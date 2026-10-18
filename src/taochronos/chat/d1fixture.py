"""A small D1 backup for the tests (``cloud/test/backup.test.js``, ``tests/test_d1.py``): ten books of the committed
要籍 pack (corpus/web — every kind of source, of passage id, of date), made into a store, its results precomputed by
the Python tools, and exported and imported by the exporter itself into local SQLite files (``db-<k>.sqlite``), spread
over five databases as the full corpus is (what a search costs grows with them: a statement and side rows a database).
``python -m taochronos.chat.d1 fixture <dir>``.

``fixture.json`` also carries ``alias_cases``: what the alias layer's pure functions (``backup/aliases.js``; ADR 0023)
give in Python on the layer the Worker ships, which the port must reproduce exactly — questions read with the layer
(their expansions and views, under the profile's parameters and some others; a few searched, for the reasons an
expansion goes unsearched), the gates on the fixture's passages and on made-up ones (将军 and 大将军, 天地精, a
straddle, 青木香's window, 通草's periods, ties), the slots and the rounding.  No held-out gold name is asked or tested
(``aliases_gold.heldout_surfaces``).
"""

from __future__ import annotations

import gzip
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

BOOKS = ("cm_shanghan_npm", "cm_jingui_wuqian", "ws_36bca7b992", "suwen_wangbing", "hejiju_fang", "jc_o056", "yimen_falv",
         "ws_abfd7a1046", "tab_277", "mg_nuke_jiyao")
