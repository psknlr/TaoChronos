"""Supplementary Information of the TaoChronos (道乃久) paper: Supplementary Notes 1–4, Supplementary Tables 1–12,
Supplementary Fig. 1 and Supplementary Data 1–2, as Markdown and Word, with every table also as CSV.

    python paper/supplementary/make_supplementary.py

Everything is read from files the repository writes: ``docs/evals.md`` (the evaluation design and its results), the
harness as configured (``paper/figures/source_data/fig1_architecture.json``), the end-to-end run of Fig. 3
(``fig3_e2e_*``, from ``paper/figures/e2e_case.py``) and the research-value benchmark on the open corpus
(``extfig_research_value_canon.json``).
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path

HOME = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SD = HOME / "paper" / "figures" / "source_data"
TABLES = HERE / "tables"

# where the paper reports each suite (the rest are reported only in docs/evals.md and in Supplementary Table 1)
REPORTED = {"invariants": "Fig. 4b; ED Table 2", "interpretive": "Fig. 4c,d; ED Table 2",
            "research_value": "Fig. 5; ED Fig. 2; ED Table 2", "hallucination": "Fig. 4a; ED Table 2",
            "provenance": "ED Table 2", "claims": "ED Table 2", "temporal": "ED Table 2", "anachronism": "ED Table 2",
            "ablations": "ED Fig. 1c", "collation": "ED Table 2", "reuse": "ED Table 2", "stratigraphy": "ED Table 2",
            "fragments": "ED Fig. 1a; ED Table 2", "punctuation": "ED Fig. 1b; ED Table 2", "pairs": "Fig. 6d; ED Table 2",
            "names": "Fig. 6a,b", "entities": "ED Fig. 1a; ED Table 2", "bridge": "ED Fig. 1a; ED Table 2",
            "audit": "ED Table 2"}
# the data of the suites docs/evals.md describes only in prose, and the questions of the V2 suites
DATA = {"invariants": "19 probes (the audit's counterexamples P01–P10 and nine boundaries added with them) run against "
                      "the harness under test; six boundaries removed in turn (mutation)",
        "interpretive": "107 verbatim cases in 8 classes (gold/interpretive.yaml); 23 development, 84 held-out, split "
                        "fixed before the first run; 4 blind rounds",
        "research_value": "full corpus split at 1127 and 1368: 230 topic–cutoff pairs read, 189 with a link that came "
                          "true, 29,467 candidates; the pipeline run on the past view at 1368 for 2 development and 4 "
                          "held-out topics; replicated on the open corpus (Extended Data Fig. 2)",
        "philology": "7 contested readings (gold/philology.yaml)", "claims": "42 gold hyperedges (gold/claims.yaml), "
        "development", "provenance": "every claim and evidence record a demonstration run commits",
        "hallucination": "60 random passages × 4 probes: verbatim, one character replaced, random characters, shifted span",
        "contradiction": "12 passage pairs (gold/contradictions.yaml)", "lineage": "typed links of the demonstration "
        "corpus (gold/lineage.yaml)", "temporal": "6 period constraints, 6 earliest attestations (gold/temporal.yaml)",
        "anachronism": "10 statements, 8 mappings, agent-asserted equivalences (gold/anachronism.yaml)",
        "recovery": "crashes at 4 points of a run; reruns; parallel against sequential runs",
        "time_machine": "the demonstration corpus split at 1368 (a separate harness indexes the past only)",
        "source_rediscovery": "3 cited books held out (gold/rediscovery.yaml)",
        "ablations": "demonstration corpus: 6 terms, 12 passage pairs, the agents' context, runs without the Skeptic"}
QUESTION = {"entities": ("Are the entities of a sentence found and typed (24 types)?", "precision · recall · F1"),
            "places": ("Are physicians placed from their signatures, prefaces and biographies?", "precision · recall"),
            "translation": ("Does a translation keep the original layer and add no present-day diagnosis?",
                            "guard accuracy · layer preserved"),
            "layout": ("Are page images read in order, with notes, margins and OCR errors located?",
                       "reading-order accuracy · CER · notes F1"),
            "bridge": ("Are the findings of a passage projected into HPO with typed relations?", "precision · recall · F1"),
            "audit": ("Does each statement of an answer get the verdict its evidence supports?",
                      "verdict accuracy · false SUPPORTED"),
            "modern": ("Are modern records typed by design and population, and cross-level claims refused?",
                       "typing accuracy · guard accuracy"),
            "workflow": ("Does the orchestrator plan the skills a question needs and no others?",
                         "valid plans · rerun from the workspace")}
RESULT = {"research_value": "precision@10 0.168 (popularity 0.134; chance 0.054); average precision above popularity "
                            "in 149 of 189 pairs (P = 2.4 × 10⁻¹⁶); held-out predictions: discoveries 7/19; open "
                            "corpus: above popularity 24/6 (P = 0.0014), not separable from chance 13/17 (P = 0.58)"}
LAYER = {"invariants": "Boundaries", "interpretive": "Readings", "research_value": "Research value",
         "time_machine": "Research value", "source_rediscovery": "Research value"}
GATE_ROWS = [
    ("G0", "Source", "claim, evidence", "the book is in the store with an origin and a licence (score 0.8 when the "
     "transcription is unverified)", "—", "unknown book, or no origin or licence", "validator"),
    ("G1", "Transcription", "claim, evidence", "a verified manual transcription, or OCR confidence ≥ 0.9",
     "an unverified transcription, or OCR confidence 0.7–0.9", "OCR confidence < 0.7", "validator"),
    ("G2", "Philology", "claim, evidence", "text collated against an edition, and the span not on a contested reading",
     "uncollated text, or a contested reading whose base reading has p ≥ 0.4", "the span rests on a contested reading "
     "with p < 0.4", "validator"),
    ("G3", "Sense", "claim; hypothesis", "every term resolved to one sense for its period", "a homonym whose most likely "
     "sense has p < 0.6", "—", "validator"),
    ("G4", "Claim provenance", "claim, evidence; hypothesis", "the quote is verbatim at its span and states the "
     "relation", "verbatim, but the quote does not clearly state the relation, or states a view the author rejects",
     "the quote is not verbatim or not where it is said to be, or it contradicts the claim", "validator"),
    ("G5", "Independent sources", "hypothesis", "supporting evidence from ≥ 2 independent source families (the "
     "contract may ask for more)", "one family", "no supporting evidence", "validator"),
    ("G6", "Falsification", "hypothesis", "the latest Skeptic review leaves no open critical or major objection",
     "an open major objection", "an open critical objection (pending before any review)", "validator"),
    ("G7", "Expert", "hypothesis", "a named expert approves", "—", "a named expert rejects (pending until then)",
     "human only"),
    ("G8", "Modern evidence", "hypothesis (biomedical or bridge claims)", "records in people support a biomedical "
     "claim; any modern record contextualizes a typed bridge", "—", "no modern record, or a record contradicts the "
     "claim; not applicable to historical hypotheses", "validator"),
]
HOOK_ROWS = [
    ("BeforeToolCall", "scope_guard", "every tool call", "arguments that name material outside the research's scope "
     "(withheld books, the future of a blind cutoff)"),
    ("AfterToolCall", "scope_firewall", "every tool result", "a result that carries withheld material back to the caller"),
    ("BeforeClaimCommit", "provenance_validator", "every claim", "a quote that is not verbatim, empty or outside its "
     "passage; inconsistent argument spans"),
    ("BeforeClaimCommit", "semantic_support", "every claim", "a claim its quote contradicts (a true quote with a false "
     "relation); frames the rest with speaker, stance, conditions and negations"),
    ("BeforeClaimCommit", "anachronism_guard", "every claim", "a classical claim that carries a modern concept"),
    ("AfterHypothesis", "anachronism_guard", "every hypothesis and revision", "a statement that equates a historical "
     "concept with a modern category, or breaks a forbidden assumption of the contract"),
    ("BeforeGraphWrite", "anachronism_guard", "every mapping into the knowledge graph", "a historical-to-modern "
     "equivalence asserted by anyone but a human expert"),
    ("BeforeArtifactPublish", "publish_guard", "every report that is not a draft", "a report without evidence, one that "
     "cites missing or retracted objects, or one that presents a hypothesis not judged on its current version"),
]
PERM = {"classics:read": "read the corpus through the research's scoped view", "kg:read": "read the knowledge graph",
        "kg:propose": "propose a change to canonical knowledge", "analysis:run": "run the discovery and statistics engines",
        "literature:read": "read modern literature and real-world data", "codemode:exec": "run code in the sandbox",
        "validation:run": "run the gates (validators)"}


# ------------------------------------------------------------------------------------------------------------ helpers
def md_table(header: list[str], rows: list[list], widths: list[int] | None = None) -> str:
    def cell(v: object) -> str:
        return str(v).replace("|", "\\|").replace("\n", " ")
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(cell(v) for v in r) + " |" for r in rows]
    return "\n".join(out)


def write_csv(name: str, header: list[str], rows: list[list]) -> None:
    TABLES.mkdir(parents=True, exist_ok=True)
    with open(TABLES / name, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def md_tables_of(path: Path) -> list[tuple[list[str], list[list[str]]]]:
    """The pipe tables of a Markdown file, as (header, rows)."""
    out, cur = [], None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("|"):
            cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip())[1:-1]]
            if cur is None:
                cur = (cells, [])
            elif not all(re.fullmatch(r":?-+:?", c) for c in cells):
                cur[1].append(cells)
        elif cur is not None:
            out.append(cur)
            cur = None
    if cur:
        out.append(cur)
    return out


def plain(s: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"\1", s).replace("`", "")


# ------------------------------------------------------------------------------------------------------------- tables
def table_evaluation() -> tuple[list[str], list[list]]:
    tabs = md_tables_of(HOME / "docs" / "evals.md")
    question = {plain(r[0]): (r[1], r[2]) for h, rows in tabs if h[:2] == ["Suite", "Question"] for r in rows}
    result = {}
    data = {}
    for h, rows in tabs:
        if h == ["Suite", "Result"]:
            for r in rows:
                result[plain(r[0]).split(" ")[0]] = r[1]
        if h[:3] == ["Suite", "Data", "Result"]:
            for r in rows:
                key = plain(r[0]).split(" ")[0]
                data[key], result[key] = r[1], r[2]
    evals = json.loads((SD / "eval_demo_corpus.json").read_text(encoding="utf-8"))
    header = ["Layer", "Suite", "Question", "Data and split", "Metrics", "Result", "Reported in"]
    rows = []
    for suite in evals:
        q, m = question.get(suite) or QUESTION.get(suite, ("", ""))
        layer = LAYER.get(suite) or ("Deep discovery" if suite in ("collation", "reuse", "stratigraphy", "cases",
                                                                     "argument", "senses", "fragments")
                                      else "Task specification" if suite in ("punctuation", "commentaries", "disputes",
                                                                             "variant_impact", "clause", "glosses",
                                                                             "pairs", "schools", "names", "chain")
                                      else "V2" if suite in ("entities", "places", "translation", "layout", "bridge",
                                                             "audit", "modern", "workflow")
                                      else "Verification")
        rows.append([layer, suite, plain(q), plain(data.get(suite) or DATA.get(suite, "")), plain(m),
                     plain(RESULT.get(suite) or result.get(suite, "")), REPORTED.get(suite, "—")])
    return header, rows


def architecture() -> dict:
    return json.loads((SD / "fig1_architecture.json").read_text(encoding="utf-8"))


def table_agents(arch: dict) -> tuple[list[str], list[list]]:
    header = ["Agent", "Name", "Role", "Mode", "Model tier (minimum)", "Permissions", "Tools", "Output",
              "Budget (tool calls · model calls)"]
    rows = []
    for a in arch["agents"]:
        b = a.get("budget") or {}
        rows.append([a["role"], a["name"], a["description"], a["mode"], (a.get("model") or {}).get("min_tier", ""),
                     ", ".join(a["permissions"]), ", ".join(a["tools"]), a["output_schema"],
                     f"{b.get('max_tool_calls', '–')} · {b.get('max_llm_calls', 0 if a['mode'] == 'procedure' else '–')}"])
    return header, rows


def table_tools(arch: dict) -> tuple[list[str], list[list]]:
    fam: dict[tuple[str, str], list[str]] = {}
    for t in arch["tools"]:
        fam.setdefault((t["family"], t["permission"]), []).append(t["name"] + ("" if t["read_only"] else " (writes)"))
    header = ["Family", "Permission needed", "What the permission allows", "Tools", "Names"]
    rows = [[f, p, PERM.get(p, ""), len(names), ", ".join(sorted(names))] for (f, p), names in sorted(fam.items())]
    return header, rows


def table_authority(arch: dict) -> tuple[list[str], list[list]]:
    header = ["Event", "Agent", "Validator", "Human", "Kernel", "Why"]
    rows = []
    for e, ps in arch["authority"].items():
        rows.append([e] + ["●" if p in ps else "" for p in ("agent", "validator", "human", "kernel")]
                    + [arch["why"].get(e, "")])
    return header, rows


def table_core(arch: dict) -> tuple[list[str], list[list]]:
    skills = {s["id"]: s["name"] for s in arch["skills"]}
    header = ["Core agent", "Skills", "Specialists it delegates to", "Permissions", "Rules"]
    rows = []
    for c in arch["core_agents"]:
        rows.append([c["name"], "; ".join(f"{s} {skills.get(s, s)}" for s in c.get("skills", [])),
                     ", ".join(c.get("delegates", [])), ", ".join(c.get("permissions", [])),
                     " / ".join(c.get("rules", []))])
    return header, rows


def table_criteria() -> tuple[list[str], list[list]]:
    detail = json.loads((SD / "fig3_e2e_detail.json").read_text(encoding="utf-8"))
    header = ["Criterion", "Requirement", "Judge", "State when unmet", "H1 in Fig. 3 (observed)"]
    rows = [[c["id"], c["required"], c["judge"], c["failure_state"], f"{c['status']}: {c['observed']}"]
            for c in detail["needs_expert"]["criteria"]]
    rows.append(["falsification", "not rejected", "validator:contract", "rejected",
                 "R1 in Fig. 3: " + detail["rejected"]["criteria"][0]["observed"]])
    return header, rows


def table_hypotheses() -> tuple[list[str], list[list]]:
    report = json.loads((SD / "fig3_e2e_report.json").read_text(encoding="utf-8"))
    pred = {h["id"]: h.get("testable_prediction", "") for h in report["hypotheses"] + report["rejected"]}
    with open(SD / "fig3_e2e_hypotheses.csv", encoding="utf-8") as f:
        rows_ = list(csv.DictReader(f))
    header = ["Label", "Id", "Kind", "Generation", "Parent", "Status", "Verdict", "Gates G0–G8", "Criteria unmet",
              "Objections (closed)", "Statement", "Testable prediction"]
    rows = []
    for r in rows_:
        gates = " ".join(f"{g}:{r['gate_' + g] or '·'}" for g in ("G0", "G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8"))
        unmet = [k.removeprefix("crit_") for k, v in r.items() if k.startswith("crit_") and v and v != "pass"]
        rows.append([r["label"] or "(superseded)", r["id"], r["kind"], r["generation"], r["parent_id"], r["status"],
                     r["verdict"], gates, ", ".join(unmet), f"{r['objections']} ({r['objections_closed']})",
                     r["statement"], pred.get(r["id"], "")])
    return header, rows


def table_objections() -> tuple[list[str], list[list], list[str], list[list]]:
    with open(SD / "fig3_e2e_objections.csv", encoding="utf-8") as f:
        obj = list(csv.DictReader(f))
    full_header = ["Hypothesis", "Label", "Reviewer task", "Review verdict", "Check", "Severity", "Kind", "Status",
                   "Closed by", "Closure", "Detail"]
    full = [[o["hypothesis"], o["label"], o["reviewer"].split("@")[-1], o["verdict"], o["check"], o["severity"], o["kind"],
             o["status"], o["closed_by"], o["closure"], o["detail"]] for o in obj]
    by = Counter((o["check"], o["status"], o["severity"]) for o in obj)
    checks = sorted({o["check"] for o in obj}, key=lambda c: -sum(v for k, v in by.items() if k[0] == c))
    head = ["Check", "Raised", "Closed after narrowing", "Open: major", "Open: minor", "Open: critical"]
    summary = [[c, sum(v for k, v in by.items() if k[0] == c), sum(v for k, v in by.items() if k[0] == c and k[1] == "closed"),
                by.get((c, "raised", "major"), 0), by.get((c, "raised", "minor"), 0), by.get((c, "raised", "critical"), 0)]
               for c in checks]
    return head, summary, full_header, full


def benchmark() -> dict:
    return json.loads((SD / "extfig_research_value_canon.json").read_text(encoding="utf-8"))["research_value"]


def table_predictions(rv: dict) -> tuple[list[str], list[list]]:
    header = ["Topic", "Split", "Hypothesis", "Kind", "Review status", "Prediction", "Subject", "Object", "Held (strict)",
              "Held (loose)", "Later books", "Note"]
    rows = []
    for d in rv["details"]:
        if d["part"] != "end_to_end":
            continue
        held = {True: "yes", False: "no", None: "not judged"}
        note = d.get("why", "")
        if d.get("written_before"):
            note = (note + "; " if note else "") + "already written before the cutoff"
        rows.append([d["topic"], d["split"], d["hypothesis"], d["kind"], d["status"], d["prediction"], d.get("subject"),
                     d.get("object") or "", held[d.get("held")], held[d.get("held_loose")], d.get("future_books", ""),
                     note])
    return header, rows


def table_links(rv: dict) -> tuple[list[str], list[list]]:
    header = ["Cutoff", "Topic", "Past passages", "Future passages", "Candidates", "Came true", "AP Adamic–Adar",
              "AP popularity", "AP chance", "First true link (Adamic–Adar rank)", "True links in Adamic–Adar's top 20"]
    rows = []
    for d in rv["details"]:
        if d["part"] != "link_anticipation" or d.get("skipped") or not d.get("came_true"):
            continue
        ex = "; ".join(f"{e['remedy']} (rank {e['rank']}, {e['future_books']} later books)" for e in d.get("examples", []))
        rows.append([d["cutoff"], d["topic"], d["past_passages"], d["future_passages"], d["candidates"], d["came_true"],
                     d["adamic_adar"]["ap"], d["popularity"]["ap"], d["random"]["ap"],
                     d["adamic_adar"].get("first_hit", ""), ex])
    return header, rows


# -------------------------------------------------------------------------------------------------------------- notes
def notes(arch: dict, rv: dict) -> dict[str, str]:
    contract = json.loads((SD / "fig3_e2e_contract.json").read_text(encoding="utf-8"))
    metrics = json.loads((SD / "fig3_e2e_metrics.json").read_text(encoding="utf-8"))
    comp = json.loads((SD / "fig3_e2e_family_components.json").read_text(encoding="utf-8"))
    e2e = rv["metrics"]["end_to_end"]
    pooled = rv["metrics"]["link_anticipation"]["pooled"]
    n_pred = sum(1 for d in rv["details"] if d["part"] == "end_to_end")
    saturation = float(re.search(r"\(([\d.]+) <", metrics["stop"]["reasons"][0]).group(1))
    judged = [d for d in rv["details"] if d["part"] == "end_to_end" and d.get("held") is not None]
    return {
        "eval": (
            "TaoChronos-Eval has forty suites in three layers. The first tests the harness's boundaries: nineteen "
            "invariants run as probes against the harness under test, each checked by mutation (the boundary removed, "
            "the invariant broken, the boundary restored; Fig. 4b measures all nineteen on every variant). The second "
            "tests readings: 107 verbatim quotations that can still be read wrongly, in eight classes, with unsafe "
            "errors (those that would let a false claim through) counted apart. The split into 23 development and 84 "
            "held-out cases was fixed before the suite first ran, and four blind rounds were each written before the "
            "rules that first read them (Fig. 4d). The third tests research value: a blind temporal benchmark in which "
            "the store is split at a cutoff year, passages that may have been written on either side belong to neither "
            "side, the rules were written before the first run (evals/gold/research_value.yaml) and every read path is "
            "bounded in SQL, so that leakage is counted rather than assumed; graph rankings are compared with "
            "popularity, chance and two other link predictors, and the pipeline's own predictions are judged by later "
            "books.\n\n"
            "The other suites measure each capability in the way its task allows: constructed data where an answer can "
            "be constructed (planted drug pairs, artificial manuscript traditions, a lost work quoted by four books), a "
            "development set where rules need examples, and results the literature already holds where the real corpus "
            "can be checked (the taboo renamings of Fig. 6, the Yunqi chapters of the Suwen, the first gloss of 几几). "
            "Development and constructed sets were written with the rules they test; they are regression tests of "
            "intended behaviour, and only held-out or real-corpus results estimate generalization (Extended Data Fig. 1). "
            "The two held-out sets of the V2 layer (entities, ancient phenotypes) were annotated before the rules ran on "
            "them. Everything but the full-corpus suites reruns on the demonstration corpus in under a minute "
            "(`taochronos eval`); the full-corpus values, which need a store that is not distributed, are transcribed "
            "from docs/evals.md and marked. Supplementary Table 1 lists every suite."),
        "gates": (
            "Five mechanisms bound what any part of the harness can do, and they are layered so that the failure of one "
            "is caught by another (Fig. 4b). (1) Permissions: every tool needs one permission, and an agent holds only "
            "those its specification lists (Supplementary Tables 4 and 5); an agent that asks for a tool outside them is "
            "refused and the refusal is logged. (2) Hooks: deterministic guards at eight points of the lifecycle "
            "(Supplementary Table 6) refuse a tool call or result outside the research's scope, a claim whose quote is "
            "not verbatim or contradicts it, an anachronistic equation and a report on unjudged versions. (3) Event "
            "authority: every change to the research object is an event, and the reducer refuses an event its principal "
            f"may not emit; {len(arch['authority'])} event types, nine patterns of permission (Fig. 1b, Supplementary "
            "Table 7). An agent proposes; only validators grade, and only a human sets G7. (4) Gates G0–G8 grade each "
            "claim, evidence record and hypothesis on its current version (Supplementary Table 2). (5) The research "
            "contract, hashed before the first task, fixes the criteria by which a hypothesis is accepted, needs an "
            "expert, stays inconclusive or is rejected, and names the judge of each (Supplementary Table 3): finishing "
            "the tasks never accepts a research. In conversation, four core agents run the same specialists as fifteen "
            "skills (Supplementary Table 8)."),
        "case": (
            f"The question {contract['question']} was put to the harness on the open canon corpus with "
            "`taochronos research \"肾气丸的组成与主治如何随时代演变？\" --profile web-canon --focus 肾气丸,六味地黄丸 --forbid "
            "消渴=糖尿病`, offline: the rules ran alone and no model was called. The run scoped "
            f"{contract['books_in_scope']} books and "
            f"{contract['passages_in_scope']:,} passages, planned 30 tasks in three rounds, called {metrics['tool_calls']} "
            f"tools (none refused), extracted {metrics['claims']} claims, recorded {metrics['evidence_count']} evidence and "
            f"{metrics['counter_evidence']} counter-evidence records and {metrics['hypotheses']} hypotheses, and stopped "
            f"after round {metrics['round']}, the last the contract allowed, when new evidence had fallen to "
            f"{saturation:.1%}, below the 5% of its stop rule. It is deterministic: a second run "
            "writes the same report. The contract's verdict: one hypothesis (H1) meets every criterion a machine can "
            "check and waits for an expert, twelve are inconclusive and one (R1) is rejected. Supplementary Data 1 is "
            "the whole Discovery Report the run wrote, in Chinese, as a user of the harness receives it; Supplementary "
            "Data 2 is its event log, from which the state replays; Supplementary Tables 9 and 10 list every hypothesis "
            "and objection. "
            f"Reading each surviving hypothesis against its evidence found five failure modes (Supplementary Fig. 1), "
            f"the largest being that the independence check merged {comp['rules']['harness']['largest_among_evidence_books']} "
            f"of the {comp['evidence_books']} books that supplied evidence into one source family."),
        "predictions": (
            "Two lists record what the harness predicted before it could see the outcome, on the open canon corpus. "
            f"Supplementary Table 11 lists the {n_pred} predictions of the whole pipeline run on the past view at "
            f"{e2e['cutoff']} for two development topics (消渴, 中风) and four held-out topics (胸痹, 霍乱, 虚劳, 痰饮), each "
            f"with its outcome in the later books ({len(judged)} could be judged by the benchmark; formula evolutions, "
            "contradictions and lost books are not). No passage outside the past view was read (leakage "
            f"{e2e['leakage']}). Supplementary Table 12 lists, for each of the {pooled['topics_with_links_come_true']} "
            f"topic–cutoff pairs in which a link came true ({pooled['came_true']} links among {pooled['candidates']:,} "
            "candidates), the average precision of three rankers and the true links Adamic–Adar placed in its top 20. "
            "The full-corpus runs of Fig. 5 (189 pairs, 1,314 links) need the store that is not distributed; their "
            "aggregates are in docs/evals.md."),
    }


FIG_LEGEND = (
    "**Supplementary Fig. 1 | Where the end-to-end run of Fig. 3 went wrong, and why.** **a**, Books merged into one "
    "source family under three rules: the harness's (the same work or author, or any transcription or rephrasing link "
    "between their passages, closed transitively), transcription links only, and the same work or author only. Under "
    "the harness's rule 35 of the 38 books that supplied evidence, and 182 of the 368 books of the open corpus, fall "
    "into one family. **b**, The independent families each final hypothesis rests on under the three rules; dashed "
    "line, the two that G5 requires. Five hypotheses that G5 failed (H4, H5, H9, H12, H13) rest on two to four "
    "families once rephrasing links are left out. **c**, The failure modes found by reading every surviving hypothesis "
    "against its evidence, with what each did and the check that would catch it. None is repaired here: the run is "
    "reported as it happened.")


# ---------------------------------------------------------------------------------------------------------------- docx
def to_docx(blocks: list[tuple[str, object]], path: Path) -> None:
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Mm, Pt

    doc = Document()
    sec = doc.sections[0]
    sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = Mm(297), Mm(210)
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(sec, side, Mm(14))
    st = doc.styles["Normal"]
    st.font.name, st.font.size = "Arial", Pt(9)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "SimSun")

    def runs(par, text: str, size: float | None = None) -> None:
        for k, part in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
            if part:
                r = par.add_run(part.replace("`", ""))
                r.bold = bool(k % 2)
                if size:
                    r.font.size = Pt(size)

    def border(cell, **edges):
        tcPr = cell._tc.get_or_add_tcPr()
        b = OxmlElement("w:tcBorders")
        for edge, on in edges.items():
            el = OxmlElement(f"w:{edge}")
            el.set(qn("w:val"), "single" if on else "nil")
            if on:
                el.set(qn("w:sz"), "6")
            b.append(el)
        tcPr.append(b)

    for kind, content in blocks:
        if kind == "h1":
            doc.add_heading(str(content), level=1)
        elif kind == "h2":
            doc.add_heading(str(content), level=2)
        elif kind == "p":
            for para in str(content).split("\n\n"):
                runs(doc.add_paragraph(), para)
        elif kind == "img":
            doc.add_picture(str(content), width=Mm(183))
        elif kind == "table":
            title, header, rows, limit = content  # type: ignore[misc]
            runs(doc.add_paragraph(), f"**{title}**")
            shown = rows[:limit] if limit else rows
            tab = doc.add_table(rows=1 + len(shown), cols=len(header))
            for j, h in enumerate(header):
                tab.rows[0].cells[j].text = ""
                tab.rows[0].cells[j].paragraphs[0].add_run(str(h)).bold = True
            for i, r in enumerate(shown, start=1):
                for j, v in enumerate(r):
                    tab.rows[i].cells[j].text = str(v)
            for i, row in enumerate(tab.rows):
                for c in row.cells:
                    border(c, left=False, right=False, insideV=False, insideH=False, top=(i == 0),
                           bottom=(i in (0, len(shown))))
                    for par in c.paragraphs:
                        par.paragraph_format.space_after = Pt(0)
                        for r_ in par.runs:
                            r_.font.size = Pt(7)
            if limit and len(rows) > limit:
                runs(doc.add_paragraph(), f"The first {limit} of {len(rows)} rows; all are in the CSV file.", 7.5)
    doc.save(path)


# ---------------------------------------------------------------------------------------------------------------- main
def main() -> None:
    arch, rv = architecture(), benchmark()
    note = notes(arch, rv)
    t1 = table_evaluation()
    t2 = (["Gate", "Name", "Subject", "Pass", "Warn", "Fail", "Set by"], [list(r) for r in GATE_ROWS])
    t3 = table_criteria()
    t4, t5 = table_agents(arch), table_tools(arch)
    t6 = (["Hook point", "Guard", "Runs on", "Refuses"], [list(r) for r in HOOK_ROWS])
    t7, t8 = table_authority(arch), table_core(arch)
    t9 = table_hypotheses()
    oh, osum, ofh, ofull = table_objections()
    t11, t12 = table_predictions(rv), table_links(rv)
    tables = [
        ("S1_evaluation_design.csv", "Supplementary Table 1 | The forty evaluation suites: question, data and split, "
                                     "metrics, result and where the paper reports them", t1, 0),
        ("S2_gates.csv", "Supplementary Table 2 | Gates G0–G8: what each passes, warns and fails, and who sets it", t2, 0),
        ("S3_contract_criteria.csv", "Supplementary Table 3 | The criteria of the research contract, each with its judge "
                                     "and the state it leaves when unmet", t3, 0),
        ("S4_agents.csv", "Supplementary Table 4 | The sixteen agents of a research: role, mode, minimum model tier, "
                          "permissions, tools, output and budget", t4, 0),
        ("S5_tools.csv", "Supplementary Table 5 | The tool mesh: families, the permission each needs and the tools", t5, 0),
        ("S6_hooks.csv", "Supplementary Table 6 | The hooks the harness runs and what each refuses", t6, 0),
        ("S7_event_authority.csv", "Supplementary Table 7 | Event authority: the principals allowed to emit each event "
                                   "type (● allowed), with the reason where the table records one", t7, 0),
        ("S8_core_agents_skills.csv", "Supplementary Table 8 | In conversation: the four core agents, the skills S01–S15 "
                                      "they run and the specialists they delegate to", t8, 0),
        ("S9_e2e_hypotheses.csv", "Supplementary Table 9 | Every hypothesis of the end-to-end run (Fig. 3), with its "
                                  "gates, unmet criteria, objections and testable prediction", t9, 0),
        ("S10_e2e_objections.csv", "Supplementary Table 10 | The Skeptic's 117 objections in the end-to-end run, by "
                                   "check (each objection is in the CSV file)", (oh, osum), 0),
        ("S11_predictions_open_corpus.csv", "Supplementary Table 11 | The predictions of the pipeline run on the past "
                                            "view at 1368 on the open corpus, and their outcomes", t11, 0),
        ("S12_anticipated_links_open_corpus.csv", "Supplementary Table 12 | Topic–cutoff pairs of the open corpus in "
                                                  "which a link came true: average precision of three rankers and the "
                                                  "true links Adamic–Adar ranked in its top 20", t12, 0),
    ]
    for name, _, (h, rows), _ in tables:
        write_csv(name, h, rows)
    write_csv("S10_e2e_objections_all.csv", ofh, ofull)

    title = "TaoChronos (道乃久)"  # the paper's title is the authors' to set
    md = [f"# Supplementary Information\n\n**{title}**\n",
          "Contents: Supplementary Notes 1–4; Supplementary Tables 1–12 (each also as CSV in `tables/`); Supplementary "
          "Fig. 1; Supplementary Data 1 (the Discovery Report of the end-to-end run) and 2 (its event log).\n"]
    blocks: list[tuple[str, object]] = [("h1", "Supplementary Information"), ("p", f"**{title}**"),
                                        ("p", md[1].strip())]
    sections = [("Supplementary Note 1 | Evaluation design", note["eval"], [tables[0]]),
                ("Supplementary Note 2 | Gates, permissions and authority", note["gates"], tables[1:8]),
                ("Supplementary Note 3 | The end-to-end research case", note["case"], tables[8:10]),
                ("Supplementary Note 4 | Prediction lists", note["predictions"], tables[10:12])]
    for head, text, tabs in sections:
        md.append(f"## {head}\n\n{text}\n")
        blocks += [("h2", head), ("p", text)]
        for name, cap, (h, rows), limit in tabs:
            md.append(f"**{cap}** (`tables/{name}`)\n\n{md_table(h, rows)}\n")
            blocks.append(("table", (cap, h, rows, 40 if len(rows) > 60 else limit)))
    fig = HOME / "paper" / "figures" / "out" / "suppfig1_failures.png"
    md.append("## Supplementary Figure\n\n![Supplementary Fig. 1](../figures/out/suppfig1_failures.png)\n\n" + FIG_LEGEND + "\n")
    blocks += [("h2", "Supplementary Figure"), ("img", fig), ("p", FIG_LEGEND)]
    data = ("**Supplementary Data 1 | The Discovery Report of the end-to-end run** "
            "(`Supplementary_Data_1_e2e_discovery_report.md`): the report the harness wrote, in Chinese with English "
            "section titles, as the conversation client and the command line show it.\n\n"
            "**Supplementary Data 2 | The event log of the end-to-end run** (`Supplementary_Data_2_e2e_event_log.jsonl.gz`): "
            "every event in order, one JSON object a line, each with its sequence number, type, actor, principal and "
            "payload; replaying it rebuilds the state from which Fig. 3 and the report were drawn.")
    md.append("## Supplementary Data\n\n" + data + "\n")
    blocks += [("h2", "Supplementary Data"), ("p", data)]
    (HERE / "Supplementary_Information.md").write_text("\n".join(md), encoding="utf-8")
    to_docx(blocks, HERE / "Supplementary_Information.docx")
    print("wrote paper/supplementary/Supplementary_Information.{md,docx} and", len(list(TABLES.glob("*.csv"))),
          "tables in paper/supplementary/tables")


if __name__ == "__main__":
    main()
