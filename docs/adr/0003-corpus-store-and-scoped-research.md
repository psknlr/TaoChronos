# ADR 0003 — A corpus store with a bigram index, layer-level dating, and frame-scoped research

**Status:** accepted

## Context

The demo corpus (131 passages) fits in memory and every agent could read all of it. The full corpus — the 100
medical works of the *Siku quanshu*, 25.7 million characters in 354k passages — does not: eager claim extraction,
in-memory BM25/dense indexes and pairwise text-reuse comparison over everything are infeasible. The texts are
also unpunctuated, in traditional and variant characters, and layered (main text, commentaries and editorial
notes written centuries apart), which the demo never had to face.

## Decision

1. **Store.** Passages live in one SQLite file with provenance, locators and the four clocks. A contentless
   FTS5 index over overlapping character *bigrams* of the normalised text answers substring, phrase and
   proximity queries for terms of any length (a trigram index cannot serve two-character terms, which are the
   majority). `StoreCorpus` implements the `Corpus` interface lazily; claims are extracted on demand and cached
   in the store.
2. **Normalisation for matching only.** Script conversion (OpenCC) and variant forms (Unihan + curated) are
   length-preserving and applied to the index and to queries; the text is never altered, so every quote stays
   verbatim. The normaliser's fingerprint is stored with the index.
3. **Dating per layer.** The catalog dates each separable layer (commentaries, editorial notes, added chapters,
   appended sections, front matter). Where layers cannot be separated, passages are dated by the latest layer
   and the older text's date is kept as `t_citation` — conservative for questions of earliest attestation.
4. **A segmented view, not an edited text.** Unpunctuated passages are read through a machine-segmented view
   whose spans map back to the source; segmentation artefacts are labelled as such.
5. **Frame-scoped reading, whole-corpus falsification.** The Curator freezes a relevance-scoped, period-
   stratified sampling frame (recorded in the manifest); reading agents work inside it. Checks of absence and
   later attestation query the whole store within the contract's window.

## Consequences

- Research over the full corpus runs in about a minute offline; searches take about a second with warm caches.
- The demo corpus and all evaluation suites behave exactly as before (the store is a second implementation of
  the same interface, selected by profile).
- Results depend on the frame for *what is read* but not for *what is refuted*: a lost-knowledge hypothesis is
  challenged by any later co-mention anywhere in the corpus.
- The quality ceiling is now the rule-based segmentation and the vocabulary: harvested names are candidates,
  and claims read through segmentation carry lower confidence until a learned segmenter or punctuated sources
  (e.g. the 笈成 collection) are added.

## Addendum — a second source (笈成)

The 857 punctuated texts of the 笈成 collection go into the same store through a second connector. Their catalog
is generated rather than written: curated overrides, then the Kanripo date of the same work, then the books' own
metadata, then **dated prefaces** (reign-era signatures parsed with an era table), then sibling transcriptions and
the author's other works. What cannot be dated is placed in the Qing and says so — the policy stays "never date a
witness earlier than the evidence allows". Works present in both sources share a `work` id, so Gate G5 counts
them once. Modern works and non-medical texts are stored but excluded from research by profile.

## Addendum — admission and deduplication across collections

Adding the web collections (Wikisource, TCM-Ancient-Books, tcmoc, a Hugging Face dataset) and the McGill prints
raised two questions the first two sources did not.

**Admission.** The corpus is a corpus of historical sources. Contemporary publications (after 1949), works of
contemporary physicians and modern annotated, translated or reconstructed editions are left out at catalog time —
reviewed decisions in `corpus/catalog/exclusions.yaml`, an automatic screen for the rest — and recorded with their
reason; they never enter the store. Republican works (1912–1949) stay, as the 近代 category and the 民国 period.
Modern editors' paratext is dropped from admitted books. This replaces the earlier choice of storing modern works
and hiding them by profile. *(Amended by [ADR 0007](0007-modern-apparatus-as-layers.md): modern editions kept on
review enter the store with their editors' work as dated layers or metadata; research reads nothing from 1950 on
unless a question names its period.)*

**Duplicates.** Most web texts are copies of the 笈成 transcriptions, often converted to simplified characters and
back. Ingesting a copy adds no witness and inflates every frequency, so each text is compared with the store on
sampled shingles of its normalised Han characters before ingestion. Sources are ranked by trust and a source is
compared only with higher-ranked ones (and itself), which makes the catalogs independent of ingestion order.
Overlap cannot tell two editions from two transcriptions of one edition (Siku and 笈成 witnesses of one work overlap
by 0.5–0.93), so the looser thresholds apply only to sources known to copy others; independent transcriptions of
prints (McGill) are never judged, only matched. Every judgement is catalogued with the book duplicated and the
overlap, and can be overruled per text.

