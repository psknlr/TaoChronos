# 古今桥接 — the Ancient–Modern Bridge Engine (AMBE)

A passage of the classics describes a patient, or a disease as its period understood it.  The bridge carries that
description across to modern medicine **as far as the evidence allows and no further**: findings as the text states
them, their projection into the Human Phenotype Ontology with a relation type, the modern disease profiles the
description resembles (a qualitative level, never a probability), what would tell those candidates apart, and how the
passage's historical names relate to the modern ones.  It goes the other way too, from a modern disease to the passages
and names that describe something like it.

It is phenotypic similarity, **not retrospective diagnosis** — every statement it writes says so, and passes the
presentism guard (`verification/presentism.py`).

```bash
taochronos bridge phenotype --passage jinkui.13.xiaoke1      # the AncientPhenotypePacket
taochronos bridge map --passage jinkui.13.xiaoke1            # candidates, discriminators, term relations
taochronos bridge map "胸痹之病，喘息咳唾，胸背痛，短气。"
taochronos bridge reverse E11                                 # ICD-10 code, profile id, Chinese or English name
taochronos bridge diseases                                    # the 64 profiles
taochronos bridge verify --obo .taochronos/ontology/hp.obo --write   # check every HPO id; rewrite the hierarchy
taochronos bridge map --passage … --llm minimax:MiniMax-M2.7  # rules first, then a model's review (below)
```

