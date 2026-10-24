"""Research runs in the background, as a server starts them (``POST /api/research``): their records, their queue, and
the one worker that runs them.

A run's ``state``: ``queued`` until the worker takes it, then ``running``; asked to stop, ``cancel_requested`` until the
task it is running ends, then ``cancelled``; else it ends ``completed`` or ``failed``.  A run that was queued or running
when the server stopped is ``interrupted`` once the server is back, its record and its session's log kept: asked to
(:meth:`Jobs.resume`), it is queued again and goes on from its session's last checkpoint.  A run the server has no
record of is ``unknown``.  ``status`` keeps the words a page of an earlier version reads (queued, running, done, error).

One run at a time, first come first served, and a run waiting says how many are ahead of it.  A run puts its contract's
forbidden assumptions into the anachronism guard, which the harness's hooks hold for every session
(ResearchEngine._install_goal_hooks): two at once would check each other's claims against the wrong contract.

While a run goes on, a heartbeat every HEARTBEAT seconds says the server is still at it, and ``progress_at`` when its
session last logged something new.  A record says apart how long the run waited for its turn and how long it ran.

Where the runtime's sessions are kept on disk, so are the records (``<data>/chat/jobs``, a JSON file each, written when
the state changes and with each heartbeat), and an ended run's for KEEP_DAYS days (KEEP at most).
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Callable

HEARTBEAT = 5.0       # seconds between a running run's heartbeats
KEEP_DAYS = 3         # an ended run's record is kept this long
KEEP = 200            # and so many at most, the latest
ENDED = ("completed", "failed", "cancelled")
UNFINISHED = ("queued", "running", "cancel_requested")
LEGACY = {"queued": "queued", "running": "running", "cancel_requested": "running", "completed": "done", "failed": "error",
          "cancelled": "error", "interrupted": "error"}
STOPPED = "cancelled at the visitor's request"  # the reason the session's log records

# work(record, stop, attach) runs a record's research: `stop()` gives a reason once it is asked to stop, `attach(session)`
# names the session it runs (started, or opened from the store); it returns the outcome (chat.shape)
Work = Callable[[dict[str, Any], Callable[[], "str | None"], Callable[[Any], None]], dict[str, Any]]


def _failure(error: str) -> dict[str, Any]:
    from . import shape  # the package imports this module: shape is there by the time a run ends

    return shape("taochronos_research", False, None, error)


class Jobs:
    """The background research runs of one runtime.  `lock`: the runtime's research lock, which a run asked for
    directly (``taochronos_research``) holds too; `folder`: where the records are kept, or None (in memory only)."""

    def __init__(self, work: Work, *, lock: Any, folder: Path | None = None, clock: Callable[[], float] = time.time,
                 heartbeat: float = HEARTBEAT) -> None:
        self.work = work
        self.lock = lock
        self.folder = folder
        self.clock = clock
        self.beat = heartbeat
        self.mu = threading.Lock()   # the records and the queue
        self.wake = threading.Condition(self.mu)
        self.records: dict[str, dict[str, Any]] = {}
        self.queue: deque[str] = deque()
        self.sessions: dict[str, Any] = {}  # a running record's session, by its id
        self.worker: threading.Thread | None = None
        self.pulse: threading.Thread | None = None
        self._load()

    # ------------------------------------------------------------------ asked
    def start(self, question: str, arguments: dict[str, Any] | None = None) -> str:
        """Queue a run of `question` (its contract's fields in `arguments`); returns its id."""
        now = self.clock()
        rec: dict[str, Any] = {"id": "job_" + uuid.uuid4().hex[:12], "question": question, "arguments": dict(arguments or {}),
                               "state": "queued", "created": now, "queued_at": now, "started": None, "finished": None,
                               "waited": 0.0, "ran": 0.0, "session": None, "progress": None, "progress_at": None,
                               "heartbeat": None, "resumed": 0, "reason": None, "error": None, "outcome": None}
        with self.mu:
            self.records[rec["id"]] = rec
            self._enqueue(rec)
        return rec["id"]

    def cancel(self, job_id: str) -> dict[str, Any]:
        """Stop a run: one still queued at once, one running once the task it runs ends.  Returns its view."""
        with self.mu:
            rec = self.records.get(job_id)
            if rec is not None and rec["state"] in ("queued", "interrupted"):  # nothing runs it: it ends here
                if job_id in self.queue:
                    self.queue.remove(job_id)
                self._end(rec, "cancelled", _failure("研究已按要求停止"), reason="asked")
            elif rec is not None and rec["state"] == "running":
                rec.update(state="cancel_requested", reason="asked")
                self._save(rec)
        return self.view(job_id)

    def resume(self, job_id: str) -> dict[str, Any]:
        """Queue again a run the server stopped (``interrupted``): it goes on from its session's last checkpoint, or
        begins, if it had none.  Returns its view."""
        with self.mu:
            rec = self.records.get(job_id)
            if rec is not None and rec["state"] == "interrupted":
                rec.update(resumed=rec["resumed"] + 1, reason=None, queued_at=self.clock(), heartbeat=None)
                self._enqueue(rec)
        return self.view(job_id)

    def view(self, job_id: str) -> dict[str, Any]:
        """A run as the page sees it: its state, its place in the queue while it waits, how long it waited and ran, its
        heartbeat and last progress (seconds ago), and its outcome once it ended."""
        with self.mu:
            rec = self.records.get(job_id)
            if rec is None:
                return {"id": job_id, "state": "unknown", "status": "unknown"}
            now = self.clock()
            self._progress(rec, now)
            state = rec["state"]
            waiting = state == "queued"
            running = state in ("running", "cancel_requested")
            out = {k: v for k, v in rec.items() if k not in ("outcome", "arguments", "waited", "ran", "queued_at")}
            out["status"] = LEGACY[state]
            out["position"] = list(self.queue).index(job_id) + 1 if waiting and job_id in self.queue else None
            out["queued_s"] = round(rec["waited"] + (now - rec["queued_at"] if waiting else 0.0), 1)
            out["run_s"] = round(rec["ran"] + (now - rec["started"] if running and rec["started"] else 0.0), 1)
            out["elapsed_s"] = round((rec["finished"] or now) - rec["created"], 1)
            out["heartbeat_s"] = round(now - rec["heartbeat"], 1) if running and rec["heartbeat"] else None
            out["progress_s"] = round(now - rec["progress_at"], 1) if rec["progress_at"] else None
            if state in ENDED or state == "interrupted":
                out["outcome"] = rec["outcome"]
            return out

    # ------------------------------------------------------------------ the worker
    def _enqueue(self, rec: dict[str, Any]) -> None:
        rec["state"] = "queued"
        self.queue.append(rec["id"])
        self._save(rec)
        if self.worker is None or not self.worker.is_alive():
            self.worker = threading.Thread(target=self._serve, name="research-jobs", daemon=True)
            self.worker.start()
        if self.pulse is None:
            self.pulse = threading.Thread(target=self._pulse, name="research-heartbeat", daemon=True)
            self.pulse.start()
        self.wake.notify_all()

    def _serve(self) -> None:
        while True:
            with self.mu:
                while not self.queue:
                    self.wake.wait()
                rec = self.records[self.queue[0]]
            self._run(rec)

    def _run(self, rec: dict[str, Any]) -> None:
        stopped: list[bool] = []

        def stop() -> str | None:
            if rec["state"] != "cancel_requested":
                return None
            stopped.append(True)
            return STOPPED

        def attach(session: Any) -> None:
            with self.mu:
                self.sessions[rec["id"]] = session
                rec["session"] = session.id
                self._progress(rec, self.clock())
                self._save(rec)

        with self.lock:  # a run asked for directly may hold it: this one is first in the queue meanwhile
            with self.mu:
                if self.queue and self.queue[0] == rec["id"]:
                    self.queue.popleft()
                if rec["state"] != "queued":  # cancelled while it waited
                    return
                now = self.clock()
                rec.update(state="running", started=now, heartbeat=now, waited=rec["waited"] + now - rec["queued_at"])
                self._save(rec)
            try:
                outcome = self.work(dict(rec), stop, attach)
                state, error = ("cancelled" if stopped else "completed"), None
            except Exception as exc:  # the run's failure, kept as its outcome
                error = f"{type(exc).__name__}: {exc}"
                outcome, state = _failure(error), "failed"
        with self.mu:
            if state == "cancelled":  # what it found stays in its session (session_id)
                outcome = {**_failure("研究已按要求停止"), "session_id": rec["session"]}
            self._end(rec, state, outcome, reason="asked" if state == "cancelled" else None, error=error)

    def _end(self, rec: dict[str, Any], state: str, outcome: dict[str, Any], *, reason: str | None = None,
             error: str | None = None) -> None:
        now = self.clock()
        ran = rec["ran"] + (now - rec["started"] if rec["state"] in ("running", "cancel_requested") and rec["started"] else 0.0)
        rec.update(state=state, finished=now, ran=ran, outcome=outcome, error=error, heartbeat=None, reason=reason)
        session = self.sessions.pop(rec["id"], None)
        if session is not None:
            self._progress(rec, now, session)
        self._save(rec)
        self._prune(now)

    def _pulse(self) -> None:
        """The heartbeat of the run going on, while one runs or waits: it ends after the last (the next starts it again)."""
        tick = threading.Event()  # never set: a timed wait that a stubbed time.sleep does not turn into a busy loop
        while True:
            tick.wait(self.beat)
            with self.mu:
                now = self.clock()
                going = [rec for rec in self.records.values() if rec["state"] in ("running", "cancel_requested")]
                for rec in going:
                    rec["heartbeat"] = now
                    self._progress(rec, now)
                    self._save(rec)
                if not going and not self.queue:
                    self.pulse = None
                    return

    def _progress(self, rec: dict[str, Any], now: float, session: Any = None) -> None:
        """What its session has done so far, and when it last logged something new."""
        session = session or self.sessions.get(rec["id"])
        if session is None:
            return
        state = session.state
        m = state.metrics or {}
        progress = {"round": state.round, "status": state.status, "hypotheses": len(state.hypotheses), "claims": len(state.claims),
                    "evidence_count": len(state.evidence), "tool_calls": m.get("tool_calls"), "agents_spawned": m.get("agents_spawned"),
                    "events": session.seq}
        if (rec["progress"] or {}).get("events") != progress["events"]:
            rec["progress_at"] = now
        rec["progress"] = progress

    # ------------------------------------------------------------------ kept
    def _save(self, rec: dict[str, Any]) -> None:
        if self.folder is None:
            return
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            path = self.folder / f"{rec['id']}.json"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(rec, ensure_ascii=False, default=str), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:  # a full disk: the run goes on, kept in memory
            pass

    def _load(self) -> None:
        """The records an earlier server kept: a run it left queued or running is ``interrupted``."""
        if self.folder is None or not self.folder.is_dir():
            return
        for path in sorted(self.folder.glob("job_*.json")):
            try:
                rec = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(rec, dict) or rec.get("id") != path.stem or rec.get("state") not in (*UNFINISHED, *ENDED, "interrupted"):
                    continue
            except (OSError, ValueError):
                continue
            if rec["state"] in UNFINISHED:
                was = rec["state"]
                ran = rec.get("ran", 0.0) + (max(0.0, (rec.get("heartbeat") or rec["started"]) - rec["started"])
                                              if was != "queued" and rec.get("started") else 0.0)
                rec.update(state="interrupted", reason="restart", heartbeat=None, ran=ran,
                           outcome=_failure("服务在这次研究进行时停止了：可以从上次的检查点继续"))
                self._save(rec)
            self.records[rec["id"]] = rec
        self._prune(self.clock())

    def _prune(self, now: float) -> None:
        ended = sorted((r for r in self.records.values() if r["state"] in ENDED), key=lambda r: r["finished"] or 0.0)
        old = {r["id"] for r in ended if now - (r["finished"] or 0.0) > KEEP_DAYS * 86400}
        old |= {r["id"] for r in ended[:max(0, len(ended) - KEEP)]}
        for job_id in old:
            del self.records[job_id]
            if self.folder is not None:
                try:
                    (self.folder / f"{job_id}.json").unlink()
                except OSError:
                    pass
