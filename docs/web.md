# 网页对话 — the web client

**道乃久** (TaoChronos; model **Tao-R1**; published by 医哲未来人工智能研究院, IMPF-AI): a model of your choice that answers
from the classics through TaoChronos's tools, with every quotation checked against its source.  Published at
**https://chat.impf.ai/** (GitHub Pages under IMPF-AI's domain; the old address redirects there), where it runs in the browser on the **要籍语料** — the texts of the 350 key works,
the first whole, the rest in excerpts ([要籍语料](#要籍语料--the-browsers-corpus)); the same page is served by
`taochronos serve`, which brings all the books of the full corpus into it ([接入全部古籍](#接入全部古籍)).

```
            browser                                         your machine (optional)
 ┌────────────────────────────────────┐                ┌──────────────────────────────┐
 │  web/  chat UI · agent loop        │  tool calls    │  taochronos serve            │
 │        citation checks             │ ─────────────► │  ChatRuntime (full corpus)   │
 │  worker.js  Pyodide + TaoChronos   │                │  /api/call · /api/research … │
 │        (要籍语料, indexed once)     │                │  /api/llm  (model proxy)     │
 └──────────────┬─────────────────────┘                └──────────────┬───────────────┘
                │ your key, straight to the provider (or via /api/llm) │
                ▼                                                      ▼
   道乃久默认服务 (default, no key; relay/) · DeepSeek · Qwen · Kimi · GLM · OpenRouter · Poe · LiteLLM · Claude · local models · any API set by hand
```

The model holds the conversation; TaoChronos executes.  The browser runs the agent loop — it streams the model's
answer, runs the tools the model asks for, sends their results back, and repeats until the model answers.  The tools
run in one of two places, with the same Python module (`taochronos.chat`) behind both, so both answer alike:

| Runtime | Where | Corpus | Start |
|---|---|---|---|
| **浏览器内** (in the browser) | Pyodide (CPython on WebAssembly) in a Web Worker | the 要籍语料: 348 of the 350 key works, the first whole, the rest in excerpts (a site built without the pack: the demonstration corpus, 23 short excerpts) | nothing: the page loads it (about 20 MB the first time, then kept in the browser) |
| **本地服务 / 远程服务** (a TaoChronos server) | `taochronos serve` on your machine, or on another one with a token | the full corpus you built (`corpus ingest …`; this project's build: 966 books, 2.05 million passages, 123 million characters), else the demonstration corpus | `pip install -e . && taochronos serve` |

The full corpus is never part of the site: it is built from its sources on your machine, under their licences.

## 道乃久 · Tao-R1 · IMPF-AI

The agent is **道乃久** (its English name TaoChronos; the name is from the 《道德经》: “天乃道，道乃久”), published by
**医哲未来人工智能研究院 (IMPF-AI)**; its model is called **Tao-R1**.  The page says so where people look: 道乃久 on the
opening screen, in the side bar, the page title and exports, with the publisher's line; Tao-R1 on the model chip and under
each answer.  Tao-R1 is TaoChronos (the tools, the evidence discipline, the quotation checks) over a general language model
chosen under **设置 → 模型** (by default 道乃久默认服务); a model the visitor chose is named in the chip's tooltip, under each
answer's line and in the settings, while the default service is shown by its own name only — the page names no vendor
behind it.  The standing instructions give the model its names and publisher and tell it to be plain about
what it is: asked what it is or what it is built on, it names TaoChronos and the underlying model (the page adds
`底层语言模型：<model>（<provider>）` to the instructions' 运行环境 section), and it claims no other identity.  `/api/info`
reports `agent_name`, `assistant_name` and `publisher`.

## 要籍语料 — the browser's corpus

The published site cannot carry all the books ([接入全部古籍](#接入全部古籍)): the 350 key works alone are some 57 million
characters, far more than a browser can download and index.  It carries every one of them, the first whole and the rest in
excerpts.  Two steps choose them:

1. **要籍** — `taochronos study canon --write-catalog` ranks the works of the full corpus by the citation network of the
   whole store (who cites which book, 《书名》 and 经曰, resolved to works): score = 10·log₂(1 + distinct works citing it, not
   older than it) + 2·periods in which it is cited + 2·log₂(1 + citations) + 3·log₂(1 + witnesses) + 6·in the 四库全书.  The
   first 350 of 759 are written to `corpus/catalog/canon.yaml` (metadata only).  It is what this corpus quotes, not a verdict:
   late works have had less time to be cited, lost works are not in it.  `classics.canon` — offered to the model directly —
   queries the list in any corpus and says whether the current one holds each work.
2. **要籍语料** — `taochronos web pack` takes, for each of the 350, the best witness (`WEB_SOURCES`: the openly licensed first
   — CMETA's collated editions, 汉籍仓库, 维基文库, McGill — then 笈成 and the collections transcribed from it; the most complete
   within a source) — up to three for the first ten, so that the 素问, 灵枢, 伤寒论 and 金匮要略 can be collated in the browser —
   whole within 350 000 characters for the first ten; then 50 000, 25 000 and 12 000 by rank, as whole chapters spread
   through the book.  Result: 348 works, 368 witnesses, 135 083 passages, 8.5 million characters, with the passage ids of
   the full corpus, in rank order, in `corpus/web/` (passages.jsonl.gz, books.json, [ATTRIBUTION.md](../corpus/web/ATTRIBUTION.md)).
   The texts are all in the public domain.  The transcriptions of 笈成 and its derivatives declare no licence and their
   punctuation and collation are their editors'; IMPF-AI decided to publish them with the site (2026-09-28), and their
   records say so.  Sources whose terms forbid passing their transcriptions on (`NEVER_PACKED`: 東亜医学協会, a Hugging Face
   dataset under a proprietary licence) are never packed; the two works known only through them (扁鹊仓公列传, 伤寒论集注) are
   listed without text.

`taochronos web build` turns the pack into a corpus store — the schema of the full corpus — without its full-text index
(the index is two thirds of a download that compresses badly), xz-compressed (`runtime/corpus.sqlite.xz`: 10.8 MB for 90;
gzip would be 17).  Loading is arranged for the wait a visitor sees:

* **In parallel** — the worker downloads the corpus while Pyodide starts, and unpacks it (xzwasm, `web/js/vendor/`) into
  the runtime's file system as the bytes arrive.
* **The first-ranked first** — on the first visit the worker indexes the passages of the works ranked up to 40 (the pack is
  in rank order; 70 648 passages) before the runtime answers, and the rest in the background, a slice at a time between the
  questions it answers (`index_store(phase=…, limit=…)`, resumable).  The text of every book is there from the start; only
  the search of the later ones waits, a few seconds.  The status pill shows “其余要籍检索索引 n%”.
* **Kept in the browser** — once it is all indexed, the store is kept in IndexedDB (in 16 MB parts; the head written last,
  so that a half-kept store is never read), with the runtime archives.  IndexedDB, unlike the Cache API, is there on an
  http:// page too — the site is served over http until its certificate is issued — so a later visit downloads and indexes
  nothing: Pyodide, then the kept store, then the tools, in about 6 seconds.
* **The conversation starts at once** — the build writes `runtime/boot.json`: what the runtime will report once loaded (its
  info with the standing instructions, and its tool catalogs), computed on the same code and corpus.  The page puts the first
  question to the model with it while the runtime loads; the tools the model calls wait for the runtime.

Measured in Chromium on a fast machine: first visit ready in 15 s (the rest indexed 10 s later), a return visit in 6 s; on a
connection throttled to 1 MB/s and 150 ms, 40 s and 16 s.  The runtime uses the `web-canon` profile; `info.corpus` says
`kind: canon`, `label: 要籍语料`, and how many of the 350 it holds.  The standing instructions tell the model which corpus it
reads, that excerpted books may lack what the whole book has, and where the rest is.

## 接入全部古籍

The published site runs the 要籍语料 in the browser.  All the books — the full corpus — cannot be put on the site: the store is about 2.2 GB (a published GitHub Pages site may be no larger than 1 GB; git refuses files over 100 MB), a browser could
neither download nor index it, some of its sources may not be redistributed, and the project keeps no bulk texts in git
beyond the site's pack.  So the full corpus reaches the page through `taochronos serve`, wherever it runs:

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

1. Open the page and ask: **道乃久默认服务** needs no key (below).  To use a model of your own, choose **设置 → 模型** and
   paste its key; fifteen providers are listed from the harness's own presets (`taochronos llm presets`; MiniMax's own
   presets are not listed, since it serves the default service), and any other endpoint can be set by hand.  A key is
   kept in this browser's localStorage and sent only to its provider — or to your local server's proxy.
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
sees sixteen tools directly — `classics.search`, `classics.get_passage`, `classics.list_books`, `classics.canon`, `kg.term`, `kg.claims`,
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

**自定义 API** — an endpoint not in the list, set by hand (**设置 → 模型 → ＋ 自定义 API**; several can be kept): a name, the
wire format (OpenAI-compatible, or Anthropic Messages through the SDK), the base URL (the page appends `/chat/completions`,
or, ticked, calls the address as given — e.g. Azure's `…/chat/completions?api-version=…`), the model, the key (sent as
`Authorization: Bearer`; left empty when the service wants another header), extra request headers and body parameters as
JSON (a malformed field is shown and not taken), the name of the output-length parameter, whether the reasoning the model
streams is sent back in later turns (`reasoning_content`, `reasoning_details`, or not at all), and whether it takes
images.  The model must support tool calling for the agent to read the classics.  The underlying model's line in the
instructions names the endpoint (`底层语言模型：<model>（<name>）`).

**请求路径** chooses how requests travel: *浏览器直连* (straight to the provider, which must allow browser requests),
*经本地服务转发* (through `taochronos serve`'s proxy), or *自动*
(through the proxy when the page is connected to a local server; an API set by hand goes direct, since the proxy forwards
only to listed hosts — `taochronos serve --allow-host api.example.com` adds one).  **测试连接** sends one short request.

## 道乃久默认服务 — asking without a key, and conversation records

The published page lets a visitor ask at once: **道乃久默认服务** is MiniMax-M3 behind a relay of IMPF-AI's
([`relay/`](../relay/README.md), a Cloudflare Worker at `chat-api.impf.ai`).  The MiniMax key is a secret of that Worker,
set from the repository's Actions secrets when it is deployed: it is never in the page, the site or the repository, and
the page sends no key to the relay.  A key inside a static page cannot be kept, however it is encoded — the browser has to
send it in clear to the provider, where any visitor can read it — so the relay is the only place it can live.

* The build writes the relay's address into the site (`taochronos web build --relay URL` → `site.json`; the Pages
  workflow passes `https://chat-api.impf.ai`, or the repository variable `RELAY_URL`).  The page asks the relay's
  `/v1/health` as it loads; when it answers, a visitor who has set up no model of their own uses the default service (the
  tile 道乃久默认服务 · 免密钥 in 设置 → 模型, no key or address to fill in), and the opening screen says so.  When it does
  not answer, the page is what it was before: the visitor's own key.
* The relay accepts the page's origins only, the allowed models only, caps the output, and counts use per visitor
  (a hash of address and day; addresses are kept nowhere) per minute and per day, and in all per day
  (`relay/wrangler.toml`).  Its refusals are sentences a visitor can act on (wait, or use one's own key).
* **Conversation records** (the test period): before a visitor's first question the page says what would be recorded
  and why, and asks — 同意并继续 or 不记录; the choice stays in that browser and can be changed at any time under
  设置 → 数据.  A visitor who agreed sends, after each finished turn, one compact record to the relay: the question, the
  answer, the tools called, how the citations were checked, the model, token usage and timings — never a key, the
  settings or an address (`web/js/records.js`, `relay/src/relay.js` keeps only those fields).  The relay holds the records
  until `.github/workflows/chat-logs.yml` collects them, every hour, into `data/chat-logs/YYYY/MM/DD.jsonl` in this private
  repository, and deletes them once the commit is pushed (`relay/collect.py`).  The records never enter the published
  site.  If the repository is ever made public, `data/chat-logs/` must be moved out first.

**The page names no vendor.**  The default service appears as 道乃久默认服务 and its answers as Tao-R1 — on its tile
(免密钥 · 直接提问, with no model to choose), in the chip's and the composer's tooltips, under each answer, in exports and in
the connection test — and MiniMax's own presets are not listed (`UNLISTED` in `taochronos.chat.providers`; the local
server's proxy still reaches them).  The consent notice speaks of recording to the institute's server.  The standing
instructions still carry the underlying model (`底层语言模型：…`), so that a visitor who asks what the assistant is built on
gets a truthful answer rather than a denial.

Setting it up once: a Cloudflare API token and account id, the MiniMax key and a collector token as repository secrets,
then **Actions → relay → Run workflow** — step by step, with the checks and the usual errors, in
[relay/SETUP.md](../relay/SETUP.md) (Chinese).

## The local server

```bash
taochronos serve                      # http://localhost:8765 — the full corpus when its store exists
taochronos serve --env-keys           # the proxy adds this machine's keys (MINIMAX_API_KEY …) to requests without one
taochronos serve --llm minimax:MiniMax-M3   # research runs use the model for their judgement roles
taochronos serve --code-mode --open   # let the chat model run Code Mode programs; open the page
taochronos serve --allow-host https://gw.example.com:8443   # the proxy may also forward to an API set by hand
```

Endpoints: `GET /api/info`, `GET /api/catalog?mode=core|all`, `POST /api/call {name, arguments, max_chars}`,
`GET /api/passage?id=`, `POST /api/research` → `{job}`, `GET /api/research/<job>` (progress: round, claims, hypotheses;
then the outcome), `GET /api/session/<id>?what=summary|report|hypothesis|evidence`, `POST /api/llm` (model proxy).

It binds to 127.0.0.1.  Only this machine's pages, the server's own pages, the published client
(`https://chat.impf.ai`, and `https://psknlr.github.io`) and origins named with `--allow-origin` may call it (CORS, with Private Network Access
headers so the HTTPS page may reach it — the browser may ask for permission); the Host header must name this machine,
so a rebound DNS name cannot reach it.  Bound to any other address it requires its access token (above).  The
proxy forwards only to the hosts of the listed providers and streams the answer back; keys pass through and are never
stored or logged, and requests are not logged at all unless `--verbose` (paths only).  Research runs one at a time in a
background thread (a run installs its contract's guards harness-wide).  When the page is served from here and the site
was not built, the in-browser runtime's archives are made from the checkout on first use.

## Publishing

`.github/workflows/pages.yml` builds and deploys the site on every push to `main` that touches the client, the package
or the data it ships, and on demand.  One-time setup: **Settings → Pages → Build and deployment → Source: GitHub
Actions**.  It must be the only thing that publishes the site: a Pages site left on "Deploy from a branch", or a second
workflow such as GitHub's Jekyll starter (`jekyll-gh-pages.yml`), publishes the README rendered by Jekyll over the client.
The site lives under the repository's path (`/TaoChronos/`); every address in it is relative.  To build locally:

```bash
taochronos study canon --write-catalog      # (with the full corpus) rank the works → corpus/catalog/canon.yaml
taochronos web pack                         # (with the full corpus) their open texts → corpus/web/
taochronos web build -o _site               # client + runtime archives + 要籍语料 store + providers.json + pinned Pyodide 0.28.2
taochronos web build -o _site --pyodide cdn # without Pyodide: the page loads it from jsDelivr
python -m http.server -d _site 8000
```

The site (about 26 MB) holds: the client (`web/`), `runtime/taochronos.zip` (the package), `runtime/home.zip`
(profiles, domain packs, the demonstration corpus, catalogs with the 要籍 list, agents, skills, gold sets; the lexicon
harvested from the full corpus is left out), `runtime/corpus.sqlite.xz` (the 要籍语料 as a store without its index, 10.8 MB;
built from `corpus/web` by the build, the same bytes for the same pack; `TAOCHRONOS_WEB_XZ_PRESET` trades size for build
time, the tests use 1), `runtime/boot.json` (the runtime's info and catalogs, for the conversation to start while it
loads), `runtime/manifest.json` (sizes and SHA-256; the worker keeps the archives by content in IndexedDB, and the corpus
once indexed), `providers.json` (from `taochronos.chat.providers`) and, by default, the Pyodide core with the PyYAML and
SQLite wheels, checksums verified against `pyodide-lock.json`.  Archives are deterministic.  Every path is relative.

## Tests

`tests/test_chat.py` — the catalog (what is offered, what never is, valid names and schemas), calls by either name,
failures as results, meta-tools, the system prompt and the identity (道乃久, Tao-R1, IMPF-AI; honest about the model), trimming and citations, research runs and
their sessions, the V2 workflow, every server endpoint, CORS and Private Network Access, the origin and host checks
(the server's own pages on any address), the access token (refused without it, the proxy too; generated for any address
but loopback), the proxy (streaming, allow-list, the SDK path form, `--env-keys`, `--allow-host`), background research, the
site build (with the corpus store).  `tests/test_web_corpus.py` — the 要籍 list (ranked, metadata only, the classics first,
nothing modern), the choice of witnesses (openly licensed first, never a source in `NEVER_PACKED`), budgets kept as whole
chapters spread through a book, the pack → a store with the same bytes → indexed once → read by the harness, the index in
two phases (the first-ranked works first, the rest in slices, seen by a connection already reading) and the shipped pack
under the `web-canon` profile (348 works in rank order, the terms of each transcription that is not openly licensed; a 宋本
found for a punctuated 伤寒论 clause; `classics.canon` for what it lacks).
`tests/test_corpus_store.py` — on a store: a quotation found whatever its punctuation and in either script, across a
witness's own marks, never with a changed or missing character; outside a session `classics.list_books` lists every
book with its filters and `kg.claims` / `kg.neighbors` read the passages that write the term.  `tests/test_web_client.py` — the
client's logic under Node (cumulative and incremental streams, history rules, dangling tool calls, citation pairing) and
the page in Chromium against scripted providers (`tests/web_mock.py`): a MiniMax-style stream (cumulative
`reasoning_details` and content, streamed tool arguments) and a Claude stream through the real SDK, checking the
requests (`reasoning_split`, `max_completion_tokens`, `reasoning_details` and thinking signatures replayed, fallbacks),
the chip states, the highlighted passage, Tao-R1 in the chip and under the answer, and persistence across a reload; and
a page served elsewhere (as on GitHub Pages) connecting to a server in one step, using it again after a reload, and a
token taken from the address (and its absence reported); an API set by hand (address, model, key, headers, parameters —
checked in the request it makes); the default service (a stand-in relay): asked at once without a key, no key sent by the
page, the consent question once, a turn recorded only after 同意 (its fields, no key or settings), none after 不记录 or
once switched off under 设置 → 数据, and the page asking for a key while the relay is down; and, with
`TAOCHRONOS_PYODIDE_E2E=1`, the built site in Chromium on an http:// origin like the published one (no Cache API) —
Pyodide, the 要籍语料 downloaded, the first-ranked works indexed before it answers and the rest in the background, the
store kept in IndexedDB and a reload that downloads no corpus, a turn answered on it.  The browser tests are skipped where Playwright or Chromium is missing.  `relay/test/relay.test.js`
(`node --test`, in CI) — the Worker's handler and its two stores on SQLite: the key added by the relay and never shown,
origins, models, output cap and body size, the three limits and a new day, MiniMax's refusals turned into plain messages,
the records reduced to their fields, and the collector's token, cursor, deletion and ids never reused.
`tests/test_relay_collect.py` — `relay/collect.py` against a stand-in relay: records pulled once, by day, the cursor
committed with them, deleted only once held, a deployment checked (and a refused key explained).  The site build writes
`site.json` only when given a relay, carries the texts' attribution, and never a conversation record or a key.

## Limits

* In the browser the corpus is the 要籍语料: 348 of the 350 key works, the first whole, the others in chapters spread
  through the book — enough to read and compare the main classics, not the whole literature; the page says so, and so
  does the model's standing instruction.  The first visit downloads about 20 MB (Pyodide and the corpus) and indexes the
  corpus (the first-ranked works before the runtime answers, the rest in the background); later visits open it from
  IndexedDB.  A browser that keeps no site data (a private window) indexes it on every visit.  `modern.search` reads its cached records only (no network from
  Python in the browser); `vision.layout` needs a file on the server's disk.
* Quotation checks compare characters after removing punctuation and spacing, then after the harness's normalisation
  (`philology.normalize`); a quotation that abridges the passage (「……」 dropped words) reads as a mismatch, by design:
  the reader is sent to the passage.  Checks run against the corpus the page is connected to: a passage id from the full
  corpus reads as "no such passage" in the browser — reconnect the server and the check runs again.
* Research in the browser runs the deterministic procedures (no model inside the harness); on the local server
  `--llm` gives its judgement roles a model.
* A provider that does not allow browser requests needs the local server's proxy.
