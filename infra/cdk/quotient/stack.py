# Motivation vs Logic
# Motivation: Synthesize one staging stack an operator can deploy in
# ap-southeast-2 without attaching Quotient to an Engine VPC.
# Logic: Compose network, data, auth, IAM, Fargate, the coarse DAG, and the
# billing alarms. Tag every resource Project=axion-meeting-staging so the
# budgets can filter this product. Pass the state machine ARN into the tasks
# after the machine exists. Emit identifiers only. No secret values.

from aws_cdk import CfnOutput, Fn, Stack, Tags
from constructs import Construct

from auth.pool import MeetingAuth
from compute.cluster import MeetingCompute
from identity.roles import TaskRoles
from network.vpc import MeetingVpc
from ops.alarms import BillingAlarms
from ops.logs import MeetingLogs
from quotient.names import PREFIX
from storage.buckets import MeetingBuckets
from storage.tables import MeetingTables
from workflow.machine import MeetingMachine
from workflow.queue import WorkQueue


class StagingStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        Tags.of(self).add("Project", PREFIX)
        Tags.of(self).add("Environment", "staging")

        network = MeetingVpc(self, "Network")
        groups = MeetingLogs(self, "Logs")
        buckets = MeetingBuckets(self, "Buckets")
        tables = MeetingTables(self, "Tables")
        queue = WorkQueue(self, "Queue")
        auth = MeetingAuth(self, "Auth")
        roles = TaskRoles(
            self,
            "Roles",
            tables=[tables.jobs, tables.checkpoints, tables.audit],
            media=buckets.media,
            artifacts=buckets.artifacts,
            partner_secret=auth.partner_secret,
        )
        compute = MeetingCompute(
            self,
            "Compute",
            network=network,
            groups=groups,
            buckets=buckets,
            tables=tables,
            work=queue.queue,
            roles=roles,
            auth=auth,
        )
        machine = MeetingMachine(self, "Workflow", queue=queue.queue, state_logs=groups.states)
        roles.grant_orchestration(machine=machine.machine, queue=queue.queue)
        compute.api_container.add_environment("STATE_MACHINE_ARN", machine.machine.state_machine_arn)
        compute.worker_container.add_environment("STATE_MACHINE_ARN", machine.machine.state_machine_arn)
        alarms = BillingAlarms(self, "Alarms", dlq=queue.dlq)

        self._outputs(network, buckets, tables, queue, auth, roles, compute, machine, alarms)

    def _outputs(self, network, buckets, tables, queue, auth, roles, compute, machine, alarms) -> None:
        vpc = network.vpc
        pairs = {
            "VpcId": vpc.vpc_id,
            "PublicSubnetIds": Fn.join(",", [subnet.subnet_id for subnet in vpc.public_subnets]),
            "PrivateSubnetIds": Fn.join(",", [subnet.subnet_id for subnet in vpc.private_subnets]),
            "AlbDnsName": compute.alb.load_balancer_dns_name,
            "McpResourceUrl": compute.mcp_resource_url,
            "CognitoUserPoolId": auth.pool.user_pool_id,
            "CognitoClientId": auth.client.user_pool_client_id,
            "CognitoDomain": auth.domain.base_url(),
            "MediaBucketName": buckets.media.bucket_name,
            "ArtifactsBucketName": buckets.artifacts.bucket_name,
            "LogsBucketName": buckets.logs.bucket_name,
            "JobsTableName": tables.jobs.table_name,
            "CheckpointsTableName": tables.checkpoints.table_name,
            "AuditTableName": tables.audit.table_name,
            "WorkQueueUrl": queue.queue.queue_url,
            "StateMachineArn": machine.machine.state_machine_arn,
            "ApiRoleArn": roles.api.role_arn,
            "WorkerRoleArn": roles.worker.role_arn,
            "SandboxRoleArn": roles.sandbox.role_arn,
            "ClusterName": compute.cluster.cluster_name,
            "ApiRepositoryUri": compute.api_repo.repository_uri,
            "WorkerRepositoryUri": compute.worker_repo.repository_uri,
            "SandboxTaskDefinitionArn": compute.sandbox_task.task_definition_arn,
            "BillingTopicArn": alarms.topic.topic_arn,
        }
        for name, value in pairs.items():
            CfnOutput(self, name, value=value)
