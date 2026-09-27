"""TaoChronos V2 runtime: skills with manifests, four core agents, a workflow compiled from a question, run as a DAG.

* **Skill manifests** (``skills/manifests/S01.yaml`` … ``S15.yaml``): id, version, owner, inputs, outputs, dependencies,
  whether a model is needed, the deterministic and model steps, the tool calls the skill makes, validators, evaluation.
* **Core agents** (``agents/core/*.yaml``): the Research Orchestrator, the Classical TCM Scholar, the Translational
  Medicine Agent and the Evidence & Critic Agent — each owns skills, acts with its own permissions (the kernel's policy
  checks every tool call) and delegates to the specialist roles of the research engine.
* **Workflow compiler**: the question's intents (rules over its words: 版本, 演变, 现代, 证据, 真实世界 …) select skills;
  dependencies are closed over; S01 (sources) opens every plan and S15 (audit) closes it.  A model may propose a plan
  too — only known skills, never without S01 and S15 — and it is validated against the registry before it is used.
* **Executor**: runs the DAG in order through the tool scheduler; each call's result is an artifact in the run's
  workspace (``<data>/workspaces/<run>/``) keyed by the hash of its skill version, tool and arguments, so a run resumes
  where it stopped and a step already done is read, not redone.  Before S15 the Orchestrator composes the answer's
  statements from the artifacts; S15 audits each of them; the report shows every statement with its verdict.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..kernel import Actor, ToolCall
from ..protocol.yamlio import load_yaml

REQUIRED_SKILLS = ("S01", "S15")
INTENTS: dict[str, tuple[str, ...]] = {
    # skill: the words of a question that call for it
    "S03": ("句读", "训诂", "释义", "字义", "今译", "翻译", "何意", "含义", "注家", "怎么读", "读法"),
    "S04": ("条文", "结构", "方证", "主之", "证候"),
    "S05": ("异文", "版本", "校勘", "传本", "底本", "善本"),
    "S06": ("引用", "引文", "互见", "传承", "转引", "流传", "传播"),
    "S07": ("实体", "方剂", "药物", "组成", "症状", "主治", "功效"),
    "S08": ("名称", "异名", "别名", "规范", "同物异名", "避讳"),
    "S09": ("演变", "历代", "变化", "源流", "沿革", "古今", "以前", "以后", "明清", "唐宋", "宋代", "汉代", "概念"),
    "S10": ("现代", "西医", "对应", "相当", "疾病", "表型", "临床", "转译", "今病", "糖尿病", "卒中", "疟疾"),
    "S13": ("现代研究", "证据", "临床试验", "药理", "疗效", "机制", "研究进展", "文献"),
    "S14": ("真实世界", "队列", "数据库", "OMOP", "患者中", "发生率", "风险"),
}


@dataclass
class SkillManifest:
    id: str
    key: str
    name: str
    version: str
    owner: str
    description: str
    inputs: list[str]
    outputs: list[str]
    dependencies: list[str]
    requires_llm: str
    deterministic_steps: list[str]
    llm_steps: list[str]
    calls: list[dict[str, Any]]
    validators: list[str]
    evaluation: dict[str, Any]
    path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if k != "path"}


@dataclass
class CoreAgent:
    id: str
    name: str
    description: str
    skills: list[str]
    delegates: list[str]
    permissions: list[str]
    outputs: list[str] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)

    def actor(self) -> Actor:
        return Actor(id=f"core:{self.id}", role=self.id, principal="agent", permissions=frozenset(self.permissions), name=self.name)


def load_manifests(root: str | Path) -> dict[str, SkillManifest]:
    out: dict[str, SkillManifest] = {}
    for path in sorted(Path(root).glob("S*.yaml")):
        d = load_yaml(path) or {}
        m = SkillManifest(id=d["id"], key=d["key"], name=d["name"], version=str(d["version"]), owner=d["owner"],
                          description=d.get("description", ""), inputs=list(d.get("inputs", [])), outputs=list(d.get("outputs", [])),
                          dependencies=list(d.get("dependencies", [])), requires_llm=d.get("requires_llm", "none"),
                          deterministic_steps=list(d.get("deterministic_steps", [])), llm_steps=list(d.get("llm_steps", [])),
                          calls=list(d.get("calls", [])), validators=list(d.get("validators", [])),
                          evaluation=dict(d.get("evaluation") or {}), path=str(path))
        out[m.id] = m
    return out


def load_core_agents(root: str | Path) -> dict[str, CoreAgent]:
    out: dict[str, CoreAgent] = {}
    for path in sorted(Path(root).glob("*.yaml")):
        d = load_yaml(path) or {}
        out[d["id"]] = CoreAgent(id=d["id"], name=d["name"], description=str(d.get("description", "")).strip(),
                                 skills=list(d.get("skills", [])), delegates=list(d.get("delegates", [])),
                                 permissions=list(d.get("permissions", [])), outputs=list(d.get("outputs", [])),
                                 rules=list(d.get("rules", [])))
    return out


def validate_registry(skills: dict[str, SkillManifest], agents: dict[str, CoreAgent], tools: Any, roles: set[str]) -> list[str]:
    """Every skill owned by an agent that lists it, depending on known skills, calling known tools the owner may call;
    every delegate a specialist role of the research engine; no commit permissions."""
    errors: list[str] = []
    for m in skills.values():
        owner = agents.get(m.owner)
        if owner is None:
            errors.append(f"{m.id}: owner {m.owner!r} is not a core agent")
        elif m.id not in owner.skills:
            errors.append(f"{m.id}: its owner {m.owner} does not list it")
        for dep in m.dependencies:
            if dep not in skills:
                errors.append(f"{m.id}: unknown dependency {dep}")
        if m.requires_llm not in ("none", "optional", "required"):
            errors.append(f"{m.id}: requires_llm must be none, optional or required")
        for call in m.calls:
            try:
                spec = tools.get(call["tool"])
            except KeyError:
                errors.append(f"{m.id}: unknown tool {call['tool']}")
                continue
            if owner is not None and spec.permission not in owner.permissions:
                errors.append(f"{m.id}: {m.owner} lacks {spec.permission} for {call['tool']}")
    for a in agents.values():
        for s in a.skills:
            if s not in skills and s not in ("plan", "synthesize"):
                errors.append(f"{a.id}: unknown skill {s}")
        for r in a.delegates:
            if r not in roles:
                errors.append(f"{a.id}: delegate {r!r} is not a specialist role")
        if any(p.endswith(":commit") or p == "kg:commit" for p in a.permissions):
            errors.append(f"{a.id}: core agents never hold commit permissions")
    for dep_cycle in _cycles(skills):
        errors.append("dependency cycle: " + " → ".join(dep_cycle))
    return errors


def _cycles(skills: dict[str, SkillManifest]) -> list[list[str]]:
    out, state = [], {}

    def visit(n: str, path: list[str]) -> None:
        state[n] = 1
        for d in skills[n].dependencies:
            if d not in skills:
                continue
            if state.get(d) == 1:
                out.append([*path, n, d])
            elif state.get(d) is None:
                visit(d, [*path, n])
        state[n] = 2

    for n in skills:
        if state.get(n) is None:
            visit(n, [])
    return out


# ---------------------------------------------------------------- compiling a question
@dataclass
class Plan:
    question: str
    skills: list[str]
    reasons: dict[str, str]
    edges: list[tuple[str, str]]
    context: dict[str, Any]
    by: str = "rules"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"question": self.question, "skills": self.skills, "reasons": self.reasons, "edges": [list(e) for e in self.edges],
                "context": self.context, "by": self.by, "notes": self.notes}

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


class WorkflowCompiler:
    def __init__(self, skills: dict[str, SkillManifest], harness: Any) -> None:
        self.skills = skills
        self.harness = harness

    def context(self, question: str, *, page: str | None = None) -> dict[str, Any]:
        """What a question names: historical terms, drugs and formulas, modern diseases."""
        pack = self.harness.pack
        terms: list[str] = []
        for t, ht in getattr(pack.terminology, "terms", {}).items():
            if t in question and t not in terms and ht.category in ("disease", "symptom", "sign", "pattern", "disease_class", "pathology"):
                terms.append(t)
        drugs: list[str] = []
        for m in pack.lexicon.match(question):
            if m.category in ("herb", "formula") and m.surface not in drugs:
                drugs.append(m.surface)
            elif m.category in ("disease", "symptom", "pattern") and m.surface not in terms:
                terms.append(m.surface)
        caps = self.harness.capabilities
        if caps.has("modern"):
            for n in caps.get("modern").names_in(question)["drugs"]:
                if n not in drugs and not any(n in d for d in drugs):
                    drugs.append(n)
        diseases: list[str] = []
        if caps.has("bridge"):
            for d in caps.get("bridge").data.diseases.values():
                if d.label.split("（")[0] in question or d.en.lower() in question.lower():
                    diseases.append(d.id)
            if "糖尿病" in question and "diabetes_mellitus" not in diseases:
                diseases.append("diabetes_mellitus")
        return {"question": question, "terms": terms[:4], "drugs": drugs[:3], "diseases": diseases[:2],
                **({"page": page} if page else {})}

    def plan(self, question: str, *, page: str | None = None, judge: Any = None) -> Plan:
        ctx = self.context(question, page=page)
        chosen: dict[str, str] = {"S01": "every answer starts from its sources", "S15": "every answer is audited"}
        for sid, words in INTENTS.items():
            hit = next((w for w in words if w in question), None)
            if hit:
                chosen[sid] = f"the question says 「{hit}」"
        if ctx["diseases"]:
            chosen.setdefault("S10", "the question names a modern disease: " + "、".join(ctx["diseases"]))
        if "S10" in chosen:
            chosen.setdefault("S11", "projection of the findings (the mapping needs it)")
            chosen.setdefault("S12", "the resemblance to modern profiles")
        if "S13" in chosen and not ctx["drugs"]:
            chosen.pop("S13")
            note = "S13 dropped: the question names no drug or formula to search the modern literature for"
        else:
            note = ""
        if ctx["drugs"] and "S10" in chosen and "S13" not in chosen:
            chosen["S13"] = "a drug and a modern disease are named: what modern studies exist"
        if ctx["terms"] and not ({"S08", "S09"} & set(chosen)):
            chosen["S09"] = "the question names historical terms: their use over time"
        if page:
            chosen["S02"] = "a page image or OCR output is given"
        by, notes = "rules", [note] if note else []
        if judge is not None:
            proposal = self._model_plan(question, ctx, judge)
            if proposal is not None:
                added = [s for s in proposal if s not in chosen]
                dropped = [s for s in list(chosen) if s not in proposal and s not in REQUIRED_SKILLS]
                for s in added:
                    chosen[s] = "proposed by the model"
                for s in dropped:
                    chosen.pop(s)
                by = "rules+model"
                notes.append(f"model added {added or 'none'}, dropped {dropped or 'none'}")
        # close over dependencies
        changed = True
        while changed:
            changed = False
            for sid in list(chosen):
                for dep in self.skills[sid].dependencies:
                    if dep not in chosen:
                        chosen[dep] = f"needed by {sid}"
                        changed = True
        order = self._order(list(chosen))
        edges = [(d, s) for s in order for d in self.skills[s].dependencies if d in chosen]
        edges += [(s, "S15") for s in order if s != "S15" and not any(e[0] == s for e in edges)]
        return Plan(question, order, {s: chosen[s] for s in order}, edges, ctx, by, notes)

    def _order(self, ids: list[str]) -> list[str]:
        done: list[str] = []
        pending = sorted(ids, key=lambda s: int(s[1:]))
        while pending:
            for s in pending:
                if all(d in done or d not in ids for d in self.skills[s].dependencies) and (s != "S15" or len(pending) == 1):
                    done.append(s)
                    pending.remove(s)
                    break
            else:
                raise ValueError(f"cannot order {pending}")
        return done

    def _model_plan(self, question: str, ctx: dict[str, Any], judge: Any) -> list[str] | None:
        catalogue = "\n".join(f"{m.id} {m.name}: {m.description}" for m in self.skills.values())
        schema = {"type": "object", "required": ["skills"], "properties": {"skills": {"type": "array", "items": {"enum": list(self.skills)}}}}
        res = judge.ask("workflow.plan", "你是研究编排者：为问题选择所需的技能；只能从目录中选。",
                        f"问题：{question}\n已识别：{json.dumps(ctx, ensure_ascii=False)}\n技能目录：\n{catalogue}\n"
                        '答 {"skills": ["S01", …]}（S01 与 S15 必选）', schema=schema)
        if not res.ok:
            return None
        return list(dict.fromkeys([*REQUIRED_SKILLS, *res.data["skills"]]))


# ---------------------------------------------------------------- running a plan
class Executor:
    def __init__(self, harness: Any, skills: dict[str, SkillManifest], agents: dict[str, CoreAgent], root: str | Path) -> None:
        self.harness = harness
        self.skills = skills
        self.agents = agents
        self.root = Path(root)

    def run(self, plan: Plan, *, run_id: str | None = None, resume: bool = True) -> dict[str, Any]:
        run_id = run_id or f"run-{plan.digest()}"
        ws = self.root / run_id
        (ws / "steps").mkdir(parents=True, exist_ok=True)
        (ws / "plan.json").write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
        ctx: dict[str, Any] = dict(plan.context)
        steps: list[dict[str, Any]] = []
        for sid in plan.skills:
            m = self.skills[sid]
            if sid == "S15":
                ctx["statements"] = compose_statements(steps, ctx)
            steps.append(self._skill(m, ctx, ws, resume))
        manifest = {"run": run_id, "question": plan.question, "plan": plan.digest(), "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "steps": [{k: s[k] for k in ("skill", "status", "calls", "cached", "agent")} for s in steps]}
        (ws / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
        return {"run": run_id, "workspace": str(ws), "plan": plan.to_dict(), "steps": steps, "context": ctx}

    def _skill(self, m: SkillManifest, ctx: dict[str, Any], ws: Path, resume: bool) -> dict[str, Any]:
        agent = self.agents[m.owner]
        actor = agent.actor()
        out: dict[str, Any] = {"skill": m.id, "name": m.name, "agent": agent.id, "calls": 0, "cached": 0, "status": "ok",
                               "results": [], "errors": []}
        for call in m.calls:
            if call.get("when") and not ctx.get(call["when"]):
                out["status"] = "skipped"
                out["errors"].append(f"no {call['when']} given")
                continue
            items = _items(ctx, call.get("for_each"))[: int(call.get("limit", 99))]
            if call.get("for_each") and not items:
                out["errors"].append(f"nothing to run {call['tool']} on (no {call['for_each']})")
                continue
            for item in items or [None]:
                args = _fill(call.get("args", {}), ctx, item)
                key = hashlib.sha256(json.dumps([m.id, m.version, call["tool"], args], ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]
                path = ws / "steps" / f"{m.id}-{key}.json"
                if resume and path.exists():
                    rec = json.loads(path.read_text(encoding="utf-8"))
                    out["cached"] += 1
                else:
                    t0 = time.monotonic()
                    res = self.harness.scheduler.execute(ToolCall(call["tool"], args), actor=actor)
                    rec = {"skill": m.id, "tool": call["tool"], "args": args, "ok": res.ok, "result": res.result if res.ok else None,
                           "error": res.error, "seconds": round(time.monotonic() - t0, 3)}
                    path.write_text(json.dumps(rec, ensure_ascii=False, default=str), encoding="utf-8")
                out["calls"] += 1
                if not rec["ok"]:
                    out["errors"].append(f"{call['tool']}: {rec['error']}")
                    continue
                out["results"].append({"tool": call["tool"], "args": args, "result": rec["result"], "artifact": path.name})
                if call.get("collect") == "passages":
                    hits = (rec["result"] or {}).get("hits", [])
                    ctx["passages"] = [{"passage_id": h.get("passage_id") or h.get("id"),
                                        "locator": (f"《{h['title']}》" if h.get("title") else "") + (h.get("locator") or ""),
                                        "period": h.get("period"), "quote": (h.get("quote") or h.get("text") or "")[:120]}
                                       for h in hits if h.get("passage_id") or h.get("id")]
        if out["calls"] and not out["results"]:
            out["status"] = "failed"
        elif out["errors"] and out["status"] == "ok" and not out["results"]:
            out["status"] = "skipped"
        return out


def _items(ctx: dict[str, Any], key: str | None) -> list[Any]:
    if not key:
        return []
    return list(ctx.get(key) or [])


def _fill(args: dict[str, Any], ctx: dict[str, Any], item: Any) -> dict[str, Any]:
    names = {**{k: v for k, v in ctx.items() if isinstance(v, (str, int, float))},
             "disease0": (ctx.get("diseases") or [None])[0]}
    if isinstance(item, dict):
        names.update({k: v for k, v in item.items() if isinstance(v, (str, int, float))})
    elif item is not None:
        for singular in ("term", "drug", "disease", "statement", "passage_id"):
            names[singular] = item
    out = {}
    for k, v in args.items():
        if isinstance(v, str):
            m = re.fullmatch(r"\{(\w+)\}", v)
            if m:
                val = names.get(m.group(1))
                if val is None:
                    continue
                out[k] = val
            else:
                out[k] = v.format(**{k2: v2 for k2, v2 in names.items() if v2 is not None})
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------- the answer
def compose_statements(steps: list[dict[str, Any]], ctx: dict[str, Any]) -> list[str]:
    """The answer's statements, written from the artifacts by rules: what the witnesses say (quoted), how the bridge
    reads the descriptions (its own guarded statement), what modern evidence exists (by level) — for S15 to audit."""
    out: list[str] = []
    by_skill = {s["skill"]: s for s in steps}
    for p in (ctx.get("passages") or [])[:3]:
        q = _clean_quote(p.get("quote", ""))
        loc = p.get("locator") or ""
        work = re.match(r"《([^》]+)》", loc)
        if q and work:
            out.append(f"《{work.group(1)}》载「{q}」。")
    quotes = {p["passage_id"]: _clean_quote(p.get("quote", ""), 40) for p in ctx.get("passages") or []}
    for r in [x for x in (by_skill.get("S12") or {}).get("results", []) if x["tool"] == "bridge.map"][:2]:
        lead = [c for c in r["result"].get("candidates", []) if isinstance(c, dict) and c.get("level") in ("high", "moderate", "low")]
        q = quotes.get(r["args"].get("passage_id") or "")
        if lead and q:
            names = "、".join(f"{c['label']}（{c.get('level_zh') or c['level']}）" for c in lead[:2])
            out.append(f"「{q}」所述症状在表型上与{names}相容；这是表型相似，不是回溯诊断。")
    for r in (by_skill.get("S13") or {}).get("results", [])[:1]:
        s = r["result"].get("summary", {})
        if s and s.get("by_type"):
            out.append(f"现代文献中关于{r['args'].get('subject')}的记录按研究类型为：" + "、".join(f"{k} {v}" for k, v in (s.get("by_type") or {}).items())
                       + "；这是文献分布，不是疗效结论。")
    return out


def _clean_quote(text: str, width: int = 30) -> str:
    """A verbatim stretch of a passage to quote: its first sentence, after any title it cites (《古今录验》论：…)."""
    text = re.sub(r"\s+", "", text)
    if "》" in text:
        text = text.split("》")[-1].lstrip("论曰云：:，, ")
    cut = re.split(r"[。；？！]", text)[0]
    return cut[:width].rstrip("，、：")


def render_report(run: dict[str, Any]) -> str:
    plan = run["plan"]
    lines = [f"# {plan['question']}", "", f"运行：{run['run']}（计划 {plan['by']}；工作区 {run['workspace']}）", "", "## 工作流", ""]
    for sid in plan["skills"]:
        step = next(s for s in run["steps"] if s["skill"] == sid)
        lines.append(f"- {sid} {step['name']}（{step['agent']}）：{step['status']}，{step['calls']} 次调用"
                     + (f"，{step['cached']} 次读自工作区" if step["cached"] else "") + f" — {plan['reasons'][sid]}")
    passages = run["context"].get("passages") or []
    if passages:
        lines += ["", "## 来源", ""] + [f"- {p.get('locator') or p['passage_id']}：{p.get('quote', '')[:60]}" for p in passages[:6]]
    shown: set[str] = set()
    for step in run["steps"]:
        for r in step["results"]:
            key = r["tool"] + json.dumps(r["args"], ensure_ascii=False, sort_keys=True)
            if key in shown:
                continue
            shown.add(key)
            if r["tool"] == "bridge.map":
                res = r["result"]
                lines += ["", f"## 古今映射（{r['args'].get('passage_id')}）", "", res.get("statement", "")]
                for c in (res.get("candidates") or [])[:3]:
                    if isinstance(c, dict) and "label" in c:
                        lines.append(f"- {c['label']}（ICD-10 {c.get('icd10')}）：{c.get('level')}")
            elif r["tool"] == "modern.search":
                s = r["result"].get("summary", {})
                src = r["result"].get("source")
                lines += ["", f"## 现代证据：{r['args'].get('subject')}", "",
                          (f"按类型：{s.get('by_type')}；来源：{src}" if s.get("by_type") else
                           f"未检得记录（来源：{src}；PubMed 需 --online 或 TAOCHRONOS_PUBMED=1）")]
            elif r["tool"] == "rwd.ask":
                res = r["result"]
                lines += ["", "## 真实世界数据", "", f"{res.get('arms')}；RR {res.get('risk_ratio')}；" + "；".join(res.get("caveats", []))]
    audit = next((s for s in run["steps"] if s["skill"] == "S15"), None)
    if audit:
        lines += ["", "## 陈述与审计", ""]
        for r in audit["results"]:
            if r["tool"] == "audit.claim":
                lines.append(f"- {r['result'].get('verdict')}：{r['args'].get('claim')}")
    lines += ["", "*每一陈述都经证据审计；SUPPORTED 表示本系统能做的核查通过，不等于结论为真；非临床建议。*"]
    return "\n".join(lines)


def ask(harness: Any, question: str, *, page: str | None = None, judge: Any = None, run_id: str | None = None,
        resume: bool = True, plan_only: bool = False) -> dict[str, Any]:
    home = Path(getattr(harness, "home", "."))
    skills = load_manifests(home / "skills" / "manifests")
    agents = load_core_agents(home / "agents" / "core")
    plan = WorkflowCompiler(skills, harness).plan(question, page=page, judge=judge)
    if plan_only:
        return {"plan": plan.to_dict()}
    run = Executor(harness, skills, agents, Path(harness.data_dir) / "workspaces").run(plan, run_id=run_id, resume=resume)
    report = render_report(run)
    Path(run["workspace"], "report.md").write_text(report, encoding="utf-8")
    run["report"] = report
    return run


__all__ = ["CoreAgent", "Executor", "Plan", "SkillManifest", "WorkflowCompiler", "ask", "compose_statements", "load_core_agents",
           "load_manifests", "render_report", "validate_registry"]
