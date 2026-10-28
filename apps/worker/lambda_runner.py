"""AWS Lambda SQS worker handler for on-demand meeting processing."""

from __future__ import annotations

import json
import logging
import os
import sys

logger = logging.getLogger("quotient.worker.lambda")


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
