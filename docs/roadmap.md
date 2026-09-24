# Roadmap

**Data**
- More sources through the same pipeline: the 笈成 (Jicheng) collection (punctuated texts, variant table, rare
  characters) and Wikisource (CC BY-SA; the API currently rate-limits this environment's shared address).
- Cross-witness collation of works present in several transcriptions (e.g. 证类 大观本 vs 政和本).
- Expert review of the harvested formula and drug names; separation of 本经 and 别录 layers.
- Page images and OCR confidence (completes Claim → Pixel; the Kanripo locators already give page and line).
- Expert-built lexicon, sense inventory, variant tables and gold sets (replace the author-constructed demo gold).
- Edition-level collation across witnesses, with automatic variant discovery.

**Discovery**
- A learned punctuation / segmentation model for 白文, evaluated against punctuated editions.
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
