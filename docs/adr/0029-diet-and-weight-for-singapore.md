# ADR 0029 — 饮食与体重管理 for Singapore: a mode of its own, computed in the page, never recorded

**Status:** accepted · 2026-11-01

## Context

The proposal *TaoChronos Scientific Dietary Wellness & Personalized Weight Management* asked for an assistant that turns
modern nutrition, an optional TCM food layer, the 24 solar terms and local climate into personal eating plans, with one
or two questions a turn, deterministic numbers, strict evidence separation and health data kept out of the records.  It
was written for China (the 2024 national obesity dietary guideline, PIPL, northern-hemisphere solar terms).  The request
was to make the agent give dietary recommendations **in Singapore**, and to take a better route where there is one.

Singapore changes several of the proposal's premises:

- **Climate.**  Singapore lies 1° north of the equator.  Its year is set by the monsoons (Northeast Monsoon December to
  early March, inter-monsoon, Southwest Monsoon June to September, inter-monsoon), not by the temperate seasons the
  solar terms describe; seasonal advice written for China's winters (warming tonics) or summers does not carry over.
  The solar terms remain a living *cultural* calendar there (冬至 and its tang yuan).
- **Guidance.**  The Health Promotion Board's *My Healthy Plate* (a quarter wholegrains, a quarter protein, half fruit
  and vegetables), sodium at most 2,000 mg, added sugar at most 10% of energy, Nutri-Grade for drinks, and the Ministry
  of Health's BMI cut-offs for Asian adults (23 and 27.5, not 25 and 30).
- **Food.**  Most adults eat out — hawker centres, kopitiams, food courts — so a plan must be made of dishes people buy,
  and of how to order them (kopi-O kosong, siew dai, less gravy), across Chinese, Malay, Indian and Peranakan food,
  halal and vegetarian.
- **Festivals.**  Chinese New Year, Ramadan and Hari Raya, Deepavali, the Mid-Autumn Festival and Christmas move what
  people eat more than the weather does.

And the repository changes others: the classics' tools run in the browser (Pyodide) or on the site's container; the
records of the test period go to the institute's relay ([ADR 0012](0012-default-service-relay.md)); feedback may carry
a turn ([ADR 0028](0028-feedback-on-answers.md)); only 我的资料 conversations were kept out of both
([ADR 0022](0022-the-users-own-data.md)) — a visitor typing their weight into an ordinary chat was not.

## Decision

1. **A mode, not a new site.**  饮食与体重管理 (`conv.mode = "diet"`) is entered from the side bar or the opening screen.
   Its conversations are offered seven tools of their own (`diet__assess`, `diet__plan`, `diet__swap`, `diet__dishes`,
   `diet__context`, `diet__food_nature`, `diet__progress`) and, to quote a classic when asked, the corpus search and
   reading; the platform's standing instructions stay (identity, evidence discipline, nothing of the inside named, no
   diagnosis or prescription) and the mode's are added after them (`web/js/diet/prompt.js`).  The classics' tools,
   research gates and quotation checks are unchanged.
