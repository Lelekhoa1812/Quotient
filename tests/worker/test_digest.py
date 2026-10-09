from graph.digest import claim_rows, ground_digest, transcript_lines
from graph.span import Span
from graph.state import Claim


def _span(span_id, text, start, end, speaker=None):
    return Span(
        id=span_id, meeting_id="m", kind="speech", start_ms=start, end_ms=end,
        raw_text=text, text=text, speaker_hypothesis_id=speaker,
    )


SPANS = [
    _span("s1", "We pick about one thousand orders every day.", 0, 4000, "spk_0"),
    _span("s2", "So the pilot starts on the third of November.", 5000, 9000, "spk_1"),
    _span("s3", "Who owns the scanner order?", 10000, 12000, "spk_0"),
    _span("s4", "Priya owns it and will confirm by Monday.", 13000, 17000, "spk_1"),
    _span("s5", "I disagree, we should wait until January.", 18000, 21000, "spk_0"),
]


def _claim(claim_id, span_id, confidence):
    claim = Claim(id=claim_id, meeting_id="m", kind="decision", proposition="p", paraphrase="p", quote="q", span_id=span_id)
    claim.confidence = confidence
    return claim


CLAIMS = [_claim("c-ok", "s2", "confirmed"), _claim("c-likely", "s4", "likely"), _claim("c-weak", "s5", "unverified")]
SPEAKERS = {"spk_0", "spk_1"}


def _raw(**overrides):
    base = {
        "content_type": "meeting",
        "title": "Warehouse pilot",
        "summary": [{"text": "The pilot starts in November.", "span_ids": ["s2", "nope"], "claim_ids": ["c-ok"]}],
        "chapters": [],
        "decisions": [],
        "actions": [],
        "open_questions": [],
        "disagreements": [],
        "key_figures": [],
        "risks": [],
        "concepts": [],
        "diagram": None,
    }
    base.update(overrides)
    return base


def test_unknown_citations_are_dropped_and_times_come_from_spans():
    digest = ground_digest(_raw(), SPANS, CLAIMS, [], SPEAKERS)
    assert digest["summary"] == [
        {"text": "The pilot starts in November.", "span_ids": ["s2"], "claim_ids": ["c-ok"], "basis": "confirmed", "start_ms": 5000}
    ]
    empty = ground_digest(_raw(summary=[{"text": "Invented.", "span_ids": ["zzz"], "claim_ids": []}]), SPANS, CLAIMS, [], SPEAKERS)
    assert empty["summary"] == []


def test_decisions_need_confirmed_or_likely_evidence_and_carry_the_weakest_basis():
    raw = _raw(decisions=[
        {"statement": "Start in November", "status": "agreed", "decided_by": "spk_1", "span_ids": ["s2"], "claim_ids": ["c-ok"]},
        {"statement": "Priya confirms Monday", "status": "agreed", "decided_by": "Priya", "span_ids": ["s4"], "claim_ids": ["c-ok", "c-likely"]},
        {"statement": "Wait until January", "status": "agreed", "decided_by": None, "span_ids": ["s5"], "claim_ids": ["c-weak"]},
        {"statement": "No evidence at all", "status": "agreed", "decided_by": None, "span_ids": ["s1"], "claim_ids": []},
    ])
    decisions = ground_digest(raw, SPANS, CLAIMS, [], SPEAKERS)["decisions"]
    assert [(d["statement"], d["basis"], d["decided_by"]) for d in decisions] == [
        ("Start in November", "confirmed", "spk_1"),
        ("Priya confirms Monday", "likely", None),  # a name not in the transcript labels is not kept
    ]


def test_a_key_figure_must_appear_in_its_span():
    raw = _raw(key_figures=[
        {"value": "1,000 orders per day", "what": "Picking volume", "span_id": "s1"},
        {"value": "5,000 orders per day", "what": "Invented volume", "span_id": "s1"},
    ])
    figures = ground_digest(raw, SPANS, CLAIMS, [], SPEAKERS)["key_figures"]
    assert [f["value"] for f in figures] == ["1,000 orders per day"]


