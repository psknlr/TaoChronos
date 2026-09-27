"""释义与今译 — a classical text read in five layers that never overwrite one another (T10).

=============  =====================================================================================================
original       the text as the witness has it — never changed, returned as given
normalized     the variant and traditional characters mapped to the standard forms the corpus is searched by (a reading
               aid: the characters that changed are listed)
punctuated     the editors' marks when the text has them; for 白文, the 句读 model's (marks only, every character kept —
               checked)
interpreted    the words that need explaining, each with what the commentators say of it (``study glosses``: who glossed
               it first, how, when — with the passage) and, for terms with curated historical senses, the sense its
               context and date favour (terminology.yaml) — the evidence layer
translated     a modern Chinese translation by a model (``--llm``), written from the punctuated text and the evidence
               layer: it must cite the glosses it relies on, keep the historical terms in their own senses, and pass the
               presentism guardrail (no modern disease name the original does not have); it is labelled as a model's
               translation, never as the text
=============  =====================================================================================================

Without a model the first four layers stand: an interlinear reading aid built from the commentators' own glosses.
"""

from __future__ import annotations

import re
from typing import Any

from ....verification.presentism import guard_from_pack
from .base import StudyBase
from .punctuation import has_marks

EXPLAIN_TYPES = {"Symptom", "Sign", "Pulse", "Tongue", "Disease", "Syndrome", "Pathogenesis", "Etiology", "Treatment",
                 "Theory", "Location", "Nature"}
REDUP = re.compile(r"([一-鿿])\1")  # 啬啬 淅淅 翕翕 几几: the descriptive doublets the commentators gloss


