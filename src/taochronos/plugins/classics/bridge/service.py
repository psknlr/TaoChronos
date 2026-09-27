"""The ``bridge`` capability: the Ancient–Modern Bridge over the study layer's corpus (AMBE; S10 古代表型, S11 本体桥接,
S12 临床映射).

``phenotype`` reads a passage into its AncientPhenotypePacket; ``map`` scores it against the modern disease profiles and
says which findings carry each candidate, what would tell them apart, how the passage's historical names relate to the
modern ones, and a statement that passes the presentism guard; ``reverse`` goes from a modern disease back to the
passages and names; ``verify`` checks the HPO identifiers against a local release.  Rules first: with a model configured
(``study.judge``), it adjudicates the uncertain findings, may add missed ones, reviews the leading candidates (it can
lower a level, never raise it) and writes a cited summary that the guard then reads.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ....capabilities.judge import adjudicate, synthesize
from ....protocol.bridge import Strength, step_down
from ....verification.presentism import guard_from_pack
from .data import BridgeData, read_obo, verify, write_closure
from .mapping import LEVEL_LABEL, discriminators, rank, reverse, statement, term_relations
from .packet import PacketReader, quote

SYSTEM = ("你是医学史与临床表型的审读者。只依原文与给出的证据判断；古代描述与现代疾病之间只谈表型相似，"
          "不作回溯诊断，不把古病名等同于今病名。")


class BridgeService:
    def __init__(self, study: Any, root: str | Path | None = None) -> None:
        self.study = study
        pack = study.pack
        self.root = Path(root) if root else pack.root.parent / "bridge"
        self.data = BridgeData(self.root)
        self.reader = PacketReader(self.data, study.normalize, pack.terminology)
        self.guard = guard_from_pack(pack)
        self._cache: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------ reading
    def _source(self, passage_id: str) -> tuple[str, float | None, dict[str, Any]]:
        found = self.study.passages([passage_id])
        if not found:
            raise ValueError(f"no passage {passage_id!r}")
        p = found[0]
        w = self.study.witness(p, width=30)
        src = {k: w.get(k) for k in ("passage_id", "book_id", "title", "work", "locator", "period", "years", "layer")}
        return p.text, self.study.year(p), src

    def phenotype(self, text: str | None = None, *, passage_id: str | None = None, review: bool = True) -> dict[str, Any]:
        if passage_id:
            text, year, src = self._source(passage_id)
        elif text:
            year, src = None, None
        else:
            raise ValueError("give a text or a passage id")
        packet = self.reader.read(text, year=year, source=src)
        if review and self.study.judge is not None:
            packet = self.reader.review(packet, self.study.judge)
        for f in packet["findings"]:
            f["quote"] = quote(packet, f)
        return packet

    # ------------------------------------------------------------ mapping
    def map(self, text: str | None = None, *, passage_id: str | None = None, top: int = 5,
            systems: list[str] | None = None) -> dict[str, Any]:
        packet = self.phenotype(text, passage_id=passage_id)
        cands = rank(self.data, packet, top=top, systems=systems)
        where = f"{packet['source']['locator']}" if packet.get("source") else ""
        out: dict[str, Any] = {
            "packet": packet, "candidates": cands, "discriminators": discriminators(self.data, packet, cands),
            "terms": term_relations(self.data, packet, cands), "statement": statement(packet, cands, where),
            "ontology": {"hpo": self.data.hpo_release, "hierarchy": self.data.closure_release, "icd10": "WHO ICD-10 2019"},
            "calibration": ("not calibrated: levels are rules over the matched findings (high, moderate, low, insufficient), "
                            "not probabilities; no gold standard of historical descriptions with known modern diagnoses exists"),
        }
        judge = self.study.judge
        if judge is not None and cands:
            out["model_review"] = self._review(packet, cands, judge)
            out["statement"] = statement(packet, cands, where)
            out["summary"] = self._summary(packet, cands, out["terms"], judge)
        out["guard"] = [f.to_dict() for f in self.guard.check(out["statement"])]
        return out

    def _review(self, packet: dict[str, Any], cands: list[dict[str, Any]], judge: Any) -> dict[str, Any]:
        """The model reads the leading candidates against the text: it may lower a level (doubtful: one step,
        incompatible: two), never raise one."""
        lead = [c for c in cands if c["level"] != "insufficient"][:3]
        if not lead:
            return {"asked": 0, "note": "no candidate above insufficient"}
        items = [{"id": c["id"], "rule": "compatible", "candidate": c} for c in lead]
        text = packet["normalized"]
        findings = "；".join(f"{f['id']} {f['surface']}→{(f['hpo'] or {}).get('label', 'TCM')}（{f['relation']}"
                            + ("，否定" if f["negated"] else "") + ("，或然" if f["optional"] else "")
                            + ("，假设" if f["conditional"] else "") + "）" for f in packet["findings"])
        terms = "；".join(f"{t['term']}：{t.get('sense_label') or ''}" + (f"（{t['homonym']['note']}）" if t.get("homonym") else "")
                         for t in packet.get("terms", []))

        def render(group: list[dict[str, Any]]) -> str:
            lines = [f"原文：{text}", f"规则读出的症状：{findings}", *( [f"文中的历史名称：{terms}"] if terms else []),
                     "下列现代疾病是规则按表型相似排出的候选。逐项判断这种相似在原文语境中是否站得住（例如某症是否读错、"
                     "此段是否是辨证框架中的证候而非一个病人的病象、关键症状是否被否定）。不要作回溯诊断。"]
            for it in group:
                c = it["candidate"]
                matched = "、".join(f"{m['surface']}→{m['feature_label']}({m['tier']})" for m in c["matched"][:8])
                lines.append(f"- {c['id']} {c['label']}（{c['en']}）：强度 {c['level']}；相合：{matched}；"
                             f"缺典型症：{'、'.join(m['label'] for m in c['missing_typical'][:5]) or '无'}；冲突：{len(c['conflicts'])}")
            lines.append('答 {"decisions": [{"id": "D1", "verdict": "compatible|doubtful|incompatible", "reason": 引原文说明}]}')
            return "\n".join(lines)

        decisions, summary = adjudicate(judge, items, task="bridge.candidates", system=SYSTEM, render=render,
                                        allowed=["compatible", "doubtful", "incompatible"], value_key="verdict")
        by_id = {c["id"]: c for c in cands}
        for d in decisions:
            c = by_id[d.id]
            c["decided_by"] = d.decided_by
            if d.model:
                c["model_verdict"], c["model_reason"] = d.model, d.reason
            if d.final in ("doubtful", "incompatible"):
                lv = Strength(c["level"])
                lv = step_down(lv) if d.final == "doubtful" else step_down(step_down(lv))
                c["level"], c["level_zh"] = lv.value, LEVEL_LABEL[lv.value]
                c.setdefault("caps", []).append(f"lowered by the model's review: {d.reason}"[:200])
        return summary

    def _summary(self, packet: dict[str, Any], cands: list[dict[str, Any]], terms: list[dict[str, Any]], judge: Any) -> dict[str, Any]:
        src = packet.get("source") or {}
        evidence = [{"id": "P", "text": packet["normalized"][:400], "source": src.get("locator", "")}]
        evidence += [{"id": f["id"], "text": f"「{f['surface']}」→ {(f['hpo'] or {}).get('label', '无现代对应')}（{f['relation']}）"
                      + ("，被否定" if f["negated"] else "")} for f in packet["findings"] if f["status"] == "presenting"]
        evidence += [{"id": c["id"], "text": f"{c['label']}：表型相似强度 {c['level']}；相合 "
                      + "、".join(f"{m['surface']}→{m['feature_label']}" for m in c["matched"][:6])
                      + (f"；缺 {'、'.join(m['label'] for m in c['missing_typical'][:4])}" if c["missing_typical"] else "")}
                     for c in cands[:3]]
        evidence += [{"id": t["id"], "text": f"{t['term']}：" + "；".join(f"{r['label']} {r['relation']}" for r in t["relations"])}
                     for t in terms]
        syn = synthesize(judge, task="bridge.summary", system=SYSTEM, evidence=evidence, max_sentences=6,
                         question="概括这段古代描述与现代疾病之间的表型关系：哪些症状支持哪些候选、还缺什么、古今名称如何对应。",
                         instructions="用中文；只说表型相似，不说“即”“就是”“相当于”；指出强度未经校准。")
        out = syn.to_dict()
        kept, flagged = [], []
        for s in out.get("sentences", []):
            problems = self.guard.check(s["text"])
            (flagged if problems else kept).append({**s, **({"guard": [p.to_dict() for p in problems]} if problems else {})})
        out["sentences"], out["guard_dropped"] = kept, flagged
        out["ok"] = bool(kept)
        return out

    # ------------------------------------------------------------ reverse
    def reverse(self, disease: str, *, limit: int = 20) -> dict[str, Any]:
        d = self.data.find_disease(disease)
        if d is None:
            raise ValueError(f"no disease profile {disease!r} (see `taochronos bridge diseases`)")

        def read(pid: str) -> dict[str, Any] | None:
            if pid not in self._cache:
                try:
                    text, year, src = self._source(pid)
                except ValueError:
                    return None
                with self.study.rules_only():
                    packet = self.reader.read(text, year=year, source=src)
                self._cache[pid] = {"packet": packet, "witness": src, "period": src.get("period")}
            return self._cache[pid]

        return reverse(self.data, d, find=lambda s: self.study.find(s, limit=200), read_passage=read, limit=limit)

    # ------------------------------------------------------------ data
    def diseases(self) -> list[dict[str, Any]]:
        return [{**d.summary(), "typical": list(d.tiers["typical"].values())} for d in self.data.diseases.values()]

    def phenotypes(self) -> list[dict[str, Any]]:
        return [{"id": p.id, "label": p.label, "system": p.system, "hpo": p.hpo, "hpo_label": p.hpo_label,
                 "relation": p.relation.value, "surfaces": p.surfaces} for p in self.data.phenotypes.values()]

    def verify(self, obo: str | Path, *, write: bool = False) -> dict[str, Any]:
        release = read_obo(obo)
        out = verify(self.data, release)
        if write and not out["problems"]:
            out["closure"] = str(write_closure(self.data, release))
            self.data = BridgeData(self.root)
            self.reader = PacketReader(self.data, self.study.normalize, self.study.pack.terminology)
        return out


def render_map(r: dict[str, Any]) -> str:
    """The mapping as a page."""
    p = r["packet"]
    src = p.get("source") or {}
    lines = [f"# 古今映射{('：' + src['locator']) if src.get('locator') else ''}", "", f"> {p['normalized'][:200]}", "",
             r["statement"], ""]
    lines += ["## 古代表型包", "", "| | 原文 | 表型 | HPO | 关系 | 状态 |", "|---|---|---|---|---|---|"]
    for f in p["findings"]:
        state = "、".join(x for x, on in (("否定", f["negated"]), ("或然", f["optional"]), ("假设", f["conditional"]),
                                          ("待审", f["review"]), ("治后", f["status"] == "after_treatment"),
                                          ("预后", f["status"] == "prognosis"),
                                          ("剔除", f["status"] == "rejected")) if on) or "—"
        hpo = f"{f['hpo']['label']} ({f['hpo']['id']})" if f["hpo"] else "—"
        lines.append(f"| {f['id']} | {f['surface']} | {f['label']} | {hpo} | {f['relation']} | {state} |")
    if p.get("terms"):
        lines += ["", "## 历史名称", ""]
        for t in r["terms"]:
            rels = "；".join(f"{x['label']}：{x['relation']}" for x in t["relations"]) or "—"
            lines.append(f"- {t['term']}（{t.get('sense_label') or '未收义项'}，p={t.get('p')}）→ {rels}")
            for why in dict.fromkeys(w for x in t["relations"] for w in x["why"]):
                lines.append(f"  - {why}")
    lines += ["", "## 现代候选（表型相似，未校准）", ""]
    for c in r["candidates"]:
        lines.append(f"### {c['rank']}. {c['label']}（{c['en']}，ICD-10 {c['icd10']}）— {c['level_zh']}（fit {c['fit']}）")
        lines.append("")
        lines.append("- 相合：" + ("；".join(f"{m['surface']}→{m['feature_label']}（{m['tier']}，{m['relation']}，{m['hierarchy']}）"
                                          for m in c["matched"]) or "—"))
        if c["missing_typical"]:
            lines.append("- 缺典型：" + "；".join(m["label"] + (f"（古籍写作：{'、'.join(m['surfaces'][:3])}）" if m["surfaces"] else "（古籍无对应写法）")
                                              for m in c["missing_typical"]))
        if c["conflicts"]:
            lines.append("- 冲突：" + "；".join(f"{x['surface']}（{x['kind']}：{x['feature_label']}）" for x in c["conflicts"]))
        if c["compatibility"]["notes"]:
            lines.append("- 相容性：" + "；".join(c["compatibility"]["notes"]))
        if c.get("caps"):
            lines.append("- 限制：" + "；".join(c["caps"]))
        if c.get("model_verdict"):
            lines.append(f"- 模型复核：{c['model_verdict']}（{c.get('model_reason', '')}）")
        if c.get("tests"):
            lines.append(f"- 现代确诊所需：{c['tests']}")
        lines.append("")
    disc = [d for d in r["discriminators"] if "feature" in d]
    if disc:
        lines += ["## 鉴别所需", ""] + [f"- {d['label']}：见于{'、'.join(d['for'])}" + (f"，与{'、'.join(d['against'])}相悖" if d["against"] else "")
                                       + (f"；古籍写作 {'、'.join(d['ancient_forms'][:4])}" if d["ancient_forms"] else "；古籍无对应写法")
                                       for d in disc]
    if r.get("summary", {}).get("sentences"):
        lines += ["", "## 模型综述（引证）", ""] + [f"- {s['text']} [{', '.join(s['cites'])}]" for s in r["summary"]["sentences"]]
    lines += ["", f"*{r['calibration']}；HPO {r['ontology']['hpo']}。*"]
    return "\n".join(lines)


def render_reverse(r: dict[str, Any]) -> str:
    d = r["disease"]
    lines = [f"# 今病溯古：{d['label']}（{d['id']}，ICD-10 {d['icd10']}）", "", r["note"], "", "## 其症状在古籍中的写法", ""]
    lines += [f"- {k}：{'、'.join(v)}" for k, v in r["forms"].items()]
    if r["unobservable"]:
        lines += ["", "古籍无从观察：" + "、".join(r["unobservable"])]
    lines += ["", "## 相似的古代描述", ""]
    for p in r["passages"]:
        w = p.get("witness") or {}
        lines.append(f"- {w.get('locator', p['passage_id'])}（{p.get('period') or '?'}）fit {p['fit']}："
                     + "、".join(f"{m['surface']}→{m['feature']}" for m in p["matched"])
                     + (f"；名称：{'、'.join(p['terms'])}" if p["terms"] else ""))
    if r["names"]:
        lines += ["", "## 这些描述所用的名称（候选，非等同）", ""] + [f"- {n['term']}：{n['passages']} 段 {n['periods']}" for n in r["names"]]
    return "\n".join(lines)


__all__ = ["BridgeService", "render_map", "render_reverse"]
