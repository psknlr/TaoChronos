# ADR 0027 — Acupuncture reasoning: contracts, a coordinator that routes first, an independent audit

**Status:** accepted · 2026-10-29

## Context

A design package for the acupuncture tools (*TaoChronos Acupuncture Point-Selection Tools*, design v1 with its toolkit:
contracts, an example rule pack, 39 acceptance cases, sources, glossary, integration map; 2026-10-29, on `a4c6bc6`)
asked to keep `study.acupoints`, `study.point` and `study.wuxing`, and to add a coordinator (`study.acupuncture_reason`)
and an independent audit (`study.acupuncture_audit`).  It reproduced defects of the baseline: a denied symptom (没有耳鸣)
still selected tinnitus points; 胃虚 met a premise on 脾虚 and 大肠虚 one on 肺虚 (a shared phase replaced the organ);
肾阳虚 completed 滋水涵木 (an aspect collapsed); an unknown state was taken as 不实不虚; an unknown method fell back to all.
It asked:

* that a fact be one of four states — present, absent, unknown, conflicting — with its subject, time, side, the words
  it came from and its provenance, and that unknown never become absent;
* that the execution status (completed, invalid_parameters, dependency_unavailable) and the assessment status
  (educational_only, needs_information, needs_urgent_assessment, needs_etiologic_assessment, pattern_comparison,
  candidate_review, rule_conflict, no_applicable_rule; null when nothing was assessed) be separate;
* that routing come first (sudden hearing loss: assessment within 24 hours, NICE NG155; pulsatile tinnitus: the cause
  first), that at most two questions be asked per turn, and that no state be invented to make a method run;
* that methods run only when named (omitted and [] run none; an unknown name is INVALID_METHOD);
* that rules be data in a closed, three-valued language (all, any, eq, in, present), personal hypotheses disabled, typed
  relations kept apart and not chained (interior–exterior, Yuan–Luo, 脏腑别通);
* that a candidate point need a premise accepted by a server-side review record bound to the case version — never a
  flag, a claimed acceptance or a sentence in the request — and that a purely educational assumption give mappings about
  no one;
* that the case-specific paths of the existing tools share the same validation and not fall back to an unchecked
  recommendation;
* and that a candidate budget of six be a display budget only.

## Decision

1. **Semantics first, in the existing tools** (`acupuncture.py`, `acupuncture.yaml`).  The cues of `reading` (denial,
   unstated, uncertain, conflicting, another person, the past, a hypothesis, the side) give every finding its scope;
   `study.acupoints` keeps what it does not take (`scoped`).  Five-Phase states keep the organ entity and the aspect (气,
   血, 阴, 阳, 精); a phase written alone stands for its zang only as an assumption.  Strategies, Nanjing 75 and 当先实脾
   test the organ and the aspect, never the phase.  Unknown, balanced, mixed and conflicting take no method; 不实不虚 must
   be stated.  `study.wuxing` keeps its v1 default (no `methods`: all, said so in `method_resolution`), `[]` runs none and
   an unknown name raises INVALID_METHOD.  Tinnitus and hearing loss are two symptoms.  Pregnancy is three-valued (unknown
   is not "not pregnant").  The selection budget counts pairs whole.
