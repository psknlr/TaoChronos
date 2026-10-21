"""The block list as code (security/apply.py, security/blocklist.yaml) against a stand-in Cloudflare API: the repository's
list is valid and spares what must never be blocked; an entry that overlaps such a network, or cannot be read, stops the
list's write; an entry is refused for good unless it has an until, and goes once that day is past; apply writes ours,
keeps the addresses added by hand in the dashboard, drops ours that left the file, and waits for Cloudflare's operation
to finish."""

from __future__ import annotations

import importlib.util
import ipaddress
from datetime import date, datetime
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("apply", ROOT / "security" / "apply.py")
apply = importlib.util.module_from_spec(spec)
spec.loader.exec_module(apply)

RULES = ROOT / "security" / "rules.yaml"
BLOCKLIST = ROOT / "security" / "blocklist.yaml"
TODAY = date(2026, 10, 7)
ACCOUNT, LIST = "acc0", "list0"


class FakeCloudflare:
    """The account's lists, the block list's items (two pages), its replacement and the operation's status."""

    def __init__(self, items: list[dict], operation: str = "completed") -> None:
        self.items = items
        self.operation = operation
        self.puts: list[list[dict]] = []
        self.calls: list[tuple[str, str]] = []

    def __call__(self, api, method: str, path: str, body=None):
        self.calls.append((method, path))
        if (method, path) == ("GET", f"/accounts/{ACCOUNT}/rules/lists"):
            return 200, {"result": [{"id": "other", "name": "something_else"}, {"id": LIST, "name": "taochronos_block"}]}
        if method == "GET" and path.startswith(f"/accounts/{ACCOUNT}/rules/lists/{LIST}/items"):
            first, rest = self.items[:1], self.items[1:]
            if "cursor=next" in path:
                return 200, {"result": [{"id": f"i{k}", **i} for k, i in enumerate(rest)], "result_info": {"cursors": {}}}
            return 200, {"result": [{"id": "i0", **i} for i in first], "result_info": {"cursors": {"after": "next"} if rest else {}}}
        if (method, path) == ("PUT", f"/accounts/{ACCOUNT}/rules/lists/{LIST}/items"):
            self.puts.append(body)
            return 200, {"result": {"operation_id": "op1"}}
        if (method, path) == ("GET", f"/accounts/{ACCOUNT}/rules/lists/bulk_operations/op1"):
            return 200, {"result": {"id": "op1", "status": self.operation, **({"error": "an item is not valid"} if self.operation == "failed" else {})}}
        raise AssertionError(f"unexpected call {method} {path}")