CLAUSE = "太阳之为病，脉浮，头项强痛而恶寒"
KEYS: list[tuple[str, str, dict[str, Any]]] = [
    ("study.formula", "桂枝汤", {"name": "桂枝汤"}),
    ("study.herb", "人参", {"name": "人参"}),
    ("study.term", "消渴", {"term": "消渴"}),
    ("study.network", "桂枝汤", {"target": "桂枝汤"}),
    ("study.taboo", "", {}),
    ("kg.claims", "disease:消渴", {"terms": ["disease:消渴"]}),
]
# a prescription pasted in as a question (422 characters): read without the layer past hybrid.ALIAS_MAX_CHARS (200)
LONG_QUESTION = "治伤寒中风，" + "国老二两，桂枝三两，芍药三两，生姜三两，大枣十二枚，" * 16
# the Python tools' answers on the fixture, which the backup's must equal (a search: its query analysis, and the labels
# of the passages both find)
REFERENCE: list[tuple[str, dict[str, Any]]] = [
    ("classics.get_passage", {"passage_id": "cm_shanghan_npm.00001"}),
    ("classics.get_passage", {"passage_id": "suwen_wangbing.000.00001"}),
    ("classics.get_passage", {"passage_id": "hejiju_fang.000.00002"}),
    ("classics.get_passage", {"passage_id": "cm_jingui_wuqian.99999"}),
    ("classics.list_books", {}),
    ("classics.list_books", {"query": "伤寒"}),
    ("classics.list_books", {"dynasty": "宋", "limit": 3}),
    ("classics.canon", {"limit": 5}),
    ("classics.canon", {"query": "伤寒"}),
    ("classics.canon", {"held": True}),
    ("kg.term", {"surface": "消渴"}),
    ("kg.term", {"surface": "桂枝汤"}),
    ("kg.term", {"surface": "pulse:浮"}),  # an id that is not category:term (the term is 脉浮)
    ("kg.term", {"surface": "formula:小柴胡汤"}),
    ("kg.term", {"surface": "薯蓣"}),
    ("philology.normalize", {"text": "太陽之為病，脈浮，頭項強痛而惡寒。黃耆、五藏"}),
    ("philology.normalize", {"text": "募原淡飲栝蔞"}),
    ("philology.assess_passage", {"passage_id": "suwen_wangbing.000.00001"}),
    ("philology.assess_passage", {"passage_id": "cm_jingui_wuqian.00365"}),
    ("philology.collate", {"passage_a": "cm_jingui_wuqian.00356", "passage_b": "cm_jingui_wuqian.00365"}),
    ("philology.inspect_page", {"object_id": "suwen_wangbing.000.00001"}),
    ("validation.provenance_chain", {"object_id": "cm_shanghan_npm.00001"}),
    ("validation.verify_quote", {"quote": CLAUSE}),
    ("validation.verify_quote", {"quote": "桂枝湯主之"}),  # twice in one chunk (00356, 00365), among others
    ("validation.verify_quote", {"quote": "太阳之为病脉浮头项强痛而恶寒"}),  # 白文 against punctuated witnesses
    ("validation.verify_quote", {"quote": "这句话不在任何古籍里出现过"}),
    ("validation.verify_quote", {"quote": "脉浮紧"}),
    ("validation.verify_quote", {"quote": "柴胡桂枝湯主之", "passage_id": "cm_jingui_wuqian.00365"}),
    ("study.metrology", {"dose": "一两半", "year": 1600}),
    ("study.metrology", {"dose": "三两", "year": 200}),
    ("study.metrology", {"dose": "半升", "year": 200}),
    ("modern.safety", {"text": "附子一枚，炮，朱砂、雄黄各少许"}),
    ("literature.modern_evidence", {"term": "青蒿"}),
    ("classics.search", {"query": "太阳之为病脉浮头项强痛而恶寒"}),
    ("classics.search", {"query": "宋代以前的消渴"}),
    ("classics.search", {"query": "桂枝汤", "books": ["cm_shanghan_npm"]}),
    ("classics.search", {"query": "人参汤即理中汤"}),  # a variant spelling replaces every occurrence (湯 twice)
    # the alias layer's questions (ADR 0023): an alias, its drug, a drug in a period, an alias in another, a name nobody knows
    ("classics.search", {"query": "国老"}),
    ("classics.search", {"query": "甘草"}),
    ("classics.search", {"query": "唐以前的木通"}),
    ("classics.search", {"query": "清代的通草"}),
    ("classics.search", {"query": "蘖木"}),
    # … and the question rules the Worker's port reads alike (search.js): a shared name, stop names asked on their own
    # (one after a period), a cue name a 一名 shows as a drug, one inside a blocker, a longer name and a run nobody knows,
    # a quoted alias beside its drug, origin questions, a book filter, the side queue's place taken away (k, routes)
    # and the layer turned off
    ("classics.search", {"query": "鬼督邮是什么药"}),
    ("classics.search", {"query": "救火是哪味药"}),
    ("classics.search", {"query": "宋以前的解离"}),
    ("classics.search", {"query": "大黄一名将军"}),
    ("classics.search", {"query": "将军"}),
    ("classics.search", {"query": "将军之官"}),
    ("classics.search", {"query": "慎火草"}),
    ("classics.search", {"query": "干葛"}),
    ("classics.search", {"query": "百枝"}),
    ("classics.search", {"query": "“国老”与甘草"}),
    ("classics.search", {"query": "人参最早见于哪部书"}),
    ("classics.search", {"query": "唐以前的通草"}),
    ("classics.search", {"query": "丹砂", "books": ["cm_shanghan_npm", "jc_o056"]}),
    ("classics.search", {"query": "国老", "k": 3}),
    ("classics.search", {"query": "国老", "routes": ["bm25", "temporal"]}),
    ("classics.search", {"query": "国老", "aliases": "off"}),
    ("classics.search", {"query": "国老", "k": 0}),  # no place and no hit: k as asked, not as the Worker caps it
    # each of these reads differently where one of the question rules is left out (found by leaving each out of the
    # port in turn): a drug word, another drug's name, a stop name alone, a stop written inside its blocker or a longer
    # word, unknown runs of four and of known characters, a dose beside a name, the thresholds of a common name, a longer
    # alias over a lexicon name, a blocker that names a drug, a quoted name's own mentions, a doubtful pairing, a name the
    # lexicon files under another term
    ("classics.search", {"query": "白粉是什么药"}),
    ("classics.search", {"query": "芙蓉与甘草"}),
    ("classics.search", {"query": "止行"}),
    ("classics.search", {"query": "抱薪救火"}),
    ("classics.search", {"query": "救火车"}),
    ("classics.search", {"query": "岩蜜二两"}),
    ("classics.search", {"query": "姜枣"}),
    ("classics.search", {"query": "山药二两"}),
    ("classics.search", {"query": "鸡头治什么病"}),
    ("classics.search", {"query": "清代的人言"}),
    ("classics.search", {"query": "余甘子与甘草"}),
    ("classics.search", {"query": "石南藤"}),
    ("classics.search", {"query": "“碧蝉花”"}),
    ("classics.search", {"query": "清代的蹲鸱"}),
    ("classics.search", {"query": "地精"}),
    # a name only lists give, and only as a candidate, beside another name is no name of the question (味药 in 苦菜是哪味药);
    # a candidate only lists give is listed only where nothing else is, and is no rival (五爪龙 stays 乌蔹莓's)
    ("classics.search", {"query": "苦菜是哪味药"}),
    ("classics.search", {"query": "五爪龙"}),
    # of two such names and nothing else the first is asked (支子, not 味药); one holding a lexicon name is asked whole
    ("classics.search", {"query": "支子是哪味药"}),
    ("classics.search", {"query": "明没药是哪味药"}),
    # a blocker the lexicon files as a whole (川乌头: its mention is asked); what a question says of a drug is no longer
    # name of it (甘草入脾 asks 甘草 and 脾); a dose beside a weak herb's run (葛二两 asks 葛); a hit that is A by one asked
    # drug and writes the other out of drug context, labelled with neither its reading nor homonym (阿胶与通草)
    ("classics.search", {"query": "川乌头"}),
    ("classics.search", {"query": "甘草入脾"}),
    ("classics.search", {"query": "葛二两"}),
    ("classics.search", {"query": "阿胶与通草"}),
    # a blocker the lexicon reads as a formula keeps the layer's drug, asked as written (蜣螂转丸), but a longer formula
    # over a blocker is read as today (麦门冬汤 over 麦门冬, 五加皮散 over 五加皮); a question as long as the layer reads
    # (hybrid.ALIAS_MAX_CHARS) and a longer one, read without the layer and ranked as today
    ("classics.search", {"query": "蜣螂转丸"}),
    ("classics.search", {"query": "麦门冬汤"}),
    ("classics.search", {"query": "五加皮散的组成"}),
    ("classics.search", {"query": LONG_QUESTION[:200]}),
    ("classics.search", {"query": LONG_QUESTION}),
]
# the alias cases: questions read with the layer, and made-up passages for the gates ([text, the name it tests, the
# passage's range, its edition's]) — none asks or writes a held-out gold name
ALIAS_QUESTIONS = ("国老", "甘草", "唐以前的木通", "清代的通草", "唐以前的通草", "明清的通草", "通草", "蘖木", "大黄", "将军", "大将军",
                   "大黄一名将军", "地精", "天地精", "人参", "鬼督邮是什么药", "百枝", "救火是哪味药", "宋以前的解离", "止行", "慎火草",
                   "国老与蜜甘", "山药", "元参", "党参最早见于哪部书", "红豆", "大戟", "赤箭", "马兜铃", "紫河车", "朴消", "百药煎",
                   "桂枝汤与甘草", "苦菜是哪味药", "五爪龙", "乌蔹莓", "金沸草", "胡王使者", "支子是哪味药", "彼子")
