"""Context Operating System.

A model call never sees "everything".  It sees a budgeted view assembled from
prioritised sections: the pinned Goal Anchor and current task first, then open
questions, the ResearchObject slice, evidence, skills and memory.  Sections
that do not fit are compacted (items elided with ids kept) or dropped, and the
view records what was left out.  The Goal Anchor is never compacted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_CJK = re.compile(r"[㐀-鿿豈-﫿]")


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~1 token per CJK character, ~4 characters per token otherwise."""
    if not text:
        return 0
    cjk = len(_CJK.findall(text))
    other = len(text) - cjk
    return cjk + (other + 3) // 4


@dataclass
class ContextSection:
    name: str
    content: str
    priority: int = 50  # lower = more important
    pinned: bool = False
    items: list[str] = field(default_factory=list)  # optional itemised form for compaction

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.render())

    def render(self) -> str:
        body = self.content if self.content else "\n".join(self.items)
        return f"## {self.name}\n{body}".rstrip()


@dataclass
class ContextView:
    sections: list[ContextSection]
    budget_tokens: int
    omitted: list[str] = field(default_factory=list)
    compacted: list[str] = field(default_factory=list)

    @property
    def tokens(self) -> int:
        return sum(s.tokens for s in self.sections)

    def render(self) -> str:
        parts = [s.render() for s in self.sections]
        if self.omitted or self.compacted:
            notes = []
            if self.compacted:
                notes.append("compacted: " + ", ".join(self.compacted))
            if self.omitted:
                notes.append("omitted for budget: " + ", ".join(self.omitted))
            parts.append("## Context notes\n" + "; ".join(notes))
        return "\n\n".join(parts)

    def get(self, name: str) -> ContextSection | None:
        for s in self.sections:
            if s.name == name:
                return s
        return None


class ContextManager:
    def __init__(self, max_tokens: int = 24000) -> None:
        self.max_tokens = max_tokens

    def build(self, sections: list[ContextSection], max_tokens: int | None = None) -> ContextView:
        budget = max_tokens or self.max_tokens
        pinned = [s for s in sections if s.pinned]
        others = sorted((s for s in sections if not s.pinned), key=lambda s: s.priority)
        used = sum(s.tokens for s in pinned)
        chosen = list(pinned)
        omitted: list[str] = []
        compacted: list[str] = []
        for section in others:
            if used + section.tokens <= budget:
                chosen.append(section)
                used += section.tokens
                continue
            smaller = self.compact(section, budget - used)
            if smaller is not None:
                chosen.append(smaller)
                used += smaller.tokens
                compacted.append(section.name)
            else:
                omitted.append(section.name)
        order = {id(s): i for i, s in enumerate(sections)}
        chosen.sort(key=lambda s: (not s.pinned, s.priority, order.get(id(s), 0)))
        return ContextView(chosen, budget, omitted, compacted)

    @staticmethod
    def compact(section: ContextSection, room: int) -> ContextSection | None:
        """Keep as many leading items as fit and summarise the rest."""
        if room <= 32 or not section.items:
            return None
        kept: list[str] = []
        header = estimate_tokens(f"## {section.name}\n")
        used = header
        for item in section.items:
            cost = estimate_tokens(item) + 1
            if used + cost > room - 24:
                break
            kept.append(item)
            used += cost
        if not kept:
            return None
        dropped = len(section.items) - len(kept)
        items = kept + ([f"… {dropped} more item(s) omitted; request them by id via tools."] if dropped else [])
        return ContextSection(section.name, "", section.priority, section.pinned, items)
