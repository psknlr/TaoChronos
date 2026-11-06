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
food("pine_nut", "松子仁", "pine nuts", "pine_nuts")
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

# the second set of dishes
food("euryale", "芡实", "euryale seed (fox nut)", None, homology="2002", note="On the list as 芡实. No USDA record.")
food("poria", "茯苓（粉）", "poria (fu ling), powdered", None, homology="2002", herb=True, note="No USDA record.")
food("hyacinth_bean", "白扁豆", "white hyacinth beans", "hyacinth_beans_raw", homology="2002")
food("wheat", "小麦（全麦粒）", "wheat grain", "wheat_flour_whole", note="USDA's whole-grain wheat flour stands for the whole grain.")
food("flour", "面粉", "wheat flour", "wheat_flour_white")
food("purslane", "马齿苋", "purslane", "purslane_raw", homology="2002")
food("longan", "桂圆肉（干）", "longan, dried", "longan_dried", homology="2002", note="On the list as 龙眼肉（桂圆）.")
food("xiebai", "薤白", "Chinese chive bulb (xie bai)", None, homology="2002", note="No USDA record.")
food("scallion", "葱白", "spring onion", "spring_onion_raw")
food("chicken_breast", "鸡胸肉", "chicken breast", "chicken_breast_raw")
food("carp", "鲤鱼（净肉）", "carp, flesh", "carp_raw")
food("caoguo", "草果（作调料）", "tsaoko (cao guo), as a spice", None, homology="2019",
     note="Added to the list in 2019 for use only as a spice or seasoning. No USDA record.")
food("chickpeas", "鹰嘴豆（熟）", "chickpeas, cooked", "chickpeas")
food("cabbage", "大白菜", "Chinese cabbage (napa)", "chinese_cabbage_raw")
food("tofu", "豆腐", "tofu, firm", "tofu")
food("garland", "茼蒿", "garland chrysanthemum greens", "garland_chrysanthemum_raw")
food("shepherds_purse", "荠菜", "shepherd's purse", None, note="No USDA record.")
food("amaranth", "苋菜", "amaranth greens", "amaranth_leaves_raw")
food("bamboo", "竹笋", "bamboo shoots", "bamboo_shoots_raw")
food("taro", "芋头", "taro", "taro_raw")
food("water_chestnut", "荸荠（马蹄）", "Chinese water chestnut", "water_chestnut_raw")
food("wumei", "乌梅", "smoked plum (wu mei)", None, homology="2002", note="No USDA record.")
food("lotus_starch", "藕粉", "lotus-root starch", None, note="No USDA record.")
food("beef", "牛肉（瘦）", "beef, lean", "beef_lean_raw", note="The closest USDA record whose values could be read: round, lean only, trimmed to 1/8\" fat, raw.")
food("lily", "百合（干）", "lily bulb, dried", None, homology="2002", note="No USDA record.")
food("yuzhu", "玉竹", "Solomon's seal rhizome (yu zhu)", None, homology="2002", herb=True, note="No USDA record.")
food("kudzu", "葛根粉", "kudzu-root starch", None, homology="2002", note="On the list as 葛根. No USDA record.")
food("persimmon_dried", "柿饼", "dried persimmon", "persimmon_dried")
food("goji_leaf", "枸杞叶", "goji leaves", None, note="No USDA record.")
food("barley", "大麦（珍珠麦）", "pearled barley", "barley_pearled_raw")
food("sugarcane", "甘蔗汁", "sugar-cane juice", None, note="No USDA record.")
food("duck", "鸭肉（去皮）", "duck meat, skinless", "duck_raw")
food("honey", "蜂蜜", "honey", "honey", homology="2002")

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

# ------------------------------------------------------------------ more passages (the second set of dishes)
quote("no_autumn_ginger", "jc_c049.00120", "八月、九月匆食薑，傷人神，損壽。",
      "Do not eat ginger in the eighth and ninth (lunar) months: it harms the spirit and shortens life (匆 for 勿 in this text).", "season")
quote("no_autumn_ginger_2", "jc_c028.00074", "九月食薑。傷人損壽。", "Ginger in the ninth month harms and shortens life.", "season")
quote("yangrou_sixth_month", "jc_c049.00180", "六月勿食羊肉，傷人神氣。", "Do not eat mutton in the sixth (lunar) month.", "season")
quote("jiangzao_yinshan", "jc_c047.00325", "和脾胃，進飲食。", "Ginger and jujube (a powder taken in hot water): harmonises the spleen and stomach, helps one eat.", "dish")
quote("zhengli", "jc_c028.00331", "大雪梨連皮。安飯鍋內蒸。熟食能化痰清火。", "Steamed pear: a large pear in its skin, steamed on the rice; eaten cooked, it clears phlegm and fire.", "dish")
quote("lianzi_yinshan", "jc_c047.00538", "治心志不寧。補中強志，聰明耳目。", "Lotus-seed congee (饮膳正要): for an unsettled mind; supplements the middle, strengthens the will, sharpens ears and eyes.", "dish")
quote("lianzi_method", "jc_c047.00540", "上件煮熟，研如泥，與粳米三合，作粥，空腹食之。", "Cook the lotus seeds, mash them, make congee with the rice; eat on an empty stomach.", "dish")
quote("qianshi_zhou", "jc_c028.00349", "益精氣。強智力。聰耳目。用芡實去殼三合。新者研成膏。陳者作粉。和粳米三合煮食。",
      "Euryale congee: benefits essence and qi, strengthens the mind, sharpens ears and eyes; euryale with rice.", "dish")
