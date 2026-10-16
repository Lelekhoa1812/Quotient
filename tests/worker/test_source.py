from loop.ingest import open_source
import pytest


def test_a_local_derivatives_file_is_not_downloaded(tmp_path, monkeypatch):
    local = tmp_path / "kollab.mp4"
    local.write_bytes(b"x")
    monkeypatch.setattr("loop.ingest.resolve_object", lambda key: local)
    monkeypatch.setattr("media.storage.download", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("downloaded")))
    path, scratch = open_source("derivatives/kollab.mp4")
    assert path == local and scratch is None


def test_a_missing_derivatives_file_is_read_from_the_bucket(tmp_path, monkeypatch):
    fetched = tmp_path / "kollab.mp4"
    fetched.write_bytes(b"video")

    def fake_resolve(key):
        raise FileNotFoundError("media object is not on disk")

    def fake_download(key, directory=None, max_bytes=None):
        assert key == "derivatives/kollab.mp4"
        return fetched

    monkeypatch.setattr("loop.ingest.resolve_object", fake_resolve)
    monkeypatch.setattr("media.storage.download", fake_download)
    path, scratch = open_source("derivatives/kollab.mp4")
    assert path == fetched and scratch == fetched.parent


def test_a_key_outside_derivatives_is_not_fetched(monkeypatch):
    called = []
    monkeypatch.setattr("loop.ingest.resolve_object", lambda key: (_ for _ in ()).throw(FileNotFoundError("object key is outside derivatives")))
    monkeypatch.setattr("media.storage.download", lambda *args, **kwargs: called.append(1))
    with pytest.raises(FileNotFoundError, match="outside derivatives"):
        open_source("../secret.mp4")
    assert called == []


def test_an_upload_key_is_fetched_from_the_bucket(tmp_path, monkeypatch):
    fetched = tmp_path / "a.mp4"
    fetched.write_bytes(b"v")
    monkeypatch.setattr("loop.ingest.resolve_object", lambda key: (_ for _ in ()).throw(AssertionError("resolved")))
    monkeypatch.setattr("media.storage.download", lambda key, directory=None, max_bytes=None: fetched)
    path, scratch = open_source("uploads/x/a.mp4")
    assert path == fetched and scratch == fetched.parent
