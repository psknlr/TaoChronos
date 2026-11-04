"""Builds web/js/diet/medicinal-data.js: the medicinal dishes (药膳) of 饮食与体重管理, their ingredients, the per-serving
nutrition of each, and the classical passages each rests on.

- usda.sources.json and medicinal-usda.sources.json: plain foods per 100 g as USDA FoodData Central gives them (via
  mirrors naming the entry).  A dish's nutrient is the sum over the ingredients that have it; an ingredient with no
  record (薏苡仁, 陈皮, 菊花, 当归, 黄芪, 山楂, 韭菜) is listed in `not_counted` and the totals are
  marked partial — never estimated.
- corpus/web/passages.jsonl.gz and books.json: every quotation below must occur, character for character, in the
  passage it names; the build stops otherwise.  A quotation's book title and chapter are taken from the corpus.

The dishes, their roles, natures, seasons, times, constitutions and cautions are this project's annotations of what the
quoted texts say (docs/diet.md, "Medicinal dishes"; ADR 0031).  Only foods and substances on China's list of
substances that are both food and traditional medicine (按照传统既是食品又是中药材的物质目录) are used, in recipe amounts.

    python data/diet/make_medicinal.py            # writes web/js/diet/medicinal-data.js
"""
import gzip, json, math, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TARGET = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "web" / "js" / "diet" / "medicinal-data.js"
CORPUS = ROOT / "corpus" / "web"
NUTRIENTS = ["energy_kcal", "protein_g", "fat_g", "sat_fat_g", "carb_g", "fibre_g", "sugar_g", "sodium_mg", "potassium_mg"]

usda = {}
for name in ("usda.sources.json", "medicinal-usda.sources.json"):
    for r in json.load(open(HERE / name, encoding="utf-8")):
        usda[r["key"]] = r

# ------------------------------------------------------------------ ingredients
# key -> (中文, English, USDA key or None, homology: the list's year for a listed substance, "food" for an everyday food,
#         herb: not an everyday food — left out when a visitor's medicines are not known to be safe with it)
FOOD = {}
def food(key, zh, en, usda_key, homology="food", herb=False, note=""):
    assert usda_key is None or usda_key in usda, (key, usda_key)
    FOOD[key] = dict(zh=zh, en=en, usda=usda_key, homology=homology, herb=herb, note=note)

food("rice", "粳米（生）", "white rice, raw", "rice_white_raw")
food("millet", "小米（粟米，生）", "millet, raw", "millet_raw")
food("glutinous_rice", "糯米（生）", "glutinous rice, raw", "glutinous_rice_raw")
food("yam", "鲜山药", "Chinese yam, fresh", "yam_raw", homology="2002",
     note="USDA's 'Yam, raw' (Dioscorea species) stands for Chinese yam (Dioscorea polystachya).")
food("lotus_seed", "莲子（干）", "lotus seeds, dried", "lotus_seeds_dried", homology="2002")
food("jujube", "红枣（干）", "jujube (red date), dried", "jujube_dried", homology="2002", note="On the list as 枣（大枣、酸枣、黑枣）.")
food("goji", "枸杞子", "goji berries, dried", "goji_dried", homology="2002", herb=True)
food("coix", "薏苡仁", "Job's tears (coix seed)", None, homology="2002", note="No USDA record.")
food("adzuki", "赤小豆", "adzuki beans, raw", "adzuki_raw", homology="2002",
     note="赤小豆 is strictly Vigna umbellata; the adzuki bean (Vigna angularis) is commonly used for it and stands for it here.")
food("mung", "绿豆（带皮）", "mung beans, raw, with skins", "mung_raw")
food("waxgourd", "冬瓜", "winter melon (wax gourd)", "waxgourd_raw")
food("pear", "梨", "pear", "pear_raw")
food("lotus_root", "莲藕", "lotus root", "lotus_root_raw")
food("daikon", "白萝卜", "daikon radish", "daikon_raw")
food("carrot", "胡萝卜", "carrot", "carrots", note="USDA's boiled carrots stand for carrots cooked in congee.")
food("lamb", "羊肉（瘦）", "lamb, lean", "lamb_leg_raw")
food("chicken", "鸡腿肉（去皮）", "chicken thigh, skinless", "chicken_thigh_raw")
food("pork_ribs", "猪排骨", "pork spareribs", "pork_ribs_raw")
food("ginger", "生姜", "fresh ginger", "ginger_raw", homology="2002", note="On the list as 姜（生姜、干姜）.")
food("sesame", "黑芝麻", "black sesame seeds", "sesame_seeds", homology="2002",
     note="USDA's whole dried sesame seeds stand for black sesame.")
