import subprocess
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


def _port_module():
    path = Path(__file__).resolve().parents[2] / "apps" / "worker" / "quotient" / "port.py"
    spec = importlib.util.spec_from_file_location("worker_port_persistence_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _port_type():
    return _port_module().Port


def test_local_port_restores_completed_meetings_and_marks_interrupted_work(tmp_path):
    Port = _port_type()
    state = tmp_path / "meetings.json"
    port = Port(None, None, None, None, state_path=state)
    port._rows["done"] = {
        "meeting_id": "done",
        "subject": "person@example.test",
        "status": "needs_review",
        "idempotency_key": "request-1",
        "artifacts": {"exports": "ready"},
        "spans": [],
    }
    port._rows["busy"] = {
        "meeting_id": "busy",
        "subject": "person@example.test",
        "status": "working",
        "idempotency_key": None,
        "artifacts": {"exports": "not_run"},
        "spans": [],
    }
    with port._lock:
        port._save_locked()

    restored = Port(None, None, None, None, state_path=state)
    assert restored.meeting("done", "person@example.test")["status"] == "needs_review"
    interrupted = restored.meeting("busy", "person@example.test")
    assert interrupted["status"] == "failed"
    assert "restarted" in interrupted["failure_message"]
    assert restored._idempotency[("person@example.test", "request-1")] == "done"
    # Export bytes are in-memory, so stale ready state must not survive restart.
    assert interrupted["artifacts"]["exports"] == "not_run"
    assert json.loads(state.read_text())["version"] == 1


def test_media_url_is_owner_scoped_and_uses_local_minio_credentials(tmp_path, monkeypatch):
    Port = _port_type()
    port = Port(None, None, None, None, state_path=tmp_path / "state.json")
    port._rows["m1"] = {"meeting_id": "m1", "subject": "owner", "status": "ready", "object_key": "derivatives/source.mp4"}
    calls = []
    monkeypatch.setattr(
        "subprocess.run",
        lambda command, **kwargs: calls.append((command, kwargs))
        or SimpleNamespace(returncode=0, stdout="http://127.0.0.1:9000/signed", stderr=""),
    )
    monkeypatch.setenv("QUOTIENT_ENVIRONMENT", "local")
    monkeypatch.setenv("QUOTIENT_MEDIA_BUCKET", "axion-meeting-local")
    monkeypatch.setenv("QUOTIENT_S3_ENDPOINT_URL", "http://127.0.0.1:9000")
    monkeypatch.setenv("QUOTIENT_S3_ACCESS_KEY_ID", "minio-user")
    monkeypatch.setenv("QUOTIENT_S3_SECRET_ACCESS_KEY", "minio-secret")

    assert port.media_url("m1", "other") is None
    assert calls == []
    assert port.media_url("m1", "owner") == "http://127.0.0.1:9000/signed"
    command, options = [call for call in calls if "presign" in call[0]][0]
    assert "--expires-in" in command and command[command.index("--expires-in") + 1] == "3600"
    assert options["env"]["AWS_ACCESS_KEY_ID"] == "minio-user"
    assert options["env"]["AWS_SECRET_ACCESS_KEY"] == "minio-secret"


def test_local_startup_queues_interrupted_analysis_for_automatic_resume(tmp_path, monkeypatch):
    module = _port_module()
    state = tmp_path / "meetings.json"
    state.write_text(json.dumps({"version": 1, "meetings": [{
        "meeting_id": "resume-me",
        "subject": "owner",
        "object_key": "derivatives/source.mp4",
        "context_names": [],
        "status": "working",
        "failure_message": None,
        "progress_message": "Extracting claims from the transcript",
        "artifacts": {"ledger": "ready", "exports": "not_run"},
        "spans": [],
        "claims": [],
    }]}))
    scheduled = []

    class FakeThread:
        def __init__(self, *, target, args, name, daemon):
            scheduled.append((target, args, name, daemon))

        def start(self):
            pass

    monkeypatch.setattr(module.threading, "Thread", FakeThread)
    port = module.Port(None, None, None, None, state_path=state, resume_interrupted=True)
    row = port.meeting("resume-me", "owner")
    assert row["status"] == "queued"
    assert row["failure_message"] is None
    assert row["progress_message"] == "Restarting analysis from the source after the local app restarted"
    assert len(scheduled) == 1
    assert scheduled[0][1] == ("resume-me",)
    assert scheduled[0][2:] == ("quotient-analysis-resume", True)


def _presign_keys(tmp_path, monkeypatch, *, own_copy_exists):
    Port = _port_type()
    port = Port(None, None, None, None, state_path=tmp_path / "state.json")
    port._rows["m1"] = {"meeting_id": "m1", "subject": "owner", "status": "ready", "object_key": "derivatives/source.mp4"}
    signed = []

    def run(command, **kwargs):
        if "head-object" in command:
            ok = own_copy_exists and command[command.index("--key") + 1] == "derivatives/m1-0.mp4"
            return SimpleNamespace(returncode=0 if ok else 254, stdout="", stderr="")
        signed.append(command[command.index("presign") + 1])
        return SimpleNamespace(returncode=0, stdout="http://127.0.0.1:9000/signed", stderr="")

    monkeypatch.setattr("subprocess.run", run)
    monkeypatch.setenv("QUOTIENT_ENVIRONMENT", "local")
    monkeypatch.setenv("QUOTIENT_MEDIA_BUCKET", "axion-meeting-local")
    monkeypatch.setenv("QUOTIENT_S3_ENDPOINT_URL", "http://127.0.0.1:9000")
    assert port.media_url("m1", "owner")
    return signed


def test_local_playback_signs_the_per_meeting_upload_when_the_submitted_key_is_not_in_the_bucket(tmp_path, monkeypatch):
    assert _presign_keys(tmp_path, monkeypatch, own_copy_exists=True) == ["s3://axion-meeting-local/derivatives/m1-0.mp4"]


def test_local_playback_falls_back_to_the_submitted_key(tmp_path, monkeypatch):
    assert _presign_keys(tmp_path, monkeypatch, own_copy_exists=False) == ["s3://axion-meeting-local/derivatives/source.mp4"]


def test_aws_playback_signs_the_submitted_key_without_probing(tmp_path, monkeypatch):
    Port = _port_type()
    port = Port(None, None, None, None, state_path=tmp_path / "state.json")
    port._rows["m1"] = {"meeting_id": "m1", "subject": "owner", "status": "ready", "object_key": "derivatives/source.mp4"}
    calls = []
    monkeypatch.setattr(
        "subprocess.run",
        lambda command, **kwargs: calls.append(command) or SimpleNamespace(returncode=0, stdout="https://s3/signed", stderr=""),
    )
    monkeypatch.setenv("QUOTIENT_MEDIA_BUCKET", "prod-bucket")
    monkeypatch.delenv("QUOTIENT_S3_ENDPOINT_URL", raising=False)
    assert port.media_url("m1", "owner") == "https://s3/signed"
    assert len(calls) == 1 and calls[0][calls[0].index("presign") + 1] == "s3://prod-bucket/derivatives/source.mp4"


def test_public_failures_are_plain_sentences_without_paths_or_commands(capsys):
    module = _port_module()
    bad = subprocess.CalledProcessError(1, ["ffprobe", "-v", "error", "/Users/someone/derivatives/x.mp4"])
    assert module._public_failure(bad) == "This file is not a readable audio or video recording."
    assert module._public_failure(FileNotFoundError("media object is not on disk")) == "The recording could not be found."
    assert "content filters" not in module._public_failure(RuntimeError("validationException: RequestId=abc blocked by our content filters"))
    for exc in (bad, RuntimeError("AKIA secret Bearer x"), KeyError("k")):
        text = module._public_failure(exc)
        assert "/Users" not in text and "AKIA" not in text and "Bearer" not in text and "ffprobe" not in text
    # the raw detail goes to the log, not the row
    assert "/Users/someone" in capsys.readouterr().err


def test_checkpoint_keys_are_scoped_by_subject_so_one_tenant_cannot_replay_anothers_analysis(tmp_path):
    seen = []

    def quality_run(ledger, model, registry, checkpoints, key, **kwargs):
        seen.append(key)
        return SimpleNamespace(status="needs_review")

    Port = _port_type()
    port = Port(quality_run, {}, None, None, state_path=tmp_path / "state.json")
    for meeting_id, subject in (("m1", "alice"), ("m2", "bob")):
        port._rows[meeting_id] = {
            "meeting_id": meeting_id, "subject": subject, "status": "queued",
            "idempotency_key": "weekly", "updated_at": "", "artifacts": {},
        }
    for meeting_id in ("m1", "m2"):
        try:
            port.run_quality(SimpleNamespace(meeting_id=meeting_id), None, None)
        except Exception:
            pass  # projection of the stub result is not under test; the key is
    assert len(seen) == 2 and seen[0] != seen[1]
    assert all("weekly" in key for key in seen)


def test_no_media_url_is_signed_for_a_meeting_that_never_ingested_anything(tmp_path, monkeypatch):
    Port = _port_type()
    port = Port(None, None, None, None, state_path=tmp_path / "state.json")
    # a client names an object_key it does not own; the submission failed before any ingest
    port._rows["m1"] = {"meeting_id": "m1", "subject": "owner", "status": "failed", "spans": [], "object_key": "derivatives/someone-elses.mp4"}
    called = []
    monkeypatch.setattr("subprocess.run", lambda *a, **k: called.append(a) or SimpleNamespace(returncode=0, stdout="http://x/s", stderr=""))
    monkeypatch.setenv("QUOTIENT_MEDIA_BUCKET", "bucket")
    assert port.media_url("m1", "owner") is None
    assert called == []


def test_a_restart_loop_cannot_resume_the_same_meeting_forever(tmp_path):
    import json as _json

    module = _port_module()
    state = tmp_path / "meetings.json"
    row = {"meeting_id": "loop", "subject": "owner", "object_key": "derivatives/x.mp4", "context_names": [], "status": "working", "resumes": 2, "artifacts": {}, "spans": [], "claims": []}
    state.write_text(_json.dumps({"version": 1, "meetings": [row]}))
    scheduled = []

    class FakeThread:
        def __init__(self, **kwargs):
            scheduled.append(kwargs)

        def start(self):
            pass

    import types

    original = module.threading.Thread
    module.threading.Thread = FakeThread
    try:
        port = module.Port(None, None, None, None, state_path=state, resume_interrupted=True)
    finally:
        module.threading.Thread = original
    fresh = port.meeting("loop", "owner")
    assert fresh["status"] == "failed"
    assert "interrupted too many times" in fresh["failure_message"]
    assert scheduled == []


def test_claim_rows_keep_the_verdict_diagnostics_but_the_api_view_does_not_expose_them():
    module = _port_module()
    from graph.state import Claim

    claim = Claim(
        id="c1", meeting_id="m", kind="decision", proposition="p", paraphrase="p", quote="q",
        status="gap", span_id="s1", sol_label="entails", luna_label="neutral", searched_ids=["s1"], opened_ids=["s1", "s2"],
    )
    verdict = module._claim_row(claim)["verdict"]
    assert verdict == {"sol": "entails", "luna": "neutral", "searched": 1, "opened": 2, "search_matches_open": False, "quote_resolved": True, "contradiction": False}


def test_a_rejected_sign_in_gets_an_actionable_sentence():
    module = _port_module()
    text = module._public_failure(RuntimeError("sonic HTTP 403: check the configured AWS identity, Sonic model access, and bidirectional-stream permission"))
    assert "Sign in to AWS again" in text and "HTTP" not in text
