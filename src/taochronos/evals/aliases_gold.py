"""The alias gold (``evals/gold/aliases.yaml``, spec §3.10): its split rule, its contract, and the candidate pools its
items come from.

* ``split_of(group)`` — dev or held-out, fixed by the group's name before the first run; ``groups(gold)`` names the
  groups (items that share any string, named by the first of them) and ``split_digest`` pins the result;
* ``validate(gold, corpus=None, pools=None)`` — what breaks the file's contract (header, quotas, keys and types,
  groups and splits, tuned names, witnesses, pool provenance), as messages;
* ``heldout_surfaces(gold)`` — the strings curated.yaml may not hold (``aliases check``, ``aliases review``);
* ``pools(store)`` — the §3.10 pools, mined from a store with this module's own patterns (never the alias layer's, so
  a pair the 别名录 lacks is still found and can count as a miss), each candidate with its band and sub-pool;
  ``propose`` draws from them with the seed into ``<data>/aliases/gold-candidates.yaml`` for annotators:
  ``python -m taochronos.evals.aliases_gold propose [--db PATH] [--data DIR] [--all]``.
"""

from __future__ import annotations

import hashlib
import random
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Container, Iterable

import yaml

from ..protocol.yamlio import load_yaml

TYPES = ("alias", "head", "ambiguous", "period", "trap", "substring")
QUOTAS = {"alias": 30, "head": 25, "ambiguous": 20, "period": 20, "trap": 15, "substring": 10}
# the sub-pools an item may come from, by type (``pools``); a held-out ambiguous item must come from a source the
# shipped layer reads (the lexicon's rival entries or the 别名录), since curated.yaml may not add its names
POOLS = {"alias": ("equation", "gloss", "entry"), "head": ("equation", "gloss", "entry"),
         "ambiguous": ("lexicon", "bielu", "store"), "period": ("taboo", "curated", "dated"),
         "trap": ("false-friend", "ordinary"), "substring": ("substring",)}
SHIPPED_AMBIGUOUS = ("lexicon", "bielu")
RESOLUTION_ROWS = 80
BANDS = ("1-2", "3-19", ">=20")
ACTIONS = ("expand", "candidate", "none")
KEYS = ("id", "group", "split", "type", "pool", "query", "asked", "asked_cues", "false_friends", "referents", "wrong",
        "expect_candidates", "floor", "band", "adjudicated")
REF_KEYS = {"head", "names", "valid", "witness"}
ADJ_KEYS = {"name", "witness", "by", "date"}  # + optional parallel
ROW_KEYS = ("surface", "expect_heads", "expect_action", "group", "split")
SEED = 23
EXCLUDED = ("jc_c030",)  # the 别名录 itself: never a witness, never a hit
NO_WITNESS = ("jc_c030", "bencao_gangmu_")  # the lists the alias layer is built from (prefixes)
# sha256 of the sorted "id group split" lines, pinned when the file was frozen: a renamed group or a moved item fails
SPLIT_SHA256 = "cd186cf8937f895adca94b6a4ba80da19d68f373a6b3ceb8bf002fe9f2dc463a"
# the datasets report's false friends (top-40 aliases of the two datasets judged "a common word")
FALSE_FRIENDS = ("小便", "不过", "缺盆", "白虎", "生菜", "月经", "芦头", "内虚", "百节", "风药", "内消", "胞衣", "血结", "针石",
                 "头发", "天癸", "将军", "伤寒头")
# the spec's curated example (§3.3), which curated.yaml starts from: referent changes (name, head) and first-use names
SPEC_CURATED = (("通草", "木通"), ("通草", "通脱木"), ("青木香", "木香"), ("青木香", "马兜铃"), ("党参", None), ("枳壳", None),
                ("苍术", None), ("官桂", None), ("川贝", None), ("浙贝", None))
DATED_GAP = 300  # years between two equated names' first attestations that make a period candidate
ORDINARY = (3, 2 / 3)  # a trap candidate: written in 3 passages or more, at most two thirds of them in 本草 books

# eval-local equation patterns (the idea of study/names.py's, never imported from the alias layer)
HAN = "[㐀-鿿]"
EQUATE = ("(?:一名|又名|亦名|又曰|一曰|俗名|俗呼为|俗呼|俗谓之|俗称|今名|今呼为|今呼|今人呼为|土人呼为|人呼为|古名|又称|"
          "谓之|呼为)")
