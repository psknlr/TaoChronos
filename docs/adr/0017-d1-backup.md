# ADR 0017 — The full corpus in D1: the site's backup without a container

**Status:** accepted · 2026-09-30 · complements [ADR 0016](0016-site-and-full-corpus-on-cloudflare.md): the container
stays the full service wherever the account has one; the browser's 要籍语料 ([ADR 0013](0013-canon-corpus-in-the-browser.md))
stays the last fallback

## Context

ADR 0016 serves the full corpus from a container, and Containers need the Workers Paid plan.  IMPF-AI's account is on
the Workers Free plan, so https://chat.impf.ai has the site but not the full corpus: the page runs the 要籍语料 in the
browser.  The free plan does have Cloudflare D1 and the site's Worker, within hard limits:

| | Workers Free / D1 Free |
|---|---|
| D1 | 10 databases, 500 MB each, 5 GB in all; 100,000 rows written and 5,000,000 rows read a day; a row ≤ 2 MB; a statement ≤ 100 KB of SQL and ≤ 100 bound parameters, ≤ 30 s; FTS5 |
| Workers | 10 ms of CPU a request; 100,000 requests a day; ≤ 50 D1 queries a request; the script ≤ 3 MB compressed |

Every index entry counts as a row written, so the question is not only whether 958 books and 122 million characters
fit in D1, but whether they can be written in a reasonable number of days, and whether a search over them can be
answered in 10 ms of a Worker's CPU.

## Decision

1. **The site's own Worker answers the API from D1 when there is no container.**  `site.js` passes `/api/*` to the
   container when it is bound (`CORPUS`); otherwise, when the D1 import is complete and matches the deployment
   (`D1_BACKUP`, the version the databases must hold), `cloud/site/src/backup` answers `/api/info`, `/api/catalog`,
   `/api/call` and `/api/passage` in the Python server's shapes; otherwise 503, and the page falls back to the browser as
   before.  The info says it is the backup (`runtime: "d1"`, the label 全量语料（备份）, a paragraph in the standing
   instructions: what is computed, what is precomputed, what needs the server); `proxy: false` as before.  Research runs
   and sessions answer 501 with the reason.
2. **The layout** (`taochronos.chat.d1`, from the store the site may publish — `WEB_SOURCES` only, never
   `NEVER_PACKED`, checked by the exporter itself):
   - **chunks**: the passages of one book with one temporal context (597 books alternate dated layers) in reading order,
     at most 64 passages and 4,000 characters: 41,869 rows for 2,038,497 passages.  They are numbered (`cid`) in the order
     of their year, so a time bound is a range of numbers (the first chunk of each year is in the statistics).  `body`
     holds the passages as the tools cite them; `norm` their normalised text, one character a token (the page's
     normaliser, ported to JavaScript and checked identical on all 2,038,497 passages).
   - **fts**: FTS5 over `norm` with the ascii tokenizer (every character is a token; ASCII marks and the passage breaks
     are tokens no phrase runs across), contentless, without document sizes, built from the chunks by SQL in 23 large
     statements (a segment each, `pgsz` 64 000, no automerge) and optimized once.  D1 counts a row per chunk indexed; the
     index's own shadow rows are not counted.
   - database 0 also holds **books** (cards and chunk maps: a passage id finds its chunk without an index), **seqmap**
     (for the books whose passages fall into several temporal groups or whose numbering has gaps, which group each
     passage is in: a character a passage, 601 rows), **lex** (the lexicon by first character), **results** (the
     precomputed tools, below) and **meta** (the statistics; `complete` is written last).
   - five databases, `taochronos-d1-0` … `-4`, filled to about 320 MB (database 0 keeps room for the rest), bound as
     `D1_0` … `D1_4`.
3. **The import is resumable and budgeted** (`.github/workflows/d1.yml`, daily shortly after 00:00 UTC and on *Run
   workflow*).  Every statement (once the tables are made, an INSERT) is within D1's limits (≤ 90 KB, ≤ 100
   parameters) and atomic; where the import has got to is read from the databases themselves (the last chunk, the
   last book, …, and the index's progress, which its own trigger writes in the same statement), so an interrupted run
   resumes without writing anything twice.  A run sends a statement only if its upper bound of rows still fits the
   day's budget (90,000 of the 100,000; the day's use is kept in database 0, recorded at least every 5,000 rows, so
   that a killed run under-counts it by less than the margin), and stops at 00:00 UTC.  The job checks first that the token may use D1 (else a warning: *Account · D1 · Edit*, `cloud/SETUP.md`),
   creates the databases if missing, and fetches and checks the store as the container's build does.  Another store,
   normaliser or layout is another version: the databases are made anew.  When the import is complete the version is
   written to the KV namespace (`deployed/d1`) and the site is deployed again; `deploy.sh` binds the databases and sets
   `D1_BACKUP` from it.
