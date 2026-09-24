import json
import re
import sys

import pytest

from conftest import HOME, make_harness, run_research
from taochronos.agents import AgentSpec, CognitiveRouter, SpecError, load_specs, parse_json_output, validate_spec
from taochronos.capabilities.llm import LLMResponse, Usage
from taochronos.kernel import PolicyEngine
from taochronos.plugins.models.scripted import ScriptedProvider
from taochronos.plugins.subagents import CommandSubagentProvider


def test_director_is_named_taochronos_and_all_specs_validate(harness):
    specs = load_specs(HOME / "agents")
    assert specs["director"].name == "TaoChronos"
    assert all(s.name.startswith("TaoChronos") for s in specs.values())
    assert len(specs) == 15
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
