# ADR 0028 — Feedback on answers: the visitor's own act, kept with the records

**Status:** accepted · 2026-10-30

## Context

The test period's conversation records ([ADR 0012](0012-default-service-relay.md)) say what was asked, what was answered,
how its citations checked and where its time went — but not whether the answer served the person who asked.  The
citation checks catch a misquotation, not an answer that misses the question, leaves out the commentary that mattered, or
takes too long to be worth the wait.  Visitors of ChatGPT and Claude expect to say so under the answer: 👍 or 👎, and a few
words.

Two things constrain how.  Recording is opt-in, and a visitor who declined must not find their turns sent by another
door.  And a conversation that touches the visitor's own data (我的资料, [ADR 0022](0022-the-users-own-data.md)) is never
recorded, whatever they chose.

## Decision

1. **Under each answer, 👍 有帮助 and 👎 有问题**, beside 复制 — when the site's relay says it takes feedback (`/v1/health`,
   `feedback`; `FEEDBACK = "off"` takes the thumbs off the page).  Either opens a dialog: what was good, or what was
   wrong, as short reasons (several may be ticked), and a few words.  **Nothing is sent before 提交**; a dialog dismissed
   sends nothing.  The rating stays on the answer (kept with the conversation in the browser); pressed again, it is
   taken back.
2. **Feedback is its own consent.**  Submitting is an act of the visitor's, so it does not wait on the records' consent.
   What goes with it does: a turn already recorded is named by its ids (its record holds the question and answer);
   any other turn's question and answer go only when the visitor ticks 附上这一轮的问题和回答; a conversation that touches
   我的资料 sends no word of itself, and the dialog says so.  The dialog says where it goes and asks for no personal
   information.
3. **Reasons are short words**, the same under every language (`citation`, `inaccurate`, `incomplete`, `off_topic`,
   `slow`, `other`; `accurate`, `sourced`, `clear`, `thorough`, `insight`): what the visitors found wrong can be counted
   without reading what anyone wrote.
4. **The relay keeps it with the records** (`POST /v1/feedback`, `relay/src/relay.js`, `normalizeFeedback`): the known
   fields only — the turn's message and conversation ids (as its record has them), the rating (`up`, `down`, or `null`
   when taken back), the reasons, at most 2 000 characters of what was written, the question and answer when attached.
   It goes through the same intake as a record — the page's origins, the ten-second gate, the size limit, the sentinel
   (`route: feedback`), the counters — with limits of its own (`FEEDBACK_PER_MINUTE`, `FEEDBACK_PER_DAY`), and into the
   same book, so the hourly collector brings both into `data/chat-logs/` (`"kind": "feedback"`) and the archive takes both
   alike.  Unlike a record's, a feedback needs no recent conversation with the relay: a rating may come days after the
   turn, or be of a turn answered with the visitor's own key.  The visitor waits for it, so a feedback the relay could
   not keep is refused aloud (503), where a record is let go without a word.
5. **The last word on a turn stands.**  `taochronos records` counts the ratings apart from the turns (`feedback`: how
   many turns are rated, 👍 and 👎 and the share of 👍, the reasons under each, how many came with words, with the turn
   attached, or on a recorded turn) — never a word of what anyone wrote.

## Consequences

- No new store, workflow or secret: feedback travels and is kept as the records are, and `relay/collect.py` takes it
  unchanged.  A consumer of `data/chat-logs/` that reads each line as a turn must now pass over `"kind": "feedback"`
  (`taochronos.chat.records.read` yields both; `summary` keeps them apart).
- A visitor who declined the records can still send the institute a turn — but only by ticking a box under the words
  that say so, for that one turn.
- A feedback is joined to its turn by ids that mean something only in the visitor's browser; a turn that was not
  recorded and not attached is known by its rating and reasons alone.
- Retracting sends a feedback of its own (`rating: null`): what was sent before stays in the repository, and the
  summary counts the turn as unrated.
