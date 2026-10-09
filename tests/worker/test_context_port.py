import pytest

from media import storage
from quotient.port import Port, PortError


@pytest.fixture()
def port(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "presign_put", lambda key, media_type: f"http://signed/{key}?ct={media_type}")
    return Port(None, None, None, None, tmp_path / "state.json")


def _files(*names, size=1000):
    return [{"filename": name, "media_type": None, "byte_size": size} for name in names]


def test_prepare_context_mints_server_keys_and_one_signed_target_per_file(port):
    out = port.prepare_context("me", [{"filename": "../Design Doc.DOCX", "media_type": "Application/Vnd.X;charset=utf-8", "byte_size": 10}, {"filename": "notes.md", "media_type": None, "byte_size": None}])
    assert [u["index"] for u in out["uploads"]] == [0, 1]
    first = out["uploads"][0]
    assert first["object_key"].startswith(f"context/{out['batch_id']}/00-") and ".." not in first["object_key"] and " " not in first["object_key"]
    assert first["headers"] == {"Content-Type": "application/vnd.x"}  # parameters dropped so the signed header and the PUT agree
    assert out["uploads"][1]["headers"] == {"Content-Type": "application/octet-stream"}


def test_prepare_context_refuses_what_it_cannot_read_or_carry(port):
    for files, message in (
        (_files("photo.png"), "not a supported type"),
        (_files("a.exe"), "not a supported type"),
        (_files("noextension"), "not a supported type"),
        (_files("big.pdf", size=storage.CONTEXT_MAX_FILE_BYTES + 1), "larger than 25 MB"),
        (_files(*[f"f{i}.md" for i in range(21)]), "At most 20"),
        (_files(*[f"f{i}.pdf" for i in range(5)], size=storage.CONTEXT_MAX_FILE_BYTES), "over 100 MB"),
    ):
        with pytest.raises(PortError, match=message):
            port.prepare_context("me", files)


def test_without_object_storage_prepare_context_returns_none(tmp_path, monkeypatch):
    def unavailable(key, media_type):
        raise storage.StorageUnavailable("no bucket")

    monkeypatch.setattr(storage, "presign_put", unavailable)
    assert Port(None, None, None, None, tmp_path / "s.json").prepare_context("me", _files("a.md")) is None


def test_a_batch_belongs_to_the_subject_who_prepared_it(port):
    batch = port.prepare_context("alice", _files("a.md"))["batch_id"]
    assert [item["name"] for item in port.context_items("alice", batch)] == ["a.md"]
    assert port.context_items("mallory", batch) is None and port.context_items("alice", "nope") is None


def test_a_meeting_carries_its_purpose_and_items_but_only_for_the_batch_owner(port, monkeypatch):
    monkeypatch.setattr(port, "_analyze", lambda meeting_id: None)
    batch = port.prepare_context("alice", _files("design.pdf", "notes.md"))["batch_id"]
    mine = port.submit(subject="alice", object_key="uploads/t/x.mp4", context_names=(), idempotency_key=None, context_batch=batch, purpose="  Review the order service  ")
    row = port.meeting(mine, "alice")
    assert row["context"]["purpose"] == "Review the order service"
    assert [(i["name"], i["status"]) for i in row["context"]["items"]] == [("design.pdf", "pending"), ("notes.md", "pending")]
    # The batch was consumed by the first meeting, so a second submit cannot start without its documents.
    with pytest.raises(PortError, match="not found"):
        port.submit(subject="mallory", object_key="uploads/t/y.mp4", context_names=(), idempotency_key=None, context_batch=batch, purpose="")


def test_only_a_purpose_is_still_context_and_none_means_no_block(port, monkeypatch):
    monkeypatch.setattr(port, "_analyze", lambda meeting_id: None)
    only = port.submit(subject="a", object_key="uploads/t/x.mp4", context_names=(), idempotency_key=None, purpose="Why we meet")
    none = port.submit(subject="a", object_key="uploads/t/z.mp4", context_names=(), idempotency_key=None)
    assert port.meeting(only, "a")["context"] == {"purpose": "Why we meet", "items": []}
    assert "context" not in port.meeting(none, "a")


def test_loading_context_updates_each_item_and_a_failure_never_raises(port, monkeypatch):
    monkeypatch.setattr(port, "_analyze", lambda meeting_id: None)
    batch = port.prepare_context("a", _files("a.md"))["batch_id"]
    meeting = port.submit(subject="a", object_key="uploads/t/x.mp4", context_names=(), idempotency_key=None, context_batch=batch, purpose="p")
    import context.loader as loader
    from context.library import ContextDoc, ContextLibrary

    def fake(items, purpose, cache_dir=None, **kwargs):
        done = [{**items[0], "status": "ready", "chars": 12, "summary": "gist", "reason": None}]
        return ContextLibrary([ContextDoc("c1", "a.md", "# T\n\nbody text here is long")], purpose), done

    monkeypatch.setattr(loader, "load_library", fake)
    library = port._load_context(meeting)
    assert [doc.id for doc in library.docs] == ["c1"]
    assert port.meeting(meeting, "a")["context"]["items"][0]["status"] == "ready"

    def boom(*args, **kwargs):
        raise RuntimeError("storage exploded")

    monkeypatch.setattr(loader, "load_library", boom)
    assert port._load_context(meeting) is None  # the meeting goes on without its context
    assert port._load_context("unknown") is None


