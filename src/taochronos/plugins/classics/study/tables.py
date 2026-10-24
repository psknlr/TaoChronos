"""表格 — the tables of the study results as a paper prints them: three-line tables (三线表).

A study result says what the texts write; its tables put the numbers a paper reports into the form a journal prints:
a numbered title above, grouped column heads, the statistics in their usual notation — n (%), M (P25, P75), x̄ ± s,
a 95 % CI, an odds ratio with its interval, P to three decimals (P < 0.001 below) — and the notes below: what each
abbreviation means, which test gave which number, how the texts were counted.  Each table is a small declarative
specification (``TABLE_VERSION``), built from the full result and carried under ``tables``: the web client prints it
as a three-line table with downloads (Word, LaTeX, CSV, Markdown, and copy for Word or Excel; ``web/js/table.js``),
``taochronos study … --charts <dir>`` writes it (``tablefmt.py``), and the model reads only the titles
(``tables_shown``), as it does of the charts.

A specification: ``id``, ``title`` (without its number: a page numbers the tables of a result 表 1, 表 2 … in order),
``columns`` [{key, label, align (left, center, right), group?}] — consecutive columns of one ``group`` share a head
above theirs — ``rows`` (records of display strings, in the columns' keys), ``notes`` (the lines under the table) and
``source``.  The cells are text: a table shows what the result computed, formatted, and adds no inference.
"""

from __future__ import annotations

import math
from typing import Any, Callable

from .charts import WORDS, _period_order

TABLE_VERSION = 1
ALIGN = {"l": "left", "c": "center", "r": "right"}


def table(id_: str, title: str, columns: list[tuple[Any, ...]], rows: list[dict[str, Any]], *,
          notes: list[str | None] | None = None, source: str | None = None) -> dict[str, Any]:
    """One table specification.  ``columns``: (key, label, align[, group]) — align l, c or r."""
    cols = []
    for c in columns:
        key, label, align = c[0], c[1], c[2]
        col: dict[str, Any] = {"key": key, "label": label, "align": ALIGN.get(align, align)}
        if len(c) > 3 and c[3]:
            col["group"] = c[3]
        cols.append(col)
    out: dict[str, Any] = {"version": TABLE_VERSION, "id": id_, "title": title, "columns": cols,
                           "rows": [{k: "" if v is None else str(v) for k, v in r.items()} for r in rows],
                           "notes": [n for n in (notes or []) if n]}
    if source:
        out["source"] = source
    return out


# ------------------------------------------------------------------ numbers as a paper writes them
def fixed(x: Any, digits: int = 1) -> str:
    return "" if x is None else f"{float(x):.{digits}f}"


def plain(x: Any) -> str:
    """A number without trailing zeros (3, 0.5, 1.25)."""
    if x is None or x == "":
        return ""
    return f"{float(x):.3f}".rstrip("0").rstrip(".") if not float(x).is_integer() else str(int(x))


def n_pct(k: int, n: int, digits: int = 1) -> str:
    """n (%)."""
    return f"{k} ({k / n * 100:.{digits}f})" if n else str(k)


def pct(x: Any, digits: int = 1) -> str:
    return "" if x is None else f"{float(x) * 100:.{digits}f}"


def ci_pct(lo: Any, hi: Any, digits: int = 1) -> str:
    return "" if lo is None or hi is None else f"{float(lo) * 100:.{digits}f}–{float(hi) * 100:.{digits}f}"


def est(x: Any) -> str:
    """An estimate (an odds ratio, a lift) to the precision its size deserves."""
    if x is None:
        return ""
    v = float(x)
    if not math.isfinite(v):
        return "∞"
    a = abs(v)
    return f"{v:.0f}" if a >= 100 else f"{v:.1f}" if a >= 10 else f"{v:.2f}" if a >= 0.01 or a == 0 else f"{v:.3f}"


def est_ci(x: Any, lo: Any, hi: Any) -> str:
    """An estimate with its interval: 1.85 (1.32–2.60)."""
    return f"{est(x)} ({est(lo)}–{est(hi)})" if x is not None and lo is not None and hi is not None else est(x)


def p_value(p: Any) -> str:
    """P as journals print it: <0.001, 0.045, 0.41."""
    if p is None:
        return ""
    p = float(p)
    return "<0.001" if p < 0.001 else f"{p:.3f}" if p < 0.1 else f"{p:.2f}"


def p_eq(p: Any) -> str:
    """P < 0.001 / P = 0.045 — for a note."""
    text = p_value(p)
    return f"P {text[0]} {text[1:]}" if text.startswith("<") else f"P = {text}"


def med_iqr(q: dict[str, Any] | None, digits: int = 1) -> str:
    """M (P25, P75)."""
    if not q:
        return ""
    f = (lambda v: fixed(v, digits)) if digits >= 0 else plain
    return f"{f(q['median'])} ({f(q['q1'])}, {f(q['q3'])})"


