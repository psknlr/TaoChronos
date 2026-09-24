# TaoChronos

*A provenance-grounded, evidence-native research harness for knowledge discovery in Chinese medical classics (中医古籍).*

[中文 README](README.md) · [Architecture](docs/architecture.md) · [Agents](docs/agents.md) · [Discovery](docs/discovery.md) · [Evaluation](docs/evals.md) · [Data](docs/data.md) · [Roadmap](docs/roadmap.md)

TaoChronos turns a study of the classics into a **replayable, auditable and falsifiable** process. The
research question becomes an immutable contract. The research director agent — **TaoChronos** — spawns
specialists on demand (philology, historical semantics, claim extraction, lineage, evidence, pattern
mining, statistics, hypotheses, falsification, meta-review…). Every conclusion must rest on **verbatim,
mechanically verified textual evidence** and pass the epistemic gates G0–G8; a human expert has the last word.

> ⚠️ `corpus/demo` is an **unverified transcription** of short excerpts assembled to demonstrate the method; the
> full corpus (the 100 medical works of the Siku quanshu, Kanseki Repository transcriptions, CC BY-SA 4.0) has
> not been collated by this project either. All outputs are **computational hypotheses** — not medical
> conclusions and not clinical advice.

## Principles

- **Deterministic harness, stochastic intelligence.** The kernel (event sourcing, transactions, gates, stop
  conditions) is deterministic; models appear only in judgement roles, and their output must validate against
  a schema and survive verbatim-quote checks.
- **Everything is a plugin, not everything is an agent.** Corpus, domain pack, retrieval, models, sandbox and
  storage are plugins. Pattern mining and statistics are tool-first procedures that need no model.
- **Claims, not facts.** A claim is “what this text, edition and passage says” — a hyperedge — never a
  context-free medical fact.
- **No forced single reading.** Contested spans keep reading probabilities and an explicit uncertain mass.
- **No medical anachronism.** Historical terms relate to modern concepts only through typed mappings
  (related / partially_overlapping / uncertain / not_equivalent); only a human may assert equivalence.
- **Propose, don't commit.** Agents may only propose changes to canonical knowledge; validators or humans decide.
- **The harness decides when to stop** — evidence saturation, no new sources, validation, budget or expert
  intervention — never a model saying “done”.

## Quick start

```bash
pip install -e ".[dev]"            # Python ≥ 3.11; data and configuration live in the repository (or set TAOCHRONOS_HOME)
taochronos demo                    # offline 消渴 demo research (deterministic procedures, ~4 s)
taochronos agents                  # the 15 agents and their current routes
taochronos search "膜原最早见于何书"
taochronos report <session>        # the 12-section Discovery Report
taochronos workspace <session>     # offline HTML Discovery Workspace
taochronos review <session> <hypothesis> --approve --expert "Name"   # Gate G7: humans only
taochronos eval                    # TaoChronos-Eval
taochronos governance              # architecture policy check
```

With Claude as the reasoning model (judgement roles only; tool-first roles stay deterministic):

```bash
pip install -e ".[anthropic]"
export ANTHROPIC_API_KEY=...
taochronos demo --profile claude   # Opus 5 (frontier) / Sonnet 5 (medium) / Haiku 4.5 (small)
```

Server-side refusal fallbacks (`fallbacks="default"`) are enabled by default for Opus 5 requests. A refusal,
schema-invalid output or exhausted budget falls back to the role's deterministic procedure, and the fallback
is recorded as a Decision. OpenAI-compatible endpoints (DeepSeek, Grok, Gemini, local vLLM/Ollama) and external
command subagents are supported as well — see [docs/agents.md](docs/agents.md).

## The full corpus

Beyond the demo, TaoChronos ingests the Kanseki Repository's **KR3e 醫家類** — all **100** medical works of the
*Siku quanshu* (about **25.7 million characters, 354k passages**). The texts stay out of git; fetching, ingestion
and indexing are reproducible:

```bash
taochronos corpus fetch kanripo     # one shallow clone per text into the data dir; writes corpus/sources.lock.yaml
taochronos corpus ingest kanripo    # parse → date every layer → SQLite corpus store + full-text index (~3 min)
taochronos corpus status            # books, passages, characters, periods, layers; is the index current?
taochronos lexicon harvest          # candidate formula (~4,800) and drug (~2,100) names harvested from the corpus
taochronos research "消渴的概念如何随时代演变？" --profile full-corpus --focus 消渴 --forbid 消渴=糖尿病
```

- A **catalog** (`corpus/catalog/kanripo-kr3e.yaml`) dates every work and every separable **layer**: 王冰's
  commentary (762), the 新校正 notes (1068), the seven 运气 chapters he added (762), the successive layers of the
  证类本草, the Siku abstracts (dated from their 乾隆 year), front matter (by edition). Layers that cannot be
  separated are dated by the latest one, with the older text's date kept as `t_citation`.
- **Script and variant normalisation** (`domains/classics/script/`: OpenCC, Unihan, curated forms such as
  䜴→豉, 茰→萸, 㪚→散) is used for matching only; the text is never altered.
