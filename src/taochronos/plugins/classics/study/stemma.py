"""版本谱系 — collating the witnesses of a work: variant units, the stemma, contamination, edition profiles.

The witnesses of a work are its transcriptions in the corpus (a witness in several volumes is joined in volume order)
or any books given explicitly; for a *passage*, its witnesses are its copies and quotations across the corpus (from
the concordance).  The main text is collated: prefaces, tables of contents, separated commentary layers and the
notes in brackets are left out.  Every witness is aligned to a base — by default the witness most of whose text the
others carry (a plain text rather than a commentary that embeds it) — the edits are merged into variant units, and the
units give distances, a neighbour-joining stemma, the groups defined by shared readings, and contamination (a witness
that also copied another branch).  The base is a coordinate system, not a claim that its readings are right.
"""

from __future__ import annotations

import json
import re
import zlib
from collections import Counter, defaultdict
from typing import Any

from ....protocol.textual_criticism import VariantUnit, Witness
from ..collation import (
    WitnessText,
    align,
    apparatus,
    ascii_tree,
    build_units,
    clades,
    contamination,
    distances,
    counts,
    groups,
    load_equivalents,
    matched,
    neighbour_joining,
    newick,
    patterns,
    project,
    root,
)
from .base import StudyBase, dated

SIGLA = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
SOURCE_NAMES = {"kanripo": "四库", "jicheng": "笈成", "wikisource": "维基文库", "mcgill": "McGill", "tcm-ancient-books": "TCM-AB",
                "tcmoc": "tcmoc", "hf-tcm-canon": "HF", "demo": "演示"}
_NOTE = re.compile(r"（[^（）]*）|\([^()]*\)|〔[^〔〕]*〕|【[^【】]*】|\[[^\[\]]*\]")
_VOLUME = re.compile(r"[（(](?:[上中下]|[一二三四五六七八九十]+)[）)]$")
_FRONT_LAYER = re.compile(r"^(?:卷首|序跋)")
_EXCLUDED_KINDS = {"toc", "preface", "commentary"}


def mask_notes(text: str) -> str:
    """Bracketed notes blanked out (same length, so offsets into the passage stay valid)."""
    prev = None
    while prev != text:
        prev = text
        text = _NOTE.sub(lambda m: " " * len(m.group(0)), text)
    return text


def _shingles(s: str, k: int = 12, keep: int = 4) -> set[str]:
    """The k-grams of a text sampled by content (the same k-grams are kept in every text, wherever they fall; a stable
    hash, so the choice of base does not change from run to run)."""
    return {g for g in (s[i: i + k] for i in range(max(0, len(s) - k + 1))) if zlib.crc32(g.encode("utf-8")) % keep == 0}


