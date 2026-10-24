// How long a turn waits for each thing it waits on, each with a limit of its own — a search and a research run do not
// share one: the model's first reply, a streamed reply gone silent, a reply read whole, one tool call, a research run,
// one look at a research run on a server, and the turn itself.  A limit counts the time the page ran: a phone asleep or
// a tab the browser froze does not use one up.

/** The limits, in milliseconds (0: none). */
export const LIMITS = Object.freeze({
  firstReply: 120000, // a model's reply, to its first byte: a service answers at once, and streams while it thinks
  silence: 300000,    // a streamed reply that sends nothing more for this long has stalled (a model that thinks
                      // without showing it may say nothing for minutes)
  whole: 600000,      // a reply read whole (a browser that cannot read one as it arrives): it says nothing until it is done
  tool: 120000,       // a tool call, from when it runs: not while it waits for its runtime to load, or for its turn
  research: 1800000,  // a research run, from when it runs
  poll: 20000,        // one look at how a research run on a server is going
  offer: 20000,       // a round's tools waited on this long: the page offers to answer with what it has
  turn: 1800000,      // a turn: past this, no more tools run, and the model answers from what it has
});

// how often a limit looks at the clock, and the most of a gap between two looks it counts: a hidden tab's clock may be
// looked at only once a minute, and that minute counts; a longer gap is a page that did not run (a phone asleep, a tab
// the browser froze), and counts as no more than this
const TICK = 1000;
const MAX_GAP = 65000;

/** A limit of `ms` on a wait, counted in the time the page ran: `onExpire` is called once, when it is used up.  pause()
 * and resume(): time that does not count (a call waiting for its turn); restart(): the count begins again (a stream that
 * sent something); stop(): it ends.  `spent`: the time counted so far. */
export function limit(ms, onExpire) {
  const tick = Math.max(1, Math.min(TICK, ms));
  let spent = 0;
  let last = Date.now();
  let paused = false;
  let timer = null;
  const look = () => {
    const now = Date.now();
    if (!paused) spent += Math.min(now - last, MAX_GAP);
    last = now;
    if (spent >= ms) {
      clearInterval(timer);
      timer = null;
      onExpire();
    }
  };
  if (ms > 0 && Number.isFinite(ms)) timer = setInterval(look, tick);
  return {
    get spent() { return spent; },
    pause() { if (timer && !paused) { look(); paused = true; } },
    resume() { if (paused) { last = Date.now(); paused = false; } },
    restart() { spent = 0; last = Date.now(); },
    stop() { clearInterval(timer); timer = null; },
  };
}

/** A model request's limits: its first reply, then — once it streams — its silence (or, read whole, the time to read it).
 * `signal` ends the request when one of them is used up, or when the caller's `outer` signal ends it; `expired` names
 * the limit that did ("firstReply" | "silence" | "whole"), and `ms` what it was.  close() when the request is done.
 * `mark` (an object), when given, is told when the request was sent (`sent`), when its reply began (`open`), when its
 * first and its last part came (`first`, `last`), and the limit that ended it (`expired`): the page's clock, Date.now(). */
export function watch(outer, limits = {}, mark = null) {
  const lim = { ...LIMITS, ...limits };
  const ctl = new AbortController();
  let current = null;
  const stop = () => ctl.abort(outer.reason);
  const w = {
    signal: ctl.signal,
    expired: null,
    ms: 0,
    /** the request is sent: its first reply is waited for */
    sent() { if (mark) mark.sent = Date.now(); arm("firstReply"); },
    /** the reply has begun to stream: from now on, its silence */
    streaming() { if (mark) mark.open = Date.now(); arm("silence"); },
    /** the reply is read whole */
    whole() { if (mark) mark.open = Date.now(); arm("whole"); },
    /** something arrived */
    heard() {
      if (mark) mark.last = Date.now();
      if (mark && !mark.first) mark.first = mark.last;
      current?.restart();
    },
    close() {
      current?.stop();
      outer?.removeEventListener("abort", stop);
    },
  };
  const arm = (what) => {
    current?.stop();
    current = limit(lim[what], () => {
      w.expired = what;
      w.ms = lim[what];
      if (mark) mark.expired = what;
      ctl.abort();
    });
  };
  if (outer?.aborted) ctl.abort(outer.reason);
  else outer?.addEventListener("abort", stop, { once: true });
  return w;
}

/** From now until stop(): how long the page was hidden (its tab in the background, its screen off), and how long it did
 * not run at all (`asleep`: of each gap between two looks at its clock, what is past MAX_GAP — the time no limit counts).
 * stop() ends it and returns {hidden, asleep}, in milliseconds. */
export function pageClock() {
  const doc = globalThis.document;
  let hidden = 0;
  let asleep = 0;
  let last = Date.now();
  let since = doc?.visibilityState === "hidden" ? last : 0; // hidden since then
  const look = () => {
    const now = Date.now();
    asleep += Math.max(0, now - last - MAX_GAP);
    last = now;
  };
  const seen = () => {
    const now = Date.now();
    if (doc.visibilityState === "hidden") since ||= now;
    else if (since) { hidden += now - since; since = 0; }
  };
  const timer = setInterval(look, TICK);
  doc?.addEventListener("visibilitychange", seen);
  return {
    stop() {
      look();
      clearInterval(timer);
      doc?.removeEventListener("visibilitychange", seen);
      if (since) hidden += Date.now() - since;
      return { hidden, asleep };
    },
  };
}

/** A promise's result (or a value's), or an AbortError as soon as `signal` ends the wait (the promise itself goes on). */
export function until(promise, signal) {
  if (!signal) return promise;
  const waited = Promise.resolve(promise);
  if (signal.aborted) {
    waited.catch(() => {}); // nothing waits for it: its failure (a fetch given a stopped signal) is not left unhandled
    return Promise.reject(aborted());
  }
  return new Promise((resolve, reject) => {
    const stop = () => reject(aborted());
    signal.addEventListener("abort", stop, { once: true });
    waited.then(resolve, reject).finally(() => signal.removeEventListener("abort", stop));
  });
}

/** A wait that ends early when `signal` does. */
export function pause(ms, signal) {
  return new Promise((resolve) => {
    if (signal?.aborted) return resolve();
    const done = () => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", done);
      resolve();
    };
    const timer = setTimeout(done, ms);
    signal?.addEventListener("abort", done, { once: true });
  });
}

export const aborted = () => new DOMException("aborted", "AbortError");