def test_a_question_is_answered_only_by_a_later_span():
    raw = _raw(open_questions=[
        {"question": "Who owns the scanner order?", "asked_by": "spk_0", "asked_span_id": "s3", "answered": True,
         "answer": "Priya", "answer_span_id": "s4"},
        {"question": "When does the pilot start?", "asked_by": None, "asked_span_id": "s3", "answered": True,
         "answer": "November", "answer_span_id": "s2"},
    ])
    questions = ground_digest(raw, SPANS, CLAIMS, [], SPEAKERS)["open_questions"]
    assert [(q["answered"], q["answer_ms"]) for q in questions] == [(True, 13000), (False, None)]


def test_chapters_are_ordered_and_never_overlap():
    raw = _raw(chapters=[
        {"title": "Decision", "gist": "g", "start_span_id": "s2", "end_span_id": "s5"},
        {"title": "Volume", "gist": "g", "start_span_id": "s1", "end_span_id": "s2"},
        {"title": "Bogus", "gist": "g", "start_span_id": "missing", "end_span_id": "s5"},
    ])
    chapters = ground_digest(raw, SPANS, CLAIMS, [], SPEAKERS)["chapters"]
    assert [(c["title"], c["start_ms"], c["end_ms"]) for c in chapters] == [("Volume", 0, 5000), ("Decision", 5000, 21000)]


def test_disagreements_need_two_cited_positions():
    raw = _raw(disagreements=[
        {"topic": "Start date", "positions": [
            {"speaker": "spk_1", "position": "November", "span_ids": ["s2"]},
            {"speaker": "spk_0", "position": "January", "span_ids": ["s5"]},
        ]},
        {"topic": "One-sided", "positions": [
            {"speaker": "spk_1", "position": "Yes", "span_ids": ["s2"]},
            {"speaker": "spk_0", "position": "No", "span_ids": ["unknown"]},
        ]},
    ])
    rows = ground_digest(raw, SPANS, CLAIMS, [], SPEAKERS)["disagreements"]
    assert [row["topic"] for row in rows] == ["Start date"]


def test_unsafe_diagram_is_scrubbed_or_dropped():
    safe = _raw(diagram={"kind": "flowchart", "title": "Flow", "span_ids": ["s1"],
                         "mermaid": "flowchart LR\n  A[Order] --> B[Pick]\n  click A \"javascript:alert(1)\""})
    diagram = ground_digest(safe, SPANS, CLAIMS, [], SPEAKERS)["diagram"]
    assert diagram and "javascript" not in diagram["mermaid"] and "click" not in diagram["mermaid"]
    bogus = _raw(diagram={"kind": "flowchart", "title": "x", "span_ids": ["s1"], "mermaid": "<script>alert(1)</script>"})
    assert ground_digest(bogus, SPANS, CLAIMS, [], SPEAKERS)["diagram"] is None


def test_actions_may_rest_on_a_grounded_action_record():
    class Action:
        statement = "Confirm scanner date"
        due_surface = "by Monday"

    raw = _raw(actions=[
        {"task": "Confirm scanner date", "owner": "spk_1", "due": "Monday", "agreed": True, "span_ids": ["s4"], "claim_ids": [], "action_id": "a0"},
        {"task": "Untraceable", "owner": None, "due": None, "agreed": False, "span_ids": ["s4"], "claim_ids": [], "action_id": "a9"},
    ])
    actions = ground_digest(raw, SPANS, CLAIMS, [Action()], SPEAKERS)["actions"]
    assert [(a["task"], a["action_id"], a["basis"], a["assignee"]) for a in actions] == [("Confirm scanner date", "a0", "likely", "spk_1")]


def test_payload_helpers_send_only_speech_with_text_and_only_confirmed_or_likely_claims():
    rows = transcript_lines(SPANS + [_span("s6", "  ", 22000, 23000)], lambda span: span.speaker_hypothesis_id or "unknown")
    assert [row["id"] for row in rows] == ["s1", "s2", "s3", "s4", "s5"]
    assert rows[1] == {"id": "s2", "t": "0:05", "speaker": "spk_1", "text": "So the pilot starts on the third of November."}
    assert [row["id"] for row in claim_rows(CLAIMS)] == ["c-ok", "c-likely"]


def test_garbage_output_yields_no_digest():
    assert ground_digest(None, SPANS, CLAIMS, [], SPEAKERS) is None
    assert ground_digest("text", SPANS, CLAIMS, [], SPEAKERS) is None


def test_grouped_numbers_are_one_quantity():
    from graph.numbers import grounded

    assert grounded("1,000 orders", "We pick about one thousand orders every day.")
    assert not grounded("1,000 people", "about 1,000,000 people")
    assert not grounded("5,000 orders", "one thousand orders")
    assert grounded("$42,000", "a budget of $42,000")


