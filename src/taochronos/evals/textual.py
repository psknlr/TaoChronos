"""TaoChronos-Eval for computational philology: collation and stemma on artificial traditions; reuse types;
stratigraphy on restyled composites (and, when the full corpus is present, on the 素问 and the 伤寒论).

A real text (the demo corpus, normalised) is copied down a known stemma — two branches, three generations, one
witness contaminated from the other branch — with every copy adding known changes (substitutions, omissions,
additions of function words, transpositions).  The collation must find the changes, the tree must recover the
branches, the groups of shared readings must match the changes each branch introduced, and only the contaminated
witness may be flagged.  Artificial traditions are the standard test bed of computational stemmatology: the true
history is known exactly, which no real tradition offers.
"""

from __future__ import annotations

import bisect
import random
import re
from collections import Counter
from typing import Any

import yaml

from ..plugins.classics.collation import (
    WitnessText,
    align,
    build_units,
    clades,
    contamination,
    distances,
    groups,
    han_only,
    neighbour_joining,
    project,
    root,
    robinson_foulds,
    splits,
)
from ..plugins.classics.intertext import IntertextAnalyzer
from ..science import sense_evolution as sensevo
from ..science import stratigraphy as strata
from ..science.semantic_reuse import LABELS, MODES
from .base import EvalContext, SuiteResult, accuracy, confusion, macro_f1, prf

POOL = "之而也其于以者所则乃又亦若故夫盖此是"
SWAP = "寒热虚实表里上下左右大小多少先后"

Token = tuple[str, float]  # (character, position in the archetype; insertions sit between)


def _copy(tokens: list[Token], rng: random.Random, n: int, events: list[float]) -> list[Token]:
    out = list(tokens)
    for _ in range(n):
        i = rng.randrange(1, len(out) - 2)
        op = rng.random()
        pos = out[i][1]
        if op < 0.45:  # substitution
            out[i] = (rng.choice(SWAP + POOL), pos)
        elif op < 0.7:  # omission of one or two characters
            del out[i: i + rng.choice((1, 1, 2))]
        elif op < 0.9:  # addition of a function word
            out.insert(i, (rng.choice(POOL), pos - 0.5))
        else:  # transposition of two characters
            out[i], out[i + 1] = out[i + 1], out[i]
        events.append(pos)
    return out


def _witness(siglum: str, tokens: list[Token]) -> WitnessText:
    text = "".join(ch for ch, _ in tokens)
    return WitnessText(siglum, siglum, text, text, [(0, i) for i in range(len(text))], [(siglum, siglum, "正文")])


