"""Long analyses leave the 15-minute Lambda for a one-off Fargate task; the Lambda falls back to itself when it can't."""

import sys
import types

import pytest

import lambda_runner

ENV = {
    "LONG_JOB_TASK_DEFINITION_ARN": "arn:aws:ecs:ap-southeast-2:1:task-definition/w:7",
    "CLUSTER_ARN": "arn:aws:ecs:ap-southeast-2:1:cluster/c",
    "LONG_JOB_SUBNET_IDS": "subnet-a,subnet-b",
    "LONG_JOB_SECURITY_GROUP_ID": "sg-1",
}


class Ecs:
    """Stands in for the AWS CLI call: records the request it is given."""

    def __init__(self, reply=None, error=None):
        self.calls = []
        self.reply = reply if reply is not None else {"tasks": [{"taskArn": "t"}], "failures": []}
        self.error = error

    def __call__(self, request):
        self.calls.append(request)
        if self.error:
            raise self.error
        return self.reply


@pytest.fixture
def configured(monkeypatch):
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)


def test_a_configured_deployment_starts_the_worker_task_for_the_meeting(configured):
    ecs = Ecs()
    assert lambda_runner.start_long_job("m1", runner=ecs) is True
    call = ecs.calls[0]
    assert call["taskDefinition"] == ENV["LONG_JOB_TASK_DEFINITION_ARN"] and call["launchType"] == "FARGATE"
    assert call["networkConfiguration"]["awsvpcConfiguration"]["assignPublicIp"] == "ENABLED"
    assert call["networkConfiguration"]["awsvpcConfiguration"]["subnets"] == ["subnet-a", "subnet-b"]
    override = call["overrides"]["containerOverrides"][0]
    assert override["command"] == ["python", "apps/worker/task_runner.py"]
    assert override["environment"] == [{"name": "MEETING_ID", "value": "m1"}]


def test_without_the_settings_the_lambda_runs_the_analysis_itself(monkeypatch):
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    ecs = Ecs()
    assert lambda_runner.start_long_job("m1", runner=ecs) is False and not ecs.calls


def test_a_task_that_could_not_start_falls_back_instead_of_losing_the_meeting(configured):
    assert lambda_runner.start_long_job("m1", runner=Ecs(error=RuntimeError("AccessDenied"))) is False
    assert lambda_runner.start_long_job("m1", runner=Ecs(reply={"tasks": [], "failures": [{"reason": "RESOURCE:CPU"}]})) is False


def test_the_handler_does_not_analyse_inline_when_the_task_started(configured, monkeypatch):
    ran = []

    class Port:
        _rows = {"m1": {}, "m2": {}}

        def _analyze(self, meeting_id):
            ran.append(meeting_id)

    _fake_worker_port(monkeypatch, Port())
    monkeypatch.setattr(lambda_runner, "start_long_job", lambda meeting_id, runner=None: True)
    out = lambda_runner.handler({"Records": [{"body": '{"meeting_id": "m1"}'}]}, None)
    assert out["processed"] == 1 and ran == []
    monkeypatch.setattr(lambda_runner, "start_long_job", lambda meeting_id, runner=None: False)
    lambda_runner.handler({"Records": [{"body": '{"meeting_id": "m2"}'}]}, None)
    assert ran == ["m2"]


def test_the_task_runner_analyses_the_named_meeting_and_flushes(monkeypatch):
    import task_runner

    seen = []

    class Port:
        _rows = {"m9": {}}

        def _analyze(self, meeting_id):
            seen.append(("analyze", meeting_id))

        def flush_storage(self):
            seen.append(("flush",))

    _fake_worker_port(monkeypatch, Port())
    monkeypatch.setenv("MEETING_ID", "m9")
    assert task_runner.main() == 0 and seen == [("analyze", "m9"), ("flush",)]
    monkeypatch.delenv("MEETING_ID")
    assert task_runner.main() == 2


def test_an_error_outside_the_analysis_marks_the_meeting_failed(monkeypatch):
    import task_runner

    failed = []

    class Port:
        _rows = {"m3": {}}

        def _analyze(self, meeting_id):
            raise MemoryError()

        def _fail(self, meeting_id, message):
            failed.append(meeting_id)

    _fake_worker_port(monkeypatch, Port())
    monkeypatch.setenv("MEETING_ID", "m3")
    assert task_runner.main() == 1 and failed == ["m3"]


def _fake_worker_port(monkeypatch, port):
    # Not the real module: importing it changes how PortError resolves for every test that runs after this one.
    module = types.ModuleType("quotient.worker.port")
    module.load_worker_port = lambda: port
    monkeypatch.setitem(sys.modules, "quotient.worker.port", module)


def test_the_task_is_started_with_the_aws_cli_because_the_image_has_no_boto3(monkeypatch):
    import json
    import subprocess

    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout='{"tasks": [{"taskArn": "t"}], "failures": []}', stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    out = lambda_runner._aws_run_task({"cluster": "c", "count": 1})
    assert out["tasks"] and seen["argv"][:3] == ["aws", "ecs", "run-task"]
    assert json.loads(seen["argv"][seen["argv"].index("--cli-input-json") + 1]) == {"cluster": "c", "count": 1}

    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 255, stdout="", stderr="AccessDenied"))
    with pytest.raises(RuntimeError, match="exited 255"):
        lambda_runner._aws_run_task({})


def test_the_runner_waits_for_a_meeting_that_has_not_reached_it_yet(monkeypatch):
    import task_runner

    class Port:
        def __init__(self):
            self._rows = {}
            self.syncs = 0

        def _sync_remote(self, meeting_id=None):
            self.syncs += 1
            if self.syncs == 2:
                self._rows["m5"] = {"meeting_id": "m5"}

    monkeypatch.setattr(task_runner.time, "sleep", lambda seconds: None)
    port = Port()
    assert task_runner.wait_for_meeting(port, "m5", attempts=5, pause=0) is True and port.syncs == 2
    assert task_runner.wait_for_meeting(Port(), "never", attempts=3, pause=0) is False


def test_the_runner_does_not_pretend_a_missing_meeting_was_analysed(monkeypatch):
    import task_runner

    class Port:
        _rows = {}
        called = False

        def _analyze(self, meeting_id):
            Port.called = True

    _fake_worker_port(monkeypatch, Port())
    monkeypatch.setenv("MEETING_ID", "gone")
    monkeypatch.setattr(task_runner, "wait_for_meeting", lambda port, meeting_id, **kw: False)
    assert task_runner.main() == 3 and Port.called is False
