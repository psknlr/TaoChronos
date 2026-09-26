"""Five-layer memory.

M0 scratch (per agent run) · M1 episodic (the event log) · M2 research (the
ResearchObject) · M3 domain (expert-confirmed knowledge) · M4 skill (reusable
research methods).  A conversation is not knowledge: only committed M3 items
are treated as established, and only humans or validators can commit them.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from ..protocol.base import Model, stable_id
from .policy import Actor, PolicyViolation


class MemoryLayer(str, Enum):
    M0_SCRATCH = "M0"
    M1_EPISODIC = "M1"
    M2_RESEARCH = "M2"
    M3_DOMAIN = "M3"
    M4_SKILL = "M4"


PERSISTENT_LAYERS = (MemoryLayer.M3_DOMAIN, MemoryLayer.M4_SKILL)


@dataclass(kw_only=True)
class MemoryItem(Model):
    id: str
    layer: MemoryLayer
    summary: str
    content: dict = field(default_factory=dict)
    terms: list[str] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)
    status: str = "proposed"  # proposed | active | rejected
    decided_by: str | None = None


_TOKEN = re.compile(r"[㐀-鿿]|[A-Za-z0-9_]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(text))


class MemoryStore:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root else None
        self._items: dict[str, MemoryItem] = {}
        self._scratch: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        if self.root:
            self.root.mkdir(parents=True, exist_ok=True)
            for layer in PERSISTENT_LAYERS:
                path = self.root / f"{layer.value}.jsonl"
                if path.exists():
                    for line in path.read_text(encoding="utf-8").splitlines():
                        if line.strip():
                            item = MemoryItem.from_dict(json.loads(line))
                            self._items[item.id] = item

    # -------------------------------------------------------------- scratch
    def scratch(self, agent_id: str) -> dict[str, Any]:
        with self._lock:
            return self._scratch.setdefault(agent_id, {})

    def clear_scratch(self, agent_id: str) -> None:
        with self._lock:
            self._scratch.pop(agent_id, None)

    # ------------------------------------------------------------ persistent
    def propose(self, layer: MemoryLayer, summary: str, content: dict, *, actor: Actor, terms: list[str] | None = None,
                provenance: dict | None = None) -> MemoryItem:
        if layer not in PERSISTENT_LAYERS:
            raise ValueError("only M3 and M4 are persistent proposal layers")
        item = MemoryItem(
            id=stable_id("mem", layer.value, summary, content),
            layer=layer,
            summary=summary,
            content=content,
            terms=terms or [],
            provenance={"proposed_by": actor.id, **(provenance or {})},
        )
        with self._lock:
            self._items.setdefault(item.id, item)
            self._persist(layer)
        return self._items[item.id]

    def commit(self, item_id: str, *, actor: Actor, approve: bool = True) -> MemoryItem:
        if actor.principal not in ("human", "validator", "kernel"):
            raise PolicyViolation(f"{actor.id} cannot commit memory; only humans or validators can")
        with self._lock:
            item = self._items[item_id]
            item.status = "active" if approve else "rejected"
            item.decided_by = actor.id
            self._persist(item.layer)
            return item

    def recall(self, layer: MemoryLayer, query: str | list[str], k: int = 5, include_proposed: bool = False) -> list[MemoryItem]:
        q = _tokens(query) if isinstance(query, str) else set().union(*(_tokens(t) for t in query)) if query else set()
        with self._lock:
            candidates = [
                i for i in self._items.values()
                if i.layer == layer and (i.status == "active" or (include_proposed and i.status == "proposed"))
            ]
        scored = []
        for item in candidates:
            vocab = _tokens(item.summary) | set().union(*(_tokens(t) for t in item.terms)) if item.terms else _tokens(item.summary)
            overlap = len(q & vocab)
            if overlap or not q:
                scored.append((overlap, item.id, item))
        scored.sort(key=lambda t: (-t[0], t[1]))
        return [item for _, _, item in scored[:k]]

    def items(self, layer: MemoryLayer | None = None) -> list[MemoryItem]:
        with self._lock:
            return sorted((i for i in self._items.values() if layer is None or i.layer == layer), key=lambda i: i.id)

    def _persist(self, layer: MemoryLayer) -> None:
        if not self.root:
            return
        path = self.root / f"{layer.value}.jsonl"
        lines = [json.dumps(i.to_dict(), ensure_ascii=False, sort_keys=True) for i in self._items.values() if i.layer == layer]
        path.write_text("\n".join(sorted(lines)) + ("\n" if lines else ""), encoding="utf-8")
