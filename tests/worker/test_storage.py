import pytest

from media import storage


def test_upload_keys_are_minted_under_the_task_and_cannot_escape_it():
    assert storage.upload_key("task123", "Q3 review (final).mp4") == "uploads/task123/Q3-review-final.mp4"
    key = storage.upload_key("t/../x", "../../etc/passwd")
    assert key.startswith("uploads/tx/") and ".." not in key and key.count("/") == 2
    assert storage.upload_key("t", "") == "uploads/t/recording"


def test_only_audio_and_video_types_may_be_uploaded():
    assert storage.media_type_allowed("audio/mp4")
    assert storage.media_type_allowed("video/quicktime")
    assert not storage.media_type_allowed("application/pdf")
    assert not storage.media_type_allowed("text/html")
    assert not storage.media_type_allowed(None)


def test_port_refuses_non_media_and_oversize_uploads(tmp_path, monkeypatch):
    from quotient.port import Port

    port = Port(None, None, None, None, state_path=tmp_path / "state.json")
    monkeypatch.setattr(storage, "presign_put", lambda key, media_type: f"http://signed/{key}")
    target = port.upload_target("task1", "call.m4a", "audio/mp4", 1000)
    assert target == {
        "upload_url": "http://signed/uploads/task1/call.m4a",
        "method": "PUT",
        "headers": {"Content-Type": "audio/mp4"},
        "object_key": "uploads/task1/call.m4a",
    }
    with pytest.raises(Exception, match="audio or video"):
        port.upload_target("task1", "deck.pdf", "application/pdf", 10)
    with pytest.raises(Exception, match="5 GB"):
        port.upload_target("task1", "huge.mp4", "video/mp4", storage.MAX_UPLOAD_BYTES + 1)
