// Medicinal dishes (药膳) for health care (养生): which of the dishes in medicinal-data.js suit this person, now — by the
// constitution the published questionnaire (or a registered practitioner) found, the season and climate where they
// live, and the time of day — after a safety screen, with each dish's nutrition per serving (USDA FoodData Central) and
// the classical passages it rests on (checked against the corpus when the data are built).  Every rule is in this file
// and every exclusion is said, with the passage when a classic is the reason.
//
// The ingredients are everyday foods and substances on China's list of things that are both food and traditional
// medicine (按照传统既是食品又是中药材的物质目录), in recipe amounts.  What this gives is traditional food care: not a
// treatment for any disease, not a substitute for medical care, and not evidence that a dish changes a constitution.

import { DISHES, FOODS, QUOTES } from "./medicinal-data.js";
import { context } from "./context.js";
import { limits } from "./energy.js";
import { region as regionOf } from "./regions.js";
import { TYPES, TYPE_NAMES } from "./constitution.js";
import { ALGORITHM, provenance } from "./sources.js";

export const SLOTS = ["breakfast", "lunch", "afternoon", "dinner"];
export const MEDICINES = ["none", "anticoagulant", "immunosuppressant", "diabetes_medicine", "other", "unsure"];

// what a season or climate phase means in the traditional terms the dishes are annotated with
const QUALITIES = {
  spring: ["spring"], summer: ["summer", "hot"], autumn: ["autumn", "dry"], winter: ["winter", "cold"],
  tropical: ["hot", "wet"], northeast_monsoon_wet: ["wet"], northeast_monsoon_dry: ["hot"], inter_monsoon_1: ["hot", "wet"],
  inter_monsoon_2: ["hot", "wet"], southwest_monsoon: ["hot", "wet"], pre_monsoon: ["hot", "dry"], post_monsoon: ["hot"],
};
const QUALITY_WORDS = { spring: "spring", summer: "summer", autumn: "autumn", winter: "winter", hot: "heat", wet: "damp", dry: "dryness", cold: "cold" };

// answers that mean no medicinal dish is suggested at all: what to say instead
const NOT_OFFERED = {
  pregnant: "Pregnancy: no medicinal dishes are suggested. Several of their substances carry traditional cautions in pregnancy, and the newer ones on China's list are labelled as not advised for pregnant women. Ordinary meals, and the advice of your doctor or midwife, apply.",
  breastfeeding: "Breastfeeding: no medicinal dishes are suggested (the newer substances on China's list are labelled as not advised while breastfeeding). Ordinary meals apply; ask your doctor or midwife before any herbal food.",
  kidney_disease: "Kidney disease: no medicinal dishes are suggested — several are high in potassium, and herbs need your renal team's review.",
  eating_disorder: "With an eating disorder, now or in the past, food is best planned with your care team; no medicinal dishes are suggested here.",
  unexplained_weight_loss: "Unexplained weight loss needs a doctor's assessment first; no medicinal dishes are suggested.",
};
const ASK = {
  conditions: { question: "Before suggesting medicinal dishes: are you pregnant or breastfeeding, or do you have kidney disease, diabetes, gout, an eating disorder, or a food allergy?",
    options: ["None of these", "Pregnant or breastfeeding", "Kidney disease", "Diabetes", "Gout", "Eating disorder", "Food allergy", "Not sure"],
    why: "some answers rule medicinal dishes out, others rule out particular dishes" },
  medicines: { question: "Do you take any regular medicines — especially a blood thinner (such as warfarin), an immunosuppressant, or a diabetes medicine?",
    options: ["None", "Blood thinner (e.g. warfarin)", "Immunosuppressant", "Diabetes medicine", "Other medicines", "Not sure"],
    why: "goji and dang gui can strengthen warfarin's effect; astragalus may work against immunosuppressants" },
  allergies: { question: "Which foods are you allergic to?", options: ["Tree nuts", "Sesame", "Milk", "Egg", "Other", "None"],
    why: "a dish with an allergen is left out" },
};

const has = (list, x) => Array.isArray(list) && list.includes(x);
const known = (list) => Array.isArray(list) && list.length > 0;
const qref = (id) => { const q = QUOTES[id]; return q ? { passage_id: q.passage_id, work: q.work, chapter: q.chapter || undefined, quote: q.text, says: q.gloss } : null; };
const name = (t) => `${TYPE_NAMES[t][0]} (${TYPE_NAMES[t][1]})`;