def mean_sd(q: dict[str, Any] | None, digits: int = 1) -> str:
    return "" if not q or q.get("mean") is None else f"{fixed(q['mean'], digits)} ± {fixed(q.get('sd') or 0, digits)}"


def spread(q: dict[str, Any] | None, digits: int = 1) -> str:
    return "" if not q else f"{fixed(q['min'], digits)}–{fixed(q['max'], digits)}"


def _year(y: Any) -> str:
    if y is None:
        return ""
    y = int(round(float(y)))
    return f"前{-y}" if y < 0 else str(y)


def _years(w: dict[str, Any] | None) -> str:
    ys = (w or {}).get("years")
    if not ys:
        return ""
    a, b = int(ys[0]), int(ys[1])
    return _year(a) if a == b else f"{_year(a)}–{_year(b)}"


def _book(w: dict[str, Any] | None) -> str:
    loc = (w or {}).get("locator") or ""
    return loc.split("》")[0] + "》" if "》" in loc else loc


COUNTED = "每部著作计一次：同一著作诸本中的同一组成只计一次。"


# ------------------------------------------------------------------ builders, one per study function
def usage(r: dict[str, Any], base: Any) -> list[dict[str, Any]]:
    name = r.get("drug", {}).get("name", "")
    out = []
    rows = [{"period": x["period"], "n": x["compositions"], "with": n_pct(x["with"], x["compositions"]), "ci": ci_pct(*x["ci"])}
            for x in r.get("by_period", [])]
    if rows:
        trend = r.get("trend") or {}
        out.append(table("usage-periods", f"各时期写出组成中含{name}的比例", [
            ("period", "时期", "l"), ("n", "写出组成（首）", "c"), ("with", f"含{name}，n (%)", "c"), ("ci", "95% CI（%）", "c")], rows,
            notes=["CI：置信区间（Wilson 法）。" + COUNTED,
                   f"趋势检验（Cochran–Armitage，未定期除外）：z = {trend['z']:.2f}，{p_eq(trend['p'])}。" if trend.get("z") is not None else None]))
    doses = r.get("doses") or {}
    if doses.get("by_period"):
        rows = []
        for x in doses["by_period"]:
            g = x.get("grams")
            rows.append({"period": x["period"], "n": x["n"], "liang": med_iqr(x["liang"], -1), "grams": med_iqr(g, 1),
                         "mean": mean_sd(g, 1), "range": spread(g, 1), "common": "、".join(c["dose"] for c in x.get("common", []))})
        test = doses.get("test") or {}
        trend = doses.get("trend") or {}
        out.append(table("usage-doses", f"历代汤剂中{name}的用量", [
            ("period", "时期", "l"), ("n", "n", "c"), ("liang", "M (P25, P75)", "c", "原书剂量（两）"),
            ("grams", "M (P25, P75)", "c", "折合克数（g）"), ("mean", "x̄ ± s", "c", "折合克数（g）"), ("range", "范围", "c", "折合克数（g）"),
            ("common", "常见写法", "l")], rows,
            notes=["M (P25, P75)：中位数（第 25、75 百分位数）；x̄ ± s：均数 ± 标准差。只计汤剂中以重量写出的剂量；丸、散、膏与煮散为一料之量，不在此表。",
                   f"各时期折合克数的 Kruskal–Wallis 检验（n ≥ 3 的 {test['groups']} 个时期）：H = {test['h']:.2f}，df = {test['df']}，{p_eq(test['p'])}。"
                   if test.get("h") is not None else None,
                   f"年代与折合克数的 Spearman 相关：ρ = {trend['rho']:.2f}，{p_eq(trend['p'])}，n = {trend['n']}。" if trend.get("rho") is not None else None,
                   (r.get("metrology_notice") or "").replace("以下为", "表中剂量为", 1) or None]))
    if doses.get("by_form"):
        rows = [{"form": x["form"], "n": x["n"], "liang": med_iqr(x["liang"], -1), "range": f"{plain(x['liang']['min'])}–{plain(x['liang']['max'])}"}
                for x in doses["by_form"]]
        out.append(table("usage-forms", f"各剂型中{name}的原书剂量", [
            ("form", "剂型", "l"), ("n", "n", "c"), ("liang", "M (P25, P75)（两）", "c"), ("range", "范围（两）", "c")], rows,
            notes=["丸、散、膏与煮散所记为一料之量，与汤剂一剂之量不可相比。剂型由组成后所写制法判定，未写者按方名。"]))
    if r.get("partners"):
        with_ = r.get("with") or 0
        rows = [{"drug": x["with"], "n": x["compositions"], "share": pct(x.get("share")), "lift": est(x.get("lift"))} for x in r["partners"][:20]]
        out.append(table("usage-partners", f"与{name}同用最多的药物", [
            ("drug", "药物", "l"), ("n", "同方组成（首）", "c"), ("share", f"占含{name}组成（%）", "c"), ("lift", "提升度", "c")], rows,
            notes=[f"含{name}的写出组成共 {with_} 首。提升度：同见次数与两药独立时期望次数之比（> 1 为多于随机）。" + COUNTED]))
    return out


