"""What a conversational model is offered: the tool mesh as function schemas, grouped by family.

Two modes.  ``core`` offers the tools a conversation needs most often directly, and the rest through two meta-tools —
``taochronos_catalog`` (what exists, with its parameters) and ``taochronos_call`` (call any of it) — so the model's
context holds a dozen schemas, not seventy.  ``all`` offers every tool directly.  Either way the engine tools (a
discovery research run, its sessions, the V2 workflow) are offered, and two tools never are: ``kg.propose_change``
(a proposal to canonical knowledge is a human's act) and Code Mode (``research.run_code``) unless the runtime was
started with it.
"""

from __future__ import annotations

import copy
from typing import Any

FAMILIES: dict[str, dict[str, str]] = {
    "retrieval": {"label": "检索", "blurb": "全文检索（七路融合，可加时代约束）、段落原文、书目、知识谱系"},
    "study": {"label": "治学", "blurb": "方源考、药性源流、术语源流、经文互见、集注、训诂、句读、版本谱系、医案、学派、今译……"},
    "knowledge": {"label": "知识", "blurb": "主张抽取与查询、共现、术语词条（异名、避讳、义项）"},
    "analytics": {"label": "发现", "blurb": "D1 失传关联、D2 概念漂移、D3 方剂演化、D4 关联规则与隐含关联、D5 矛盾、佚书"},
    "philology": {"label": "文献", "blurb": "异体规范、校勘、页面溯源、版面理解与 OCR 核对"},
    "validation": {"label": "核验", "blurb": "引文核对、溯源链、门控、证据审计、证据图谱"},
    "bridge": {"label": "古今", "blurb": "古代表型包、HPO 映射、今病溯古（表型相似，不是回溯诊断）"},
    "literature": {"label": "现代", "blurb": "现代研究证据、有毒药物安全提示、真实世界数据（合成 OMOP）"},
    "mydata": {"label": "我的资料", "blurb": "用户上传的资料（本机读取、已脱敏）：列表、阅读、检索、描述统计、组间比较、处方用药分析"},
    "engine": {"label": "研究", "blurb": "多智能体发现研究（证据 → 假说 → 证伪 → 门控）、研究会话、V2 技能工作流"},
    "research": {"label": "代码", "blurb": "Code Mode：在隔离环境中运行调用工具的 Python 研究脚本"},
}

# offered directly in ``core`` mode: the questions a conversation asks most
CORE = [
    "classics.search", "classics.get_passage", "classics.list_books", "classics.canon",
    "kg.term", "kg.claims",
    "study.formula", "study.herb", "study.term", "study.concordance", "study.commentaries", "study.translate",
    "study.network", "study.compare", "study.usage", "study.protocol",
    "validation.verify_quote", "audit.claim", "modern.safety",
]
NEVER = {"kg.propose_change"}   # proposals to canonical knowledge are made by people, not by a chat model
CODE_MODE = "research.run_code"

S = {"type": "string"}
STRINGS = {"type": "array", "items": S}

ENGINE_TOOLS: list[dict[str, Any]] = [
    {
        "name": "taochronos_research",
        "family": "engine",
        "description": (
            "运行一次完整的多智能体发现研究（研究契约 → 证据基础 → 模式挖掘 D1–D5 → 假说 → 证伪 → 门控 G0–G8）。"
            "适合“系统研究某个病证/方剂/概念的历史演变并提出可检验的假说”。返回会话号、研究结论、按发现分排序的假说"
            "（含支持与反面证据的原文与 passage_id、替代解释、可检验预测）。耗时：演示语料数秒，全量语料约一两分钟。"
            "假说是计算推断，须经专家核验。"),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "研究问题，如“消渴的认识与治疗在明代以前如何演变？”"},
                "focus_terms": {**STRINGS, "description": "焦点术语，如 [\"消渴\"]"},
                "tracks": {**STRINGS, "description": "发现轨道子集：D1 失传关联、D2 概念漂移、D3 方剂演化、D4 隐含关联、D5 矛盾；默认全部"},
                "max_rounds": {"type": "integer", "description": "研究轮次（1–6，默认按画像）"},
                "forbidden_assumptions": {**STRINGS, "description": "禁止的时代错置假设，如 [\"消渴=糖尿病\"]"},
                "holdout_after": {"type": "integer", "description": "时间留出：该年及以后的文本对研究不可见（历史时间机器）"},
                "books": {**STRINGS, "description": "只读这些书（book_id）"},
            },
            "required": ["question"],
        },
    },
    {
        "name": "taochronos_session",
        "family": "engine",
        "description": ("读取本次对话中已运行的研究会话：report（完整报告的某一节或全部）、hypothesis（某个假说的全部字段，"
                        "含证据、置信向量、合同评估）、evidence（证据表）。用于回答对研究结果的追问。"),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": S,
                "what": {"type": "string", "enum": ["summary", "report", "hypothesis", "evidence"]},
                "hypothesis": {"type": "string", "description": "假说编号（H1…）或 id（what=hypothesis 时）"},
                "section": {"type": "string", "description": "报告小节标题中的关键词（what=report 时，可省略）"},
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "taochronos_ask",
        "family": "engine",
        "description": ("V2 技能工作流：把问题编译为技能 S01–S15 的有向无环图（四个核心智能体），逐步执行并返回一份经批评者"
                        "审计的回答（每个陈述带证据等级与出处）。适合综合性问题；单点问题优先直接调用相应工具。"),
        "parameters": {"type": "object", "properties": {"question": S}, "required": ["question"]},
    },
]

