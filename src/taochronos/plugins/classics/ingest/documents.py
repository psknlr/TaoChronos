"""The common path of the smaller collections into the corpus store.

A connector reads its source into :class:`Document` objects — a title, metadata as the source gives it, and a
sequence of headings and paragraphs.  :func:`build_document_catalog` then decides, for every document:

* its **date**, in the order used for the 笈成 collection: curated override → the same work's curated date
  (Kanripo, then 笈成) → the document's own metadata (years, reign eras, dynasties) and dated prefaces →
  sibling copies and the author's other works → undated (placed in the Qing, never earlier);
* its **admission** (:mod:`.policy`): contemporary works and modern editions are catalogued as excluded;
* whether it is a **copy** of a text already in the store (:mod:`.dedupe`): copies are catalogued with the book
  they duplicate and are not ingested.

:func:`document_rows` turns an admitted document into passages (headings → locator, 序/跋/凡例 → paratext dated
by its signature, prescriptions → ``formula`` passages).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator

from ..segment import split_long
from .dedupe import SketchIndex, classify, han, sample
from .jicheng import FRONT, MODERN_PARATEXT, TOC, _SELF, _SIGN, date_signed_prefaces
from .policy import Exclusions, screen

FULL_SPACE = "　"


@dataclass
class Block:
    kind: str  # heading | para | formula
    text: str
    level: int = 0
    page: str | None = None  # a physical page (McGill 10a) or a source subpage (Wikisource 卷一)


@dataclass
class Document:
    source: str
    code: str  # stable id within the source
    title: str
    blocks: list[Block]
    meta: dict[str, str] = field(default_factory=dict)  # 作者 / 朝代 / 年份 / notes as the source gives them
    authors: list[str] = field(default_factory=list)
    punctuation: str = "editorial"  # none: unpunctuated 白文
    url: str | None = None
    ref: str | None = None  # file, revision or record id
    chartype: str = "traditional"  # simplified: a converted copy
    edition: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def text(self) -> str:
        return "\n".join(b.text for b in self.blocks)


# credit lines of the websites the texts passed through (中医瑰宝苑, 大医精诚 …): never part of the text
_WEB_CREDIT = re.compile(r"(版權所有|版权所有|瑰寶苑|瑰宝苑|大醫精誠|大医精诚|中醫在線|中医在线|電子版|电子版|www\.|https?://|\.com|\.net|"
                         r"^\s*\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日\s*$|掃描|扫描|錄入|录入|校對|校对)")
_MODERN_SECTION = re.compile(r"^(概述|前言|出版說明|出版说明|內容提要|内容提要|整理說明|整理说明|校注說明|校注说明|點校說明|点校说明|編者按|编者按|"
                             r"電子版序|电子版序|作者簡介|作者简介)$")
MIN_CHARACTERS = 300  # shorter documents are hub pages, stubs or fragments


def strip_modern_paratext(blocks: list[Block]) -> list[Block]:
    """Drop website credit lines, and sections a modern editor wrote (概述, 前言, 整理说明 …) — as headings or as
    short title lines of a flat text — up to the next heading or short line."""
    out: list[Block] = []
    dropping: int | None = None
    for b in blocks:
        core = re.sub(r"\s+", "", b.text)
        if b.kind == "para" and ((len(core) <= 40 and _WEB_CREDIT.search(core)) or re.fullmatch(r"[-－—]*\d{1,4}[-－—]*", core)):
            continue  # credit lines, page numbers
        is_title = b.kind == "heading" or (b.kind == "para" and len(core) <= 8 and not re.search(r"[。，；：]", core))
        if is_title:
            if _MODERN_SECTION.match(core):
                dropping = b.level if b.kind == "heading" else 99
                continue
            if dropping is not None and (b.kind == "para" or b.level <= dropping):
                dropping = None
        if dropping is not None:
            continue
        out.append(b)
    return out


# characters that exist only in simplified or only in traditional script (a rough, fast chartype test)
_SIMPLIFIED = set("这们来说时发会对经过还没现问题实际样应该机进动产长门马东车书头义为国医药病证热气脏体学")
_TRADITIONAL = set("這們來說時發會對經過還沒現問題實際樣應該機進動產長門馬東車書頭義為國醫藥病證熱氣臟體學")


def chartype(text: str) -> str:
    s = sum(1 for ch in text if ch in _SIMPLIFIED)
    t = sum(1 for ch in text if ch in _TRADITIONAL)
    return "simplified" if s > t * 2 else "traditional"


def front_paragraph_texts(doc: Document) -> Iterator[str]:
    front, seen = False, False
    for b in doc.blocks:
        if b.kind == "heading":
            seen = True
            if b.level <= 3:
                front = bool(FRONT.search(b.text))
            continue
        if front or not seen:
            yield b.text


def document_preface_dates(doc: Document, chronology: Any, authors: Iterable[str] = ()) -> list[tuple[int, bool, str]]:
    n = chronology.normalize
    names = {n(a) for a in authors if len(a) >= 2}
    names |= {x[-2:] for x in names if len(x) >= 3}
    out: list[tuple[int, bool, str]] = []
    for para in front_paragraph_texts(doc):
        norm = n(para)
        for year, start, end in chronology.statements(para):
            if len(norm) - start > 90 or not _SIGN.search(norm[end:end + 16]):
                continue
            ctx = norm[max(0, start - 30): end + 40]
            out.append((year, bool(_SELF.search(ctx)) or any(a in ctx for a in names), para[max(0, start - 6): end + 24].strip()))
    return out


# the subject of a book the curated catalogs do not know, from its title (the 笈成 classes, first match wins)
_CATEGORY_RULES = [
    ("医案", r"医案|醫案|医话|醫話|治验|治驗|验案|驗案|医验|醫驗|寓意草"),
    ("伤寒", r"伤寒|傷寒|金匮|金匱|仲景|长沙|長沙"),
    ("温病", r"温病|溫病|温热|溫熱|瘟疫|温疫|溫疫|疫|暑|湿热|濕熱|时病|時病|霍乱|霍亂"),
    ("针灸", r"针|鍼|針|灸|经穴|經穴|明堂|推拿|按摩|经络|經絡"),
    ("本草", r"本草|药性|藥性|药品|藥品|药鉴|藥鑑|药赋|藥賦|食疗|食療|食物|饮膳|飲膳|草木|炮炙"),
    ("妇科", r"女科|妇|婦|产|產|胎|济阴|濟陰|达生|達生|广嗣|廣嗣|种子|種子"),
    ("儿科", r"幼|儿|兒|痘|麻疹|疹|痧|惊风|驚風|保婴|保嬰|育婴|育嬰|小儿|小兒"),
    ("外科", r"外科|疡|瘍|疮|瘡|痈|癰|疽|疔|梅毒|霉疮|黴瘡"),
    ("伤科", r"伤科|傷科|跌|骨|正体|正體|接骨|金疮|金瘡|理伤|理傷"),
    ("眼科", r"眼|目科|银海|銀海|审视瑶函|審視瑤函|目经|目經"),
    ("五官", r"喉|口齿|口齒|牙|耳|鼻|咽"),
    ("诊法", r"脉|脈|诊|診|舌|察色|望色"),
    ("医经", r"内经|內經|素问|素問|灵枢|靈樞|难经|難經|太素|甲乙"),
    ("方书", r"方|丹|丸|散"),
    ("歌赋", r"歌|赋|賦|诀|訣|三字经|三字經"),
]


def guess_category(title: str) -> str:
    for category, pattern in _CATEGORY_RULES:
        if re.search(pattern, title):
            return category
    return "综合"


def _title_index(normalize: Callable[[str], str], entries: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    from . import _title_key

    index: dict[str, dict[str, Any]] = {}
    for e in entries:
        for t in [e["title"], *e.get("aliases", [])]:
            index.setdefault(_title_key(normalize, t), e)
    return index


def _priority(doc: Document) -> tuple:
    """Order in which a source's documents are judged, so that of two copies the better one is kept: traditional
    before simplified, punctuated before bare text, the complete before the partial."""
    return (doc.chartype == "simplified", doc.punctuation == "none", -len(doc.text()), doc.code)


def build_document_catalog(docs: Iterable[Document], source: dict[str, Any], *, normalize: Callable[[str], str], chronology: Any,
                           kanripo: dict[str, Any] | None, jicheng: dict[str, Any] | None, overrides: dict[str, Any],
                           exclusions: Exclusions, sketch: SketchIndex | None, dynasty_of: Callable[[float], str | None] | None,
                           prefix: str, duplicate: float | None = 0.85, same_work: float | None = 0.4,
                           derived_copy: float | None = 0.5, derivative: bool = False,
                           book_work: dict[str, str] | None = None, ignore: Iterable[str] = (),
                           log: Callable[[str], None] = lambda m: None) -> dict[str, Any]:
    """Catalogue documents: date, admission and duplicate status (see the module docstring).

    ``duplicate``: containment in one stored book (or the union of the best matches ≥ 0.9) that makes a copy;
    ``None`` never marks copies (independent transcriptions of rare prints: the matches are only recorded).
    ``same_work``: the lower containment that suffices for a copy converted to simplified characters (which loses
    shingles) when the book it matches is the same work (by title) or the two contain each other; ``derived_copy``:
    the containment in any one stored book that makes a copy whatever its title (an extract, a part).  Both apply
    to every document of a ``derivative`` source (web copies), otherwise to simplified documents only.
    ``book_work``: the work of each stored book; ``ignore``: stored books not to compare with (this source's own,
    and those of sources that rank below it).  Admitted documents join the sketch as they are accepted, so copies
    within the source are caught too."""
    from . import (LAYERED_TITLE, UNDATED_NOTE, _date_from_prefaces, _date_from_witnesses, _narrow_by_author, _person,
                   _title_key)
    from .policy import MODERN_ERA

    kr_index = _title_index(normalize, (kanripo or {}).get("books", []))
    jc_index = _title_index(normalize, (jicheng or {}).get("books", []))
    works = dict(book_work or {})
    skip = set(ignore)
    books: list[dict[str, Any]] = []
    for doc in sorted(docs, key=_priority):
        ov = dict(overrides.get(doc.code) or {})
        title = ov.get("title") or normalize(doc.title)
        key = _title_key(normalize, doc.title)
        kr, jc = kr_index.get(key), jc_index.get(key)
        authors = ov.get("authors") or [p for p in (_person(normalize(a)) for a in doc.authors) if p]
        text = doc.text()
        dating, dating_note = "curated", None
        comp = ov.get("composition")
        if comp is None and kr is not None:
            comp, dating = list(kr["composition"]), f"kanripo:{kr['kr']}"
        elif comp is None and jc is not None and not str(jc.get("dating", "")).startswith(("undated", "dynasty")):
            comp, dating = list(jc["composition"]), f"jicheng:{jc['code']}"
        elif comp is None:
            rng, how = chronology.parse(doc.meta.get("年份"), doc.meta.get("朝代"), doc.meta.get("年代"))
            comp, dating, dating_note = _date_from_prefaces(rng, how, document_preface_dates(doc, chronology, authors),
                                                            bool(LAYERED_TITLE.search(key)))
        dyn_meta = (doc.meta.get("朝代") or "").split("‧")[0].split("·")[0].strip()
        modern = (comp is not None and comp[0] >= 1912) or bool(re.search(r"(民國|民国|現代|现代|當代|当代|近代)", doc.meta.get("朝代") or ""))
        if comp is None:
            contemporary = bool(re.search(r"(現代|现代|當代|当代)", doc.meta.get("朝代") or ""))
            comp = [MODERN_ERA, 2010] if contemporary else ([1912, 1949] if modern else [1644, 1911])
            dating = "undated"
        mid = (comp[0] + comp[1]) / 2
        dynasty = ov.get("dynasty") or (normalize(dyn_meta) if dyn_meta and not re.search(r"\d|西元|公元", dyn_meta) else None) \
            or (dynasty_of(mid) if dynasty_of else "") or ""
        # admission: a reviewed decision, the same work already judged in the 笈成 catalog, then the screen
        curated, keep = exclusions.decision(doc.source, doc.code, key)
        if not curated and not keep and jc is not None:  # the 笈成 copy of the same work was reviewed already
            if jc.get("status") == "excluded":
                curated = jc.get("excluded_reason")
            else:
                keep = exclusions.decision("jicheng", str(jc.get("code")), key)[1]
        verdict = screen(doc.title, text, comp, curated=curated, keep=keep)
        work = ov.get("work") or (kr or {}).get("work") or (jc or {}).get("work") or f"{prefix}:{key}"
        entry: dict[str, Any] = {
            "code": doc.code, "id": f"{prefix}_{_slug(doc.code)}", "title": title,
            "aliases": sorted({doc.title} - {title}), "authors": authors, "dynasty": dynasty, "composition": comp,
            "dating": dating, **({"dating_note": dating_note} if dating_note else {}),
            "category": ov.get("category") or ("近代" if modern else (jc or {}).get("category") or (kr or {}).get("category")
                                               or guess_category(title)),
            "work": work, "attribution": ov.get("attribution", "traditional"), "modern": modern, "chartype": doc.chartype,
            "punctuation": doc.punctuation, "characters": len(text),
        }
        for k in ("url", "ref", "edition"):
            if getattr(doc, k):
                entry[k] = getattr(doc, k)
        if doc.meta.get("notes"):
            entry["notes_text"] = doc.meta["notes"]
        for k in ("mixed", "cites_work", "notes_text", "quality"):
            if k in ov:
                entry[k] = ov[k]
        status = "ingest"
        grams: set[int] = set()
        if len(han(text)) < MIN_CHARACTERS and not ov.get("force_ingest"):
            status = "skipped"
            entry["skipped_reason"] = f"篇幅过短（不足 {MIN_CHARACTERS} 字：目录页、残页或存目）"
        elif verdict.reason:
            status = "excluded"
            entry["excluded_reason"] = verdict.reason
            entry["screen"] = {k: v for k, v in verdict.evidence.items() if v and k != "curated"} or {"curated": True}
        elif sketch is not None:
            grams = sample(han(normalize(text)))
            kind, matches, union = classify(sketch, grams, duplicate=duplicate if duplicate is not None else 2.0,
                                            union=0.9 if duplicate is not None else 2.0, ignore=skip)
            if matches:
                entry["closest"] = [{"book": m.book_id.removeprefix(_RUN), "containment": m.containment, "reverse": m.reverse}
                                    for m in matches[:3]]
            twin = None
            if duplicate is not None and not ov.get("force_ingest"):
                if kind == "duplicate":
                    twin = matches[0]
                elif same_work is not None and (derivative or doc.chartype == "simplified"):
                    related = {x for x in ((kr or {}).get("id"), (jc or {}).get("id")) if x}
                    for m in matches:
                        if m.containment < same_work:
                            break
                        bid = m.book_id.removeprefix(_RUN)
                        if (derived_copy is not None and m.containment >= derived_copy) or works.get(m.book_id) == work \
                                or bid in related or m.reverse >= same_work:
                            twin = m
                            break
            if twin is not None:
                status = "duplicate"
                entry["duplicate_of"] = twin.book_id.removeprefix(_RUN)
        entry["status"] = status
        if status == "ingest" and grams and sketch is not None:  # later copies in this source are compared with it
            sketch.add(_RUN + entry["id"], grams)
            works[_RUN + entry["id"]] = work
        books.append(entry)
        log(f"  {doc.code[:28]:28s} {status:9s} {title[:24]}")
    if sketch is not None:
        for b in books:
            if b["status"] == "ingest":
                sketch.remove(_RUN + b["id"])
    books.sort(key=lambda b: b["code"])
    _date_from_witnesses([b for b in books if b["status"] == "ingest"])
    known = [*(kanripo or {}).get("books", []), *[b for b in (jicheng or {}).get("books", []) if b.get("status") != "excluded"]]
    _narrow_by_author([b for b in books if b["status"] == "ingest"], known, normalize)
    for b in books:
        if b["dating"] == "undated":
            b.setdefault("notes_text", UNDATED_NOTE)
    return {"source": source, "books": books}


_RUN = "@"  # sketch keys of documents admitted earlier in the same run


def _slug(code: str) -> str:
    s = re.sub(r"[^0-9A-Za-z]+", "_", code).strip("_").lower()
    if s and len(s) >= len(code) * 0.5:
        return s[:48]
    import hashlib

    return (s[:24] + "_" if s else "") + hashlib.sha1(code.encode("utf-8")).hexdigest()[:10]


def document_rows(doc: Document, entry: dict[str, Any], *, chronology: Any = None, dynasty_of: Any = None,
                  report: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Passages of an admitted document, dated by its catalog entry (paratext by its own signature)."""
    comp = entry["composition"]
    front_year = max(comp[1], 1911)
    mixed = entry.get("mixed")
    cites = entry.get("cites_work")
    book_id = entry["id"]
    edition_id = f"{book_id}@{doc.source}"
    rows: list[dict[str, Any]] = []
    heads: dict[int, str] = {}
    front = toc = False
    dropping: int | None = None
    seq = 0
    layers: dict[str, int] = {}

    def temporal(year_range: list[int], layer: str, citation: list[int] | None) -> dict[str, Any]:
        mid = (year_range[0] + year_range[1]) / 2
        dyn = entry.get("dynasty", "") if layer == "正文" else ((dynasty_of(mid) if dynasty_of else None) or entry.get("dynasty", ""))
        return {"dynasty": dyn, "t_author": None, "t_composition": list(year_range), "t_edition": None, "t_citation": citation}

    for b in doc.blocks:
        if b.kind == "heading":
            title = b.text.strip(FULL_SPACE + " ")
            if not title:
                continue
            if dropping is not None and b.level <= dropping:
                dropping = None
            if MODERN_PARATEXT.match(title):
                dropping = b.level
                continue
            if dropping is not None:
                continue
            for lvl in [k for k in heads if k >= b.level]:
                del heads[lvl]
            heads[b.level] = title
            front = any(FRONT.search(h) and len(h) <= 20 for lvl, h in heads.items() if lvl <= 3)
            toc = any(TOC.match(h) for h in heads.values())
            continue
        if dropping is not None:
            continue
        text = re.sub(r"\s*\n\s*", FULL_SPACE if b.kind == "formula" else "", b.text).strip(FULL_SPACE + " ")
        if not text:
            continue
        kind = "toc" if toc else ("preface" if front else ("formula" if b.kind == "formula" else "text"))
        if front:
            layer, years, citation = "卷首（序跋凡例等，年代未定，按下限计）", [front_year, front_year], None
        elif mixed:
            layer, years, citation = mixed["layer"], list(mixed["year"]), list(cites) if cites else list(comp)
        else:
            layer, years, citation = "正文", list(comp), None
        path = [heads[k] for k in sorted(heads)]
        volume = path[0] if len(path) > 2 else None
        rest = path[1:] if len(path) > 2 else path
        loc = {"volume": volume, "chapter": rest[0] if rest else None, "section": " · ".join(rest[1:]) or None,
               "precision": "exact"}
        if b.page:
            loc["page"] = b.page
        for s0, e0 in split_long(text):
            chunk = text[s0:e0]
            if not chunk.strip(FULL_SPACE + " "):
                continue
            t = temporal(years, layer, citation)
            rows.append({
                "id": f"{book_id}.{seq:05d}", "book_id": book_id, "edition_id": edition_id, "seq": seq, "kind": kind,
                "layer": layer, "year": (years[0] + years[1]) / 2, "y_start": years[0], "y_end": years[1], "locator": loc,
                "temporal": t, "text": chunk, "punctuation": doc.punctuation,
                "extra": {"layer": layer, **({"chartype": doc.chartype} if doc.chartype != "traditional" else {})},
            })
            layers[layer] = layers.get(layer, 0) + 1
            seq += 1
    signed = date_signed_prefaces(rows, chronology, dynasty_of, entry.get("dynasty", ""), layers) if chronology is not None else 0
    if report is not None:
        report.update({"passages": len(rows), "signed_prefaces": signed, "layers": {k: v for k, v in layers.items() if v}})
    return rows


