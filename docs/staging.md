# Quotient staging

Sydney stack for account `255834078973`, region `ap-southeast-2`, prefix `axion-meeting-staging`. The template is synthesized from `infra/cdk`. This pass does not deploy it.

The stack creates a new VPC `10.40.0.0/16`. It does not reference, peer with, or modify `10.30.0.0/16` or `10.20.0.0/16`.

## Deploy

From `infra/cdk`, with Python 3.12:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
npx --yes aws-cdk@2.1144.0 bootstrap aws://255834078973/ap-southeast-2
npx --yes aws-cdk@2.1144.0 deploy axion-meeting-staging --parameters AlarmEmail=operator@example.com
```

Replace `operator@example.com` with the inbox that should receive billing mail. `cdk synth` does not need the parameter. `cdk deploy` does. Confirm the SNS subscription email after deploy, or the alarms stay silent.

Library pin: `aws-cdk-lib==2.272.0` in `requirements.txt`. CLI pin: `aws-cdk@2.1144.0` (the CLI package is not published as `2.272.0`). Bootstrap once per account and region. The default security group restriction is a custom resource and uses the bootstrap bucket.

`cdk.context.json` caches the two availability zones chosen for this account. Keep that file so a later synth does not look up zones again.

A full 84-minute meeting is a manual start of the state machine. It is not part of deploy or CI. The budgeted live test is the 5-minute slice.

## Images

Both repositories are mutable and keep the last 10 images. The task definitions pull tag `staging`. Images must be `linux/arm64`.

| Repository | Image |
| --- | --- |
| `axion-meeting-staging-api` | API, port 8080, `GET /health` returns 200 |
| `axion-meeting-staging-worker` | Worker process and the chart sandbox task |

The repositories are created by this stack, so the first deploy cannot already contain those tags. Application Auto Scaling then asks for one API task. Until the image exists, that task cannot start and the load balancer has no healthy target. After the push, force a deployment:

```bash
aws ecr get-login-password --region ap-southeast-2 \
  | docker login --username AWS --password-stdin 255834078973.dkr.ecr.ap-southeast-2.amazonaws.com

docker buildx build --platform linux/arm64 \
  -t 255834078973.dkr.ecr.ap-southeast-2.amazonaws.com/axion-meeting-staging-api:staging --push apps/api

docker buildx build --platform linux/arm64 \
  -t 255834078973.dkr.ecr.ap-southeast-2.amazonaws.com/axion-meeting-staging-worker:staging --push apps/worker

aws ecs update-service --region ap-southeast-2 \
  --cluster axion-meeting-staging --service axion-meeting-staging-api \
  --desired-count 1 --force-new-deployment

aws ecs update-service --region ap-southeast-2 \
  --cluster axion-meeting-staging --service axion-meeting-staging-worker \
  --force-new-deployment
