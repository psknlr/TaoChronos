"""The repository's side of the activity ledger (security/activity.py) against stand-in Workers: the days not yet kept
are reported, each with the week, the month and the year it falls in asked for as a whole; what is written is sums, a
small place folded into the rest; the pipeline's faults end the run in failure; and the days before the ledger are told
from what was kept of them, the visitors as the two numbers they lie between."""

from __future__ import annotations

import importlib.util
import json
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("activity", ROOT / "security" / "activity.py")
activity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(activity)

SITE, RELAY = "https://chat.impf.ai", "https://chat-api.impf.ai"
TOKEN = "export-token-0123456789abcdef"


def stats(first: str, last: str, *, today: str = "2026-11-25", ledger_first: str = "2026-11-20") -> dict:
    """The ledger's counts over a stretch, as the site answers them: a visitor a day and one who is there every day."""
    days = [(date.fromisoformat(first).toordinal() + i) for i in range(date.fromisoformat(last).toordinal() - date.fromisoformat(first).toordinal() + 1)]
    n = len(days)
    return {
        "v": 1, "from": first, "to": last, "asOf": today, "first_day": ledger_first, "days": [date.fromordinal(d).isoformat() for d in days],
        "totals": {"visitors": n + 1, "new_visitors": n, "returning_visitors": 1, "visits": 2 * n, "page_views": 3 * n, "questions": 5 * n, "questions_archived": 2 * n,
                   "questions_unarchived": 3 * n, "model_calls": 9 * n, "tokens_in": 1000 * n, "tokens_out": 100 * n, "countries": 3, "regions": 2},
        "lifetime": {"visitors": 40, "unconfirmed": 2, "removed": 0},
        "daily": {"active": [2] * n, "page_views": [3] * n, "questions": [5] * n},
        "questions": {"by_basis": [["relay", 4 * n], ["client", n]], "by_model": [["impf", "Tao-R1", 4 * n]]},
        "models": {"calls": [["Tao-R1", 9 * n]]},
        "places": [{"country": "CN", "region": "GD", "visitors": 5, "page_views": 2 * n, "questions": 4 * n},
                   {"country": "SG", "region": "", "visitors": 2, "page_views": n, "questions": n},
                   {"country": "IS", "region": "", "visitors": 1, "page_views": 1, "questions": 0}],
        "retention": {"weekly": [], "d1": {"cohort": 4, "back": 1}},
        "features": {"tools": [["classics.search", 7 * n]]},
        "audience": {"browsers": [["Chrome", 3 * n]], "referrers": [["https://www.baidu.com", 9], ["https://intranet.hospital.example", 1]]},
        "sessions": {"count": 2 * n, "seconds": 600 * n, "median_s": 240},
        "security": {"classes": [["human", 30 * n]]},
        "coverage": {"page_ready": 3 * n, "pending_days": 0},
    }


