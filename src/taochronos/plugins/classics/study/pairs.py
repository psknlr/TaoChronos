"""方证网络与配伍 — which drugs go together, and which formulas answer which findings, across the literature.

One pass over the store (cached) reads

* **compositions** — every written-out composition after a formula's name (the parser of ``study formula``: drugs
  with their doses, drug families such as 桂枝/桂心/肉桂 → 桂), and those that open a passage headed by a formula;
* **indications** — every treatment sentence (…主之, 宜…汤, 与…汤): the formula and the findings, pulses, patterns
  and diseases named before it in the sentence;

the same composition or indication in several transcriptions of a work counts once.  From them

* ``study pairs`` — 配伍: for each pair of drugs, how often they are prescribed together against chance: support,
  confidence both ways, lift, pointwise mutual information (and its normalised form, by which pairs are ranked, so
  that drugs named a handful of times do not come first), the odds ratio with its 95 % interval and a one-sided Fisher
  test with Benjamini–Hochberg; the partners of one drug; over the whole corpus the drugs written most often, the
  association rules of the significant pairs (support, confidence, lift), the groups of drugs that hold together
  (communities of the significant pairs) and a clustering of the most frequent drugs (average linkage on 1 − Jaccard);
  a pair's share of compositions period by period;
* ``study network`` — 方证网络: a formula's findings (lift against how often each finding is named at all) and its
  drugs; a finding's formulas; the strongest formula–finding links of the corpus.

Associations in a corpus are associations of the writing: a pair common in one period may be one formula copied
many times (the counts are per work to temper it), and a finding named before a formula is not proof the formula
treats it.  The numbers point to what to read; each carries examples.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable

from ....science.association import CooccurrenceGraph, communities
from ....science.stats import average_linkage, benjamini_hochberg, cut_tree, fisher_exact_greater, largest_gap, leaf_order, odds_ratio
from .base import StudyBase, cache_tmp, dated
from .formulas import _LEADS_ON
from .usage import prepared_form

HARVEST_VERSION = "harvest@3"  # @2: each composition keeps its items (drug, dose as written, preparation note); a composition
                               # written in the passage after the one that introduces it (…汤方：) is read too; @3: and the
                               # form its preparation gives (丸剂, 煮散 …)
_DOSE_RAW = re.compile(r"[一二三四五六七八九十半兩两][兩两錢钱分銖铢升枚]")
_TREAT_RAW = re.compile(r"主之|[宜與与][^，。；]{0,10}[湯汤丸散飲饮]")
_SENTENCE = re.compile(r"[^。；？！]+[。；？！]?")
FINDINGS = ("symptom", "sign", "tongue", "pulse")
CONTEXT = ("pattern", "pathogenesis", "disease")


def _sig(x: float, digits: int = 3) -> float:
    """``x`` to ``digits`` significant figures (an odds ratio of 0.0123 or of 123 alike)."""
    return float(f"{x:.{digits}g}") if math.isfinite(x) and x else x


class FormulaHarvest:
    """Compositions and indications read once from the whole store (or the demo corpus), cached per corpus state."""

    def __init__(self, base: StudyBase, formulas: Any) -> None:
        self.b = base
        self.formulas = formulas
        self._built: dict[str, Any] | None = None

    def key(self) -> str:
        lex = self.b.pack.lexicon
        raw = json.dumps([self.b.signature()["corpus_digest"], len(lex.entries), HARVEST_VERSION])
        return hashlib.sha1(raw.encode()).hexdigest()[:12]

    def rows(self) -> Iterable[tuple[str, str, float | None, str, str]]:
        """(passage id, book id, year, text, heading) of the passages that may hold a composition or an indication."""
        store = getattr(self.b.corpus, "store", None)
        if store is None:
            for p in self.b.corpus.passages():
                if _DOSE_RAW.search(p.text) or _TREAT_RAW.search(p.text):
                    yield p.id, p.book_id, self.b.year(p), p.text, p.locator.section or ""
            return
        last = 0
        while True:
            with store.lock:
                rows = store.db.execute(
                    "SELECT rid, id, book_id, year, text, json_extract(locator, '$.section') FROM passages "
                    "WHERE rid > ? AND kind != 'toc' ORDER BY rid LIMIT 20000", (last,)).fetchall()
            if not rows:
                return
            last = rows[-1][0]
            for _rid, pid, bid, year, text, section in rows:
                if bid in self.b.corpus.books and (len(_DOSE_RAW.findall(text)) >= 2 or _TREAT_RAW.search(text)):
                    yield pid, bid, year, text, section or ""

    def build(self, cache: str | Path | None = None, *, refresh: bool = False, limit: int | None = None) -> dict[str, Any]:
        """``compositions``: [work, formula id, drug keys (sorted), year, passage id, drugs with a dose, items, form] — the
        items [drug key, drug, dose as written, preparation note] in the order written, the form what the preparation
        after them makes (丸剂, 煮散, 散剂, 汤剂 or ""); ``indications``: [work, formula id,
        finding ids (sorted), year, passage id].  One row per work and composition (or indication)."""
        if self._built is not None and not refresh and limit is None:
            return self._built
        path = Path(cache) / f"harvest-{self.key()}.json.gz" if cache is not None and limit is None else None
        if path is not None and path.exists() and not refresh:
            with gzip.open(path, "rt", encoding="utf-8") as f:
                self._built = json.load(f)
            return self._built
        lex = self.b.pack.lexicon
        comps: dict[tuple, list[Any]] = {}
        inds: dict[tuple, list[Any]] = {}
        scanned = 0
        lead: tuple[str, str] | None = None  # (book, formula) a passage introduced and left to the next (…汤方：)
        for pid, bid, year, text, section in self.rows():
            scanned += 1
            if limit is not None and scanned > limit:
                break
            book = self.b.corpus.books.get(bid)
            work = (book.work if book else None) or bid
            norm = self.b.normalize(text)
            mentions = lex.match(norm, include_weak=False)
            formulas = [m for m in mentions if m.category == "formula"]
            led, lead = (lead[1] if lead and lead[0] == bid else None), None
            if formulas and not _DOSE_RAW.search(text) and _LEADS_ON.match(norm[formulas[-1].end:]):
                lead = (bid, formulas[-1].entry.term_id)  # 与桂枝加桂汤，更加桂二两也。方六十一。 / 桂枝加桂汤方：
            covered: list[tuple[int, int]] = []
            if _DOSE_RAW.search(text):
                starts = [(m.start, m.surface, m.entry.term_id) for m in formulas
                          if _DOSE_RAW.search(norm[m.end: m.end + 60]) or re.search(r"[两钱分铢]", norm[m.end: m.end + 60])]
                heading = [m for m in lex.match(self.b.normalize(section), include_weak=False) if m.category == "formula"] if section else []
                if heading and (not formulas or formulas[0].start > 12):
                    starts.insert(0, (0, "", heading[0].entry.term_id))
                elif led and (not formulas or formulas[0].start > 12):
                    starts.insert(0, (0, "", led))  # the composition the previous passage introduced
                for pos, surface, fid in starts:
                    if any(a <= pos < b for a, b in covered):
                        continue
                    comp = self.formulas.parse_at(norm, pos, surface)
                    if comp is None:
                        continue
                    covered.append((pos, comp.end))
                    herbs = sorted(comp.herbs)
                    if len(herbs) >= 2:
                        items = [[i.get("family") or i["term_id"], i["term"], i["dose"], i["processing"]] for i in comp.items]
                        comps.setdefault((work, fid, tuple(herbs)), [work, fid, herbs, year, pid, sum(1 for i in comp.items if i["dose"]),
                                                                     items, prepared_form(comp.preparation or norm[comp.end: comp.end + 80])])
            if _TREAT_RAW.search(text):
                for s in _SENTENCE.finditer(norm):
                    sent = s.group(0)
                    if "主之" not in sent and not re.search(r"[宜与][^，。；]{0,10}[汤丸散饮]", sent):
                        continue
                    ms = [m for m in mentions if s.start() <= m.start < s.end()]
                    fs = [m for m in ms if m.category == "formula"]
                    if not fs:
                        continue
                    f = fs[-1] if "主之" in sent else fs[0]
                    found = sorted({m.entry.term_id for m in ms if m.start < f.start and m.category in FINDINGS + CONTEXT})
                    if found:
                        inds.setdefault((work, f.entry.term_id, tuple(found)), [work, f.entry.term_id, found, year, pid])
        built = {"key": self.key(), "scanned": scanned, "compositions": list(comps.values()), "indications": list(inds.values())}
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache_tmp(path)
            with gzip.open(tmp, "wt", encoding="utf-8") as f:
                json.dump(built, f, ensure_ascii=False)
            tmp.replace(path)
            for old in path.parent.glob("harvest-*.json.gz"):
                if old != path:
                    old.unlink(missing_ok=True)
        if limit is None:
            self._built = built
        return built


class PairsStudy:
    def __init__(self, base: StudyBase, harvest: FormulaHarvest) -> None:
        self.b = base
        self.h = harvest

    def _cache(self) -> str | None:
        store = getattr(self.b.corpus, "store", None)
        return str(store.path.parent / "study-cache") if store is not None else None

    def _label(self, key: str) -> str:
        if key.startswith("family:"):
            return key.split(":", 1)[1]
        entry = self.b.pack.lexicon.entries.get(key)
        return entry.term if entry else key.split(":", 1)[-1]

    def _key_of(self, name: str, category: str = "herb") -> str | None:
        """The key a drug is counted under (its family if it has one: 桂枝 → 桂), from any of its names."""
        fam = self.h.formulas.families.get(name) or self.h.formulas.families.get(self.b.normalize(name))
        if fam:
            return f"family:{fam}"
        entry = self.b.pack.lexicon.resolve(name, category) or self.b.pack.lexicon.resolve(self.b.normalize(name), category)
        return entry.term_id if entry else None

    def _period(self, year: float | None) -> str:
        per = self.b.period_of(year)
        return per.label if per else "未定"

    # ------------------------------------------------------------ 配伍
    @staticmethod
    def pair_table(transactions: list[set[str]], *, min_support: int = 5, q: float = 0.05) -> list[dict[str, Any]]:
        """Every pair seen together at least ``min_support`` times: support, confidence both ways, lift, PMI, the
        one-sided Fisher p against independence and whether it passes Benjamini–Hochberg at ``q``."""
        n = len(transactions)
        single: Counter = Counter()
        joint: Counter = Counter()
        for t in transactions:
            items = sorted(t)
            single.update(items)
            joint.update(combinations(items, 2))
        rows = []
        pvals: dict[tuple[str, str], float] = {}
        for (a, b), k in joint.items():
            if k < min_support:
                continue
            na, nb = single[a], single[b]
            lift = k * n / (na * nb)
            p = fisher_exact_greater(k, na - k, nb - k, n - na - nb + k)
            pvals[(a, b)] = p
            pmi = math.log2(lift)
            npmi = pmi / -math.log2(k / n) if k < n else 1.0  # normalised: rare drugs do not rank first by chance of rarity
            o = odds_ratio(k, na - k, nb - k, n - na - nb + k)
            rows.append({"a": a, "b": b, "support": k, "conf_ab": round(k / na, 4), "conf_ba": round(k / nb, 4),
                         "lift": round(lift, 3), "pmi": round(pmi, 3), "npmi": round(npmi, 4), "p": p, "n_a": na, "n_b": nb,
                         "or": _sig(o["or"]), "or_ci": [_sig(o["lo"]), _sig(o["hi"])]})
        passed = benjamini_hochberg(pvals, q=q) if pvals else {}
        for r in rows:
            r["significant"] = bool(passed.get((r["a"], r["b"])))
            r["p"] = float(f"{r['p']:.3g}")
        rows.sort(key=lambda r: (not r["significant"], -r["npmi"], -r["support"], r["a"], r["b"]))
        return rows

    def pairs(self, herb: str | None = None, *, min_support: int | None = None, top: int = 60, period: str | None = None) -> dict[str, Any]:
        min_support = min_support or (5 if herb else 10)  # the corpus-wide list: pairs seen at least ten times
        built = self.h.build(self._cache())
        comps = built["compositions"]
        if period:
            comps = [c for c in comps if self._period(c[3]) == period]
        transactions = [set(c[2]) for c in comps]
        table = self.pair_table(transactions, min_support=min_support)
        target = self._key_of(herb) if herb else None
        if herb and target is None:
            raise self.b.not_taken(herb, ("herb",), "is not a drug of the lexicon")
        rows = [r for r in table if target in (r["a"], r["b"])] if target else table
        for r in rows:
            r["a_name"], r["b_name"] = self._label(r["a"]), self._label(r["b"])
        significant = [r for r in rows if r["significant"]]
        out: dict[str, Any] = {"herb": herb, "key": target, "compositions": len(transactions), "period": period,
                               "min_support": min_support, "significant": len(significant), "pairs": significant[:top],
                               "not_significant": sum(1 for r in rows if not r["significant"]),
                               "note": "counts are per work (a composition repeated in the copies of one work counts once); "
                                       "significant = one-sided Fisher test, Benjamini–Hochberg at q=0.05"}
        if target:
            out["partners"] = self._partners(transactions, target, rows)
            out["triples"] = self._triples(transactions, target)
            out["by_period"] = self._by_period(comps, target)
        else:
            out["groups"] = self._groups(table)
            out["top_by_support"] = [{"pair": f"{self._label(r['a'])}—{self._label(r['b'])}", "support": r["support"], "lift": r["lift"]}
                                     for r in sorted(table, key=lambda r: -r["support"])[:20]]
            single: Counter = Counter(x for t in transactions for x in t)
            n = len(transactions) or 1
            out["frequency"] = [{"drug": self._label(k), "compositions": v, "share": round(v / n, 4)} for k, v in single.most_common(30)]
            out["rules"] = self._rules(table, n)
            clusters, dendrogram = self._clusters(transactions, single, min_support)
            if clusters:
                out["clusters"] = clusters
                out["_raw"] = {"dendrogram": dendrogram}  # the tree the figure draws: taken out with the charts (charts.attach)
        return out

    def _rules(self, table: list[dict[str, Any]], n: int, *, top: int = 30, min_confidence: float = 0.5) -> list[dict[str, Any]]:
        """Association rules of the significant pairs, both ways (A → B: of the compositions with A, the share with B),
        at least ``min_confidence``, most confident first."""
        rules = []
        for r in table:
            if not r["significant"]:
                continue
            for lhs, rhs, conf in ((r["a"], r["b"], r["conf_ab"]), (r["b"], r["a"], r["conf_ba"])):
                if conf >= min_confidence:
                    rules.append({"if": self._label(lhs), "then": self._label(rhs), "support": r["support"],
                                  "support_share": round(r["support"] / n, 4), "confidence": conf, "lift": r["lift"]})
        rules.sort(key=lambda x: (-x["confidence"], -x["lift"], -x["support"], x["if"], x["then"]))
        return rules[:top]

    def _clusters(self, transactions: list[set[str]], single: Counter, min_support: int,
                  top: int = 30) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """The ``top`` most frequent drugs clustered by average linkage on 1 − Jaccard of the compositions they are
        written in, cut where the next merge is the longest branch: [{cluster, drugs}] and the tree to draw."""
        keys = [k for k, v in single.most_common(top) if v >= min_support]
        if len(keys) < 4:
            return [], {}
        where: dict[str, set[int]] = {k: set() for k in keys}
        for i, t in enumerate(transactions):
            for k in keys:
                if k in t:
                    where[k].add(i)
        dist = [[0.0 if a == b else 1 - len(where[a] & where[b]) / len(where[a] | where[b]) for b in keys] for a in keys]
        merges = average_linkage(dist)
        n = len(keys)
        k = largest_gap(merges, n, k_min=2, k_max=min(8, n - 1))
        member = cut_tree(merges, n, k)
        labels = [self._label(x) for x in keys]
        order = leaf_order(merges, n)
        groups = [{"cluster": c + 1, "drugs": [labels[i] for i in order if member[i] == c]} for c in range(k)]
        cut = (float(merges[n - k - 1][2]) + float(merges[n - k][2])) / 2 if 0 < n - k < len(merges) else None
        return groups, {"labels": labels, "frequency": [single[x] for x in keys], "merges": merges, "order": order,
                        "member": member, "k": k, "cut": round(cut, 4) if cut is not None else None,
                        "method": "average linkage (UPGMA), distance 1 − Jaccard"}

    def _partners(self, transactions: list[set[str]], target: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for r in rows:
            other = r["b"] if r["a"] == target else r["a"]
            given_target, given_other = (r["conf_ab"], r["conf_ba"]) if r["a"] == target else (r["conf_ba"], r["conf_ab"])
            out.append({"with": self._label(other), "key": other, "support": r["support"], "p_with_given_drug": given_target,
                        "p_drug_given_with": given_other, "lift": r["lift"], "pmi": r["pmi"], "npmi": r["npmi"],
                        "or": r["or"], "or_ci": r["or_ci"], "p": r["p"], "significant": r["significant"]})
        return sorted(out, key=lambda x: (not x["significant"], -x["npmi"], -x["support"]))[:40]

    def _triples(self, transactions: list[set[str]], target: str, *, min_support: int = 5) -> list[dict[str, Any]]:
        counts: Counter = Counter()
        with_target = [t for t in transactions if target in t]
        for t in with_target:
            counts.update(combinations(sorted(t - {target}), 2))
        return [{"with": [self._label(a), self._label(b)], "support": k, "share": round(k / len(with_target), 4)}
                for (a, b), k in counts.most_common(15) if k >= min_support]

    def _by_period(self, comps: list[list[Any]], target: str) -> list[dict[str, Any]]:
        totals: Counter = Counter()
        hits: Counter = Counter()
        for c in comps:
            per = self._period(c[3])
            totals[per] += 1
            hits[per] += target in c[2]
        order = [p.label for p in self.b.periods] + ["未定"]
        return [{"period": p, "compositions": totals[p], "with": hits[p], "share": round(hits[p] / totals[p], 4) if totals[p] else None}
                for p in order if totals[p]]

    def _groups(self, table: list[dict[str, Any]], *, top: int = 12, min_npmi: float = 0.3,
                min_support: int = 10) -> list[dict[str, Any]]:
        """Groups of drugs that hold together: communities of the graph of the strong pairs (significant, normalised
        PMI at least ``min_npmi``, seen ``min_support`` times), weighted by PMI — the weak links of drugs used
        everywhere (甘草) would join everything into one group."""
        edges = []
        for r in table:
            if r["significant"] and r["npmi"] >= min_npmi and r["support"] >= min_support:
                edges += [[r["a"], r["b"]]] * max(1, int(round(r["pmi"])))
        if not edges:
            return []
        graph = CooccurrenceGraph(edges)
        groups = communities(graph, min_weight=1)
        return [{"size": len(g), "drugs": [self._label(x) for x in sorted(g)][:16]} for g in groups if len(g) >= 2][:top]

    # ------------------------------------------------------------ 方证网络
    def network(self, target: str | None = None, *, min_support: int = 10, top: int = 40) -> dict[str, Any]:
        built = self.h.build(self._cache())
        inds = built["indications"]
        comps = built["compositions"]
        lex = self.b.pack.lexicon
        finding_n: Counter = Counter(x for i in inds for x in i[2])
        formula_n: Counter = Counter(i[1] for i in inds)
        n = len(inds) or 1
        if target is None:
            joint: Counter = Counter((i[1], x) for i in inds for x in i[2])
            rows = []
            for (f, x), k in joint.items():
                if k < min_support:
                    continue
                lift = k * n / (formula_n[f] * finding_n[x])
                rows.append({"formula": self._label(f), "finding": self._label(x), "support": k, "lift": round(lift, 3),
                             "npmi": round(math.log2(lift) / -math.log2(k / n), 4) if k < n else 1.0})
            rows.sort(key=lambda r: (-r["npmi"], -r["support"]))
            return {"target": None, "indications": len(inds), "compositions": len(comps), "links": rows[:top],
                    "note": "formula–finding links seen at least ten times: the findings named before a formula in a "
                            "treatment sentence, ranked by normalised PMI (lift against how often each is named at all)"}
        entry = lex.resolve(target, "formula") or lex.resolve(self.b.normalize(target), "formula")
        if entry is not None:
            fid = entry.term_id
            mine = [i for i in inds if i[1] == fid]
            got: Counter = Counter(x for i in mine for x in i[2])
            findings = [{"finding": self._label(x), "category": lex.entries[x].category if x in lex.entries else "", "support": k,
                         "share": round(k / len(mine), 4), "lift": round(k * n / (len(mine) * finding_n[x]), 3)}
                        for x, k in got.most_common() if k >= 2]
            findings.sort(key=lambda r: (-r["support"], -r["lift"]))
            herbs: Counter = Counter(h for c in comps if c[1] == fid for h in c[2])
            n_c = sum(1 for c in comps if c[1] == fid) or 1
            periods: Counter = Counter(self._period(i[3]) for i in mine)
            return {"target": entry.term, "kind": "formula", "indications": len(mine), "findings": findings[:top],
                    "drugs": [{"drug": self._label(h), "compositions": k, "share": round(k / n_c, 4)} for h, k in herbs.most_common(20)],
                    "compositions": n_c if herbs else 0, "by_period": dict(periods),
                    "examples": [i[4] for i in sorted(mine, key=lambda i: dated([i[3], i[3]] if i[3] is not None else None))[:5]],
                    "note": "findings named before the formula in its treatment sentences (per work); drugs of its "
                            "written-out compositions"}
        entry = next((lex.resolve(target, c) for c in FINDINGS + CONTEXT if lex.resolve(target, c)), None) or \
            next((lex.resolve(self.b.normalize(target), c) for c in FINDINGS + CONTEXT if lex.resolve(self.b.normalize(target), c)), None)
        if entry is None:
            raise self.b.not_taken(target, ("formula", *FINDINGS, *CONTEXT),
                                   "is neither a formula nor a finding of the lexicon")
        xid = entry.term_id
        mine = [i for i in inds if xid in i[2]]
        got = Counter(i[1] for i in mine)
        formulas = [{"formula": self._label(f), "support": k, "share": round(k / len(mine), 4),
                     "lift": round(k * n / (len(mine) * formula_n[f]), 3)} for f, k in got.most_common() if k >= 2]
        periods = Counter(self._period(i[3]) for i in mine)
        return {"target": entry.term, "kind": entry.category, "indications": len(mine), "formulas": formulas[:top],
                "by_period": dict(periods), "note": "formulas whose treatment sentences name the finding before them (per work)"}


__all__ = ["FormulaHarvest", "HARVEST_VERSION", "PairsStudy"]
