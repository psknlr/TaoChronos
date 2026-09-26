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


__all__ = ["cases", "collation", "reuse", "stratigraphy"]
