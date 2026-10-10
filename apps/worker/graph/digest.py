# Motivation vs Logic
# Motivation: The digest is what a reader takes away, so nothing in it may rest on the model's word
# alone. The model proposes; this module decides what is grounded.
# Logic:
# - Every span id an item cites must be a transcript span of this meeting; unknown ids are dropped and
#   an item left with no citation is dropped. Times always come from the cited spans.
# - Evidence bar chosen by the owner: decisions, risks and concepts are kept only when they rest on a
#   confirmed or likely claim; an action also on a ledger action whose words it shares, or on a quote
#   of at least three words that is in a cited line. Their basis is the weakest claim they cite.
#   Disagreements and perspectives are positions the speakers took: they need valid citations (and
#   disagreements two distinct voices), not a claim, because a position is not a statement of fact. Summary, chapters and questions are navigational and only
#   need valid span citations; their basis is "transcript".
# - A key figure is kept only when its number appears in its cited span (graph.numbers.grounded).
# - A question counts as answered only when the answer span exists and comes after the question.
# - Speaker fields must be a speaker label present in the transcript, else null.
# - Chapters are ordered by time and clipped so they never overlap.
# - The diagram passes the same mermaid scrub as brief prose, or is dropped.
# - A speaker name is kept only when the name appears as a whole word in a span the model cited for it.
# - Model output is untrusted in shape as well as content: a non-object item is dropped, and a field of
#   the wrong type is treated as missing, so one malformed value cannot cost the whole walkaway.
# - A disagreement needs positions from at least two distinct identified voices; if the diarizer
#   collapsed everyone into one voice, there is no disagreement to assert.
# - Outside an ordinary meeting (hearing, panel, interview, lecture) an action is kept only when it
#   has a named owner who either agreed or said it themselves: another voice's prediction about what
#   someone will do is not a commitment.

from __future__ import annotations

import re

from graph.numbers import grounded, scan
from graph.prose import _scrub

_EVIDENCE = {"confirmed": 2, "likely": 1}
GAP_MS = 60_000


_DIAGRAMS = frozenset({"flowchart", "graph", "sequenceDiagram"})
_STRINGS = ("id", "start_span_id", "end_span_id", "asked_span_id", "answer_span_id", "span_id", "action_id",
            "asked_by", "decided_by", "owner", "speaker")
_LISTS = ("summary", "chapters", "decisions", "actions", "open_questions", "disagreements", "key_figures",
          "risks", "concepts", "perspectives", "speakers")
_NUMBER_WORDS = re.compile(
    r"\b(zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
    r"seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|"
    r"billion|half|dozen|percent|negative|minus)\b", re.I)


# A due phrase is worth showing only when it names a time. "next", "soon" or "later" on their own tell the reader nothing.
_TIME_CUE = re.compile(
    r"\d|\b(today|tonight|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|march|april|"
    r"may|june|july|august|september|october|november|december|weeks?|weekends?|months?|years?|quarters?|morning|afternoon|evening|"
    r"hours?|minutes?|days?|eod|eow|end of|sprints?|noon|midnight|midday|overnight|fortnights?|asap|immediately|right away|"
    r"mon|tue|tues|wed|thu|thur|thurs|fri)\b", re.I)


_DATE_NAMES = re.compile(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|march|april|june|july|august|september|october|november|december)\b", re.I)


def _due_supported(due: str | None, nearby: str) -> bool:
    """A weekday or month in a due phrase has to be in the lines it came from (or the two either side): a date nobody said is worse than none."""
    return all(name.lower() in nearby.lower() for name in _DATE_NAMES.findall(due or ""))


def _due(value: object) -> str | None:
    due = value.strip() if isinstance(value, str) else ""
    return due if due and _TIME_CUE.search(due) else None


# A first-person promise in a transcript: "we will", "i'll", "i am going to". Used to say who owns a task when only one voice spoke it.
_PROMISE = re.compile(r"\b(?:i|we)(?:['’]ll|\s+will|\s+shall|\s+can|\s+am\s+going\s+to|\s+are\s+going\s+to|\s+gonna|['’](?:m|re)\s+(?:gonna|going\s+to))\b(?!['’]t|\s+never\b|\s+not(?!\s+only\b))", re.I)