quote("qianshi_yinshan", "jc_c047.00541", "治精氣不足，強志，明耳目。", "Euryale congee (饮膳正要): for insufficient essence and qi.", "dish")
quote("qianshi", "jc_c049.00041", "雞頭實：味甘、平、無毒。主濕痹，腰脊膝痛；補中；除暴疾；益精氣，強志意，耳目聰明。",
      "Euryale seed: sweet, neutral; for damp painful obstruction, aching back and knees; supplements the middle.")
quote("fuling_zhou", "jc_c028.00327", "粳米煮粥。半熟。入茯苓末。和勻煮熟。空心食。能治濕痰健脾。",
      "Poria congee: rice half-cooked, poria powder stirred in; on an empty stomach it treats damp phlegm and strengthens the spleen.", "dish")
quote("fuling_zhou_2", "jc_c028.00353", "治虛泄脾弱。又治欲睡不睡。", "Poria congee: for weak-spleen diarrhoea, and for wanting to sleep but not sleeping.", "dish")
quote("fuling", "ws_36bca7b992.00086", "久服安魂養神，不饑延年。", "Poria: taken long, calms the ethereal soul and nourishes the spirit.")
quote("biandou_zhou", "jc_c028.00355", "益精補脾。", "Hyacinth-bean congee: benefits essence, supplements the spleen (the recipe adds ginseng, left out here).", "dish")
quote("biandou", "jc_c028.00023", "清胃解毒。久食須發不白。又能解酒毒", "White hyacinth bean: clears the stomach and toxins, eases the effects of wine.")
quote("biandou_caution", "jc_c028.00023", "惟患寒熱及冷氣人忌食。", "Not for those with chills and fever or cold qi.", "caution")
quote("biandou_jingui", "cm_jingui_wuqian.01139", "扁豆，寒熱者不可食之。", "The 金匮要略: hyacinth beans are not for those with chills and fever.", "caution")
quote("luobo_zhou", "jc_c047.00577", "上件，用粳米三合，同水並汁，煮粥食之。", "Radish congee (饮膳正要): radish cooked and its juice cooked with rice into congee.", "dish")
quote("luobo_zhou_2", "jc_o031.00944", "蘿卜大者一個，配米二合煮食。", "Radish congee (寿世青编): one large radish with rice.", "dish")
quote("xiaomai_zhou", "jc_c047.00598", "右以煮粥，或炊作飯，空腹食之。", "Wheat: cooked as congee, or as a rice-like dish, on an empty stomach.", "dish")
quote("xiaomai_region", "jc_c028.00015", "北方多霜雪。面無毒益人。南方少霜雪。面有濕熱損人。",
      "Wheat flour from the frosty north benefits; from the warm south it carries damp heat (the 食鉴本草's regional view).", "caution")
quote("machixian_zhou", "jc_c047.00595", "上件，和粳米同煮粥，空腹食之。", "Purslane congee (饮膳正要): purslane juice cooked with rice.", "dish")
quote("machixian_geng", "jc_c028.00311", "用馬齒莧菜煮熟。用鹽豉或薑醋拌勻食之。", "Purslane: boiled, dressed with salt and fermented soybeans, or ginger and vinegar.", "dish")
quote("machixian", "jc_c049.00075", "久服益氣力，不飢，輕身。", "Purslane (its seed, in the 千金食治): taken long, adds strength.")
quote("songzi_zhou", "jc_o031.00971", "潤心肺，和大腸。同米煮粥食。", "Pine-nut congee: moistens the heart and lung, harmonises the large intestine.", "dish")
quote("songzi", "jc_c028.00136", "潤燥明目生痰。久服輕身不老。", "Pine nuts: moisten dryness, brighten the eyes — and produce phlegm; taken long, keep the body light.")
quote("longyan", "jc_c028.00138", "安神補血。久服輕身不老。", "Longan: calms the spirit and supplements the blood.")
quote("longyan_shennong", "ws_36bca7b992.00203", "主治五臟邪氣，安誌，厭食。久服強魂，聰明，輕身不老，通神明。", "Longan (神农本草经): settles the mind; taken long, strengthens the soul.")
quote("dazao_qianjin", "jc_c049.00037", "補中益氣，強志，除煩悶", "Jujube (千金食治): supplements the middle and benefits qi, eases vexation.")
quote("zao_caution", "jc_c028.00101", "熟食補脾。和諸藥。凡中滿與腹脹牙痛者。俱不可食。", "Jujube: cooked, supplements the spleen; not with fullness, bloating or toothache.", "caution")
quote("xiebai_zhou", "shouqin_yanglao.001.00170", "薤白粥方", "Chinese-chive-bulb (薤白) congee, with rice and spring onion.", "dish")
quote("xiebai_method", "shouqin_yanglao.001.00171", "右相和作羮下五味椒醬薑空心食常作取效", "Cook together, season, eat on an empty stomach.", "dish")
quote("xie", "jc_c049.00090", "除寒熱，去水氣，溫中，散結氣", "Chinese chive bulb: dispels cold and heat, drains water, warms the middle, disperses bound qi.")
quote("xie_caution", "jc_c028.00056", "食之生痰涕。動邪火。", "It produces phlegm and stirs pathogenic fire.", "caution")
quote("ji_geng", "shouqin_yanglao.001.00184", "右切雞和煮作羮下五味少著鹽空心食之漸進當效", "Hen and rice soup: the hen cut and cooked with rice, a little salt, on an empty stomach.", "dish")
quote("ji_huntun", "shouqin_yanglao.001.00158", "右以切肉作餛飩下椒醬五味調和煮熟空心食之日一服皆益臟腑悦澤顔色",
      "Hen wontons: the meat in wontons, cooked and seasoned; they benefit the organs and brighten the complexion.", "dish")
