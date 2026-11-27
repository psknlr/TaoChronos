"""What one call may cost a server that runs it for whoever asks: every argument of every tool has a limit, checked
before the tool runs and no part of what a model is shown; and the loops a caller's text or number used to drive
without bound — a count of permutations, brackets nested without end, a pattern that backtracks, a text with no mark
in it, an edge looked for among all its source's — end in the time their input's length allows."""

from __future__ import annotations

import contextlib
import faulthandler
import json
import random
import re
import sys
import time

import pytest

from taochronos.chat import SESSIONS_KEPT, ChatRuntime
from taochronos.chat.catalog import llm_tools
from taochronos.kernel.tools import LIST_ITEMS, TEXT_CHARS, ToolCall, ToolRegistry, ToolSpec
from taochronos.plugins.classics.notes import DEPTH, NOTE_OR_SQUARE, blank_notes, note_mask
from taochronos.plugins.classics.study.stemma import mask_notes
from taochronos.protocol.assertions import AssertionType
from taochronos.verification.evidence_graph import EvidenceGraph

LIMIT_WORDS = ("minimum", "maximum", "maxLength", "maxItems")


@pytest.fixture(scope="module")
def rt(tmp_path_factory):
    return ChatRuntime.create("full-discovery", kind="test", ephemeral=True, data_dir=tmp_path_factory.mktemp("cost"))


@pytest.fixture()
def within(capfd):
    """``with within(seconds):`` — the block ends within them, or the test fails; and if it has not ended in several
    times as long, the test process ends, with where it was written to the terminal: a loop that holds the interpreter
    (a pattern that backtracks) lets no other thread of this process say so, and a suite that hangs says nothing."""

    @contextlib.contextmanager
    def block(seconds: float):
        with capfd.disabled():  # the stack, should it come to that, is written where it can be read
            faulthandler.dump_traceback_later(max(30.0, seconds * 4), exit=True, file=sys.stderr)
            started = time.perf_counter()
            try:
                yield
            finally:
                faulthandler.cancel_dump_traceback_later()
        took = time.perf_counter() - started
        assert took < seconds, f"took {took:.1f} s, more than the {seconds} s it may"

    return block


# ------------------------------------------------------------------ the limits
def _kinds(prop):
    kinds = prop.get("type")
    return kinds if isinstance(kinds, list) else [kinds]


def test_every_argument_of_every_tool_has_a_limit_and_a_model_is_shown_none(rt):
    """A number, a text and a list each have a limit in every tool (the mesh's, a plugin's, the engine's and the
    meta-tools'); the schema a model's provider is sent says nothing of them — not every provider takes these words —
    and is what it was."""
    seen = 0
    for spec in rt.h.tools.list():
        checked = spec.checked["properties"] if spec.input_schema.get("properties") else {}
        for name, prop in (spec.input_schema.get("properties") or {}).items():
            kinds = _kinds(prop)
            if "enum" in prop or not {"integer", "number", "string", "array"} & set(kinds):
                continue
            seen += 1
            limit = checked[name]
            if "integer" in kinds or "number" in kinds:
                assert "minimum" in limit and "maximum" in limit, (spec.name, name)
            if "string" in kinds:
                assert 0 < limit["maxLength"] <= TEXT_CHARS, (spec.name, name)
            if "array" in kinds:
                assert 0 < limit["maxItems"], (spec.name, name)
                if (prop.get("items") or {}).get("type") == "string":
                    assert limit["items"]["maxLength"] <= TEXT_CHARS, (spec.name, name)
        assert not any(w in json.dumps(spec.input_schema) for w in LIMIT_WORDS), spec.name  # the schema itself is as it was
    assert seen > 300
    for name in ("taochronos_research", "taochronos_ask", "taochronos_session", "taochronos_catalog", "taochronos_call"):
        props = rt._schema(name)["properties"]
        assert all(any(w in p for w in LIMIT_WORDS) for k, p in props.items() if "enum" not in p and _kinds(p) != ["object"]), name
    for mode in ("core", "all"):
        shown = json.dumps(rt.catalog(mode), ensure_ascii=False)
        assert not any(f'"{w}"' in shown for w in LIMIT_WORDS)
        for tool in llm_tools(rt.h.tools, mode=mode):  # what the page hands a model's provider
            assert not any(w in json.dumps(tool["parameters"]) for w in LIMIT_WORDS), tool["name"]


