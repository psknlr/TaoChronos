"""Conversion repairs: errors a transcription took from the program that converted it, put right in the text itself.

Some of the transcriptions were made from simplified copies and converted back to traditional characters with Taiwan
phrasing, which replaces a word by the modern Taiwan word for it: 腳氣 (the classical disease) became 香港腳 (athlete's
foot), 《小品方》 became 《短劇方》 (短劇, a comic sketch), 循環 became 迴圈 (a loop in a program); and a one-to-many
character resolved to the wrong traditional form: 厚朴 (the drug, after the tree 朴) became 厚樸.  These are not the
edition's readings, so — unlike the script normaliser (``domain.ScriptTable``, ``domain.VariantTable``), which serves
matching only and never changes a text — a repair changes the passage: its text and its locator (the volume, chapter
and section titles), when the passage enters the store (``ingest``), and in a store already built
(``CorpusStore.repair``, ``taochronos corpus repair``).

The table is curated, ``domains/classics/script/conversion_repairs.tsv``: the wrong form, the right one, the contexts in
which the wrong form is a real word and stays (厚樸 in 敦厚樸實), a note.  A repair never produces a form another repair
would change again, so repairing twice changes nothing more.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

TABLE = "conversion_repairs.tsv"  # in domains/classics/script/


@dataclass(frozen=True)
class Repair:
    wrong: str
    right: str
    keep: tuple[str, ...] = ()
    note: str = ""


class ConversionRepairs:
    """The repairs of a table, applied longest wrong form first."""

    def __init__(self, repairs: Iterable[Repair] = ()) -> None:
        rows = list(repairs)
        by: dict[str, Repair] = {}
        for r in rows:
            if not r.wrong or r.wrong == r.right:
                raise ValueError(f"repair {r.wrong!r} → {r.right!r}: nothing to repair")
            if r.wrong in by:
                raise ValueError(f"repair {r.wrong!r} is listed twice")
            for k in r.keep:
                if r.wrong not in k:
                    raise ValueError(f"repair {r.wrong!r}: the context {k!r} it keeps does not contain it")
            by[r.wrong] = r
        for r in rows:
            again = [w for w in by if w in r.right]
            if again:
                raise ValueError(f"repair {r.wrong!r} → {r.right!r} produces {again[0]!r}, which another repair changes")
        self.repairs: tuple[Repair, ...] = tuple(sorted(rows, key=lambda r: (-len(r.wrong), r.wrong)))
        self._by = by
        self._pattern = re.compile("|".join(re.escape(r.wrong) for r in self.repairs)) if self.repairs else None
        digest = hashlib.sha1("\n".join(f"{r.wrong}\t{r.right}\t{' '.join(r.keep)}" for r in self.repairs).encode("utf-8"))
        self.fingerprint = digest.hexdigest()[:12]

    @classmethod
    def load(cls, path: str | Path) -> "ConversionRepairs":
        """The table at ``path`` (none when the file is missing)."""
        p = Path(path)
        if not p.exists():
            return cls()
        rows = []
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip() or line.startswith("#"):
                continue
            cols = line.split("\t")
            if len(cols) < 2 or not cols[0] or not cols[1]:
                raise ValueError(f"{p.name}:{n}: a repair needs the wrong form and the right one")
            keep = tuple(cols[2].split()) if len(cols) > 2 else ()
            rows.append(Repair(cols[0], cols[1], keep, cols[3].strip() if len(cols) > 3 else ""))
        return cls(rows)

    def __len__(self) -> int:
        return len(self.repairs)

    def __bool__(self) -> bool:
        return bool(self.repairs)

    @property
    def wrong_forms(self) -> list[str]:
        return [r.wrong for r in self.repairs]

    @staticmethod
    def _kept(text: str, at: int, repair: Repair) -> bool:
        """Whether the wrong form at ``at`` is part of one of the contexts it stays in."""
        for k in repair.keep:
            i = k.find(repair.wrong)
            while i >= 0:
                if at - i >= 0 and text.startswith(k, at - i):
                    return True
                i = k.find(repair.wrong, i + 1)
        return False

    def fix(self, text: str) -> tuple[str, int]:
        """The text repaired, and how many repairs were made."""
        if self._pattern is None or not text:
            return text, 0
        out: list[str] = []
        last = n = 0
        for m in self._pattern.finditer(text):
            r = self._by[m.group()]
            if r.keep and self._kept(text, m.start(), r):
                continue
            out += [text[last:m.start()], r.right]
            last = m.end()
            n += 1
        if not n:
            return text, 0
        out.append(text[last:])
        return "".join(out), n

    def fix_value(self, value: Any) -> tuple[Any, int]:
        """Every string in a locator (a dict, list or string) repaired — not addresses (``uri``/``url`` fields)."""
        if isinstance(value, str):
            return self.fix(value)
        if isinstance(value, dict):
            out, total = {}, 0
            for k, v in value.items():
                if isinstance(k, str) and ("uri" in k or "url" in k):
                    out[k] = v
                    continue
                out[k], n = self.fix_value(v)
                total += n
            return (out, total) if total else (value, 0)
        if isinstance(value, (list, tuple)):
            items, total = [], 0
            for v in value:
                fixed, n = self.fix_value(v)
                items.append(fixed)
                total += n
            return (type(value)(items), total) if total else (value, 0)
        return value, 0

    def fix_row(self, row: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """A passage row (``text``, ``locator``) repaired: a new dict when anything changed, else the row itself."""
        text, a = self.fix(row.get("text") or "")
        locator, b = self.fix_value(row.get("locator"))
        if not (a or b):
            return row, 0
        return {**row, "text": text if a else row.get("text"), "locator": locator}, a + b

    def rows(self, rows: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
        """Passage rows repaired, and how many repairs were made in them."""
        out, total = [], 0
        for r in rows:
            fixed, n = self.fix_row(r)
            out.append(fixed)
            total += n
        return out, total


def repair_rows(rows: list[dict[str, Any]], repairs: ConversionRepairs | None) -> tuple[list[dict[str, Any]], int]:
    """``repairs.rows(rows)``, or the rows as they are without a table."""
    return repairs.rows(rows) if repairs else (rows, 0)


__all__ = ["ConversionRepairs", "Repair", "TABLE", "repair_rows"]