def pairs(r: dict[str, Any], base: Any) -> list[dict[str, Any]]:
    out = []
    n = r.get("compositions") or 0
    sig_note = "P：单侧 Fisher 精确检验；* 经 Benjamini–Hochberg 校正后 q < 0.05。"
    measures = ("支持度：两药同见的写出组成数；置信度 A→B：含 A 的组成中同含 B 的比例；提升度：同见次数与独立期望之比；"
                "OR：比值比（Woolf 法 95% CI，有零格时各格加 0.5）。")
    herb = r.get("herb")
    if r.get("partners"):
        rows = [{"drug": x["with"], "n": x["support"], "conf_a": pct(x["p_with_given_drug"]), "conf_b": pct(x["p_drug_given_with"]),
                 "lift": est(x["lift"]), "or": est_ci(x.get("or"), *(x.get("or_ci") or [None, None])),
                 "p": p_value(x.get("p")) + ("*" if x.get("significant") else "")} for x in r["partners"][:30]]
        out.append(table("pairs-partners", f"与{herb}同方的药物及其关联强度", [
            ("drug", "药物", "l"), ("n", "同方（首）", "c"), ("conf_a", f"{herb}→该药", "c", "置信度（%）"),
            ("conf_b", f"该药→{herb}", "c", "置信度（%）"), ("lift", "提升度", "c"), ("or", "OR (95% CI)", "c"), ("p", "P", "c")], rows,
            notes=[f"写出组成 {n} 首；同方至少 {r.get('min_support')} 次者。" + COUNTED, measures, sig_note]))
        return out
    if r.get("frequency"):
        rows = [{"rank": i, "drug": x["drug"], "n": x["compositions"], "share": pct(x["share"])} for i, x in enumerate(r["frequency"], 1)]
        out.append(table("pairs-frequency", "高频药物", [("rank", "序号", "c"), ("drug", "药物", "l"), ("n", "频次（首）", "c"),
                                                       ("share", "频率（%）", "c")], rows,
                         notes=[f"频率：含该药的写出组成占全部 {n} 首的比例。" + COUNTED]))
    if r.get("rules"):
        rows = [{"rule": f"{x['if']} → {x['then']}", "support": n_pct(x["support"], n), "confidence": pct(x["confidence"]), "lift": est(x["lift"])}
                for x in r["rules"]]
        out.append(table("pairs-rules", "药物关联规则", [("rule", "规则（前项 → 后项）", "l"), ("support", "支持度，n (%)", "c"),
                                                     ("confidence", "置信度（%）", "c"), ("lift", "提升度", "c")], rows,
                         notes=[f"取显著药对（单侧 Fisher 精确检验，Benjamini–Hochberg 校正 q < 0.05，同方至少 {r.get('min_support')} 次）"
                                "两个方向中置信度 ≥ 50% 的规则，按置信度排序。", measures]))
    if r.get("pairs"):
        rows = [{"pair": f"{x['a_name']}—{x['b_name']}", "n": x["support"], "lift": est(x["lift"]), "npmi": fixed(x["npmi"], 3),
                 "or": est_ci(x.get("or"), *(x.get("or_ci") or [None, None])), "p": p_value(x["p"]) + ("*" if x.get("significant") else "")}
                for x in r["pairs"][:30]]
        out.append(table("pairs-top", "显著药对", [("pair", "药对", "l"), ("n", "同方（首）", "c"), ("lift", "提升度", "c"),
                                               ("npmi", "NPMI", "c"), ("or", "OR (95% CI)", "c"), ("p", "P", "c")], rows,
                         notes=["NPMI：归一化点互信息（−1 至 1，0 为独立），按之排序以免稀见药居前。", measures, sig_note]))
    if r.get("clusters"):
        rows = [{"cluster": f"第 {c['cluster']} 类", "k": len(c["drugs"]), "drugs": "、".join(c["drugs"])} for c in r["clusters"]]
        out.append(table("pairs-clusters", "高频药物的聚类", [("cluster", "类别", "l"), ("k", "味数", "c"), ("drugs", "药物", "l")], rows,
                         notes=["系统聚类：频次最高的药物，以 1 − Jaccard 系数（两药所在写出组成的重合度）为距离，平均联结法（UPGMA）；"
                                "在相邻两次合并距离之差最大处切分。"]))
    return out