Tools for the agents: `bridge.phenotype`, `bridge.map`, `bridge.reverse` (ontologist, modern-evidence and semanticist
roles; the Translational Medicine Agent's skills S10–S12).

## 1. The data (`domains/bridge/`)

| File | What it holds |
|---|---|
| `phenotypes.yaml` | 168 atomic ancient phenotypes: their written forms (longest matched first, on the normalised text), the HPO term each projects to **with a relation type**, per-form relations where a form differs (哕, 目如脱状, 滑胎), one ambiguous form read by its sentence's cues (不得卧: orthopnea or insomnia), phrases in which no finding is read (利小便, 汗出而解, 热中 …), modifiers (severity, frequency, timing, course), the negation pattern, the openers of optional (或) and conditional (若) clauses, the population words (男子, 妇人, 小儿) |
| `diseases.yaml` | 64 modern disease profiles over HPO terms: ICD-10 code, typical / frequent / occasional findings, findings that argue against, **required** findings (any one of them, or the resemblance stays low: plague without buboes, mumps without swollen parotids), what a modern diagnosis needs that no ancient text can show (`confirm`, `tests`), course and onset; and the **homonym table** (伤寒, 中风, 霍乱, 痛风, 脚气, 消渴, 疟, 胸痹, 肠痈, 痫, 瘰疬, 虚劳) |
| `hpo_closure.yaml` | the HPO hierarchy among the 213 terms the bridge names (generated from the release; identifiers only) |

Every HPO identifier and label was checked against **hp/releases/2026-09-01** (20 482 terms; 213 used, 213 valid);
`bridge verify` checks them again against any local `hp.obo` and reports missing, obsolete, alt-id and synonym-only
labels.  HPO is © the Jackson Laboratory and the Monarch Initiative (hpo.jax.org); only identifiers and labels are kept
in the repository, the ontology itself stays in the data directory.  ICD-10 codes follow the WHO 2019 edition.

### Relation types

| Relation | Meaning | Example |
|---|---|---|
| `EXACT` | the same observable | 吐血 → Hematemesis |
| `CLOSE` | nearly the same | 渴欲饮水 → Polydipsia |
| `BROADER` / `NARROWER` | the ancient finding is wider / narrower | 目赤 → Conjunctivitis (broader); 顿咳 → Cough (narrower) |
| `PARTIAL_OVERLAP` | they share part of their extension | 小便不利 → Oliguria (不利 is scanty *or* difficult) |
| `PHENOTYPIC_SIMILARITY` | a description resembles a profile; the concepts are not claimed to overlap | 金匮消渴 ~ diabetes mellitus |
| `CONTEXT_DEPENDENT` | depends on the passage | 目如脱状 (a gasping man's eyes, not Graves' proptosis); 消渴 as a finding |
| `HISTORICAL_SEMANTIC_SHIFT` | the form meant something else then | 哕 (hiccup before the Song); 伤寒 ≠ typhoid |
| `NO_MODERN_EQUIVALENT` | TCM's own | 脉浮, 恶风, 胸胁苦满, 中风#外感 (a pattern) |
| `UNCERTAIN` | not enough to say | |

Relations weigh a finding when it is matched (`protocol/bridge.py`: EXACT 1.0 … UNCERTAIN 0.25, NO_MODERN_EQUIVALENT 0).

## 2. The AncientPhenotypePacket (S10)

Rules read the passage:

1. normalise variant forms (瞤→𥆧, 鞕→硬 — the written forms are indexed the same way), block the phrases that state no
   finding;
2. match written forms longest first; a one-character form (渴, 利, 热) only at a clause boundary and never before a
   verb of pathogenesis (热迫, 热入); a form listed under two phenotypes gives both (寒热: chills and fever; 咳唾脓血:
   hemoptysis and purulent sputum); a negator inside a two-part form reads it negated (腹不满, 口不渴);
3. bound each finding: **negated** (不渴, 无大热, 不能发黄), **optional** (或渴 — and the 或 list goes on after 、),
   **conditional** (若…者, for the rest of the sentence), **after treatment** (服之则…); severity, frequency and timing
   from its clause;
4. the passage as a whole: its course (久, 卒; counted in days 五六日 → acute; 太阳病 → acute), population, whether it is
   a drug's or formula's **indications** rather than one patient's picture, and the historical terms it names with the
   **sense its context selects** (the terminology's period-bound senses: 消渴#症状 vs 消渴#病·多饮多尿) and the homonym
   warnings;
5. the findings a named disease **implies** by its selected sense (霍乱#吐利 implies vomiting and diarrhoea) are kept
   apart, at half weight.

Then, when a model is configured (`--llm`), it **reviews what the rules leave open** — ambiguous readings, one-character
forms, forms whose relation depends on context — choosing among the allowed readings or rejecting a finding, and it may
add findings the forms missed, **as exact spans of the text with phenotype ids from the map** (anything else is dropped,
not argued over).

## 3. Mapping (S11–S12)

For each profile, the score is built from parts a reader can check:

* **coverage** of the profile's *typical* findings, each weighted by how specific it is among the profiles (normalised
  idf: fever 0.15, polyuria 0.67);
* **precision** — how much of the description the profile explains (typical 1, frequent 0.6, occasional 0.3), each
  finding weighted by its relation and its standing in the text (optional 0.5, conditional 0.4, implied 0.5);
* matching through the **HPO hierarchy**: 腰痛 (Low back pain) counts for Back pain (0.8), a broader finding for a
  narrower feature at 0.5;
* **conflicts** — findings a profile argues against, typical findings the text denies (unless it affirms them elsewhere);
* **compatibility** — course and population (a child, a man, a woman);
* `fit = (coverage + precision) / 2 × compatibility − conflicts`.

The fit ranks within a level.  The **level** is qualitative, by rules over the matched findings, and every cap that
applies is reported:

| Level | Needs |
|---|---|
| high | fit ≥ 0.55, coverage ≥ 0.6, ≥ 2 typical findings, ≥ 3 findings, evidence mass ≥ 1.0, no conflict |
| moderate | fit ≥ 0.35, coverage ≥ 0.4, ≥ 2 findings, 2 typical findings (or a profile's only one), evidence mass ≥ 0.55 |
| low | any finding |
| capped to low | no required finding; fewer than two stated projected findings; support only from what a name implies |
| capped to moderate | a drug's or formula's indications; support partly implied; not clearly ahead of the next candidate |

*Evidence mass* is the specificity of the distinct findings behind a candidate times their match degree — fever and
vomiting weigh little, polyuria and night sweats much.  **Nothing here is calibrated**: no gold standard of historical
descriptions with known modern diagnoses exists (for most of history it cannot), so a level is the strength of a
resemblance and is said to be so in every result.

Each mapping also returns:

* **discriminators** — findings typical of one leading candidate and absent from (or against) another, with the ancient
  forms that would state them (尿甜 separates diabetes mellitus from diabetes insipidus) and the modern tests each needs;
* **term relations** — for each historical name in the passage and each disease its curated sense or the homonym table
  names: `NO_MODERN_EQUIVALENT` when the sense is a pattern of TCM's framework, `PARTIAL_OVERLAP` when the sense names the
  disease and the findings fit (moderate or better), `CONTEXT_DEPENDENT` when senses compete, `UNCERTAIN` when the findings
  do not bear it out, `HISTORICAL_SEMANTIC_SHIFT` when only the name coincides;
* a **statement** in the form 「…所载 N 项可投射的症状，在表型上与 X 相容，强度为中；…这是表型相似，不是回溯诊断」, which the
  presentism guard reads.

With a model configured, it reviews the leading candidates against the text — it **may lower a level** (doubtful: one
step; incompatible: two), **never raise one** — and writes a cited summary (`capabilities/judge.synthesize`: every
sentence cites finding, candidate or term ids and quotes only what they say) that the presentism guard filters.

## 4. Reverse mapping

`bridge reverse <disease>`: the profile's typical and frequent findings → the ancient forms that state them → passages
that carry several of them together, **with at least one required finding**, scored with the same machinery, drug
indications left out, the editions of one work collapsed into one row → the historical names those passages use, by
period — *candidates for historical study, not equivalents*.

## 5. Evaluation

`taochronos eval bridge` (`evals/gold/bridge.yaml`):

| Part | Result |
|---|---|
| Phenotype packets, 20 dev sentences | P 0.971 · R 1.0 · F1 0.985; negation / optional / conditional bounds 1.0 |
| **Held-out**, 12 passages drawn at random (seed 20260927) from 65 clinical works of the full corpus, annotated from the text before the reader ran on them | **P 0.938 · R 0.732 · F1 0.822**; bounds 1.0 |
| Mapping, 18 canonical descriptions (dev) | top-1 1.0, top-3 1.0; negative cases stay low 3/3; statements guard-clean 20/20 |
| Ontology | 213 HPO terms valid in the named release; 35 terms with ancestors in the closure |

The held-out misses are forms the map does not have (不食, 小便难, 腰胯疼痛, 风疹, 嗽, 寒慄, 气喘 …): they were **not**
added after the held-out was scored, so the number stays an honest estimate; a model's recall pass exists for exactly this.
After the first held-out score two general rules were fixed (brackets as clause boundaries; a one-character form before a
verb of pathogenesis), and the evaluation's own set logic was corrected; the recall did not change.

## 6. On the full corpus

`bridge reverse` on the full corpus (≈ 10 s to load the store, then 1–2 s per disease; the editions of a work collapse
into one row): **diabetes mellitus** → 《外台秘要》「近效極要熱中小便多漸瘦方」 and 《景岳全书》三消 at *high*, 《金匮》消渴
(five editions, one row), 《金匮玉函经二注》 and 《张氏医通》 at *moderate*; the names those passages use: 消渴 in 14 (先秦两汉 1,
魏晋南北朝 4, 明 3, 清 6), 消瘅 in 3.  **Malaria** → 《外台秘要》瘧病 at *high*, and the 伤寒论's 往来寒热 clause (26 editions,
one row) at *moderate* — a phenotypic resemblance of the 少阳 picture to malaria, the reason the bridge reports resemblance
and never diagnosis.  A drug's indications (the 本经's 葛根 entry for cholera) are left out of reverse mapping.

## 7. Limits

* The profiles are curated for research screening from standard clinical descriptions; they need clinical review before
  any use beyond that.  64 diseases cover the common comparisons of the literature, not medicine.
* Ancient texts do not state laboratory findings; the profiles list them (`confirm`, `tests`) so a reader sees what the
  text *cannot* settle.
* The written-form map is the reader's vocabulary; its recall on unseen text (0.73) is the main limit, and the reason a
  model's recall pass is built in.
* Senses and homonym notes are curated and need expert review (`domains/classics/terminology.yaml`).
* Mondo, SNOMED CT, LOINC and ISPO are not bundled: the profiles carry ICD-10 and HPO; a mapping to other vocabularies is
  a data addition, not a code change.