class Site:
    """The Workers' answers.  health: what each says of its ledger; archive: what a day's check says."""

    def __init__(self, *, today: str = "2026-11-25", ledger: bool = True, health: dict | None = None, archive: dict | None = None, usage: bool = True) -> None:
        self.today, self.ledger, self.asked, self.usage = today, ledger, [], usage
        self.health = health or {}
        self.archive = archive

    def __call__(self, url: str, *, token: str | None = None, timeout: float = 90):
        u = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        self.asked.append((u.netloc, u.path, q, token))
        if u.path == "/api/activity/stats":
            if not self.ledger:
                return 404, {"error": "这里没有活动账本", "ledger": False}
            last = min(q.get("to", self.today), self.today)
            return 200, stats(q.get("from", "2026-11-20"), last, today=self.today)
        if u.path in ("/api/activity/health", "/v1/activity/health"):
            name = "site" if u.path.startswith("/api") else "relay"
            base = {"waiting": 0, "oldest_seconds": 0, "dropped": 0, "lost": 0, "duplicates": 0, "d1_failures": 0, "r2_failures": 0}
            body = {"v": 1, name: {**base, **self.health.get(name, {})}}
            if name == "site":
                body.update({"archive": self.archive is not None, "registry": {"visitors": 40}})
            return 200, body
        if u.path == "/api/activity/archive":
            return 200, {"v": 1, "day": q["day"], "sources": self.archive}
        if u.path in ("/api/stats", "/v1/stats"):
            if not self.usage:
                return 401, {"error": "需要收集令牌"}
            days = ["2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20"]
            kinds = {"view": [30, 40, 50, 60], "visitor": [10, 25, 20, 30]} if u.path == "/api/stats" else {"question": [8, 9, 0, 11], "call": [40, 45, 0, 50], "asker": [4, 5, 0, 6]}
            # each Worker its own kinds, by place over the days asked (a visitor one day in Iceland; two who asked in Singapore)
            places = ([{"country": "CN", "region": "GD", "view": 150, "visitor": 70}, {"country": "IS", "region": "", "view": 2, "visitor": 1}] if u.path == "/api/stats"
                      else [{"country": "CN", "region": "GD", "question": 25, "call": 120, "asker": 12}, {"country": "SG", "region": "", "question": 3, "call": 9, "asker": 2}])
            return 200, {"v": 1, "asOf": self.today, "offset": 8, "days": days, "daily": kinds, "places": places}
        raise AssertionError(f"not asked for: {url}")


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("LOG_EXPORT_TOKEN", TOKEN)
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_days_not_yet_kept_are_reported_with_the_week_the_month_and_the_year_asked_as_a_whole(monkeypatch, tmp_path, env):
    site = Site()
    monkeypatch.setattr(activity, "_request", site)
    out = activity.report(SITE, tmp_path)
    assert out == {"new": 11, "ledger": 1, "days": 5, "through": "2026-11-24"}  # the 20th to the 24th; two weeks, a month, a year, the lifetime, the summary
    assert all(token == TOKEN and host == "chat.impf.ai" for host, _, _, token in site.asked)  # the collector's token, to the site alone
    day = read(tmp_path / "daily" / "2026" / "11" / "22.json")
    assert (day["kind"], day["period"], day["complete"], day["backfill"]) == ("daily", {"label": "2026-11-22", "from": "2026-11-22", "to": "2026-11-22"}, True, None)
    assert day["ledger"]["totals"]["questions_unarchived"] == 3 and "days" not in day["ledger"]
    # a week is asked for as a whole, never added up from its days: the 20th to the 22nd of the week of the 16th
    week = read(tmp_path / "weekly" / "2026-W47.json")
    assert (week["period"], week["complete"]) == ({"label": "2026-W47", "from": "2026-11-16", "to": "2026-11-22"}, True)
    assert (week["ledger"]["from"], week["ledger"]["to"], week["ledger"]["totals"]["visitors"]) == ("2026-11-20", "2026-11-22", 4)
    assert week["ledger"]["daily"]["active"] == [2, 2, 2] and len(week["ledger"]["days"]) == 3
    this = read(tmp_path / "weekly" / "2026-W48.json")
    assert (this["complete"], this["ledger"]["to"]) == (False, "2026-11-24")  # not over: to yesterday
    assert read(tmp_path / "monthly" / "2026-11.json")["ledger"]["totals"]["visitors"] == 6
    assert read(tmp_path / "yearly" / "2026.json")["period"]["to"] == "2026-12-31"
    life = read(tmp_path / "lifetime.json")
    assert (life["kind"], life["period"]["to"], life["ledger"]["lifetime"]["visitors"]) == ("lifetime", "2026-11-24", 40)
    # the same again: nothing new is asked for but today's probe, and nothing is written
    site.asked.clear()
    assert activity.report(SITE, tmp_path) == {"new": 0, "ledger": 1, "days": 0, "through": "2026-11-24"}
    assert len(site.asked) == 1
    # the next day: that day, its week, month and year, and the lifetime
    later = Site(today="2026-11-26")
    monkeypatch.setattr(activity, "_request", later)
    assert activity.report(SITE, tmp_path)["days"] == 1
    # (the month, the year and the summary's last 7 and 30 days from the ledger's first day: there is nothing of it
    # before), the lifetime, and the summary's yesterday
    assert sorted(q.get("from", "all") + "…" + q["to"] for _, _, q, _ in later.asked[1:]) == [
        "2026-11-20…2026-11-25", "2026-11-20…2026-11-25", "2026-11-20…2026-11-25", "2026-11-20…2026-11-25", "2026-11-23…2026-11-25",
        "2026-11-25…2026-11-25", "2026-11-25…2026-11-25", "all…2026-11-25"]
    assert read(tmp_path / "weekly" / "2026-W48.json")["ledger"]["to"] == "2026-11-25"


