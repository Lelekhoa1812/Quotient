# Motivation vs Logic
# Motivation: Run the MCP API at a floor of one task and keep workers at zero
# until the stage queue has depth. Chart code runs as a separate task.
# The meeting loop still runs inside the API process, so 0.25 vCPU and 0.5 GB
# exhausts memory on a real recording. 1 vCPU and 2 GB is the smallest Fargate
# size that can hold ffmpeg plus an in-process analysis.
# Logic: ARM64 Fargate in private subnets behind one public ALB. DesiredCount
# is removed from the service resources so CloudFormation does not wait for a
# healthy image during the first deploy and does not reset a live worker on
# update. Application Auto Scaling owns the counts: API min 1 max 2 on CPU,
# worker min 0 max 10 at exact queue depth (visible + in flight). The sandbox
# task is not a service. Its image is the worker image; the worker must pass
# the sandbox task role at RunTask. On-demand Fargate, not Spot.

from aws_cdk import (
    Aws,
    Duration,
    Fn,
    RemovalPolicy,
    aws_applicationautoscaling as appscaling,
    aws_cloudwatch as cloudwatch,
    aws_ec2 as ec2,
    aws_ecr as ecr,
    aws_ecs as ecs,
    aws_elasticloadbalancingv2 as elbv2,
    aws_s3 as s3,
    aws_iam as iam,
    aws_secretsmanager as secretsmanager,
    aws_sqs as sqs,
)
from constructs import Construct

from auth.pool import MeetingAuth
from identity.roles import TaskRoles
from network.vpc import MeetingVpc
from ops.logs import MeetingLogs
from quotient.names import (
    API_PORT,
    WEB_PORT,
    DERIVATIVES_PREFIX,
    GLOBAL_PROFILES,
    IMAGE_TAG,
    PREFIX,
    REGION,
    SANDBOX_PREFIX,
    SONIC_MODEL_ID,
    SONIC_REGION,
)
from storage.buckets import MeetingBuckets
from storage.tables import MeetingTables

_PLATFORM = ecs.RuntimePlatform(
    cpu_architecture=ecs.CpuArchitecture.ARM64,
    operating_system_family=ecs.OperatingSystemFamily.LINUX,
)