/** The local hour (0–23) in `tz` at `now`. */
function hourIn(tz, now) {
  try { return Number(new Intl.DateTimeFormat("en-GB", { timeZone: tz || undefined, hour: "numeric", hourCycle: "h23" }).format(now)); }
  catch { return now.getHours(); }
}
/** The meal slot of an hour: breakfast 5–10, lunch 10–14, afternoon 14–17, dinner 17–21, late 21–5. */
export function slotOf(hour) {
  return hour >= 5 && hour < 10 ? "breakfast" : hour < 14 && hour >= 10 ? "lunch" : hour < 17 && hour >= 14 ? "afternoon" : hour < 21 && hour >= 17 ? "dinner" : "late";
}

/** The person's constitution as given: types judged 是 (primary) and 倾向是 (tendency), and where it came from. */
function readConstitution(c) {
  const ok = (list) => (Array.isArray(list) ? list : []).filter((t) => TYPES.includes(t));
  const primary = ok(c?.primary);
  const tendency = ok(c?.tendency).filter((t) => !primary.includes(t));
  const source = ["questionnaire", "practitioner", "self_described"].includes(c?.source) ? c.source : (primary.length || tendency.length ? "self_described" : "unknown");
  const biased = [...primary, ...tendency].filter((t) => t !== "pinghe");
  return { primary, tendency, source, biased, balanced: !biased.length && (primary.includes("pinghe") || source !== "unknown") };
}

/** Why a dish is out for this person now (the first reason found), or null. */
function exclusion(d, who, now, slot) {
  const { allergies, diet, meds, conditions } = who;
  const hit = d.allergens.find((a) => has(allergies, a));
  if (hit) return { code: "allergen", allergen: hit, why: `contains ${hit.replace("_", " ")}` };
  if (d.meat && (has(diet, "vegetarian") || has(diet, "vegan"))) return { code: "diet", why: `contains ${d.meat}` };
  if (has(diet, "vegan") && d.allergens.some((a) => a === "milk" || a === "egg")) return { code: "diet", why: "contains milk or egg" };
  if (d.pork && (has(diet, "halal") || has(diet, "no_pork"))) return { code: "diet", why: "contains pork" };
  if (meds.anticoagulant && d.herbs.some((h) => h === "goji" || h === "danggui")) {
    return { code: "medicine", why: `${d.herbs.includes("danggui") ? "dang gui" : "goji"} can strengthen the effect of warfarin (case reports): not with a blood thinner` };
  }
  if (meds.immunosuppressant && d.herbs.includes("huangqi")) return { code: "medicine", why: "astragalus may work against immunosuppressants" };
  if ((meds.other || meds.unsure) && d.herbs.length) return { code: "medicine", why: `has ${d.herbs.map((h) => FOODS[h].en).join(", ")}: ask a pharmacist whether it suits your medicines first` };
  if (has(conditions, "gout") && d.purine_broth) return { code: "condition", why: "a long-simmered meat broth, rich in purines: not with gout" };
  for (const t of who.c.biased) {
    const a = d.avoid.find((x) => x.type === t);
    if (a) return { code: "constitution", type: t, why: `${name(t)}: ${a.why}`, quote: a.quote ? qref(a.quote) : undefined };
    if (t === "yangxu" && d.nature === "cold") return { code: "constitution", type: t, why: `${name(t)}: a cold dish` };
    if ((t === "yinxu" || t === "shire") && d.nature === "hot") return { code: "constitution", type: t, why: `${name(t)}: a hot dish` };
  }
  const off = d.not_seasons.find((q) => now.qualities.includes(q));
  if (off) {
    const q = [...d.cautions, ...d.evidence].find((id) => QUOTES[id]?.kind === "season");
    return { code: "season", quality: off, why: `not in ${QUALITY_WORDS[off]}`, quote: q ? qref(q) : undefined };
  }
  if (slot && d.not_slots.includes(slot)) {
    return { code: "time", why: "ginger is for the morning or midday, not the evening", quote: qref("no_night_ginger") };
  }
  return null;
}

/** How well a dish fits: constitution first, then the season, with the reasons. */
function fit(d, who, now) {
  let score = 0;
  const why = [], fits = [];
  for (const t of who.c.primary) if (d.suits.includes(t)) { score += 3; why.push(`suits ${name(t)}`); fits.push({ kind: "constitution", type: t, level: "primary" }); }
  for (const t of who.c.tendency) if (d.suits.includes(t)) { score += 1.5; why.push(`suits a tendency to ${name(t)}`); fits.push({ kind: "constitution", type: t, level: "tendency" }); }
  if (!who.c.biased.length && (d.suits.includes("pinghe") || d.nature === "neutral")) {
    score += 1; why.push(who.c.balanced ? "mild, for a balanced constitution" : "mild, for any constitution"); fits.push({ kind: "mild" });
  }
  const match = d.seasons.filter((q) => now.qualities.includes(q));
  if (match.length) { score += 2; why.push(`in season (${match.map((q) => QUALITY_WORDS[q]).join(", ")})`); fits.push({ kind: "season", qualities: match }); }
  else if (d.seasons.length && now.qualities.length) { score -= 1; }
  return { score, why, fits };
}

