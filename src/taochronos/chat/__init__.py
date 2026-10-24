"""The chat runtime: TaoChronos as the tools of a conversational model.

A model holds the conversation (in the browser, with the user's own key); this runtime does what it asks — the tool
mesh through the scheduler (permission, argument schema, hooks and receipts all apply), the discovery research
engine, the V2 skill workflow — and answers in two forms: a compact text for the model and the value for the
interface, with the passages the result cites, so that every ``[[passage_id]]`` the model writes can be checked
against what a tool returned.

It also holds the user's own data (我的资料, the ``mydata`` capability): files the page hands it (``data_add``) are
read, made anonymous and kept in this runtime — in the browser, the browser's — for the ``mydata.*`` tools, their
passages and rows citable as ``[[mine:…]]``.

The model acts as an agent-principal actor holding read and analysis permissions only: it can propose nothing to
canonical knowledge and, unless the runtime was started with Code Mode, run no code.  The same module serves the
local server (``taochronos serve``, the full corpus) and the browser (Pyodide, the demonstration corpus), so both
answer alike.

The model writes its calls itself, and they are read here, at its side of the scheduler: a tool's name written in
another form is that tool's, arguments whose form only is wrong are repaired, and a call that still does not fit — a
name no tool has, a parameter the tool does not take — is answered with what exists, for the model to correct in one
step.  What then runs passes the scheduler's gauntlet like any call.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from .. import AGENT_NAME, __version__
from ..kernel.policy import Actor
from ..kernel.store import MemoryEventStore
from ..kernel.tools import ToolCall, closest_names, resolve_name
from ..protocol.base import to_jsonable
from ..protocol.schema import fit_arguments, signature
from ..plugins.userdata.formats import ACCEPTED, MAX_BYTES, Unreadable
from ..plugins.userdata.service import MyData
from ..plugins.userdata.store import MAX_DATASETS
from .catalog import (CODE_MODE, ENGINE_TOOLS, META_TOOLS, NEVER, PARAMETERS, catalog_view, family_counts, llm_tools, offered,
                      tool_entry)
from .jobs import Jobs
from .prompt import AGENT_NAME as AGENT_NAME_ZH
from .prompt import ASSISTANT_NAME, PUBLISHER, STARTERS, system_prompt
from .results import citations, compact, for_interface, for_model, summarize

CORPUS_LABELS = {"demo": "演示语料", "canon": "要籍语料", "full": "全量语料"}
CHAT_PERMISSIONS = frozenset({"classics:read", "kg:read", "analysis:run", "literature:read", "validation:run", "mydata:read"})
ENGINE_NAMES = {t["name"] for t in ENGINE_TOOLS} | {t["name"] for t in META_TOOLS}
MAX_ROUNDS = 6


def default_profile(home: str | Path | None = None, data_dir: str | Path | None = None) -> str:
    """The full corpus when its store has been built, the demonstration corpus otherwise (as the CLI chooses)."""
    from ..config import data_dir as default_data_dir
    from ..config import find_home

    root = find_home(str(home) if home else None)
    data = Path(data_dir) if data_dir else default_data_dir(root)
    return "full-corpus" if (data / "corpus" / "tcm.sqlite").exists() else "full-discovery"


class UnknownTool(LookupError):
    pass


class InvalidArguments(ValueError):
    pass


def shape(tool: str, ok: bool, result: Any, error: str | None = None, receipt: dict[str, Any] | None = None, *,
          duration_ms: float = 0.0, max_chars: int = 16000) -> dict[str, Any]:
    """A tool's outcome as the client receives it: ``text`` for the model, ``result`` and ``citations`` for the interface."""
    out: dict[str, Any] = {"ok": ok, "tool": tool, "duration_ms": round(duration_ms, 1)}
    if ok:
        # the model reads a research run's summary; the interface also shows its full report — and a result's charts
        seen = {k: v for k, v in result.items() if k != "report_markdown"} if tool == "taochronos_research" else for_model(result)
        out.update(text=compact(seen, max_chars), result=for_interface(result), citations=citations(result),
                   summary=summarize(result), receipt=to_jsonable(receipt or {}))
    else:
        out.update(text=f"ERROR: {error}", error=error, summary=(error or "")[:160], citations=[])
    return out