```

The worker service rests at 0 tasks. Force its deployment anyway after the push so the next scale-out resolves tag `staging`. ECS keeps the digest from the last deployment until a new deployment runs.

## Network

| Subnet | CIDR | Use |
| --- | --- | --- |
| public, AZ 1 | `10.40.0.0/24` | ALB, and the single NAT gateway |
| public, AZ 2 | `10.40.1.0/24` | ALB |
| private, AZ 1 | `10.40.2.0/24` | API, worker, chart sandbox |
| private, AZ 2 | `10.40.3.0/24` | API, worker, chart sandbox |

One NAT gateway, in the first public subnet. Private egress from the second AZ crosses availability zones. An S3 gateway endpoint is attached to the private route tables, so application object transfer does not go through the NAT. The endpoint policy is unrestricted because Fargate pulls image layers from AWS-owned S3 buckets through the same gateway. Task IAM limits which application buckets the credentials can use.

The ALB is internet-facing on port 80. This pass has no ACM certificate and no production hostname. `/health` is the target-group check and must not return meeting data.

## Compute

Cluster `axion-meeting-staging`. On-demand Fargate, ARM64, not Spot. Container Insights is off. Execute command is off. `DesiredCount` is omitted from the service resources so CloudFormation does not pin it; Application Auto Scaling owns the count.

| Service | vCPU | Memory | Count |
| --- | --- | --- | --- |
| API | 0.25 | 0.5 GB | minimum 1, maximum 2, target 70% CPU |
| Worker | 2 | 4 GB | minimum 0, maximum 10, exact queue depth |
| Chart sandbox | 1 | 2 GB | no service; `RunTask` only |

Worker depth is visible messages plus in-flight messages. At 0 the service scales to 0. At 1 it scales to 1, at 2 to 2, at 4 to 4, and at 8 or more to 10. Cooldown is 2 minutes.

The chart task uses the worker image and the sandbox task role. The worker launches it with `assignPublicIp` disabled, the sandbox security group, and the private subnets (`SANDBOX_SUBNET_IDS`). Fargate still needs egress to pull the image and to write logs, so that security group allows outbound traffic. Bedrock and foreign S3 writes are removed by the role, not by a closed security group.

## Data

On-demand DynamoDB, AWS-managed encryption, retained if the stack is deleted. Partition key `job_id` on all three. Checkpoints sort key `checkpoint_id`. Audit sort key `event_id`.

| Table | Name |
| --- | --- |
| Jobs | `axion-meeting-staging-jobs` |
| Checkpoints | `axion-meeting-staging-checkpoints` |
| Audit | `axion-meeting-staging-audit` |

S3, Block Public Access, TLS required, bucket-owner enforced, SSE-S3, retained on delete. No public read. The API role signs uploads and downloads; objects are not anonymous.

| Bucket | Name |
| --- | --- |
| Media | `axion-meeting-staging-media` |
| Artifacts | `axion-meeting-staging-artifacts` |
| Access logs | `axion-meeting-staging-logs` |

Server access logs for media and artifacts, and ALB access logs, go to the logs bucket and expire after 90 days. Unfinished multipart uploads abort after 7 days. Objects under `derivatives/` on media and artifacts move to Standard-Infrequent Access after 30 days. S3 does not transition objects smaller than 128 KB. Originals must not use the `derivatives/` prefix.

`sandbox/` on the artifacts bucket is the chart prefix. Bedrock may `GetObject` on media and artifacts for Pegasus input from this account in Sydney, and may not read `sandbox/`.

CORS allows `http://localhost:3000` so the portal can use presigned `PUT`, `POST`, and `GET`. `ETag` is exposed for multipart completion.

Partner OAuth material is the Secrets Manager secret `axion-meeting-staging/partner`. CloudFormation generates the value at deploy time. It is not in the template and not in this document. It is not written to DynamoDB. The API task receives `PARTNER_SECRET_ARN` only.

## Auth

Cognito user pool `axion-meeting-staging` is the OAuth 2.1 authorization server for the MCP resource. Self-service sign-up is off. An operator creates users. MFA is optional TOTP.

The portal client has no secret, so Cognito requires PKCE (`S256`) on the authorization-code grant. Callback `http://localhost:3000/callback`. Logout `http://localhost:3000/`. Scope `quotient/mcp`, plus `openid` and `email`.

Hosted UI domain prefix `axion-meeting-staging` (the prefix is global; if it is taken, change `PREFIX` before deploy):

- Authorize: `https://axion-meeting-staging.auth.ap-southeast-2.amazoncognito.com/oauth2/authorize`
- Token: `https://axion-meeting-staging.auth.ap-southeast-2.amazoncognito.com/oauth2/token`
- Issuer: `https://cognito-idp.ap-southeast-2.amazonaws.com/<user pool id>`

The RFC 8707 resource indicator is the MCP URL on the load balancer, `http://<alb-dns>/mcp`, passed to the API as `MCP_RESOURCE_URL`. The API publishes protected-resource metadata for protocol `2025-11-25` with that resource, the Cognito issuer as the authorization server, and scope `quotient/mcp`.

## Workflow

