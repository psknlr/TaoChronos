"""研究方案 — a research question about the classics turned into a research protocol that can be carried out and checked.

A question (桂枝汤与桂枝加桂汤的组成与剂量有何异同？/ 半夏的用量与炮制历代如何变化？/ 十八反之说何时形成？) is read
against the lexicon — the formulas, drugs, findings and historical terms it names, the period it bounds (宋代以前) — and
its kind is told by its words and what it names: 方源考, 方剂比较, 类方, 药性源流, 用药谱, 配伍规律, 配伍禁忌, 方证关系, 术语
源流, 名称考, 古今对照.  Each kind contributes what a protocol of that kind needs, filled with the question's own names:

* the questions and **hypotheses**, each with its prediction, the test that decides it and what would refute it, and
  the rival explanations to rule out;
* the **scope** — the corpus (its size and sources), the period, the works to read first (the 要籍 of the kind's
  categories), what is included and what is not;
* the **variables** and how each is read off the texts (a composition is a set of drugs by family; a dose is read in
  the measures of its witness's period; a date is the terminus ante quem; a work counts once, whatever its copies);
* the **methods** — the steps, each a capability of this system with its arguments and the command that reruns it —
  the **analysis** (the statistics and their corrections), the **figures** planned (图 1 … with their form: a box plot, a
  forest plot …) and the **table shells** (表 1 …: the three-line tables the steps fill, their heads and a row of
  placeholders — n (%), M (P25, P75), OR (95% CI), P — with the statistics behind them), the **quality** checks (verbatim
  witnesses, source dependence, the gates and the acceptance criteria of a research run), the **limitations** (what
  survives, what this corpus holds, machine reading), the **ethics** (no clinical advice; doses are historical readings;
  the modern warnings for the toxic drugs named) and a **timeline**;
* a **research contract** ready for ``taochronos research`` (focus terms, tracks, period, forbidden assumptions).

With ``pilot`` (the default) the main steps are run once at their default settings: the protocol then says how much
evidence the corpus holds — compositions, works, periods, the earliest witness — and whether that is enough, with the
pilot's charts; its background cites witnesses, never memory.  The protocol plans research; it concludes nothing.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable

from .base import StudyBase, _load_yaml

# kind → (label, cue words); the order is the order a protocol presents them in
KINDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "origin": ("方源考", ("源流", "出处", "原方", "演变", "化裁", "沿革", "流变", "最早", "来源", "组成", "出自")),
    "compare": ("方剂比较", ("比较", "异同", "区别", "同药异量", "对比", "不同", "差异")),
    "family": ("类方", ("类方", "衍化", "衍生", "化裁而成", "系列", "方族", "加减", "发展")),
    "herb": ("药性源流", ("性味", "归经", "药性", "毒性", "升降", "浮沉", "气味", "功效", "主治", "性能")),
    "usage": ("用药谱", ("用量", "剂量", "用法", "炮制", "常用", "应用", "使用", "频率", "多少")),
    "pairs": ("配伍规律", ("配伍", "药对", "相须", "相使", "同用", "合用", "伍用", "搭配", "相配")),
    "incompat": ("配伍禁忌", ("十八反", "十九畏", "相反", "相畏", "禁忌", "反药", "畏药", "配伍禁忌")),
    "network": ("方证关系", ("方证", "主治", "适应", "证候", "病证", "所治", "用于")),
    "term": ("术语源流", ("含义", "概念", "演变", "源流", "词义", "认识", "内涵", "意义")),
    "names": ("名称考", ("异名", "名称", "别名", "正名", "改名", "名实", "称谓")),
    "modern": ("古今对照", ("现代", "药理", "机制", "临床", "疗效", "西医", "现代医学", "实验", "研究证据")),
}
TRACKS = {"origin": "D3", "family": "D3", "compare": "D3", "term": "D2", "names": "D2", "pairs": "D4", "usage": "D4",
          "network": "D4", "incompat": "D5", "herb": "D2"}
CATEGORIES = {"origin": ("方书", "伤寒", "杂病"), "compare": ("方书", "伤寒", "杂病"), "family": ("方书", "伤寒", "杂病"),
              "herb": ("本草",), "usage": ("方书", "本草"), "pairs": ("方书",), "incompat": ("本草", "方书"),
              "network": ("伤寒", "杂病", "方书", "医案"), "term": ("医经", "伤寒", "温病", "综合"), "names": ("本草", "方书"),
              "modern": ("本草", "方书")}
_QUESTION_WORDS = re.compile(r"如何|怎样|怎么|为何|为什么|是否|哪些|什么|研究|探讨|考察|分析|古代|古籍|历代|中医|的|了|吗|呢|？|\?|。|，")
# a formula's name the lexicon may lack (桂枝加桂汤): characters up to a dosage-form ending, no connective or mark inside
_FORMULA_SHAPE = re.compile(r"[^\s与和及或的、，,。；;：:？?！!在对从至自]{2,14}?(?:饮子|汤|散|丸|圆|饮|丹|膏)")
_ASKING = re.compile(r"^(?:比较|对比|研究|分析|考察|探讨|关于|请问|请|试论|论)+")
_BOTH_SIDES = re.compile(r"(以前|之前).{0,8}(以后|之后|以来)|(以后|之后).{0,8}(以前|之前)|前后")
NOTICE = ("本方案是研究计划，不是研究结论：其中的背景与预试验数字来自语料的机器阅读，须回查原文；不构成诊断、处方或剂量建议，"
          "历代剂量折合只是历史读法。")


# a figure's form in words (charts.py's types)
FORMS = {"line": "折线图，含 95% 置信带", "bar": "柱状图", "hbar": "条形图", "stack": "堆积柱状图", "heatmap": "热图", "range": "箱线图",
         "box": "Tukey 箱线图", "forest": "森林图", "scatter": "散点图", "dendrogram": "聚类树状图", "timeline": "时间线", "network": "网络图"}
# a table shell's placeholders: the notation of the number each cell will hold
N, NP, CI, MIQR, MSD, ORCI, P, PCT, TXT = "××", "×× (××.×)", "××.×–××.×", "××.× (××.×, ××.×)", "××.× ± ××.×", "×.×× (×.××–×.××)", "×.×××", "××.×", "……"
PERIOD_STUBS = ["先秦两汉", "魏晋南北朝", "……"]


def _shell(title: str, source: str, columns: list[tuple[str, str]], stubs: list[str], *, stats: str = "", groups: dict[str, str] | None = None) -> dict[str, Any]:
    """A table shell: the table a step will fill — its heads ((label, placeholder) pairs, the first the stub), rows of
    placeholders under the stubs, the statistics behind its numbers; ``groups`` puts a head over columns."""
    return {"title": title, "from": source, "columns": [c for c, _ in columns], "cells": [x for _, x in columns], "stubs": stubs,
            "statistics": stats, "groups": groups or {}}


def _first(seq: list[Any]) -> Any:
    return seq[0] if seq else None


class ProtocolDesigner:
    def __init__(self, study: Any) -> None:
        self.s = study  # the StudyService: its functions run the pilot
        self.b: StudyBase = study

    # ------------------------------------------------------------ reading the question
    def entities(self, question: str) -> dict[str, Any]:
        b = self.b
        norm = b.normalize(question)
        mentions = b.pack.lexicon.match(norm, include_weak=False)
        # formula names the lexicon lacks, read by their shape — unless a known formula, or a drug (石膏), ends there
        spans = [(m.start, m.end) for m in mentions if m.category == "formula"]
        ends = {m.end for m in mentions if m.category in ("formula", "herb")}
        unknown: list[tuple[int, str]] = []
        for c in _FORMULA_SHAPE.finditer(norm):
            name = _ASKING.sub("", c.group(0))
            if c.end() in ends or len(name) < 3:
                continue
            unknown.append((c.end() - len(name), question[c.end() - len(name): c.end()]))
            spans.append((c.end() - len(name), c.end()))
        by: dict[str, list[str]] = {}
        for m in sorted(mentions, key=lambda m: m.start):
            if m.category != "formula" and any(a <= m.start and m.end <= z for a, z in spans):
                continue  # a drug inside a formula's name (桂枝 in 桂枝加桂汤) is not asked about
            by.setdefault(m.category, [])
            if m.entry.term not in by[m.category]:
                by[m.category].append(m.entry.term)
        if unknown:  # in the order the question names them
            known = [(m.start, m.entry.term) for m in mentions if m.category == "formula"]
            by["formula"] = list(dict.fromkeys(t for _, t in sorted(known + unknown)))
        terms = [t for t in b.pack.terminology.terms if t in question or b.normalize(t) in norm]
        books = [t for t in re.findall(r"《([^》]{1,30})》", question)]
        after, before = b.pack.periods.parse_constraint(question)
        split = None
        if _BOTH_SIDES.search(question) and (after is None) != (before is None):  # 宋代以前与以后: all periods, compared at the cut
            split, after, before = after if after is not None else before, None, None
        terms = [t for t in terms if t not in by.get("herb", []) + by.get("formula", [])]
        findings = [x for c in ("disease", "pattern", "symptom", "sign", "pulse") for x in by.get(c, []) if x not in terms]
        return {"formulas": by.get("formula", []), "herbs": by.get("herb", []), "findings": findings, "terms": terms, "books": books,
                "unlisted": [t for _, t in unknown],
                "period": {"after": after, "before": before, "split": split, "label": self._period_label(after, before, split)}}

    @staticmethod
    def _period_label(after: Any, before: Any, split: Any = None) -> str:
        year = lambda y: f"前 {-int(y)} 年" if y < 0 else f"{int(y)} 年"
        if split is not None:
            return f"全部时期，以{year(split)}为界比较前后"
        if after is None and before is None:
            return "全部时期"
        if after is None:
            return f"{year(before)}以前"
        if before is None:
            return f"{year(after)}以后"
        return f"{year(after)}至{year(before)}"

    def kinds(self, question: str, ent: dict[str, Any]) -> list[str]:
        f, h = ent["formulas"], ent["herbs"]
        hit = {k for k, (_, cues) in KINDS.items() if any(c in question for c in cues)}
        need = {"origin": bool(f), "compare": len(f) >= 2, "family": bool(f), "herb": bool(h), "usage": bool(h),
                "pairs": bool(h), "incompat": True, "network": bool(f or ent["findings"]), "term": bool(ent["terms"] or ent["findings"]),
                "names": bool(f or h or ent["terms"]), "modern": True}
        out = [k for k in KINDS if k in hit and need[k]]
        if len(f) >= 2 and "compare" not in out:
            out.insert(0, "compare")
        if not [k for k in out if k != "modern"]:  # no cue: what the question names decides
            out += ["origin", "family"] if f else []
            out += ["herb", "usage"] if h else []
            out += ["term"] if (ent["terms"] or ent["findings"]) and not (f or h) else []
        out = [k for k in KINDS if k in out]
        return out or ["general"]

    # ------------------------------------------------------------ the protocol
    def design(self, question: str, *, pilot: bool = True) -> dict[str, Any]:
        question = question.strip()
        if not question:
            raise ValueError("give a research question")
        ent = self.entities(question)
        kinds = self.kinds(question, ent)
        ent_q = {**ent, "question": question}
        parts: list[dict[str, Any]] = [getattr(self, f"_{k}")(ent_q) for k in kinds]
        sig = self.b.signature()
        corpus = self._corpus(sig)
        p: dict[str, Any] = {
            "id": "proto-" + hashlib.sha1(json.dumps([question, sig["corpus_digest"]], ensure_ascii=False).encode()).hexdigest()[:12],
            "title": self._title(question, ent, kinds), "question": question,
            "kinds": [{"id": k, "label": KINDS[k][0] if k in KINDS else "综合检索"} for k in kinds], "entities": ent,
        }
        p["objectives"] = [o for part in parts for o in part.get("objectives", [])]
        p["questions"] = [{"id": f"Q{i}", "text": q} for i, q in enumerate((q for part in parts for q in part.get("questions", [])), 1)]
        p["hypotheses"] = [{"id": f"H{i}", **h} for i, h in enumerate((h for part in parts for h in part.get("hypotheses", [])), 1)]
        p["scope"] = self._scope(ent, kinds, corpus)
        p["variables"] = self._dedupe([v for part in parts for v in part.get("variables", [])] + COMMON_VARIABLES, "name")
        steps = self._dedupe([m for part in parts for m in part.get("methods", [])], "command")
        p["methods"] = [{"step": i, **m} for i, m in enumerate(steps, 1)]
        p["analysis"] = self._dedupe([a for part in parts for a in part.get("analysis", [])] + COMMON_ANALYSIS, "name")
        p["figures"] = [{"id": f"F{i}", "number": i, **fig, "form": FORMS.get(fig.get("type"), fig.get("type"))}
                        for i, fig in enumerate(self._dedupe([f for part in parts for f in part.get("figures", [])], "chart"), 1)]
        p["table_shells"] = [{"id": f"T{i}", "number": i, **t} for i, t in enumerate(self._dedupe([t for part in parts for t in part.get("tables", [])], "title"), 1)]
        p["quality"] = QUALITY
        p["limitations"] = [x for part in parts for x in part.get("limitations", [])] + self._limitations(corpus)
        if ent.get("unlisted"):
            p["limitations"].insert(0, f"{'、'.join(ent['unlisted'])}不在本系统词表中（按方名读作方剂）：其见证只能按原名检索，异名与讳改名"
                                       "不会自动合并，预试验可能检不到")
        p["ethics"] = self._ethics(ent)
        p["timeline"] = self._timeline(p)
        p["outputs"] = OUTPUTS
        p["contract"] = self._contract(question, ent, kinds)
        p["reproducibility"] = {"corpus": {k: sig[k] for k in ("books", "passages", "sources", "normalizer", "corpus_digest")},
                                "commands": [m["command"] for m in p["methods"]] + [p["contract"]["command"]]}
        p["pilot"] = self._pilot(parts) if pilot else {"ran": False, "findings": [], "feasibility": "未做预试验"}
        charts = p["pilot"].pop("charts", [])
        p["background"] = [{"text": f["text"], "passage_id": f.get("passage_id"), "basis": "预试验（机器阅读，须回查原文）"}
                           for f in p["pilot"].get("findings", []) if f.get("background")]
        if charts:
            p["charts"] = charts
        p["notice"] = NOTICE
        return p

    def _title(self, question: str, ent: dict[str, Any], kinds: list[str]) -> str:
        names = list(dict.fromkeys(ent["formulas"] + ent["herbs"] + ent["terms"] + ent["findings"]))[:3]
        label = "、".join(KINDS[k][0] for k in kinds if k in KINDS)[:24] or "文献"
        return f"{'、'.join(names)}的{label}研究方案" if names else f"{label}研究方案"

    @staticmethod
    def _dedupe(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
        seen: set[Any] = set()
        out = []
        for r in rows:
            if r.get(key) in seen:
                continue
            seen.add(r.get(key))
            out.append(r)
        return out

    # ------------------------------------------------------------ scope
    def _corpus(self, sig: dict[str, Any]) -> dict[str, Any]:
        edition = getattr(self.b.corpus, "edition", None)
        label = {"web": "要籍语料（按历代引用排序的要籍，重要典籍全书、其余为章节节选）", "full": "全量语料"}.get(edition, "演示语料" if not getattr(self.b.corpus, "large", False) else "语料库")
        return {"label": label, "edition": edition or "demo", "books": sig["books"], "passages": sig["passages"], "sources": sig["sources"]}

    def _scope(self, ent: dict[str, Any], kinds: list[str], corpus: dict[str, Any]) -> dict[str, Any]:
        cats = [c for k in kinds for c in CATEGORIES.get(k, ())]
        works = []
        try:
            listed = self.s._canon.catalog()
        except AttributeError:  # pragma: no cover - a study service without the canon
            listed = []
        held = {bk.work or bid for bid, bk in self.b.corpus.books.items()} | set(self.b.corpus.books)
        for cat in dict.fromkeys(cats):
            picked = [w for w in listed if w.get("category") == cat][:4]
            works += [{"title": w["title"], "rank": w["rank"], "dynasty": w.get("dynasty"), "category": cat,
                       "in_this_corpus": w.get("work") in held} for w in picked]
        works = self._dedupe(works, "title")[:12]
        for title in ent["books"]:
            if title not in {w["title"] for w in works}:
                works.insert(0, {"title": title, "rank": None, "dynasty": None, "category": "问题所指", "in_this_corpus": None})
        return {
            "corpus": corpus, "period": ent["period"], "works": works,
            "inclusion": ["语料中成书于 1949 年以前的医籍；每部著作的多个录本合为一个来源（按著作计数）",
                          "写出原文的见证：每条结论附原文、书名、卷篇与段落号",
                          f"时间范围：{ent['period']['label']}（以成书年代下限为准）"],
            "exclusion": ["当代著作与现代整理者的按语、校注（整理本中的今人成分另为一层）",
                          "仅提及名称而未写出组成或性能的段落（只作旁证）",
                          "辑本（如《神农本草经》辑本）中后世附入的文字，年代以其层次而非所辑之书为准"],
        }

    def _limitations(self, corpus: dict[str, Any]) -> list[str]:
        out = ["传世文献有存佚偏倚：一个时期写下且留存的文字，不等于当时的全部认识或实践；“未检得”不等于“没有”",
               "录文来自多个数字化来源，未经本项目逐字校勘；规则抽取属机器阅读，结论须回查原文",
               "成书年代多为区间，以下限排序；同一书的不同层次（正文、注、附方）年代不同",
               "计数按著作而非录本，但一方被多书转抄时仍会重复计入（可用转录与引用分析核查依存关系）"]
        if corpus["edition"] == "web":
            out.insert(1, "要籍语料只收要籍且多为章节节选：其中未检得者，应在全量语料中复核")
        return out

    def _ethics(self, ent: dict[str, Any]) -> list[str]:
        out = ["本研究为文献研究：结论描述古籍如何记载，不构成诊断、处方、用药或剂量建议",
               "历代剂量按各期度量衡折合，只是学术估值与历史读法，不可作为今日用量",
               "古病名不等同现代疾病（如“消渴”不等于糖尿病）；古今对照只说表型相似，不作回溯诊断"]
        safety = (_load_yaml(str(self.b.pack.root.parent / "modern" / "safety.yaml")) or {}).get("materials") or {}
        named = set(ent["herbs"]) | {self.b.normalize(h) for h in ent["herbs"]}
        for drug, info in safety.items():
            if drug in named or any(a in named for a in info.get("aliases", [])):
                out.append(f"{drug}：{info.get('risk', '')}（现代安全提示）".strip())
        return out

    def _timeline(self, p: dict[str, Any]) -> list[dict[str, Any]]:
        n = len(p["methods"])
        return [
            {"phase": "一、准备与预试验", "tasks": "确定问题与范围，跑通预试验，核对语料覆盖", "deliverables": "研究方案（本文件）、预试验结果"},
            {"phase": "二、取证", "tasks": f"按方法步骤 1–{n} 取得全部见证，逐条回查原文，剔除误读", "deliverables": "见证表（含段落号）、数据包（CSV）"},
            {"phase": "三、分析与检验", "tasks": "按分析计划计算并检验各假设，记录证伪与替代解释", "deliverables": "统计结果、图表（SVG/CSV）"},
            {"phase": "四、核验与复核", "tasks": "引文逐字核验、来源依存核查；必要时发起系统研究并经专家复核", "deliverables": "核验记录、复核意见"},
            {"phase": "五、撰写", "tasks": "按原文、注家解释、计算推断、现代医学四个层次分别表述", "deliverables": "研究报告"},
        ]

    def _contract(self, question: str, ent: dict[str, Any], kinds: list[str]) -> dict[str, Any]:
        focus = list(dict.fromkeys(ent["formulas"] + ent["herbs"] + ent["terms"] + ent["findings"]))[:6]
        tracks = sorted({TRACKS[k] for k in kinds if k in TRACKS}) or ["D1", "D2", "D3", "D4", "D5"]
        forbid = [f"{t}=现代病名" for t in ent["terms"][:2]] + ["古代剂量=今日用量"]
        period = ent["period"]
        cmd = [f'taochronos research "{question}"'] + [f"--focus {x}" for x in focus[:3]] + [f"--tracks {','.join(tracks)}"]
        return {"question": question, "focus_terms": focus, "tracks": tracks,
                "temporal_scope": {"after": period["after"], "before": period["before"]}, "holdout_after": period.get("split"),
                "forbidden_assumptions": forbid, "max_rounds": 2, "command": " ".join(cmd),
                "note": "交给系统研究（多智能体：取证、模式挖掘、假说、证伪、门控与专家复核）时所用的研究合同"}

    # ------------------------------------------------------------ pilot
    def _pilot(self, parts: list[dict[str, Any]]) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        charts: list[dict[str, Any]] = []
        notes: list[str] = []
        ran = 0
        for part in parts:
            fn: Callable[[], tuple[list[dict[str, Any]], list[dict[str, Any]]]] | None = part.get("pilot")
            if fn is None or ran >= 3:
                continue
            ran += 1
            try:
                got, got_charts = fn()
            except (ValueError, KeyError) as exc:
                notes.append(f"{part.get('label', '')}：预试验未能运行（{exc}）")
                continue
            findings += got
            charts += got_charts[:2]
        enough = [f for f in findings if f.get("n") is not None]
        if not enough:
            verdict = "不足" if findings or notes else "未做预试验"
        elif all(f["n"] >= 20 for f in enough):
            verdict = "充分"
        elif any(f["n"] >= 5 for f in enough):
            verdict = "有限"
        else:
            verdict = "不足"
        advice = {"充分": "见证足以进行按时期的统计；仍须逐条回查原文。",
                  "有限": "见证有限：按时期的统计区间会很宽，宜以个案考证为主，或在全量语料中复核。",
                  "不足": "见证不足：建议在全量语料中运行，或放宽名称（异名、讳改名）与时间范围。"}.get(verdict, "")
        return {"ran": True, "findings": findings, "feasibility": verdict, "advice": advice, "notes": notes, "charts": charts}

    # ------------------------------------------------------------ the kinds
    def _origin(self, ent: dict[str, Any]) -> dict[str, Any]:
        f = ent["formulas"][0]

        def pilot() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
            r = self.s.formula(f, other_names=False)
            s = r.get("summary", {})
            out = [{"text": f"{f}写出组成的见证 {s.get('compositions', 0)} 条，见于 {s.get('works', 0)} 部著作；组成类别 {s.get('groups', 0)} 类"
                            f"（加减化裁 {s.get('variants', 0)}、同名异方 {s.get('same_name_different', 0)}）",
                    "n": s.get("works", 0)}]
            e = r.get("earliest")
            if e:
                out.append({"text": f"{f}原方最早见于{e['locator']}（{'–'.join(str(int(y)) for y in e['years']) if e.get('years') else '年代未定'}）",
                            "passage_id": e["passage_id"], "background": True})
            return out, r.get("charts", [])

        return {"label": "方源考", "pilot": pilot,
                "objectives": [f"考定{f}的原方组成、剂量与煎服法的最早见证，梳理其通行方、加减化裁与同名异方"],
                "questions": [f"{f}的原方（药味、剂量、煎服法）最早见于何书？后世通行之方与原方是否一致？",
                              f"{f}在历代有哪些加减化裁、同名异方与同方异名？"],
                "hypotheses": [{"statement": f"{f}的通行方保持原方的核心药味",
                                "prediction": "通行方与原方的药味集合 Jaccard ≥ 0.8，且主要药物的配伍比例相同",
                                "test": "方源考：组成聚类（Jaccard ≥ 0.7 归为一类）与配伍比例对照",
                                "falsified_if": "通行方核心药味与原方不同（Jaccard < 0.8），或主要药物的剂量比改变一成以上",
                                "alternatives": ["同名异方：后世同名而组成不同的另一方", "转抄讹误：剂量、药名在传写中致误"]}],
                "variables": [{"name": "组成", "definition": "一处写出的药味集合，按药物同类归并（桂枝/桂心/肉桂 → 桂）", "measure": "集合；Jaccard 相似度", "source": "方源考"},
                              {"name": "配伍比例", "definition": "方中各药剂量与最大剂量之比", "measure": "0–1", "source": "方源考"},
                              {"name": "组成类别", "definition": "原方（最早见）、通行方（见证最多）、加减化裁（Jaccard ≥ 0.5）、同名异方、孤例", "measure": "类别", "source": "方源考"}],
                "methods": [{"title": f"{f}的全部写出组成", "tool": "study.formula", "args": {"name": f},
                             "command": f"taochronos study formula {f} --charts figures", "purpose": "原方、通行方、加减、同名异方、配伍比例、历代主治、方歌",
                             "outputs": "见证表、组成类别、比例"},
                            {"title": f"{f}的类方", "tool": "study.family", "args": {"formula": f},
                             "command": f"taochronos study family {f} --charts figures", "purpose": "由本方加减而成之方、合方与同药异量", "outputs": "类方表、时间线"}],
                "analysis": [{"name": "组成聚类", "method": "Jaccard 相似度", "detail": "≥ 0.7 归为一类；最早见者为原方，见证最多者为通行方"},
                             {"name": "剂量比较", "method": "配伍比例与倍数", "detail": "同一药物剂量相差一成以上记为变化；以枚、升计者只在同一单位间比较"}],
                "figures": [{"title": f"{f}的见证（按时期与组成类别）", "type": "stack", "from": "study.formula", "chart": "formula-witnesses"},
                            {"title": f"{f}的配伍比例", "type": "bar", "from": "study.formula", "chart": "formula-ratios"},
                            {"title": f"{f}类方的最早见", "type": "timeline", "from": "study.family", "chart": "family-timeline"}],
                "tables": [_shell(f"{f}写出组成的见证（按时期与组成类别）", "study.formula",
                                  [("时期", ""), ("原方", N), ("通行方", N), ("加减化裁", N), ("同名异方", N), ("合计", N)], PERIOD_STUBS,
                                  stats="组成按药味 Jaccard 系数（≥ 0.7）归类；每部著作计一次"),
                           _shell(f"{f}原方与通行方的组成与剂量", "study.compare", [("药物", ""), ("原方：剂量（比例）", "××两（×.××）"),
                                  ("通行方：剂量（比例）", "××两（×.××）")], ["……"], stats="比例：以该方最大重量为 1；剂量按见证年代计量折合")],
                "limitations": ["方名之后未写出组成者（只言“桂枝汤主之”）不计入组成，只作旁证"]}

    def _compare(self, ent: dict[str, Any]) -> dict[str, Any]:
        fs = ent["formulas"][:6]
        names = "、".join(fs)

        def pilot() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
            r = self.s.compare(fs)
            out = [{"text": f"{x['a']}与{x['b']}：{x['verdict']}"
                            + (f"（{'；'.join(c['drug'] + c['a'] + '→' + c['b'] for c in x['dose_changes'])}）" if x["dose_changes"] else ""),
                    "background": True} for x in r.get("pairs", [])]
            found = [f_ for f_ in r.get("formulas", []) if f_.get("found")]
            out.append({"text": f"写出组成可资比较者 {len(found)} 方（共 {len(fs)} 方）", "n": min((f_.get("witnesses") or 0) for f_ in found) if found else 0})
            return out, r.get("charts", [])

        derived = self._derivation(fs[0], fs[1])
        added = [d for op, ds in derived[2] if op in ("加", "倍") for d in ds] if derived else []
        stem = re.sub(r"(汤|散|丸|圆|饮子|饮|丹|膏|方)$", "", derived[1]) if derived else ""
        if derived is not None and added and all(op in ("加", "倍") for op, _ in derived[2]) and all(d in stem for d in added):
            # 桂枝加桂汤: the drug added is the one the base is named after — its dose raised, 同药异量
            child, parent, _ = derived
            heavier = "、".join(added)
            first = {"statement": f"{child}即{parent}加重{heavier}之量（同药异量），药味与{parent}相同",
                     "prediction": f"两方药味集合相同；{heavier}在{child}中的剂量大于{parent}，其余药物剂量相同",
                     "test": f"方剂比较：各取原方一条见证比较药味与剂量；类方：{parent}的类方中{child}应为同药异量",
                     "falsified_if": f"两方药味不同，或{heavier}的剂量并未增加",
                     "alternatives": ["同名异方：所比见证并非二方的原方", "所加者为同名异物（如桂枝与肉桂）：须看各见证的写法",
                                      "不同见证所据版本不同：须比较原方与通行方两种取法"]}
        elif derived is not None:  # 白虎加人参汤 is named as 白虎汤 加 人参: the name is the hypothesis
            child, parent, changes = derived
            said = "，".join(f"{op}{'、'.join(ds)}" for op, ds in changes)
            relation = "加减" if len({op for op, _ in changes} & {"加", "去"}) == 2 else {"加": "加味", "去": "减味"}.get(changes[0][0], "同药异量")
            first = {"statement": f"{child}即{parent}{said}（{relation}），其余药味与{parent}相同",
                     "prediction": f"{child}的药味等于{parent}的药味{said}；共有药物的剂量比相同（相差不超过一成）",
                     "test": f"方剂比较：各取原方一条见证比较药味与剂量；类方：{parent}的类方中{child}的关系应为{relation}",
                     "falsified_if": f"{child}另有增减之药，或共有药物的剂量比改变一成以上（则名实不符或兼调剂量）",
                     "alternatives": ["同名异方：所比见证并非二方的原方", "以名推方：后人据方名补写组成，组成之合不足以证明其源",
                                      f"所加之药本已在{parent}中（如桂枝加芍药汤）：则是加重其量，为同药异量",
                                      "不同见证所据版本不同：须比较原方与通行方两种取法"]}
        else:
            first = {"statement": f"{fs[0]}与{fs[1]}同出一源（共有药味过半）",
                     "prediction": "共有药味占两方药味并集的一半以上（Jaccard ≥ 0.5）",
                     "test": "方剂比较：各取原方（及通行方）一条见证，比较药味与剂量",
                     "falsified_if": "Jaccard < 0.5（异方）",
                     "alternatives": ["药味相同而剂量不同（同药异量）：见剂量对照", "共有者只是常用药（甘草、生姜、大枣）：不足以说明同源",
                                      "不同见证所据版本不同：须比较原方与通行方两种取法"]}
        return {"label": "方剂比较", "pilot": pilot,
                "objectives": [f"比较{names}的药味与剂量，判定其为同方、同药异量、加减化裁或异方"],
                "questions": [f"{names}的组成与剂量有何异同？哪些是同药异量？"],
                "hypotheses": [first,
                               {"statement": f"{fs[0]}与{fs[1]}的共有药物剂量比相同",
                                "prediction": "共有药物两两之间的剂量比，在两方中相差不超过一成",
                                "test": "方剂比较：配伍比例对照（以重量写者折合为两）",
                                "falsified_if": "至少一味共有药物的剂量倍数偏离 1 超过 0.1（同药异量或兼调剂量）",
                                "alternatives": ["计量单位不同（枚、升）而无法比较", "传写之误：剂量数字在转抄中改变"]}],
                "variables": [{"name": "剂量", "definition": "原文写法；以重量写者按见证年代计量折合为两（学术估值）", "measure": "两；同一单位的枚、升", "source": "方剂比较"},
                              {"name": "剂量加权重合", "definition": "两方各药占全方重量份额的较小者之和", "measure": "0–1", "source": "方剂比较"}],
                "methods": [{"title": "原方对照", "tool": "study.compare", "args": {"formulas": fs},
                             "command": f"taochronos study compare {' '.join(fs)} --charts figures", "purpose": "药味、剂量、比例、两两结论", "outputs": "对照表、相似度"},
                            {"title": "通行方对照", "tool": "study.compare", "args": {"formulas": fs, "which": "current"},
                             "command": f"taochronos study compare {' '.join(fs)} --which current", "purpose": "以见证最多之方复核结论", "outputs": "对照表"}],
                "analysis": [{"name": "同药异量判定", "method": "药味集合相同且剂量倍数偏离 1 超过 0.1", "detail": "以重量计者换算为两；以枚、升计者只在同单位间比较"}],
                "figures": [{"title": "配伍比例对照", "type": "bar", "from": "study.compare", "chart": "compare-ratios"},
                            {"title": "方剂相似度", "type": "heatmap", "from": "study.compare", "chart": "compare-similarity"}],
                "tables": [_shell("、".join(fs) + "的组成与剂量", "study.compare", [("药物", "")] + [(f"{x}：剂量（比例）", "××两（×.××）") for x in fs],
                                  ["……"], stats="比例：以该方最大重量为 1；以枚、升等计者无比例"),
                           _shell("方剂两两比较", "study.compare", [("方 A", ""), ("方 B", TXT), ("共有药物", TXT), ("Jaccard", "×.××"),
                                  ("剂量加权重合", "×.××"), ("结论", TXT)], [fs[0] if fs else "……"],
                                  stats="Jaccard：共有药味 ÷ 药味并集；剂量加权重合：两方各药剂量份额之较小者之和")],
                "limitations": ["各方只取一条见证（原方或通行方）：不同版本的剂量可能不同，须结合方源考"]}

    def _derivation(self, a: str, b: str) -> tuple[str, str, list[tuple[str, list[str]]]] | None:
        """What the names say of two formulas: 白虎加人参汤 is 白虎汤 加 人参, 桂枝去芍药汤 is 桂枝汤 去 芍药 — (the one
        derived, the one it is derived from, [(加 / 去 / 倍, drugs)]); None when neither name builds on the other."""
        lex = self.s.pack.lexicon
        for child, parent in ((a, b), (b, a)):
            stem = re.sub(r"(汤|散|丸|圆|饮子|饮|丹|膏|方)$", "", parent)
            if len(stem) < 2 or child == parent or not child.startswith(stem):
                continue
            rest = re.sub(r"(汤|散|丸|圆|饮子|饮|丹|膏|方)$", "", child[len(stem):])
            changes = []
            for op, part in re.findall(r"(加|去|倍)([^加去倍]+)", rest):
                drugs = [m.entry.term for m in lex.match(part) if m.category == "herb"] or [part]
                changes.append((op, list(dict.fromkeys(drugs))))
            if changes and rest.startswith(("加", "去", "倍")):
                return child, parent, changes
        return None

    def _family(self, ent: dict[str, Any]) -> dict[str, Any]:
        f = ent["formulas"][0]

        def pilot() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
            r = self.s.family(f)
            rel = r.get("by_relation", {})
            return ([{"text": f"含{f}核心组成（{'、'.join(r['formula']['core'])}）而加减者 {len(r.get('members', []))} 方：" +
                              "，".join(f"{k} {v}" for k, v in rel.items()), "n": len(r.get("members", []))}], r.get("charts", []))

        return {"label": "类方", "pilot": pilot,
                "objectives": [f"整理以{f}为基础加减而成的类方，区分加味、减味、加减、同药异量与合方"],
                "questions": [f"哪些方由{f}加减而成？其加减之药与出现年代如何？"],
                "hypotheses": [{"statement": f"{f}的类方以加味为主",
                                "prediction": "类方中“加味”多于“减味”与“加减”",
                                "test": "类方：按关系计数（每部著作一次）",
                                "falsified_if": "“减味”或“加减”多于“加味”",
                                "alternatives": ["趋同：药味相近而非由本方衍化（须有“于本方加某药”之类的明文）"]}],
                "methods": [{"title": f"{f}的类方", "tool": "study.family", "args": {"formula": f},
                             "command": f"taochronos study family {f} --charts figures", "purpose": "类方及其关系", "outputs": "类方表、关系图"}],
                "analysis": [{"name": "类方判定", "method": "核心药味包含度 ≥ 0.75、增药 ≤ 4 味", "detail": "合方：所增之药合于另一常见方的核心组成"}],
                "figures": [{"title": f"{f}类方关系", "type": "network", "from": "study.family", "chart": "family-network"}],
                "tables": [_shell(f"{f}的类方", "study.family", [("方名", ""), ("关系", TXT), ("加", TXT), ("减", TXT), ("著作（部）", N),
                                  ("最早见", "《……》（年代）")], ["……"], stats="关系：加味、减味、加减、同药异量、同方异名、合方")],
                "limitations": ["类方以组成相近判定，未必有明文的衍化关系；衍化须以“于某方加某药”之类的原文为证"]}

    def _herb(self, ent: dict[str, Any]) -> dict[str, Any]:
        h = ent["herbs"][0]

        def pilot() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
            r = self.s.herb(h)
            s = r.get("summary", {})
            out = [{"text": f"{h}的本草条目见于 {s.get('works', 0)} 部著作，其中言归经者 {s.get('with_channels', 0)} 部", "n": s.get("works", 0)}]
            for f in [x for x in r.get("firsts", []) if x["field"] in ("性味", "药性", "归经")][:3]:
                out.append({"text": f"{h}{f['field']}“{f['value']}”首见于{f['locator']}", "passage_id": f.get("passage_id"), "background": True})
            return out, r.get("charts", [])

        return {"label": "药性源流", "pilot": pilot,
                "objectives": [f"梳理历代本草对{h}性味、归经、毒性、升降浮沉与主治的记载及其首见"],
                "questions": [f"{h}的性味、毒性、归经之说各首见于何书？历代有无改变？"],
                "hypotheses": [{"statement": f"{h}的归经之说晚于性味之说，至金元以后始见",
                                "prediction": "归经的最早见证晚于性味的最早见证，且不早于宋",
                                "test": "药性源流：各项性能的首见（按成书年代下限）",
                                "falsified_if": "归经之说的最早见证早于宋（960 年）",
                                "alternatives": ["辑本或后世注文混入早期书中（须看文字层次）"]}],
                "variables": [{"name": "药性", "definition": "本草条目所言的味、性（寒凉平温热）、毒、归经、升降浮沉", "measure": "类别；言之者占著作的比例", "source": "药性源流"}],
                "methods": [{"title": f"{h}的本草条目", "tool": "study.herb", "args": {"name": h},
                             "command": f"taochronos study herb {h} --charts figures", "purpose": "逐书的性能与首见", "outputs": "条目表、首见"},
                            {"title": f"{h}的名称", "tool": "study.names", "args": {"term": h},
                             "command": f"taochronos study names {h}", "purpose": "异名与讳改名，避免漏检", "outputs": "名称表"}],
                "analysis": [{"name": "首见", "method": "按成书年代下限（terminus ante quem）排序", "detail": "辑本另行标注"}],
                "figures": [{"title": f"{h}历代本草所言药性", "type": "stack", "from": "study.herb", "chart": "herb-natures"},
                            {"title": f"{h}各项药性的首见", "type": "timeline", "from": "study.herb", "chart": "herb-firsts"}],
                "tables": [_shell(f"历代本草所言{h}之性味", "study.herb", [("时期", ""), ("本草著作（部）", N), ("寒", N), ("凉", N), ("平", N),
                                  ("温", N), ("热", N), ("味（部）", TXT)], PERIOD_STUBS, stats="一部著作言之者计一次",
                                  groups={c: "言其性为（部）" for c in ("寒", "凉", "平", "温", "热")}),
                           _shell(f"{h}各项性能的首见", "study.herb", [("项目", ""), ("所言", TXT), ("首见", "《……》"), ("成书年代", N)],
                                  ["性味", "归经", "……"], stats="按成书年代下限（terminus ante quem）排序；辑本另标")],
                "limitations": ["本草条目的切分为规则阅读：一条之中混入他药的文字会误读，首见须回查原文"]}

    def _usage(self, ent: dict[str, Any]) -> dict[str, Any]:
        h = ent["herbs"][0]

        def pilot() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
            r = self.s.usage(h)
            trend = r.get("trend") or {}
            out = [{"text": f"写出组成 {r['compositions']} 首中含{h} {r['with']} 首（{r['share']:.1%}），见于 {r['works']} 部著作"
                            + (f"；历期趋势 z = {trend['z']:.2f}" if trend.get("z") is not None else ""), "n": r["works"]}]
            if r.get("examples"):
                e = r["examples"][0]
                out.append({"text": f"最早含{h}的组成见于{e.get('locator', '')}（{e.get('formula', '')}）", "passage_id": e.get("passage_id"), "background": True})
            return out, r.get("charts", [])

        return {"label": "用药谱", "pilot": pilot,
                "objectives": [f"统计{h}在历代方剂中的使用比例、剂量、炮制与常用配伍"],
                "questions": [f"{h}在历代方剂中的使用比例如何变化？汤剂中的用量与炮制有何不同？"],
                "hypotheses": [{"statement": f"{h}在方剂中的使用比例随时期而变",
                                "prediction": "各时期含此药的组成占比不同，存在单调趋势",
                                "test": "Cochran–Armitage 趋势检验（按时期排序），并报告各期 95% Wilson 区间",
                                "falsified_if": "趋势检验 |z| < 1.96（p ≥ 0.05）",
                                "alternatives": ["某一大部头方书的偏重（按著作计数可减轻）", "各时期存世方书的构成不同"]},
                               {"statement": f"汤剂中{h}的用量（折合克数）宋以后低于汉唐",
                                "prediction": "宋金元以后各期汤剂用量的中位数低于先秦两汉与隋唐五代",
                                "test": "各期汤剂用量的中位数与四分位距（只计以重量写出者）",
                                "falsified_if": "宋以后的中位数不低于汉唐",
                                "alternatives": ["度量衡折合的不确定（各期两之克数取估值区间）", "剂型不同：丸散之量为一料，不与汤剂相比"]}],
                "variables": [{"name": "使用比例", "definition": "含此药的写出组成占该期全部写出组成的比例（每部著作一次）", "measure": "比例与 95% Wilson 区间", "source": "用药谱"},
                              {"name": "剂型", "definition": "由方名判定：汤、饮、煎为汤剂；丸、圆、丹为丸剂；散为散剂；膏为膏剂", "measure": "类别", "source": "用药谱"}],
                "methods": [{"title": f"{h}的用药谱", "tool": "study.usage", "args": {"herb": h},
                             "command": f"taochronos study usage {h} --charts figures", "purpose": "比例、剂量、炮制、配伍、所在之方", "outputs": "按时期的表与图"},
                            {"title": f"{h}的配伍", "tool": "study.pairs", "args": {"herb": h},
                             "command": f"taochronos study pairs {h} --charts figures", "purpose": "显著药对（Fisher + BH）", "outputs": "配伍表"}],
                "analysis": [{"name": "趋势检验", "method": "Cochran–Armitage", "detail": "各期比例按时间排序"},
                             {"name": "用量", "method": "中位数与四分位距", "detail": "只计汤剂中以重量写出的剂量，按见证年代计量折合"}],
                "figures": [{"title": f"含{h}的组成占比", "type": "line", "from": "study.usage", "chart": "usage-share"},
                            {"title": f"{h}历代汤剂用量", "type": "box", "from": "study.usage", "chart": "usage-doses"},
                            {"title": f"{h}汤剂用量与成书年代", "type": "scatter", "from": "study.usage", "chart": "usage-dose-years"},
                            {"title": f"{h}的炮制与用法注", "type": "stack", "from": "study.usage", "chart": "usage-processing"}],
                "tables": [_shell(f"各时期写出组成中含{h}的比例", "study.usage", [("时期", ""), ("写出组成（首）", N), (f"含{h}，n (%)", NP),
                                  ("95% CI（%）", CI)], PERIOD_STUBS, stats="比例的 95% CI：Wilson 法；趋势：Cochran–Armitage 检验（z，P）"),
                           _shell(f"历代汤剂中{h}的用量", "study.usage", [("时期", ""), ("n", N), ("M (P25, P75)", MIQR), ("x̄ ± s", MSD), ("范围", CI)],
                                  PERIOD_STUBS, stats="Kruskal–Wallis 检验（H，df，P）；年代与用量的 Spearman 相关（ρ，P）",
                                  groups={c: "折合克数（g）" for c in ("M (P25, P75)", "x̄ ± s", "范围")})],
                "limitations": ["剂量只计以重量写出者；以枚、升、方寸匕计者不折合", "“方中最大剂量”只是剂量线索，不是君臣佐使的判定"]}

    def _pairs(self, ent: dict[str, Any]) -> dict[str, Any]:
        hs = ent["herbs"][:2]
        h = hs[0]
        other = hs[1] if len(hs) > 1 else None

        def pilot() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
            r = self.s.pairs(h)
            out = [{"text": f"含{h}的写出组成中，显著的配伍药对 {r.get('significant', 0)} 对（Fisher + BH，q = 0.05）", "n": r.get("significant", 0)}]
            if other:
                row = next((x for x in r.get("partners", []) if x["with"] == other or x["key"].endswith(other)), None)
                out.append({"text": f"{h}—{other}：" + (f"同方 {row['support']} 次，提升度 {row['lift']}，{'显著' if row['significant'] else '未达显著'}" if row else "未达最小同方次数"),
                            "background": True})
            return out, r.get("charts", [])

        return {"label": "配伍规律", "pilot": pilot,
                "objectives": [f"检验{h}" + (f"与{other}" if other else "") + "在历代组成中的配伍是否高于随机"],
                "questions": [f"{h}常与哪些药同方？" + (f"{h}与{other}的同方是否高于随机？" if other else "")],
                "hypotheses": [{"statement": f"{h}与{other or '其常用之药'}的同方共现高于随机",
                                "prediction": "同方次数高于独立假设下的期望（提升度 > 1）",
                                "test": "单侧 Fisher 精确检验，Benjamini–Hochberg 校正（q = 0.05）；以 NPMI 排序",
                                "falsified_if": "校正后不显著",
                                "alternatives": ["一方被多书转抄造成的共现（按著作计数可减轻）", "两药各自常用而非彼此相配（提升度可辨）"]}],
                "methods": [{"title": f"{h}的配伍", "tool": "study.pairs", "args": {"herb": h},
                             "command": f"taochronos study pairs {h} --charts figures", "purpose": "药对统计、三药同用、按时期", "outputs": "配伍表"}],
                "analysis": [{"name": "配伍检验", "method": "单侧 Fisher 精确检验 + Benjamini–Hochberg", "detail": "支持度 ≥ 5；NPMI 排序以免稀见药居前"}],
                "figures": [{"title": f"{h}同方药物的关联强度（OR 与 95% CI）", "type": "forest", "from": "study.pairs", "chart": "pairs-forest"},
                            {"title": f"{h}常相配伍之药", "type": "hbar", "from": "study.pairs", "chart": "pairs-partners"}],
                "tables": [_shell(f"与{h}同方的药物及其关联强度", "study.pairs", [("药物", ""), ("同方（首）", N), (f"{h}→该药", PCT),
                                  (f"该药→{h}", PCT), ("提升度", "×.××"), ("OR (95% CI)", ORCI), ("P", P)], ["……"],
                                  stats="单侧 Fisher 精确检验，Benjamini–Hochberg 校正（q = 0.05）；OR 的 95% CI：Woolf 法",
                                  groups={f"{h}→该药": "置信度（%）", f"该药→{h}": "置信度（%）"})],
                "limitations": ["共现是书写的关联，不是疗效的证据"]}

    def _incompat(self, ent: dict[str, Any]) -> dict[str, Any]:
        target = _first(ent["formulas"]) or _first(ent["herbs"])

        def pilot() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
            r = self.s.incompat(target) if target else self.s.incompat()
            st = r.get("statements", {})
            s = r.get("summary", {})
            out = [{"text": f"所检药对 {s.get('pairs', 0)} 对，文献中有“反”“畏”之说者 {s.get('attested', 0)} 对；写出组成中仍同用者 {s.get('written_together', 0)} 对",
                    "n": s.get("attested", 0)}]
            for x in (st.get("pairs") or [])[:2]:
                e = x.get("earliest_uncompiled") or x["earliest"]
                out.append({"text": f"“{x['pair']}”之说见于 {x['works']} 部著作，辑本之外最早见于{e['locator']}", "passage_id": e.get("passage_id"), "background": True})
            if r.get("check", {}).get("flagged"):
                out.append({"text": f"{target}的原方含 " + "、".join(x["pair"] for x in r["check"]["flagged"]), "background": True})
            return out, r.get("charts", [])

        return {"label": "配伍禁忌", "pilot": pilot,
                "objectives": ["考察十八反、十九畏之说的形成与流传，以及写出组成中反、畏之药同用的情形"],
                "questions": ["十八反、十九畏所列药对的“反”“畏”之说各首见于何书？歌诀何时出现？",
                              "历代方书中有哪些组成仍将反、畏之药同用？集中于何时？"],
                "hypotheses": [{"statement": "十八反所列药对的“相反”之说在唐以前已有记载",
                                "prediction": "辑本之外的最早见证早于 907 年",
                                "test": "配伍禁忌：各药对“反”之陈述的最早见证（辑本另计）",
                                "falsified_if": "辑本之外的最早见证晚于唐",
                                "alternatives": ["辑本所附七情文字出于后世（以层次判定年代）"]},
                               {"statement": "反、畏之药同用的组成集中于唐宋方书",
                                "prediction": "同用者按时期的著作数以隋唐五代、宋金元为多",
                                "test": "各时期写出组成中同用的著作数（每部著作一次）",
                                "falsified_if": "明清的同用著作数不少于唐宋",
                                "alternatives": ["唐宋方书存世较多（以各期组成总数为分母比较）"]}],
                "methods": [{"title": "反畏之说与同用之方", "tool": "study.incompat", "args": {"target": target} if target else {},
                             "command": f"taochronos study incompat {target or ''} --charts figures".replace("  ", " "),
                             "purpose": "陈述的最早见证、歌诀、同用之方", "outputs": "药对表、时间线、热图"}],
                "analysis": [{"name": "首见", "method": "按成书年代下限，辑本另计", "detail": "一部著作只计一次"}],
                "figures": [{"title": "反、畏之药同见于写出的组成", "type": "heatmap", "from": "study.incompat", "chart": "incompat-together"},
                            {"title": "“反”“畏”之说的最早见证", "type": "timeline", "from": "study.incompat", "chart": "incompat-firsts"}],
                "tables": [_shell("言“反”“畏”的著作与最早见证", "study.incompat", [("药对", ""), ("著作（部）", N), ("最早见证", "《……》"),
                                  ("成书年代", N)], ["甘草反甘遂", "……"], stats="一部著作计一次；辑本另计"),
                           _shell("反、畏之药同见于写出的组成", "study.incompat", [("药对", ""), ("著作（部）", N), ("各时期（部）", TXT),
                                  ("所见之方", TXT)], ["……"], stats="文本事实：同用见于书中，不说明合理或安全")],
                "limitations": ["同用只说明文献中有此组成，不说明其合理或无害；七情之“相畏”与十九畏之“畏”含义不同"]}

    def _network(self, ent: dict[str, Any]) -> dict[str, Any]:
        target = _first(ent["formulas"]) or _first(ent["findings"])

        def pilot() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
            r = self.s.network(target)
            items = r.get("findings") or r.get("formulas") or []
            return ([{"text": f"{target}的治疗语句 {r.get('indications', 0)} 条；最常见的" + ("所见" if r.get("findings") else "方") + "："
                              + "、".join(x.get("finding") or x.get("formula") for x in items[:5]), "n": r.get("indications", 0)}], r.get("charts", []))

        return {"label": "方证关系", "pilot": pilot,
                "objectives": [f"整理{target}在治疗语句中的方证对应"],
                "questions": [f"{target}在历代治疗语句中对应哪些" + ("症状、脉象与病证？" if ent["formulas"] else "方剂？")],
                "hypotheses": [{"statement": f"{target}的方证对应在后世有所扩展",
                                "prediction": "后世治疗语句中出现早期未见的所见（或方）",
                                "test": "按时期比较对应的所见（或方）",
                                "falsified_if": "后世所见均已见于早期",
                                "alternatives": ["后世书籍数量多造成的“扩展”（以提升度而非次数比较）"]}],
                "methods": [{"title": "方证网络", "tool": "study.network", "args": {"target": target},
                             "command": f"taochronos study network {target} --charts figures", "purpose": "所见或方、提升度、时期", "outputs": "方证表"}],
                "analysis": [{"name": "关联强度", "method": "提升度、NPMI", "detail": "所见在方名之前、同一治疗语句中"}],
                "figures": [{"title": f"{target}的方证对应", "type": "hbar", "from": "study.network", "chart": "network-findings"}],
                "tables": [_shell(f"{target}的方证对应", "study.network", [("所见", ""), ("次数", N), ("占（%）", PCT), ("提升度", "×.××")], ["……"],
                                  stats="提升度：同见次数与独立期望之比；每部著作一次")],
                "limitations": ["方名前所列之症不一定是该方所治（语句结构为规则阅读）"]}

    def _term(self, ent: dict[str, Any]) -> dict[str, Any]:
        t = _first(ent["terms"]) or _first(ent["findings"])

        def pilot() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
            r = self.s.term(t)
            total = sum(p["passages"] for p in r.get("periods", []))
            trend = r.get("trend") or {}
            out = [{"text": f"含“{t}”的段落 {total} 段" + (f"；历期趋势 z = {trend['z']:.2f}" if trend.get("z") is not None else ""), "n": total}]
            if r.get("earliest"):
                e = r["earliest"][0]
                out.append({"text": f"“{t}”的早期用例见于{e['locator']}", "passage_id": e["passage_id"], "background": True})
            return out, r.get("charts", [])

        return {"label": "术语源流", "pilot": pilot,
                "objectives": [f"考察“{t}”一词的历代使用频率、搭配与含义的变化"],
                "questions": [f"“{t}”在各时期的使用频率如何变化？其含义在何时发生转变？"],
                "hypotheses": [{"statement": f"“{t}”的使用频率存在历期趋势",
                                "prediction": "各期每万段的出现率不同且呈单调趋势",
                                "test": "Cochran–Armitage 趋势检验；各期 95% Wilson 区间",
                                "falsified_if": "|z| < 1.96",
                                "alternatives": ["专书集中于某一时期造成的峰值（看论述最密的著作）"]},
                               {"statement": f"“{t}”的含义在某一时期发生转变",
                                "prediction": "义项份额在某一时期前后显著不同",
                                "test": "语义演变：义项份额的变点",
                                "falsified_if": "未见显著变点",
                                "alternatives": ["义项判别的规则误读（核对义项样例）"]}],
                "methods": [{"title": f"“{t}”的术语源流", "tool": "study.term", "args": {"term": t},
                             "command": f"taochronos study term {t} --charts figures", "purpose": "各期频率、趋势、首见、搭配", "outputs": "按时期的表与图"},
                            {"title": f"“{t}”的义项", "tool": "study.senses", "args": {"term": t},
                             "command": f"taochronos study senses {t} --charts figures", "purpose": "义项份额与变点", "outputs": "义项表"}],
                "analysis": [{"name": "频率", "method": "每万段出现率与 Wilson 区间", "detail": "分母为该期全部段落"}],
                "figures": [{"title": f"“{t}”各时期出现率", "type": "line", "from": "study.term", "chart": "term-periods"},
                            {"title": f"“{t}”各义项的历代份额", "type": "stack", "from": "study.senses", "chart": "senses-shares"}],
                "tables": [_shell(f"“{t}”各时期的出现率", "study.term", [("时期", ""), ("段落总数", N), ("含该词段落", N), ("每万段 (95% CI)", "××.× (××.×–××.×)")],
                                  PERIOD_STUBS, stats="每万段出现率与 Wilson 区间；趋势：Cochran–Armitage 检验（z，P）")],
                "limitations": [f"“{t}”之古义不等同现代病名；现代概念只作候选，不作等同"]}

    def _names(self, ent: dict[str, Any]) -> dict[str, Any]:
        x = _first(ent["herbs"]) or _first(ent["formulas"]) or _first(ent["terms"])
        return {"label": "名称考",
                "objectives": [f"考察{x}的历代名称（本名、异名、讳改名）及其更替"],
                "questions": [f"{x}在历代有哪些名称？首选之名何时改变？"],
                "hypotheses": [{"statement": f"{x}的首选之名在某一时期更替",
                                "prediction": "各期以某名为多，其后为另一名所取代",
                                "test": "名称考：各名称按时期的著作份额与更替点",
                                "falsified_if": "各期首选之名不变",
                                "alternatives": ["避讳改字只影响某些版本（看版本年代）"]}],
                "methods": [{"title": f"{x}的名称", "tool": "study.names", "args": {"term": x},
                             "command": f"taochronos study names {x} --charts figures", "purpose": "名称、首见、更替、等同之文", "outputs": "名称表"}],
                "figures": [{"title": f"{x}各名称的历代份额", "type": "stack", "from": "study.names", "chart": "names-shares"}],
                "tables": [_shell(f"{x}各名称的历代份额", "study.names", [("时期", ""), ("名称一（%）", PCT), ("名称二（%）", PCT), ("……", "")], PERIOD_STUBS,
                                  stats="各时期言及此物的段落中各名称所占份额")]}

    def _modern(self, ent: dict[str, Any]) -> dict[str, Any]:
        x = _first(ent["herbs"]) or _first(ent["formulas"]) or _first(ent["findings"]) or _first(ent["terms"])
        return {"label": "古今对照",
                "objectives": ["在古籍取证之外，另行检索现代证据，并按研究设计分层"],
                "questions": [f"{x or '所论对象'}的现代证据属何种研究设计？与古籍记载是否属于同一层次？"],
                "hypotheses": [],
                "methods": [{"title": "现代证据", "tool": "modern.search", "args": {"query": x or ""},
                             "command": f'taochronos modern search "{x or ""}"', "purpose": "按设计与人群分层的文献", "outputs": "证据表"}],
                "analysis": [{"name": "证据分层", "method": "按研究设计与人群", "detail": "动物实验、细胞实验与网络药理不作为人体疗效的证据"}],
                "tables": [_shell("古今对照的现代证据", "modern.search", [("文献", ""), ("研究设计", TXT), ("人群", TXT), ("结局", TXT), ("证据等级", TXT)],
                                  ["……"], stats="按研究设计与人群分层；动物、细胞与网络药理研究不作为人体疗效的证据")],
                "limitations": ["古籍记载与现代证据分属不同知识空间：不得以现代疗效证古书之是，亦不得以古书证现代疗效"]}

    def _general(self, ent: dict[str, Any]) -> dict[str, Any]:
        question = ent.get("question", "")
        topic = _QUESTION_WORDS.sub("", question).strip() or question

        def pilot() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
            r = self.s.term(topic)
            total = sum(p["passages"] for p in r.get("periods", []))
            out = [{"text": f"含“{topic}”的段落 {total} 段", "n": total}]
            if r.get("earliest"):
                e = r["earliest"][0]
                out.append({"text": f"“{topic}”的早期用例见于{e['locator']}", "passage_id": e["passage_id"], "background": True})
            return out, r.get("charts", [])

        return {"label": "综合检索", "pilot": pilot if topic else None,
                "objectives": [f"在语料中检索与“{topic}”相关的原文，确定可研究的对象与范围"],
                "questions": [f"“{topic}”涉及哪些方、药、病证与术语？语料中有多少可用的见证？"],
                "hypotheses": [],
                "methods": [{"title": "检索", "tool": "classics.search", "args": {"query": question}, "command": f'taochronos search "{question}"',
                             "purpose": "相关段落与年代分布", "outputs": "段落表"},
                            {"title": "术语源流", "tool": "study.term", "args": {"term": topic}, "command": f"taochronos study term {topic} --charts figures",
                             "purpose": "各期频率与首见", "outputs": "按时期的表与图"},
                            {"title": "阅读门径", "tool": "study.reading", "args": {"topic": topic}, "command": f"taochronos study reading {topic}",
                             "purpose": "源头经典、历代发挥与专书", "outputs": "书目"}],
                "limitations": ["问题中未识别出方、药或术语：写出具体的方名、药名或术语，可得到可检验的假设"]}


COMMON_VARIABLES = [
    {"name": "见证年代", "definition": "所据之书的成书年代下限（terminus ante quem）；层次不同者按层次", "measure": "年；分析时期（先秦两汉…民国）", "source": "书目"},
    {"name": "著作", "definition": "同一著作的多个录本（版本、转录）合为一个来源", "measure": "计数单位", "source": "书目（work）"},
]
COMMON_ANALYSIS = [
    {"name": "比例的区间", "method": "95% Wilson 区间", "detail": "小样本时期的比例须连同区间报告"},
    {"name": "多重比较", "method": "Benjamini–Hochberg", "detail": "同时检验多个药对或多个时期时控制错误发现率"},
]
QUALITY = [
    "每条结论附原文、书名、卷篇与段落号，界面逐字核验引文（✓ 相符、≠ 误引、✕ 无此段）",
    "来源依存：同一著作的录本只计一次；转抄与引用（语义复用、传播链）不作为独立证据",
    "研究合同的验收标准：证据须由引文明言、至少两个独立来源、证伪审查、无未决的严重异议、提出替代解释",
    "门控：G0 来源、G1 录文、G2 文献学、G3 语义、G4 主张溯源、G5 跨来源、G6 证伪、G7 专家、G8 现代证据",
    "以今律古之防：古今概念分层表述，不以现代病名释古",
]
OUTPUTS = ["研究方案（本文件，Markdown 与 JSON；表格模板另可下载为 Word）", "见证表与数据包（CSV + datapackage.json：taochronos study dataset）",
           "图（期刊样式的 SVG、PNG、TIFF，组图；CSV 数据：--charts）", "三线表（Word、LaTeX、CSV：--charts）",
           "研究报告（原文、注家解释、计算推断、现代医学四层分述）"]

__all__ = ["KINDS", "NOTICE", "ProtocolDesigner"]
