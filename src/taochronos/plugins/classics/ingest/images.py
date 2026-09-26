"""Image witnesses (影像见证): digitised copies of the medical classics in libraries, catalogued without their images.

A transcription in the store is one witness of a work; the prints and manuscripts scanned by libraries are others,
and the only ones that show the page itself.  This module harvests their *records* — title, author, date, print or
manuscript, holder, shelfmark, the IIIF manifest (the standard address from which any viewer loads the pages) and
the terms of use — and links each record to the works of the corpus by its title.  No image is downloaded: a record
tells a reader where the page of a witness can be seen, and a future image layer where to fetch it.

Sources, each through the interface its holder publishes:

* **NIJL 国書データベース** (``kokusho.nijl.ac.jp``): the holder lists of the medical collections — 研医会図書館,
  慶應義塾大学 富士川文庫, 京都大学 富士川文庫, 東京大学総合図書館 (medicine and materia medica classes, which hold the
  鶚軒文庫), 東京大学医学図書館, 九州大学医学図書館, 東北大学医学分館 — and, with ``enrich``, each record's IIIF manifest for
  its author and date.  NIJL's own bibliographic data is free to use; images follow each holder's licence.
* **Staatsbibliothek zu Berlin · Sammlung Unschuld**: the K10plus catalogue (SRU, shelfmarks ``Slg. Unschuld …``) with
  the digitised copies' manifests, joined with the acquisition data of the Hamburg provenance dataset (CC BY 4.0).
* **Library of Congress · Chinese Rare Books**: the collection's medical items (loc.gov JSON API).
* **早稲田大学 古典籍総合データベース**: the medical class (ヤ09), item by item.
* **NDL デジタルコレクション**: the works of the corpus looked up by title in NDL Search (pre-1912 digitised items).

Records are written as CSV (``corpus/catalog/images/<source>.csv``) and read back by the study layer.  Every request
is paced; responses are cached under ``<data>/sources/images``.
"""

from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import subprocess
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

Log = Callable[[str], None]
FIELDS = ["id", "source", "holder", "collection", "title", "title_alt", "authors", "date", "years", "kind", "shelfmark",
          "manifest", "page", "rights", "work", "book", "match", "notes"]
UA = "TaoChronos image-witness catalog (research; metadata only)"


@dataclass
class Record:
    id: str
    source: str
    holder: str
    title: str
    collection: str = ""
    title_alt: str = ""
    authors: str = ""
    date: str = ""
    years: str = ""  # "1682" or "1821-1850"
    kind: str = ""  # 刊 | 写 | ""
    shelfmark: str = ""
    manifest: str = ""
    page: str = ""
    rights: str = ""
    work: str = ""
    book: str = ""
    match: str = ""
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def row(self) -> dict[str, str]:
        return {k: str(getattr(self, k) or "") for k in FIELDS}


# ------------------------------------------------------------------ fetching, paced and cached
class Fetcher:
    def __init__(self, cache: Path, pause: float = 1.0, log: Log = print) -> None:
        self.cache = cache
        self.pause = pause
        self.log = log
        self._last = 0.0
        cache.mkdir(parents=True, exist_ok=True)

    def get(self, url: str, *, refresh: bool = False) -> str | None:
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()
        path = self.cache / key[:2] / key
        if path.exists() and not refresh:
            return path.read_text(encoding="utf-8")
        wait = self.pause - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        for attempt in range(3):
            p = subprocess.run(["curl", "-sS", "--fail", "-L", "-m", "120", "-A", UA, url], capture_output=True)
            self._last = time.time()
            if p.returncode == 0:
                text = p.stdout.decode("utf-8", "replace")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                return text
            time.sleep(2 ** (attempt + 1))
        self.log(f"  failed: {url}")
        return None


def _cells(row_html: str) -> list[str]:
    return [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S)]


FULLWIDTH = str.maketrans("０１２３４５６７８９", "0123456789")
# Japanese eras (元号) from 天正 to 昭和 → first year: the imprints of NIJL's records are dated 元禄９, 〔寛永〕, ［文政頃］
JP_ERAS = {"天正": 1573, "文禄": 1592, "慶長": 1596, "元和": 1615, "寛永": 1624, "正保": 1644, "慶安": 1648, "承応": 1652,
           "明暦": 1655, "万治": 1658, "寛文": 1661, "延宝": 1673, "天和": 1681, "貞享": 1684, "元禄": 1688, "宝永": 1704,
           "正徳": 1711, "享保": 1716, "元文": 1736, "寛保": 1741, "延享": 1744, "寛延": 1748, "宝暦": 1751, "明和": 1764,
           "安永": 1772, "天明": 1781, "寛政": 1789, "享和": 1801, "文化": 1804, "文政": 1818, "天保": 1830, "弘化": 1844,
           "嘉永": 1848, "安政": 1854, "万延": 1860, "文久": 1861, "元治": 1864, "慶応": 1865, "明治": 1868, "大正": 1912,
           "昭和": 1926}
