"""方剂比较与类方 — formulas side by side, and the formulas built on one.

* ``compare`` — two to six formulas, each as its earliest tradition (原方) or its most witnessed (通行方) writes it out:
  the drugs side by side with the doses as written, each dose in 两 of the witness's own period and as a ratio (the
  largest = 1, so that the measures of the period do not matter), and for every two formulas the drugs they share and do
  not, the Jaccard similarity of the drug sets, a dose-weighted overlap (Σ of the smaller share of the total weight) and a
  verdict: **同方** (the same drugs, the doses within a tenth), **同药异量** (the same drugs, other doses: 桂枝汤 /
  桂枝加桂汤 / 桂枝加芍药汤; 小承气汤 / 厚朴三物汤 / 厚朴大黄汤), **加减化裁** (Jaccard ≥ 0.5) or **异方**.
* ``family`` — 类方: among every composition the corpus writes out (the harvest of ``study pairs``), the formulas whose
  drugs hold most of one formula's core (its most common drug set): what each adds and leaves out (加味, 减味, 加减, 同药),
  how many works write it, its earliest witness, and — when the drugs it adds are another known formula's core — the
  formula it combines with (合方: 柴胡桂枝汤 = 小柴胡汤 + 桂枝汤).  Same drugs under another name are told apart by their
  doses: 同药异量 when the ratios differ, 同方异名 when they agree.

Doses are read in the measures of their witness's own date — a historical reading for comparing the texts, never dosage
guidance.  Drugs are compared by family (``drug_families.yaml``: 桂枝/桂心/肉桂 → 桂), as ``study formula`` does.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations
from typing import Any

from .base import StudyBase, dated
from .formulas import jaccard

SAME_DOSE = 0.1  # two doses of a drug are "the same" when they differ by at most a tenth
MAX_FORMULAS = 6


def _when(row: list[Any]) -> tuple[float, float]:
    """A harvested composition's date as the "earliest" sort key (its year, else last)."""
    return dated([row[3], row[3]] if row[3] is not None else None)


