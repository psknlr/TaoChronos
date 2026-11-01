# 饮食与体重管理 — diet and weight for Singapore

A mode of the web client in which 道乃久 gives evidence-based eating advice and weight-management plans to adults in
Singapore: hawker-centre and home food, the monsoons and the festive seasons, an optional traditional (TCM) food layer —
with every number computed in the visitor's browser, and nothing of the conversation recorded.  The decision and its
reasons: [ADR 0029](adr/0029-diet-and-weight-for-singapore.md).  The code: `web/js/diet/` (the engine and tools),
`web/js/view/diet.js` (its screens); tests: `tests/test_diet.py`.

```
 visitor ──► 饮食与体重管理 (side bar)            the page (browser)                          model service
              │                              ┌──────────────────────────────────────┐      (the visitor's
              ├─ quick check ──────────────► │ assess · plan        (no model, nothing sent)  choice)
              │                              │                                      │
              └─ a question ───────────────► │ agent loop ── tool call diet__* ──► web/js/diet/*.js
                                             │     ▲                 (in the page: no runtime, no server)
                                             │     └── result (numbers, provenance) │ ◄───────► answer, phrased
                                             │ records ✕ · feedback without content │
                                             │ kept in memory unless 保存在本浏览器    │
                                             └──────────────────────────────────────┘
```

## What a visitor sees

- **The way in**: 饮食与体重管理 · SG under 新对话, or the card on the opening screen.  The mode's opening screen says what
  happens to what one tells it (not recorded; kept in this page only unless kept; the model service reads what one
  writes; not a diagnosis), today in Singapore (date, monsoon phase, solar term, the next festival), six starters, and
  **不用模型，先在本机算一算** — a form whose answers are assessed and planned on the device, shown as a table, and sent to
  the model only if the visitor presses 带着这些信息问道乃久.
- **A conversation**: the model asks one or two questions a turn (health conditions and body measurements first, then
  the sex the energy equation should use and activity), gives two or three things to do at once while it asks, and a
  first plan within about two turns.  A plan is a table — meal, dish and serving, energy, protein, how to order — with
  the day's total against the target, three things to do today, and a line of what has been recorded so the visitor
  can correct it.  Swaps, a week, festive advice, the traditional layer and a weekly review follow when asked.
- **The banner** at the head of a diet conversation: not recorded; kept only in this page (保存在本浏览器 keeps it in this
  browser, unencrypted; 不再保存 removes it again).

## The tools

| Tool (plain words on the page) | What it does |
|---|---|
| `diet__assess` (饮食评估) | Reads the profile (every field optional; left out = unknown), screens it, computes what the screening allows — BMI against Singapore's Asian cut-offs, Mifflin–St Jeor resting energy, total energy as a range over the activity assumption, the target, protein, the day's limits — and names the next questions (at most two). |
| `diet__plan` (饮食方案) | A day or up to seven from the dish dataset, under the hard constraints; each meal with its serving, numbers, typical allergens, how to order, and its source; a vegetable side and fruit to complete the plate; the day's totals and checks (energy, protein, sodium, saturated fat). |
| `diet__swap` (换菜核算) | One meal replaced — by a named dish or the best other — and the whole day rebuilt and re-checked; a dish breaking a hard rule is refused. |
| `diet__dishes` (菜品营养) | Dishes by name or kind, with every nutrient the source gave, the source, another source's figure when they disagree, and why a dish is not for this visitor. |
| `diet__context` (新加坡节令) | Singapore's date, the monsoon phase and what it means for eating, hydration and food safety, the current and next solar term (a cultural calendar), and the festive seasons in the next 60 days with their foods and tips. |
| `diet__food_nature` (食物寒热) | The natures (寒/凉/平/温/热, "heaty"/"cooling") of ordinary foods where references agree, the disputed ones, and what two preference answers mean for food style.  `tcm_pattern_status: unconfirmed`. |
| `diet__progress` (体重趋势) | Weigh-ins as a trend (least squares over four weeks; this week's average against last week's): too early, on track, faster than planned, plateau, rising, stable. |

### Screening

| Answer | Effect | What happens |
|---|---|---|
| none of the below, BMI ≥ 23, asks to lose weight | — | a deficit of about 300–500 kcal, never below max(resting estimate, 1,200 kcal women / 1,500 men) |
| BMI 18.5–22.9 and asks to lose weight | maintenance | food quality, protein, strength exercise |
| no goal stated | maintenance | eating better, no deficit |
| aged 65–74 · diabetes without insulin or a sulfonylurea · high blood pressure · high cholesterol · prediabetes · fatty liver · gout · warfarin · heart disease · BMI ≥ 32.5 | caution | a plan, with what to watch |
| aged 75+ · underweight | maintenance | energy kept up; see a doctor if weight is falling |
| under 18 · pregnant · breastfeeding · insulin or a sulfonylurea · a condition not listed · unsure | no target | healthy-plate guidance, the reason said |
| eating disorder (now or past) | professional first | no BMI, energy, weight or plan numbers at all |
| kidney disease · unexplained weight loss · wants to lose weight while underweight | professional first | general safe eating only; no protein target with kidney disease |

