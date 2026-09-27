# Roadmap

**Data**
- Connected: Kanripo KR3e (100) and its catalogue, 笈成 (816 of 857), McGill (5), CMETA (the 11 collated editions it
  opens), the 東亜医学協会 (7), Wikisource Category:中醫 and 醫書 (18 new of 627, from the dumps), TCM-Ancient-Books (8
  new of 701), tcmoc (a copy), classical-tcm-canon (1 new of 115); contemporary works left out
  (`corpus/catalog/exclusions.yaml`), the modern editions kept with their editors' work separated (ADR 0007). Image witnesses: the records of the digitised prints and manuscripts at NIJL's
  medical holders, Berlin (Sammlung Unschuld), the Library of Congress, Waseda and the NDL Digital Collections
  (`corpus/catalog/images/`).
- CMETA's texts still being collated (粗校, 待校) when the site opens them; its 難經集注 and further editions as they
  are completed. The Biodiversity Heritage Library (with an API key) and the 中国中医古籍数字资源库 when reachable;
  国立公文書館 (内閣文庫) records by hand. `corpus images --enrich all` for the dates and authors of every NIJL record,
  and expert review of the title links (`match` in `corpus/catalog/images/*.csv`).
- Expert review of the duplicate judgements in the 0.4–0.9 band (`closest` in each collection catalog), and of the
  Wikisource works converted from web copies that may still be independent transcriptions (`force_ingest`).
- Scan-backed Wikisource transcriptions (the `Page:` namespace behind `<pages>` transclusions) are not fetched yet.
- Expert review of the undated 笈成 books and of the dates taken from prefaces (`dating` in
  `corpus/catalog/jicheng.yaml`); layer rules for more annotated 笈成 texts (most commentaries are still `mixed`);
  the 6 disagreements between the curated Kanripo catalog and KR-Catalog (`review` in `kr-catalog-kr3e.yaml`).
- 句读 of 白文 (done: `study punctuate`, learned from the store's punctuated texts, evaluated on held-out works and on
  4 Siku works against their 笈成 punctuation): extend the 白文 evaluation to all 78 works shared by the Siku and 笈成
  (126 笈成 transcriptions), and review where the editors of two punctuated transcriptions disagree.
- Collation of the works present in several transcriptions (`study stemma`), work by work, with the frequent
  substitutions reviewed into `collation.yaml` (e.g. 证类 大观本 vs 政和本).
- Expert review of the harvested formula and drug names; separation of 本经 and 别录 layers.
- Page images and OCR confidence (completes Claim → Pixel; the Kanripo locators already give page and line; CMETA's
  passages already link their page image). An image layer over the IIIF manifests of the image witnesses: page-level
  OCR of the digitised prints, and the collation of a transcription against the print it claims to transcribe.
- Expert-built lexicon, sense inventory, variant tables and gold sets (replace the author-constructed demo gold).

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