quote("liyu_chixiaodou", "jc_c047.00591", "大鯉魚（一頭）　赤小豆（一合）　陳皮（二錢，去白）", "Carp with adzuki beans and tangerine peel (饮膳正要).", "dish")
quote("liyu_chixiaodou_method", "jc_c047.00592", "上件，入五味，調和勻，煮熟，空腹食之。", "Season, cook, eat on an empty stomach.", "dish")
quote("liyu_caution", "jc_c028.00194", "發風熱。凡一切風病大癰疽瘡疥瘧痢。俱不可食。", "Carp stirs wind-heat: not with skin sores, boils or dysentery.", "caution")
quote("chenpi_liyu", "shouqin_yanglao.001.00216", "右和煮令爛熟空心以二味少著鹽食之常服並飲少許汁將理為驗",
      "Carp boiled with tangerine peel until tender, a little salt, eaten on an empty stomach with some of the broth.", "dish")
quote("chixiaodou_ji", "jc_c047.00570", "黃雌雞（一只，　淨）　草果（二錢）　赤小豆（一升）", "Hen with tsaoko and adzuki beans (饮膳正要).", "dish")
quote("chixiaodou_ji_method", "jc_c047.00571", "上件，同煮熟，空心食之。", "Cook together; eat on an empty stomach.", "dish")
quote("chixiaodou_ya", "jc_c047.00574", "上件，用赤小豆半升，入鴨腹內煮熟，五味調，空心食。", "Duck with adzuki beans inside it, cooked and seasoned (饮膳正要).", "dish")
quote("ya_season", "jc_c028.00177", "野鴨九月以後宜食。不動氣。", "Duck is good from the ninth month on.", "season")
quote("yangrou_caoguo", "jc_c047.00102", "羊肉（一腳子，卸成事件）　草果（五個）　回回豆子（半升，搗碎，去皮）", "Mutton, tsaoko and chickpeas: the broth of the 饮膳正要's court soups.", "dish")
quote("yangrou_caoguo_effect", "jc_c047.00101", "補中益氣。", "It supplements the middle and benefits qi.", "dish")
quote("songcai", "jc_c049.00082", "菘菜：味甘、溫、澀、無毒。久食通利腸胃，除胸中煩，解消渴。", "Chinese cabbage: eaten long, frees the bowels, eases vexation in the chest, relieves thirst.")
quote("qingcai_doufu", "jc_c028.00030", "凡往遠方煮青菜豆腐食。則無不服水土病。", "Travelling far, cook greens with tofu, and you will not fall ill from strange waters and soils.", "dish")
quote("tonghao", "jc_c049.00101", "茼蒿：味辛、平，無毒。安心氣，養脾胃。消痰飲。", "Garland chrysanthemum: calms heart qi, nourishes spleen and stomach, clears phlegm-fluid.")
quote("jicai", "jc_c049.00079", "薺菜：味甘、溫、澀、無毒。利肝氣，和中；殺諸毒。", "Shepherd's purse: frees liver qi, harmonises the middle.")
quote("xiancai", "jc_c049.00076", "小莧菜：味甘、大寒、滑、無毒。可久食，益氣力，除熱。", "Amaranth greens: very cold; may be eaten long; add strength, clear heat.")
quote("xiancai_caution", "jc_c049.00076", "不可共鱉肉食", "Not with soft-shelled turtle.", "caution")
quote("sun", "jc_c049.00123", "竹筍。味甘、微寒、無毒。主消渴，利水道，益氣力，可久食，患冷人食之心痛。", "Bamboo shoot: slightly cold; for thirst, frees the waterways, adds strength — but those with cold suffer heart pain.")
quote("yu", "jc_c049.00054", "芋：味辛、平、滑、有毒。寬腸胃、充肌膚，滑中。一名土芝，不可多食，動宿冷。", "Taro: eases the bowels, fills out the flesh; not in quantity (it stirs old cold); raw taro is irritant.")
quote("wuyu", "jc_c049.00055", "烏芋：味苦、甘、微寒、滑，無毒。主消渴、癉熱；益氣。", "Water chestnut: slightly cold; for thirst and heat; benefits qi.")
quote("biqi", "jc_c028.00146", "消食除滿。作粉食之。濃腸胃。", "Water chestnut: helps digestion, relieves fullness; as a starch, thickens the intestines.")
quote("meishi", "jc_c049.00048", "梅實：味酸、平、澀、無毒。下氣，除熱煩滿，安心", "Mume (乌梅): sour; sends qi down, clears heat and vexation, calms the heart.")
quote("meizi", "jc_c028.00103", "止渴生津。多食壞齒損筋", "Plum: stops thirst, makes fluids; too much harms the teeth.")
quote("oufen", "jc_c028.00321", "真藕粉空心滾水沖食。最能散血補陰。", "Lotus-root starch, stirred into boiling water on an empty stomach: best to disperse the blood and supplement yin.", "dish")
quote("ou_raw", "jc_c049.00040", "生根寒，止熱渴，破留血。", "Lotus root, raw: cold; stops thirst from heat, breaks up retained blood.")
quote("niurou", "jc_c049.00182", "肉：味甘、平、無毒。主消渴，止唾涎出，安中益氣力，養脾胃氣，不可常食，發宿病。",
      "Beef: sweet, neutral; settles the middle, adds strength, nourishes the spleen and stomach — not every day.")
