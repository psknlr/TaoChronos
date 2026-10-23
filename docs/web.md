# 网页对话 — the web client

**道乃久** (TaoChronos; model **Tao-R1**; published by 医哲未来人工智能研究院, IMPF-AI): a model of your choice that answers
from the classics through TaoChronos's tools, with every quotation checked against its source.  Published at
**https://chat.impf.ai/** — served over HTTPS by a Cloudflare Worker, its tools running on the site's own server over the
**full corpus** (958 books, 122 million characters: [cloud/](../cloud/README.md), [ADR 0016](adr/0016-site-and-full-corpus-on-cloudflare.md);
without a container, the site's own Worker answers from its copy in Cloudflare D1: [ADR 0017](adr/0017-d1-backup.md));
when that server cannot answer, the page runs in the browser on the **要籍语料** — the texts of the listed key works, the
first whole, the rest in excerpts ([要籍语料](#要籍语料--the-browsers-corpus)).  The same page is served by
`taochronos serve`, which brings the full corpus you built into it ([接入全部古籍](#接入全部古籍)).

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
| **浏览器内** (in the browser) | Pyodide (CPython on WebAssembly) in a Web Worker | the 要籍语料: 533 of the 535 key works, the first whole, the rest in excerpts (a site built without the pack: the demonstration corpus, 23 short excerpts) | nothing: the page loads it (about 20 MB the first time, then kept in the browser) |
| **本站服务** (the site's server) | a container on Cloudflare behind https://chat.impf.ai/api (`cloud/`), started on demand | the full corpus as the site may carry it: 958 books, 2.04 million passages, 122 million characters (`taochronos web store`: never the sources whose terms forbid it) | nothing: the page on chat.impf.ai uses it, and falls back to the browser when it cannot answer (503) — or refuses this visitor (403 for a restricted address, 429 for a day spent: the page says which; [ADR 0023](adr/0023-workers-paid.md)) |
| **本地服务 / 远程服务** (a TaoChronos server) | `taochronos serve` on your machine, or on another one with a token | the full corpus you built (`corpus ingest …`; this project's build: 966 books, 2.05 million passages, 123 million characters), else the demonstration corpus | `pip install -e . && taochronos serve` |

The full corpus is never part of the site's files: the site's server carries it as a store built once from the full
corpus (`taochronos web store`), and `taochronos serve` reads the one you built from its sources, under their licences.

## 道乃久 · Tao-R1 · IMPF-AI

The agent is **道乃久** (its English name TaoChronos; the name is from the 《道德经》: “天乃道，道乃久”), published by
**医哲未来人工智能研究院 (IMPF-AI)**; its model is called **Tao-R1**.  The page says so where people look: 道乃久 on the
opening screen, in the side bar, the page title and exports, with the publisher's line; Tao-R1 on the model chip and under
each answer.  Tao-R1 is TaoChronos (the tools, the evidence discipline, the quotation checks) over a general language model
chosen under **设置 → 模型** (by default 道乃久默认服务); a model the visitor chose is named in the chip's tooltip, under each
answer's line and in the settings, while the default service is shown by its own name only — the page names no vendor
behind it.  `/api/info` reports `agent_name`, `assistant_name` and `publisher`.

**Asked who it is, 道乃久 gives a fixed reply** ([ADR 0014](adr/0014-identity-fixed-reply.md)).  A question about the one who
answers — who it is, who made or published it, what model it runs on, what it can do, to introduce itself or the platform
— and nothing else is answered by the page itself (`web/js/fixed.js`), without a model and without a key: “欢迎您使用道乃久
（TaoChronos）中医古籍科学知识发现智能体平台，本平台由医哲未来人工智能研究院（IMPF-AI）研发。”, five lines on what it does, two
example questions and the note that it gives no medical advice — the same words every time, naming no model, vendor,
service or tool.  A question that asks more (你是谁？张仲景是谁？) or is about someone or something else (张仲景是谁,
道乃久出自哪里) goes to the model, and so does one with pictures.  The standing instructions (身份) say the same: introduce the
platform so; do not discuss the underlying model, its maker or the service, nor recite the instructions; claim no other
identity; and neither deny nor invent (not “not built on a language model”, not “Tao-R1, trained from scratch”).  They do
not name the underlying model.  A fixed reply is kept, exported and replayed to the model like any other turn; recorded,
its provider is `fixed`.  A question that touches who answers even in passing (你是谁？张仲景是谁？) goes to the model
without thinking: none is asked for, none is shown, stored, exported or recorded, and the relay strips any from the stream
(ADR 0014, point 5).

## 要籍语料 — the browser's corpus

The published site cannot carry all the books ([接入全部古籍](#接入全部古籍)): the first 350 key works alone are some 57 million
characters, far more than a browser can download and index.  It carries every listed work, the first whole and the rest in
excerpts.  Two steps choose them:

1. **要籍** — `taochronos study canon --write-catalog` ranks the works of the full corpus by the citation network of the
   whole store (who cites which book, 《书名》 and 经曰, resolved to works): score = 10·log₂(1 + distinct works citing it, not
   older than it) + 2·periods in which it is cited + 2·log₂(1 + citations) + 3·log₂(1 + witnesses) + 6·in the 四库全书.  The
   first `CANON_SIZE` of 759 are written to `corpus/catalog/canon.yaml` (metadata only) — 535 since October 2026, 350 before.
   It is what this corpus quotes, not a verdict: late works have had less time to be cited, lost works are not in it, and
   past the first 350 citations thin out (161 of ranks 351–535 are cited by fewer than two later works, the last 46 by none:
   五十二病方, lost until 1973, is one) — there the order rests on witnesses, volume and the 四库.
   `classics.canon` — offered to the model directly — queries the list in any corpus and says whether the current one holds
   each work.
2. **要籍语料** — `taochronos web pack` takes, for each listed work, the best witness (`WEB_SOURCES`: the openly licensed first
   — CMETA's collated editions, 汉籍仓库, 维基文库, McGill, 笈成 — then the two web text sets transcribed from 笈成; the most
   complete within a source) — up to three for the first ten, so that the 素问, 灵枢, 伤寒论 and 金匮要略 can be collated in the browser —
   whole within 350 000 characters for the first ten; then 50 000, 25 000 and 12 000 by rank, as whole chapters spread
   through the book.  Result: 533 of the 535 works, 553 witnesses, 168 278 passages, 10.5 million characters, with the passage ids of
   the full corpus, in rank order, in `corpus/web/` (passages.jsonl.gz, books.json, [ATTRIBUTION.md](../corpus/web/ATTRIBUTION.md)).
   The texts are all in the public domain.  笈成 releases its editorial work on them — selection, arrangement, punctuation,
   annotation — under CC0 1.0 and its own writing under CC BY 4.0 ([著作權聲明](https://jicheng.tw/tcm/copyright.html),
   checked 2026-09-29; credit 中醫笈成), so 529 of the works come from an openly licensed witness.  IMPF-AI decided to
   publish the rest with the site (2026-09-28): the four works known only through TCM-Ancient-Books, a set of copies of 笈成
   texts whose repository declares no licence (a copy of a 笈成 text is never stored, so these four match no 笈成 text in
   the store; their records carry the site's terms), and the modern editors' part of the 笈成 texts that follow a modern edition, such as
   the 今人辑校本 of 集验方, 名医别录, 食疗本草, 小品方, 吴普本草, 海药本草 and 新修本草, which 笈成's CC0 cannot release (the
   licence of every 笈成 record and the attribution say so).  Sources whose terms forbid passing their transcriptions on
   (`NEVER_PACKED`: 東亜医学協会, a Hugging Face dataset under a proprietary licence) are never packed; the two works known
   only through them (扁鹊仓公列传, 伤寒论集注) are listed without text.

`taochronos web build` turns the pack into a corpus store — the schema of the full corpus — without its full-text index
(the index is two thirds of a download that compresses badly), xz-compressed (`runtime/corpus.sqlite.xz`: 13.3 MB for 97.5;
10.8 MB for 90 with the 350; a test keeps it under 16 MB).  Loading is arranged for the wait a visitor sees:

* **In parallel** — while Pyodide starts, a worker of its own (`unpack-worker.js`) downloads the corpus and unpacks it
  (xzwasm, `web/js/vendor/`) as the bytes arrive, into one buffer the runtime's file system then takes without a copy
  ([ADR 0015](adr/0015-faster-start.md)).
* **The first-ranked first** — on the first visit the worker indexes the passages of the works ranked up to 40 (the pack is
  in rank order; 70 648 passages) before the runtime answers, and the rest in the background, a slice at a time between the
  questions it answers (`index_store(phase=…, limit=…)`, resumable).  The text of every book is there from the start; only
  the search of the later ones waits, a few seconds.  The page does not show it (the side panel's pill carries it as
  `data-indexing`, for scripts and tests).
* **Kept in the browser** — once it is all indexed, the store is kept in IndexedDB (in 16 MB parts; the head written last,
  so that a half-kept store is never read), with the runtime archives.  IndexedDB, unlike the Cache API, is there on an
  http:// page too — the site is served over http until its certificate is issued — so a later visit downloads and indexes
  nothing: Pyodide, then the kept store, then the tools, in about 4 seconds.  The package's bytecode is kept too (compiled
  once after the first visit's indexing), the YAML the runtime reads comes parsed with the site (`home.zip`, `.cache/yaml`),
  and the store's counts come with the store.
* **The conversation starts at once** — the build writes `runtime/boot.json`: what the runtime will report once loaded (its
  info with the standing instructions, and its tool catalogs), computed on the same code and corpus.  The page puts the first
  question to the model with it while the runtime loads; the tools the model calls wait for the runtime.

Measured in Chromium on a fast machine: first visit ready in 9.6 s (the rest indexed 7 s later), a return visit in 4 s; on a
connection throttled to 1 MB/s and 150 ms, 27 s and 13–14 s (before ADR 0015: 15 s, 6 s; 39 s, 15–16 s) — measured with the 350:
the 535 add 2.5 MB to the first download and 33 000 passages to the background indexing, while the works ranked up to 40,
indexed before the runtime answers, are the same.  The runtime uses the `web-canon` profile; `info.corpus` says
`kind: canon`, `label: 要籍语料`, and how many of the listed works it holds.  The standing instructions tell the model which
corpus it reads, that excerpted books may lack what the whole book has, and where the rest is.

**From 350 to 535.**  The list and the pack are made on the full store, which this repository does not hold.  `taochronos
web canon --extend` (on a machine with the store: `--data <dir>`) ranks the store again, keeps the 350 already listed in
their order and appends ranks 351–535, writes the catalog, packs, and regenerates the D1 backup's tables; the `canon`
workflow (`.github/workflows/canon.yml`, run by hand) does the same in CI from the site's corpus parts (the KV store of
[cloud/](../cloud/README.md)), commits the result to the branch it runs on and, on main, starts the site's deployment.
It leaves the alias layer (below) to be rebuilt: its witnesses' `web` flags come from the pack (built on the full
store, from `corpus/web/passages.jsonl.gz`; on the web store, the pack is the store), so a new pack makes it stale —
the layer's header names the pack it was built against (`web_pack`), and `aliases check` warns when that is not the
pack `corpus/web` holds — until the `aliases` workflow runs again, which commits nothing if `corpus/web` changed while
it ran.
`--extend` is needed whenever the store at hand lacks sources of the first ranking (the KV parts never hold `NEVER_PACKED`
sources): ranked again without them, the first 350 would move.  It ran on 2026-10-11 (757 works ranked on the parts):
budgets are by rank, so the 185 works added came in 12 000-character excerpts — 1.9 million characters more for the
browser.

The browser's corpus also loads two lexicons beyond the curated one (profile `web-canon`, `lexicon_extra`): a supplement
of common drugs (`lexicon-supplement`) and the core of the harvested lexicon — the 800 drugs and 2 000 formulas the full
corpus attests most (`lexicon-core`, `taochronos lexicon core`) — so that its compositions are read with the names the
literature writes most ([data.md](data.md)).

## 接入全部古籍

On https://chat.impf.ai the full corpus is there already: the site's own server (a container on Cloudflare, [cloud/](../cloud/README.md))
answers the page's tools over every book the site may carry.  A browser could neither download nor index the full store
(1.7 GB indexed), some of its sources may not be redistributed, and the project keeps no bulk texts in git beyond the
site's pack; so everywhere else — and for the books the site may not carry — the full corpus reaches the page through
`taochronos serve`, wherever it runs:

1. **Build the corpus once** on the machine that will serve it — the commands under “接入全量语料” in the
   [README](../README.md#二快速开始) (`taochronos corpus fetch … && taochronos corpus ingest …`; `corpus status` counts
   what is in).
2. **Start the server**: `taochronos serve`.  It finds the store and uses the `full-corpus` profile; it counts the corpus
   before it answers, so the page connects at once.
3. **Connect**: on the page, **设置 → 运行环境 → 接入全部古籍 → 连接** (the address is `http://localhost:8765` by
   default).  Or open `http://localhost:8765` itself: the server serves the same page, already connected.

The browser remembers the server it connected to.  In **自动** mode the page uses, in order: the server that served it;
the server this browser last worked with, if it answers within a moment; TaoChronos in the browser.  So with the server
running, the page opens on the full corpus; without it, on the demonstration corpus.  The page does not say which —
not on the opening screen, the side panel or the composer, nor in **设置 → 运行环境** (a server's `/api/info` says what
it serves): while the runtime loads, 加载中 and one progress bar for the whole load (on the opening screen and on the
side panel's pill; the bar never goes back, also when the runtime tried first does not answer and another takes over);
once it answers, the pill says 运行环境 · 已就绪 and the opening screen nothing; when it cannot load, what went wrong and
the way to the settings.  Connected to a server that has only the demonstration corpus, 设置 → 运行环境 says so (the
corpus is to be built on that machine).  **指定的服务** always uses the server and reports it when it is down;
**浏览器内** never looks for one.

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
   hypotheses with their supporting and contradicting quotations, the full report), **资料** (the user's own files:
   [below](#我的资料--the-users-own-data)), **工具台** (every tool, with a form generated from its schema — no model
   needed).
5. **上传资料** (the document button beside the image button, or a file dropped or pasted into the composer — images go
   with the message, other files to 我的资料): the user's own table or text, read on their machine, made anonymous and
   attached to the next message, for the model to analyse ([below](#我的资料--the-users-own-data)).

Keyboard: Enter sends, Shift+Enter breaks the line (input methods are respected), Esc stops, Ctrl/⌘+K new
conversation, Ctrl/⌘+B the conversation list, Ctrl/⌘+J the side panel, `/` focuses the input.  Conversations are kept in
this browser (IndexedDB); **设置 → 数据** exports and imports them (JSON) or one as Markdown.

### Eight languages

The page reads in eight languages: the six of the United Nations (简体中文, English, Français, Español, Русский,
العربية), 繁體中文 for readers from Taiwan, Hong Kong and Macau, and Bahasa Melayu.  A browser gets its own language when
the page has it (`zh-TW`, `zh-HK` and `zh-Hant` get Traditional Chinese) and English otherwise; the language menu in the
top bar changes it (kept in this browser as `tc.lang`), and a link can ask for one with `?lang=` and the code: `zh`,
`zh-Hant`, `en`, `fr`, `es`, `ru`, `ar` or `ms`.  Arabic is laid out right to left; the stylesheet says start and end,
not left and right, and code, keys and addresses stay left to right.

The code is written in Chinese: every string a visitor reads goes through `T` (`web/js/i18n.js`), which looks it up in
`web/js/i18n-<code>.js` by the Chinese (a template's `{0}`, `{1}`… are its values); a string with no translation there
is shown in Chinese, and a Chinese page fetches no dictionary at all.  The Traditional Chinese dictionary is the Chinese
converted with OpenCC (`s2twp`, Taiwan wording, 「」 quotation marks).  The model is asked to answer in the page's
language, quoting the classics in the original Chinese (exactly as the tools return them, so that the quotation check
still holds) with a translation; the corpus is searched in Chinese as always.  The About page (`about.html`) carries
all eight languages.  The top bar's **TaoChronos | TCMScience** switch links this site (chat.impf.ai) and TCMScience
(science.impf.ai), each with its description on hover.

## 别名 — a drug's other names

`classics.search` reads a drug's other names from the alias layer ([ADR 0023](adr/0023-alias-layer.md),
[data.md](data.md#alias-layer-domainsclassicsaliases)): asked about 甘草, it also returns passages that write 国老; asked
about 木通 before the Song, passages that write 通草.  Places 4, 7 and 10 of each ten are theirs while today's ranking
lasts (one they cannot fill goes back to it), and every place after it runs out; the name asked keeps the others, and
a passage that writes the name only inside a longer one (将军 in 将军之官) or out of drug context comes last.  The
question is read for the names it asks ([ADR 0023](adr/0023-alias-layer.md) §4): a name it writes only inside a
longer one is not asked (将军之官); a longer name that is itself a drug's is asked as written (石南藤), unless a lexicon
herb or a longer lexicon name holds it (川乌头, 麦门冬汤); and a short question that is one name nobody knows asks that
name (干葛, not 葛; 人参叶 and 酒大黄 as written), question words and a dose staying outside it (葛二两 asks 葛), but
never takes in what it says of a drug (甘草入脾 asks 甘草 and 脾).  A question longer than 200 characters
(`ALIAS_MAX_CHARS`, on the normalised text: a passage pasted in, a list of names) is read and ranked as without the
layer: nothing found under another name, no `via`; only a passage that writes a name before it came into use is still
flagged (年代存疑).
A name two drugs share is listed with every drug and its sources (`query.aliases`), never answered as one.  The
browser's runtime has it on (`web-canon`: `retrieval.alias.enabled`, and `witness_scope: web`, so a witness passage
shown is one the 要籍语料 holds); its directory rides in `home.zip`, of which the runtime reads the two built files (a test
keeps the directory under 150 KB deflated as `home.zip` stores it, and any file of a local list out of it).  The full-corpus profile of the
site's server has it on too (`alias: {enabled: true}`), and so has the D1 backup, whose port of it (below) answers
alike.  The model is told so: the tool's description says what the places and labels are, that a term's lexicon
synonyms are always searched with it, that `aliases: off` turns the layer off, the lexicon synonyms then coming back
unlabelled, and that a question longer than 200 characters is searched as with `aliases: off` but for that flag; the standing
instructions tell it that such entries say which name they were found under, for which drug and on whose authority, to
keep a shared name's drugs apart, to say when a name belongs to some periods only, and — when a result has neither
`query.aliases` nor any `via`, so that only the lexicon's synonyms were searched — to search the other name itself.

**On the page.**  A passage found under another name carries a badge under its chip in 涉及的段落, in the 证据 list and
on the passage view's status line; its tooltip says what the passage writes, how the names relate, all the sources and
the witness:

| Badge | Meaning |
|---|---|
| 别名：国老→甘草 · 别名录（中醫笈成） | found under the drug (甘草) an asked name (国老) names: only an asked name stands before an arrow, as in the evidence ledger's words; with the first source; a kind other than a plain 异名 replaces 别名 (避讳改名：…, 古名：…), 相关 a term the lexicon only relates; several names of one drug from one source share a badge (at most four named, then 等); the title adds 此为候选别名，未经确认 for a candidate pair and 「X」多作普通词语，罕作药名 for a false friend asked |
| 别名：甘草（写作国老） · 别名录（中醫笈成） | the drug asked (甘草), found where the passage writes another name of it (国老): no arrow, the drug and then what the passage writes, the kind that name's; several written names share a badge as above |
| 别名：旱莲草（写作莲子草；所问鳢肠） · 别名录（中醫笈成） | the passage writes another name (莲子草) of the drug an asked name (鳢肠) names: the written name and then the asked one follow the drug, since the kind is the written name's, in a badge of its own (the title: 为所问「鳢肠」检索旱莲草) |
| 读作：鬼督邮→徐长卿 | how the passage reads a name that may mean more than one drug (p in the tooltip) |
| via 川楝子（写作金铃子；词表） | on a `taochronos_ask` source card: the label in the evidence ledger's words, as the 来源 lines give it (below), the legend in the tooltip; a flag there shows only its word (年代存疑, 同名异物, 所指不同) or, for another flag, its whole label |
| 年代存疑 | the passage is earlier than the name came into use: its edition may have changed the character, or it is a later layer |
| 同名异物 | a shared name the passage does not decide |
| 仅见于「X」 · 无药物语境 | the name asked occurs only inside X, or not as a drug: ranked after the others |
| 所指不同 | in this passage's years the name meant another drug |

The latest search sets or clears a passage's badges (a passage found later under the name asked shows none); a flag
the page has no words for is not shown; badges wrap on a phone.  The research agent's evidence keeps the same labels
in words in its notes (`via 国老→甘草（别名录（中醫笈成））`, `年代存疑（…）`); the research report adds them to each
passage of its corpus evidence (section 3) that the search found, with a legend, and the evidence table
(`evidence.csv`) ends with the note.  `taochronos_ask` gives its sources the same words (`sources[].labels`), and its
report (`taochronos ask`'s too) adds them, with the legend, to the 来源 lines.  In words only an asked name stands
before an arrow: `via 国老→甘草` was found for 国老 asked, through 甘草; a via for the drug itself asked (or with no
asked name known) has no arrow and says what the passage writes, `via 川楝子（写作金铃子；词表）`; a passage two of the
research's searches found (金铃子, then 川楝子) keeps each one's label.  The page shows an ask's source cards with
these words as badges (the row above); an ask source without labels is left as it is, and a search that returns the
passage later sets its badges as a search does.  A search hit's badge reads its arrow the same way: 别名：金铃子→川楝子
· 词表 only where 金铃子 was asked, 别名：川楝子（写作金铃子） · 词表 where 川楝子 was asked and the passage writes
金铃子; its kind is how the name before the arrow, or the written one, relates to the drug.

**The D1 backup.**  The Worker answers the same query block as Python: `chat/d1tables.py` writes the layer into
`tables.js` (`ALIASES`, the records of the shippable sources keyed by name; `ALIAS_SOURCES`; `ALIAS_CONTEXT`;
`ALIAS_PARAMS`, the full-corpus profile's parameters), and `backup/aliases.js` ports the layer's gates, readings,
expansions, view and places line for line, `search.js` the question rules (the 200-character limit among them),
tiers, places and labels, and `corpus.js` the card centred on the name a passage was found under.  Nothing is imported into D1 again (the lexicon,
the normaliser and the D1 version are unchanged), and the side search is one more part of statements the backup
already runs.  The query block and the labels (`via`, `flags`) of the passages both runtimes return for the reference
searches, and alias cases Python generates (gate inputs and verdicts, expansions and views, the places), are compared in
`cloud/test/backup.test.js`; which passages are returned is not, since the two candidate sets differ by design.

## 图表 — charts and their downloads

A study's result carries its charts and its three-line tables ([study.md](study.md#图表-charts),
[study.md](study.md#表格-three-line-tables)): specifications drawn from the whole result, never from the model's trimmed copy.
The page draws them (`web/js/chart.js`, `web/js/table.js`) in three places:

* **under the step that made them** — the figures and tables of a turn's tools follow its tool steps, one at a time with a
  row of tabs (图 1 …, 表 1 …: numbered as a paper numbers them) when there are several, with **导出组图** (all the figures as
  one figure in panels, A, B …, two columns at 175 mm, one caption) and **全部表格（Word）** (all the tables in one Word
  document);
* **in the 工具台**, under the result of a tool run by hand;
* **in an answer** — the model may draw the numbers it read from the tools in a ```chart block (a JSON specification of
  the same form: line, bar, hbar, stack, heatmap, timeline, box, forest, scatter …; the standing instructions say how, and
  that every number must come from a tool's result).  The block is checked before it is drawn; while it is still being
  written the page shows a placeholder, and one that cannot be drawn is shown as code with the reason.  A Markdown table in
  an answer is a three-line table: a line 「表1　…」 just above it is its caption, a line 「注：…」 just below its notes, and once
  the answer is written it has **复制** and **下载** as a study's table has.

Each chart is a card: 图 n and its title, what it counts; hover, or focus and the arrow keys, read out the values; **表格**
shows every number; **期刊样式** shows the figure as a journal prints it (white paper in either mode — what the journal export
gives); **导出** opens the export: the style (期刊 or 屏幕), the printed width (单栏 85 mm, 1.5 栏 120 mm, 双栏 175 mm), the
resolution (300 or 600 dpi), the number and caption (含图号与图注, off for a journal that sets its own), then the figure as
**SVG** (vector, its physical size in millimetres), **PNG** (the resolution written in the file, pHYs) or **TIFF** (RGB,
PackBits, with its resolution — what many journals ask for), the data as **CSV** (UTF-8 with a byte-order mark, for
spreadsheet programs) and the specification as **JSON**.  The settings are kept for the next figure (this browser only).

Each table is a card: 表 n and its title, the three-line table (its group heads ruled as booktabs' `\cmidrule`, statistical
symbols in italics), its notes and source; **复制** puts it on the clipboard as HTML with its rules inline and as
tab-separated text — pasted into Word or WPS it is a three-line table, into Excel cells; **下载** gives **Word** (.docx),
**LaTeX** (booktabs), **CSV** and **Markdown** — the same files as `taochronos study … --charts` (`study/tablefmt.py`).  The
Word document and the ZIP inside it, the PNG's pHYs and the TIFF are written by `web/js/bytes.js`, without a library.

A conversation exported as Markdown appends each chart's data and each table.  A research protocol (`study.protocol`) comes
with its whole text — **下载研究方案（Markdown）** under its step and in the 工具台 — and its tables to copy or download as Word:
filled with the pilot's numbers where the pilot ran the step that fills them (…（预试验）), shells with ×× placeholders where
it did not (…（模板）).  The colours are tokens (`--viz-1` … `--viz-8`, `--viz-other`, the `--viz-seq` ramp; `css/app.css`),
selected for the light and the dark surfaces and validated for colour-vision deficiency; a downloaded figure takes the
light ones, a journal figure its black and white.  The model reads only the titles of the figures and tables the page
shows (`charts_shown`, `tables_shown`), so it can point to them (见上方图 1、表 1) without spending its context on their data.

## 我的资料 — the user's own data

A visitor may bring their own data — a clinic's prescriptions, case records, a survey, notes — as CSV, TSV, Excel
(.xlsx), Word (.docx), TXT, Markdown or JSON, up to 10 MB a file ([mydata.md](mydata.md), [ADR 0022](adr/0022-the-users-own-data.md)):

* **Before the first upload** the page says, once per browser, what happens to the data: read on this machine (in the
  browser, or by `taochronos serve` on this machine) and never sent to the site's server; made anonymous as it is read
  (names and doctors' names to pseudonyms, identity and record numbers to codes, telephones, addresses and e-mails
  removed, a birth date to its year; such numbers in free text replaced; a freely written name may be missed); what the
  model reads (statistics and the rows it asks for, anonymous, sent with the conversation to the chosen model service;
  the file's name too); never recorded; kept in this browser until removed; statistics describe, they do not infer a
  cause or advise treatment.
* **Uploading** reads the file and attaches it to the next message as a chip (门诊处方.csv · 表格 120 行 · 9 列); a message
  may carry it alone (the page asks for an overview).  The model reads, with the message, the dataset's id, name,
  columns and their types — never its rows — and is offered the 我的资料 tools while there is data: `mydata.list`,
  `mydata.read`, `mydata.search`, `mydata.describe` (descriptive statistics), `mydata.compare` (Kruskal–Wallis, χ² or
  Fisher, Spearman) and `mydata.prescriptions` (drugs, doses, pairs, rules, clusters, groups compared, the nearest
  compositions of the classics).  Their figures and three-line tables are drawn and downloaded as a study's are; a row
  or passage the answer cites, `[[mine:…]]`, is a chip checked like any citation (门诊处方.csv·第 1 行), opened in the
  side panel.
* **资料** in the side panel lists the datasets: size, columns and types, what was taken out, its id; **附到消息** attaches
  one to the next message, the bin removes it (and its rows from the conversation's chips), **全部删除** removes all, and
  **资料如何处理** repeats the notice.
* **Where it is read**: by the browser's runtime (and kept in IndexedDB, given back at the next visit), or by
  `taochronos serve` on this machine (kept in its memory).  When the page works with the site's own server or a server
  elsewhere, it starts a runtime of its own in the browser for the data and sends that runtime the 我的资料 tools, the
  `mine:` passages and the normalisation of their quotations — the server is sent none of it, and would refuse it.
* **Never recorded**: a conversation that carried a dataset or called a 我的资料 tool sends no conversation record, even
  when the visitor agreed to records.

## 设置 → 统计 — how much the site is used, and from where

The site's owner reads the site's usage under **设置 → 统计**, over the last 7, 30 or 90 days: pages opened and their
visitors (the site's Worker counts a page a browser opens — crawlers and scripts are not counted), questions asked of
道乃久默认服务, the model calls they took and who asked (the relay counts each call it lets through; a tool round of a
question is a call, not a question).  Four stat tiles with the change against the days before, a day-by-day line for
pages and one for questions, and the countries and China's provinces by pages opened — every chart switches to a table.
A day runs on Beijing time.  Visitors are counted once a day by the sentinel's hashed key (dropped after two days); a
place is the country and first-level region Cloudflare puts the request in (ISO 3166-2; the page names China's
provinces); no address is kept (`security/usage.js`, `/api/stats` on the site, `/v1/stats` on the relay).

The counts are read with a token: create the repository secret **`STATS_TOKEN`** (16 characters or more, e.g.
`openssl rand -hex 24`), let the site and relay workflows deploy (a push, or Run workflow), then enter the same value in
the pane once — it is kept in that browser only, and **忘记令牌** removes it.  `STATS_PUBLIC = "1"` in both
`wrangler.toml` files shows the counts to every visitor instead; `STATS_UTC_OFFSET` moves the day boundary.  The pane
and the endpoints tell a visitor nothing of how the counts are opened — that is here only: without the token set (and on
a page with neither the site's server nor the relay: a local server, the GitHub Pages copy) the pane says just
统计尚未开放, and with it set it asks for the token and nothing more.

## What the model is offered

`taochronos.chat.catalog` turns the tool mesh into function schemas.  In **精选 + 目录** mode (the default) the model
sees nineteen tools directly — `classics.search`, `classics.get_passage`, `classics.list_books`, `classics.canon`, `kg.term`, `kg.claims`,
`study.formula`, `study.herb`, `study.term`, `study.concordance`, `study.commentaries`, `study.translate`,
`study.network`, `study.compare`, `study.usage`, `study.protocol`, `validation.verify_quote`, `audit.claim`,
`modern.safety` — and reaches the others (`study.family`, `study.properties` and `study.incompat` among them) through
`taochronos_catalog` (families, tools, parameters) and `taochronos_call`.  In **全部工具** mode it sees every tool.
Either way it also has the engine: `taochronos_research` (a full multi-agent discovery run: contract → evidence →
D1–D5 → hypotheses → falsification → gates G0–G8), `taochronos_session` (its report, hypotheses, evidence) and
`taochronos_ask` (the V2 skill workflow).  While the visitor has data in 我的资料 the page adds the six 我的资料 tools
(the runtime lists them apart: `catalog("core")["mydata"]`), routed to the runtime that holds the data.

The model acts as an agent-principal actor with read and analysis permissions only (and `mydata:read`, which no research
agent holds: a research run never reads the user's data).  It is never offered
`kg.propose_change` (a proposal to canonical knowledge is a person's act) or Code Mode (`research.run_code`) unless the
local server is started with `--code-mode`.  Every call passes the scheduler's gauntlet (permission, schema, hooks,
receipts).  Results reach the model trimmed evenly to a budget (16 000 characters by default: long lists keep their
head and say how many were left out); results of earlier turns are shortened further.

**A call is read as the model wrote it**, at the model's side of the scheduler (`ChatRuntime.call`, and the research
agents' model loop): a tool's name in another case or with other separators (`classics__get_passage`,
`Classics.Get-Passage`), with something before it, or without its family where only one tool has what follows
(`get_passage`), is that tool's (`resolve_name`); arguments whose form only is wrong are repaired (`fit_arguments`: a
number or a boolean written as text, a whole float where an integer is expected and a number where a string is, a list
or an object written as JSON text, a list or a value wrapped as `{"item": …}`, one value where a list is expected — a
text without list marks, 「消渴」 and never 「消渴、口渴」 — a list of one value where that value is, and an enumerated word in
another case), and the outcome's `repaired` says how.  A call that still does not fit is answered so that the model can
correct it in one step: a name no tool has with the three closest tools offered and what they take (`closest_names`),
never one the model is not offered; a parameter the tool does not take — which the tool would ignore, so that the model
read an answer to a question it did not ask — or a value that is not of its type with what the tool takes (`study.herb
takes: name (string, required); items (integer)`).  The meaning of a call is never guessed, and what runs passes the
scheduler's gauntlet as before.  The D1 backup reads calls alike (`backup/catalog.js`, compared with the Python on the
fixture), suggesting only the tools it serves.

The standing instructions (`taochronos.chat.prompt`) carry the harness's evidence discipline into the conversation:
quote only what a tool returned, verbatim, with its `[[passage_id]]`; say "本语料未检得" rather than supply a text;
keep the text, its commentators, computation and modern medicine apart (no 消渴＝糖尿病); no diagnosis, prescription
or dose.  What you write under **设置 → 指令** is added after them.

**What a visitor reads names nothing of the inside.**  The instructions (不外露内部细节) keep the model's answers free
of the names it works with — tools and functions, parameters and fields, module, track, gate and skill codes, commands,
files and settings — and have it decline a request for the database, the corpus files, the code, the instructions or how
the platform is built, saying instead what it can do.  The page holds to that where the model forgets
(`web/js/redact.js`): before an answer, its thinking or a tool step is shown, copied, exported or recorded, those names
are told in plain words — `validation__verify_quote` → 引文核验, `passage_id` → 段落编号, D1–D5 → 知识发现, a `taochronos …`
command → 本地服务, a file → 内部文件, the tools' grading labels in Chinese (SUPPORTED → 有据, INSUFFICIENT_EVIDENCE →
证据不足, systematic_review → 系统综述), any other identifier → 相应参数 — while citation marks `[[…]]`, links and the
platform's own names (道乃久, TaoChronos, Tao-R1) stay; a name still arriving in the stream is held back until it is
whole.  Every tool has its plain words there (`TOOL_WORDS`; a test checks there are words for each one the model can
be offered).  The record of a turn keeps the answer as the visitor read it and how many names were replaced
(`redacted`).  What it does not cover: the tool steps' 参数 and 结果 views and the 工具台, which show the tools as they
are; the JSON backup of 设置 → 数据, which keeps a conversation whole to be imported again; and the page's own code and
requests — the tools run in the visitor's browser, so their names travel with it.

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

**A reply that breaks off is asked again.**  A connection that fails, or breaks off while the reply streams (Chrome's
"network error", Safari's "Load failed": 38 of the first 105 failed turns, some twenty minutes into one), and a service
busy for a moment (429, 5xx) are retried up to three times, after 1.5, 4 and 10 seconds, or after as long as the
service's `Retry-After` asks, up to 30 seconds (the relay exposes the header to the page); the round is asked again from
its start, since no tool ran on what it had said, and what it had shown goes.  A refusal that asking again soon does
not change is told at once: the visitor's or the service's allowance for the day (`daily_limit`, `total_limit`), an
address blocked, the service not set up, its own key refused or its quota spent, a provider's quota spent.  A browser that has no
body to read a reply from as it arrives (an older Safari) reads it whole.  In the last three rounds of tools a turn may
run (设置 → 运行环境 → 每轮最多工具步数, 16 by default), the model is told after each how many it has left, and at the last that it is
to answer from what it has.

**自定义 API** — an endpoint not in the list, set by hand (**设置 → 模型 → ＋ 自定义 API**; several can be kept): a name, the
wire format (OpenAI-compatible, or Anthropic Messages through the SDK), the base URL (the page appends `/chat/completions`,
or, ticked, calls the address as given — e.g. Azure's `…/chat/completions?api-version=…`), the model, the key (sent as
`Authorization: Bearer`; left empty when the service wants another header), extra request headers and body parameters as
JSON (a malformed field is shown and not taken), the name of the output-length parameter, whether the reasoning the model
streams is sent back in later turns (`reasoning_content`, `reasoning_details`, or not at all), and whether it takes
images.  The model must support tool calling for the agent to read the classics.  The page names the endpoint (the chip's
tooltip, under each answer); the instructions name no model ([ADR 0014](adr/0014-identity-fixed-reply.md)).

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
  tile 道乃久默认服务 · 免密钥 in 设置 → 模型, no key or address to fill in), and the opening screen says so.  The page is
  patient — it is downloading its runtime over the same link: 10 s, then 15 s, and if the relay did not answer, again 20,
  40, 60 and 80 seconds later, and once more before it asks a visitor for a key.  When it does not answer, the page is what
  it was before: the visitor's own key.
* Both Workers carry the sentinel (`security/sentinel.js`, [ADR 0018](adr/0018-sentinel-and-edge-rules.md)): every request
  is fingerprinted and scored, a scanner path refuses its address, a flagged request is kept whole for the owner
  (`data/security-logs/`), and the edge's own rules are code (`security/rules.yaml`); the relay also counts an answer's
  tokens against the visitor's day.
* The relay accepts the page's origins only, its own model only (by its public name, Tao-R1), caps the output, and
  counts use per visitor (a hash of address and day; addresses are kept nowhere) per minute and per day, and in all per
  day (`relay/wrangler.toml`).  Its refusals are sentences a visitor can act on (wait, check an option, or use one's own
  key).
* **Conversation records** (the test period): before a visitor's first question the page says what would be recorded
  and why, and asks — 同意并继续 or 不记录; the choice stays in that browser and can be changed at any time under
  设置 → 数据.  A visitor who agreed sends, after each finished turn, one compact record to the relay: the question, the
  answer, the tools called, how the citations were checked, the model, token usage and timings — never a key, the
  settings or an address (`web/js/records.js`, `relay/src/relay.js` keeps only those fields).  The relay holds the records
  until `.github/workflows/chat-logs.yml` collects them, every hour, into `data/chat-logs/YYYY/MM/DD.jsonl` in this private
  repository, and deletes them once the commit is pushed (`relay/collect.py`).  The records never enter the published
  site.  If the repository is ever made public, `data/chat-logs/` must be moved out first.  A conversation that touches
  the visitor's own data (我的资料) is never recorded, whatever they chose.

**The page names no vendor, and nothing it receives does.**  The default service appears as 道乃久默认服务 and its
answers as Tao-R1 — on its tile (免密钥 · 直接提问, with no model to choose), in the chip's and the composer's tooltips,
under each answer, in exports and in the connection test — and the presets of the model behind it are not offered: the
site's build leaves them out (`taochronos web build --unlist minimax,minimax-global` in `site.yml` and `pages.yml`; the
local server's page offers every preset, and its proxy reaches them all).  Between the page and the relay only the
service's own terms travel (`relay/src/relay.js`, `publicText`): the relay's health names the model Tao-R1; the page asks
for Tao-R1 and sends nothing only the upstream would understand (the relay adds `reasoning_split`, and renames the
reasoning formats the page sends back); in the replies the model reads Tao-R1 and the reasoning formats `Tao-…`, the
upstream's own fields (`base_resp`, the `*_sensitive` flags, `usage.total_characters`) are dropped, and an upstream error
— an HTTP error, a failure reported in a 200 body or inside the stream — reaches the visitor as a sentence of the
service's own, never the upstream's text (the relay logs its status only).  The page shows the service's errors without
the model client's preamble, and brings conversations kept by an older page in line as it loads
(`web/js/providers.js`, `publicConversation`).  The records, which are the institute's, keep the model that answered: the
relay turns the public name back.  The consent notice speaks of recording to the institute's server.  Nor do the
standing instructions name it: asked what it is built on, the assistant neither names nor denies it, and a question only
about who answers gets the page's fixed reply ([above](#道乃久--tao-r1--impf-ai)).

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
then the outcome), `GET /api/session/<id>?what=summary|report|hypothesis|evidence`, `POST /api/llm` (model proxy),
`POST /api/data {name, data}` (a file of the user's in base64) · `GET /api/data` · `POST /api/data/remove {id}` ·
`POST /api/data/clear` (我的资料 — only when the server is bound to this machine: one other machines reach answers 403).

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
harvested from the full corpus is left out), `runtime/corpus.sqlite.xz` (the 要籍语料 as a store without its index, 13.3 MB;
built from `corpus/web` by the build, the same bytes for the same pack; `TAOCHRONOS_WEB_XZ_PRESET` trades size for build
time, the tests use 1), `runtime/boot.json` (the runtime's info and catalogs, for the conversation to start while it
loads), `runtime/manifest.json` (sizes and SHA-256; the worker keeps the archives by content in IndexedDB, and the corpus
once indexed), `providers.json` (from `taochronos.chat.providers`) and, by default, the Pyodide core with the PyYAML and
SQLite wheels, checksums verified against `pyodide-lock.json`.  Archives are deterministic.  Every path is relative.

For search engines: the page is a script, so `index.html` carries what a crawler reads without it — a short static
introduction (`.intro-static`, replaced by the conversation once the script runs), the canonical address, Open Graph and
a schema.org `WebApplication` — and `about.html` describes the platform in full.  The build writes `robots.txt` (the
pages indexed, `runtime/` and `pyodide/` not; crawlers that only gather training data — `TRAINING_CRAWLERS` in
`build.py`, never a search engine's — asked to stay away) and `sitemap.xml` (`/`, `/about`, `/attribution`) for the site's address
(`--site`, default `https://chat.impf.ai`; no lastmod, so the build stays deterministic).  To be indexed: verify the
domain in Google Search Console (a DNS TXT record, added in Cloudflare), submit `https://chat.impf.ai/sitemap.xml`, and
request indexing of the home page.

## Tests

`tests/test_chat.py` — the catalog (what is offered, what never is, valid names and schemas), calls by either name,
a call as the model wrote it (a name in another form, arguments repaired, a parameter the tool does not take refused,
the closest tools for an unknown name and never one the model is not offered), failures as results, meta-tools, the system prompt and the identity (道乃久, Tao-R1, IMPF-AI; the platform introduced as the fixed reply does, no model named or denied), trimming and citations, research runs and
their sessions, the V2 workflow, every server endpoint, CORS and Private Network Access, the origin and host checks
(the server's own pages on any address), the access token (refused without it, the proxy too; generated for any address
but loopback), the proxy (streaming, allow-list, the SDK path form, `--env-keys`, `--allow-host`), background research, the
site build (with the corpus store), and `home.zip` carrying the alias layer (its two built files, no file or record of a local
list, the directory under 150 KB deflated).  `tests/test_web_corpus.py` — the 要籍 list (ranked, metadata only, the classics first,
nothing modern, open where a source is openly licensed, its open witness the pack's first), the choice of witnesses
(openly licensed first, 笈成 last among them, never a source in `NEVER_PACKED`), budgets kept as whole chapters spread
through a book, the pack → a store with the same bytes → indexed once → read by the harness, the index in two phases
(the first-ranked works first, the rest in slices, seen by a connection already reading) and the shipped pack under the
`web-canon` profile (533 works in rank order, an openly licensed transcription with its own terms, any other with the
terms the site carries it under; a 宋本 found for a punctuated 伤寒论 clause; `classics.canon` for what it lacks).
`tests/test_corpus_store.py` — on a store: a quotation found whatever its punctuation and in either script, across a
witness's own marks, never with a changed or missing character; outside a session `classics.list_books` lists every
book with its filters and `kg.claims` / `kg.neighbors` read the passages that write the term.  `tests/test_web_client.py` — the
client's logic under Node (cumulative and incremental streams, a reply that breaks off asked again and one read whole,
which refusals are retried and how long after, the rounds of tools left named to the model, history rules, dangling
tool calls, citation pairing, which
questions get the fixed reply and which go to the model; the alias badges — labels, the names merged, the asked name found
for a hit, the flags' words, every card of a search marked with its badges or with none; the charts' checks, CSV, Markdown tables, colours and axes; a box
plot's numbers, a forest plot's log axis, a tree's checks; CRC-32, PackBits, a TIFF's directory, a PNG's pHYs and a ZIP;
three-line tables' heads, italics, LaTeX, CSV, Markdown and Word XML) and
the page in Chromium against scripted providers (`tests/web_mock.py`): a MiniMax-style stream (cumulative
`reasoning_details` and content, streamed tool arguments) and a Claude stream through the real SDK, checking the
requests (`reasoning_split`, `max_completion_tokens`, `reasoning_details` and thinking signatures replayed, fallbacks),
the chip states, the highlighted passage, Tao-R1 in the chip and under the answer, and persistence across a reload; and
a page served elsewhere (as on GitHub Pages) connecting to a server in one step, using it again after a reload, and a
token taken from the address (and its absence reported); an API set by hand (address, model, key, headers, parameters —
checked in the request it makes); the default service (a stand-in relay): asked at once without a key, no key sent by the
page, the consent question once, a turn recorded only after 同意 (its fields, no key or settings), none after 不记录 or
once switched off under 设置 → 数据, a relay slow to answer (6 s) or missed once still found, and the page asking for a
key while the relay is down; a question about the assistant answered by the page (no model called, no key needed, the
same words when regenerated, recorded as `fixed`, replayed to the model when the conversation goes on) while one that asks
more goes to the model, asked for no thinking, showing and storing none; a study's figures and tables under its step (tabs
图 1 … 表 1 …, a chart as its table and in the journal style, exported as PNG at 300 dpi and TIFF at 600 dpi read back with
their resolution, an 85 mm SVG, CSV; all the figures in panels, all the tables in one Word document; a table downloaded as
LaTeX and copied as HTML), a ```chart block drawn in the answer and a table it writes (its caption and notes gathered, saved
as Word and read back), the model told only the titles, and the 工具台's charts; and, with
我的资料 (`tests/test_userdata.py` too): the notice, a GB18030 CSV uploaded to a server on this machine, made anonymous,
analysed, a `mine:` row cited and checked, nothing naming a patient sent to the model and no record sent; the browser's
own runtime (the worker's code and IndexedDB, with a stand-in for Pyodide whose Python runs in the test) keeping a
workbook across a reload; and the page working with a server elsewhere keeping the data in the browser; and, with
`TAOCHRONOS_PYODIDE_E2E=1`, the built site in Chromium on an http:// origin like the published one (no Cache API) —
Pyodide, the 要籍语料 downloaded, the first-ranked works indexed before it answers and the rest in the background, the
store kept in IndexedDB and a reload that downloads no corpus, a turn answered on it.  The browser tests are skipped where Playwright or Chromium is missing.  `relay/test/relay.test.js`
(`node --test`, in CI) — the Worker's handler and its two stores on SQLite: the key added by the relay and never shown,
origins, models, output cap and body size, the three limits and a new day, MiniMax's refusals turned into plain messages, no reasoning let through when the page asks for none (however the stream is cut),
the records reduced to their fields, and the collector's token, cursor, deletion and ids never reused.
`tests/test_relay_collect.py` — `relay/collect.py` against a stand-in relay: records pulled once, by day, the cursor
committed with them, deleted only once held, a deployment checked (and a refused key explained).  The site build writes
`site.json` only when given a relay, carries the texts' attribution, and never a conversation record or a key.

## Limits

* In the browser the corpus is the 要籍语料: 533 of the 535 key works, the first whole, the others in chapters spread
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
* 我的资料 reads no PDF, scanned image, .xls or .doc (it says what to save them as); it finds the names a table's heads
  or a label (姓名：) mark, not a name written freely in a text; a server's data lives in its memory (gone when it
  stops); with the site's server, the first upload starts the browser's runtime, which downloads it on a first visit.
