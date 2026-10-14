# ADR 0023 — Other names of a drug (别名), kept apart

**Status:** accepted · 2026-10-14

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
   names; an unknown kind or a blank or one-character surface is skipped and counted, never fatal.
2. **Every decision is data, frozen at build.**  `taochronos aliases build` writes
   `domains/classics/aliases/aliases.jsonl` and `context.json` (the herb set and the context patterns): statuses,
   blockers, cues, windows and floors.  The gates are pure functions of the passage's text, the record, the passage's
   dates and the query's window, so both Python profiles and the Worker's port decide alike.  The file is compact
   JSON lines — a header (store, normaliser and lexicon fingerprints, sources, counts), then one record per surface
   in code-point order, keys sorted, defaults left out: `s raw stop n sh b fl flb ho r`, each referent
   `h g t k st v c a src w cr nt`.
   Curated and source files (`sources.yaml`, `curated.yaml`) are YAML and never read at runtime.
3. **Three statuses, and stop.**  `open` is searched as the drug; `cue` only where the passage reads as a drug (a dose,
   各 or a preparation after it, 一名 before it, a cue within 20 characters, two herb names within 10); `candidate` is
   listed, never searched; a false friend is `stop`.  The first rule that holds: a curated decision; damaged or
   truncated → candidate; another drug's headword → candidate; shared → cue; 20 passages or more with under 10 % read
   as a drug → stop (for review), under 30 % → cue; two characters → cue; otherwise open.  An occurrence counts only
   outside the record's blockers (大将军, 天地精气, and straddles such as 石蜜甘).
4. **The asked form first.**  Today's list is the main queue.  Passages found only under another name — and, for a
   question about a drug, those matched only by a lexicon synonym — form a side queue that fills reserved places 4, 7,
   10, 14 …, at most ⌊3k/10⌋ while the main queue lasts; the asked form keeps the rest when it has the passages,
   pulled from deeper when needed.  Hits are demoted, never dropped.  One hop only: an alias to its drug's head and
   spellings, a drug to its aliases, never on to the drug's other aliases (地精 → 何首乌 → 夜合 → 合欢).  At most 8
   expansions within 30 mask bits, in both runtimes.  `aliases="off"` is exactly the old search.
5. **Periods.**  Hard `valid` windows only for a curated change of referent (通草, 青木香).  Taboo and first-use years
   are soft floors that flag — `anachronism:山药<1063:edition` when the edition reaches the floor, `:layer` otherwise —
   and never filter.  A passage is tested by the overlap of its composition range, not its midpoint; the query's own
   window stays on the midpoint, so leakage means what it meant.  In the side queue a wrong-period referent is
   rejected; an asked hit with one is demoted and labelled.
6. **Nothing is merged.**  A shared name lists every referent with its sources and witnesses, its side places rotate
   across them, and drug → alias needs an own name in the passage and no rival's.  A hit's reading follows the
   `Terminology.resolve` formula; under p 0.5 it is null and the hit is flagged `homonym`.  Same-drug groups are curated
   (丹砂/朱砂, 黄柏/黄蘗/黄檗/檗木 …); the lexicon's rival entries are listed as referents; a name that is another
   entry's headword is never expanded.
7. **Labelled.**  Each side hit names the name, the drug, the kind (异名, 避讳改名, 药用部位名, 炮制/加工名, 简称,
   品种/产地名, 异写, 古名, 俗名), the source and a witness passage; the query lists the asked names, the expansions,
   and what was left out and why.
8. **Licences.**  The open build takes no local input.  What ships — the repository, `home.zip`, the container,
   `tables.js` — comes from the CC0 别名录 (`jc_c030`, credited to 中醫笈成), the project's curated decisions (each with a
   witness passage) and facts derived from the store with their witness ids (equations, 釋名 brackets, taboo pairs), as
   `lexicon-core` does; never from a `NEVER_PACKED` book.  It is built on the site's full store, whose `jc_c030` is
   complete.  The NTU table, hurbTable and the GB 别名录 are for local research only: imported under
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

## Consequences

* A question about a drug finds passages under its other names — at most 3 of 10 places, each labelled; the asked
  form keeps the others.  On a 29-item prototype gold, seen while tuning and so only indicative, precision at 10 rose
  from .865 to .907 (web-canon) and from .779 to .924 (the full-corpus lexicon on the web store).
  `taochronos eval aliases` measures it on a frozen 120-item gold with a held-out half, for both deployed pairs.
* A question naming the head gives up some of its own form by design (.84 → .67 of the first 10 in the prototype).
* The data follow the store, the normaliser and the lexicon: the header records their fingerprints, and
  `aliases check --db` finds a stale file.  Until the build runs on the site's store, the 釋名 credits and about a
  quarter of the 别名录 are missing.
* The Worker carries the layer in `tables.js` and a hand-written port; parity is tested on the query block and on gate
  cases Python generates.
* A shared name is never answered as one drug, and a dated name is said to be dated; the answer is longer for it.
* Local layers improve research runs on one machine; nothing they contribute is published.
