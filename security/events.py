"""The edge's own record of impf.ai, kept beyond the plan's retention (security/README.md; standard library only).

  pull     Cloudflare's security events (what the WAF, the rate limit and the bot checks did) and the requests worth a
           look (an error, a security action, a path a scanner asks for, an agent that is not a browser, a volume no reader
           has) from the GraphQL Analytics API, for a day (UTC; by default every day after the last one kept, through
           yesterday — runs that did not happen are caught up — no further back than CATCH_UP_DAYS), appended to
           data/security-logs/edge/YYYY/MM/DD.jsonl (events once each, by their ray id) — and the suspects: per address,
           over the days kept, what it did (data/security-logs/edge/suspects.json)
  suspects the suspects, printed

Environment: CLOUDFLARE_ANALYTICS_TOKEN — a read-only token with Zone → Analytics: Read on impf.ai (never the deploy
token); CLOUDFLARE_ZONE_ID.  The first query asks the zone what its plan exposes of each node (the fields, how far back,
how wide a window, how many fields a query may name) and the pulls keep within it; what was out of reach is said.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

API = "https://api.cloudflare.com/client/v4/graphql"
UA = "taochronos-security/1"
HOSTS = ["chat.impf.ai", "chat-api.impf.ai"]
SUSPECT_DAYS = 30
CATCH_UP_DAYS = 31  # the most days a pull without --day goes back for: about what the plan keeps (pull() says what is out of reach)

# what is asked of each node when the zone exposes it (the first query says what it does)
FIREWALL_FIELDS = ["datetime", "action", "source", "kind", "ruleId", "description", "matchIndex", "rayName", "clientIP", "clientIPClass", "clientAsn",
                   "clientASNDescription", "clientCountryName", "userAgent", "clientRequestHTTPHost", "clientRequestHTTPMethodName",
                   "clientRequestHTTPProtocol", "clientRequestPath", "clientRequestQuery", "clientRefererHost", "edgeResponseStatus",
                   "originResponseStatus", "sampleInterval"]
REQUEST_DIMENSIONS = ["clientIP", "userAgent", "clientRequestPath", "clientRequestHTTPHost", "clientRequestHTTPMethodName", "edgeResponseStatus",
                      "clientAsn", "clientASNDescription", "clientCountryName", "clientRequestHTTPProtocol", "securityAction", "securitySource"]

SCANNER_PATH = re.compile(r"wp-|wordpress|/\.git|/\.env|/\.aws|/\.svn|phpmyadmin|xmlrpc|/cgi-bin/|/actuator|/boaform|/hnap1|eval-stdin|phpinfo|"
                          r"/server-status|\.(?:php|phtml|asp|aspx|jsp|cgi|bak|sql|old|swp|rar|7z)$|/\.\./|%2e%2e|%00", re.I)
BROWSER = re.compile(r"^Mozilla/5\.0 .*(?:Chrome/|CriOS/|Firefox/|FxiOS/|Safari/|Edg|OPR/|MicroMessenger|QQBrowser|UCBrowser|baiduboxapp|Mobile)", re.I)
TOOL = re.compile(r"^curl/|^wget/|python|aiohttp|go-http-client|^java/|okhttp|apache-httpclient|node-fetch|undici|axios|libwww|scrapy|masscan|zgrab|zmap|"
                  r"nmap|nikto|sqlmap|nuclei|gobuster|ffuf|wpscan|censys|expanse|paloaltonetworks|internetmeasurement|^mozilla/[45]\.0$", re.I)
OWN = ("taochronos-",)


def query(token: str, q: str, variables: dict) -> dict:
    req = urllib.request.Request(API, data=json.dumps({"query": q, "variables": variables}).encode("utf-8"), method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310 — Cloudflare's API
            body = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        raise SystemExit(f"the GraphQL API answered {err.code}: {err.read().decode('utf-8', 'replace')[:300]}") from None
    if body.get("errors"):
        raise SystemExit(f"the GraphQL API refused the query: {json.dumps(body['errors'], ensure_ascii=False)[:600]}")
    return body["data"]


def available(token: str, zone: str) -> dict[str, dict]:
    """What the zone's plan exposes of the two nodes: enabled, the fields, the limits."""
    q = ("query($zone: string) { viewer { zones(filter: {zoneTag: $zone}) { settings { "
         "firewallEventsAdaptive { enabled availableFields maxDuration maxNumberOfFields maxPageSize notOlderThan } "
         "httpRequestsAdaptiveGroups { enabled availableFields maxDuration maxNumberOfFields maxPageSize notOlderThan } } } } }")
    data = query(token, q, {"zone": zone})
    zones = data["viewer"]["zones"]
    if not zones:
        raise SystemExit("the zone is not visible to this token (Zone → Analytics: Read on impf.ai, and the right CLOUDFLARE_ZONE_ID)")
    return zones[0]["settings"]


