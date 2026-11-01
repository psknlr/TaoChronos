// Screening and the next questions: what the visitor has told, what it allows, and what to ask next — at most two
// questions a turn, safety first.  The model passes what it has learnt (every field optional; a field left out is
// unknown, never "none"); the result says whether a plan may have an energy target, which numbers may be shown, what
// is still missing, and which questions to ask.  Missing data lowers what is offered; it is never made up.

import { ACTIVITY, bmi, limits, measures, protein, ree, target, tdee, waistRisk } from "./energy.js";
import { ALGORITHM, provenance } from "./sources.js";

export const CONDITIONS = ["none", "pregnant", "breastfeeding", "eating_disorder", "kidney_disease", "diabetes", "glucose_lowering_medicine",
  "prediabetes", "high_blood_pressure", "high_cholesterol", "heart_disease", "fatty_liver", "gout", "warfarin",
  "unexplained_weight_loss", "food_allergy", "other", "unsure"];
export const ALLERGENS = ["none", "peanut", "tree_nut", "crustacean", "mollusc", "fish", "egg", "milk", "soy", "wheat", "sesame", "other"];
export const DIETS = ["halal", "vegetarian", "vegan", "no_beef", "no_pork", "no_seafood", "ramadan_fasting"];
export const EATING = ["hawker", "home_cooking", "takeaway", "workplace_canteen", "quick_cooking", "low_budget"];
export const GOALS = ["lose_weight", "maintain", "eat_better"];
export const SEXES = ["male", "female", "not_stated"];

// what each answer does to the plan: refer (see a professional first; safe general eating only), no_target (general
// guidance, no energy target), maintenance (energy kept steady, no deficit), caution (a plan, with what to watch)
const EFFECT = { refer: 3, no_target: 2, maintenance: 1, caution: 0 };

// the questions, in the order they are asked; `required` ones come before any energy target
const QUESTIONS = {
  conditions: {
    required: true,
    question: "Do you have any health conditions or food restrictions I should take into account?",
    options: ["None", "Pregnant or breastfeeding", "Diabetes (and whether you take insulin or a sulfonylurea such as gliclazide)",
      "Kidney disease", "Eating disorder, now or in the past", "Food allergy", "Other", "Not sure"],
    why: "screening comes first: some answers mean a calorie target is not set automatically",
  },
  body: {
    required: true,
    question: "How old are you, and what are your height and current weight?",
    fields: ["age (years)", "height (cm)", "weight (kg)"],
    options: ["Skip"],
    why: "needed for BMI (Singapore's Asian cut-offs) and an energy estimate",
  },
  sex: {
    required: true,
    question: "Which sex should the standard energy equation use?",
    options: ["Male", "Female", "Prefer not to say"],
    why: "the Mifflin–St Jeor equation differs by sex; without it no energy number is given",
  },
  activity: {
    required: true,
    question: "How active are you on a typical day?",
    options: ["Sedentary", "Lightly active", "Moderately active", "Highly active", "Not sure"],
    why: "sets the activity assumption of the energy range",
  },
  diabetes_medicine: {
    required: true,
    question: "For your diabetes, do you take insulin or a sulfonylurea (such as gliclazide, glipizide or glimepiride)?",
    options: ["Yes", "No", "Not sure"],
    why: "these medicines can cause low blood sugar if intake drops, so a calorie deficit needs your doctor's review",
  },
  allergies: {
    required: true,
    question: "Which foods are you allergic to?",
    options: ["Peanut", "Tree nuts", "Prawn/crab/shellfish", "Fish", "Egg", "Milk", "Soy", "Wheat", "Sesame", "Other"],
    why: "every dish containing an allergen is excluded from the plan",
  },
  food_rules: {
    question: "Any food rules to follow — halal, vegetarian, no beef or no pork — and any food allergies?",
    options: ["Halal", "Vegetarian", "No beef", "No pork", "Food allergy", "None"],
    why: "hard limits on what the plan may contain",
  },
  routine: {
    question: "How do you usually eat — mostly at hawker centres or food courts, home cooking, or takeaway — and is it two or three meals a day?",
    options: ["Hawker / food court", "Home cooking", "Takeaway or delivery", "Workplace canteen", "Two meals", "Three meals"],
    why: "the plan uses dishes where you actually eat",
  },
  after_meal: {
    question: "How do you usually feel after a meal?",
    options: ["Hungry again quickly", "Often bloated", "Comfortable", "Not sure"],
    why: "optional: shapes food choices (a preference clue, not a TCM diagnosis)",
  },
  food_style: {
    question: "Which food style do you prefer?",
    options: ["Warm, cooked food", "Lighter, cooling food", "I often have a dry mouth", "No preference"],
    why: "optional: matches the traditional 'warm'/'cooling' food preference (not a TCM diagnosis)",
  },
};

