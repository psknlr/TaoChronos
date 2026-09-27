"""Durable research sessions: identities, emit, transactions, recovery, fork and replay.

Three rules make the event log trustworthy:

1. **Every event is authorised by an identity object.**  The session resolves the principal of each event (kernel,
   validator, human, agent) from an :class:`Actor` it is handed, never from the text of an actor id; a bare string
   other than the kernel's own id is at most an agent.  The reducer then checks the event type against the authority
   table (:mod:`.authority`).
2. **A batch is validated in order, on the state as the batch leaves it.**  A transaction's events are validated and
   applied one after the other, so the second ``ResearchCreated`` of a batch sees the goal the first one set.  If any
   event fails, the live state is rebuilt from the log — nothing of the batch remains.
3. **Nothing reaches the log before it has been validated and applied.**  The batch is persisted only after every event
   in it passed; a rejected event is never written, so a session always reopens.

Agent code never holds the session itself: it gets a :class:`SessionView` bound to its own identity, whose state is a
read-only :class:`StateView`.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Callable, Iterable

from ..protocol.events import Event, EventType
from ..protocol.research import ResearchObject
from .authority import AGENT, KERNEL, PRINCIPALS, RANK
from .policy import Actor
from .reducer import InvalidEvent, Reducer
from .store import EventStore, SimulatedCrash


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


KERNEL_ACTOR = Actor.kernel()


@dataclass
class RecoveryReport:
    session_id: str
    events_read: int
    discarded_events: int
    discarded_transactions: list[str] = field(default_factory=list)
    checkpoints_verified: int = 0
    checkpoint_mismatches: list[int] = field(default_factory=list)
    rejected_events: list[int] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.discarded_events and not self.checkpoint_mismatches and not self.rejected_events


class StateView:
    """The research object as agent code sees it: containers are read-only views and nothing can be assigned.

    Objects inside it are ordinary Python objects; a mutation that bypasses the event log is caught when the engine
    compares the live state with a replay of the log at the end of every round (and the log wins)."""

    __slots__ = ("_state",)

    def __init__(self, state: ResearchObject) -> None:
        object.__setattr__(self, "_state", state)

    def __getattr__(self, name: str) -> Any:
        value = getattr(object.__getattribute__(self, "_state"), name)
        if isinstance(value, dict):
            return MappingProxyType(value)
        if isinstance(value, list):
            return tuple(value)
        return value

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError(f"the research state is read-only (tried to set {name!r}): emit an event instead")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("the research state is read-only: emit an event instead")

    def __repr__(self) -> str:
        return f"StateView({object.__getattribute__(self, '_state').session_id})"


class Transaction:
    """Buffers the domain events of one task and commits them atomically, under one identity.

    A crash before :meth:`commit` leaves no partial writes on the blackboard; the task is simply re-run on resume.
    Each :meth:`emit` is checked early against the committed state (quick feedback); :meth:`commit` validates the
    whole batch in order and is the check that counts.
    """

    def __init__(self, session: "Session", tx_id: str, identity: Actor, task_id: str | None) -> None:
        self.session = session
        self.id = tx_id
        self.identity = identity
        self.task_id = task_id
        self.pending: list[Event] = []
        self.pending_ids: set[str] = set()
        self.closed = False

    @property
    def actor(self) -> str:
        return self.identity.id

    def emit(
        self,
        type: EventType | str,
        payload: dict[str, Any] | None = None,
        *,
        actor: Actor | str | None = None,
        used: Iterable[str] = (),
        generated: Iterable[str] = (),
    ) -> Event:
        if self.closed:
            raise RuntimeError(f"transaction {self.id} is closed")
        identity = self.identity if actor is None else self.session.narrow(actor, self.identity)
        event = Event(
            session_id=self.session.id,
            seq=0,
            type=type.value if isinstance(type, EventType) else type,
            actor=identity.id,
            principal=identity.principal,
            payload=payload or {},
            task_id=self.task_id,
            tx=self.id,
            used=list(used),
            generated=list(generated),
        )
        with self.session.lock:
            self.session.reducer.validate(self.session.state, event, self.pending_ids, pending=self.pending)
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
        # identities seen in this session (for audit); authority always comes from the object handed to emit
        self.identities: dict[str, Actor] = {KERNEL_ACTOR.id: KERNEL_ACTOR}

    # ---------------------------------------------------------------- factory
    @classmethod
    def create(cls, store: EventStore, session_id: str | None = None, **kw: Any) -> "Session":
        sid = session_id or f"ses_{uuid.uuid4().hex[:12]}"
        if store.last_seq(sid):
            raise ValueError(f"session {sid} already exists")
        return cls(sid, store, **kw)

    @classmethod
    def open(cls, store: EventStore, session_id: str, *, verify: bool = True, repair: bool = False, **kw: Any) -> "Session":
        """Rebuild a session from its log.  A torn tail (a transaction without its commit marker) is discarded.  An
        event that no longer applies (a log written by an older version that persisted before validating) stops the
        replay; with ``repair=True`` the log is cut before it and the session opens without it."""
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
            try:
                session.reducer.apply(session.state, event)
            except InvalidEvent as exc:
                if not repair:
                    raise InvalidEvent(f"{exc} (event {event.seq}; reopen with repair=True to cut the log before it)") from exc
                report.rejected_events.extend(e.seq for e in kept if e.seq >= event.seq)
                store.truncate(session_id, event.seq - 1)
                rebuilt = cls(session_id, store, **kw)
                for e in store.read(session_id):
                    rebuilt.reducer.apply(rebuilt.state, e)
                    rebuilt.seq = e.seq
                session.state, session.seq = rebuilt.state, rebuilt.seq
                break
            session.seq = event.seq
            if event.tx:
                session._tx_counter += 1
        session.recovery = report
        return session

    # -------------------------------------------------------------- identity
    def resolve(self, actor: Actor | str | None) -> Actor:
        """The identity an event is emitted under.  An :class:`Actor` object carries its principal; a bare string is
        the kernel only if it is the kernel's own id, and otherwise at most an agent — ``"human:x"`` typed by anyone
        is not a human."""
        if actor is None:
            return KERNEL_ACTOR
        if isinstance(actor, Actor):
            if actor.principal not in PRINCIPALS:
                raise InvalidEvent(f"unknown principal {actor.principal!r} for {actor.id}")
            known = self.identities.get(actor.id)
            if known is not None and known.principal != actor.principal:
                raise InvalidEvent(f"identity {actor.id} is {known.principal} in this session, not {actor.principal}")
            self.identities.setdefault(actor.id, actor)
            return actor
        if actor == KERNEL_ACTOR.id:
            return KERNEL_ACTOR
        known = self.identities.get(actor)
        if known is not None and known.principal == AGENT:
            return known
        return Actor(id=actor, role="agent", principal=AGENT)

    def narrow(self, actor: Actor | str | None, within: Actor) -> Actor:
        """An identity for an event emitted inside ``within`` (a transaction or a session view): the same identity or
        one with less authority — never more."""
        if actor is None or actor == within.id or actor is within:
            return within
        identity = self.resolve(actor)
        if RANK[identity.principal] > RANK[within.principal]:
            raise InvalidEvent(f"{within.id} ({within.principal}) cannot emit as {identity.id} ({identity.principal})")
        return identity

    def view(self, identity: Actor) -> "SessionView":
        return SessionView(self, self.resolve(identity))

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
        actor: Actor | str | None = None,
        task_id: str | None = None,
        used: Iterable[str] = (),
        generated: Iterable[str] = (),
        parent_seq: int | None = None,
    ) -> Event:
        identity = self.resolve(actor)
        with self.lock:
            event = Event(
                session_id=self.id,
                seq=self.seq + 1,
                type=type.value if isinstance(type, EventType) else type,
                actor=identity.id,
                principal=identity.principal,
                payload=payload or {},
                task_id=task_id,
                parent_seq=parent_seq,
                used=list(used),
                generated=list(generated),
                ts=self.clock(),
            )
            self._apply_all([event])
            self._persist([event])
            self.seq = event.seq
        self._notify([event])
        return event

    def transaction(self, actor: Actor | str | None, task_id: str | None = None) -> Transaction:
        identity = self.resolve(actor)
        with self.lock:
            self._tx_counter += 1
            tx_id = f"tx{self._tx_counter}:{task_id or 'adhoc'}"
        return Transaction(self, tx_id, identity, task_id)

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
                    actor=KERNEL_ACTOR.id,
                    principal=KERNEL,
                    payload={"tx": tx.id, "count": len(tx.pending)},
                    task_id=tx.task_id,
                    tx=tx.id,
                    ts=now,
                )
            )
            self._apply_all(batch)
            self._persist(batch)  # atomic batch; a crash here is recovered on open()
            self.seq = seq
        self._notify(batch)
        return batch

    def _apply_all(self, batch: list[Event]) -> None:
        """Validate and apply each event on the state the previous ones left; on any failure, rebuild the live state
        from the log (so no part of the batch remains) and re-raise."""
        try:
            for event in batch:
                self.reducer.validate(self.state, event)
                self.reducer.apply(self.state, event)
        except BaseException:
            self.restore()
            raise

    def _persist(self, batch: list[Event]) -> None:
        try:
            self.store.append(batch)
        except SimulatedCrash:
            raise  # the process is gone; open() recovers from what reached the store
        except BaseException:
            self.restore(truncate=True)
            raise

    def restore(self, *, truncate: bool = False) -> None:
        """Rebuild the live state from the log, in place (every reference to ``self.state`` stays valid)."""
        with self.lock:
            events = self.store.read(self.id)
            kept, dropped, _ = _drop_uncommitted_tail(events)
            if dropped and truncate:
                self.store.truncate(self.id, kept[-1].seq if kept else 0)
            rebuilt = ResearchObject(session_id=self.id)
            for event in kept:
                self.reducer.apply(rebuilt, event)
            self.state.__dict__.update(rebuilt.__dict__)
            self.seq = kept[-1].seq if kept else 0

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
        child.identities.update(self.identities)
        info = {"parent_session": self.id, "branch_id": child_id, "at_seq": at, "purpose": purpose}
        if hypothesis_id:
            info["hypothesis_id"] = hypothesis_id
        child.emit(EventType.BRANCH_FORKED, {**info, "role": "child"})
        if record_in_parent:
            self.emit(EventType.BRANCH_FORKED, {**info, "role": "parent"})
        return child


class SessionView:
    """The session as agent code and its tools see it: the state read-only, events and transactions only under the
    view's own identity (or a lesser one).  The kernel's session is never reachable from here by design."""

    __slots__ = ("_session", "_identity", "_state")

    def __init__(self, session: Session, identity: Actor) -> None:
        self._session = session
        self._identity = identity
        self._state = StateView(session.state)

    @property
    def id(self) -> str:
        return self._session.id

    @property
    def seq(self) -> int:
        return self._session.seq

    @property
    def identity(self) -> Actor:
        return self._identity

    @property
    def state(self) -> StateView:
        return self._state

    def emit(
        self,
        type: EventType | str,
        payload: dict[str, Any] | None = None,
        *,
        actor: Actor | str | None = None,
        task_id: str | None = None,
        used: Iterable[str] = (),
        generated: Iterable[str] = (),
        parent_seq: int | None = None,
    ) -> Event:
        identity = self._session.narrow(actor, self._identity)
        return self._session.emit(type, payload, actor=identity, task_id=task_id, used=used, generated=generated,
                                  parent_seq=parent_seq)

    def transaction(self, actor: Actor | str | None = None, task_id: str | None = None) -> Transaction:
        return self._session.transaction(self._session.narrow(actor, self._identity), task_id)

    def events(self, from_seq: int = 1, to_seq: int | None = None) -> list[Event]:
        return self._session.events(from_seq, to_seq)


def kernel_session(session: Session | SessionView) -> Session:
    """The session behind a view — for kernel code (the runtime) acting on behalf of an agent."""
    return session._session if isinstance(session, SessionView) else session


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