META_TOOLS: list[dict[str, Any]] = [
    {
        "name": "taochronos_catalog",
        "family": "meta",
        "description": ("列出 TaoChronos 的全部工具（按家族：检索、治学、知识、发现、文献、核验、古今、现代……）。给出 family 或 query "
                        "时返回匹配工具的完整参数表，再用 taochronos_call 调用。"),
        "parameters": {
            "type": "object",
            "properties": {
                "family": {"type": "string", "description": "工具家族：" + "、".join(k for k in FAMILIES if k not in ("engine", "research"))},
                "query": {"type": "string", "description": "按名称或描述中的关键词查找，如“配伍”“避讳”“stemma”"},
            },
        },
    },
    {
        "name": "taochronos_call",
        "family": "meta",
        "description": "调用任一 TaoChronos 工具（名称见 taochronos_catalog，如 study.pairs、analysis.concept_drift）。",
        "parameters": {
            "type": "object",
            "properties": {"tool": {"type": "string", "description": "工具名，如 study.pairs"},
                           "arguments": {"type": "object", "description": "该工具的参数"}},
            "required": ["tool"],
        },
    },
]


def llm_name(name: str) -> str:
    """The name a model calls a tool by (dots are not allowed in most tool-name grammars)."""
    return name.replace(".", "__")


def clean_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """A copy every provider accepts: an array always says what its items are."""
    out = copy.deepcopy(schema) if schema else {"type": "object", "properties": {}}
    out.setdefault("type", "object")
    if out.get("type") == "object":
        out.setdefault("properties", {})

    def fix(node: Any) -> None:
        if not isinstance(node, dict):
            return
        if node.get("type") == "array" and "items" not in node:
            node["items"] = {"type": "object"}
        for child in (node.get("properties") or {}).values():
            fix(child)
        fix(node.get("items"))

    fix(out)
    return out


def offered(registry: Any, *, code_mode: bool = False) -> list[Any]:
    """The mesh tools a chat model may call at all (directly or through ``taochronos_call``)."""
    return [s for s in registry.list() if s.name not in NEVER and (code_mode or s.name != CODE_MODE)]


def tool_entry(spec: Any) -> dict[str, Any]:
    desc = spec.description + (f" Returns: {spec.returns}" if spec.returns else "")
    return {"name": llm_name(spec.name), "tool": spec.name, "family": spec.family, "description": desc,
            "parameters": clean_schema(spec.input_schema), "expensive": bool(spec.expensive)}


def llm_tools(registry: Any, *, mode: str = "core", code_mode: bool = False) -> list[dict[str, Any]]:
    """Neutral tool definitions ``{name, tool, family, description, parameters}`` for the client to put in the wire
    format of its provider (OpenAI ``function`` or Anthropic ``input_schema``)."""
    specs = offered(registry, code_mode=code_mode)
    if mode == "core":
        wanted = set(CORE) | ({CODE_MODE} if code_mode else set())
        direct = [tool_entry(s) for s in specs if s.name in wanted]
        meta = [{**m, "tool": m["name"]} for m in META_TOOLS]
    else:
        direct = [tool_entry(s) for s in specs]
        meta = []
    engine = [{**e, "tool": e["name"]} for e in ENGINE_TOOLS]
    return direct + engine + meta


def catalog_view(registry: Any, *, family: str | None = None, query: str | None = None,
                 code_mode: bool = False) -> dict[str, Any]:
    """What ``taochronos_catalog`` answers: every family with its tools, and full parameters for a family or a query."""
    specs = offered(registry, code_mode=code_mode)
    families: dict[str, Any] = {}
    for s in specs:
        fam = families.setdefault(s.family, {**FAMILIES.get(s.family, {"label": s.family, "blurb": ""}), "tools": []})
        fam["tools"].append({"tool": s.name, "summary": s.description.split("。")[0].split(". ")[0][:90]})
    out: dict[str, Any] = {"families": families,
                           "how": "用 taochronos_call 调用：{\"tool\": \"study.pairs\", \"arguments\": {...}}"}
    if family or query:
        q = (query or "").lower()
        matched = [s for s in specs if (not family or s.family == family)
                   and (not q or q in s.name.lower() or q in s.description.lower())]
        out["matched"] = [{"tool": s.name, "description": tool_entry(s)["description"], "parameters": tool_entry(s)["parameters"]}
                          for s in matched[:24]]
        if not matched:
            out["matched"] = []
            out["note"] = "没有匹配的工具；family 可选：" + "、".join(sorted(families))
    return out


def family_counts(registry: Any, *, code_mode: bool = False) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for s in offered(registry, code_mode=code_mode):
        counts[s.family] = counts.get(s.family, 0) + 1
    counts["engine"] = len(ENGINE_TOOLS)
    return {fam: {**meta, "count": counts[fam]} for fam, meta in FAMILIES.items() if counts.get(fam)}