Diabetes alone asks first whether the visitor takes insulin or a sulfonylurea.  A value out of human bounds is reported
and not used.  The sex for the equation may be withheld: then no energy number is given, and portions follow the plate.

## The data

`web/js/diet/dishes.js` is generated by [`data/diet/make_dishes.py`](../data/diet/README.md) from the collected records
(`data/diet/sg-dishes.sources.json`: each value with its URL and notes) and the script's annotations: 66 items — 39 main dishes from Singapore's hawker, kopitiam and food-court
repertoire (Chinese, Malay, Indian, Peranakan), drinks (kopi, teh and their orders, bubble tea, sugarcane juice),
festive foods and desserts, and plain foods.

| Source | Items | Notes |
|---|---|---|
| HPB values with HPB food codes, as quoted by Nutri Kaki | 3 | the chicken rices: F05100133, F05100112, F05100131 |
| HPB values quoted without codes (Daniel Food Diary's list from HPB's iDAT app, Mothership, Women's Weekly, HungryGoWhere, HealthXchange articles) | ~35 | energy only for most |
| HealthHub (HPB) pages | 4 | energy only |
| HealthXchange (SingHealth/KKH dietitians' tables), magazines, Malaysia's MOH | ~15 | fuller panels for some dishes; marked by publisher |
| USDA FoodData Central (SR Legacy), per 100 g scaled to the serving | 8 | brown rice, firm tofu, egg, pak choi, banana, apple, watermelon; the home plates are sums of them, without oil or sauce |

The status is `secondary_source_unverified`: **before production use, check every value against HPB's Energy &
Nutrient Composition of Food (focos.hpb.gov.sg) and its terms of use**, and replace the secondary figures.  Fields no
source gave are `null` and stay so; a day's total of a nutrient is given only when every item has it.  The allergen,
halal, pork and vegetarian marks, tags and ordering tips are this project's, from the dishes' usual recipes, and
conservative (a dish often cooked with lard is marked pork).  Guidance values and their sources are in
`web/js/diet/sources.js`: MOH's Clinical Practice Guidelines on Obesity (2016) for the Asian BMI and waist cut-offs,
the WHO expert consultation (2004) for the further action points, HPB for My Healthy Plate, sodium, added sugar and
Nutri-Grade, WHO for fruit and vegetables, free sugars and fibre, Mifflin–St Jeor (1990) for resting energy; the
activity factors and protein range are this project's rules and labelled so.  The monsoons are MSS's climatology; the
festive dates MOM's 2026 and 2027 public-holiday lists (as reported) and the lunar calendar; the solar terms are computed
(Meeus, ch. 25) and agree with the NAOJ 2026 almanac within 15 minutes.

### Evidence labels

Every source carries one: `modern_guideline`, `food_composition`, `local_data`, `personalization_algorithm`,
`tcm_food_guideline`, `classical_text`.  The instructions have the model say which kind of support each recommendation
has, and never present one as another — a traditional food nature is not evidence of an effect, a classic's sentence
is not modern evidence, a rule of this project is not a trial result.

## Privacy

- **In the page**: the diet tools run in the browser (`routed()` in `app.js`); the site's server and runtime are never
  sent them.  The engine makes no network request, reads no location and needs no change to the Content-Security-Policy
  or Permissions-Policy.
- **Never recorded**: `healthConv(conv)` — a diet conversation, one that called a diet tool, or one in which the visitor
  wrote their own measurements or conditions — sends no conversation record, whatever the visitor chose under
  设置 → 数据; feedback on it carries no question or answer; the consent question is not asked for it.
- **Kept in memory**: a diet conversation is `ephemeral` until kept (`store.js` writes none); reloading or closing the
  page ends it.  Kept, it is stored in IndexedDB like any conversation — not encrypted, as the banner says.
- **The model service** the visitor chose reads what they write, as in any conversation; the quick check sends nothing.

## Limits and next steps

- Verify the dish values against HPB's database; add sodium, protein and fibre where HPB has them; widen the dataset
  (economy rice components, soups, more vegetarian and Indian dishes, home recipes with ingredient weights for
  shopping lists).
- Live weather and haze (NEA's public APIs on data.gov.sg) would need a new `connect-src` origin and a privacy review;
  today the season is calendar-only.
- Festival dates are verified for 2026–2027 only.
- The page's own screens are in Chinese, English, Malay and Traditional Chinese; the other four languages show the new
  strings in Chinese until translated.  Tamil is not among the page's languages.
- The engine is JavaScript only; the Python harness, the tool console and the D1 backup do not carry it.
