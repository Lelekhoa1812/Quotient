# Motivation vs Logic
# Motivation: Split data-plane credentials so the chart sandbox cannot call
# Bedrock or write outside its prefix, and so model invokes stay on the locked
# profiles. The meeting loop still runs inside the API process, so the API
# role needs those same invokes or every recording fails at the first model call.
# Logic: Three ECS task roles. Tokyo InvokeModel and
# InvokeModelWithBidirectionalStream exist only on
# amazon.nova-2-5-sonic. Sydney InvokeModel and InvokeModelWithResponseStream
# cover the Pegasus profile, the Haiku profile, the Haiku fallback, and the
# foundation-model ARNs those profiles require. An explicit deny blocks every
# other Tokyo foundation-model invoke.
# API and worker are denied writes under artifacts/sandbox/. The sandbox role
# allows object I/O only on that prefix and denies bedrock, DynamoDB, Step
# Functions, SQS, and Secrets Manager. SendTask* remains resource "*" because
# those actions do not support resource-level permissions.

from aws_cdk import Stack, aws_dynamodb as dynamodb, aws_ecs as ecs, aws_iam as iam
from aws_cdk import aws_s3 as s3, aws_secretsmanager as secretsmanager, aws_sqs as sqs
from aws_cdk import aws_stepfunctions as sfn
from constructs import Construct

from quotient.names import (
    PREFIX,
    SANDBOX_PREFIX,
    SONIC_REGION,
    global_foundation_arns,
    sydney_profile_arns,
    tokyo_sonic_arn,
)

_SANDBOX_OBJECT_ACTIONS = [
    "s3:GetObject",
    "s3:PutObject",
    "s3:AbortMultipartUpload",
    "s3:ListMultipartUploadParts",
    "s3:CreateMultipartUpload",
    "s3:CompleteMultipartUpload",
    "s3:UploadPart",
]

_OBJECT_WRITES = [
    "s3:PutObject",
    "s3:DeleteObject",
    "s3:DeleteObjectVersion",
    "s3:AbortMultipartUpload",
    "s3:PutObjectAcl",
    "s3:PutObjectTagging",
    "s3:CreateMultipartUpload",
    "s3:UploadPart",
    "s3:CompleteMultipartUpload",
]


