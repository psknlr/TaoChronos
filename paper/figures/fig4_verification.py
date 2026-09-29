"""Fig. 4 | Verification keeps quotations verbatim, the harness's boundaries hold, and hard readings stay safe."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.patches import Patch, Rectangle

from nature_style import C, Canvas, tint, wilson

HERE = Path(__file__).resolve().parent
SD = HERE / "source_data"

CLASSES = [("relation_inversion", "Relation inversion"), ("textual_crux", "Textual crux"),
           ("reported_view", "Reported or rejected view"), ("omitted_condition", "Omitted condition"),
           ("negation_scope", "Scope of a prohibition"), ("consequence", "Warning versus remedy"),
           ("witness_mixing", "Mixed witnesses"), ("date_dispute", "Disputed date")]

VARIANTS = [("intact", "Intact harness", None),
            ("no_scope_guard", "BeforeToolCall scope guard", "I01"),
            ("no_scope_firewall", "AfterToolCall result firewall", "I02"),
            ("no_semantic_support", "Semantic-support commit hook", "I04"),
            ("no_gate_authority", "Reducer authority over G7", "I12"),
            ("no_evidence_bounds", "Evidence-bound checks", "I13"),
            ("no_publish_guard", "Publish guard", "I18")]


def mutation_matrix(invariants: list[str]) -> tuple[np.ndarray, str]:
    """0 held · 1 broken · 2 not exercised · 3 not measured.  The measured matrix when mutation_matrix.py has run;
    otherwise the documented result (each removed boundary breaks the invariant named for it; the rest unmeasured)."""
    path = SD / "extfig_mutation_matrix.json"
    m = np.full((len(VARIANTS), len(invariants)), 3)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        by_name = {v["name"]: v for v in data["variants"]}
        for i, (name, _, _) in enumerate(VARIANTS):
            v = by_name[name]
            res = {r["id"]: r["held"] for r in v["results"]}
            for j, iid in enumerate(invariants):
                held = res.get(iid)
                m[i, j] = 0 if held is True else 1 if held is False else 2
        return m, "measured"
    inv = pd.read_csv(SD / "fig4_invariants.csv")
    held = dict(zip(inv.id, inv.held))
    m[0] = [0 if held[i] is True or held[i] == "True" else 1 for i in invariants]
    for i, (_, _, target) in enumerate(VARIANTS[1:], start=1):
        m[i, invariants.index(target)] = 1
    return m, "documented"


def main() -> dict:
    hal = pd.read_csv(SD / "fig4_hallucination.csv")
    inv = pd.read_csv(SD / "fig4_invariants.csv")
    cases = pd.read_csv(SD / "fig4_interpretive_cases.csv")
    rounds = pd.read_csv(SD / "fig4_interpretive_rounds.csv")

    cv = Canvas("double", 104)

    # a — the quotation check ----------------------------------------------------------------------------------------------
    ax = cv.ax(31, 11, 24, 26)
    ys = np.arange(len(hal))[::-1]
    for y, (_, r) in zip(ys, hal.iterrows()):
        lo, hi = wilson(int(r.passed), int(r.n))
        ax.plot([lo, hi], [y, y], color=C["black"], lw=0.7, solid_capstyle="butt")
        ax.plot([r.rate], [y], "o", ms=3.2, color=C["blue"], mec="none", clip_on=False, zorder=3)
        ax.text(1.008, y, f"{int(r.passed)}/{int(r.n)}", va="center", ha="left", fontsize=5.5)
    ax.set_yticks(ys)
    ax.set_yticklabels(hal.probe, fontsize=5.5)
    ax.set_ylim(-0.6, len(hal) - 0.4)
    ax.set_xlim(0.9, 1.0)
    ax.set_xticks([0.9, 0.95, 1.0])
    ax.set_xticklabels(["0.90", "0.95", "1.00"])
    ax.set_xlabel("Proportion handled correctly")
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    cv.label(2, 3, "a")

    # b — invariants on the intact harness and with one boundary removed ---------------------------------------------------
    ids = list(inv.id)
    m, kind = mutation_matrix(ids)
    x0, y0, cw, rh = 104.0, 13.0, 3.95, 3.3
    axm = cv.blank(x0, y0, cw * len(ids), rh * len(VARIANTS))
    fills = {0: tint(C["blue"], 0.55), 1: C["vermillion"], 2: "white", 3: "white"}
    for i, (_, label, target) in enumerate(VARIANTS):
        for j, iid in enumerate(ids):
            v = int(m[i, j])
            axm.add_patch(Rectangle((j * cw + 0.25, i * rh + 0.25), cw - 0.5, rh - 0.5, facecolor=fills[v],
                                    edgecolor=C["grey"] if v in (2, 3) else "none", lw=0.4 if v in (2, 3) else 0))
            if v == 2:
                axm.text(j * cw + cw / 2, i * rh + rh / 2, "–", ha="center", va="center", fontsize=5, color=C["dark"])
        if target:
            j = ids.index(target)
            axm.add_patch(Rectangle((j * cw + 0.05, i * rh + 0.05), cw - 0.1, rh - 0.1, facecolor="none",
                                    edgecolor=C["black"], lw=0.8))
        cv.text(x0 - 1.2, y0 + i * rh + rh / 2, label, ha="right", va="center", fontsize=5.5)
    for j, iid in enumerate(ids):
        cv.text(x0 + j * cw + cw / 2, y0 - 0.8, iid[1:], ha="center", va="bottom", fontsize=5, rotation=0)
    cv.text(x0 - 1.2, y0 - 0.8, "Invariant", ha="right", va="bottom", fontsize=5.5)
    brk = cv.blank(68.5, y0 + rh, 2.0, rh * (len(VARIANTS) - 1))
    brk.plot([1.6, 0.6, 0.6, 1.6], [0.3, 0.3, rh * (len(VARIANTS) - 1) - 0.3, rh * (len(VARIANTS) - 1) - 0.3],
             color=C["black"], lw=0.5)
    cv.text(67.8, y0 + rh + rh * (len(VARIANTS) - 1) / 2, "Boundary removed", rotation=90, ha="center", va="center",
            fontsize=5.5)
    held0 = int((m[0] == 0).sum())
    ly = y0 + rh * len(VARIANTS) + 3.2
    items = [(fills[0], "none", "Held"), (fills[1], "none", "Broken")]
    if kind == "measured" and (m == 2).any():
        items.append(("white", C["grey"], "Not exercised here"))
    if kind == "documented":
        items.append(("white", C["grey"], "Not measured"))
    lx = x0
    for fc, ec, lab in items:
        axl = cv.blank(lx, ly - 1.2, 3.2, 2.4)
        axl.add_patch(Rectangle((0.2, 0.2), 2.8, 2.0, facecolor=fc, edgecolor=ec, lw=0.4 if ec != "none" else 0))
        cv.text(lx + 4.0, ly, lab, va="center", ha="left", fontsize=5.5)
        lx += 5.0 + 1.25 * len(lab)
    axl = cv.blank(lx, ly - 1.2, 3.2, 2.4)
    axl.add_patch(Rectangle((0.2, 0.2), 2.8, 2.0, facecolor="none", edgecolor=C["black"], lw=0.8))
    cv.text(lx + 4.0, ly, "Invariant named for that boundary", va="center", ha="left", fontsize=5.5)
    cv.text(x0 + cw * len(ids), y0 - 4.6, f"Intact: {held0}/{len(ids)} held", ha="right", va="bottom", fontsize=5.5)
    cv.label(64, 3, "b")

    # c — hard interpretive cases by class -----------------------------------------------------------------------------------
    ax = cv.ax(33, 55, 60, 38)
    ys = np.arange(len(CLASSES))[::-1]
    for y, (key, label) in zip(ys, CLASSES):
        sub = cases[cases["class"] == key]
        ho = sub[sub.split == "heldout"]
        dv = sub[sub.split == "dev"]
        ho_ok, dv_ok = int(ho.correct.sum()), int(dv.correct.sum())
        wrong = len(sub) - ho_ok - dv_ok
        ax.barh(y, ho_ok, height=0.62, color=C["blue"], lw=0)
        ax.barh(y, dv_ok, left=ho_ok, height=0.62, color=tint(C["blue"], 0.35), lw=0)
        if wrong:
            ax.barh(y, wrong, left=ho_ok + dv_ok, height=0.62, color=C["vermillion"], lw=0)
        ax.text(len(sub) + 0.6, y, f"{ho_ok}/{len(ho)}", va="center", ha="left", fontsize=5.5)
    ax.set_yticks(ys)
    ax.set_yticklabels([lab for _, lab in CLASSES], fontsize=5.5)
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.set_xlim(0, 30)
    ax.set_xticks([0, 10, 20, 30])
    ax.set_xlabel("Cases")
    ax.set_ylim(-0.7, len(CLASSES) - 0.3)
    handles = [Patch(facecolor=fc, edgecolor="none", label=lab) for fc, lab in
               ((C["blue"], "Held-out, read right"), (tint(C["blue"], 0.35), "Development, read right"),
                (C["vermillion"], "Unsafe misreading (held-out)"))]
    ax.legend(handles=handles, loc="center right", bbox_to_anchor=(1.04, 0.36), handlelength=1.0, fontsize=5.5)
    ax.text(30, len(CLASSES) - 0.35, "Held-out correct / held-out cases", ha="right", va="bottom", fontsize=5.5,
            color=C["dark"])
    cv.label(2, 49, "c")

    # d — the blind rounds as they happened ---------------------------------------------------------------------------------
    ax = cv.ax(120, 55, 56, 29)
    xs = np.arange(len(rounds))
    for x, (_, r) in zip(xs, rounds.iterrows()):
        lo, hi = wilson(int(r.correct), int(r.cases))
        last = r["round"].startswith("Held-out")
        col = C["black"] if last else C["blue"]
        ax.plot([x, x], [lo, hi], color=col, lw=0.7, solid_capstyle="butt")
        ax.plot([x], [r.correct / r.cases], "s" if last else "o", ms=3.4, color=col, mec="none", clip_on=False, zorder=3)
        tr = ax.get_xaxis_transform()
        ax.text(x, -0.2, f"{int(r.correct)}/{int(r.cases)}", transform=tr, ha="center", va="top", fontsize=5.5)
        ax.text(x, -0.32, f"{int(r.unsafe)} unsafe", transform=tr, ha="center", va="top", fontsize=5.5,
                color=C["vermillion"] if r.unsafe else C["dark"])
    ax.axvline(len(rounds) - 1.5, color=C["grey"], lw=0.5, ls=(0, (2, 1.5)))
    ax.set_xlim(-0.5, len(rounds) - 0.5)
    ax.set_ylim(0.35, 1.02)
    ax.set_yticks([0.4, 0.6, 0.8, 1.0])
    ax.set_xticks(xs)
    ax.set_xticklabels(["Round 1", "Round 2", "Round 3", "Round 4", "All held-out"], fontsize=5.5)
    ax.set_ylabel("Accuracy (new held-out cases)")
    cv.label(104, 49, "d")

    rep = cv.save("fig4_verification", HERE / "out")
    rep["mutation_matrix"] = kind
    return rep


if __name__ == "__main__":
    r = main()
    print({k: r[k] for k in ("width_mm", "height_mm", "fonts", "text_sizes_pt", "stroke_widths_pt", "mutation_matrix")})
    print("\n".join(r["warnings"]) or "no warnings")