4. **Three kinds of tools** (the table below; the tests hold every one of the 74 to one kind):
   - **live** (14): computed by the Worker — the SQL does the scanning, the Worker reads little.  `classics.search` in
     three steps: the chunks the index ranks first for the query's surfaces in each database (and the earliest and
     latest writing each surface, and those writing a targeted sense's head term); in SQL, the passages of those chunks
     that write a surface, with the counts the routes need (the query's bigrams, the variant spellings in the raw text,
     a sense's cues and anti-cues); in JavaScript, the four routes that need no server model — bm25, temporal, variant,
     sense — and the server's reciprocal-rank fusion.  `verify_quote` finds every occurrence of the quote's longest run
     in the chunks the index matches (a recursive query) and runs the verbatim and normalised tests in SQL.
   - **precomputed** (16): computed in CI by the Python tools themselves on the full corpus, for the keys that can be
     listed (the 1,200 most written formulas, 600 drugs, 300 pairs, the curated terms, every book, every canon work, the
     clauses of 伤寒论 and 金匮要略 …: 11,765 keys), stored compressed in `results` and served by the canonical key
     (a traditional or variant name finds its entry; a key not computed is said to be so).
   - **unavailable** (44): the research engine, the D1–D5 analyses (they read a session's working set), and the tools
     that need the server's models or a computation over thousands of passages with open-ended arguments.  A call says
     which, and the catalog offers only what is served.
5. **CPU**: the per-request work is kept small (candidates chosen and measured in SQL; the normaliser on a table of
   code units; verification in SQL), and the code is run once over made-up databases in memory when the isolate starts
   (`warm.js`), so that the first request in a fresh isolate does not pay for compiling it.

## Measurements

Measured on the store of `cloud/store.json` (958 books, 2,038,497 passages, 122,219,380 characters) with the exporter
into local SQLite and into the local D1 emulator (wrangler's platform proxy: workerd's own D1 and its accounting of
rows), and the backup's code in Node 22 over the local files.

**Sizes.**  Five databases of 238, 313, 310, 306 and 262 MB (1.43 GB; 2.3 MB of books, 1.5 MB of lexicon), each under
D1's 500 MB and together well under 5 GB; the precomputed results, 45 MB compressed, take some 70 MB more of database 0,
which ends near 280 MB (in the simulated import below, 37 MB of results — the clauses' answers were smaller then —
took 56 MB).  The index is 36–49 MB of each (the chunks 159–205 MB); its optimize writes it once more before freeing
the old segments, so a database peaks at 362 MB.  The Worker's script is 395 KB (139 KB compressed).

**Rows written.**  The corpus is 11,934 statements; the rows as the emulator's D1 reports them (one run, from empty),
beside the plan's expectation and the upper bound each statement is checked against before it is sent:

| Step | Statements | Rows (D1) | Expected | Upper bound |
|---|---:|---:|---:|---:|
| schema | 65 | 95 | 105 | 205 |
| chunks | 11,731 | 41,869 | 41,869 | 41,869 |
| fts (a row per chunk indexed, and the progress) | 23 | 41,892 | 41,892 | 49,646 |
| optimize | 5 | 10 | 10 | 15,338 |
| books | 39 | 958 | 958 | 958 |
| seqmap | 28 | 601 | 601 | 601 |
| lex | 40 | 1,916 | 1,916 | 1,916 |
| meta | 3 | 3 | 3 | 3 |
| **corpus** | **11,934** | **87,344** | **87,354** | **110,536** |

By database: 17,767, 20,496, 17,224, 16,612 and 15,245 rows.  SQLite's own count, which includes the index's shadow
rows, is 107,171: were D1 ever to count those too, the corpus alone would take two days.  The slowest statement took
under a second in the emulator (the index's optimize, 0.99 s; a segment of the index, 0.85 s; D1 allows 30 s).

The results are 11,763 rows (of 11,765 keys: two canon works have no witness in the published store) in some 550
statements, and a row recording their key list.  In all 99,107 rows as D1 reports them, and the runs' records of the
day's use (a row every 500 statements or 5,000 rows): **two days** at 90,000 a day — the first run writes the corpus
and the first results, the second the rest.  Through the REST API the first run should take about two hours (an
estimate, not measured here: a request and a pause of 0.2 s for each of 11,934 statements — now a request
started 0.3 s at least after the one before, which saves the pauses; the emulator imports the corpus in five and a half
minutes); the second is mostly the Python tools' time.  Computing the results from nothing
takes about two hours here (measured: the store unpacked in 19 s and indexed in 2¼ minutes, the key list in 12 s, the
11,765 keys in 106 minutes, 7 more since the clauses are computed as punctuated): the drug pairs, 12 s a key, are an
hour of it (`study.pairs` computes the whole table of pairs for each drug), the formulas 18 minutes, the clauses 10;
the first key of a tool builds its caches (the network's harvest 2 minutes, the taboo survey and the schools a minute
each, the citation graph 47 s).  The first run computes only the few minutes of results the day's budget has room for.
The daily job now computes them in as many worker processes as the runner has processors and memory for (`--workers
0`, each with its runtime over the same store, the results imported in the same key order, the study caches written
atomically): some half an hour on four processors, an hour on the two of a private repository's runner (estimates; each worker
builds its own caches in memory).

**The daily run, simulated** (the local emulator; `TAOCHRONOS_D1_DAY` sets the day).  Day 1: the first run was killed
after five minutes — its whole process group, the emulator included, in the middle of a statement — having written
75,663 rows of the corpus and recorded 75,247 as the day's use (the 416 since its last record are what the margin is
for).  The day's second run read from the databases where the first had stopped, sent none of the statements already
applied, wrote the rest of the corpus (586 chunk rows, the index's 7,615, the books, seqmaps and lexicon) and the first
3,066 precomputed results, and stopped at 89,992 of the 90,000 recorded — 90,407 in fact, under D1's 100,000.  Day 2:
the run found the corpus complete, computed the other 8,697 results — an hour and forty minutes, nearly all of it the
Python tools' — and imported them in 350 statements, then the statistics and `complete`: 8,700 rows.  Day 3:
everything imported, the run wrote nothing.  The databases the three days left are table for table those of the
one-shot import (the results and their count in the statistics apart), the index finds the same chunks for 15 queries
in each, and the Worker's answers over them, in Node and in workerd (`wrangler dev`), are the local build's for all 75
calls.

**The Worker's CPU per call** (the main thread's time in Node less the SQL's; D1's own work is not the Worker's; the
results parsed from JSON as the binding hands them over).  Warm (an isolate that has answered before; 75 calls, two
runs each, three times): `classics.search` median 2.3–3.0 ms, 95th percentile 4.7–6.3; `verify_quote` median 2.0–2.3;
every other live tool under 2.3 ms (`list_books` of all 958 books 3 ms); now and then a garbage collection of the test
process adds 10–20 ms to one call.  The first call in a fresh isolate, after the start's warm-up (Node's own lazily
loaded built-ins loaded first, as workerd has them from the start; five fresh processes a call, the median): a search
4.0–8.9 ms (eight queries, median 5.0; but four runs in forty above 10, at most 11.8), `verify_quote` 2.1–4.2,
`get_passage`, `list_books`, `kg.term` under 2, `collate` 2.4.  Without the warm-up the first searches took 10–16 ms.
The warm-up itself takes some 35 ms of the isolate's start (three rounds; six made some first searches faster and
others slower, and the start longer).  D1 statements per call: search 4–16, `verify_quote` 3–10, the rest at most 6 (the
limit is 50); the longest statement a search sends is 18 KB, for a question naming thirteen diseases.  **Rows read**
(D1's own count, the emulator): a search 2,700–12,000, median 5,500 — the passages of the candidate chunks, which the
filters read in SQL; `verify_quote` 3–12,000; a precomputed tool 1–4; the other tools a handful (`list_books` scans the
958 cards: up to 2,800).  So some 900 searches a day within the 5,000,000.

**D1's own limits, found in the emulator.**  A compound SELECT may have at most five terms (SQLite's default is 500):
the search's candidate query, a UNION ALL of the ranked chunks and each surface's earliest and latest, is nested five
to a compound.  The tests' D1 adapter (node:sqlite) holds every statement to D1's limits — 100 KB, 100 parameters,
five terms a compound — so the tests would fail on such a statement.

