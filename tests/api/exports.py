"""Publish gate, captions, and export resources."""

import json

from starlette.testclient import TestClient

from quotient.app import create_app
from quotient.export.captions import webvtt
from quotient.export.project import render_local
from quotient.graph.gate import project_meeting, summary
from quotient.worker.memory import MemoryPort

from conftest import open_session, published_graph, rpc


def _resource(client, headers, uri: str) -> dict:
    body = rpc(client, headers, "resources/read", {"uri": uri})
    return json.loads(body["result"]["contents"][0]["text"])


def test_brief_withholds_unresolved_claims_and_captions_use_source_time():
    text = "Ship the report by Friday."
    cues = webvtt(
        [
            {
                "span_id": "s1",
                "kind": "speech",
                "start_ms": 1000,
                "end_ms": 1000,
                "text": text,
            }
        ]
    )
    assert cues.startswith("WEBVTT\n")
    assert "00:00:01.000 --> 00:00:01.001" in cues
    assert text in cues

    mismatched = published_graph("m1")
    mismatched["claims"].append(
        {
            "claim_id": "c2",
            "kind": "figure",
            "status": "supported",
            "text": "The budget increased 15%.",
            "origin": "model",
            "citations": [
                {
                    "quote": "15%",
                    "span_id": "s1",
                    "relation": "mentions",
                    "char_start": 0,
                    "char_end": 3,
                    "start_ms": 1000,
                    "end_ms": 4000,
                }
            ],
        }
    )
    projected = project_meeting({"meeting_id": "m1", "status": "ready", "prompt_release": "bad\nprompt", **mismatched})
    assert projected["status"] == "needs_review"
    assert projected["brief"]["withheld"] is True
    assert projected["prompt_release"] is None
    assert projected["brief"]["findings"] == []
    assert "15%" not in json.dumps(projected["brief"])
    assert projected["review"]["counts"]["unresolved"] == 1

    port = MemoryPort()
    app = create_app(auth_bypass=True, port=port, environ={})
    with TestClient(app) as client:
        headers = open_session(client)
        created = rpc(
            client,
            headers,
            "tools/call",
            {
                "name": "submit_meeting",
                "arguments": {"object_key": "media/slice.mp4"},
                "task": {},
            },
        )
        task_id = created["result"]["task"]["taskId"]
        viewed = rpc(client, headers, "tasks/get", {"taskId": task_id})
        meeting_id = viewed["result"]["statusMessage"].split(" ", 2)[1]
        graph = published_graph(meeting_id)
        graph["claims"].append(
            {
                "claim_id": "c-open",
                "kind": "figure",
                "status": "unresolved",
                "text": "The budget increased 15%.",
                "origin": "model",
                "citations": [],
            }
        )
        port.settle(meeting_id, status="ready", graph=graph, prompt_release="registry-1")
        brief = _resource(client, headers, f"quotient://meetings/{meeting_id}/brief")
        review = _resource(client, headers, f"quotient://meetings/{meeting_id}/review")
        assert brief["withheld"] is True
        assert "15%" not in json.dumps(brief)
        assert review["claims"][0]["text"] == "The budget increased 15%."
        captions = rpc(
            client,
            headers,
            "resources/read",
            {"uri": f"quotient://meetings/{meeting_id}/exports/captions.vtt"},
        )
        assert "WEBVTT" in captions["result"]["contents"][0]["text"]
        burned = rpc(
            client,
            headers,
            "resources/read",
            {"uri": f"quotient://meetings/{meeting_id}/exports/burned.mp4"},
        )
        assert burned["error"]["code"] == -32002
        pdf = rpc(
            client,
            headers,
            "resources/read",
            {"uri": f"quotient://meetings/{meeting_id}/exports/brief.pdf"},
        )
        import base64

        blob = base64.b64decode(pdf["result"]["contents"][0]["blob"])
        assert blob.startswith(b"%PDF")
        assert b"15%" not in blob


