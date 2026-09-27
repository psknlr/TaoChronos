"""The model's second look: what the rules of the study layer hand to a language model, and how its answers are checked.

The rules and statistics of each study function decide first, over the whole corpus.  When a ``Judge`` is configured
(``--llm provider:model``), the cases the rules mark as uncertain — and nothing else — go to the model, each with the
rule's decision and the words it rests on; the model's answer is taken only when it passes the checks below, and every
item keeps both decisions (``capabilities/judge.py``).  Summaries are written from the results with a citation per
sentence, and quotes checked against what is cited.

=============  ==================================================  ===============================================
function       what the model is asked                             checks
=============  ==================================================  ===============================================
punctuate      the mark of each gap near the model's cut           a label from the marks; characters never change
               (``review``: doubtful and possible marks)           (the model picks marks, it never writes text)
disputes       the stance in each sentence whose rule reading is   a stance from reject / endorse / cite; the
               weak (a rejection or approval word, or a            sentence's own words only
               contrastive word with none)
commentaries   how the commentators read the clause, compared      each sentence cites commentary ids; quotes are
                                                                   found in the commentary cited
=============  ==================================================  ===============================================
"""

from __future__ import annotations

import json
import re
from typing import Any

from ....capabilities.judge import Judge, adjudicate, synthesize

PUNCT_LABELS = ["none", "，", "。", "、", "：", "；", "？", "！"]
PUNCT_SYSTEM = ("你是中医古籍的句读专家。每条给出白文中一个位置（以▲标出）的上下文和模型的当前判断。"
                "判断▲处应否加标点、加何种标点：none 表示不断；，、：为句内停顿；。；？！为句末。"
                "只能在▲处选择标点，不得增删改任何文字；按古文语法、医书文例（方名、药名、剂量、煎服法）断句。")


def review_punctuation(judge: Judge | None, text: str, marked: dict[str, Any], *, limit: int = 240,
                       window: int = 14) -> tuple[dict[int, str | None], dict[str, Any], list[dict[str, Any]]]:
    """The model's marks for the gaps the punctuation model was least sure of: overrides (text index → mark, or None
    to leave the gap open), the adjudication summary, and the decisions."""
    items = []
    for r in marked.get("review", [])[:limit]:
        at = r["at"]
        current = r["mark"] if r["kind"] == "doubtful" else "none"
        items.append({"id": f"g{at}", "at": at, "rule": current, "p": r.get("p"),
                      "context": text[max(0, at - window): at] + "▲" + text[at: at + window]})

    def render(group: list[dict[str, Any]]) -> str:
        rows = [{"id": it["id"], "context": it["context"], "current": it["rule"]} for it in group]
        return ("为下列每个▲位置选择标点（" + " ".join(PUNCT_LABELS) + "），答案为 "
                '{"decisions": [{"id": …, "label": …, "reason": 简短理由}]}：\n' + json.dumps(rows, ensure_ascii=False, indent=0))

    decisions, summary = adjudicate(judge, items, task="study.punctuate.review", system=PUNCT_SYSTEM, render=render,
                                    allowed=PUNCT_LABELS, batch=30)
    at_of = {it["id"]: it["at"] for it in items}
    overrides = {at_of[d.id]: (None if d.final == "none" else d.final) for d in decisions if d.decided_by == "model"}
    rows = [dict(d.to_dict(), at=at_of[d.id], context=next(it["context"] for it in items if it["id"] == d.id))
            for d in decisions if d.asked]
    return overrides, summary, rows


STANCE_LABELS = ["reject", "endorse", "cite"]
STANCE_SYSTEM = ("你是中医学术史研究者。每条给出一句古籍原文、其中被点名引述的医家（target）以及规则的判断。"
                 "判断引述者本人对该医家观点的立场：reject＝驳斥、否定或指其误；endorse＝赞同、遵从；cite＝只是引述，未表态。"
                 "注意：被引者原话里的否定词不是引述者的立场；设问、假设语气不算表态；反问（岂不、宁非）按其肯定义理解；"
                 "只根据这句话本身判断，不要依据你对医家的先验印象。")
CONTRAST = re.compile(r"非|误|谬|岂|未必|不然|殊不知|何必|何尝|然[而则]?|但|惟|独|恐|不可|当从|宗|本|诚|是也|得之")


