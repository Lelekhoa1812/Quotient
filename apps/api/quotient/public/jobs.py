"""Motivation vs Logic

Motivation: An external app submits one recording, optionally with context, and
later reads the transcript or analysis it asked for. A finished result has to
survive an API task being replaced.
Logic: The board stores the job, signs uploads through the worker port, and
calls submit only after the upload is stored. Each read syncs the meeting.
The selected projection is kept on the job and, when ARTIFACTS_BUCKET is set,
written under integration/<key_id>/<job_id>.json.
"""

from __future__ import annotations

import json
import os
import secrets
from collections.abc import Mapping
from datetime import datetime, timezone

from quotient.public.disk import Disk, default_path
from quotient.public.project import parse_job, project_result
from quotient.worker.port import PortError

_TERMINAL = {"ready", "needs_review", "failed", "cancelled"}
_ORPHAN = "The analysis is no longer on this server."


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class JobBoard:
    def __init__(self, port: object, *, persist: object | None = None, poll_seconds: float = 0.25) -> None:
        self.port = port
        self.persist = persist
        self.poll_seconds = poll_seconds
        self._jobs: dict[str, dict] = {}
        if persist is not None:
            for job in persist.load():  # type: ignore[attr-defined]
                if isinstance(job, dict) and isinstance(job.get("job_id"), str):
                    self._jobs[job["job_id"]] = job

    def create(self, *, key_id: str, subject: str, body: dict) -> dict:
        spec = parse_job(body)
        idem = spec["idempotency_key"]
        if idem:
            existing = self._by_idempotency(key_id, idem)
            if existing is not None:
                return self.public(existing)
        job_id = secrets.token_hex(12)
        upload = None
        media = spec["media"]
        if "object_key" in media:
            object_key = media["object_key"]
        else:
            signer = getattr(self.port, "upload_target", None)
            if not callable(signer):
                raise PortError("unavailable", "Object storage is not configured.")
            target = signer(job_id, media["filename"], media["media_type"], media["byte_size"])
            if target is None:
                raise PortError("unavailable", "Object storage is not configured.")
            upload = _public_upload(target)
            object_key = str(target.get("object_key") or "")
        context_uploads = None
        batch = None
        if spec["files"]:
            prepared = self.port.prepare_context(subject, spec["files"])  # type: ignore[attr-defined]
            if not isinstance(prepared, dict) or not isinstance(prepared.get("batch_id"), str):
                raise PortError("unavailable", "Object storage is not configured.")
            batch = prepared["batch_id"]
            uploads = prepared.get("uploads") if isinstance(prepared.get("uploads"), list) else []
            context_uploads = [_public_upload(item) for item in uploads if isinstance(item, dict)]
        job = {
            "job_id": job_id,
            "key_id": key_id,
            "subject": subject,
            "status": "awaiting_upload",
            "outputs": spec["outputs"],
            "stream": spec["stream"],
            "meeting_id": None,
            "object_key": object_key,
            "issued_upload": upload is not None,
            "upload": upload,
            "context_uploads": context_uploads,
            "context_batch": batch,
            "purpose": spec["purpose"],
            "context_names": list(spec["names"]),
            "idempotency_key": idem,
            "failure_message": None,
            "progress_message": "Waiting for the recording to upload.",
            "updated_at": _now(),
            "result": None,
        }
        self._save(job)
        return self.public(job)

    def submit(self, job_id: str, subject: str) -> dict:
        job = self._owned(job_id, subject)
        if job is None:
            raise PortError("not_found", "Job not found.")
        if job.get("meeting_id") and job["status"] not in {"failed", "cancelled"}:
            return self.sync(job_id, subject)
        if job["issued_upload"]:
            checker = getattr(self.port, "uploaded_object", None)
            if not callable(checker):
                raise PortError("unavailable", "Object storage is not configured.")
            stored = checker(job["object_key"])
            size = stored.get("size") if isinstance(stored, dict) else None
            if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
                raise PortError("invalid", "The recording has not finished uploading.")
        extra = {}
        if job.get("context_batch"):
            extra["context_batch"] = job["context_batch"]
        if job.get("purpose"):
            extra["purpose"] = job["purpose"]
        meeting_id = self.port.submit(  # type: ignore[attr-defined]
            subject=subject,
            object_key=str(job["object_key"]),
            context_names=tuple(job.get("context_names") or ()),
            idempotency_key=job.get("idempotency_key"),
            **extra,
        )
        job["meeting_id"] = meeting_id
        job["status"] = "queued"
        job["progress_message"] = "Recording the meeting."
        job["updated_at"] = _now()
        self._save(job)
        return self.sync(job_id, subject)

    def sync(self, job_id: str, subject: str) -> dict:
        job = self._owned(job_id, subject)
        if job is None:
            raise PortError("not_found", "Job not found.")
        self._sync(job)
        return self.public(job)

    def cancel(self, job_id: str, subject: str) -> dict:
        job = self._owned(job_id, subject)
        if job is None:
            raise PortError("not_found", "Job not found.")
        if job["status"] in _TERMINAL:
            return self.public(job)
        meeting_id = job.get("meeting_id")
        if isinstance(meeting_id, str) and meeting_id:
            self.port.cancel(meeting_id, subject)  # type: ignore[attr-defined]
        job["status"] = "cancelled"
        job["progress_message"] = "Stopped before it finished."
        job["updated_at"] = _now()
        self._save(job)
        return self.public(job)

    def result(self, job_id: str, subject: str, kind: str) -> dict:
        job = self._owned(job_id, subject)
        if job is None:
            raise PortError("not_found", "Job not found.")
        self._sync(job)
        outputs = job.get("outputs") if isinstance(job.get("outputs"), dict) else {}
        if kind == "transcript" and not outputs.get("transcript"):
            raise PortError("not_found", "This job did not ask for a transcript.")
        if kind == "analysis" and not (outputs.get("analysis") or []):
            raise PortError("not_found", "This job did not ask for an analysis.")
        if job["status"] not in {"ready", "needs_review"}:
            raise PortError("conflict", _not_ready(kind, job["status"]))
        payload = job.get("result")
        if not isinstance(payload, dict) and self.persist is not None:
            loaded = self.persist.load_result(job)  # type: ignore[attr-defined]
            if isinstance(loaded, dict):
                payload = loaded
                job["result"] = loaded
        if not isinstance(payload, dict):
            raise PortError("conflict", _not_ready(kind, job["status"]))
        if kind == "transcript":
            return {
                "job_id": job_id,
                "meeting_id": payload.get("meeting_id"),
                "status": payload.get("status"),
                "transcript": payload.get("transcript") or {"audio": "", "video": ""},
            }
        return {
            "job_id": job_id,
            "meeting_id": payload.get("meeting_id"),
            "status": payload.get("status"),
            "analysis": payload.get("analysis") or {},
        }

    def fail_orphans(self) -> None:
        for job in list(self._jobs.values()):
            if job.get("status") not in {"queued", "working"}:
                continue
            meeting_id = job.get("meeting_id")
            raw = None
            if isinstance(meeting_id, str) and meeting_id:
                raw = self.port.meeting(meeting_id, job.get("subject") or "")  # type: ignore[attr-defined]
            if raw is None:
                job["status"] = "failed"
                job["failure_message"] = _ORPHAN
                job["progress_message"] = _ORPHAN
                job["updated_at"] = _now()
                self._save(job)

    def public(self, job: dict) -> dict:
        body = {
            "job_id": job["job_id"],
            "status": job["status"],
            "stream": job["stream"],
            "outputs": job.get("outputs") or {},
            "progress_message": job.get("progress_message") or "",
            "meeting_id": job.get("meeting_id"),
            "updated_at": job.get("updated_at"),
        }
        if job.get("failure_message"):
            body["failure_message"] = job["failure_message"]
        if job["status"] == "awaiting_upload":
            if job.get("upload"):
                body["upload"] = job["upload"]
            if job.get("context_uploads"):
                body["context_uploads"] = job["context_uploads"]
        if job.get("stream"):
            body["events_url"] = f"/v1/jobs/{job['job_id']}/events"
        return body

    def owned_row(self, job_id: str, subject: str) -> dict | None:
        job = self._owned(job_id, subject)
        return dict(job) if job is not None else None

    def _sync(self, job: dict) -> None:
        if job["status"] in _TERMINAL and isinstance(job.get("result"), dict):
            return
        if job["status"] in {"cancelled", "failed"} and not job.get("meeting_id"):
            return
        meeting_id = job.get("meeting_id")
        if not isinstance(meeting_id, str) or not meeting_id:
            return
        raw = self.port.meeting(meeting_id, job["subject"])  # type: ignore[attr-defined]
        if raw is None:
            if job["status"] in {"queued", "working"}:
                job["status"] = "failed"
                job["failure_message"] = _ORPHAN
                job["progress_message"] = _ORPHAN
                job["updated_at"] = _now()
                self._save(job)
            return
        from quotient.graph.gate import project_meeting

        projected = project_meeting(raw)
        message = projected.get("progress_message") if isinstance(projected.get("progress_message"), str) else ""
        status = projected.get("status")
        if message:
            job["progress_message"] = message
        if status in {"queued", "working"}:
            job["status"] = status
            job["updated_at"] = _now()
            self._save(job)
            return
        if status in {"ready", "needs_review"}:
            payload = project_result(raw, job.get("outputs") or {}, job_id=job["job_id"])
            job["status"] = status
            job["result"] = payload
            job["failure_message"] = None
            job["updated_at"] = _now()
            if self.persist is not None:
                self.persist.save_result(job, payload)  # type: ignore[attr-defined]
            self._save(job)
            return
        if status == "cancelled":
            job["status"] = "cancelled"
            job["progress_message"] = message or "Stopped before it finished."
        elif status == "failed":
            job["status"] = "failed"
            job["failure_message"] = projected.get("failure_message") or "Meeting failed."
            job["progress_message"] = job["failure_message"]
        job["updated_at"] = _now()
        self._save(job)

    def _owned(self, job_id: str, subject: str) -> dict | None:
        job = self._jobs.get(job_id)
        if job is None or job.get("subject") != subject:
            return None
        return job

    def _by_idempotency(self, key_id: str, idem: str) -> dict | None:
        matches = [
            job
            for job in self._jobs.values()
            if job.get("key_id") == key_id and job.get("idempotency_key") == idem and job.get("status") not in {"failed", "cancelled"}
        ]
        if not matches:
            return None
        matches.sort(key=lambda job: str(job.get("updated_at") or ""))
        return matches[-1]

    def _save(self, job: dict) -> None:
        self._jobs[job["job_id"]] = job
        if self.persist is not None:
            self.persist.save(job)  # type: ignore[attr-defined]