_JP_END = dict(zip(JP_ERAS, [*list(JP_ERAS.values())[1:], 1989]))
_JP_FORMS = str.maketrans("寬應曆德寶萬祿", "寛応暦徳宝万禄")
_JP_ERA = re.compile("(" + "|".join(JP_ERAS) + r")\s*(元|\d{1,2})?(?!\d)")
# the conventional spans of the period words a catalogue gives when it has no year (［江戸中期］)
JP_PERIODS = (("江戸初期", 1603, 1650), ("江戸前期", 1603, 1709), ("江戸中期", 1709, 1789), ("江戸後期", 1789, 1868),
              ("江戸末期", 1830, 1868), ("江戸時代", 1603, 1868), ("明治前期", 1868, 1887), ("明治", 1868, 1912))


def _span(ys: list[int]) -> str:
    return "" if not ys else (str(ys[0]) if min(ys) == max(ys) else f"{min(ys)}-{max(ys)}")


def _years(text: str) -> str:
    """The years a date statement gives: western years (1682 · 1821-1850), else a Japanese era with its year
    (享和１ → 1801; an era alone, 〔寛永〕, gives its span), else a period word (［江戸中期］ → 1709-1789).  Chinese
    reign eras (嘉慶5) are read by :func:`chinese_years` with the domain's era table."""
    t = (text or "").translate(FULLWIDTH)
    ys = [int(y) for y in re.findall(r"(?<!\d)(1[0-9]{3})(?!\d)", t)]
    if ys:
        return _span(ys)
    for era, num in _JP_ERA.findall(t.translate(_JP_FORMS)):
        ys += [JP_ERAS[era] + (1 if num == "元" else int(num)) - 1] if num else [JP_ERAS[era], _JP_END[era]]
    if ys:
        return _span(ys)
    return next((f"{a}-{b}" for word, a, b in JP_PERIODS if word in t), "")


def _cn_numeral(n: int) -> str:
    digits = "〇一二三四五六七八九"
    if n < 10:
        return digits[n]
    tens, ones = divmod(n, 10)
    return ("" if tens == 1 else digits[tens]) + "十" + (digits[ones] if ones else "")


_CN_FORMS = str.maketrans("暦煕豊", "曆熙豐")  # the Japanese forms of era characters the search normaliser leaves apart


def chinese_years(text: str, chronology: Any) -> str:
    """The year of a Chinese reign-era date as catalogues write it (嘉慶5 · 萬暦29 · ［康煕］), read with the domain's
    era table (:class:`~taochronos.plugins.classics.chronology.Chronology`)."""
    t = re.sub(r"[\[\]［］〔〕()（）]|頃", "", (text or "").translate(FULLWIDTH).translate(_CN_FORMS))
    t = re.sub(r"(?<!\d)(\d{1,2})(?!\d)", lambda m: _cn_numeral(int(m.group(1))) + "年", t)
    for part in reversed(t.split()):  # the date closes the imprint statement (publisher 〈place〉 date)
        r = chronology.era(part)
        if r:
            return _span([r[0], r[1]])
    return ""


def _rights(url: str) -> str:
    """A licence or rights statement URL as a short name; "" when it names none."""
    if m := re.search(r"creativecommons\.org/licenses/([a-z\-]+)/([0-9.]+)", url):
        return f"CC {m.group(1).upper()} {m.group(2)}"
    if m := re.search(r"creativecommons\.org/publicdomain/(zero|mark)/([0-9.]+)", url):
        return ("CC0 " if m.group(1) == "zero" else "Public Domain Mark ") + m.group(2)
    if m := re.search(r"rightsstatements\.org/(?:page|vocab)/([A-Za-z\-]+)/([0-9.]+)", url):
        return f"RightsStatements {m.group(1)} {m.group(2)}"
    if "rmda.kulib.kyoto-u.ac.jp/license_icon/free-license" in url:
        return "自由利用（京都大学貴重資料デジタルアーカイブ）"
    return ""