**Parity with the Python runtime on the same store** (75 calls, `classics.search` 31 of them).  The site's Worker itself,
run by workerd (`wrangler dev`, local) over the databases the emulator imported, answers all 75 exactly as the backup's
code does in Node over the local build (and those databases are table for table the local build's, and the index
finds the same chunks):

- every call of the other live tools (44: passages, books, canon, terms, normalisation, assessment, collation, pages,
  provenance, quotations, metrology, safety, modern evidence) gives the same result as the Python tool's, field for field
  — including `verify_quote`'s 500 hits for a common quote, in the same order.  The fixture of the tests carries the
  Python tools' own answers to 36 calls, and the backup must equal them in CI.
- `classics.search`: the query analysis (terms, surfaces, variant spellings, time bounds, intent) is identical for all
  31 queries.  The hits are not the server's: of the server's top 10, the backup has 14 % (15 % against the server
  restricted to the same four routes; the first hit is the same in 5 of 31), and 51 % of the backup's hits are in the
  server's top 50.  Intended: the server fuses seven routes over 4,000 candidates from a passage-level index, which
  favours very short passages (a line reading only 黃連); the backup fuses four routes over the passages of the densest
  chunks, which favours passages rich in the query's words.  Every hit writes a query surface (or matches a targeted
  sense), time bounds and the earliest attestations are honoured, and the server's dense, graph and citation routes —
  the lineage notes (`inherits …`) — are not there.
