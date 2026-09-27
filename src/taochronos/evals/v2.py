"""TaoChronos-Eval suites of the V2 capabilities: entities (T7) and the others added with them.

A model can be measured too: set ``TAOCHRONOS_EVAL_LLM=provider:model`` (e.g. ``minimax:MiniMax-M2.7``) and the suites
that have a model phase run it beside the rules, and report both.  Without it only the rules are measured — the numbers
the documentation gives are those.
"""

from __future__ import annotations

import os
from typing import Any

from .base import EvalContext, SuiteResult


def eval_judge(ctx: EvalContext, harness: Any) -> Any:
    """The judge named by TAOCHRONOS_EVAL_LLM, or None."""
    spec = os.environ.get("TAOCHRONOS_EVAL_LLM")
    if not spec:
        return None
    try:
        return harness.judge(spec, max_calls=int(os.environ.get("TAOCHRONOS_EVAL_LLM_CALLS", "120")))
    except ValueError:
        return None


def _gold_spans(sentences: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    out = []
    for sent in sentences:
        text, pos, gold = sent["text"], {}, []
        for surface, type_ in sent["entities"]:
            start = text.find(surface, pos.get(surface, 0))
            if start < 0:
                raise ValueError(f"gold entity {surface!r} not in {text!r}")
            pos[surface] = start + len(surface)
            gold.append({"start": start, "end": start + len(surface), "type": type_, "text": surface})
        out.append((text, gold))
    return out


def _ner(study: Any, cases: list[tuple[str, list[dict[str, Any]]]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from ..plugins.classics.study.entities import score_entities

    gold_all, pred_all, details = [], [], []
    offset = 0
    for text, gold in cases:
        res = study.entities(text)
        pred = [{"start": e["start"], "end": e["end"], "type": e["type"]} for e in res["entities"]]
        g = {(x["start"], x["end"], x["type"]) for x in gold}
        p = {(x["start"], x["end"], x["type"]) for x in pred}
        if g != p:
            details.append({"text": text, "missed": sorted(f"{text[s:e]}:{t}" for s, e, t in g - p),
                            "extra": sorted(f"{text[s:e]}:{t}" for s, e, t in p - g)})
        gold_all += [dict(x, start=x["start"] + offset, end=x["end"] + offset) for x in gold]
        pred_all += [dict(x, start=x["start"] + offset, end=x["end"] + offset) for x in pred]
        offset += len(text) + 1
    s = score_entities(gold_all, pred_all)
    return s, details


def entities(ctx: EvalContext) -> SuiteResult:
    """EntityEval (T7): entity P/R/F1 (exact span and type) on sentences of the classics and sentences written for the
    test — the development set the rules were written on (gold/ner.yaml) and a set annotated before the recognizer ever
    ran on it (gold/ner_heldout.yaml, the fairer estimate); per type; with a model (TAOCHRONOS_EVAL_LLM), both again."""
    from ..plugins.classics.study import StudyService

    h = ctx.default
    study = StudyService(h.pack, h.corpus)
    metrics: dict[str, Any] = {}
    details: list[dict[str, Any]] = []
    for name in ("ner", "ner_heldout"):
        cases = _gold_spans(ctx.gold(name)["sentences"])
        s, d = _ner(study, cases)
        key = "development" if name == "ner" else "held_out"
        metrics[key] = {"precision": s["precision"], "recall": s["recall"], "f1": s["f1"], "span_f1": s["span_only"]["f1"],
                        "entities": s["tp"] + s["fn"], "sentences": len(cases)}
        metrics[f"{key}_per_type"] = {t: v["f1"] for t, v in s["per_type"].items()}
        details += [dict(x, set=key) for x in d]
    notes = ["gold/ner.yaml is the development set; gold/ner_heldout.yaml was annotated before the recognizer ran on it "
             "(first measured F1 0.757; 0.776 after fixing two bugs it revealed — chained processing words, 破八片 read "
             "as a dose — with no rule added for its content)"]
    judge = eval_judge(ctx, h)
    if judge is not None:
        study.judge = judge
        for name in ("ner", "ner_heldout"):
            s, _ = _ner(study, _gold_spans(ctx.gold(name)["sentences"]))
            metrics[("development" if name == "ner" else "held_out") + "_with_model"] = {
                "precision": s["precision"], "recall": s["recall"], "f1": s["f1"], "judge": judge.label}
        metrics["model_usage"] = judge.report()["budget"]
        notes.append(f"with the model {judge.label}: ambiguous spans typed and missed entities added (spans checked)")
    else:
        notes.append("no model measured (set TAOCHRONOS_EVAL_LLM=provider:model to measure the rule + model pipeline)")
    return SuiteResult("entities", metrics, details, notes=notes)


def places(ctx: EvalContext) -> SuiteResult:
    """PlaceEval (T27): signatures of prefaces and colophons (place + writer + verb) and statements of a physician's
    place read right, traps reading nothing (gold/places.yaml); the share of the physicians of physicians.yaml with a
    place; with the full corpus, how many works are placed, whether the places the texts state for physicians agree with
    the curated ones, and the regions that lead 湿热 by period."""
    from ..plugins.classics.study import StudyService

    h = ctx.default
    study = StudyService(h.pack, h.corpus)
    reader = study._places
    gold = ctx.gold("places")
    details: list[dict[str, Any]] = []

    def score(rows: list[dict[str, Any]], read: Any) -> dict[str, Any]:
        tp = fp = fn = person_ok = 0
        for row in rows:
            got = read(row["text"])
            first = got[0] if got else None
            want = row["place"]
            if want and first and first["place"] == want:
                tp += 1
                person_ok += first.get("person") == row["person"]
            else:
                fp += bool(first) and (not want or first["place"] != want)
                fn += bool(want)
                details.append({"text": row["text"], "expected": want, "got": first["place"] if first else None})
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0,
                "person_accuracy": round(person_ok / tp, 3) if tp else None, "cases": len(rows)}

    metrics: dict[str, Any] = {
        "signatures": score(gold["signatures"], lambda t: reader.read_signatures(None, t)),
        "stated": score(gold["stated"], reader.read_stated),
    }
    people = [reader.person_row(pid) for pid in reader.persons]
    metrics["physicians_placed"] = round(sum(1 for r in people if r["place"]) / len(people), 3)
    notes = ["gold/places.yaml: signatures and statements written in the forms of real prefaces and biographies, with traps"]
    big = None if ctx.quick else ctx.corpus_harness()
    if big is not None:
        s = big.capabilities.get("study")
        over = s.places()
        agree = checked = 0
        for pid in ("li_gao", "zhu_zhenheng", "zhang_ji", "ye_gui", "wu_tang", "li_shizhen", "zhang_jiebin", "liu_wansu",
                    "xue_xue", "wu_youxing", "li_zhongzi", "yu_chang"):
            r = s.places(person=pid)
            if r["places_in_texts"]:
                checked += 1
                agree += bool(r["curated_confirmed"])
        term = s.places(term="湿温")
        qing = next((x for x in term["rows"] if x["period"] == "清" and x["region"] == "江南"), None)
        metrics["real"] = {"works_placed": over["placed"]["works"], "works": over["placed"]["works_total"],
                           "works_by": over["placed"]["works_by"], "curated_confirmed": f"{agree}/{checked}",
                           "湿温_清_江南": ({k: qing[k] for k in ("works_with", "works", "share", "rest_share", "z", "q")}
                                         if qing else None)}
        notes.append("real: works placed by author and signature; the places the texts state for twelve physicians against "
                     "the curated ones (a county agrees with its prefecture); the share of 江南's Qing works using 湿温 "
                     "against the other regions'")
    return SuiteResult("places", metrics, details, notes=notes)


def translation(ctx: EvalContext) -> SuiteResult:
    """TranslationEval (T10): the presentism guardrail on statements and translations (gold/presentism.yaml: equations,
    retrospective diagnoses, modern names a translation adds, and comparisons that must pass); the five layers' promises
    on the demo corpus (the original returned as given, 白文 punctuated without a character changed); the evidence layer
    on a synthetic commentary (the doublets glossed by who first glossed them); with the full corpus, 几几 in the 伤寒论
    clause glossed from the commentaries; with a model (TAOCHRONOS_EVAL_LLM), the share of translations that pass."""
    import tempfile
    from pathlib import Path

    from ..plugins.classics import Corpus
    from ..plugins.classics.study import StudyService
    from ..verification.presentism import guard_from_pack
    from .textual import _write_corpus

    h = ctx.default
    guard = guard_from_pack(h.pack)
    cases = ctx.gold("presentism")["cases"]
    details: list[dict[str, Any]] = []
    confusion: dict[str, dict[str, int]] = {}
    for c in cases:
        found = guard.check(c["text"], source=c.get("source"))
        got = found[0].kind if found else "none"
        confusion.setdefault(c["expect"], {}).setdefault(got, 0)
        confusion[c["expect"]][got] += 1
        if got != c["expect"]:
            details.append({"text": c["text"], "expected": c["expect"], "got": got})
    flagged = sum(n for want, row in confusion.items() for got, n in row.items() if got != "none")
    right = sum(row.get(want, 0) for want, row in confusion.items() if want != "none")
    should = sum(n for want, row in confusion.items() if want != "none" for n in row.values())
    metrics: dict[str, Any] = {"presentism": {"accuracy": round(sum(row.get(w, 0) for w, row in confusion.items()) / len(cases), 3),
                                              "precision": round(right / flagged, 3) if flagged else 0.0,
                                              "recall": round(right / should, 3) if should else 0.0, "cases": len(cases)}}
    study = StudyService(h.pack, h.corpus)
    kept = punct_ok = 0
    sample = [p for p in list(h.corpus.passages())[:24] if len(p.text) >= 12]
    for p in sample:
        r = study.translate(p.text)
        kept += r["original"] == p.text[:1200]
        punct_ok += r["preserved"]
    metrics["layers"] = {"texts": len(sample), "original_kept": kept, "preserved": punct_ok}
    root = _write_corpus(Path(tempfile.mkdtemp(prefix="taochronos-gloss-")), [
        ("zhu", "注解伤寒论", "成无己", 1144, "注本", ["几几者，伸颈之貌也。", "啬啬者，不足也，恶寒之貌也。",
                                                    "淅淅者，洒淅也，恶风之貌也。", "翕翕者，熇熇然而热也。"]),
        ("shl", "伤寒论", "张机", 205, "医经", ["太阳中风，啬啬恶寒，淅淅恶风，翕翕发热，鼻鸣干呕者，桂枝汤主之。"]),
    ], "translation eval")
    corpus = Corpus.load(root)
    corpus.normalize = h.pack.variants.normalize_text
    small = StudyService(h.pack, corpus)
    want = {"啬啬": "不足", "淅淅": "洒淅", "翕翕": "熇熇然而热"}
    got = {it["term"]: it["glosses"] for it in small.translate("太阳中风，啬啬恶寒，淅淅恶风，翕翕发热，鼻鸣干呕者，桂枝汤主之。")["interpreted"]}
    grounded = sum(1 for term, g in want.items() if any(x["gloss"] == g and x["by"] == "成无己" for x in got.get(term, [])))
    metrics["grounding"] = {"doublets": len(want), "glossed_by_their_commentator": grounded}
    notes = ["gold/presentism.yaml: equations, retrospective diagnoses, modern names a translation adds, and bounded "
             "comparisons that must pass", "grounding: a synthetic 注解伤寒论 glossing the doublets of the 桂枝汤 clause"]
    big = None if ctx.quick else ctx.corpus_harness()
    if big is not None:
        r = big.capabilities.get("study").translate("太阳病，项背强几几，反汗出恶风者，桂枝加葛根汤主之。")
        jiji = next((it for it in r["interpreted"] if it["term"] == "几几"), None)
        metrics["real"] = {"几几_glosses": len(jiji["glosses"]) if jiji else 0,
                           "几几_first": (jiji["glosses"][0]["by"] if jiji and jiji["glosses"] else None)}
        notes.append("real: the glosses the store's commentaries give 几几, the most repeated first")
    judge = eval_judge(ctx, h)
    if judge is not None:
        study.judge = judge
        texts = [p.text for p in sample[:8]]
        results = [study.translate(t)["translated"] for t in texts]
        metrics["with_model"] = {"texts": len(texts), "passed_checks": sum(1 for x in results if x and x.get("ok")),
                                 "judge": judge.label}
    return SuiteResult("translation", metrics, details, notes=notes)


def _synthetic_pages(texts: list[str], n: int, seed: int, jitter: float, characters: bool = False) -> list[tuple[Any, ...]]:
    import random
    import re as _re

    from ..plugins.classics.vision.layout import Token
    from ..plugins.classics.vision.synth import layout_text, tokens

    rng = random.Random(seed)
    pages = []
    for i in range(n):
        chars = list(rng.choice(texts))
        out, k = [], 0
        while k < len(chars):
            if rng.random() < 0.08:
                length = rng.randint(2, 18)
                out.append("（" + "".join(chars[k:k + length]) + "）")
                k += length
            else:
                out.append(chars[k])
                k += 1
        segs, truth = layout_text(_re.sub(r"）（", "", "".join(out)), rows=rng.randint(14, 22), max_cols=rng.randint(6, 10),
                                  title="伤寒论卷一" if rng.random() < .7 else None, leaf=rng.choice(["三", "十二", None]),
                                  head_note="眉批" if rng.random() < .3 else None)
        toks, kinds = tokens(segs, seed=seed * 1000 + i, jitter=jitter)
        if characters:  # an engine that reports every character on its own
            split = []
            for t in toks:
                if kinds[t.id] in ("main", "commentary") and len(t.text) > 1:
                    ch = t.h / len(t.text)
                    for j, c in enumerate(t.text):
                        tid = f"{t.id}.{j}"
                        split.append(Token(c, t.x, t.y + j * ch, t.w, ch, id=tid))
                        kinds[tid] = kinds[t.id]
                else:
                    split.append(t)
            toks = split
        pages.append((toks, kinds, truth))
    return pages


def layout(ctx: EvalContext) -> SuiteResult:
    """LayoutEval (T1–T2): synthetic pages built from the demo corpus's text as a 刻本 lays it out (vertical columns right
    to left, 双行小注, a 版心 with title and leaf number, head-notes), reported as an OCR engine reports them (boxes
    jittered and shuffled; lines, or single characters): is the reading order recovered (the running text exactly,
    and its character error rate), is each block's kind right (notes, 版心, 书眉); do the ALTO, hOCR, PAGE and PaddleOCR
    readers give the same page; does the comparison find planted OCR errors in the store's transcriptions."""
    import random
    import re as _re

    from ..plugins.classics.vision import analyse
    from ..plugins.classics.vision.formats import read_alto, read_hocr, read_page, read_paddle
    from ..plugins.classics.vision.ocr import compare

    h = ctx.default
    texts = [_re.sub(r"[，。、；：？！「」『』（）()\s]", "", p.text) for p in h.corpus.passages() if len(p.text) > 40]
    metrics: dict[str, Any] = {}
    details: list[dict[str, Any]] = []
    for name, jitter, chars in (("lines", 0.05, False), ("lines_noisy", 0.12, False), ("characters", 0.05, True)):
        pages = _synthetic_pages(texts, 60 if ctx.quick else 200, 7, jitter, chars)
        exact = cer = kinds_ok = kinds_n = note_tp = note_fp = note_fn = 0
        for toks, kinds, truth in pages:
            g = analyse(toks)
            exact += g.text == truth
            cer += compare(g.text, truth, windowed=False)["cer"] or 0.0
            for b in g.blocks:
                for pid in b.parts:
                    kinds_n += 1
                    kinds_ok += kinds.get(pid) == b.kind
                    note_tp += b.kind == "commentary" and kinds.get(pid) == "commentary"
                    note_fp += b.kind == "commentary" and kinds.get(pid) != "commentary"
                    note_fn += b.kind != "commentary" and kinds.get(pid) == "commentary"
            if g.text != truth and len(details) < 10:
                details.append({"set": name, "truth": truth[:80], "read": g.text[:80]})
        metrics[name] = {"pages": len(pages), "exact_order": round(exact / len(pages), 3), "mean_cer": round(cer / len(pages), 4),
                         "block_kind": round(kinds_ok / max(1, kinds_n), 3),
                         "notes_f1": round(2 * note_tp / max(1, 2 * note_tp + note_fp + note_fn), 3)}
    # the readers: one page written in each format, read back
    toks, _, truth = _synthetic_pages(texts, 1, 11, 0.02)[0]
    alto = "<alto><Layout><Page>" + "".join(
        f'<TextLine ID="{t.id}" HPOS="{t.x}" VPOS="{t.y}" WIDTH="{t.w}" HEIGHT="{t.h}"><String CONTENT="{t.text}"/></TextLine>'
        for t in toks) + "</Page></Layout></alto>"
    hocr = "<div class='ocr_page'>" + "".join(
        f"<span class='ocr_line' title='bbox {int(t.x)} {int(t.y)} {int(t.x + t.w)} {int(t.y + t.h)}'>{t.text}</span>"
        for t in toks) + "</div>"
    page = "<PcGts><Page>" + "".join(
        f'<TextLine id="{t.id}"><Coords points="{t.x},{t.y} {t.x + t.w},{t.y} {t.x + t.w},{t.y + t.h} {t.x},{t.y + t.h}"/>'
        f"<TextEquiv><Unicode>{t.text}</Unicode></TextEquiv></TextLine>" for t in toks) + "</Page></PcGts>"
    paddle = [[[[t.x, t.y], [t.x + t.w, t.y], [t.x + t.w, t.y + t.h], [t.x, t.y + t.h]], [t.text, 0.99]] for t in toks]
    metrics["formats"] = {name: analyse(reader(data)).text == truth for name, reader, data in
                          (("alto", read_alto, alto), ("hocr", read_hocr, hocr), ("page", read_page, page), ("paddle", read_paddle, paddle))}
    # the comparison: planted substitutions in passages of the store, found and located
    vision = h.capabilities.get("vision")
    rng = random.Random(3)
    long = [p for p in h.corpus.passages() if len(_re.sub(r"[^一-鿿]", "", p.text)) >= 60]
    found = located = 0
    for p in long[:12]:
        han = _re.sub(r"[^一-鿿]", "", p.text)[:60]
        k = rng.randrange(5, 55)
        wrong = "目" if han[k] != "目" else "日"
        r = vision.compare(han[:k] + wrong + han[k + 1:])
        found += r["substitutions"] == 1 and r["insertions"] == 0 and r["deletions"] == 0
        located += bool(r["located"]) and r["located"][0] == p.id
    metrics["compare"] = {"passages": min(12, len(long)), "one_substitution_found": found, "located": located}
    notes = ["synthetic pages from the demo corpus (notes planted at random, 版心 and 书眉 added); an engine's lines or "
             "characters, boxes jittered by 5 % (12 % noisy) of a character and shuffled",
             "a page carrying more than nine characters of note for one of text is read as all text (the main size cannot "
             "be told), the known limit of reading layout from boxes alone"]
    return SuiteResult("layout", metrics, details, notes=notes)


__all__ = ["entities", "eval_judge", "layout", "places", "translation"]


def _finding_sets(packet: dict[str, Any]) -> tuple[set[str], set[str], set[str]]:
    """(presenting, negated, optional or conditional) phenotype ids of a packet."""
    pres, neg, opt = set(), set(), set()
    for f in packet["findings"]:
        if f["status"] != "presenting":
            continue
        if f["optional"] or f["conditional"]:
            opt.add(f["phenotype"])
        elif f["negated"]:
            neg.add(f["phenotype"])
        else:
            pres.add(f["phenotype"])
    # a finding the text states plainly somewhere is presenting, whatever else it says of it elsewhere
    return pres, neg - pres, opt - pres - neg


def _gold_sets(rows: list[str]) -> tuple[set[str], set[str], set[str]]:
    pres = {r for r in rows if r[0] not in "!?"}
    return pres, {r[1:] for r in rows if r.startswith("!")}, {r[1:] for r in rows if r.startswith("?")}


def _prf(tp: int, fp: int, fn: int) -> dict[str, float]:
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0}


def _score_packets(cases: list[tuple[str, dict[str, Any], list[str]]], details: list[dict[str, Any]]) -> dict[str, Any]:
    tp = fp = fn = 0
    bound_ok = bound_n = 0
    for name, packet, gold in cases:
        got_p, got_n, got_o = _finding_sets(packet)
        want_p, want_n, want_o = _gold_sets(gold)
        got_all, want_all = got_p | got_n | got_o, want_p | want_n | want_o
        tp += len(got_all & want_all)
        fp += len(got_all - want_all)
        fn += len(want_all - got_all)
        for pid in got_all & want_all:  # was the finding bounded right (negated, optional or conditional, presenting)?
            bound_n += 1
            bound_ok += ((pid in got_n) == (pid in want_n)) and ((pid in got_o) == (pid in want_o))
        if got_all != want_all or got_n != want_n or got_o != want_o:
            details.append({"case": name, "missing": sorted(want_all - got_all), "extra": sorted(got_all - want_all),
                            "negated": {"got": sorted(got_n), "want": sorted(want_n)},
                            "optional": {"got": sorted(got_o), "want": sorted(want_o)}})
    return {**_prf(tp, fp, fn), "bounds_accuracy": round(bound_ok / bound_n, 3) if bound_n else None, "cases": len(cases)}


def bridge(ctx: EvalContext) -> SuiteResult:
    """BridgeEval (AMBE): the AncientPhenotypePacket against gold findings (dev sentences; with the full corpus, a
    held-out sample annotated blind), and the mapping of canonical descriptions to the profile a clinician-historian
    names first (top-1, top-3), negative cases that must stay low, every statement through the presentism guard, and
    every HPO identifier present in the closure's release.  With TAOCHRONOS_EVAL_LLM, the model phase runs too."""
    h = ctx.default
    b = h.capabilities.get("bridge")
    gold = ctx.gold("bridge")
    details: list[dict[str, Any]] = []
    judge = eval_judge(ctx, h)
    b.study.judge = None
    dev = [(row["text"], b.phenotype(row["text"]), row["findings"]) for row in gold["phenotypes"]]
    metrics: dict[str, Any] = {"phenotypes": _score_packets(dev, details)}
    order = ["insufficient", "low", "moderate", "high"]
    top1 = top3 = pos = neg_ok = neg = guard_ok = 0
    levels: dict[str, int] = {}
    for row in gold["mapping"]:
        r = b.map(row["text"])
        cands = r["candidates"]
        guard_ok += not r["guard"]
        lead = cands[0] if cands else None
        if lead:
            levels[lead["level"]] = levels.get(lead["level"], 0) + 1
        want = [row["top"]] if "top" in row else row.get("top3", [])
        if want:
            pos += 1
            ids = [c["disease"] for c in cands]
            hit1 = bool(ids) and ids[0] == want[0] if "top" in row else bool(ids) and ids[0] in want
            hit3 = all(w in ids[:3] for w in want) if "top3" in row else want[0] in ids[:3]
            top1 += hit1
            top3 += hit3
            if not hit1 or not hit3:
                details.append({"case": row["text"], "want": want, "got": [(c["disease"], c["level"]) for c in cands[:3]]})
        if "max_level" in row:
            neg += 1
            worst = max((order.index(c["level"]) for c in cands), default=0)
            ok = worst <= order.index(row["max_level"])
            neg_ok += ok
            if not ok:
                details.append({"case": row["text"], "max_level": row["max_level"], "got": [(c["disease"], c["level"]) for c in cands[:3]]})
    metrics["mapping"] = {"top1": round(top1 / pos, 3) if pos else None, "top3": round(top3 / pos, 3) if pos else None,
                          "cases": pos, "caps_respected": f"{neg_ok}/{neg}", "guard_clean": f"{guard_ok}/{len(gold['mapping'])}",
                          "lead_levels": levels}
    data = b.data
    metrics["ontology"] = {"hpo_terms": len(data.hpo_ids()), "phenotypes": len(data.phenotypes), "profiles": len(data.diseases),
                           "hierarchy_release": data.closure_release, "release": data.hpo_release,
                           "closure_terms": len(data.ancestors)}
    notes = ["phenotypes and mapping: dev cases written while the reader was built (gold/bridge.yaml); levels are not "
             "calibrated and the mapping cases test the construct, not a diagnosis"]
    big = None if ctx.quick else ctx.corpus_harness()
    if big is not None:
        bb = big.capabilities.get("bridge")
        bb.study.judge = None
        rows = []
        for row in gold["heldout"]:
            try:
                rows.append((row["passage"], bb.phenotype(passage_id=row["passage"]), row["findings"]))
            except ValueError:
                continue
        held: list[dict[str, Any]] = []
        metrics["heldout"] = _score_packets(rows, held)
        details += [{"heldout": True, **d} for d in held]
        notes.append("heldout: 12 passages drawn at random from 65 clinical works of the full corpus and annotated from the "
                     "text before the reader ran on them (no forms added after)")
    if judge is not None:
        b.study.judge = judge
        try:
            model = [(row["text"], b.phenotype(row["text"]), row["findings"]) for row in gold["phenotypes"]]
            metrics["phenotypes_with_model"] = _score_packets(model, [])
            metrics["judge"] = judge.report()
        finally:
            b.study.judge = None
    return SuiteResult("bridge", metrics, details, notes=notes)


def audit(ctx: EvalContext) -> SuiteResult:
    """AuditEval (S15): claims against the verdict and the claim kinds the audit must give (gold/audit.yaml: verbatim and
    fabricated quotes, wrong works, equations and bounded comparisons, inference leaps and hypotheses, clinical advice,
    glosses, caveats), and the safety flags."""
    h = ctx.default
    a = h.capabilities.get("audit")
    a.study.judge = None
    gold = ctx.gold("audit")
    details: list[dict[str, Any]] = []
    right = kinds_right = 0
    confusion: dict[str, int] = {}
    for row in gold["claims"]:
        r = a.audit(row["text"], modern=False)
        got_kinds = [c["kind"] for c in r["claims"]]
        ok, kok = r["verdict"] == row["verdict"], got_kinds == row["kinds"]
        right += ok
        kinds_right += kok
        if not ok:
            key = f"{row['verdict']}→{r['verdict']}"
            confusion[key] = confusion.get(key, 0) + 1
        if not ok or not kok:
            details.append({"claim": row["text"], "want": row["verdict"], "got": r["verdict"], "kinds": got_kinds, "want_kinds": row["kinds"]})
    safe_ok = 0
    for row in gold["safety"]:
        got = sorted(x["material"] for x in a.audit(row["text"], modern=False)["safety"])
        safe_ok += got == sorted(row["materials"])
        if got != sorted(row["materials"]):
            details.append({"safety": row["text"], "want": row["materials"], "got": got})
    n = len(gold["claims"])
    metrics = {"verdict_accuracy": round(right / n, 3), "kind_accuracy": round(kinds_right / n, 3), "claims": n,
               "confusions": confusion, "safety": f"{safe_ok}/{len(gold['safety'])}",
               "false_supported": sum(1 for d in details if d.get("got") == "SUPPORTED")}
    return SuiteResult("audit", metrics, details, notes=["dev cases written with the checks (gold/audit.yaml); offline: no modern evidence"])


def modern(ctx: EvalContext) -> SuiteResult:
    """ModernEval (S13–S14): evidence typing from publication types, titles and MeSH (gold/modern.yaml), the cross-level
    guard, and the RWD compiler on the synthetic OMOP database — the planted association recovered, every query checked."""
    import tempfile
    from pathlib import Path

    from ..plugins.modern import rwd
    from ..plugins.modern.evidence_types import type_record
    from ..protocol.modern import EvidenceType, cross_level
    from ..verification.audit import claim_level

    gold = ctx.gold("modern")
    details: list[dict[str, Any]] = []
    typed = 0
    for row in gold["typing"]:
        et, _, rule = type_record(row["pubtypes"], row["title"], "", row.get("mesh"))
        typed += et.value == row["want"]
        if et.value != row["want"]:
            details.append({"title": row["title"], "want": row["want"], "got": et.value, "rule": rule})
    guarded = 0
    for row in gold["guard"]:
        carries = cross_level(claim_level(row["claim"]), EvidenceType(row["type"])) is None
        guarded += carries == row["carries"]
        if carries != row["carries"]:
            details.append({"claim": row["claim"], "type": row["type"], "want": row["carries"], "got": carries})
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "omop.sqlite"
        rwd.synthesize(db)
        import sqlite3

        con = sqlite3.connect(db)
        spec = rwd.spec_from_question(gold["rwd"]["question"], con)
        con.close()
        sql, params = rwd.compile_spec(spec)
        res = rwd.run(spec, db)
    rr = (res.get("risk_ratio") or {}).get("estimate")
    direction = None if rr is None else ("lower" if rr < 1 else "higher")
    metrics = {"typing_accuracy": round(typed / len(gold["typing"]), 3), "typing_cases": len(gold["typing"]),
               "guard_accuracy": round(guarded / len(gold["guard"]), 3), "guard_cases": len(gold["guard"]),
               "rwd": {"sql_checks": rwd.check_sql(sql, params) == [], "risk_ratio": res.get("risk_ratio"),
                       "planted_direction_recovered": direction == gold["rwd"]["planted_direction"],
                       "bad_sql_refused": all(rwd.check_sql(q, []) for q in ("DROP TABLE person", "SELECT * FROM secrets",
                                                                            "SELECT 1 FROM person WHERE year_of_birth = '1950'"))}}
    return SuiteResult("modern", metrics, details, notes=["dev cases (gold/modern.yaml); PubMed is not queried by the suite",
                                                          "RWD on synthetic people: a check of the compiler, not a finding"])


def workflow(ctx: EvalContext) -> SuiteResult:
    """WorkflowEval (V2 runtime): the registry of skills and core agents is valid; questions compile into the skills they
    need and not those they do not (gold/workflow.yaml); one question runs end to end, resumes from its workspace, and its
    statements pass the audit without an UNSUPPORTED verdict."""
    from ..engine.workflow import WorkflowCompiler, ask, load_core_agents, load_manifests, validate_registry

    h = ctx.default
    skills = load_manifests(ctx.home / "skills" / "manifests")
    agents = load_core_agents(ctx.home / "agents" / "core")
    errors = validate_registry(skills, agents, h.scheduler.registry, set(h.specs))
    gold = ctx.gold("workflow")
    details: list[dict[str, Any]] = []
    ok = 0
    compiler = WorkflowCompiler(skills, h)
    for row in gold["questions"]:
        plan = compiler.plan(row["q"])
        missing = sorted(set(row["need"]) - set(plan.skills))
        extra = sorted(set(row["absent"]) & set(plan.skills))
        ok += not missing and not extra
        if missing or extra:
            details.append({"question": row["q"], "missing": missing, "unwanted": extra, "plan": plan.skills})
    h.capabilities.get("study").judge = None
    run = ask(h, gold["questions"][0]["q"], run_id="eval", resume=False)
    again = ask(h, gold["questions"][0]["q"], run_id="eval")
    audit_step = next(s for s in run["steps"] if s["skill"] == "S15")
    verdicts = [r["result"]["verdict"] for r in audit_step["results"] if r["tool"] == "audit.claim"]
    metrics = {"registry_errors": len(errors), "skills": len(skills), "agents": len(agents),
               "plans_right": f"{ok}/{len(gold['questions'])}",
               "run": {"steps": len(run["steps"]), "calls": sum(s["calls"] for s in run["steps"]),
                       "resumed_all": all(s["cached"] == s["calls"] for s in again["steps"]),
                       "statements": len(verdicts), "verdicts": {v: verdicts.count(v) for v in sorted(set(verdicts))}}}
    return SuiteResult("workflow", metrics, details + [{"registry_error": e} for e in errors],
                       notes=["dev questions (gold/workflow.yaml); the run uses the demo corpus and the rules only"])

