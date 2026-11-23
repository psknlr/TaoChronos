"""A schematic human figure seen from behind, for the point map of the acupuncture case.

The figure stands in the anatomical position (arms a little away from the trunk, backs of the hands towards the
viewer).  It is drawn from smooth closed outlines given in fractions of the body's height: x from the midline
(positive to the viewer's right), y from the top of the head (0) to the soles (1).  ``Body.at(x, y)`` turns such a
pair into millimetres on the page, so that points and channels are placed by surface anatomy (the level of a
vertebra, the popliteal crease, the lateral malleolus) and not by eye.  It is a diagram for orientation, not an atlas.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from matplotlib.patches import Ellipse, PathPatch
from matplotlib.path import Path as MPath

SKIN, EDGE, MARK, FAINT = "#ECECEC", "#B9B9B9", "#CFCFCF", "#D9D9D9"

# the levels of the spinous processes, as fractions of the body's height (C7 … the tip of the coccyx)
C7, T1, T12, L1, L5, SACRUM_END = 0.166, 0.178, 0.343, 0.360, 0.436, 0.500
VERTEBRAE = {f"T{i}": T1 + (T12 - T1) * (i - 1) / 11 for i in range(1, 13)}
VERTEBRAE.update({f"L{i}": L1 + (L5 - L1) * (i - 1) / 4 for i in range(1, 6)})
LUMBAR_STEP = (L5 - L1) / 4
THORACIC_STEP = (T12 - T1) / 11
POPLITEAL, MALLEOLUS = 0.712, 0.952

# right half of the figure (the viewer's right); the left half is its mirror image
TORSO = [(0.000, 0.150), (0.030, 0.152), (0.050, 0.166), (0.085, 0.176), (0.112, 0.186), (0.128, 0.205),
         (0.126, 0.240), (0.100, 0.262), (0.096, 0.300), (0.090, 0.345), (0.086, 0.385), (0.090, 0.425),
         (0.100, 0.465), (0.104, 0.505), (0.100, 0.540), (0.050, 0.548), (0.000, 0.540)]
ARM = [(0.108, 0.190), (0.128, 0.200), (0.141, 0.235), (0.148, 0.300), (0.158, 0.365), (0.170, 0.400),
       (0.180, 0.450), (0.186, 0.500), (0.189, 0.525), (0.201, 0.548), (0.207, 0.572), (0.199, 0.580),
       (0.196, 0.600), (0.191, 0.628), (0.182, 0.636), (0.173, 0.628), (0.166, 0.598), (0.163, 0.560),
       (0.160, 0.525), (0.152, 0.480), (0.140, 0.420), (0.128, 0.375), (0.116, 0.320), (0.104, 0.270),
       (0.098, 0.235)]
LEG = [(0.004, 0.520), (0.050, 0.480), (0.098, 0.490), (0.106, 0.540), (0.102, 0.600), (0.092, 0.660),
       (0.080, 0.705), (0.079, 0.735), (0.086, 0.775), (0.084, 0.820), (0.071, 0.880), (0.062, 0.925),
       (0.062, 0.955), (0.068, 0.978), (0.064, 0.994), (0.044, 0.999), (0.026, 0.994), (0.024, 0.975),
       (0.029, 0.950), (0.029, 0.920), (0.022, 0.870), (0.014, 0.810), (0.014, 0.770), (0.020, 0.735),
       (0.018, 0.700), (0.010, 0.650), (0.004, 0.590)]
NECK = [(0.000, 0.105), (0.030, 0.108), (0.032, 0.140), (0.046, 0.168), (0.000, 0.176)]
SCAPULA = [(0.036, 0.214), (0.060, 0.205), (0.088, 0.214), (0.085, 0.244), (0.064, 0.288), (0.046, 0.278),
           (0.036, 0.246)]


def smooth(points: list[tuple[float, float]], closed: bool = True) -> MPath:
    """A smooth curve through the points (uniform Catmull–Rom, written as cubic Béziers)."""
    p = np.asarray(points, float)
    n = len(p)
    idx = (lambda i: i % n) if closed else (lambda i: min(max(i, 0), n - 1))
    verts, codes = [tuple(p[0])], [MPath.MOVETO]
    for i in range(n if closed else n - 1):
        p0, p1, p2, p3 = p[idx(i - 1)], p[idx(i)], p[idx(i + 1)], p[idx(i + 2)]
        verts += [tuple(p1 + (p2 - p0) / 6), tuple(p2 - (p3 - p1) / 6), tuple(p2)]
        codes += [MPath.CURVE4] * 3
    if closed:
        verts.append(verts[0])
        codes.append(MPath.CLOSEPOLY)
    return MPath(verts, codes)


class Body:
    """The figure on the page: its midline at ``cx`` mm, the top of its head at ``top`` mm, ``height`` mm tall."""

    def __init__(self, ax: Any, cx: float, top: float, height: float) -> None:
        self.ax, self.cx, self.top, self.h = ax, cx, top, height

    def at(self, x: float, y: float) -> tuple[float, float]:
        return (self.cx + x * self.h, self.top + y * self.h)

    def _shape(self, pts: list[tuple[float, float]], side: int, *, fill: str, edge: str | None, lw: float, z: float,
               closed: bool = True) -> None:
        path = smooth([self.at(side * x, y) for x, y in pts], closed)
        self.ax.add_patch(PathPatch(path, facecolor=fill, edgecolor=edge if edge else "none", lw=lw if edge else 0,
                                    zorder=z, joinstyle="round", capstyle="round"))

    def draw(self) -> "Body":
        ax, h = self.ax, self.h
        whole = [(x, y) for x, y in TORSO] + [(-x, y) for x, y in reversed(TORSO[1:-1])]
        neck = [(x, y) for x, y in NECK] + [(-x, y) for x, y in reversed(NECK[1:-1])]
        # every part twice: first with its outline, then again as a fill, so that only the outer contour remains
        for z, (fill, edge) in ((1.0, (SKIN, EDGE)), (1.2, (SKIN, None))):
            self._shape(whole, 1, fill=fill, edge=edge, lw=1.0, z=z)
            self._shape(neck, 1, fill=fill, edge=edge, lw=1.0, z=z)
            for side in (1, -1):
                self._shape(ARM, side, fill=fill, edge=edge, lw=1.0, z=z)
                self._shape(LEG, side, fill=fill, edge=edge, lw=1.0, z=z)
            cx, cy = self.at(0, 0.063)
            ax.add_patch(Ellipse((cx, cy), 0.096 * h, 0.126 * h, facecolor=fill, edgecolor=edge if edge else "none",
                                 lw=1.0 if edge else 0, zorder=z))
        # surface landmarks: the spinous processes, the sacrum, the shoulder blades, the folds of buttock and knee
        for name, y in VERTEBRAE.items():
            step = LUMBAR_STEP if name[0] == "L" else THORACIC_STEP
            w = (0.013 if name[0] == "L" else 0.010) * h
            x0, y0 = self.at(0, y)
            ax.add_patch(PathPatch(MPath([(x0 - w / 2, y0 - step * h * 0.36), (x0 + w / 2, y0 - step * h * 0.36),
                                          (x0 + w / 2, y0 + step * h * 0.36), (x0 - w / 2, y0 + step * h * 0.36),
                                          (x0 - w / 2, y0 - step * h * 0.36)]), facecolor=MARK, edgecolor="none",
                                   lw=0, zorder=1.4))
        sac = [self.at(-0.016, L5 + 0.012), self.at(0.016, L5 + 0.012), self.at(0.0, SACRUM_END)]
        ax.add_patch(PathPatch(MPath(sac + [sac[0]]), facecolor=MARK, edgecolor="none", lw=0, zorder=1.4))
        for side in (1, -1):
            self._shape(SCAPULA, side, fill="none", edge=FAINT, lw=0.4, z=1.4)
            for pts in ([(0.012, 0.538), (0.050, 0.552), (0.090, 0.540)],     # the gluteal fold
                        [(0.024, POPLITEAL), (0.048, POPLITEAL + 0.004), (0.072, POPLITEAL)],  # the popliteal crease
                        [(0.012, 0.420), (0.050, 0.404), (0.086, 0.418)]):    # the iliac crest
                self._shape(pts, side, fill="none", edge=MARK, lw=0.5, z=1.4, closed=False)
        gx, gy = zip(self.at(0, SACRUM_END), self.at(0, 0.540))
        ax.plot(gx, gy, color=MARK, lw=0.5, zorder=1.4, solid_capstyle="round")
        return self

    def channel(self, pts: list[tuple[float, float]], side: int = 1, **kw: Any) -> None:
        path = smooth([self.at(side * x, y) for x, y in pts], closed=False)
        self.ax.add_patch(PathPatch(path, facecolor="none", zorder=kw.pop("z", 2), capstyle="round", **kw))


__all__ = ["Body", "C7", "L1", "L5", "LUMBAR_STEP", "MALLEOLUS", "POPLITEAL", "VERTEBRAE", "smooth"]
