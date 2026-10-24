"""The conversation records' numbers (taochronos.chat.records, ``taochronos records``) — from made-up records only."""

from __future__ import annotations

import json

from taochronos.chat.records import answer_after_tools, read, summary, whole
from taochronos.cli import main

QUESTION = "桂枝汤主治什么？"
ANSWER = "太阳中风，桂枝汤主之。[[a.1]]"


def timed(**kw):
    """A turn as a page that times it records it: a chart and a search in round 1 (the search waits 600 ms for its
    turn), then the answer — its reply begun 590 ms after it was asked for, its first text 1.41 s after that."""
    r = {
        "v": 1, "id": "m1", "conversation": "c1", "turn": 1, "started": "2026-10-23T08:00:00.000Z", "status": "done",
        "provider": "impf", "model": "Tao-R1", "question": QUESTION, "answer": ANSWER, "ms": 6100, "rounds": 2,
        "citations": {"total": 1, "ok": 1, "warn": 0, "bad": 0, "pending": 0},
        "requests": [
            {"round": 1, "attempt": 1, "sent": 10, "open": 300, "first": 320, "last": 900, "end": 905, "finish": "tool_calls"},
            {"round": 2, "attempt": 1, "sent": 2010, "open": 2600, "first": 2610, "text": 4010, "last": 6000, "end": 6005,
             "finish": "stop", "input": 1200, "output": 180},
        ],
        "tools": [
            {"name": "analysis.chart", "ok": True, "ms": 100, "round": 1, "status": "ok", "at": 905, "wait": 0},
            {"name": "classics.search", "ok": True, "ms": 1100, "round": 1, "status": "ok", "at": 906, "wait": 600},
        ],
        "events": [], "hidden": 0, "asleep": 0,
    }
    r.update(kw)
    return r


def old(**kw):
    """A turn as an older page recorded it: no times."""
    r = {"v": 1, "started": "2026-10-20T08:00:00Z", "status": "done", "provider": "impf", "question": QUESTION,
         "answer": ANSWER, "tools": [{"name": "classics.search", "ok": True, "ms": 80, "args": "{}"}],
         "citations": {"total": 2, "ok": 1, "warn": 1, "bad": 0, "pending": 0}}
    r.update(kw)
    return r


def test_the_time_from_the_last_tool_result_to_the_first_answer_text():
    assert answer_after_tools(timed()) == {"total": 2004, "before": 4, "reply": 590, "thinking": 1410}
    # the answer asked again after its first asking broke off before any text: that asking is counted before it
    stalled = timed(requests=[timed()["requests"][0],
                              {"round": 2, "attempt": 1, "sent": 2010, "open": 2100, "end": 3000, "failed": "unfinished"},
                              {"round": 2, "attempt": 2, "sent": 4000, "open": 4100, "first": 4100, "text": 4500, "end": 5000, "finish": "stop"}])
    assert answer_after_tools(stalled) == {"total": 2494, "before": 1994, "reply": 100, "thinking": 400}
    assert answer_after_tools(timed(tools=[])) is None  # no tools: nothing to wait after
    assert answer_after_tools(old()) is None  # an older record has no times


def test_a_whole_answer():
    assert whole(timed()) and whole(old())
    assert not whole(timed(error="回答在输出上限处被截断，续写后仍未写完。"))  # a notice under it
    assert not whole(timed(status="stopped")) and not whole(timed(answer=""))
    cut = timed()
    cut["requests"][-1]["finish"] = "length"
    assert not whole(cut)
    # a request that failed after the answer (a rewrite the turn took out): the answer that stands came whole
    after = timed()
    after["requests"].append({"round": 3, "attempt": 1, "sent": 6100, "end": 6200, "failed": "http 500"})
    assert whole(after)