def test_brief_exports_render_markdown_and_mermaid():
    prose = "The service split is <script>alert(1)</script>."
    flow = f"""{prose}

```mermaid
flowchart TD
  A[API] --> B[Store]
```
"""
    other = """```mermaid
classDiagram
  ClassA <|-- ClassB
```
"""
    brief = {
        "playback": "meetings/m1",
        "withheld": False,
        "dimensions": [],
        "synthesis": [
            {"text": flow, "playback": "meetings/m1?t=1"},
            {"text": other, "playback": "meetings/m1?t=2"},
        ],
        "actions": [],
        "omissions": [],
    }
    projected = {"brief": brief, "graph": {"actions": [], "spans": []}}
    mime, html_bytes = render_local("brief.html", projected)
    page = html_bytes.decode()
    assert mime.startswith("text/html")
    assert "<svg" in page
    assert "API" in page
    assert "Store" in page
    assert 'class="mermaid"' in page
    assert "classDiagram" in page
    assert "mermaid.esm.min.mjs" in page
    assert "<script>alert" not in page
    assert "&lt;script&gt;" in page
    _pdf_mime, pdf = render_local("brief.pdf", projected)
    assert pdf.startswith(b"%PDF")
    assert b"API" in pdf
    assert b"Store" in pdf
    assert b"classDiagram" in pdf
    assert b"none_in_transcript" not in pdf
    assert b"meetings/m1?t=" not in pdf
    assert b"At 0:00" in pdf
    assert b"Brief" in pdf


def test_media_resource_uses_owner_scoped_short_lived_url():
    class MediaPort(MemoryPort):
        def media_url(self, meeting_id: str, subject: str) -> str | None:
            if self.meeting(meeting_id, subject) is None:
                return None
            return "http://127.0.0.1:9000/axion-meeting-local/source.mp4?signature=test"

    port = MediaPort()
    app = create_app(auth_bypass=True, port=port, environ={})
    with TestClient(app) as client:
        headers = open_session(client)
        created = rpc(client, headers, "tools/call", {
            "name": "submit_meeting",
            "arguments": {"object_key": "derivatives/source.mp4"},
            "task": {},
        })
        task_id = created["result"]["task"]["taskId"]
        status = rpc(client, headers, "tasks/get", {"taskId": task_id})
        meeting_id = status["result"]["statusMessage"].split(" ", 2)[1]
        graph = _resource(client, headers, f"quotient://meetings/{meeting_id}/graph")
        assert graph["playback"] == f"quotient://meetings/{meeting_id}/media"
        media = rpc(client, headers, "resources/read", {"uri": graph["playback"]})
        content = media["result"]["contents"][0]
        assert content["mimeType"] == "video/mp4"
        assert content["text"].startswith("http://127.0.0.1:9000/")


def test_review_projection_preserves_worker_priority_order():
    source = published_graph("m-order")
    source["claims"] = [
        {
            "claim_id": claim_id,
            "kind": "observation",
            "status": "unresolved",
            "text": claim_id,
            "origin": "model",
            "citations": [],
        }
        for claim_id in ("c-first-extracted", "c-high-priority")
    ]
    source["review_queue"] = ["c-high-priority", "c-first-extracted"]
    projected = project_meeting({"meeting_id": "m-order", "status": "needs_review", **source})
    assert [claim["claim_id"] for claim in projected["review"]["claims"]] == [
        "c-high-priority",
        "c-first-extracted",
    ]


def test_meeting_summary_keeps_the_last_analysis_phase_after_restart():
    projected = project_meeting(
        {
            "meeting_id": "m-progress",
            "status": "needs_review",
            "progress_message": "Analysis complete; this meeting needs review.",
        }
    )
    assert summary(projected)["progress_message"] == "Analysis complete; this meeting needs review."


def test_transcript_gaps_are_exposed_and_downgrade_ready_status():
    source = published_graph("m-gap")
    source["gaps"] = [{"span_ids": ["s1", "foreign"], "reason": "Extraction needs a human check."}]
    projected = project_meeting({"meeting_id": "m-gap", "status": "ready", **source})
    assert projected["status"] == "needs_review"
    assert projected["brief"]["withheld"] is True
    assert projected["graph"]["gaps"] == [{"gap_id": "gap-1", "span_ids": ["s1"], "reason": "Extraction needs a human check."}]


