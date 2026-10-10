"""Tool results in two forms — a compact text for the model, the value for the interface — and the passages they cite.

A model's context is finite and tool results are not: a concordance or a formula history can run to hundreds of
kilobytes.  :func:`compact` keeps a result's shape and trims it evenly (long lists keep their head and say how many
were left out; long strings keep their start and say their length), tightening until it fits.  :func:`citations`
collects every passage card a result carries, so that the interface can check each ``[[passage_id]]`` the model
writes against what a tool returned.
"""

from __future__ import annotations

import json
from typing import Any

from ..protocol.base import to_jsonable

CARD_FIELDS = ("passage_id", "book_id", "title", "dynasty", "year", "period", "locator")
TEXT_FIELDS = ("quote", "text")

# (items kept per list, characters kept per string), from loose to tight
LEVELS = ((40, 1600), (24, 800), (12, 400), (8, 220), (5, 140), (3, 90))


def _trim(value: Any, items: int, chars: int, depth: int = 0) -> Any:
    if depth > 10:
        return "…"
    if isinstance(value, dict):
        return {k: _trim(v, items, chars, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        head = [_trim(v, items, chars, depth + 1) for v in value[:items]]
        if len(value) > items:
            head.append(f"…（另有 {len(value) - items} 项未显示）")
        return head
    if isinstance(value, str) and len(value) > chars:
        return value[:chars] + f"…（共 {len(value)} 字）"
    return value


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def compact(value: Any, max_chars: int = 16000) -> str:
    """The result as the model reads it: JSON, trimmed evenly until it fits ``max_chars``."""
    data = to_jsonable(value)
    text = dumps(data)
    if len(text) <= max_chars:
        return text
    for items, chars in LEVELS:
        text = dumps(_trim(data, items, chars))
        if len(text) <= max_chars:
            return text
    return text[:max_chars] + f"…［截断：原长 {len(text)} 字符］"


def for_model(value: Any) -> Any:
    """What the model reads of a result: all of it but the chart specifications (``charts``), which are for the page —
    of them it reads only the titles of those the page shows (``charts_shown``), so that it can point to them."""
    if isinstance(value, dict) and "charts" in value:
        rest = {k: v for k, v in value.items() if k != "charts"}
        charts = value["charts"] if isinstance(value["charts"], list) else []
        titles = [c["title"] for c in charts if isinstance(c, dict) and isinstance(c.get("title"), str) and c["title"]]
        if titles:
            rest["charts_shown"] = titles
        return rest
    return value


def for_interface(value: Any, max_chars: int = 400_000) -> Any:
    """The result as the interface shows it: whole when it is small enough, trimmed (still valid JSON) otherwise — its
    charts never trimmed (a chart cut short would draw something the result did not say)."""
    data = to_jsonable(value)
    if len(dumps(data)) <= max_chars:
        return data
    if isinstance(data, dict) and "charts" in data:
        rest = for_interface({k: v for k, v in data.items() if k != "charts"}, max_chars - len(dumps(data["charts"])))
        return {**rest, "charts": data["charts"]} if isinstance(rest, dict) else rest
    for items, chars in ((200, 4000), (80, 2000), (30, 800), (10, 300)):
        trimmed = _trim(data, items, chars)
        if len(dumps(trimmed)) <= max_chars:
            return trimmed
    return {"note": "结果过大，界面只显示摘要", "preview": dumps(data)[:4000]}


def citations(value: Any, limit: int = 120) -> list[dict[str, Any]]:
    """Every passage a result names: ``{passage_id, title, dynasty, year, locator, text}`` as far as the result says."""
    found: dict[str, dict[str, Any]] = {}

    def visit(node: Any, depth: int) -> None:
        if depth > 14 or len(found) >= limit:
            return
        if isinstance(node, dict):
            pid = node.get("passage_id")
            if isinstance(pid, str) and pid:
                card = {k: node[k] for k in CARD_FIELDS if node.get(k) not in (None, "")}
                for k in TEXT_FIELDS:
                    if isinstance(node.get(k), str) and node[k]:
                        card["text"] = node[k][:240]
                        break
                old = found.get(pid)
                if old is None:
                    found[pid] = card
                else:  # the same passage met again: keep what was known, and the longer text
                    for k, v in card.items():
                        if k != "text":
                            old.setdefault(k, v)
                        elif len(v) > len(old.get("text", "")):
                            old["text"] = v
            for child in node.values():
                visit(child, depth + 1)
        elif isinstance(node, (list, tuple)):
            for child in node[:600]:
                visit(child, depth + 1)

    visit(to_jsonable(value), 0)
    return list(found.values())[:limit]


LIST_KEYS = ("hits", "groups", "witnesses", "entries", "items", "results", "records", "cases", "passages", "claims", "edges",
             "rows", "senses", "fragments", "pairs", "studies", "statements", "atoms", "nodes")


VERDICTS = {"accepted": "已接受", "needs_expert": "需专家判定", "inconclusive": "不确定", "rejected": "未通过"}


def summarize(result: Any) -> str:
    """A few words for the tool card: how much came back."""
    if isinstance(result, dict):
        if "session_id" in result and isinstance(result.get("hypotheses"), list):  # a research run
            verdict = VERDICTS.get(result.get("acceptance") or "", result.get("acceptance") or result.get("status") or "")
            return f"{len(result['hypotheses'])} 个假说 · {verdict} · {result.get('rounds', '?')} 轮"
        if isinstance(result.get("steps"), list) and "report_markdown" in result:  # the V2 workflow
            skills = "→".join(s.get("skill", "") for s in result["steps"] if s.get("status") == "ok")
            return f"技能 {skills} · {len(result.get('sources') or [])} 条来源"
        if isinstance(result.get("hits"), list):
            return f"{len(result['hits'])} 条命中"
        for key in LIST_KEYS:
            if isinstance(result.get(key), list):
                return f"{len(result[key])} 项（{key}）"
        keys = [k for k in result if not k.startswith("_")]
        return "字段：" + "、".join(keys[:6]) + ("…" if len(keys) > 6 else "")
    if isinstance(result, list):
        return f"{len(result)} 项"
    if result is None:
        return "无结果"
    return str(result)[:80]