class ChatRuntime:
    def __init__(self, harness: Any, *, kind: str = "server", code_mode: bool = False) -> None:
        self.h = harness
        self.kind = kind
        self.code_mode = code_mode
        permissions = CHAT_PERMISSIONS | ({"codemode:exec"} if code_mode else frozenset())
        self.actor = Actor(id="agent:chat", role="chat", principal="agent", permissions=frozenset(permissions), name="chat")
        self.sessions: dict[str, Any] = {}
        self._research = threading.Lock()  # one research run at a time: a run installs its contract's guards harness-wide
        # the runs a server started in the background (chat/jobs.py), kept on disk where the sessions are
        kept = None if isinstance(harness.store, MemoryEventStore) else Path(harness.data_dir) / "chat" / "jobs"
        self.jobs = Jobs(self._work, lock=self._research, folder=kept)
        self._info: dict[str, Any] | None = None
        caps = harness.capabilities
        self.mydata = MyData(caps.get("study") if caps.has("study") else None)  # 我的资料: the classics read its prescriptions
        caps.register("mydata", "chat", self.mydata, default=True)

    @classmethod
    def create(cls, profile: str | None = None, *, home: str | Path | None = None, data_dir: str | Path | None = None,
               llm: str | None = None, kind: str = "server", code_mode: bool = False, ephemeral: bool = False) -> "ChatRuntime":
        from ..bootstrap import Harness

        harness = Harness.from_profile(profile or default_profile(home, data_dir), home=home, data_dir=data_dir,
                                       ephemeral=ephemeral)
        if llm:
            harness.use_llm(llm)
        return cls(harness, kind=kind, code_mode=code_mode)

    # ------------------------------------------------------------------ describe
    def info(self) -> dict[str, Any]:
        if self._info is None:
            corpus = self.h.corpus
            stats = corpus.stats(self.h.pack.periods)
            large = bool(getattr(corpus, "large", False))
            kind = ("canon" if getattr(corpus, "edition", "full") == "web" else "full") if large else "demo"
            study = self.h.capabilities.get("study")
            canon = study.canon(limit=1) if study is not None and hasattr(study, "canon") else {"listed": 0, "held_here": 0}
            judge = dict(self.h.profile.judge or {})
            info: dict[str, Any] = {
                "name": AGENT_NAME,
                "version": __version__,
                "runtime": self.kind,
                "profile": self.h.profile.name,
                "corpus": {"books": stats.get("books"), "passages": stats.get("passages"), "characters": stats.get("characters"),
                           "by_period": stats.get("by_period", {}), "large": large, "demo": kind != "full", "kind": kind,
                           "label": CORPUS_LABELS[kind], "canon": {"listed": canon["listed"], "held": canon["held_here"]}},
                "tools": {"offered": len(offered(self.h.tools, code_mode=self.code_mode)) + len(ENGINE_TOOLS),
                          "families": family_counts(self.h.tools, code_mode=self.code_mode)},
                "assistant_name": ASSISTANT_NAME, "agent_name": AGENT_NAME_ZH, "publisher": PUBLISHER,
                "engine_model": f"{judge['provider']}:{judge.get('model', '')}" if judge.get("provider") else None,
                "code_mode": self.code_mode,
                "starters": STARTERS,
                "mydata": {"accepted": list(ACCEPTED), "max_bytes": MAX_BYTES, "max_datasets": MAX_DATASETS,
                           "prescriptions": self.mydata.reader is not None},
            }
            info["system_prompt"] = system_prompt(info)
            self._info = info
        return self._info

    def catalog(self, mode: str = "core") -> dict[str, Any]:
        """The tools offered to the model; in ``core`` mode with the 我的资料 tools apart (``mydata``), which the page
        offers too while the user has data."""
        out = {"mode": mode, "tools": llm_tools(self.h.tools, mode=mode, code_mode=self.code_mode),
               "families": family_counts(self.h.tools, code_mode=self.code_mode)}
        if mode == "core":
            out["mydata"] = [tool_entry(s) for s in offered(self.h.tools, code_mode=self.code_mode) if s.family == "mydata"]
        return out

    # ---------------------------------------------------------------------- call
    def _resolve(self, name: str) -> str:
        try:
            spec = self.h.tools.get(name)  # accepts dotted names and model names (dots as "__")
        except KeyError:
            raise UnknownTool(f"unknown tool {name!r}; use taochronos_catalog to see what exists") from None
        if spec.name in NEVER:
            raise PermissionError(f"{spec.name} is not offered to a chat model: proposals to canonical knowledge are made by people")
        if spec.name == CODE_MODE and not self.code_mode:
            raise PermissionError("Code Mode is off in this runtime (start the local server with --code-mode to allow it)")
        return spec.name

    def _names(self) -> list[tuple[str, str]]:
        """Every tool a model may call here, with its family: the mesh tools offered, the engine and the meta-tools."""
        return ([(s.name, s.family) for s in offered(self.h.tools, code_mode=self.code_mode)]
                + [(t["name"], t["family"]) for t in (*ENGINE_TOOLS, *META_TOOLS)])

    def _schema(self, name: str) -> dict[str, Any]:
        return PARAMETERS[name] if name in PARAMETERS else self.h.tools.get(name).input_schema

    def _canonical(self, name: str) -> str:
        """The tool a model's name denotes: the name itself (a mesh tool's model name too), or the one tool offered whose
        name it writes in another form (``get_passage``, ``taochronos.catalog``); else :class:`UnknownTool`, which names
        the closest tools offered and what they take."""
        name = str(name or "")
        if name in ENGINE_NAMES or self.h.tools.has(name):
            return name
        names = self._names()
        found = resolve_name(name, [n for n, _ in names])
        if found is not None:
            return found
        near = " · ".join(f"{n} {{{signature(self._schema(n), limit=6)}}}" for n in closest_names(name, names))
        raise UnknownTool(f"unknown tool {name!r}; closest: {near}; use taochronos_catalog to see what exists")

    def call(self, name: str, arguments: dict[str, Any] | None = None, *, max_chars: int = 16000) -> dict[str, Any]:
        """Run one tool the model asked for; never raises — a failure is a result the model can read.  A name written in
        another form is the tool's it denotes; arguments are read against the tool's parameters (``fit_arguments``): their
        form repaired where only that was wrong (the outcome's ``repaired`` says how), and a call they still do not fit —
        a parameter the tool does not take, which it would otherwise ignore — answered with what the tool takes."""
        started = time.perf_counter()
        tool, ok, result, error, receipt, repaired = name, False, None, None, {}, []
        try:
            name = self._canonical(name)
            if name == "taochronos_call":
                arguments, _, problem = fit_arguments(arguments if arguments is not None else {}, PARAMETERS[name], tool=name)
                if problem:
                    raise InvalidArguments(problem)
                inner = str(arguments.get("tool") or "")
                if not inner:
                    raise ValueError("taochronos_call needs {\"tool\": <name>, \"arguments\": {...}}")
                inner = self._canonical(inner)
                if inner in ENGINE_NAMES:
                    return {**self.call(inner, arguments.get("arguments") or {}, max_chars=max_chars), "via": "taochronos_call"}
                name, arguments = inner, arguments.get("arguments") or {}
            tool = name if name in ENGINE_NAMES else self._resolve(name)
            arguments, repaired, problem = fit_arguments(arguments if arguments is not None else {}, self._schema(tool), tool=tool)
            if problem:
                raise InvalidArguments(problem)
            if tool in ENGINE_NAMES:
                result, ok = self._engine_tool(tool, arguments), True
            else:
                outcome = self.h.scheduler.execute(ToolCall(tool, arguments), actor=self.actor)
                ok, result, error, receipt = outcome.ok, outcome.result, outcome.error, outcome.receipt
        except (UnknownTool, InvalidArguments) as exc:
            error = str(exc)
        except Exception as exc:  # a failing tool is data for the model, not a crash of the conversation
            error = f"{type(exc).__name__}: {exc}"
        out = shape(tool, ok, result, error, receipt, duration_ms=(time.perf_counter() - started) * 1000, max_chars=max_chars)
        if repaired:
            out["repaired"] = repaired
        for card in out.get("citations") or []:  # a row or passage of the user's data, as the page names it (for the page only)
            if str(card.get("passage_id", "")).startswith("mine:"):
                try:
                    full = self.mydata.card(card["passage_id"])
                except LookupError:
                    continue
                card.update({k: v for k, v in full.items() if k != "passage_id"}, text=full["text"][:240])
        return out

    def _engine_tool(self, name: str, a: dict[str, Any]) -> Any:
        spec = next(t for t in (*ENGINE_TOOLS, *META_TOOLS) if t["name"] == name)
        missing = [k for k in spec["parameters"].get("required", []) if a.get(k) in (None, "")]
        if missing:
            raise ValueError(f"{name} needs {', '.join(missing)}")
        if name == "taochronos_catalog":
            return catalog_view(self.h.tools, family=a.get("family"), query=a.get("query"), code_mode=self.code_mode)
        if name == "taochronos_research":
            return self.research(**{k: a[k] for k in ("question", "focus_terms", "tracks", "max_rounds", "forbidden_assumptions",
                                                      "holdout_after", "books") if a.get(k) not in (None, "", [])})
        if name == "taochronos_session":
            return self.session_view(a["session_id"], what=a.get("what", "summary"), hypothesis=a.get("hypothesis"),
                                     section=a.get("section"))
        if name == "taochronos_ask":
            return self.ask(a["question"])
        raise KeyError(name)

    # ------------------------------------------------------------------ passages
    def passage(self, passage_id: str) -> dict[str, Any]:
        """A passage in full, for the evidence drawer (and to check a citation the model wrote) — a passage or row of the
        user's data too (``mine:…``)."""
        if passage_id.startswith("mine:"):
            try:
                return {"ok": True, **self.mydata.card(passage_id)}
            except LookupError as exc:
                return {"ok": False, "passage_id": passage_id, "error": str(exc)}
        outcome = self.h.scheduler.execute(ToolCall("classics.get_passage", {"passage_id": passage_id}), actor=self.actor)
        if not outcome.ok:
            return {"ok": False, "passage_id": passage_id, "error": outcome.error}
        return {"ok": True, **to_jsonable(outcome.result)}

    # ------------------------------------------------------------------ 我的资料
    def data_add(self, name: str, data: bytes) -> dict[str, Any]:
        """Read a file of the user's, make it anonymous and keep it: the dataset's summary, or why it cannot be read."""
        try:
            return {"ok": True, "dataset": self.mydata.add(str(name or "资料"), bytes(data))}
        except Unreadable as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:  # a damaged file: the reason, not a crash
            return {"ok": False, "error": f"无法读取「{name}」：文件可能已损坏或格式不符（{type(exc).__name__}）"}

    def data_list(self) -> dict[str, Any]:
        return self.mydata.datasets()

    def data_remove(self, ds_id: str) -> dict[str, Any]:
        try:
            return {"ok": True, **self.mydata.remove(ds_id)}
        except LookupError as exc:
            return {"ok": False, "error": str(exc)}

    def data_clear(self) -> dict[str, Any]:
        return {"ok": True, **self.mydata.clear()}

    def data_export(self, ds_id: str) -> dict[str, Any]:
        """A dataset as plain data, for the browser to keep (the runtime there starts afresh at each visit)."""
        return self.mydata.export(ds_id)

    def data_restore(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return {"ok": True, "dataset": self.mydata.restore(payload)}
        except Exception as exc:  # kept by an older page in a form this one does not read: dropped by the page
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    # ------------------------------------------------------------------ research
    def _goal(self, question: str, *, focus_terms: list[str] | None = None, tracks: list[str] | None = None,
              max_rounds: int | None = None, forbidden_assumptions: list[str] | None = None, holdout_after: int | None = None,
              books: list[str] | None = None) -> Any:
        fields: dict[str, Any] = {}
        if focus_terms:
            fields["focus_terms"] = [str(t) for t in focus_terms if str(t).strip()]
        if tracks:
            fields["tracks"] = [t.strip().upper() for t in tracks if t.strip().upper() in ("D1", "D2", "D3", "D4", "D5")]
        if max_rounds:
            fields["stop"] = {"max_rounds": max(1, min(int(max_rounds), MAX_ROUNDS))}
        if forbidden_assumptions:
            fields["forbidden_assumptions"] = [str(x) for x in forbidden_assumptions]
        if holdout_after is not None:
            fields["holdout_after"] = int(holdout_after)
        if books:
            fields["corpus"] = {"books": [str(b) for b in books]}
        return self.h.make_goal(question, **fields)

    def research(self, question: str, **fields: Any) -> dict[str, Any]:
        """A discovery research run, start to finish; returns its summary."""
        with self._research:
            engine = self.h.engine()
            session = engine.start(self._goal(question, **fields))
            self.sessions[session.id] = session
            engine.run(session)
        return self.summary(session)

    def start_research(self, question: str, **fields: Any) -> str:
        """The same run in the background (a server): queued, and a job id to follow with :meth:`job` (chat/jobs.py)."""
        return self.jobs.start(question, fields)

    def job(self, job_id: str) -> dict[str, Any]:
        """A background run: its state, its place in the queue, its times, heartbeat and progress, and its outcome."""
        return self.jobs.view(job_id)

    def cancel_research(self, job_id: str) -> dict[str, Any]:
        """Stop a background run: at once while it waits, at the end of the task it runs once it has begun."""
        return self.jobs.cancel(job_id)

    def resume_research(self, job_id: str) -> dict[str, Any]:
        """Queue again a run the server stopped while it went on: from its session's last checkpoint."""
        return self.jobs.resume(job_id)

    def _work(self, job: dict[str, Any], stop: Any, attach: Any) -> dict[str, Any]:
        """A background run of the job's question, or of its session again (resumed), until it ends or `stop` says to."""
        started = time.time()
        engine = self.h.engine()
        if job.get("session"):
            session = engine.open(job["session"])  # its log, from the store: the run goes on from its last checkpoint
        else:
            session = engine.start(self._goal(job["question"], **job.get("arguments", {})))
        self.sessions[session.id] = session
        attach(session)
        engine.run(session, stop=stop)
        return shape("taochronos_research", True, self.summary(session), duration_ms=(time.time() - started) * 1000)

    def _session(self, session_id: str) -> Any:
        session = self.sessions.get(session_id)
        if session is None:
            session = self.h.engine().open(session_id)  # a session this runtime did not start, from the store
            self.sessions[session_id] = session
        return session

    def _evidence_card(self, state: Any, evidence_id: str) -> dict[str, Any] | None:
        e = state.evidence.get(evidence_id)
        if e is None:
            return None
        card: dict[str, Any] = {"evidence_id": evidence_id, "passage_id": e.passage_id, "quote": e.quote[:200],
                                "stance": getattr(e.stance, "value", str(e.stance))}
        try:
            book = self.h.corpus.book(e.book_id)
            card.update(title=book.title, dynasty=book.dynasty, locator=e.locator.label() if e.locator else "")
            card["year"] = self.h.corpus.year(self.h.corpus.passage(e.passage_id))
        except Exception:
            pass
        return card

    def summary(self, session: Any, *, hypotheses: int = 8) -> dict[str, Any]:
        from ..engine.report import build

        state = session.state
        _, md, payload = build(self.h, state, session.id)
        acceptance = payload.get("acceptance") or {}
        verdicts = {j.get("hypothesis_id"): j.get("status") for j in acceptance.get("hypotheses", [])}
        hyps = []
        for i, hy in enumerate(payload["hypotheses"][:hypotheses], 1):
            support = [c for c in (self._evidence_card(state, x) for x in hy.get("supporting_evidence", [])[:4]) if c]
            against = [c for c in (self._evidence_card(state, x) for x in hy.get("contradictory_evidence", [])[:3]) if c]
            hyps.append({
                "label": f"H{i}", "id": hy["id"], "kind": hy.get("kind"), "statement": hy.get("statement"),
                "status": hy.get("status"), "acceptance": verdicts.get(hy["id"]), "discovery_score": hy.get("discovery_score"),
                "novelty": hy.get("novelty"), "terms": hy.get("terms", [])[:8],
                "supporting": support, "contradicting": against,
                "alternatives": (hy.get("alternative_explanations") or [])[:3],
                "prediction": hy.get("testable_prediction"),
                "risks": {"philological": hy.get("philological_risk"), "anachronism": hy.get("anachronism_risk")},
            })
        metrics = {**(state.metrics or {}), **(payload.get("metrics") or {})}
        return {
            "session_id": session.id,
            "question": state.goal.question if state.goal else None,
            "status": (state.stop or {}).get("status", state.status),
            "acceptance": acceptance.get("status"),
            "acceptance_reasons": acceptance.get("reasons", [])[:6],
            "rounds": state.round,
            "metrics": {k: metrics.get(k) for k in ("claims", "evidence_count", "counter_evidence", "hypotheses",
                                                    "hypothesis_survival", "agents_spawned", "tool_calls")},
            "hypotheses": hyps,
            "rejected": len(payload.get("rejected") or []),
            "sections": [s["title"] for s in payload["report"]["sections"]],
            "report_markdown": md,
            "note": "假说是计算推断（Computational Hypothesis Space），不构成医学结论，须经专家核验（G7）。",
        }

    def session_view(self, session_id: str, *, what: str = "summary", hypothesis: str | None = None,
                     section: str | None = None) -> dict[str, Any]:
        session = self._session(session_id)
        if what == "summary":
            out = self.summary(session)
            out.pop("report_markdown", None)
            return out
        from ..engine.report import build, evidence_table

        _, md, payload = build(self.h, session.state, session.id)
        if what == "report":
            if section:
                chosen = [s for s in payload["report"]["sections"] if section in s["title"]]
                return {"sections": chosen or payload["report"]["sections"], "matched": bool(chosen)}
            return {"report_markdown": md}
        if what == "hypothesis":
            key = (hypothesis or "").strip()
            hyps = payload["hypotheses"] + payload.get("rejected", [])
            if key.upper().startswith("H") and key[1:].isdigit():
                idx = int(key[1:]) - 1
                chosen = payload["hypotheses"][idx] if 0 <= idx < len(payload["hypotheses"]) else None
            else:
                chosen = next((h for h in hyps if h["id"] == key), None)
            if chosen is None:
                return {"error": f"no hypothesis {key!r}", "available": [f"H{i}" for i in range(1, len(payload['hypotheses']) + 1)]}
            state = session.state
            return {**chosen, "supporting_cards": [self._evidence_card(state, x) for x in chosen.get("supporting_evidence", [])],
                    "contradicting_cards": [self._evidence_card(state, x) for x in chosen.get("contradictory_evidence", [])]}
        if what == "evidence":
            return {"csv": evidence_table(self.h, session.state)}
        raise ValueError(f"what must be summary, report, hypothesis or evidence, not {what!r}")

    # ---------------------------------------------------------------- workflow
    def ask(self, question: str) -> dict[str, Any]:
        """The V2 workflow: skills compiled into a DAG, run, audited; the report and the steps it took.  A source the
        search found under another name of a drug, or flagged, carries ``labels`` (ADR 0023): each ``via`` and flag in
        words, as the evidence ledger's notes say them (``via 国老→甘草（别名录（中醫笈成））``, ``年代存疑（…）``)."""
        from ..engine.workflow import ask

        run = ask(self.h, question, resume=False)
        steps = [{"skill": s.get("skill"), "name": s.get("name"), "agent": s.get("agent"), "status": s.get("status"),
                  "calls": s.get("calls")} for s in run.get("steps", [])]
        sources = citations([s.get("results") for s in run.get("steps", [])], limit=40)
        labels = {p["passage_id"]: p["labels"] for p in (run.get("context") or {}).get("passages") or [] if p.get("labels")}
        for card in sources:
            if card.get("passage_id") in labels:
                card["labels"] = list(labels[card["passage_id"]])
        return {"run": run.get("run"), "plan": {k: run["plan"].get(k) for k in ("skills", "reasons", "by")},
                "steps": steps, "report_markdown": run.get("report", ""), "sources": sources}


__all__ = ["CHAT_PERMISSIONS", "ChatRuntime", "default_profile", "shape"]
