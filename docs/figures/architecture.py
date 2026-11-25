"""The system architecture of TaoChronos (道乃久) as one figure, drawn from the harness as it is configured.

    python docs/figures/architecture.py              # read the harness, write architecture.json, draw the figure
    python docs/figures/architecture.py --draw-only  # draw from the architecture.json already written

Three views of one system, each answering one question (the legend is in README.md beside this file):

a  the runtime architecture — who acts (the principals), what stands between them and everything else (the kernel: one
   path to the tools, one to the state) and what they act on (tools, capabilities, plugins, stores), with the life of a
   research task numbered along its arrows;
b  the layering rule — which layer may import which (``architecture-policy.yaml``) against which layer does, counted
   from the import statements of the source, with the size of each layer;
c  the deployment — the one chat runtime in the three places it runs, and the separate paths of model calls and tool
   calls.

Every number in the figure is read from this repository (``collect``, written to ``architecture.json``): the agent
specs, the skill manifests, the tool mesh, the hook registry, the gates, the event types, the capability registry, the
evaluation suites and their invariants, the layering policy and the imports of ``src/``, the corpus catalogues
(``corpus/catalog``) and ``corpus/web/books.json``.  None is typed in by hand, so the figure cannot drift from the code without a new run of
this script showing it.

The figure is laid out in millimetres at its printed size — 7 in wide, the text width of a two-column ACM, IEEE or
USENIX page — in Arial (Liberation Sans where Arial is not installed: the two share their metrics), with DejaVu Sans
Mono for paths in the source; text is placed by its baseline.  ``save`` writes a vector PDF (TrueType fonts only,
embedded as subsets, text left live; the three Chinese characters of the name are drawn as outlines) and a 600 dpi RGB
PNG — the same bytes on every run — then checks what it wrote: page size, fonts, text sizes, stroke widths, text
leaving the page or its box, and text colliding with text.  An empty ``warnings`` list is the pass signal.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
HOME = HERE.parents[1]
DATA = HERE / "architecture.json"
NAME = "architecture"
PROFILE = "full-discovery"


# ======================================================================================================== source data
def _layering(home: Path) -> dict[str, Any]:
    """The layers of ``architecture-policy.yaml``: what each may import, what each does import (cross-layer import
    statements, read as ``taochronos governance`` reads them), and its size."""
    from taochronos.governance import PACKAGE, _imports, _layer_of, _module_of, check
    from taochronos.protocol.yamlio import load_yaml

    policy = load_yaml(home / "architecture-policy.yaml")
    prefixes: dict[str, list[str]] = {}
    for name, spec in policy["layers"].items():
        prefixes[name] = [p.replace("src/", "").replace("/", ".").removesuffix(".py").removeprefix(PACKAGE + ".")
                          .removeprefix(PACKAGE).strip(".") for p in spec["paths"]]
    src = home / "src"
    files: Counter[str] = Counter()
    lines: Counter[str] = Counter()
    imports: Counter[tuple[str, str]] = Counter()
    for path in sorted((src / PACKAGE).rglob("*.py")):
        module = _module_of(path, src)
        layer = _layer_of(module, prefixes)
        if layer is None:
            continue
        files[layer] += 1
        lines[layer] += len(path.read_text(encoding="utf-8").splitlines())
        seen: set[tuple[int, str]] = set()
        for target, line in _imports(path, module):
            if not target.startswith(PACKAGE + "."):
                continue
            to = _layer_of(target, prefixes)
            if to is None or to == layer or (line, to) in seen:
                continue
            seen.add((line, to))  # one statement importing several names of one layer counts once
            imports[(layer, to)] += 1
    report = check(home)
    order = list(policy["layers"])
    return {
        "order": order,
        "may_import": {k: list(v.get("may_import", [])) for k, v in policy["layers"].items()},
        "files": {k: files[k] for k in order},
        "lines": {k: lines[k] for k in order},
        "imports": {f"{a}>{b}": n for (a, b), n in sorted(imports.items())},
        "governance": {"files_checked": report["files_checked"], "violations": len(report["violations"]),
                       "rules": report["rules"]},
    }


def _deployment(home: Path) -> dict[str, Any]:
    """The corpora a deployed runtime reads.  ``corpus`` is the corpus as the catalogues admit it (the books a full
    build ingests: every entry marked ``ingest``, and every entry of a catalogue curated by hand, which marks none);
    ``site_store`` is the store the public site deploys, cut from it without the sources whose terms forbid passing
    their transcriptions on (``excluded``); ``browser_pack`` is what the page itself carries."""
    from taochronos.protocol.yamlio import load_yaml

    admitted: dict[str, int] = {}
    for path in sorted((home / "corpus" / "catalog").glob("*.yaml")):
        catalog = load_yaml(path)
        if isinstance(catalog, dict) and isinstance(catalog.get("books"), list):
            n = sum(1 for b in catalog["books"] if b.get("status", "ingest") == "ingest")
            if n:
                admitted[(catalog.get("source") or {}).get("id", path.stem)] = n
    store = json.loads((home / "cloud" / "store.json").read_text(encoding="utf-8"))
    books = json.loads((home / "corpus" / "web" / "books.json").read_text(encoding="utf-8"))
    return {"corpus": {"books": sum(admitted.values()), "by_source": admitted},
            "site_store": {k: store[k] for k in ("books", "passages", "characters", "excluded")},
            "browser_pack": {"witnesses": len(books), "works": len({b["work"] for b in books})}}


def collect(home: Path = HOME) -> dict[str, Any]:
    """Everything the figure draws and its legend cites, read from the repository and from a harness built on the
    default profile."""
    sys.path.insert(0, str(home / "src"))
    from taochronos.bootstrap import Harness
    from taochronos.engine.workflow import load_core_agents, load_manifests
    from taochronos.evals import SUITES
    from taochronos.evals.boundaries import INVARIANTS
    from taochronos.kernel.authority import EVENT_AUTHORITY, PRINCIPALS, RANK
    from taochronos.kernel.hooks import HookPoint
    from taochronos.kernel.memory import MemoryLayer
    from taochronos.plugins.models.openai_compat import PRESETS
    from taochronos.plugins.sandbox.isolation import REQUIRED
    from taochronos.protocol.events import EventType
    from taochronos.verification.gates import GATE_NAMES

    with tempfile.TemporaryDirectory() as tmp:  # never the user's data directory
        h = Harness.from_profile(PROFILE, home=home, data_dir=tmp, ephemeral=True)
        tools = h.tools.list()
        out: dict[str, Any] = {
            "profile": PROFILE,
            "events": {"types": len(EventType),
                       "may_emit": {p: sum(p in who for who in EVENT_AUTHORITY.values()) for p in sorted(PRINCIPALS, key=RANK.get)}},
            "agents": [{"role": r, "mode": h.specs[r].mode} for r in sorted(h.specs)],
            "core_agents": sorted(load_core_agents(home / "agents" / "core")),
            "skill_manifests": sorted(load_manifests(home / "skills" / "manifests")),
            "tools": {"total": len(tools),
                      "families": dict(Counter(t.family for t in tools).most_common()),
                      "permissions": dict(Counter(t.permission for t in tools).most_common())},
            "hooks": {"points": [p.value for p in HookPoint],
                      "installed": {p.value: h.hooks.names(p) for p in HookPoint if h.hooks.names(p)}},
            "gates": dict(GATE_NAMES),
            "capabilities": h.capabilities.capabilities(),
            "plugins": [p.removeprefix("taochronos.plugins.") for p in h.capabilities.loaded_plugins],
            "llm": {"openai_compatible_presets": len(PRESETS)},
            "sandbox": {"required_for": dict(REQUIRED)},
            "memory_layers": [m.value for m in MemoryLayer],
            "evals": {"suites": len(SUITES), "invariants": [{"id": i[0], "boundary": i[3]} for i in INVARIANTS]},
        }
    out["layers"] = _layering(home)
    out["deployment"] = _deployment(home)
    return out


# ============================================================================================================= style
MM = 1 / 25.4
PT = 25.4 / 72  # mm per point
WIDTH = 177.8  # 7 in: the text width of a two-column ACM, IEEE or USENIX page
EDGE = 0.5     # nothing is drawn nearer the page's edge: a stroke centred on the edge would lose half its width
TEXT_MIN, TEXT_MAX = 6.0, 9.0
LINE_MIN, LINE_MAX = 0.3, 1.2
S_PANEL, S_TITLE, S_SUB, S_BODY, S_NUM = 8.0, 7.2, 6.5, 6.0, 6.5
LEAD = 1.19   # line pitch, in ems
CAP = 0.72    # height of a capital, in ems (Arial and Liberation Sans: 0.716)

# Okabe–Ito, with the meanings the other figures of this repository give its colours: blue for what an agent does,
# orange for what a human does, vermillion for what can refuse, grey and black for the harness itself
INK = "#111111"
C = {"agent": "#0072B2", "human": "#E69F00", "guard": "#D55E00", "kernel": "#4D4D4D", "grey": "#707070",
     "bar": "#8C8C8C", "rule": "#C8C8C8",
     "human_ink": "#8F5E00", "guard_ink": "#B34A00"}  # the two light hues darkened until 6 pt text in them reads


def tint(color: str, f: float) -> str:
    """``color`` mixed with white: f = 0 white, f = 1 the colour itself."""
    color = color.lstrip("#")
    rgb = [int(color[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{round(255 - (255 - v) * f):02X}" for v in rgb)


FILL = {"agent": tint(C["agent"], 0.10), "human": tint(C["human"], 0.20), "kernel": "#E9E9E9", "harness": "#FAFAFA"}
DASH = (0, (3.2, 1.8))   # an external service
DOTS = (0, (2.2, 1.4))   # a read-only view, a fallback
HAN = re.compile(r"([\u2e80-\u9fff\uf900-\ufaff]+)")  # a run of Chinese characters


def _first_font(names: list[str], default: str = "DejaVu Sans") -> str:
    from matplotlib import font_manager

    have = {f.name for f in font_manager.fontManager.ttflist}
    return next((n for n in names if n in have), default)


def apply_style() -> dict[str, str]:
    import matplotlib as mpl

    mpl.use("Agg")
    fonts = {"sans": _first_font(["Arial", "Helvetica", "Liberation Sans"]),
             "cjk": _first_font(["Noto Sans CJK SC", "Source Han Sans SC", "WenQuanYi Zen Hei"], ""),
             "mono": _first_font(["DejaVu Sans Mono"])}
    mpl.rcParams.update({
        "font.family": [fonts["sans"]], "font.size": S_BODY, "text.color": INK,
        "pdf.fonttype": 42, "ps.fonttype": 42, "svg.fonttype": "none",
        "savefig.bbox": "standard", "savefig.pad_inches": 0, "savefig.facecolor": "white", "figure.facecolor": "white",
        "axes.unicode_minus": True, "path.simplify": False,
    })
    return fonts


class Canvas:
    """One page in millimetres, the origin at its top-left corner, y downwards."""

    def __init__(self, height_mm: float = 200.0) -> None:
        self.fonts = apply_style()
        import matplotlib.pyplot as plt

        self.w, self.h = WIDTH, float(height_mm)
        self.fig = plt.figure(figsize=(self.w * MM, self.h * MM))
        self.ax = self.fig.add_axes([0, 0, 1, 1])
        self.ax.set_xlim(0, self.w)
        self.ax.set_ylim(self.h, 0)
        self.ax.axis("off")
        self.fits: list[tuple[Any, float, float, float, float]] = []  # a text and the box it must stay inside
        self.notes: list[str] = []  # what could not be drawn as meant: reported with the checks
        self._renderer = None

    def finish(self, height_mm: float) -> None:
        """Cut the page to its final height (a millimetre stays a millimetre)."""
        self.h = float(height_mm)
        self.fig.set_size_inches(self.w * MM, self.h * MM)
        self.ax.set_ylim(self.h, 0)

    # ------------------------------------------------------------------------------------------------------- text
    def width(self, s: str, size: float = S_BODY, weight: str = "normal", mono: bool = False) -> float:
        """Printed width of ``s`` in millimetres."""
        import matplotlib as mpl
        from matplotlib import font_manager
        from matplotlib.backends.backend_agg import RendererAgg

        if self._renderer is None:
            self._renderer = RendererAgg(100, 100, 72)
        family = [self.fonts["mono"]] if mono else list(mpl.rcParams["font.family"])
        prop = font_manager.FontProperties(family=family, size=size, weight=weight)
        return self._renderer.get_text_width_height_descent(s, prop, ismath=False)[0] * PT

    def wrap(self, s: str, width: float, size: float = S_BODY, weight: str = "normal") -> list[str]:
        """Lines no wider than ``width`` mm; words stay whole."""
        lines: list[str] = []
        for part in s.split("\n"):
            line = ""
            for word in part.split(" "):
                trial = f"{line} {word}" if line else word
                if line and self.width(trial, size, weight) > width:
                    lines.append(line)
                    line = word
                else:
                    line = trial
            lines.append(line)
        return lines

    def text(self, x: float, y: float, s: str, size: float = S_BODY, *, weight: str = "normal", color: str = INK,
             ha: str = "left", va: str = "top", mono: bool = False, style: str = "normal", z: float = 6,
             within: tuple[float, float, float, float] | None = None) -> list[Any]:
        """Text placed by its baseline, so that its position never depends on which letters it holds: ``va`` "top"
        puts the top of its capitals at y, "middle" their middle, "baseline" the baseline.  One artist per line."""
        kw: dict[str, Any] = {"fontfamily": self.fonts["mono"]} if mono else {}
        base = y + {"top": CAP, "middle": CAP / 2, "baseline": 0.0}[va] * size * PT
        out = []
        for i, line in enumerate(s.split("\n")):
            yb = base + i * size * PT * LEAD
            runs = [r for r in HAN.split(line) if r]
            widths = [len(r) * size * PT if HAN.fullmatch(r) else self.width(r, size, weight, mono) for r in runs]
            xr = x - {"left": 0.0, "center": 0.5, "right": 1.0}[ha] * sum(widths) if len(runs) > 1 else x
            for run, w in zip(runs, widths):
                if HAN.fullmatch(run):
                    self._outline(xr, yb, run, size, color, z)
                else:
                    t = self.ax.text(xr, yb, run, fontsize=size, fontweight=weight, color=color, va="baseline",
                                     ha=ha if len(runs) == 1 else "left", fontstyle=style, zorder=z, **kw)
                    if within is not None:
                        self.fits.append((t, *within))
                    out.append(t)
                xr += w
        return out

    def _outline(self, x: float, base: float, s: str, size: float, color: str, z: float) -> None:
        """Chinese characters as outlines.  Noto Sans CJK is an OpenType font with PostScript outlines, which
        matplotlib embeds under a TrueType label that stricter PDF readers object to: drawn as shapes, the characters
        need no font in the file and look the same everywhere."""
        from matplotlib.font_manager import FontProperties
        from matplotlib.patches import PathPatch
        from matplotlib.textpath import TextPath
        from matplotlib.transforms import Affine2D

        if not self.fonts["cjk"]:
            self.notes.append(f"no font for Chinese characters is installed: {s!r} is not drawn")
            return
        path = TextPath((0, 0), s, size=size, prop=FontProperties(family=self.fonts["cjk"]))
        self.ax.add_patch(PathPatch(path, transform=Affine2D().scale(PT, -PT).translate(x, base) + self.ax.transData,
                                    facecolor=color, edgecolor="none", lw=0, zorder=z))

    def para(self, x: float, y: float, s: str, width: float, size: float = S_BODY, *, weight: str = "normal",
             color: str = INK, ha: str = "left", within: tuple[float, float, float, float] | None = None) -> float:
        """Wrapped text from the top of its first line; returns the y at which a next paragraph would start."""
        lines = self.wrap(s, width, size, weight)
        self.text(x, y, "\n".join(lines), size, weight=weight, color=color, ha=ha, within=within)
        return y + len(lines) * size * PT * LEAD

    def lead(self, x: float, y: float, head: str, first: str, second: str = "", *, size: float = S_BODY,
             head_size: float = S_TITLE, within: tuple[float, float, float, float] | None = None) -> None:
        """A bold head, a line that runs on after it on its baseline, and a second line under them."""
        base = y + CAP * head_size * PT
        self.text(x, base, head, head_size, weight="bold", va="baseline", within=within)
        self.text(x + self.width(head, head_size, "bold") + 1.5, base, first, size, va="baseline", within=within)
        if second:
            self.text(x, base + size * PT * LEAD * 1.07, second, size, va="baseline", within=within)

    # ----------------------------------------------------------------------------------------------------- shapes
    def box(self, x: float, y: float, w: float, h: float, *, fc: str = "white", ec: str = INK, lw: float = 0.6,
            r: float = 0.8, ls: Any = "-", z: float = 2) -> None:
        from matplotlib.patches import FancyBboxPatch

        self.ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}", facecolor=fc,
                                         edgecolor=ec, lw=lw, linestyle=ls, zorder=z, joinstyle="round"))

    def rect(self, x: float, y: float, w: float, h: float, *, fc: str = "white", ec: str = "none", lw: float = 0.5,
             z: float = 3) -> None:
        from matplotlib.patches import Rectangle

        self.ax.add_patch(Rectangle((x, y), w, h, facecolor=fc, edgecolor=ec, lw=lw, zorder=z))

    def line(self, pts: list[tuple[float, float]], *, color: str = INK, lw: float = 0.7, ls: Any = "-", z: float = 4) -> None:
        xs, ys = zip(*pts)
        self.ax.plot(xs, ys, color=color, lw=lw, ls=ls, zorder=z, solid_capstyle="butt", solid_joinstyle="miter",
                     dash_capstyle="butt")

    def arrow(self, pts: list[tuple[float, float]], *, color: str = INK, lw: float = 0.7, ls: Any = "-",
              both: bool = False, head: float = 1.45, z: float = 4) -> None:
        """A polyline with a filled head at its end (and at its start when ``both``)."""
        from matplotlib.patches import Polygon

        pts = [(float(px), float(py)) for px, py in pts]

        def tip(p: tuple[float, float], q: tuple[float, float]) -> tuple[float, float]:
            """The head at ``p`` of a line arriving from ``q``; returns where the shaft stops."""
            dx, dy = p[0] - q[0], p[1] - q[1]
            n = (dx * dx + dy * dy) ** 0.5
            ux, uy = dx / n, dy / n
            bx, by = p[0] - ux * head, p[1] - uy * head
            hw = head * 0.40
            self.ax.add_patch(Polygon([p, (bx - uy * hw, by + ux * hw), (bx + uy * hw, by - ux * hw)], closed=True,
                                      facecolor=color, edgecolor="none", zorder=z + 1))
            return (p[0] - ux * head * 0.85, p[1] - uy * head * 0.85)

        end = tip(pts[-1], pts[-2])
        start = tip(pts[0], pts[1]) if both else pts[0]
        self.line([start, *pts[1:-1], end], color=color, lw=lw, ls=ls, z=z)

    def circle(self, x: float, y: float, r: float, *, fc: str = INK, ec: str = "none", lw: float = 0.5, z: float = 7) -> None:
        from matplotlib.patches import Circle

        self.ax.add_patch(Circle((x, y), r, facecolor=fc, edgecolor=ec, lw=lw, zorder=z))

    def badge(self, x: float, y: float, n: int | str, *, r: float = 1.45) -> None:
        """A numbered step."""
        self.circle(x, y, r, fc=INK, ec="white", z=8)
        self.text(x, y, str(n), S_NUM, weight="bold", color="white", ha="center", va="middle", z=9)

    def guard(self, x: float, y: float, s: float = 1.05) -> None:
        """A guard: a deterministic check that can refuse what passes it."""
        from matplotlib.patches import Polygon

        self.ax.add_patch(Polygon([(x, y - s), (x + s, y), (x, y + s), (x - s, y)], closed=True, facecolor=C["guard"],
                                  edgecolor="white", lw=0.4, zorder=8))

    def cylinder(self, x: float, y: float, w: float, h: float, *, fc: str = "white", ec: str = INK, lw: float = 0.6,
                 ry: float = 0.9, z: float = 2) -> None:
        """A store."""
        import numpy as np
        from matplotlib.patches import Ellipse, Polygon

        t = np.linspace(0, np.pi, 40)
        cx, top, bot = x + w / 2, y + ry, y + h - ry
        xs = np.concatenate([[x], cx - (w / 2) * np.cos(t), [x + w]])
        ys = np.concatenate([[top], bot + ry * np.sin(t), [top]])
        self.ax.add_patch(Polygon(np.c_[xs, ys], closed=True, facecolor=fc, edgecolor="none", zorder=z))
        self.ax.plot(xs, ys, color=ec, lw=lw, zorder=z + 0.1, solid_joinstyle="round")
        self.ax.add_patch(Ellipse((cx, top), w, 2 * ry, facecolor=fc, edgecolor=ec, lw=lw, zorder=z + 0.2))

    def titled(self, x: float, y: float, w: float, h: float, title: str, *, side: str = "", side_mono: bool = False,
               side_color: str = "", side_style: str = "normal", fc: str = "white", ec: str = INK, lw: float = 0.7,
               ls: Any = "-", size: float = S_TITLE, z: float = 2, pad: float = 1.3) -> float:
        """A box with its name at the top left and, on the same baseline at the top right, what it is in the source or
        in the figure.  Returns the baseline."""
        self.box(x, y, w, h, fc=fc, ec=ec, lw=lw, ls=ls, z=z)
        base = y + 0.95 + CAP * size * PT
        self.text(x + pad, base, title, size, weight="bold", va="baseline", within=(x, y, w, h))
        if side:
            self.text(x + w - pad, base, side, S_BODY, mono=side_mono, color=side_color or C["grey"], ha="right",
                      va="baseline", style=side_style, within=(x, y, w, h))
        return base

    def panel(self, x: float, y: float, letter: str, title: str) -> None:
        base = y + CAP * S_PANEL * PT
        self.text(x, base, f"({letter})", S_PANEL, weight="bold", va="baseline")
        self.text(x + self.width(f"({letter})", S_PANEL, "bold") + 1.3, base, title, S_TITLE, va="baseline")


def _n(n: int) -> str:
    """A count as the figure writes it: 2 038 497 → 2.04 M, 45 470 → 45.5 k, 3 046 → 3.0 k."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.3g} M"
    if n >= 1000:
        return f"{n / 1000:.1f} k"
    return f"{n}"