quote("niurou_against", "jc_c028.00188", "耕田。大功於人。不可食。", "The ox ploughs the fields, a great service to people: do not eat it (the 食鉴本草's moral view).", "caution")
quote("baihe_zheng", "jc_c004.00042", "蒸過，蜜和食之。作粉尤佳。", "Lily bulb: steamed, eaten with honey; even better as a starch.", "dish")
quote("baihe", "ws_36bca7b992.00262", "利大小便。補中益氣。", "Lily bulb: frees the bowels and bladder, supplements the middle, benefits qi.")
quote("yuzhu", "jc_c000a.00014", "久服去面黑䵟，好顏色，潤澤，輕身，不老。", "Solomon's seal (玉竹): taken long, clears dark facial spots, gives a good, moist complexion.")
quote("gegen", "ws_36bca7b992.00160", "主治消渴，身大熱，嘔吐，諸痹，起陰氣，解諸毒。", "Kudzu root: for thirst and great body heat, raises yin qi, relieves toxins.")
quote("shibing", "jc_c028.00296", "大柿餅放飯鍋內。蒸極爛。空心熱服。最能清火涼血。", "Steamed dried persimmon, very soft, eaten hot on an empty stomach: clears fire and cools the blood.", "dish")
quote("shi_caution", "jc_c028.00130", "多食腹痛。久食寒中。同蟹食。即腹痛泄瀉。", "Too much persimmon: abdominal pain; never with crab.", "caution")
quote("gouqiye", "jc_c049.00065", "枸杞葉：味苦、平、澀、無毒。補虛羸，益精髓。", "Goji leaves: supplement weakness, benefit essence and marrow.")
quote("damai_tang", "shouqin_yanglao.001.00182", "大麥湯方", "Barley decoction (寿亲养老新书), for thirst.", "dish")
quote("damai", "jc_c028.00013", "健胃。寬中。多食消腎。", "Barley: strengthens the stomach, eases the middle; too much depletes the kidney.")
quote("ganzhe_zhou", "jc_c028.00283", "用甘蔗搗汁。入米煮粥。空心食之。", "Sugar-cane congee: cane juice cooked with rice, on an empty stomach.", "dish")
quote("ganzhe", "jc_c049.00052", "甘蔗：味甘、平、澀、無毒。下氣和中，補脾氣，利大腸，止渴，去煩，解酒毒。", "Sugar cane: harmonises the middle, supplements spleen qi, stops thirst.")

# ------------------------------------------------------------------ the dishes
DISHES = []
def dish(id, zh, en, kind, parts, *, nature, suits, slots, method_zh, method_en, evidence, avoid=(), seasons=(), not_seasons=(),
         not_slots=(), cautions=(), serving="1 bowl", allergens=(), meat=None, pork=False, beef=False, purine_broth=False, sweet=False,
         notes=()):
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
        evidence=list(evidence), cautions=list(cautions), allergens=sorted(allergens), meat=meat, pork=pork, beef=beef,
        purine_broth=purine_broth, sweet=sweet, herbs=sorted({i["food"] for i in items if i["herb"]}),
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
     evidence=["lianzi_yinshan", "lianzi_method", "lianzi", "oushi"], cautions=["lianzi_raw"])
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
     evidence=["danggui_yangrou", "yangrou"], cautions=["yangrou_summer", "yangrou_sixth_month", "no_night_ginger"], meat="lamb", purine_broth=True,
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
     nature="warm", suits=["yangxu", "qixu"], slots=[B], not_slots=[D], seasons=["winter", "cold", "wet"], not_seasons=["autumn"],
     avoid=[("yinxu", None, "warm and pungent"), ("shire", None, "warm and pungent")],
     method_zh="生姜切片、红枣掰开，加水煮十五分钟。宜早晨喝，晚上不喝。",
     method_en="Slice the ginger, split the dates, simmer 15 minutes in water. A morning drink, not an evening one.",
     evidence=["jiangzao_yinshan", "ginger_morning", "dazao"], cautions=["no_autumn_ginger", "no_night_ginger"], serving="1 cup")
dish("jiangju_tang", "姜橘汤", "Ginger and tangerine-peel tea", "drink", [("ginger", 6), ("chenpi", 3)],
     nature="warm", suits=["qiyu", "tanshi"], slots=[B], not_slots=[D], not_seasons=["autumn"],
     avoid=[("yinxu", None, "warm and drying"), ("shire", None, "warm and drying")],
     method_zh="生姜切片、陈皮一小块，加水煮十分钟，早晨空腹温饮。",
     method_en="Simmer sliced ginger and a small piece of dried tangerine peel for 10 minutes; drink warm in the morning before eating.",
     evidence=["jiangju", "jupi"], cautions=["no_autumn_ginger", "no_night_ginger"], serving="1 cup")
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
     evidence=["zhengli", "li", "ligao"], cautions=["li_caution"], serving="1 pear")
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

# ------------------------------------------------------------------ the second set
dish("qianshi_zhou", "芡实粥", "Euryale (fox-nut) congee", "congee", [("rice", 40), ("euryale", 20)],
     nature="neutral", suits=["qixu", "tanshi", "pinghe"], slots=[B],
     method_zh="芡实浸泡一夜，先煮半小时，再加粳米同煮至稠。",
     method_en="Soak the euryale overnight, simmer half an hour, add the rice and cook until thick.",
     evidence=["qianshi_zhou", "qianshi_yinshan", "qianshi"])
dish("fuling_zhou", "茯苓粥", "Poria congee", "congee", [("rice", 50), ("poria", 10)],
     nature="neutral", suits=["tanshi", "qixu", "qiyu"], slots=[B], seasons=["wet"],
     method_zh="粳米煮粥至半熟，调入茯苓粉，搅匀再煮至熟。宜早晨空腹。",
     method_en="Cook the rice halfway, stir in the poria powder and cook through. Best first thing in the morning.",
     evidence=["fuling_zhou", "fuling_zhou_2", "fuling"])
