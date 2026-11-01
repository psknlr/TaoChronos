"""Builds web/js/diet/dishes.js from the collected records (sg-dishes.sources.json: each dish's values as a publication
quoting HPB, HealthHub, HealthXchange or a magazine gave them, with its URL and notes; null where none was shown) and
the annotations below (ids, Chinese names, kinds, allergens, food rules, tags, ordering tips), plus plain foods from USDA
FoodData Central per 100 g scaled to the serving stated.  No value is estimated: a record without energy is left out.

    python data/diet/make_dishes.py            # writes web/js/diet/dishes.js (docs/diet.md, "The data")
"""
import json, sys, re
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
SOURCES = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "sg-dishes.sources.json"
TARGET = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE.parents[1] / "web" / "js" / "diet" / "dishes.js"
src = json.load(open(SOURCES, encoding="utf-8"))
by = {r["dish"]: r for r in src}

# dish (as in the JSON) -> annotation
# kind: main | side | snack | fruit | drink | treat ; slots ; times (servings ordered) ; allergens ; rules ; tags ; order
A = {}
def a(dish, id, zh, cuisine, kind, slots, allergens, *, tags=(), order="", pork=False, beef=False, halal=False, veg=False, vegan=False,
      times=1, serving=None, aka=()):
    assert dish in by, dish
    A[dish] = dict(id=id, zh=zh, cuisine=cuisine, kind=kind, slots=list(slots), allergens=sorted(allergens), tags=list(tags), order=order,
                   pork=pork, beef=beef, halal=halal, vegetarian=veg, vegan=vegan, times=times, serving=serving, aka=list(aka))

L, D, B, S = ["lunch", "dinner"], ["dinner"], ["breakfast"], ["snack"]
a("Steamed chicken rice", "chicken_rice_steamed", "海南鸡饭（白斩鸡）", "chinese", "main", L, {"soy", "wheat", "sesame"}, halal=True,
  tags=["steamed"], aka=["hainanese chicken rice", "ji fan"],
  order="Ask for plain white rice instead of oily chicken rice where the stall has it, or less rice; remove the skin; add a plate of blanched greens with the sauce on the side; go easy on dark soy and chilli.")
a("Roasted chicken rice", "chicken_rice_roasted", "烧鸡饭", "chinese", "main", L, {"soy", "wheat", "sesame"}, halal=True, tags=["roasted"],
  order="Steamed or soya sauce chicken is lighter; remove the skin, take less rice and add greens.")
a("Soya sauce chicken rice", "chicken_rice_soy_sauce", "酱油鸡饭", "chinese", "main", L, {"soy", "wheat", "sesame"}, tags=["braised"],
  order="Less rice, remove the skin, add blanched greens; skip the extra sauce poured over the rice.")
a("Char kway teow", "char_kway_teow", "炒粿条", "chinese", "main", L, {"egg", "crustacean", "mollusc", "fish", "soy", "wheat"}, pork=True,
  tags=["fried"], order="An occasional dish: ask for more bean sprouts and greens, less oil, no lard or Chinese sausage — or share a plate.")
a("Laksa (curry laksa)", "laksa", "叻沙", "peranakan", "main", L, {"crustacean", "mollusc", "fish", "egg", "soy", "tree_nut"},
  tags=["gravy", "coconut_milk", "spicy", "heaty"], aka=["curry laksa"],
  order="Ask for less gravy and more bean sprouts; leave most of the gravy, which holds most of the coconut fat and sodium.")
a("Fried Hokkien prawn mee", "hokkien_mee", "福建炒虾面", "chinese", "main", L, {"crustacean", "mollusc", "egg", "wheat", "soy"}, pork=True,
  tags=["fried"], aka=["hokkien mee"], order="Ask for less oil and more bean sprouts, no crispy lard; a small plate.")
a("Bak chor mee", "bak_chor_mee", "肉脞面", "chinese", "main", L, {"wheat", "egg", "soy", "fish"}, pork=True,
  tags=["noodles"], aka=["minced meat noodles"], order="Ask for less sauce and no crispy lard, more vegetables; or the soup version, leaving the soup.")
