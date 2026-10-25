# ADR 0024 — Acupuncture points: selection reasoned as the tradition reasons, and the classics read for their points

**Status:** accepted · 2026-10-25

## Context

The roadmap left acupuncture undone ("points, channels, moxibustion … read like formulas").  The request was for a
mechanism — an agent tool — that helps choose acupuncture points for a given presentation on the criteria the tradition
established, following a review of meridian-based point selection: the levels apart (treatment principle, the principle
of selection, the specific-point categories, the methods of combination, location and implementation); local, distal,
pattern-based and symptom-oriented selection; the Five-Shu points with the phases of *Nanjing* 64 and the separate
indications of *Nanjing* 68 and *Lingshu* 44; the Yuan, Luo (fifteen) and Xi (sixteen) points; Back-Shu and Front-Mu;
the Eight Influential and Eight Confluent points; the Lower He-Sea and crossing points; the combinations by region and by
channel, Yuan–Luo host–guest, Shu–Mu, Shu–Yuan, Lower He–Mu, Xi–Hui, mother–child (*Nanjing* 69); empirical pairs such
as the Four Gates; prescription design in five steps, every point saying what it is for; localization by the national
standard; and the three levels of knowledge kept apart — classical theory, standards, clinical research — each rule
recorded as point and attributes → condition → rationale → implementation → classical source → modern evidence.  And it
asked that the data of the classical texts be part of it.

Two risks shape the design.  A tool that "selects points" reads as a prescription; this system gives no medical advice.
And a table of attributes typed from a textbook is only as good as the typing; the corpus holds the texts the attributes
come from (the 甲乙经 whole in the 要籍语料, in two transcriptions), so the attributes can be checked against them.

## Decision

1. **The reasoning as data** (`domains/classics/acupuncture.yaml`).  Channels, 181 points (codes, names, the aliases a text
   may give them, part of the body, the GB/T 12346—2021 location, cautions), the specific-point tables written as tables
   (the phase of each Five-Shu point is derived from *Nanjing* 64, never typed point by point), regions with their channels
   and local and distal points, symptoms with the points the teaching takes and the words the classics write them with,
   natures and courses, and every rule with its level (classical, teaching, empirical, standard), statement, source and
   probes.  Names two points share (临泣, 通谷, 窍阴, 五里) are no alias: the data never reads one for the other.
2. **Two functions of the study layer, two tools** (`study/acupuncture.py`; `study.acupoints`, `study.point`; CLI
   `study acupoints`, `study point`).  No agent was added: the Scholar may call them, and the skill `acupoint-selection`
   tells an agent the method and what it must not claim.
3. **Selection by objectives and weighted reasons.**  The presentation becomes objectives (location, organ system or
   channel, each symptom, nature); each applicable rule proposes points for an objective with a weight; a point's score
   sums its best reason per objective, so a point serving several objectives ranks first and a category alone adds
   nothing.  The core serves the principal objective; every objective is then served once; a location gets a local and a
   distal point; a conventional pair is taken whole.  A symptom's usual region and organ are inferred only when none is
   given, and said to be inferred.  Deterministic: the same presentation gives the same points.
4. **Combinations named, and what they are not.**  The chosen points are read for every method they form.  合谷 + 太冲 is
   reported as the Four Gates — empirical, upper–lower, yin–yang — and never as Yuan–Luo; one channel's Yuan and Luo
   (太渊 + 列缺) are reported as such, not as the host–guest structure, which needs the host's Yuan and the partner's Luo.
5. **Technique is principle; implementation is the practitioner's.**  Mother and child points carry 补 / 泻 as the
   tradition's intention; natures give principles (寒则留之，陷下则灸之, 热则疾之); a category never fixes the technique.
   The record leaves modality, stimulation, frequency and course empty, to be filled after examination.
6. **Safety first in the choice.**  Every chosen point carries its cautions; in pregnancy the points the teaching lists
   and those of the lower abdomen and the lumbosacral region are left out before choosing, and listed as left out.
7. **The classics as data.**  Every rule's probes are found in the corpus as written (earliest witness, works, periods; a
   term read in its senses — 四关 the four joints in the 灵枢, 合谷 and 太冲 in later books).  The acupuncture books are
   read for **entries** (a point's statement of phase, kind, Mu, Xi, Luo, meeting, other names, location, needling,
   moxibustion, prohibitions), checked against the data with the differing witnesses quoted, and for **indications**
   (…主之, X主…, 取X), which give each point the findings the texts say it treats, by work.  In a selection, a candidate
   the texts say treats a finding asked about gains a light reason, and the points the texts propose are listed beside
   the rules' — the texts inform the choice without overruling the framework.
8. **Three levels apart.**  A few modern records, checked (two individual-patient-data meta-analyses of acupuncture for
   chronic pain and of the characteristics of treatment; the Cochrane review of PC6 for postoperative nausea and
   vomiting), each with what it shows of which population and what it does not: none validates a selection rule.
   `modern.search` reaches the rest, typed by design.
9. **Measured** (`taochronos eval acupuncture`): the tables, the mother–child points, seventeen combinations and twelve
   selection cases against the review's own statements, written out by hand in `evals/gold/acupuncture.yaml`; with a store,
   the data against the entries: on the 要籍语料, 56 of the 60 Five-Shu points have their phase and kind stated, all agree in
   at least one witness, and three witnesses differ (太渊 水 in the Siku 甲乙经, 涌泉 水 in one 笈成 甲乙经, 曲池 木 in the
   铜人针灸经) — variant readings the tool surfaces for a person to weigh.

## Consequences

* A researcher, teacher or student can ask why a point is in a prescription and get the rule, its source and the earliest
  sentence of the corpus that states it; a point's attributes are no longer only asserted but checked against the texts.
* The output is labelled throughout as the tradition's reasoning and the texts' record, never a diagnosis or a
  prescription; the chat prompt tells the model to say so and to pass the cautions on.
* The weights and the regions' and symptoms' points are a teaching selection by hand; they will be wrong at the edges, and
  the eval measures them only against the review's examples.  Entries and indications are machine reading: list layouts,
  unrecognised point names and shared names limit them; every statement carries its witness.
* The D1 backup lists both tools as unavailable (`data`: the rules and points are not in the Worker); the page runs them in
  the browser on the 要籍语料.
