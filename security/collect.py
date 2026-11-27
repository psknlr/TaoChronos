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

# What a Worker answers is JSON, and JSON carries two things a file of lines cannot take as they are.  A lone surrogate
# ("\ud800": half a character — what a text cut in the middle of one leaves, or what a sender put there) cannot be
# written as UTF-8: a pull stopped on it before its cursor moved, and so at every run after.  It becomes U+FFFD as the
# answer comes in (_text).  And U+0085, U+2028 and U+2029, which JSON lets a string hold as they are, end a line for
# str.splitlines and for some editors: a record holding one was several lines to its readers.  They are written as
# JSON's own escapes (_line) — the same string to whoever parses the line.
_LONE = re.compile("[\ud800-\udfff]")
_ENDS = re.compile("[\u0085\u2028\u2029]")


def _text(data):
    """Parsed JSON with every string and every key well-formed: a lone surrogate is U+FFFD.  Walked without recursion:
    what a Worker kept may be nested deeper than the interpreter's own stack goes (a report kept before its fields were
    checked), and a walk that stopped there would stop the run on what the parser had read."""
    if isinstance(data, str):
        return _LONE.sub("\ufffd", data)
    waiting = [data]
    while waiting:
        box = waiting.pop()
        if isinstance(box, dict):
            for key in [k for k in box if isinstance(k, str) and _LONE.search(k)]:
                box[_LONE.sub("\ufffd", key)] = box.pop(key)
            inside = list(box.items())
        elif isinstance(box, list):
            inside = list(enumerate(box))
        else:
            continue
        for at, value in inside:
            if isinstance(value, str):
                if _LONE.search(value):
                    box[at] = _LONE.sub("\ufffd", value)
            elif isinstance(value, (dict, list)):
                waiting.append(value)
    return data


def _line(record: dict) -> str:
    """A record as one line of JSON: one line to every reader."""
    return _ENDS.sub(lambda m: f"\\u{ord(m.group()):04x}", json.dumps(record, ensure_ascii=False, sort_keys=True))


# A day's file is kept under what GitHub takes: it refuses a push holding a file over 100 MiB, and nothing bounded a
# day's — four callers' allowance of the largest record made one of 114 MiB, the push was refused, and the same records
# were pulled into the same file at every run after.  Past PART_BYTES a day goes on in a further part, DD.p02.jsonl,
# DD.p03.jsonl …: every reader takes a folder's *.jsonl, and a day is told by what a line says, not by its file's name.
PART_BYTES = 32 * 1024 * 1024


def _part(folder: Path, dd: str, n: int) -> Path:
    return folder / (f"{dd}.jsonl" if n == 1 else f"{dd}.p{n:02d}.jsonl")


def _append(folder: Path, dd: str, lines: list[str]) -> None:
    """A day's lines onto its file: its last part, and a further one wherever a part would pass PART_BYTES."""
    folder.mkdir(parents=True, exist_ok=True)
    n = 1
    while _part(folder, dd, n + 1).exists():
        n += 1
    size = _part(folder, dd, n).stat().st_size if _part(folder, dd, n).exists() else 0
    held: list[str] = []

    def put() -> None:
        if held:
            with _part(folder, dd, n).open("a", encoding="utf-8") as f:
                f.write("\n".join(held) + "\n")
            held.clear()

    for line in lines:
        weight = len(line.encode("utf-8")) + 1
        if size and size + weight > PART_BYTES:
            put()
            n, size = n + 1, 0
        held.append(line)
        size += weight
    put()


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
            raw = r.read().decode("utf-8", "replace")
            status = r.status
    except urllib.error.HTTPError as err:
        raw, status = err.read().decode("utf-8", "replace"), err.code
    try:
        return status, _text(json.loads(raw))
    except (json.JSONDecodeError, RecursionError):  # not JSON, or nested deeper than anything a Worker keeps
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
        size = limit
        for _ in range(pages):
            status, page = _request(f"{base}{PREFIX[name]}/export?after={last}&limit={size}", token=token)
            while status >= 500 and size > 1:  # a page the Worker cannot hand out (too heavy for it): asked for again, smaller
                size = max(1, size // 4)
                status, page = _request(f"{base}{PREFIX[name]}/export?after={last}&limit={size}", token=token)
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
                line = _line({"n": item["id"], "received": received, "source": name, **(item.get("event") or {})})
                by_day.setdefault(received[:10], []).append(line)
                last = max(last, int(item["id"]))
                new += 1
            for day, lines in sorted(by_day.items()):
                _append(out / name / day[:4] / day[5:7], day[8:10], lines)
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
            lines += [_line(item) for item in page.get("items", [])]
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