# ------------------------------------------------------------------ NIJL 国書データベース
NIJL = "https://kokusho.nijl.ac.jp/"
NIJL_HOLDERS = {  # key → (list page, holder, licence, filter on (call no., collection))
    "knik": ("list-kenikaito.html", "研医会図書館", "CC BY-NC 4.0", None),
    "keio-fujikawa": ("list-keio.html", "慶應義塾大学信濃町メディアセンター（富士川文庫）", "CC BY-NC-SA 4.0", None),
    "kyoto-fujikawa": ("list-kyot.html", "京都大学附属図書館（富士川文庫）",
                       "利用条件见 https://rmda.kulib.kyoto-u.ac.jp/reuse", lambda call, coll: coll == "富士川文庫"),
    "utokyo-medicine": ("list-toky.html", "東京大学総合図書館（医学・本草類，含鶚軒文庫）",
                        "利用条件见 https://www.lib.u-tokyo.ac.jp/ja/library/contents/archives-top/reuse",
                        lambda call, coll: bool(re.match(r"^[ＶV][０-９0-9]|^[ＴT]８１|^[ＴT]81", call))),
    "utokyo-medlib": ("list-toky-medical.html", "東京大学医学図書館", "RightsStatements NoC-CR 1.0", None),
    "kyushu-medlib": ("list-kyuudaiigaku.html", "九州大学附属図書館（医学図書館）", "Public Domain Mark 1.0", None),
    "tohoku-medlib": ("list-thklmed.html", "東北大学附属図書館医学分館", "RightsStatements NoC-CR 1.0", None),
}


def nijl_licences(fetch: Fetcher) -> dict[str, str]:
    """The terms of each holder list as the usage page links them (list page → licence, or the holder's terms page
    where it names no licence)."""
    page = fetch.get(NIJL + "page/usage.html") or ""
    out: dict[str, str] = {}
    for row in re.findall(r"<tr>(.*?)</tr>", page, re.S):
        links = re.findall(r'href="([^"]+)"', row)
        lists = [u for u in links if re.fullmatch(r"list-[^/\"]+\.html", u)]
        if not lists:
            continue
        named = next((r for r in map(_rights, links) if r), "")
        terms = next((u for u in links if u.startswith("http") and re.search(r"reuse|copyright|rights|terms|licen", u)), "")
        if named or terms:
            out.setdefault(lists[0], named or f"利用条件见 {terms}")
    return out


def harvest_nijl(fetch: Fetcher, key: str, *, enrich: bool = False, log: Log = print) -> list[Record]:
    list_page, holder, licence, keep = NIJL_HOLDERS[key]
    licence = nijl_licences(fetch).get(list_page) or licence
    page = fetch.get(NIJL + "page/" + list_page) or ""
    out: list[Record] = []
    for row in re.findall(r"<tr>(.*?)</tr>", page, re.S)[1:]:
        c = _cells(row)
        if len(c) < 5 or not c[0].isdigit():
            continue
        bid, title, kana = c[0], c[1], c[2]
        call = c[3] if len(c) >= 7 else ""
        image_call = c[4] if len(c) >= 7 else c[3]
        coll = c[-1] if len(c) >= 6 else ""
        if keep is not None and not keep(call, coll):
            continue
        rec = Record(id=f"nijl:{bid}", source=f"nijl:{key}", holder=holder, collection=coll, title=title, title_alt=kana,
                     shelfmark=call, manifest=f"{NIJL}biblio/{bid}/manifest", page=f"{NIJL}biblio/{bid}", rights=licence,
                     notes=f"画像請求記号 {image_call}" if image_call else "")
        out.append(rec)
    if enrich:
        for i, rec in enumerate(out):
            nijl_enrich(fetch, rec)
            if i and i % 200 == 0:
                log(f"  {key}: {i}/{len(out)} manifests")
    log(f"  {key}: {len(out)} records")
    return out


def _iiif_text(x: Any) -> str:
    """A IIIF label or value as text: Presentation 2 (a string, a list, ``{"@value"}``) or 3 (``{lang: [...]}``)."""
    if isinstance(x, str):
        return html.unescape(re.sub(r"<[^>]+>", "", x)).strip()
    if isinstance(x, list):
        return "；".join(filter(None, map(_iiif_text, x)))
    if isinstance(x, dict):
        return _iiif_text(x["@value"]) if "@value" in x else "；".join(filter(None, map(_iiif_text, x.values())))
    return "" if x is None else str(x)


def manifest_facts(data: dict[str, Any]) -> dict[str, str]:
    """Author, date and licence from a IIIF manifest's metadata (the labels NIJL and the holders use)."""
    meta = {_iiif_text(m.get("label")).lower(): _iiif_text(m.get("value")) for m in data.get("metadata") or [] if isinstance(m, dict)}
    author = next((meta[k] for k in ("author", "著者", "作者", "creator") if meta.get(k)), "")
    if not author and " / " in meta.get("タイトル / 著者", ""):  # 京都大学: 嬰児論 / (清)周士称撰
        author = meta["タイトル / 著者"].split(" / ", 1)[1]
    date = next((meta[k] for k in ("date", "出版年", "刊写年", "書写年", "出版年月日") if meta.get(k)), "")
    return {"authors": author.strip(), "date": date.strip(), "rights": _rights(_iiif_text(data.get("license") or data.get("rights")))}


def _json(text: str | None) -> dict[str, Any] | None:
    try:
        data = json.loads(text) if text else None
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


