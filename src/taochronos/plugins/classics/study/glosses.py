"""训诂 — what commentators said a word means: glosses gathered from the corpus, by who gave them and when.

The commentators explained difficult words in set forms: 几几者，伸颈之貌也 (者…也), 濈然，汗出貌 (…貌), 强，群养切
(反切), 几音殊 (音), 痓当作痉 (当作), 一作… (异文).  ``study glosses``

* for a **term**, reads the passages that contain it and keeps every gloss whose head is the term (or ends with it:
  项背强几几者 … glosses 几几 too), with the commentator (the passage's layer, else the book's authors) and the date;
* groups the glosses into **readings** — the same gloss in other words is not merged, the same words are — and says
  who first gave each and how many later repeated it, and which kinds of gloss (meaning, sound, emendation) the
  word drew period by period;
* for a **book**, lists the glosses it gives: the glossary of a commentary.

The forms are those of ``exegesis.yaml``; a set form can be used for something other than a gloss (…者，…也 also
states a pattern), so each gloss carries its sentence to check.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from .base import StudyBase, dated

SOUND = {"音", "反切", "读为"}
TEXT = {"异文", "校改"}


_QUOTED = re.compile(r"^[一-鿿]{1,4}(?:氏)?(?:云|曰)[：:，,]?[「“『]?")
_NOTES = re.compile(r"（[^（）]*）|\([^()]*\)")


def clean(gloss: str) -> str:
    """A gloss without the notes inside it and the name of the one it is quoted from (程氏云：「连绵也」 → 连绵)."""
    return re.sub(r"(?<=[一-鿿])也$", "", _QUOTED.sub("", _NOTES.sub("", gloss)).strip("，,「」“”『』 　"))


class GlossStudy:
    def __init__(self, base: StudyBase, commentary: Any) -> None:
        self.b = base
        self.forms = commentary.ex.glosses
        self.people = commentary.people

    def find(self, norm: str, raw: str | None = None) -> list[dict[str, Any]]:
        """The glosses in a normalised text: kind, head, gloss, span.  With ``raw`` (the same text as written — the
        normaliser keeps lengths), the head and gloss of a gloss on the letter (音, 反切, 读为, 通, 一作, 当作) are
        taken as written: 痓当作痉 is an emendation the normaliser, which reads both as 痉, would hide."""
        raw = raw if raw is not None and len(raw) == len(norm) else None
        out: list[dict[str, Any]] = []
        seen: set[tuple[int, int]] = set()
        notes = [(m.start(), m.end()) for m in re.finditer(r"（[^（）]{0,300}）|\([^()]{0,300}\)", norm)]
        for kind, rx in self.forms:
            for m in rx.finditer(norm):
                head, gloss = m.group("head"), clean(m.group("gloss"))
                if raw is not None and kind in SOUND | TEXT | {"通"}:
                    head = raw[m.start("head"): m.end("head")]
                    gloss = clean(raw[m.start("gloss"): m.end("gloss")])
                if not head or not gloss or head == gloss or (m.start(), m.end()) in seen:
                    continue
                seen.add((m.start(), m.end()))
                bounded = m.start() == 0 or not re.match(r"[㐀-鿿]", norm[m.start() - 1])
                in_note = any(s <= m.start() < e for s, e in notes)
                out.append({"kind": kind, "head": head, "gloss": gloss.strip("，,"), "start": m.start(), "end": m.end(),
                            "bounded": bounded, "in_note": in_note, "sentence": norm[max(0, m.start() - 10): m.end() + 6]})
        return out

    def _commentator(self, p: Any) -> str:
        layer = next((t.split(":", 1)[1] for t in p.tags if t.startswith("layer:")), "")
        book = self.b.corpus.books.get(p.book_id)
        if layer and (layer.endswith(("注", "按", "疏", "解", "释")) or "·" in layer) and "（" not in layer:
            return layer
        return "、".join(book.authors) if book and book.authors else (book.title if book else p.book_id)

    def run(self, term: str | None = None, *, book: str | None = None, limit: int = 400,
            max_passages: int = 20000) -> dict[str, Any]:
        if not term and not book:
            raise ValueError("give a term (几几) or a book id (its glossary)")
        norm_term = self.b.normalize(term) if term else None
        if term:
            ids: set[str] = set()
            for f in [term, norm_term]:
                ids.update(self.b.find(f, limit=max_passages, book_ids=[book] if book else None))
            passages = self.b.passages(sorted(ids)[:max_passages])
        else:
            passages = self.b.corpus.passages(book_ids=[book]) if not getattr(self.b.corpus, "store", None) else \
                self.b.passages(self._book_ids(book))
        records: list[dict[str, Any]] = []
        for p in passages:
            norm = self.b.normalize(p.text)
            for g in self.find(norm, p.text):
                head = self.b.normalize(g["head"])
                if norm_term:  # the gloss is of the word itself (几几者 …, 濈濈然者 … for 濈然), not of a clause ending in it
                    if not (head == norm_term or (head.endswith(norm_term) and len(head) - len(norm_term) <= 1)):
                        continue
                    g["head"] = g["head"][-len(norm_term):]
                elif not g["bounded"] or len(g["head"]) > 4:  # a glossary lists words, not clauses
                    continue
                years = self.b.years(p)
                per = self.b.period_of(self.b.year(p))
                bk = self.b.corpus.books.get(p.book_id)
                records.append({**g, "by": self._commentator(p) + ("（小注）" if g["in_note"] else ""), "book_id": p.book_id,
                                "title": bk.title if bk else p.book_id,
                                "work": (bk.work if bk else None) or p.book_id, "passage_id": p.id,
                                "locator": self.b.locator(p), "years": list(years) if years else None,
                                "period": per.label if per else None,
                                "type": "sound" if g["kind"] in SOUND else ("text" if g["kind"] in TEXT else "meaning")})
        records = self._one_per_work(records)
        records.sort(key=lambda r: (dated(r["years"]), r["book_id"], r["start"]))
        readings: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for r in records:
            readings[(r["type"], re.sub(r"[也之者]$", "", r["gloss"]))].append(r)
        rows = [{"type": t, "gloss": g, "count": len(rs), "first": {k: rs[0][k] for k in ("by", "title", "years", "period", "passage_id")},
                 "by": list(dict.fromkeys(x["by"] for x in rs))[:12], "heads": sorted({x["head"] for x in rs})[:6]}
                for (t, g), rs in readings.items()]
        rows.sort(key=lambda r: (-r["count"], dated(r["first"]["years"]), r["gloss"]))
        by_period: dict[str, Counter] = defaultdict(Counter)
        for r in records:
            by_period[r["period"] or "未定"][r["type"]] += 1
        return {"term": term, "book": book, "count": len(records), "glosses": records[:limit], "readings": rows[:80],
                "kinds": dict(Counter(r["kind"] for r in records)), "by_period": {k: dict(v) for k, v in by_period.items()},
                "note": "glosses in the set forms of exegesis.yaml (…者…也, …貌, 音, 反切, 读为, 当作, 一作 …); a form can "
                        "state something other than a gloss — read the sentence"}

    def _book_ids(self, book: str) -> list[str]:
        store = self.b.corpus.store
        with store.lock:
            return [r[0] for r in store.db.execute("SELECT id FROM passages WHERE book_id=? ORDER BY rid", (book,))]

    @staticmethod
    def _one_per_work(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The same gloss in several transcriptions of one work counts once."""
        seen: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for r in sorted(records, key=lambda r: (dated(r["years"]), r["book_id"])):
            key = (r["work"], r["kind"], r["head"], r["gloss"])
            if key in seen:
                seen[key].setdefault("copies", []).append(r["passage_id"])
            else:
                seen[key] = r
        return list(seen.values())


__all__ = ["GlossStudy"]
