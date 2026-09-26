"""学习 — study cards and reading paths made from the verbatim classics.

* **学习卡片** (cloze cards, exportable to Anki): 方证 — a clause of the classics with its formula blanked
  (「……者，〔　　〕主之」); 组成 — the composition and preparation of a formula from its earliest witness, with its
  方歌; 药性 — the flavour, nature, channels of a drug from the 本经 and from a late materia medica; 经文 — the
  earliest attestations of a term with the term blanked.  Every card carries its source and passage id.
* **阅读门径** (a reading path for a topic): the works where the topic first appears (源头经典), the works of each
  period that discuss it most densely (历代发挥), the books devoted to it (专书), the case records that show it in
  practice (临证医案), and the Republican works that close the tradition (近代) — each with the reason it is there.
"""

from __future__ import annotations

import re
from typing import Any

from .base import StudyBase, dated

BLANK = "〔　　〕"
_PRESCRIBE = re.compile(r"(主之|宜服|宜用|宜|可与|与之|服之)")


class Learning:
    def __init__(self, base: StudyBase, formulas: Any, herbs: Any, terms: Any, network: Any) -> None:
        self.b = base
        self.formulas = formulas
        self.herbs = herbs
        self.terms = terms
        self.network = network

    # ------------------------------------------------------------ cards
    def book_by_title(self, title: str) -> list[str]:
        norm = self.b.normalize
        key = norm(title)
        exact = [bk.id for bk in self.b.corpus.books.values() if norm(bk.title) == key or key in {norm(a) for a in bk.aliases}]
        if exact or title in self.b.corpus.books:
            return exact or [title]
        return [bk.id for bk in self.b.corpus.books.values() if key in norm(bk.title)]

    def clause_cards(self, book: str, limit: int = 60) -> list[dict[str, Any]]:
        """方证 cards: clauses prescribing a formula, the formula blanked."""
        b = self.b
        ids = self.book_by_title(book)
        if not ids:
            return []
        bid = sorted(ids, key=lambda i: ((b.corpus.books[i].composition.start if b.corpus.books[i].composition else 9999),
                                         len(b.corpus.books[i].title)))[0]
        lex = b.pack.lexicon
        cards: list[dict[str, Any]] = []
        seen: set[str] = set()
        for p in b.corpus.passages(book_ids=[bid]):
            if p.kind in ("toc", "preface"):
                continue
            norm = b.normalize(p.text)
            for sent in re.finditer(r"[^。！？]{6,120}[。！？]", norm):
                s = sent.group(0)
                for m in lex.match(s):
                    if m.category != "formula" or not _PRESCRIBE.match(s, m.end) and not re.search(r"(宜|与|可与)$", s[: m.start]):
                        continue
                    raw = p.text[sent.start(): sent.end()]
                    if raw in seen:
                        break
                    seen.add(raw)
                    front = raw[: m.start] + BLANK + raw[m.end:]
                    cards.append({"type": "方证", "front": front, "back": raw[m.start: m.end],
                                  "source": b.locator(p), "passage_id": p.id,
                                  "tags": ["方证", b.book_title(bid)]})
                    break
                if len(cards) >= limit:
                    return cards
        return cards

    def formula_cards(self, names: list[str]) -> list[dict[str, Any]]:
        cards = []
        for name in names:
            res = self.formulas.run(name, other_names=False, max_passages=3000)
            w = res.get("earliest")
            if not w:
                continue
            items = "、".join(f"{i['surface']}{i['dose']}" + (f"（{i['processing']}）" if i["processing"] else "") for i in w["ingredients"])
            back = f"{items}。" + (f"{w['preparation']}" if w["preparation"] else "")
            song = max(res["songs"], key=lambda x: (x.get("score", 0) + 0.25 * len(re.findall(r"[，。；！？]", re.sub(r"（[^（）]*）", "", x["quote"]))),
                                                    tuple(-v for v in dated(x["years"]))))["quote"] if res.get("songs") else ""
            cards.append({"type": "组成", "front": f"{name}（出{w['locator']}）的组成与用法？",
                          "back": back + (f"\n方歌：{song}" if song else ""), "source": w["locator"], "passage_id": w["passage_id"],
                          "tags": ["方剂", name]})
        return cards

    def herb_cards(self, names: list[str]) -> list[dict[str, Any]]:
        cards = []
        for name in names:
            res = self.herbs.run(name)
            rows = res["entries"]
            if not rows:
                continue
            # the earliest entry, and the latest one that says most (归经 and 升降 are later doctrines)
            later = [r for r in rows[1:] if (r["years"] or [0])[0] >= 1100] or rows[1:]
            richest = max(later, key=lambda r: (bool(r["channels"]), sum(bool(r[k]) for k in ("flavor", "nature", "toxicity", "direction")),
                                                 (r["years"] or [0])[0]), default=None)
            picks = [rows[0]] + ([richest] if richest else [])
            lines = []
            for r in picks:
                props = "，".join(x for x in (f"味{r['flavor']}" if r["flavor"] else "", r["nature"], r["toxicity"],
                                               ("入" + "、".join(r["channels"])) if r["channels"] else "", r["direction"]) if x)
                lines.append(f"{props}（{r['locator']}）")
            cards.append({"type": "药性", "front": f"{name}的性味、毒性与归经？（本经与后世本草）", "back": "\n".join(lines),
                          "source": picks[0]["locator"], "passage_id": picks[0]["passage_id"], "tags": ["本草", name]})
        return cards

    def term_cards(self, term: str, limit: int = 8) -> list[dict[str, Any]]:
        res = self.terms.run(term, sample_per_period=50)
        keys = [self.b.normalize(f["form"]) for f in res["term"]["forms"]]
        cards = []
        for w in res["earliest"][:limit]:
            quote = w["quote"]
            norm = self.b.normalize(quote)
            pos = next((norm.find(k) for k in keys if norm.find(k) >= 0), -1)
            if pos < 0:
                continue
            k = next(k for k in keys if norm.find(k) == pos)
            lead = len(quote) - len(quote.lstrip("）)」』，。；、：　 "))
            cards.append({"type": "经文", "front": quote[lead:pos] + BLANK + quote[pos + len(k):], "back": quote[pos: pos + len(k)],
                          "source": w["locator"], "passage_id": w["passage_id"], "tags": ["经文", term]})
        return cards

    # ------------------------------------------------------------ reading path
    def reading_path(self, topic: str) -> dict[str, Any]:
        b = self.b
        res = self.terms.run(topic, sample_per_period=60)
        stages: list[dict[str, Any]] = []
        used: set[str] = set()

        def book_row(bid: str, why: str) -> dict[str, Any] | None:
            book = b.corpus.books.get(bid)
            work = (getattr(book, "work", None) or bid) if book is not None else bid
            if book is None or work in used:
                return None  # one row per work, whichever copy comes first
            used.add(work)
            return {"book_id": bid, "title": book.title, "authors": list(book.authors), "dynasty": book.dynasty,
                    "years": [book.composition.start, book.composition.end] if book.composition else None,
                    "category": book.category, "why": why}

        sources = [r for r in (book_row(w["book_id"], f"首见之一：{w['quote'][:40]}") for w in res["earliest"][:5]) if r]
        stages.append({"stage": "源头经典", "note": "该主题最早出现的著作，先读原文，再读注本", "books": sources})
        dense = [r for r in (book_row(d["book_id"], f"论述最密：{d['passages']}段，占全书{d['share']:.1%}") for d in res["dense_books"][:8]) if r]
        dense.sort(key=lambda r: dated(r["years"]))
        stages.append({"stage": "历代发挥", "note": "按年代读各期集中论述该主题的著作", "books": dense})
        key = b.normalize(topic)
        special = [r for r in (book_row(bk.id, "以该主题名书") for bk in sorted(b.corpus.books.values(), key=lambda x: (x.composition.start if x.composition else 9999))
                               if key and key in b.normalize(bk.title)) if r][:8]
        if special:
            stages.append({"stage": "专书", "note": "以该主题命名的专门著作", "books": special})
        cases = []
        for d in res["dense_books"][:40]:
            if d["category"] == "医案":
                row = book_row(d["book_id"], f"医案中的运用：{d['passages']}段")
                if row:
                    cases.append(row)
        if cases:
            stages.append({"stage": "临证医案", "note": "看历代医家如何在病案中运用", "books": cases[:5]})
        modern = [r for r in (book_row(d["book_id"], f"近代论述：{d['passages']}段") for d in res["dense_books"][:40]
                              if d["category"] == "近代" or ((d["years"] or [0])[0] >= 1912)) if r][:4]
        if modern:
            stages.append({"stage": "近代汇通", "note": "民国时期的总结与中西汇通之论", "books": modern})
        return {"topic": topic, "stages": stages, "periods": res["periods"], "trend": res["trend"],
                "senses": res["senses"]}


def anki_tsv(cards: list[dict[str, Any]]) -> str:
    """Anki import format: front, back (source appended), tags — one card per line."""
    def clean(s: str) -> str:
        return s.replace("\t", " ").replace("\n", "<br>")

    lines = [f"{clean(c['front'])}\t{clean(c['back'])}<br><small>{clean(c['source'])} · {c['passage_id']}</small>\t"
             + " ".join(t.replace(' ', '_') for t in c.get("tags", [])) for c in cards]
    return "#separator:tab\n#html:true\n#tags column:3\n" + "\n".join(lines) + "\n"


__all__ = ["Learning", "anki_tsv"]
