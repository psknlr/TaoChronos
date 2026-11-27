"""Research runs in the background (src/taochronos/chat/jobs.py): their states, their queue, their times and heartbeat,
stopping one, and one the server stopped taken up again from its last checkpoint."""

from __future__ import annotations

import json
import threading
import time

from taochronos.chat import ChatRuntime
from taochronos.chat import jobs as J
from taochronos.chat.jobs import Jobs
from taochronos.kernel import FaultInjectingStore
from taochronos.kernel.store import SqliteEventStore

from conftest import HOME, make_harness


def until(test, timeout=10.0):
    end = time.time() + timeout
    while not test():
        if time.time() > end:
            raise AssertionError("timed out")
        time.sleep(0.005)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class State:
    def __init__(self):
        self.round, self.status, self.metrics = 0, "running", {"tool_calls": 2}
        self.hypotheses, self.claims, self.evidence = {}, {"c1": 1}, {}


class Session:
    """What a run's session shows of itself: its id, how many events its log holds, its state."""

    def __init__(self, sid):
        self.id, self.seq, self.state = sid, 1, State()


class Runs:
    """Runs held until let go, each told by its question; a run asked to stop says so, and stops when it may."""

    def __init__(self):
        self.go = {}
        self.seen = []
        self.sessions = {}

    def __call__(self, job, stop, attach):
        q = job["question"]
        self.seen.append((q, job["session"]))
        session = Session(job["session"] or f"s-{q}")
        attach(session)  # the record names its session before the test can see it
        self.sessions[q] = session
        gate = self.go.setdefault(q, threading.Event())
        while not gate.wait(0.005):
            if q.startswith("stoppable") and stop():
                return {"ok": False, "text": "stopped"}
        if q.startswith("failing"):
            raise RuntimeError("boom")
        return {"ok": True, "tool": "taochronos_research", "text": q, "result": {"session_id": session.id}}

    def let(self, q):
        self.go.setdefault(q, threading.Event()).set()


def state(jobs, job_id):
    return jobs.view(job_id)["state"]


def test_runs_wait_their_turn_first_come_first_served_and_say_where_they_are():
    runs, clock = Runs(), Clock()
    jobs = Jobs(runs, lock=threading.Lock(), clock=clock)
    a, b, c = (jobs.start(q, {"max_rounds": 1}) for q in ("a", "b", "c"))
    until(lambda: state(jobs, a) == "running")
    clock.t += 30
    va, vb, vc = jobs.view(a), jobs.view(b), jobs.view(c)
    assert [va["state"], vb["state"], vc["state"]] == ["running", "queued", "queued"]
    assert [va["position"], vb["position"], vc["position"]] == [None, 1, 2]
    assert [va["status"], vb["status"]] == ["running", "queued"]  # the words an earlier page reads
    assert [va["queued_s"], va["run_s"], vb["queued_s"], vb["run_s"]] == [0.0, 30.0, 30.0, 0.0]
    assert "outcome" not in va and "arguments" not in va and va["question"] == "a"
    runs.let("a")
    until(lambda: state(jobs, b) == "running")
    clock.t += 5
    va, vb, vc = jobs.view(a), jobs.view(b), jobs.view(c)
    assert [va["state"], va["status"], va["outcome"]["text"], vb["queued_s"], vb["run_s"], vc["position"]] == [
        "completed", "done", "a", 30.0, 5.0, 1]
    assert va["heartbeat_s"] is None and va["run_s"] == 30.0  # an ended run: neither beats nor runs on
    runs.let("b")
    runs.let("c")
    until(lambda: state(jobs, c) == "completed")
    assert [q for q, _ in runs.seen] == ["a", "b", "c"]
    assert jobs.view("job_none") == {"id": "job_none", "state": "unknown", "status": "unknown"}


