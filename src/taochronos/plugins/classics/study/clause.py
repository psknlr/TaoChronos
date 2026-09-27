"""条文结构 — the parts of a clause: condition, disease, findings, pulse, pattern, principle, formula, composition,
preparation, administration, modification, contraindication, prognosis.

The clauses of the 伤寒论 and of the books written on its model run in a recognisable order: under a condition (若,
伤寒二三日, 发汗后) a disease shows findings and a pulse, is named (名为中风), and is treated (当…, …汤主之) with a
formula whose drugs, doses, preparation and administration follow, with its 加减 and what becomes of the patient.
``study clause`` cuts a clause at its punctuation (白文 is punctuated first by the 句读 model, marks only), gives each
piece a role by the rules of ``clause.yaml`` — the first that applies — or by what the lexicon finds in it, and lists
what it contains: the findings, the pulse, the formula, the drugs with their doses.  With a work, it reads the
clauses of its main text and counts the forms they take.

The roles are read from wording and the lexicon; a piece can do two things at once (脉浮而紧者，名为伤寒 names a
pattern from a pulse), and the role given is the first rule's.  The order of the roles is noted, not enforced.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from ..segment import DOSE
from .base import StudyBase
from .punctuation import has_marks

_PIECE = re.compile(r"[^，。；：！？、,;:!?　 ]+[，。；：！？、,;:!?]?")
_NOTE = re.compile(r"（[^（）]{0,300}）|\([^()]{0,300}\)")
LABELS = {"condition": "前提", "disease": "病", "findings": "症", "pulse": "脉", "pattern": "证·病机", "principle": "治则",
          "contraindication": "禁忌", "formula": "方", "composition": "组成", "preparation": "煎制", "administration": "服法",
          "modification": "加减", "prognosis": "预后", "other": "其他"}


class ClauseStructure:
    def __init__(self, base: StudyBase, punctuation: Any) -> None:
        self.b = base
        self.punct = punctuation
        data = base.data("clause.yaml")
        self.rules = [(role, [re.compile(p) for p in patterns]) for role, patterns in (data.get("roles") or {}).items()]
        self.lexicon_roles = {role: set(cats) for role, cats in (data.get("lexicon") or {}).items()}
        self.order = list(data.get("order") or [])

    # ------------------------------------------------------------ one clause
    def pieces(self, text: str) -> tuple[list[str], bool]:
        """The pieces of a clause (its punctuation's cuts); 白文 is punctuated by the model first."""
        punctuated = False
        if not has_marks(text) and len(re.findall(r"[一-鿿]", text)) >= 8:
            text = self.punct.model().punctuate(text, self.b.normalize)["text"]
            punctuated = True
        return [m.group(0) for m in _PIECE.finditer(text) if re.search(r"[㐀-鿿]", m.group(0))], punctuated

    def role(self, piece: str) -> tuple[str, str]:
        """(role, why) of one piece."""
        norm = self.b.normalize(_NOTE.sub("", piece)).strip("，。；：！？、,;:!? 　")
        mentions = self.b.pack.lexicon.match(norm, include_weak=False)
        herbs = [m for m in mentions if m.category == "herb"]
        for role, patterns in self.rules:
            if role not in ("composition", "preparation", "modification"):
                continue  # a drug's processing (去皮, 炙), how it is made (去滓) and 加减 (去半夏) before the drugs they name
            for rx in patterns:
                if rx.search(norm):
                    return role, rx.pattern
        if herbs and DOSE.search(norm) and not re.search(r"主之|[宜与]", norm):
            return "composition", "a drug with its dose"
        for role, patterns in self.rules:
            for rx in patterns:
                if rx.search(norm):
                    return role, rx.pattern
        cats = Counter(m.category for m in mentions)
        for role in ("pulse", "findings", "pattern", "principle", "disease"):
            if cats and set(cats) & self.lexicon_roles.get(role, set()):
                return role, "lexicon: " + "、".join(sorted(set(cats) & self.lexicon_roles[role]))
        if herbs and len(herbs) * 2 >= len(re.findall(r"[一-鿿]", norm)) / 2:
            return "composition", "drugs"
        return "other", ""

    def run(self, text: str | None = None, passage_id: str | None = None) -> dict[str, Any]:
        passage = None
        if passage_id:
            found = self.b.passages([passage_id])
            if not found:
                raise KeyError(f"no passage {passage_id}")
            passage = found[0]
            text = passage.text
        if not text or not text.strip():
            raise ValueError("give a clause or a passage id")
        pieces, punctuated = self.pieces(text)
        rows: list[dict[str, Any]] = []
        for piece in pieces:
            role, why = self.role(piece)
            if role == "composition" and rows and rows[-1]["role"] == "modification" and not rows[-1]["text"].endswith(("。", "；")):
                role, why = "modification", "the drugs of the 加减 before it"
            norm = self.b.normalize(_NOTE.sub("", piece))
            terms = [(m.entry.term, m.category) for m in self.b.pack.lexicon.match(norm, include_weak=False)]
            rows.append({"text": piece, "role": role, "label": LABELS[role], "rule": why,
                         "terms": [{"term": t, "category": c} for t, c in dict.fromkeys(terms)]})
        sequence = [r["role"] for r in rows]
        collapsed = [r for k, r in enumerate(sequence) if k == 0 or sequence[k - 1] != r]
        rank = {r: k for k, r in enumerate(self.order)}
        main = [r for r in collapsed if r in rank and r not in ("condition", "findings", "pulse")]  # 若… opens sub-cases anywhere
        out_of_order = [f"{LABELS[a]}→{LABELS[b]}" for a, b in zip(main, main[1:]) if rank[b] < rank[a]]

        def of(role: str, cats: tuple[str, ...]) -> list[str]:
            return list(dict.fromkeys(t["term"] for r in rows if r["role"] == role or not role for t in r["terms"] if t["category"] in cats))

        out: dict[str, Any] = {
            "text": text[:2000], "punctuated_by_model": punctuated, "pieces": rows,
            "form": "→".join(LABELS[r] for r in collapsed), "roles": dict(Counter(sequence)), "out_of_order": out_of_order,
            "findings": of("", ("symptom", "sign", "tongue")), "pulse": of("", ("pulse",)),
            "diseases": of("", ("disease",)), "formulas": of("", ("formula",)),
            "drugs": [{"text": r["text"].strip("，。；：、 　"), "herbs": [t["term"] for t in r["terms"] if t["category"] == "herb"]}
                      for r in rows if r["role"] == "composition"],
            "note": "roles read from wording (clause.yaml) and the lexicon, the first rule that applies; check the pieces",
        }
        if passage is not None:
            out["passage"] = self.b.witness(passage)
        return out

    # ------------------------------------------------------------ a work
    def profile(self, work: str, *, passages: int = 800) -> dict[str, Any]:
        """The forms the clauses of a work take: the role sequences most common in its main text."""
        ids = self._work_passages(work, passages)
        forms: Counter = Counter()
        roles: Counter = Counter()
        examples: dict[str, str] = {}
        for p in self.b.passages(ids):
            if p.kind not in ("text", "formula") or len(p.text) < 6:
                continue
            res = self.run(p.text)
            forms[res["form"]] += 1
            roles.update(res["roles"])
            examples.setdefault(res["form"], p.id)
        total = sum(forms.values()) or 1
        return {"work": work, "clauses": sum(forms.values()),
                "forms": [{"form": f, "clauses": n, "share": round(n / total, 4), "example": examples[f]} for f, n in forms.most_common(25)],
                "roles": {LABELS[r]: n for r, n in roles.most_common()}}

    def _work_passages(self, work: str, limit: int) -> list[str]:
        books = [bid for bid, bk in self.b.corpus.books.items() if (bk.work or bid) == work or bid == work]
        if not books:
            norm = self.b.normalize(work)
            books = [bid for bid, bk in self.b.corpus.books.items() if self.b.normalize(bk.title) == norm]
        if not books:
            raise ValueError(f"no work or book matches {work!r}")
        store = getattr(self.b.corpus, "store", None)
        if store is not None:  # the witness with the most main text stands for the work
            with store.lock:
                sizes = {bid: store.db.execute("SELECT COALESCE(SUM(LENGTH(text)), 0) FROM passages WHERE book_id=? AND "
                                               "layer='正文'", (bid,)).fetchone()[0] for bid in books}
                best = max(books, key=lambda b: (sizes[b], b))
                return [r[0] for r in store.db.execute(
                    "SELECT id FROM passages WHERE book_id=? AND layer='正文' AND kind IN ('text','formula') ORDER BY rid LIMIT ?",
                    (best, limit))]
        best = max(books, key=lambda b: (sum(len(p.text) for p in self.b.corpus.passages(book_ids=[b])), b))
        return [p.id for p in self.b.corpus.passages(book_ids=[best])][:limit]


__all__ = ["LABELS", "ClauseStructure"]