def _not_ready(kind: str, status: str) -> str:
    name = "transcript" if kind == "transcript" else "analysis"
    if status == "failed":
        return f"The {name} is not available because the job failed."
    if status == "cancelled":
        return f"The {name} is not available because the job was cancelled."
    return f"The {name} is not ready."


def _public_upload(target: dict) -> dict:
    return {
        "method": target.get("method") or "PUT",
        "url": target.get("upload_url") or target.get("url"),
        "headers": target.get("headers") if isinstance(target.get("headers"), dict) else {},
        "object_key": target.get("object_key"),
    }


class FileJobs:
    def __init__(self, disk: Disk) -> None:
        self.disk = disk

    def load(self) -> list[dict]:
        rows = self.disk.read().get("jobs") or []
        return [row for row in rows if isinstance(row, dict)]

    def save(self, job: dict) -> None:
        def mutate(document: dict) -> None:
            jobs = [row for row in document.get("jobs") or [] if isinstance(row, dict) and row.get("job_id") != job["job_id"]]
            jobs.append(job)
            document["jobs"] = jobs

        self.disk.update(mutate)

    def save_result(self, job: dict, payload: dict) -> None:
        del job, payload

    def load_result(self, job: dict) -> dict | None:
        stored = job.get("result")
        return stored if isinstance(stored, dict) else None