Standard state machine `axion-meeting-staging`. Input is `{"job_id":"<id>"}`. Each stage sends one SQS message and waits for the task token. Heartbeat timeout is 5 minutes. Each stage times out after 3 hours. The execution times out after 24 hours. Parallel results are discarded so the next state still has `job_id`. Error logs omit execution data.

Order: `media`, then `sonic` and `pegasus` together, then the ten council stages together (`decision`, `commitment`, `temporal`, `stakeholder`, `cross_modal`, `documentary`, `risk`, `gap`, `dependency`, `question`), then `exports`.

Message body:

```json
{"job_id": "<id>", "stage": "<stage>", "task_token": "<token>"}
```

The worker treats `job_id` plus `stage` as the idempotency key. A redelivery continues that stage. It does not open a second model session. The worker heartbeats Step Functions at least every minute and extends SQS visibility (5 minutes) on the same cadence. It deletes the message only after `SendTaskSuccess` or `SendTaskFailure`. The callback body is ids and a status. Transcript text in the callback is stored in execution history.

Queue `axion-meeting-staging-work`. Eight receives, then `axion-meeting-staging-dlq`, which alarms the billing topic.

## IAM

| Role | What it can do |
| --- | --- |
| `axion-meeting-staging-api` | Tables, presign on media and artifacts, start and stop executions, read the partner secret. Bedrock is denied. Writes under `sandbox/` are denied. |
| `axion-meeting-staging-worker` | Tables, media and artifacts, consume the queue, heartbeat a task token, run the sandbox task. |
| `axion-meeting-staging-sandbox` | Get and put objects under `artifacts/sandbox/` only. Bedrock, DynamoDB, Step Functions, SQS, and Secrets Manager are denied. Any other S3 action is denied. |
| `axion-meeting-staging-exec` | ECR pull for the two repositories, and log streams for the three task groups. |

Tokyo `bedrock:InvokeModel` and `bedrock:InvokeModelWithBidirectionalStream` are granted only for `arn:aws:bedrock:ap-northeast-1::foundation-model/amazon.nova-2-5-sonic`. Any other invoke whose requested region is `ap-northeast-1` is denied.

From Sydney the worker may invoke these global profiles, plus the foundation-model ARNs behind them:

- `global.twelvelabs.pegasus-1-2-v1:0`
- `global.openai.gpt-6.1-sol`
- `global.openai.gpt-6-luna`
- `global.openai.gpt-6-sol` (fallback only)

Those Sydney actions are `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream`.

## Budget

Two cost budgets notify the SNS topic `axion-meeting-staging-billing` when actual spend is over 100 percent. Both filter on cost-allocation tag `Project=axion-meeting-staging` (`user:Project$axion-meeting-staging`).

| Budget | Limit |
| --- | --- |
| `axion-meeting-staging-daily` | 25 USD per day |
| `axion-meeting-staging-monthly` | 200 USD per month |

Activate the `Project` tag as a cost allocation tag in the payer billing console. Until it is active, the filter matches nothing and the alarms do not see charges. Activation can take about a day. Bedrock invocation lines in this shared account may not inherit the task tag. After the first 5-minute slice, check Cost Explorer for that tag before treating the alarms as closed.

Idle staging is the NAT gateway, the public load balancer, one 0.25 vCPU API task, and empty on-demand tables. Using public list prices as a planning estimate, not a quote: NAT hourly charge is on the order of 45 USD per month, the load balancer on the order of 20 USD per month, and the API task on the order of 10 USD per month. Idle is on the order of 80 USD per month, under the monthly alarm, and a few dollars per day, under the daily alarm. Workers cost nothing while the queue is empty. A council fan-out can run up to 10 worker tasks of 2 vCPU and 4 GB. Bedrock token use is the spend the daily alarm is there to catch. The alarms do not change model output limits.

CloudWatch log groups `/axion-meeting-staging/{api,worker,sandbox,states}` retain events for 30 days.

## Retain

Deleting the stack retains the three buckets, three tables, user pool, partner secret, and both ECR repositories. Those names must be removed by hand before a recreate. Log groups, queues, the cluster, and the state machine are deleted with the stack.
