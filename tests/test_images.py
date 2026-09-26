"""Image witnesses (影像见证): the harvesters of the library records (NIJL holder lists and IIIF manifests, the
Staatsbibliothek's SRU catalogue, NDL Search) on constructed responses, the dating of imprint statements, the terms
of use, the linking of records to the works of the corpus by title, and the catalog files."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from taochronos.plugins.classics.chronology import Chronology
from taochronos.plugins.classics.domain import DomainPack
from taochronos.plugins.classics.ingest import images
from taochronos.plugins.classics.ingest.images import Record

HOME = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def normalize():
    return DomainPack(HOME / "domains" / "classics").variants.normalize_text


class FakeFetch:
    """Answers from a dict of URL → text (or a function of the URL); records what was asked."""

    def __init__(self, pages: dict[str, str], default=None) -> None:
        self.pages = pages
        self.default = default
        self.asked: list[str] = []

    def get(self, url: str, *, refresh: bool = False) -> str | None:
        self.asked.append(url)
        return self.pages.get(url) if url in self.pages else (self.default(url) if self.default else None)


USAGE = """<table><tr><th>地域</th></tr>
<tr><td>東京</td><td>KNIK</td><td>研医会図書館</td><td>663</td><td>デジタル</td>
<td><a href="list-kenikaito.html">画像一覧へ</a></td><td><a href="http://ken-i-kai.org/homepage/indextoshokan.html">案内</a></td>
<td><a href="https://creativecommons.org/licenses/by-nc/4.0/deed.ja">CC BY-NC 4.0</a>にて公開</td></tr>
<tr><td>京都</td><td>KYOT</td><td>京都大学附属図書館</td><td>11,469</td><td>デジタル</td>
<td><a href="list-kyot.html">画像一覧へ</a></td><td><a href="https://rmda.kulib.kyoto-u.ac.jp/reuse">案内</a></td><td></td></tr>
<tr><td>東京</td><td>TOKY</td><td>東京大学医学図書館</td><td>62</td><td>デジタル</td>
<td><a href="list-toky-medical.html">画像一覧へ</a></td><td></td>
<td><a href="https://rightsstatements.org/page/NoC-CR/1.0/?language=en">Rights Statements No Copyright - Contractual Restrictions</a>にて公開</td></tr>
</table>"""
KNIK = """<table><tr><th>BID</th><th>書名/Title</th><th>よみ/Kana</th><th>デジタル請求記号</th><th>画像</th><th>文庫名等</th></tr>
<tr><td>100232346</td><td>医学雑集</td><td>いがくざっしゅう</td><td>ＤＩＧＫＮＩＫ０００７０</td><td><a href="/biblio/100232346">表示</a></td><td></td></tr>
<tr><td>100452159</td><td>新刊傷寒論 10巻</td><td>しんかんしょうかんろん</td><td>ＤＩＧＫＮＩＫ０００７１</td><td><a href="/biblio/100452159">表示</a></td><td></td></tr>
</table>"""
KYOT = """<table><tr><th>BID</th></tr>
<tr><td>100317231</td><td>嬰児論</td><td>えいじろん</td><td>富士川／エ／２</td><td>ＤＩＧ－ＫＹＯＴ－１</td><td><a>表示</a></td><td>富士川文庫</td></tr>
<tr><td>100416963</td><td>嗚呼忠臣楠氏籏</td><td>ああちゅうしん</td><td>４－２８／マ／１</td><td>ＤＩＧ－ＫＹＯＴ－２</td><td><a>表示</a></td><td>大惣本</td></tr>
</table>"""


def test_nijl_holder_lists_filters_and_terms():
    fetch = FakeFetch({images.NIJL + "page/usage.html": USAGE, images.NIJL + "page/list-kenikaito.html": KNIK,
                       images.NIJL + "page/list-kyot.html": KYOT})
    assert images.nijl_licences(fetch) == {"list-kenikaito.html": "CC BY-NC 4.0",
                                           "list-kyot.html": "利用条件见 https://rmda.kulib.kyoto-u.ac.jp/reuse",
                                           "list-toky-medical.html": "RightsStatements NoC-CR 1.0"}
    knik = images.harvest_nijl(fetch, "knik", log=lambda m: None)
    assert [(r.id, r.title, r.rights, r.notes) for r in knik] == [
        ("nijl:100232346", "医学雑集", "CC BY-NC 4.0", "画像請求記号 ＤＩＧＫＮＩＫ０００７０"),
        ("nijl:100452159", "新刊傷寒論 10巻", "CC BY-NC 4.0", "画像請求記号 ＤＩＧＫＮＩＫ０００７１")]
    assert knik[1].manifest == images.NIJL + "biblio/100452159/manifest" and knik[1].page == images.NIJL + "biblio/100452159"
    [kyoto] = images.harvest_nijl(fetch, "kyoto-fujikawa", log=lambda m: None)  # only the 富士川文庫 of the Kyoto list
    assert (kyoto.title, kyoto.shelfmark, kyoto.collection) == ("嬰児論", "富士川／エ／２", "富士川文庫")
    assert kyoto.rights.startswith("利用条件见 https://rmda.kulib.kyoto-u.ac.jp/reuse")


def test_nijl_enrich_reads_presentation_2_and_follows_a_collection_to_the_holder():
    v2 = {"@context": "http://iiif.io/api/presentation/2/context.json", "license": "https://kokusho.nijl.ac.jp/page/usage.html",
          "metadata": [{"label": "author", "value": "張／仲景 他"}, {"label": "Title", "value": "傷寒論"},
                       {"label": "Date", "value": "山本／長兵衞〈皇都〉，林／權兵衞〈皇都〉 享和１"}]}
    kyoto = "https://rmda.kulib.kyoto-u.ac.jp/iiif/metadata_manifest/RB00001275/manifest.json"
    collection = {"@type": "sc:Collection", "manifests": [{"@id": kyoto, "@type": "sc:Manifest", "label": "IIIF連携"}]}
    v3 = {"type": "Manifest", "rights": "https://rmda.kulib.kyoto-u.ac.jp/license_icon/free-license",
          "metadata": [{"label": {"ja": ["タイトル / 著者"]},
                        "value": {"ja": ['<a href="https://rmda.kulib.kyoto-u.ac.jp/item/RB00001275"><strong>嬰児論</strong> / (清)周士称撰</a>']}}]}
    fetch = FakeFetch({"https://m/1": json.dumps(v2), "https://m/2": json.dumps(collection), kyoto: json.dumps(v3),
                       "https://m/3": "<html>not found</html>"})
    rec = Record(id="nijl:1", source="nijl:knik", holder="研医会図書館", title="傷寒論", manifest="https://m/1", rights="CC BY-NC 4.0")
    images.nijl_enrich(fetch, rec)
    assert (rec.authors, rec.years, rec.rights) == ("張／仲景 他", "1801", "CC BY-NC 4.0")  # the usage page names no licence
    assert rec.date.endswith("享和１")
    rec = Record(id="nijl:2", source="nijl:kyoto-fujikawa", holder="京都大学", title="嬰児論", manifest="https://m/2")
    images.nijl_enrich(fetch, rec)
    assert (rec.manifest, rec.authors, rec.rights) == (kyoto, "(清)周士称撰", "自由利用（京都大学貴重資料デジタルアーカイブ）")
    rec = Record(id="nijl:3", source="nijl:knik", holder="h", title="t", manifest="https://m/3", authors="kept")
    images.nijl_enrich(fetch, rec)
    assert rec.authors == "kept"  # an unreadable manifest changes nothing


def test_nijl_enrich_reads_the_record_api_first():
    tokyo = {"bid": 100452159, "author": ["（漢）／張／仲景 著", "（晉）／王／叔和 撰次"], "kansha": "刊",
             "bpublish": ["享和１", "　〈皇都〉山本／長兵衞"], "chuki": ["〈注〉正徳５年叙刊の再板。"],
             "manifest": "https://kokusho.nijl.ac.jp/biblio/100452159/manifest", "licensetext1": "All-Rights-Reserved",
             "doi": "https://doi.org/10.20730/100452159"}
    kyoto_manifest = "https://rmda.kulib.kyoto-u.ac.jp/iiif/metadata_manifest/RB00001275/manifest.json"
    kyoto = {"bid": 100317231, "work": [{"name": "嬰児論", "author": [{"aid": 1, "name": "周／士称（Shuu Shishou） 撰"}]}],
             "kansha": "刊", "manifest": kyoto_manifest,
             "chuki": ["〈注〉寛政９跋，所蔵者作成画像のＩＩＩＦ連携。"], "doi": "https://doi.org/10.20730/100317231"}
    fetch = FakeFetch({images.NIJL_API + "100452159": json.dumps(tokyo, ensure_ascii=False),
                       images.NIJL_API + "100317231": json.dumps(kyoto, ensure_ascii=False),
                       kyoto_manifest: json.dumps({"rights": "https://rmda.kulib.kyoto-u.ac.jp/license_icon/free-license"})})
    rec = Record(id="nijl:100452159", source="nijl:utokyo-medicine", holder="東京大学総合図書館", title="傷寒論",
                 manifest=images.NIJL + "biblio/100452159/manifest", rights="利用条件见 https://example.org/reuse")
    images.nijl_enrich(fetch, rec)
    assert (rec.authors, rec.date, rec.years, rec.kind) == ("（漢）／張／仲景 著；（晉）／王／叔和 撰次", "享和１ 〈皇都〉山本／長兵衞", "1801", "刊")
    assert rec.rights == "All-Rights-Reserved（利用条件见 https://example.org/reuse）" and rec.page == "https://doi.org/10.20730/100452159"
    assert rec.notes.endswith("〈注〉正徳５年叙刊の再板。")
    rec = Record(id="nijl:100317231", source="nijl:kyoto-fujikawa", holder="京都大学", title="嬰児論",
                 manifest=images.NIJL + "biblio/100317231/manifest")
    images.nijl_enrich(fetch, rec)
    assert (rec.manifest, rec.date, rec.years) == (kyoto_manifest, "寛政９跋", "1797")  # a dated colophon, no imprint
    assert rec.authors == "周／士称（Shuu Shishou） 撰"  # the copy names none: the work's author
    assert rec.rights == "自由利用（京都大学貴重資料デジタルアーカイブ）"  # the holder's manifest states the terms

def test_imprint_dates_western_japanese_and_chinese_eras(normalize):
    assert images._years("1790") == "1790" and images._years("1821-1850") == "1821-1850"
    assert images._years("須原屋／茂兵衛〈江戸〉 享和１") == "1801" and images._years("元禄元") == "1688"
    assert images._years("寬政3") == "1791"  # the old form of the era name
    assert images._years(" 淳化2 /  寛政6") == "1794"  # the Japanese print of a Song text
    assert images._years(" 〔寛永〕") == "1624-1644" and images._years(" ［文政頃］") == "1818-1830"
    assert images._years("芳野屋／作十郎〈京〉 ［江戸中期］") == "1709-1789"
    assert images._years(" [1‐‐‐]") == "" and images._years("傳經堂 嘉慶5") == ""
    chron = Chronology(HOME / "domains" / "classics" / "eras.yaml", normalize)
    assert images.chinese_years("傳經堂 嘉慶5", chron) == "1800" and images.chinese_years("掃葉山房 光緒13", chron) == "1887"
    assert images.chinese_years("唐對溪〈金陵〉 万暦9", chron) == "1581" and images.chinese_years(" ［康煕］", chron) == "1662-1722"
    assert images.chinese_years("須原屋 平左衛門", chron) == ""


def test_rights_urls_are_named():
    assert images._rights("https://creativecommons.org/licenses/by-nc-sa/4.0/deed.ja") == "CC BY-NC-SA 4.0"
    assert images._rights("https://creativecommons.org/publicdomain/mark/1.0/deed.ja") == "Public Domain Mark 1.0"
    assert images._rights("https://creativecommons.org/publicdomain/zero/1.0/") == "CC0 1.0"
    assert images._rights("https://rightsstatements.org/vocab/NoC-CR/1.0/") == "RightsStatements NoC-CR 1.0"
    assert images._rights("https://kokusho.nijl.ac.jp/page/usage.html") == ""


SRU_PAGE = """<zs:searchRetrieveResponse xmlns:zs="http://www.loc.gov/zing/srw/"><zs:numberOfRecords>2</zs:numberOfRecords>
<zs:records><zs:record><zs:recordData><record xmlns="http://www.loc.gov/MARC21/slim">
<controlfield tag="001">1234567</controlfield>
<datafield tag="245" ind1="1" ind2="0"><subfield code="6">880-01</subfield><subfield code="a">Shang han lun</subfield></datafield>
<datafield tag="880" ind1="1" ind2="0"><subfield code="6">245-01</subfield><subfield code="a">傷寒論</subfield></datafield>
<datafield tag="246" ind1="3" ind2=" "><subfield code="a">Shanghan lun</subfield></datafield>
<datafield tag="264" ind1=" " ind2="1"><subfield code="c">[1790]</subfield></datafield>
<datafield tag="535" ind1="1" ind2=" "><subfield code="3">Slg. Unschuld 8123</subfield></datafield>
<datafield tag="650" ind1=" " ind2="7"><subfield code="a">Chinesische Medizin</subfield></datafield>
<datafield tag="650" ind1=" " ind2="7"><subfield code="a">Sammlung Unschuld</subfield></datafield>
<datafield tag="776" ind1="0" ind2="8"><subfield code="w">(DE-627)7654321</subfield></datafield>
</record></zs:recordData></zs:record>
<zs:record><zs:recordData><record xmlns="http://www.loc.gov/MARC21/slim">
<controlfield tag="001">7777777</controlfield>
<datafield tag="245" ind1="1" ind2="0"><subfield code="a">Another book</subfield></datafield>
<datafield tag="924" ind1=" " ind2=" "><subfield code="g">4 Ostas. 12</subfield></datafield>
</record></zs:recordData></zs:record></zs:records></zs:searchRetrieveResponse>"""


def test_unschuld_records_join_the_provenance_data():
    provenance = "SBB shelf mark,Date,City,Description\nSlg. Unschuld 8123,1986,Beijing,bought at a market\n"
    fetch = FakeFetch({images.PROVENANCE_CSV: provenance}, default=lambda url: SRU_PAGE if url.startswith(images.SRU) else None)
    [rec] = images.harvest_unschuld(fetch, log=lambda m: None)  # the record without an Unschuld shelfmark is left out
    assert (rec.id, rec.title, rec.title_alt, rec.years, rec.shelfmark) == ("sbb:1234567", "傷寒論", "Shanghan lun", "1790",
                                                                            "Slg. Unschuld 8123")
    assert rec.manifest == "https://content.staatsbibliothek-berlin.de/dc/PPN7654321/manifest"
    assert rec.rights.startswith("Public Domain Mark 1.0") and rec.notes == "主题：Chinesische Medizin；入藏：1986 Beijing"
    assert sum(1 for u in fetch.asked if u.startswith(images.SRU)) == 1  # one page holds both records


def test_loc_keeps_medical_items_by_subject_or_title():
    results = {"results": [{"id": "https://www.loc.gov/item/1/", "title": "Shi yi de xiao fang"},
                           {"id": "https://www.loc.gov/item/2/", "title": "Huang niu jing"},
                           {"id": "https://www.loc.gov/item/3/", "title": "Ben cao"},
                           {"id": "https://www.loc.gov/item/4/", "title": "Yao shi jing"}], "pagination": {"next": None}}
    items = {
        "1": {"other_title": ["世醫得效方 : 二十卷 /"], "date": "1345", "created_published": ["元刻本"],
              "rights": ["<p>The Library of Congress obtained permission … National Central Library of Taiwan.</p>"],
              "iiif_manifest_url": "https://www.loc.gov/item/1/manifest.json"},  # no subject heading: the title tells
        "2": {"other_title": ["新刊圖像黃牛經全書"], "subject_headings": [], "rights": []},  # cattle, not medicine
        "4": {"other_title": ["藥師琉璃光如來本願功德經"], "subject_headings": ["Zi bu--Shi jia lei 子部--釋家類"]},  # a sutra
        "3": {"other_title": ["本草綱目"], "subject_headings": ["Materia medica--China"], "date": "1603",
              "rights": ["<p>The Library of Congress is unaware of any copyright or other restrictions in the World Digital "
                         "Library Collection.</p>"]},
    }

    def answer(url: str):
        if "/collections/chinese-rare-books/" in url:
            return json.dumps(results) if "q=medicine" in url else json.dumps({"results": [], "pagination": {}})
        iid = url.split("/item/")[1].split("/")[0]
        return json.dumps({"item": items[iid]}, ensure_ascii=False)

    recs = images.harvest_loc(FakeFetch({}, default=answer), log=lambda m: None)
    assert [(r.id, r.title, r.years) for r in recs] == [("loc:1", "世醫得效方", "1345"), ("loc:3", "本草綱目", "1603")]
    assert recs[0].rights.startswith("仅供教育与研究在线阅览") and recs[1].rights.startswith("馆方未知有版权或其他限制")
    assert recs[0].manifest == "https://www.loc.gov/item/1/manifest.json" and recs[0].kind == "刊"

NDL_RSS = """<rss><channel>
<item><title>傷寒論10卷</title><dc:title>傷寒論10卷</dc:title><dc:creator>張機</dc:creator><dcterms:issued>寛文8</dcterms:issued>
<dc:date>1668</dc:date><dc:description>刊本</dc:description><rdfs:seeAlso rdf:resource="https://dl.ndl.go.jp/pid/2536123"/></item>
<item><dc:title>傷寒論講義</dc:title><dc:date>1790</dc:date><rdfs:seeAlso rdf:resource="https://dl.ndl.go.jp/pid/999"/></item>
<item><dc:title>傷寒論</dc:title><dc:date>1925</dc:date><rdfs:seeAlso rdf:resource="https://dl.ndl.go.jp/pid/888"/></item>
<item><dc:title>傷寒論</dc:title><dc:date>1800</dc:date><rdfs:seeAlso rdf:resource="https://ci.nii.ac.jp/ncid/BA1"/></item>
</channel></rss>"""


def test_ndl_keeps_the_digitised_items_of_the_title_before_1912(normalize):
    calls = []

    def answer(url: str):  # an overload answer first, then the page
        calls.append(url)
        return '<?xml version="1.0"?><error><code>429</code></error>' if len(calls) == 1 else NDL_RSS

    [rec] = images.harvest_ndl(FakeFetch({}, default=answer), ["伤寒论"], normalize=normalize, backoff=0, log=lambda m: None)
    assert (rec.id, rec.title, rec.authors, rec.date, rec.years, rec.kind) == ("ndl:2536123", "傷寒論10卷", "張機", "寛文8", "1668", "刊")
    assert rec.manifest == "https://dl.ndl.go.jp/api/iiif/2536123/manifest.json" and len(calls) == 2
    assert "until=1911" in calls[0] and "mediatype" not in calls[0]


def test_titles_link_records_to_works(normalize):
    books = [{"id": "kr_shl", "title": "傷寒論", "work": "shanghanlun", "aliases": ["傷寒卒病論"]},
             {"id": "jc_lingshu", "title": "灵枢经", "work": "lingshu"}, {"id": "jc_nanjing", "title": "难经", "work": "nanjing"},
             {"id": "jc_x", "title": "論"}]
    index = images.work_index(books, normalize)
    assert normalize("論") not in index  # a single character is not a key
    keys = images.title_keys("新刊図像傷寒論 10巻", normalize)
    assert [how for _, how in keys] == ["exact", "without-volumes", "without-print-prefix"]
    assert keys[-1][0] == normalize("傷寒論")  # stacked print prefixes are all removed
    recs = [Record(id="a", source="s", holder="h", title="新刊傷寒論 10巻"), Record(id="b", source="s", holder="h", title="霊枢経（写本）"),
            Record(id="c", source="s", holder="h", title="傷寒卒病論"), Record(id="d", source="s", holder="h", title="医学雑集"),
            Record(id="e", source="s", holder="h", title="難経"), Record(id="f", source="s", holder="h", title="難経 2巻"),
            Record(id="g", source="s", holder="h", title="重刊難経")]
    assert images.link(recs, index, normalize) == 4
    assert [(r.work, r.book, r.match) for r in recs] == [
        ("shanghanlun", "kr_shl", "without-print-prefix"), ("lingshu", "jc_lingshu", "without-volumes"),  # 霊 folded to 靈
        ("shanghanlun", "kr_shl", "exact·alias"), ("", "", ""), ("nanjing", "jc_nanjing", "exact"),
        ("", "", ""), ("", "", "")]  # a two-character title links only as written, whole


def test_query_titles_choose_the_frequent_traditional_form(tmp_path):
    t2s = tmp_path / "t2s.tsv"
    t2s.write_text("# trad\tsimp\n發\t发\n髮\t发\n頭\t头\n論\t论\n", encoding="utf-8")
    books = [{"id": "a", "title": "头发论", "composition": [1600, 1600]}, {"id": "b", "title": "现代书籍", "composition": [1950, 1950]},
             {"id": "c", "title": "某某书", "modern": True}, {"id": "d", "title": "论", "composition": [1600, 1600]}]
    assert images.query_titles(books, t2s, {"發": 10, "髮": 1}) == ["頭發論"]
    assert images.query_titles(books, t2s, {"發": 1, "髮": 10}) == ["頭髮論"]


def test_catalog_files_round_trip(tmp_path):
    recs = [Record(id="nijl:2", source="nijl:knik", holder="研医会図書館", title="乙", years="1801"),
            Record(id="nijl:1", source="nijl:knik", holder="研医会図書館", title="甲", manifest="https://m/1")]
    images.write_csv(tmp_path / images.file_name("nijl:knik"), recs)
    assert (tmp_path / "nijl-knik.csv").exists()
    rows = list(images.load_catalog(tmp_path))
    assert [r["id"] for r in rows] == ["nijl:1", "nijl:2"] and list(rows[0]) == images.FIELDS
    assert rows[1]["years"] == "1801" and rows[0]["manifest"] == "https://m/1"
