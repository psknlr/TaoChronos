"""证据图谱 — the Evidence Graph: six layers from the witness to modern evidence, every edge with who asserts it.

Nodes live in a layer (source, historical, TCM semantic, mapping, modern, evidence) and have a type (passage, quote,
finding, term, sense, phenotype, hpo, disease, study, claim, audit …).  Every edge carries an assertion type — the text
says it, a scholar or curator interprets it, a model extracted or inferred it, modern evidence supports it, or it is a
hypothesis — and the ids of the evidence it rests on.  ``lineage`` walks from any node back to the source layer, so a
claim about a modern disease can always be followed to the words of a witness; ``unsupported`` lists the inferred edges
with no path to a source.

Builders read the plain results of the capabilities (a bridge mapping, modern evidence records, an audit); they never
import the plugins that make them.  Export: JSON (nodes, edges) and GraphML.
"""

from __future__ import annotations

import hashlib
import html
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..protocol.assertions import AssertionType, GraphLayer

A = AssertionType
L = GraphLayer


@dataclass
class Node:
    id: str
    layer: GraphLayer
    type: str
    label: str
    props: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "layer": self.layer.value, "type": self.type, "label": self.label, **({"props": self.props} if self.props else {})}


@dataclass
class Edge:
    source: str
    target: str
    type: str
    assertion: AssertionType
    evidence: list[str] = field(default_factory=list)
    props: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "target": self.target, "type": self.type, "assertion": self.assertion.value,
                **({"evidence": self.evidence} if self.evidence else {}), **({"props": self.props} if self.props else {})}


class EvidenceGraph:
    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []
        self._out: dict[str, list[Edge]] = defaultdict(list)
        self._in: dict[str, list[Edge]] = defaultdict(list)

    # ------------------------------------------------------------ building
    def node(self, id_: str, layer: GraphLayer, type_: str, label: str, **props: Any) -> str:
        if id_ not in self.nodes:
            self.nodes[id_] = Node(id_, layer, type_, label, {k: v for k, v in props.items() if v not in (None, "", [], {})})
        return id_

    def edge(self, source: str, target: str, type_: str, assertion: AssertionType, evidence: Iterable[str] = (), **props: Any) -> Edge:
        for e in self._out[source]:
            if e.target == target and e.type == type_:
                return e
        e = Edge(source, target, type_, assertion, list(evidence), {k: v for k, v in props.items() if v not in (None, "", [], {})})
        self.edges.append(e)
        self._out[source].append(e)
        self._in[target].append(e)
        return e

    def merge(self, other: "EvidenceGraph") -> "EvidenceGraph":
        for n in other.nodes.values():
            self.nodes.setdefault(n.id, n)
        for e in other.edges:
            self.edge(e.source, e.target, e.type, e.assertion, e.evidence, **e.props)
        return self

    # ------------------------------------------------------------ reading
    def lineage(self, node_id: str, *, max_depth: int = 8) -> list[list[dict[str, Any]]]:
        """The paths from ``node_id`` back (against the edges) to nodes of the source layer."""
        paths: list[list[dict[str, Any]]] = []

        def walk(nid: str, path: list[Edge], seen: set[str]) -> None:
            if len(path) > max_depth:
                return
            node = self.nodes.get(nid)
            if node is not None and node.layer == L.SOURCE and path:
                paths.append([e.to_dict() for e in reversed(path)])
                return
            for e in self._in.get(nid, []):
                if e.source not in seen:
                    walk(e.source, [*path, e], seen | {e.source})

        walk(node_id, [], {node_id})
        return paths

    def grounded(self, node_id: str) -> bool:
        return bool(self.lineage(node_id))

    def unsupported(self) -> list[dict[str, Any]]:
        """Inferred or hypothesised edges whose source node has no path back to a witness."""
        out = []
        for e in self.edges:
            if e.assertion in (A.MODEL_INFERRED, A.HYPOTHESIS):
                src = self.nodes.get(e.source)
                if src is not None and src.layer != L.SOURCE and not self.grounded(e.source):
                    out.append(e.to_dict())
        return out

    def stats(self) -> dict[str, Any]:
        return {"nodes": len(self.nodes), "edges": len(self.edges),
                "layers": dict(Counter(n.layer.value for n in self.nodes.values())),
                "node_types": dict(Counter(n.type for n in self.nodes.values())),
                "assertions": dict(Counter(e.assertion.value for e in self.edges))}

    def to_dict(self) -> dict[str, Any]:
        return {"nodes": [n.to_dict() for n in self.nodes.values()], "edges": [e.to_dict() for e in self.edges],
                "stats": self.stats()}

    def to_graphml(self) -> str:
        esc = html.escape
        lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                 '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
                 '  <key id="layer" for="node" attr.name="layer" attr.type="string"/>',
                 '  <key id="type" for="node" attr.name="type" attr.type="string"/>',
                 '  <key id="label" for="node" attr.name="label" attr.type="string"/>',
                 '  <key id="etype" for="edge" attr.name="type" attr.type="string"/>',
                 '  <key id="assertion" for="edge" attr.name="assertion" attr.type="string"/>',
                 '  <key id="evidence" for="edge" attr.name="evidence" attr.type="string"/>',
                 '  <graph id="evidence" edgedefault="directed">']
        for n in self.nodes.values():
            lines.append(f'    <node id="{esc(n.id)}"><data key="layer">{n.layer.value}</data><data key="type">{esc(n.type)}</data>'
                         f'<data key="label">{esc(n.label)}</data></node>')
        for k, e in enumerate(self.edges):
            lines.append(f'    <edge id="e{k}" source="{esc(e.source)}" target="{esc(e.target)}"><data key="etype">{esc(e.type)}</data>'
                         f'<data key="assertion">{e.assertion.value}</data><data key="evidence">{esc(",".join(e.evidence))}</data></edge>')
        lines += ["  </graph>", "</graphml>"]
        return "\n".join(lines)