def offered(wanted: list[str], node: dict, nested: str = "") -> list[str]:
    """The wanted fields the node offers, in order.  availableFields names a nested field by its path joined with '_'
    (dimensions_clientIP, avg_sampleInterval); a node that lists none is asked for all of them."""
    have = {str(f).replace(".", "_") for f in node.get("availableFields") or []}
    if not have:
        return list(wanted)
    return [f for f in wanted if (f"{nested}_{f}" if nested else f) in have]


def capped(fields: list[str], node: dict, others: int = 0) -> list[str]:
    """As many of the fields as a query of the node may name beside `others`."""
    most = int(node.get("maxNumberOfFields") or 0)
    return fields[: max(most - others, 0)] if most else fields


def reach(node: dict, start: datetime, end: datetime, now: datetime) -> datetime | None:
    """Where a query of [start, end) may begin: not before the node's notOlderThan (five minutes inside it, for the
    clock and the run); None when none of it is in reach."""
    older = int(node.get("notOlderThan") or 0)
    if older:
        start = max(start, (now - timedelta(seconds=older) + timedelta(minutes=5)).replace(second=0, microsecond=0))
    return start if start < end else None


def slices(start: datetime, end: datetime, width: timedelta) -> list[tuple[str, str]]:
    """[start, end) in windows no wider than width, as the API's times."""
    out = []
    while start < end:
        stop = min(start + width, end)
        out.append((start.strftime("%Y-%m-%dT%H:%M:%SZ"), stop.strftime("%Y-%m-%dT%H:%M:%SZ")))
        start = stop
    return out


def widest(node: dict, most: timedelta) -> timedelta:
    """The window a query of the node may cover: its maxDuration, and no more than most."""
    return min(timedelta(seconds=int(node.get("maxDuration") or 0)) or most, most)


def limits(node: dict) -> dict:
    return {k: node.get(k) for k in ("enabled", "notOlderThan", "maxDuration", "maxPageSize", "maxNumberOfFields")} | {
        "fields": len(node.get("availableFields") or [])}


def firewall_events(token: str, zone: str, start: str, end: str, fields: list[str], page: int, pages: int = 40) -> tuple[list[dict], bool]:
    """The events of the window, newest first, page by page (the next page ends where the last one began); (events,
    complete) — not complete when the pages ran out."""
    q = ("query($zone: string, $start: Time, $end: Time, $limit: Int) { viewer { zones(filter: {zoneTag: $zone}) { "
         f"firewallEventsAdaptive(filter: {{datetime_geq: $start, datetime_leq: $end}}, limit: $limit, orderBy: [datetime_DESC]) {{ {' '.join(fields)} }} }} }} }}")
    out: list[dict] = []
    until = end
    for _ in range(pages):
        rows = query(token, q, {"zone": zone, "start": start, "end": until, "limit": page})["viewer"]["zones"][0]["firewallEventsAdaptive"]
        out.extend(rows)
        if len(rows) < page:
            return out, True
        oldest = min(r.get("datetime") or until for r in rows)
        if oldest >= until:  # a page of events all at one instant: nothing earlier can be asked for
            return out, False
        until = oldest
    return out, False