# ========================================================================================================== panel a
def panel_a(cv: Canvas, d: dict[str, Any], top: float) -> float:
    """The runtime architecture: principals above, the kernel between, resources below; the life of a research task
    numbered along the arrows.  Returns the y of the panel's bottom."""
    modes = Counter(a["mode"] for a in d["agents"])
    tools, hooks, ev = d["tools"], d["hooks"], d["events"]
    cv.panel(EDGE, top, "a", "Runtime architecture: principals reach tools and state only through the kernel")

    # ---- three zones, left to right: what is not trusted, what is code, who decides
    LX0, LX1 = EDGE, 26.0            # stochastic intelligence
    LW = LX1 - LX0
    HX0, HX1 = 31.0, 149.4           # the harness
    X0, X1 = 33.5, 147.5             # what stands inside it
    RX0 = 155.1                      # human authority
    RW = WIDTH - EDGE - RX0
    zb = top + 6.9                   # the baseline of the zones' names
    cv.text(LX0, zb, "Stochastic intelligence", S_SUB, weight="bold", color=C["agent"], va="baseline")
    cv.text(HX0, zb, "Deterministic harness", S_SUB, weight="bold", color=C["kernel"], va="baseline")
    cv.text(HX0 + cv.width("Deterministic harness", S_SUB, "bold") + 1.6, zb,
            "TaoChronos (道乃久): state, ordering, permissions, verification and stopping are code",
            color=C["kernel"], va="baseline")
    cv.text(RX0, zb, "Human authority", S_SUB, weight="bold", color=C["human_ink"], va="baseline")

    FY0 = top + 8.4
    DR_Y, DR_H = FY0 + 2.0, 7.6                 # what drives work
    PR_Y, PR_H = DR_Y + DR_H + 4.3, 18.4        # the principals
    KB_Y = PR_Y + PR_H + 6.7                    # the kernel
    KX_Y, KX_H = KB_Y + 4.0, 17.0
    KB_H = 4.0 + KX_H + 4.5
    TM_Y, RW_H = KB_Y + KB_H + 2.3, 7.3         # tools; capabilities and plugins
    CP_Y = TM_Y + RW_H + 1.0
    FY1 = CP_Y + RW_H + 1.9
    ST_Y, ST_H = FY1 + 2.9, 7.7                 # stores and services
    cv.box(HX0, FY0, HX1 - HX0, FY1 - FY0, fc=FILL["harness"], ec=C["kernel"], lw=0.9, r=1.5, z=1)
    cv.para(LX0, zb + 1.9, "untrusted: a model's reply or program is input, checked before anything is committed",
            LW, color=C["agent"])

    # ---- what drives work through the kernel: three front ends
    EX0 = X0 + 55.5
    drivers = [(X0, 24.5, "Chat runtime", "tools for a chat model", ""),
               (X0 + 26.5, 27.0, "Skill workflow", f"{len(d['skill_manifests'])} skills · {len(d['core_agents'])} core agents", ""),
               (EX0, X1 - EX0, "Research engine", "rounds → task DAG → stop rule → verdict → report", "engine/")]
    for x, w, title, body, tag in drivers:
        cv.titled(x, DR_Y, w, DR_H, title, side=tag, side_mono=True)
        cv.text(x + 1.3, DR_Y + 4.3, body, within=(x, DR_Y, w, DR_H))

    # ---- the principals
    AW = 72.0
    ab = cv.titled(X0, PR_Y, AW, PR_H, "Agents propose", side="agents/", side_mono=True, fc=FILL["agent"], ec=C["agent"], lw=0.8)
    cv.text(X0 + 1.3 + cv.width("Agents propose", S_TITLE, "bold") + 1.6, ab, "principal: agent", color=C["agent"], va="baseline")
    sub = [(f"AgentSpec × {len(d['agents'])}", "YAML: role, tools, permissions, output schema, budget"),
           ("Cognitive router", "routes by task, not vendor; falls back to rules"),
           ("Agent loop", f"context view in,\ntyped output out;\n{modes['hybrid']} may call a model")]
    sw, sg, sy, sh = 21.6, 2.3, PR_Y + 4.6, PR_H - 6.0
    for i, (title, body) in enumerate(sub):
        x = X0 + 1.8 + i * (sw + sg)
        cv.box(x, sy, sw, sh, fc="white", ec=C["agent"], lw=0.5, r=0.6, z=3)
        cv.text(x + 1.0, sy + 0.95, title, S_SUB, weight="bold", within=(x, sy, sw, sh))
        cv.para(x + 1.0, sy + 3.95, body, sw - 2.0, within=(x, sy, sw, sh))
        if i:
            cv.arrow([(x - sg, sy + sh / 2), (x, sy + sh / 2)], color=C["agent"], lw=0.6, head=1.2)

    VX, VW = X0 + AW + 4.0, X1 - X0 - AW - 4.0
    cv.titled(VX, PR_Y, VW, PR_H, "Validators grade", lw=0.8)
    cv.text(VX + 1.3, PR_Y + 4.25, "principal: validator", color=C["kernel"])
    gates = list(d["gates"])
    gg = 0.36
    gw = (VW - 2.6 - (len(gates) - 1) * gg) / len(gates)
    for i, g in enumerate(gates):
        human, x = g == "G7", VX + 1.3 + i * (gw + gg)
        cv.box(x, PR_Y + 7.2, gw, 3.2, fc=FILL["human"] if human else "#EFEFEF",
               ec=C["human"] if human else C["kernel"], lw=0.5, r=0.4, z=3)
        cv.text(x + gw / 2, PR_Y + 8.8, g, ha="center", va="middle", color=C["human_ink"] if human else INK,
                weight="bold" if human else "normal")
    cv.para(VX + 1.3, PR_Y + 11.6, "scores and ranks; objections closed by re-run; the contract's verdict",
            VW - 2.6, within=(VX, PR_Y, VW, PR_H))

    # ---- stochastic intelligence, outside the harness
    cv.titled(LX0, PR_Y, LW, PR_H, "Language models", fc=FILL["agent"], ec=C["agent"], lw=0.8, ls=DASH)
    cv.para(LX0 + 1.3, PR_Y + 4.25, "reached only through the llm capability: provider plugins, "
            f"{d['llm']['openai_compatible_presets']} OpenAI-compatible presets",
            LW - 2.4, within=(LX0, PR_Y, LW, PR_H))
    cv.titled(LX0, KX_Y, LW, KX_H, "Code sandbox", fc=FILL["agent"], ec=C["agent"], lw=0.8)
    cv.para(LX0 + 1.3, KX_Y + 4.25, f"model-written programs run at the {d['sandbox']['required_for']['model']} tier: no network, "
            "no credentials; tools only by RPC", LW - 2.4, within=(LX0, KX_Y, LW, KX_H))

    # ---- and what checks that the boundaries drawn here hold
    EV_H = CP_Y + RW_H - TM_Y
    cv.titled(LX0, TM_Y, LW, EV_H, "Evaluation", side="evals/", side_mono=True)
    cv.para(LX0 + 1.3, TM_Y + 4.25, f"{len(d['evals']['invariants'])} invariants run as probes against the boundaries drawn here; "
            f"{d['evals']['suites']} suites in all", LW - 2.4, within=(LX0, TM_Y, LW, EV_H))
    cv.arrow([(LX1, TM_Y + EV_H / 2), (HX0, TM_Y + EV_H / 2)], lw=0.6)

    # ---- human authority
    SC_Y, SC_H = FY0 + 0.4, 12.2
    cv.titled(RX0, SC_Y, RW, SC_H, "Scientist asks", fc=FILL["human"], ec=C["human"], lw=0.8)
    cv.para(RX0 + 1.3, SC_Y + 4.25, "a research contract: question, scope, hold-out, acceptance", RW - 2.4,
            within=(RX0, SC_Y, RW, SC_H))
    cv.titled(RX0, PR_Y, RW, PR_H, "Expert decides", fc=FILL["human"], ec=C["human"], lw=0.8)
    cv.text(RX0 + 1.3, PR_Y + 4.25, "principal: human", color=C["human_ink"])
    cv.para(RX0 + 1.3, PR_Y + 7.0, "alone sets gate G7; closes interpretive objections; approves changes",
            RW - 2.4, within=(RX0, PR_Y, RW, PR_H))

    # ---- the kernel: one path for reads, one for writes
    cv.box(X0, KB_Y, X1 - X0, KB_H, fc=FILL["kernel"], ec=C["kernel"], lw=0.8, r=1.0, z=1.5)
    kb = KB_Y + 0.8 + CAP * S_TITLE * PT
    cv.text(X0 + 1.5, kb, "Kernel mediates and records", S_TITLE, weight="bold", va="baseline")
    cv.text(X1 - 1.5, kb, "kernel/", mono=True, color=C["grey"], ha="right", va="baseline")
    # reads: the tool scheduler
    SX, SW_ = X0 + 2.0, 44.6
    cv.titled(SX, KX_Y, SW_, KX_H, "Tool scheduler", side="read path", side_color=C["kernel"], side_style="italic")
    rail = [("step", "permission · argument schema · budget"),
            ("guard", "scope guard on the arguments"),
            ("step", "execute on scoped capability views"),
            ("guard", "result firewall, else quarantine"),
            ("step", "receipt: hashes of arguments and result")]
    ry0, pitch, rx = KX_Y + 5.15, 2.5, SX + 2.3
    cv.line([(rx, ry0), (rx, ry0 + pitch * (len(rail) - 1))], color=C["kernel"], lw=0.6, z=5)
    for i, (kind, label) in enumerate(rail):
        y = ry0 + i * pitch
        if kind == "guard":
            cv.guard(rx, y, 0.95)
        else:
            cv.circle(rx, y, 0.6, fc="white", ec=C["kernel"], lw=0.6)
        cv.text(rx + 2.0, y, label, va="middle", color=C["guard_ink"] if kind == "guard" else INK,
                within=(SX, KX_Y, SW_, KX_H))
    # writes: transaction → reducer → event log → state
    WX = SX + SW_ + 4.0
    WW = X1 - 2.0 - WX
    cv.titled(WX, KX_Y, WW, KX_H, "Session and reducer", side="write path", side_color=C["kernel"], side_style="italic")
    nodes = [("Transaction", 14.8, "atomic batch,\ncommit marker"), ("Reducer", 11.8, "authority,\ninvariants"),
             ("Event log", 12.6, f"{ev['types']} event types"), ("State", 11.4, "one research\nobject")]
    ng = (WW - 3.4 - sum(n[1] for n in nodes)) / 3
    nx, ny, nh = WX + 1.7, KX_Y + 4.4, 3.4
    for name, w, note in nodes:
        if name == "Event log":       # a log: cells, the batch being appended filled
            n = 8
            for k in range(n):
                cv.rect(nx + k * w / n, ny, w / n, nh, fc=C["kernel"] if k >= n - 3 else "white", ec=C["kernel"])
            cv.text(nx + w / 2, ny + nh + 0.95, name, S_SUB, weight="bold", ha="center")
            cv.text(nx + w / 2, ny + nh + 0.95 + S_SUB * PT * LEAD, note, ha="center", within=(WX, KX_Y, WW, KX_H))
        else:
            cv.box(nx, ny, w, nh, fc="white", ec=C["kernel"], lw=0.6, r=0.5, z=3)
            cv.text(nx + w / 2, ny + nh / 2, name, S_SUB, weight="bold", ha="center", va="middle")
            cv.text(nx + w / 2, ny + nh + 1.0, note, ha="center", within=(WX, KX_Y, WW, KX_H))
        if name != "State":
            cv.arrow([(nx + w, ny + nh / 2), (nx + w + ng, ny + nh / 2)], color=C["kernel"], lw=0.6, head=1.2)
        nx += w + ng
    cv.text(WX + 1.7, KX_Y + KX_H - 1.15, "state = reduce(events), checked by replay every round", va="baseline",
            within=(WX, KX_Y, WW, KX_H))
    # the rest of the kernel
    ky = KX_Y + KX_H + 2.25
    sx5 = SX + 6.0
    cv.text(sx5 + 4.6, ky, f"policy · budgets (reserve → settle) · hooks at {len(hooks['points'])} points · context views · "
            f"memory {d['memory_layers'][0]}–{d['memory_layers'][-1]} · stop rule", va="middle")

    # ---- resources: tools, capabilities and plugins, stores
    cv.box(X0, TM_Y, X1 - X0, RW_H, fc="white", ec=INK, lw=0.7)
    cv.text(X1 - 1.3, TM_Y + 0.95 + CAP * S_TITLE * PT, "tools/", mono=True, color=C["grey"], ha="right", va="baseline")
    cv.lead(X0 + 1.3, TM_Y + 0.95, "Tool mesh", f"{tools['total']} tools in {len(tools['families'])} families, "
            f"each behind one of {len(tools['permissions'])} permissions",
            ", ".join(f"{k} {v}" for k, v in tools["families"].items()), within=(X0, TM_Y, X1 - X0, RW_H))
    plugins = Counter(p.split(".")[0] for p in d["plugins"])
    cv.box(X0, CP_Y, X1 - X0, RW_H, fc="white", ec=INK, lw=0.7)
    cv.text(X1 - 1.3, CP_Y + 0.95 + CAP * S_TITLE * PT, "plugins/", mono=True, color=C["grey"], ha="right", va="baseline")
    cv.lead(X0 + 1.3, CP_Y + 0.95, "Capability registry", f"{len(d['capabilities'])} provider-neutral capabilities, "
            f"implemented by {len(d['plugins'])} plugins loaded from a profile",
            ", ".join(f"{k} × {v}" if v > 1 else k for k, v in plugins.items()), within=(X0, CP_Y, X1 - X0, RW_H))
    stores = [("Corpus store", "SQLite + FTS5", 24.0, "store"), ("Domain packs", "lexicon, terms, ontology", 26.0, "store"),
              ("User data", "de-identified, local", 23.0, "store"), ("Modern evidence", "PubMed · OMOP", 23.0, "service"),
              ("Page images", "IIIF", 16.0, "service")]
    stg = (HX1 - HX0 - sum(s[2] for s in stores)) / (len(stores) - 1)
    x = HX0
    for name, note, w, kind in stores:
        if kind == "store":
            cv.cylinder(x, ST_Y, w, ST_H, ec=INK, lw=0.7, ry=1.0)
            ty = ST_Y + 2.3
        else:
            cv.box(x, ST_Y + 0.5, w, ST_H - 0.5, fc="white", ec=INK, lw=0.7, ls=DASH)
            ty = ST_Y + 1.7
        cv.text(x + w / 2, ty, name, S_SUB, weight="bold", ha="center")
        cv.text(x + w / 2, ty + 2.75, note, ha="center", within=(x, ST_Y, w, ST_H + 0.3))
        cv.arrow([(x + w / 2, CP_Y + RW_H), (x + w / 2, ST_Y + (0.0 if kind == "store" else 0.5))], lw=0.6, head=1.2)
        x += w + stg

    # ---- the life of a research task
    y1 = DR_Y + 2.2
    cv.arrow([(RX0, y1), (X1, y1)])                                        # 1 the contract
    cv.badge((RX0 + X1) / 2 + 0.75, y1, 1)
    y1b = DR_Y + 5.6
    cv.arrow([(X1, y1b), (RX0, y1b)], lw=0.6)                              # the report, past the publish guard
    cv.guard((RX0 + X1) / 2 - 0.75, y1b)
    ax2, y2 = EX0 + 8.5, (DR_Y + DR_H + PR_Y) / 2 - 0.25
    cv.arrow([(ax2, DR_Y + DR_H), (ax2, PR_Y)])                            # 2 plan and spawn
    cv.badge(ax2, y2, 2)
    cv.text(ax2 + 2.3, y2, "plan, spawn", va="middle")
    vx2 = VX + VW - 20.5
    cv.arrow([(vx2, DR_Y + DR_H), (vx2, PR_Y)], lw=0.6)
    cv.text(vx2 + 1.2, y2, "validator tasks", va="middle")
    for x, w, *_ in drivers[:2]:
        cv.arrow([(x + w / 2, DR_Y + DR_H), (x + w / 2, PR_Y)], lw=0.6)
    my = PR_Y + PR_H / 2
    cv.arrow([(LX1, my), (X0, my)], both=True)                             # 3 the model
    cv.badge((LX1 + X0) / 2, my, 3)
    g0 = PR_Y + PR_H
    gy = g0 + 2.45
    cx = X0 + 30.0
    cv.arrow([(cx, KB_Y), (cx, g0)], lw=0.6, ls=DOTS)                       # the context view
    cv.text(cx - 1.3, gy, "read-only context view", va="middle", ha="right")
    tx4 = SX + SW_ - 6.0
    cv.arrow([(tx4, g0), (tx4, KX_Y)], both=True)                          # 4 a tool call
    cv.badge(tx4, gy, 4)
    cv.text(tx4 + 2.3, gy, "tool call", va="middle")
    tx6 = WX + 8.0
    cv.arrow([(tx6, g0), (tx6, KX_Y)])                                     # 6 the commit
    cv.badge(tx6, gy, 6)
    cv.text(tx6 + 2.3, gy, "commit", va="middle")
    cv.guard(tx6, gy + 2.95)
    tx7 = VX + 9.0
    cv.arrow([(tx7, g0), (tx7, KX_Y)])                                     # 7 grading
    cv.badge(tx7, gy, 7)
    cv.text(tx7 + 2.3, gy, "grade", va="middle")
    tx8, ex = WX + WW - 16.0, RX0 + RW / 2                                 # 8 the expert's decision
    cv.arrow([(ex, g0), (ex, gy + 2.95), (tx8, gy + 2.95), (tx8, KX_Y)])
    cv.badge(ex, gy, 8)
    cv.text(ex + 2.3, gy, "decide", va="middle")
    cv.arrow([(sx5, KX_Y + KX_H), (sx5, TM_Y)])                            # 5 the tool runs
    cv.badge(sx5, ky, 5)
    cv.arrow([(LX1, KX_Y + KX_H / 2), (SX, KX_Y + KX_H / 2)], both=True, lw=0.6)   # code mode: run, and call back

    # ---- key
    kx, ky0, kp = RX0, KB_Y + 5.6, 3.2
    cv.text(kx, ky0 - 3.9, "Key", S_SUB, weight="bold")
    keys = ["agent principal", "kernel", "human principal", "external service", "store", "guard: can refuse",
            "step of a task", "request, write", "request and reply", "read-only, fallback"]
    for i, label in enumerate(keys):
        y = ky0 + i * kp
        if i < 4:
            fc, ec = [(FILL["agent"], C["agent"]), (FILL["kernel"], C["kernel"]), (FILL["human"], C["human"]), ("white", INK)][i]
            cv.box(kx, y - 1.0, 3.4, 2.0, fc=fc, ec=ec, lw=0.6, r=0.4, ls=(0, (2.4, 1.4)) if i == 3 else "-")
        elif i == 4:
            cv.cylinder(kx, y - 1.15, 3.4, 2.3, ec=INK, lw=0.6, ry=0.5)
        elif i == 5:
            cv.guard(kx + 1.7, y, 0.95)
        elif i == 6:
            cv.badge(kx + 1.7, y, "n", r=1.3)
        else:
            cv.arrow([(kx, y), (kx + 3.4, y)], head=1.2, both=i == 8, lw=0.6 if i == 9 else 0.7, ls=DOTS if i == 9 else "-")
        cv.text(kx + 4.6, y, label, va="middle")
    return ST_Y + ST_H + 0.5


