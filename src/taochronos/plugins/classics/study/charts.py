"""图表 — chart specifications of the study results, for the web client and for figures.

A study result says what the texts write; its charts show the same numbers so that a reader sees the shape at once — a
term's rise and fall with its intervals, a drug's doses by period, two formulas' ratios side by side.  Each chart is a
small declarative specification (``SPEC_VERSION``), drawn from the full result before it is trimmed for a model's
context, and carried in the result under ``charts``: the web client draws it (``web/js/chart.js``: hover, a table view,
SVG / PNG / CSV / JSON downloads), ``taochronos study … --charts <dir>`` writes it as SVG, CSV and JSON (``svg.py``), and
the model's text leaves it out.

A specification: ``type`` (line, bar, hbar, stack, heatmap, range, box, forest, scatter, dendrogram, timeline,
network), ``title``, ``subtitle``, ``rows`` (records) with ``columns`` ([{key, label}] — the table and the CSV), and per
type the keys it reads:

* line / bar / hbar / stack — ``x`` the category ({key, label}), ``series`` [{key, label, lo?, hi?}] the values (lo/hi:
  an interval, drawn as a band or whiskers), ``y`` {label, percent?, min?}; stack: ``percent`` to show shares of 100 %;
* heatmap — ``x`` and ``y`` the two categories, ``value`` {key, label, percent?} the cell's number;
* range — ``x`` the category, ``range`` {min, q1, median, q3, max} keys (whiskers, box and median);
* box — a box plot (Tukey): ``x`` the category, rows with q1, median, q3, the whiskers lo and hi (the furthest values
  within 1.5 IQR), mean and n — or, without them, ``points`` {category: [values]} from which they are computed;
  ``points`` are drawn too (the values beyond the whiskers always, the others jittered when there are few);
* forest — estimates with their intervals, one row each: ``y`` the label ({key}), ``estimate`` {key, lo, hi, label},
  ``x`` {label, log?, ref?} (an odds ratio: a log axis and a line at 1), a row's ``sig`` (false: drawn in grey);
* scatter — ``x`` and ``y`` numeric ({key, label, year?, percent?, min?}), ``size`` {key, label} (a bubble), ``group``
  {key} (three groups at most), ``fit`` {points: [[x, y]], label} (a smoothed line), ``label`` the key named on hover;
* dendrogram — a tree of ``labels``: ``merges`` [[a, b, height, size]] (scipy's linkage form), ``order`` (the leaves
  top to bottom), ``member`` (each item's cluster), ``groups`` (the clusters' names), ``cut`` (the height cut), ``x``;
* timeline — ``rows`` with ``start`` (a year), ``label`` and ``group``;
* network — ``nodes`` [{id, label, group, size}] and ``edges`` [{source, target, weight, label}].

Numbers are what the result computed; a chart adds no inference.  ``note`` repeats the caveat that goes with the numbers
(machine reading, historical doses, per-work counting).  A page numbers the charts of a result 图 1, 图 2 … in order
and writes them, for a paper, in the journal style (``svg.py``, ``web/js/chart.js``).
"""

from __future__ import annotations

from typing import Any, Callable

from ....science.stats import loess, tukey
from .usage import even_sample

SPEC_VERSION = 1
TYPES = ("line", "bar", "hbar", "stack", "heatmap", "range", "box", "forest", "scatter", "dendrogram", "timeline", "network")
MAX_JITTER = 300  # a box's values drawn one by one beside it (beyond them: the box and the values past its whiskers)
MAX_SERIES = 8  # the palette's categorical slots: past them, fold into 其他 (never a generated colour)


def chart(type_: str, title: str, rows: list[dict[str, Any]], columns: list[tuple[str, str]], **spec: Any) -> dict[str, Any]:
    """One chart specification (``columns``: (key, label) pairs, in table order)."""
    if type_ not in TYPES:
        raise ValueError(f"unknown chart type {type_!r}")
    out: dict[str, Any] = {"version": SPEC_VERSION, "type": type_, "title": title, "rows": rows,
                           "columns": [{"key": k, "label": label} for k, label in columns]}
    out.update({k: v for k, v in spec.items() if v is not None})
    return out


def _period_order(base: Any) -> list[str]:
    return [p.label for p in base.periods] + ["未定"]


def _fold(counts: dict[str, int | float], top: int) -> tuple[list[str], dict[str, float]]:
    """The ``top`` largest keys, the rest as 其他 (a chart never needs more colours than the palette has)."""
    keys = sorted(counts, key=lambda k: -counts[k])
    head = keys[:top]
    other = sum(counts[k] for k in keys[top:])
    out = {k: counts[k] for k in head}
    if other:
        out["其他"] = other
        head = head + ["其他"]
    return head, out


