"""The block list as code (security/apply.py, security/blocklist.yaml) against a stand-in Cloudflare API: the repository's
list is valid and spares what must never be blocked; an entry that overlaps such a network, or cannot be read, stops the
list's write; expired entries go; apply writes ours, keeps the addresses added by hand in the dashboard, drops ours that
left the file, and waits for Cloudflare's operation to finish."""

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


def entry(ip: str, until: date = date(2027, 1, 5), why: str = "scanner") -> dict:
    return {"ip": ip, "why": why, "seen": date(2026, 10, 5), "until": until}


def test_the_repository_blocklist_is_valid_and_spares_what_must_never_be_blocked():
    blocklist = yaml.safe_load(BLOCKLIST.read_text(encoding="utf-8"))
    items, notes, problems = apply.wanted_items(blocklist, TODAY)
    assert problems == [] and notes == [] and len(items) == len(blocklist["block"]) > 0
    for e in blocklist["block"]:
        assert e["until"] > e["seen"] and (e["until"] - e["seen"]).days <= 366, e["ip"]  # nothing is refused for good
    for i in items:
        assert i["comment"].startswith(apply.TAG) and len(i["comment"]) <= apply.COMMENT_MAX
    blocked = [ipaddress.ip_network(i["ip"]) for i in items]
    # what this repository's own checks, the search engines and Cloudflare send from: never in the list
    for ip in ("160.79.106.130", "160.79.106.16", "66.249.64.99", "180.163.30.100", "172.70.67.148", "104.16.0.1"):
        assert not any(ipaddress.ip_address(ip) in n for n in blocked), ip


def test_an_entry_overlapping_a_network_never_to_be_blocked_stops_the_write(cloudflare, tmp_path, capsys):
    fake = cloudflare([])
    path = write_blocklist(tmp_path, [entry("82.102.18.116"), entry("160.79.106.129"), entry("180.163.30.0/24"), entry("2606:4700:10::1")])
    with pytest.raises(SystemExit, match="blocklist.yaml"):
        apply.main(["apply", "--only", "list", "--rules", str(RULES), "--blocklist", str(path)])
    out = capsys.readouterr().out
    assert out.count("overlaps a network never to be blocked") == 3 and "360" in out and "Anthropic" in out
    assert fake.puts == []  # not even the good entry: a half-applied list is worse than an unchanged one


def test_every_entry_is_checked_and_an_expired_one_is_left_out():
    blocklist = {"block": [entry("999.1.1.1"), entry("10.0.0.0/4"), {"ip": "198.51.100.1", "why": "x"}, entry("203.0.113.9"),
                           entry("203.0.113.9/32"), entry("203.0.113.0/24", until=date(2026, 10, 1)), entry("2001:db8::1"),
                           entry("192.0.2.0/24", until=datetime(2026, 9, 30, 12, 0))],
                 "never": [{"net": "not a network"}]}
    items, notes, problems = apply.wanted_items(blocklist, TODAY)
    assert [i["ip"] for i in items] == ["203.0.113.9", "2001:db8::1"]
    assert notes == ["· 203.0.113.0/24: expired on 2026-10-01, left out", "· 192.0.2.0/24: expired on 2026-09-30, left out"]
    assert len(problems) == 5 and any("wider than /8" in p for p in problems) and any("listed twice" in p for p in problems)
    assert any("needs why" in p for p in problems) and any("never:" in p for p in problems)


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
