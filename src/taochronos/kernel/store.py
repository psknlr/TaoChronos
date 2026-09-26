"""Append-only event stores.

Every store appends a *batch* atomically from the reader's point of view:
readers either see the whole batch or detect a torn tail, which the session
discards on open (crash recovery).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from abc import ABC, abstractmethod
from pathlib import Path

from ..protocol.events import Event


class EventStore(ABC):
    @abstractmethod
    def append(self, events: list[Event]) -> None: ...

    @abstractmethod
    def read(self, session_id: str, from_seq: int = 1, to_seq: int | None = None) -> list[Event]: ...

    @abstractmethod
    def sessions(self) -> list[str]: ...

    @abstractmethod
    def truncate(self, session_id: str, keep_through_seq: int) -> None: ...

    def exists(self, session_id: str) -> bool:
        return session_id in self.sessions()

    def last_seq(self, session_id: str) -> int:
        events = self.read(session_id)
        return events[-1].seq if events else 0


class MemoryEventStore(EventStore):
    def __init__(self) -> None:
        self._events: dict[str, list[Event]] = {}
        self._lock = threading.Lock()

    def append(self, events: list[Event]) -> None:
        with self._lock:
            for ev in events:
                log = self._events.setdefault(ev.session_id, [])
                if log and ev.seq != log[-1].seq + 1:
                    raise ValueError(f"non-contiguous seq {ev.seq} after {log[-1].seq}")
                log.append(Event.from_dict(ev.to_dict()))

    def read(self, session_id: str, from_seq: int = 1, to_seq: int | None = None) -> list[Event]:
        with self._lock:
            log = self._events.get(session_id, [])
            return [
                Event.from_dict(e.to_dict()) for e in log if e.seq >= from_seq and (to_seq is None or e.seq <= to_seq)
            ]

    def sessions(self) -> list[str]:
        with self._lock:
            return sorted(self._events)

    def truncate(self, session_id: str, keep_through_seq: int) -> None:
        with self._lock:
            self._events[session_id] = [e for e in self._events.get(session_id, []) if e.seq <= keep_through_seq]


class JsonlEventStore(EventStore):
    """One ``events.jsonl`` per session. Torn trailing lines are ignored on read."""

    def __init__(self, root: str | Path, fsync: bool = True) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.fsync = fsync
        self._lock = threading.Lock()

    def _path(self, session_id: str) -> Path:
        return self.root / session_id / "events.jsonl"

    def append(self, events: list[Event]) -> None:
        if not events:
            return
        by_session: dict[str, list[Event]] = {}
        for ev in events:
            by_session.setdefault(ev.session_id, []).append(ev)
        with self._lock:
            for session_id, batch in by_session.items():
                path = self._path(session_id)
                path.parent.mkdir(parents=True, exist_ok=True)
                payload = "".join(json.dumps(e.to_dict(), ensure_ascii=False, sort_keys=True) + "\n" for e in batch)
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(payload)
                    fh.flush()
                    if self.fsync:
                        os.fsync(fh.fileno())

    def read(self, session_id: str, from_seq: int = 1, to_seq: int | None = None) -> list[Event]:
        path = self._path(session_id)
        if not path.exists():
            return []
        out: list[Event] = []
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if not line.endswith("\n"):
                    break  # torn write
                try:
                    ev = Event.from_dict(json.loads(line))
                except (json.JSONDecodeError, TypeError, KeyError):
                    break
                if ev.seq < from_seq:
                    continue
                if to_seq is not None and ev.seq > to_seq:
                    break
                out.append(ev)
        return out

    def sessions(self) -> list[str]:
        return sorted(p.parent.name for p in self.root.glob("*/events.jsonl"))

    def truncate(self, session_id: str, keep_through_seq: int) -> None:
        with self._lock:
            path = self._path(session_id)
            if not path.exists():
                return
            kept = [e for e in self.read(session_id) if e.seq <= keep_through_seq]
            tmp = path.with_suffix(".jsonl.tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                for e in kept:
                    fh.write(json.dumps(e.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
                fh.flush()
                if self.fsync:
                    os.fsync(fh.fileno())
            os.replace(tmp, path)


class SqliteEventStore(EventStore):
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS events ("
            " session_id TEXT NOT NULL, seq INTEGER NOT NULL, type TEXT NOT NULL,"
            " actor TEXT, task_id TEXT, tx TEXT, data TEXT NOT NULL,"
            " PRIMARY KEY (session_id, seq))"
        )
        self._lock = threading.Lock()

    def append(self, events: list[Event]) -> None:
        if not events:
            return
        rows = [
            (e.session_id, e.seq, e.type, e.actor, e.task_id, e.tx, json.dumps(e.to_dict(), ensure_ascii=False))
            for e in events
        ]
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                self._conn.executemany("INSERT INTO events VALUES (?,?,?,?,?,?,?)", rows)
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def read(self, session_id: str, from_seq: int = 1, to_seq: int | None = None) -> list[Event]:
        query = "SELECT data FROM events WHERE session_id=? AND seq>=?"
        params: list = [session_id, from_seq]
        if to_seq is not None:
            query += " AND seq<=?"
            params.append(to_seq)
        query += " ORDER BY seq"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [Event.from_dict(json.loads(r[0])) for r in rows]

    def sessions(self) -> list[str]:
        with self._lock:
            return [r[0] for r in self._conn.execute("SELECT DISTINCT session_id FROM events ORDER BY session_id")]

    def truncate(self, session_id: str, keep_through_seq: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM events WHERE session_id=? AND seq>?", (session_id, keep_through_seq))

    def last_seq(self, session_id: str) -> int:
        with self._lock:
            row = self._conn.execute("SELECT MAX(seq) FROM events WHERE session_id=?", (session_id,)).fetchone()
        return int(row[0] or 0)


class SimulatedCrash(RuntimeError):
    """Raised by :class:`FaultInjectingStore` to emulate a process dying mid-write."""


class FaultInjectingStore(EventStore):
    """Wraps a store and crashes during the N-th batch append (used by RecoveryEval).

    With ``torn=True`` only the first half of the crashing batch reaches the
    underlying store, which is exactly the state a power loss can leave behind.
    """

    def __init__(self, inner: EventStore, crash_on_batch: int, torn: bool = True, only_tx: bool = True) -> None:
        self.inner = inner
        self.crash_on_batch = crash_on_batch
        self.torn = torn
        self.only_tx = only_tx
        self.batches = 0
        self.crashed = False

    def append(self, events: list[Event]) -> None:
        if self.only_tx and not any(e.tx for e in events):
            self.inner.append(events)
            return
        self.batches += 1
        if not self.crashed and self.batches == self.crash_on_batch:
            self.crashed = True
            if self.torn and len(events) > 1:
                self.inner.append(events[: len(events) // 2])
            raise SimulatedCrash(f"simulated crash during batch {self.batches}")
        self.inner.append(events)

    def read(self, session_id: str, from_seq: int = 1, to_seq: int | None = None) -> list[Event]:
        return self.inner.read(session_id, from_seq, to_seq)

    def sessions(self) -> list[str]:
        return self.inner.sessions()

    def truncate(self, session_id: str, keep_through_seq: int) -> None:
        self.inner.truncate(session_id, keep_through_seq)

    def last_seq(self, session_id: str) -> int:
        return self.inner.last_seq(session_id)


def open_store(kind: str, location: str | Path | None = None) -> EventStore:
    if kind == "memory":
        return MemoryEventStore()
    if kind == "jsonl":
        return JsonlEventStore(location or ".taochronos/sessions")
    if kind == "sqlite":
        return SqliteEventStore(location or ".taochronos/events.sqlite")
    raise ValueError(f"unknown event store kind: {kind}")
