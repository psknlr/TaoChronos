# ADR 0007 — Modern editions kept, their editors' work as layers or metadata

**Status:** accepted

## Context

The admission policy (ADR 0003, `corpus/catalog/exclusions.yaml`) left out 当代出版物, 当代名医著作 and 现代校注本.
The last class held two kinds of book whose old text is what a historian wants:

- **辑校本 of lost works** — 吴普本草, 本草经集注, 新修本草, 食疗本草, 海药本草, 本草图经, 名医别录, 集验方, 小品方 and
  the 复古辑本 of the 神农本草经: the only continuous texts of these works, reassembled from the books that quote them,
  with the editor's source references (（《新修》三頁，《大觀》卷三，《政和》八一頁）), sigla (〔證〕〔嘉〕〔心〕) and notes
  interleaved;
- **old books in modern annotated or explicated editions** — 俞根初's 通俗伤寒论 in 徐荣斋's 重订 (1956) with four strata
  of commentary, 郑钦安's 伤寒恒论 and 医理真传 in 唐步祺's 阐释 (1990s), 六因条辨 and 万氏秘传片玉心书 with numbered
  modern notes, 许氏医案 re-collated on a forum, 湖岳村叟医案 with its doses converted to grams, 傅青主男科 rearranged
  with passages supplied from 石室秘录, and 香月牛山's 妇人寿草 in a modern Chinese translation.

Left out, they could only be reached through the fragments `study fragments` recovers.  Taken in whole, they would
put 1950s commentary, gram doses and a translation's wording into the Qing, the Tang or the Wei.

## Decision

1. **Kept on review.**  The twenty-one texts (eighteen 笈成 files and three Wikisource pages) and 吴棹仙's 子午流注说难
   (1956) are kept (`keep: true`, the note says how).
2. **The old text is the main layer; the editors' work is separated by rules of the catalog entry**, shared by the
   笈成 and document parsers (`plugins/classics/ingest/apparatus.py`):
   - `paragraphs` — a marked paragraph (【闡釋】, 【榮齋按】, 【廉勘】, （1）…) takes a dated layer, alone or as a
     block running on over unmarked paragraphs until another rule matches or a heading comes; a block may run only
     while a condition holds (徐荣斋's modern punctuation among older layers punctuated with 。 alone) or up to a
     closing bracket; rules without a layer switch back to the old text (the next 条文, 【鄭論】, 问曰);
   - `apparatus` — inline pieces leave the text: with a layer they become commentary anchored to the passage
     (（榮齋按：…）), otherwise they go to the passage's metadata (`extra.apparatus`: source references, sigla, note
     calls, converted doses);
   - `drop_sections` (an editor's 凡例, a 1963 校勘记), `heading_layers` (sections an editor added, marked 新增),
     `own_sections` (a 序錄 that is the author's own text, dated with the book).
3. **Layers are dated by who wrote them.**  何秀山 (乾隆), 何廉臣 (1916—), 曹炳章 (1929—1934) and 徐荣斋 (1955—1956) in the
   重订通俗伤寒论; 唐步祺 (1993—1996) in the 伤寒恒论; an unnamed modern editor as 1950—2010.  Where commentary cannot be
   told from later additions it takes the later date (湖岳村叟医案: the 1984 editors' 按语 and the 眉批 they moved).  A
   translation is dated by the translation (妇人寿草, `mixed`).
4. **1950 on belongs to no analysis period and is no evidence by default.**  `period_of` returns nothing after the
   last period (民国, to 1950) instead of counting later years in it; the dynasty label 当代 names them.  A 当代
   analysis period was not added: its coverage would be a few editors' notes, and absences in it would read as
   change.  The research frame of the full-corpus profile reads up to 1950 when a question names no period
   (`discovery.scope.latest_year`); the study functions list what they find with its date.  Signed prefaces of
   1950 and later take their year too (a 1955 postscript is no longer placed in 1911).
5. **Western years in signatures** — 西元一九一六年丙辰四月望 — are read like reign-era dates.
6. **Figure file names leave the 笈成 texts** (`[i]九宮八風圖\pt1a1.bmp[/i]` → 九宮八風圖, the name in
   `extra.images`), after the text is cut into passages, so that passage ids — cited by the harvested lexicons —
   stay what they were.

## Consequences

- The store gains the continuous texts of ten lost works and nine old books, and their editors' notes as layers
  that a question can include or leave out; the reconstructed lost works can be read, searched and cited, and
  `study fragments --verify` can compare the fragments it recovers with the editors' reconstructions in the store.
- The separation is as good as the markers: continuation paragraphs follow the commentary they continue (a
  paragraph of old text resumed without a marker is dated later, never earlier), and silent modern changes (the
  corrections of 1963 in 湖岳村叟医案, a forum's re-punctuation) cannot be separated and are stated in the notes.
- The rules live in the overrides, one entry per book, with tests on synthetic texts for each kind of rule.
