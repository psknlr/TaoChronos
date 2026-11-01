// The numbers of a diet plan, computed, never estimated by the model: BMI on the scale that fits the visitor (WHO's,
// the lower thresholds for Asian and some other family backgrounds, or China's standard: regions.js), waist risk on the
// same, resting energy by Mifflin–St Jeor, total energy as a range over an activity assumption, the energy target
// a plan may aim for (only when screening allows one, never below its floor), protein, and the daily limits of sodium,
// added sugar and saturated fat as the visitor's national guide sets them (WHO's where it sets none).  Each figure says
// what it rests on (sources.js) and what it assumes.

import { GUIDES, SCALES, WAIST } from "./regions.js";

/** Activity levels: the multiplier range of resting energy (an assumption, revised by the weight trend). */
export const ACTIVITY = {
  sedentary: { pal: [1.2, 1.3], label: "sedentary (desk work, little exercise)" },
  light: { pal: [1.35, 1.45], label: "lightly active (walking, light exercise 1–3 days a week)" },
  moderate: { pal: [1.5, 1.65], label: "moderately active (exercise 3–5 days a week, or an active job)" },
  high: { pal: [1.7, 1.85], label: "highly active (hard exercise most days, or heavy physical work)" },
  unsure: { pal: [1.2, 1.45], label: "not sure (assumed sedentary to lightly active)" },
};

// a self-guided plan never aims below these, nor below the estimated resting energy (screening decides who may have one)
export const FLOOR = { female: 1200, male: 1500 };
export const DEFICIT = [300, 500]; // a modest daily deficit, kcal

const round = (x, step = 1) => Math.round(x / step) * step;
const finite = (x) => typeof x === "number" && Number.isFinite(x);

/** Measurements read as numbers within human bounds, or null (a value out of bounds is reported, not used). */
export function measures(p = {}) {
  const out = { age: null, height: null, weight: null, waist: null, problems: [] };
  const take = (key, value, lo, hi, what) => {
    if (value === undefined || value === null || value === "") return;
    const n = Number(value);
    if (!Number.isFinite(n) || n < lo || n > hi) out.problems.push(`${what} ${value} is outside ${lo}–${hi}; not used — please check it`);
    else out[key] = n;
  };
  take("age", p.age, 1, 120, "age");
  take("height", p.height_cm, 100, 230, "height_cm");
  take("weight", p.weight_kg, 25, 300, "weight_kg");
  take("waist", p.waist_cm, 40, 200, "waist_cm");
  return out;
}

/** BMI and its band on a scale (`who`, `asian` or `china`; adults only). */
export function bmi(weight, height, age = null, scale = "who") {
  if (!finite(weight) || !finite(height)) return null;
  const S = SCALES[scale] || SCALES.who;
  const value = Math.round((weight / (height / 100) ** 2) * 10) / 10;
  const out = { value, scale: SCALES[scale] ? scale : "who", source: S.source };
  if (finite(age) && age < 18) {
    return { ...out, band: "not_applicable", note: "Under 18: BMI is read against BMI-for-age charts, not adult cut-offs." };
  }
  if (value < S.under) Object.assign(out, { band: "underweight", risk: "risk of nutritional deficiency and osteoporosis" });
  else if (value < S.over) Object.assign(out, { band: "healthy", risk: "low risk" });
  else if (value < S.obese) Object.assign(out, { band: "overweight", risk: "increased risk of heart disease, stroke and type 2 diabetes" });
  else Object.assign(out, { band: "obese", risk: "high risk of heart disease, stroke and type 2 diabetes" });
  out.cutoffs = `${S.name}: ${S.bands}`;
  const point = [...S.higher].reverse().find((p) => value >= p);
  if (point) out.action_point = point; // obesity class II and III, or their lower-threshold equivalents
  out.note = "BMI does not measure body fat or muscle; waist circumference adds to it.";
  return out;
}

/** Waist circumference against the thresholds of the same scale (needs the sex for the comparison). */
export function waistRisk(waist, sex, scale = "who") {
  if (!finite(waist)) return null;
  const W = WAIST[scale] || WAIST.who;
  const [raised, high] = W[sex] || [];
  if (!raised) return { cm: waist, note: `Thresholds differ by sex (men ${W.male.join(" / ")} cm, women ${W.female.join(" / ")} cm); sex not given.` };
  return { cm: waist, thresholds_cm: [raised, high], raised: waist >= raised, high: waist >= high, source: W.source };
}

/** Resting energy (kcal/day) by Mifflin–St Jeor, for an adult with sex given; else null. */
export function ree({ weight, height, age, sex }) {
  if (![weight, height, age].every(finite) || age < 18 || !(sex === "male" || sex === "female")) return null;
  return round(10 * weight + 6.25 * height - 5 * age + (sex === "male" ? 5 : -161));
}

