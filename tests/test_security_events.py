"""The edge's record of impf.ai (security/events.py) against a stand-in GraphQL API: the fields asked for are the ones
the zone offers, named as its settings name them (a nested field by its path: dimensions_clientIP); a query never goes
out with an empty selection; the pulls keep within how far back, how wide and how many fields the plan allows, and say
what was out of reach."""

from __future__ import annotations

import importlib.util
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("events", ROOT / "security" / "events.py")
events = importlib.util.module_from_spec(spec)
spec.loader.exec_module(events)

DAY = datetime(2026, 10, 5, tzinfo=timezone.utc)
LATER = DAY + timedelta(days=1, hours=9)  # the run: the next morning
FW_TIMES = ["2026-10-05T00:30:00Z", "2026-10-05T02:00:00Z", "2026-10-05T12:00:00Z"]


def zone_settings(**over) -> dict:
    """The settings node as a Free zone answers it: dimensions named by their path."""
    fw = {"enabled": True, "availableFields": list(events.FIREWALL_FIELDS), "maxDuration": 259200, "maxNumberOfFields": 30,
          "maxPageSize": 1000, "notOlderThan": 2678400}
    rq = {"enabled": True, "availableFields": ["count", "avg_sampleInterval", "dimensions_requestSource",
                                               *(f"dimensions_{d}" for d in events.REQUEST_DIMENSIONS)],
          "maxDuration": 86400, "maxNumberOfFields": 30, "maxPageSize": 1000, "notOlderThan": 691200}
    fw.update(over.get("fw", {}))
    rq.update(over.get("rq", {}))
    return {"firewallEventsAdaptive": fw, "httpRequestsAdaptiveGroups": rq}


class FakeAPI:
    def __init__(self, settings: dict) -> None:
        self.settings = settings
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, token: str, q: str, variables: dict) -> dict:
        assert not re.search(r"\{\s*\}", q), f"a query with an empty selection: {q}"
        self.calls.append((q, variables))
        if "settings" in q:
            return {"viewer": {"zones": [{"settings": self.settings}]}}
        if "firewallEventsAdaptive(" in q:
            rows = [{"datetime": t, "action": "block", "ruleId": "r1", "rayName": f"ray{i}", "clientIP": "203.0.113.9",
                     "description": "[taochronos] 2 tc-scanner-paths"}
                    for i, t in enumerate(FW_TIMES) if variables["start"] <= t <= variables["end"]]
            return {"viewer": {"zones": [{"firewallEventsAdaptive": rows}]}}
        assert "httpRequestsAdaptiveGroups(" in q
        if variables["start"] != "2026-10-05T08:00:00Z":
            return {"viewer": {"zones": [{"httpRequestsAdaptiveGroups": []}]}}
        row = {"count": 4, "dimensions": {"clientIP": "203.0.113.9", "userAgent": "python-requests/2.32", "clientRequestPath": "/.env",
                                          "clientRequestHTTPHost": variables["host"], "clientRequestHTTPMethodName": "GET",
                                          "edgeResponseStatus": 403}}
        if "sampleInterval" in q:
            row["avg"] = {"sampleInterval": 10}
        return {"viewer": {"zones": [{"httpRequestsAdaptiveGroups": [row]}]}}

    def of(self, node: str) -> list[tuple[str, dict]]:
        return [(q, v) for q, v in self.calls if f"{node}(" in q]


def run(monkeypatch, tmp_path: Path, settings: dict, hosts=("chat.impf.ai",)) -> tuple[dict, FakeAPI, list[dict]]:
    api = FakeAPI(settings)
    monkeypatch.setattr(events, "query", api)
    result = events.pull("token", "zone", DAY, tmp_path, list(hosts), now=LATER)
    f = tmp_path / "2026" / "10" / "05.jsonl"
    rows = [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines()] if f.is_file() else []
    return result, api, rows


