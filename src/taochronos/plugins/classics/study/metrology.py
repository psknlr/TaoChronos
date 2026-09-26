"""历代度量衡 — reading a dose of the classics in the measures of its own time.

A dose string (三两, 一两半, 六铢, 二钱五分, 半升, 十二枚, 等分) is parsed into amounts and units; weights and volumes are
converted into gram and millilitre *ranges* with the estimates of ``domains/classics/metrology.yaml`` for the period of
the witness.  分 changed meaning (a quarter of a 两 in the Han–Tang system of 陶弘景, a hundredth of a 两 from the Song),
and every conversion names the system it used.  These are readings of historical texts, never dosage guidance.
"""

from __future__ import annotations

import re
from typing import Any

_DIGITS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "〇": 0, "零": 0}
NUM = "[一二三四五六七八九十廿卅百千半〇零]+"


def cn_number(text: str) -> float | None:
    """一 → 1, 十二 → 12, 廿四 → 24, 一百二十 → 120, 半 → 0.5."""
    if text == "半":
        return 0.5
    text = text.replace("廿", "二十").replace("卅", "三十")
    total, current = 0, 0
    for ch in text:
        if ch in _DIGITS:
            current = _DIGITS[ch]
        elif ch == "十":
            total += (current or 1) * 10
            current = 0
        elif ch == "百":
            total += (current or 1) * 100
            current = 0
        elif ch == "千":
            total += (current or 1) * 1000
            current = 0
        else:
            return None
    value = total + current
    return float(value) if value else None


class Metrology:
    def __init__(self, data: dict[str, Any]) -> None:
        self.notice = data.get("notice", "")
        self.weight = {k: float(v) for k, v in (data.get("weight_units") or {}).items()}
        self.volume = {k: float(v) for k, v in (data.get("volume_units") or {}).items()}
        self.count = list(data.get("count_units") or [])
        self.nonstandard = list(data.get("nonstandard") or [])
        self.periods = list(data.get("periods") or [])
        units = sorted([*self.weight, "分", *self.volume, *self.count], key=len, reverse=True)
        self._amount = re.compile(rf"({NUM})({'|'.join(map(re.escape, units))})(半)?") if units else None
        self._nonstd = re.compile(rf"({NUM})?({'|'.join(map(re.escape, sorted(self.nonstandard, key=len, reverse=True)))})") \
            if self.nonstandard else None

    # ------------------------------------------------------------ periods
    def period(self, year: float | None) -> dict[str, Any] | None:
        if year is None:
            return None
        for p in self.periods:
            if p["start"] <= year < p["end"]:
                return p
        return None

    # ------------------------------------------------------------ parsing
    def parse(self, dose: str | None) -> list[dict[str, Any]]:
        """Amounts in a dose string: [{value, unit, kind}] (kind: weight | volume | count | nonstandard | equal)."""
        if not dose:
            return []
        if "等分" in dose:
            return [{"value": None, "unit": "等分", "kind": "equal"}]
        out: list[dict[str, Any]] = []
        text = dose.split("或")[0]
        if self.count:  # 两 is also the numeral two before a counting unit (两枚, 两片)
            text = re.sub(rf"两(?=({'|'.join(map(re.escape, self.count))}))", "二", text)
        if self._amount is not None:
            for num, unit, half in self._amount.findall(text):
                n = cn_number(num)
                if n is None:
                    continue
                kind = "weight" if unit in self.weight or unit == "分" else ("volume" if unit in self.volume else "count")
                out.append({"value": n + (0.5 if half else 0.0), "unit": unit, "kind": kind})
        if not out and self._nonstd is not None:
            for num, unit in self._nonstd.findall(text):
                out.append({"value": cn_number(num) if num else None, "unit": unit, "kind": "nonstandard"})
        return out

    def in_liang(self, dose: str | None, year: float | None) -> float | None:
        """The weight of a dose in 两 of its own time (None when it is not a weight)."""
        per = self.period(year)
        total, found = 0.0, False
        for part in self.parse(dose):
            if part["kind"] != "weight" or part["value"] is None:
                continue
            factor = (per or {}).get("fen", 0.01) if part["unit"] == "分" else self.weight.get(part["unit"])
            if factor is None:
                continue
            total += part["value"] * float(factor)
            found = True
        return round(total, 4) if found else None

    def convert(self, dose: str | None, year: float | None) -> dict[str, Any] | None:
        """Gram (or millilitre) range of a dose in the measures of the witness's period."""
        per = self.period(year)
        if per is None:
            return None
        liang = self.in_liang(dose, year)
        if liang is not None and per.get("liang_g"):
            lo, hi = per["liang_g"]
            return {"system": per["label"], "liang": liang, "grams": [round(liang * lo, 1), round(liang * hi, 1)],
                    "text": f"约{_fmt(liang * lo)}–{_fmt(liang * hi)}克（{per['label']}制）" if lo != hi else
                    f"约{_fmt(liang * lo)}克（{per['label']}制）"}
        for part in self.parse(dose):
            if part["kind"] == "volume" and part["value"] is not None and per.get("sheng_ml"):
                sheng = part["value"] * self.volume[part["unit"]]
                lo, hi = per["sheng_ml"]
                return {"system": per["label"], "sheng": sheng, "ml": [round(sheng * lo), round(sheng * hi)],
                        "text": f"约{round(sheng * lo)}–{round(sheng * hi)}毫升（{per['label']}制）"}
        return None


def _fmt(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".")


__all__ = ["Metrology", "NUM", "cn_number"]
