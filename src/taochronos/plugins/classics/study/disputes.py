"""争议 — where the literature argues with itself: a named physician's view reported, and rejected in the next breath.

Chinese medicine argued in commentary: 景岳 against 丹溪's 阳常有余阴常不足, 修园 against 景岳, 喻昌 against 叔和's
arrangement of the 伤寒论.  An argument of this kind has a form: a predecessor is named with a word that reports his
view (丹溪谓…, 东垣之说…, 成氏注…), and the sentence after it, or the next, says the view is wrong (非也, 谬矣, 殊不知,
不可从, 此说非 …).  ``study disputes``

* for a **term** (相火) or a **person** (丹溪), reads the passages that name them and keeps each named view with its
  stance — rejected, endorsed, or only cited — and the words that decide it;
* aggregates who rejects whom (the citing book's author, else the book), when (by the date of the citing passage's
  layer), about what (the terms of the lexicon and of ``exegesis.yaml`` in the disputed sentences);
* with neither, reads the whole corpus through the citation network (``study citations``): for every citing author
  and cited physician, how often the citation is a rejection or an approval.

The markers and the name forms are in ``exegesis.yaml`` and ``physicians.yaml``; the reading is mechanical and
conservative (a rejection must follow a named, reported view), so a dispute conducted without names is missed, and
a marker that belongs to the quoted text itself can be misread — each record carries its sentence to check.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from .base import StudyBase, dated
from .commentary import Commentators, CommentaryStudy


class DisputeStudy:
    def __init__(self, base: StudyBase, commentary: CommentaryStudy, network: Any) -> None:
        self.b = base
        self.c = commentary
        self.people: Commentators = commentary.people
        self.net = network

    def _candidates(self, term: str | None, person: str | None, limit: int) -> tuple[list[str], list[str], str | None]:
        """Passages that carry the term (any of its written forms) and name the person; the forms; the person id."""
        forms: list[str] = []
        ids: set[str] | None = None
        if term:
            _, found = self.b.surfaces(term)
            forms = [f for f, _ in found] or [term]
            hit: set[str] = set()
            for f in forms:
                hit.update(self.b.find(f, limit=limit))
            ids = hit
        pid = None
        if person:
            pid = self.people.alias.get(self.b.normalize(person)) or (person if person in self.people.persons else None)
            names = (self.people.persons.get(pid, {}).get("names") if pid else None) or [person]
            hit = set()
            for name in names:
                if len(self.b.normalize(name)) >= 2:
                    hit.update(self.b.find(name, limit=limit))
            ids = hit if ids is None else ids & hit
        return sorted(ids or []), forms, pid

    def run(self, term: str | None = None, *, person: str | None = None, limit: int = 400,
            max_passages: int = 30000) -> dict[str, Any]:
        if not term and not person:
            return self.survey()
        ids, forms, pid = self._candidates(term, person, max_passages)
        norm_forms = [self.b.normalize(f) for f in forms]
        records: list[dict[str, Any]] = []
        scanned = 0
        for p in self.b.passages(ids[:max_passages]):
            scanned += 1
            norm = self.b.normalize(p.text)
            book = self.b.corpus.books.get(p.book_id)
            own = self.people.person_of(list(book.authors) if book else [])
            for c in self.people.cited(norm, own=own):
                if pid and c["person"] != pid:
                    continue
                if norm_forms and not any(f in c["quote"] for f in norm_forms) and not any(f in norm for f in norm_forms):
                    continue
                years = self.b.years(p)
                per = self.b.period_of(self.b.year(p))
                concepts = sorted(self.c.concepts(c["quote"]))
                born = self._start(c["person"])
                records.append({
                    "later_layer": bool(years and born is not None and years[1] < born),
                    "stance": c["stance"] or "cite", "marker": c["marker"], "target": c["name"], "target_person": c["person"],
                    "by": (self.people.name(c["reported_by"]) if c.get("reported_by")
                           else "、".join(book.authors) if book and book.authors else (book.title if book else p.book_id)),
                    "by_person": c.get("reported_by") or own, "reported_in": (book.title if book else p.book_id) if c.get("reported_by") else None,
                    "book_id": p.book_id, "title": book.title if book else p.book_id,
                    "work": (book.work if book else None) or p.book_id, "passage_id": p.id, "locator": self.b.locator(p),
                    "years": list(years) if years else None, "period": per.label if per else None,
                    "sentence": c["quote"], "about": concepts[:12],
                    "term_in_sentence": any(f in c["quote"] for f in norm_forms) if norm_forms else None,
                })
        records = self._one_per_work(records)
        records.sort(key=lambda r: (dated(r["years"]), r["book_id"], r["passage_id"]))
        later = [r for r in records if r["later_layer"]]  # a physician named before he lived: a later layer's note
        records = [r for r in records if not r["later_layer"]]
        rejects = [r for r in records if r["stance"] == "reject"]
        pairs: Counter = Counter((r["by"], r["target"]) for r in rejects)
        by_period: dict[str, Counter] = defaultdict(Counter)
        for r in records:
            by_period[r["period"] or "未定"][r["stance"]] += 1
        about: Counter = Counter(c for r in rejects for c in r["about"])
        return {
            "term": term, "person": person, "forms": forms, "passages_scanned": scanned,
            "counts": dict(Counter(r["stance"] for r in records)),
            "disputes": rejects[:limit], "endorsements": [r for r in records if r["stance"] == "endorse"][:limit],
            "citations": [r for r in records if r["stance"] == "cite"][:limit],
            "who_rejects_whom": [{"by": a, "target": b, "count": n} for (a, b), n in pairs.most_common(40)],
            "by_period": {k: dict(v) for k, v in by_period.items()},
            "about": [{"concept": c, "count": n} for c, n in about.most_common(20)],
            "later_layers": later[:40],
            "note": "a dispute is a named, reported view followed by a rejection word in the same or the next sentence; "
                    "read each sentence — a marker can belong to the quoted text, and disputes without names are missed",
        }

    def _start(self, person: str | None) -> float | None:
        p = self.people.persons.get(person or "", {})
        dates = p.get("life") or p.get("active")
        return float(dates[0]) if dates else None

    @staticmethod
    def _one_per_work(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The same sentence in several transcriptions of one work counts once (the earliest-dated copy stands)."""
        seen: dict[tuple[str, str, str], dict[str, Any]] = {}
        for r in sorted(records, key=lambda r: (dated(r["years"]), r["book_id"])):
            key = (r["by"], r["target"], re.sub(r"[^一-鿿]", "", r["sentence"])[:30])
            if key in seen:
                seen[key].setdefault("copies", []).append(r["passage_id"])
            else:
                seen[key] = r
        return list(seen.values())

    def survey(self, *, min_count: int = 2, top: int = 40) -> dict[str, Any]:
        """The corpus through the citation network: for each citing author and cited physician, the citations that
        reject and that approve."""
        built = self.net.build(self.b_cache())
        rejects = built.get("rejects") or {}
        endorses = built.get("endorses") or {}
        cites = built.get("persons") or {}
        edges: dict[tuple[str, str], Counter] = defaultdict(Counter)
        for key, people in cites.items():
            src = self._citing(key.split("|", 1)[0])
            for person, n in people.items():
                edges[(src, person)]["cite"] += n
                edges[(src, person)]["reject"] += (rejects.get(key) or {}).get(person, 0)
                edges[(src, person)]["endorse"] += (endorses.get(key) or {}).get(person, 0)
        examples: dict[tuple[str, str], list[str]] = defaultdict(list)
        for key, pids in (built.get("reject_examples") or {}).items():
            bid, person = key.split("|", 1)
            examples[(self._citing(bid), person)] += pids
        rows = [{"by": src, "target": self.people.name(person), "citations": c["cite"], "rejections": c["reject"],
                 "approvals": c["endorse"], "examples": self._examples(examples.get((src, person), [])[:3], person)}
                for (src, person), c in edges.items() if c["reject"] >= min_count]
        rows.sort(key=lambda r: (-r["rejections"], -r["citations"], r["by"], r["target"]))
        targets: Counter = Counter()
        cited: Counter = Counter()
        for (_, person), c in edges.items():
            targets[person] += c["reject"]
            cited[person] += c["cite"]
        most = [{"target": self.people.name(p), "rejections": n, "citations": cited[p], "share": round(n / cited[p], 3) if cited[p] else None}
                for p, n in targets.most_common(top) if n]
        return {"term": None, "person": None, "who_rejects_whom": rows[:top], "most_disputed": most,
                "passages_scanned": built.get("passages"),
                "note": "counted over the whole corpus by the citation network; a rejection is a rejection word after a "
                        "named, reported view — read the examples"}

    def _examples(self, pids: list[str], person: str) -> list[dict[str, Any]]:
        """The rejecting sentences of the example passages, with their sources."""
        out = []
        for p in self.b.passages(pids):
            norm = self.b.normalize(p.text)
            for c in self.people.cited(norm):
                if c["person"] == person and c["stance"] == "reject":
                    years = self.b.years(p)
                    out.append({"passage_id": p.id, "locator": self.b.locator(p), "years": list(years) if years else None,
                                "sentence": c["quote"], "marker": c["marker"]})
                    break
        return out

    def _citing(self, book_id: str) -> str:
        book = self.b.corpus.books.get(book_id)
        if book is None:
            return book_id
        person = self.people.person_of(list(book.authors))
        return self.people.name(person) if person else ("、".join(book.authors) or book.title)

    def b_cache(self) -> str | None:
        store = getattr(self.b.corpus, "store", None)
        return str(store.path.parent / "study-cache") if store is not None else None


__all__ = ["DisputeStudy"]
