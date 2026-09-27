# ADR 0006 — Independent witnesses, and image witnesses as records

**Status:** accepted

## Context

A review of TaoChronos 2.0 proposed some twenty further resources for the medical classics. They are of two kinds.

- **Transcriptions of named prints.** 數位中醫校書郎 CMETA publishes editions collated page by page against their
  images (the 赵开美本 of the 伤寒论 in two copies, the 康平本 and 康治本, the 吴迁本 and 邓珍本 of the 金匮, the 顾从德本 素问,
  …), cut at the page boundaries of the images, with the structure of each edition and, for some, the images
  themselves. The 東亜医学協会 publishes seven classics transcribed from named base editions and punctuated after the
  Edo philologists. Both are independent witnesses of works the store already holds in other transcriptions — exactly
  what collation and stemmatics need — but their orthography follows the prints (𤍠 for 熱, 厺 for 去), their notes
  (王冰注, 新校正) sit inside the text, and their terms differ: CC BY 4.0 for CMETA's collation, © with non-commercial
  personal use only for the 東亜医学協会.
- **Digitised prints and manuscripts.** NIJL's 国書データベース (the medical collections of 研医会, 慶應 and 京都 富士川文庫,
  東京大学, 九州, 東北), the Staatsbibliothek zu Berlin (Sammlung Unschuld), the Library of Congress, 早稲田 and NDL hold
  tens of thousands of page images of medical books, with catalogue records and, mostly, IIIF manifests. The images
  are large, their terms vary from holder to holder and from record to record (CC BY-NC, CC BY-NC-SA, PDM,
  RightsStatements NoC-CR, All-Rights-Reserved), and several sites limit automated access.

## Decision

1. **Independent witnesses join the document path.** CMETA and the 東亜医学協会 are collections like McGill: a reader
   turns each edition into a document, the catalog dates and screens it, and it is stored with `duplicate: null` —
   its closest books are recorded, never judged — ranked after McGill and before Wikisource. Only what the site opens
   to every visitor is taken (CMETA's 精校 texts outside its allow-list, by the rule its own front end applies; its
   static files, not its pages); the 東亜医学協会's texts are for local research only.
2. **Editions are data.** A catalog entry may name the edition it transcribes, its year and its holder (`edition`,
   `edition_year`, `holding`); they become the book's edition record. A passage keeps its page, and its page image
   where the source shows it to guests (`locator.page`, `locator.image_uri`): the claim-to-pixel chain is closed for
   these witnesses.
3. **Dated layers in every source.** `notes`, `markers` and `chapter_layers` apply to the document path as they do to
   the Kanripo catalog: CMETA's 素问 keeps 王冰注 (762), 新校正 (1068) and the 运气七篇 as layers of their own.
4. **Orthography is normalised for matching, and judged in collation.** The rare forms of the prints go into a
   normaliser table found by aligning the new witnesses with the others (`script/cmeta_variants.tsv`, 34 mappings seen
   consistently); the orthographic habits of a print (发/発, 去/厺, 草/屮, 枣/栆, 俱/倶) into `collation.yaml`, from the
   frequent substitutions the stemma lists. The texts are never altered.
5. **Image witnesses are records, not images.** `corpus images` harvests, through each holder's published interface
   (holder lists and the record API at NIJL, SRU at K10plus, the loc.gov JSON API, class lists at 早稲田, OpenSearch at
   NDL), paced and cached, the record of every digitised copy: title, author, date statement and years, print or
   manuscript, holder, shelfmark, IIIF manifest, page (NIJL's DOI), and the terms of use of that record. No image is
   downloaded. Records are linked to works by title, as candidates with the way the link was made (`match`), and the
   catalogs are committed as CSV (`corpus/catalog/images/`): records of public catalogues, not texts or images.
6. **One question, one command.** `study witnesses` (tool `study.witnesses`, on the Philologist) lists a work's
   transcriptions and its digitised copies together.
7. **What is not harvested is said.** Sites whose terms restrict bulk download (ctext.org), that refuse automated
   requests or cannot be reached are recorded in `docs/data.md` with the reason, and not worked around.

## Consequences

- The stemma of the 伤寒论 grows from five to nine witnesses, three of them transcriptions of the 赵开美本 checked
  against their images; they group together, and the differences of editorial practice (names supplied for
  prescriptions, the per-chapter lists of the 宋本) show up as what they are.
- The store holds editions with dates and holders and passages that open their page; a future image layer (page
  OCR, collation of a transcription against the print it claims to transcribe) can start from the manifests.
- Title links are candidates: a commentary and its classic, or two works of one title, cannot be told apart by the
  title, and a person checks the record. Enrichment reads one API record per linked NIJL record by default
  (`--enrich all` for every record).
- The repository gains a few megabytes of catalogue records; the harvest takes about an hour with the default pace
  and minutes from its cache.
