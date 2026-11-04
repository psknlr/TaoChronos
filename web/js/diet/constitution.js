// The nine constitutions of Chinese medicine (中医体质), scored as the published standard scores them: 中华中医药学会
// ZYYXH/T157-2009《中医体质分类与判定》, the Constitution in Chinese Medicine Questionnaire (CCMQ, 王琦 et al.).
// Sixty questions, each answered for the past year on a five-point scale; a type's raw score is the sum of its items,
// its transformed score (转化分) (raw − n) / (4n) × 100, and the judgement the standard's thresholds.  Nothing is
// estimated: a type is judged only when every one of its items has an answer.  In 2026 the association standard was
// superseded by a national one, GB/T 46939—2025 (27 questions, its own scoring), whose text was not available: this
// is the 2009 questionnaire, widely published and validated, and its result is labelled as such.  A constitution is a tendency of the body
// for health care (养生), not a diagnosis of a disease or of a pattern (证); a registered practitioner judges those.

import { ALGORITHM, provenance } from "./sources.js";

export const TYPES = ["pinghe", "qixu", "yangxu", "yinxu", "tanshi", "shire", "xueyu", "qiyu", "tebing"];
export const TYPE_NAMES = {
  pinghe: ["平和质", "Balanced"], qixu: ["气虚质", "Qi deficiency"], yangxu: ["阳虚质", "Yang deficiency"],
  yinxu: ["阴虚质", "Yin deficiency"], tanshi: ["痰湿质", "Phlegm-dampness"], shire: ["湿热质", "Damp-heat"],
  xueyu: ["血瘀质", "Blood stasis"], qiyu: ["气郁质", "Qi stagnation"], tebing: ["特禀质", "Inherited special (allergic)"],
};

// The answer scale: the standard's two wordings of each point (frequency, degree).
export const SCALE = [
  [1, "没有（根本不）", "Never (not at all)"], [2, "很少（有一点）", "Rarely (a little)"], [3, "有时（有些）", "Sometimes (somewhat)"],
  [4, "经常（相当）", "Often (quite)"], [5, "总是（非常）", "Always (very)"],
];
export const TIMEFRAME = ["请根据近一年的体验和感觉回答", "Answer for how you have felt over the past year"];

