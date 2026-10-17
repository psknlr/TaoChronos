import json
import re
import sys
from types import SimpleNamespace

import pytest

from conftest import HOME, make_harness, run_research
from taochronos.agents import AgentSpec, CognitiveRouter, SpecError, load_specs, parse_json_output, validate_spec
from taochronos.agents.procedures.evidence import PER_QUERY, _question_level, hit_note
from taochronos.capabilities.llm import LLMResponse, Usage
from taochronos.kernel import Actor, PolicyEngine, ToolCall
from taochronos.plugins.classics import DomainPack
from taochronos.plugins.classics.aliases import AliasRecord, Referent, Witness, write_records
from taochronos.plugins.models.scripted import ScriptedProvider
from taochronos.plugins.retrieval import HybridRetriever
from taochronos.plugins.subagents import CommandSubagentProvider


def test_director_is_named_taochronos_and_all_specs_validate(harness):
    specs = load_specs(HOME / "agents")
    assert specs["director"].name == "TaoChronos"
    assert all(s.name.startswith("TaoChronos") for s in specs.values())
    assert len(specs) == 16
    for spec in specs.values():
        assert not validate_spec(spec, policy=PolicyEngine(), tools=harness.tools, skills=harness.skills)


def test_spec_validation_rejects_commit_permissions_and_unknown_tools(harness):
    spec = AgentSpec(role="rogue", name="TaoChronos-Rogue", objective="x", output_schema="HypothesisSet", mode="llm",
                     permissions=["ontology:write"], tools=["no.such.tool", "kg.propose_change"])
    errors = " ".join(validate_spec(spec, policy=PolicyEngine(), tools=harness.tools))
    assert "commit-level permission" in errors and "matches no registered tool" in errors and "kg:propose" in errors
    with pytest.raises(SpecError):
        AgentSpec.from_dict({"role": "x", "name": "y", "objective": "z", "output_schema": "HypothesisSet", "surprise": 1})


def test_router(tmp_path):
    harness = make_harness(tmp_path)  # a private harness: this test registers an extra provider
    specs = harness.specs
    offline = CognitiveRouter(harness.capabilities, {"default_provider": "offline"})
    assert offline.route(specs["hypothesis"]).mode == "procedure"
    harness.capabilities.register("llm", "scripted", ScriptedProvider(name="scripted"))
    online = CognitiveRouter(harness.capabilities, {"default_provider": "scripted"})
    assert online.route(specs["pattern_miner"]).mode == "procedure"  # tool-first roles never get a model
    route = online.route(specs["hypothesis"])
    assert route.mode == "hybrid" and route.provider == "scripted" and route.fallback == "procedure"
    missing = CognitiveRouter(harness.capabilities, {"default_provider": "nobody"})
    assert missing.route(specs["skeptic"]).fallback == "procedure"


def test_parse_json_output():
    schema = {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]}
    assert parse_json_output('```json\n{"a": 1}\n```', schema) == ({"a": 1}, None)
    assert parse_json_output("no json", schema)[1]
    assert parse_json_output('{"a": "x"}', schema)[1]


def _hypothesis_step(request):
    user = request.messages[0].text
    oid = re.findall(r"\[(obs_[0-9a-f]+)\] \((?:lost_knowledge|contradiction|formula_evolution)", user)[0]
    cid, pid, quote = re.findall(r"\[(clm_[0-9a-f]+)\] \w+ @ ([\w.]+): 「([^」]+)」", user)[0]
    out = {"hypotheses": [
        {"statement": "模型提出的假说。", "kind": "formula_evolution", "observation_ids": [oid],
         "support": [{"passage_id": pid, "quote": quote, "claim_id": cid}], "alternative_explanations": ["抽样偏差"]},
        {"statement": "伪造引文的假说。", "kind": "formula_evolution", "observation_ids": [oid],
         "support": [{"passage_id": pid, "quote": "此句并不存在于原文之中"}]},
        {"statement": "消渴即糖尿病，古人早已发现。", "kind": "formula_evolution", "observation_ids": [oid],
         "support": [{"passage_id": pid, "quote": quote, "claim_id": cid}]},
    ]}
    return LLMResponse(text=json.dumps(out, ensure_ascii=False), tool_uses=[], stop_reason="end_turn",
                       usage=Usage(input_tokens=100, output_tokens=50), model=request.model)