_LEFT = f"(?:(?<!{HAN})(?!曰)|(?<=曰))"  # a name starts after a non-Han character (，：》（ …) or after 曰
_NAME = f"为?({HAN}{{2,4}}?)(?=[^㐀-鿿]|{EQUATE}|$)"  # the shortest run before a non-Han character or an EQUATE (一名为粉锡)
_CHAIN_HEAD = re.compile(f"{_LEFT}({HAN}{{2,4}})(?=[，,]?{EQUATE})")
_CHAIN_LINK = re.compile(f"[，,]?{EQUATE}[，,]?{_NAME}")
_GLOSS = re.compile(f"{_LEFT}({HAN}{{2,4}})[（(](?:即|乃|一名|又名|俗名|俗呼|今名){_NAME}(?:也)?[，。,）)]")
_IS = re.compile(f"({HAN}{{2,4}})[，,]?(?:即是|即|乃){EQUATE}?({HAN}{{2,4}}?)(?:是也|也|(?=[，。；])|$)")
_BRACKET = re.compile(f"[（(]((?:[，,、]?(?:即|{EQUATE})为?{HAN}{{2,4}}?(?=[^㐀-鿿]|{EQUATE}))+)")
_BRACKET_NAME = re.compile(f"(?:即|{EQUATE})为?({HAN}{{2,4}}?)(?=[^㐀-鿿]|{EQUATE}|$)")
_EDITORIAL = re.compile(r"〔[^〕]*〕|｛[^｝]*｝")  # 本草求真's 〔专入肝胃〕 and ｛…｝ notes
_EQUATE_WORD = re.compile(EQUATE)
_BEFORE = re.compile(f"{_LEFT}({HAN}{{2,4}})$")
# a section's numbering, as the build reads it (aliasbuild._SECTION_NUM, a test holds the two equal): digits, or
# numerals before a separator or three or more of them (一八一梔子, 一○七　白石脂), never the numeral a drug's name opens
# with (五味子, 百合, 三七)
_SECTION_NUM = re.compile(r"^(?:[0-9]+|[〇○一二三四五六七八九十百千]{3,}|[〇○一二三四五六七八九十百千]+(?=[、.．\s　]))[、.．\s　]*")
_SECTION = re.compile(f"^({HAN}{{2,4}})$")
_NUMERALS = re.compile("[〇○一二三四五六七八九十百千]+")  # a heading of numerals alone: a chapter's number, unless a herb (三七)
_ENTRY_ALIAS = re.compile(f"{EQUATE}{_NAME}")


def split_of(group: str) -> str:
    """``dev`` when sha1(group) is even, else ``heldout``."""
    return "dev" if int(hashlib.sha1(group.encode("utf-8")).hexdigest(), 16) % 2 == 0 else "heldout"


def band(n: int) -> str:
    return "1-2" if n <= 2 else "3-19" if n < 20 else ">=20"


def gold_path(home: str | Path | None = None) -> Path:
    from ..config import find_home

    return Path(home or find_home()) / "evals" / "gold" / "aliases.yaml"


def load_gold(home: str | Path | None = None) -> dict[str, Any]:
    return load_yaml(gold_path(home)) or {}


def _strs(x: Any) -> list[str]:
    return [s for s in x if isinstance(s, str)] if isinstance(x, list) else []


def _refs(item: dict[str, Any]) -> list[dict[str, Any]]:
    return [r for r in item.get("referents") or [] if isinstance(r, dict)] if isinstance(item.get("referents"), list) \
        else []


def item_surfaces(item: dict[str, Any]) -> set[str]:
    """Every string an item labels with: its asked form, referent heads and names, wrong names, cues and false
    friends.  Items sharing any of them share a group, and the held-out ones are kept out of curated.yaml."""
    out = {item["asked"]} if isinstance(item.get("asked"), str) else set()
    for r in _refs(item):
        out |= set(_strs([r.get("head")])) | set(_strs(r.get("names")))
    for k in ("wrong", "asked_cues", "false_friends"):
        out |= set(_strs(item.get(k)))
    return out


def row_surfaces(row: dict[str, Any]) -> set[str]:
    return set(_strs([row.get("surface")])) | set(_strs(row.get("expect_heads")))


def _union(sets: list[set[str]]) -> list[int]:
    """The component (index of its first member) of each set, joining sets that share a string."""
    parent = list(range(len(sets)))
    owner: dict[str, int] = {}

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, ss in enumerate(sets):
        for s in sorted(ss):
            if s in owner:
                a, b = find(owner[s]), find(i)
                parent[max(a, b)] = min(a, b)
            else:
                owner[s] = i
    return [find(i) for i in range(len(sets))]


def groups(gold: dict[str, Any]) -> tuple[list[str], list[str | None]]:
    """The group of each item and of each resolution row.  Items sharing any string form a group, named by its first
    item in file order: the item's head when it is an alias item, else its asked form.  A row takes the group of the
    items it touches, else its own surface (None when it touches two groups)."""
    items = [i for i in gold.get("items") or [] if isinstance(i, dict)]
    rows = [r for r in gold.get("resolution") or [] if isinstance(r, dict)]
    comp = _union([item_surfaces(i) for i in items])
    name = {c: (_refs(items[c]) or [{}])[0].get("head") if items[c].get("type") == "alias" else items[c].get("asked")
            for c in set(comp)}
    item_groups = [str(name[c]) for c in comp]
    owner = {s: item_groups[k] for k, i in enumerate(items) for s in item_surfaces(i)}
    rcomp = _union([row_surfaces(r) for r in rows])
    row_groups: list[str | None] = []
    for k, r in enumerate(rows):
        touched = {owner[s] for j, rr in enumerate(rows) if rcomp[j] == rcomp[k]
                   for s in row_surfaces(rr) if s in owner}
        own = str(rows[rcomp[k]].get("surface"))
        row_groups.append(touched.pop() if len(touched) == 1 else None if touched else own)
    return item_groups, row_groups


