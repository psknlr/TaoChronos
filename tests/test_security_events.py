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
    groups = api.of("httpRequestsAdaptiveGroups")
    assert len(groups) == 6  # the day in four-hour windows
    q = groups[0][0]
    assert f"dimensions {{ {' '.join(events.REQUEST_DIMENSIONS)} }}" in q
    assert "avg { sampleInterval }" in q and 'requestSource: "eyeball"' in q
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
    rq = [v["start"] for _, v in api.of("httpRequestsAdaptiveGroups")]
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