def test_the_dimensions_are_asked_for_as_the_zone_names_them(monkeypatch, tmp_path):
    result, api, rows = run(monkeypatch, tmp_path, zone_settings())
    groups = [g for g in api.of("httpRequestsAdaptiveGroups") if "clientIP" in g[0]]
    assert len(groups) == 6  # the day in four-hour windows
    q = groups[0][0]
    assert f"dimensions {{ {' '.join(events.REQUEST_DIMENSIONS)} }}" in q
    assert "avg { sampleInterval }" in q and 'requestSource: "eyeball"' in q
    # and the day's requests whatever became of them, asked by country and status alone: no address, no path, no agent
    totals = [g for g in api.of("httpRequestsAdaptiveGroups") if "clientIP" not in g[0]]
    assert len(totals) == 6 and all("dimensions { clientCountryName edgeResponseStatus }" in g[0] and "userAgent" not in g[0] for g in totals)
    assert [r for r in rows if r["kind"] == "traffic"] == [{"key": "tr:chat.impf.ai:XX:403", "kind": "traffic", "day": "2026-10-05", "host": "chat.impf.ai", "country": "XX",
                                                           "status": 403, "requests": 40, "complete": True}]
    assert result["traffic"] == 1
    assert [r["clientRequestPath"] for r in rows if r["kind"] == "requests"] == ["/.env"]
    assert next(r for r in rows if r["kind"] == "requests")["requests"] == 40  # four sampled requests at one in ten
    assert sorted(r["datetime"] for r in rows if r["kind"] == "firewall") == FW_TIMES
    assert result["events"] == 3 and result["requests"] == 1 and result["skipped"] == []
    assert result["limits"]["httpRequestsAdaptiveGroups"]["notOlderThan"] == 691200


def test_a_zone_that_offers_none_of_the_dimensions_is_told_so_and_not_queried(monkeypatch, tmp_path):
    result, api, _ = run(monkeypatch, tmp_path, zone_settings(rq={"availableFields": ["count", "sum_edgeResponseBytes"]}))
    assert api.of("httpRequestsAdaptiveGroups") == []
    assert any(n.startswith("request groups: the zone offers none") and "sum_edgeResponseBytes" in n for n in result["skipped"])
    assert result["events"] == 3  # the firewall events are kept all the same


def test_the_pulls_keep_within_how_far_back_and_how_wide_the_plan_allows(monkeypatch, tmp_path):
    # 26 hours back from 09:00 the next morning: the day from 07:05 on; windows of at most six hours and one hour
    result, api, rows = run(monkeypatch, tmp_path, zone_settings(fw={"notOlderThan": 26 * 3600, "maxDuration": 6 * 3600},
                                                                  rq={"notOlderThan": 26 * 3600, "maxDuration": 3600}))
    fw = [(v["start"], v["end"]) for _, v in api.of("firewallEventsAdaptive")]
    assert fw == [("2026-10-05T07:05:00Z", "2026-10-05T13:05:00Z"), ("2026-10-05T13:05:00Z", "2026-10-05T19:05:00Z"),
                  ("2026-10-05T19:05:00Z", "2026-10-06T00:00:00Z")]
    rq = [v["start"] for q, v in api.of("httpRequestsAdaptiveGroups") if "clientIP" in q]
    assert rq[0] == "2026-10-05T07:05:00Z" and len(rq) == 17
    assert all(datetime.fromisoformat(e.replace("Z", "+00:00")) - datetime.fromisoformat(s.replace("Z", "+00:00")) <= timedelta(hours=1)
               for (_, v) in api.of("httpRequestsAdaptiveGroups") for s, e in [(v["start"], v["end"])])
    assert [r["datetime"] for r in rows if r["kind"] == "firewall"] == ["2026-10-05T12:00:00Z"]
    assert "firewall events: 2026-10-05 before 07:05 UTC is out of reach (the plan keeps 26 hours)" in result["skipped"]
    assert any(n.startswith("request groups: 2026-10-05 before 07:05 UTC") for n in result["skipped"])


def test_a_day_past_the_plans_reach_is_said_and_not_asked_for(monkeypatch, tmp_path):
    result, api, rows = run(monkeypatch, tmp_path, zone_settings(fw={"notOlderThan": 3600}, rq={"notOlderThan": 3600}))
    assert api.of("firewallEventsAdaptive") == [] and api.of("httpRequestsAdaptiveGroups") == [] and rows == []
    assert "firewall events: 2026-10-05 is out of reach (the plan keeps 1 hours)" in result["skipped"]


