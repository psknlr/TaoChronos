"""JSON Schemas of the results the task specification (docs/tasks.md) names as each task's output.

A schema lists the fields a consumer can rely on (``required``) and their types; a result may carry more (fields for
display, diagnostics).  ``tests/test_tasks.py`` validates the results of the functions on the fixture corpora
against them with ``protocol.schema.validate``, so the specification and the code cannot drift apart;
``taochronos schema --study`` prints them.
"""

from __future__ import annotations

from typing import Any

S: dict[str, Any] = {"type": "string"}
N: dict[str, Any] = {"type": "number"}
I: dict[str, Any] = {"type": "integer"}
B: dict[str, Any] = {"type": "boolean"}
NS: dict[str, Any] = {"type": ["string", "null"]}
NN: dict[str, Any] = {"type": ["number", "null"]}
STRS: dict[str, Any] = {"type": "array", "items": S}


def obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        out["required"] = required
    return out


def arr(items: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": items}


YEARS: dict[str, Any] = {"anyOf": [arr(N), {"type": "null"}]}
# every quotation a result carries: verbatim text with its book, date, locator, layer, source and licence
WITNESS = obj({"passage_id": S, "book_id": S, "title": S, "work": NS, "authors": STRS, "dynasty": S, "years": YEARS,
               "period": NS, "category": S, "kind": S, "layer": S, "locator": S, "quote": S, "span": arr(I), "source": S,
               "license": S, "punctuation": NS},
              ["passage_id", "book_id", "title", "years", "locator", "quote", "source", "license"])
SHARE_ROW = obj({"item": S, "units": N, "share": N, "other_units": N, "other_share": N, "share_z": N, "z": N, "p": N,
                 "significant": B, "occurrences": arr(N)}, ["item", "share", "other_share", "z", "significant"])

STUDY_SCHEMAS: dict[str, dict[str, Any]] = {
    # T3 异体字 / 通假 — the normalised text, the original never altered
    "normalize": obj({"normalized": S, "normalizations": arr(obj({"from": S, "to": S, "kind": S}))}, ["normalized", "normalizations"]),
    # T4–T5 断句 · 标点
    "punctuate": obj({
        "input": S, "unpunctuated": S, "punctuated": S, "preserved": B, "inserted": I,
        "marks": arr(obj({"at": I, "mark": S, "p": NN}, ["at", "mark"])),
        "review": arr(obj({"after": I, "context": S})),
        "model": obj({"version": S, "passages": I, "characters": I, "threshold": N, "rules": B}, ["version", "rules"]),
        "measured": {"type": ["object", "null"]}, "method": S},
        ["unpunctuated", "punctuated", "preserved", "inserted", "marks", "model"]),
    # T6 条文结构
    "clause": obj({
        "text": S, "punctuated_by_model": B,
        "pieces": arr(obj({"text": S, "role": S, "label": S, "rule": S,
                           "terms": arr(obj({"term": S, "category": S}, ["term", "category"]))}, ["text", "role", "label", "terms"])),
        "form": S, "roles": {"type": "object"}, "out_of_order": STRS, "findings": STRS, "pulse": STRS, "diseases": STRS,
        "formulas": STRS, "drugs": arr(obj({"text": S, "herbs": STRS}))},
        ["pieces", "form", "roles", "findings", "formulas", "drugs"]),
    # T7–T8 实体与关系 (claims: typed relations between lexicon entities, with the quote they are read from)
    "claims": arr(obj({
        "id": S, "passage_id": S, "book_id": S, "relation": S,
        "arguments": arr(obj({"role": S, "term_id": NS, "surface": S}, ["role"])),
        "quote": S, "start": I, "end": I, "polarity": S, "modality": S,
        "extraction": obj({"method": S, "rule": NS, "confidence": N}), "confidence": {"type": "object"}},
        ["id", "passage_id", "relation", "arguments", "quote", "start", "end"])),
    # T9 名称 (entity linking over time)
    "names": obj({
        "term": S, "term_id": NS,
        "names": arr(obj({"name": S, "kind": S, "note": S, "passages": I, "works": I, "first": arr(WITNESS)},
                         ["name", "kind", "passages", "works", "first"])),
        "periods": arr(obj({"period": S, "works": I, "shares": {"type": "object"}, "preferred": NS}, ["period", "works", "shares"])),
        "bins": arr(obj({"from": I, "to": I, "works": I, "shares": {"type": "object"}, "preferred": S})),
        "switches": arr(obj({"from": S, "to": S, "between": arr(I), "last_bin": B}, ["from", "to", "between"])),
        "equations": arr(obj({"names": STRS, "year": NN, "witness": WITNESS}, ["names", "witness"])),
        "candidates": arr(obj({"name": S, "passages": I, "works": I, "first": WITNESS}, ["name", "passages", "works", "first"]))},
        ["term", "names", "periods", "switches", "equations", "candidates"]),
    # T7 实体识别
    "entities": obj({
        "text": S, "types": STRS,
        "entities": arr(obj({"id": S, "start": I, "end": I, "text": S, "type": S, "label": S, "ref": NS, "source": S, "rule": S,
                             "ambiguous": B, "alternatives": STRS, "negated": B, "extraction": {"enum": ["rule", "model"]},
                             "decided_by": S}, ["id", "start", "end", "text", "type", "source", "ambiguous", "extraction"])),
        "counts": {"type": "object"}, "ambiguous": I, "llm_review": {"type": "object"}},
        ["text", "entities", "counts"]),
    # T10 训诂
    "glosses": obj({
        "term": NS, "book": NS, "count": I,
        "glosses": arr(obj({"kind": S, "head": S, "gloss": S, "by": S, "title": S, "passage_id": S, "years": YEARS,
                            "period": NS, "type": S, "sentence": S}, ["kind", "head", "gloss", "by", "passage_id", "type"])),
        "readings": arr(obj({"type": S, "gloss": S, "count": I, "first": {"type": "object"}, "by": STRS}, ["type", "gloss", "count"])),
        "kinds": {"type": "object"}, "by_period": {"type": "object"}},
        ["count", "glosses", "readings"]),
    # T11 条文对齐 (concordance)
    "concordance": obj({
        "query": S, "normalized": S, "base_work": NS,
        "hits": arr({**WITNESS, "properties": {**WITNESS["properties"], "coverage": N, "relation": S, "aligned": S, "marker": S},
                     "required": WITNESS["required"] + ["coverage", "relation"]}),
        "apparatus": arr(obj({"base": S, "reading": S, "kind": S, "witnesses": STRS, "impact": S, "score": N},
                             ["base", "reading", "kind", "witnesses"])),
        "summary": obj({"witnesses": I, "books": I, "works": I, "by_relation": {"type": "object"}}, ["witnesses", "works"])},
        ["query", "hits", "apparatus", "summary"]),
    # T12–T13 异文 · 异文分级 (variants of a work)
    "variants": obj({
        "work": S, "base": S, "base_characters": I,
        "witnesses": arr({"type": "object"}),
        "units": arr(obj({"id": S, "start": I, "end": I, "lemma": S, "kind": S,
                          "readings": arr(obj({"text": S, "witnesses": STRS}, ["text", "witnesses"])),
                          "impact": obj({"impact": S, "label": S, "score": N, "reason": S}, ["impact", "score"])},
                         ["id", "lemma", "kind", "readings"])),
        "by_impact": {"type": "object"},
        "review_queue": arr(obj({"id": S, "impact": S, "label": S, "score": N, "reason": S, "lemma": S, "context": S,
                                 "readings": arr({"type": "object"})}, ["id", "impact", "score", "lemma"])),
        "summary": obj({"units": I, "substantive": I, "per_1000": N}, ["units"])},
        ["work", "base", "witnesses", "units", "review_queue", "summary"]),
    # T14 文本复用
    "reuse": obj({
        "query": S,
        "hits": arr({**WITNESS, "properties": {**WITNESS["properties"], "label": S, "label_zh": S, "mode": S, "direction": S,
                                              "rule": S, "features": {"type": "object"}},
                     "required": WITNESS["required"] + ["label", "direction"]}),
        "summary": obj({"reuses": I, "works": I, "by_label": {"type": "object"}}, ["reuses", "by_label"])},
        ["query", "hits", "summary"]),
    # T15 出处追踪 · 传播链
    "chain": obj({
        "query": S, "root": {"type": ["object", "null"]},
        "nodes": arr(obj({"passage_id": S, "book_id": S, "title": S, "years": YEARS, "relation": S, "innovations": I, "depth": I},
                         ["passage_id", "title", "years", "depth"])),
        "edges": arr(obj({"from": S, "to": S, "basis": S, "shared": arr(obj({"root": S, "reading": S})), "score": N,
                          "margin": NN, "uncertain": B, "dates_overlap": B}, ["from", "to", "basis", "shared", "uncertain"])),
        "summary": obj({"witnesses": I, "through_intermediaries": I, "uncertain": I, "depth": I})},
        ["query", "nodes", "edges"]),
    "transmission": obj({"work": S, "title": S, "clauses": arr({"type": "object"}), "edges": I, "works": arr({"type": "object"}),
                         "periods": arr({"type": "object"}), "channels": arr({"type": "object"})},
                        ["work", "clauses", "works", "periods", "channels"]),
    # T16–T17 注家对齐 · 注家观点比较
    "commentaries": obj({
        "clause": S, "base_work": NS, "concepts_in_clause": STRS,
        "commentaries": arr(obj({"id": S, "commentator": S, "person": NS, "book_id": S, "title": S, "voice": S, "years": YEARS,
                                 "period": NS, "text": S, "quote": S, "passage_ids": STRS, "concepts": {"type": "object"},
                                 "cites": arr({"type": "object"}), "added": STRS},
                                ["id", "commentator", "title", "years", "text", "passage_ids", "concepts"])),
        "relations": arr(obj({"from": S, "to": S, "from_commentator": S, "to_commentator": S, "type": S, "share": N},
                             ["from", "to", "type"])),
        "consensus": arr({"type": "object"}), "unique": arr({"type": "object"}), "first_readings": arr({"type": "object"}),
        "quotations": arr({"type": "object"}), "count": I},
        ["clause", "commentaries", "relations", "count"]),
    # T18 版本谱系
    "stemma": obj({"work": S, "witnesses": arr({"type": "object"}), "units": arr({"type": "object"}), "tree": arr({"type": "object"}),
                   "root": NS, "newick": S, "groups": arr({"type": "object"}), "contamination": arr({"type": "object"})},
                  ["work", "witnesses", "tree", "newick", "groups", "contamination"]),
    # T19 provenance — a passage's chain of custody, and a quote located in the corpus
    "provenance": arr(obj({"level": S, "id": NS, "label": NS, "available": B}, ["level", "id", "available"])),
    "verify_quote": arr(obj({"passage_id": S, "start": I, "end": I}, ["passage_id", "start", "end"])),
    # T20 方证网络
    "network": obj({
        "target": NS, "kind": S, "indications": I,
        "findings": arr(obj({"finding": S, "category": S, "support": I, "share": N, "lift": N}, ["finding", "support", "lift"])),
        "drugs": arr(obj({"drug": S, "compositions": I, "share": N}, ["drug", "share"])), "by_period": {"type": "object"}},
        ["kind", "indications"]),
    # T21 配伍
    "pairs": obj({
        "herb": NS, "compositions": I, "min_support": I, "significant": I,
        "pairs": arr(obj({"a": S, "b": S, "support": I, "lift": N, "pmi": N, "npmi": N, "p": N, "significant": B},
                         ["a", "b", "support", "lift", "npmi", "p", "significant"])),
        "partners": arr(obj({"with": S, "support": I, "lift": N, "npmi": N, "significant": B}, ["with", "support", "lift", "significant"]))},
        ["compositions", "significant"]),
    # T22 方剂演化
    "formula": obj({
        "formula": obj({"term_id": NS, "name": S, "forms": arr({"type": "object"})}, ["name"]),
        "witnesses": arr({"type": "object"}),
        "groups": arr(obj({"core": STRS, "witnesses": I, "exact": I, "names": {"type": "object"}, "books": STRS,
                           "earliest": {"type": ["object", "null"]}, "span": YEARS, "relation": S}, ["core", "witnesses", "relation"])),
        "earliest": {"type": ["object", "null"]}, "modifications": arr({"type": "object"}), "ratios": arr({"type": "object"}),
        "other_names": arr({"type": "object"}), "metrology_notice": S,
        "summary": obj({"compositions": I, "works": I, "groups": I}, ["compositions", "groups"])},
        ["formula", "witnesses", "groups", "summary", "metrology_notice"]),
    # T23–T24 疾病 / 概念演化
    "term": obj({"term": {"type": "object"}, "periods": arr(obj({"period": S, "passages": I, "total": I, "per_10k": NN}, ["period", "passages", "total"])),
                 "trend": {"type": ["object", "null"]}, "earliest": arr({"type": "object"}), "collocates": arr({"type": "object"})},
                ["term", "periods", "earliest"]),
    "senses": obj({"term": S, "senses": arr({"type": "object"}), "series": arr({"type": "object"}), "change_points": arr({"type": "object"}),
                   "candidate_senses": arr({"type": "object"}), "neighbourhood": arr({"type": "object"})},
                  ["term", "senses", "series", "change_points", "candidate_senses"]),
    # T25 医家 / 流派
    "schools": obj({
        "school": S, "label": S,
        "members": arr(obj({"person": S, "name": S, "school": STRS, "dates": {"anyOf": [arr(N), {"type": "null"}]},
                            "works": arr(obj({"work": S, "title": S, "years": YEARS}, ["work", "title"]))}, ["person", "name", "works"])),
        "works": I,
        "comparison": obj({"works": I, "units": I, "other_units": N, "window": I, "forms": {"type": "object"}}, ["works", "units", "other_units"]),
        "vocabulary": arr({**SHARE_ROW, "properties": {**SHARE_ROW["properties"], "type": S, "per_10k": arr(N), "used_in": STRS,
                                                      "example": WITNESS}}),
        "formulas": arr({**SHARE_ROW, "properties": {**SHARE_ROW["properties"], "name": S}}),
        "probes": arr(obj({"item": S, "share": N, "other_share": N, "z": N, "share_z": N}, ["item", "z"])),
        "citations": obj({"cited": arr({"type": "object"}),
                          "homophily": obj({"own_share": NN, "other_share": NN, "ratio": NN}),
                          "cites_schools": {"type": "object"}, "cited_by_schools": {"type": "object"},
                          "rejects_schools": {"type": "object"}, "rejected_by": arr({"type": "object"}), "lineage": arr({"type": "object"})},
                         ["cited", "homophily"])},
        ["school", "label", "members", "works"]),
    # T26 争议
    "disputes": obj({
        "term": NS, "person": NS,
        "who_rejects_whom": arr({"type": "object"}), "most_disputed": arr({"type": "object"}), "passages_scanned": I},
        []),
    # P0 原文精确检索
    "search": obj({"query": {"type": "object"},
                   "hits": arr(obj({"passage_id": S, "book_id": S, "title": S, "year": NN, "locator": S, "text": S, "score": N},
                                   ["passage_id", "book_id", "locator", "text"]))}, ["hits"]),
}

__all__ = ["STUDY_SCHEMAS", "WITNESS"]