dish("biandou_zhou", "白扁豆粥", "White hyacinth-bean congee", "congee", [("hyacinth_bean", 20), ("rice", 40)],
     nature="neutral", suits=["qixu", "tanshi", "shire"], slots=[B], seasons=["summer", "wet", "hot"],
     avoid=[("yangxu", "biandou_caution", "not for those with cold qi")],
     method_zh="白扁豆浸泡一夜后煮至软烂（一定要煮透），再加粳米同煮。",
     method_en="Soak the beans overnight and simmer until completely soft (never undercooked), then add the rice.",
     evidence=["biandou_zhou", "biandou"], cautions=["biandou_caution", "biandou_jingui"],
     notes=["Hyacinth beans contain lectins that only thorough cooking destroys: never eat them undercooked."])
dish("luobo_zhou", "萝卜粥", "Daikon congee", "congee", [("daikon", 100), ("rice", 40)],
     nature="cool", suits=["tanshi", "qiyu"], slots=[B, D],
     avoid=[("qixu", "luobo", "too much drains spleen qi")],
     method_zh="白萝卜切丁（或榨汁），与粳米同煮成粥。",
     method_en="Dice (or juice) the daikon and cook it with the rice into congee.",
     evidence=["luobo_zhou", "luobo_zhou_2", "luobo"])
dish("xiaomai_zhou", "小麦粥", "Wheat-berry congee", "congee", [("wheat", 50)],
     nature="neutral", suits=["yinxu", "qiyu", "pinghe"], slots=[B],
     method_zh="小麦粒淘净浸泡一夜，小火煮成粥。",
     method_en="Soak the wheat berries overnight and simmer into a porridge.",
     evidence=["xiaomai_zhou"], cautions=["xiaomai_region"], allergens=["wheat"])
dish("machixian_zhou", "马齿苋粥", "Purslane congee", "congee", [("purslane", 80), ("rice", 40)],
     nature="cold", suits=["shire"], slots=[B], seasons=["summer", "hot", "wet"], not_seasons=["winter", "cold"],
     avoid=[("qixu", None, "cold"), ("yangxu", None, "cold")],
     method_zh="马齿苋洗净切碎，粥将熟时放入，再煮五分钟。",
     method_en="Chop the purslane and add it to the congee for its last five minutes.",
     evidence=["machixian_zhou", "machixian"])
dish("songzi_zhou", "松子仁粥", "Pine-nut congee", "congee", [("pine_nut", 15), ("rice", 50)],
     nature="neutral", suits=["yinxu", "pinghe"], slots=[B], seasons=["autumn", "dry", "winter"],
     avoid=[("tanshi", "songzi", "pine nuts produce phlegm")],
     method_zh="松子仁捣碎，粥将熟时放入同煮。一小撮即可。",
     method_en="Crush the pine nuts and stir them into the congee near the end. A small handful.",
     evidence=["songzi_zhou", "songzi"], allergens=["tree_nut"])
dish("guiyuan_zhou", "桂圆红枣粥", "Longan and red-date congee", "congee", [("longan", 10), ("jujube", 10), ("rice", 40)],
     nature="warm", suits=["qixu", "qiyu"], slots=[B], seasons=["autumn", "winter", "cold"],
     avoid=[("yinxu", None, "warm and sweet"), ("shire", None, "warm and sweet"), ("tanshi", None, "sweet")],
     method_zh="粳米煮粥，加桂圆肉与去核红枣同煮至稠。不另加糖。",
     method_en="Cook the rice with the dried longan and pitted dates until thick. No added sugar.",
     evidence=["longyan", "longyan_shennong", "dazao_qianjin"], cautions=["zao_caution"], sweet=True)
dish("xiebai_zhou", "薤白粥", "Chinese-chive-bulb congee", "congee", [("xiebai", 15), ("rice", 50), ("scallion", 10)],
     nature="warm", suits=["yangxu", "qiyu", "xueyu"], slots=[B, L], seasons=["winter", "cold"],
     avoid=[("yinxu", "xie_caution", "it stirs fire"), ("shire", "xie_caution", "it stirs fire"), ("tanshi", "xie_caution", "it produces phlegm")],
     method_zh="薤白、葱白切碎，粥将熟时放入，再煮片刻，少盐。",
     method_en="Chop the xie bai and spring onion and add them to the congee near the end; a little salt.",
     evidence=["xiebai_zhou", "xiebai_method", "xie"], cautions=["xie_caution"])
dish("lizi_zhou", "板栗粥", "Chestnut congee", "congee", [("chestnut", 50), ("rice", 40)],
     nature="warm", suits=["qixu", "yangxu"], slots=[B], seasons=["autumn", "winter", "cold"],
     avoid=[("shire", None, "warm and filling")],
     method_zh="板栗去壳切碎，与粳米同煮至软烂。",
     method_en="Shell and chop the chestnuts and simmer them with the rice until soft.",
     evidence=["lizi"], cautions=["lizi_caution"])
dish("jirou_zhou", "鸡肉粥", "Chicken congee", "congee", [("chicken_breast", 60), ("rice", 40), ("scallion", 10), ("salt", 1)],
     nature="neutral", suits=["qixu", "pinghe", "tebing"], slots=[B, L],
     method_zh="鸡胸肉切丝，粥将熟时放入煮熟，撒葱白，少盐。",
     method_en="Shred the chicken into the congee near the end; spring onion and a little salt.",
     evidence=["ji_geng", "ji"], meat="chicken")
dish("ji_huntun", "鸡肉馄饨", "Chicken wontons", "dish", [("chicken_breast", 60), ("flour", 50), ("scallion", 10), ("salt", 1)],
     nature="neutral", suits=["qixu", "pinghe"], slots=[B, L],
     method_zh="鸡肉剁馅，加葱白、少盐，用面皮包成馄饨，煮熟连汤吃。",
     method_en="Mince the chicken with spring onion and a little salt, wrap in wonton skins, boil and serve in their broth.",
     evidence=["ji_huntun", "ji"], meat="chicken", allergens=["wheat"])
