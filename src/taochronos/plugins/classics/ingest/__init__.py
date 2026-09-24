"""Ingestion pipeline: catalogs + source connectors → the corpus store.

Sources are fetched into the data directory (never committed): ``taochronos corpus fetch <source>``.
``taochronos corpus ingest <source>`` parses them with the matching connector, dates every passage
according to the catalog (``corpus/catalog/*.yaml``), records provenance and licence per book, and builds
the full-text index.  Re-ingesting a book replaces it (idempotent).
"""

from __future__ import annotations

import math
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable

import yaml

from ..store import CorpusStore
from .kanripo import BookSpec, KanripoFile, KanripoParser, LayerSpec, read_file

Log = Callable[[str], None]


def load_catalog(path: str | Path) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    data["_path"] = str(path)
    return data


def _range(v: Any) -> tuple[int, int] | None:
    if v is None:
        return None
    if isinstance(v, int):
        return (v, v)
    return (int(v[0]), int(v[1]))


def _layer(raw: dict[str, Any] | None) -> LayerSpec | None:
    if not raw:
        return None
    return LayerSpec(raw["layer"], _range(raw["year"]) or (0, 0), raw.get("attribution", ""))


def book_spec(entry: dict[str, Any], catalog: dict[str, Any]) -> BookSpec:
    ed = entry.get("edition") or {}
    base = ed.get("base", "WYG")
    base_info = (catalog.get("editions") or {}).get(base, {})
    edition_year = _range(ed.get("year") or base_info.get("year"))
    markers = [(m["prefix"], LayerSpec(m["layer"], _range(m["year"]) or (0, 0), m.get("attribution", "")))
               for m in entry.get("markers") or []]
    return BookSpec(
        book_id=entry["id"],
        kr_id=entry["kr"],
        composition=_range(entry["composition"]) or (0, 0),
        edition_id=f"{entry['id']}@{base}",
        edition_year=edition_year,
        dynasty=entry.get("dynasty", ""),
        author_life=_range(entry.get("author_life")),
        note_order=entry.get("note_order", "AB"),
        notes=_layer(entry.get("notes")),
        markers=markers,
        indented_commentary=_layer(entry.get("indented_commentary")),
        mixed=_layer(entry.get("mixed")),
        cites=_range(entry.get("cites_work")),
        chapter_layers=[(c["pattern"], _layer(c)) for c in entry.get("chapter_layers") or []],  # type: ignore[misc]
        section_layers=[(c["pattern"], _layer(c)) for c in entry.get("section_layers") or []],  # type: ignore[misc]
    )


def book_record(entry: dict[str, Any], catalog: dict[str, Any], *, original_title: str | None = None,
                commit: str | None = None) -> dict[str, Any]:
    src = catalog.get("source") or {}
    ed = entry.get("edition") or {}
    base = ed.get("base", "WYG")
    base_info = (catalog.get("editions") or {}).get(base, {})
    aliases = list(dict.fromkeys([*(entry.get("aliases") or []), *([original_title] if original_title else [])]))
    aliases = [a for a in aliases if a and a != entry["title"]]
    layers = []
    for key in ("notes", "indented_commentary", "mixed"):
        if entry.get(key):
            layers.append({"kind": key, **entry[key]})
    for m in entry.get("markers") or []:
        layers.append({"kind": "marker", **m})
    for key in ("chapter_layers", "section_layers"):
        for c in entry.get(key) or []:
            layers.append({"kind": key, **c})
    url = (src.get("repo") or "").format(kr_lower=entry.get("kr", "").lower(), kr=entry.get("kr", ""))
    return {
        "id": entry["id"],
        "title": entry["title"],
        "aliases": aliases,
        "authors": list(entry.get("authors") or []),
        "dynasty": entry.get("dynasty", ""),
        "category": entry.get("category", ""),
        "composition": list(_range(entry["composition"]) or ()),
        "author_life": list(_range(entry.get("author_life")) or ()) or None,
        "dating_basis": entry.get("dating_basis", "composition"),
        "attribution": entry.get("attribution", "traditional"),
        "school": entry.get("school"),
        "work": entry.get("work"),
        "editions": [{
            "id": f"{entry['id']}@{base}", "name": ed.get("name") or base_info.get("name", base),
            "year": list(_range(ed.get("year") or base_info.get("year")) or ()) or None,
            "quality": float(ed.get("quality", base_info.get("quality", 0.5))),
        }],
        "source": {
            "origin": src.get("name", ""), "license": src.get("license", ""),
            "acquisition": f"{src.get('acquisition', '')}" + (f"; commit {commit}" if commit else ""),
            "url": url or src.get("url"), "transcription": src.get("transcription", ""), "verified": bool(src.get("verified", False)),
        },
        "notes": entry.get("notes_text", ""),
        "layers": layers,
        "source_id": src.get("id"),
        "source_ref": entry.get("kr"),
    }