def test_dimension_states_separate_absent_held_and_not_evaluated():
    graph = published_graph("m1")
    graph["findings"].append(
        {
            "finding_id": "f-risk",
            "dimension": "risk",
            "stance": "supports",
            "text": "Weather may delay the pilot.",
            "claim_ids": ["c-held"],
        }
    )
    graph["claims"].append(
        {"claim_id": "c-held", "kind": "decision", "status": "unresolved", "text": "Weather may delay it.", "origin": "model", "citations": []}
    )
    projected = project_meeting(
        {"meeting_id": "m1", "status": "ready", "prompt_release": "r", "not_evaluated": ["commitment"], **graph}
    )
    states = {row["dimension"]: row for row in projected["graph"]["dimensions"]}
    assert states["decision"]["state"] == "findings"
    assert states["commitment"]["state"] == "not_evaluated"
    assert states["risk"]["state"] == "none_in_transcript"
    assert states["risk"]["held_findings"] == 1
    assert states["question"]["state"] == "none_in_transcript"
    assert states["question"]["held_findings"] == 0
    assert projected["status"] == "needs_review"


def test_a_not_evaluated_lens_alone_prevents_ready():
    graph = published_graph("m1")
    clean = project_meeting({"meeting_id": "m1", "status": "ready", "prompt_release": "r", **graph})
    blocked = project_meeting(
        {"meeting_id": "m1", "status": "ready", "prompt_release": "r", "not_evaluated": ["risk"], **graph}
    )
    assert clean["status"] == "ready"
    assert blocked["status"] == "needs_review"


def test_actions_csv_neutralises_spreadsheet_formulas():
    from quotient.export.project import _csv

    rows = [{"action_id": "a1", "statement": '=HYPERLINK("http://evil","x")', "owner_display": "@alex", "acceptance": "proposed", "due_kind": "none", "due_surface": None}]
    text = _csv(rows)
    body = text.splitlines()[1]
    assert "'=HYPERLINK" in body and "'@alex" in body
    assert not any(line.startswith(("=", "+", "-", "@")) for line in text.splitlines()[1:])


def test_failed_meetings_report_a_sanitised_reason_and_old_leaky_rows_are_masked():
    leaky = {"meeting_id": "m1", "status": "failed", "failure_message": "CalledProcessError: Command ['ffprobe', '/Users/x/a.mp4']"}
    projected = project_meeting(leaky)
    assert "failure_message" in summary(projected)
    assert "/Users" not in summary(projected)["failure_message"]
    assert "ffprobe" not in summary(projected)["failure_message"]
    plain = project_meeting({"meeting_id": "m2", "status": "failed", "failure_message": "The recording could not be found."})
    assert summary(plain)["failure_message"] == "The recording could not be found."
    ok = project_meeting({"meeting_id": "m3", "status": "queued"})
    assert "failure_message" not in summary(ok)


def test_downloads_of_a_meeting_needing_review_carry_the_confirmed_brief_under_a_partial_notice():
    graph = published_graph("m1")
    graph["claims"].append(
        {"claim_id": "c-held", "kind": "decision", "status": "unresolved", "text": "Maybe move to Monday.", "origin": "model", "citations": []}
    )
    projected = project_meeting({"meeting_id": "m1", "status": "ready", "prompt_release": "r", **graph})
    assert projected["status"] == "needs_review" and projected["brief"]["withheld"] is True  # the MCP contract is unchanged

    _, html_body = render_local("brief.html", projected)
    page = html_body.decode()
    assert "Partial brief" in page and "1 other statements" in page
    assert "The group decided to ship the report by Friday." in page
    assert "Maybe move to Monday." not in page  # nothing unconfirmed is added

    _, pdf_body = render_local("brief.pdf", projected)
    assert b"Partial brief" in pdf_body and len(pdf_body) > 1200

    ready = project_meeting({"meeting_id": "m2", "status": "ready", "prompt_release": "r", **published_graph("m2")})
    assert "Partial brief" not in render_local("brief.html", ready)[1].decode()

    nothing = project_meeting({"meeting_id": "m3", "status": "needs_review", "prompt_release": "r"})
    assert "The brief is withheld" in render_local("brief.html", nothing)[1].decode()