dish("liyu_chixiaodou_tang", "鲤鱼赤小豆汤", "Carp and adzuki-bean soup", "soup", [("carp", 150), ("adzuki", 30), ("chenpi", 2), ("salt", 1)],
     nature="neutral", suits=["tanshi"], slots=[L, D], seasons=["wet", "summer"],
     avoid=[("shire", "liyu_caution", "carp stirs wind-heat")],
     method_zh="赤小豆先煮半小时，放入鲤鱼与一小片陈皮同煮，少盐。",
     method_en="Simmer the adzuki beans half an hour, add the carp and a sliver of tangerine peel; little salt.",
     evidence=["liyu_chixiaodou", "liyu_chixiaodou_method", "chixiaodou"], cautions=["liyu_caution", "chixiaodou_caution"],
     meat="fish", allergens=["fish"])
dish("chenpi_liyu_tang", "陈皮鲤鱼汤", "Carp soup with tangerine peel", "soup", [("carp", 150), ("chenpi", 3), ("salt", 1)],
     nature="neutral", suits=["tanshi", "qiyu"], slots=[L, D],
     avoid=[("shire", "liyu_caution", "carp stirs wind-heat")],
     method_zh="鲤鱼与陈皮同煮至鱼熟汤白，少盐，连汤食。",
     method_en="Simmer the carp with the tangerine peel until done; a little salt; eat with some of the broth.",
     evidence=["chenpi_liyu", "jupi"], cautions=["liyu_caution"], meat="fish", allergens=["fish"])
dish("chixiaodou_dunji", "赤小豆炖鸡", "Chicken stewed with adzuki beans", "soup", [("chicken", 100), ("adzuki", 30), ("caoguo", 1), ("salt", 1)],
     nature="neutral", suits=["tanshi", "qixu"], slots=[L, D], seasons=["wet"],
     method_zh="赤小豆浸泡后与鸡块、一枚草果同炖一小时，少盐。",
     method_en="Stew the soaked adzuki beans with the chicken and one tsaoko pod for an hour; little salt.",
     evidence=["chixiaodou_ji", "chixiaodou_ji_method", "ji"], cautions=["chixiaodou_caution"], meat="chicken", purine_broth=True)
dish("chixiaodou_ya_tang", "赤小豆鸭汤", "Duck and adzuki-bean soup", "soup", [("duck", 120), ("adzuki", 30), ("caoguo", 1), ("salt", 1)],
     nature="cool", suits=["shire", "tanshi", "yinxu"], slots=[L, D], seasons=["autumn", "wet"],
     avoid=[("yangxu", None, "cool")],
     method_zh="鸭肉焯水，与赤小豆、一枚草果同炖一个半小时，撇去浮油，少盐。",
     method_en="Blanch the duck, stew with the adzuki beans and a tsaoko pod for 1½ hours, skim the fat; little salt.",
     evidence=["chixiaodou_ya", "ya_season"], cautions=["chixiaodou_caution"], meat="duck", purine_broth=True)
dish("yuzhu_laoya_tang", "玉竹老鸭汤", "Duck soup with Solomon's seal", "soup", [("duck", 120), ("yuzhu", 10), ("salt", 1)],
     nature="cool", suits=["yinxu", "pinghe"], slots=[L, D], seasons=["autumn", "dry"],
     avoid=[("yangxu", None, "cool"), ("tanshi", None, "moistening")],
     method_zh="鸭肉焯水，与玉竹同炖一个半小时，撇去浮油，少盐。",
     method_en="Blanch the duck, stew with the yu zhu for 1½ hours, skim the fat; little salt.",
     evidence=["yuzhu", "ya_season"], meat="duck", purine_broth=True)
dish("yangrou_caoguo_tang", "羊肉草果鹰嘴豆汤", "Lamb, tsaoko and chickpea soup", "soup", [("lamb", 100), ("chickpeas", 60), ("caoguo", 1), ("salt", 1)],
     nature="hot", suits=["yangxu", "qixu"], slots=[L, D], seasons=["winter", "cold"], not_seasons=["summer", "hot"],
     avoid=[("yinxu", None, "very warm"), ("shire", None, "very warm")],
     method_zh="羊肉切块焯水，与煮熟的鹰嘴豆、一枚草果同炖一个半小时，撇去浮油，少盐。",
     method_en="Blanch the diced lamb, stew with cooked chickpeas and a tsaoko pod for 1½ hours, skim the fat; little salt.",
     evidence=["yangrou_caoguo_effect", "yangrou_caoguo", "yangrou"], cautions=["yangrou_summer", "yangrou_sixth_month"], meat="lamb", purine_broth=True,
     notes=["The 饮膳正要 builds its court soups on this broth (with many more ingredients); here, only the broth and its chickpeas."])
dish("shanyao_niurou", "山药炖牛肉", "Beef stewed with Chinese yam", "soup", [("beef", 100), ("yam", 100), ("salt", 1)],
     nature="neutral", suits=["qixu", "pinghe"], slots=[L, D], seasons=["autumn", "winter"],
     method_zh="牛肉切块焯水，炖一小时后放入山药块再炖二十分钟，少盐。",
     method_en="Blanch the diced beef, stew an hour, add the yam and stew twenty minutes more; little salt.",
     evidence=["niurou", "shuyu"], cautions=["niurou_against"], meat="beef", beef=True, purine_broth=True,
     notes=["The 千金食治 commends beef (though not every day); the 食鉴本草 says not to eat the ox that ploughs the fields: both are given."])
dish("baicai_doufu_tang", "白菜豆腐汤", "Chinese cabbage and tofu soup", "soup", [("cabbage", 150), ("tofu", 100), ("salt", 1)],
     nature="neutral", suits=["pinghe", "shire", "yinxu"], slots=[L, D], seasons=["winter"],
     method_zh="白菜切段，与豆腐块同煮十分钟，少盐。",
     method_en="Simmer the cabbage and cubed tofu for ten minutes; a little salt.",
     evidence=["songcai", "qingcai_doufu"], allergens=["soy"])
