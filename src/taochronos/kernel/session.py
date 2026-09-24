"""Durable research sessions: emit, transactions, recovery, fork and replay."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from ..protocol.events import Event, EventType
from ..protocol.research import ResearchObject
from .reducer import Reducer
from .store import EventStore


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class RecoveryReport:
    session_id: str
    events_read: int
    discarded_events: int
    discarded_transactions: list[str] = field(default_factory=list)
    checkpoints_verified: int = 0
    checkpoint_mismatches: list[int] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.discarded_events and not self.checkpoint_mismatches


class Transaction:
    """Buffers the domain events of one agent task and commits them atomically.

    A crash before :meth:`commit` leaves no partial writes on the blackboard;
    the task is simply re-run on resume.
    """

    def __init__(self, session: "Session", tx_id: str, actor: str, task_id: str | None) -> None:
        self.session = session
        self.id = tx_id
        self.actor = actor
        self.task_id = task_id
        self.pending: list[Event] = []
        self.pending_ids: set[str] = set()
        self.closed = False

    def emit(
        self,
        type: EventType | str,
        payload: dict[str, Any] | None = None,
        *,
        actor: str | None = None,
        used: Iterable[str] = (),
        generated: Iterable[str] = (),
    ) -> Event:
        if self.closed:
            raise RuntimeError(f"transaction {self.id} is closed")
        event = Event(
            session_id=self.session.id,
            seq=0,
            type=type.value if isinstance(type, EventType) else type,
            actor=actor or self.actor,
            payload=payload or {},
            task_id=self.task_id,
            tx=self.id,
            used=list(used),
            generated=list(generated),
        )
        with self.session.lock:
            self.session.reducer.validate(self.session.state, event, self.pending_ids)
        self.pending.append(event)
        self.pending_ids.update(event.generated)
        return event

    def commit(self) -> list[Event]:
        if self.closed:
            raise RuntimeError(f"transaction {self.id} is closed")
        self.closed = True
        return self.session._commit(self)

    def abort(self) -> None:
        self.closed = True
        self.pending.clear()


class Session:
    def __init__(
        self,
        session_id: str,
        store: EventStore,
        reducer: Reducer | None = None,
        clock: Callable[[], str] = utc_now,
    ) -> None:
        self.id = session_id
        self.store = store
        self.reducer = reducer or Reducer()
        self.clock = clock
        self.state = ResearchObject(session_id=session_id)
        self.seq = 0
        self.lock = threading.RLock()
        self._listeners: list[Callable[[Event], None]] = []
        self._tx_counter = 0
        self.recovery: RecoveryReport | None = None

    # ---------------------------------------------------------------- factory
    @classmethod
    def create(cls, store: EventStore, session_id: str | None = None, **kw: Any) -> "Session":
        sid = session_id or f"ses_{uuid.uuid4().hex[:12]}"
        if store.last_seq(sid):
            raise ValueError(f"session {sid} already exists")
        return cls(sid, store, **kw)

    @classmethod
    def open(cls, store: EventStore, session_id: str, *, verify: bool = True, **kw: Any) -> "Session":
        session = cls(session_id, store, **kw)
        events = store.read(session_id)
        if not events:
            raise KeyError(f"no such session: {session_id}")
        kept, dropped, dropped_tx = _drop_uncommitted_tail(events)
        if dropped:
            store.truncate(session_id, kept[-1].seq if kept else 0)
        report = RecoveryReport(
            session_id=session_id, events_read=len(events), discarded_events=dropped, discarded_transactions=dropped_tx
        )
        for event in kept:
            if verify and event.type == EventType.CHECKPOINT_CREATED.value:
                report.checkpoints_verified += 1
                if event.payload.get("state_hash") != session.state.state_hash():
                    report.checkpoint_mismatches.append(event.seq)
            session.reducer.apply(session.state, event)
            session.seq = event.seq
            if event.tx:
                session._tx_counter += 1
        session.recovery = report
        return session

    # ------------------------------------------------------------------- emit
    def subscribe(self, listener: Callable[[Event], None]) -> None:
        self._listeners.append(listener)

    def _notify(self, events: list[Event]) -> None:
        for listener in list(self._listeners):
            for event in events:
                try:
                    listener(event)
                except Exception:  # observers must never break the harness
                    pass

    def emit(
        self,
        type: EventType | str,
        payload: dict[str, Any] | None = None,
        *,
        actor: str = "kernel",
        task_id: str | None = None,
        used: Iterable[str] = (),
        generated: Iterable[str] = (),
        parent_seq: int | None = None,
    ) -> Event:
        with self.lock:
            event = Event(
                session_id=self.id,
                seq=self.seq + 1,
                type=type.value if isinstance(type, EventType) else type,
                actor=actor,
                payload=payload or {},
                task_id=task_id,
                parent_seq=parent_seq,
                used=list(used),
                generated=list(generated),
                ts=self.clock(),
            )
            self.reducer.validate(self.state, event)
            self.store.append([event])
            self.reducer.apply(self.state, event)
            self.seq = event.seq
        self._notify([event])
        return event

    def transaction(self, actor: str, task_id: str | None = None) -> Transaction:
        with self.lock:
            self._tx_counter += 1
            tx_id = f"tx{self._tx_counter}:{task_id or 'adhoc'}"
        return Transaction(self, tx_id, actor, task_id)

    def _commit(self, tx: Transaction) -> list[Event]:
        with self.lock:
            batch: list[Event] = []
            seq = self.seq
            now = self.clock()
            for pending in tx.pending:
                seq += 1
                batch.append(pending.replace(seq=seq, ts=now))
            seq += 1
            batch.append(
                Event(
                    session_id=self.id,
                    seq=seq,
                    type=EventType.TRANSACTION_COMMITTED.value,
                    actor="kernel",
                    payload={"tx": tx.id, "count": len(tx.pending)},
                    task_id=tx.task_id,
                    tx=tx.id,
                    ts=now,
                )
            )
            self.store.append(batch)  # atomic batch; a crash here is recovered on open()
            for event in batch:
                self.reducer.apply(self.state, event)
            self.seq = seq
        self._notify(batch)
        return batch

    # ------------------------------------------------------------- durability
    def checkpoint(self) -> Event:
        with self.lock:
            state_hash = self.state.state_hash()
        return self.emit(EventType.CHECKPOINT_CREATED, {"state_hash": state_hash, "at_seq": self.seq})

    def events(self, from_seq: int = 1, to_seq: int | None = None) -> list[Event]:
        return self.store.read(self.id, from_seq, to_seq)

    def replay(self, to_seq: int | None = None) -> ResearchObject:
        return self.reducer.replay(self.id, self.store.read(self.id, 1, to_seq))

    def verify(self) -> dict[str, Any]:
        """Rebuild state from the log and compare with the live projection and all checkpoints."""
        rebuilt = ResearchObject(session_id=self.id)
        mismatches: list[int] = []
        checkpoints = 0
        for event in self.store.read(self.id):
            if event.type == EventType.CHECKPOINT_CREATED.value:
                checkpoints += 1
                if event.payload.get("state_hash") != rebuilt.state_hash():
                    mismatches.append(event.seq)
            self.reducer.apply(rebuilt, event)
        with self.lock:
            live = self.state.state_hash()
        return {
            "session_id": self.id,
            "events": self.seq,
            "checkpoints": checkpoints,
            "checkpoint_mismatches": mismatches,
            "replayed_hash": rebuilt.state_hash(),
            "live_hash": live,
            "consistent": not mismatches and rebuilt.state_hash() == live,
        }

    def fork(
        self,
        *,
        at_seq: int | None = None,
        new_session_id: str | None = None,
        purpose: str = "",
        hypothesis_id: str | None = None,
        record_in_parent: bool = True,
    ) -> "Session":
        """Branch the research: the child starts from a prefix of this session's log."""
        with self.lock:
            target = self.seq if at_seq is None else min(at_seq, self.seq)
            events = self.store.read(self.id, 1, target)
            kept, _, _ = _drop_uncommitted_tail(events)
            at = kept[-1].seq if kept else 0
            n = len(self.state.branches) + 1
        child_id = new_session_id or f"{self.id}.b{n}"
        if self.store.last_seq(child_id):
            raise ValueError(f"session {child_id} already exists")
        self.store.append([e.replace(session_id=child_id) for e in kept])
        child = Session.open(self.store, child_id, reducer=self.reducer, clock=self.clock)
        info = {"parent_session": self.id, "branch_id": child_id, "at_seq": at, "purpose": purpose}
        if hypothesis_id:
            info["hypothesis_id"] = hypothesis_id
        child.emit(EventType.BRANCH_FORKED, {**info, "role": "child"})
        if record_in_parent:
            self.emit(EventType.BRANCH_FORKED, {**info, "role": "parent"})
        return child


def _drop_uncommitted_tail(events: list[Event]) -> tuple[list[Event], int, list[str]]:
    """Drop trailing events that belong to a transaction without a commit marker."""
    committed = {e.payload.get("tx") for e in events if e.type == EventType.TRANSACTION_COMMITTED.value}
    cut = len(events)
    dropped_tx: list[str] = []
    while cut > 0 and events[cut - 1].tx and events[cut - 1].tx not in committed:
        if events[cut - 1].tx not in dropped_tx:
            dropped_tx.append(events[cut - 1].tx)  # type: ignore[arg-type]
        cut -= 1
    return events[:cut], len(events) - cut, dropped_tx
