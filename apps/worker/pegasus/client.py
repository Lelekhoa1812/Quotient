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


SCREEN_KINDS = ("slide", "screen_share", "diagram", "whiteboard", "document", "spreadsheet", "code", "ui", "chart", "other")
MAX_SCREEN_TEXT = 4000
MAX_SCREEN_DETAILS = 3000


@dataclass(frozen=True)
class Screen:
    """Something shown on screen: a slide, a shared window, a diagram. Text is copied as shown, details say how it is laid out."""

    id: str
    kind: str
    title: str
    text: str
    details: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class Sighting:
    """A person whose name is shown on screen over a stretch of time; speaking is true when the picture marks them as the active speaker."""

    id: str
    name: str
    speaking: bool
    cue: str
    start_ms: int
    end_ms: int


@dataclass
class PegasusResult:
    observations: list[Observation] = field(default_factory=list)
    notes: list[VisualNote] = field(default_factory=list)
    screens: list[Screen] = field(default_factory=list)
    sightings: list[Sighting] = field(default_factory=list)
    incomplete: bool = False
    # Windows whose visual analysis failed; each is reported as a note, so the meeting still completes.
    failed_windows: int = 0


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


def _span_in_part(item: dict, part: Part) -> tuple[int, int] | None:
    """A window-local time range made absolute. A small overshoot is clamped; a range that is not inside
    the window at all is dropped (the picture reading is kept only when its time can be trusted)."""
    try:
        start, end = int(item["start_ms"]), int(item["end_ms"])
    except (KeyError, TypeError, ValueError):
        return None
    slack = 3000
    if end <= start or start < -slack or start >= part.duration_ms or end > part.duration_ms + slack:
        return None
    start, end = max(0, start), min(part.duration_ms, end)
    if end <= start:
        return None
    return start + part.source_start_ms, end + part.source_start_ms


def _text(value: object, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def classify_screens(data: dict, part: Part, meeting_id: str) -> tuple[list[Screen], list[Sighting]]:
    screens: list[Screen] = []
    for item in data.get("screens") or []:
        if not isinstance(item, dict):
            continue
        when = _span_in_part(item, part)
        text, details, title = _text(item.get("text"), MAX_SCREEN_TEXT), _text(item.get("details"), MAX_SCREEN_DETAILS), _text(item.get("title"), 200)
        if when is None or not (text or details or title):
            continue
        kind = _text(item.get("kind"), 40).lower().replace(" ", "_").replace("-", "_")
        screens.append(
            Screen(
                id=f"{meeting_id}-screen-{part.index}-{len(screens)}",
                kind=kind if kind in SCREEN_KINDS else "other",
                title=title,
                text=text,
                details=details,
                start_ms=when[0],
                end_ms=when[1],
            )
        )
    sightings: list[Sighting] = []
    for item in data.get("people") or []:
        if not isinstance(item, dict):
            continue
        when = _span_in_part(item, part)
        name = _text(item.get("name"), 120)
        if when is None or not name:
            continue
        cue = _text(item.get("cue"), 20).lower()
        sightings.append(
            Sighting(
                id=f"{meeting_id}-sight-{part.index}-{len(sightings)}",
                name=name,
                speaking=item.get("speaking") is True,
                cue=cue if cue in {"label", "highlight", "caption"} else "other",
                start_ms=when[0],
                end_ms=when[1],
            )
        )
    return screens, sightings


def _reason(response: dict) -> str:
    return str(response.get("finishReason") or response.get("stopReason") or "stop")


class PegasusClient:
    def __init__(self, registry, transport, *, continuation_ceiling: int = 8, strict: bool = False):
        self.registry = registry
        self.transport = transport
        self.continuation_ceiling = continuation_ceiling
        # strict: a window that fails raises (the old behaviour), instead of becoming a note.
        self.strict = strict

    def analyze(self, parts: list[Part], upload, meeting_id: str) -> PegasusResult:
        prompt = self.registry.prompt(PEGASUS)
        schema = self.registry.schema_for(PEGASUS)
        # Bugs vs Fixes
        # Bug: Scene parts waited in line, so a long meeting paid each Pegasus
        # call before the next upload started.
        # Fix: Parts run together. A length continuation stays inside its part,
        # and results are merged in part order.
        # Bug: One window that Pegasus could not read (an unprocessable clip, a timestamp
        # outside the window) failed the whole meeting, though the speech was fine.
        # Fix: A failed window becomes a note and the other windows still count. The
        # error is kept only as its class name, never copied into the note.
        def one(part: Part):
            try:
                uri = upload(part)
                body = build_body(prompt.body, schema, uri)
                response = self._invoke(body)
                turns = 1
                while _reason(response) == "length":
                    if turns > self.continuation_ceiling:
                        return [], [], [], [], True, False
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
                screens, sightings = classify_screens(data, part, meeting_id)
                return observations, notes, screens, sightings, False, False
            except (SchemaRejected, TimestampOutside, RuntimeError, TimeoutError, OSError) as exc:
                if self.strict:
                    raise
                note = VisualNote(
                    id=f"{meeting_id}-note-{part.index}-failed",
                    statement=(
                        f"Visual analysis of {part.source_start_ms // 60000}:{part.source_start_ms // 1000 % 60:02d} to "
                        f"{part.source_end_ms // 60000}:{part.source_end_ms // 1000 % 60:02d} was not available ({type(exc).__name__})."
                    ),
                )
                return [], [note], [], [], False, True

        result = PegasusResult()
        for observations, notes, screens, sightings, incomplete, failed in map_ordered(one, parts):
            if incomplete:
                result.incomplete = True
                return result
            result.observations.extend(observations)
            result.notes.extend(notes)
            result.screens.extend(screens)
            result.sightings.extend(sightings)
            result.failed_windows += 1 if failed else 0
        return result

    def _invoke(self, body: dict) -> dict:
        return self.transport.invoke(model_id=PEGASUS_MODEL, region=PEGASUS_REGION, body=body)
