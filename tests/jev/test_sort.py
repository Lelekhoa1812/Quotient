import json

import pytest

from bedrock.turn import ModelTurn
from errors import SchemaRejected
from graph.publish import GateResult, gate
from graph.span import Span
from graph.state import Claim
from jev.client import MODEL, Client, JevFailed
from jev.sort import Refused, apply_order, order, pack_questions
from loop.quality import Ledger, run
from loop.store import MemoryStore
from registry.check import validate
from registry.ids import ENTAILMENT_LUNA, ENTAILMENT_SOL, LENS_ORDER, REVIEW_SORT, SYNTHESIS
from registry.load import Registry
from registry.pins import PROMPT_ROLE


def claim(claim_id, proposition, quote, **kwargs):
    return Claim(
        id=claim_id,
        meeting_id="m",
        kind="figure",
        proposition=proposition,
        paraphrase="paraphrase away from the proposition",
        quote=quote,
        **kwargs,
    )


def queued_result(ids, claims):
    return GateResult(
        status="needs_review",
        brief={"sentences": [], "finding_ids": [], "claim_ids": []},
        review_queue=list(ids),
        dimensions={name: "none_in_transcript" for name in LENS_ORDER},
        findings=[],
        synthesis=[],
        synthesis_omissions=[],
        actions=[],
        claims=claims,
        disagreements=[],
        omissions=[],
        gaps=[],
        audit={},
        artifacts={},
    )


class Answers:
    def __init__(self, scores, *, confidence=None):
        self.scores = scores
        self.confidence = confidence or {}
        self.payloads = []

    def evaluate(self, payload):
        self.payloads.append(payload)
        answers = {}
        for claim_id in payload["questions"]:
            answer = {"type": "score", "score": self.scores[claim_id]}
            if claim_id in self.confidence:
                answer["confidence"] = self.confidence[claim_id]
            answers[claim_id] = answer
        return {"answers": answers}


def test_score_order_follows_urgency_and_sends_only_the_queue():
    logo = claim("logo", "The logo uses blue.", "The logo is blue.", char_start=4, char_end=12)
    ship = claim("ship", "Ship the notes tomorrow.", "Please ship the notes tomorrow.")
    refund = claim("refund", "Refund the duplicate charge today or the customer cancels.", "Cancel by today.")
    secret = claim("kept", "SECRET-SUPPORTED", "secret quote", status="supported")
    result = queued_result(["logo", "ship", "refund"], [logo, ship, refund, secret])
    client = Answers({"logo": 0.41, "ship": 1.77, "refund": 2.95}, confidence={"logo": 0.99, "ship": 0.6, "refund": 0.1})
    apply_order(result, Registry(), client=client)
    assert result.review_queue == ["refund", "ship", "logo"]
    assert result.status == "needs_review"
    assert result.brief["claim_ids"] == []
    assert logo.status == "unresolved"
    payload = client.payloads[0]
    encoded = json.dumps(payload)
    prompt = Registry().prompt(REVIEW_SORT)
    assert payload["model"] == MODEL == "jev-1.13.0"
    assert payload["state"] == prompt.body.strip()
    assert set(payload) == {"model", "state", "questions"}
    assert set(payload["questions"]) == {"logo", "ship", "refund"}
    assert payload["questions"]["refund"]["type"] == "score"
    assert payload["questions"]["refund"]["criteria"] == list(prompt.criteria)
    assert payload["questions"]["refund"]["instructions"]["proposition"] == refund.proposition
    assert payload["questions"]["refund"]["instructions"]["quote"] == refund.quote
    assert "SECRET-SUPPORTED" not in encoded
    assert "char_start" not in encoded
    assert "confidence" not in encoded


def test_tie_keeps_original_order():
    claims = [claim("a", "Send the recap.", "Send the recap."), claim("b", "Send the note.", "Send the note.")]
    result = queued_result(["a", "b"], claims)
    apply_order(result, Registry(), client=Answers({"a": 1.0, "b": 1.0}))
    assert result.review_queue == ["a", "b"]


def test_confidence_does_not_reorder():
    claims = [claim("logo", "The logo uses blue.", "The logo is blue."), claim("refund", "Refund today.", "Refund today.")]
    result = queued_result(["logo", "refund"], claims)
    client = Answers({"logo": 0.41, "refund": 2.95}, confidence={"logo": 0.99, "refund": 0.1})
    apply_order(result, Registry(), client=client)
    assert result.review_queue == ["refund", "logo"]


