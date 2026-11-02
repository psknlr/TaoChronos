# 饮食与体重管理 — diet and weight, worldwide

A mode of the web client in which 道乃久 gives evidence-based eating advice and weight-management plans to adults
anywhere: by the visitor's own country — its food guide and limits, the BMI scale that fits them, its season and
festivals, and its dishes where there is a dish pack — and by international (WHO) defaults until they say where they
live; with an optional traditional (TCM) food layer, every number from the mode's own tools with its source, and
nothing of the conversation recorded.  The decisions and their reasons: [ADR 0029](adr/0029-diet-and-weight-for-singapore.md)
(the mode, its privacy, its screening) and [ADR 0030](adr/0030-diet-and-weight-worldwide.md) (every region).  The
code: `web/js/diet/` (the engine and tools; `regions.js` the countries), `web/js/view/diet.js` (its screens); tests:
`tests/test_diet.py`.

```
 visitor ──► 饮食与体重管理 (side bar)            the page                                    model service
              │                              ┌──────────────────────────────────────┐      (the visitor's
              ├─ quick check ──────────────► │ assess · plan        (no model, nothing sent)  choice)
              │                              │                                      │
              └─ a question ───────────────► │ agent loop ── tool call diet__* ──► web/js/diet/*.js
                                             │     ▲                 (no runtime, no server)
                                             │     └── result (numbers, provenance) │ ◄───────► answer, phrased
                                             │ records ✕ · feedback without content │
                                             │ kept in memory unless 保存在本浏览器    │
                                             └──────────────────────────────────────┘
```

## What a visitor sees

- **The way in**: 饮食与体重管理 under 新对话, or the card on the opening screen.  The mode's opening screen says what
  happens to what one tells it (not recorded; kept in this page only unless kept; the model service reads what one
  writes; not a diagnosis), today where the time zone suggests (date, country, season, solar term, the next festival
  kept there), six starters, and **不用模型，先快速算一算** — a form (with the country, preselected from the time zone,
  and the family background that decides the BMI scale) whose answers are assessed and planned without a model, shown
  as a table, and sent to the model only if the visitor presses 带着这些信息问道乃久.
- **A conversation**: the model asks one or two questions a turn (health conditions and body measurements first, then
  the sex the energy equation should use and activity), gives two or three things to do at once while it asks, and a
  first plan within about two turns; where they live is asked among the optional questions, after the safety ones.  A
  plan is a table — meal, dish and serving, energy, protein, how to cook or order — with
  the day's total against the target, three things to do today, and a line of what has been recorded so the visitor
  can correct it.  Swaps, a week, festive advice, the traditional layer and a weekly review follow when asked.
- **The banner** at the head of a diet conversation: not recorded; kept only in this page (保存在本浏览器 keeps it in this
  browser, unencrypted; 不再保存 removes it again).

## The tools

| Tool (plain words on the page) | What it does |
|---|---|
| `diet__assess` (饮食评估) | Reads the profile (every field optional; left out = unknown), screens it, computes what the screening allows — BMI on the scale that fits the visitor, Mifflin–St Jeor resting energy, total energy as a range over the activity assumption, the target, protein, the day's limits and plate model of their national guide — and names the next questions (at most two). |
| `diet__plan` (饮食方案) | A day or up to seven, under the hard constraints: everyday meals of plain foods anywhere, and a region's own dishes where it has a dish pack (Singapore and Malaysia); each meal with its serving, numbers, typical allergens, how to cook or order it, and its source; a vegetable side and fruit to complete the plate; the day's totals and checks (energy, protein, sodium, saturated fat). |
| `diet__swap` (换菜核算) | One meal replaced — by a named dish or the best other — and the whole day rebuilt and re-checked; a dish breaking a hard rule is refused. |
| `diet__dishes` (菜品营养) | Dishes by name or kind, with every nutrient the source gave, the source, another source's figure when they disagree, and why a dish is not for this visitor. |
| `diet__context` (季节与节令) | The date on the visitor's clock, the season where they live (temperate seasons by hemisphere, tropical wet and dry, South Asia's and Singapore's monsoons) and what it means for eating, hydration and food safety, the current and next solar term (a Chinese cultural calendar, with what it means there), and the festive seasons in the next 60 days worldwide, those kept where the visitor lives first. |
| `diet__food_nature` (食物寒热) | The natures (寒/凉/平/温/热, "heaty"/"cooling") of ordinary foods where references agree, the disputed ones, and what two preference answers mean for food style.  `tcm_pattern_status: unconfirmed`. |
| `diet__progress` (体重趋势) | Weigh-ins as a trend (least squares over four weeks; this week's average against last week's): too early, on track, faster than planned, plateau, rising, stable. |

