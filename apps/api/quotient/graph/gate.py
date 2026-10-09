"""Motivation vs Logic

Motivation: A partner payload is a projection of the provenance graph. A claim
is published only when its citations resolve, and a brief is withheld while the
job is not ready. Owner strings are not a field the product stores.
Logic: Strip denied keys, verify each citation against span text, drop findings
and synthesis that lack supported ids, force a relative due date to stay null
without an anchor, and downgrade a ready job that still has review items or
uncovered speech spans.
"""

from __future__ import annotations

import re

from quotient.worker.port import ARTIFACT_KEYS

DIMENSIONS = (
    "decision",
    "commitment",
    "temporal",
    "stakeholder",
    "cross_modal",
    "documentary",
    "risk",
    "gap",
    "dependency",
    "question",
)

_DENY_KEYS = frozenset(
    {
        "owner",
        "owner_name",
        "owner_string",
        "bedrock_api_key",
        "aws_secret_access_key",
        "aws_access_key_id",
        "aws_session_token",
        "api_key",
        "secret_access_key",
        "prompt_body",
        "system_prompt",
        "object_key",
        "subject",
        "context_names",
    }
)

_SECRET_MARKERS = ("AKIA", "aws_secret_access_key", "BEGIN PRIVATE")


def project_meeting(raw: dict) -> dict:
    meeting_id = str(raw.get("meeting_id") or "")
    cleaned = _strip(raw)
    spans = [span for span in cleaned.get("spans") or [] if isinstance(span, dict)]
    spans_by_id = {span.get("span_id"): span for span in spans if isinstance(span.get("span_id"), str)}
    published: list[dict] = []
    review_claims: list[dict] = []
    for claim in cleaned.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        view, ok = _claim_view(claim, spans_by_id, meeting_id)
        if ok:
            published.append(view)
        else:
            review_claims.append(view)
    review_by_id = {claim["claim_id"]: claim for claim in review_claims}
    queue_order = [
        claim_id
        for claim_id in cleaned.get("review_queue") or []
        if isinstance(claim_id, str) and claim_id in review_by_id
    ]
    ordered_ids = set(queue_order)
    review_claims = [review_by_id[claim_id] for claim_id in queue_order] + [
        claim for claim in review_claims if claim["claim_id"] not in ordered_ids
    ]
    published_ids = {claim["claim_id"] for claim in published}
    findings = _findings(cleaned.get("findings") or [], published_ids)
    synthesis = _synthesis(cleaned.get("synthesis") or [], findings, published, meeting_id)
    actions = _actions(cleaned.get("actions") or [], spans_by_id)
    disagreements = [item for item in cleaned.get("disagreements") or [] if isinstance(item, dict)]
    omissions = [item for item in cleaned.get("omissions") or [] if isinstance(item, dict)]
    gaps = _gaps(cleaned.get("gaps"), spans_by_id)
    counts = _counts(review_claims)
    coverage_gap = _coverage_gap(spans, published, omissions)
    stored_status = str(cleaned.get("status") or "queued")
    status = stored_status
    not_evaluated = [name for name in cleaned.get("not_evaluated") or [] if name in DIMENSIONS]
    if stored_status == "ready" and (sum(counts.values()) > 0 or coverage_gap or gaps or not_evaluated):
        status = "needs_review"
    withheld = status != "ready"
    dimensions = _dimensions(findings, cleaned.get("findings") or [], not_evaluated)
    # Bugs vs Fixes
    # Bug: read_graph dropped the worker chart tables and the dissent omission
    # records, so a client had to invent both.
    # Fix: Copy charts and synthesis_omissions from the meeting row. This
    # function does not call the chart renderer.
    playback = (
        f"quotient://meetings/{meeting_id}/media"
        if isinstance(raw.get("object_key"), str) and raw.get("object_key")
        else f"meetings/{meeting_id}"
    )
    release = _release(cleaned.get("prompt_release"))
    graph = {
        "meeting_id": meeting_id,
        "status": status,
        "prompt_release": release,
        "playback": playback,
        "spans": [_span_view(span, meeting_id) for span in spans],
        "claims": published + review_claims,
        "findings": findings,
        "synthesis": synthesis,
        "actions": actions,
        "disagreements": disagreements,
        "omissions": omissions,
        "gaps": gaps,
        "dimensions": dimensions,
        "raw_transcript": _raw_transcript(spans, cleaned.get("observations")),
        "charts": _charts(cleaned.get("charts")),
        "digest": _digest(cleaned.get("digest"), spans_by_id),
        "captions": (
            f"quotient://meetings/{meeting_id}/exports/captions.vtt"
            if any(span.get("kind") == "speech" for span in spans)
            else None
        ),
        "synthesis_omissions": _omissions(cleaned.get("synthesis_omissions"), "finding_id"),
        "dissent_omissions": _omissions(cleaned.get("synthesis_omissions"), "finding_id"),
    }
    brief_actions = []
    if not withheld:
        brief_actions = [
            action
            for action in actions
            if action.get("acceptance") == "accepted" or _action_claims_published(action, published_ids)
        ]
    brief = {
        "meeting_id": meeting_id,
        "status": status,
        "withheld": withheld,
        "prompt_release": None if withheld else release,
        "playback": playback,
        "dimensions": [] if withheld else dimensions,
        "findings": [] if withheld else findings,
        "synthesis": [] if withheld else synthesis,
        "actions": brief_actions,
        "disagreements": [] if withheld else disagreements,
        "omissions": [] if withheld else omissions,
    }
    return {
        "meeting_id": meeting_id,
        "status": status,
        "stored_status": stored_status,
        "prompt_release": release,
        "artifacts": _artifacts(cleaned.get("artifacts")),
        "review_counts": counts,
        "playback": playback,
        "progress_message": (
            cleaned.get("progress_message")
            if isinstance(cleaned.get("progress_message"), str)
            else ""
        ),
        "withheld": withheld,
        "updated_at": cleaned.get("updated_at") if isinstance(cleaned.get("updated_at"), str) else None,
        "source_name": _source_name(raw.get("object_key")),
        "task_id": _task_id(raw.get("object_key")),
        "context": _context_view(raw.get("context")),
        "failure_message": _safe_failure(cleaned.get("failure_message")),
        "graph": graph,
        "brief": brief,
        "review": {
            "meeting_id": meeting_id,
            "status": status,
            "counts": counts,
            "claims": review_claims,
        },
    }


