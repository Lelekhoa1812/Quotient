# Motivation vs Logic
# Motivation: The MCP process must enqueue a meeting and read its projection without
# hosting claim extraction, entailment, or a burned-video renderer.
# Logic: load_port() returns a subject-scoped ledger. run_quality delegates to
# loop.quality.run. classify_media delegates to media.probe. export_bytes returns
# burned.mp4 only after store_export has recorded those bytes. A non-empty review
# queue stays needs_review; a brief that cites that queue is a failed publish.

from __future__ import annotations

import copy
import secrets
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

_ARTIFACT_KEYS = (
    "ledger",
    "claims",
    "counterevidence",
    "entailment",
    "coverage",
    "exports",
)


class PortError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _raise(code: str, message: str) -> None:
    """Raise the API PortError when this module was loaded by the MCP process."""

    module = sys.modules.get("quotient.worker.port")
    error_type = getattr(module, "PortError", None) if module is not None else None
    if isinstance(error_type, type) and issubclass(error_type, Exception):
        raise error_type(code, message)
    raise PortError(code, message)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pending() -> dict[str, str]:
    return {key: "pending" for key in _ARTIFACT_KEYS}


def _relation(status: object) -> str:
    if status == "supported":
        return "entails"
    if status == "contradicted":
        return "contradicts"
    return "mentions"


def _span_row(span: object) -> dict:
    if isinstance(span, dict):
        return copy.deepcopy(span)
    return {
        "span_id": span.id,
        "meeting_id": span.meeting_id,
        "kind": span.kind,
        "start_ms": span.start_ms,
        "end_ms": span.end_ms,
        "raw_text": span.raw_text,
        "text": span.text,
        "coarse": bool(span.coarse),
        "overlap": bool(span.overlap),
        "session_id": getattr(span, "session_id", None),
        "speaker_hypothesis_id": getattr(span, "speaker_hypothesis_id", None),
    }


# Motivation vs Logic
# Motivation: raw_transcript.video is the Pegasus statements in time order. The API
# can join them only when the meeting row keeps those observation records.
# Logic: Copy id, statement, and source times off the ledger. Do not call a model.
def _observation_row(observation: object) -> dict:
    if isinstance(observation, dict):
        return copy.deepcopy(observation)
    return {
        "id": getattr(observation, "id", None),
        "statement": getattr(observation, "statement", ""),
        "start_ms": getattr(observation, "start_ms", None),
        "end_ms": getattr(observation, "end_ms", None),
    }


def _claim_row(claim: object) -> dict:
    if isinstance(claim, dict):
        return copy.deepcopy(claim)
    citation = {
        "quote": claim.quote,
        "span_id": claim.span_id,
        "relation": _relation(claim.status),
        "start_ms": claim.start_ms,
        "end_ms": claim.end_ms,
    }
    if claim.char_start is not None and claim.char_end is not None:
        citation["char_start"] = claim.char_start
        citation["char_end"] = claim.char_end
    citations = [citation] if claim.quote and claim.span_id else []
    origin = claim.origin if claim.origin in {"model", "human"} else "model"
    return {
        "claim_id": claim.id,
        "kind": claim.kind,
        "status": claim.status,
        "text": claim.proposition,
        "decision_status": claim.decision_status,
        "origin": origin,
        "coarse": bool(claim.coarse),
        "overlap": bool(claim.overlap),
        "citations": citations,
    }


def _finding_row(finding: object) -> dict:
    if isinstance(finding, dict):
        return copy.deepcopy(finding)
    return {
        "finding_id": finding.id,
        "dimension": finding.dimension,
        "stance": finding.stance,
        "text": finding.text,
        "claim_ids": list(finding.claim_ids),
    }


def _sentence_row(sentence: object, index: int) -> dict:
    if isinstance(sentence, dict):
        row = copy.deepcopy(sentence)
        row.setdefault("sentence_id", f"y{index}")
        return row
    return {
        "sentence_id": f"y{index}",
        "text": sentence.text,
        "finding_ids": list(sentence.finding_ids),
    }


def _action_row(action: object, index: int, anchor_date: str | None) -> dict:
    if isinstance(action, dict):
        row = copy.deepcopy(action)
        row.setdefault("action_id", f"a{index}")
        return row
    due_kind = action.due_kind if action.due_kind in {"absolute", "relative", "none"} else "none"
    return {
        "action_id": f"a{index}",
        "statement": action.statement,
        "owner_span_id": action.owner_span_id,
        "agreement_span_id": action.agreement_span_id,
        "due_kind": due_kind,
        "due_surface": action.due_surface,
        "due_date": action.due_iso,
        "due_span_id": action.due_span_id,
        "anchor_date": anchor_date if due_kind == "relative" else None,
        "claim_ids": list(action.claim_ids),
        "origin": action.origin if action.origin in {"model", "human"} else "model",
        "acceptance": action.acceptance if action.acceptance in {"proposed", "accepted"} else "proposed",
    }


