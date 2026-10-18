"""Build the submission files of the TaoChronos manuscript for npj Digital Medicine and for Engineering.

    pip install python-docx pyyaml          # pandoc ≥ 3 and Chromium (for the PDFs) must be on the machine
    python paper/manuscript/build.py                 # both journals
    python paper/manuscript/build.py npj             # or: engineering

Sources (edit these, never the outputs):
  manuscript.md       the npj Digital Medicine Article (Nature style; Oxford spelling)
  engineering.md      the Engineering Research Article (Elsevier style; American spelling; ~6,000 words in all)
  highlights.md       Engineering's highlights (3–5 bullets, ≤ 85 characters each)
  references.bib      one bibliography for both; csl/ holds the two citation styles
  make_manuscript_tables.py   Tables 1–2 (Markdown, LaTeX, CSV, Word) in tables/
and, from the display-item package one directory up, the figures (paper/figures/out), their legends
(paper/legends.md), Extended Data Table 1 (paper/tables) and the Supplementary Information (paper/supplementary).

Outputs in submission/<journal>/: the manuscript as Word, PDF, LaTeX and the assembled Markdown, and the
Supplementary Information renumbered for that journal (neither journal has Extended Data: Extended Data Figs. 1–3
become Supplementary Figs. 2–4, Extended Data Table 1 Supplementary Table 13 and Extended Data Table 2 the main
text's Table 2; for Engineering, which counts figures and tables in its word limit, Fig. 6 and Table 2 also move to
the Supplementary Information as Supplementary Fig. 5 and Supplementary Table 14).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAPER = HERE.parent
MASTERS = PAPER / "figures" / "out"
FIGS = HERE / "build" / "figures"  # 300 dpi copies of the masters for the reviewing files (git-ignored)
OUT = HERE / "submission"

sys.path.insert(0, str(HERE))
import make_manuscript_tables  # noqa: E402

MAIN_FIGURES = ["fig1_architecture", "fig2_corpus", "fig3_end_to_end", "fig4_verification", "fig5_research_value",
                "fig6_case_studies"]
SUPP_FIGURES = {"Supplementary Fig. 2": ("Extended Data Fig. 1", "extfig1_generalization"),
                "Supplementary Fig. 3": ("Extended Data Fig. 2", "extfig2_canon_replication"),
                "Supplementary Fig. 4": ("Extended Data Fig. 3", "extfig3_resources")}

# Neither journal has Extended Data.  Longest names first, so that "Extended Data Fig. 1" is not read as "Fig. 1".
NPJ_NUMBERS = [
    ("Extended Data Figs. 1–3", "Supplementary Figs. 2–4"), ("Extended Data Fig. 1", "Supplementary Fig. 2"),
    ("Extended Data Fig. 2", "Supplementary Fig. 3"), ("Extended Data Fig. 3", "Supplementary Fig. 4"),
    ("Extended Data Table 1", "Supplementary Table 13"), ("Extended Data Table 2", "Table 2"),
    ("ED Fig. 1", "Supplementary Fig. 2"), ("ED Fig. 2", "Supplementary Fig. 3"), ("ED Fig. 3", "Supplementary Fig. 4"),
    ("ED Table 1", "Supplementary Table 13"), ("ED Table 2", "Table 2"),
]
# Engineering also moves Fig. 6 and Table 2 to the Supplementary Information.
ENGINEERING_NUMBERS = NPJ_NUMBERS + [
    (re.compile(r"(?<!Supplementary )Fig\. 6"), "Supplementary Fig. 5"),
    (re.compile(r"(?<!Supplementary )Table 2\b"), "Supplementary Table 14"),
]

CSS = """
@page { size: A4; margin: 20mm 18mm; }
body { font-family: Arial, 'Liberation Sans', 'WenQuanYi Zen Hei', 'Noto Sans CJK SC', sans-serif; font-size: 10.5pt;
       line-height: 1.5; color: #000; max-width: 175mm; margin: 0 auto; }
h1 { font-size: 13pt; margin: 7mm 0 2mm; } h2 { font-size: 11pt; margin: 5mm 0 1.5mm; }
header h1.title { font-size: 16pt; line-height: 1.25; margin-top: 0; }
p { margin: 0 0 2.2mm; text-align: justify; }
figure { margin: 4mm 0 2mm; break-inside: avoid; } figure img { width: 100%; }
figcaption { display: none; }
.legend { break-before: avoid; margin-bottom: 6mm; font-size: 9pt; }
table { border-collapse: collapse; width: 100%; font-size: 8pt; margin: 1.5mm 0 2mm; line-height: 1.3; }
th, td { text-align: left; vertical-align: top; padding: 1.1mm 1.6mm 1.1mm 0; }
thead th { border-top: 0.9pt solid #000; border-bottom: 0.5pt solid #000; }
tbody tr:last-child td { border-bottom: 0.9pt solid #000; }
code { font-family: 'DejaVu Sans Mono', monospace; font-size: 8.5pt; }
#refs { font-size: 9pt; } .csl-entry { margin-bottom: 1mm; } .csl-left-margin { float: left; width: 8mm; }
.csl-right-inline { margin-left: 8mm; }
.pagebreak { break-before: page; }
.tablewrap { break-before: page; } .tablewrap p { font-size: 8pt; line-height: 1.35; text-align: left; }
.tablewrap p:first-child { font-size: 9.5pt; }
"""


def renumber(text: str, mapping: list) -> str:
    for old, new in mapping:
        text = old.sub(new, text) if isinstance(old, re.Pattern) else text.replace(old, new)
    return text


def legends() -> dict[str, tuple[str, str]]:
    """paper/legends.md, figure by figure: number → (title, legend)."""
    text = (PAPER / "legends.md").read_text(encoding="utf-8")
    out = {}
    for block in re.split(r"^## ", text, flags=re.M)[1:]:
        title, _, body = block.partition("\n")
        m = re.match(r"(Extended Data Fig\. \d+|Supplementary Fig\. \d+|Fig\. \d+)\s*\|\s*(.*)", title.strip())
        if m:
            out[m.group(1)] = (m.group(2).strip(), " ".join(body.split()))
    return out


def legend_block(number: str, title: str, body: str, image: str) -> str:
    return (f"![](@FIGS@/{image}.png){{width=100%}}\n\n"
            f"::: legend\n**{number} | {title}** {body}\n:::\n")


def table_block(path: Path, mapping: list | None = None) -> str:
    text = path.read_text(encoding="utf-8")
    text = renumber(text, mapping) if mapping else text
    return f"::: tablewrap\n{text}\n:::\n"


def pandoc(src: Path, out: Path, csl: str, *extra: str) -> None:
    cmd = ["pandoc", src.name, "-o", out.name, "--citeproc", "--bibliography", str(HERE / "references.bib"),
           "--csl", str(HERE / "csl" / csl), *extra]
    subprocess.run(cmd, check=True, cwd=src.parent)  # image paths are relative to the output folder


def chrome() -> str | None:
    for c in ("/opt/pw-browsers/chromium", shutil.which("chromium") or "", shutil.which("google-chrome") or ""):
        if c and Path(c).exists():
            return c
    return None


def to_pdf(page: Path, pdf: Path) -> None:
    exe = chrome()
    if not exe:
        print("  (no Chromium found: PDF skipped)")
        return
    subprocess.run([exe, "--headless", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf}", page.as_uri()], check=True, capture_output=True, timeout=300)


def graphical_abstract(png: Path) -> None:
    """figures/graphical_abstract.svg → PNG at twice its 1328 × 531 px (Engineering asks for at least 1328 × 531)."""
    exe = chrome()
    if not exe:
        print("  (no Chromium found: graphical abstract PNG skipped)")
        return
    from PIL import Image  # installed with matplotlib
    svg = HERE / "figures" / "graphical_abstract.svg"
    page = png.with_suffix(".html")
    page.write_text('<!doctype html><meta charset="utf-8"><style>html,body{margin:0;background:#fff}img{display:block}'
                    f'</style><img src="{svg.as_uri()}" width="1328" height="531">', encoding="utf-8")
    shot = png.with_suffix(".full.png")
    subprocess.run([exe, "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                    "--allow-file-access-from-files", "--window-size=1328,900", "--force-device-scale-factor=2",
                    f"--screenshot={shot}", page.as_uri()], check=True, capture_output=True, timeout=120)
    Image.open(shot).crop((0, 0, 2656, 1062)).save(png, dpi=(192, 192))
    page.unlink()
    shot.unlink()


def write_all(md: str, stem: str, folder: Path, csl: str, title: str, *extra: str) -> None:
    """One assembled Markdown file → Word, PDF (printed from standalone HTML) and LaTeX.  The Markdown kept in the
    folder points at the master figures, so it reads on GitHub; Word and PDF embed the 300 dpi copies; LaTeX takes the
    vector PDFs."""
    folder.mkdir(parents=True, exist_ok=True)
    src = folder / f"{stem}.md"
    src.write_text(md.replace("@FIGS@", os.path.relpath(MASTERS, folder)), encoding="utf-8")
    review = folder / f".{stem}.review.md"
    review.write_text(md.replace("@FIGS@", os.path.relpath(FIGS, folder)), encoding="utf-8")
    css = folder / "style.css"
    css.write_text(CSS, encoding="utf-8")
    pandoc(review, folder / f"{stem}.docx", csl, *extra)
    html = folder / f"{stem}.html"
    pandoc(review, html, csl, "--standalone", "--embed-resources", "--css", css.name, "--metadata",
           f"pagetitle={title}", *extra)
    to_pdf(html, folder / f"{stem}.pdf")
    html.unlink()  # images embedded, several MB; the PDF is printed from it
    tex = folder / f"{stem}.tex"
    pandoc(src, tex, csl, "--standalone", "-V", "documentclass=article", "-V", "geometry:margin=2.5cm",
           "-V", "CJKmainfont=Noto Serif CJK SC", "-V", "mainfont=TeX Gyre Termes", *extra)
    t = tex.read_text(encoding="utf-8").replace(".png}", ".pdf}")
    tex.write_text("% Compile with xelatex (the Chinese text needs xeCJK and a CJK font). Figures are the vector PDFs in\n"
                   "% paper/figures/out; the references are already formatted (citeproc), so no BibTeX run is needed.\n"
                   + t, encoding="utf-8")
    css.unlink()
    review.unlink()
    print("  wrote", ", ".join(p.name for p in sorted(folder.glob(f"{stem}.*"))))


def supplementary(journal: str, mapping: list) -> str:
    """The Supplementary Information renumbered for a journal, with the items that leave the main text appended."""
    si = (PAPER / "supplementary" / "Supplementary_Information.md").read_text(encoding="utf-8")
    si = si.replace("](../figures/out/", "](@FIGS@/")
    si = renumber(si, mapping)
    leg = legends()
    extra = ["", "## Supplementary Figures 2–4" + (" and 5" if journal == "engineering" else ""), ""]
    for number, (ed, image) in SUPP_FIGURES.items():
        title, body = leg[ed]
        extra.append(legend_block(number, title, renumber(body, mapping), image))
    if journal == "engineering":
        title, body = leg["Fig. 6"]
        extra.append(legend_block("Supplementary Fig. 5", title, renumber(body, mapping), "fig6_case_studies"))
    extra += ["", "## Supplementary Table 13" + (" and 14" if journal == "engineering" else ""), ""]
    extra.append(table_block(PAPER / "tables" / "extended_data_table1.md", mapping))
    if journal == "engineering":
        extra.append(renumber(table_block(HERE / "tables" / "table2.md"), mapping))
    marker = "## Supplementary Data"
    head, _, tail = si.partition(marker)
    return head + "\n".join(extra) + "\n\n" + marker + tail


def npj() -> None:
    print("npj Digital Medicine")
    leg = legends()
    md = (HERE / "manuscript.md").read_text(encoding="utf-8")
    parts = [md, "", "# Figure legends", ""]
    for i, image in enumerate(MAIN_FIGURES, start=1):
        title, body = leg[f"Fig. {i}"]
        parts.append(legend_block(f"Fig. {i}", title, renumber(body, NPJ_NUMBERS), image))
    parts += ["", "# Tables", "", table_block(HERE / "tables" / "table1.md"), "",
              table_block(HERE / "tables" / "table2.md")]
    folder = OUT / "npj"
    write_all("\n".join(parts), "TaoChronos_npjDigitalMedicine", folder, "nature.csl",
              "TaoChronos: A Reliable Agent for Knowledge Discovery in Traditional Chinese Medicine")
    si = "---\ntitle: \"Supplementary Information\"\nsubtitle: \"TaoChronos: A Reliable Agent for Knowledge Discovery " \
         "in Traditional Chinese Medicine\"\n---\n\n" + supplementary("npj", NPJ_NUMBERS).split("\n", 1)[1]
    write_all(si, "Supplementary_Information_npj", folder, "nature.csl", "Supplementary Information")


def engineering() -> None:
    print("Engineering")
    md = (HERE / "engineering.md").read_text(encoding="utf-8")
    md = md.replace("{{TABLE1}}", table_block(HERE / "tables" / "table1.md"))
    md = re.sub(r"\{\{FIG (\w+)\}\}", lambda m: f"![](@FIGS@/{m.group(1)}.png){{width=100%}}", md)
    folder = OUT / "engineering"
    write_all(md, "TaoChronos_Engineering", folder, "elsevier-vancouver.csl",
              "TaoChronos: A Reliable Agent for Knowledge Discovery in Traditional Chinese Medicine", "--number-sections")
    graphical_abstract(HERE / "figures" / "graphical_abstract.png")
    shutil.copy(HERE / "figures" / "graphical_abstract.png", folder / "Graphical_abstract.png")
    hl = folder / "Highlights.docx"
    subprocess.run(["pandoc", str(HERE / "highlights.md"), "-o", str(hl)], check=True)
    print("  wrote", hl.name)
    si = "---\ntitle: \"Appendix A. Supplementary data\"\nsubtitle: \"TaoChronos: A Reliable Agent for Knowledge " \
         "Discovery in Traditional Chinese Medicine\"\n---\n\n" + \
         supplementary("engineering", ENGINEERING_NUMBERS).split("\n", 1)[1]
    write_all(si, "Supplementary_Information_Engineering", folder, "elsevier-vancouver.csl",
              "Appendix A. Supplementary data")


def review_figures() -> None:
    """The figures embedded in the Word and PDF files at 300 dpi (the masters in paper/figures/out are 600 dpi and are
    what the journals receive as figure files)."""
    from PIL import Image  # installed with matplotlib
    FIGS.mkdir(parents=True, exist_ok=True)
    for src in MASTERS.glob("*.png"):
        dst = FIGS / src.name
        if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
            continue
        im = Image.open(src)
        small = im.convert("RGB").resize((im.width // 2, im.height // 2), Image.LANCZOS)
        small.quantize(colors=256, method=Image.Quantize.MEDIANCUT).save(dst, dpi=(300, 300), optimize=True)


def main() -> None:
    make_manuscript_tables.main()
    review_figures()
    which = sys.argv[1:] or ["npj", "engineering"]
    if "npj" in which:
        npj()
    if "engineering" in which:
        engineering()


if __name__ == "__main__":
    main()