# ========================================================================================================== panel b
def panel_b(cv: Canvas, d: dict[str, Any], x0: float, top: float) -> float:
    """The layering rule as a dependency matrix: a row imports its columns.  A disc is drawn where the source does
    import (its area the number of import statements), a ring where the policy allows an import nobody makes, and
    nothing where the policy forbids one; beside each row, the size of the layer."""
    L = d["layers"]
    order, may = L["order"], L["may_import"]
    made = {tuple(k.split(">")): v for k, v in L["imports"].items()}
    n = len(order)
    cv.panel(x0, top, "b", "Layering: imports allowed and imports made")
    cw, ch = 2.9, 2.55
    gx, gy = x0 + 18.2, top + 9.7
    bx = gx + n * cw + 2.4                        # the bars of size
    hb = top + 5.9
    cv.text(x0, hb, "layer", color=C["kernel"], va="baseline")
    cv.text(gx, hb, "imports from layer", color=C["kernel"], va="baseline")
    cv.text(bx, hb, "lines of code", color=C["kernel"], va="baseline")
    cv.rect(gx, gy, n * cw, n * ch, fc="white", z=1.5)
    biggest, longest = max(made.values()), max(L["lines"].values())
    for i, name in enumerate(reversed(order)):
        row = n - i                               # the layer's number: 1 imports nothing
        y = gy + i * ch
        core = name == "kernel"
        if core:
            cv.rect(x0, y, bx + 17.4 - x0, ch, fc=FILL["kernel"], z=1.6)
        cv.text(x0 + 2.9, y + ch / 2, str(row), ha="right", va="middle", color=C["kernel"])
        cv.text(x0 + 4.0, y + ch / 2, name, va="middle", weight="bold" if core else "normal")
        cv.text(gx + (row - 0.5) * cw, gy - 0.9, str(row), ha="center", va="baseline", color=C["kernel"])
        for j, to in enumerate(order):
            cx, cy = gx + (j + 0.5) * cw, y + ch / 2
            count = made.get((name, to), 0)
            allowed = "*" in may[name] or to in may[name]
            if to == name:
                cv.rect(gx + j * cw, y, cw, ch, fc=C["rule"], z=2)
            elif count and allowed:
                cv.circle(cx, cy, 0.30 + 0.80 * (count / biggest) ** 0.5, fc=INK, z=5)
            elif count:                            # an import the policy forbids: none while governance passes
                cv.line([(cx - 0.7, cy - 0.7), (cx + 0.7, cy + 0.7)], color=C["guard"], lw=1.0, z=5)
                cv.line([(cx - 0.7, cy + 0.7), (cx + 0.7, cy - 0.7)], color=C["guard"], lw=1.0, z=5)
            elif allowed:
                cv.circle(cx, cy, 0.42, fc="white", ec=C["bar"], lw=0.5, z=5)
        lines = L["lines"][name]
        cv.rect(bx, y + 0.5, 9.2 * lines / longest, ch - 1.0, fc=INK if core else C["bar"], z=3)
        cv.text(bx + 9.2 * lines / longest + 0.8, y + ch / 2, _n(lines), va="middle", weight="bold" if core else "normal")
    for k in range(n + 1):                        # the grid
        cv.line([(gx, gy + k * ch), (gx + n * cw, gy + k * ch)], color=C["rule"], lw=0.3, z=2.5)
        cv.line([(gx + k * cw, gy), (gx + k * cw, gy + n * ch)], color=C["rule"], lw=0.3, z=2.5)
    y = gy + n * ch + 2.2
    cv.circle(x0 + 1.0, y, 0.9, fc=INK, z=5)
    cv.text(x0 + 2.6, y, "import made (area: statements)", va="middle")
    cv.circle(x0 + 36.6, y, 0.42, fc="white", ec=C["bar"], lw=0.5, z=5)
    cv.text(x0 + 37.9, y, "allowed, unused", va="middle")
    cv.text(x0 + 55.0, y, "blank: forbidden", va="middle")
    allowed_pairs = sum(n - 1 if "*" in v else len([t for t in v if t != k]) for k, v in may.items())
    cv.text(x0, y + 2.8, f"{sum(made.values())} cross-layer imports on {sum(1 for v in made.values() if v)} of "
            f"{allowed_pairs} allowed pairs; {L['governance']['violations']} violations, checked in CI", va="middle")
    return y + 4.3


