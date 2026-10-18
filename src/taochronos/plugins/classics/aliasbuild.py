"""Building the alias layer (ADR 0023): ``domains/classics/aliases/aliases.jsonl`` and ``context.json``.

``build_open(store, home)`` reads only what may ship: the CC0 本草纲目别名录 in the store (book ``jc_c030``), the editors'
decisions (``curated.yaml``, each with a witness passage), the herb pairs of ``taboo.yaml``, the 本草纲目's 释名 brackets
(``a（唐本）`` under its drug), the NTU table (CC BY-NC 4.0) from its committed extract ``corpus/aliases/ntu40k.tsv``
while sources.yaml ships it, the full-corpus lexicon and the store's texts.  It takes no local input.  An NTU pair
(PrimaryDrugName → AlternateName) enters only when its head (or a curated same-drug member) or its name is a lexicon
herb or written in the store; an ethnic-language name is a folk name (the language in its note, with the places its
remark names), and the earliest classical work its remark cites (sources.yaml ``works``) is its credit (``cr``).
``build_local(open_result, local_pairs, store)`` adds the pairs imported under ``<data>/aliases/local/`` (hurbTable,
the GB 别名录; not a list that ships, which open_pairs reads), counted with the shipped ``context.json`` (the herb set
its profile loads), and is written only under ``<data>``.

For every pair (name, drug) the build

* groups the drugs: a curated same-drug group, or heads the full-corpus lexicon files under one entry, are one drug
  (its canonical head: the group's first name, else the lexicon's headword); a lexicon entry that files two or more of
  a drug's names again under another headword (亭历 beside 葶苈) joins it; every member's record carries the drug as
  ``ho``, and a member no pair ties to it gets one (牡丹皮 → 牡丹), so each reaches the other; a name with only a
  first-use or taboo floor (党参) heads a drug of its own; the NTU table's heads come after, changing none of these
  drugs: one the editors or the others tie to drugs as a part, an older name, within a window, as a cue or to two
  drugs is kept apart, its entry giving no drug (青木香, 小草, 通草); else each joins the drug of the lexicon entry it
  heads, or the drug whose names its own share two or more of (七叶一枝花 joins 蚤休) among those that name it, that
  its lexicon entry files the head of or that it names with or without the part the drug is (牛蒡 and 牛蒡子) — only
  one the others give it when they give it any — else heads a drug of its own;
* adds the lexicon's other herb entries for the name as rival referents (source ``lexicon``);
* finds up to three witnesses outside ``jc_c030`` and the ``NEVER_PACKED`` sources: the earliest equation (h，一名a; a即h;
  not 一作, a variant reading), gloss (h（a）) or 本草 entry (headed by h, 一名a in its first 400 characters), each name
  standing whole (not 栝楼|根，一名地楼), then the 别名录 entry itself; a pair a store witness confirms is credited
  ``store`` (古籍互证) too;
* collects blockers — the curated cover strings, then longer herb or alias names holding the name whose drug is another
  (a window where they mean the same drug in some periods only) and names that straddle an occurrence in the store
  (石蜜|甘; only the name the straddle cuts: 常山|甘草 cuts 山甘草, not 常山), ordered by how many passages write
  them; never the strings curated.yaml unblocks for the name (青矾石 is 青矾), nor the 本草纲目's joint headings that
  the lexicon harvested as one name and the store nowhere writes as one (假苏荆芥, 赤箭天麻);
* counts with the runtime's own gates (``AliasIndex.free_offsets``, ``drug_context``) the passages that write the name
  free of its blockers (``n``) and the share of them that read it as a drug (``sh``), with cues that are the drug's
  head and its other names that may be read as it (no candidate, none written 20 times and mostly not as a drug);
* gives each pair its status by the first rule that holds: a curated decision; damaged (``DOUBT_FLAGS``) or under a
  one-character head → candidate; another drug's headword → candidate (another drug's head too, but a head only the
  NTU table gives demotes only the table's own pairs); a pair only the NTU table gives, its name written in the store
  free of its blockers, under 50 % of those passages as a drug and with no store witness → candidate (5b), as is one
  whose name reads as a formula's or a class of drugs' (镇心丹, 止血药: 5c), as is one whose drug shares two names or
  more with a drug the other sources give the name (荜澄茄 beside 毕澄茄: 5d — no rival then); two drugs or more → cue;
  written 20 times or more and under 10 % as a drug → stop (for review; a candidate when the name heads the drug);
  under 30 % → cue; two characters → cue; else open.  A pair only a local list gives also needs a passage before 1912 that reads it as a
  drug, else it is a candidate;
* sets soft floors (the earliest taboo year over herb pairs, else a curated first use) and hard windows (curated only);
* reports what editors should look at: 别名录 heads nothing writes (garbled: 蘆藜), lexicon rivals sharing names with
  another of the name's drugs, drugs named by an unwritten name, cover strings past the cap.

Everything is sorted before it is written: the same inputs give the same bytes.  The header fingerprints the inputs:
the store (:func:`store_label`), the normaliser, the lexicon, the NTU extract read (``ntu40k``) and, where the layer
follows it, the 要籍语料's pack
(``web_pack``, :func:`pack_fingerprint`): on a full store the pack sets each witness's ``web`` flag; the web store is
the pack made into a store, and the header names the pack only when the store holds exactly the pack's passages, row
for row and column for column as ``webcorpus.build_store`` writes them (a pack written again after a text or heading fix
keeps its ids: a store made of the old one does not claim the new).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import time
import zlib
from collections import defaultdict
from contextlib import nullcontext
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from ...protocol.base import canonical_dumps
from ...protocol.yamlio import load_yaml
from .aliases import (CONTEXT_PATTERNS, FORMULA_ENDS, KINDS, MAX_BLOCKERS, MAX_CUES, MAX_RAW, MAX_WITNESSES, STATUSES,
                      WITNESS_KINDS, AliasIndex, AliasRecord, Referent, Witness, dumps_records, loads_records, gate_form)
from .domain import DomainPack
from .ingest.aliases import BOOK, DOUBT_FLAGS, LOCAL_SOURCES, NTU_EXTRACT, read_bielu_store, read_ntu
from .store import CorpusStore, StoreCorpus, is_han
from .study.names import EQUATE as NAMES_EQUATE

ALIAS_DIR = "aliases"  # under the domain: sources.yaml, curated.yaml, aliases.jsonl, context.json
FILES = ("aliases.jsonl", "context.json", "curated.yaml", "sources.yaml")
LEXICON_EXTRA = ("lexicon-supplement", "lexicon-harvested")  # the full-corpus profile's lexicon
WEB_PACK = Path("corpus") / "web" / "passages.jsonl.gz"  # the 要籍语料's pack, under the home
LOCAL_FILE = "aliases-local.jsonl"  # <data>/aliases/local/: the shipped records and the local pairs, re-classified
BIELU_ENTRIES = 1086  # entries of the whole 别名录 (the web store's excerpt has 778)
NTU = "ntu40k"  # the NTU table's id in sources.yaml: read from its committed extract (NTU_EXTRACT) when it ships
CLASSES = ("open", "nc", "derived", "local")  # sources.yaml's classes; every one but local may ship
MODERN = "modern"  # a book of sources.yaml's works that is modern: it credits nothing
# aliases.jsonl raw and deflated; the directory deflated file by file, as home.zip stores it.  With the NTU table the
# layer holds about 18,400 names on the web store (3,402,245 / 824,525 bytes, the directory 893,846; set at 3,461,929 /
# 844,728 / 913,724 + 40 %), for the rebuild on the full store (more of the table's pairs, the whole 别名录: not
# measured yet) and curation.  The browser downloads the directory once with home.zip (cached after) and reads it in
# about 0.6 s in Pyodide (0.4 s in CPython); the Worker's tables.js carries the records the full-corpus profile reads,
# the whole Worker within Workers Free's 3 MB compressed (tests/test_d1.py) and its start within 1 s
# (cloud/test/backup.test.js)
BUDGET = {"raw": 4_900_000, "deflated": 1_200_000, "directory": 1_300_000}
STOP_N, STOP_SHARE, CUE_SHARE = 20, 0.10, 0.30  # status rules 7 and 8
LIST_SHARE = 0.50  # a pair only the NTU table gives, its name written in the store: the share it needs (5b)
# the NTU table's heads: a drug named with or without the part it is (牛蒡 and 牛蒡子, 龙眼 and 龙眼肉, 地锦 and 地锦草)
# is one drug; a name the editors or the other sources tie to a drug as a part or an older name, or within a period
# window, is never joined to it (青木香, 小草, 通草)
SAME_FORM = "子仁实肉草"
APART_KINDS = ("part_name", "old_name")
# a name only the NTU table gives that reads as a formula's or a class of drugs (镇心丹, 清凉膏, 止血药): ends in one of
# these, at most 8 characters, and no lexicon herb nor a name the other sources give → candidate (rule 5c)
LIST_ENDS = FORMULA_ENDS + "药"
LOCAL_BEFORE = 1912  # a local-only pair needs a passage before this year that reads it as a drug
MAX_NAME = 8  # the longest name a straddle is read with
STRADDLE_RATIO = 2  # a name standing whole beside a straddler is not cut by it unless the straddler is written this
#                     many times as often (又方|石硫黄)
# equation words: those of ``study names`` but 一作 and 或作 (a variant reading, not another name), and 一曰, 谓之, 呼为
EQUATE = "(?:" + "|".join([w for w in NAMES_EQUATE[3:-1].split("|") if w not in ("一作", "或作")]
                          + ["一曰", "谓之", "呼为"]) + ")"
# curated.yaml: each section's row keys (required, optional); cover_stops and unblock are {name: [strings holding it]}
CURATED_MAPS = ("cover_stops", "unblock")
CURATED = {
    "repairs": ({"from", "to"}, set()),
    "head_repairs": ({"passage", "head", "wit"}, {"why"}),
    "same_drug": ({"names", "wit"}, {"why"}),
    "pairs": ({"s", "head", "wit"}, {"kind", "status", "valid", "cues", "anti", "why", "note"}),
    "first_use": ({"s", "year", "wit"}, {"why"}),
    "stop": ({"s", "wit"}, {"why"}),
    "decisions": ({"s", "status", "wit"}, {"head", "why"}),
}
KIND_ORDER = ("taboo_rename", "spelling", "old_name", "part_name", "processing_variant", "variety", "abbreviation",
              "folk", "alias")  # the kind a referent takes when its pairs differ: the most specific
_HAN = "\u3400-\u9fff\uf900-\ufaff\U00020000-\U0003134f\u3007\u3013"  # what is_han accepts
_RUBRIC = ("集解", "气味", "主治", "发明", "附方", "正误", "修治", "校正", "释名")
# a section's numbering: digits, or numerals before a separator or three or more of them (一八一梔子); never the
# numeral a drug's name opens with (五味子, 百合, 三七).  Its zero is 〇 (U+3007) or ○ (U+25CB), as editions write it
# (一○七　白石脂).  evals/aliases_gold.py reads headings with the same pattern, and a test holds the two equal
_SECTION_NUM = re.compile(r"^(?:[0-9]+|[〇○一二三四五六七八九十百千]{3,}|[〇○一二三四五六七八九十百千]+(?=[、.．\s　]))[、.．\s　]*")
_LEAD = re.compile(f"^([{_HAN}]{{1,6}}?)(?:\\||味)")  # a 本草 entry that opens with its drug: 赤箭　味辛温 · 丹砂，一名朱砂


def _n(value: Any) -> str:
    return "" if value is None else str(value)


# a passage's columns as the store holds them (``CorpusStore.add_passages``, which ``webcorpus.build_store`` writes the
# pack with): what the web store must hold row for row to be the pack made into a store — its JSON columns last
_PASSAGE_COLUMNS = ("id", "book_id", "edition_id", "seq", "kind", "layer", "year", "y_start", "y_end", "text",
                    "punctuation", "locator", "temporal", "extra")


def _is_stored(line: bytes, row: tuple[Any, ...] | None) -> bool:
    """Whether a store's passage row (:data:`_PASSAGE_COLUMNS`) is the pack line made into one: the same values, a
    locator and a temporal context without their empty fields, as the store keeps them."""
    if row is None:
        return False
    try:
        r = json.loads(line)
        if row[:11] != (r["id"], r["book_id"], r.get("edition_id"), r["seq"], r.get("kind", "text"), r.get("layer"),
                        r.get("year"), r.get("y_start"), r.get("y_end"), r["text"], r.get("punctuation", "none")):
            return False
        loc, tem = json.loads(row[11]), json.loads(row[12])
        return (loc == {k: v for k, v in r["locator"].items() if v is not None}
                and tem == {k: v for k, v in r["temporal"].items() if v is not None}
                and json.loads(row[13]) == (r.get("extra") or {}))
    except (ValueError, TypeError, KeyError, AttributeError):
        return False


def _window(value: Any) -> tuple[int | None, int | None] | None:
    if not value:
        return None
    lo, hi = value
    return None if lo is None and hi is None else (lo, hi)


def _complement(windows: list[tuple[int | None, int | None]]) -> list[tuple[int | None, int | None]]:
    """The years outside every window, as [from, to) windows."""
    out: list[tuple[int | None, int | None]] = []
    cursor: int | None = None  # None: from the beginning of time
    started = False
    for lo, hi in sorted(windows, key=lambda w: (-10 ** 9 if w[0] is None else w[0])):
        if lo is not None and (not started or (cursor is not None and lo > cursor)):
            out.append((cursor if started else None, lo))
        started = True
        if hi is None:
            return out
        cursor = hi if cursor is None or hi > cursor else cursor
    out.append((cursor, None))
    return out


def deflated(data: bytes) -> int:
    """Bytes ``data`` takes raw-deflated at zlib's default level, as ``home.zip`` stores it (its entries are written
    from a ``ZipInfo``, which takes the default level, not the archive's)."""
    z = zlib.compressobj(zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, -15)
    return len(z.compress(data) + z.flush())


def store_label(db: CorpusStore) -> dict[str, Any]:
    """What the header records of the store a build ran on: a digest of its counts, its books and passages."""
    books = db.db.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    passages, last = db.db.execute("SELECT COUNT(*), MAX(rid) FROM passages").fetchone()
    basis = db.meta("counted") or f"{passages}:{last}"
    sha = hashlib.sha256(f"{db.meta('edition') or 'full'}\n{db.meta('normalizer')}\n{basis}".encode()).hexdigest()
    return {"sha": sha[:12], "books": books, "passages": passages}


