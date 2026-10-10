"""图表 — chart specifications of the study results, for the web client and for figures.

A study result says what the texts write; its charts show the same numbers so that a reader sees the shape at once — a
term's rise and fall with its intervals, a drug's doses by period, two formulas' ratios side by side.  Each chart is a
small declarative specification (``SPEC_VERSION``), drawn from the full result before it is trimmed for a model's
context, and carried in the result under ``charts``: the web client draws it (``web/js/chart.js``: hover, a table view,
SVG / PNG / CSV / JSON downloads), ``taochronos study … --charts <dir>`` writes it as SVG, CSV and JSON (``svg.py``), and
the model's text leaves it out.

A specification: ``type`` (line, bar, hbar, stack, heatmap, range, timeline, network), ``title``, ``subtitle``, ``rows``
(records) with ``columns`` ([{key, label}] — the table and the CSV), and per type the keys it reads:

* line / bar / hbar / stack — ``x`` the category ({key, label}), ``series`` [{key, label, lo?, hi?}] the values (lo/hi:
  an interval, drawn as a band or whiskers), ``y`` {label, percent?, min?}; stack: ``percent`` to show shares of 100 %;
* heatmap — ``x`` and ``y`` the two categories, ``value`` {key, label, percent?} the cell's number;
* range — ``x`` the category, ``range`` {min, q1, median, q3, max} keys (whiskers, box and median);
* timeline — ``rows`` with ``start`` (a year), ``label`` and ``group``;
* network — ``nodes`` [{id, label, group, size}] and ``edges`` [{source, target, weight, label}].

Numbers are what the result computed; a chart adds no inference.  ``note`` repeats the caveat that goes with the numbers
(machine reading, historical doses, per-work counting).
"""

from __future__ import annotations

from typing import Any, Callable

SPEC_VERSION = 1
TYPES = ("line", "bar", "hbar", "stack", "heatmap", "range", "timeline", "network")
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
        labels = [f"{x['locator'].split('》')[0].lstrip('《')}（{int(x['years'][1]) if x.get('years') else '?'}）" for x in picked]
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
    elif r.get("pairs"):
        rows = [{"pair": f"{x['a_name']}—{x['b_name']}", "npmi": x["npmi"], "support": x["support"], "lift": x["lift"]} for x in r["pairs"][:20]]
        out.append(chart("hbar", "最显著的药对", rows, [("pair", "药对"), ("npmi", "NPMI"), ("support", "同方次数"), ("lift", "提升度")],
                         id="pairs-top", x={"key": "pair", "label": "药对"}, y={"label": "NPMI"}, series=[{"key": "npmi", "label": "NPMI"}]))
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
    doses = [x for x in (r.get("doses") or {}).get("by_period", []) if x.get("grams")]
    if doses:
        rows = [{"period": x["period"], "n": x["n"], **{k: x["grams"][k] for k in ("min", "q1", "median", "q3", "max")}} for x in doses]
        out.append(chart("range", f"{name} · 历代汤剂用量（克，学术估值）", rows,
                         [("period", "时期"), ("n", "见证"), ("min", "最小"), ("q1", "下四分位"), ("median", "中位"), ("q3", "上四分位"), ("max", "最大")],
                         id="usage-doses", subtitle="汤剂中以重量写出的剂量，按各期计量折合（两之克数取各期估值的中点）；丸、散与煮散为一料之量，不入此图；箱为四分位，须线为最小至最大",
                         x={"key": "period", "label": "时期"}, y={"label": "克", "min": 0},
                         range={"min": "min", "q1": "q1", "median": "median", "q3": "q3", "max": "max"},
                         note=_dose_note(r)))
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
    """``result`` with its charts under ``charts`` (when it has any)."""
    charts = build(kind, result, base)
    if charts:
        result["charts"] = charts
    return result


__all__ = ["BUILDERS", "MAX_SERIES", "SPEC_VERSION", "TYPES", "attach", "build", "chart"]