// The items, each once ([id, 中文, English, who answers it]); an item shared by two types is asked once and scored in both.
export const ITEMS = [
  ["energetic", "您精力充沛吗？", "Are you full of energy?"],
  ["tired", "您容易疲乏吗？", "Do you tire easily?"],
  ["short_breath", "您容易气短（呼吸短促，接不上气）吗？", "Do you easily get short of breath (breathing fast, unable to catch your breath)?"],
  ["palpitations", "您容易心慌吗？", "Do you easily get palpitations?"],
  ["dizzy", "您容易头晕或站起时晕眩吗？", "Do you easily feel dizzy, or light-headed when you stand up?"],
  ["colds", "您比别人容易患感冒吗？", "Do you catch colds more easily than others?"],
  ["quiet", "您喜欢安静、懒得说话吗？", "Do you prefer quiet and find talking an effort?"],
  ["weak_voice", "您说话声音低弱无力吗？", "Is your voice low and weak?"],
  ["sweat_exertion", "您活动量稍大就容易出虚汗吗？", "Do you sweat easily on slight exertion?"],
  ["cold_limbs", "您手脚发凉吗？", "Are your hands and feet cold?"],
  ["cold_back", "您胃脘部、背部或腰膝部怕冷吗？", "Do your stomach area, back, or lower back and knees feel the cold?"],
  ["feel_cold", "您感到怕冷、衣服比别人穿得多吗？", "Do you feel the cold and wear more clothes than others?"],
  ["cold_intolerant", "您比一般人耐受不了寒冷（冬天的寒冷，夏天的冷空调、电扇等）吗？", "Do you tolerate cold less well than most people (winter cold, air-conditioning or fans in summer)?"],
  ["cold_food_discomfort", "您吃（喝）凉的东西会感到不舒服或者怕吃（喝）凉的东西吗？", "Does cold food or drink make you uncomfortable, or do you avoid it?"],
  ["cold_diarrhoea", "您受凉或吃（喝）凉的东西后，容易腹泻（拉肚子）吗？", "Do you easily get diarrhoea after getting cold or eating or drinking something cold?"],
  ["hot_palms", "您感到手脚心发热吗？", "Do the palms of your hands and soles of your feet feel hot?"],
  ["hot_face", "您感觉身体、脸上发热吗？", "Do your body or face feel hot?"],
  ["dry_skin", "您皮肤或口唇干吗？", "Is your skin or are your lips dry?"],
  ["red_lips", "您口唇的颜色比一般人红吗？", "Are your lips redder than most people's?"],
  ["constipation", "您容易便秘或大便干燥吗？", "Do you easily become constipated, or are your stools dry?"],
  ["flushed_cheeks", "您面部两颧潮红或偏红吗？", "Are your cheeks flushed or reddish?"],
  ["dry_eyes", "您感到眼睛干涩吗？", "Do your eyes feel dry?"],
  ["dry_mouth", "您感到口干咽燥、总想喝水吗？", "Do your mouth and throat feel dry, so that you always want to drink?"],
  ["chest_fullness", "您感到胸闷或腹部胀满吗？", "Do you feel tightness in the chest or fullness in the abdomen?"],
  ["heavy_body", "您感到身体沉重不轻松或不爽快吗？", "Does your body feel heavy, not light or refreshed?"],
  ["soft_belly", "您腹部肥满松软吗？", "Is your abdomen large and soft?"],
  ["oily_forehead", "您有额部油脂分泌多的现象吗？", "Is your forehead oily?"],
  ["puffy_eyelids", "您上眼睑比别人肿（上眼睑有轻微隆起的现象）吗？", "Are your upper eyelids puffier than others' (slightly raised)?"],
  ["sticky_mouth", "您嘴里有黏黏的感觉吗？", "Does your mouth feel sticky?"],
  ["phlegm", "您平时痰多，特别是咽喉部总感到有痰堵着吗？", "Do you usually have a lot of phlegm, especially a feeling of phlegm stuck in the throat?"],
  ["thick_coating", "您舌苔厚腻或有舌苔厚厚的感觉吗？", "Is your tongue coating thick and greasy, or does it feel thick?"],
  ["oily_face", "您面部或鼻部有油腻感或者油亮发光吗？", "Are your face or nose greasy or shiny?"],
  ["acne", "您容易生痤疮或疮疖吗？", "Do you easily get acne or boils?"],
  ["bitter_mouth", "您感到口苦或嘴里有异味吗？", "Do you have a bitter or bad taste in your mouth?"],
  ["sticky_stool", "您大便黏滞不爽、有解不尽的感觉吗？", "Are your stools sticky, with a feeling of not having finished?"],
  ["hot_urine", "您小便时尿道有发热感、尿色浓（深）吗？", "Does passing urine feel hot, with dark urine?"],
  ["yellow_discharge", "您带下色黄（白带颜色发黄）吗？（限女性回答）", "Is your vaginal discharge yellowish? (women only)", "female"],
  ["damp_scrotum", "您的阴囊部位潮湿吗？（限男性回答）", "Is your scrotum damp? (men only)", "male"],
  ["bruises", "您的皮肤在不知不觉中会出现青紫瘀斑（皮下出血）吗？", "Do bruises (bleeding under the skin) appear without your knowing why?"],
  ["red_threads", "您两颧部有细微红丝吗？", "Do you have fine red threads on your cheeks?"],
  ["pain", "您身体上有哪里疼痛吗？", "Do you have pain anywhere in your body?"],
  ["dark_face", "您面色晦黯或容易出现褐斑吗？", "Is your complexion dull and dark, or do you easily get brown spots?"],
  ["dark_circles", "您容易有黑眼圈吗？", "Do you easily get dark circles under your eyes?"],
  ["forgetful", "您容易忘事（健忘）吗？", "Are you forgetful?"],
  ["dark_lips", "您口唇颜色偏黯吗？", "Are your lips darkish?"],
  ["low_mood", "您感到闷闷不乐、情绪低沉吗？", "Do you feel unhappy or low in mood?"],
  ["tense", "您容易精神紧张、焦虑不安吗？", "Do you easily become tense or anxious?"],
  ["sensitive", "您多愁善感、感情脆弱吗？", "Are you prone to melancholy and emotionally fragile?"],
  ["frightened", "您容易感到害怕或受到惊吓吗？", "Are you easily afraid or startled?"],
  ["rib_breast_pain", "您胁肋部或乳房胀痛吗？", "Do you have distending pain in your sides (below the ribs) or breasts?"],
  ["sighing", "您无缘无故叹气吗？", "Do you sigh for no reason?"],
  ["throat_lump", "您咽喉部有异物感，且吐之不出、咽之不下吗？", "Do you feel something stuck in your throat that you can neither cough up nor swallow?"],
  ["sneeze", "您没有感冒时也会打喷嚏吗？", "Do you sneeze even when you don't have a cold?"],
  ["stuffy_nose", "您没有感冒时也会鼻塞、流鼻涕吗？", "Is your nose blocked or runny even when you don't have a cold?"],
  ["wheeze", "您有因季节变化、温度变化或异味等原因而咳喘的现象吗？", "Do you cough or wheeze with changes of season or temperature, or with odours?"],
  ["allergic", "您容易过敏（对药物、食物、气味、花粉或在季节交替、气候变化时）吗？", "Are you prone to allergies (to medicines, foods, smells or pollen, or when seasons or weather change)?"],
  ["hives", "您的皮肤容易起荨麻疹（风团、风疹块、风疙瘩）吗？", "Does your skin easily come out in hives (wheals)?"],
  ["purpura", "您的皮肤因过敏出现过紫癜（紫红色瘀点、瘀斑）吗？", "Has your skin ever had purpura (purple-red spots or patches) from an allergy?"],
  ["dermographism", "您的皮肤一抓就红，并出现抓痕吗？", "Does your skin go red and show the marks when scratched?"],
  ["adaptable", "您能适应外界自然和社会环境的变化吗？", "Can you adapt to changes in your natural and social surroundings?"],
  ["insomnia", "您容易失眠吗？", "Do you have trouble sleeping?"],
].map(([id, zh, en, sex = null]) => ({ id, zh, en, ...(sex ? { sex } : {}) }));
const ITEM = Object.fromEntries(ITEMS.map((i) => [i.id, i]));