# ========================================================================================================== panel c
def panel_c(cv: Canvas, d: dict[str, Any], x0: float, top: float) -> float:
    """The deployment: the chat runtime (the harness of panel a, as the tools of the model a page talks to) in the
    three places it runs, and the two separate paths of a conversation: model calls and tool calls."""
    dep = d["deployment"]
    pack, corpus = dep["browser_pack"], dep["corpus"]
    cv.panel(x0, top, "c", "Deployment: one chat runtime in three places; model calls and tool calls travel apart")
    c1w, g1, c2w, g2 = 27.0, 12.3, 27.6, 8.0
    c1x = x0
    c2x = c1x + c1w + g1
    c3x = c2x + c2w + g2
    c3w = WIDTH - EDGE - c3x
    hA, hB, hC = 7.3, 9.9, 9.9
    rA = top + 8.4
    rB = rA + hA + 2.2
    rC = rB + hB + 4.3
    py0 = rA - 2.4                               # the page and the model providers stand a little taller
    blue = C["agent"]

    def named(x: float, y: float, w: float, h: float, title: str, place: str = "", *, mono: bool = False, **kw: Any) -> None:
        cv.box(x, y, w, h, **kw)
        base = y + 0.95 + CAP * S_SUB * PT
        cv.text(x + 1.2, base, title, S_BODY if mono else S_SUB, weight="bold", mono=mono, va="baseline", within=(x, y, w, h))
        if place:
            cv.text(x + w - 1.2, base, place, color=C["grey"], ha="right", va="baseline", within=(x, y, w, h))

    def runtime(x: float, y: float, after: str = "") -> None:
        """The mark of a place where the chat runtime runs."""
        w = cv.width("Chat runtime", S_BODY, "bold") + 1.6
        cv.box(x, y - 1.35, w, 2.7, fc=FILL["kernel"], ec=C["kernel"], lw=0.5, r=0.5, z=3)
        cv.text(x + 0.8, y, "Chat runtime", weight="bold", va="middle")
        if after:
            cv.text(x + w + 1.0, y, after, va="middle")

    # in the browser
    ph = rB + hB - py0
    named(c1x, py0, c1w, ph, "Page", "browser", lw=0.7)
    yp = cv.para(c1x + 1.2, py0 + 3.9, "chat interface and agent loop: the model asks, a runtime runs its tool calls",
                 c1w - 2.4, within=(c1x, py0, c1w, ph))
    cv.para(c1x + 1.2, yp + 1.0, "every cited passage is checked against its source", c1w - 2.4, within=(c1x, py0, c1w, ph))
    named(c1x, rC, c1w, hC, "Web Worker", "browser", lw=0.7)
    runtime(c1x + 1.2, rC + 4.95, "Pyodide")
    cv.text(c1x + 1.2, rC + 7.85, f"{pack['witnesses']} witnesses, {pack['works']} works", va="middle", within=(c1x, rC, c1w, hC))
    # at the edge, or on a machine of one's own
    named(c2x, rA, c2w, hA, "Relay Worker", "Cloudflare", lw=0.7)
    cv.text(c2x + 1.2, rA + 4.1, "keeps the key; sets quotas", within=(c2x, rA, c2w, hA))
    named(c2x, rB, c2w, hB, "Site Worker", "Cloudflare", lw=0.7)
    cv.para(c2x + 1.2, rB + 4.0, "site, API allow-list, rate limits, sentinel", c2w - 2.4, within=(c2x, rB, c2w, hB))
    named(c2x, rC, c2w, hC, "taochronos serve", mono=True, lw=0.7)
    runtime(c2x + 1.2, rC + 4.95)
    cv.text(c2x + 1.2, rC + 7.85, "your machine, your corpus", va="middle", within=(c2x, rC, c2w, hC))
    # behind them
    named(c3x, py0, c3w, rA + hA - py0, "Model providers", fc=FILL["agent"], ec=blue, lw=0.8, ls=DASH)
    cv.para(c3x + 1.2, py0 + 3.9, "the default service's, or one the visitor names", c3w - 2.4,
            within=(c3x, py0, c3w, rA + hA - py0))
    named(c3x, rB, c3w, hB, "Container", "Cloudflare", lw=0.7)
    runtime(c3x + 1.2, rB + 4.95)
    cv.text(c3x + 1.2, rB + 7.85, f"{corpus['books']} books, on demand", va="middle", within=(c3x, rB, c3w, hB))
    cv.cylinder(c3x, rC - 0.6, c3w, hC + 0.6, ec=INK, lw=0.7, ry=1.0)
    db = rC + 1.75 + CAP * S_SUB * PT
    cv.text(c3x + 1.2, db, "D1 backup", S_SUB, weight="bold", va="baseline")
    cv.text(c3x + c3w - 1.2, db, "Cloudflare", color=C["grey"], ha="right", va="baseline")
    cv.para(c3x + 1.2, rC + 4.75, "the tools in JavaScript, the corpus in SQL", c3w - 2.4, within=(c3x, rC, c3w, hC))

    # model calls: through the relay, which adds the key, or straight to a provider with the visitor's own
    e1, e2 = c1x + c1w, c2x + c2w
    ym = rA + hA / 2
    cv.arrow([(e1, ym), (c2x, ym)], color=blue)
    cv.text((e1 + c2x) / 2 - 0.5, ym - 0.9, "model calls", color=blue, ha="center", va="baseline")
    cv.arrow([(e2, ym), (c3x, ym)], color=blue)
    yd = rA - 1.2
    cv.arrow([(e1, yd), (c3x, yd)], color=blue, lw=0.6)
    cv.text(c2x + c2w / 2, yd - 0.9, "with the visitor's own key", color=blue, ha="center", va="baseline")
    # tool calls: to the site's server, to one's own, or to the worker in the page
    yt = rB + 3.0
    cv.arrow([(e1, yt), (c2x, yt)])
    cv.text((e1 + c2x) / 2 - 0.5, yt - 0.9, "tool calls", ha="center", va="baseline")
    cv.arrow([(e2, yt), (c3x, yt)])
    yf, mid = rB + 7.0, rB + hB + 2.15
    cv.arrow([(e2, yf), (e2 + 4.2, yf), (e2 + 4.2, rC + hC / 2), (c3x, rC + hC / 2)], lw=0.6, ls=DOTS)
    cv.text(e2 + 3.2, mid, "no container", ha="right", va="middle")
    cv.arrow([(e1, yf), (e1 + 4.8, yf), (e1 + 4.8, rC + hC / 2), (c2x, rC + hC / 2)], lw=0.6)
    xf = c1x + 6.0
    cv.arrow([(xf, rB + hB), (xf, rC)], lw=0.6, ls=DOTS)
    cv.text(xf + 1.3, mid, "if no server answers", va="middle")
    return rC + hC + 0.5


