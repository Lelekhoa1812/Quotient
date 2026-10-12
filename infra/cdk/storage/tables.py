# Motivation vs Logic
# Motivation: Persist job state, turn checkpoints, the audit trail, and the
# integration key in Sydney without a provisioned-capacity floor.
# Logic: Jobs, checkpoints, and audit are keyed by job_id. The key table is
# keyed by key_id so a bearer token resolves in one read. Checkpoints and
# audit add a sort key. AWS-managed encryption. Retain on stack delete so a
# destroy does not drop the system of record.

from aws_cdk import RemovalPolicy, aws_dynamodb as dynamodb
from constructs import Construct

from quotient.names import PREFIX


class MeetingTables(Construct):
    def __init__(self, scope: Construct, construct_id: str) -> None:
        super().__init__(scope, construct_id)
        self.jobs = self._table("Jobs", "jobs", sort_key=None, partition="job_id")
        self.checkpoints = self._table("Checkpoints", "checkpoints", sort_key="checkpoint_id", partition="job_id")
        self.audit = self._table("Audit", "audit", sort_key="event_id", partition="job_id")
        self.keys = self._table("Keys", "keys", sort_key=None, partition="key_id")

    def _table(self, construct_id: str, suffix: str, sort_key: str | None, *, partition: str) -> dynamodb.Table:
        sort = None
        if sort_key is not None:
            sort = dynamodb.Attribute(name=sort_key, type=dynamodb.AttributeType.STRING)
        return dynamodb.Table(
            self,
            construct_id,
            table_name=f"{PREFIX}-{suffix}",
            partition_key=dynamodb.Attribute(name=partition, type=dynamodb.AttributeType.STRING),
            sort_key=sort,
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            removal_policy=RemovalPolicy.RETAIN,
        )
