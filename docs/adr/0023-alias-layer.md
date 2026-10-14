# ADR 0023 — Other names of a drug (别名), kept apart

**Status:** proposed · 2026-10-14 (accepted when the user approves it)

## Context

A drug is written under many names: 国老 for 甘草, 黄蘗 for 黄柏, 丹砂 beside 朱砂, 通草 for 木通 before the Song, 山药
for 薯蓣 after the taboo of 1063.  Search found the name asked and the lexicon's own synonyms, which carry no source and
no date.  Measured on web-canon (the browser's profile) over the local 553-book store: a search for 甘草 has no passage
writing 国老 in its first 10, 50 or 200; 丹砂 reaches 朱砂 0, 1 and 8 times (first at rank 38); 黄柏 never reaches 黄蘗
in 200.

Lists of other names exist, all noisy.  The 本草纲目别名录 is in the store as book `jc_c030` (CC0 1.0 via 中醫笈成; the
web excerpt keeps 6 of its 8 units, the site's store all of them); a GB copy of it on GitHub, hurbTable (879 rows,
scraped) and the NTU 40K table (CC BY-NC 4.0) carry no licence or a non-commercial one.  The 别名录 has 1,086
entries and 3,369 names, with 463 one-character fragments, lost characters (blanks, `KT`), 85 notes rather than names
(根名茹根) and word-level conversion errors (野狼 for 狼).  Using such names as they are fails in four ways, each
measured:

* **The asked form is crowded out.**  With the 别名录's names added to the lexicon as plain synonyms, a search for 国老
  returns ten passages about 甘草 and none that writes 国老 (ten of ten before); the gain lies deep in the list (甘草 →
  国老: 0, 1 and 12 at 10, 50 and 200).
* **Common words and names inside names.**  Of the 40 most frequent new names, 18 are ordinary words: 小便 (5,855
  passages, 4 % read as a drug), 月经, 缺盆, 白虎, 将军 as in 将军之官.  将军 stands in 大将军, 地精 in 天地精气, 党参
  in 上党参, and the search's substring test counts them all.
* **Shared names.**  Across the 别名录 and hurbTable, 455 names point to two drugs or more: 鬼督邮 to 徐长卿, 赤箭
  and the 唐本草's 独摇草; 地精 to 人参, 何首乌 and, in 千金's five 精, 雄黄.  The lexicon already merges silently —
  52 herb surfaces of web-canon go to the entry loaded first (離母 in 本经's 赤箭 entry reads as 白英), and the
  full-corpus lexicon reads 山蓟 as `herb:山` and 黄蘗 as `herb:黄`.
* **Periods.**  通草 is 木通 before about 960 and 通脱木 after; 青木香 is 木香 early and the root of 马兜铃 later.  山药
  is written in 8 passages wholly before 1063, 党参 in 5 before 1700, 枳壳 in 16 before 960 — mostly later editions,
  which date the edition, not the composition ([ADR 0004](0004-study-layer.md)).  An equation passage in the store
  dates only 358 of 2,760 pairs, and 76,809 passages are dated by a range rather than a year.

Three runtimes answer the same site — the browser (web-canon, [ADR 0013](0013-canon-corpus-in-the-browser.md)), the
server and the D1 backup (full-corpus, [ADR 0017](0017-d1-backup.md)) — and the backup's query block is compared with
Python's.  A change of the lexicon never reaches D1; a change of the normaliser re-indexes the store and re-imports D1.

## Decision

1. **A layer of its own, `pack.aliases`, outside the lexicon** (`plugins/classics/aliases.py`).  The segmenter,
   extraction, entity tagging, the harvest, D1's `lex`, the normaliser, the precomputed study results and
   `SynonymKind` are unchanged: no re-index, no re-import.  One record per normalised surface lists every drug it
   names; an unknown kind or status, or a blank or one-character surface, is skipped and counted, never fatal; a
   value of the wrong type refuses the file at its line.
2. **Every decision is data, frozen at build.**  `taochronos aliases build` writes
   `domains/classics/aliases/aliases.jsonl` and `context.json` (the herb set and the context patterns): statuses,
   blockers, cues, windows and floors.  The gates are pure functions of the passage's text, the record, the passage's
   dates and the query's window, so both Python profiles and the Worker's port decide alike.  Curated and source files
   (`sources.yaml`, `curated.yaml`) are YAML and never read at runtime; the build writes the sources' labels into the
   file's header, so every runtime credits a source in the same words.
3. **Three statuses, and stop.**  `open` is searched as the drug; `cue` only where the passage reads as a drug;
   `candidate` is listed, never searched; a false friend is `stop` (as a head it still reaches its own names).  The
   first rule that holds: a curated decision; damaged or truncated → candidate; another drug's headword → candidate;
   shared → cue; 20 passages or more with under 10 % read as a drug → stop (for review), under 30 % → cue; two
   characters → cue; otherwise open.  An occurrence counts only outside the record's blockers (大将军, 天地精气, and
   straddles such as 石蜜甘).
4. **The asked form first.**  Today's list is the main queue.  Passages found only under another name — and, for a
   question about a drug, those matched only by a lexicon synonym — form a side queue that fills reserved places 4, 7,
   10, 14 …, at most ⌊3k/10⌋ while the main queue lasts; the asked form keeps the rest when it has the passages,
   pulled from deeper when needed.  Hits are demoted, never dropped.  One hop only: an alias to its drug's head and
   spellings, a drug to its aliases, never on to the drug's other aliases (地精 → 何首乌 → 夜合 → 合欢).  At most 8
   expansions within 30 mask bits, in both runtimes.  `aliases="off"` is exactly the old search.
5. **Periods.**  Hard `valid` windows only for a curated change of referent (通草, 青木香).  Taboo and first-use years
   are soft floors that flag and never filter.  A passage is tested by the overlap of its composition range, not its
   midpoint; the query's own window stays on the midpoint, so leakage means what it meant.  In the side queue a
   wrong-period referent is rejected; an asked hit with one is demoted and labelled.
6. **Nothing is merged.**  A shared name lists every referent with its sources and witnesses, and its side places
   rotate across them.  Drug → alias takes a shared name only with an own name in the passage and no rival's — where a
   rival may be meant at all: a rival whose window the passage's range misses is none, so 通草 in a passage of 650
   serves a question about 木通.  A hit's reading follows the `Terminology.resolve` formula; when the best p is under
   0.5 or tied (two at 0.5) it is null and the hit is flagged `homonym`.  Same-drug groups are curated (丹砂/朱砂,
   黄柏/黄蘗/黄檗/檗木, 地肤/地肤子 …), and every member's record carries the group as `ho`, so that the lexicon's
   separate entries for them read as one drug; the lexicon's rival entries are listed as referents; a name that is
   another entry's headword is never expanded.
7. **Labelled.**  Each side hit names the name, the drug, the kind (异名, 避讳改名, 药用部位名, 炮制/加工名, 简称,
   品种/产地名, 异写, 古名, 俗名), the source and a witness passage; the query lists the asked names, the expansions,
   and what was left out and why.
8. **Licences.**  The open build takes no local input.  What ships — the repository, `home.zip`, the container,
   `tables.js` — comes from the CC0 别名录 (`jc_c030`, credited as 别名录（中醫笈成）), the project's curated decisions
   (each with a witness passage) and facts derived from the store with their witness ids (equations, 釋名 brackets,
   taboo pairs), as `lexicon-core` does; never from a `NEVER_PACKED` book.  It is built on the site's full store, whose
   `jc_c030` is complete.  The NTU table, hurbTable and the GB 别名录 are for local research only: imported under
   `<data>/aliases/local/` with a pin, read only by `profiles/full-corpus-local.yaml`, which is never deployed; the site
   builders refuse a profile with a local layer.  Only the importers and the NTU pin (DOI, file, rows, digest) are
   committed, and the NTU attribution is marked unverified until its citation is confirmed.
9. **In phases.**  A: web-canon on; full-corpus loads the data with the feature off.  B: the Worker's port and
   full-corpus on, in one change, gated by the parity tests.  Later, if at all: the study tools, gate G3 and `kg.term`,
   which would leave D1's precomputed results stale until a re-import of several days.  `asked_first: herbs` and the
   3-in-10 share are defaults, measured against `all` and 2-in-10 on the held-out half of the eval.

Rejected: the names as lexicon synonyms (they crowd out the asked form and reach every reader of the lexicon); a fused
route with its own weight (fusion places the hits, nothing keeps the asked form); folding spellings in the normaliser
(a re-index and a D1 re-import); YAML at runtime (3,369 records: 2.4 s against 26 ms for JSON lines, and a second copy
of its cache in `home.zip`).

## Formulas

A passage's range `yr` is closed, [y0, y1]; a window is [from, to); null leaves a side open.  Text is read in gate
form: the normalised text with every character that is neither Han nor ASCII alphanumeric replaced by `|`, its length
kept.  Offsets count code points.

* **Free occurrence** of s: an offset of s not inside an occurrence of a blocker (a longer string containing s) whose
  window overlaps `yr`.
* **Drug context** at a free occurrence: the 12 characters after it match `dose`, `each` or `prep`; or the 4 before
  match `nameof`; or a cue other than s lies within ±`cue_window` (20); or two herb-set names (longest match, not
  across s) lie within ±`list_window` (10).  The patterns compile alike in Python `re` and JS `RegExp(…, "u")`.
* **Accept** a side passage for an expansion, gates in this order: boundary (a free occurrence), context (a `cue`
  name in drug context), rival (above), validity (`yr` overlaps the expansion's window).  The first expansion
  accepted claims the passage.
* **Reading** of a shared name: per referent fit = 1 when its window overlaps `yr`, else max(0.15, 1 − gap/600);
  raw = fit · (1 + cues) · 0.35 per anti-cue, cues and anti-cues counted within ±`reading_window` (40) of a free
  occurrence; p = raw / Σ raw, Σ added left to right, rounded half up to 4 places (`Math.round(x·10⁴)/10⁴`).
* **Floor**: `anachronism:<s><<floor>:edition` when y1 < floor ≤ the edition's end, `:layer` when the edition is
  early too.
* **Cap**: min(`expansions`, `mask_bits` − surfaces searched − component groups); ordered alias→drug first, open
  before cue, more passages first, then by surface; only attested names (n > 0) are searched.
* **Slots**: place p of k (1-based) takes the side queue when ⌊num·p/den⌋ > ⌊num·(p − 1)/den⌋, else the main queue;
  either fills in when the other runs out.  A side hit scores round(1000·`alias_score`/(61 + i), 4) with route
  `alias` (not one of `ROUTES`); a deeper asked hit round(1000·0.5/(61 + i), 4).

**Parameters** (`retrieval.alias` in a profile overrides them): `enabled` false, `asked_first` herbs, `share` [3, 10],
`expansions` 8, `mask_bits` 30, `candidates` 400, `edges` 10, `widen` 150, `list_window` 10, `cue_window` 20,
`reading_window` 40, `witness_scope` full (web-canon: web), `unknown_runs` true, `alias_score` 0.5, `ablate` [].
The ablations: `gates` lifts the status, context and rival gates (every pair open); `boundary` ignores blockers;
`slots` sorts main and side together by score; `period` ignores windows.

## Shapes

The file is compact JSON lines, keys sorted, records in code-point order of `s`, defaults left out; whole numbers are
written as ints.

```
{"_header":{"format":"taochronos-aliases","version":1,"store":{"sha","books","passages"},"normalizer","lexicon",
  "sources":[ids],"labels":{id:label},"coverage":{…},"counts":{"surfaces","pairs","open","cue","candidate","stop"}}}
{"s","raw","stop","n","sh","b":[str|[str,from,to]],"fl","flb","ho","r":[{"h","g","t","k","st","v":[from,to],"c","a",
  "src","w":[[pid,y0,y1,kind,web]],"cr":[work,y0,y1],"nt"}]}
```

A search result gains, only where not empty:

```
query.aliases = {"asked":[{"surface","term","ambiguous","referents":[{"head","kind","status","valid","floor",
                   "source","witness","witness_year","credited"}]}],
                 "expansions":[{"surface","for","direction","referent","kind","status","searched","why"}],
                 "excluded":[{"surface","for","why"}]}
hit.via   = [{"surface","referent","direction","kind","status","source","witness","reading","p"}]
hit.flags = ["anachronism:<s><<floor>:edition|layer", "homonym:<s>", "demoted:inside <blocker>",
             "demoted:no-context", "other-referent:<s>"]
```

`kind` and `source` are labels (古名, 别名录（中醫笈成）); `why` is `cap`, `unattested` or `period`.

## The Worker's port

`chat/d1tables.py` writes into `tables.js` the records (`ALIASES`, keyed by surface, shippable sources only), the
sources (`ALIAS_SOURCES`: id, label, licence), `context.json` (`ALIAS_CONTEXT`) and the merged parameters
(`ALIAS_PARAMS`).  `backup/aliases.js` is a line-for-line port of `gate_form`, `scan`, `free_offsets`,
`drug_context`, `accept`, `reading`, `floor_flag`, `expansions`, `view` and `assemble`: offsets over
`Array.from(text)`, strings ordered by code point, ties broken on explicit keys, the slots in integer arithmetic and
p rounded as above.  Parity is tested twice: the query block of the reference searches, and alias cases Python
generates (gate inputs and verdicts, expansions and views, slot cases).  The candidate sets differ by design (other
FTS limits, no deeper asked search), so hits are not compared.

## Consequences

* A question about a drug finds passages under its other names — at most 3 of 10 places, each labelled; the asked
  form keeps the others.  On a 29-item prototype gold, seen while tuning and so only indicative, precision at 10 rose
  from .865 to .907 (web-canon) and from .779 to .924 (the full-corpus lexicon on the web store).
  `taochronos eval aliases` measures it on a frozen 120-item gold with a held-out half, for both deployed pairs.
* A question naming the head gives up some of its own form by design (.84 → .67 of the first 10 in the prototype).
* A shared name reaches a side passage only through an own name the question did not ask (the asked forms are
  searched already, so a side passage never holds them), within the periods its rivals share.
* The data follow the store, the normaliser and the lexicon: the header records their fingerprints, and
  `aliases check --db` finds a stale file.  Until the build runs on the site's store, the 釋名 credits and about a
  quarter of the 别名录 are missing.
* The Worker carries the layer in `tables.js` and a hand-written port; parity is tested on the query block and on gate
  cases Python generates.
* A shared name is never answered as one drug, and a dated name is said to be dated; the answer is longer for it.
* Local layers improve research runs on one machine; nothing they contribute is published.
