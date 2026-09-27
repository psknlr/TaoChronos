# ADR 0011 — A web client: the conversation in the browser, the harness as its tools, every quotation checked

**Status:** accepted

## Context

TaoChronos was reached through a command line and a generated workspace page.  A conversational interface was asked
for — one like the chat products people already use, published on the repository's GitHub Pages, configured with the
user's own model key (MiniMax-M3 by default), and reaching every function of the harness.

Three constraints shaped it.  GitHub Pages serves static files only.  The full corpus (2 GB, built locally from sources
under their own licences) cannot be published.  And a chat model is exactly the kind of component the harness keeps at
arm's length: it recalls texts, sources and dates it was never shown, and states computed associations as findings.

## Decision

**The browser holds the conversation; the harness executes.**  The page runs the agent loop itself: it streams the
model's answer, runs the tools the model asks for, returns their results and repeats until the model answers.  The
model is the user's, called with their key straight from the browser (MiniMax allows the published origin) or through
the local server.  Nothing is hosted: no service stands between the user, the provider and the harness.

**One Python module behind two runtimes.**  `taochronos.chat` (in the app layer) exposes the harness as a chat model's
tools — catalog, call, passage, research, session, workflow — and runs unchanged in two places: in the browser under
Pyodide (CPython on WebAssembly, in a Web Worker, on the demonstration corpus) and on the user's machine under
`taochronos serve` (the full corpus when it has been built).  The site ships the package and its data as two
deterministic archives and, by default, a pinned Pyodide, so it depends on no other host.

**The chat model is an agent, not a user.**  It acts as an agent-principal actor with read and analysis permissions;
every call passes the scheduler (permission, schema, hooks, receipts).  It is never offered `kg.propose_change`, and
Code Mode only when the local server is started with `--code-mode`.  By default it sees fifteen tools and reaches the
other fifty-odd through a catalog and a generic call, which keeps its context small; results are trimmed evenly to a
budget, earlier turns' results further.  A research run is one tool call; on the server it runs in a background thread
(one at a time — a run installs its contract's guards harness-wide) and the page polls its progress.

**Quotations are checked, not trusted.**  The standing instructions ask for verbatim quotation of tool results with
`[[passage_id]]`.  The page then checks every citation against the corpus it is connected to: the quotation before it
matches the passage (directly, or after the harness's normalisation of scripts and variant forms); the passage exists
and a tool returned it; it exists but no tool returned it; it does not exist.  Each state is shown on the citation, and
the passage opens beside the answer with the quotation marked.

**Each provider's history is replayed as it was produced.**  MiniMax-M3's interleaved thinking requires the full
assistant message (content, `tool_calls`, `reasoning_details`) back; Claude's thinking blocks carry signatures.  Each turn
keeps its provider's exact messages and replays them to the same provider; another provider gets the turn without the
fields it does not know, and reasoning of earlier turns is not sent back to providers that reject it.  Streams are read
whether they arrive as increments or, as MiniMax's own examples read them, cumulatively.  Claude is called through the
official SDK with adaptive thinking and server-side refusal fallbacks, and no tool runs after a refusal or a `max_tokens`
cut.

**The local server is narrow.**  It binds to 127.0.0.1, answers only this machine's pages, the published client and
named origins (CORS with Private Network Access), checks the Host header against DNS rebinding, and forwards model
requests only to the hosts of the listed providers, keys passing through unstored and unlogged.

## Consequences

* The page works with no installation: open it, paste a key, ask.  Every tool also runs by hand in the tool console,
  so the functions are usable without any model.
* In the browser the corpus is the demonstration corpus.  The page, the model's instructions and the documentation say
  so; research on the full corpus goes through the local server.
* A citation the model invents is visible as such, and a misquotation is marked — the discipline the research engine
  applies to its own evidence now applies to a conversation.  The check is literal (after normalisation): an honest
  abridgement reads as a mismatch and sends the reader to the passage.
* Research inside the browser runs the deterministic procedures; a model for its judgement roles is a server option
  (`--llm`).
* Tests cover the runtime and server in Python, the client's pure logic under Node, and the page in Chromium against
  scripted MiniMax-style and Claude streams; the browser tests are skipped where Chromium is not installed.