def summary(projected: dict) -> dict:
    result = {
        "meeting_id": projected["meeting_id"],
        "status": projected["status"],
        "prompt_release": projected["prompt_release"],
        "review_counts": projected["review_counts"],
        "artifacts": projected["artifacts"],
        "playback": projected["playback"],
        "withheld": projected["withheld"],
        "progress_message": projected.get("progress_message", ""),
    }
    if projected.get("updated_at"):
        result["updated_at"] = projected["updated_at"]  # additive: lets a client show real times
    if projected.get("source_name"):
        result["source_name"] = projected["source_name"]  # additive: a readable fallback title
    if projected.get("task_id"):
        result["task_id"] = projected["task_id"]  # additive: lets a client tie its own submission to this meeting
    if projected.get("context"):
        result["context"] = projected["context"]  # additive: what reference material the analysis was given
    digest = (projected.get("graph") or {}).get("digest")
    if isinstance(digest, dict):
        # Additive: what a meeting list needs to say what the meeting was and what came out of it.
        result["headline"] = {
            "title": digest.get("title") or "",
            "content_type": digest.get("content_type") or "other",
            "decisions": len(digest.get("decisions") or []),
            "actions": len(digest.get("actions") or []),
            "open_questions": sum(1 for row in digest.get("open_questions") or [] if not row.get("answered")),
            "summary": next((row.get("text") for row in digest.get("summary") or [] if row.get("text")), ""),
        }
    # Additive: only a failed meeting carries its (already sanitised) reason.
    if projected["status"] == "failed" and projected.get("failure_message"):
        result["failure_message"] = projected["failure_message"]
    return result


