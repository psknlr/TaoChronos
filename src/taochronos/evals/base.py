"""Shared machinery for TaoChronos-Eval: gold loading, harness factories, metrics."""

from __future__ import annotations

import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..bootstrap import Harness
from ..config import find_home
from ..kernel.store import MemoryEventStore

DEFAULT_QUESTION = "消渴的概念如何随时代演变？宋代以前治疗消渴的哪些知识后来被遗忘？"


@dataclass
class SuiteResult:
    name: str
    metrics: dict[str, Any]
    details: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "metrics": self.metrics, "details": self.details, "notes": self.notes}


class EvalContext:
    def __init__(self, home: str | Path | None = None, data_dir: str | Path | None = None, quick: bool = False) -> None:
        self.home = Path(home) if home else find_home()
        self.data_dir = Path(data_dir) if data_dir else Path(tempfile.mkdtemp(prefix="taochronos-eval-"))
        self.quick = quick
        self._default: Harness | None = None
        self._pipeline: tuple[Harness, Any] | None = None
        self._corpus: Harness | None | bool = False

    # ------------------------------------------------------------- harnesses
    def harness(self, profile: str = "full-discovery", **kw: Any) -> Harness:
        """A fresh, in-memory harness (events never touch the user's data directory)."""
        kw.setdefault("store", MemoryEventStore())
        return Harness.from_profile(profile, home=self.home, data_dir=self.data_dir, **kw)

    @property
    def default(self) -> Harness:
        if self._default is None:
            self._default = self.harness()
        return self._default

    def corpus_harness(self) -> Harness | None:
        """A harness on the full corpus when its store exists (in the data directory given, or the default one) —
        the real-corpus parts of some suites; None otherwise, and those parts are skipped."""
        if self._corpus is False:
            from ..config import data_dir as default_data_dir

            self._corpus = None
            for data in (self.data_dir, default_data_dir(self.home)):
                if (Path(data) / "corpus" / "tcm.sqlite").exists():
                    self._corpus = Harness.from_profile("full-corpus", home=self.home, data_dir=data, store=MemoryEventStore())
                    break
        return self._corpus  # type: ignore[return-value]

    def gold(self, name: str) -> dict[str, Any]:
        path = self.home / "evals" / "gold" / f"{name}.yaml"
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def run(self, harness: Harness, question: str = DEFAULT_QUESTION, session_id: str = "eval", **fields: Any) -> Any:
        engine = harness.engine()
        fields.setdefault("focus_terms", ["消渴"])
        fields.setdefault("forbidden_assumptions", ["消渴=糖尿病"])
        session = engine.start(harness.make_goal(question, **fields), session_id=session_id)
        engine.run(session)
        return session

    def pipeline(self) -> tuple[Harness, Any]:
        """The reference research run shared by several suites."""
        if self._pipeline is None:
            h = self.harness()
            self._pipeline = (h, self.run(h, session_id="eval-ref"))
        return self._pipeline


# ---------------------------------------------------------------- metrics
def prf(tp: int, fp: int, fn: int) -> dict[str, float | None]:
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
    return {"precision": _r(p), "recall": _r(r), "f1": _r(f), "tp": tp, "fp": fp, "fn": fn}


def accuracy(pairs: list[tuple[Any, Any]]) -> float | None:
    return _r(sum(1 for g, p in pairs if g == p) / len(pairs)) if pairs else None


def macro_f1(pairs: list[tuple[str, str]]) -> float | None:
    labels = sorted({g for g, _ in pairs} | {p for _, p in pairs})
    scores = []
    for label in labels:
        tp = sum(1 for g, p in pairs if g == label and p == label)
        fp = sum(1 for g, p in pairs if g != label and p == label)
        fn = sum(1 for g, p in pairs if g == label and p != label)
        f = prf(tp, fp, fn)["f1"]
        scores.append(f or 0.0)
    return _r(sum(scores) / len(scores)) if scores else None


def confusion(pairs: list[tuple[str, str]]) -> dict[str, dict[str, int]]:
    out: dict[str, Counter] = {}
    for g, p in pairs:
        out.setdefault(g, Counter())[p] += 1
    return {g: dict(c) for g, c in sorted(out.items())}


def _r(x: float | None) -> float | None:
    return None if x is None else round(x, 4)