def pack_fingerprint(path: str | Path) -> str:
    """sha256[:12] of the 要籍语料's pack uncompressed (``corpus/web/passages.jsonl.gz``: the digest ``taochronos web
    pack`` reports), so that a pack written again with another zlib reads alike."""
    digest = hashlib.sha256()
    with gzip.open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()[:12]


def read_yaml(path: str | Path) -> Any:
    """A YAML file of the alias directory (curated.yaml, sources.yaml): its content, None when it is empty;
    ``ValueError`` when it is not UTF-8 or not YAML at all, naming the file and where the parser stopped."""
    try:
        return load_yaml(path)
    except UnicodeDecodeError as exc:
        raise ValueError(f"{Path(path).name} is not valid YAML: not UTF-8 at byte {exc.start}") from None
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" at line {mark.line + 1}, column {mark.column + 1}" if mark is not None else ""
        problem = getattr(exc, "problem", None) or " ".join(str(exc).split())
        raise ValueError(f"{Path(path).name} is not valid YAML: {problem}{where}") from None


def read_registry(path: str | Path) -> dict[str, Any]:
    """sources.yaml, the source registry (``sources``: a list of mappings, ``works``: a mapping of a title to its
    [first, last] years, or to ``modern``), {} when it is empty; ``ValueError`` in a sentence when it is not YAML
    (:func:`read_yaml`) or not of that shape."""
    data = read_yaml(path)
    if data is None:
        return {}
    name = Path(path).name
    # a file's shape, reported as its other faults are (ValueError, which the CLI says in a sentence)
    if not isinstance(data, dict):
        raise ValueError(f"{name}: the top level is not a mapping")  # noqa: TRY004
    if not isinstance(data.get("sources") or [], list) or not all(isinstance(x, dict) for x in data.get("sources") or []):
        raise ValueError(f"{name}: sources is not a list of mappings")
    if not isinstance(data.get("works") or {}, dict):
        raise ValueError(f"{name}: works is not a mapping")  # noqa: TRY004
    for title, years in (data.get("works") or {}).items():
        if not (years == MODERN or (isinstance(years, list) and len(years) == 2
                                    and all(type(y) is int for y in years) and years[0] <= years[1])):
            raise ValueError(f"{name}: works {title} is not [first, last] years or {MODERN}")
    return data


