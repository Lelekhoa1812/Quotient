"""Several processes share one stored meeting document: a save must not erase their meetings, and a read must see them."""

import copy

from quotient import seed


def row(meeting_id, updated_at, status="queued", subject="me"):
    return {"meeting_id": meeting_id, "subject": subject, "status": status, "updated_at": updated_at}


def test_a_save_keeps_meetings_another_process_added():
    stored = [row("a", "2026-11-11T00:00:05Z", "working"), row("b", "2026-11-11T00:00:01Z")]
    mine = [row("b", "2026-11-11T00:00:09Z", "ready"), row("c", "2026-11-11T00:00:02Z")]
    merged = {r["meeting_id"]: r for r in seed.merge_rows(stored, mine)}
    assert set(merged) == {"a", "b", "c"}
    assert merged["b"]["status"] == "ready"  # mine is newer
    assert merged["a"]["status"] == "working"  # another process's, kept


def test_a_stale_copy_never_overwrites_a_newer_stored_row():
    stored = [row("a", "2026-11-11T00:00:09Z", "ready")]
    stale = [row("a", "2026-11-11T00:00:01Z", "queued")]
    assert seed.merge_rows(stored, stale)[0]["status"] == "ready"


def test_a_tie_goes_to_the_writer_and_rows_without_ids_are_dropped():
    stored = [row("a", "2026-11-11T00:00:05Z", "working")]
    mine = [row("a", "2026-11-11T00:00:05Z", "failed"), {"status": "queued"}]
    merged = seed.merge_rows(stored, mine)
    assert len(merged) == 1 and merged[0]["status"] == "failed"


class Port:
    def __init__(self):
        self._rows = {}
        self._idempotency = {}


def test_a_read_adopts_missing_and_newer_rows_but_not_older_or_foreign_ones():
    port = Port()
    port._rows["old"] = row("old", "2026-11-11T00:00:09Z", "ready")
    port._rows["mine"] = row("mine", "2026-11-11T00:00:01Z", "queued")
    incoming = [
        row("new", "2026-11-11T00:00:02Z", "queued"),  # never seen here
        row("old", "2026-11-11T00:00:01Z", "queued"),  # older than what this process has
        row("mine", "2026-11-11T00:00:07Z", "ready"),  # advanced by another process
        row("mine", "2026-11-11T00:00:08Z", "ready", subject="someone else"),  # a different owner's row of the same id
    ]
    incoming[0]["idempotency_key"] = "k1"
    assert seed.adopt(port, copy.deepcopy(incoming)) == 2
    assert port._rows["new"]["status"] == "queued" and port._idempotency[("me", "k1")] == "new"
    assert port._rows["old"]["status"] == "ready"
    assert port._rows["mine"]["status"] == "ready" and port._rows["mine"]["subject"] == "me"


def test_on_the_cloud_a_cold_start_does_not_rewrite_a_meeting_another_process_is_analysing(monkeypatch):
    monkeypatch.setenv("ARTIFACTS_BUCKET", "bucket")
    monkeypatch.setenv("QUOTIENT_ENVIRONMENT", "staging")
    port = Port()
    port._lock = None
    assert seed.install(port, {"meetings": [row("w", "2026-11-11T00:00:09Z", "working")]}) == 1
    assert port._rows["w"]["status"] == "working"
    monkeypatch.delenv("ARTIFACTS_BUCKET")
    other = Port()
    seed.install(other, {"meetings": [row("w", "2026-11-11T00:00:09Z", "working")]})
    assert other._rows["w"]["status"] == "needs_review"  # a restarted local app cannot still be running it