def test_overlapping_caption_cues_never_share_screen_time():
    spans = [
        {"span_id": "a", "kind": "speech", "start_ms": 0, "end_ms": 5738, "text": "first line"},
        {"span_id": "b", "kind": "speech", "start_ms": 3000, "end_ms": 6438, "text": "second line"},
        {"span_id": "c", "kind": "speech", "start_ms": 3000, "end_ms": 4000, "text": "simultaneous"},
        {"span_id": "d", "kind": "speech", "start_ms": 9000, "end_ms": 10000, "text": "later"},
    ]
    cues = webvtt(spans)
    assert "00:00:00.000 --> 00:00:03.000" in cues  # cut where the next cue starts
    assert "00:00:03.000 --> 00:00:06.438" in cues  # cues that start together keep their own end
    assert "00:00:09.000 --> 00:00:10.000" in cues  # no overlap, untouched


def test_summary_offers_a_readable_source_name_but_never_a_path_or_generated_copy_name():
    named = project_meeting({"meeting_id": "m1", "status": "queued", "object_key": "derivatives/Quarterly_review-2026.mp4"})
    assert summary(named)["source_name"] == "Quarterly review 2026"
    copy = project_meeting({"meeting_id": "m2", "status": "queued", "object_key": "derivatives/AbCdEf-0.mp4"})
    assert "source_name" not in summary(copy)
    assert "source_name" not in summary(project_meeting({"meeting_id": "m3", "status": "queued"}))


def test_digest_items_are_rechecked_against_this_meetings_spans_and_captions_are_offered():
    graph = published_graph("m1")
    graph["digest"] = {
        "content_type": "meeting",
        "title": "Report",
        "summary": [
            {"text": "The report ships Friday.", "span_ids": ["s1"], "basis": "confirmed", "start_ms": 1000},
            {"text": "Ghost sentence.", "span_ids": ["gone"], "basis": "transcript", "start_ms": 0},
        ],
        "key_figures": [{"value": "Friday", "what": "due", "span_id": "gone", "start_ms": 0}],
        "diagram": {"kind": "flowchart", "title": "x", "mermaid": "flowchart LR\\n A-->B", "span_ids": ["gone"]},
    }
    projected = project_meeting({"meeting_id": "m1", "status": "ready", "prompt_release": "r", **graph})
    digest = projected["graph"]["digest"]
    assert [row["text"] for row in digest["summary"]] == ["The report ships Friday."]
    assert digest["key_figures"] == [] and digest["diagram"] is None
    assert digest["decisions"] == [] and digest["chapters"] == []
    assert projected["graph"]["captions"] == "quotient://meetings/m1/exports/captions.vtt"
    assert projected["graph"]["playback"] == "meetings/m1"


def test_meeting_without_digest_projects_none():
    projected = project_meeting({"meeting_id": "m1", "status": "ready", "prompt_release": "r", **published_graph("m1")})
    assert projected["graph"]["digest"] is None


def test_long_spans_become_several_two_line_cues_and_fall_back_to_raw_text():
    long_text = " ".join(["word"] * 60)  # 299 characters
    cues = webvtt(
        [
            {"span_id": "s1", "kind": "speech", "start_ms": 0, "end_ms": 30_000, "text": long_text},
            {"span_id": "s2", "kind": "speech", "start_ms": 31_000, "end_ms": 32_000, "text": "", "raw_text": "raw words <here>"},
        ]
    )
    blocks = [block.strip() for block in cues.split("\n\n") if "-->" in block]
    texts = [block.split("\n", 2)[2] for block in blocks]
    assert len(blocks) >= 4
    assert all(len(line) <= 42 for text in texts for line in text.split("\n"))
    assert all(len(text.split("\n")) <= 2 for text in texts)
    assert blocks[0].split("\n")[1].startswith("00:00:00.000 -->")
    assert "00:00:30.000" in blocks[-2].split("\n")[1]
    assert texts[-1] == "raw words &lt;here&gt;"


