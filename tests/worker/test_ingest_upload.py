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

    class FakeFrames:
        def __init__(self, *_args, **_kwargs):
            pass

        def read_frames(self, *_args, **_kwargs):
            return [], 8000, 0

    monkeypatch.setattr("visual.frames.FrameReader", FakeFrames)

    stages = []
    ledger = ingest.assemble(source, "local-meeting", progress_callback=stages.append)

    assert ledger.observations == []
    assert len(ledger.notes) == 1
    assert "Video event descriptions were skipped" in ledger.notes[0].statement
    assert stages == ["Streaming audio transcription and reading the picture from video frames"]
    assert temporary_dirs and not temporary_dirs[0].exists()


def test_pegasus_parts_go_to_the_aws_bucket_when_media_is_on_minio(monkeypatch, tmp_path):
    # Bedrock cannot read MinIO, so with QUOTIENT_PEGASUS_BUCKET set the visual parts
    # must reach that AWS bucket, never the MinIO endpoint.
    source = tmp_path / "meeting.mp4"
    source.write_bytes(b"video")
    monkeypatch.setenv("QUOTIENT_S3_ENDPOINT_URL", "http://127.0.0.1:9000")
    monkeypatch.setenv("QUOTIENT_PEGASUS_BUCKET", "axion-meeting-dev-pegasus")
    monkeypatch.setattr(ingest, "probe", lambda _path: {"format": {"duration": "1"}})
    monkeypatch.setattr(ingest, "classify_file", lambda _path: "video")

    def write_pcm(_source, dest):
        dest.write_bytes(b"\0" * 32000)

    monkeypatch.setattr(ingest, "write_pcm", write_pcm)
    monkeypatch.setattr(ingest, "_silence_ranges", lambda *_args: [])
    monkeypatch.setattr(ingest, "_cut", lambda path, _part: path)
    puts = []

    def put_object(path, key, *, aws_bucket=None):
        puts.append((key, aws_bucket))
        return f"s3://{aws_bucket or 'axion-meeting-local'}/{key}"

    monkeypatch.setattr(ingest, "_put_object", put_object)
    monkeypatch.setattr(ingest, "Registry", lambda: object())
    monkeypatch.setattr(ingest, "Transport", lambda: object())
    uris = []

    class FakeSonic:
        def __init__(self, *_args):
            pass

        def transcribe(self, *_args, **_kwargs):
            return [], []

    class FakePegasus:
        def __init__(self, *_args):
            pass

        def analyze(self, parts, upload, meeting_id):
            uris.extend(upload(part) for part in parts)
            return SimpleNamespace(observations=[], notes=[], screens=[], sightings=[], failed_windows=0, incomplete=False)

    monkeypatch.setattr(ingest, "SonicClient", FakeSonic)
    monkeypatch.setattr(ingest, "PegasusClient", FakePegasus)
    stages = []
    ledger = ingest.assemble(source, "aws-pegasus-meeting", progress_callback=stages.append)

    assert uris == ["s3://axion-meeting-dev-pegasus/derivatives/aws-pegasus-meeting-0.mp4"]
    assert puts[-1] == ("derivatives/aws-pegasus-meeting-0.mp4", "axion-meeting-dev-pegasus")
    assert not any("Visual analysis was skipped" in note.statement for note in ledger.notes)
    assert stages == ["Transcribing audio and analyzing video in parallel"]


def test_aws_bucket_upload_drops_the_minio_endpoint_and_credentials(monkeypatch, tmp_path):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["env"] = kwargs.get("env")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        ingest.os,
        "environ",
        {
            "QUOTIENT_S3_ENDPOINT_URL": "http://127.0.0.1:9000",
            "QUOTIENT_S3_ACCESS_KEY_ID": "minio-user",
            "QUOTIENT_S3_SECRET_ACCESS_KEY": "minio-secret",
        },
    )
    monkeypatch.setattr(ingest.subprocess, "run", fake_run)
    uri = ingest._put_object(tmp_path / "part.mp4", "derivatives/m-0.mp4", aws_bucket="axion-meeting-dev-pegasus")

    assert uri == "s3://axion-meeting-dev-pegasus/derivatives/m-0.mp4"
    assert "--endpoint-url" not in seen["command"]
    assert seen["env"] is None
