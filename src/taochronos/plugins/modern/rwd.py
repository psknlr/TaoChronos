"""真实世界数据 (S14 RWD) — a question about real-world data, as a structured study, over the OMOP common data model.

A question becomes a ``StudySpec`` (protocol/modern.py): exposure and outcome concept sets, the population, the design,
the time windows.  The spec is written by rules (names resolved against the database's own ``concept`` table) or proposed
by a model — which never writes SQL — and validated against its schema and the vocabulary before anything runs.  A
validated spec is compiled into one fixed, parameterised query (a new-user cohort: the population's first qualifying
condition is the index, exposure after it, outcome in the follow-up window, the outcome in the washout window excluded)
and the SQL is checked (read-only, the OMOP tables only, every value a bound parameter) before it is run on a read-only
connection.  The result is counts, risks and a crude risk ratio with its interval — observational, unadjusted, and said
to be so.

``synthesize`` writes a small synthetic OMOP database (clearly fake people, concept ids in the local range above two
billion) for tests and demonstrations; point ``--db`` at a real OMOP CDM (SQLite export) to ask a real one.
"""

from __future__ import annotations

import json
import math
import random
import re
import sqlite3
from pathlib import Path
from typing import Any

from ...protocol.modern import STUDY_SPEC_SCHEMA
from ...protocol.schema import validate

OMOP_TABLES = {"person", "observation_period", "condition_occurrence", "drug_exposure", "concept", "concept_ancestor",
               "measurement", "observation"}
FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|replace|vacuum|reindex|grant)\b", re.I)
GENDER = {"male": 8507, "female": 8532}  # the OMOP standard gender concepts


# ---------------------------------------------------------------- vocabulary
def concept_ids(db: sqlite3.Connection, name: str, domain: str | None = None) -> list[int]:
    """Standard concepts named ``name`` (exact, then contained), with their descendants."""
    q = "SELECT concept_id FROM concept WHERE lower(concept_name) = lower(?)" + (" AND lower(domain_id) = lower(?)" if domain else "")
    rows = [r[0] for r in db.execute(q, (name, domain) if domain else (name,))]
    if not rows:
        q = "SELECT concept_id FROM concept WHERE lower(concept_name) LIKE lower(?)" + (" AND lower(domain_id) = lower(?)" if domain else "")
        rows = [r[0] for r in db.execute(q, (f"%{name}%", domain) if domain else (f"%{name}%",))]
    out = set(rows)
    if rows:
        marks = ",".join("?" * len(rows))
        out |= {r[0] for r in db.execute(f"SELECT descendant_concept_id FROM concept_ancestor WHERE ancestor_concept_id IN ({marks})", rows)}
    return sorted(out)


def names_in_vocabulary(db: sqlite3.Connection) -> dict[str, list[tuple[str, str]]]:
    """Chinese and English names of the vocabulary's concepts, by domain (for reading a question)."""
    out: dict[str, list[tuple[str, str]]] = {}
    for name, domain, synonyms in db.execute("SELECT concept_name, domain_id, coalesce(concept_synonyms, '') FROM concept"):
        for n in [name, *[s for s in synonyms.split("|") if s]]:
            out.setdefault(domain.lower(), []).append((n, name))
    return out