def test_a_tool_registered_with_no_limits_of_its_own_has_its_types_defaults():
    reg = ToolRegistry()
    spec = reg.register(ToolSpec("x.count", "counts", {"type": "object", "properties": {
        "n": {"type": "integer"}, "share": {"type": "number", "minimum": 0, "maximum": 1}, "text": {"type": "string"},
        "mode": {"type": "string", "enum": ["a", "b"]}, "names": {"type": "array", "items": {"type": "string"}},
        "deep": {"type": "integer"}, "flag": {"type": "boolean"}}}, lambda ctx, a: a, limits={"deep": {"minimum": 1, "maximum": 3}}))
    assert spec.limits == {"deep": {"minimum": 1, "maximum": 3}, "n": {"minimum": 0, "maximum": 10_000}, "text": {"maxLength": TEXT_CHARS},
                           "names": {"maxItems": LIST_ITEMS, "items": {"maxLength": TEXT_CHARS}}}
    assert spec.checked["properties"]["share"] == {"type": "number", "minimum": 0, "maximum": 1}  # its schema's own stays
    assert spec.checked["properties"]["names"] == {"type": "array", "items": {"type": "string", "maxLength": TEXT_CHARS}, "maxItems": LIST_ITEMS}
    assert spec.input_schema["properties"]["n"] == {"type": "integer"}


def test_a_call_beyond_its_limits_is_refused_before_the_tool_runs(rt, within):
    """What these calls cost before: 10**18 permutations never ended (and their thread went on after the caller had
    hung up); a search for a thousand million hits read as deep as the corpus goes."""
    refused = [
        ("analysis.concept_drift", {"term": "消渴", "permutations": 10 ** 18}, "$.permutations: 1000000000000000000 > maximum 999"),
        ("analysis.concept_drift", {"term": "消渴", "permutations": 10 ** 300}, "$.permutations: a number of 301 digits > maximum 999"),
        ("analysis.concept_drift", {"term": "消渴", "permutations": -1}, "$.permutations: -1 < minimum 0"),
        ("classics.search", {"query": "桂枝汤", "k": 10 ** 9}, "$.k: 1000000000 > maximum 100"),
        ("classics.search", {"query": "桂枝汤", "k": "1000"}, "$.k: 1000 > maximum 100"),  # said of the number, not of its form
        ("classics.search", {"query": "桂" * (TEXT_CHARS + 1)}, f"$.query: {TEXT_CHARS + 1} characters > maxLength {TEXT_CHARS}"),
        ("classics.search", {"query": "桂枝汤", "books": ["b"] * (LIST_ITEMS + 1)}, f"$.books: {LIST_ITEMS + 1} items > maxItems {LIST_ITEMS}"),
        ("classics.search", {"query": "桂枝汤", "books": ["b" * (TEXT_CHARS + 1)]}, "$.books[0]: "),
        ("classics.search", {"query": "桂枝汤", "before": float("nan")}, "$.before: not a number"),
        ("classics.search", {"query": "桂枝汤", "before": float("inf")}, "$.before: inf > maximum"),
        ("study.term", {"term": "消渴", "items": -1}, "$.items: -1 < minimum 0"),
        ("study.stemma", {"work": "伤寒论", "max_chars": 10 ** 9}, "$.max_chars: 1000000000 > maximum"),
        ("taochronos_call", {"tool": "classics.search", "arguments": {"query": "桂枝汤", "k": 500}}, "$.k: 500 > maximum 100"),
        ("taochronos_ask", {"question": "消" * (TEXT_CHARS + 1)}, "$.question: "),
        ("taochronos_research", {"question": "消" * (TEXT_CHARS + 1)}, "$.question: "),
    ]
    with within(20):
        for name, arguments, said in refused:
            out = rt.call(name, arguments)
            assert not out["ok"] and out["error"].startswith("invalid arguments: ") and said in out["error"], (name, out["error"][:200])
            assert " takes: " in out["error"]  # with what the tool takes: the model asks again within it
    # the scheduler refuses the same, whoever calls (an agent's procedure, code in the sandbox)
    direct = rt.h.scheduler.execute(ToolCall("analysis.concept_drift", {"term": "消渴", "permutations": 10 ** 18}), actor=rt.actor)
    assert not direct.ok and "> maximum 999" in direct.error
    with pytest.raises(Exception, match="maxLength"):
        rt.research_arguments({"question": "消" * (TEXT_CHARS + 1)})
    # within them, as before — a tool's own calls of another too (the statistician ranks among the first 5000)
    assert rt.call("analysis.concept_drift", {"term": "消渴", "permutations": 999, "seed": 3})["ok"]
    assert rt.call("analysis.link_prediction", {"k": 5000})["ok"]
    assert rt.call("classics.search", {"query": "桂" * TEXT_CHARS, "k": 100, "before": -221, "after": -2000})["ok"]
    assert rt.call("classics.search", {"query": "桂枝汤", "k": "3"})["repaired"] == ['$.k: "3" → 3']