function nutritionNotes(d, who, guideKey) {
  const n = d.nutrition;
  const lim = limits(null, guideKey);
  const out = [];
  if (n.energy_kcal != null) out.push(`About ${n.energy_kcal} kcal${d.not_counted.length ? " (not counting the items listed as not counted)" : ""}: it takes the place of a dish in the day's meals rather than adding to them.`);
  if (n.sodium_mg != null && lim.sodium_mg?.max) out.push(`Sodium ${n.sodium_mg} mg — ${Math.round((n.sodium_mg / lim.sodium_mg.max) * 100)}% of the ${lim.sodium_mg.max} mg daily limit (${lim.guide}).`);
  const added = d.ingredients.find((i) => i.food === "sugar");
  if (added) out.push(`${added.g} g added sugar, optional: leave it out${who.diabetes ? " — with diabetes, do" : ""}.`);
  if (who.diabetes && d.kind === "congee") out.push("White-rice congee digests quickly (a high glycaemic index): with diabetes, a smaller bowl, an egg, tofu or vegetables alongside, or part whole grain; check your glucose as your care team advises.");
  if (who.diabetes && d.ingredients.some((i) => i.food === "jujube" || i.food === "goji") && n.sugar_g != null) out.push(`Dried fruit adds sugar (${n.sugar_g} g sugars in the serving, all sources).`);
  if (n.sat_fat_g != null && n.sat_fat_g >= 4) out.push(`Saturated fat ${n.sat_fat_g} g: skim the fat off the broth.`);
  return out;
}

function present(d, why, who, guideKey, fits = []) {
  return {
    id: d.id, zh: d.zh, en: d.en, kind: d.kind, serving: d.serving, nature: d.nature,
    why, fits,
    ingredients: d.ingredients.map((i) => `${i.zh} ${i.en} ${i.g} g${i.homology !== "food" ? ` [listed ${i.homology}]` : ""}`),
    method_zh: d.method_zh, method_en: d.method_en,
    nutrition: { per: d.serving, ...Object.fromEntries(Object.entries(d.nutrition).filter(([, v]) => v != null)), ...(d.not_counted.length ? { not_counted: d.not_counted } : {}) },
    nutrition_notes: nutritionNotes(d, who, guideKey),
    classics: d.evidence.map(qref),
    cautions: [...d.cautions.map(qref), ...d.notes.map((n) => ({ note: n }))],
  };
}

/** The tool.  `profile`: the screening answers (conditions, medicines, allergies, diet, age); `constitution`: {primary,
 * tendency, source}; `region`, `date`; `time`: "breakfast" | "lunch" | "afternoon" | "dinner" | "day" | "now". */
