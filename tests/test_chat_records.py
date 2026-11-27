"""The conversation records' numbers (taochronos.chat.records, ``taochronos records``) — from made-up records only."""

from __future__ import annotations

import itertools
import json

from taochronos.chat.records import answer_after_tools, ratings, read, summary, whole
from taochronos.cli import main

QUESTION = "桂枝汤主治什么？"
ANSWER = "太阳中风，桂枝汤主之。[[a.1]]"
IDS = itertools.count(1)  # each made-up turn its own message


def timed(**kw):
    """A turn as a page that times it records it: a chart and a search in round 1 (the search waits 600 ms for its
    turn), then the answer — its reply begun 590 ms after it was asked for, its first text 1.41 s after that."""
    r = {
        "v": 1, "id": f"m{next(IDS)}", "conversation": "c1", "turn": 1, "started": "2026-10-23T08:00:00.000Z", "status": "done",
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
    # the self-check's rewrite, cut at the output limit, taken out: the answer before its note stands, and came whole
    taken = timed(events=[{"at": 6010, "what": "review"}, {"at": 9000, "what": "unchecked"}])
    taken["requests"].append({"round": 3, "attempt": 1, "sent": 6020, "end": 8900, "finish": "length"})
    assert whole(taken)
    assert not whole({**taken, "events": taken["events"][:1]})  # a rewrite that stands, cut: not whole


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
        "overloaded_error 529": 3, "timeout:silence": 1, "network": 1, "daily_limit 429": 1},
        "unseen": {"n": 0, "of": 0, "share": None}}  # no request timed by the page's own clock
    assert out["completion"] == {
        "whole": {"n": 6, "of": 9, "share": 0.667}, "whole_unflagged": {"n": 5, "of": 9, "share": 0.556},
        "whole_verified": {"n": 3, "of": 9, "share": 0.333}, "whole_uncited": {"n": 1, "of": 9, "share": 0.111}}
    time = out["time"]
    assert time["tools"]["max"] == 1.1 and time["hidden"]["max"] == 30.0 and time["asleep"]["max"] == 120.0
    assert time["model"]["n"] == 6 and time["calls_waiting"] == 0.5  # of the calls' 1200 ms, the search waited 600
    # by the day the turn began
    assert summary([timed(), old()], since="2026-10-21")["turns"] == 1
    assert summary([timed(), old()], until="2026-10-21")["turns"] == 1


def test_how_often_the_model_is_asked_again():
    """Of the model requests, those the page asked again; of those whose service said how many times it asked the model
    service itself, those it asked once; and the place each reply came from (ADR 0033)."""
    smooth = timed(requests=[
        {"round": 1, "attempt": 1, "sent": 10, "open": 300, "end": 905, "finish": "tool_calls", "asks": 1, "via": "direct"},
        {"round": 2, "attempt": 1, "sent": 2010, "open": 2600, "text": 4010, "end": 6005, "finish": "stop", "asks": 2, "via": "apac"}])
    rough = timed(requests=[
        {"round": 1, "attempt": 1, "sent": 10, "end": 46000, "failed": "upstream_timeout", "status": 504, "asks": 3},  # no reply: no place
        {"round": 1, "attempt": 2, "sent": 47500, "open": 49000, "text": 50000, "end": 60000, "finish": "stop", "asks": 1, "via": "apac"}])
    out = summary([smooth, rough, timed(), old()])  # (a page that does not say, and one that times nothing)
    assert out["asked_again"] == {
        "by_page": {"n": 1, "of": 6, "share": 0.167},              # one request of six was a second asking of its round
        "service_asked_once": {"n": 2, "of": 4, "share": 0.5},     # of the four that say: two took one ask of the model service
        "via": {"apac": 2, "direct": 1}}
    assert summary([old()])["asked_again"] == {"by_page": {"n": 0, "of": 0, "share": None},
                                               "service_asked_once": {"n": 0, "of": 0, "share": None}, "via": {}}


def test_the_requests_that_broke_off_while_the_page_was_not_seen():
    """A page that times each model request with its own clock says how long it was hidden, or not running, while each was
    asked: of the requests that broke off, those asked while no one could see the page may have been cut by the browser."""
    behind = timed(requests=[
        {"round": 1, "attempt": 1, "sent": 10, "open": 50, "first": 60, "last": 9000, "end": 9010, "failed": "network",
         "hidden": 4000, "asleep": 0},
        {"round": 1, "attempt": 2, "sent": 9100, "end": 9200, "failed": "network", "hidden": 0, "asleep": 0},
        {"round": 1, "attempt": 3, "sent": 9500, "end": 69500, "failed": "timeout", "expired": "firstReply", "hidden": 0,
         "asleep": 90000},
        {"round": 1, "attempt": 4, "sent": 70000, "open": 70100, "first": 70110, "text": 70200, "end": 70900, "finish": "stop",
         "hidden": 0, "asleep": 0}], tools=[])
    refused = timed(requests=[{"round": 1, "attempt": 1, "sent": 10, "end": 20, "failed": "daily_limit", "status": 429,
                               "hidden": 5, "asleep": 0}], tools=[])
    out = summary([behind, refused, timed()])
    assert out["recovery"]["unseen"] == {"n": 2, "of": 3, "share": 0.667}  # a refusal is no break