def test_brief_exports_carry_the_walkaway_when_a_meeting_has_one():
    graph = published_graph("m1")
    graph["digest"] = {
        "content_type": "meeting",
        "title": "Report shipping review",
        "summary": [{"text": "The team agreed to ship the report on Friday.", "span_ids": ["s1"], "basis": "confirmed", "start_ms": 1000}],
        "decisions": [{"statement": "Ship the report on Friday", "status": "agreed", "decided_by": "spk_1", "span_ids": ["s1"], "basis": "likely", "start_ms": 1000}],
        "actions": [{"task": "Send the report <draft>", "assignee": "h1", "due": "Friday", "agreed": True, "span_ids": ["s1"], "basis": "confirmed", "start_ms": 1000}],
    }
    projected = project_meeting({"meeting_id": "m1", "status": "ready", "prompt_release": "r", **graph})
    _, page = render_local("brief.html", projected)
    text = page.decode("utf-8")
    assert "<h1>Report shipping review</h1>" in text
    assert "Agreed: Ship the report on Friday (decided by Speaker 2) [likely] (0:01)" in text
    assert "Send the report &lt;draft&gt; (owner h1) (due Friday)" in text
    assert "<script" not in text.split("</h1>", 1)[1]
    mime, pdf = render_local("brief.pdf", projected)
    assert mime == "application/pdf" and pdf.startswith(b"%PDF")


def test_digest_passes_speakers_perspectives_and_outcome_only_when_cited():
    graph = published_graph("m1")
    graph["digest"] = {
        "content_type": "discussion",
        "title": "Hearing",
        "summary": [],
        "speakers": [
            {"id": "spk_0", "name": "Dr. Casserly", "role": "witness", "span_ids": ["s1"]},
            {"id": "spk_1", "name": "Ghost", "role": None, "span_ids": ["gone"]},
        ],
        "perspectives": [
            {"speaker": "spk_0", "position": "Keep the 2014 goal.", "span_ids": ["s1"], "start_ms": 1000},
            {"speaker": "spk_1", "position": "Invented.", "span_ids": ["gone"], "start_ms": 0},
        ],
        "outcome": {"text": "No decision was reached.", "span_ids": ["s1"], "start_ms": 1000},
    }
    digest = project_meeting({"meeting_id": "m1", "status": "ready", "prompt_release": "r", **graph})["graph"]["digest"]
    assert [row["name"] for row in digest["speakers"]] == ["Dr. Casserly"]
    assert [row["position"] for row in digest["perspectives"]] == ["Keep the 2014 goal."]
    assert digest["outcome"]["text"] == "No decision was reached."
    graph["digest"]["outcome"] = {"text": "Ghost.", "span_ids": ["gone"]}
    assert project_meeting({"meeting_id": "m1", "status": "ready", "prompt_release": "r", **graph})["graph"]["digest"]["outcome"] is None


def test_brief_uses_names_a_person_gave_voices_and_never_a_raw_voice_id():
    graph = published_graph("m1")
    graph["digest"] = {
        "content_type": "meeting", "title": "Plan",
        "summary": [{"text": "spk_1 will send the quote.", "span_ids": ["s1"], "basis": "confirmed", "start_ms": 1000}],
        "decisions": [{"statement": "Ship Friday", "status": "agreed", "decided_by": "spk_1", "span_ids": ["s1"], "basis": "confirmed", "start_ms": 1000}],
        "speakers": [{"id": "spk_1", "name": "Priya", "role": "lead", "span_ids": ["s1"]}],
    }
    projected = project_meeting({"meeting_id": "m1", "status": "ready", "prompt_release": "r", **graph})
    mime, body = render_local("brief.html", projected)
    text = body.decode()
    assert "decided by Priya (lead)" in text and "Priya (lead) will send the quote." in text and "spk_" not in text
    voiced = [dict(projected["graph"]["spans"][0], speaker_hypothesis_id="spk_1", speaker_display="Priya Nair")]
    typed = dict(projected["graph"], spans=voiced + projected["graph"]["spans"][1:])
    mime, body = render_local("brief.html", {**projected, "graph": typed})
    assert "decided by Priya Nair" in body.decode()  # a typed name outranks the one the transcript gave


