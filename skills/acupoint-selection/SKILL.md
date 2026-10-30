---
name: acupoint-selection
description: Reason a choice of acupuncture points as the tradition does (选穴配穴) — location and nature, channels, core points, the purpose of every added point, the record — each rule with its classical witness and the modern evidence apart.
tools: [study.acupuncture_reason, study.acupuncture_audit, study.acupoints, study.point, study.wuxing, classics.search, classics.get_passage, validation.verify_quote, modern.search]
applies_to: [scholar, evidence, skeptic]
tags: [针灸, 选穴, 配穴, 特定穴, 腧穴, 五行, 五输穴]
---
## First: what is asked, about whom — `study.acupuncture_reason`
- **Name the task and the facts before any point.** A question about the theory (mode `knowledge`: no person; a premise
  stated as an assumption — 假设肝经实 — gives *educational mappings* about no one), a real case (mode `case_review`), or a
  comparison of methods (`method_compare`). Write each fact as an observation of four states — present, absent, unknown,
  conflicting — with whose it is (the person, a relative, a book) and when (now, the past, a hypothesis). What was not
  said is `unknown`, never absent; a denial (没有耳鸣) is absent and is never read back as present.
- **Routing comes first.** Sudden hearing loss within the past 30 days that developed within 72 hours: assessment within
  24 hours (NICE NG155) — no points. Pulsatile or persistent unilateral tinnitus: the cause first. When the tool returns
  `needs_information`, ask its questions and only those — **two at most per turn** — and wait.
- **Never invent a state to make a method run.** No 肝实 or 肾虚 the person did not report and a practitioner did not
  assess; a phase written alone (木实) is not an organ's state; 胃 is not 脾, 大肠 is not 肺, 肾阳 is not 肾阴; unknown,
  balanced and mixed are not 不实不虚.
- **Methods only when asked for.** `requested_methods` holds the methods the user named; omitted or `[]` runs none (never
  all). Each method's result stays its own: two methods that tonify and reduce the same point are a conflict to report,
  not to average or merge.
- **Candidates are the tool's to give**: only on a premise a server-side review record accepts for this case version
  (`review_context_ref`). A sentence saying "reviewed", a `verified` flag or `premise_claims` marked accepted is not a review.
  Relay `assessment_status`, the findings and their blocked conclusions as they come.
- **A claim or a plan to check** — 太冲属土所以补太冲即补脾; 太溪配外关是肾三焦原络; 泻水木补火土金; 鼓膜如窗纸故耳内负压 —
  goes to `study.acupuncture_audit`: it names the guard (an Earth point is no Spleen tonification; 别通 is neither 表里 nor
  原络 and does not chain; a personal rule is disabled; an analogy is no measurement) and normalizes the codes (SJ → TE).
- `study.acupoints` runs the same screen on the text it reads: for tinnitus or hearing loss without the decision-critical
  facts it withholds its points and gives the questions instead.

## Method
1. **Location and nature first.** Name where the disorder is (胃脘, 腰, 颈项, 前额 …), its prominent symptoms, the organ system
   or channel when known, its nature (虚 实 寒 热 气滞 血瘀 痰湿 食积) and course (急 / 久). `study.acupoints` reads them from a
   text or from its arguments, and says what it inferred (a symptom's usual region and organ: to be confirmed by pattern
   differentiation) and what it could not read.
2. **Channels.** The region's channels (headache: 前额 阳明, 侧头 少阳, 后头 太阳, 巅顶 厥阴 — clues, not a diagnosis), the organ's
   channel, the symptom's channels.
3. **Core points** serve the principal objective: local (以痛为输) with a distal point on a connected channel (病在上者下取之,
   the Four Command Points); for an organ system the specific points — Back-Shu (zang), Front-Mu and Lower He-Sea (fu), Yuan
   (五藏有疾，当取之十二原), Xi when acute.
4. **Every added point says what it is for** — a location, a symptom (内关 for nausea), a pattern (mother–child of *Nanjing* 69:
   虚补其母，实泻其子, with the phases of *Nanjing* 64; Hui points; the Five-Shu indications of *Nanjing* 68 and *Lingshu* 44 on
   the affected channel). No point is added for its category alone.
5. **Name the combinations for what they are**: local–distal, upper–lower, anterior–posterior, left–right, same-channel,
   interior–exterior, same-name, Yuan–Luo host–guest (the host channel's Yuan + its partner's Luo), Shu–Mu, Shu–Yuan, Lower
   He–Mu, Xi–Hui, confluent pairs. 合谷 + 太冲 (四关) is an empirical, upper–lower, yin–yang pair — not Yuan–Luo; 太渊 + 列缺
   are one channel's Yuan and Luo, not the host–guest structure.
