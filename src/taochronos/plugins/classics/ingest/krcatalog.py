"""The Kanripo catalogue (github.com/kanripo/KR-Catalog, ``KR/KR3e.txt``, CC BY-SA 4.0).

An org-mode file with one entry per text of the 醫家類 (KR3e): its title, the Siku edition's volume and page
(``SOURCE``), extent, the responsible persons as printed (``_RESP``: （唐）王冰,（宋）林億) and, under 人物, each
person's dynasty, role (撰, 次注, 校正 …) and dates (``fl. 762``, ``1518 - 1593``, ``12th cent``); then the
editions (WYG = 文淵閣, SBCK = 四部叢刊 …) and appended parts.  :func:`read_kr_catalog` parses it;
:func:`cross_check` lists where the curated Kanripo catalog disagrees with it, for review.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

KR_CATALOG_URL = "https://github.com/kanripo/KR-Catalog"


def _props(lines: list[str], i: int) -> tuple[dict[str, str], int]:
    """The :PROPERTIES: drawer starting at line ``i`` (if any) and the line after it."""
    out: dict[str, str] = {}
    if i < len(lines) and lines[i].strip() == ":PROPERTIES:":
        i += 1
        while i < len(lines) and lines[i].strip() != ":END:":
            m = re.match(r"^\s*:([A-Z_]+):\s*(.*?)\s*$", lines[i])
            if m:
                out[m.group(1)] = m.group(2)
            i += 1
        i += 1
    return out, i


def parse_dates(s: str | None) -> dict[str, Any] | None:
    """``fl. 762`` / ``1518 - 1593`` / ``ca. 250 - ca. 330`` / ``d. 1078`` / ``12th cent`` → a range and its kind."""
    if not s:
        return None
    t = s.strip()
    m = re.match(r"^(\d{1,2})(st|nd|rd|th) cent", t)
    if m:
        c = int(m.group(1))
        return {"text": t, "kind": "century", "range": [(c - 1) * 100, c * 100 - 1]}
    nums = [int(x) for x in re.findall(r"-?\d{2,4}", t)]
    if not nums:
        return {"text": t, "kind": "unparsed"}
    if t.startswith("fl."):
        return {"text": t, "kind": "flourished", "range": [nums[0], nums[-1]]}
    if t.startswith("d."):
        return {"text": t, "kind": "death", "range": [nums[0] - 60, nums[0]]}
    if t.startswith("b."):
        return {"text": t, "kind": "birth", "range": [nums[0], nums[0] + 90]}
    if len(nums) >= 2:
        return {"text": t, "kind": "life", "range": [nums[0], nums[-1]], **({"approximate": True} if "ca." in t else {})}
    return {"text": t, "kind": "year", "range": [nums[0], nums[0]]}


def read_kr_catalog(path: str | Path) -> dict[str, dict[str, Any]]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    out: dict[str, dict[str, Any]] = {}
    cur: dict[str, Any] | None = None
    section = None
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^(\*+)\s+(.*?)\s*$", line)
        if not m:
            i += 1
            continue
        depth, head = len(m.group(1)), m.group(2)
        props, j = _props(lines, i + 1)
        if depth == 3:
            mm = re.match(r"^(KR\w+)\s+(.*)$", head)
            if mm:
                title, *rest = mm.group(2).split("-")
                cur = {"title": title.strip(), "heading": mm.group(2)}
                for key, name in (("SOURCE", "siku"), ("EXTENT", "extent"), ("BOOK", "book"), ("_RESP", "responsibility"),
                                  ("EDITION", "edition"), ("DATE", "date")):
                    if props.get(key):
                        cur[name] = props[key]
                cur["persons"], cur["editions"], cur["parts"] = [], [], []
                out[mm.group(1)] = cur
            section = None
        elif depth == 4 and cur is not None:
            section = head
            if head not in ("人物", "版本"):
                part = {"title": head}
                if props.get("EXTENT", "").strip() not in ("", "卷"):
                    part["extent"] = props["EXTENT"]
                cur["parts"].append(part)
        elif depth == 5 and cur is not None:
            if section == "人物":
                person = {"name": head}
                if props.get("DYNASTY"):
                    person["dynasty"] = props["DYNASTY"]
                if props.get("FUNCTION"):
                    person["role"] = props["FUNCTION"]
                dates = parse_dates(props.get("DATES"))
                if dates:
                    person["dates"] = dates
                cur["persons"].append(person)
            elif section == "版本":
                cur["editions"].append(head)
        i = j if j > i + 1 else i + 1
    for entry in out.values():
        for k in ("parts", "editions"):
            if not entry[k]:
                del entry[k]
    return out


def _clean(name: str) -> str:
    return re.sub(r"[（(][^）)]*[）)]|\s|^旧题|^舊題|等$|續$|续$", "", name)


def cross_check(texts: dict[str, dict[str, Any]], kanripo: dict[str, Any],
                normalize: Callable[[str], str] = lambda s: s) -> list[dict[str, Any]]:
    """Curated entries none of whose authors the catalogue names, or whose date lies well outside the dates the
    catalogue gives for that author (for review; nothing is changed).  Pseudepigrapha (旧题 …) are left alone."""
    out: list[dict[str, Any]] = []
    for b in kanripo.get("books", []):
        t = texts.get(b["kr"])
        if not t:
            continue
        persons = {normalize(_clean(p["name"])): p for p in t.get("persons", [])}
        authors = [normalize(_clean(a)) for a in b.get("authors", []) if not re.match(r"^(佚名|阙名|闕名|旧题|舊題)", a)]
        issue: dict[str, Any] = {}
        matched = [persons[n] for a in authors for n in persons if a and (a == n or a in n or n in a)]
        if authors and persons and not matched:
            issue["authors"] = {"curated": b.get("authors"), "kr_catalog": sorted(p["name"] for p in persons.values())}
        comp = b.get("composition")
        pseud = b.get("attribution") == "pseudepigraphic" or any("旧题" in a or "舊題" in a for a in b.get("authors", []))
        spans = [p["dates"] for p in matched if p.get("dates", {}).get("range")]
        if spans and comp and not pseud and all(comp[1] < d["range"][0] - 20 or comp[0] > d["range"][1] + 20 for d in spans):
            issue["dates"] = {"curated": comp, "kr_catalog": sorted({f"{p['name']} {p['dates']['text']}" for p in matched if p.get("dates")})}
        if issue:
            out.append({"kr": b["kr"], "book": b["id"], **issue})
    return out


def record_extras(entry: dict[str, Any] | None) -> dict[str, Any]:
    """What a Kanripo book record carries from the catalogue: responsibility (persons, roles, dates) and the
    Siku location."""
    if not entry:
        return {}
    persons = [{k: v for k, v in p.items() if k != "dates"} | ({"dates": p["dates"]["text"]} if p.get("dates") else {})
               for p in entry.get("persons", [])]
    note = "、".join(f"{p.get('dynasty', '')}·{p['name']}{p.get('role', '')}" + (f"（{p['dates']}）" if p.get("dates") else "")
                    for p in persons)
    return {"responsibility": persons, "kr_catalog": {k: entry[k] for k in ("siku", "extent", "responsibility") if k in entry},
            "responsibility_note": f"责任者（Kanripo 目录）：{note}" if note else ""}


__all__ = ["KR_CATALOG_URL", "cross_check", "parse_dates", "read_kr_catalog", "record_extras"]