def test_a_report_is_sums_nobody_can_be_picked_out_of(monkeypatch, tmp_path, env):
    monkeypatch.setattr(activity, "_request", Site())
    activity.report(SITE, tmp_path, least=3)
    month = read(tmp_path / "monthly" / "2026-11.json")["ledger"]
    assert month["places"] == [{"country": "CN", "region": "GD", "visitors": 5, "page_views": 10, "questions": 20},
                               {"country": "", "region": "", "folded": 2, "visitors": 3, "page_views": 6, "questions": 5}]
    assert month["audience"]["referrers"] == [["https://www.baidu.com", 9], ["", 1]]  # a site one visitor came from is not named
    text = json.dumps(read(tmp_path / "lifetime.json"))
    assert "hospital" not in text and '"IS"' not in text and "v_" not in text
    assert month["totals"]["countries"] == 3  # how many there were is said; which the small ones were is not
    # with a least of one, everything is named (the owner's choice)
    activity.report(SITE, tmp_path, least=1, day="2026-11-22")
    assert len(read(tmp_path / "daily" / "2026" / "11" / "22.json")["ledger"]["places"]) == 3


def test_a_run_that_did_not_happen_is_caught_up_and_a_site_without_a_ledger_is_passed_over(monkeypatch, tmp_path, env, capsys):
    monkeypatch.setattr(activity, "_request", Site(today="2027-02-01"))
    out = activity.report(SITE, tmp_path)
    assert (out["days"], out["through"]) == (31, "2027-01-31")  # no further back than a month
    assert not (tmp_path / "daily" / "2026").exists()
    # without a ledger (or before its first day is over) the summary is the Workers' daily counts, and nothing else is written
    monkeypatch.setattr(activity, "_request", Site(ledger=False))
    assert activity.report(SITE, tmp_path / "none") == {"new": 1, "ledger": 0}
    assert "::notice::the site has no activity ledger" in capsys.readouterr().out
    assert [f.name for f in (tmp_path / "none").iterdir()] == ["SUMMARY.md"]
    monkeypatch.setattr(activity, "_request", Site(ledger=False, usage=False))  # nor any daily counts: nothing at all
    assert activity.report(SITE, tmp_path / "nothing") == {"new": 0, "ledger": 0}
    assert not (tmp_path / "nothing").exists()
    monkeypatch.setattr(activity, "_request", Site(today="2026-11-20"))  # its first day is not over
    assert activity.report(SITE, tmp_path / "early") == {"new": 1, "ledger": 1}
    assert [f.name for f in (tmp_path / "early").iterdir()] == ["SUMMARY.md"]
    monkeypatch.delenv("LOG_EXPORT_TOKEN")
    with pytest.raises(SystemExit, match="LOG_EXPORT_TOKEN"):
        activity.report(SITE, tmp_path)


def test_the_week_the_month_and_the_year_of_a_day():
    p = activity.periods(date(2026, 11, 25))
    assert p == {"weekly": ("2026-W48", date(2026, 11, 23), date(2026, 11, 29)), "monthly": ("2026-11", date(2026, 11, 1), date(2026, 11, 30)),
                 "yearly": ("2026", date(2026, 1, 1), date(2026, 12, 31))}
    assert activity.periods(date(2027, 1, 1))["weekly"] == ("2026-W53", date(2026, 12, 28), date(2027, 1, 3))  # the week belongs to the year most of it is in
    assert activity.periods(date(2028, 2, 29))["monthly"] == ("2028-02", date(2028, 2, 1), date(2028, 2, 29))
    assert activity.reader_day("2026-11-24T16:30:00Z") == "2026-11-25" and activity.reader_day("2026-11-24T15:59:59+00:00") == "2026-11-24"
    assert activity.reader_day("nonsense") is None


