"""The end-to-end research case of Fig. 3: one research question run by the whole harness on the open canon corpus.

    python paper/figures/e2e_case.py --canon-data D   # D holds the 要籍语料 store (corpus/tcm.sqlite); make_data.py passes it

The run is `taochronos research "肾气丸的组成与主治如何随时代演变？" --focus 肾气丸,六味地黄丸 --forbid 消渴=糖尿病` under the
web-canon profile, offline (rules only: no model is called), in a fresh data directory beside the store.  It is
deterministic: a second run writes the same report.  From its event log and state this script writes the contract, the
tasks each agent ran with their tool calls, the events each principal emitted, the knowledge gained per round, every
hypothesis with its gates G0–G8 and contract criteria, the Skeptic's objections, and the three hypotheses Fig. 3 shows in
full; the whole Discovery Report and the event log go to paper/supplementary (Supplementary Data 1 and 2).
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

HOME = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "source_data"
SUPP = HOME / "paper" / "supplementary"
QUESTION = "肾气丸的组成与主治如何随时代演变？"
ARGS = ["--profile", "web-canon", "--focus", "肾气丸,六味地黄丸", "--forbid", "消渴=糖尿病", "--session", "e2e-shenqiwan"]
GATES = ["G0", "G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8"]
CRITERIA = ["min_supporting_evidence", "semantic_support", "source_dependence", "falsification_review",
            "unresolved_hard_objections", "unresolved_critical", "alternatives_addressed", "current_version_gates",
            "expert_review"]


def write_csv(name: str, rows: list[dict], fields: list[str]) -> None:
    with open(OUT / name, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"  {name}: {len(rows)} rows")


def run(data: Path) -> None:
    env = dict(os.environ, TAOCHRONOS_DATA=str(data))
    subprocess.run([sys.executable, "-m", "taochronos", "research", QUESTION, *ARGS], check=True, env=env, cwd=HOME,
                   stdout=subprocess.DEVNULL)


def extract(data: Path) -> None:
    sys.path.insert(0, str(HOME / "src"))
    from taochronos.bootstrap import Harness
    from taochronos.engine.report import build

    h = Harness.from_profile("web-canon", home=HOME, data_dir=data)
    s = h.engine().open("e2e-shenqiwan")
    st, events = s.state, s.events()
    _, md, payload = build(h, st, s.id)
    SUPP.mkdir(parents=True, exist_ok=True)
    (SUPP / "S3_end_to_end_discovery_report.md").unlink(missing_ok=True)  # the name before the numbering of 2026-09-29
    (SUPP / "Supplementary_Data_1_e2e_discovery_report.md").write_text(md, encoding="utf-8")
    # the whole event log, replayable: every event with its principal, in order (gzip without a timestamp)
    with open(SUPP / "Supplementary_Data_2_e2e_event_log.jsonl.gz", "wb") as raw, \
            gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
        for ev in events:
            gz.write((json.dumps(ev.to_dict(), ensure_ascii=False, default=str) + "\n").encode("utf-8"))
    (OUT / "fig3_e2e_report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str),
                                              encoding="utf-8")

    # the contract and the corpus in scope
    goal = st.goal.to_dict()
    books = set(st.corpus.book_ids)
    report = payload["report"]
    scope = next(sec["body"] for sec in report["sections"] if sec["title"].startswith("2."))
    m = re.search(r"语料范围：(\d+) 部书、(\d+) 段文本；时期覆盖：(.+)", scope)
    per = {k.strip("，, "): v for k, v in re.findall(r"([^，\d\s]+) (\d+)", m.group(3))} if m else {}
    contract = {"question": goal["question"], "focus_terms": goal["focus_terms"], "tracks": goal["tracks"],
                "forbidden_assumptions": goal["forbidden_assumptions"], "required_validation": goal["required_validation"],
                "required_evidence": goal["required_evidence"], "stop": goal["stop"], "acceptance": goal["acceptance"],
                "goal_digest": st.goal_digest, "books_in_scope": int(m.group(1)) if m else len(books),
                "passages_in_scope": int(m.group(2)) if m else None,
                "passages_by_period": {k: int(v) for k, v in per.items()}, "profile": "web-canon",
                "llm_calls": st.metrics.get("llm_calls", 0) if isinstance(st.metrics, dict) else 0}
    (OUT / "fig3_e2e_contract.json").write_text(json.dumps(contract, ensure_ascii=False, indent=1, default=str),
                                                encoding="utf-8")
    print("  fig3_e2e_contract.json")

    # tasks, in the order they were planned, with the agent that ran each and its tool calls
    tasks: dict[str, dict] = {}
    order: list[str] = []
    agent_of: dict[str, str] = {}
    tools: dict[str, Counter] = defaultdict(Counter)
    rounds: dict[int, dict] = {}
    for ev in events:
        if ev.type == "RoundStarted":
            rounds.setdefault(ev.payload.get("round", len(rounds)), {})["start"] = ev.seq
        elif ev.type == "RoundCompleted":
            rounds.setdefault(ev.payload.get("round", len(rounds) - 1), {})["end"] = ev.seq
        if ev.type == "TaskStarted":
            tid = ev.payload.get("task_id") or ev.task_id
            if tid in tasks:
                tasks[tid]["start"] = ev.seq
        elif ev.type == "TaskPlanned":
            for t in ev.payload["tasks"]:
                if t["id"] not in tasks:
                    tasks[t["id"]] = {"task": t["id"], "kind": t["kind"], "role": t["role"], "round": t.get("round", 0)}
                    order.append(t["id"])
        elif ev.type == "AgentSpawned" and ev.payload["agent"].get("task_id"):
            agent_of[ev.payload["agent"]["task_id"]] = ev.payload["agent"]["id"]
        elif ev.type == "ToolCalled":
            tools[ev.actor][ev.payload["tool"]] += 1
        elif ev.type in ("TaskCompleted", "TaskFailed", "TaskSkipped"):
            tid = ev.payload.get("task_id") or ev.task_id
            if tid in tasks:
                tasks[tid]["status"] = ev.type.removeprefix("Task").lower()
                tasks[tid]["seq"] = ev.seq
    rows = []
    for i, tid in enumerate(order):
        t = tasks[tid]
        agent = agent_of.get(tid, "")
        calls = tools.get(agent, Counter())
        rows.append({**t, "order": i, "agent": agent or f"validator:{t['kind']}",
                     "principal": "agent" if agent else "validator", "tool_calls": sum(calls.values()),
                     "tools": "; ".join(f"{k}×{v}" for k, v in sorted(calls.items()))})
    write_csv("fig3_e2e_tasks.csv", rows, ["order", "round", "task", "kind", "role", "agent", "principal", "status",
                                           "start", "seq", "tool_calls", "tools"])

    # events by principal
    by = Counter((ev.type, ev.principal) for ev in events)
    write_csv("fig3_e2e_events.csv", [{"event": k[0], "principal": k[1], "count": v} for k, v in sorted(by.items())],
              ["event", "principal", "count"])

    # knowledge gained per round, and why the harness stopped
    from taochronos.kernel.observability import research_metrics

    rm = research_metrics(st)
    rm = json.loads(rm) if isinstance(rm, str) else rm
    gain = rm.get("knowledge_gain", {})
    write_csv("fig3_e2e_rounds.csv", [{"round": int(k), **v, **rounds.get(int(k), {})}
                                      for k, v in sorted(gain.items(), key=lambda kv: int(kv[0]))],
              ["round", "start", "end", "new_evidence", "new_sources", "new_hypotheses"])
    (OUT / "fig3_e2e_metrics.json").write_text(json.dumps({**rm, "stop": payload["stop"]}, ensure_ascii=False, indent=1,
                                                          default=str), encoding="utf-8")

    # every hypothesis: gates, contract criteria, objections, lineage
    judged = {j["hypothesis_id"]: j for j in payload["acceptance"]["hypotheses"]}
    label = {}
    for i, hp in enumerate(payload["hypotheses"], start=1):
        label[hp["id"]] = f"H{i}"
    for hp in payload["rejected"]:
        label[hp["id"]] = "R1"
    objections = defaultdict(list)
    for rev in st.reviews.values():
        for o in rev.objections:
            objections[rev.hypothesis_id].append(o)
    rows = []
    for hid, hp in st.hypotheses.items():
        g = st.gates.get(hid, {})
        j = judged.get(hid, {})
        crit = {c["id"]: c["status"] for c in j.get("criteria", [])}
        obs = objections.get(hid, [])
        rows.append({
            "label": label.get(hid, ""), "id": hid, "kind": hp.kind, "status": hp.status, "verdict": j.get("status", ""),
            "generation": hp.generation, "parent_id": hp.parent_id or "", "round": hp.round,
            "discovery_score": round(hp.discovery_score or 0, 4),
            "n_supporting": len(hp.supporting_evidence), "n_contradictory": len(hp.contradictory_evidence),
            **{f"gate_{k}": (g[k].status if k in g else ("pending" if k == "G7" else "")) for k in GATES},
            **{f"crit_{k}": crit.get(k, "") for k in CRITERIA},
            "objections": len(obs), "objections_closed": sum(1 for o in obs if o.status == "closed" or o.resolved),
            "objection_checks": "; ".join(sorted({o.check for o in obs})), "statement": hp.statement})
    rows.sort(key=lambda r: (r["label"] == "", r["label"][:1], int(r["label"][1:] or 0) if r["label"] else 0, r["id"]))
    write_csv("fig3_e2e_hypotheses.csv", rows, list(rows[0].keys()))
    obj_rows = []
    for rev in st.reviews.values():
        for o in rev.objections:
            obj_rows.append({"hypothesis": rev.hypothesis_id, "label": label.get(rev.hypothesis_id, ""),
                             "reviewer": rev.reviewer, "verdict": rev.verdict, "objection": o.id, "check": o.check,
                             "severity": o.severity, "kind": o.kind, "status": o.status, "closed_by": o.closed_by,
                             "closure": o.closure, "detail": o.detail})
    write_csv("fig3_e2e_objections.csv", obj_rows, list(obj_rows[0].keys()))
    rev_rows = []
    for rev in sorted(st.reviews.values(), key=lambda r: (r.round, r.reviewer, label.get(r.hypothesis_id, "~"))):
        sev = Counter(o.severity for o in rev.objections)
        rev_rows.append({"hypothesis": rev.hypothesis_id, "label": label.get(rev.hypothesis_id, ""),
                         "generation": st.hypotheses[rev.hypothesis_id].generation, "reviewer": rev.reviewer,
                         "round": rev.round, "verdict": rev.verdict, "objections": len(rev.objections),
                         "critical": sev.get("critical", 0), "major": sev.get("major", 0), "minor": sev.get("minor", 0)})
    write_csv("fig3_e2e_reviews.csv", rev_rows, list(rev_rows[0].keys()))

    # how many independent source families each hypothesis rests on under three rules for merging books: the harness's
    # (same work or author, or linked by any transcription or rephrasing edge, closed transitively), transcription only,
    # and same work or author only.  The first merges most of the corpus into one family (Supplementary Fig. S2).
    from taochronos.tools.adapters import author_clusters

    lin = list(st.lineage.values())
    rules = {"harness": author_clusters(h.corpus, lin),
             "transcription_only": author_clusters(h.corpus, [e for e in lin if e.relation == "transcribes"]),
             "work_author_only": author_clusters(h.corpus, [])}
    fam_rows = []
    for hid, hp in st.hypotheses.items():
        if hp.status == "superseded":
            continue
        bks = [st.evidence[e].book_id for e in hp.supporting_evidence if e in st.evidence]
        fam_rows.append({"label": label.get(hid, ""), "id": hid, "kind": hp.kind, "books": len(set(bks)),
                         **{k: len({f(b) for b in bks}) for k, f in rules.items()},
                         "G5": st.gates[hid]["G5"].status if "G5" in st.gates.get(hid, {}) else ""})
    fam_rows.sort(key=lambda r: (r["label"][:1], int(r["label"][1:] or 0)))
    write_csv("fig3_e2e_families.csv", fam_rows, list(fam_rows[0].keys()))
    ev_books = sorted({e.book_id for e in st.evidence.values()})
    comp = {k: Counter(f(b) for b in h.corpus.books) for k, f in rules.items()}
    comp_ev = {k: Counter(f(b) for b in ev_books) for k, f in rules.items()}
    (OUT / "fig3_e2e_family_components.json").write_text(json.dumps({
        "lineage_edges": dict(Counter(e.relation for e in lin)), "corpus_books": len(h.corpus.books),
        "evidence_books": len(ev_books),
        "rules": {k: {"families_in_corpus": len(comp[k]), "largest_in_corpus": comp[k].most_common(1)[0][1],
                      "families_among_evidence_books": len(comp_ev[k]),
                      "largest_among_evidence_books": comp_ev[k].most_common(1)[0][1]} for k in rules}},
        ensure_ascii=False, indent=1), encoding="utf-8")

    # the two hypotheses shown in full: the one that met the machine criteria, and the one falsification rejected
    def evidence(ids: list[str]) -> list[dict]:
        out = []
        for eid in ids:
            e = st.evidence[eid]
            bk = h.corpus.book(e.book_id)
            loc = e.locator
            year = e.temporal.year("composition") if e.temporal else None
            out.append({"id": eid, "passage_id": e.passage_id, "book_id": e.book_id, "title": bk.title if bk else "",
                        "dynasty": e.temporal.dynasty if e.temporal else "", "year": year, "quote": e.quote,
                        "span": [e.start, e.end],
                        "chapter": getattr(loc, "chapter", None), "section": getattr(loc, "section", None),
                        "stance": getattr(e.stance, "value", str(e.stance)), "source": bk.source.origin if bk and bk.source else "",
                        "license": bk.source.license if bk and bk.source else ""})
        return out

    top = next(hp for hp in payload["hypotheses"] if judged.get(hp["id"], {}).get("status") == "needs_expert")
    warrant = next((w for w in payload["warrants"] if w["hypothesis_id"] == top["id"]), {})
    rej = payload["rejected"][0]
    rej_review = [o for o in objections.get(rej["id"], [])]
    # the inconclusive hypothesis about the focus formula with the most witnesses: many copies, one source family
    inc = max((hp for hp in payload["hypotheses"] if judged.get(hp["id"], {}).get("status") == "inconclusive"
               and "肾气丸" in hp["statement"]), key=lambda hp: len(hp["supporting_evidence"]))
    parent = inc.get("parent_id")
    inc_obs = objections.get(parent, []) + objections.get(inc["id"], [])
    detail = {
        "needs_expert": {"label": label[top["id"]], "id": top["id"], "kind": top["kind"], "statement": top["statement"],
                         "statistics": top.get("statistics"), "confidence": top.get("confidence"),
                         "discovery_score": top.get("discovery_score"), "gates": {k: (st.gates[top["id"]][k].status if k in st.gates[top["id"]] else "pending") for k in GATES},
                         "criteria": judged[top["id"]]["criteria"], "competing": warrant.get("competing", []),
                         "testable_prediction": top.get("testable_prediction"),
                         "evidence": evidence(top["supporting_evidence"])},
        "inconclusive": {"label": label[inc["id"]], "id": inc["id"], "parent_id": parent, "kind": inc["kind"],
                         "statement": inc["statement"], "parent_statement": st.hypotheses[parent].statement if parent else "",
                         "revision_note": inc.get("revision_note"), "qualifiers": inc.get("qualifiers"),
                         "replication_sources": inc.get("replication_sources"), "statistics": inc.get("statistics"),
                         "gates": {k: (st.gates[inc["id"]][k].status if k in st.gates[inc["id"]] else "pending")
                                   for k in GATES},
                         "gate_details": {k: st.gates[inc["id"]][k].details for k in GATES if k in st.gates[inc["id"]]
                                          and st.gates[inc["id"]][k].details},
                         "criteria": judged[inc["id"]]["criteria"], "evidence": evidence(inc["supporting_evidence"]),
                         "objections": [{"hypothesis": "parent" if o in objections.get(parent, []) else "revision",
                                         "check": o.check, "severity": o.severity, "status": o.status,
                                         "closure": o.closure, "detail": o.detail} for o in inc_obs]},
        "rejected": {"label": "R1", "id": rej["id"], "kind": rej["kind"], "statement": rej["statement"],
                     "supporting": evidence(rej["supporting_evidence"]),
                     "counter": evidence(rej["contradictory_evidence"]),
                     "objections": [{"check": o.check, "severity": o.severity, "status": o.status, "detail": o.detail}
                                    for o in rej_review],
                     "criteria": judged.get(rej["id"], {}).get("criteria", [])},
    }
    (OUT / "fig3_e2e_detail.json").write_text(json.dumps(detail, ensure_ascii=False, indent=1, default=str),
                                              encoding="utf-8")
    print("  fig3_e2e_detail.json; paper/supplementary/Supplementary_Data_1 (report) and _2 (event log)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--canon-data", type=Path, required=True, help="a data directory holding corpus/tcm.sqlite")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp)
        (data / "corpus").symlink_to((a.canon_data / "corpus").resolve(), target_is_directory=True)
        run(data)
        extract(data)


if __name__ == "__main__":
    main()
