"""The repository's side of the activity ledger (security/ledger.js; standard library only; run by
.github/workflows/activity.yml): the ledger's counts, as sums nobody can be picked out of, kept here for good.

  report    the days not yet kept (every day after the last one, through yesterday — a run that did not happen is caught
            up, no further back than CATCH_UP_DAYS), each asked of the site (GET /api/activity/stats) and written to
            data/activity-analytics/daily/YYYY/MM/DD.json; then the week, the month and the year those days fall in,
            each asked for as a whole — a month's visitors are the different visitors of the month, which no sum of its
            days gives — and lifetime.json, since the ledger's first day
  validate  the pipeline: what waits in each Worker's outbox and for how long, what was dropped or lost or failed to
            be written since the last look, yesterday's archive against its manifest, the day's counts against
            themselves, and the count of visitors there ever were against the last one kept (it never falls).  What is
            wrong is said (::error::) and ends the run in failure, after everything else was done
  backfill  the days before the ledger, from what was kept of them: the two Workers' daily counts (pages opened,
            questions and calls of the default service, a visitor counted anew each day) and the conversation records
            committed under data/chat-logs/ (the questions of visitors who agreed, in counts).  What was not kept then
            cannot be made now: those days say how many visitor-days there were, and between which two numbers the
            visitors lie

What is written here is sums: no visitor's id, no event, no address.  A place with fewer visitors than --min-cell
(default 3) is folded into "other", and so is a site few came from: the reports are read by whoever reads the
repository.  The rows the sums are of stay in the registry (D1) and the archive (R2).

Environment: LOG_EXPORT_TOKEN, the collector's token — it reads the ledger's counts and its pipeline; STATS_TOKEN (for
backfill: the Workers' daily counts open to no other).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

UA = "taochronos-collector/1"
CATCH_UP_DAYS = 31
OFFSET_HOURS = 8  # the readers' day: UTC+8, as the Workers count it (STATS_UTC_OFFSET)
STALE_SECONDS = 3 * 3600  # an event older than this still in an outbox: nothing is draining it
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _request(url: str, *, token: str | None = None, timeout: float = 90) -> tuple[int, dict | str]:
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — the Workers' https addresses
            raw, status = r.read().decode("utf-8"), r.status
    except urllib.error.HTTPError as err:
        raw, status = err.read().decode("utf-8", "replace"), err.code
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, raw


def _token(name: str = "LOG_EXPORT_TOKEN", needed: bool = True) -> str:
    token = "".join(os.environ.get(name, "").split())  # a space or line break pasted with it is not part of it
    if len(token) < 16:
        if needed:
            raise SystemExit(f"{name} is not set (at least 16 characters)")
        return ""
    return token


def _output(**values: object) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            for k, v in values.items():
                f.write(f"{k}={v}\n")
    print(json.dumps(values, ensure_ascii=False))


def _write(path: Path, data: dict) -> bool:
    """The file written when what it says changed; whether it did."""
    text = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------- the periods
def day_of(d: str) -> date:
    return datetime.strptime(d, "%Y-%m-%d").date()


def periods(d: date) -> dict[str, tuple[str, date, date]]:
    """The week (Monday to Sunday, by its ISO number), the month and the year a day falls in: kind → (label, first, last)."""
    monday = d - timedelta(days=d.weekday())
    year, week, _ = d.isocalendar()
    next_month = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return {
        "weekly": (f"{year}-W{week:02d}", monday, monday + timedelta(days=6)),
        "monthly": (d.strftime("%Y-%m"), d.replace(day=1), next_month - timedelta(days=1)),
        "yearly": (d.strftime("%Y"), d.replace(month=1, day=1), d.replace(month=12, day=31)),
    }


def daily_path(out: Path, d: date) -> Path:
    return out / "daily" / d.strftime("%Y") / d.strftime("%m") / f"{d.strftime('%d')}.json"


def kept_days(out: Path, basis: str | None = None) -> list[date]:
    days = []
    for f in sorted((out / "daily").glob("*/*/*.json")):
        try:
            d = date(int(f.parts[-3]), int(f.parts[-2]), int(f.stem))
        except ValueError:
            continue
        if basis is None or ((_read(f) or {}).get(basis) is not None):
            days.append(d)
    return days


# ---------------------------------------------------------------- what a report keeps of the ledger's counts
def fold(rows: list, least: int, value=lambda r: r[-1], other=lambda n, total: ["", total]) -> list:
    """The rows whose count reaches `least`; the others as one."""
    kept = [r for r in rows if value(r) >= least]
    small = [r for r in rows if value(r) < least]
    return kept + ([other(len(small), sum(value(r) for r in small))] if small else [])


def anonymous(stats: dict, least: int, series: bool) -> dict:
    """The ledger's counts as a report keeps them: the sums, a place or a referring site only where enough visitors
    make it one of many, the days' series for a week or longer."""
    places = [p for p in stats.get("places", []) if not p.get("folded") and p.get("visitors", 0) >= least]
    small = [p for p in stats.get("places", []) if p.get("folded") or p.get("visitors", 0) < least]
    if small:
        places.append({"country": "", "region": "", "folded": sum(int(p.get("folded") or 1) for p in small),
                       **{k: sum(int(p.get(k) or 0) for p in small) for k in ("visitors", "page_views", "questions")}})
    audience = dict(stats.get("audience") or {})
    audience["referrers"] = fold(audience.get("referrers") or [], least)
    out = {k: stats.get(k) for k in ("totals", "lifetime", "questions", "models", "retention", "features", "sessions", "security", "coverage")}
    out.update({"from": stats.get("from"), "to": stats.get("to"), "first_day": stats.get("first_day"), "places": places, "audience": audience})
    if series:
        out["days"], out["daily"] = stats.get("days"), stats.get("daily")
    return out