def test_a_runs_id_is_its_only_key_and_only_so_many_runs_wait():
    """Whoever names a run may follow, stop and read it, so its id is not a short handle: 128 random bits.  And the
    queue has an end: a run asked for beyond it is refused at once, not queued behind hours of others."""
    runs = Runs()
    jobs = Jobs(runs, lock=threading.Lock(), limit=2)
    first = jobs.start("stoppable")
    until(lambda: state(jobs, first) == "running")
    waiting = [jobs.start("w1"), jobs.start("w2")]
    ids = [first, *waiting]
    assert all(len(i) == len("job_") + 32 and int(i[4:], 16) >= 0 for i in ids) and len(set(ids)) == 3
    assert J.QUEUE == 20 and Jobs(runs, lock=threading.Lock()).limit == 20
    try:
        jobs.start("w3")
        raise AssertionError("a third waiting run was taken")
    except J.QueueFull as exc:
        assert "2 个研究在等候" in str(exc)
    assert len(jobs.records) == 3  # the one refused left no record
    jobs.cancel(waiting[0])  # a place freed is a place to take
    third = jobs.start("w3")
    assert [jobs.view(waiting[1])["position"], jobs.view(third)["position"]] == [1, 2]
    for q in ("w2", "w3"):
        runs.let(q)
    jobs.cancel(first)
    until(lambda: state(jobs, third) == "completed")


def test_a_run_asked_for_directly_keeps_the_next_one_waiting_first_in_the_queue():
    runs, lock = Runs(), threading.Lock()
    jobs = Jobs(runs, lock=lock)
    with lock:  # ChatRuntime.research holds it while it runs
        j = jobs.start("a")
        time.sleep(0.05)
        assert [state(jobs, j), jobs.view(j)["position"], runs.seen] == ["queued", 1, []]
    until(lambda: state(jobs, j) == "running")
    runs.let("a")
    until(lambda: state(jobs, j) == "completed")


def test_a_run_stops_at_once_while_it_waits_and_once_its_task_ends_while_it_runs():
    runs = Runs()
    jobs = Jobs(runs, lock=threading.Lock())
    first, waiting, behind = jobs.start("stoppable"), jobs.start("w"), jobs.start("x")
    until(lambda: state(jobs, first) == "running")
    v = jobs.cancel(waiting)
    assert [v["state"], v["status"], v["reason"], v["outcome"]["ok"], jobs.view(behind)["position"]] == [
        "cancelled", "error", "asked", False, 1]
    v = jobs.cancel(first)
    assert v["state"] in ("cancel_requested", "cancelled") and v["status"] in ("running", "error")
    until(lambda: state(jobs, first) == "cancelled")
    v = jobs.view(first)
    assert [v["reason"], v["outcome"]["ok"], v["outcome"]["session_id"], v["outcome"]["error"]] == [
        "asked", False, "s-stoppable", "研究已按要求停止"]
    until(lambda: state(jobs, behind) == "running")  # the queue goes on
    assert jobs.cancel(first)["state"] == "cancelled" and jobs.resume(first)["state"] == "cancelled"  # once ended, ended
    # asked to stop, a run that ends without asking whether to stop has completed
    v = jobs.cancel(behind)
    assert v["state"] == "cancel_requested"
    runs.let("x")
    until(lambda: state(jobs, behind) == "completed")
    assert jobs.view(behind)["reason"] is None and jobs.view(behind)["outcome"]["ok"]
    # a failure is the run's end, with its reason
    f = jobs.start("failing")
    runs.let("failing")
    until(lambda: state(jobs, f) == "failed")
    v = jobs.view(f)
    assert [v["status"], v["error"], v["outcome"]["ok"], v["outcome"]["error"]] == ["error", "RuntimeError: boom", False,
                                                                                   "RuntimeError: boom"]


def test_a_running_run_beats_and_says_when_it_last_made_progress(monkeypatch):
    slept, sleep = [], time.sleep  # who sleeps (time.sleep, as a test may stub it): not the heartbeat
    monkeypatch.setattr(time, "sleep", lambda s: (slept.append(threading.current_thread().name), sleep(s)))
    runs = Runs()
    jobs = Jobs(runs, lock=threading.Lock(), heartbeat=0.02)
    j = jobs.start("a")
    until(lambda: state(jobs, j) == "running" and "a" in runs.sessions)
    first = jobs.view(j)
    assert first["session"] == "s-a" and first["progress"] == {"round": 0, "status": "running", "hypotheses": 0, "claims": 1,
                                                               "evidence_count": 0, "tool_calls": 2, "agents_spawned": None, "events": 1}
    beat = jobs.records[j]["heartbeat"]
    until(lambda: jobs.records[j]["heartbeat"] > beat)  # beating while nothing new is logged
    assert jobs.records[j]["progress_at"] == first["progress_at"] and jobs.view(j)["heartbeat_s"] < 1
    runs.sessions["a"].seq, runs.sessions["a"].state.round = 7, 1
    runs.sessions["a"].state.hypotheses["H1"] = 1
    until(lambda: jobs.records[j]["progress_at"] > first["progress_at"])
    v = jobs.view(j)
    assert [v["progress"]["events"], v["progress"]["round"], v["progress"]["hypotheses"]] == [7, 1, 1] and v["progress_s"] < 1
    pulse = jobs.pulse
    runs.let("a")
    until(lambda: state(jobs, j) == "completed")
    # the heartbeat ends with the last run, and the next starts it again
    until(lambda: jobs.pulse is None and not pulse.is_alive())
    k = jobs.start("b")
    until(lambda: state(jobs, k) == "running")
    beat = jobs.records[k]["heartbeat"]
    until(lambda: jobs.records[k]["heartbeat"] > beat)
    runs.let("b")
    until(lambda: state(jobs, k) == "completed" and jobs.pulse is None)
    assert slept and "research-heartbeat" not in slept


