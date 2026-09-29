"""Fig. 1 | TaoChronos (道乃久): agents propose, validators grade, experts decide, and every claim resolves to a verbatim
witness.

Drawn from the harness as configured (``source_data/fig1_architecture.json``, written by make_data.py from ``agents``,
``skills/manifests``, the tool mesh, the registered hooks, the gates and the event-authority table).
"""

from __future__ import annotations

import json
from pathlib import Path

from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Rectangle
from matplotlib.path import Path as MPath

from nature_style import C, Canvas, text_width_mm, tint, wrap_mm

HERE = Path(__file__).resolve().parent
SD = HERE / "source_data"
PT = 0.3528  # mm per point
COL = {"human": C["orange"], "agent": C["blue"], "validator": C["black"], "kernel": C["grey"]}
FILL = {"human": tint(C["orange"], 0.22), "agent": tint(C["blue"], 0.10), "validator": tint(C["black"], 0.07),
        "kernel": tint(C["grey"], 0.22), "tools": "white"}
PERM = {"classics:read": "C", "kg:read": "K", "kg:propose": "P", "analysis:run": "A", "literature:read": "L",
        "codemode:exec": "X", "validation:run": "V"}
JOB = {"director": "plans rounds, picks agents", "meta_reviewer": "weak points, next round",
       "curator": "freezes scope and coverage", "philologist": "readings, variants, collation",
       "semanticist": "period-bound senses of terms", "extractor": "claims with verbatim spans",
       "lineage": "citation and transcription links", "scholar": "textual history of focus terms",
       "evidence": "verbatim, locatable evidence", "pattern_miner": "discovery engines D1–D5",
       "statistician": "tests, FDR, coverage", "evolution": "concept and formula timelines",
       "hypothesis": "testable hypotheses, revisions", "skeptic": "attacks every hypothesis",
       "ontologist": "ancient–modern mappings", "modern_evidence": "sole door to modern data"}
NAME = {"director": "Director", "meta_reviewer": "Meta-reviewer", "pattern_miner": "Pattern miner",
        "modern_evidence": "Modern evidence"}


def rbox(ax, x, y, w, h, *, fc="white", ec=None, lw=0.5, r=0.7, ls="-"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}", facecolor=fc,
                                edgecolor=ec or C["black"], lw=lw, linestyle=ls))


def arrow(ax, p0, p1, color=None, lw=0.6, style="-|>"):
    ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle=f"{style},head_length=1.4,head_width=0.75", mutation_scale=1,
                                 lw=lw, color=color or C["black"], shrinkA=0, shrinkB=0))


def para(ax, x, y, s, width, fs=5.0, *, weight="normal", color="black", lh=1.2, ha="left"):
    lines = wrap_mm(s, width, fs, weight)
    ax.text(x, y, "\n".join(lines), ha=ha, va="top", fontsize=fs, fontweight=weight, color=color, linespacing=lh)
    return y + len(lines) * fs * PT * lh


def agent_box(ax, x, y, w, h, a):
    rbox(ax, x, y, w, h, fc="white", ec=COL["agent"], lw=0.5, r=0.6)
    name = NAME.get(a["role"], a["role"].capitalize())
    ax.text(x + 1.0, y + 0.7, name, ha="left", va="top", fontsize=5.5, fontweight="bold")
    ax.text(x + 1.0, y + 3.35, JOB[a["role"]], ha="left", va="top", fontsize=5)
    if text_width_mm(JOB[a["role"]], 5) > w - 1.6:
        print(f"  ! job of {a['role']} is wider than its box")
    # mode: filled, may call a model where the rules are uncertain; open, rules only
    hybrid = a["mode"] == "hybrid"
    ax.add_patch(Circle((x + w - 1.3, y + 1.55), 0.55, facecolor=COL["agent"] if hybrid else "white",
                        edgecolor=COL["agent"], lw=0.4))
    perms = " ".join(PERM[p] for p in sorted(a["permissions"], key=list(PERM).index))
    ax.text(x + w - 2.4, y + 1.55, perms, ha="right", va="center", fontsize=5, color=C["dark"])


def lane(ax, y, h, name, key):
    ax.add_patch(Rectangle((0, y), 179, h, facecolor=FILL[key], edgecolor="none"))
    ax.text(1.0, y + h / 2, name, ha="left", va="center", fontsize=5.5, fontweight="bold",
            color="black" if key != "human" else "black", linespacing=1.1)


