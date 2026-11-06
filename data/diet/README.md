# data/diet — the dish data of 饮食与体重管理

- `usda.sources.json` — 26 plain foods per 100 g as USDA FoodData Central gives them (description, FDC id where shown,
  energy and seven nutrients, the URL the values came from, notes where sources disagree), read through mirrors that
  name each entry: FoodData Central's own pages could not be read when the set was made.  A nutrient no source showed
  is `null`.  The everyday meals, planned anywhere, are sums of these.
- `sg-dishes.sources.json` — the Singapore/Malaysia dish pack: for each dish its serving and the nutrients a publication
  gave for it (HPB's values as quoted, with the HPB food code where shown; HealthHub; HealthXchange; magazines), the
  URL, and notes on disagreeing sources.  HPB's own database (focos.hpb.gov.sg) could not be reached.
- `medicinal-usda.sources.json` — 84 plain foods per 100 g for the medicinal dishes (the same shape, with potassium),
  read from web-search extracts of mirror pages naming each USDA record (no page could be fetched); conversions from a
  serving with its stated weight, second sources and disagreements are in each entry's notes.
- `make_medicinal.py` — writes `web/js/diet/medicinal-data.js`: the 61 medicinal dishes (药膳), their ingredients and
  per-serving nutrition from both USDA files, and their 128 classical quotations, each checked against its passage in
  `corpus/web` (the script stops otherwise).  `tests/test_diet.py` checks the module is what the script writes.
- `make_dishes.py` — writes `web/js/diet/dishes.js` from both and its own annotations (ids, Chinese names, kinds, slots,
  regions, allergens, pork/halal/vegetarian marks, tags, cooking and ordering tips).  `tests/test_diet.py` checks the
  module is what the script writes.

Collected through web search on 2026-11-01 (the medicinal-dish foods on 2026-11-04); every value is to be checked
against its database before production use.  See [docs/diet.md](../../docs/diet.md#the-data),
[ADR 0029](../../docs/adr/0029-diet-and-weight-for-singapore.md), [ADR 0030](../../docs/adr/0030-diet-and-weight-worldwide.md)
and [ADR 0031](../../docs/adr/0031-medicinal-dishes.md).
