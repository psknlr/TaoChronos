"""Machine segmentation of unpunctuated classical text (白文) — a *view*, never an edit.

Most digitised editions of the medical classics (四库全书, 四部丛刊 transcriptions) are unpunctuated.
The rule-based extractor needs clause and sentence boundaries, so this module inserts virtual
punctuation into a *copy* of the (normalised) text and keeps an offset map back to the original.
Claims extracted from the view are mapped back, so their quotes and spans stay verbatim in the source.

The rules are deliberately conservative and transparent (every inserted mark has a rule name); they are
a reading aid for extraction, not an edition.  Punctuated texts pass through unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

SEGMENTER_VERSION = "baiwen-seg@0.1"
PUNCT = set("，。；：、？！“”‘’（）《》…—·「」『』,.;:!?()")
SENTENCE_FINAL = "也矣焉哉乎欤耶"
NUM = "一二三四五六七八九十百千半两"
DOSE = re.compile(rf"(?:各)?[{NUM}]+(?:两|钱|分|铢|斤|升|合|枚|个|片|握|茎|撮|匕|丸|条|具|斗)(?:[{NUM}]+(?:两|钱|分|铢|升|合|枚))?(?:半)?")
PREP = ("去皮尖", "去皮", "去节", "去心", "去芦", "去毛", "去核", "去子", "去足", "去翅", "去土", "去皮脐", "炮去皮脐",
        "炙", "炮", "熬", "洗", "切", "擘", "碎", "绵裹", "酒洗", "酒浸", "研", "锉", "去白", "焙", "炒", "煨")
HERB_NATURE = re.compile(r"味[甘苦辛酸咸淡涩]{1,3}(?:[，、]?[大小微]?[寒热温凉平]){0,2}")
TOXICITY = ("无毒", "有毒", "有小毒", "有大毒", "小毒", "大毒")
SPEECH = ("曰", "云")
STARTERS = ("凡", "夫", "若", "假令", "设", "又方", "又", "治", "右", "上件", "上为", "其", "故", "盖", "是以", "所以", "然则", "此")


@dataclass
class SegmentedView:
    """``text`` is the view; ``origin[i]`` is the source index of view character ``i`` and
    ``marks[i]`` says whether it was inserted (an inserted mark points at the next source character)."""

    text: str
    origin: list[int]
    marks: list[bool]
    source_length: int
    rules: dict[str, int] = field(default_factory=dict)

    @property
    def inserted(self) -> int:
        return sum(self.marks)

    def to_source(self, start: int, end: int) -> tuple[int, int]:
        """Map a view span to the smallest source span covering its source characters."""
        chars = [self.origin[i] for i in range(max(0, start), min(end, len(self.text))) if not self.marks[i]]
        if not chars:
            pos = self.origin[start] if start < len(self.origin) else self.source_length
            return pos, pos
        return min(chars), max(chars) + 1


def punctuation_density(text: str) -> float:
    if not text:
        return 0.0
    return sum(1 for ch in text if ch in PUNCT) / len(text)


def is_unpunctuated(text: str, threshold: float = 0.02) -> bool:
    """A passage longer than a short heading with (almost) no punctuation is 白文."""
    return len(text) >= 12 and punctuation_density(text) < threshold


class Segmenter:
    """Rule-based virtual punctuation.  ``lexicon`` (optional) improves formula and herb boundaries."""

    def __init__(self, lexicon: Any = None) -> None:
        self.lexicon = lexicon

    def boundaries(self, norm: str) -> dict[int, tuple[str, str]]:
        """Position → (mark, rule): the mark is inserted *before* the character at that position."""
        marks: dict[int, tuple[str, str]] = {}
        n = len(norm)

        def put(pos: int, mark: str, rule: str) -> None:
            if 0 < pos < n and norm[pos - 1] not in PUNCT and norm[pos] not in PUNCT:
                prev = marks.get(pos)
                if prev is None or (prev[0] == "，" and mark in "。：；"):
                    marks[pos] = (mark, rule)

        formula_spans: list[tuple[int, int]] = []
        herb_spans: list[tuple[int, int]] = []
        if self.lexicon is not None:
            for m in self.lexicon.match(norm, include_weak=False):
                if m.category == "formula":
                    formula_spans.append((m.start, m.end))
                elif m.category == "herb":
                    herb_spans.append((m.start, m.end))
        formula_starts = {s for s, _ in formula_spans}
        # layout marks already in the source (○ bullets) end sentences; space runs are handled in view()
        for i, ch in enumerate(norm):
            if ch in "○" and i + 1 < n:
                put(i + 1, "。", "layout")
        # 曰 / 云 introduce speech or quotation
        for m in re.finditer(r"曰", norm):
            if m.start() > 0 and norm[m.start() - 1] not in "名号谓是或" and "\u4e00" <= norm[m.start() - 1] <= "\u9fff":
                put(m.end(), "：", "speech")
        for m in re.finditer(r"(?:经|论|又|注|按|方|传|书|氏|师|公|子|人)云", norm):
            put(m.end(), "：", "speech")
        # sentence-final particles
        for m in re.finditer(f"[{SENTENCE_FINAL}]", norm):
            nxt = norm[m.end(): m.end() + 1]
            if nxt and nxt not in "者之所而则以" + SENTENCE_FINAL:
                put(m.end(), "。", "final-particle")
        # prescriptions: …X主之 / …宜X / 可与X
        for m in re.finditer(r"主之", norm):
            put(m.end(), "。", "zhuzhi")
        for s, e in formula_spans:
            tail = norm[e: e + 2]
            if tail.startswith(("方", "主之", "亦主之")):
                continue
            head = norm[max(0, s - 2): s]
            if head.endswith(("宜", "与", "服", "用")) or norm[max(0, s - 3): s].endswith(("宜服", "可与", "宜用")):
                put(e, "。", "yi-formula")
            if e < n and norm[e] == "方":
                put(e + 1, "。", "formula-heading")
        # 者 closes a condition before a prescription / verdict
        for m in re.finditer("者", norm):
            nxt = norm[m.end(): m.end() + 3]
            if (m.end() in formula_starts or nxt.startswith(("宜", "可与", "不可", "当", "必", "此为", "此名", "名曰", "名为",
                                                               "为", "死", "生", "难治", "易治", "不治", "可治", "属", "是", "此", "其",
                                                               "须", "即", "便", "乃", "亦", "宜"))):
                put(m.end(), "，", "zhe-condition")
        # doses and preparation in prescriptions
        herb_ends = {e for _, e in herb_spans}
        for m in DOSE.finditer(norm):
            end = m.end()
            for prep in PREP:
                if norm.startswith(prep, end):
                    end += len(prep)
                    break
            if m.start() in herb_ends or norm[max(0, m.start() - 1): m.start()] in ("各",):
                put(end, "，", "dose")
            elif m.start() > 0 and "一" <= norm[m.start() - 1] <= "鿿":
                put(end, "，", "dose")
        for m in re.finditer(r"[右上][一二三四五六七八九十]+味", norm):
            put(m.start(), "。", "you-wei")
        # materia medica: X，味…，…。无毒。主…
        for m in HERB_NATURE.finditer(norm):
            put(m.start(), "，", "herb-nature")
            put(m.end(), "，", "herb-nature")
        for tox in TOXICITY:
            for m in re.finditer(tox, norm):
                put(m.end(), "。", "toxicity")
        # common sentence starters after a completed clause
        for starter in STARTERS:
            for m in re.finditer(re.escape(starter), norm):
                if m.start() > 0 and norm[m.start() - 1] in "之也矣焉耳愈死差瘥止出下":
                    put(m.start(), "。", "starter")
        return marks

    def layout(self, norm: str, herb_ends: set[int], herb_starts: set[int]) -> dict[int, str]:
        """Layout space runs (list separators in printed prescriptions) → replacement in the view:
        the first space becomes 、 between list items (。 otherwise) and the rest are dropped."""
        out: dict[int, str] = {}
        for m in re.finditer(r"[\u3000 ]+", norm):
            s, e = m.start(), m.end()
            if s == 0 or e == len(norm):
                continue
            before = norm[s - 1]
            item_before = s in herb_ends or before == "）" or DOSE.search(norm[max(0, s - 6): s]) is not None
            out[s] = "、" if item_before and (e in herb_starts or norm[e] not in PUNCT) else "。"
            for i in range(s + 1, e):
                out[i] = ""
        return out

    def view(self, norm: str) -> SegmentedView:
        marks = self.boundaries(norm)
        herb_ends: set[int] = set()
        herb_starts: set[int] = set()
        if self.lexicon is not None:
            for m in self.lexicon.match(norm, include_weak=False):
                if m.category == "herb":
                    herb_ends.add(m.end)
                    herb_starts.add(m.start)
        replace = self.layout(norm, herb_ends, herb_starts)
        chars: list[str] = []
        origin: list[int] = []
        inserted: list[bool] = []
        rules: dict[str, int] = {}
        for i, ch in enumerate(norm):
            if i in marks and i not in replace:
                mark, rule = marks[i]
                chars.append(mark)
                origin.append(i)
                inserted.append(True)
                rules[rule] = rules.get(rule, 0) + 1
            if i in replace:
                if replace[i]:
                    chars.append(replace[i])
                    origin.append(i)
                    inserted.append(False)
                    rules["layout"] = rules.get("layout", 0) + 1
                continue
            chars.append(ch)
            origin.append(i)
            inserted.append(False)
        if norm and norm[-1] not in PUNCT:
            chars.append("。")
            origin.append(len(norm))
            inserted.append(True)
        return SegmentedView("".join(chars), origin, inserted, len(norm), rules)


def split_long(text: str, limit: int = 400, hard: int = 900) -> list[tuple[int, int]]:
    """Split a long paragraph into spans at sentence-final particles (or at ``hard`` characters)."""
    if len(text) <= limit:
        return [(0, len(text))]
    spans: list[tuple[int, int]] = []
    start = 0
    while len(text) - start > limit:
        window = text[start + limit // 2: start + hard]
        cut = -1
        for m in re.finditer(f"[{SENTENCE_FINAL}。；]", window):
            cut = start + limit // 2 + m.end()
            if cut - start >= limit:
                break
        if cut <= start:
            cut = min(len(text), start + hard)
        spans.append((start, cut))
        start = cut
    if start < len(text):
        spans.append((start, len(text)))
    return spans


def iter_sentences(view: SegmentedView) -> Iterable[tuple[int, int]]:
    start = 0
    for i, ch in enumerate(view.text):
        if ch in "。；！？":
            if i > start:
                yield start, i
            start = i + 1
    if start < len(view.text):
        yield start, len(view.text)