def main() -> dict:
    arch = json.loads((SD / "fig1_architecture.json").read_text(encoding="utf-8"))
    agents = {a["role"]: a for a in arch["agents"]}
    tools = arch["tools"]
    hooks = arch["hooks"]
    cv = Canvas("double", 166)

    # a — the harness ----------------------------------------------------------------------------------------------------
    ax = cv.blank(2, 6, 179, 96)
    X0, G = 13.5, 1.2
    widths = [27.0, 57.0, 28.5, 23.0, 24.4]
    S, x = {}, X0
    for k, w in enumerate(widths):
        S[k] = (x, w)
        x += w + G
    END = S[4][0] + S[4][1]
    Y = {"human": (0.0, 11.4), "agent": (12.6, 30.2), "kernel": (48.6, 8.4), "validator": (58.2, 12.2),
         "tools": (71.6, 16.6)}
    lane(ax, *Y["human"], "Human\ndecides", "human")
    lane(ax, *Y["agent"], "Agents\npropose", "agent")
    lane(ax, *Y["kernel"], "Kernel\nrecords", "kernel")
    lane(ax, *Y["validator"], "Validators\ngrade", "validator")
    ax.add_patch(Rectangle((0, Y["tools"][0]), 179, Y["tools"][1], facecolor="white", edgecolor=C["grey"], lw=0.4))
    ax.text(1.0, Y["tools"][0] + Y["tools"][1] / 2, "Tools\nand data", ha="left", va="center", fontsize=5.5,
            fontweight="bold", linespacing=1.1)

    def titled(x, y, w, h, title, body, ec, fc="white", ls="-"):
        rbox(ax, x, y, w, h, fc=fc, ec=ec, lw=0.55, ls=ls)
        ax.text(x + 1.0, y + 0.7, title, ha="left", va="top", fontsize=5.5, fontweight="bold")
        end = para(ax, x + 1.0, y + 3.2, body, w - 2.0)
        if end > y + h + 0.2:
            print(f"  ! text leaves the box '{title}' by {end - y - h:.1f} mm")

    # human: the scientist writes the contract before work begins; the expert judges what the machine could not
    hy, hh = Y["human"][0] + 0.9, Y["human"][1] - 1.8
    titled(S[0][0], hy, S[0][1], hh, "Scientist", "asks the question and scopes it in time", COL["human"])
    titled(S[1][0], hy, S[1][1], hh, "Research contract", "focus terms, forbidden equivalences, tracks, required "
           "gates, acceptance criteria and stop rule, hashed before the first task", COL["human"])
    para(ax, S[2][0] + 0.3, hy + 0.6, "A human writes no claim or hypothesis; an agent grades nothing",
         S[2][1] - 0.3, color=C["dark"])
    titled(S[3][0], hy, END - S[3][0], hh, "Expert", "alone sets G7, closes interpretive objections, approves "
           "changes to canonical knowledge", COL["human"])

    # agents, by the stage of a round at which they work
    ay = Y["agent"][0]
    heads = {0: "Plan and reflect", 1: "Read (from round 0)", 2: "Discover (from round 1)", 3: "Criticize",
             4: "Translate (if asked)"}
    for k, t in heads.items():
        ax.text(S[k][0] + 0.2, ay + 0.9, t, ha="left", va="top", fontsize=5.5, fontweight="bold",
                color=COL["agent"])
    bh, step = 6.0, 6.45
    r0 = ay + 3.6
    half = (S[1][1] - G) / 2
    place = {(S[0][0], S[0][1]): ["director", "meta_reviewer"],
             (S[1][0], half): ["curator", "philologist", "semanticist", "extractor"],
             (S[1][0] + half + G, half): ["lineage", "scholar", "evidence"],
             (S[2][0], S[2][1]): ["pattern_miner", "statistician", "evolution", "hypothesis"],
             (S[3][0], S[3][1]): ["skeptic"], (S[4][0], S[4][1]): ["ontologist", "modern_evidence"]}
    boxes = {}
    for (x, w), roles in place.items():
        for i, role in enumerate(roles):
            agent_box(ax, x, r0 + i * step, w, bh, agents[role])
            boxes[role] = (x, r0 + i * step, w)
    sx, sy, sw = boxes["skeptic"]
    para(ax, sx + 0.3, sy + bh + 0.9, "objections go back to the Hypothesis agent, which may only narrow the claim",
         sw - 0.3, color=C["dark"])
    hx, hy2, hw = boxes["hypothesis"]
    gx = sx - G / 2
    ax.add_patch(FancyArrowPatch(path=MPath([(sx - 0.1, sy + bh / 2), (gx, sy + bh / 2), (gx, hy2 + bh / 2),
                                             (hx + hw + 0.1, hy2 + bh / 2)]),
                                 arrowstyle="<|-|>,head_length=1.1,head_width=0.6", mutation_scale=1, lw=0.5,
                                 color=COL["agent"]))
    para(ax, S[0][0] + 0.3, r0 + 2 * step + 0.4, "a new round until the contract's stop rule is met", S[0][1] - 0.5,
         color=C["dark"])
    para(ax, S[4][0] + 0.3, r0 + 2 * step + 0.4, "historical hypotheses mark G8 not applicable", S[4][1] - 0.5,
         color=C["dark"])
    # hooks where agents write: on the boundary between the agents and the log
    hk = Y["kernel"][0] - 0.7
    commit = " · ".join(h.replace("_validator", "").replace("_guard", "").replace("_", " ")
                        for h in hooks.get("BeforeClaimCommit", []))
    ax.text(S[1][0] + 0.5, hk, f"▼ BeforeClaimCommit: {commit}", ha="left", va="bottom", fontsize=5,
            color=C["vermillion"])
    ax.text(S[2][0] + 0.5, hk, "▼ AfterHypothesis: anachronism", ha="left", va="bottom", fontsize=5,
            color=C["vermillion"])
    ax.text(END - 0.3, hk, "▼ BeforeGraphWrite: anachronism", ha="right", va="bottom", fontsize=5,
            color=C["vermillion"])

    # kernel: the event log
    ky, kh = Y["kernel"][0] + 0.9, Y["kernel"][1] - 1.8
    rbox(ax, S[0][0], ky, END - S[0][0], kh, fc="white", ec=C["dark"], lw=0.55)
    ax.text(S[0][0] + 1.0, ky + 0.7, f"Append-only event log ({len(arch['authority'])} event types)", ha="left",
            va="top", fontsize=5.5, fontweight="bold")
    ax.text(S[0][0] + 1.0, ky + kh - 0.6, "every event carries its principal, and the reducer refuses one that its "
            "principal may not emit (b); state is replayed and hashed every round; budgets, checkpoints and the stop "
            "rule are the kernel's", ha="left", va="bottom", fontsize=5)

    # validators
    vy, vh = Y["validator"][0] + 0.9, Y["validator"][1] - 1.8
    titled(S[0][0], vy, S[0][1], vh, "Gates G0–G8", "per claim, evidence and hypothesis; G7 only by the expert",
           C["black"])
    titled(S[1][0], vy, S[1][1], vh, "Claim validation", "the passage exists, the quote is verbatim at its span, and "
           "the quote states the claim; otherwise the claim is rejected", C["black"])
    titled(S[2][0], vy, S[2][1], vh, "Scores and ranks", "discovery score and Elo; a ranking, never a truth value",
           C["black"])
    titled(S[3][0], vy, S[3][1], vh, "Objections", "a hard one closes only when its check re-runs and passes",
           C["black"])
    titled(S[4][0], vy, S[4][1], vh, "Contract verdict", "accepted, needs expert, inconclusive or rejected",
           C["black"])
    ax.text(END - 0.3, Y["validator"][0] + 0.15, "▼ BeforeArtifactPublish: publish guard", ha="right",
            va="bottom", fontsize=5, color=C["vermillion"])

    # tools and data
    ty, th = Y["tools"][0] + 1.0, Y["tools"][1] - 2.0
    titled(S[0][0], ty, S[0][1], th, "Corpus store", "dated, layered witnesses, read only through scoped views "
           "(past views for blind tests)", C["blue"], fc=tint(C["blue"], 0.10))
    fam = {}
    for t in tools:
        fam.setdefault((t["family"], t["permission"]), []).append(t["name"])
    chips = [("retrieval", "classics:read", "search, passages, lineage"), ("study", "classics:read", "the study layer"),
             ("philology", "classics:read", "collation, page images"), ("knowledge", "kg:read", "claims, terms"),
             ("knowledge", "kg:propose", "propose a change"), ("analytics", "analysis:run", "D1–D5 engines"),
             ("validation", "classics:read", "quote checks, audit"), ("validation", "validation:run", "gates"),
             ("bridge", "classics:read", "ancient phenotypes"), ("literature", "literature:read", "modern evidence"),
             ("research", "codemode:exec", "sandboxed code")]
    assert sum(len(v) for v in fam.values()) == len(tools) and len(fam) == len(chips)
    tx0 = S[1][0]
    ax.text(tx0 + 0.2, ty + 0.7, f"Tool mesh: {len(tools)} tools, each behind one permission; every call passes the "
            "BeforeToolCall scope guard and the AfterToolCall result firewall", ha="left", va="top", fontsize=5.5,
            fontweight="bold")
    cwid = (END - tx0 - 5 * 1.0) / 6
    for i, (f, perm, what) in enumerate(chips):
        r, c = divmod(i, 6)
        x = tx0 + c * (cwid + 1.0)
        yy = ty + 3.5 + r * 5.9
        rbox(ax, x, yy, cwid, 5.5, fc="white", ec=C["grey"], lw=0.4, r=0.5)
        ax.text(x + 0.9, yy + 0.55, f"{f} {len(fam[(f, perm)])}", ha="left", va="top", fontsize=5.5,
                fontweight="bold")
        ax.text(x + cwid - 0.9, yy + 0.55, PERM[perm], ha="right", va="top", fontsize=5, color=C["dark"])
        ax.text(x + 0.9, yy + 3.05, what, ha="left", va="top", fontsize=5)
    # legend
    ly = Y["tools"][0] + Y["tools"][1] + 2.3
    ax.add_patch(Circle((1.6, ly), 0.55, facecolor=COL["agent"], edgecolor=COL["agent"], lw=0.4))
    t1 = "may consult a model where the rules leave a case uncertain"
    ax.text(2.8, ly, t1, ha="left", va="center", fontsize=5)
    x2 = 2.8 + text_width_mm(t1, 5) + 3.0
    ax.add_patch(Circle((x2, ly), 0.55, facecolor="white", edgecolor=COL["agent"], lw=0.4))
    ax.text(x2 + 1.2, ly, "rules only", ha="left", va="center", fontsize=5)
    x3 = x2 + 1.2 + text_width_mm("rules only", 5) + 3.5
    ax.text(x3, ly, "Permissions: C classics:read · K kg:read · P kg:propose · A analysis:run · L literature:read · "
            "X codemode:exec · V validation:run", ha="left", va="center", fontsize=5, color=C["dark"])
    g = arch["gates"]
    gate_names = {"G1": "transcription", "G3": "sense", "G5": "independent sources", "G8": "modern evidence"}
    ax.text(1.0, ly + 2.6, "Gates: " + ", ".join(f"{k} {gate_names.get(k, v.lower())}" for k, v in g.items()),
            ha="left", va="center", fontsize=5, color=C["dark"])
    cv.label(2, 3, "a")

    # b — who may emit what --------------------------------------------------------------------------------------------
    ax = cv.blank(2, 108, 96, 58)
    groups = [
        (("agent", "kernel", "validator"), "Plan and run tasks; scope the corpus; propose evidence, claims, lineage, "
                                           "observations; generate, review and revise hypotheses"),
        (("agent", "human", "kernel", "validator"), "Call tools; record a decision; propose a change"),
        (("agent", "kernel"), "Call a model"),
        (("kernel", "validator"), "Grade: gates, scores, ranks, confirmation; evaluate the contract; publish"),
        (("human", "kernel", "validator"), "Reject a hypothesis; retract evidence; write memory"),
        (("human", "validator"), "Close an objection; approve or reject a change"),
        (("human",), "Approve or reject a hypothesis (G7); steer a research"),
        (("human", "kernel"), "Stop a research"),
        (("kernel",), "Open the contract, run rounds, spawn agents, route models, budget, checkpoint, complete"),
    ]
    count = {}
    for e, ps in arch["authority"].items():
        count[tuple(sorted(ps))] = count.get(tuple(sorted(ps)), 0) + 1
    cols = [("agent", "Agent"), ("validator", "Validator"), ("human", "Human"), ("kernel", "Kernel")]
    cx0, cwb = 62.5, 8.7
    for j, (k, lab) in enumerate(cols):
        ax.text(cx0 + j * cwb, 3.6, lab, ha="center", va="bottom", fontsize=5.5, fontweight="bold", color=C["black"])
    ax.text(0, 3.6, "Events a principal may emit (count)", ha="left", va="bottom", fontsize=5.5, fontweight="bold")
    ax.plot([0, 94], [4.2, 4.2], color="black", lw=0.5)
    yy = 5.3
    for ps, desc in groups:
        key = tuple(sorted(ps))
        lines = wrap_mm(f"{desc} ({count.get(key, 0)})", cx0 - cwb / 2 - 1.5, 5.0)
        hrow = max(len(lines), 1) * 5.0 * PT * 1.2 + 1.3
        ax.text(0, yy + 0.4, "\n".join(lines), ha="left", va="top", fontsize=5, linespacing=1.2)
        for j, (k, _) in enumerate(cols):
            on = k in ps
            ax.add_patch(Circle((cx0 + j * cwb, yy + hrow / 2 - 0.2), 0.9 if on else 0.35,
                                facecolor=COL[k] if on else C["light"], edgecolor="none"))
        yy += hrow
        ax.plot([0, 94], [yy - 0.2, yy - 0.2], color=C["light"], lw=0.3)
    why = arch["why"]
    para(ax, 0, yy + 0.8, f"Gate results: {why['GateEvaluated']}. Objections: {why['ObjectionClosed']}. Only a human "
         "expert sets G7.", 94, 5.0, color=C["dark"])
    cv.label(2, 104, "b")

    # c — one clause, three witnesses, and the chain from a claim to its licence -----------------------------------------
    ax = cv.blank(102, 108, 79, 58)
    deng = "男子消渴小便反多以飲一斗小便一斗腎氣丸主之"
    wuq = "男子消渴小便反多以飲一斗" + "    " + "腎氣丸主之"
    maij = "男子消渴小便反多以飲一斗小便一斗腎氣圎主之"
    cols_ = len(deng)
    cw, rh = 2.45, 3.1
    gx, gy = 23.5, 6.2
    wits = [("Deng Zhen print, 1340", deng), ("Wu Qian manuscript, 1395", wuq), ("Maijing, Yuan print, 1330", maij)]
    var_cols = [j for j in range(cols_) if len({w[1][j] for w in wits}) > 1]
    for j in var_cols:
        ax.add_patch(Rectangle((gx + j * cw, gy - 0.3), cw, rh * 3 + 0.6, facecolor=tint(C["vermillion"], 0.18),
                               edgecolor="none"))
    for i, (name, text) in enumerate(wits):
        yc = gy + i * rh + rh / 2
        ax.text(gx - 1.0, yc, name, ha="right", va="center", fontsize=5)
        for j, ch in enumerate(text):
            if ch == " ":
                ax.plot([gx + j * cw + 0.6, gx + (j + 1) * cw - 0.6], [yc, yc], color=C["dark"], lw=0.5)
            else:
                ax.text(gx + j * cw + cw / 2, yc, ch, ha="center", va="center", fontsize=6)
    ax.text(gx + 14 * cw, gy - 1.2, "omission (脱)", ha="center", va="bottom", fontsize=5)
    ax.text(gx + 18 * cw + cw / 2, gy - 1.2, "丸 → 圎", ha="center", va="bottom", fontsize=5)
    ax.text(0, 0.8, "Jingui yaolüe ch. 13 on xiaoke 消渴 in three witnesses (punctuation removed)", ha="left",
            va="center", fontsize=5.5)
    gb = gy + 3 * rh + 0.8
    ax.text(gx + cols_ * cw, gb, "圎 for 丸 avoids the name of Emperor Qinzong (桓, from 1126): that witness\n"
                                 "descends from an edition made after 1126", ha="right", va="top", fontsize=5,
            color=C["dark"], linespacing=1.15)
    chain = [("Claim", "Shenqi wan 肾气丸 indicated for 消渴 with polyuria"),
             ("Quote", "男子消渴，小便反多，以飲一斗，小便一斗，腎氣丸主之"),
             ("Passage", "cm_jingui_dengzhen.00712"),
             ("Locator", "卷中 · 消渴小便利淋病脉證并治第十三 · p. 100"),
             ("Witness", "Deng Zhen print, 1340; Peking University Library"),
             ("Work · layer", "Jingui yaolüe, 200–219 · main text"),
             ("Source · licence", "CMETA, collated page by page · CC BY 4.0"),
             ("Check in chat", "✓ verbatim    ≠ quote differs    × no such passage")]
    cy, stepc = gb + 5.8, 3.95
    ax.plot([1.6, 1.6], [cy, cy + (len(chain) - 1) * stepc], color=C["blue"], lw=0.6)
    for k, (key, val) in enumerate(chain):
        yk = cy + k * stepc
        ax.add_patch(Circle((1.6, yk), 0.6, facecolor=C["blue"], edgecolor="none", zorder=3))
        ax.text(3.4, yk, key, ha="left", va="center", fontsize=5.5, fontweight="bold")
        ax.text(21.0, yk, val, ha="left", va="center", fontsize=5.5)
    cv.label(100, 104, "c")
    return cv.save("fig1_architecture", HERE / "out")


if __name__ == "__main__":
    rep = main()
    print(json.dumps({k: rep[k] for k in ("width_mm", "height_mm", "warnings")}, ensure_ascii=False, indent=1))
