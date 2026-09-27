"""InterpretiveEval — the second evaluation layer: hard interpretive cases, measured per case class.

Every quote in these cases is verbatim, and every one can still be read wrongly: a true quote filed under the inverse
relation, a prohibition read as a prescription because it stands beside one, a view the author cites in order to
refute it, a condition the quote leaves out, one witness's words under another's locator, a disputed date ordered by
its midpoint.  The harness reads each case with the same readers it uses in a research run (the support reading and
the statement frame, the quote locator, the corpus's date ranges) and is scored per class, with the **unsafe** errors
counted apart — a misreading that would let a false claim through (a contradicted claim read as supported, a rejected
view read as the author's, a mixed witness verified, a disputed order asserted, a straddling text put in the past).

Gold: ``evals/gold/interpretive.yaml``, split into ``dev`` (the cases behind changes already made, and their controls)
and ``heldout`` (never used to change a rule); both are reported, and only the held-out score estimates anything.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..protocol.claims import Claim, ClaimArgument, ClaimRelation, ExtractionInfo, Role
from ..protocol.documents import TemporalContext
from ..verification.provenance import find_quote
from ..verification.support import assess_support, statement_frame
from .base import EvalContext, SuiteResult

SUPPORT_CLASSES = ("relation_inversion", "negation_scope", "consequence")


class CaseError(ValueError):
    """The gold case is malformed (a quote or an argument not in its text)."""


def _text(h: Any, case: dict[str, Any]) -> tuple[str, str]:
    if "passage" in case:
        return case["passage"], h.corpus.passage(case["passage"]).text
    return f"text:{case['id']}", case["text"]


def _span(text: str, quote: str, normalize: Any) -> tuple[int, int]:
    at = text.find(quote)
    if at < 0:
        at = normalize(text).find(normalize(quote))
    if at < 0:
        raise CaseError(f"quote {quote!r} not in its text")
    return at, at + len(quote)


def _claim(h: Any, case: dict[str, Any], text: str, pid: str) -> Claim:
    normalize = h.pack.variants.normalize_text
    lo, hi = _span(text, case["quote"], normalize)
    norm_text, args = normalize(text), []
    for spec in case.get("arguments", []):
        spec = spec if isinstance(spec, dict) else {"role": spec[0], "surface": spec[1]}
        surface, role = spec["surface"], Role(spec["role"])
        if spec.get("referent"):
            args.append(ClaimArgument(role=role, surface=surface, negated=bool(spec.get("negated")), qualifiers={"referent": "之"}))
            continue
        pos, target = lo - 1, normalize(surface)
        for _ in range(int(spec.get("nth", 0)) + 1):
            pos = norm_text.find(target, pos + 1, hi)
            if pos < 0:
                raise CaseError(f"argument {surface!r} not in the quote of {case['id']}")
        args.append(ClaimArgument(role=role, surface=surface, start=pos, end=pos + len(surface), negated=bool(spec.get("negated"))))
    return Claim(id=f"clm_{case['id']}", passage_id=pid, book_id=pid.split(".")[0], relation=ClaimRelation(case["relation"]),
                 arguments=args, quote=text[lo:hi], start=lo, end=hi, temporal=TemporalContext(),
                 extraction=ExtractionInfo(method="manual", agent="eval"))


def _support_case(h: Any, case: dict[str, Any]) -> tuple[Any, bool, bool]:
    pid, text = _text(h, case)
    got = assess_support(_claim(h, case, text, pid), text, h.pack.variants.normalize_text).verdict
    want = case["expect"]["verdict"]
    return got, got == want, got == "supports" and want != "supports"


def _stance_case(h: Any, case: dict[str, Any]) -> tuple[Any, bool, bool]:
    _, text = _text(h, case)
    normalize = h.pack.variants.normalize_text
    lo, hi = _span(text, case["quote"], normalize)
    got = statement_frame(text, lo, hi, normalize)["stance"]
    want = case["expect"]["stance"]
    return got, got == want, want in ("rejected", "reported") and got == "asserted"


def _condition_case(h: Any, case: dict[str, Any]) -> tuple[Any, bool, bool]:
    _, text = _text(h, case)
    normalize = h.pack.variants.normalize_text
    lo, hi = _span(text, case["quote"], normalize)
    frame = statement_frame(text, lo, hi, normalize)
    if case["expect"]["condition"] is None:  # a definition, not a condition: a spurious condition is wrong, not unsafe
        return frame["conditions"], not frame["conditions"], False
    want = normalize(case["expect"]["condition"])
    ok = any(want in c or c in want for c in frame["conditions"] if c)
    return frame["conditions"], ok, not ok  # a condition silently dropped is always the unsafe reading


def _witness_case(h: Any, case: dict[str, Any]) -> tuple[Any, bool, bool]:
    hits = {pid for pid, _, _ in find_quote(h.corpus, case["quote"], h.pack.variants.normalize_text)}
    if "cited" in case:
        found = case["cited"] in hits
    else:
        found = any(h.corpus.passage(pid).book_id == case["cited_book"] for pid in hits)
    want = case["expect"]["found"]
    return {"found": found, "located_at": sorted(hits)[:4]}, found == want, found and not want


def _date_case(h: Any, case: dict[str, Any]) -> tuple[Any, bool, bool]:
    corpus, want = h.corpus, case["expect"]
    if "order" in case:
        a, b = (corpus.year_range(corpus.passage(pid)) for pid in case["order"])
        got = a.order(b)
        return got, got == want["order"], want["order"] == "undetermined" and got != "undetermined"
    if "basis" in case:
        rng = corpus.year_range(corpus.passage(case["basis"]))
        got = [rng.start, rng.end]
        if "range" in want:
            return got, got == want["range"], got != want["range"]
        lo, hi = want["within"]
        ok = lo <= rng.start and rng.end <= hi
        return got, ok, not ok
    pid, cutoff = case["cutoff"]
    got = corpus.year_range(corpus.passage(pid)).side_of(cutoff)
    return got, got == want["side"], want["side"] != "before" and got == "before"  # a possibly later text put in the past


READERS = {"relation_inversion": _support_case, "negation_scope": _support_case, "consequence": _support_case,
           "reported_view": _stance_case, "omitted_condition": _condition_case, "witness_mixing": _witness_case,
           "date_dispute": _date_case}


def interpretive(ctx: EvalContext) -> SuiteResult:
    h = ctx.default
    cases = ctx.gold("interpretive").get("cases", [])
    details = []
    by_class: dict[str, list[dict]] = defaultdict(list)
    by_split: dict[str, list[dict]] = defaultdict(list)
    for case in cases:
        row = {"id": case["id"], "class": case["class"], "split": case.get("split", "heldout"), "expected": case["expect"]}
        try:
            got, correct, unsafe = READERS[case["class"]](h, case)
            row.update(got=got, correct=correct, unsafe=bool(unsafe and not correct))
        except CaseError as exc:
            row.update(got=f"gold error: {exc}", correct=False, unsafe=False, gold_error=True)
        if case.get("note"):
            row["note"] = case["note"]
        details.append(row)
        by_class[row["class"]].append(row)
        by_split[row["split"]].append(row)

    def score(rows: list[dict]) -> dict[str, Any]:
        return {"n": len(rows), "accuracy": round(sum(r["correct"] for r in rows) / len(rows), 4) if rows else None,
                "unsafe": sum(r["unsafe"] for r in rows)}

    metrics = {"cases": len(details), **{k: v for k, v in score(details).items() if k != "n"}, **{split: score(rows) for split, rows in sorted(by_split.items())},
               "accuracy_by_class": {k: score(v)["accuracy"] for k, v in sorted(by_class.items())},
               "unsafe_by_class": {k: score(v)["unsafe"] for k, v in sorted(by_class.items()) if score(v)["unsafe"]},
               "missed": [r["id"] for r in details if not r["correct"]], "gold_errors": [r["id"] for r in details if r.get("gold_error")]}
    notes = ["unsafe = a misreading that lets a false claim through: a contradicted claim read as supported, a rejected or "
             "reported view read as the author's, a mixed witness verified, a disputed order asserted, a text that may "
             "be later put before a cutoff, a condition dropped.",
             "Only the held-out score estimates anything; the dev cases were used to make the rules they test."]
    return SuiteResult("interpretive", metrics, details, notes)