def test_digest_drops_a_reply_to_a_line_that_is_gone_and_keeps_topics_contiguous():
    graph = published_graph("m1")
    graph["spans"].append(dict(graph["spans"][0], span_id="s9", start_ms=15000, end_ms=20000))
    graph["digest"] = {
        "content_type": "meeting", "title": "x", "summary": [],
        "open_questions": [{"question": "Who?", "asked_span_id": "s1", "answered": True, "answer": "Me", "answer_span_id": "gone", "answer_ms": 5, "start_ms": 1000}],
        "chapters": [
            {"title": "A", "gist": "", "start_span_id": "s1", "start_ms": 0, "end_ms": 4000},
            {"title": "Gone", "gist": "", "start_span_id": "gone", "start_ms": 5000, "end_ms": 9000},
            {"title": "C", "gist": "", "start_span_id": "s1", "start_ms": 10000, "end_ms": 99999},
        ],
    }
    digest = project_meeting({"meeting_id": "m1", "status": "ready", "prompt_release": "r", **graph})["graph"]["digest"]
    question = digest["open_questions"][0]
    assert (question["answered"], question["answer"], question["answer_span_id"]) == (False, None, None)
    assert [(c["title"], c["start_ms"], c["end_ms"]) for c in digest["chapters"]] == [("A", 0, 10000), ("C", 10000, 20000)]  # contiguous, and the last stops at the last spoken line


def test_summary_names_the_task_that_uploaded_the_recording_so_a_client_can_tie_its_own_submission_to_it():
    uploaded = project_meeting({"meeting_id": "m1", "status": "queued", "object_key": "uploads/AbC-123_x/Weekly sync.mp4"})
    assert summary(uploaded)["task_id"] == "AbC-123_x"
    assert "task_id" not in summary(project_meeting({"meeting_id": "m2", "status": "queued", "object_key": "derivatives/local.mp4"}))
    assert "task_id" not in summary(project_meeting({"meeting_id": "m3", "status": "queued", "object_key": "uploads/../x/y.mp4"}))


def test_a_script_in_the_summary_text_is_escaped_in_the_brief_even_when_a_diagram_is_present():
    graph = published_graph("m1")
    graph["digest"] = {
        "content_type": "meeting", "title": "T",
        "summary": [{"text": "Ship <script>alert(1)</script> now.", "span_ids": ["s1"], "basis": "confirmed", "start_ms": 1000}],
        "diagram": {"kind": "flowchart", "title": "Flow", "mermaid": "flowchart LR\n  A --> B", "span_ids": ["s1"], "start_ms": 1000},
    }
    projected = project_meeting({"meeting_id": "m1", "status": "ready", "prompt_release": "r", **graph})
    _, page = render_local("brief.html", projected)
    text = page.decode("utf-8")
    body = text.split("</h1>", 1)[1]
    assert "<script>alert" not in body and "&lt;script&gt;alert(1)&lt;/script&gt;" in body
    # A diagram the server can draw is inline SVG: the page needs no script at all, and none comes from the text.
    assert "<script" not in body and "<svg" in body and ">A</text>" in body


def test_the_context_block_never_carries_storage_keys_or_batch_ids():
    raw = {"meeting_id": "m1", "status": "queued", "object_key": "uploads/t/x.mp4", "context": {
        "purpose": "Why we meet", "batch_id": "b1",
        "items": [{"name": "a.md", "key": "context/b1/00-a.md", "bytes": 10, "status": "ready", "reason": None, "chars": 10, "summary": "gist"},
                  {"name": "b.pdf", "key": "context/b1/01-b.pdf", "status": "weird", "reason": "r", "chars": True}]}}
    block = summary(project_meeting(raw))["context"]
    assert block == {"purpose": "Why we meet", "items": [
        {"name": "a.md", "status": "ready", "reason": None, "chars": 10, "summary": "gist"},
        {"name": "b.pdf", "status": "pending", "reason": "r", "chars": None, "summary": None},  # an unknown status is pending; a boolean is not a size
    ]}
    assert "context/b1" not in str(summary(project_meeting(raw))) and "b1" not in str(block)