NIJL_API = NIJL + "api/biblioDetail/"
_DATED = re.compile(r"(?:" + "|".join(JP_ERAS) + r"|[\u3400-\u9fff]{2})[０-９0-9元]{1,2}年?(?:[序跋刊写書奥識]|頃)")


def nijl_enrich(fetch: Fetcher, rec: Record) -> None:
    """The record's bibliographic data from NIJL's API (the data its record pages show): authors, imprint (year and
    publishers), print or manuscript, notes, the IIIF manifest — the holder's own where NIJL links rather than holds
    the images (IIIF連携: 京都大学) —, the record's terms of use and its DOI (the credit NIJL asks for).  Without the
    API, the IIIF manifest is read instead."""
    bid = rec.id.split(":", 1)[-1]
    data = _json(fetch.get(NIJL_API + bid))
    if data is None or str(data.get("bid")) != bid:
        _enrich_from_manifest(fetch, rec)
        return
    authors = [a.strip() for a in data.get("author") or [] if isinstance(a, str) and a.strip()]
    rec.authors = "；".join(authors) or rec.authors
    notes = [n.strip() for n in data.get("chuki") or [] if isinstance(n, str) and n.strip()]
    imprint = [x.strip() for x in data.get("bpublish") or [] if isinstance(x, str) and x.strip()]
    dated = next((m.group(0) for n in notes for m in [_DATED.search(n.translate(_JP_FORMS))] if m), "")
    rec.date = " ".join(imprint) or dated or rec.date  # a colophon or preface date when no imprint is given (寛政９跋)
    rec.years = _years(rec.date) or rec.years
    kansha = str(data.get("kansha") or "")
    rec.kind = "写" if "写" in kansha else ("刊" if "刊" in kansha else rec.kind)
    rec.manifest = str(data.get("manifest") or rec.manifest)
    rec.page = str(data.get("doi") or rec.page)
    if notes:
        rec.notes = "；".join(filter(None, [rec.notes, *notes]))[:400]
    licence = str(data.get("licensetext1") or "").strip()
    if licence:
        rec.rights = licence if licence != "All-Rights-Reserved" else f"All-Rights-Reserved（{rec.rights}）"
    elif rec.manifest and not rec.manifest.startswith(NIJL):  # the holder's manifest states its terms
        rec.rights = manifest_facts(_json(fetch.get(rec.manifest)) or {})["rights"] or rec.rights


def _enrich_from_manifest(fetch: Fetcher, rec: Record) -> None:
    data = _json(fetch.get(rec.manifest))
    if data is None:
        return
    if data.get("@type") == "sc:Collection" or data.get("type") == "Collection":
        linked = next((m.get("@id") or m.get("id") for m in data.get("manifests") or data.get("items") or [] if isinstance(m, dict)), None)
        if not linked:
            return
        rec.manifest = str(linked)
        data = _json(fetch.get(rec.manifest)) or {}
    facts = manifest_facts(data)
    rec.authors = facts["authors"] or rec.authors
    rec.date = facts["date"] or rec.date
    rec.years = _years(rec.date) or rec.years
    rec.rights = facts["rights"] or rec.rights


# ------------------------------------------------------------------ Staatsbibliothek zu Berlin · Sammlung Unschuld
SRU = "https://sru.k10plus.de/opac-de-1"
PROVENANCE_CSV = ("https://www.fdr.uni-hamburg.de/record/19481/files/"
                  "2_Provenance_data_notebook_complete_chronological_v2.csv?download=1")


def _marc_fields(record: str) -> list[tuple[str, list[tuple[str, str]]]]:
    out = []
    for m in re.finditer(r'<(?:datafield|controlfield) tag="(\d+)"[^>]*>(.*?)</(?:datafield|controlfield)>', record, re.S):
        subs = [(a, html.unescape(b)) for a, b in re.findall(r'<subfield code="(.)">(.*?)</subfield>', m.group(2), re.S)]
        out.append((m.group(1), subs if subs else [("", html.unescape(m.group(2)))]))
    return out


def unschuld_provenance(fetch: Fetcher) -> dict[str, list[dict[str, str]]]:
    """Acquisition date and place of Unschuld's manuscripts by shelf number (Staack 2025, CC BY 4.0)."""
    text = fetch.get(PROVENANCE_CSV) or ""
    rows = list(csv.reader(text.splitlines()))
    out: dict[str, list[dict[str, str]]] = {}
    if not rows:
        return out
    head = [h.strip() for h in rows[0]]
    for r in rows[1:]:
        d = dict(zip(head, r))
        for num in re.findall(r"\b(8\d{3})\b", d.get("SBB shelf mark", "")):
            out.setdefault(num, []).append({"date": d.get("Date", ""), "city": d.get("City", ""), "what": d.get("Description", "")})
    return out


