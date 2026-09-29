"""One reviewing copy of the display items: every figure (vector SVG) with its legend, then the tables, as HTML and PDF.

    python paper/build_preview.py      # paper/preview.html and, when Chromium is found, paper/TaoChronos_display_items.pdf

The PDF is for reading and circulating among the authors; the files submitted are the figures in paper/figures/out
(PDF masters), the legends in paper/legends.md and the tables in paper/tables (Word, LaTeX or Markdown).
"""

from __future__ import annotations

import html
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "tables"))
from make_tables import table1, table2  # noqa: E402

FIGURES = ["fig1_overview", "fig2_corpus", "fig3_verification", "fig4_research_value", "fig5_case_studies",
           "extfig1_generalization", "extfig2_canon_replication", "extfig3_resources"]
CSS = """
@page { size: A4; margin: 14mm 13.5mm; }
body { font-family: Arial, 'Noto Sans CJK SC', sans-serif; font-size: 8.5pt; line-height: 1.35; color: #000; }
h1 { font-size: 13pt; margin: 0 0 2mm; } .sub { color: #444; margin-bottom: 6mm; }
.item { break-inside: avoid; page-break-inside: avoid; margin-bottom: 7mm; }
.item img { width: 183mm; display: block; margin: 0 0 2.5mm; }
.legend h2 { font-size: 8.5pt; margin: 0 0 1mm; } .legend p { margin: 0; text-align: justify; }
.pagebreak { break-before: page; }
table { border-collapse: collapse; width: 100%; font-size: 7.5pt; margin: 1mm 0 1.5mm; }
th, td { text-align: left; vertical-align: top; padding: 1.2mm 1.6mm 1.2mm 0; }
thead th { border-top: 0.8pt solid #000; border-bottom: 0.5pt solid #000; }
tbody tr:last-child td { border-bottom: 0.8pt solid #000; }
.note { font-size: 7pt; margin: 0.6mm 0; } code { font-family: 'DejaVu Sans Mono', monospace; font-size: 7.5pt; }
"""


def inline(s: str) -> str:
    s = html.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", s)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", s)


def legends() -> dict[str, tuple[str, str]]:
    text = (HERE / "legends.md").read_text(encoding="utf-8")
    out = {}
    for block in re.split(r"^## ", text, flags=re.M)[1:]:
        title, _, body = block.partition("\n")
        m = re.match(r"(Extended Data Fig\. \d+|Fig\. \d+)", title)
        if m:
            out[m.group(1)] = (title.strip(), " ".join(body.split()))
    return out


def table_html(t: dict) -> str:
    head, rest = t["title"].split(" | ")
    rows = t["rows"] + ([t["total"]] if t["total"] else [])
    body = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows)
    notes = "".join(f'<p class="note">{inline(n)}</p>' for n in t["notes"])
    return (f'<div class="item"><div class="legend"><h2>{inline(head)} | {inline(rest)}</h2></div><table><thead><tr>'
            + "".join(f"<th>{inline(h)}</th>" for h in t["header"]) + f"</tr></thead><tbody>{body}</tbody></table>"
            f"{notes}</div>")


def main() -> None:
    leg = legends()
    parts = [f"<!doctype html><html lang='en'><meta charset='utf-8'><title>TaoChronos display items</title>"
             f"<style>{CSS}</style><body><h1>TaoChronos (道乃久): display items</h1>"
             "<div class='sub'>Five figures, three Extended Data figures and two tables, at their final print size "
             "(183 mm wide). Masters: paper/figures/out (PDF, SVG, 600 dpi PNG); legends: paper/legends.md; tables: "
             "paper/tables.</div>"]
    for i, name in enumerate(FIGURES):
        key = (f"Fig. {i + 1}" if not name.startswith("extfig") else f"Extended Data Fig. {name[6]}")
        title, body = leg[key]
        brk = " pagebreak" if i else ""
        parts.append(f'<div class="item{brk}"><img src="figures/out/{name}.svg" alt="{html.escape(key)}">'
                     f'<div class="legend"><h2>{inline(title)}</h2><p>{inline(body)}</p></div></div>')
    parts.append('<div class="pagebreak"></div>' + table_html(table1()))
    parts.append('<div class="pagebreak"></div>' + table_html(table2()))
    parts.append("</body></html>")
    page = HERE / "preview.html"
    page.write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {page.relative_to(HERE.parent)}")
    chrome = next((c for c in ("/opt/pw-browsers/chromium", shutil.which("chromium") or "",
                               shutil.which("google-chrome") or "") if c and Path(c).exists()), None)
    if chrome:
        pdf = HERE / "TaoChronos_display_items.pdf"
        subprocess.run([chrome, "--headless", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
                        f"--print-to-pdf={pdf}", page.as_uri()], check=True, capture_output=True, timeout=180)
        print(f"wrote {pdf.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