**深层发现 2.0 (next)**
- Expert gold for the 2.0 capabilities on the full corpus: a collated chapter with its stemma, typed reuse pairs
  drawn from the corpus, segmented case records from several collections, argument graphs, dated sense shifts,
  fragments checked against the modern 辑佚 editions now in the store (their editors' apparatus in metadata, ADR 0007)
  as a gold standard of what a recovery should find.
- Collation at the scale of whole works: the variant units of every work with several witnesses, as a variant
  dataset; stemmata compared with the editorial histories of the literature.
- Transmission for every major work, and a corpus-wide reuse graph (who took up whom, how, and through which channels).
- 学派 · 地域 · 传播网络: schools (done: `study schools`, the textbooks' groupings tested against the texts) and the
  transmission of a passage (done: `study chain`); still to do, regions (T27): physicians' native places and places of
  practice, places of printing (the place names of signed prefaces, 河間劉完素, 雲間李豫亨), normalised, so that the
  vocabulary and formula statistics of `study schools` and `study pairs` can be compared by region.
- 方剂表型: dose-aware formula similarity (ratios and preparation, 同药异量: 桂枝加桂汤 vs 桂枝汤), formula phenotypes
  from indications and case-record use.
- 药物基原: the historical identity of drugs (one name, several plants; one plant, several names) from descriptions,
  illustrations and places of origin in the 本草.
- 针灸与非药物疗法: points, channels, moxibustion, 导引 and diet, read like formulas (sources, variants, indications).
- 多模态与图像谱系: page images, OCR confidence, and the lineage of illustrations (本草图, 经络图) across editions.
- A Bayesian, missingness-aware D1 (lost knowledge): the probability that an association would have been written
  down had it persisted, given how much of each period survives.
- Temporal hypergraph embeddings, for candidate generation only (links, analogues, reuses to check); the rules and
  gates still decide.
- Contextual historical NER and entity linking (people, books, places, drugs, formulas in context), with the lexicon
  and the catalog as the targets.

**V2 (docs/v2.md) — done:** rules screen, a model judges (LiteLLM, MiniMax mainland, Poe and the mainland platforms);
T1 layout and a model's reading of page images, T2 OCR comparison with the store, T7 contextual NER (24 types), T10
five-layer text and grounded translation, T27 places; the Ancient–Modern Bridge (HPO, 64 profiles, levels, reverse
mapping); the six-layer Evidence Graph; the Evidence Audit; modern evidence typed by design with the cross-level guard;
real-world data through validated study specs over OMOP; fifteen skill manifests, four core agents, a workflow compiler
and a resumable executor (`taochronos ask`).

**V2 — what remains**
- Real page images with a layout gold (T1), an OCR engine's confidence into G1 (T2).
- The bridge's written-form map from its held-out misses and a larger held-out sample; clinical review of the 64 profiles;
  ISPO, Mondo, SNOMED CT and LOINC mappings as data; profiles for more diseases.
- An expert gold for the audit on real answers; PubMed typing checked against full texts on a sample.
- The RWD path on a real OMOP database with adjustment (propensity scores) behind the same validated spec.
- A model-planned workflow evaluated against the rules' plans on a larger question set.

**任务规格 v1.0 (docs/tasks.md) — what remains**
- T21 配伍: frequent subgraphs, drug embeddings and Bayesian association, compared against the present NPMI / Fisher
  rankings; T22 方剂演化: an expert gold of formula lineages.
- Expert gold for the capabilities of the specification: clause roles, commentary relations and stances, the
  doctrines of each school (beyond the 44 of the textbooks), preferred names by period, the transmission of passages
  whose history the literature has established.

**Discovery**
- Learned extractors (distant supervision from rule claims + expert corrections), evaluated by ClaimEval.
- Better lineage: rarity-weighted herb overlap and explicit textual statements of derivation, to separate
  convergent composition from inheritance.
- Dose- and preparation-aware formula comparison.
- ~~Time-machine evaluation on a large corpus (link-level hits@k against the baselines)~~ — done: `research_value`
  ([ADR 0010](adr/0010-speed-cruxes-and-research-value.md)).

**Harness — done with the architecture audit ([ADR 0009](adr/0009-boundaries-contract-and-evaluation-layers.md))**:
authority by principal on every event; atomic, pre-validated batches with restore; reading scopes as views with a result
firewall; semantic support at commit and the statement frame; the objection state machine; sandbox tiers with a
namespace tier for model code; the executable contract with acceptance statuses, warrants, confirmation on withheld
material; selection-aware statistics; the budget ledger, paging, record/replay, retraction, cancel and retry, run
manifests and tool receipts; discriminating actions; the invariant and interpretive evaluation layers.

**Harness — done with [ADR 0010](adr/0010-speed-cruxes-and-research-value.md)**: YAML parsed once per content, the lean
state hash and incremental integrity checks; the registry of textual cruxes harvested from the commentaries and read by
the support reading; clause-bounded cue windows; time-machine views of the store; the research-value layer on the full
corpus (link anticipation against popularity and chance; the pipeline end to end on the past, dev and held-out);
arguments from silence tested against what the whole scope states.

**Harness — next**
- Research value: a baseline for lost associations (how often an early-only association of the frame stays absent), a
  third cutoff to decide between Adamic–Adar and common neighbours, more held-out end-to-end topics, and association
  rules that hold (they rarely do: replication across source families before a rule is proposed).
- Whole-store checks that also leave out the other passages of a confirmation family (today only the withheld passages
  themselves are left out).
- Cruxes the harvest misses (the 大黄牡丹汤 inversion, 里水): markers of reordering stated as a reading, not as 当在.
- Calibration of acceptance levels against expert verdicts once expert reviews accumulate (they are ordinal labels
  now, not probabilities).
- A container sandbox provider (VM-grade isolation) behind the same tier interface.
- A queue-backed scheduler and remote subagents for large runs.
- Human-in-the-loop review UI on top of the Discovery Workspace (approve, reject, close objections, retract evidence,
  steer, decide changes).
- More providers behind the `llm` capability; per-role routing learned from evaluation results.
