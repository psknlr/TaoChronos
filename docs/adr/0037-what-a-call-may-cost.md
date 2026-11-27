# ADR 0037 — What a call may cost: every argument has a limit, checked beside the schema

**Status:** accepted · 2026-11-27 · amends [ADR 0016](0016-site-and-full-corpus-on-cloudflare.md) (what the full
corpus's server takes from a visitor) and [ADR 0011](0011-web-client.md) (the harness's tools as a conversation's)

## Context

The full corpus's server runs a tool for whoever asks: `POST /api/call` on chat.impf.ai needs no key, only an address
within its day's allowance (3,000 calls). A review of the server after the log collectors were repaired (2026-11-27)
put every tool's parameters to extremes — each number at 10⁹, 10¹⁸ and 10³⁰⁰, each text at the 256 KB the site lets a
request carry — and found that a tool's cost followed its arguments with nothing in between:

| Call | What it cost |
|---|---|
| `analysis.concept_drift` with `permutations: 10**18` | never ended; its thread went on after the caller had hung up, and each such request took a share of the processor from every other visitor for as long as the process lived |
| `study.stemma` / `study.variants` with `chapter: "(.+)+!"` | `chapter` was compiled as a regular expression and every heading searched with it; a pattern that backtracks holds the interpreter, so **no other request was answered** until the process was replaced |
| `study.argument`, `study.reuse` with a text of nested brackets | a pass over the whole text for each level of nesting: `study.reuse` took 47 s at 40,000 characters and 198 s at 80,000 |
| `graph.evidence`, `bridge.map` with 79,000 characters and no mark | each finding read its whole clause (`bridge.map`: 7 s), and an edge was looked for among all that leave its source (`graph.evidence`: over 25 s) |
| `classics.search` with `k: 200` | 15 s on the full corpus (0.2 s at `k: 50`): a search reads three times `k` deep on every route; at 10⁹, as deep as the corpus goes |
| `POST /api/research` with a list written as JSON text that spells half a character | the run's record could not be written; twenty such requests filled the queue with runs nobody would take, and no research run was accepted until the server was started anew |
| `POST /api/call` naming `taochronos_research` | a run made inside the request: beside the queue, and counted by the site as a call (3,000 a day) where a research run is counted apart (100) |
| every research run | its session — the whole state, and the copy its replay is checked against — stayed in memory for as long as the server ran (61 MB a run on the 要籍语料), and its log (20 MB) and artifacts (3 MB) on the disk; a question asked of the workflow left its workspace (170 KB) |
| one call that computes, within any limit | beside it a call that reads the store waited a whole switch interval of the interpreter (5 ms) at each of its reads: a search of 0.15 s took 44 s, `study.formula` 9.5 s |

None of it had happened in production.

## Decision

**1. Every argument of every tool has a limit, and a call outside one is refused before the tool runs.** A number has
a range, a text a length, a list a length. The limits are `ToolSpec.limits`, `{argument: {"minimum", "maximum"} |
{"maxLength"} | {"maxItems"}}`; `ToolSpec.checked` is the schema with them, and it is what the scheduler validates
against (whoever calls: a chat model, an agent's procedure, code in the sandbox) and what a chat model's arguments are
fitted to (`fit_arguments`). The refusal names the limit — `invalid arguments: $.k: 1000000000 > maximum 100 ·
classics.search takes: …` — so that a model asks again within it.

* **The defaults** (`kernel/tools.py`), for an argument whose tool says nothing: a text 20,000 characters, a list 60
  entries (its texts 20,000 each), a whole number 0–10,000, a number ±10⁹. The registry gives them to every tool it is
  handed, so a plugin's tool is bounded without knowing of any of this.
* **The mesh's own** (`tools/limits.py`), by the parameter's name and, where a tool uses a name otherwise, by the tool:
  a few times what the tool does by default where the number is work (`k` 1–100, `permutations` 0–999, `max_chars`
  to 120,000, `max_candidates` to 2,000, `clauses` to 60), generous where it only cuts what was worked out (`items` to
  1,000), years −5000…5000, shares 0…1. `analysis.link_prediction` keeps `k` to 5,000: the statistician ranks its
  hypotheses among the first 5,000.
* **Refused, not clamped.** A call that asks for 10⁹ hits and is answered with 100 has been answered a question it
  did not ask; the codebase already refuses a parameter a tool does not take for the same reason.
* **No part of what a model is shown.** The schema goes to model providers as it was: `minimum`, `maxLength` and
  `maxItems` are not words every provider's tool grammar takes, and a tool list one of them rejects is a conversation
  that cannot start. The limits are checked beside the schema, never sent with it.
* `validate` reads `maxLength` and `maxItems`, and a bound refuses what is no number (NaN, which Python reads from
  JSON text). A value whose form is repaired (`"1000"` for 1000) and which is only too large is said to be too large.

**2. Where the cost was a loop over the argument, the loop is bounded as well** — the limit is the first guard, not
the only one:

* **Notes** (`plugins/classics/notes.py`): notes are read inside notes to 32 levels (the corpus nests them two deep:
  of the 要籍语料's 168,278 passages, 45,587 have notes and 41 a note inside a note). The same result as before on
  every text of up to 8 characters over three kinds of brackets (6.7 million), on 300,000 random texts and on every
  passage of the 要籍语料; brackets nested 20,000 deep: 9.7 s → 0.02 s.
* **`chapter` is text.** Part of a heading, found as it is written, in either script, several apart by `|`. Every use
  in the documentation and the evaluations was a plain name; a heading with a bracket in it was no pattern at all.
* **The bridge reads around a finding**: 2,000 characters of its clause and of its sentence (a passage of the corpus is
  900 at the most, so the classics read as before). **An evidence graph finds an edge by its ends.**
* **What is kept is bounded by what it weighs**: the normaliser's memo by characters as well as entries, and no text
  over 2,000 characters; a runtime holds the four sessions last run or read and reads the others again from the store
  (read only: the contract's guards are a run's to install, not a reader's); a school's study asked with probes leaves
  no file; a taboo survey reads each book once.

**3. A research run is started in one place.** On a server other machines reach, `taochronos_research` is not made
inside `POST /api/call`: the page starts it with `POST /api/research`, where it waits its turn among twenty and is
counted as a run. A record that cannot be written neither ends the worker nor stays in the queue; what a run is asked
is made whole before it is kept, and a list or an object written as JSON text is read whole.

**4. A thread of the server gives the interpreter up often.** `ChatServer.serve_forever` sets the switch interval to
0.1 ms. Beside one call computing, the search above takes 1.4 s instead of 44 s and `study.formula` 0.5 s instead of
9.5 s; a thread alone gives the interpreter up to no one, so a server with one visitor is as fast as it was.

**5. What a run leaves on the corpus container goes with its record.** The container's disk is its image's (8 GB, the
store 2.3 of them) and nobody's to keep: it keeps the last 60 ended runs, and a run's log and artifacts are removed
with its record (`chat/cloud.py`; `ChatRuntime.forget_session`). A server of one's own keeps every session, as it
did. A question asked of the workflow in a conversation keeps no workspace anywhere (`engine.workflow.ask(keep=False)`),
and its report no longer names a folder of the server's disk.

## Consequences

* A call within the limits behaves as before: the same results (the searches' result hashes on the full corpus are
  compared before and after each deployment), the same schemas shown to a model.
* A call outside them fails where it used to work slowly: a search for more than 100 hits, a text of more than 20,000
  characters, a list of more than 60. The command line calls the study functions themselves and is not bounded.
* Measured after, every tool at the limits of each of its arguments in turn (1,941 calls on the demonstration corpus,
  1,941 on the 要籍语料 as a store): none ran over a minute, and what ran longest is a tool's own work with its default
  arguments (a taboo survey of every book: 16 s), not its arguments.
* The D1 backup, which answers only where there is no container, reads a call's form as before and keeps its own
  bounds (a search's `k` is at most 50 there, a study's result is one precomputed by its key): it is not changed.
* **What this does not bound**: a tool that is heavy by what it does (a collation, a survey of every book, a research
  run) costs what it costs each time it is asked within its limits, and the day's allowance of an address is the only
  bound on how often: one caller repeating such calls still takes its share of the processor from the others (a search
  beside it: ten times its time alone, measured as above). A bound on how many such calls run at once, or on the time
  an address's calls may take in a day, belongs to the server and the site's Worker and is not decided here. Nor is
  the cache of the claims read from the passages a search finds, which the store keeps (0.8 MB for the search of a new
  term) and only the corpus bounds.
