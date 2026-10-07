# Motivation vs Logic
# Motivation: A length stop is a partial object and must not be spliced into the next JSON value.
# Logic: InvokeModel always sends maxOutputTokens 4096. On length, discard the message and issue a new call.

from __future__ import annotations

from dataclasses import dataclass, field

from loop.pool import map_ordered

from bedrock.limits import (
    PEGASUS_BUCKET_OWNER,
    PEGASUS_MAX_OUTPUT_TOKENS,
    PEGASUS_MODEL,
    PEGASUS_REGION,
)
from errors import SchemaRejected, TimestampOutside
from pegasus.parts import Part
from registry.check import validate_json
from registry.ids import PEGASUS, PEGASUS_CONTINUE


@dataclass(frozen=True)
class Observation:
    id: str
    statement: str
    start_ms: int
    end_ms: int
    cited: bool = True

    @property
    def can_support_claim(self) -> bool:
        return self.cited


@dataclass(frozen=True)
class VisualNote:
    id: str
    statement: str
    cited: bool = False

    @property
    def can_support_claim(self) -> bool:
        return False


@dataclass
class PegasusResult:
    observations: list[Observation] = field(default_factory=list)
    notes: list[VisualNote] = field(default_factory=list)
    incomplete: bool = False


def _vendor_schema(schema):
    # Bugs vs Fixes
    # Bug: Pegasus answers "Unprocessable video" when jsonSchema contains
    # additionalProperties, even though the MP4 itself decodes.
    # Fix: Send type, properties, required, and items only. The response is
    # still validated against the contract schema after the call returns.
    drop = {"additionalProperties", "$schema", "$id", "title", "description", "$comment"}
    if isinstance(schema, dict):
        return {key: _vendor_schema(value) for key, value in schema.items() if key not in drop}
    if isinstance(schema, list):
        return [_vendor_schema(item) for item in schema]
    return schema


def build_body(prompt_body: str, schema: dict, uri: str, *, max_output_tokens: int = PEGASUS_MAX_OUTPUT_TOKENS) -> dict:
    if max_output_tokens != PEGASUS_MAX_OUTPUT_TOKENS:
        raise ValueError(
            f"Pegasus maxOutputTokens stays at the vendor maximum {PEGASUS_MAX_OUTPUT_TOKENS}"
        )
    return {
        "inputPrompt": prompt_body,
        "mediaSource": {
            "s3Location": {
                "uri": uri,
                "bucketOwner": PEGASUS_BUCKET_OWNER,
            }
        },
        "maxOutputTokens": PEGASUS_MAX_OUTPUT_TOKENS,
        "responseFormat": {"jsonSchema": _vendor_schema(schema)},
    }


def classify_observations(data: dict, part: Part, meeting_id: str) -> tuple[list[Observation], list[VisualNote]]:
    observations: list[Observation] = []
    notes: list[VisualNote] = []
    for item in data.get("observations") or []:
        if not isinstance(item, dict):
            continue
        statement = item.get("statement") if isinstance(item.get("statement"), str) else ""
        if "start_ms" in item and "end_ms" in item:
            local_start = int(item["start_ms"])
            local_end = int(item["end_ms"])
            if local_start < 0 or local_end > part.duration_ms or local_start >= local_end:
                raise TimestampOutside(
                    f"Pegasus time {local_start}-{local_end} is outside part {part.index} ({part.duration_ms} ms)"
                )
            observations.append(
                Observation(
                    id=f"{meeting_id}-pegasus-{part.index}-{len(observations)}",
                    statement=statement,
                    start_ms=local_start + part.source_start_ms,
                    end_ms=local_end + part.source_start_ms,
                )
            )
        else:
            notes.append(
                VisualNote(
                    id=f"{meeting_id}-note-{part.index}-{len(notes)}",
                    statement=statement,
                )
            )
    for note in data.get("notes") or []:
        if isinstance(note, str):
            notes.append(VisualNote(id=f"{meeting_id}-note-{part.index}-{len(notes)}", statement=note))
    return observations, notes


def _reason(response: dict) -> str:
    return str(response.get("finishReason") or response.get("stopReason") or "stop")


class PegasusClient:
    def __init__(self, registry, transport, *, continuation_ceiling: int = 8):
        self.registry = registry
        self.transport = transport
        self.continuation_ceiling = continuation_ceiling

    def analyze(self, parts: list[Part], upload, meeting_id: str) -> PegasusResult:
        prompt = self.registry.prompt(PEGASUS)
        schema = self.registry.schema_for(PEGASUS)
        # Bugs vs Fixes
        # Bug: Scene parts waited in line, so a long meeting paid each Pegasus
        # call before the next upload started.
        # Fix: Parts run together. A length continuation stays inside its part,
        # and results are merged in part order.
        def one(part: Part) -> tuple[list[Observation], list[VisualNote], bool]:
            uri = upload(part)
            body = build_body(prompt.body, schema, uri)
            response = self._invoke(body)
            turns = 1
            while _reason(response) == "length":
                if turns > self.continuation_ceiling:
                    return [], [], True
                continuation = self.registry.prompt(PEGASUS_CONTINUE)
                body = build_body(continuation.body, schema, uri)
                response = self._invoke(body)
                turns += 1
            if _reason(response) != "stop":
                raise SchemaRejected(f"Pegasus finishReason {_reason(response)!r} is not a complete object")
            message = response.get("message")
            if not isinstance(message, str):
                raise SchemaRejected("Pegasus stop response has no JSON message")
            data = validate_json(message, schema)
            observations, notes = classify_observations(data, part, meeting_id)
            return observations, notes, False

        result = PegasusResult()
        for observations, notes, incomplete in map_ordered(one, parts):
            if incomplete:
                result.incomplete = True
                return result
            result.observations.extend(observations)
            result.notes.extend(notes)
        return result

    def _invoke(self, body: dict) -> dict:
        return self.transport.invoke(model_id=PEGASUS_MODEL, region=PEGASUS_REGION, body=body)