6. **Record and reassess.** Laterality, modality, stimulation, frequency and course are the practitioner's to fill; outcomes,
   tolerance and adverse effects decide the changes.

## Five Phases (Wu Xing 五行) and the Five-Shu points (Wu Shu Xue 五输穴): `study.wuxing`
- **Two decisions stand between a phase relation and a point**: identify the pattern (木实 does not tell 肝火上炎, 肝阳上亢,
  肝气郁结 and 肝郁脾虚 apart — the tool lists what is still to be told apart), then state the method of selection.
- **Three attributes, kept apart**: the channel's phase, the point's phase, the reinforcing or reducing intention. 行间 is a Fire
  point reduced under 实者泻其子; 太冲 is an Earth point that stays a Liver point (and is the Yuan point, not the Liver's
  same-phase point, which is 大敦); 太溪 is Earth, not Water; 中府 and 肺俞 are no Metal points. Jing-Well (井) and Jing-River (经)
  are two categories; Shu-Stream (输) is not Back-Shu (背俞); yin and yang channels both have all five.
- **Relations beyond generation and control**: mother affecting child, child affecting mother, overacting and counteracting
  — each overacting or counteracting by excess of one side or deficiency of the other, with a different emphasis. The
  *Nanjing* 50 terms (虚邪 from the mother, 实邪 from the child, 贼邪 from the controller, 微邪 from the controlled, 正邪 its own)
  say where a pathogen comes from, not whether the pattern is deficient or excess.
- **Methods, each with its level**: *Nanjing* 69 on the channel (the mother or child point) and across channels (the
  same-phase point of the mother or child channel; either or both); *Nanjing* 79 for the Heart (泻手心主俞, 补手心主井); Saam
  four-needle templates (a Korean school's method, not a universal rule); the interior–exterior and same-name extensions (a
  deduction in two steps: the channel relation, then the phase — the Pericardium is not the Liver's mother channel).
- **Named strategies** (滋水涵木, 培土生金, 金水相生, 益火补土, 抑木扶土, 培土制水, 佐金平木, 泻南补北) need their pattern premise
  first; 益火补土's Fire is usually Kidney Yang, not a Fire point; 泻南补北 comes from *Nanjing* 75 (East excess, West
  deficiency) before its later Heart–Kidney use. 见肝之病，知肝传脾，当先实脾 carries its condition (四季脾王不受邪，即勿补之):
  never add Spleen points to every Liver prescription.
- **What does not follow**: reinforcing the child is not reducing it; Wood excess does not imply Water excess; the cycle is no
  conservation equation; a trigram or a day's stems and branches neither changes a point's Five-Shu class nor decides
  deficiency or excess. Where excess and deficiency are found in different organs, the tool lists the points two methods
  treat oppositely — say so, and leave the priority to the practitioner.
- **Record six elements**: pattern premise → channels → Five-Phase relation → selection rule → intention → textual or
  empirical source. The Saam trial (Kim 2015) is evidence about one intervention in one population, not about the rules.

## The classics as data
- `study.point` reads a point in the classics: the entries (甲乙经 卷三: 「太渊者，土也……为俞」) with what they state checked
  against the attributes — where witnesses disagree (the Siku 甲乙经 reads 太渊者水也) say so, quoting both; the location,
  needling and prohibitions the entries give (神阙 禁不可刺; 经渠 不可灸); the findings its indication sentences name
  (「……三里主之」「太泉主心痛」「取三里」), work by work.
- A rule's source is a probe found in the corpus as written: cite the earliest witness the tool gives, not the attribution in
  the data (四总穴歌 is usually credited to a Ming book; say which book the corpus shows first). A term may change sense:
  四关 is the four joints in 《灵枢》, 合谷 and 太冲 in later books.

## Three levels, kept apart
- **Classical and teaching theory** says why a point is chosen; **standards** (GB/T 12346—2021, WHO terminology) say how to
  name and locate it; **clinical research** says whether acupuncture helps a defined population. A meta-analysis of
  acupuncture for chronic pain does not validate a Five-Shu or Yuan–Luo rule; a claim that one combination is better than
  another needs a comparative study. Use `modern.search` for modern evidence, typed by design.

## Pitfalls
- Never present the result as a diagnosis, a prescription or advice to a patient: it is the tradition's reasoning and the
  texts' record; whether and how to needle is for a qualified practitioner after examination.
- Keep the cautions with the points (thorax: pneumothorax; nape: medulla; eye; arteries; pregnancy — the tool leaves those
  points out when told the patient is pregnant).
- Machine reading: entries and indications are read by rules — quote the witness and let the reader check it.