def ask(site: str, token: str, first: date | None, last: date) -> dict:
    q = f"to={last.isoformat()}" + (f"&from={first.isoformat()}" if first else "&range=all")
    status, body = _request(f"{site}/api/activity/stats?{q}", token=token)
    if status == 404:
        raise LookupError("the site has no activity ledger (ACTIVITY_KEY and the registry are not set up: security/README.md)")
    if status != 200 or not isinstance(body, dict) or "totals" not in body:
        raise SystemExit(f"the site refused the ledger's counts: HTTP {status} {str(body)[:300]}")
    return body


def report(site: str, out: Path, *, least: int = 3, day: str | None = None, today: date | None = None) -> dict:
    token = _token()
    try:
        probe = ask(site, token, None, today or date.max)  # as the site knows today, and since when it has a ledger
    except LookupError as err:
        print(f"::notice::{err}")
        return {"new": 0, "ledger": 0}
    yesterday = day_of(probe["asOf"]) - timedelta(days=1)
    first = day_of(probe["first_day"]) if probe.get("first_day") else None
    if first is None or first > yesterday:
        print("::notice::the ledger has no finished day yet: nothing to report")
        return {"new": 0, "ledger": 1}
    if day:
        days = [day_of(day)]
    else:
        kept = kept_days(out, "ledger")
        start = max(max(kept) + timedelta(days=1) if kept else first, first, yesterday - timedelta(days=CATCH_UP_DAYS - 1))
        days = [start + timedelta(days=i) for i in range((yesterday - start).days + 1)]
    changed = 0
    touched: dict[tuple[str, str], tuple[date, date]] = {}
    for d in days:
        stats = ask(site, token, d, d)
        path = daily_path(out, d)
        data = {**(_read(path) or {}), "v": 1, "kind": "daily", "period": {"label": d.isoformat(), "from": d.isoformat(), "to": d.isoformat()},
                "complete": True, "min_cell": least, "ledger": anonymous(stats, least, series=False)}
        data.setdefault("backfill", None)
        changed += _write(path, data)
        for kind, (label, a, b) in periods(d).items():
            touched[(kind, label)] = (a, b)
    # the week, the month and the year of those days, each as a whole (to yesterday, while it is not over)
    for (kind, label), (a, b) in sorted(touched.items()):
        changed += period_file(site, token, out, kind, label, a, b, first, yesterday, least)
    if days:
        stats = ask(site, token, None, yesterday)
        path = out / "lifetime.json"
        data = {**(_read(path) or {}), "v": 1, "kind": "lifetime", "period": {"label": "lifetime", "from": stats.get("from"), "to": yesterday.isoformat()},
                "min_cell": least, "ledger": anonymous(stats, least, series=False)}
        data.setdefault("backfill", None)
        changed += _write(path, data)
    return {"new": changed, "ledger": 1, "days": len(days), "through": yesterday.isoformat()}


