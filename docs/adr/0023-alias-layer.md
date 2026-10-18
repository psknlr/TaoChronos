# ADR 0023 — Other names of a drug (别名), kept apart

**Status:** accepted · 2026-10-15 · decision 8 amended 2026-10-18 (the NTU table ships)

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
   value of the wrong type refuses the file at its line.  `aliases="off"`, and any pack without a layer, is exactly
   the old search.
2. **Every decision is data, frozen at build.**  `taochronos aliases build` (`plugins/classics/aliasbuild.py`) writes
   `domains/classics/aliases/aliases.jsonl` and `context.json` (the herb set and the context patterns): statuses,
   blockers, cues, windows and floors.  The gates are pure functions of the passage's text, the record, the passage's
   dates and the query's window, so both Python profiles and the Worker's port decide alike.  Curated and source files
   (`sources.yaml`, `curated.yaml`) are YAML and never read at runtime; the build writes the sources' labels into the
   file's header, so every runtime credits a source in the same words.  The same inputs give the same bytes, and
   `aliases check --db` refuses a committed file a build on that store would not reproduce.  The inputs are the
   store, the domain's files (the sources, curated, taboo and lexicon files), the normaliser and the 要籍语料's
   committed pack (`corpus/web/passages.jsonl.gz`): on a full store it sets each witness's `web` flag (`witness_scope:
   web` shows only the flagged); the web store is the pack, every witness its own.  Since 2026-10-18 the NTU table's
   committed extract (`corpus/aliases/ntu40k.tsv`) is one more, read while `sources.yaml` ships it (decision 8).  The
   header fingerprints the store, the normaliser, the lexicon and the pack (`web_pack`, the sha256 of the pack
   uncompressed, 12 hex digits) — on the web store only when the store holds exactly the pack's passages, in its order,
   row for row and on every column `webcorpus.build_store` writes (a pack written again after a text or heading fix
   keeps its ids), else no `web_pack` and a warning — and the NTU extract read (`ntu40k`, 12 hex digits of its
   sha256).  What the build decides:
   * **Drugs.**  A curated `same_drug` group, or the heads the full-corpus lexicon files under one entry, are one
     drug, named by the group's first name (else the lexicon's headword).  A lexicon herb entry that files two or more
     of a drug's names again under another headword joins it (亭历 beside 葶苈, 牙子 beside 狼牙), unless a pair heads
     its headword, files it under another drug, or a curated row decides about it.  Every member — and every name
     with only a first-use or taboo floor (党参, 官桂, 浙贝, 苍术), which heads a drug of its own — carries the drug as
     `ho`, and a member no pair ties to it gets a referent (牡丹皮 → 牡丹), so the members reach one another.  The
     lexicon's other herb entries for a name are listed as its rival referents (source `lexicon`).  The NTU table's
     heads that no other source heads or groups come last and change none of these drugs.  One that curated.yaml
     splits (a row, not a candidate's, with a window, a part's or an older name's kind, or the status cue: 青木香, 小草,
     通草), a curated stop, a name the other sources give as a part or an older name, or one they give two drugs is
     kept apart: its entry gives no drug and its pairs are left out, since a member is searched as its drug's own name
     in every period (settled 2026-10-18, after the review of the NTU change).  Any other joins the drug of the
     lexicon entry it heads, else, of the drugs that name it, that its own lexicon entry files the head of or that it
     names with or without the part the drug is (`SAME_FORM`: 牛蒡 and 牛蒡子, 地锦 and 地锦草), the one whose names
     share two or more of its names in the table, and more than any other's (七叶一枝花 joins 蚤休; 天胡荽 stays apart
     though the lexicon files it under 蘩蒌) — a head the others already give as a name joins only one of those
     drugs — else it heads a drug of its own.  The table never joins two lexicon entries: its evidence would join
     entries that are not one drug.  Where it enters a drug of its own that the store writes as another source's drug
     under another name, a curated same-drug row joins them (无食子 and 没食子, 毕澄茄 and 荜澄茄, 麦芽 and 大麦芽).
     `aliases check` refuses a layer in which a name curated.yaml splits is a member of another drug or heads a drug
     only the table gives.
   * **The NTU table's pairs** (PrimaryDrugName → AlternateName, normalised) enter only when the name, the head or a
     curated same-drug member of the head is a lexicon herb or written in the store; a name or head holding a lost
     character (〓) gives none, since it would match the store's own 〓.  The same pair from two dictionaries is one.
     An ethnic-language name is a folk name with its language in its note (`nt`, with the places the remark names);
     the earliest classical work the remark cites that `sources.yaml` `works` dates is its credit (`cr`), a modern book
     (`modern` there) credits nothing.  The 释名 reader takes every dated title of `works` as a credit too.
   * **Blockers** (`b`: longer strings that hold the name and are not it, at most 24): the curated `cover_stops`
     first; then longer herb or alias names holding it whose drug is another (with a year window where they are the
     same drug in some periods only), and strings that straddle an occurrence in the store — on the name the straddle
     cuts only: a name stands whole beside a straddler, and keeps no such blocker, when the straddler's part outside
     it is a name of its own, no name across its edge takes its leftover characters, and the straddler is not written
     at least twice as often (`STRADDLE_RATIO` 2; 又方|石硫黄 still cuts 方石); ordered by how many passages write
     them.  Never a string a curated `unblock` row lists for the name (青矾石 is 青矾; 防风党参 a 党参), and never a
     本草纲目 joint heading the lexicon harvested as one name (赤箭天麻, 独活羌活) — unless the store writes it as one
     drug's name (a dose after it, not 各; 一名 before it; 之名 after it) or an `unblock` row reads it as one name of
     that name's drug, which then blocks the other.  Headwords harvested from other 本草 entries keep blocking
     (防风党参 of 防风, the 根皮 titles).
   * **Counts.**  `n` (passages writing the name free of its blockers, `jc_c030` left out) and `sh` (the share of them
     that read it as a drug) are counted with the runtime's own gates, chained blockers included.
   * **Report.**  Besides counts and bytes: `joined` (lexicon entries joined to a drug), `unblocked`, `concatenations`,
     `unattested_heads` (别名录 heads nothing writes: garbled), `rivals_sharing_names`, `counts.usage_witnesses`, and
     `ntu40k` (the table's pairs left out, and its remarks by the books they cite: a dated classical work, modern books
     only, or a book `works` lacks); the coverage counts the table's rows, pairs, kept and left-out pairs, credits and
     folk names.
3. **Three statuses, and stop.**  `open` is searched as the drug; `cue` only where the passage reads as a drug;
   `candidate` is listed, never searched; a false friend is `stop`.  The first rule that holds: a curated decision;
   damaged (a doubt flag of the readers: `lost_char`, `joined`, `truncated`, `wrap`, `marks`) or under a one-character
   head → candidate; another drug's headword or head → candidate (since 2026-10-18: a name only the NTU table makes
   another drug's head turns only the table's own pairs into candidates); a pair only the NTU table gives whose name the
   store writes free of its blockers, read as a drug in under 50 % of those passages (`LIST_SHARE`) and tied to the
   drug by no passage of the store → candidate (五味 is not 石灰; 熟地 stays 地黄's; 刀斧伤 is no name of 山大刀), as is
   one whose name reads as a formula's or a class of drugs' (at most 8 characters ending in 汤散丸膏丹圆饮 or 药, no
   lexicon herb, no name the other sources give: 镇心丹, 止血药) and one whose drug shares two names or more with a
   drug the other sources give the name, which is then no rival of it (荜澄茄 beside 毕澄茄); until 2026-10-18's
   settlement the first rule held only at 20 passages or more and the other two did not exist; shared by two drugs or
   more → cue; 20 passages or more with
   under 10 % read as a drug → stop (listed for review; a drug's own name becomes a candidate instead), under 30 % →
   cue; two characters → cue; otherwise open.  A pair only a local list gives also needs a passage before 1912 that
   reads it as a drug, else it is a candidate.  A stop is never expanded — not through its record, nor through a lexicon
   entry that files it as a herb — but as a head it still reaches its own names.  A stop the question asks on its own
   (the question's only name, outside its blockers, a word of its own — 救火车 and 救火队员 are other words — standing alone or
   beside a drug word, a period and question words counting for nothing: 救火是哪味药, 宋以前的解离; `q.stops`) is **listed**:
   `query.aliases.asked` gives every drug its record or the lexicon gives it, each of status `stop`, with a `note` that
   the name is mostly an ordinary word and that nothing was searched for it — or, where the lexicon files it as a herb
   (救火 under 景天), only today's search of that entry's names, whose hits are labelled status `stop`.
4. **The asked form first.**
   * **What is asked.**  The names the question writes outside their blockers, in the order written (`q.asked`).  A
     name written only inside one of its own blockers is not asked (将军之官, 古人言): an alias span there is dropped,
     and a lexicon mention there keeps its term, read as today, but is no asked name.  A blocker that is itself a
     drug's name is asked as written in its place, the mentions inside it dropped (石南藤, not 石南) — unless a lexicon
     mention that is not weak spans it and is a lexicon herb (川乌头, which the lexicon files under 川乌) or a longer
     lexicon name of any kind (麦门冬汤, a formula, over the blocker 麦门冬): that mention keeps its reading, asked with its
     term and forms as today.  A non-herb entry of the blocker itself does not hold it (蜣螂转丸, which the full-corpus
     lexicon files under a formula first, is asked as written, as a drug).  A stop asked on its own (§3) that the
     lexicon files as a herb is asked as that herb's name, a period and question words beside it counting for nothing
     (宋以前的救火 is 救火 with the window).  Only those asked **as drugs** (`q.drugs`) are expanded, gated and listed: a
     name the corpus mostly writes in other senses (n ≥ 20 with sh < 0.10, or < 0.5 when every drug it is searched for is `cue` and it
     has neither `ho` nor a floor), a false friend the lexicon files as a herb, or a name with only candidate
     pairings, neither `ho` nor a floor, that the lexicon does not file (one it files is asked as written) is asked as
     a drug only where the question reads as one — the name alone, a drug word (药, 本草, 功效, 性味, 一名, 是什么 …), another
     drug's name, or the passage gate applied to the question (a dose, 一名, a cue); a name the lexicon reads as no
     herb, and a single character, never.  A question that asks no drug is ranked exactly as today.  A question longer
     than 200 characters (`ALIAS_MAX_CHARS`: the normalised text, in code points in both runtimes — a passage pasted
     in, a list of names) is read as with the layer off: nothing is asked as a drug, expanded or listed, no hit has a
     `via`, and it is ranked as today — only the floor still flags a passage that writes a name before it came into use
     (`anachronism`), in both runtimes; read name by name it would cost the Worker more than a request's 10 ms of CPU.
   * **Reading the question.**  An alias span outranks a weak or shorter lexicon mention it overlaps (山蓟 over
     `herb:山`).  A question of four characters or fewer that is one name nobody knows, holding a weak herb character,
     asks that name (干葛 is not 葛).  Question words and a dose (`DOSE_AT`: numerals, then a unit) stay outside such a
     name, and either may stand beside it: 葛的功效 and 葛二两 ask 葛.  In such a question a drug's name inside a longer
     name is asked as written there (`q.longer`: 慎火草 keeps its places for passages that write 慎火草; 慎火 still
     gives the reading, the other names and the listing).  The longer name is the run of Han characters around the
     drug's name, question words left out, when that run is itself a drug's name; else, falling back, the drug's name
     with only part or form characters after it and preparation characters before it (`NAME_TAILS`, `NAME_HEADS`:
     人参叶, 甘草梢, 酒大黄) — longer than the drug's name, four characters at most, nothing but question words and a dose
     beside it, and the drug's name asked as a drug there.  It takes in no other lexicon mention but a weak herb's (a
     weak 脾 or 心 stops it too), so what a question says of a drug is no name: 甘草入脾 asks 甘草 and 脾, 桂枝温经 asks
     桂枝, and 将军二两 is read as 将军.  Both rules apply only where the profile's `unknown_runs` is on (the default).
   * **Tiers.**  A hit of today's fused pool is **A** when an asked drug's name occurs free there (and in drug context
     where it needs it), **D** (demoted) when it occurs but never so (`demoted:inside <blocker>`, `demoted:no-context`),
     **O** when it matched no surface (graph, citation, sense), **H** when it matched only other lexicon forms of an
     asked drug (D when each of them stands only inside a longer name: 金沸 in 金沸草), **L** when it matched another
     term's forms.  A name needs drug context when every drug it may be searched as is `cue` and it heads none itself
     (将军); a false friend asked through the lexicon needs it named (`named`: a 一名 before it, a 之名 after it, a cue
     near it — 抱薪救火 beside 麻黄 and 桂枝 is no herb).
   * **Queues.**  The main queue M holds A, O and L in today's order.  The side queue interleaves the H hits (as X;
     at `asked_first: all`, the L hits too) with passages found under the expansions (B), X first.  Places 4, 7, 10,
     14 … are reserved for it: while M lasts it takes at most those ⌊3k/10⌋, and a reserved place it cannot fill goes
     to M; once M runs out it fills every place left.  Where asked-first holds (`herbs`: a drug asked; or `all`),
     the asked name keeps the first k − ⌊3k/10⌋ main places when it has the passages, taken from deeper in the pool or,
     when `routes` names `bm25`, from a search of the asked names; what they displace moves down, never out.  An H hit
     every form of which names an asked drug only in a window the passage misses is flagged `other-referent` and goes
     to the end of M.  Demoted hits come after both queues.  An origin question reads each queue in order of years in
     its own places: in the main places the asked name's hits first, then the rest; then the side places; then the
     demoted.
   * **Side search.**  One BM25 search over the searched expansions (`candidates` 400) in the question's window met with
     the expansions' windows widened by `widen` (150 years, for passages dated by a range), plus the `edges` (10)
     earliest per expansion for an origin question; a passage writing any of the question's own surfaces is dropped; the
     first expansion whose gates a passage passes claims it; drugs are dealt round-robin, so a shared name never gives
     every place to one of them; within a drug, a **bare** passage — under 4 characters (`BARE_REST`) beside the name
     once the formula names it writes are set aside (runs of at most 8 characters ending in 汤散丸膏丹圆饮 that are not a
     drug's own name: 石膏, 牡丹, 黄丹（炒）) and no drug context — follows the others (a contents line such as 炙甘草汤 甘草汤 comes
     after them, never left out).  No side search runs where it has no place: `routes` without `alias` (the expansions
     say why `routes`) or ⌊3k/10⌋ = 0 (why `share`).
   * **One hop.**  An alias reaches its drug's head and spellings, a drug its aliases, never on to the drug's other
     aliases (地精 → 何首乌 → 夜合 → 合欢); a name reached for two asked names is one expansion, for the first, the
     others in `also`.  A `part_name` pair joining two drugs that are parts of one plant (青木香, the root, and 马兜铃,
     the fruit; 鸡舌香 and 丁香) is listed with why `part` and never searched, unless the part name is a member of its
     drug (天麻 of 赤箭).  Ordered alias→drug first, open before cue, more passages first, then by surface; at most 8
     searched within 30 mask bits, in both runtimes; unattested names (n = 0) are listed, not searched.
5. **Periods.**  Hard `valid` windows only for a curated change of referent (通草, 青木香).  Taboo and first-use years
   are soft floors that flag and never filter.  A passage is tested by the overlap of its composition range, not its
   midpoint; the query's own window stays on the midpoint, so leakage means what it meant.  In the side queue a
   wrong-period referent is rejected; a hit on a lexicon form that names the asked drug only in a window the passage
   misses goes to the end of the main queue, flagged `other-referent`; an expansion whose window misses the question's
   is listed as excluded (why `period`).
6. **Nothing is merged.**  A shared name lists every referent with its sources and witnesses, and its side places
   rotate across them.  Drug → alias takes a shared name only with an own name in the passage and no rival's — names
   read outside the name itself (木香 in 青木香 is no rival's), and only where a rival may be meant at all: a referent
   whose window misses the question's window does not make the name shared, and one whose window the passage's range
   misses is no rival there, so 通草 in a passage of 650 serves a question about 木通.  A hit's reading follows the
   `Terminology.resolve` formula over the name's readings — its referents that are not candidates, plus the drug it
   heads itself, cued by that drug's own names; when the best p is under 0.5 or tied (two at 0.5) it is null and the
   hit is flagged `homonym`.  Same-drug groups are curated (丹砂/朱砂/辰砂, 黄柏/黄檗/黄蘗/黄蘖 …) and carried as `ho`,
   so that the lexicon's separate entries for them read as one drug; a lexicon referent is shown under its group's
   head (止行, filed under 蒺藜子, lists 蒺藜); a name that is another entry's headword is never expanded.
7. **Labelled.**  Each side hit, and each asked hit of an ambiguous or context-gated name — for the asked names that
   pass the gates in it, the same check the tiers make (never on a demoted hit, nor for a name that does not pass
   there: 将军 written only inside 大将军, or out of drug context, gives no via) — carries a `via`: the name the
   passage writes, `for` (the asked names it stands for: always a list), the drug, the direction (`alias→drug`, `drug→alias`, or `asked` for the reading of the asked name itself), the kind
   (异名, 避讳改名, 药用部位名, 炮制/加工名, 简称, 品种/产地名, 异写, 古名, 俗名), the status, the sources and a witness
   passage; the query lists the asked names with their drugs, the expansions with whether each was searched, and what
   was left out and why.  Flags say what a hit is not sure of (`anachronism`, `homonym`, `demoted:…`,
   `other-referent`).  The page shows them as badges ([web.md](../web.md)) on a search's results.  Research
   evidence keeps them in words in its note (`routes: alias; via 国老→甘草（别名录（中醫笈成））; 年代存疑（…）`); the
   research report's corpus evidence (section 3) adds them to each record the search wrote (`retrieval:hybrid`; a
   model's note is never read as labels), with a legend, and the evidence table (`evidence.csv`) ends with the note.
   `taochronos ask` adds them, with the legend, to its report's 来源 lines, and the chat's `taochronos_ask` gives its
   sources the same labels (`sources[].labels`), which the page shows as badges on their cards.  In words only an
   asked name stands before an arrow (`via 国老→甘草`: 国老 asked, the passage found through 甘草); a via for the drug
   itself asked, or with no asked name known, has no arrow and says what the passage writes
   (`via 川楝子（写作金铃子；词表）`); a passage several queries found keeps each one's label.  A search's badges on
   the page read alike (别名：金铃子→川楝子 only for 金铃子 asked; 别名：川楝子（写作金铃子）, and
   别名：旱莲草（写作莲子草；所问鳢肠） where the drug was searched for another asked name).
8. **Licences.**  The open build takes no local input.  What ships — the repository, `home.zip`, the container,
   `tables.js` — comes from the CC0 别名录 (`jc_c030`, credited as 别名录（中醫笈成）), the project's curated decisions (every
   pairing, group, floor, stop and status with a witness passage) and facts derived from the store and the project's
   data with their witness ids (equations, 釋名 brackets, taboo pairs, the lexicon's entries), as `lexicon-core` does;
   never from a `NEVER_PACKED` book.  It is to be built on the site's full store, whose `jc_c030` is complete.  The
   NTU table, hurbTable and the GB 别名录 are for local research only: imported under `<data>/aliases/local/` with a pin,
   read only by `profiles/full-corpus-local.yaml`, which is never deployed; deployed profiles may not name a local
   layer.  Only the importers and the NTU pin (DOI, file, rows) are committed, and the NTU attribution is marked
   unverified until its citation is confirmed.

   **Amended 2026-10-18: the NTU table ships.**  IMPF-AI, the site's publisher, decided to publish all of the NTU
   table's pairs, credited to NTU under CC BY-NC 4.0, the site staying non-commercial; the paragraph above holds for
   the rest.  Why: the shipped lists gave the names of the 别名录's 1,086 entries; the table gives the other names of
   8,240 drugs from five modern dictionaries (中华本草, 全国中草药汇编, 中药大辞典, 中国药典, 标准藏药), with the
   books, places and languages its remarks name, and its licence lets anyone share and adapt it, credited, for a
   non-commercial purpose, which the site's is.  What changes:
   * **What ships** includes the table: `sources.yaml` gives `ntu40k` `ship: true` and a class of its own, `nc` (a
     list under a non-commercial licence), with the licence, its URL, the attribution (still marked unverified) and
     the label NTU 40K（CC BY-NC 4.0）, so every answer that credits it names the licence.  `aliases check` refuses a
     source of no known class, a `local` source that ships, and an `nc` source without a non-commercial licence and an
     attribution.
   * **Its extract is committed** (`corpus/aliases/ntu40k.tsv`: the workbook's sheet "1-to-1 records", its cells
     unchanged, credited in its header, written by `taochronos aliases import ntu FILE --publish`), pinned in
     `sources.yaml` with the workbook it comes from, and read by every build while the table ships (decision 2).  Its
     pairs pass the gates the others do — stop names, the cue and candidate statuses, blockers — and a relevance
     filter: a pair neither of whose names is a lexicon herb or written in the store is left out.  Rules keep the
     table from regrouping the other sources' drugs or demoting their pairs: its heads are grouped last, and one the
     editors or the others split is kept apart (decision 2); a head only it gives demotes only its own pairs; a pair
     only it gives whose name the store mostly writes in other senses, that names a formula or a class of drugs, or
     whose drug doubles one of the others' is a candidate, the double no rival (decision 3).
   * **What stays local**: hurbTable and the GB 别名录, as above; `import ntu` without `--publish` still writes a local
     copy, which the local build leaves out while the table ships.
   * **The condition travels**: the repository, `home.zip`, the container and `tables.js` carry the table's pairs,
     and with them its non-commercial condition.  A commercial use needs a layer built without it (`ntu40k` back to
     `ship: false`, `class: local`).
9. **In phases.**  A: web-canon on (`witness_scope: web`); full-corpus loads the data with the feature off.  B, done
   2026-10-15: the Worker's port (`backup/aliases.js`, with `search.js` and `corpus.js`) and full-corpus on
   (`profiles/full-corpus.yaml`: `alias: {enabled: true}`), in one change, gated by the parity tests
   (`cloud/test/backup.test.js`); the eval's full-corpus numbers are still those of the web store standing in for the
   site's.  Later, if at all: the study tools, gate G3 and `kg.term`, which would leave D1's precomputed results stale
   until a re-import of several days.
   `asked_first: herbs` and the 3-in-10 share are defaults, measured against `all`, `off` and the other ablations on
   the held-out half of the eval.

Rejected: the names as lexicon synonyms (they crowd out the asked form and reach every reader of the lexicon); a fused
route with its own weight (fusion places the hits, nothing keeps the asked form); folding spellings in the normaliser
(a re-index and a D1 re-import); YAML at runtime (3,369 records: 2.4 s against 26 ms for JSON lines, and a second copy
of its cache in `home.zip`).

## Formulas

A passage's range `yr` is closed, [y0, y1]; a window is [from, to); null leaves a side open.  Text is read in gate
form: the normalised text with every character that is neither Han nor ASCII alphanumeric replaced by `|`, its length
kept.  Offsets count code points.

* **Free occurrence** of s: an offset of s not covered by an occurrence of a blocker whose window overlaps `yr` — and a
  blocker written there only inside one of its own blockers covers nothing (one step, no further: in 大黄大戟 the
  黄大戟 that would hide 大戟 is itself the straddle of 大黄 and 大戟).
* **Drug context** at a free occurrence: the 12 characters after it match `dose`, `each` or `prep`; or the name is
  **named** there — the 4 characters before match `nameof` (一名, 又名 …), the 4 after match `named` (之名, 之称, 之号),
  or a cue other than s lies within ±`cue_window` (20); or two herb-set names (longest match, not across s) lie within
  ±`list_window` (10).  The patterns compile alike in Python `re` and JS `RegExp(…, "u")`.
* **Accept** a side passage for an expansion, gates in this order: boundary (a free occurrence), context (a `cue` name
  in drug context), rival (above), validity (`yr` overlaps the expansion's window).  The first expansion accepted
  claims the passage.
* **Reading** of a shared name: per reading, fit = 1 when its window overlaps `yr`, else max(0.15, 1 − gap/600);
  raw = fit · (1 + cues) · 0.35 per anti-cue (multiplied in once per anti-cue, not raised to a power), cues and
  anti-cues other than the name counted within ±`reading_window` (40) of a free occurrence; p = raw / Σ raw, Σ added
  left to right.
* **Floor**: `anachronism:<s><<floor>:edition` when y1 < floor ≤ the edition's end, `:layer` when the edition is
  early too (or has no end); no flag for a passage with no end year.
* **Cap**: min(`expansions`, `mask_bits` − surfaces searched − component groups), counting searched expansions only.
* **Slots**: place p of k (1-based) takes the side queue when ⌊num·p/den⌋ > ⌊num·(p − 1)/den⌋, else the main queue;
  either fills in when the other runs out; integer arithmetic, so both runtimes place alike.
* **Rounding.**  p to 4 places, halves up as the Worker rounds (`Math.round(x·10⁴)/10⁴`: 0.65625 → 0.6563, where
  Python's `round` takes the even neighbour); a tie is judged on the rounded values.  A side hit scores
  round(1000·`alias_score`/(61 + i), 4) with route `alias` (not one of `ROUTES`), a deeper asked hit
  round(1000·0.5/(61 + i), 4) with route `bm25`, rounded as fused scores are.  `sh` has 2 decimals; a whole number is
  written as an int (`n`, `fl`, window and witness years, `cr`), so 1063.0 stays 1063; a witness's year as shown
  (`witness_year`) is the middle of its range.

**Parameters** (`retrieval.alias` in a profile overrides them): `enabled` false, `asked_first` herbs, `share` [3, 10],
`expansions` 8, `mask_bits` 30, `candidates` 400, `edges` 10, `widen` 150, `list_window` 10, `cue_window` 20,
`reading_window` 40, `witness_scope` full (web-canon: web), `unknown_runs` true, `alias_score` 0.5, `ablate` [].
The ablations: `gates` lifts the status, context, rival and part gates (every pair open); `boundary` ignores blockers;
`slots` sorts main and side together by score; `period` ignores windows.  Module constants, not parameters: the
question's thresholds and words (`COMMON_N` 20, `COMMON_SH` 0.10, `COMMON_CUE_SH` 0.5, `DRUG_WORDS`, `RUN_STOPS`,
`DOSE_AT`, `NAME_TAILS`, `NAME_HEADS`, `ALIAS_MAX_CHARS` 200), `BARE_REST` 4, `FORMULA_ENDS`, the build's
`STRADDLE_RATIO` 2, `LIST_SHARE` 0.5 (the NTU rule of §3) and its budgets (`BUDGET`: 4,900,000 bytes raw and 1,200,000
deflated for `aliases.jsonl`, 1,300,000 deflated for the directory, since 2026-10-18; 700,000, 150,000 and 150,000
before the NTU table).

## Shapes

The file is compact JSON lines, keys sorted, records in code-point order of `s`, defaults left out.

```
{"_header":{"format":"taochronos-aliases","version":1,"store":{"sha","books","passages"},"normalizer","lexicon",
  "web_pack"?,"ntu40k"?,"sources":[ids],"labels":{id:label},"coverage":{…},"counts":{"surfaces","pairs","open","cue",
  "candidate","stop"}}}
{"s","raw","stop","n","sh","b":[str|[str,from,to]],"fl","flb","ho","r":[{"h","g","t","k","st","v":[from,to],"c","a",
  "src","w":[[pid,y0,y1,kind,web]],"cr":[work,y0,y1],"nt"}]}
