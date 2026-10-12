"""Motivation vs Logic

Motivation: A caller chooses a raw transcript, analysis sections, or both.
The meeting pipeline itself does not change.
Logic: Reject an unknown field before any upload is signed. Slice the publish
gate: raw_transcript for the transcript, and the gated digest plus published
findings for the analysis sections that were asked for.
"""

from __future__ import annotations

import re

from quotient.graph.gate import project_meeting

_SECTIONS = ("summary", "decisions", "actions", "questions", "findings")
_TOP = {"media", "context", "outputs", "stream", "idempotency_key"}
_CONTEXT = {"purpose", "names", "files"}
_MEDIA_TYPE = re.compile(r"^(audio|video)/[a-z0-9.+-]+$")


def parse_job(body: dict) -> dict:
    extra = set(body) - _TOP
    if extra:
        raise ValueError("The request has an unrecognised field.")
    if not isinstance(body.get("stream"), bool):
        raise ValueError("stream must be true or false.")
    outputs = _outputs(body.get("outputs"))
    media = _media(body.get("media"))
    context = _context(body.get("context"))
    idem = body.get("idempotency_key")
    if idem is not None:
        if not isinstance(idem, str) or not idem or len(idem) > 128:
            raise ValueError("idempotency_key must be a string.")
        if not all(char.isalnum() or char in "_-." for char in idem):
            raise ValueError("idempotency_key has unsupported characters.")
    return {
        "media": media,
        "outputs": outputs,
        "stream": body["stream"],
        "idempotency_key": idem,
        "purpose": context["purpose"],
        "names": context["names"],
        "files": context["files"],
    }


def project_result(raw: dict, outputs: dict, *, job_id: str) -> dict:
    projected = project_meeting(raw)
    graph = projected.get("graph") if isinstance(projected.get("graph"), dict) else {}
    body: dict = {
        "job_id": job_id,
        "meeting_id": projected.get("meeting_id"),
        "status": projected.get("status"),
    }
    if outputs.get("transcript"):
        transcript = graph.get("raw_transcript")
        body["transcript"] = transcript if isinstance(transcript, dict) else {"audio": "", "video": ""}
    sections = outputs.get("analysis") or []
    if sections:
        digest = graph.get("digest") if isinstance(graph.get("digest"), dict) else {}
        analysis: dict = {}
        if "summary" in sections:
            analysis["title"] = digest.get("title") if isinstance(digest.get("title"), str) else ""
            analysis["summary"] = digest.get("summary") if isinstance(digest.get("summary"), list) else []
            analysis["outcome"] = digest.get("outcome") if isinstance(digest.get("outcome"), dict) else None
        if "decisions" in sections:
            analysis["decisions"] = digest.get("decisions") if isinstance(digest.get("decisions"), list) else []
        if "actions" in sections:
            analysis["actions"] = digest.get("actions") if isinstance(digest.get("actions"), list) else []
        if "questions" in sections:
            questions = digest.get("open_questions")
            analysis["questions"] = questions if isinstance(questions, list) else []
        if "findings" in sections:
            findings = graph.get("findings")
            analysis["findings"] = findings if isinstance(findings, list) else []
        body["analysis"] = analysis
    return body


def wants(outputs: dict, name: str) -> bool:
    if name == "transcript":
        return outputs.get("transcript") is True
    return name in (outputs.get("analysis") or [])


def _outputs(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("outputs must name a transcript, an analysis, or both.")
    unknown = set(value) - {"transcript", "analysis"}
    if unknown:
        raise ValueError("outputs has an unrecognised field.")
    if "transcript" in value and not isinstance(value.get("transcript"), bool):
        raise ValueError("transcript must be true or false.")
    transcript = value.get("transcript") is True
    analysis = _analysis(value.get("analysis")) if "analysis" in value else []
    if not transcript and not analysis:
        raise ValueError("Choose a transcript, an analysis section, or both.")
    return {"transcript": transcript, "analysis": analysis}


def _analysis(value: object) -> list[str]:
    if value is True:
        return list(_SECTIONS)
    if value is False or value is None:
        return []
    if not isinstance(value, dict):
        raise ValueError("analysis must be true or a set of sections.")
    unknown = set(value) - set(_SECTIONS)
    if unknown:
        raise ValueError("analysis has an unrecognised section.")
    chosen = []
    for name in _SECTIONS:
        if name not in value:
            continue
        if not isinstance(value[name], bool):
            raise ValueError(f"{name} must be true or false.")
        if value[name]:
            chosen.append(name)
    return chosen


def _media(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("media is required.")
    object_key = value.get("object_key")
    filename = value.get("filename")
    has_key = isinstance(object_key, str) and bool(object_key.strip())
    has_file = isinstance(filename, str) and bool(filename.strip())
    if has_key and has_file:
        raise ValueError("Send a stored object_key or a new file, not both.")
    if has_key:
        key = str(object_key).strip()
        if not _safe_key(key):
            raise ValueError("object_key is not a storage key.")
        return {"object_key": key}
    if not has_file:
        raise ValueError("media needs a filename or an object_key.")
    media_type = value.get("media_type")
    if not isinstance(media_type, str) or _MEDIA_TYPE.fullmatch(media_type) is None:
        raise ValueError("media_type must be an audio or video type.")
    size = value.get("byte_size")
    if isinstance(size, bool) or (size is not None and not isinstance(size, int)):
        raise ValueError("byte_size must be a whole number of bytes.")
    if isinstance(size, int) and size < 0:
        raise ValueError("byte_size must be a whole number of bytes.")
    return {"filename": str(filename).strip(), "media_type": media_type, "byte_size": size}


def _context(value: object) -> dict:
    if value is None:
        return {"purpose": None, "names": (), "files": []}
    if not isinstance(value, dict):
        raise ValueError("context must be an object.")
    if set(value) - _CONTEXT:
        raise ValueError("context has an unrecognised field.")
    purpose = value.get("purpose")
    if purpose is not None and not isinstance(purpose, str):
        raise ValueError("purpose must be text of at most 2000 characters.")
    if isinstance(purpose, str) and len(purpose) > 2000:
        raise ValueError("purpose must be text of at most 2000 characters.")
    names = value.get("names", [])
    if names is None:
        names = []
    if not isinstance(names, list) or len(names) > 32:
        raise ValueError("names must be a list of at most 32 strings.")
    clean = []
    for name in names:
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 64:
            raise ValueError("names entries must be short strings.")
        clean.append(name.strip())
    files = value.get("files", [])
    if files is None:
        files = []
    if not isinstance(files, list):
        raise ValueError("files must be a list.")
    prepared = []
    for entry in files:
        if not isinstance(entry, dict) or not isinstance(entry.get("filename"), str) or not entry["filename"].strip():
            raise ValueError("Each context file needs a filename.")
        item = {"filename": entry["filename"].strip()}
        if "media_type" in entry:
            if not isinstance(entry.get("media_type"), str):
                raise ValueError("A context file media_type must be a string.")
            item["media_type"] = entry["media_type"]
        if "byte_size" in entry:
            size = entry.get("byte_size")
            if isinstance(size, bool) or not isinstance(size, int) or size < 0:
                raise ValueError("A context file byte_size must be a whole number of bytes.")
            item["byte_size"] = size
        prepared.append(item)
    text = purpose.strip() if isinstance(purpose, str) else ""
    return {"purpose": text or None, "names": tuple(clean), "files": prepared}


def _safe_key(value: str) -> bool:
    if len(value) > 1024 or ".." in value or "\\" in value or value.startswith("/"):
        return False
    return all(32 < ord(char) < 127 for char in value)
