// What the relay's Limiter object does with a request, in one round trip — apart from the object itself (index.js needs
// the Workers runtime) so that it runs under Node in the tests, which use this very code.
//
//   gateCall    a call the relay may let through: the sentinel sees the request (and may refuse it), then the counters;
//               a call that answers a visitor is told which turn it belongs to, and the turn's first call is its
//               question — counted once in the owner's daily counts (security/usage.js) and, where the Worker has the activity
//               ledger (security/ledger.js), written down with the model call it is
//   logged      anything else worth an event of the ledger: a request noted, a feedback, a sponsorship
//
// Which turn.  The page names a turn on every call of it (X-Tao-Turn), so its tool rounds, the self-check's rewrite, an
// answer written on at the output limit and the page asking again after a failure are the same question.  Before this,
// a question was "a call that ends with a user's message" — which the self-check's note and the note that asks an
// answer to be written on both are, and so is the same call made again: each was counted as a question more.

import { envelope } from "../../security/ledger.js";
import { WatchCore } from "../../security/sentinel.js";
import { ANSWERS } from "./state.js";

/** Did the sentinel write an event for this request (security/sentinel.js: WatchCore.record)?  Then the archive drains. */
export const evented = (w, a, extra = {}) => Boolean(w && (w.flagged || w.blocked || w.shadow || a?.route === "honeypot" || extra.kind === "csp"));

/** The ledger's event of a request, from what the Worker read of it: {type, route, fp, a, status, visitor, offset,
 * flagScore, more} and the sentinel's word `w`. */
export const eventOf = (act, w, now, extra = {}) => envelope({ type: act.type || "request", source: "relay", fp: act.fp || {}, a: act.a || null, w, status: act.status ?? null,
  visitor: act.visitor || null, now, offset: act.offset ?? 8, route: act.route || null, latency: act.latency ?? null, flagScore: act.flagScore ?? 5,
  more: { ...(act.more || {}), ...extra } });

/**
 * stores: {core (LimiterCore), watch (WatchCore), usage (UsageCore), ledger (LedgerCore)}.  args: what the relay asks
 * (relay.js) — who, kind, limits, fp, a, shape, status, cfg, served, reserve, usage, question — and `activity`:
 *
 *   {key, explicit, turn, turnMs}                    which turn the call belongs to (a keyed digest of the page's name
 *                                                    for it, or of what was asked), whether the page named it, and
 *                                                    whether it ends with what a visitor asked
 *   {ledger: true, visitor, route, offset, flagScore, keep, more}   the Worker has the ledger: the call is written down
 *
 * → the counters' answer, with `watch` (the sentinel's word), `question` (this call is its turn's first), and, with the
 * ledger, `turn_id` and `invocation_id` for the call's outcome (relay.js: settle).
 */
export async function gateCall(stores, { who, kind, limits, fp, a, shape, status, cfg, served, reserve, usage, question, activity }, now = Date.now()) {
  const { core, watch: sentinel, usage: counts, ledger } = stores;
  const w = fp && a ? await sentinel.observe(fp, a, { shape, status }, cfg, now) : null;
  // (the request as the Worker read it: the sentinel's own reading, or — the sentinel off — the ledger's)
  const act = activity ? { ...activity, fp: fp || activity.fp, a } : null;
  const written = Boolean(act?.ledger && ledger);
  const refused = (out) => {
    // a call refused is an event too: by what (the day's limit, the minute's, the sentinel), and for whom
    if (written && ANSWERS.has(kind)) {
      ledger.append([eventOf({ ...act, type: "model_refused", status: out.reason === "blocked" || out.reason === "not_served" ? 403 : 429 }, w, now, { detail: out.reason })], now, act.keep);
    }
    return { ...out, watch: w };
  };
  if (w?.blocked) return refused({ ok: false, reason: "blocked", retry: w.retry });
  const keys = fp ? [await WatchCore.who(fp.ip, cfg, now), await WatchCore.who(fp.ip, cfg, now - 86400000)] : [];
  if (served && !(fp ? core.wasServed(keys, now) : core.served(who, served, now))) return { ok: false, reason: "not_served", retry: 0, watch: w };
  const q = question ? core.question(who, question, now) : null;
  if (q && !q.ok) return refused(q);
  const gate = core.hit(who, kind, limits, now, reserve);
  if (!gate.ok) return refused(gate);
  q?.commit?.();
  if (!ANSWERS.has(kind)) return { ...gate, watch: w };
  if (keys.length) core.markServed(keys[0], now);
  // the turn this call belongs to: its first call is its question
  let turn = { question: Boolean(usage?.turn) };
  if (act?.key && ledger) {
    try {
      turn = written ? ledger.call(eventOf(act, w, now), act, now, { turnMs: act.turnMs, keep: act.keep }) : ledger.asks(act, now, act.turnMs);
    } catch (err) {
      console.error("ledger", err?.name || "Error"); // never in a call's way
    }
  }
  if (usage && counts) {
    try { counts.call({ ...usage, turn: turn.question }, keys[0]); } catch (err) { console.error("usage", err?.name || "Error"); } // never in a call's way
  }
  return { ...gate, watch: w, question: turn.question, turn_id: turn.turn_id, invocation_id: turn.invocation_id };
}

/** An event of the ledger for something that is not a model call: act as eventOf takes it. */
export function logged(ledger, act, now = Date.now()) {
  if (!ledger || !act?.ledger) return;
  ledger.note(eventOf(act, act.w || null, now), now, act.keep);
}

/** A turn's end as the page tells it (POST /v1/activity), and a record taken in for a turn (POST /v1/logs): into the
 * ledger's outbox, with the event of the request that brought it.  cfg: ledgerConfig. */
export function turnFinished(ledger, act, key, info, now, cfg) {
  return ledger.finished(eventOf(act, act.w || null, now), key, info, now, { turnMs: cfg.turnDays * 86400000, offset: act.offset ?? 8, keep: cfg.keep });
}

export function turnRecorded(ledger, act, key, info, now, cfg) {
  return ledger.recorded(eventOf(act, act.w || null, now), key, info, now, { turnMs: cfg.turnDays * 86400000, offset: act.offset ?? 8, keep: cfg.keep });
}
