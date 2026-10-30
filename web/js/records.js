// Conversation records for the test period of 道乃久默认服务: one compact record per finished turn, sent to the site's
// relay only after the visitor agreed; the repository collects them (relay/README.md).  The visitor's choice is kept in
// this browser; a new version of the notice asks again.  A record says where its turn's time went (timings).

import { AGENT, PUBLISHER, PUBLISHER_EN } from "./brand.js";
import { storage, truncate } from "./util.js";
import { T } from "./i18n.js";

const KEY = "tc.consent";
const VERSION = 1;

export const NOTICE = [
  T`测试期间，${AGENT}会把你的对话——问题、回答、用到的工具和引文核对结果——记录到${PUBLISHER}（${PUBLISHER_EN}）的服务器，只用于测试和改进${AGENT}。`,
  T("不记录 API Key、设置和你的网络地址。请不要输入姓名、联系方式、病历等个人信息。"),
];

/** true (agreed), false (declined) or null (not asked yet, or asked under an older notice). */
export function consent() {
  const c = storage.get(KEY);
  return c && c.v === VERSION ? Boolean(c.logs) : null;
}

export function setConsent(logs) {
  storage.set(KEY, { v: VERSION, logs: Boolean(logs), at: new Date().toISOString() });
}

/** Where a turn's time went, as its record carries it, each time in milliseconds from the turn's start (`started`): its
 * model requests and tool calls (agent.js, runTurn's trace), what happened between them, the runtime it began on when
 * it ended on another (`was`; `now`: the one it ended on), and how long the page was hidden or did not run — in the
 * turn, and while each model request was asked (`hidden`, `asleep`: milliseconds, not times).  Never a request's or a
 * result's content: a call's arguments are kept as the records always kept them, shortened. */
export function timings({ started, trace, was, now, hidden, asleep }) {
  const at = (t) => (Number.isFinite(t) ? Math.max(0, Math.round(t - started)) : undefined);
  return {
    requests: trace.requests.slice(0, 48).map((q) => ({
      round: q.round, attempt: q.attempt, sent: at(q.sent), open: at(q.open), first: at(q.first), text: at(q.text),
      last: at(q.last), end: at(q.end), finish: q.finish, failed: q.failed, expired: q.expired, status: q.status,
      input: q.input, output: q.output, hidden: q.hidden, asleep: q.asleep,
    })),
    tools: trace.tools.slice(0, 40).map((c) => ({
      name: c.name, ok: c.status === "ok", ms: c.end ? c.end - c.start : undefined, args: truncate(JSON.stringify(c.args ?? {}), 300),
      id: c.id, round: c.round, status: c.status, at: at(c.start),
      wait: c.waiting ? (c.run || c.end || c.waiting) - c.start : 0, // for the runtime to load, or for its turn
      compute: c.compute,
    })),
    events: trace.events.slice(0, 40).map((e) => ({ at: at(e.at), what: e.what })),
    hidden: Math.round(hidden), asleep: Math.round(asleep),
    was: was && (was.runtime !== now.runtime || was.corpus !== now.corpus) ? was : undefined,
  };
}

/** What a visitor may tick when they rate an answer, under 👍 and under 👎: short words (the relay keeps only such words,
 * and `taochronos records` counts them without reading what anyone wrote), shown in plain words. */
export const REASONS = {
  up: [["accurate", T("内容准确")], ["sourced", T("引文可靠、出处清楚")], ["clear", T("条理清楚")], ["thorough", T("资料全面")],
    ["insight", T("有新的发现")]],
  down: [["citation", T("引文有误或查无出处")], ["inaccurate", T("内容不准确")], ["incomplete", T("回答不完整")],
    ["off_topic", T("没有回答我的问题")], ["slow", T("太慢")], ["other", T("其他")]],
};

/** A visitor's feedback on a turn, as the relay keeps it (relay/src/relay.js, normalizeFeedback): which turn — its message
 * and conversation, as the turn's own record names them —, the rating ("up", "down", or null: taken back), the reasons
 * ticked, what they wrote, and whether the turn was recorded (its record then holds the question and answer).  The
 * question and answer go with it only when the visitor chose to attach them (`attach`: {question, answer}).  Sent only
 * when the visitor submits it, whether or not they agreed to their turns being recorded: it is an act of its own. */
export function feedbackRecord({ conv, msg, rating, reasons = [], comment = "", attach = null, runtime = {}, now = new Date() }) {
  const idx = conv.messages.indexOf(msg);
  const record = {
    v: 1, kind: "feedback", id: msg.id, conversation: conv.id, turn: conv.messages.slice(0, idx).filter((m) => m.role === "user").length,
    rating, given: now.toISOString(), model: msg.model, provider: msg.provider, runtime: runtime.runtime, corpus: runtime.corpus, app: runtime.app,
  };
  if (rating) {
    Object.assign(record, { reasons: [...reasons], comment: comment.trim().slice(0, 2000) || undefined, recorded: msg.recorded === true || undefined });
    if (attach) Object.assign(record, { question: String(attach.question || "").slice(0, 4000), answer: String(attach.answer || "").slice(0, 12000) });
  }
  return record;
}
