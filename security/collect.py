"""The repository's side of the sentinels (security/README.md; standard library only; run by .github/workflows/chat-logs.yml).

  pull     the events the two Workers hold — the relay (chat-api.impf.ai, /v1/security) and the site (chat.impf.ai,
           /api/security) — after the cursor committed in the repository, appended to data/security-logs/<source>/YYYY/MM/DD.jsonl
           (by the day, UTC, the Worker received them); the cursor (cursor.json) moves with them
  ack      the Workers delete what the repository now holds (after the commit is pushed, never before)
  summary  what a Worker's sentinel sees now: the visitors by score, the addresses refused (printed, kept nowhere)
  archive  a day of the events a Worker archived in its private bucket, into .archive/security-logs/<source>/YYYY/MM/DD.jsonl
           (a local copy to read, never committed: .gitignore)

A Worker with the archive's bucket (docs/adr/0023-workers-paid.md) drains its events there itself: pull then takes none
of its events (its export says so), and its ack is refused (409) — one collector deletes from a Worker, never two.

A Worker that has no sentinel yet (an older deployment: 404), or no collector token yet (the site before deploy.sh set it:
401), is passed over with a notice: the events wait there.  LOG_EXPORT_TOKEN, in the environment, is the collector's token
(a secret of the repository and of both Workers).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

UA = "taochronos-collector/1"
PREFIX = {"relay": "/v1/security", "site": "/api/security"}


def _request(url: str, *, token: str | None = None, data: dict | None = None, timeout: float = 60) -> tuple[int, dict | str]:
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — the Workers' https addresses
            raw = r.read().decode("utf-8")
            status = r.status
    except urllib.error.HTTPError as err:
        raw, status = err.read().decode("utf-8", "replace"), err.code
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, raw


def _token() -> str:
    token = "".join(os.environ.get("LOG_EXPORT_TOKEN", "").split())  # a space or line break pasted with it is not part of it
    if len(token) < 16:
        raise SystemExit("LOG_EXPORT_TOKEN is not set (at least 16 characters)")
    return token


def _output(**values: object) -> None:
    """Step outputs for the workflow, and a line for its log."""
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            for k, v in values.items():
                f.write(f"{k}={v}\n")
    print(json.dumps(values, ensure_ascii=False))


def _sources(args: argparse.Namespace) -> dict[str, str]:
    out = {}
    if args.relay:
        out["relay"] = args.relay.rstrip("/")
    if args.site:
        out["site"] = args.site.rstrip("/")
    if not out:
        raise SystemExit("name at least one of --relay and --site")
    return out


def _cursor(out: Path) -> dict:
    f = out / "cursor.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}


def pull(sources: dict[str, str], out: Path, *, limit: int = 500, pages: int = 40) -> dict:
    token = _token()
    cursor = _cursor(out)
    new_total = 0
    result: dict[str, object] = {}
    for name, base in sources.items():
        state = dict(cursor.get(name) or {})
        last, new = int(state.get("last", 0)), 0
        skipped = None
        for _ in range(pages):
            status, page = _request(f"{base}{PREFIX[name]}/export?after={last}&limit={limit}", token=token)
            if status in (401, 404):
                skipped = status
                break
            if status != 200 or not isinstance(page, dict):
                raise SystemExit(f"the {name} refused the export: HTTP {status} {str(page)[:300]}")
            if page.get("archive"):
                skipped = "archive"
                break
            by_day: dict[str, list[str]] = {}
            for item in page.get("items", []):
                received = str(item.get("received") or datetime.now(timezone.utc).isoformat())
                line = json.dumps({"n": item["id"], "received": received, "source": name, **(item.get("event") or {})}, ensure_ascii=False, sort_keys=True)
                by_day.setdefault(received[:10], []).append(line)
                last = max(last, int(item["id"]))
                new += 1
            for day, lines in sorted(by_day.items()):
                path = out / name / day[:4] / day[5:7] / f"{day[8:10]}.jsonl"
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as f:
                    f.write("\n".join(lines) + "\n")
            if not page.get("more"):
                break
        if skipped == "archive":
            print(f"::notice::the {name} archives its events in its own bucket: none are taken into the repository")
        elif skipped:
            why = "has no sentinel endpoints yet (an older deployment)" if skipped == 404 else "has no collector token yet (deploy it again with LOG_EXPORT_TOKEN set)"
            print(f"::notice::the {name} {why}: its events, if any, wait there")
        if new:
            state["total"] = int(state.get("total", 0)) + new
            state["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        state["last"] = last
        state["pulled"] = new  # this run's: ack acknowledges only a source that gave something
        cursor[name] = state
        result[f"{name}_last"] = last
        result[f"{name}_new"] = new
        new_total += new
    out.mkdir(parents=True, exist_ok=True)
    (out / "cursor.json").write_text(json.dumps(cursor, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return {"new": new_total, **result}


def ack(sources: dict[str, str], out: Path) -> dict:
    token = _token()
    cursor = _cursor(out)
    result: dict[str, object] = {}
    for name, base in sources.items():
        state = cursor.get(name) or {}
        through = int(state.get("last", 0))
        if not state.get("pulled") or through < 1:
            result[f"{name}_acked"] = 0
            continue
        status, body = _request(f"{base}{PREFIX[name]}/ack", token=token, data={"through": through})
        if status == 409:  # the archive took the events over since the pull: it deletes what it archived, and only that
            print(f"::notice::the {name} archives its events now: it deletes them itself once archived")
            result[f"{name}_acked"] = 0
            continue
        if status != 200:
            raise SystemExit(f"the {name} refused the acknowledgement: HTTP {status} {str(body)[:300]}")
        result[f"{name}_acked"] = through
        result[f"{name}_remaining"] = body.get("remaining") if isinstance(body, dict) else None
    return result


def archive(sources: dict[str, str], day: str, out: Path) -> dict:
    """A day of each Worker's archived events, a page at a time, into out/<source>/YYYY/MM/DD.jsonl (written anew)."""
    token = _token()
    result: dict[str, object] = {"day": day}
    for name, base in sources.items():
        lines, cursor, missing = [], "", False
        while True:
            q = f"day={day}&limit=100" + (f"&cursor={urllib.parse.quote(cursor)}" if cursor else "")
            status, page = _request(f"{base}{PREFIX[name]}/archive?{q}", token=token)
            if status == 404:
                missing = True
                break
            if status != 200 or not isinstance(page, dict):
                raise SystemExit(f"the {name} refused the archive: HTTP {status} {str(page)[:300]}")
            lines += [json.dumps(item, ensure_ascii=False, sort_keys=True) for item in page.get("items", [])]
            cursor = page.get("cursor") or ""
            if not page.get("more") or not cursor:
                break
        if missing:
            print(f"::notice::the {name} has no archive (no ARCHIVE bucket bound)")
            result[name] = None
            continue
        path = out / name / day[:4] / day[5:7] / f"{day[8:10]}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(f"{x}\n" for x in lines), encoding="utf-8")
        result[name] = len(lines)
    return result