const list = (v, allowed) => [...new Set((Array.isArray(v) ? v : v == null || v === "" ? [] : [v])
  .map((x) => String(x).trim().toLowerCase().replace(/[\s-]+/g, "_")).filter((x) => allowed.includes(x)))];
const known = (v) => Array.isArray(v) ? v.length > 0 : v !== undefined && v !== null && v !== "";

/** A profile as the tools read it: only the values they know, the rest unknown (and what was not understood). */
export function readProfile(p = {}) {
  const m = measures(p);
  const out = {
    goal: GOALS.includes(p.goal) ? p.goal : null,
    age: m.age, height_cm: m.height, weight_kg: m.weight, waist_cm: m.waist,
    sex: SEXES.includes(p.sex) ? p.sex : null,
    activity: ACTIVITY[p.activity] ? p.activity : null,
    conditions: known(p.conditions) ? list(p.conditions, CONDITIONS) : null,
    other_condition: p.other_condition ? String(p.other_condition).slice(0, 120) : undefined,
    allergies: known(p.allergies) ? list(p.allergies, ALLERGENS) : null,
    other_allergy: p.other_allergy ? String(p.other_allergy).slice(0, 120) : undefined,
    diet: known(p.diet) ? list(p.diet, DIETS) : null,
    eating: known(p.eating) ? list(p.eating, EATING) : null,
    meals: Number(p.meals) === 2 || Number(p.meals) === 3 ? Number(p.meals) : null,
    after_meal: ["hungry_soon", "bloated", "comfortable", "unsure"].includes(p.after_meal) ? p.after_meal : null,
    food_style: ["warm_cooked", "light_cool", "dry_mouth", "no_preference"].includes(p.food_style) ? p.food_style : null,
    problems: m.problems,
  };
  if (out.conditions?.length > 1) out.conditions = out.conditions.filter((c) => c !== "none");
  if (out.allergies?.length > 1) out.allergies = out.allergies.filter((c) => c !== "none");
  if (out.conditions && !out.conditions.length) out.problems.push(`conditions ${JSON.stringify(p.conditions)} not understood; use the listed values`);
  if (out.allergies && !out.allergies.length) out.problems.push(`allergies ${JSON.stringify(p.allergies)} not understood; use the listed values`);
  if (out.conditions && !out.conditions.length) out.conditions = null;
  if (out.allergies && !out.allergies.length) out.allergies = null;
  if (out.allergies?.includes("other") && !out.other_allergy) out.problems.push("allergies include 'other': name it in other_allergy, and check every dish yourself");
  return out;
}