def test_records_are_kept_and_a_run_the_server_stopped_goes_on_when_asked(tmp_path):
    gone, runs, clock = Runs(), Runs(), Clock()  # the server that stops (its runs never let go until the end), the next
    folder = tmp_path / "jobs"
    jobs = Jobs(gone, lock=threading.Lock(), folder=folder, clock=clock)
    a, b, done = jobs.start("a", {"max_rounds": 1}), jobs.start("b"), jobs.start("c")
    # (the run has named its session: its thread saves the record as it does, and a save of the test's own beside it
    # tore the file, or came before the session, one run in twenty on a busy machine)
    until(lambda: state(jobs, a) == "running" and jobs.view(a)["session"] == "s-a")
    clock.t += 40
    with jobs.mu:  # as the heartbeat keeps it
        jobs.records[a]["heartbeat"] = clock.t  # its last heartbeat, 40 s into the run
        jobs._save(jobs.records[a])
    assert json.loads((folder / f"{a}.json").read_text(encoding="utf-8"))["state"] == "running"
    (folder / "job_garbled.json").write_text("{", encoding="utf-8")
    (folder / "job_other.json").write_text(json.dumps({"id": "job_else", "state": "queued"}), encoding="utf-8")
    # the server starts again: what was queued or running is interrupted, kept, and says so
    again = Jobs(runs, lock=threading.Lock(), folder=folder, clock=clock)
    assert set(again.records) == {a, b, done}
    va, vb = again.view(a), again.view(b)
    assert [va["state"], va["status"], va["reason"], va["run_s"], va["session"], vb["state"]] == [
        "interrupted", "error", "restart", 40.0, "s-a", "interrupted"]
    assert va["outcome"]["error"] == "服务在这次研究进行时停止了：可以从上次的检查点继续" and va["heartbeat_s"] is None
    assert json.loads((folder / f"{a}.json").read_text(encoding="utf-8"))["state"] == "interrupted"
    # asked, it goes on from its session (the one it had), its times adding up; one not begun begins; one let go ends
    v = again.resume(a)
    assert v["resumed"] == 1 and v["state"] in ("queued", "running")
    until(lambda: state(again, a) == "running" and runs.seen == [("a", "s-a")])
    clock.t += 10
    assert again.view(a)["run_s"] == 50.0
    runs.let("a")
    until(lambda: state(again, a) == "completed")
    assert again.view(a)["outcome"]["result"]["session_id"] == "s-a" and again.resume(a)["state"] == "completed"
    assert again.cancel(b)["state"] == "cancelled" and again.resume(b)["state"] == "cancelled"
    assert json.loads((folder / f"{b}.json").read_text(encoding="utf-8"))["state"] == "cancelled"
    gone.let("a")  # the first server's worker, held until now
    for q in ("b", "c"):
        gone.let(q)


def test_ended_runs_are_kept_a_few_days_and_so_many_at_most(tmp_path, monkeypatch):
    monkeypatch.setattr(J, "KEEP", 2)
    runs, clock = Runs(), Clock()
    folder = tmp_path / "jobs"
    jobs = Jobs(runs, lock=threading.Lock(), folder=folder, clock=clock)
    ids = []
    for q in ("a", "b", "c"):
        ids.append(jobs.start(q))
        runs.let(q)
        until(lambda: state(jobs, ids[-1]) == "completed")
        clock.t += 1
    assert [state(jobs, i) for i in ids] == ["unknown", "completed", "completed"] and not (folder / f"{ids[0]}.json").exists()
    waiting = jobs.start("w")  # held: not an ended run, whatever its age
    until(lambda: state(jobs, waiting) == "running")
    clock.t += J.KEEP_DAYS * 86400 + 5
    jobs.cancel(jobs.start("z"))  # an end: the old ones go
    assert [state(jobs, i) for i in ids[1:]] == ["unknown", "unknown"] and state(jobs, waiting) == "running"
    assert sorted(p.stem for p in folder.glob("*.json")) == sorted(jobs.records)
    runs.let("w")


