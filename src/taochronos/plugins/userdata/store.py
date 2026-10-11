"""我的资料 — the data a user brings, kept where the runtime runs (in the browser, in its own storage), for the tools.

A dataset is a text (TXT, Markdown, Word) cut into passages, or a table (CSV, Excel, JSON) with typed columns, made
anonymous as it is read (:mod:`.deid`).  Its parts have ids the conversation can cite as it cites the classics:
``mine:<dataset>.<n>`` for the n-th passage of a text, ``mine:<dataset>.r<n>`` for the n-th row of a table.

The store holds what was read, not the file: the page keeps each dataset's exported form (``export``) in the browser's
own storage and gives it back at the next visit (``restore``); nothing is sent anywhere by the store.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from . import deid
from .formats import Parsed, Unreadable, read

MAX_DATASETS = 20
MAX_TOTAL_ROWS = 200_000
MAX_TOTAL_CHARS = 6_000_000
PASSAGE_CHARS = 400
_NUMBER = re.compile(r"^[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?$")
_DATE = re.compile(r"^(?:1[89]|20)\d{2}(?:[-/.年](?:0?[1-9]|1[0-2])(?:[-/.月](?:0?[1-9]|[12]\d|3[01])日?)?月?)?(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?$")
_SENTENCE_END = re.compile(r"(?<=[。！？；!?;])")


class NotFound(LookupError):
    """No such dataset, column, passage or row: the message says what there is."""


def number(cell: str) -> float | None:
    """A cell's number (1,234.5 → 1234.5; 12% → 12), or None."""
    c = cell.strip()
    if not _NUMBER.match(c):
        return None
    try:
        return float(c.rstrip("%").replace(",", ""))
    except ValueError:
        return None


@dataclass
class Dataset:
    id: str
    name: str
    kind: str  # "text" or "table"
    created: str
    bytes: int = 0
    passages: list[str] = field(default_factory=list)  # a text's passages
    columns: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    types: dict[str, str] = field(default_factory=dict)  # column → number, date, category, text (or prescription)
    deid: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.rows) if self.kind == "table" else sum(len(p) for p in self.passages)

    def part_id(self, i: int) -> str:
        """The citable id of the i-th (0-based) passage or row."""
        return f"mine:{self.id}.r{i + 1}" if self.kind == "table" else f"mine:{self.id}.{i + 1}"

    def column(self, name: str) -> int:
        """The index of a column, by its head (exact, or the only one containing the name)."""
        if name in self.columns:
            return self.columns.index(name)
        hits = [i for i, c in enumerate(self.columns) if name and name in c]
        if len(hits) == 1:
            return hits[0]
        raise NotFound(f"{self.name} 中没有列「{name}」（有：{'、'.join(self.columns[:30])}）")

    def values(self, name: str) -> list[str]:
        i = self.column(name)
        return [r[i] for r in self.rows]

    def summary(self, *, preview: int = 3) -> dict[str, Any]:
        """What the dataset is, for the page and the model: its size, its columns and their types, what was removed."""
        out: dict[str, Any] = {"id": self.id, "name": self.name, "kind": self.kind, "created": self.created}
        if self.kind == "table":
            out.update(rows=len(self.rows), columns=[{"name": c, "type": self.types.get(c, "text")} for c in self.columns],
                       preview=[dict(zip(self.columns, r)) for r in self.rows[:preview]])
        else:
            out.update(passages=len(self.passages), characters=self.size,
                       preview=[{"passage_id": self.part_id(i), "text": p[:120]} for i, p in enumerate(self.passages[:preview])])
        out["deidentified"] = self.deid
        if self.notes:
            out["notes"] = self.notes
        return out