dish("chao_tonghao", "清炒茼蒿", "Stir-fried garland chrysanthemum", "dish", [("garland", 150), ("oil", 5), ("salt", 1)],
     nature="neutral", suits=["qiyu", "tanshi", "pinghe"], slots=[L, D], seasons=["spring", "winter"],
     method_zh="茼蒿洗净，少油大火快炒，少盐。",
     method_en="Stir-fry the greens quickly in a little oil over high heat; a little salt.",
     evidence=["tonghao"], notes=["Garland chrysanthemum belongs to the daisy family: skip it with a ragweed or daisy allergy."])
dish("jicai_doufu_geng", "荠菜豆腐羹", "Shepherd's purse and tofu soup", "soup", [("shepherds_purse", 80), ("tofu", 100), ("salt", 1)],
     nature="neutral", suits=["qiyu", "pinghe"], slots=[L, D], seasons=["spring"],
     method_zh="荠菜焯水切碎，与豆腐丁同煮，少盐，可勾薄芡。",
     method_en="Blanch and chop the shepherd's purse, simmer with diced tofu; a little salt, lightly thickened if liked.",
     evidence=["jicai", "qingcai_doufu"], allergens=["soy"])
dish("xiancai_tang", "苋菜汤", "Amaranth soup", "soup", [("amaranth", 150), ("salt", 1)],
     nature="cold", suits=["shire"], slots=[L, D], seasons=["summer", "hot"], not_seasons=["winter", "cold"],
     avoid=[("yangxu", None, "very cold"), ("qixu", None, "very cold")],
     method_zh="苋菜洗净，水开后放入煮三五分钟，少盐。",
     method_en="Simmer the amaranth greens three to five minutes; a little salt.",
     evidence=["xiancai"], cautions=["xiancai_caution"])
dish("chunsun_tang", "春笋香菇汤", "Bamboo-shoot and shiitake soup", "soup", [("bamboo", 120), ("shiitake", 5), ("salt", 1)],
     nature="cool", suits=["tanshi", "shire"], slots=[L, D], seasons=["spring"],
     avoid=[("yangxu", "sun", "those with cold suffer from it")],
     method_zh="鲜笋切片焯水去涩，与泡发的香菇同煮十五分钟，少盐。",
     method_en="Slice and blanch the fresh shoots to remove bitterness, then simmer with soaked shiitake for 15 minutes; a little salt.",
     evidence=["sun"], notes=["Fresh bamboo shoots must be cooked through: raw, they contain a cyanide-releasing compound."])
dish("zheng_yutou", "蒸芋头", "Steamed taro", "dish", [("taro", 150)],
     nature="neutral", suits=["qixu", "pinghe"], slots=[A, L],
     avoid=[("yangxu", "yu", "it stirs old cold")],
     method_zh="芋头带皮蒸熟（一定要熟透），剥皮蘸少许酱油或白糖吃。",
     method_en="Steam the taro in its skin until fully cooked, then peel; eat plain or with a little soy sauce.",
     evidence=["yu"], notes=["Raw taro irritates the mouth and throat: always cook it through."])
dish("biqi_li_tang", "荸荠雪梨汤", "Water-chestnut and pear soup", "drink", [("water_chestnut", 80), ("pear", 150)],
     nature="cool", suits=["yinxu", "shire"], slots=[A], seasons=["autumn", "dry"],
     avoid=[("yangxu", "li_caution", "cool"), ("qixu", "li_caution", "the weak who eat many get diarrhoea")],
     method_zh="荸荠去皮、梨切块，加水煮二十分钟，连汤温食。不加糖。",
     method_en="Peel the water chestnuts, cut the pear, simmer 20 minutes; drink warm with the fruit. No sugar.",
     evidence=["wuyu", "biqi", "li"], cautions=["li_caution"], serving="1 bowl")
dish("wumei_tang", "乌梅汤", "Smoked-plum drink", "drink", [("wumei", 10), ("hawthorn", 5), ("sugar", 5)],
     nature="neutral", suits=["shire", "yinxu"], slots=[A], seasons=["summer", "hot"],
     method_zh="乌梅、山楂加水煮半小时，放凉至温热饮，糖可不放。",
     method_en="Simmer the smoked plums and hawthorn for half an hour; drink warm or cool (not iced). Sugar optional.",
     evidence=["meishi", "meizi"], serving="1 cup",
     notes=["Sour: skip with a stomach ulcer or acid reflux; rinse the mouth after (the texts warn of the teeth)."])
dish("oufen_geng", "藕粉羹", "Lotus-root starch pudding", "dessert", [("lotus_starch", 20), ("honey", 5)],
     nature="cool", suits=["xueyu", "yinxu"], slots=[B, A],
     method_zh="藕粉先用少许凉水调开，再用滚水冲成透明的羹，可加少许蜂蜜。宜早晨空腹。",
     method_en="Mix the starch with a little cold water, then pour on boiling water, stirring, until clear; a little honey if liked. Best on an empty stomach in the morning.",
     evidence=["oufen", "ou_raw"])
dish("lianzi_baihe_geng", "莲子百合羹", "Lotus-seed and lily-bulb soup", "dessert", [("lotus_seed", 20), ("lily", 10), ("honey", 5)],
     nature="neutral", suits=["yinxu", "qiyu", "qixu"], slots=[A, D], seasons=["autumn", "dry"],
     method_zh="莲子去心与干百合浸泡后同煮至酥烂，可加少许蜂蜜。",
     method_en="Soak the lotus seeds (germ removed) and dried lily bulb, simmer until soft; a little honey if liked.",
     evidence=["lianzi", "baihe"], cautions=["lianzi_raw"])
