"""语义演变 2.0 — a term's senses period by period, the date its meaning shifted, and senses the curation lacks.

Occurrences of the term (in any of its written forms) are sampled period by period and read in a window of context:
the concepts the lexicon finds there and the content bigrams.  The curated senses of ``terminology.yaml`` label the
contexts their cues fit (``science.sense_evolution``); the rest are clustered into candidate senses, each shown with
its distinctive words and examples for a person to read and name; the sense shares by period give the series and the
change point; the neighbourhood of the term is compared from period to period.  The curated exemplars (passages
the curation cites for each sense) serve as a check of the labelling.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from ....science.sense_evolution import assign, change_points, discover, neighbourhood, series
from .base import StudyBase, han_only
from .stemma import mask_notes

_FUNCTION = set("之乎者也矣焉哉而其以于所则乃且亦又即若如故夫盖此是斯兮曰云为与皆不无")


class SenseStudy:
    def __init__(self, base: StudyBase) -> None:
        self.b = base

    def _senses(self, term: str) -> tuple[Any, list[dict[str, Any]]]:
        ht = self.b.pack.terminology.term(term)
        if ht is None:
            return None, []
        n = self.b.normalize
        return ht, [{"id": s.id, "label": s.label, "gloss": s.gloss, "period": [s.period.start, s.period.end] if s.period else None,
                     "cues": [n(c) for c in s.cues], "anti_cues": [n(c) for c in s.anti_cues], "exemplars": list(s.exemplars)}
                    for s in ht.senses]

    def occurrences(self, term: str, *, per_period: int = 300, window: int = 12) -> list[dict[str, Any]]:
        """Up to ``per_period`` dated occurrences per analysis period, each with its context window and tokens."""
        _, forms = self.b.surfaces(term)
        surfaces = sorted({self.b.normalize(f) for f, _ in forms if f}, key=len, reverse=True)
        ids: set[str] = set()
        for f in surfaces[:8]:
            ids.update(self.b.find(f, limit=20000))
        by_period: dict[str, list[Any]] = defaultdict(list)
        for p in self.b.passages(sorted(ids)):
            if p.kind == "toc":
                continue
            per = self.b.period_of(self.b.year(p))
            if per is not None:
                by_period[per.id].append(p)
        own = set(surfaces)
        out: list[dict[str, Any]] = []
        for per in self.b.periods:
            ps = by_period.get(per.id, [])
            if len(ps) > per_period:
                step = len(ps) / per_period
                ps = [ps[int(i * step)] for i in range(per_period)]
            for p in ps:
                norm = self.b.normalize(mask_notes(p.text))
                at = next((norm.find(f) for f in surfaces if f in norm), -1)
                if at < 0:
                    continue
                text = norm[max(0, at - window): at + window + 2]
                quote = p.text[max(0, at - window): at + window + 2]  # the same window, verbatim (normalising keeps lengths)
                han, _ = han_only(text)
                concepts = [m.entry.term for m in self.b.pack.lexicon.match(han, include_weak=False)
                            if len(m.surface) >= 2 and m.surface not in own]
                grams = [han[i: i + 2] for i in range(len(han) - 1)
                         if not set(han[i: i + 2]) & _FUNCTION and han[i: i + 2] not in own and not any(han[i: i + 2] in f for f in own)]
                out.append({"passage_id": p.id, "book_id": p.book_id, "year": self.b.year(p), "period": per.label,
                            "text": text, "quote": quote, "tokens": concepts + grams})
        return out

    def run(self, term: str, *, per_period: int = 300, window: int = 12, k: int = 3) -> dict[str, Any]:
        ht, senses = self._senses(term)
        occ = self.occurrences(term, per_period=per_period, window=window)
        labels = assign(occ, senses) if senses else [None] * len(occ)
        per_series = series(labels, [o["period"] for o in occ])
        order = [p.label for p in self.b.periods]
        table = []
        for per in order:
            if per in per_series:
                c = per_series[per]
                total = sum(c.values())
                table.append({"period": per, "occurrences": total,
                              "shares": {k_: round(v / total, 3) for k_, v in c.most_common()}})
        dated = [(o["year"], lab) for o, lab in zip(occ, labels) if lab and o["year"] is not None]
        changes = change_points([y for y, _ in dated], [lab for _, lab in dated]) if dated else []
        change = max(changes, key=lambda c: c["statistic"]) if changes else None
        found = discover(occ, labels, k=k)
        for cand in found:
            members = cand.pop("members")
            years = sorted(occ[m]["year"] for m in members if occ[m]["year"] is not None)
            cand["span"] = [years[0], years[-1]] if years else None
            cand["examples"] = [{"passage_id": occ[m]["passage_id"], "period": occ[m]["period"], "context": occ[m]["text"],
                                 "quote": occ[m]["quote"]} for m in members[:4]]
        tokens_by_period: dict[str, list[list[str]]] = defaultdict(list)
        for o in occ:
            tokens_by_period[o["period"]].append(o["tokens"])
        exemplars = []
        by_passage = {o["passage_id"]: lab for o, lab in zip(occ, labels)}
        for s in senses:
            for pid in s["exemplars"]:
                if pid in by_passage:
                    exemplars.append({"sense": s["id"], "passage_id": pid, "assigned": by_passage[pid]})
        return {
            "term": term, "curated": ht is not None, "senses": [{k_: v for k_, v in s.items() if k_ not in ("cues", "anti_cues")} for s in senses],
            "occurrences": len(occ), "assigned": sum(1 for x in labels if x), "series": table, "change_point": change,
            "change_points": changes,
            "candidate_senses": found, "neighbourhood": neighbourhood(tokens_by_period, order),
            "exemplar_check": {"checked": len(exemplars), "agree": sum(1 for e in exemplars if e["assigned"] == e["sense"]),
                               "items": exemplars},
            "note": "senses labelled by their curated cues (anti-cues against); unlabelled contexts clustered into candidate "
                    "senses for a person to read and name; change point: the date splitting the labelled occurrences into "
                    "the most different sense distributions (permutation test), then again before and after it; a sample "
                    "of at most "
                    f"{per_period} occurrences per period",
        }


__all__ = ["SenseStudy"]