export function medicinal({ profile = {}, constitution = null, region = null, date = null, time = "day", limit = 3 } = {}, nowDate = new Date()) {
  const code = region || profile.region || null;
  const r = regionOf(code);
  const ctx = context({ region: r?.code || null, date }, nowDate);
  if (!ctx.ok) return { ok: false, error: ctx.error };
  const conditions = profile.conditions;
  const medsList = Array.isArray(profile.medicines) ? profile.medicines : null;
  const meds = Object.fromEntries(MEDICINES.map((m) => [m, has(medsList, m)]));
  if (has(conditions, "warfarin")) meds.anticoagulant = true;
  if (has(conditions, "glucose_lowering_medicine")) meds.diabetes_medicine = true;
  const base = { ok: true, algorithm: ALGORITHM };

  // 1. who is not offered medicinal dishes at all
  const out = Object.keys(NOT_OFFERED).filter((k) => has(conditions, k));
  if (Number(profile.age) && Number(profile.age) < 18) out.push("under_18");
  if (out.length) {
    return { ...base, status: "not_offered", codes: out, reasons: out.map((k) => (k === "under_18" ? "Under 18: this mode is for adults; no medicinal dishes are suggested." : NOT_OFFERED[k])),
      instead: "Ordinary balanced meals (the diet plan) are fine; anything herbal is for your doctor or a registered practitioner to advise on." };
  }
  // 2. the safety questions first
  const ask = [];
  if (!known(conditions) || has(conditions, "unsure")) ask.push({ key: "conditions", ...ASK.conditions });
  if (!medsList?.length) ask.push({ key: "medicines", ...ASK.medicines });
  if (has(conditions, "food_allergy") && !known(profile.allergies)) ask.push({ key: "allergies", ...ASK.allergies });
  if (ask.length) {
    return { ...base, status: "needs_information", ask_next: ask.slice(0, 2),
      say: "Medicinal dishes come after a short safety check; ask only these, then call again with the answers." };
  }

  // 3. now: the season's qualities, the time of day
  const phase = ctx.season.phase;
  const qualities = [...(QUALITIES[phase] || [])];
  if (r?.climate === "arid" && phase === "summer") qualities.push("dry");
  const hour = hourIn(r?.tz || null, nowDate);
  const wanted = time === "now" ? slotOf(hour) : SLOTS.includes(time) ? time : "day";
  const now = { qualities };
  const who = {
    c: readConstitution(constitution), allergies: profile.allergies || [], diet: profile.diet || [], meds, conditions,
    diabetes: has(conditions, "diabetes") || has(conditions, "prediabetes") || meds.diabetes_medicine,
  };
  const guideKey = r?.guide || "who";

  const pickFor = (slot) => {
    const shown = [], out = [];
    for (const d of DISHES) {
      if (slot && !d.slots.includes(slot)) continue;
      const x = exclusion(d, who, now, slot);
      if (x) { out.push({ id: d.id, zh: d.zh, en: d.en, ...x }); continue; }
      const f = fit(d, who, now);
      shown.push({ d, ...f });
    }
    shown.sort((a, b) => b.score - a.score);
    return { shown, out };
  };

  const principles = [qref("food_nourishes"), { ...qref("food_first"), read_as: "A historical view of food before medicine. Today, a diagnosed condition needs medical care: food is never a substitute for it." }];
  const seasonQuotes = { spring: ["seasons", "spring_taste"], summer: ["seasons", "summer_food", "summer_cold_greasy"], autumn: ["seasons"], winter: ["seasons"] };
  const timeQuotes = { breakfast: ["ginger_morning"], dinner: ["no_full_sleep", "no_night_ginger"], late: ["no_full_sleep"] };

  let result;
  if (wanted === "late") {
    result = { slot: "late", local_hour: hour, dishes: [], say: "It is late in the evening: the classics advise against eating a full meal before lying down; if hungry, something small and plain.",
      classics: timeQuotes.late.map(qref) };
  } else if (wanted === "day") {
    const used = new Set();
    result = { slot: "day", meals: SLOTS.map((slot) => {
      const { shown } = pickFor(slot);
      const best = shown.filter((s) => !used.has(s.d.id)).slice(0, 2);
      best.forEach((s) => used.add(s.d.id));
      return { slot, dishes: best.map((s) => present(s.d, s.why, who, guideKey, s.fits)) };
    }), left_out: pickFor(null).out };
  } else {
    const { shown, out: left } = pickFor(wanted);
    result = { slot: wanted, ...(time === "now" ? { local_hour: hour } : {}), dishes: shown.slice(0, Math.max(1, Math.min(6, Number(limit) || 3))).map((s) => present(s.d, s.why, who, guideKey, s.fits)),
      left_out: left };
  }

  const c = who.c;
  return {
    ...base, status: "ready",
    now: {
      date: ctx.date, region: ctx.region.code ? ctx.region.name : null,
      season: phase ? { phase, qualities, traditional_qualities: qualities.map((q) => QUALITY_WORDS[q]) } : { phase: null, note: "No region given: dishes are not matched to a season. Ask where the visitor lives to add it." },
      solar_term: ctx.solar_term.current.zh, solar_term_note: ctx.solar_term.note,
    },
    constitution: c.source === "unknown" && !c.primary.length
      ? { status: "unknown", note: "No constitution given: dishes are matched to the season and time only. The 60-question self-check on the opening screen (published standard ZYYXH/T157-2009), or a registered TCM practitioner's assessment, would refine them." }
      : { primary: c.primary.map(name), tendency: c.tendency.map(name), source: c.source },
    ...result,
    principles,
    season_classics: (seasonQuotes[phase] || []).map(qref),
    time_classics: (timeQuotes[wanted] || []).map(qref),
    homology: "Every ingredient is an everyday food or a substance on China's list of things that are both food and traditional medicine ([listed year] marks the latter), used in recipe amounts. Dang gui (listed 2019) only as a seasoning; astragalus (listed 2023) is labelled as not advised for pregnant or breastfeeding women and infants.",
    layers: { classics: "classical_text — historical statements, quoted with their passage ids; not modern evidence of an effect",
      fit: "tcm_food_guideline — the traditional reading of natures, constitutions and seasons", nutrition: "food_composition — USDA FoodData Central, per serving as listed",
      rules: "personalization_algorithm — this tool's screening and ranking rules" },
    boundary: "Traditional food care (食养) for wellbeing: not a treatment for any disease, not a substitute for medical care, and not proof that a dish changes a constitution. Stop a dish that disagrees with you. With a medical condition or regular medicines, check with your doctor or pharmacist.",
    provenance: provenance(["ccmq", "homology_list", "classics_corpus", "medicinal_rules", "herb_drug", "usda_fdc", "tcm_food_nature", ...(phase ? [ctx.season.source] : [])].filter(Boolean)),
  };
}
