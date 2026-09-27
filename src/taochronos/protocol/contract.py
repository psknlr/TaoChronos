"""The executable research contract: what a research must deliver, and who decides whether it did.

The GoalSpec states the question; this states the **acceptance**.  Every criterion names who judges it (a validator or a
human), what it reads, the version of the objects it judged, and what the research becomes when it fails.  The outcome
separates *execution* (the tasks ran) from *acceptance* (the research meets its contract):

``execution_finished``  the tasks ran; nothing has been judged yet
``research_accepted``   at least one hypothesis meets every criterion, the expert's included
``needs_expert``        hypotheses meet every machine criterion; an expert has not yet decided (G7, or a criterion only a
                        person can judge)
``inconclusive``        the run finished and no hypothesis meets the contract — an answer, not a failure
``budget_exhausted``    stopped by the budget before the contract could be met

A formal *inconclusive* is allowed and honest; "no tasks left" is never "accepted".
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .base import Model, field_dict, field_list

ACCEPTANCE_STATUSES = ("execution_finished", "research_accepted", "needs_expert", "inconclusive", "budget_exhausted")
REQUIRED_OUTPUTS = ("candidate_hypotheses", "supporting_and_counter_evidence", "alternative_explanations", "reproducibility_bundle")


@dataclass(kw_only=True)
class AcceptanceSpec(Model):
    """Machine-checkable acceptance criteria (every one is evaluated by a validator on the current object versions)."""

    semantic_support_checked: bool = True  # every supporting quote bears the claim it is used for
    source_dependence_checked: bool = True  # independent source families counted (G5) and robust to dropping one family
    max_unresolved_hard_objections: int = 0
    max_unresolved_critical: int = 0
    alternatives_required: bool = True  # the discovery type's rival explanations are each addressed in the warrant
    current_version_gates: bool = True  # required gates ran on the hypothesis as it now stands
    confirmation_required: bool = False  # predictions re-tested on material withheld from exploration
    expert_review_required_for_publication: bool = True


@dataclass(kw_only=True)
class ConfirmationSpec(Model):
    """Material kept back from exploration to re-test what exploration found: whole source families (so exploration and
    confirmation are independent witnesses), a fraction of them in every period."""

    fraction: float = 0.25
    seed: int = 7
    unit: str = "family"  # family (author / transcription cluster) | book


@dataclass(kw_only=True)
class CriterionResult(Model):
    id: str
    status: str  # pass | fail | pending | not_applicable
    judge: str  # validator:contract | human
    observed: str = ""
    required: str = ""
    failure_state: str = "inconclusive"  # what the hypothesis is when this criterion fails


@dataclass(kw_only=True)
class HypothesisAcceptance(Model):
    hypothesis_id: str
    version: str
    status: str  # accepted | needs_expert | inconclusive | rejected
    criteria: list[CriterionResult] = field_list()


@dataclass(kw_only=True)
class ContractEvaluation(Model):
    status: str
    execution: str  # how the run ended: completed | max_rounds | budget_exhausted | awaiting_expert | stopped
    hypotheses: list[HypothesisAcceptance] = field_list()
    outputs: dict = field_dict()  # required output → present?
    human_criteria: list[str] = field_list()  # free-text criteria only a person can judge
    reasons: list[str] = field_list()
    evaluated_by: str = "validator:contract"
    at_seq: int = 0  # operational (left 0 in the log: a resumed run must hash like an uninterrupted one)
    versions: dict = field_dict()  # hypothesis id → the version it was judged on

    def accepted(self) -> list[str]:
        return [h.hypothesis_id for h in self.hypotheses if h.status == "accepted"]


def default_outputs() -> list[str]:
    return list(REQUIRED_OUTPUTS)


__all__ = ["ACCEPTANCE_STATUSES", "AcceptanceSpec", "ConfirmationSpec", "ContractEvaluation", "CriterionResult",
           "HypothesisAcceptance", "REQUIRED_OUTPUTS", "default_outputs", "field"]