def lexicon_fingerprint(root: Path) -> str:
    """sha256[:12] of the full-corpus lexicon's files (path and bytes, in path order)."""
    digest = hashlib.sha256()
    for d in ("lexicon", *LEXICON_EXTRA):
        for path in sorted((root / d).glob("*.yaml")):
            digest.update(f"{d}/{path.name}\0".encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def gangmu_titles(root: Path, normalize: Any) -> set[str]:
    """The herbs the full-corpus lexicon harvested from 本草纲目 entry titles (pattern ``gangmu-entry``), normalised:
    where the 纲目 heads one entry with two names (赤箭天麻, 假苏荆芥), the harvest took the heading for one name."""
    out: set[str] = set()
    for path in (p for d in LEXICON_EXTRA for p in sorted((root / d).glob("*.yaml"))):
        data = load_yaml(path) or {}
        for block in data if isinstance(data, list) else [data]:
            for e in block.get("entries") or []:
                if (isinstance(e, dict) and e.get("category", block.get("category")) == "herb"
                        and "gangmu-entry" in ((e.get("evidence") or {}).get("patterns") or {})):
                    out.add(normalize(e["term"]))
    return out


def validate_curated(curated: Any) -> list[str]:
    """What is wrong with curated.yaml's shape: an unknown section or row key, a missing one, a value of the wrong
    type, an unknown kind or status, a name of fewer than two characters, a row without a witness or citing the 别名录
    itself, a cover or unblock string that does not hold its name, more cover strings than a record keeps, a string
    both a cover string and unblocked."""
    if not isinstance(curated, Mapping):
        return ["curated.yaml: not a mapping"]
    errors = [f"curated.yaml: unknown section {k}" for k in curated if k not in CURATED and k not in ("version",
                                                                                                    *CURATED_MAPS)]
    if curated.get("version", 1) != 1:
        errors.append("curated.yaml: version must be 1")

    def name(row: Mapping[str, Any], key: str, where: str, short: bool = False) -> None:
        value = row.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{where}: {key} must be a name")
        elif not short and sum(map(is_han, value)) < 2:
            errors.append(f"{where}: {key} {value} has fewer than two characters")

    for section, (required, optional) in CURATED.items():
        rows = curated.get(section) or []
        if not isinstance(rows, list):
            errors.append(f"curated.yaml {section}: not a list")
            continue
        for i, row in enumerate(rows):
            where = f"curated.yaml {section}[{i}]"
            if not isinstance(row, Mapping):
                errors.append(f"{where}: {row!r} is not a mapping")
                continue
            errors += [f"{where}: no {k}" for k in sorted(required - set(row) - {"wit"})]
            errors += [f"{where}: unknown key {k}" for k in sorted(set(row) - required - optional)]
            wit = row.get("wit")
            if "wit" in required and (not isinstance(wit, list) or not wit or not all(isinstance(p, str) for p in wit)):
                errors.append(f"{where}: no witness passage (wit: a list of passage ids)")
            elif wit and any(p.startswith(f"{BOOK}.") for p in wit):
                errors.append(f"{where}: a witness from the 别名录 ({BOOK}) itself")
            for key in ("why", "note"):
                if key in row and not isinstance(row[key], str):
                    errors.append(f"{where}: {key} must be text")
            if section == "repairs":
                name(row, "from", where, short=True)
                name(row, "to", where, short=True)
            elif section == "head_repairs":
                name(row, "passage", where, short=True)
                name(row, "head", where, short=True)
            elif section == "same_drug":
                names = row.get("names")
                if (not isinstance(names, list) or len(names) < 2 or len(set(map(str, names))) < len(names)
                        or not all(isinstance(x, str) and x.strip() for x in names)):
                    errors.append(f"{where}: names must list two names or more")
            else:
                name(row, "s", where)
                if row.get("head") is not None or section == "pairs":
                    name(row, "head", where, short=True)
            if "kind" in row and row["kind"] not in KINDS:
                errors.append(f"{where}: unknown kind {row['kind']}")
            if "status" in row and row["status"] not in STATUSES:
                errors.append(f"{where}: unknown status {row['status']}")
            if section == "first_use" and type(row.get("year")) is not int:
                errors.append(f"{where}: year must be a whole year")
            if "valid" in row:
                v = row["valid"]
                ok = (isinstance(v, list) and len(v) == 2 and all(x is None or type(x) is int for x in v)
                      and v != [None, None] and (None in v or v[0] < v[1]))
                if not ok:
                    errors.append(f"{where}: valid must be [from, to) years, one of them null at most")
            for key in ("cues", "anti"):
                if key in row and (not isinstance(row[key], list) or not all(isinstance(c, str) for c in row[key])):
                    errors.append(f"{where}: {key} must list names")
    maps: dict[str, Mapping[Any, Any]] = {}
    for section in CURATED_MAPS:
        maps[section] = curated.get(section) or {}
        if not isinstance(maps[section], Mapping):
            errors.append(f"curated.yaml {section}: not a mapping")
            maps[section] = {}
        for key, strings in maps[section].items():
            where = f"curated.yaml {section} {key}"
            if not isinstance(key, str) or sum(map(is_han, key)) < 2:
                errors.append(f"{where}: the name must have two characters or more")
            if not isinstance(strings, list) or not all(isinstance(x, str) for x in strings):
                errors.append(f"{where}: must list strings")
                continue
            errors += [f"{where}: {x} does not hold {key}" for x in strings if str(key) not in x or x == key]
            if section == "cover_stops" and len(set(strings)) > MAX_BLOCKERS:
                errors.append(f"{where}: {len(set(strings))} strings, over the {MAX_BLOCKERS} blockers a record keeps")
    for key, strings in maps["unblock"].items():
        both = set(_strings(strings)) & set(_strings(maps["cover_stops"].get(key)))
        errors += [f"curated.yaml unblock {key}: {x} is a cover string of it too" for x in sorted(both)]
    return errors


def _strings(value: Any) -> list[str]:
    return [x for x in value if isinstance(x, str)] if isinstance(value, list) else []


def entry_head(section: str | None, normalize: Any) -> str | None:
    """The drug a 本草 section is headed by: the innermost heading, numbering and bracketed glosses dropped."""
    s = re.sub(r"[（(][^）)]*[）)]", "", normalize((section or "").split(" · ")[-1])).strip()
    s = _SECTION_NUM.sub("", s).strip()
    return s if re.fullmatch(f"[{_HAN}]{{1,6}}", s) else None


# --------------------------------------------------------------------------- the pairs
@dataclass
class Pair:
    """A name given for a drug by one source."""

    s: str
    h: str
    src: str
    kind: str = "alias"
    doubt: bool = False  # a DOUBT_FLAGS token: a lost character, a join, a truncated note
    raw: str = ""
    wit: list[Witness] = field(default_factory=list)  # the list's own passage, a 释名 block, curated witnesses
    status: str | None = None  # curated
    valid: tuple[int | None, int | None] | None = None  # curated
    cues: list[str] = field(default_factory=list)
    anti: list[str] = field(default_factory=list)
    note: str = ""
    cr: tuple[str, int | None, int | None] | None = None  # 释名: the work credited
    local: bool = False


@dataclass
class BuildResult:
    """What a build made: the records, ``context.json``, the header's metadata and a report."""

    records: list[AliasRecord]
    context: dict[str, Any]
    meta: dict[str, Any]
    report: dict[str, Any]
    stopped: dict[str, list[str]] = field(default_factory=dict)  # rule-7 stops: the referents they had, for review
    builder: Any = None

    def text(self) -> str:
        return dumps_records(self.records, self.meta)

    def context_text(self) -> str:
        return canonical_dumps(self.context) + "\n"

    def write(self, out_dir: Path | str, name: str = "aliases.jsonl", context: bool = True) -> dict[str, Any]:
        """Write the records (and ``context.json``) into ``out_dir``; their sizes raw and deflated."""
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        sizes = {}
        files = [(name, self.text())] + ([("context.json", self.context_text())] if context else [])
        for fname, text in files:
            data = text.encode("utf-8")
            (out / fname).write_bytes(data)
            sizes[fname] = {"raw": len(data), "deflated": deflated(data)}
        return sizes


class _Groups:
    """Union-find over head names: a curated same-drug group, or heads of one lexicon entry, are one drug."""

    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def add(self, x: str) -> None:
        self.parent.setdefault(x, x)

    def find(self, x: str) -> str:
        self.add(x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)

    def components(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = defaultdict(list)
        for x in sorted(self.parent):
            out[self.find(x)].append(x)
        return out


# --------------------------------------------------------------------------- the build
class Builder:
    """One build's inputs and caches: the pack, the store, the registry, the curated decisions and the passages read."""

    def __init__(self, store: CorpusStore | str | Path, home: str | Path) -> None:
        self.home = Path(home)
        self.root = self.home / "domains" / "classics"
        self.dir = self.root / ALIAS_DIR
        self.registry = read_registry(self.dir / "sources.yaml")
        curated = self.dir / "curated.yaml"
        self.curated: dict[str, Any] = (read_yaml(curated) or {}) if curated.exists() else {}
        errors = validate_curated(self.curated)
        if errors:
            raise ValueError("\n".join(errors))
        self.taboo = load_yaml(self.root / "taboo.yaml") or {}
        self.pack = DomainPack(self.root, extra_lexicons=LEXICON_EXTRA)
        self.norm = self.pack.variants.normalize_text
        self.db = store if isinstance(store, CorpusStore) else CorpusStore(store, readonly=True)
        self.corpus = StoreCorpus(self.db, self.norm, exclude_books=(BOOK,))
        self.edition = self.db.meta("edition") or "full"
        self.sources = {s["id"]: s for s in self.registry.get("sources") or []}
        works = self.registry.get("works") or {}
        self.works = {self.norm(k): (v[0], v[1]) for k, v in works.items() if v != MODERN}  # a title → its years
        self.modern = {self.norm(k) for k, v in works.items() if v == MODERN}
        self.extract: str | None = None  # sha256[:12] of the NTU extract a build read
        self.notes_ntu: dict[str, Any] = {}  # what the NTU table's reading leaves out and how its remarks cite
        from .webcorpus import NEVER_PACKED

        self.never = {b for b, src in self.corpus.sources.items() if src in NEVER_PACKED}
        self.bencao = {b for b, book in self.corpus.books.items() if book.category == "本草"}
        # the full-corpus lexicon's herbs, normalised
        self.herb_terms: dict[str, set[str]] = defaultdict(set)  # surface → term ids
        self.headwords: dict[str, set[str]] = defaultdict(set)  # headword → term ids
        self.term_head: dict[str, str] = {}
        self.term_names: dict[str, set[str]] = defaultdict(set)  # term id → its surfaces
        self.lex_kind: dict[tuple[str, str], str] = {}
        for e in self.pack.lexicon.by_category("herb"):
            head = self.norm(e.term)
            self.term_head[e.term_id] = head
            self.headwords[head].add(e.term_id)
            for s in e.surfaces():
                ns = self.norm(s)
                self.herb_terms[ns].add(e.term_id)
                self.term_names[e.term_id].add(ns)
                kind = e.synonyms.get(s)
                if kind:
                    self.lex_kind[(ns, e.term_id)] = kind
        self.gangmu_titles = gangmu_titles(self.root, self.norm)
        self._web: set[str] | None = None
        self._pack: tuple[str | None, bool] | None = None  # the pack's fingerprint; whether the web store is made of it
        self._web_pack: str | None = None
        self._web_pack_read = False
        self._rows: dict[str, tuple[str, int | None, int | None, str | None]] = {}  # pid → book, y0, y1, 本草 heading
        self._text: dict[str, str] = {}  # pid → normalised text
        self._gate: dict[str, str] = {}
        self._ids: dict[str, list[str]] = {}  # surface → passages that may write it
        self._bielu: list[Any] | None = None
        self._drugs: dict[str, set[str]] = {}
        self._refs: dict[str, dict[str, Referent]] = {}
        self._longer: dict[str, list[str]] = {}  # a name → the longer names holding it (the last build's)
        self.concatenations: set[str] = set()  # 纲目 joint headings the lexicon harvested as one name
        # what the last build decided, for the review and the local build
        self.members: dict[str, str] = {}  # name → the drug it heads
        self.group_term: dict[str, str | None] = {}
        self.term_group: dict[str, str] = {}
        self.joined: dict[str, str] = {}  # a lexicon headword joined to the drug it files twice → its term id
        self.attached: dict[str, str] = {}  # an NTU head that joined another source's drug → how (_attach)
        self.apart: dict[str, str] = {}  # an NTU head kept apart → why (_attach): its entry gives no drug
        self.core_names: set[str] = set()  # the names the other sources give or head (rule 5c)
        self.grouped: set[str] = set()  # the names the other sources head or group (the NTU table's heads come after)
        self.free: dict[str, list[str]] = {}  # name → the passages that write it free of its blockers
        self.last_context: dict[str, Any] = {}
        self.warnings: list[str] = []  # the inputs' (open_pairs)
        self.notes: dict[str, Any] = {"warnings": []}  # the last build's: warnings and what they point at

    # ---------------------------------------------------------------- the store
    def _fetch(self, ids: Iterable[str]) -> None:
        missing = [i for i in dict.fromkeys(ids) if i not in self._rows]
        for k in range(0, len(missing), 500):
            chunk = missing[k:k + 500]
            rows = self.db.db.execute(f"SELECT id, book_id, text, y_start, y_end, year, locator FROM passages WHERE id "
                                      f"IN ({','.join('?' * len(chunk))})", chunk).fetchall()
            for pid, book, text, y0, y1, year, locator in rows:
                y0 = y0 if y0 is not None else year
                y1 = y1 if y1 is not None else year
                head = entry_head(json.loads(locator).get("section"), self.norm) if book in self.bencao else None
                self._rows[pid] = (book, None if y0 is None else int(y0 // 1), None if y1 is None else int(-(-y1 // 1)),
                                   head)
                self._text[pid] = self.norm(text)

    def text(self, pid: str) -> str:
        self._fetch([pid])
        return self._text.get(pid, "")

    def gate(self, pid: str) -> str:
        g = self._gate.get(pid)
        if g is None:
            g = self._gate[pid] = gate_form(self.text(pid))
        return g

    def yr(self, pid: str) -> tuple[int | None, int | None]:
        self._fetch([pid])
        row = self._rows.get(pid)
        return (row[1], row[2]) if row else (None, None)

    def book(self, pid: str) -> str:
        self._fetch([pid])
        return self._rows.get(pid, ("",))[0]

    def _open(self, ids: list[str]) -> list[str]:
        """The passages a witness or a count may read: not the 别名录 (left out of the corpus), not NEVER_PACKED."""
        self._fetch(ids)
        return [i for i in ids if i in self._rows and self._rows[i][0] not in self.never]

    def passages(self, s: str) -> list[str]:
        """Passages that may write ``s`` (an index match, unverified), in (year, id) order."""
        ids = self._ids.get(s)
        if ids is None:
            ids = self._ids[s] = self._open(self.corpus.contains(s, verify=False))
        return ids

    def _read_pack(self) -> tuple[str | None, bool]:
        """The committed pack (``corpus/web/passages.jsonl.gz``) read once: its fingerprint (None without one) and, on
        the web store, whether the store holds exactly its passages — each row as ``webcorpus.build_store`` writes the
        line (:func:`_is_stored`), in the pack's order, none more; on a full store each line is parsed for the ``web``
        flags instead."""
        if self._pack is None:
            pack = self.home / WEB_PACK
            self._web, fp, same = set(), None, False
            if pack.exists():
                digest = hashlib.sha256()
                web = self.edition == "web"
                with self.db.lock if web else nullcontext(), gzip.open(pack, "rb") as fh:
                    held = iter(self.db.db.execute(f"SELECT {', '.join(_PASSAGE_COLUMNS)} FROM passages ORDER BY rid")
                                if web else ())
                    same = web
                    for line in fh:
                        digest.update(line)
                        if not line.strip():
                            continue
                        if not web:
                            self._web.add(json.loads(line)["id"])
                        elif same:  # once the store differs, the rest is only fingerprinted
                            same = _is_stored(line, next(held, None))
                    same = same and next(held, None) is None
                fp = digest.hexdigest()[:12]
            self._pack = (fp, same)
        return self._pack

    def web(self, pid: str) -> bool:
        """Whether the passage is in the committed web pack (``corpus/web/passages.jsonl.gz``): on the web store every
        passage is."""
        if self.edition == "web":
            return True
        if self._web is None:
            self._read_pack()
        return pid in self._web

    def web_pack(self) -> str | None:
        """The fingerprint of the pack the layer is built against (:func:`pack_fingerprint`), for the header: on a full
        store the pack that sets the ``web`` flags; on the web store the pack it is made of — only when the store holds
        exactly the pack's passages, text, locators and dates as the pack has them, in its order (else None, and a
        warning).  None without a pack."""
        if not self._web_pack_read:
            fp, same = self._read_pack()
            if fp is not None and self.edition == "web" and not same:
                fp = None
            self._web_pack, self._web_pack_read = fp, True
        if self._web_pack is None and self.edition == "web" and (self.home / WEB_PACK).exists():
            note = f"the store is not the pack {WEB_PACK.as_posix()} holds: the header names no web pack"
            if note not in self.notes["warnings"]:
                self.notes["warnings"].append(note)
        return self._web_pack

    def witness(self, pid: str, kind: str) -> Witness | None:
        self._fetch([pid])
        row = self._rows.get(pid)
        if row is None:
            return None
        return Witness(pid, row[1], row[2], kind, self.web(pid))

    # ---------------------------------------------------------------- the inputs
    def bielu(self) -> list[Any]:
        if self._bielu is None:
            heads = [{"passage": r["passage"], "head": r["head"]} for r in self.curated.get("head_repairs") or []]
            self._bielu = read_bielu_store(self.db, normalize=self.norm, attested=lambda s: bool(self.passages(s)),
                                           repairs=self.curated.get("repairs") or (), head_repairs=heads)
        return self._bielu

    def open_pairs(self) -> tuple[list[Pair], dict[str, Any]]:
        """The pairs every build reads: the 别名录 in the store, curated pairs, 释名 brackets, taboo herb pairs."""
        pairs: list[Pair] = []
        entries = self.bielu()
        lost = one = 0
        for e in entries:
            if not e.head:
                lost += 1
                continue
            one += len(e.head) < 2
            lw = self.witness(e.ref, "l")
            for t in e.aliases:
                pairs.append(Pair(t.name, e.head, "bielu-jc", kind=t.kind if t.kind in KINDS else "alias",
                                  doubt=bool(DOUBT_FLAGS & set(t.flags)), raw=t.raw, wit=[lw] if lw else []))
        repaired = {r["passage"] for r in self.curated.get("head_repairs") or []}
        refs = {e.ref for e in entries}
        coverage = {"bielu_entries": BIELU_ENTRIES, "bielu_parsed": len(entries), "bielu_lost_heads": lost,
                    "bielu_one_character_heads": one, "head_repairs": len(repaired & refs),
                    "head_repairs_absent": len(repaired - refs)}
        if repaired - refs:
            self.warnings.append(f"head_repairs name passages this store lacks: {', '.join(sorted(repaired - refs))}")
        for row in self.curated.get("pairs") or []:  # the witnesses' kinds are read once the drugs are known (_keep)
            wit = [w for w in (self.witness(p, "e") for p in row.get("wit") or []) if w]
            pairs.append(Pair(self.norm(row["s"]), self.norm(row["head"]), "curated", kind=row.get("kind") or "alias",
                              raw=row["s"], wit=wit, status=row.get("status"), valid=_window(row.get("valid")),
                              cues=[self.norm(c) for c in row.get("cues") or []],
                              anti=[self.norm(c) for c in row.get("anti") or []], note=row.get("note") or ""))
        shiming = self.shiming_pairs()
        coverage["shiming_pairs"] = len(shiming)
        pairs += shiming
        names = {p.s for p in pairs} | {p.h for p in pairs} | set(self.herb_terms)
        taboo = self.taboo_pairs(names)
        coverage["taboo_pairs"] = len(taboo)
        ntu, ntu_coverage = self.ntu_pairs()
        return pairs + taboo + ntu, {**coverage, **ntu_coverage}

    # ---------------------------------------------------------------- the NTU table
    def written(self, s: str) -> bool:
        """Whether the store writes ``s`` in a passage the build reads (not the 别名录, not NEVER_PACKED)."""
        return any(s in self.text(pid) for pid in self.passages(s))

    def credit(self, books: Iterable[str]) -> tuple[str, int, int] | None:
        """The earliest classical work of sources.yaml's ``works`` among the books a remark cites, with its years."""
        found = [(self.works[w][0], self.works[w][1], w) for w in map(self.norm, books) if w in self.works]
        if not found:
            return None
        y0, y1, w = min(found)
        return w, y0, y1

    def ntu_pairs(self) -> tuple[list[Pair], dict[str, Any]]:
        """The NTU table's pairs when sources.yaml ships it, read from its committed extract (``NTU_EXTRACT``): the
        PrimaryDrugName as head, each AlternateName as a name of it, both through the pack's normaliser
        (``ingest.aliases.read_ntu``: a head or a name with a lost character gives none, a damaged name is in doubt
        — a candidate).  A name
        in an ethnic language is a folk name, the language in its note; the places a remark names go into the note too;
        the earliest classical work it cites (``works``) is the pair's credit.  A pair enters only when its head (or a
        curated same-drug member of it) or its name is a herb of the full-corpus lexicon or written in the store: the
        others are counted as left out.  A missing extract, or one other than the pin's, is a warning."""
        source = self.sources.get(NTU) or {}
        if source.get("ship") is not True:
            return [], {}
        path = self.home / NTU_EXTRACT
        if not path.is_file():
            self.warnings.append(f"{NTU} ships but {NTU_EXTRACT} is missing: none of its pairs is read")
            return [], {f"{NTU}_rows": 0}
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        self.extract = sha[:12]
        entries = read_ntu(path, normalize=self.norm)
        pin = (source.get("pin") or {}).get("extract") or {}
        for key, value in (("file", NTU_EXTRACT), ("sha256", sha), ("rows", len(entries))):
            if pin.get(key) is not None and pin[key] != value:
                self.warnings.append(f"{NTU_EXTRACT}: {key} {value} differs from the pinned {pin[key]}")
        same: dict[str, set[str]] = defaultdict(set)  # a name → the curated same-drug members of its drug
        for row in self.curated.get("same_drug") or []:
            names = {self.norm(x) for x in row["names"]}
            for x in names:
                same[x] |= names
        merged: dict[tuple[str, str], Pair] = {}
        books = {"classical": 0, "modern": 0, "unlisted": 0}  # rows citing a book, by what the works table says
        lost = lost_names = 0
        for e in entries:
            remark = e.info.get("remark") or {}
            cited = [self.norm(b) for b in remark.get("books") or ()]
            if cited:
                kind = ("classical" if any(b in self.works for b in cited)
                        else "modern" if all(b in self.modern for b in cited) else "unlisted")
                books[kind] += 1
            if not e.head:
                lost += 1
                continue
            cr = self.credit(cited)
            regions = list(remark.get("regions") or ())
            for t in e.aliases:
                if "〓" in t.name:  # a character lost: never asked, and the store's own 〓 would match it
                    lost_names += 1
                    continue
                note = "、".join(dict.fromkeys(([t.note] if t.kind == "folk" and t.note else []) + regions))
                p = Pair(t.name, e.head, NTU, kind=t.kind if t.kind in KINDS else "alias",
                         doubt=bool(DOUBT_FLAGS & set(t.flags)) or "head_marks" in e.flags, raw=t.raw, note=note, cr=cr)
                q = merged.get((p.s, p.h))
                if q is None:
                    merged[(p.s, p.h)] = p
                    continue
                # the same pair from another dictionary: the most specific kind, the earliest credit, every note
                q.kind = min(q.kind, p.kind, key=_kind_rank)
                q.doubt = q.doubt and p.doubt
                q.cr = min((c for c in (q.cr, p.cr) if c), key=_credit_order, default=None)
                q.note = "、".join(dict.fromkeys(x for n in (q.note, p.note) if n for x in n.split("、")))
        relevant: dict[str, bool] = {}

        def known(x: str) -> bool:
            if x not in relevant:
                relevant[x] = x in self.herb_terms or self.written(x)
            return relevant[x]

        kept = [p for _, p in sorted(merged.items())
                if known(p.s) or any(known(m) for m in sorted(same.get(p.h, set()) | {p.h}))]
        # left out: neither name is a lexicon herb or written in the store (nor a curated same-drug member of the head)
        self.notes_ntu = {"books": books, "left_out": len(merged) - len(kept)}
        return kept, {f"{NTU}_rows": len(entries), f"{NTU}_lost_heads": lost, f"{NTU}_lost_names": lost_names,
                      f"{NTU}_pairs": len(merged),
                      f"{NTU}_left_out": len(merged) - len(kept), f"{NTU}_kept": len(kept),
                      f"{NTU}_credited": sum(p.cr is not None for p in kept),
                      f"{NTU}_folk": sum(p.kind == "folk" for p in kept), f"{NTU}_doubt": sum(p.doubt for p in kept)}

    def _kind_of(self, pid: str, s: str, heads: list[str], g: str) -> str | None:
        """The kind of witness a curated passage is for ``s`` and the drug ``g`` (any of its ``heads``): equation (in
        either order: 鬼箭羽……一名卫矛), gloss or entry when it reads as one; None when it only shows the name in use."""
        for kind in ("e", "g", "n"):
            if any(pid in self._witnesses_in([pid], a, h, kinds=kind, group=g) for x in heads if x != s
                   for a, h in ((s, x), (x, s))[:2 if kind == "e" else 1]):
                return kind
        return None

    def taboo_pairs(self, names: set[str]) -> list[Pair]:
        """taboo.yaml's pairs whose two sides are drug names: the substitute an alias of the original (taboo_rename)."""
        out = []
        for rule in self.taboo.get("rules") or []:
            for orig, sub in rule.get("pairs") or []:
                o, u = self.norm(orig), self.norm(sub)
                if o in names and u in names and o != u:
                    out.append(Pair(u, o, "taboo", kind="taboo_rename", raw=sub, note=f"taboo:{rule['id']}"))
        return out

    def floors(self, names: set[str]) -> dict[str, tuple[int, str]]:
        """Soft floors: the earliest taboo year over herb pairs (the substitute side), else a curated first use."""
        out: dict[str, tuple[int, str]] = {}
        for rule in self.taboo.get("rules") or []:
            for orig, sub in rule.get("pairs") or []:
                o, u = self.norm(orig), self.norm(sub)
                if o in names and u in names and rule.get("from") is not None:
                    if u not in out or rule["from"] < out[u][0]:
                        out[u] = (int(rule["from"]), f"taboo:{rule['id']}")
        for row in self.curated.get("first_use") or []:
            s = self.norm(row["s"])
            if s not in out and row.get("year") is not None:
                out[s] = (int(row["year"]), "curated")
        return out

    def shiming_pairs(self) -> list[Pair]:
        """``a（work）`` in the 释名 blocks of the 本草纲目 under the drug the entry heads (source shiming; the work
        credited from sources.yaml's ``works``)."""
        books = sorted(b for b in self.corpus.books if b.startswith("bencao_gangmu"))
        if not books or not self.works:
            return []
        labels = "|".join(sorted(map(re.escape, self.works), key=lambda w: (-len(w), w)))
        heading = re.compile(f"(?:^|[　\\s）|])([{_HAN}]{{1,6}})（(?:{labels})(?:上品|中品|下品|草)?[^（）]{{0,4}}）")
        token = re.compile(f"[　\\s、，]*([{_HAN}]{{1,8}})(（[^（）]*）)?")
        between = re.compile(r"^[　\s]*(?:校正（[^）]*）[　\s]*)?$")
        out = []
        for p in self.corpus.iter_passages(book_ids=books):
            text = self.norm(p.text)
            heads = [(m.end(), m.group(1)) for m in heading.finditer(text)]
            for m in re.finditer("释名", text):
                head = next((h for end, h in reversed(heads) if end <= m.start()
                             and between.match(text[end:m.start()])), None)
                if head is None:
                    continue
                pos = m.end()
                while (t := token.match(text, pos)) is not None:
                    name, bracket = t.group(1), (t.group(2) or "")[1:-1]
                    if name.startswith(_RUBRIC):
                        break
                    work = next((w for w in self.works if bracket == w or (bracket.startswith(w) and bracket[len(w):]
                                                                            in ("上品", "中品", "下品"))), None)
                    if work and len(name) >= 2 and name != head:
                        y0, y1 = self.works[work]
                        wit = self.witness(p.id, "m")
                        out.append(Pair(name, head, "shiming", wit=[wit] if wit else [], cr=(work, y0, y1)))
                    pos = t.end()
                    if "曰" in bracket:
                        break
        return out

    # ---------------------------------------------------------------- witnesses
    def _witnesses_in(self, pids: Iterable[str], a: str, h: str, kinds: str = "egn",
                      group: str | None = None) -> dict[str, str]:
        """pid → the kind of witness each passage is for (a, h): equation, gloss or 本草 entry.  Either name read
        inside a longer name of a drug other than ``group`` does not count (栝楼|根，一名地楼 · 枳|壳 · 大|蒜)."""
        ea, eh = re.escape(a), re.escape(h)
        eq = re.compile(f"(?P<h>{eh})[^。；]{{0,30}}?{EQUATE}[，,]?(?P<a>{ea})|(?P<a2>{ea})[，,]?{EQUATE}[，,]?(?P<h2>{eh})")
        gloss = re.compile(f"(?P<h>{eh})[（(](?P<a>{ea})[）)]|(?P<a2>{ea})[（(](?P<h2>{eh})[）)]")
        out = {}
        for pid in pids:
            text = self.text(pid)
            if "e" in kinds and self._found(eq, text, group):
                out[pid] = "e"
            elif "g" in kinds and self._found(gloss, text, group):
                out[pid] = "g"
            elif "n" in kinds and self._entry(pid, a, h, group):
                out[pid] = "n"
        return out

    def _found(self, pattern: re.Pattern[str], text: str, group: str | None) -> bool:
        """Whether ``pattern`` matches with each name it captures standing as a name of its own."""
        pos = 0
        while (m := pattern.search(text, pos)) is not None:
            if group is None or all(self._whole(text, m.start(k), m.end(k), group) for k in pattern.groupindex
                                    if m.start(k) >= 0):
                return True
            pos = m.start() + 1
        return False

    def _whole(self, text: str, i: int, j: int, group: str) -> bool:
        """Whether ``text[i:j]`` is not read inside a longer name (an herb or alias name) of a drug other than
        ``group`` that runs across it."""
        x = text[i:j]
        for u in self._longer.get(x, ()):
            if group in self.drugs_of(u):
                continue
            o = u.find(x)
            while o >= 0:
                if i - o >= 0 and text.startswith(u, i - o):
                    return False
                o = u.find(x, o + 1)
        return True

    def _entry(self, pid: str, a: str, h: str, group: str | None = None) -> bool:
        """A 本草 passage headed by ``h`` (its section, or the name it opens with), 一名a in its first 400 characters
        (a name of its own there)."""
        if self.book(pid) not in self.bencao:
            return False
        text = self.text(pid)[:400]
        i = text.find(f"一名{a}")
        while i >= 0 and group is not None and not self._whole(text, i + 2, i + 2 + len(a), group):
            i = text.find(f"一名{a}", i + 1)
        if i < 0:
            return False
        lead = _LEAD.match(self.gate(pid))
        return (lead is not None and lead.group(1) == h) or self._rows[pid][3] == h

    def store_witnesses(self, a: str, heads: Iterable[str], group: str | None = None) -> list[Witness]:
        """Equations, glosses and 本草 entries that tie ``a`` to one of ``heads`` (of the drug ``group``), earliest
        first."""
        found: dict[str, str] = {}
        entry = [i for i in self._open(self.corpus.contains(f"一名{a}", verify=False)) if self.book(i) in self.bencao]
        for h in heads:
            if h == a:
                continue
            ids = self._open(self.corpus.contains_all([a, h]))
            for pid, kind in self._witnesses_in(ids, a, h, "eg", group).items():
                found.setdefault(pid, kind)
            for pid in entry:
                if pid not in found and self._entry(pid, a, h, group):
                    found[pid] = "n"
        wits = [w for w in (self.witness(pid, kind) for pid, kind in found.items()) if w]
        return sorted(wits, key=_by_date)

    # ---------------------------------------------------------------- the records
    def build(self, pairs: list[Pair], *, local: bool = False,
              context: dict[str, Any] | None = None) -> tuple[list[AliasRecord], dict[str, list[str]]]:
        """The records for ``pairs``: grouped, witnessed, blocked, counted and classified; and the referents of the
        names rule 7 stopped (for the review sheet).  ``context``: the ``context.json`` the gates count with, when
        not this build's own (the local build counts with the shipped one, which its profile loads)."""
        cur = self.curated
        self.notes = {"warnings": []}
        stops = {self.norm(r["s"]) for r in cur.get("stop") or []}
        # rows whose names normalise alike (鸡头, 雞頭) are one row: their strings merged, none lost
        covers: dict[str, set[str]] = {}
        unblock: dict[str, set[str]] = {}
        for section, merged in (("cover_stops", covers), ("unblock", unblock)):
            for k, v in (cur.get(section) or {}).items():
                merged.setdefault(self.norm(k), set()).update(self.norm(x) for x in v)
        cover = {s: sorted(v) for s, v in covers.items()}
        for s in sorted(unblock):  # a cover string in another spelling (validate_curated reads the rows as written)
            both = sorted(unblock[s] & set(cover.get(s, ())))
            self.notes["warnings"] += [f"unblock {s}: {x} is a cover string of it too; kept as one" for x in both]
            unblock[s] -= set(both)
        decisions: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in cur.get("decisions") or []:
            decisions[self.norm(row["s"])].append(row)
        rows = [([self.norm(x) for x in row["names"]], row) for row in cur.get("same_drug") or []]
        pairs = [p for p in pairs if len(p.s) >= 2 and p.h and p.s != p.h]
        canon, self.members, self.group_term, self.term_group = self._groups(pairs, [names for names, _ in rows])
        # the NTU table's entries under a head kept apart give no drug (_attach)
        apart = [p for p in pairs if p.src == NTU and p.h in self.apart]
        if apart:
            pairs = [p for p in pairs if not (p.src == NTU and p.h in self.apart)]
            self.notes["ntu_apart"] = {"heads": _tally(self.apart.values()), "pairs": len(apart)}
        self.core_names = {p.s for p in pairs if p.src != NTU} | self.grouped
        pairs += self._member_pairs(pairs, rows, canon)
        members = self.members

        # referents: one per (name, drug)
        merged: dict[tuple[str, str], list[Pair]] = defaultdict(list)
        for p in pairs:
            if p.s != canon[p.h]:
                merged[(p.s, canon[p.h])].append(p)
        refs: dict[str, dict[str, Referent]] = defaultdict(dict)
        info: dict[tuple[str, str], dict[str, Any]] = {}
        for (s, g), ps in sorted(merged.items()):
            lead = next((p for p in ps if p.src == "curated"), None)
            kind = lead.kind if lead is not None else min((p.kind for p in ps), key=_kind_rank)
            cr = min((p.cr for p in ps if p.cr), key=_credit_order, default=None)
            # the note: a curated pair's, else the NTU table's (a folk name's language, the places a remark names)
            nt = lead.note if lead else "、".join(sorted({x for p in ps if p.src == NTU and p.note
                                                          for x in p.note.split("、")}))
            refs[s][g] = Referent(g, t=self.group_term.get(g), k=kind if kind in KINDS else "alias",
                                  src=sorted({p.src for p in ps}), v=lead.valid if lead else None,
                                  a=list(dict.fromkeys(lead.anti)) if lead else [], cr=cr, nt=nt)
            info[(s, g)] = {"pairs": ps, "doubt": all(p.doubt for p in ps) or len(g) < 2,
                            "local": all(p.local for p in ps), "status": lead.status if lead else None,
                            "cues": [c for p in ps if p.src == "curated" for c in p.cues]}
        # rivals: the lexicon's other herb entries filing an alias
        for s in sorted(refs):
            for t in sorted(self.herb_terms.get(s, ())):
                word = self.term_head[t]
                g = self.group_of_term(t)
                if word == s or len(word) < 2 or g in refs[s] or g == members.get(s):
                    continue
                kind = self.lex_kind.get((s, t), "alias")
                refs[s][g] = Referent(g, t=t, k=kind if kind in KINDS else "alias", src=["lexicon"])
                info[(s, g)] = {"pairs": [], "doubt": False, "local": False, "status": None, "cues": []}
                members.setdefault(g, g)
        names = set(refs) | set(members)
        floors = self.floors(set(self.herb_terms) | names)
        # a name with only a floor (党参, 苍术) is a drug of its own: it heads the drug of the lexicon entry it heads,
        # else its own
        for s in sorted(set(floors) - names - stops):
            if len(s) >= 2 and sum(map(is_han, s)) >= 2:
                own = sorted(self.headwords.get(s, ()))
                members[s] = self.group_of_term(own[0]) if len(own) == 1 else s
        names |= set(members)
        heads_of: dict[str, list[str]] = defaultdict(list)
        for m in sorted(members):
            heads_of[members[m]].append(m)
        surfaces = sorted(s for s in names | stops | set(floors) if len(s) >= 2 and sum(map(is_han, s)) >= 2)
        self._drugs = {}
        self._refs = refs

        # blockers, then the passages that write each name free of them
        self.last_context = context if context is not None else self.context(members)
        universe = self._longer = self._universe(surfaces, cover)
        straddlers = {u for u in set(self.herb_terms) | names if 2 <= len(u) <= MAX_NAME}
        self.concatenations = self._concatenations({u for u in set(self.herb_terms) | set(members) if len(u) >= 2},
                                                   set().union(*unblock.values()))
        blockers = {s: self._blockers(s, universe, cover.get(s, []), straddlers if s in refs else set(),
                                      unblock.get(s, set())) for s in surfaces}
        # the runtime's gates over the names' blockers, so that a blocker written there only inside one of its own
        # covers nothing (常山甘草 frees 甘草 of 山甘草), as at runtime
        gates = AliasIndex([AliasRecord(s, b=blockers[s]) for s in surfaces], context=self.last_context)
        free = {s: [pid for pid in self.passages(s)
                    if s in self.gate(pid) and gates.free_offsets(self.gate(pid), s, blockers[s], self.yr(pid))]
                for s in surfaces}
        dropped = self.notes.get("unblocked", {})
        self.notes["warnings"] += [f"unblock {s}: {x} is no blocker of it" for s in sorted(unblock)
                                   for x in sorted(unblock[s] - set(dropped.get(s, ())))]

        self.free = free

        # cues: the head, curated cues, then the drug's names that name nothing else and may be read as it (no
        # candidate, no stop, none written 20 times or more and mostly not as a drug), the most written first
        # rule 5d: a drug only the NTU table gives a name that the other sources give another drug sharing two names
        # or more with it is that drug again under another head (荜澄茄 beside 毕澄茄), or a plant of today that borrows
        # its names: its pair is a candidate, and it is no rival that makes the others' pair a cue
        named: dict[str, set[str]] = defaultdict(set)  # a drug → its heads and the names that have it
        for a, by_g in refs.items():
            for g in by_g:
                named[g].add(a)
        for g, hs in heads_of.items():
            named[g] |= set(hs)
        double = {(s, g) for s, by_g in refs.items() for g in by_g if _ntu_only(info[(s, g)]) and any(
            o != g and info[(s, o)]["pairs"] and not _ntu_only(info[(s, o)]) and len(named[g] & named[o]) >= 2
            for o in by_g)}
        self.notes["ntu_doubles"] = len(double)
        ruled = {(s, g): self._ruled(s, g, info[(s, g)], decisions.get(s, []))
                 or ("candidate" if (s, g) in double else None) for s, by_g in refs.items() for g in by_g}

        def own_names(shaky: set[str]) -> dict[str, list[str]]:
            out = {}
            for g, hs in heads_of.items():
                names_g = set(hs) | {a for a, by_g in refs.items() if g in by_g and len(by_g) == 1
                                     and not info[(a, g)]["doubt"] and a not in stops and ruled[(a, g)] != "candidate"}
                out[g] = sorted((x for x in names_g if len(x) >= 2 and (x == g or (x not in shaky
                                                                                       and x not in self.joined))),
                                key=lambda x: (-len(free.get(x, ())), x))
            return out

        def cue_sets(own: dict[str, list[str]]) -> dict[str, list[str]]:
            for s, by_g in refs.items():
                for g, ref in by_g.items():
                    cues = ([g] if len(g) >= 2 else []) + info[(s, g)]["cues"] + own.get(g, [])
                    ref.c = [c for c in dict.fromkeys(cues) if c != s][:MAX_CUES]
            return {s: sorted(({c for ref in refs.get(s, {}).values() for c in ref.c}
                               | set(own.get(members.get(s, ""), ()))) - {s}) for s in surfaces}

        cues = cue_sets(own_names(set()))
        share = {s: self._share(s, free[s], blockers[s], cues[s], gates) for s in surfaces}
        shaky = {s for s in surfaces if (len(free[s]) >= STOP_N and share[s][0] < CUE_SHARE) or (
            free[s] and share[s][0] < LIST_SHARE and refs.get(s) and all(_ntu_only(info[(s, g)]) for g in refs[s]))}
        again = cue_sets(own_names(shaky))
        for s in surfaces:
            if again[s] != cues[s]:
                share[s] = self._share(s, free[s], blockers[s], again[s], gates)

        # statuses and witnesses
        records, stopped = [], {}
        for s in surfaces:
            n, (sh, early) = len(free[s]), share[s]
            fl = floors.get(s)
            rec = AliasRecord(s, raw=self._raws(s, merged), n=n, sh=sh, b=blockers[s], fl=fl[0] if fl else None,
                              flb=fl[1] if fl else None, ho=members.get(s))
            if s in stops:
                records.append(replace(rec, stop=True))
                continue
            by_g = refs.get(s, {})
            rivals = sum((s, g) not in double for g in by_g)
            statuses = {g: ruled[(s, g)] or self._ntu_share(s, g, n, sh, info[(s, g)], heads_of)
                        or self._status(s, n, sh, rivals >= 2) for g in sorted(by_g)}
            if "stop" in statuses.values():
                stopped[s] = [f"{g}:{by_g[g].k}:{'+'.join(by_g[g].src)}" for g in sorted(by_g)]
                records.append(replace(rec, stop=True))
                continue
            out = []
            for g in sorted(by_g):
                ref, inf = by_g[g], info[(s, g)]
                ref.st = statuses[g]
                if local and inf["local"] and ref.st != "candidate" and not early:
                    ref.st = "candidate"  # a local list's pair no early passage reads as a drug
                ref.w, confirmed = self._keep(s, g, inf["pairs"], heads_of.get(g, [g]))
                if confirmed and inf["pairs"]:
                    ref.src = sorted(set(ref.src) | {"store"})
                out.append(ref)
            records.append(replace(rec, r=out))
        stop_names = {r.s for r in records if r.stop}
        for rec in records:
            for ref in rec.r:
                ref.c = [c for c in ref.c if c not in stop_names]
        self._review(records, pairs, heads_of, free)
        return records, stopped

    def _review(self, records: list[AliasRecord], pairs: list[Pair], heads_of: dict[str, list[str]],
                free: dict[str, list[str]]) -> None:
        """What the report asks editors to look at: 别名录 heads the store never writes and no lexicon entry heads
        (a garbled head: 蘆藜 for 藜芦), drugs named by a name the store never writes, lexicon rivals that share two
        names or more with another of the name's drugs (the lexicon filing one drug twice), cover strings past the
        cap."""
        warn = self.notes["warnings"]
        live = {ref.g for rec in records for ref in rec.r if ref.st != "candidate"}
        listed = {p.h for p in pairs if p.src == "bielu-jc"}
        heads = sorted(h for h in listed if not free.get(h) and h not in self.headwords and len(h) >= 2
                       and self.members.get(h) in live)
        self.notes["unattested_heads"] = heads
        if heads:
            warn.append(f"{len(heads)} 别名录 heads the store never writes and no lexicon entry heads (garbled?): "
                        "see unattested_heads")
        for g, hs in sorted(heads_of.items()):
            if g in hs and not free.get(g) and any(free.get(h) for h in hs):
                warn.append(f"the drug {g} is named by a name the store never writes (its group: {', '.join(hs)})")
        names: dict[str, set[str]] = defaultdict(set)
        for rec in records:
            for ref in rec.r:
                names[ref.g].add(rec.s)
            if rec.ho:
                names[rec.ho].add(rec.s)
        twice = []
        for rec in records:
            for ref in rec.r:
                if ref.src == ["lexicon"] and ref.t:
                    best = max(((len(self.term_names[ref.t] & names[o.g]), o.g) for o in rec.r if o is not ref),
                               default=(0, ""))
                    if best[0] >= 2:
                        twice.append(f"{rec.s}:{ref.h}~{best[1]}")
        self.notes["rivals_sharing_names"] = twice
        if twice:
            warn.append(f"{len(twice)} lexicon rivals share two names or more with another drug of the name (one drug "
                        "filed twice?): see rivals_sharing_names")
        warn += [f"{s}: {k} blockers, {k - MAX_BLOCKERS} past the cap dropped" for s, k in self.notes.get("capped", [])]

    def _groups(self, pairs: list[Pair], same: list[list[str]]) -> tuple[dict[str, str], dict[str, str],
                                                                            dict[str, str | None], dict[str, str]]:
        """Each head's drug: heads in one curated same-drug list, or of one lexicon herb entry, are one drug, named by
        the list's first name, else the entry's headword, else the head; a lexicon entry that files a drug's names
        again under another headword joins it (:meth:`_join`).  The NTU table's heads that no other source heads come
        after, so that they change none of these drugs or names: each joins a drug or heads one of its own
        (:meth:`_attach`).  Returns head → drug, name → the drug it heads (``ho``), drug → its lexicon term id, term id
        → its drug."""
        uf = _Groups()
        core = [p for p in pairs if p.src != NTU]
        heads = sorted({p.h for p in core} | {x for row in same for x in row})
        for h in heads:
            uf.add(h)
        for row in same:
            for x in row[1:]:
                uf.union(row[0], x)
        listed = {x for row in same for x in row}  # a listed name joins by the entry it heads only (重楼 is filed
        term_of = {h: t for h in heads if (t := self._term(h, h in listed))}  # under 黄精 too)
        first_of: dict[str, str] = {}
        for h in heads:
            if h in term_of:
                uf.union(first_of.setdefault(term_of[h], h), h)
        self.joined = self._join(uf, core, set(heads), term_of)
        self.grouped = set(uf.parent)
        self.attached = self._attach(uf, pairs, term_of, first_of)
        canon: dict[str, str] = {}
        group_term: dict[str, str | None] = {}
        for members in uf.components().values():
            terms = sorted({term_of[m] for m in members if m in term_of and m not in self.joined})
            first = next((row[0] for row in same if row[0] in members), None)
            word = self.term_head[terms[0]] if len(terms) == 1 else None
            pool = [m for m in members if m not in self.attached] or members  # a drug keeps the name it had
            g = first or (word if word and len(word) >= 2 else None) or min(
                pool, key=lambda m: (len(m) < 2, m in self.joined, m))
            for m in members:
                canon[m] = g
            group_term[g] = term_of.get(g) or self.joined.get(g) or (terms[0] if terms else None)
        ho = dict(canon)
        for g in canon.values():
            ho[g] = g
        term_of.update(self.joined)
        term_group = {t: canon[h] for h, t in sorted(term_of.items(), reverse=True)}
        return canon, ho, group_term, term_group

    def _attach(self, uf: _Groups, pairs: list[Pair], term_of: dict[str, str],
                first_of: dict[str, str]) -> dict[str, str]:
        """The NTU table's heads that no other source heads or groups (its dictionaries' entries: one drug is often
        entered under two names, 重楼 and 七叶一枝花), each joining a drug, heading one of its own or kept apart.

        A head the editors or the other sources tie to drugs in a way a member of one drug cannot keep is kept apart
        (:meth:`_apart`): the table's entry under it gives no drug, and its pairs are left out (青木香, the editors'
        木香 before 1100 and 马兜铃's root after; 小草, 远志's leaves, a cue; 通草, 木通 before 960 and 通脱木 after) —
        joined, it would be searched as the drug's own name, everywhere and in every period.  Else one that heads a
        lexicon entry of a drug of the others joins that drug; else, of the drugs that name it — another source's (by
        its names there and its lexicon entry's), one its own lexicon entry files the head of (葶苈子's files 葶苈), one
        it names with or without the part the drug is (牛蒡 and 牛蒡子: ``SAME_FORM``) or a lexicon entry filing it — the
        one whose names share two or more with its names in the table, and more than any other's, takes it (七叶一枝花,
        whose names there are 蚤休's, joins 蚤休; 天胡荽, whose names are not 蘩蒌's, stays apart though the lexicon
        files it there); a head the others already give as a name of drugs joins only one of those; else it heads a
        drug of its own.  Returns each head that joined a drug of the other sources → how (``lexicon`` or ``names``);
        ``self.apart`` keeps the heads kept apart → why."""
        self.apart = {}
        own: dict[str, set[str]] = defaultdict(set)  # an NTU-only head → its names in the table
        for p in pairs:
            if p.src == NTU and p.h not in uf.parent:
                own[p.h] |= {p.h, p.s}
        if not own:
            return {}
        names: dict[str, set[str]] = defaultdict(set)  # a drug of the other sources → its names there and its entries'
        given: dict[str, set[str]] = defaultdict(set)  # a name → the drugs the other sources' pairs give it
        kinds: dict[str, set[str]] = defaultdict(set)  # a name → the kinds those pairs give it
        for p in pairs:
            if p.src != NTU:
                g = uf.find(p.h)
                names[g] |= {p.s, p.h}
                given[p.s].add(g)
                kinds[p.s].add(p.kind)
        for h, t in term_of.items():
            names[uf.find(h)] |= self.term_names[t]
        for w, t in self.joined.items():
            names[uf.find(w)] |= self.term_names[t]
        for x in list(uf.parent):
            names[uf.find(x)].add(x)
        drugs: dict[str, set[str]] = defaultdict(set)  # a name → the drugs of the other sources it is a name of
        for g, ns in names.items():
            for x in ns:
                drugs[x].add(g)
        root = {x: uf.find(x) for x in uf.parent}  # the other sources' drugs as they stand (a union may move a root)
        anchor = {**first_of, **{t: w for w, t in self.joined.items()}}  # a term → a name of its drug
        rows: dict[str, list[Mapping[str, Any]]] = defaultdict(list)  # a name → its curated decisions, then pairs
        for key in ("decisions", "pairs"):
            for row in self.curated.get(key) or []:
                rows[self.norm(row["s"])].append(row)
        stops = {self.norm(r["s"]) for r in self.curated.get("stop") or []}
        out: dict[str, str] = {}
        for h in sorted(own):
            lexical = {root[anchor[t]] for t in self.herb_terms.get(h, ()) if anchor.get(t) in root}
            mine = self._decided(rows[h], given[h] | lexical, root)  # the drugs the others give h, candidates aside
            why = "stop" if h in stops else self._apart(rows[h], mine, kinds[h])
            if why:
                self.apart[h] = why
                continue
            uf.add(h)
            heads = sorted(self.headwords.get(h, ()))
            if len(heads) == 1 and anchor.get(heads[0]) in root and (not mine or root[anchor[heads[0]]] in mine):
                out[h] = "lexicon"  # the entry it heads is a drug of the others
                uf.union(anchor[heads[0]], h)
                continue
            options: dict[tuple[str, str], set[str]] = {}  # a drug: ("g", another source's) or ("t", an entry's own)
            for g in sorted(drugs.get(h, set()) | self._akin(h, heads, root)):
                options[("g", g)] = names[g]
            if len(heads) != 1:
                for t in heads or sorted(self.herb_terms.get(h, ())):
                    a = anchor.get(t)
                    if a in root:
                        options[("g", root[a])] = names[root[a]]
                    else:
                        options[("t", t)] = self.term_names[t]
            if mine:  # a name the others give for drugs joins only one of them
                options = {k: v for k, v in options.items() if k[0] == "g" and k[1] in mine}
            else:  # never one the editors made a candidate of it
                options = {k: v for k, v in options.items() if not (k[0] == "g" and k[1] in given[h] | lexical)}
            scores = sorted(((len(own[h] & ns), key) for key, ns in options.items()), key=lambda sk: (-sk[0], sk[1]))
            entry = heads[0] if len(heads) == 1 and anchor.get(heads[0]) not in root else None
            if not scores or scores[0][0] < 2 or (len(scores) > 1 and scores[1][0] == scores[0][0]):
                if entry:  # the lexicon entry it heads, a drug of its own (or of a head filed there)
                    term_of[h] = entry
                    uf.union(anchor.setdefault(entry, h), h)
                continue
            kind, x = scores[0][1]
            if kind == "g":
                uf.union(x, h)
                out[h] = "names"
                if entry and entry not in anchor:  # its entry is that drug's from now on
                    anchor[entry] = h
                    root[h] = x
            else:
                term_of[h] = x
                uf.union(anchor.setdefault(x, h), h)
        return out

    def _decided(self, rows: list[Mapping[str, Any]], drugs: set[str], root: dict[str, str]) -> set[str]:
        """Of the drugs the other sources give a name, those its curated rows do not make candidates (the first row
        for a drug decides, as in :meth:`_ruled`; a row without a head is for every drug)."""
        out = set()
        for g in drugs:
            row = next((r for r in rows if not r.get("head") or root.get(self.norm(r["head"])) == g), None)
            if row is None or row.get("status") != "candidate":
                out.add(g)
        return out

    def _apart(self, rows: list[Mapping[str, Any]], mine: set[str], kinds: set[str]) -> str | None:
        """Why an NTU head is kept apart (:meth:`_attach`), or None: a curated row (not a candidate's) that gives it a
        period window, a part's or an older name's kind, or the status cue (``curated``); a part's or older name's
        kind the other sources give it (``part``); two drugs of the others, candidates aside (``ambiguous``)."""
        if any(r.get("status") != "candidate" and (r.get("valid") or r.get("kind") in APART_KINDS
                                                   or r.get("status") == "cue") for r in rows):
            return "curated"
        if kinds & set(APART_KINDS):
            return "part"
        return "ambiguous" if len(mine) >= 2 else None

    def _akin(self, h: str, heads: list[str], root: dict[str, str]) -> set[str]:
        """The other sources' drugs an NTU head may be by its form: one headed by it with or without the part the drug
        is (``SAME_FORM``: 牛蒡 and 牛蒡子, 地锦草 and 地锦), or whose head the lexicon entry it heads files (葶苈子's
        entry files 葶苈)."""
        forms = {h + c for c in SAME_FORM} | ({h[:-1]} if h[-1] in SAME_FORM and len(h) >= 3 else set())
        if len(heads) == 1:
            forms |= self.term_names[heads[0]] - {h}
        return {root[x] for x in forms if x in root and len(x) >= 2}

    def _join(self, uf: _Groups, pairs: list[Pair], heads: set[str], term_of: dict[str, str]) -> dict[str, str]:
        """Lexicon herb entries that file a drug of the pairs a second time under another headword (亭历 beside
        葶苈, 牙子 beside 狼牙, 代赭 beside 代赭石): an entry sharing two names or more with one drug — its headword
        among them — and fewer with any other joins it, unless a pair heads its headword, files it under another drug,
        or a curated row decides about it.  Returns joined headword → its term id."""
        cur = self.curated
        decided = {self.norm(r[k]) for key in ("pairs", "decisions", "stop") for r in cur.get(key) or []
                   for k in ("s", "head") if r.get(k)}
        names: dict[str, set[str]] = defaultdict(set)
        drugs_of: dict[str, set[str]] = defaultdict(set)  # alias → the drugs its pairs give
        for h in heads:
            names[uf.find(h)].add(h)
        for p in pairs:
            g = uf.find(p.h)
            names[g] |= {p.s, p.h}
            drugs_of[p.s].add(g)
        taken = set(term_of.values())
        out: dict[str, str] = {}
        for t in sorted({t for s in drugs_of for t in self.herb_terms.get(s, ())}):
            w = self.term_head[t]
            if (t in taken or len(w) < 2 or w in heads or w in decided or len(self.headwords.get(w, ())) != 1
                    or len(drugs_of.get(w, ())) > 1):
                continue
            mine = self.term_names[t]
            scores = sorted(((len(mine & names[g]), g) for g in {g for x in mine for g in drugs_of.get(x, ())}),
                            key=lambda sg: (-sg[0], sg[1]))
            if not scores or scores[0][0] < 2 or (len(scores) > 1 and scores[1][0] == scores[0][0]):
                continue
            g = scores[0][1]
            if drugs_of.get(w, {g}) != {g}:
                continue
            uf.union(g, w)
            out[w] = t
        return out

    def _member_pairs(self, pairs: list[Pair], rows: list[tuple[list[str], Mapping[str, Any]]],
                      canon: dict[str, str]) -> list[Pair]:
        """A same-drug member, or a joined lexicon headword (:meth:`_join`), that no pair ties to its drug, as a pair
        of the list (curated, its witnesses the row's that write the member) or of the lexicon: so the drug reaches
        the member's passages (牡丹 → 牡丹皮, 卢会 → 芦荟) and the member the drug's.  Its kind is 异名: a list does
        not say which names are spellings (朱砂 is not one of 丹砂), a curated pair does."""
        tied = {(p.s, canon[p.h]) for p in pairs}
        out = []
        for names, row in rows:
            g = canon[names[0]]
            for m, raw in zip(names, row["names"]):
                if m == g or len(m) < 2 or sum(map(is_han, m)) < 2 or (m, g) in tied:
                    continue
                wit = [w for w in (self.witness(p, "e") for p in row["wit"]) if w and m in self.text(w.pid)]
                if not wit:
                    self.notes["warnings"].append(f"same_drug {g}: no witness of the list writes {m}")
                out.append(Pair(m, g, "curated", raw=raw, wit=wit))
                tied.add((m, g))
        for w in sorted(self.joined):
            if (w, canon[w]) not in tied and w != canon[w]:
                out.append(Pair(w, canon[w], "lexicon", raw=w))
                tied.add((w, canon[w]))
        return out

    def group_of_term(self, t: str) -> str:
        """The drug a lexicon herb entry is: the group of a head filed under it, else its headword's, else itself."""
        word = self.term_head[t]
        return self.term_group.get(t) or self.members.get(word) or word

    def drugs_of(self, u: str) -> set[str]:
        """The drugs a name is: its referents, the group it heads, its lexicon entries."""
        out = self._drugs.get(u)
        if out is None:
            out = set(self._refs.get(u, {})) | {self.group_of_term(t) for t in self.herb_terms.get(u, ())}
            if u in self.members:
                out.add(self.members[u])
            self._drugs[u] = out
        return out

    def _term(self, h: str, headword_only: bool = False) -> str | None:
        """The lexicon herb entry a head is: the one it heads, else (not ``headword_only``) the only one filing it."""
        own = self.headwords.get(h, set())
        if len(own) == 1:
            return next(iter(own))
        filed = self.herb_terms.get(h, set())
        return next(iter(filed)) if not own and not headword_only and len(filed) == 1 else None

    def _ruled(self, s: str, g: str, inf: dict[str, Any], decisions: list[dict[str, Any]]) -> str | None:
        """Rules 1, 4 and 5 of the status table, which the store's counts do not enter: a curated decision or pair, a
        damaged entry or a one-character drug, another drug's headword or head; None when none holds."""
        for row in decisions:  # all of the name's drugs, or the one whose head (or group) it names
            if not row.get("head") or self.members.get(self.norm(row["head"]), self.norm(row["head"])) == g:
                return row["status"]
        if inf["status"]:
            return inf["status"]
        if inf["doubt"]:
            return "candidate"
        if _ntu_only(inf) and self._listish(s):
            return "candidate"  # rule 5c: a formula's name or a class of drugs (镇心丹, 清凉膏, 止血药)
        own = self.members.get(s)
        # another drug's head: for a pair only the NTU table gives, any; for the others, a head the other sources give
        # (the table's entry 余甘子 leaves the 别名录's 余甘子 → 摩勒 alone)
        if (own is not None and own != g and (_ntu_only(inf) or s in self.grouped)) or any(
                self.group_of_term(t) != g for t in self.headwords.get(s, ())):
            return "candidate"  # another drug's headword or head
        return None

    def _listish(self, s: str) -> bool:
        """Whether a name reads as a formula's or a class of drugs' (rule 5c): at most 8 characters ending in one of
        ``LIST_ENDS`` (镇心丹, 清凉膏, 止血药), and neither a herb of the lexicon (铅丹, 石膏, 芍药) nor a name the other
        sources give or head."""
        return len(s) <= 8 and s[-1] in LIST_ENDS and s not in self.herb_terms and s not in self.core_names

    def _ntu_share(self, s: str, g: str, n: int, sh: float, inf: dict[str, Any],
                   heads_of: dict[str, list[str]]) -> str | None:
        """Rule 5b: a pair only the NTU table gives (a modern list) whose name the store writes free of its blockers
        needs the store to read it as a drug in LIST_SHARE of those passages, or a witness there, else it is a
        candidate (五味, mostly 五味子's or the five flavours, is not 石灰's; 熟地 is 地黄's); None
        when the rule does not hold."""
        if n < 1 or sh >= LIST_SHARE or not _ntu_only(inf):
            return None
        names = sorted({p.h for p in inf["pairs"]} | set(heads_of.get(g, [g])) | {g})
        return None if self.store_witnesses(s, names, g) else "candidate"

    def _status(self, s: str, n: int, sh: float, shared: bool) -> str:
        """Rules 6 to 10 of the status table; ``stop`` makes the record a stop — never a drug's own name's (its head's,
        a same-drug member's), which is a candidate instead: it stays a head."""
        if shared:
            return "cue"
        if n >= STOP_N and sh < STOP_SHARE:
            return "candidate" if s in self.members else "stop"
        if n >= STOP_N and sh < CUE_SHARE:
            return "cue"
        return "cue" if len(s) == 2 else "open"

    def _universe(self, surfaces: list[str], cover: dict[str, list[str]]) -> dict[str, list[str]]:
        """A name → the longer herb and alias names holding it."""
        out: dict[str, list[str]] = defaultdict(list)
        for u in sorted(set(self.herb_terms) | set(surfaces) | {x for v in cover.values() for x in v}):
            subs = {u[i:j] for i in range(len(u)) for j in range(i + 2, len(u) + 1)} - {u}
            for sub in subs:
                out[sub].append(u)
        return out

    def _concatenations(self, known: set[str], unblocked: set[str]) -> set[str]:
        """The lexicon's herb headwords harvested from 本草纲目 entry titles that are two ``known`` names written
        together (赤箭天麻, 假苏荆芥: the 纲目 heads one entry with two names and the harvest took the heading for one),
        which the store never writes as one drug's name: with a dose after it (not 各, which shares one dose among
        names), or named (一名…, …之名).  They block nothing.  Not a title an editor ``unblocked`` for a name (a
        curated unblock row reads it as one name, that name's drug: it blocks the other), nor a headword harvested
        from other 本草 entries, which are one drug's (防风党参 is a 党参, 乌臼木根皮 an entry of 证类)."""
        dose, each, nameof, named = (re.compile(CONTEXT_PATTERNS[k]) for k in ("dose", "each", "nameof", "named"))

        def as_one(g: str, w: str) -> bool:
            i = g.find(w)
            while i >= 0:
                after = g[i + len(w):i + len(w) + 12]
                if ((dose.match(after) and not each.match(after)) or nameof.search(g[max(0, i - 4):i])
                        or named.match(after)):
                    return True
                i = g.find(w, i + 1)
            return False

        return {w for w in sorted(self.headwords) if len(w) >= 4 and w in self.gangmu_titles and w not in unblocked
                and any(w[:k] in known and w[k:] in known for k in range(2, len(w) - 1))
                and not any(as_one(self.gate(pid), w) for pid in self.passages(w))}

    def _blockers(self, s: str, universe: dict[str, list[str]], cover: list[str], straddlers: set[str],
                  unblock: set[str]) -> list[Any]:
        """Strings that hold ``s`` and are not it (≤ 24): the curated cover strings, then longer names of another drug
        (with the years they mean another, where they mean this one in some only) and names straddling an occurrence
        of an alias in the store (石蜜|甘), each lot the most written first.  Past the cap, the least written are
        dropped (and reported).  Not the strings curated.yaml unblocks for ``s`` (青矾石 is 青矾, not 青|矾石), nor
        the 纲目's joint headings the lexicon harvested as one name (:meth:`_concatenations`)."""
        mine = self.drugs_of(s)
        cands: dict[tuple[str, int | None, int | None], int] = {}
        for u in sorted(universe.get(s, ())):
            theirs = {(g, ref.v) for g, ref in self._refs.get(u, {}).items()}
            theirs |= {(g, None) for g in self.drugs_of(u) - set(self._refs.get(u, {}))}
            same = [v for g, v in theirs if g in mine]
            if any(v is None for v in same):
                continue
            if u in unblock:
                self._note("unblocked", s, u)
                continue
            if u in self.concatenations:
                self._note("concatenations", u, s)
                continue
            for lo, hi in (_complement(same) if same else [(None, None)]):
                cands[(u, lo, hi)] = 0
        for u in cover:
            cands[(u, None, None)] = 0
        n = len(s)
        for pid in self.passages(s):
            g = self.gate(pid)
            if s not in g:
                continue
            for key in cands:
                if key[0] in g:
                    cands[key] += 1
            if not straddlers:
                continue
            seen = set()
            i = g.find(s)
            while i >= 0:
                # a name ending inside s (石蜜 of 石蜜甘), unless a name ends in its part before s (麻黄|连轺 is not
                # 麻|黄连|轺); a name starting inside s, unless a name starts in its part after s (天麻|黄芪); either
                # unless s stands whole beside it (熟地|黄芪, 常山|甘草: the straddle cuts the other name)
                for j in range(max(0, i - MAX_NAME + 1), i):
                    for k in range(i + 1, min(i + n, j + MAX_NAME + 1)):
                        if (g[j:k] in straddlers and not self.drugs_of(g[j:k]) & mine
                                and not _read_across(g, straddlers, j, i, left=True)
                                and not self._stands(g, s, i, j, k, straddlers)):
                            seen.add(g[j:i + n])
                for j in range(i + 1, i + n):
                    for k in range(i + n + 1, min(len(g), j + MAX_NAME) + 1):
                        if (g[j:k] in straddlers and not self.drugs_of(g[j:k]) & mine
                                and not _read_across(g, straddlers, i + n, k, left=False)
                                and not self._stands(g, s, i, j, k, straddlers)):
                            seen.add(g[i:k])
                i = g.find(s, i + 1)
            for x in sorted(seen):
                if x in unblock:
                    self._note("unblocked", s, x)
                    continue
                key = (x, None, None)
                cands[key] = cands.get(key, 0) + 1
        given = set(cover)
        ranked = sorted(cands.items(), key=lambda kv: (kv[0][0] not in given, -kv[1], kv[0][0], _n(kv[0][1]),
                                                       _n(kv[0][2])))
        if len(ranked) > MAX_BLOCKERS:
            self.notes.setdefault("capped", []).append((s, len(ranked)))
        return [text if lo is None and hi is None else (text, lo, hi) for (text, lo, hi), _ in ranked[:MAX_BLOCKERS]]

    def _stands(self, g: str, s: str, i: int, j: int, k: int, names: set[str]) -> bool:
        """Whether ``s`` (at ``i``) stands whole where the name ``g[j:k]`` straddles it, so that the straddle cuts that
        name: the name's part outside ``s`` is a name of its own (常山|甘草 cuts 山甘草; 熟地|黄芪 cuts 熟地黄), no name
        across the edge of ``s`` takes its part outside the straddler (生地|麦门冬 cuts 地麦; 地肤子|柏子仁 cuts 子柏),
        and the straddler is not written twice as often as ``s`` (又方|石硫黄 cuts 方石; 大腹皮|消 cuts 皮消)."""
        n = len(s)
        if j < i:  # the straddler ends inside s: its part before s, then s's part after it
            if g[j:i] not in names or any(g[k:y] in names for y in range(i + n, min(len(g), k + MAX_NAME) + 1)):
                return False
        elif g[i + n:k] not in names or any(g[x:j] in names for x in range(max(0, j - MAX_NAME), i + 1)):
            return False
        return len(self.passages(g[j:k])) < STRADDLE_RATIO * len(self.passages(s))

    def _note(self, key: str, name: str, value: str) -> None:
        """Keep ``value`` under ``name`` in the report's ``key`` (once)."""
        values = self.notes.setdefault(key, {}).setdefault(name, [])
        if value not in values:
            values.append(value)

    def _share(self, s: str, free: list[str], blockers: list[Any], cues: list[str],
               gates: AliasIndex) -> tuple[float, bool]:
        """The share of the passages writing ``s`` free that read it as a drug (2 decimals), and whether one of them is
        earlier than 1912."""
        hits, early = 0, False
        for pid in free:
            g, yr = self.gate(pid), self.yr(pid)
            if gates.drug_context(g, s, gates.free_offsets(g, s, blockers, yr), cues):
                hits += 1
                early = early or (yr[1] is not None and yr[1] < LOCAL_BEFORE)
        return (round(hits / len(free), 2) if free else 0.0), early

    def _raws(self, s: str, merged: dict[tuple[str, str], list[Pair]]) -> list[str] | None:
        """The spellings the lists write ``s`` in (≤ 4), when they differ from it."""
        raws = sorted({p.raw for (a, _), ps in merged.items() if a == s for p in ps
                       if p.raw and len(p.raw) == len(s) and p.raw != s})
        return [s, *raws][:MAX_RAW] if raws else None

    def _keep(self, s: str, g: str, ps: list[Pair], heads: list[str]) -> tuple[list[Witness], bool]:
        """The witnesses kept for (s, g), ≤ 3: curated ones, then the earliest equation, gloss, entry or 释名 by its
        last year, then the list's own entry, then the next earliest; and whether the store confirms the pair."""
        listed = sorted({w.pid: w for p in ps for w in p.wit if w.kind == "l"}.values(), key=_by_date)
        names = sorted({p.h for p in ps} | set(heads) | {g})
        # the editors' witnesses, those that equate the names first; one that only shows the name in use is labelled
        # a usage witness (an equation while the format has no kind for it) and counted in the report
        read = [(w, self._kind_of(w.pid, s, names, g)) for w in {w.pid: w for p in ps if p.src == "curated"
                                                                  for w in p.wit}.values()]
        usage = usage_kind()
        given = [replace(w, kind=kind) for w, kind in read if kind] + [replace(w, kind=usage) for w, kind in read
                                                                       if not kind]
        self.notes["usage_witnesses"] = self.notes.get("usage_witnesses", 0) + sum(not kind for _, kind in read)
        shiming = [w for p in ps if p.src == "shiming" for w in p.wit]
        found = self.store_witnesses(s, names, g)
        rest = sorted({w.pid: w for w in shiming + found if w.pid not in {x.pid for x in given}}.values(), key=_by_date)
        out = given[:MAX_WITNESSES] + rest[:1] + listed[:1] + rest[1:]
        return out[:MAX_WITNESSES], bool(found)

    # ---------------------------------------------------------------- context.json
    def context(self, heads: Iterable[str]) -> dict[str, Any]:
        """``context.json``: the herb set the list gate counts (the full-corpus lexicon's herb names and the layer's
        heads, two to four characters) and the drug-context patterns."""
        herbs = {s for s in self.herb_terms if 2 <= len(s) <= 4} | {h for h in heads if 2 <= len(h) <= 4}
        return {"version": 1, "herbs": sorted(herbs), **CONTEXT_PATTERNS}

    def meta(self, coverage: dict[str, Any], records: list[AliasRecord]) -> dict[str, Any]:
        used = sorted({src for rec in records for ref in rec.r for src in ref.src})
        web_pack = self.web_pack()
        return {"store": store_label(self.db), "normalizer": self.pack.variants.fingerprint,
                "lexicon": lexicon_fingerprint(self.root), "coverage": coverage,
                "labels": {i: self.sources.get(i, {}).get("label", i) for i in used},
                **({"web_pack": web_pack} if web_pack else {}), **({NTU: self.extract} if self.extract else {})}


def _read_across(g: str, names: set[str], a: int, b: int, *, left: bool) -> bool:
    """Whether a known name crosses the edge of ``g[a:b]``, the part of a straddling name outside the alias: ending
    inside it from the left (``left``: 麻黄 across 黄 of 黄连轺) or starting inside it and running on to the right."""
    if left:
        return any(g[x:y] in names for x in range(max(0, a - MAX_NAME + 1), a) for y in range(a + 1, b + 1))
    return any(g[x:y] in names for x in range(a, b) for y in range(b + 1, min(len(g), x + MAX_NAME) + 1))


def usage_kind() -> str:
    """The kind of a curated witness that only shows the name in use: ``u`` once the format has it, else ``e``."""
    return "u" if "u" in WITNESS_KINDS else "e"


def _kind_rank(kind: str) -> int:
    return KIND_ORDER.index(kind) if kind in KIND_ORDER else len(KIND_ORDER)


def _ntu_only(inf: Mapping[str, Any]) -> bool:
    """Whether only the NTU table gives a referent's pairs (a lexicon rival has none)."""
    return bool(inf["pairs"]) and all(p.src == NTU for p in inf["pairs"])


def _credit_order(cr: tuple[str, int | None, int | None]) -> tuple[int, int, str]:
    """Credits earliest first (by their first year, then their last; a year missing counts as 0), then by title."""
    return (cr[1] if cr[1] is not None else 0, cr[2] if cr[2] is not None else 0, cr[0])


def _by_date(w: Witness) -> tuple:
    return (w.y1 is None, w.y1 if w.y1 is not None else 0, w.y0 if w.y0 is not None else 0, w.pid)


# --------------------------------------------------------------------------- builds
def build_open(store: CorpusStore | str | Path, home: str | Path) -> BuildResult:
    """The layer that ships: the pairs of the shipped sources (the 别名录 in the store, curated, 释名, taboo, and the NTU
    table's extract under the home while sources.yaml ships it) classified on ``store``.  It takes no local input."""
    t0 = time.time()
    b = Builder(store, home)
    pairs, coverage = b.open_pairs()
    records, stopped = b.build(pairs)
    return _result(b, records, stopped, coverage, pairs, t0)


def build_local(open_result: BuildResult, local_pairs: Iterable[Mapping[str, Any]],
                store: CorpusStore | str | Path | None = None) -> BuildResult:
    """The shipped pairs and the rows of the local lists (``<data>/aliases/local/*.jsonl``), classified again on the
    store — for ``<data>/aliases/local/aliases-local.jsonl`` only, never for the domain.  It counts with the shipped
    layer's ``context.json`` (its herb set takes in no local head), the one the profile reading the local layer
    loads.  The rows of a list sources.yaml ships (an earlier local import of the NTU table) are left out: the shipped
    pairs read it from its extract."""
    t0 = time.time()
    b = open_result.builder
    if b is None:
        raise ValueError("build_local reads the result of build_open")
    if store is not None and Path(store.path if isinstance(store, CorpusStore) else store) != b.db.path:
        b = Builder(store, b.home)
    pairs, coverage = b.open_pairs()
    rows = list(local_pairs)
    # a list that now ships (the NTU table) is read from its extract by open_pairs: its local rows are left out
    shipped = {i for i, s in b.sources.items() if s.get("ship") is True}
    local = [local_pair(row) for row in rows if row.get("src") not in shipped]
    coverage = {**coverage, "local_pairs": len(local), **({"local_shipped": len(rows) - len(local)}
                                                          if len(local) < len(rows) else {})}
    records, stopped = b.build(pairs + local, local=True, context=open_result.context)
    return _result(b, records, stopped, coverage, pairs + local, t0)


def local_pair(row: Mapping[str, Any]) -> Pair:
    """A row of ``<data>/aliases/local/<source>.jsonl`` (``ingest.aliases.local_rows``) as a pair."""
    kind = row.get("k") or "alias"
    return Pair(row["s"], row["h"], row["src"], kind=kind if kind in KINDS else "alias",
                doubt=bool(DOUBT_FLAGS & set(row.get("fl") or ())), raw=row.get("raw") or "", note=row.get("nt") or "",
                local=True)


def read_local(local_dir: Path | str) -> list[dict[str, Any]]:
    """The rows the local imports wrote (``bielu-gb``, ``hurb``, ``ntu``), in that order."""
    rows: list[dict[str, Any]] = []
    for name in sorted(LOCAL_SOURCES):
        path = Path(local_dir) / f"{name}.jsonl"
        if path.exists():
            rows += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows


def _result(b: Builder, records: list[AliasRecord], stopped: dict[str, list[str]], coverage: dict[str, Any],
            pairs: list[Pair], t0: float) -> BuildResult:
    meta = b.meta(coverage, records)
    result = BuildResult(records, b.last_context, meta, {}, stopped, b)
    refs = [ref for rec in records for ref in rec.r]
    text = result.text().encode("utf-8")
    ctx = result.context_text().encode("utf-8")
    result.report = {
        "store": meta["store"], "coverage": coverage, "surfaces": len(records),
        "heads": sum(rec.ho is not None for rec in records), "pairs": _tally(p.src for p in pairs),
        "counts": {"status": {**_tally(ref.st for ref in refs), "stop": sum(rec.stop for rec in records),
                              "stop_by_rule_7": len(stopped)},
                   "kind": _tally(ref.k for ref in refs), "source": _tally(s for ref in refs for s in ref.src),
                   "witness": _tally(w.kind for ref in refs for w in ref.w),
                   "floors": _tally((rec.flb or "").split(":")[0] for rec in records if rec.fl is not None),
                   "windows": sum(ref.v is not None for ref in refs), "blocked": sum(bool(rec.b) for rec in records),
                   "attested": sum(rec.n > 0 for rec in records if rec.r),
                   "usage_witnesses": b.notes.get("usage_witnesses", 0)},
        "joined": {w: b.members.get(w) for w in sorted(b.joined)},
        "unblocked": dict(sorted(b.notes.get("unblocked", {}).items())),
        "concatenations": dict(sorted(b.notes.get("concatenations", {}).items())),
        "bytes": {"aliases.jsonl": {"raw": len(text), "deflated": deflated(text)},
                  "context.json": {"raw": len(ctx), "deflated": deflated(ctx)}},
        "warnings": list(dict.fromkeys(b.warnings + b.notes["warnings"])),
        "unattested_heads": b.notes.get("unattested_heads", []),
        "rivals_sharing_names": b.notes.get("rivals_sharing_names", []), "seconds": round(time.time() - t0, 1)}
    if b.notes_ntu:
        result.report[NTU] = {**b.notes_ntu, **({"apart": b.notes["ntu_apart"]} if b.notes.get("ntu_apart") else {}),
                              "attached": _tally(b.attached.values()), "doubles": b.notes.get("ntu_doubles", 0)}
    return result


def _tally(keys: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for k in keys:
        out[k] += 1
    return dict(sorted(out.items()))


# --------------------------------------------------------------------------- review
REVIEW_COLUMNS = ("rank", "surface", "n", "sh", "verdict", "referents", "blockers", "context_1", "context_2",
                  "context_3", "decision")


def review(result: BuildResult, *, top: int = 200, heldout: Iterable[str] = (), width: int = 20) -> list[list[str]]:
    """The keyword-in-context sheet editors decide from: the names with referents (and the stops of rule 7) the store
    writes most, three passages each (the first, middle and last by date; ◆ where the gates read a drug), held-out
    names and drugs left out.  Rows of :data:`REVIEW_COLUMNS`."""
    b = result.builder
    held = {b.norm(h) for h in heldout}
    gates = AliasIndex(result.records, context=result.context)
    rows: list[list[str]] = []
    for rec in sorted(result.records, key=lambda r: (-r.n, r.s)):
        if not (rec.r or rec.s in result.stopped) or rec.n == 0:
            continue
        heads = {ref.h for ref in rec.r} | {x.split(":", 1)[0] for x in result.stopped.get(rec.s, [])}
        if rec.s in held or heads & held:
            continue
        if rec.r:
            refs = "; ".join(f"{ref.h}·{KINDS.get(ref.k, ref.k)}·{ref.st}·{'+'.join(ref.src)}" for ref in rec.r)
            verdict = ",".join(sorted({ref.st for ref in rec.r}))
        else:
            refs, verdict = "; ".join(result.stopped[rec.s]), "stop"
        free = b.free.get(rec.s, [])
        picks = sorted({0, len(free) // 2, len(free) - 1}) if free else []
        ctx = []
        for k in picks:
            pid = free[k]
            g, text, yr = b.gate(pid), b.text(pid), b.yr(pid)
            offs = gates.free_offsets(g, rec.s, rec.b, yr)
            i = offs[0]
            cues = sorted({c for ref in rec.r for c in ref.c} - {rec.s})
            mark = "◆" if gates.drug_context(g, rec.s, offs, cues) else "◇"
            kwic = text[max(0, i - width):i] + "【" + rec.s + "】" + text[i + len(rec.s):i + len(rec.s) + width]
            ctx.append(f"{mark} {pid} ({_n(yr[0])}–{_n(yr[1])}) {kwic}")
        blockers = [x if isinstance(x, str) else f"{x[0]}[{_n(x[1])},{_n(x[2])})" for x in rec.b]
        blockers = [x for x in blockers if not any(h in x for h in held)]
        rows.append([str(len(rows) + 1), rec.s, str(rec.n), f"{rec.sh:.2f}", verdict, refs, " ".join(blockers[:6]),
                     *(ctx + ["", "", ""])[:3], ""])
        if len(rows) >= top:
            break
    return rows


def review_tsv(rows: list[list[str]]) -> str:
    clean = [[c.replace("\t", " ").replace("\n", " ") for c in row] for row in [list(REVIEW_COLUMNS), *rows]]
    return "".join("\t".join(row) + "\n" for row in clean)


# --------------------------------------------------------------------------- check
def curated_strings(curated: Mapping[str, Any]) -> set[str]:
    """Every name curated.yaml writes (held-out gold names may be none of them), as written."""
    out: set[str] = set()
    for section in CURATED_MAPS:
        strings = curated.get(section)
        for k, v in (strings.items() if isinstance(strings, Mapping) else ()):
            out |= {k, *(v if isinstance(v, list) else [])}
    for key, fields in (("stop", ("s",)), ("repairs", ("from", "to")), ("head_repairs", ("head",)),
                        ("same_drug", ("names",)), ("pairs", ("s", "head", "cues", "anti")),
                        ("first_use", ("s",)), ("decisions", ("s", "head"))):
        for row in curated.get(key) or []:
            if not isinstance(row, Mapping):
                continue
            for f in fields:
                value = row.get(f)
                out |= set(value) if isinstance(value, list) else {value} if value else set()
    return {str(x) for x in out}


def curated_notes(curated: Mapping[str, Any]) -> list[str]:
    """The free text of curated.yaml's rows: ``why`` (the editors') and ``note`` (shipped as ``nt``)."""
    return [str(row[k]) for key in CURATED for row in curated.get(key) or [] if isinstance(row, Mapping)
            for k in ("why", "note") if row.get(k)]


def heldout_in(curated: Mapping[str, Any], heldout: Iterable[str], normalize: Any) -> list[str]:
    """The held-out gold strings curated.yaml writes, compared normalised: as a name, or inside a reason or note."""
    held = {normalize(h) for h in heldout if h}
    names = {normalize(x) for x in curated_strings(curated)}
    text = "\n".join(normalize(x) for x in curated_notes(curated))
    return sorted((held & names) | {h for h in held if h in text})


def check(home: str | Path, *, heldout: Iterable[str] = (), store: CorpusStore | str | Path | None = None,
          rebuild: bool = False) -> dict[str, Any]:
    """What breaks the committed layer's contract, as ``errors`` (and ``warnings``): the schema, a surface under two
    characters, an unknown kind or status, a repeated surface, a cap exceeded, a source that does not ship, a
    sources.yaml or curated.yaml that is not YAML, sources.yaml's shape (:func:`read_registry`), curated.yaml's shape
    (:func:`validate_curated`), a held-out gold name curated.yaml writes (normalised: as a name, or in a reason or
    note; counted, never named), a name curated.yaml splits that the NTU table joins to a drug or heads a drug with
    (:func:`apart_errors`), the size budget of aliases.jsonl and of the directory; a warning when the header names another web pack than ``corpus/web`` holds (the layer is to be
    built again); with a store, a witness from a ``NEVER_PACKED`` source, missing from it, or not writing the name it
    witnesses; with ``rebuild``, a build on the store that differs from the bytes (none when curated.yaml is not YAML
    or its shape is wrong: the build would refuse it)."""
    home = Path(home)
    d = home / "domains" / "classics" / ALIAS_DIR
    errors: list[str] = []
    warnings: list[str] = []
    present = sorted(p.name for p in d.iterdir()) if d.is_dir() else []
    errors += [f"{d.name}/ holds {x}, which is not one of its files" for x in present if x not in FILES]
    errors += [f"{d.name}/{x} is missing" for x in FILES if x not in present]
    if errors:
        return {"ok": False, "errors": errors, "warnings": warnings}
    try:
        registry = read_registry(d / "sources.yaml")
    except ValueError as exc:
        return {"ok": False, "errors": [str(exc)], "warnings": warnings}
    sources = {s.get("id"): s for s in registry.get("sources") or []}
    for sid, s in sources.items():
        if not s.get("label") or s.get("ship") not in (True, False):
            errors.append(f"sources.yaml: {sid} needs a label and ship")
        if s.get("class") not in CLASSES:
            errors.append(f"sources.yaml: {sid} has no class of {', '.join(CLASSES)}")
        if s.get("ship") is False and s.get("class") != "local":
            errors.append(f"sources.yaml: {sid} does not ship, so its class is local")
        if s.get("ship") is True and s.get("class") == "local":
            errors.append(f"sources.yaml: {sid} is local, so it does not ship")
        if s.get("class") == "nc" and ("NC" not in str(s.get("licence") or "") or not s.get("attribution")):
            errors.append(f"sources.yaml: {sid} ships under a non-commercial licence: it needs that licence and an "
                          f"attribution")
    text = (d / "aliases.jsonl").read_bytes()
    try:
        header, records = loads_records(text.decode("utf-8"), origin="aliases.jsonl")
    except ValueError as exc:
        return {"ok": False, "errors": errors + [str(exc)], "warnings": warnings}
    used: set[str] = set()
    seen: set[str] = set()
    pids: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for rec in records:
        s = rec.s
        if s in seen:
            errors.append(f"{s}: a surface met twice")
        seen.add(s)
        if len(s) < 2 or sum(map(is_han, s)) < 2:
            errors.append(f"{s}: fewer than two characters")
        if rec.stop and rec.r:
            errors.append(f"{s}: a stop name lists referents")
        if len(rec.raw or ()) > MAX_RAW or len(rec.b) > MAX_BLOCKERS:
            errors.append(f"{s}: over {MAX_RAW} spellings or {MAX_BLOCKERS} blockers")
        for ref in rec.r:
            where = f"{s} → {ref.h}"
            if ref.k not in KINDS:
                errors.append(f"{where}: unknown kind {ref.k}")
            if ref.st not in STATUSES:
                errors.append(f"{where}: unknown status {ref.st}")
            if not ref.src:
                errors.append(f"{where}: no source")
            for src in ref.src:
                used.add(src)
                if src not in sources:
                    errors.append(f"{where}: source {src} is not in sources.yaml")
                elif sources[src].get("ship") is not True:
                    errors.append(f"{where}: source {src} does not ship")
            if len(ref.w) > MAX_WITNESSES or len(ref.c or ()) > MAX_CUES:
                errors.append(f"{where}: over {MAX_WITNESSES} witnesses or {MAX_CUES} cues")
            for w in ref.w:
                if w.kind not in WITNESS_KINDS:
                    errors.append(f"{where}: unknown witness kind {w.kind}")
                pids[w.pid].append((where, w.kind, s))
    pack = home / WEB_PACK
    held = pack_fingerprint(pack) if header.get("web_pack") and pack.exists() else None
    if held is not None and held != header["web_pack"]:
        warnings.append(f"aliases.jsonl was built against another web pack ({header['web_pack']}) than "
                        f"{WEB_PACK.as_posix()} ({held}): build it again on a store of this pack")
    labels = header.get("labels") or {}
    missing = sorted(used - set(labels))
    if missing:
        errors.append(f"header: no label for {', '.join(missing)}")
    for sid, label in labels.items():
        if sid in sources and sources[sid].get("label") != label:
            errors.append(f"header: the label of {sid} is not sources.yaml's")
    try:
        context = json.loads((d / "context.json").read_text(encoding="utf-8"))
        for key in CONTEXT_PATTERNS:
            re.compile(context[key])
        herbs = context["herbs"]
        if herbs != sorted(set(herbs)) or not all(isinstance(h, str) and len(h) >= 2 for h in herbs):
            errors.append("context.json: herbs must be distinct names in code-point order")
    except (ValueError, KeyError, TypeError, re.error) as exc:
        errors.append(f"context.json: {exc}")
    raw, packed = len(text), deflated(text)
    folder = sum(deflated((d / x).read_bytes()) for x in FILES)  # as home.zip stores the directory
    if raw > BUDGET["raw"] or packed > BUDGET["deflated"]:
        errors.append(f"aliases.jsonl: {raw} bytes ({packed} deflated) is over the budget {BUDGET}")
    if folder > BUDGET["directory"]:
        errors.append(f"{d.name}/: {folder} bytes deflated is over the budget {BUDGET['directory']}")
    try:
        curated = read_yaml(d / "curated.yaml") or {}
        shape = validate_curated(curated)
    except ValueError as exc:  # not YAML at all: nothing below reads it
        curated, shape = {}, [str(exc)]
    errors += shape
    # what the checks below read: a section of the wrong type is reported above and read as empty
    curated = ({k: v for k, v in curated.items() if isinstance(v, Mapping if k in CURATED_MAPS else list)}
               if isinstance(curated, Mapping) else {})
    normalize = DomainPack(home / "domains" / "classics").variants.normalize_text
    held = heldout_in(curated, heldout, normalize)
    if held:  # counted, never named: whoever reads the report does not learn the held-out half
        errors.append(f"curated.yaml writes {len(held)} held-out gold name{'' if len(held) == 1 else 's'} (counted, "
                      f"not shown: find the rows by comparing with evals/gold/aliases.yaml outside the eval)")
    errors += apart_errors(records, curated, normalize, heldout={normalize(h) for h in heldout if h})
    if store is not None:
        db = store if isinstance(store, CorpusStore) else CorpusStore(store, readonly=True)
        _check_store(db, pids, curated, normalize, errors, warnings)
        if rebuild and not shape:  # a build refuses a malformed curated.yaml: its errors are the report's
            result = build_open(db, home)
            if result.text().encode("utf-8") != text:
                errors.append("aliases.jsonl differs from a build on this store (run `taochronos aliases build`)")
            if result.context_text().encode("utf-8") != (d / "context.json").read_bytes():
                errors.append("context.json differs from a build on this store")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "surfaces": len(records),
            "bytes": {"raw": raw, "deflated": packed, "directory": folder}}


def split_names(curated: Mapping[str, Any], normalize: Any) -> set[str]:
    """The names curated.yaml splits — a row (not a candidate's) with a period window, a part's or an older name's
    kind, or the status cue: 青木香 (木香 before 1100, 马兜铃's root after), 通草, 小草."""
    return {normalize(r["s"]) for key in ("pairs", "decisions") for r in curated.get(key) or []
            if isinstance(r, Mapping) and isinstance(r.get("s"), str) and r.get("status") != "candidate"
            and (r.get("valid") or r.get("kind") in APART_KINDS or r.get("status") == "cue")}


def apart_errors(records: Iterable[AliasRecord], curated: Mapping[str, Any], normalize: Any, *,
                 heldout: Iterable[str] = ()) -> list[str]:
    """The NTU table joins no name curated.yaml splits (:func:`split_names`) to a drug and heads no drug with it: such
    a name is a member (``ho``) of no other drug unless a same-drug row lists both, and no referent only the table
    gives (``ntu40k``, ``store`` beside it at most) is headed by it.  A member is searched as its drug's own name, in
    every period: the editors' split would be lost.  A held-out gold string is not named."""
    split = split_names(curated, normalize)
    held = set(heldout)
    same: dict[str, set[str]] = defaultdict(set)
    for row in curated.get("same_drug") or []:
        names = {normalize(x) for x in row.get("names") or [] if isinstance(x, str)} if isinstance(row, Mapping) else set()
        for x in names:
            same[x] |= names
    out = []
    headed: dict[str, int] = defaultdict(int)
    for rec in records:
        if rec.s in split and rec.ho is not None and rec.ho != rec.s and rec.ho not in same[rec.s]:
            drug = "a held-out name" if rec.ho in held else rec.ho
            out.append(f"{rec.s}: a member of {drug}, though curated.yaml splits it (a window, a part's or an older "
                       f"name, a cue)")
        for ref in rec.r:
            if ref.h in split and not set(ref.src) - {NTU, "store"}:
                headed[ref.h] += 1
    out += [f"{h}: heads a drug of the NTU table ({k} name{'' if k == 1 else 's'}), though curated.yaml splits it"
            for h, k in sorted(headed.items())]
    return out


def layer_diff(old: str, new: str, *, heldout: Iterable[str] = (), top: int = 100) -> dict[str, Any]:
    """What a rebuild changes, for review before it ships (both ``aliases.jsonl`` texts): surfaces added and removed,
    names that become a member of another drug (``ho``), referents lost, pairs whose status drops (open → cue or
    candidate, cue → candidate) with the drugs new beside them, and stop names gained or lost.  Rows that write a
    held-out gold string are counted, never listed."""
    held = set(heldout)
    _, a = loads_records(old, origin="old")
    _, b = loads_records(new, origin="new")
    was, now = {r.s: r for r in a}, {r.s: r for r in b}
    rank = {"open": 0, "cue": 1, "candidate": 2}
    rows: dict[str, list[Any]] = {"ho": [], "lost": [], "drops": []}
    counts: dict[str, Any] = {"ho": 0, "lost": 0, "drops": defaultdict(int), "held_out_rows": 0}

    def keep(key: str, row: list[Any], strings: Iterable[str]) -> None:
        if held & set(strings):
            counts["held_out_rows"] += 1
        elif len(rows[key]) < top:
            rows[key].append(row)

    for s, r in sorted(now.items()):
        o = was.get(s)
        if r.ho is not None and r.ho != s and (o is None or o.ho != r.ho):
            counts["ho"] += 1
            keep("ho", [s, o.ho if o else None, r.ho], [s, r.ho, o.ho if o and o.ho else ""])
        if o is None or r.stop:
            continue
        mine = {ref.h: ref for ref in r.r}
        for ref in o.r:
            new_ref = mine.get(ref.h)
            if new_ref is None:
                counts["lost"] += 1
                keep("lost", [s, ref.h, ref.st, sorted(mine)], [s, ref.h, *mine])
            elif rank[new_ref.st] > rank[ref.st]:
                beside = sorted(set(mine) - {x.h for x in o.r})
                counts["drops"][f"{ref.st}→{new_ref.st}"] += 1
                keep("drops", [s, ref.h, ref.st, new_ref.st, beside], [s, ref.h, *beside])
    counts["drops"] = dict(sorted(counts["drops"].items()))
    stops = ({r.s for r in a if r.stop}, {r.s for r in b if r.stop})
    return {"surfaces": {"old": len(was), "new": len(now), "added": len(set(now) - set(was)),
                         "removed": len(set(was) - set(now))},
            "stops": {"old": len(stops[0]), "new": len(stops[1]), "gained": len(stops[1] - stops[0]),
                      "lost": len(stops[0] - stops[1])},
            **counts, "rows": rows}


def _check_store(db: CorpusStore, pids: dict[str, list[tuple[str, str, str]]], curated: Mapping[str, Any],
                 normalize: Any, errors: list[str], warnings: list[str]) -> None:
    """Witnesses against the store: there (on a web store a missing one is a warning), never NEVER_PACKED, of kind
    ``l`` exactly when they are the 别名录's, and writing the name they witness when they are not."""
    from .webcorpus import NEVER_PACKED

    web = (db.meta("edition") or "full") == "web"
    sources = dict(db.db.execute("SELECT id, source FROM books").fetchall())
    given = {p for key in CURATED for row in curated.get(key) or [] if isinstance(row, Mapping)
             for p in _strings(row.get("wit"))}
    repaired = {r["passage"] for r in curated.get("head_repairs") or []
                if isinstance(r, Mapping) and isinstance(r.get("passage"), str)}
    wanted = sorted(set(pids) | given | repaired)
    rows: dict[str, tuple[str, str]] = {}
    for k in range(0, len(wanted), 500):
        chunk = wanted[k:k + 500]
        rows.update((pid, (book, text)) for pid, book, text in db.db.execute(
            f"SELECT id, book_id, text FROM passages WHERE id IN ({','.join('?' * len(chunk))})", chunk))
    for pid in wanted:
        if pid not in rows:
            (warnings if web else errors).append(f"{pid} is not in this store")
            continue
        book, text = rows[pid]
        if sources.get(book) in NEVER_PACKED:
            errors.append(f"{pid} is from {sources[book]}, which may never be packed")
        norm = None
        for where, kind, s in pids.get(pid, ()):
            if (book == BOOK) != (kind == "l"):
                errors.append(f"{where}: witness {pid} of kind {kind}")
            elif kind != "l":
                norm = normalize(text) if norm is None else norm
                if s not in norm:
                    errors.append(f"{where}: witness {pid} does not write {s}")
