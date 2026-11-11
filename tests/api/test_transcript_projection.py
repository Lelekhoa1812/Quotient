"""A transcript meeting projects without a recording: no playback, and the portal is told what it was made from."""

from quotient.graph.gate import page_graph, project_meeting, summary


def row(**extra):
    base = {
        "meeting_id": "m1", "subject": "me", "object_key": "uploads/t1/sync.md", "status": "ready",
        "spans": [], "claims": [], "findings": [], "synthesis": [], "actions": [], "disagreements": [], "omissions": [], "gaps": [],
        "none_in_transcript": [], "not_evaluated": [], "digest": None, "observations": [], "revisions": [],
    }
    base.update(extra)
    return base


def test_transcript_meeting_has_no_playback_and_carries_its_source():
    projected = project_meeting(row(source={"kind": "transcript", "format": "vtt", "timings": "estimated", "speakers": 3, "words": 900}, model_provider="nim"))
    assert projected["playback"] == "" and projected["graph"]["playback"] == ""
    assert projected["source"] == {"kind": "transcript", "format": "vtt", "timings": "estimated", "speakers": 3, "words": 900, "title": None, "truncated": False}
    paged, _ = page_graph(projected["graph"], 0, 50)
    assert paged["source"]["kind"] == "transcript" and paged["model_provider"] == "nim"
    assert summary(projected)["source"]["timings"] == "estimated" and summary(projected)["model_provider"] == "nim"
    assert projected["graph"]["captions"] is None  # estimated times must not become a caption file


def test_recording_meeting_is_unchanged():
    projected = project_meeting(row(object_key="uploads/t1/call.mp4"))
    assert projected["playback"] == "quotient://meetings/m1/media" and projected["source"] is None
    assert summary(projected)["model_provider"] == "bedrock" and "source" not in summary(projected)


def test_unknown_source_and_provider_values_are_not_passed_through():
    projected = project_meeting(row(source={"kind": "hacked"}, model_provider="<script>"))
    assert projected["source"] is None and projected["model_provider"] == "bedrock"


def test_an_upload_issued_without_a_task_belongs_only_to_the_person_it_was_issued_to():
    from quotient.mcp.jobs import issued_upload_id, owns_upload

    mine = f"uploads/{issued_upload_id('alice')}/notes.vtt"
    assert owns_upload("alice", None, mine)
    assert not owns_upload("bob", None, mine)
    assert owns_upload("bob", "task9", "uploads/task9/notes.vtt")  # the task's own key (the elicitation flow)
    assert not owns_upload("bob", "task9", "uploads/task8/notes.vtt")
    assert owns_upload("bob", None, "derivatives/sample.mp4")  # only browser uploads are bound to a person