def period_file(site: str, token: str, out: Path, kind: str, label: str, a: date, b: date, first: date, yesterday: date, least: int) -> int:
    """A week's, a month's or a year's file: the ledger's counts over its days (asked for as a whole), beside what was
    kept of its days before the ledger."""
    path = out / kind / f"{label}.json"
    data = {**(_read(path) or {}), "v": 1, "kind": kind, "period": {"label": label, "from": a.isoformat(), "to": b.isoformat()}, "complete": b <= yesterday, "min_cell": least}
    lo, hi = max(a, first), min(b, yesterday)
    data["ledger"] = anonymous(ask(site, token, lo, hi), least, series=True) if lo <= hi else None
    data["backfill"] = summed(out, a, b)
    return int(_write(path, data))


# ---------------------------------------------------------------- the days before the ledger
def summed(out: Path, a: date, b: date) -> dict | None:
    """What was kept of the days a…b before the ledger, added up — and the visitors as the two numbers they lie
    between: a day's visitors at least, every day's added up at most (a visitor was counted anew each day)."""
    days = [x for x in (_read(daily_path(out, a + timedelta(days=i))) for i in range((b - a).days + 1)) if x and x.get("backfill")]
    if not days:
        return None
    total: dict = {"days": len(days)}
    for x in days:
        for part in ("usage", "records", "edge"):
            for k, v in (x["backfill"].get(part) or {}).items():
                slot = total.setdefault(part, {})
                if isinstance(v, dict):
                    inner = slot.setdefault(k, {})
                    for name, n in v.items():
                        inner[name] = inner.get(name, 0) + n
                elif isinstance(v, (int, float)):
                    slot[k] = slot.get(k, 0) + v
    visitors = [int((x["backfill"].get("usage") or {}).get("visitor_days") or 0) for x in days]
    if any(visitors):
        total["visitors"] = {"at_least": max(visitors), "at_most": sum(visitors)}
    return total


def reader_day(stamp: str) -> str | None:
    """The readers' day a moment (ISO, UTC) falls on."""
    try:
        t = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (t.astimezone(timezone.utc) + timedelta(hours=OFFSET_HOURS)).strftime("%Y-%m-%d")


def provider_of(p: object) -> str:
    """A provider as a report names it: the default service, the page's own reply, a preset's id — "custom" for an
    endpoint a visitor set by hand."""
    if not isinstance(p, str) or not p:
        return "unknown"
    return "custom" if p.startswith("custom") else p if re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", p) else "other"