def compare(r: dict[str, Any], base: Any) -> list[dict[str, Any]]:
    found = [f for f in r.get("formulas", []) if f.get("found")]
    out = []
    if len(found) >= 2:
        keys = [f"f{i}" for i in range(len(found))]
        rows = []
        for row in r.get("matrix", []):
            cells = {}
            for k, f in zip(keys, found):
                c = row.get(f["name"])
                cells[k] = "—" if not c else (c.get("dose") or "?") + (f"（{plain(c['ratio'])}）" if c.get("ratio") is not None else "")
            rows.append({"drug": row["drug"], **cells})
        which = "通行方（见证最多）" if r.get("which") == "current" else "原方（最早见）"
        out.append(table("compare-doses", "、".join(f["name"] for f in found) + "的组成与剂量", [("drug", "药物", "l")]
                         + [(k, f["name"], "c") for k, f in zip(keys, found)], rows,
                         notes=[f"各方取其{which}的一条见证：" + "；".join(f"{f['name']}据{_book(f.get('witness'))}（{_years(f.get('witness'))}）" for f in found) + "。",
                                "括号内为配伍比例：以该方最大重量为 1；以枚、升等计者无比例。“—”：该方无此药。",
                                (r.get("metrology_notice") or "").replace("以下为", "表中剂量为", 1) or None]))
        if r.get("pairs"):
            rows = [{"a": x["a"], "b": x["b"], "shared": "、".join(x["shared"]), "only_a": "、".join(x["only_a"]) or "—",
                     "only_b": "、".join(x["only_b"]) or "—", "jaccard": fixed(x["jaccard"], 2),
                     "overlap": fixed(x["weighted_overlap"], 2) if x.get("weighted_overlap") is not None else "—", "verdict": x["verdict"]}
                    for x in r["pairs"]]
            out.append(table("compare-pairs", "方剂两两比较", [("a", "方 A", "l"), ("b", "方 B", "l"), ("shared", "共有药物", "l"),
                                                         ("only_a", "仅 A", "l"), ("only_b", "仅 B", "l"), ("jaccard", "Jaccard", "c"),
                                                         ("overlap", "剂量加权重合", "c"), ("verdict", "结论", "c")], rows,
                             notes=["Jaccard：共有药味数 ÷ 两方药味并集数；剂量加权重合：两方各药剂量份额之较小者之和（两方均以重量写出剂量时）。",
                                    "结论：同方（药味与比例相同）、同药异量（药味相同、剂量不同）、加减化裁、异方。"]))
    return out


def family(r: dict[str, Any], base: Any) -> list[dict[str, Any]]:
    f = r.get("formula") or {}
    if not r.get("members"):
        return []
    rows = [{"formula": m["formula"], "relation": m["relation"], "added": "、".join(m["added"]) or "—", "removed": "、".join(m["removed"]) or "—",
             "works": m["works"], "earliest": f"{_book(m.get('earliest'))}（{_years(m.get('earliest'))}）" if m.get("earliest") else ""}
            for m in r["members"][:40]]
    return [table("family-members", f"{f.get('name', '')}的类方", [("formula", "方名", "l"), ("relation", "关系", "c"), ("added", "加", "l"),
                                                                   ("removed", "减", "l"), ("works", "著作（部）", "c"), ("earliest", "最早见", "l")], rows,
                  notes=[f"本方核心组成：{'、'.join(f.get('core', []))}。类方：其组成包含本方核心药味之大部、增药不多者；"
                         "关系为加味、减味、加减、同药异量、同方异名、合方。著作：写出该方组成的著作数。"])]


def term(r: dict[str, Any], base: Any) -> list[dict[str, Any]]:
    name = (r.get("term") or {}).get("name", "")
    rows = [{"period": p["period"], "total": p["total"], "n": p["passages"], "rate": fixed(p["per_10k"], 1),
             "ci": f"{fixed(p['ci_per_10k'][0], 1)}–{fixed(p['ci_per_10k'][1], 1)}" if p.get("ci_per_10k") else ""}
            for p in r.get("periods", []) if p.get("total")]
    if not rows:
        return []
    trend = r.get("trend") or {}
    return [table("term-periods", f"“{name}”各时期的出现率", [("period", "时期", "l"), ("total", "段落总数", "c"), ("n", "含该词段落", "c"),
                                                        ("rate", "每万段", "c"), ("ci", "95% CI", "c")], rows,
                  notes=["每万段：含该词（及其异名）的段落数 ÷ 该期段落总数 × 10 000；CI：Wilson 区间。",
                         f"趋势检验（Cochran–Armitage）：z = {trend['z']:.2f}，{p_eq(trend['p'])}。" if trend.get("z") is not None else None])]