def test_a_research_run_asked_to_stop_ends_after_its_task_and_its_session_says_so(tmp_path):
    h = make_harness(tmp_path)
    engine = h.engine()
    session = engine.start(h.make_goal("消渴的概念如何演变？", focus_terms=["消渴"], stop={"max_rounds": 2}), session_id="halt")
    asked = []

    def stop():
        asked.append(session.seq)
        return "cancelled at the visitor's request" if len(asked) > 3 else None

    engine.run(session, stop=stop)
    state = session.state
    assert state.status == "stopped" and state.stop["reasons"] == ["cancelled at the visitor's request"]
    assert state.round == 0 and "0" in state.rounds and state.acceptance  # its round closed, the contract judged
    assert any(t.status == "pending" for t in state.task_graph.values())  # what it had not begun stays undone
    assert session.verify()["consistent"]
    assert engine.resume("halt").status == "stopped"  # a stopped run stays stopped


def test_a_run_the_server_stopped_mid_way_is_taken_up_from_its_log_after_a_restart(tmp_path):
    """The whole path: a run whose server dies mid-way (its log as a crash leaves it, its record still running) is
    interrupted when the server is back on the same data, and goes on from its last checkpoint to the end."""
    data = tmp_path / "data"
    inner = SqliteEventStore(data / "events.sqlite")
    harness = make_harness(data, store=FaultInjectingStore(inner, crash_on_batch=9))
    first = ChatRuntime(harness, kind="test")
    assert first.jobs.folder == data / "chat" / "jobs"
    job = first.start_research("消渴的概念如何随时代演变？", focus_terms=["消渴"], max_rounds=1)
    until(lambda: first.job(job)["state"] == "failed", 120)
    assert "SimulatedCrash" in first.job(job)["error"]
    path = data / "chat" / "jobs" / f"{job}.json"
    rec = json.loads(path.read_text(encoding="utf-8"))
    rec.update(state="running", finished=None, outcome=None, error=None)  # a process that died writes nothing more
    path.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")

    rt = ChatRuntime.create("full-discovery", home=HOME, data_dir=data, kind="test")
    v = rt.job(job)
    assert [v["state"], v["reason"], v["session"]] == ["interrupted", "restart", rec["session"]] and rec["session"]
    rt.resume_research(job)
    until(lambda: rt.job(job)["state"] in ("completed", "failed"), 180)
    v = rt.job(job)
    assert v["state"] == "completed" and v["resumed"] == 1, v.get("error")
    result = v["outcome"]["result"]
    assert result["session_id"] == rec["session"] and result["hypotheses"]


def test_an_ephemeral_runtime_keeps_its_records_in_memory(tmp_path):
    rt = ChatRuntime.create("full-discovery", home=HOME, data_dir=tmp_path, kind="test", ephemeral=True)
    assert rt.jobs.folder is None


def test_a_record_that_cannot_be_written_neither_ends_the_worker_nor_stays_in_the_queue(tmp_path, monkeypatch):
    """A record with half a character in it (a lone surrogate, which a list written as JSON text could bring past the
    door) could not be written: the run was queued, its request failed, and when the worker reached it, the worker ended
    with it.  Twenty such requests filled the queue with runs nobody would ever take: no research run was accepted
    again until the server was started anew."""
    runs = Runs()
    jobs = Jobs(runs, lock=threading.Lock(), folder=tmp_path / "jobs", limit=3)
    half = [jobs.start("消渴\ud83d的源流", {"books": ["b\udc00"], "focus_terms": ["消渴"]}) for _ in range(3)]
    until(lambda: state(jobs, half[0]) == "running")
    kept = json.loads((tmp_path / "jobs" / f"{half[0]}.json").read_text(encoding="utf-8"))  # written, and as text
    assert kept["question"] == "消渴�的源流" and kept["arguments"]["books"] == ["b�"]
    assert jobs.view(half[0])["question"] == "消渴�的源流"
    for _ in half:
        runs.let("消渴�的源流")
    until(lambda: state(jobs, half[2]) == "completed")

    # whatever else the keeping of a run raises: that run fails, the worker goes on to the next
    real, raised = jobs._save, []

    def save(rec):
        if rec["question"] == "unkept" and rec["state"] == "running":
            raised.append(rec["id"])
            raise ValueError("no room, no JSON, whatever")
        real(rec)

    monkeypatch.setattr(jobs, "_save", save)
    bad, good = jobs.start("unkept"), jobs.start("kept")
    runs.let("kept")
    until(lambda: state(jobs, good) == "completed")
    view = jobs.view(bad)
    assert raised == [bad] and view["state"] == "failed" and "ValueError" in view["error"] and bad not in jobs.queue
    assert jobs.worker.is_alive() and not jobs.queue
    assert [q for q, _ in runs.seen].count("unkept") == 0  # it never ran: nothing of it was kept