- the precomputed tools (21 calls, served from the results the simulated import computed, in Node and in workerd): 15
  are the Python tool's answer exactly; a traditional or variant name (桂枝湯, 黄耆) gets its canonical entry's answer,
  which names the canonical form; a formula not precomputed is said to be.  `study.senses` orders ties by string
  hashing, so its lists differ from one Python process to the next — the server's as much as the backup's (the import
  runs with a fixed seed, so that a result computed again is the same).  A clause's commentaries and concordance had
  been computed from its bare characters, which find other witnesses than the punctuated clause a reader sends (the
  concordance's probes follow the punctuation); computed now as the witness punctuates the clause, they are the tool's
  answer to it but for the text echoed (checked on the full corpus).

## The 74 tools in the backup

| Tool | Family | In the backup | Why |
|---|---|---|---|
| `classics.search` | retrieval | live | bm25, temporal, variant and sense routes; dense, graph and citation need the server |
| `classics.get_passage` | retrieval | live | |
| `classics.list_books` | retrieval | live | |
| `classics.canon` | retrieval | live | |
| `classics.lineage` | retrieval | unavailable | lineage edges come from claims extracted into a session's or the server's working set |
| `kg.term` | knowledge | live | |
| `kg.claims` | knowledge | precomputed | claims of the curated terms and concepts on the whole store (323) |
| `kg.neighbors` | knowledge | precomputed | co-occurring terms of the same (323) |
| `kg.extract_claims` | knowledge | unavailable | the claim-extraction rules and knowledge graph are the server's |
| `philology.normalize` | philology | live | |
| `philology.assess_passage` | philology | live | |
| `philology.collate` | philology | live | |
| `philology.inspect_page` | philology | live | |
| `vision.compare`, `vision.layout` | philology | unavailable | need OCR input and the server's layout code |
| `validation.provenance_chain` | validation | live | |
| `validation.verify_quote` | validation | live | |
| `validation.gates` | validation | unavailable | gates G0–G8 judge a research session's objects |
| `audit.claim`, `graph.evidence` | validation | unavailable | decomposition and the six-layer graph run the server's tools and models |
| `study.metrology` | study | live | |
| `study.formula` | study | precomputed | the 1,200 formulas most written in the corpus |
| `study.herb` | study | precomputed | 600 drugs |
| `study.pairs` | study | precomputed | 300 drugs, and the survey |
| `study.network` | study | precomputed | 600 formulas and the curated findings (812) |
| `study.term`, `study.reading` | study | precomputed | the curated and terminology terms (334; 323) |
| `study.senses` | study | precomputed | the terms with period-bound senses (27) |
| `study.names` | study | precomputed | the curated terms with other names (185) |
| `study.commentaries`, `study.concordance` | study | precomputed | the 2,833 clauses of 伤寒论 and 金匮要略 (the open witnesses), found by their normalised characters, computed as the witness punctuates them |
| `study.taboo` | study | precomputed | every book, and the survey (959) |
| `study.witnesses` | study | precomputed | every canon work (348; two have no witness in the published store) |
| `study.citations` | study | precomputed | every canon title, and the survey (351) |
| `study.schools` | study | precomputed | every school, and the survey (11) |
| `study.punctuate`, `study.translate`, `study.clause`, `study.entities`, `study.argument` | study | unavailable | the punctuation model, the rules of entities and discourse, the layered translation are the server's |
| `study.authorship`, `study.cards`, `study.cases`, `study.chain`, `study.dating`, `study.disputes`, `study.fragments`, `study.glosses`, `study.layers`, `study.places`, `study.reuse`, `study.stemma`, `study.trajectories`, `study.transmission`, `study.variants`; the case exploration added later (`study.casefind`, `study.similar`, `study.case`, `study.casecompare`, `study.modifications`, `study.treatments`) | study | unavailable | a computation over many passages (alignment, classification, extraction, tests) with open-ended arguments: beyond 10 ms and not to be listed ahead of time |
| `analysis.association_rules`, `analysis.communities`, `analysis.concept_drift`, `analysis.contradictions`, `analysis.formula_evolution`, `analysis.link_prediction`, `analysis.lost_knowledge`, `analysis.missing_sources`, `analysis.temporal_profile` | analytics | unavailable | the D1–D5 analyses read a session's working set of retrieved passages and their claims |
| `bridge.map`, `bridge.phenotype`, `bridge.reverse` | bridge | unavailable | the modern mappings (HPO, ICD-10) and profiles are the server's |
| `literature.modern_evidence` | literature | live | |
| `modern.safety` | literature | live | |
| `modern.search`, `rwd.ask` | literature | unavailable | the modern studies and the synthetic OMOP database are the server's |
| `taochronos_research`, `taochronos_session`, `taochronos_ask` | engine | unavailable | the multi-agent research engine |

14 live, 16 precomputed, 44 unavailable.  `taochronos_catalog` and `taochronos_call` (the two meta-tools of the core
mode) are served over what the backup has.

## What the backup cannot do

- No multi-agent research, research sessions or D1–D5 analyses; no dense, graph or citation retrieval routes, so no
  lineage notes on hits; the search ranks differently from the server's (above).
- A precomputed tool answers only for its listed keys, with its default arguments (other arguments are answered with
  the defaults and a note), for the canonical name (which its answer names) and a clause as its witness punctuates it;
  its results are those of the day they were computed.
- The daily allowance of 5,000,000 rows read is shared by every visitor: a search reads 2,700–12,000 rows (the
  candidate chunks' passages), so some 900 searches a day; past it, D1 refuses reads until 00:00 UTC and the page falls
  back to the browser.
- The first search in a fresh isolate takes 4–9 ms of CPU as measured here, but one run in ten went over 10 ms (the
  warm-up covers the common code paths, not every query's): Cloudflare may stop a request over the limit (error 1102),
  and the page then falls back to the browser for that conversation.  A warm isolate answers a search in 1.4–6 ms.
- Updating the corpus means two days of import again (the databases are made anew; the page uses the browser's corpus
  meanwhile).

## Consequences

- On the Workers Free plan, https://chat.impf.ai answers from all 958 books: search, passages, quotation checks and
  most study tools, with no container and nothing to pay.
- The owner's one step: add *Account · D1 · Edit* to the existing API token (`cloud/SETUP.md`); the d1 workflow does the
  rest in two days and deploys the site with it.
- With a container, nothing changes: the container answers, the backup is not consulted.
- The JavaScript tools are a second implementation: the fixture's reference answers (made by the Python tools in CI),
  `tables.js` (generated and checked against the checkout) and the normaliser's test keep them in step with the Python
  ones.
- Everything above was measured in the local emulator — workerd's own D1 — not against Cloudflare's (nothing here may
  reach it); the import's REST calls are tested against a stand-in for D1's API as Cloudflare documents it (the wording
  of its daily-limit error is assumed).  The first real run's summary is where to check the rows D1 reports for the
  index (a row per chunk here; the budget holds either way, as each statement is sent only if its upper bound fits) and
  that a statement indexing 6 million characters (FTS5's hash up to 64 MB) stays within D1's time and memory; if it
  does not, `FTS_CHARS` is the one constant to lower.
