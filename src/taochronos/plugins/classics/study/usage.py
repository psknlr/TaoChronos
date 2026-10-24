"""用药谱与药性谱 — how a drug was prescribed through the centuries, and what the 本草 said of several drugs at once.

* ``usage`` — over every composition the corpus writes out (the harvest of ``study pairs``, one per work): the share of
  compositions holding the drug, period by period, with 95 % Wilson intervals and a Cochran–Armitage test for a trend;
  its doses as written, read in 两 and grams of the witness's own period (median and quartiles; a historical reading,
  never dosage guidance); how often it is the formula's largest dose (a clue the literature reads as the 君药, not a
  judgement of 君臣佐使); its preparation notes (炙, 炮, 去皮 …) by period; the drugs it is written with (count and lift);
  the formulas it is written in; the earliest compositions.
* ``properties`` — 药性谱: for several drugs, or the drugs of a formula's 原方, what the 本草 entries say (``study
  herb``): flavours, natures, toxicity and channels, each with the share of the works that state it and the first work
  to state it; channels read by the usual correspondence of the twelve channels and the organs (手太阴 → 肺 …); for a
  formula, its profile weighted by the dose of each drug.

Counts are of the writing, not of practice: a formula copied in many works counts once per work, and what was not written
down is not counted.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from ....science.stats import kruskal_wallis, spearman
from .base import StudyBase, dated, trend_test, wilson

# the twelve channels as the organs the 本草 name (the usual correspondence), and the names of the 心包
CHANNEL_ORGAN = {"手太阴": "肺", "足太阴": "脾", "手少阴": "心", "足少阴": "肾", "手厥阴": "心包", "足厥阴": "肝", "手太阳": "小肠",
                 "足太阳": "膀胱", "手阳明": "大肠", "足阳明": "胃", "手少阳": "三焦", "足少阳": "胆", "心包络": "心包", "包络": "心包"}
ORGAN_ORDER = ["肺", "大肠", "胃", "脾", "心", "小肠", "膀胱", "肾", "心包", "三焦", "胆", "肝", "命门"]
NATURE_ORDER = ["寒", "凉", "平", "温", "热"]
FLAVOR_ORDER = list("酸苦甘辛咸淡涩")
MAX_DRUGS = 16
MAX_POINTS = 1500  # the doses a figure draws one by one (an even sample of them beyond; the statistics use every dose)
# the form a formula's name gives (汤剂, 丸剂 …): a decoction's doses are what is boiled for a course; a pill's, powder's or
# paste's are the batch it is made in — the two are not compared
FORMS = (("汤剂", ("汤", "饮", "煎", "饮子")), ("丸剂", ("丸", "圆", "丹")), ("散剂", ("散",)), ("煮散", ()), ("膏剂", ("膏",)))
# what the preparation written after the drugs makes of them — it overrides the name: 宋 方书 write many a 汤 as a powder
# boiled by the spoonful (右为粗末，每服三钱，水一盏，煎至七分: a 煮散), whose amounts are a batch, as a pill's are
_PILL = re.compile(r"(?:[为和作]|蜜|糊)[丸圆]|[丸圆]，?如")
_POWDER = re.compile(r"[为捣杵研][^，。；]{0,4}[末散]")
_BOILED = re.compile(r"[煎煮]")
_DECOCTION = re.compile(r"以水[^，。；]{0,8}[升斗]|水[一二三四五六七八九十]+[升斗]|煮取|水煎")


def dosage_form(name: str) -> str:
    """汤剂 / 丸剂 / 散剂 / 膏剂 / 其他, from the formula's name."""
    for form, ends in FORMS:
        if ends and name.endswith(ends):
            return form
    return "其他"


def prepared_form(text: str) -> str:
    """丸剂 / 煮散 / 散剂 / 汤剂, from the preparation written after the drugs (its first 80 characters); "" when it
    says none of them."""
    t = text[:80]
    if _PILL.search(t):
        return "丸剂"
    if _POWDER.search(t):
        return "煮散" if _BOILED.search(t[_POWDER.search(t).end():]) else "散剂"
    return "汤剂" if _DECOCTION.search(t) else ""


def base_nature(nature: str) -> str:
    """大寒/微寒/寒 → 寒 …: the five natures (寒 凉 平 温 热)."""
    for n in NATURE_ORDER:
        if n in nature:
            return n
    return ""


def _quantiles(values: list[float]) -> dict[str, float]:
    v = sorted(values)

    def q(p: float) -> float:
        k = (len(v) - 1) * p
        lo, hi = int(k), min(int(k) + 1, len(v) - 1)
        return v[lo] + (v[hi] - v[lo]) * (k - lo)

    return {"min": round(v[0], 3), "q1": round(q(0.25), 3), "median": round(q(0.5), 3), "q3": round(q(0.75), 3), "max": round(v[-1], 3)}


