"""V2 runtime: skill manifests, core agents, the workflow compiler and the resumable executor."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from taochronos.capabilities.judge import Judge
from taochronos.cli import main
from taochronos.engine.workflow import (Executor, SkillManifest, WorkflowCompiler, ask, load_core_agents, load_manifests,
                                        validate_registry)
from taochronos.plugins.models.scripted import ScriptedProvider

HOME = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def registry():
    return load_manifests(HOME / "skills" / "manifests"), load_core_agents(HOME / "agents" / "core")


def test_fifteen_skills_four_agents_and_a_clean_registry(registry, harness):
    skills, agents = registry
    assert sorted(skills) == [f"S{k:02d}" for k in range(1, 16)]
    assert sorted(agents) == ["classical_scholar", "critic", "orchestrator", "translational"]
    assert validate_registry(skills, agents, harness.scheduler.registry, set(harness.specs)) == []
    for m in skills.values():
        assert m.version and m.inputs and m.outputs and m.requires_llm in ("none", "optional", "required") and m.calls
        assert m.id in agents[m.owner].skills
    # a manifest calling a tool its owner may not use is refused
    bad = {**skills, "S16": SkillManifest(id="S16", key="x", name="x", version="1", owner="classical_scholar", description="",
                                          inputs=["q"], outputs=["x"], dependencies=["S01"], requires_llm="none",
                                          deterministic_steps=[], llm_steps=[], calls=[{"tool": "modern.search"}], validators=[],
                                          evaluation={})}
    errs = validate_registry(bad, agents, harness.scheduler.registry, set(harness.specs))
    assert any("S16: its owner classical_scholar does not list it" in e for e in errs)
    assert any("lacks literature:read for modern.search" in e for e in errs)


@pytest.mark.parametrize("question, needed, absent", [
    ("消渴的概念如何随时代演变？与现代糖尿病有何异同？", {"S09", "S10", "S11", "S12"}, {"S14"}),
    ("2型糖尿病患者中，使用黄连素与糖尿病肾病的关系", {"S10", "S12", "S13", "S14"}, {"S05"}),
    ("桂枝汤条文的版本异文", {"S04", "S05"}, {"S10", "S13"}),
    ("「几几」何意？注家如何训诂？", {"S03"}, {"S12"}),
])
def test_a_question_compiles_into_a_workflow(registry, harness, question, needed, absent):
    skills, _ = registry
    plan = WorkflowCompiler(skills, harness).plan(question)
    assert plan.skills[0] == "S01" and plan.skills[-1] == "S15"
    assert needed <= set(plan.skills) and not (absent & set(plan.skills))
    for a, b in plan.edges:  # dependencies come first
        assert plan.skills.index(a) < plan.skills.index(b)
    assert all(plan.reasons[s] for s in plan.skills)


def test_a_model_may_shape_the_plan_but_not_drop_sources_or_audit(registry, harness):
    skills, _ = registry
    judge = Judge(ScriptedProvider([{"text": json.dumps({"skills": ["S03", "S07"]})}]), "m")
    plan = WorkflowCompiler(skills, harness).plan("消渴的概念如何随时代演变？", judge=judge)
    assert plan.by == "rules+model" and {"S01", "S03", "S07", "S15"} <= set(plan.skills) and "S09" not in plan.skills
    bad = Judge(ScriptedProvider([{"text": json.dumps({"skills": ["S99"]})}, {"text": json.dumps({"skills": ["S99"]})}]), "m")
    fallback = WorkflowCompiler(skills, harness).plan("消渴的概念如何随时代演变？", judge=bad)
    assert fallback.by == "rules" and "S09" in fallback.skills  # an unknown skill fails validation: the rules stand


def test_a_run_is_a_workspace_of_artifacts_that_resumes(harness):
    q = "《金匮要略》肾气丸治消渴的记载与现代糖尿病有何异同？"
    run = ask(harness, q, run_id="t-resume", resume=False)
    ws = Path(run["workspace"])
    assert (ws / "plan.json").exists() and (ws / "manifest.json").exists() and (ws / "report.md").exists()
    assert len(list((ws / "steps").glob("*.json"))) >= sum(s["calls"] for s in run["steps"]) // 2
    audit = next(s for s in run["steps"] if s["skill"] == "S15")
    verdicts = [r["result"]["verdict"] for r in audit["results"] if r["tool"] == "audit.claim"]
    assert verdicts and "UNSUPPORTED" not in verdicts and verdicts.count("SUPPORTED") >= 2
    assert "## 陈述与审计" in run["report"] and "非临床建议" in run["report"]
    again = ask(harness, q, run_id="t-resume")
    assert all(s["cached"] == s["calls"] for s in again["steps"])  # every step read back from the workspace
    agents = {s["skill"]: s["agent"] for s in run["steps"]}
    assert agents["S01"] == "classical_scholar" and agents["S12"] == "translational" and agents["S15"] == "critic"


def test_each_core_agent_acts_with_its_own_permissions(registry, harness, tmp_path):
    skills, agents = registry
    narrow = {**agents}
    narrow["translational"] = type(agents["translational"])(**{**agents["translational"].__dict__, "permissions": ["kg:read"]})
    plan = WorkflowCompiler(skills, harness).plan("消渴与现代糖尿病有何异同？")
    run = Executor(harness, skills, narrow, tmp_path).run(plan, run_id="denied")
    s10 = next(s for s in run["steps"] if s["skill"] == "S10")
    assert s10["status"] == "failed" and "lacks permission 'classics:read'" in s10["errors"][0]


def test_ask_and_skills_through_the_cli(capsys, tmp_path):
    assert main(["--data", str(tmp_path), "ask", "桂枝汤条文的版本异文", "--plan-only", "--profile", "full-discovery"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["skills"][0] == "S01" and "S05" in plan["skills"]
    assert main(["--data", str(tmp_path), "skills", "--profile", "full-discovery"]) == 0
    assert "注册检查：通过" in capsys.readouterr().out