def split_digest(gold: dict[str, Any]) -> str:
    """sha256 of the sorted ``id group split`` lines of the items (the pin in ``SPLIT_SHA256``)."""
    lines = sorted(f"{i.get('id')} {i.get('group')} {i.get('split')}" for i in gold.get("items") or []
                   if isinstance(i, dict))
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def heldout_surfaces(gold: dict[str, Any]) -> set[str]:
    """Every string of the held-out items and resolution rows: curated.yaml may hold none of them."""
    out: set[str] = set()
    for item in gold.get("items") or []:
        if isinstance(item, dict) and item.get("split") == "heldout":
            out |= item_surfaces(item)
    for row in gold.get("resolution") or []:
        if isinstance(row, dict) and row.get("split") == "heldout":
            out |= row_surfaces(row)
    return out


def _no_witness(book_id: str) -> bool:
    return any(book_id == p or (p.endswith("_") and book_id.startswith(p)) for p in NO_WITNESS)


# --------------------------------------------------------------------------- the contract
def _window(v: Any) -> bool:
    if v is None:
        return True
    if not (isinstance(v, list) and len(v) == 2 and v != [None, None]):
        return False
    if any(x is not None and (isinstance(x, bool) or not isinstance(x, int)) for x in v):
        return False
    return None in v or v[0] < v[1]


def _item_errors(item: Any, k: int) -> list[str]:
    """Shape and type errors of one item (an item with any is left out of the later checks)."""
    if not isinstance(item, dict):
        return [f"item {k}: not a mapping"]
    iid = item.get("id", f"item {k}")
    if tuple(item) != KEYS:
        return [f"{iid}: keys {list(item)}, expected {list(KEYS)}"]
    errs: list[str] = []
    for key in ("id", "group", "query", "asked", "pool"):
        if not isinstance(item[key], str) or not item[key]:
            errs.append(f"{iid}: {key} must be a non-empty string")
    for key in ("asked_cues", "false_friends", "wrong", "expect_candidates"):
        if not isinstance(item[key], list) or len(_strs(item[key])) != len(item[key]):
            errs.append(f"{iid}: {key} must be a list of strings")
    if item["split"] not in ("dev", "heldout") or item["type"] not in TYPES or item["band"] not in BANDS:
        errs.append(f"{iid}: split, type or band")
    if not isinstance(item["referents"], list) or not item["referents"]:
        errs.append(f"{iid}: referents must be a non-empty list")
    elif any(not isinstance(r, dict) or set(r) != REF_KEYS for r in item["referents"]):
        errs.append(f"{iid}: each referent needs exactly {sorted(REF_KEYS)}")
    else:
        for r in item["referents"]:
            names = r["names"] if isinstance(r["names"], list) else [None]
            if not isinstance(r["head"], str) or len(r["head"]) < 2 or not isinstance(r["witness"], str) \
                    or any(not isinstance(n, str) or len(n) < 2 for n in names):
                errs.append(f"{iid}: referent {r['head']} needs a head, a witness and names of two characters or more")
            if not _window(r["valid"]):
                errs.append(f"{iid}: valid {r['valid']} must be null or [from, to) years, not both null")
    fl = item["floor"]
    if fl is not None and not (isinstance(fl, dict) and set(fl) == {"surface", "year"}
                               and isinstance(fl["surface"], str)
                               and isinstance(fl["year"], int) and not isinstance(fl["year"], bool)):
        errs.append(f"{iid}: floor {fl} must be null or {{surface, year}}")
    if not isinstance(item["adjudicated"], list) or any(
            not isinstance(a, dict) or not ADJ_KEYS <= set(a) <= ADJ_KEYS | {"parallel"}
            or not all(isinstance(a[x], str) and a[x] for x in ADJ_KEYS)
            or not isinstance(a.get("parallel", ""), str) for a in item["adjudicated"]):
        errs.append(f"{iid}: adjudicated rows need name, witness, by and date (and an optional parallel)")
    if not errs and len(item["asked"]) < 2:
        errs.append(f"{iid}: the asked form needs two characters or more")
    return errs


def _item_rules(item: dict[str, Any]) -> list[str]:
    """What a well-formed item must also satisfy."""
    iid, asked, t = item["id"], item["asked"], item["type"]
    refs = item["referents"]
    heads = [r["head"] for r in refs]
    names = {n for r in refs for n in r["names"]}
    errs: list[str] = []
    if item["pool"] not in POOLS[t]:
        errs.append(f"{iid}: pool {item['pool']} is not one of {list(POOLS[t])}")
    if asked not in item["query"]:
        errs.append(f"{iid}: the query does not write the asked form")
    if len(set(heads)) != len(heads) or not set(item["expect_candidates"]) <= set(heads):
        errs.append(f"{iid}: heads must differ, and expect_candidates must be referent heads")
    clash = set(item["wrong"]) & (names | set(heads) | {asked})
    if clash:
        errs.append(f"{iid}: {sorted(clash)} both wrong and a name")
    for f in item["false_friends"]:
        if asked not in f and not any(n in f for n in names):
            errs.append(f"{iid}: false friend {f} masks neither the asked form nor a name")
    if t == "ambiguous" and (len(refs) < 2 or len(item["expect_candidates"]) < 2):
        errs.append(f"{iid}: an ambiguous item lists two referents or more and expects them")
    if t == "head" and (heads != [asked] or item["expect_candidates"]):
        errs.append(f"{iid}: a head item has the asked form as its one referent and expects no candidates")
    if t == "trap" and not item["expect_candidates"] and (names or item["asked_cues"]):
        # a stop: the drug sense is not what the query asks, so expanding to the head must not score
        errs.append(f"{iid}: a trap expected to stay unexpanded has no names and no cues")
    adj = [a["name"] for a in item["adjudicated"]]
    if len(set(adj)) != len(adj):
        errs.append(f"{iid}: a name adjudicated twice")
    for n in sorted(names - {asked} - set(adj)):
        errs.append(f"{iid}: name {n} has no adjudicated witness")
    for n in sorted(set(adj) - names):
        errs.append(f"{iid}: adjudicated {n} is not a referent name")
    return errs


