"""文本地层 — the layers of a classic, the dates its chapters can bear, and who wrote a text.

``layers`` cuts the base witness of a work into chapters (long chapters into parts of about ``chunk`` characters),
profiles each by its function characters, and finds layers, change points in reading order and the chapters that
stand apart (``science.stratigraphy``).  ``dating`` collects, chapter by chapter, the evidence of date: the works a
chapter cites in its main text (not in the notes), vocabulary that the rest of the corpus attests only long after the
work's date, and the taboo characters of the witness.  ``authorship`` measures a text against the works of candidate
authors.  Style says *that* chapters differ, the dating evidence *when* they can have been written; neither alone
proves an addition.
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from typing import Any

from ....science.stratigraphy import (
    FUNCTION_CHARS,
    attribute,
    boundaries,
    change_points,
    distinctive_features,
    interval,
    layers,
    most_frequent,
    outliers,
    profile,
    zscores,
)
from ..citations import CitationExtractor
from .base import StudyBase, dated, han_only
from .stemma import _EXCLUDED_KINDS, _FRONT_LAYER, mask_notes


_VOLUME_NAME = re.compile(r"^卷[之第]?[一二三四五六七八九十百〇零\d]+[上中下]?$")
_CLAUSE_NAME = re.compile(r"^第?[一二三四五六七八九十百〇零\d]+[条條]?$")


def unit_name(loc: dict[str, Any]) -> str:
    """The named unit of a text (篇): the chapter field, unless it only numbers a volume (卷第二, where 笈成 puts the 篇
    in the section field); a section that only numbers a clause (第12条) is not a unit."""
    ch = (loc.get("chapter") or "").strip()
    sec = (loc.get("section") or "").strip()
    if ch and not _VOLUME_NAME.match(ch):
        return ch
    if sec and not _CLAUSE_NAME.match(sec):
        return sec
    return ch or (loc.get("volume") or "").strip() or "（无篇名）"


class StratigraphyStudy:
    def __init__(self, base: StudyBase, stemma: Any, taboo: Any) -> None:
        self.b = base
        self.stemma = stemma
        self.taboo = taboo
        self._extractor: CitationExtractor | None = None
        self._first: dict[tuple[str, frozenset[str], float], dict[str, Any] | None] = {}

    # ------------------------------------------------------------ the text
    def chapters(self, ids: list[str]) -> list[dict[str, Any]]:
        """The main text of a witness chapter by chapter: normalised Han characters (notes left out) and passages."""
        out: list[dict[str, Any]] = []
        store = getattr(self.b.corpus, "store", None)
        for bid in ids:
            if store is not None:
                with store.lock:
                    rows = store.db.execute("SELECT id, locator, layer, kind, text FROM passages WHERE book_id=? ORDER BY seq",
                                            (bid,)).fetchall()
                items = [(pid, json.loads(loc), layer or "", kind, text) for pid, loc, layer, kind, text in rows]
            else:
                items = [(p.id, {"volume": p.locator.volume, "chapter": p.locator.chapter, "section": p.locator.section}, "",
                          p.kind, p.text) for p in self.b.corpus.passages(book_ids=[bid])]
            for pid, loc, layer, kind, text in items:
                if kind in _EXCLUDED_KINDS or _FRONT_LAYER.match(layer):
                    continue
                name = unit_name(loc)
                han, _ = han_only(self.b.normalize(mask_notes(text)))
                if not han:
                    continue
                if out and out[-1]["chapter"] == name and out[-1]["book_id"] == bid:
                    out[-1]["text"] += han
                    out[-1]["passages"].append(pid)
                else:
                    out.append({"chapter": name, "book_id": bid, "text": han, "passages": [pid]})
        for c in out:
            c["chars"] = len(c["text"])
        return out

    @staticmethod
    def segments(chapters: list[dict[str, Any]], *, chunk: int = 800, min_chars: int = 200) -> list[dict[str, Any]]:
        """Chapters cut into parts of about ``chunk`` characters; parts shorter than ``min_chars`` are left out."""
        out = []
        for ci, c in enumerate(chapters):
            n = c["chars"]
            parts = max(1, round(n / chunk))
            size = math.ceil(n / parts)
            for k in range(parts):
                text = c["text"][k * size: (k + 1) * size]
                if len(text) >= min_chars:
                    out.append({"chapter_index": ci, "chapter": c["chapter"], "part": f"{k + 1}/{parts}", "text": text,
                                "chars": len(text)})
        return out

    def _witness(self, work: str | None, books: list[str] | None) -> tuple[list[str], Any]:
        ids = self.stemma.base_witness(work, books)
        return ids, self.b.corpus.books.get(ids[0])

    # ------------------------------------------------------------ layers
    def layers(self, work: str | None = None, *, books: list[str] | None = None, k: int = 2, features: str = "frequent",
               chunk: int = 800, min_chars: int = 200, permutations: int = 39) -> dict[str, Any]:
        ids, book = self._witness(work, books)
        chapters = self.chapters(ids)
        segs = self.segments(chapters, chunk=chunk, min_chars=min_chars)
        if len(segs) < 4:
            raise ValueError("fewer than four segments long enough to profile")
        if features == "function":  # the function characters the work uses at least once per 1 000 characters
            whole = profile("".join(s["text"] for s in segs), FUNCTION_CHARS)
            names = [f for f, v in zip(FUNCTION_CHARS, whole) if v >= 1.0]
        else:
            names = most_frequent((s["text"] for s in segs), 100)
        raw = [profile(s["text"], names, root=True) for s in segs]
        z, _, _ = zscores(raw)
        weights = [float(s["chars"]) for s in segs]
        res = layers(z, weights, k=k, permutations=permutations)
        dist = outliers(z, weights)
        cps = change_points(z)
        for i, s in enumerate(segs):
            lab = res["labels"][i]
            s.update({"i": i, "layer": lab, "p": round(res["memberships"][i][lab], 3),
                      "memberships": [round(x, 3) for x in res["memberships"][i]], **dist[i]})
            del s["text"]
        by_chapter: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for s in segs:
            by_chapter[s["chapter_index"]].append(s)
        chapter_rows = []
        for ci, ss in sorted(by_chapter.items()):
            mass: dict[int, float] = defaultdict(float)
            for s in ss:
                mass[s["layer"]] += s["chars"]
            lab = max(mass, key=lambda x: (mass[x], -x))
            chapter_rows.append({"chapter": chapters[ci]["chapter"], "chars": chapters[ci]["chars"], "segments": len(ss), "layer": lab,
                                 "p": round(sum(s["memberships"][lab] * s["chars"] for s in ss) / sum(s["chars"] for s in ss), 3),
                                 "delta": round(sum(s["delta"] * s["chars"] for s in ss) / sum(s["chars"] for s in ss), 4),
                                 "z": max(s["z"] for s in ss)})
        total = sum(weights)
        layer_rows = []
        for lab in range(res["k"]):
            members = [c for c in chapter_rows if c["layer"] == lab]
            layer_rows.append({"layer": lab, "chars": int(sum(s["chars"] for s in segs if s["layer"] == lab)),
                               "share": round(sum(s["chars"] for s in segs if s["layer"] == lab) / total, 3),
                               "chapters": [c["chapter"] for c in members],
                               "distinctive": distinctive_features(z, res["labels"], names, lab) if res["k"] > 1 else []})
        return {
            "work": book.title if book else work, "witness": ids, "features": features, "feature_names": names,
            "k": res["k"], "supported": res["supported"], "p": res["p"], "r2": res["r2"], "null_r2": res.get("null_r2"),
            "silhouette": res.get("silhouette"), "layers": layer_rows,
            "chapters": chapter_rows, "segments": segs,
            "change_points": [{**cp, "before": segs[cp["at"] - 1]["chapter"], "after": segs[cp["at"]]["chapter"]} for cp in cps],
            "layer_boundaries": [{"at": b, "before": segs[b - 1]["chapter"], "after": segs[b]["chapter"],
                                  "from_layer": segs[b - 1]["layer"], "to_layer": segs[b]["layer"]}
                                 for b in boundaries([s_["layer"] for s_ in segs])] if res["k"] > 1 else [],
            "outliers": sorted((c for c in chapter_rows if c["z"] >= 1.5), key=lambda c: -c["z"]),
            "note": "style profiles: √frequency of the 100 most frequent characters (features=frequent; topic shows in "
                    "them too) or of the function characters (features=function); layers by k-means, the split tested "
                    "against feature-shuffled profiles (p), membership probabilities; change points by binary "
                    "segmentation with permutation tests; Delta = mean absolute z-difference from the rest of the work. "
                    "Style shows that chapters differ, not when or by whom — read it with the dating evidence",
        }

    # ------------------------------------------------------------ dating
    def _attested(self, surface: str, same: frozenset[str]) -> dict[str, Any] | None:
        """The earliest other work that uses ``surface`` (by the start of its date range) and how many do."""
        key = (surface, same)
        if key in self._first:
            return self._first[key]
        ids = self.b.corpus.contains(surface, verify=False, limit=3000)  # (year, id) order: the earliest first
        others = [bid for bid in self.b.book_counts(ids) if bid not in same]
        starts = sorted((y[0], bid) for bid in others if (y := _years(self.b, bid)))
        out = {"after": starts[0][0], "first": self.b.book_title(starts[0][1]), "book_id": starts[0][1],
               "books": len(others)} if starts else None
        self._first[key] = out
        return out

    def dating(self, work: str | None = None, *, books: list[str] | None = None, margin: float = 300, min_later: int = 3,
               max_terms: int = 60) -> dict[str, Any]:
        ids, book = self._witness(work, books)
        work_key = (book.work or book.id) if book else ids[0]
        same = frozenset(bk.id for bk in self.b.corpus.books.values() if (bk.work or bk.id) == work_key)
        nominal = (book.composition.start, book.composition.end) if book and book.composition else None
        cut = (nominal[1] + margin) if nominal else None
        chapters = self.chapters(ids)
        if self._extractor is None:
            self._extractor = CitationExtractor(self.b.pack, self.b.corpus)
        floors = [f for f in (self.taboo.profile(bid).get("edition_floor") for bid in ids if bid in self.b.corpus.books)
                  if f is not None]
        witness_evidence = [{"kind": "taboo", "after": max(floors), "strength": "hard", "applies": "edition",
                             "what": "taboo characters of the witness (date the edition, not the composition)"}] if floors else []
        rows = []
        for c in chapters:
            evidence: list[dict[str, Any]] = []
            for p in self.b.passages(c["passages"]):
                blank = mask_notes(p.text)
                for m in self._extractor.extract(p):
                    if blank[m.start: m.end].strip() == "":  # a citation inside a note belongs to the annotator
                        continue
                    for target, weight in m.candidates.items():
                        tb = self.b.corpus.books.get(target)
                        if tb is None or (tb.work or tb.id) == work_key or tb.composition is None:
                            continue
                        evidence.append({"kind": "citation", "what": m.surface, "target": tb.title, "after": tb.composition.start,
                                         "strength": "hard" if weight >= 0.8 else "soft", "passage_id": p.id})
            checked = 0
            if cut is not None:
                terms = sorted({mt.surface for mt in self.b.pack.lexicon.match(c["text"], include_weak=False) if len(mt.surface) >= 2},
                               key=lambda s_: (self.b.corpus.count(s_), s_))[:max_terms]
                for surface in terms:
                    first = self._attested(surface, same)
                    if first is None:
                        continue
                    checked += 1
                    if first["after"] >= cut and first["books"] >= min_later:
                        evidence.append({"kind": "vocabulary", "what": surface, "after": first["after"], "strength": "soft",
                                         "first": first["first"], "books": first["books"]})
            late = sorted({e["what"] for e in evidence if e["kind"] == "vocabulary"})
            rows.append({"chapter": c["chapter"], "chars": c["chars"], "evidence": evidence, "late_vocabulary": late,
                         "terms_checked": checked, "late_rate": round(len(late) / checked, 4) if checked else 0.0})
        # a chapter's late vocabulary counts against the rest of the same work: a thin early corpus makes some words
        # of every early chapter look late, a later layer has many more of them
        rates = [r["late_rate"] for r in rows if r["terms_checked"] >= 5]
        mean = sum(rates) / len(rates) if rates else 0.0
        sd = (sum((x - mean) ** 2 for x in rates) / max(1, len(rates) - 1)) ** 0.5 if len(rates) > 1 else 0.0
        for r in rows:
            r["late_z"] = round((r["late_rate"] - mean) / sd, 3) if sd > 0 and r["terms_checked"] >= 5 else None
            unusual = r["late_z"] is not None and r["late_z"] >= 1.5 and len(r["late_vocabulary"]) >= 3
            kept = [e for e in r["evidence"] if e["kind"] != "vocabulary" or unusual]
            r["interval"] = interval(kept, nominal)
            r["unusual_vocabulary"] = unusual
            r["evidence"] = sorted(r["evidence"], key=lambda e: (-(e.get("after") or 0), e["kind"]))[:12]
        flagged = [r for r in rows if r["interval"].get("later_than_nominal")]
        return {
            "work": book.title if book else work, "witness": ids, "nominal": list(nominal) if nominal else None,
            "margin": margin, "witness_evidence": witness_evidence, "chapters": rows, "late_rate_mean": round(mean, 4),
            "later_than_nominal": [{"chapter": r["chapter"], "after": r["interval"]["after"],
                                    "vocabulary_after": r["interval"]["vocabulary_after"], "late_z": r["late_z"],
                                    "terms": r["late_vocabulary"][:10]} for r in flagged],
            "note": "terminus post quem from works cited in the main text (hard evidence); late vocabulary = terms no other "
                    f"work attests before the work's date + {int(margin)} years while {min_later}+ works attest them later — "
                    "counted only where a chapter has unusually many of them for its work (z ≥ 1.5), since a thin early "
                    "corpus makes some words of every early chapter look late (soft evidence); recensions of the same text "
                    "under another title count as other works; taboo characters date the witness's edition",
        }

    # ------------------------------------------------------------ authorship
    def _profile_of(self, ids: list[str], names: list[str], chapter: str | None = None) -> tuple[list[float], int]:
        text = "".join(c["text"] for c in self.chapters(ids) if chapter is None or chapter in c["chapter"])
        return profile(text, names), len(text)

    def authorship(self, text: str | None = None, *, book: str | None = None, chapter: str | None = None,
                   candidates: list[str] | None = None, min_chars: int = 2000) -> dict[str, Any]:
        """Burrows' Delta of a text — given, or a book (optionally one chapter) — against candidate works (book ids
        or works; default: the dated works of the text's category with at least ``min_chars`` characters)."""
        names = FUNCTION_CHARS
        if text:
            han, _ = han_only(self.b.normalize(text))
            target, n = profile(han, names), len(han)
            label = text[:30]
        else:
            if not book:
                raise ValueError("give a text or a book")
            ids = self.stemma.witness_sets(None, [book])[0] if book in self.b.corpus.books else self.stemma.base_witness(book)
            target, n = self._profile_of(ids, names, chapter)
            label = self.b.book_title(ids[0]) + (f"·{chapter}" if chapter else "")
        if n < 200:
            raise ValueError("the text is too short to profile (fewer than 200 characters)")
        pool: dict[str, list[str]] = {}
        if candidates:
            for cand in candidates:
                ids = [cand] if cand in self.b.corpus.books else self.stemma.base_witness(cand)
                pool[self.b.book_title(ids[0])] = ids
        else:
            cat = self.b.corpus.books[book].category if book and book in self.b.corpus.books else None
            seen_works: set[str] = set()
            for bk in sorted(self.b.corpus.books.values(), key=lambda x: x.id):
                if cat and bk.category != cat or (bk.work or bk.id) in seen_works or bk.id == book:
                    continue
                seen_works.add(bk.work or bk.id)
                pool[bk.title] = [bk.id]
        profiles = {}
        sizes = {}
        for title, ids in pool.items():
            prof, size = self._profile_of(ids, names)
            if size >= min_chars:
                profiles[title], sizes[title] = prof, size
        ranked = attribute(target, profiles)
        for r in ranked:
            r["characters"] = sizes[r["candidate"]]
        return {"text": label, "characters": n, "candidates": ranked,
                "note": "Burrows' Delta over function characters (z-scored over the candidates and the text): smaller is "
                        "closer; a margin much smaller than the spread of the deltas decides nothing.  Style is shaped by "
                        "genre and editing as well as by the author"}


def _years(b: StudyBase, book_id: str) -> list[float] | None:
    book = b.corpus.books.get(book_id)
    rng = getattr(book, "composition", None)
    return [rng.start, rng.end] if rng is not None else None


__all__ = ["StratigraphyStudy"]