# ---------------------------------------------------------------- builders
def from_bridge(result: dict[str, Any], graph: EvidenceGraph | None = None) -> EvidenceGraph:
    """The graph of one bridge mapping: the passage and its quotes, the findings it states, the phenotypes they are
    instances of, their HPO projections, the profiles the description resembles, and the historical names with their
    selected senses and curated candidates."""
    g = graph or EvidenceGraph()
    packet = result.get("packet", result)
    src = packet.get("source") or {}
    pid = src.get("passage_id") or "text:" + hashlib.sha1(packet["normalized"].encode("utf-8")).hexdigest()[:10]
    p = g.node(f"passage:{pid}", L.SOURCE, "passage", src.get("locator") or packet["normalized"][:24],
               book=src.get("book_id"), period=src.get("period"), text=packet["normalized"][:120])
    for f in packet.get("findings", []):
        if f.get("status") == "rejected":
            continue
        q = g.node(f"quote:{pid}:{f['span'][0]}-{f['span'][1]}", L.SOURCE, "quote", f["surface"], span=f["span"],
                   context=f.get("quote"))
        g.edge(p, q, "contains", A.SOURCE_ASSERTED)
        fid = g.node(f"finding:{pid}:{f['id']}", L.HISTORICAL, "finding", f["surface"] + ("（否定）" if f["negated"] else ""),
                     negated=f["negated"], optional=f.get("optional"), conditional=f.get("conditional"), status=f.get("status"))
        g.edge(q, fid, "states", A.MODEL_EXTRACTED, extraction=f.get("source"), decided_by=f.get("decided_by"))
        ph = g.node(f"phenotype:{f['phenotype']}", L.TCM_SEMANTIC, "phenotype", f["label"])
        g.edge(fid, ph, "instance_of", A.MODEL_EXTRACTED)
        if f.get("hpo"):
            h = g.node(f"hpo:{f['hpo']['id']}", L.MODERN, "hpo", f["hpo"]["label"], id=f["hpo"]["id"])
            m = g.node(f"map:{f['phenotype']}->{f['hpo']['id']}", L.MAPPING, "mapping", f"{f['label']} → {f['hpo']['label']}",
                       relation=f["hpo"]["relation"])
            g.edge(ph, m, "projects", A.SCHOLAR_INTERPRETED, relation=f["hpo"]["relation"])
            g.edge(m, h, "to", A.SCHOLAR_INTERPRETED, relation=f["hpo"]["relation"])
    for f in packet.get("implied", []):
        t = next((x for x in packet.get("terms", []) if x["id"] == f.get("implied_by")), None)
        if t is None or not t.get("sense"):
            continue
        ph = g.node(f"phenotype:{f['phenotype']}", L.TCM_SEMANTIC, "phenotype", f["label"])
        g.edge(f"sense:{t['sense']}", ph, "implies", A.SCHOLAR_INTERPRETED)
    for t in packet.get("terms", []):
        q = g.node(f"quote:{pid}:term:{t['term']}", L.SOURCE, "quote", t["term"])
        g.edge(p, q, "contains", A.SOURCE_ASSERTED)
        term = g.node(f"term:{t['term']}", L.HISTORICAL, "term", t["term"])
        g.edge(q, term, "names", A.MODEL_EXTRACTED)
        if t.get("sense"):
            s = g.node(f"sense:{t['sense']}", L.TCM_SEMANTIC, "sense", t.get("sense_label") or t["sense"])
            g.edge(term, s, "used_in_sense", A.MODEL_INFERRED, p=t.get("p"))
    for c in result.get("candidates", []):
        d = g.node(f"disease:{c['disease']}", L.MODERN, "disease", c["label"], icd10=c.get("icd10"), en=c.get("en"))
        m = g.node(f"resemblance:{pid}->{c['disease']}", L.MAPPING, "resemblance", f"{c['label']}（{c['level']}）",
                   level=c["level"], fit=c.get("fit"), relation=c.get("relation"), calibrated=False)
        g.edge(p, m, "described_by", A.MODEL_INFERRED)
        g.edge(m, d, "resembles", A.MODEL_INFERRED, level=c["level"])
        for mt in c.get("matched", []):
            h = g.node(f"hpo:{mt['feature']}", L.MODERN, "hpo", mt["feature_label"], id=mt["feature"])
            g.edge(d, h, "has_phenotype", A.SCHOLAR_INTERPRETED, tier=mt["tier"])
            fnode = f"finding:{pid}:{mt['via']}"
            if fnode in g.nodes:
                g.edge(fnode, m, "supports", A.MODEL_INFERRED, degree=mt.get("degree"))
    for t in result.get("terms", []):
        if not t.get("relations"):
            continue
        for r in t["relations"]:
            d = g.node(f"disease:{r['disease']}", L.MODERN, "disease", r["label"])
            m = g.node(f"termmap:{t['term']}->{r['disease']}", L.MAPPING, "term_mapping", f"{t['term']} ~ {r['label']}",
                       relation=r["relation"])
            g.edge(f"term:{t['term']}", m, "related", A.MODEL_INFERRED, relation=r["relation"])
            g.edge(m, d, "to", A.MODEL_INFERRED, relation=r["relation"])
    return g


