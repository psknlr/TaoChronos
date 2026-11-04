// The diet tools as the model is offered them, and the page's own runner for them.  They run in this page — no runtime,
// no server, no network: what the visitor says of their body and health goes nowhere but to the model service they
// chose.  Each answers as a runtime's call does ({ok, tool, text, result, summary, citations, duration_ms}), so the
// agent loop, the tool steps and the turn's record of times treat them alike.

import { ALLERGENS, assess, CONDITIONS, DIETS, EATING, GOALS, SEXES } from "./assess.js";
import { BACKGROUNDS, REGION_CODES } from "./regions.js";
import { context } from "./context.js";
import { dishes, plan, swap } from "./plan.js";
import { progress } from "./progress.js";
import { foodNature } from "./tcm.js";
import { constitution, ITEMS, TYPES } from "./constitution.js";
import { medicinal, MEDICINES } from "./medicinal.js";
import { QUOTES } from "./medicinal-data.js";
import { LABELS } from "./sources.js";

/** A tool of the diet mode, by the name the model calls it (diet__plan) or the catalog's (diet.plan). */
export const isDiet = (name) => /^diet(?:__|\.)/.test(String(name || ""));

const PROFILE = {
  type: "object",
  description: "What the user has said so far (self-reported). Leave out anything not said — never guess or fill in a value; "
    + "a field left out is unknown, not 'none'. Pass the same profile, updated, on every call.",
  properties: {
    goal: { type: "string", enum: GOALS, description: "lose_weight, maintain, or eat_better (no calorie deficit)" },
    region: { type: "string", description: `the country the user lives in, as an ISO code: ${REGION_CODES.join(", ")}; leave out if not said (another country: its name, which gets the international defaults)` },
    background: { type: "string", enum: BACKGROUNDS, description: "family background, only as the user stated it (it decides the BMI scale: lower thresholds for Asian, Middle Eastern, Black African and African-Caribbean backgrounds)" },
    age: { type: "number", description: "years" },
    sex: { type: "string", enum: SEXES, description: "the sex the energy equation should use; not_stated when the user prefers not to say" },
    height_cm: { type: "number" },
    weight_kg: { type: "number" },
    waist_cm: { type: "number" },
    activity: { type: "string", enum: ["sedentary", "light", "moderate", "high", "unsure"] },
    conditions: { type: "array", items: { type: "string", enum: CONDITIONS },
      description: "health conditions as the user stated them; [\"none\"] when they said none" },
    other_condition: { type: "string", description: "the user's words for a condition not in the list" },
    diabetes_medicine: { type: "string", enum: ["yes", "no", "unsure"], description: "insulin or a sulfonylurea (gliclazide, glipizide, glimepiride)" },
    allergies: { type: "array", items: { type: "string", enum: ALLERGENS }, description: "food allergies; [\"none\"] when they said none" },
    other_allergy: { type: "string" },
    diet: { type: "array", items: { type: "string", enum: DIETS }, description: "food rules: halal, vegetarian, vegan, no_beef, no_pork, no_seafood, ramadan_fasting" },
    eating: { type: "array", items: { type: "string", enum: EATING }, description: "where and how they usually eat" },
    meals: { type: "integer", enum: [2, 3] },
    after_meal: { type: "string", enum: ["hungry_soon", "bloated", "comfortable", "unsure"], description: "optional: how they feel after meals" },
    food_style: { type: "string", enum: ["warm_cooked", "light_cool", "dry_mouth", "no_preference"], description: "optional: food style preferred" },
    medicines: { type: "array", items: { type: "string", enum: MEDICINES },
      description: "regular medicines, as the user said: anticoagulant (warfarin or another blood thinner), immunosuppressant, diabetes_medicine, other, unsure; [\"none\"] when they take none" },
  },
};

