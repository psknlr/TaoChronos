"""Reading a reuse pair in the classics: where the source is reused in a later passage, and the features of the pair.

The labels and the rules are in ``science.semantic_reuse``; this module reads the texts: variant-normalised Han
characters, the lexicon's concepts weighted by their rarity in the corpus, the markers and stock phrases of
``intertext.yaml``.  The later passage may be long (a commentary, a chapter of a compendium), so the reused span is
located first — the densest stretch of shared wording and shared concepts no longer than three times the source.
"""

from __future__ import annotations

import difflib
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ...science.semantic_reuse import ReuseFeatures, SparseEncoder, classify, order_concordance, weighted_coverage
from .domain import DomainPack

HAN = re.compile(r"[㐀-鿿\U00020000-\U0002ffff〓□]")
NOTE = re.compile(r"（[^（）]*）|\([^()]*\)|〔[^〔〕]*〕|【[^【】]*】")  # interlinear notes (夹注)
FUNCTION_CHARS = set("之乎者也矣焉哉而其以于於所则乃且亦又即若如故夫盖此是斯兮耳尔曰云为")
_WEAK_CATEGORIES = {"herb", "formula"}  # single-character drug and formula names match everywhere (发, 阴)


@dataclass
class Concept:
    term_id: str
    surface: str
    start: int  # in the Han string
    end: int
    category: str


@dataclass
class Prepared:
    """A text ready for comparison: normalised, its Han characters with their offsets, its concepts."""

    text: str  # normalised (same length as the original)
    han: str
    index: list[int]  # Han position → offset in ``text``
    concepts: list[Concept] = field(default_factory=list)

    def joined(self, i: int) -> bool:
        """Are Han characters ``i`` and ``i + 1`` adjacent in the text (no punctuation between them)?"""
        return i + 1 < len(self.index) and self.index[i + 1] == self.index[i] + 1

    def raw_span(self, a: int, b: int) -> tuple[int, int]:
        if not self.index or a >= b:
            return 0, 0
        return self.index[a], self.index[b - 1] + 1


