import importlib.util
import json
import threading
from pathlib import Path
from types import SimpleNamespace


def _seed():
    path = Path(__file__).resolve().parents[2] / "apps" / "worker" / "quotient" / "seed.py"
    spec = importlib.util.spec_from_file_location("quotient_seed_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _Port:
    def __init__(self):
        self._lock = threading.Lock()
        self._rows = {}
        self._idempotency = {}


def test_install_keeps_an_existing_meeting_and_drops_export_bytes():
    seed = _seed()
    port = _Port()
    port._rows["kept"] = {"meeting_id": "kept", "subject": "portal", "status": "ready"}
    count = seed.install(
        port,
        {
            "meetings": [
                {"meeting_id": "kept", "subject": "portal", "status": "needs_review", "spans": [{"text": "new"}]},
                {"meeting_id": "", "subject": "portal"},
                "not-a-row",
                {
                    "meeting_id": "demo",
                    "subject": "portal",
                    "status": "needs_review",
                    "idempotency_key": "once",
                    "artifacts": {"exports": "ready"},
                    "spans": [{"text": "hello"}],
                },
            ]
        },
    )
    assert count == 1
    assert port._rows["kept"]["status"] == "ready"
    assert "spans" not in port._rows["kept"]
    assert port._rows["demo"]["artifacts"]["exports"] == "not_run"
    assert port._rows["demo"]["spans"][0]["text"] == "hello"
    assert port._idempotency[("portal", "once")] == "demo"


def test_a_missing_seed_object_installs_nothing():
    seed = _seed()

    def run(command, **kwargs):
        assert command[1] == "s3api" and command[2] == "get-object"
        return SimpleNamespace(returncode=254, stdout="", stderr="An error occurred (NoSuchKey) when calling the HeadObject operation: Not Found")

    assert seed.read_remote({"QUOTIENT_ENVIRONMENT": "staging", "ARTIFACTS_BUCKET": "artifacts"}, run=run) is None
    assert seed.load_into(_Port(), {"QUOTIENT_ENVIRONMENT": "local", "ARTIFACTS_BUCKET": "artifacts"}, run=run) == 0


def test_a_seed_document_is_installed_and_a_damaged_one_is_skipped(tmp_path):
    seed = _seed()
    body = {"version": 1, "meetings": [{"meeting_id": "demo", "subject": "portal", "status": "needs_review"}]}

    def run(command, **kwargs):
        Path(command[-1]).write_text(json.dumps(body), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    port = _Port()
    env = {"QUOTIENT_ENVIRONMENT": "staging", "ARTIFACTS_BUCKET": "artifacts", "QUOTIENT_SEED_KEY": "seed/meetings.json"}
    assert seed.load_into(port, env, run=run) == 1
    assert port._rows["demo"]["subject"] == "portal"

    def damaged(command, **kwargs):
        Path(command[-1]).write_text("{", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    assert seed.load_into(_Port(), env, run=damaged) == 0


def test_a_non_list_and_an_oversized_document_are_skipped():
    seed = _seed()
    assert seed.install(_Port(), {"meetings": {"meeting_id": "demo"}}) == 0

    def huge(command, **kwargs):
        Path(command[-1]).write_bytes(b"{" + b" " * (seed._MAX_BYTES + 1))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    env = {"QUOTIENT_ENVIRONMENT": "staging", "ARTIFACTS_BUCKET": "artifacts"}
    assert seed.read_remote(env, run=huge) is None