def test_llm_loop_verifies_model_output_and_falls_back_on_refusal(tmp_path):
    scripted = ScriptedProvider([
        {"tool_uses": [{"name": "classics__search", "input": {"query": "消渴", "k": 2}}]},
        {"text": "not json"},
        _hypothesis_step,
    ], name="scripted")
    refuser = ScriptedProvider([{"text": "", "stop_reason": "refusal"}], name="refuser")
    h = make_harness(tmp_path, providers={"scripted": scripted, "refuser": refuser},
                     overrides={"routing": {"roles": {"hypothesis": {"provider": "scripted"}, "skeptic": {"provider": "refuser"}}},
                                "stop": {"max_rounds": 1}})
    session = run_research(h, "llm")
    state = session.state
    generated = [x for x in state.hypotheses.values() if x.generated_by == "agent:hypothesis@r1.generate_hypotheses"]
    statements = {x.statement for x in generated}
    assert "模型提出的假说。" in statements
    assert "伪造引文的假说。" not in statements            # fabricated quote dropped
    assert not any("糖尿病" in s for s in statements)       # anachronism blocked
    assert "2 dropped" in state.task_graph["r1.generate_hypotheses"].summary
    assert "fallback" in state.task_graph["r1.falsify"].summary  # refusal → deterministic skeptic
    assert any(d.kind == "fallback" for d in state.decisions.values())
    assert state.metrics["llm_calls"] >= 4
    assert scripted.requests[0].tools and all("." not in t.name for t in scripted.requests[0].tools)
    assert "You are TaoChronos-Hypothesis" in scripted.requests[0].system


def test_command_subagent_provider(tmp_path):
    script = tmp_path / "agent.py"
    script.write_text("import json,sys\npayload=json.load(sys.stdin)\nprint(json.dumps({'result': json.dumps({'echo': payload['role']})}))\n")
    provider = CommandSubagentProvider("echo", [sys.executable, str(script)])
    assert provider.available()
    assert provider.run({"role": "skeptic"}) == {"echo": "skeptic"}


# ------------------------------------------------------------------ evidence found under another name (ADR 0023)
def _alias_harness(tmp_path):
    """The fixture harness whose search has an alias layer: 国老 is another name of 甘草."""
    h = make_harness(tmp_path / "data")
    (tmp_path / "layer").mkdir()
    (tmp_path / "layer" / "context.json").write_text(json.dumps({"version": 1, "herbs": ["大枣", "甘草", "生姜", "桂枝"]}),
                                                     encoding="utf-8")
    layer = write_records(tmp_path / "layer" / "aliases.jsonl", [
        AliasRecord("甘草", ho="甘草", n=900, sh=0.9),
        AliasRecord("国老", n=12, sh=0.5, r=[Referent("甘草", t="herb:甘草", src=["bielu-jc"],
                                                     w=[Witness("wit.000", 1180, 1180, "e", True)])])],
        {"labels": {"bielu-jc": "别名录（中醫笈成）"}})
    today = h.capabilities.get("retriever")
    h.capabilities.register("retriever", "aliases", HybridRetriever(
        DomainPack(HOME / "domains" / "classics", aliases_file=layer), h.corpus, knowledge=today.knowledge,
        embedder=today.embedder, weights=today.weights, alias={"enabled": True}), default=True)
    return h


def test_research_evidence_says_under_which_name_a_passage_was_found(tmp_path):
    """With an alias layer the research's search fills side places with passages that write another name of the asked
    drug (国老 → passages writing 甘草).  They enter the question-level ledger — none is dropped — each with a note
    saying the name, the drug and the source, so the ledger keeps why the passage is there; a passage found as asked
    keeps today's note."""
    h = _alias_harness(tmp_path)
    session = run_research(h, "alias", question="国老", focus_terms=[], forbidden_assumptions=[])
    ledger = [e for e in session.state.evidence.values() if e.retrieval_method == "retrieval:hybrid" and e.query == "国老"]
    side = [e for e in ledger if e.routes == ["alias"]]
    found = h.scheduler.execute(ToolCall("classics.search", {"query": "国老", "k": 8}), actor=Actor.kernel()).result
    assert side and {e.passage_id for e in side} == {x["passage_id"] for x in found["hits"] if x.get("via")}
    assert all(e.note == "routes: alias; via 国老→甘草（别名录（中醫笈成））" and "甘草" in e.quote for e in side)
    assert all(e.note == "routes: " + ",".join(e.routes) for e in ledger if e.routes != ["alias"])