def document_book_record(entry: dict[str, Any], source: dict[str, Any], version: str | None = None) -> dict[str, Any]:
    from . import UNDATED_NOTE

    licence = source.get("license", "")
    basis = str(entry.get("dating") or "")
    how = {"curated": "编目人工考定", "western": "书目所载公元年", "era": "书目所载年号", "dynasty": "书目所载朝代",
           "preface": "序跋落款", "preface:author": "作者自序落款", "undated": UNDATED_NOTE}.get(basis)
    if how is None and ":" in basis:
        kind, ref = basis.split(":", 1)
        how = {"kanripo": f"同书四库本（{ref}）编目年代", "jicheng": f"同书笈成本（{ref}）编目年代",
               "author": f"同作者（{ref}）他书年代 ±20 年", "work": f"同一著作的另一录本（{ref}）"}.get(kind, basis)
    notes = "；".join(x for x in (entry.get("notes_text"), "断代依据：" + (how or basis)
                                  + (f"（{entry['dating_note']}）" if entry.get("dating_note") else "")) if x)
    quality = float(entry.get("quality", 0.5 if entry.get("chartype") == "simplified" else 0.7))
    layers = [{"kind": "mixed", **entry["mixed"]}] if entry.get("mixed") else []
    return {
        "id": entry["id"], "title": entry["title"], "aliases": entry.get("aliases", []), "authors": entry.get("authors", []),
        "dynasty": entry.get("dynasty", ""), "category": entry.get("category", ""), "composition": entry["composition"],
        "author_life": None, "dating_basis": "composition", "attribution": entry.get("attribution", "traditional"),
        "school": None, "work": entry.get("work"),
        "editions": [{"id": f"{entry['id']}@{source['id']}", "name": source.get("edition_name", source.get("name", "")) +
                      (f"（{entry['edition']}）" if entry.get("edition") else ""), "year": None, "quality": quality}],
        "source": {"origin": source.get("name", ""), "license": licence, "acquisition": source.get("acquisition", "") + (f" {version}" if version else ""),
                   "url": entry.get("url") or source.get("url"), "transcription": source.get("transcription", ""), "verified": False},
        "notes": notes, "layers": layers, "source_id": source["id"], "source_ref": entry.get("ref") or entry["code"],
        "modern": bool(entry.get("modern")), "dating": entry.get("dating"), "chartype": entry.get("chartype"),
    }


