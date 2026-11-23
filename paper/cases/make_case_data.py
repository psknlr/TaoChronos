"""Source data for the three case figures — every value a case figure draws is written here first.

    python paper/cases/make_case_data.py --knee K.zip --huangqi H.zip --lbp L.zip

The three archives are answers the conversation agent 道乃久 (Tao-R1) wrote on the full corpus on 2026-11-23 (the
report as Markdown, the tables it drew as CSV, the charts it drew as SVG and PNG).  Nothing is recomputed here and
nothing is added: the script copies the report's own tables, counts the passages the report cites and looks their
witnesses up in the corpus catalogues (``corpus/catalog/*.yaml``: title, author, dynasty, composition range), and reads
back from the agent's vector charts the few values no table carries:

* ``case1``: the outcomes of the retrieved case records by period (图18) and the formula-similarity matrix (图20);
* ``case2``: the 991 decoctions of the dose chart (图7; year and converted grams, read to 0.1 px ≈ 0.5 year and
  0.13 g, and checked here against the n, median and quartiles of the agent's own 表7), its LOESS line, the shares of
  the processing notes (图8) and the tropism survey (图3);
* ``case3``: the earliest witness of each rule the selection used (图2) and the edges of the pairing network (图1).

Each ``source_data/caseN_*.json`` holds the report's header, every table verbatim and the values read from the
charts; ``caseN_citations.csv`` lists every cited passage with its witness and date; ``caseN_answer.md`` is the
answer itself, verbatim, against which the figure scripts check every quotation and passage identifier they draw.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import zipfile
from collections import Counter
from html import unescape
from pathlib import Path

import numpy as np
import yaml

HOME = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "source_data"

PERIODS = [("先秦两汉", -475, 220.5), ("魏晋南北朝", 220.5, 581), ("隋唐五代", 581, 960), ("宋金元", 960, 1368),
           ("明", 1368, 1644), ("清", 1644, 1912), ("民国", 1912, 1950)]


# --- the archives -------------------------------------------------------------------------------------------------------
class Result:
    """One answer of the agent: its report, its tables (by number) and its vector charts (by number)."""

    def __init__(self, path: str | Path) -> None:
        self.zip = zipfile.ZipFile(path)
        names = self.zip.namelist()
        self.report_name = next(n for n in names if n.endswith(".md"))
        self.report = self.zip.read(self.report_name).decode("utf-8")
        self.tables: dict[int, dict] = {}
        for n in names:
            m = re.match(r"tables/表(\d+)(?:-(.*))?\.csv$", n)
            if m:
                rows = list(csv.reader(io.StringIO(self.zip.read(n).decode("utf-8-sig"))))
                self.tables[int(m.group(1))] = {"title": m.group(2) or "", "columns": rows[0], "rows": rows[1:]}
        self.svgs: dict[int, str] = {}
        self.svg_titles: dict[int, str] = {}
        for n in names:
            m = re.match(r"figures/图(\d+)-(.*)\.svg$", n)
            if m:
                self.svgs[int(m.group(1))] = self.zip.read(n).decode("utf-8")
                self.svg_titles[int(m.group(1))] = m.group(2)

    def header(self) -> dict:
        lines = self.report.splitlines()
        query = lines[0].lstrip("# ").strip()
        m = re.search(r"> (.+?)· (.+?)· (\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})", self.report)
        version = sorted({v for s in self.svgs.values() for v in re.findall(r"语料版本 ([0-9a-f]{12})", s)})
        return {"query": query, "agent": m.group(1).strip(), "publisher": m.group(2).strip(), "answered": m.group(3),
                "corpus_version": version, "report": self.report_name,
                "tables": {str(k): v["title"] for k, v in sorted(self.tables.items())},
                "charts": {str(k): v for k, v in sorted(self.svg_titles.items())}}

    def table(self, k: int) -> list[dict]:
        t = self.tables[k]
        return [dict(zip(t["columns"], r)) for r in t["rows"]]

    def svg_texts(self, k: int) -> list[str]:
        out = [unescape(re.sub(r"<[^>]+>", "", t)).strip()
               for t in re.findall(r"<text[^>]*>(.*?)</text>", self.svgs[k], flags=re.S)]
        return [t for t in out if t]


# --- the catalogues -----------------------------------------------------------------------------------------------------
def catalogue() -> dict[str, dict]:
    """Witness id → title, authors, dynasty, composition range, from every catalogue file."""
    entries: dict[str, dict] = {}

    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("id"), str):
                e = entries.setdefault(o["id"], {})
                for k in ("title", "authors", "dynasty", "composition", "category"):
                    if k in o and k not in e:
                        e[k] = o[k]
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    for f in sorted((HOME / "corpus" / "catalog").glob("*.yaml")):
        walk(yaml.safe_load(f.read_text(encoding="utf-8")))
    return entries


def citations(report: str, cat: dict[str, dict]) -> list[dict]:
    """Every passage the report cites as [[id]]: how often, and the witness it belongs to."""
    ids = re.findall(r"\[\[([^\]]+)\]\]", report)
    count = Counter(ids)
    rows = []
    for pid in dict.fromkeys(ids):
        m = re.match(r"^(.*?)(?:\.\d+)+$", pid)
        wit = m.group(1) if m else pid
        e = cat.get(wit)
        if e is None:  # a record of the safety reference, not a passage of the corpus
            rows.append({"passage_id": pid, "witness": "", "title": "", "authors": "", "dynasty": "",
                         "from": "", "to": "", "cited": count[pid], "kind": "reference record"})
            continue
        a, b = e["composition"]
        rows.append({"passage_id": pid, "witness": wit, "title": e.get("title", ""),
                     "authors": "、".join(e.get("authors") or []), "dynasty": e.get("dynasty", ""), "from": a, "to": b,
                     "cited": count[pid], "kind": "passage"})
    return rows


def evidence_summary(rows: list[dict]) -> dict:
    passages = [r for r in rows if r["kind"] == "passage"]
    wits = {r["witness"]: r for r in passages}
    return {"citations": sum(r["cited"] for r in rows), "passages": len(passages), "witnesses": len(wits),
            "reference_records": len(rows) - len(passages),
            "earliest": min(([r["from"], r["to"], r["title"]] for r in wits.values()), key=lambda v: v[1]),
            "latest": max(([r["from"], r["to"], r["title"]] for r in wits.values()), key=lambda v: v[1]),
            "witness_dates": sorted(([r["witness"], r["title"], r["from"], r["to"],
                                      sum(p["cited"] for p in passages if p["witness"] == r["witness"])]
                                     for r in wits.values()), key=lambda v: (v[2] + v[3]) / 2)}


def write_csv(name: str, rows: list[dict]) -> None:
    with open(OUT / name, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"  {name}: {len(rows)} rows")


def write_answer(name: str, res: "Result") -> None:
    """The answer itself, verbatim: the figures check every quotation and passage identifier against it."""
    (OUT / name).write_text(res.report, encoding="utf-8")
    print(f"  {name}: {len(res.report):,} characters")


def write_json(name: str, obj: dict) -> None:
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"  {name}")


def axis(svg: str, pattern: str) -> tuple[float, float]:
    """A linear axis read from its ticks: value = a × pixel + b."""
    ticks = [(float(p), float(v.replace("K", "e3").rstrip("%"))) for p, v in re.findall(pattern, svg)]
    (p0, v0), (p1, v1) = ticks[0], ticks[-1]
    a = (v1 - v0) / (p1 - p0)
    return a, v0 - a * p0


def period_of(year: float) -> str:
    return next(name for name, lo, hi in PERIODS if lo <= year < hi)


# --- case 1: knee pain, the formula ------------------------------------------------------------------------------------
def case1(res: Result, cat: dict[str, dict]) -> None:
    print("case 1 (bilateral knee pain: pattern and formula)")
    cites = citations(res.report, cat)
    write_csv("case1_citations.csv", cites)
    write_answer("case1_answer.md", res)
    # 图18: one stacked bar per period, a case is 21.7 px with a 2 px gap between segments
    svg = res.svgs[18]
    px = 261.0 - 44.0
    top = max(int(t) for t in res.svg_texts(18) if t.isdigit())
    unit = px / top
    labels = dict(zip(["#2a78d6", "#eb6834", "#1baf7a"], ["improved", "died", "not recorded"]))
    xs = sorted({float(x) for x in re.findall(r'<rect x="([\d.]+)" y="[\d.]+" width="24.0"', svg)})
    period = dict(zip(xs, ["明", "清"]))
    outcomes: dict[str, dict[str, int]] = {}
    for x, h, fill in re.findall(r'<rect x="([\d.]+)" y="[\d.]+" width="24.0" height="([\d.]+)" fill="(#\w+)"', svg):
        outcomes.setdefault(period[float(x)], {})[labels[fill]] = round((float(h) + 2.0) / unit)
    # 图20: the similarity matrix as printed
    txt = res.svg_texts(20)
    names = txt[:4]
    cells = txt[4:4 + 20]
    matrix = [[float(v) for v in cells[i * 5 + 1:i * 5 + 5]] for i in range(4)]
    assert [cells[i * 5] for i in range(4)] == names
    trend = re.search(r"趋\s*势 z = ([\d.]+)", "".join(res.svg_texts(3))).group(1)
    write_json("case1_knee_formula.json", {
        "header": res.header(), "evidence": evidence_summary(cites),
        "tables": {str(k): v for k, v in sorted(res.tables.items())},
        "from_charts": {
            "case_outcomes_by_period": outcomes,
            "case_outcomes_note": "图18 检索所得医案·各时期的转归: stacked counts read from the bar heights",
            "similarity": {"formulas": names, "matrix": matrix,
                           "note": "图20: dose-weighted overlap where both formulas are written with weights, "
                                   "otherwise the Jaccard index of their drugs"},
            "term_bizheng_trend_z": float(trend)},
        "from_report": {
            "pattern": "痹证·久痹，肝肾两虚，寒湿痹阻；兼腰痛",
            "formula": "独活寄生汤",
            "finding_works": 9,
            "case_records": {"naming_formula": 11, "ming": 1, "qing": 10, "women": 7, "improved": 9, "died": 1,
                             "not_recorded": 1},
            "clusters": [
                {"n": 1, "function": "祛风湿、通经络、止痹痛（治标）", "herbs": ["独活", "细辛", "秦艽", "防风"]},
                {"n": 2, "function": "温经散寒", "herbs": ["桂心"]},
                {"n": 3, "function": "补肝肾、强筋骨、固下（治本）", "herbs": ["桑寄生", "杜仲", "牛膝"]},
                {"n": 4, "function": "养血活血、荣筋止痛（治风先治血）", "herbs": ["当归", "川芎", "芍药", "熟地黄"]},
                {"n": 5, "function": "益气健脾（扶正以祛邪）", "herbs": ["人参", "茯苓", "甘草"]}]}})


# --- case 2: Huangqi ----------------------------------------------------------------------------------------------------
def case2(res: Result, cat: dict[str, dict]) -> None:
    print("case 2 (Huangqi across the materia medica)")
    cites = citations(res.report, cat)
    write_csv("case2_citations.csv", cites)
    write_answer("case2_answer.md", res)
    # 图7: every decoction as (year, grams) and the LOESS line
    svg = res.svgs[7]
    ax, bx = axis(svg, r'<line x1="([\d.]+)" y1="260.7" x2="\1" y2="264.7"[^>]*/><text[^>]*>(\d+)</text>')
    ay, by = axis(svg, r'<line x1="52.3" y1="([\d.]+)" x2="56.3" y2="\1"[^>]*/><text[^>]*>(\d+)</text>')
    pts = [(ax * float(x) + bx, ay * float(y) + by)
           for x, y in re.findall(r'<circle cx="([\d.]+)" cy="([\d.]+)" r="3.0"', svg)]
    doses = [{"year": round(y), "grams": round(g, 1), "period": period_of(y)} for y, g in pts]
    write_csv("case2_decoction_doses.csv", doses)
    loess = [[round(ax * float(x) + bx), round(ay * float(y) + by, 1)]
             for x, y in (p.split(",") for p in re.search(r'<polyline points="([^"]+)"', svg).group(1).split())]
    # the recovered points against the agent's own table (表7): n, median and quartiles of every period
    check = []
    for row in res.table(7):
        v = np.array([d["grams"] for d in doses if d["period"] == row["时期"]])
        med, q1, q3 = (float(x) for x in re.match(r"([\d.]+) \(([\d.]+), ([\d.]+)\)",
                                                   row["折合克数（g） · M (P25, P75)"]).groups())
        got = [float(np.median(v)), float(np.percentile(v, 25)), float(np.percentile(v, 75))]
        ok = len(v) == int(row["n"]) and all(abs(a - b) <= 0.25 for a, b in zip(got, [med, q1, q3]))
        check.append({"period": row["时期"], "n_table": int(row["n"]), "n_read": int(len(v)),
                      "median_table": med, "median_read": round(got[0], 1), "agrees": bool(ok)})
        assert ok, (row, got)
    # 图8: shares of the processing notes (a share is (height + 2) / 217 px)
    svg = res.svgs[8]
    names = dict(zip(["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#b3b1aa"],
                     ["锉", "炒", "炙", "蜜炙", "去芦", "细锉", "其他"]))
    xs = sorted({float(x) for x in re.findall(r'<rect x="([\d.]+)" y="[\d.]+" width="24.0"', svg)})
    per = dict(zip(xs, ["先秦两汉", "隋唐五代", "宋金元", "明", "清"]))
    proc: dict[str, dict[str, float]] = {}
    for x, h, fill in re.findall(r'<rect x="([\d.]+)" y="[\d.]+" width="24.0" height="([\d.]+)" fill="(#\w+)"', svg):
        proc.setdefault(per[float(x)], {})[names[fill]] = round((float(h) + 2.0) / 217.0 * 100, 1)
    # 图3: works stating a tropism, by period (the numbers printed in the cells)
    svg = res.svgs[3]
    cols = dict(zip([68.0, 132.0, 196.0, 260.0, 324.0], ["先秦两汉", "魏晋南北朝", "宋金元", "明", "清"]))
    rows = {float(y): t for y, t in re.findall(r'<text x="28.0" y="([\d.]+)"[^>]*>([^<]+)</text>', svg)}
    cells = re.findall(r'<text x="([\d.]+)" y="([\d.]+)" font-size="10" fill="#ffffff"[^>]*>(\d+)<', svg)
    tropism = [{"organ": rows[float(y)], "period": cols[float(x)], "works": int(v)} for x, y, v in cells]
    stats = {
        "share_trend_z": float(re.search(r"z = ([\d.]+)", "".join(res.svg_texts(5))).group(1)),
        "dose_kruskal_wallis_H": float(re.search(r"H = ([\d.]+)", "".join(res.svg_texts(6))).group(1)),
        "dose_spearman_rho_chart": float(re.search(r"ρ = (-?[\d.]+)", "".join(res.svg_texts(7))).group(1)),
        "dose_n": int(re.search(r"n = (\d+)", "".join(res.svg_texts(7))).group(1))}
    npmi = res.svg_texts(19)
    i0 = npmi.index("鹿肉")
    write_json("case2_huangqi.json", {
        "header": res.header(), "evidence": evidence_summary(cites),
        "tables": {str(k): v for k, v in sorted(res.tables.items())},
        "from_charts": {"dose_loess": loess, "dose_points_check": check, "processing_share_percent": proc,
                        "tropism_works": tropism, "statistics": stats,
                        "npmi": [[npmi[i], float(npmi[i + 1])] for i in range(i0, i0 + 30, 2)]},
        "from_report": {
            "compositions": 69744, "works_with_compositions": 101, "with_huangqi": 2693, "share_percent": 3.86,
            "corpus_works": 958, "share_trend": {"z": 4.163, "p": 0.000031},
            "dose_spearman": {"rho": -0.3375, "p": 8.0e-28, "n": 991},
            "largest_dose_share_percent": 50.7, "tropism_works_stating": 4, "materia_medica_works": 13,
            "incompatibility_pairs_with_huangqi": 0}})


# --- case 3: low back pain, acupuncture ---------------------------------------------------------------------------------
def case3(res: Result, cat: dict[str, dict]) -> None:
    print("case 3 (low back pain: points)")
    cites = citations(res.report, cat)
    write_csv("case3_citations.csv", cites)
    write_answer("case3_answer.md", res)
    # 图2: a rule's earliest witness; the axis is linear between its ticks
    svg = res.svgs[2]
    a, b = axis(svg, r'<line x1="([\d.]+)" y1="160.0" x2="\1" y2="164.0"[^>]*/><text[^>]*>(\d+)</text>')
    kind = {"#2a78d6": "classic", "#eb6834": "textbook"}
    dots = [(float(x), float(y), kind[f]) for x, y, f in
            re.findall(r'<circle cx="([\d.]+)" cy="([\d.]+)" r="4" fill="(#\w+)"', svg)]
    labels = [(float(x), float(y), t) for x, y, t in
              re.findall(r'<text x="([\d.]+)" y="([\d.]+)" font-size="10.5" fill="#000000"[^>]*>([^<]+)</text>', svg)]
    rules = []
    for x, y, k in dots:
        name = min(labels, key=lambda v: abs(v[1] - 4.0 - y) * 1000 + abs(v[0] - x))[2]
        rules.append({"rule": name, "source": k, "earliest_year": int(round((a * x + b) / 1.0))})
    # 图1: nodes and edges of the pairing network
    svg = res.svgs[1]
    nodes = [(float(x), float(y), t) for (x, y), t in zip(
        re.findall(r'<circle cx="([\d.]+)" cy="([\d.]+)" r="12"', svg),
        re.findall(r'<text x="[\d.]+" y="[\d.]+" font-size="10.5" fill="#000000"[^>]*>([^<]+)</text>', svg))]
    near = lambda x, y: min(nodes, key=lambda n: (n[0] - x) ** 2 + (n[1] - y) ** 2)[2]  # noqa: E731
    edges = [[near(float(x1), float(y1)), near(float(x2), float(y2))] for x1, y1, x2, y2 in re.findall(
        r'<line x1="([\d.]+)" y1="([\d.]+)" x2="([\d.]+)" y2="([\d.]+)" stroke="#9a9a9a"', svg)]
    write_json("case3_low_back_pain.json", {
        "header": res.header(), "evidence": evidence_summary(cites),
        "tables": {str(k): v for k, v in sorted(res.tables.items())},
        "from_charts": {"rule_earliest_witness": rules, "pairing_network_edges": edges},
        "from_report": {
            "review_verdict": "information insufficient",
            "blocking_findings": [
                "Candidate points may only be released against a reviewed premise that matches this case's organ, "
                "aspect and excess/deficiency status",
                "The 'take the channel itself' method (不实不虚，以经取之) requires an explicitly established "
                "实 / 虚 / 不实不虚 — and 'unknown' is neither"],
            "kidney_state": "unknown",
            "layers": {"A local": ["阿是穴", "腰阳关 GV3", "肾俞 BL23", "大肠俞 BL25"],
                       "B distal": ["委中 BL40", "昆仑 BL60"],
                       "C upper–lower, extraordinary vessel": ["后溪 SI3", "申脉 BL62"]},
            "not_found_in_corpus": "《素问·刺腰痛篇》"}})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--knee", required=True, help="archive of the knee-pain answer")
    ap.add_argument("--huangqi", required=True, help="archive of the Huangqi answer")
    ap.add_argument("--lbp", required=True, help="archive of the low-back-pain answer")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    cat = catalogue()
    case1(Result(args.knee), cat)
    case2(Result(args.huangqi), cat)
    case3(Result(args.lbp), cat)


if __name__ == "__main__":
    main()