2. **Deterministic tools, in the page.**  The tools are plain JavaScript modules (`web/js/diet/`) that the page runs
   itself (`routed()` in `app.js`): no runtime, no server, no network — so nothing the visitor says of their health goes
   anywhere but to the model service they chose, the site's container never hears of it, and there is no Pyodide to
   download for a diet question.  The model asks, explains and phrases; every number (BMI, energy, targets, a dish's
   energy and nutrients, a day's totals, a trend) comes from the tools, and the instructions forbid any other.
3. **Screening first, two questions a turn.**  `diet__assess` reads what is known (a field left out is unknown, never
   "none"), screens it, and names the next questions — at most two, and **the health-conditions question before body
   measurements** (the proposal asked them the other way round: asked first, a pregnancy, an eating disorder or kidney
   disease means weight need not be asked at all).  Its status decides what may follow: `ready` (a plan, with an energy
   target), `needs_information`, `general_guidance_only` (no calorie target: under 18, pregnancy or breastfeeding,
   insulin or a sulfonylurea, an unlisted or unsure condition) or `see_professional_first` (an eating disorder — then no
   BMI, energy or weight numbers at all —, kidney disease, unexplained weight loss, wanting to lose weight while
   underweight).  Energy is Mifflin–St Jeor times an activity *range*; a deficit of 300–500 kcal only for an adult with
   BMI ≥ 23 who asked to lose weight, never below the larger of the resting estimate and 1,200 / 1,500 kcal; a healthy
   BMI gets body-composition advice instead, and no goal stated means no deficit.
4. **Plans from Singapore dishes, under hard constraints.**  `diet__plan` builds a day or a week from a dataset of
   Singapore dishes (`web/js/diet/dishes.js`, generated from `data/diet/`), never breaking an allergy, halal, vegetarian, vegan, no-pork, no-beef or
   no-seafood rule; within them it fits each meal to its share of the target, varies dishes across the week, prefers
   less sodium and saturated fat and more protein and vegetables, adds a vegetable side and fruit to complete the plate,
   and says how to order.  Totals are sums of the dataset's values; a nutrient missing for any item is reported as not
   totalled, never filled in; a day it cannot bring within range says by how much; no dish meeting the constraints is
   reported as such.  `diet__swap` rebuilds and re-checks the whole day, and refuses a dish that breaks a rule.
5. **Provenance on every value, and honesty about it.**  HPB's own database (FOCOS) could not be reached when the data
   were gathered; the dish values are HPB's as quoted by publications that cite them (three with HPB food codes), a
   few from SingHealth's HealthXchange or magazines (marked), and plain foods from USDA FoodData Central per 100 g scaled
   to a stated serving.  The dataset says `secondary_source_unverified`; each dish names its publisher and URL, and
   `other_figure` keeps a disagreeing source's value.  Allergen, halal and pork marks are this project's, from usual
   recipes, conservative, and the plans tell a visitor with an allergy to ask the stall.
6. **Singapore's calendar, not China's seasons.**  `diet__context` works on Singapore's clock (UTC+8), gives the
   monsoon phase from MSS climatology with what it means for eating, hydration and food safety, the solar terms computed
   from the Sun's apparent longitude (Meeus, checked against the NAOJ 2026 almanac to within 15 minutes; a term within
   half an hour of midnight says its date may be a day off) as a cultural calendar, and the festive seasons ahead from
   MOM's 2026 and 2027 lists with their foods and tips.  No live weather is read (no new network origin, CSP unchanged,
   no geolocation): the result says `calendar_only`.  The season changes food choices, never the energy target.
7. **The traditional layer is optional and never a diagnosis.**  `diet__food_nature` gives the natures of ordinary
   foods (寒凉平温热, and Singapore's everyday "heaty"/"cooling") only where common references agree — saying so where they
   do not (mango, coffee) — and turns two preference answers into food-style advice.  `tcm_pattern_status` stays
   `unconfirmed`; no herbs, tonics or medicinal soups; a pattern needs a TCMPB-registered practitioner.  A classic is
   quoted through the corpus tools and labelled a historical statement.
8. **Health is never recorded, and is kept only in the page by default.**  `healthConv()` (`web/js/diet/privacy.js`)
   holds for a diet conversation, any conversation that called a diet tool, and an ordinary one in which the visitor
   wrote their own measurements or conditions (`healthText`: first person, or a body measurement with its unit — not a
   question about 消渴 or a herb's 9 克).  Such a conversation sends no record **whatever the visitor chose**, its
   feedback carries no word of it, and the consent question is not asked for it.  A diet conversation is `ephemeral`:
   `store.js` writes none, so it is gone with the page until the visitor presses 保存在本浏览器 (kept unencrypted in
   that browser, and said so).
9. **A model is optional.**  The diet opening screen has a quick check that runs `assess` and `plan` on the device and
   shows the result without sending anything; 带着这些信息问道乃久 sends it as a message only when pressed.

## Consequences

- Seven tools exist only in the browser: the tool console (工具台), the local server's catalog and the D1 backup do not
  list them, and the Python harness has no `diet` family.  If a later release needs them server-side, they belong in an
  isolated plugin with a `wellness:read` permission no research agent holds, as the proposal suggested.
- The dataset is small (≈ 40 main dishes) and mostly energy-only; protein, sodium and fibre are often not totalled, and
  vegetarian or multi-allergy plans have few dishes to choose from (a dish may appear twice in a day, which the plan
  notes).  Before production use the values must be checked against HPB's database and its licence; a recipe database
  with ingredient weights would make shopping lists possible (not built).
- Festival dates end with 2027; later years say there are none verified.  Live weather (NEA's public APIs) would need a
  new `connect-src` origin and its own privacy review.
- An ordinary conversation in which someone writes "我想减肥" is no longer recorded; research turns lose nothing they
  needed, and a few borderline first-person questions are not recorded.
- Tests: `tests/test_diet.py` (the engine under Node — screening, energy, constraints under every combination tried,
  sums, swaps, the dataset's provenance, solar terms against NAOJ, festivals, the review, the traditional layer, the
  tools, the health detector — and the mode in Chromium against a scripted provider: tools routed to the page, no
  record with consent given, feedback without content, ephemeral until kept, an ordinary chat with a weight not
  recorded).  Design notes and data sources: [docs/diet.md](../diet.md).