def _p(p: Any) -> str:
    """"< 0.001" / "= 0.045": P as a figure's subtitle writes it."""
    p = float(p)
    return "< 0.001" if p < 0.001 else f"= {p:.3f}" if p < 0.1 else f"= {p:.2f}"


def _dose_note(r: dict[str, Any]) -> str | None:
    """The result's caveat on historical doses, worded for a figure (it stands under the chart, not above a list)."""
    notice = r.get("metrology_notice")
    return notice.replace("以下为", "图中剂量为", 1) if isinstance(notice, str) and notice else None


# ------------------------------------------------------------------ builders, one per study function
def term(r: dict[str, Any], base: Any) -> list[dict[str, Any]]:
    rows = [{"period": p["period"], "per_10k": p["per_10k"], "lo": (p.get("ci_per_10k") or [None, None])[0],
             "hi": (p.get("ci_per_10k") or [None, None])[1], "passages": p["passages"], "total": p["total"]}
            for p in r.get("periods", []) if p.get("total")]
    if len(rows) < 2:
        return []
    name = r.get("term", {}).get("name", "")
    trend = r.get("trend") or {}
    sub = "每万段中含该词的段数，阴影为 95% Wilson 区间" + (f"；趋势 z = {trend['z']:.2f}" if trend.get("z") is not None else "")
    return [chart("line", f"{name} · 各时期出现率", rows,
                  [("period", "时期"), ("per_10k", "每万段"), ("lo", "区间下限"), ("hi", "区间上限"), ("passages", "段落"), ("total", "该期总段落")],
                  id="term-periods", subtitle=sub, x={"key": "period", "label": "时期"},
                  y={"label": "每万段", "min": 0}, series=[{"key": "per_10k", "label": name, "lo": "lo", "hi": "hi"}])]


def herb(r: dict[str, Any], base: Any) -> list[dict[str, Any]]:
    from .usage import CHANNEL_ORGAN, NATURE_ORDER, ORGAN_ORDER, base_nature

    name = r.get("herb", {}).get("name", "")
    periods = [p for p in r.get("periods", []) if p.get("books")]
    out = []
    if periods:
        rows = []
        for p in periods:
            row: dict[str, Any] = {"period": p["period"], "books": p["books"]}
            for n in NATURE_ORDER:
                row[n] = sum(v for k, v in (p.get("natures") or {}).items() if base_nature(k) == n)
            rows.append(row)
        used = [n for n in NATURE_ORDER if any(row[n] for row in rows)]
        if used:
            out.append(chart("stack", f"{name} · 历代本草所言药性", rows, [("period", "时期"), ("books", "本草著作")] + [(n, n) for n in used],
                             id="herb-natures", subtitle="各时期言其性为寒、凉、平、温、热的本草著作数",
                             x={"key": "period", "label": "时期"}, y={"label": "著作数", "min": 0},
                             series=[{"key": n, "label": n} for n in used]))
        cells = []
        for p in periods:
            organs: dict[str, int] = {}
            for c, k in (p.get("channels") or {}).items():
                organ = CHANNEL_ORGAN.get(c, c)
                organs[organ] = organs.get(organ, 0) + k
            for organ, k in organs.items():
                cells.append({"period": p["period"], "channel": organ, "books": k})
        if cells:
            seen = {c["channel"] for c in cells}
            order = [o for o in ORGAN_ORDER if o in seen] + sorted(seen - set(ORGAN_ORDER))
            out.append(chart("heatmap", f"{name} · 归经之说的时代分布", cells, [("period", "时期"), ("channel", "归经"), ("books", "著作数")],
                             id="herb-channels", subtitle="各时期言其入某经（按十二经与脏腑的通行对应归并）的本草著作数",
                             x={"key": "period", "label": "时期", "order": [p["period"] for p in periods]},
                             y={"key": "channel", "label": "归经", "order": order}, value={"key": "books", "label": "著作数"}))
    firsts = [f for f in r.get("firsts", []) if f.get("years")]
    if firsts:
        rows = [{"label": f"{f['field']}·{f['value']}", "start": f["years"][1], "group": f["field"], "where": f.get("locator", ""),
                 "passage_id": f.get("passage_id", "")} for f in firsts[:24]]
        out.append(chart("timeline", f"{name} · 各项药性的首见", rows,
                         [("label", "性能"), ("start", "年代（下限）"), ("group", "类"), ("where", "出处"), ("passage_id", "段落号")],
                         id="herb-firsts", subtitle="每项性能最早见于何书（按成书年代下限）", x={"key": "start", "label": "年代"}))
    return out