def _row_errors(row: Any, k: int) -> list[str]:
    if not isinstance(row, dict) or tuple(row) != ROW_KEYS:
        return [f"resolution {k}: {row} needs exactly {list(ROW_KEYS)}"]
    heads, action = row["expect_heads"], row["expect_action"]
    if not isinstance(row["surface"], str) or len(row["surface"]) < 2 or not isinstance(heads, list) \
            or len(_strs(heads)) != len(heads) or action not in ACTIONS or row["split"] not in ("dev", "heldout"):
        return [f"resolution {k}: {row}"]
    want = {"expand": len(heads) == 1, "candidate": len(heads) >= 1, "none": not heads}[action]
    return [] if want else [f"resolution {row['surface']}: {action} with {len(heads)} heads"]


def validate(gold: Any, *, corpus: Any = None, pools: dict[str, list[dict[str, Any]]] | None = None) -> list[str]:
    """Problems with the gold, as messages ([] when it holds).  With a ``StoreCorpus``, every witness must also exist
    outside jc_c030 and bencao_gangmu_* and write its name beside a partner (``_witness_errors``); with ``pools``
    (``pools()`` on the store the gold was drawn from), every item must be a candidate of its type's sub-pool."""
    if not isinstance(gold, dict):
        return ["the gold is not a mapping"]
    errs: list[str] = []
    if gold.get("version") != 1 or gold.get("seed") != SEED:
        errs.append("header: version 1 and seed 23 expected")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(gold.get("frozen") or "")):
        errs.append("header: frozen must be a date")
    if not set(EXCLUDED) <= set(_strs(gold.get("excluded_books"))):
        errs.append("header: excluded_books must hold jc_c030")
    if not _strs(gold.get("report_without")):
        errs.append("header: report_without must list the books reported without (bencao_gangmu_skqs)")
    tuned = gold.get("tuned")
    if not isinstance(tuned, list) or not tuned or len(_strs(tuned)) != len(tuned):
        errs.append("header: tuned must list the names the design was tuned on")
    items = gold.get("items") if isinstance(gold.get("items"), list) else []
    rows = gold.get("resolution") if isinstance(gold.get("resolution"), list) else []
    if not items or not rows:
        errs.append("items and resolution must be lists")
    bad = [e for k, i in enumerate(items) for e in _item_errors(i, k)]
    bad += [e for k, r in enumerate(rows) for e in _row_errors(r, k)]
    if bad:
        return errs + bad  # the checks below read the keys
    counts: dict[str, int] = defaultdict(int)
    for item in items:
        counts[item["type"]] += 1
        errs += _item_rules(item)
    for t in TYPES:
        if counts[t] != QUOTAS[t]:
            errs.append(f"quota: {counts[t]} {t} items, {QUOTAS[t]} expected")
    ids = [i["id"] for i in items]
    if len(set(ids)) != len(ids):
        errs.append("duplicate item ids")
    item_groups, row_groups = groups(gold)
    for item, g in zip(items, item_groups):
        if item["group"] != g or item["split"] != split_of(g):
            errs.append(f"{item['id']}: group {item['group']}/{item['split']}, the rule gives {g}/{split_of(g)}")
    if SPLIT_SHA256 and split_digest(gold) != SPLIT_SHA256:
        errs.append("split: the (id, group, split) list differs from the one pinned when the gold was frozen")
    if len(rows) != RESOLUTION_ROWS:
        errs.append(f"resolution: {len(rows)} rows, {RESOLUTION_ROWS} expected")
    if len({r["surface"] for r in rows}) != len(rows):
        errs.append("resolution: duplicate surfaces")
    for r, g in zip(rows, row_groups):
        if g is None:
            errs.append(f"resolution {r['surface']}: touches items of two groups")
        elif r["group"] != g or r["split"] != split_of(g):
            errs.append(f"resolution {r['surface']}: group {r['group']}/{r['split']}, the rule gives {g}/{split_of(g)}")
    for item in items:
        if item["type"] == "ambiguous" and item["split"] == "heldout" and item["pool"] not in SHIPPED_AMBIGUOUS:
            errs.append(f"{item['id']}: a held-out ambiguous item must come from {list(SHIPPED_AMBIGUOUS)} "
                        f"(curated.yaml may not add its names)")
    seen = set(_strs(tuned)) & heldout_surfaces(gold)
    if seen:
        errs.append(f"tuned: held-out items or rows use names the design was tuned on: {sorted(seen)}")
    if corpus is not None:
        errs += _witness_errors(items, corpus)
    if pools is not None:
        errs += pool_errors(items, pools)
    return errs


