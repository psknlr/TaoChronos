"""Rules screen, a model judges, rules stay accountable: the provider-neutral judgement layer.

Every capability of the study layer is deterministic first: rules and statistics find the
candidates cheaply over the whole corpus and decide what they can.  A ``Judge`` is how a
language model is then asked, *after* the rules, to adjudicate what they could not settle
(a stance, an entity type, a mark between two characters) or to write a summary of results
the rules produced.  Four guarantees:

* **Validated or discarded.** Every answer is one JSON object that must validate against the
  task's schema and pass the task's own checks (labels from the allowed set, quotes found
  verbatim in the source, not a character of the text changed …).  One repair turn is
  allowed; an answer that still fails is dropped and the rule's decision stands.
* **Recorded.** Each item keeps the rule's decision, the model's, the final one and who made
  it (``rule`` · ``model`` · ``both``), so agreement between rules and model is measured and
  every change can be reviewed.
* **Reproducible and bounded.** Answers are cached by the digest of the request (the same
  question costs once; a rerun is identical); calls, tokens and cost are counted against a
  budget, and a run past its budget keeps the rules' decisions for the rest.
* **Cited.** A synthesis must cite the evidence ids it rests on, sentence by sentence;
  sentences without a valid citation, and quotes that are not in the evidence cited, are
  removed and reported.

The judge knows nothing of the classics: prompts, schemas and checks come from the caller.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from ..protocol.schema import validate
from .llm import ImageBlock, LLMError, LLMProvider, LLMRequest, Message

THINK = re.compile(r"^\s*<think>.*?</think>\s*", re.S)
FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def extract_json(text: str) -> tuple[Any, str | None]:
    """The first JSON object (or array) in a reply, fenced or not; (value, error)."""
    body = THINK.sub("", text or "", count=1).strip()
    fence = FENCE.search(body)
    if fence:
        body = fence.group(1).strip()
    starts = [i for i in (body.find("{"), body.find("[")) if i >= 0]
    if not starts:
        return None, "no JSON object found"
    start = min(starts)
    closer = "}" if body[start] == "{" else "]"
    end = body.rfind(closer)
    if end <= start:
        return None, "no complete JSON object found"
    try:
        return json.loads(body[start: end + 1]), None
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"


class JudgeBudgetExceeded(RuntimeError):
    pass


@dataclass
class JudgeBudget:
    max_calls: int = 200
    max_cost_usd: float = 5.0
    max_tokens: int = 2_000_000
    calls: int = 0
    cost_usd: float = 0.0
    tokens: int = 0

    def check(self) -> None:
        if self.calls >= self.max_calls:
            raise JudgeBudgetExceeded(f"model calls {self.calls} reached the limit {self.max_calls}")
        if self.cost_usd >= self.max_cost_usd:
            raise JudgeBudgetExceeded(f"cost ${self.cost_usd:.2f} reached the limit ${self.max_cost_usd:.2f}")
        if self.tokens >= self.max_tokens:
            raise JudgeBudgetExceeded(f"tokens {self.tokens} reached the limit {self.max_tokens}")

    def charge(self, input_tokens: int, output_tokens: int, cost_usd: float) -> None:
        self.calls += 1
        self.tokens += input_tokens + output_tokens
        self.cost_usd += cost_usd

    def to_dict(self) -> dict[str, Any]:
        return {"calls": self.calls, "tokens": self.tokens, "cost_usd": round(self.cost_usd, 4),
                "limits": {"calls": self.max_calls, "cost_usd": self.max_cost_usd, "tokens": self.max_tokens}}


@dataclass
class JudgeResult:
    ok: bool
    data: Any = None
    error: str | None = None
    cached: bool = False
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    attempts: int = 0


Check = Callable[[Any], list[str]]


class Judge:
    """A model asked for structured judgements, through any ``LLMProvider``."""

    def __init__(self, provider: LLMProvider, model: str, *, cache_dir: str | Path | None = None,
                 log_path: str | Path | None = None, budget: JudgeBudget | None = None, temperature: float | None = 0.0,
                 max_tokens: int = 4000, refresh: bool = False) -> None:
        self.provider = provider
        self.model = model
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.log_path = Path(log_path) if log_path else None
        self.budget = budget or JudgeBudget()
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.refresh = refresh
        self.stats: dict[str, dict[str, int]] = {}

    @property
    def label(self) -> str:
        return f"{getattr(self.provider, 'name', 'llm')}:{self.model}"

    # ----------------------------------------------------------------- cache
    def _key(self, task: str, system: str, prompt: str, schema: dict[str, Any] | None, images: list[ImageBlock]) -> str:
        h = hashlib.sha256()
        for part in (self.label, task, system, prompt, json.dumps(schema or {}, sort_keys=True, ensure_ascii=False),
                     str(self.temperature)):
            h.update(part.encode("utf-8"))
            h.update(b"\x00")
        for img in images:
            h.update(hashlib.sha256(img.data).digest())
        return h.hexdigest()

    def _cache_get(self, key: str) -> dict[str, Any] | None:
        if self.cache_dir is None or self.refresh:
            return None
        path = self.cache_dir / key[:2] / f"{key}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _cache_put(self, key: str, value: dict[str, Any]) -> None:
        if self.cache_dir is None:
            return
        path = self.cache_dir / key[:2] / f"{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    def _log(self, record: dict[str, Any]) -> None:
        if self.log_path is None:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _count(self, task: str, key: str) -> None:
        row = self.stats.setdefault(task, {"asked": 0, "cached": 0, "valid": 0, "invalid": 0, "errors": 0})
        row[key] = row.get(key, 0) + 1

    # ------------------------------------------------------------------- ask
    def ask(self, task: str, system: str, prompt: str, *, schema: dict[str, Any] | None = None, check: Check | None = None,
            images: Iterable[ImageBlock] = (), max_tokens: int | None = None) -> JudgeResult:
        """One structured judgement: a JSON value that validates against ``schema`` and passes ``check``."""
        images = list(images)
        key = self._key(task, system, prompt, schema, images)
        self._count(task, "asked")
        hit = self._cache_get(key)
        if hit is not None:
            self._count(task, "cached")
            data = hit.get("data")
            errors = self._errors(data, schema, check)
            if not errors:
                self._count(task, "valid")
                return JudgeResult(ok=True, data=data, cached=True, model=hit.get("model", self.model))
        instruction = ("\n\nReturn only one JSON value" + (" matching this JSON Schema:\n" + json.dumps(schema, ensure_ascii=False)
                                                            if schema else ".") )
        messages = [Message("user", prompt + instruction, images=images)]
        started = time.perf_counter()
        result = JudgeResult(ok=False, model=self.model)
        for attempt in range(2):
            try:
                self.budget.check()
            except JudgeBudgetExceeded as exc:
                result.error = f"budget: {exc}"
                break
            request = LLMRequest(model=self.model, system=system, messages=messages, max_tokens=max_tokens or self.max_tokens,
                                 temperature=self.temperature, json=True, metadata={"task": task})
            try:
                response = self.provider.complete(request)
            except LLMError as exc:
                self._count(task, "errors")
                result.error = f"model error: {exc}"
                break
            u = response.usage
            self.budget.charge(u.input_tokens, u.output_tokens, u.cost_usd)
            result.input_tokens += u.input_tokens
            result.output_tokens += u.output_tokens
            result.cost_usd += u.cost_usd
            result.attempts = attempt + 1
            result.model = response.model or self.model
            if response.stop_reason == "refusal":
                result.error = "the model declined" + (f" ({response.note})" if response.note else "")
                break
            data, error = extract_json(response.text)
            errors = [error] if error else self._errors(data, schema, check)
            if not errors:
                result.ok, result.data, result.error = True, data, None
                break
            result.error = "; ".join(errors[:6])
            messages += [Message("assistant", response.text),
                         Message("user", "That answer does not pass the checks: " + result.error[:1500]
                                 + ". Return only the corrected JSON value.")]
        result.latency_ms = round((time.perf_counter() - started) * 1000, 1)
        self._count(task, "valid" if result.ok else "invalid")
        if result.ok:
            self._cache_put(key, {"data": result.data, "model": result.model, "task": task})
        self._log({"ts": time.time(), "task": task, "judge": self.label, "key": key[:16], "ok": result.ok, "error": result.error,
                   "attempts": result.attempts, "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
                   "cost_usd": round(result.cost_usd, 6), "latency_ms": result.latency_ms})
        return result

    @staticmethod
    def _errors(data: Any, schema: dict[str, Any] | None, check: Check | None) -> list[str]:
        errors = validate(data, schema) if schema else []
        if not errors and check is not None:
            try:
                errors = list(check(data) or [])
            except Exception as exc:  # a check that crashes rejects the answer
                errors = [f"check failed: {type(exc).__name__}: {exc}"]
        return errors

    def report(self) -> dict[str, Any]:
        return {"judge": self.label, "budget": self.budget.to_dict(), "tasks": self.stats}


# ------------------------------------------------------------------ adjudication
@dataclass
class Decision:
    """One item decided by rules, reviewed by a model when it was asked."""

    id: str
    rule: Any
    final: Any
    model: Any = None
    decided_by: str = "rule"  # rule | model | both (agree)
    asked: bool = False
    reason: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def adjudicate(judge: Judge | None, items: list[dict[str, Any]], *, task: str, system: str,
               render: Callable[[list[dict[str, Any]]], str], allowed: Iterable[Any] | None = None,
               item_check: Callable[[dict[str, Any], dict[str, Any]], list[str]] | None = None,
               select: Callable[[dict[str, Any]], bool] | None = None, batch: int = 20,
               value_key: str = "label") -> tuple[list[Decision], dict[str, Any]]:
    """Rules first: every item carries ``id`` and ``rule`` (the rule's decision).  The items that
    ``select`` picks (all, by default) go to the model in batches; it answers
    ``{"decisions": [{"id", value_key, "reason"}]}``.  A decision is taken only when it validates
    (a known id, a value in ``allowed``, ``item_check`` passes); otherwise the rule's stands."""
    allowed_set = list(allowed) if allowed is not None else None
    decisions = {it["id"]: Decision(id=it["id"], rule=it["rule"], final=it["rule"]) for it in items}
    summary: dict[str, Any] = {"items": len(items), "asked": 0, "answered": 0, "changed": 0, "agreed": 0, "invalid": 0,
                               "failed_batches": 0, "judge": judge.label if judge else None}
    if judge is None:
        summary["note"] = "no model configured: rules only"
        return list(decisions.values()), summary
    chosen = [it for it in items if select is None or select(it)]
    by_id = {it["id"]: it for it in chosen}
    value_schema: dict[str, Any] = {"enum": allowed_set} if allowed_set is not None else {}
    schema = {"type": "object", "required": ["decisions"], "properties": {"decisions": {"type": "array", "items": {
        "type": "object", "required": ["id", value_key], "properties": {"id": {"type": "string"}, value_key: value_schema,
                                                                          "reason": {"type": "string"}}}}}}
    for start in range(0, len(chosen), batch):
        group = chosen[start: start + batch]
        ids = {it["id"] for it in group}

        def check(data: Any, ids: set[str] = ids) -> list[str]:
            errs = []
            for d in data.get("decisions", []):
                if d.get("id") not in ids:
                    errs.append(f"unknown id {d.get('id')!r}")
            return errs

        summary["asked"] += len(group)
        for it in group:
            decisions[it["id"]].asked = True
        try:
            res = judge.ask(task, system, render(group), schema=schema, check=check)
        except JudgeBudgetExceeded as exc:
            summary["note"] = str(exc)
            break
        if not res.ok:
            summary["failed_batches"] += 1
            summary.setdefault("errors", []).append(res.error)
            if res.error and res.error.startswith("budget"):
                summary["note"] = res.error
                break
            continue
        for d in res.data.get("decisions", []):
            item = by_id.get(d["id"])
            if item is None:
                continue
            value = d.get(value_key)
            problems = item_check(item, d) if item_check else []
            dec = decisions[d["id"]]
            if problems:
                summary["invalid"] += 1
                dec.note = "; ".join(problems)[:300]
                continue
            summary["answered"] += 1
            dec.model, dec.reason = value, str(d.get("reason", ""))[:300]
            if value == dec.rule:
                dec.decided_by = "both"
                summary["agreed"] += 1
            else:
                dec.final, dec.decided_by = value, "model"
                summary["changed"] += 1
    answered = summary["answered"]
    summary["agreement"] = round(summary["agreed"] / answered, 3) if answered else None
    return list(decisions.values()), summary


# -------------------------------------------------------------------- synthesis
@dataclass
class Synthesis:
    ok: bool
    sentences: list[dict[str, Any]] = field(default_factory=list)  # {text, cites}
    dropped: list[dict[str, Any]] = field(default_factory=list)  # {text, why}
    error: str | None = None
    judge: str | None = None

    @property
    def text(self) -> str:
        return "".join(s["text"] + "".join(f"[{c}]" for c in s["cites"]) for s in self.sentences)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "text": self.text, "sentences": self.sentences, "dropped": self.dropped, "error": self.error,
                "judge": self.judge}


