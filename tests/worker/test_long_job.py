"""Long analyses leave the 15-minute Lambda for a one-off Fargate task; the Lambda falls back to itself when it can't."""

import sys
from pathlib import Path

import pytest

import lambda_runner

ENV = {
    "LONG_JOB_TASK_DEFINITION_ARN": "arn:aws:ecs:ap-southeast-2:1:task-definition/w:7",
    "CLUSTER_ARN": "arn:aws:ecs:ap-southeast-2:1:cluster/c",
    "LONG_JOB_SUBNET_IDS": "subnet-a,subnet-b",
    "LONG_JOB_SECURITY_GROUP_ID": "sg-1",
}


class Ecs:
    def __init__(self, reply=None, error=None):
        self.calls = []
        self.reply = reply if reply is not None else {"tasks": [{"taskArn": "t"}], "failures": []}
        self.error = error

    def run_task(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.reply


@pytest.fixture
def configured(monkeypatch):
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)


def test_a_configured_deployment_starts_the_worker_task_for_the_meeting(configured):
    ecs = Ecs()
    assert lambda_runner.start_long_job("m1", client=ecs) is True
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
    assert lambda_runner.start_long_job("m1", client=ecs) is False and not ecs.calls


def test_a_task_that_could_not_start_falls_back_instead_of_losing_the_meeting(configured):
    assert lambda_runner.start_long_job("m1", client=Ecs(error=RuntimeError("AccessDenied"))) is False
    assert lambda_runner.start_long_job("m1", client=Ecs(reply={"tasks": [], "failures": [{"reason": "RESOURCE:CPU"}]})) is False


def test_the_handler_does_not_analyse_inline_when_the_task_started(configured, monkeypatch):
    ran = []

    class Port:
        def _analyze(self, meeting_id):
            ran.append(meeting_id)

    import quotient.worker.port as worker_port

    monkeypatch.setattr(worker_port, "load_worker_port", lambda: Port())
    monkeypatch.setattr(lambda_runner, "start_long_job", lambda meeting_id, client=None: True)
    out = lambda_runner.handler({"Records": [{"body": '{"meeting_id": "m1"}'}]}, None)
    assert out["processed"] == 1 and ran == []
    monkeypatch.setattr(lambda_runner, "start_long_job", lambda meeting_id, client=None: False)
    lambda_runner.handler({"Records": [{"body": '{"meeting_id": "m2"}'}]}, None)
    assert ran == ["m2"]


def test_the_task_runner_analyses_the_named_meeting_and_flushes(monkeypatch):
    import task_runner
    import quotient.worker.port as worker_port

    seen = []

    class Port:
        def _analyze(self, meeting_id):
            seen.append(("analyze", meeting_id))

        def flush_storage(self):
            seen.append(("flush",))

    monkeypatch.setattr(worker_port, "load_worker_port", lambda: Port())
    monkeypatch.setenv("MEETING_ID", "m9")
    assert task_runner.main() == 0 and seen == [("analyze", "m9"), ("flush",)]
    monkeypatch.delenv("MEETING_ID")
    assert task_runner.main() == 2


def test_an_error_outside_the_analysis_marks_the_meeting_failed(monkeypatch):
    import task_runner
    import quotient.worker.port as worker_port

    failed = []

    class Port:
        def _analyze(self, meeting_id):
            raise MemoryError()

        def _fail(self, meeting_id, message):
            failed.append(meeting_id)

    monkeypatch.setattr(worker_port, "load_worker_port", lambda: Port())
    monkeypatch.setenv("MEETING_ID", "m3")
    assert task_runner.main() == 1 and failed == ["m3"]
