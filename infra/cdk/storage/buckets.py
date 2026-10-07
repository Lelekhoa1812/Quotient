# Motivation vs Logic
# Motivation: Keep media and derived artifacts private in Sydney, and move
# derivative objects to infrequent access after 30 days.
# Logic: Three buckets with Block Public Access, TLS-only policies, and
# bucket-owner-enforced ownership. Server access logs land in the logs bucket.
# Lifecycle: abort unfinished multipart uploads after 7 days; transition
# derivatives/ to STANDARD_IA at 30 days. A Bedrock service principal in this
# account may GetObject everywhere except the chart sandbox prefix, which is
# what Pegasus needs for S3 input. Downloads stay presigned: no public grant.

from aws_cdk import Duration, RemovalPolicy, aws_iam as iam, aws_s3 as s3
from constructs import Construct

from quotient.names import ACCOUNT, DERIVATIVES_PREFIX, PORTAL_ORIGIN, PREFIX, REGION, SANDBOX_PREFIX


class MeetingBuckets(Construct):
    def __init__(self, scope: Construct, construct_id: str) -> None:
        super().__init__(scope, construct_id)
        self.logs = s3.Bucket(
            self,
            "Logs",
            bucket_name=f"{PREFIX}-logs",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            object_ownership=s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
            versioned=False,
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.logs.add_lifecycle_rule(
            id="expire-access-logs",
            expiration=Duration.days(90),
        )
        self.media = self._data_bucket("Media", "media", logs_prefix="s3/media/")
        self.artifacts = self._data_bucket("Artifacts", "artifacts", logs_prefix="s3/artifacts/")
        self._allow_bedrock_read(self.media)
        self._allow_bedrock_read(self.artifacts)
        self._deny_bedrock_sandbox()

    def _data_bucket(self, construct_id: str, suffix: str, logs_prefix: str) -> s3.Bucket:
        bucket = s3.Bucket(
            self,
            construct_id,
            bucket_name=f"{PREFIX}-{suffix}",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            object_ownership=s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
            versioned=False,
            removal_policy=RemovalPolicy.RETAIN,
            cors=[
                s3.CorsRule(
                    allowed_methods=[
                        s3.HttpMethods.GET,
                        s3.HttpMethods.HEAD,
                        s3.HttpMethods.PUT,
                        s3.HttpMethods.POST,
                    ],
                    allowed_origins=[PORTAL_ORIGIN],
                    allowed_headers=["*"],
                    exposed_headers=["ETag"],
                    max_age=3600,
                )
            ],
            server_access_logs_bucket=self.logs,
            server_access_logs_prefix=logs_prefix,
        )
        bucket.add_lifecycle_rule(
            id="abort-incomplete-multipart",
            abort_incomplete_multipart_upload_after=Duration.days(7),
        )
        bucket.add_lifecycle_rule(
            id="derivatives-infrequent-access",
            prefix=DERIVATIVES_PREFIX,
            transitions=[
                s3.Transition(
                    storage_class=s3.StorageClass.INFREQUENT_ACCESS,
                    transition_after=Duration.days(30),
                )
            ],
        )
        return bucket

    def _allow_bedrock_read(self, bucket: s3.Bucket) -> None:
        bucket.add_to_resource_policy(
            iam.PolicyStatement(
                sid="BedrockReadForPegasus",
                principals=[iam.ServicePrincipal("bedrock.amazonaws.com")],
                actions=["s3:GetObject"],
                resources=[bucket.arn_for_objects("*")],
                conditions={
                    "StringEquals": {"aws:SourceAccount": ACCOUNT},
                    "ArnLike": {"aws:SourceArn": f"arn:aws:bedrock:{REGION}:{ACCOUNT}:*"},
                },
            )
        )

    def _deny_bedrock_sandbox(self) -> None:
        self.artifacts.add_to_resource_policy(
            iam.PolicyStatement(
                sid="DenyBedrockReadSandbox",
                effect=iam.Effect.DENY,
                principals=[iam.ServicePrincipal("bedrock.amazonaws.com")],
                actions=["s3:GetObject"],
                resources=[self.artifacts.arn_for_objects(f"{SANDBOX_PREFIX}*")],
            )
        )