def witness_labels(witnesses: list[dict[str, Any]]) -> list[str]:
    """Each witness by its book and year — 新编金匮要略方论（219）; two from one book told apart by their juan (·卷1, ·卷2),
    and, failing that, by their order (甲, 乙 …): a legend never names two series alike."""
    def book(x: dict[str, Any]) -> str:
        return str(x.get("locator") or "").split("》")[0].lstrip("《")

    def year(x: dict[str, Any]) -> str:
        return f"{int(x['years'][1])}" if x.get("years") else "?"

    def part(x: dict[str, Any]) -> str:
        rest = str(x.get("locator") or "").split("》", 1)[1] if "》" in str(x.get("locator") or "") else ""
        return rest.split("·")[0].strip()[:8]

    labels = [f"{book(x)}（{year(x)}）" for x in witnesses]
    if len(set(labels)) < len(labels):  # two from one book: by their juan
        labels = [f"{book(x)}·{part(x)}（{year(x)}）" if labels.count(label) > 1 and part(x) else label for x, label in zip(witnesses, labels)]
    out: list[str] = []
    seen: dict[str, int] = {}
    for label in labels:  # and, failing that, by their order
        k = seen[label] = seen.get(label, -1) + 1
        out.append(label if labels.count(label) == 1 else label + "甲乙丙丁戊己庚辛"[k % 8])
    return out


def formula(r: dict[str, Any], base: Any) -> list[dict[str, Any]]:
    name = r.get("formula", {}).get("name", "")
    out = []
    order = _period_order(base)
    rel_of = {}
    for g in r.get("groups", []):
        rel = (g.get("relation") or "").split("（")[0]
        for pid in g.get("member_ids", []):
            rel_of[pid] = rel
    counts: dict[str, dict[str, int]] = {}
    for w in r.get("witnesses", []):
        per = w.get("period") or "未定"
        rel = rel_of.get(w["passage_id"], "其他")
        counts.setdefault(per, {})
        counts[per][rel] = counts[per].get(rel, 0) + 1
    rels = sorted({k for c in counts.values() for k in c}, key=lambda k: (["原方·通行方", "原方", "通行方", "加减化裁", "同名异方", "孤例"] + [k]).index(k))
    if counts and rels:
        rows = [{"period": p, **{k: counts[p].get(k, 0) for k in rels}} for p in order if p in counts]
        out.append(chart("stack", f"{name} · 写出组成的见证（按时期与组成类别）", rows, [("period", "时期")] + [(k, k) for k in rels],
                         id="formula-witnesses", subtitle="每一见证为一处写出组成的原文；类别见“组成类别”",
                         x={"key": "period", "label": "时期"}, y={"label": "见证数", "min": 0},
                         series=[{"key": k, "label": k} for k in rels[:MAX_SERIES]]))
    ratios = [x for x in r.get("ratios", []) if x.get("ratio")]
    if ratios:
        picked = ratios[:4]
        drugs = list(dict.fromkeys(d for x in picked for d in x["ratio"]))
        keys = [f"w{i}" for i in range(len(picked))]
        labels = witness_labels(picked)
        rows = [{"drug": d, **{k: x["ratio"].get(d) for k, x in zip(keys, picked)}} for d in drugs]
        out.append(chart("bar", f"{name} · 配伍比例", rows, [("drug", "药")] + list(zip(keys, labels)),
                         id="formula-ratios", subtitle="各见证中主方药物的剂量比（以最大剂量为 1，与各期计量无关）",
                         x={"key": "drug", "label": "药"}, y={"label": "比例", "min": 0},
                         series=[{"key": k, "label": label} for k, label in zip(keys, labels)],
                         note=_dose_note(r)))
    return out


