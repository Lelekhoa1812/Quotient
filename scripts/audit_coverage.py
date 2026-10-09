"""Motivation vs Logic

Motivation: Blind scoring says completeness is stuck at 3, but it cannot say where the walkaway is thin. This reads the stored meetings and
reports, with no model call, how much of each recording the digest touches: chapters, the share of spoken lines cited by any item, the
longest stretch of speech with no cited line, and items per ten minutes. Compare a new run against the table in docs/quality-ledger.md.
Logic: Project each meeting through the API gate (what a reader receives), collect every span id an item cites, and measure gaps in time.

Usage (repo root, worker venv): /tmp/quotient-worker-venv/bin/python scripts/audit_coverage.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from quotient.graph.gate import project_meeting  # noqa: E402

KEYS = ("summary", "decisions", "actions", "open_questions", "disagreements", "key_figures", "risks", "concepts", "perspectives")


def cited_ids(item: dict) -> list[str]:
    ids = list(item.get("span_ids") or []) + [item.get(key) for key in ("span_id", "asked_span_id", "answer_span_id") if item.get(key)]
    for position in item.get("positions") or []:
        ids += position.get("span_ids") or []
    return ids


def main() -> None:
    ledger = json.loads((ROOT / ".local" / "run" / "meetings.json").read_text())["meetings"]
    rows = ledger.values() if isinstance(ledger, dict) else ledger
    print(f"{'meeting':44} {'min':>4} {'chap':>4} {'speech':>6} {'cited%':>6} {'gap(min)':>8} {'items':>5} {'per10min':>8}")
    for row in rows:
        if not isinstance(row, dict):
            continue
        graph = project_meeting(row)["graph"]
        digest = graph.get("digest")
        speech = sorted((s for s in graph["spans"] if s.get("kind") == "speech" and s.get("start_ms") is not None), key=lambda s: s["start_ms"])
        if not digest or not speech:
            continue
        end = max(s.get("end_ms") or 0 for s in speech)
        cited: set[str] = set()
        items = 0
        for key in KEYS:
            for item in digest.get(key) or []:
                items += 1
                cited.update(cited_ids(item))
        marks = [0] + [s["start_ms"] for s in speech if s["span_id"] in cited] + [end]
        gap = max((b - a for a, b in zip(marks, marks[1:])), default=0) / 60000
        minutes = end / 60000
        share = 100 * sum(1 for s in speech if s["span_id"] in cited) / len(speech)
        print(f"{(digest.get('title') or '')[:42]:44} {minutes:4.0f} {len(digest.get('chapters') or []):4} {len(speech):6} {share:6.1f} {gap:8.1f} {items:5} {items / (minutes / 10):8.1f}")


if __name__ == "__main__":
    main()