# ---------------------------------------------------------------- the question → a study spec (rules)
def spec_from_question(question: str, db: sqlite3.Connection) -> dict[str, Any]:
    """Rules: the drugs the question names are the exposure, a condition named with 患者/人群 the population, another
    condition the outcome.  Unresolvable parts are reported, not guessed."""
    vocab = names_in_vocabulary(db)
    found: dict[str, list[tuple[int, str, str]]] = {"drug": [], "condition": []}
    for domain in ("drug", "condition"):
        for surface, canonical in sorted(vocab.get(domain, []), key=lambda x: -len(x[0])):
            i = question.find(surface)
            if i >= 0 and not any(i < p + len(s) and p < i + len(surface) for p, s, _ in found[domain]):
                found[domain].append((i, surface, canonical))
    found = {k: sorted(v) for k, v in found.items()}
    notes = []
    pop = next(((i, s, c) for i, s, c in found["condition"] if re.search(re.escape(s) + r"(?:患者|病人|人群)", question)), None)
    rest = [x for x in found["condition"] if x != pop]
    outcome = rest[0] if rest else None
    exposure = found["drug"][0] if found["drug"] else None
    spec: dict[str, Any] = {
        "question": question, "design": "cohort" if exposure else "descriptive",
        "population": {"name": pop[2] if pop else "all persons", **({"concepts": concept_ids(db, pop[2], "condition")} if pop else {}),
                       "sex": "female" if "女" in question else "male" if re.search(r"男(?!女)", question) else "any"},
        "time": {"washout_days": 365, "followup_days": 365 * (int(m.group(1)) if (m := re.search(r"(\d+)\s*年", question)) else 1)},
    }
    if exposure:
        spec["exposure"] = {"name": exposure[2], "concepts": concept_ids(db, exposure[2], "drug"), "domain": "drug"}
    else:
        notes.append("no exposure the vocabulary knows: a descriptive count only")
    if outcome:
        spec["outcome"] = {"name": outcome[2], "concepts": concept_ids(db, outcome[2], "condition"), "domain": "condition"}
    else:
        notes.append("no outcome the vocabulary knows")
    age = re.search(r"(\d+)\s*岁(?:以上|及以上)", question)
    if age:
        spec["population"]["age_min"] = int(age.group(1))
    spec["notes"] = notes
    return spec


def check_spec(spec: dict[str, Any], db: sqlite3.Connection | None = None) -> list[str]:
    errors = validate(spec, STUDY_SPEC_SCHEMA)
    if errors:
        return errors
    if spec["design"] == "cohort" and "exposure" not in spec:
        errors.append("a cohort design needs an exposure")
    if db is not None:
        known = {r[0] for r in db.execute("SELECT concept_id FROM concept")}
        for part in ("exposure", "outcome", "population", "comparator"):
            for cid in (spec.get(part) or {}).get("concepts", []):
                if cid not in known:
                    errors.append(f"{part}: concept {cid} is not in the vocabulary")
    if spec["time"]["followup_days"] <= 0 or spec["time"]["washout_days"] < 0:
        errors.append("time windows must be positive")
    return errors


# ---------------------------------------------------------------- the spec → SQL (fixed templates)
def compile_spec(spec: dict[str, Any]) -> tuple[str, list[Any]]:
    """One parameterised query for the spec: population, exposure (new users after the index), outcome in follow-up."""
    params: list[Any] = []

    def marks(values: list[int]) -> str:
        params.extend(values)
        return ",".join("?" * len(values))

    pop = spec["population"]
    pop_concepts = pop.get("concepts") or []
    if pop_concepts:
        base = (f"SELECT person_id, min(condition_start_date) AS index_date FROM condition_occurrence "
                f"WHERE condition_concept_id IN ({marks(pop_concepts)}) GROUP BY person_id")
    else:
        base = "SELECT person_id, min(observation_period_start_date) AS index_date FROM observation_period GROUP BY person_id"
    filters = []
    if pop.get("sex", "any") != "any":
        filters.append("p.gender_concept_id = ?")
        params.append(GENDER[pop["sex"]])
    if pop.get("age_min") is not None:
        filters.append("(CAST(substr(b.index_date, 1, 4) AS INTEGER) - p.year_of_birth) >= ?")
        params.append(int(pop["age_min"]))
    if pop.get("age_max") is not None:
        filters.append("(CAST(substr(b.index_date, 1, 4) AS INTEGER) - p.year_of_birth) <= ?")
        params.append(int(pop["age_max"]))
    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    sql = [f"WITH base AS ({base}),",
           f"pop AS (SELECT b.person_id, b.index_date FROM base b JOIN person p ON p.person_id = b.person_id {where}),"]
    fu = int(spec["time"]["followup_days"])
    wo = int(spec["time"]["washout_days"])
    if "exposure" in spec:
        exp = marks(spec["exposure"]["concepts"])
        sql.append(f"exp AS (SELECT pop.person_id, min(d.drug_exposure_start_date) AS t0 FROM pop JOIN drug_exposure d "
                   f"ON d.person_id = pop.person_id AND d.drug_concept_id IN ({exp}) AND d.drug_exposure_start_date >= pop.index_date "
                   f"GROUP BY pop.person_id),")
        sql.append("arms AS (SELECT pop.person_id, CASE WHEN exp.person_id IS NULL THEN 0 ELSE 1 END AS exposed, "
                   "coalesce(exp.t0, pop.index_date) AS t0 FROM pop LEFT JOIN exp ON exp.person_id = pop.person_id),")
    else:
        sql.append("arms AS (SELECT person_id, 0 AS exposed, index_date AS t0 FROM pop),")
    out_c = spec["outcome"]["concepts"] if "outcome" in spec else []
    if out_c:
        o1 = marks(out_c)
        params.append(wo)
        o2 = marks(out_c)
        params.append(fu)
        sql.append(f"prior AS (SELECT DISTINCT a.person_id FROM arms a JOIN condition_occurrence c ON c.person_id = a.person_id "
                   f"AND c.condition_concept_id IN ({o1}) AND c.condition_start_date < a.t0 "
                   f"AND julianday(a.t0) - julianday(c.condition_start_date) <= ?),")
        sql.append(f"events AS (SELECT DISTINCT a.person_id FROM arms a JOIN condition_occurrence c ON c.person_id = a.person_id "
                   f"AND c.condition_concept_id IN ({o2}) AND c.condition_start_date >= a.t0 "
                   f"AND julianday(c.condition_start_date) - julianday(a.t0) <= ?)")
        sql.append("SELECT a.exposed AS exposed, count(*) AS n, sum(CASE WHEN e.person_id IS NULL THEN 0 ELSE 1 END) AS events "
                   "FROM arms a LEFT JOIN events e ON e.person_id = a.person_id "
                   "WHERE a.person_id NOT IN (SELECT person_id FROM prior) GROUP BY a.exposed ORDER BY a.exposed")
    else:
        sql[-1] = sql[-1].rstrip(",")
        sql.append("SELECT a.exposed AS exposed, count(*) AS n, 0 AS events FROM arms a GROUP BY a.exposed ORDER BY a.exposed")
    return "\n".join(sql), params


