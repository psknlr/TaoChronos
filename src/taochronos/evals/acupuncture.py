"""AcupunctureEval (针灸选穴配穴): the specific-point data and the reasoning over it against an independent statement of the
tables and teaching examples (``evals/gold/acupuncture.yaml``), and — with the full corpus — the data against what the
classics' own entries state.

* **tables** — the Five-Shu points of every channel, their phases (Nanjing 64), the Yuan, Luo and Xi points (with the three
  extra Luo and the four Xi of the extraordinary vessels), the Back-Shu and Front-Mu points, the Eight Influential points,
  the confluent pairs, the Lower He-Sea points and the mother–child points (Nanjing 69): each entry of the gold matched;
* **combinations** — pairs of points named for the methods they form, and not for those they do not (合谷 + 太冲 is no
  Yuan–Luo pair, 太渊 + 列缺 not the host–guest structure);
* **selection** — the review's examples and textbook prescriptions: the points a presentation must choose (in its core,
  or among all), the distal point a located headache needs, and the points it must not (in pregnancy);
* **five phases** — the Liver's points against Liver Wood, the Saam templates of the twelve channels, the paired
  deductions, and Five-Phase states (木实 土虚 金虚, 肝虚, 心实, 肝郁脾虚 …) against the relations, strategies, classical
  statements, opposite intentions, method points and the claims the reasoning must answer (``wuxing``);
* **real** (the full corpus) — for every Five-Shu point, the entries of the acupuncture books that state its phase and its
  kind (「太渊者，土也……为俞」): how many points are stated, the share agreeing with the data, and every witness that
  differs, to be read (an error of the data, a variant reading — the Siku 甲乙经's 太渊者水也 — or a misreading).
"""

from __future__ import annotations

from typing import Any

from .base import EvalContext, SuiteResult


def _match(rows: list[tuple[str, Any, Any]]) -> dict[str, Any]:
    wrong = [{"what": w, "gold": g, "data": d} for w, g, d in rows if g != d]
    return {"matched": f"{len(rows) - len(wrong)}/{len(rows)}", "wrong": wrong}