def _describe(values: list[float]) -> dict[str, float]:
    """Quartiles, mean and standard deviation (n − 1)."""
    out = _quantiles(values)
    n = len(values)
    mean = sum(values) / n
    out["mean"] = round(mean, 3)
    out["sd"] = round((sum((x - mean) ** 2 for x in values) / (n - 1)) ** 0.5, 3) if n > 1 else 0.0
    return out


def even_sample(rows: list[Any], k: int) -> list[Any]:
    """At most ``k`` of ``rows``, evenly spaced (the first and last kept): a figure's sample that is the same every run."""
    if len(rows) <= k:
        return list(rows)
    step = (len(rows) - 1) / (k - 1)
    return [rows[round(i * step)] for i in range(k)]


class DrugUsage:
    def __init__(self, base: StudyBase, formulas: Any, herbs: Any, pairs: Any) -> None:
        self.b = base
        self.formulas = formulas
        self.herbs = herbs
        self.pairs = pairs

    # ------------------------------------------------------------ usage (用药谱)
    def usage(self, name: str, *, top: int = 20) -> dict[str, Any]:
        key = self.pairs._key_of(name)
        if key is None:
            raise self.b.not_taken(name, ("herb",), "is not a drug of the lexicon")
        built = self.pairs.h.build(self.pairs._cache())
        comps = built["compositions"]
        mine = [c for c in comps if key in c[2]]
        order = [p.label for p in self.b.periods] + ["未定"]
        totals: Counter = Counter(self.pairs._period(c[3]) for c in comps)
        hits: Counter = Counter(self.pairs._period(c[3]) for c in mine)
        by_period = []
        for per in order:
            n, k = totals[per], hits[per]
            if not n:
                continue
            lo, hi = wilson(k, n)
            by_period.append({"period": per, "compositions": n, "with": k, "share": round(k / n, 4),
                              "ci": [round(lo, 4), round(hi, 4)]})
        trend = trend_test([(r["with"], r["compositions"]) for r in by_period if r["period"] != "未定"])
        doses, largest, processing = self._doses(mine, key)
        raw = {"grams": doses.pop("_values"), "points": doses.pop("_points")}
        partners = self._partners(comps, mine, key, top)
        formulas = Counter(c[1] for c in mine if c[1])
        work_of: dict[str, set[str]] = defaultdict(set)
        for c in mine:
            if c[1]:
                work_of[c[1]].add(c[0])
        first = sorted(mine, key=lambda c: (dated([c[3], c[3]] if c[3] is not None else None), c[4]))[:5]
        return {
            "drug": {"name": name, "key": key, "label": self.pairs._label(key)},
            "compositions": len(comps), "with": len(mine), "share": round(len(mine) / len(comps), 4) if comps else 0.0,
            "works": len({c[0] for c in mine}), "by_period": by_period,
            "trend": {"z": trend[0], "p": trend[1]} if trend else None,
            "doses": doses, "largest_dose": largest, "processing": processing, "partners": partners,
            "formulas": [{"formula": self.pairs._label(f), "compositions": k, "works": len(work_of[f])}
                         for f, k in formulas.most_common(top)],
            "examples": [self._example(c) for c in first],
            "metrology_notice": self.formulas.metrology.notice,
            "_raw": raw,  # what the figures draw dose by dose: taken out with the charts (charts.attach), never read by a model
            "note": "per work: a composition repeated in the copies of one work counts once; doses are read in the measures "
                    "of each witness's period (weights only), by period for the decoctions (汤剂) — a pill's or powder's amount "
                    "is its batch, as is a 煮散's (a 汤 the preparation makes a powder boiled by the spoonful), summarised by "
                    "form; 'largest dose' is a clue the literature reads as the 君药, not a judgement of 君臣佐使",
        }

    def _doses(self, mine: list[list[Any]], key: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        """Doses by period — of the decoctions (汤剂) only: a pill's or powder's dose is its batch — and a summary per form;
        how often the drug is the largest dose (a ratio, the same in any form); its preparation notes."""
        met = self.formulas.metrology
        liang: dict[str, list[float]] = defaultdict(list)
        grams: dict[str, list[float]] = defaultdict(list)
        points: list[list[Any]] = []  # [year, grams, formula] of each dated decoction
        written: dict[str, Counter] = defaultdict(Counter)
        by_form: dict[str, list[float]] = defaultdict(list)
        largest: Counter = Counter()
        weighed: Counter = Counter()
        notes: dict[str, Counter] = defaultdict(Counter)
        for c in mine:
            items = c[6] if len(c) > 6 else []
            per = self.pairs._period(c[3])
            form = (c[7] if len(c) > 7 and c[7] else "") or (dosage_form(self.pairs._label(c[1])) if c[1] else "其他")
            weights: dict[str, float] = {}
            for k, _term, dose, proc in items:
                w = met.in_liang(dose, c[3]) if dose else None
                if w:
                    weights[k] = weights.get(k, 0.0) + w
                if k != key:
                    continue
                if dose and form == "汤剂":
                    written[per][dose] += 1
                for note in filter(None, (x.strip() for x in (proc or "").replace("；", "，").split("，"))):
                    notes[per][note] += 1
            if key in weights:
                by_form[form].append(weights[key])
                if form == "汤剂":
                    liang[per].append(weights[key])
                    measures = met.period(c[3])
                    if measures and measures.get("liang_g"):  # the middle of the period's 两 in grams
                        g = weights[key] * sum(measures["liang_g"]) / 2
                        grams[per].append(g)
                        if c[3] is not None:
                            points.append([c[3], round(g, 2), self.pairs._label(c[1]) if c[1] else ""])
                if len(weights) >= 2:
                    weighed[per] += 1
                    largest[per] += weights[key] >= max(weights.values()) - 1e-9
        order = [p.label for p in self.b.periods] + ["未定"]
        dose_rows = []
        for per in order:
            if not liang[per]:
                continue
            row = {"period": per, "n": len(liang[per]), "liang": _quantiles(liang[per]),
                   "common": [{"dose": d, "count": k} for d, k in written[per].most_common(3)]}
            if grams[per]:
                row["grams"] = _describe(grams[per])
            dose_rows.append(row)
        all_written: Counter = sum(written.values(), Counter())
        tested = [grams[p] for p in order if p != "未定" and len(grams[p]) >= 3]
        kw = kruskal_wallis(tested) if len(tested) >= 2 else None
        dated_points = sorted(points, key=lambda x: x[0])
        rho = spearman([x[0] for x in dated_points], [x[1] for x in dated_points]) if len(dated_points) >= 10 else None
        doses = {"form": "汤剂", "by_period": dose_rows, "weighed": sum(len(v) for v in liang.values()),
                 "test": {"name": "Kruskal–Wallis", "unit": "克", "groups": len(tested), **kw} if kw else None,
                 "trend": {"name": "Spearman", "of": "年代与克数", **rho} if rho else None,
                 "_values": {p: sorted(round(x, 2) for x in grams[p]) for p in order if grams[p]},
                 "_points": even_sample(dated_points, MAX_POINTS),
                 "common": [{"dose": d, "count": k} for d, k in all_written.most_common(8)],
                 "by_form": [{"form": f, "n": len(v), "liang": _quantiles(v)} for f, v in
                             sorted(by_form.items(), key=lambda kv: [x for x, _ in FORMS].index(kv[0]) if kv[0] in dict(FORMS) else 9)]}
        n_w, n_l = sum(weighed.values()), sum(largest.values())
        largest_out = {"share": round(n_l / n_w, 4) if n_w else None, "compositions": n_w,
                       "by_period": [{"period": p, "compositions": weighed[p], "largest": largest[p],
                                      "share": round(largest[p] / weighed[p], 4)} for p in order if weighed[p]]}
        all_notes: Counter = sum(notes.values(), Counter())
        top_notes = [n for n, _ in all_notes.most_common(6)]
        processing = {"top": [{"note": n, "count": k} for n, k in all_notes.most_common(12)],
                      "by_period": [{"period": p, **{n: notes[p][n] for n in top_notes},
                                     "其他": sum(v for n, v in notes[p].items() if n not in top_notes)}
                                    for p in order if notes[p]], "notes": top_notes}
        return doses, largest_out, processing

    def _partners(self, comps: list[list[Any]], mine: list[list[Any]], key: str, top: int) -> list[dict[str, Any]]:
        n = len(comps)
        single: Counter = Counter(k for c in comps for k in c[2])
        joint: Counter = Counter(k for c in mine for k in c[2] if k != key)
        out = []
        for other, k in joint.most_common(top):
            lift = k * n / (len(mine) * single[other]) if mine and single[other] else None
            out.append({"with": self.pairs._label(other), "key": other, "compositions": k,
                        "share": round(k / len(mine), 4), "lift": round(lift, 3) if lift else None})
        return out

    def _example(self, c: list[Any]) -> dict[str, Any]:
        ps = self.b.passages([c[4]])
        label = self.pairs._label(c[1]) if c[1] else ""
        if not ps:
            return {"passage_id": c[4], "formula": label}
        p = ps[0]
        norm = self.b.normalize(p.text)
        at = norm.find(self.b.normalize(label)) if label else -1
        w = self.b.witness(p, start=at, end=min(len(p.text), at + len(label) + 80), width=0) if at >= 0 else self.b.witness(p, width=60)
        return {**w, "formula": label}

    # ------------------------------------------------------------ properties (药性谱)
    def properties(self, drugs: list[str] | None = None, *, formula: str | None = None) -> dict[str, Any]:
        weights: dict[str, float] = {}
        source = None
        names = [d.strip() for d in (drugs or []) if d and d.strip()]
        if formula:
            res = self.formulas.run(formula, other_names=False)
            group = next((g for g in res.get("groups", []) if "原方" in (g.get("relation") or "")), None)
            w = next((x for x in res.get("witnesses", []) if group and x["passage_id"] == group["earliest"]["passage_id"]), None)
            if w is None:
                raise ValueError(f"{formula!r}: no written-out composition of this formula was found")
            source = {k: w.get(k) for k in ("passage_id", "title", "years", "locator", "quote")}
            year = (w["years"][0] + w["years"][1]) / 2 if w.get("years") else None
            for i in w.get("ingredients", []):
                names.append(i["term"])
                lw = self.formulas.metrology.in_liang(i.get("dose"), year)
                if lw:
                    weights[i["term"]] = weights.get(i["term"], 0.0) + lw
        names = list(dict.fromkeys(names))[:MAX_DRUGS]
        if not names:
            raise ValueError("give drugs, or a formula whose drugs to read")
        rows = [self._profile(n) for n in names]
        out: dict[str, Any] = {"drugs": rows, "formula": formula, "composition": source,
                               "channels": [o for o in ORGAN_ORDER if any(o in r["channels"] for r in rows)],
                               "note": "shares are of the works whose 本草 entry for the drug states anything of the kind; channels "
                                       "read by the usual correspondence (手太阴 → 肺 …); an entry is the text's, not a verdict"}
        if formula:
            out["profile"] = self._formula_profile(rows, weights)
        return out

    def _profile(self, name: str) -> dict[str, Any]:
        r = self.herbs.run(name)
        entries = r.get("entries", [])
        natures: Counter = Counter()
        detail: Counter = Counter()
        flavors: Counter = Counter()
        toxicity: Counter = Counter()
        channels: Counter = Counter()
        for e in entries:
            if e["nature"]:
                natures[base_nature(e["nature"])] += 1
                detail[e["nature"]] += 1
            for ch in dict.fromkeys(e["flavor"]):
                flavors[ch] += 1
            if e["toxicity"]:
                toxicity[e["toxicity"]] += 1
            for organ in dict.fromkeys(CHANNEL_ORGAN.get(c, c) for c in e["channels"]):
                channels[organ] += 1

        def shares(counter: Counter, order: list[str] | None = None) -> dict[str, float]:
            total = len(entries) or 1
            keys = [k for k in (order or []) if counter[k]] + [k for k in counter if not order or k not in order]
            return {k: round(counter[k] / total, 3) for k in keys}

        firsts = {(f["field"], f["value"]): f for f in r.get("firsts", [])}
        first = {field: next(({"value": f["value"], "locator": f["locator"], "years": f["years"], "passage_id": f["passage_id"]}
                              for (fd, _), f in firsts.items() if fd == field), None) for field in ("性味", "药性", "毒性", "归经")}
        return {"drug": name, "works": len(entries), "natures": shares(natures, NATURE_ORDER), "nature_detail": dict(detail.most_common()),
                "flavors": shares(flavors, FLAVOR_ORDER), "toxicity": shares(toxicity), "channels": shares(channels, ORGAN_ORDER),
                "consensus": {"nature": natures.most_common(1)[0][0] if natures else "",
                              "flavors": [k for k, _ in flavors.most_common(2)],
                              "channels": [k for k, v in channels.most_common() if v >= max(1, len(entries) / 3)][:4]},
                "first": first}

    @staticmethod
    def _formula_profile(rows: list[dict[str, Any]], weights: dict[str, float]) -> dict[str, Any]:
        """The formula's natures, flavours and channels: each drug's shares weighted by its share of the weight (equal
        weights when the doses are not all weights)."""
        known = {r["drug"]: weights.get(r["drug"]) for r in rows if r["works"]}
        use_dose = bool(known) and all(v for v in known.values())
        total = sum(known.values()) if use_dose else float(len(known) or 1)
        out: dict[str, dict[str, float]] = {"natures": defaultdict(float), "flavors": defaultdict(float), "channels": defaultdict(float)}
        for r in rows:
            if not r["works"]:
                continue
            w = (known[r["drug"]] if use_dose else 1.0) / total
            for kind in out:
                for k, v in r[kind].items():
                    out[kind][k] += w * v
        return {"weighted_by": "dose" if use_dose else "equal", "drugs": len(known),
                **{kind: {k: round(v, 3) for k, v in sorted(vals.items(), key=lambda kv: -kv[1])} for kind, vals in out.items()}}


__all__ = ["CHANNEL_ORGAN", "DrugUsage", "FORMS", "MAX_DRUGS", "base_nature", "dosage_form"]