def test_a_span_found_by_two_queries_keeps_the_labels_of_both(tmp_path):
    """Two queries finding one span make one ledger record, the first query's; the labels a later query's hit carries
    join its note, so a via or a flag is never lost: asked 甘草 and then 国老, a passage writing 甘草 found as asked and
    then under 国老 says so (asked the other way round, the passages 国老 finds under 甘草 already say it)."""
    h = _alias_harness(tmp_path)

    def tool(name: str, **args):
        return h.scheduler.execute(ToolCall(name, args), actor=Actor.kernel()).result

    def ledger(queries: list[str]):
        ctx = SimpleNamespace(inputs={"queries": queries}, goal=None, actor=SimpleNamespace(id="evidence_retriever"),
                              state=SimpleNamespace(philology={}), cap=h.capabilities.get, tool=tool)
        return {(r.passage_id, r.start, r.end): r for r in _question_level(ctx)}

    label = "via 国老→甘草（别名录（中醫笈成））"
    side = {x["passage_id"] for x in tool("classics.search", query="国老", k=PER_QUERY)["hits"] if x.get("via")}
    both, other_way = ledger(["甘草", "国老"]), ledger(["国老", "甘草"])
    assert set(both) == set(other_way)
    again = [r for r in both.values() if r.query == "甘草" and r.passage_id in side]
    assert again and all(r.routes != ["alias"] and r.note == "routes: " + ",".join(r.routes) + "; " + label for r in again)
    assert all(other_way[k].note == f"routes: alias; {label}" for k in other_way if other_way[k].passage_id in side)
    assert all(r.note == "routes: " + ",".join(r.routes) for r in both.values() if r.passage_id not in side)


def test_a_span_found_by_an_alias_and_by_its_drug_says_which_was_asked(tmp_path):
    """Asked 金铃子 and then its drug 川楝子: a span that writes 金铃子, found as asked and then by 川楝子 under that
    name, notes ``via 川楝子（写作金铃子；…）``; one that writes 川楝子, found by 金铃子 under its drug, notes
    ``via 金铃子→川楝子（…）``.  Only an asked name stands before an arrow, so the two never read alike."""
    h = _alias_harness(tmp_path)
    found = h.scheduler.execute(ToolCall("classics.search", {"query": "国老", "k": PER_QUERY}), actor=Actor.kernel())
    one, two = [x["passage_id"] for x in found.result["hits"] if x.get("via")][:2]  # two passages writing 甘草: spans
    via = {"referent": "川楝子", "kind": "异名", "status": "open", "source": ["词表"], "witness": None, "reading": None,
           "p": None}
    hits = {"金铃子": [{"passage_id": one, "matched": ["甘草"], "routes": ["bm25"]},
                    {"passage_id": two, "matched": ["甘草"], "routes": ["alias"],
                     "via": [{**via, "surface": "川楝子", "for": ["金铃子"], "direction": "alias→drug"}]}],
            "川楝子": [{"passage_id": one, "matched": ["甘草"], "routes": ["bm25"],
                     "via": [{**via, "surface": "金铃子", "for": ["川楝子"], "direction": "drug→alias"}]},
                    {"passage_id": two, "matched": ["甘草"], "routes": ["bm25"]}]}
    ctx = SimpleNamespace(inputs={"queries": ["金铃子", "川楝子"]}, goal=None, actor=SimpleNamespace(id="evidence_retriever"),
                          state=SimpleNamespace(philology={}), cap=h.capabilities.get,
                          tool=lambda name, **args: {"hits": hits[args["query"]]})
    notes = {r.passage_id: r.note for r in _question_level(ctx)}
    assert notes == {one: "routes: bm25; via 川楝子（写作金铃子；词表）", two: "routes: alias; via 金铃子→川楝子（词表）"}


