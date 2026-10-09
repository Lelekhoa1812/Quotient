"""Motivation vs Logic

Motivation: Blind scoring needs, per meeting, a plain-text transcript and a plain-text walkaway that show what a
person sees. The first version of this script lived in a scratch folder and printed "unknown" for an empty
decider or owner; an evaluator scored that text and the attribution result in Round 13 was partly that formatting
error, not the product (the portal shows no "Decided by" line, and "No owner named" for an action).
Logic: Read .local/run/meetings.json, project each meeting through the API gate (so the evaluator sees what a client
would receive, read-time filters included), and write <out>/<label>_transcript.txt and <out>/<label>_walkaway.txt.
An empty owner or decider is printed as "(not stated)", exactly the meaning the portal gives it.

Usage (repo root, worker venv):
  /tmp/quotient-worker-venv/bin/python scripts/build_eval_inputs.py OUT_DIR label=MEETING_ID [label=MEETING_ID ...]
Example:
  /tmp/quotient-worker-venv/bin/python scripts/build_eval_inputs.py /tmp/eval sbc=IM3PxoZaTjpGQzqk sales=F8EvL69EiM3F5TRW
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from quotient.graph.gate import project_meeting  # noqa: E402

NOT_STATED = "(not stated)"


def clock(ms: float) -> str:
    return f"{int(ms // 60000)}:{int(ms // 1000) % 60:02d}"


def build(row: dict, out_dir: Path, label: str) -> tuple[int, int]:
    graph = project_meeting(row)["graph"]
    digest = graph.get("digest")
    if not digest:
        raise SystemExit(f"{label}: this meeting has no digest (analysed before summaries existed or failed)")
    named = {s["id"]: s["name"] for s in digest.get("speakers") or [] if s.get("id") and s.get("name")}

    def voice(value):
        """A voice as a reader sees it: the name the transcript gives, else Speaker N, else nothing."""
        if not value:
            return NOT_STATED
        if value in named:
            return named[value]
        return f"Speaker {int(value[4:]) + 1}" if isinstance(value, str) and re.fullmatch(r"spk_\d+", value) else value

    def fix(text):
        return re.sub(r"\bspk_(\d+)\b", lambda m: named.get(m.group(0)) or f"Speaker {int(m.group(1)) + 1}", text or "")

    lines = []
    speech = [s for s in graph["spans"] if s.get("kind") == "speech"]
    for span in sorted(speech, key=lambda s: s.get("start_ms") or 0):
        who = voice(span.get("speaker_hypothesis_id")) if span.get("speaker_hypothesis_id") else "unknown speaker"
        lines.append(f"[{clock(span.get('start_ms') or 0)}] {who}: {span.get('text') or span.get('raw_text')}")
    (out_dir / f"{label}_transcript.txt").write_text("\n".join(lines), encoding="utf-8")

    walk = [f"TITLE: {digest.get('title')}", f"TYPE: {digest.get('content_type')}", "", "SUMMARY:"]
    walk += [f"- {fix(x['text'])}" for x in digest.get("summary") or []]
    if digest.get("outcome"):
        walk += ["", "WHERE IT ENDED: " + fix(digest["outcome"]["text"])]

    def section(title, items, render):
        if items:
            walk.extend(["", title + ":"] + [render(x) for x in items])

    at = lambda x: f"@{clock(x.get('start_ms') or 0)}"  # noqa: E731
    section("DECISIONS", digest.get("decisions"), lambda x: f"- [{x.get('status')}] {fix(x['statement'])} (decided by {voice(x.get('decided_by'))}) {at(x)}")
    section("ACTIONS", digest.get("actions"), lambda x: f"- {fix(x['task'])} | owner: {voice(x.get('assignee'))} | due: {x.get('due') or NOT_STATED} | agreed: {x.get('agreed')} {at(x)}")
    section("QUESTIONS", digest.get("open_questions"), lambda x: f"- {fix(x['question'])} | answered: {x.get('answered')} | {fix(x.get('answer') or '')} {at(x)}")
    section("DISAGREEMENTS", digest.get("disagreements"), lambda x: f"- {fix(x.get('topic') or '')}: " + " VS ".join(f"{voice(p.get('speaker'))}: {fix(p.get('position') or p.get('text') or '')}" for p in x.get("positions") or []))
    section("WHO ARGUED WHAT", digest.get("perspectives"), lambda x: f"- {voice(x.get('speaker'))}: {fix(x.get('position') or x.get('text') or '')} {at(x)}")
    section("KEY FIGURES", digest.get("key_figures"), lambda x: f"- {x['value']}: {fix(x['what'])} {at(x)}")
    section("RISKS", digest.get("risks"), lambda x: f"- {fix(x.get('text') or x.get('risk') or '')}")
    section("CONCEPTS", digest.get("concepts"), lambda x: f"- {x.get('term')}: {fix(x.get('explanation') or '')}")
    section("TOPICS", digest.get("chapters"), lambda x: f"- {clock(x.get('start_ms') or 0)} {x.get('title')}: {fix(x.get('gist') or '')}")
    (out_dir / f"{label}_walkaway.txt").write_text("\n".join(walk), encoding="utf-8")
    return len(lines), len(walk)


def main(argv: list[str]) -> None:
    if len(argv) < 2 or any("=" not in a for a in argv[1:]):
        raise SystemExit(__doc__)
    out_dir = Path(argv[0])
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger = json.loads((ROOT / ".local" / "run" / "meetings.json").read_text())["meetings"]
    rows = ledger.values() if isinstance(ledger, dict) else ledger
    by_id = {r["meeting_id"]: r for r in rows if isinstance(r, dict) and r.get("meeting_id")}
    for pair in argv[1:]:
        label, meeting_id = pair.split("=", 1)
        if meeting_id not in by_id:
            raise SystemExit(f"{label}: meeting {meeting_id} is not in .local/run/meetings.json")
        spans, walk = build(by_id[meeting_id], out_dir, label)
        print(f"{label}: {spans} transcript lines, {walk} walkaway lines -> {out_dir}")


if __name__ == "__main__":
    main(sys.argv[1:])
