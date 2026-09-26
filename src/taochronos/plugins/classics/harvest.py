"""Lexicon harvesting from the corpus store (candidate terms, never canonical knowledge).

The curated lexicon is demo-sized; the full corpus names thousands of formulas and drugs.  This module
collects *candidate* terms with transparent, pattern-level evidence:

* herbs — 本草 entries 「X味甘…」 (证类本草 lineage), with 「一名Y」 aliases; 本草纲目 entry titles
  「X（别录中品）」, whose label names the work Li Shizhen credits with the drug's first record;
* formulas — prescription headings 「X汤方」, block openings 「X散治…」 and 「…X丸主之」 clauses,
  with Song-taboo 圆/丸 pairs linked as synonyms.

Every harvested entry records how often and in how many books it was seen and its earliest dated
witness.  Harvested files live apart from the curated lexicon and are loaded only by profiles that ask
for them (``full-corpus``); an expert promotes entries into the curated lexicon.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

HAN = "一-鿿㐀-䶿"
SUFFIX = "汤散丸圆饮丹膏煎"
BAD_START = set("右上以用服煮和入加去每宜与可先后作名其此又方治主之为若如凡夫即便乃但并同各等取令将及或并前右即凡盖故论至饮下送")
BAD_CHARS = set("两钱分升合枚斤铢个片握匕服煮以水酒和末各等为之者也其曰云")
DRUG_SOURCES = ("本经", "别录", "唐本", "拾遗", "开宝", "嘉祐", "图经", "日华", "纲目", "宋本", "蜀本", "食疗", "海药", "日用", "衍义",
                "药性", "千金", "外台", "食物", "证类", "救荒", "炮炙", "唐本草")


@dataclass
class Candidate:
    term: str
    category: str
    count: int = 0
    books: set[str] = field(default_factory=set)
    evidence: dict[str, int] = field(default_factory=dict)  # pattern → count
    first_year: float | None = None
    first_passage: str | None = None
    aliases: set[str] = field(default_factory=set)
    origin: str | None = None  # 本草纲目 source label (本经, 别录…)

    def see(self, book: str, pattern: str, year: float | None, passage: str) -> None:
        self.count += 1
        self.books.add(book)
        self.evidence[pattern] = self.evidence.get(pattern, 0) + 1
        if year is not None and (self.first_year is None or year < self.first_year):
            self.first_year, self.first_passage = year, passage


def _ok_name(name: str) -> bool:
    if not (2 <= len(name) <= 9) or name[0] in BAD_START:
        return False
    if re.search(r"[一二三四五六七八九十百]+[丸圆丹]$", name) and len(name) <= 5:
        return False  # 饮下三十丸, 至四十丸: a dose, not a name
    body = name[:-1]
    return not any(ch in BAD_CHARS for ch in body) and not re.search(r"[一二三四五六七八九十百]味", name)


INDICATION_CHARS = set("治主疗杀去除止利益补痛疮毒病风痢血疽瘘痈肿虫")
# disease headings that end like a formula name (一切痰饮, 留饮): kept only when also used as a name in running text
DISEASE_TAIL = re.compile(r"(痰饮|悬饮|支饮|溢饮|留饮|伏饮|停饮|宿饮|水饮|酒饮|癖饮|澼饮|冷饮|饮食)$")


def _ok_drug(name: str) -> bool:
    if not (1 <= len(name) <= 5) or name[0] in BAD_START or any(ch in "味气曰云之也者其释色" for ch in name):
        return False
    return sum(ch in INDICATION_CHARS for ch in name) < 2  # 润肌肤皮毛, 风鼠瘘痈肿: an indication, not a drug


class Harvester:
    def __init__(self, normalize: Callable[[str], str], known: set[str]) -> None:
        self.normalize = normalize
        self.known = known  # normalised surfaces of the curated lexicon (never re-harvested)
        self.formulas: dict[str, Candidate] = {}
        self.herbs: dict[str, Candidate] = {}
        self._headings: set[tuple[str, str]] = set()  # (book, section path): a heading counts once, not per passage

    def _formula(self, name: str, book: str, pattern: str, year: float | None, pid: str) -> None:
        if name in self.known or not _ok_name(name):
            return
        cand = self.formulas.setdefault(name, Candidate(name, "formula"))
        cand.see(book, pattern, year, pid)

    def _herb(self, name: str, book: str, pattern: str, year: float | None, pid: str) -> Candidate | None:
        if name in self.known or not _ok_drug(name):
            return None
        cand = self.herbs.setdefault(name, Candidate(name, "herb"))
        cand.see(book, pattern, year, pid)
        return cand

    def passage(self, pid: str, book: str, category: str, text: str, section: str | None, year: float | None, kind: str) -> None:
        if kind in ("toc",):
            return
        norm = self.normalize(text)
        sec = self.normalize(section.split(" · ")[-1]) if section else ""  # the innermost heading of a path
        if sec and (book, section) not in self._headings:
            self._headings.add((book, section))  # type: ignore[arg-type]
            m = re.fullmatch(rf"([{HAN}]{{2,9}}?[{SUFFIX}])方?", sec)
            if m:
                self._formula(m.group(1), book, "heading", year, pid)
        m = re.match(rf"^([{HAN}]{{2,9}}?[{SUFFIX}])(?:方|治|主|疗|：|　)", norm)
        if m:
            self._formula(m.group(1), book, "block", year, pid)
        for m in re.finditer(rf"(?:者|宜|与|宜服|可与|宜用|服|用|以)([{HAN}]{{2,8}}?[{SUFFIX}])(?:主之|亦主之|治之)", norm):
            self._formula(m.group(1), book, "zhuzhi", year, pid)
        if category == "本草":
            m = re.match(rf"^(?:衍义曰|图经曰)?([{HAN}]{{1,5}}?)[，、：]?味[甘苦辛酸咸淡涩]", norm)
            if m is None and re.fullmatch(rf"[{HAN}]{{1,5}}", sec) and re.match(r"^(?:气味：?)?味[甘苦辛酸咸淡涩]", norm):
                m = re.match(r"(.*)", sec)  # punctuated editions: the entry is a heading, the text opens with 味
            if m:
                cand = self._herb(m.group(1), book, "materia-entry", year, pid)
                if cand is not None:
                    for a in re.finditer(rf"一名([{HAN}]{{2,4}}?)(?=一名|生|[，。；]|$)", norm[:400]):
                        alias = a.group(1)
                        if _ok_drug(alias) and alias != cand.term and not re.search(r"[一二三四五六七八九十]月|采|日", alias):
                            cand.aliases.add(alias)
            # 本草纲目 entry titles: at a passage start or after a layout space, followed by the next rubric
            for m in re.finditer(rf"(?:^|　)([{HAN}]{{1,5}}?)（({'|'.join(DRUG_SOURCES)})(上品|中品|下品|草|)[^）]{{0,4}}）(?=　|释名|集解|$)", norm):
                cand = self._herb(m.group(1), book, "gangmu-entry", year, pid)
                if cand is not None and cand.origin is None:
                    cand.origin = m.group(2)

    def select(self, *, min_books: int = 2, min_count: int = 3) -> tuple[list[Candidate], list[Candidate]]:
        formulas = [c for c in self.formulas.values()
                    if c.evidence.get("heading") or c.evidence.get("block", 0) >= 2
                    or (len(c.books) >= min_books and c.count >= min_count)]
        formulas = [c for c in formulas if not DISEASE_TAIL.search(c.term) or c.evidence.get("zhuzhi")]
        # 「附都气丸」 is the heading 附 (appended) + 都气丸: merge into the name when that name is attested
        names = {c.term for c in formulas} | self.known
        for c in [c for c in formulas if c.term.startswith("附") and c.term[1:] in names]:
            target = self.formulas.get(c.term[1:])
            if target is not None:
                target.count += c.count
                target.books |= c.books
                for k, v in c.evidence.items():
                    target.evidence[k] = target.evidence.get(k, 0) + v
            formulas.remove(c)
        # a candidate that is a suffix of a longer accepted name seen far more often is a fragment (黄汤 < 麻黄汤)
        names = {c.term for c in formulas}
        formulas = [c for c in formulas if not any(o != c.term and o.endswith(c.term) and len(c.term) <= 2 for o in names)]
        herbs = [c for c in self.herbs.values() if c.evidence.get("materia-entry") or c.evidence.get("gangmu-entry")]
        herb_names = {c.term for c in herbs}
        for c in herbs:
            c.aliases = {a for a in c.aliases if a not in self.known and a not in herb_names}
        return sorted(formulas, key=lambda c: (-c.count, c.term)), sorted(herbs, key=lambda c: (-c.count, c.term))


def taboo_pairs(formulas: Iterable[Candidate]) -> dict[str, str]:
    """X圆 → X丸 (宋人避钦宗讳改“丸”为“圆”): the 圆 form becomes a taboo-rename synonym of the 丸 form."""
    names = {c.term for c in formulas}
    return {n: n[:-1] + "丸" for n in names if n.endswith("圆") and n[:-1] + "丸" in names}


def to_yaml_entries(formulas: list[Candidate], herbs: list[Candidate]) -> tuple[dict[str, Any], dict[str, Any]]:
    pairs = taboo_pairs(formulas)
    f_entries = []
    for c in formulas:
        if c.term in pairs:
            continue
        syn = [{"surface": k, "kind": "taboo_rename", "note": "宋人避讳，丸作圆"} for k, v in pairs.items() if v == c.term]
        f_entries.append({"term": c.term, "kind": "harvested", **({"synonyms": syn} if syn else {}),
                          "evidence": {"count": c.count, "books": len(c.books), "patterns": dict(sorted(c.evidence.items())),
                                       "first_year": c.first_year, "first_passage": c.first_passage}})
    h_entries = []
    for c in herbs:
        entry: dict[str, Any] = {"term": c.term, "kind": "harvested"}
        if len(c.term) == 1:
            entry["weak"] = True  # single-character drug names (栗, 芥) are ambiguous in running text
        if c.aliases:
            entry["synonyms"] = [{"surface": a, "kind": "alias", "note": "本草“一名”"} for a in sorted(c.aliases)]
        if c.origin:
            entry["origin_record"] = c.origin
        entry["evidence"] = {"count": c.count, "books": len(c.books), "patterns": dict(sorted(c.evidence.items())),
                             "first_year": c.first_year, "first_passage": c.first_passage}
        h_entries.append(entry)
    header = {"provenance": "harvested from the corpus store by `taochronos lexicon harvest`; candidates, not expert-reviewed"}
    return ({**header, "category": "formula", "entries": f_entries}, {**header, "category": "herb", "entries": h_entries})
