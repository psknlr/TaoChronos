"""实体识别 — the entities of a medical text in its own context (T7): 24 types, found by rules, reviewed by a model.

Rules first (``domains/classics/entities.yaml``): the lexicon (curated terms, and harvested formula and drug names as
candidates), ``physicians.yaml``, ``schools.yaml``, ``places.yaml``, the reign eras, and patterns for what lists
cannot hold — doses (三两, 各等分), the making and taking of a remedy (以水七升, 煮取三升, 去滓), contraindications (不可发汗,
忌生冷), pulses (脉阴阳俱紧), tongues (舌上白苔), dates (康熙戊申), the course of an illness (二三日, 日晡所), titles in
《》, and formula names the lexicon lacks (…汤主之).  Overlaps go to the longer span, then to the type listed first.

Context decides what the lists cannot: a physician followed by 注 or 按 is a Commentator; 长沙 before 方 or 论 is
张仲景, elsewhere a place; a one-character cause (风 寒 湿) is an entity only in a causal frame (伤于风, 感受湿邪); an
herb name that is also a word (当归, 远志, 独活) is an herb in a composition, and ambiguous elsewhere; a finding that
starts with 不 无 未 is kept with ``negated``.

With a judge (``--llm``) the model then (1) types the ambiguous candidates — or rejects them — from their context, and
(2) lists entities the rules missed in each stretch of text; its spans must be found in the text, its types come from
the schema, and each carries ``extraction: model``.  Everything is machine reading: spans and types are for review.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from ....protocol.yamlio import loads_yaml
from .base import StudyBase

HAN = re.compile(r"[㐀-鿿\U00020000-\U0002ffff]")
NEGATION = "不无未非勿"
FINDINGS = {"Symptom", "Sign", "Pulse", "Tongue"}
SOURCE_RANK = {"lexicon": 0, "physicians": 0, "schools": 0, "places": 1, "eras": 1, "list": 1, "pattern": 2, "harvested": 3,
               "guess": 4}


@dataclass
class Cand:
    start: int
    end: int
    type: str
    source: str
    ref: str | None = None
    rule: str = ""
    ambiguous: bool = False
    alternatives: list[str] = field(default_factory=list)

    @property
    def length(self) -> int:
        return self.end - self.start


class EntityRecognizer:
    def __init__(self, base: StudyBase) -> None:
        self.b = base
        cfg = base.data("entities.yaml")
        self.cfg = cfg
        self.types: list[str] = list(cfg["types"])
        self.rank = {t: i for i, t in enumerate(self.types)}
        self.labels = {t: v.get("label", t) for t, v in cfg["types"].items()}
        self._surfaces: dict[str, list[Cand]] | None = None
        self._patterns: list[tuple[str, re.Pattern[str], str]] | None = None
        self._norm_cache: dict[str, str] = {}

    # ------------------------------------------------------------ building
    def _add(self, table: dict[str, list[Cand]], surface: str, type_: str, ref: str | None, source: str,
             ambiguous: bool = False) -> None:
        surface = self._norm(surface)
        if not surface:
            return
        bucket = table.setdefault(surface, [])
        if any(c.type == type_ for c in bucket):
            return
        bucket.append(Cand(0, len(surface), type_, source, ref, rule=source, ambiguous=ambiguous))

    def surfaces(self) -> dict[str, list[Cand]]:
        if self._surfaces is not None:
            return self._surfaces
        cfg = self.cfg
        table: dict[str, list[Cand]] = {}
        cat_type = {c: t for t, v in cfg["types"].items() for c in v.get("lexicon", [])}
        cond = cfg.get("condition_types") or {}
        for entry in self.b.pack.lexicon.entries.values():
            type_ = cond.get(entry.term) if entry.category == "condition" else cat_type.get(entry.category)
            if type_ is None:
                continue
            harvested_entry = entry.kind == "harvested"
            for s in entry.surfaces():
                if harvested_entry and not _plausible_name(s):
                    continue
                self._add(table, s, type_, entry.term_id, "harvested" if harvested_entry else "lexicon")
        harvested = self.b.pack.root / "lexicon-harvested"
        if not self.b.pack.lexicon.harvested and harvested.exists():  # the demo profile does not load them: candidates here
            for path in sorted(harvested.glob("*.yaml")):
                category, terms = _harvested_terms(path)
                type_ = {"formula": "Formula", "herb": "Herb"}.get(category or "")
                for term in terms if type_ else []:
                    if _plausible_name(term) and self._norm(term) not in table:
                        self._add(table, term, type_, f"{category}:{term}", "harvested")
        people = self.b.data("physicians.yaml").get("persons", [])
        for p in people:
            for name in p.get("names", []):
                if len(self._norm(name)) >= 2:
                    self._add(table, name, "Physician", p["id"], "physicians", ambiguous=name in ("长沙",))
        for key, s in (self.b.data("schools.yaml").get("schools") or {}).items():
            for form in {s.get("label", ""), f"{key}学派", f"{key}派"}:
                if len(form) >= 3:
                    self._add(table, form, "School", key, "schools")
        for place in self.b.data("places.yaml").get("places", []):
            for name in place.get("names", []):
                if len(self._norm(name)) >= 2:
                    self._add(table, name, "Place", place.get("same_as") or place["id"], "places",
                              ambiguous=bool(place.get("ambiguous")))
        for word in cfg.get("theory", []):
            self._add(table, word, "Theory", word, "list")
        for word in cfg.get("nature", []):
            if self._norm(word) not in table:
                self._add(table, word, "Nature", word, "list")
        for word in cfg.get("location", []):
            if self._norm(word) not in table or all(c.type not in FINDINGS for c in table[self._norm(word)]):
                self._add(table, word, "Location", word, "list")
        for word in cfg.get("editions", []):
            self._add(table, word, "Edition", word, "list", ambiguous=word in (cfg.get("ambiguous_editions") or []))
        for word in cfg.get("dynasties", []):
            self._add(table, word, "Time", word, "list")
        for s, cands in table.items():  # a surface of two types is ambiguous between them
            if len({c.type for c in cands}) > 1:
                for c in cands:
                    c.ambiguous = True
                    c.alternatives = sorted({x.type for x in cands} - {c.type})
        self._surfaces = table
        self.max_len = max(len(s) for s in table) if table else 1
        return table

    def patterns(self) -> list[tuple[str, re.Pattern[str], str]]:
        if self._patterns is not None:
            return self._patterns
        out: list[tuple[str, re.Pattern[str], str]] = []
        for type_, regs in (self.cfg.get("patterns") or {}).items():
            real = "Preparation" if type_ == "Preparation_in_composition" else type_
            for i, reg in enumerate(regs):
                out.append((real, re.compile(reg), f"{type_}#{i + 1}"))
        eras = sorted({self._norm(e) for e in (self.b.data("eras.yaml").get("eras") or {})}, key=len, reverse=True)
        if eras:
            out.append(("Time", re.compile("(?:" + "|".join(map(re.escape, eras)) + ")(?:元年|[一二三四五六七八九十百]+年|"
                                             "[甲乙丙丁戊己庚辛壬癸][子丑寅卯辰巳午未申酉戌亥]|初|末|间|中)"), "era"))
        single = "".join(self.cfg.get("dynasty_single", []))
        if single:
            out.append(("Time", re.compile(f"[{single}]{self.cfg.get('dynasty_after', '(?:时|代)')}"), "dynasty"))
        self._patterns = out
        return out

    # ------------------------------------------------------------ normalising
    def _norm(self, text: str) -> str:
        """Normalised text of the same length as the input (character by character where the whole would shift)."""
        cached = self._norm_cache.get(text)
        if cached is not None:
            return cached
        norm = self.b.normalize(text)
        if len(norm) != len(text):
            norm = "".join(n if len(n := self.b.normalize(ch)) == 1 else ch for ch in text)
        if len(self._norm_cache) > 50_000:
            self._norm_cache.clear()
        self._norm_cache[text] = norm
        return norm

    # ------------------------------------------------------------ reading
    def candidates(self, norm: str) -> list[Cand]:
        table = self.surfaces()
        found: list[Cand] = []
        n = len(norm)
        for i in range(n):
            for length in range(min(self.max_len, n - i), 0, -1):
                for c in table.get(norm[i: i + length], ()):
                    found.append(Cand(i, i + length, c.type, c.source, c.ref, c.rule, c.ambiguous, list(c.alternatives)))
        for type_, reg, rule in self.patterns():
            for m in reg.finditer(norm):
                s, e = m.span()
                if e <= s:
                    continue
                if type_ == "Book":
                    s, e = s + 1, e - 1
                if rule.startswith("Preparation_in_composition"):
                    continue  # read below, after drugs and doses are known
                found.append(Cand(s, e, type_, "pattern", None, rule))
        found += self._guesses(norm)
        return found

    def _guesses(self, norm: str) -> list[Cand]:
        """Names the lists lack: a drug before its dose in a composition, a formula before 主之."""
        stop = set(self.cfg.get("name_stop", ""))
        out = []
        name = r"(?:(?![一二三四五六七八九十半百千两各])[一-鿿])"
        for m in re.finditer(rf"({name}{{2,5}})(?=各?[一二三四五六七八九十半]+(?:两|钱|分|铢|枚|升|合|斤|个|片|茎))", norm):
            s, e = m.span(1)
            while s < e and norm[s] in stop:
                s += 1
            if e - s >= 2:
                out.append(Cand(s, e, "Herb", "guess", None, "name before a dose", ambiguous=True))
        return out

    def resolve(self, norm: str, found: list[Cand]) -> list[Cand]:
        # guesses only fill gaps; otherwise the longer span wins, then the type listed first, then the surer source
        found.sort(key=lambda c: (c.source == "guess", -c.length, self.rank.get(c.type, 99), SOURCE_RANK.get(c.source, 9), c.start))
        taken = [False] * len(norm)
        chosen: list[Cand] = []
        for c in found:
            if any(taken[c.start: c.end]):
                continue
            if not self._fits(norm, c):
                continue
            for k in range(c.start, c.end):
                taken[k] = True
            chosen.append(c)
        chosen.sort(key=lambda c: c.start)
        chosen += self._processing(norm, chosen, taken)
        chosen.sort(key=lambda c: c.start)
        return chosen

    def _fits(self, norm: str, c: Cand) -> bool:
        """Context checks before a candidate is accepted."""
        frame = self.cfg.get("etiology_frame") or {}
        if c.type == "Etiology" and c.length == 1:
            before, after = norm[max(0, c.start - 3): c.start], norm[c.end: c.end + 2]
            return bool(re.search(frame.get("before", "$^"), before) or re.search(frame.get("after", "$^"), after)
                        or (after[:1] and after[:1] in "风寒暑湿燥火热") or (before[-1:] and before[-1:] in "风寒暑湿燥火热"))
        if c.type in ("Location", "Theory", "Nature", "Pathogenesis", "Treatment") and c.length == 1 and c.source != "pattern":
            return False  # 表 里 痰 饮 alone are too common to assert
        if c.type == "Time" and c.source == "pattern" and c.rule.startswith("Time#1"):
            return not re.match(r"[一-鿿]?服", norm[c.end: c.end + 2])
        return True

    def _processing(self, norm: str, chosen: list[Cand], taken: list[bool]) -> list[Cand]:
        """Processing words (去皮, 炙, 擘) right after a drug, a dose or another processing word (炮，去皮，破八片); a
        processing word may take the place of a shorter dose inside it (破八片 is not the dose 八片)."""
        regs = [re.compile(r) for r in (self.cfg.get("patterns") or {}).get("Preparation_in_composition", [])]
        matches = sorted({m.span() for reg in regs for m in reg.finditer(norm)})
        ends = {c.end for c in chosen if c.type in ("Herb", "Dose")}
        out: list[Cand] = []
        for s, e in matches:
            gap = s
            while gap > 0 and norm[gap - 1] in "（(，、 ":
                gap -= 1
            if gap not in ends:
                continue
            inside = [c for c in chosen if c.start < e and s < c.end]
            if any(c.type != "Dose" or c.length >= e - s or c.start < s for c in inside):
                continue
            if any(taken[k] for k in range(s, e) if not any(c.start <= k < c.end for c in inside)):
                continue
            for c in inside:
                chosen.remove(c)
            for k in range(s, e):
                taken[k] = True
            out.append(Cand(s, e, "Preparation", "pattern", None, "processing after a drug"))
            ends.add(e)
        return out

    def _context(self, norm: str, c: Cand) -> Cand:
        """Types that depend on the words around the span."""
        after = norm[c.end: c.end + 3]
        if c.type == "Physician" and re.match(self.cfg.get("commentator_after", "$^"), after):
            c.type, c.rule = "Commentator", "physician before 注/按"
        if norm[c.start: c.end] == "长沙":  # 张仲景 (长沙太守) or the place
            if re.match(r"[方论曰云之氏]", after):
                c.type, c.ref, c.rule, c.ambiguous, c.alternatives = "Physician", "zhang_ji", "长沙 before 方/论/曰", False, []
            else:
                c.type, c.ref, c.ambiguous, c.alternatives = "Place", "changsha", True, ["Physician"]
        if c.type == "Disease" and re.search(r"(?:之为病|病)[，,]\s*$", norm[max(0, c.start - 5): c.start]):
            c.ambiguous = True  # a disease name listed among the findings of a disease (厥阴之为病，消渴) may be a finding
            c.alternatives = sorted(set(c.alternatives) | {"Symptom"})
        if c.type == "Herb" and self._norm(norm[c.start: c.end]) in {self._norm(h) for h in self.cfg.get("ambiguous_herbs", [])}:
            if not re.match(r"各?[一二三四五六七八九十半等]", after):  # no dose after it: see its neighbours (run)
                c.ambiguous = True
                c.alternatives = sorted(set(c.alternatives) | {"none"})
        return c

    # ------------------------------------------------------------ run
    def run(self, text: str | None = None, passage_id: str | None = None, *, llm_recall: bool = True,
            max_chars: int = 20000) -> dict[str, Any]:
        passage = None
        if passage_id:
            found = self.b.passages([passage_id])
            if not found:
                raise KeyError(f"no passage {passage_id}")
            passage = found[0]
            text = passage.text
        if not text or not text.strip():
            raise ValueError("give a text or a passage id")
        text = text[:max_chars]
        norm = self._norm(text)
        chosen = [self._context(norm, c) for c in self.resolve(norm, self.candidates(norm))]
        for k, c in enumerate(chosen):  # an ambiguous drug name beside drugs or doses is a drug (a composition)
            if c.type == "Herb" and "none" in c.alternatives:
                near = [x for x in (chosen[k - 1] if k else None, chosen[k + 1] if k + 1 < len(chosen) else None)
                        if x is not None and min(abs(x.start - c.end), abs(c.start - x.end)) <= 2]
                if any(x.type in ("Herb", "Dose", "Preparation") and not (x.type == "Herb" and "none" in x.alternatives) for x in near):
                    c.ambiguous = len(c.alternatives) > 1
                    c.alternatives = [t for t in c.alternatives if t != "none"]
        for c, nxt in zip(chosen, chosen[1:]):  # a place name before a person's name is his place (河间刘完素, 新安汪机)
            if c.end == nxt.start and nxt.type in ("Physician", "Commentator") and c.type != "Place" and "Place" in c.alternatives:
                c.type, c.ambiguous, c.rule = "Place", False, "place before a name"
                c.alternatives = [t for t in c.alternatives if t != "Place"]
        entities = []
        for i, c in enumerate(chosen, start=1):
            span = text[c.start: c.end]
            ent: dict[str, Any] = {"id": f"e{i}", "start": c.start, "end": c.end, "text": span, "type": c.type,
                                   "label": self.labels.get(c.type, c.type), "ref": c.ref, "source": c.source, "rule": c.rule,
                                   "ambiguous": c.ambiguous, "extraction": "rule"}
            if c.alternatives:
                ent["alternatives"] = c.alternatives
            if c.type in FINDINGS and (span[:1] in NEGATION):
                ent["negated"] = True
            entities.append(ent)
        out: dict[str, Any] = {"text": text, "entities": entities, "types": self.types}
        if passage is not None:
            out["passage"] = self.b.witness(passage)
        if self.b.judge is not None:
            out["llm_review"] = self.review(text, entities, recall=llm_recall)
            entities = out["entities"] = [e for e in out["entities"] if e["type"] != "none"]
        out["counts"] = dict(Counter(e["type"] for e in entities))
        out["ambiguous"] = sum(1 for e in entities if e["ambiguous"] and e.get("decided_by") in (None, "rule"))
        out["note"] = ("machine reading: spans and types come from the lexicon, the lists and patterns of entities.yaml "
                       "(and, with --llm, a model's review); ambiguous spans carry their alternatives")
        return out

    # ------------------------------------------------------------ the model's look
    SYSTEM = ("你是中医古籍的信息抽取专家，熟悉病、证、症、脉、舌、方、药、剂量、炮制、医家、书名、地名、年代等实体。"
              "只根据给出的原文判断；实体必须是原文中连续出现的字，不得改写。")

    def review(self, text: str, entities: list[dict[str, Any]], *, recall: bool = True, window: int = 18,
               max_chunks: int = 8) -> dict[str, Any]:
        from ....capabilities.judge import adjudicate

        judge = self.b.judge
        allowed = self.types + ["none"]
        items = []
        for e in entities:
            if not e["ambiguous"]:
                continue
            s, t = e["start"], e["end"]
            items.append({"id": e["id"], "rule": e["type"], "entity": e,
                          "context": text[max(0, s - window): s] + "【" + text[s:t] + "】" + text[t: t + window]})

        def render(group: list[dict[str, Any]]) -> str:
            rows = [{"id": it["id"], "context": it["context"], "rule_type": it["rule"],
                     "alternatives": it["entity"].get("alternatives", [])} for it in group]
            return ("判断每条中【】内文字在此语境中的实体类型；可选类型：" + "、".join(allowed)
                    + "（none 表示不是实体）。答案为 {\"decisions\": [{\"id\": …, \"label\": …, \"reason\": …}]}：\n"
                    + json.dumps(rows, ensure_ascii=False, indent=0))

        decisions, summary = adjudicate(judge, items, task="study.entities.type", system=self.SYSTEM, render=render,
                                        allowed=allowed, batch=25)
        by_id = {e["id"]: e for e in entities}
        for d in decisions:
            e = by_id[d.id]
            e["type"], e["decided_by"] = d.final, d.decided_by
            if d.decided_by != "rule":
                e["label"] = self.labels.get(d.final, d.final)
                e["ambiguous"] = False
            if d.reason:
                e["model_reason"] = d.reason
        added: list[dict[str, Any]] = []
        failures: list[str] = []
        if recall:
            added, failures = self._recall(text, entities, max_chunks=max_chunks)
            entities.extend(added)
            entities.sort(key=lambda e: e["start"])
        return {"judge": judge.label, "summary": summary, "added": len(added), "added_entities": added[:60],
                "recall_failures": failures[:10]}

    def _recall(self, text: str, entities: list[dict[str, Any]], *, max_chunks: int, size: int = 360) -> tuple[list[dict[str, Any]], list[str]]:
        judge = self.b.judge
        taken = [False] * len(text)
        for e in entities:
            if e["type"] != "none":
                for k in range(e["start"], e["end"]):
                    taken[k] = True
        chunks: list[tuple[int, int]] = []
        start = 0
        for m in re.finditer(r"[。；！？\n]", text):
            if m.end() - start >= size:
                chunks.append((start, m.end()))
                start = m.end()
        if start < len(text):
            chunks.append((start, len(text)))
        schema = {"type": "object", "required": ["entities"], "properties": {"entities": {"type": "array", "items": {
            "type": "object", "required": ["text", "type"], "properties": {"text": {"type": "string"}, "type": {"enum": self.types}}}}}}
        added: list[dict[str, Any]] = []
        failures: list[str] = []
        for a, b in chunks[:max_chunks]:
            piece = text[a:b]
            known = [f"{text[e['start']:e['end']]}:{e['type']}" for e in entities if a <= e["start"] < b and e["type"] != "none"]
            prompt = ("原文：" + piece + "\n已识别：" + ("；".join(known) or "无") + "\n列出已识别之外、原文中确有的实体（类型："
                      + "、".join(self.types) + "）。答案为 {\"entities\": [{\"text\": 原文中的字, \"type\": 类型}]}；没有则给空列表。")

            res = judge.ask("study.entities.recall", self.SYSTEM, prompt, schema=schema)
            if not res.ok:
                failures.append(res.error or "failed")
                continue
            for x in res.data.get("entities", []):
                span = x["text"].strip()
                if not span or len(span) > 20 or span not in piece:  # not in the text: dropped, never written back
                    failures.append(f"「{span[:20]}」不在原文中")
                    continue
                s = e = -1
                replaced: list[dict[str, Any]] = []
                pos = piece.find(span)
                while pos >= 0:
                    s0, e0 = a + pos, a + pos + len(span)
                    inside = [y for y in entities + added if y["type"] != "none" and y["start"] < e0 and s0 < y["end"]]
                    # a free stretch, or one that only extends rule spans of the same kind (默默不欲饮食 over 不欲饮食)
                    if not inside or all(s0 <= y["start"] and y["end"] <= e0 and y["extraction"] == "rule"
                                         and (y["type"] == x["type"] or {y["type"], x["type"]} <= FINDINGS) for y in inside):
                        s, e, replaced = s0, e0, inside
                        break
                    pos = piece.find(span, pos + 1)
                if s < 0:
                    continue
                for y in replaced:
                    y["type"] = "none"
                for k in range(s, e):
                    taken[k] = True
                ent = {"id": f"m{len(added) + 1}", "start": s, "end": e, "text": span, "type": x["type"],
                       "label": self.labels.get(x["type"], x["type"]), "ref": None, "source": judge.label, "rule": "model recall",
                       "ambiguous": False, "extraction": "model", "decided_by": "model"}
                if replaced:
                    ent["replaces"] = [y["id"] for y in replaced]
                if x["type"] in FINDINGS and span[:1] in NEGATION:
                    ent["negated"] = True
                added.append(ent)
        return added, failures


def _plausible_name(term: str) -> bool:
    """A harvested name worth matching: two characters or more, not opening with a function word (有毒, 其人)."""
    return len(term) >= 2 and term[0] not in "有无不其之者以而则又可所各每用服"


def _harvested_terms(path: Any) -> tuple[str | None, list[str]]:
    """The terms of a harvested vocabulary: read line by line (the files are generated, and parsing their evidence
    blocks as YAML takes seconds), else as YAML."""
    text = path.read_text(encoding="utf-8")
    cat = re.search(r"^category:\s*(\w+)", text, re.M)
    terms = re.findall(r"^- term:\s*(\S+)\s*$", text, re.M)
    if cat and terms:
        return cat.group(1), [t.strip("'\"") for t in terms]
    data = loads_yaml(text) or {}
    return data.get("category"), [(e["term"] if isinstance(e, dict) else str(e)) for e in data.get("entries", [])]


def score_entities(gold: list[dict[str, Any]], pred: list[dict[str, Any]], types: list[str] | None = None) -> dict[str, Any]:
    """Exact span-and-type P/R/F1 (spans as (start, end, type)); per type; and span-only (type ignored)."""
    def f1(tp: int, fp: int, fn: int) -> dict[str, float]:
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0,
                "tp": tp, "fp": fp, "fn": fn}

    g = {(x["start"], x["end"], x["type"]) for x in gold}
    p = {(x["start"], x["end"], x["type"]) for x in pred}
    out = f1(len(g & p), len(p - g), len(g - p))
    out["span_only"] = f1(len({x[:2] for x in g} & {x[:2] for x in p}), len({x[:2] for x in p} - {x[:2] for x in g}),
                          len({x[:2] for x in g} - {x[:2] for x in p}))
    per = {}
    for t in types or sorted({x[2] for x in g | p}):
        gt = {x for x in g if x[2] == t}
        pt = {x for x in p if x[2] == t}
        if gt or pt:
            per[t] = f1(len(gt & pt), len(pt - gt), len(gt - pt))
    out["per_type"] = per
    return out


__all__ = ["EntityRecognizer", "score_entities"]
