from types import SimpleNamespace

from loop.quality import _reviewed


def _digest(n):
    return {"summary": [{"text": "s"}] * 2, "chapters": [{"title": "c"}] * n, "risks": [], "decisions": [], "actions": [],
            "open_questions": [], "disagreements": [], "perspectives": [], "key_figures": [], "concepts": [], "speakers": []}


def _call(output=None, raises=False, answer=True):
    def call(route, payload):
        assert "draft" in payload
        if raises:
            raise RuntimeError("boom")
        return SimpleNamespace(output=output) if answer else None
    return call


def test_a_sound_review_replaces_the_draft():
    draft, better = _digest(4), _digest(6)
    out = _reviewed(_call({"x": 1}), {}, {"d": 1}, draft, lambda raw: better)
    assert out is better


def test_a_much_thinner_review_keeps_the_draft():
    draft = _digest(10)
    assert _reviewed(_call({"x": 1}), {}, {"d": 1}, draft, lambda raw: _digest(1)) is draft


def test_a_review_without_a_summary_keeps_the_draft():
    draft = _digest(4)
    bare = {**_digest(8), "summary": []}
    assert _reviewed(_call({"x": 1}), {}, {"d": 1}, draft, lambda raw: bare) is draft


def test_no_answer_garbage_or_an_error_keeps_the_draft():
    draft = _digest(4)
    assert _reviewed(_call(answer=False), {}, {"d": 1}, draft, lambda raw: None) is draft
    assert _reviewed(_call({"x": 1}), {}, {"d": 1}, draft, lambda raw: None) is draft
    assert _reviewed(_call(raises=True), {}, {"d": 1}, draft, lambda raw: None) is draft
    assert _reviewed(_call({"x": 1}), {}, {"d": 1}, None, lambda raw: _digest(9)) is None


def test_a_question_the_check_does_not_confirm_is_demoted_but_keeps_its_cited_reply():
    from loop.quality import _verify_questions
    from graph.span import Span

    def span(span_id, start, speaker):
        return Span(id=span_id, meeting_id="m", kind="speech", start_ms=start, end_ms=start + 1000, raw_text="t", text="t", speaker_hypothesis_id=speaker)

    ledger = SimpleNamespace(spans=[span("q", 0, "spk_0"), span("a", 3000, "spk_1")])
    digest = {"open_questions": [
        {"question": "Will it ship?", "asked_span_id": "q", "answered": True, "answer": "Parents must be involved", "answer_span_id": "a", "answer_ms": 3000},
    ]}

    def call(route, payload):
        return SimpleNamespace(output={"answered": False, "answer_span_id": "a", "answer": "a partial remark"})

    out = _verify_questions(ledger, call, digest)["open_questions"][0]
    assert out["answered"] is False
    assert out["answer"] == "Parents must be involved" and out["answer_span_id"] == "a"

    def confirming(route, payload):
        return SimpleNamespace(output={"answered": True, "answer_span_id": "a", "answer": "yes"})

    digest["open_questions"][0]["answered"] = True
    assert _verify_questions(ledger, confirming, digest)["open_questions"][0]["answered"] is True


def test_a_check_that_fails_or_cites_a_line_it_was_not_shown_leaves_the_writers_answer_alone():
    from loop.quality import ANSWER_WINDOW_MS, _verify_questions
    from graph.span import Span

    def span(span_id, start, speaker):
        return Span(id=span_id, meeting_id="m", kind="speech", start_ms=start, end_ms=start + 1000, raw_text="t", text="t", speaker_hypothesis_id=speaker)

    far = ANSWER_WINDOW_MS + 60_000
    ledger = SimpleNamespace(spans=[span("q", 0, "spk_0"), span("a", 3000, "spk_1"), span("far", far, "spk_1")])

    def digest():
        return {"open_questions": [
            {"question": "Will it ship?", "asked_span_id": "q", "answered": True, "answer": "Friday", "answer_span_id": "a", "answer_ms": 3000},
            {"question": "Open?", "asked_span_id": "q", "answered": False, "answer": None, "answer_span_id": None},
        ]}

    failing = lambda route, payload: None  # noqa: E731
    first, second = _verify_questions(ledger, failing, digest())["open_questions"]
    assert first["answered"] is True and first["answer"] == "Friday" and second["answered"] is False

    outside = lambda route, payload: SimpleNamespace(output={"answered": True, "answer_span_id": "far", "answer": "much later"})  # noqa: E731
    first, second = _verify_questions(ledger, outside, digest())["open_questions"]
    assert first["answered"] is True and first["answer_span_id"] == "a"  # kept as written
    assert second["answered"] is False and second["answer_span_id"] is None  # a line outside the window is not accepted


