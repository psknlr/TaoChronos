"""The ``modern`` capability (S13): modern literature on a drug, formula or disease, typed by design and population, with
the evidence hierarchy, the cross-level guard and the safety table.

``search`` builds a PubMed query from the Chinese names (``domains/modern/crosswalk.yaml``: 黄连 → Coptis, berberine) and
the disease (a bridge profile's English name), fetches records and abstracts, types each (RCT, cohort, animal, cell,
network pharmacology …) and sums them up by level.  The curated records (``corpus/modern/evidence.yaml``) are always
read; PubMed only when the capability is online (``--online`` on the CLI, ``TAOCHRONOS_PUBMED=1``, or the profile) —
offline, what is cached is used and the result says so.  Nothing here is advice: the safety table only warns.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import yaml

from ...protocol.modern import EVIDENCE_RANK, ClaimLevel, EvidenceType, ModernRecord, Population, cross_level
from .evidence_types import type_record
from .pubmed import PubMed, PubMedError

DESIGN_FILTERS = {
    "rct": "randomized controlled trial[pt]",
    "review": "(systematic review[pt] OR meta-analysis[pt])",
    "human": "humans[mh]",
}


class ModernEvidence:
    def __init__(self, domain: str | Path, *, curated: str | Path | None = None, cache_dir: str | Path, online: bool = False,
                 opener: Callable[[str], bytes] | None = None, diseases: Callable[[], dict[str, Any]] | None = None) -> None:
        self.domain = Path(domain)
        cw = _load(self.domain / "crosswalk.yaml")
        self.drugs: dict[str, dict[str, Any]] = {**(cw.get("drugs") or {}), **(cw.get("formulas") or {})}
        self.safety_table: dict[str, dict[str, Any]] = (_load(self.domain / "safety.yaml").get("materials") or {})
        self.curated_records = list((_load(Path(curated)) if curated and Path(curated).exists() else {}).get("records", []))
        env = os.environ.get("TAOCHRONOS_PUBMED")
        self.pubmed = PubMed(cache_dir, opener=opener, online=online if env is None else env not in ("0", "off", "false"))
        self._diseases = diseases

    @property
    def online(self) -> bool:
        return self.pubmed.online

    @online.setter
    def online(self, value: bool) -> None:
        self.pubmed.online = value

    # ------------------------------------------------------------ names
    def english(self, name: str) -> list[str]:
        row = self.drugs.get(name)
        if row:
            return list(row.get("en", []))
        d = self._disease(name)
        return [d["en"]] if d else ([name] if re.match(r"^[A-Za-z]", name) else [])

    def _disease(self, name: str) -> dict[str, Any] | None:
        if self._diseases is None:
            return None
        table = self._diseases()
        low = name.lower()
        for d in table.values():
            if name in (d["label"], d["id"]) or low == d["en"].lower() or name == d["label"].split("（")[0]:
                return d
        return None

    def names_in(self, text: str) -> dict[str, list[str]]:
        drugs = [n for n in sorted(self.drugs, key=len, reverse=True) if n in text]
        diseases = []
        if self._diseases is not None:
            for d in self._diseases().values():
                short = d["label"].split("（")[0]
                if short in text or d["en"].lower() in text.lower():
                    diseases.append(d["id"])
        for extra, did in (("2型糖尿病", "diabetes_mellitus"), ("糖尿病", "diabetes_mellitus")):
            if extra in text and did not in diseases and self._diseases is not None and did in self._diseases():
                diseases.append(did)
        return {"drugs": drugs, "diseases": diseases}

    def query(self, subject: str, disease: str | None = None, design: str | None = None) -> str:
        names = self.english(subject) or [subject]
        q = "(" + " OR ".join(f'"{n}"[tiab]' for n in names) + ")"
        if disease:
            dn = self.english(disease) or [disease]
            q += " AND (" + " OR ".join(f'"{n}"[tiab]' for n in dn) + ")"
        if design:
            q += " AND " + DESIGN_FILTERS.get(design, design)
        return q

    # ------------------------------------------------------------ search
    def search(self, subject: str, disease: str | None = None, *, design: str | None = None, limit: int = 20) -> dict[str, Any]:
        q = self.query(subject, disease, design)
        records: list[dict[str, Any]] = []
        errors: list[str] = []
        source = "pubmed" if self.online else "cache"
        try:
            pmids = self.pubmed.search(q, retmax=limit)
            summaries = self.pubmed.summaries(pmids)
            try:
                extra = self.pubmed.abstracts(pmids)
            except PubMedError as exc:
                extra, _ = {}, errors.append(f"abstracts: {exc}")
            for s in summaries:
                more = extra.get(s["pmid"], {})
                pts = more.get("publication_types") or s["publication_types"]
                et, pop, rule = type_record(pts, s["title"], more.get("abstract", ""), more.get("mesh"))
                rec = ModernRecord(id=f"pmid:{s['pmid']}", title=s["title"], source="pubmed", year=s["year"], journal=s["journal"],
                                   pmid=s["pmid"], doi=s["doi"], publication_types=pts, evidence_type=et, population=pop,
                                   typing_rule=rule, url=f"https://pubmed.ncbi.nlm.nih.gov/{s['pmid']}/",
                                   retracted="Retracted Publication" in pts)
                records.append(rec.to_dict())
        except PubMedError as exc:
            errors.append(str(exc))
            source = "unavailable"
        records += self.curated(subject, disease)
        return {"subject": subject, "disease": disease, "query": q, "source": source, "records": records,
                "summary": summarize(records), "safety": self.safety(subject), "errors": errors,
                "note": ("modern literature typed by design and population; a record's type is the rule's reading of its "
                         "indexing, to be checked; nothing here is medical advice")}

    def curated(self, subject: str, disease: str | None = None) -> list[dict[str, Any]]:
        out = []
        for r in self.curated_records:
            terms = r.get("related_terms", [])
            if subject in terms or subject in r.get("subject", "") or (disease and disease in (r.get("concept_id") or "")):
                et = EvidenceType(r.get("evidence_type", "unknown"))
                out.append(ModernRecord(id=r["id"], title=r.get("statement", "")[:200], source="curated", evidence_type=et,
                                        population=Population(r.get("population", "unknown")), typing_rule="curated",
                                        url=r.get("url", "")).to_dict() | {"citation": r.get("source")})
        return out

    def for_claim(self, text: str, *, limit: int = 15) -> list[dict[str, Any]]:
        """The typed records bearing on a claim: its drugs against its diseases (the audit's modern evidence)."""
        names = self.names_in(text)
        out: list[dict[str, Any]] = []
        for drug in names["drugs"][:2]:
            for dis in names["diseases"][:1] or [None]:
                out += self.search(drug, dis, limit=limit)["records"]
        seen, uniq = set(), []
        for r in out:
            if r["id"] not in seen:
                seen.add(r["id"])
                uniq.append(r)
        return uniq

    def safety(self, text: str) -> list[dict[str, Any]]:
        out = []
        for name, row in self.safety_table.items():
            hit = next((f for f in [name, *row.get("aliases", [])] if f and f in text), None)
            if hit:
                out.append({"material": name, "found": hit, "risk": row.get("risk"), **({"note": row["note"]} if row.get("note") else {})})
        return out

    def guard(self, claim: str, records: list[dict[str, Any]]) -> dict[str, Any]:
        """The cross-level guard: which records can carry the claim, and why the others cannot."""
        from ...verification.audit import claim_level

        level = claim_level(claim)
        rows = []
        for r in records:
            why = cross_level(level, EvidenceType(r["evidence_type"]))
            rows.append({"id": r["id"], "type": r["evidence_type"], "can_carry": why is None, **({"why": why} if why else {})})
        return {"claim_level": level.value, "records": rows, "carrying": sum(1 for x in rows if x["can_carry"])}


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    types = Counter(r["evidence_type"] for r in records if not r.get("retracted"))
    human = [r for r in records if r["evidence_type"] in {e.value for e in EVIDENCE_RANK} and not r.get("retracted")]
    best = min((EVIDENCE_RANK[EvidenceType(r["evidence_type"])] for r in human), default=None)
    best_types = sorted({r["evidence_type"] for r in human if EVIDENCE_RANK[EvidenceType(r["evidence_type"])] == best}) if best else []
    return {"by_type": dict(types), "by_population": dict(Counter(r["population"] for r in records)),
            "retracted": sum(1 for r in records if r.get("retracted")), "best_human_level": best, "best_human_types": best_types,
            "can_carry_efficacy": sum(1 for r in records if cross_level(ClaimLevel.HUMAN_EFFICACY, EvidenceType(r["evidence_type"])) is None)}


def _load(path: Path) -> dict[str, Any]:
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.exists() else {}


__all__ = ["ModernEvidence", "summarize"]