def page_graph(graph: dict, offset: int, page_size: int) -> tuple[dict, int | None]:
    keys = ("spans", "claims", "findings", "synthesis", "actions", "disagreements", "omissions", "gaps")
    paged = {
        "meeting_id": graph["meeting_id"],
        "status": graph["status"],
        "prompt_release": graph["prompt_release"],
        "playback": graph["playback"],
    }
    if offset == 0:
        paged.update(
            {
                "dimensions": graph["dimensions"],
                "raw_transcript": graph["raw_transcript"],
                "charts": graph.get("charts") or [],
                "synthesis_omissions": graph.get("synthesis_omissions") or [],
                "digest": graph.get("digest"),
                "captions": graph.get("captions"),
                "dissent_omissions": graph.get("dissent_omissions") or [],
            }
        )
    more = False
    for key in keys:
        rows = graph.get(key) or []
        paged[key] = rows[offset : offset + page_size]
        if offset + page_size < len(rows):
            more = True
    next_offset = offset + page_size if more else None
    return paged, next_offset


def _gaps(value: object, spans_by_id: dict) -> list[dict]:
    if not isinstance(value, list):
        return []
    rows = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        ids = item.get("span_ids")
        valid_ids = list(dict.fromkeys(span_id for span_id in ids if isinstance(span_id, str) and span_id in spans_by_id)) if isinstance(ids, list) else []
        if valid_ids:
            rows.append({"gap_id": f"gap-{index + 1}", "span_ids": valid_ids, "reason": item.get("reason") if isinstance(item.get("reason"), str) else ""})
    return rows


def _charts(value: object) -> list:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _omissions(value: object, field: str) -> list:
    if not isinstance(value, list):
        return []
    rows = []
    for item in value:
        if isinstance(item, dict) and isinstance(item.get(field), str):
            rows.append({"finding_id": item[field], "reason": item.get("reason") if isinstance(item.get("reason"), str) else ""})
    return rows


def _raw_transcript(spans: list, observations: object) -> dict:
    """Motivation vs Logic

    Motivation: The portal shows the Sonic audio string and the Pegasus video
    statements beside the synthesized span text. No model writes this object.
    Logic: Sort each source by start_ms and join the stored strings with newlines.
    Audio is span raw_text. Video is observation statements. Span text is unused.
    """

    rows = observations if isinstance(observations, list) else []
    return {"audio": _join_timed(spans, "raw_text"), "video": _join_timed(rows, "statement")}