def test_the_pipeline_is_checked_and_what_is_wrong_ends_the_run(monkeypatch, tmp_path, env, capsys):
    now = datetime(2026, 11, 25, 2, 0, tzinfo=timezone.utc)
    ok = Site(archive={"site": {"ok": True}, "relay": {"ok": None}})
    monkeypatch.setattr(activity, "_request", ok)
    activity.report(SITE, tmp_path)
    result = activity.validate(SITE, RELAY, tmp_path, now=now)
    assert (result["errors"], result["warnings"]) == ([], [])
    kept = read(tmp_path / "pipeline.json")
    assert kept["sources"]["lifetime"] == {"visitors": 40} and kept["archive"] == {"day": "2026-11-24", "site": True, "relay": None}
    assert ("chat.impf.ai", "/api/activity/archive", {"day": "2026-11-24"}, TOKEN) in ok.asked
    # an outbox nothing drains, events dropped and lost since the last look, an archive that does not match its manifest
    bad = Site(health={"site": {"waiting": 5000, "oldest_seconds": 5 * 3600, "dropped": 12, "d1_failures": 3}, "relay": {"lost": 4, "duplicates": 9}},
               archive={"site": {"ok": False, "missing": ["a", "b"], "mismatched": [], "unlisted": ["c"]}, "relay": {"ok": True}})
    monkeypatch.setattr(activity, "_request", bad)
    result = activity.validate(SITE, RELAY, tmp_path, now=now)
    said = capsys.readouterr().out
    assert len(result["errors"]) == 4 and len(result["warnings"]) == 1
    for word in ("::error::the site's outbox is not being drained: 5000 events wait, the oldest for 5 hours", "::error::the site's ledger dropped 12 events",
                 "::error::the relay's ledger lost 4 events", "2 missing, 0 changed, 1 unlisted", "::warning::the site's ledger had 3 more d1_failures"):
        assert word in said, word
    # the same counts at the next look are no news; the count of visitors there ever were never falls
    assert activity.validate(SITE, RELAY, tmp_path, now=now)["errors"] == [e for e in result["errors"] if "outbox" in e or "manifest" in e]
    life = read(tmp_path / "lifetime.json")
    life["ledger"]["lifetime"]["visitors"] = 12
    (tmp_path / "lifetime.json").write_text(json.dumps(life), encoding="utf-8")
    monkeypatch.setattr(activity, "_request", Site())
    assert any("fell from 40 to 12" in e for e in activity.validate(SITE, RELAY, tmp_path, now=now)["errors"])
    with pytest.raises(SystemExit):
        activity.main(["validate", "--site", SITE, "--relay", RELAY, "--out", str(tmp_path)])


def records(tmp_path: Path) -> Path:
    logs = tmp_path / "chat-logs"
    lines = {
        "2026/11/17": [
            {"n": 1, "received": "2026-11-17T03:00:00+00:00", "id": "m1", "conversation": "c1", "provider": "impf", "model": "MiniMax-M3", "status": "done", "rounds": 3,
             "usage": {"input": 9000, "output": 500}, "tools": [{"name": "classics.search"}, {"name": "classics__search"}, {"name": "Bad Name"}], "question": "不该出现", "answer": "也不该"},
            # taken up again: the same turn, its last record is the one that counts
            {"n": 2, "received": "2026-11-17T03:05:00+00:00", "id": "m1", "conversation": "c1", "provider": "impf", "model": "MiniMax-M3", "status": "done", "rounds": 5,
             "usage": {"input": 12000, "output": 900}, "tools": [{"name": "study.formula"}], "question": "不该出现"},
            {"n": 3, "received": "2026-11-17T20:00:00+00:00", "id": "m2", "conversation": "c2", "provider": "custom-l8x2", "model": "our-private-model", "status": "error", "rounds": 1,
             "tools": []},  # 04:00 on the 18th for its readers
            {"n": 4, "received": "2026-11-17T04:00:00+00:00", "kind": "feedback", "id": "m1", "conversation": "c1", "rating": "down", "comment": "不该出现"},
            "not json",
        ],
        "2026/11/18": [{"n": 5, "received": "2026-11-18T01:00:00+00:00", "id": "m3", "conversation": "c2", "provider": "fixed", "status": "done", "rounds": 0, "tools": []}],
    }
    for day, rows in lines.items():
        f = logs / f"{day}.jsonl"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("".join((r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)) + "\n" for r in rows), encoding="utf-8")
    return logs


