"""Check the three case figures, as saved, against the answers they draw.

    python paper/cases/verify_cases.py        # exit status 1 if a check fails

Read back from each PDF (not from the scripts):

* the page is 183 × 170 mm, one page, every font embedded as TrueType and none of them a fallback font;
* Chinese characters are drawn by the two engines that disagree about wrongly embedded CJK fonts (MuPDF and Poppler):
  each must put ink where the text is;
* every passage identifier printed in the figure is one the answer cites;
* every quotation printed between 「 and 」 is in the answer character for character (an ellipsis marks an omission:
  each part must be there, in order).

The figure scripts themselves assert the numbers they draw against the answer's tables while they run.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image

HERE = Path(__file__).resolve().parent
FIGURES = {1: "Case1_herbal_formula_knee_pain", 2: "Case2_materia_medica_huangqi", 3: "Case3_acupuncture_low_back_pain"}
PASSAGE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?:\.\d{2,5})+\b")


def in_order(parts: list[str], text: str) -> bool:
    at = 0
    for p in parts:
        at = text.find(p, at)
        if at < 0:
            return False
        at += len(p)
    return True


def cjk_ink(pdf: Path) -> dict[str, float]:
    """The least share of inked pixels in any box of Chinese text, as MuPDF and as Poppler draw the page."""
    doc = pymupdf.open(pdf)
    page = doc[0]
    boxes = [s["bbox"] for b in page.get_text("dict")["blocks"] for ln in b.get("lines", []) for s in ln["spans"]
             if re.search(r"[㐀-鿿]{2,}", s["text"]) and not re.search(r"[A-Za-z0-9]", s["text"])]
    scale = 300 / 72
    pix = page.get_pixmap(dpi=300, colorspace=pymupdf.csGRAY)
    images = {"mupdf": np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)[:, :pix.width]}
    if shutil.which("pdftoppm"):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["pdftoppm", "-r", "300", "-gray", "-png", str(pdf), f"{tmp}/p"], check=True,
                           capture_output=True)
            images["poppler"] = np.asarray(Image.open(next(Path(tmp).glob("p*.png"))).convert("L"))
    out = {}
    for name, im in images.items():
        ink = []
        for x0, y0, x1, y1 in boxes:  # ink: pixels that differ from the box's background (its median grey)
            box = im[int(y0 * scale):int(y1 * scale), int(x0 * scale):int(x1 * scale)].astype(int)
            ink.append(float((np.abs(box - np.median(box)) > 45).mean()))
        out[name] = min(ink) if ink else 0.0
    out["boxes"] = len(boxes)
    return out


def main() -> int:
    failures = 0
    for n, name in FIGURES.items():
        pdf = HERE / "out" / f"{name}.pdf"
        answer = (HERE / "source_data" / f"case{n}_answer.md").read_text(encoding="utf-8")
        doc = pymupdf.open(pdf)
        page = doc[0]
        text = page.get_text()
        problems = []
        w, h = page.rect.width / 72 * 25.4, page.rect.height / 72 * 25.4
        if len(doc) != 1 or abs(w - 183) > 0.5 or h > 170.5:
            problems.append(f"page {w:.1f} × {h:.1f} mm, {len(doc)} pages")
        fonts = page.get_fonts(full=True)
        bad = [f[3] for f in fonts if f[1] != "ttf" or f[2] != "Type0" or "LastResort" in f[3]]
        if bad:
            problems.append(f"fonts not embedded as TrueType: {bad}")
        ink = cjk_ink(pdf)
        for engine in ("mupdf", "poppler"):
            if engine in ink and ink[engine] < 0.02:
                problems.append(f"{engine} draws no ink in at least one of {ink['boxes']} Chinese text boxes")
        ids = sorted(set(PASSAGE.findall(text)))
        missing = [i for i in ids if i not in answer]
        if missing:
            problems.append(f"passage identifiers not in the answer: {missing}")
        flat = re.sub(r"\s+", "", text)
        quotes = re.findall(r"「([^「」]+)」", flat)
        plain = re.sub(r"\s+", "", answer)
        wrong = [q for q in quotes if not in_order([p for p in q.split("…") if p], plain)]
        if wrong:
            problems.append(f"quotations not in the answer: {wrong}")
        engines = ", ".join(f"{k} {ink[k]:.2f}" for k in ("mupdf", "poppler") if k in ink)
        print(f"{name}: {w:.0f} × {h:.0f} mm; {len(fonts)} fonts, all TrueType; Chinese text ink ({engines}); "
              f"{len(ids)} passage identifiers and {len(quotes)} quotations checked against the answer"
              + ("" if not problems else "\n  FAIL: " + "\n  FAIL: ".join(problems)))
        failures += len(problems)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