def test_outcome_needs_a_cited_span_and_text():
    good = ground_digest(_raw(outcome={"text": "No decision yet; a follow-up call is planned.", "span_ids": ["s4", "gone"]}), SPANS, CLAIMS, [], SPEAKERS)
    assert good["outcome"] == {"text": "No decision yet; a follow-up call is planned.", "span_ids": ["s4"], "start_ms": 13000}
    assert ground_digest(_raw(outcome={"text": "Invented.", "span_ids": ["gone"]}), SPANS, CLAIMS, [], SPEAKERS)["outcome"] is None
    assert ground_digest(_raw(outcome=None), SPANS, CLAIMS, [], SPEAKERS)["outcome"] is None


def test_a_speaker_name_must_appear_in_a_cited_span():
    spans = [
        _span("n1", "Thank you, Dr. Casserly, for being here.", 0, 3000, "spk_0"),
        _span("n2", "Happy to be here.", 3000, 5000, "spk_1"),
    ]
    raw = _raw(speakers=[
        {"id": "spk_1", "name": "Dr. Casserly", "role": "witness", "span_ids": ["n1"]},
        {"id": "spk_0", "name": "Mr. Hoekstra", "role": "chair", "span_ids": ["n1"]},  # not said in n1
        {"id": "spk_9", "name": "Ghost", "role": None, "span_ids": ["n1"]},  # unknown voice
    ])
    digest = ground_digest(raw, spans, [], [], {"spk_0", "spk_1"})
    assert digest["speakers"] == [{"id": "spk_1", "name": "Dr. Casserly", "role": "witness", "span_ids": ["n1"]}]


def test_a_disagreement_needs_two_distinct_identified_voices():
    raw = _raw(disagreements=[
        {"topic": "Same voice twice", "positions": [
            {"speaker": "spk_0", "position": "For", "span_ids": ["s1"]},
            {"speaker": "spk_0", "position": "Against", "span_ids": ["s5"]},
        ]},
        {"topic": "Unidentified", "positions": [
            {"speaker": None, "position": "For", "span_ids": ["s1"]},
            {"speaker": None, "position": "Against", "span_ids": ["s5"]},
        ]},
    ])
    assert ground_digest(raw, SPANS, CLAIMS, [], SPEAKERS)["disagreements"] == []


def test_outside_an_ordinary_meeting_an_action_needs_a_named_owner_who_agreed():
    candidates = [
        {"task": "Expand the tests", "owner": None, "due": None, "agreed": True, "span_ids": ["s4"], "claim_ids": ["c-ok"], "action_id": None},
        {"task": "Send the quote", "owner": "spk_1", "due": "Monday", "agreed": True, "span_ids": ["s4"], "claim_ids": ["c-ok"], "action_id": None},
        {"task": "Maybe send notes", "owner": "spk_1", "due": None, "agreed": False, "span_ids": ["s4"], "claim_ids": ["c-ok"], "action_id": None},
        # Said by a different voice than the one it names: a prediction about someone else, not their commitment.
        {"task": "Will file the report", "owner": "spk_0", "due": None, "agreed": False, "span_ids": ["s4"], "claim_ids": ["c-ok"], "action_id": None},
    ]
    hearing = ground_digest(_raw(content_type="discussion", actions=candidates), SPANS, CLAIMS, [], SPEAKERS)["actions"]
    assert [a["task"] for a in hearing] == ["Send the quote", "Maybe send notes"]  # agreed, or said by its owner
    assert [a["agreed"] for a in hearing] == [True, False]
    meeting = ground_digest(_raw(content_type="meeting", actions=candidates), SPANS, CLAIMS, [], SPEAKERS)["actions"]
    assert len(meeting) == 4


def test_a_malformed_value_costs_one_item_not_the_whole_walkaway():
    raw = _raw(
        summary=["plain text", {"text": "Good line.", "span_ids": ["s2"], "claim_ids": []}],
        open_questions=[{"question": "Who?", "asked_span_id": "s3", "answered": True, "answer_span_id": ["s4"], "answer": "Priya"}],
        actions="not a list",
        chapters=[{"title": "T", "gist": "g", "start_span_id": {"x": 1}, "end_span_id": 5}],
    )
    out = ground_digest(raw, SPANS, CLAIMS, [], SPEAKERS)
    assert [row["text"] for row in out["summary"]] == ["Good line."]
    assert out["actions"] == [] and out["chapters"] == []
    assert out["open_questions"][0]["answered"] is False