class FormulaComparison:
    def __init__(self, base: StudyBase, formulas: Any, pairs: Any) -> None:
        self.b = base
        self.formulas = formulas
        self.pairs = pairs

    # ------------------------------------------------------------ helpers
    def _label(self, key: str) -> str:
        return self.pairs._label(key)

    def _amount(self, dose: str, year: float | None) -> dict[str, Any]:
        """A dose as a comparable amount: weight in 两 of its period, or a count or volume in its own unit."""
        met = self.formulas.metrology
        liang = met.in_liang(dose, year)
        if liang is not None:
            return {"liang": liang}
        parts = [p for p in met.parse(dose) if p.get("value") is not None and p["kind"] in ("count", "volume")]
        if parts:
            return {"value": parts[0]["value"], "unit": parts[0]["unit"]}
        return {}

    @staticmethod
    def _mid(years: Any) -> float | None:
        return (years[0] + years[1]) / 2 if years else None

    # ------------------------------------------------------------ compare
    def compare(self, names: list[str], *, which: str = "original") -> dict[str, Any]:
        names = [n.strip() for n in names if n and n.strip()]
        names = list(dict.fromkeys(names))[:MAX_FORMULAS]
        if len(names) < 2:
            raise ValueError("give two to six formulas to compare")
        formulas = [self._one(n, which) for n in names]
        found = [f for f in formulas if f["found"]]
        order: list[str] = []
        for f in found:
            order += [d["key"] for d in f["drugs"] if d["key"] not in order]
        matrix = []
        for key in order:
            row: dict[str, Any] = {"drug": self._label(key), "key": key}
            for f in found:
                d = next((x for x in f["drugs"] if x["key"] == key), None)
                row[f["name"]] = {"dose": d["dose"], "ratio": d["ratio"], "share": d["share"]} if d else None
            matrix.append(row)
        pairs = [self._pair(a, b) for a, b in combinations(found, 2)]
        return {"formulas": formulas, "which": which, "drugs": [self._label(k) for k in order], "matrix": matrix, "pairs": pairs,
                "summary": {"formulas": len(formulas), "found": len(found), "drugs": len(order),
                            "same_drugs_other_doses": [f"{p['a']}—{p['b']}" for p in pairs if p["verdict"] == "同药异量"]},
                "metrology_notice": self.formulas.metrology.notice,
                "note": "each formula as one witness writes it (原方: its earliest tradition; 通行方: the most witnessed); "
                        "ratios take the largest weight in the formula as 1; counts (枚) and volumes are compared only with "
                        "the same unit; drugs are compared by family"}

    def _one(self, name: str, which: str) -> dict[str, Any]:
        res = self.formulas.run(name, other_names=False)
        groups = [g for g in res.get("groups", []) if g.get("witnesses")]
        want = "通行方" if which == "current" else "原方"
        group = next((g for g in groups if want in (g.get("relation") or "")), groups[0] if groups else None)
        out: dict[str, Any] = {"name": name, "found": False, "mentions": res.get("mentions", 0),
                               "compositions": res.get("summary", {}).get("compositions", 0)}
        if group is None:
            return out
        pid = group["earliest"]["passage_id"]
        w = next((x for x in res["witnesses"] if x["passage_id"] == pid), None)
        if w is None:
            return out
        year = self._mid(w.get("years"))
        drugs: list[dict[str, Any]] = []
        for i in w.get("ingredients", []):
            key = i.get("family") or i["term_id"]
            if any(d["key"] == key for d in drugs):
                continue
            drugs.append({"drug": self._label(key), "key": key, "surface": i["surface"], "dose": i.get("dose") or "",
                          "processing": i.get("processing") or "", "reading": i.get("reading") or "",
                          **self._amount(i.get("dose") or "", year)})
        weights = [d["liang"] for d in drugs if d.get("liang")]
        top, total = (max(weights), sum(weights)) if weights else (0.0, 0.0)
        for d in drugs:
            d["ratio"] = round(d["liang"] / top, 3) if d.get("liang") and top else None
            d["share"] = round(d["liang"] / total, 4) if d.get("liang") and total else None
        keep = ("passage_id", "book_id", "title", "work", "dynasty", "years", "period", "locator", "quote", "source", "license")
        out.update(found=True, relation=group.get("relation"), witnesses=group.get("witnesses"),
                   witness={k: w.get(k) for k in keep}, preparation=w.get("preparation") or "", indication=w.get("indication") or "",
                   drugs=drugs, weighed=len(weights))
        return out

    def _pair(self, a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
        ka = [d["key"] for d in a["drugs"]]
        kb = [d["key"] for d in b["drugs"]]
        sa, sb = set(ka), set(kb)
        da = {d["key"]: d for d in a["drugs"]}
        db = {d["key"]: d for d in b["drugs"]}
        changes = []
        for key in [k for k in ka if k in sb]:
            x, y = da[key], db[key]
            fold = None
            if x.get("liang") and y.get("liang"):
                fold = y["liang"] / x["liang"]
            elif x.get("unit") and x.get("unit") == y.get("unit") and x.get("value") and y.get("value"):
                fold = y["value"] / x["value"]
            if fold is not None and abs(fold - 1) > SAME_DOSE:
                changes.append({"drug": self._label(key), "a": x["dose"], "b": y["dose"], "fold": round(fold, 3)})
        comparable = sum(1 for k in sa & sb if (da[k].get("liang") and db[k].get("liang"))
                         or (da[k].get("unit") and da[k].get("unit") == db[k].get("unit")))
        weighted = None
        if a.get("weighed", 0) >= 2 and b.get("weighed", 0) >= 2:
            weighted = round(sum(min(da[k]["share"] or 0, db[k]["share"] or 0) for k in sa & sb), 4)
        same = sa == sb
        if same and changes:
            verdict = "同药异量"
        elif same:
            verdict = "同方" if comparable else "药味相同（剂量未能比较）"
        elif jaccard(sa, sb) >= 0.5:
            verdict = "加减化裁"
        else:
            verdict = "异方"
        return {"a": a["name"], "b": b["name"], "shared": [self._label(k) for k in ka if k in sb],
                "only_a": [self._label(k) for k in ka if k not in sb], "only_b": [self._label(k) for k in kb if k not in sa],
                "jaccard": round(jaccard(sa, sb), 3), "weighted_overlap": weighted, "same_drugs": same,
                "dose_changes": changes, "doses_compared": comparable, "verdict": verdict}

    # ------------------------------------------------------------ family (类方)
    def family(self, name: str, *, min_share: float = 0.75, max_extra: int = 4, top: int = 40) -> dict[str, Any]:
        lex = self.b.pack.lexicon
        entry = lex.resolve(name, "formula") or lex.resolve(self.b.normalize(name), "formula")
        built = self.pairs.h.build(self.pairs._cache())
        comps = built["compositions"]
        fid = entry.term_id if entry else None
        own = [c for c in comps if fid and c[1] == fid]
        if own:  # the drug set most works write, the earlier on a tie
            sets = Counter(tuple(c[2]) for c in own)
            first = {s: min(_when(c) for c in own if tuple(c[2]) == s) for s in sets}
            core = set(min(sets, key=lambda s: (-sets[s], first[s], s)))
        else:  # not in the harvest: the main group of 方源考
            res = self.formulas.run(name, other_names=False)
            group = next((g for g in res.get("groups", []) if "原方" in (g.get("relation") or "")), None)
            core = set(group["core"]) if group else set()
        if len(core) < 2:
            raise ValueError(f"{name!r}: no written-out composition of this formula was found")
        base_doses = self._typical_doses([c for c in own if set(c[2]) == core])
        cores = self._cores(comps)
        by_member: dict[str, list[list[Any]]] = defaultdict(list)
        for c in comps:
            if c[1] == fid or not c[1]:
                continue
            herbs = set(c[2])
            shared = herbs & core
            if len(shared) < max(2, round(min_share * len(core) + 1e-9)) or len(herbs - core) > max_extra:
                continue
            if len(core) <= 3 and herbs - core and core - herbs:
                continue  # a small core: only additions or omissions, not both
            by_member[c[1]].append(c)
        members = []
        for mid, rows in by_member.items():
            sig = Counter((tuple(sorted(set(r[2]) - core)), tuple(sorted(core - set(r[2])))) for r in rows)
            (added, removed), _ = sig.most_common(1)[0]
            rows_sig = [r for r in rows if (tuple(sorted(set(r[2]) - core)), tuple(sorted(core - set(r[2])))) == (added, removed)]
            relation = "加减" if added and removed else "加味" if added else "减味" if removed else "同药"
            doses = None
            if relation == "同药":
                doses = self._dose_verdict(base_doses, self._typical_doses(rows_sig))
                relation = {"同药异量": "同药异量", "同方异名": "同方异名"}.get(doses or "", "同药")
            first = min(rows, key=lambda r: (_when(r), r[4]))
            herbs = set(rows_sig[0][2])
            members.append({
                "formula": self._label(mid), "term_id": mid, "relation": relation, "added": [self._label(k) for k in added],
                "removed": [self._label(k) for k in removed], "works": len({r[0] for r in rows}), "compositions": len(rows),
                "containment": round(len(herbs & core) / len(core), 3), "jaccard": round(jaccard(herbs, core), 3),
                "combines": self._combines(herbs, core, cores, exclude={fid, mid}), "year": first[3], "_pid": first[4]})
        members.sort(key=lambda m: (-m["works"], dated([m["year"], m["year"]] if m["year"] is not None else None), m["formula"]))
        members = members[:top]
        self._witnesses(members, name)
        by_relation = Counter(m["relation"] for m in members)
        periods: Counter = Counter(self.pairs._period(m["year"]) for m in members)
        order = [p.label for p in self.b.periods] + ["未定"]
        first_own = min(own, key=lambda r: (_when(r), r[4])) if own else None
        return {
            "formula": {"name": entry.term if entry else name, "term_id": fid, "core": [self._label(k) for k in sorted(core)],
                        "core_keys": sorted(core), "compositions": len(own), "works": len({c[0] for c in own}),
                        "earliest": self._witness_of(first_own[4], name) if first_own else None},
            "members": members, "by_relation": dict(by_relation.most_common()),
            "by_period": [{"period": p, "members": periods[p]} for p in order if periods[p]],
            "params": {"min_share": min_share, "max_extra": max_extra},
            "note": "formulas whose written-out compositions hold at least the given share of the core and add at most "
                    f"{max_extra} drugs (per work); 同药异量 / 同方异名 compare the doses where both are written in weights; "
                    "合方 names a formula whose core the drugs also hold",
            "metrology_notice": self.formulas.metrology.notice,
        }

    def _cores(self, comps: list[list[Any]]) -> dict[str, set[str]]:
        """Each formula's most common drug set, for formulas written out in at least two works."""
        sets: dict[str, Counter] = defaultdict(Counter)
        works: dict[str, set[str]] = defaultdict(set)
        for c in comps:
            if c[1]:
                sets[c[1]][tuple(c[2])] += 1
                works[c[1]].add(c[0])
        return {f: set(s.most_common(1)[0][0]) for f, s in sets.items() if len(works[f]) >= 2}

    def _combines(self, herbs: set[str], core: set[str], cores: dict[str, set[str]], *, exclude: set[Any]) -> str | None:
        """合方: another formula whose core (three drugs at least, two of them beyond the base's core) the drugs hold."""
        best, size = None, 0
        for f, other in cores.items():
            if f in exclude or len(other) < 3 or not other <= herbs or len(other - core) < 2:
                continue
            if len(other) > size:
                best, size = f, len(other)
        return self._label(best) if best else None

    def _typical_doses(self, rows: list[list[Any]]) -> dict[str, float]:
        """The median share of the total weight of each drug, over compositions written in weights."""
        shares: dict[str, list[float]] = defaultdict(list)
        for r in rows:
            items = r[6] if len(r) > 6 else []
            weights: dict[str, float] = {}
            for key, _term, dose, _proc in items:
                w = self.formulas.metrology.in_liang(dose, r[3])
                if w:
                    weights[key] = weights.get(key, 0.0) + w
            total = sum(weights.values())
            if len(weights) >= 2 and total:
                for key, w in weights.items():
                    shares[key].append(w / total)
        return {k: sorted(v)[len(v) // 2] for k, v in shares.items()}

    @staticmethod
    def _dose_verdict(a: dict[str, float], b: dict[str, float]) -> str | None:
        keys = set(a) & set(b)
        if len(keys) < 2:
            return None
        differ = any(abs(b[k] - a[k]) > SAME_DOSE * max(a[k], b[k]) and abs(b[k] - a[k]) > 0.03 for k in keys)
        return "同药异量" if differ else "同方异名"

    def _witness_of(self, pid: str, name: str) -> dict[str, Any] | None:
        ps = self.b.passages([pid])
        if not ps:
            return None
        p = ps[0]
        norm = self.b.normalize(p.text)
        at = norm.find(self.b.normalize(name))
        if at < 0:
            return self.b.witness(p, width=60)
        return self.b.witness(p, start=at, end=min(len(p.text), at + len(name) + 80), width=0)

    def _witnesses(self, members: list[dict[str, Any]], base_name: str) -> None:
        for m in members:
            pid = m.pop("_pid")
            m["earliest"] = self._witness_of(pid, m["formula"]) or {"passage_id": pid}


__all__ = ["FormulaComparison", "MAX_FORMULAS", "SAME_DOSE"]
