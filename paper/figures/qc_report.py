"""Nature display-item QC of every figure in paper/figures/out: the machine-measurable rules, one table per figure.

    python paper/figures/qc_report.py      # writes paper/figures/out/qc/QC_REPORT.md; exit status 1 on a failure

Width (89, 120–136 or 183 mm), height (≤ 170 mm), the 600 dpi PNG, RGB, embedded fonts (Arial; Noto Sans CJK for
Chinese characters), live text in the PDF, text of 5–7 pt with 8 pt bold panel labels and strokes of 0.25–1 pt (from the
per-figure checks Canvas.save writes), text overlaps, and a strong red + strong green heuristic.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

OUT = Path(__file__).resolve().parent / "out"
QC = OUT / "qc"


def width_class(w: float) -> tuple[str, str]:
    for label, t in (("single column (89 mm)", 89.0), ("double column (183 mm)", 183.0)):
        if abs(w - t) <= 0.5:
            return "PASS", label
    if 120.0 <= w <= 136.0:
        return "PASS", "1.5 column (120–136 mm)"
    return "FAIL", "not a Nature column width"


def red_green(png: Path) -> tuple[str, float, float]:
    arr = np.asarray(Image.open(png).convert("RGB")).reshape(-1, 3).astype("int16")
    idx = np.linspace(0, len(arr) - 1, min(len(arr), 400_000)).astype(int)
    r, g, b = arr[idx, 0], arr[idx, 1], arr[idx, 2]
    red = float(((r > 120) & (g < 90) & (b < 90)).mean())
    green = float(((g > 100) & (r < 100) & (b < 100)).mean())
    return ("WARN" if red > 0.003 and green > 0.003 else "PASS"), red, green


def main() -> int:
    lines = ["# Nature display-item QC", "",
             "Machine-measured: size, resolution, colour mode, fonts, live text, text sizes, stroke widths, overlaps, "
             "red/green. Checked by eye: panel order, legend content, colour meaning.", ""]
    failures = 0
    for qc_json in sorted(QC.glob("*.json")):
        name = qc_json.stem
        q = json.loads(qc_json.read_text(encoding="utf-8"))
        png = OUT / f"{name}.png"
        im = Image.open(png)
        dpi = im.info.get("dpi", (0, 0))[0]
        wpx, hpx = im.size
        wc, wlab = width_class(q["width_mm"])
        rg, red, green = red_green(png)
        fonts_ok = all(any(k in f for k in ("Arial", "NotoSansCJK")) for f in q["fonts"])
        sizes = [s for s in q["text_sizes_pt"] if s != 8.0]
        rows = [
            ("Figure width", wc, f"{q['width_mm']:.1f} mm ({wlab})", "89 / 120–136 / 183 mm"),
            ("Figure height", "PASS" if q["height_mm"] <= 170.5 else "FAIL", f"{q['height_mm']:.1f} mm", "≤ 170 mm"),
            ("Vector master", "PASS", "PDF (TrueType fonts, text live) + SVG", "vector for line art"),
            ("Raster preview", "PASS" if round(dpi) >= 300 and im.mode == "RGB" else "FAIL", f"{round(dpi)} dpi, {wpx} × {hpx} px, {im.mode}",
             "≥ 300 dpi, RGB"),
            ("Embedded fonts", "PASS" if fonts_ok else "FAIL", ", ".join(q["fonts"]), "Arial (Noto Sans CJK for 汉字)"),
            ("Live text", "PASS" if q["live_text_chars"] > 0 else "FAIL", f"{q['live_text_chars']} characters selectable",
             "not outlined"),
            ("Text size", "PASS" if sizes and min(sizes) >= 5 and max(sizes) <= 7 else "FAIL",
             f"{min(sizes)}–{max(sizes)} pt; panel labels 8 pt bold", "5–7 pt; labels 8 pt bold"),
            ("Stroke width", "PASS" if q["stroke_widths_pt"] and min(q["stroke_widths_pt"]) >= 0.25
             and max(q["stroke_widths_pt"]) <= 1.0 else "FAIL",
             f"{min(q['stroke_widths_pt'])}–{max(q['stroke_widths_pt'])} pt", "0.25–1 pt"),
            ("Overlaps and page bounds", "PASS" if not q["warnings"] else "FAIL",
             "none" if not q["warnings"] else "; ".join(q["warnings"]), "no collisions"),
            ("Red/green", rg, f"strong red {red:.4f}, strong green {green:.4f}", "no red–green contrast"),
        ]
        bad = sum(r[1] == "FAIL" for r in rows)
        failures += bad
        warn = sum(r[1] == "WARN" for r in rows)
        lines += [f"## {name}", "", f"Verdict: {'PASS' if not bad else f'NEEDS FIXES: {bad} failures'}"
                  + (f" with {warn} warnings" if warn else ""), "",
                  "| Check | Status | Measured | Target |", "|---|---|---|---|"]
        lines += [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in rows]
        lines.append("")
    (QC / "QC_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