def herb(r: dict[str, Any], base: Any) -> list[dict[str, Any]]:
    from .usage import NATURE_ORDER, base_nature

    name = (r.get("herb") or {}).get("name", "")
    out = []
    periods = [p for p in r.get("periods", []) if p.get("books")]
    if periods:
        counts = [{n: sum(v for k, v in (p.get("natures") or {}).items() if base_nature(k) == n) for n in NATURE_ORDER} for p in periods]
        used = [n for n in NATURE_ORDER if any(c[n] for c in counts)]
        rows = [{"period": p["period"], "books": p["books"], **{n: c[n] for n in used},
                 "flavors": "、".join(f"{k} {v}" for k, v in sorted((p.get("flavors") or {}).items(), key=lambda kv: -kv[1])[:4])}
                for p, c in zip(periods, counts)]
        out.append(table("herb-periods", f"历代本草所言{name}之性味", [("period", "时期", "l"), ("books", "本草著作（部）", "c")]
                         + [(n, n, "c", "言其性为（部）") for n in used] + [("flavors", "味（部）", "l")], rows,
                         notes=["一部著作言其性、味者各计一次；“大寒”“微寒”归入寒，余仿此。"]))
    firsts = [f for f in r.get("firsts", []) if f.get("years")]
    if firsts:
        rows = [{"field": f["field"], "value": f["value"], "where": _book(f), "year": _years(f)} for f in firsts[:30]]
        out.append(table("herb-firsts", f"{name}各项性能的首见", [("field", "项目", "l"), ("value", "所言", "l"), ("where", "首见", "l"),
                                                              ("year", "成书年代", "c")], rows,
                         notes=["首见：语料中最早言之的著作（按成书年代下限）；辑本另须回查。"]))
    return out


def properties(r: dict[str, Any], base: Any) -> list[dict[str, Any]]:
    drugs = [d for d in r.get("drugs", []) if d.get("works")]
    if not drugs:
        return []
    share = lambda m: "、".join(f"{k} {v * 100:.0f}" for k, v in list(m.items())[:4])  # noqa: E731
    rows = [{"drug": d["drug"], "works": d["works"], "natures": share(d["natures"]), "flavors": share(d["flavors"]),
             "toxicity": share(d["toxicity"]), "channels": share(d["channels"])} for d in drugs]
    out = [table("properties-drugs", "、".join(d["drug"] for d in drugs) + "的性味归经", [
        ("drug", "药物", "l"), ("works", "本草著作（部）", "c"), ("natures", "性", "l", "言之者占著作（%）"),
        ("flavors", "味", "l", "言之者占著作（%）"), ("toxicity", "毒", "l", "言之者占著作（%）"), ("channels", "归经", "l", "言之者占著作（%）")], rows,
        notes=["各药本草条目中言其性、味、毒、归经者占其著作之比；归经按十二经与脏腑的通行对应归并（手太阴 → 肺 …）。"])]
    prof = r.get("profile")
    if prof:
        rows = [{"kind": label, "values": "、".join(f"{k} {v * 100:.0f}" for k, v in list(prof[kind].items())[:8])}
                for kind, label in (("natures", "性"), ("flavors", "味"), ("channels", "归经"))]
        out.append(table("properties-profile", f"{r.get('formula')}全方的性味归经", [("kind", "项目", "l"), ("values", "份额（%）", "l")], rows,
                         notes=["按剂量加权：各药之份额乘以其重量占全方之比。" if prof.get("weighted_by") == "dose" else "各药等权（剂量未全以重量写出）。"]))
    return out


def incompat(r: dict[str, Any], base: Any) -> list[dict[str, Any]]:
    out = []
    stated = (r.get("statements") or {}).get("pairs") or []
    if stated:
        rows = []
        for x in stated:
            e = x.get("earliest_uncompiled") or x.get("earliest") or {}
            rows.append({"pair": x["pair"], "works": x["works"], "earliest": _book(e), "year": _years(e)})
        out.append(table("incompat-statements", "言“反”“畏”的著作与最早见证", [("pair", "药对", "l"), ("works", "著作（部）", "c"),
                                                                       ("earliest", "最早见证", "l"), ("year", "成书年代", "c")], rows,
                         notes=["最早见证不计辑本（如《神农本草经》）；一部著作只计一次。"]))
    together = [x for x in (r.get("formulas") or {}).get("pairs", []) if x.get("works")]
    if together:
        order = _period_order(base)
        rows = [{"pair": x["pair"], "works": x["works"], "periods": "、".join(f"{p} {x['periods'][p]}" for p in order if x["periods"].get(p)),
                 "formulas": "、".join(f["formula"] for f in x.get("formulas", [])[:6])} for x in together]
        out.append(table("incompat-together", "反、畏之药同见于写出的组成", [("pair", "药对", "l"), ("works", "著作（部）", "c"),
                                                                    ("periods", "各时期（部）", "l"), ("formulas", "所见之方", "l")], rows,
                         notes=[r.get("notice") or "文本事实：同用见于书中，不说明合理或安全。"]))
    return out


