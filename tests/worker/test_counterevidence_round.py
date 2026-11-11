"""The counter-evidence check must still know the claim after it has opened spans, and its final JSON step must not offer tools."""

import json
from types import SimpleNamespace

import loop.quality as quality
from bedrock.reason import Reasoner
from graph.state import Claim
from registry.load import Registry
from transcript.ingest import assemble_transcript

TEXT = "Maya: We agreed to launch the pilot in March with three customers.\nJon: I will own the connector by 14 March.\n"


def test_the_round_after_opening_spans_repeats_the_claim(tmp_path):
    path = tmp_path / "t.txt"
    path.write_text(TEXT, encoding="utf-8")
    ledger, _info = assemble_transcript(path, "m1")
    first = next(span for span in ledger.spans if span.kind == "speech")
    seen = []

    def call(prompt_id, payload):
        seen.append((prompt_id, payload))
        if prompt_id != "meeting.counterevidence.v1":
            return SimpleNamespace(output={"label": "entails"}, tool_calls=[])
        if len(seen) == 1:
            return SimpleNamespace(output={}, tool_calls=[SimpleNamespace(name="open_span", arguments={"span_id": first.id})])
        return SimpleNamespace(output={"searched_ids": [first.id], "finding": {"kind": "empty"}}, tool_calls=[])

    claim = Claim(
        id="c0", meeting_id="m1", kind="decision", proposition="x",
        paraphrase="The pilot launches in March.", quote="We agreed to launch the pilot in March", span_id=first.id, source_span_ids=[first.id],
    )
    quality._contest(ledger, call, claim)
    counter = [payload for prompt_id, payload in seen if prompt_id == "meeting.counterevidence.v1"]
    assert len(counter) == 2
    fill = counter[1]
    assert fill["_fill"] is True and fill["tool_results"][0]["span_id"] == first.id
    assert fill["paraphrase"] == "The pilot launches in March." and fill["quotes"] == ["We agreed to launch the pilot in March"]


def test_the_final_json_step_of_a_tool_prompt_names_no_tool():
    registry = Registry()
    prompt = registry.prompt("meeting.counterevidence.v1")
    schema = registry.schema(prompt.schema_id)
    reasoner = Reasoner(registry, transport=None)
    model_id, cap, _fallback = reasoner._role(prompt.model_role)
    tool_name = prompt.tools[0]["name"]

    def system_text(schema_mode):
        request = reasoner._request(model_id, cap, prompt, schema, {"paraphrase": "p"}, schema_mode, "earlier findings", tools=False)
        return request["input"][0]["content"][0]["text"]

    final, first = system_text(True), system_text(False)
    assert json.dumps(prompt.tools, sort_keys=True) in first
    assert json.dumps(prompt.tools, sort_keys=True) not in final
    assert "final step" in final and "Do not call any tool" in final
    assert "final step" not in first


def test_entailment_sees_who_said_the_cited_line(tmp_path):
    path = tmp_path / "t.txt"
    path.write_text(TEXT, encoding="utf-8")
    ledger, _info = assemble_transcript(path, "m1")
    first = next(span for span in ledger.spans if span.kind == "speech")
    seen = []

    def call(prompt_id, payload):
        seen.append((prompt_id, payload))
        if prompt_id == "meeting.counterevidence.v1":
            return SimpleNamespace(output={"searched_ids": [first.id], "finding": {"kind": "empty"}}, tool_calls=[])
        return SimpleNamespace(output={"label": "entails"}, tool_calls=[])

    claim = Claim(
        id="c0", meeting_id="m1", kind="decision", proposition="x",
        paraphrase="Speaker spk_0 says the pilot launches in March.", quote="We agreed to launch the pilot in March", span_id=first.id, source_span_ids=[first.id],
    )
    quality._contest(ledger, call, claim)
    packs = [payload for prompt_id, payload in seen if prompt_id.startswith("meeting.entailment")]
    assert packs and all(pack["cited_span_texts"][0].startswith(f"{first.speaker_hypothesis_id}: ") for pack in packs)


def test_a_review_that_lost_the_transcript_never_replaces_the_draft(monkeypatch):
    draft = {"summary": ["a"], "chapters": [1, 2], "actions": [1]}
    bad = {"summary": ["a"], "chapters": [1, 2], "actions": [1], "outcome": {"text": "Note: The transcript was not provided for this review."}}
    monkeypatch.setattr(quality, "complete_with_tools", lambda *a, **k: SimpleNamespace(output=bad))
    kept = quality._reviewed(lambda *a: None, {}, {"x": 1}, draft, lambda raw: raw)
    assert kept is draft
    good = {"summary": ["a"], "chapters": [1, 2], "actions": [1], "outcome": {"text": "Fine."}}
    monkeypatch.setattr(quality, "complete_with_tools", lambda *a, **k: SimpleNamespace(output=good))
    assert quality._reviewed(lambda *a: None, {}, {"x": 1}, draft, lambda raw: raw) is good