def harvest_unschuld(fetch: Fetcher, *, log: Log = print) -> list[Record]:
    prov = unschuld_provenance(fetch)
    out: list[Record] = []
    start, total = 1, None
    while total is None or start <= total:
        q = urllib.parse.urlencode({"version": "1.1", "operation": "searchRetrieve", "query": "pica.xsgb=Slg.Unschuld*",
                                    "maximumRecords": "100", "startRecord": str(start), "recordSchema": "marcxml"})
        text = fetch.get(f"{SRU}?{q}") or ""
        if total is None:
            m = re.search(r"<zs:numberOfRecords>(\d+)", text)
            total = int(m.group(1)) if m else 0
        records = re.findall(r'<record xmlns="http://www.loc.gov/MARC21/slim".*?</record>', text, re.S)
        if not records:
            break
        for r in records:
            f = _marc_fields(r)

            def first(tag: str, code: str = "a", pred: Callable[[list[tuple[str, str]]], bool] = lambda s: True) -> str:
                for t, subs in f:
                    if t == tag and pred(subs):
                        for c, v in subs:
                            if c == code:
                                return v.strip()
                return ""

            shelf = first("535", "3") or first("924", "g")
            if "Unschuld" not in shelf:
                continue
            ppn = first("001", "")
            title = first("880", "a", lambda s: any(v.startswith("245") for c, v in s if c == "6")) or first("245")
            alt = first("246")
            date = first("264", "c") or first("260", "c")
            digital = re.sub(r"^\(DE-627\)", "", first("776", "w"))
            subjects = [v for t, subs in f if t == "650" for c, v in subs if c == "a" and v != "Sammlung Unschuld"]
            num = re.search(r"\b(8\d{3})\b", shelf)
            acq = prov.get(num.group(1), []) if num else []
            notes = "；".join(filter(None, [
                ("主题：" + "、".join(subjects)) if subjects else "",
                ("入藏：" + "、".join(f"{a['date']} {a['city']}".strip() for a in acq)) if acq else "",
            ]))
            out.append(Record(
                id=f"sbb:{ppn}", source="sbb:unschuld", holder="Staatsbibliothek zu Berlin", collection="Sammlung Unschuld",
                title=title, title_alt=alt, date=date, years=_years(date), kind="写" if "抄本" in date or "manuscript" in r.lower() else "",
                shelfmark=shelf, manifest=f"https://content.staatsbibliothek-berlin.de/dc/PPN{digital}/manifest" if digital else "",
                page=f"https://digital.staatsbibliothek-berlin.de/werkansicht?PPN=PPN{digital}" if digital else
                f"https://stabikat.de/Record/{ppn}", rights="Public Domain Mark 1.0（数字化影像）" if digital else "未数字化",
                notes=notes))
        start += 100
    log(f"  sbb:unschuld: {len(out)} records ({sum(1 for r in out if r.manifest)} digitised)")
    return out


# ------------------------------------------------------------------ Library of Congress · Chinese Rare Books
LOC = "https://www.loc.gov/"
# most of the collection's medical books carry no subject heading: their Chinese title tells
_LOC_SUBJECT = re.compile(r"medicine|materia medica|pharmac|acupunct|yi jia|smallpox|diseases|surgery|pediatrics|obstetrics|"
                          r"gynecology|ophthalmology", re.I)
_MEDICAL_TITLE = re.compile(r"醫|医|藥|药|本草|傷寒|伤寒|病|鍼|針灸|灸|脈|痘|瘡|疹|素問|靈樞|難經|金匱|經絡|明堂|瘍|婦人|幼科|"
                            r"養生|攝生|衛生|良方|效方|方考|方論|神方|秘方|妙方|證治|湯液|丹溪|天花|外科|眼科|神彀|神穀|啟微")