def request_groups(token: str, zone: str, windows: list[tuple[str, str]], host: str, dims: list[str], page: int,
                   sampled: bool = True, eyeball: bool = True) -> tuple[list[dict], bool]:
    """The request groups of the windows (a group node cannot be paged, so they are narrow: four hours at most);
    (groups, complete) — not complete when a window filled its page.  sampled: ask for the sample interval (a group's
    count is of the sampled requests); eyeball: only what visitors asked, not the Workers' own fetches."""
    where = "datetime_geq: $start, datetime_lt: $end, " + ('requestSource: "eyeball", ' if eyeball else "") + "clientRequestHTTPHost: $host"
    q = ("query($zone: string, $start: Time, $end: Time, $host: string, $limit: Int) { viewer { zones(filter: {zoneTag: $zone}) { "
         f"httpRequestsAdaptiveGroups(filter: {{{where}}}, limit: $limit, orderBy: [count_DESC]) "
         f"{{ count {'avg { sampleInterval } ' if sampled else ''}dimensions {{ {' '.join(dims)} }} }} }} }} }}")
    out: list[dict] = []
    complete = True
    for start, end in windows:
        rows = query(token, q, {"zone": zone, "start": start, "end": end, "host": host, "limit": page})["viewer"]["zones"][0]["httpRequestsAdaptiveGroups"]
        out.extend(rows)
        if len(rows) >= page:
            complete = False
    return out, complete


# ---------------------------------------------------------------- what is worth keeping of the requests
def ua_class(ua: str) -> str:
    if not ua:
        return "empty"
    if ua.startswith(OWN):
        return "own"
    if TOOL.search(ua):
        return "tool"
    if BROWSER.search(ua):
        return "browser"
    return "other"


def worth(row: dict, volume: int) -> list[str]:
    """Why a request group is kept: the reasons (none: it is a reader's)."""
    d = row["dimensions"]
    why = []
    status = int(d.get("edgeResponseStatus") or 0)
    if status >= 400:
        why.append(f"status_{status // 100}xx")
    action = str(d.get("securityAction") or "").strip().lower()
    if action and action not in ("unknown", "none", "allow", "skip", "log"):  # an action taken, not the absence of one
        why.append(f"security_{action}")
    path = d.get("clientRequestPath") or ""
    if SCANNER_PATH.search(path):
        why.append("scanner_path")
    kind = ua_class(d.get("userAgent") or "")
    if kind in ("empty", "tool"):
        why.append(f"ua_{kind}")
    if volume >= 300:
        why.append("volume")
    return why