def test_http_failure_keeps_order_status_and_brief():
    queued = claim("c1", "Ship the notes tomorrow.", "Please ship the notes tomorrow.", span_id="s1")
    span = Span(id="s1", meeting_id="m", kind="speech", start_ms=0, end_ms=1000, raw_text="Please ship the notes tomorrow.")
    result = gate(
        meeting_id="m",
        duration_ms=10_000,
        spans=[span],
        claims=[queued],
        findings=[],
        sentences=[],
        synthesis_omissions=[],
        actions=[],
        disagreements=[],
        omissions=[],
        gaps=[],
        dimensions={name: "none_in_transcript" for name in LENS_ORDER},
        ceiling_hit=False,
    )
    assert result.status == "needs_review"
    assert queued.id in result.review_queue
    assert queued.id not in result.brief["claim_ids"]
    calls = []

    def transport(payload):
        calls.append(payload)
        return 401, {}, b"{}"

    apply_order(result, Registry(), client=Client("test-key", transport=transport))
    assert calls and len(calls) == 1
    assert result.review_queue == [queued.id]
    assert queued.id not in result.brief["claim_ids"]
    assert queued.status == "unresolved"
    assert result.status == "needs_review"


@pytest.mark.parametrize("status", [401, 422, 529])
def test_auth_validation_and_overload_do_not_retry(status):
    seen = []

    def transport(payload):
        seen.append(status)
        return status, {"Retry-After": "1"}, json.dumps({"detail": "SECRET-BODY"}).encode()

    client = Client("test-key", transport=transport, sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("slept")))
    with pytest.raises(JevFailed) as caught:
        client.evaluate({"model": MODEL, "state": "synthetic", "questions": {}})
    assert caught.value.status == status
    assert seen == [status]
    assert "SECRET-BODY" not in str(caught.value)


def test_timeout_keeps_the_original_order():
    claims = [claim("a", "One.", "One."), claim("b", "Two.", "Two.")]
    result = queued_result(["a", "b"], claims)

    class Down:
        def evaluate(self, payload):
            raise TimeoutError()

    apply_order(result, Registry(), client=Down())
    assert result.review_queue == ["a", "b"]


def test_429_honors_retry_after_once():
    claims = [claim("logo", "The logo uses blue.", "The logo is blue."), claim("refund", "Refund today.", "Refund today.")]
    result = queued_result(["logo", "refund"], claims)
    steps = [
        (429, {"Retry-After": "0"}, {}),
        (200, {}, {"answers": {"logo": {"type": "score", "score": 0.41}, "refund": {"type": "score", "score": 2.95}}}),
    ]
    slept = []

    def transport(payload):
        status, headers, body = steps.pop(0)
        return status, headers, json.dumps(body).encode()

    apply_order(result, Registry(), client=Client("test-key", transport=transport, sleep=slept.append))
    assert slept == [0]
    assert result.review_queue == ["refund", "logo"]


def test_second_429_keeps_the_original_order():
    claims = [claim("a", "One.", "One."), claim("b", "Two.", "Two.")]
    result = queued_result(["a", "b"], claims)
    seen = []

    def transport(payload):
        seen.append(payload)
        return 429, {"Retry-After": "0"}, b"{}"

    apply_order(result, Registry(), client=Client("test-key", transport=transport, sleep=lambda _seconds: None))
    assert len(seen) == 2
    assert result.review_queue == ["a", "b"]


def test_empty_queue_does_not_call():
    result = queued_result([], [])

    class Down:
        def evaluate(self, payload):
            raise AssertionError("called")

    apply_order(result, Registry(), client=Down())
    assert result.review_queue == []


def test_missing_key_keeps_the_original_order():
    claims = [claim("a", "One.", "One.")]
    ordered = order(REVIEW_SORT, claims, ["a"], registry=Registry(), client=None, env={})
    assert ordered == ["a"]
    assert Client.from_env({}) is None


@pytest.mark.parametrize("prompt_id", [ENTAILMENT_SOL, ENTAILMENT_LUNA, SYNTHESIS])
def test_entailment_and_synthesis_are_refused(prompt_id):
    class Down:
        def evaluate(self, payload):
            raise AssertionError("called")

    with pytest.raises(Refused):
        order(prompt_id, [], ["c1"], registry=None, client=Down())


def test_missing_answer_keeps_every_id():
    claims = [claim("a", "One.", "One."), claim("b", "Two.", "Two.")]
    result = queued_result(["a", "b"], claims)

    class Partial:
        def evaluate(self, payload):
            return {"answers": {"a": {"type": "score", "score": 3}}}

    apply_order(result, Registry(), client=Partial())
    assert result.review_queue == ["a", "b"]


