"""TrueType-outline copies of Noto Sans CJK SC, so that the PDFs draw Chinese characters in every viewer.

The Noto Sans CJK faces most systems install are OpenType fonts with CFF outlines (``NotoSansCJK-Regular.ttc``).
matplotlib embeds such a face in a PDF as if it were TrueType (a ``CIDFontType2`` descriptor around a CFF font
program).  Poppler and Acrobat tolerate the mismatch ("Mismatch between font type and embedded font file"); MuPDF,
and the viewers built on it, draw no glyph at all, so every Chinese character in the figure goes missing.

``use_truetype_cjk()`` writes, once, a copy of the regular and the bold face with quadratic (TrueType) outlines,
limited to the characters the figures can draw (every non-ASCII character in this directory's scripts and source
data), and makes matplotlib resolve "Noto Sans CJK SC" to those copies for the running process.  The shapes are the
same to within one font unit in 1,000; the names inside the font are unchanged, so the PDF still lists
``NotoSansCJKsc-Regular``.  A face that already has TrueType outlines is left alone.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = Path(os.environ.get("TAOCHRONOS_FONT_CACHE", Path.home() / ".cache" / "taochronos" / "fonts"))
FAMILY = "Noto Sans CJK SC"


def needed_characters() -> str:
    """Every non-ASCII character a case figure can draw: those in the scripts and in the source data."""
    chars: set[str] = set()
    for f in [*HERE.glob("*.py"), *(HERE / "source_data").glob("*")]:
        chars.update(c for c in f.read_text(encoding="utf-8") if ord(c) > 0x7F)
    return "".join(sorted(chars))


def _convert(src: str, index: int, chars: str, out: Path) -> None:
    from fontTools import subset
    from fontTools.pens.cu2quPen import Cu2QuPen
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.ttLib import TTFont, newTable

    font = TTFont(src, fontNumber=index)
    opts = subset.Options()
    opts.layout_features = []
    opts.name_IDs = ["*"]
    opts.name_languages = ["*"]
    opts.notdef_outline = True
    opts.glyph_names = False
    opts.drop_tables += ["vhea", "vmtx", "VORG", "BASE", "GSUB", "GPOS", "GDEF"]
    sub = subset.Subsetter(opts)
    sub.populate(text=chars)
    sub.subset(font)
    order = font.getGlyphOrder()
    glyphs = font.getGlyphSet()
    glyf = newTable("glyf")
    glyf.glyphOrder = order
    glyf.glyphs = {}
    for name in order:
        pen = TTGlyphPen(glyphs)
        glyphs[name].draw(Cu2QuPen(pen, max_err=1.0, reverse_direction=True))
        glyf[name] = pen.glyph()
    font["loca"] = newTable("loca")
    font["glyf"] = glyf
    del font["CFF "]
    maxp = font["maxp"]
    maxp.tableVersion = 0x00010000
    maxp.maxZones = 1
    maxp.maxTwilightPoints = maxp.maxStorage = maxp.maxFunctionDefs = maxp.maxInstructionDefs = 0
    maxp.maxStackElements = maxp.maxSizeOfInstructions = 0
    maxp.maxComponentElements = max((len(g.components) for g in glyf.glyphs.values() if g.isComposite()), default=0)
    font["post"].formatType = 3.0
    font["post"].extraNames = []
    font["post"].mapping = {}
    font["post"].glyphOrder = None
    font.sfntVersion = "\x00\x01\x00\x00"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    font.save(tmp)
    tmp.replace(out)


def use_truetype_cjk() -> list[str]:
    """Make matplotlib draw Chinese characters from TrueType-outline copies of Noto Sans CJK SC.

    Returns the font files now behind the family (an empty list when the family is not installed, or already has
    TrueType outlines)."""
    from fontTools.ttLib import TTFont
    from matplotlib import font_manager as fm

    faces = [f for f in fm.fontManager.ttflist if f.name == FAMILY]
    if not faces:
        return []
    chars = needed_characters()
    key = hashlib.sha256(chars.encode("utf-8")).hexdigest()[:12]
    made = []
    for face in list(faces):
        src = face.fname
        if str(src).startswith(str(CACHE)):
            made.append(src)
            continue
        number = 0
        if str(src).lower().endswith((".ttc", ".otc")):
            from fontTools.ttLib import TTCollection

            names = [f["name"].getDebugName(1) for f in TTCollection(src, lazy=True).fonts]
            number = names.index(FAMILY)
        probe = TTFont(src, fontNumber=number, lazy=True)
        if "glyf" in probe:
            continue  # TrueType outlines already: matplotlib embeds it correctly
        weight = "Bold" if str(face.weight) in ("bold", "700") or face.weight == 700 else "Regular"
        out = CACHE / f"NotoSansCJKsc-{weight}-truetype-{key}.ttf"
        if not out.exists():
            _convert(src, number, chars, out)
        fm.fontManager.ttflist.remove(face)
        fm.fontManager.addfont(str(out))
        made.append(str(out))
    if made:
        fm.fontManager._findfont_cached.cache_clear()
    return made


if __name__ == "__main__":
    for path in use_truetype_cjk():
        print(path)