```

A witness's kind is `e` (equation), `g` (gloss), `n` (本草 entry), `m` (釋名) or `l` (the 别名录's list).

A search result gains, only where not empty:

```
query.aliases = {"asked":[{"surface","term","ambiguous","note"?,"referents":[{"head","kind","status","valid","floor",
                   "source","witness","witness_year","credited":[work,y0,y1]|null}]}],
                 "expansions":[{"surface","for","direction","referent","kind","status","searched","why"}],
                 "excluded":[{"surface","for","why"}]}
hit.via   = [{"surface","for":[asked names],"referent","direction","kind","status","source","witness","reading","p"}]
hit.flags = ["anachronism:<s><<floor>:edition|layer", "homonym:<s>", "demoted:inside <blocker>",
             "demoted:no-context", "other-referent:<s>"]
```

`kind` and `source` are labels (古名, 别名录（中醫笈成）).  A referent's `status` is `open`, `cue`, `candidate`, or
`stop` in a stop's listing (with its `note`); a via's is that or null (the reading of a drug the name heads).  `why` is
`cap`, `unattested`, `period`, `part`, `routes` or `share`.  `classics.search` takes `aliases: auto | off`
(`STUDY_SCHEMAS["search"]` holds these shapes).

## The Worker's port

`chat/d1tables.py` writes into `tables.js` the records (`ALIASES`, keyed by surface, shippable sources only), the
sources (`ALIAS_SOURCES`: id, label, licence), `context.json` (`ALIAS_CONTEXT`) and the merged parameters
(`ALIAS_PARAMS`); a profile with a local layer is refused.  `backup/aliases.js` is a line-for-line port of the index —
`gate_form`, `scan`, `free_offsets` with `covers` (the chained rule), `drug_context` and `named`, `accept`, `bare`,
`readings` and `reading`, `floor_flag`, `expansions` (the part rule, `also`), `view` (the stop listing, lexicon
referents under their group's head) and `assemble` — and `search.js` of the question rules (`q.drugs`, `q.longer`,
the stop listing, unknown runs and longer names, the 200-character limit), the tiers with H, retention where
asked-first holds, the other-referent rule, demoted hits last, the per-queue order of years, the `routes` and `share`
marking, and `via` with `for`; `corpus.js`
`passageCard` centres a card on the name it was found under, as `passage_card(focus=…)` does.  Offsets over
`Array.from(text)`, strings ordered by code point, ties broken on explicit keys, the slots in integer arithmetic and p
rounded as above.  Parity is tested on the reference searches — their query block, and the labels (`via`, `flags`) of
the passages both runtimes return — and on alias cases Python generates (gate inputs and verdicts, expansions and
views, slot cases).  The candidate sets differ by design (other FTS limits, no deeper asked search), so which passages
are returned is not compared.

## Consequences

* A question about a drug finds passages under its other names, each labelled, in the side queue's places (4, 7 and
  10 of each ten while the main queue lasts, every place after it runs out); the asked form keeps the others.
  `taochronos eval aliases` measures it on a frozen 120-item gold with a held-out half ([evals.md](../evals.md)).  **The third held-out report** (2026-10-18, 59 items, on the web store, after adding
  the NTU table): web-canon, the deployed pair, P@10 0.683 → 0.797, Wrong@10 25 → 9, AskedRet mean 0.589 → 0.744,
  leakage 0 — but 6 of the 10 acceptance checks: AskedRet min 0.000, ON@50 698 → 907 (1.30× against 1.5×),
  CandRecall 0.875 and SilentMerge 1 fail; full-corpus as a proxy on the web store 0.673 → 0.805, 7 of 10 (ON@50
  690 → 859, 1.24×; CandRecall 0.875, SilentMerge 1 fail).  The second report (before the table) had 0.771 and
  0.795, the first 0.791 and 0.805, with the same checks failing.  Against the second, the table brought the 18
  held-out alias items back to the first report's level (0.806 → 0.878 on web-canon), raised CandRecall (0.650 →
  0.875) and cut wrong hits (12 → 9), and cost CandPrecision (0.788 → 0.583), resolution accuracy (0.577 → 0.385)
  and the head items' P@10 (0.953 → 0.920).  Most of the gain is the question's reading alone (`analysis`: 0.783 on
  web-canon); the other names add recall (ON@50) and remove wrong hits.
* **Dev** (61 items, tuned on; web-canon, third report): P@10 0.726 → 0.861 (0.918 before the table), ON@50 448 →
  1029, CandRecall 0.944, CandPrecision 0.395 (0.867 before); of the dev checks no item type down by more than 0.05
  (substring, −0.075), AskedRet min ≥ 0.7 (0.100) and SilentMerge = 0 (2) fail.  Dev and held-out moved in opposite
  directions with the table: on dev, whose gaps curated rows had filled, its new rivals and candidates cost more than
  its names add (22 of the 61 items list other drugs, 17 lose P@10).  After the report the NTU table's settlement (2026-10-18: the heads the editors split kept apart, the table's own pairs gated harder, §2 and §3) moved dev P@10 0.861 → 0.869 on both profiles (5 items, 4 up; paired bootstrap 95 % CI −0.002 to +0.021); it changes records that 36 of the 59 held-out items write (counted, not read), and the held-out half has not been run on it.  Every
  change to the layer, the eval or the gold after the first held-out report is logged with its date in
  [evals.md](../evals.md); the third report was run once, on the tree with the table, and full-store numbers wait
  for a build on the site's store.
* A question naming the head gives up some of its own form by design; a question that asks no drug is answered as
  before.
* A shared name reaches a side passage only through an own name the question did not ask (the asked forms are
  searched already, so a side passage never holds them), within the periods its rivals share.  A candidate referent
  still counts as a rival there, so a wrong list pairing can keep a drug's side passages out.
* The data follow the store, the normaliser, the lexicon and the web pack (on a full store the witnesses' `web`
  flags; the web store is the pack): the header records their fingerprints, and `aliases check --db` finds a stale
  file.  A `canon` run that rewrites `corpus/web` leaves the layer to be rebuilt: `aliases check` warns when the
  header's `web_pack` is not the pack `corpus/web` holds, and `--db` finds the rebuild differs.  Reading the web store
  row by row against the pack costs a web-store build or `check --db` about 5 s.  The committed layer is built on the
  web store (553 books: 778 of the 别名录's 1,086 entries, 6 釋名 pairs; `web_pack` 01cae4ae63a3) before the NTU table: 2,724 surfaces,
  2,138 pairs (734 open, 1,101 cue, 303 candidate; 63 stop records), 470,111 bytes (the directory 143,545 deflated as
  `home.zip` stores it, of its 150,000; `aliases check` measures it the same way, and a test reads `home.zip` itself).  A build on the site's store adds the rest of the 别名录 and the 釋名 credits, and may
  need the budget looked at again.
* **With the NTU table** (2026-10-18, decision 8 amended; the same web store, the extract `ntu40k` dd8544014297): of
  the table's 43,433 distinct pairs 18,362 enter and 25,071 are left out, neither of their names being a lexicon herb
  or written in the store; 26 heads are kept apart (188 pairs).  The layer holds 18,402 surfaces and 19,208 pairs
  (7,539 open, 5,579 cue, 6,090 candidate; 97 stop records, 8 釋名 pairs): 3,402,245 bytes (824,525 deflated; the
  directory 893,846 of its 1,300,000), and a build or `check --db` takes about a minute and a half; `AliasIndex.load`
  reads it in about 0.4 s in CPython and 0.6 s in Pyodide (0.04 and 0.08 s before the table), the Worker's start
  (tables.js and the index) about 0.3 s under Node — Cloudflare's own measure of the 1 s limit is not known here.  The
  table neither regroups the other sources' drugs nor makes their pairs candidates (§2, §3), but a name it gives a
  drug of its own that shares fewer than two names with theirs is shared, so 104 of their open pairs are cues now
  (过山龙, 血见愁, 断肠草 name a dozen plants or more in it); the editors' "NTU 40K review" rows in `curated.yaml`
  decide on the names it brings in that the store writes most.  A build on the site's store keeps more of the table,
  whose filter reads that store: its size and load times against the budgets are not measured yet.  The first two
  held-out reports measured the layer before the table, the third (above) the layer with it before the settlement of
  2026-10-18, which changed it again ([evals.md](../evals.md), change log).
* The NTU pairs carry their licence: whatever carries the layer — the repository, `home.zip`, the container,
  `tables.js` — carries the non-commercial condition, which the site meets by staying non-commercial.  A pair only the
  table gives has no witness passage, only its source and the classical work its remark cites, where it cites one.
* The Worker carries the layer in `tables.js` and a hand-written port; parity is tested on the query block, on the
  labels of the passages both find, and on gate cases Python generates.
* A shared name is never answered as one drug, and a dated name is said to be dated; the answer is longer for it.
* Witnesses that only show a name in use are labelled `e`, as equations are: there is no kind for usage evidence yet.
  A lexicon headword gets `ho` only when some pair names it.
* Local layers improve research runs on one machine; nothing they contribute is published.