// Each type's items in the standard's order; "-id" is scored in reverse (平和质's negative items).
export const TYPE_ITEMS = {
  yangxu: ["cold_limbs", "cold_back", "feel_cold", "cold_intolerant", "colds", "cold_food_discomfort", "cold_diarrhoea"],
  yinxu: ["hot_palms", "hot_face", "dry_skin", "red_lips", "constipation", "flushed_cheeks", "dry_eyes", "dry_mouth"],
  qixu: ["tired", "short_breath", "palpitations", "dizzy", "colds", "quiet", "weak_voice", "sweat_exertion"],
  tanshi: ["chest_fullness", "heavy_body", "soft_belly", "oily_forehead", "puffy_eyelids", "sticky_mouth", "phlegm", "thick_coating"],
  shire: ["oily_face", "acne", "bitter_mouth", "sticky_stool", "hot_urine", "yellow_discharge", "damp_scrotum"],
  xueyu: ["bruises", "red_threads", "pain", "dark_face", "dark_circles", "forgetful", "dark_lips"],
  qiyu: ["low_mood", "tense", "sensitive", "frightened", "rib_breast_pain", "sighing", "throat_lump"],
  tebing: ["sneeze", "stuffy_nose", "wheeze", "allergic", "hives", "purpura", "dermographism"],
  pinghe: ["energetic", "-tired", "-weak_voice", "-low_mood", "-cold_intolerant", "adaptable", "-insomnia", "-forgetful"],
};

/** The items a person of `sex` answers ("female", "male", or anything else: neither sex-specific item), in asking order. */
export function itemsFor(sex = null) {
  return ITEMS.filter((i) => !i.sex || i.sex === sex);
}

const JUDGE = { yes: ["是", "yes"], basically: ["基本是", "basically yes"], tendency: ["倾向是", "tendency"], no: ["否", "no"] };

/** Scores answers ({item id: 1–5}) as the standard does.  A type is judged only when all its items (for this sex) are answered. */
export function score(answers = {}, sex = null) {
  const value = (id) => { const v = Number(answers?.[id]); return Number.isInteger(v) && v >= 1 && v <= 5 ? v : null; };
  const out = {};
  for (const t of TYPES) {
    const ids = TYPE_ITEMS[t].filter((x) => { const i = ITEM[x.replace(/^-/, "")]; return !i.sex || i.sex === sex; });
    const vals = ids.map((x) => { const v = value(x.replace(/^-/, "")); return v == null ? null : x.startsWith("-") ? 6 - v : v; });
    const answered = vals.filter((v) => v != null).length;
    if (answered < ids.length) { out[t] = { items: ids.length, answered, raw: null, transformed: null }; continue; }
    const raw = vals.reduce((a, b) => a + b, 0);
    out[t] = { items: ids.length, answered, raw, transformed: Math.round(((raw - ids.length) / (ids.length * 4)) * 1000) / 10 };
  }
  return out;
}