def test_noul_answer_does_not_reorder():
    claims = [claim("a", "One.", "One."), claim("b", "Two.", "Two.")]
    result = queued_result(["a", "b"], claims)

    class Noul:
        def evaluate(self, payload):
            return {"answers": {"a": {"type": "noul", "noul": 0.1}, "b": {"type": "noul", "noul": 0.9}}}

    apply_order(result, Registry(), client=Noul())
    assert result.review_queue == ["a", "b"]


def test_sol_and_luna_roles_are_unchanged():
    prompt = Registry().prompt(REVIEW_SORT)
    assert prompt.model_role is None
    assert REVIEW_SORT not in PROMPT_ROLE
    assert PROMPT_ROLE[ENTAILMENT_SOL] == "llm"
    assert PROMPT_ROLE[ENTAILMENT_LUNA] == "slm"
    schema = Registry().schema(REVIEW_SORT)
    validate({"type": "score", "score": 1.5}, schema)
    with pytest.raises(SchemaRejected):
        validate({"type": "noul", "noul": 0.9}, schema)
    with pytest.raises(SchemaRejected):
        validate({"type": "score", "score": True}, schema)


def test_pack_splits_on_the_vendor_request_limit_and_not_sooner():
    keyed = [("a", {"n": 1}), ("b", {"n": 2})]

    def estimate(value):
        if isinstance(value, str):
            return 10
        if isinstance(value, dict) and "model" in value:
            return 70_000 if len(value["questions"]) > 1 else 100
        return 100

    assert pack_questions("shared", keyed, estimate) == [[keyed[0]], [keyed[1]]]

    def too_big(value):
        if isinstance(value, str):
            return 32_000
        return 1

    assert pack_questions("shared", [("a", {"n": 1})], too_big) is None


def test_unsplittable_queue_keeps_original_order():
    claims = [claim("a", "One.", "One."), claim("b", "Two.", "Two.")]
    result = queued_result(["a", "b"], claims)

    class Down:
        def evaluate(self, payload):
            raise AssertionError("called")

    def too_big(value):
        if isinstance(value, str):
            return 32_000
        return 1

    apply_order(result, Registry(), client=Down(), estimate=too_big)
    assert result.review_queue == ["a", "b"]


def test_run_sorts_after_the_gate(monkeypatch):
    logo = claim("logo", "The logo uses blue.", "The logo is blue.")
    refund = claim("refund", "Refund today.", "Refund today.")
    queued = queued_result(["logo", "refund"], [logo, refund])
    monkeypatch.setattr("loop.quality.gate", lambda **kwargs: queued)
    calls = []

    class Model:
        def complete(self, *, prompt_id, role, payload, max_output_tokens=None):
            calls.append({"prompt_id": prompt_id, "role": role})
            return ModelTurn(output={"result": "none_in_transcript", "charts": []})

    client = Answers({"logo": 0.41, "refund": 2.95})
    result = run(Ledger("m", 1000, "audio", []), Model(), Registry(), MemoryStore(), "k", review_client=client)
    assert result.review_queue == ["refund", "logo"]
    assert result.status == "needs_review"
    assert refund.id not in result.brief["claim_ids"]
    assert {call["role"] for call in calls} <= {"llm", "slm"}
    assert REVIEW_SORT not in {call["prompt_id"] for call in calls}
    assert client.payloads


def test_walkaway_items_are_ordered_by_importance_and_fail_open():
    from jev.client import Client
    from jev.rank import rank_digest

    def transport(payload):
        scores = {"i0": 1.0, "i1": 3.6, "i2": 2.2}
        answers = {key: {"type": "score", "score": scores[key]} for key in payload["questions"]}
        return 200, {}, __import__("json").dumps({"answers": answers})

    digest = {
        "title": "Pilot",
        "decisions": [{"statement": "Minor"}, {"statement": "Critical"}, {"statement": "Useful"}],
        "actions": [{"task": "only one"}],
    }
    ranked = rank_digest(dict(digest), client=Client("key", transport=transport))
    assert [row["statement"] for row in ranked["decisions"]] == ["Critical", "Useful", "Minor"]
    assert ranked["actions"] == [{"task": "only one"}]

    def broken(payload):
        return 500, {}, "{}"

    kept = rank_digest(dict(digest), client=Client("key", transport=broken, sleep=lambda _s: None))
    assert [row["statement"] for row in kept["decisions"]] == ["Minor", "Critical", "Useful"]
    assert rank_digest(dict(digest), env={}) == digest  # no key: unchanged
