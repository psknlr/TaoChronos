// The numbers of a diet plan, computed, never estimated by the model: BMI against Singapore's cut-offs for Asian adults,
// waist risk, resting energy by Mifflin–St Jeor, total energy as a range over an activity assumption, the energy target
// a plan may aim for (only when screening allows one, never below its floor), protein, and the daily limits of sodium,
// added sugar and saturated fat.  Each figure says what it rests on (sources.js) and what it assumes.

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

/** BMI and its Singapore/Asian risk band (adults only). */
export function bmi(weight, height, age = null) {
  if (!finite(weight) || !finite(height)) return null;
  const value = Math.round((weight / (height / 100) ** 2) * 10) / 10;
  const out = { value, source: "sg_moh_cpg_obesity" };
  if (finite(age) && age < 18) {
    return { ...out, band: "not_applicable", note: "Under 18: BMI is read against BMI-for-age charts, not adult cut-offs." };
  }
  if (value < 18.5) Object.assign(out, { band: "underweight", risk: "risk of nutritional deficiency and osteoporosis" });
  else if (value < 23) Object.assign(out, { band: "healthy", risk: "low risk" });
  else if (value < 27.5) Object.assign(out, { band: "overweight", risk: "moderate risk of heart disease, stroke and diabetes" });
  else Object.assign(out, { band: "obese", risk: "high risk of heart disease, stroke and diabetes" });
  out.cutoffs = "Singapore (Asian) cut-offs: <18.5 underweight · 18.5–22.9 low risk · 23.0–27.4 moderate risk · ≥27.5 high risk";
  if (value >= 32.5) out.action_point = value >= 37.5 ? 37.5 : 32.5; // WHO 2004 further action points for Asians
  out.note = "BMI does not measure body fat or muscle; waist circumference adds to it.";
  return out;
}

/** Waist circumference against Singapore's thresholds (needs the sex for the comparison). */
export function waistRisk(waist, sex) {
  if (!finite(waist)) return null;
  const limit = sex === "male" ? 90 : sex === "female" ? 80 : null;
  if (!limit) return { cm: waist, note: "The threshold is 90 cm for men and 80 cm for women; sex not given." };
  return { cm: waist, threshold_cm: limit, raised: waist >= limit, source: "sg_moh_cpg_obesity" };
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
 * reference weight is the weight at BMI 25 when BMI is 27.5 or more.  Null when protein is not ours to set (`withheld`). */
export function protein({ weight, height, age, index, losing, withheld }) {
  if (withheld || !finite(weight)) return null;
  const reference = index && index.value >= 27.5 && finite(height) ? 25 * (height / 100) ** 2 : weight;
  const [a, b] = losing || (finite(age) && age >= 65) ? [1.0, 1.2] : [0.8, 1.0];
  return { g_range: [round(reference * a, 5), round(reference * b, 5)], per_kg: [a, b], reference_kg: round(reference, 0.5),
    source: "protein_reference" };
}

/** The day's limits, scaled to its energy where they are a share of it. */
export function limits(kcal) {
  const e = finite(kcal) ? kcal : 2000;
  return {
    sodium_mg: { max: 2000, source: "hpb_sodium", note: "about 1 teaspoon of salt, sauces and gravy included" },
    added_sugar_g: { max: round(0.1 * e / 4), source: "hpb_sugar", note: `10% of ${round(e, 10)} kcal` },
    saturated_fat_g: { max: round(0.1 * e / 9), source: "who_healthy_diet", note: `under 10% of ${round(e, 10)} kcal` },
    fibre_g: { min: 25, source: "who_carbohydrate" },
    fruit_veg: { min: "at least 400 g a day — about 2 servings of fruit and 2 of vegetables", source: "who_healthy_diet" },
  };
}
