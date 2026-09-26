"""Period binning and temporal series (the Diachronic knowledge graph's time axis)."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Hashable, Iterable


@dataclass(frozen=True)
class Bin:
    id: str
    label: str
    start: int
    end: int


class PeriodBinner:
    def __init__(self, bins: Iterable[tuple[str, str, int, int]]) -> None:
        self.bins = [Bin(*b) for b in bins]

    def of(self, year: float | None) -> str | None:
        if year is None:
            return None
        for b in self.bins:
            if b.start <= year < b.end:
                return b.id
        return self.bins[0].id if year < self.bins[0].start else self.bins[-1].id

    def ids(self) -> list[str]:
        return [b.id for b in self.bins]

    def label(self, bin_id: str) -> str:
        for b in self.bins:
            if b.id == bin_id:
                return b.label
        return bin_id

    def index(self, bin_id: str | None) -> int:
        for i, b in enumerate(self.bins):
            if b.id == bin_id:
                return i
        return -1

    def before(self, pivot_year: float) -> list[str]:
        return [b.id for b in self.bins if b.end <= pivot_year]

    def after(self, pivot_year: float) -> list[str]:
        return [b.id for b in self.bins if b.start >= pivot_year]


def series(items: Iterable[tuple[float | None, Hashable]], binner: PeriodBinner) -> dict[Hashable, dict[str, int]]:
    out: dict[Hashable, dict[str, int]] = defaultdict(lambda: {b: 0 for b in binner.ids()})
    for year, key in items:
        period = binner.of(year)
        if period is not None:
            out[key][period] += 1
    return dict(out)


def coverage(years: Iterable[float | None], binner: PeriodBinner) -> dict[str, int]:
    counts = Counter(binner.of(y) for y in years if y is not None)
    return {b: counts.get(b, 0) for b in binner.ids()}