def passages_of(text: str) -> list[str]:
    """A text cut into passages: its paragraphs, a long one cut after a sentence near ``PASSAGE_CHARS``."""
    out: list[str] = []
    for para in re.split(r"\n\s*\n|\n", text):
        para = para.strip()
        if not para:
            continue
        while len(para) > PASSAGE_CHARS * 1.5:
            cut = max((m.start() for m in _SENTENCE_END.finditer(para, 0, PASSAGE_CHARS + 120) if m.start() >= PASSAGE_CHARS // 2), default=PASSAGE_CHARS)
            out.append(para[:cut].strip())
            para = para[cut:].strip()
        if para:
            out.append(para)
    return out


def column_types(columns: list[str], rows: list[list[str]], detect: Callable[[list[str]], str | None] | None = None) -> dict[str, str]:
    """Each column's type, read from its cells: number (nine in ten are numbers), date, category (few distinct short
    values), text — or what ``detect`` says (the classics: prescription)."""
    out = {}
    for i, c in enumerate(columns):
        cells = [r[i] for r in rows if r[i].strip()]
        if not cells:
            out[c] = "empty"
            continue
        sample = cells[:5000]
        kind = detect(sample) if detect else None
        if kind:
            out[c] = kind
        elif sum(1 for v in sample if number(v) is not None) >= 0.9 * len(sample):
            out[c] = "number"
        elif sum(1 for v in sample if _DATE.match(v.strip())) >= 0.9 * len(sample):
            out[c] = "date"
        else:
            distinct = len(set(sample))
            avg = sum(len(v) for v in sample) / len(sample)
            out[c] = "category" if (distinct <= max(12, 0.05 * len(sample)) or distinct <= 0.5 * len(sample)) and avg <= 16 else "text"
    return out


class UserData:
    """The user's datasets in this runtime.  ``normalize`` folds a text for search (the domain's variants); ``detect``
    tells a column's special type from its cells (the classics: a column of prescriptions)."""

    def __init__(self, *, normalize: Callable[[str], str] | None = None, detect: Callable[[list[str]], str | None] | None = None) -> None:
        self.sets: dict[str, Dataset] = {}
        self.normalize = normalize or (lambda t: t)
        self.detect = detect

    # ------------------------------------------------------------ in and out
    def add(self, name: str, data: bytes) -> Dataset:
        """Read a file, make it anonymous and keep it; raises :class:`Unreadable` with the reason when it cannot."""
        if len(self.sets) >= MAX_DATASETS:
            raise Unreadable(f"我的资料至多 {MAX_DATASETS} 份：请先删去不用的")
        parsed = read(name, data)
        digest = hashlib.sha1(data).hexdigest()[:8]
        ds = self._dataset(name, parsed, digest, len(data))
        rows = sum(len(d.rows) for d in self.sets.values()) + len(ds.rows)
        chars = sum(d.size for d in self.sets.values() if d.kind == "text") + (ds.size if ds.kind == "text" else 0)
        if rows > MAX_TOTAL_ROWS or chars > MAX_TOTAL_CHARS:
            raise Unreadable("我的资料已满：请先删去不用的")
        self.sets[ds.id] = ds
        return ds

    def _dataset(self, name: str, parsed: Parsed, digest: str, size: int) -> Dataset:
        base = re.sub(r"[^0-9a-z]", "", digest.lower())[:6] or "data"
        ds_id, k = f"d{base}", 2
        while ds_id in self.sets:
            ds_id, k = f"d{base}{k}", k + 1
        created = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
        if parsed.kind == "table":
            rows, report = deid.table(parsed.columns, parsed.rows)
            return Dataset(ds_id, name, "table", created, size, columns=parsed.columns, rows=rows,
                           types=column_types(parsed.columns, rows, self.detect), deid=report, notes=parsed.notes)
        text, report = deid.text(parsed.text)
        return Dataset(ds_id, name, "text", created, size, passages=passages_of(text), deid=report, notes=parsed.notes)

    def export(self, ds_id: str) -> dict[str, Any]:
        """A dataset as plain data, to keep in the browser and give back with :meth:`restore`."""
        return {"v": 1, **asdict(self.get(ds_id))}

    def restore(self, data: dict[str, Any]) -> Dataset:
        fields = {k: data[k] for k in Dataset.__dataclass_fields__ if k in data}
        ds = Dataset(**fields)
        if ds.kind == "table" and not ds.types:
            ds.types = column_types(ds.columns, ds.rows, self.detect)
        self.sets[ds.id] = ds
        return ds

    def remove(self, ds_id: str) -> bool:
        return self.sets.pop(self.get(ds_id).id, None) is not None

    def clear(self) -> int:
        n = len(self.sets)
        self.sets.clear()
        return n

    # ------------------------------------------------------------ reading
    def get(self, key: str) -> Dataset:
        """A dataset by its id or its file name (or the only one there is, when ``key`` is empty)."""
        key = (key or "").strip()
        if not key and len(self.sets) == 1:
            return next(iter(self.sets.values()))
        if key in self.sets:
            return self.sets[key]
        hits = [d for d in self.sets.values() if d.name == key] or [d for d in self.sets.values() if key and key in d.name]
        if len(hits) == 1:
            return hits[0]
        known = "、".join(f"{d.id}「{d.name}」" for d in self.sets.values()) or "（还没有上传资料）"
        raise NotFound(f"没有这份资料：{key or '（未指明）'}；我的资料：{known}")

    def list(self) -> list[dict[str, Any]]:
        return [d.summary() for d in self.sets.values()]

    def part(self, part_id: str) -> tuple[Dataset, int]:
        """The dataset and index of a ``mine:`` id."""
        m = re.fullmatch(r"mine:([0-9a-z]+)\.(r?)(\d+)", part_id or "")
        if not m:
            raise NotFound(f"不是我的资料的段落号：{part_id}")
        ds = self.get(m.group(1))
        i = int(m.group(3)) - 1
        size = len(ds.rows) if ds.kind == "table" else len(ds.passages)
        if (m.group(2) == "r") != (ds.kind == "table") or not 0 <= i < size:
            raise NotFound(f"{ds.name} 中没有 {part_id}")
        return ds, i

    def card(self, part_id: str) -> dict[str, Any]:
        """A passage or row in full, as the evidence drawer shows a passage of the classics."""
        ds, i = self.part(part_id)
        if ds.kind == "table":
            text = "；".join(f"{c}：{v}" for c, v in zip(ds.columns, ds.rows[i]) if v)
            locator = f"第 {i + 1} 行"
        else:
            text, locator = ds.passages[i], f"第 {i + 1} 段"
        return {"passage_id": part_id, "book_id": f"mine:{ds.id}", "title": ds.name, "locator": locator, "text": text,
                "dynasty": "我的资料", "mine": True}

    def read(self, key: str, *, start: int = 1, limit: int = 20, columns: list[str] | None = None) -> dict[str, Any]:
        ds = self.get(key)
        start, limit = max(1, int(start)), max(1, min(int(limit), 200))
        if ds.kind == "table":
            idx = [ds.column(c) for c in columns] if columns else list(range(len(ds.columns)))
            heads = [ds.columns[i] for i in idx]
            rows = [{"passage_id": ds.part_id(n), **{h: ds.rows[n][i] for h, i in zip(heads, idx)}}
                    for n in range(start - 1, min(start - 1 + limit, len(ds.rows)))]
            return {"dataset": ds.id, "name": ds.name, "kind": "table", "rows_total": len(ds.rows), "start": start, "rows": rows}
        items = [{"passage_id": ds.part_id(n), "text": ds.passages[n]} for n in range(start - 1, min(start - 1 + limit, len(ds.passages)))]
        return {"dataset": ds.id, "name": ds.name, "kind": "text", "passages_total": len(ds.passages), "start": start, "passages": items}

    def search(self, query: str, *, key: str | None = None, limit: int = 30, window: int = 40) -> dict[str, Any]:
        """Where the user's data writes ``query`` (each term of it, after the domain's folding): the passages and rows,
        with the words around it."""
        terms = [t for t in re.split(r"[\s,，、;；]+", query.strip()) if t]
        if not terms:
            raise ValueError("给出要检索的词")
        sets = [self.get(key)] if key else list(self.sets.values())
        if not sets:
            raise NotFound("还没有上传资料")
        folded = [self.normalize(t) for t in terms]
        hits, total = [], 0
        for ds in sets:
            parts = ([("；".join(f"{c}：{v}" for c, v in zip(ds.columns, r) if v)) for r in ds.rows] if ds.kind == "table" else ds.passages)
            for i, text in enumerate(parts):
                norm = self.normalize(text)
                if not all(t in norm for t in folded):
                    continue
                total += 1
                if len(hits) >= limit:
                    continue
                at = norm.find(folded[0])
                lo = max(0, at - window)
                hits.append({"passage_id": ds.part_id(i), "dataset": ds.id, "name": ds.name,
                             "text": ("…" if lo else "") + text[lo: at + len(folded[0]) + window] + ("…" if at + len(folded[0]) + window < len(text) else "")})
        return {"query": query, "terms": terms, "hits": hits, "total": total}


__all__ = ["Dataset", "NotFound", "UserData", "column_types", "number", "passages_of"]