class ObjectJobs:
    """Job rows in the jobs table. The finished JSON goes to the artifacts bucket."""

    def __init__(self, table: str, bucket: str, client: object | None = None, objects: object | None = None) -> None:
        self.table = table
        self.bucket = bucket
        self._client = client
        self._objects = objects

    def load(self) -> list[dict]:
        try:
            client = self._dynamo()
            items: list[dict] = []
            start = None
            while True:
                kwargs: dict = {"TableName": self.table}
                if start:
                    kwargs["ExclusiveStartKey"] = start
                page = client.scan(**kwargs)
                for item in page.get("Items") or []:
                    parsed = _job_item(item)
                    if parsed is not None:
                        items.append(parsed)
                start = page.get("LastEvaluatedKey")
                if not start:
                    break
            return items
        except Exception as exc:
            print(f"integration jobs could not be loaded: {type(exc).__name__}", file=__import__("sys").stderr, flush=True)
            return []

    def save(self, job: dict) -> None:
        stored = {key: value for key, value in job.items() if key != "result"}
        self._dynamo().put_item(
            TableName=self.table,
            Item={"job_id": {"S": job["job_id"]}, "document": {"S": json.dumps(stored, separators=(",", ":"))}},
        )

    def save_result(self, job: dict, payload: dict) -> None:
        if not self.bucket:
            return
        key = f"integration/{job['key_id']}/{job['job_id']}.json"
        body = json.dumps(payload).encode("utf-8")
        self._s3().put_object(Bucket=self.bucket, Key=key, Body=body, ContentType="application/json")
        job["result_key"] = key

    def load_result(self, job: dict) -> dict | None:
        key = job.get("result_key")
        if not isinstance(key, str) or not key or not self.bucket:
            return None
        try:
            response = self._s3().get_object(Bucket=self.bucket, Key=key)
            raw = response["Body"].read()
            parsed = json.loads(raw)
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _dynamo(self):
        if self._client is not None:
            return self._client
        return _aws("dynamodb")

    def _s3(self):
        if self._objects is not None:
            return self._objects
        return _aws("s3")


