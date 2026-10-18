[Date]

The Editorial Office
*Engineering*

Dear Editors,

We submit the Research Article **"TaoChronos: A Reliable Agent for Knowledge Discovery in Traditional Chinese
Medicine"** for consideration in *Engineering*.

Large language model (LLM) agents are being deployed to mine medical literature, including the classical literature
of traditional Chinese medicine (TCM). Since ZhongJingGPT introduced the first TCM language model in 2023, the
reliability of what such systems assert has rested on the model itself. Our manuscript treats reliability as an
engineering property of the agent: models and rules only propose, deterministic validators grade, and human experts
alone approve. The design is enforced in code a model cannot route around, and every safeguard is tested by deleting
it and confirming that the property it guards then fails.

The four contributions are (1) an agent architecture that separates proposal from verdict — authority by principal
over 61 event types, a permissioned tool mesh, hooks that require verbatim and semantically supported quotations,
nine epistemic gates and an executable research contract; (2) a dated, layered, license-tracked corpus of 966
witnesses of Chinese medical classics (123 million characters, 475 BCE–1949); (3) a three-layer evaluation of
reliability and research value, including a blind temporal benchmark in which leakage is counted rather than assumed;
and (4) guarded translation to modern medicine through the Human Phenotype Ontology, with a complete, replayable
research run released with its failure analysis.

With rules alone, TaoChronos rejected 180 of 180 corrupted quotations, kept 19 of 19 safety invariants and read 82 of
84 held-out hard interpretive cases correctly; rankings computed from earlier texts anticipated links later
physicians wrote (precision@10 0.168 vs 0.134 for popularity and 0.054 for chance; *P* = 2.4 × 10⁻¹⁶). We discuss five
engineering lessons that carry beyond TCM to any agent whose outputs must be auditable.

The manuscript has not been published and is not under consideration elsewhere, and all authors approved the
submission. Code, data and the source data of every figure are publicly available. [Conflicts of interest.]
[Suggested reviewers.]

Yours sincerely,

[Corresponding author], on behalf of all authors
[Affiliation, address, e-mail]