def _tool_turn(name, arguments):
    from bedrock.turn import ToolCall

    return SimpleNamespace(output={}, tool_calls=[ToolCall(name=name, arguments=arguments)])


def test_the_tool_loop_runs_handlers_and_asks_again_with_every_result():
    from loop.tools import complete_with_tools

    seen = []

    def complete(payload):
        seen.append(payload)
        if len(seen) == 1:
            return _tool_turn("read_context", {"doc_id": "c1", "query": "spooler"})
        return SimpleNamespace(output={"ok": True}, tool_calls=[])

    turn = complete_with_tools(complete, {"read_context": lambda arguments: {"excerpt": "single thread", "q": arguments["query"]}}, {"transcript": []})
    assert turn.output == {"ok": True}
    assert seen[1]["_fill"] is True and seen[1]["transcript"] == []
    assert seen[1]["tool_results"] == [{"tool": "read_context", "arguments": {"doc_id": "c1", "query": "spooler"}, "result": {"excerpt": "single thread", "q": "spooler"}}]


def test_an_unknown_tool_or_a_broken_handler_still_gets_an_answer_not_an_empty_turn():
    from loop.tools import complete_with_tools

    calls = []

    def complete(payload):
        calls.append(payload)
        return _tool_turn("nope", {}) if len(calls) == 1 else SimpleNamespace(output={"done": 1}, tool_calls=[])

    assert complete_with_tools(complete, {}, {}).output == {"done": 1}
    assert calls[1]["tool_results"][0]["result"] == {"error": "no result"}

    def boom(arguments):
        raise RuntimeError("x")

    calls.clear()
    assert complete_with_tools(complete, {"nope": boom}, {}).output == {"done": 1}


def test_a_model_that_never_stops_calling_tools_is_cut_off_after_three_rounds():
    from loop.tools import complete_with_tools

    count = []

    def complete(payload):
        count.append(1)
        return _tool_turn("read_context", {"doc_id": "c1"})

    turn = complete_with_tools(complete, {"read_context": lambda a: {"excerpt": "x"}}, {})
    assert len(count) == 4 and turn.tool_calls  # one first call plus three rounds; the caller treats a still-calling turn as no answer


def test_the_digest_stage_sends_context_only_when_there_is_some_and_lets_the_model_read_it():
    from context.library import ContextDoc, ContextLibrary
    from graph.span import Span
    from loop.quality import _digest

    spans = [Span(id="s1", meeting_id="m", kind="speech", start_ms=0, end_ms=4000, raw_text="We pick about a thousand orders a day.", text="We pick about a thousand orders a day.", speaker_hypothesis_id="spk_0")]
    minimal = {"content_type": "meeting", "title": "T", "summary": [{"text": "Orders are picked daily.", "span_ids": ["s1"], "claim_ids": []}]}

    def run(library):
        payloads = []

        def call(route, payload):
            payloads.append((route, payload))
            if route.endswith("digest.v1") and len(payloads) == 1 and library is not None:
                return _tool_turn("read_context", {"doc_id": "c1", "query": "orders"})
            return SimpleNamespace(output=minimal, tool_calls=[])

        ledger = SimpleNamespace(spans=spans, context=library)
        return _digest(ledger, call, [], []), payloads

    library = ContextLibrary([ContextDoc("c1", "Design.md", "# Orders\n\nThe order service takes orders from the shop.", headings=["Orders"])], "Review the order service")
    digest, payloads = run(library)
    assert digest and digest["summary"][0]["text"] == "Orders are picked daily."
    first = payloads[0][1]
    assert first["context"]["purpose"] == "Review the order service" and first["context"]["documents"][0]["id"] == "c1"
    assert "order service takes orders" not in str(first)  # the index travels; the document stays here
    second = payloads[1][1]
    assert second["_fill"] is True and "order service takes orders" in str(second["tool_results"])
    assert all("context" in payload for route, payload in payloads if route.endswith(("digest.v1", "digest_review.v1")))

    digest, payloads = run(None)
    assert digest and "context" not in payloads[0][1]