def test_a_line_cannot_answer_itself_and_names_match_whole_words():
    raw = _raw(
        open_questions=[{"question": "Who owns it?", "asked_by": "spk_0", "asked_span_id": "s3", "answered": True, "answer": "me", "answer_span_id": "s3"}],
        speakers=[
            {"id": "spk_1", "name": "Pri", "role": None, "span_ids": ["s4"]},       # "Pri" is inside "Priya", not a word
            {"id": "spk_0", "name": "Priya", "role": None, "span_ids": ["s4"]},     # a whole word in the cited line
        ],
    )
    out = ground_digest(raw, SPANS, CLAIMS, [], SPEAKERS)
    assert out["open_questions"][0]["answered"] is False
    assert [row["name"] for row in out["speakers"]] == ["Priya"]


def test_quoted_promises_need_three_whole_words_and_ledger_links_need_shared_words():
    class Ledger:
        statement = "Confirm scanner date"

    promise = {"owner": "spk_1", "agreed": True, "span_ids": ["s4"], "claim_ids": [], "action_id": None}
    out = ground_digest(_raw(actions=[
        {**promise, "task": "Confirm by Monday", "quote": "will confirm by monday"},
        {**promise, "task": "Say yes", "quote": "by"},                                   # too short to prove anything
        {**promise, "task": "Sign the contract", "quote": None, "action_id": "a0"},      # shares no word with the ledger action
        {**promise, "task": "Confirm the scanner date", "quote": None, "action_id": "a0"},
    ]), SPANS, CLAIMS, [Ledger()], SPEAKERS)
    assert [row["task"] for row in out["actions"]] == ["Confirm by Monday", "Confirm the scanner date"]
    assert [row["basis"] for row in out["actions"]] == ["transcript", "likely"]
    assert out["actions"][1]["action_id"] == "a0" and out["actions"][0]["action_id"] is None


def test_a_figure_without_a_quantity_is_not_a_figure():
    spans = SPANS + [_span("s6", "We put a lot into it and about forty people came.", 22000, 26000, "spk_0")]
    raw = _raw(key_figures=[
        {"value": "a lot", "what": "effort", "span_id": "s6"},
        {"value": "about forty", "what": "attendees", "span_id": "s6"},
    ])
    assert [row["value"] for row in ground_digest(raw, spans, CLAIMS, [], SPEAKERS)["key_figures"]] == ["about forty"]


def test_perspectives_need_a_valid_citation_and_are_time_ordered():
    raw = _raw(perspectives=[
        {"speaker": "spk_0", "position": "Wait until January", "span_ids": ["s5"]},
        {"speaker": "spk_1", "position": "Start in November", "span_ids": ["s2", "gone"]},
        {"speaker": "spk_1", "position": "Invented", "span_ids": ["gone"]},
    ])
    rows = ground_digest(raw, SPANS, CLAIMS, [], SPEAKERS)["perspectives"]
    assert [(r["speaker"], r["start_ms"]) for r in rows] == [("spk_1", 5000), ("spk_0", 18000)]


def test_a_voice_label_is_not_a_number():
    from graph.numbers import grounded, scan

    assert scan("spk_0 will put a box around the pivot").quantities == ()
    assert grounded("spk_0 will put a box around the pivot", "and that's called the pivot i'll put a box around it")
    assert grounded("spk_12 asked for 3 pivots", "we need three pivots")
    assert not grounded("spk_1 asked for 4 pivots", "we need three pivots")


def test_lower_case_asr_names_are_shown_capitalised():
    spans = [_span("n1", "thank you dr casserly for being here", 0, 3000, "spk_0"), _span("n2", "happy to be here", 3000, 5000, "spk_1")]
    raw = _raw(speakers=[{"id": "spk_1", "name": "dr casserly", "role": "witness", "span_ids": ["n1"]}])
    assert ground_digest(raw, spans, [], [], {"spk_0", "spk_1"})["speakers"][0]["name"] == "Dr Casserly"


def test_a_concept_starts_at_its_earliest_cited_line():
    raw = _raw(concepts=[{"term": "Pivot", "explanation": "x", "span_ids": ["s1", "s2", "s4"], "claim_ids": ["c-ok"]}])
    concept = ground_digest(raw, SPANS, CLAIMS, [], SPEAKERS)["concepts"][0]
    assert concept["start_ms"] == 0  # earliest of 0, 5000, 13000


