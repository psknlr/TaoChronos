"""Tables 1–2 of the TaoChronos (道乃久) paper as editable text: Markdown, LaTeX (booktabs) and Word (.docx).

    python paper/tables/make_tables.py

Three-line style: a rule above the header, one below it, one at the foot; no vertical rules, no shading; units in the
headers; footnotes keyed by symbols.  Numbers come from the corpus catalogs, from `taochronos eval` on the
demonstration corpus (paper/figures/source_data/eval_demo_corpus.json) and, for the suites that need the full corpus
store, from docs/evals.md (marked †).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import yaml

HOME = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
SD = HOME / "paper" / "figures" / "source_data"


def catalog_chars(src: str) -> int | None:
    d = yaml.safe_load(open(HOME / f"corpus/catalog/{src}.yaml", encoding="utf-8"))
    vals = [b.get("characters") for b in d["books"] if b.get("status") == "ingest"]
    return sum(v for v in vals if v) if vals and all(vals) else None


def table1() -> dict:
    wit = list(csv.DictReader(open(SD / "fig2_corpus_witnesses.csv", encoding="utf-8")))
    n = {}
    for r in wit:
        n[r["source"]] = n.get(r["source"], 0) + 1
    ch = {s: catalog_chars(s) for s in ("mcgill", "cmeta", "aeam", "wikisource", "tcm-ancient-books", "hf-tcm-canon")}
    fmt = lambda c: f"{c / 1e6:.2f}" if c else "–"  # noqa: E731
    rows = [
        ["Kanseki Repository KR3e, Siku quanshu medical section (漢籍リポジトリ)", "CC BY-SA 4.0", str(n["kanripo"]),
         "25.66*", "Wenyuange Siku and Sibu congkan facsimiles; unpunctuated; catalogue with authors, dates, layers"],
        ["JiCheng 笈成 edited texts, v1.4.8", "User-supplied; local research only†", str(n["jicheng"]), "93.64*",
         "Volunteer transcriptions with modern punctuation; 41 of 857 works excluded"],
        ["CMETA 數位中醫校書郎 collated editions", "CC BY 4.0 (collation); base texts public domain", str(n["cmeta"]),
         fmt(ch["cmeta"]), "Collated page by page against images; passages carry page numbers and image links"],
        ["Tōa Igaku Kyōkai 東亜医学協会 texts", "© the society; local research only†", str(n["aeam"]), fmt(ch["aeam"]),
         "Suwen, Lingshu, Nanjing, Shanghan lun, Jingui yaolüe, Shennong bencao jing, Bian Que biography"],
        ["Wikisource (Category 中醫, 醫書)", "CC BY-SA 4.0", str(n["wikisource"]), fmt(ch["wikisource"]),
         "Works new after de-duplication of 627 candidates"],
        ["McGill University Library rare books", "Public domain", str(n["mcgill"]), fmt(ch["mcgill"]),
         "Qing prints and manuscripts on gynaecology"],
        ["TCM-Ancient-Books; tcmoc", "Not declared; local research only†", str(n["tcm-ancient-books"]),
         fmt(ch["tcm-ancient-books"]), "Mostly simplified copies of JiCheng texts, de-duplicated work by work"],
        ["Hugging Face classical-tcm-canon", "Proprietary-commercial; local research only†", str(n["hf-tcm-canon"]),
         fmt(ch["hf-tcm-canon"]), "One work (Zhang Zhicong's commentary on the Shanghan lun)"],
        ["Kanseki Repository catalogue (KR-Catalog)", "CC BY-SA 4.0", "–", "–",
         "Roles and life dates of 132 persons responsible for the Siku works"],
        ["Image catalogues of 11 collections‡", "Recorded per collection", "–", "–",
         "10,001 records (787 linked to 179 works): title, date, print or manuscript, shelfmark, IIIF manifest"],
    ]
    total = ["Total", "", str(len(wit)), "≈123", "2.05 M passages; 761 distinct works; analysis periods 475 BCE–1949"]
    return {
        "title": "Table 1 | Sources of the corpus",
        "header": ["Source", "Licence", "Works admitted", "Characters (millions)", "Transcription and notes"],
        "rows": rows, "total": total,
        "notes": [
            "*Counted in the corpus store (README); the catalogues of these two sources do not record characters. Other "
            "counts sum the catalogue records of the admitted works.",
            "†Used for local research only and never redistributed; the open web corpus carries none of the texts whose "
            "terms forbid redistribution.",
            "‡Kyoto University (Fujikawa), Staatsbibliothek zu Berlin (Unschuld), Kyushu University, Keio University "
            "(Fujikawa), University of Tokyo (two libraries), Kenikai, Waseda University, National Diet Library, "
            "Tohoku University and Library of Congress. Only metadata are held; no image is downloaded.",
            "Sources are ranked by trust for de-duplication (Kanripo, JiCheng, McGill, CMETA, AEAM, Wikisource, web "
            "collections); a candidate sharing enough normalized 12-character shingles with an admitted work is recorded "
            "as its copy, while McGill, CMETA and AEAM transcriptions are kept as independent witnesses. "
            "IIIF, International Image Interoperability Framework.",
        ],
    }


def table2() -> dict:
    r = json.load(open(SD / "eval_demo_corpus.json", encoding="utf-8"))
    m = lambda s: r[s]["metrics"]  # noqa: E731
    inv, it = m("invariants"), m("interpretive")
    rows = [
        ["Boundaries", "Invariants", f"{inv['invariants']} probes of the harness under test", "Held",
         f"{inv['held']}/{inv['invariants']}", "Each of 6 boundaries removed breaks its invariant"],
        ["Readings", "Hard interpretive cases", f"{it['cases']} cases in 8 classes", "Accuracy (unsafe errors)",
         f"{it['dev']['n']}/{it['dev']['n']} (0)", f"82/84 = {it['heldout']['accuracy']:.3f} ({it['heldout']['unsafe']})"],
        ["Research value†", "Link anticipation", "189 topic–cutoff pairs; 29,467 candidates", "Precision@10",
         "–", "0.168 (popularity 0.134; chance 0.054); better in 149 of 189, P = 2.4 × 10⁻¹⁶"],
        ["", "End-to-end predictions", "Held-out topics, cutoff 1368", "Discoveries among survivors", "1/8",
         "7/19 = 0.37; leakage 0"],
        ["Verification", "Fabricated quotations", f"{m('hallucination')['samples']} quotations × 4 probes",
         "Handled correctly", "–", "60/60 in every probe; variant spellings accepted"],
        ["", "Provenance", "Committed claims and evidence", "Verbatim", "–",
         f"{m('provenance')['claims_verbatim']:.0%}; mean chain depth {m('provenance')['mean_chain_depth']:.1f} levels"],
        ["", "Claim extraction", "42 gold hyperedges", "Precision / recall",
         f"{m('claims')['precision']:.2f} / {m('claims')['recall']:.3f}", "–"],
        ["", "Temporal and anachronism guards", "Constraints, earliest attestations, equations", "Correct",
         "6/6 · 6/6 · 10/10", "Leakage 0; agent-asserted equivalence blocked"],
        ["Deep discovery", "Collation", "5 traditions copied down a known stemma", "Variant-unit recall / precision",
         f"{m('collation')['unit_recall']:.3f} / {m('collation')['unit_precision']:.3f}", "–"],
        ["", "Semantic reuse", "33 typed pairs", "Accuracy", f"{m('reuse')['accuracy']:.2f}", "–"],
        ["", "Stratigraphy", "5 composites; the Suwen", "Layer accuracy", f"{m('stratigraphy')['layer_accuracy']:.3f}",
         "Yunqi chapters 7/7 in the minor layer†"],
        ["", "Lost-text fragments", "Constructed lost work; Qianjin yaofang", "Precision",
         f"{m('fragments')['precision']:.2f}", "0.32†"],
        ["Task specification", "Punctuation", "55 held-out works (104 k characters)†", "Boundary F1", "–",
         "0.767 (rules 0.235); characters kept 1.000"],
        ["", "Drug pairs", "66,196 compositions†", "Textbook pairs significant", "–", "7/7, lift > 1.5"],
        ["V2", "Entities (24 types)", "41 development, 25 held-out sentences", "F1",
         f"{m('entities')['development']['f1']:.3f}", f"{m('entities')['held_out']['f1']:.3f}"],
        ["", "Ancient phenotypes → HPO", "20 development cases; 12 random passages†", "F1",
         f"{m('bridge')['phenotypes']['f1']:.3f}", "0.822"],
        ["", "Evidence audit", f"{m('audit')['claims']} claims", "Verdicts right (false SUPPORTED)",
         f"{m('audit')['claims']}/{m('audit')['claims']} ({m('audit')['false_supported']})", "–"],
    ]
    return {
        "title": "Table 2 | Evaluation of TaoChronos across its three layers",
        "header": ["Layer", "Suite", "Data", "Metric", "Development or constructed", "Held-out or real corpus"],
        "rows": rows, "total": None,
        "notes": [
            "Development and constructed gold sets were written by the authors with the rules they test; they are "
            "regression tests of intended behaviour, not unbiased benchmarks. Only held-out and real-corpus columns "
            "estimate generalization.",
            "†Needs the full corpus store, which is not distributed; values from docs/evals.md. All other values were "
            "reproduced for this paper by `taochronos eval` on the demonstration corpus (40 suites, 47 s).",
            "P value from a two-sided sign test over topic–cutoff pairs. HPO, Human Phenotype Ontology.",
        ],
    }


# ---------------------------------------------------------------------------------------------------------- writers
def to_markdown(t: dict) -> str:
    out = [f"**{t['title']}**", "", "| " + " | ".join(t["header"]) + " |", "|" + "---|" * len(t["header"])]
    for r in t["rows"] + ([t["total"]] if t["total"] else []):
        out.append("| " + " | ".join(c.replace("|", "\\|") for c in r) + " |")
    out.append("")
    out += [n for n in t["notes"]]
    return "\n\n".join([out[0], "\n".join(out[2:-len(t["notes"])])] + t["notes"]) + "\n"


def tex_escape(s: str) -> str:
    rep = {"&": r"\&", "%": r"\%", "#": r"\#", "_": r"\_", "~": r"\textasciitilde{}", "†": r"$^{\dagger}$",
           "‡": r"$^{\ddagger}$", "*": r"$^{*}$", "×": r"$\times$", "⁻¹⁶": r"$^{-16}$", "→": r"$\rightarrow$",
           "≈": r"$\approx$", ">": r"$>$"}
    for k, v in rep.items():
        s = s.replace(k, v)
    return s


def to_latex(t: dict) -> str:
    cols = "l" * len(t["header"])
    lines = [r"% requires \usepackage{booktabs} and a CJK-capable engine (xelatex + xeCJK) for the Chinese names",
             r"\begin{table}[t]", r"\small", rf"\caption{{\textbf{{{tex_escape(t['title'].split(' | ')[0])}}} $|$ "
             rf"{tex_escape(t['title'].split(' | ')[1])}}}", rf"\begin{{tabular}}{{{cols}}}", r"\toprule",
             " & ".join(tex_escape(h) for h in t["header"]) + r" \\", r"\midrule"]
    for r in t["rows"]:
        lines.append(" & ".join(tex_escape(c) for c in r) + r" \\")
    if t["total"]:
        lines.append(r"\addlinespace")
        lines.append(" & ".join(tex_escape(c) for c in t["total"]) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}", r"\par\footnotesize"]
    lines += [tex_escape(n) + r"\par" for n in t["notes"]]
    lines.append(r"\end{table}")
    return "\n".join(lines) + "\n"


def to_docx(tables: list[dict], path: Path) -> None:
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
        setattr(sec, side, Mm(15))
    style = doc.styles["Normal"]
    style.font.name = "Arial"
    style.font.size = Pt(8)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "SimSun")

    def border(cell, **edges):
        tcPr = cell._tc.get_or_add_tcPr()
        b = tcPr.find(qn("w:tcBorders"))
        if b is None:
            b = OxmlElement("w:tcBorders")
            tcPr.append(b)
        for edge, on in edges.items():
            el = OxmlElement(f"w:{edge}")
            el.set(qn("w:val"), "single" if on else "nil")
            if on:
                el.set(qn("w:sz"), "6")
                el.set(qn("w:color"), "000000")
            b.append(el)

    for k, t in enumerate(tables):
        if k:
            doc.add_page_break()
        p = doc.add_paragraph()
        head, rest = t["title"].split(" | ")
        p.add_run(head + " | ").bold = True
        p.add_run(rest).bold = True
        body = t["rows"] + ([t["total"]] if t["total"] else [])
        tab = doc.add_table(rows=1 + len(body), cols=len(t["header"]))
        tab.style = doc.styles["Normal Table"]
        for j, h in enumerate(t["header"]):
            c = tab.rows[0].cells[j]
            c.text = ""
            c.paragraphs[0].add_run(h).bold = True
        for i, r in enumerate(body, start=1):
            for j, v in enumerate(r):
                tab.rows[i].cells[j].text = v
                if t["total"] and i == len(body):
                    for run in tab.rows[i].cells[j].paragraphs[0].runs:
                        run.bold = True
        last = len(body)
        for i, row in enumerate(tab.rows):
            for c in row.cells:
                border(c, left=False, right=False, insideV=False, insideH=False,
                       top=(i == 0), bottom=(i == 0 or i == last))
                for par in c.paragraphs:
                    par.paragraph_format.space_after = Pt(1)
                    for run in par.runs:
                        run.font.size = Pt(8)
                        run.font.name = "Arial"
        for n in t["notes"]:
            q = doc.add_paragraph(n)
            q.paragraph_format.space_after = Pt(2)
            for run in q.runs:
                run.font.size = Pt(7.5)
    doc.save(path)


def main() -> None:
    tables = [table1(), table2()]
    for i, t in enumerate(tables, start=1):
        (OUT / f"table{i}.md").write_text(to_markdown(t), encoding="utf-8")
        (OUT / f"table{i}.tex").write_text(to_latex(t), encoding="utf-8")
    to_docx(tables, OUT / "tables.docx")
    print("wrote", ", ".join(str(p.relative_to(HOME)) for p in sorted(OUT.glob("table*")) if p.suffix != ".py"))


if __name__ == "__main__":
    main()
