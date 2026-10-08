from types import SimpleNamespace

import pytest

from loop import ingest


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        ("Your session has expired. Please reauthenticate using 'aws login'.", "AWS session expired"),
        ("An error occurred (AccessDenied) when calling PutObject", "lack permission"),
        ("opaque failure with account 123456789012", "check AWS credentials"),
    ],
)
def test_upload_failure_is_actionable_without_leaking_cli_output(monkeypatch, tmp_path, stderr, expected):
    monkeypatch.setattr(ingest.os, "environ", {"QUOTIENT_MEDIA_BUCKET": "test-bucket"})
    monkeypatch.setattr(
        ingest.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stderr=stderr),
    )

    with pytest.raises(RuntimeError) as error:
        ingest._put_object(tmp_path / "slice.mp4", "derivatives/meeting-0.mp4")

    message = str(error.value)
    assert expected in message
    assert stderr not in message


def test_local_s3_endpoint_is_passed_to_aws_cli(monkeypatch, tmp_path):
    monkeypatch.setattr(
        ingest.os,
        "environ",
        {
            "QUOTIENT_MEDIA_BUCKET": "local-bucket",
            "QUOTIENT_S3_ENDPOINT_URL": "http://127.0.0.1:9000",
            "QUOTIENT_S3_ACCESS_KEY_ID": "minio-user",
            "QUOTIENT_S3_SECRET_ACCESS_KEY": "minio-secret",
        },
    )
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(ingest.subprocess, "run", fake_run)

    uri = ingest._put_object(tmp_path / "slice.mp4", "derivatives/meeting-0.mp4")

    assert uri == "s3://local-bucket/derivatives/meeting-0.mp4"
    args, kwargs = calls[0]
    assert args[args.index("--endpoint-url") + 1] == "http://127.0.0.1:9000"
    assert kwargs["env"]["AWS_ACCESS_KEY_ID"] == "minio-user"
    assert kwargs["env"]["AWS_SECRET_ACCESS_KEY"] == "minio-secret"


def test_local_s3_upload_rejects_partial_credentials(monkeypatch, tmp_path):
    monkeypatch.setattr(
        ingest.os,
        "environ",
        {
            "QUOTIENT_MEDIA_BUCKET": "local-bucket",
            "QUOTIENT_S3_ENDPOINT_URL": "http://127.0.0.1:9000",
            "QUOTIENT_S3_ACCESS_KEY_ID": "minio-user",
        },
    )

    with pytest.raises(RuntimeError, match="both access and secret keys"):
        ingest._put_object(tmp_path / "slice.mp4", "derivatives/meeting-0.mp4")


def test_nonlocal_upload_requires_explicit_bucket(monkeypatch, tmp_path):
    monkeypatch.setattr(ingest.os, "environ", {"QUOTIENT_ENVIRONMENT": "production"})
    with pytest.raises(RuntimeError, match="QUOTIENT_MEDIA_BUCKET must be configured"):
        ingest._put_object(tmp_path / "slice.mp4", "derivatives/meeting-0.mp4")


def test_local_s3_video_ingest_records_skipped_visual_analysis(monkeypatch, tmp_path):
    source = tmp_path / "meeting.mp4"
    source.write_bytes(b"video")
    temporary_dirs = []
    monkeypatch.setenv("QUOTIENT_S3_ENDPOINT_URL", "http://127.0.0.1:9000")
    monkeypatch.setattr(ingest, "probe", lambda _path: {"format": {"duration": "1"}})
    monkeypatch.setattr(ingest, "classify_file", lambda _path: "video")

    def write_pcm(_source, dest):
        temporary_dirs.append(dest.parent)
        dest.write_bytes(b"\0" * 32000)

    monkeypatch.setattr(ingest, "write_pcm", write_pcm)
    monkeypatch.setattr(ingest, "_silence_ranges", lambda *_args: [])
    monkeypatch.setattr(ingest, "_put_object", lambda *_args: "s3://local/meeting.mp4")
    monkeypatch.setattr(ingest, "Registry", lambda: object())
    monkeypatch.setattr(ingest, "Transport", lambda: object())

    class FakeSonic:
        def __init__(self, *_args):
            pass

        def transcribe(self, *_args, **_kwargs):
            return [], []

    monkeypatch.setattr(ingest, "SonicClient", FakeSonic)

    stages = []
    ledger = ingest.assemble(source, "local-meeting", progress_callback=stages.append)

    assert ledger.observations == []
    assert len(ledger.notes) == 1
    assert "Visual analysis was skipped" in ledger.notes[0].statement
    assert stages == ["Streaming audio transcription; visual analysis is unavailable on local MinIO"]
    assert temporary_dirs and not temporary_dirs[0].exists()