def pairs(r: dict[str, Any], base: Any) -> list[dict[str, Any]]:
    out = []
    if r.get("partners"):
        forest = [{"drug": x["with"], "or": x["or"], "lo": x["or_ci"][0], "hi": x["or_ci"][1], "support": x["support"], "lift": x["lift"],
                   "p": x.get("p"), "sig": bool(x["significant"])} for x in r["partners"][:20] if x.get("or") and x.get("or_ci")]
        if forest:
            out.append(chart("forest", f"{r.get('herb')} · 同方药物的关联强度", forest,
                             [("drug", "药物"), ("or", "OR"), ("lo", "95% CI 下限"), ("hi", "95% CI 上限"), ("support", "同方次数"),
                              ("lift", "提升度"), ("p", "P")],
                             id="pairs-forest", subtitle="比值比（OR）与 95% 置信区间（Woolf 法），对数轴；灰色为经 Benjamini–Hochberg 校正后不显著",
                             y={"key": "drug", "label": "药物"}, estimate={"key": "or", "lo": "lo", "hi": "hi", "label": "OR"},
                             x={"label": "OR（95% CI）", "log": True, "ref": 1}))
        rows = [{"drug": x["with"], "npmi": x["npmi"], "support": x["support"], "lift": x["lift"]} for x in r["partners"][:15]]
        out.append(chart("hbar", f"{r.get('herb')} · 常相配伍之药", rows, [("drug", "药"), ("npmi", "NPMI"), ("support", "同方次数"), ("lift", "提升度")],
                         id="pairs-partners", subtitle="按归一化点互信息（NPMI）排序；显著性见表（Fisher 检验 + BH）",
                         x={"key": "drug", "label": "药"}, y={"label": "NPMI"}, series=[{"key": "npmi", "label": "NPMI"}]))
        if len(r.get("by_period") or []) >= 2:
            rows = [{"period": x["period"], "share": x["share"], "with": x["with"], "compositions": x["compositions"]}
                    for x in r["by_period"] if x.get("share") is not None]
            out.append(chart("line", f"{r.get('herb')} · 含此药的组成占比", rows,
                             [("period", "时期"), ("share", "占比"), ("with", "含此药"), ("compositions", "组成")],
                             id="pairs-periods", x={"key": "period", "label": "时期"}, y={"label": "占比", "percent": True, "min": 0},
                             series=[{"key": "share", "label": r.get("herb")}]))
    else:
        if r.get("frequency"):
            rows = [{"drug": x["drug"], "n": x["compositions"], "share": x["share"]} for x in r["frequency"][:20]]
            out.append(chart("hbar", "高频药物", rows, [("drug", "药物"), ("n", "频次（首）"), ("share", "频率")], id="pairs-frequency",
                             subtitle=f"写出组成 {r.get('compositions', 0)} 首中含各药者（前 20 位，每部著作计一次）",
                             x={"key": "drug", "label": "药物"}, y={"label": "频次（首）", "min": 0}, series=[{"key": "n", "label": "频次"}]))
        if r.get("pairs"):
            rows = [{"pair": f"{x['a_name']}—{x['b_name']}", "npmi": x["npmi"], "support": x["support"], "lift": x["lift"]} for x in r["pairs"][:20]]
            out.append(chart("hbar", "最显著的药对", rows, [("pair", "药对"), ("npmi", "NPMI"), ("support", "同方次数"), ("lift", "提升度")],
                             id="pairs-top", x={"key": "pair", "label": "药对"}, y={"label": "NPMI"}, series=[{"key": "npmi", "label": "NPMI"}]))
        tree = (r.get("_raw") or {}).get("dendrogram")
        if tree and tree.get("merges"):
            names_ = [f"第 {c + 1} 类" for c in range(tree["k"])]
            rows = [{"drug": tree["labels"][i], "cluster": names_[tree["member"][i]], "n": tree["frequency"][i]} for i in tree["order"]]
            out.append(chart("dendrogram", "高频药物聚类树状图", rows, [("drug", "药物"), ("cluster", "类别"), ("n", "频次（首）")],
                             id="pairs-dendrogram", subtitle=f"频次最高的 {len(tree['labels'])} 味药，以 1 − Jaccard 系数为距离，平均联结法（UPGMA）；"
                                                             f"竖线为切分处，分为 {tree['k']} 类",
                             labels=tree["labels"], merges=tree["merges"], order=tree["order"], member=tree["member"], cut=tree.get("cut"),
                             groups=names_, x={"label": "距离（1 − Jaccard）"}))
        if r.get("rules"):
            rows = [{"rule": f"{x['if']} → {x['then']}", "support": x["support_share"], "confidence": x["confidence"], "lift": x["lift"],
                     "n": x["support"]} for x in r["rules"]]
            out.append(chart("scatter", "药物关联规则", rows, [("rule", "规则"), ("support", "支持度"), ("confidence", "置信度"), ("lift", "提升度"),
                                                          ("n", "同方（首）")],
                             id="pairs-rules", subtitle="每点为一条规则（前项 → 后项）；点的大小为提升度",
                             x={"key": "support", "label": "支持度", "percent": True, "min": 0}, y={"key": "confidence", "label": "置信度", "percent": True},
                             size={"key": "lift", "label": "提升度"}, label="rule"))
    return out


