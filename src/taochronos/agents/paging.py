"""Per-turn context: paged tool results and compaction of older turns.

A long tool result is never cut off silently.  It becomes a *paged artifact*: the model receives the first page and a
handle (page id, number of pages, items), and reads further pages with the ``context__page`` tool.  Every result is
kept this way for the task, so when older turns are compacted — each turn's messages are compiled afresh, the recent
exchanges whole and older tool results reduced to their handles — nothing is lost: it can be read again by its id.
"""

from __future__ import annotations

import json
from typing import Any

from ..capabilities.llm import Message, ToolResultBlock, ToolSchema
from ..protocol.base import to_jsonable

PAGE_TOOL = "context__page"
PAGE_SCHEMA = ToolSchema(PAGE_TOOL, "Read one page of a long tool result (the result told you its page_id and page count).",
                         {"type": "object", "properties": {"page_id": {"type": "string"}, "page": {"type": "integer"}},
                          "required": ["page_id"]})


def _dump(value: Any) -> str:
    return json.dumps(to_jsonable(value), ensure_ascii=False, default=str)


def _split(value: Any, size: int) -> list[str]:
    """Split a result into pages of at most ``size`` characters, along its structure where it has one."""
    if isinstance(value, list):
        pages, current, length = [], [], 2
        for item in value:
            text = _dump(item)
            if current and length + len(text) + 1 > size:
                pages.append("[" + ",".join(current) + "]")
                current, length = [], 2
            current.append(text)
            length += len(text) + 1
        if current:
            pages.append("[" + ",".join(current) + "]")
        return [p if len(p) <= size else p[:size] for p in pages] or ["[]"]
    if isinstance(value, dict):
        lists = [(k, v) for k, v in value.items() if isinstance(v, list)]
        if lists:
            key, items = max(lists, key=lambda kv: len(_dump(kv[1])))
            head = {k: v for k, v in value.items() if k != key}
            head_text = _dump(head)
            if len(head_text) < size // 2:
                return [f'{{"{key}": {page}, "_rest": {head_text}}}' for page in _split(items, size - len(head_text) - len(key) - 20)]
    text = _dump(value)
    return [text[i: i + size] for i in range(0, len(text), size)] or [""]


class ResultPager:
    def __init__(self, page_chars: int = 6000) -> None:
        self.page_chars = page_chars
        self.pages: dict[str, list[str]] = {}

    def render(self, call_id: str, name: str, ok: bool, result: Any, error: str | None) -> str:
        if not ok:
            return f"ERROR: {error}"
        pages = _split(result, self.page_chars)
        page_id = f"res:{call_id}"
        self.pages[page_id] = pages
        if len(pages) == 1:
            return pages[0]
        return _dump({"page_id": page_id, "page": 1, "pages": len(pages), "tool": name, "content": pages[0],
                      "note": f"a long result: call {PAGE_TOOL} with this page_id and page=2..{len(pages)} to read on"})

    def page(self, arguments: dict[str, Any]) -> tuple[str, bool]:
        pid = str(arguments.get("page_id", ""))
        pages = self.pages.get(pid)
        if pages is None:
            return f"ERROR: unknown page_id {pid!r}", True
        n = int(arguments.get("page", 1) or 1)
        if not 1 <= n <= len(pages):
            return f"ERROR: page {n} out of 1..{len(pages)}", True
        return _dump({"page_id": pid, "page": n, "pages": len(pages), "content": pages[n - 1]}), False


def compile_messages(messages: list[Message], *, keep_recent: int = 3, stub_chars: int = 240) -> list[Message]:
    """The messages of the next turn: the first (the compiled view of the research) and the last ``keep_recent``
    exchanges in full; older tool results reduced to a short stub that names the page id holding the full result."""
    tail = 2 * keep_recent
    if len(messages) <= 1 + tail:
        return list(messages)
    head, older, recent = messages[:1], messages[1:-tail], messages[-tail:]
    out = list(head)
    for m in older:
        if not m.tool_results:
            out.append(m)
            continue
        stubs = []
        for r in m.tool_results:
            content = r.content
            if len(content) > stub_chars:
                content = (content[:stub_chars] + f"… [compacted; the full result is page_id res:{r.tool_use_id} — read it with {PAGE_TOOL}]")
            stubs.append(ToolResultBlock(r.tool_use_id, content, r.is_error))
        out.append(Message(m.role, text=m.text, tool_uses=list(m.tool_uses), tool_results=stubs, raw=m.raw, images=list(m.images)))
    return out + list(recent)