def _record(item: object, fields: tuple[str, ...]) -> dict:
    if isinstance(item, dict):
        return copy.deepcopy(item)
    return {name: getattr(item, name) for name in fields}


def _public_failure(exc: BaseException) -> str:
    detail = str(exc).replace("\n", " ").strip()
    if not detail or "AKIA" in detail or "Bearer " in detail or "AWS_BEDROCK" in detail:
        detail = ""
    text = type(exc).__name__ if not detail else f"{type(exc).__name__}: {detail}"
    return text[:180]


def _worker_charts(result, ledger) -> list:
    """Copy worker table rows. The API stores this list and does not recompute it."""

    from chart.sandbox import portal_charts

    spans = []
    for span in getattr(ledger, "spans", []) or []:
        spans.append(
            {
                "id": span.id,
                "kind": span.kind,
                "start_ms": int(span.start_ms),
                "end_ms": int(span.end_ms),
                "speaker_hypothesis_id": span.speaker_hypothesis_id or "unassigned",
                "overlap": bool(span.overlap),
            }
        )
    claims = []
    for claim in result.claims:
        status = claim.status if isinstance(getattr(claim, "status", None), str) and claim.status else "unresolved"
        claims.append({"id": claim.id, "status": status})
    findings = [
        {"id": finding.id, "dimension": finding.dimension}
        for finding in result.findings
        if isinstance(getattr(finding, "dimension", None), str) and finding.dimension
    ]
    actions = []
    for index, action in enumerate(result.actions):
        acceptance = action.acceptance if action.acceptance in {"proposed", "accepted"} else "proposed"
        actions.append({"id": f"a{index}", "acceptance": acceptance})
    cells = ledger.cells if isinstance(getattr(ledger, "cells", None), dict) else {}
    return portal_charts(
        {"spans": spans, "claims": claims, "findings": findings, "actions": actions, "cells": cells}
    )


def _refuse_queued_brief(result: object) -> None:
    brief = getattr(result, "brief", None)
    queue = set(getattr(result, "review_queue", None) or [])
    if not isinstance(brief, dict) or not queue:
        return
    published = set(brief.get("claim_ids") or [])
    if published & queue:
        raise RuntimeError("a queued claim entered the brief")