ALIAS_SAMPLE = 120  # more names of the layer, each asked alone, a third of them in a period too
ALIAS_SEARCHES: list[tuple[str, dict[str, Any]]] = [  # searched: expansions unsearched for want of a place
    ("国老", {"k": 10}), ("国老", {"k": 3}), ("国老", {"k": 10, "routes": ["bm25"]}), ("甘草", {"k": 2}),
    ("甘草", {"k": 3, "alias_params": {"ablate": ["slots"]}}),
    ("国老", {"k": 0}), ("国老", {"k": -1}),  # k as asked: ⌊3·0/10⌋ = 0, no place; ⌊3·(−1)/10⌋ = −1 (floored), searched
]
ALIAS_PARAMS: list[dict[str, Any]] = [{"ablate": ["gates"]}, {"ablate": "period"}, {"ablate": ["boundary", "slots"]},
                                      {"witness_scope": "web"}, {"expansions": 1}, {"mask_bits": 3}, {"mask_bits": 12}]
ALIAS_TEXTS: list[tuple[str, str, list[int | None] | None, list[int | None] | None]] = [
    ("大将军", "将军", None, None), ("将军二两", "将军", [200, 220], None), ("将军（酒洗）三两", "将军", None, None),
    ("大黄一名将军", "将军", None, None), ("将军之官", "将军", None, None), ("将军、芒硝各三两", "将军", None, None),
    ("故有将军之名", "将军", None, None), ("将军锦纹大黄", "将军", [1100, 1200], None), ("𠀀将军二两😀大将军", "将军", None, None),
    ("天地精", "地精", None, None), ("人参一名地精", "地精", None, None), ("地精何首乌交藤", "地精", [700, 800], None),
    ("地精", "地精", None, None), ("大黄大戟甘遂各等分", "大戟", None, None), ("黄大戟", "大戟", None, None),
    ("青木香二两", "木香", [600, 650], None), ("青木香二两", "木香", [1200, 1250], None), ("青木香二两", "木香", None, None),
    ("通草二两", "通草", [650, 650], None), ("通草二两", "通草", [1700, 1700], None), ("通草二两", "通草", None, None),
    ("通草木通", "通草", [1000, None], None), ("紫河车一具", "紫河车", None, None), ("紫河车蚤休重楼", "紫河车", [1500, 1600], None),
    ("山药", "山药", [600, 650], [1600, 1700]), ("山药", "山药", [600, 650], None), ("山药", "山药", [1100, 1100], None),
    ("山药", "山药", [None, 900], [None, None]), ("元参三两", "元参", [900, 1000], None), ("国老", "国老", None, None),
    ("救火", "救火", None, None), ("抱薪救火麻黄桂枝", "救火", None, None), ("百枝", "百枝", None, None),
    ("红豆蔻 红豆二两", "红豆", None, None), ("慎火草", "慎火", None, None), ("马兜铃根名青木香", "青木香", [600, 650], None),
    # a window ends the year before its to: a passage of the year a referent changes reads the new one
    ("通草二两", "通草", [959, 959], None), ("通草二两", "通草", [960, 960], None), ("通草二两", "通草", [961, 961], None),
    ("通草二两", "通草", [960, 1000], None), ("青木香二两", "青木香", [1099, 1099], None),
    ("青木香二两", "青木香", [1100, 1100], None), ("青木香二两", "青木香", [1101, 1101], None),
]


