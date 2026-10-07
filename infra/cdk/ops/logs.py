# Motivation vs Logic
# Motivation: Bound log retention so an idle staging API cannot grow an
# unbounded CloudWatch bill.
# Logic: Four log groups, each retained 30 days and destroyed with the stack.
# Application groups are written by the task execution role. The state-machine
# group is written by the Step Functions service role.

from aws_cdk import RemovalPolicy, aws_logs as logs
from constructs import Construct

from quotient.names import PREFIX


class MeetingLogs(Construct):
    def __init__(self, scope: Construct, construct_id: str) -> None:
        super().__init__(scope, construct_id)
        self.api = self._group("Api", "api")
        self.worker = self._group("Worker", "worker")
        self.sandbox = self._group("Sandbox", "sandbox")
        self.states = self._group("States", "states")

    def _group(self, construct_id: str, suffix: str) -> logs.LogGroup:
        return logs.LogGroup(
            self,
            construct_id,
            log_group_name=f"/{PREFIX}/{suffix}",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )
