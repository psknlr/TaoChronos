// The diet tools as the model is offered them, and the page's own runner for them.  They run in this page — no runtime,
// no server, no network: what the visitor says of their body and health goes nowhere but to the model service they
// chose.  Each answers as a runtime's call does ({ok, tool, text, result, summary, citations, duration_ms}), so the
// agent loop, the tool steps and the turn's record of times treat them alike.

import { ALLERGENS, assess, CONDITIONS, DIETS, EATING, GOALS, SEXES } from "./assess.js";
import { context } from "./context.js";
import { dishes, plan, swap } from "./plan.js";
import { progress } from "./progress.js";
import { foodNature } from "./tcm.js";
import { LABELS } from "./sources.js";

/** A tool of the diet mode, by the name the model calls it (diet__plan) or the catalog's (diet.plan). */
export const isDiet = (name) => /^diet(?:__|\.)/.test(String(name || ""));

const PROFILE = {
  type: "object",
  description: "What the user has said so far (self-reported). Leave out anything not said — never guess or fill in a value; "
    + "a field left out is unknown, not 'none'. Pass the same profile, updated, on every call.",
  properties: {
    goal: { type: "string", enum: GOALS, description: "lose_weight, maintain, or eat_better (no calorie deficit)" },
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
  },
};

export const DIET_TOOLS = [
  {
    name: "diet__assess",
    description: "Screen the user's answers and compute what they allow: status (ready, needs_information, general_guidance_only, "
      + "see_professional_first), BMI against Singapore's Asian cut-offs, resting and total energy (Mifflin–St Jeor, as a range), the "
      + "energy target (only when screening allows one), protein, daily limits, and the next questions to ask (at most two). Call it first, "
      + "and again whenever the user tells you more.",
    parameters: { type: "object", properties: { profile: PROFILE }, required: ["profile"] },
  },
  {
    name: "diet__plan",
    description: "A day or a week of meals from Singapore dishes (hawker, kopitiam, food court), each with HPB's energy and nutrients "
      + "for its serving, what to add (vegetables, fruit) and how to order it; hard limits (allergies, halal, vegetarian, no beef or pork) "
      + "are never broken. The day's totals are checked against the energy target, protein and sodium.",
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
    description: "Look up Singapore dishes in the dataset by name or kind (e.g. 'laksa', 'soup', 'halal', 'breakfast'): energy and "
      + "nutrients per serving as HPB published them, typical allergens, and how to order a lighter version. With a profile, marks the ones "
      + "the user may not have. Use it to compare dishes; a dish it does not list has no data here.",
    parameters: {
      type: "object",
      properties: {
        query: { type: "string" },
        slot: { type: "string", enum: ["breakfast", "lunch", "dinner", "snack", "drink"] },
        cuisine: { type: "string", enum: ["chinese", "malay", "indian", "peranakan", "western", "drink", "fruit", "basic"] },
        max_kcal: { type: "number" },
        sort: { type: "string", enum: ["kcal", "sodium", "protein"] },
        limit: { type: "integer" },
        profile: PROFILE,
      },
    },
  },
  {
    name: "diet__context",
    description: "Singapore's date (Asia/Singapore), its monsoon season and what it means for eating and hydration, the current "
      + "and next of the 24 solar terms (as a cultural calendar), and festive seasons ahead with their foods and tips. No live weather.",
    parameters: { type: "object", properties: { date: { type: "string", description: "YYYY-MM-DD; default today in Singapore" },
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
  "diet.context": (a) => context({ date: a.date, within: a.within_days }),
  "diet.food_nature": (a) => foodNature(a),
  "diet.progress": (a) => progress(a),
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
    case "diet.context": return `${r.date} · ${r.solar_term?.current?.zh} · ${r.season?.phase?.replace(/_/g, " ")}`;
    case "diet.food_nature": return `${r.found?.length || 0} food(s)`;
    case "diet.progress": return r.verdict || (r.reviewed ? "" : "not reviewed");
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
  return { ok: true, tool, result, text: fit(result, maxChars), summary: summarize(tool, result), citations: [], duration_ms: ms };
}

/** The result as the model reads it, within `max` characters: a long plan keeps its first day whole and the others'
 * meals and totals (their ordering tips and the sources' long titles go first). */
function fit(result, max) {
  let text = JSON.stringify(result);
  if (text.length <= max) return text;
  const slim = structuredClone(result);
  for (const p of slim.provenance || []) delete p.title;
  for (const d of (slim.days || []).slice(1)) {
    for (const m of d.meals) { if (m.dish) delete m.dish.order; for (const s of m.add || []) delete s.order; }
    for (const f of d.fruit_and_snacks || []) delete f.order;
    delete d.drinks;
  }
  text = JSON.stringify(slim);
  return text.length <= max ? text : `${text.slice(0, max)}…［truncated: ask for fewer days］`;
}

export const EVIDENCE_LABELS = LABELS;
