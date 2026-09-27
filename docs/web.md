# 网页对话 — the web client

**Tao-R1**, TaoChronos's research model for the classics: a model of your choice that answers from the classics through
TaoChronos's tools, with every quotation checked against its source.  Published at
**https://psknlr.github.io/TaoChronos/**; the same page is served by `taochronos serve`, which brings all the books of
the full corpus into it ([接入全部古籍](#接入全部古籍)).

```
            browser                                         your machine (optional)
 ┌────────────────────────────────────┐                ┌──────────────────────────────┐
 │  web/  chat UI · agent loop        │  tool calls    │  taochronos serve            │
 │        citation checks             │ ─────────────► │  ChatRuntime (full corpus)   │
 │  worker.js  Pyodide + TaoChronos   │                │  /api/call · /api/research … │
 │        (demonstration corpus)      │                │  /api/llm  (model proxy)     │
 └──────────────┬─────────────────────┘                └──────────────┬───────────────┘
                │ your key, straight to the provider (or via /api/llm) │
                ▼                                                      ▼
        MiniMax-M3 (default) · DeepSeek · Qwen · Kimi · GLM · OpenRouter · Poe · LiteLLM · Claude · local models
```

The model holds the conversation; TaoChronos executes.  The browser runs the agent loop — it streams the model's
answer, runs the tools the model asks for, sends their results back, and repeats until the model answers.  The tools
run in one of two places, with the same Python module (`taochronos.chat`) behind both, so both answer alike:

| Runtime | Where | Corpus | Start |
|---|---|---|---|
| **浏览器内** (in the browser) | Pyodide (CPython on WebAssembly) in a Web Worker | the demonstration corpus: short excerpts of 23 works, unverified | nothing: the page loads it (about 14 MB, cached) |
| **本地服务 / 远程服务** (a TaoChronos server) | `taochronos serve` on your machine, or on another one with a token | the full corpus you built (`corpus ingest …`; this project's build: 966 books, 2.05 million passages, 123 million characters), else the demonstration corpus | `pip install -e . && taochronos serve` |

The full corpus is never part of the site: it is built from its sources on your machine, under their licences.

## Tao-R1

The assistant is called **Tao-R1** everywhere on the page — the model chip, each answer, the composer, exports.  Tao-R1
is TaoChronos (the tools, the evidence discipline, the quotation checks) over a general language model chosen under
**设置 → 模型** (default MiniMax-M3); that underlying model is named in the chip's tooltip, under each answer's line and in
the settings.  The standing instructions give the model the name and tell it to be plain about what it is: asked what it
is built on, it names TaoChronos and the underlying model (the page adds `底层语言模型：<model>（<provider>）` to the
instructions' 运行环境 section), and it claims no other identity.  `/api/info` reports the name as `assistant_name`.

## 接入全部古籍

The published site runs the demonstration corpus in the browser.  All the books — the full corpus — cannot be put on
the site: the store is about 2.2 GB (a published GitHub Pages site may be no larger than 1 GB; git refuses files over 100 MB), its sources come under
their own licences (some, such as 笈成, are provided by the user and may not be redistributed), and the project keeps no
bulk texts in git.  So the full corpus reaches the page through `taochronos serve`, wherever it runs:

1. **Build the corpus once** on the machine that will serve it — the commands under “接入全量语料” in the
   [README](../README.md#二快速开始) (`taochronos corpus fetch … && taochronos corpus ingest …`; `corpus status` counts
   what is in).
2. **Start the server**: `taochronos serve`.  It finds the store and uses the `full-corpus` profile; it counts the corpus
   before it answers, so the page connects at once.
3. **Connect**: on the page, **设置 → 运行环境 → 接入全部古籍 → 连接** (the address is `http://localhost:8765` by
   default).  Or open `http://localhost:8765` itself: the server serves the same page, already connected.

The browser remembers the server it connected to.  In **自动** mode the page uses, in order: the server that served it;
the server this browser last worked with, if it answers within a moment; TaoChronos in the browser.  So with the server
running, the page opens on the full corpus; without it, on the demonstration corpus, and it says which (the side
panel's status, the composer, the opening screen's “接入全部古籍”).  **指定的服务** always uses the server and reports
it when it is down; **浏览器内** never looks for one.

**On another machine** (a workstation, a server):

```bash
taochronos serve --host 0.0.0.0             # prints an access token and the address with it: http://host:8765/#token=…
taochronos serve --host 0.0.0.0 --token …   # or choose the token (also $TAOCHRONOS_TOKEN)
```

A server bound beyond 127.0.0.1 never runs without a token: every API request, the model proxy's included, must carry
it (`X-TC-Token`), compared in constant time.  Opening the printed address gives the page the token (the page keeps it
and removes it from the address); or enter the address and token under **设置 → 运行环境**.  The published page, served
over HTTPS, may reach `http://localhost` but not plain `http://` on another machine (mixed content): put the server
behind HTTPS (a reverse proxy), or use the server's own page.

**What the tools read on the full corpus.**  Outside a research run the scope is the whole store: `classics.search`,
`classics.get_passage`, the study, philology and validation tools read all of it; `classics.list_books` lists every
book (filter by words of the title or author, dynasty, category); `kg.claims` and `kg.neighbors` read the claims of the
passages that write the term (every written form of two characters or more; at most 400 passages per term, spread
evenly over time); the D1–D5 analyses read the working set — the passages the server has read so far — and
`taochronos_research` runs a whole study over its own scoped corpus.  A book often has several witnesses from different
sources (different `book_id`s); the model is told to say which one it quotes.  `validation.verify_quote` finds a
quotation in every witness whatever its punctuation: as written, by its runs of characters between marks, or — when it
runs across a witness's own marks — by its 3-grams, each candidate then checked character by character (a changed or
missing character is never accepted).

## Using it

1. Open the page, choose **设置 → 模型**, paste an API key.  The default is **MiniMax (mainland) · MiniMax-M3**
   (`https://api.minimax.cn/v1`); sixteen other providers are listed, from the harness's own presets
   (`taochronos llm presets`).  The key is kept in this browser's localStorage and sent only to the provider — or to your
   local server's proxy.
2. Ask.  The page shows the model's thinking (folded), each tool call (its family, arguments, what the model read, the
   passages it returned), and the answer.
3. Every `[[passage_id]]` in the answer becomes a chip, checked as soon as it appears:

   | Chip | Meaning |
   |---|---|
   | ✓ jade | the quotation before it (「…」) matches the passage word for word (punctuation and spacing aside; failing that, after the harness's own normalisation of scripts and variant forms, 繁→简 and 异体) |
   | ○ jade | the passage exists and a tool returned it in this conversation (no quotation to compare) |
   | ≠ ochre | the quotation does not match the passage: an abridgement, a paraphrase or a misquotation |
   | ? ochre | the passage exists, but no tool returned it in this conversation (the model recalled the id) |
   | ✕ red | there is no such passage in the corpus: a fabricated source, or one from another corpus |

   Clicking a chip opens the passage in the side panel with the quotation highlighted, in horizontal or vertical
   (竖排) reading, with its variants and notes.  A line under each answer counts the results.
4. The side panel: **证据** (every passage the conversation touched), **研究** (research runs: verdict, metrics,
   hypotheses with their supporting and contradicting quotations, the full report), **工具台** (every tool, with a form
   generated from its schema — no model needed).

Keyboard: Enter sends, Shift+Enter breaks the line (input methods are respected), Esc stops, Ctrl/⌘+K new
conversation, Ctrl/⌘+B the conversation list, Ctrl/⌘+J the side panel, `/` focuses the input.  Conversations are kept in
this browser (IndexedDB); **设置 → 数据** exports and imports them (JSON) or one as Markdown.

## What the model is offered

`taochronos.chat.catalog` turns the tool mesh into function schemas.  In **精选 + 目录** mode (the default) the model
sees fifteen tools directly — `classics.search`, `classics.get_passage`, `classics.list_books`, `kg.term`, `kg.claims`,
`study.formula`, `study.herb`, `study.term`, `study.concordance`, `study.commentaries`, `study.translate`,
`study.network`, `validation.verify_quote`, `audit.claim`, `modern.safety` — and reaches the others through
`taochronos_catalog` (families, tools, parameters) and `taochronos_call`.  In **全部工具** mode it sees every tool.
Either way it also has the engine: `taochronos_research` (a full multi-agent discovery run: contract → evidence →
D1–D5 → hypotheses → falsification → gates G0–G8), `taochronos_session` (its report, hypotheses, evidence) and
`taochronos_ask` (the V2 skill workflow).

The model acts as an agent-principal actor with read and analysis permissions only.  It is never offered
`kg.propose_change` (a proposal to canonical knowledge is a person's act) or Code Mode (`research.run_code`) unless the
local server is started with `--code-mode`.  Every call passes the scheduler's gauntlet (permission, schema, hooks,
receipts).  Results reach the model trimmed evenly to a budget (16 000 characters by default: long lists keep their
head and say how many were left out); results of earlier turns are shortened further.

The standing instructions (`taochronos.chat.prompt`) carry the harness's evidence discipline into the conversation:
quote only what a tool returned, verbatim, with its `[[passage_id]]`; say "本语料未检得" rather than supply a text;
keep the text, its commentators, computation and modern medicine apart (no 消渴＝糖尿病); no diagnosis, prescription
or dose.  What you write under **设置 → 指令** is added after them.

## Models

The page speaks two wire formats:

* **OpenAI-compatible chat completions**, streamed — MiniMax, DeepSeek, Qwen, Kimi, GLM, SiliconFlow, Doubao,
  OpenRouter, Poe, OpenAI, Gemini's compatibility endpoint, Grok, a LiteLLM proxy, vLLM, Ollama.  MiniMax-M3 is asked
  with `reasoning_split` (its thinking arrives in `reasoning_details`) and `max_completion_tokens`; turning thinking off
  sends `thinking: {type: "disabled"}`.  MiniMax streams `reasoning_details` — and, in its own examples, `content` — as
  cumulative text, other providers as increments; the client accepts both.  Each assistant turn is kept exactly as the
  provider produced it (content, `tool_calls`, `reasoning_details`) and replayed verbatim to the same provider, as MiniMax
  requires for its interleaved thinking; another provider gets the turn without fields it does not know, and reasoning
  of earlier turns is never sent back to DeepSeek-style providers.  A tool call whose turn was stopped is answered with
  a note, so the history stays valid.
* **Claude**, through the official Anthropic TypeScript SDK (pinned, loaded from jsDelivr on first use): adaptive
  thinking shown as a summary, server-side refusal fallbacks (`fallbacks: "default"`) on Claude Opus 5 and Fable 5.1 as
  in the harness's own provider, tool inputs streamed eagerly, the stop reason checked before any tool runs (a refusal or
  a `max_tokens` cut never runs a tool), assistant content replayed verbatim so thinking blocks round-trip.

**请求路径** chooses how requests travel: *浏览器直连* (straight to the provider, which must allow browser requests —
MiniMax does, for the published page's origin), *经本地服务转发* (through `taochronos serve`'s proxy), or *自动*
(through the proxy when the page is connected to a local server).  **测试连接** sends one short request.

## The local server

```bash
taochronos serve                      # http://localhost:8765 — the full corpus when its store exists
taochronos serve --env-keys           # the proxy adds this machine's keys (MINIMAX_API_KEY …) to requests without one
taochronos serve --llm minimax:MiniMax-M3   # research runs use the model for their judgement roles
taochronos serve --code-mode --open   # let the chat model run Code Mode programs; open the page
```

Endpoints: `GET /api/info`, `GET /api/catalog?mode=core|all`, `POST /api/call {name, arguments, max_chars}`,
`GET /api/passage?id=`, `POST /api/research` → `{job}`, `GET /api/research/<job>` (progress: round, claims, hypotheses;
then the outcome), `GET /api/session/<id>?what=summary|report|hypothesis|evidence`, `POST /api/llm` (model proxy).

It binds to 127.0.0.1.  Only this machine's pages, the server's own pages, the published client
(`https://psknlr.github.io`) and origins named with `--allow-origin` may call it (CORS, with Private Network Access
headers so the HTTPS page may reach it — the browser may ask for permission); the Host header must name this machine,
so a rebound DNS name cannot reach it.  Bound to any other address it requires its access token (above).  The
proxy forwards only to the hosts of the listed providers and streams the answer back; keys pass through and are never
stored or logged, and requests are not logged at all unless `--verbose` (paths only).  Research runs one at a time in a
background thread (a run installs its contract's guards harness-wide).  When the page is served from here and the site
was not built, the in-browser runtime's archives are made from the checkout on first use.

## Publishing

`.github/workflows/pages.yml` builds and deploys the site on every push to `main` that touches the client, the package
or the data it ships, and on demand.  One-time setup: **Settings → Pages → Build and deployment → Source: GitHub
Actions**.  To build locally:

```bash
taochronos web build -o _site               # client + runtime archives + providers.json + pinned Pyodide 0.28.2
taochronos web build -o _site --pyodide cdn # without Pyodide: the page loads it from jsDelivr
python -m http.server -d _site 8000
```

The site (about 15 MB) holds: the client (`web/`), `runtime/taochronos.zip` (the package), `runtime/home.zip`
(profiles, domain packs, the demonstration corpus, catalogs, agents, skills, gold sets; the lexicon harvested from the
full corpus is left out), `runtime/manifest.json` (sizes and SHA-256; the worker caches the archives by content),
`providers.json` (from `taochronos.chat.providers`) and, by default, the Pyodide core with the PyYAML and SQLite
wheels, checksums verified against `pyodide-lock.json`.  Archives are deterministic.  Every path is relative, so the
site works under `/TaoChronos/`.

## Tests

`tests/test_chat.py` — the catalog (what is offered, what never is, valid names and schemas), calls by either name,
failures as results, meta-tools, the system prompt and the Tao-R1 identity, trimming and citations, research runs and
their sessions, the V2 workflow, every server endpoint, CORS and Private Network Access, the origin and host checks
(the server's own pages on any address), the access token (refused without it, the proxy too; generated for any address
but loopback), the proxy (streaming, allow-list, the SDK path form, `--env-keys`), background research, the site build.
`tests/test_corpus_store.py` — on a store: a quotation found whatever its punctuation and in either script, across a
witness's own marks, never with a changed or missing character; outside a session `classics.list_books` lists every
book with its filters and `kg.claims` / `kg.neighbors` read the passages that write the term.  `tests/test_web_client.py` — the
client's logic under Node (cumulative and incremental streams, history rules, dangling tool calls, citation pairing) and
the page in Chromium against scripted providers (`tests/web_mock.py`): a MiniMax-style stream (cumulative
`reasoning_details` and content, streamed tool arguments) and a Claude stream through the real SDK, checking the
requests (`reasoning_split`, `max_completion_tokens`, `reasoning_details` and thinking signatures replayed, fallbacks),
the chip states, the highlighted passage, Tao-R1 in the chip and under the answer, and persistence across a reload; and
a page served elsewhere (as on GitHub Pages) connecting to a server in one step, using it again after a reload, and a
token taken from the address (and its absence reported).  The browser tests are skipped where Playwright or Chromium is
missing.

## Limits

* In the browser the corpus is the demonstration corpus — enough to see every function work, not to research; the page
  says so, and so does the model's standing instruction.  `modern.search` reads its cached records only (no network from
  Python in the browser); `vision.layout` needs a file on the server's disk.
* Quotation checks compare characters after removing punctuation and spacing, then after the harness's normalisation
  (`philology.normalize`); a quotation that abridges the passage (「……」 dropped words) reads as a mismatch, by design:
  the reader is sent to the passage.  Checks run against the corpus the page is connected to: a passage id from the full
  corpus reads as "no such passage" in the browser — reconnect the server and the check runs again.
* Research in the browser runs the deterministic procedures (no model inside the harness); on the local server
  `--llm` gives its judgement roles a model.
* A provider that does not allow browser requests needs the local server's proxy.
