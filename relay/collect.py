"""The repository's side of 道乃久默认服务 (standard library only; run by .github/workflows).

  pull     the conversation records the relay holds, after the cursor committed in the repository, appended to
           data/chat-logs/YYYY/MM/DD.jsonl (by the day, UTC, the relay received them); the cursor moves with them
  ack      the relay deletes what the repository now holds (after the commit is pushed, never before)
  archive  a day of the records the relay archived in its private bucket, into .archive/chat-logs/YYYY/MM/DD.jsonl
           (a local copy to read, never committed: .gitignore)
  check    a deployed relay answers, and MiniMax accepts its key (one tiny call); and, when it offers a second model
           (GPT-6 Luna), that OpenAI accepts its key too
  sponsors the visitors' sponsored API keys, hinted only; --reveal ID prints one key in full, --delete ID removes one
           (SPONSOR_SECRET in the environment; for the owner's own machine — never run --reveal in a workflow)

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

# What a Worker answers is JSON, and JSON carries two things a file of lines cannot take as they are.  A lone surrogate
# ("\ud800": half a character — what a text cut in the middle of one leaves, or what a sender put there) cannot be
# written as UTF-8: a pull stopped on it before its cursor moved, and so at every run after.  It becomes U+FFFD as the
# answer comes in (_text).  And U+0085, U+2028 and U+2029, which JSON lets a string hold as they are, end a line for
# str.splitlines and for some editors: a record holding one was several lines to its readers.  They are written as
# JSON's own escapes (_line) — the same string to whoever parses the line.
_LONE = re.compile("[\ud800-\udfff]")
_ENDS = re.compile("[\u0085\u2028\u2029]")


def _text(data):
    """Parsed JSON with every string and every key well-formed: a lone surrogate is U+FFFD."""
    if isinstance(data, str):
        return _LONE.sub("\ufffd", data)
    if isinstance(data, list):
        return [_text(v) for v in data]
    if isinstance(data, dict):
        return {_text(k): _text(v) for k, v in data.items()}
    return data


def _line(record: dict) -> str:
    """A record as one line of JSON: one line to every reader."""
    return _ENDS.sub(lambda m: f"\\u{ord(m.group()):04x}", json.dumps(record, ensure_ascii=False, sort_keys=True))


def _request(url: str, *, token: str | None = None, data: dict | None = None, origin: str | None = None,
             timeout: float = 60, headers: dict | None = None) -> tuple[int, dict | str]:
    headers = {"User-Agent": UA, "Accept": "application/json", **(headers or {})}
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


def pull(relay: str, out: Path, *, limit: int = 500, pages: int = 40) -> dict:
    token = _token()
    cursor_file = out / "cursor.json"
    cursor = json.loads(cursor_file.read_text(encoding="utf-8")) if cursor_file.is_file() else {"last": 0, "total": 0}
    last, new = int(cursor.get("last", 0)), 0
    for _ in range(pages):
        status, page = _request(f"{relay}/v1/logs/export?after={last}&limit={limit}", token=token)
        # a page the relay cannot hand out (one heavier than a Durable Object may return — a relay from before it bounded
        # its pages by weight — fails at every run, and the collection with it): asked for again, smaller
        while status >= 500 and limit > 1:
            limit = max(1, limit // 4)
            status, page = _request(f"{relay}/v1/logs/export?after={last}&limit={limit}", token=token)
        if status != 200 or not isinstance(page, dict):
            raise SystemExit(f"the relay refused the export: HTTP {status} {str(page)[:300]}")
        if page.get("archive"):
            print(f"::notice::the relay archives its records in its own bucket ({page['archive']}): none are taken into the repository")
            return {"new": 0, "last": last}
        by_day: dict[str, list[str]] = {}
        for item in page.get("items", []):
            received = str(item.get("received") or datetime.now(timezone.utc).isoformat())
            line = _line({"n": item["id"], "received": received, **(item.get("record") or {})})
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
        lines += [_line(item) for item in page.get("items", [])]
        cursor = page.get("cursor") or ""
        if not page.get("more") or not cursor:
            break
    path = out / day[:4] / day[5:7] / f"{day[8:10]}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{x}\n" for x in lines), encoding="utf-8")
    return {"day": day, "records": len(lines), "file": str(path)}


def _second(relay: str, origin: str, model: str) -> str:
    """One tiny call to the relay's second model, as the page makes it (a turn of its own: it counts one question of the
    checker's address).  "ok"; "limited" when the day's questions there are spent (the key is not reached)."""
    status, reply = _request(f"{relay}/v1/chat/completions", origin=origin, timeout=90, headers={"X-Tao-Turn": f"deploy-check-{int(time.time())}"},
                             data={"model": model, "messages": [{"role": "user", "content": "Reply with one word: ok"}], "max_completion_tokens": 16})
    if status == 200:
        return "ok"
    kind = reply.get("error", {}).get("type") if isinstance(reply, dict) else ""
    if status == 429 and kind in ("daily_limit", "total_limit"):
        return "limited"
    message = reply.get("error", {}).get("message") if isinstance(reply, dict) else str(reply)[:300]
    hint = (" — OpenAI refused OPENAI_API_KEY: update the repository secret and deploy again" if kind == "upstream_auth"
            else " — OpenAI refused the region the call left from: check OPENAI_LOCATION in relay/wrangler.toml" if kind == "upstream_region"
            else " — OpenAI may not offer this model to the key: check OPENAI_MODEL in relay/wrangler.toml" if kind == "upstream_error"
            else " — OpenAI refused the request: the Worker's log names the parameter (upstream openai 400 …)" if kind == "upstream_rejected" else "")
    raise SystemExit(f"the relay's {model} answered {status}: {message}{hint}")


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
    out = {"relay": relay, "model": health.get("model"), "default": health.get("default"), "logs": health.get("logs"),
           "limits": health.get("limits"), "call": "ok"}
    failed: list[str] = []  # each model is checked, whatever another said: one failing does not hide the others
    status, reply = _request(f"{relay}/v1/chat/completions", origin=origin, timeout=90, data={
        "model": health.get("model"), "messages": [{"role": "user", "content": "请只回复两个字：可以"}], "max_completion_tokens": 16})
    if status != 200:
        message = reply.get("error", {}).get("message") if isinstance(reply, dict) else str(reply)[:300]
        hint = ""
        if isinstance(reply, dict) and reply.get("error", {}).get("type") == "upstream_auth":
            hint = (" — MiniMax refused the key: a key from the international platform (platform.minimax.io) needs "
                    "UPSTREAM_BASE = \"https://api.minimax.io/v1\" in relay/wrangler.toml; a mainland key, https://api.minimax.cn/v1")
        out["call"] = "failed"
        failed.append(f"the relay answered {status}: {message}{hint}")
    others = [m for m in health.get("models") or [] if m != health.get("model")]
    if others:
        out["second"] = {}
        for m in others:
            try:
                out["second"][m] = _second(relay, origin, m)
            except SystemExit as err:
                out["second"][m] = "failed"
                failed.append(str(err))
    # whether the model service's host answers from each place the relay asks it from, and how soon (GET /v1/egress,
    # docs/adr/0033): for whoever reads the log — the deployment stands whatever this says, or if it says nothing.  The
    # relay answers it to the collector's token only (it is the owner's diagnostic): asked when this run has the token
    token = "".join(os.environ.get("LOG_EXPORT_TOKEN", "").split())
    if len(token) >= 16:
        try:
            status, seen = _request(f"{relay}/v1/egress", token=token, timeout=45)
            if status == 200 and isinstance(seen, dict) and isinstance(seen.get("model"), dict):
                out["places"] = {"from": seen.get("worker"), **seen["model"]}
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
    if failed:
        print(json.dumps(out, ensure_ascii=False))  # what did pass, in the log, before the failure
        raise SystemExit("; ".join(failed))
    return out


def _sponsor_secret() -> str:
    secret = "".join(os.environ.get("SPONSOR_SECRET", "").split())
    if len(secret) < 32:
        raise SystemExit("SPONSOR_SECRET is not set (the Worker's, at least 32 characters)")
    return secret


def sponsors(relay: str, *, reveal: int | None = None, delete: int | None = None) -> dict:
    """The visitors' sponsorships: the list (keys hinted), one with its key (reveal), or one removed (delete)."""
    if reveal and os.environ.get("GITHUB_ACTIONS") == "true":
        raise SystemExit("--reveal prints a visitor's key: run it on your own machine, never in a workflow (its log is kept)")
    secret = _sponsor_secret()
    if delete:
        status, body = _request(f"{relay}/v1/sponsors/delete", token=secret, data={"id": delete})
    else:
        status, body = _request(f"{relay}/v1/sponsors" + (f"?reveal={int(reveal)}" if reveal else ""), token=secret)
    if status != 200:
        message = body.get("error", {}).get("message") if isinstance(body, dict) else str(body)[:200]
        raise SystemExit(f"the relay refused: HTTP {status} {message}")
    return body


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["pull", "ack", "archive", "check", "sponsors"])
    ap.add_argument("--relay", default=os.environ.get("RELAY_URL") or "https://chat-api.impf.ai")
    ap.add_argument("--out", help="pull: where the records go (data/chat-logs); archive: where the day goes (.archive/chat-logs)")
    ap.add_argument("--day", help="archive: the day (YYYY-MM-DD, UTC)")
    ap.add_argument("--through", type=int, help="ack: the last record the repository holds")
    ap.add_argument("--origin", default="https://chat.impf.ai", help="check: the page's origin")
    ap.add_argument("--reveal", type=int, help="sponsors: print this sponsorship's key in full")
    ap.add_argument("--delete", type=int, help="sponsors: remove this sponsorship")
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
    elif args.action == "sponsors":
        # printed only, never into the workflow's outputs: a revealed key is a visitor's
        print(json.dumps(sponsors(relay, reveal=args.reveal, delete=args.delete), ensure_ascii=False, indent=1))
    else:
        print(json.dumps(check(relay, args.origin), ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1:])