/** Total energy as a range: resting energy times the activity level's multipliers (unknown activity: as `unsure`). */
export function tdee(rest, activity) {
  if (!finite(rest)) return null;
  const level = ACTIVITY[activity] ? activity : "unsure";
  const [lo, hi] = ACTIVITY[level].pal;
  return { range: [round(rest * lo, 10), round(rest * hi, 10)], mid: round(rest * (lo + hi) / 2, 10), activity: level,
    assumption: `${ACTIVITY[level].label}: activity factor ${lo}–${hi}` };
}

/** The daily energy a plan aims for, by `mode` (screening's): "deficit" (a modest deficit within the floor), or
 * "maintenance".  A deficit that the floor leaves too small to matter becomes maintenance, saying why. */
export function target({ total, rest, sex, mode }) {
  if (!total || !finite(rest)) return null;
  if (mode !== "deficit") {
    return { kind: "maintenance", kcal_range: total.range, why: "energy to keep weight steady; the focus is on what is eaten" };
  }
  const floor = Math.max(FLOOR[sex] || FLOOR.female, round(rest, 10));
  let lo = round(total.mid - DEFICIT[1], 50);
  let hi = round(total.mid - DEFICIT[0], 50);
  lo = Math.max(lo, floor);
  hi = Math.max(hi, lo + 100);
  if (total.mid - hi < 150) {
    return { kind: "maintenance", kcal_range: total.range, floor_kcal: floor,
      why: `a deficit would take intake below the safety floor (${floor} kcal: the larger of the resting estimate and ${FLOOR[sex] || FLOOR.female} kcal), so the plan keeps energy steady and improves food quality` };
  }
  return { kind: "deficit", kcal_range: [lo, hi], deficit_kcal: [total.mid - hi, total.mid - lo], floor_kcal: floor,
    expected: "about 0.25–0.5 kg a week on average, judged on the 2–4-week trend, not a single weigh-in",
    why: "a modest deficit of about 300–500 kcal a day from the estimated total, never below the floor" };
}

/** Protein (g/day): 1.0–1.2 g per kg of reference weight when losing weight or aged 65 and over, else 0.8–1.0; the
 * reference weight is the weight at BMI 25 when BMI is in the obesity range of its scale.  Null when protein is not ours to set (`withheld`). */
export function protein({ weight, height, age, index, losing, withheld }) {
  if (withheld || !finite(weight)) return null;
  // in the obesity range, protein is reckoned on the weight at BMI 25 (an adjusted weight), not the whole of it
  const reference = index?.band === "obese" && finite(height) ? Math.min(weight, 25 * (height / 100) ** 2) : weight;
  const [a, b] = losing || (finite(age) && age >= 65) ? [1.0, 1.2] : [0.8, 1.0];
  return { g_range: [round(reference * a, 5), round(reference * b, 5)], per_kg: [a, b], reference_kg: round(reference, 0.5),
    source: "protein_reference" };
}

/** The day's limits by a national guide (WHO's by default), scaled to the day's energy where they are a share of it. */
export function limits(kcal, guide = "who") {
  const e = finite(kcal) ? kcal : 2000;
  const g = GUIDES[guide] || GUIDES.who;
  const sugar = g.sugar.grams
    ? { max: g.sugar.grams, kind: g.sugar.kind, source: g.source, note: `${g.name}: no more than ${g.sugar.grams} g ${g.sugar.kind} a day` }
    : { max: round((g.sugar.share * e) / 4), kind: g.sugar.kind, source: g.sugar.fallback ? "who_healthy_diet" : g.source,
      note: `${Math.round(g.sugar.share * 100)}% of ${round(e, 10)} kcal${g.sugar.ideal ? ` (ideally under ${Math.round(g.sugar.ideal * 100)}%: ${round((g.sugar.ideal * e) / 4)} g)` : ""}`
        + `${g.sugar.fallback ? " — WHO's limit, which this guide's number was not checked against" : ""}${g.sugar.note ? `; ${g.sugar.note}` : ""}` };
  return {
    guide: g.name,
    sodium_mg: { max: g.sodium_mg, source: g.sodium_mg === 2000 && guide !== "sg" && guide !== "cn" ? "who_healthy_diet" : g.source,
      note: `${g.salt_g ? `about ${g.salt_g} g of salt` : "salt"}, sauces and stock included` },
    sugar_g: sugar,
    saturated_fat_g: { max: round((0.1 * e) / 9), source: "who_healthy_diet", note: `under 10% of ${round(e, 10)} kcal` },
    ...(g.oil_g ? { cooking_oil_g: { range: g.oil_g, source: g.source } } : {}),
    fibre_g: { min: 25, source: "who_carbohydrate" },
    fruit_veg: { min: "at least 400 g a day — about 5 portions of fruit and vegetables", source: "who_healthy_diet" },
  };
}