class StemmaStudy:
    def __init__(self, base: StudyBase) -> None:
        self.b = base
        self.equivalents = load_equivalents(base.data("collation.yaml").get("equivalents") or [], base.normalize)

    # ------------------------------------------------------------ witnesses
    def witness_sets(self, work: str | None = None, books: list[str] | None = None) -> list[list[str]]:
        """Witnesses as lists of book ids — one list per witness, its volumes in order (``a+b`` joins volumes)."""
        corpus = self.b.corpus
        if books:
            return [[x for x in spec.split("+") if x in corpus.books] for spec in books if spec]
        if not work:
            raise ValueError("give a work (its key, title or a book id) or the books to collate")
        key = work if any((bk.work or bk.id) == work for bk in corpus.books.values()) else None
        if key is None:
            norm = self.b.normalize(work)
            hit = next((bk for bk in corpus.books.values() if bk.id == work or self.b.normalize(bk.title) == norm
                        or norm in {self.b.normalize(a) for a in bk.aliases}), None)
            if hit is None:
                hit = next((bk for bk in sorted(corpus.books.values(), key=lambda x: len(x.title))
                            if norm and norm in self.b.normalize(bk.title)), None)
            if hit is None:
                raise ValueError(f"no work or book matches {work!r}")
            key = hit.work or hit.id
        members = sorted(bk.id for bk in corpus.books.values() if (bk.work or bk.id) == key)
        sources = getattr(corpus, "sources", {}) or {}
        by_stem: dict[tuple[str, str], list[str]] = defaultdict(list)
        for bid in members:
            stem = _VOLUME.sub("", corpus.books[bid].title)
            by_stem[(sources.get(bid, ""), stem)].append(bid)
        out: list[list[str]] = []
        for ids in by_stem.values():
            titles = [corpus.books[b].title for b in ids]
            if len(ids) > 1 and len(set(titles)) == len(titles):  # 普济方, 普济方(二) …: the volumes of one witness
                out.append(ids)
            else:  # the same title twice: two transcriptions
                out += [[b] for b in ids]
        return sorted(out, key=lambda ids: ids[0])

    def base_witness(self, work: str | None = None, books: list[str] | None = None) -> list[str]:
        """The book ids of the witness most of whose text the other witnesses carry (a plain text rather than a
        commentary that embeds it; among near-equals the longest) — the base of collation and stratigraphy."""
        sets = self.witness_sets(work, books)
        if len(sets) == 1:
            return sets[0]
        texts = {i: self._witness_text("X", ids).text for i, ids in enumerate(sets[: len(SIGLA)])}
        texts = {i: t for i, t in texts.items() if len(t) >= 20} or {0: ""}
        if len(texts) == 1:
            return sets[next(iter(texts))]
        return sets[_choose_base(texts)]

    def _rows(self, book_id: str, chapter: re.Pattern[str] | None = None) -> list[tuple[str, str, str, str]]:
        store = getattr(self.b.corpus, "store", None)
        out: list[tuple[str, str, str, str]] = []
        if store is not None:
            with store.lock:
                rows = store.db.execute("SELECT id, locator, layer, kind, text FROM passages WHERE book_id=? ORDER BY seq",
                                        (book_id,)).fetchall()
            for pid, loc, layer, kind, text in rows:
                if kind in _EXCLUDED_KINDS or _FRONT_LAYER.match(layer or ""):
                    continue
                d = json.loads(loc)
                label = "·".join(x for x in (d.get("volume"), d.get("chapter"), d.get("section")) if x)
                if chapter is not None and not chapter.search(label):
                    continue
                out.append((pid, label, layer or "", mask_notes(text)))
        else:
            for p in self.b.corpus.passages(book_ids=[book_id]):
                if p.kind in _EXCLUDED_KINDS:
                    continue
                label = self.b.locator(p)
                if chapter is not None and not chapter.search(label):
                    continue
                out.append((p.id, label, "", mask_notes(p.text)))
        return out

    def _witness_text(self, siglum: str, ids: list[str], chapter: re.Pattern[str] | None = None) -> WitnessText:
        rows = [r for bid in ids for r in self._rows(bid, chapter)]
        return WitnessText.build(siglum, "+".join(ids), rows, self.b.normalize)

    def _describe(self, siglum: str, ids: list[str], text: WitnessText) -> Witness:
        corpus = self.b.corpus
        book = corpus.books.get(ids[0])
        years = [book.composition.start, book.composition.end] if book and book.composition else []
        edition = next((e for e in (book.editions if book else []) if e.year), None)
        if edition is not None:
            years = [edition.year.start, edition.year.end]
        sources = getattr(corpus, "sources", {}) or {}
        return Witness(id=siglum, book_id="+".join(ids), title=book.title if book else ids[0], kind="edition", years=years,
                       source=SOURCE_NAMES.get(sources.get(ids[0], ""), sources.get(ids[0], "")),
                       license=getattr(book.source, "license", "") if book else "", characters=len(text.text))

    # ------------------------------------------------------------ collation
    def collate(self, work: str | None = None, *, books: list[str] | None = None, base: str | None = None,
                chapter: str | None = None, max_chars: int = 60000, min_coverage: float = 0.2) -> dict[str, Any]:
        sets = self.witness_sets(work, books)
        pattern = re.compile(chapter) if chapter else None
        texts: dict[str, WitnessText] = {}
        ids_of: dict[str, list[str]] = {}
        for k, ids in enumerate(sets[: len(SIGLA)]):
            siglum = SIGLA[k]
            texts[siglum] = self._witness_text(siglum, ids, None)
            ids_of[siglum] = ids
        texts = {s: t for s, t in texts.items() if len(t.text) >= 20}
        if len(texts) < 2:
            raise ValueError("fewer than two witnesses with text to collate")
        # the base: a named witness, else the plain text of the whole work (see _choose_base)
        shingles = {s: _shingles(t.text) for s, t in texts.items()}
        if base:
            base_sig = next((s for s, ids in ids_of.items() if base in ids or base == s), None)
            if base_sig is None or base_sig not in texts:
                raise ValueError(f"the base {base!r} is not one of the witnesses")
        else:
            base_sig = _choose_base({s: t.text for s, t in texts.items()}, shingles)
        base_text = self._witness_text(base_sig, ids_of[base_sig], pattern) if pattern else texts[base_sig]
        if len(base_text.text) > max_chars:
            base_text = _truncate(base_text, max_chars)
        if len(base_text.text) < 20:
            raise ValueError("the base has no text in the chosen range")
        base_sh = _shingles(base_text.text)
        projections = {}
        witnesses = [self._describe(base_sig, ids_of[base_sig], base_text)]
        witnesses[0].coverage = 1.0
        excluded = []
        for s, t in texts.items():
            if s == base_sig:
                continue
            overlap = len(base_sh & shingles[s]) / max(1, len(base_sh))
            if overlap < min_coverage * 0.5:  # hardly any text in common: another part of the work, or another text
                excluded.append({"siglum": s, "books": ids_of[s], "title": self.b.book_title(ids_of[s][0]),
                                 "overlap": round(overlap, 3)})
                continue
            proj = project(len(base_text.text), align(base_text.text, t.text), t)
            coverage = proj.carried / len(base_text.text)
            if coverage < min_coverage:
                excluded.append({"siglum": s, "books": ids_of[s], "title": self.b.book_title(ids_of[s][0]),
                                 "coverage": round(coverage, 3)})
                continue
            projections[s] = proj
            w = self._describe(s, ids_of[s], t)
            w.characters = len(t.text) - proj.out_of_scope
            w.coverage = round(coverage, 3)
            witnesses.append(w)
        units = build_units(base_text, projections, equivalents=self.equivalents)
        return {"base": base_text, "base_siglum": base_sig, "witnesses": witnesses, "projections": projections,
                "units": units, "excluded": excluded}

    def variants(self, work: str | None = None, **kw: Any) -> dict[str, Any]:
        """The apparatus of a work: witnesses, variant units, counts by kind."""
        c = self.collate(work, **kw)
        return self._variants_result(c)

    def _variants_result(self, c: dict[str, Any]) -> dict[str, Any]:
        base, units, witnesses = c["base"], c["units"], c["witnesses"]
        n = len(base.text)
        textual = [u for u in units if not u.structural]
        kinds = Counter(u.kind for u in textual)
        subs: Counter = Counter()
        where: dict[tuple[str, str], list[str]] = defaultdict(list)
        for u in textual:  # single-character substitutions: spelling conventions to review, or real variants
            if u.kind != "substitution" or len(u.lemma) != 1:
                continue
            for r in u.readings[1:]:
                if len(r.text) == 1:
                    pair = tuple(sorted((u.lemma, r.text)))
                    subs[pair] += 1
                    if len(where[pair]) < 3:
                        where[pair].append(u.context)
        lacunae = {s: sum(l1 - l0 for l0, l1 in p.lacunae) for s, p in c["projections"].items()}
        structural = {s: p.structural for s, p in c["projections"].items()}
        singular = Counter(r.witnesses[0] for u in textual if counts(u) and _present(u) >= 3 for r in u.readings
                           if len(r.witnesses) == 1)
        return {
            "work": witnesses[0].title, "base": c["base_siglum"], "base_characters": n,
            "witnesses": [w.to_dict() | {"lacuna_chars": lacunae.get(w.id, 0), "structural_chars": structural.get(w.id, 0),
                                         "singular_readings": singular.get(w.id, 0)} for w in witnesses],
            "excluded": c["excluded"],
            "summary": {"units": len(textual), "structural": len(units) - len(textual), "by_kind": dict(kinds),
                        "substantive": sum(1 for u in textual if counts(u)),
                        "per_1000": round(1000 * sum(1 for u in textual if counts(u)) / n, 2) if n else None},
            "frequent_substitutions": [{"characters": "/".join(pair), "units": k, "contexts": where[pair]}
                                       for pair, k in subs.most_common(20) if k >= 3],
            "units": [u.to_dict() for u in units],
        }

    def stemma(self, work: str | None = None, *, root_at: str | None = None, **kw: Any) -> dict[str, Any]:
        """Variants, distances, the stemma (tree + contamination) and the groups of shared readings."""
        c = self.collate(work, **kw)
        out = self._variants_result(c)
        out.update(self._tree(c, root_at))
        return out

    def _tree(self, c: dict[str, Any], root_at: str | None) -> dict[str, Any]:
        units: list[VariantUnit] = c["units"]
        sigla = [w.id for w in c["witnesses"]]
        present = {c["base_siglum"]: bytearray(b"\x01" * len(c["base"].text))}
        present.update({s: p.present for s, p in c["projections"].items()})
        d = distances(units, sigla, present)
        grouped = groups(units, sigla)
        agreement = patterns(units, sigla)
        if len(sigla) < 3:
            return {"distances": _matrix(d, sigla), "groups": grouped, "patterns": agreement, "tree": [], "newick": "", "contamination": [],
                    "conflicts": [], "note": "two witnesses: distances only (a stemma needs three or more)"}
        nj = neighbour_joining(sigla, d)
        at = next((s for s in sigla if root_at and (root_at == s or root_at in (c["witnesses"][sigla.index(s)].book_id or ""))),
                  None)
        edges, root_name = root(nj, sigla, at)
        tree_clades = clades(edges, sigla)
        for e in edges:  # support: shared readings that define exactly the child's group
            below = tree_clades.get(e.child, frozenset())
            e.support = round(sum(g["support"] for g in grouped if frozenset(g["witnesses"]) == below), 2)
        enough = sum(1 for u in units if counts(u)) >= 30  # a few units cannot tell contamination from chance
        contaminated, conflicts = contamination(units, grouped, edges, sigla) if len(sigla) >= 4 and enough else ([], [])
        labels = {w.id: f"{w.id} {w.title}" + (f"（{w.source}）" if w.source else "") for w in c["witnesses"]}
        return {"distances": _matrix(d, sigla), "tree": [e.to_dict() for e in edges], "root": root_name,
                "root_basis": f"witness {at}" if at else "midpoint of the longest path",
                "newick": newick(edges, root_name), "ascii": ascii_tree(edges, root_name, labels),
                "groups": grouped[:30], "patterns": agreement, "contamination": [x.to_dict() for x in contaminated],
                "conflicts": conflicts,
                "note": "distances: weighted disagreements per 1 000 characters both witnesses carry; groups: minority "
                        "readings shared by two or more witnesses (candidate shared innovations); contamination: a witness "
                        "that also agrees with another branch against the tree, the direction read from which of the two "
                        "carries the other's private readings — contamination, or an alternative placement to examine"}

    def edition(self, book: str, **kw: Any) -> dict[str, Any]:
        """One witness among the others of its work: agreement with each, singular readings, lacunae, additions."""
        work = (self.b.corpus.books[book].work or book) if book in self.b.corpus.books else book
        c = self.collate(work, **kw)
        sig = next((w.id for w in c["witnesses"] if book in (w.book_id or "").split("+")), None)
        if sig is None:
            raise ValueError(f"{book} is not among the collated witnesses of its work")
        units = [u for u in c["units"] if counts(u)]
        sigla = [w.id for w in c["witnesses"]]
        present = {c["base_siglum"]: bytearray(b"\x01" * len(c["base"].text))}
        present.update({s: p.present for s, p in c["projections"].items()})
        d = distances(units, sigla, present)
        singular = [u for u in units if _present(u) >= 3 and any(r.witnesses == [sig] for r in u.readings)]
        p = c["projections"].get(sig)
        return {
            "book": book, "siglum": sig, "work": c["witnesses"][0].title,
            "witnesses": [w.to_dict() for w in c["witnesses"]],
            "agreement": sorted(({"siglum": o, "title": next(w.title for w in c["witnesses"] if w.id == o),
                                  "differences_per_1000": d[(sig, o)]} for o in sigla if o != sig),
                                key=lambda r: r["differences_per_1000"]),
            "singular_readings": len(singular),
            "singular_per_1000": round(1000 * len(singular) / max(1, len(c["base"].text)), 2),
            "examples": [u.to_dict() for u in singular[:20]],
            "lacunae": [{"start": a, "end": b_, "locator": c["base"].locate(a)[1]} for a, b_ in (p.lacunae if p else [])][:20],
            "structural_chars": p.structural if p else 0,
        }

    def passage(self, text: str | None = None, passage_id: str | None = None, *, concordance: Any, min_coverage: float = 0.8,
                max_witnesses: int = 24) -> dict[str, Any]:
        """A passage's copies and quotations across the corpus as witnesses: apparatus, groups, stemma."""
        res = concordance.run(text, passage_id, min_coverage=min_coverage, limit=400)
        hits = [h for h in res["hits"] if h["coverage"] >= min_coverage]
        hits.sort(key=lambda h: (dated(h["years"]), -h["coverage"], h["passage_id"]))
        seen_books: set[str] = set()
        chosen = []
        for h in hits:  # one witness per book: its earliest-located hit
            if h["book_id"] in seen_books:
                continue
            seen_books.add(h["book_id"])
            chosen.append(h)
            if len(chosen) >= max_witnesses:
                break
        base_raw = res["query"]
        base = WitnessText.build("Q", None, [(passage_id or "query", "", "", base_raw)], self.b.normalize)
        witnesses = [Witness(id="Q", title="检索文本" if not passage_id else self.b.book_title(passage_id.split(".")[0]),
                             kind="edition", characters=len(base.text), coverage=1.0, passage_id=passage_id)]
        projections = {}
        for k, h in enumerate(chosen):
            sig = _siglum(k)
            t = WitnessText.build(sig, h["book_id"], [(h["passage_id"], h["locator"], h.get("layer", ""), h["quote"])],
                                  self.b.normalize)
            proj = project(len(base.text), align(base.text, t.text), t)
            projections[sig] = proj
            src = (getattr(self.b.corpus, "sources", {}) or {}).get(h["book_id"], "")
            witnesses.append(Witness(id=sig, book_id=h["book_id"], title=h["title"],
                                     kind="edition" if h["relation"] == "同书异本" else "quotation",
                                     years=list(h["years"] or []), source=SOURCE_NAMES.get(src, src), license=h.get("license", ""),
                                     characters=len(t.text), coverage=round(proj.carried / max(1, len(base.text)), 3),
                                     passage_id=h["passage_id"]))
        c = {"base": base, "base_siglum": "Q", "witnesses": witnesses, "projections": projections,
             "units": build_units(base, projections, prefix="pu", equivalents=self.equivalents), "excluded": []}
        out = self._variants_result(c)
        out["work"] = base_raw[:30]
        out["relations"] = {w.id: next((h["relation"] for h in chosen if h["passage_id"] == w.passage_id), "")
                            for w in witnesses[1:]}
        if len(witnesses) >= 3:
            out.update(self._tree(c, None))
        return out

    def tei(self, work: str | None = None, **kw: Any) -> str:
        c = self.collate(work, **kw)
        return apparatus(c["base"], c["units"], c["witnesses"], title=f"{c['witnesses'][0].title}：计算校勘")