def _clean_item(item: dict) -> dict:
    item = dict(item)
    for key in _STRINGS:
        if key in item and not isinstance(item[key], str):
            item[key] = None
    for key in ("status", "kind", "content_type"):
        if key in item and not isinstance(item[key], str):
            item[key] = None  # an unhashable value would otherwise fail the membership test and lose the whole digest
    if "answered" in item and not isinstance(item["answered"], bool):
        item["answered"] = False  # only a real true counts; the text "false" is not an answer
    for key in ("span_ids", "claim_ids"):
        value = item.get(key)
        item[key] = [entry for entry in value if isinstance(entry, str)] if isinstance(value, list) else []
    if "positions" in item:  # a number, boolean or string here would otherwise crash the loop that reads it and lose the digest
        value = item["positions"]
        item["positions"] = [_clean_item(position) for position in value if isinstance(position, dict)] if isinstance(value, list) else []
    return item


def _clean(raw: dict) -> dict:
    """Same data with every list a list of objects and every id a string, whatever the model sent."""
    out = dict(raw)
    if not isinstance(raw.get("content_type"), str):
        out["content_type"] = None
    for key in _LISTS:
        rows = raw.get(key)
        out[key] = [_clean_item(row) for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    for key in ("outcome", "diagram"):
        out[key] = _clean_item(raw[key]) if isinstance(raw.get(key), dict) else None
    return out


def _has_quantity(value: str) -> bool:
    """True when the figure reads as at least one number the span can be checked for; "half" or "negative" alone cannot, and would pass any span."""
    return bool(scan(value).quantities)


# Function words: two actions that both say "that" or "with" share nothing.
_STOP = frozenset(
    "that this these those with from have has had will would could should shall they them their then than there where when what which "
    "while been being were into onto over under your yours ours about after before also just only very more most some such each both "
    "other another same still like make made need needs want wants going gonna".split()
)


def _words(value: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", value.lower()) if len(word) > 3 and word not in _STOP}


def _clock(ms: int) -> str:
    seconds = int(ms // 1000)
    return f"{seconds // 60}:{seconds % 60:02d}"


def transcript_lines(spans: list, speaker_of) -> list[dict]:
    """Compact transcript rows for the digest payload: id, m:ss, speaker label, text."""
    rows = []
    last_end = None
    for span in spans:
        if span.kind != "speech" or not (span.text or "").strip() or span.start_ms is None:
            continue
        seconds = int(span.start_ms // 1000)
        # A long stretch with no text is a part the recording could not transcribe; say so, so the
        # walkaway does not read as continuous.
        if last_end is not None and span.start_ms - last_end > GAP_MS:
            rows.append({"gap": f"no transcript between {_clock(last_end)} and {_clock(span.start_ms)}"})
        last_end = max(last_end or 0, span.end_ms or span.start_ms)
        rows.append(
            {
                "id": span.id,
                "t": f"{seconds // 60}:{seconds % 60:02d}",
                "speaker": speaker_of(span),
                "text": span.text.strip(),
            }
        )
    return rows


# Screens go to the writer as evidence of what was shown. A cap keeps a long slide-heavy recording from
# crowding out the transcript: the budget is characters of text and details, spent in time order.
SCREEN_CHARS = 60_000
SCREEN_MAX = 120


def screen_rows(screens: list) -> list[dict]:
    """The on_screen payload: one row per distinct screen, in time order. A screen that repeats the one before
    (the same slide shown again after a cut) is folded into it, so the writer reads each thing once."""
    rows: list[dict] = []
    budget = SCREEN_CHARS
    previous = None
    for screen in sorted(screens, key=lambda item: item.start_ms):
        text = (getattr(screen, "text", "") or "").strip()
        details = (getattr(screen, "details", "") or "").strip()
        title = (getattr(screen, "title", "") or "").strip()
        signature = (screen.kind, title.casefold(), text.casefold())
        if previous is not None and signature == previous["sig"]:
            previous["row"]["end"] = _clock(screen.end_ms)
            continue
        cost = len(text) + len(details) + len(title)
        if len(rows) >= SCREEN_MAX or cost > budget:
            break
        budget -= cost
        row = {"t": _clock(screen.start_ms), "end": _clock(screen.end_ms), "kind": screen.kind}
        if title:
            row["title"] = title
        if text:
            row["text"] = text
        if details:
            row["details"] = details
        rows.append(row)
        previous = {"sig": signature, "row": row}
    return rows


def claim_rows(claims: list) -> list[dict]:
    rows = []
    for claim in claims:
        confidence = getattr(claim, "confidence", None)
        if confidence not in _EVIDENCE or not claim.span_id:
            continue
        rows.append(
            {
                "id": claim.id,
                "span_id": claim.span_id,
                "kind": claim.kind,
                "text": claim.paraphrase or claim.proposition,
                "quote": claim.quote,
                "confidence": confidence,
            }
        )
    return rows


def ground_digest(raw: dict | None, spans: list, claims: list, actions: list, speakers: set[str], known_names: dict | None = None) -> dict | None:
    if not isinstance(raw, dict):
        return None
    raw = _clean(raw)
    # Only lines a reader can see (the model is shown the same set) can be cited.
    by_span = {span.id: span for span in spans if span.kind == "speech" and span.start_ms is not None and (span.text or "").strip()}
    # Only claims the model was shown (a claim with no span is not in its payload) can support an item.
    evidence = {
        claim.id: getattr(claim, "confidence", None)
        for claim in claims
        if getattr(claim, "confidence", None) in _EVIDENCE and getattr(claim, "span_id", None)
    }
    action_ids = {f"a{index}" for index in range(len(actions))}
    statements = {f"a{index}": str(getattr(action, "statement", "") or "") for index, action in enumerate(actions)}

    linked: set[str] = set()

    def linked_action(item) -> str | None:
        """The ledger action a draft action names, only when the two share a content word."""
        action_id = item.get("action_id")
        if not isinstance(action_id, str) or action_id not in action_ids or action_id in linked:
            return None  # one ledger action backs one digest action
        return action_id if _words(str(item.get("task") or "")) & _words(statements[action_id]) else None

    known = {label: name.strip() for label, name in (known_names or {}).items() if isinstance(label, str) and isinstance(name, str) and name.strip()}
    ordered = sorted(by_span.values(), key=lambda span: span.start_ms)
    where = {span.id: index for index, span in enumerate(ordered)}

    def neighbours(ids) -> list[str]:
        """The cited lines and the two on either side of each, in transcript order."""
        keep = {j for i in ids for j in range(where[i] - 2, where[i] + 3) if 0 <= j < len(ordered)}
        return [ordered[j].id for j in sorted(keep)]

    def cite(ids) -> list[str]:
        return [item for item in dict.fromkeys(ids or []) if isinstance(item, str) and item in by_span]

    def basis(claim_ids) -> str | None:
        ranks = [_EVIDENCE[evidence[item]] for item in claim_ids or [] if item in evidence]
        if not ranks:
            return None
        return "confirmed" if min(ranks) == 2 else "likely"

    def when(ids: list[str]) -> int | None:
        times = [by_span[item].start_ms for item in ids if item in by_span]
        return min(times) if times else None

    def speaker(value) -> str | None:
        return value if isinstance(value, str) and value in speakers else None

    def text(value) -> str:
        return value.strip() if isinstance(value, str) else ""

    def bound(label, ids: list[str], *, derive: bool = False) -> str | None:
        """A voice may only be named on an item if it spoke one of the lines the item cites. When the
        model names a voice that did not, a single cited voice is used instead (derive) or nobody is named."""
        wanted = speaker(label)
        heard = {by_span[item].speaker_hypothesis_id for item in ids if by_span[item].speaker_hypothesis_id in speakers}
        if not heard or wanted in heard:
            return wanted
        return next(iter(heard)) if derive and len(heard) == 1 else None

    out: dict = {
        "content_type": raw.get("content_type") if raw.get("content_type") in {
            "meeting", "presentation", "lecture", "discussion", "interview", "other"
        } else "other",
        "title": text(raw.get("title"))[:140],
    }

    named = []
    seen_ids: set[str] = set()
    for item in raw.get("speakers") or []:
        label = item.get("id")
        name = text(item.get("name"))
        ids = cite(item.get("span_ids"))
        if label not in speakers or label in seen_ids or not name or not ids:
            continue
        needle = name.casefold().split()[-1]
        given = known.get(label)
        if given:
            # The picture or the person already named this voice: the writer may use it but not rename it.
            if given.casefold().split()[0] != name.casefold().split()[0] and needle != given.casefold().split()[-1]:
                continue
            name = given
        elif not any(re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", by_span[span_id].text.casefold()) for span_id in ids):
            continue
        seen_ids.add(label)
        # Transcripts are lower-case; a name shown to a reader should read like a name.
        shown = name.title() if name == name.lower() else name
        named.append({"id": label, "name": shown, "role": text(item.get("role")) or None, "span_ids": ids})
    # A voice with a known name is listed even when the writer did not list it, on its own first lines.
    for label, given in known.items():
        if label in seen_ids or label not in speakers:
            continue
        lines = [span.id for span in ordered if span.speaker_hypothesis_id == label][:2]
        if lines:
            seen_ids.add(label)
            named.append({"id": label, "name": given, "role": None, "span_ids": lines})
    out["speakers"] = named
    known = {row["id"] for row in named}

    summary = []
    for item in raw.get("summary") or []:
        ids = cite(item.get("span_ids"))
        if ids and text(item.get("text")):
            claim_ids = [c for c in item.get("claim_ids") or [] if c in evidence]
            summary.append({"text": text(item["text"]), "span_ids": ids, "claim_ids": claim_ids,
                            "basis": basis(claim_ids) or "transcript", "start_ms": when(ids)})
    out["summary"] = summary

    outcome = raw.get("outcome") if isinstance(raw.get("outcome"), dict) else None
    ids = cite(outcome.get("span_ids")) if outcome else []
    out["outcome"] = (
        {"text": text(outcome.get("text")), "span_ids": ids, "start_ms": when(ids)}
        if outcome and ids and text(outcome.get("text"))
        else None
    )

    chapters = []
    for item in raw.get("chapters") or []:
        start, end = by_span.get(item.get("start_span_id")), by_span.get(item.get("end_span_id"))
        if start is None or not text(item.get("title")):
            continue
        end = end or start
        # A named end line that comes before the start line would leave a zero-length topic; it covers at least its own first line.
        start_ms, end_ms = start.start_ms, max(end.end_ms or end.start_ms, start.end_ms or start.start_ms)
        chapters.append({"title": text(item["title"]), "gist": text(item.get("gist")),
                         "start_span_id": start.id, "start_ms": start_ms, "end_ms": end_ms})
    chapters.sort(key=lambda row: row["start_ms"])
    chapters = [row for index, row in enumerate(chapters) if index == 0 or row["start_ms"] != chapters[index - 1]["start_ms"]]  # two topics cannot start on one line
    for current, following in zip(chapters, chapters[1:]):
        # Topics run until the next one starts, so the timeline has no unlabelled stretch.
        current["end_ms"] = following["start_ms"]
    # No topic runs past the last line of the transcript (a model that rounds the end up to the minute
    # would otherwise show a topic playing over a recording that has already stopped).
    last_ms = max((span.end_ms or span.start_ms or 0 for span in spans if span.kind == "speech"), default=None)
    if last_ms:
        for row in chapters:
            row["end_ms"] = min(row["end_ms"], max(last_ms, row["start_ms"]))
    out["chapters"] = [row for row in chapters if row["end_ms"] >= row["start_ms"]]

    def squash(value: str) -> str:
        return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in value).split())

    def evidenced(item, *, allow_action=False) -> tuple[list[str], list[str], str] | None:
        ids = cite(item.get("span_ids"))
        claim_ids = [c for c in item.get("claim_ids") or [] if c in evidence]
        level = basis(claim_ids)
        if level is None and allow_action and linked_action(item):
            level = "likely"
        # A spoken promise can be checked directly: the words the model quotes must be in a cited line.
        if level is None and allow_action:
            words = squash(text(item.get("quote")))
            if len(words.split()) >= 3 and any(f" {words} " in f" {squash(by_span[span_id].text)} " for span_id in ids):
                level = "transcript"
        if not ids or level is None:
            return None
        return ids, claim_ids, level

    decisions = []
    for item in raw.get("decisions") or []:
        kept = evidenced(item)
        if kept and text(item.get("statement")):
            ids, claim_ids, level = kept
            decisions.append({"statement": text(item["statement"]),
                              "status": item.get("status") if item.get("status") in {"agreed", "tentative", "deferred"} else "tentative",
                              "decided_by": bound(item.get("decided_by"), ids), "span_ids": ids, "claim_ids": claim_ids,
                              "basis": level, "start_ms": when(ids)})
    out["decisions"] = decisions

    out_actions = []
    ordinary = out["content_type"] == "meeting"
    for item in raw.get("actions") or []:
        kept = evidenced(item, allow_action=True)
        owner = speaker(item.get("owner"))
        said_it = any(by_span[span_id].speaker_hypothesis_id == owner for span_id in cite(item.get("span_ids")))
        if not ordinary and not (owner and (item.get("agreed") is True or said_it)):
            continue
        if kept and text(item.get("task")):
            ids, claim_ids, level = kept
            link = linked_action(item)
            # The model's field is `owner`; the output calls it `assignee` because the API strips any key named owner.
            # The owner must be a voice that spoke one of the cited lines. When it was not, one voice making a
            # first-person promise in those lines owns it; otherwise no owner is stated, because a wrong name is worse.
            heard = {by_span[i].speaker_hypothesis_id for i in ids if by_span[i].speaker_hypothesis_id in speakers}
            promised = any(_PROMISE.search(by_span[i].text or "") for i in ids)
            assignee = speaker(item.get("owner"))
            if assignee is not None and assignee not in heard:
                assignee = None
            if assignee is None and len(heard) == 1 and promised:
                assignee = next(iter(heard))
            if not ordinary and assignee is None:
                continue  # outside an ordinary meeting an action needs a named owner, and the check above may have removed the model's
            if link:
                linked.add(link)
            due = _due(text(item.get("due")))
            if due and not _due_supported(due, " ".join(by_span[i].text or "" for i in neighbours(ids))):
                due = None
            out_actions.append({"task": text(item["task"]), "assignee": assignee,
                                "due": due, "agreed": item.get("agreed") is True,
                                "action_id": link,
                                "span_ids": ids, "claim_ids": claim_ids, "basis": level, "start_ms": when(ids)})
    out["actions"] = out_actions

    questions = []
    for item in raw.get("open_questions") or []:
        asked = by_span.get(item.get("asked_span_id"))
        if asked is None or not text(item.get("question")):
            continue
        answer_span = by_span.get(item.get("answer_span_id"))
        # A partial reply comes from someone other than the asker: the same voice carrying on is the
        # question continuing. A full answer is kept even from the same voice id, because the diarizer
        # sometimes puts both sides of a short exchange under one id.
        if (answer_span is not None and not item.get("answered") and asked.speaker_hypothesis_id
                and answer_span.speaker_hypothesis_id == asked.speaker_hypothesis_id):
            answer_span = None
        if answer_span is asked:
            answer_span = None  # a line cannot answer itself
        answered = bool(item.get("answered")) and answer_span is not None and answer_span.start_ms >= asked.start_ms
        # An unanswered question may still carry what was said in reply: a partial answer is shown
        # as such (answered stays false) instead of being thrown away.
        answer_text = text(item.get("answer")) or (answer_span.text.strip()[:240] if answered else "")
        replied = answer_span is not None and answer_span.start_ms >= asked.start_ms and bool(answer_text)
        questions.append({"question": text(item["question"]), "asked_by": bound(item.get("asked_by"), [asked.id], derive=True),
                          "asked_span_id": asked.id, "start_ms": asked.start_ms, "answered": answered,
                          "answer": answer_text or None if replied else None,
                          "answer_span_id": answer_span.id if replied else None,
                          "answer_ms": answer_span.start_ms if replied else None})
    out["open_questions"] = questions

    disagreements = []
    for item in raw.get("disagreements") or []:
        positions = []
        for position in item.get("positions") or []:
            ids = cite(position.get("span_ids"))
            if ids and text(position.get("position")):
                positions.append({"speaker": bound(position.get("speaker"), ids, derive=True), "position": text(position["position"]),
                                  "span_ids": ids, "start_ms": when(ids)})
        voices = {position["speaker"] for position in positions if position["speaker"]}
        if len(positions) >= 2 and len(voices) >= 2 and text(item.get("topic")):
            disagreements.append({"topic": text(item["topic"]), "positions": positions,
                                  "start_ms": min(p["start_ms"] for p in positions)})
    out["disagreements"] = disagreements

    figures = []
    for item in raw.get("key_figures") or []:
        span = by_span.get(item.get("span_id"))
        value = text(item.get("value"))
        if span is None or not value or not text(item.get("what")):
            continue
        if not _has_quantity(value) or not grounded(value, span.text):
            continue
        figures.append({"value": value, "what": text(item["what"]), "span_id": span.id, "start_ms": span.start_ms})
    out["key_figures"] = figures

    for key, field in (("risks", "risk"), ("concepts", "term")):
        rows = []
        for item in raw.get(key) or []:
            kept = evidenced(item)
            if kept and text(item.get(field)):
                ids, claim_ids, level = kept
                row = {field: text(item[field]), "span_ids": ids, "claim_ids": claim_ids, "basis": level, "start_ms": when(ids)}
                if key == "concepts":
                    row["explanation"] = text(item.get("explanation"))
                    # A concept starts at the earliest line it cites. The prompt asks for the line where the
                    # term is explained; a median start was tried and three blind evaluations in a row found
                    # it landing minutes after the explanation began.
                    row["start_ms"] = min(by_span[item].start_ms for item in ids)
                rows.append(row)
        out[key] = rows

    perspectives = []
    for item in raw.get("perspectives") or []:
        ids = cite(item.get("span_ids"))
        if ids and text(item.get("position")):
            perspectives.append({"speaker": bound(item.get("speaker"), ids, derive=True), "position": text(item["position"]),
                                 "span_ids": ids, "start_ms": when(ids)})
    perspectives.sort(key=lambda row: (row["start_ms"] is None, row["start_ms"] or 0))
    out["perspectives"] = perspectives

    diagram = raw.get("diagram") if isinstance(raw.get("diagram"), dict) else None
    out["diagram"] = None
    if diagram:
        ids = cite(diagram.get("span_ids"))
        source = _scrub(text(diagram.get("mermaid")))
        # The contract is a flowchart or a sequence diagram. Other mermaid types (gantt, xychart, radar, architecture, state diagrams with
        # classDef) are where the renderer's published denial-of-service and CSS-injection flaws sit, and a recording can steer what the model draws.
        if ids and source and source.split(None, 1)[0] in _DIAGRAMS and source.count("\n") <= 40:
            out["diagram"] = {"kind": diagram.get("kind") if diagram.get("kind") in {"flowchart", "sequence"} else "flowchart",
                              "title": text(diagram.get("title")), "mermaid": source, "span_ids": ids, "start_ms": when(ids)}
    # The same point written twice (or once per window) is one item: keep the first of each.
    for key, fields in (("summary", ("text",)), ("decisions", ("statement",)), ("actions", ("task",)), ("key_figures", ("value", "what")),
                        ("open_questions", ("question",)), ("risks", ("risk",)), ("concepts", ("term",)), ("perspectives", ("speaker", "position")),
                        ("disagreements", ("topic",))):
        seen, unique = set(), []
        for row in out.get(key) or []:
            sig = tuple(squash(str(row.get(field) or "")) for field in fields)
            if sig in seen:
                continue
            seen.add(sig)
            unique.append(row)
        out[key] = unique
    return out