food("walnut", "核桃仁", "walnuts", "walnuts")
food("chestnut", "板栗", "Chinese chestnuts", "chestnuts_chinese_raw")
food("milk", "全脂牛奶", "whole milk", "milk_whole")
food("shiitake", "干香菇", "dried shiitake", "shiitake_dried")
food("sugar", "冰糖（可不放）", "rock sugar (optional)", "sugar_white", note="USDA's granulated sugar stands for rock sugar.")
food("salt", "盐", "salt", "salt_table")
food("egg", "鸡蛋", "egg", "egg", note="USDA's hard-boiled egg stands for egg cooked in the dish.")
food("oil", "食用油", "cooking oil", "olive_oil", note="USDA's olive oil stands for a cooking oil.")
food("chives", "韭菜", "Chinese chives (garlic chives)", None, note="No USDA record for Allium tuberosum.")
food("chenpi", "陈皮", "dried tangerine peel", None, homology="2002", herb=True, note="On the list as 橘皮. No USDA record.")
food("chrysanthemum", "菊花（干）", "dried chrysanthemum flowers", None, homology="2002", herb=True, note="No USDA record.")
food("hawthorn", "山楂（干片）", "dried hawthorn slices", None, homology="2002", herb=True, note="No USDA record.")
food("danggui", "当归（作调料）", "dang gui (Angelica sinensis root), as a seasoning", None, homology="2019", herb=True,
     note="Added to the list in 2019 (NHC/SAMR announcement 2019 No. 8) for use only as a spice or seasoning (仅作为香辛料和调味品使用). No USDA record.")
food("huangqi", "黄芪", "astragalus root", None, homology="2023", herb=True,
     note="Added to the list in 2023 (announcement 2023 No. 9); the NHC's explanation advises moderate amounts eaten in traditional ways and does not recommend it for pregnant or breastfeeding women or infants. No USDA record.")

# ------------------------------------------------------------------ the classical passages
books = {b["id"]: b for b in json.load(open(CORPUS / "books.json", encoding="utf-8"))}
passages = {}
with gzip.open(CORPUS / "passages.jsonl.gz", "rt", encoding="utf-8") as f:
    for line in f:
        p = json.loads(line)
        passages[p["id"]] = p

QUOTES = {}
def quote(qid, pid, text, gloss, kind="ingredient"):
    """`text` must occur in passage `pid` exactly; `gloss` says in English what it says (for the model and the page)."""
    p = passages.get(pid)
    assert p, f"{qid}: no passage {pid} in the corpus pack"
    assert text in p["text"], f"{qid}: {text!r} is not in {pid}"
    b = books[p["book_id"]]
    QUOTES[qid] = dict(passage_id=pid, work=b["data"]["title"], dynasty=b["data"].get("dynasty") or "",
                       chapter=(p.get("locator") or {}).get("chapter") or "", text=text, gloss=gloss, kind=kind)

# principles: what food care is for, the seasons, the times of the day
quote("food_first", "qianjin_yaofang.079.05698", "夫爲醫者當須先洞曉病源知其所犯以食治之食療不愈然後命藥",
      "A physician should first understand the illness and treat it with food; only when food fails, prescribe medicine.", "principle")
quote("food_nourishes", "cm_suwen_gucongde.03439", "穀肉果菜，食養盡之，旡使過之傷其正也",
      "Grains, meat, fruit and vegetables complete the nourishing — without excess, which harms what is right.", "principle")
quote("food_settles", "qianjin_yaofang.079.05698", "食能排邪而安臟腑悦神爽志以資血氣",
      "Food can expel what is harmful and settle the organs, lift the spirit and support qi and blood.", "principle")
quote("seasons", "cm_suwen_gucongde.00329", "所以聖人春夏養陽，秋冬養隂以從其根",
      "So the sages nourished yang in spring and summer and yin in autumn and winter, following the root.", "season")
quote("spring_taste", "shouqin_yanglao.001.00044", "當春之時其飲食之味宜减酸益甘以飬脾氣",
      "In spring, eat less sour and more sweet, to nourish the spleen.", "season")
quote("summer_food", "shouqin_yanglao.001.00054", "飲食温軟不令太飽",
      "In summer, food warm and soft, never too full.", "season")
quote("summer_cold_greasy", "shouqin_yanglao.001.00054", "生冷肥膩尤宜减之",
      "In summer, raw, cold, fatty and greasy foods especially should be cut down.", "season")
quote("no_full_sleep", "qianjin_yaofang.081.05828", "飽食即臥乃生百病",
      "Lying down straight after a full meal breeds a hundred illnesses.", "time")
quote("no_night_ginger", "cm_jingui_wuqian.01113", "夜食諸薑、蒜、蔥等，傷人心。",
      "Eating ginger, garlic, spring onion and the like at night harms the heart.", "time")
