// @ts-check
// A module worker's first import: it holds the messages that come before the worker's handler is set, and gives them
// to it once it is.  A worker's own code runs only once everything it imports has run, and i18n.js waits for its
// dictionary (a top-level await) on every page but a Chinese one; meanwhile the messages the page sent arrive, and with
// no handler set yet they would be dropped (a page in English that never started).  Imported first, this module runs
// before anything waits, before any message can arrive.

/** @type {MessageEvent[]} */
const early = [];
self.onmessage = (e) => { early.push(e); };

/** The worker's handler, from now on: given first, in order, what came before it.
 * @param {(e: MessageEvent) => unknown} handler */
export function listen(handler) {
  self.onmessage = handler;
  for (const e of early.splice(0)) handler(e);
}
