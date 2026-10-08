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
