"""Deleting a meeting must stick: the plan refuses running work, and a tombstone stops any process writing it back."""

from quotient import purge, seed


def row(meeting_id, status="needs_review", updated_at="2026-11-11T00:00:01Z", subject="me"):
    return {"meeting_id": meeting_id, "subject": subject, "status": status, "updated_at": updated_at}


DOC = {"version": 1, "meetings": [row("keep"), row("test-a"), row("busy", status="working"), row("test-b", status="failed")]}


def test_the_plan_removes_finished_meetings_and_refuses_running_ones():
    new, removed, refused, missing = purge.plan(DOC, ["test-a", "busy", "absent", "test-b", "test-a"])
    assert removed == ["test-a", "test-b"] and refused == ["busy"] and missing == ["absent"]
    assert [r["meeting_id"] for r in new["meetings"]] == ["keep", "busy"]
    assert new["deleted"] == ["test-a", "test-b"]


def test_a_second_purge_keeps_the_earlier_tombstones():
    once, _removed, _refused, _missing = purge.plan(DOC, ["test-a"])
    twice, removed, _refused, _missing = purge.plan(once, ["test-b"])
    assert removed == ["test-b"] and twice["deleted"] == ["test-a", "test-b"]


def test_a_warm_process_that_still_holds_a_deleted_meeting_cannot_write_it_back():
    stored = [row("keep")]
    mine = [row("keep"), row("test-a", updated_at="2026-11-11T00:00:09Z")]  # newer than the stored copy, still in memory
    merged = seed.merge_rows(stored, mine, {"test-a"})
    assert [r["meeting_id"] for r in merged] == ["keep"]


def test_a_read_drops_a_meeting_deleted_elsewhere_from_memory():
    class Port:
        def __init__(self):
            self._rows = {"test-a": row("test-a", updated_at="2026-11-11T00:00:09Z"), "keep": row("keep")}
            self._idempotency = {("me", "k"): "test-a"}

    port = Port()
    seed.adopt(port, [row("keep")], {"test-a"})
    assert "test-a" not in port._rows and ("me", "k") not in port._idempotency and "keep" in port._rows


def test_deleted_ids_reads_only_strings_from_the_document():
    assert seed.deleted_ids({"deleted": ["a", 3, "", "b"]}) == {"a", "b"}
    assert seed.deleted_ids({}) == set() and seed.deleted_ids({"deleted": "x"}) == set()