def check_sql(sql: str, params: list[Any]) -> list[str]:
    errors = []
    body = sql.strip()
    if not re.match(r"^(WITH|SELECT)\b", body, re.I):
        errors.append("not a read-only query")
    if ";" in body.rstrip(";"):
        errors.append("more than one statement")
    if FORBIDDEN.search(body):
        errors.append("a write or schema statement")
    ctes = {m.group(1).lower() for m in re.finditer(r"(\w+)\s+AS\s*\(", body, re.I)}
    tables = {m.group(1).lower() for m in re.finditer(r"\b(?:FROM|JOIN)\s+([A-Za-z_][\w]*)", body, re.I)}
    unknown = tables - OMOP_TABLES - ctes
    if unknown:
        errors.append(f"tables outside the OMOP CDM: {sorted(unknown)}")
    if re.search(r"'[^']*'", body):
        errors.append("a literal in the query: every value must be a bound parameter")
    if body.count("?") != len(params):
        errors.append("placeholders and parameters differ")
    return errors


def run(spec: dict[str, Any], db_path: str | Path) -> dict[str, Any]:
    uri = f"file:{Path(db_path).resolve()}?mode=ro"
    db = sqlite3.connect(uri, uri=True)
    try:
        errors = check_spec(spec, db)
        if errors:
            return {"ok": False, "stage": "spec", "errors": errors, "spec": spec}
        sql, params = compile_spec(spec)
        errors = check_sql(sql, params)
        if errors:
            return {"ok": False, "stage": "sql", "errors": errors, "sql": sql}
        rows = {r[0]: {"n": r[1], "events": r[2] or 0} for r in db.execute(sql, params)}
        synthetic = bool(db.execute("SELECT count(*) FROM sqlite_master WHERE name = 'taochronos_synthetic'").fetchone()[0])
    finally:
        db.close()
    out: dict[str, Any] = {"ok": True, "spec": spec, "sql": sql, "parameters": len(params), "synthetic": synthetic,
                           "arms": {("exposed" if k else "unexposed"): {**v, "risk": round(v["events"] / v["n"], 4) if v["n"] else None}
                                    for k, v in rows.items()}}
    e, u = rows.get(1), rows.get(0)
    if e and u and e["n"] and u["n"] and e["events"] and u["events"]:
        rr = (e["events"] / e["n"]) / (u["events"] / u["n"])
        se = math.sqrt(1 / e["events"] - 1 / e["n"] + 1 / u["events"] - 1 / u["n"])
        out["risk_ratio"] = {"estimate": round(rr, 3), "ci95": [round(math.exp(math.log(rr) - 1.96 * se), 3),
                                                                 round(math.exp(math.log(rr) + 1.96 * se), 3)]}
    out["caveats"] = (["synthetic data: a demonstration, not a finding"] if synthetic else []) + [
        "observational and unadjusted: confounding by indication and healthy-user effects are not removed",
        "a crude risk ratio is not a treatment effect; a real study needs a protocol, adjustment and review",
        "not medical advice"]
    return out


