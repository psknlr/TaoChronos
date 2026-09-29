"""Fig. 3 | One research question, end to end: what the harness did with it and what it concluded.

The run is `taochronos research "肾气丸的组成与主治如何随时代演变？"` on the open canon corpus (web-canon profile, rules only,
no model called); `e2e_case.py` writes its source data from the event log and state.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from matplotlib.patches import FancyBboxPatch, PathPatch, Rectangle
from matplotlib.path import Path as MPath

from nature_style import C, Canvas, text_width_mm, tint, wrap_mm

HERE = Path(__file__).resolve().parent
SD = HERE / "source_data"
PT = 0.3528  # mm per point
GATES = ["G0", "G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8"]
CRITERIA = [("min_supporting_evidence", "≥ 2 verified records"), ("semantic_support", "Quote states claim"),
            ("source_dependence", "≥ 2 source families"), ("falsification_review", "Skeptic review"),
            ("unresolved_hard_objections", "No hard objection"), ("unresolved_critical", "No critical one"),
            ("alternatives_addressed", "Rivals addressed"), ("current_version_gates", "Gates, this version"),
            ("expert_review", "Expert review")]
STATUS_FILL = {"pass": C["blue"], "warn": tint(C["blue"], 0.3), "fail": C["vermillion"], "pending": "white",
               "not_applicable": "white", "": "white"}
VERDICT = {"needs_expert": ("Needs expert", C["blue"]), "inconclusive": ("Inconclusive", C["dark"]),
           "rejected": ("Rejected", C["vermillion"])}
AGENTS = [("director", "Director"), ("curator", "Curator"), ("philologist", "Philologist"),
          ("semanticist", "Semanticist"), ("extractor", "Extractor"), ("lineage", "Lineage"), ("scholar", "Scholar"),
          ("evidence", "Evidence"), ("pattern_miner", "Pattern miner"), ("statistician", "Statistician"),
          ("evolution", "Evolution"), ("hypothesis", "Hypothesis"), ("skeptic", "Skeptic"),
          ("meta_reviewer", "Meta-reviewer"), ("validator", "Validators")]
# the hypotheses in words (track; what is claimed); the statements themselves are in fig3_e2e_hypotheses.csv
SHORT = {"H1": ("D4", "烦躁 → 六味地黄丸 (indication rule)"), "H2": ("D1", "肾气丸 with 心烦, not after 960"),
         "H3": ("D1", "《下經》, a book cited but not held"), "H4": ("D2", "中风, Song–Yuan → Ming"),
         "H5": ("D2", "中风, Ming → Qing"), "H6": ("D1", "肾气丸 with 腹痛, not after 960"),
         "H7": ("D4", "壮热 → 六味地黄丸 (indication rule)"), "H8": ("D1", "《集验方》, a lost book cited once"),
         "H9": ("D2", "伤寒, Han → Song–Yuan"), "H10": ("D5", "痰: 校注妇人良方 against 内科摘要"),
         "H11": ("D5", "痰: the same two works, other passages"), "H12": ("D4", "呕吐 → 六味地黄丸 (graph link)"),
         "H13": ("D4", "痰饮 → 六味地黄丸 (graph link)"), "R1": ("D1", "理中丸 with 发热, not after 960")}
# the Skeptic's checks, named by what they found in this run (fig3_e2e_objections.csv, column detail)
CHECKS = [("single_source", "Single source"), ("transcription_dependence", "Transcription dependence"),
          ("statistical", "Not significant"), ("homonym", "Homonym"), ("sample_size", "Sample size"),
          ("school", "Same school"), ("counterexample", "Already co-occurs"), ("earliest_source", "Co-mentioned later"),
          ("partial_persistence", "Persists in other words"), ("restated_after", "Restated later")]


def rbox(ax, x, y, w, h, *, fc="white", ec=None, lw=0.5, r=0.8):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}", facecolor=fc,
                                edgecolor=ec or C["black"], lw=lw))


def para(ax, x, y, s, width, fs=5.5, *, weight="normal", color="black", lh=1.22, **kw):
    """Wrapped text from its top-left corner; returns the y below it (mm)."""
    lines = wrap_mm(s, width, fs, weight)
    ax.text(x, y, "\n".join(lines), ha="left", va="top", fontsize=fs, fontweight=weight, color=color,
            linespacing=lh, **kw)
    return y + len(lines) * fs * PT * lh


def band(ax, x0, y0a, y0b, x1, y1a, y1b, color, alpha=1.0):
    """A flow band from the segment (x0, y0a–y0b) to (x1, y1a–y1b), with S-shaped edges."""
    xm = (x0 + x1) / 2
    verts = [(x0, y0a), (xm, y0a), (xm, y1a), (x1, y1a), (x1, y1b), (xm, y1b), (xm, y0b), (x0, y0b), (x0, y0a)]
    codes = [MPath.MOVETO, MPath.CURVE4, MPath.CURVE4, MPath.CURVE4, MPath.LINETO, MPath.CURVE4, MPath.CURVE4,
             MPath.CURVE4, MPath.CLOSEPOLY]
    ax.add_patch(PathPatch(MPath(verts, codes), facecolor=color, edgecolor="none", alpha=alpha))


def main() -> dict:
    contract = json.loads((SD / "fig3_e2e_contract.json").read_text(encoding="utf-8"))
    tasks = pd.read_csv(SD / "fig3_e2e_tasks.csv")
    rounds = pd.read_csv(SD / "fig3_e2e_rounds.csv")
    metrics = json.loads((SD / "fig3_e2e_metrics.json").read_text(encoding="utf-8"))
    hyps = pd.read_csv(SD / "fig3_e2e_hypotheses.csv", keep_default_na=False)
    objections = pd.read_csv(SD / "fig3_e2e_objections.csv", keep_default_na=False)
    reviews = pd.read_csv(SD / "fig3_e2e_reviews.csv", keep_default_na=False)
    events = pd.read_csv(SD / "fig3_e2e_events.csv")
    detail = json.loads((SD / "fig3_e2e_detail.json").read_text(encoding="utf-8"))
    cv = Canvas("double", 168)

    # a — the question and the contract fixed before work began ----------------------------------------------------------
    ax = cv.blank(2, 6, 61, 50)
    rbox(ax, 0.3, 0.3, 60.4, 49.4, ec=C["grey"], lw=0.5)
    ax.text(2, 2.0, contract["question"], ha="left", va="top", fontsize=7, fontweight="bold")
    y = para(ax, 2, 5.4, "How did the composition and indications of Shenqi wan change over time?", 57, 5.5,
             color=C["dark"])
    rows = [("Focus", "肾气丸, 六味地黄丸 (Liuwei dihuang wan)"),
            ("Forbidden", "消渴 = 糖尿病 (xiaoke read as diabetes)"),
            ("Tracks", "all five discovery tracks, D1–D5"),
            ("Evidence", "verbatim quotations; ≥ 2 records from ≥ 2 independent source families"),
            ("Gates", "G0–G6 pass on the current version; G4–G6 strict"),
            ("Accept", "no open hard or critical objection; rival explanations addressed; expert review "
                       "before publication"),
            ("Stop", "after 2 rounds, or when new evidence adds < 5%"),
            ("Digest", f"{contract['goal_digest'][:16]}…, fixed before the first task")]
    y += 0.9
    for lab, val in rows:
        ax.text(2, y, lab, ha="left", va="top", fontsize=5.5, fontweight="bold")
        y = para(ax, 12.5, y, val, 46.5, 5.5) + 0.35
    per = contract["passages_by_period"]
    names = {"先秦两汉": "Qin–Han", "魏晋南北朝": "Wei–Jin", "隋唐五代": "Sui–Tang", "宋金元": "Song–Jin–Yuan",
             "明": "Ming", "清": "Qing", "民国": "Republic"}
    ax.text(2, y + 0.6, "Scope", ha="left", va="top", fontsize=5.5, fontweight="bold")
    para(ax, 12.5, y + 0.6, f"{contract['books_in_scope']} books, {contract['passages_in_scope']:,} passages naming a "
         "focus term (" + ", ".join(f"{names[k]}\u00a0{v}" for k, v in per.items()) + ")", 46.5, 5.5)
    cv.label(2, 3, "a")

    # b — who did what, in the order the harness ran it ------------------------------------------------------------------
    x0, y0, wd = 86.0, 12.0, 95.0
    rh = 2.35
    n = len(tasks)
    axr = cv.blank(x0 - 20, y0 - 5, wd + 20, rh * len(AGENTS) + 14.5)
    ox, oy = 20.0, 5.0
    xs = lambda i: ox + (i + 0.5) * wd / n  # noqa: E731
    row = {k: j for j, (k, _) in enumerate(AGENTS)}
    edges = [0] + [int(tasks[tasks["round"] == r].order.max()) + 1 for r in sorted(tasks["round"].unique())]
    titles = ["Round 0: read", "Round 1: discover, falsify, grade", "Round 2: re-check, grade"]
    for r in range(3):
        xa, xb = ox + edges[r] * wd / n, ox + edges[r + 1] * wd / n
        if r % 2 == 0:
            axr.add_patch(Rectangle((xa, oy), xb - xa, rh * len(AGENTS), facecolor="#F2F2F2", edgecolor="none"))
        axr.text((xa + xb) / 2, oy - 1.0, titles[r], ha="center", va="bottom", fontsize=5.5, fontweight="bold")
        g = rounds[rounds["round"] == r].iloc[0]
        gain = (f"+{g.new_evidence} evidence, {g.new_sources} new books"
                + (f", {g.new_hypotheses} hypotheses" if g.new_hypotheses else ""))
        axr.text((xa + xb) / 2, oy + rh * len(AGENTS) + 1.2, gain, ha="center", va="top", fontsize=5)
    for j, (_, name) in enumerate(AGENTS):
        axr.text(ox - 1.0, oy + (j + 0.5) * rh, name, ha="right", va="center", fontsize=5.5,
                 color=C["dark"] if name == "Validators" else "black")
        axr.plot([ox, ox + wd], [oy + (j + 0.5) * rh] * 2, color=C["light"], lw=0.25, zorder=0)
    pts = [(xs(t.order), oy + (row[t.role] + 0.5) * rh) for t in tasks.itertuples()]
    for t, (px, py) in zip(tasks.itertuples(), pts):
        agent = t.principal == "agent"
        axr.add_patch(Rectangle((px - 0.95, py - 0.8), 1.9, 1.6, facecolor=C["blue"] if agent else C["dark"],
                                edgecolor="none", zorder=2))
        if t.tool_calls:
            axr.text(px + 1.4, py, f"{t.tool_calls}", ha="left", va="center", fontsize=5, zorder=3)
    stop = metrics["stop"]["reasons"][0].split("(")[1].split(" < ")[0]
    by = events.groupby("principal")["count"].sum()
    yb = oy + rh * len(AGENTS) + 4.2
    axr.text(ox, yb, f"Log: {by.sum()} events (agents {by['agent']}, validators {by['validator']}, kernel "
             f"{by['kernel']}); {metrics['tool_calls']} tool calls, {metrics['tool_denials']} refused; "
             f"{metrics['llm_calls']} model calls", ha="left", va="top", fontsize=5, color=C["dark"])
    axr.text(ox, yb + 2.4, f"Stop: new evidence {float(stop):.1%} < 5% in round 2 of 2", ha="left", va="top",
             fontsize=5, color=C["dark"])
    kx = ox + wd - 42.5
    for k, (lab, col) in enumerate([("agent task", C["blue"]), ("validator task", C["dark"])]):
        axr.add_patch(Rectangle((kx + k * 15.0, yb + 2.45), 1.9, 1.6, facecolor=col, edgecolor="none"))
        axr.text(kx + k * 15.0 + 2.6, yb + 3.25, lab, ha="left", va="center", fontsize=5)
    axr.text(ox + wd, yb + 3.25, "3: tool calls", ha="right", va="center", fontsize=5)
    cv.label(66, 3, "b")

    # c — from proposals to verdicts -------------------------------------------------------------------------------------
    ax = cv.blank(2, 61, 64, 57)
    u = 1.35  # mm per hypothesis
    r1 = reviews[reviews.reviewer.str.endswith("@r1.falsify")]
    verdict_of = dict(zip(hyps["id"], hyps["verdict"]))
    kept = r1[r1.verdict == "survives"]
    revised = r1[r1.verdict == "revise"]
    rejected = r1[r1.verdict == "reject"]
    n0 = len(r1)
    col_x = [1.5, 17.5, 33.5, 48.0]
    top = 3.9
    gap = 1.3
    fate_col = lambda v: C["blue"] if v == "needs_expert" else C["vermillion"] if v == "rejected" else C["grey"]  # noqa
    v1 = dict(zip(r1.hypothesis, r1.verdict))
    children = dict(zip(hyps["parent_id"], hyps["id"]))
    final = {hid: verdict_of.get(children.get(hid, hid)) or verdict_of.get(hid) for hid in r1.hypothesis}
    # proposals in the order: kept (the one that needs an expert first), narrowed, rejected
    order0 = (sorted(kept.hypothesis, key=lambda h: final[h] != "needs_expert") + list(revised.hypothesis)
              + list(rejected.hypothesis))
    seg1 = {"survives": top, "revise": top + len(kept) * u + gap,
            "reject": top + (len(kept) + len(revised)) * u + 2 * gap}
    pos1, cur = {}, dict(seg1)
    for hid in order0:
        pos1[hid] = cur[v1[hid]]
        cur[v1[hid]] += u
    cands = [h for h in order0 if v1[h] != "reject"]
    seg3 = {"needs_expert": top, "inconclusive": top + u + gap}
    pos3, cur = {}, dict(seg3)
    for hid in cands:
        pos3[hid] = cur[final[hid]]
        cur[final[hid]] += u
    hw = 1.1  # half the width of a node
    for i, hid in enumerate(order0):
        colr = tint(fate_col(final[hid]), 0.45)
        band(ax, col_x[0] + hw, top + i * u, top + (i + 1) * u - 0.22, col_x[1] - hw, pos1[hid],
             pos1[hid] + u - 0.22, colr)
    for i, hid in enumerate(cands):
        colr = tint(fate_col(final[hid]), 0.45)
        band(ax, col_x[1] + hw, pos1[hid], pos1[hid] + u - 0.22, col_x[2] - hw, top + i * u, top + (i + 1) * u - 0.22,
             colr)
        band(ax, col_x[2] + hw, top + i * u, top + (i + 1) * u - 0.22, col_x[3] - hw, pos3[hid], pos3[hid] + u - 0.22,
             colr)

    def node(x, ya, k, color):
        ax.add_patch(Rectangle((x - hw, ya), 2 * hw, k * u - 0.22, facecolor=color, edgecolor="none"))

    node(col_x[0], top, n0, C["dark"])
    for v, colr in (("survives", C["dark"]), ("revise", C["dark"]), ("reject", C["vermillion"])):
        node(col_x[1], seg1[v], int((r1.verdict == v).sum()), colr)
    node(col_x[2], top, len(cands), C["dark"])
    for v in ("needs_expert", "inconclusive"):
        node(col_x[3], seg3[v], sum(1 for h in cands if final[h] == v), fate_col(v))
    hy = top - 0.9
    ax.text(col_x[0] - hw, hy, f"{n0} proposed", ha="left", va="bottom", fontsize=5.5, fontweight="bold")
    ax.text(col_x[1], hy, "Skeptic", ha="center", va="bottom", fontsize=5.5, fontweight="bold")
    ax.text(col_x[2], hy, f"{len(cands)} candidates", ha="center", va="bottom", fontsize=5.5, fontweight="bold")
    ax.text(col_x[3] - hw, hy, "Validators", ha="left", va="bottom", fontsize=5.5, fontweight="bold")
    ax.text(col_x[1] + hw + 0.8, seg1["survives"] + len(kept) * u / 2, f"{len(kept)} kept", ha="left",
            va="center", fontsize=5)
    ax.text(col_x[1] + hw + 0.8, seg1["revise"] + len(revised) * u / 2, f"{len(revised)} narrowed", ha="left",
            va="center", fontsize=5)
    ax.text(col_x[1] + hw + 0.8, seg1["reject"] + len(rejected) * u / 2, "1 rejected (R1)", ha="left",
            va="center", fontsize=5, color=C["vermillion"])
    n_inc = sum(1 for h in cands if final[h] == "inconclusive")
    ax.text(col_x[3] + hw + 0.8, seg3["needs_expert"] + u / 2, "1 needs\nexpert (H1)", ha="left", va="top",
            fontsize=5, color=C["blue"], linespacing=1.1)
    ax.text(col_x[3] + hw + 0.8, seg3["inconclusive"] + n_inc * u / 2, f"{n_inc}\ninconclusive", ha="left",
            va="center", fontsize=5, linespacing=1.1)
    # objections the Skeptic raised, by check: closed once the claim was narrowed, left open, critical
    oy0 = top + n0 * u + 2 * gap + 2.6
    ax.text(0, oy0, f"Objections raised by the Skeptic ({len(objections)})", ha="left", va="top", fontsize=5.5,
            fontweight="bold")
    kx = 0.0
    for lab, colr in (("closed after narrowing", tint(C["blue"], 0.45)), ("open", C["grey"]),
                      ("critical", C["vermillion"])):
        ax.add_patch(Rectangle((kx, oy0 + 2.75), 1.8, 1.5, facecolor=colr, edgecolor="none"))
        ax.text(kx + 2.4, oy0 + 3.5, lab, ha="left", va="center", fontsize=5)
        kx += 4.6 + text_width_mm(lab, 5)
    ch_top = oy0 + 5.6
    axo = cv.ax(2 + 25.5, 61 + ch_top, 34, 57 - ch_top - 4.3)
    for i, (key, _) in enumerate(CHECKS):
        sub = objections[objections.check == key]
        closed = int((sub.status == "closed").sum())
        crit = int(((sub.status != "closed") & (sub.severity == "critical")).sum())
        open_ = len(sub) - closed - crit
        axo.barh(i, closed, height=0.72, color=tint(C["blue"], 0.45), lw=0)
        axo.barh(i, open_, left=closed, height=0.72, color=C["grey"], lw=0)
        axo.barh(i, crit, left=closed + open_, height=0.72, color=C["vermillion"], lw=0)
        axo.text(len(sub) + 0.8, i, f"{len(sub)}", ha="left", va="center", fontsize=5)
    axo.set_yticks(range(len(CHECKS)), [lab for _, lab in CHECKS], fontsize=5)
    axo.set_ylim(len(CHECKS) - 0.5, -0.5)
    axo.set_xlim(0, 40)
    axo.set_xticks([0, 10, 20, 30, 40])
    axo.set_xlabel("Objections", fontsize=5, labelpad=0.8)
    axo.tick_params(axis="x", labelsize=5, length=1.5, pad=0.8)
    axo.tick_params(axis="y", length=0, pad=1.2)
    cv.label(2, 58, "c")

    # d — every surviving and rejected hypothesis against the gates and the contract -----------------------------------
    rows_ = hyps[hyps.label != ""].copy()
    rows_["k"] = rows_.label.map(lambda s: (s[0] == "R", int(s[1:])))
    rows_ = rows_.sort_values("k")
    x_lab, x_cell, cw, rh2 = 70.5, 118.8, 2.6, 2.5
    y_top = 80.2
    axm = cv.blank(68, 58, 115, 62)
    X = lambda x: x - 68.0  # noqa: E731
    Y = lambda y: y - 58.0  # noqa: E731
    cols = [("gate", g) for g in GATES] + [("crit", c) for c, _ in CRITERIA]
    cx = [x_cell + j * cw + (1.5 if kind == "crit" else 0) for j, (kind, _) in enumerate(cols)]
    for j, (kind, key) in enumerate(cols):
        if kind == "gate":
            axm.text(X(cx[j] + cw / 2), Y(y_top - 0.8), key, ha="center", va="bottom", fontsize=5)
        else:
            axm.text(X(cx[j] + cw / 2), Y(y_top - 0.8), dict(CRITERIA)[key], ha="center", va="bottom", fontsize=5,
                     rotation=90)
    axm.text(X(cx[0]), Y(y_top - 4.6), "Gates", ha="left", va="bottom", fontsize=5.5, fontweight="bold")
    axm.plot([X(cx[0]), X(cx[8] + cw)], [Y(y_top - 3.9)] * 2, color="black", lw=0.4)
    axm.text(X(cx[9]), Y(y_top - 19.2), "Contract criteria", ha="left", va="bottom", fontsize=5.5,
             fontweight="bold")
    axm.plot([X(cx[9]), X(cx[17] + cw)], [Y(y_top - 18.5)] * 2, color="black", lw=0.4)
    axm.text(X(x_lab), Y(y_top - 0.8), "Hypothesis (track: claim)", ha="left", va="bottom", fontsize=5.5,
             fontweight="bold")
    vx = cx[-1] + cw + 1.4
    axm.text(X(vx), Y(y_top - 0.8), "Verdict", ha="left", va="bottom", fontsize=5.5, fontweight="bold")
    for i, r in enumerate(rows_.itertuples()):
        yy = y_top + i * rh2
        track, what = SHORT[r.label]
        col = VERDICT[r.verdict][1]
        axm.text(X(x_lab), Y(yy + rh2 / 2), r.label, ha="left", va="center", fontsize=5.5, fontweight="bold",
                 color=col)
        axm.text(X(x_lab + 5.2), Y(yy + rh2 / 2), f"{track}: {what}", ha="left", va="center", fontsize=5.5)
        for j, (kind, key) in enumerate(cols):
            st = getattr(r, f"gate_{key}") if kind == "gate" else getattr(r, f"crit_{key}")
            if r.label == "R1" and kind == "crit":
                continue
            fill = STATUS_FILL.get(st, "white")
            axm.add_patch(Rectangle((X(cx[j]) + 0.2, Y(yy) + 0.22), cw - 0.4, rh2 - 0.44, facecolor=fill,
                                    edgecolor=C["grey"] if fill == "white" else "none", lw=0.25))
            if st in ("pending", "not_applicable"):
                axm.text(X(cx[j] + cw / 2), Y(yy + rh2 / 2) - (0.15 if st == "pending" else 0),
                         "…" if st == "pending" else "–", ha="center", va="center", fontsize=5, color=C["dark"])
        if r.label == "R1":
            axm.text(X(cx[9]) + 0.3, Y(yy + rh2 / 2), "not evaluated: falsified", ha="left", va="center",
                     fontsize=5, color=C["dark"])
        axm.text(X(vx), Y(yy + rh2 / 2), VERDICT[r.verdict][0], ha="left", va="center", fontsize=5.5, color=col)
    ky = y_top + len(rows_) * rh2 + 1.0
    kx = x_lab
    for lab, fill in [("pass", STATUS_FILL["pass"]), ("warn", STATUS_FILL["warn"]), ("fail", STATUS_FILL["fail"]),
                      ("pending", "white"), ("not applicable", "white")]:
        axm.add_patch(Rectangle((X(kx), Y(ky)), 2.2, 1.9, facecolor=fill,
                                edgecolor=C["grey"] if fill == "white" else "none", lw=0.25))
        if lab in ("pending", "not applicable"):
            axm.text(X(kx + 1.1), Y(ky + 0.95) - (0.15 if lab == "pending" else 0), "…" if lab == "pending" else "–",
                     ha="center", va="center", fontsize=5, color=C["dark"])
        axm.text(X(kx + 2.8), Y(ky + 0.95), lab, ha="left", va="center", fontsize=5)
        kx += 5.0 + text_width_mm(lab, 5)
    axm.text(X(kx + 1.0), Y(ky + 0.95), "D1–D5: discovery tracks (a)", ha="left", va="center", fontsize=5,
             color=C["dark"])
    cv.label(68, 58, "d")

    # e — three outcomes in full --------------------------------------------------------------------------------------------
    cards = [(2.0, "needs_expert"), (62.5, "inconclusive"), (123.0, "rejected")]
    cw_, ch_ = 58.0, 45.0
    y_card = 122.8
    for x, key in cards:
        axc = cv.blank(x, y_card, cw_, ch_)
        col = VERDICT[key][1]
        rbox(axc, 0.25, 0.25, cw_ - 0.5, ch_ - 0.5, ec=col, lw=0.6)
        d = detail[key]
        head = {"needs_expert": "H1 · meets every machine criterion; waits for an expert",
                "inconclusive": "H2 · five witnesses, one source family",
                "rejected": "R1 · falsified by a later book"}[key]
        axc.text(1.6, 1.5, head, ha="left", va="top", fontsize=6, fontweight="bold", color=col)
        w = cw_ - 3.4
        if key == "needs_expert":
            s = d["statistics"]
            yy = para(axc, 1.6, 4.6, "In indication claims, 烦躁 (restlessness) goes with 六味地黄丸: confidence 1.0, "
                      f"lift {s['effect']['lift']:.1f}; one-sided Fisher exact P = {s['p_value']:.3f}, retained after "
                      f"Benjamini–Hochberg correction across 6 rules (q = {s['fdr']}).", w, 5.5)
            for e in d["evidence"]:
                q = e["quote"]
                q = "…" + q[q.index("其證"):] if "其證" in q else q[q.index("煩躁"):] if "煩躁" in q else q
                when = "Qing" if e["year"] == 1777.5 else f"Qing, {int(e['year'])}"
                yy = para(axc, 1.6, yy + 0.8, f"{e['title']} ({when}) · {e['passage_id']}", w, 5.5,
                          weight="bold")
                yy = para(axc, 1.6, yy + 0.2, f"「{q}」", w, 6)
            yy = para(axc, 1.6, yy + 0.9, "Two independent source families (G5 pass). Rival explanations: the same "
                      "formula under another name, a single case and one passage copied are excluded; another "
                      "formula under the same name stays open.", w, 5.5)
            para(axc, 1.6, yy + 0.8, "8 of 9 contract criteria met; only an expert may set G7.", w, 5.5,
                 weight="bold", color=col)
        elif key == "inconclusive":
            s = d["statistics"]
            yy = para(axc, 1.6, 4.6, "肾气丸 with 心烦 (vexation) is written before 960 and not after; had the "
                      f"early rate persisted, finding no later instance would have P = {s['p_absence']:.2f}.", w, 5.5)
            e = next(v for v in d["evidence"] if v["passage_id"].startswith("cm_jingui_dengzhen"))
            q = e["quote"]
            yy = para(axc, 1.6, yy + 0.8, "The clause on 转胞 (retention of urine in women)", w, 5.5, weight="bold")
            yy = para(axc, 1.6, yy + 0.2, f"「{q[q.index('煩熱'):q.index('倚息') + 2]}……{q[q.index('但利'):]}」", w, 6)
            wits = ["新编金匮方论, Deng Zhen print (CMETA)", "金匮要略方, Wu Qian manuscript (CMETA)",
                    "新编金匮要略方论 (Kanseki Repository)", "脉经, two witnesses (JiCheng)"]
            yy = para(axc, 1.6, yy + 0.6, "Witnesses: " + "; ".join(wits) + ". The 脉经 copies the 金匮 clause.",
                      w, 5.5)
            yy = para(axc, 1.6, yy + 0.8, "Skeptic: transcription dependence, one source, absence not significant. "
                      "The claim was narrowed (one tradition, surveyed corpus, exploratory) and a validator closed "
                      "the three objections.", w, 5.5)
            para(axc, 1.6, yy + 0.8, "G5 warns: one independent family, two required.", w, 5.5, weight="bold",
                 color=col)
        else:
            yy = para(axc, 1.6, 4.6, "理中丸 with 发热 (fever) is written before 960 and not after.", w, 5.5)
            yy = para(axc, 1.6, yy + 0.8, "伤寒论, two Song-print witnesses (CMETA)", w, 5.5, weight="bold")
            yy = para(axc, 1.6, yy + 0.2, "a cholera clause listing fever, headache and body pain, ending", w, 5.5)
            q = d["supporting"][0]["quote"]
            yy = para(axc, 1.6, yy + 0.2, f"「…{q[q.index('寒多'):]}」", w, 6)
            e = next(v for v in d["counter"] if v["passage_id"] == "jc_d041.00588")
            q = e["quote"]
            yy = para(axc, 1.6, yy + 0.8, f"Counter-evidence: {e['title']} (Qing, {int(e['year'])}) · "
                      f"{e['passage_id']}", w, 5.5, weight="bold")
            yy = para(axc, 1.6, yy + 0.2, f"「…{q[q.index('則為發熱'):]}」", w, 6)
            yy = para(axc, 1.6, yy + 0.8, "Critical objection: the link is restated after 960, so G6 fails and "
                      "the hypothesis is rejected.", w, 5.5, weight="bold", color=col)
            para(axc, 1.6, yy + 0.6, "Neither passage gives 理中 for fever itself: the rules read co-occurrence "
                 "as association (Supplementary Fig. 1).", w, 5.5, color=C["dark"])
    cv.label(2, 119.8, "e")
    return cv.save("fig3_end_to_end", HERE / "out")


if __name__ == "__main__":
    rep = main()
    print(json.dumps({k: rep[k] for k in ("width_mm", "height_mm", "warnings")}, ensure_ascii=False, indent=1))
