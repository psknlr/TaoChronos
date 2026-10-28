"""Conservative, source-labelled symptom hypotheses for Five-Phase teaching.

Matching gates are engineering rules, not validated diagnostic criteria or probabilities.
No candidate becomes an asserted state; the caller evaluates each hypothesis separately.
"""

from __future__ import annotations

import re
from typing import Any, Callable


def mention_status(text: str, start: int, end: int) -> str:
    """Scope explicit negation/uncertainty to a clause, including coordinated lists.

    Not a general clinical NLP parser. Unknown wording must never be advertised as
    understood. Keep offsets in the normalised text used by the caller.
    """
    left = re.split(r"[，,。；;！!？?\n]", text[:start])[-1]
    left = re.split(r"但是|但|而是|不过|目前|现在|现有|仅有|只有|仍有|\bbut\b", left)[-1]
    # These words contain 无/非 without denying the following finding.
    left = re.sub(r"无(?:明显)?诱因|无力|无法|无论|非常", "", left)
    right = re.split(r"[，,。；;！!\n]", text[end:])[0]
    if re.search(r"不是没有|并非没有|不能排除|不排除|尚未排除|待排|疑似|怀疑|可能|假如|假设|如果|若有|是否|\b(?:possible|suspected|if)\b", left) or re.match(
        r"\s*(?:尚待|待排|待查|待定|未确诊|可能|[？?])", right
    ):
        return "uncertain"
    if re.search(r"未见|未(?:曾)?$|没有|否认|并非|不是|不伴|不考虑|不支持|已排除|排除|无|非|\b(?:no|not|denies|without)\b", left) or re.match(
        r"\s*(?:已排除|未见|阴性|不存在|没有|已消失)", right
    ):
        return "negated"
    if re.search(r"既往|曾有|过去有|\bhistory of\b", left) or re.match(r"\s*(?:病史|史)", right):
        return "historical"
    return "present"


def read_features(text: str, data: dict[str, Any], normalize: Callable[[str], str]) -> list[dict[str, Any]]:
    norm = normalize(text).lower()
    rows = []
    for key, spec in data.get("features", {}).items():
        seen = set()
        for form in sorted(spec["forms"], key=len, reverse=True):
            word = normalize(form).lower()
            pattern = rf"(?<![a-z]){re.escape(word)}(?![a-z])" if word.isascii() else re.escape(word)
            for match in re.finditer(pattern, norm):
                if any(a <= match.start() and match.end() <= b for a, b in seen):
                    continue
                seen.add(match.span())
                rows.append({"id": key, "name": spec["name"], "written": match.group(), "span": list(match.span()),
                             "status": mention_status(norm, *match.span())})
    return sorted(rows, key=lambda r: (r["span"][0], -len(r["written"])))


def assess(text: str, data: dict[str, Any], normalize: Callable[[str], str]) -> dict[str, Any]:
    findings = read_features(text, data, normalize)
    present = {r["id"] for r in findings if r["status"] == "present"}
    denied = {r["id"] for r in findings if r["status"] == "negated"}
    # Conflicting assertions are not resolved by counting the positive occurrence.
    contradictory = present & denied
    present -= contradictory
    features = data.get("features", {})
    names = lambda ids: [features[x]["name"] for x in ids]
    alerts = []
    possible_urgent = {r["id"] for r in findings if r["status"] in ("present", "uncertain")}
    for rule in data.get("urgent", []):
        if all(possible_urgent.intersection(group) for group in rule["all"]):
            alerts.append({"id": rule["id"], "text": rule["text"], "source": data["sources"][rule["source"]]})
    candidates = []
    norm = normalize(text).lower()
    for pattern, spec in data.get("patterns", {}).items():
        if any(mention_status(norm, *m.span()) != "present" for m in re.finditer(re.escape(normalize(pattern)), norm)):
            continue
        matched, missing, contradicted = [], [], []
        for group in spec["groups"]:
            hits = [x for x in group["any"] if x in present]
            if hits:
                matched.append({"group": group["name"], "findings": names(hits)})
            else:
                missing.append({"group": group["name"], "question": group["question"]})
                if set(group["any"]) <= denied:
                    contradicted.append(group["name"] + "被明确否认")
        if not matched:
            continue
        opposed = [x for x in spec.get("against", []) if x in present]
        contradicted += names(opposed)
        eligible = not missing and not contradicted and not contradictory
        candidates.append({"pattern": pattern, "status": "conditional" if eligible else "needs_clarification",
                           "matched": matched, "missing": missing, "contradictions": contradicted,
                           "sources": [{"id": sid, **data["sources"][sid]} for sid in spec["sources"]],
                           "selection": None, "requires_confirmation": True})
    candidates.sort(key=lambda c: (c["status"] != "conditional", bool(c["contradictions"]), -len(c["matched"]), len(c["missing"])))
    total = len(candidates)
    candidates = candidates[:3]
    questions = []
    if contradictory:
        questions.append("请确认" + "、".join(names(sorted(contradictory))) + "目前是否存在？")
    for candidate in candidates:
        for group in candidate["missing"]:
            if group["question"] not in questions:
                questions.append(group["question"])
    if not questions and not findings:
        questions.append("主要哪里不舒服，具体是什么感觉？")
    questions += ["症状持续多久，什么情况下加重或缓解？", "舌色、舌苔和脉象有记录吗？"]
    return {"mode": "symptoms", "status": "urgent" if alerts else (
                "conditional_candidates" if any(c["status"] == "conditional" for c in candidates) else "needs_clarification"),
            "findings": findings, "candidates": candidates, "omitted_candidates": max(0, total - len(candidates)),
            "questions": [] if alerts else list(dict.fromkeys(questions))[:2], "alerts": alerts,
            "contradictory_findings": names(sorted(contradictory)),
            "note": "仅按已记录的症状组列出待辨证候；匹配门槛是可审阅的工程规则，未经诊断效能验证，不是诊断概率。"
                    "未提及不等于没有；各候选取穴仅在该证候经辨证确认后成立，不可合并为处方。"}
