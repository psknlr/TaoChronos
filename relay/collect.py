"""The repository's side of 道乃久默认服务 (standard library only; run by .github/workflows).

  pull     the conversation records the relay holds, after the cursor committed in the repository, appended to
           data/chat-logs/YYYY/MM/DD.jsonl (by the day, UTC, the relay received them); the cursor moves with them
  ack      the relay deletes what the repository now holds (after the commit is pushed, never before)
  archive  a day of the records the relay archived in its private bucket, into .archive/chat-logs/YYYY/MM/DD.jsonl
           (a local copy to read, never committed: .gitignore)
  check    a deployed relay answers, and MiniMax accepts its key (one tiny call)

A relay with the archive's bucket (docs/adr/0023-workers-paid.md) drains its records there itself: pull then takes
nothing (the export says so), and ack is refused (409) — one collector deletes from the relay, never two.

The records are those of visitors who agreed to be recorded (the page asks first).  LOG_EXPORT_TOKEN, in the
environment, is the collector's token (a secret of the repository and of the Worker).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

UA = "taochronos-collector/1"


def _request(url: str, *, token: str | None = None, data: dict | None = None, origin: str | None = None,
             timeout: float = 60) -> tuple[int, dict | str]:
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if origin:
        headers["Origin"] = origin
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — the relay's https address
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


def pull(relay: str, out: Path, *, limit: int = 500, pages: int = 40) -> dict:
    token = _token()
    cursor_file = out / "cursor.json"
    cursor = json.loads(cursor_file.read_text(encoding="utf-8")) if cursor_file.is_file() else {"last": 0, "total": 0}
    last, new = int(cursor.get("last", 0)), 0
    for _ in range(pages):
        status, page = _request(f"{relay}/v1/logs/export?after={last}&limit={limit}", token=token)
        if status != 200 or not isinstance(page, dict):
            raise SystemExit(f"the relay refused the export: HTTP {status} {str(page)[:300]}")
        if page.get("archive"):
            print(f"::notice::the relay archives its records in its own bucket ({page['archive']}): none are taken into the repository")
            return {"new": 0, "last": last}
        by_day: dict[str, list[str]] = {}
        for item in page.get("items", []):
            received = str(item.get("received") or datetime.now(timezone.utc).isoformat())
            line = json.dumps({"n": item["id"], "received": received, **(item.get("record") or {})}, ensure_ascii=False, sort_keys=True)
            by_day.setdefault(received[:10], []).append(line)
            last = max(last, int(item["id"]))
            new += 1
        for day, lines in sorted(by_day.items()):
            path = out / day[:4] / day[5:7] / f"{day[8:10]}.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        if not page.get("more"):
            break
    if new:
        out.mkdir(parents=True, exist_ok=True)
        cursor = {"last": last, "total": int(cursor.get("total", 0)) + new, "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        cursor_file.write_text(json.dumps(cursor, indent=1) + "\n", encoding="utf-8")
    return {"new": new, "last": last}


def ack(relay: str, through: int) -> dict:
    status, body = _request(f"{relay}/v1/logs/ack", token=_token(), data={"through": through})
    if status == 409:  # the archive took the book over since the pull: it deletes what it archived, and only that
        print("::notice::the relay archives its records now: it deletes them itself once archived")
        return {"acked": 0, "remaining": None}
    if status != 200:
        raise SystemExit(f"the relay refused the acknowledgement: HTTP {status} {str(body)[:300]}")
    return {"acked": through, "remaining": body.get("remaining") if isinstance(body, dict) else None}


def archive(relay: str, day: str, out: Path) -> dict:
    """A day of the archived records, a page at a time, into out/YYYY/MM/DD.jsonl (written anew each time)."""
    token = _token()
    lines, cursor = [], ""
    while True:
        q = f"day={day}&limit=100" + (f"&cursor={urllib.parse.quote(cursor)}" if cursor else "")
        status, page = _request(f"{relay}/v1/logs/archive?{q}", token=token)
        if status == 404:
            raise SystemExit("the relay has no archive (no ARCHIVE bucket bound: relay/SETUP.md)")
        if status != 200 or not isinstance(page, dict):
            raise SystemExit(f"the relay refused the archive: HTTP {status} {str(page)[:300]}")
        lines += [json.dumps(item, ensure_ascii=False, sort_keys=True) for item in page.get("items", [])]
        cursor = page.get("cursor") or ""
        if not page.get("more") or not cursor:
            break
    path = out / day[:4] / day[5:7] / f"{day[8:10]}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{x}\n" for x in lines), encoding="utf-8")
    return {"day": day, "records": len(lines), "file": str(path)}


def check(relay: str, origin: str, wait: float = 240) -> dict:
    """Health (retried while a new custom domain comes up), then one tiny completion through the relay."""
    end = time.time() + wait
    while True:
        try:
            status, health = _request(f"{relay}/v1/health", timeout=15)
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            status, health = 0, str(err)
        if status == 200 and isinstance(health, dict):
            break
        if time.time() > end:
            raise SystemExit(f"{relay} does not answer: {status} {str(health)[:200]}")
        time.sleep(10)
    if not health.get("ok"):
        raise SystemExit("the relay answers but has no MINIMAX_API_KEY: set the repository secret and deploy again")
    status, reply = _request(f"{relay}/v1/chat/completions", origin=origin, timeout=90, data={
        "model": health.get("model"), "messages": [{"role": "user", "content": "请只回复两个字：可以"}], "max_completion_tokens": 16})
    if status != 200:
        message = reply.get("error", {}).get("message") if isinstance(reply, dict) else str(reply)[:300]
        hint = ""
        if isinstance(reply, dict) and reply.get("error", {}).get("type") == "upstream_auth":
            hint = (" — MiniMax refused the key: a key from the international platform (platform.minimax.io) needs "
                    "UPSTREAM_BASE = \"https://api.minimax.io/v1\" in relay/wrangler.toml; a mainland key, https://api.minimax.cn/v1")
        raise SystemExit(f"the relay answered {status}: {message}{hint}")
    return {"relay": relay, "model": health.get("model"), "logs": health.get("logs"), "limits": health.get("limits"), "call": "ok"}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["pull", "ack", "archive", "check"])
    ap.add_argument("--relay", default=os.environ.get("RELAY_URL") or "https://chat-api.impf.ai")
    ap.add_argument("--out", help="pull: where the records go (data/chat-logs); archive: where the day goes (.archive/chat-logs)")
    ap.add_argument("--day", help="archive: the day (YYYY-MM-DD, UTC)")
    ap.add_argument("--through", type=int, help="ack: the last record the repository holds")
    ap.add_argument("--origin", default="https://chat.impf.ai", help="check: the page's origin")
    args = ap.parse_args(argv)
    relay = args.relay.rstrip("/")
    if args.action == "pull":
        _output(**pull(relay, Path(args.out or "data/chat-logs")))
    elif args.action == "archive":
        if not args.day or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.day):
            raise SystemExit("archive needs --day YYYY-MM-DD")
        _output(**archive(relay, args.day, Path(args.out or ".archive/chat-logs")))
    elif args.action == "ack":
        if not args.through:
            raise SystemExit("ack needs --through")
        _output(**ack(relay, args.through))
    else:
        print(json.dumps(check(relay, args.origin), ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1:])
