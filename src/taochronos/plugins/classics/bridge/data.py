"""The bridge's data: the ancient phenotypes (their written forms and HPO projections), the modern disease profiles, and
the part of the HPO hierarchy the matching needs (``domains/bridge``).

The hierarchy (``hpo_closure.yaml``) holds, for each HPO term the two files name, its ancestors among those terms — so a
finding of 腰痛 (Low back pain) counts for a profile that lists Back pain, and 跗肿 (Pedal edema) for one that lists Edema,
without shipping the ontology.  ``taochronos bridge verify --obo hp.obo --write`` checks every identifier and label
against a local HPO release and rewrites the closure from it.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ....protocol.bridge import RELATION_WEIGHT, BridgeRelation

TIERS = ("typical", "frequent", "occasional")


@dataclass
class Phenotype:
    id: str
    label: str
    system: str
    hpo: str | None
    hpo_label: str | None
    relation: BridgeRelation
    surfaces: list[str]
    surface_relations: dict[str, BridgeRelation] = field(default_factory=dict)
    note: str = ""

    def relation_of(self, surface: str) -> BridgeRelation:
        return self.surface_relations.get(surface, self.relation)


@dataclass
class Disease:
    id: str
    label: str
    en: str
    icd10: str
    system: str
    course: str
    onset: list[str]
    tiers: dict[str, dict[str, str]]
    against: dict[str, str]
    confirm: dict[str, str]
    tests: str = ""
    note: str = ""
    concept: str | None = None
    sex: str | None = None
    required: dict[str, str] = field(default_factory=dict)  # any one of them, or the resemblance stays low

    def features(self) -> dict[str, tuple[str, str]]:
        """HPO id → (tier, label)."""
        return {h: (t, lab) for t in TIERS for h, lab in self.tiers.get(t, {}).items()}

    def summary(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "en": self.en, "icd10": self.icd10, "system": self.system,
                "course": self.course, "onset": self.onset, **({"sex": self.sex} if self.sex else {}),
                **({"concept": self.concept} if self.concept else {})}


class BridgeData:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        ph = _load(self.root / "phenotypes.yaml")
        dz = _load(self.root / "diseases.yaml")
        self.hpo_release = ph.get("hpo_release") or (dz.get("release") or {}).get("hpo")
        self.phenotypes: dict[str, Phenotype] = {}
        self.by_surface: dict[str, list[str]] = defaultdict(list)
        self.labels: dict[str, str] = {}
        for raw in ph.get("phenotypes", []):
            hpo = raw.get("hpo") or None
            rel = BridgeRelation((hpo or {}).get("relation") or raw.get("relation") or "UNCERTAIN")
            p = Phenotype(id=raw["id"], label=raw["label"], system=raw.get("system", ""), hpo=hpo["id"] if hpo else None,
                          hpo_label=hpo["label"] if hpo else None, relation=rel, surfaces=list(raw["surfaces"]),
                          surface_relations={k: BridgeRelation(v) for k, v in (raw.get("surface_relations") or {}).items()},
                          note=(hpo or {}).get("note") or raw.get("note", ""))
            self.phenotypes[p.id] = p
            for s in p.surfaces:
                if p.id not in self.by_surface[s]:
                    self.by_surface[s].append(p.id)
            if p.hpo:
                self.labels[p.hpo] = p.hpo_label or p.hpo
        self.max_len = max((len(s) for s in self.by_surface), default=1)
        self.ambiguous = {a["surface"]: a for a in ph.get("ambiguous", [])}
        for a in self.ambiguous.values():
            self.by_surface.setdefault(a["surface"], [])
            self.max_len = max(self.max_len, len(a["surface"]))
        self.blocked = sorted(ph.get("blocked", []), key=len, reverse=True)
        self.modifiers: dict[str, dict[str, str]] = ph.get("modifiers", {})
        self.negation = re.compile(ph.get("negation") or r"(?:不|无|未|非)$")
        self.optional = list(ph.get("optional", []))
        self.conditional = list(ph.get("conditional", []))
        self.population: dict[str, str] = ph.get("population", {})
        self.course_patterns = {k: [re.compile(x) for x in v] for k, v in (ph.get("course_patterns") or {}).items()}
        self.weights = {"typical": 1.0, "frequent": 0.6, "occasional": 0.3, "against": 0.8, **(dz.get("weights") or {})}
        self.course_terms = dz.get("course_terms", {})
        self.onset_terms = dz.get("onset_terms", {})
        self.diseases: dict[str, Disease] = {}
        for raw in dz.get("diseases", []):
            d = Disease(id=raw["id"], label=raw["label"], en=raw.get("en", ""), icd10=str(raw.get("icd10", "")),
                        system=raw.get("system", ""), course=raw.get("course", ""), onset=list(raw.get("onset", [])),
                        tiers={t: dict(raw.get(t) or {}) for t in TIERS}, against=dict(raw.get("against") or {}),
                        confirm=dict(raw.get("confirm") or {}), tests=raw.get("tests", ""), note=raw.get("note", ""),
                        concept=raw.get("concept"), sex=raw.get("sex"), required=dict(raw.get("required") or {}))
            unknown = set(d.required) - set(d.features())
            if unknown:
                raise ValueError(f"{d.id}: required findings not in its profile: {sorted(unknown)}")
            self.diseases[d.id] = d
            for part in (*d.tiers.values(), d.against, d.confirm):
                self.labels.update(part)
        self.homonyms: list[dict[str, Any]] = list(dz.get("homonyms", []))
        closure = _load(self.root / "hpo_closure.yaml") if (self.root / "hpo_closure.yaml").exists() else {}
        self.ancestors: dict[str, set[str]] = {k: set(v) for k, v in (closure.get("ancestors") or {}).items()}
        self.closure_release = closure.get("release")
        # document frequency of a phenotype among the profiles: a finding few diseases share says more
        df: dict[str, int] = defaultdict(int)
        for d in self.diseases.values():
            for h in d.features():
                df[h] += 1
        n = len(self.diseases)
        self._df = dict(df)
        self._idf_max = math.log((n + 1) / 0.5)
        self.idf = {h: math.log((n + 1) / (c + 0.5)) / self._idf_max for h, c in df.items()}
        self.by_hpo: dict[str, list[str]] = defaultdict(list)
        for p in self.phenotypes.values():
            if p.hpo:
                self.by_hpo[p.hpo].append(p.id)
        self.by_concept: dict[str, list[str]] = defaultdict(list)
        for d in self.diseases.values():
            if d.concept:
                self.by_concept[d.concept].append(d.id)

    # ------------------------------------------------------------ lookups
    def weight(self, relation: BridgeRelation) -> float:
        return RELATION_WEIGHT[relation]

    def idf_of(self, hpo: str) -> float:
        return self.idf.get(hpo, 1.0)

    def match(self, finding: str, feature: str) -> float:
        """How far a finding's HPO term counts as a profile's feature: the same term 1; the feature an ancestor of the
        finding (腰痛 Low back pain for Back pain) 0.8; the finding an ancestor of the feature (Edema for Pedal edema) 0.5."""
        if finding == feature:
            return 1.0
        if feature in self.ancestors.get(finding, ()):
            return 0.8
        if finding in self.ancestors.get(feature, ()):
            return 0.5
        return 0.0

    def surfaces_for(self, hpo: str, *, with_ancestry: bool = True) -> list[dict[str, Any]]:
        """The ancient phenotypes whose projection is ``hpo`` (or, with ancestry, a narrower term of it)."""
        out = []
        for p in self.phenotypes.values():
            if not p.hpo:
                continue
            m = self.match(p.hpo, hpo) if with_ancestry else float(p.hpo == hpo)
            if m >= 0.8:
                out.append({"phenotype": p.id, "label": p.label, "surfaces": p.surfaces, "relation": p.relation.value,
                            "via": "same" if m == 1.0 else "narrower"})
        return out

    def find_disease(self, key: str) -> Disease | None:
        """A profile by id, Chinese or English name, ICD-10 code (E11 falls in E10-E14) or modern concept id; a name that
        several profiles contain is ambiguous (ValueError naming them)."""
        if key in self.diseases:
            return self.diseases[key]
        k = key.strip().lower()
        code = k.upper()
        for d in self.diseases.values():
            names = {d.label.lower(), d.en.lower(), d.icd10.lower(), d.id.replace("_", " "), (d.concept or "").lower()}
            names |= {part.strip() for part in d.label.lower().replace("（", "(").replace("）", ")").replace(")", "").split("(")}
            if k in names:
                return d
        for d in self.diseases.values():
            if not d.icd10:
                continue
            lo, _, hi = d.icd10.upper().partition("-")
            hi = hi or lo
            if len(code) >= 3 and lo[:1] == code[:1] == hi[:1] and lo[:3] <= code[:3] <= hi[:3]:
                return d
        hits = [d for d in self.diseases.values() if k in d.en.lower() or k in d.label.lower()]
        if len(hits) == 1:
            return hits[0]
        if hits:
            raise ValueError(f"{key!r} names several profiles: " + ", ".join(f"{d.id} ({d.label})" for d in hits))
        return None

    def hpo_ids(self) -> dict[str, str]:
        """Every HPO identifier the bridge names, with its label."""
        out = dict(self.labels)
        for t in (*self.course_terms.values(), *self.onset_terms.values()):
            out[t["id"]] = t["label"]
        return out


# ---------------------------------------------------------------- HPO release
def read_obo(path: str | Path) -> dict[str, Any]:
    """The terms of an OBO file: id → {name, synonyms, obsolete, replaced_by, parents}; alt ids map to their term."""
    terms: dict[str, dict[str, Any]] = {}
    alt: dict[str, str] = {}
    version = None
    cur: dict[str, Any] | None = None
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if version is None and line.startswith("data-version:"):
                version = line.split(":", 1)[1].strip()
            if line == "[Term]":
                cur = {"synonyms": [], "parents": [], "obsolete": False, "replaced_by": None}
            elif line.startswith("["):
                cur = None
            elif cur is not None:
                if line.startswith("id: "):
                    cur["id"] = line[4:]
                    terms[cur["id"]] = cur
                elif line.startswith("name: "):
                    cur["name"] = line[6:]
                elif line.startswith("alt_id: "):
                    alt[line[8:]] = cur.get("id", "")
                elif line.startswith("synonym: "):
                    m = re.match(r'synonym: "(.*?)"', line)
                    if m:
                        cur["synonyms"].append(m.group(1))
                elif line.startswith("is_a: "):
                    cur["parents"].append(line[6:].split(" ")[0])
                elif line.startswith("is_obsolete: true"):
                    cur["obsolete"] = True
                elif line.startswith("replaced_by: "):
                    cur["replaced_by"] = line[13:].strip()
    return {"version": version, "terms": terms, "alt": alt}


def ancestors_of(obo: dict[str, Any], hpo: str) -> set[str]:
    seen: set[str] = set()
    stack = list(obo["terms"].get(hpo, {}).get("parents", []))
    while stack:
        h = stack.pop()
        if h in seen:
            continue
        seen.add(h)
        stack.extend(obo["terms"].get(h, {}).get("parents", []))
    return seen


def verify(data: BridgeData, obo: dict[str, Any]) -> dict[str, Any]:
    """Every HPO identifier and label of the bridge against an HPO release."""
    problems: list[dict[str, Any]] = []
    ids = data.hpo_ids()
    for hpo, label in sorted(ids.items()):
        term = obo["terms"].get(hpo)
        if term is None and hpo in obo["alt"]:
            problems.append({"id": hpo, "label": label, "problem": "alt_id", "use": obo["alt"][hpo]})
            continue
        if term is None:
            problems.append({"id": hpo, "label": label, "problem": "missing"})
        elif term["obsolete"]:
            problems.append({"id": hpo, "label": label, "problem": "obsolete", "use": term.get("replaced_by")})
        elif term.get("name") != label:
            kind = "synonym" if label in term["synonyms"] else "label"
            problems.append({"id": hpo, "label": label, "problem": kind, "name": term.get("name")})
    return {"release": obo.get("version"), "bridge_release": data.hpo_release, "checked": len(ids),
            "ok": len(ids) - len(problems), "problems": problems}


def closure(data: BridgeData, obo: dict[str, Any]) -> dict[str, Any]:
    """For each HPO term the bridge names, its ancestors among those terms (what ``hpo_closure.yaml`` holds)."""
    ids = set(data.hpo_ids())
    out = {}
    for h in sorted(ids):
        anc = sorted(ancestors_of(obo, h) & ids)
        if anc:
            out[h] = anc
    return {"release": obo.get("version"), "ancestors": out}


def write_closure(data: BridgeData, obo: dict[str, Any]) -> Path:
    c = closure(data, obo)
    path = data.root / "hpo_closure.yaml"
    head = ("# The HPO hierarchy among the terms the bridge names: term → its ancestors among them.  Generated by\n"
            "# `taochronos bridge verify --obo hp.obo --write` from the HPO release below (© the Jackson Laboratory and\n"
            "# the Monarch Initiative, hpo.jax.org; identifiers only).  Do not edit by hand.\n")
    body = yaml.safe_dump(c, allow_unicode=True, sort_keys=False, default_flow_style=None, width=140)
    path.write_text(head + body, encoding="utf-8")
    return path


def _load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


__all__ = ["BridgeData", "Disease", "Phenotype", "TIERS", "ancestors_of", "closure", "read_obo", "verify", "write_closure"]