# ---------------------------------------------------------------- a synthetic OMOP database
SYNTH_CONCEPTS = [
    # id, name, domain, synonyms (Chinese names first), ancestor
    (2_000_000_001, "Type 2 diabetes mellitus", "Condition", "2型糖尿病|糖尿病", None),
    (2_000_000_002, "Diabetic nephropathy", "Condition", "糖尿病肾病", None),
    (2_000_000_003, "Diabetic retinopathy", "Condition", "糖尿病视网膜病变", None),
    (2_000_000_004, "Essential hypertension", "Condition", "高血压", None),
    (2_000_000_005, "Acute myocardial infarction", "Condition", "急性心肌梗死|心肌梗死", None),
    (2_000_000_101, "Metformin", "Drug", "二甲双胍", None),
    (2_000_000_102, "Berberine", "Drug", "小檗碱|黄连素", None),
    (2_000_000_103, "Berberine 100 MG Oral Tablet", "Drug", "黄连素片", 2_000_000_102),
    (2_000_000_104, "Insulin", "Drug", "胰岛素", None),
    (2_000_000_105, "Coptis preparation", "Drug", "黄连", None),
]


def synthesize(path: str | Path, *, persons: int = 3000, seed: int = 7) -> dict[str, Any]:
    """A small synthetic OMOP CDM (SQLite): fake people, local concept ids, a planted and documented association."""
    p = Path(path)
    if p.exists():
        p.unlink()
    db = sqlite3.connect(p)
    db.executescript("""
        CREATE TABLE taochronos_synthetic (note TEXT);
        CREATE TABLE concept (concept_id INTEGER PRIMARY KEY, concept_name TEXT, domain_id TEXT, vocabulary_id TEXT,
                              standard_concept TEXT, concept_synonyms TEXT);
        CREATE TABLE concept_ancestor (ancestor_concept_id INTEGER, descendant_concept_id INTEGER, min_levels_of_separation INTEGER);
        CREATE TABLE person (person_id INTEGER PRIMARY KEY, gender_concept_id INTEGER, year_of_birth INTEGER);
        CREATE TABLE observation_period (person_id INTEGER, observation_period_start_date TEXT, observation_period_end_date TEXT);
        CREATE TABLE condition_occurrence (person_id INTEGER, condition_concept_id INTEGER, condition_start_date TEXT);
        CREATE TABLE drug_exposure (person_id INTEGER, drug_concept_id INTEGER, drug_exposure_start_date TEXT);
    """)
    db.execute("INSERT INTO taochronos_synthetic VALUES (?)", ("synthetic people for tests and demonstrations; the association "
                                                              "between berberine and nephropathy is planted, not real",))
    for cid, name, domain, syn, parent in SYNTH_CONCEPTS:
        db.execute("INSERT INTO concept VALUES (?,?,?,?,?,?)", (cid, name, domain, "TaoChronos-synthetic", "S", syn))
        if parent:
            db.execute("INSERT INTO concept_ancestor VALUES (?,?,1)", (parent, cid))
    rng = random.Random(seed)

    def day(y: int, d: int) -> str:
        import datetime

        return (datetime.date(y, 1, 1) + datetime.timedelta(days=d)).isoformat()

    for pid in range(1, persons + 1):
        sex = rng.choice(("male", "female"))
        yob = rng.randint(1940, 1995)
        db.execute("INSERT INTO person VALUES (?,?,?)", (pid, GENDER[sex], yob))
        db.execute("INSERT INTO observation_period VALUES (?,?,?)", (pid, "2015-01-01", "2023-12-31"))
        if rng.random() < 0.6:
            t0 = rng.randint(0, 1500)
            db.execute("INSERT INTO condition_occurrence VALUES (?,?,?)", (pid, 2_000_000_001, day(2015, t0)))
            berb = rng.random() < 0.3
            if rng.random() < 0.7:
                db.execute("INSERT INTO drug_exposure VALUES (?,?,?)", (pid, 2_000_000_101, day(2015, t0 + rng.randint(0, 60))))
            if berb:
                db.execute("INSERT INTO drug_exposure VALUES (?,?,?)",
                           (pid, rng.choice((2_000_000_102, 2_000_000_103)), day(2015, t0 + rng.randint(0, 90))))
            risk = 0.10 if berb else 0.16  # planted: a documented, synthetic association
            if rng.random() < risk:
                db.execute("INSERT INTO condition_occurrence VALUES (?,?,?)", (pid, 2_000_000_002, day(2015, t0 + rng.randint(120, 330))))
        if rng.random() < 0.3:
            db.execute("INSERT INTO condition_occurrence VALUES (?,?,?)", (pid, 2_000_000_004, day(2015, rng.randint(0, 2500))))
    db.commit()
    counts = {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("person", "condition_occurrence", "drug_exposure", "concept")}
    db.close()
    return {"path": str(p), "counts": counts, "note": "synthetic OMOP CDM subset: fake people; not for any finding"}


