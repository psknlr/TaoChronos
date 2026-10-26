---
name: acupoint-selection
description: Reason a choice of acupuncture points as the tradition does (选穴配穴) — location and nature, channels, core points, the purpose of every added point, the record — each rule with its classical witness and the modern evidence apart.
tools: [study.acupoints, study.point, classics.search, classics.get_passage, validation.verify_quote, modern.search]
applies_to: [scholar, evidence, skeptic]
tags: [针灸, 选穴, 配穴, 特定穴, 腧穴]
---
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
