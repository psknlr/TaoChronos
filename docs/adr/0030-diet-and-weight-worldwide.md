# ADR 0030 — 饮食与体重管理 worldwide: the visitor's region decides, international defaults until they say

**Status:** accepted · 2026-11-01 · amends [ADR 0029](0029-diet-and-weight-for-singapore.md)

## Context

ADR 0029 built the diet mode for Singapore: Singapore's BMI cut-offs, HPB's plate and limits, its monsoons and public
holidays, and a plan made of hawker dishes.  Visitors come from everywhere, and the mode should serve them all.  Read
from anywhere else, it mis-served them in several ways:

- **BMI.**  Singapore uses the lower thresholds for Asian adults (23 and 27.5).  Applied to everyone, they read an
  international visitor's BMI of 24 as overweight and offer a deficit where WHO's scale (25 and 30) would not.
  Neither scale fits everyone: NICE uses the lower thresholds for South Asian, Chinese, other Asian, Middle Eastern,
  Black African and African-Caribbean family backgrounds wherever they live, and China has its own standard (24 and
  28, WS/T 428-2013).
- **Guides and limits.**  National food guides differ in their plate models and limits (the UK's 6 g of salt and 30 g
  of free sugars; China's 5 g of salt and 25–30 g of cooking oil; the US's 2,300 mg of sodium in its 2020–2025 edition).
- **Seasons.**  The monsoons are Singapore's.  Most visitors live with four temperate seasons, half of them in the
  southern hemisphere, or in other tropical, arid or monsoon climates.
- **Food.**  A plan of chicken rice and laksa is of little use in London or São Paulo.
- **Festivals.**  Deepavali and Hari Raya are not everyone's; Thanksgiving, Easter and Christmas are not Singapore's.

## Decision

1. **A region, stated by the visitor.**  `profile.region` (an ISO code from `web/js/diet/regions.js`, 35 countries and
   territories) carries each country's time zone, hemisphere, broad climate, BMI scale, national food guide and dish
   packs.  A country not listed, or none stated, gets the international defaults (WHO's scale, guide and limits, no
   season) — the mode assumes no country.  The model asks where the visitor lives only among the optional questions,
   after the safety questions.  The page may suggest a region from the time zone in its own quick check and
   opening line, without sending it anywhere; the model is told only what the visitor says.
2. **The BMI scale follows the person, then the place.**  A family background NICE and WHO name gets the lower
   thresholds (China's standard in China); a background stated otherwise gets WHO's; else the region's scale; else
   WHO's.  On WHO's scale for want of a background, a BMI where the scales disagree on the advice (23–24.9 and
   27.5–29.9, when weight loss is asked for) makes the background a question, still within two a turn.  Waist
   thresholds follow the same scale.
3. **The guide sets the plate and the limits.**  WHO, Singapore, Malaysia, China, the US, the UK, Canada, Australia,
   Japan and India each have their plate model; where the guide's own number was checked it is used (sodium, salt,
   sugar, cooking oil), else WHO's, and the result says so.
4. **Seasons by hemisphere and climate.**  Temperate, cold, subtropical and arid climates get meteorological seasons
   (inverted in the south), the tropics get "wet and dry, warm all year", South Asia the IMD's four seasons, Singapore
   its monsoons (MSS).  A large country says that its climate varies; a visitor may give their own climate and
   hemisphere instead.  No region, no season.  Still no live weather.
5. **Everyday meals for everywhere; dish packs for regions.**  Fourteen meals, with snacks, sides and fruit, made of plain
   foods (oats, wholemeal bread, eggs, yoghurt, chicken, salmon, lentils, chickpeas, black beans, brown and white rice,
   wholewheat pasta, potato, vegetables, fruit, olive oil), each the sum of its parts from USDA FoodData Central at the
   weights stated, are planned anywhere (`regions: ["*"]`).  The Singapore/Malaysia hawker pack is planned only there
   (`regions: ["SG", "MY"]`); a dish asked for by name may still come from any pack.  Elsewhere the plan says there is
   no dish data for local dishes yet: the model may suggest them in words, never with numbers.
6. **Festivals worldwide, ranked by where they are kept.**  Christmas, Western Easter (computus), US and Canadian
   Thanksgiving and Dongzhi are computed; the Lunar New Year and Mid-Autumn come from published calendars; Eid and
   Diwali dates are Singapore's gazetted ones, marked approximate elsewhere; each festival says who keeps it, those
   kept where the visitor lives come first, and Thanksgiving appears only in its country.
7. **The solar terms stay a Chinese cultural calendar**, dated in China Standard Time, with a note by place: they
   broadly follow the seasons in China, Japan, Korea and Taiwan (traditional seasonal eating may be quoted from the
   classics as history); they are reversed in the southern hemisphere and describe no climate in the tropics.
8. **Unchanged**: screening and its gates, the energy arithmetic and floors, two questions a turn, the tools running in
   the page, nothing recorded, ephemeral conversations, the traditional layer that never diagnoses.

## Consequences

- The Singapore pack and its sources stay as they were; nothing Singapore visitors had is lost (their BMI scale,
  guide, monsoons, festivals and dishes come with `region: SG`).
- The everyday meals' values are USDA's, read through mirrors that name each entry (`data/diet/usda.sources.json`);
  a part lacking a value leaves the meal without it (olive oil's sodium and fibre, brown rice's saturated fat), so a
  day's sodium, fibre and saturated fat are often reported as not totalled.  Values are for food cooked without salt.
- Region tables are coarse: one time zone, hemisphere and climate per country.  Dish packs beyond Singapore/Malaysia,
  checked national limits beyond those listed, and festival dates after 2027 remain to be added.
- Tests: `tests/test_diet.py` — the three scales and who gets which, the guides' limits, seasons by hemisphere and
  climate, computed festivals, plans that use a region's pack only there, and the end-to-end flow unchanged.