def spec_by_model(question: str, db: sqlite3.Connection, judge: Any) -> dict[str, Any]:
    """A model proposes the spec (never SQL); concepts are named and resolved against the vocabulary, then validated."""
    vocab = names_in_vocabulary(db)
    lines = [f"问题：{question}", "把问题写成研究规格（StudySpec，JSON）：design 取 cohort | descriptive；exposure / outcome / population 各给 name（只能用下列词表中的名称）。"
             "不要写 SQL。", "词表：" + "；".join(f"{d}: " + "、".join(sorted({c for _, c in v})) for d, v in vocab.items())]
    schema = {"type": "object", "required": ["design", "population", "time"], "properties": {
        "design": {"enum": ["cohort", "descriptive"]}, "exposure": {"type": "object", "properties": {"name": {"type": "string"}}},
        "outcome": {"type": "object", "properties": {"name": {"type": "string"}}},
        "population": {"type": "object", "properties": {"name": {"type": "string"}, "sex": {"enum": ["any", "female", "male"]},
                                                        "age_min": {"type": "integer"}}},
        "time": {"type": "object", "properties": {"washout_days": {"type": "integer"}, "followup_days": {"type": "integer"}}}}}
    res = judge.ask("rwd.spec", "你是真实世界研究的设计者：只写研究规格，不写 SQL。", "\n".join(lines), schema=schema)
    if not res.ok:
        return {"ok": False, "error": res.error}
    d = res.data
    spec: dict[str, Any] = {"question": question, "design": d["design"], "time": {"washout_days": int(d["time"].get("washout_days", 365)),
                                                                                  "followup_days": int(d["time"].get("followup_days", 365)),}}
    pop = d.get("population") or {}
    spec["population"] = {"name": pop.get("name") or "all persons", "sex": pop.get("sex", "any"),
                          **({"age_min": int(pop["age_min"])} if pop.get("age_min") is not None else {})}
    if pop.get("name") and pop["name"] != "all persons":
        spec["population"]["concepts"] = concept_ids(db, pop["name"], "condition")
    for part, domain in (("exposure", "drug"), ("outcome", "condition")):
        if (d.get(part) or {}).get("name"):
            spec[part] = {"name": d[part]["name"], "concepts": concept_ids(db, d[part]["name"], domain), "domain": domain}
    spec["notes"] = ["proposed by a model, resolved against the vocabulary and validated"]
    return spec


def load_spec(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


__all__ = ["OMOP_TABLES", "check_spec", "check_sql", "compile_spec", "concept_ids", "load_spec", "run", "spec_by_model",
           "spec_from_question", "synthesize"]