def test_the_summary():
    broke_recovered = timed(requests=[
        {"round": 1, "attempt": 1, "sent": 10, "open": 50, "first": 60, "text": 80, "end": 9000, "failed": "timeout", "expired": "silence"},
        {"round": 1, "attempt": 2, "sent": 9100, "end": 9200, "failed": "network"},
        {"round": 1, "attempt": 3, "sent": 9500, "open": 9600, "first": 9610, "text": 9700, "end": 9900, "finish": "stop"}], tools=[])
    broke_lost = timed(status="error", error="Claude API 返回 529", answer="", requests=[  # the service failed: a kind of its own
        {"round": 1, "attempt": n, "sent": 10, "end": 20, "failed": "overloaded_error", "status": 529} for n in (1, 2, 3)], tools=[])
    refused = timed(status="error", error="今天的次数已用完", answer="", requests=[
        {"round": 1, "attempt": 1, "sent": 10, "end": 20, "failed": "daily_limit", "status": 429}], tools=[])
    stopped = timed(status="stopped", requests=[{"round": 1, "attempt": 1, "sent": 10, "end": 20, "failed": "stopped"}], tools=[])
    uncited = old(citations={"total": 0, "ok": 0, "warn": 0, "bad": 0, "pending": 0})
    flagged = old(citations={"total": 2, "ok": 1, "warn": 0, "bad": 1, "pending": 0})
    fixed = {"v": 1, "provider": "fixed", "status": "done", "question": "你是谁", "answer": "道乃久", "rounds": 0,
             "started": "2026-10-23T09:00:00Z"}
    hidden = timed(hidden=30000, asleep=120000)
    out = summary([timed(), broke_recovered, broke_lost, refused, stopped, old(), uncited, flagged, fixed, hidden])
    assert (out["turns"], out["timed"], out["fixed"]) == (9, 6, 1)
    assert out["answer_after_tools"]["total"] == {"n": 2, "p50": 2.0, "p90": 2.0, "p99": 2.0, "max": 2.0}
    assert out["answer_after_tools"]["reply"]["p50"] == 0.6 and out["answer_after_tools"]["thinking"]["p50"] == 1.4
    # of the two turns a model request broke off in, one still answered whole; the visitor's daily limit is not a break
    assert out["recovery"] == {"n": 1, "of": 2, "share": 0.5, "failed": {
        "overloaded_error 529": 3, "timeout:silence": 1, "network": 1, "daily_limit 429": 1}}
    assert out["completion"] == {
        "whole": {"n": 6, "of": 9, "share": 0.667}, "whole_unflagged": {"n": 5, "of": 9, "share": 0.556},
        "whole_verified": {"n": 3, "of": 9, "share": 0.333}, "whole_uncited": {"n": 1, "of": 9, "share": 0.111}}
    time = out["time"]
    assert time["tools"]["max"] == 1.1 and time["hidden"]["max"] == 30.0 and time["asleep"]["max"] == 120.0
    assert time["model"]["n"] == 6 and time["calls_waiting"] == 0.5  # of the calls' 1200 ms, the search waited 600
    # by the day the turn began
    assert summary([timed(), old()], since="2026-10-21")["turns"] == 1
    assert summary([timed(), old()], until="2026-10-21")["turns"] == 1


def test_the_command_reads_the_collected_days_and_says_no_word_of_them(tmp_path, capsys):
    day = tmp_path / "2026" / "10" / "23.jsonl"
    day.parent.mkdir(parents=True)
    day.write_text("\n".join([json.dumps({"n": 1, "received": "2026-10-23T08:00:07Z", **timed()}, ensure_ascii=False),
                              "not a record", json.dumps(old(), ensure_ascii=False)]) + "\n", encoding="utf-8")
    (tmp_path / "cursor.json").write_text('{"last": 1}', encoding="utf-8")
    assert [r["started"][:10] for r in read([tmp_path])] == ["2026-10-23", "2026-10-20"]
    assert main(["records", str(tmp_path)]) == 0
    printed = capsys.readouterr().out
    out = json.loads(printed)
    assert out["turns"] == 2 and out["timed"] == 1 and out["completion"]["whole"]["n"] == 2
    assert QUESTION not in printed and "桂枝" not in printed and "a.1" not in printed
    assert main(["records", str(tmp_path), "--since", "2026-10-21"]) == 0
    assert json.loads(capsys.readouterr().out)["turns"] == 1