def _choose_base(texts: dict[Any, str], shingles: dict[Any, set[str]] | None = None) -> Any:
    """The witness that is the plain text of the whole work.  Excerpts are set aside first — a witness that carries
    less than half as much of the others' text as the fullest one does (补养宣导法 beside 诸病源候论, a partial
    transcription) — then the one most of whose text the others carry wins (a plain text, not a commentary that
    embeds it); among near-equals, the longest."""
    sh = shingles or {k: _shingles(t) for k, t in texts.items()}
    keys = list(texts)
    if len(keys) == 1:
        return keys[0]

    def share(a: Any, b: Any) -> float:  # the part of a's text that b carries
        return len(sh[a] & sh[b]) / max(1, len(sh[a]))

    carried = {k: sum(share(k, o) for o in keys if o != k) / (len(keys) - 1) for k in keys}
    covers = {k: sum(share(o, k) for o in keys if o != k) / (len(keys) - 1) for k in keys}
    whole = [k for k in keys if covers[k] >= 0.5 * max(covers.values())]
    top = max(carried[k] for k in whole)
    return max((k for k in whole if carried[k] >= top - 0.02), key=lambda k: (len(texts[k]), str(k)))


def _present(u: VariantUnit) -> int:
    return sum(len(r.witnesses) for r in u.readings)


def _siglum(k: int) -> str:
    """Sigla of quotation witnesses (Q is the passage itself)."""
    letters = [x for x in SIGLA if x != "Q"]
    return letters[k] if k < len(letters) else f"W{k + 1}"


def _truncate(t: WitnessText, n: int) -> WitnessText:
    return WitnessText(t.siglum, t.book_id, t.text[:n], t.raw[:n], t.where[:n], t.passages)


def _matrix(d: dict[tuple[str, str], float], sigla: list[str]) -> list[dict[str, Any]]:
    return [{"siglum": a, **{b: (0.0 if a == b else d.get((a, b))) for b in sigla}} for a in sigla]


__all__ = ["StemmaStudy", "mask_notes", "matched"]
