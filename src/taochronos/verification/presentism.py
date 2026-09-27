"""以今律古 — the presentism guardrail: a historical description is not a retrospective diagnosis.

``PresentismGuard.check(text)`` reads a text (a translation, a claim, a report) sentence by sentence and returns what it
finds wrong with it:

* ``equation`` — an ancient term equated with a modern disease (消渴即糖尿病, 胸痹就是冠心病);
* ``retrospective`` — an ancient text credited with a modern diagnosis (《金匮要略》已经描述了糖尿病);
* ``modern_term`` — with ``source`` given (a translation and the text it translates), a modern biomedical name the
  source does not contain: a translation of a classic that says 糖尿病 has put the modern name in the ancient mouth.

A sentence that bounds its comparison (相似, 部分, 并非一一对应, 不宜等同 …) passes: comparing is allowed, equating is
not.  Each finding carries the sentence, the words that triggered it, and a suggested rewrite.  The word lists are data
(``domains/classics/presentism.yaml``) and the modern-concept labels of the domain pack.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable
from ..protocol.yamlio import load_yaml

SENTENCE = re.compile(r"[^。；！？!?;\n]+[。；！？!?;]?")


@dataclass
class PresentismFinding:
    kind: str  # equation | retrospective | modern_term
    sentence: str
    ancient: str | None
    modern: str
    marker: str | None
    suggestion: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PresentismGuard:
    def __init__(self, data: dict[str, Any], modern_labels: Iterable[str] = ()) -> None:
        self.modern = sorted({*data.get("modern_terms", []), *(l.split("（")[0] for l in modern_labels if l)},
                             key=len, reverse=True)
        # a modern label that is also a classical term (霍乱, 黄疸, 失音) is not a modern name in a classical sentence
        self.classical_too = {"霍乱", "黄疸", "失音", "心脏", "肾脏", "痰液"}
        self.modern = [m for m in self.modern if m not in self.classical_too and len(m) >= 2]
        self.equated: dict[str, list[str]] = {k: list(v) for k, v in (data.get("equated") or {}).items()}
        self.equating = sorted(data.get("equating", []), key=len, reverse=True)
        self.retrospective = sorted(data.get("retrospective", []), key=len, reverse=True)
        self.hedges = list(data.get("hedges", []))
        self.template = data.get("hedge_template", "「{ancient}」与现代{modern}并非一一对应。")

    def modern_terms_in(self, text: str) -> list[str]:
        found, taken = [], [False] * len(text)
        for m in self.modern:
            start = text.find(m)
            while start >= 0:
                if not any(taken[start: start + len(m)]):
                    found.append(m)
                    for k in range(start, start + len(m)):
                        taken[k] = True
                start = text.find(m, start + 1)
        return found

    def hedged(self, sentence: str) -> bool:
        return any(h in sentence for h in self.hedges)

    def _ancients(self, sentence: str, extra: Iterable[str]) -> list[str]:
        names = set(self.equated) | set(extra)
        return sorted((a for a in names if a and a in sentence), key=lambda a: sentence.find(a))

    def check(self, text: str, *, source: str | None = None, ancient_terms: Iterable[str] = ()) -> list[PresentismFinding]:
        extra = list(ancient_terms)
        out: list[PresentismFinding] = []
        for m in SENTENCE.finditer(text or ""):
            sentence = m.group(0).strip()
            if not sentence:
                continue
            moderns = [x for x in self.modern_terms_in(sentence) if source is None or x not in source]
            if not moderns:
                continue
            hedged = self.hedged(sentence)
            ancients = self._ancients(sentence, extra)
            done = False
            for modern in moderns:
                for ancient in ancients:
                    i, j = sentence.find(ancient), sentence.find(modern)
                    if i < 0 or j < 0 or i == j:
                        continue
                    between = sentence[min(i, j): max(i, j)]
                    marker = next((e for e in self.equating if e in between), None)
                    if marker and not hedged:
                        out.append(PresentismFinding("equation", sentence, ancient, modern, marker,
                                                     self.template.format(ancient=ancient, modern=modern)))
                        done = True
                        break
                if done:
                    break
            if done:
                continue
            marker = next((r for r in self.retrospective if r in sentence), None)
            if marker and not hedged:
                ancient = ancients[0] if ancients else None
                out.append(PresentismFinding("retrospective", sentence, ancient, moderns[0], marker,
                                             self.template.format(ancient=ancient or "古籍所述", modern=moderns[0])))
                continue
            if source is not None and not hedged:
                out.append(PresentismFinding("modern_term", sentence, ancients[0] if ancients else None, moderns[0], None,
                                             f"译文不用现代病名「{moderns[0]}」：按原文的说法译出，现代对照另作说明。"))
        return out


def guard_from_pack(pack: Any) -> PresentismGuard:
    """The guardrail of a domain pack: its presentism.yaml and its modern-concept labels."""
    path = pack.root / "presentism.yaml"
    data = load_yaml(path) if path.exists() else {}
    labels = [c.label for c in getattr(getattr(pack, "terminology", None), "concepts", {}).values()]
    return PresentismGuard(data or {}, labels)


__all__ = ["PresentismFinding", "PresentismGuard", "guard_from_pack"]