def _weak(record: dict[str, Any]) -> bool:
    """A reading worth a second look: a rejection or approval (the marker may belong to the quoted view), or a bare
    citation whose sentence has a contrastive word."""
    return record["stance"] in ("reject", "endorse") or bool(CONTRAST.search(record.get("sentence") or ""))


def review_disputes(judge: Judge | None, records: list[dict[str, Any]], *, limit: int = 150) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Stances re-read by the model where the rule reading is weak; records are updated in place (``stance`` final,
    ``rule_stance`` kept, ``decided_by``)."""
    chosen = [r for r in records if _weak(r)][:limit]
    items = [{"id": f"r{i}", "rule": r["stance"], "record": r} for i, r in enumerate(chosen)]

    def render(group: list[dict[str, Any]]) -> str:
        rows = [{"id": it["id"], "target": it["record"]["target"], "sentence": it["record"]["sentence"],
                 "rule": it["rule"], "marker": it["record"].get("marker")} for it in group]
        return ('判断每句的立场（reject / endorse / cite），答案为 {"decisions": [{"id": …, "label": …, "reason": 简短理由}]}：\n'
                + json.dumps(rows, ensure_ascii=False, indent=0))

    decisions, summary = adjudicate(judge, items, task="study.disputes.stance", system=STANCE_SYSTEM, render=render,
                                    allowed=STANCE_LABELS, batch=25)
    by_id = {it["id"]: it["record"] for it in items}
    rows = []
    for d in decisions:
        rec = by_id[d.id]
        rec["rule_stance"] = d.rule
        rec["stance"] = d.final
        rec["decided_by"] = d.decided_by
        if d.reason:
            rec["model_reason"] = d.reason
        if d.asked:
            rows.append({"passage_id": rec["passage_id"], "target": rec["target"], "sentence": rec["sentence"][:120],
                         "rule": d.rule, "model": d.model, "final": d.final, "decided_by": d.decided_by, "reason": d.reason})
    for rec in records:
        rec.setdefault("decided_by", "rule")
    return summary, rows


COMMENTARY_SYSTEM = ("你是中医经典注释史研究者。根据所给诸家注文，比较他们对这一条文的解释：共同之处、分歧所在、"
                     "谁首先提出某种解释、谁沿袭谁。只依据所给注文，不加入注文之外的知识；引用原文必须一字不差。")


def summarize_commentaries(judge: Judge | None, result: dict[str, Any], *, max_units: int = 16, chars: int = 220) -> dict[str, Any] | None:
    """A cited comparison of the commentators' readings of the clause (each sentence cites commentary ids)."""
    if judge is None or not result.get("commentaries"):
        return None
    evidence = []
    for i, c in enumerate(result["commentaries"][:max_units], start=1):
        years = c.get("years") or []
        when = f"{years[0]}" if years else "年代未定"
        evidence.append({"id": f"C{i}", "source": f"{c.get('commentator') or '佚名'}《{c.get('title', '')}》（{when}）",
                         "text": (c.get("text") or "")[:chars]})
    clause = result.get("clause") or result.get("query") or ""
    out = synthesize(judge, task="study.commentaries.summary", system=COMMENTARY_SYSTEM,
                     question=f"条文：「{clause}」。比较诸家对此条的解释。", evidence=evidence, max_sentences=8)
    d = out.to_dict()
    d["evidence"] = [{"id": e["id"], "source": e["source"]} for e in evidence]
    return d


def summarize_results(judge: Judge | None, *, task: str, system: str, question: str, evidence: list[dict[str, Any]],
                      max_sentences: int = 8) -> dict[str, Any] | None:
    """A cited summary of any study result, from evidence rows the caller picks (``{"id", "text", "source"}``)."""
    if judge is None or not evidence:
        return None
    out = synthesize(judge, task=task, system=system, question=question, evidence=evidence, max_sentences=max_sentences)
    d = out.to_dict()
    d["evidence"] = [{"id": e["id"], "source": e.get("source", "")} for e in evidence]
    return d


__all__ = ["PUNCT_LABELS", "STANCE_LABELS", "review_disputes", "review_punctuation", "summarize_commentaries",
           "summarize_results"]