def build_fixture(out: str | Path, *, home: str | Path | None = None, log: Any = print) -> dict[str, Any]:
    from ..config import find_home
    from ..plugins.classics.domain import DomainPack
    from ..plugins.classics.webcorpus import build_store
    from .d1 import SqliteTarget, make_plan, run_import, summary
    from .d1results import Precompute, clause_key, runtime_for

    root = find_home(str(home) if home else None)
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    pack_dir = out / "pack"
    pack_dir.mkdir(parents=True)
    books = [b for b in json.loads((root / "corpus" / "web" / "books.json").read_text(encoding="utf-8")) if b["id"] in BOOKS]
    (pack_dir / "books.json").write_text(json.dumps(books, ensure_ascii=False), encoding="utf-8")
    with gzip.open(root / "corpus" / "web" / "passages.jsonl.gz", "rt", encoding="utf-8") as f:
        lines = [line for line in f if json.loads(line)["book_id"] in BOOKS]
    (pack_dir / "passages.jsonl.gz").write_bytes(gzip.compress("".join(lines).encode("utf-8"), mtime=0))
    pack = DomainPack(root / "domains" / "classics")
    store = out / "data" / "corpus" / "tcm.sqlite"
    store.parent.mkdir(parents=True)
    # the pack keeps whole chapters spread through each book, with their numbers in the full corpus: the store has gaps
    build_store(pack_dir, store, pack.variants.normalize_text, pack.variants.fingerprint, index=True)
    runtime = runtime_for(store, home=root)
    norm = pack.variants.normalize_text
    keys = KEYS + [("study.commentaries", clause_key(CLAUSE, norm), {"text": CLAUSE})]
    results = Precompute(runtime, only=keys, log=log)
    plan = make_plan(store, home=root, version="fixture0000000", results=results, db_bytes=1_000_000, db0_reserve=400_000)
    target = SqliteTarget(out)
    report = run_import(plan, target, budget=10**9, log=lambda m: None)
    target.close()
    reference = []
    for name, args in REFERENCE:
        r = runtime.call(name, args, max_chars=16000)
        reference.append({"name": name, "args": args, "ok": r["ok"], "result": r.get("result"), "error": r.get("error")})
    cases = alias_cases(runtime, home=root)
    runtime.h.corpus.store.close()
    info = {"report": report, "summary": summary(plan, statements=False), "clause": CLAUSE, "keys": [[t, k] for t, k, _ in keys],
            "reference": reference, "alias_cases": cases}
    (out / "fixture.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"fixture: {report['statements']} statements, {plan.databases} databases, {len(plan.chunks)} chunks, complete={report['complete']}")
    return info


# ------------------------------------------------------------------ the alias layer's cases
# A made-up layer for what the shipped one never shows (its names are no drug's): a stop name with drugs of its own,
# names beyond U+FFFF and a compatibility ideograph (code-point order), blockers with a window on either side and a
# chain, a shared name with a dated rival and anti-cues, a spelling, parts of the drug and of another, a candidate, an
# unattested name, a name holding a rival's, a name reached for three asked ones (``also`` in the order asked).
SYNTHETIC: list[dict[str, Any]] = [
    {"s": "甲木", "ho": "甲木", "n": 40, "fl": 1000, "b": ["子甲木", ["甲木丸", 1200, None]]},
    {"s": "子甲木", "b": ["癸子甲木"], "n": 1, "r": [{"h": "申酉", "k": "part_name", "src": ["syn"]}]},
    {"s": "乙草", "n": 12, "b": [["大乙草", 1000, None], "乙草根"], "r": [
        {"h": "甲木", "t": "herb:甲木", "c": ["甲木", "丙花"], "src": ["syn", "lexicon"],
         "w": [["syn.1", 500, 601, "e", 0], ["syn.2", None, 700, "g", 1]]},
        {"h": "卯辰", "st": "cue", "v": [None, 900], "a": ["午未"], "src": ["syn"], "w": [["syn.3", 700, None, "n", 1]]}]},
    {"s": "丙花", "n": 3, "r": [{"h": "甲木", "st": "cue", "c": ["甲木", "丁根"], "cr": ["本经", 25, 220], "src": ["syn"]}]},
    {"s": "𠀀丁", "n": 2, "r": [{"h": "甲木", "c": ["甲木", "𪚥"], "src": ["syn"]}]},
    {"s": "\uf900戊", "n": 2, "r": [{"h": "甲木", "src": ["syn"]}]},  # U+F900 sorts before 𠀀 (U+20000), not after
    {"s": "辛癸", "n": 2, "r": [{"h": "甲木", "k": "spelling", "st": "candidate", "src": ["syn"]}]},
    {"s": "乾坤", "n": 2, "r": [{"h": "𠀂", "src": ["syn"]}, {"h": "卯辰", "src": ["syn"]}]},  # a one-character head
    {"s": "辰巳", "ho": "辰巳", "n": 4, "r": [{"h": "甲木", "src": ["syn"]}]},  # heads a drug and names another
    {"s": "戊己庚汤", "stop": True, "n": 2, "r": [{"h": "卯辰", "src": ["syn"]}]},
    {"s": "卯丙", "n": 2, "r": [{"h": "卯辰", "k": "spelling", "src": ["syn"]}]},
    {"s": "寅卯", "n": 2, "r": [{"h": "辰午", "src": ["syn"]}]},
    {"s": "辰午", "n": 3, "r": [{"h": "未酉", "src": ["syn"]}, {"h": "未酉", "k": "spelling", "nt": "twice", "src": ["syn"]}]},
    {"s": "己庚", "n": 9, "r": [{"h": "甲木", "st": "candidate", "src": ["syn"]}]},
    {"s": "辛壬", "n": 4, "r": [{"h": "甲木", "k": "spelling", "st": "cue", "src": ["syn"]}]},
    {"s": "癸子", "n": 3, "r": [{"h": "甲木", "k": "part_name", "st": "cue", "src": ["syn"]}]},
    {"s": "丑寅", "n": 2, "ho": "甲木", "r": [{"h": "甲木", "k": "part_name", "src": ["syn"]}]},
    {"s": "卯辰", "ho": "卯辰", "n": 8},
    {"s": "巳午", "stop": True, "n": 5, "r": [{"h": "甲木", "src": ["syn"]}, {"h": "卯辰", "st": "candidate", "src": ["syn"]}]},
    {"s": "未申", "fl": 1300},
    {"s": "酉戌", "r": [{"h": "卯辰", "src": ["syn"]}]},
    {"s": "戌亥", "n": 6, "r": [{"h": "卯辰", "v": [1100, None], "src": ["syn"]}, {"h": "甲木", "v": [None, 1100], "src": ["syn"]}]},
    {"s": "甲木花", "n": 3, "r": [{"h": "卯辰", "src": ["syn"]}, {"h": "甲木", "st": "candidate", "src": ["syn"]}]},
    # what only a list of names gives (ntu40k): listed after the others, its candidates only where nothing else is
    # (at most three, a credited one first) and never by a name that heads a drug; no rival of the name's other drugs
    {"s": "亥子", "n": 5, "r": [{"h": "卯辰", "st": "candidate", "src": ["ntu40k"]}, {"h": "甲木", "src": ["syn"]},
                               {"h": "辰巳", "st": "cue", "src": ["ntu40k"]},
                               {"h": "未酉", "cr": ["本经", 25, 220], "src": ["ntu40k"]}]},
    {"s": "子丑", "n": 2, "r": [{"h": "卯辰", "st": "candidate", "src": ["ntu40k"]},
                               {"h": "甲木", "st": "candidate", "src": ["ntu40k"]},
                               {"h": "辰午", "st": "candidate", "cr": ["本经", 25, 220], "src": ["ntu40k"]},
                               {"h": "未酉", "st": "candidate", "src": ["ntu40k"]}]},
    {"s": "丑午", "n": 3, "r": [{"h": "甲木", "src": ["syn"]}, {"h": "卯辰", "st": "candidate", "src": ["ntu40k"]}]},
    {"s": "申戌", "ho": "申戌", "n": 2, "r": [{"h": "甲木", "st": "candidate", "src": ["ntu40k"]}]},
    # its own lexicon entry hides none of them (the view shows a name for nothing less): listed beside it
    {"s": "寅午", "n": 2, "r": [{"h": "卯辰", "st": "candidate", "src": ["ntu40k"]},
                               {"h": "甲木", "st": "candidate", "cr": ["本经", 25, 220], "src": ["ntu40k"]}]},
]
SYNTHETIC_HERBS = ["甲木", "卯辰", "申酉", "癸子", "𪚥"]
# its lexicon, as D1's lex table holds one ({surface: [entry …]} in lookup order): a name several entries file, out of
# term-id order (亥丑, 午申), and a formula among them; a member of a layer's group (丑寅) filed under another name
SYNTHETIC_LEXICON: dict[str, list[dict[str, Any]]] = {}
for _e in ({"id": "herb:甲木", "term": "甲木", "cat": "herb", "aliases": ["乙草"]},
           {"id": "formula:乙草", "term": "乙草", "cat": "formula"},
           {"id": "herb:午申", "term": "午申", "cat": "herb", "aliases": ["乙草", "坤乾"]},
           {"id": "herb:亥丑", "term": "亥丑", "cat": "herb", "aliases": ["乙草"], "synonyms": {"坤乾": "alias"}},
           {"id": "herb:丑寅", "term": "丑寅", "cat": "herb", "aliases": ["坤乾"]},
           {"id": "herb:卯辰", "term": "卯辰", "cat": "herb"}, {"id": "formula:卯辰甲", "term": "卯辰甲", "cat": "formula", "aliases": ["卯辰"]},
           {"id": "herb:寅午", "term": "寅午", "cat": "herb"}):
    for _s in [_e["term"], *_e.get("aliases", []), *_e.get("synonyms", {})]:
        SYNTHETIC_LEXICON.setdefault(_s, []).append(_e)
# the questions: asked and stop names (→ term id), the window, how many surfaces the query searches, its groups
SYNTHETIC_QUESTIONS: list[dict[str, Any]] = [
    {"asked": [["甲木", "herb:甲木"]]}, {"asked": [["乙草", None]]}, {"asked": [["乙草", "herb:甲木"]], "after": 1000},
    {"asked": [["甲木", None], ["乙草", None], ["丙花", None]], "surfaces": 3}, {"asked": [["卯辰", "herb:卯辰"]], "after": 1000},
    {"asked": [["卯辰", None]], "before": 800}, {"stops": [["巳午", None]]}, {"stops": [["巳午", "herb:甲木"]]},
    {"asked": [["𠀀丁", None], ["\uf900戊", None]], "surfaces": 2}, {"asked": [["甲木", None]], "surfaces": 27},
    {"asked": [["甲木", None]], "surfaces": 24, "groups": {"formula:甲卯": [["甲木", "卯辰"]], "formula:卯甲": [["卯辰", "甲木"]]}},
    {"asked": [["癸子", None]]}, {"asked": [["丑寅", "herb:甲木"]]}, {"asked": [["坤乾", None]]},
    {"asked": [["甲木花", None], ["戌亥", None]], "stops": [["巳午", None]], "after": 1050, "before": 1150, "surfaces": 2},
    {"asked": [["乾坤", None], ["辰巳", None]], "surfaces": 2}, {"asked": [["卯辰甲", "formula:卯辰甲"]]}, {"asked": [["寅卯", None]]},
    {"asked": [["亥子", None]]}, {"asked": [["子丑", None]]}, {"asked": [["申戌", None]]},
    {"asked": [["丑午", None], ["卯辰", None]], "surfaces": 2}, {"asked": [["寅午", "herb:寅午"]]},
]
SYNTHETIC_TEXTS: list[tuple[str, str, list[int | None] | None, list[int | None] | None]] = [
    ("癸子甲木", "甲木", None, None), ("子甲木", "甲木", None, None), ("甲木丸", "甲木", [1100, 1150], None),
    ("甲木丸", "甲木", [1300, 1300], None), ("大乙草", "乙草", [800, 850], None), ("大乙草", "乙草", [1100, 1100], None),
    ("乙草根乙草", "乙草", None, None), ("𠀀丁二两", "𠀀丁", None, None), ("𪚥甲木𠀀丁", "𠀀丁", [1000, 1000], None),
    ("乙草午未", "乙草", [700, 800], None), ("乙草", "乙草", [1000, 1000], None), ("乙草丙花", "乙草", [None, None], None),
    ("甲木", "甲木", [900, 950], [1000, 1100]), ("甲木", "甲木", [900, 950], None), ("未申", "未申", [1200, 1250], None),
    ("卯辰甲木花", "甲木花", None, None), ("甲木花一名卯辰", "甲木花", None, None), ("戌亥卯辰", "戌亥", [1200, 1300], None),
    ("戌亥甲木", "戌亥", [800, 900], None), ("甲木汤𠀀丁汤", "𠀀丁", None, None), ("巳午", "巳午", None, None),
    ("卯辰汤 乙草", "乙草", None, None), ("乙草（炒）", "乙草", None, None), ("戊己庚汤 乙草", "乙草", None, None),
    ("甲木", "甲木", [990, 1000], None),
    ("甲乙丙丁戊己庚辛汤 乙草", "乙草", None, None), ("辰巳", "辰巳", None, None), ("辰巳丙花", "辰巳", [500, 600], None),
    ("丑午三两", "丑午", None, None), ("丑午卯辰", "丑午", None, None),
]


def alias_cases(runtime: Any, *, home: str | Path | None = None, passages: int = 240, accepts: int = 240) -> dict[str, Any]:
    """What the alias layer's pure functions give in Python, for ``backup/aliases.js`` to reproduce: on the layer the
    runtime reads (the full-corpus profile's, which tables.js ships) — questions read with it, ``passages`` gate cases
    on the fixture's passages (a name it scans in each, a passage per name) besides the made-up ones, ``accepts``
    passages tried for the questions' expansions — and on :data:`SYNTHETIC`, the slots and the rounding."""
    import hashlib
    import math

    from ..config import find_home
    from ..evals.aliases_gold import heldout_surfaces, load_gold
    from ..plugins.classics.aliases import (
        CONTEXT_PATTERNS,
        AliasIndex,
        AliasRecord,
        _round4,
        assemble,
        gate_form,
    )

    root = find_home(str(home) if home else None)
    retriever = runtime.h.capabilities.get("retriever")
    pack, corpus, analyzer = retriever.pack, retriever.corpus, retriever.analyzer
    index, lex, norm = pack.aliases, pack.lexicon, pack.variants.normalize_text
    cfg = dict(retriever.alias)
    held = {norm(x) for x in heldout_surfaces(load_gold(root)) if x}

    def free(s: str) -> bool:  # neither a held-out gold name nor in one, nor holding one
        return not any(s == h or h in s or s in h for h in held)

    def rng(passage: Any) -> list[int | None] | None:
        r = corpus.year_range(passage)
        return None if r is None else [r.start, r.end]

    def query(q: Any) -> dict[str, Any]:
        ns = analyzer._drugs(q)
        return {"asked": [[s, t] for s, t in ns.asked.items()], "stops": [[s, t] for s, t in ns.stops.items()],
                "after": ns.after, "before": ns.before, "surfaces": ns.all_surfaces(), "groups": ns.groups}

    # the questions: the named ones and a sample of the layer's names (by the hash of the name)
    sample = sorted((s for s in index.records if free(s)), key=lambda s: hashlib.sha1(s.encode("utf-8")).hexdigest())
    named = [x for x in ALIAS_QUESTIONS if free(x)]
    questions = named + sample[:ALIAS_SAMPLE]
    questions += [f"唐以前的{s}" for s in sample[:ALIAS_SAMPLE:3]] + [f"{s}最早见于哪部书" for s in sample[1:ALIAS_SAMPLE:6]]
    analysed = [(text, analyzer.analyze(text, aliases=True, cfg=cfg)) for text in questions]
    expansions = [{"text": text, "q": query(q), "cfg": {}, "expansions": [_expansion(e) for e in q.expansions],
                   "view": q.alias_view, "referents": _referents(index, analyzer._drugs(q), lex)} for text, q in analysed]
    for extra in ALIAS_PARAMS:  # the ablations and other parameters, on the named questions
        expansions += [_expansions_case(index, analyzer._drugs(q), query(q), lex, cfg, extra, text)
                       for text, q in analysed[:len(named)]]
    searches = []
    for text, args in ALIAS_SEARCHES:
        q, _ = retriever.search(text, k=args["k"], routes=args.get("routes"), aliases="on",
                                alias_params=args.get("alias_params"))
        searches.append({"text": text, "k": args["k"], "routes": args.get("routes"), "cfg": args.get("alias_params") or {},
                         "q": query(q), "expansions": [_expansion(e) for e in q.expansions], "view": q.alias_view})
    # the gates: the made-up passages, then the fixture's
    gates = [_gate_case(index, gate_form(norm(text)), s, yr, edition, cfg) for text, s, yr, edition in ALIAS_TEXTS]
    done, texts = set(), []
    for passage in sorted(corpus.iter_passages(), key=lambda x: x.id):
        n = retriever.norm(passage.id)
        texts.append((n, rng(passage)))
        edition = passage.temporal.t_edition
        for _, _, s in index.scan(n):
            if s not in done and free(s) and len(gates) < len(ALIAS_TEXTS) + passages:
                done.add(s)
                gates.append(_gate_case(index, gate_form(n), s, rng(passage), [edition.start, edition.end] if edition else None,
                                        cfg))
    # accept and bare: the questions' expansions on the made-up passages and on the fixture's that write them (and none
    # of the question's surfaces, as the side queue reads them)
    made_up = [(norm(text), yr) for text, _, yr, _ in ALIAS_TEXTS]
    accept = []
    for text, q in analysed:
        own = [x for x in (norm(s) for s in q.all_surfaces()) if x]
        for e in q.expansions:
            if free(e.surface) and (len(accept) < accepts or text in named):
                tried = [(n, yr) for n, yr in made_up if e.surface in n]
                tried += [(n, yr) for n, yr in texts if e.surface in n and not any(s in n for s in own)][:2]
                accept += [_accept_case(index, gate_form(n), e, yr, cfg) for n, yr in tried]
    asked = [s for _, q in analysed[:len(named)] for s in [*q.asked, *q.stops] if index.record(s) is not None]
    records = [_record_case(index, s) for s in [*dict.fromkeys(asked), *sample[:ALIAS_SAMPLE]]]
    scan = [[norm(x), index.scan(norm(x))] for x in [*(t for t, *_ in ALIAS_TEXTS), *named]]
    scan += [[n, index.scan(n)] for n, _ in texts[:: max(1, len(texts) // 60)]]

    # the made-up layer, without a lexicon
    context = {**CONTEXT_PATTERNS, "herbs": SYNTHETIC_HERBS}
    syn = AliasIndex([AliasRecord.from_json(r) for r in SYNTHETIC], context=context,
                     headers=[{"sources": ["syn", "ntu40k"], "labels": {"syn": "合成", "ntu40k": "名表"}}])
    synthetic: dict[str, Any] = {"records": {r["s"]: {k: v for k, v in r.items() if k != "s"} for r in SYNTHETIC},
                                 "context": context, "sources": [{"id": "syn", "label": "合成"},
                                                                  {"id": "lexicon", "label": "词表"},
                                                                  {"id": "ntu40k", "label": "名表"}]}
    synthetic["lexicon"] = SYNTHETIC_LEXICON
    lexicon = _Lexicon(SYNTHETIC_LEXICON)
    synthetic["expansions"] = []
    for question in SYNTHETIC_QUESTIONS:
        asked, stops = question.get("asked", []), question.get("stops", [])
        surfaces = [a for a, _ in asked] + [f"填{i}" for i in range(question.get("surfaces", 1) - len(asked))]
        ns = SimpleNamespace(asked=dict(map(tuple, asked)), stops=dict(map(tuple, stops)), after=question.get("after"),
                             before=question.get("before"), all_surfaces=lambda surfaces=surfaces: list(surfaces),
                             groups=question.get("groups", {}))
        for extra in ({}, {"ablate": ["gates"]}, {"ablate": ["period"]}, {"expansions": 2}, {"witness_scope": "web"}):
            synthetic["expansions"].append({**_expansions_case(syn, ns, None, lexicon, cfg, extra, "synthetic"), "lexicon": True})
        synthetic["expansions"].append({**_expansions_case(syn, ns, None, None, cfg, {}, "synthetic"), "lexicon": False})
    synthetic["gates"] = [_gate_case(syn, gate_form(text), s, yr, edition, cfg) for text, s, yr, edition in SYNTHETIC_TEXTS]
    tried: dict[str, Any] = {}  # each expansion (as a question gives it) on each made-up passage that writes it, once
    for case in synthetic["expansions"]:
        for e in case["expansions"] if not case["cfg"] and case["lexicon"] else ():
            for text, _, yr, _ in SYNTHETIC_TEXTS:
                if e["surface"] in text:
                    tried.setdefault(json.dumps([e, text, yr], ensure_ascii=False), (e, text, yr))
    synthetic["accept"] = [_accept_case(syn, gate_form(text), _from_json(e), yr, cfg) for e, text, yr in tried.values()]
    synthetic["record_cases"] = [_record_case(syn, r["s"]) for r in SYNTHETIC]
    synthetic["scan"] = [[text, syn.scan(text)] for text, *_ in SYNTHETIC_TEXTS]

    slots = [{"M": list(range(100, 100 + m)), "S": list(range(200, 200 + n)), "k": k, "num": num, "den": den,
              "out": assemble(list(range(100, 100 + m)), list(range(200, 200 + n)), k, num, den)}
             for m in (0, 3, 12) for n in (0, 2, 9) for k in (1, 3, 4, 10, 25) for num, den in ((3, 10), (0, 1), (1, 2), (2, 3))]
    rounding = [[x, _round4(x)] for x in (0.65625, 0.00005, 0.00015, 0.12345, 1 / 3, 2 / 3, 0.5, 0.99995, 0.999949,
                                           0.483333, 0.25, 1.0, 0.0, 2.5e-05, 0.6666500000000001, math.pi / 4)]
    forms = ["将军（酒洗）三两", "abc 12; 甘草。𠀀x", "国老\n即甘草", "𠀀😀〇〓ａ", ""]
    return {"params": cfg, "gate_form": [[x, gate_form(x)] for x in forms], "scan": scan, "gates": gates, "accept": accept,
            "expansions": expansions, "searches": searches, "records": records, "synthetic": synthetic, "assemble": slots,
            "round4": rounding}


class _Lexicon:
    """A lexicon of entries as D1's lex table holds them ({surface: [entry …]}, entries {id, term, cat, aliases,
    synonyms}), read as ``domain.Lexicon`` is — lookup in the order given, resolve by id or by surface, entry by id —
    and as ``backup/lexicon.js`` reads the same buckets."""

    def __init__(self, by_surface: dict[str, list[dict[str, Any]]]) -> None:
        def entry(e: dict[str, Any]) -> Any:
            forms = [e["term"], *e.get("aliases", []), *e.get("synonyms", {})]
            return SimpleNamespace(term_id=e["id"], term=e["term"], category=e["cat"], surfaces=lambda: list(forms))

        self.entries = {e["id"]: entry(e) for es in by_surface.values() for e in es}
        self.by_surface = {s: [self.entries[e["id"]] for e in es] for s, es in by_surface.items()}

    def lookup(self, surface: str) -> list[tuple[Any, None]]:
        return [(e, None) for e in self.by_surface.get(surface, [])]

    def entry(self, term_id: str) -> Any:
        return self.entries.get(term_id)

    def resolve(self, surface_or_id: str, category: str | None = None) -> Any:
        if surface_or_id in self.entries:
            return self.entries[surface_or_id]
        return next((e for e, _ in self.lookup(surface_or_id) if category is None or e.category == category), None)


def _window(w: Any) -> list[Any] | None:
    return None if w is None else list(w)


def _referent(ref: Any) -> dict[str, Any]:
    """A referent with its defaults filled in, as aliases.js holds one."""
    return {"h": ref.h, "g": ref.g, "t": ref.t, "k": ref.k, "st": ref.st, "v": _window(ref.v), "c": list(ref.c),
            "a": list(ref.a), "src": list(ref.src), "w": [w.to_json() for w in ref.w], "cr": _window(ref.cr)}


def _expansion(e: Any) -> dict[str, Any]:
    """An expansion as aliases.js holds one (``for_`` is ``for``, a witness the file's row)."""
    return {"surface": e.surface, "for": e.for_, "direction": e.direction, "group": e.group, "head": e.head,
            "kind": e.kind, "status": e.status, "valid": _window(e.valid), "shared": e.shared, "cues": list(e.cues),
            "own": list(e.own), "rivals": [[_window(w), list(names)] for w, names in e.rivals], "src": list(e.src),
            "wit": [w.to_json() for w in e.wit], "n": e.n, "searched": e.searched, "why": e.why, "also": list(e.also)}


def _from_json(d: dict[str, Any]) -> Any:
    from ..plugins.classics.aliases import Expansion, Witness

    return Expansion(d["surface"], d["for"], d["direction"], d["group"], d["head"], kind=d["kind"], status=d["status"],
                     valid=None if d["valid"] is None else tuple(d["valid"]), shared=d["shared"], cues=list(d["cues"]),
                     own=list(d["own"]), rivals=[(None if w is None else tuple(w), list(n)) for w, n in d["rivals"]],
                     src=list(d["src"]), wit=[Witness.from_json(w) for w in d["wit"]], n=d["n"], searched=d["searched"],
                     why=d["why"], also=list(d["also"]))


def _expansions_case(index: Any, ns: Any, shown: dict[str, Any] | None, lex: Any, cfg: dict[str, Any],
                     extra: dict[str, Any], text: str) -> dict[str, Any]:
    """A question's expansions and view under ``cfg`` and ``extra`` (``shown``: the question as the case gives it)."""
    p = {**cfg, **extra}
    exps = index.expansions(ns, lex, p)
    if shown is None:
        shown = {"asked": [[s, t] for s, t in ns.asked.items()], "stops": [[s, t] for s, t in ns.stops.items()],
                 "after": ns.after, "before": ns.before, "surfaces": ns.all_surfaces(), "groups": ns.groups}
    return {"text": text, "q": shown, "cfg": extra, "expansions": [_expansion(e) for e in exps],
            "view": index.view(ns, p, lex, exps), "referents": _referents(index, ns, lex)}


def _referents(index: Any, ns: Any, lex: Any) -> list[list[Any]]:
    """The drugs each asked name may name, and each stop name asked on its own."""
    return ([[s, False, [_referent(r) for r in index.referents(s, t, lex)]] for s, t in ns.asked.items()]
            + [[s, True, [_referent(r) for r in index.referents(s, t, lex, stop=True)]] for s, t in ns.stops.items()])


def _gate_case(index: Any, g: str, s: str, yr: Any, edition: Any, cfg: dict[str, Any]) -> dict[str, Any]:
    """The gates on a passage for one name: its free offsets (and every blocker written there, at each occurrence), the
    blocker a demoted occurrence stands in, drug context and naming (at the free offsets and at every one), the
    reading, the floor's flag."""
    from ..plugins.retrieval.hybrid import _covering

    rec = index.record(s)
    blockers = [b if isinstance(b, str) else list(b) for b in (rec.b if rec is not None else [])]
    cues = sorted({c for r in (rec.r if rec is not None else ()) if r.st != "candidate" for c in r.c})
    offs = index.free_offsets(g, s, blockers, yr)
    every = [i for i in range(len(g)) if g.startswith(s, i)]
    written = [b if isinstance(b, str) else b[0] for b in blockers]
    ref, p = index.reading(g, s, yr, cfg=cfg)
    return {"g": g, "s": s, "yr": yr, "edition": edition, "b": blockers, "cues": cues, "out": {
        "free": offs,
        "covers": [[i, b, index.covers(g, i, s, b, yr)] for i in every for b in written if s in b and b != s and b in g],
        "covering": _covering(index, g, s, blockers, yr), "context": index.drug_context(g, s, offs, cues, cfg=cfg),
        "named": index.named(g, s, offs, cues, cfg=cfg), "context_every": index.drug_context(g, s, every, cues, cfg=cfg),
        "reading": [ref.h if ref else None, ref.g if ref else None, p], "floor": index.floor_flag(s, yr, edition)}}


def _accept_case(index: Any, g: str, e: Any, yr: Any, cfg: dict[str, Any]) -> dict[str, Any]:
    """The side queue's gates and order for an expansion on a passage, and with the gates and windows lifted."""
    return {"g": g, "yr": yr, "exp": _expansion(e), "out": list(index.accept(g, e, yr, cfg=cfg)),
            "lifted": list(index.accept(g, e, yr, cfg={**cfg, "ablate": ["gates", "period"]})),
            "bare": index.bare(g, e, yr, cfg=cfg)}


def _record_case(index: Any, s: str) -> dict[str, Any]:
    """What the index reads of a record: its readings, its groups' names and members, the groups its term belongs to."""
    rec = index.record(s)
    groups = sorted({r.g for r in rec.r} | ({rec.ho} if rec.ho else set()))
    return {"s": s, "readings": [_referent(r) for r in index.readings(s)], "names": {g: index.names(g) for g in groups},
            "groups_for": index.groups_for(rec.r[0].t if rec.r else None, [s]),
            "by_group": {g: [a for a, _ in index.by_group(g)] for g in groups}}
