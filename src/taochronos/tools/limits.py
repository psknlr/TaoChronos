"""How large the arguments of the mesh's tools may be.

A tool's cost follows its arguments, and the full-corpus server runs a tool for whoever asks: ``permutations`` is a
loop (10**18 of them never ended, and their thread went on after the caller hung up), ``k`` is how deep a search reads
(200 hits cost the full corpus 15 s where 50 cost 0.2 s), ``max_chars`` is how much of a book is aligned.  So each
numeric parameter has a range — a few times what the tool does by default where the number is work, generous where it
only cuts what was worked out — and every text and list the default limit of its type (``kernel.tools``).  A call
outside them is refused before the tool runs, with the limit it passed, so that a model can ask again within it; the
limits are checked beside the schema and are no part of it (``ToolSpec.limits``): a model is shown the schema as before.
"""

from __future__ import annotations

from typing import Any


def count(least: int, most: int) -> dict[str, Any]:
    return {"minimum": least, "maximum": most}


YEAR = count(-5000, 5000)
SHARE = {"minimum": 0, "maximum": 1}
THRESHOLD = count(0, 1_000_000_000)  # compared with, never counted to

# by the parameter's name, as the tools use it
BY_NAME: dict[str, dict[str, Any]] = {
    # cuts of what was worked out: the entries of each list a result keeps, the characters of each text
    "items": count(0, 1000),
    "chars": count(1, 100_000),
    "top": count(1, 100),
    # how much is worked out
    "limit": count(0, 1000),
    "k": count(1, 100),
    "max_candidates": count(1, 2000),
    "max_chars": count(0, 120_000),  # of the base witness of a collation (0: the default)
    "permutations": count(0, 999),  # twice the default: 9,999 of them were 15 s of one call on a working set of 20,000 passages
    "per_period": count(1, 1000),
    "sample_per_period": count(1, 1000),
    "clauses": count(1, 60),
    "max_points": count(1, 50),
    "similar": count(0, 100),
    "max_extra": count(0, 50),
    "max_rounds": count(0, 100),  # (a research run keeps it within its own range)
    "start": THRESHOLD,  # the first row to read
    "seed": count(-(2 ** 63), 2 ** 63 - 1),
    # thresholds
    "min_cases": THRESHOLD,
    "min_support": THRESHOLD,
    "min_weight": THRESHOLD,
    "min_chars": THRESHOLD,
    "min_confidence": SHARE,
    "min_coverage": SHARE,
    "min_share": SHARE,
    # years, ages
    "before": YEAR,
    "after": YEAR,
    "pivot_year": YEAR,
    "year": YEAR,
    "holdout_after": YEAR,
    "age_min": count(0, 150),
    "age_max": count(0, 150),
    # a page's tokens: one a character
    "tokens": {"maxItems": 5000},
    # the terms the schools are compared on: each is a reading of the corpus
    "probes": {"maxItems": 12, "items": {"maxLength": 200}},
}

# where a tool uses a name otherwise
BY_TOOL: dict[str, dict[str, dict[str, Any]]] = {
    "analysis.link_prediction": {"k": count(1, 5000)},  # the statistician ranks its hypotheses in the first 5000
    "kg.neighbors": {"k": count(1, 500)},
    "study.layers": {"k": count(1, 20)},  # the layers a work is cut into
    "study.reuse": {"limit": count(0, 400)},  # the candidates labelled (200 by default: 7 s on the full corpus)
    "study.concordance": {"limit": count(0, 500)},
}


def limits_for(name: str, schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The limits of the tool ``name`` for the parameters its schema names (the others have their type's default)."""
    props = schema.get("properties") if isinstance(schema, dict) else None
    own = BY_TOOL.get(name, {})
    return {p: dict(own.get(p) or BY_NAME[p]) for p in (props if isinstance(props, dict) else ()) if p in own or p in BY_NAME}