- **Unpunctuated text** is read through a machine-segmented *view*; every quote and argument span is mapped
  back, so provenance stays verbatim. Finding-level oppositions produced by segmentation are recorded as
  apparent, never as hypotheses.
- **Scale.** The Curator freezes a relevance-scoped, period-stratified sampling frame from the full-text index
  (recorded in the manifest); absence and later-attestation checks run against the **whole store** (respecting
  hold-outs and exclusions), so sampling never manufactures an absence.

## Anatomy of a run

```
GoalSpec (immutable): question · focus terms · tracks · temporal scope & hold-out · forbidden assumptions · gates
 ├─ round 0  foundation  plan → scope → philology → senses → claims (+G0–G4) → lineage → evidence → typed mappings (proposed)
 ├─ round 1  discovery   mine D1–D5 → statistics → evolution maps → hypotheses → falsify → revise → re-falsify
 │                       → cross-space bridges (G8) → gates G0–G8 → scores + Elo → meta-review
 └─ round 2+ deepening   act on the meta-review (independent witnesses, sensitivity analyses) — or stop
```

Agents are configuration (`agents/*.yaml`), instantiated per task — not a fixed team. The director is
**TaoChronos**; specialists are TaoChronos-Curator, -Philologist, -Semanticist, -Extractor, -Ontologist,
-Lineage, -Evidence, -PatternMiner, -Statistician, -Evolution, -Hypothesis, -Skeptic, -ModernEvidence and
-MetaReviewer.

## Discovery tracks

| Track | What it finds | Demo example (a computational hypothesis awaiting expert review) |
|---|---|---|
| D1 lost knowledge | associations that vanish after a pivot year while their concepts persist; textual testimony | 本草纲目 on how the uses of 忍冬 changed (“昔人… 后世…”) |
| D2 concept drift | per-period context divergence (JSD, permutation tests), dominant senses | 消渴: Sui–Tang “polydipsia–polyuria disease” → Song–Jin–Yuan “three-消 system” (exploratory: small sample) |
| D3 formula evolution | derivation families, stable cores, additions/removals, taboo renames | 肾气丸 → 六味地黄丸 → 左/右归丸 with core 地黄·山茱萸·山药; 薯蓣 → 山药 |
| D4 hidden association | association rules (Fisher + BH), Adamic–Adar link prediction | 大便黑 ⇒ 犀角地黄汤; “渴 ⇢ 桂枝汤” rejected by the Skeptic (伤寒论 §26 differential) |
| D5 contradiction | contradiction / conditional / apparent (variant, homonymy) / support | 半身不遂: 金匮 (wind) vs 医林改错 (元气亏损); §176 “表里字差” |
| Source rediscovery | cited works missing from the corpus, with date bounds | 古今录验方, cited by 外台秘要, written before ~752 |

## Evaluation

`taochronos eval` (≈45 s on the demo corpus). Gold sets are author-constructed for the demo corpus and were
used during development: read the numbers as **regression tests of intended behaviour, not benchmark results**.

| Suite | Result |
|---|---|
| Philology | 7/7 — no forced readings, uncertain mass kept, matching normalisation |
| Claims | P 0.98 · R 0.95 · F1 0.96; 100% of extracted claims verbatim |
| Provenance | claims and evidence 100% verbatim; mean provenance chain 7.8 levels (page/line/region/image honestly unavailable) |
| Hallucination | fabricated and one-character-perturbed quotes 100% detected; no false alarms on verbatim quotes or variant spellings |
| Contradiction | 12/12 including hard negatives (differential diagnosis, text reuse) |
| Lineage | P 0.87 · R 0.93 (two convergent “lineages”: 逍遥散, 补阳还五汤) |
| Temporal | constraints 6/6, earliest attestation 6/6, period leakage 0 |
| Anachronism | 10/10 statements, 8/8 mappings; agent-asserted equivalence blocked |
| Recovery | 4/4 crash points recover the identical scientific state; parallel = sequential; replay consistent |
| Time Machine (1368) | 2/3 decidable predictions held (张景岳 dropped the “three draining herbs”); zero leakage |
| Source rediscovery | 素问, 灵枢, 伤寒论 each held out and re-inferred (3/3), date bounds consistent |
| Ablations | no sense route → earliest 0.67; no sense resolution → contradiction 0.83; Context OS −94% tokens; Skeptic off → 1 false survival |

## Limitations

The demo corpus is tiny (23 books, 131 excerpts) and unverified; evaluation numbers are illustrative. The full
corpus consists of uncollated transcriptions of the Siku (with its Qing-era alterations and taboo substitutions);
segmentation of unpunctuated text is rule-based and can merge adjacent clauses; harvested names are candidates
for expert review. The rule extractor and curated lexicons were written for the demo. Composition similarity alone cannot separate derivation from
convergence. Link-level time-machine evaluation needs a large corpus. TaoChronos gives no medical advice;
every result is a research lead until an expert (Gate G7) reviews it.