quote("ginger_morning", "jc_c028.00074", "蓋晚食蘿卜。則消酒食之滯。清晨食薑。能開胃御風。敵寒解穢。",
      "Radish in the evening clears what wine and food leave stuck; ginger in the early morning opens the stomach and wards off wind and cold.", "time")
# dishes and ingredients
quote("shanyao_zhou", "jc_c028.00347", "甚補下元。治脾瀉。淮山藥末四五兩。配米煮食。",
      "Chinese-yam congee: strongly tonifies the lower origin and treats spleen diarrhoea; Chinese yam cooked with rice.", "dish")
quote("shuyu", "ws_36bca7b992.00042", "主治傷中，補虛羸，除寒熱邪氣，補中益氣力，長肌肉。",
      "Chinese yam: for damage to the middle; supplements weakness and emaciation, supplements the middle, adds strength, builds flesh.")
quote("shanyao_cool", "jc_c028.00150", "涼而補肺。久食強陰。",
      "Chinese yam is cool and supplements the lung; eaten long, it strengthens yin (a later text calling it cool where the 神农本草经 calls it slightly warm).")
quote("sumi_zhou", "jc_c028.00343", "煮粥空心食之。極和養胃氣。",
      "Millet congee, eaten on an empty stomach, most gently nourishes the stomach qi.", "dish")
quote("lianzi", "jc_c028.00095", "熟者佳。宜去心。治泄精補脾。久食輕身耐老。",
      "Lotus seeds: better cooked, with the germ removed; supplement the spleen; eaten long, keep the body light.")
quote("lianzi_raw", "jc_c028.00095", "生者動氣。脹人。傷脾胃。",
      "Raw lotus seeds stir the qi, bloat and harm the spleen and stomach.", "caution")
quote("oushi", "ws_36bca7b992.00106", "主補中養神，益氣力",
      "Lotus seed and stem: supplement the middle, nourish the spirit, add strength.")
quote("yiyi_zhou", "jc_c028.00265", "去濕氣腫脹。功勝諸藥。用苡仁淘淨。對配白米煮粥食之。",
      "Coix congee clears damp swelling — 'better than any drug', the text says; coix and white rice cooked together.", "dish")
quote("yiyi", "ws_36bca7b992.00055", "主治筋急拘攣不可屈伸，風濕痹，下氣。久服輕身益氣。",
      "Coix seed: for cramped sinews and wind-damp painful obstruction; eaten long, lightens the body and adds qi.")
quote("lvdou_zhou", "jc_c028.00257", "綠豆淘淨熟煮入米同煮食。最解暑。",
      "Mung-bean congee: mung beans cooked, then with rice; best against summer heat.", "dish")
quote("lvdou", "jc_c028.00025", "清熱解毒。不可去皮。去皮壅氣。",
      "Mung beans clear heat and toxins; keep the skins on, which the text says prevents stagnation.")
quote("lvdou_medicine", "jc_c028.00025", "服藥人不可食。令藥無力。",
      "Those taking medicine should not eat them: they weaken the medicine (a historical belief).", "caution")
quote("chixiaodou", "ws_36bca7b992.00222", "赤小豆，主下水，排癰腫膿血。",
      "Adzuki (rice) bean: drains water, expels pus from swellings.")
quote("chixiaodou_caution", "jc_c028.00027", "解毒利小便。能逐津液。久食虛人。",
      "It clears toxins and promotes urination, drives out fluids; eaten long, it weakens a person.", "caution")
quote("gouqi_zhou", "jc_c028.00370", "用甘州枸杞子一合。米三合。煮粥食。",
      "Goji congee: one measure of Ganzhou goji to three of rice, cooked as congee.", "dish")
quote("gouqi", "ws_36bca7b992.00101", "久服堅筋骨，輕身耐老。",
      "Goji (the plant, in this oldest text, which does not yet separate fruit and root bark): taken long, firms sinews and bones, lightens the body.")
quote("hutao_zhou", "jc_c028.00373", "治陽虛腰痛。及石淋五痔。用胡桃肉煮粥食。",
      "Walnut congee: for yang-deficiency low-back pain; walnuts cooked into congee.", "dish")
quote("hutao_caution", "jc_c049.00064", "不可多食，動痰飲，令人惡心",
      "Walnuts: not to be eaten in quantity; they stir phlegm and cause nausea.", "caution")
quote("niuru", "jc_c049.00166", "牛乳汁：味甘、微寒、無毒。補虛羸、止渴。",
      "Cow's milk: sweet, slightly cold; supplements weakness and emaciation, stops thirst.")
quote("niuru_zhou", "jc_o031.01038", "如常粥內加入牛乳和勻食。",
      "Milk congee: stir milk into ordinary congee.", "dish")