def harvest_loc(fetch: Fetcher, *, log: Log = print) -> list[Record]:
    seen: dict[str, dict[str, Any]] = {}
    for q in ("medicine", "materia medica", "pharmacopoeia", "yi jia lei", "ben cao", "yi xue", "shang han", "zhen jiu", "yi fang"):
        page = 1
        while True:
            text = fetch.get(f"{LOC}collections/chinese-rare-books/?fo=json&c=100&sp={page}&q={urllib.parse.quote(q)}")
            if not text:
                break
            data = json.loads(text)
            for r in data.get("results", []):
                if r.get("id"):
                    seen.setdefault(r["id"], r)
            if not data.get("pagination", {}).get("next"):
                break
            page += 1
    out: list[Record] = []
    for url, r in sorted(seen.items()):
        item_id = url.rstrip("/").split("/")[-1]
        detail = fetch.get(f"{LOC}item/{item_id}/?fo=json&at=item")
        item = (json.loads(detail).get("item") or {}) if detail else {}
        subjects = " ".join(item.get("subject_headings") or r.get("subject") or [])
        others = item.get("other_title") or []
        title = next((t for t in others if re.search(r"[㐀-鿿]", t)), "") or r.get("title", "")
        if not (_LOC_SUBJECT.search(subjects) or _MEDICAL_TITLE.search(title)):
            continue
        rights = re.sub(r"\s+", " ", " ".join(html.unescape(re.sub(r"<[^>]+>", " ", x)) for x in (item.get("rights") or []))).strip()
        out.append(Record(
            id=f"loc:{item_id}", source="loc:chinese-rare-books", holder="Library of Congress, Asian Division",
            collection="Chinese Rare Books", title=re.sub(r"\s*[:/：]\s*$", "", title.split(" : ")[0]).strip(),
            title_alt=r.get("title", ""), authors="；".join(item.get("contributor_names") or []),
            date=str(item.get("date") or r.get("date") or ""), years=_years(str(item.get("date") or r.get("date") or "")),
            kind="刊" if re.search(r"ke|刻|print", " ".join(item.get("created_published") or []), re.I) else "",
            manifest=str(item.get("iiif_manifest_url") or f"{LOC}item/{item_id}/manifest.json"), page=f"{LOC}item/{item_id}/",
            rights=_loc_rights(rights),
            notes=subjects[:200]))
    log(f"  loc: {len(out)} records")
    return out


def _loc_rights(text: str) -> str:
    if "National Central Library" in text:
        return "仅供教育与研究在线阅览，不授予第三方再利用权（与台湾“国家图书馆”合作数字化）"
    if "unaware of any copyright" in text:
        return "馆方未知有版权或其他限制，可自由使用与再利用" + ("（World Digital Library 藏品）" if "World Digital Library" in text else "")
    first = re.split(r"(?<=[.。])\s", text, maxsplit=1)[0]
    return first[:160] or "见 loc.gov 权利说明"


# ------------------------------------------------------------------ 早稲田大学 古典籍総合データベース
WASEDA = "https://www.wul.waseda.ac.jp/kotenseki/"


def harvest_waseda(fetch: Fetcher, cls: str = "ya09", *, log: Log = print) -> list[Record]:
    index = fetch.get(f"{WASEDA}html/{cls}/index.html") or ""
    volumes: dict[str, list[str]] = {}  # an item digitised volume by volume is listed as ya09_00082_0001, _0009 …
    for page in re.findall(rf'href="\./({cls}_\d+(?:_\d+)?)/index\.html"', index):
        volumes.setdefault(re.match(rf"{cls}_\d+", page).group(0), []).append(page)
    out: list[Record] = []
    for it, pages in sorted(volumes.items()):
        text = fetch.get(f"{WASEDA}html/{cls}/{pages[0]}/index.html")
        if not text:
            continue
        body = html.unescape(re.sub(r"<[^>]+>", "\n", re.sub(r"<script.*?</script>|<style.*?</style>", "", text, flags=re.S)))
        lines = [ln.strip() for ln in body.split("\n") if ln.strip()]

        def after(label: str) -> str:
            for i, ln in enumerate(lines):
                if ln.startswith(label):
                    return lines[i + 1] if i + 1 < len(lines) else ""
            return ""

        title = after("タイトル Title")
        author = after("著者/作者 Author")
        imprint = after("出版事項 Imprint")
        keywords = after("キーワード Keywords")
        if not title:
            continue
        out.append(Record(
            id=f"waseda:{it}", source=f"waseda:{cls}", holder="早稲田大学図書館", collection="古典籍総合データベース", title=title,
            authors=author, date=imprint, years=_years(imprint),
            kind="写" if re.search(r"^写|[(（]写[)）]|写本|書写", imprint) else ("刊" if imprint else ""),
            shelfmark=after("請求記号 Call No."), page=f"{WASEDA}html/{cls}/{pages[0]}/index.html",
            rights="早稲田大学図書館（画像利用は同館の規定による）",
            notes="；".join(filter(None, [keywords, f"分{len(pages)}部分数字化" if len(pages) > 1 else ""]))))
    log(f"  waseda:{cls}: {len(out)} records")
    return out


# ------------------------------------------------------------------ NDL デジタルコレクション (by title)
NDL_SEARCH = "https://ndlsearch.ndl.go.jp/api/opensearch"


