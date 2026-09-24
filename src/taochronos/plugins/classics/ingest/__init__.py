"""Ingestion pipeline: catalogs + source connectors → the corpus store.

Sources are fetched into the data directory (never committed): ``taochronos corpus fetch <source>``.
``taochronos corpus ingest <source>`` parses them with the matching connector, dates every passage
according to the catalog (``corpus/catalog/*.yaml``), records provenance and licence per book, and builds
the full-text index.  Re-ingesting a book replaces it (idempotent).
"""

from __future__ import annotations

import math
import re
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


def load_external_works(path: str | Path) -> list[dict[str, Any]]:
    """``corpus/catalog/external-works.yaml``: works cited in the corpus but not in it (lost, or extant elsewhere)."""
    p = Path(path)
    return list((yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("works") or []) if p.exists() else []


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





# ====================================================================== 笈成 (JiCheng)
JC_CATEGORY = {"內經、難經": "医经", "傷寒": "伤寒", "金匱": "杂病", "本草": "本草", "炮製": "本草", "方劑": "方书", "溫病": "温病",
               "雜病": "内科", "婦產": "妇科", "兒科": "儿科", "外科": "外科", "傷科": "伤科", "針灸": "针灸", "眼科": "眼科",
               "五官科": "五官", "診法": "诊法", "醫案": "医案", "綜合": "综合", "叢書": "综合", "短篇": "歌赋", "資料庫": "现代",
               "其他": "非医籍"}
JC_SOURCE = {
    "id": "jicheng",
    "name": "笈成（JiCheng）中医古籍整理本 · 笈成檢閱系統 v1.4.8 资料",
    "url": "https://jicheng.tw/",
    "license": "使用者提供之笈成整理本：古籍原文属公有领域，校点与整理成果归笈成整理者；现代著作可能仍受著作权保护，仅供本地研究使用",
    "transcription": "笈成志愿者录入、校对并加新式标点（各书“品质”见 [book] 信息）；未经本项目逐字核对",
}
FRONT_MATTER_UPPER = 1911  # paratext of undetermined date is placed at the end of the imperial era (never earlier)
UNDATED_NOTE = "成书年代无从考定，按清代（1644—1911）保守计"


def _title_key(normalize: Callable[[str], str], title: str, last_part: bool = False) -> str:
    """Matching key of a title; ``last_part`` keeps only what follows the last · (證治準繩·類方 → 类方)."""
    t = normalize(title or "").replace("‧", "·").replace("・", "·")
    if last_part:
        t = t.split("·")[-1]
    t = re.sub(r"[（(][^）)]*[）)]", "", t)
    return re.sub(r"[\s　《》〈〉]", "", t)


# titles of books that carry a later layer over an earlier text (增訂, 評, 注 …): dated by their latest preface
LAYERED_TITLE = re.compile(r"(增订|增补|重订|评|批|注|笺|疏|校|参订|合刻|合刊|续|衍义|发挥|补遗|详解|浅注|新编|重编|考释|选注|集注|辑注|类编|类纂|节注|串解|释义)")


def _date_from_prefaces(rng: tuple[int, int] | None, how: str, sigs: list[tuple[int, bool, str]],
                        layered: bool) -> tuple[list[int] | None, str, str | None]:
    """Date a book from its metadata and the dated signature lines of its prefaces.

    Coarse metadata (a dynasty, a span over 60 years) or none: the dated prefaces inside that span decide —
    the author's own if there is one, otherwise the earliest (the latest for a book whose title marks a later
    layer); a preface dated after the span belongs to a reprint and is ignored.  Precise metadata stands,
    unless the author's own preface dates the book outside it (or narrows a span to one year)."""
    own = sorted(s for s in sigs if s[1] and s[0] <= 1949)
    if rng is not None and rng[1] - rng[0] <= 60:
        if own and (rng[0] != rng[1] or abs(own[0][0] - rng[0]) > 5):
            d = own[-1] if layered else own[0]
            if rng[0] <= d[0] <= rng[1] or abs(d[0] - rng[0]) > 5:
                return [d[0], d[0]], "preface:author", d[2]
        return [rng[0], rng[1]], how, None
    lo, hi = rng if rng is not None else (-300, 1949)
    pool = sorted(s for s in sigs if lo - 5 <= s[0] <= hi + 5)
    own = [s for s in pool if s[1]]
    if own:
        d = own[-1] if layered else own[0]
        return [d[0], d[0]], "preface:author", d[2]
    if pool:
        d = pool[-1] if layered else pool[0]
        return [d[0], d[0]], "preface", d[2]
    return ([rng[0], rng[1]], how, None) if rng is not None else (None, "undated", None)


def build_jicheng_catalog(root: Path, normalize: Callable[[str], str], chronology: Any, kanripo: dict[str, Any] | None,
                          overrides: dict[str, Any], dynasty_of: Callable[[float], str | None] | None = None) -> dict[str, Any]:
    """Catalogue every book of the collection: its own [book] metadata, curated overrides, Kanripo dates."""
    from .jicheng import preface_dates, read_book_block, read_filelist

    index: dict[str, dict[str, Any]] = {}
    for e in (kanripo or {}).get("books", []):
        for t in [e["title"], *e.get("aliases", [])]:
            index.setdefault(_title_key(normalize, t), e)
    books: list[dict[str, Any]] = []
    missing: list[str] = []
    conflicts: list[str] = []
    for le in read_filelist(root):
        ov = dict(overrides.get(le.code) or {})
        if ov.get("exclude"):
            continue
        path = root / "data" / le.path
        if not path.exists():
            missing.append(le.code)
            continue
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        meta = read_book_block(text[:6000])
        # a part of a collection keeps the collection's name (證治準繩·類方, 醫學經驗錄·醫案): the part's own name alone
        # (類方, 醫案) would be ambiguous as a title and as a work
        orig_title = re.sub(r"\s*[‧・]\s*", "·", (meta.get("書名") or le.name).strip()) or le.name
        part = orig_title.split("·")[-1]
        key = _title_key(normalize, orig_title)
        kr = index.get(key) or (index.get(_title_key(normalize, part)) if len(part) >= 3 and part != orig_title else None)
        authors = ov.get("authors") or [p for p in (_person(normalize(x)) for x in re.split(r"[、，,；;。]", meta.get("作者") or "")) if p]
        dating, dating_note = "curated", None
        comp = ov.get("composition")
        if comp is None and kr is not None:  # the same work in the curated Kanripo catalog
            comp, dating = list(kr["composition"]), f"kanripo:{kr['kr']}"
        elif comp is None:
            rng, how = chronology.parse(meta.get("年份"), meta.get("朝代"), meta.get("年代"), meta.get("時間"))
            dyn_rng, dyn_how = chronology.parse(meta.get("朝代"))
            sigs = preface_dates(text, chronology, authors)
            if rng is not None and dyn_rng is not None and max(rng[0], dyn_rng[0]) < 1840 \
                    and (rng[1] < dyn_rng[0] - 10 or rng[0] > dyn_rng[1] + 10):
                # 年份 contradicts 朝代 (南宋 with the years of 劉宋, 清 for a Ming author …): the range a dated
                # preface falls in wins; without one, the later range (never date a book too early)
                conflicts.append(f"{le.code} 年份={meta.get('年份')} 朝代={meta.get('朝代')}")
                backed = [r for r in ((rng, how), (dyn_rng, dyn_how)) if any(r[0][0] - 5 <= y <= r[0][1] + 5 for y, _, _ in sigs)]
                rng, how = max(backed or [(rng, how), (dyn_rng, dyn_how)], key=lambda r: r[0][1])
            comp, dating, dating_note = _date_from_prefaces(rng, how, sigs, bool(LAYERED_TITLE.search(key)))
        dyn_meta = (meta.get("朝代") or "").split("‧")[0].split("·")[0].strip()
        modern = bool(ov["modern"]) if "modern" in ov else ((comp is not None and comp[0] >= 1912) or any(
            x in (meta.get("朝代") or "") for x in ("民國", "民国", "現代", "现代", "近代")))
        if comp is None:
            comp, dating = ([1912, 2010] if modern else [1644, 1911]), "undated"
        elif modern and "composition" not in ov and comp[0] < 1912:  # a modern work carrying an old preface
            comp, dating, dating_note = [1912, 2010], "modern", None
        mid = (comp[0] + comp[1]) / 2
        dynasty = ov.get("dynasty") or (normalize(dyn_meta) if dyn_meta and not re.search(r"\d|西元|公元", dyn_meta) else None) \
            or (dynasty_of(mid) if dynasty_of else "") or ""
        category = ov.get("category") or ("现代" if modern else JC_CATEGORY.get(le.category, le.category))
        quality = None
        if meta.get("品質"):
            qm = re.match(r"(\d+)%", meta["品質"])
            quality = int(qm.group(1)) / 100 if qm else None
        entry: dict[str, Any] = {
            "code": le.code, "id": f"jc_{le.code.lower()}", "file": le.path, "title": ov.get("title") or normalize(orig_title),
            "aliases": sorted({orig_title, le.name, *([part] if len(part) >= 4 else [])} - {ov.get("title") or normalize(orig_title)}),
            "authors": authors, "dynasty": dynasty,
            "composition": comp, "dating": dating, **({"dating_note": dating_note} if dating_note else {}),
            "category": category, "jicheng_category": le.category,
            "work": ov.get("work") or (kr.get("work") if kr else None) or f"jc:{key}",
            "attribution": ov.get("attribution", "traditional"), "modern": modern,
        }
        if kr is not None:
            entry["kanripo"] = kr["kr"]
        if quality is not None:
            entry["quality"] = quality
        edition = "；".join(x for x in (meta.get("版本"), meta.get("參本") or meta.get("參考紙本") or meta.get("參校紙本")) if x)
        if edition:
            entry["edition"] = edition
        notes = "；".join(x for x in (ov.get("notes_text"), le.remark, meta.get("備考")) if x)
        if notes:
            entry["notes_text"] = notes
        for k in ("z_layer", "s_layer", "markers", "mixed", "cites_work", "chapter_layers", "section_layers"):
            if k in ov:
                entry[k] = ov[k]
        books.append(entry)
    _date_from_witnesses(books)
    _narrow_by_author(books, (kanripo or {}).get("books", []), normalize)
    return {"source": JC_SOURCE, "books": books, "missing": missing, "metadata_conflicts": conflicts}


def _date_from_witnesses(books: list[dict[str, Any]]) -> None:
    """Transcriptions of one work (the "a" files, a second copy under another code) share the most precise
    date found for any of them."""
    by_work: dict[str, list[dict[str, Any]]] = {}
    for e in books:
        by_work.setdefault(e["work"], []).append(e)
    for group in by_work.values():
        dated = [e for e in group if not e.get("modern") and e["composition"][1] - e["composition"][0] <= 15
                 and not str(e["dating"]).startswith(("undated", "dynasty", "work"))]
        if not dated:
            continue
        best = min(dated, key=lambda e: (e["composition"][1] - e["composition"][0], e["code"]))
        for e in group:
            c = e["composition"]
            if e is best or e["dating"] == "curated" or e.get("modern") or c[1] - c[0] <= 15:
                continue
            e["composition"], e["dating"] = list(best["composition"]), f"work:{best['code']}"


GENERIC_PERSONS = {"佚名", "不详", "无名氏", "阙名", "未详", "失名", "不著撰人", "佚"}


def _person(author: str) -> str | None:
    """A person's name from an author string of the metadata: 吴谦等 → 吴谦, 武当山道医：祝华英 → 祝华英."""
    a = re.sub(r"[（(][^）)]*[）)]", "", author or "")
    a = re.split(r"[：:]", a)[-1].replace("旧题", "")
    a = re.sub(r"^(日本人|日本|日|朝鲜人|朝鲜)[‧·、，,\s]*", "", a.strip())
    a = re.sub(r"(等|著|撰|编著|编|辑|点校|校注|注|校|原著|重订|手订|述)+$", "", re.sub(r"[\s　]+", "", a))
    return None if len(a) < 2 or a in GENERIC_PERSONS else a


def _narrow_by_author(books: list[dict[str, Any]], kanripo: list[dict[str, Any]], normalize: Callable[[str], str]) -> None:
    """A book dated only to a dynasty (or a span over 60 years) whose author has well-dated works elsewhere in the
    catalogs is narrowed to those works' years ± 20, within its own span."""
    known: dict[str, list[int]] = {}
    for e in [*kanripo, *books]:
        c = e["composition"]
        if c[1] - c[0] > 15 or e.get("modern") or e.get("attribution", "traditional") != "traditional" \
                or str(e.get("dating", "")).startswith(("undated", "modern", "author")):
            continue
        for a in e.get("authors") or []:
            if (k := _person(normalize(a))):
                known.setdefault(k, []).extend(c)
    for e in books:
        c = e["composition"]
        if c[1] - c[0] <= 60 or e.get("modern") or e["dating"] == "curated" or e["dating"].startswith("kanripo"):
            continue
        for a in e.get("authors") or []:
            ys = known.get(_person(normalize(a)) or "")
            if not ys:
                continue
            lo, hi = max(c[0], min(ys) - 20), min(c[1], max(ys) + 20)
            if lo <= hi and hi - lo < c[1] - c[0]:
                e["composition"], e["dating"] = [lo, hi], f"author:{_person(normalize(a))}"
                break


def jicheng_spec(entry: dict[str, Any]) -> Any:
    from .jicheng import JichengSpec

    comp = _range(entry["composition"]) or (0, 0)

    def lay(raw: dict[str, Any] | None) -> LayerSpec | None:
        return _layer(raw) if raw else None

    markers = [(m["prefix"], LayerSpec(m["layer"], _range(m["year"]) or (0, 0), m.get("attribution", "")))
               for m in entry.get("markers") or []]
    return JichengSpec(
        book_id=entry["id"], code=entry["code"], composition=comp, dynasty=entry.get("dynasty", ""),
        edition_id=f"{entry['id']}@jicheng",
        z_layer=lay(entry.get("z_layer")), s_layer=lay(entry.get("s_layer")), markers=markers,
        mixed=lay(entry.get("mixed")), cites=_range(entry.get("cites_work")),
        chapter_layers=[(c["pattern"], _layer(c)) for c in entry.get("chapter_layers") or []],  # type: ignore[misc]
        section_layers=[(c["pattern"], _layer(c)) for c in entry.get("section_layers") or []],  # type: ignore[misc]
        front_matter=LayerSpec("卷首（序跋凡例等，年代未定，按下限计）", (max(comp[1], FRONT_MATTER_UPPER), max(comp[1], FRONT_MATTER_UPPER)), ""),
    )


def jicheng_book_record(entry: dict[str, Any], catalog: dict[str, Any], version: str | None = None) -> dict[str, Any]:
    src = catalog.get("source") or JC_SOURCE
    licence = src.get("license", "")
    if entry.get("modern"):
        licence += "（本书为现代著作）"
    layers = []
    for key in ("z_layer", "s_layer", "mixed"):
        if entry.get(key):
            layers.append({"kind": key, **entry[key]})
    for m in entry.get("markers") or []:
        layers.append({"kind": "marker", **m})
    for key in ("chapter_layers", "section_layers"):
        for c in entry.get(key) or []:
            layers.append({"kind": key, **c})
    basis = str(entry.get("dating") or "")
    how = {"curated": "编目人工考定", "western": "笈成书目所载公元年", "era": "笈成书目所载年号", "dynasty": "笈成书目所载朝代",
           "preface": "序跋落款", "preface:author": "作者自序落款", "modern": "现代著作", "undated": UNDATED_NOTE}.get(basis)
    if how is None and basis.startswith("kanripo:"):
        how = f"同书四库本（{basis.split(':', 1)[1]}）编目年代"
    elif how is None and basis.startswith("author:"):
        how = f"同作者（{basis.split(':', 1)[1]}）他书年代 ±20 年"
    elif how is None and basis.startswith("work:"):
        how = f"同一著作的另一录本（{basis.split(':', 1)[1]}）"
    dating_text = "断代依据：" + (how or basis) + (f"（{entry['dating_note']}）" if entry.get("dating_note") else "")
    return {
        "id": entry["id"], "title": entry["title"], "aliases": entry.get("aliases", []), "authors": entry.get("authors", []),
        "dynasty": entry.get("dynasty", ""), "category": entry.get("category", ""), "composition": entry["composition"],
        "author_life": None, "dating_basis": "composition", "attribution": entry.get("attribution", "traditional"),
        "school": entry.get("school"), "work": entry.get("work"),
        "editions": [{"id": f"{entry['id']}@jicheng", "name": "笈成整理本" + (f"（{entry['edition']}）" if entry.get("edition") else ""),
                      "year": None, "quality": float(entry.get("quality", 0.7))}],
        "source": {"origin": src.get("name", ""), "license": licence, "acquisition": f"user-supplied archive {version or ''}".strip(),
                   "url": src.get("url"), "transcription": src.get("transcription", ""), "verified": False},
        "notes": "；".join(x for x in (entry.get("notes_text"), dating_text) if x), "layers": layers, "source_id": "jicheng",
        "source_ref": entry["code"],
        "modern": bool(entry.get("modern")), "dating": entry.get("dating"),
    }


def ingest_jicheng(store: CorpusStore, catalog: dict[str, Any], root: Path, normalize: Callable[[str], str], fingerprint: str,
                   *, only: Iterable[str] | None = None, log: Log = print, dynasty_of: Callable[[float], str | None] | None = None,
                   version: str | None = None, chronology: Any = None, changed_only: bool = False) -> dict[str, Any]:
    from .jicheng import JichengParser, read_nclist

    import json

    nc = read_nclist(root / "config" / "nclist.txt")
    wanted = {x.lower() for x in only} if only else None
    report: dict[str, Any] = {"source": "jicheng", "books": {}, "missing": [], "unknown_tags": {}, "records_only": 0}
    stored = {bid: json.loads(data) for bid, data in store.db.execute("SELECT id, data FROM books WHERE source='jicheng'")}
    for entry in catalog["books"]:
        if wanted is not None and entry["code"].lower() not in wanted and entry["id"] not in wanted:
            continue
        path = root / "data" / entry["file"]
        if not path.exists():
            report["missing"].append(entry["code"])
            continue
        record = jicheng_book_record(entry, catalog, version)
        old = stored.get(entry["id"])
        if changed_only and old is not None and all(old.get(k) == record.get(k) for k in ("composition", "layers", "dynasty")) \
                and old.get("source_ref") == entry["code"]:
            store.put_book(record, source="jicheng")  # dates and layers unchanged: the passages stand
            report["records_only"] += 1
            continue
        parser = JichengParser(jicheng_spec(entry), nc, dynasty_of, chronology)
        rows = parser.parse(path)
        store.delete_book(entry["id"], normalize)
        store.put_book(record, source="jicheng")
        store.add_passages(rows, normalize)
        store.commit()
        chars = sum(len(r["text"]) for r in rows)
        report["books"][entry["id"]] = {"code": entry["code"], "passages": len(rows), "characters": chars,
                                        "layers": parser.report["layers"], "gaiji": parser.report["gaiji"],
                                        "dropped_collation": parser.report["dropped_collation"], "boxes": parser.report["boxes"],
                                        "signed_prefaces": parser.report["signed_prefaces"]}
        if parser.report["unknown_tags"]:
            report["unknown_tags"][entry["code"]] = parser.report["unknown_tags"]
        log(f"  {entry['code']:7s} {entry['id']:12s} {len(rows):6d} passages {chars:9d} chars")
    store.set_meta("normalizer", fingerprint)
    store.commit()
    return report


def jicheng_variant_rows(groups: list[list[str]], normalize: Callable[[str], str], existing: set[str]) -> list[tuple[str, str, str]]:
    """Rare variant forms from the viewer's search table: a member outside the common character set maps to the
    group's common form, and only when that form is unambiguous (two different common characters are never merged)."""

    def common(ch: str) -> bool:
        try:
            ch.encode("gb2312")
            return True
        except UnicodeEncodeError:
            return False

    rows: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for g in groups:
        singles = [m for m in g if len(m) == 1]
        if len(singles) < 2:
            continue
        norms = {m: normalize(m) for m in singles}
        targets = {norms[m] for m in singles if common(norms[m])}
        if len(targets) != 1:
            continue
        target = next(iter(targets))
        for m in singles:
            if m in existing or m in seen or common(m) or norms[m] == target or ord(target) > 0xFFFF:
                continue
            rows.append((m, target, "jicheng:synonyms", " ".join(g)))
            seen.add(m)
    return rows  # type: ignore[return-value]


__all__ = ["BigramModel", "book_record", "book_spec", "build_jicheng_catalog", "git_head", "ingest_jicheng", "ingest_kanripo",
           "jicheng_book_record", "jicheng_spec", "jicheng_variant_rows", "load_catalog", "load_external_works"]
