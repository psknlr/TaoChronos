"""What the corpus admits: historical texts, not their modern afterlives.

Three kinds of text are excluded from every source (the user's criteria):

* **当代出版物** — works first written or compiled after 1949 (textbooks, dictionaries, modern compilations);
* **当代名医著作** — writings and case records of physicians of the People's Republic era;
* **现代校注本** — modern annotated, translated or reconstructed editions: annotation apparatus (【注释】,
  numbered footnotes, 阐释), and modern reconstructions of lost works (辑校本 whose entries carry the modern
  editor's source references, e.g. 「（《外台》卷一）」, 「〔證〕」).

Republican-era works (1912–1949) are historical sources and stay (category 近代); so do Qing reconstructions
(孙星衍's 本经).  Decisions come from the curated list (``corpus/catalog/exclusions.yaml`` and the per-source
override files) first, then from the automatic screen below; both record their reason in the catalogs.  A review
may keep a modern edition (``keep``): it then enters the store with its editors' work separated from the old text
by the rules of its catalog entry (:mod:`.apparatus`, ADR 0007).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONTEMPORARY = "当代出版物"
CONTEMPORARY_PHYSICIAN = "当代名医著作"
MODERN_EDITION = "现代校注本"
MODERN_RECONSTRUCTION = "现代校注本（现代辑校本）"
MODERN_ERA = 1949  # works composed from this year on are contemporary

# strong signals of a text written (or re-edited) after 1949; 西醫 alone is not one — late-Qing 中西汇通 texts use it
_MODERN = re.compile(
    r"(19[4-9][0-9]\s*年|20[0-2][0-9]\s*年|[0-9０-９]+\s*(克|毫克|毫升|公斤|公分|厘米|毫米)|醫院|医院|醫學院|医学院|衛生部|卫生部|"
    r"研究所|研究院|中華人民共和國|中华人民共和国|解放[前後后]|出版社|教授|研究員|研究员|主任醫師|主任医师|門診|门诊|住院|化驗|化验|"
    r"血壓|血压|維生素|维生素|抗生素|青黴素|青霉素|心電圖|心电图|白細胞|白细胞|紅細胞|红细胞|血紅蛋白|血红蛋白|碳水化合物|蛋白質|蛋白质)")
# a modern editor's source references in a reconstructed lost work
_RECONSTRUCTION = re.compile(
    r"（《(外臺|外台|醫心方|医心方|證類|证类|大觀|大观|政和|千金|御覽|御览|綱目|纲目)》[^）]{0,12}）|〔(證|证|心|千|外)〕|"
    r"《本經》原文|《本经》原文|按：此藥參見|按：此药参见")
# numbered footnote calls of a modern annotated edition: 「如舔犢(1)而愛惜」
_FOOTNOTE = re.compile(r"[一-鿿][(（][0-9０-９]{1,3}[)）]")
_APPARATUS = re.compile(r"【(注釋|注释|註釋|語譯|语译|譯文|译文|今譯|今译|白話|白话|點評|点评|評析|评析|闡釋|阐释|導讀|导读|作者簡介|作者简介)】")
MODERN_TITLE = re.compile(r"(校注|校釋|校释|語譯|语译|今譯|今译|白話|白话|譯注|译注|註譯|注译|新解|考釋|考释|講義|讲义|選讀|选读|淺釋|浅释|"
                          r"經驗集|经验集|老中醫|老中医|驗案精選|验案精选|醫療經驗|医疗经验|臨證經驗|临证经验|教材|辭典|辞典|大辭典|大辞典)")


@dataclass
class Screen:
    reason: str | None  # None: admitted
    evidence: dict[str, Any] = field(default_factory=dict)
    curated: bool = False


def scan(text: str) -> dict[str, float]:
    """Counts and densities (per 10,000 characters) of the modern signals in a text."""
    n = max(1, len(text))
    modern = len(_MODERN.findall(text))
    rec = len(_RECONSTRUCTION.findall(text))
    foot = len(_FOOTNOTE.findall(text))
    app = len(_APPARATUS.findall(text))
    return {"modern": modern, "modern_per_10k": round(modern * 1e4 / n, 2), "reconstruction": rec,
            "reconstruction_per_10k": round(rec * 1e4 / n, 2), "footnotes": foot, "apparatus": app}


def screen(title: str, text: str, composition: list[int] | tuple[int, int] | None, *, curated: str | None = None,
           keep: bool = False, lost_work: bool = False) -> Screen:
    """Decide whether a text is admitted.  ``curated`` is a reviewed decision (a reason, or ``keep``)."""
    if curated:
        return Screen(curated, {"curated": True}, curated=True)
    stats = scan(text)
    if keep:
        return Screen(None, stats, curated=True)
    if composition is not None and composition[0] >= MODERN_ERA:
        return Screen(CONTEMPORARY, {**stats, "composition": list(composition)})
    if MODERN_TITLE.search(title or ""):
        label = CONTEMPORARY_PHYSICIAN if re.search(r"(經驗|经验|老中|驗案|验案|醫療|医疗|臨證|临证)", title) else MODERN_EDITION
        return Screen(label, {**stats, "title": title})
    if stats["modern"] >= 8 and stats["modern_per_10k"] >= 2.0:
        return Screen(CONTEMPORARY, stats)
    if stats["apparatus"] >= 5:
        return Screen(MODERN_EDITION, stats)
    if stats["footnotes"] >= 20:
        return Screen(MODERN_EDITION, stats)
    if lost_work and stats["reconstruction_per_10k"] >= 3.0:
        return Screen(MODERN_RECONSTRUCTION, stats)
    return Screen(None, stats)


class Exclusions:
    """``corpus/catalog/exclusions.yaml``: reviewed decisions by source and code (``exclude`` with a reason, or
    ``keep`` to overrule the automatic screen), and titles excluded (a reason) or kept (``keep``) wherever they
    appear."""

    def __init__(self, path: str | Path | None) -> None:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) if path and Path(path).exists() else {}
        data = data or {}
        self.by_source: dict[str, dict[str, dict[str, Any]]] = {k: dict(v or {}) for k, v in (data.get("sources") or {}).items()}
        self.titles: dict[str, str] = dict(data.get("titles") or {})

    def decision(self, source: str, code: str, title_key: str = "") -> tuple[str | None, bool]:
        """(curated exclusion reason, curated keep)."""
        d = self.by_source.get(source, {}).get(code) or {}
        if d.get("exclude"):
            return str(d["exclude"]), False
        if d.get("keep"):
            return None, True
        for t, reason in self.titles.items():
            if title_key and t == title_key:
                return (None, True) if reason == "keep" else (reason, False)
        return None, False


__all__ = ["CONTEMPORARY", "CONTEMPORARY_PHYSICIAN", "MODERN_EDITION", "MODERN_ERA", "MODERN_RECONSTRUCTION", "MODERN_TITLE",
           "Exclusions", "Screen", "scan", "screen"]