### Screening

| Answer | Effect | What happens |
|---|---|---|
| none of the below, BMI overweight or above on their scale, asks to lose weight | — | a deficit of about 300–500 kcal, never below max(resting estimate, 1,200 kcal women / 1,500 men) |
| BMI in the healthy range of their scale and asks to lose weight | maintenance | food quality, protein, strength exercise |
| no goal stated | maintenance | eating better, no deficit |
| aged 65–74 · diabetes without insulin or a sulfonylurea · high blood pressure · high cholesterol · prediabetes · fatty liver · gout · warfarin · heart disease · BMI at a further action point (≥35 on WHO's scale, ≥32.5 on the lower thresholds) | caution | a plan, with what to watch |
| aged 75+ · underweight | maintenance | energy kept up; see a doctor if weight is falling |
| under 18 · pregnant · breastfeeding · insulin or a sulfonylurea · a condition not listed · unsure | no target | healthy-plate guidance, the reason said |
| eating disorder (now or past) | professional first | no BMI, energy, weight or plan numbers at all |
| kidney disease · unexplained weight loss · wants to lose weight while underweight | professional first | general safe eating only; no protein target with kidney disease |

Diabetes alone asks first whether the visitor takes insulin or a sulfonylurea.  On WHO's scale for want of a family
background, a BMI of 23–24.9 or 27.5–29.9 with weight loss asked for makes the background a question (the scales
disagree there on whether a deficit is advised).  A value out of human bounds is reported
and not used.  The sex for the equation may be withheld: then no energy number is given, and portions follow the plate.

## Regions

`web/js/diet/regions.js` lists 35 countries and territories, each with its time zone, hemisphere, broad climate, BMI
scale, food guide and dish packs; any other country, or none, gets the international defaults.

| | Scale | Cut-offs (overweight / obesity) | Applies to |
|---|---|---|---|
| `who` | WHO international classification | 25 / 30 (classes II and III at 35 and 40) | the default |
| `asian` | lower thresholds (WHO 2004; NICE; Singapore's MOH) | 23 / 27.5 (further action points 32.5, 37.5) | Asian, Middle Eastern, Black African and African-Caribbean family backgrounds anywhere; residents of East, South and Southeast Asian countries when no background is given |
| `china` | WS/T 428-2013 | 24 / 28; central obesity at a waist of 90 / 85 cm | visitors in China |

| Guide | Plate model | Limits checked against the guide's own numbers |
|---|---|---|
| WHO (default) | vegetables, fruit, wholegrains, pulses; ≥400 g fruit and vegetables | sodium 2,000 mg (salt 5 g); free sugars <10% of energy (ideally <5%) |
| Singapore (HPB My Healthy Plate) | ¼ wholegrains, ¼ protein, ½ fruit and vegetables | sodium 2,000 mg; added sugar ≤10% |
| UK (Eatwell Guide; NHS) | 5 a day, starchy wholegrain foods, protein, dairy | salt 6 g; free sugars 30 g |
| US (Dietary Guidelines; MyPlate) | ½ fruit and vegetables, grains, protein, dairy | sodium 2,300 mg (2020–2025 edition); added sugars limited |
| China (Dietary Guidelines 2022) | the Chinese Food Guide Plate | salt 5 g; cooking oil 25–30 g |
| Malaysia, Canada, Australia, Japan, India | their national plate or guide | WHO's numbers, said so |

Seasons: temperate, cold, subtropical and arid countries have meteorological seasons by hemisphere (with the heat and
food-safety advice of summer, the arid climates' extreme heat); tropical countries "warm all year, wet and dry
seasons"; India the India Meteorological Department's four seasons; Singapore the MSS monsoons.  Countries spanning
several climates say so, and a visitor may give their own climate and hemisphere.  Festivals: Christmas, Western
Easter, US and Canadian Thanksgiving and Dongzhi computed; the Lunar New Year and the Mid-Autumn Festival from published
calendars; Eid al-Fitr, Eid al-Adha, Diwali and Vesak from Singapore's gazetted 2026–2027 dates, approximate elsewhere.

## The data

`web/js/diet/dishes.js` is generated by [`data/diet/make_dishes.py`](../data/diet/README.md) from two sets of collected
records, each value with its URL and notes, and the script's annotations — 81 items:

- **Everyday meals, anywhere** (`regions: ["*"]`): 14 breakfasts, lunches and dinners (porridge oats, wholemeal toast and
  eggs, yoghurt with fruit and nuts; chicken, salmon, lentil, chickpea, black-bean, pasta, tofu and egg plates), snacks,
  vegetable sides and fruit — each the sum of plain foods at the weights stated (`data/diet/usda.sources.json`: USDA
  FoodData Central per 100 g, read through mirrors that name the entry), cooked without salt, with the olive oil stated.
- **The Singapore/Malaysia pack** (`regions: ["SG", "MY"]`, `data/diet/sg-dishes.sources.json`): 39 hawker, kopitiam and
  food-court dishes (Chinese, Malay, Indian, Peranakan), drinks and festive foods.

| Source | Items | Notes |
|---|---|---|
| USDA FoodData Central (SR Legacy / Foundation entries), per 100 g scaled | 26 plain foods | 16 with all eight nutrients; the others' gaps stay null and so do the meals' that use them |
| HPB values with HPB food codes, as quoted by Nutri Kaki | 3 | the chicken rices: F05100133, F05100112, F05100131 |
| HPB values quoted without codes (Daniel Food Diary's list from HPB's iDAT app, Mothership, Women's Weekly, HungryGoWhere, HealthXchange articles) | ~35 | energy only for most |
| HealthHub (HPB) pages | 4 | energy only |
| HealthXchange (SingHealth/KKH dietitians' tables), magazines, Malaysia's MOH | ~15 | fuller panels for some dishes; marked by publisher |

The status is `secondary_source_unverified`: **before production use, check the values against FoodData Central and
HPB's Energy & Nutrient Composition of Food (focos.hpb.gov.sg) and their terms of use**, and replace the secondary
figures.  Fields no source gave are `null` and stay so; a day's total of a nutrient is given only when every item has
it.  The allergen, halal, pork and vegetarian marks, tags and cooking or ordering tips are this project's, from usual
recipes, and conservative (a dish often cooked with lard is marked pork).  Guidance values and their sources are in
`web/js/diet/sources.js`; the activity factors, protein range and season rules are this project's and labelled so.
The solar terms are computed (Meeus, ch. 25) and agree with the NAOJ 2026 almanac within 15 minutes.

### Evidence labels

Every source carries one: `modern_guideline`, `food_composition`, `local_data`, `personalization_algorithm`,
`tcm_food_guideline`, `classical_text`.  The instructions have the model say which kind of support each recommendation
has, and never present one as another — a traditional food nature is not evidence of an effect, a classic's sentence
is not modern evidence, a rule of this project is not a trial result.

## Privacy

- **Not sent to the site's server**: the diet tools' calls are answered by the page's own code (`routed()` in
  `app.js`); the site's server and runtime are never sent them.  The engine makes no network request, reads no location and needs no change to the Content-Security-Policy
  or Permissions-Policy.
- **Where the visitor lives**: the model hears only what the visitor says.  The opening line and the quick check read the
  time zone to preselect a country; nothing of it is sent.
- **Never recorded**: `healthConv(conv)` — a diet conversation, one that called a diet tool, or one in which the visitor
  wrote their own measurements or conditions — sends no conversation record, whatever the visitor chose under
  设置 → 数据; feedback on it carries no question or answer; the consent question is not asked for it.
- **Kept in memory**: a diet conversation is `ephemeral` until kept (`store.js` writes none); reloading or closing the
  page ends it.  Kept, it is stored in IndexedDB like any conversation — not encrypted, as the banner says.
- **The model service** the visitor chose reads what they write, as in any conversation; the quick check sends nothing.

## Limits and next steps

- Verify the values against FoodData Central and HPB's database; add sodium, saturated fat and fibre where the gaps
  are; dish packs for more regions (each a region code on the dish and its own source records); recipes with
  ingredient weights for shopping lists.
- One time zone, hemisphere and climate per country; live weather would need a new `connect-src` origin and a privacy
  review — today the season is calendar-only.
- National limits are checked for WHO, Singapore, the UK, the US and China; the other guides fall back on WHO's numbers.
- Festival dates are published for 2026–2027 only (the computed ones run on).
- The page's own screens are in Chinese, English, Malay and Traditional Chinese; the other four languages show the new
  strings in Chinese until translated.
- The engine is JavaScript only; the Python harness, the tool console and the D1 backup do not carry it.