def _witness_errors(items: list[dict[str, Any]], corpus: Any) -> list[str]:
    """A referent's witness writes the asked form and the head or one of its names (only the asked form when it is
    the head, or when the passage is one side of a parallel row of the item); a name's witness writes the name and a
    partner (the asked form, a head or another name; none for the asked form itself).  Text or section heading (an
    entry witness) count, and a name only inside a longer partner, or a partner only inside the name, does not.  A
    ``parallel`` row's witness writes the name in a line (six characters in common) that the parallel writes with a
    partner."""
    wanted: list[tuple[str, str, str, set[str], str | None]] = []  # (item, name, pid, partners, parallel pid)
    for item in items:
        asked = item["asked"]
        everyone = {asked} | {r["head"] for r in item["referents"]} | {n for r in item["referents"] for n in r["names"]}
        sides = {x for a in item["adjudicated"] if a.get("parallel") for x in (a["witness"], a["parallel"])}
        for r in item["referents"]:
            alone = r["head"] == asked or r["witness"] in sides
            wanted.append((item["id"], asked, r["witness"],
                           set() if alone else ({r["head"]} | set(r["names"])) - {asked}, None))
        wanted += [(item["id"], a["name"], a["witness"], set() if a["name"] == asked else everyone - {a["name"]},
                    a.get("parallel")) for a in item["adjudicated"]]
    pids = {w[2] for w in wanted} | {w[4] for w in wanted if w[4]}
    found = {p.id: p for p in corpus.passages_by_id(sorted(pids))}
    errs = []
    for iid, name, pid, partners, parallel in wanted:
        p, q = found.get(pid), found.get(parallel) if parallel else None
        if p is None or _no_witness(p.book_id) or (parallel and (q is None or _no_witness(q.book_id))):
            errs.append(f"{iid}: witness {pid} of {name} is missing or in an excluded book")
            continue
        text = corpus.normalize(p.text) + "|" + corpus.normalize(p.locator.section or "")
        if name not in _mask(text, [x for x in partners if name in x and x != name]):
            errs.append(f"{iid}: witness {pid} does not write {name}")
        elif parallel:
            twin = corpus.normalize(q.text)
            if not _writes_partner(twin, "", partners) or not _shares_line(text, name, twin):
                errs.append(f"{iid}: {pid} and its parallel {parallel} do not write one line with {name} and a partner")
        elif partners and not _writes_partner(text, name, partners):
            errs.append(f"{iid}: witness {pid} writes {name} but none of {sorted(partners)}")
    return errs


def _mask(text: str, strings: Iterable[str]) -> str:
    for x in sorted(strings, key=len, reverse=True):
        text = text.replace(x, "|" * len(x))
    return text


def _writes_partner(text: str, name: str, partners: set[str]) -> bool:
    """A partner occurs: one containing the name as itself, any other outside the name's occurrences."""
    rest = _mask(text, [name]) if name else text
    return any(x in (text if name and name in x else rest) for x in partners)


def _shares_line(text: str, name: str, other: str, size: int = 6) -> bool:
    """Some run of ``size`` characters near ``name`` in ``text`` (the name itself left out) occurs in ``other``."""
    for m in re.finditer(re.escape(name), text):
        for part in (text[max(0, m.start() - 40): m.start()], text[m.end(): m.end() + 40]):
            if any(part[i: i + size] in other for i in range(len(part) - size + 1)):
                return True
    return False


def pool_errors(items: list[dict[str, Any]], pools: dict[str, list[dict[str, Any]]]) -> list[str]:
    """Items whose asked form is not a candidate of the sub-pool they name (an alias or head item: any equated name,
    the head pool listing each with its partners)."""
    have = {("alias" if t == "head" else t, c["pool"], c["asked"]) for t, cands in pools.items() for c in cands}
    return [f"{i['id']}: {i['asked']} is not in the {i['pool']} pool of {i['type']}" for i in items
            if ("alias" if i["type"] == "head" else i["type"], i["pool"], i["asked"]) not in have]


def summary(gold: dict[str, Any]) -> dict[str, Any]:
    """Item counts by type and split, by band, by pool, and the groups."""
    by: dict[str, dict[str, int]] = {t: {"dev": 0, "heldout": 0} for t in TYPES}
    bands: dict[str, dict[str, int]] = {t: {b: 0 for b in BANDS} for t in TYPES}
    pools: dict[str, int] = defaultdict(int)
    for item in gold.get("items") or []:
        by[item["type"]][item["split"]] += 1
        bands[item["type"]][item["band"]] += 1
        pools[f"{item['type']}/{item['pool']}"] += 1
    groups_ = {i["group"]: i["split"] for i in gold.get("items") or []}
    rows = gold.get("resolution") or []
    return {"items": by, "bands": bands, "pools": dict(pools), "groups": {s: sum(1 for v in groups_.values() if v == s)
                                                                          for s in ("dev", "heldout")},
            "resolution": {s: sum(1 for r in rows if r.get("split") == s) for s in ("dev", "heldout")},
            "split_sha256": split_digest(gold)}


# --------------------------------------------------------------------------- the candidate pools
def _name_ok(x: str) -> bool:
    return not _EQUATE_WORD.search(x) and not x.startswith(("为", "是", "此", "即")) and not x.endswith(("之称", "之名"))


