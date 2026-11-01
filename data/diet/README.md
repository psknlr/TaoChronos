# data/diet — the Singapore dish data of 饮食与体重管理

- `sg-dishes.sources.json` — the records collected for each dish: its serving and the nutrients a publication gave for
  it (HPB's values as quoted, with the HPB food code where shown; HealthHub; HealthXchange; magazines), the URL, and
  notes on disagreeing sources.  A nutrient no source showed is `null`.  Collected through web search on 2026-11-01:
  HPB's own database (focos.hpb.gov.sg) could not be reached, so every value is to be checked against it before
  production use.
- `make_dishes.py` — writes `web/js/diet/dishes.js` from those records and its own annotations (ids, Chinese names,
  kinds, slots, allergens, pork/halal/vegetarian marks, tags, ordering tips) and the plain foods from USDA FoodData
  Central.  `tests/test_diet.py` checks the module is what the script writes.

See [docs/diet.md](../../docs/diet.md#the-data) and [ADR 0029](../../docs/adr/0029-diet-and-weight-for-singapore.md).