def test_the_days_before_the_ledger_are_told_from_what_was_kept_of_them(monkeypatch, tmp_path, env):
    site = Site()
    monkeypatch.setattr(activity, "_request", site)
    out = tmp_path / "analytics"
    edge = tmp_path / "edge" / "2026" / "11"
    edge.mkdir(parents=True)
    (edge / "17.jsonl").write_text("\n".join(json.dumps(e) for e in [
        {"key": "tr:a", "kind": "traffic", "day": "2026-11-17", "host": "chat.impf.ai", "country": "CN", "status": 200, "requests": 900, "visits": 70},
        {"key": "tr:b", "kind": "traffic", "day": "2026-11-17", "host": "chat.impf.ai", "country": "US", "status": 403, "requests": 100},
        {"key": "fw:c", "kind": "firewall", "day": "2026-11-17", "clientIP": "203.0.113.9"}]) + "\n", encoding="utf-8")
    activity.report(SITE, out)  # the ledger's days: from the 20th
    done = activity.backfill(SITE, RELAY, out, records(tmp_path), tmp_path / "edge")
    assert done["days"] == 3 and done["first"] == "2026-11-17" and done["last"] == "2026-11-19" and done["sources"] == ["edge", "records", "usage"]
    assert [t for _, p, _, t in site.asked if p in ("/api/stats", "/v1/stats")] == [TOKEN] * 2  # the collector's token: the daily counts are the owner's
    d17 = read(out / "daily" / "2026" / "11" / "17.json")
    assert d17["ledger"] is None and d17["backfill"] == {
        "usage": {"page_views": 30, "visitor_days": 10, "questions_default_service": 8, "model_calls_default_service": 40, "asker_days": 4},
        "records": {"questions": 1, "by_provider": {"impf": 1}, "by_model": {"MiniMax-M3": 1}, "by_status": {"done": 1}, "model_calls": 5, "tokens_in": 12000, "tokens_out": 900,
                    "tool_calls": 1, "tools": {"study.formula": 1}, "feedback": {"down": 1}},
        "edge": {"requests": 1000, "visits": 70, "by_status": {"2xx": 900, "4xx": 100}}}
    d18 = read(out / "daily" / "2026" / "11" / "18.json")["backfill"]["records"]
    assert d18["by_provider"] == {"custom": 1, "fixed": 1} and "by_model" not in d18  # their own endpoint and model are their settings
    text = "".join(f.read_text(encoding="utf-8") for f in out.rglob("*.json"))
    for kept in ("不该", "our-private", "l8x2", "203.0.113", "c1", "m1"):
        assert kept not in text, kept
    # the 20th is the ledger's: what the Workers counted of it by the day is not put beside it
    assert read(out / "daily" / "2026" / "11" / "20.json")["backfill"] is None
    # the week of the 16th: the ledger's days as a whole, and the three days before it added up — the visitors between two numbers
    week = read(out / "weekly" / "2026-W47.json")
    assert week["ledger"]["from"] == "2026-11-20"
    assert week["backfill"]["days"] == 3 and week["backfill"]["usage"]["page_views"] == 120 and week["backfill"]["records"]["questions"] == 3
    assert week["backfill"]["visitors"] == {"at_least": 25, "at_most": 55}
    assert week["backfill"]["records"]["by_provider"] == {"impf": 1, "custom": 1, "fixed": 1}
    life = read(out / "lifetime.json")
    assert life["backfill"]["days"] == 3 and life["ledger"]["lifetime"]["visitors"] == 40
    # again: nothing changes; without the collector's token, from the records and the edge alone
    assert activity.backfill(SITE, RELAY, out, tmp_path / "chat-logs", tmp_path / "edge")["new"] == 0
    monkeypatch.delenv("LOG_EXPORT_TOKEN")
    alone = activity.backfill(SITE, RELAY, tmp_path / "alone", tmp_path / "chat-logs", tmp_path / "edge")
    assert alone["sources"] == ["edge", "records"] and alone["days"] == 2