quote("huluobo_zhou", "jc_o031.00946", "寬中下氣",
      "Carrot congee: eases the middle and sends qi down.", "dish")
quote("danggui_yangrou", "cm_jingui_wuqian.00351", "寒疝，腹中痛及脅痛裏急者，當歸生薑羊肉湯主之。",
      "Where the text first appears it is a prescription: for cold colic with abdominal and flank pain, Dang gui, Ginger and Mutton Decoction governs.", "dish")
quote("yangrou", "jc_c049.00177", "肉：味苦、甘，大熱、無毒。主暖中止痛",
      "Mutton: bitter and sweet, very hot; warms the middle and stops pain.")
quote("yangrou_summer", "jc_c028.00186", "夏月不可食。",
      "Mutton is not to be eaten in the summer months.", "season")
quote("lizi", "jc_c049.00044", "栗子：味鹹、溫、無毒。益氣，濃腸胃，補腎氣，令人耐飢。",
      "Chestnut: salty, warm; adds qi, thickens the intestines and stomach, supplements kidney qi, keeps hunger away.")
quote("lizi_caution", "jc_c028.00127", "生食難消化。熟食滯氣。",
      "Raw chestnuts are hard to digest; cooked ones make the qi sluggish (so, a few).", "caution")
quote("ji", "jc_c049.00205", "補益五臟，絕傷五勞，益氣力。",
      "Hen (yellow): supplements the five organs, mends exhaustion, adds strength.")
quote("donggua", "jc_c049.00069", "白冬瓜：味甘、微寒、無毒。除少腹水脹，利小便、止消渴。",
      "Winter melon: sweet, slightly cold; relieves water bloating of the lower belly, promotes urination, stops thirst.")
quote("donggua_caution", "jc_c028.00079", "霜降後。方可食。早食傷胃反病。及陰虛人不可食。",
      "A later text: eat it only after 霜降 (late October), not earlier, and not if yin-deficient — the references disagree on its season.", "caution")
quote("luobo", "jc_c028.00064", "消痰下氣。利膈寬中。多食耗脾氣。",
      "Daikon: clears phlegm, sends qi down, eases the chest and middle; too much drains spleen qi.")
quote("ou", "jc_c028.00098", "熟補五臟。實下焦。",
      "Lotus root, cooked, supplements the five organs and firms the lower burner.")
quote("huangqi", "ws_36bca7b992.00078", "黃芪　味甘微溫。主治癰疽久敗瘡，排膿止痛，大風癩疾，五痔鼠瘺，補虛，小兒百病。",
      "Astragalus: sweet, slightly warm; the oldest text lists it for sores and fistulas, and 'supplements weakness'.")
quote("jiu_season", "jc_c049.00091", "五月勿食韭，損人滋味，令人乏氣力。二月、三月宜食韭，大益人心。",
      "Chinese chives: not in the fifth (lunar) month; in the second and third months they greatly benefit the heart.", "season")
quote("jiu_caution", "jc_c028.00054", "多食助陽損神昏目。",
      "Too many chives assist yang, harm the spirit and dim the eyes.", "caution")
quote("jiu_blood", "jc_o031.01011", "以其散氣行血。",
      "Chives disperse qi and move the blood.")
quote("dazao", "ws_36bca7b992.00105", "主治心腹邪氣，安中養脾",
      "Jujube: settles the middle and nourishes the spleen.")
quote("jiangju", "jc_c028.00359", "用生薑二兩。陳皮一兩。空心煎湯服。極開脾胃。",
      "Ginger and tangerine-peel decoction, taken on an empty stomach, opens the spleen and stomach.", "dish")
quote("jupi", "jc_c000.00445", "主胸中瘕熱逆氣，利水谷。久服，去臭、下氣、通神。",
      "Tangerine peel: for counterflow qi in the chest, frees food and water; taken long, sends qi down.")
quote("juhua", "ws_36bca7b992.00043", "久服，利血氣、輕身、耐老延年。",
      "Chrysanthemum: taken long, benefits blood and qi, lightens the body, wards off age.")
quote("li", "jc_c028.00122", "治上焦熱。醒酒消痰。",
      "Pear: treats heat of the upper burner, sobers, clears phlegm.")
quote("li_caution", "jc_c028.00122", "病患虛人多食。泄瀉浮腫。",
      "The sick and the weak who eat many get diarrhoea and swelling.", "caution")
quote("ligao", "jc_c028.00294", "清火滋陰。",
      "Pear syrup: clears fire and enriches yin.")
quote("zhima", "ws_36bca7b992.00112", "主治傷中虛羸，補五內，益氣力，長肌肉，填腦髓。久服輕身不老。",
      "Sesame: for damage to the middle and weakness; supplements the five internal organs, adds strength, builds flesh, fills the marrow.")