dish("fengmi_baihe", "蜂蜜蒸百合", "Steamed lily bulb with honey", "dessert", [("lily", 15), ("honey", 10)],
     nature="cool", suits=["yinxu", "qiyu"], slots=[A], seasons=["autumn", "dry"],
     avoid=[("yangxu", None, "cool and moistening")],
     method_zh="干百合泡软（或鲜百合掰瓣），隔水蒸十五分钟，淋上蜂蜜。",
     method_en="Soften dried lily bulb (or use fresh petals), steam 15 minutes and drizzle with honey.",
     evidence=["baihe_zheng", "baihe"], sweet=True)
dish("gegen_geng", "葛根粉羹", "Kudzu-starch pudding", "dessert", [("kudzu", 20), ("honey", 5)],
     nature="cool", suits=["shire", "yinxu"], slots=[A], seasons=["summer", "hot"],
     avoid=[("yangxu", None, "cool")],
     method_zh="葛根粉先用凉水调开，再用滚水冲成透明的羹，可加少许蜂蜜。",
     method_en="Mix the kudzu starch with cold water, then stir in boiling water until clear; a little honey if liked.",
     evidence=["gegen"])
dish("zheng_shibing", "蒸柿饼", "Steamed dried persimmon", "dessert", [("persimmon_dried", 40)],
     nature="cool", suits=["yinxu", "shire"], slots=[B, A], seasons=["autumn", "dry"],
     avoid=[("yangxu", "shi_caution", "it cools the middle"), ("qixu", "shi_caution", "it cools the middle")],
     method_zh="柿饼隔水蒸至极软，趁热吃，一次一个。不与螃蟹同食。",
     method_en="Steam the dried persimmon until very soft and eat it hot, one at a time. Never with crab.",
     evidence=["shibing"], cautions=["shi_caution"], sweet=True, serving="1 persimmon")
dish("gouqiye_dantang", "枸杞叶蛋花汤", "Goji-leaf and egg-drop soup", "soup", [("goji_leaf", 60), ("egg", 50), ("salt", 1)],
     nature="neutral", suits=["yinxu", "qixu", "pinghe"], slots=[L, D], seasons=["spring", "summer"],
     method_zh="水开后放入枸杞叶煮两分钟，淋入蛋液成蛋花，少盐。",
     method_en="Simmer the goji leaves two minutes, drizzle in the beaten egg; a little salt.",
     evidence=["gouqiye"], allergens=["egg"])
dish("damai_cha", "大麦茶", "Barley tea", "drink", [("barley", 15)],
     nature="cool", suits=["shire", "tanshi", "pinghe"], slots=[A, L], seasons=["summer", "hot"],
     method_zh="大麦炒至焦黄，加水煮十分钟，代茶温饮，不加糖。",
     method_en="Toast the barley golden, simmer ten minutes in water; drink warm instead of tea, unsweetened.",
     evidence=["damai_tang", "damai"], serving="1 cup", allergens=["wheat"],
     notes=["Barley contains gluten (the allergen marked is cereal gluten): not for coeliac disease. Strained, the tea carries far less energy than the grain counted."])
dish("donggua_yiyi_tang", "冬瓜薏米汤", "Winter melon and coix soup", "soup", [("waxgourd", 200), ("coix", 20), ("salt", 1)],
     nature="cool", suits=["tanshi", "shire"], slots=[L, D], seasons=["summer", "wet", "hot"],
     avoid=[("yinxu", "donggua_caution", "the 食鉴本草 says those with yin deficiency should not eat winter melon"), ("yangxu", None, "cool")],
     method_zh="薏苡仁先煮半小时，再放冬瓜（连皮）煮二十分钟，少盐。",
     method_en="Simmer the coix half an hour, add the winter melon (skin on) and simmer twenty minutes; little salt.",
     evidence=["donggua", "yiyi"], cautions=["donggua_caution"])
dish("zheng_shanyao", "蒸山药", "Steamed Chinese yam", "dish", [("yam", 150), ("honey", 5)],
     nature="neutral", suits=["qixu", "pinghe", "tebing"], slots=[B, A],
     method_zh="山药去皮切段，隔水蒸二十分钟，可淋少许蜂蜜。",
     method_en="Peel and cut the yam, steam twenty minutes; a little honey if liked.",
     evidence=["shuyu", "shanyao_cool"], notes=["Raw Chinese yam can itch on the hands: wear gloves to peel it."])
dish("liangban_machixian", "凉拌马齿苋", "Purslane with ginger and vinegar", "dish", [("purslane", 150), ("ginger", 3), ("salt", 1)],
     nature="cold", suits=["shire"], slots=[L], seasons=["summer", "hot"], not_seasons=["winter", "cold"],
     avoid=[("qixu", None, "cold"), ("yangxu", None, "cold")],
     method_zh="马齿苋焯水，拌姜末、少许醋与盐。",
     method_en="Blanch the purslane and dress it with minced ginger, a little vinegar and salt.",
     evidence=["machixian_geng", "machixian"])
dish("ganzhe_zhou", "甘蔗粥", "Sugar-cane congee", "congee", [("sugarcane", 100), ("rice", 40)],
     nature="cool", suits=["yinxu"], slots=[B], seasons=["autumn", "dry"],
     avoid=[("tanshi", None, "very sweet")],
     method_zh="甘蔗榨汁，与粳米同煮成粥。宜早晨空腹。",
     method_en="Juice the sugar cane and cook it with the rice into congee. Best first thing in the morning.",
     evidence=["ganzhe_zhou", "ganzhe"], sweet=True)

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