def test_before_the_ledger_the_owners_summary_is_the_workers_daily_counts(monkeypatch, tmp_path, env):
    """No ledger yet: what the 统计 pane once showed, in the repository — the two Workers' daily counts, read with the
    collector's token, yesterday to all they keep; a visitor counted anew each day, and said so; a small place folded."""
    site = Site(ledger=False)
    monkeypatch.setattr(activity, "_request", site)
    step = tmp_path / "step.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(step))
    assert activity.report(SITE, tmp_path / "out", relay=RELAY) == {"new": 1, "ledger": 0}
    text = (tmp_path / "out" / "SUMMARY.md").read_text(encoding="utf-8")
    assert step.read_text(encoding="utf-8") == text
    assert {(host, path) for host, path, _, _ in site.asked} == {("chat.impf.ai", "/api/activity/stats"), ("chat.impf.ai", "/api/stats"), ("chat-api.impf.ai", "/v1/stats")}
    assert all(token == TOKEN for *_, token in site.asked)  # the collector's token: the counts are the owner's
    # through the 24th (today, the 25th, is not over): the counts reach the 20th, so yesterday has none
    assert "截至 2026-11-24" in text and "自 2026-11-17 起" in text
    for line in ("| 页面访问 | 0 | 150 | 180 | 180 |", "| 访客（逐日相加） | 0 | 75 | 85 | 85 |", "| 默认服务的提问 | 0 | 20 | 28 | 28 |",
                 "| 默认服务的模型调用 | 0 | 95 | 135 | 135 |", "| 提问的访客（逐日相加） | 0 | 11 | 15 | 15 |"):
        assert line in text, line
    assert "逐日相加的人次，不是不同的人" in text
    # the places of the last 30 days: both Workers' by place, the two small ones as "other"
    assert "| CN·GD | 150 | 70 | 25 |" in text and "| 其他 2 处 | 2 | 1 | 3 |" in text
    assert "IS" not in text and "SG" not in text
    # the same again: nothing changes
    assert activity.report(SITE, tmp_path / "out", relay=RELAY)["new"] == 0


def test_the_nightly_backfill_keeps_what_was_kept_and_closes_the_weeks_that_are_over(monkeypatch, tmp_path, env):
    monkeypatch.setattr(activity, "_request", Site(ledger=False))
    out = tmp_path / "analytics"
    activity.backfill(SITE, RELAY, out, records(tmp_path), tmp_path / "edge")
    kept = read(out / "daily" / "2026" / "11" / "17.json")["backfill"]["usage"]
    # a run that reads no daily counts (no token; or a year on, when the Workers no longer keep the day) loses none of them
    monkeypatch.delenv("LOG_EXPORT_TOKEN")
    assert activity.backfill(SITE, RELAY, out, tmp_path / "chat-logs", tmp_path / "edge")["new"] == 0
    assert read(out / "daily" / "2026" / "11" / "17.json")["backfill"]["usage"] == kept
    # a week kept while it ran is whole once it is over
    week = out / "weekly" / "2026-W47.json"
    week.write_text(json.dumps({**read(week), "complete": False}), encoding="utf-8")
    activity.backfill(SITE, RELAY, out, tmp_path / "chat-logs", tmp_path / "edge")
    assert read(week)["complete"] is True


def test_the_reports_are_written_only_when_they_change(tmp_path):
    f = tmp_path / "a" / "b.json"
    assert activity._write(f, {"b": 1, "a": [1, 2]}) is True
    assert f.read_text(encoding="utf-8") == '{\n "a": [\n  1,\n  2\n ],\n "b": 1\n}\n'
    assert activity._write(f, {"a": [1, 2], "b": 1}) is False
    assert activity.fold([["a", 5], ["b", 1], ["c", 2]], 3) == [["a", 5], ["", 3]]
    assert activity.provider_of("custom-abc") == "custom" and activity.provider_of("DeepSeek!") == "other" and activity.provider_of(None) == "unknown"


def test_both_workers_run_the_ledger_alike():
    """The site gives a visitor an id and the relay reads the pass made from it: both must hold the same mode, the same
    lifetimes and the same day — each in its own wrangler.toml."""
    import tomllib

    site = tomllib.loads((ROOT / "cloud" / "site" / "wrangler.toml").read_text(encoding="utf-8"))["vars"]
    relay = tomllib.loads((ROOT / "relay" / "wrangler.toml").read_text(encoding="utf-8"))["vars"]
    names = ["ACTIVITY", "ACTIVITY_IDS", "VISITOR_DAYS", "ACTIVITY_EVENT_DAYS", "ACTIVITY_VISITOR_DAYS", "ACTIVITY_TURN_DAYS", "STATS_UTC_OFFSET"]
    assert {k: site.get(k) for k in names} == {k: relay.get(k) for k in names}
    assert site["ACTIVITY_IDS"] in ("notice", "optin", "off")
    # the key is a secret of the repository, never a value in a file; the registry is bound at deployment
    for text in ((ROOT / "cloud" / "site" / "wrangler.toml").read_text(encoding="utf-8"), (ROOT / "relay" / "wrangler.toml").read_text(encoding="utf-8")):
        assert "ACTIVITY_KEY =" not in text and "ACTIVITY_DB" not in text.replace("ACTIVITY_DB (security/bind-ledger.sh)", "")