export const DIET_TOOLS = [
  {
    name: "diet__assess",
    description: "Screen the user's answers and compute what they allow: status (ready, needs_information, general_guidance_only, "
      + "see_professional_first), BMI on the scale that fits the user (WHO's, the lower thresholds for some family backgrounds, or China's), "
      + "resting and total energy (Mifflin–St Jeor, as a range), the energy target (only when screening allows one), protein, the daily "
      + "limits and plate model of the user's national food guide (WHO's by default), and the next questions to ask (at most two). Call it "
      + "first, and again whenever the user tells you more.",
    parameters: { type: "object", properties: { profile: PROFILE }, required: ["profile"] },
  },
  {
    name: "diet__plan",
    description: "A day or a week of meals, each with its energy and nutrients for the serving stated, what to add (vegetables, fruit) "
      + "and how to cook or order it: everyday meals made of plain foods (USDA values) anywhere, and a region's own dishes where it has a "
      + "dish pack (Singapore and Malaysia: hawker and kopitiam dishes, HPB values). Hard limits (allergies, halal, vegetarian, no beef or "
      + "pork) are never broken. The day's totals are checked against the energy target, protein and sodium.",
    parameters: {
      type: "object",
      properties: {
        profile: PROFILE,
        days: { type: "integer", minimum: 1, maximum: 7, description: "1 for today, up to 7 for a week" },
        meals: { type: "integer", enum: [2, 3] },
        exclude: { type: "array", items: { type: "string" }, description: "dish ids to leave out (ones the user dislikes)" },
        variant: { type: "integer", description: "another number gives another plan of the same quality" },
      },
      required: ["profile"],
    },
  },
  {
    name: "diet__swap",
    description: "Replace one meal of a planned day — with a named dish, or the best other one — and re-check the whole day "
      + "(energy, protein, sodium, allergens). Refuses a dish that breaks a hard limit.",
    parameters: {
      type: "object",
      properties: {
        profile: PROFILE,
        day: { type: "array", description: "the day as planned: its meals' slots and dish ids",
          items: { type: "object", properties: { slot: { type: "string" }, dish_id: { type: "string" } }, required: ["slot", "dish_id"] } },
        slot: { type: "string", description: "the meal to replace: breakfast, lunch, dinner (brunch with 2 meals; sahur, iftar in Ramadan)" },
        want: { type: "string", description: "optional: the dish id (or name) the user wants instead" },
        meals: { type: "integer", enum: [2, 3] },
        exclude: { type: "array", items: { type: "string" } },
        day_number: { type: "integer" },
      },
      required: ["profile", "day", "slot"],
    },
  },
  {
    name: "diet__dishes",
    description: "Look up dishes in the dataset by name or kind (e.g. 'lentil', 'chicken', 'laksa', 'soup', 'breakfast'): energy and "
      + "nutrients per serving with their source, typical allergens, how to cook or order a lighter version, and where each belongs. "
      + "With a region, only what is eaten there (and the everyday meals); with a profile, marks what the user may not have. A dish it does "
      + "not list has no data here.",
    parameters: {
      type: "object",
      properties: {
        query: { type: "string" },
        slot: { type: "string", enum: ["breakfast", "lunch", "dinner", "snack", "drink"] },
        region: { type: "string", description: "ISO country code" },
        cuisine: { type: "string", enum: ["basic", "chinese", "malay", "indian", "peranakan", "drink", "fruit"] },
        max_kcal: { type: "number" },
        sort: { type: "string", enum: ["kcal", "sodium", "protein"] },
        limit: { type: "integer" },
        profile: PROFILE,
      },
    },
  },
  {
    name: "diet__context",
    description: "The user's date on their own clock, the season where they live (by hemisphere and climate; the monsoons in Singapore "
      + "and South Asia) and what it means for eating, hydration and food safety, the current and next of the 24 solar terms (a Chinese "
      + "cultural calendar), and the festive seasons ahead worldwide with their foods and tips, those kept where the user lives first. "
      + "No live weather.",
    parameters: { type: "object", properties: {
      region: { type: "string", description: "ISO country code; without it, no season is given" },
      climate: { type: "string", enum: ["temperate", "cold", "subtropical", "arid", "tropical"], description: "the user's own climate when their country's broad one does not fit, or when the country is not listed" },
      hemisphere: { type: "string", enum: ["N", "S"] },
      date: { type: "string", description: "YYYY-MM-DD; default today on the region's clock (the local date without a region)" },
      within_days: { type: "integer", description: "how far ahead to look for festivals (default 60)" } } },
  },
  {
    name: "diet__food_nature",
    description: "Optional traditional layer: the natures (寒/凉/平/温/热; everyday 'heaty'/'cooling') of ordinary foods, and how the "
      + "user's after-meal feeling and food-style preference shape choices. Not a TCM diagnosis: tcm_pattern_status stays unconfirmed.",
    parameters: { type: "object", properties: {
      foods: { type: "array", items: { type: "string" } },
      after_meal: { type: "string", enum: ["hungry_soon", "bloated", "comfortable", "unsure"] },
      food_style: { type: "string", enum: ["warm_cooked", "light_cool", "dry_mouth", "no_preference"] } } },
  },
  {
    name: "diet__constitution",
    description: "Score the nine-constitution questionnaire (中医体质, the published 60-question standard ZYYXH/T157-2009) from the "
      + "user's answers, item by item (1 never … 5 always, for the past year): transformed scores and the standard's judgements "
      + "(是 / 倾向是 / 基本是). The full questionnaire is the self-check form on the mode's opening screen; in chat, do not ask sixty "
      + "questions — invite the user to fill in the form, and accept a constitution a registered practitioner found. A constitution is a "
      + "tendency for health care, not a diagnosis.",
    parameters: { type: "object", properties: {
      answers: { type: "object", description: `item id → 1–5; ids: ${ITEMS.map((i) => i.id).join(", ")}`, additionalProperties: { type: "integer", minimum: 1, maximum: 5 } },
      sex: { type: "string", enum: ["female", "male", "not_stated"], description: "decides the one sex-specific item of 湿热质" } },
      required: ["answers"] },
  },
  {
    name: "diet__medicinal",
    description: "Medicinal dishes (药膳) for health care, chosen for the user's constitution, the season and climate where they live, "
      + "and the time of day, after a safety screen (pregnancy, breastfeeding, under 18, kidney disease and eating disorders: none offered; "
      + "allergens, food rules, blood thinners, immunosuppressants, gout, and constitutions or seasons a classic warns against: those dishes "
      + "left out, with the reason). Each dish: why it fits, ingredients (everyday foods and substances on China's food–medicine list, in "
      + "recipe amounts), method, nutrition per serving (USDA; items without data listed as not counted), and the classical passages it "
      + "rests on with their passage ids, checked word for word. Not a treatment.",
    parameters: { type: "object", properties: {
      profile: PROFILE,
      constitution: { type: "object", description: "from diet__constitution (types judged 是 → primary, 倾向是 → tendency), or as a registered practitioner told the user; leave out if unknown",
        properties: { primary: { type: "array", items: { type: "string", enum: TYPES } }, tendency: { type: "array", items: { type: "string", enum: TYPES } },
          source: { type: "string", enum: ["questionnaire", "practitioner", "self_described"] } } },
      region: { type: "string", description: "ISO country code (else the profile's); without it, no season" },
      date: { type: "string", description: "YYYY-MM-DD; default today" },
      time: { type: "string", enum: ["day", "now", "breakfast", "lunch", "afternoon", "dinner"], description: "day (default): a dish for each meal; now: the user's present meal" },
      limit: { type: "integer", minimum: 1, maximum: 6 } },
      required: ["profile"] },
  },
  {
    name: "diet__progress",
    description: "Weekly review of weigh-ins as a trend (kg a week over up to four weeks, this week's average against last week's) "
      + "and what it means for the plan: too early, on track, faster than planned, plateau or rising.",
    parameters: {
      type: "object",
      properties: {
        profile: PROFILE,
        entries: { type: "array", items: { type: "object", properties: { date: { type: "string" }, weight_kg: { type: "number" }, waist_cm: { type: "number" } },
          required: ["date", "weight_kg"] } },
      },
      required: ["entries"],
    },
  },
];

