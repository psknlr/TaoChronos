"""Record and replay model responses, so a research can be replayed exactly.

``record``: every response is saved under the hash of its request (model, system prompt, messages, tools, limits).
``replay``: the saved response is returned and the provider is never called; a request with no recording is an error,
not a live call — an exact replay reads only what was saved.  Keys and prompts are not in the file names; the files
hold the responses (text and tool calls) and their usage, which is what a replay needs.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .llm import LLMError, LLMRequest, LLMResponse, ToolUse, Usage

MODES = ("record", "replay")


def request_key(request: LLMRequest) -> str:
    def msg(m: Any) -> dict[str, Any]:
        return {"role": m.role, "text": m.text,
                "tool_uses": [{"id": u.id, "name": u.name, "input": u.input} for u in m.tool_uses],
                "tool_results": [{"id": r.tool_use_id, "content": r.content, "error": r.is_error} for r in m.tool_results],
                "images": [hashlib.sha256(i.data).hexdigest() for i in m.images]}

    body = {"model": request.model, "system": request.system, "messages": [msg(m) for m in request.messages],
            "tools": [{"name": t.name, "schema": t.input_schema} for t in request.tools], "max_tokens": request.max_tokens,
            "effort": request.effort, "temperature": request.temperature, "json": request.json}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:32]


class RecordingProvider:
    def __init__(self, inner: Any, root: str | Path, mode: str = "record") -> None:
        if mode not in MODES:
            raise ValueError(f"recording mode is one of {MODES}, not {mode!r}")
        self.inner = inner
        self.root = Path(root)
        self.mode = mode
        self.name = getattr(inner, "name", "recorded")
        self.deterministic = getattr(inner, "deterministic", False)
        self.hits = self.misses = 0

    def models(self) -> list[Any]:
        return self.inner.models()

    def available(self) -> bool:
        return True if self.mode == "replay" else self.inner.available()

    def _path(self, request: LLMRequest) -> Path:
        return self.root / f"{request_key(request)}.json"

    def complete(self, request: LLMRequest) -> LLMResponse:
        path = self._path(request)
        if self.mode == "replay":
            if not path.exists():
                self.misses += 1
                raise LLMError(f"no recorded response for this request ({path.name}): an exact replay does not call the model")
            self.hits += 1
            data = json.loads(path.read_text(encoding="utf-8"))
            return LLMResponse(text=data["text"], tool_uses=[ToolUse(**u) for u in data["tool_uses"]], stop_reason=data["stop_reason"],
                               usage=Usage(**data["usage"]), model=data.get("model", ""), note=f"replayed {path.name}")
        response = self.inner.complete(request)
        self.root.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"text": response.text, "stop_reason": response.stop_reason, "model": response.model,
                                    "tool_uses": [{"id": u.id, "name": u.name, "input": u.input} for u in response.tool_uses],
                                    "usage": {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens,
                                              "cost_usd": response.usage.cost_usd}}, ensure_ascii=False), encoding="utf-8")
        return response
