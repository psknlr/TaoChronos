"""Built-in lifecycle hooks: provenance validator, anachronism guard, publish guard."""

from __future__ import annotations

import re
from typing import Any

from ..kernel.hooks import HookContext, HookPoint, HookRegistry, HookResult
from ..protocol.artifacts import Artifact
from ..protocol.claims import Claim
from ..protocol.concepts import KnowledgeSpace, MappingRelation
from ..protocol.hypothesis import Hypothesis
from .provenance import verify_claim

EQUATING = re.compile(r"(即|就是|等同于|等于|=|即为|相当于)")


def provenance_validator(corpus: Any, normalize: Any):
    def hook(ctx: HookContext) -> HookResult:
        claim = ctx.subject
        if not isinstance(claim, Claim):
            return HookResult()
        problems = verify_claim(claim, corpus, normalize)
        if problems:
            return HookResult(allow=False, reason="provenance: " + "; ".join(problems[:3]))
        return HookResult()

    return hook


def anachronism_guard(modern_labels: list[str], forbidden: list[str] | None = None):
    """Blocks equations of historical terms with modern diseases and GoalSpec-forbidden assumptions."""
    labels = [label.split("（")[0] for label in modern_labels if label]

    def text_risk(text: str) -> str | None:
        compact = text.replace(" ", "")
        for rule in forbidden or []:
            norm_rule = rule.replace(" ", "")
            if norm_rule and norm_rule in compact:
                return f"violates forbidden assumption “{rule}”"
            parts = re.split(r"[=＝]|即|等于", norm_rule)
            if len(parts) == 2 and all(parts) and parts[0] in compact and parts[1] in compact:
                left, right = parts
                window = compact[compact.find(left): compact.find(left) + len(left) + 12]
                if right in window and EQUATING.search(window):
                    return f"violates forbidden assumption “{rule}”"
        for label in labels:
            idx = compact.find(label)
            if idx > 0 and EQUATING.search(compact[max(0, idx - 4): idx]):
                return f"equates a historical concept with the modern category “{label}”"
        return None

    def hook(ctx: HookContext) -> HookResult:
        subject = ctx.subject
        if isinstance(subject, Claim):
            if any((a.term_id or "").startswith("modern:") for a in subject.arguments) and subject.space == KnowledgeSpace.CLASSICAL:
                return HookResult(allow=False, reason="anachronism: classical claim carries a modern concept")
            return HookResult()
        if isinstance(subject, Hypothesis):
            risk = text_risk(subject.statement)
            if risk:
                return HookResult(allow=False, reason=f"anachronism: {risk}")
            return HookResult()
        if isinstance(subject, dict) and subject.get("relation") == MappingRelation.EQUIVALENT.value:
            if ctx.actor is not None and getattr(ctx.actor, "principal", "") != "human":
                return HookResult(allow=False, reason="anachronism: only a human expert may assert historical→modern equivalence")
        return HookResult()

    return hook


def publish_guard(require_evidence_for: tuple[str, ...] = ("discovery_report", "hypothesis_report", "evidence_table")):
    def hook(ctx: HookContext) -> HookResult:
        artifact = ctx.subject
        if isinstance(artifact, Artifact) and artifact.kind in require_evidence_for and artifact.status != "draft" and not artifact.evidence_refs:
            return HookResult(allow=False, reason=f"{artifact.kind} must cite evidence (Evidence-first); publish as draft instead")
        return HookResult()

    return hook


def install_default_hooks(hooks: HookRegistry, *, corpus: Any, pack: Any, forbidden: list[str] | None = None,
                          enabled: list[str] | None = None) -> list[str]:
    names = enabled or ["provenance_validator", "anachronism_guard", "publish_guard"]
    installed = []
    modern_labels = [c.label for c in pack.terminology.concepts.values()]
    if "provenance_validator" in names:
        hooks.register(HookPoint.BEFORE_CLAIM_COMMIT, "provenance_validator", provenance_validator(corpus, pack.variants.normalize_text), 10)
        installed.append("provenance_validator")
    if "anachronism_guard" in names:
        guard = anachronism_guard(modern_labels, forbidden)
        hooks.register(HookPoint.BEFORE_CLAIM_COMMIT, "anachronism_guard", guard, 20)
        hooks.register(HookPoint.AFTER_HYPOTHESIS, "anachronism_guard", guard, 20)
        hooks.register(HookPoint.BEFORE_GRAPH_WRITE, "anachronism_guard", guard, 20)
        installed.append("anachronism_guard")
    if "publish_guard" in names:
        hooks.register(HookPoint.BEFORE_ARTIFACT_PUBLISH, "publish_guard", publish_guard(), 10)
        installed.append("publish_guard")
    return installed