@pytest.fixture
def cloudflare(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_SECURITY_TOKEN", "token")
    monkeypatch.setenv("CLOUDFLARE_ZONE_ID", "zone0")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", ACCOUNT)
    monkeypatch.setattr(apply, "pause", lambda s: None)

    def install(items: list[dict], operation: str = "completed") -> FakeCloudflare:
        fake = FakeCloudflare(items, operation)
        monkeypatch.setattr(apply.Api, "call", lambda api, method, path, body=None: fake(api, method, path, body))  # a method, bound
        return fake
    return install


def write_blocklist(tmp_path: Path, block: list[dict]) -> Path:
    never = yaml.safe_load(BLOCKLIST.read_text(encoding="utf-8"))["never"]
    path = tmp_path / "blocklist.yaml"
    path.write_text(yaml.safe_dump({"block": block, "never": never}, allow_unicode=True), encoding="utf-8")
    return path


def entry(ip: str, until: date | None = None, why: str = "scanner") -> dict:
    """A block-list entry: for good, or until a day."""
    return {"ip": ip, "why": why, "seen": date(2026, 10, 5), **({"until": until} if until else {})}


def test_the_repository_blocklist_is_valid_and_spares_what_must_never_be_blocked():
    blocklist = yaml.safe_load(BLOCKLIST.read_text(encoding="utf-8"))
    items, notes, problems = apply.wanted_items(blocklist, TODAY)
    assert problems == [] and notes == [] and len(items) == len(blocklist["block"]) > 0
    for e, i in zip(blocklist["block"], items):
        assert isinstance(e["seen"], date) and ("until" not in e or e["until"] > e["seen"]), e["ip"]
        assert i["comment"].startswith(apply.TAG) and len(i["comment"]) <= apply.COMMENT_MAX
        assert i["comment"].endswith("for good" if "until" not in e else f"until {e['until']}")
    blocked = [ipaddress.ip_network(i["ip"]) for i in items]
    # what this repository's own checks, the search engines and Cloudflare send from: never in the list — nor a GitHub
    # Actions runner the collector and the deploy check ran on, Bingbot, Bytespider (头条搜索), or a Tencent Cloud address
    # fetching the page as WeChat's link preview and safety check do (seen in data/security-logs; security/README.md)
    for ip in ("160.79.106.130", "160.79.106.16", "66.249.64.99", "180.163.30.100", "172.70.67.148", "104.16.0.1",
               "20.168.124.176", "40.77.167.46", "52.167.144.25", "111.225.148.175", "106.55.200.45"):
        assert not any(ipaddress.ip_address(ip) in n for n in blocked), ip


def test_an_entry_overlapping_a_network_never_to_be_blocked_stops_the_write(cloudflare, tmp_path, capsys):
    fake = cloudflare([])
    path = write_blocklist(tmp_path, [entry("82.102.18.116"), entry("160.79.106.129"), entry("180.163.30.0/24"), entry("2606:4700:10::1")])
    with pytest.raises(SystemExit, match="blocklist.yaml"):
        apply.main(["apply", "--only", "list", "--rules", str(RULES), "--blocklist", str(path)])
    out = capsys.readouterr().out
    assert out.count("overlaps a network never to be blocked") == 3 and "360" in out and "Anthropic" in out
    assert fake.puts == []  # not even the good entry: a half-applied list is worse than an unchanged one


def test_every_entry_is_checked_refused_for_good_without_until_and_left_out_past_it():
    blocklist = {"block": [entry("999.1.1.1"), entry("10.0.0.0/4"), {"ip": "198.51.100.1", "why": "x"},
                           {"ip": "198.51.100.2", "until": date(2027, 1, 1)}, {"ip": "198.51.100.3", "why": "x", "until": "soon"},
                           entry("203.0.113.9", until=date(2027, 1, 5)), entry("203.0.113.9/32"),
                           entry("203.0.113.0/24", until=date(2026, 10, 1)), entry("2001:db8::1"),
                           entry("192.0.2.0/24", until=datetime(2026, 9, 30, 12, 0))],
                 "never": [{"net": "not a network"}]}
    items, notes, problems = apply.wanted_items(blocklist, TODAY)
    assert [i["ip"] for i in items] == ["198.51.100.1", "203.0.113.9", "2001:db8::1"]
    assert items[0]["comment"].endswith("· for good") and items[1]["comment"].endswith("· until 2027-01-05")
    assert notes == ["· 203.0.113.0/24: expired on 2026-10-01, left out", "· 192.0.2.0/24: expired on 2026-09-30, left out"]
    assert len(problems) == 6 and any("wider than /8" in p for p in problems) and any("listed twice" in p for p in problems)
    assert any("needs why" in p for p in problems) and any("until must be a date" in p for p in problems)
    assert any("never:" in p for p in problems)


def test_apply_writes_ours_keeps_the_ones_added_by_hand_and_drops_ours_that_left(cloudflare, tmp_path, capsys):
    by_hand = {"ip": "203.0.113.5", "comment": "added in the dashboard during an incident"}
    stale = {"ip": "198.51.100.7", "comment": f"{apply.TAG} an old scanner · seen 2026-07-01 · until 2026-12-31"}
    fake = cloudflare([stale, by_hand])  # two pages
    path = write_blocklist(tmp_path, [entry("82.102.18.116"), entry("34.76.3.0/24")])
    apply.main(["apply", "--only", "list", "--rules", str(RULES), "--blocklist", str(path)])
    out = capsys.readouterr().out
    assert len(fake.puts) == 1
    assert [i["ip"] for i in fake.puts[0]] == ["82.102.18.116", "34.76.3.0/24", "203.0.113.5"]
    assert fake.puts[0][2] == by_hand and all(i["comment"].startswith(apply.TAG) for i in fake.puts[0][:2])
    assert "+ 82.102.18.116: added" in out and "- 198.51.100.7: removed" in out and "= 1 address(es) added by hand kept: 203.0.113.5" in out
    assert "written" in out and ("GET", f"/accounts/{ACCOUNT}/rules/lists/bulk_operations/op1") in fake.calls


def test_plan_writes_nothing_and_an_unchanged_list_is_not_rewritten(cloudflare, tmp_path, capsys):
    path = write_blocklist(tmp_path, [entry("82.102.18.116")])
    fake = cloudflare([])
    apply.main(["plan", "--only", "list", "--rules", str(RULES), "--blocklist", str(path)])
    assert fake.puts == [] and "+ 82.102.18.116: added" in capsys.readouterr().out
    wanted, _, _ = apply.wanted_items(yaml.safe_load(path.read_text(encoding="utf-8")), TODAY)
    fake = cloudflare(wanted)
    apply.main(["apply", "--only", "list", "--rules", str(RULES), "--blocklist", str(path)])
    assert fake.puts == [] and "(no change)" in capsys.readouterr().out


def test_a_failed_operation_and_a_missing_list_are_failures(cloudflare, tmp_path, monkeypatch, capsys):
    path = write_blocklist(tmp_path, [entry("82.102.18.116")])
    cloudflare([], operation="failed")
    with pytest.raises(SystemExit, match="the block list's addresses"):
        apply.main(["apply", "--only", "list", "--rules", str(RULES), "--blocklist", str(path)])
    assert "REFUSED: an item is not valid" in capsys.readouterr().out
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID")  # addresses to refuse and no list to hold them: not a quiet success
    fake = cloudflare([])
    with pytest.raises(SystemExit):
        apply.main(["apply", "--only", "list", "--rules", str(RULES), "--blocklist", str(path)])
    assert fake.puts == []


# ------------------------------------------------------------------ the rules as Cloudflare reads them
TOKEN = __import__("re").compile(r'\s*(?:(?P<str>"(?:[^"\\]|\\.)*")|(?P<num>\d+)|(?P<op>\(|\)|\{|\}|,|\[|\])|(?P<word>[A-Za-z_][\w.]*))')


def evaluate(expression: str, request: dict) -> bool:
    """A rule's expression evaluated against a request — the part of Cloudflare's rules language these rules use: fields
    (a header map indexed as field["name"][0]: a header the request lacks is missing, and compares false), strings,
    numbers and sets, eq / ne / contains / in, lower() / len() / starts_with() / ends_with(), not / and / or."""
    import json as _json

    tokens, at = [], 0
    while at < len(expression):
        m = TOKEN.match(expression, at)
        if not m or m.end() == at:
            if expression[at:].strip():
                raise ValueError(f"cannot read {expression[at:at + 30]!r}")
            break
        at = m.end()
        kind = m.lastgroup
        tokens.append((kind, _json.loads(m.group(kind)) if kind == "str" else int(m.group(kind)) if kind == "num" else m.group(kind)))
    pos = 0

    def peek():
        return tokens[pos] if pos < len(tokens) else (None, None)

    def take(value=None):
        nonlocal pos
        tok = tokens[pos]
        assert value is None or tok[1] == value, (tok, value)
        pos += 1
        return tok

    def value():
        kind, v = take()
        if kind in ("str", "num"):
            return v
        if v == "{":
            items = []
            while peek()[1] != "}":
                items.append(take()[1])
            take("}")
            return set(items)
        if v == "(":
            out = disjunction()
            take(")")
            return out
        if v in ("lower", "len", "starts_with", "ends_with"):
            take("(")
            args = [value()]
            while peek()[1] == ",":
                take(",")
                args.append(value())
            take(")")
            return {"lower": lambda s: s.lower(), "len": len, "starts_with": lambda s, p: s.startswith(p),
                    "ends_with": lambda s, p: s.endswith(p)}[v](*args)
        if v in ("true", "false"):
            return v == "true"
        out = request[v]  # a field
        while peek()[1] == "[":
            take("[")
            key = value()
            take("]")
            out = out.get(key) if isinstance(out, dict) else out[key] if isinstance(out, list) and key < len(out) else None
        return out

    def comparison():
        left = value()
        op = peek()[1]
        if op in ("eq", "ne", "contains", "in"):
            take()
            right = value()
            if op == "eq":
                return left == right
            if op == "ne":
                return left != right
            if op == "contains":
                return isinstance(left, str) and right in left
            return left in right
        return left

    def negation():
        if peek()[1] == "not":
            take()
            return not negation()
        return comparison()

    def conjunction():
        out = negation()
        while peek()[1] == "and":
            take()
            right = negation()
            out = out and right
        return out

    def disjunction():
        out = conjunction()
        while peek()[1] == "or":
            take()
            right = conjunction()
            out = out or right
        return out

    result = disjunction()
    assert pos == len(tokens), tokens[pos:]
    return bool(result)


def rendered_rule(ref: str) -> str:
    rules = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    return next(r["expression"] for r in apply.render(rules, True)["http_request_firewall_custom"] if r["ref"] == ref)


GOOGLEBOT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
GOOGLEBOT_PHONE = ("Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/141.0.7390.122 Mobile Safari/537.36 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)")
BINGBOT = ("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm) "
           "Chrome/116.0.1938.76 Safari/537.36")
CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"


def test_search_engines_pass_the_edge_and_crawlers_for_ai_training_do_not():
    """Cloudflare's own AI-training block (ai_training: block, its rule BOBA-199) refused the real Googlebot and Bingbot
    (data/security-logs/edge, 2026-10-07 to 10-10), so the site fell out of their indexes.  Training crawlers are refused
    by name in R4 instead — verified or not — and the search engines, verified, pass; a name a crawler claims without
    Cloudflare's verification is still refused."""
    from taochronos.chat.build import TRAINING_CRAWLERS

    rules = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    assert rules["bot_management"]["ai_training"] != "block"
    robots_only = {"Google-Extended", "Applebot-Extended"}  # tokens in robots.txt, never in a request's agent
    assert set(rules["training_agents"]) == set(TRAINING_CRAWLERS) - robots_only
    search = ("Googlebot", "bingbot", "Baiduspider", "Bytespider", "YandexBot", "Applebot/", "PetalBot", "Sogou", "360Spider",
              "DuckDuckBot", "YisouSpider", "OAI-SearchBot", "ChatGPT-User", "Claude-User", "Claude-SearchBot", "PerplexityBot")
    assert not [a for a in rules["training_agents"] for s in search if s.lower() in a.lower() or a.lower() in s.lower()]
    r4 = rendered_rule("tc-tooling-and-spoofed-crawlers")
    req = lambda ua, bot=False, path="/": {"http.user_agent": ua, "cf.client.bot": bot, "http.request.uri.path": path}  # noqa: E731
    passes = [req(GOOGLEBOT, True), req(GOOGLEBOT_PHONE, True), req("Googlebot-Image/1.0", True), req(BINGBOT, True),
              req("Mozilla/5.0 (compatible; Baiduspider/2.0; +http://www.baidu.com/search/spider.html)", True),
              req("Mozilla/5.0 (Linux; Android 5.0) AppleWebKit/537.36 (KHTML, like Gecko) Mobile Safari/537.36 (compatible; "
                  "Bytespider; spider-feedback@bytedance.com)", True),
              req("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; ChatGPT-User/1.0; +https://openai.com/bot)", True),
              req("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Claude-User/1.0; +claude-user@anthropic.com)", True),
              req(CHROME), req("curl/8.5.0"), req("taochronos-collector/1"), req("", path="/.well-known/acme-challenge/x")]
    blocked = [req("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2; +https://openai.com/gptbot)", True),
               req("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; ClaudeBot/1.0; +claudebot@anthropic.com)", True),
               req("CCBot/2.0 (https://commoncrawl.org/faq/)", True), req("meta-externalagent/1.1", True),
               req(GOOGLEBOT), req(BINGBOT),  # the names without Cloudflare's verification
               req("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Claude-User/1.0; +claude-user@anthropic.com)"),
               req("python-requests/2.27.1"), req("Python-urllib/3.10"), req(""), req("Go-http-client/1.1")]
    assert [r["http.user_agent"][:40] for r in passes if evaluate(r4, r)] == []
    assert [r["http.user_agent"][:40] for r in blocked if not evaluate(r4, r)] == []
    # the other rules read the same language: the scanner paths (R2) refuse /.env and let the site's own files through
    r2 = rendered_rule("tc-scanner-paths")
    path = lambda p: {"http.request.uri.path": p, "http.request.uri": p, "http.host": "chat.impf.ai",  # noqa: E731
                      "http.user_agent": CHROME, "http.request.uri.query": "", "http.request.method": "GET", "cf.client.bot": False}
    assert evaluate(r2, path("/.env")) and evaluate(r2, path("/.git/config")) and not evaluate(r2, path("/js/app.js"))


def test_the_relays_take_nothing_another_zones_worker_forwards():
    """R3: the relay (chat-api.impf.ai) takes a model call or a record only from the page's origins; and neither relay
    (chat-api.impf.ai, science.impf.ai's Tao-S1) takes anything a Worker of another zone forwards.  A Worker writes any
    Origin it likes, and every cross-zone subrequest comes from 2a06:98c0:3600::103, Cloudflare's own address (never on
    the block list): 2,225 model calls in the owner's report of 2026-10-21.  The page's calls (no upstream zone), our own
    Workers' (impf.ai), a page or the site's API fetched by a Worker, and a health check pass."""
    r3 = rendered_rule("tc-relay-origin")
    page = yaml.safe_load(RULES.read_text(encoding="utf-8"))["origins"][0]

    def req(host: str, path: str = "/v1/chat/completions", method: str = "POST", origin: str = page, zone: str = "") -> dict:
        return {"http.host": host, "http.request.uri.path": path, "http.request.method": method,
                "http.request.headers": {"origin": [origin]} if origin else {}, "cf.worker.upstream_zone": zone}

    passes = [req("chat-api.impf.ai"), req("chat-api.impf.ai", "/v1/logs"), req("science.impf.ai", origin="https://science.impf.ai"),
              req("chat-api.impf.ai", zone="impf.ai"), req("chat-api.impf.ai", "/v1/health", "GET", origin=""),
              req("science.impf.ai", "/v1/health", "GET", origin=""), req("chat.impf.ai", "/", "GET", origin="", zone="someone.workers.dev"),
              req("chat.impf.ai", "/api/call", origin="https://chat.impf.ai", zone="someone.workers.dev")]
    blocked = [req("chat-api.impf.ai", origin="https://example.com"), req("chat-api.impf.ai", origin=""),
               req("chat-api.impf.ai", "/v1/logs", origin="https://example.com"), req("chat-api.impf.ai", zone="someone.workers.dev"),
               req("science.impf.ai", origin="https://science.impf.ai", zone="proxy.example.com"),
               req("science.impf.ai", "/v1/models", "GET", origin="", zone="someone.workers.dev")]
    assert [(r["http.host"], r["http.request.uri.path"]) for r in passes if evaluate(r3, r)] == []
    assert [(r["http.host"], r["http.request.uri.path"]) for r in blocked if not evaluate(r3, r)] == []