const RUN = {
  "diet.assess": (a) => assess(a.profile || {}),
  "diet.plan": (a) => plan(a),
  "diet.swap": (a) => swap(a),
  "diet.dishes": (a) => dishes(a),
  "diet.context": (a) => context({ date: a.date, within: a.within_days, region: a.region, climate: a.climate, hemisphere: a.hemisphere }),
  "diet.food_nature": (a) => foodNature(a),
  "diet.progress": (a) => progress(a),
  "diet.constitution": (a) => constitution(a),
  "diet.medicinal": (a) => medicinal(a),
};

/** A tool's name as the catalog has it (diet.plan), for one written as the model may write it (diet__plan, Diet.Plan). */
export function dietName(name) {
  const key = String(name || "").trim().toLowerCase().replace(/__/g, ".").replace(/-/g, "_");
  return RUN[key] ? key : null;
}

/** A line under the tool's step: what came of it. */
function summarize(tool, r) {
  if (!r.ok) return r.error || "";
  switch (tool) {
    case "diet.assess": {
      const parts = [{ ready: "ready for a plan", needs_information: "needs more information", general_guidance_only: "general guidance",
        see_professional_first: "see a professional first" }[r.status]];
      if (r.bmi?.value) parts.push(`BMI ${r.bmi.value}`);
      if (r.target) parts.push(`${r.target.kcal_range[0]}–${r.target.kcal_range[1]} kcal`);
      return parts.join(" · ");
    }
    case "diet.plan": return `${r.days.length} day(s)${r.energy_target ? ` · target ${r.energy_target.kcal_range.join("–")} kcal` : ""}`;
    case "diet.swap": return `${r.swapped?.slot}: ${r.swapped?.to}`;
    case "diet.dishes": return `${r.count} dish(es)`;
    case "diet.context": return [r.date, r.region?.name, r.season?.phase?.replace(/_/g, " "), r.solar_term?.current?.zh].filter(Boolean).join(" · ");
    case "diet.food_nature": return `${r.found?.length || 0} food(s)`;
    case "diet.progress": return r.verdict || (r.reviewed ? "" : "not reviewed");
    case "diet.constitution": return r.status === "complete" ? r.result.summary : `${r.answered}/${r.of} answered`;
    case "diet.medicinal": {
      if (r.status !== "ready") return { not_offered: "not offered", needs_information: "safety questions first" }[r.status] || r.status;
      const n = r.meals ? r.meals.reduce((k, m) => k + m.dishes.length, 0) : (r.dishes || []).length;
      return `${n} dish(es)${r.now?.season?.phase ? ` · ${r.now.season.phase.replace(/_/g, " ")}` : ""}`;
    }
    default: return "";
  }
}