def network(r: dict[str, Any], base: Any) -> list[dict[str, Any]]:
    if r.get("findings"):
        rows = [{"finding": x["finding"], "support": x["support"], "lift": x["lift"]} for x in r["findings"][:15]]
        return [chart("hbar", f"{r.get('target')} · 主治所见", rows, [("finding", "所见"), ("support", "次数"), ("lift", "提升度")],
                      id="network-findings", subtitle="治疗语句中方名之前所见（每部著作一次）", x={"key": "finding", "label": "所见"},
                      y={"label": "次数", "min": 0}, series=[{"key": "support", "label": "次数"}])]
    if r.get("formulas"):
        rows = [{"formula": x["formula"], "support": x["support"], "lift": x["lift"]} for x in r["formulas"][:15]]
        return [chart("hbar", f"{r.get('target')} · 所用之方", rows, [("formula", "方"), ("support", "次数"), ("lift", "提升度")],
                      id="network-formulas", x={"key": "formula", "label": "方"}, y={"label": "次数", "min": 0},
                      series=[{"key": "support", "label": "次数"}])]
    return []


def _shares(r: dict[str, Any], items_key: str, title: str, cid: str, label: str) -> list[dict[str, Any]]:
    rows_in = [p for p in r.get("periods" if items_key == "names" else "series", []) if p.get("shares")]
    if len(rows_in) < 2:
        return []
    totals: dict[str, float] = {}
    for p in rows_in:
        for k, v in p["shares"].items():
            totals[k] = totals.get(k, 0) + v
    keys, _ = _fold(totals, MAX_SERIES - 1)
    rows = []
    for p in rows_in:
        row = {"period": p["period"], **{k: p["shares"].get(k, 0) for k in keys if k != "其他"}}
        if "其他" in keys:
            row["其他"] = sum(v for k, v in p["shares"].items() if k not in keys)
        rows.append(row)
    return [chart("stack", title, rows, [("period", "时期")] + [(k, k) for k in keys], id=cid, percent=True,
                  subtitle=f"各时期{label}所占份额", x={"key": "period", "label": "时期"}, y={"label": "份额", "percent": True},
                  series=[{"key": k, "label": k} for k in keys])]


def names(r: dict[str, Any], base: Any) -> list[dict[str, Any]]:
    return _shares(r, "names", f"{r.get('term', '')} · 各名称的历代份额", "names-shares", "各名称")


def senses(r: dict[str, Any], base: Any) -> list[dict[str, Any]]:
    term_ = r.get("term")
    name = term_.get("name") if isinstance(term_, dict) else term_
    return _shares(r, "series", f"{name or ''} · 各义项的历代份额", "senses-shares", "各义项")


def compare(r: dict[str, Any], base: Any) -> list[dict[str, Any]]:
    found = [f for f in r.get("formulas", []) if f.get("found")]
    out = []
    if len(found) >= 2:
        keys = [f"f{i}" for i in range(len(found))]
        rows = []
        for row in r.get("matrix", []):
            vals = {k: (row.get(f["name"]) or {}).get("ratio") for k, f in zip(keys, found)}
            if any(v is not None for v in vals.values()):
                rows.append({"drug": row["drug"], **vals})
        if rows:
            out.append(chart("bar", "配伍比例对照", rows, [("drug", "药")] + [(k, f["name"]) for k, f in zip(keys, found)],
                             id="compare-ratios", subtitle="各方以其最大重量为 1 的剂量比；以枚、升等计者不入此图（见表）",
                             x={"key": "drug", "label": "药"}, y={"label": "比例", "min": 0},
                             series=[{"key": k, "label": f["name"]} for k, f in zip(keys, found)][:MAX_SERIES],
                             note=_dose_note(r)))
        cells = []
        for p in r.get("pairs", []):
            score = p["weighted_overlap"] if p["weighted_overlap"] is not None else p["jaccard"]
            cells += [{"a": p["a"], "b": p["b"], "similarity": score, "verdict": p["verdict"]},
                      {"a": p["b"], "b": p["a"], "similarity": score, "verdict": p["verdict"]}]
        cells += [{"a": f["name"], "b": f["name"], "similarity": 1.0, "verdict": "—"} for f in found]
        names_ = [f["name"] for f in found]
        out.append(chart("heatmap", "方剂相似度", cells, [("a", "方"), ("b", "方"), ("similarity", "相似度"), ("verdict", "结论")],
                         id="compare-similarity", subtitle="剂量加权重合（两方均以重量写出剂量时），否则药味 Jaccard",
                         x={"key": "a", "label": "方", "order": names_}, y={"key": "b", "label": "方", "order": names_},
                         value={"key": "similarity", "label": "相似度", "max": 1}))
    return out