def test_a_query_names_no_more_fields_than_the_plan_allows(monkeypatch, tmp_path):
    _, api, _ = run(monkeypatch, tmp_path, zone_settings(fw={"maxNumberOfFields": 10}, rq={"maxNumberOfFields": 6}))
    fw = api.of("firewallEventsAdaptive")[0][0]
    asked = re.search(r"orderBy: \[datetime_DESC\]\) \{ (.*?) \}", fw).group(1).split()
    assert asked == events.FIREWALL_FIELDS[:10]
    rq = api.of("httpRequestsAdaptiveGroups")[0][0]
    assert re.search(r"dimensions \{ (.*?) \}", rq).group(1).split() == events.REQUEST_DIMENSIONS[:4]  # count and the interval are two


@pytest.mark.parametrize("missing", ["avg_sampleInterval", "dimensions_requestSource"])
def test_what_the_zone_does_not_offer_is_left_out_of_the_query(monkeypatch, tmp_path, missing):
    settings = zone_settings()
    settings["httpRequestsAdaptiveGroups"]["availableFields"].remove(missing)
    _, api, rows = run(monkeypatch, tmp_path, settings)
    q = api.of("httpRequestsAdaptiveGroups")[0][0]
    if missing == "avg_sampleInterval":
        assert "avg" not in q
        assert next(r for r in rows if r["kind"] == "requests")["requests"] == 4  # the count as it is
    else:
        assert "requestSource" not in q and "clientRequestHTTPHost: $host" in q


CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"