quote("zhima_black", "jc_c028.00019", "黑芝麻炒食。不生風疾。",
      "Black sesame, toasted and eaten, keeps wind illnesses away.")
quote("shanzha", "jc_g002.00108", "傷肉食宜麥芽山楂。",
      "For indigestion from meat, malt and hawthorn.")

# ------------------------------------------------------------------ the dishes
DISHES = []
def dish(id, zh, en, kind, parts, *, nature, suits, slots, method_zh, method_en, evidence, avoid=(), seasons=(), not_seasons=(),
         not_slots=(), cautions=(), serving="1 bowl", allergens=(), meat=None, pork=False, purine_broth=False, notes=()):
    for q in evidence: assert q in QUOTES, (id, q)
    for a in avoid: assert a[1] in QUOTES or a[1] is None, (id, a)
    items, totals, missing = [], {n: 0.0 for n in NUTRIENTS}, set()
    not_counted = []
    for key, grams in parts:
        f = FOOD[key]
        items.append(dict(food=key, zh=f["zh"], en=f["en"], g=grams, homology=f["homology"], herb=f["herb"]))
        rec = usda.get(f["usda"]) if f["usda"] else None
        if not rec:
            not_counted.append(f"{f['en']} {grams} g")
            continue
        for n in NUTRIENTS:
            v = rec["per_100g"].get(n)
            if v is None: missing.add(n)
            else: totals[n] += v * grams / 100
    nut = {}
    for n in NUTRIENTS:
        if n in missing: nut[n] = None
        else: nut[n] = round(totals[n]) if n in ("energy_kcal", "sodium_mg", "potassium_mg") else round(totals[n], 1)
    DISHES.append(dict(
        id=id, zh=zh, en=en, kind=kind, serving=serving, nature=nature, suits=list(suits),
        avoid=[dict(type=t, quote=q, why=w) for t, q, w in avoid], seasons=list(seasons), not_seasons=list(not_seasons),
        slots=list(slots), not_slots=list(not_slots), ingredients=items, method_zh=method_zh, method_en=method_en,
        evidence=list(evidence), cautions=list(cautions), allergens=sorted(allergens), meat=meat, pork=pork,
        purine_broth=purine_broth, herbs=sorted({i["food"] for i in items if i["herb"]}),
        nutrition=nut, not_counted=not_counted, notes=list(notes)))

B, L, A, D = "breakfast", "lunch", "afternoon", "dinner"
dish("shanyao_zhou", "山药粥", "Chinese-yam congee", "congee", [("rice", 40), ("yam", 100)],
     nature="neutral", suits=["qixu", "pinghe", "tebing"], slots=[B, D],
     method_zh="粳米淘净加水煮开，放入去皮切块的鲜山药，小火煮至米烂粥稠。不加糖。",
     method_en="Bring the rice to the boil in water, add peeled, diced fresh yam and simmer until the rice breaks down. No sugar.",
     evidence=["shanyao_zhou", "shuyu", "shanyao_cool"],
     notes=["The references differ on its nature: slightly warm in the 神农本草经, cool in the 食鉴本草."])
dish("xiaomi_zhou", "小米粥", "Millet congee", "congee", [("millet", 50)],
     nature="neutral", suits=["qixu", "pinghe", "tebing"], slots=[B],
     method_zh="小米淘净，加十倍水，小火煮三四十分钟至米油浮起。宜早晨空腹温食。",
     method_en="Rinse the millet, add ten times its volume of water and simmer 30–40 minutes until creamy. Best warm, first thing in the morning.",
     evidence=["sumi_zhou"])
dish("lianzi_zhou", "莲子粥", "Lotus-seed congee", "congee", [("rice", 40), ("lotus_seed", 20)],
     nature="neutral", suits=["qixu", "pinghe", "qiyu"], slots=[B, D],
     method_zh="莲子去心，先浸泡两小时；与粳米同煮至莲子酥烂。一定要煮熟。",
     method_en="Remove the green germ, soak the lotus seeds two hours, then simmer with the rice until soft. Always cook them through.",
     evidence=["lianzi", "oushi"], cautions=["lianzi_raw"])
dish("yiyiren_zhou", "薏苡仁粥", "Coix (Job's tears) congee", "congee", [("coix", 30), ("rice", 30)],
     nature="cool", suits=["tanshi", "shire"], slots=[B], seasons=["summer", "wet", "hot"],
     avoid=[("yangxu", None, "cool: not for those who feel the cold")],
     method_zh="薏苡仁淘净先浸泡两小时，与粳米同煮至开花软烂。",
     method_en="Soak the coix two hours, then simmer with the rice until it splits and softens.",
     evidence=["yiyi_zhou", "yiyi"])
