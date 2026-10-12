"""Motivation vs Logic

Motivation: An external app needs one bearer key that never expires and can be
revoked. Settings has to show that same key again later.
Logic: One active row. The token is qnt_<id>_<secret> and is stored in full.
Verify compares the whole token. Revoke stamps revoked_at and later reads omit
the token. DynamoDB when KEYS_TABLE is set; otherwise the local JSON file.
"""

from __future__ import annotations

import hmac
import os
import secrets
import threading
from collections.abc import Callable, Mapping
from datetime import datetime, timezone

from quotient.public.disk import Disk, default_path


class KeyBusy(Exception):
    """An active key already exists."""


class KeyMissing(Exception):
    """There is no active key to revoke."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class KeyDirectory:
    """The one integration key. load and save exchange the full row list."""

    def __init__(self, load: Callable[[], list], save: Callable[[list], None], *, scope: str) -> None:
        self._load = load
        self._save = save
        self.scope = scope
        self._lock = threading.Lock()

    def issue(self) -> dict:
        with self._lock:
            rows = [dict(row) for row in self._load() if isinstance(row, dict)]
            if any(not row.get("revoked_at") for row in rows):
                raise KeyBusy()
            key_id = secrets.token_hex(8)
            token = f"qnt_{key_id}_{secrets.token_hex(16)}"
            row = {"key_id": key_id, "token": token, "created_at": _now(), "revoked_at": None}
            rows.append(row)
            self._save(rows)
            return dict(row)

    def revoke(self) -> dict:
        with self._lock:
            rows = [dict(row) for row in self._load() if isinstance(row, dict)]
            active = next((row for row in rows if not row.get("revoked_at")), None)
            if active is None:
                raise KeyMissing()
            active["revoked_at"] = _now()
            self._save(rows)
            return self._view(rows)

    def view(self) -> dict:
        with self._lock:
            rows = [row for row in self._load() if isinstance(row, dict)]
            return self._view(rows)

    def verify(self, token: str) -> tuple[str, str] | None:
        """Return (key_id, subject) for an active token."""

        if not isinstance(token, str) or not token.startswith("qnt_") or len(token) > 256:
            return None
        key_id, _, _secret = token[4:].partition("_")
        if not key_id or not _secret:
            return None
        with self._lock:
            rows = [row for row in self._load() if isinstance(row, dict)]
        row = next((item for item in rows if item.get("key_id") == key_id), None)
        if row is None or row.get("revoked_at"):
            return None
        stored = row.get("token")
        if not isinstance(stored, str) or not hmac.compare_digest(stored, token):
            return None
        return key_id, f"key:{key_id}"

    def _view(self, rows: list) -> dict:
        row = rows[-1] if rows else None
        if row is None or not isinstance(row.get("key_id"), str):
            return {"key": None, "scope": self.scope}
        public = {
            "key_id": row["key_id"],
            "created_at": row.get("created_at"),
            "revoked_at": row.get("revoked_at"),
        }
        if not row.get("revoked_at") and isinstance(row.get("token"), str):
            public["token"] = row["token"]
        return {"key": public, "scope": self.scope}


class MemoryDirectory(KeyDirectory):
    def __init__(self) -> None:
        self._rows: list[dict] = []
        super().__init__(self._read, self._write, scope="local")

    def _read(self) -> list:
        return [dict(row) for row in self._rows]

    def _write(self, rows: list) -> None:
        self._rows = [dict(row) for row in rows]


def file_directory(disk: Disk) -> KeyDirectory:
    def load() -> list:
        rows = disk.read().get("keys") or []
        return [row for row in rows if isinstance(row, dict)]

    def save(rows: list) -> None:
        disk.update(lambda document: document.__setitem__("keys", rows))

    return KeyDirectory(load, save, scope="local")


def dynamo_directory(table: str, client: object | None = None) -> KeyDirectory:
    backend = _Dynamo(table, client)

    def load() -> list:
        return backend.rows()

    def save(rows: list) -> None:
        backend.replace(rows)

    return KeyDirectory(load, save, scope="shared")


def load_directory(env: Mapping[str, str], disk: Disk | None) -> KeyDirectory:
    table = (env.get("KEYS_TABLE") or "").strip()
    if table:
        return dynamo_directory(table)
    return file_directory(disk if disk is not None else Disk(default_path()))


class _Dynamo:
    def __init__(self, table: str, client: object | None) -> None:
        self.table = table
        self._client = client

    def rows(self) -> list[dict]:
        client = self._client or _client()
        items: list[dict] = []
        start = None
        while True:
            kwargs = {"TableName": self.table}
            if start:
                kwargs["ExclusiveStartKey"] = start
            page = client.scan(**kwargs)  # type: ignore[attr-defined]
            for item in page.get("Items") or []:
                parsed = _row(item)
                if parsed is not None:
                    items.append(parsed)
            start = page.get("LastEvaluatedKey")
            if not start:
                break
        items.sort(key=lambda row: str(row.get("created_at") or ""))
        return items

    def replace(self, rows: list) -> None:
        """Write the latest rows. A handful of historical keys is the whole table."""

        client = self._client or _client()
        existing = {row["key_id"] for row in self.rows()}
        wanted = {row["key_id"] for row in rows if isinstance(row.get("key_id"), str)}
        for key_id in existing - wanted:
            client.delete_item(TableName=self.table, Key={"key_id": {"S": key_id}})  # type: ignore[attr-defined]
        for row in rows:
            client.put_item(TableName=self.table, Item=_item(row))  # type: ignore[attr-defined]


def _client():
    import botocore.session
    from botocore.config import Config

    session = botocore.session.get_session()
    return session.create_client(
        "dynamodb",
        region_name=os.environ.get("AWS_REGION", "ap-southeast-2"),
        config=Config(connect_timeout=5, read_timeout=10),
    )


def _item(row: dict) -> dict:
    item = {
        "key_id": {"S": str(row.get("key_id") or "")},
        "token": {"S": str(row.get("token") or "")},
        "created_at": {"S": str(row.get("created_at") or "")},
    }
    revoked = row.get("revoked_at")
    if isinstance(revoked, str) and revoked:
        item["revoked_at"] = {"S": revoked}
    return item


def _row(item: dict) -> dict | None:
    key_id = _string(item.get("key_id"))
    token = _string(item.get("token"))
    created = _string(item.get("created_at"))
    if not key_id or not token or not created:
        return None
    return {
        "key_id": key_id,
        "token": token,
        "created_at": created,
        "revoked_at": _string(item.get("revoked_at")),
    }


def _string(value: object) -> str | None:
    if isinstance(value, dict):
        text = value.get("S")
        if isinstance(text, str) and text:
            return text
    return None
