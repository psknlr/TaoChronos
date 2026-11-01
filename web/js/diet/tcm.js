// The traditional layer, optional and non-diagnostic: the natures of everyday foods (寒/凉/平/温/热) as Chinese
// dietetics and Singapore's "heaty" (热气) / "cooling" (凉) food culture describe them — only foods on which common
// references agree; those on which they disagree are said to — and how two short preference answers (how one feels
// after a meal, which food style one likes) shape food choices.  Nothing here diagnoses a pattern or constitution
// (证型、体质): two questions cannot, and the result says so (`tcm_pattern_status: "unconfirmed"`).  Ordinary foods only:
// no herbs, tonics, medicinal soups or formulas, and no claim that a food burns fat or removes "dampness".

import { ALGORITHM, provenance } from "./sources.js";

// [food, 中文, nature, the everyday Singapore word when there is one]
const NATURES = [
  ["watermelon", "西瓜", "cold", "cooling"], ["pear", "梨", "cool", "cooling"], ["banana", "香蕉", "cold", null],
  ["star fruit", "杨桃", "cold", "cooling"], ["mangosteen", "山竹", "cold", "cooling"], ["sugarcane juice", "甘蔗汁", "cool", "cooling"],
  ["coconut water", "椰子水", "cool", "cooling"], ["cucumber", "黄瓜", "cool", "cooling"], ["bitter gourd", "苦瓜", "cold", "cooling"],
  ["winter melon", "冬瓜", "cool", "cooling"], ["kangkong (water spinach)", "蕹菜", "cold", null], ["lettuce", "生菜", "cool", null],
  ["seaweed / kelp", "海带", "cold", null], ["tofu", "豆腐", "cool", null], ["mung bean", "绿豆", "cool", "cooling"],
  ["barley (barley water, unsweetened)", "薏米 / 大麦", "cool", "cooling"], ["chrysanthemum tea (unsweetened)", "菊花茶", "cool", "cooling"],
  ["grass jelly", "仙草", "cool", "cooling"], ["crab", "蟹", "cold", null],
  ["rice", "粳米", "neutral", null], ["sweet potato", "番薯", "neutral", null], ["corn", "玉米", "neutral", null],
  ["soybean / soya milk", "黄豆 / 豆浆", "neutral", null], ["egg", "鸡蛋", "neutral", null], ["pork", "猪肉", "neutral", null],
  ["carrot", "胡萝卜", "neutral", null], ["papaya", "木瓜", "neutral", null], ["shiitake mushroom", "香菇", "neutral", null],
  ["black fungus", "黑木耳", "neutral", null],
  ["ginger", "生姜", "warm", null], ["garlic", "大蒜", "warm", null], ["spring onion", "葱", "warm", null], ["chicken", "鸡肉", "warm", null],
  ["mutton / lamb", "羊肉", "warm", "heaty"], ["prawn", "虾", "warm", null], ["glutinous rice", "糯米", "warm", null],
  ["red dates", "红枣", "warm", null], ["longan", "龙眼", "warm", "heaty"], ["lychee", "荔枝", "warm", "heaty"],
  ["rambutan", "红毛丹", "warm", "heaty"], ["durian", "榴莲", "hot", "heaty"], ["chilli", "辣椒", "hot", "heaty"],
  ["black pepper", "胡椒", "hot", null], ["cinnamon", "肉桂", "hot", null],
];
// the everyday culture adds: deep-fried, grilled and very spicy foods are "heaty"; herbal teas and soups are "cooling"
const DISAGREE = [
  ["mango", "芒果", "called 'heaty' in everyday Singapore usage, but cool or neutral in Chinese dietetics references"],
  ["apple", "苹果", "cool in some references, neutral in others"],
  ["beef", "牛肉", "neutral or warm depending on the reference (and on the kind of cattle in older texts)"],
  ["lotus root", "莲藕", "cold when raw, neutral or warm when cooked"],
  ["coffee / kopi", "咖啡", "not in the classical materia medica; called 'heaty' by many, but references differ"],
];
const NATURE_WORDS = { cold: "cold (寒)", cool: "cool (凉)", neutral: "neutral (平)", warm: "warm (温)", hot: "hot (热)" };

const fold = (s) => String(s || "").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();
const keys = (en, zh) => [...en.split("(")[0].split("/"), ...zh.split("/")].map(fold).filter(Boolean);
const cjk = (s) => /\p{Script=Han}/u.test(s);
/** Whether the words `a` hold the words `b` (whole words; Chinese by its characters). */
const holds = (a, b) => (cjk(b) ? a.includes(b) : ` ${a} `.includes(` ${b} `));
const matches = (asked, en, zh) => keys(en, zh).some((k) => holds(asked, k) || holds(k, asked));