def add_modern(g: EvidenceGraph, subject: str, subject_label: str, records: list[dict[str, Any]], *,
               layer: GraphLayer = L.MODERN, subject_type: str = "concept") -> EvidenceGraph:
    """Modern studies bearing on a subject (a disease, a drug, a formula), each typed by design and population."""
    s = g.node(subject, layer, subject_type, subject_label)
    for r in records:
        rid = g.node(f"study:{r.get('pmid') or r['id']}", L.EVIDENCE, "study", r.get("title", "")[:80],
                     evidence_type=r.get("evidence_type"), population=r.get("population"), year=r.get("year"),
                     pmid=r.get("pmid"), source=r.get("source"))
        g.edge(rid, s, "bears_on", A.MODERN_EVIDENCE_SUPPORTED, evidence=[r.get("pmid") or r["id"]],
               evidence_type=r.get("evidence_type"))
    return g


def add_audit(g: EvidenceGraph, audit: dict[str, Any]) -> EvidenceGraph:
    """An audit and its atomic claims, linked to what they cite."""
    a = g.node(f"audit:{audit.get('id', 'a')}", L.EVIDENCE, "audit", audit.get("verdict", ""), verdict=audit.get("verdict"))
    for c in audit.get("claims", []):
        cid = g.node(f"claim:{audit.get('id', 'a')}:{c['id']}", L.EVIDENCE, "claim", c["text"][:60], kind=c.get("kind"),
                     verdict=c.get("verdict"))
        g.edge(a, cid, "audits", A.MODEL_INFERRED, verdict=c.get("verdict"))
        for pid in c.get("passages", []):
            p = g.node(f"passage:{pid}", L.SOURCE, "passage", pid)
            g.edge(p, cid, "cited_by", A.SOURCE_ASSERTED if c.get("verdict") == "SUPPORTED" else A.HYPOTHESIS)
    return g


__all__ = ["Edge", "EvidenceGraph", "Node", "add_audit", "add_modern", "from_bridge"]