2. **The contracts, vendored and enforced** (`domains/classics/acupuncture_contracts.schema.json`).  The toolkit's
   schema, adapted where the repository decides (`source_registry_ref`, `production_integration`), checked by a small
   in-module checker of the Draft 2020-12 keywords the contracts use (`$ref`, type, const, enum, pattern, lengths,
   bounds, items, uniqueness, properties, required, additionalProperties, allOf/anyOf/oneOf, if/then) — no new dependency,
   as the Pyodide runtime needs.  It runs on the way in, with the checks a schema cannot make (offsets that give their
   text, references that exist, an organ concept naming its entity's organ), and on the way out: an invalid request is
   answered `invalid_parameters` with `assessment_status` null; a result that would break the return contract is withheld
   as `dependency_unavailable` (fail closed).  The tests cross-check every acceptance case with `jsonschema` where it is
   installed.
3. **The rule pack** (`domains/classics/acupuncture_reasoning.yaml`).  Sources with what each supports and does not
   establish (cited, or with probes into the corpus; a locator not linked to the corpus stays unresolved, no passage id is
   invented); concepts with their names, denials and patterns; timing words; the complaints with their decision-critical
   concepts; the rules — routing guards and inference guards — each a condition in the closed language, an effect (code,
   severity, status, message), blocked conclusions, a restatement and sources; the text claims they answer; the control
   facts only the controller sets; the typed relations (the five 别通 pairs, Kidney–ear, the channels entering the ear);
   the analogy and the three frames of direction; the disabled hypotheses (泻水木补火土金, 水阳木阴); the tinnitus patterns
   with what supports, opposes and only hints; the questions in priority; the methods with their level and the policy
   they need.  The pack is checked when loaded: operators, declared facts, effects, registered sources.
4. **The coordinator** (`study.acupuncture_reason`).  It keeps the case's observations and reads its messages (and the
   query) for what the case does not already hold — concepts, explicit denials, organ states (study.wuxing's reading),
   and the timing facts the words next to a finding give (突然, 前天, 逐渐; nothing beyond them).  Only the case subject's
   present findings are routing facts; another person's and past findings stay as background.  Routing is required in a
   case review, or wherever the request states the subject's present findings (a knowledge question that does is told so,
   and its status stays educational).  Missing decision-critical information gives `needs_information` and its questions
   (two at most, in priority, the decision-critical first, then what would tell the standing patterns apart); an urgent or
   etiologic route decides the answer and nothing more is asked.  Candidates come only from a verified, bound review that
   accepts the very organ, aspect and state, with nothing in the routing pending; points two methods tonify and reduce
   are a `rule_conflict`, the merged candidates withheld.  Without a real case and without a review asked for, a stated
   assumption gives educational mappings (`clinical_truth_status: not_asserted`, a span of its words), differing intents
   shown apart.  The display budget counts what is shown and what remains.  `bietong` and `yuan_luo` give typed relations,
   not points.
5. **Review records** (`ReviewStore`).  A record is kept with an HMAC-SHA256 under a server key (`TAOCHRONOS_REVIEW_KEY`;
   records from `TAOCHRONOS_REVIEW_STORE`, or issued by a trusted host in process); it binds the case id and version, the
   SHA-256 of the case's observations, the knowledge and rule versions — each carrying the digest of its files
   (`acupuncture@1+…`, `1.0.0+…`), so that an edit of the data, bumped or not, retires the records given against it — and
   the role and modes (a domain reviewer authorizes teaching comparison, a clinician case review).  No record, a broken signature, a changed case or an unauthorized use
   gives no reviewed premise and a finding that says which.
6. **The audit** (`study.acupuncture_audit`).  Each claim against the guards (with the disabled hypotheses explained, their
   mapping only under `explanation_only`), each plan point against the tables (SJ normalized to TE; channel, channel
   phase, point phase compared), the same point both tonified and reduced a conflict.
7. **One screen for the legacy paths.**  `study.acupoints` runs the coordinator's routing on the text and symptoms it
   reads: for a complaint the pack routes (tinnitus, hearing loss), an urgent or etiologic route or missing
   decision-critical facts withholds its case-specific points, combinations and record, and gives the questions; other
   presentations are unchanged.  `study.wuxing` withholds its method points only before an urgent or etiologic
   assessment.  Knowledge (tables, indications, rules) stays available.
8. **Wiring.**  `StudyService.acupuncture_reason` / `acupuncture_audit`; two `ToolSpec`s whose mesh schemas are
   permissive so that the contract itself answers an invalid argument (the model's view keeps statuses, findings,
   questions, candidates and mappings whole); CLI `study acupuncture-reason` / `acupuncture-audit`; their pages; the chat
   prompt, the `acupoint-selection` skill and the scholar agent; the web labels; the D1 backup lists both as unavailable
   (`data`).  The toolkit proposed this record as ADR 0026; that number was taken.

## Consequences

* The 39 acceptance cases pass as tests and in the eval (`acceptance` 39/39), with twenty text-only coordinator cases
  (`reasoning` 20/20) and thirteen audit cases (`audit` 13/13); the existing groups are unchanged.  The positive review
  cases pass only because the test host issues their records; the same request on a server without them gives
  `needs_information`.
* No review records exist in production: every `review_context_ref` is unverified until a reviewing workflow issues
  them, so no candidate is given to anyone today — by design.  Records bind their issuer, not yet the requesting
  principal: the tool context carries no requester identity.
* The routing rules are the package's examples, not a clinical pathway; the reader is rule-based (Chinese and English
  cues) and covers tinnitus and hearing loss; other presentations get `no_applicable_rule` from the screen and the
  legacy reasoning as before.  Questions a person answers come back as observations in the next request; the tool keeps
  no conversation.
* A result id is derived from the arguments and the versions; nothing is cached across case versions, and no case text
  is stored.
* The D1 backup's catalog has 97 tools.