def summary(sources: dict[str, str]) -> dict:
    token = _token()
    out = {}
    for name, base in sources.items():
        status, body = _request(f"{base}{PREFIX[name]}/summary", token=token)
        out[name] = body if status == 200 else {"error": f"HTTP {status}", "body": str(body)[:300]}
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["pull", "ack", "summary", "archive"])
    ap.add_argument("--relay", default=os.environ.get("RELAY_URL") or "https://chat-api.impf.ai", help="the relay's address ('' to skip it)")
    ap.add_argument("--site", default=os.environ.get("SITE_URL") or "https://chat.impf.ai", help="the site's address ('' to skip it)")
    ap.add_argument("--out", help="pull, ack: where the events and the cursor are (data/security-logs); archive: where the day goes "
                    "(.archive/security-logs)")
    ap.add_argument("--day", help="archive: the day (YYYY-MM-DD, UTC)")
    args = ap.parse_args(argv)
    sources = _sources(args)
    if args.action == "pull":
        _output(**pull(sources, Path(args.out or "data/security-logs")))
    elif args.action == "ack":
        _output(**ack(sources, Path(args.out or "data/security-logs")))
    elif args.action == "archive":
        if not args.day or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.day):
            raise SystemExit("archive needs --day YYYY-MM-DD")
        _output(**archive(sources, args.day, Path(args.out or ".archive/security-logs")))
    else:
        print(json.dumps(summary(sources), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
