"""Semantic text reuse: what a later passage does with an earlier one.

Reuse in the medical classics is rarely a clean copy.  A later author quotes (直接引用), transcribes with small
changes (近似转录), cuts (节略), condenses (撮要), restates in other words (转述), rewrites while explaining
(解释性改写), quotes in order to refute (引而驳之) — or merely shares the stock phrasing of the genre (套语相似:
以水七升，煮取三升，去滓 …), which is no reuse at all.

Finding such pairs and saying which kind they are are two different stages.  Candidates may come from anything with
high recall — rare character n-grams, co-occurring concepts, an embedding — and prove nothing.  The label is given by
transparent rules over features of the aligned pair: how much of the source's wording the target keeps
(``cov_source``) and how much of the target is the source's wording (``cov_target``), how much of the source's
content — its concepts, weighted by rarity — the target expresses, whether in the same order, how long the target is,
which discourse markers surround it, and how much of the shared wording is stock phrasing.  Every label carries the
rule that fired and the values it read.  A similarity from an encoder is reported with the features but no rule
reads it: an embedding may suggest a pair, it cannot establish one.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from ..protocol.base import Model

LABELS = {
    "verbatim_quote": "直接引用",
    "near_verbatim": "近似转录",
    "abridgement": "节略",
    "summary": "撮要",
    "paraphrase": "转述",
    "reinterpretation": "解释性改写",
    "oppositional_reuse": "引而驳之",
    "formulaic_similarity": "套语相似",
    "uncertain": "待定",
}
# how the target treats the source's wording: kept, transformed, disputed — for period profiles
MODES = {"verbatim_quote": "retained", "near_verbatim": "retained", "abridgement": "retained", "summary": "transformed",
         "paraphrase": "transformed", "reinterpretation": "transformed", "oppositional_reuse": "disputed",
         "formulaic_similarity": "none", "uncertain": "none"}

THRESHOLDS: dict[str, float] = {
    "related": 0.5,  # the pair is related by wording: this much of the source's words are there
    "content_related": 0.4,  # … or by content (if specific): this much of the source's content
    "verbatim_source": 0.95, "verbatim_target": 0.9,
    "near_source": 0.8, "near_len_low": 0.8, "near_len_high": 1.25,
    "abridge_target": 0.8, "abridge_len": 0.8, "abridge_source": 0.2, "abridge_block": 5.0,
    "close_source": 0.5, "close_len_low": 0.67, "close_len_high": 1.5,
    "summary_len": 0.5, "summary_concepts": 0.2, "summary_precision": 0.4,
    "wording_target": 0.8, "wording_chars": 8, "wording_block": 4,
    "reinterpret_concepts": 0.4, "reinterpret_len": 1.5,
    "paraphrase_concepts": 0.6, "paraphrase_order": 0.5, "paraphrase_len_low": 0.5, "paraphrase_len_high": 1.6,
    "formulaic_share": 0.6, "formulaic_concepts": 0.5, "formulaic_wording": 0.2,
    "specificity": 1.0, "distinctive": 0.5,
}


@dataclass(kw_only=True)
class ReuseFeatures(Model):
    """What the rules read about one (source, target) pair; the target is the aligned span of the later passage."""

    source_chars: int = 0
    target_chars: int = 0
    notes: int = 0  # characters of interlinear notes (夹注) inside the target span: commentary, left out of cov_target
    cov_source: float = 0.0  # share of the source's characters found, in order, in the target span (blocks of ≥ 2)
    cov_target: float = 0.0  # share of the target span's characters (notes aside) that are the source's
    longest_block: int = 0
    mean_block: float = 0.0  # mean length of the shared runs: excerpts are long runs, a condensation short fragments
    concept_cov: float = 0.0  # rarity-weighted share of the source's content (concepts, content bigrams) the target expresses
    concept_prec: float = 0.0  # … and of the target span's content that comes from the source
    specificity: float = 0.0  # Σ credit × idf of what the target expresses, minus log N: > 0 = the shared content would
    #                          co-occur in less than one passage by chance (an E-value below one, in nats)
    distinctive: float = 0.0  # best credit among the source's three most specific concepts: is its point there?
    attributed_to_source: bool = False  # the attribution names the source's book or author (仲景曰 for 伤寒论)
    concept_basis: str = "concepts+bigrams"  # or bigrams: the lexicon knows no concept of the source
    concepts_shared: list[str] = field(default_factory=list)
    concepts_partial: list[str] = field(default_factory=list)  # expressed in part (头项强痛 ~ 项背强痛)
    concepts_missing: list[str] = field(default_factory=list)
    concepts_added: list[str] = field(default_factory=list)  # the target's own concepts, absent from the source
    order: float = 1.0  # concordance of the shared concepts' order (1 = same order)
    length_ratio: float = 0.0  # target span / source
    formulaic_share: float = 0.0  # share of the shared wording that is stock phrasing
    similarity: float | None = None  # encoder cosine — reported, never read by a rule
    attribution: str = ""  # an explicit citation before the span (《千金》云, 仲景曰 …)
    opposition: list[str] = field(default_factory=list)  # refutation markers around the span (非也, 殊不知 …)
    interpretation: list[str] = field(default_factory=list)  # explanation markers in or after the span (谓, 盖, 此言 …)


def classify(f: ReuseFeatures, thresholds: dict[str, float] | None = None) -> dict[str, Any]:
    """The reuse type of a pair, with the rule that fired, the values it read and a confidence from the margins."""
    t = THRESHOLDS | (thresholds or {})
    wording = f.cov_source
    # related by wording (the source's words are there), or by content — only if what the target shares is specific
    # (genre concepts such as 太阳病, 脉浮, 恶寒 co-occur everywhere; an attribution to the source's author or book is
    # evidence too) and includes one of the source's most distinctive concepts
    specific = (f.specificity >= t["specificity"] or f.attributed_to_source) and f.distinctive >= t["distinctive"]
    by_content = specific and (f.concept_cov >= t["content_related"] or (
        f.length_ratio <= t["summary_len"] and f.concept_cov >= t["summary_concepts"] and f.concept_prec >= t["summary_precision"]))
    # a short target made of the source's own words is related however little of the source it keeps
    by_wording = wording >= t["related"] or (f.cov_target >= t["wording_target"] and f.longest_block >= t["wording_block"]
                                             and f.cov_target * f.target_chars >= t["wording_chars"])
    related = by_wording or by_content
    citation = "明引" if f.attribution else "暗引"

    def out(label: str, rule: str, margins: list[float], reasons: list[str]) -> dict[str, Any]:
        m = min(margins) if margins else 0.0
        confidence = "high" if m >= 0.1 else ("medium" if m >= 0.03 else "low")
        return {"label": label, "label_zh": LABELS[label], "mode": MODES[label], "rule": rule, "reasons": reasons,
                "confidence": confidence if label != "uncertain" else "low", "citation": citation if related else ""}

    content = (f"{f.concept_cov:.0%} of the content (specificity {f.specificity:+.1f}, "
               f"most distinctive concept {f.distinctive:.0%})")
    if f.formulaic_share >= t["formulaic_share"] and f.concept_cov < t["formulaic_concepts"] and wording >= t["formulaic_wording"]:
        return out("formulaic_similarity", "stock phrasing", [f.formulaic_share - t["formulaic_share"],
                                                               t["formulaic_concepts"] - f.concept_cov],
                   [f"{f.formulaic_share:.0%} of the shared wording is stock phrasing",
                    f"content in common {f.concept_cov:.2f} < {t['formulaic_concepts']}"])
    if not related:
        why = [f"wording {wording:.2f} < {t['related']}"]
        why.append(content if f.concept_cov >= t["related"] else f"content {f.concept_cov:.2f} < {t['related']}")
        return out("uncertain", "unrelated" if f.concept_cov < t["related"] else "shared content not specific", [], why)
    if f.opposition:
        return out("oppositional_reuse", "refutation markers", [max(wording, f.concept_cov) - t["related"]],
                   [f"refutation markers {'、'.join(dict.fromkeys(f.opposition))} beside a passage that keeps "
                    f"{wording:.0%} of the wording and {f.concept_cov:.0%} of the content"])
    if f.cov_source >= t["verbatim_source"] and f.cov_target >= t["verbatim_target"]:
        return out("verbatim_quote", "wording kept both ways", [f.cov_source - t["verbatim_source"], f.cov_target - t["verbatim_target"]],
                   [f"{f.cov_source:.0%} of the source in the target, {f.cov_target:.0%} of the target from the source"])
    if f.cov_source >= t["near_source"] and t["near_len_low"] <= f.length_ratio <= t["near_len_high"]:
        return out("near_verbatim", "most wording, similar length",
                   [f.cov_source - t["near_source"], f.length_ratio - t["near_len_low"], t["near_len_high"] - f.length_ratio],
                   [f"{f.cov_source:.0%} of the source's wording kept", f"length ratio {f.length_ratio:.2f}"])
    if f.cov_target >= t["abridge_target"] and f.length_ratio < t["abridge_len"] and f.cov_source >= t["abridge_source"] \
            and f.mean_block >= t["abridge_block"]:
        return out("abridgement", "the source's own words, fewer of them",
                   [f.cov_target - t["abridge_target"], t["abridge_len"] - f.length_ratio, f.cov_source - t["abridge_source"],
                    (f.mean_block - t["abridge_block"]) / 10],
                   [f"{f.cov_target:.0%} of the target is the source's wording, in runs of {f.mean_block:.1f} characters",
                    f"length ratio {f.length_ratio:.2f}"])
    if f.cov_source >= t["close_source"] and t["close_len_low"] <= f.length_ratio <= t["close_len_high"] \
            and f.order >= t["paraphrase_order"] and not f.interpretation:
        return out("paraphrase", "half the wording or more, reworded, similar length",
                   [f.cov_source - t["close_source"], f.length_ratio - t["close_len_low"], t["close_len_high"] - f.length_ratio],
                   [f"{f.cov_source:.0%} of the source's wording", f"length ratio {f.length_ratio:.2f}",
                    f"order concordance {f.order:.2f}"])
    if not by_content:
        return out("uncertain", "wording in part, content not specific", [],
                   [f"wording {f.cov_source:.2f}/{f.cov_target:.2f}, length ratio {f.length_ratio:.2f}", content])
    if f.length_ratio <= t["summary_len"] and f.concept_cov >= t["summary_concepts"] and f.concept_prec >= t["summary_precision"]:
        return out("summary", "much shorter, its content from the source",
                   [t["summary_len"] - f.length_ratio, f.concept_cov - t["summary_concepts"], f.concept_prec - t["summary_precision"]],
                   [f"length ratio {f.length_ratio:.2f}", content, f"{f.concept_prec:.0%} of the target's content from the source"])
    if f.concept_cov >= t["reinterpret_concepts"] and f.interpretation and (
            f.length_ratio >= t["reinterpret_len"] or len(set(f.interpretation)) >= 2):
        return out("reinterpretation", "content restated with explanation",
                   [f.concept_cov - t["reinterpret_concepts"], max(f.length_ratio - t["reinterpret_len"], 0.1 * (len(set(f.interpretation)) - 1))],
                   [content, f"explanation markers {'、'.join(dict.fromkeys(f.interpretation))}", f"length ratio {f.length_ratio:.2f}"])
    if f.concept_cov >= t["paraphrase_concepts"] and f.order >= t["paraphrase_order"] \
            and t["paraphrase_len_low"] <= f.length_ratio <= t["paraphrase_len_high"]:
        return out("paraphrase", "content in other words",
                   [f.concept_cov - t["paraphrase_concepts"], f.order - t["paraphrase_order"],
                    t["paraphrase_len_high"] - f.length_ratio, f.length_ratio - t["paraphrase_len_low"]],
                   [content, f"{f.cov_source:.0%} of the wording", f"order concordance {f.order:.2f}",
                    f"length ratio {f.length_ratio:.2f}"])
    return out("uncertain", "related, no type fits", [],
               [f"wording {f.cov_source:.2f}/{f.cov_target:.2f}, order {f.order:.2f}, length ratio {f.length_ratio:.2f}", content])


# ---------------------------------------------------------------- feature helpers
def order_concordance(pairs: list[tuple[int, int]]) -> float:
    """Share of concordant pairs among items placed in both texts ((position in source, position in target))."""
    if len(pairs) < 2:
        return 1.0
    good = total = 0
    for i in range(len(pairs)):
        for j in range(i + 1, len(pairs)):
            (a1, b1), (a2, b2) = pairs[i], pairs[j]
            if a1 == a2 or b1 == b2:
                continue
            total += 1
            good += (a1 - a2) * (b1 - b2) > 0
    return good / total if total else 1.0


def weighted_coverage(items: dict[str, float], credit: dict[str, float]) -> float:
    """Σ weight × credit / Σ weight over the source's items (credit 1 = expressed, a fraction = in part)."""
    total = sum(items.values())
    return sum(w * credit.get(k, 0.0) for k, w in items.items()) / total if total else 0.0