class Port:
    """Ledger the MCP server calls. Analysis stays in loop.quality.run."""

    def __init__(self, quality_run, checkpoints, classify_file, model_plan) -> None:
        self._quality_run = quality_run
        self._checkpoints = checkpoints
        self._classify_file = classify_file
        self._model_plan = model_plan
        self._lock = threading.Lock()
        self._rows: dict[str, dict] = {}
        self._idempotency: dict[tuple[str, str], str] = {}
        self._exports: dict[tuple[str, str], tuple[str, bytes]] = {}

    def submit(
        self,
        *,
        subject: str,
        object_key: str,
        context_names: tuple[str, ...],
        idempotency_key: str | None,
    ) -> str:
        with self._lock:
            if idempotency_key:
                existing = self._idempotency.get((subject, idempotency_key))
                if existing:
                    return existing
            meeting_id = secrets.token_urlsafe(12)
            self._rows[meeting_id] = {
                "meeting_id": meeting_id,
                "subject": subject,
                "object_key": object_key,
                "context_names": list(context_names),
                "idempotency_key": idempotency_key,
                "status": "queued",
                "prompt_release": None,
                "failure_message": None,
                "updated_at": _now(),
                "artifacts": _pending(),
                "spans": [],
                "claims": [],
                "findings": [],
                "synthesis": [],
                "actions": [],
                "disagreements": [],
                "omissions": [],
                "none_in_transcript": [],
                "observations": [],
                "revisions": [],
            }
            if idempotency_key:
                self._idempotency[(subject, idempotency_key)] = meeting_id
        # Bugs vs Fixes
        # Bug: submit stored a queued row and returned. Nothing called Sonic,
        # Pegasus, or the publish gate, so tasks/get stayed queued.
        # Fix: Start one daemon thread per new meeting. It resolves the object
        # key, runs the ledger, then projects the gate. A second idempotent
        # submit does not start another thread.
        threading.Thread(
            target=self._analyze,
            args=(meeting_id,),
            name="quotient-analysis",
            daemon=True,
        ).start()
        return meeting_id

    def _analyze(self, meeting_id: str) -> None:
        try:
            with self._lock:
                row = self._rows.get(meeting_id)
                if row is None or row["status"] in {"cancelled", "failed"}:
                    return
                object_key = row["object_key"]
                names = tuple(
                    name for name in row.get("context_names") or [] if isinstance(name, str) and name.strip()
                )
                row["status"] = "working"
                row["updated_at"] = _now()
            self._run_meeting(meeting_id, object_key, names)
        except Exception as exc:
            self._fail(meeting_id, _public_failure(exc))

    def _run_meeting(self, meeting_id: str, object_key: str, names: tuple[str, ...]) -> None:
        from bedrock.reason import Reasoner
        from bedrock.wire import Transport
        from loop.ingest import LIVE_CEILING, assemble, resolve_object
        from registry.load import Registry

        path = resolve_object(object_key)
        ledger = assemble(path, meeting_id, context=", ".join(names) if names else None)
        registry = Registry()
        reasoner = Reasoner(registry, Transport())
        print("analysis stage: quality", file=sys.stderr, flush=True)
        self.run_quality(ledger, reasoner, registry, iteration_ceiling=LIVE_CEILING)
        for item in reasoner.fallback_log:
            print(
                "sol fallback: "
                f"model_id={item.get('model_id')} error_code={item.get('error_code')} fallback={item.get('fallback')}",
                file=sys.stderr,
                flush=True,
            )

    def meeting(self, meeting_id: str, subject: str) -> dict | None:
        with self._lock:
            row = self._rows.get(meeting_id)
            if row is None or row["subject"] != subject:
                return None
            return copy.deepcopy(row)

    def list_meetings(self, subject: str) -> list[dict]:
        with self._lock:
            rows = [row for row in self._rows.values() if row["subject"] == subject]
            rows.sort(key=lambda row: row["meeting_id"])
            return [copy.deepcopy(row) for row in rows]

    def accept_action(self, meeting_id: str, subject: str, action_id: str) -> dict:
        with self._lock:
            row = self._owned(meeting_id, subject)
            for action in row["actions"]:
                if action.get("action_id") != action_id:
                    continue
                acceptance = action.get("acceptance")
                if acceptance == "accepted":
                    row["updated_at"] = _now()
                    return copy.deepcopy(row)
                if acceptance != "proposed":
                    _raise("conflict", "Only a proposed action can be accepted.")
                action["acceptance"] = "accepted"
                action["origin"] = action.get("origin") or "model"
                row["updated_at"] = _now()
                return copy.deepcopy(row)
            _raise("not_found", "Action not found.")

    def revise_speaker(
        self,
        meeting_id: str,
        subject: str,
        span_id: str,
        scope: str,
        display_name: str,
    ) -> dict:
        with self._lock:
            row = self._owned(meeting_id, subject)
            anchor = next((span for span in row["spans"] if span.get("span_id") == span_id), None)
            if anchor is None:
                _raise("not_found", "Span not found.")
            hypothesis = anchor.get("speaker_hypothesis_id")
            if scope == "hypothesis":
                targets = [
                    span
                    for span in row["spans"]
                    if span.get("speaker_hypothesis_id") == hypothesis and hypothesis
                ]
                if not targets:
                    targets = [anchor]
            else:
                targets = [anchor]
                anchor["speaker_hypothesis_id"] = "hyp_" + secrets.token_urlsafe(8)
            for span in targets:
                span["speaker_display"] = display_name
            row["revisions"].append(
                {
                    "span_id": span_id,
                    "scope": scope,
                    "display_name": display_name,
                    "at": _now(),
                }
            )
            row["status"] = "working"
            for key in ("claims", "counterevidence", "entailment", "coverage", "exports"):
                row["artifacts"][key] = "pending"
            row["updated_at"] = _now()
            return copy.deepcopy(row)

    def cancel(self, meeting_id: str, subject: str) -> dict:
        with self._lock:
            row = self._owned(meeting_id, subject)
            row["status"] = "cancelled"
            row["updated_at"] = _now()
            return copy.deepcopy(row)

    def export_bytes(self, meeting_id: str, subject: str, name: str) -> tuple[str, bytes] | None:
        with self._lock:
            row = self._rows.get(meeting_id)
            if row is None or row["subject"] != subject:
                return None
            stored = self._exports.get((meeting_id, name))
            if stored is None:
                return None
            mime, body = stored
            return mime, bytes(body)

    def store_export(self, meeting_id: str, subject: str, name: str, mime: str, body: bytes) -> None:
        """Record bytes a worker renderer already produced. Empty bodies are ignored."""

        if not isinstance(body, (bytes, bytearray)) or len(body) == 0:
            return
        with self._lock:
            row = self._owned(meeting_id, subject)
            self._exports[(meeting_id, name)] = (mime, bytes(body))
            if name == "burned.mp4":
                row["artifacts"]["exports"] = "ready"
                row["updated_at"] = _now()

    def classify_media(self, path: str | Path) -> dict:
        """Media entrypoint: ffprobe kind plus the model plan. Extensions are not used."""

        kind = self._classify_file(path)
        return {"kind": kind, "models": tuple(sorted(self._model_plan(kind)))}

    def run_quality(self, ledger, model, registry, key: str | None = None, *, iteration_ceiling: int = 32):
        """Quality entrypoint. Calls loop.quality.run and stores its gate result."""

        meeting_id = getattr(ledger, "meeting_id", None)
        with self._lock:
            row = self._rows.get(meeting_id) if isinstance(meeting_id, str) else None
            if row is not None and row["status"] not in {"cancelled", "failed"}:
                row["status"] = "working"
                row["updated_at"] = _now()
            checkpoint = key or (row or {}).get("idempotency_key") or meeting_id or ""
        try:
            result = self._quality_run(
                ledger,
                model,
                registry,
                self._checkpoints,
                str(checkpoint),
                iteration_ceiling=iteration_ceiling,
            )
        except RuntimeError as exc:
            if "queued claim" in str(exc):
                self._fail(meeting_id, "A queued claim entered the brief.")
            raise
        try:
            _refuse_queued_brief(result)
        except RuntimeError as exc:
            if "queued claim" in str(exc):
                self._fail(meeting_id, "A queued claim entered the brief.")
            raise
        with self._lock:
            self._project(result, ledger)
        return result

    def _fail(self, meeting_id: object, message: str) -> None:
        if not isinstance(meeting_id, str):
            return
        with self._lock:
            row = self._rows.get(meeting_id)
            if row is None or row["status"] == "cancelled":
                return
            row["status"] = "failed"
            row["failure_message"] = message
            row["updated_at"] = _now()

    def _project(self, result, ledger) -> None:
        meeting_id = getattr(ledger, "meeting_id", None)
        if not isinstance(meeting_id, str):
            return
        row = self._rows.get(meeting_id)
        if row is None or row["status"] == "cancelled":
            return
        displays = {
            span.get("span_id"): span.get("speaker_display")
            for span in row["spans"]
            if isinstance(span, dict) and span.get("speaker_display")
        }
        spans = [_span_row(span) for span in getattr(ledger, "spans", []) or []]
        for span in spans:
            display = displays.get(span.get("span_id"))
            if display and not span.get("speaker_display"):
                span["speaker_display"] = display
        anchor = getattr(ledger, "anchor_date", None)
        row["status"] = result.status
        row["failure_message"] = None
        row["prompt_release"] = result.prompt_release
        row["spans"] = spans
        row["observations"] = [
            _observation_row(item) for item in getattr(ledger, "observations", []) or []
        ]
        row["observations"].extend(
            _observation_row(item) for item in getattr(ledger, "notes", []) or []
        )
        row["claims"] = [_claim_row(claim) for claim in result.claims]
        row["findings"] = [_finding_row(finding) for finding in result.findings]
        row["synthesis"] = [_sentence_row(sentence, index) for index, sentence in enumerate(result.synthesis)]
        row["actions"] = [
            _action_row(action, index, anchor if isinstance(anchor, str) else None)
            for index, action in enumerate(result.actions)
        ]
        row["disagreements"] = [
            _record(item, ("sonic_span_id", "observation_id", "statement")) for item in result.disagreements
        ]
        row["omissions"] = [_record(item, ("span_id", "reason")) for item in result.omissions]
        dimensions = result.dimensions if isinstance(result.dimensions, dict) else {}
        row["none_in_transcript"] = [
            name for name, value in dimensions.items() if value == "none_in_transcript"
        ]
        row["synthesis_omissions"] = [
            _record(item, ("finding_id", "reason")) for item in getattr(result, "synthesis_omissions", []) or []
        ]
        row["charts"] = _worker_charts(result, ledger)
        artifacts = dict(result.artifacts) if isinstance(result.artifacts, dict) else {}
        for key in _ARTIFACT_KEYS:
            artifacts.setdefault(key, "pending")
        if (meeting_id, "burned.mp4") in self._exports:
            artifacts["exports"] = "ready"
        row["artifacts"] = artifacts
        row["updated_at"] = _now()

    def _owned(self, meeting_id: str, subject: str) -> dict:
        row = self._rows.get(meeting_id)
        if row is None or row["subject"] != subject:
            _raise("not_found", "Meeting not found.")
        return row


def _load_entrypoints():
    root = str(Path(__file__).resolve().parents[1])
    inserted = root not in sys.path
    if inserted:
        sys.path.insert(0, root)
    try:
        from loop.quality import run as quality_run
        from loop.store import MemoryStore
        from media.probe import classify_file, model_plan
    finally:
        if inserted and sys.path and sys.path[0] == root:
            sys.path.pop(0)
    return quality_run, MemoryStore(), classify_file, model_plan


def load_port() -> Port:
    quality_run, checkpoints, classify_file, model_plan = _load_entrypoints()
    return Port(quality_run, checkpoints, classify_file, model_plan)
