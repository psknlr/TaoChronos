"""Storage plugins: event-store backends and knowledge-graph export formats.

The kernel defines the EventStore contract and ships reference backends; this
plugin exposes them (and graph exporters) as named providers so a profile can
choose ``storage: {event_store: sqlite}`` without the kernel naming a product.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...kernel.store import JsonlEventStore, MemoryEventStore, SqliteEventStore
from ..knowledge.export import json_graph, to_cypher, to_graphml, to_prov


def register(registry: Any, config: dict[str, Any], context: Any) -> None:
    data_dir = Path(getattr(context, "data_dir", ".taochronos"))
    registry.register("event_store", "memory", lambda: MemoryEventStore())
    registry.register("event_store", "jsonl", lambda: JsonlEventStore(data_dir / "events"))
    registry.register("event_store", "sqlite", lambda: SqliteEventStore(data_dir / "events.sqlite"), default=True)
    default = config.get("event_store")
    if default:
        registry.set_default("event_store", default)
    registry.register("graph_export", "json", json_graph, default=True)
    registry.register("graph_export", "cypher", to_cypher)
    registry.register("graph_export", "graphml", to_graphml)
    registry.register("graph_export", "prov", to_prov)