def _pairs(text: str, head: str | None = None, known: Callable[[str], bool] = lambda s: False
           ) -> Iterable[tuple[str, str, str]]:
    """(x, y, kind) equations in a normalised text: 一名 chains (every link pairs with the chain's first name), X即Y也,
    X乃Y也, X，即Y。, X（即Y）, and bracketed 一名 lists, whose names pair with the name before the bracket or, after a
    full stop, with ``head`` (the section's drug, or the drug the passage opens with) and with the first of them.
    In unpunctuated text X即Y也 takes the longest ``known`` suffix of X (狼牙马勃乃马屁菌也 → 马勃)."""
    text = _EDITORIAL.sub("", text)
    for m in _CHAIN_HEAD.finditer(text):
        x, pos = m.group(1), m.end()
        while (link := _CHAIN_LINK.match(text, pos)) is not None:
            yield x, link.group(1), "equation"
            pos = link.end()
    for m in _GLOSS.finditer(text):
        yield m.group(1), m.group(2), "gloss"
    for m in _IS.finditer(text):
        x = m.group(1)
        free = m.start() == 0 or not re.match(HAN, text[m.start() - 1])
        x = next((x[i:] for i in range(len(x) - 1) if known(x[i:])), x if free else None)
        if x:
            yield x, m.group(2), "equation"
    for m in _BRACKET.finditer(text):
        prefix = text[: m.start()].rstrip("、")
        before = _BEFORE.search(prefix)
        x = before.group(1) if before else head if not prefix or not re.match(HAN, prefix[-1]) else None
        ys = _BRACKET_NAME.findall(m.group(1))
        for y in ys:
            if x:
                yield x, y, "gloss"
            if not before and y != ys[0]:
                yield ys[0], y, "gloss"


def _entry_head(section: str | None, normalize: Callable[[str], str]) -> str | None:
    """The drug a 本草 section is headed by, as the build reads it (``aliasbuild.entry_head``): the innermost heading,
    bracketed glosses then numbering dropped (一八三　蘗（柏）木 → 蘗木, 一七一　五味子 → 五味子), of two to four
    characters."""
    s = re.sub(r"[（(][^）)]*[）)]", "", normalize((section or "").split(" · ")[-1])).strip()
    m = _SECTION.match(_SECTION_NUM.sub("", s).strip())
    return m.group(1) if m else None


def _entry_drug(section: str | None, normalize: Callable[[str], str], herbs: Container[str]) -> str | None:
    """The drug a 本草 section of the pools is headed by (:func:`_entry_head`), never a chapter's number: a heading of
    numerals alone (六七, 一一, which the build's rule keeps whole for 三七's sake) heads an entry only as a lexicon herb."""
    head = _entry_head(section, normalize)
    return None if head and _NUMERALS.fullmatch(head) and head not in herbs else head