RELATIONS = ["加味", "减味", "加减", "同药异量", "同方异名", "同药", "本方"]  # 类方: one colour per relation in every chart


def family(r: dict[str, Any], base: Any) -> list[dict[str, Any]]:
    members = [m for m in r.get("members", []) if m.get("year") is not None]
    name = r.get("formula", {}).get("name", "")
    out = []
    if members:
        rows = [{"label": m["formula"], "start": m["year"], "group": m["relation"], "works": m["works"],
                 "added": "、".join(m["added"]), "removed": "、".join(m["removed"])} for m in members[:30]]
        out.append(chart("timeline", f"{name} · 类方的最早见", rows,
                         [("label", "方"), ("start", "年代"), ("group", "关系"), ("works", "著作"), ("added", "加"), ("removed", "减")],
                         id="family-timeline", subtitle="各成员在语料中最早写出组成的年代", x={"key": "start", "label": "年代"},
                         groups=RELATIONS))
    if r.get("members"):
        nodes = [{"id": "base", "label": name, "group": "本方", "size": r["formula"].get("works") or 1}]
        edges = []
        for i, m in enumerate(r["members"][:24]):
            nodes.append({"id": f"m{i}", "label": m["formula"], "group": m["relation"], "size": m["works"]})
            change = "＋" + "、".join(m["added"]) if m["added"] else ""
            change += ("－" + "、".join(m["removed"])) if m["removed"] else ""
            edges.append({"source": "base", "target": f"m{i}", "weight": m["works"], "label": change or m["relation"]})
        out.append(chart("network", f"{name} · 类方关系", [{"formula": m["formula"], "relation": m["relation"], "works": m["works"],
                                                         "added": "、".join(m["added"]), "removed": "、".join(m["removed"])}
                                                        for m in r["members"][:24]],
                         [("formula", "方"), ("relation", "关系"), ("works", "著作"), ("added", "加"), ("removed", "减")],
                         id="family-network", subtitle="由本方加减而成之方（节点大小：写出组成的著作数）", nodes=nodes, edges=edges,
                         groups=RELATIONS))
    return out