def test_a_spoken_promise_is_kept_when_its_quoted_words_are_in_the_cited_line():
    spans = [_span("p1", "okay I'll show you that next on my mobile device, so", 0, 4000, "spk_1")]
    raw = _raw(actions=[
        {"task": "Demonstrate scanning on a mobile device", "owner": "spk_1", "due": None, "agreed": False, "span_ids": ["p1"], "claim_ids": [], "action_id": None,
         "quote": "I'll show you that next, on my mobile device"},
        {"task": "Invented task", "owner": "spk_1", "due": None, "agreed": False, "span_ids": ["p1"], "claim_ids": [], "action_id": None,
         "quote": "we will sign the contract on Friday"},
    ])
    actions = ground_digest(raw, spans, [], [], {"spk_1"})["actions"]
    assert [(a["task"], a["basis"], a["agreed"]) for a in actions] == [("Demonstrate scanning on a mobile device", "transcript", False)]


def test_a_long_stretch_without_transcript_is_marked_as_a_gap_row():
    rows = transcript_lines(
        [_span("s1", "Before the break.", 1000, 5000), _span("s2", "After the break.", 125000, 130000)],
        lambda span: span.speaker_hypothesis_id or "unknown",
    )
    assert [row.get("id") or row["gap"] for row in rows] == ["s1", "no transcript between 0:05 and 2:05", "s2"]


def test_chapters_leave_no_unlabelled_stretch_between_them():
    raw = _raw(chapters=[
        {"title": "Volume", "gist": "g", "start_span_id": "s1", "end_span_id": "s1"},
        {"title": "Owner", "gist": "g", "start_span_id": "s4", "end_span_id": "s4"},
    ])
    chapters = ground_digest(raw, SPANS, CLAIMS, [], SPEAKERS)["chapters"]
    assert [(c["start_ms"], c["end_ms"]) for c in chapters] == [(0, 13000), (13000, 17000)]


def test_an_unanswered_question_keeps_the_partial_reply_that_was_cited():
    raw = _raw(open_questions=[
        {"question": "Who owns the scanner order?", "asked_by": "spk_0", "asked_span_id": "s3",
         "answered": False, "answer": "Priya owns it, no date given", "answer_span_id": "s4"},
        {"question": "Backwards", "asked_by": "spk_0", "asked_span_id": "s3",
         "answered": False, "answer": "said before it was asked", "answer_span_id": "s1"},
    ])
    first, second = ground_digest(raw, SPANS, CLAIMS, [], SPEAKERS)["open_questions"]
    assert (first["answered"], first["answer"], first["answer_ms"]) == (False, "Priya owns it, no date given", 13000)
    assert (second["answered"], second["answer"], second["answer_span_id"]) == (False, None, None)


def test_the_asker_carrying_on_is_not_a_reply():
    raw = _raw(open_questions=[
        {"question": "Who owns the scanner order?", "asked_by": "spk_0", "asked_span_id": "s3",
         "answered": False, "answer": "still the asker", "answer_span_id": "s5"},
    ])
    row = ground_digest(raw, SPANS, CLAIMS, [], SPEAKERS)["open_questions"][0]
    assert (row["answered"], row["answer"], row["answer_span_id"]) == (False, None, None)


def test_a_full_answer_is_kept_even_when_the_diarizer_gave_both_sides_one_voice():
    raw = _raw(open_questions=[
        {"question": "Who owns the scanner order?", "asked_by": "spk_0", "asked_span_id": "s3",
         "answered": True, "answer": "Yes", "answer_span_id": "s5"},
    ])
    row = ground_digest(raw, SPANS, CLAIMS, [], SPEAKERS)["open_questions"][0]
    assert (row["answered"], row["answer_span_id"]) == (True, "s5")


def test_the_last_chapter_stops_where_the_transcript_stops():
    raw = _raw(chapters=[{"title": "Everything", "gist": "g", "start_span_id": "s1", "end_span_id": "s5"}])
    chapter = ground_digest(raw, SPANS, CLAIMS, [], SPEAKERS)["chapters"][0]
    assert chapter["end_ms"] == 21000  # the last span ends at 21 s


