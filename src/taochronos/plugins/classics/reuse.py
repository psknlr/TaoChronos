"""Text-reuse detection (转录 / 改写) between passages of different books."""

from __future__ import annotations

import difflib
import math
import re
from collections import Counter
from dataclasses import dataclass, field

from ...protocol.documents import Passage
from .domain import DomainPack

PUNCT = set("，。；：、？！“”‘’（）《》…—·「」『』 \n\t,.;:!?()[]")


def strip_punct(text: str) -> tuple[str, list[int]]:
    """Remove punctuation, returning the cleaned string and a map back to original offsets."""
    chars: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text):
        if ch not in PUNCT:
            chars.append(ch)
            index.append(i)
    return "".join(chars), index


def bigrams(text: str) -> list[str]:
    return [text[i: i + 2] for i in range(len(text) - 1)]


@dataclass
class ReuseMatch:
    source: str  # passage id (later)
    target: str  # passage id (earlier or undetermined)
    relation: str  # transcribes | rephrases
    blocks: list[dict] = field(default_factory=list)
    longest_block: int = 0
    containment: float = 0.0
    weighted_overlap: float = 0.0
    direction_certain: bool = True
    quote_source: str = ""
    quote_target: str = ""


class TextReuseDetector:
    def __init__(self, pack: DomainPack, min_block: int = 6, min_weighted_overlap: float = 0.42) -> None:
        self.pack = pack
        self.min_block = min_block
        self.min_weighted_overlap = min_weighted_overlap
        self._idf: dict[str, float] = {}
        self._formula_terms = {e.term for e in pack.lexicon.by_category("formula")}
        self._corpus = None  # large corpora: document frequencies come from the full-text index on demand
        self._n = 0

    def fit(self, passages: list[Passage]) -> None:
        df: Counter = Counter()
        for p in passages:
            clean, _ = strip_punct(self.pack.variants.normalize_text(p.text))
            df.update(set(bigrams(clean)))
        n = max(1, len(passages))
        self._idf = {bg: math.log((n + 1) / (c + 0.5)) for bg, c in df.items()}

    def use_corpus_statistics(self, corpus: object) -> None:
        self._corpus = corpus
        self._n = max(1, len(corpus))  # type: ignore[arg-type]

    def idf(self, bg: str, default: float = 1.0) -> float:
        if bg in self._idf:
            return self._idf[bg]
        if self._corpus is None:
            return default
        df = self._corpus.document_frequency([bg]).get(bg, 0)  # type: ignore[attr-defined]
        value = math.log((self._n + 1) / (df + 0.5)) if df else default
        self._idf[bg] = value
        return value

    def _masked(self, clean: str) -> str:
        """Blank out formula names and prescription formulae so shared names do not look like reuse."""
        chars = list(clean)
        for m in self.pack.lexicon.match(clean):
            if m.category in ("formula", "herb"):
                chars[m.start: m.end] = "□" * (m.end - m.start)
        masked = "".join(chars)
        return re.sub(r"主之|宜", lambda mt: "□" * len(mt.group(0)), masked)

    def _formulaic(self, block: str) -> bool:
        stripped = re.sub(r"(主之|宜|可与|汤|丸|散|饮)", "", block)
        return any(term in block and len(term) >= len(block) - 3 for term in self._formula_terms) or len(stripped) < 3

    def compare(self, a: Passage, b: Passage) -> ReuseMatch | None:
        """Compare two passages; ``a`` is treated as the later witness when dates differ."""
        na = self.pack.variants.normalize_text(a.text)
        nb = self.pack.variants.normalize_text(b.text)
        ca, ia = strip_punct(na)
        cb, ib = strip_punct(nb)
        if len(ca) < 4 or len(cb) < 4:
            return None
        matcher = difflib.SequenceMatcher(None, ca, cb, autojunk=False)
        blocks = []
        for blk in matcher.get_matching_blocks():
            if blk.size >= self.min_block:
                text = ca[blk.a: blk.a + blk.size]
                if self._formulaic(text):
                    continue
                blocks.append(
                    {
                        "text": text,
                        "a_span": [ia[blk.a], ia[blk.a + blk.size - 1] + 1],
                        "b_span": [ib[blk.b], ib[blk.b + blk.size - 1] + 1],
                        "size": blk.size,
                    }
                )
        ma, mb = self._masked(ca), self._masked(cb)
        shorter = ma if len(ca) <= len(cb) else mb
        shared = {bg for bg in set(bigrams(ma)) & set(bigrams(mb)) if "□" not in bg}
        total_w = sum(self.idf(bg) for bg in set(bigrams(shorter))) or 1.0
        weighted = sum(self.idf(bg) for bg in shared) / total_w
        longest = max((blk["size"] for blk in blocks), default=0)
        containment = sum(blk["size"] for blk in blocks) / len(shorter)
        distinctive = [bg for bg in shared if self.idf(bg, 0) > 1.5]
        if not blocks and not (weighted >= self.min_weighted_overlap and len(distinctive) >= 4 and len(shorter) >= 8):
            return None
        relation = "transcribes" if containment >= 0.85 else "rephrases"
        return ReuseMatch(
            source=a.id,
            target=b.id,
            relation=relation,
            blocks=blocks,
            longest_block=longest,
            containment=round(containment, 4),
            weighted_overlap=round(weighted, 4),
            quote_source=blocks[0]["text"] if blocks else "",
            quote_target=blocks[0]["text"] if blocks else "",
        )