def acupuncture(ctx: EvalContext) -> SuiteResult:
    h = ctx.default
    study = h.capabilities.get("study")
    acu = study._acupuncture
    fw = acu.fw
    gold = ctx.gold("acupuncture")
    d = fw.d
    phase = lambda code: next((c["phase"] for c in fw.categories(code) if c["type"] == "five_shu"), None)  # noqa: E731
    tables: dict[str, Any] = {}
    tables["five_shu"] = _match([(ch, codes, d["five_shu"]["points"].get(ch)) for ch, codes in gold["five_shu"].items()])
    tables["phases"] = _match([(code, p, phase(code)) for code, p in gold["phases"].items()])
    tables["yuan_luo_xi"] = _match([(ch, codes, [d["yuan"].get(ch), d["luo"].get(ch), d["xi"].get(ch)])
                                    for ch, codes in gold["yuan_luo_xi"].items()])
    tables["extra"] = _match([(k, v, d["luo"].get(k)) for k, v in gold["extra_luo"].items()]
                             + [(k, v, d["xi"].get(k)) for k, v in gold["extra_xi"].items()])
    tables["shu_mu"] = _match([(o, codes, [d["back_shu"].get(o), d["front_mu"].get(o)]) for o, codes in gold["shu_mu"].items()])
    tables["hui"] = _match([(k, v, (d["hui"].get(k) or {}).get("point")) for k, v in gold["hui"].items()])
    tables["confluent"] = _match([("pairs", sorted(map(sorted, gold["confluent_pairs"])), sorted(sorted(p["points"]) for p in d["confluent"]["pairs"]))])
    tables["lower_he"] = _match([(k, v, d["lower_he"].get(k)) for k, v in gold["lower_he"].items()])
    mc = []
    for ch, want in gold["mother_child"].items():
        m = fw.mother_child(ch)
        mc.append((ch, want, [m["same"]["mother"], m["cross"]["mother"], m["same"]["child"], m["cross"]["child"]]))
    tables["mother_child"] = _match(mc)
    tables["channel_relations"] = _match([(code, want, [fw.shu_phase(code), fw.relation(fw.shu_phase(code), fw.channels[fw.points[code]["channel"]]["phase"])])
                                          for code, want in gold["channel_relations"].items()])
    tables["saam"] = _match([(ch, [sorted(x) for x in want],
                              [sorted(fw.saam(ch)[st][act]["points"]) for st, act in (("deficiency", "tonify"), ("deficiency", "sedate"),
                                                                                       ("excess", "tonify"), ("excess", "sedate"))])
                             for ch, want in gold["saam"].items()])
    tables["paired"] = _match([(f"{ch}:{via}", pts, [fw.paired(ch)[via]["mother"], fw.paired(ch)[via]["child"]])
                               for ch, vias in gold["paired"].items() for via, pts in vias.items()])
    details: list[dict[str, Any]] = []
    # combinations
    ok_c = 0
    for g in gold["combinations"]:
        regions = [fw.lookup("region", g["region"])] if g.get("region") else []
        pres = acu._presentation(None, regions, [], [], [], [], None, None, False)
        combos = acu._combinations(list(g["points"]), {}, pres)
        methods = {c["method"] for c in combos if set(c["points"]) >= set(g["points"]) or c["method"] in ("local_distal", "upper_lower",
                                                                                                            "anterior_posterior")}
        classical_yl = any(c["method"] == "yuan_luo" and c.get("classical") is not False for c in combos)
        ok = set(g["expect"]) <= methods and not set(g.get("forbid") or []) & methods
        if g.get("classical_yuan_luo") is False:
            ok = ok and not classical_yl
        if "yuan_luo" in g["expect"]:
            ok = ok and classical_yl
        ok_c += ok
        details.append({"case": "combination:" + "+".join(g["points"]), "pass": ok, "methods": sorted(methods)})
    # selection
    ok_s = 0
    for g in gold["selection"]:
        r = study.acupoints(g.get("text"), regions=g.get("regions") or (), symptoms=g.get("symptoms") or (),
                            organs=g.get("organs") or (), natures=g.get("natures") or (), pregnant=bool(g.get("pregnant")))
        core = [p["code"] for p in r["prescription"]["core"]]
        every = core + [p["code"] for p in r["prescription"]["supplementary"]]
        checks = {"core": set(g.get("core") or []) <= set(core), "must": set(g.get("must") or []) <= set(every),
                  "any": not g.get("any") or bool(set(g["any"]) & set(every)),
                  "distal": not g.get("must_any_distal") or bool(set(g["must_any_distal"]) & set(every)),
                  "forbid": not set(g.get("forbid") or []) & set(every)}
        ok = all(checks.values())
        ok_s += ok
        details.append({"case": f"selection:{g['id']}", "pass": ok, "chosen": every, "core": core,
                        "failed": [k for k, v in checks.items() if not v]})
    # Five Phases
    ok_w = 0
    for g in gold["wuxing"]:
        r = study.wuxing(g["text"])
        pts = {m["method"]: [p["code"] for p in m["points"]] for m in r["methods"]}
        checks = {"relations": set(g.get("relations") or []) <= {x["kind"] for x in r["relations"]},
                  "strategies": set(g.get("strategies") or []) <= {s["name"] for s in r["strategies"] if s["fit"] == "full"},
                  "classical": all({c["rule"]: c["status"] for c in r["classical"]}.get(k) == v for k, v in (g.get("classical") or {}).items()),
                  "conflicts": set(g.get("conflicts") or []) <= {c["code"] for c in r["conflicts"]},
                  "guards": set(g.get("guards") or []) <= {x["id"] for x in r["guards"]},
                  "claims": set(g.get("claims") or []) <= {x["id"] for x in r["guards"] if x["claim"]},
                  "points": all(pts.get(m) == want for m, want in (g.get("points") or {}).items())}
        ok = all(checks.values())
        ok_w += ok
        details.append({"case": f"wuxing:{g['id']}", "pass": ok, "failed": [k for k, v in checks.items() if not v]})
    metrics: dict[str, Any] = {"tables": {k: v["matched"] for k, v in tables.items()},
                               "combinations": f"{ok_c}/{len(gold['combinations'])}", "selection": f"{ok_s}/{len(gold['selection'])}",
                               "wuxing": f"{ok_w}/{len(gold['wuxing'])}"}
    wrong = [{"table": k, **w} for k, v in tables.items() for w in v["wrong"]]
    if wrong:
        details += [{"case": f"table:{w['table']}:{w['what']}", "pass": False, "gold": w["gold"], "data": w["data"]} for w in wrong]
    notes = ["tables, combinations and selection on the data and the reasoning (no corpus needed); the gold is the review's "
             "own tables and examples, written out by hand",
             "wuxing: Five-Phase states against the relations, strategies, classical statements, opposite intentions, guards "
             "and method points the reasoning must give; the Saam table as its tradition prints it (a school's templates)"]
    big = None if ctx.quick else ctx.corpus_harness()
    if big is not None:
        bst = big.capabilities.get("study")._acupuncture
        stated = agree_phase = agree_kind = with_kind = 0
        differ = []
        for code in [c for codes in gold["five_shu"].values() for c in codes]:
            entries = bst._point_passages(code)["entries"]
            checks = {c["attribute"]: c for c in bst._checks(code, entries)}
            if "phase" in checks:
                stated += 1
                agree_phase += checks["phase"]["agree"] > 0
                differ += [{"point": code, "attribute": "phase", "stated": x["stated"], "passage_id": x["witness"]["passage_id"],
                            "locator": x["witness"]["locator"]} for x in checks["phase"]["differ"]]
            if "kind" in checks:
                with_kind += 1
                agree_kind += checks["kind"]["agree"] > 0
                differ += [{"point": code, "attribute": "kind", "stated": x["stated"], "passage_id": x["witness"]["passage_id"],
                            "locator": x["witness"]["locator"]} for x in checks["kind"]["differ"]]
        metrics["real"] = {"five_shu_with_phase_stated": f"{stated}/60", "phase_agreeing": f"{agree_phase}/{stated}",
                           "five_shu_with_kind_stated": f"{with_kind}/60", "kind_agreeing": f"{agree_kind}/{with_kind}",
                           "differing_witnesses": len(differ)}
        details += [{"case": f"real:{x['point']}:{x['attribute']}", "pass": None, **x} for x in differ[:60]]
        notes.append("real: a point agrees when at least one entry states its phase (kind) as the data does; every differing "
                     "witness is listed — a variant reading, an error of the data or a misreading, for a person to decide")
    return SuiteResult("acupuncture", metrics, details, notes=notes)


__all__ = ["acupuncture"]