dish("lvdou_zhou", "绿豆粥", "Mung-bean congee", "congee", [("mung", 30), ("rice", 30)],
     nature="cold", suits=["shire", "yinxu", "pinghe"], slots=[B, A], seasons=["summer", "hot"], not_seasons=["winter", "cold"],
     avoid=[("yangxu", None, "cold"), ("qixu", None, "cold, for a weak middle")],
     method_zh="绿豆带皮先煮至开花，再加粳米同煮至稠。温食，不要冰镇；不加糖或少加。",
     method_en="Simmer the mung beans, skins on, until they split, then add the rice and cook until thick. Eat warm, not iced; little or no sugar.",
     evidence=["lvdou_zhou", "lvdou"], cautions=["lvdou_medicine"])
dish("chixiaodou_zhou", "赤小豆粥", "Adzuki-bean congee", "congee", [("adzuki", 30), ("rice", 30)],
     nature="neutral", suits=["tanshi", "shire"], slots=[B], seasons=["wet", "summer"],
     avoid=[("qixu", "chixiaodou_caution", "the text warns it weakens with long use"),
            ("yinxu", "chixiaodou_caution", "it drives out fluids")],
     method_zh="赤小豆浸泡一夜，煮至软烂后加粳米同煮。宜间断食用，不宜天天长期吃。",
     method_en="Soak the beans overnight, simmer until soft, then add the rice. Now and then, not every day for long.",
     evidence=["chixiaodou"], cautions=["chixiaodou_caution"])
dish("gouqi_zhou", "枸杞粥", "Goji congee", "congee", [("rice", 50), ("goji", 10)],
     nature="neutral", suits=["yinxu", "pinghe"], slots=[B], seasons=["autumn", "dry", "spring"],
     avoid=[("shire", None, "a supplementing dish: not while damp-heat dominates")],
     method_zh="粳米煮粥，将熟时放入洗净的枸杞子，再煮五分钟。",
     method_en="Cook the rice into congee; add the rinsed goji for the last five minutes.",
     evidence=["gouqi_zhou", "gouqi"])
dish("hutao_zhou", "核桃粥", "Walnut congee", "congee", [("rice", 50), ("walnut", 15)],
     nature="warm", suits=["yangxu", "qixu"], slots=[B], seasons=["autumn", "winter", "cold"],
     avoid=[("tanshi", "hutao_caution", "walnuts stir phlegm"), ("shire", None, "warm and rich")],
     method_zh="核桃仁捣碎，与粳米同煮成粥。一次一小把核桃即可。",
     method_en="Crush the walnuts and cook them with the rice. A small handful is enough.",
     evidence=["hutao_zhou"], cautions=["hutao_caution"], allergens=["tree_nut"])
dish("niuru_zhou", "牛奶粥", "Milk congee", "congee", [("rice", 40), ("milk", 200)],
     nature="neutral", suits=["qixu", "yinxu", "pinghe"], slots=[B],
     method_zh="粳米加水煮成稀粥，将熟时倒入牛奶，搅匀煮开即可。",
     method_en="Cook the rice into a thin congee and stir in the milk at the end; bring just to the boil.",
     evidence=["niuru_zhou", "niuru"], allergens=["milk"])
dish("huluobo_zhou", "胡萝卜粥", "Carrot congee", "congee", [("rice", 40), ("carrot", 80)],
     nature="neutral", suits=["qiyu", "tanshi", "pinghe"], slots=[B, D],
     method_zh="胡萝卜切丁，与粳米同煮至软烂。",
     method_en="Dice the carrot and simmer it with the rice until soft.",
     evidence=["huluobo_zhou"])
dish("danggui_yangrou_tang", "当归生姜羊肉汤", "Lamb soup with dang gui and ginger", "soup",
     [("lamb", 100), ("ginger", 15), ("danggui", 3), ("salt", 1)],
     nature="hot", suits=["yangxu"], slots=[L], not_slots=[D], seasons=["winter", "cold"], not_seasons=["summer", "hot"],
     avoid=[("yinxu", None, "very warm"), ("shire", None, "very warm")],
     method_zh="羊肉切块焯水；与生姜片、当归片同炖一个半小时，撇去浮油，加少许盐。当归只作调料，少量。",
     method_en="Blanch the diced lamb; simmer 1½ hours with sliced ginger and a few slices of dang gui; skim the fat; a little salt. Dang gui as a seasoning only, in a small amount.",
     evidence=["danggui_yangrou", "yangrou"], cautions=["yangrou_summer", "no_night_ginger"], meat="lamb", purine_broth=True,
     notes=["In the 金匮要略 this is a prescription for an illness; here it is only the everyday winter soup of the same name, with dang gui as a seasoning (as China's list allows), never a treatment."])