def test_the_runtimes_files_are_counted_by_day_without_addresses_and_who_takes_them_in_bulk_or_by_a_tool_is_kept(monkeypatch, tmp_path):
    """The files the runtime in the browser is made of are public and served past the Worker: what is known of who takes
    them is known at the edge.  A day's totals by file, status and kind of agent are kept with the bytes sent and no
    address (they are every reader's own downloads); an address only with a fetch by what is not a browser, or with one
    file taken more often in the day than readers take it.  And the id of a research run goes into no kept path."""
    def group(ip, ua, path, status, count, size, method="GET"):
        return {"count": count, "avg": {"sampleInterval": 1}, "sum": {"edgeResponseBytes": size},
                "dimensions": {"clientIP": ip, "userAgent": ua, "clientRequestPath": path, "clientRequestHTTPHost": "chat.impf.ai",
                               "clientRequestHTTPMethodName": method, "edgeResponseStatus": status}}

    windows = {
        "2026-10-05T08:00:00Z": [
            group("203.0.113.1", CHROME, "/runtime/taochronos.zip", 200, 1, 1111791),   # two readers: the page's own downloads
            group("203.0.113.2", CHROME, "/runtime/taochronos.zip", 200, 1, 1111791),
            group("203.0.113.1", CHROME, "/runtime/corpus.sqlite.xz", 206, 2, 9000000),  # in parts
            group("203.0.113.1", CHROME, "/runtime/boot.json", 304, 1, 0),
            group("198.51.100.3", "curl/8.4.0", "/runtime/corpus.sqlite.xz", 200, 1, 16853896),  # a tool
            group("198.51.100.4", "Lightpanda/1.0", "/runtime/home.zip", 200, 1, 1468338),       # neither a browser nor a known tool
            group("198.51.100.5", CHROME, "/runtime/home.zip", 200, 12, 12 * 1468338),          # a browser's name, in bulk
            group("198.51.100.6", CHROME, "/api/research/job_0123456789abcdef0123456789abcdef/cancel", 403, 1, 80, "POST"),
        ],
        "2026-10-05T12:00:00Z": [group("198.51.100.5", CHROME, "/runtime/home.zip", 200, 20, 20 * 1468338)],
    }
    settings = zone_settings()
    settings["httpRequestsAdaptiveGroups"]["availableFields"].append("sum_edgeResponseBytes")
    asked = []

    def api(token, q, variables):
        if "settings" in q:
            return {"viewer": {"zones": [{"settings": settings}]}}
        if "firewallEventsAdaptive(" in q:
            rows = [{"datetime": "2026-10-05T09:00:00Z", "action": "block", "ruleId": "r5", "rayName": "ray9", "clientIP": "198.51.100.6",
                     "clientRequestPath": "/api/session/ses_0123456789abcdef0123456789abcdef"}] if variables["start"] <= "2026-10-05T09:00:00Z" <= variables["end"] else []
            return {"viewer": {"zones": [{"firewallEventsAdaptive": rows}]}}
        asked.append(q)
        return {"viewer": {"zones": [{"httpRequestsAdaptiveGroups": windows.get(variables["start"], [])}]}}

    monkeypatch.setattr(events, "query", api)
    result = events.pull("token", "zone", DAY, tmp_path, ["chat.impf.ai"], now=LATER)
    assert "sum { edgeResponseBytes }" in asked[0]
    rows = [json.loads(line) for line in (tmp_path / "2026" / "10" / "05.jsonl").read_text(encoding="utf-8").splitlines()]
    totals = {(r["path"], r["status"], r["agent"]): r for r in rows if r["kind"] == "artifacts"}
    assert result["artifacts"] == len(totals) == 6
    assert [totals["/runtime/taochronos.zip", 200, "browser"][k] for k in ("requests", "addresses", "bytes", "method", "complete")] == [2, 2, 2223582, "GET", True]
    assert [totals["/runtime/corpus.sqlite.xz", 206, "browser"][k] for k in ("requests", "addresses", "bytes")] == [2, 1, 9000000]
    assert totals["/runtime/boot.json", 304, "browser"]["requests"] == 1
    assert [totals["/runtime/home.zip", 200, "browser"][k] for k in ("requests", "addresses", "bytes")] == [32, 1, 32 * 1468338]  # both windows
    assert totals["/runtime/corpus.sqlite.xz", 200, "tool"]["requests"] == 1 and totals["/runtime/home.zip", 200, "other"]["requests"] == 1
    assert not any("clientIP" in r or "userAgent" in r for r in totals.values())  # every reader's own downloads: no address
    by_ip = {r["clientIP"]: r for r in rows if r["kind"] == "requests"}
    assert set(by_ip) == {"198.51.100.3", "198.51.100.4", "198.51.100.5", "198.51.100.6"}  # not the two readers
    assert by_ip["198.51.100.3"]["why"] == ["ua_tool"] and by_ip["198.51.100.3"]["bytes"] == 16853896
    assert by_ip["198.51.100.4"]["why"] == ["artifact_agent"]
    # (its requests are the day's: twelve in one window and twenty in another are one group of thirty-two)
    assert [by_ip["198.51.100.5"][k] for k in ("why", "requests", "fetched", "bytes")] == [["artifact_volume"], 32, 32, 32 * 1468338]
    assert events.ARTIFACT_VOLUME == 30 and events.worth(windows["2026-10-05T08:00:00Z"][0], 1, 29) == []
    # a device's own networking under a browser or an app is a reader's, not a program's: no address for it
    for stack in ("Quark/7.4.5.680 (iPhone; iOS 18.1; Scale/3.00)", "NetworkingExtension/8621.1.15.10.7 Network/4277.42.2 iOS/18.1",
                  "com.apple.WebKit.Networking/20621.1.15 CFNetwork/1568.200.51 Darwin/24.1.0", "Dalvik/2.1.0 (Linux; U; Android 13; BKQ-AN10 Build/HONORBKQ-AN10)"):
        assert events.worth(group("203.0.113.7", stack, "/runtime/corpus.sqlite.xz", 200, 1, 9), 1, 1) == [], stack
    assert events.worth(group("203.0.113.7", "opencode/latest/1.0/cli", "/runtime/boot.json", 200, 1, 9), 1, 1) == ["artifact_agent"]
    # the id of a research run or its session: in no kept path
    assert by_ip["198.51.100.6"]["clientRequestPath"] == "/api/research/…/cancel"
    assert next(r for r in rows if r["kind"] == "firewall")["clientRequestPath"] == "/api/session/…"
    assert "0123456789abcdef" not in (tmp_path / "2026" / "10" / "05.jsonl").read_text(encoding="utf-8")
    # the suspects: what took the runtime's files by a tool or in bulk is counted; the day's totals name nobody
    monkeypatch.setattr(events, "SUSPECT_DAYS", 100000)
    ranked = events.suspects(tmp_path)
    assert {ip: s["artifacts"] for ip, s in ranked.items()} == {"198.51.100.3": 1, "198.51.100.4": 1, "198.51.100.5": 32, "198.51.100.6": 0}
    assert ranked["198.51.100.5"]["score"] == 20 and next(iter(ranked)) == "198.51.100.5"
    # a second pull of the day adds nothing
    again = events.pull("token", "zone", DAY, tmp_path, ["chat.impf.ai"], now=LATER)
    assert [again["events"], again["requests"], again.get("artifacts", 0)] == [0, 0, 0]


