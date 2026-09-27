"""古今映射 — an ancient description scored against the modern disease profiles, explainably, and the way back.

For each profile the score is built from parts a reader can check:

* **coverage** — how much of the profile's *typical* findings the description gives (each weighted by how specific it is
  among the profiles: polyuria says more than fever);
* **precision** — how much of the description's projected findings the profile explains (typical 1, frequent 0.6,
  occasional 0.3), each finding weighted by its relation to the HPO term (CLOSE 0.9, PARTIAL_OVERLAP 0.6 …) and by its
  standing in the text (optional 0.5, conditional 0.4);
* **conflicts** — findings the profile argues against, and its typical findings the text denies (不渴);
* **compatibility** — course (久 vs an acute disease) and population (小儿, 男子, 妇人);

``fit = (coverage + precision) / 2 × compatibility − conflicts``.  The fit ranks; the reported *level* is qualitative
(high, moderate, low, insufficient), by rules over the matched findings — at most low with fewer than two projected
findings, at most moderate for a drug's or formula's indications, and at most moderate when the next candidate is not
clearly behind.  Nothing here is calibrated: a level is the strength of a phenotypic resemblance, never the probability
that the patient of a text "had" the disease.

``reverse`` goes the other way: from a modern disease to the ancient written forms of its findings, to the passages
that describe several of them together, to the historical names those passages use — candidates for historical study,
not equivalents.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Callable

from ....protocol.bridge import STRENGTH_ORDER, BridgeRelation, Strength
from .data import TIERS, BridgeData, Disease

# evidence mass: the specificity (normalised idf) of the distinct findings behind a candidate, each times its match degree —
# fever and vomiting (0.15, 0.18) weigh little, polyuria and night sweats (0.67) much
MASS_MODERATE = 0.55
MASS_HIGH = 1.0
LEVEL_LABEL = {"high": "高", "moderate": "中", "low": "低", "insufficient": "不足"}
PATTERN_CATEGORIES = ("pattern",)


def observed(data: BridgeData, packet: dict[str, Any]) -> list[dict[str, Any]]:
    """The findings that speak for a profile: projected, presenting, not negated (one per HPO term, the strongest); then
    the findings a named disease implies by its sense, where the text does not state them."""
    best: dict[str, dict[str, Any]] = {}
    stated = [f for f in packet["findings"] if f["status"] == "presenting"]
    implied = [f for f in packet.get("implied", []) if f["status"] == "implied"]
    for f in [*stated, *implied]:
        if not f["hpo"] or f["negated"]:
            continue
        rel = BridgeRelation(f["relation"])
        strength = data.weight(rel) * f["weight"]
        h = f["hpo"]["id"]
        if h not in best or strength > best[h]["strength"]:
            best[h] = {"hpo": h, "label": f["hpo"]["label"], "strength": strength, "relation": rel.value, "finding": f["id"],
                       "surface": f["surface"], "idf": data.idf_of(h), "implied": f["status"] == "implied"}
    return list(best.values())


def denied(packet: dict[str, Any]) -> list[dict[str, Any]]:
    """Findings the text denies (不渴) — unless it affirms the same finding elsewhere (不能发黄 … 身必发黄)."""
    affirmed = {f["hpo"]["id"] for f in packet["findings"] if f["hpo"] and not f["negated"] and f["status"] == "presenting"}
    return [f for f in packet["findings"] if f["hpo"] and f["negated"] and f["status"] == "presenting"
            and f["hpo"]["id"] not in affirmed]


def score(data: BridgeData, packet: dict[str, Any], d: Disease, obs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    obs = observed(data, packet) if obs is None else obs
    features = d.features()
    # coverage of the typical findings
    matched: dict[str, dict[str, Any]] = {}
    for h, (tier, label) in features.items():
        top = None
        for o in obs:
            m = data.match(o["hpo"], h)
            if m and (top is None or m * o["strength"] > top["degree"]):
                top = {"feature": h, "feature_label": label, "tier": tier, "degree": round(m * o["strength"], 3),
                       "idf": round(data.idf_of(h), 3), "implied": o["implied"],
                       "via": o["finding"], "surface": o["surface"], "finding_hpo": o["hpo"], "relation": o["relation"],
                       "hierarchy": "same" if m == 1.0 else ("finding narrower" if m >= 0.8 else "finding broader")}
        if top:
            matched[h] = top
    typical = d.tiers.get("typical", {})
    typ_total = sum(data.idf_of(h) for h in typical) or 1.0
    coverage = sum(data.idf_of(h) * matched[h]["degree"] for h in typical if h in matched) / typ_total
    # precision over the description's findings
    num = den = 0.0
    for o in obs:
        w = o["idf"] * o["strength"]
        den += w
        expl = max((data.match(o["hpo"], h) * data.weights[tier] for h, (tier, _) in features.items()), default=0.0)
        num += w * expl
    precision = num / den if den else 0.0
    # conflicts
    conflicts = []
    for o in obs:
        for h, label in d.against.items():
            if data.match(o["hpo"], h) >= 0.8:
                conflicts.append({"kind": "against", "feature": h, "feature_label": label, "via": o["finding"], "surface": o["surface"],
                                  "weight": round(data.weights["against"] * o["idf"] * o["strength"], 3)})
    for f in denied(packet):
        for h in typical:
            if data.match(f["hpo"]["id"], h) >= 0.8:
                conflicts.append({"kind": "denied_typical", "feature": h, "feature_label": typical[h], "via": f["id"],
                                  "surface": f["surface"], "weight": round(0.5 * data.idf_of(h) * f["weight"], 3)})
    penalty = sum(c["weight"] for c in conflicts) / ((den or 0.0) + typ_total)
    compat, notes = compatibility(packet, d)
    fit = max(0.0, (coverage + precision) / 2 * compat - penalty)
    # what the thresholds count: solid matches (not through a broader finding), distinct findings
    solid = [m for m in matched.values() if m["degree"] >= 0.25 and m["hierarchy"] != "finding broader"]
    only_implied = bool(solid) and all(m["implied"] for m in solid)
    n_typ = len({m["feature"] for m in solid if m["tier"] == "typical"})
    n_all = len({m["via"] for m in solid})
    mass = sum(max(m["idf"] * m["degree"] for m in solid if m["via"] == v) for v in {m["via"] for m in solid})
    missing = [{"feature": h, "label": lab, "surfaces": [s for p in data.surfaces_for(h) for s in p["surfaces"][:3]][:6]}
               for h, lab in typical.items() if h not in matched]
    return {
        "disease": d.id, "label": d.label, "en": d.en, "icd10": d.icd10, "system": d.system,
        "fit": round(fit, 3), "coverage": round(coverage, 3), "precision": round(precision, 3), "penalty": round(penalty, 3),
        "compatibility": {"factor": round(compat, 2), "notes": notes},
        "matched": sorted(matched.values(), key=lambda m: (TIERS.index(m["tier"]), -m["degree"])),
        "typical_matched": n_typ, "typical_total": len(typical), "features_matched": n_all,
        "evidence_mass": round(mass, 3), "implied_support": any(m["implied"] for m in solid), "only_implied": only_implied,
        "required_met": not d.required or any(m["feature"] in d.required for m in solid),
        "required": list(d.required.values()),
        "missing_typical": missing, "conflicts": conflicts,
        "confirm": [{"id": h, "label": lab} for h, lab in d.confirm.items()], "tests": d.tests,
        **({"note": d.note} if d.note else {}),
    }


def compatibility(packet: dict[str, Any], d: Disease) -> tuple[float, list[str]]:
    factor, notes = 1.0, []
    ctx = packet.get("context", {})
    course = set(ctx.get("course", []))
    if "chronic" in course and d.course == "acute":
        factor *= 0.85
        notes.append("the text speaks of a long course; the disease is acute")
    if course & {"acute"} and d.course == "chronic":
        factor *= 0.85
        notes.append("the text speaks of a sudden onset; the disease is chronic")
    pop = set(ctx.get("population", []))
    if "child" in pop and d.onset and "child" not in d.onset:
        factor *= 0.8
        notes.append("the text speaks of a child; the disease rarely begins in childhood")
    if "elderly" in pop and d.onset and not {"elderly", "adult"} & set(d.onset):
        factor *= 0.8
        notes.append("the text speaks of the old")
    if d.sex and (("male" in pop and d.sex == "female") or ("female" in pop and d.sex == "male")):
        factor *= 0.2
        notes.append(f"the text speaks of a {'man' if 'male' in pop else 'woman'}; the disease is of the other sex")
    return factor, notes


def level(c: dict[str, Any]) -> Strength:
    """High: most of the typical picture, three findings or more, enough specific evidence, no conflict.  Moderate: two
    typical findings (or the one a profile has), two findings or more, some specific evidence.  Low: any finding.  (Fit
    and coverage bound each level too.)"""
    typical_ok = c["typical_matched"] >= 2 or (c["typical_total"] == 1 and c["typical_matched"] == 1)
    if (c["fit"] >= 0.55 and c["coverage"] >= 0.6 and c["typical_matched"] >= 2 and c["features_matched"] >= 3
            and c["evidence_mass"] >= MASS_HIGH and not c["conflicts"]):
        return Strength.HIGH
    if (c["fit"] >= 0.35 and c["coverage"] >= 0.4 and c["features_matched"] >= 2 and typical_ok
            and c["evidence_mass"] >= MASS_MODERATE):
        return Strength.MODERATE
    if c["fit"] >= 0.15 and c["features_matched"] >= 1:
        return Strength.LOW
    return Strength.INSUFFICIENT


def capped(r: dict[str, Any], packet: dict[str, Any], n_proj: int) -> tuple[Strength, list[str]]:
    """The level of one candidate with the caps that do not depend on the others."""
    lv = level(r)
    caps = []
    if not r["required_met"] and lv in (Strength.HIGH, Strength.MODERATE):
        lv = Strength.LOW
        caps.append("without " + " / ".join(r["required"]) + " the resemblance stays low")
    if r.get("only_implied") and lv in (Strength.HIGH, Strength.MODERATE):
        lv = Strength.LOW
        caps.append("rests only on what a historical name implies: the passage states none of these findings")
    if r["implied_support"] and lv == Strength.HIGH:
        lv = Strength.MODERATE
        caps.append("rests in part on what a historical name implies by its curated sense, not on stated findings")
    if n_proj < 2 and lv in (Strength.HIGH, Strength.MODERATE):
        lv = Strength.LOW
        caps.append("fewer than two projected findings stated")
    if packet.get("kind") == "indication" and lv == Strength.HIGH:
        lv = Strength.MODERATE
        caps.append("the findings are the indications of a drug or formula, not one patient's picture")
    return lv, caps


def rank(data: BridgeData, packet: dict[str, Any], *, top: int = 5, systems: list[str] | None = None) -> list[dict[str, Any]]:
    """The profiles the description resembles, strongest level first (fit within a level)."""
    obs = observed(data, packet)
    rows = [score(data, packet, d, obs) for d in data.diseases.values() if not systems or d.system in systems]
    rows = [r for r in rows if r["features_matched"] > 0]
    n_proj = len({o["hpo"] for o in obs if not o["implied"]})
    for r in rows:
        r["_level"], r["caps"] = capped(r, packet, n_proj)
    rows.sort(key=lambda r: (-STRENGTH_ORDER.index(r["_level"]), -r["fit"], r["disease"]))
    for k, r in enumerate(rows):
        lv = r.pop("_level")
        if lv == Strength.HIGH:
            close = [x for x in rows[max(0, k - 1): k + 2] if x is not r and abs(x["fit"] - r["fit"]) < 0.1]
            if close:
                lv = Strength.MODERATE
                r["caps"].append("not clearly ahead of " + "、".join(x["label"] for x in close) + " on the findings the text gives")
        r["level"] = lv.value
        r["level_zh"] = LEVEL_LABEL[lv.value]
        r["relation"] = (BridgeRelation.PHENOTYPIC_SIMILARITY if lv != Strength.INSUFFICIENT else BridgeRelation.UNCERTAIN).value
        r["rank"] = k + 1
        r["id"] = f"D{k + 1}"
        r["calibrated"] = False
    rows.sort(key=lambda r: (-STRENGTH_ORDER.index(Strength(r["level"])), -r["fit"], r["disease"]))
    for k, r in enumerate(rows):
        r["rank"], r["id"] = k + 1, f"D{k + 1}"
    return rows[:top]


def discriminators(data: BridgeData, packet: dict[str, Any], cands: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    """What would tell the leading candidates apart: findings typical or frequent in one and absent from (or against)
    another, not given by the text — with the ancient written forms that would state them, and the modern tests."""
    lead = [c for c in cands if c["level"] != "insufficient"][:3]
    if len(lead) < 2:
        return []
    seen = {m["feature"] for c in lead for m in c["matched"]}
    denied_ids = {f["hpo"]["id"] for f in denied(packet)}
    rows: dict[str, dict[str, Any]] = {}
    for c in lead:
        d = data.diseases[c["disease"]]
        for h, (tier, label) in d.features().items():
            if tier == "occasional" or h in seen or h in denied_ids:
                continue
            others = [data.diseases[o["disease"]] for o in lead if o is not c]
            for o in others:
                of = o.features()
                if h in o.against or h not in of or of[h][0] == "occasional":
                    row = rows.setdefault(h, {"feature": h, "label": label, "for": [], "against": [], "idf": round(data.idf_of(h), 3),
                                              "ancient_forms": [s for p in data.surfaces_for(h) for s in p["surfaces"][:3]][:6]})
                    if d.label not in row["for"]:
                        row["for"].append(d.label)
                    if o.label not in row["against"] and h in o.against:
                        row["against"].append(o.label)
    out = sorted(rows.values(), key=lambda r: (not r["against"], -r["idf"], r["feature"]))
    tests = [{"disease": data.diseases[c["disease"]].label, "tests": data.diseases[c["disease"]].tests,
              "confirm": [x["label"] for x in c["confirm"]]} for c in lead if data.diseases[c["disease"]].tests]
    return [*out[:limit], *([{"modern_tests": tests}] if tests else [])]


def term_relations(data: BridgeData, packet: dict[str, Any], cands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """How each historical name in the passage relates to the diseases its curated sense and the homonym table name.

    A sense that is a pattern of TCM's framework (中风#外感) has no modern equivalent; a disease the selected sense names as
    a candidate overlaps in part when the passage's findings fit it (moderate or better), is context-dependent when the
    senses are close, and uncertain otherwise; a disease only the homonym table names (the name coincides, the sense
    selected here is another) is a historical semantic shift."""
    by_id = {c["disease"]: c for c in cands}
    out = []
    for t in packet.get("terms", []):
        named = set(t.get("diseases", []))
        homonym = set((t.get("homonym") or {}).get("diseases", []))
        rows = []
        for did in sorted(named | homonym):
            d = data.diseases.get(did)
            if d is None:
                continue
            c = by_id.get(did)
            why = []
            if t.get("category") in PATTERN_CATEGORIES:
                rel = BridgeRelation.NO_MODERN_EQUIVALENT
                why.append(f"the sense selected here ({t.get('sense_label')}) is a pattern of TCM's framework, not a disease")
            elif did in named:
                if t.get("senses", 0) > 1 and (t.get("p") or 0) < 0.6:
                    rel = BridgeRelation.CONTEXT_DEPENDENT
                    why.append(f"{t['senses']} senses; the context selects {t.get('sense')} only weakly (p={t.get('p')})")
                elif c is not None and c["level"] in ("high", "moderate"):
                    rel = BridgeRelation.PARTIAL_OVERLAP
                    why.append(f"the sense names it as a candidate and the passage's findings fit at level {c['level']}")
                else:
                    rel = BridgeRelation.UNCERTAIN
                    why.append("the curated sense names it as a candidate; the passage's findings do not bear it out"
                               + (f" (level {c['level']})" if c else ""))
            else:
                rel = BridgeRelation.HISTORICAL_SEMANTIC_SHIFT
                why.append(f"the name coincides with the modern one, but the sense selected here is {t.get('sense_label') or 'another'}")
            if did in homonym:
                why.append(t["homonym"]["note"])
            rows.append({"disease": did, "label": d.label, "relation": rel.value, "why": why,
                         **({"level": c["level"]} if c else {})})
        out.append({"id": t["id"], "term": t["term"], "sense": t.get("sense"), "sense_label": t.get("sense_label"),
                    "p": t.get("p"), "relations": rows})
    return out


def statement(packet: dict[str, Any], cands: list[dict[str, Any]], where: str = "") -> str:
    lead = [c for c in cands if c["level"] in ("high", "moderate", "low")]
    n = packet["counts"]["projected"]
    src = where or "这段描述"
    if not lead:
        return (f"{src}可投射到现代表型术语的症状有 {n} 项，不足以与任何现代疾病谱建立表型上的对应；"
                "这不是说它没有对应，而是文本给出的信息不够。")
    head = lead[0]
    others = "、".join(f"{c['label']}（{c['level_zh']}）" for c in lead[1:3])
    what = "主治中" if packet.get("kind") == "indication" else ""
    return (f"{src}所载{what} {n} 项可投射的症状，在表型上与{head['label']}（ICD-10 {head['icd10']}）相容，强度为{head['level_zh']}"
            + (f"；也与{others}相容" if others else "")
            + "。这是表型相似，不是回溯诊断：古今病名并非一一对应，强度未经校准，不是概率。")


# ---------------------------------------------------------------- reverse mapping
def reverse(data: BridgeData, d: Disease, *, find: Callable[[str], list[str]], read_passage: Callable[[str], dict[str, Any] | None],
            limit: int = 20, per_surface: int = 60, min_features: int = 2, indications: bool = False) -> dict[str, Any]:
    """From a modern disease to the passages whose findings resemble it, and the historical names they use."""
    forms: dict[str, list[dict[str, Any]]] = {}
    for h, (tier, label) in d.features().items():
        if tier == "occasional":
            continue
        forms[h] = data.surfaces_for(h)
    probes: list[str] = []
    for h in d.tiers.get("typical", {}):
        for p in forms.get(h, []):
            probes += [s for s in p["surfaces"] if len(s) >= 2][:4]
    candidates: Counter[str] = Counter()
    for s in dict.fromkeys(probes):
        for pid in find(s)[:per_surface]:
            candidates[pid] += 1
    rows = []
    for pid, _ in candidates.most_common(limit * 8):
        info = read_passage(pid)
        if info is None:
            continue
        packet = info["packet"]
        if packet.get("kind") == "indication" and not indications:  # a drug's indications are not a described picture
            continue
        obs = observed(data, packet)
        c = score(data, packet, d, obs)
        if c["features_matched"] < min_features or c["typical_matched"] < 1 or not c["required_met"]:
            continue
        lv, caps = capped(c, packet, len({o["hpo"] for o in obs if not o["implied"]}))
        if lv == Strength.INSUFFICIENT:
            continue
        rows.append({"passage_id": pid, "level": lv.value, "fit": c["fit"], "coverage": c["coverage"], "caps": caps, "matched": [
            {"surface": m["surface"], "feature": m["feature_label"], "tier": m["tier"]} for m in c["matched"]],
            "conflicts": len(c["conflicts"]), "terms": [t["term"] for t in packet.get("terms", [])],
            "witness": info.get("witness"), "year": packet.get("year"), "period": info.get("period")})
    rows.sort(key=lambda r: (-STRENGTH_ORDER.index(Strength(r["level"])), -r["fit"], r["passage_id"]))
    # one row per work and finding set: the editions of a work repeat its passage
    seen: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}
    unique = []
    for r in rows:
        w = r.get("witness") or {}
        key = (w.get("work") or w.get("book_id") or r["passage_id"], tuple(sorted({m["feature"] for m in r["matched"]})))
        if key in seen:
            seen[key]["editions"] = seen[key].get("editions", 1) + 1
            continue
        seen[key] = r
        unique.append(r)
    rows = unique[:limit]
    names: dict[str, Counter[str]] = defaultdict(Counter)
    for r in rows:
        for t in r["terms"]:
            names[t][r.get("period") or "?"] += 1
    return {
        "disease": d.summary(),
        "forms": {data.labels.get(h, h): [s for p in ps for s in p["surfaces"]][:10] for h, ps in forms.items() if ps},
        "unobservable": [data.labels.get(h, h) for h, ps in forms.items() if not ps] + [lab for lab in d.confirm.values()],
        "passages": rows,
        "names": [{"term": t, "passages": sum(c.values()), "periods": dict(c)} for t, c in
                  sorted(names.items(), key=lambda kv: -sum(kv[1].values()))],
        "required": list(d.required.values()),
        "note": ("passages whose stated findings resemble the profile (with at least one of its required findings), and the "
                 "historical names they use: candidates for historical study, not equivalents of the modern disease"),
    }


__all__ = ["compatibility", "discriminators", "level", "observed", "rank", "reverse", "score", "statement", "term_relations"]
