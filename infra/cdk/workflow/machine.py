# Motivation vs Logic
# Motivation: Run the meeting as a coarse standard workflow whose history
# stores job ids, not transcript bodies.
# Logic: Each stage sends one SQS message containing job_id, stage, and a
# task token, then waits. Heartbeat timeout is 5 minutes. Task timeout is
# 3 hours. Sonic and Pegasus run in parallel. The ten council dimensions run
# in parallel. Exports follow. Parallel results are discarded so the next
# state still sees the original job_id. Execution ceiling is 24 hours.
# CloudWatch logging is errors only and omits execution data.

from aws_cdk import Duration, aws_logs as logs, aws_sqs as sqs, aws_stepfunctions as sfn
from aws_cdk import aws_stepfunctions_tasks as tasks
from constructs import Construct

from quotient.names import COUNCIL_STAGES, PREFIX


class MeetingMachine(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        queue: sqs.IQueue,
        state_logs: logs.ILogGroup,
    ) -> None:
        super().__init__(scope, construct_id)
        self.queue = queue
        media = self._stage("MediaPrep", "media")
        perceive = sfn.Parallel(
            self,
            "Perceive",
            state_name="Perceive",
            result_path=sfn.JsonPath.DISCARD,
        )
        perceive.branch(self._stage("Sonic", "sonic"))
        perceive.branch(self._stage("Pegasus", "pegasus"))
        council = sfn.Parallel(
            self,
            "Council",
            state_name="Council",
            result_path=sfn.JsonPath.DISCARD,
        )
        for stage in COUNCIL_STAGES:
            council.branch(self._stage(_label(stage), stage))
        exports = self._stage("Exports", "exports")
        definition = media.next(perceive).next(council).next(exports)
        self.machine = sfn.StateMachine(
            self,
            "Dag",
            state_machine_name=PREFIX,
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            timeout=Duration.hours(24),
            tracing_enabled=False,
            logs=sfn.LogOptions(
                destination=state_logs,
                level=sfn.LogLevel.ERROR,
                include_execution_data=False,
            ),
        )

    def _stage(self, state_name: str, stage: str) -> tasks.SqsSendMessage:
        return tasks.SqsSendMessage(
            self,
            state_name,
            state_name=state_name,
            comment="Payload is job_id, stage, and task_token. No transcript body.",
            queue=self.queue,
            integration_pattern=sfn.IntegrationPattern.WAIT_FOR_TASK_TOKEN,
            heartbeat_timeout=sfn.Timeout.duration(Duration.minutes(5)),
            task_timeout=sfn.Timeout.duration(Duration.hours(3)),
            result_path=sfn.JsonPath.DISCARD,
            message_body=sfn.TaskInput.from_object(
                {
                    "job_id": sfn.JsonPath.string_at("$.job_id"),
                    "stage": stage,
                    "task_token": sfn.JsonPath.task_token,
                }
            ),
        )


def _label(stage: str) -> str:
    return "".join(part.capitalize() for part in stage.split("_"))
