"""异文分级 — how much a variant reading matters: the Variant Impact Score.

Most variants of the medical classics are harmless (之 for 而, 於 for 于, a transposed pair); a few change what a
physician would do: a dose (桂枝三两 / 二两), a negation or a modal word (可发汗 / 不可发汗, 宜 / 忌), a drug or a
formula, a symptom or a pulse.  Each reading of a variant unit is put in one class, the first that applies:

=============  =====  =====================================================================================
class          score  when (in this order)
=============  =====  =====================================================================================
orthographic   0.05   the readings differ only in the spelling of the same words (collation.yaml)
lacuna         0.30   a witness has a lacuna mark (□, 〓) where the others have text
structural     0.60   six or more characters added or left out (a line, a note, a formula heading)
dose           1.00   a numeral or a measure that is part of a dose or a frequency (三两, 半升, 日三服) differs
negation       0.95   a negation or a modal word (不 勿 毋 无 非 未 莫, 可 宜 忌 禁 当 必) differs
order          0.35   the same characters in another order (倒文)
prescription   0.90   a drug or a formula of the lexicon differs, read in the unit's context
clinical       0.80   a symptom, pulse, sign, tongue, disease, pattern or pathogenesis term differs
structural     0.60   four or more characters added or left out
function       0.20   only function words (之 而 也 其 …) differ
lexical        0.50   any other difference
=============  =====  =====================================================================================

The classes are rules, not judgements: a dose variant in a composition is worth a physician's look first, and the
review queue of ``study variants`` is ordered by this score.  The scores order the queue; they are not probabilities.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from .variant_graph import FUNCTION_WORDS

SCORES = {"dose": 1.0, "negation": 0.95, "prescription": 0.9, "clinical": 0.8, "structural": 0.6, "lexical": 0.5,
          "order": 0.35, "lacuna": 0.3, "function": 0.2, "orthographic": 0.05}
NUMERALS = set("一二三四五六七八九十百千半廿卅两")
MEASURES = set("两钱分铢斤升合斗勺枚个片丸匕撮握茎条具粒寸尺")
NEGATION = set("不勿毋无非未莫弗")
MODAL = set("可宜忌禁当必须")
PER = set("服次剂遍沸度日")  # a frequency: 日三服, 三沸
LACUNA_MARKS = set("□〓■◻")
DRUGS = ("herb", "formula")
CLINICAL = ("symptom", "pulse", "sign", "tongue", "disease", "pattern", "pathogenesis", "condition")
LABELS = {"dose": "剂量", "negation": "否定·情态", "prescription": "方药", "clinical": "证候", "structural": "脱衍（长）",
          "lexical": "实词", "order": "倒文", "lacuna": "阙文", "function": "虚词", "orthographic": "异体"}


def _terms(text: str, lexicon: Any, categories: Iterable[str]) -> set[str]:
    cats = set(categories)
    return {m.term_id for m in lexicon.match(text, include_weak=False) if m.category in cats}


def classify(lemma: str, reading: str, context: str = "", lexicon: Any = None, *, kind: str | None = None,
             normalize: Any = None) -> dict[str, Any]:
    """The impact class of one reading against the lemma, read in the unit's context (``…〔lemma〕…``, normalised with
    ``normalize`` when it is given in the witness's own characters)."""
    if normalize is not None:
        context = normalize(context)
    if kind == "orthographic":
        return _out("orthographic", "readings differ only in spelling")
    diff = set(lemma) ^ set(reading)
    if (set(reading) | set(lemma)) & LACUNA_MARKS:
        return _out("lacuna", "a lacuna mark in one witness")
    if (not lemma or not reading) and max(len(lemma), len(reading)) >= 6:
        return _out("structural", f"{max(len(lemma), len(reading))} characters added or left out")
    if diff & (NUMERALS | MEASURES) and _dosed(lemma, reading, context):
        return _out("dose", f"numeral or measure: {''.join(sorted(diff & (NUMERALS | MEASURES)))}")
    if diff & (NEGATION | MODAL):
        return _out("negation", f"negation or modal word: {''.join(sorted(diff & (NEGATION | MODAL)))}")
    if len(lemma) >= 2 and sorted(lemma) == sorted(reading):
        return _out("order", "the same characters in another order")
    if lexicon is not None:
        left, right = (context.split("〔", 1)[0], context.split("〕", 1)[-1]) if "〔" in context else ("", "")
        before, after = left + lemma + right, left + reading + right
        drugs = _terms(before, lexicon, DRUGS) ^ _terms(after, lexicon, DRUGS)
        if drugs:
            return _out("prescription", "drug or formula: " + "、".join(sorted(t.split(":", 1)[-1] for t in drugs))[:60])
        clinical = _terms(before, lexicon, CLINICAL) ^ _terms(after, lexicon, CLINICAL)
        if clinical:
            return _out("clinical", "clinical term: " + "、".join(sorted(t.split(":", 1)[-1] for t in clinical))[:60])
    if max(len(lemma), len(reading)) >= 4 and (not lemma or not reading or abs(len(lemma) - len(reading)) >= 4):
        return _out("structural", f"{max(len(lemma), len(reading))} characters added or left out")
    if diff and diff <= FUNCTION_WORDS:
        return _out("function", "function words only")
    return _out("lexical", "a content word differs")


