"""Motivation vs Logic

Motivation: Streamable HTTP keeps a session so progress, task status, and
resource updates can reach the client on GET /mcp after the POST that created
them has finished.
Logic: Each session stores a bounded event buffer and a set of waiter queues.
Enqueue writes the buffer and every waiter. Replay walks ids greater than
Last-Event-ID. The session is bound to the auth subject captured at initialize.
"""

from __future__ import annotations

import asyncio
import secrets
import threading
from collections.abc import Iterator

from quotient.auth.context import AuthContext

_BUFFER = 200
# Bounded so repeated initialize calls cannot grow memory without limit; the oldest idle session goes first.
MAX_SESSIONS = 500


class Session:
    def __init__(self, session_id: str, auth: AuthContext) -> None:
        self.session_id = session_id
        self.auth = auth
        self.ready = False
        self.closed = False
        self.subscriptions: set[str] = set()
        self._buffer: list[tuple[int, dict]] = []
        self._next = 1
        self._waiters: list[asyncio.Queue] = []
        self._lock = threading.Lock()

    def enqueue(self, message: dict) -> int:
        with self._lock:
            event_id = self._next
            self._next += 1
            self._buffer.append((event_id, message))
            del self._buffer[:-_BUFFER]
            waiters = list(self._waiters)
        for waiter in waiters:
            try:
                waiter.put_nowait((event_id, message))
            except asyncio.QueueFull:
                continue
        return event_id

    def since(self, cursor: int) -> list[tuple[int, dict]]:
        with self._lock:
            return [(event_id, message) for event_id, message in self._buffer if event_id > cursor]

    def add_waiter(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=_BUFFER)
        with self._lock:
            self._waiters.append(queue)
        return queue

    def remove_waiter(self, queue: asyncio.Queue) -> None:
        with self._lock:
            if queue in self._waiters:
                self._waiters.remove(queue)

    def close(self) -> None:
        self.closed = True
        with self._lock:
            waiters = list(self._waiters)
        for waiter in waiters:
            try:
                waiter.put_nowait(None)
            except asyncio.QueueFull:
                continue


class SessionStore:
    def __init__(self) -> None:
        self._items: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(self, auth: AuthContext) -> Session:
        session = Session(secrets.token_urlsafe(32), auth)
        evicted: list[Session] = []
        with self._lock:
            self._items[session.session_id] = session
            while len(self._items) > MAX_SESSIONS:
                oldest = next(iter(self._items))
                evicted.append(self._items.pop(oldest))
        for old in evicted:
            old.close()
        return session

    def get(self, session_id: str | None) -> Session | None:
        if not session_id:
            return None
        with self._lock:
            session = self._items.get(session_id)
        if session is None or session.closed:
            return None
        return session

    def drop(self, session_id: str) -> bool:
        with self._lock:
            session = self._items.pop(session_id, None)
        if session is None:
            return False
        session.close()
        return True

    def for_subject(self, subject: str) -> Iterator[Session]:
        with self._lock:
            sessions = list(self._items.values())
        for session in sessions:
            if not session.closed and session.auth.subject == subject:
                yield session
