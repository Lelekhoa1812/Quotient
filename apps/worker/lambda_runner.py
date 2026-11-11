"""AWS Lambda SQS worker handler for on-demand meeting processing."""

from __future__ import annotations

import json
import logging
import os
import sys

logger = logging.getLogger("quotient.worker.lambda")


def start_long_job(meeting_id: str, *, client=None) -> bool:
    """Hand the analysis to a one-off Fargate task, which has no time limit and stops when it is done.

    Returns False when this deployment has no such task configured, or the task could not be started; the caller
    then runs the analysis in this invocation instead.
    """
    task_definition = os.environ.get("LONG_JOB_TASK_DEFINITION_ARN", "").strip()
    cluster = os.environ.get("CLUSTER_ARN", "").strip()
    subnets = [item for item in os.environ.get("LONG_JOB_SUBNET_IDS", "").split(",") if item.strip()]
    group = os.environ.get("LONG_JOB_SECURITY_GROUP_ID", "").strip()
    if not (task_definition and cluster and subnets and group):
        return False
    try:
        if client is None:
            import boto3

            client = boto3.client("ecs")
        result = client.run_task(
            cluster=cluster,
            taskDefinition=task_definition,
            launchType="FARGATE",
            count=1,
            # No NAT gateway: the task is in a public subnet and needs its own address to reach the model APIs.
            networkConfiguration={"awsvpcConfiguration": {"subnets": subnets, "securityGroups": [group], "assignPublicIp": "ENABLED"}},
            overrides={
                "containerOverrides": [
                    {
                        "name": "Worker",
                        "command": ["python", "apps/worker/task_runner.py"],
                        "environment": [{"name": "MEETING_ID", "value": meeting_id}],
                    }
                ]
            },
            startedBy="quotient-long-job",
        )
    except Exception as exc:
        print(f"long-job start failed for meeting {meeting_id}: {type(exc).__name__}", file=sys.stderr, flush=True)
        return False
    if result.get("failures") or not result.get("tasks"):
        print(f"long-job start refused for meeting {meeting_id}: {str(result.get('failures'))[:200]}", file=sys.stderr, flush=True)
        return False
    return True


def handler(event: dict, context: object) -> dict:
    from quotient.worker.port import load_worker_port

    port = load_worker_port()
    records = event.get("Records") or []
    processed = 0

    for record in records:
        body_raw = record.get("body") or "{}"
        try:
            payload = json.loads(body_raw)
        except json.JSONDecodeError:
            payload = {"meeting_id": body_raw.strip()}

        meeting_id = payload.get("meeting_id")
        if not meeting_id:
            logger.warning("Record missing meeting_id: %s", body_raw)
            continue

        if start_long_job(str(meeting_id)):
            print(f"on-demand worker handed meeting {meeting_id} to a long-job task", file=sys.stderr, flush=True)
            processed += 1
            continue
        print(f"on-demand worker starting analysis for meeting {meeting_id}", file=sys.stderr, flush=True)
        try:
            port._analyze(meeting_id)
            processed += 1
            print(f"on-demand worker completed analysis for meeting {meeting_id}", file=sys.stderr, flush=True)
        except Exception as exc:
            print(f"on-demand worker failed for meeting {meeting_id}: {exc}", file=sys.stderr, flush=True)
            raise
        finally:
            # Bugs vs Fixes
            # Bug: The finished meeting row was only queued for a background S3
            # put. The handler returned and Lambda froze that thread, so the
            # API kept reading the queued copy from submit.
            # Fix: Drain the put before this invocation ends.
            flush = getattr(port, "flush_storage", None)
            if callable(flush):
                flush()

    return {"status": "ok", "processed": processed}