/** The natures of the foods asked for (each by any of its English or Chinese names), and those the references disagree on. */
export function natures(foods = []) {
  const asked = (Array.isArray(foods) ? foods : [foods]).map(fold).filter(Boolean);
  const pick = (rows) => rows.filter(([en, zh]) => !asked.length || asked.some((a) => matches(a, en, zh)));
  const found = pick(NATURES).map(([food, zh, nature, local]) => ({ food, zh, nature: NATURE_WORDS[nature], everyday: local || undefined }));
  const disputed = pick(DISAGREE).map(([food, zh, note]) => ({ food, zh, references_disagree: note }));
  const unknown = asked.filter((a) => ![...NATURES, ...DISAGREE].some(([en, zh]) => matches(a, en, zh)));
  return { found, disputed, unknown };
}

const AFTER = {
  hungry_soon: ["Hungry again soon after meals: build each meal around protein and fibre — egg, tofu, fish or lean meat, a vegetable side, brown rice or wholemeal — and swap sweet drinks, which digest fast, for water or kopi-O/teh-O kosong."],
  bloated: ["Often bloated: smaller portions eaten slowly; cooked rather than large raw portions of vegetables; fewer fried and oily dishes and fizzy drinks.",
    "If bloating is frequent, or comes with pain, weight loss, vomiting or a change in bowel habits, see a doctor."],
  comfortable: [],
  unsure: [],
};
const STYLE = {
  warm_cooked: { advice: ["You prefer warm, cooked food: soups (sliced fish, ABC soup, tofu and vegetable soup), steamed fish, stir-fried or blanched vegetables; ginger and spring onion as seasoning; fewer iced drinks.",
    "In the traditional view such warm, cooked foods suit those who like warmth; within the plan they change the style, not the amount."], prefer: ["soup", "steamed", "cooked"], avoid: ["iced"] },
  light_cool: { advice: ["You prefer lighter, cooling food: steamed and soup dishes, plenty of vegetables (cucumber, winter melon, bitter gourd, kangkong), fruit such as watermelon, pear or star fruit; fewer deep-fried, very spicy or 'heaty' foods (durian, fried snacks).",
    "Unsweetened barley or chrysanthemum drinks are 'cooling' in everyday terms; sweetened, they add sugar."], prefer: ["soup", "steamed"], avoid: ["fried", "spicy", "heaty"] },
  dry_mouth: { advice: ["A dry mouth: drink water through the day, add soups and fruit, and cut down fried, very spicy and salty foods and alcohol.",
    "A dry mouth that persists, especially with strong thirst or passing more urine, should be checked by a doctor: it can be a sign of high blood sugar."], prefer: ["soup", "steamed"], avoid: ["fried", "spicy"] },
  no_preference: { advice: [], prefer: [], avoid: [] },
};

/** How the preference answers shape food choices: advice, and the dish styles a plan leans towards or away from. */
export function preference({ after_meal = null, food_style = null } = {}) {
  const style = STYLE[food_style] || STYLE.no_preference;
  return {
    advice: [...(AFTER[after_meal] || []), ...style.advice],
    prefer: style.prefer, avoid: style.avoid,
    tcm_pattern_status: "unconfirmed",
    boundary: "These are food-preference clues, not a TCM diagnosis: a pattern or constitution (e.g. 痰湿、脾虚) cannot be judged from two questions. For one, see a TCM practitioner registered with Singapore's TCM Practitioners Board. Herbs, tonics and medicinal soups are outside this plan, especially in pregnancy or alongside medicines.",
  };
}

/** The tool: the natures of foods and/or what the preference answers mean. */
export function foodNature({ foods = [], after_meal = null, food_style = null } = {}) {
  const n = natures(foods);
  const out = { ok: true, algorithm: ALGORITHM, ...n, preference: (after_meal || food_style) ? preference({ after_meal, food_style }) : undefined,
    everyday_rule: "In everyday Singapore usage deep-fried, grilled and very spicy foods are also called 'heaty'.",
    use: "Natures describe a traditional way of choosing food; they are not evidence that a food treats a condition or helps weight loss. The nutrition plan's numbers stay as they are.",
    tcm_pattern_status: "unconfirmed",
    provenance: provenance(["tcm_food_nature"]) };
  if (!foods?.length) delete out.unknown;
  return out;
}