def pools(store: Any, home: str | Path | None = None) -> dict[str, Any]:
    """Mine the §3.10 pools from a store (a ``CorpusStore`` or a path; opened read-only) with jc_c030 excluded.

    * alias / head — equations and glosses (``_pairs``) in every book outside jc_c030 and bencao_gangmu_*, and the
      一名/又名… lists in the first 400 characters of 本草 sections headed by a drug (entry); a pair is (head, alias) when one
      side is a herb of the full-corpus lexicon and the other is not, or is not a headword, and is listed both ways
      when both sides are herbs;
    * ambiguous — names filed under two herbs or more in the lexicon (lexicon), listed under two 别名录 heads or more
      (bielu), or equated with two herbs of different entries by the pairs above (store);
    * period — taboo pairs with a herb side (taboo), curated windows and first-use years (curated: curated.yaml when
      it exists, and the spec's example ``SPEC_CURATED``), and equated names first attested ``DATED_GAP`` years or more
      apart (dated);
    * trap — the datasets report's false friends, and two-character equated names written in ``ORDINARY[0]`` passages
      or more, at most ``ORDINARY[1]`` of them in 本草 books (ordinary);
    * substring — drug names (lexicon herbs and equated names) inside a longer name of another drug.

    Each candidate carries ``pool`` (its sub-pool), ``n`` (passages writing the asked form) and ``band``."""
    from ..config import find_home
    from ..plugins.classics.domain import DomainPack
    from ..plugins.classics.ingest.aliases import read_bielu_store
    from ..plugins.classics.store import CorpusStore, StoreCorpus

    home = Path(home or find_home())
    pack = DomainPack(home / "domains" / "classics", extra_lexicons=("lexicon-supplement", "lexicon-harvested"))
    norm = pack.variants.normalize_text
    db = store if isinstance(store, CorpusStore) else CorpusStore(store, readonly=True)
    corpus = StoreCorpus(db, norm, exclude_books=EXCLUDED)
    herbs: dict[str, set[str]] = defaultdict(set)  # normalised surface -> herb term ids
    headwords: set[str] = set()
    for e in pack.lexicon.by_category("herb"):
        headwords.add(norm(e.term))
        for s in e.surfaces():
            herbs[norm(s)].add(e.term_id)
    herbs = dict(herbs)
    bencao = {b for b, book in corpus.books.items() if book.category == "本草"}

    found: dict[tuple[str, str], list[tuple[float, str, str]]] = defaultdict(list)  # (head, alias) -> (year, pid, kind)
    for p in corpus.iter_passages(book_ids=[b for b in corpus.books if not _no_witness(b)]):
        text, year = norm(p.text), corpus.year(p) or 9999.0
        entry = _entry_drug(p.locator.section, norm, herbs) if p.book_id in bencao else None
        lead = next((text[:k] for k in (4, 3, 2) if text[:k] in herbs), None)  # 药性歌括: 商陆苦寒…（一名章柳。）
        pairs = set(_pairs(text, entry or lead, herbs.__contains__))
        if entry:
            pairs |= {(entry, y, "entry") for y in _ENTRY_ALIAS.findall(text[:400])}
        for x, y, kind in sorted(pairs):
            if kind != "entry":
                if (y in headwords and x not in headwords) or (y in herbs and x not in herbs):
                    x, y = y, x
                if x not in herbs:
                    continue
            if x != y and _name_ok(x) and _name_ok(y) and y not in FALSE_FRIENDS:
                found[(x, y)].append((year, p.id, kind))
    counts: dict[str, int] = {}

    def n_of(s: str) -> int:
        if s not in counts:
            counts[s] = corpus.count(s)
        return counts[s]

    out: dict[str, list[dict[str, Any]]] = {t: [] for t in TYPES}
    by_head: dict[str, dict[str, tuple[str, list[str]]]] = defaultdict(dict)
    by_alias: dict[str, set[str]] = defaultdict(set)  # alias -> the heads equated with it
    for (h, a), wits in sorted(found.items()):
        wits.sort()
        kind = min((k for _, _, k in wits), key=POOLS["alias"].index)
        ids = list(dict.fromkeys(pid for _, pid, _ in wits))[:3]
        for x, y in ((h, a), (a, h)):
            if x == h or a in herbs:
                out["alias"].append({"asked": y, "head": x, "pool": kind, "witnesses": ids})
            by_head[x][y] = (kind, ids)
        by_alias[a].add(h)
    for h, names in sorted(by_head.items()):
        kind = min((k for k, _ in names.values()), key=POOLS["head"].index)
        out["head"].append({"asked": h, "pool": kind, "names": sorted(names),
                            "witnesses": {a: ids for a, (_, ids) in sorted(names.items())}})

    # ambiguous
    rows = db.db.execute("SELECT id, book_id, text FROM passages WHERE book_id = ?", (EXCLUDED[0],)).fetchall()
    bielu: dict[str, set[str]] = defaultdict(set)
    for e in read_bielu_store([{"id": i, "book_id": b, "text": t} for i, b, t in rows], normalize=norm):
        for tok in e.aliases:
            if e.head:
                bielu[tok.name].add(e.head)
    for s in sorted(set(herbs) | set(bielu) | set(by_alias)):
        lex = sorted(t.split(":", 1)[1] for t in herbs.get(s, ()))
        mined = sorted(h for h in by_alias.get(s, ()) if h in herbs)
        apart = any(not herbs[x] & herbs[y] for i, x in enumerate(mined) for y in mined[i + 1:])
        kind = "lexicon" if len(lex) >= 2 else "bielu" if len(bielu.get(s, ())) >= 2 else "store" if apart else None
        if kind and len(s) >= 2:
            out["ambiguous"].append({"asked": s, "pool": kind, "lexicon": lex, "bielu": sorted(bielu.get(s, ())),
                                     "store": mined})

    # period
    taboo = load_yaml(home / "domains" / "classics" / "taboo.yaml") or {}
    renames: dict[tuple[str, str], list[str]] = defaultdict(list)
    for rule in taboo.get("rules") or []:
        for orig, sub in rule.get("pairs") or []:
            o, s = norm(orig), norm(sub)
            if o in herbs or s in herbs:
                renames[(s, o)].append(f"{rule['id']}:{rule.get('from')}")
                renames[(o, s)].append(f"{rule['id']}:{rule.get('from')}")
    out["period"] = [{"asked": a, "pool": "taboo", "partner": b, "rules": src}
                     for (a, b), src in sorted(renames.items())]
    curated_file = home / "domains" / "classics" / "aliases" / "curated.yaml"
    curated = (load_yaml(curated_file) or {}) if curated_file.exists() else {}
    for row in curated.get("pairs") or []:
        if row.get("valid"):
            out["period"].append({"asked": norm(row["s"]), "pool": "curated", "partner": norm(row["head"]),
                                  "valid": row["valid"]})
    for row in curated.get("first_use") or []:
        out["period"].append({"asked": norm(row["s"]), "pool": "curated", "year": row.get("year")})
    for a, h in SPEC_CURATED:
        out["period"] += [{"asked": x, "pool": "curated", "partner": y, "spec": True}
                          for x, y in ((a, h), (h, a)) if x]
    first: dict[str, float | None] = {}

    def first_year(s: str) -> float | None:
        """The year of the earliest passage writing ``s`` outside the excluded books."""
        if s not in first:
            first[s] = None
            ids = [i for i in corpus.contains(s, verify=False) if not _no_witness(i.split(".", 1)[0])]
            for i in range(0, len(ids), 20):
                hit = [p for p in corpus.passages_by_id(ids[i: i + 20]) if s in norm(p.text)]
                if hit:
                    first[s] = min(corpus.year(p) or 9999.0 for p in hit)
                    break
        return first[s]

    for h, a in sorted(found):
        yh, ya = first_year(h), first_year(a)
        if yh is not None and ya is not None and abs(yh - ya) >= DATED_GAP:
            for x, y in ((h, a), (a, h)):
                out["period"].append({"asked": x, "pool": "dated", "partner": y,
                                      "first": {x: round(first[x] or 0), y: round(first[y] or 0)}})

    # trap
    out["trap"] = [{"asked": s, "pool": "false-friend"} for s in FALSE_FRIENDS]
    for a in sorted({a for _, a in found if len(a) == 2} - set(FALSE_FRIENDS)):
        ids = corpus.contains(a, verify=False)
        share = sum(1 for i in ids if i.split(".", 1)[0] in bencao) / max(1, len(ids))
        if len(ids) >= ORDINARY[0] and share <= ORDINARY[1]:
            out["trap"].append({"asked": a, "pool": "ordinary", "heads": sorted({h for h, x in found if x == a}),
                                "bencao_share": round(share, 2)})

    # substring: a drug name inside a longer name whose drug is another (lexicon entries; an equated name is its head's)
    drugs: dict[str, set[str]] = {s: set(t) for s, t in herbs.items()}
    for h, a in found:
        drugs.setdefault(a, set()).update(herbs.get(h, ()))
    longer: dict[str, set[str]] = defaultdict(set)
    for x, dx in drugs.items():
        for size in range(2, len(x)):
            for i in range(len(x) - size + 1):
                s = x[i: i + size]
                if dx and drugs.get(s) and not dx & drugs[s]:
                    longer[s].add(x)
    out["substring"] = [{"asked": s, "pool": "substring", "false_friends": sorted(v)[:12]}
                        for s, v in sorted(longer.items())]
    for t in TYPES:
        for cand in out[t]:
            cand["n"] = n_of(cand["asked"])
            cand["band"] = band(cand["n"])
    return {"store": {"label": db.meta("label"), "normalizer": db.meta("normalizer"), "passages": len(corpus)},
            "excluded_books": list(EXCLUDED), "pools": out}