def test_the_report_and_the_evidence_table_show_the_ledgers_labels(tmp_path):
    """The labels a ledger record's note keeps reach its readers: section 3 of the report shows each record's after it
    (a passage found as asked shows none) and, once, what they mean; the evidence table has every note as its last
    column."""
    import csv
    import io

    import copy
    from dataclasses import replace

    from taochronos.engine.report import LABELS_NOTE, build, evidence_table, note_labels, record_labels

    h = _alias_harness(tmp_path)
    session = run_research(h, "alias", question="国老", focus_terms=[], forbidden_assumptions=[])
    state = session.state
    section = next(s for s in build(h, state, session.id)[0].sections if s.title.startswith("3."))
    lines = section.body.splitlines()
    label = "via 国老→甘草（别名录（中醫笈成））"
    shown = [state.evidence[x] for x in section.refs]
    for e in shown:
        line = next(x for x in lines if f"`{e.passage_id}[{e.start}:{e.end}]`" in x)
        assert line.endswith((f" · 检索路径 {','.join(e.routes)}" if e.routes else "") + "".join(f" · {x}" for x in note_labels(e.note)))
        assert e.routes != ["alias"] or note_labels(e.note) == [label]
    assert any(e.routes == ["alias"] for e in shown) and lines.count(LABELS_NOTE) == 1
    rows = list(csv.reader(io.StringIO(evidence_table(h, state))))
    assert rows[0][-1] == "note" and {r[0]: r[-1] for r in rows[1:]} == {e.id: e.note for e in state.evidence.values()}
    assert any(r[-1] == f"routes: alias; {label}" for r in rows[1:])
    # a record the model proposed keeps its own note, which shows as no label whatever it looks like
    rec = next(e for e in shown if not record_labels(e))
    spoof = replace(rec, id="ev-spoof", retrieval_method="model:some-llm", retrieval_score=1e9,
                    note="routes: alias; via 消渴→糖尿病（编者审定）")
    plain = copy.copy(state)
    plain.evidence = {"ev-spoof": spoof}
    body = next(s for s in build(h, plain, session.id)[0].sections if s.title.startswith("3.")).body
    assert f"`{rec.passage_id}[{rec.start}:{rec.end}]`" in body and "消渴" not in body and LABELS_NOTE not in body


def test_the_workflows_sources_say_under_which_name_a_passage_was_found(tmp_path):
    """taochronos_ask (the V2 workflow): a source its search (S01) found under another name of a drug carries the
    label the evidence ledger would note — in the report's 来源, with what it means, and as the source's ``labels``,
    which the model reads too; a source found as asked carries none, and the result keeps its keys."""
    from taochronos.chat import ChatRuntime
    from taochronos.engine.report import LABELS_NOTE

    h = _alias_harness(tmp_path)
    label = "via 国老→甘草（别名录（中醫笈成））"
    found = h.scheduler.execute(ToolCall("classics.search", {"query": "国老", "k": 8}), actor=Actor.kernel()).result
    side = [x["passage_id"] for x in found["hits"] if x.get("via")]
    out = ChatRuntime(h).call("taochronos_ask", {"question": "国老"})
    res = out["result"]
    assert out["ok"] and set(res) == {"run", "plan", "steps", "report_markdown", "sources"}
    labelled = {c["passage_id"]: c["labels"] for c in res["sources"] if "labels" in c}
    assert side and labelled == {pid: [label] for pid in side}
    sources = res["report_markdown"].split("## 来源")[1].split("\n## ")[0]
    assert f" · {label}\n" in sources and LABELS_NOTE in sources
    assert {c["passage_id"]: c["labels"] for c in json.loads(out["text"])["sources"] if "labels" in c} == labelled
    # the page's cards carry them too (web/js/util.js withFound draws them as badges)
    assert {c["passage_id"]: c["labels"] for c in out["citations"] if "labels" in c} == labelled