dish("lizi_menji", "板栗焖鸡", "Chicken braised with chestnuts", "dish", [("chicken", 100), ("chestnut", 60), ("salt", 1)],
     nature="warm", suits=["qixu", "yangxu"], slots=[L, D], seasons=["autumn", "winter", "cold"],
     avoid=[("shire", None, "warm and filling")],
     method_zh="鸡腿肉切块，与去壳板栗加水焖至板栗酥软，少盐。板栗一次十来颗为宜。",
     method_en="Braise the diced chicken with shelled chestnuts in a little water until the chestnuts are soft; little salt. About ten chestnuts.",
     evidence=["lizi", "ji"], cautions=["lizi_caution"], meat="chicken")
dish("donggua_tang", "冬瓜汤", "Winter-melon soup", "soup", [("waxgourd", 200), ("shiitake", 5), ("salt", 1)],
     nature="cool", suits=["tanshi", "shire"], slots=[L, D], seasons=["summer", "hot", "wet"],
     avoid=[("yinxu", "donggua_caution", "the 食鉴本草 says those with yin deficiency should not eat it"), ("yangxu", None, "cool")],
     method_zh="冬瓜连皮切块，与泡发的香菇同煮二十分钟，少盐。",
     method_en="Simmer the winter melon (skin on) with soaked shiitake for 20 minutes; little salt.",
     evidence=["donggua"], cautions=["donggua_caution"])
dish("luobo_tang", "白萝卜汤", "Daikon soup", "soup", [("daikon", 150), ("shiitake", 5), ("salt", 1)],
     nature="cool", suits=["tanshi", "qiyu"], slots=[D, L], seasons=["autumn", "winter"],
     avoid=[("qixu", "luobo", "too much drains spleen qi")],
     method_zh="白萝卜切块，与香菇同煮至透明，少盐。宜作晚餐的汤。",
     method_en="Simmer the daikon with the shiitake until translucent; little salt. A soup for the evening meal.",
     evidence=["luobo", "ginger_morning"])
dish("lianou_paigu_tang", "莲藕排骨汤", "Lotus-root and pork-rib soup", "soup", [("lotus_root", 150), ("pork_ribs", 80), ("salt", 1)],
     nature="neutral", suits=["pinghe", "qixu", "yinxu"], slots=[L, D], seasons=["autumn", "winter", "dry"],
     method_zh="排骨焯水，与莲藕块同炖一个半小时，撇去浮油，少盐。",
     method_en="Blanch the ribs; simmer with chunks of lotus root for 1½ hours; skim the fat; little salt.",
     evidence=["ou"], meat="pork", pork=True, purine_broth=True)
dish("huangqi_dunji", "黄芪炖鸡", "Chicken stewed with astragalus", "soup", [("chicken", 100), ("huangqi", 10), ("jujube", 10), ("salt", 1)],
     nature="warm", suits=["qixu", "tebing"], slots=[L, D], seasons=["autumn", "winter"],
     avoid=[("shire", None, "a warm supplementing dish"), ("yinxu", None, "warm and supplementing")],
     method_zh="鸡腿肉焯水，与黄芪片、红枣同炖一小时，撇去浮油，少盐。",
     method_en="Blanch the chicken; simmer one hour with astragalus slices and red dates; skim the fat; little salt.",
     evidence=["huangqi", "ji", "dazao"], meat="chicken", purine_broth=True)
dish("jiucai_chaodan", "韭菜炒蛋", "Chinese chives with egg", "dish", [("chives", 100), ("egg", 100), ("oil", 5), ("salt", 1)],
     nature="warm", suits=["yangxu", "pinghe", "xueyu"], slots=[L, D], seasons=["spring"], not_seasons=["summer"],
     avoid=[("yinxu", "jiu_caution", "too many assist yang"), ("shire", "jiu_caution", "too many assist yang")],
     method_zh="韭菜切段，鸡蛋打散；少油先炒蛋，再下韭菜快炒，少盐。",
     method_en="Cut the chives; beat the eggs; scramble in a little oil, add the chives and stir-fry briefly; little salt.",
     evidence=["jiu_season", "jiu_blood"], cautions=["jiu_caution"], allergens=["egg"],
     notes=["The text's months are China's lunar months (about March–April); here they follow the local spring."])
dish("jiangzao_cha", "姜枣茶", "Ginger and red-date tea", "drink", [("ginger", 10), ("jujube", 15)],
     nature="warm", suits=["yangxu", "qixu"], slots=[B], not_slots=[D], seasons=["autumn", "winter", "cold", "wet"],
     avoid=[("yinxu", None, "warm and pungent"), ("shire", None, "warm and pungent")],
     method_zh="生姜切片、红枣掰开，加水煮十五分钟。宜早晨喝，晚上不喝。",
     method_en="Slice the ginger, split the dates, simmer 15 minutes in water. A morning drink, not an evening one.",
     evidence=["ginger_morning", "dazao"], cautions=["no_night_ginger"], serving="1 cup")