def network(r: dict[str, Any], base: Any) -> list[dict[str, Any]]:
    target = r.get("target") or ""
    if r.get("findings"):
        rows = [{"x": x["finding"], "n": x["support"], "share": pct(x.get("share")), "lift": est(x.get("lift"))} for x in r["findings"][:30]]
        return [table("network-findings", f"{target}的主治所见", [("x", "所见", "l"), ("n", "次数", "c"), ("share", "占（%）", "c"),
                                                              ("lift", "提升度", "c")], rows,
                      notes=[f"治疗语句中方名之前所见；{target}的治疗语句共 {r.get('indications', 0)} 条（每部著作一次）。"])]
    if r.get("formulas"):
        rows = [{"x": x["formula"], "n": x["support"], "share": pct(x.get("share")), "lift": est(x.get("lift"))} for x in r["formulas"][:30]]
        return [table("network-formulas", f"{target}所用之方", [("x", "方", "l"), ("n", "次数", "c"), ("share", "占（%）", "c"),
                                                            ("lift", "提升度", "c")], rows,
                      notes=[f"在方名之前言及{target}的治疗语句共 {r.get('indications', 0)} 条（每部著作一次）。"])]
    return []


RELATION_ORDER = ["原方·通行方", "原方", "通行方", "加减化裁", "同名异方", "孤例"]


def formula(r: dict[str, Any], base: Any) -> list[dict[str, Any]]:
    from .charts import witness_labels

    name = (r.get("formula") or {}).get("name", "")
    groups = r.get("groups") or []
    if not groups:
        return []
    rows = []
    for i, g in enumerate(groups[:12], 1):
        e = g.get("earliest") or {}
        rows.append({"group": f"{i}. {g.get('relation') or ''}", "core": "、".join(g.get("core_terms") or [])[:60], "n": g.get("witnesses", 0),
                     "books": "、".join(g.get("books") or [])[:60], "earliest": f"{_book(e)}（{_years(e)}）" if e else ""})
    out = [table("formula-groups", f"{name}写出组成的类别", [("group", "组成类别", "l"), ("core", "核心药味", "l"), ("n", "见证", "c"),
                                                        ("books", "见于", "l"), ("earliest", "最早见", "l")], rows,
                 notes=["组成按药味的 Jaccard 相似度（≥ 0.7）归类；最早见者为原方，见证最多者为通行方。"])]
    # the witnesses by period and by the group of their composition (the numbers of the figure)
    rel_of = {pid: (g.get("relation") or "").split("（")[0] for g in groups for pid in g.get("member_ids", [])}
    counts: dict[str, dict[str, int]] = {}
    for w in r.get("witnesses", []):
        per, rel = w.get("period") or "未定", rel_of.get(w.get("passage_id"), "其他")
        counts.setdefault(per, {})
        counts[per][rel] = counts[per].get(rel, 0) + 1
    rels = sorted({k for c in counts.values() for k in c}, key=lambda k: (RELATION_ORDER + [k]).index(k))
    if counts:
        keys = [f"r{i}" for i in range(len(rels))]
        rows = [{"period": p, **{k: counts[p].get(rel, 0) for k, rel in zip(keys, rels)}, "total": sum(counts[p].values())}
                for p in _period_order(base) if p in counts]
        rows.append({"period": "合计", **{k: sum(c.get(rel, 0) for c in counts.values()) for k, rel in zip(keys, rels)},
                     "total": sum(sum(c.values()) for c in counts.values())})
        out.append(table("formula-witnesses", f"{name}写出组成的见证（按时期与组成类别）",
                         [("period", "时期", "l")] + [(k, rel, "c", "组成类别（处）") for k, rel in zip(keys, rels)] + [("total", "合计（处）", "c")], rows,
                         notes=["见证：一处写出组成的原文（一书数处者分计）；组成类别见上表：原方为最早见者，通行方为见证最多者，"
                                "加减化裁为与之相近（Jaccard ≥ 0.5）者，同名异方为同名而组成不同者，孤例为只见一处者。"]))
    # the doses of the witnesses whose ratios are compared (the numbers of the figure), as written and as ratios
    ratios = [x for x in r.get("ratios", []) if x.get("ratio")][:4]
    if ratios:
        by_pid = {w.get("passage_id"): w for w in r.get("witnesses", [])}

        def key(ing: dict[str, Any], ratio: dict[str, Any]) -> str:  # a drug as the ratios name it: its family (桂类) or itself (生姜)
            family = str(ing.get("family") or "").split(":")[-1]
            names = ([family + "类"] if family else []) + [str(ing.get("term") or "")]
            return next((n for n in names if n in ratio), names[0])

        doses = [{key(ing, x["ratio"]): str(ing.get("dose") or "") for ing in (by_pid.get(x.get("passage_id")) or {}).get("ingredients", [])}
                 for x in ratios]
        drugs = list(dict.fromkeys([d for x in ratios for d in x["ratio"]] + [d for ds in doses for d in ds]))  # those by weight first
        keys = [f"w{i}" for i in range(len(ratios))]
        cell = lambda x, ds, d: ((ds.get(d) or "") + (f"（{plain(x['ratio'][d])}）" if d in x["ratio"] else "")) if d in ds or d in x["ratio"] else "—"  # noqa: E731
        rows = [{"drug": d, **{k: cell(x, ds, d) for k, x, ds in zip(keys, ratios, doses)}} for d in drugs]
        out.append(table("formula-ratios", f"{name}各见证的剂量与配伍比例", [("drug", "药物", "l")]
                         + [(k, label, "c") for k, label in zip(keys, witness_labels(ratios))], rows,
                         notes=["剂量照原书所写；括号内为配伍比例：以该见证中最大重量为 1，以枚、升等计者无比例。“—”：该见证无此药。"
                                "药物按同类归并（桂枝、桂心 → 桂类）。",
                                (r.get("metrology_notice") or "").replace("以下为", "表中剂量为", 1) or None]))
    return out