def _tradition(text: str, seed: int, rate: int = 90) -> dict[str, Any]:
    rng = random.Random(seed)
    n = max(4, len(text) // rate)
    arche: list[Token] = [(ch, float(i)) for i, ch in enumerate(text)]
    events: dict[str, list[float]] = {}
    tokens: dict[str, list[Token]] = {}
    for node, parent in (("A", None), ("B", None), ("C", "A"), ("D", "A"), ("H", "A"), ("E", "B"), ("F", "B")):
        events[node] = list(events.get(parent, [])) if parent else []
        tokens[node] = _copy(tokens[parent] if parent else arche, rng, n, events[node])
    half = len(tokens["D"]) // 2  # G: copied from D, then from F from the middle on (contamination), with its own changes
    cut = next(i for i, (_, p) in enumerate(tokens["F"]) if p >= tokens["D"][half][1])
    events["G"] = [p for p in events["D"] if p < tokens["D"][half][1]] + [p for p in events["F"] if p >= tokens["D"][half][1]]
    tokens["G"] = _copy(tokens["D"][:half] + tokens["F"][cut:], rng, n // 2, events["G"])
    return {"tokens": tokens, "events": events, "archetype": arche}


def collation(ctx: EvalContext) -> SuiteResult:
    h = ctx.default
    normalize = h.pack.variants.normalize_text
    text = han_only(normalize("".join(p.text for p in h.corpus.passages())))[0][:4000]
    observed = ["C", "D", "E", "F", "G", "H"]
    clean = [s for s in observed if s != "G"]  # G is contaminated: it has no single place in a tree
    true_splits = {frozenset({"C", "D", "H"}), frozenset({"E", "F"})}
    details = []
    agg: dict[str, list[float]] = {k: [] for k in ("unit_recall", "unit_precision", "split_recall", "rf", "group_precision_top3", "group_precision",
                                                   "contamination_precision", "contamination_recall")}
    seeds = (1, 2, 3) if ctx.quick else (1, 2, 3, 4, 5)
    for seed in seeds:
        t = _tradition(text, seed)
        base = _witness("C", t["tokens"]["C"])
        origins = [p for _, p in t["tokens"]["C"]]
        projections = {s: project(len(base.text), align(base.text, _witness(s, t["tokens"][s]).text), _witness(s, t["tokens"][s]))
                       for s in observed if s != "C"}
        units = build_units(base, projections)
        # every change of any witness, placed in the base's coordinates
        true_pos = sorted({bisect.bisect_left(origins, p) for s in observed for p in t["events"][s]})
        found = 0
        for q in true_pos:
            if any(u.start - 1 <= q <= u.end + 1 for u in units):
                found += 1
        matched_units = sum(1 for u in units if any(u.start - 1 <= q <= u.end + 1 for q in true_pos[bisect.bisect_left(true_pos, u.start - 1):
                                                                                                    bisect.bisect_left(true_pos, u.end + 2)]))
        present = {"C": bytearray(b"\x01" * len(base.text))} | {s: p.present for s, p in projections.items()}
        # the groups the changes really define: for each change, the witnesses that carry it
        carriers: dict[float, set[str]] = {}
        for s_ in observed:
            for p_ in set(t["events"][s_]):
                carriers.setdefault(p_, set()).add(s_)
        true_groups = {frozenset(c) for c in carriers.values() if 2 <= len(c) < len(observed)}
        d = distances(units, observed, present)
        nj_clean = neighbour_joining(clean, d)
        inferred = splits(nj_clean, clean)
        canon = {x if sorted(clean)[0] not in x else frozenset(set(clean) - x) for x in true_splits}
        nj = neighbour_joining(observed, d)
        edges, _ = root(nj, observed)
        grouped = groups(units, observed)
        top = [frozenset(g["witnesses"]) for g in grouped[:3]]
        contaminated, _ = contamination(units, grouped, edges, observed)
        flagged = {c.witness for c in contaminated}
        agg["unit_recall"].append(found / len(true_pos) if true_pos else 1.0)
        agg["unit_precision"].append(matched_units / len(units) if units else 0.0)
        agg["split_recall"].append(len(inferred & canon) / len(canon))
        agg["rf"].append(robinson_foulds(inferred, canon) or 0.0)
        agg["group_precision_top3"].append(sum(1 for g in top if g in true_groups) / len(top) if top else 0.0)
        agg["group_precision"].append(sum(1 for g in grouped if frozenset(g["witnesses"]) in true_groups) / len(grouped) if grouped else 0.0)
        agg["contamination_precision"].append((len(flagged & {"G"}) / len(flagged)) if flagged else 1.0)
        agg["contamination_recall"].append(1.0 if "G" in flagged else 0.0)
        details.append({"seed": seed, "changes": len(true_pos), "units": len(units), "found": found,
                        "splits": sorted(sorted(x) for x in inferred), "flagged": sorted(flagged),
                        "top_groups": [g["witnesses"] for g in grouped[:3]], "clades": sorted(sorted(v) for v in clades(edges, observed).values() if 1 < len(v) < len(observed))})
    metrics = {k: round(sum(v) / len(v), 4) for k, v in agg.items()}
    metrics["traditions"] = len(seeds)
    return SuiteResult("collation", metrics, details, notes=[
        "artificial traditions copied from the demo corpus down a known stemma (two branches, a contaminated witness); "
        "base = witness C, as in real use; a change counts as found when a variant unit covers it; the tree is scored "
        "on the uncontaminated witnesses (a contaminated one has no single place in a tree)"])


def reuse(ctx: EvalContext) -> SuiteResult:
    """ReuseEval: the reuse type of labelled pairs (gold/reuse.yaml), whether a pair is reuse at all, and — end to
    end on the demo corpus — whether ``study.reuse`` finds the lineage gold's transcriptions and rephrasings."""
    h = ctx.default
    an = IntertextAnalyzer(h.pack, h.corpus)
    pairs: list[tuple[str, str]] = []
    details: list[dict[str, Any]] = []
    for g in ctx.gold("reuse").get("pairs", []):
        r = an.label(g["source"], g["target"])
        pairs.append((g["label"], r["label"]))
        f = r["features"]
        details.append({"id": g["id"], "gold": g["label"], "predicted": r["label"], "correct": g["label"] == r["label"],
                        "rule": r["rule"], "basis": g.get("basis"),
                        "features": {k: f[k] for k in ("cov_source", "cov_target", "concept_cov", "concept_prec",
                                                       "specificity", "distinctive", "length_ratio", "formulaic_share")}})
    is_reuse = lambda label: MODES.get(label, "none") != "none"  # noqa: E731
    tp = sum(1 for g, p in pairs if is_reuse(g) and is_reuse(p))
    fp = sum(1 for g, p in pairs if not is_reuse(g) and is_reuse(p))
    fn = sum(1 for g, p in pairs if is_reuse(g) and not is_reuse(p))
    by_mode = accuracy([(MODES[g], MODES[p]) for g, p in pairs])
    # end to end: candidates and labels over the demo corpus
    study = h.capabilities.get("study")
    found = []
    for e in ctx.gold("lineage").get("positive", []):
        if e["relation"] not in ("transcribes", "rephrases"):
            continue
        res = study.reuse(passage_id=e["target"])
        hit = next((x for x in res["hits"] if x["passage_id"] == e["source"]), None)
        found.append({"relation": e["relation"], "source": e["target"], "reuser": e["source"],
                      "found": hit is not None, "label": hit["label"] if hit else None,
                      "found_by": hit["found_by"] if hit else []})
    metrics = {"pairs": len(pairs), "accuracy": accuracy(pairs), "macro_f1": macro_f1(pairs), "mode_accuracy": by_mode,
               "reuse_detection": prf(tp, fp, fn),
               "per_label": {k: {"gold": sum(1 for g, _ in pairs if g == k),
                                 "correct": sum(1 for g, p in pairs if g == k == p)} for k in LABELS},
               "pipeline_recall": round(sum(1 for x in found if x["found"]) / len(found), 4) if found else None,
               "confusion": confusion(pairs)}
    return SuiteResult("reuse", metrics, details + [{"pipeline": x} for x in found], notes=[
        "author-constructed pairs (gold/reuse.yaml): a development set for the transparent rules, not an independent "
        "benchmark; mode = retained / transformed / disputed / none; pipeline_recall = lineage gold transcriptions "
        "and rephrasings that study.reuse finds in the demo corpus"])


# a later author's habits: function characters exchanged for others of the same use (也→矣, 而→则 …)
RESTYLE = {"也": "矣耳", "而": "则乃", "于": "乎诸", "其": "厥彼", "者": "所", "以": "用因", "则": "即便", "若": "如倘",
           "此": "是斯", "之": "诸", "故": "是", "乃": "即"}
YUNQI = ("天元纪", "五运行", "六微旨", "气交变", "五常政", "六元正纪", "至真要")


def _composite(clauses: list[str], seed: int, chunk: int, rate: float, length: int = 16000
               ) -> tuple[list[str], list[int], list[int]]:
    """A text of ``length`` characters drawn clause by clause from the corpus, in chunks; blocks of chunks are rewritten
    with a second author's function characters, so the layers differ in style only (their content is drawn from the
    same clauses, at random)."""
    rng = random.Random(seed)
    stream: list[str] = []
    while sum(map(len, stream)) < length:
        stream.append(rng.choice(clauses))
    text = "".join(stream)
    chunks = [text[i: i + chunk] for i in range(0, len(text) - chunk + 1, chunk)]
    truth, bounds = [], []
    layer, left = 0, rng.randint(4, 8)
    for i, c in enumerate(chunks):
        if left == 0:
            layer, left = 1 - layer, rng.randint(4, 8)
            bounds.append(i)
        left -= 1
        truth.append(layer)
        if layer == 1:
            chunks[i] = "".join(rng.choice(RESTYLE[ch]) if ch in RESTYLE and rng.random() < rate else ch for ch in c)
    return chunks, truth, bounds


def stratigraphy(ctx: EvalContext) -> SuiteResult:
    """StratigraphyEval: layers and change points on composites whose layers differ only in function-character habits,
    attribution of held-out chunks; with the full corpus, the 运气七篇 of the 素问 (layer, change points, late
    vocabulary) and the chapters of the 伤寒论 ascribed to 王叔和 (辨脉法, 平脉法: nearest 脉经)."""
    h = ctx.default
    normalize = h.pack.variants.normalize_text
    clauses = [c for p in h.corpus.passages() for c in (han_only(x)[0] for x in re.split(r"[。；！？]", normalize(p.text))) if len(c) >= 4]
    agg: dict[str, list[float]] = {k: [] for k in ("layer_accuracy", "split_supported", "change_point_recall",
                                                   "change_point_precision", "boundary_recall", "boundary_precision",
                                                   "attribution_accuracy")}
    details: list[dict[str, Any]] = []
    seeds = (1, 2, 3) if ctx.quick else (1, 2, 3, 4, 5)
    for seed in seeds:
        chunks, truth, bounds = _composite(clauses, seed, 400, 0.5)
        whole = strata.profile("".join(chunks), strata.FUNCTION_CHARS)
        names = [f for f, v in zip(strata.FUNCTION_CHARS, whole) if v >= 1.0]
        z, _, _ = strata.zscores([strata.profile(c, names, root=True) for c in chunks])
        res = strata.layers(z, [float(len(c)) for c in chunks], k=2)
        acc = sum(1 for a, b in zip(res["labels"], truth) if a == b) / len(truth)
        found = [c["at"] for c in strata.change_points(z, window=4)]
        hit = sum(1 for b in bounds if any(abs(b - f) <= 1 for f in found))
        good = sum(1 for f in found if any(abs(b - f) <= 1 for b in bounds))
        runs = strata.boundaries(res["labels"])
        agg["boundary_recall"].append(sum(1 for b in bounds if any(abs(b - f) <= 1 for f in runs)) / len(bounds) if bounds else 1.0)
        agg["boundary_precision"].append(sum(1 for f in runs if any(abs(b - f) <= 1 for b in bounds)) / len(runs) if runs else 1.0)
        # attribution: profiles from the even chunks of each layer, the odd ones attributed
        pools = {lab: "".join(c for i, (c, t) in enumerate(zip(chunks, truth)) if t == lab and i % 2 == 0) for lab in (0, 1)}
        cands = {f"L{lab}": strata.profile(t, names) for lab, t in pools.items()}
        tests = [(c, t) for i, (c, t) in enumerate(zip(chunks, truth)) if i % 2 == 1]
        right = sum(1 for c, t in tests if strata.attribute(strata.profile(c, names), cands)[0]["candidate"] == f"L{t}")
        agg["layer_accuracy"].append(max(acc, 1 - acc))
        agg["split_supported"].append(1.0 if res["supported"] else 0.0)
        agg["change_point_recall"].append(hit / len(bounds) if bounds else 1.0)
        agg["change_point_precision"].append(good / len(found) if found else 1.0)
        agg["attribution_accuracy"].append(right / len(tests) if tests else 0.0)
        details.append({"seed": seed, "chunks": len(chunks), "boundaries": bounds, "change_points": found, "layer_runs": runs,
                        "p": res["p"]})
    metrics: dict[str, Any] = {k: round(sum(v) / len(v), 4) for k, v in agg.items()}
    metrics["composites"] = len(seeds)
    notes = ["composites: 16 000 characters drawn clause by clause from the demo corpus, in 400-character chunks, "
             "blocks of 4–8 chunks rewritten with a second author's function characters (half of them), so the layers "
             "differ in style only; function-character profiles; a change point counts within one chunk of a boundary"]
    corpus = None if ctx.quick else ctx.corpus_harness()
    if corpus is not None:
        study = corpus.capabilities.get("study")
        lay = study.layers("素问")
        minor = {c["chapter"] for c in lay["chapters"] if c["layer"] != 0}
        yq = [c["chapter"] for c in lay["chapters"] if any(k in normalize(c["chapter"]) for k in YUNQI)]
        in_minor = [c for c in yq if c in minor]
        cps = [(normalize(c["before"]), normalize(c["after"])) for c in lay["change_points"]]
        edges = sum(1 for before, after in (("标本病传论", "天元纪大论"), ("至真要大论", "著至教论"))
                    if any(before in b and after in a for b, a in cps))
        dat = study.dating("素问")
        late = [r["chapter"] for r in dat["later_than_nominal"]]
        auth = {ch: study.authorship(book="jc_b000", chapter=ch, candidates=["脉经", "金匮要略", "针灸甲乙经", "千金翼方",
                                                                             "外台秘要", "肘后备急方"])["candidates"][0]["candidate"]
                for ch in ("辨脈法", "平脈法")}
        metrics["real"] = {"yunqi_in_minor_layer": f"{len(in_minor)}/{len(yq)}",
                           "yunqi_share_of_minor_layer": round(len(in_minor) / len(minor), 3) if minor else None,
                           "yunqi_boundaries_found": f"{edges}/2",
                           "late_vocabulary_chapters_yunqi": f"{sum(1 for c in late if any(k in normalize(c) for k in YUNQI))}/{len(late)}",
                           "shuhe_chapters_nearest_maijing": f"{sum(1 for v in auth.values() if v == '脉经')}/{len(auth)}"}
        details.append({"real": {"minor_layer": sorted(minor), "change_points": lay["change_points"], "late": late,
                                 "authorship": auth}})
        notes.append("real: the 素问 (四库 witness) — the 运气七篇 are held to be a later addition; the 伤寒论's 辨脉法 and "
                     "平脉法 are ascribed to 王叔和 (compared with 脉经 and other early works)")
    return SuiteResult("stratigraphy", metrics, details, notes=notes)


CASE_FIELDS = ("pulse", "formulas", "added", "removed", "principles", "doses")


def _visit_values(v: Any, field: str) -> list[str]:
    if field == "pulse":
        return list(v.findings.get("pulse", []))
    if field == "doses":
        return [v.doses] if v.doses else []
    return list(getattr(v, field))


def _match(a: str, b: str) -> bool:
    return bool(a) and bool(b) and (a in b or b in a)


def cases(ctx: EvalContext) -> SuiteResult:
    """CaseEval: constructed case records (gold/cases.yaml) cut into cases and visits and read field by field."""
    h = ctx.default
    study = h.capabilities.get("study")
    gold = ctx.gold("cases")
    predicted: dict[str, list[Any]] = {}
    for book in gold.get("books", []):
        rows = [(f"{book['id']}.{i}", book["heading"], text) for i, text in enumerate(book["passages"])]
        predicted[book["id"]] = study._cases.parse_rows(rows, book["id"])
    by_book: dict[str, list[dict[str, Any]]] = {}
    for g in gold.get("cases", []):
        by_book.setdefault(g["book"], []).append(g)
    counts = {f: [0, 0, 0] for f in CASE_FIELDS}  # tp, fp, fn
    visit_ok = response_ok = response_n = outcome_ok = patient_ok = patient_n = 0
    details = []
    for bid, gcases in by_book.items():
        pcases = predicted.get(bid, [])
        details.append({"book": bid, "gold_cases": len(gcases), "predicted_cases": len(pcases)})
        for g, p in zip(gcases, pcases):
            visit_ok += len(g["visits"]) == len(p.visits)
            outcome_ok += (g.get("outcome") or "") == p.outcome
            for k, val in (g.get("patient") or {}).items():
                patient_n += 1
                patient_ok += _match(str(val), p.patient.get(k, ""))
            for gv, pv in zip(g["visits"], p.visits):
                for f in CASE_FIELDS:
                    gvals = [str(x) for x in (gv.get(f) if isinstance(gv.get(f), list) else ([gv[f]] if gv.get(f) else []))]
                    pvals = _visit_values(pv, f)
                    counts[f][0] += sum(1 for x in gvals if any(_match(x, y) for y in pvals))
                    counts[f][2] += sum(1 for x in gvals if not any(_match(x, y) for y in pvals))
                    counts[f][1] += sum(1 for y in pvals if not any(_match(x, y) for x in gvals))
                response_n += 1
                response_ok += (gv.get("response") or "") == pv.response
            details.append({"book": bid, "patient": p.patient, "visits": [len(g["visits"]), len(p.visits)],
                            "outcome": [g.get("outcome"), p.outcome],
                            "responses": [[gv.get("response") or "" for gv in g["visits"]], [pv.response for pv in p.visits]]})
    n_cases = sum(len(v) for v in by_book.values())
    metrics: dict[str, Any] = {
        "cases": n_cases,
        "case_segmentation": round(sum(1 for d in details if "gold_cases" in d and d["gold_cases"] == d["predicted_cases"]) /
                                   max(1, len(by_book)), 4),
        "visit_segmentation": round(visit_ok / n_cases, 4) if n_cases else None,
        "response_accuracy": round(response_ok / response_n, 4) if response_n else None,
        "outcome_accuracy": round(outcome_ok / n_cases, 4) if n_cases else None,
        "patient_accuracy": round(patient_ok / patient_n, 4) if patient_n else None,
        "fields": {f: prf(*c) for f, c in counts.items()},
    }
    notes = ["constructed records in the two manners of the literature (successive visits under a heading; narratives), a "
             "development set written with the rules: it shows what they are meant to do, not how they generalise; case "
             "segmentation = books whose number of cases is right; fields compared as sets, one value containing the other"]
    corpus = None if ctx.quick else ctx.corpus_harness()
    if corpus is not None:  # two independent transcriptions of one case collection should be read alike
        cs = corpus.capabilities.get("study")._cases
        a, b = cs.parse("jc_n003"), cs.parse("jc_n003a")
        oa, ob = Counter(c.outcome or "-" for c in a), Counter(c.outcome or "-" for c in b)
        metrics["real"] = {"wu_jutong_cases": [len(a), len(b)], "case_count_agreement": round(min(len(a), len(b)) / max(len(a), len(b)), 4),
                           "outcome_agreement": round(sum(min(oa[k], ob[k]) for k in oa) / max(len(a), len(b)), 4)}
        notes.append("real: the two transcriptions of 吴鞠通医案 in the corpus (笈成 jc_n003, jc_n003a), read independently")
    return SuiteResult("cases", metrics, details, notes=notes)


def argument(ctx: EvalContext) -> SuiteResult:
    """ArgumentEval: the steps of reasoning of annotated passages (gold/argument.yaml); with the full corpus, whether
    two transcriptions of one work reason alike (and unlike another work)."""
    h = ctx.default
    study = h.capabilities.get("study")
    tp = fp = fn = utp = ufp = ufn = seg = 0
    details = []
    passages = ctx.gold("argument").get("passages", [])
    for g in passages:
        r = study.argument(g["text"])
        pred = {(e["source"], e["target"], e["relation"]) for e in r["edges"]}
        gold = {tuple(e) for e in g["edges"]}
        tp, fp, fn = tp + len(pred & gold), fp + len(pred - gold), fn + len(gold - pred)
        up, ug = {(s_, t) for s_, t, _ in pred}, {(s_, t) for s_, t, _ in gold}
        utp, ufp, ufn = utp + len(up & ug), ufp + len(up - ug), ufn + len(ug - up)
        seg += len(r["clauses"]) == g["clauses"]
        details.append({"text": g["text"][:30], "gold": sorted(map(list, gold)), "predicted": sorted(map(list, pred))})
    metrics: dict[str, Any] = {"passages": len(passages), "edges": prf(tp, fp, fn), "unlabelled": prf(utp, ufp, ufn),
                               "clause_segmentation": round(seg / len(passages), 4) if passages else None}
    notes = ["author-constructed passages (a development set written with the marker table): labelled edges = source, "
             "target and relation all right; unlabelled = the step found, its type aside"]
    corpus = None if ctx.quick else ctx.corpus_harness()
    if corpus is not None:
        arg = corpus.capabilities.get("study")._argument
        from ..science.argumentation import compare as compare_profiles

        a, b, c = (arg.profile(books=[x], passages=400) for x in ("jc_m100", "jc_m100a", "jc_e004"))
        same = compare_profiles(a["_counts"], b["_counts"])
        other = compare_profiles(a["_counts"], c["_counts"])
        metrics["real"] = {"same_work_jsd": same["relations_jsd"], "other_work_jsd": other["relations_jsd"],
                           "same_work_closer": same["relations_jsd"] < other["relations_jsd"]}
        notes.append(f"real: the relations of the two transcriptions of 脉经 (jc_m100, jc_m100a) against "
                     f"{c['work']} (jc_e004)")
    return SuiteResult("argument", metrics, details, notes=notes)


VOCAB_A = ["口渴", "引饮", "身热", "脉浮", "发汗", "烦满"]
VOCAB_B = ["多饮", "尿多", "肾虚", "消瘦", "肾气", "下焦"]
VOCAB_C = ["痈疽", "饮酒", "尿甜", "肥甘", "疮疡", "嗜酒"]  # a sense no curation names
FILLER = ["其人", "日久", "不已", "或曰", "治之", "当以", "此病", "亦有", "兼见", "至于", "所以", "病者", "由是", "诸家"]


def _sense_trial(seed: int, n: int = 600, turn: float = 1000.0, hidden_from: float = 1300.0) -> dict[str, Any]:
    rng = random.Random(seed)
    contexts, truth = [], []
    for _ in range(n):
        year = rng.uniform(0, 2000)
        if year >= hidden_from and rng.random() < 0.3:
            sense, vocab = "C", VOCAB_C
        else:
            sense = "B" if rng.random() < (0.75 if year >= turn else 0.15) else "A"
            vocab = VOCAB_B if sense == "B" else VOCAB_A
        words = rng.sample(vocab, 2) + rng.sample(FILLER, 4)
        rng.shuffle(words)
        contexts.append({"text": "".join(words), "tokens": words, "year": year})
        truth.append(sense)
    return {"contexts": contexts, "truth": truth}


def senses(ctx: EvalContext) -> SuiteResult:
    """SenseEvolutionEval: synthetic occurrences of a term whose second sense takes over at a known date and whose
    third sense, named by no curation, appears later — the change point, the labelling and the discovery of the
    hidden sense; on the demo corpus, the curated exemplars of 消渴 labelled as curated."""
    curated = [{"id": "A", "cues": VOCAB_A[:4], "anti_cues": []}, {"id": "B", "cues": VOCAB_B[:4], "anti_cues": []}]
    agg: dict[str, list[float]] = {k: [] for k in ("change_year_error", "change_detected", "labelling_accuracy",
                                                   "hidden_sense_found", "hidden_sense_precision")}
    details = []
    seeds = (1, 2, 3) if ctx.quick else (1, 2, 3, 4, 5)
    for seed in seeds:
        t = _sense_trial(seed)
        occ, truth = t["contexts"], t["truth"]
        labels = sensevo.assign(occ, curated)
        known = [(lab, tr) for lab, tr in zip(labels, truth) if tr in ("A", "B")]
        agg["labelling_accuracy"].append(sum(1 for lab, tr in known if lab == tr) / len(known))
        dated = [(o["year"], lab) for o, lab in zip(occ, labels) if lab]
        cp = sensevo.change_point([y for y, _ in dated], [lab for _, lab in dated], permutations=99)
        agg["change_detected"].append(1.0 if cp and cp["p"] < 0.05 else 0.0)
        agg["change_year_error"].append(abs(cp["year"] - 1000.0) if cp else 1000.0)
        found = sensevo.discover(occ, labels, k=2)
        best = max(found, key=lambda c: sum(1 for d in c["distinctive"][:5] if d["token"] in VOCAB_C), default=None)
        hits = sum(1 for d in (best["distinctive"][:5] if best else []) if d["token"] in VOCAB_C)
        agg["hidden_sense_found"].append(1.0 if hits >= 3 else 0.0)
        agg["hidden_sense_precision"].append(hits / 5)
        details.append({"seed": seed, "change": cp["year"] if cp else None, "p": cp["p"] if cp else None,
                        "candidates": [[d["token"] for d in c["distinctive"][:5]] for c in found]})
    metrics: dict[str, Any] = {k: round(sum(v) / len(v), 4) for k, v in agg.items()}
    demo = ctx.default.capabilities.get("study").senses("消渴")
    metrics["exemplars"] = f"{demo['exemplar_check']['agree']}/{demo['exemplar_check']['checked']}"
    details.append({"exemplars": demo["exemplar_check"]["items"]})
    return SuiteResult("senses", metrics, details, notes=[
        "synthetic occurrences (600 per trial): sense B's share rises from 15% to 75% in the year 1000, a sense C that "
        "no cue names appears from 1300 (30%); change_year_error in years; hidden_sense_found = a candidate cluster with "
        "3 of its top 5 words from C; exemplars: the curated exemplar passages of 消渴 in the demo corpus labelled with "
        "their curated sense"])


def fragments(ctx: EvalContext) -> SuiteResult:
    """FragmentEval: a lost work reconstructed from the books that quote it — on a constructed corpus whose lost
    text is known (gold/fragments: attributions with source notes and 又, a competing source, packed quotations, a
    late paraphrase), and, with the full corpus, 千金要方 and 肘后备急方 (which survive) reconstructed from quotation."""
    from ..plugins.classics import Corpus
    from ..plugins.classics.study import StudyService

    h = ctx.default
    corpus = Corpus.load(ctx.home / "evals" / "gold" / "fragments")
    corpus.normalize = h.pack.variants.normalize_text
    study = StudyService(h.pack, corpus)
    res = study.fragments("集古方", verify_against=["jigu"])
    lost = {p.id: (han_only(h.pack.variants.normalize_text(p.text))[0], p.locator.volume) for p in corpus.passages(book_ids=["jigu"])}
    decoys = ("杏仁", "齿痛", "饱食", "半夏、陈皮")  # the words of other sources' entries
    leaks = sum(1 for f in res["fragments"] if any(d in f["text"] for d in decoys))
    vol_ok = vol_n = 0
    for f in res["fragments"]:
        if f["volume"] is None:
            continue
        han = han_only(h.pack.variants.normalize_text(f["text"]))[0]
        best = max(lost.values(), key=lambda v: len(_trigrams(han) & _trigrams(v[0])))
        vol_n += 1
        vol_ok += f["volume"] == _volume_number(best[1])
    metrics: dict[str, Any] = {
        "fragments": res["count"], "precision": res["verification"]["precision"], "coverage": res["verification"]["coverage"],
        "decoy_leaks": leaks, "volume_accuracy": round(vol_ok / vol_n, 4) if vol_n else None,
        "merged": sum(1 for f in res["fragments"] if len(f["witnesses"]) > 1)}
    details = [{"fragment": f["text"][:40], "volume": f["volume"], "witnesses": [w["passage_id"] for w in f["witnesses"]]}
               for f in res["fragments"]]
    notes = ["constructed corpus (gold/fragments): precision = fragments whose 6-grams are at least 30% in the held-out "
             "lost text; decoy_leaks = fragments carrying another source's words; volume_accuracy = source-note volumes "
             "matching the lost text's volume"]
    big = None if ctx.quick else ctx.corpus_harness()
    if big is not None:
        st = big.capabilities.get("study")
        qj = st.fragments("千金要方", verify_against=["*"])["verification"]
        zh = st.fragments("肘后备急方", verify_against=["*"])["verification"]
        metrics["real"] = {"qianjin_precision": qj["precision"], "qianjin_coverage": qj["coverage"],
                           "qianjin_best_quoting_books": [(b["book"], b["precision"]) for b in qj["by_quoting_book"][:3]],
                           "zhouhou_not_in_extant": round(1 - zh["precision"], 4) if zh["precision"] is not None else None}
        notes.append("real: 千金要方 and 肘后备急方 reconstructed from the books that quote them and checked against their "
                     "surviving witnesses; the extant 肘后 is a reworked remnant, so most quotations of it are not in it — "
                     "candidate lost text (佚文), which is what 辑佚 recovers")
    return SuiteResult("fragments", metrics, details, notes=notes)


def punctuation(ctx: EvalContext) -> SuiteResult:
    """PunctuationEval (句读): the punctuated texts are the gold — their marks are stripped and the model's gaps scored
    against the editors' (boundary P/R/F1, sentence F1, the kind of mark), beside the rule segmenter.  On the demo
    corpus, works held out in four folds; with the full corpus, the store's model (whole works held out of training)
    on a sample of the held-out works, and on real 白文 — the 四库 transcriptions of held-out works, scored against
    the editors' marks carried over from their punctuated transcriptions by alignment.  The character preservation
    rate is the share of punctuated outputs whose characters are exactly the input's."""
    from ..plugins.classics.segment import Segmenter, is_unpunctuated
    from ..plugins.classics.study.punctuation import (PunctuationModel, gaps, model_labels, rule_labels, score,
                                                        strip_marks)

    h = ctx.default
    normalize = h.pack.variants.normalize_text
    books = h.corpus.books
    unit = lambda p: books[p.book_id].work or p.book_id  # noqa: E731
    passages = [p for p in h.corpus.passages() if p.kind in ("text", "formula", "materia_medica") and not is_unpunctuated(p.text)]
    works = sorted({unit(p) for p in passages})
    seg = Segmenter(h.pack.lexicon)
    gold: list[int] = []
    pred: list[int] = []
    rules: list[int] = []
    preserved = checked = 0
    folds = 4
    for f in range(folds):
        test = {w for k, w in enumerate(works) if k % folds == f}
        model = PunctuationModel().train([normalize(p.text) for p in passages if unit(p) not in test], lexicon=h.pack.lexicon)
        for p in passages:
            if unit(p) not in test:
                continue
            chars, labels = gaps(normalize(p.text))
            if len(chars) < 2:
                continue
            gold += labels
            pred += model_labels(model, chars)
            rules += rule_labels(seg, chars)
            preserved += int(model.punctuate(strip_marks(p.text), normalize)["preserved"])
            checked += 1
    sm, sr = score(gold, pred), score(gold, rules)
    metrics: dict[str, Any] = {
        "boundary_f1": sm["boundary_f1"], "boundary_p": sm["boundary_p"], "boundary_r": sm["boundary_r"],
        "sentence_f1": sm["sentence_f1"], "mark_type_accuracy": sm["mark_type_accuracy"],
        "rules_boundary_f1": sr["boundary_f1"], "rules_sentence_f1": sr["sentence_f1"],
        "preservation_rate": round(preserved / checked, 4) if checked else None, "gaps": sm["gaps"]}
    notes = [f"demo corpus: {len(works)} works in {folds} folds, each punctuated by a model trained on the other folds "
             "(a few thousand characters of training text: the scores show the method works, not how well it works)"]
    details: list[dict[str, Any]] = []
    big = None if ctx.quick else ctx.corpus_harness()
    if big is not None:
        st = big.capabilities.get("study")
        model = st._punct.model()
        held = st._punct.evaluate(model)
        typed = held["typed"]
        baiwen = st._punct.against_baiwen(model)
        metrics["real"] = {
            "works": held["works"], "books": held["books"], "characters": held["characters"],
            "boundary_f1": held["model"]["boundary_f1"], "boundary_p": held["model"]["boundary_p"],
            "boundary_r": held["model"]["boundary_r"], "sentence_f1_typed": typed["model"]["sentence_f1"],
            "mark_type_accuracy_typed": typed["model"]["mark_type_accuracy"],
            "rules_boundary_f1": held["rules"]["boundary_f1"], "rules_sentence_f1_typed": typed["rules"]["sentence_f1"],
            "preservation_rate": held["preservation_rate"], "training_characters": model.info.get("characters")}
        if baiwen.get("model"):
            typed_b = baiwen.get("typed") or {}
            metrics["baiwen"] = {"works": len(baiwen["works"]), "skipped": len(baiwen["skipped"]), "gaps": baiwen["model"]["gaps"],
                                 "boundary_f1": baiwen["model"]["boundary_f1"], "boundary_p": baiwen["model"]["boundary_p"],
                                 "boundary_r": baiwen["model"]["boundary_r"], "rules_boundary_f1": baiwen["rules"]["boundary_f1"],
                                 "sentence_f1_typed": (typed_b.get("model") or {}).get("sentence_f1"),
                                 "rules_sentence_f1_typed": (typed_b.get("rules") or {}).get("sentence_f1")}
            details += [{"work": w["work"], "baiwen": w["baiwen"], "punctuated": w["punctuated"], "aligned": w["aligned"],
                         "boundary_f1": w["model"]["boundary_f1"], "rules_boundary_f1": w["rules"]["boundary_f1"],
                         "sentence_f1": w["model"]["sentence_f1"] if w["tells_sentences"] else None}
                        for w in baiwen["works"]] + [{"skipped": x} for x in baiwen["skipped"]]
        notes.append("real: the store's model, trained on the punctuated main text of the works not held out (every "
                     "transcription of a held-out work is out); scored on a sample of the held-out works' passages. "
                     "sentence F1 and mark type on the texts whose editors use both sentence and clause marks")
        notes.append("baiwen: the 四库 白文 of held-out works punctuated by the model and scored against the editors' marks of "
                     "their punctuated transcriptions, carried over by alignment (gaps inside aligned runs)")
    return SuiteResult("punctuation", metrics, details, notes=notes)


def commentaries(ctx: EvalContext) -> SuiteResult:
    """CommentaryEval (集注对齐与注家比较): a constructed classic and its commentaries in four layouts (gold/commentaries)
    — the commentaries found for each clause (precision, recall), the text taken as each commentary against the gold
    (character F1), the explicit and wording relations between them, and the quotations kept apart; with the full
    corpus, the commentaries on 太阳之为病 against the commentators known to be in the store and two relations known
    from the literature (张卿子 reprints 成无己's notes; 喻昌 took over 方有执's wording)."""
    from ..plugins.classics import Corpus
    from ..plugins.classics.study import StudyService

    h = ctx.default
    root = ctx.home / "evals" / "gold" / "commentaries"
    corpus = Corpus.load(root)
    corpus.normalize = h.pack.variants.normalize_text
    study = StudyService(h.pack, corpus)
    gold = yaml.safe_load((root / "gold.yaml").read_text(encoding="utf-8"))["clauses"]
    tp = fp = fn = rtp = rfp = rfn = qtp = qfn = 0
    f1s: list[float] = []
    details: list[dict[str, Any]] = []
    for g in gold:
        res = study.commentaries(g["clause"])
        found = {u["book_id"]: u for u in res["commentaries"]}
        want = g["commentaries"]
        tp += len(set(found) & set(want))
        fp += len(set(found) - set(want))
        fn += len(set(want) - set(found))
        for bid in set(found) & set(want):
            got = han_only(h.pack.variants.normalize_text(found[bid]["text"]))[0]
            f1s.append(_char_f1(got, h.pack.variants.normalize_text(want[bid]), g["clause"], h.pack.variants.normalize_text))
        ids = {u["id"]: u["book_id"] for u in res["commentaries"]}
        rels = {(ids[r["from"]], ids[r["to"]], r["type"]) for r in res["relations"] if r["type"] in ("驳", "从", "引", "照录", "承袭")}
        want_rels = {(r["from"], r["to"], r["type"]) for r in g.get("relations") or []}
        rtp += len(rels & want_rels)
        rfp += len(rels - want_rels)
        rfn += len(want_rels - rels)
        quoted = {q["passage_id"] for q in res["quotations"]}
        qtp += len(quoted & set(g.get("quotations") or []))
        qfn += len(set(g.get("quotations") or []) - quoted)
        details.append({"clause": g["clause"], "found": sorted(found), "missed": sorted(set(want) - set(found)),
                        "extra": sorted(set(found) - set(want)), "relations": sorted(rels)})
    metrics: dict[str, Any] = {"units": prf(tp, fp, fn), "text_f1": round(sum(f1s) / len(f1s), 4) if f1s else None,
                               "relations": prf(rtp, rfp, rfn),
                               "quotations_recall": round(qtp / (qtp + qfn), 4) if qtp + qfn else None}
    notes = ["constructed corpus (gold/commentaries): four layouts — the row after the clause, rows of a layer of their "
             "own, run on in the clause's paragraph, 白文 with notes after each clause; text_f1 = character F1 of the text "
             "taken as a commentary (the lemma's own characters left out) against the gold commentary"]
    big = None if ctx.quick else ctx.corpus_harness()
    if big is not None:
        st = big.capabilities.get("study")
        res = st.commentaries("太阳之为病，脉浮，头项强痛而恶寒。")
        known = ["成无己", "方有执", "张卿子", "喻昌", "汪琥", "张志聪", "张璐", "钱潢", "尤怡", "吴谦", "柯琴"]
        got = {u["commentator"] for u in res["commentaries"]}
        rels = {(r["from_commentator"], r["to_commentator"], r["type"]) for r in res["relations"]}
        expected = [("张卿子", "成无己", "照录"), ("喻昌", "方有执", "承袭")]
        metrics["real"] = {"commentaries": res["count"], "known_commentators_found": f"{sum(k in got for k in known)}/{len(known)}",
                           "known_relations_found": f"{sum(e in rels for e in expected)}/{len(expected)}",
                           "quotations": res["quotation_count"]}
        notes.append("real: the commentaries on 伤寒论 太阳之为病 in the store; the known commentators are those whose "
                     "commentaries on the clause the store holds; the relations are documented in the literature")
    return SuiteResult("commentaries", metrics, details, notes=notes)


def _char_f1(got: str, want: str, clause: str, normalize: Any) -> float:
    """Character-overlap F1 of an extracted commentary against the gold (bag of characters; the clause left out)."""
    rest = Counter(got)
    for ch in han_only(normalize(clause))[0]:
        if rest[ch]:
            rest[ch] -= 1
    gold = Counter(han_only(want)[0])
    common = sum((rest & gold).values())
    if not common:
        return 0.0
    prec, rec = common / sum(rest.values()), common / sum(gold.values())
    return round(2 * prec * rec / (prec + rec), 4)


def disputes(ctx: EvalContext) -> SuiteResult:
    """DisputeEval (争议): the stance a sentence takes towards the physician it names, on constructed sentences with
    the hard cases kept (gold/disputes.yaml: a verdict belonging to the quoted words, a hypothetical, a rejection of
    others, a denial of the marker, a dispute without a reporting word); with the full corpus, whether three
    controversies known from the literature are found (景岳 against 丹溪 on 相火, 越人's 左肾右命门 rejected, 张介宾
    the one who rejects 丹溪 most)."""
    from ..plugins.classics.study import StudyService

    h = ctx.default
    study = StudyService(h.pack, h.corpus)
    people = study._commentary.people
    gold = ctx.gold("disputes")["cases"]
    pairs: list[tuple[str, str]] = []
    details = []
    for c in gold:
        found = [x for x in people.cited(h.pack.variants.normalize_text(c["text"])) if x["person"] == c["person"]]
        got = (found[0]["stance"] if found else None) or "none"
        if c.get("by") and found and found[0].get("reported_by") != c["by"]:
            got = f"{got}(by?)"
        pairs.append((c["stance"], got))
        if got != c["stance"]:
            details.append({"text": c["text"], "expected": c["stance"], "got": got, "why": c.get("why", "")})

    def pr(label: str) -> dict[str, float | None]:
        t = sum(1 for g, p in pairs if g == label and p == label)
        return prf(t, sum(1 for g, p in pairs if p == label and g != label), sum(1 for g, p in pairs if g == label and p != label))

    metrics: dict[str, Any] = {"accuracy": accuracy(pairs), "reject": pr("reject"), "endorse": pr("endorse"), "cases": len(pairs)}
    notes = ["constructed sentences (gold/disputes.yaml) with known hard cases; the misses listed in the details are "
             "the limits of a marker-and-name reading"]
    big = None if ctx.quick else ctx.corpus_harness()
    if big is not None:
        st = big.capabilities.get("study")
        fire = st.disputes("相火")
        ming = st.disputes("命门")
        dan = st.disputes(person="丹溪")
        checks = {
            "景岳驳丹溪（相火）": any(d["by"] == "张介宾" and d["target"] == "朱震亨" for d in fire["disputes"]),
            "驳越人左肾右命门": any(d["target"] == "扁鹊" for d in ming["disputes"]),
            "驳丹溪最多者为张介宾": bool(dan["who_rejects_whom"]) and dan["who_rejects_whom"][0]["by"] == "张介宾",
        }
        metrics["real"] = {"known_controversies_found": f"{sum(checks.values())}/{len(checks)}",
                           "丹溪_rejections": dan["counts"].get("reject", 0), "丹溪_endorsements": dan["counts"].get("endorse", 0)}
        details.append({"real_checks": checks})
        notes.append("real: controversies documented in the history of medicine, looked for in the store")
    return SuiteResult("disputes", metrics, details, notes=notes)


def variant_impact(ctx: EvalContext) -> SuiteResult:
    """ImpactEval (异文分级): the class of a variant reading — dose, negation, prescription, clinical, structural,
    lexical, order, lacuna, function, orthographic — on constructed pairs with their contexts (gold/variant_impact.yaml),
    including the traps of a numeral inside a word (半表半里, 合病, 十枣汤); with the full corpus, the classes of the
    variants of 伤寒论's 太阳篇 between two transcriptions, and whether the review queue puts doses first."""
    from ..plugins.classics.collation.impact import classify

    h = ctx.default
    cases = ctx.gold("variant_impact")["cases"]
    pairs = []
    details = []
    for c in cases:
        got = classify(c["lemma"], c["reading"], c["context"], h.pack.lexicon, normalize=h.pack.variants.normalize_text)["impact"]
        pairs.append((c["expect"], got))
        if got != c["expect"]:
            details.append({"lemma": c["lemma"], "reading": c["reading"], "context": c["context"], "expected": c["expect"], "got": got})
    high = {"dose", "negation", "prescription", "clinical"}
    hp = [(g in high, p in high) for g, p in pairs]
    tp = sum(1 for g, p in hp if g and p)
    metrics: dict[str, Any] = {"accuracy": accuracy(pairs), "macro_f1": macro_f1(pairs), "cases": len(pairs),
                               "high_impact": prf(tp, sum(1 for g, p in hp if p and not g), sum(1 for g, p in hp if g and not p))}
    notes = ["constructed pairs (gold/variant_impact.yaml); high_impact = dose, negation, prescription or clinical — "
             "the variants a physician should see first"]
    big = None if ctx.quick else ctx.corpus_harness()
    if big is not None:
        st = big.capabilities.get("study")
        res = st.variants(books=["jc_b000", "cm_shanghan_npm"], chapter="辨太阳病", max_chars=12000)
        queue = res.get("review_queue") or []
        metrics["real"] = {"units": res["summary"]["units"], "by_impact": res.get("by_impact"),
                           "queue_top10_high": sum(1 for q in queue[:10] if q["impact"] in high)}
        notes.append("real: 伤寒论 太阳篇, the 笈成 宋本 against CMETA's 台北故宫 宋本 (12 000 characters)")
    return SuiteResult("variant_impact", metrics, details, notes=notes)


def clause(ctx: EvalContext) -> SuiteResult:
    """ClauseEval (条文结构): clauses of the 伤寒论 and 金匮要略 cut into pieces, each annotated with its role
    (gold/clause.yaml) — piece role accuracy and per-role precision/recall; with the full corpus, the forms of the
    伤寒论's clauses and the share of its pieces that no rule reads (其他)."""
    from ..plugins.classics.study import StudyService

    h = ctx.default
    study = StudyService(h.pack, h.corpus)
    gold = ctx.gold("clause")["clauses"]
    pairs: list[tuple[str, str]] = []
    details = []
    split_ok = 0
    for c in gold:
        res = study.clause(c["text"])
        got = [x["role"] for x in res["pieces"]]
        split_ok += len(got) == len(c["roles"])
        for want, have, piece in zip(c["roles"], got, res["pieces"]):
            pairs.append((want, have))
            if want != have:
                details.append({"piece": piece["text"], "expected": want, "got": have, "rule": piece["rule"]})
    roles = sorted({w for w, _ in pairs})
    per_role = {r: prf(sum(1 for w, g in pairs if w == r and g == r), sum(1 for w, g in pairs if g == r and w != r),
                       sum(1 for w, g in pairs if w == r and g != r))["f1"] for r in roles}
    metrics: dict[str, Any] = {"piece_accuracy": accuracy(pairs), "macro_f1": macro_f1(pairs),
                               "segmentation": round(split_ok / len(gold), 4), "pieces": len(pairs), "per_role_f1": per_role}
    notes = ["gold/clause.yaml: sixteen clauses of the 伤寒论 and 金匮要略 (public domain), roles annotated by the author "
             "following clause.yaml's definitions"]
    big = None if ctx.quick else ctx.corpus_harness()
    if big is not None:
        prof = big.capabilities.get("study").clause(work="shanghanlun", passages=800)
        total = sum(prof["roles"].values()) or 1
        metrics["real"] = {"clauses": prof["clauses"], "other_share": round(prof["roles"].get("其他", 0) / total, 4),
                           "top_forms": [f["form"] for f in prof["forms"][:5]]}
        notes.append("real: the main text of the 伤寒论's fullest witness; other_share = pieces no rule reads (dialogues "
                     "of 平脉法, numbering, notes)")
    return SuiteResult("clause", metrics, details, notes=notes)


def glosses(ctx: EvalContext) -> SuiteResult:
    """GlossEval (训诂): sentences in the forms of the commentaries with the gloss they give the term, and traps (a
    clause ending in the term, 反折 that is not a 反切) (gold/glosses.yaml); with the full corpus, whether the glosses
    of 几几 known from the commentaries are found (成无己's 伸颈之貌 first)."""
    from ..plugins.classics.study import StudyService

    h = ctx.default
    study = StudyService(h.pack, h.corpus)
    finder = study._glosses
    cases = ctx.gold("glosses")["cases"]
    tp = fp = fn = correct = 0
    details = []
    for c in cases:
        norm, term = h.pack.variants.normalize_text(c["text"]), h.pack.variants.normalize_text(c["term"])
        found = [g for g in finder.find(norm, c["text"]) if h.pack.variants.normalize_text(g["head"]) == term
                 or (h.pack.variants.normalize_text(g["head"]).endswith(term) and len(g["head"]) - len(term) <= 1)]
        got = (found[0]["gloss"], found[0]["kind"]) if found else ("", "none")
        want = (c["gloss"], c["kind"])
        correct += got == want
        if want[1] != "none" and got == want:
            tp += 1
        elif got[1] != "none":
            fp += 1
            fn += want[1] != "none"
        elif want[1] != "none":
            fn += 1
        if got != want:
            details.append({"text": c["text"], "expected": want, "got": got})
    metrics: dict[str, Any] = {"accuracy": round(correct / len(cases), 4), "glosses": prf(tp, fp, fn), "cases": len(cases)}
    notes = ["gold/glosses.yaml: glosses in the set forms and traps; a gloss counts when its words and its kind are right"]
    big = None if ctx.quick else ctx.corpus_harness()
    if big is not None:
        res = big.capabilities.get("study").glosses("几几")
        readings = {r["gloss"]: r for r in res["readings"]}
        first = readings.get("伸颈之貌", {}).get("first", {})
        metrics["real"] = {"glosses": res["count"], "readings": len(res["readings"]),
                           "成无己_伸颈之貌_first": first.get("by") == "成无己"}
        notes.append("real: the glosses of 几几 in the store; 成无己's 伸颈之貌 (1144) is the earliest known")
    return SuiteResult("glosses", metrics, details, notes=notes)


def _trigrams(s: str) -> set[str]:
    return {s[i: i + 3] for i in range(len(s) - 2)}


def _volume_number(label: str | None) -> int | None:
    from ..plugins.classics.study.fragments import cn_number

    m = re.search(r"[一二三四五六七八九十百]+", label or "")
    return cn_number(m.group(0)) if m else None


__all__ = ["argument", "cases", "clause", "collation", "commentaries", "disputes", "fragments", "glosses", "punctuation",
           "reuse", "senses", "stratigraphy", "variant_impact"]