# ------------------------------------------------------------------ a chapter is text
def test_a_chapter_to_collate_is_part_of_a_heading_and_no_pattern(rt, within):
    """``chapter`` was compiled as a regular expression and every heading searched with it: ``(.+)+!`` — some twenty
    bytes of a request — backtracks for longer than the process lives, and the matcher holds the interpreter, so no
    other visitor of the server was answered meanwhile."""
    books = {"books": ["shanghanlun", "jinkui"], "base": "jinkui"}
    with within(20):
        for tool in ("study.stemma", "study.variants"):
            for chapter in ("(.+)+!", "(.+)+(.+)+!", "(" * 200, "卷一[上", "^妇人"):
                out = rt.call(tool, {**books, "chapter": chapter})
                assert not out["ok"] and "no heading of it holds" in out["error"], (tool, chapter, out["error"][:160])
    one = rt.call("study.stemma", {**books, "chapter": "妇人"})
    assert one["ok"], one.get("error")
    study = rt.h.capabilities.get("study")._stemma
    women = study.collate(books=books["books"], base="jinkui", chapter="妇人")["base"].text
    either = study.collate(books=books["books"], base="jinkui", chapter="婦人")["base"].text  # the other script
    several = study.collate(books=books["books"], base="jinkui", chapter="没有这一篇 | 妇人")["base"].text  # several, apart by |
    whole = study.collate(books=books["books"], base="jinkui")["base"].text
    assert women and women == either == several and len(women) < len(whole)
    for nothing in (" ", " | "):
        with pytest.raises(ValueError, match="empty"):
            study._headings(nothing)
    assert study._headings(None) is None and study._headings("") is None


# ------------------------------------------------------------------ notes
_OLD = re.compile(r"（[^（）]*）|\([^()]*\)|〔[^〔〕]*〕|【[^【】]*】|\[[^\[\]]*\]")


def _old_mask_notes(text: str) -> str:
    """What mask_notes was: the innermost notes blanked, again and again until nothing changes."""
    prev = None
    while prev != text:
        prev = text
        text = _OLD.sub(lambda m: " " * len(m.group(0)), text)
    return text


_OLD_NOTE = re.compile(r"（[^（）]*）|\([^()]*\)|〔[^〔〕]*〕|【[^【】]*】")


def _old_note_mask(text: str) -> bytearray:
    """What intertext's _note_mask was: the notes marked, the marked blanked, again until nothing more is marked."""
    mask = bytearray(len(text))
    for m in _OLD_NOTE.finditer(text):
        mask[m.start():m.end()] = b"\x01" * (m.end() - m.start())
    prev = None
    while prev != bytes(mask):
        prev = bytes(mask)
        blanked = "".join(" " if mask[i] else ch for i, ch in enumerate(text))
        for m in _OLD_NOTE.finditer(blanked):
            mask[m.start():m.end()] = b"\x01" * (m.end() - m.start())
    return mask


def test_notes_are_blanked_as_they_were_and_brackets_nested_deep_cost_no_more(within):
    """A pass over the whole text for each level of nesting: brackets nested 20,000 deep (40,000 characters, a sixth
    of what the site takes in a request) took 10 s in one function and over a minute in the other."""
    rng = random.Random(11)
    alphabet = "（）()〔〕【】[]桂枝 。\n"
    for _ in range(4000):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 30)))
        assert mask_notes(text) == blank_notes(text, NOTE_OR_SQUARE) == _old_mask_notes(text), text
        assert note_mask(text) == _old_note_mask(text), text
    text = "桂枝（去皮【一本作〔桂〕心】）三两，芍药(三两)，甘草[二两]（炙）"
    assert mask_notes(text) == "桂枝" + " " * 13 + "三两，芍药" + " " * 4 + "，甘草" + " " * 7
    assert bytes(note_mask("桂枝（去皮【心】）三两[二]")) == bytes([0, 0, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0])  # square brackets are text here
    deep = "（" * 20000 + "）" * 20000
    with within(2):
        blanked = mask_notes(deep)
        mask = note_mask(deep)
    # as deep as notes are read inside notes (DEPTH): what is nested deeper stays text
    assert len(blanked) == len(deep) and blanked.count(" ") == 2 * DEPTH == sum(mask)
    assert blanked[:20000 - DEPTH] == "（" * (20000 - DEPTH)