def pull(token: str, zone: str, day: datetime, out: Path, hosts: list[str], now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    end_dt = min(day + timedelta(days=1), now.replace(second=0, microsecond=0))
    the_day = day.strftime("%Y-%m-%d")
    caps = available(token, zone)
    fw = caps.get("firewallEventsAdaptive") or {}
    rq = caps.get("httpRequestsAdaptiveGroups") or {}
    kept = {"events": 0, "requests": 0, "skipped": [], "limits": {"firewallEventsAdaptive": limits(fw), "httpRequestsAdaptiveGroups": limits(rq)}}

    def within(node: dict, name: str) -> datetime | None:
        """Where the node may be asked from, saying what of the day it may not be asked for."""
        begin = reach(node, day, end_dt, now)
        keeps = f"the plan keeps {int(node.get('notOlderThan') or 0) // 3600} hours"
        if end_dt <= day:
            kept["skipped"].append(f"{name}: {the_day} has not begun")
        elif begin is None:
            kept["skipped"].append(f"{name}: {the_day} is out of reach ({keeps})")
        elif begin > day:
            kept["skipped"].append(f"{name}: {the_day} before {begin.strftime('%H:%M')} UTC is out of reach ({keeps})")
        return begin

    path = out / day.strftime("%Y") / day.strftime("%m") / f"{day.strftime('%d')}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    seen = set()
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                seen.add(json.loads(line).get("key"))
            except json.JSONDecodeError:
                continue
    lines = []
    fields = capped(offered(FIREWALL_FIELDS, fw), fw)
    begin = within(fw, "firewall events") if fw.get("enabled") and "datetime" in fields else None
    if not fw.get("enabled"):
        kept["skipped"].append("firewallEventsAdaptive is not enabled for this zone/token")
    elif "datetime" not in fields:
        kept["skipped"].append(f"firewall events: the zone offers none of the fields asked for (it lists {sorted(fw.get('availableFields') or [])[:12]})")
    if begin is not None:
        page = min(int(fw.get("maxPageSize") or 1000), 5000)
        events = []
        for start, end in slices(begin, end_dt, widest(fw, timedelta(days=1))):
            got, complete = firewall_events(token, zone, start, end, fields, page)
            events.extend(got)
            if not complete:
                kept["skipped"].append(f"firewall events: more than the pages fetched for {start}–{end} (the oldest of it may be missing)")
        for ev in events:
            key = f"fw:{ev.get('rayName') or ''}:{ev.get('datetime')}:{ev.get('ruleId') or ''}"
            if key in seen:
                continue
            seen.add(key)
            lines.append(json.dumps({"key": key, "kind": "firewall", "day": the_day, **ev}, ensure_ascii=False, sort_keys=True))
            kept["events"] += 1
    sampled = bool(offered(["sampleInterval"], rq, "avg"))
    dims = capped(offered(REQUEST_DIMENSIONS, rq, "dimensions"), rq, 1 + sampled)
    begin = within(rq, "request groups") if rq.get("enabled") and "clientRequestHTTPHost" in dims else None
    if not rq.get("enabled"):
        kept["skipped"].append("httpRequestsAdaptiveGroups is not enabled for this zone/token")
    elif "clientRequestHTTPHost" not in dims:
        kept["skipped"].append(f"request groups: the zone offers none of the dimensions asked for (it lists {sorted(rq.get('availableFields') or [])[:12]})")
    if begin is not None:
        page = min(int(rq.get("maxPageSize") or 2000), 10000)
        windows = slices(begin, end_dt, widest(rq, timedelta(hours=4)))
        eyeball = bool(offered(["requestSource"], rq, "dimensions"))
        actions: dict[str, int] = {}
        for host in hosts:
            groups, complete = request_groups(token, zone, windows, host, dims, page, sampled, eyeball)
            if not complete:
                kept["skipped"].append(f"request groups of {host}: a window filled its page of {page} (the rarest groups may be missing)")
            for row in groups:
                act = str(row["dimensions"].get("securityAction") or "")
                actions[act] = actions.get(act, 0) + 1
                d = row["dimensions"]
                volume = int(round((row.get("count") or 0) * float((row.get("avg") or {}).get("sampleInterval") or 1)))
                why = worth(row, volume)
                if not why:
                    continue
                key = "rq:" + ":".join(str(d.get(k) or "") for k in ("clientIP", "userAgent", "clientRequestPath", "edgeResponseStatus", "clientRequestHTTPMethodName")) + f":{host}"
                if key in seen:
                    continue
                seen.add(key)
                lines.append(json.dumps({"key": key, "kind": "requests", "day": the_day, "requests": volume, "why": why, **d}, ensure_ascii=False, sort_keys=True))
                kept["requests"] += 1
        kept["security_actions_seen"] = actions  # what the zone reports as 'no action': checked once against what worth() ignores
    if lines:
        with path.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    kept["suspects"] = len(suspects(out, write=True))
    return kept


# ---------------------------------------------------------------- the suspects
def suspects(out: Path, write: bool = False) -> dict:
    """Per address, over the last SUSPECT_DAYS days of what was kept: first and last seen, counts by what happened,
    the networks, the agents and the paths (a handful of each), and a score — what the edge rules and the sentinel
    may take into their lists."""
    since = (datetime.now(timezone.utc) - timedelta(days=SUSPECT_DAYS)).strftime("%Y-%m-%d")
    by_ip: dict[str, dict] = {}
    for f in sorted(out.glob("*/*/*.jsonl")):
        day = f"{f.parts[-3]}-{f.parts[-2]}-{f.stem}"
        if day < since:
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            ip = e.get("clientIP")
            if not ip:
                continue
            s = by_ip.setdefault(ip, {"first": day, "last": day, "events": 0, "requests": 0, "blocked": 0, "challenged": 0, "scanner_paths": 0,
                                     "tool_agents": 0, "errors": 0, "asn": None, "asOrg": None, "country": None, "agents": [], "paths": [], "hosts": [], "sources": []})
            s["first"], s["last"] = min(s["first"], day), max(s["last"], day)
            s["asn"] = e.get("clientAsn") or s["asn"]
            s["asOrg"] = e.get("clientASNDescription") or s["asOrg"]
            s["country"] = e.get("clientCountryName") or s["country"]
            for k, v, cap in (("agents", e.get("userAgent"), 6), ("paths", e.get("clientRequestPath"), 12), ("hosts", e.get("clientRequestHTTPHost"), 3),
                              ("sources", e.get("source") or e.get("securitySource"), 4)):
                if v and v not in s[k]:
                    s[k] = (s[k] + [v])[-cap:]
            if e.get("kind") == "firewall":
                s["events"] += 1
                action = str(e.get("action") or "")
                if action == "block":
                    s["blocked"] += 1
                elif "challenge" in action:
                    s["challenged"] += 1
            else:
                n = int(e.get("requests") or 0)
                s["requests"] += n
                why = e.get("why") or []
                if "scanner_path" in why:
                    s["scanner_paths"] += n
                if any(w.startswith("ua_") for w in why):
                    s["tool_agents"] += n
                if any(w.startswith("status_") for w in why):
                    s["errors"] += n
    for s in by_ip.values():
        s["score"] = (min(s["blocked"], 20) * 2 + min(s["challenged"], 20) + min(s["scanner_paths"], 50) * 2 + min(s["tool_agents"], 200) // 10
                      + min(s["errors"], 200) // 20 + (5 if s["requests"] >= 1000 else 2 if s["requests"] >= 300 else 0))
    ranked = dict(sorted(by_ip.items(), key=lambda kv: (-kv[1]["score"], kv[1]["last"]), reverse=False))
    if write:
        out.mkdir(parents=True, exist_ok=True)
        (out / "suspects.json").write_text(json.dumps({"days": SUSPECT_DAYS, "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                                       "suspects": ranked}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return ranked


def days_to_pull(out: Path, now: datetime) -> list[datetime]:
    """The days a pull without --day asks for: every day after the last one kept, through yesterday — the runs that did
    not happen (the Actions minutes ran out, a token was unset) are caught up by the next — no further back than
    CATCH_UP_DAYS; yesterday when none is kept, or the last one kept is yesterday or later."""
    yesterday = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    kept = [f"{f.parts[-3]}-{f.parts[-2]}-{f.stem}" for f in out.glob("*/*/*.jsonl")]
    start = yesterday
    if kept:
        start = min(datetime.strptime(max(kept), "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1), yesterday)
    start = max(start, yesterday - timedelta(days=CATCH_UP_DAYS - 1))
    return [start + timedelta(days=i) for i in range((yesterday - start).days + 1)]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["pull", "suspects"])
    ap.add_argument("--out", default="data/security-logs/edge")
    ap.add_argument("--day", help="the UTC day, YYYY-MM-DD (pull; by default every day after the last one kept, through yesterday)")
    ap.add_argument("--hosts", default=",".join(HOSTS))
    ap.add_argument("--top", type=int, default=30, help="suspects: how many to print")
    args = ap.parse_args(argv)
    out = Path(args.out)
    if args.action == "suspects":
        ranked = suspects(out)
        for ip, s in list(ranked.items())[: args.top]:
            print(f"{s['score']:4d}  {ip:40s} {str(s['country'] or '?'):3s} AS{s['asn'] or '?'} {str(s['asOrg'] or '')[:24]:24s} "
                  f"events {s['events']} blocked {s['blocked']} requests {s['requests']} scanner_paths {s['scanner_paths']}  {s['last']}")
        return
    token = "".join(os.environ.get("CLOUDFLARE_ANALYTICS_TOKEN", "").split())
    zone = os.environ.get("CLOUDFLARE_ZONE_ID", "").strip()
    if not token or not zone:
        raise SystemExit("CLOUDFLARE_ANALYTICS_TOKEN and CLOUDFLARE_ZONE_ID are needed (security/README.md)")
    days = [datetime.strptime(args.day, "%Y-%m-%d").replace(tzinfo=timezone.utc)] if args.day else days_to_pull(out, datetime.now(timezone.utc))
    new = 0
    for day in days:
        result = pull(token, zone, day, out, [h.strip() for h in args.hosts.split(",") if h.strip()])
        for note in result.pop("skipped"):
            print(f"::notice::{note}")
        new += result["events"] + result["requests"]
        print(json.dumps({"day": day.strftime("%Y-%m-%d"), **result}, ensure_ascii=False))
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"new={new}\n")


if __name__ == "__main__":
    main(sys.argv[1:])
