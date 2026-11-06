# ADR 0031 — 药膳: medicinal dishes by constitution, season and time, from listed foods, with the classics quoted

**Status:** accepted · 2026-11-04 · amends [ADR 0029](0029-diet-and-weight-for-singapore.md) (decision 7: "no herbs, tonics or
medicinal soups") and [ADR 0030](0030-diet-and-weight-worldwide.md)

## Context

Visitors asked the diet mode for 药膳 — dishes for health and wellbeing chosen by season, by the time of day, by one's
constitution (体质), with what nutrition science says of them and what the old texts say.  ADR 0029 had kept them out:
two preference questions cannot judge a constitution, herbs interact with medicines, and a model left to itself
invents recipes, doses and claims ("祛湿减肥", "补气血") and attributes sayings to books that do not contain them.
Each of those reasons names something a design must answer, not a reason to refuse:

- **The constitution.**  A published, validated questionnaire exists: 中华中医药学会 ZYYXH/T157-2009《中医体质分类与判定》
  (the CCMQ, 王琦 et al.), sixty self-report questions scored into nine constitutions with fixed thresholds.  It was
  superseded in April 2026 by a 27-question national standard (GB/T 46939—2025) whose items and scoring were not
  available; the 2009 questionnaire is still the widely published and validated one.
- **What may be eaten.**  China's National Health Commission lists the substances that are both food and traditional
  medicine (按照传统既是食品又是中药材的物质目录): 106 in all (87 in 2002; 6 in 2019 — as spices or seasonings only,
  当归 among them; 9 in 2023 — 黄芪 among them, with the NHC's explanation that pregnant and breastfeeding women and
  infants are not advised to eat them; 4 in 2024).  Everyday foods and these, in recipe amounts, are food, not
  prescriptions.
- **Interactions and who should not.**  Dang gui and goji can strengthen warfarin (case reports); astragalus may work
  against immunosuppressants; pregnancy, breastfeeding, kidney disease (potassium) and eating disorders call for no
  medicinal food at all without a clinician; long-simmered meat broths are rich in purines (gout).
- **The classics.**  The corpus the site carries (the 要籍语料) has the texts these dishes come from: 神农本草经,
  金匮要略, 备急千金要方 and 千金食治, 食鉴本草 (with its congees filed under 寒、暑、湿、燥、气、虚), 寿世青编,
  寿亲养老新书.  They say when, too: 「清晨食薑…晚食蘿卜」, 「夜食諸薑、蒜、蔥等，傷人心」, 羊肉「夏月不可食」,
  「二月、三月宜食韭」, 「飽食即臥乃生百病」.

## Decision

1. **A fixed set of dishes, not generated ones.**  `data/diet/make_medicinal.py` writes `web/js/diet/medicinal-data.js`:
   23 dishes (congees, soups, braises, teas, a steamed pear, a sesame paste) of everyday foods and listed substances
   in recipe amounts, each with its method, nature (寒凉平温热), the constitutions it suits and those a text warns
   against, its seasons and the seasons or times it is not for, allergens, meat, pork, the herbs in it, whether it
   is a long-simmered broth — and its classical passages.  The model may recommend only these, as given.
2. **Every quotation checked when it is built.**  Each of the 55 quotations must occur, character for character, in
   the passage of `corpus/web` it names; the build stops otherwise, and a test reads the pack again independently.
   The tool returns them with their passage ids, as citations, so the page's own check (`queueVerify`) marks a
   quotation the model copies 原文一致 and counts it as returned by the turn's tools.  Where texts disagree (山药 slightly
   warm or cool; 冬瓜 for summer, or "only after 霜降 and not for yin deficiency"; 胡桃 warm and good, or "動痰"), both are
   given; where a classic presents the dish as a prescription (当归生姜羊肉汤 for 寒疝), the result says so and offers only
   the everyday soup.
3. **Nutrition from data, partial when the data are.**  Per serving, the sum of USDA FoodData Central values
   (`data/diet/medicinal-usda.sources.json`, 32 foods); an ingredient without a record (薏苡仁, 陈皮, 菊花, 当归, 黄芪,
   山楂, 韭菜) is listed as not counted, never estimated.  Sodium against the region's limit,
   added sugar (optional), the glycaemic note on white-rice congee for diabetes, and saturated fat in broths are said.
4. **Safety first, then fit.**  `diet__medicinal`: pregnancy, breastfeeding, under 18, kidney disease, eating disorders
   and unexplained weight loss — no medicinal dishes at all (status `not_offered`, ordinary meals instead); unknown
   conditions or medicines — those two questions first (`needs_information`); then dishes with an allergen, against a
   food rule, with goji or dang gui for a blood thinner, astragalus for an immunosuppressant, any herb for "other" or
   "not sure" medicines, a purine-rich broth for gout, or warned against for the person's constitution (cold dishes for
   阳虚, hot ones for 阴虚 and 湿热, and each text's own warnings) are left out, each with its reason — and the passage
   when a classic is the reason.  Out of season (by the visitor's own hemisphere and climate, never China's calendar
   abroad) and wrong time of day likewise.  The rest are ranked by constitution (是 3, 倾向是 1.5), then season (2).
5. **Constitution only from the questionnaire or a practitioner.**  `diet__constitution` scores the sixty answers as the
   standard does; a type is judged only when all its items are answered.  The opening screen carries the
   questionnaire (Chinese and English only — its meaning rests on its wording — with the page around it in all eight
   languages), a short safety check, and the dishes, computed in the page without a model and sent nowhere.  In chat
   the model does not ask sixty questions or judge a constitution from a description; without one, dishes follow the
   season and time only.
6. **Layers kept apart.**  Each result names what supports what: `classical_text` (historical statements),
   `tcm_food_guideline` (natures, constitutions), `food_composition` (USDA), `personalization_algorithm` (this tool's
   rules), `local_data` (the homology list), `modern_guideline` (the interaction sources).  The instructions forbid
   presenting a classic's 「主…」 as modern evidence, calling a dish a treatment, adding herbs or changing amounts.

## Consequences

- The diet mode can answer "what should I eat this season, for my constitution, at this meal, and what do the classics
  say" with dishes it can stand behind, and the visitor sees why others were left out.
- What it cannot do: judge a pattern (证), treat anything, or say a dish changes a constitution.  The 2009
  questionnaire's result is labelled as indicative; the 2025 standard should replace it when its text is available.
- Coverage is uneven: 血瘀质 has few dishes (山楂茶, 韭菜炒蛋 in spring); several herbs have no USDA record; the
  dishes are Chinese.  Adding a dish means its passages in the corpus pack, its USDA records, and its annotations.
- Herb–drug knowledge is a short list; the instructions send anyone on regular medicines to a pharmacist, and "other"
  or "not sure" medicines exclude every dish with a herb.
- Extended (2026-11-05) to 61 dishes and 128 quotations, adding 饮膳正要 and 食疗本草 and the texts' own recipes
  (食鉴本草's congees, 饮膳正要's carp and duck with adzuki beans, 寿亲养老新书's wontons and 薤白粥); the texts' calendar
  now also rules out ginger in autumn; very sweet dishes are left out for diabetes, beef for no-beef, fish for
  no-seafood, honey for vegans.  USDA records for 52 more foods (84 in all) were collected the same way.
- Tests: `tests/test_diet.py` — the questionnaire's counts, reverse scoring, bands and the standard's two worked
  examples; every exclusion under every constitution × season × region tried; the classics as reasons; nutrition sums;
  the data module regenerated identically; every quotation found in the pack; and in Chromium, the self-check without a
  model or a request, and a chat turn whose quotation the page marks 原文一致.
