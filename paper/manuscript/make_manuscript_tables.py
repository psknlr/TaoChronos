"""Tables 1–2 of the manuscript (paper/manuscript/manuscript.md) as editable text: Markdown, LaTeX (booktabs), CSV
and Word.

    python paper/manuscript/make_manuscript_tables.py

Table 1 is new: the ways an agent can go wrong on the classics, the mechanism that stops each in TaoChronos and the
measured evidence that it does.  Table 2 is Extended Data Table 2 of the display-item package (paper/tables), promoted
to the main text, with its numbers read from the same sources (`taochronos eval` on the demonstration corpus, and
docs/evals.md for the suites that need the full corpus store, marked †).  The writers are those of
paper/tables/make_tables.py, so both packages share one three-line style.
"""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

HOME = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "tables"
SD = HOME / "paper" / "figures" / "source_data"

_spec = importlib.util.spec_from_file_location("ed_tables", HOME / "paper" / "tables" / "make_tables.py")
ed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ed)


def table1() -> dict:
    r = json.load(open(SD / "eval_demo_corpus.json", encoding="utf-8"))
    m = lambda s: r[s]["metrics"]  # noqa: E731
    hal, inv, it, rec = m("hallucination"), m("invariants"), m("interpretive"), m("recovery")
    n = hal["samples"]
    rows = [
        ["Fabricated or altered quotation",
         "A quote with one character changed, or the right words at the wrong place",
         "The harness, not the producer, locates every quote in its passage at commit (verbatim, or after "
         "length-preserving variant normalization); the conversation client checks every cited passage",
         f"{3 * n}/{3 * n} corrupted quotations rejected, {n}/{n} verbatim accepted; "
         f"{m('provenance')['claims_verbatim']:.0%} of committed claims verbatim (Fig. 4a)"],
        ["True quote, false reading",
         "「不可发汗，宜桂枝汤」 (a prohibition beside a prescription); 「或曰…余曰非也」 (a view the author rejects)",
         "Semantic-support hook reads each claim's statement frame (speaker, stance, conditions, negations) and refuses "
         "a claim its quote contradicts; a registry of textual cruxes harvested from commentaries makes doubtful "
         "clauses read as ambiguous",
         f"Held-out hard cases {round(it['heldout']['accuracy'] * 84)}/84, {it['heldout']['unsafe']} unsafe; "
         "four blind rounds (Fig. 4c,d)"],
        ["Copies counted as independent testimony",
         "Five witnesses of one clause of the Jingui yaolüe and its copy in the Maijing",
         "Gate G5 counts independent source families (author and transcription clusters), not books; the Skeptic "
         "checks transcription dependence and single sources",
         "H5 held inconclusive on one family (Fig. 3e); an over-merging of families reported (Supplementary Fig. 1)"],
        ["Anachronism (presentism)",
         "Xiaoke 消渴 read as diabetes mellitus; shanghan 伤寒 read as typhoid",
         "Anachronism guard at claim, hypothesis and graph-write hooks; the contract's forbidden equivalences; the "
         "ancient–modern bridge states phenotypic similarity with typed relations, never a retrospective diagnosis",
         "Statements 10/10, mappings 8/8, translations 24/24; agent-asserted equivalence blocked"],
        ["Arguments from silence",
         "An association called lost after 960 that a later book still states",
         "The Skeptic searches the whole scope for explicit, supported statements; one later statement refutes a "
         "loss and any statement refutes a hidden link, as hard, critical objections no rewording can close",
         "2 wrong lost and 2 already-written hidden associations rejected, and no discovery (Fig. 5d); R1 rejected "
         "(Fig. 3)"],
        ["Self-grading and premature acceptance",
         "A model closing its own objection, setting expert approval, or a finished run taken as an accepted finding",
         "Every event carries its principal and the reducer refuses an event its principal may not emit (61 types); "
         "only validators grade, only a human sets G7; an executable contract judges acceptance",
         f"{inv['held']}/{inv['invariants']} invariants held; each of 6 boundaries removed broke its invariant and "
         "no other (Fig. 4b)"],
        ["Hindsight in testing foresight",
         "A 'prediction' made after reading the books that later confirm it",
         "Time-machine views bounded in SQL on every read path; passages that straddle the cutoff belong to neither "
         "side; leakage counted, not assumed",
         "Leakage 0; precision@10 0.168 against 0.134 (popularity) and 0.054 (chance)† (Fig. 5)"],
        ["Irreproducible runs",
         "A result that cannot be rerun or audited step by step",
         "Append-only event log replayed and hashed every round; tool-call receipts in a hash chain; recorded model "
         "responses replayed exactly",
         f"Resume after a crash at {round(rec['recovery_success_rate'] * rec['crash_points'])} of "
         f"{rec['crash_points']} points reaches the same state; reruns and parallel runs identical; the end-to-end "
         "report rewritten identically"],
    ]
    return {
        "title": "Table 1 | Eight ways an agent can go wrong on the classical literature, the mechanism that stops "
                 "each in TaoChronos, and the measured evidence that it does",
        "header": ["Failure mode", "Example in the classics", "Mechanism in TaoChronos", "Evidence in this study"],
        "rows": rows, "total": None,
        "notes": [
            "Every mechanism is deterministic code that runs whether a language model or a rule produced the output; "
            "all evidence was measured with the rules alone (no model called).",
            "†Needs the full corpus store, which is not distributed; values from docs/evals.md. Other values were "
            "reproduced by `taochronos eval` on the demonstration corpus.",
        ],
    }


def table2() -> dict:
    t = ed.table2()
    t["title"] = "Table 2 | Evaluation of TaoChronos across its three layers"
    return t


def to_csv(t: dict, path: Path) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(t["header"])
        w.writerows(t["rows"] + ([t["total"]] if t["total"] else []))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tables = [table1(), table2()]
    for i, t in enumerate(tables, start=1):
        (OUT / f"table{i}.md").write_text(ed.to_markdown(t), encoding="utf-8")
        (OUT / f"table{i}.tex").write_text(ed.to_latex(t), encoding="utf-8")
        to_csv(t, OUT / f"table{i}.csv")
    ed.to_docx(tables, OUT / "tables.docx")
    print("wrote", ", ".join(str(p.relative_to(HOME)) for p in sorted(OUT.iterdir())))


if __name__ == "__main__":
    main()