def _join_timed(rows: list, field: str) -> str:
    pieces: list[tuple[tuple[int, int, int], str]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        value = row.get(field)
        if not isinstance(value, str) or value == "":
            continue
        start = row.get("start_ms")
        if isinstance(start, int) and not isinstance(start, bool):
            pieces.append(((0, start, index), value))
        else:
            pieces.append(((1, 0, index), value))
    pieces.sort(key=lambda item: item[0])
    return "\n".join(value for _key, value in pieces)


def _action_claims_published(action: dict, published_ids: set[str]) -> bool:
    claim_ids = action.get("claim_ids") or []
    return bool(claim_ids) and all(item in published_ids for item in claim_ids)


# Motivation vs Logic
# Motivation: "none_in_transcript" must mean the lens looked and found nothing. A
# dimension with no published finding can also be held (findings exist but their
# claims are unconfirmed) or not evaluated (the lens did not complete).
# Logic: state stays "findings" or "none_in_transcript" for existing clients.
# A dimension the lens did not complete is "not_evaluated". A none row also
# carries held_findings, the count of worker findings for that dimension that the
# publish rules kept off the page, so a reader can tell "absent" from "unconfirmed".
def _dimensions(findings: list[dict], raw_findings: list | None = None, not_evaluated: list[str] | None = None) -> list[dict]:
    grouped: dict[str, list[str]] = {name: [] for name in DIMENSIONS}
    for finding in findings:
        grouped[finding["dimension"]].append(finding["finding_id"])
    held: dict[str, int] = {name: 0 for name in DIMENSIONS}
    published = {item["finding_id"] for item in findings}
    for raw in raw_findings or []:
        if not isinstance(raw, dict) or raw.get("dimension") not in held:
            continue
        identifier = raw.get("finding_id") or raw.get("id")
        if identifier not in published:
            held[raw["dimension"]] += 1
    unevaluated = set(not_evaluated or [])
    rows = []
    for name in DIMENSIONS:
        ids = grouped[name]
        if ids:
            rows.append({"dimension": name, "state": "findings", "finding_ids": ids})
        elif name in unevaluated:
            rows.append({"dimension": name, "state": "not_evaluated"})
        else:
            rows.append({"dimension": name, "state": "none_in_transcript", "held_findings": held[name]})
    return rows


def _findings(raw_findings: list, published_ids: set[str]) -> list[dict]:
    kept = []
    for finding in raw_findings:
        if not isinstance(finding, dict):
            continue
        if finding.get("dimension") not in DIMENSIONS:
            continue
        claim_ids = [item for item in finding.get("claim_ids") or [] if isinstance(item, str)]
        if not claim_ids or any(item not in published_ids for item in claim_ids):
            continue
        finding_id = finding.get("finding_id")
        text = finding.get("text")
        if not isinstance(finding_id, str) or not isinstance(text, str) or not text:
            continue
        stance = finding.get("stance")
        if stance not in {"supports", "conflicts", "unknown"}:
            stance = "unknown"
        kept.append(
            {
                "finding_id": finding_id,
                "dimension": finding["dimension"],
                "stance": stance,
                "text": text,
                "claim_ids": claim_ids,
            }
        )
    return kept


def _synthesis(raw_rows: list, findings: list[dict], published: list[dict], meeting_id: str) -> list[dict]:
    finding_claims = {item["finding_id"]: item["claim_ids"] for item in findings}
    claim_times = {}
    for claim in published:
        starts = [
            citation["start_ms"]
            for citation in claim.get("citations") or []
            if isinstance(citation.get("start_ms"), int) and not isinstance(citation.get("start_ms"), bool)
        ]
        if starts and isinstance(claim.get("claim_id"), str):
            claim_times[claim["claim_id"]] = min(starts)
    kept = []
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        ids = [item for item in row.get("finding_ids") or [] if item in finding_claims]
        text = row.get("text")
        if not ids or not isinstance(text, str) or not text:
            continue
        starts = [
            claim_times[claim_id]
            for finding_id in ids
            for claim_id in finding_claims[finding_id]
            if claim_id in claim_times
        ]
        if not starts:
            continue
        start_ms = min(starts)
        kept.append(
            {
                "sentence_id": row.get("sentence_id"),
                "text": text,
                "finding_ids": ids,
                "playback": f"meetings/{meeting_id}?t={start_ms}",
                "start_ms": start_ms,
            }
        )
    return kept


def _actions(raw_actions: list, spans_by_id: dict) -> list[dict]:
    prepared = []
    for action in raw_actions:
        if not isinstance(action, dict):
            continue
        action_id = action.get("action_id")
        statement = action.get("statement")
        if not isinstance(action_id, str) or not isinstance(statement, str):
            continue
        due_kind = action.get("due_kind")
        if due_kind not in {"absolute", "relative", "none"}:
            due_kind = "none"
        due_date = action.get("due_date") if isinstance(action.get("due_date"), str) else None
        anchor = action.get("anchor_date") if isinstance(action.get("anchor_date"), str) else None
        if due_kind == "relative" and not anchor:
            due_date = None
        if due_kind != "absolute":
            if due_kind != "relative":
                due_date = None
        acceptance = action.get("acceptance")
        if acceptance not in {"proposed", "accepted"}:
            acceptance = "proposed"
        origin = action.get("origin") if action.get("origin") in {"model", "human"} else "model"
        claim_ids = [item for item in action.get("claim_ids") or [] if isinstance(item, str)]
        prepared.append(
            {
                "action_id": action_id,
                "statement": statement,
                "owner_span_id": action.get("owner_span_id") if isinstance(action.get("owner_span_id"), str) else None,
                "owner_display": _owner_display(action.get("owner_span_id"), spans_by_id),
                "agreement_span_id": action.get("agreement_span_id")
                if isinstance(action.get("agreement_span_id"), str)
                else None,
                "due_kind": due_kind,
                "due_surface": action.get("due_surface") if isinstance(action.get("due_surface"), str) else None,
                "due_span_id": action.get("due_span_id") if isinstance(action.get("due_span_id"), str) else None,
                "due_date": due_date,
                "anchor_date": anchor,
                "claim_ids": claim_ids,
                "origin": origin,
                "acceptance": acceptance,
            }
        )
    merged: dict[tuple[str, ...], dict] = {}
    order: list[tuple[str, ...]] = []
    for action in prepared:
        key = tuple(action["claim_ids"])
        if not key:
            key = ("__id__", action["action_id"])
        if key not in merged:
            merged[key] = action
            order.append(key)
            continue
        current = merged[key]
        if current["acceptance"] != "accepted" and action["acceptance"] == "accepted":
            merged[key] = action
    return [merged[key] for key in order]


def _owner_display(span_id: object, spans_by_id: dict) -> str:
    if not isinstance(span_id, str):
        return "not stated"
    span = spans_by_id.get(span_id)
    if not isinstance(span, dict):
        return "not stated"
    text = span.get("text")
    if isinstance(text, str) and text.strip():
        return text
    return "not stated"


def _claim_view(claim: dict, spans_by_id: dict, meeting_id: str) -> tuple[dict, bool]:
    citations = []
    for citation in claim.get("citations") or []:
        view = _citation_view(citation, spans_by_id, meeting_id)
        if view is not None:
            citations.append(view)
    status = claim.get("status")
    holds = status == "supported" and bool(citations) and len(citations) == len(claim.get("citations") or [])
    if not holds:
        if status in {"contradicted", "numeric_failed"}:
            public_status = status
        else:
            public_status = "unresolved"
    else:
        public_status = "supported"
    claim_id = claim.get("claim_id") if isinstance(claim.get("claim_id"), str) else ""
    view = {
        "claim_id": claim_id,
        "kind": claim.get("kind"),
        "status": public_status,
        "text": claim.get("text") if isinstance(claim.get("text"), str) else "",
        "decision_status": claim.get("decision_status"),
        "origin": claim.get("origin") if claim.get("origin") in {"model", "human"} else "model",
        "coarse": bool(claim.get("coarse")),
        "overlap": bool(claim.get("overlap")),
        "citations": citations,
        "confidence": _confidence(claim, public_status, citations),
    }
    return view, holds and bool(claim_id)


_CONFIDENCE = {"confirmed", "likely", "contradicted", "unverified"}


def _confidence(claim: dict, public_status: str, citations: list[dict]) -> str:
    """Confidence tier for display. A tier never outranks what the citations prove:
    without a verified citation a claim is at best unverified."""
    if public_status == "supported":
        return "confirmed"
    if public_status == "contradicted":
        return "contradicted"
    stored = claim.get("confidence")
    if stored not in _CONFIDENCE:
        verdict = claim.get("verdict") if isinstance(claim.get("verdict"), dict) else {}
        labels = {verdict.get("sol"), verdict.get("luna")}
        if "contradicts" in labels or verdict.get("contradiction"):
            stored = "contradicted"
        elif verdict.get("quote_resolved") and "entails" in labels:
            stored = "likely"
        else:
            stored = "unverified"
    if stored == "confirmed":
        stored = "likely"
    if stored == "likely" and not citations:
        return "unverified"
    return stored


def _citation_view(citation: object, spans_by_id: dict, meeting_id: str) -> dict | None:
    if not isinstance(citation, dict):
        return None
    span_id = citation.get("span_id")
    span = spans_by_id.get(span_id)
    if not isinstance(span, dict):
        return None
    if span.get("meeting_id") not in (None, meeting_id):
        return None
    quote = citation.get("quote")
    text = span.get("text")
    if not isinstance(quote, str) or quote == "" or not isinstance(text, str):
        return None
    located = _offsets(citation, quote, text)
    if located is None:
        return None
    char_start, char_end = located
    start_ms = citation.get("start_ms")
    end_ms = citation.get("end_ms")
    span_start = span.get("start_ms")
    span_end = span.get("end_ms")
    if not _ints(start_ms, end_ms, span_start, span_end):
        return None
    if not (span_start <= start_ms <= end_ms <= span_end):
        return None
    relation = citation.get("relation")
    if relation not in {"entails", "contradicts", "mentions"}:
        relation = "mentions"
    return {
        "quote": quote,
        "span_id": span_id,
        "relation": relation,
        "char_start": char_start,
        "char_end": char_end,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "playback": f"meetings/{meeting_id}?t={start_ms}",
    }


def _offsets(citation: dict, quote: str, text: str) -> tuple[int, int] | None:
    start = citation.get("char_start")
    end = citation.get("char_end")
    if _ints(start, end):
        if text[start:end] != quote:
            return None
        return start, end
    found = text.find(quote)
    if found < 0 or text.find(quote, found + 1) != -1:
        return None
    return found, found + len(quote)


def _span_view(span: dict, meeting_id: str) -> dict:
    start_ms = span.get("start_ms") if _ints(span.get("start_ms")) else None
    playback = f"meetings/{meeting_id}?t={start_ms}" if isinstance(start_ms, int) else f"meetings/{meeting_id}"
    return {
        "span_id": span.get("span_id"),
        "meeting_id": meeting_id,
        "kind": span.get("kind"),
        "start_ms": span.get("start_ms"),
        "end_ms": span.get("end_ms"),
        "raw_text": span.get("raw_text") if isinstance(span.get("raw_text"), str) else "",
        "text": span.get("text") if isinstance(span.get("text"), str) else "",
        "coarse": bool(span.get("coarse")),
        "overlap": bool(span.get("overlap")),
        "session_id": span.get("session_id"),
        "speaker_hypothesis_id": span.get("speaker_hypothesis_id"),
        "speaker_display": span.get("speaker_display"),
        "playback": playback,
    }


def _coverage_gap(spans: list[dict], published: list[dict], omissions: list[dict]) -> bool:
    covered = set()
    for claim in published:
        for citation in claim.get("citations") or []:
            covered.add(citation.get("span_id"))
    omitted = {item.get("span_id") for item in omissions if item.get("span_id")}
    for span in spans:
        if span.get("kind") != "speech":
            continue
        span_id = span.get("span_id")
        if span_id not in covered and span_id not in omitted:
            return True
    return False


def _counts(review_claims: list[dict]) -> dict[str, int]:
    counts = {name: 0 for name in ("unresolved", "contradicted", "numeric_failed")}
    for claim in review_claims:
        status = claim.get("status")
        if status not in counts:
            status = "unresolved"
        counts[status] += 1
    return counts


def _artifacts(raw: object) -> dict[str, str]:
    source = raw if isinstance(raw, dict) else {}
    result = {}
    for key in ARTIFACT_KEYS:
        value = source.get(key)
        result[key] = value if isinstance(value, str) and value else "pending"
    return result


def _release(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    if not value or len(value) > 128 or "\n" in value or "\r" in value:
        return None
    return value


_LEAKY = ("/Users/", "/home/", "/private/", "/tmp/", "Command [", "Command '[", "Traceback", "RequestId")


_CONTEXT_STATUS = {"pending", "ready", "skipped", "failed"}


def _context_view(value: object) -> dict | None:
    """The person's purpose and each item's name and state; never storage keys or batch ids."""
    if not isinstance(value, dict):
        return None
    items = []
    for item in value.get("items") or []:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        status = item.get("status") if item.get("status") in _CONTEXT_STATUS else "pending"
        chars = item.get("chars")
        items.append({
            "name": item["name"][:160],
            "status": status,
            "reason": item.get("reason") if isinstance(item.get("reason"), str) else None,
            "chars": chars if isinstance(chars, int) and not isinstance(chars, bool) else None,
            "summary": item.get("summary") if isinstance(item.get("summary"), str) else None,
        })
    purpose = value.get("purpose") if isinstance(value.get("purpose"), str) and value["purpose"].strip() else None
    return {"purpose": purpose, "items": items} if (items or purpose) else None


_UPLOAD_TASK = re.compile(r"^uploads/([A-Za-z0-9_-]{1,64})/")


def _task_id(object_key: object) -> str | None:
    """The task that uploaded the recording: the server mints uploads/<task_id>/<name>, so the key names it."""
    match = _UPLOAD_TASK.match(object_key) if isinstance(object_key, str) else None
    return match.group(1) if match else None


def _source_name(object_key: object) -> str | None:
    """The file's own name without folders or extension; never the per-meeting copy's generated name."""
    if not isinstance(object_key, str) or not object_key:
        return None
    stem = object_key.rsplit("/", 1)[-1].rsplit(".", 1)[0].strip()
    if not stem or len(stem) > 80 or stem.lower().endswith("-0"):
        return None
    return stem.replace("_", " ").replace("-", " ").strip() or None


def _safe_failure(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 200:
        return None
    if any(marker in value for marker in _SECRET_MARKERS):
        return "Meeting failed."
    # Rows written before failures were sanitised can still hold paths or command lines.
    if any(marker in value for marker in _LEAKY):
        return "The analysis could not be completed. Please try again."
    return value


def _strip(value: object) -> object:
    if isinstance(value, dict):
        return {key: _strip(item) for key, item in value.items() if key not in _DENY_KEYS}
    if isinstance(value, list):
        return [_strip(item) for item in value]
    return value


def _ints(*values: object) -> bool:
    return all(isinstance(value, int) and not isinstance(value, bool) for value in values)


_DIGEST_LISTS = (
    "summary", "chapters", "decisions", "actions", "open_questions", "disagreements", "perspectives",
    "key_figures", "risks", "concepts", "speakers",
)


# Commentary about the transcript's own mechanics ("the continuing argument under Speaker 8", "completed in the following
# line labeled Speaker 7") reads as nonsense to someone who never saw the lines. The writer is told not to produce it; this
# drops the clause that does, for meetings analysed before that rule and for any that slip past it.
_LEAK = re.compile(
    r"\b(?:the\s+)?(?:continuing|continued|continuation)\s+(?:argument|statement|remark|point|line)s?\b"
    r"|\b(?:in|on|from|by)\s+the\s+(?:following|next|previous|preceding|prior)\s+(?:line|span|segment|turn)\b"
    r"|\bline\s+labell?ed\b|\blabell?ed\s+(?:as\s+)?(?:speaker\s*\d+|spk_\d+)\b|\bspan[_ ]?ids?\b",
    re.I,
)
# A first-person promise: "we will", "i'll". Mirrors the worker, which applies the same rule to new analyses.
_PROMISE = re.compile(r"\b(?:i|we)(?:'ll|\s+will|\s+shall|\s+can|\s+am\s+going\s+to|\s+are\s+going\s+to|\s+gonna)\b", re.I)
# A choice somebody describes from the past is background, not something these participants settled.
_HISTORY = re.compile(r"^\s*(?:historically|in the past|back then|years ago)\b[\s,]", re.I)
_PROSE_KEYS = ("text", "statement", "position", "task", "question", "answer", "explanation", "gist", "what", "reason")


def _unleak(value: str) -> str:
    """Remove every clause that talks about the transcript itself; keep the rest of the sentence."""
    if not _LEAK.search(value):
        return value
    clauses = re.split(r"(?<=[;])\s+", value)
    kept = [clause for clause in clauses if not _LEAK.search(clause)]
    text = " ".join(kept).strip().rstrip(";,").strip()
    if text and text[-1] not in ".!?":
        text += "."
    return text if kept else ""


def _unleak_row(row: dict) -> bool:
    """Clean one row in place. False when its main text was nothing but such commentary."""
    main = next((key for key in _PROSE_KEYS if isinstance(row.get(key), str) and row[key].strip()), None)
    for key in _PROSE_KEYS:
        if isinstance(row.get(key), str):
            row[key] = _unleak(row[key])
    positions = row.get("positions")
    if isinstance(positions, list):
        copies = [dict(position) for position in positions if isinstance(position, dict)]
        row["positions"] = [position for position in copies if _unleak_row(position)]
    return main is None or bool(row.get(main))


def _digest(value: object, spans_by_id: dict) -> dict | None:
    """Re-check the worker's grounded digest against this meeting's spans before anyone reads it.

    An item whose citations no longer resolve (for example after a span was removed) is dropped,
    so the API never shows a walkaway item without evidence on this graph.
    """
    if not isinstance(value, dict):
        return None
    known = {span_id for span_id, span in spans_by_id.items() if isinstance(span, dict)}

    def cited(item: dict) -> bool:
        ids = [item.get(key) for key in ("span_id", "asked_span_id", "start_span_id") if item.get(key)]
        ids += list(item.get("span_ids") or [])
        for position in item.get("positions") or []:
            ids += list(position.get("span_ids") or []) if isinstance(position, dict) else []
        return bool(ids) and all(isinstance(span_id, str) and span_id in known for span_id in ids)

    out: dict = {
        "content_type": value.get("content_type") if isinstance(value.get("content_type"), str) else "other",
        "title": value.get("title") if isinstance(value.get("title"), str) else "",
    }
    for key in _DIGEST_LISTS:
        rows = value.get(key) if isinstance(value.get(key), list) else []
        out[key] = [row for row in (dict(item) for item in rows if isinstance(item, dict) and cited(item)) if _unleak_row(row)]
    for row in out.get("actions") or []:
        cited_spans = [spans_by_id[i] for i in row.get("span_ids") or [] if isinstance(spans_by_id.get(i), dict)]
        heard = {sp.get("speaker_hypothesis_id") for sp in cited_spans if sp.get("speaker_hypothesis_id")}
        if row.get("assignee") and row["assignee"] not in heard:
            promised = any(_PROMISE.search(str(sp.get("text") or sp.get("raw_text") or "")) for sp in cited_spans)
            row["assignee"] = next(iter(heard)) if len(heard) == 1 and promised else None
    out["decisions"] = [row for row in out.get("decisions") or [] if not _HISTORY.match(str(row.get("statement") or ""))]
    # A reply citing a line that is no longer on this graph loses the reply, not the question.
    for row in out.get("open_questions") or []:
        reply = row.get("answer_span_id")
        if reply is not None and reply not in known:
            row.update({"answered": False, "answer": None, "answer_span_id": None, "answer_ms": None})
    # Topics stay contiguous after any chapter was dropped: each runs until the next one starts.
    chapters = sorted(
        (row for row in out.get("chapters") or [] if isinstance(row.get("start_ms"), (int, float))),
        key=lambda row: row["start_ms"],
    )
    for current, following in zip(chapters, chapters[1:]):
        if isinstance(current.get("end_ms"), (int, float)) and current["end_ms"] < following["start_ms"]:
            current["end_ms"] = following["start_ms"]
    # And none runs past the last spoken line (a stored digest may round its last topic up to the minute).
    ends = [span.get("end_ms") for span in spans_by_id.values() if isinstance(span, dict) and span.get("kind") == "speech" and isinstance(span.get("end_ms"), (int, float))]
    if chapters and ends:
        last = max(ends)
        for row in chapters:
            if isinstance(row.get("end_ms"), (int, float)):
                row["end_ms"] = min(row["end_ms"], max(last, row["start_ms"]))
    if chapters:
        out["chapters"] = chapters
    outcome = value.get("outcome")
    out["outcome"] = outcome if isinstance(outcome, dict) and cited(outcome) and isinstance(outcome.get("text"), str) else None
    if out["outcome"] is not None:
        out["outcome"] = dict(out["outcome"])
        if not _unleak_row(out["outcome"]):
            out["outcome"] = None
    diagram = value.get("diagram")
    out["diagram"] = diagram if isinstance(diagram, dict) and cited(diagram) and isinstance(diagram.get("mermaid"), str) else None
    return out