def usage(r: dict[str, Any], base: Any) -> list[dict[str, Any]]:
    name = r.get("drug", {}).get("name", "")
    out = []
    rows = [{"period": x["period"], "share": x["share"], "lo": x["ci"][0], "hi": x["ci"][1], "with": x["with"],
             "compositions": x["compositions"]} for x in r.get("by_period", []) if x["period"] != "未定"]
    if len(rows) >= 2:
        trend = r.get("trend") or {}
        out.append(chart("line", f"{name} · 含此药的组成占比", rows,
                         [("period", "时期"), ("share", "占比"), ("lo", "区间下限"), ("hi", "区间上限"), ("with", "含此药"), ("compositions", "组成")],
                         id="usage-share", subtitle="每部著作计一次；阴影为 95% Wilson 区间"
                         + (f"；趋势 z = {trend['z']:.2f}" if trend.get("z") is not None else ""),
                         x={"key": "period", "label": "时期"}, y={"label": "占比", "percent": True, "min": 0},
                         series=[{"key": "share", "label": name, "lo": "lo", "hi": "hi"}]))
    raw = r.get("_raw") or {}
    doses_ = r.get("doses") or {}
    grams = raw.get("grams") or {}
    rows, points = [], {}
    for x in doses_.get("by_period", []):
        if not x.get("grams"):
            continue
        values = grams.get(x["period"]) or []
        t = tukey(values) if values else None
        if t:
            rows.append({"period": x["period"], "n": t["n"], "q1": t["q1"], "median": t["median"], "q3": t["q3"], "lo": t["lo"], "hi": t["hi"],
                         "mean": t["mean"], "min": t["min"], "max": t["max"]})
            inside = [v for v in values if t["lo"] <= v <= t["hi"]]
            points[x["period"]] = sorted(t["outliers"] + even_sample(inside, MAX_JITTER))
        else:  # no values to draw: the summary the result keeps
            q = x["grams"]
            rows.append({"period": x["period"], "n": x["n"], **{k: q[k] for k in ("q1", "median", "q3")}, "lo": q["min"], "hi": q["max"],
                         "mean": q.get("mean"), "min": q["min"], "max": q["max"]})
    if rows:
        test = doses_.get("test") or {}
        out.append(chart("box", f"{name} · 历代汤剂用量（折合克数）", rows,
                         [("period", "时期"), ("n", "n"), ("median", "中位数"), ("q1", "P25"), ("q3", "P75"), ("lo", "须线下端"), ("hi", "须线上端"),
                          ("mean", "均数"), ("min", "最小"), ("max", "最大")],
                         id="usage-doses", subtitle="汤剂中以重量写出的剂量，按各期计量折合（两之克数取各期估值的中点）；箱为四分位距，中线为中位数，"
                                                    "须线至 1.5 倍四分位距内的最远值，圆点为各剂量"
                         + (f"；Kruskal–Wallis H = {test['h']:.2f}，P {_p(test['p'])}" if test.get("h") is not None else ""),
                         x={"key": "period", "label": "时期"}, y={"label": "折合克数（g）", "min": 0}, points=points,
                         note="丸、散、膏与煮散为一料之量，不入此图。" + (_dose_note(r) or "")))
    pts = raw.get("points") or []
    if len(pts) >= 10:
        trend = doses_.get("trend") or {}
        fit = loess([p[0] for p in pts], [p[1] for p in pts])
        out.append(chart("scatter", f"{name} · 汤剂用量与成书年代", [{"year": p[0], "grams": p[1], "formula": p[2]} for p in pts],
                         [("year", "成书年代"), ("grams", "折合克数（g）"), ("formula", "方")],
                         id="usage-dose-years", subtitle="每点为一首写出组成（汤剂，按成书年代的中点）；曲线为 LOESS 平滑"
                         + (f"；Spearman ρ = {trend['rho']:.2f}，P {_p(trend['p'])}，n = {trend['n']}" if trend.get("rho") is not None else ""),
                         x={"key": "year", "label": "成书年代", "year": True}, y={"key": "grams", "label": "折合克数（g）", "min": 0},
                         label="formula", fit={"points": fit, "label": "LOESS"} if fit else None, note=_dose_note(r)))
    proc = r.get("processing") or {}
    if proc.get("by_period") and proc.get("notes"):
        keys = list(proc["notes"]) + ["其他"]
        out.append(chart("stack", f"{name} · 炮制与用法注", proc["by_period"], [("period", "时期")] + [(k, k) for k in keys],
                         id="usage-processing", percent=True, subtitle="写在药名之后的炮制、修治与用法注，各时期份额",
                         x={"key": "period", "label": "时期"}, y={"label": "份额", "percent": True},
                         series=[{"key": k, "label": k} for k in keys][:MAX_SERIES]))
    if r.get("partners"):
        rows = [{"drug": x["with"], "compositions": x["compositions"], "lift": x["lift"]} for x in r["partners"][:15]]
        out.append(chart("hbar", f"{name} · 常同用之药", rows, [("drug", "药"), ("compositions", "同方组成"), ("lift", "提升度")],
                         id="usage-partners", x={"key": "drug", "label": "药"}, y={"label": "同方组成数", "min": 0},
                         series=[{"key": "compositions", "label": "同方组成"}]))
    return out


def properties(r: dict[str, Any], base: Any) -> list[dict[str, Any]]:
    from .usage import NATURE_ORDER

    drugs = [d for d in r.get("drugs", []) if d.get("works")]
    out = []
    channels = r.get("channels") or []
    if drugs and channels:
        cells = [{"drug": d["drug"], "channel": c, "share": d["channels"].get(c, 0)} for d in drugs for c in channels]
        out.append(chart("heatmap", "归经谱", cells, [("drug", "药"), ("channel", "归经"), ("share", "言此经的著作占比")],
                         id="properties-channels", subtitle="各药的本草条目中言入某经者占其著作的比例",
                         x={"key": "channel", "label": "归经", "order": channels}, y={"key": "drug", "label": "药", "order": [d["drug"] for d in drugs]},
                         value={"key": "share", "label": "占比", "percent": True, "max": 1}))
    if drugs:
        used = [n for n in NATURE_ORDER if any(d["natures"].get(n) for d in drugs)]
        if used:
            rows = [{"drug": d["drug"], **{n: d["natures"].get(n, 0) for n in used}} for d in drugs]
            out.append(chart("stack", "药性（寒热）谱", rows, [("drug", "药")] + [(n, n) for n in used], id="properties-natures",
                             subtitle="各药的本草条目言其性者占其著作的比例", x={"key": "drug", "label": "药"},
                             y={"label": "占比", "percent": True}, series=[{"key": n, "label": n} for n in used]))
    prof = r.get("profile")
    if prof and prof.get("natures"):
        rows = [{"nature": k, "share": v} for k, v in prof["natures"].items()]
        out.append(chart("bar", f"{r.get('formula')} · 全方药性", rows, [("nature", "性"), ("share", "份额")], id="properties-profile",
                         subtitle="按剂量加权" if prof.get("weighted_by") == "dose" else "各药等权",
                         x={"key": "nature", "label": "性"}, y={"label": "份额", "percent": True, "min": 0},
                         series=[{"key": "share", "label": "份额"}]))
    return out