class TaskRoles(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        tables: list[dynamodb.ITable],
        media: s3.IBucket,
        artifacts: s3.IBucket,
        partner_secret: secretsmanager.ISecret,
    ) -> None:
        super().__init__(scope, construct_id)
        self.api = self._role("Api", "api")
        self.worker = self._role("Worker", "worker")
        self.sandbox = self._role("Sandbox", "sandbox")
        self._deny_bedrock(self.sandbox)
        for table in tables:
            table.grant_read_write_data(self.api)
            table.grant_read_write_data(self.worker)
        for bucket in (media, artifacts):
            bucket.grant_read_write(self.api)
            bucket.grant_read_write(self.worker)
        sandbox_objects = artifacts.arn_for_objects(f"{SANDBOX_PREFIX}*")
        for role in (self.api, self.worker):
            role.add_to_policy(
                iam.PolicyStatement(
                    sid="DenySandboxPrefixWrite",
                    effect=iam.Effect.DENY,
                    actions=_OBJECT_WRITES,
                    resources=[sandbox_objects],
                )
            )
        partner_secret.grant_read(self.api)
        self._grant_models(self.api)
        self._grant_models(self.worker)
        self._sandbox_prefix(sandbox_objects)
        self._sandbox_data_plane_deny()

    def grant_orchestration(self, *, machine: sfn.IStateMachine, queue: sqs.IQueue) -> None:
        machine.grant_start_execution(self.api)
        machine.grant_read(self.api)
        machine.grant_execution(self.api, "states:StopExecution")
        machine.grant_read(self.worker)
        machine.grant_task_response(self.worker)
        # SendTaskSuccess, SendTaskFailure, and SendTaskHeartbeat do not
        # support resource-level permissions. The grant above records the
        # state machine ARN; this statement is the one IAM will honor.
        self.worker.add_to_policy(
            iam.PolicyStatement(
                sid="HeartbeatTaskToken",
                actions=[
                    "states:SendTaskSuccess",
                    "states:SendTaskFailure",
                    "states:SendTaskHeartbeat",
                ],
                resources=["*"],
            )
        )
        # Bugs vs Fixes
        # Bug: The API enqueues each meeting with sqs:SendMessage, but only the
        # worker could consume the queue. SendMessage was denied, so analysis
        # fell back into the API process and ffprobe timed out there.
        # Fix: Let the API send to the work queue. The worker still consumes it.
        queue.grant_send_messages(self.api)
        queue.grant_consume_messages(self.worker)

    def grant_sandbox_launch(
        self,
        *,
        cluster: ecs.ICluster,
        sandbox_task: ecs.ITaskDefinition,
        execution_role: iam.IRole,
    ) -> None:
        self.worker.add_to_policy(
            iam.PolicyStatement(
                sid="RunSandboxTask",
                actions=["ecs:RunTask"],
                resources=[sandbox_task.task_definition_arn],
                conditions={"ArnEquals": {"ecs:cluster": cluster.cluster_arn}},
            )
        )
        self.worker.add_to_policy(
            iam.PolicyStatement(
                sid="DescribeSandboxTasks",
                actions=["ecs:DescribeTasks", "ecs:StopTask"],
                resources=[
                    self._task_wildcard(cluster),
                ],
            )
        )
        self.worker.add_to_policy(
            iam.PolicyStatement(
                sid="PassSandboxRoles",
                actions=["iam:PassRole"],
                resources=[self.sandbox.role_arn, execution_role.role_arn],
                conditions={"StringEquals": {"iam:PassedToService": "ecs-tasks.amazonaws.com"}},
            )
        )

    def _role(self, construct_id: str, suffix: str) -> iam.Role:
        role = iam.Role(
            self,
            construct_id,
            role_name=f"{PREFIX}-{suffix}",
            assumed_by=iam.CompositePrincipal(
                iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
                iam.ServicePrincipal("lambda.amazonaws.com"),
            ),
            description=f"Quotient staging {suffix} task role.",
        )
        role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")
        )
        return role

    def _deny_bedrock(self, role: iam.Role) -> None:
        role.add_to_policy(
            iam.PolicyStatement(
                sid="DenyBedrock",
                effect=iam.Effect.DENY,
                actions=["bedrock:*"],
                resources=["*"],
            )
        )

    def _grant_models(self, role: iam.Role) -> None:
        sonic = tokyo_sonic_arn()
        role.add_to_policy(
            iam.PolicyStatement(
                sid="TokyoSonicOnly",
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithBidirectionalStream",
                ],
                resources=[sonic],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                sid="SydneyGlobalProfiles",
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                ],
                resources=[*sydney_profile_arns(), *global_foundation_arns()],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                sid="DenyTokyoExceptSonic",
                effect=iam.Effect.DENY,
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock:InvokeModelWithBidirectionalStream",
                ],
                not_resources=[sonic],
                conditions={"StringEquals": {"aws:RequestedRegion": SONIC_REGION}},
            )
        )

    def _sandbox_prefix(self, sandbox_objects: str) -> None:
        self.sandbox.add_to_policy(
            iam.PolicyStatement(
                sid="SandboxPrefixObjectIo",
                actions=_SANDBOX_OBJECT_ACTIONS,
                resources=[sandbox_objects],
            )
        )
        self.sandbox.add_to_policy(
            iam.PolicyStatement(
                sid="DenyS3OutsideSandboxPrefix",
                effect=iam.Effect.DENY,
                actions=["s3:*"],
                not_resources=[sandbox_objects],
            )
        )

    def _sandbox_data_plane_deny(self) -> None:
        self.sandbox.add_to_policy(
            iam.PolicyStatement(
                sid="DenySandboxControlPlane",
                effect=iam.Effect.DENY,
                actions=[
                    "dynamodb:*",
                    "states:*",
                    "sqs:*",
                    "secretsmanager:*",
                ],
                resources=["*"],
            )
        )

    def _task_wildcard(self, cluster: ecs.ICluster) -> str:
        return Stack.of(self).format_arn(
            service="ecs",
            resource="task",
            resource_name=f"{cluster.cluster_name}/*",
        )