def harvest_ndl(fetch: Fetcher, titles: Iterable[str], *, normalize: Callable[[str], str] = lambda x: x, until: int = 1912,
                log: Log = print) -> list[Record]:
    """The digitised pre-1912 items NDL Search finds for each title (the same title, in any script)."""
    out: dict[str, Record] = {}
    for title in titles:
        text = fetch.get(f"{NDL_SEARCH}?{urllib.parse.urlencode({'title': title, 'cnt': '20', 'mediatype': '1'})}") or ""
        for item in re.findall(r"<item>(.*?)</item>", text, re.S):
            def g(tag: str) -> list[str]:
                return [html.unescape(x).strip() for x in re.findall(rf"<{tag}[^>]*>(.*?)</{tag}>", item, re.S)]

            pids = re.findall(r"https?://dl\.ndl\.go\.jp/(?:pid/|info:ndljp/pid/)(\d+)", item)
            issued = " ".join(g("dcterms:issued") + g("dc:date"))
            years = _years(issued)
            if not pids or not years or int(years.split("-")[0]) >= until:
                continue
            name = (g("title") or [""])[0]
            if normalize(_loose(name)) != normalize(_loose(title)):
                continue
            pid = pids[0]
            out.setdefault(pid, Record(
                id=f"ndl:{pid}", source="ndl", holder="国立国会図書館", collection="NDLデジタルコレクション", title=name,
                authors="；".join(g("dc:creator")), date=issued, years=years, manifest=f"https://dl.ndl.go.jp/api/iiif/{pid}/manifest.json",
                page=f"https://dl.ndl.go.jp/pid/{pid}", rights="NDL デジタルコレクション（保護期間満了資料はインターネット公開）"))
    log(f"  ndl: {len(out)} records")
    return list(out.values())


# ------------------------------------------------------------------ linking records to the works of the corpus
# 新字体 → 旧字体 for title matching only (the search normaliser is not touched)
SHINJITAI = str.maketrans({"霊": "靈", "験": "驗", "薬": "藥", "気": "氣", "総": "總", "児": "兒", "弁": "辨", "稲": "稻",
                           "渇": "渴", "焼": "燒", "隠": "隱", "禅": "禪", "遅": "遲", "楽": "樂", "釈": "釋", "蔵": "藏",
                           "拠": "據", "滞": "滯", "変": "變", "応": "應", "恵": "惠", "懐": "懷", "穂": "穗", "粋": "粹",
                           "歯": "齒", "舎": "舍", "当": "當", "発": "發", "闘": "鬭", "猟": "獵", "塩": "鹽", "黒": "黑",
                           "県": "縣", "脳": "腦", "乗": "乘", "価": "價", "仮": "假", "択": "擇", "沢": "澤", "訳": "譯",
                           "単": "單", "営": "營", "労": "勞", "栄": "榮", "蛍": "螢", "覚": "覺", "学": "學", "挙": "舉",
                           "誉": "譽", "鉄": "鐵", "尽": "盡", "昼": "晝", "浅": "淺", "銭": "錢", "残": "殘", "桟": "棧",
                           "巻": "卷", "図": "圖", "伝": "傳", "経": "經", "軽": "輕", "径": "徑", "茎": "莖", "駆": "驅",
                           "医": "醫", "済": "濟", "剤": "劑", "証": "證", "体": "體", "読": "讀", "麦": "麥", "竜": "龍",
                           "独": "獨", "数": "數", "断": "斷", "与": "與", "万": "萬", "旧": "舊", "広": "廣", "歳": "歲",
                           "摂": "攝", "続": "續", "権": "權", "観": "觀", "嘱": "囑", "弾": "彈", "転": "轉", "宝": "寶",
                           "実": "實", "来": "來", "両": "兩", "満": "滿", "静": "靜", "痩": "瘦", "湿": "濕", "胆": "膽",
                           "脈": "脈", "臓": "臟", "囲": "圍", "肃": "肅", "浄": "淨", "犠": "犧", "鉱": "鑛", "枢": "樞"})
_EDITION_PREFIX = re.compile(r"^(?:新刊|新鐫|新鍥|新刻|新校|新編|新版|重刊|重刻|重鐫|重訂|重校|校正|校刻|官板|官刻|京板|和刻|翻刻|覆刻|家刻|袖珍|"
                             r"繡像|圖像|図像|繪圖|絵図|増補|增補|新増|新增|鼇頭|鰲頭|頭書|首書|標注|標註|補註|訂字|訓点|訓點|改正)+")
_VOLUMES = re.compile(r"[（(].*?[）)]|[.．]\s*[巻卷].*$|\s*[0-9０-９一二三四五六七八九十百]+\s*[巻卷冊册].*$|[\s　:：/／].*$")


def _loose(title: str) -> str:
    """A title compared across scripts without the normaliser: 新字体 and simplified forms folded to traditional."""
    return re.sub(r"[（(].*?[）)]|[\s　・·‧《》「」『』〈〉:：/／.．,，]", "", (title or "").translate(SHINJITAI))


def _plain(title: str) -> str:
    return re.sub(r"[\s　・·‧《》「」『』〈〉]", "", (title or "").translate(SHINJITAI))