def names(r: dict[str, Any], base: Any) -> list[dict[str, Any]]:
    periods = [p for p in r.get("periods", []) if p.get("works")]
    if not periods:
        return []
    totals: dict[str, int] = {}
    for p in periods:
        for form, k in (p.get("names") or {}).items():
            totals[form] = totals.get(form, 0) + k
    forms = sorted(totals, key=lambda f: -totals[f])[:6]
    keys = [f"n{i}" for i in range(len(forms))]
    rows = [{"period": p["period"], "works": p["works"], **{k: n_pct((p.get("names") or {}).get(f, 0), p["works"]) for k, f in zip(keys, forms)},
             "preferred": p.get("preferred") or ""} for p in periods]
    switches = r.get("switches") or []
    return [table("names-shares", f"{r.get('term', '')}各名称的历代使用", [("period", "时期", "l"), ("works", "著作（部）", "c")]
                  + [(k, f, "c", "写此名的著作，n (%)") for k, f in zip(keys, forms)] + [("preferred", "首选之名", "c")], rows,
                  notes=["著作：写其任一名称的著作（每部著作计一次，按段落的层次定年）；一书可写数名，故各名之和可逾 100%。"
                         + ("" if len(totals) <= len(forms) else f"另有 {len(totals) - len(forms)} 名见名称表。"),
                         ("首选之名的更替（按百年分段）：" + "；".join(f"{x['from']} → {x['to']}（{_year(x['between'][0])}–{_year(x['between'][1])} 年间）"
                                                              for x in switches) + "。") if switches else None])]


def shell(t: dict[str, Any]) -> dict[str, Any]:
    """A protocol's table shell (protocol.py) as a table: its heads, a row of placeholders under each stub, and how its
    numbers will be computed — the table a paper will print, before it is filled; a shell the pilot filled
    (``protocol.fill``) with the rows it holds."""
    if t.get("filled") and t.get("rows"):
        cols = [(f"c{i}", label, "l" if i == 0 else "c") for i, label in enumerate(t["columns"])]
        return table(f"shell-{t.get('id') or t.get('number') or 1}", f"{t['title']}（预试验）", cols,
                     [{f"c{i}": v for i, v in enumerate(row)} for row in t["rows"]], notes=list(t.get("notes") or []))
    groups = t.get("groups") or {}
    cols = [(f"c{i}", label, "l" if i == 0 else "c", groups.get(label)) for i, label in enumerate(t["columns"])]
    rows = [{"c0": stub, **{f"c{i}": cell for i, cell in enumerate(t.get("cells") or []) if i}} for stub in t.get("stubs") or ["……"]]
    return table(f"shell-{t.get('id') or t.get('number') or 1}", f"{t['title']}（模板）", cols, rows,
                 notes=["表格模板：×× 为待填之数，按研究方法的步骤取得" + ("；预试验未得此表之数" if t.get("filled") is False else "") + "。"
                        + (f"统计：{t['statistics']}。" if t.get("statistics") else ""),
                        f"数据来自：{t['from']}。" if t.get("from") else None])


def senses(r: dict[str, Any], base: Any) -> list[dict[str, Any]]:
    series = [x for x in r.get("series", []) if x.get("occurrences")]
    if not series:
        return []
    term_ = r.get("term")
    name = term_.get("name") if isinstance(term_, dict) else term_
    label = {x["id"]: x.get("label") or x["id"] for x in r.get("senses", []) if isinstance(x, dict) and x.get("id")}
    ids = [k for k in dict.fromkeys(k for x in series for k in x.get("shares", {})) if k != "unassigned"]
    if not ids:  # no sense told apart (a term without curated senses): nothing to tabulate
        return []
    ids.sort(key=lambda k: -sum(x["shares"].get(k, 0) * x["occurrences"] for x in series))
    keys = [f"s{i}" for i in range(len(ids))]
    rows = [{"period": x["period"], "n": x["occurrences"], **{k: pct(x["shares"].get(i, 0)) for k, i in zip(keys, ids)},
             "none": pct(x["shares"].get("unassigned", 0))} for x in series]
    cp = r.get("change_point") or {}
    short = {i: i.split("#", 1)[-1] for i in ids}  # 消渴#病·三消 → 病·三消: unique, where the labels' heads (病名) are not
    return [table("senses-shares", f"“{name or ''}”各义项的历代份额", [("period", "时期", "l"), ("n", "用例（处）", "c")]
                  + [(k, short[i], "c", "义项（%）") for k, i in zip(keys, ids)] + [("none", "未判定", "c", "义项（%）")], rows,
                  notes=["义项：" + "；".join(f"{short[i]}，{label.get(i, i).split('：', 1)[-1]}" for i in ids)
                         + "。用例由规则按上下文判归义项，未判定者另列；每期份额之和为 100%。",
                         f"变点：约 {_year(cp['year'])} 年前后义项的分布相差最大（n₁n₂/n × Jensen–Shannon 散度 = {cp['statistic']:.2f}，置换检验 "
                         f"{p_eq(cp['p'])}；其前 {cp['n_before']} 例，其后 {cp['n_after']} 例）。"
                         if cp.get("year") is not None and cp.get("p") is not None else None])]