QUOTE = re.compile(r"[「“]([^」”]{2,})[」”]")

SYNTHESIS_SCHEMA = {"type": "object", "required": ["sentences"], "properties": {"sentences": {"type": "array", "items": {
    "type": "object", "required": ["text", "cites"],
    "properties": {"text": {"type": "string"}, "cites": {"type": "array", "items": {"type": "string"}}}}}}}


def synthesize(judge: Judge | None, *, task: str, system: str, question: str, evidence: list[dict[str, Any]],
               max_sentences: int = 8, instructions: str = "") -> Synthesis:
    """A cited summary: each sentence cites evidence ids (``E1`` …) and quotes only what they say.

    ``evidence`` items are ``{"id", "text", "source"?}``; sentences whose citations are unknown,
    or whose 「quotes」 are not in the evidence they cite, are dropped and reported."""
    if judge is None:
        return Synthesis(ok=False, error="no model configured")
    texts = {e["id"]: e.get("text", "") for e in evidence}
    lines = [f"[{e['id']}] {e.get('source', '')} {e.get('text', '')}".strip() for e in evidence]
    prompt = (f"{question}\n\n{instructions}\nEvidence (cite by id, e.g. [E1]):\n" + "\n".join(lines)
              + f"\n\nWrite at most {max_sentences} sentences as {{\"sentences\": [{{\"text\": …, \"cites\": [\"E1\", …]}}]}}. "
              "Every sentence cites at least one evidence id; put words quoted from the evidence in 「」 exactly as written there; "
              "say only what the cited evidence supports.")

    def check(data: Any) -> list[str]:
        if not data.get("sentences"):
            return ["no sentences"]
        return [] if any(set(s.get("cites") or []) & set(texts) for s in data["sentences"]) else ["no sentence cites known evidence"]

    res = judge.ask(task, system, prompt, schema=SYNTHESIS_SCHEMA, check=check)
    if not res.ok:
        return Synthesis(ok=False, error=res.error, judge=judge.label)
    out = Synthesis(ok=True, judge=judge.label)
    for s in res.data["sentences"][:max_sentences]:
        text, cites = str(s.get("text", "")).strip(), [c for c in s.get("cites") or [] if c in texts]
        unknown = [c for c in s.get("cites") or [] if c not in texts]
        if not text:
            continue
        if not cites:
            out.dropped.append({"text": text, "why": "cites no known evidence" + (f" ({', '.join(unknown)})" if unknown else "")})
            continue
        missing = [q for q in QUOTE.findall(text) if not any(q in texts[c] for c in cites)]
        if missing:
            out.dropped.append({"text": text, "why": "quotes not found in the cited evidence: " + "、".join(missing)})
            continue
        out.sentences.append({"text": text, "cites": cites})
    out.ok = bool(out.sentences)
    if not out.ok:
        out.error = "no sentence survived the citation checks"
    return out