# ------------------------------------------------------------------ the evidence graph
def test_an_evidence_graph_finds_an_edge_by_its_ends(within):
    """An edge was looked for among all that leave its source: a passage with as many quotes as a long text has
    findings read each new one against all the others (30,000 edges: 10 s)."""
    g = EvidenceGraph()
    with within(2):
        for i in range(30000):
            g.edge("passage:p", f"quote:{i}", "contains", AssertionType.SOURCE_ASSERTED)
    assert len(g.edges) == 30000
    first = g.edge("passage:p", "quote:7", "contains", AssertionType.SOURCE_ASSERTED)
    again = g.edge("passage:p", "quote:7", "contains", AssertionType.MODEL_INFERRED, note="another")  # the same edge, kept as it was
    assert again is first and len(g.edges) == 30000 and first.assertion is AssertionType.SOURCE_ASSERTED and not first.props
    other = g.edge("passage:p", "quote:7", "states", AssertionType.MODEL_EXTRACTED)  # another type between the same nodes
    assert other is not first and len(g.edges) == 30001
    merged = EvidenceGraph().merge(g)
    assert len(merged.edges) == 30001 and len(merged.merge(g).edges) == 30001


# ------------------------------------------------------------------ the bridge reads around a finding
def test_a_text_without_marks_is_read_around_each_finding(harness, within):
    """A clause ends at a mark, and a text with none is one clause: each of its findings read the whole of it for the
    words of its timing, and to the text's ends for its sentence — the square of the text (79,000 characters: 7 s).
    What is read is now what stands around the finding; a clause of the classics is far shorter, and reads as before."""
    bridge = harness.capabilities.get("bridge")
    bridge.study.judge = None
    by = lambda packet, surface: next(f for f in packet["findings"] if f["surface"] == surface)  # noqa: E731
    assert by(bridge.phenotype("口渴夜甚"), "口渴")["modifiers"] == {"timing": "night"}
    assert by(bridge.phenotype("咳逆上气喘而不得卧"), "不得卧")["phenotype"] == "orthopnea"
    far = "桂" * 3000
    assert by(bridge.phenotype("口渴" + far + "夜甚"), "口渴")["modifiers"] == {}  # 夜 three thousand characters on is not its timing
    assert by(bridge.phenotype("夜甚" + far + "口渴"), "口渴")["modifiers"] == {}
    alone = by(bridge.phenotype("咳逆上气喘" + far + "不得卧"), "不得卧")
    assert alone["phenotype"] == "insomnia" and alone["review"]  # no cue near it: the default, for review
    near = "桂" * 500  # within what is read: as in a clause
    assert by(bridge.phenotype("口渴" + near + "夜甚"), "口渴")["modifiers"] == {"timing": "night"}
    assert by(bridge.phenotype("咳逆上气喘" + near + "不得卧"), "不得卧")["phenotype"] == "orthopnea"
    with within(8):
        packet = bridge.phenotype(("消渴口渴多饮小便数" * 9000)[:80000])
    assert len(packet["findings"]) > 30000


# ------------------------------------------------------------------ what is kept
def test_the_normalizer_keeps_the_corpus_passages_and_no_long_text(harness):
    """Its memo was bounded by entries alone (200,000): of a caller's long texts, more than any memory holds."""
    v = harness.pack.variants
    before = len(v._cache)
    for i in range(40):
        long = f"第{i}问：" + "消渴口渴多饮小便数" * 2000
        assert v.normalize_text(long) == v.normalize_text(long) and long not in v._cache
    assert len(v._cache) == before
    assert v.normalize_text("傷寒") == "伤寒" and "傷寒" in v._cache
    assert v._cache.chars <= 24_000_000 and v._cache.texts == 200_000