def test_the_owners_summary_is_readable_and_names_no_one(monkeypatch, tmp_path, env):
    """SUMMARY.md, the owner's view in the repository (no page of the site shows the counts): yesterday, the last 7 and 30
    days and all time side by side, who came back, where from — sums only, the small places folded — and the same text
    on the run's own summary page."""
    step = tmp_path / "step.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(step))
    monkeypatch.setattr(activity, "_request", Site())
    activity.report(SITE, tmp_path / "out", least=3)
    text = (tmp_path / "out" / "SUMMARY.md").read_text(encoding="utf-8")
    assert step.read_text(encoding="utf-8") == text
    assert text.startswith("# 使用统计摘要\n") and "截至 2026-11-24" in text and "活动账本自 2026-11-20 起" in text and "网站的页面上不显示这些统计" in text
    assert "| 访客（整段时间去重） | 2 | 6 | 6 | 6 |" in text  # each stretch counted as a whole (the stand-in: a visitor a day and one every day)
    assert "| 　其中未存档 | 3（60%） |" in text and "| 有过的访客（含已删除） | — | — | — | 40 |" in text
    assert "首次来访后再来：第 1 天 25%（1/4）" in text
    assert "CN·GD 5，其他 2 处 3" in text  # Singapore's two visitors and Iceland's one: folded
    assert "IS" not in text and "hospital" not in text and "v_" not in text
    # nothing new: the summary is not written again
    assert activity.report(SITE, tmp_path / "out", least=3)["new"] == 0


def test_what_was_kept_is_read_whatever_its_words_hold(tmp_path):
    """A day of records or of the edge's events kept with U+2028, U+2029 or U+0085 inside a string (as the collectors
    once wrote them) is read by its line feeds alone: ``str.splitlines`` made several lines of such a record, and a
    piece that was JSON but no record (a number) ended the run."""
    ends = "\u0085\u2028\u2029"
    logs = tmp_path / "chat-logs" / "2026" / "11"
    logs.mkdir(parents=True)
    (logs / "17.jsonl").write_text(
        json.dumps({"n": 1, "received": "2026-11-17T03:00:00+00:00", "id": "m1", "conversation": "c1", "provider": "impf", "model": "MiniMax-M3", "status": "done",
                    "rounds": 2, "tools": [], "question": f"一行{ends}123{ends}又一行"}, ensure_ascii=False) + "\n123\n[1]\n", encoding="utf-8")
    assert activity.from_records(tmp_path / "chat-logs")["2026-11-17"]["questions"] == 1
    edge = tmp_path / "edge" / "2026" / "11"
    edge.mkdir(parents=True)
    (edge / "17.jsonl").write_text(
        json.dumps({"key": "tr:a", "kind": "traffic", "day": "2026-11-17", "host": f"chat.impf.ai{ends}7{ends}", "country": "CN", "status": 200, "requests": 900},
                   ensure_ascii=False) + "\n7\n", encoding="utf-8")
    assert activity.from_edge(tmp_path / "edge")["2026-11-17"]["requests"] == 900


