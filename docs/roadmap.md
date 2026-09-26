# Roadmap

**Data**
- Connected: Kanripo KR3e (100) and its catalogue, 笈成 (797 of 857), McGill (5), Wikisource Category:中醫 (15 new of
  625, from the dumps), TCM-Ancient-Books (8 new of 701), tcmoc (a copy), classical-tcm-canon (1 new of 115);
  contemporary works and modern editions left out (`corpus/catalog/exclusions.yaml`).
- Expert review of the duplicate judgements in the 0.4–0.9 band (`closest` in each collection catalog), and of the
  Wikisource works converted from web copies that may still be independent transcriptions (`force_ingest`).
- Scan-backed Wikisource transcriptions (the `Page:` namespace behind `<pages>` transclusions) are not fetched yet.
- Expert review of the undated 笈成 books and of the dates taken from prefaces (`dating` in
  `corpus/catalog/jicheng.yaml`); layer rules for more annotated 笈成 texts (most commentaries are still `mixed`);
  the 6 disagreements between the curated Kanripo catalog and KR-Catalog (`review` in `kr-catalog-kr3e.yaml`).
- Use the 笈成 punctuation of the 78 works that are also in the Siku (126 笈成 transcriptions) to evaluate and train the
  segmentation of 白文.
- Cross-witness collation of works present in several transcriptions (e.g. 证类 大观本 vs 政和本).
- Expert review of the harvested formula and drug names; separation of 本经 and 别录 layers.
- Page images and OCR confidence (completes Claim → Pixel; the Kanripo locators already give page and line).
- Expert-built lexicon, sense inventory, variant tables and gold sets (replace the author-constructed demo gold).
- Edition-level collation across witnesses, with automatic variant discovery.

**治学 (study layer)**
- Expert review of the curated study data: taboo start years and spellings (`taboo.yaml`), period measures
  (`metrology.yaml`), physicians' names and dates (`physicians.yaml`), drug families (`drug_families.yaml`).
- A gold set for formula parsing and grouping (原方 / 通行方 / 同名异方 / 同方异名) and for drug-property extraction, from
  expert-checked witnesses; precision and recall in TaoChronos-Eval.
- Wider drug coverage in compositions (regional and rare names), dose-aware grouping (同药异量: 桂枝加桂汤 vs 桂枝汤).
- Layer-aware citation dating for annotated classics whose notes are not yet separated (孙星衍's 本经 notes).
- More learning material: 方歌 alignment with their formulas across verse books, 经文背诵 by chapter, spaced-repetition
  exports beyond Anki.
- Concordance at scale: all-pairs 互见 detection for a work (a 校勘 table per chapter), and a variant-reading dataset.

**Discovery**
- A learned punctuation / segmentation model for 白文, evaluated against punctuated editions (笈成).
- Learned extractors (distant supervision from rule claims + expert corrections), evaluated by ClaimEval.
- Better lineage: rarity-weighted herb overlap and explicit textual statements of derivation, to separate
  convergent composition from inheritance.
- Dose- and preparation-aware formula comparison.
- Time-machine evaluation on a large corpus (link-level hits@k against the baselines).

**Harness**
- A queue-backed scheduler and remote subagents for large runs.
- Human-in-the-loop review UI on top of the Discovery Workspace (approve, reject, steer, decide changes).
- More providers behind the `llm` capability; per-role routing learned from evaluation results.
- Container sandbox provider for untrusted Code Mode programs.