class IntertextAnalyzer:
    def __init__(self, pack: DomainPack, corpus: Any, data: dict[str, Any] | None = None) -> None:
        self.pack = pack
        self.corpus = corpus
        self.normalize = pack.variants.normalize_text
        if data is None:
            path = Path(pack.root) / "intertext.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
        n = self.normalize
        self.citation = [re.compile(f"(?:{n(p)})[：:，,]?[“「『]?$") for p in data.get("citation", [])]
        self.dialogue = [re.compile(n(p)) for p in data.get("dialogue", [])]
        self.opposition = [re.compile(n(p)) for p in data.get("opposition", [])]
        self.interpretation = [re.compile(n(p)) for p in data.get("interpretation", [])]
        self.stock = [re.compile(n(p)) for p in data.get("stock_phrases", [])]
        self._df: dict[str, int] = {}
        self._n = max(1, len(corpus))
        self.encoder = SparseEncoder(self.idf)

    # ------------------------------------------------------------ texts
    def prepare(self, text: str) -> Prepared:
        """Normalised, with its Han characters — interlinear notes (夹注) left out: they comment on the text."""
        norm = self.normalize(text)
        noted = _note_mask(norm)
        index = [i for i, ch in enumerate(norm) if HAN.match(ch) and not noted[i]]
        han = "".join(norm[i] for i in index)
        concepts = []
        for m in self.pack.lexicon.match(han, include_weak=False):
            if len(m.surface) == 1 and m.category in _WEAK_CATEGORIES:
                continue
            concepts.append(Concept(m.term_id, m.surface, m.start, m.end, m.category))
        return Prepared(norm, han, index, concepts)

    # ------------------------------------------------------------ rarity
    def df(self, surface: str) -> int:
        """Passages containing ``surface`` (a bigram: from the full-text index's vocabulary, at once)."""
        if surface not in self._df:
            try:
                if len(surface) == 2 and getattr(self.corpus, "large", False):
                    self._df[surface] = int(self.corpus.document_frequency([surface]).get(surface, 0))
                else:
                    self._df[surface] = int(self.corpus.count(surface))
            except Exception:  # noqa: BLE001 - a surface the index cannot query counts as unseen
                self._df[surface] = 0
        return self._df[surface]

    def idf(self, token: str) -> float:
        """Rarity of a concept (``term:…`` tokens are weighted by their surface) or of a character bigram."""
        surface = token.split(":", 1)[1] if ":" in token else token
        return math.log((self._n + 1) / (self.df(surface) + 0.5))

    def items(self, p: Prepared, a: int, b: int) -> dict[str, tuple[float, int, str, str]]:
        """The content of ``p.han[a:b]``: its concepts, and the content bigrams wholly outside them (half weight:
        overlapping bigrams are not independent evidence) — key → (weight, position from ``a``, kind, surface)."""
        out: dict[str, tuple[float, int, str, str]] = {}
        covered = bytearray(max(0, b - a))
        for c in p.concepts:
            if a <= c.start and c.end <= b:
                covered[c.start - a: c.end - a] = b"\x01" * (c.end - c.start)
                if c.term_id not in out:
                    out[c.term_id] = (self.concept_idf(c.term_id, c.surface), c.start - a, "concept", c.surface)
        piece = p.han[a:b]
        for pattern in self.stock:  # the genre's stock phrasing is no one's content
            for m in pattern.finditer(piece):
                covered[m.start():m.end()] = b"\x01" * (m.end() - m.start())
        for i in range(a, b - 1):
            g = p.han[i: i + 2]
            if not p.joined(i) or set(g) <= FUNCTION_CHARS or covered[i - a] or covered[i + 1 - a] or g in out:
                continue
            out[g] = (0.5 * self.idf(g), i - a, "bigram", g)
        return out

    def concept_idf(self, term_id: str, surface: str) -> float:
        """Rarity of a concept: of its commonest written form among the one used and the lexicon's headword (the
        headword 太阳病 is far commoner than the form 太阳之为病, and the concept is what is shared)."""
        entry = self.pack.lexicon.entry(term_id)
        forms = {surface} | ({self.normalize(entry.term)} if entry else set())
        df = max(self.df(f) for f in forms)
        return math.log((self._n + 1) / (df + 0.5))

    def tokens(self, p: Prepared, a: int = 0, b: int | None = None) -> list[str]:
        b = len(p.han) if b is None else b
        grams = [p.han[i: i + 2] for i in range(a, b - 1) if p.joined(i) and not set(p.han[i: i + 2]) <= FUNCTION_CHARS]
        return grams + [c.term_id for c in p.concepts if a <= c.start and c.end <= b]

    # ------------------------------------------------------------ the reused span
    @staticmethod
    def _densest(items: list[tuple[int, int, float]], width: int) -> tuple[int, int, float]:
        """The run of (start, end, weight) items with the largest weight whose extent stays within ``width``."""
        items = sorted(items)
        best = (0, 0, 0.0)
        total = 0.0
        j = 0  # the window is items[i:j]
        for i in range(len(items)):
            if j <= i:
                j, total = i, 0.0
            while j < len(items) and items[j][1] - items[i][0] <= width:
                total += items[j][2]
                j += 1
            if j > i and total > best[2]:
                best = (items[i][0], max(e for _, e, _ in items[i:j]), total)
            if j > i:
                total -= items[i][2]
        return best

    def span(self, s: Prepared, t: Prepared) -> tuple[int, int]:
        """Where in ``t`` the source ``s`` is reused (Han offsets): shared trigrams and concepts locate it, the
        alignment's blocks and the shared concepts bound it."""
        n = len(s.han)
        width = max(3 * n, n + 40)
        grams = {s.han[i: i + 3] for i in range(n - 2)}
        terms = {c.term_id for c in s.concepts}
        content = {g for g, v in self.items(s, 0, n).items() if v[2] == "bigram"}  # the source's content bigrams
        anchors = [(i, i + 3, 1.0) for i in range(len(t.han) - 2) if t.han[i: i + 3] in grams]
        anchors += [(c.start, c.end, 2.0) for c in t.concepts if c.term_id in terms]
        anchors += [(i, i + 2, 0.5) for i in range(len(t.han) - 1) if t.han[i: i + 2] in content]
        if not anchors:
            return 0, 0
        a0, b0, _ = self._densest(anchors, width)
        lo, hi = max(0, a0 - width), min(len(t.han), b0 + width)
        crop = t.han[lo:hi]
        blocks = [(lo + bl.b, lo + bl.b + bl.size, float(bl.size))
                  for bl in difflib.SequenceMatcher(None, s.han, crop, autojunk=False).get_matching_blocks() if bl.size >= 2]
        # wording first: where most of the source is there almost word for word, that is the span (a quotation
        # followed by commentary is a quotation); otherwise the stretch that carries the source's content
        a, b, kept = self._densest(blocks, int(1.6 * n) + 8) if blocks else (0, 0, 0.0)
        if kept >= 0.8 * n or (kept >= 0.5 * n and kept >= 0.8 * (b - a)):  # whole, or a dense partial quotation
            return a, b
        items = blocks + [(c.start, c.end, 2.0) for c in t.concepts if c.term_id in terms and lo <= c.start and c.end <= hi]
        items += [(i, i + 2, 1.0) for i in range(lo, hi - 1) if t.han[i: i + 2] in content]
        if not items:
            return a0, b0
        a, b, _ = self._densest(items, width)
        return a, b

    # ------------------------------------------------------------ features
    def _markers(self, patterns: list[re.Pattern[str]], text: str, exclude: str) -> list[str]:
        found = []
        for p in patterns:
            for m in p.finditer(text):
                if m.group(0) not in exclude:  # the source's own words are not the target's comment on it
                    found.append(m.group(0))
        return found

    def attribution(self, t: Prepared, a: int) -> str:
        if not t.index:
            return ""
        ra = t.index[a] if a < len(t.index) else len(t.text)
        before = t.text[max(0, ra - 16): ra].rstrip("　 ")
        for p in self.citation:
            m = p.search(before)
            if m and not any(d.search(m.group(0).rstrip("：:，,“「『")) for d in self.dialogue):
                return m.group(0).rstrip("：:，,“「『")
        return ""

    def features(self, source: str | Prepared, target: str | Prepared) -> tuple[ReuseFeatures, dict[str, Any]]:
        """The features of reusing ``source`` in ``target``, and where: ``{"span": [a, b] (Han), "raw": [start, end]
        (in the target's text), "text": the reused span as written}``."""
        s = source if isinstance(source, Prepared) else self.prepare(source)
        t = target if isinstance(target, Prepared) else self.prepare(target)
        n = len(s.han)
        if n < 2 or len(t.han) < 2:
            return ReuseFeatures(source_chars=n), {"span": [0, 0], "raw": [0, 0], "text": ""}
        a, b = self.span(s, t)
        if b <= a:
            return ReuseFeatures(source_chars=n, target_chars=0), {"span": [0, 0], "raw": [0, 0], "text": ""}
        piece = t.han[a:b]
        blocks = [bl for bl in difflib.SequenceMatcher(None, s.han, piece, autojunk=False).get_matching_blocks() if bl.size >= 2]
        matched = sum(bl.size for bl in blocks)
        # content: the source's concepts and the content bigrams outside them, weighted by rarity; credit where the
        # target expresses them (a concept in part: 头项强痛 ~ 项背强痛; a bigram split: 离决 ~ 相离而决)
        in_span = [c for c in t.concepts if a <= c.start and c.end <= b]
        first = {c.term_id: c for c in reversed(s.concepts)}
        src_items = self.items(s, 0, n)
        tgt_items = self.items(t, a, b)
        target_terms = {k: v[1] for k, v in tgt_items.items() if v[2] == "concept"}
        credit: dict[str, float] = {}
        pairs: list[tuple[int, int]] = []
        shared, partial, missing = [], [], []
        for key, (_, pos, kind, surface) in src_items.items():
            if kind == "concept":
                if key in target_terms:
                    credit[key], at = 1.0, target_terms[key]
                    shared.append(key)
                else:
                    frac, at = _partial(surface, piece)
                    if frac < 0.6:  # 头项强痛 ~ 项背强痛 (3 of 4), not 头…疼痛 (2 of 4)
                        missing.append(key)
                        continue
                    credit[key] = 0.8 * frac
                    partial.append(key)
            else:
                at = piece.find(key)
                if at < 0:
                    at = _split(key, piece)
                    if at < 0:
                        continue
                    credit[key] = 0.5
                else:
                    credit[key] = 1.0
            pairs.append((pos, at))
        weights = {k: v[0] for k, v in src_items.items()}
        concept_cov = weighted_coverage(weights, credit)
        specificity = sum(weights[k] * v for k, v in credit.items()) - math.log(self._n)
        # the source's point: its three most specific concepts (its rarest bigrams, when the lexicon knows none of
        # its concepts — a summary drops rare details such as 侠鼻, but keeps the concepts)
        pool = [k for k, v in src_items.items() if v[2] == "concept"] or list(weights)
        top = sorted(pool, key=lambda k: (-weights[k], k))[:3]
        distinctive = max((credit.get(k, 0.0) for k in top), default=0.0)
        # precision: how much of what the target span says comes from the source
        back: dict[str, float] = {}
        for key, (_, _, kind, surface) in tgt_items.items():
            if kind == "concept":
                if key in src_items:
                    back[key] = 1.0
                else:
                    frac, _ = _partial(surface, s.han)
                    back[key] = 0.8 * frac if frac >= 0.6 else 0.0
            else:
                back[key] = 1.0 if key in s.han else 0.0
        concept_prec = weighted_coverage({k: v[0] for k, v in tgt_items.items()}, back)
        basis = "concepts+bigrams" if first else "bigrams"
        added = sorted({c.term_id for c in in_span} - set(first))
        # stock phrasing: the share of the shared wording that falls inside the genre's formulae
        mask = bytearray(n)
        for p in self.stock:
            for m in p.finditer(s.han):
                mask[m.start():m.end()] = b"\x01" * (m.end() - m.start())
        stock = sum(sum(mask[bl.a: bl.a + bl.size]) for bl in blocks)
        ra, rb = t.raw_span(a, b)
        source_text = s.text
        noted = _note_mask(t.text)  # interlinear notes inside the span: commentary on the quotation, counted apart
        notes = sum(1 for i in range(ra, rb) if noted[i] and HAN.match(t.text[i]))
        f = ReuseFeatures(
            source_chars=n, target_chars=b - a, notes=notes,
            cov_source=round(matched / n, 4), cov_target=round(matched / (b - a), 4),
            longest_block=max((bl.size for bl in blocks), default=0),
            mean_block=round(matched / len(blocks), 2) if blocks else 0.0,
            concept_cov=round(concept_cov, 4), concept_prec=round(concept_prec, 4), concept_basis=basis,
            specificity=round(specificity, 2),
            distinctive=round(distinctive, 3),
            concepts_shared=shared, concepts_partial=partial, concepts_missing=missing, concepts_added=added[:12],
            order=round(order_concordance(pairs), 4), length_ratio=round((b - a) / n, 4),
            formulaic_share=round(stock / matched, 4) if matched else 0.0,
            similarity=self.encoder.similarity(self.tokens(s), self.tokens(t, a, b)),
            attribution=self.attribution(t, a),
            opposition=self._markers(self.opposition, t.text[max(0, ra - 8): rb + 16], source_text),
            interpretation=self._markers(self.interpretation, t.text[ra: rb + 40], source_text),
        )
        return f, {"span": [a, b], "raw": [ra, rb], "text": t.text[ra:rb]}

    def label(self, source: str | Prepared, target: str | Prepared, thresholds: dict[str, float] | None = None) -> dict[str, Any]:
        """Features, span and the reuse type of ``source`` reused in ``target``."""
        f, where = self.features(source, target)
        return {"features": f.to_dict(), "where": where, **classify(f, thresholds)}


