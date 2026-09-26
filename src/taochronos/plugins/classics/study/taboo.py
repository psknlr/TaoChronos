"""避讳断代 — dating a witness by the taboo characters it avoids.

For every rule of ``domains/classics/taboo.yaml`` the verbatim text of a book is counted for the original forms and
their substitutes (玄参 / 元参, 陶弘景 / 陶宏景, 薯蓣 / 山药, and formula names in 丸 / 圆).  A witness that writes
the substitute and (nearly) never the original was copied or printed after the taboo came into force: its *edition*
is not earlier than that year, whatever the date of the work.  When the date of the work is earlier, the substitution
is an editor's change (传本改字) — the typical case of the Siku copies, where Song and Tang works carry Qing taboos.

Several dynasties avoided the same character (玄: 宋 1012, 清 1662), so the floor a substitution gives is the earliest
rule that explains it; another rule (弘 → 宏, only Qing) can raise it.  These are indications to weigh, not proofs:
modern transcribers sometimes restore the original characters, and a substitute can be the ordinary word.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from .base import StudyBase

_FORMULA_END = re.compile(r"([一-鿿]{2,6})(丸|圆|圓)(?=方|[：:，,。、\s　（(]|治|主|服|each)")


class TabooStudy:
    def __init__(self, base: StudyBase) -> None:
        self.b = base
        self.rules = list(base.data("taboo.yaml").get("rules") or [])

    def _formula_names(self) -> set[str]:
        return {self.b.normalize(e.term) for e in self.b.pack.lexicon.by_category("formula")}

    def count(self, texts: list[str]) -> dict[str, dict[str, Any]]:
        """Original and substitute counts per rule over the verbatim texts."""
        joined = "\n".join(texts)
        simplified = joined  # the pairs are written in both scripts: count each form as given and in its normal form
        out: dict[str, dict[str, Any]] = {}
        formulas = None
        for rule in self.rules:
            orig = subs = 0
            examples: dict[str, int] = defaultdict(int)
            for a, bsub in rule.get("pairs") or []:
                for form, is_sub in ((a, False), (bsub, True)):
                    n = sum(simplified.count(v) for v in self._spellings(form))
                    if n:
                        examples[form] += n
                    if is_sub:
                        subs += n
                    else:
                        orig += n
            if rule.get("formula_suffix"):
                if formulas is None:
                    formulas = self._formula_names()
                for m in _FORMULA_END.finditer(joined):
                    stem = self.b.normalize(m.group(1))
                    if stem + "丸" not in formulas and stem + "圆" not in formulas:
                        continue
                    if m.group(2) == "丸":
                        orig += 1
                        examples["…丸"] += 1
                    else:
                        subs += 1
                        examples["…圆"] += 1
            out[rule["id"]] = {"original": orig, "substitute": subs, "examples": dict(examples)}
        return out

    def _spellings(self, form: str) -> list[str]:
        """The form as written in traditional and simplified script (the counts are made on the verbatim text)."""
        forms = {form}
        t2s = getattr(self.b.pack.script, "map", {}) or {}
        s2t = {v: k for k, v in t2s.items() if len(k) == 1 and len(v) == 1}
        forms.add("".join(t2s.get(ch, ch) for ch in form))
        forms.add("".join(s2t.get(ch, ch) for ch in form))
        return sorted(f for f in forms if f)

    def verdicts(self, counts: dict[str, dict[str, Any]], composition: tuple[float, float] | None) -> dict[str, Any]:
        rows = []
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for rule in self.rules:
            c = counts[rule["id"]]
            total = c["original"] + c["substitute"]
            ratio = c["substitute"] / total if total else None
            if total == 0:
                verdict = "无证据"
            elif c["substitute"] >= 3 and ratio >= 0.8:
                verdict = "避讳"
            elif c["original"] >= 3 and ratio is not None and ratio <= 0.2:
                verdict = "未避"
            else:
                verdict = "兼用"
            row = {"rule": rule["id"], "dynasty": rule["dynasty"], "ruler": rule["ruler"], "from": rule["from"],
                   "char": rule["char"], "original": c["original"], "substitute": c["substitute"],
                   "ratio": round(ratio, 3) if ratio is not None else None, "verdict": verdict, "examples": c["examples"],
                   "note": rule.get("note", "")}
            rows.append(row)
            if verdict == "避讳":
                groups[rule["char"]].append(row)
        floors = {char: min(r["from"] for r in rs) for char, rs in groups.items()}
        floor = max(floors.values()) if floors else None
        explain = ""
        if floor is not None:
            decisive = [r for rs in groups.values() for r in rs if r["from"] == floor]
            explain = "；".join(f"{r['ruler']}讳（{r['char']}，{r['from']}年起）" for r in decisive)
        edited = bool(floor is not None and composition and composition[1] < floor)
        return {"rules": rows, "edition_floor": floor, "decisive": explain, "edited_after_composition": edited}

    def profile(self, book_id: str) -> dict[str, Any]:
        b = self.b
        book = b.corpus.books.get(book_id)
        if book is None:
            raise KeyError(f"unknown book {book_id}")
        texts = list(b.book_texts(book_id))
        comp = (book.composition.start, book.composition.end) if book.composition else None
        v = self.verdicts(self.count(texts), comp)
        return {"book_id": book_id, "title": book.title, "dynasty": book.dynasty, "composition": list(comp) if comp else None,
                "source": b.corpus.sources.get(book_id) if hasattr(b.corpus, "sources") else None,
                "characters": sum(len(t) for t in texts), **v}

    def survey(self, book_ids: list[str] | None = None, *, min_chars: int = 20000) -> dict[str, Any]:
        """Profiles of many books, with the witnesses whose edition postdates their composition."""
        ids = book_ids or sorted(self.b.corpus.books)
        rows = []
        for bid in ids:
            prof = self.profile(bid)
            if prof["characters"] < min_chars:
                continue
            rows.append({k: prof[k] for k in ("book_id", "title", "dynasty", "composition", "source", "characters",
                                               "edition_floor", "decisive", "edited_after_composition")}
                        | {"avoided": [r["rule"] for r in prof["rules"] if r["verdict"] == "避讳"],
                           "not_avoided": [r["rule"] for r in prof["rules"] if r["verdict"] == "未避"]})
        by_source: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for r in rows:
            by_source[r["source"] or "?"]["books"] += 1
            if r["edited_after_composition"]:
                by_source[r["source"] or "?"]["edited"] += 1
        return {"books": rows, "by_source": {k: dict(v) for k, v in by_source.items()},
                "rules": [{k: r[k] for k in ("id", "dynasty", "ruler", "from", "char")} for r in self.rules]}


__all__ = ["TabooStudy"]