def test_a_zone_that_does_not_list_the_bytes_is_not_asked_for_them(monkeypatch, tmp_path):
    _, api, _ = run(monkeypatch, tmp_path, zone_settings())
    assert "edgeResponseBytes" not in api.of("httpRequestsAdaptiveGroups")[0][0]


def kept(out: Path, *days: str) -> None:
    for d in days:
        f = out / d[:4] / d[5:7] / f"{d[8:]}.jsonl"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("{}\n", encoding="utf-8")


def test_a_pull_without_a_day_catches_up_the_days_no_run_kept(tmp_path):
    # the Actions minutes ran out after the run of 10-11 (which kept 10-10): the next run, on 10-18, asks for 10-11 to 10-17
    now = datetime(2026, 10, 18, 1, 41, tzinfo=timezone.utc)
    kept(tmp_path, "2026-10-09", "2026-10-10")
    assert [d.strftime("%m-%d") for d in events.days_to_pull(tmp_path, now)] == [f"10-{n}" for n in range(11, 18)]
    # nothing kept yet, or yesterday kept already (a second run the same day): yesterday, as before
    assert [d.strftime("%m-%d") for d in events.days_to_pull(tmp_path / "none", now)] == ["10-17"]
    kept(tmp_path, "2026-10-17")
    assert [d.strftime("%m-%d") for d in events.days_to_pull(tmp_path, now)] == ["10-17"]


def test_a_catch_up_goes_no_further_back_than_the_plan_keeps(tmp_path):
    now = datetime(2026, 10, 18, 1, 41, tzinfo=timezone.utc)
    kept(tmp_path, "2026-07-01")
    days = events.days_to_pull(tmp_path, now)
    assert len(days) == events.CATCH_UP_DAYS and days[0] == datetime(2026, 9, 17, tzinfo=timezone.utc) and days[-1].strftime("%m-%d") == "10-17"


def fake_groups(windows: dict[str, list[dict]], settings: dict, *, refuse=lambda q: False):
    """A stand-in API answering the request groups of each window (by its start); refuse(q): a query the zone refuses."""
    asked: list[str] = []

    def api(token, q, variables):
        if "settings" in q:
            return {"viewer": {"zones": [{"settings": settings}]}}
        if "firewallEventsAdaptive(" in q:
            return {"viewer": {"zones": [{"firewallEventsAdaptive": []}]}}
        asked.append(q)
        if refuse(q):
            raise SystemExit("the GraphQL API refused the query: unknown field")
        rows = windows.get(variables["start"], [])
        return {"viewer": {"zones": [{"httpRequestsAdaptiveGroups": [r for r in rows if ("clientIP" in r["dimensions"]) == ("clientIP" in q)]}]}}

    return api, asked


def test_a_group_is_counted_over_the_whole_day_and_judged_by_the_days_count(monkeypatch, tmp_path):
    """The API is asked in windows of a few hours.  An address asking a hundred and ten times in each of three windows
    asked three hundred and thirty times that day: one line with that number, kept for its volume.  It was three groups
    of a hundred and ten — each under the day's three hundred, so none of them was kept at all."""
    def group(ip, count):
        return {"count": count, "avg": {"sampleInterval": 1},
                "dimensions": {"clientIP": ip, "userAgent": CHROME, "clientRequestPath": "/api/passage", "clientRequestHTTPHost": "chat.impf.ai",
                               "clientRequestHTTPMethodName": "GET", "edgeResponseStatus": 200}}

    windows = {f"2026-10-05T{h:02d}:00:00Z": [group("198.51.100.9", 110), group("203.0.113.1", 40)] for h in (0, 8, 16)}
    api, _ = fake_groups(windows, zone_settings())
    monkeypatch.setattr(events, "query", api)
    result = events.pull("token", "zone", DAY, tmp_path, ["chat.impf.ai"], now=LATER)
    rows = [json.loads(line) for line in (tmp_path / "2026" / "10" / "05.jsonl").read_text(encoding="utf-8").splitlines()]
    kept = [r for r in rows if r["kind"] == "requests"]
    assert [(r["clientIP"], r["requests"], r["why"]) for r in kept] == [("198.51.100.9", 330, ["volume"])]  # the reader's hundred and twenty are a reader's
    assert result["requests"] == 1


