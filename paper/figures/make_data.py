"""Source data for the TaoChronos (道乃久) figures — every number a figure draws is written here first.

    python paper/figures/make_data.py                 # everything (builds the 要籍语料 store in a temporary directory)
    python paper/figures/make_data.py --canon-data D  # reuse a data directory whose corpus/tcm.sqlite is the 要籍语料 store
    python paper/figures/make_data.py --eval-json F   # reuse a `taochronos eval -o F` run instead of running the suites
    python paper/figures/make_data.py --research-value  # also re-run research_value on the 要籍语料 (about 4 minutes)

What comes from where:

* the corpus catalogs (``corpus/catalog/*.yaml``): the 966 admitted witnesses, their dates, categories and dating basis;
* ``corpus/catalog/canon.yaml``: the 350 works of the canon ranked by the citation network;
* ``corpus/catalog/images/*.csv``: the 10 001 image-witness records of eleven collections;
* ``corpus/web``: the 要籍语料 (348 works, 368 witnesses, 135 083 passages) the site carries, built into a store on which
  the study layer runs (``study names`` · ``study term`` · ``study pairs`` · ``study citations``);
* ``taochronos eval`` on the demonstration corpus: invariants, hard interpretive cases, hallucination probes and the other
  suites (``eval_demo_corpus.json``);
* the harness itself (``agents``, ``skills/manifests``, the tool mesh, hooks, gates and the event-authority table):
  ``fig1_architecture.json``; and one research question run end to end on the 要籍语料 (``e2e_case.py``);
* ``docs/evals.md``: the full-corpus research-value benchmark and the blind rounds of the interpretive suite, which need
  the full corpus store (not distributed) — transcribed into ``research_value_full_corpus.json`` and
  ``interpretive_rounds.csv`` with the page they come from.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

import yaml

HOME = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = HERE / "source_data"

PERIODS = [("Qin–Han", "先秦两汉", -475, 220), ("Wei–Jin", "魏晋南北朝", 220, 581), ("Sui–Tang", "隋唐五代", 581, 960),
           ("Song–Jin–Yuan", "宋金元", 960, 1368), ("Ming", "明", 1368, 1644), ("Qing", "清", 1644, 1912),
           ("Republican", "民国", 1912, 1950)]

SOURCE_FAMILY = {"kanripo": "Siku quanshu (Kanripo)", "jicheng": "JiCheng editions", "cmeta": "Collated witnesses",
                 "mcgill": "Collated witnesses", "aeam": "Collated witnesses", "wikisource": "Wikisource and web",
                 "tcm-ancient-books": "Wikisource and web", "tcmoc": "Wikisource and web",
                 "hf-tcm-canon": "Wikisource and web"}

DATING_BASIS = [("curated", "Curated by the editors"), ("western", "Year stated in the book record"),
                ("preface", "Signed preface or colophon"), ("author", "Author's other works or life"),
                ("witness", "Another witness of the work"), ("dynasty", "Dynasty only"),
                ("undated", "Undated (counted as Qing)")]


def dating_class(src: str, basis: str | None) -> str:
    if src == "kanripo":
        return "curated"  # the Kanripo catalog is dated by hand (corpus/catalog/kanripo-kr3e.yaml)
    b = (basis or "").split(":")[0]
    if b in ("curated", "western", "undated", "dynasty"):
        return b
    if b in ("preface",):
        return "author" if (basis or "").endswith(":author") else "preface"
    if b in ("author",):
        return "author"
    if b in ("jicheng", "kanripo", "cmeta", "wikisource", "mcgill", "aeam", "work"):
        return "witness"
    return "curated" if not b else "witness"


def write_csv(name: str, rows: list[dict], fields: list[str] | None = None) -> None:
    fields = fields or list(rows[0].keys())
    with open(OUT / name, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"  {name}: {len(rows)} rows")


def load_yaml(path: Path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# 1. the corpus ------------------------------------------------------------------------------------------------------------
def corpus_works() -> None:
    rows = []
    kr = load_yaml(HOME / "corpus/catalog/kanripo-kr3e.yaml")
    for b in kr["books"]:
        rows.append({"source": "kanripo", "id": b["id"], "title": b["title"], "work": b.get("work"),
                     "dynasty": b.get("dynasty"), "comp_lo": b["composition"][0], "comp_hi": b["composition"][1],
                     "category": b.get("category"), "dating_basis": "kanripo-curated", "modern": False})
    for src in ("jicheng", "mcgill", "cmeta", "aeam", "wikisource", "tcm-ancient-books", "tcmoc", "hf-tcm-canon"):
        cat = load_yaml(HOME / f"corpus/catalog/{src}.yaml")
        for b in cat["books"]:
            if b.get("status") != "ingest":
                continue
            rows.append({"source": src, "id": b["id"], "title": b["title"], "work": b.get("work"),
                         "dynasty": b.get("dynasty"), "comp_lo": b["composition"][0], "comp_hi": b["composition"][1],
                         "category": b.get("category"), "dating_basis": b.get("dating"), "modern": bool(b.get("modern"))})
    for r in rows:
        r["source_family"] = SOURCE_FAMILY[r["source"]]
        r["dating_class"] = dating_class(r["source"], r["dating_basis"])
    write_csv("fig2_corpus_witnesses.csv", rows,
              ["source", "source_family", "id", "title", "work", "dynasty", "comp_lo", "comp_hi", "category",
               "dating_basis", "dating_class", "modern"])


def _canon_years(s: str) -> tuple[int, int]:
    s = str(s)
    parts = [p.strip() for p in s.split("–")]
    vals = [-int(p[1:]) if p.startswith("前") else int(p) for p in parts]
    return (vals[0], vals[-1])


CANON_EN = {"suwen": "Suwen", "lingshu": "Lingshu", "jinkui": "Jingui yaolüe", "nanjing": "Nanjing",
            "shanghanlun": "Shanghan lun", "shennong": "Shennong bencao jing", "qianjin": "Qianjin yaofang",
            "maijing": "Maijing", "jiayi": "Zhenjiu jiayi jing", "waitai": "Waitai miyao", "zhouhou": "Zhouhou beiji fang",
            "hejiju": "Hejiju fang", "zhubing": "Zhubing yuanhou lun", "bencao_gangmu": "Bencao gangmu",
            "shengji_zonglu": "Shengji zonglu", "sanyin": "Sanyin fang", "yizong_jinjian": "Yizong jinjian"}


def canon_works() -> None:
    c = load_yaml(HOME / "corpus/catalog/canon.yaml")
    rows = []
    for w in c["works"]:
        lo, hi = _canon_years(w["composition"])
        rows.append({"rank": w["rank"], "work": w["work"], "title": w["title"], "title_en": CANON_EN.get(w["work"], ""),
                     "dynasty": w["dynasty"], "comp_lo": lo, "comp_hi": hi, "year_mid": (lo + hi) / 2,
                     "category": w["category"], "score": w["score"], "cited_by": w["cited_by"], "periods": w["periods"],
                     "citations": w["citations"], "witnesses": w["witnesses"], "siku": w["siku"], "open": w["open"]})
    write_csv("fig2_canon_350.csv", rows)


def image_collections() -> None:
    per: dict[str, dict] = {}
    for p in sorted((HOME / "corpus/catalog/images").glob("*.csv")):
        with open(p, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                key = r["source"]
                d = per.setdefault(key, {"source": key, "holder": r["holder"], "collection": r["collection"],
                                         "records": 0, "linked_to_corpus": 0, "dated": 0, "manuscripts": 0,
                                         "prints": 0, "iiif_manifest": 0, "works_linked": set()})
                d["records"] += 1
                d["dated"] += bool(r["years"])
                d["manuscripts"] += r["kind"] == "写"
                d["prints"] += r["kind"] == "刊"
                d["iiif_manifest"] += bool(r["manifest"])
                if r["work"]:
                    d["linked_to_corpus"] += 1
                    d["works_linked"].add(r["work"])
    rows = []
    for d in per.values():
        d["works_linked"] = len(d["works_linked"])
        rows.append(d)
    rows.sort(key=lambda d: -d["records"])
    write_csv("extfig_image_collections.csv", rows)


def web_corpus() -> None:
    books = json.load(open(HOME / "corpus/web/books.json", encoding="utf-8"))
    rows = []
    for b in books:
        ex = b.get("excerpt") or {}
        rows.append({"witness": b["id"], "work": b["work"], "rank": b["rank"], "source": b["source"],
                     "witness_no": b["witness"], "chars_kept": ex.get("kept_chars"), "chars_witness": ex.get("chars"),
                     "whole": ex.get("whole")})
    write_csv("extfig_web_canon_witnesses.csv", rows)


# 2. the evaluation suites -------------------------------------------------------------------------------------------------
def eval_suites(eval_json: Path | None) -> None:
    dest = OUT / "eval_demo_corpus.json"
    if eval_json is None:
        print("  running `taochronos eval` on the demonstration corpus (about a minute) …")
        env = {k: v for k, v in os.environ.items() if k != "TAOCHRONOS_DATA"}
        with tempfile.TemporaryDirectory() as tmp:
            env["TAOCHRONOS_DATA"] = tmp  # no corpus store here: the demonstration corpus, as in CI
            subprocess.run([sys.executable, "-m", "taochronos", "eval", "-o", str(dest)], check=True, env=env,
                           cwd=HOME, stdout=subprocess.DEVNULL)
    elif eval_json.resolve() != dest.resolve():
        shutil.copyfile(eval_json, dest)
    r = json.load(open(dest, encoding="utf-8"))
    cases = [{"id": d["id"], "class": d["class"], "split": d["split"], "correct": d["correct"], "unsafe": d["unsafe"],
              "expected": json.dumps(d.get("expected"), ensure_ascii=False), "got": d.get("got")}
             for d in r["interpretive"]["details"]]
    write_csv("fig4_interpretive_cases.csv", cases)
    inv = [{k: d[k] for k in ("id", "probe", "invariant", "boundary", "held", "observed")} for d in r["invariants"]["details"]]
    write_csv("fig4_invariants.csv", inv)
    h = r["hallucination"]["metrics"]
    n = hallucination_counts()
    rows = [("Verbatim quotation accepted", "verbatim", h["verbatim_recall"]),
            ("One character replaced", "perturbed", h["perturbed_detection"]),
            ("Random characters (fabricated)", "fabricated", h["fabricated_detection"]),
            ("Verbatim text at a shifted span", "span", h["wrong_span_detection"])]
    out = []
    for label, key, rate in rows:
        k, total = n[key]
        assert abs(k / total - rate) < 1e-4, (key, k, total, rate)
        out.append({"probe": label, "passed": k, "n": total, "rate": rate})
    write_csv("fig4_hallucination.csv", out)


def hallucination_counts() -> dict[str, tuple[int, int]]:
    """The hallucination suite reports rates; its exact counts, by the suite's own procedure and seed
    (``taochronos.evals.suites.hallucination``), for the intervals of Fig. 4."""
    import random

    sys.path.insert(0, str(HOME / "src"))
    from taochronos.evals.base import EvalContext
    from taochronos.protocol.evidence import EvidenceRecord
    from taochronos.verification.provenance import find_quote, verify_evidence

    with tempfile.TemporaryDirectory() as tmp:
        h = EvalContext(home=HOME, data_dir=tmp).default
        corpus, normalize = h.corpus, h.pack.variants.normalize_text
        rng = random.Random(7)
        passages = [p for p in corpus.passages() if len(p.text) >= 24]
        rng.shuffle(passages)
        alphabet = sorted({ch for p in corpus.passages() for ch in p.text if "一" <= ch <= "鿿"})
        s = {k: [0, 0] for k in ("verbatim", "perturbed", "fabricated", "span")}
        for p in passages[:60]:
            n = rng.randint(8, min(20, len(p.text) - 1))
            start = rng.randint(0, len(p.text) - n)
            quote = p.text[start: start + n]
            s["verbatim"][1] += 1
            s["verbatim"][0] += bool(find_quote(corpus, quote, normalize))
            i = rng.randrange(len(quote))
            rep = next(ch for ch in rng.sample(alphabet, 40) if ch not in p.text and normalize(ch) != normalize(quote[i]))
            s["perturbed"][1] += 1
            s["perturbed"][0] += not find_quote(corpus, quote[:i] + rep + quote[i + 1:], normalize)
            fabricated = "".join(rng.sample(alphabet, n))
            s["fabricated"][1] += 1
            s["fabricated"][0] += not find_quote(corpus, fabricated, normalize)
            shift = min(len(p.text) - n, start + 3) if start + 3 <= len(p.text) - n else max(0, start - 3)
            if shift != start:
                rec = EvidenceRecord(id="evd_test", passage_id=p.id, book_id=p.book_id, locator=p.locator, quote=quote,
                                     start=shift, end=shift + n, agent="eval", retrieval_method="test")
                s["span"][1] += 1
                s["span"][0] += bool(verify_evidence(rec, corpus))
    return {k: (v[0], v[1]) for k, v in s.items()}


INTERPRETIVE_ROUNDS = [  # docs/evals.md, "The first two layers": the blind rounds as they happened
    {"round": "Round 1", "cases": 53, "correct": 43, "unsafe": 4, "note": "60 cases written together, 53 held out"},
    {"round": "Round 2", "cases": 32, "correct": 30, "unsafe": 1, "note": "written after round 1, before its changes ran"},
    {"round": "Round 3", "cases": 10, "correct": 7, "unsafe": 3, "note": "before the crux registry"},
    {"round": "Round 4", "cases": 5, "correct": 5, "unsafe": 0, "note": "written after the changes, before they ran"},
    {"round": "Held-out now", "cases": 84, "correct": 82, "unsafe": 2, "note": "all held-out cases on the current rules"},
]

RESEARCH_VALUE = {  # docs/evals.md, "Research value (full corpus)"
    "source": "docs/evals.md § Research value (full corpus); taochronos eval research_value on the full-corpus store",
    "cutoffs": [1127, 1368],
    "topic_cutoff_pairs_read": 230,
    "topic_cutoff_pairs_scored": 189,
    "candidates": 29467,
    "came_true": 1314,
    "base_rate": 0.045,
    "rankers": [
        {"ranker": "Adamic–Adar (D4)", "p10": 0.168, "p10_lo": 0.152, "p10_hi": 0.185, "p20": 0.131, "p20_lo": 0.120,
         "p20_hi": 0.142, "map": 0.199, "map_lo": 0.175, "map_hi": 0.222},
        {"ranker": "Common neighbours", "p10": 0.170, "p10_lo": 0.154, "p10_hi": 0.188, "p20": 0.133, "p20_lo": 0.123,
         "p20_hi": 0.145, "map": 0.208, "map_lo": 0.185, "map_hi": 0.232},
        {"ranker": "Resource allocation", "p10": 0.149, "p10_lo": 0.134, "p10_hi": 0.166, "p20": 0.118, "p20_lo": 0.108,
         "p20_hi": 0.129, "map": 0.175, "map_lo": 0.154, "map_hi": 0.197},
        {"ranker": "Popularity", "p10": 0.134, "p10_lo": 0.119, "p10_hi": 0.150, "p20": 0.101, "p20_lo": 0.092,
         "p20_hi": 0.111, "map": 0.143, "map_lo": 0.126, "map_hi": 0.161},
        {"ranker": "Chance (20 draws)", "p10": 0.054, "p10_lo": None, "p10_hi": None, "p20": 0.055, "p20_lo": None,
         "p20_hi": None, "map": 0.092, "map_lo": None, "map_hi": None},
    ],
    "paired": [
        {"comparison": "Adamic–Adar vs popularity", "cutoff": "all", "better": 149, "worse": 39, "tie": 1, "p": 2.4e-16},
        {"comparison": "Adamic–Adar vs popularity", "cutoff": "1127", "better": 73, "worse": 21, "tie": None, "p": None},
        {"comparison": "Adamic–Adar vs popularity", "cutoff": "1368", "better": 76, "worse": 18, "tie": None, "p": None},
        {"comparison": "Popularity vs chance", "cutoff": "all", "better": 116, "worse": 73, "tie": None, "p": 0.002},
    ],
    "end_to_end_heldout": [  # 1368, rules only, held-out topics 胸痹 霍乱 虚劳 痰饮; before/after the absence checks
        {"prediction": "Lost association stays absent (D1)", "held_before": 4, "n_before": 9, "held_after": 4, "n_after": 9,
         "note": "the 2 rejected by the new checks were both wrong; 4/7 of those surviving hold"},
        {"prediction": "Association rule holds", "held_before": 1, "n_before": 7, "held_after": 1, "n_after": 7, "note": ""},
        {"prediction": "Hidden association comes true (D4)", "held_before": 4, "n_before": 8, "held_after": 4, "n_after": 8,
         "note": "2 new; the 2 already written before the cutoff are now rejected (attested)"},
        {"prediction": "Surviving predictions that are discoveries", "held_before": 7, "n_before": 23, "held_after": 7,
         "n_after": 19, "note": "true and new; Wilson 95% CI 0.19–0.59 after"},
    ],
    "leakage": 0,
}


def generalization() -> None:
    """Development (or constructed) data against held-out (or real-corpus) data, capability by capability: from this
    run of the suites where the demonstration corpus holds both, else from docs/evals.md (full corpus, marked)."""
    r = json.load(open(OUT / "eval_demo_corpus.json", encoding="utf-8"))
    m = lambda s: r[s]["metrics"]  # noqa: E731
    rows = [
        ("Hard interpretive readings", "accuracy", "development, 23 cases", m("interpretive")["dev"]["accuracy"],
         "held-out, 84 cases", m("interpretive")["heldout"]["accuracy"], "eval", "eval"),
        ("Entities, 24 types", "F1", "development, 41 sentences", m("entities")["development"]["f1"],
         "held-out, 25 sentences", m("entities")["held_out"]["f1"], "eval", "eval"),
        ("Ancient phenotypes → HPO", "F1", "development, 20 cases", m("bridge")["phenotypes"]["f1"],
         "12 random passages, annotated first", 0.822, "eval", "docs/evals.md (full corpus)"),
        ("Senses of a term", "labelling accuracy", "synthetic shift", m("senses")["labelling_accuracy"],
         "curated exemplars of 消渴", 6 / 8, "eval", "eval"),
        ("Named disputes", "accuracy", "development, 22 sentences", m("disputes")["accuracy"],
         "known controversies", 3 / 3, "eval", "docs/evals.md (full corpus)"),
        ("School doctrines", "recall", "synthetic school (planted, top 2)", m("schools")["synthetic"]["planted_top2"],
         "44 textbook doctrines", 0.73, "eval", "docs/evals.md (full corpus)"),
        ("Case records", "outcome accuracy", "development, 6 records", m("cases")["outcome_accuracy"],
         "two transcriptions agree", 0.92, "eval", "docs/evals.md (full corpus)"),
        ("Lost-text fragments", "precision", "constructed lost work", m("fragments")["precision"],
         "Qianjin yaofang, real", 0.32, "eval", "docs/evals.md (full corpus)"),
        ("Discoveries among surviving predictions", "proportion", "development topics, 8", 1 / 8,
         "held-out topics, 19", 7 / 19, "docs/evals.md (full corpus)", "docs/evals.md (full corpus)"),
    ]
    write_csv("extfig_generalization.csv", [
        {"capability": a, "metric": b, "dev_label": c, "dev_value": round(d, 4), "test_label": e,
         "test_value": round(f, 4), "dev_source": g, "test_source": h} for a, b, c, d, e, f, g, h in rows])
    p = m("punctuation")
    write_csv("extfig_punctuation.csv", [
        {"setting": "Demonstration corpus, 22 works, 4-fold", "model": p["boundary_f1"], "rules": p["rules_boundary_f1"],
         "source": "eval"},
        {"setting": "55 held-out works (104 k characters)", "model": 0.767, "rules": 0.235,
         "source": "docs/evals.md (full corpus)"},
        {"setting": "Siku 白文, 4 works", "model": 0.780, "rules": 0.303, "source": "docs/evals.md (full corpus)"},
    ])
    a = m("ablations")
    write_csv("extfig_ablations.csv", [
        {"test": "Earliest attestation", "condition": "all retrieval routes", "value": a["retrieval_routes"]["all"], "n": 6},
        {"test": "Earliest attestation", "condition": "without the variant route", "value": a["retrieval_routes"]["no_variant"], "n": 6},
        {"test": "Earliest attestation", "condition": "without the sense route", "value": a["retrieval_routes"]["no_sense"], "n": 6},
        {"test": "Earliest attestation", "condition": "BM25 only", "value": a["retrieval_routes"]["bm25_only"], "n": 6},
        {"test": "Earliest attestation", "condition": "dense only", "value": a["retrieval_routes"]["dense_only"], "n": 6},
        {"test": "Contradiction typing", "condition": "full reader", "value": a["contradiction_context"]["full"], "n": 12},
        {"test": "Contradiction typing", "condition": "without sense resolution",
         "value": a["contradiction_context"]["no_sense_resolution"], "n": 12},
        {"test": "Contradiction typing", "condition": "without philology", "value": a["contradiction_context"]["no_philology"],
         "n": 12},
        {"test": "Context tokens", "condition": "Context OS view", "value": a["context_os"]["view_tokens"], "n": None},
        {"test": "Context tokens", "condition": "naive dump", "value": a["context_os"]["naive_dump_tokens"], "n": None},
        {"test": "Hypotheses surviving review", "condition": "with the Skeptic", "value": a["skeptic"]["survived_with_skeptic"],
         "n": None},
        {"test": "Hypotheses surviving review", "condition": "without the Skeptic",
         "value": a["skeptic"]["survived_without_skeptic"], "n": None},
    ])


def documented() -> None:
    generalization()
    write_csv("fig4_interpretive_rounds.csv", INTERPRETIVE_ROUNDS)
    (OUT / "fig5_research_value_full_corpus.json").write_text(json.dumps(RESEARCH_VALUE, ensure_ascii=False, indent=1),
                                                                encoding="utf-8")
    print("  fig5_research_value_full_corpus.json (transcribed from docs/evals.md)")


# 3. the study layer on the 要籍语料 -----------------------------------------------------------------------------------------
STUDY = [
    ("names_shanyao.json", ["names", "山药"]),
    ("names_xuanshen.json", ["names", "玄参"]),
    ("term_wenbing.json", ["term", "温病"]),
    ("citations.json", ["citations"]),
]
# `study pairs` lists the 60 strongest significant pairs; the figure needs every one, so it is called with top raised
PAIRS = """
import json, sys
from taochronos.bootstrap import Harness
h = Harness.from_profile("web-canon", home=sys.argv[1], data_dir=sys.argv[2])
res = h.capabilities.get("study").pairs(None, top=100000)
json.dump(res, open(sys.argv[3], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
"""


# the harness as it is configured: agents, skills, tools with the permission each needs, hooks, gates, event authority
ARCH = """
import json, sys
from pathlib import Path
import yaml
from taochronos.bootstrap import Harness
from taochronos.kernel.authority import EVENT_AUTHORITY, WHY
from taochronos.kernel.hooks import HookPoint
from taochronos.verification.gates import GATE_NAMES
home = Path(sys.argv[1])
h = Harness.from_profile("web-canon", home=home, data_dir=sys.argv[2])
load = lambda f: yaml.safe_load(f.read_text(encoding="utf-8"))
keys = ("role", "name", "description", "mode", "permissions", "tools", "skills", "output_schema", "model", "budget")
out = {
    "agents": [{k: load(f).get(k) for k in keys} for f in sorted((home / "agents").glob("*.yaml"))],
    "core_agents": [load(f) for f in sorted((home / "agents" / "core").glob("*.yaml"))],
    "skills": [{k: load(f).get(k) for k in ("id", "name", "description")}
               for f in sorted((home / "skills" / "manifests").glob("S*.yaml"))],
    "tools": [s.metadata() for s in h.tools.list()],
    "hooks": {p.value: h.hooks.names(p) for p in HookPoint if h.hooks.names(p)},
    "gates": GATE_NAMES,
    "authority": {e: sorted(p) for e, p in EVENT_AUTHORITY.items()},
    "why": WHY,
}
json.dump(out, open(sys.argv[3], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
"""


def build_canon_store(data: Path) -> None:
    sys.path.insert(0, str(HOME / "src"))
    from taochronos.plugins.classics.domain import DomainPack
    from taochronos.plugins.classics.webcorpus import build_store

    domain = DomainPack(HOME / "domains" / "classics")
    (data / "corpus").mkdir(parents=True, exist_ok=True)
    info = build_store(HOME / "corpus" / "web", data / "corpus" / "tcm.sqlite", domain.variants.normalize_text,
                       domain.variants.fingerprint, external=HOME / "corpus" / "catalog" / "external-works.yaml",
                       index=True)
    print(f"  built the 要籍语料 store: {info['books']} witnesses, {info['passages']} passages")


def study(canon_data: Path | None, research_value: bool = False) -> None:
    tmp = None
    if canon_data is None or not (canon_data / "corpus" / "tcm.sqlite").exists():
        tmp = tempfile.TemporaryDirectory()
        canon_data = Path(tmp.name)
        build_canon_store(canon_data)
    env = dict(os.environ, TAOCHRONOS_DATA=str(canon_data))
    for name, args in STUDY:
        cmd = [sys.executable, "-m", "taochronos", "study", *args, "--profile", "web-canon", "--json", "-o", str(OUT / name)]
        subprocess.run(cmd, check=True, env=env, cwd=HOME, stdout=subprocess.DEVNULL)
        print(f"  {name}: study {' '.join(args)}")
    subprocess.run([sys.executable, "-c", PAIRS, str(HOME), str(canon_data), str(OUT / "pairs.json")], check=True,
                   env=env, cwd=HOME, stdout=subprocess.DEVNULL)
    print("  pairs.json: study pairs (every significant pair)")
    subprocess.run([sys.executable, "-c", ARCH, str(HOME), str(canon_data), str(OUT / "fig1_architecture.json")],
                   check=True, env=env, cwd=HOME, stdout=subprocess.DEVNULL)
    print("  fig1_architecture.json: agents, skills, tools, hooks, gates and event authority")
    subprocess.run([sys.executable, str(HERE / "e2e_case.py"), "--canon-data", str(canon_data)], check=True, cwd=HOME,
                   stdout=subprocess.DEVNULL)
    print("  fig3_e2e_*: the end-to-end research case (e2e_case.py)")
    if research_value:  # the full-corpus benchmark re-run on the open corpus (Extended Data Fig. 2), about 4 minutes
        subprocess.run([sys.executable, "-m", "taochronos", "eval", "research_value", "-o",
                        str(OUT / "extfig_research_value_canon.json")], check=True, env=env, cwd=HOME,
                       stdout=subprocess.DEVNULL)
        print("  extfig_research_value_canon.json: eval research_value on the 要籍语料")
    if tmp is not None:
        tmp.cleanup()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--canon-data", type=Path, help="a data directory holding the 要籍语料 store (corpus/tcm.sqlite)")
    ap.add_argument("--eval-json", type=Path, help="a `taochronos eval -o` result on the demonstration corpus")
    ap.add_argument("--skip-study", action="store_true", help="keep the study-layer files already written")
    ap.add_argument("--research-value", action="store_true",
                    help="also re-run the research-value benchmark on the 要籍语料 (Extended Data Fig. 2; ~4 min)")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    print("corpus catalogs")
    corpus_works()
    canon_works()
    image_collections()
    web_corpus()
    print("evaluation")
    eval_suites(a.eval_json)
    documented()
    if not a.skip_study:
        print("study layer on the 要籍语料")
        study(a.canon_data, a.research_value)


if __name__ == "__main__":
    main()
