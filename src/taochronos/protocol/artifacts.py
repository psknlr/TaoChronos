"""Artifacts are first-class, versioned research products with provenance."""

from __future__ import annotations

from dataclasses import dataclass

from .base import Model, field_list

ARTIFACT_KINDS = (
    "discovery_report",
    "knowledge_graph",
    "timeline",
    "concept_map",
    "formula_evolution_tree",
    "evidence_table",
    "hypothesis_report",
    "notebook",
    "dataset",
    "figure",
    "manuscript",
    "workspace",
)


@dataclass(kw_only=True)
class Artifact(Model):
    id: str
    kind: str
    title: str
    version: int
    path: str  # relative to the artifact store root
    media_type: str
    sha256: str
    generator: str
    parent_artifacts: list[str] = field_list()
    evidence_refs: list[str] = field_list()
    hypothesis_refs: list[str] = field_list()
    status: str = "published"  # published | draft
    note: str = ""
