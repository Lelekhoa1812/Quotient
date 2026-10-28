# Motivation vs Logic
# Motivation: The MCP process must enqueue a meeting and read its projection without
# hosting claim extraction, entailment, or a burned-video renderer.
# Logic: load_port() returns a subject-scoped ledger. run_quality delegates to
# loop.quality.run. classify_media delegates to media.probe. export_bytes returns
# burned.mp4 only after store_export has recorded those bytes. A non-empty review
# queue stays needs_review; a brief that cites that queue is a failed publish.

from __future__ import annotations

import copy
import hashlib
import importlib.util
import shutil
import json
import os
import queue
import secrets
import subprocess
import sys
import tempfile
import threading
import time
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


MAX_RESUMES = 2


CONTEXT_BATCH_SECONDS = 6 * 3600
CONTEXT_BATCHES_PER_SUBJECT = 20


class PortError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# Portal uploads are stored under this prefix; the key is minted by upload_target, never the client.
UPLOAD_PREFIX = "uploads/"


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


SCREEN_ROWS = 300


def _screen_row(screen: object) -> dict:
    if isinstance(screen, dict):
        return copy.deepcopy(screen)
    return {
        "id": getattr(screen, "id", None),
        "kind": getattr(screen, "kind", "other"),
        "title": getattr(screen, "title", ""),
        "text": getattr(screen, "text", ""),
        "details": getattr(screen, "details", ""),
        "start_ms": getattr(screen, "start_ms", None),
        "end_ms": getattr(screen, "end_ms", None),
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
        "confidence": getattr(claim, "confidence", None) or ("confirmed" if claim.status == "supported" else "unverified"),
        "text": claim.proposition,
        "decision_status": claim.decision_status,
        "origin": origin,
        "coarse": bool(claim.coarse),
        "overlap": bool(claim.overlap),
        "citations": citations,
        # Diagnostics for tuning. Ledger only: the API projection does not copy this key.
        "verdict": {
            "sol": getattr(claim, "sol_label", None),
            "luna": getattr(claim, "luna_label", None),
            "searched": len(getattr(claim, "searched_ids", None) or []),
            "opened": len(getattr(claim, "opened_ids", None) or []),
            "search_matches_open": bool(getattr(claim, "searched_ids", None))
            and set(claim.searched_ids) == set(getattr(claim, "opened_ids", None) or []),
            "quote_resolved": bool(claim.span_id),
            "contradiction": bool(getattr(claim, "contradicting_quote", None)),
        },
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


def _restore_claim(raw: dict) -> object:
    from graph.state import Claim
    citations = raw.get("citations") or []
    c = citations[0] if citations else {}
    return Claim(
        id=raw.get("claim_id", ""),
        meeting_id="",
        kind=raw.get("kind", "factual"),
        proposition=raw.get("text", ""),
        paraphrase=raw.get("text", ""),
        quote=c.get("quote", ""),
        span_id=c.get("span_id"),
        char_start=c.get("char_start"),
        char_end=c.get("char_end"),
        start_ms=c.get("start_ms"),
        end_ms=c.get("end_ms"),
        status=raw.get("status", "unresolved"),
        decision_status=raw.get("decision_status"),
        origin=raw.get("origin", "model"),
        coarse=bool(raw.get("coarse")),
        overlap=bool(raw.get("overlap")),
        confidence=raw.get("confidence", "unverified"),
    )


def _restore_finding(raw: dict) -> object:
    from graph.state import Finding
    return Finding(
        id=raw.get("finding_id", ""),
        dimension=raw.get("dimension", ""),
        stance=raw.get("stance", "supported"),
        claim_ids=list(raw.get("claim_ids") or []),
        text=raw.get("text", ""),
    )


def _restore_sentence(raw: dict) -> object:
    from graph.state import Sentence
    return Sentence(
        text=raw.get("text", ""),
        finding_ids=list(raw.get("finding_ids") or []),
    )


# Motivation vs Logic
# Motivation: failure_message is shown to people and returned to MCP clients. It used to be
# "<ExceptionType>: <raw message>", which exposed local file paths and ffprobe command
# lines for an unreadable file, and provider request ids for a rejected call.
# Logic: Known failures map to one plain sentence. Unknown failures say only that the
# analysis could not finish. The full exception goes to the server log (stderr), never
# to the row. The sentences are matched by the portal's friendlyError as well.
def _public_failure(exc: BaseException) -> str:
    import subprocess

    detail = str(exc).replace("\n", " ").strip()
    print(f"analysis failed: {type(exc).__name__}: {detail[:400]}", file=sys.stderr, flush=True)
    lowered = detail.lower()
    if type(exc).__name__ == "NoSpeech":
        return "No speech could be transcribed from this recording. Check that it has clear audio and try again."
    if type(exc).__name__ == "NoAudioTrack":
        return "This recording has no audio, so there is nothing to transcribe."
    if isinstance(exc, subprocess.TimeoutExpired):
        return "The analysis took too long and was stopped. Please try again."
    if isinstance(exc, FileNotFoundError):
        return "The recording could not be found."
    if isinstance(exc, subprocess.CalledProcessError) and any(
        str(part).endswith(("ffprobe", "ffmpeg")) or str(part) in {"ffprobe", "ffmpeg"} for part in (exc.cmd or [])[:1]
    ):
        return "This file is not a readable audio or video recording."
    if "http 403" in lowered or "http 401" in lowered or "check the configured aws identity" in lowered:
        return "The analysis service did not accept this computer's sign-in. Sign in to AWS again, then start the analysis again."
    if "content filter" in lowered:
        return "The analysis service declined this recording."
    if "timed out" in lowered or isinstance(exc, TimeoutError):
        return "The analysis took too long and was stopped. Please try again."
    return "The analysis could not be completed. Please try again."


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


def _object_exists(bucket: str, key: str, endpoint: str, env: dict | None) -> bool:
    try:
        result = subprocess.run(
            ["aws", "s3api", "head-object", "--bucket", bucket, "--key", key, "--endpoint-url", endpoint, "--no-cli-pager"],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            env=env,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


class Port:
    """Ledger the MCP server calls. Analysis stays in loop.quality.run."""

    def __init__(
        self,
        quality_run,
        checkpoints,
        classify_file,
        model_plan,
        state_path: Path | None = None,
        *,
        resume_interrupted: bool = False,
    ) -> None:
        self._quality_run = quality_run
        self._checkpoints = checkpoints
        self._classify_file = classify_file
        self._model_plan = model_plan
        self._lock = threading.Lock()
        self._rows: dict[str, dict] = {}
        self._idempotency: dict[tuple[str, str], str] = {}
        self._context_batches: dict[str, dict] = {}
        self._exports: dict[tuple[str, str], tuple[str, bytes]] = {}
        self._state_path = state_path
        self._lock_file = self._claim_store(state_path)
        resume_ids = []
        if state_path is not None and state_path.exists():
            # Refuse, never repair: this file is rewritten whole on every save, so reading a damaged or differently shaped one as
            # "empty" would silently erase every meeting in it. The file is left exactly as found.
            where = f"The local meeting file {state_path}"
            try:
                payload = json.loads(state_path.read_text(encoding="utf-8"))
            except ValueError as exc:
                raise ValueError(f"{where} is not valid JSON ({exc}). Repair it, or move it aside to start with no meetings.") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"{where} must be a JSON object with a meetings list, not {type(payload).__name__}. It was left unchanged.")
            rows = payload.get("meetings", [])
            if not isinstance(rows, list):
                raise ValueError(f"{where} has an invalid meetings collection. It was left unchanged.")
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get("meeting_id"), str):
                    raise ValueError(f"{where} contains a row that is not a meeting object with a meeting_id. It was left unchanged.")
                if row.get("status") in {"queued", "working"}:
                    # Bugs vs Fixes
                    # Bug: Every restart re-queued every unfinished row with no limit, so a
                    # recording that crashed the process was re-run (and re-billed) forever.
                    # Fix: Count restarts per row; after MAX_RESUMES the row fails with a plain reason.
                    resumes = int(row.get("resumes") or 0)
                    if resume_interrupted and resumes >= MAX_RESUMES:
                        row["status"] = "failed"
                        row["failure_message"] = "The analysis was interrupted too many times. Please upload the recording again."
                    elif resume_interrupted:
                        row["resumes"] = resumes + 1
                        row["status"] = "queued"
                        row["failure_message"] = None
                        row["progress_message"] = "Restarting analysis from the source after the local app restarted"
                        resume_ids.append(row["meeting_id"])
                    else:
                        row["status"] = "failed"
                        row["failure_message"] = "Local worker restarted before analysis finished; resubmit this meeting."
                    row["updated_at"] = _now()
                artifacts = row.get("artifacts")
                if isinstance(artifacts, dict) and artifacts.get("exports") == "ready":
                    # Export bytes are intentionally not copied into the meeting
                    # JSON state file; don't advertise an unavailable render.
                    artifacts["exports"] = "not_run"
                self._rows[row["meeting_id"]] = row
                idem = row.get("idempotency_key")
                if isinstance(idem, str):
                    self._idempotency[(str(row.get("subject", "")), idem)] = row["meeting_id"]
            self._save_locked()
        self._work_queue: queue.Queue[str] = queue.Queue()
        self._active_analysis: str | None = None
        self._worker_thread = threading.Thread(
            target=self._queue_worker,
            args=(),
            daemon=True,
            name="quotient-analysis-worker",
        )
        self._worker_thread.start()
        self._remote_save_lock = threading.Lock()
        self._remote_write_lock = threading.Lock()
        self._remote_save_event = threading.Event()
        self._pending_remote_save: dict | None = None
        self._remote_save_thread: threading.Thread | None = None
        self._stopping_remote_saver = False
        artifacts_bucket = os.environ.get("ARTIFACTS_BUCKET", "").strip()
        is_local = os.environ.get("QUOTIENT_ENVIRONMENT", "").strip().lower() == "local"
        self._remote_storage_enabled = bool(artifacts_bucket) and not is_local

        if self._remote_storage_enabled:
            self._remote_save_thread = threading.Thread(
                target=self._remote_saver_loop,
                args=(),
                daemon=True,
                name="quotient-s3-saver",
            )
            self._remote_save_thread.start()
        for meeting_id in resume_ids:
            self._enqueue_analysis(meeting_id)

    @staticmethod
    def _claim_store(state_path: Path | None):
        """One process owns the meeting store. Two writers would each rewrite the whole file from their own
        memory, and both would re-run the same interrupted meetings. The lock goes when the process does."""
        if state_path is None:
            return None
        import fcntl

        state_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(state_path.with_name(state_path.name + ".lock"), "w")
        try:
            fcntl.lockf(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)  # per process: a restart in the same process is fine
        except OSError:
            handle.close()
            raise RuntimeError("Another Quotient process is already using this meeting store. Stop it first.") from None
        return handle

    def _remote_saver_loop(self) -> None:
        while not self._stopping_remote_saver:
            triggered = self._remote_save_event.wait(timeout=1.0)
            if not triggered and not self._stopping_remote_saver:
                continue
            self._remote_save_event.clear()
            self._drain_remote()

    def flush_storage(self, timeout: float = 30.0) -> None:
        # Bugs vs Fixes
        # Bug: Flush took the pending document and returned while the saver
        # thread could still put an older copy. The Lambda handler then froze,
        # so the newer meeting row never reached the bucket.
        # Fix: One drain holds the write lock and puts until the pending slot
        # is empty, so the last document is the one stored.
        del timeout
        self._drain_remote()

    def _drain_remote(self) -> None:
        if not getattr(self, "_remote_storage_enabled", False):
            return
        write_lock = getattr(self, "_remote_write_lock", None)
        if write_lock is None:
            return
        with write_lock:
            while True:
                with self._remote_save_lock:
                    payload = self._pending_remote_save
                    self._pending_remote_save = None
                if payload is None:
                    return
                try:
                    mod = _seed_module()
                    if mod is not None:
                        mod.save_remote_state(payload)
                except Exception as exc:
                    print(f"remote state save error: {exc}", file=sys.stderr, flush=True)

    def _save_locked(self) -> None:
        payload = {"version": 1, "meetings": list(self._rows.values())}
        if self._state_path is not None:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            # default=str: one unexpected value (an enum, a Path) must not make every later save raise.
            encoded = json.dumps(payload, ensure_ascii=False, default=str)
            fd, temporary = tempfile.mkstemp(prefix="meetings-", suffix=".json", dir=self._state_path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self._state_path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)

        if getattr(self, "_remote_storage_enabled", False):
            with self._remote_save_lock:
                self._pending_remote_save = payload
            self._remote_save_event.set()

    def _set_progress(self, meeting_id: str, message: str) -> None:
        with self._lock:
            row = self._rows.get(meeting_id)
            if row is None or row.get("status") in {"cancelled", "failed"} or _reindex_stopped(row) or row.get("progress_message") == message:
                return
            row["progress_message"] = message
            row["updated_at"] = _now()
            self._save_locked()

    def submit(
        self,
        *,
        subject: str,
        object_key: str,
        context_names: tuple[str, ...],
        idempotency_key: str | None,
        context_batch: str | None = None,
        purpose: str | None = None,
    ) -> str:
        with self._lock:
            if idempotency_key:
                existing = self._idempotency.get((subject, idempotency_key))
                # A retry after a failure or a cancellation is a new attempt, not a request for the dead one.
                if existing and self._rows.get(existing, {}).get("status") not in {"failed", "cancelled"}:
                    return existing
            if context_batch:
                self._prune_batches()
                record = self._context_batches.get(context_batch)
                if not record or record["subject"] != subject:
                    # Starting without the documents the person added would be a silent downgrade.
                    _raise("not_found", "The context you added was not found. Add it again and start the analysis.")
            context = self._context_for(subject, context_batch, purpose)
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
                "review_queue": [],
                "findings": [],
                "synthesis": [],
                "actions": [],
                "disagreements": [],
                "omissions": [],
                "gaps": [],
                "none_in_transcript": [],
                "not_evaluated": [],
                "digest": None,
                "observations": [],
                "revisions": [],
            }
            if context:
                self._rows[meeting_id]["context"] = context
            try:
                self._save_locked()
            except Exception:
                # Not stored means not submitted: a retry must start fresh, not be handed an id that never ran.
                del self._rows[meeting_id]
                raise
            if idempotency_key:
                self._idempotency[(subject, idempotency_key)] = meeting_id
        # Queue for sequential background analysis so multiple concurrent jobs never saturate Fargate CPU/memory.
        self._enqueue_analysis(meeting_id)
        return meeting_id

    def prepare_context(self, subject: str, files: list[dict]) -> dict | None:
        """Signed upload targets for reference files. The keys are minted here under context/<batch>/."""
        from media import storage

        if len(files) > storage.CONTEXT_MAX_FILES:
            _raise("invalid", f"At most {storage.CONTEXT_MAX_FILES} context files can be added.")
        total = 0
        for entry in files:
            if not storage.context_allowed(entry.get("filename")):
                _raise("invalid", f"{str(entry.get('filename'))[:60]} is not a supported type. Use PDF, Word, PowerPoint, Excel, CSV, JSON, HTML, XML, EPUB, Markdown or text.")
            size = entry.get("byte_size")
            if isinstance(size, int):
                if size > storage.CONTEXT_MAX_FILE_BYTES:
                    _raise("invalid", f"{str(entry.get('filename'))[:60]} is larger than 25 MB.")
                total += size
        if total > storage.CONTEXT_MAX_TOTAL_BYTES:
            _raise("invalid", "The context is over 100 MB in total.")
        batch_id = secrets.token_urlsafe(12)
        uploads, items = [], []
        try:
            for index, entry in enumerate(files):
                key = storage.context_key(batch_id, index, entry.get("filename"))
                content_type = storage.base_media_type(entry.get("media_type")) or "application/octet-stream"
                url = storage.presign_put(key, content_type)
                uploads.append({"index": index, "filename": entry["filename"], "upload_url": url, "method": "PUT",
                                "headers": {"Content-Type": content_type}, "object_key": key})
                items.append({"name": str(entry["filename"])[:160], "key": key, "bytes": size if isinstance((size := entry.get("byte_size")), int) else None})
        except storage.StorageUnavailable:
            return None
        with self._lock:
            self._prune_batches()
            mine = sorted((rec["at"], key) for key, rec in self._context_batches.items() if rec["subject"] == subject)
            for _at, key in mine[: max(0, len(mine) - (CONTEXT_BATCHES_PER_SUBJECT - 1))]:
                del self._context_batches[key]  # the oldest unused batches make room: they are only reservations
            self._context_batches[batch_id] = {"subject": subject, "items": items, "at": time.time()}
        return {"batch_id": batch_id, "uploads": uploads}

    def _prune_batches(self) -> None:
        now = time.time()
        for stale in [key for key, rec in self._context_batches.items() if now - rec["at"] > CONTEXT_BATCH_SECONDS]:
            del self._context_batches[stale]

    def context_items(self, subject: str, batch_id: str) -> list[dict] | None:
        with self._lock:
            self._prune_batches()
            record = self._context_batches.get(batch_id)
            return copy.deepcopy(record["items"]) if record and record["subject"] == subject else None

    def _context_for(self, subject: str, batch_id: str | None, purpose: str | None) -> dict | None:
        """The context block a new meeting row carries; called with the lock held."""
        record = self._context_batches.get(batch_id) if batch_id else None
        items = []
        if record and record["subject"] == subject:
            del self._context_batches[batch_id]  # one batch belongs to one meeting; a second submit must upload again
            for position, item in enumerate(record["items"], start=1):
                items.append({"id": f"i{position}", "name": item["name"], "key": item["key"], "bytes": item.get("bytes"),
                              "status": "pending", "reason": None, "chars": None, "summary": None})
        text = (purpose or "").strip()[:2000]
        return {"purpose": text or None, "items": items} if (items or text) else None

    def _load_context(self, meeting_id: str):
        """Turn the meeting's uploaded reference files into a library the agents can read. Never raises."""
        try:
            from context.loader import load_library

            with self._lock:
                row = self._rows.get(meeting_id)
                block = copy.deepcopy(row.get("context")) if row else None
            if not block:
                return None
            self._set_progress(meeting_id, "Reading the context documents")
            cache = os.environ.get("QUOTIENT_CONTEXT_CACHE_DIR", "").strip()
            if not cache and os.environ.get("QUOTIENT_ENVIRONMENT", "").strip().lower() == "local":
                cache = str(Path(__file__).resolve().parents[3] / ".local" / "run" / "context")
            library, items = load_library(
                block.get("items") or [],
                block.get("purpose") or "",
                cache_dir=Path(cache) if cache else None,
                scope=hashlib.sha256(str(self._subject_of(meeting_id) or "").encode()).hexdigest()[:16],
            )
            with self._lock:
                row = self._rows.get(meeting_id)
                if row is not None:
                    row["context"] = {**block, "items": items}
                    self._save_locked()
            print(f"context: {len(library.docs)} of {len(items)} documents ready", file=sys.stderr, flush=True)
            return library if library else None
        except Exception as exc:  # reference material is an aid; the analysis does not depend on it
            print(f"context skipped: {type(exc).__name__}", file=sys.stderr, flush=True)
            self._mark_context_unread(meeting_id)
            return None

    def _mark_context_unread(self, meeting_id: str) -> None:
        """Say on the row that the documents were not read, so nobody assumes the analysis used them."""
        try:
            with self._lock:
                row = self._rows.get(meeting_id)
                block = row.get("context") if row else None
                if not isinstance(block, dict):
                    return
                for item in block.get("items") or []:
                    if isinstance(item, dict) and item.get("status") != "ready":
                        item["status"], item["reason"] = "failed", "The documents could not be read, so this analysis ran without them."
                self._save_locked()
        except Exception:
            pass

    def _enqueue_analysis(self, meeting_id: str) -> None:
        """Enqueue a meeting for sequential background analysis so concurrent jobs never saturate compute."""
        with self._lock:
            if self._active_analysis is not None and self._active_analysis != meeting_id:
                row = self._rows.get(meeting_id)
                if row and row.get("status") == "queued":
                    row["progress_message"] = "Queued: waiting for active analysis to finish"
                    self._save_locked()
        queue_url = os.environ.get("WORK_QUEUE_URL", "").strip()
        if queue_url:
            try:
                import botocore.session
                from bedrock.wire import iam_credentials
                session = botocore.session.get_session()
                creds = iam_credentials()
                kwargs = {"region_name": os.environ.get("AWS_REGION") or "ap-southeast-2"}
                if creds is not None:
                    kwargs["aws_access_key_id"] = creds.access_key
                    kwargs["aws_secret_access_key"] = creds.secret_key
                    kwargs["aws_session_token"] = creds.token
                sqs = session.create_client("sqs", **kwargs)
                sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps({"meeting_id": meeting_id}))
                print(f"enqueued meeting {meeting_id} to SQS {queue_url}", file=sys.stderr, flush=True)
                return
            except Exception as exc:
                print(f"failed to enqueue to SQS: {exc}; falling back to local thread", file=sys.stderr, flush=True)
        self._work_queue.put(meeting_id)

    def _queue_worker(self) -> None:
        """Single-task background worker: processes meetings one at a time to preserve system stability."""
        while True:
            meeting_id = self._work_queue.get()
            try:
                with self._lock:
                    self._active_analysis = meeting_id
                self._analyze(meeting_id)
            except Exception as exc:
                print(f"analysis queue worker error for {meeting_id}: {exc}", file=sys.stderr, flush=True)
            finally:
                with self._lock:
                    if self._active_analysis == meeting_id:
                        self._active_analysis = None
                self._work_queue.task_done()

    def _analyze(self, meeting_id: str) -> None:
        try:
            with self._lock:
                row = self._rows.get(meeting_id)
                if row is None or row["status"] in {"cancelled", "failed"} or _reindex_stopped(row):
                    return
                object_key = row["object_key"]
                names = tuple(
                    name for name in row.get("context_names") or [] if isinstance(name, str) and name.strip()
                )
                reindex = bool(row.get("reindexing"))
                row["status"] = "working"
                if reindex:
                    row["progress_message"] = "Reindexing identities"
                row["updated_at"] = _now()
                self._save_locked()
            self._run_meeting(meeting_id, object_key, names, reindex=reindex)
        except Exception as exc:
            message = _public_failure(exc)
            if not self._restore_after_reindex(meeting_id, message):
                self._fail(meeting_id, message)

    def _restore_after_reindex(self, meeting_id: str, message: str) -> bool:
        """A reindex that fails leaves the meeting as it was: the brief it already had is not lost to a retry."""
        with self._lock:
            row = self._rows.get(meeting_id)
            if row is None or not row.get("reindexing"):
                return False
            row["reindexing"] = False
            if row["status"] != "cancelled":
                row["status"] = row.pop("previous_status", None) or "needs_review"
                row["progress_message"] = "Reindex did not finish; the earlier analysis is kept."
            row["reindex_error"] = message
            row["updated_at"] = _now()
            self._save_locked()
            return True

    def reindex(self, meeting_id: str, subject: str) -> dict:
        """Run the analysis again on the same recording so a name a person has since given (or a voice they
        merged) reaches the whole analysis. Transcript, voices and the visual scan are replayed from the
        local cache when they are there; the language-model stages run again."""
        with self._lock:
            row = self._owned(meeting_id, subject)
            if row.get("reindexing") and row.get("status") in {"queued", "working"}:
                return copy.deepcopy(row)
            if row["status"] in {"queued", "working"}:
                _raise("conflict", "The analysis is still running.")
            if row["status"] == "cancelled":
                _raise("conflict", "This meeting was stopped. Upload the recording again.")
            row["previous_status"] = row["status"]
            row["reindexing"] = True
            row["reindex_error"] = None
            row["reindex_count"] = int(row.get("reindex_count") or 0) + 1
            row["status"] = "queued"
            row["progress_message"] = "Reindexing identities"
            row["updated_at"] = _now()
            self._save_locked()
            result = copy.deepcopy(row)
        self._enqueue_analysis(meeting_id)
        return result

    def _find_cached_turns(self, meeting_id: str, row: dict, spans: list) -> list[tuple[int, int, str]]:
        duration_ms = max((s.end_ms for s in spans if s.end_ms is not None), default=0)
        candidates = [
            Path("/tmp/quotient/artifacts"),
            Path(__file__).resolve().parents[3] / "cache" / "artifacts",
        ]
        for cdir in candidates:
            if not cdir.is_dir():
                continue
            for file_path in cdir.glob("*.json"):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, list) and data and isinstance(data[0], list) and len(data[0]) == 3:
                        if isinstance(data[0][2], str) and data[0][2].startswith("spk_"):
                            max_turn = max(item[1] for item in data)
                            if abs(max_turn - duration_ms) <= 15000:
                                return [tuple(item) for item in data]
                except Exception:
                    continue
        return []

    def _reconstruct_ledger(self, meeting_id: str, row: dict):
        from graph.span import Span
        from loop.quality import Ledger
        from visual.frames import Screen

        row_spans = row.get("spans") or []
        spans = []
        for idx, s in enumerate(row_spans):
            if not isinstance(s, dict):
                continue
            s_id = s.get("span_id") or s.get("id") or f"{meeting_id}-span-{idx}"
            s_mid = s.get("meeting_id") or meeting_id
            s_kind = s.get("kind") or "speech"
            s_start = s.get("start_ms") if s.get("start_ms") is not None else 0
            s_end = s.get("end_ms") if s.get("end_ms") is not None else 0
            spans.append(
                Span(
                    id=s_id,
                    meeting_id=s_mid,
                    kind=s_kind,
                    start_ms=s_start,
                    end_ms=s_end,
                    raw_text=s.get("raw_text", ""),
                    text=s.get("text", s.get("raw_text", "")),
                    coarse=bool(s.get("coarse")),
                    session_id=s.get("session_id"),
                    speaker_hypothesis_id=s.get("speaker_hypothesis_id"),
                    overlap=bool(s.get("overlap")),
                )
            )

        turns = [tuple(t) for t in (row.get("turns") or [])]
        if not turns:
            turns = self._find_cached_turns(meeting_id, row, spans)

        if any(s.speaker_hypothesis_id is None for s in spans if s.kind == "speech") and turns:
            from media.diarize import attach_speakers
            attach_speakers(spans, turns)

        duration_ms = max((s.end_ms for s in spans if s.end_ms is not None), default=0)
        screens = [
            Screen(
                id=sc.get("id") or f"{meeting_id}-screen-{s_idx}",
                kind=sc.get("kind", "other"),
                title=sc.get("title", ""),
                text=sc.get("text", ""),
                details=sc.get("details", ""),
                start_ms=sc.get("start_ms", 0),
                end_ms=sc.get("end_ms", 0),
            )
            for s_idx, sc in enumerate(row.get("screens") or [])
            if isinstance(sc, dict)
        ]
        observations = row.get("observations") or []
        ledger = Ledger(
            meeting_id=meeting_id,
            duration_ms=duration_ms,
            kind="video" if screens or observations else "audio",
            spans=spans,
            screens=screens,
            observations=observations,
            turns=turns,
        )
        ledger.context = self._load_context(meeting_id)
        return ledger

    def _run_meeting(self, meeting_id: str, object_key: str, names: tuple[str, ...], reindex: bool = False) -> None:
        from bedrock.reason import Reasoner
        from bedrock.wire import Transport
        from loop.ingest import assemble, open_source
        from registry.load import Registry

        ledger = None
        if reindex:
            with self._lock:
                row = self._rows.get(meeting_id) or {}
                row_spans = row.get("spans")
            if row_spans:
                self._set_progress(meeting_id, "Reindexing identity provenance")
                try:
                    ledger = self._reconstruct_ledger(meeting_id, row)
                except Exception as exc:
                    print(f"ledger reconstruction fallback: {exc}", file=sys.stderr, flush=True)
                    ledger = None

        if ledger is None:
            self._set_progress(meeting_id, "Preparing the media and building the transcript")
            # A file that is not on this disk is copied from the media bucket into a
            # private directory that is removed whatever happens next.
            path, scratch = open_source(object_key)
            if scratch is not None:
                self._set_progress(meeting_id, "Fetching the recording")
            try:
                ledger = assemble(
                    path,
                    meeting_id,
                    context=", ".join(names) if names else None,
                    progress_callback=lambda message: self._set_progress(meeting_id, message),
                    should_stop=lambda: self._is_cancelled(meeting_id),
                    cache_scope=self._subject_of(meeting_id),
                )
            finally:
                if scratch is not None:
                    shutil.rmtree(scratch, ignore_errors=True)
            ledger.context = self._load_context(meeting_id)
        self._apply_identity_state(meeting_id, ledger)
        registry = Registry()
        reasoner = Reasoner(registry, Transport())
        print("analysis stage: quality", file=sys.stderr, flush=True)
        existing_data = None
        if reindex:
            with self._lock:
                row = self._rows.get(meeting_id) or {}
                raw_claims = row.get("claims")
                raw_findings = row.get("findings")
                if raw_claims and raw_findings:
                    none_set = set(row.get("none_in_transcript") or [])
                    not_eval_set = set(row.get("not_evaluated") or [])
                    existing_data = {
                        "claims": raw_claims,
                        "findings": raw_findings,
                        "synthesis": row.get("synthesis"),
                        "omissions": row.get("omissions"),
                        "gaps": row.get("gaps"),
                        "disagreements": row.get("disagreements"),
                        "dimensions": {
                            name: "none_in_transcript"
                            for name in none_set
                        } | {
                            name: "not_evaluated"
                            for name in not_eval_set
                        },
                    }
        self.run_quality(
            ledger,
            reasoner,
            registry,
            # A reindex has to run the analysis again, so it gets a checkpoint key of its own.
            f"{self._subject_of(meeting_id)}:{meeting_id}:{self._reindex_count(meeting_id)}" if reindex else None,
            stage_callback=lambda message: self._set_progress(meeting_id, message),
            should_stop=lambda: self._is_cancelled(meeting_id),
            reindex_data=existing_data,
        )
        for item in reasoner.fallback_log:
            print(
                "sol fallback: "
                f"model_id={item.get('model_id')} error_code={item.get('error_code')} fallback={item.get('fallback')}",
                file=sys.stderr,
                flush=True,
            )

    def _reindex_count(self, meeting_id: str) -> int:
        with self._lock:
            row = self._rows.get(meeting_id)
            return int((row or {}).get("reindex_count") or 0)

    def _apply_identity_state(self, meeting_id: str, ledger) -> None:
        """What a person decided about voices outranks a fresh run: merges are replayed on the new voice ids,
        and the names they typed and the names the picture gave are handed to the analysis."""
        with self._lock:
            row = self._rows.get(meeting_id) or {}
            merges = dict(row.get("speaker_merges") or {})
            locked = dict(row.get("speaker_names") or {})
        resolve = lambda voice: _final_voice(merges, voice)
        for span in getattr(ledger, "spans", []) or []:
            voice = getattr(span, "speaker_hypothesis_id", None)
            if voice and resolve(voice) != voice:
                span.speaker_hypothesis_id = resolve(voice)
        known: dict[str, str] = {}
        for identity in getattr(ledger, "visual_identities", []) or []:
            voice = resolve(identity.speaker)
            known.setdefault(voice, identity.name)
        for voice, item in (row.get("identities") or {}).items():
            if isinstance(item, dict) and item.get("name"):
                known.setdefault(resolve(voice), item["name"])
        known.update({resolve(voice): name for voice, name in locked.items() if isinstance(name, str) and name.strip()})
        ledger.known_names = known

    def meeting(self, meeting_id: str, subject: str) -> dict | None:
        self._pull_remote(meeting_id)
        with self._lock:
            row = self._rows.get(meeting_id)
            if row is None or row["subject"] != subject:
                return None
            return copy.deepcopy(row)

    def _pull_remote(self, meeting_id: str) -> None:
        # Bugs vs Fixes
        # Bug: Submit stores the meeting in the API process. The worker, a
        # different process, writes the finished row to the artifacts object.
        # The API kept polling its queued copy, so a finished job stayed queued.
        # Fix: While the local row is queued or working, adopt the stored row
        # when its updated_at is later. This read does not write the object back.
        if not getattr(self, "_remote_storage_enabled", False):
            return
        with self._lock:
            local = self._rows.get(meeting_id)
            if local is None or local.get("status") not in {"queued", "working"}:
                return
        module = _seed_module()
        if module is None:
            return
        try:
            document, _source = module.read_state_or_seed()
        except Exception as exc:
            print(f"remote meeting read error: {exc}", file=sys.stderr, flush=True)
            return
        rows = document.get("meetings") if isinstance(document, dict) else None
        if not isinstance(rows, list):
            return
        remote = next(
            (row for row in rows if isinstance(row, dict) and row.get("meeting_id") == meeting_id),
            None,
        )
        if remote is None:
            return
        with self._lock:
            local = self._rows.get(meeting_id)
            if local is None or local.get("status") not in {"queued", "working"}:
                return
            if str(remote.get("updated_at") or "") <= str(local.get("updated_at") or ""):
                return
            if remote.get("subject") != local.get("subject"):
                return
            self._rows[meeting_id] = copy.deepcopy(remote)

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
                    self._save_locked()
                    return copy.deepcopy(row)
                if acceptance != "proposed":
                    _raise("conflict", "Only a proposed action can be accepted.")
                action["acceptance"] = "accepted"
                action["origin"] = action.get("origin") or "model"
                row["updated_at"] = _now()
                self._save_locked()
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
            if scope == "hypothesis" and hypothesis:
                from identity.resolve import same_person
                names = row.setdefault("speaker_names", {})
                existing_match = None
                for other_hyp, other_name in list(names.items()):
                    if other_hyp != hypothesis and same_person(other_name, display_name):
                        existing_match = other_hyp
                        break
                if not existing_match and "identities" in row and isinstance(row["identities"], dict):
                    for other_hyp, other_ident in list(row["identities"].items()):
                        if other_hyp != hypothesis and isinstance(other_ident, dict):
                            if same_person(other_ident.get("name", ""), display_name):
                                existing_match = other_hyp
                                break

                if existing_match:
                    keep, gone = existing_match, hypothesis
                    for s in row["spans"]:
                        if s.get("speaker_hypothesis_id") == gone:
                            s["speaker_hypothesis_id"] = keep
                        if s.get("speaker_hypothesis_id") == keep:
                            s["speaker_display"] = display_name
                    names.pop(gone, None)
                    names[keep] = display_name
                    merges = row.setdefault("speaker_merges", {})
                    for earlier, target in list(merges.items()):
                        if target == gone:
                            merges[earlier] = keep
                    if gone != keep:
                        merges[gone] = keep
                    if "digest" in row and isinstance(row["digest"], dict):
                        d = row["digest"]
                        d_spks = d.get("speakers")
                        if isinstance(d_spks, list):
                            for spk in d_spks:
                                if isinstance(spk, dict) and spk.get("id") == gone:
                                    spk["id"] = keep
                                    spk["name"] = display_name
                            seen_spk_ids = set()
                            deduped = []
                            for spk in d_spks:
                                if isinstance(spk, dict) and spk.get("id"):
                                    if spk["id"] not in seen_spk_ids:
                                        seen_spk_ids.add(spk["id"])
                                        deduped.append(spk)
                            d["speakers"] = deduped
                        for p in d.get("perspectives") or []:
                            if isinstance(p, dict) and p.get("speaker") == gone:
                                p["speaker"] = keep
                        for dec in d.get("decisions") or []:
                            if isinstance(dec, dict) and dec.get("decided_by") == gone:
                                dec["decided_by"] = keep
                    if "identities" in row and isinstance(row["identities"], dict):
                        identities = row["identities"]
                        target_ident = identities.setdefault(keep, {
                            "name": display_name,
                            "source": "user",
                            "confidence": 1.0,
                            "conflict": None,
                            "merged": [],
                        })
                        target_ident["name"] = display_name
                        target_ident["source"] = "user"
                        merged_list = target_ident.setdefault("merged", [])
                        if gone not in merged_list:
                            merged_list.append(gone)
                        if gone in identities:
                            for m in identities[gone].get("merged", []):
                                if m not in merged_list and m != keep:
                                    merged_list.append(m)
                            identities.pop(gone, None)
                else:
                    # Locked: a name a person gave a voice survives any later analysis of the recording.
                    names[hypothesis] = display_name
                    if "identities" in row and isinstance(row["identities"], dict):
                        target_ident = row["identities"].setdefault(hypothesis, {
                            "name": display_name,
                            "source": "user",
                            "confidence": 1.0,
                            "conflict": None,
                            "merged": [],
                        })
                        target_ident["name"] = display_name
                        target_ident["source"] = "user"
            row.setdefault("revisions", []).append(
                {
                    "span_id": span_id,
                    "scope": scope,
                    "display_name": display_name,
                    "at": _now(),
                }
            )
            # The analysis was written before this name existed, so it is stale until a reindex.
            row["identity_revision"] = int(row.get("identity_revision") or 0) + 1
            # Speaker labels are a presentation edit; no analysis rerun is queued.
            row["updated_at"] = _now()
            self._save_locked()
            return copy.deepcopy(row)

    def merge_speakers(
        self,
        meeting_id: str,
        subject: str,
        span_id: str,
        other_span_id: str,
        display_name: str,
    ) -> dict:
        with self._lock:
            row = self._owned(meeting_id, subject)
            anchor = next((span for span in row["spans"] if span.get("span_id") == span_id), None)
            other = next((span for span in row["spans"] if span.get("span_id") == other_span_id), None)
            if anchor is None or other is None:
                _raise("not_found", "Span not found.")
            keep = anchor.get("speaker_hypothesis_id")
            gone = other.get("speaker_hypothesis_id")
            if not keep or not gone:
                _raise("conflict", "Both lines need a speaker to be merged.")
            # One voice from here on: every line of the other voice moves to the anchor's voice and takes its name.
            for span in row["spans"]:
                if span.get("speaker_hypothesis_id") == gone:
                    span["speaker_hypothesis_id"] = keep
                if span.get("speaker_hypothesis_id") == keep:
                    span["speaker_display"] = display_name
            names = row.setdefault("speaker_names", {})
            names.pop(gone, None)
            names[keep] = display_name
            # Remembered by voice id so that a fresh analysis of the same recording (same ids) merges them again.
            merges = row.setdefault("speaker_merges", {})
            for earlier, target in list(merges.items()):
                if target == gone:
                    merges[earlier] = keep
            if gone != keep:
                merges[gone] = keep

            # Update row['identities'] so portals immediately reflect merged identities
            if "identities" in row and isinstance(row["identities"], dict):
                identities = row["identities"]
                target_ident = identities.setdefault(keep, {
                    "name": display_name,
                    "source": "user",
                    "confidence": 1.0,
                    "conflict": None,
                    "merged": [],
                })
                target_ident["name"] = display_name
                target_ident["source"] = "user"
                merged_list = target_ident.setdefault("merged", [])
                if gone not in merged_list:
                    merged_list.append(gone)
                if gone in identities:
                    for m in identities[gone].get("merged", []):
                        if m not in merged_list and m != keep:
                            merged_list.append(m)
                    identities.pop(gone, None)

            # Update row['digest']['speakers'] so digest consistency is maintained
            if "digest" in row and isinstance(row["digest"], dict):
                d_speakers = row["digest"].get("speakers")
                if isinstance(d_speakers, list):
                    for spk in d_speakers:
                        if isinstance(spk, dict) and spk.get("id") == gone:
                            spk["id"] = keep
                            spk["name"] = display_name
                    seen_spk_ids = set()
                    deduped = []
                    for spk in d_speakers:
                        if isinstance(spk, dict) and spk.get("id"):
                            if spk["id"] not in seen_spk_ids:
                                seen_spk_ids.add(spk["id"])
                                deduped.append(spk)
                    row["digest"]["speakers"] = deduped
                for p in row["digest"].get("perspectives") or []:
                    if isinstance(p, dict) and p.get("speaker") == gone:
                        p["speaker"] = keep
                for dec in row["digest"].get("decisions") or []:
                    if isinstance(dec, dict) and dec.get("decided_by") == gone:
                        dec["decided_by"] = keep

            row["identity_revision"] = int(row.get("identity_revision") or 0) + 1
            row.setdefault("revisions", []).append(
                {
                    "span_id": span_id,
                    "scope": "merge",
                    "display_name": display_name,
                    "merged_from": gone,
                    "at": _now(),
                }
            )
            row["updated_at"] = _now()
            self._save_locked()
            return copy.deepcopy(row)

    def revise_text(self, meeting_id: str, subject: str, span_id: str, text: str) -> dict:
        with self._lock:
            row = self._owned(meeting_id, subject)
            span = next((item for item in row["spans"] if item.get("span_id") == span_id), None)
            if span is None:
                _raise("not_found", "Span not found.")
            span["text"] = text
            _record_text_edit(row, span_id, text)
            row["updated_at"] = _now()
            self._save_locked()
            return copy.deepcopy(row)

    def cancel(self, meeting_id: str, subject: str) -> dict:
        with self._lock:
            row = self._owned(meeting_id, subject)
            if row["status"] in {"ready", "needs_review", "failed"}:
                # A finished meeting is not "stopped": cancelling it would hide the brief it already produced.
                _raise("conflict", "This meeting has already finished.")
            if row.get("reindexing"):
                # Stopping a reindex keeps the analysis the meeting already had.
                row["reindexing"] = False
                row["reindex_stopped_run"] = int(row.get("reindex_count") or 0)
                row["status"] = row.pop("previous_status", None) or "needs_review"
                row["progress_message"] = "Reindex stopped; the earlier analysis is kept."
                row["updated_at"] = _now()
                self._save_locked()
                return copy.deepcopy(row)
            row["status"] = "cancelled"
            row["progress_message"] = "Stopped before it finished."
            row["updated_at"] = _now()
            self._save_locked()
            return copy.deepcopy(row)

    def rename_meeting(self, meeting_id: str, subject: str, title: str) -> dict:
        with self._lock:
            row = self._owned(meeting_id, subject)
            cleaned = title.strip()
            row["title"] = cleaned
            row["updated_at"] = _now()
            if isinstance(row.get("digest"), dict):
                row["digest"]["title"] = cleaned
            self._save_locked()
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

    def upload_target(self, task_id: str, filename: str | None, media_type: str | None, byte_size: object) -> dict | None:
        """A signed PUT for one browser upload, or None when object storage is not configured."""
        from media import storage

        if not storage.media_type_allowed(media_type):
            _raise("invalid", "Only audio or video recordings can be uploaded.")
        if isinstance(byte_size, str) and byte_size.strip().isdigit():
            byte_size = int(byte_size)
        if isinstance(byte_size, int) and not isinstance(byte_size, bool) and byte_size > storage.MAX_UPLOAD_BYTES:
            _raise("invalid", "The recording is larger than 5 GB.")
        key = storage.upload_key(task_id, filename)
        content_type = storage.base_media_type(media_type)  # the signed header and the browser's PUT must agree
        try:
            url = storage.presign_put(key, content_type)
        except storage.StorageUnavailable:
            return None
        return {"upload_url": url, "method": "PUT", "headers": {"Content-Type": content_type}, "object_key": key}

    def uploaded_object(self, key: str) -> dict | None:
        """Size and type of an uploaded object (None when it is missing)."""
        from media import storage

        return storage.head(key)

    def media_url(self, meeting_id: str, subject: str) -> str | None:
        """Return a short-lived URL for the submitted source, scoped to its owner."""
        with self._lock:
            row = self._rows.get(meeting_id)
            if row is None or row["subject"] != subject:
                return None
            key = row.get("object_key")
            # A client chooses object_key. Sign it only once this meeting has ingested media of its
            # own; a failed or queued submission naming someone else's key gets no URL.
            if row.get("status") not in {"ready", "needs_review"} and not row.get("spans"):
                return None
        if not isinstance(key, str) or not key.startswith(("derivatives/", UPLOAD_PREFIX)):
            return None
        bucket = os.environ.get("QUOTIENT_MEDIA_BUCKET", "").strip()
        if not bucket:
            if os.environ.get("QUOTIENT_ENVIRONMENT", "").strip().lower() != "local":
                return None
            bucket = "axion-meeting-local"
        endpoint = os.environ.get("QUOTIENT_S3_ENDPOINT_URL", "").strip()
        env = None
        if endpoint:
            env = os.environ.copy()
            access = env.get("QUOTIENT_S3_ACCESS_KEY_ID", "")
            secret = env.get("QUOTIENT_S3_SECRET_ACCESS_KEY", "")
            if bool(access) != bool(secret):
                return None
            if access:
                env["AWS_ACCESS_KEY_ID"] = access
                env["AWS_SECRET_ACCESS_KEY"] = secret
                env.pop("AWS_SESSION_TOKEN", None)
            # Bugs vs Fixes
            # Bug: In local S3 mode the worker reads the source from disk and uploads a
            # playback copy to derivatives/<meeting_id>-0.mp4, but this URL was signed for
            # the submitted object_key, which is not in the bucket. Every recording
            # processed from disk was unplayable (403/404, MEDIA_ERR_SRC_NOT_SUPPORTED).
            # Fix: With a local endpoint, sign the per-meeting upload when it exists and
            # fall back to the submitted key. Without an endpoint (AWS) the key is unchanged.
            own = f"derivatives/{meeting_id}-0.mp4"
            if own != key and _object_exists(bucket, own, endpoint, env):
                key = own
        command = ["aws", "s3", "presign", f"s3://{bucket}/{key}", "--expires-in", "3600"]
        if endpoint:
            command.extend(["--endpoint-url", endpoint])
        try:
            result = subprocess.run(command, capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return None
        url = result.stdout.strip()
        if result.returncode or not url.startswith(("http://", "https://")):
            return None
        return url

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
            self._save_locked()

    def classify_media(self, path: str | Path) -> dict:
        """Media entrypoint: ffprobe kind plus the model plan. Extensions are not used."""

        kind = self._classify_file(path)
        return {"kind": kind, "models": tuple(sorted(self._model_plan(kind)))}

    def run_quality(
        self,
        ledger,
        model,
        registry,
        key: str | None = None,
        *,
        iteration_ceiling: int | None = None,
        stage_callback=None,
        should_stop=None,
        reindex_data: dict | None = None,
    ):
        """Quality entrypoint. Calls loop.quality.run and stores its gate result."""

        meeting_id = getattr(ledger, "meeting_id", None)
        with self._lock:
            row = self._rows.get(meeting_id) if isinstance(meeting_id, str) else None
            if row is not None and row["status"] not in {"cancelled", "failed"}:
                row["status"] = "working"
                row["updated_at"] = _now()
                self._save_locked()
            # Bugs vs Fixes
            # Bug: The checkpoint store is process-wide and was keyed by the raw client
            # idempotency key, so two subjects using the same key shared one cached analysis
            # (one could read the other's claims, findings, and brief).
            # Fix: Scope the checkpoint by subject. The API already scopes idempotency per subject.
            subject = (row or {}).get("subject") or ""
            checkpoint = f"{subject}\u0000{key or (row or {}).get('idempotency_key') or meeting_id or ''}"

        existing_kwargs = {}
        if reindex_data:
            from graph.state import Gap, Omission

            raw_claims = reindex_data.get("claims") or []
            raw_findings = reindex_data.get("findings") or []
            if raw_claims and raw_findings:
                restored_findings = [_restore_finding(f) for f in raw_findings]
                from graph.lenses import LENS_ORDER
                findings_by_dim: dict[str, list] = {}
                for f in restored_findings:
                    findings_by_dim.setdefault(f.dimension, []).append(f)

                raw_dims = reindex_data.get("dimensions") or {}
                dims: dict[str, object] = {}
                for name in LENS_ORDER:
                    if raw_dims.get(name) in ("none_in_transcript", "not_evaluated"):
                        dims[name] = raw_dims[name]
                    elif name in findings_by_dim:
                        dims[name] = findings_by_dim[name]
                    else:
                        dims[name] = "none_in_transcript"

                existing_kwargs = {
                    "existing_claims": [_restore_claim(c) for c in raw_claims],
                    "existing_findings": restored_findings,
                    "existing_synthesis": [_restore_sentence(s) for s in (reindex_data.get("synthesis") or [])],
                    "existing_omissions": [
                        Omission(span_id=o["span_id"], reason=o.get("reason", ""))
                        for o in (reindex_data.get("omissions") or [])
                        if isinstance(o, dict) and "span_id" in o
                    ],
                    "existing_gaps": [
                        Gap(span_ids=g.get("span_ids", []), reason=g.get("reason", ""))
                        for g in (reindex_data.get("gaps") or [])
                        if isinstance(g, dict)
                    ],
                    "existing_disagreements": reindex_data.get("disagreements") or [],
                    "existing_dimensions": dims,
                }
        try:
            result = self._quality_run(
                ledger,
                model,
                registry,
                self._checkpoints,
                str(checkpoint),
                iteration_ceiling=iteration_ceiling,
                stage_callback=stage_callback,
                should_stop=should_stop,
                **existing_kwargs,
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
            self._project(result, ledger, reasoner=model, registry=registry)
        return result

    def _subject_of(self, meeting_id: str) -> str:
        with self._lock:
            row = self._rows.get(meeting_id)
            return str(row["subject"]) if row and row.get("subject") else ""

    def _is_cancelled(self, meeting_id: str) -> bool:
        with self._lock:
            row = self._rows.get(meeting_id)
            return row is None or row["status"] == "cancelled" or _reindex_stopped(row)

    def _fail(self, meeting_id: object, message: str) -> None:
        if not isinstance(meeting_id, str):
            return
        with self._lock:
            row = self._rows.get(meeting_id)
            if row is None or row["status"] == "cancelled" or _reindex_stopped(row):
                return
            row["status"] = "failed"
            row["failure_message"] = message
            row["updated_at"] = _now()
            self._save_locked()

    def _project(self, result, ledger, reasoner: object | None = None, registry: object | None = None) -> None:
        meeting_id = getattr(ledger, "meeting_id", None)
        if not isinstance(meeting_id, str):
            return
        row = self._rows.get(meeting_id)
        if row is None or row["status"] == "cancelled" or _reindex_stopped(row):
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
        apply_locked_names(row, spans)
        apply_text_edits(row, spans)
        anchor = getattr(ledger, "anchor_date", None)
        row["status"] = result.status
        row["progress_message"] = (
            "Analysis complete; this meeting needs review."
            if result.status == "needs_review"
            else "Analysis complete."
        )
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
        row["review_queue"] = [
            claim_id for claim_id in getattr(result, "review_queue", []) if isinstance(claim_id, str)
        ]
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
        row["gaps"] = [_record(item, ("span_ids", "reason")) for item in getattr(result, "gaps", []) or []]
        dimensions = result.dimensions if isinstance(result.dimensions, dict) else {}
        row["none_in_transcript"] = [
            name for name, value in dimensions.items() if value == "none_in_transcript"
        ]
        row["not_evaluated"] = [name for name, value in dimensions.items() if value == "not_evaluated"]
        row["synthesis_omissions"] = [
            _record(item, ("finding_id", "reason")) for item in getattr(result, "synthesis_omissions", []) or []
        ]
        row["charts"] = _worker_charts(result, ledger)
        digest = getattr(result, "digest", None)
        row["digest"] = digest if isinstance(digest, dict) else None
        self._project_identity(row, ledger, row["digest"], reasoner=reasoner, registry=registry)
        row["reindexing"] = False
        row["reindex_error"] = None
        row.pop("previous_status", None)
        artifacts = dict(result.artifacts) if isinstance(result.artifacts, dict) else {}
        for key in _ARTIFACT_KEYS:
            artifacts.setdefault(key, "pending")
        if (meeting_id, "burned.mp4") in self._exports:
            artifacts["exports"] = "ready"
        row["artifacts"] = artifacts
        row["updated_at"] = _now()
        self._save_locked()

    def _project_identity(
        self,
        row: dict,
        ledger,
        digest,
        reasoner: object | None = None,
        registry: object | None = None,
    ) -> None:
        """Who is who after this analysis, and what the picture showed. The names a person typed stay in
        speaker_names; this is the machine's answer, kept apart so the portal can tell them apart."""
        from identity.resolve import fuse_identities_model

        merges = dict(row.get("speaker_merges") or {})
        intervals = getattr(ledger, "turns", None) or []
        spans = row.get("spans") or getattr(ledger, "spans", []) or []
        sightings = getattr(ledger, "sightings", []) or []
        locked = {voice: name for voice, name in (row.get("speaker_names") or {}).items() if isinstance(name, str) and name.strip()}
        digest_speakers = (digest or {}).get("speakers") or []

        final, new_merges = fuse_identities_model(
            spans=spans,
            sightings=sightings,
            intervals=intervals,
            locked_names=locked,
            digest_speakers=digest_speakers,
            reasoner=reasoner,
            registry=registry,
        )

        if new_merges:
            for keep, other in new_merges:
                merges[other] = keep
                for span in row.get("spans") or []:
                    if span.get("speaker_hypothesis_id") == other:
                        span["speaker_hypothesis_id"] = keep
                        if span.get("speaker_display") and keep in final:
                            span["speaker_display"] = final[keep].name
            if digest and isinstance(digest, dict):
                for p in digest.get("perspectives") or []:
                    if isinstance(p, dict) and p.get("speaker") in merges:
                        p["speaker"] = merges[p["speaker"]]
                for q in digest.get("decisions") or []:
                    if isinstance(q, dict) and q.get("decided_by") in merges:
                        q["decided_by"] = merges[q["decided_by"]]
            row["speaker_merges"] = merges
        row["identities"] = {
            voice: {
                "name": item.name,
                "source": item.source,
                "confidence": item.confidence,
                "conflict": item.conflict,
                "merged": list(item.merged),
            }
            for voice, item in sorted(final.items())
            if voice not in merges
        }
        row["screens"] = [_screen_row(item) for item in (getattr(ledger, "screens", None) or [])][:SCREEN_ROWS]
        row["turns"] = [list(t) for t in (getattr(ledger, "turns", None) or [])]
        row["visual"] = {
            "screens": len(getattr(ledger, "screens", None) or []),
            "sightings": len(getattr(ledger, "sightings", None) or []),
            "named_from_picture": len([item for item in final.values() if "visual" in item.source]),
        }
        # Everything the person decided so far is now in the analysis.
        row["analysed_identity_revision"] = int(row.get("identity_revision") or 0)

    def _owned(self, meeting_id: str, subject: str) -> dict:
        row = self._rows.get(meeting_id)
        if row is None or row["subject"] != subject:
            _raise("not_found", "Meeting not found.")
        return row


MAX_REVISIONS = 5000


def _reindex_stopped(row: dict) -> bool:
    """True once a person stopped the reindex that is (still) running on this row."""
    count = int(row.get("reindex_count") or 0)
    return count > 0 and row.get("reindex_stopped_run") == count and not row.get("reindexing")


def _final_voice(merges: dict, voice: str) -> str:
    """Follow merge links to the voice that was kept (a chain is possible, a loop is not trusted)."""
    seen = set()
    while voice in merges and voice not in seen:
        seen.add(voice)
        voice = merges[voice]
    return voice


def _record_text_edit(row: dict, span_id: str, text: str) -> None:
    """Keep the newest correction per span (re-analysis replays only that) and bound the list, so repeated edits cannot grow the ledger file
    that is rewritten whole on every save."""
    revisions = [
        item for item in row.get("revisions") or []
        if not (isinstance(item, dict) and item.get("span_id") == span_id and "text" in item and "scope" not in item)
    ]
    revisions.append({"span_id": span_id, "text": text, "at": _now()})
    row["revisions"] = revisions[-MAX_REVISIONS:]


def apply_text_edits(row: dict, spans: list[dict]) -> None:
    """Text a person corrected survives a re-analysis: the newest correction for a span wins over what the
    model transcribed this time. Only spans that still exist are touched."""
    latest: dict[str, str] = {}
    for revision in row.get("revisions") or []:
        if isinstance(revision, dict) and isinstance(revision.get("span_id"), str) and isinstance(revision.get("text"), str):
            latest[revision["span_id"]] = revision["text"]
    for span in spans:
        if span.get("span_id") in latest:
            span["text"] = latest[span["span_id"]]


def apply_locked_names(row: dict, spans: list[dict]) -> None:
    """A name a person gave a voice outranks anything a later analysis produced for it."""
    locked = row.get("speaker_names") or {}
    for span in spans:
        name = locked.get(span.get("speaker_hypothesis_id"))
        if name:
            span["speaker_display"] = name


def _load_entrypoints():
    # Bugs vs Fixes
    # Bug: The worker tree was added to sys.path only while these three
    # modules loaded, then removed. The analysis thread later imports
    # bedrock, loop, and registry as top-level names and raised
    # ModuleNotFoundError, so every staging job failed at submit.
    # Fix: Leave apps/worker on the path. Append it so the API's quotient
    # package, already first on the path, is not shadowed by
    # apps/worker/quotient.
    root = str(Path(__file__).resolve().parents[1])
    test_index = next((i for i, p in enumerate(sys.path) if "tests" in Path(p).parts), -1)
    if root not in sys.path:
        if test_index != -1:
            sys.path.insert(test_index, root)
        else:
            sys.path.append(root)
    elif test_index != -1 and sys.path.index(root) > test_index:
        sys.path.remove(root)
        sys.path.insert(test_index, root)
    for name in ("graph", "identity", "screenuse"):
        if name in sys.modules and not hasattr(sys.modules[name], "__path__"):
            del sys.modules[name]
    from loop.quality import run as quality_run
    from loop.store import MemoryStore
    from media.probe import classify_file, model_plan
    return quality_run, MemoryStore(), classify_file, model_plan


def load_port() -> Port:
    quality_run, checkpoints, classify_file, model_plan = _load_entrypoints()
    is_local = os.environ.get("QUOTIENT_ENVIRONMENT", "").strip().lower() == "local"
    local_state = None
    if is_local:
        configured = os.environ.get("QUOTIENT_LOCAL_STATE_PATH", "").strip()
        local_state = Path(configured) if configured else Path(__file__).resolve().parents[3] / ".local" / "run" / "meetings.json"
    else:
        local_state = Path("/tmp/quotient/meetings.json")
    port = Port(
        quality_run,
        checkpoints,
        classify_file,
        model_plan,
        state_path=local_state,
        resume_interrupted=is_local,
    )
    if not is_local:
        _load_seed(port)
    return port


def _seed_module():
    mod = sys.modules.get("quotient_worker_seed")
    if mod is not None:
        return mod
    path = Path(__file__).with_name("seed.py")
    spec = importlib.util.spec_from_file_location("quotient_worker_seed", path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        sys.modules["quotient_worker_seed"] = mod
        return mod
    except Exception as exc:
        print(f"seed module exec error: {exc}", file=sys.stderr, flush=True)
        return None


def _load_seed(port: Port) -> None:
    module = _seed_module()
    if module is None:
        print("meeting seed skipped: seed module is missing", file=sys.stderr, flush=True)
        return
    try:
        module.load_into(port)
    except Exception as exc:
        print(f"meeting seed skipped: {type(exc).__name__}: {str(exc)[:200]}", file=sys.stderr, flush=True)