def _note_mask(text: str) -> bytearray:
    """1 for every character inside an interlinear note (nested brackets included)."""
    mask = bytearray(len(text))
    for m in NOTE.finditer(text):
        mask[m.start():m.end()] = b"\x01" * (m.end() - m.start())
    prev = None
    while prev != bytes(mask):  # notes inside notes: widen to the outer brackets
        prev = bytes(mask)
        blanked = "".join(" " if mask[i] else ch for i, ch in enumerate(text))
        for m in NOTE.finditer(blanked):
            mask[m.start():m.end()] = b"\x01" * (m.end() - m.start())
    return mask


def _split(bigram: str, piece: str, width: int = 4) -> int:
    """Where a bigram's two characters stand in order a few characters apart (离决 in 相离而决), or -1."""
    i = piece.find(bigram[0])
    while i >= 0:
        j = piece.find(bigram[1], i + 1, i + 1 + width)
        if j >= 0:
            return i
        i = piece.find(bigram[0], i + 1)
    return -1


def _partial(surface: str, piece: str) -> tuple[float, int]:
    """How much of a concept's written form the target has, close together (头项强痛 in 项背强痛: 项, 强, 痛 within a
    few characters): the share of its content characters in the best window, and where that window starts."""
    content = list(dict.fromkeys(ch for ch in surface if ch not in FUNCTION_CHARS)) or list(surface)
    width = len(surface) + 3
    positions = sorted((i, ch) for i, ch in enumerate(piece) if ch in content)
    best, at = 0, -1
    for k, (i, _) in enumerate(positions):
        seen = {ch for j, ch in positions[k:] if j - i < width}
        if len(seen) > best:
            best, at = len(seen), i
    return best / len(content), at


__all__ = ["Concept", "IntertextAnalyzer", "Prepared"]