class TranslationStudy:
    def __init__(self, base: StudyBase, punct: Any, glosses: Any, entities: Any) -> None:
        self.b = base
        self.punct = punct
        self.glosses = glosses
        self.entities = entities
        self._guard = None

    @property
    def guard(self) -> Any:
        if self._guard is None:
            self._guard = guard_from_pack(self.b.pack)
        return self._guard

    def run(self, text: str | None = None, passage_id: str | None = None, *, max_terms: int = 8,
            max_chars: int = 1200) -> dict[str, Any]:
        passage = None
        if passage_id:
            found = self.b.passages([passage_id])
            if not found:
                raise KeyError(f"no passage {passage_id}")
            passage = found[0]
            text = passage.text
        if not text or not text.strip():
            raise ValueError("give a text or a passage id")
        original = text[:max_chars]
        normalized = self.b.normalize(original)
        changes = ([{"at": i, "from": a, "to": b} for i, (a, b) in enumerate(zip(original, normalized)) if a != b]
                   if len(normalized) == len(original) else [])
        with self.b.rules_only():  # the steps before the translation are the rules' (the model's turn comes once, last)
            if has_marks(original):
                punctuated, how, preserved = original, "input", True
            else:
                r = self.punct.run(original, compare=False)
                punctuated, how, preserved = r["punctuated"], "model", r["preserved"]
            year = self.b.year(passage) if passage is not None else None
            terms = self._targets(punctuated, max_terms)
            interpreted = [self._explain(t, punctuated, year) for t in terms]
        evidence = [g for item in interpreted for g in item["glosses"]]
        for i, g in enumerate(evidence, start=1):
            g["id"] = f"G{i}"
        out: dict[str, Any] = {
            "original": original, "normalized": normalized, "normalized_changes": changes[:200],
            "punctuated": punctuated, "punctuation": how, "preserved": preserved,
            "interpreted": interpreted, "translated": None,
            "layers": ["original", "normalized", "punctuated", "interpreted", "translated"],
            "note": "the original is returned as given; the other layers are readings of it — the glosses are the "
                    "commentators', the senses curated, the translation (if any) a model's, checked but not the text",
        }
        if passage is not None:
            out["passage"] = self.b.witness(passage)
        if self.b.judge is not None:
            out["translated"] = self._translate(punctuated, original, interpreted, evidence)
        return out

    # ------------------------------------------------------------ the evidence layer
    def _targets(self, text: str, limit: int) -> list[dict[str, Any]]:
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for m in REDUP.finditer(text):
            w = m.group(0)
            if w not in seen:
                seen.add(w)
                out.append({"term": w, "type": "doublet", "start": m.start(), "end": m.end()})
        for e in self.entities.run(text)["entities"]:
            if e["type"] in EXPLAIN_TYPES and e["text"] not in seen and len(e["text"]) >= 2:
                seen.add(e["text"])
                out.append({"term": e["text"], "type": e["type"], "start": e["start"], "end": e["end"]})
        return out[:limit]

    def _explain(self, target: dict[str, Any], text: str, year: float | None) -> dict[str, Any]:
        term = target["term"]
        item: dict[str, Any] = {**target, "glosses": [], "sense": None}
        try:
            res = self.glosses.run(term)
        except Exception:  # noqa: BLE001 - a term the gloss reader cannot take has no glosses
            res = {"readings": []}
        for reading in res.get("readings", [])[:3]:
            first = reading.get("first") or {}
            item["glosses"].append({"id": "", "gloss": reading["gloss"], "type": reading.get("type"),
                                    "by": first.get("by"), "title": first.get("title"), "years": first.get("years"),
                                    "passage_id": first.get("passage_id"), "count": reading.get("count")})
        terminology = getattr(self.b.pack, "terminology", None)
        if terminology is not None and terminology.term(term) is not None:
            context_terms = {e for e in re.findall(r"[一-鿿]{2}", text)}
            sense_id, p, alternatives, why = terminology.resolve(term, text, context_terms, year)
            sense = terminology.sense(sense_id) if sense_id else None
            if sense is not None:
                item["sense"] = {"id": sense.id, "label": getattr(sense, "label", ""), "gloss": getattr(sense, "gloss", ""),
                                 "p": round(p, 3), "alternatives": {k: round(v, 3) for k, v in alternatives.items()},
                                 "why": why}
        return item

    # ------------------------------------------------------------ the model's translation
    SYSTEM = ("你是中医古籍的译注者。把给出的古文译成现代汉语（白话），逐句忠实，不增不减。"
              "术语按其当时的意义译出，保留古代病名、证名（如消渴、胸痹、中风），不得换成现代病名；"
              "凡依据所给训诂（G 编号）解释之处，在 notes 中注明所用编号；无把握之处列入 uncertain。")

    def _translate(self, punctuated: str, original: str, interpreted: list[dict[str, Any]],
                   evidence: list[dict[str, Any]]) -> dict[str, Any]:
        judge = self.b.judge
        ids = {g["id"] for g in evidence}
        lines = []
        for item in interpreted:
            gl = "；".join(f"[{g['id']}] {g['by'] or '佚名'}：{g['gloss']}" for g in item["glosses"])
            sense = f"；当时义项：{item['sense']['label']}" if item.get("sense") else ""
            if gl or sense:
                lines.append(f"- {item['term']}（{item['type']}）：{gl}{sense}")
        prompt = ("古文：" + punctuated + "\n\n训诂与义项（引用时写编号）：\n" + ("\n".join(lines) or "（无）")
                  + "\n\n答案为 {\"translation\": 白话译文, \"notes\": [{\"term\": 词, \"gloss_ids\": [编号]}], "
                    "\"uncertain\": [无把握之处]}。")
        schema = {"type": "object", "required": ["translation"], "properties": {
            "translation": {"type": "string"}, "uncertain": {"type": "array", "items": {"type": "string"}},
            "notes": {"type": "array", "items": {"type": "object", "required": ["term", "gloss_ids"], "properties": {
                "term": {"type": "string"}, "gloss_ids": {"type": "array", "items": {"type": "string"}}}}}}}

        def check(data: Any) -> list[str]:
            errors = []
            translation = data.get("translation", "")
            han = len(re.findall(r"[一-鿿]", original))
            if not translation.strip():
                errors.append("empty translation")
            elif han and not (0.6 * han <= len(re.findall(r"[一-鿿]", translation)) <= 6 * han + 40):
                errors.append("the translation's length does not fit the text")
            for n in data.get("notes", []):
                errors += [f"unknown gloss id {g}" for g in n.get("gloss_ids", []) if g not in ids]
            for f in self.guard.check(translation, source=original):
                errors.append(f"presentism ({f.kind}): 「{f.modern}」 in 「{f.sentence[:40]}」 — {f.suggestion}")
            return errors

        res = judge.ask("study.translate", self.SYSTEM, prompt, schema=schema, check=check, max_tokens=3000)
        if not res.ok:
            return {"ok": False, "error": res.error, "judge": judge.label}
        return {"ok": True, "text": res.data["translation"], "notes": res.data.get("notes", []),
                "uncertain": res.data.get("uncertain", []), "judge": judge.label, "assertion": "MODEL_GENERATED",
                "checks": ["gloss ids exist", "length fits the text", "no modern disease name the original lacks"]}


__all__ = ["TranslationStudy"]
