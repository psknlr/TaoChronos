"""佚书辑佚 — gathering the fragments of a lost work from the books that quote it, and ordering them.

Lost works survive in quotation: 外台秘要 opens its entries with their source (小品论曰, 《深师》疗…, 千金…; 又 for "the
same source again") and closes them with a note on where the source had it (（出第十卷中千金同）: volume ten, the
same text in 千金); 医心方 and later compilations cite likewise, and any book may quote 《小品方》云….  ``fragments``
finds these attributions for a work's names, takes the attributed text up to the source note (and the entries 又
continues), strips the note but keeps its volume and parallels, merges the same fragment quoted in several books,
and orders the fragments by the volume the notes give (then by where they are quoted).  Every fragment keeps its
witnesses.  ``verify`` measures a reconstruction against a text that survives (how much of what is gathered is in
it, and how much of it is gathered) — which is how the method is tested before it is trusted on lost works.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from .base import StudyBase, han_only
from .stemma import mask_notes

NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "百": 100}
_NOTE = re.compile(r"[（(]出(?:第)?([一二三四五六七八九十百]+)卷(?:中)?([^）)]{0,20})[）)]")
_HEAD_VERBS = "论曰|论云|曰|云|疗|治|主|方|说|载|论"
_SUFFIXES = ("备急方", "要方", "方论", "方", "论", "经", "录", "集")
# where the next source begins inside a passage that packs several (医心方: …又云…《养生要集》云…; 证类本草's 附方:
# 千金方治…肘后方治…): a cited title, or a book name (not a formula: 桂枝汤方治 stays) opening a quotation
_NEXT_SOURCE = re.compile(r"《[^》]{1,14}》(?:云|曰|方|治|疗|论)?|(?:^|(?<=[。　 ]))[一-鿿]{2,5}(?<![汤散丸饮膏丹煎])(?:方|论)(?:云|曰|治|疗)")


def cn_number(s: str) -> int | None:
    """二十八 → 28, 十 → 10, 一百二 → 102."""
    total, cur = 0, 0
    for ch in s:
        v = NUM.get(ch)
        if v is None:
            return None
        if v >= 10:
            total += (cur or 1) * v
            cur = 0
        else:
            cur = v
    return total + cur or None


class FragmentStudy:
    def __init__(self, base: StudyBase) -> None:
        self.b = base
        self._start: float | None = None  # the date of the work whose fragments are gathered

    # ------------------------------------------------------------ names
    def forms(self, work: str) -> tuple[str, list[str]]:
        """The names under which a work is cited: its title and aliases (a book or an external work of the catalog),
        and the short forms without 方 / 论 / 要方 … (小品方 → 小品, 千金要方 → 千金)."""
        n = self.b.normalize
        corpus = self.b.corpus
        names = {work}
        title = work
        ext = getattr(corpus, "external", {}) or {}
        key = n(work)
        self._start = None
        for rec in list(ext.values()) + list(corpus.books.values()):
            titles = [rec.title, *getattr(rec, "aliases", [])]
            if key in {n(t) for t in titles} or getattr(rec, "id", None) == work:
                names.update(titles)
                title = rec.title
                if rec.composition is not None:
                    self._start = min(self._start if self._start is not None else 9999.0, float(rec.composition.start))
        short = set()
        for x in names:
            for suf in _SUFFIXES:
                if x.endswith(suf) and len(x) - len(suf) >= 2:
                    short.add(x[: -len(suf)])
            if x.startswith("备急") and len(x) > 4:
                short.add(x[2:])
        forms = sorted({n(x) for x in names | short if len(n(x)) >= 2}, key=len, reverse=True)
        return title, forms

    # ------------------------------------------------------------ gathering
    def collect(self, work: str, *, exclude_books: set[str] | None = None, limit: int = 20000) -> tuple[str, list[str], list[dict[str, Any]]]:
        title, forms = self.forms(work)
        if not forms:
            return title, forms, []
        alt = "|".join(map(re.escape, forms))
        head = re.compile(rf"^[《〈]?(?:{alt})[》〉]?(?:{_HEAD_VERBS}|[，：])")
        inline = re.compile(rf"《(?:{alt})》(?:云|曰|言|载)?[：:，]?|(?<![一-鿿])(?:{alt})(?:云|曰)[：:，]?")
        exclude = exclude_books or set()
        ids: set[str] = set()
        for f in forms:
            ids.update(self.b.find(f, limit=limit))
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        start = self._start
        for p in self.b.passages(sorted(ids)):
            if p.book_id in exclude or p.kind == "toc" or p.id in seen:
                continue
            book = self.b.corpus.books.get(p.book_id)
            if start is not None and book is not None and book.composition is not None and book.composition.end < start:
                continue  # a book written before the work cannot quote it (a later note in its transcription can)
            norm = self.b.normalize(p.text)
            m = head.match(norm.lstrip("　 "))
            if m:  # an entry opened by the source: it runs to the source note, and 又 continues it
                chain = [p] + [q for q in self.b.following(p, 40)]
                i = 0
                noted = False
                while i < len(chain):
                    body, used, note = self._entry(chain, i)
                    noted = noted or note is not None
                    for q in chain[i: i + used]:
                        seen.add(q.id)
                    out.append(self._fragment(body, chain[i], note, "head" if i == 0 else "continuation"))
                    i += used
                    if i >= len(chain):
                        break
                    nxt = self.b.normalize(chain[i].text).lstrip("　 ")
                    # 又 continues the source where the book says so: entries closed by a source note (外台秘要), or
                    # 又云 / 又曰 (医心方); elsewhere 又方 is only "another recipe"
                    continues = nxt.startswith(("又云", "又曰")) or (noted and nxt.startswith("又"))
                    if not continues or chain[i].locator.chapter != p.locator.chapter:
                        break
                continue
            for mm in inline.finditer(norm):
                quote = norm[mm.end():]
                stop = re.search(r"[。」』”]", quote)
                quote = quote[: stop.start() + 1] if stop else quote[:200]
                if len(han_only(quote)[0]) >= 12:
                    out.append(self._fragment(quote, p, None, "inline"))
        return title, forms, [f for f in out if len(f["han"]) >= 12]  # shorter ones cannot be told from a coincidence

    def _entry(self, chain: list[Any], i: int) -> tuple[str, int, re.Match[str] | None]:
        """The text of the entry starting at chain[i]: passages up to (and with) the one carrying a source note."""
        parts = []
        for k in range(i, min(len(chain), i + 8)):
            text = self.b.normalize(chain[k].text)
            if k > i and (text.lstrip("　 ").startswith("又") or re.match(r"^[《〈]?[一-鿿]{2,6}?[》〉]?(?:论曰|疗|治)", text)):
                return "".join(parts), k - i, None
            note = _NOTE.search(text)
            parts.append(text[: note.start()] if note else text)
            if note:
                return "".join(parts), k - i + 1, note
        return "".join(parts), max(1, min(len(chain), i + 8) - i), None

    def _fragment(self, body: str, p: Any, note: re.Match[str] | None, kind: str) -> dict[str, Any]:
        nxt = next((m for m in _NEXT_SOURCE.finditer(body) if m.start() >= 6), None)
        if nxt is not None:  # the fragment ends where another source begins
            body = body[: nxt.start()]
        han, _ = han_only(mask_notes(body))
        book = self.b.corpus.books.get(p.book_id)
        return {"han": han, "text": body.strip()[:400], "book_id": p.book_id, "title": book.title if book else p.book_id,
                "passage_id": p.id, "locator": self.b.locator(p), "chapter": p.locator.chapter or "", "kind": kind,
                "volume": cn_number(note.group(1)) if note else None,
                "parallels": [x for x in re.split(r"[、，,]", re.sub(r"同$", "", note.group(2).strip())) if x] if note and note.group(2).strip() else []}

    # ------------------------------------------------------------ the reconstruction
    def run(self, work: str, *, exclude_books: list[str] | None = None, same: float = 0.5) -> dict[str, Any]:
        own = set(exclude_books or [])
        title, forms, raw = self.collect(work, exclude_books=own)
        clusters: list[dict[str, Any]] = []
        grams_of = [_grams(f["han"]) for f in raw]
        for f, g in zip(raw, grams_of):  # the same fragment quoted in several books is one fragment
            home = next((c for c in clusters if _overlap(g, c["grams"]) >= same), None)
            if home is None:
                clusters.append({"grams": set(g), "members": [f]})
            else:
                home["members"].append(f)
                home["grams"] |= g
        fragments = []
        for c in clusters:
            ms = c["members"]
            best = max(ms, key=lambda f: (len(f["han"]), f["kind"] == "head"))
            vols = sorted({f["volume"] for f in ms if f["volume"]})
            fragments.append({"text": best["text"][:120], "characters": len(best["han"]), "volume": vols[0] if vols else None,
                              "volumes": vols, "topic": best["chapter"], "kinds": sorted({f["kind"] for f in ms}),
                              "parallels": sorted({x for f in ms for x in f["parallels"]}),
                              "witnesses": [{k: f[k] for k in ("title", "passage_id", "locator")} for f in ms[:8]],
                              "_han": best["han"]})
        fragments.sort(key=lambda f: (f["volume"] if f["volume"] is not None else 10 ** 6, f["witnesses"][0]["passage_id"]))
        by_volume: dict[int, int] = defaultdict(int)
        for f in fragments:
            if f["volume"] is not None:
                by_volume[f["volume"]] += 1
        quoting: dict[str, int] = defaultdict(int)
        for f in raw:
            quoting[f["title"]] += 1
        return {
            "work": title, "forms": forms, "fragments": fragments, "count": len(fragments),
            "characters": sum(f["characters"] for f in fragments), "quotations": len(raw),
            "by_volume": dict(sorted(by_volume.items())), "quoted_in": dict(sorted(quoting.items(), key=lambda kv: -kv[1])),
            "note": "fragments: text attributed to the work at the head of an entry (to the source note, with the entries 又 "
                    "continues) or quoted inline (《…》云); the same fragment quoted in several books merged; ordered by the "
                    "volume the source notes give, then by where they are quoted.  A reconstruction, to be checked against "
                    "the witnesses it lists",
        }

    def verify(self, reconstruction: dict[str, Any], books: list[str], *, k: int = 6, found: float = 0.3) -> dict[str, Any]:
        """A reconstruction against a surviving text (all its witnesses together): the share of fragments with at
        least ``found`` of their k-grams in it (precision — quotations abridge, and the text that survives may be a
        later recension: 外台 quotes the Tang 千金, the extant one is the Song edition) and the share of its characters
        the fragments cover (coverage)."""
        text = "".join(han_only(self.b.normalize(mask_notes(t)))[0] for bid in books for t in self.b.book_texts(bid))
        where: dict[str, list[int]] = defaultdict(list)
        for i in range(len(text) - k + 1):
            where[text[i: i + k]].append(i)
        covered = bytearray(len(text))
        ok = 0
        per_book: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for f in reconstruction["fragments"]:
            grams = [f["_han"][i: i + k] for i in range(len(f["_han"]) - k + 1)]
            hits = [g for g in grams if g in where]
            good = bool(grams) and len(hits) / len(grams) >= found
            for title in {w["title"] for w in f["witnesses"]}:
                per_book[title][0] += 1
                per_book[title][1] += good
            if good:
                ok += 1
                for g in hits:
                    for i in where[g][:3]:
                        covered[i: i + k] = b"\x01" * k
        n = len(reconstruction["fragments"])
        reliability = sorted(({"book": b, "fragments": v[0], "verified": v[1], "precision": round(v[1] / v[0], 3)}
                              for b, v in per_book.items() if v[0] >= 10), key=lambda r: (-r["precision"], -r["fragments"]))
        return {"fragments": n, "verified": ok, "precision": round(ok / n, 4) if n else None,
                "coverage": round(sum(covered) / len(text), 4) if text else None, "characters": len(text),
                "by_quoting_book": reliability}


def _grams(han: str) -> set[str]:
    return {han[i: i + 3] for i in range(len(han) - 2)}


def _overlap(a: set[str], b: set[str]) -> float:
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


__all__ = ["FragmentStudy", "cn_number"]
