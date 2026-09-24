# Data: corpus and domain pack

Both are plain YAML so historians can read, review and version them. Replace `corpus/demo` with a licensed,
collated corpus for real research (see `corpus/demo/README.md`).

## Corpus

`corpus/<name>/books.yaml` — the bibliographic layer (Gate G0 reads `source`):

```yaml
books:
  - id: suwen
    title: 黄帝内经素问
    aliases: [素问, 黄帝内经, 内经]
    authors: [佚名（托名黄帝、岐伯）]
    dynasty: 战国—西汉
    composition: [-300, 25]          # a range expresses uncertainty
    attribution: pseudepigraphic
    category: 医经
    source: {origin: …, license: …, acquisition: …, transcription: …, verified: false}
    editions:
      - {id: suwen@wangbing, name: 唐王冰次注、北宋林亿等新校正本系统, quality: 0.7}
external_works:                        # works known only through citations (lost or not collected)
  - {id: gujin_luyan, title: 古今录验方, aliases: [古今录验], authors: [甄立言], dynasty: 唐, composition: [618, 650], status: lost}
```

`corpus/<name>/books/<book>.yaml` — passages:

```yaml
book: shanghanlun
edition: shanghanlun@songben
passages:
  - id: shanghanlun.c176
    locator: {chapter: 辨太阳病脉证并治下, section: 第176条}
    text: 伤寒脉浮滑，此以表有热，里有寒，白虎汤主之。
    tags: [白虎汤, 异文, 校勘]
    variants:                          # never overwrite the base text; record readings with witnesses
      - {base: 表有热，里有寒, reading: 表有寒，里有热, witness: 宋本林亿等按语, witness_type: commentator, kind: transposition}
    temporal: {t_composition: [100, 762]}   # optional per-passage clocks (author / composition / edition / citation)
```

The four clocks (`t_author`, `t_composition`, `t_edition`, `t_citation`) let a research contract choose its
time basis; a passage quoting older material can carry `t_citation`.

`corpus/modern/evidence.yaml` — summaries of modern evidence (Biomedical space) with `concept_id`,
`evidence_domain` (`modern_clinical`, `pharmacology`, `molecular`) and `related_terms`. They are never
historical evidence.

## Domain pack (`domains/classics`)

| File | Content |
|---|---|
| `periods.yaml` | analysis periods (half-open year ranges), dynasties, and the expressions used in questions (宋代以前, 明清, 唐以后…) |
| `variants.yaml` | length-preserving character and word normalisations (异体字, 古今字, 通假), witness weights, uncertain-mass floors — normalisation is for matching only; the text is never altered |
| `lexicon/*.yaml` | terms by category (symptom, sign, pulse, disease, pattern, pathogenesis, etiology, treatment, formula, herb, organ, condition, concept) with aliases, typed synonyms (`taboo_rename`, `part_name`, `processing_variant`, `abbreviation`, `variety`), polarity axes, origin, thermal nature, components, broader/related links |
| `terminology.yaml` | historical terms with period-bound **senses** (label, gloss, category, scope, period, cues, anti-cues, exemplars) and *candidate* modern concepts — candidates, never equivalences |
| `modern_concepts.yaml` | modern concepts (labels only; no mapping implied) |
| `ontology.yaml` | entity types, category → claim role, claim relations, treatment verbs, opposition markers, school canons, opposite findings |
| `citations.yaml` | citation patterns and generic references (经曰 → candidate books with weights) |
| `known_findings.yaml` | curated existing understanding used by the novelty check (a restated textbook finding is a rediscovery) |

## Adding a real corpus

1. Write a corpus plugin (or reuse `plugins.classics` with `config: {corpus: corpus/<name>}`) and record
   origin, license and acquisition for every source — TaoChronos refuses unlicensed books at scope time.
2. Mark collation status honestly; attach OCR confidence and page images (`locator.page`, `line`, `region`,
   `image_uri`) to complete the Claim → Pixel chain.
3. Extend the lexicon, terminology and variant tables with expert review; add gold sets under `evals/gold`.
4. Add a profile that points at the new corpus and run `taochronos eval`.
