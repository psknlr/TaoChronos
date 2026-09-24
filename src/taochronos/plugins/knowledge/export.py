"""Knowledge exports: JSON graph, Neo4j Cypher, GraphML and W3C PROV-O (JSON-LD)."""

from __future__ import annotations

import json
from typing import Any, Iterable
from xml.sax.saxutils import escape

from ...protocol.claims import Claim
from ...protocol.events import Event, EventType
from ...protocol.research import LineageEdge, ResearchObject


def _term_label(term_id: str) -> str:
    return term_id.split(":", 1)[1] if ":" in term_id else term_id


def json_graph(claims: Iterable[Claim], lineage: Iterable[LineageEdge] = (), books: dict[str, Any] | None = None) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    for c in claims:
        nodes[c.id] = {"id": c.id, "type": "Claim", "relation": c.relation.value, "quote": c.quote, "passage": c.passage_id}
        nodes.setdefault(c.passage_id, {"id": c.passage_id, "type": "Passage", "book": c.book_id})
        nodes.setdefault(c.book_id, {"id": c.book_id, "type": "Book", "title": (books or {}).get(c.book_id, c.book_id)})
        edges.append({"source": c.id, "target": c.passage_id, "type": "FROM"})
        edges.append({"source": c.passage_id, "target": c.book_id, "type": "IN"})
        for a in c.arguments:
            if a.term_id is None:
                continue
            nodes.setdefault(a.term_id, {"id": a.term_id, "type": "Term", "label": _term_label(a.term_id), "category": a.term_id.split(":", 1)[0]})
            edges.append({"source": c.id, "target": a.term_id, "type": "ARG", "role": a.role.value, "negated": a.negated,
                          "optional": bool(a.qualifiers.get("optional"))})
    for e in lineage:
        for node, kind in ((e.source_id, e.source_kind), (e.target_id, e.target_kind)):
            nodes.setdefault(node, {"id": node, "type": kind.capitalize()})
        edges.append({"source": e.source_id, "target": e.target_id, "type": "LINEAGE", "relation": e.relation,
                      "confidence": e.confidence, "direction_certain": e.direction_certain})
    return {"nodes": sorted(nodes.values(), key=lambda n: n["id"]), "edges": edges}


def _cy(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def to_cypher(claims: Iterable[Claim], lineage: Iterable[LineageEdge] = (), books: dict[str, Any] | None = None) -> str:
    """Neo4j import script. Claims are reified hyperedges: (:Claim)-[:ARG {role}]->(:Term)."""
    graph = json_graph(claims, lineage, books)
    lines = [
        "// TaoChronos claim hypergraph export (hyperedges reified as :Claim nodes)",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Node) REQUIRE n.id IS UNIQUE;",
    ]
    for n in graph["nodes"]:
        props = ", ".join(f"n.{k} = {_cy(v)}" for k, v in sorted(n.items()) if k not in ("id", "type"))
        lines.append(f"MERGE (n:Node:{n['type']} {{id: {_cy(n['id'])}}})" + (f" SET {props};" if props else ";"))
    for e in graph["edges"]:
        props = ", ".join(f"{k}: {_cy(v)}" for k, v in sorted(e.items()) if k not in ("source", "target", "type"))
        lines.append(
            f"MATCH (a:Node {{id: {_cy(e['source'])}}}), (b:Node {{id: {_cy(e['target'])}}}) "
            f"MERGE (a)-[:{e['type']}{' {' + props + '}' if props else ''}]->(b);"
        )
    return "\n".join(lines) + "\n"


def to_graphml(claims: Iterable[Claim], lineage: Iterable[LineageEdge] = (), books: dict[str, Any] | None = None) -> str:
    graph = json_graph(claims, lineage, books)
    keys = ["type", "label", "category", "relation", "quote", "role", "negated", "confidence"]
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">']
    for k in keys:
        out.append(f'  <key id="{k}" for="all" attr.name="{k}" attr.type="string"/>')
    out.append('  <graph id="taochronos" edgedefault="directed">')
    for n in graph["nodes"]:
        out.append(f'    <node id="{escape(n["id"])}">')
        for k in keys:
            if k in n:
                out.append(f'      <data key="{k}">{escape(str(n[k]))}</data>')
        out.append("    </node>")
    for i, e in enumerate(graph["edges"]):
        out.append(f'    <edge id="e{i}" source="{escape(e["source"])}" target="{escape(e["target"])}">')
        out.append(f'      <data key="type">{escape(e["type"])}</data>')
        for k in ("role", "relation", "negated", "confidence"):
            if k in e:
                out.append(f'      <data key="{k}">{escape(str(e[k]))}</data>')
        out.append("    </edge>")
    out.append("  </graph>")
    out.append("</graphml>")
    return "\n".join(out) + "\n"


def to_prov(events: Iterable[Event], state: ResearchObject) -> dict[str, Any]:
    """W3C PROV-O as JSON-LD: entities, activities (tasks/tool calls) and agents."""
    graph: list[dict[str, Any]] = []
    agents: set[str] = set()
    for ev in events:
        activity = f"taochronos:activity/{ev.task_id or ev.type}"
        if ev.type == EventType.TOOL_CALLED.value:
            node = {"@id": f"taochronos:call/{ev.payload.get('call_id')}", "@type": "prov:Activity",
                    "rdfs:label": ev.payload.get("tool"), "prov:wasAssociatedWith": {"@id": f"taochronos:agent/{ev.actor}"},
                    "prov:startedAtTime": ev.ts}
            graph.append(node)
            agents.add(ev.actor)
        for entity in ev.generated:
            graph.append({"@id": f"taochronos:entity/{entity}", "@type": "prov:Entity",
                          "prov:wasGeneratedBy": {"@id": activity}, "prov:generatedAtTime": ev.ts,
                          "prov:wasAttributedTo": {"@id": f"taochronos:agent/{ev.actor}"}})
            agents.add(ev.actor)
        for entity in ev.used:
            graph.append({"@id": activity, "@type": "prov:Activity", "prov:used": {"@id": f"taochronos:entity/{entity}"}})
    for claim in state.claims.values():
        graph.append({"@id": f"taochronos:entity/{claim.id}", "@type": ["prov:Entity", "taochronos:Claim"],
                      "prov:wasDerivedFrom": {"@id": f"taochronos:passage/{claim.passage_id}"},
                      "prov:value": claim.quote})
    for rec in state.evidence.values():
        graph.append({"@id": f"taochronos:entity/{rec.id}", "@type": ["prov:Entity", "taochronos:Evidence"],
                      "prov:wasDerivedFrom": {"@id": f"taochronos:passage/{rec.passage_id}"},
                      "prov:value": rec.quote})
    for h in state.hypotheses.values():
        graph.append({"@id": f"taochronos:entity/{h.id}", "@type": ["prov:Entity", "taochronos:Hypothesis"],
                      "prov:wasDerivedFrom": [{"@id": f"taochronos:entity/{e}"} for e in h.supporting_evidence]
                      + ([{"@id": f"taochronos:entity/{h.parent_id}"}] if h.parent_id else [])})
    for a in sorted(agents):
        graph.append({"@id": f"taochronos:agent/{a}", "@type": "prov:Agent",
                      "rdfs:label": a, "taochronos:principal": a.split(":", 1)[0]})
    return {
        "@context": {
            "prov": "http://www.w3.org/ns/prov#",
            "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
            "taochronos": "https://github.com/psknlr/TaoChronos/ns#",
        },
        "@graph": graph,
    }


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True)