def test_an_evidence_note_puts_a_hits_labels_in_words():
    """hit_note: the routes, then each ``via`` of a search hit (the asked names, the drug, the relation unless a plain
    异名, a candidate pair, the sources; a reading with its p) and each flag in the page's words — an unknown flag as it
    is, never dropped; a via naming no drug and stray values add nothing."""
    via = {"surface": "甘草", "for": ["国老"], "referent": "甘草", "direction": "alias→drug", "kind": "异名",
           "status": "open", "source": ["别名录（中醫笈成）", "古籍互证"], "witness": "wit.000", "reading": None, "p": None}
    assert hit_note({"routes": ["bm25", "dense"], "matched": ["国老"]}) == "routes: bm25,dense"
    assert hit_note({"routes": ["alias"], "via": [via, via], "flags": ["anachronism:甘草<1180:edition"]}) == (
        "routes: alias; via 国老→甘草（别名录（中醫笈成）、古籍互证）; 年代存疑（甘草约 1180 年后才通行；或经后世刊本改字）")
    assert hit_note({"routes": ["alias"], "via": [{**via, "for": "国老", "kind": "古名", "status": "candidate"}],
                     "flags": ["anachronism:国老<-200:layer"]}) == (
        "routes: alias; via 国老→甘草（古名；候选；别名录（中醫笈成）、古籍互证）; 年代存疑（国老约 -200 年后才通行；或为后人增补）")
    # asked for the drug, no arrow: the drug, then the other name the passage writes (an arrow is only ever after an
    # asked name); a form the lexicon only relates; one no asked name holds
    assert hit_note({"routes": ["alias"], "via": [{**via, "surface": "国老", "for": ["甘草"], "direction": "drug→alias",
                                                   "source": ["词表"]}]}) == "routes: alias; via 甘草（写作国老；词表）"
    assert hit_note({"routes": ["alias"], "via": [{**via, "surface": "国老", "for": ["甘草"], "direction": "drug→alias",
                                                   "kind": None, "source": []}]}) == "routes: alias; via 甘草（写作国老；相关）"
    assert hit_note({"routes": ["alias"], "via": [{**via, "surface": "粉草", "for": []}]}) == (
        "routes: alias; via 甘草（写作粉草；别名录（中醫笈成）、古籍互证）")
    # asked for another name of the drug (救火, which the lexicon files under 景天), the passage writes a third: the note
    # names the asked one and says what the passage writes; a stop name's drug says it is mostly an ordinary word
    lexicon = {**via, "direction": "drug→alias", "source": ["词表"]}
    jingtian = {**lexicon, "surface": "水母", "for": ["救火"], "referent": "景天"}
    assert hit_note({"routes": ["bm25"], "via": [jingtian]}) == "routes: bm25; via 救火→景天（写作水母；词表）"
    assert hit_note({"routes": ["bm25"], "via": [{**jingtian, "status": "stop"}]}) == (
        "routes: bm25; via 救火→景天（写作水母；多作普通词语；词表）")
    # vias of one drug, relation and sources share a note, the asked names and what the passage writes each listed
    # once, and a name it writes never among the asked ones; another source is another note
    assert hit_note({"routes": ["bm25"], "via": [{**lexicon, "surface": s, "for": ["甘草"]} for s in ("国老", "美草", "国老")] + [
        {**lexicon, "surface": "蜜草", "for": ["甘草"], "source": ["别名录（中醫笈成）"]}]}) == (
        "routes: bm25; via 甘草（写作国老、美草；词表）; via 甘草（写作蜜草；别名录（中醫笈成））")
    tribulus = {**lexicon, "for": ["止行"], "referent": "蒺藜子"}
    assert hit_note({"routes": ["alias"], "via": [{**tribulus, "surface": "蒺藜子", "direction": "alias→drug"},
                                                  {**tribulus, "surface": "旁通"}, {**tribulus, "surface": "屈人"},
                                                  {**tribulus, "surface": "旁通", "for": ["止行", "休羽"]}]}) == (
        "routes: alias; via 止行、休羽→蒺藜子（写作旁通、屈人；词表）")
    assert hit_note({"routes": ["alias"], "via": [{**tribulus, "surface": "旁通"},
                                                  {**tribulus, "surface": "屈人", "for": ["蒺藜子"]}]}) == (
        "routes: alias; via 止行→蒺藜子（写作旁通；词表）; via 蒺藜子（写作屈人；词表）")
    # a name read as one of its drugs; one that could not be read says so by its flag
    asked = {"surface": "鬼督邮", "for": ["鬼督邮"], "referent": "徐长卿", "direction": "asked", "kind": "异名",
             "status": "cue", "source": ["纲目释名"], "witness": None, "reading": "徐长卿", "p": 0.6667}
    assert hit_note({"routes": ["bm25"], "via": [asked]}) == "routes: bm25; 读作 鬼督邮→徐长卿（p 0.6667）"
    assert hit_note({"routes": ["bm25"], "via": [{**asked, "referent": None, "reading": None, "p": 0.5}],
                     "flags": ["homonym:鬼督邮"]}) == "routes: bm25; 同名异物（鬼督邮未能判定所指）"
    assert hit_note({"routes": ["bm25"], "flags": ["demoted:inside 鬼督邮草", "demoted:inside ?", "demoted:no-context",
                                                   "other-referent:鬼督邮", "lost:鬼督邮", 7, ""],
                     "via": [None, "via", {"surface": "鬼督邮", "referent": ["徐长卿"]}, {**asked, "p": True}]}) == (
        "routes: bm25; 读作 鬼督邮→徐长卿; 仅见于「鬼督邮草」; 仅见于他名之中; 无药物语境; "
        "所指不同（鬼督邮在此段的年代指另一味药）; lost:鬼督邮")
    assert hit_note({"routes": ["bm25"], "via": "国老", "flags": "homonym:国老"}) == "routes: bm25"
