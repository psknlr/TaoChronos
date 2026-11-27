"""The numbers of the conversation records (``data/chat-logs/``): where a turn's time went, how often a model request
that broke off was recovered from, how often an answer came whole and checked — counts and times only, never a word of
a record.

A visitor who agreed has each finished turn recorded (web/js/records.js, relay/README.md): its question and answer, its
tools, how its citations were checked and, from the page that times them (web/js/records.js, ``timings``), each model
request's times and end, each call's waiting and running, and how long the page was hidden or did not run — in the turn,
and while each model request was asked — each time in milliseconds from the turn's start.  :func:`summary` reads
records of either kind: one without the times counts towards the answers' completion only.  A turn taken up again
(继续作答) is recorded again, its times from then on: the summary counts it once, as its last record ended, with the
failures and the time of all of them.

The same files hold the visitors' feedback on answers (``"kind": "feedback"``: 👍 or 👎, the reasons ticked, what they
wrote; web/js/records.js), sent by any visitor who chose to give it, whether or not their turns are recorded.  They are
not turns: :func:`summary` counts them apart (:func:`ratings`), the last word on each turn standing.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

# a service's word for a reply it finished: OpenAI-compatible services, Claude
FINISHED = frozenset({"stop", "end_turn", "stop_sequence"})
# how a model request that broke off failed (agent.js, failure): it stalled or never answered (a limit, "timeout"), its
# stream ended before the model said it was done, the connection failed — or the service did (its HTTP status a 5xx)
BROKE_OFF = frozenset({"timeout", "unfinished", "network"})
FIXED = "fixed"  # the page's own fixed reply (web/js/fixed.js): no model, nothing to time
FEEDBACK = "feedback"  # a visitor's feedback on an answer, not a turn


def read(paths: Iterable[Path]) -> Iterator[dict[str, Any]]:
    """The records in *paths*: JSON-lines files (``YYYY/MM/DD.jsonl``, as relay/collect.py writes them), or directories
    of them; a line that is not a record is passed over.  A file is read by its line feeds alone: U+2028, U+2029 and
    U+0085, which a question or an answer may hold, end a line for ``str.splitlines`` and are part of one here."""
    for path in paths:
        files = sorted(path.rglob("*.jsonl")) if path.is_dir() else [path]
        for f in files:
            for line in f.read_text(encoding="utf-8").split("\n"):
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if isinstance(r, dict) and r.get("v") == 1:
                    yield r


def _n(v: Any) -> float | None:
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def _seconds(values: list[float]) -> dict[str, Any] | None:
    """How many, the median, the 90th and 99th percentiles (nearest rank) and the longest — in seconds."""
    if not values:
        return None
    v = sorted(values)
    at = lambda q: v[min(len(v) - 1, max(0, math.ceil(q * len(v)) - 1))]  # noqa: E731
    return {"n": len(v), "p50": round(at(0.5) / 1000, 1), "p90": round(at(0.9) / 1000, 1), "p99": round(at(0.99) / 1000, 1),
            "max": round(v[-1] / 1000, 1)}


def _share(part: int, whole: int) -> dict[str, Any]:
    return {"n": part, "of": whole, "share": round(part / whole, 3) if whole else None}


def answer_after_tools(r: dict[str, Any]) -> dict[str, float] | None:
    """In a timed record, the time from its last tool result to the first answer text the visitor saw (``total``: of a
    request that then broke off, too), and of it: the model requests before that one — asked again after a failure, or
    with less thinking (``before``) —, its wait for its reply to begin (``reply``), and its time from then to that text
    (``thinking``).  None when no call ended, or no answer text came after the last one."""
    ends = [t["at"] + t["ms"] for t in r.get("tools") or [] if _n(t.get("at")) is not None and _n(t.get("ms")) is not None]
    if not ends:
        return None
    last = max(ends)
    after = [q for q in r.get("requests") or [] if _n(q.get("sent")) is not None and q["sent"] >= last]
    answering = next((q for q in after if _n(q.get("text")) is not None), None)
    if answering is None:
        return None
    began = answering["open"] if _n(answering.get("open")) is not None else answering["text"]
    return {"total": answering["text"] - last, "before": answering["sent"] - last, "reply": began - answering["sent"],
            "thinking": answering["text"] - began}


def whole(r: dict[str, Any]) -> bool:
    """The answer came whole: the turn is done, with an answer and no notice under it (a cut, a limit, the content
    filter, the user's 不再等待) — and, where the record times its requests, the last of them to finish said it was done:
    of those before the self-check's note, when the rewrite it asked for was taken out and the answer before it stands."""
    if r.get("status") != "done" or r.get("error") or not str(r.get("answer") or "").strip():
        return False
    requests = [q for q in r.get("requests") or [] if isinstance(q, dict)]
    events = [e for e in r.get("events") or [] if isinstance(e, dict)]
    noted = next((e.get("at") for e in events if e.get("what") == "review"), None)
    if _n(noted) is not None and any(e.get("what") == "unchecked" for e in events):
        requests = [q for q in requests if _n(q.get("sent")) is not None and q["sent"] < noted]
    finished = [q for q in requests if q.get("finish")]  # a request that failed after the answer (a rewrite) is not it
    return not requests or bool(finished) and finished[-1]["finish"] in FINISHED


def _failed(q: dict[str, Any]) -> str | None:
    """How a model request failed, for the counts ("timeout:silence", "overloaded_error 529", "http 503" …); None when it
    did not, or the turn was stopped."""
    why = q.get("failed")
    if not isinstance(why, str) or not why or why == "stopped":
        return None
    if why == "timeout" and isinstance(q.get("expired"), str):
        return f"timeout:{q['expired']}"
    status = _n(q.get("status"))
    return f"{why} {int(status)}" if status and not why.startswith("http ") else why


def _broke_off(q: dict[str, Any]) -> bool:
    """The request broke off (:data:`BROKE_OFF`), or the service failed — not a refusal: a key, a rate, the day's turns."""
    return q.get("failed") in BROKE_OFF or (_n(q.get("status")) or 0) >= 500


def _unseen(q: dict[str, Any]) -> bool | None:
    """Was the page hidden, or not running at all, for some of the time a model request was asked?  None for a request a
    page did not time so (an earlier page's): a reply that broke off while no one could see the page may have been cut by
    the browser (a tab in the background, a phone asleep), not by the service."""
    hidden, asleep = _n(q.get("hidden")), _n(q.get("asleep"))
    if hidden is None and asleep is None:
        return None
    return (hidden or 0) > 0 or (asleep or 0) > 0


def _rounds_span(tools: list[dict[str, Any]]) -> float:
    """The time a turn's rounds of calls took, each round from its first call's start to its last call's end."""
    by_round: dict[Any, list[tuple[float, float]]] = {}
    for t in tools:
        if _n(t.get("at")) is not None and _n(t.get("ms")) is not None:
            by_round.setdefault(t.get("round"), []).append((t["at"], t["at"] + t["ms"]))
    return sum(max(e for _, e in spans) - min(s for s, _ in spans) for spans in by_round.values())


def _key(r: dict[str, Any], k: int) -> Any:
    """A turn's key: its message id in its conversation (the turn's records and the feedback on it share it)."""
    return (r.get("conversation"), r["id"]) if isinstance(r.get("id"), str) and r["id"] else k


def ratings(feedback: Iterable[dict[str, Any]], since: str | None = None, until: str | None = None) -> dict[str, Any]:
    """The feedback on answers given from *since* to *until* (``YYYY-MM-DD``, both included), each turn's last word
    standing — a rating given again replaces the one before it, one taken back (``rating`` null) leaves the turn
    unrated: how many turns are rated, 👍 and 👎 and the share of 👍, the reasons ticked under each, and how many of the
    ratings came with written words, with the turn's question and answer attached, or on a turn whose record is here
    (``recorded``).  Counts only, never a word of what anyone wrote."""
    last: dict[Any, dict[str, Any]] = {}
    for k, r in enumerate(feedback):
        day = str(r.get("given") or r.get("received") or "")[:10]
        if (since and day < since) or (until and day > until):
            continue
        last[_key(r, k)] = r
    standing = [r for r in last.values() if r.get("rating") in ("up", "down")]
    up = sum(r["rating"] == "up" for r in standing)
    reasons: dict[str, Counter[str]] = {"up": Counter(), "down": Counter()}
    for r in standing:
        reasons[r["rating"]].update(x for x in r.get("reasons") or [] if isinstance(x, str))
    return {
        "rated": len(standing), "up": up, "down": len(standing) - up,
        "share_up": round(up / len(standing), 3) if standing else None,
        "taken_back": len(last) - len(standing),
        "reasons": {k: dict(v.most_common()) for k, v in reasons.items()},
        "commented": sum(bool(str(r.get("comment") or "").strip()) for r in standing),
        "attached": sum(bool(r.get("question") or r.get("answer")) for r in standing),
        "recorded": sum(r.get("recorded") is True for r in standing),
    }


def _turns(records: Iterable[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """The records by turn, in the order the turns were first recorded: a turn taken up again has one record for each
    time it ran (the same message id in the same conversation)."""
    turns: dict[Any, list[dict[str, Any]]] = {}
    for k, r in enumerate(records):
        turns.setdefault(_key(r, k), []).append(r)
    return list(turns.values())


def summary(records: Iterable[dict[str, Any]], since: str | None = None, until: str | None = None) -> dict[str, Any]:
    """The records' numbers (turns begun from *since* to *until*, ``YYYY-MM-DD``, both included):

    * ``answer_after_tools`` — the time from a turn's last tool result to the first text of its answer, and its parts
      (:func:`answer_after_tools`), in seconds;
    * ``recovery`` — of the turns in which a model request broke off (it stalled, never answered, ended before the model
      was done, or the connection or the service failed), those that still ended with a whole answer; how the requests
      failed, by kind; and of the requests that broke off, timed by the page's own clock, those asked while the page was
      hidden or not running for some of the time (``unseen``);
    * ``completion`` — of the turns a model answered: the answer came whole (:func:`whole`); whole, with no citation the
      corpus lacks (✕) or left unchecked; whole and verified (it cites, and every citation is ✓); whole, citing nothing;
    * ``time`` — per timed turn: in model requests, in rounds of calls, the page hidden, the page asleep (seconds);
      and of the calls' own time, how much went on waiting for their runtime or their turn;
    * ``asked_again`` — how often the model was asked again: of the model requests, those the page asked again (a
      round's second request and later: after a failure, a stall, a cut connection); of the requests whose service said
      how many times it asked the model service itself (``asks``: the default service, ADR 0033), those it asked once;
      and the place the reply came from (``via``), for the replies that came;
    * ``resumed`` — the turns taken up again (继续作答), and how many of them then answered whole;
    * ``feedback`` — the visitors' ratings of answers (:func:`ratings`), given from *since* to *until*.
    """
    records = list(records)
    feedback = [r for r in records if r.get("kind") == FEEDBACK]
    turns = timed = fixed = 0
    after: dict[str, list[float]] = {"total": [], "before": [], "reply": [], "thinking": []}
    broke = recovered = 0
    kinds: Counter[str] = Counter()
    clocked = unseen = 0  # the requests that broke off with the page's own times; of them, while it was not seen
    done = unflagged = verified = uncited = 0
    spent: dict[str, list[float]] = {"model": [], "tools": [], "hidden": [], "asleep": []}
    waited = ran = 0.0
    resumed = resumed_whole = 0
    asked = again = 0  # model requests, and those the page asked again
    told = once = 0  # the requests whose service said how many times it asked the model service; those it asked once
    via: Counter[str] = Counter()  # the place a reply came from
    for runs in _turns(r for r in records if r.get("kind") != FEEDBACK):
        r = runs[-1]  # as the turn ended
        day = str(runs[0].get("started") or runs[0].get("received") or "")[:10]
        if (since and day < since) or (until and day > until):
            continue
        if r.get("provider") == FIXED:
            fixed += 1
            continue
        turns += 1
        ok = whole(r)
        c = r.get("citations") if isinstance(r.get("citations"), dict) else {}
        done += ok
        unflagged += ok and not c.get("bad") and not c.get("pending")
        verified += ok and bool(c.get("total")) and c.get("ok") == c.get("total")
        uncited += ok and not c.get("total")
        if len(runs) > 1 or _n(r.get("resumed")):
            resumed += 1
            resumed_whole += ok
        timed_runs = [x for x in runs if any(isinstance(q, dict) for q in x.get("requests") or [])]
        if not timed_runs:
            continue
        timed += 1
        parts = next((p for p in map(answer_after_tools, timed_runs) if p), None)
        for k, v in (parts or {}).items():
            after[k].append(v)
        requests = [q for x in timed_runs for q in x.get("requests") or [] if isinstance(q, dict)]
        failures = [q for q in requests if _failed(q)]
        kinds.update(map(_failed, failures))
        asked += len(requests)
        again += sum((_n(q.get("attempt")) or 1) > 1 for q in requests)
        for q in requests:
            if (_n(q.get("asks")) or 0) >= 1:
                told += 1
                once += q["asks"] == 1
                if q.get("finish") and isinstance(q.get("via"), str):
                    via[q["via"]] += 1
        if any(map(_broke_off, failures)):
            broke += 1
            recovered += ok
        seen = [_unseen(q) for q in failures if _broke_off(q)]
        clocked += sum(v is not None for v in seen)
        unseen += sum(v is True for v in seen)
        spent["model"].append(sum(q["end"] - q["sent"] for q in requests if _n(q.get("end")) is not None and _n(q.get("sent")) is not None))
        spent["tools"].append(sum(_rounds_span([t for t in x.get("tools") or [] if isinstance(t, dict)]) for x in timed_runs))
        for k in ("hidden", "asleep"):
            got = [x[k] for x in timed_runs if _n(x.get(k)) is not None]
            if got:
                spent[k].append(sum(got))
        for t in (t for x in timed_runs for t in x.get("tools") or [] if isinstance(t, dict)):
            if _n(t.get("ms")) is not None:
                w = min(_n(t.get("wait")) or 0, t["ms"])
                waited += w
                ran += t["ms"] - w
    return {
        "turns": turns, "timed": timed, "fixed": fixed,
        "answer_after_tools": {k: _seconds(v) for k, v in after.items()},
        "recovery": {**_share(recovered, broke), "failed": dict(kinds.most_common()), "unseen": _share(unseen, clocked)},
        "completion": {"whole": _share(done, turns), "whole_unflagged": _share(unflagged, turns),
                       "whole_verified": _share(verified, turns), "whole_uncited": _share(uncited, turns)},
        "time": {**{k: _seconds(v) for k, v in spent.items()},
                 "calls_waiting": round(waited / (waited + ran), 3) if waited + ran else None},
        "asked_again": {"by_page": _share(again, asked), "service_asked_once": _share(once, told), "via": dict(via.most_common())},
        "resumed": {"n": resumed, "whole": resumed_whole},
        "feedback": ratings(feedback, since, until),
    }