/** What the answers mean for a plan: each flag with its effect and what to tell the visitor. */
export function screen(pf, index) {
  const flags = [];
  const flag = (code, effect, say, extra = {}) => flags.push({ code, effect, say, ...extra });
  const has = (c) => pf.conditions?.includes(c);
  if (pf.age !== null && pf.age < 18) {
    flag("under_18", "no_target", "Under 18: growing bodies need enough energy, so no calorie target is set here — healthy-plate guidance only; a doctor, school health service or dietitian can advise on weight.");
  }
  if (pf.age !== null && pf.age >= 75) {
    flag("aged_75_plus", "maintenance", "Aged 75 or over: intentional weight loss risks muscle and bone loss, so the plan keeps energy steady with enough protein; discuss weight loss with your doctor.");
  } else if (pf.age !== null && pf.age >= 65) {
    flag("aged_65_plus", "caution", "Aged 65 or over: keep protein up at every meal and add strength exercise so weight lost is mainly fat; tell your doctor before you begin.");
  }
  if (has("pregnant") || has("breastfeeding")) {
    flag(has("pregnant") ? "pregnant" : "breastfeeding", "no_target", "Pregnancy and breastfeeding need extra energy and nutrients: no calorie deficit is planned. Follow your doctor or midwife; food-safety and healthy-plate guidance still apply.");
  }
  if (has("eating_disorder")) {
    flag("eating_disorder", "refer", "With an eating disorder now or in the past, calorie counting and weight targets can do harm. No numbers are given; please talk with your doctor or eating-disorder care team, and eat regular, balanced meals.",
      { quiet_numbers: true });
  }
  if (has("kidney_disease")) {
    flag("kidney_disease", "refer", "Kidney disease changes what is safe to eat (protein, potassium, phosphate, fluid). Your renal doctor or dietitian should set those; the plan gives only general guidance and no protein target.",
      { withhold_protein: true });
  }
  if (has("unexplained_weight_loss")) {
    flag("unexplained_weight_loss", "refer", "Weight loss you can't explain should be checked by a doctor before any diet change.");
  }
  if (has("glucose_lowering_medicine")) {
    flag("glucose_lowering_medicine", "no_target", "Insulin and sulfonylureas can cause low blood sugar if you eat less or cut carbohydrate suddenly. Keep carbohydrate steady across meals; a calorie deficit needs your doctor's review of your medicines and how to monitor.");
  } else if (has("diabetes")) {
    flag("diabetes", "caution", "With diabetes, spread carbohydrate evenly across meals (wholegrains, not sugary drinks), keep your usual monitoring, and tell your doctor about the plan.");
  }
  if (has("heart_disease")) {
    flag("heart_disease", "caution", "With heart disease, keep sodium low and follow any fluid or salt limit your care team set; heart failure needs their plan first.");
  }
  if (has("high_blood_pressure")) flag("high_blood_pressure", "caution", "With high blood pressure, sodium matters most: gravy, soup and sauces carry most of it.");
  if (has("high_cholesterol")) flag("high_cholesterol", "caution", "With high cholesterol, swap saturated fat (fried food, coconut-milk gravies, fatty meats) for unsaturated oils, fish and pulses.");
  if (has("prediabetes")) flag("prediabetes", "caution", "With prediabetes, losing 5–7% of weight and choosing wholegrains and water over sugary drinks lowers the risk of diabetes.");
  if (has("fatty_liver")) flag("fatty_liver", "caution", "With fatty liver, gradual weight loss, less sugar and alcohol help; keep your doctor informed.");
  if (has("gout")) flag("gout", "caution", "With gout, lose weight gradually (rapid loss and fasting can trigger attacks), keep drinking water, and limit organ meats, sugary drinks and alcohol.");
  if (has("warfarin")) flag("warfarin", "caution", "On warfarin, keep the amount of leafy green vegetables steady from week to week rather than changing it suddenly, and tell your doctor about diet changes.");
  if (has("other")) {
    flag("other_condition", "no_target", `A condition not listed${pf.other_condition ? ` (${pf.other_condition})` : ""}: no calorie target is set automatically until it is clear a deficit is safe — check with your doctor; general guidance still applies.`);
  }
  if (has("unsure")) flag("conditions_unsure", "no_target", "Unsure about health conditions: general healthy-plate guidance for now; a calorie target can follow once that is clear.");
  if (index && index.band === "underweight") {
    flag("underweight", pf.goal === "lose_weight" ? "refer" : "maintenance",
      pf.goal === "lose_weight" ? "BMI below 18.5: losing weight is not recommended — please check with a doctor." : "BMI below 18.5: the plan keeps energy up; if weight is falling without trying, see a doctor.");
  }
  if (index && index.band === "healthy" && pf.goal === "lose_weight") {
    flag("healthy_weight", "maintenance", "BMI is in the healthy range (18.5–22.9): rather than a calorie deficit, focus on food quality, enough protein and strength exercise to change body composition.");
  }
  if (index && index.value >= 32.5) {
    flag("bmi_32_5_plus", "caution", `BMI ${index.value}: at this level a doctor-supported programme (a polyclinic or GP can refer you) adds to what diet alone does.`);
  }
  return flags;
}

