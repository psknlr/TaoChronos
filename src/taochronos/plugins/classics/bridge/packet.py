"""古籍表型包 — the AncientPhenotypePacket: the findings a passage states, read by rules, with what bounds each of them.

Reading (rules):

1. the text is normalised (variant forms) and the phrases that state no finding are blocked (利小便, 汗出而解, 热中 …);
2. written forms are matched longest first; a one-character form (渴, 利, 热) only at a clause boundary; a form mapped to
   two phenotypes (咳唾脓血: hemoptysis and purulent sputum) gives both; a form read two ways (不得卧: orthopnea or
   insomnia) takes the reading whose cues stand in the same sentence, or its default, marked for review;
3. each finding is bounded: negated (不渴, 无大热, 不能发黄), optional (或渴), conditional (若…者), after treatment
   (服之则…); its severity, frequency and timing are read from its clause;
4. the passage as a whole: its course (久, 卒), the population it speaks of (男子, 妇人, 小儿), whether it is a drug's or a
   formula's indications rather than one patient's picture, and the historical terms it names (消渴, 中风, 霍乱) with the
   sense the context selects (the terminology's period-bound senses) and the homonym warnings.

A model, when one is configured, then reviews what the rules leave uncertain (the ambiguous readings, the one-character
forms, the forms whose relation depends on context) and may add findings the forms missed — as exact spans of the text
and phenotype ids from the map, validated before they are taken.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from ....capabilities.judge import adjudicate
from ....protocol.bridge import BridgeRelation
from .data import BridgeData

CLAUSE = re.compile(r"[，,、。；;：:？！?!\s（）()「」“”【】〔〕《》〈〉]")
SENTENCE_END = "。；;？！?!"
HAN = re.compile(r"[㐀-鿿]")
BOUNDARY_BEFORE = set("而则或且反又必但甚微大时亦若复更犹即，。；、：？！ 【】〔〕（）") | {""}
BOUNDARY_AFTER = set("者而不甚止已也矣则或，。；、：？！ 【】〔〕（）") | {""}
# after a one-character form, a verb of pathogenesis makes it a cause, not a finding (热迫阴血, 热蓄膀胱, 热入血室)
CAUSE_AFTER = set("迫蓄入结郁盛伤在毒邪")
NEGATORS_INFIX = "不无"
AFTER_TREATMENT = ("服之", "服汤", "服已", "得汤", "饮已", "药后", "服后", "服药")
INDICATION = re.compile(r"^[^，。：:]{1,8}，味[^，。]{1,4}[，。]|^[^。]{0,12}味[甘苦辛酸咸淡涩][^。]{0,4}[平温寒凉热]|"
                        r"^[^，。：:]{2,12}(?:汤|散|丸|饮|丹|膏)[：:，,][^。]{0,6}治|主治")
# a finding the text gives as what the illness will become, not as what the patient has (故其气上溢，转为消渴)
PROGNOSIS = re.compile(r"(?:转为|变为|传为|转成|变成|发为|久则|将为|恐成|遂成|乃成)$")
TERM_CATEGORIES = ("disease", "symptom", "sign", "pattern", "disease_class")
MARKS = re.compile(r"[，。、；：？！,.;:?!\s]")


class PacketReader:
    def __init__(self, data: BridgeData, normalize: Callable[[str], str], terminology: Any = None) -> None:
        self.data = data
        self.normalize = normalize
        self.terminology = terminology
        # the written forms as the normalised text spells them (瞤→𥆧, 鞕→硬, 癥→症): normalised form → (form, phenotypes)
        self.index: dict[str, tuple[str, list[str]]] = {}
        for form, pids in data.by_surface.items():
            key = normalize(form)
            old = self.index.get(key)
            self.index[key] = (form, [*dict.fromkeys([*(old[1] if old else []), *pids])])
        self.ambiguous = {normalize(k): v for k, v in data.ambiguous.items()}
        self.blocked = sorted({normalize(b) for b in data.blocked}, key=len, reverse=True)
        self.max_len = max((len(k) for k in self.index), default=1)

    # ------------------------------------------------------------ rules
    def read(self, text: str, *, year: float | None = None, source: dict[str, Any] | None = None) -> dict[str, Any]:
        norm = self.normalize(text)
        if len(norm) != len(text):  # offsets refer to the normalised text; quotes are taken from it
            text = norm
        findings = self._scan(norm)
        for k, f in enumerate(findings, 1):
            f["id"] = f"F{k}"
        course = sorted({v for k, v in self.data.modifiers.get("course", {}).items() if k in norm}
                        | {k for k, pats in self.data.course_patterns.items() if any(pt.search(norm) for pt in pats)})
        population = sorted({v for k, v in self.data.population.items() if k in norm})
        kind = "indication" if INDICATION.search(norm) else "description"
        terms = self._terms(norm, findings, year)
        implied = self._implied(terms)
        projected = [f for f in findings if f["hpo"] and not f["negated"] and f["status"] == "presenting"]
        return {
            "text": text, "normalized": norm, "kind": kind, "year": year, **({"source": source} if source else {}),
            "findings": findings, "terms": terms, "implied": implied,
            "context": {"course": course, "population": population},
            "counts": {"findings": len(findings), "projected": len(projected),
                       "negated": sum(1 for f in findings if f["negated"]),
                       "tcm_only": sum(1 for f in findings if not f["hpo"]),
                       "uncertain": sum(1 for f in findings if f["review"]), "implied": len(implied)},
            "review": None,
            "note": ("findings as the text states them, each with its HPO projection and relation; negated, optional and "
                     "conditional findings are kept apart from the presenting picture; `implied` are the findings a named "
                     "disease entails by its curated sense (counted at half weight, never alone for more than moderate)"),
        }

    def _implied(self, terms: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The findings a historical name entails by the sense the context selected (霍乱#吐利: 呕吐而利)."""
        out: list[dict[str, Any]] = []
        if self.terminology is None:
            return out
        for t in terms:
            sense = self.terminology.sense(t["sense"]) if t.get("sense") else None
            if sense is None:
                continue
            gloss = self.normalize(f"{sense.label.split('：', 1)[-1]}，{sense.gloss}")
            for f in self._scan(gloss):
                if f["negated"] or not f["hpo"] or f["status"] != "presenting":
                    continue
                if any(o["phenotype"] == f["phenotype"] for o in out):
                    continue
                f.update({"status": "implied", "weight": 0.5, "implied_by": t["id"], "source": f"sense:{sense.id}",
                          "review": False, "clause": gloss})
                out.append(f)
        for k, f in enumerate(out, 1):
            f["id"] = f"I{k}"
        return out

    def _scan(self, norm: str) -> list[dict[str, Any]]:
        n = len(norm)
        blocked = [False] * n
        for phrase in self.blocked:
            start = norm.find(phrase)
            while start >= 0:
                for k in range(start, start + len(phrase)):
                    blocked[k] = True
                start = norm.find(phrase, start + 1)
        clauses = self._clauses(norm)
        findings: list[dict[str, Any]] = []
        i = 0
        while i < n:
            if blocked[i] or not HAN.match(norm[i]):
                i += 1
                continue
            hit = None
            for length in range(min(self.max_len, n - i), 0, -1):
                s = norm[i: i + length]
                if s in self.index and not any(blocked[i: i + length]):
                    if length == 1 and not self._bounded(norm, i):
                        continue
                    hit = s
                    break
            if hit is None:
                form = self._infix(norm, i, blocked)
                if form is None:
                    i += 1
                    continue
                clause = next(c for c in clauses if c["start"] <= i < c["end"])
                for pid, reading, uncertain in self._readings(form, norm, i):
                    f = self._finding(pid, form, i, norm, clause, reading, uncertain)
                    f.update({"surface": norm[i: i + len(form) + 1], "span": [i, i + len(form) + 1], "negated": True})
                    findings.append(f)
                i += len(form) + 1
                continue
            clause = next(c for c in clauses if c["start"] <= i < c["end"])
            for pid, reading, uncertain in self._readings(hit, norm, i):
                findings.append(self._finding(pid, hit, i, norm, clause, reading, uncertain))
            i += len(hit)
        return findings

    def _clauses(self, norm: str) -> list[dict[str, Any]]:
        out, start, sentence_cond = [], 0, False
        for k, ch in enumerate(norm + "。"):
            if k < len(norm) and not CLAUSE.match(ch):
                continue
            if k > start:
                body = norm[start:k]
                listed = start > 0 and norm[start - 1] == "、" and bool(out)  # 或心下悸、小便不利: the list goes on
                opener_opt = any(body.startswith(o) for o in self.data.optional) or (listed and out[-1]["optional"])
                opener_cond = any(body.startswith(c) for c in self.data.conditional)
                sentence_cond = sentence_cond or opener_cond
                after = any(body.startswith(a) for a in AFTER_TREATMENT) or (out and out[-1]["after"] and not opener_cond
                                                                           and not out[-1]["end_sentence"])
                out.append({"start": start, "end": k, "text": body, "optional": opener_opt, "conditional": sentence_cond,
                            "after": bool(after), "end_sentence": k >= len(norm) or norm[k] in SENTENCE_END})
            if k < len(norm) and norm[k] in SENTENCE_END:
                sentence_cond = False
            start = k + 1
        if not out:
            out.append({"start": 0, "end": len(norm), "text": norm, "optional": False, "conditional": False, "after": False,
                        "end_sentence": True})
        # a clause boundary inside a finding's span never happens (forms carry no marks), but a finding may sit between
        # clauses when the text has none: the whole text is one clause then
        return out

    def _bounded(self, norm: str, i: int) -> bool:
        before = norm[i - 1] if i > 0 else ""
        after = norm[i + 1] if i + 1 < len(norm) else ""
        if after in CAUSE_AFTER:
            return False
        return before in BOUNDARY_BEFORE or after in BOUNDARY_AFTER or bool(self.data.negation.search(norm[max(0, i - 3): i]))

    def _infix(self, norm: str, i: int, blocked: list[bool]) -> str | None:
        """A two-part form with a negator inside it (腹不满, 口不渴, 头不痛): the form, read negated."""
        if i + 2 >= len(norm) or norm[i + 1] not in NEGATORS_INFIX:
            return None
        for k in range(min(3, len(norm) - i - 2), 0, -1):
            form = norm[i] + norm[i + 2: i + 2 + k]
            if form in self.index and len(form) >= 2 and not any(blocked[i: i + 2 + k]):
                return form
        return None

    def _readings(self, surface: str, norm: str, i: int) -> list[tuple[str, str | None, bool]]:
        """(phenotype id, the ambiguous reading's cue, needs review)."""
        amb = self.ambiguous.get(surface)
        if amb is None:
            form, pids = self.index[surface]
            single = len(surface) == 1
            return [(pid, None, single or self.data.phenotypes[pid].relation_of(form) in (
                BridgeRelation.CONTEXT_DEPENDENT, BridgeRelation.HISTORICAL_SEMANTIC_SHIFT)) for pid in pids]
        left = max(norm.rfind(ch, 0, i) for ch in SENTENCE_END)
        rights = [p for p in (norm.find(ch, i) for ch in SENTENCE_END) if p >= 0]
        sentence = norm[left + 1: min(rights) if rights else len(norm)].replace(surface, "")
        scores = {r: sum(1 for c in cues if c in sentence) for r, cues in amb["readings"].items()}
        best = max(scores.values()) if scores else 0
        winners = [r for r, v in scores.items() if v == best and v > 0]
        if len(winners) == 1:
            cue = next(c for c in amb["readings"][winners[0]] if c in sentence)
            return [(winners[0], cue, False)]
        return [(amb["default"], None, True)]

    def _finding(self, pid: str, surface: str, i: int, norm: str, clause: dict[str, Any], cue: str | None,
                 uncertain: bool) -> dict[str, Any]:
        p = self.data.phenotypes[pid]
        rel = p.relation_of(self.index.get(surface, (surface,))[0])
        before = norm[max(clause["start"], i - 4): i]
        negated = bool(self.data.negation.search(before)) and not surface.startswith(("不", "无", "未"))
        mods: dict[str, str] = {}
        near = norm[max(clause["start"], i - 2): i] + (surface[0] if surface[0] in "大壮微甚" and len(surface) > 1 else "")
        for key, value in self.data.modifiers.get("severity", {}).items():
            if key in near:
                mods["severity"] = value
                break
        rest = clause["text"].replace(surface, "", 1)
        for group in ("frequency", "timing"):
            for key, value in sorted(self.data.modifiers.get(group, {}).items(), key=lambda kv: -len(kv[0])):
                if key in rest:
                    mods[group] = value
                    break
        status = "after_treatment" if clause["after"] else "presenting"
        if status == "presenting" and PROGNOSIS.search(norm[max(clause["start"], i - 3): i]):
            status = "prognosis"
        weight = 1.0
        if clause["conditional"]:
            weight = 0.4
        elif clause["optional"]:
            weight = 0.5
        return {
            "phenotype": pid, "label": p.label, "surface": surface, "span": [i, i + len(surface)],
            "clause": clause["text"], "system": p.system,
            "hpo": {"id": p.hpo, "label": p.hpo_label, "relation": rel.value, **({"note": p.note} if p.note else {})} if p.hpo else None,
            "relation": rel.value, "negated": negated, "optional": clause["optional"], "conditional": clause["conditional"],
            "status": status, "weight": weight, "modifiers": mods,
            **({"reading_cue": cue} if cue else {}), "review": uncertain, "source": "rule",
        }

    def _terms(self, norm: str, findings: list[dict[str, Any]], year: float | None) -> list[dict[str, Any]]:
        """The historical terms the passage names, with the sense its context selects and the homonym warnings."""
        out: list[dict[str, Any]] = []
        context = {f["surface"] for f in findings} | {f["label"] for f in findings}
        seen: set[str] = set()
        terms = getattr(self.terminology, "terms", {}) if self.terminology is not None else {}
        homonyms = {h["term"]: h for h in self.data.homonyms}
        for term in sorted(set(terms) | set(homonyms), key=len, reverse=True):
            if term in seen or term not in norm:
                continue
            if any(term in s and term != s for s in seen):  # 半身不遂 inside a longer named term
                continue
            seen.add(term)
            row: dict[str, Any] = {"term": term, "at": norm.find(term)}
            ht = terms.get(term)
            if ht is not None and ht.category not in TERM_CATEGORIES and term not in homonyms:
                continue
            if ht is not None and getattr(ht, "senses", None):
                sense, p, alts, why = self.terminology.resolve(term, norm, context, year)
                s = self.terminology.sense(sense) if sense else None
                meta = self.terminology.sense_meta.get(sense, {}) if sense else {}
                row.update({"sense": sense, "sense_label": s.label if s else None, "category": s.category if s else None,
                            "scope": meta.get("scope"), "p": p, "alternatives": alts, "why": why,
                            "senses": len(ht.senses), "candidates": list(meta.get("candidates", [])),
                            "diseases": sorted({d for c in meta.get("candidates", []) for d in self.data.by_concept.get(c, [])})})
            if term in homonyms:
                row["homonym"] = {"diseases": homonyms[term]["diseases"], "note": homonyms[term]["note"]}
            out.append(row)
        out.sort(key=lambda r: r["at"])
        for k, r in enumerate(out, 1):
            r["id"] = f"T{k}"
        return out

    # ------------------------------------------------------------ model review
    def review(self, packet: dict[str, Any], judge: Any, *, recall: bool = True) -> dict[str, Any]:
        """A model adjudicates the uncertain findings and may add findings the forms missed (rules first)."""
        if judge is None:
            return packet
        norm = packet["normalized"]
        items = []
        for f in packet["findings"]:
            if not f["review"]:
                continue
            amb = self.ambiguous.get(f["surface"])
            options = list(amb["readings"]) if amb else list(self.index.get(f["surface"], ("", [f["phenotype"]]))[1])
            items.append({"id": f["id"], "rule": f["phenotype"], "options": [*dict.fromkeys(options), "none"], "finding": f})
        summary: dict[str, Any] = {"asked": 0}
        if items:
            def render(group: list[dict[str, Any]]) -> str:
                lines = [f"原文：{norm}", "对下列规则读出的症状逐项判断：保留其读法、改为另一读法，或 none（此处并非症状，如治法、比喻、病名的一部分）。"]
                for it in group:
                    f = it["finding"]
                    opts = "、".join(f"{o}（{self.data.phenotypes[o].label}）" if o in self.data.phenotypes else o for o in it["options"])
                    lines.append(f"- {it['id']}：「{f['surface']}」在「{f['clause']}」中；规则读为 {f['phenotype']}；可选：{opts}")
                lines.append('答 {"decisions": [{"id": "F1", "reading": 选项之一, "reason": 简述}]}')
                return "\n".join(lines)

            def item_check(item: dict[str, Any], d: dict[str, Any]) -> list[str]:
                return [] if d.get("reading") in item["options"] else [f"reading must be one of {item['options']}"]

            decisions, summary = adjudicate(judge, items, task="bridge.findings", render=render, value_key="reading",
                                            system="你是中医古籍的临床表型标注者：只依原文判断，不以今病释古。",
                                            item_check=item_check)
            by_id = {f["id"]: f for f in packet["findings"]}
            for d in decisions:
                f = by_id[d.id]
                f["decided_by"] = d.decided_by
                if d.reason:
                    f["model_reason"] = d.reason
                if d.final == "none":
                    f["status"] = "rejected"
                elif d.final != f["phenotype"]:
                    replaced = self._finding(d.final, f["surface"], f["span"][0], norm,
                                             {"start": 0, "end": len(norm), "text": f["clause"], "optional": f["optional"],
                                              "conditional": f["conditional"], "after": f["status"] == "after_treatment"},
                                             None, False)
                    f.update({k: v for k, v in replaced.items() if k not in ("id", "source", "clause")})
                f["review"] = False
        added: list[dict[str, Any]] = []
        if recall:
            added, rec = self._recall(packet, judge)
            summary["recall"] = rec
        packet["findings"].extend(added)
        for k, f in enumerate(packet["findings"], 1):
            f["id"] = f"F{k}"
        projected = [f for f in packet["findings"] if f["hpo"] and not f["negated"] and f["status"] == "presenting"]
        packet["counts"].update({"findings": len(packet["findings"]), "projected": len(projected),
                                 "uncertain": sum(1 for f in packet["findings"] if f["review"])})
        packet["review"] = {**summary, "judge": judge.label}
        return packet

    def _recall(self, packet: dict[str, Any], judge: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        norm = packet["normalized"]
        taken = [False] * len(norm)
        for f in packet["findings"]:
            for k in range(*f["span"]):
                taken[k] = True
        catalogue = "；".join(f"{p.id}={p.label}" for p in self.data.phenotypes.values())
        schema = {"type": "object", "required": ["findings"], "properties": {"findings": {"type": "array", "items": {
            "type": "object", "required": ["text", "phenotype"], "properties": {
                "text": {"type": "string"}, "phenotype": {"type": "string"}, "negated": {"type": "boolean"}}}}}}
        found = "、".join(f["surface"] for f in packet["findings"]) or "（无）"
        prompt = (f"原文：{norm}\n规则已读出：{found}\n请找出规则漏读的症状、体征（只取原文中确实出现的片段，逐字照录），"
                  f"每项给出表型 id（只能取自下表）与是否被否定。没有就答空表。\n表型：{catalogue}\n"
                  '答 {"findings": [{"text": 原文片段, "phenotype": id, "negated": false}]}')

        # a proposal that is not an exact span of the text, or names no known phenotype, is dropped (not argued over)
        res = judge.ask("bridge.recall", "你是中医古籍的临床表型标注者：只依原文，不以今病释古。", prompt, schema=schema)
        if not res.ok:
            return [], {"ok": False, "error": res.error}
        added, dropped = [], []
        for row in res.data.get("findings", []):
            start = norm.find(row["text"])
            while start >= 0 and any(taken[start: start + len(row["text"])]):
                start = norm.find(row["text"], start + 1)
            if start < 0 or row["phenotype"] not in self.data.phenotypes:
                dropped.append(row)
                continue
            for k in range(start, start + len(row["text"])):
                taken[k] = True
            clause = {"start": 0, "end": len(norm), "text": row["text"], "optional": False, "conditional": False, "after": False}
            f = self._finding(row["phenotype"], row["text"], start, norm, clause, None, False)
            f["negated"] = bool(row.get("negated", False))
            f["source"] = "model"
            added.append(f)
        return added, {"ok": True, "added": len(added), "dropped": len(dropped)}


def quote(packet: dict[str, Any], finding: dict[str, Any], width: int = 10) -> str:
    """The finding in its words (a short, bounded quote)."""
    norm = packet["normalized"]
    a, b = finding["span"]
    return norm[max(0, a - width): a] + "【" + norm[a:b] + "】" + norm[b: b + width]


__all__ = ["PacketReader", "quote"]
