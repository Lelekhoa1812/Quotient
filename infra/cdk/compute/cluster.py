# Motivation vs Logic
# Motivation: Run Quotient as a 100% on-demand serverless architecture to achieve
# near-$0 idle costs while keeping fast, elastic response when active.
# Logic: ARM64 Lambda functions with Function URLs behind CloudFront.
# API and Web containers run with aws-lambda-adapter.
# The worker runs on-demand via SQS event source mapping with awslambdaric (up to 15 min).
# The ECS cluster and task definitions are retained solely for on-demand Fargate Spot
# fallback (RunTask) for chart sandbox and long-running batch jobs.
# Application Load Balancer and continuous ECS services are removed.

from aws_cdk import (
    Aws,
    Duration,
    Fn,
    RemovalPolicy,
    Size,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_ec2 as ec2,
    aws_ecr as ecr,
    aws_ecs as ecs,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_lambda_event_sources as lambda_event_sources,
    aws_s3 as s3,
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
    LLM_FALLBACK_PROFILE,
    LLM_PROFILE,
    PEGASUS_PROFILE,
    PREFIX,
    REGION,
    SANDBOX_PREFIX,
    SLM_PROFILE,
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

        # ECS Cluster retained at 0 cost for ephemeral RunTask (chart sandbox and long jobs)
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
            description="Chart sandbox tasks. IAM denies Bedrock and S3 writes outside the sandbox prefix.",
            allow_all_outbound=True,
        )

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

        # S3 CORS
        for bucket in (buckets.media, buckets.artifacts):
            bucket.add_cors_rule(
                allowed_methods=[s3.HttpMethods.GET, s3.HttpMethods.HEAD, s3.HttpMethods.PUT, s3.HttpMethods.POST],
                allowed_origins=["*"],
                allowed_headers=["*"],
                exposed_headers=["ETag"],
                max_age=3600,
            )

        # Sandbox Task Definition (for ephemeral chart generation via RunTask)
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

        # Worker Task Definition (retained for fallback long-running batch execution via RunTask)
        self.worker_task = ecs.FargateTaskDefinition(
            self,
            "WorkerTask",
            family=f"{PREFIX}-worker",
            cpu=2048,
            memory_limit_mib=4096,
            runtime_platform=_PLATFORM,
            execution_role=self.execution_role,
            task_role=roles.worker,
        )
        self.worker_container = self.worker_task.add_container(
            "Worker",
            image=ecs.ContainerImage.from_ecr_repository(self.worker_repo, IMAGE_TAG),
            logging=ecs.LogDrivers.aws_logs(stream_prefix="worker", log_group=groups.worker),
            environment=self._worker_environment(tables, buckets, work, vpc),
            essential=True,
        )

        roles.grant_sandbox_launch(
            cluster=self.cluster,
            sandbox_task=self.sandbox_task,
            execution_role=self.execution_role,
        )

        # Serverless API Lambda Function
        api_env = self._api_environment(auth, tables, buckets)
        api_env["QUOTIENT_PORTAL_TOKEN"] = self.portal_token.secret_value.unsafe_unwrap()
        api_env["PORT"] = "8080"
        api_env["AWS_LWA_PORT"] = "8080"
        api_env["AWS_LWA_READINESS_CHECK_PATH"] = "/health"
        api_env["WORK_QUEUE_URL"] = work.queue_url

        self.api_fn = lambda_.DockerImageFunction(
            self,
            "ApiFn",
            function_name=f"{PREFIX}-api",
            code=lambda_.DockerImageCode.from_ecr(self.api_repo, tag_or_digest=IMAGE_TAG),
            architecture=lambda_.Architecture.ARM_64,
            memory_size=2048,
            timeout=Duration.seconds(300),
            role=roles.api,
            environment=api_env,
            log_group=groups.api,
        )
        self.api_fn_url = self.api_fn.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
            invoke_mode=lambda_.InvokeMode.BUFFERED,
        )

        # Serverless Web (Portal) Lambda Function
        self.web_role = iam.Role(
            self,
            "WebRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            description="Quotient staging web Lambda execution role.",
        )
        self.web_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")
        )
        self.portal_token.grant_read(self.web_role)

        self.web_fn = lambda_.DockerImageFunction(
            self,
            "WebFn",
            function_name=f"{PREFIX}-web",
            code=lambda_.DockerImageCode.from_ecr(self.web_repo, tag_or_digest=IMAGE_TAG),
            architecture=lambda_.Architecture.ARM_64,
            memory_size=1024,
            timeout=Duration.seconds(60),
            role=self.web_role,
            environment={
                "HOSTNAME": "0.0.0.0",
                "PORT": "3000",
                "AWS_LWA_PORT": "3000",
                "QUOTIENT_ENVIRONMENT": "staging",
                "QUOTIENT_PORTAL_TOKEN": self.portal_token.secret_value.unsafe_unwrap(),
                "QUOTIENT_CLOUDFRONT_ORIGIN": "https://d13b140h08qjom.cloudfront.net",
                "QUOTIENT_CLOUDFRONT_MCP_URL": "https://d13b140h08qjom.cloudfront.net/mcp",
                "NEXT_PUBLIC_CLOUDFRONT_MCP_URL": "https://d13b140h08qjom.cloudfront.net/mcp",
                "QUOTIENT_API_ORIGIN": "https://d13b140h08qjom.cloudfront.net",
            },
            log_group=groups.web,
        )
        self.web_fn_url = self.web_fn.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
            invoke_mode=lambda_.InvokeMode.BUFFERED,
        )

        # Serverless SQS Worker Lambda Function (Primary on-demand executor)
        worker_env = self._worker_environment(tables, buckets, work, vpc)
        self.worker_fn = lambda_.DockerImageFunction(
            self,
            "WorkerFn",
            function_name=f"{PREFIX}-worker",
            code=lambda_.DockerImageCode.from_ecr(
                self.worker_repo,
                tag_or_digest=IMAGE_TAG,
                entrypoint=["/usr/local/bin/python", "-m", "awslambdaric"],
                cmd=["lambda_runner.handler"],
            ),
            architecture=lambda_.Architecture.ARM_64,
            memory_size=2048,
            ephemeral_storage_size=Size.gibibytes(2),
            timeout=Duration.minutes(15),
            role=roles.worker,
            environment=worker_env,
            log_group=groups.worker,
        )
        self.worker_fn.add_event_source(
            lambda_event_sources.SqsEventSource(
                work,
                batch_size=1,
                max_concurrency=10,
            )
        )

        # CloudFront Distribution pointing to Serverless Function URLs
        api_domain = Fn.select(2, Fn.split("/", self.api_fn_url.url))
        web_domain = Fn.select(2, Fn.split("/", self.web_fn_url.url))

        api_origin = origins.HttpOrigin(
            api_domain,
            protocol_policy=cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
        )
        web_origin = origins.HttpOrigin(
            web_domain,
            protocol_policy=cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
        )

        api_behavior = cloudfront.BehaviorOptions(
            origin=api_origin,
            viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
            cached_methods=cloudfront.CachedMethods.CACHE_GET_HEAD_OPTIONS,
            cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
            origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
        )

        self.distribution = cloudfront.Distribution(
            self,
            "Distribution",
            comment="Quotient Serverless HTTPS distribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=web_origin,
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                cached_methods=cloudfront.CachedMethods.CACHE_GET_HEAD_OPTIONS,
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
            ),
            additional_behaviors={
                "/health": api_behavior,
                "/.well-known": api_behavior,
                "/.well-known/*": api_behavior,
                "/v1": api_behavior,
                "/v1/*": api_behavior,
                "/mcp": api_behavior,
                "/mcp/*": api_behavior,
            },
        )
        self.cloudfront_domain = self.distribution.distribution_domain_name
        self.cloudfront_url = Fn.join("", ["https://", self.cloudfront_domain])
        self.cloudfront_mcp_url = Fn.join("", ["https://", self.cloudfront_domain, "/mcp"])
        self.public_origin = self.cloudfront_url
        self.mcp_resource_url = self.cloudfront_mcp_url

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
            "QUOTIENT_ENV": "staging",
            "QUOTIENT_ENVIRONMENT": "staging",
            "QUOTIENT_ROLE": "api",
            "QUOTIENT_MEDIA_BUCKET": buckets.media.bucket_name,
            "QUOTIENT_TRANSCRIPT_CACHE_DIR": "/tmp/quotient",
            "MCP_PROTOCOL_VERSION": "2025-11-25",
            "MCP_RESOURCE_URL": "https://d13b140h08qjom.cloudfront.net/mcp",
            "CLOUDFRONT_RESOURCE_URL": "https://d13b140h08qjom.cloudfront.net/mcp",
            "CLOUDFRONT_ORIGIN": "https://d13b140h08qjom.cloudfront.net",
            "ALB_ORIGIN": "https://d13b140h08qjom.cloudfront.net",
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
        return {
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
            "BEDROCK_PEGASUS_PROFILE": PEGASUS_PROFILE,
            "BEDROCK_LLM_PROFILE": LLM_PROFILE,
            "BEDROCK_SLM_PROFILE": SLM_PROFILE,
            "BEDROCK_LLM_FALLBACK_PROFILE": LLM_FALLBACK_PROFILE,
            "CLUSTER_ARN": self.cluster.cluster_arn,
            "SANDBOX_TASK_DEFINITION_ARN": self.sandbox_task.task_definition_arn,
            "SANDBOX_SECURITY_GROUP_ID": self.sandbox_sg.security_group_id,
            "SANDBOX_SUBNET_IDS": Fn.join(",", [subnet.subnet_id for subnet in vpc.public_subnets]),
        }