def incompat(r: dict[str, Any], base: Any) -> list[dict[str, Any]]:
    out = []
    order = _period_order(base)
    together = [x for x in (r.get("formulas") or {}).get("pairs", []) if x.get("works")]
    if together:
        cells = [{"pair": x["pair"], "period": p, "works": x["periods"].get(p, 0)} for x in together for p in order
                 if any(y["periods"].get(p) for y in together)]
        out.append(chart("heatmap", "反、畏之药同见于写出的组成", cells, [("pair", "药对"), ("period", "时期"), ("works", "著作数")],
                         id="incompat-together", subtitle="各时期写出组成中两药同用的著作数（文本事实，不说明合理或安全）",
                         x={"key": "period", "label": "时期", "order": [p for p in order if any(c["period"] == p for c in cells)]},
                         y={"key": "pair", "label": "药对", "order": [x["pair"] for x in together]}, value={"key": "works", "label": "著作数"},
                         note=r.get("notice")))
    stated = (r.get("statements") or {}).get("pairs") or []
    if stated:
        rows = [{"pair": x["pair"], "works": x["works"]} for x in stated]
        out.append(chart("hbar", "言“反”“畏”的著作数", rows, [("pair", "药对"), ("works", "著作数")], id="incompat-statements",
                         x={"key": "pair", "label": "药对"}, y={"label": "著作数", "min": 0}, series=[{"key": "works", "label": "著作数"}]))
        rows = []
        for x in stated:
            e = x.get("earliest_uncompiled") or x["earliest"]
            if e and e.get("years"):
                rows.append({"label": x["pair"], "start": e["years"][1], "group": x["pair"][2] if len(x["pair"]) > 2 else "",
                             "where": e.get("locator", ""), "passage_id": e.get("passage_id", "")})
        if rows:
            out.append(chart("timeline", "“反”“畏”之说的最早见证", rows, [("label", "药对"), ("start", "年代（下限）"), ("where", "出处"), ("passage_id", "段落号")],
                             id="incompat-firsts", subtitle="辑本（如《神农本草经》）之外的最早见证", x={"key": "start", "label": "年代"}))
    return out


BUILDERS: dict[str, Callable[[dict[str, Any], Any], list[dict[str, Any]]]] = {
    "term": term, "herb": herb, "formula": formula, "pairs": pairs, "network": network, "names": names, "senses": senses,
    "compare": compare, "family": family, "usage": usage, "properties": properties, "incompat": incompat,
}


# what a figure's source line calls each study, in plain words (as the page does, web/js/redact.js): a figure leaves the
# platform, its inside names stay
WORDS = {"formula": "方源考", "herb": "药性源流", "term": "术语源流", "pairs": "配伍规律", "network": "方证网络", "names": "名称",
         "senses": "语义演变", "compare": "方剂比较", "family": "类方", "usage": "药物用量与配伍", "properties": "性味归经对照",
         "incompat": "配伍禁忌"}


def build(kind: str, result: dict[str, Any], base: Any) -> list[dict[str, Any]]:
    """The charts of a study result (none when there is too little to draw); never raises — a chart is an extra."""
    fn = BUILDERS.get(kind)
    if fn is None or not isinstance(result, dict):
        return []
    try:
        charts = [c for c in fn(result, base) if c.get("rows") or c.get("nodes")]
    except (KeyError, TypeError, ValueError, IndexError):  # pragma: no cover - a malformed result draws nothing
        return []
    sig = base.signature() if hasattr(base, "signature") else {}
    digest = sig.get("corpus_digest", "")
    source = f"道乃久（TaoChronos）· {WORDS.get(kind, '治学')}" + (f" · 语料版本 {digest}" if digest else "")
    for c in charts:
        c.setdefault("source", source)
    return charts


def attach(kind: str, result: dict[str, Any], base: Any) -> dict[str, Any]:
    """``result`` with its charts under ``charts`` and its three-line tables under ``tables`` (``tables.py``), when it
    has any; the values its figures draw one by one (``_raw``: doses, a tree) are taken out once they are drawn."""
    from . import tables as _tables

    charts = build(kind, result, base)
    tables = _tables.build(kind, result, base)
    if isinstance(result, dict):
        result.pop("_raw", None)
    if charts:
        result["charts"] = charts
    if tables:
        result["tables"] = tables
    return result


__all__ = ["BUILDERS", "MAX_SERIES", "SPEC_VERSION", "TYPES", "attach", "build", "chart"]
