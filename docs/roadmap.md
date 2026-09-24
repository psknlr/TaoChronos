# Roadmap

**Data**
- A licensed, collated corpus with page images and OCR confidence (completes Claim → Pixel).
- Expert-built lexicon, sense inventory, variant tables and gold sets (replace the author-constructed demo gold).
- Edition-level collation across witnesses, with automatic variant discovery.

**Discovery**
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