def test_a_voice_is_named_only_on_items_whose_cited_lines_it_actually_spoke():
    raw = _raw(
        perspectives=[
            {"speaker": "spk_0", "position": "Credited to the wrong voice, but one voice spoke the line", "span_ids": ["s2"]},  # s2 is spk_1
            {"speaker": "spk_1", "position": "Correct", "span_ids": ["s2"]},
            {"speaker": "spk_1", "position": "Two voices cited, neither is the named one", "span_ids": ["s1", "s5", "s3"], },     # all spk_0
            {"speaker": "spk_1", "position": "Cites lines of both voices, so the model's pick stands", "span_ids": ["s1", "s2"]},
            {"speaker": "spk_1", "position": "Cites a voice-less set", "span_ids": ["s1", "s2", "s4"]},
        ],
        decisions=[
            {"statement": "Decided by someone who did not speak the cited line", "status": "agreed", "decided_by": "spk_0", "span_ids": ["s2"], "claim_ids": ["c-ok"]},
            {"statement": "Decided by the speaker", "status": "agreed", "decided_by": "spk_1", "span_ids": ["s2"], "claim_ids": ["c-ok"]},
        ],
        open_questions=[{"question": "Who owns the scanner order?", "asked_by": "spk_1", "asked_span_id": "s3", "answered": False}],
        disagreements=[{"topic": "Start date", "positions": [
            {"speaker": "spk_0", "position": "Wait", "span_ids": ["s5"]},
            {"speaker": "spk_0", "position": "Start now (wrongly the same voice)", "span_ids": ["s2"]},
        ]}],
    )
    out = ground_digest(raw, SPANS, CLAIMS, [], SPEAKERS)
    assert {p["position"][:12]: p["speaker"] for p in out["perspectives"]} == {
        "Credited to ": "spk_1",   # derived from the only voice that spoke the cited line
        "Correct": "spk_1",
        "Two voices c": "spk_0",    # one voice spoke all three cited lines
        "Cites lines ": "spk_1",    # both voices were cited, so the model's pick stands
        "Cites a voic": "spk_1",
    }
    assert [d["decided_by"] for d in out["decisions"]] == [None, "spk_1"]
    assert out["open_questions"][0]["asked_by"] == "spk_0"  # the asking line was spoken by spk_0, whatever the model said
    assert [p["speaker"] for p in out["disagreements"][0]["positions"]] == ["spk_0", "spk_1"]  # the second side is the voice that spoke it


def test_odd_types_cost_a_field_not_the_walkaway():
    raw = _raw(
        content_type=["meeting"],
        decisions=[{"statement": "Pilot in November", "status": {"x": 1}, "span_ids": ["s2"], "claim_ids": ["c-ok"]}],
        open_questions=[{"question": "Who owns the scanner order?", "asked_by": "spk_0", "asked_span_id": "s3",
                         "answered": "false", "answer": "the asker again", "answer_span_id": "s5"}],
    )
    digest = ground_digest(raw, SPANS, CLAIMS, [], SPEAKERS)
    assert digest is not None
    assert digest["content_type"] == "other"
    assert digest["decisions"][0]["status"] == "tentative"
    assert digest["open_questions"][0]["answered"] is False  # the text "false" is not a yes


def test_one_ledger_action_backs_one_digest_action():
    class Action:
        statement = "Confirm scanner date"
        due_surface = "by Monday"

    twin = {"owner": "spk_1", "due": "Monday", "agreed": True, "span_ids": ["s4"], "claim_ids": [], "action_id": "a0"}
    raw = _raw(actions=[{"task": "Confirm scanner date", **twin}, {"task": "Confirm the scanner date again", **twin}])
    actions = ground_digest(raw, SPANS, CLAIMS, [Action()], SPEAKERS)["actions"]
    assert [a["action_id"] for a in actions] == ["a0"]


def test_a_due_phrase_is_kept_only_when_it_names_a_time():
    base = {"owner": "spk_1", "agreed": True, "span_ids": ["s4"], "claim_ids": ["c-ok"], "action_id": None}
    raw = _raw(actions=[
        {"task": "Send the quote", "due": "Monday", **base},
        {"task": "Show the demo", "due": "next", **base},
        {"task": "Send the notes", "due": "in the next half hour or so", **base},
        {"task": "File the report", "due": "later", **base},
        {"task": "Ship the build", "due": "by the 3rd of November", **base},
    ])
    actions = ground_digest(raw, SPANS, CLAIMS, [], SPEAKERS)["actions"]
    assert [a["due"] for a in actions] == ["Monday", None, "in the next half hour or so", None, "by the 3rd of November"]