# ======================================================================================================== output, QC
def qc(cv: Canvas) -> dict[str, Any]:
    """Text sizes, stroke widths, text leaving the page or its box, text colliding with text."""
    from itertools import combinations

    from matplotlib.collections import Collection
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    from matplotlib.text import Text

    fig = cv.fig
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    warnings: list[str] = list(cv.notes)
    texts = [t for t in fig.findobj(Text) if t.get_visible() and t.get_text().strip()]
    sizes = sorted({round(t.get_fontsize(), 2) for t in texts})
    for t in texts:
        if not (TEXT_MIN - 1e-6 <= t.get_fontsize() <= TEXT_MAX + 1e-6):
            warnings.append(f"text {t.get_text()[:40]!r} is {t.get_fontsize()} pt ({TEXT_MIN:g}–{TEXT_MAX:g} pt)")
    widths: set[float] = set()
    for a in fig.findobj(lambda o: isinstance(o, (Line2D, Patch, Collection))):
        if not a.get_visible() or a is fig.patch or a is cv.ax.patch:
            continue
        if isinstance(a, Patch):
            ec = a.get_edgecolor()
            lws = [a.get_linewidth()] if ec is not None and ec[3] > 0 else []
        elif isinstance(a, Collection):
            lws = [float(v) for v in a.get_linewidths()] if len(a.get_edgecolors()) else []
        else:
            lws = [a.get_linewidth()] if a.get_linestyle() not in ("None", "none", "") else []
        for lw in lws:
            if lw > 0:
                widths.add(round(lw, 3))
                if not (LINE_MIN - 1e-6 <= lw <= LINE_MAX + 1e-6):
                    warnings.append(f"stroke of {lw:.2f} pt on {type(a).__name__} ({LINE_MIN:g}–{LINE_MAX:g} pt)")
    fb = fig.bbox
    boxes = []
    for t in texts:
        bb = t.get_window_extent(renderer)
        if bb.width and bb.height:
            if bb.x0 < fb.x0 - 1 or bb.y0 < fb.y0 - 1 or bb.x1 > fb.x1 + 1 or bb.y1 > fb.y1 + 1:
                warnings.append(f"text {t.get_text()[:40]!r} leaves the page")
            boxes.append((t, bb))
    to_px = cv.ax.transData.transform
    for t, x, y, w, h in cv.fits:
        bb = t.get_window_extent(renderer)
        (x0, y1), (x1, y0) = to_px((x, y)), to_px((x + w, y + h))  # y runs downwards on the page
        over = max(x0 - bb.x0, bb.x1 - x1, y0 - bb.y0, bb.y1 - y1)
        if over > 0.5:
            warnings.append(f"text {t.get_text()[:40]!r} leaves its box by {over / fig.dpi * 25.4:.2f} mm")
    pad = 0.3 * fig.dpi / 72
    for (t1, b1), (t2, b2) in combinations(boxes, 2):
        if b1.x0 + pad < b2.x1 and b2.x0 + pad < b1.x1 and b1.y0 + pad < b2.y1 and b2.y0 + pad < b1.y1:
            warnings.append(f"text overlaps: {t1.get_text()[:30]!r} × {t2.get_text()[:30]!r}")
    return {"warnings": warnings, "text_sizes_pt": sizes, "stroke_widths_pt": sorted(widths), "n_texts": len(texts)}


