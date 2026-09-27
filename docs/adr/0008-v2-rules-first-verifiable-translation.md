# ADR 0008 — V2: rules first, a model second; resemblance, not diagnosis; every statement audited

**Status:** accepted

## Context

The V2 proposal asks for an agent that carries the classics across to modern medicine — ancient phenotypes, ontology
projection, modern disease candidates, modern literature, real-world data — with an evidence graph and an audit of every
conclusion, built from skills with manifests and a few core agents, and able to use models from several providers
(LiteLLM, MiniMax mainland, Poe …).

Three temptations come with it.  To let a model do the reading and the mapping end to end (fast to build, impossible to
check); to report a probability that an ancient description "is" a modern disease (there is no gold standard to calibrate
it on, and for most of history there cannot be); to let a model write the SQL of a real-world-data question (a query
that runs is not a query that is right).

## Decision

1. **Rules screen, a model judges.**  Every capability runs on rules; a model (any provider behind the neutral
   `LLMProvider`) reviews only what the rules leave uncertain, may add what they missed as spans validated against the
   text, and writes summaries that cite evidence ids.  Its answers pass a schema, the text and the presentism guard; where
   it reviews a result it can only lower it (a bridge level, an audit verdict).  Every judge call is cached, budgeted and
   logged without its prompt.
2. **Resemblance, not diagnosis.**  The bridge projects findings into HPO with typed relations (EXACT … NO_MODERN_EQUIVALENT,
   HISTORICAL_SEMANTIC_SHIFT), scores modern profiles explainably, and reports a **qualitative level** with the caps that
   applied — never a probability.  Historical names are related to modern diseases through their curated, period-bound
   senses and a homonym table; a pattern of TCM's framework has no modern equivalent.
3. **Every link says who asserts it.**  The evidence graph types each edge (source, scholar, model-extracted,
   model-inferred, modern evidence, hypothesis) and lets any node be walked back to a witness.
4. **Every statement is audited.**  Claims are decomposed and checked by kind; an inference from the historical record
   to modern efficacy is a leap unless put as a hypothesis; clinical and dosage advice is refused; animal, cell and
   computational evidence never carries a claim about people.
5. **A model never writes SQL.**  A real-world-data question becomes a validated `StudySpec`; one fixed template compiles
   it; the SQL is checked (read-only, OMOP tables, bound values) before it runs on a read-only connection.
6. **Skills are data, agents own them.**  Fifteen manifests (inputs, outputs, dependencies, model need, tool bindings,
   validators, evaluation) and four core agents with their own permissions, validated as a registry; workflows are
   compiled from the question and run as DAGs whose every step is an artifact of a resumable workspace.
7. **Held-out numbers are kept honest.**  The bridge's held-out sample was annotated before the reader ran on it and its
   misses were not patched in; dev numbers are reported as dev numbers.

## Consequences

* Everything runs offline and repeatably; a model improves recall and prose where configured, without being trusted.
* The bridge's reach is its written-form map (held-out recall 0.73): extending the map or configuring a model's recall
  pass is how coverage grows.
* No output of V2 is clinical advice, and none claims a retrospective diagnosis; results say so in their own words.
* The profiles, senses and homonym notes are curated data that need expert review; ISPO, Mondo, SNOMED CT and LOINC can be
  added as data without code changes.