def test_too_many_tool_calls_and_long_arguments_are_cut_down():
    from bedrock.turn import ToolCall
    from loop.tools import MAX_ARGUMENT_CHARS, MAX_CALLS_PER_ROUND, complete_with_tools

    seen = []
    first = SimpleNamespace(output={}, tool_calls=[ToolCall(name="read_context", arguments={"doc_id": "c1", "query": "x" * 5000}) for _ in range(10)])

    def complete(payload):
        seen.append(payload)
        return first if len(seen) == 1 else SimpleNamespace(output={"ok": 1}, tool_calls=[])

    ran = []
    complete_with_tools(complete, {"read_context": lambda arguments: ran.append(arguments) or {"excerpt": "y"}}, {})
    assert len(ran) == MAX_CALLS_PER_ROUND and all(len(a["query"]) == MAX_ARGUMENT_CHARS for a in ran)
    assert len(seen[1]["tool_results"]) == MAX_CALLS_PER_ROUND


def test_an_oversized_prompt_is_retried_without_context_instead_of_losing_the_walkaway():
    from context.library import ContextDoc, ContextLibrary
    from errors import InputTooLarge
    from graph.span import Span
    from loop.quality import _digest

    spans = [Span(id="s1", meeting_id="m", kind="speech", start_ms=0, end_ms=4000, raw_text="We pick orders.", text="We pick orders.", speaker_hypothesis_id="spk_0")]
    seen = []

    def call(route, payload):
        seen.append(("context" in payload, route))
        if "context" in payload and route.endswith("digest.v1"):
            raise InputTooLarge("too big")
        return SimpleNamespace(output={"content_type": "meeting", "title": "T", "summary": [{"text": "Orders are picked.", "span_ids": ["s1"], "claim_ids": []}]}, tool_calls=[])

    library = ContextLibrary([ContextDoc("c1", "Doc", "# H\n\ntext here is long enough to be a gist", headings=["H"])], "p")
    digest = _digest(SimpleNamespace(spans=spans, context=library), call, [], [])
    assert digest and digest["summary"][0]["text"] == "Orders are picked."
    assert seen[0] == (True, "meeting.digest.v1") and (False, "meeting.digest.v1") in seen


def test_the_review_replaces_the_draft_at_seven_tenths_of_its_size_and_not_below():
    draft = _digest(10)  # 2 summary lines + 10 chapters = 12 items; 70% is 8.4
    assert _reviewed(_call({"x": 1}), {}, {"d": 1}, draft, lambda raw: _digest(7)) is not draft   # 9 items
    assert _reviewed(_call({"x": 1}), {}, {"d": 1}, draft, lambda raw: _digest(6)) is draft       # 8 items


def test_a_reply_exactly_at_the_end_of_the_window_counts_and_one_millisecond_later_does_not():
    from loop.quality import ANSWER_WINDOW_MS, _verify_questions
    from graph.span import Span

    def span(span_id, start, speaker):
        return Span(id=span_id, meeting_id="m", kind="speech", start_ms=start, end_ms=start + 100, raw_text="t", text="t", speaker_hypothesis_id=speaker)

    ledger = SimpleNamespace(spans=[span("q", 0, "spk_0"), span("edge", ANSWER_WINDOW_MS, "spk_1"), span("late", ANSWER_WINDOW_MS + 1, "spk_1")])

    def check(target):
        digest = {"open_questions": [{"question": "Q?", "asked_span_id": "q", "answered": False}]}
        call = lambda route, payload: SimpleNamespace(output={"answered": True, "answer_span_id": target, "answer": "yes"}, tool_calls=[])  # noqa: E731
        return _verify_questions(ledger, call, digest)["open_questions"][0]["answered"]

    assert check("edge") is True
    assert check("late") is False
