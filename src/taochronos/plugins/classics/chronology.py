"""Chinese dating expressions → years CE: reign eras (天啟四年, 康熙戊申, 乾隆四十六年), explicit Western years
(西元1644-1911年, 公元前206年-西元8年) and dynasty or period names (清, 明末清初, 民國)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Iterator

import yaml

STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"
DIGITS = {"〇": 0, "零": 0, "一": 1, "二": 2, "兩": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def cn_int(text: str) -> int | None:
    """Chinese numerals up to the thousands (元 = 1): 元 → 1, 十三 → 13, 四十六 → 46, 一千二百 → 1200."""
    text = text.strip()
    if not text:
        return None
    if text == "元":
        return 1
    if text.isdigit():
        return int(text)
    if all(ch in DIGITS for ch in text):  # 一六四四
        return int("".join(str(DIGITS[ch]) for ch in text))
    total, current = 0, 0
    for ch in text:
        if ch in DIGITS:
            current = DIGITS[ch]
        elif ch in "十拾":
            total += (current or 1) * 10
            current = 0
        elif ch in "百佰":
            total += (current or 1) * 100
            current = 0
        elif ch in "千仟":
            total += (current or 1) * 1000
            current = 0
        else:
            return None
    return total + current


def ganzhi_year(stem_branch: str, start: int, end: int) -> int | None:
    """The year in [start, end] whose sexagenary name is ``stem_branch`` (甲子 = 4 CE)."""
    if len(stem_branch) != 2 or stem_branch[0] not in STEMS or stem_branch[1] not in BRANCHES:
        return None
    s, b = STEMS.index(stem_branch[0]), BRANCHES.index(stem_branch[1])
    for y in range(start, end + 1):
        if (y - 4) % 10 == s and (y - 4) % 12 == b:
            return y
    return None


class Chronology:
    def __init__(self, path: str | Path, normalize: Callable[[str], str] | None = None) -> None:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        self.normalize = normalize or (lambda t: t)
        n = self.normalize
        self.eras = {n(k): (int(v[0]), int(v[1])) for k, v in (data.get("eras") or {}).items()}
        self.dynasties = {n(k): (int(v[0]), int(v[1])) for k, v in (data.get("dynasty_names") or {}).items()}
        # era names used twice (至元 of Khubilai and of Toghon Temür): alternative ranges, tried when the
        # sexagenary year given with the number does not fit the first reading
        self.alternates = {n(k): [(int(a), int(b)) for a, b in v] for k, v in (data.get("era_alternates") or {}).items()}
        names = sorted(self.eras, key=len, reverse=True)
        alt = "|".join(map(re.escape, names))
        gz = "[" + STEMS + "][" + BRANCHES + "]"
        self._era_re = re.compile("(" + alt + r")"
                                  r"(?:([元〇零一二三四五六七八九十百]+)年|(" + gz + r")年?|(末年|初年|年間|年间|間|间|中)|$)")
        filler = "|".join(map(re.escape, sorted({n(x) for x in ("歲次", "歲在", "龍集", "龍在", "太歲", "歲", "在", "次")}, key=len, reverse=True)))
        self._stmt_re = re.compile("(" + alt + r")(?:([元〇零一二三四五六七八九十]+)年(?:" + filler + ")?(" + gz + ")?|(?:" + filler + ")?(" + gz + "))")

    def western(self, text: str) -> tuple[int, int] | None:
        """西元762年 · 公元25－220年 · 西元1368年—1644年 · 西元前206年-西元8年."""
        t = text.replace("紀元", "元")
        m = re.search(r"(?:西元|公元)?\s*(前)?\s*(\d{1,4})\s*年?\s*(?:[-－—–~～至到]\s*(?:西元|公元)?\s*(前)?\s*(\d{1,4})\s*年?)?", t)
        if not m or not ("西元" in t or "公元" in t or re.fullmatch(r"\s*前?\d{3,4}(\s*[-－—–~～至到]\s*\d{3,4})?\s*年?\s*", t)):
            return None
        a = int(m.group(2)) * (-1 if m.group(1) else 1)
        if m.group(4):
            b = int(m.group(4)) * (-1 if m.group(3) else 1)
            return (min(a, b), max(a, b))
        return (a, a)

    def era(self, text: str) -> tuple[int, int] | None:
        for y, _, _ in self.statements(text):
            return (y, y)
        m = self._era_re.search(self.normalize(text))
        if not m:
            return None
        start, end = self.eras[m.group(1)]
        if m.group(2) or m.group(3):  # a number or sexagenary name that does not fit the era
            return (start, end)
        if m.group(4) in ("末年",):
            return (max(start, end - 5), end)
        if m.group(4) in ("初年",):
            return (start, min(end, start + 5))
        return (start, end)

    def statements(self, text: str) -> Iterator[tuple[int, int, int]]:
        """Era-dated statements naming one year — 康熙五十三年, 乾隆丙午, 至元三年丁丑 — as (year, start, end), with
        offsets into the normalised text (normalisation preserves length, so they hold for the original too)."""
        for m in self._stmt_re.finditer(self.normalize(text)):
            era = m.group(1)
            ranges = [self.eras[era], *self.alternates.get(era, [])]
            num = cn_int(m.group(2)) if m.group(2) else None
            gz = m.group(3) or m.group(4)
            year = None
            for start, end in ranges:
                if num is not None:
                    y = start + num - 1
                    if y <= end + 1 and (not gz or ganzhi_year(gz, y, y) is not None):
                        year = y
                        break
                elif gz and (y := ganzhi_year(gz, start, end)) is not None:
                    year = y
                    break
            if year is None and num is not None and ranges[0][0] + num - 1 <= ranges[0][1] + 1:
                year = ranges[0][0] + num - 1  # a miswritten sexagenary name (丙戍 for 丙戌): trust the number
            if year is not None:
                yield year, m.start(), m.end()

    def dynasty(self, text: str) -> tuple[int, int] | None:
        t = self.normalize(text.strip())
        if t in self.dynasties:
            return self.dynasties[t]
        m = re.fullmatch(r"(.+?)(代|朝|末|初|末年|初年)", t)
        if m and m.group(1) in self.dynasties:
            start, end = self.dynasties[m.group(1)]
            if m.group(2) in ("末", "末年"):
                return (max(start, end - 30), end)
            if m.group(2) in ("初", "初年"):
                return (start, min(end, start + 30))
            return (start, end)
        return None

    def parse(self, *texts: str | None) -> tuple[tuple[int, int] | None, str]:
        """The most precise dating found in the given fields, with how it was obtained."""
        for text in texts:
            if text and (r := self.western(text)):
                return r, "western"
        for text in texts:
            if text and (r := self.era(text)):
                return r, "era"
        for text in texts:
            if not text:
                continue
            for part in re.split(r"[‧·・,，、\s]+", text):
                if part and (r := self.dynasty(part)):
                    return r, "dynasty"
        return None, "none"