a("Wanton mee (dry)", "wanton_mee_dry", "云吞面（干）", "chinese", "main", L, {"wheat", "egg", "soy", "sesame", "crustacean"}, pork=True,
  tags=["noodles"], aka=["wonton noodles"], order="Ask for less sauce and lard and extra greens; or the soup version, leaving the soup.")
a("Fishball noodle soup", "fishball_noodle_soup", "鱼圆面（汤）", "chinese", "main", L, {"fish", "wheat", "egg", "soy"}, pork=True,
  tags=["soup"], aka=["fishball noodles"], order="Bee hoon in soup is the lighter choice; ask for extra fishballs or vegetables, no lard; don't finish the soup.")
a("Sliced fish bee hoon soup", "fish_soup_bee_hoon", "鱼片米粉汤", "chinese", "main", L, {"fish", "milk", "soy", "wheat"},
  tags=["soup", "vegetables"], aka=["fish soup", "sliced fish soup"],
  order="Ask for sliced (not fried) fish and no evaporated milk; add vegetables; leave most of the soup to cut the sodium.")
a("Yong tau foo (soup), mixed items, noodles not included", "yong_tau_foo_soup", "酿豆腐（汤）", "chinese", "main", L,
  {"soy", "fish", "wheat", "egg", "crustacean"}, tags=["soup", "vegetables"], aka=["ytf"],
  serving="1 bowl of mixed items in soup, noodles not included (number of pieces not stated)",
  order="Pick mostly vegetables, tofu and fish-paste items, few fried ones; clear soup, not laksa gravy; add a small portion of bee hoon or brown rice.")
a("Mee rebus", "mee_rebus", "马来卤面", "malay", "main", L, {"wheat", "egg", "crustacean", "soy"}, halal=True, tags=["gravy"],
  order="Ask for less gravy and more bean sprouts; the egg adds protein; leave the gravy.")
a("Mee goreng (Indian)", "mee_goreng", "印度炒面", "indian", "main", L, {"wheat", "egg", "soy", "crustacean", "mollusc"}, halal=True,
  tags=["fried", "spicy", "heaty"], order="Ask for less oil and more vegetables; with egg; a smaller portion if the plate is large.")
a("Chicken briyani (nasi briyani)", "briyani_chicken", "黄姜鸡饭（比尔亚尼）", "indian", "main", L, {"milk", "tree_nut"}, halal=True,
  tags=["rich", "spicy"], aka=["nasi briyani", "biryani"], order="Rich: ask for less rice, take the chicken without skin, add vegetables or dhal.")
a("Mutton murtabak", "murtabak_mutton", "羊肉煎饼（murtabak）", "indian", "main", L, {"wheat", "egg", "milk"}, halal=True,
  tags=["fried", "rich", "heaty"], order="Over 1,000 kcal a plate: share it, and skip the curry gravy.")
a("Roti prata, plain", "roti_prata_plain_2", "印度煎饼（原味，两片）", "indian", "main", B + L, {"wheat", "milk", "egg"}, halal=True, veg=True,
  tags=["fried"], times=2, serving="2 pieces", aka=["prata", "roti canai"],
  order="1–2 plain or egg prata, not cheese or extra margarine; dip lightly in dhal rather than curry.")
a("Egg prata (roti prata with egg)", "roti_prata_egg", "印度煎饼（加蛋，一片）", "indian", "main", B, {"wheat", "milk", "egg"}, halal=True, veg=True,
  tags=["fried"], aka=["roti telur"], order="Dhal rather than curry; one piece with fruit makes a breakfast.")
a("Thosai, plain", "thosai_plain", "印度薄饼（thosai）", "indian", "main", B, set(), halal=True, veg=True, vegan=True,
  tags=["vegetarian"], aka=["dosa", "dosai"], order="A lighter breakfast: take the dhal or sambar (lentils add protein); coconut chutney is richer.")