class _Session:
    def __init__(self, sid: str) -> None:
        self.id = sid


def test_a_runtime_holds_few_sessions_and_reads_the_others_again(tmp_path):
    """Every run's session stayed in memory for as long as the server ran: its whole state, twice."""
    rt = ChatRuntime.create("full-discovery", kind="test", ephemeral=True, data_dir=tmp_path)
    running = _Session("ses_running")
    rt._keep(running, running=True)
    for i in range(SESSIONS_KEPT + 5):
        rt._keep(_Session(f"ses_{i}"))
    assert len(rt.sessions) == SESSIONS_KEPT and "ses_running" in rt.sessions  # the one being run is never let go of
    assert list(rt.sessions)[-1] == f"ses_{SESSIONS_KEPT + 4}"
    rt._ran(running)
    rt._keep(_Session("ses_last"))
    assert "ses_running" not in rt.sessions and len(rt.sessions) == SESSIONS_KEPT
    # a real run, let go of and asked for again: read from the store, the same
    out = rt.call("taochronos_research", {"question": "消渴的认识与治疗在明代以前如何演变？", "focus_terms": ["消渴"], "max_rounds": 1})
    assert out["ok"], out.get("error")
    sid = out["result"]["session_id"]
    held = rt.sessions[sid]
    summary = rt.session_view(sid)
    for i in range(SESSIONS_KEPT):
        rt._keep(_Session(f"ses_more_{i}"))
    assert sid not in rt.sessions
    assert rt.session_view(sid) == summary and rt.sessions[sid] is not held and list(rt.sessions)[-1] == sid
    report = rt.session_view(sid, what="report")
    assert report["report_markdown"]
    with pytest.raises(KeyError):
        rt.session_view("ses_" + "0" * 32)
    assert "ses_" + "0" * 32 not in rt.sessions


def test_a_research_run_is_not_made_inside_a_call_on_a_server_others_reach(rt):
    """``POST /api/call`` with the tool taochronos_research made the run inside the request: beside the queue of
    ``POST /api/research`` (which holds so many and refuses the rest), and counted by the site as a call, of which an
    address has thirty times as many a day as it has research runs."""
    import http.client
    import threading

    from taochronos.chat.server import ChatServer

    for name, arguments in (("taochronos_research", {"question": "消渴的源流"}), ("taochronos__research", {"question": "消渴的源流"}),
                            ("taochronos_call", {"tool": "taochronos_research", "arguments": {"question": "消渴的源流"}})):
        out = rt.call(name, arguments, inline_research=False)
        assert not out["ok"] and "POST /api/research" in out["error"] and out["tool"] == "taochronos_research", out
    assert rt.call("classics.search", {"query": "消渴", "k": 2}, inline_research=False)["ok"]
    assert rt.call("taochronos_call", {"tool": "taochronos_catalog", "arguments": {"query": "配伍"}}, inline_research=False)["ok"]
    shared = ChatServer(("0.0.0.0", 0), rt, web_root=None, token="t0ken")
    threading.Thread(target=shared.serve_forever, daemon=True).start()
    try:
        assert not shared.private
        before = len(rt.sessions)
        conn = http.client.HTTPConnection("127.0.0.1", shared.server_address[1], timeout=60)
        conn.request("POST", "/api/call", body=json.dumps({"name": "taochronos_research", "arguments": {"question": "消渴的源流"}}),
                     headers={"Content-Type": "application/json", "X-TC-Token": "t0ken"})
        resp = conn.getresponse()
        out = json.loads(resp.read())
        conn.close()
        assert resp.status == 200 and not out["ok"] and "POST /api/research" in out["error"] and len(rt.sessions) == before
    finally:
        shared.shutdown()
        shared.server_close()