/** The questions still to ask, in order: the required, then the optional; each by its id, with its words. */
function questions(pf, flags) {
  const blocking = flags.some((f) => EFFECT[f.effect] >= EFFECT.no_target);
  const ask = [];
  if (!pf.conditions) ask.push("conditions");
  if (!blocking) {
    if (pf.age === null || pf.height_cm === null || pf.weight_kg === null) ask.push("body");
    if (!pf.sex) ask.push("sex");
    if (!pf.activity) ask.push("activity");
  }
  if (pf.conditions?.includes("diabetes") && !pf.conditions.includes("glucose_lowering_medicine") && !pf.diabetes_medicine_answered) ask.push("diabetes_medicine");
  if (pf.conditions?.includes("food_allergy") && !pf.allergies) ask.push("allergies");
  const optional = [];
  if (!pf.diet) optional.push("food_rules");
  if (!pf.eating && !pf.meals) optional.push("routine");
  if (!pf.after_meal) optional.push("after_meal");
  if (!pf.food_style) optional.push("food_style");
  return { required: ask, optional };
}

const word = (id) => ({ id, ...QUESTIONS[id], required: undefined });

/** The whole assessment: what is known, the screening, the numbers it allows, what to ask next. */
export function assess(input = {}) {
  const pf = readProfile(input);
  pf.diabetes_medicine_answered = input.diabetes_medicine === "no" || input.diabetes_medicine === false;
  if (input.diabetes_medicine === "yes" || input.diabetes_medicine === true) pf.conditions = [...new Set([...(pf.conditions || []), "glucose_lowering_medicine"])];
  if (input.diabetes_medicine === "unsure") pf.conditions = [...new Set([...(pf.conditions || []), "unsure"])];
  const index = bmi(pf.weight_kg, pf.height_cm, pf.age);
  const flags = screen(pf, index);
  const assumptions = [];
  // the conditions question lists food allergy among its answers: answered without it, there is none to exclude
  if (!pf.allergies && pf.conditions && !pf.conditions.includes("food_allergy") && !pf.conditions.includes("unsure")) {
    pf.allergies = ["none"];
    assumptions.push("no food allergy: the health-conditions answer did not include one");
  }
  const strongest = flags.reduce((a, f) => Math.max(a, EFFECT[f.effect]), -1);
  const quiet = flags.some((f) => f.quiet_numbers);
  const { required, optional } = questions(pf, flags);
  const goal = pf.goal || "eat_better";
  if (!pf.goal) assumptions.push("goal not stated: taken as eating better, so no calorie deficit is planned unless weight loss is asked for");

  const rest = strongest >= EFFECT.no_target ? null : ree({ weight: pf.weight_kg, height: pf.height_cm, age: pf.age, sex: pf.sex });
  const total = rest ? tdee(rest, pf.activity) : null;
  if (total && !pf.activity) assumptions.push(`activity not stated: ${total.assumption}`);
  else if (total) assumptions.push(total.assumption);
  if (rest) assumptions.push("resting energy estimated by Mifflin–St Jeor (individual error commonly ±10%); revise with the 2–4-week weight trend");
  const mode = goal === "lose_weight" && strongest < EFFECT.maintenance && index && index.band !== "healthy" && index.band !== "underweight"
    ? "deficit" : "maintenance";
  let status;
  if (strongest >= EFFECT.refer) status = "see_professional_first";
  else if (strongest >= EFFECT.no_target) status = "general_guidance_only";
  else if (required.length) status = "needs_information";
  else status = "ready";
  const goal_target = status === "ready" ? target({ total, rest, sex: pf.sex, mode }) : null;
  const energy = rest && !quiet ? { method: "mifflin_st_jeor", ree_kcal: rest, tdee_kcal_range: total.range, source: ["mifflin_st_jeor", "activity_factors"] } : null;
  if (!rest && strongest < EFFECT.no_target) {
    const why = pf.age !== null && pf.age < 18 ? "under 18" : !pf.sex || pf.sex === "not_stated" ? "sex for the equation not given"
      : pf.age === null || pf.height_cm === null || pf.weight_kg === null ? "age, height or weight missing" : "not computable";
    assumptions.push(`no energy estimate (${why}): portions follow the healthy plate instead of a calorie number`);
  }
  const prot = quiet ? null : protein({ weight: pf.weight_kg, height: pf.height_cm, age: pf.age, index, losing: goal_target?.kind === "deficit",
    withheld: flags.some((f) => f.withhold_protein) || strongest >= EFFECT.refer });
  const kcal = goal_target ? Math.round((goal_target.kcal_range[0] + goal_target.kcal_range[1]) / 2) : null;
  // asked at most two at a time: the required first; the optional only once the required are answered
  const next = (required.length ? required : optional).slice(0, 2).map(word);

  const known_now = Object.fromEntries(Object.entries({
    goal: pf.goal, age: pf.age, sex: pf.sex, height_cm: pf.height_cm, weight_kg: pf.weight_kg, waist_cm: pf.waist_cm, activity: pf.activity,
    conditions: pf.conditions, other_condition: pf.other_condition, allergies: pf.allergies, other_allergy: pf.other_allergy, diet: pf.diet, eating: pf.eating, meals: pf.meals,
    after_meal: pf.after_meal, food_style: pf.food_style,
  }).filter(([, v]) => v !== null && v !== undefined));
  const sources = ["hpb_healthy_plate", "hpb_sodium", "hpb_sugar", "who_healthy_diet", "who_carbohydrate"];
  if (index) sources.push("sg_moh_cpg_obesity");
  if (index?.action_point) sources.push("who_asian_bmi");
  if (energy) sources.push("mifflin_st_jeor", "activity_factors");
  if (prot) sources.push("protein_reference");
  return {
    ok: true, algorithm: ALGORITHM, status,
    status_means: {
      ready: "a plan may be made now (diet.plan) with the energy target below",
      needs_information: "ask the questions in ask_next (at most two), and give brief general guidance meanwhile",
      general_guidance_only: "give healthy-plate guidance without a calorie target; explain why (flags)",
      see_professional_first: "say kindly why a professional should be seen first; give only general safe-eating guidance",
    }[status],
    self_reported: known_now,
    goal,
    flags: flags.map(({ code, effect, say }) => ({ code, effect, say })),
    bmi: quiet ? null : index,
    waist: quiet ? null : waistRisk(pf.waist_cm, pf.sex),
    energy,
    target: goal_target && !quiet ? goal_target : null,
    protein: prot,
    limits: quiet ? null : limits(kcal),
    plate: {
      rule: "My Healthy Plate: half fruit and vegetables, a quarter wholegrains (brown rice, wholemeal bread, oats, wholegrain noodles), a quarter protein (fish, tofu, beans, eggs, lean meat); water to drink; healthier oils in small amounts",
      source: "hpb_healthy_plate",
    },
    ask_next: next,
    still_optional: required.length ? optional.map(word).map((q) => q.id) : optional.slice(2),
    assumptions,
    problems: pf.problems.length ? pf.problems : undefined,
    meals_hint: status === "ready" || status === "general_guidance_only" ? "diet.plan builds a day or a week from Singapore dishes within these limits" : undefined,
    provenance: provenance(sources),
    note: "Self-reported answers, used as given: no diagnosis is made. Never state an energy or nutrient number that is not in a tool result.",
  };
}
