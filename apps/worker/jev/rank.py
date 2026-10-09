# Motivation vs Logic
# Motivation: A walkaway lists decisions, actions, figures and risks; the most important ones should
# come first. A thesis test (27 live calls) found Jev's score questions rank meeting statements well
# (top-5 5/5, Spearman 0.93, stable on repeat) at about 0.3 s per batch. It was not reliable as a
# yes/no gate, so it is used here only to order, never to include or exclude.
# Logic: One score question per item ("how important is this for someone who did not attend"),
# batched in one request per section, then a stable sort by score. Any failure (no key, HTTP error,
# missing answers) keeps the original order. Only each item's own short text and the recording's
# title are sent; transcript text is not.

from __future__ import annotations

from jev.client import MODEL, Client, JevFailed

CRITERIA = [
    "Not important for someone who missed this",
    "Minor detail",
    "Useful to know",
    "Important to know",
    "Essential: someone who missed this must know it",
]
QUESTION = "How important is this point for someone who did not attend and needs to act on the outcome?"
_SECTIONS = {"decisions": "statement", "actions": "task", "key_figures": "what", "risks": "risk"}


def rank_digest(digest: dict | None, *, client=None, env=None) -> dict | None:
    if not isinstance(digest, dict):
        return digest
    if client is None:
        client = Client.from_env(env)
    if client is None:
        return digest
    state = f"Recording: {digest.get('title') or 'untitled'}. Rank points by importance to a reader who was not there."
    for section, field in _SECTIONS.items():
        rows = digest.get(section) or []
        if len(rows) < 3:
            continue
        try:
            digest[section] = _ordered(client, state, rows, field)
        except (JevFailed, KeyError, TypeError, ValueError):
            continue
    return digest


def _ordered(client, state: str, rows: list[dict], field: str) -> list[dict]:
    questions = {}
    for index, row in enumerate(rows):
        text = str(row.get(field) or "")
        if section_value := row.get("value"):
            text = f"{section_value}: {text}"
        questions[f"i{index}"] = {
            "type": "score",
            "instructions": {"id": f"i{index}", "proposition": text[:400], "quote": "", "question": QUESTION},
            "criteria": CRITERIA,
        }
    data = client.evaluate({"model": MODEL, "state": state, "questions": questions})
    answers = data.get("answers") if isinstance(data, dict) else None
    if not isinstance(answers, dict):
        raise JevFailed(0)
    scores = {}
    for key in questions:
        answer = answers.get(key)
        if not isinstance(answer, dict) or not isinstance(answer.get("score"), (int, float)):
            raise JevFailed(0)
        scores[key] = float(answer["score"])
    order = sorted(range(len(rows)), key=lambda index: (-scores[f"i{index}"], index))
    return [rows[index] for index in order]