def test_an_action_owner_must_have_spoken_a_cited_line_or_be_the_one_promising():
    spans = SPANS + [
        _span("p1", "um we will be explicit about every requirement", 30000, 33000, "spk_1"),
        _span("p2", "Maddy can you send the notes", 34000, 36000, "spk_0"),
        _span("p3", "sure thing", 36500, 37500, "spk_2"),
    ]
    base = {"due": None, "agreed": True, "claim_ids": ["c-ok"], "action_id": None}
    raw = _raw(actions=[
        {"task": "Classify every requirement", "owner": "spk_2", "span_ids": ["p1"], **base},      # spk_2 never spoke it; spk_1 promised
        {"task": "Send the notes", "owner": "spk_2", "span_ids": ["p2", "p3"], **base},            # spk_2 spoke a cited line
        {"task": "Send the notes again", "owner": "spk_2", "span_ids": ["p2"], **base},            # only the requester spoke, no promise
    ])
    actions = ground_digest(raw, spans, CLAIMS, [], {"spk_0", "spk_1", "spk_2"})["actions"]
    assert [(a["task"], a["assignee"]) for a in actions] == [
        ("Classify every requirement", "spk_1"),
        ("Send the notes", "spk_2"),
        ("Send the notes again", None),
    ]


def test_a_refusal_is_not_a_first_person_promise_and_a_contraction_is():
    from graph.digest import _PROMISE

    for promise in ("I'll send it", "We’ll send it", "I can send it", "I'm gonna send it", "We're going to ship it", "We will not only fix it but test it"):
        assert _PROMISE.search(promise), promise
    for refusal in ("I can't make Friday", "We will not do that", "We’ll never"):
        assert not _PROMISE.search(refusal), refusal


def test_a_due_phrase_needs_a_time_word_but_not_only_a_weekday_or_number():
    from graph.digest import _due

    for said in ("next sprint", "by noon", "ASAP", "in a fortnight", "by midnight", "overnight", "immediately", "Friday", "Q3", "end of the quarter",
                 "in two weeks", "two months", "several quarters", "by Fri", "３日", "٣ أيام"):
        assert _due(said) == said, said
    for not_a_time in ("Lee", "once approved", "after the demo", "before the board meets", "", None, 5):
        assert _due(not_a_time) is None, not_a_time


def test_a_model_that_sends_positions_as_a_number_or_text_cannot_lose_the_digest():
    for damaged in (True, 3, 2.5, "wait", {"speaker": "spk_0"}, [None, "x", 4]):
        raw = {"title": "T", "summary": [{"text": "We pick about one thousand orders every day.", "span_ids": ["s1"]}],
               "disagreements": [{"topic": "t", "positions": damaged}]}
        out = ground_digest(raw, SPANS, CLAIMS, [], SPEAKERS)
        assert out is not None and out["disagreements"] == [] and out["summary"], damaged


def test_a_magnitude_word_is_part_of_the_number_it_follows():
    from graph.numbers import grounded

    for claim, span in (
        ("$5 million", "We need $5 million"), ("1,500,000", "1.5 million users"), ("$50k", "fifty thousand dollars"),
        ("50k in fake money", "they get like fifty k"), ("5 million", "five million"), ("2 hundred", "two hundred"),
        ("10-20 days", "10 to 20 days"),
    ):
        assert grounded(claim, span), (claim, span)
    for claim, span in (
        ("$5 million", "We need $5 billion"), ("1.5 billion", "1.5 million users"), ("$50k", "it costs $50"),
        ("a million dollars", "no figures here"), ("$5 million", "five billion dollars"),
    ):
        assert not grounded(claim, span), (claim, span)


def test_a_key_figure_with_no_number_in_it_cannot_ground_against_any_line():
    raw = {"title": "T", "summary": [{"text": "We pick about one thousand orders every day.", "span_ids": ["s1"]}],
           "key_figures": [{"value": "half", "what": "of the orders", "span_id": "s1"}, {"value": "negative", "what": "growth", "span_id": "s1"},
                           {"value": "1000", "what": "orders a day", "span_id": "s1"}]}
    figures = ground_digest(raw, SPANS, CLAIMS, [], SPEAKERS)["key_figures"]
    assert [figure["value"] for figure in figures] == ["1000"]