def _dosed(lemma: str, reading: str, context: str) -> bool:
    """A numeral or a measure that is part of a dose or a frequency (三两, 半升, 日三服), not of a word (半表半里, 一身,
    十枣汤, 寸口, 合病)."""
    left, right = (context.split("〔", 1)[0], context.split("〕", 1)[-1]) if "〔" in context else ("", "")
    for text in (lemma, reading):
        around = left[-2:] + text + right[:2]
        if re.search(f"[{''.join(NUMERALS)}][{''.join(MEASURES | PER)}]", around):
            return True
    return False


def _out(kind: str, reason: str) -> dict[str, Any]:
    return {"impact": kind, "label": LABELS[kind], "score": SCORES[kind], "reason": reason}


def unit_impact(unit: dict[str, Any], lexicon: Any = None, normalize: Any = None) -> dict[str, Any]:
    """The impact of a variant unit (``VariantUnit.to_dict()``): its readings classed, the unit taking the highest."""
    best: dict[str, Any] | None = None
    per: list[dict[str, Any]] = []
    for r in unit.get("readings", [])[1:]:
        c = classify(unit.get("lemma", ""), r.get("text", ""), unit.get("context", ""), lexicon, kind=unit.get("kind"),
                     normalize=normalize)
        per.append({"reading": r.get("text", ""), "witnesses": r.get("witnesses", []), **c})
        if best is None or c["score"] > best["score"]:
            best = c
    return {**(best or _out("function", "no variant reading")), "readings": per}


def review_queue(units: list[dict[str, Any]], *, limit: int = 60) -> list[dict[str, Any]]:
    """Units to review first: by impact, then by how many witnesses carry the variant (a reading most witnesses share
    is less likely to be one copyist's slip)."""
    scored = [u for u in units if u.get("impact") and not u.get("structural")]
    scored.sort(key=lambda u: (-u["impact"]["score"], -sum(len(r.get("witnesses", [])) for r in u.get("readings", [])[1:]),
                               u.get("start", 0)))
    return [{"id": u["id"], "impact": u["impact"]["impact"], "label": u["impact"]["label"], "score": u["impact"]["score"],
             "reason": u["impact"]["reason"], "lemma": u.get("lemma", ""), "context": u.get("context", ""),
             "readings": [{"text": r.get("text", ""), "witnesses": r.get("witnesses", [])} for r in u.get("readings", [])[1:]],
             "locator": u.get("locator", ""), "passage_id": u.get("passage_id")} for u in scored[:limit]]


__all__ = ["LABELS", "SCORES", "classify", "review_queue", "unit_impact"]