dish("jiangju_tang", "姜橘汤", "Ginger and tangerine-peel tea", "drink", [("ginger", 6), ("chenpi", 3)],
     nature="warm", suits=["qiyu", "tanshi"], slots=[B], not_slots=[D],
     avoid=[("yinxu", None, "warm and drying"), ("shire", None, "warm and drying")],
     method_zh="生姜切片、陈皮一小块，加水煮十分钟，早晨空腹温饮。",
     method_en="Simmer sliced ginger and a small piece of dried tangerine peel for 10 minutes; drink warm in the morning before eating.",
     evidence=["jiangju", "jupi"], cautions=["no_night_ginger"], serving="1 cup")
dish("gouqi_juhua_cha", "枸杞菊花茶", "Goji and chrysanthemum tea", "drink", [("goji", 6), ("chrysanthemum", 3)],
     nature="cool", suits=["yinxu", "pinghe", "shire"], slots=[A], seasons=["spring", "summer", "dry"],
     avoid=[("yangxu", None, "cool")],
     method_zh="枸杞子与菊花用热水冲泡五分钟，可续水。不加糖。",
     method_en="Steep the goji and chrysanthemum in hot water for five minutes; top up. No sugar.",
     evidence=["juhua", "gouqi"], serving="1 cup",
     notes=["Chrysanthemum belongs to the daisy family: skip it with a ragweed or daisy allergy."])
dish("zheng_li", "蒸梨", "Steamed pear", "dessert", [("pear", 200)],
     nature="cool", suits=["yinxu", "shire"], slots=[A], seasons=["autumn", "dry"],
     avoid=[("yangxu", "li_caution", "cool"), ("qixu", "li_caution", "the weak who eat many get diarrhoea")],
     method_zh="梨洗净去核，隔水蒸二十分钟，连汁温食。不加糖。",
     method_en="Core the pear and steam it 20 minutes; eat it warm with its juice. No sugar.",
     evidence=["li", "ligao"], cautions=["li_caution"], serving="1 pear")
dish("heizhima_hu", "黑芝麻糊", "Black-sesame paste", "dessert", [("sesame", 20), ("glutinous_rice", 15), ("sugar", 5)],
     nature="neutral", suits=["yinxu", "pinghe"], slots=[B, A], seasons=["autumn", "winter", "dry"],
     avoid=[("tanshi", None, "rich and sweet")],
     method_zh="黑芝麻小火炒香，与糯米一同磨粉，加水边煮边搅成糊。糖可不放。",
     method_en="Toast the sesame gently, grind it with the glutinous rice, and stir into simmering water until thick. Sugar optional.",
     evidence=["zhima", "zhima_black"], allergens=["sesame"])
dish("shanzha_cha", "山楂茶", "Hawthorn infusion", "drink", [("hawthorn", 10)],
     nature="warm", suits=["xueyu", "tanshi"], slots=[L, D],
     method_zh="山楂干片加水煮十分钟，饭后温饮，尤其是吃肉较多的一餐之后。不要空腹喝。",
     method_en="Simmer dried hawthorn slices 10 minutes; drink warm after a meal, especially a meaty one. Not on an empty stomach.",
     evidence=["shanzha"], serving="1 cup",
     notes=["Sour: skip with a stomach ulcer or acid reflux."])

# ------------------------------------------------------------------ write
foods_out = {k: dict(zh=v["zh"], en=v["en"], homology=v["homology"], herb=v["herb"],
                     usda=(dict(description=usda[v["usda"]]["usda_description"], fdc_id=usda[v["usda"]]["fdc_id"]) if v["usda"] else None),
                     note=v["note"] or None)
             for k, v in FOOD.items() if any(i["food"] == k for d in DISHES for i in d["ingredients"])}
head = ("// Generated by data/diet/make_medicinal.py from data/diet/usda.sources.json, data/diet/medicinal-usda.sources.json\n"
        "// and corpus/web: do not edit.  The medicinal dishes (药膳) of 饮食与体重管理, their ingredients and per-serving\n"
        "// nutrition (USDA FoodData Central; an ingredient with no record is in `not_counted`), and the classical passages each\n"
        "// rests on (every quotation occurs in its passage, character for character).\n\n")
body = "".join(f"export const {name} = {json.dumps(val, ensure_ascii=False, indent=1)};\n\n"
               for name, val in (("FOODS", foods_out), ("QUOTES", QUOTES), ("DISHES", DISHES)))
TARGET.write_text(head + body.rstrip() + "\n", encoding="utf-8")
print(f"{len(DISHES)} dishes, {len(QUOTES)} quotations, {len(foods_out)} foods -> {TARGET}")