a("Chwee kueh", "chwee_kueh", "水粿", "chinese", "main", B, {"soy"}, pork=True, tags=["steamed"],
  serving="6 pieces", order="4 pieces rather than 6, with less chai poh (the preserved radish is salty and oily).")
a("Chee cheong fun, plain with sauce", "chee_cheong_fun", "猪肠粉", "chinese", "main", B, {"soy", "sesame", "wheat"}, tags=["steamed"],
  serving="2 rolls", order="Ask for less sauce; with prawns or char siew it has more protein.")
a("Nasi lemak", "nasi_lemak", "椰浆饭", "malay", "main", B + L, {"peanut", "fish", "crustacean", "egg"}, halal=True,
  tags=["coconut_milk", "fried", "spicy"], serving="1 plate: coconut rice with fried egg and ikan bilis (no chicken wing)",
  order="The egg and ikan bilis version, not the fried chicken wing; less sambal and rice; add cucumber.")
a("Mee siam", "mee_siam", "暹罗米粉", "malay", "main", B + L, {"crustacean", "soy", "egg", "peanut"}, halal=True, tags=["gravy", "spicy"],
  order="Ask for less gravy; the egg and tau pok add protein; skip extra sambal.")
a("Lontong (with sayur lodeh)", "lontong", "椰汁杂菜饭糕（lontong）", "malay", "main", B + L, {"egg", "soy", "crustacean"}, halal=True,
  tags=["coconut_milk", "gravy", "vegetables"], order="Large and rich: less gravy and fewer rice cakes, or share the plate.")
a("Economic fried bee hoon (plain)", "economic_bee_hoon", "经济炒米粉（原味）", "chinese", "main", B, {"soy", "wheat"},
  tags=["fried"], aka=["economy bee hoon"], order="Add an egg and vegetables for protein and fibre; skip luncheon meat and spring rolls.")
a("Fish porridge", "fish_porridge", "鱼片粥", "chinese", "main", B + D, {"fish", "soy", "sesame", "wheat"}, tags=["soup", "light"],
  order="Light: ask for no fried shallots or you tiao; add an egg or more fish for protein.")
a("Ban mian (soup)", "ban_mian_soup", "板面（汤）", "chinese", "main", L, {"wheat", "egg", "fish", "soy"}, pork=True,
  tags=["soup", "vegetables"], aka=["mee hoon kueh"], order="Ask for more vegetables; leave the soup — this bowl's sodium is above the day's limit.")
a("Duck rice, roasted", "duck_rice_roasted", "烧鸭饭", "chinese", "main", L, {"soy", "wheat", "sesame"}, tags=["roasted"],
  order="Remove the skin, take less rice and add greens.")
a("Duck rice, braised", "duck_rice_braised", "卤鸭饭", "chinese", "main", L, {"soy", "wheat", "egg"}, tags=["braised"],
  order="Remove the skin, ask for less braising sauce; tau kwa and egg add protein; add greens.")
a("Char siew rice", "char_siew_rice", "叉烧饭", "chinese", "main", L, {"soy", "wheat", "sesame"}, pork=True, tags=["roasted"],
  order="Less sauce and rice, add greens.")
a("Fried rice", "fried_rice", "炒饭", "chinese", "main", L, {"egg", "soy", "wheat", "crustacean"}, pork=True, tags=["fried"],
  order="Ask for less oil and add a side of vegetables; plain rice with dishes is lighter.")
a("Fried carrot cake, white", "carrot_cake_white", "炒萝卜糕（白）", "chinese", "main", B + L, {"egg", "soy"}, pork=True, tags=["fried"],
  aka=["chai tow kway"], order="White is lighter than black; ask for less oil and more egg; a small plate.")
a("Fried carrot cake, black (dark sauce)", "carrot_cake_black", "炒萝卜糕（黑）", "chinese", "main", B + L, {"egg", "soy", "wheat"}, pork=True,
  tags=["fried"], order="The white version is lighter; ask for less oil and sweet sauce.")