class SparseEncoder:
    """TF-IDF over tokens (concept ids, character bigrams), cosine of L2-normalised sparse vectors.  Deterministic
    and model-free: the default encoder of the candidate stage.  A neural encoder with the same two methods (a
    Classical Chinese sentence encoder) can take its place; neither proves a reuse."""

    name = "tfidf-concepts-bigrams"

    def __init__(self, idf: Callable[[str], float]) -> None:
        self.idf = idf

    def vector(self, tokens: Iterable[str]) -> dict[str, float]:
        tf = Counter(tokens)
        vec = {k: (1 + math.log(n)) * self.idf(k) for k, n in tf.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {k: v / norm for k, v in vec.items()}

    def similarity(self, a: Iterable[str], b: Iterable[str]) -> float:
        va, vb = self.vector(a), self.vector(b)
        if len(va) > len(vb):
            va, vb = vb, va
        return round(sum(v * vb.get(k, 0.0) for k, v in va.items()), 4)


# ---------------------------------------------------------------- the transmission network
def transmission_network(edges: list[dict[str, Any]]) -> dict[str, Any]:
    """Typed reuse edges of one source text's clauses → how later works took it up.

    ``edges``: ``{"clause", "target_work", "target_title", "year", "period", "label", "passage_id"}``.  Returns the
    works with their reuse types (how much of the source each carries, and how), the periods with the balance of
    retained / transformed / disputed reuse, and the first work to use each type."""
    by_work: dict[str, dict[str, Any]] = {}
    by_period: dict[str, Counter] = defaultdict(Counter)
    first: dict[str, dict[str, Any]] = {}
    for e in sorted(edges, key=lambda e: (e.get("year") if e.get("year") is not None else 9999, e.get("passage_id", ""))):
        w = by_work.setdefault(e["target_work"], {"work": e["target_work"], "title": e.get("target_title", ""),
                                                  "year": e.get("year"), "period": e.get("period"), "clauses": set(),
                                                  "labels": Counter(), "examples": []})
        w["clauses"].add(e["clause"])
        w["labels"][e["label"]] += 1
        if len(w["examples"]) < 3:
            w["examples"].append(e.get("passage_id"))
        by_period[e.get("period") or "未定"][MODES.get(e["label"], "none")] += 1
        if e["label"] not in first:
            first[e["label"]] = {"work": e["target_work"], "title": e.get("target_title", ""), "year": e.get("year"),
                                 "passage_id": e.get("passage_id")}
    works = []
    for w in by_work.values():
        labels = w.pop("labels")
        clauses = w.pop("clauses")
        dominant = labels.most_common(1)[0][0]
        works.append(w | {"clauses": len(clauses), "labels": dict(labels.most_common()), "dominant": dominant,
                          "dominant_zh": LABELS.get(dominant, dominant), "mode": MODES.get(dominant, "none")})
    works.sort(key=lambda w: (-w["clauses"], w["year"] if w["year"] is not None else 9999, w["work"]))
    periods = []
    for per, c in by_period.items():
        n = sum(v for k, v in c.items() if k != "none")
        periods.append({"period": per, "edges": sum(c.values()),
                        **{k: round(c[k] / n, 3) if n else 0.0 for k in ("retained", "transformed", "disputed")}})
    return {"works": works, "periods": periods, "first_of_each_type": first}


def intermediaries(clauses: list[dict[str, Any]], sim: Callable[[str, str], float], *, margin: float = 0.1,
                   min_clauses: int = 2) -> list[dict[str, Any]]:
    """Channels of transmission: a later work that follows an intermediate work's wording of a clause more closely
    than the source's (T2's text is closer to T1's than to S's) probably took the clause from T1.

    ``clauses``: ``{"source": text, "targets": [{"work", "title", "year", "text"}]}``.  Counted per (T1, T2) over
    the clauses; pairs seen in fewer than ``min_clauses`` clauses are left out."""
    count: Counter = Counter()
    gain: dict[tuple[str, str], list[float]] = defaultdict(list)
    titles: dict[str, str] = {}
    for c in clauses:
        targets = [t for t in c["targets"] if t.get("year") is not None]
        targets.sort(key=lambda t: t["year"])
        best_for: dict[str, tuple[str, float]] = {}  # a work that carries the clause in several places counts once
        for j, t2 in enumerate(targets):
            titles[t2["work"]] = t2.get("title", "")
            base = sim(c["source"], t2["text"])
            for t1 in targets[:j]:
                if t1["work"] == t2["work"] or t1["year"] >= t2["year"]:
                    continue
                s = sim(t1["text"], t2["text"])
                if s > base + margin and s - base > best_for.get(t2["work"], ("", 0.0))[1]:
                    best_for[t2["work"]] = (t1["work"], s - base)
        for work, (via, closer) in best_for.items():
            count[(via, work)] += 1
            gain[(via, work)].append(closer)
    return [{"via": a, "via_title": titles.get(a, ""), "work": b, "title": titles.get(b, ""), "clauses": n,
             "closer_by": round(sum(gain[(a, b)]) / n, 3)}
            for (a, b), n in count.most_common() if n >= min_clauses]


__all__ = ["LABELS", "MODES", "THRESHOLDS", "ReuseFeatures", "SparseEncoder", "classify", "intermediaries", "order_concordance",
           "transmission_network", "weighted_coverage"]