def load_board(port: object, env: Mapping[str, str], disk: Disk | None, *, poll_seconds: float = 0.25) -> JobBoard:
    table = (env.get("JOBS_TABLE") or "").strip()
    bucket = (env.get("ARTIFACTS_BUCKET") or "").strip()
    if table:
        return JobBoard(port, persist=ObjectJobs(table, bucket), poll_seconds=poll_seconds)
    return JobBoard(port, persist=FileJobs(disk if disk is not None else Disk(default_path())), poll_seconds=poll_seconds)


def _job_item(item: dict) -> dict | None:
    document = item.get("document")
    text = document.get("S") if isinstance(document, dict) else None
    if not isinstance(text, str):
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _aws(service: str):
    import botocore.session
    from botocore.config import Config

    session = botocore.session.get_session()
    kwargs: dict = {
        "region_name": os.environ.get("AWS_REGION", "ap-southeast-2"),
        "config": Config(connect_timeout=5, read_timeout=30),
    }
    if service == "s3":
        endpoint = os.environ.get("QUOTIENT_S3_ENDPOINT_URL", "").strip()
        if endpoint:
            access = os.environ.get("QUOTIENT_S3_ACCESS_KEY_ID", "")
            secret = os.environ.get("QUOTIENT_S3_SECRET_ACCESS_KEY", "")
            kwargs.update(endpoint_url=endpoint, aws_access_key_id=access, aws_secret_access_key=secret)
    return session.create_client(service, **kwargs)