a("Popiah", "popiah", "薄饼", "peranakan", "snack", S + L, {"egg", "wheat", "peanut", "crustacean", "soy"}, pork=True, tags=["vegetables"],
  serving="1 roll", order="A lighter pick: ask for less sweet sauce.")
a("Rojak (Chinese style)", "rojak_chinese", "罗惹", "chinese", "treat", S, {"crustacean", "peanut", "soy", "wheat"}, tags=["fruit", "sweet"],
  order="Ask for less sauce and fewer you tiao; more fruit and vegetables.")
a("Indian rojak", "indian_rojak", "印度罗惹", "indian", "main", L, {"egg", "fish", "crustacean", "wheat", "soy", "peanut"}, halal=True,
  tags=["fried"], order="Choose boiled egg, potato, cucumber and tofu over battered fritters; dip lightly.")
a("Kway chap", "kway_chap", "粿汁", "chinese", "main", L, {"soy", "wheat", "egg"}, pork=True, tags=["braised"],
  order="Lean meat, tau kwa and egg rather than intestines and fatty pork; less braising sauce.")
a("Prawn noodle soup", "prawn_noodle_soup", "虾面（汤）", "chinese", "main", L, {"crustacean", "wheat", "egg", "soy"}, pork=True, tags=["soup"],
  aka=["hae mee"], order="Bee hoon in soup, no fried lard; leave the soup.")
a("Lor mee", "lor_mee", "卤面", "chinese", "main", L, {"wheat", "egg", "soy", "fish"}, pork=True, tags=["gravy"],
  order="Thick, starchy gravy: ask for less of it and add vegetables.")
a("Sambal kangkong", "sambal_kangkong", "参巴蕹菜", "malay", "side", L, {"crustacean"}, tags=["vegetables", "spicy", "fried"],
  order="Over 2,000 mg sodium and 30 g fat in this plate: choose blanched or garlic-fried greens, or share it.")
a("Chapati", "chapati", "印度薄饼（chapati）", "indian", "side", B + L, {"wheat", "milk"}, halal=True, veg=True, tags=["wholegrain"],
  serving="1 piece", order="Eaten with dhal and vegetables: 2 pieces make a meal's grains.")
# drinks
for dish, id, zh, al, order in [
    ("Kopi (coffee with condensed milk)", "kopi", "咖啡（炼乳加糖）", {"milk"}, "Kopi siew dai (less sweet) or kopi-O kosong (no sugar) instead."),
    ("Kopi-O (coffee with sugar, no milk)", "kopi_o", "咖啡乌（加糖）", set(), "Kopi-O siew dai or kosong cuts the sugar."),
    ("Kopi-C (coffee with evaporated milk and sugar)", "kopi_c", "咖啡C（淡奶加糖）", {"milk"}, "Kopi-C kosong (no sugar) or siew dai."),
    ("Kopi-O kosong (black coffee, no sugar)", "kopi_o_kosong", "咖啡乌（无糖）", set(), "The lightest kopi."),
    ("Teh (tea with condensed milk)", "teh", "茶（炼乳加糖）", {"milk"}, "Teh siew dai or teh-O kosong instead."),
    ("Teh-C (tea with evaporated milk and sugar)", "teh_c", "茶C（淡奶加糖）", {"milk"}, "Teh-C kosong (no sugar) or siew dai."),
    ("Teh tarik", "teh_tarik", "拉茶", {"milk"}, "An occasional drink: ask for less sweet."),
    ("Bubble tea (milk tea with tapioca pearls)", "bubble_tea", "珍珠奶茶", {"milk"}, "Choose 0–25% sugar, skip the pearls or take a small cup; an occasional treat."),
    ("Sugarcane juice", "sugarcane_juice", "甘蔗汁", set(), "Naturally sweet: a small cup, not every day."),
]:
    a(dish, id, zh, "drink", "drink", ["drink"], al, order=order, halal=True, veg="milk" not in al or True, vegan="milk" not in al,
      tags=["drink"] + (["sweet"] if id not in ("kopi_o_kosong",) else []))
