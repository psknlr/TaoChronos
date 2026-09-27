# 网页对话 — the web client

A conversation with a model of your choice that answers from the classics through TaoChronos's tools, with every
quotation checked against its source.  Published at **https://psknlr.github.io/TaoChronos/**; the same page is served
by `taochronos serve` on your own machine.

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
| **本地服务** (local server) | `taochronos serve` on your machine | the full corpus you built (`corpus ingest …`), else the demonstration corpus | `pip install -e . && taochronos serve` |

The full corpus is never part of the site: it is built from its sources on your machine, under their licences.

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

It binds to 127.0.0.1.  Only this machine's pages, the published client (`https://psknlr.github.io`) and origins named
with `--allow-origin` may call it (CORS, with Private Network Access headers so the HTTPS page may reach it — the
browser may ask for permission); the Host header must name this machine, so a rebound DNS name cannot reach it.  The
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
failures as results, meta-tools, the system prompt, trimming and citations, research runs and their sessions, the V2
workflow, every server endpoint, CORS and Private Network Access, the origin and host checks, the proxy (streaming,
allow-list, the SDK path form, `--env-keys`), background research, the site build.  `tests/test_web_client.py` — the
client's logic under Node (cumulative and incremental streams, history rules, dangling tool calls, citation pairing) and
the page in Chromium against scripted providers (`tests/web_mock.py`): a MiniMax-style stream (cumulative
`reasoning_details` and content, streamed tool arguments) and a Claude stream through the real SDK, checking the
requests (`reasoning_split`, `max_completion_tokens`, `reasoning_details` and thinking signatures replayed, fallbacks),
the three chip states, the highlighted passage and persistence across a reload.  The browser tests are skipped where
Playwright or Chromium is missing.

## Limits

* In the browser the corpus is the demonstration corpus — enough to see every function work, not to research; the page
  says so, and so does the model's standing instruction.  `modern.search` reads its cached records only (no network from
  Python in the browser); `vision.layout` needs a file on the server's disk.
* Quotation checks compare characters after removing punctuation and spacing, then after the harness's normalisation
  (`philology.normalize`); a quotation that abridges the passage (「……」 dropped words) reads as a mismatch, by design:
  the reader is sent to the passage.  Checks run against the corpus the page is connected to: a passage id from the full
  corpus reads as "no such passage" in the browser.
* Research in the browser runs the deterministic procedures (no model inside the harness); on the local server
  `--llm` gives its judgement roles a model.
* A provider that does not allow browser requests needs the local server's proxy.