def casecompare(r: dict[str, Any], base: Any) -> list[dict[str, Any]]:
    groups = r.get("groups") or []
    if not groups:
        return []
    label = {"book": "医案集", "physician": "医家", "period": "时期", "author": "著者"}.get(r.get("by"), "组")
    rows = []
    for g in groups:
        o, rec = g.get("outcomes") or {}, g.get("recorded") or 0
        rows.append({"group": g["group"], "n": g["cases"], "visits": mean_sd(g.get("visits"), 2),
                     "improved": n_pct(o.get("improved", 0), rec), "ci": ci_pct(*(g.get("improved_ci") or (None, None))),
                     "died": n_pct(o.get("died", 0), rec),
                     "female": n_pct(round(g["female_share"] * g["sex_recorded"]), g["sex_recorded"])
                     if g.get("female_share") is not None else "",
                     "prior": pct(g.get("prior_share")),
                     "formulas": "、".join(f["name"] for f in (g.get("formulas") or [])[:3])})
    tests = r.get("tests") or {}
    oc, vk = tests.get("outcome") or {}, tests.get("visits") or {}
    return [table("casecompare-profile", f"各{label}医案概况", [
        ("group", label, "l"), ("n", "医案（案）", "r"), ("visits", "诊次 x̄ ± s", "r"),
        ("improved", "好转 n (%)", "r", "转归（记有转归者）"), ("ci", "好转率 95% CI", "r", "转归（记有转归者）"),
        ("died", "死亡 n (%)", "r", "转归（记有转归者）"), ("female", "女性 n (%)", "r", "病家（记有性别者）"), ("prior", "记前医误治 %", "r"),
        ("formulas", "常用方", "l")], rows, notes=[
        "x̄ ± s：均数 ± 标准差；转归的百分比以记有转归的医案为分母，女性以记有性别的医案为分母；95% CI 为 Wilson 区间。",
        f"转归（好转、未效、加重、死亡）× 组：χ² = {oc['chi2']:.2f}，df = {oc['df']}，{p_eq(oc['p'])}，Cramér's V = {oc['cramers_v']:.2f}"
        + ("（最小期望频数 < 5，结果宜慎读）" if oc.get("min_expected", 5) < 5 else "") + "。" if oc else None,
        f"诊次 × 组：Kruskal–Wallis H = {vk['h']:.2f}，df = {vk['df']}，{p_eq(vk['p'])}。" if vk else None,
        "医案为医家所记、编者所选：所示为记录中的分布，非疗效证据。"])]


BUILDERS: dict[str, Callable[[dict[str, Any], Any], list[dict[str, Any]]]] = {
    "usage": usage, "pairs": pairs, "compare": compare, "family": family, "term": term, "herb": herb, "properties": properties,
    "incompat": incompat, "network": network, "formula": formula, "names": names, "senses": senses,
    "casecompare": casecompare,
}


def build(kind: str, result: dict[str, Any], base: Any) -> list[dict[str, Any]]:
    """The tables of a study result (none when there is nothing to print); never raises — a table is an extra."""
    fn = BUILDERS.get(kind)
    if fn is None or not isinstance(result, dict):
        return []
    try:
        tables = [t for t in fn(result, base) if t.get("rows")]
    except (KeyError, TypeError, ValueError, IndexError, ZeroDivisionError):  # pragma: no cover - a malformed result prints nothing
        return []
    sig = base.signature() if hasattr(base, "signature") else {}
    digest = sig.get("corpus_digest", "")
    source = f"道乃久（TaoChronos）· {WORDS.get(kind, '治学')}" + (f" · 语料版本 {digest}" if digest else "")
    for t in tables:
        t.setdefault("source", source)
    return tables


__all__ = ["BUILDERS", "TABLE_VERSION", "build", "est", "est_ci", "med_iqr", "n_pct", "p_eq", "p_value", "shell", "table"]