def git_head(repo: Path) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


class BigramModel:
    """Character bigram log-probabilities over main text, used to check double-column note order."""

    def __init__(self) -> None:
        self.big: Counter = Counter()
        self.uni: Counter = Counter()

    def add(self, files: Iterable[KanripoFile]) -> None:
        import re
        for f in files:
            for pl in f.lines:
                main = re.sub(r"\([^()]*\)?", "", pl.raw).replace("　", "")
                self.uni.update(main)
                self.big.update(main[i: i + 2] for i in range(len(main) - 1))

    def __call__(self, a: str, b: str) -> float:
        v = max(1, len(self.uni))
        return math.log((self.big[a + b] + 0.1) / (self.uni[a] + 0.1 * v))


def ingest_kanripo(store: CorpusStore, catalog: dict[str, Any], sources: Path, normalize: Callable[[str], str],
                   fingerprint: str, *, only: Iterable[str] | None = None, log: Log = print,
                   dynasty_of: Callable[[float], str | None] | None = None) -> dict[str, Any]:
    from . import kanripo as _kanripo

    _kanripo.DYNASTY_OF = dynasty_of
    wanted = {x.lower() for x in only} if only else None
    entries = [e for e in catalog["books"] if wanted is None or e["kr"].lower() in wanted or e["id"].lower() in wanted]
    report: dict[str, Any] = {"source": "kanripo", "books": {}, "missing": [], "note_order_warnings": []}
    bigram = BigramModel()
    parsed: dict[str, list[KanripoFile]] = {}
    for e in entries:
        repo = sources / e["kr"]
        if not repo.exists():
            report["missing"].append(e["kr"])
            continue
        files = sorted(repo.glob(f"{e['kr']}_*.txt"))
        parsed[e["kr"]] = [read_file(p) for p in files]
        bigram.add(parsed[e["kr"]])
    for e in entries:
        if e["kr"] not in parsed:
            continue
        spec = book_spec(e, catalog)
        parser = KanripoParser(spec)
        n, diff = parser.note_order_scores(parsed[e["kr"]], bigram)
        detected = None if n < 5 else ("AB" if diff > 0 else "BA")
        if detected and detected != spec.note_order:
            report["note_order_warnings"].append({"book": spec.book_id, "catalog": spec.note_order, "detected": detected, "evidence": n})
        repo = sources / e["kr"]
        rows = parser.parse(repo)
        title = next((f.props.get("TITLE") for f in parsed[e["kr"]] if f.props.get("TITLE")), None)
        commit = git_head(repo)
        store.delete_book(spec.book_id, normalize)
        store.put_book(book_record(e, catalog, original_title=title, commit=commit), source="kanripo")
        store.add_passages(rows, normalize)
        store.commit()
        chars = sum(len(r["text"]) for r in rows)
        report["books"][spec.book_id] = {"kr": e["kr"], "passages": len(rows), "characters": chars, "commit": commit,
                                         "layers": parser.report["layers"], "notes": parser.report["notes"],
                                         "gaiji": parser.report["gaiji"], "line_width": parser.report.get("line_width"),
                                         "note_order": spec.note_order, "note_order_evidence": n}
        log(f"  {e['kr']} {spec.book_id:28s} {len(rows):6d} passages {chars:9d} chars")
    store.set_meta("normalizer", fingerprint)
    store.commit()
    return report


__all__ = ["BigramModel", "book_record", "book_spec", "git_head", "ingest_kanripo", "load_catalog"]
