"""TaoChronos-Eval: does the harness do what it claims?

Suites: philology · claims · provenance · hallucination · contradiction · lineage · temporal ·
anachronism · recovery · time_machine · source_rediscovery · ablations · collation · reuse · stratigraphy · cases · argument.  Gold sets live in
``evals/gold`` (author-constructed for the demo corpus; see its README).
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable

from .ablations import ablations
from .base import EvalContext, SuiteResult
from .rediscovery import source_rediscovery, time_machine
from .suites import anachronism, claims, contradiction, hallucination, lineage, philology, provenance, recovery, temporal
from .textual import argument, cases, collation, reuse, stratigraphy

SUITES: dict[str, Callable[[EvalContext], SuiteResult]] = {
    "philology": philology,
    "claims": claims,
    "provenance": provenance,
    "hallucination": hallucination,
    "contradiction": contradiction,
    "lineage": lineage,
    "temporal": temporal,
    "anachronism": anachronism,
    "recovery": recovery,
    "time_machine": time_machine,
    "source_rediscovery": source_rediscovery,
    "ablations": ablations,
    "collation": collation,
    "reuse": reuse,
    "stratigraphy": stratigraphy,
    "cases": cases,
    "argument": argument,
}
QUICK = ("philology", "claims", "hallucination", "contradiction", "lineage", "temporal", "anachronism", "source_rediscovery",
         "collation", "reuse", "stratigraphy", "cases", "argument")


def run_suites(names: list[str] | None = None, *, home: Any = None, data_dir: Any = None, quick: bool = False) -> dict[str, Any]:
    ctx = EvalContext(home=home, data_dir=data_dir, quick=quick)
    selected = names or (list(QUICK) if quick else list(SUITES))
    unknown = sorted(set(selected) - set(SUITES))
    if unknown:
        raise KeyError(f"unknown suites {unknown} (known: {sorted(SUITES)})")
    results: dict[str, Any] = {}
    for name in selected:
        started = time.perf_counter()
        result = SUITES[name](ctx)
        data = result.to_dict()
        data["seconds"] = round(time.perf_counter() - started, 2)
        results[name] = data
    return results


def _headline(metrics: dict[str, Any]) -> str:
    parts = []
    for key, value in metrics.items():
        if isinstance(value, dict):
            inner = ", ".join(f"{k}={v}" for k, v in value.items() if not isinstance(v, (dict, list)))
            parts.append(f"{key}{{{inner}}}")
        elif not isinstance(value, list):
            parts.append(f"{key}={value}")
    return "; ".join(parts)


def summary_table(results: dict[str, Any]) -> str:
    lines = ["TaoChronos-Eval", "=" * 15]
    for name, data in results.items():
        lines.append(f"{name:20s} {data['seconds']:6.1f}s  {_headline(data['metrics'])}")
        for note in data.get("notes", []):
            lines.append(f"{'':28s}note: {note}")
    return "\n".join(lines)


__all__ = ["EvalContext", "QUICK", "SUITES", "SuiteResult", "run_suites", "summary_table"]