# treats and festive foods
for dish, id, zh, cuisine, al, tags, order, pork, halal in [
    ("Chendol", "chendol", "煎蕊", "malay", set(), ["dessert", "coconut_milk", "iced", "sweet"], "Share a bowl; ask for less gula melaka.", False, True),
    ("Ice kacang", "ice_kacang", "红豆冰（ice kacang）", "malay", {"milk", "peanut"}, ["dessert", "iced", "sweet"], "Ask for less syrup and evaporated milk; share it.", False, True),
    ("Kueh lapis (layer cake)", "kueh_lapis", "千层糕", "peranakan", {"egg", "milk", "wheat"}, ["festive", "sweet"], "A thin slice, savoured.", False, False),
    ("Pineapple tart", "pineapple_tart", "黄梨挞", "peranakan", {"wheat", "milk", "egg"}, ["festive", "sweet"], "One or two, not the jar.", False, False),
    ("Bak kwa", "bak_kwa", "肉干", "chinese", {"soy", "wheat"}, ["festive", "grilled", "heaty"], "A slice is a meal's worth of energy: share one, or choose the coin-sized pieces.", True, False),
    ("Baked mooncake, lotus seed paste with single yolk", "mooncake_lotus_yolk", "莲蓉单黄月饼", "chinese", {"wheat", "egg"}, ["festive", "sweet"], "A quarter is a portion; share the rest.", False, False),
    ("Durian", "durian", "榴莲", "fruit", set(), ["fruit", "heaty"], "Rich for a fruit: 2–3 seeds is a portion.", False, True),
    ("Curry puff (chicken)", "curry_puff", "咖喱角", "malay", {"wheat", "egg", "milk"}, ["fried", "snack"], "An occasional snack: baked versions are lighter.", False, True),
    ("Murukku", "murukku", "印度炸饼（murukku）", "indian", {"sesame", "milk"}, ["festive", "fried"], "A small handful, not the tin.", False, True),
]:
    a(dish, id, zh, cuisine, "treat", ["snack"], al, tags=tags, order=order, pork=pork, halal=halal, veg=not pork and id not in ("curry_puff",),
      vegan=id in ("durian", "chendol"))

def publisher(url):
    host = urlparse(url).netloc.replace("www.", "")
    return {"nutrikaki-landing.pages.dev": "Nutri Kaki", "healthhub.sg": "HealthHub (HPB)", "danielfooddiary.com": "Daniel Food Diary",
            "mothership.sg": "Mothership", "healthxchange.sg": "HealthXchange (SingHealth)", "hungrygowhere.com": "HungryGoWhere",
            "womensweekly.com.sg": "Women's Weekly", "herworld.com": "Her World", "homeanddecor.com.sg": "Home & Decor",
            "thesmartlocal.com": "TheSmartLocal", "ladyironchef.com": "Lady Iron Chef", "moh.gov.my": "Ministry of Health Malaysia"}.get(host, host)

NUT = [("kcal", "energy_kcal"), ("protein_g", "protein_g"), ("fat_g", "fat_g"), ("sat_fat_g", "sat_fat_g"), ("carb_g", "carb_g"),
       ("fibre_g", "fibre_g"), ("sugar_g", "sugar_g"), ("sodium_mg", "sodium_mg")]