def from_records(logs: Path) -> dict[str, dict]:
    """The conversation records committed under data/chat-logs/, by the readers' day they were received on, in
    counts: the questions (a turn once, however often it was taken up again), by whom they were answered, what they took
    — never a word of them.  Only visitors who agreed are in the records: these are the recorded questions, not all."""
    turns: dict[str, dict] = {}  # id → the last record of the turn
    feedback: dict[str, dict] = {}
    for f in sorted(logs.glob("*/*/*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            day = reader_day(str(r.get("received") or ""))
            if not day or not r.get("id"):
                continue
            if r.get("kind") == "feedback":
                feedback[f"{r['id']}|{r.get('conversation')}"] = {"day": day, "rating": r.get("rating")}
            else:
                first = turns.get(f"{r['id']}|{r.get('conversation')}", {}).get("day", day)  # counted on the day it was first recorded
                turns[f"{r['id']}|{r.get('conversation')}"] = {"day": first, "r": r}
    out: dict[str, dict] = {}

    def bump(day: str, key: str, name: str | None = None, n: int = 1) -> None:
        slot = out.setdefault(day, {})
        if name is None:
            slot[key] = slot.get(key, 0) + n
        else:
            inner = slot.setdefault(key, {})
            inner[name] = inner.get(name, 0) + n

    for t in turns.values():
        day, r = t["day"], t["r"]
        provider = provider_of(r.get("provider"))
        bump(day, "questions")
        bump(day, "by_provider", provider)
        if provider == "impf" and isinstance(r.get("model"), str) and r["model"]:
            bump(day, "by_model", r["model"])  # a visitor's own model is their setting: not named
        bump(day, "by_status", str(r.get("status") or "unknown")[:20])
        bump(day, "model_calls", n=int(r.get("rounds") or 0))
        usage = r.get("usage") or {}
        bump(day, "tokens_in", n=int(usage.get("input") or 0))
        bump(day, "tokens_out", n=int(usage.get("output") or 0))
        tools = r.get("tools") or []
        bump(day, "tool_calls", n=len(tools))
        for tool in tools:
            name = str((tool or {}).get("name") or "").replace("__", ".")
            if re.fullmatch(r"[a-z][a-z0-9_.]{1,60}", name):
                bump(day, "tools", name)
    for fb in feedback.values():
        bump(fb["day"], "feedback", str(fb["rating"] or "withdrawn"))
    return out


def from_usage(site: str, relay: str, token: str) -> dict[str, dict]:
    """The two Workers' daily counts (security/usage.js), a year of them: pages opened and visitor-days (the site),
    questions, model calls and asker-days of the default service (the relay)."""
    out: dict[str, dict] = {}
    names = {"view": "page_views", "visitor": "visitor_days", "question": "questions_default_service", "call": "model_calls_default_service", "asker": "asker_days"}
    for base, path, kinds in ((site, "/api/stats", ("view", "visitor")), (relay, "/v1/stats", ("question", "call", "asker"))):
        if not base:
            continue
        status, body = _request(f"{base}{path}?days=366", token=token)
        if status != 200 or not isinstance(body, dict) or not isinstance(body.get("days"), list):
            print(f"::notice::{base}{path} gave no daily counts (HTTP {status}): the days before the ledger are told without them")
            continue
        for i, day in enumerate(body["days"]):
            for kind in kinds:
                n = int((body.get("daily", {}).get(kind) or [0] * (i + 1))[i] or 0)
                if n:
                    out.setdefault(day, {})[names[kind]] = n
    return out


def from_edge(edge: Path) -> dict[str, dict]:
    """The edge's own count of a day's requests (security/events.py, kind: traffic), by the day (UTC) it kept them under:
    every request to the two hosts, what a Worker saw of them or not."""
    out: dict[str, dict] = {}
    for f in sorted(edge.glob("*/*/*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("kind") != "traffic":
                continue
            slot = out.setdefault(str(e.get("day")), {})
            slot["requests"] = slot.get("requests", 0) + int(e.get("requests") or 0)
            slot["visits"] = slot.get("visits", 0) + int(e.get("visits") or 0)
            cls = f"{int(e.get('status') or 0) // 100}xx"
            by = slot.setdefault("by_status", {})
            by[cls] = by.get(cls, 0) + int(e.get("requests") or 0)
    return out


def backfill(site: str, relay: str, out: Path, logs: Path, edge: Path, *, before: str | None = None) -> dict:
    """The days before the ledger's first (or before `before`), from every source that kept something of them."""
    stats = _token("STATS_TOKEN", needed=False)
    usage = from_usage(site, relay, stats) if stats else {}
    if not stats:
        print("::notice::STATS_TOKEN is not set: the days before the ledger are told from the records alone")
    records = from_records(logs) if logs.is_dir() else {}
    traffic = from_edge(edge) if edge.is_dir() else {}
    ledger = kept_days(out, "ledger")
    # before the ledger's first reported day, and never today: a day is told once it is over
    today = (datetime.now(timezone.utc) + timedelta(hours=OFFSET_HOURS)).strftime("%Y-%m-%d")
    limit = min(before or (min(ledger).isoformat() if ledger else today), today)
    changed = 0
    touched: dict[tuple[str, str], tuple[date, date]] = {}
    days = sorted(d for d in {*usage, *records, *traffic} if DAY.match(d) and d < limit)
    for d in days:
        path = daily_path(out, day_of(d))
        data = {"v": 1, "kind": "daily", "period": {"label": d, "from": d, "to": d}, "complete": True, "ledger": None, **(_read(path) or {})}
        data["backfill"] = {k: v for k, v in (("usage", usage.get(d)), ("records", records.get(d)), ("edge", traffic.get(d))) if v}
        changed += _write(path, data)
        for kind, (label, a, b) in periods(day_of(d)).items():
            touched[(kind, label)] = (a, b)
    for (kind, label), (a, b) in sorted(touched.items()):
        path = out / kind / f"{label}.json"
        data = {"v": 1, "kind": kind, "period": {"label": label, "from": a.isoformat(), "to": b.isoformat()}, "ledger": None, **(_read(path) or {})}
        data["backfill"] = summed(out, a, b)
        data.setdefault("complete", b.isoformat() < today)
        changed += _write(path, data)
    if days:
        path = out / "lifetime.json"
        data = {"v": 1, "kind": "lifetime", "period": {"label": "lifetime", "from": days[0], "to": days[-1]}, "ledger": None, **(_read(path) or {})}
        data["backfill"] = summed(out, day_of(days[0]), day_of(days[-1]))
        changed += _write(path, data)
    return {"new": changed, "days": len(days), "first": days[0] if days else None, "last": days[-1] if days else None,
            "sources": sorted(k for k, v in (("usage", usage), ("records", records), ("edge", traffic)) if v)}


# ---------------------------------------------------------------- the pipeline
COUNTERS = ("dropped", "lost", "duplicates", "d1_failures", "r2_failures")


def validate(site: str, relay: str, out: Path, *, now: datetime | None = None) -> dict:
    """→ {"errors": [...], "warnings": [...], "pipeline": {...}}; the pipeline's counts are kept (pipeline.json), so that
    the next look says what happened since."""
    token = _token()
    now = now or datetime.now(timezone.utc)
    errors: list[str] = []
    warnings: list[str] = []
    seen: dict[str, dict] = {}
    for name, url in (("site", f"{site}/api/activity/health"), ("relay", f"{relay}/v1/activity/health" if relay else "")):
        if not url:
            continue
        status, body = _request(url, token=token)
        if status == 404:
            print(f"::notice::the {name} has no activity ledger: nothing to check there")
            continue
        if status != 200 or not isinstance(body, dict) or not isinstance(body.get(name), dict):
            errors.append(f"the {name} does not say how its ledger stands: HTTP {status} {str(body)[:200]}")
            continue
        seen[name] = body[name]
        if name == "site":
            seen["registry"] = body.get("registry") or {}
            seen["archive"] = bool(body.get("archive"))
    before = (_read(out / "pipeline.json") or {}).get("sources", {})
    for name in ("site", "relay"):
        h = seen.get(name)
        if not h:
            continue
        if int(h.get("oldest_seconds") or 0) > STALE_SECONDS:
            errors.append(f"the {name}'s outbox is not being drained: {h.get('waiting')} events wait, the oldest for {int(h['oldest_seconds']) // 3600} hours")
        for k in COUNTERS:
            grew = int(h.get(k) or 0) - int((before.get(name) or {}).get(k) or 0)
            if grew > 0 and k in ("dropped", "lost"):
                errors.append(f"the {name}'s ledger {k} {grew} events since the last look: the counts lack them")
            elif grew > 0 and k != "duplicates":
                warnings.append(f"the {name}'s ledger had {grew} more {k} since the last look (written again later; nothing is lost while its outbox drains)")
    # yesterday's archive against its manifest (UTC days: an object is kept under the hour the ledger received it in)
    if seen.get("archive"):
        day = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        status, body = _request(f"{site}/api/activity/archive?day={day}", token=token)
        if status == 200 and isinstance(body, dict):
            for source, v in (body.get("sources") or {}).items():
                if v.get("ok") is False:
                    errors.append(f"the archive of {source} for {day} does not match its manifest: {len(v.get('missing') or [])} missing, "
                                  f"{len(v.get('mismatched') or [])} changed, {len(v.get('unlisted') or [])} unlisted")
            seen["archive_checked"] = {"day": day, **{s: v.get("ok") for s, v in (body.get("sources") or {}).items()}}
        else:
            warnings.append(f"the archive of {day} could not be checked: HTTP {status}")
    # the counts against themselves, and against the last ones kept
    life = _read(out / "lifetime.json") or {}
    days = kept_days(out, "ledger")
    if days:
        last = (_read(daily_path(out, max(days))) or {}).get("ledger") or {}
        t = last.get("totals") or {}
        if t and t.get("questions") != (t.get("questions_archived") or 0) + (t.get("questions_unarchived") or 0):
            errors.append(f"{max(days)}: the questions are not the recorded and the unrecorded together")
        if int((last.get("coverage") or {}).get("pending_days") or 0) > 0:
            warnings.append(f"{max(days)}: some days' sums were still to be made when it was read")
    known = int((before.get("lifetime") or {}).get("visitors") or 0)
    visitors = int(((life.get("ledger") or {}).get("lifetime") or {}).get("visitors") or 0)
    if visitors < known:
        errors.append(f"the count of visitors there ever were fell from {known} to {visitors}: it never should")
    _write(out / "pipeline.json", {"v": 1, "sources": {**{k: {c: int(v.get(c) or 0) for c in COUNTERS} | {"waiting": int(v.get("waiting") or 0)} for k, v in seen.items()
                                                         if k in ("site", "relay")}, "lifetime": {"visitors": max(visitors, known)}},
                                   "registry": seen.get("registry"), "archive": seen.get("archive_checked")})
    for w in warnings:
        print(f"::warning::{w}")
    for e in errors:
        print(f"::error::{e}")
    return {"errors": errors, "warnings": warnings, "pipeline": seen}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["report", "validate", "backfill"])
    ap.add_argument("--site", default=os.environ.get("SITE_URL") or "https://chat.impf.ai")
    ap.add_argument("--relay", default=os.environ.get("RELAY_URL") or "https://chat-api.impf.ai", help="the relay's address ('' to skip it)")
    ap.add_argument("--out", default="data/activity-analytics")
    ap.add_argument("--day", help="report: one day (YYYY-MM-DD) instead of every day not yet kept")
    ap.add_argument("--min-cell", type=int, default=3, help="report: a place or a referring site with fewer visitors than this is folded into the rest")
    ap.add_argument("--logs", default="data/chat-logs", help="backfill: the conversation records")
    ap.add_argument("--edge", default="data/security-logs/edge", help="backfill: the edge's records")
    ap.add_argument("--before", help="backfill: only the days before this one (default: the ledger's first reported day)")
    args = ap.parse_args(argv)
    site, relay, out = args.site.rstrip("/"), args.relay.rstrip("/"), Path(args.out)
    if args.day and not DAY.match(args.day):
        raise SystemExit("--day YYYY-MM-DD")
    if args.action == "report":
        _output(**report(site, out, least=max(1, args.min_cell), day=args.day))
    elif args.action == "backfill":
        _output(**backfill(site, relay, out, Path(args.logs), Path(args.edge), before=args.before))
    else:
        result = validate(site, relay, out)
        _output(errors=len(result["errors"]), warnings=len(result["warnings"]))
        if result["errors"]:
            raise SystemExit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