/** Run a diet tool, never throwing: a failure is a result the model reads. */
export function callDiet(name, args = {}, { maxChars = 16000 } = {}) {
  const started = performance.now();
  const tool = dietName(name);
  if (!tool) {
    const error = `no diet tool ${JSON.stringify(name)}; the diet tools are ${Object.keys(RUN).join(", ")}`;
    return { ok: false, tool: name, error, text: `ERROR: ${error}`, summary: error, citations: [], duration_ms: 0 };
  }
  let result;
  try {
    result = RUN[tool](args && typeof args === "object" ? args : {});
  } catch (err) {
    result = { ok: false, error: `${err?.name || "Error"}: ${err?.message || err}` };
  }
  const ms = Math.round((performance.now() - started) * 10) / 10;
  if (!result.ok) {
    const error = result.error || "failed";
    return { ok: false, tool, error, result, text: `ERROR: ${error}\n${JSON.stringify(result)}`, summary: summarize(tool, result), citations: [], duration_ms: ms };
  }
  return { ok: true, tool, result, text: fit(result, maxChars), summary: summarize(tool, result), citations: quoted(result), duration_ms: ms };
}

/** The classical passages a result quotes, as the page registers evidence (the citation check finds them returned). */
function quoted(result) {
  const seen = new Map();
  const walk = (v) => {
    if (Array.isArray(v)) v.forEach(walk);
    else if (v && typeof v === "object") {
      if (typeof v.passage_id === "string" && typeof v.quote === "string") {
        const q = Object.values(QUOTES).find((x) => x.passage_id === v.passage_id);
        if (!seen.has(v.passage_id)) seen.set(v.passage_id, { passage_id: v.passage_id, title: v.work, dynasty: q?.dynasty || undefined, text: v.quote });
      } else Object.values(v).forEach(walk);
    }
  };
  walk(result);
  return [...seen.values()];
}

/** The result as the model reads it, within `max` characters: a long plan keeps its first day whole and the others'
 * meals, numbers and checks (their tips, Chinese names, side servings and the sources' long titles go first). */
function fit(result, max) {
  if (result.meals || result.dishes) return fitMedicinal(result, max);
  let text = JSON.stringify(result);
  if (text.length <= max) return text;
  const slim = structuredClone(result);
  for (const p of slim.provenance || []) delete p.title;
  for (const d of (slim.days || []).slice(1)) { // the first day keeps everything; the others their dishes and numbers
    for (const m of d.meals) {
      if (m.dish) { delete m.dish.order; delete m.dish.zh; }
      for (const x of m.add || []) { delete x.order; delete x.zh; delete x.serving; }
    }
    for (const f of d.fruit_and_snacks || []) { delete f.order; delete f.zh; delete f.serving; }
    delete d.not_totalled;
    delete d.drinks;
  }
  text = JSON.stringify(slim);
  return text.length <= max ? text : `${text.slice(0, max)}…［truncated: ask for fewer days］`;
}

/** A medicinal-dish result for the model: the page's own fields (fits) out, what was left out in brief, and then, if
 * still too long, the English method and the passages' glosses. */
function fitMedicinal(result, max) {
  const slim = structuredClone(result);
  const dishes = [...(slim.meals || []).flatMap((m) => m.dishes), ...(slim.dishes || [])];
  for (const d of dishes) delete d.fits;
  slim.left_out = (slim.left_out || []).map((x) => ({ dish: x.zh, code: x.code, why: x.why, ...(x.quote ? { quote: x.quote.quote, passage_id: x.quote.passage_id, work: x.quote.work } : {}) }));
  for (const p of slim.provenance || []) delete p.title;
  let text = JSON.stringify(slim);
  if (text.length <= max) return text;
  for (const d of dishes) { delete d.method_en; for (const q of [...d.classics, ...d.cautions]) if (q) delete q.says; }
  text = JSON.stringify(slim);
  return text.length <= max ? text : `${text.slice(0, max)}…［truncated: ask for one meal］`;
}

export const EVIDENCE_LABELS = LABELS;