def test_a_list_written_as_text_brings_no_half_character_into_a_run(tmp_path):
    """The whole scenario, through the server's own door: twenty requests whose list is JSON text spelling half a
    character, then another visitor's ordinary run."""
    import http.client

    from taochronos.chat.server import ChatServer

    rt = ChatRuntime.create("full-discovery", kind="test", data_dir=tmp_path, home=HOME)
    assert rt.jobs.folder is not None
    fields = rt.research_arguments({"question": "消渴的源流", "books": '["shanghanlun\\ud83d"]', "focus_terms": '["\\ud800"]'})
    assert fields["books"] == ["shanghanlun�"] and fields["focus_terms"] == ["�"]
    srv = ChatServer(("127.0.0.1", 0), rt, web_root=None)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def post(body: bytes):
        conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=60)
        conn.request("POST", "/api/research", body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        out = json.loads(resp.read())
        conn.close()
        return resp.status, out

    try:
        poison = b'{"question": "x", "books": "[\\"\\\\ud83d\\"]", "max_rounds": 1}'
        assert json.loads(poison)["books"] == '["\\ud83d"]'  # the body itself holds no half character: its text spells one
        seen = [post(poison) for _ in range(J.QUEUE)]
        assert all(status in (200, 429) for status, _ in seen) and seen[0][0] == 200, seen[:2]
        jobs = [out["job"] for status, out in seen if status == 200]
        until(lambda: all(rt.job(j)["state"] in J.ENDED for j in jobs), timeout=240)
        assert rt.jobs.worker.is_alive() and not rt.jobs.queue
        assert len(list(rt.jobs.folder.glob("job_*.json"))) == len(jobs) and not list(rt.jobs.folder.glob("*.tmp"))
        status, out = post(json.dumps({"question": "消渴的认识与治疗在明代以前如何演变？", "focus_terms": ["消渴"], "max_rounds": 1}).encode())
        assert status == 200, out
        until(lambda: rt.job(out["job"])["state"] in J.ENDED, timeout=240)
        assert rt.job(out["job"])["state"] == "completed"
    finally:
        srv.shutdown()
        srv.server_close()


def test_what_goes_with_an_ended_runs_record_is_the_servers_to_say(tmp_path):
    """A server keeps so many ended runs (``keep``), and may say what else goes when a record does (``forget``): the
    corpus container, whose disk is its image's, lets a run's log and artifacts go with it (chat/cloud.py)."""
    runs, clock = Runs(), Clock()
    jobs = Jobs(runs, lock=threading.Lock(), clock=clock, folder=tmp_path / "jobs")
    assert jobs.keep == J.KEEP and jobs.forget is None
    gone: list[tuple[str, str]] = []
    jobs.keep = 2
    jobs.forget = lambda rec: gone.append((rec["question"], rec["session"]))
    ids = []
    for q in ("a", "b", "c", "d"):
        runs.let(q)
        ids.append(jobs.start(q))
        until(lambda: state(jobs, ids[-1]) == "completed")
        clock.t += 1
    assert gone == [("a", "s-a"), ("b", "s-b")] and sorted(jobs.records) == sorted(ids[2:])
    assert sorted(p.stem for p in (tmp_path / "jobs").glob("job_*.json")) == sorted(ids[2:])
    jobs.forget = lambda rec: 1 / 0  # what a run left could not be removed: its record goes all the same
    runs.let("e")
    last = jobs.start("e")
    until(lambda: state(jobs, last) == "completed")
    assert sorted(jobs.records) == sorted([ids[3], last]) and jobs.worker.is_alive()