def ingest_documents(store: Any, catalog: dict[str, Any], docs: Iterable[Document], normalize: Callable[[str], str],
                     fingerprint: str, *, chronology: Any = None, dynasty_of: Any = None, version: str | None = None,
                     only: Iterable[str] | None = None, log: Callable[[str], None] = print) -> dict[str, Any]:
    """Ingest the admitted documents of a catalog; excluded and duplicate ones are removed from the store."""
    source = catalog["source"]
    entries = {b["code"]: b for b in catalog["books"]}
    wanted = {x.lower() for x in only} if only else None
    report: dict[str, Any] = {"source": source["id"], "books": {}, "excluded": {}, "duplicates": {}, "skipped": {}}
    stored = {bid for (bid,) in store.db.execute("SELECT id FROM books WHERE source=?", (source["id"],))}
    for doc in docs:
        entry = entries.get(doc.code)
        if entry is None or (wanted is not None and doc.code.lower() not in wanted and entry["id"] not in wanted):
            continue
        if entry["status"] != "ingest":
            if entry["id"] in stored:
                store.delete_book(entry["id"], normalize)
                store.commit()
            bucket = {"excluded": report["excluded"], "duplicate": report["duplicates"]}.get(entry["status"], report["skipped"])
            bucket[doc.code] = entry.get("excluded_reason") or entry.get("duplicate_of") or entry.get("skipped_reason")
            continue
        info: dict[str, Any] = {}
        rows = document_rows(doc, entry, chronology=chronology, dynasty_of=dynasty_of, report=info)
        store.delete_book(entry["id"], normalize)
        store.put_book(document_book_record(entry, source, version), source=source["id"])
        store.add_passages(rows, normalize)
        store.commit()
        chars = sum(len(r["text"]) for r in rows)
        report["books"][entry["id"]] = {"code": doc.code, "passages": len(rows), "characters": chars, **info}
        log(f"  {doc.code[:28]:28s} {entry['id'][:24]:24s} {len(rows):6d} passages {chars:9d} chars")
    store.set_meta("normalizer", fingerprint)
    store.commit()
    return report


__all__ = ["Block", "Document", "build_document_catalog", "chartype", "document_book_record", "document_preface_dates",
           "document_rows", "guess_category", "ingest_documents", "strip_modern_paratext"]
