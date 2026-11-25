[Date]

The Editors
*npj Digital Medicine*

Dear Editors,

We submit the Article **"TaoChronos: A Reliable Agent for Knowledge Discovery in Traditional Chinese Medicine"** for
consideration in *npj Digital Medicine*.

Large language models are increasingly used to mine medical literature, including the two-thousand-year written
record of traditional Chinese medicine (TCM) that once pointed to artemisinin. On historical medical texts their
failures are specific and consequential: a quotation altered by one character, a prohibition read as a prescription,
five copies of one clause counted as five testimonies, an ancient disease name equated with a modern diagnosis, an
agent grading its own work, and a "prediction" tested on books the system had already read. Since ZhongJingGPT
introduced the first TCM language model in 2023, models have learned to speak about TCM; whether what they assert can
be trusted has remained a property of the model.

Our manuscript shows that reliability can instead be engineered into an agent's architecture and measured. TaoChronos
lets models and rules only propose; deterministic validators grade, and human experts alone approve. Its four
contributions are (1) an architecture in which every state change is a typed event checked against the authority of
its emitter, every claim must quote a dated witness verbatim and be stated by that quote, and an executable contract
decides acceptance; (2) a dated, layered, licence-tracked corpus of 966 witnesses (123 million characters, 475
BCE–1949), with an open canon that runs in a web browser; (3) a three-layer evaluation in which safety invariants are
checked by mutation, hard interpretive cases are scored with unsafe errors counted apart in blind rounds, and a blind
temporal benchmark measures research value with leakage counted rather than assumed; and (4) a guarded bridge from
ancient phenotypes to the Human Phenotype Ontology that reports phenotypic similarity, never retrospective diagnosis,
together with a complete, replayable research run released with its unrepaired failure analysis.

With rules alone — no language model called — TaoChronos rejected 180 of 180 corrupted quotations, kept 19 of 19
safety invariants (each broke when its safeguard was removed) and read 82 of 84 held-out hard cases correctly. In
the blind temporal benchmark, rankings computed from earlier texts anticipated links that later physicians wrote
(precision@10 0.168 versus 0.134 for popularity and 0.054 for chance; *P* = 2.4 × 10⁻¹⁶). We report the limits as
plainly: an over-merging of source families in the independence gate, a replication on the open subset that cannot
separate the ranking from chance, and gold sets that are mostly author-constructed.

We believe the work fits *npj Digital Medicine*'s interest in trustworthy AI for medicine: it offers a design and an
evaluation methodology for agents that turn medical literature into hypotheses, and it never turns a hypothesis into
clinical advice. The code, the open corpus, the evaluation suites, the source data of every figure, and the full
event log of the end-to-end run are publicly available.

The manuscript has not been published and is not under consideration elsewhere. All authors approved the submission.
[Competing interests, e.g. the authors' affiliation with IMPF-AI, which operates the web deployment of TaoChronos.]
[Suggested reviewers, with affiliations and e-mail addresses.]

Yours sincerely,

[Corresponding author], on behalf of all authors
[Affiliation, address, e-mail]
