"""The design and population of a modern study, read from its publication types, MeSH headings, title and abstract.

Publication types come first (NLM indexes them by hand: Randomized Controlled Trial, Meta-Analysis, Case Reports …);
the population second, because an RCT in rats is animal evidence; the words of the title and abstract last (network
pharmacology, molecular docking, cell lines).  Each record keeps the rule that typed it, so a reader can dispute it.
"""

from __future__ import annotations

import re

from ...protocol.modern import EvidenceType, Population

E = EvidenceType
ANIMAL = re.compile(r"\b(mice|mouse|murine|rats?|rodents?|zebrafish|rabbits?|hamsters?|dogs|pigs|animal models?|in vivo)\b", re.I)
CELLS = re.compile(r"\b(in vitro|cell lines?|cultured cells|HepG2|RAW\s?264\.7|3T3-L1|HEK293|INS-1|MIN6|C2C12|L6 myotubes|"
                   r"cells were (?:treated|incubated|exposed))\b", re.I)
SILICO = re.compile(r"(network pharmacology|molecular docking|in silico|bioinformatic|molecular dynamics simulation|"
                    r"systems pharmacology|target prediction)", re.I)
PATIENTS = re.compile(r"\b(patients?|participants|subjects|volunteers|adults|children|women|men|individuals)\b", re.I)


def type_record(pubtypes: list[str], title: str = "", abstract: str = "", mesh: list[str] | None = None
                ) -> tuple[EvidenceType, Population, str]:
    pts = {p.lower() for p in pubtypes}
    mesh_l = {m.lower() for m in (mesh or [])}
    text = f"{title} {abstract}"
    human_mesh = "humans" in mesh_l
    animal_mesh = "animals" in mesh_l and not human_mesh
    silico = bool(SILICO.search(text))
    animal = animal_mesh or (bool(ANIMAL.search(text)) and not PATIENTS.search(title))
    cells = bool(CELLS.search(text)) and not PATIENTS.search(title)
    if "meta-analysis" in pts or "systematic review" in pts or re.search(r"systematic review|meta-analys", title, re.I):
        if silico and not re.search(r"trials?|studies", title, re.I):
            return E.IN_SILICO, Population.IN_SILICO, "systematic label but computational content"
        pop = Population.ANIMAL if (animal and not human_mesh and re.search(r"animal|rat|mice|preclinical", title, re.I)) else Population.HUMAN
        return (E.SYSTEMATIC_REVIEW if pop == Population.HUMAN else E.ANIMAL), pop, "publication type: systematic review / meta-analysis"
    if "practice guideline" in pts or "guideline" in pts or "consensus development conference" in pts:
        return E.GUIDELINE, Population.HUMAN, "publication type: guideline"
    if silico:
        return E.IN_SILICO, Population.IN_SILICO, "network pharmacology / docking / in silico"
    if "randomized controlled trial" in pts or re.search(r"\brandomi[sz]ed\b.*\b(trial|controlled)\b", title, re.I):
        if animal and not human_mesh:
            return E.ANIMAL, Population.ANIMAL, "randomised, but in animals"
        return E.RCT, Population.HUMAN, "publication type: randomized controlled trial"
    if animal:
        return E.ANIMAL, Population.ANIMAL, "animal study (MeSH Animals without Humans, or animal words)"
    if cells:
        return E.IN_VITRO, Population.IN_VITRO, "cell or in vitro study"
    if "case reports" in pts:
        return E.CASE_REPORT, Population.HUMAN, "publication type: case report"
    if re.search(r"case series", text, re.I):
        return E.CASE_SERIES, Population.HUMAN, "case series"
    if re.search(r"case[- ]control", text, re.I):
        return E.CASE_CONTROL, Population.HUMAN, "case-control design"
    if re.search(r"cross[- ]sectional", text, re.I):
        return E.CROSS_SECTIONAL, Population.HUMAN, "cross-sectional design"
    if "observational study" in pts or re.search(r"\bcohort\b|retrospective|prospective", text, re.I):
        return E.COHORT, Population.HUMAN, "observational / cohort design"
    if "clinical trial" in pts or "controlled clinical trial" in pts:
        return E.COHORT, Population.HUMAN, "non-randomised clinical trial (ranked with cohorts)"
    if "review" in pts or re.search(r"\breview\b", title, re.I):
        return E.NARRATIVE_REVIEW, Population.UNKNOWN, "publication type: review (not systematic)"
    if "editorial" in pts or "comment" in pts or "letter" in pts:
        return E.EXPERT_OPINION, Population.UNKNOWN, "editorial / comment / letter"
    return E.UNKNOWN, (Population.HUMAN if human_mesh else Population.UNKNOWN), "no rule applies"


__all__ = ["type_record"]