def test_a_day_pulled_again_takes_the_larger_count_and_adds_what_it_lacked(monkeypatch, tmp_path):
    def group(ip, count, path="/.env", status=404):
        return {"count": count, "avg": {"sampleInterval": 1},
                "dimensions": {"clientIP": ip, "userAgent": "curl/8.4.0", "clientRequestPath": path, "clientRequestHTTPHost": "chat.impf.ai",
                               "clientRequestHTTPMethodName": "GET", "edgeResponseStatus": status}}

    def total(country, status, count):
        return {"count": count, "avg": {"sampleInterval": 1}, "dimensions": {"clientCountryName": country, "edgeResponseStatus": status}}

    morning = {"2026-10-05T00:00:00Z": [group("198.51.100.9", 5), total("CN", 200, 100), total("US", 404, 5)]}
    api, _ = fake_groups(morning, zone_settings())
    monkeypatch.setattr(events, "query", api)
    first = events.pull("token", "zone", DAY, tmp_path, ["chat.impf.ai"], now=DAY + timedelta(hours=6))  # pulled before the day was over
    assert (first["requests"], first["traffic"]) == (1, 2)
    whole = {**morning, "2026-10-05T12:00:00Z": [group("198.51.100.9", 7), group("198.51.100.10", 2), total("CN", 200, 300), total("SG", 200, 20)]}
    api, _ = fake_groups(whole, zone_settings())
    monkeypatch.setattr(events, "query", api)
    again = events.pull("token", "zone", DAY, tmp_path, ["chat.impf.ai"], now=LATER)
    rows = [json.loads(line) for line in (tmp_path / "2026" / "10" / "05.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(r["clientIP"], r["requests"]) for r in rows if r["kind"] == "requests"] == [("198.51.100.9", 12), ("198.51.100.10", 2)]
    assert {(r["country"], r["status"]): r["requests"] for r in rows if r["kind"] == "traffic"} == {("CN", 200): 400, ("US", 404): 5, ("SG", 200): 20}
    assert (again["requests"], again["traffic"]) == (2, 2)  # one line counts more, one is new; of the totals, one more and one new
    assert len(rows) == len({r["key"] for r in rows})  # each line once
    # pulled a third time, nothing changes and nothing is counted as new
    third = events.pull("token", "zone", DAY, tmp_path, ["chat.impf.ai"], now=LATER)
    assert (third["requests"], third.get("traffic", 0)) == (0, 0)
    assert [json.loads(line) for line in (tmp_path / "2026" / "10" / "05.jsonl").read_text(encoding="utf-8").splitlines()] == rows


def test_the_days_totals_carry_bytes_and_visits_where_the_zone_lists_them_and_a_zone_that_refuses_them_costs_nothing_else(monkeypatch, tmp_path):
    def total(country, status, count, size, visits):
        return {"count": count, "avg": {"sampleInterval": 2}, "sum": {"edgeResponseBytes": size, "visits": visits},
                "dimensions": {"clientCountryName": country, "edgeResponseStatus": status}}

    probe = {"count": 3, "avg": {"sampleInterval": 1}, "dimensions": {"clientIP": "198.51.100.9", "userAgent": "curl/8.4.0", "clientRequestPath": "/.env",
                                                                    "clientRequestHTTPHost": "chat.impf.ai", "clientRequestHTTPMethodName": "GET", "edgeResponseStatus": 404}}
    windows = {"2026-10-05T08:00:00Z": [probe, total("CN", 200, 50, 9000, 12)], "2026-10-05T12:00:00Z": [total("CN", 200, 25, 1000, 3)]}
    settings = zone_settings()
    settings["httpRequestsAdaptiveGroups"]["availableFields"] += ["sum_edgeResponseBytes", "sum_visits"]
    api, asked = fake_groups(windows, settings)
    monkeypatch.setattr(events, "query", api)
    result = events.pull("token", "zone", DAY, tmp_path, ["chat.impf.ai"], now=LATER)
    rows = [json.loads(line) for line in (tmp_path / "2026" / "10" / "05.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r for r in rows if r["kind"] == "traffic"] == [{"key": "tr:chat.impf.ai:CN:200", "kind": "traffic", "day": "2026-10-05", "host": "chat.impf.ai", "country": "CN",
                                                           "status": 200, "requests": 150, "bytes": 10000, "visits": 15, "complete": True}]
    assert any("sum { edgeResponseBytes visits }" in q for q in asked)
    # a zone that does not list the country of a request is not asked; one that refuses the question loses only the totals
    bare = zone_settings(rq={"availableFields": ["count", "avg_sampleInterval", *(f"dimensions_{d}" for d in events.REQUEST_DIMENSIONS if d != "clientCountryName")]})
    api, asked = fake_groups(windows, bare)
    monkeypatch.setattr(events, "query", api)
    result = events.pull("token", "zone", DAY, tmp_path / "bare", ["chat.impf.ai"], now=LATER)
    assert all("clientIP" in q for q in asked) and result["requests"] == 1 and "traffic" not in result
    assert "traffic of chat.impf.ai: the zone does not list the country and the status of a request" in result["skipped"]
    api, _ = fake_groups(windows, zone_settings(), refuse=lambda q: "clientIP" not in q)
    monkeypatch.setattr(events, "query", api)
    result = events.pull("token", "zone", DAY, tmp_path / "refused", ["chat.impf.ai"], now=LATER)
    assert result["requests"] == 1 and any(n.startswith("traffic of chat.impf.ai: not asked") for n in result["skipped"])


def test_what_the_edge_tells_of_a_request_is_the_senders_and_is_kept_a_line_an_event(monkeypatch, tmp_path):
    """A request's user agent and path are whatever was sent.  A lone surrogate (half a character) in the API's answer
    could not be written, at this run or the next; U+2028, U+2029 and U+0085 were written as they are, and an event
    holding one was several lines when the day was read back — its pieces skipped, or read for something else."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Answer(BaseHTTPRequestHandler):  # the door: the real query against a stand-in API
        def log_message(self, *a) -> None:
            pass

        def do_POST(self) -> None:
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            raw = b'{"data": {"agent": "curl\\ud800/8", "k\\udc00": ["\\ud83d\\ude00"]}}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Answer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        monkeypatch.setattr(events, "API", f"http://127.0.0.1:{server.server_address[1]}/graphql")
        assert events.query("token", "query { x }", {}) == {"agent": "curl\ufffd/8", "k\ufffd": ["\U0001f600"]}
    finally:
        server.shutdown()

    ends = "\u0085\u2028\u2029"
    agent = f"x{ends}7{ends}{{}}{ends}y"  # a piece of it alone would be JSON: a number, an object

    class Agents(FakeAPI):
        def __call__(self, token: str, q: str, variables: dict) -> dict:
            data = super().__call__(token, q, variables)
            for row in data["viewer"]["zones"][0].get("firewallEventsAdaptive") or []:
                row["userAgent"] = agent
            return data

    api = Agents(zone_settings())
    monkeypatch.setattr(events, "query", api)
    first = events.pull("token", "zone", DAY, tmp_path, ["chat.impf.ai"], now=LATER)
    text = (tmp_path / "2026" / "10" / "05.jsonl").read_text(encoding="utf-8")
    assert not any(c in text for c in ends) and len(text.splitlines()) == text.count("\n")  # an event a line, to any reader
    kept_events = [json.loads(x) for x in text.splitlines()]
    assert [e["userAgent"] for e in kept_events if e["kind"] == "firewall"] == [agent] * first["events"] and first["events"] == 3
    again = events.pull("token", "zone", DAY, tmp_path, ["chat.impf.ai"], now=LATER)  # the day read back: nothing lost, nothing twice
    assert again["events"] == 0 and (tmp_path / "2026" / "10" / "05.jsonl").read_text(encoding="utf-8") == text
    # a day kept before, the ends of lines as they were: read whole, and nothing made of its pieces
    today = datetime.now(timezone.utc)
    before = tmp_path / "kept" / today.strftime("%Y") / today.strftime("%m") / f"{today.strftime('%d')}.jsonl"
    before.parent.mkdir(parents=True)
    before.write_text(json.dumps({"key": "fw:old", "kind": "firewall", "day": today.strftime("%Y-%m-%d"), "clientIP": "198.51.100.7", "action": "block",
                                  "userAgent": agent}, ensure_ascii=False) + "\n7\n", encoding="utf-8")
    ranked = events.suspects(tmp_path / "kept")
    assert (ranked["198.51.100.7"]["blocked"], ranked["198.51.100.7"]["agents"]) == (1, [agent])