out = []
for dish, ann in A.items():
    r = by[dish]
    if r.get("energy_kcal") is None:
        continue
    t = ann["times"]
    rec = {"id": ann["id"], "name": dish if t == 1 else f"{dish} ×{t}", "zh": ann["zh"]}
    if ann["aka"]: rec["aka"] = ann["aka"]
    rec.update(cuisine=ann["cuisine"], kind=ann["kind"], slots=ann["slots"])
    serving = ann["serving"] or r.get("serving") or "1 serving"
    if r.get("serving_g") and t == 1: serving += f" ({r['serving_g']} g)" if "g)" not in serving else ""
    rec["serving"] = serving
    for k, j in NUT:
        v = r.get(j)
        rec[k] = None if v is None else round(v * t, 1) if isinstance(v, float) and not float(v * t).is_integer() else (int(v * t) if v is not None else None)
    rec.update(allergens=ann["allergens"], pork=ann["pork"], beef=ann["beef"], halal=ann["halal"], vegetarian=ann["vegetarian"], vegan=ann["vegan"],
               tags=ann["tags"], order=ann["order"])
    kind = r.get("source_kind")
    rec["source"] = "hpb_coded" if r.get("hpb_code") else {"HPB/HealthHub": "healthhub", "secondary-quoting-HPB": "hpb_secondary"}.get(kind, "other")
    if r.get("hpb_code"): rec["hpb_code"] = r["hpb_code"]
    rec["source_url"] = r["source_url"]
    rec["publisher"] = publisher(r["source_url"])
    if t != 1: rec["per_piece_kcal"] = r["energy_kcal"]
    note = r.get("notes") or ""
    m = re.search(r"DISAGREEMENT[^.]*?(?:gives|says|lists)[^.]*\.", note)
    if m: rec["other_figure"] = m.group(0).replace("DISAGREEMENT: ", "").replace("DISAGREEMENTS: ", "")[:220]
    out.append(rec)

# plain foods: USDA FoodData Central (SR Legacy) per 100 g, scaled to the serving shown
U = {  # name: (kcal, protein, fat, carb, fibre) per 100 g, the USDA entry
    "pak_choi": ((12, 1.56, 0.16, 1.78, None), "Cabbage, chinese (pak-choi), cooked, boiled, drained, without salt"),
    "egg": ((155, 12.6, 10.6, 1.1, None), "Egg, whole, cooked, hard-boiled (FDC 173424)"),
    "tofu": ((144, 17.3, 8.7, 2.8, None), "Tofu, raw, firm, prepared with calcium sulfate (FDC 172475)"),
    "brown_rice": ((123, 2.7, 1.0, 25.6, 1.6), "Rice, brown, long-grain, cooked (FDC 169704)"),
    "banana": ((89, 1.1, None, None, 2.6), "Bananas, raw"),
    "apple": ((52, 0.3, 0.2, 13.8, 2.4), "Apples, raw, with skin (FDC 171688)"),
    "watermelon": ((30, 0.6, None, 7.5, 0.4), "Watermelon, raw (FDC 167765)"),
}
def scaled(parts):
    tot = {}
    for k, idx in [("kcal", 0), ("protein_g", 1), ("fat_g", 2), ("carb_g", 3), ("fibre_g", 4)]:
        vals = [U[n][0][idx] for n, g in parts]
        tot[k] = None if any(v is None for v in vals) else round(sum(U[n][0][idx] * g / 100 for n, g in parts), 1)
        if k == "kcal" and tot[k] is not None: tot[k] = round(tot[k])
    tot.update(sat_fat_g=None, sugar_g=None, sodium_mg=None)
    return tot
def plain(id, name, zh, kind, slots, parts, serving, allergens, tags, order, veg=True, vegan=True, cuisine="basic"):
    rec = {"id": id, "name": name, "zh": zh, "cuisine": cuisine, "kind": kind, "slots": slots, "serving": serving}
    rec.update(scaled(parts))
    rec.update(allergens=sorted(allergens), pork=False, beef=False, halal=True, vegetarian=veg, vegan=vegan, tags=tags, order=order,
               source="usda", usda=[f"{U[n][1]}: {g} g" for n, g in parts])
    out.append(rec)

plain("side_vegetables_blanched", "Blanched greens (side)", "白灼青菜", "side", ["lunch", "dinner"], [("pak_choi", 150)],
      "1 side plate (150 g), values without sauce", {"mollusc", "soy", "wheat"}, ["vegetables", "side"],
      "Ask for the oyster sauce on the side or none, and no fried shallot oil: the values are for the greens alone.")
