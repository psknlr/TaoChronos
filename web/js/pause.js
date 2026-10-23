// A model service that refused with a time to come back (Retry-After) the turn did not wait for — a visitor's free calls
// for the day used up, a limit per minute longer than a turn waits (agent.js, retryWait), an address held back a while —
// is paused until then: no question, 继续作答 or 重试 is sent to it before, and the page says until when, rather than
// meet each with the same refusal.  Another service (one's own API Key) is not paused by it.  The pauses are kept in
// this browser, so a reload does not ask again either.

import { LOCALE, T } from "./i18n.js";
import { storage, truncate } from "./util.js";

const KEY = "tc.pause";
const LONGEST = 24 * 3600; // seconds: no pause lasts longer, whatever a service asks

let held = null; // by the provider's id: {until (ms since the epoch), message (the refusal, as the turn showed it)}

/** The time before which the service that refused with `err` is not asked again (ms since the epoch), or null: only a
 * refusal that says when to come back (`retryAfter`, seconds) pauses one. */
export function pauseUntil(err, now = Date.now()) {
  const s = Number(err?.retryAfter);
  return s > 0 ? now + Math.min(s, LONGEST) * 1000 : null;
}

/** The pauses in effect, by provider id; those ended are dropped. */
function current(now) {
  if (!held) {
    const kept = storage.get(KEY, null);
    held = kept && typeof kept === "object" && !Array.isArray(kept) ? kept : {};
  }
  let ended = false;
  for (const [id, p] of Object.entries(held)) {
    if (!(Number(p?.until) > now)) { delete held[id]; ended = true; }
  }
  if (ended) Object.keys(held).length ? storage.set(KEY, held) : storage.remove(KEY);
  return held;
}

/** Pause the provider `id` after its refusal `err`, which the turn showed as `message`.  Returns the pause, or null when
 * the refusal did not say when to come back. */
export function pause(id, err, message, now = Date.now()) {
  const until = pauseUntil(err, now);
  if (!until) return null;
  const all = current(now);
  all[id] = { until, message: String(message || "") };
  storage.set(KEY, all);
  return all[id];
}

/** The pause of the provider `id` while it lasts, or null. */
export const pausedNow = (id, now = Date.now()) => current(now)[id] || null;

/** When a pause ends, as a visitor reads it: the time, and the day when it is not today. */
export function untilText(until, now = Date.now()) {
  const end = new Date(until);
  const today = end.toDateString() === new Date(now).toDateString();
  return end.toLocaleString(LOCALE, { ...(today ? {} : { month: "numeric", day: "numeric" }), hour: "2-digit", minute: "2-digit" });
}

/** What the page says of a pause: until when, and the refusal in the service's words (the turn's notice has them whole). */
export const pauseText = (p, now = Date.now()) => T`暂停到 ${untilText(p.until, now)}，不再发送请求：${truncate(p.message, 200)}`;