/** The standard's judgements: 平和质 是 / 基本是 / 否; each other type 是 (≥40) / 倾向是 (30–39) / 否 (<30). */
export function judge(scores) {
  const others = TYPES.filter((t) => t !== "pinghe");
  const res = {};
  for (const t of others) {
    const s = scores[t]?.transformed;
    res[t] = s == null ? null : s >= 40 ? "yes" : s >= 30 ? "tendency" : "no";
  }
  const p = scores.pinghe?.transformed;
  const all = others.every((t) => scores[t]?.transformed != null);
  if (p == null || !all) res.pinghe = null;
  else if (p >= 60 && others.every((t) => scores[t].transformed < 30)) res.pinghe = "yes";
  else if (p >= 60 && others.every((t) => scores[t].transformed < 40)) res.pinghe = "basically";
  else res.pinghe = "no";
  return res;
}

/** The tool: scores the answers and says what the result is (primary types, tendencies) and is not. */
export function constitution({ answers = {}, sex = null } = {}) {
  const sx = sex === "female" || sex === "male" ? sex : null;
  const scores = score(answers, sx);
  const judgement = judge(scores);
  const asked = itemsFor(sx);
  const missing = asked.filter((i) => !(Number(answers?.[i.id]) >= 1 && Number(answers?.[i.id]) <= 5)).map((i) => i.id);
  const named = (t) => ({ type: t, zh: TYPE_NAMES[t][0], en: TYPE_NAMES[t][1], transformed: scores[t].transformed, judgement: judgement[t],
    judgement_zh: judgement[t] ? JUDGE[judgement[t]][0] : null });
  const biased = TYPES.filter((t) => t !== "pinghe" && judgement[t]).sort((a, b) => scores[b].transformed - scores[a].transformed);
  const primary = biased.filter((t) => judgement[t] === "yes");
  const tendency = biased.filter((t) => judgement[t] === "tendency");
  const balanced = judgement.pinghe === "yes" || judgement.pinghe === "basically";
  return {
    ok: true, algorithm: ALGORITHM,
    status: missing.length ? (missing.length === asked.length ? "not_started" : "partial") : "complete",
    answered: asked.length - missing.length, of: asked.length,
    ...(missing.length && missing.length < asked.length ? { unanswered: missing } : {}),
    ...(sx ? {} : { sex_note: "Sex not given: the two sex-specific 湿热质 items are left out, so 湿热质 is scored on its other five." }),
    types: TYPES.filter((t) => scores[t].transformed != null).map(named),
    result: {
      balanced: judgement.pinghe ? { judgement: judgement.pinghe, judgement_zh: JUDGE[judgement.pinghe][0] } : null,
      primary, tendency,
      summary: !TYPES.some((t) => judgement[t]) ? "Not enough answers to judge any type."
        : balanced && !primary.length ? `平和质 (${JUDGE[judgement.pinghe][0]})${tendency.length ? `, with tendencies to ${tendency.map((t) => TYPE_NAMES[t][0]).join("、")}` : ""}`
          : primary.length ? `${primary.map((t) => TYPE_NAMES[t][0]).join("、")}${tendency.length ? `; tendencies: ${tendency.map((t) => TYPE_NAMES[t][0]).join("、")}` : ""}`
            : tendency.length ? `Tendencies: ${tendency.map((t) => TYPE_NAMES[t][0]).join("、")}` : "No biased type reached the standard's thresholds.",
    },
    standard: "ZYYXH/T157-2009, the 60-question CCMQ. Superseded in 2026 by the national standard GB/T 46939—2025 (27 questions), whose text was not available here: read the result as indicative.",
    thresholds: "平和质: 是 = its score ≥60 and every other type <30; 基本是 = ≥60 and every other <40. Other types: 是 ≥40, 倾向是 30–39, 否 <30 (transformed scores, 0–100).",
    boundary: "A constitution is a self-reported tendency used for health care (养生) in Chinese medicine, scored by the published questionnaire. It is not a diagnosis of any disease or of a TCM pattern (证), and it changes over time; a registered TCM practitioner can assess it in person. Symptoms in the answers (pain, bruising, palpitations, low mood, breathlessness, dark urine) can have medical causes worth checking with a doctor.",
    provenance: provenance(["ccmq"]),
  };
}