class MeetingCompute(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        network: MeetingVpc,
        groups: MeetingLogs,
        buckets: MeetingBuckets,
        tables: MeetingTables,
        work: sqs.IQueue,
        roles: TaskRoles,
        auth: MeetingAuth,
    ) -> None:
        super().__init__(scope, construct_id)
        vpc = network.vpc
        self.execution_role = self._execution_role(groups)
        self.api_repo = self._repo("ApiRepo", "api")
        self.web_repo = self._repo("WebRepo", "web")
        self.worker_repo = self._repo("WorkerRepo", "worker")
        self.api_repo.grant_pull(self.execution_role)
        self.web_repo.grant_pull(self.execution_role)
        self.worker_repo.grant_pull(self.execution_role)
        log_groups = (groups.api, groups.web, groups.worker, groups.sandbox)
        for group in log_groups:
            group.grant_write(self.execution_role)
        self.execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="TaskLogStreams",
                actions=["logs:CreateLogStream", "logs:PutLogEvents"],
                resources=[f"{group.log_group_arn}:*" for group in log_groups],
            )
        )

        # Bugs vs Fixes
        # Bug: enable_fargate_capacity_providers leaves FARGATE associated, and
        # CloudFormation cannot delete the cluster (ResourceInUseException).
        # Fix: Launch type FARGATE is on-demand without a capacity-provider
        # association, so rollback and delete can remove the cluster.
        self.cluster = ecs.Cluster(
            self,
            "Cluster",
            vpc=vpc,
            cluster_name=PREFIX,
            container_insights_v2=ecs.ContainerInsights.DISABLED,
        )
        self.api_sg = ec2.SecurityGroup(self, "ApiSg", vpc=vpc, description="Quotient API tasks.", allow_all_outbound=True)
        self.worker_sg = ec2.SecurityGroup(
            self,
            "WorkerSg",
            vpc=vpc,
            description="Quotient worker tasks. No inbound.",
            allow_all_outbound=True,
        )
        self.sandbox_sg = ec2.SecurityGroup(
            self,
            "SandboxSg",
            vpc=vpc,
            description="Chart sandbox tasks. IAM denies Bedrock and S3 writes outside the sandbox prefix. Egress stays open so Fargate can pull the image.",
            allow_all_outbound=True,
        )

        # Motivation vs Logic
        # Motivation: A streamed analysis stays connected for a long recording.
        # Logic: Raise the idle timeout to the load balancer maximum. The event
        # stream also sends a comment every 15 seconds.
        self.alb = elbv2.ApplicationLoadBalancer(
            self,
            "Alb",
            vpc=vpc,
            internet_facing=True,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            load_balancer_name=PREFIX,
            drop_invalid_header_fields=True,
            http2_enabled=True,
            idle_timeout=Duration.seconds(4000),
        )
        self.alb.log_access_logs(buckets.logs, "alb")
        self.mcp_resource_url = Fn.join("", ["http://", self.alb.load_balancer_dns_name, "/mcp"])
        self.public_origin = Fn.join("", ["http://", self.alb.load_balancer_dns_name])
        # Motivation vs Logic
        # Motivation: Settings on the load balancer has to mint the integration
        # key. The API refuses every peer that is not loopback.
        # Logic: One generated token is injected into the portal and the API.
        # The portal sends it as X-Quotient-Portal. The browser never sees it.
        self.portal_token = secretsmanager.Secret(
            self,
            "PortalToken",
            secret_name=f"{PREFIX}/portal",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                exclude_punctuation=True,
                password_length=48,
            ),
        )
        self.portal_token.grant_read(self.execution_role)

        api_task = ecs.FargateTaskDefinition(
            self,
            "ApiTask",
            family=f"{PREFIX}-api",
            cpu=1024,
            memory_limit_mib=2048,
            runtime_platform=_PLATFORM,
            execution_role=self.execution_role,
            task_role=roles.api,
        )
        self.api_container = api_task.add_container(
            "Api",
            image=ecs.ContainerImage.from_ecr_repository(self.api_repo, IMAGE_TAG),
            logging=ecs.LogDrivers.aws_logs(stream_prefix="api", log_group=groups.api),
            environment=self._api_environment(auth, tables, buckets),
            secrets={"QUOTIENT_PORTAL_TOKEN": ecs.Secret.from_secrets_manager(self.portal_token)},
            port_mappings=[ecs.PortMapping(container_port=API_PORT, protocol=ecs.Protocol.TCP)],
            essential=True,
        )
        self.api_service = ecs.FargateService(
            self,
            "ApiService",
            service_name=f"{PREFIX}-api",
            cluster=self.cluster,
            task_definition=api_task,
            desired_count=1,
            min_healthy_percent=100,
            max_healthy_percent=200,
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            assign_public_ip=False,
            security_groups=[self.api_sg],
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            health_check_grace_period=Duration.seconds(120),
            propagate_tags=ecs.PropagatedTagSource.SERVICE,
            enable_ecs_managed_tags=True,
            enable_execute_command=False,
            availability_zone_rebalancing=ecs.AvailabilityZoneRebalancing.DISABLED,
        )
        # Motivation vs Logic
        # Motivation: A browser opening the load balancer asks for /. The API
        # has no page there, so Starlette answers "Not Found".
        # Logic: The portal is the default target, including a browser GET of
        # /mcp. Protocol /mcp (Accept includes text/event-stream), /health,
        # /v1, and the OAuth metadata paths stay on the API. No circuit
        # breaker on the portal service: the first task cannot start until
        # the image exists, and a breaker would roll the whole stack back.
        self.web_sg = ec2.SecurityGroup(self, "WebSg", vpc=vpc, description="Quotient portal tasks.", allow_all_outbound=True)
        # The load balancer name is only known after the bucket exists, and
        # the bucket policy already depends on the load balancer's log bucket.
        # A hostname pattern avoids that cycle. Presigned URLs remain the
        # credential; CORS only lets the browser send them.
        for bucket in (buckets.media, buckets.artifacts):
            bucket.add_cors_rule(
                allowed_methods=[s3.HttpMethods.GET, s3.HttpMethods.HEAD, s3.HttpMethods.PUT, s3.HttpMethods.POST],
                allowed_origins=["http://*.elb.amazonaws.com"],
                allowed_headers=["*"],
                exposed_headers=["ETag"],
                max_age=3600,
            )
        web_task = ecs.FargateTaskDefinition(
            self,
            "WebTask",
            family=f"{PREFIX}-web",
            cpu=512,
            memory_limit_mib=1024,
            runtime_platform=_PLATFORM,
            execution_role=self.execution_role,
        )
        web_task.add_container(
            "Web",
            image=ecs.ContainerImage.from_ecr_repository(self.web_repo, IMAGE_TAG),
            logging=ecs.LogDrivers.aws_logs(stream_prefix="web", log_group=groups.web),
            environment={
                "HOSTNAME": "0.0.0.0",
                "PORT": str(WEB_PORT),
                "QUOTIENT_ENVIRONMENT": "staging",
                "QUOTIENT_API_ORIGIN": self.public_origin,
                "QUOTIENT_MCP_URL": self.mcp_resource_url,
            },
            secrets={"QUOTIENT_PORTAL_TOKEN": ecs.Secret.from_secrets_manager(self.portal_token)},
            port_mappings=[ecs.PortMapping(container_port=WEB_PORT, protocol=ecs.Protocol.TCP)],
            essential=True,
        )
        self.web_service = ecs.FargateService(
            self,
            "WebService",
            service_name=f"{PREFIX}-web",
            cluster=self.cluster,
            task_definition=web_task,
            desired_count=1,
            min_healthy_percent=0,
            max_healthy_percent=200,
            assign_public_ip=False,
            security_groups=[self.web_sg],
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            health_check_grace_period=Duration.seconds(180),
            propagate_tags=ecs.PropagatedTagSource.SERVICE,
            enable_ecs_managed_tags=True,
            enable_execute_command=False,
            availability_zone_rebalancing=ecs.AvailabilityZoneRebalancing.DISABLED,
        )
        listener = self.alb.add_listener("Http", port=80, open=True, protocol=elbv2.ApplicationProtocol.HTTP)
        api_targets = listener.add_targets(
            "Api",
            priority=10,
            conditions=[
                elbv2.ListenerCondition.path_patterns(["/health", "/.well-known", "/.well-known/*", "/v1", "/v1/*"]),
            ],
            port=API_PORT,
            protocol=elbv2.ApplicationProtocol.HTTP,
            targets=[self.api_service],
            deregistration_delay=Duration.seconds(30),
            health_check=elbv2.HealthCheck(
                path="/health",
                healthy_http_codes="200",
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
                healthy_threshold_count=2,
                unhealthy_threshold_count=3,
            ),
        )
        listener.add_action(
            "McpProtocol",
            priority=15,
            conditions=[
                elbv2.ListenerCondition.path_patterns(["/mcp"]),
                elbv2.ListenerCondition.http_header("Accept", ["*text/event-stream*"]),
            ],
            action=elbv2.ListenerAction.forward([api_targets]),
        )
        listener.add_targets(
            "Portal",
            port=WEB_PORT,
            protocol=elbv2.ApplicationProtocol.HTTP,
            targets=[self.web_service],
            deregistration_delay=Duration.seconds(30),
            health_check=elbv2.HealthCheck(
                path="/",
                healthy_http_codes="200",
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
                healthy_threshold_count=2,
                unhealthy_threshold_count=3,
            ),
        )
        # Bugs vs Fixes
        # Bug: CPU scale-out started a second API task. The meeting lives in
        # the first process, so a poll that landed on the new task marked the
        # job failed ("no longer on this server") while analysis was still
        # running.
        # Fix: Keep a single API task. A second task does not share that
        # memory, and the worker service is what scales with the queue.
        api_scale = self.api_service.auto_scale_task_count(min_capacity=1, max_capacity=1)
        api_scale.scale_on_cpu_utilization(
            "Cpu",
            target_utilization_percent=70,
            scale_in_cooldown=Duration.minutes(5),
            scale_out_cooldown=Duration.minutes(1),
        )

        self.sandbox_task = ecs.FargateTaskDefinition(
            self,
            "SandboxTask",
            family=f"{PREFIX}-sandbox",
            cpu=1024,
            memory_limit_mib=2048,
            runtime_platform=_PLATFORM,
            execution_role=self.execution_role,
            task_role=roles.sandbox,
        )
        self.sandbox_task.add_container(
            "Sandbox",
            image=ecs.ContainerImage.from_ecr_repository(self.worker_repo, IMAGE_TAG),
            logging=ecs.LogDrivers.aws_logs(stream_prefix="sandbox", log_group=groups.sandbox),
            environment={
                "AWS_REGION": REGION,
                "AWS_DEFAULT_REGION": REGION,
                "QUOTIENT_ROLE": "sandbox",
                "ARTIFACTS_BUCKET": buckets.artifacts.bucket_name,
                "SANDBOX_PREFIX": SANDBOX_PREFIX,
            },
            essential=True,
        )

        worker_task = ecs.FargateTaskDefinition(
            self,
            "WorkerTask",
            family=f"{PREFIX}-worker",
            cpu=2048,
            memory_limit_mib=4096,
            runtime_platform=_PLATFORM,
            execution_role=self.execution_role,
            task_role=roles.worker,
        )
        self.worker_container = worker_task.add_container(
            "Worker",
            image=ecs.ContainerImage.from_ecr_repository(self.worker_repo, IMAGE_TAG),
            logging=ecs.LogDrivers.aws_logs(stream_prefix="worker", log_group=groups.worker),
            environment=self._worker_environment(tables, buckets, work, vpc),
            essential=True,
        )
        self.worker_service = ecs.FargateService(
            self,
            "WorkerService",
            service_name=f"{PREFIX}-worker",
            cluster=self.cluster,
            task_definition=worker_task,
            desired_count=0,
            min_healthy_percent=0,
            max_healthy_percent=100,
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            assign_public_ip=False,
            security_groups=[self.worker_sg],
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            propagate_tags=ecs.PropagatedTagSource.SERVICE,
            enable_ecs_managed_tags=True,
            enable_execute_command=False,
            availability_zone_rebalancing=ecs.AvailabilityZoneRebalancing.DISABLED,
        )
        self._scale_workers(work)
        _release_desired_count(self.api_service)
        _release_desired_count(self.worker_service)
        roles.grant_sandbox_launch(
            cluster=self.cluster,
            sandbox_task=self.sandbox_task,
            execution_role=self.execution_role,
        )

    def _execution_role(self, groups: MeetingLogs) -> iam.Role:
        del groups
        role = iam.Role(
            self,
            "Execution",
            role_name=f"{PREFIX}-exec",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            description="Quotient staging execution role. Pulls images and writes logs.",
        )
        role.add_to_policy(
            iam.PolicyStatement(
                sid="EcrAuth",
                actions=["ecr:GetAuthorizationToken"],
                resources=["*"],
            )
        )
        return role

    def _repo(self, construct_id: str, suffix: str) -> ecr.Repository:
        return ecr.Repository(
            self,
            construct_id,
            repository_name=f"{PREFIX}-{suffix}",
            image_scan_on_push=True,
            image_tag_mutability=ecr.TagMutability.MUTABLE,
            removal_policy=RemovalPolicy.RETAIN,
            encryption=ecr.RepositoryEncryption.AES_256,
            lifecycle_rules=[ecr.LifecycleRule(max_image_count=10, description="Keep the last 10 images")],
        )

    def _api_environment(self, auth: MeetingAuth, tables: MeetingTables, buckets: MeetingBuckets) -> dict[str, str]:
        issuer = Fn.join(
            "",
            ["https://cognito-idp.", Aws.REGION, ".amazonaws.com/", auth.pool.user_pool_id],
        )
        return {
            "AWS_REGION": REGION,
            "AWS_DEFAULT_REGION": REGION,
            "QUOTIENT_ENV": "staging",
            "QUOTIENT_ENVIRONMENT": "staging",
            "QUOTIENT_ROLE": "api",
            "QUOTIENT_MEDIA_BUCKET": buckets.media.bucket_name,
            "QUOTIENT_TRANSCRIPT_CACHE_DIR": "/tmp/quotient",
            "PORT": str(API_PORT),
            "MCP_PROTOCOL_VERSION": "2025-11-25",
            "MCP_RESOURCE_URL": self.mcp_resource_url,
            "COGNITO_ISSUER": issuer,
            "COGNITO_CLIENT_ID": auth.client.user_pool_client_id,
            "COGNITO_DOMAIN": auth.domain.base_url(),
            "COGNITO_SCOPE": auth.oauth_scope,
            "JOBS_TABLE": tables.jobs.table_name,
            "KEYS_TABLE": tables.keys.table_name,
            "CHECKPOINTS_TABLE": tables.checkpoints.table_name,
            "AUDIT_TABLE": tables.audit.table_name,
            "MEDIA_BUCKET": buckets.media.bucket_name,
            "ARTIFACTS_BUCKET": buckets.artifacts.bucket_name,
            "DERIVATIVES_PREFIX": DERIVATIVES_PREFIX,
            "SANDBOX_PREFIX": SANDBOX_PREFIX,
            "PARTNER_SECRET_ARN": auth.partner_secret.secret_arn,
        }

    def _worker_environment(
        self,
        tables: MeetingTables,
        buckets: MeetingBuckets,
        work: sqs.IQueue,
        vpc: ec2.IVpc,
    ) -> dict[str, str]:
        pegasus, llm, slm, fallback = GLOBAL_PROFILES
        return {
            "AWS_REGION": REGION,
            "AWS_DEFAULT_REGION": REGION,
            "QUOTIENT_ENV": "staging",
            "QUOTIENT_ENVIRONMENT": "staging",
            "QUOTIENT_ROLE": "worker",
            "QUOTIENT_MEDIA_BUCKET": buckets.media.bucket_name,
            "QUOTIENT_TRANSCRIPT_CACHE_DIR": "/tmp/quotient",
            "JOBS_TABLE": tables.jobs.table_name,
            "CHECKPOINTS_TABLE": tables.checkpoints.table_name,
            "AUDIT_TABLE": tables.audit.table_name,
            "MEDIA_BUCKET": buckets.media.bucket_name,
            "ARTIFACTS_BUCKET": buckets.artifacts.bucket_name,
            "DERIVATIVES_PREFIX": DERIVATIVES_PREFIX,
            "SANDBOX_PREFIX": SANDBOX_PREFIX,
            "WORK_QUEUE_URL": work.queue_url,
            "BEDROCK_REGION": REGION,
            "BEDROCK_SONIC_MODEL_ID": SONIC_MODEL_ID,
            "BEDROCK_SONIC_REGION": SONIC_REGION,
            "BEDROCK_PEGASUS_PROFILE": pegasus,
            "BEDROCK_LLM_PROFILE": llm,
            "BEDROCK_SLM_PROFILE": slm,
            "BEDROCK_LLM_FALLBACK_PROFILE": fallback,
            "CLUSTER_ARN": self.cluster.cluster_arn,
            "SANDBOX_TASK_DEFINITION_ARN": self.sandbox_task.task_definition_arn,
            "SANDBOX_SECURITY_GROUP_ID": self.sandbox_sg.security_group_id,
            "SANDBOX_SUBNET_IDS": Fn.join(",", [subnet.subnet_id for subnet in vpc.private_subnets]),
        }

    def _scale_workers(self, work: sqs.IQueue) -> None:
        depth = cloudwatch.MathExpression(
            expression="FILL(visible, 0) + FILL(inflight, 0)",
            using_metrics={
                "visible": work.metric_approximate_number_of_messages_visible(
                    period=Duration.minutes(1),
                    statistic="Maximum",
                ),
                "inflight": work.metric_approximate_number_of_messages_not_visible(
                    period=Duration.minutes(1),
                    statistic="Maximum",
                ),
            },
            period=Duration.minutes(1),
            label="VisiblePlusInFlight",
        )
        scaling = self.worker_service.auto_scale_task_count(min_capacity=0, max_capacity=10)
        scaling.scale_on_metric(
            "QueueDepth",
            metric=depth,
            adjustment_type=appscaling.AdjustmentType.EXACT_CAPACITY,
            metric_aggregation_type=appscaling.MetricAggregationType.MAXIMUM,
            evaluation_periods=1,
            datapoints_to_alarm=1,
            cooldown=Duration.minutes(2),
            scaling_steps=[
                appscaling.ScalingInterval(upper=0, change=0),
                appscaling.ScalingInterval(lower=1, change=1),
                appscaling.ScalingInterval(lower=2, change=2),
                appscaling.ScalingInterval(lower=4, change=4),
                appscaling.ScalingInterval(lower=8, change=10),
            ],
        )


def _release_desired_count(service: ecs.FargateService) -> None:
    # Autoscaling owns the count. A pinned DesiredCount makes the first deploy
    # wait for a task that cannot start before the image exists, and a later
    # deploy would force workers back to the template value.
    service.node.default_child.add_property_deletion_override("DesiredCount")
