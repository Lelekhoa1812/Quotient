# Motivation vs Logic
# Motivation: A reviewer should see the most urgent already-queued claim first, without a second analysis pass.
# Logic: One Score question per queued id, stable sort by that score. HTTP failure, a refused prompt, or a missing id keeps the original order.

from __future__ import annotations

import json

from jev.client import MODEL, Client, JevFailed
from registry.check import validate
from registry.ids import REVIEW_SORT

STATE_PLUS_LONGEST = 32_000
REQUEST_LIMIT = 64_000


class Refused(RuntimeError):
    """Jev was pointed at a prompt other than the review-queue sort."""


def estimate_tokens(value) -> int:
    if isinstance(value, str):
        encoded = value.encode("utf-8")
    else:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return max(1, (len(encoded) + 3) // 4)


def pack_questions(state: str, keyed: list, estimate=estimate_tokens):
    groups: list = []
    current: list = []
    for item in keyed:
        if _overflows(state, [item], estimate):
            return None
        if current and _overflows(state, current + [item], estimate):
            groups.append(current)
            current = [item]
        else:
            current.append(item)
    if current:
        groups.append(current)
    return groups


def order(prompt_id: str, claims, queue, *, registry, client=None, env=None, estimate=estimate_tokens):
    if prompt_id != REVIEW_SORT:
        raise Refused(prompt_id)
    original = list(queue)
    if not original:
        return original
    if len(set(original)) != len(original):
        raise JevFailed(0)
    if client is None:
        client = Client.from_env(env)
    if client is None:
        return original
    prompt = registry.prompt(REVIEW_SORT)
    schema = registry.schema(REVIEW_SORT)
    state, question, criteria = _rubric(prompt)
    by_id = {}
    for claim in claims:
        by_id.setdefault(claim.id, claim)
    keyed = []
    for claim_id in original:
        claim = by_id.get(claim_id)
        if claim is None:
            raise JevFailed(0)
        keyed.append((claim_id, _question(claim, question, criteria)))
    groups = pack_questions(state, keyed, estimate)
    if not groups:
        raise JevFailed(0)
    scores = {}
    for group in groups:
        payload = {
            "model": MODEL,
            "state": state,
            "questions": {claim_id: item for claim_id, item in group},
        }
        data = client.evaluate(payload)
        answers = data.get("answers") if isinstance(data, dict) else None
        if not isinstance(answers, dict):
            raise JevFailed(0)
        for claim_id, _item in group:
            if claim_id not in answers:
                raise JevFailed(0)
            scores[claim_id] = _score(answers[claim_id], schema)
    positions = {claim_id: index for index, claim_id in enumerate(original)}
    return sorted(original, key=lambda claim_id: (-scores[claim_id], positions[claim_id]))


def apply_order(result, registry, client=None, estimate=estimate_tokens):
    original = list(result.review_queue)
    if not original:
        return result
    try:
        ordered = order(REVIEW_SORT, result.claims, original, registry=registry, client=client, estimate=estimate)
    except Exception:
        result.review_queue = original
        return result
    if len(ordered) != len(original) or set(ordered) != set(original):
        result.review_queue = original
        return result
    result.review_queue = ordered
    return result


def _rubric(prompt) -> tuple[str, str, list]:
    criteria = [item.strip() for item in prompt.criteria if isinstance(item, str) and item.strip()]
    question = prompt.question.strip()
    state = prompt.body.strip()
    if not state or not question or not 2 <= len(criteria) <= 10:
        raise JevFailed(0)
    return state, question, criteria


def _question(claim, question: str, criteria: list) -> dict:
    return {
        "type": "score",
        "instructions": {
            "id": claim.id,
            "proposition": claim.proposition,
            "quote": claim.quote,
            "question": question,
        },
        "criteria": list(criteria),
    }


def _score(answer, schema) -> float:
    if not isinstance(answer, dict) or isinstance(answer.get("score"), bool):
        raise JevFailed(0)
    projected = {"type": answer.get("type"), "score": answer.get("score")}
    validate(projected, schema)
    return float(projected["score"])


def _overflows(state: str, group: list, estimate) -> bool:
    longest = max(estimate(item) for _claim_id, item in group)
    if estimate(state) + longest >= STATE_PLUS_LONGEST:
        return True
    payload = {
        "model": MODEL,
        "state": state,
        "questions": {claim_id: item for claim_id, item in group},
    }
    return estimate(payload) >= REQUEST_LIMIT