def propose(store: Any, home: str | Path | None = None, *, out: str | Path | None = None, seed: int = SEED,
            per_band: int | None = None, everything: bool = False) -> dict[str, Any]:
    """The pools of a store, stratified by the asked form's band (jc_c030 excluded; unattested candidates dropped) and
    drawn with the seed, up to ``per_band`` per band (default: the type's quota), or every candidate with
    ``everything``.  Writes the draw to ``out`` (default ``<data>/aliases/gold-candidates.yaml``) and returns it."""
    from ..config import data_dir, find_home

    home = Path(home or find_home())
    mined = pools(store, home)
    rng = random.Random(seed)
    drawn: dict[str, list[dict[str, Any]]] = {}
    sizes: dict[str, dict[str, int]] = {}
    for t in TYPES:
        strata: dict[str, list[dict[str, Any]]] = {b: [c for c in mined["pools"][t] if c["n"] and c["band"] == b]
                                                   for b in BANDS}
        sizes[t] = {b: len(v) for b, v in strata.items()}
        k = per_band or QUOTAS[t]
        drawn[t] = [c for b in BANDS
                    for c in (strata[b] if everything else rng.sample(strata[b], min(k, len(strata[b]))))]
    result = {"version": 1, "seed": seed, "store": mined["store"], "excluded_books": mined["excluded_books"],
              "pools": sizes, "candidates": drawn}
    target = Path(out) if out else data_dir(home) / "aliases" / "gold-candidates.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(result, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m taochronos.evals.aliases_gold")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("propose", help="draw candidate pools from a store into <data>/aliases/gold-candidates.yaml")
    ck = sub.add_parser("check", help="validate evals/gold/aliases.yaml (with --db: witnesses and pools too)")
    for p in (pr, ck):
        p.add_argument("--db", help="the store (default <data>/corpus/tcm.sqlite)")
        p.add_argument("--data", help="the data directory (default .taochronos)")
    pr.add_argument("--seed", type=int, default=SEED)
    pr.add_argument("--all", action="store_true", help="write every candidate, not a draw")
    pr.add_argument("-o", "--out")
    args = ap.parse_args(argv)
    from ..config import data_dir, find_home

    data = Path(args.data) if args.data else data_dir(find_home())
    if args.cmd == "check":
        gold, corpus, mined = load_gold(), None, None
        if args.db:
            from ..plugins.classics.domain import DomainPack
            from ..plugins.classics.store import CorpusStore, StoreCorpus

            db = CorpusStore(args.db, readonly=True)
            corpus = StoreCorpus(db, DomainPack(find_home() / "domains" / "classics").variants.normalize_text)
            mined = pools(db)["pools"]
        errs = validate(gold, corpus=corpus, pools=mined)
        print("\n".join(errs) or "ok", summary(gold))
        return 1 if errs else 0
    out = Path(args.out) if args.out else data / "aliases" / "gold-candidates.yaml"
    res = propose(Path(args.db) if args.db else data / "corpus" / "tcm.sqlite", out=out, seed=args.seed,
                  everything=args.all)
    print(out, {t: len(v) for t, v in res["candidates"].items()}, res["pools"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
