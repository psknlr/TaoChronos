"""处方分析 — a user's prescriptions read with the classics' lexicon and set beside the compositions of the classics.

A prescription is a cell of a table (or a passage of a text) that names drugs, with or without doses: 柴胡12g 黄芩9g
半夏9g …, 桂枝三两，芍药三两 …, 丹参、葛根、山楂.  Each drug is read with the lexicon and counted under its family as
the classics are (炙甘草 → 甘草, 白芍 → 芍药, 生地黄 and 熟地黄 → 地黄); a name the lexicon lacks is counted as written
when a dose follows it (党参15g), and listed.  A dose in grams (g, 克; mg; kg) is kept in grams; others (钱, 两, 片, 枚)
as written, unconverted — what a 两 weighed depends on the period and the prescriber.

From them, as ``study pairs`` reads the classics: the drugs used most, their doses, the pairs used together more
often than chance (one-sided Fisher test, Benjamini–Hochberg), the association rules, a clustering of the most
frequent drugs; by group (a diagnosis, a syndrome) which drugs differ across the groups (χ² or Fisher, corrected); and
for each prescription the composition of the classics nearest to it (Jaccard on the drug families) with its witness —
the book, the year and the passage, to read.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Any

from ...science.stats import benjamini_hochberg, chi_square_independence, fisher_exact_two_sided, tukey
from ..classics.study.charts import chart
from ..classics.study.metrology import cn_number
from ..classics.study.tables import est, est_ci, fixed, med_iqr, n_pct, p_value, pct, table
from .analysis import NOTE, source
from .store import Dataset

_NUM = r"(?:\d+(?:\.\d+)?|[〇零一二三四五六七八九十百半]+)"
_UNIT = r"(?:mg|毫克|kg|千克|公斤|g|G|克|ml|mL|毫升|钱|两|分|斤|片|枚|个|只|条|粒|cm|厘米|寸|升|合|支|根|朵|对|袋|包)"
_WEIGHT = r"(?:mg|毫克|g|G|克|钱|两)"
_PREP = r"(?:去[皮节心尖核芦毛子须]+|[炙炒煨焙洗切擘碎捣研烧熬泡浸蒸煅]{1,2}|酒[洗炒浸蒸]|蜜炙|绵裹|先煎|后下|包煎|另煎|烊化|冲服|生用|打碎)"
_NOT_DOSE = r"(?![剂次天日周付岁年月])"
_DOSE_AT = re.compile(rf"[\s:：]*(?:{_PREP}[\s,，]*)?(各)?\s*({_NUM})\s*({_UNIT})?{_NOT_DOSE}")  # right after a drug's name
_UNKNOWN = re.compile(rf"([一-鿿]{{2,6}}?)[\s:：]*(?:{_PREP}[\s,，]*)?(各)?\s*({_NUM})\s*({_WEIGHT}){_NOT_DOSE}")  # a name the lexicon lacks
_NOTE = re.compile(r"[（(][^（）()]{0,16}[）)]")  # （炙）, (先煎): read past
_BARE = re.compile(r"^[\s、，,；;/／+＋]*$")
_HAN_CHAR = re.compile(r"[一-鿿]")
_ROUTINE = ("水煎", "煎服", "冲服", "后下", "先煎", "包煎", "另煎", "烊化", "兑服", "分服", "温服", "顿服", "每日", "一日", "早晚", "加减",
            "口服", "研末", "为末", "连服", "共服", "每次", "每剂", "疗程", "剂量", "处方", "用法", "共计", "合计", "评分", "体重")
# a character before a drug's name that is not part of it: a numeral, a unit, 各, or a word that introduces a drug (加柴胡)
_NOT_PREFIX = set("〇零一二三四五六七八九十百千半两钱分斤升合枚片个只条粒寸支根朵对袋包克毫剂付各"
                  "予用加以去减合配伍入服煎及和与并再另改换增等或之其")
GRAMS = {"g": 1.0, "G": 1.0, "克": 1.0, "mg": 0.001, "毫克": 0.001, "kg": 1000.0, "千克": 1000.0, "公斤": 1000.0}
MERGES = ("written", "family")
MERGE_NOTE = {"written": "药名照写法计（白芍与赤芍、炙甘草与甘草分计；异体字已归一）",
              "family": "药名按药类归并，与经典比较时相同（白芍、赤芍 → 芍药，炙甘草 → 甘草，桂枝、肉桂 → 桂）"}
MAX_CLASSIC_MATCHES = 200
MIN_JACCARD = 0.3  # a composition of the classics nearer than this, sharing two drugs at least, is named


class PrescriptionReader:
    """Reads prescriptions with the classics' study service (its lexicon, drug families, pairs and compositions)."""

    def __init__(self, study: Any) -> None:
        self.s = study
        self.lex = study.pack.lexicon
        self.families = study._formulas.families
        self.pairs = study._pairs

    # ------------------------------------------------------------ reading
    def family_key(self, surface: str, term: str, term_id: str) -> str:
        """The key the classics count a drug under: its family (白芍 → 芍药, 桂枝 → 桂) or its lexicon entry."""
        fam = self.families.get(surface) or self.families.get(term)
        return f"family:{fam}" if fam else term_id

    def label(self, key: str) -> str:
        return key.split(":", 1)[1] if key.startswith(("raw:", "w:")) else self.pairs._label(key)

    def herbs(self, text: str) -> list[Any]:
        return [m for m in self.lex.match(self.s.normalize(text), include_weak=False) if m.category == "herb"]

    def looks_like(self, cells: list[str]) -> str | None:
        """``prescription`` when most of the cells name two drugs or more (a column's type, for the store)."""
        sample = [c for c in cells[:300] if len(c) >= 4]
        if len(sample) < max(1, 0.5 * len(cells[:300])):
            return None
        hits = sum(1 for c in sample if len(self.herbs(c)) >= 2)
        return "prescription" if hits >= 0.5 * len(sample) else None

    def parse(self, text: str, merge: str = "written") -> tuple[list[dict[str, Any]], list[str]]:
        """The drugs of one prescription in the order written — [{key, family, name, written, dose, grams}] — and the
        names the lexicon lacks that were read as drugs because a weight follows them (党参15g).

        A drug's dose is what follows its name (桂枝三两, 柴胡 12g, 甘草二两（炙）, 桂枝去皮三两); 各 gives the dose to
        the drugs named just before it without one (柴胡、黄芩各9g).  ``merge`` is how drugs are counted: ``written``
        as written (白芍 and 赤芍, 炙甘草 and 甘草 apart), ``family`` as the classics (白芍 → 芍药, 炙甘草 → 甘草);
        a drug written twice in one prescription is counted once, its grams added."""
        norm = _NOTE.sub(lambda m: " " * len(m.group()), self.s.normalize(text))  # positions kept
        mentions = [m for m in self.lex.match(norm, include_weak=False) if m.category == "herb"]
        items: list[dict[str, Any]] = []
        unknown: list[str] = []

        def strangers(span: str, offset: int) -> None:
            for u in _UNKNOWN.finditer(span):
                name = u.group(1)
                if any(w in name for w in _ROUTINE):
                    continue
                unknown.append(name)
                items.append({"key": f"raw:{name}", "family": f"raw:{name}", "name": name, "written": text[offset + u.start(1): offset + u.end(1)],
                              "dose": u.group(3) + u.group(4), "grams": self._grams(u.group(3), u.group(4)), "bare": False})

        strangers(norm[: mentions[0].start] if mentions else norm, 0)
        for i, m in enumerate(mentions):
            end = mentions[i + 1].start if i + 1 < len(mentions) else len(norm)
            zone = norm[m.end: end]
            d = _DOSE_AT.match(zone)
            family = self.family_key(m.surface, m.entry.term, m.entry.term_id)
            start = m.start
            # written as one word with the character before it, which the lexicon lacks (夜交藤, 川牛膝, 生石膏)
            if (start and _HAN_CHAR.match(norm[start - 1]) and norm[start - 1] not in _NOT_PREFIX
                    and (start == 1 or not _HAN_CHAR.match(norm[start - 2])) and not (i and mentions[i - 1].end == start)):
                start -= 1
            key = family if merge == "family" else f"w:{norm[start: m.end]}"
            item = {"key": key, "family": family, "name": self.label(key), "written": text[start: m.end],
                    "dose": (d.group(2) + (d.group(3) or "")) if d else "", "grams": self._grams(d.group(2), d.group(3)) if d else None,
                    "bare": bool(_BARE.match(zone))}
            items.append(item)
            if d and d.group(1):  # 各: the drugs named just before, without a dose of their own, take it too
                for prev in reversed(items[:-1]):
                    if prev["dose"] or not prev["bare"]:
                        break
                    prev["dose"], prev["grams"] = item["dose"], item["grams"]
            strangers(zone[d.end():] if d else zone, m.end + (d.end() if d else 0))
        merged: dict[str, dict[str, Any]] = {}
        for it in items:
            it.pop("bare")
            if it["key"] in merged:
                old = merged[it["key"]]
                old["dose"] = "+".join(x for x in (old["dose"], it["dose"]) if x)
                if it["grams"] is not None:
                    old["grams"] = round((old["grams"] or 0.0) + it["grams"], 4)
                continue
            merged[it["key"]] = it
        return list(merged.values()), unknown

    @staticmethod
    def _grams(num: str | None, unit: str | None) -> float | None:
        if not num or (unit or "") not in GRAMS:
            return None
        try:
            value = float(num)
        except ValueError:
            value = cn_number(num)
        return round(value * GRAMS[unit], 4) if value else None

    # ------------------------------------------------------------ the analysis
    def analyse(self, ds: Dataset, column: str | None = None, *, group: str | None = None, merge: str = "written",
                classics: bool = True, min_support: int | None = None, top: int = 20) -> dict[str, Any]:
        if merge not in MERGES:
            raise ValueError(f"merge 只能是 {' 或 '.join(MERGES)}")
        texts, ids, groups, column = self._prescriptions(ds, column, group)
        parsed = [(self.parse(t, merge), pid, g) for t, pid, g in zip(texts, ids, groups)]
        rx = [(items, pid, g) for (items, _), pid, g in parsed if len(items) >= 2]
        if len(rx) < 3:
            raise ValueError(f"「{ds.name}」中读出药物（两味以上）的处方只有 {len(rx)} 张：请指明处方所在的列，或检查药名的写法")
        unknown = Counter(u for (_, us), _, _ in parsed for u in us)
        n = len(rx)
        transactions = [{it["key"] for it in items} for items, _, _ in rx]
        single: Counter = Counter(k for t in transactions for k in t)
        written: dict[str, Counter] = defaultdict(Counter)
        grams: dict[str, list[float]] = defaultdict(list)
        for items, _, _ in rx:
            for it in items:
                written[it["key"]][it["written"]] += 1
                if it["grams"] is not None:
                    grams[it["key"]].append(it["grams"])
        sizes = sorted(len(t) for t in transactions)
        out: dict[str, Any] = {"dataset": ds.id, "name": ds.name, "column": column, "merge": merge, "prescriptions": n, "read": len(texts),
                               "drugs_per_prescription": {"median": sizes[len(sizes) // 2], "min": sizes[0], "max": sizes[-1]},
                               "distinct_drugs": len(single)}
        freq = [{"drug": self.label(k), "prescriptions": v, "share": round(v / n, 4),
                 "written": [w for w, _ in written[k].most_common(4)]} for k, v in single.most_common(40)]
        out["frequency"] = freq[:30]
        dose_rows = []
        for k, _ in single.most_common(40):
            xs = grams.get(k) or []
            if len(xs) >= 3:
                q = tukey(xs)
                dose_rows.append({"drug": self.label(k), "n": len(xs), "median": q["median"], "q1": q["q1"], "q3": q["q3"], "min": q["min"],
                                  "max": q["max"], "values": xs})
        out["doses_g"] = [{k: v for k, v in r.items() if k != "values"} for r in dose_rows[:20]]
        support = min_support or max(3, math.ceil(0.03 * n))
        table_ = self.pairs.pair_table(transactions, min_support=support)
        for r in table_:
            r["a_name"], r["b_name"] = self.label(r["a"]), self.label(r["b"])
        significant = [r for r in table_ if r["significant"]]
        out["min_support"] = support
        out["pairs"] = [{"pair": f"{r['a_name']}—{r['b_name']}", "support": r["support"], "lift": r["lift"], "npmi": r["npmi"],
                         "or": r["or"], "or_ci": r["or_ci"], "p": r["p"]} for r in significant[:top]]
        out["pairs_significant"] = len(significant)
        rules = self.pairs._rules(table_, n)
        for r in rules:  # the raw names the lexicon lacks, as written
            r["if"], r["then"] = (x[4:] if x.startswith("raw:") else x for x in (r["if"], r["then"]))
        out["rules"] = rules[:top]
        clusters, tree = self.pairs._clusters(transactions, single, support)
        if clusters:
            tree["labels"] = [x[4:] if x.startswith("raw:") else x for x in tree["labels"]]
            out["clusters"] = [{"cluster": c["cluster"], "drugs": [d[4:] if d.startswith("raw:") else d for d in c["drugs"]]} for c in clusters]
        if unknown:
            out["unrecognised"] = [{"name": k, "count": v} for k, v in unknown.most_common(20)]
        by_group = self._by_group(rx, single) if any(g for _, _, g in rx) else None
        if by_group:
            out["groups"] = by_group
        matches = self._classics(rx) if classics else None
        if matches:
            out["classics"] = matches
        out["charts"], out["tables"] = self._figures(ds, out, dose_rows, significant, tree if clusters else None, by_group, matches)
        out["note"] = (MERGE_NOTE[merge] + "；词表未收而后接重量者按原名计，见 unrecognised。同一药在一方中写两次者计一次、剂量相加。"
                       "剂量只把以克、毫克、千克写出者计为克；两、钱、片、枚照写，不折算。经典方比较以药类计算 Jaccard 系数，只说明组成相近，"
                       "不说明疗效或来源。" + NOTE)
        return out

    def _prescriptions(self, ds: Dataset, column: str | None, group: str | None) -> tuple[list[str], list[str], list[str], str | None]:
        if ds.kind == "text":
            texts = list(ds.passages)
            return texts, [ds.part_id(i) for i in range(len(texts))], [""] * len(texts), None
        if column:
            col = ds.columns[ds.column(column)]
        else:
            found = [c for c in ds.columns if ds.types.get(c) == "prescription"]
            if not found:
                found = [c for c in ds.columns if self.looks_like([v for v in ds.values(c) if v.strip()])]
            if not found:
                raise ValueError(f"「{ds.name}」中没有找到处方列（有：{'、'.join(ds.columns)}）：请用 column 指明")
            col = found[0]
        gi = ds.column(group) if group else None
        ci = ds.column(col)
        rows = [r for r in range(len(ds.rows)) if ds.rows[r][ci].strip()]
        return ([ds.rows[r][ci] for r in rows], [ds.part_id(r) for r in rows],
                [ds.rows[r][gi] if gi is not None else "" for r in rows], col)

    def _by_group(self, rx: list[tuple[list[dict[str, Any]], str, str]], single: Counter, top: int = 15,
                  max_groups: int = 8) -> dict[str, Any] | None:
        """Which of the most used drugs are used differently across the groups: n (%) by group and a χ² (Fisher for
        two groups and a small count) per drug, Benjamini–Hochberg across the drugs."""
        sizes = Counter(g for _, _, g in rx if g)
        names = [g for g, _ in sizes.most_common(max_groups)]
        if len(names) < 2:
            return None
        drugs = [k for k, _ in single.most_common(top)]
        with_drug = {g: Counter() for g in names}
        for items, _, g in rx:
            if g in with_drug:
                with_drug[g].update({it["key"] for it in items})
        pvals, rows = {}, []
        for k in drugs:
            counts = [[with_drug[g][k], sizes[g] - with_drug[g][k]] for g in names]
            if len(names) == 2:
                (a, b), (c, d) = counts
                p = fisher_exact_two_sided(a, b, c, d)
            else:
                t = chi_square_independence(counts)
                p = t["p"] if t else 1.0
            pvals[k] = p
            rows.append({"drug": self.label(k), "key": k, **{g: with_drug[g][k] for g in names}, "p": p})
        passed = benjamini_hochberg(pvals, q=0.05)
        for r in rows:
            r["significant"] = bool(passed.get(r.pop("key")))
        return {"groups": [{"group": g, "prescriptions": sizes[g]} for g in names], "drugs": rows,
                "test": "Fisher 精确检验（两组）" if len(names) == 2 else "Pearson χ² 检验（各组 × 用与不用）",
                "correction": "Benjamini–Hochberg（q = 0.05）"}

    def _classics(self, rx: list[tuple[list[dict[str, Any]], str, str]]) -> dict[str, Any] | None:
        """Each prescription's nearest composition in the classics (Jaccard on the drug families; of formulas as near,
        the one more of whose witnesses are as near, and its earliest witness), and which formulas come nearest most often."""
        try:
            built = self.pairs.h.build(self.pairs._cache())
        except Exception:  # pragma: no cover - a corpus without compositions
            return None
        comps = built.get("compositions") or []
        if not comps:
            return None
        index: dict[str, list[int]] = defaultdict(list)
        for i, c in enumerate(comps):
            for k in c[2]:
                index[k].append(i)
        sets = [set(c[2]) for c in comps]
        year = lambda i: comps[i][3] if comps[i][3] is not None else 9999  # noqa: E731
        matches = []
        for items, pid, _ in rx[:MAX_CLASSIC_MATCHES]:
            mine = {it["family"] for it in items}
            if len(mine) < 3:
                continue
            seen: Counter = Counter(i for k in mine for i in index.get(k, ()))
            # by formula: how near its nearest witness is, how many of its witnesses are as near, the earliest of them
            near: dict[str, tuple[float, int, int]] = {}
            for i, shared in seen.items():
                j = round(shared / (len(mine) + len(sets[i]) - shared), 9)
                f = comps[i][1]
                old = near.get(f)
                if old is None or j > old[0]:
                    near[f] = (j, 1, i)
                elif j == old[0]:
                    near[f] = (j, old[1] + 1, i if year(i) < year(old[2]) else old[2])
            if not near:
                continue
            best_j, _, best = max(near.values(), key=lambda v: (v[0], v[1], -year(v[2])))
            if best is None or best_j < MIN_JACCARD or len(mine & sets[best]) < 2:
                continue
            c = comps[best]
            entry = self.s.pack.lexicon.entries.get(c[1])
            witness = self.s.passages([c[4]])[0] if c[4] else None
            matches.append({"passage_id": pid, "formula": entry.term if entry else c[1], "jaccard": round(best_j, 3),
                            "shared": [self.label(k) for k in sorted(mine & sets[best])],
                            "only_yours": [self.label(k) for k in sorted(mine - sets[best])],
                            "only_classic": [self.label(k) for k in sorted(sets[best] - mine)],
                            "witness": {"passage_id": c[4], "title": self.s.book_title(witness.book_id) if witness else "",
                                        "year": c[3], "locator": self.s.locator(witness) if witness else ""}})
        if not matches:
            return None
        by: dict[str, list[float]] = defaultdict(list)
        for m in matches:
            by[m["formula"]].append(m["jaccard"])
        nearest = sorted(({"formula": f, "prescriptions": len(js), "median_jaccard": sorted(js)[len(js) // 2]} for f, js in by.items()),
                         key=lambda x: (-x["prescriptions"], -x["median_jaccard"], x["formula"]))
        return {"compared": len(matches), "corpus_compositions": len(comps), "nearest": nearest[:20], "matches": matches,
                "note": "经典组成是从语料中写出组成的段落机读而来，个别方名与组成的对应可能有误：引用前请据 witness 回查原文。"}

    # ------------------------------------------------------------ figures and tables
    def _figures(self, ds: Dataset, out: dict[str, Any], dose_rows: list[dict[str, Any]], significant: list[dict[str, Any]],
                 tree: dict[str, Any] | None, by_group: dict[str, Any] | None,
                 matches: dict[str, Any] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        n = out["prescriptions"]
        src = source(ds)
        charts, tables = [], []
        freq = out["frequency"]
        charts.append(chart("hbar", "高频药物", [{"drug": f["drug"], "n": f["prescriptions"], "share": f["share"]} for f in freq[:20]],
                            [("drug", "药物"), ("n", "处方数"), ("share", "频率")], id="mine-rx-frequency",
                            subtitle=f"{n} 张处方中含各药者（前 20 位）", x={"key": "drug", "label": "药物"},
                            y={"label": "处方数", "min": 0}, series=[{"key": "n", "label": "处方数"}], source=src))
        tables.append(table("mine-rx-frequency", "高频药物", [("rank", "序号", "c"), ("drug", "药物", "l"), ("n", "频次（张）", "c"),
                            ("share", "频率（%）", "c"), ("written", "原写法", "l")],
                            [{"rank": i, "drug": f["drug"], "n": f["prescriptions"], "share": pct(f["share"]), "written": "、".join(f["written"])}
                             for i, f in enumerate(freq, 1)],
                            notes=[f"频率：含该药的处方占全部 {n} 张的比例；{MERGE_NOTE[out['merge']]}。", NOTE], source=src))
        if dose_rows:
            top = dose_rows[:8]
            charts.append(chart("box", "常用药物的剂量（g）", [{"drug": r["drug"], **{k: r[k] for k in ("n", "median", "q1", "q3", "min", "max")}}
                                                             for r in top],
                                [("drug", "药物"), ("n", "n"), ("median", "中位数"), ("q1", "P25"), ("q3", "P75"), ("min", "最小"), ("max", "最大")],
                                id="mine-rx-doses", subtitle="以克（g）写出的剂量；箱为四分位距，须线至 1.5 倍四分位距内的最远值",
                                x={"key": "drug", "label": "药物"}, y={"label": "剂量（g）", "min": 0},
                                points={r["drug"]: r["values"][:300] for r in top}, source=src))
            tables.append(table("mine-rx-doses", "常用药物的剂量", [("drug", "药物", "l"), ("n", "n", "c"), ("med", "M (P25, P75)（g）", "c"),
                                ("range", "范围（g）", "c")],
                                [{"drug": r["drug"], "n": r["n"], "med": med_iqr(r, 1), "range": f"{fixed(r['min'], 1)}–{fixed(r['max'], 1)}"} for r in dose_rows],
                                notes=["只计以克（g、克）、毫克、千克写出的剂量；钱、两、片、枚等未折算。", NOTE], source=src))
        if significant:
            rows = [{"pair": f"{r['a_name']}—{r['b_name']}", "n": r["support"], "lift": est(r["lift"]), "npmi": fixed(r["npmi"], 3),
                     "or": est_ci(r.get("or"), *(r.get("or_ci") or [None, None])), "p": p_value(r["p"]) + "*"} for r in significant[:30]]
            tables.append(table("mine-rx-pairs", "显著药对", [("pair", "药对", "l"), ("n", "同方（张）", "c"), ("lift", "提升度", "c"),
                                ("npmi", "NPMI", "c"), ("or", "OR (95% CI)", "c"), ("p", "P", "c")], rows,
                                notes=[f"同方至少 {out['min_support']} 次的药对；P：单侧 Fisher 精确检验，* 经 Benjamini–Hochberg 校正后 q < 0.05；"
                                       "按 NPMI（归一化点互信息）排序。", NOTE], source=src))
            forest = [{"pair": f"{r['a_name']}—{r['b_name']}", "or": r["or"], "lo": r["or_ci"][0], "hi": r["or_ci"][1], "support": r["support"]}
                      for r in significant[:15] if r.get("or") and r.get("or_ci") and r["or_ci"][1] is not None]
            if forest:
                charts.append(chart("forest", "显著药对的关联强度", forest, [("pair", "药对"), ("or", "OR"), ("lo", "95% CI 下限"), ("hi", "95% CI 上限"),
                                    ("support", "同方（张）")], id="mine-rx-forest", subtitle="比值比（OR）与 95% 置信区间（Woolf 法），对数轴",
                                    y={"key": "pair", "label": "药对"}, estimate={"key": "or", "lo": "lo", "hi": "hi", "label": "OR"},
                                    x={"label": "OR（95% CI）", "log": True, "ref": 1}, source=src))
        if out.get("rules"):
            charts.append(chart("scatter", "药物关联规则", [{"rule": f"{r['if']} → {r['then']}", "support": r["support_share"], "confidence": r["confidence"],
                                                         "lift": r["lift"]} for r in out["rules"]],
                                [("rule", "规则"), ("support", "支持度"), ("confidence", "置信度"), ("lift", "提升度")], id="mine-rx-rules",
                                subtitle="每点为一条规则（前项 → 后项）；点的大小为提升度", x={"key": "support", "label": "支持度", "percent": True, "min": 0},
                                y={"key": "confidence", "label": "置信度", "percent": True}, size={"key": "lift", "label": "提升度"}, label="rule",
                                source=src))
            tables.append(table("mine-rx-rules", "药物关联规则", [("rule", "规则（前项 → 后项）", "l"), ("support", "支持度，n (%)", "c"),
                                ("confidence", "置信度（%）", "c"), ("lift", "提升度", "c")],
                                [{"rule": f"{r['if']} → {r['then']}", "support": n_pct(r["support"], n), "confidence": pct(r["confidence"]),
                                  "lift": est(r["lift"])} for r in out["rules"]],
                                notes=["取显著药对两个方向中置信度 ≥ 50% 的规则，按置信度排序。", NOTE], source=src))
        if tree:
            names = [f"第 {c + 1} 类" for c in range(tree["k"])]
            charts.append(chart("dendrogram", "高频药物聚类树状图", [{"drug": tree["labels"][i], "cluster": names[tree["member"][i]], "n": tree["frequency"][i]}
                                                                for i in tree["order"]],
                                [("drug", "药物"), ("cluster", "类别"), ("n", "处方数")], id="mine-rx-tree",
                                subtitle=f"以 1 − Jaccard 系数为距离，平均联结法（UPGMA）；分为 {tree['k']} 类", labels=tree["labels"],
                                merges=tree["merges"], order=tree["order"], member=tree["member"], cut=tree.get("cut"), groups=names,
                                x={"label": "距离（1 − Jaccard）"}, source=src))
        if by_group:
            gnames = [g["group"] for g in by_group["groups"]]
            sizes = {g["group"]: g["prescriptions"] for g in by_group["groups"]}
            cells = [{"drug": r["drug"], "group": g, "share": round(r[g] / sizes[g], 4) if sizes[g] else 0} for r in by_group["drugs"] for g in gnames]
            charts.append(chart("heatmap", "各组的用药", cells, [("drug", "药物"), ("group", "组"), ("share", "用药率")], id="mine-rx-groups",
                                subtitle="每格为该组处方中含此药的比例", x={"key": "group", "label": "组", "order": gnames},
                                y={"key": "drug", "label": "药物", "order": [r["drug"] for r in by_group["drugs"]]},
                                value={"key": "share", "label": "用药率", "percent": True, "max": 1}, source=src))
            keys = [f"g{i}" for i in range(len(gnames))]
            tables.append(table("mine-rx-groups", "各组的用药比较", [("drug", "药物", "l")] + [(k, f"{g}（{sizes[g]}）", "c", "用药，n (%)")
                                                                                  for k, g in zip(keys, gnames)] + [("p", "P", "c")],
                                [{"drug": r["drug"], **{k: n_pct(r[g], sizes[g]) for k, g in zip(keys, gnames)}, "p": p_value(r["p"]) + ("*" if r["significant"] else "")}
                                 for r in by_group["drugs"]],
                                notes=[f"{by_group['test']}，{by_group['correction']}；* 校正后显著。括号内为该组处方数。", NOTE], source=src))
        if matches:
            charts.append(chart("hbar", "最相近的经典方", [{"formula": x["formula"], "n": x["prescriptions"], "jaccard": x["median_jaccard"]}
                                                       for x in matches["nearest"][:15]],
                                [("formula", "经典方"), ("n", "处方数"), ("jaccard", "Jaccard 中位数")], id="mine-rx-classics",
                                subtitle=f"{matches['compared']} 张处方各自最相近的经典组成（药类 Jaccard 系数 ≥ {MIN_JACCARD}）", x={"key": "formula", "label": "经典方"},
                                y={"label": "处方数", "min": 0}, series=[{"key": "n", "label": "处方数"}], source=src))
            tables.append(table("mine-rx-classics", "处方与最相近的经典组成", [("row", "处方", "l"), ("formula", "最相近的经典方", "l"),
                                ("j", "Jaccard", "c"), ("shared", "共有", "l"), ("only", "仅本方", "l"), ("witness", "见于", "l")],
                                [{"row": m["passage_id"], "formula": m["formula"], "j": fixed(m["jaccard"], 2), "shared": "、".join(m["shared"]),
                                  "only": "、".join(m["only_yours"]) or "—",
                                  "witness": f"《{m['witness']['title']}》（{int(m['witness']['year']) if m['witness']['year'] is not None else '?'}）"}
                                 for m in matches["matches"][:100]],
                                notes=["Jaccard：两方共有药类数 ÷ 药类并集数；经典组成取语料中写出组成者，同样相近时取同样相近的见证较多之方及其最早的见证；"
                                       "组成为机读，须回查原文。相近只说明组成相似。", NOTE],
                                source=src))
        return charts, tables


__all__ = ["PrescriptionReader"]