def test_a_digest_statement_loses_commentary_about_the_transcript_itself():
    from quotient.graph.gate import _digest

    spans = {"s1": {"kind": "speech", "start_ms": 0, "end_ms": 4000}}
    stored = {
        "content_type": "discussion",
        "title": "Hearing",
        "perspectives": [
            {"speaker": "spk_2", "text": "Challenges the distinction between national and federal standards; the continuing argument under Speaker 8 criticizes dependence on Washington.", "span_ids": ["s1"], "start_ms": 0},
            {"speaker": "spk_3", "text": "States that retaining the 2014 requirements is critical; the year is completed in the following line labeled Speaker 7.", "span_ids": ["s1"], "start_ms": 0},
            {"speaker": "spk_4", "text": "The continuing argument under spk_2 supports the plan.", "span_ids": ["s1"], "start_ms": 0},
            {"speaker": "spk_1", "text": "Speaker 1 stressed the need for data systems and proposed three years.", "span_ids": ["s1"], "start_ms": 0},
        ],
    }
    out = _digest(stored, spans)["perspectives"]
    assert [row["text"] for row in out] == [
        "Challenges the distinction between national and federal standards.",
        "States that retaining the 2014 requirements is critical.",
        "Speaker 1 stressed the need for data systems and proposed three years.",  # naming a speaker is fine; describing lines is not
    ]
    assert "continuing argument" in stored["perspectives"][0]["text"]  # the stored digest itself is not changed


def test_a_choice_described_from_the_past_is_not_a_decision():
    from quotient.graph.gate import _digest

    spans = {"s1": {"kind": "speech", "start_ms": 0, "end_ms": 4000}}
    stored = {"decisions": [
        {"statement": "Historically, Creative Commons chose to offer a suite of licenses.", "status": "agreed", "span_ids": ["s1"], "start_ms": 0},
        {"statement": "The team chose to ship the export on Friday.", "status": "agreed", "span_ids": ["s1"], "start_ms": 0},
        {"statement": "Previously we agreed, and now we will revisit it in March.", "status": "tentative", "span_ids": ["s1"], "start_ms": 0},
    ]}
    assert [row["statement"] for row in _digest(stored, spans)["decisions"]] == [
        "The team chose to ship the export on Friday.",
        "Previously we agreed, and now we will revisit it in March.",  # "previously" can introduce a real, current decision, so it is kept
    ]


def test_a_stored_action_owner_who_never_spoke_the_cited_line_is_corrected_or_cleared():
    from quotient.graph.gate import _digest

    spans = {
        "p1": {"kind": "speech", "start_ms": 0, "end_ms": 3000, "speaker_hypothesis_id": "spk_1", "text": "um we will be explicit about every requirement"},
        "p2": {"kind": "speech", "start_ms": 4000, "end_ms": 6000, "speaker_hypothesis_id": "spk_0", "text": "Maddy can you send the notes"},
        "p3": {"kind": "speech", "start_ms": 6500, "end_ms": 7500, "speaker_hypothesis_id": "spk_2", "text": "sure thing"},
    }
    stored = {"actions": [
        {"task": "Classify", "assignee": "spk_2", "span_ids": ["p1"], "start_ms": 0},
        {"task": "Send the notes", "assignee": "spk_2", "span_ids": ["p2", "p3"], "start_ms": 4000},
        {"task": "Send again", "assignee": "spk_2", "span_ids": ["p2"], "start_ms": 4000},
    ]}
    assert [(a["task"], a["assignee"]) for a in _digest(stored, spans)["actions"]] == [("Classify", "spk_1"), ("Send the notes", "spk_2"), ("Send again", None)]
    assert stored["actions"][0]["assignee"] == "spk_2"  # the stored digest itself is not changed