def test_a_turn_taken_up_again_counts_once_as_it_ended():
    # the turn's answer could not be had (the connection, three times), and the user took it up again (继续作答)
    first = timed(id="m-again", status="error", error="无法连接", answer="", requests=[
        {"round": 2, "attempt": n, "sent": 2010, "end": 2510, "failed": "network"} for n in (1, 2, 3)])
    again = timed(id="m-again", resumed=1, tools=[], hidden=0, asleep=0, requests=[
        {"round": 3, "attempt": 1, "sent": 5, "open": 400, "first": 410, "text": 800, "last": 1500, "end": 1505, "finish": "stop"}])
    out = summary([first, again, timed()])
    assert (out["turns"], out["timed"], out["resumed"]) == (2, 2, {"n": 1, "whole": 1})
    assert out["completion"]["whole"]["n"] == 2  # as it ended: whole
    assert out["recovery"] == {"n": 1, "of": 1, "share": 1.0, "failed": {"network": 3}, "unseen": {"n": 0, "of": 0, "share": None}}
    # each run is timed from its own start: no time from a tool result to an answer across them (the user's pause between
    # them is no wait of the page's), and the model's time in both adds up (1.5 s and 1.5 s)
    assert out["answer_after_tools"]["total"]["n"] == 1 and out["time"]["model"]["p50"] == 3.0
    assert summary([again])["resumed"] == {"n": 1, "whole": 1}  # its first record not collected (yet)


def rating(id, rating="down", **kw):
    """A visitor's feedback on a turn, as the relay keeps it (relay/src/relay.js, normalizeFeedback)."""
    r = {"v": 1, "kind": "feedback", "id": id, "conversation": "c1", "turn": 1, "rating": rating, "given": "2026-10-23T08:05:00.000Z",
         "provider": "impf", "model": "MiniMax-M3"}
    if rating:
        r["reasons"] = ["citation"] if rating == "down" else ["accurate"]
    r.update(kw)
    return r


def test_the_feedback_on_answers_is_counted_apart_from_the_turns():
    first, second, third = timed(), timed(), timed()
    feedback = [
        rating(first["id"], "down", reasons=["citation", "incomplete"], comment="引的不是这一条。", recorded=True),
        rating(first["id"], "up", reasons=["accurate", "sourced"], recorded=True),  # thought better of it: the last word stands
        rating(second["id"], "down", reasons=["citation"], question=QUESTION, answer=ANSWER),
        rating(third["id"], "up"),
        rating(third["id"], None),  # taken back
        rating("m-other", "down", reasons=["slow", "other"], conversation="c2", comment="  "),
    ]
    out = summary([first, second, third, *feedback])
    assert out["turns"] == 3 and out["completion"]["whole"] == {"n": 3, "of": 3, "share": 1.0}  # feedback is no turn
    assert out["feedback"] == {
        "rated": 3, "up": 1, "down": 2, "share_up": 0.333, "taken_back": 1,
        "reasons": {"up": {"accurate": 1, "sourced": 1}, "down": {"citation": 1, "slow": 1, "other": 1}},
        "commented": 0, "attached": 1, "recorded": 1}
    # by the day it was given
    assert ratings(feedback, since="2026-10-24")["rated"] == 0
    assert ratings([rating("m1", given="2026-10-20T00:00:00Z"), rating("m2")], until="2026-10-21")["rated"] == 1
    assert summary([])["feedback"] == {"rated": 0, "up": 0, "down": 0, "share_up": None, "taken_back": 0,
                                       "reasons": {"up": {}, "down": {}}, "commented": 0, "attached": 0, "recorded": 0}


def test_the_command_reads_the_collected_days_and_says_no_word_of_them(tmp_path, capsys):
    day = tmp_path / "2026" / "10" / "23.jsonl"
    day.parent.mkdir(parents=True)
    day.write_text("\n".join([json.dumps({"n": 1, "received": "2026-10-23T08:00:07Z", **timed()}, ensure_ascii=False),
                              "not a record", json.dumps(old(), ensure_ascii=False),
                              json.dumps({"n": 2, "received": "2026-10-23T08:05:01Z", **rating("m-x", comment="桂枝汤引错了")},
                                         ensure_ascii=False)]) + "\n", encoding="utf-8")
    (tmp_path / "cursor.json").write_text('{"last": 1}', encoding="utf-8")
    assert [r.get("kind") or r["started"][:10] for r in read([tmp_path])] == ["2026-10-23", "2026-10-20", "feedback"]
    assert main(["records", str(tmp_path)]) == 0
    printed = capsys.readouterr().out
    out = json.loads(printed)
    assert out["turns"] == 2 and out["timed"] == 1 and out["completion"]["whole"]["n"] == 2
    assert (out["feedback"]["down"], out["feedback"]["commented"]) == (1, 1)
    assert QUESTION not in printed and "桂枝" not in printed and "a.1" not in printed
    assert main(["records", str(tmp_path), "--since", "2026-10-21"]) == 0
    assert json.loads(capsys.readouterr().out)["turns"] == 1


def test_a_record_is_one_line_whatever_its_words_hold(tmp_path):
    """U+2028, U+2029 and U+0085 are ends of lines to ``str.splitlines`` and may be in a question or an answer: a day
    kept with them as they are (as the collector once wrote them) is read by its line feeds alone — the record whole,
    and nothing made of its pieces."""
    ends = "\u0085\u2028\u2029"
    day = tmp_path / "2026" / "10" / "23.jsonl"
    day.parent.mkdir(parents=True)
    answer = f"太阳中风{ends}{{}}{ends}123{ends}桂枝汤主之"  # a piece of it alone would be JSON: an object, a number
    day.write_text(json.dumps({"n": 1, "received": "2026-10-23T08:00:07Z", **timed(answer=answer)}, ensure_ascii=False) + "\n"
                   + "123\n[]\n" + json.dumps(old(), ensure_ascii=False) + "\n", encoding="utf-8")
    got = list(read([tmp_path]))
    assert len(got) == 2 and got[0]["answer"] == answer  # the record whole; the lines that are no record passed over
