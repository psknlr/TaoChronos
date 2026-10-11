"""描述与比较 — a user's table described column by column and its groups compared, as a paper reports them.

* ``describe``: each numeric column's n, missing, x̄ ± s, M (P25, P75) and range, with its histogram; each categorical
  column's categories, n (%), with a bar chart — two three-line tables, the numeric and the categorical variables;
* ``compare``: an outcome across the groups of another column — a numeric outcome by Kruskal–Wallis (each group's n,
  x̄ ± s, M (P25, P75); a box plot with its values), a categorical one by Pearson's χ² (Fisher's exact test for a 2 × 2
  table with an expected count under 5; n (%) by group; a stacked chart), two numeric columns by Spearman's ρ (a
  scatter with a LOESS curve).

The numbers are the data's, computed here; a test says what it tests and on how many — it does not say why.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from ...science.stats import chi_square_independence, fisher_exact_two_sided, kruskal_wallis, loess, mean_sd, spearman, tukey
from ..classics.study.charts import chart
from ..classics.study.tables import fixed, med_iqr, n_pct, p_eq, p_value, table
from .store import Dataset, number

MAX_GROUPS = 12
MAX_CATEGORIES = 10
NOTE = "数据为用户自有资料，在本机读取并已脱敏；统计只描述这份数据，不推断因果。"


def source(ds: Dataset) -> str:
    """A figure's source line: the user's data, read here (the file's name stays out: a figure leaves the page)."""
    return "道乃久（TaoChronos）· 用户资料（本机分析）"


def _fmt(x: float | None, digits: int = 2) -> str:
    if x is None:
        return ""
    a = abs(x)
    if a >= 1000 or float(x).is_integer():
        return f"{x:,.0f}" if a >= 1000 else str(int(x))
    return f"{x:.{digits}f}".rstrip("0").rstrip(".")


def _table_only(ds: Dataset) -> None:
    if ds.kind != "table":
        raise ValueError(f"「{ds.name}」是文本资料：描述统计与组间比较只用于表格（CSV、Excel）；文本请用检索与阅读")


def _numbers(ds: Dataset, col: str) -> list[float | None]:
    return [number(v) for v in ds.values(col)]


def _bins(xs: list[float], target: int = 10) -> list[tuple[float, float, int]]:
    """Equal bins of a round width over the values: (from, to, count) — the last one closed."""
    lo, hi = min(xs), max(xs)
    if hi == lo:
        return [(lo, hi, len(xs))]
    raw = (hi - lo) / target
    mag = 10 ** math.floor(math.log10(raw))
    step = next(s * mag for s in (1, 2, 2.5, 5, 10) if raw <= s * mag + 1e-12)
    start = math.floor(lo / step) * step
    edges = []
    x = start
    while x <= hi + 1e-9:
        edges.append(x)
        x += step
    if edges[-1] <= hi:
        edges.append(edges[-1] + step)
    counts = [0] * (len(edges) - 1)
    for v in xs:
        k = min(int((v - start) // step), len(counts) - 1)
        counts[k] += 1
    return [(edges[i], edges[i + 1], counts[i]) for i in range(len(counts))]


# ------------------------------------------------------------------ 描述
def describe(ds: Dataset, columns: list[str] | None = None, *, top: int = 8) -> dict[str, Any]:
    _table_only(ds)
    cols = [ds.columns[ds.column(c)] for c in columns] if columns else [c for c in ds.columns if ds.types.get(c) != "empty"]
    variables: list[dict[str, Any]] = []
    numeric_rows, cat_rows, charts = [], [], []
    for c in cols:
        kind = ds.types.get(c, "text")
        cells = ds.values(c)
        present = [v for v in cells if v.strip()]
        item: dict[str, Any] = {"column": c, "type": kind, "n": len(present), "missing": len(cells) - len(present)}
        if kind == "number":
            xs = [x for x in (number(v) for v in present) if x is not None]
            if xs:
                q = tukey(xs)
                m, sd = mean_sd(xs)
                item.update(mean=round(m, 4), sd=round(sd, 4), median=q["median"], q1=q["q1"], q3=q["q3"], min=q["min"], max=q["max"])
                numeric_rows.append({"v": c, "n": len(xs), "missing": item["missing"], "mean": f"{_fmt(m)} ± {_fmt(sd)}",
                                     "med": f"{_fmt(q['median'])} ({_fmt(q['q1'])}, {_fmt(q['q3'])})", "range": f"{_fmt(q['min'])}–{_fmt(q['max'])}"})
                if sum(1 for ch in charts if ch["type"] == "bar") < 3 and len(xs) >= 5:
                    bins = _bins(xs)
                    rows = [{"bin": f"{_fmt(a)}–{_fmt(b)}", "n": k} for a, b, k in bins]
                    charts.append(chart("bar", f"{c}的分布", rows, [("bin", c), ("n", "例数")], id=f"mine-hist-{len(charts)}",
                                        subtitle=f"n = {len(xs)}；每柱为一个等宽区间（含左端）", x={"key": "bin", "label": c},
                                        y={"label": "例数", "min": 0}, series=[{"key": "n", "label": "例数"}], source=source(ds)))
        elif kind == "prescription":
            item["distinct"] = len(set(present))
            if present:
                item["example"] = present[0][:60]
            item["hint"] = "处方列：用 mydata.prescriptions 分析其用药"
        elif kind in ("category", "date") or kind == "text" and len(set(present)) <= 30:
            counts = Counter(present).most_common()
            item["distinct"] = len(counts)
            item["values"] = [{"value": v, "n": k, "share": round(k / len(present), 4)} for v, k in counts[:top]]
            if kind == "date" and present:
                item["first"], item["last"] = min(present), max(present)
            if kind != "date":
                shown = counts[:top]
                for j, (v, k) in enumerate(shown):
                    cat_rows.append({"v": c if j == 0 else "", "cat": v[:40], "n": n_pct(k, len(present))})
                rest = sum(k for _, k in counts[top:])
                if rest:
                    cat_rows.append({"v": "", "cat": f"其他（{len(counts) - top} 类）", "n": n_pct(rest, len(present))})
                if kind == "category" and sum(1 for ch in charts if ch["type"] == "hbar") < 3 and len(counts) >= 2:
                    rows = [{"cat": v[:24], "n": k, "share": round(k / len(present), 4)} for v, k in counts[:15]]
                    charts.append(chart("hbar", f"{c}的构成", rows, [("cat", c), ("n", "例数"), ("share", "构成比")], id=f"mine-cat-{len(charts)}",
                                        subtitle=f"n = {len(present)}" + (f"；前 15 类（共 {len(counts)} 类）" if len(counts) > 15 else ""),
                                        x={"key": "cat", "label": c}, y={"label": "例数", "min": 0}, series=[{"key": "n", "label": "例数"}],
                                        source=source(ds)))
        else:
            item["distinct"] = len(set(present))
            if present:
                item["example"] = present[0][:60]
        variables.append(item)
    tables = []
    if numeric_rows:
        tables.append(table("mine-numeric", "数值变量的描述统计", [("v", "变量", "l"), ("n", "n", "c"), ("missing", "缺失", "c"),
                            ("mean", "x̄ ± s", "c"), ("med", "M (P25, P75)", "c"), ("range", "最小–最大", "c")], numeric_rows,
                            notes=["x̄ ± s：均数 ± 标准差；M (P25, P75)：中位数（第 25、75 百分位数）。偏态分布宜报告中位数与四分位数。", NOTE],
                            source=source(ds)))
    if cat_rows:
        tables.append(table("mine-categorical", "分类变量的分布", [("v", "变量", "l"), ("cat", "类别", "l"), ("n", "n (%)", "c")],
                            cat_rows, notes=["百分比以该变量的非缺失例数为分母。", NOTE], source=source(ds)))
    return {"dataset": ds.id, "name": ds.name, "rows": len(ds.rows), "variables": variables, "charts": charts[:6], "tables": tables,
            "note": NOTE}


# ------------------------------------------------------------------ 比较
def _groups(ds: Dataset, col: str, rows: list[int]) -> tuple[list[str], dict[int, str]]:
    """The groups of a categorical column over the rows that have it: the largest ``MAX_GROUPS``, the rest as 其他."""
    i = ds.column(col)
    counts = Counter(ds.rows[r][i] for r in rows)
    keep = [g for g, _ in counts.most_common(MAX_GROUPS)]
    rest = len(counts) > MAX_GROUPS
    of = {r: (ds.rows[r][i] if ds.rows[r][i] in keep else "其他") for r in rows}
    return keep + (["其他"] if rest else []), of


def compare(ds: Dataset, outcome: str, group: str) -> dict[str, Any]:
    """An outcome across the groups of another column (both by their heads)."""
    _table_only(ds)
    oc, gc = ds.columns[ds.column(outcome)], ds.columns[ds.column(group)]
    if oc == gc:
        raise ValueError("结局与分组须是两列")
    ot, gt = ds.types.get(oc, "text"), ds.types.get(gc, "text")
    oi, gi = ds.column(oc), ds.column(gc)
    rows = [r for r in range(len(ds.rows)) if ds.rows[r][oi].strip() and ds.rows[r][gi].strip()]
    if len(rows) < 4:
        raise ValueError(f"「{oc}」与「{gc}」都有值的行只有 {len(rows)} 行，不足以比较")
    if ot == "number" and gt == "number":
        return _correlate(ds, oc, gc, rows)
    if ot != "number" and gt == "number":  # a numeric "group" and a categorical outcome: the number compared across the categories
        oc, gc, ot, gt, oi, gi = gc, oc, gt, ot, gi, oi
    if ot == "number":
        return _numeric_by_group(ds, oc, gc, rows)
    return _categorical_by_group(ds, oc, gc, rows)


def _numeric_by_group(ds: Dataset, oc: str, gc: str, rows: list[int]) -> dict[str, Any]:
    oi = ds.column(oc)
    names, of = _groups(ds, gc, rows)
    values: dict[str, list[float]] = {g: [] for g in names}
    for r in rows:
        x = number(ds.rows[r][oi])
        if x is not None:
            values[of[r]].append(x)
    names = [g for g in names if values[g]]
    test = kruskal_wallis([values[g] for g in names])
    per = []
    for g in names:
        xs = values[g]
        q = tukey(xs)
        m, sd = mean_sd(xs)
        per.append({"group": g, "n": len(xs), "mean": round(m, 4), "sd": round(sd, 4), "median": q["median"], "q1": q["q1"], "q3": q["q3"],
                    "min": q["min"], "max": q["max"]})
    trows = [{"g": p["group"], "n": p["n"], "mean": f"{_fmt(p['mean'])} ± {_fmt(p['sd'])}", "med": med_iqr(p, -1)} for p in per]
    said = (f"Kruskal–Wallis 检验：H = {test['h']:.2f}，df = {test['df']}，{p_eq(test['p'])}（n = {test['n']}）。" if test else "各组取值相同，无法检验。")
    tables = [table("mine-compare", f"「{oc}」在各「{gc}」组的比较", [("g", gc, "l"), ("n", "n", "c"), ("mean", "x̄ ± s", "c"),
                    ("med", "M (P25, P75)", "c")], trows, notes=[said + ("两组时与 Mann–Whitney U 检验等价。" if len(per) == 2 else ""), NOTE],
                    source=source(ds))]
    points = {g: values[g][:300] for g in names}
    box_rows = [{"group": p["group"], **{k: p[k] for k in ("n", "q1", "median", "q3", "mean", "min", "max")}} for p in per]
    for row, g in zip(box_rows, names):
        t = tukey(values[g])
        row.update(lo=t["lo"], hi=t["hi"])
    charts = [chart("box", f"「{oc}」按「{gc}」分组", box_rows, [("group", gc), ("n", "n"), ("median", "中位数"), ("q1", "P25"), ("q3", "P75"),
                    ("mean", "均数"), ("min", "最小"), ("max", "最大")], id="mine-compare-box",
                    subtitle=said.rstrip("。"), x={"key": "group", "label": gc}, y={"label": oc}, points=points, source=source(ds))]
    out = {"dataset": ds.id, "name": ds.name, "outcome": oc, "group": gc, "kind": "numeric by group", "groups": per,
           "test": ({"name": "Kruskal–Wallis", **test} if test else None), "charts": charts, "tables": tables, "note": NOTE}
    return out


def _categorical_by_group(ds: Dataset, oc: str, gc: str, rows: list[int]) -> dict[str, Any]:
    groups, gof = _groups(ds, gc, rows)
    oi = ds.column(oc)
    cats = [c for c, _ in Counter(ds.rows[r][oi] for r in rows).most_common(MAX_CATEGORIES)]
    other = any(ds.rows[r][oi] not in cats for r in rows)
    cats_all = cats + (["其他"] if other else [])
    cell: dict[tuple[str, str], int] = Counter((gof[r], ds.rows[r][oi] if ds.rows[r][oi] in cats else "其他") for r in rows)
    counts = [[cell.get((g, c), 0) for c in cats_all] for g in groups]
    test = chi_square_independence(counts)
    method = "Pearson χ² 检验"
    fisher = None
    if len(groups) == 2 and len(cats_all) == 2 and test and test["min_expected"] < 5:
        (a, b), (c, d) = counts
        fisher = fisher_exact_two_sided(a, b, c, d)
        method = "Fisher 精确检验（双侧；有期望频数小于 5）"
    if fisher is not None:
        said = f"{method}：{p_eq(fisher)}（n = {sum(map(sum, counts))}）。"
    elif test:
        said = (f"{method}：χ² = {test['chi2']:.2f}，df = {test['df']}，{p_eq(test['p'])}（n = {test['n']}），Cramér's V = {test['cramers_v']:.2f}。"
                + ("有期望频数小于 5 的格子，χ² 近似欠准，宜合并类别或增大样本。" if test["min_expected"] < 5 else ""))
    else:
        said = "只有一组或一类，无法检验。"
    keys = [f"c{j}" for j in range(len(cats_all))]
    trows = [{"g": g, **{k: n_pct(counts[i][j], sum(counts[i])) for j, k in enumerate(keys)}, "n": sum(counts[i])} for i, g in enumerate(groups)]
    tables = [table("mine-crosstab", f"「{oc}」在各「{gc}」组的分布", [("g", gc, "l"), ("n", "n", "c")]
                    + [(k, c[:20], "c", f"{oc}，n (%)") for k, c in zip(keys, cats_all)], trows,
                    notes=["百分比为行百分比（各组内的构成）。", said, NOTE], source=source(ds))]
    srows = [{"group": g, **{k: counts[i][j] for j, k in enumerate(keys)}} for i, g in enumerate(groups)]
    charts = [chart("stack", f"「{oc}」按「{gc}」分组的构成", srows, [("group", gc)] + list(zip(keys, cats_all)), id="mine-compare-stack",
                    percent=True, subtitle=said.rstrip("。"), x={"key": "group", "label": gc}, y={"label": "构成比", "percent": True},
                    series=[{"key": k, "label": c} for k, c in zip(keys, cats_all)][:8], source=source(ds))]
    return {"dataset": ds.id, "name": ds.name, "outcome": oc, "group": gc, "kind": "categorical by group", "categories": cats_all,
            "counts": [{"group": g, **dict(zip(cats_all, counts[i]))} for i, g in enumerate(groups)],
            "test": ({"name": "Fisher", "p": fisher} if fisher is not None else {"name": "Pearson chi-square", **test} if test else None),
            "charts": charts, "tables": tables, "note": NOTE}


def _correlate(ds: Dataset, yc: str, xc: str, rows: list[int]) -> dict[str, Any]:
    yi, xi = ds.column(yc), ds.column(xc)
    pts = [(number(ds.rows[r][xi]), number(ds.rows[r][yi]), r) for r in rows]
    pts = [(x, y, r) for x, y, r in pts if x is not None and y is not None]
    rho = spearman([x for x, _, _ in pts], [y for _, y, _ in pts])
    said = f"Spearman 相关：ρ = {rho['rho']:.2f}，{p_eq(rho['p'])}，n = {rho['n']}。" if rho else "取值不变，无法计算相关。"
    fit = loess([x for x, _, _ in pts], [y for _, y, _ in pts]) if len(pts) >= 10 else []
    shown = pts if len(pts) <= 1500 else pts[:: math.ceil(len(pts) / 1500)]
    charts = [chart("scatter", f"「{yc}」与「{xc}」", [{"x": x, "y": y, "row": ds.part_id(r)} for x, y, r in shown],
                    [("x", xc), ("y", yc), ("row", "行")], id="mine-correlate", subtitle=said.rstrip("。"),
                    x={"key": "x", "label": xc}, y={"key": "y", "label": yc}, label="row",
                    fit={"points": fit, "label": "LOESS"} if fit else None, source=source(ds))]
    tables = [table("mine-correlate", f"「{yc}」与「{xc}」的相关", [("x", "变量", "l"), ("n", "n", "c"), ("rho", "ρ", "c"), ("p", "P", "c")],
                    [{"x": f"{yc} — {xc}", "n": rho["n"] if rho else len(pts), "rho": fixed(rho["rho"], 2) if rho else "",
                      "p": p_value(rho["p"]) if rho else ""}], notes=["ρ：Spearman 秩相关系数（双侧检验，t 近似）。", NOTE], source=source(ds))]
    return {"dataset": ds.id, "name": ds.name, "outcome": yc, "group": xc, "kind": "correlation",
            "test": ({"name": "Spearman", **rho} if rho else None), "charts": charts, "tables": tables, "note": NOTE}


__all__ = ["compare", "describe"]