def test_repeated_items_collapse_and_two_topics_cannot_start_on_one_line_or_have_no_length():
    raw = _raw(
        summary=[{"text": "We pick about one thousand orders every day.", "span_ids": ["s1"]}, {"text": "We pick about ONE thousand orders every day!", "span_ids": ["s1"]}],
        chapters=[
            {"title": "A", "gist": "g", "start_span_id": "s1", "end_span_id": "s1"},
            {"title": "A again", "gist": "g", "start_span_id": "s1", "end_span_id": "s3"},
            {"title": "B", "gist": "g", "start_span_id": "s4", "end_span_id": "s1"},  # names an end line before its own start
        ],
    )
    out = ground_digest(raw, SPANS, CLAIMS, [], SPEAKERS)
    assert len(out["summary"]) == 1
    assert [(c["title"], c["start_ms"], c["end_ms"]) for c in out["chapters"]] == [("A", 0, 13000), ("B", 13000, 17000)]


def test_two_actions_that_share_only_function_words_are_not_linked():
    raw = _raw(actions=[{"task": "Delete that database", "owner": "spk_0", "agreed": True, "span_ids": ["s1"], "action_id": "a0"}])
    unrelated = ground_digest(raw, SPANS, [], [type("A", (), {"statement": "Ship that build"})()], SPEAKERS)
    assert unrelated["actions"] == []
    raw["actions"][0]["task"] = "Ship the build to the pilot site"
    related = ground_digest(raw, SPANS, [], [type("A", (), {"statement": "Ship that build"})()], SPEAKERS)
    assert [(a["task"], a["basis"]) for a in related["actions"]] == [("Ship the build to the pilot site", "likely")]


def test_outside_an_ordinary_meeting_an_action_whose_owner_did_not_speak_the_line_is_dropped():
    raw = _raw(content_type="interview", actions=[
        {"task": "Send the notes", "owner": "spk_1", "agreed": True, "span_ids": ["s1"], "claim_ids": ["c-ok"]},   # spk_1 never spoke s1
        {"task": "Send the report", "owner": "spk_1", "agreed": True, "span_ids": ["s2"], "claim_ids": ["c-ok"]},  # spk_1 spoke s2
    ])
    actions = ground_digest(raw, SPANS, CLAIMS, [], SPEAKERS)["actions"]
    assert [(a["task"], a["assignee"]) for a in actions] == [("Send the report", "spk_1")]


def test_a_weekday_in_a_due_phrase_must_have_been_said_near_the_lines_it_came_from():
    raw = _raw(actions=[
        {"task": "Confirm the order", "owner": "spk_1", "agreed": True, "span_ids": ["s4"], "claim_ids": ["c-likely"], "due": "Friday 5pm"},  # s4 says Monday
        {"task": "Confirm the order now", "owner": "spk_1", "agreed": True, "span_ids": ["s4"], "claim_ids": ["c-likely"], "due": "by Monday"},
        {"task": "Confirm the order soon", "owner": "spk_1", "agreed": True, "span_ids": ["s4"], "claim_ids": ["c-likely"], "due": "in two weeks"},
    ])
    actions = ground_digest(raw, SPANS, CLAIMS, [], SPEAKERS)["actions"]
    assert [(a["task"], a["due"]) for a in actions] == [("Confirm the order", None), ("Confirm the order now", "by Monday"), ("Confirm the order soon", "in two weeks")]


def test_only_a_flowchart_or_sequence_diagram_survives_whatever_else_the_model_draws():
    def kept(source):
        raw = {"title": "T", "summary": [{"text": "We pick orders.", "span_ids": ["s1"]}],
               "diagram": {"kind": "flowchart", "title": "d", "mermaid": source, "span_ids": ["s1"]}}
        return ground_digest(raw, SPANS, CLAIMS, [], SPEAKERS)["diagram"] is not None

    for fine in ("flowchart TD\n  A --> B", "graph LR\n  A --> B", "sequenceDiagram\n  A->>B: hi"):
        assert kept(fine), fine
    for refused in ("xychart-beta\n  x-axis [a,b]\n  bar [1,2]", "gantt\n  dateFormat X", "radar-beta\n  axis a", "architecture-beta\n  group g(cloud)[G]",
                    "stateDiagram-v2\n  [*] --> A", "classDiagram\n  A <|-- B", "pie\n  \"a\": 1", "mindmap\n  root"):
        assert not kept(refused), refused