def test_what_a_run_left_can_be_forgotten_but_not_while_it_runs(tmp_path):
    """A run's log in the store and the files it published stayed for as long as the data did: on the corpus container,
    whose disk is its image's and little besides, they go when the run's record does (chat/cloud.py)."""
    rt = ChatRuntime.create("full-discovery", kind="test", data_dir=tmp_path)
    out = rt.call("taochronos_research", {"question": "消渴的认识与治疗在明代以前如何演变？", "focus_terms": ["消渴"], "max_rounds": 1})
    assert out["ok"], out.get("error")
    sid = out["result"]["session_id"]
    published = tmp_path / "artifacts" / sid
    assert rt.h.store.last_seq(sid) > 0 and published.is_dir() and any(published.rglob("*"))
    rt._running.add(sid)  # as while it runs: nothing is taken from under it
    rt.forget_session(sid)
    assert rt.h.store.last_seq(sid) > 0 and published.is_dir() and sid in rt.sessions
    rt._running.discard(sid)
    rt.forget_session(sid)
    assert rt.h.store.last_seq(sid) == 0 and not published.exists() and sid not in rt.sessions
    with pytest.raises(KeyError):
        rt.session_view(sid)
    (tmp_path / "artifacts" / "kept.txt").write_text("another's", encoding="utf-8")
    for odd in ("..", ".", "../artifacts", "a/b", ""):  # a folder of the artifacts, never anything else
        rt.forget_session(odd)
    assert (tmp_path / "artifacts" / "kept.txt").exists() and (tmp_path / "artifacts").is_dir() and (tmp_path / "events.sqlite").exists()


def test_a_question_asked_of_the_workflow_leaves_no_workspace(tmp_path):
    """The workflow writes its plan and every step's result where a run can be taken up again; a conversation never
    takes one up (resume=False), and each new question left its workspace on the server's disk for good."""
    rt = ChatRuntime.create("full-discovery", kind="test", data_dir=tmp_path)
    out = rt.call("taochronos_ask", {"question": "桂枝汤的组成在历代如何变化？"})
    assert out["ok"] and out["result"]["steps"] and out["result"]["report_markdown"], out.get("error")
    assert out["result"]["run"].startswith("run-")  # the run is named by its plan, as it was
    assert not any((tmp_path / "workspaces").iterdir())
    report = out["result"]["report_markdown"]
    assert "工作区" not in report and str(tmp_path) not in report  # and its report says nothing of the server's disk
    again = rt.call("taochronos_ask", {"question": "桂枝汤的组成在历代如何变化？"})
    assert again["result"] == out["result"] and again["receipt"] == out["receipt"]
    # the command line's run keeps its workspace, and is taken up from it
    from taochronos.engine.workflow import ask

    kept = ask(rt.h, "桂枝汤的组成在历代如何变化？")
    assert (tmp_path / "workspaces" / kept["run"] / "report.md").read_text(encoding="utf-8") == kept["report"]
    assert f"工作区 {tmp_path / 'workspaces' / kept['run']}" in kept["report"]
    assert all(s["cached"] == s["calls"] for s in ask(rt.h, "桂枝汤的组成在历代如何变化？")["steps"])


def test_a_failed_write_of_the_log_says_why():
    """With no room on the disk the write fails and has ended its own transaction: the ROLLBACK after it failed in
    turn, and what was raised was "cannot rollback - no transaction is active" — which says nothing of the disk."""
    import sqlite3

    from taochronos.kernel.store import SqliteEventStore
    from taochronos.protocol.events import Event

    store = SqliteEventStore(":memory:")

    class NoRoom:
        def execute(self, sql, *args):
            if sql == "ROLLBACK":
                raise sqlite3.OperationalError("cannot rollback - no transaction is active")

        def executemany(self, sql, rows):
            raise sqlite3.OperationalError("database or disk is full")

    store._conn = NoRoom()
    event = Event(session_id="s", seq=1, type="session.started", actor="kernel")
    with pytest.raises(sqlite3.OperationalError, match="database or disk is full"):
        store.append([event])


def test_a_server_gives_the_interpreter_up_often(rt):
    """Beside one call that computes, a call that reads the store waited a whole switch interval at each of its reads:
    at the default 5 ms a search of 0.15 s took 44 s."""
    import threading

    from taochronos.chat import server as server_module

    srv = server_module.ChatServer(("127.0.0.1", 0), rt, web_root=None)
    before = sys.getswitchinterval()
    try:
        sys.setswitchinterval(0.005)
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        deadline = time.time() + 10
        while sys.getswitchinterval() > 0.001 and time.time() < deadline:
            time.sleep(0.01)
        assert sys.getswitchinterval() <= server_module.SWITCH_INTERVAL * 1.5 and server_module.SWITCH_INTERVAL <= 0.0005
    finally:
        srv.shutdown()
        srv.server_close()
        sys.setswitchinterval(before)
