# Motivation vs Logic
# Motivation: A meeting uploaded from the portal has to reach the worker. The browser
# cannot write to the worker's disk, so it uploads straight to object storage with a
# short-lived signed PUT, and the worker reads the object back before analysis.
# Logic: One botocore client per call. With QUOTIENT_S3_ENDPOINT_URL set (local MinIO)
# it uses QUOTIENT_S3_* credentials only, so the developer's AWS identity is never
# replaced for Bedrock; without it, the default AWS credential chain. Upload keys live
# under uploads/<task_id>/ and are minted here, never taken from the client.

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

UPLOAD_PREFIX = "uploads/"
CONTEXT_PREFIX = "context/"
CONTEXT_MAX_FILES = 20
CONTEXT_MAX_FILE_BYTES = 25 * 1024**2
CONTEXT_MAX_TOTAL_BYTES = 100 * 1024**2
# What the converter can turn into Markdown without a model or the network. Images, audio, video and
# archives are refused on purpose: an image needs OCR or a vision model, and an archive can hide a bomb.
CONTEXT_EXTENSIONS = frozenset({
    ".pdf", ".docx", ".pptx", ".xlsx", ".xls", ".csv", ".json", ".xml", ".html", ".htm", ".md", ".markdown", ".txt", ".epub",
})
UPLOAD_URL_SECONDS = 900
MAX_UPLOAD_BYTES = 5 * 1024**3  # single signed PUT limit
_ALLOWED_TYPES = re.compile(r"^(audio|video)/[a-z0-9.+-]+$")
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class StorageUnavailable(RuntimeError):
    pass


def bucket_name() -> str:
    bucket = os.environ.get("QUOTIENT_MEDIA_BUCKET", "").strip()
    if bucket:
        return bucket
    if os.environ.get("QUOTIENT_ENVIRONMENT", "").strip().lower() == "local":
        return "axion-meeting-local"
    raise StorageUnavailable("QUOTIENT_MEDIA_BUCKET is not configured")


def _client():
    try:
        import botocore.session
        from botocore.config import Config
    except ImportError as exc:  # pragma: no cover - pinned in requirements.txt
        raise StorageUnavailable("botocore is not installed") from exc
    session = botocore.session.get_session()
    endpoint = os.environ.get("QUOTIENT_S3_ENDPOINT_URL", "").strip() or None
    kwargs: dict = {
        "region_name": os.environ.get("AWS_REGION", "ap-southeast-2"),
        "config": Config(signature_version="s3v4", s3={"addressing_style": "path"}, connect_timeout=5, read_timeout=60),
    }
    if endpoint:
        access = os.environ.get("QUOTIENT_S3_ACCESS_KEY_ID", "")
        secret = os.environ.get("QUOTIENT_S3_SECRET_ACCESS_KEY", "")
        if not access or not secret:
            raise StorageUnavailable("local S3 credentials are not configured")
        kwargs.update(endpoint_url=endpoint, aws_access_key_id=access, aws_secret_access_key=secret)
    return session.create_client("s3", **kwargs)


def safe_filename(name: str | None) -> str:
    base = Path(str(name or "")).name.strip()
    stem, dot, suffix = base.rpartition(".")
    if not dot:
        stem, suffix = base, ""
    clean_stem = _SAFE_NAME.sub("-", stem).strip(".-")[:110]
    clean_suffix = re.sub(r"[^A-Za-z0-9]", "", suffix)[:8]
    if not clean_stem:
        return "recording" + (f".{clean_suffix}" if clean_suffix else "")
    return clean_stem + (f".{clean_suffix}" if clean_suffix else "")


def upload_key(task_id: str, filename: str | None) -> str:
    task = re.sub(r"[^A-Za-z0-9_-]", "", task_id)[:64] or "task"
    return f"{UPLOAD_PREFIX}{task}/{safe_filename(filename)}"


def base_media_type(media_type: str | None) -> str:
    """The type without parameters: recorders send "video/webm;codecs=vp8,opus"."""
    return str(media_type or "").split(";", 1)[0].strip().lower()


def media_type_allowed(media_type: str | None) -> bool:
    return bool(_ALLOWED_TYPES.match(base_media_type(media_type)))


def presign_put(key: str, media_type: str) -> str:
    return _client().generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket_name(), "Key": key, "ContentType": media_type},
        ExpiresIn=UPLOAD_URL_SECONDS,
        HttpMethod="PUT",
    )


def head(key: str) -> dict | None:
    """Size and type of a stored object, or None when it does not exist."""
    try:
        reply = _client().head_object(Bucket=bucket_name(), Key=key)
    except Exception as exc:  # botocore ClientError and connection errors
        code = getattr(exc, "response", {}).get("Error", {}).get("Code") if hasattr(exc, "response") else None
        if code in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise StorageUnavailable("object storage could not be reached") from exc
    return {"size": int(reply.get("ContentLength") or 0), "content_type": str(reply.get("ContentType") or "")}


class TooLarge(FileNotFoundError):
    """The stored object is bigger than the caller allows."""


def download(key: str, directory: Path | None = None, max_bytes: int | None = None) -> Path:
    """Copy an uploaded object to a private temporary file and return its path.

    With max_bytes the copy stops as soon as it would exceed it: the size a head check reported can be
    out of date, because a signed upload URL stays valid for a while and can be used again."""
    target_dir = Path(directory or tempfile.mkdtemp(prefix="quotient-upload-"))
    target = target_dir / safe_filename(key.rsplit("/", 1)[-1])
    try:
        body = _client().get_object(Bucket=bucket_name(), Key=key)["Body"]
        written = 0
        with open(target, "wb") as handle:
            for chunk in iter(lambda: body.read(1024 * 1024), b""):
                written += len(chunk)
                if max_bytes is not None and written > max_bytes:
                    raise TooLarge("the stored object is larger than allowed")
                handle.write(chunk)
    except TooLarge:
        target.unlink(missing_ok=True)
        raise
    except Exception as exc:
        raise FileNotFoundError("the uploaded recording could not be read from storage") from exc
    if not target.is_file() or target.stat().st_size == 0:
        raise FileNotFoundError("the uploaded recording is empty")
    return target


def context_extension(filename: str | None) -> str:
    base = str(filename or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return "." + base.rsplit(".", 1)[-1].lower() if "." in base else ""


def context_allowed(filename: str | None) -> bool:
    return context_extension(filename) in CONTEXT_EXTENSIONS


def context_key(batch_id: str, index: int, filename: str | None) -> str:
    """context/<batch>/<n>-<safe name>: minted here, never taken from the client."""
    batch = re.sub(r"[^A-Za-z0-9_-]", "", batch_id)[:64] or "batch"
    return f"{CONTEXT_PREFIX}{batch}/{int(index):02d}-{safe_filename(filename)}"