def title_keys(title: str, normalize: Callable[[str], str]) -> list[tuple[str, str]]:
    """(key, how) for a record title: as written; without volume counts and parentheses; without a print prefix."""
    base = normalize(_plain(title))
    written = _plain(_VOLUMES.sub("", (title or "").translate(SHINJITAI)))  # the prefixes are matched before normalising
    trimmed = normalize(written)
    unprefixed = normalize(_EDITION_PREFIX.sub("", written))
    out = [(base, "exact")]
    if trimmed and trimmed != base:
        out.append((trimmed, "without-volumes"))
    if unprefixed and unprefixed != trimmed and len(unprefixed) >= 3:
        out.append((unprefixed, "without-print-prefix"))
    return out


def work_index(books: Iterable[dict[str, Any]], normalize: Callable[[str], str]) -> dict[str, tuple[str, str]]:
    """normalised title or alias → (work, book id), from book records (titles of two characters or more)."""
    index: dict[str, tuple[str, str]] = {}
    for b in sorted(books, key=lambda b: b["id"]):
        for t in [b.get("title", ""), *(b.get("aliases") or [])]:
            key = normalize(_plain(re.sub(r"[（(].*?[）)]", "", t)))
            if len(key) >= 2:
                index.setdefault(key, (b.get("work") or b["id"], b["id"]))
    return index


def link(records: list[Record], index: dict[str, tuple[str, str]], normalize: Callable[[str], str]) -> int:
    """Link each record to a work by its title; a two-character title (難経, 醫説) only as written, whole."""
    n = 0
    for rec in records:
        for key, how in title_keys(rec.title, normalize):
            if key in index and (len(key) >= 3 or how == "exact"):
                rec.work, rec.book = index[key]
                rec.match = how
                n += 1
                break
    return n


def query_titles(books: Iterable[dict[str, Any]], t2s_path: Path, freq: dict[str, int] | None = None) -> list[str]:
    """Titles to look up in catalogues that write traditional characters: each pre-1912 work's titles and aliases,
    turned back to traditional characters with the inverse of the t2s table — where several traditional characters
    share one simplified form (家 ← 家/傢, 发 ← 發/髮), the one most frequent in the traditional texts (``freq``)."""
    candidates: dict[str, list[str]] = {}
    if t2s_path.exists():
        for line in t2s_path.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#") and "\t" in line:
                trad, simp = line.split("\t")[:2]
                candidates.setdefault(simp, []).append(trad)
    freq = freq or {}

    def trad(ch: str) -> str:
        options = [ch, *candidates.get(ch, [])]
        return max(options, key=lambda c: (freq.get(c, 0), c != ch)) if freq else (candidates.get(ch) or [ch])[0]

    out: dict[str, None] = {}
    for b in books:
        if b.get("modern") or (b.get("composition") or [0])[0] >= 1912:
            continue
        for t in [b.get("title", ""), *(b.get("aliases") or [])]:
            t = re.sub(r"[（(].*?[）)]", "", t or "").strip()
            if len(t) >= 3 and re.fullmatch(r"[\u3400-\u9fff]+", t):
                out["".join(trad(ch) for ch in t)] = None
    return sorted(out)


# ------------------------------------------------------------------ catalog files
def write_csv(path: Path, records: list[Record]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for rec in sorted(records, key=lambda r: r.id):
            w.writerow(rec.row())


def read_csv(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_catalog(directory: Path) -> Iterator[dict[str, str]]:
    for path in sorted(directory.glob("*.csv")):
        yield from read_csv(path)


SOURCES = {  # source key → harvest function (fetcher, log, titles to look up, normaliser)
    **{f"nijl:{k}": (lambda k: lambda fetch, log, titles, normalize: harvest_nijl(fetch, k, log=log))(k) for k in NIJL_HOLDERS},
    "sbb:unschuld": lambda fetch, log, titles, normalize: harvest_unschuld(fetch, log=log),
    "loc:chinese-rare-books": lambda fetch, log, titles, normalize: harvest_loc(fetch, log=log),
    "waseda:ya09": lambda fetch, log, titles, normalize: harvest_waseda(fetch, "ya09", log=log),
    "ndl": lambda fetch, log, titles, normalize: harvest_ndl(fetch, titles, normalize=normalize, log=log),
}


def file_name(source: str) -> str:
    return source.replace(":", "-") + ".csv"


__all__ = ["FIELDS", "Fetcher", "JP_ERAS", "NIJL_HOLDERS", "Record", "SHINJITAI", "SOURCES", "chinese_years", "file_name",
           "harvest_loc", "harvest_ndl", "harvest_nijl", "harvest_unschuld", "harvest_waseda", "link", "load_catalog",
           "manifest_facts", "nijl_enrich", "nijl_licences", "query_titles", "read_csv", "title_keys", "work_index", "write_csv"]
