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
 * it ended on another (`was`; `now`: the one it ended on), and how long the page was hidden or did not run.  Never a
 * request's or a result's content: a call's arguments are kept as the records always kept them, shortened. */
export function timings({ started, trace, was, now, hidden, asleep }) {
  const at = (t) => (Number.isFinite(t) ? Math.max(0, Math.round(t - started)) : undefined);
  return {
    requests: trace.requests.slice(0, 48).map((q) => ({
      round: q.round, attempt: q.attempt, sent: at(q.sent), open: at(q.open), first: at(q.first), text: at(q.text),
      last: at(q.last), end: at(q.end), finish: q.finish, failed: q.failed, expired: q.expired, status: q.status,
      input: q.input, output: q.output,
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