def test_what_a_worker_answers_is_made_text_at_the_door(monkeypatch):
    """A lone surrogate (half a character) in an answer — JSON carries it, no file holds it — is U+FFFD from the door on."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Answer(BaseHTTPRequestHandler):
        def log_message(self, *a) -> None:
            pass

        def do_GET(self) -> None:
            raw = b'{"days": ["2026-11-17"], "place": "x\\ud800y", "k\\udfff": ["\\ud83d\\ude00", "\\ud83d"]}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Answer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        status, body = activity._request(f"http://127.0.0.1:{server.server_address[1]}/api/stats", token=TOKEN)
    finally:
        server.shutdown()
    assert status == 200 and body == {"days": ["2026-11-17"], "place": "x\ufffdy", "k\ufffd": ["\U0001f600", "\ufffd"]}  # a pair is its character
    json.dumps(body, ensure_ascii=False).encode("utf-8")  # and can be written


def test_the_sums_from_the_records_are_within_what_a_turn_can_be_and_named_by_no_senders_words(tmp_path):
    """A record is a visitor's to send (its Origin is all that is asked of one held with an own key).  Its numbers went
    into the kept sums as they were — one record of -1e308 rounds and 1e308 tokens made a day's sums, and the
    lifetime's, negative or 309 digits long — and its model and status, any words, became the names of counts."""
    logs = tmp_path / "chat-logs" / "2026" / "11"
    logs.mkdir(parents=True)
    rows = [
        {"n": 1, "received": "2026-11-17T03:00:00+00:00", "id": "m1", "conversation": "c1", "provider": "impf", "model": "MiniMax-M3", "status": "done", "rounds": 3,
         "usage": {"input": 9000, "output": 500}, "tools": [{"name": "classics.search"}]},
        {"n": 2, "received": "2026-11-17T03:01:00+00:00", "id": "m2", "conversation": "c2", "provider": "impf", "model": "any words a sender likes: 张三 13800138000",
         "status": "<b>x</b>|y", "rounds": -1e308, "usage": {"input": 1e308, "output": -1.5e300}, "tools": "not a list"},
        {"n": 3, "received": "2026-11-17T03:02:00+00:00", "id": "m3", "conversation": "c3", "provider": "custom-x", "status": 9, "rounds": True, "usage": [1],
         "tools": [7, {"name": 5}]},
        {"n": 4, "received": "2026-11-17T03:03:00+00:00", "id": "m4", "conversation": "c4", "provider": "impf", "model": "Tao-R1", "rounds": 1001,
         "usage": {"input": 10**9 + 1, "output": 10**9}},
        {"n": 5, "received": "2026-11-17T04:00:00+00:00", "kind": "feedback", "id": "m1", "conversation": "c1", "rating": "<script>"},
    ]
    (logs / "17.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    got = activity.from_records(tmp_path / "chat-logs")["2026-11-17"]
    assert (got["questions"], got["model_calls"], got["tokens_in"], got["tokens_out"], got["tool_calls"]) == (4, 3, 9000, 500 + 10**9, 3)
    assert got["by_model"] == {"MiniMax-M3": 1, "other": 1, "Tao-R1": 1} and got["by_status"] == {"done": 1, "other": 2, "unknown": 1}
    assert got["tools"] == {"classics.search": 1} and got["feedback"] == {"withdrawn": 1}
    assert activity._count(5.9, 10) == 5 and activity._count("5", 10) == 0 and activity._count(float("nan"), 10) == 0 and activity._count(None, 10) == 0


def test_a_name_in_the_summary_is_no_markup_of_its_senders(monkeypatch, tmp_path, env):
    """A referrer, a tool's or a model's name is a sender's to make, and the summary is Markdown that the committed file
    and the run's page render: a link under words of their choosing was written out as it came.  A name is a code span,
    with nothing in it that ends the span, the line or a cell."""
    link = "http://x <a href=https://evil.example>Token expired: sign in again</a>"
    assert activity._name(link) == f"`{link}`"
    assert activity._name("a`b|c\nd [x](https://evil.example)") == "`a b c d [x](https://evil.example)`"
    assert (activity._name(""), activity._name(None), activity._name("x" * 200)) == ("", "", "`" + "x" * 80 + "`")

    class Hostile(Site):
        def __call__(self, url: str, *, token: str | None = None, timeout: float = 90):
            status, body = super().__call__(url, token=token, timeout=timeout)
            if "audience" in body:
                body["audience"]["referrers"] = [[link, 9], ["[the stats moved](https://evil.example/login) `y`", 5]]
                body["questions"]["by_model"] = [["impf", "https://evil.example/model", 7]]
                body["features"]["tools"] = [["www.evil.example", 4]]
            return status, body

    monkeypatch.setattr(activity, "_request", Hostile())
    activity.report(SITE, tmp_path / "out", least=3)
    text = (tmp_path / "out" / "SUMMARY.md").read_text(encoding="utf-8")
    assert f"- 来源网站：`{link}` 9，`[the stats moved](https://evil.example/login) y` 5" in text
    assert "- 提问的模型：`https://evil.example/model` 7" in text and "- 工具：`www.evil.example` 4" in text
    for line in text.splitlines():  # outside a code span: no link, no tag, no bare address of theirs
        outside = "".join(line.split("`")[0::2])
        assert "evil.example" not in outside and "<a" not in outside, line