def test_a_context_that_could_not_be_read_says_so_on_the_row(port, monkeypatch):
    monkeypatch.setattr(port, "_analyze", lambda meeting_id: None)
    batch = port.prepare_context("a", _files("a.md", "b.md"))["batch_id"]
    meeting = port.submit(subject="a", object_key="uploads/t/x.mp4", context_names=(), idempotency_key=None, context_batch=batch)
    import context.loader as loader

    monkeypatch.setattr(loader, "load_library", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("disk")))
    assert port._load_context(meeting) is None
    items = port.meeting(meeting, "a")["context"]["items"]
    assert [item["status"] for item in items] == ["failed", "failed"]
    assert "ran without them" in items[0]["reason"]


def test_a_retry_with_the_same_key_returns_its_meeting_even_though_the_batch_is_spent(port, monkeypatch):
    monkeypatch.setattr(port, "_analyze", lambda meeting_id: None)
    batch = port.prepare_context("a", _files("a.md"))["batch_id"]
    args = dict(subject="a", object_key="uploads/t/x.mp4", context_names=(), idempotency_key="k1", context_batch=batch)
    first = port.submit(**args)
    assert port.submit(**args) == first


def test_the_review_prompt_body_contains_the_writing_prompt_body_so_the_two_cannot_drift():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "contracts" / "prompts"
    writing = (root / "meeting.digest.v1.yaml").read_text().split("body: |\n", 1)[1]
    review = (root / "meeting.digest_review.v1.yaml").read_text().split("body: |\n", 1)[1]
    assert writing.split("\n", 1)[1] in review


def test_a_batch_belongs_to_one_meeting_and_unused_ones_are_capped_and_expire(port, monkeypatch):
    import quotient.port as port_module

    monkeypatch.setattr(port, "_analyze", lambda meeting_id: None)
    batch = port.prepare_context("a", _files("a.md"))["batch_id"]
    port.submit(subject="a", object_key="uploads/t/x.mp4", context_names=(), idempotency_key=None, context_batch=batch)
    assert port.context_items("a", batch) is None  # consumed: a second submission must upload again

    first = port.prepare_context("a", _files("a.md"))["batch_id"]
    for _ in range(port_module.CONTEXT_BATCHES_PER_SUBJECT + 5):
        port.prepare_context("a", _files("a.md"))
    assert port.context_items("a", first) is None  # the oldest unused reservation made room
    assert len([r for r in port._context_batches.values() if r["subject"] == "a"]) == port_module.CONTEXT_BATCHES_PER_SUBJECT
    for record in port._context_batches.values():
        record["at"] -= port_module.CONTEXT_BATCH_SECONDS + 1
    assert port._context_batches and port.context_items("a", next(iter(port._context_batches))) is None  # expired on read
    assert port._context_batches == {}


def test_another_subjects_submission_cannot_take_a_batch_even_when_it_comes_first(port, monkeypatch):
    monkeypatch.setattr(port, "_analyze", lambda meeting_id: None)
    batch = port.prepare_context("alice", _files("a.md"))["batch_id"]
    with pytest.raises(PortError, match="not found"):  # refused, not started without the documents
        port.submit(subject="mallory", object_key="uploads/t/y.mp4", context_names=(), idempotency_key=None, context_batch=batch)
    mine = port.submit(subject="alice", object_key="uploads/t/x.mp4", context_names=(), idempotency_key=None, context_batch=batch)
    assert [item["name"] for item in port.meeting(mine, "alice")["context"]["items"]] == ["a.md"]  # still Alice's, untouched by the attempt


def test_a_purpose_is_cut_at_two_thousand_characters(port, monkeypatch):
    monkeypatch.setattr(port, "_analyze", lambda meeting_id: None)
    meeting = port.submit(subject="a", object_key="uploads/t/x.mp4", context_names=(), idempotency_key=None, purpose="p" * 2500)
    assert len(port.meeting(meeting, "a")["context"]["purpose"]) == 2000


def test_the_tested_prompt_wording_is_present_in_both_digest_prompts():
    """The action-recall pass and the claim check were chosen from measured comparisons; a later edit must not drop them unnoticed."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "contracts" / "prompts"
    for name in ("meeting.digest.v1.yaml", "meeting.digest_review.v1.yaml"):
        body = (root / name).read_text().split("body: |\n", 1)[1]
        # Action recall: a deliberate second pass, with precision guards.
        assert "second pass over the whole transcript for follow-ups" in body, name
        assert "a maybe or a conditional" in body.lower() or "A maybe or a conditional" in body, name
        # Claim check, and the guard added after it over-hedged a confirmed result on the lecture.
        assert "Claim check." in body, name
        assert "never turn something the speaker stated plainly into a hedge or a doubt" in body, name
        assert "keep a result the speaker confirmed as confirmed" in body, name
        assert "Delete or soften" not in body, name  # "soften" made a writer doubt a confirmed result
        # Rejected by measurement: a general coverage pass and a stricter decisions rule.
        assert "Coverage pass" not in body, name
        assert "a proposal that is only acknowledged" not in body, name
        assert "Signal only." not in body, name