def save(cv: Canvas, outdir: Path, *, png_dpi: int = 600) -> dict[str, Any]:
    import matplotlib.pyplot as plt
    from PIL import Image

    report = qc(cv)
    pdf, png = outdir / f"{NAME}.pdf", outdir / f"{NAME}.png"
    # no dates in the files: the same source data gives the same bytes
    cv.fig.savefig(pdf, metadata={"Title": "TaoChronos system architecture", "Creator": "docs/figures/architecture.py",
                                  "Producer": "matplotlib", "CreationDate": None, "ModDate": None})
    cv.fig.savefig(png, dpi=png_dpi, metadata={"Software": None})
    with Image.open(png) as im:  # RGB, as publishers ask: the alpha channel flattened onto white
        rgb = Image.new("RGB", im.size, "white")
        rgb.paste(im, mask=im.getchannel("A") if im.mode == "RGBA" else None)
    rgb.save(png, dpi=(png_dpi, png_dpi), optimize=True)
    plt.close(cv.fig)
    try:
        import pymupdf

        doc = pymupdf.open(pdf)
        page = doc[0]
        fonts = []
        for xref, _, kind, name, *_ in page.get_fonts(full=True):
            program = doc.extract_font(xref)[3]
            fonts.append(name.split("+")[-1])
            if kind == "Type3" or not program:
                report["warnings"].append(f"font {name} is not embedded as outlines a printer can use ({kind})")
            elif program[:4] not in (b"\x00\x01\x00\x00", b"true"):  # e.g. b"OTTO": PostScript outlines, mislabelled
                report["warnings"].append(f"font {name} is not a TrueType font, though the file says so")
        report.update(width_mm=round(page.rect.width * PT, 2), height_mm=round(page.rect.height * PT, 2),
                      fonts=sorted(fonts), live_text_chars=len(page.get_text().strip()))
        if abs(report["width_mm"] - WIDTH) > 0.2:
            report["warnings"].append(f"the page is {report['width_mm']} mm wide, not {WIDTH}")
        if "\ufffd" in page.get_text():
            report["warnings"].append("the PDF holds a character its font cannot show")
    except ImportError:
        report["warnings"].append("pymupdf is not installed: the PDF was not measured")
    report["png"] = {"dpi": png_dpi, "pixels": list(rgb.size), "mode": rgb.mode}
    report["files"] = [str(p.relative_to(HOME)) if p.is_relative_to(HOME) else str(p) for p in (pdf.resolve(), png.resolve())]
    return report


def draw(d: dict[str, Any], outdir: Path = HERE) -> dict[str, Any]:
    cv = Canvas()
    bottom = panel_a(cv, d, EDGE)
    row = bottom + 4.2
    cv.finish(max(panel_b(cv, d, EDGE, row), panel_c(cv, d, 74.5, row)) + EDGE)
    return save(cv, outdir)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--draw-only", action="store_true", help="draw from the architecture.json already written")
    ap.add_argument("--out", type=Path, default=HERE, help="where the PDF and the PNG are written")
    a = ap.parse_args()
    if a.draw_only:
        d = json.loads(DATA.read_text(encoding="utf-8"))
    else:
        d = collect()
        DATA.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    report = draw(d, a.out)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 1 if report["warnings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