plain("home_tofu_plate", "Home plate: brown rice, tofu and greens", "糙米豆腐青菜（家常）", "main", ["lunch", "dinner"],
      [("brown_rice", 150), ("tofu", 150), ("pak_choi", 150)], "brown rice 150 g, firm tofu 150 g, greens 150 g; oil and sauce not included",
      {"soy"}, ["home", "wholegrain", "vegetables", "steamed", "vegetarian"],
      "Steam or braise the tofu with little sauce; each teaspoon of oil (about 4.5 g) adds about 40 kcal.")
plain("home_egg_plate", "Home plate: brown rice, eggs and greens", "糙米鸡蛋青菜（家常）", "main", ["lunch", "dinner"],
      [("brown_rice", 150), ("egg", 100), ("pak_choi", 150)], "brown rice 150 g, 2 boiled eggs (100 g), greens 150 g; oil and sauce not included",
      {"egg"}, ["home", "wholegrain", "vegetables", "vegetarian"], "Boiled or steamed eggs; each teaspoon of oil adds about 40 kcal.", vegan=False)
plain("home_egg_banana_breakfast", "Breakfast: 2 boiled eggs and a banana", "早餐：两个水煮蛋和香蕉", "main", ["breakfast"],
      [("egg", 100), ("banana", 100)], "2 boiled eggs (100 g) and 1 small banana (100 g)", {"egg"}, ["home", "light", "vegetarian"],
      "Quick: boil eggs ahead for the week.", vegan=False)
plain("egg_boiled", "Boiled egg", "水煮蛋", "snack", ["snack", "breakfast"], [("egg", 50)], "1 egg (50 g)", {"egg"}, ["snack"],
      "Soft-boiled kopitiam eggs are the same egg: go easy on the soy sauce.", vegan=False)
plain("fruit_banana", "Banana", "香蕉", "fruit", ["snack"], [("banana", 100)], "1 small banana (100 g)", set(), ["fruit"], "")
plain("fruit_apple", "Apple", "苹果", "fruit", ["snack"], [("apple", 130)], "1 small apple (130 g, 1 serving)", set(), ["fruit"], "")
plain("fruit_watermelon", "Watermelon", "西瓜", "fruit", ["snack"], [("watermelon", 130)], "1 wedge (130 g, 1 serving)", set(), ["fruit"], "")
for r in out:
    if not r["order"]: del r["order"]

head = '''// Singapore dishes for the diet plans, generated by data/diet/make_dishes.py (docs/diet.md, "The data"): each a
// typical serving as HPB's Energy & Nutrient Composition of Food gives it — read through the publications that quote
// it, since HPB's database could not be reached when the set was made — or, marked so, as SingHealth's HealthXchange or
// a magazine gives it; the plain foods (rice, tofu, egg, greens, fruit) from USDA FoodData Central per 100 g, scaled to
// the serving shown.  A value no source showed is null, and stays null: the planner reports it missing, never fills it
// in.  The allergens, food rules (pork, halal, vegetarian), tags and ordering tips are this project's, from the dishes'
// usual recipes — recipes differ by stall, so a plan tells a visitor with an allergy to ask.  `other_figure`: another
// source's value.  Do not edit by hand: edit the sources or the annotations and run the script again.

'''
meta = {"id": "sg-dishes", "version": "2026-11-01", "status": "secondary_source_unverified",
        "note": "values as published for HPB's analyses, read through secondary sources (3 with HPB food codes); some from HealthXchange (SingHealth) or magazines; plain foods from USDA FoodData Central — verify against HPB's database (focos.hpb.gov.sg) before production use"}
js = head + "export const DATASET = " + json.dumps(meta, ensure_ascii=False, indent=2) + ";\n\n"
js += "export const DISHES = [\n" + ",\n".join("  " + json.dumps(r, ensure_ascii=False) for r in out) + ",\n];\n"
open(TARGET, "w", encoding="utf-8").write(js)
print(len(out), "records;", sum(1 for r in out if r["kind"] == "main"), "mains")
