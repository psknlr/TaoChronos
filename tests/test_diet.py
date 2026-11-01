"""饮食与体重管理 (the diet mode, web/js/diet/, docs/diet.md, ADR 0029): its deterministic engine under Node, and the
mode in Chromium against a scripted provider.

Under Node: the BMI scales (WHO's, the lower thresholds for some family backgrounds, China's) and which applies to whom,
the national food guides' limits, Mifflin–St Jeor and the activity range, the energy target and its
floor, the screening (who gets no target, who is sent to a professional first, which numbers are withheld), the next
questions (at most two, safety first), the plans' hard constraints (every allergen, halal, vegetarian, no pork or beef)
under every combination tried, totals that are the sums of the dataset's own values, a swap that re-checks the day and
refuses a forbidden dish, plans for any region (everyday meals everywhere, a region's own dishes only there), the
dataset's integrity and provenance, the date on the visitor's clock, seasons by hemisphere and climate (and Singapore's
and South Asia's monsoons), worldwide festivals (Easter and Thanksgiving computed), the solar terms against
the National Astronomical Observatory of Japan's 2026 almanac, the festive seasons, the weekly review, the traditional
layer (never a diagnosis), the tools as the model is offered them, which text and conversations carry health
information, and the plain words the page shows for the tools.

In the browser: a diet conversation offered its own tools (run in the page: nothing of them to the server), its
instructions, answered — and never recorded, with nothing of it in feedback, though the visitor agreed to records; kept
only in the page until the visitor keeps it; an ordinary conversation in which the visitor wrote their own weight is not
recorded either, while one without is.  Skipped where Node or Playwright is missing.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

NODE_DIET = r"""
import assert from "node:assert/strict";
import { ALLERGENS, assess, CONDITIONS } from "./js/diet/assess.js";
import { bmi, limits, protein, ree, target, tdee, waistRisk } from "./js/diet/energy.js";
import { context, easter, festivals, localDay, season, solarTerm, termsOf } from "./js/diet/context.js";
import { GUIDES, region, REGIONS, regionOfZone, scaleFor } from "./js/diet/regions.js";
import { dish, dishes, forbidden, plan, swap } from "./js/diet/plan.js";
import { DATASET, DISHES } from "./js/diet/dishes.js";
import { progress } from "./js/diet/progress.js";
import { foodNature, natures, preference } from "./js/diet/tcm.js";
import { callDiet, DIET_TOOLS, dietName, isDiet } from "./js/diet/tools.js";
import { healthConv, healthText, isDietMode } from "./js/diet/privacy.js";
import { LABELS, SOURCES } from "./js/diet/sources.js";
import { DIET_PROMPT } from "./js/diet/prompt.js";
import { scrub, toolWord } from "./js/redact.js";

const MAN = { goal: "lose_weight", age: 30, sex: "male", height_cm: 170, weight_kg: 78, activity: "sedentary", conditions: ["none"] };
const json = (x) => JSON.stringify(x);

// ------------------------------------------------------------------ BMI: three scales, and which applies to whom
const band = (scale) => (v) => bmi(v, 100, 40, scale).band; // at 1 m, BMI is the weight
assert.deepEqual([18.4, 18.5, 24.9, 25, 29.9, 30].map(band("who")), ["underweight", "healthy", "healthy", "overweight", "overweight", "obese"]);
assert.deepEqual([22.9, 23, 27.4, 27.5].map(band("asian")), ["healthy", "overweight", "overweight", "obese"]);
assert.deepEqual([23.9, 24, 27.9, 28].map(band("china")), ["healthy", "overweight", "overweight", "obese"]);
assert.equal(bmi(78, 170, 30).value, 27);
assert.equal(bmi(78, 170, 30).scale, "who"); // the international scale by default
assert.equal(bmi(60, 160, 15).band, "not_applicable"); // under 18: BMI-for-age, not adult cut-offs
assert.deepEqual([bmi(33, 100, 40).action_point, bmi(33, 100, 40, "asian").action_point, bmi(36, 100, 40).action_point], [undefined, 32.5, 35]);
// the scale: lower thresholds by family background (NICE, WHO), China's standard in China, else the region's, else WHO's
assert.equal(scaleFor({}).scale, "who"); assert.ok(scaleFor({}).ambiguous);
assert.equal(scaleFor({ region: "SG" }).scale, "asian"); assert.equal(scaleFor({ region: "cn" }).scale, "china");
assert.equal(scaleFor({ region: "US", background: "asian" }).scale, "asian");
assert.equal(scaleFor({ region: "GB", background: "black_african" }).scale, "asian");
assert.equal(scaleFor({ region: "SG", background: "white" }).scale, "who");
assert.ok(scaleFor({ region: "US" }).ambiguous && !scaleFor({ region: "SG" }).ambiguous);
assert.equal(regionOfZone("Asia/Singapore"), "SG"); assert.equal(regionOfZone("America/Los_Angeles"), "US"); assert.equal(regionOfZone("Mars/Base"), null);
assert.ok(Object.values(REGIONS).every((r) => GUIDES[r.guide] && ["N", "S"].includes(r.hemisphere)));
// waist, on the same scale
assert.deepEqual([waistRisk(95, "male").raised, waistRisk(95, "male").high, waistRisk(92, "male", "asian").raised, waistRisk(86, "female", "china").high],
  [true, false, true, true]);
assert.equal(bmi(null, 170), null);

// ------------------------------------------------------------------ energy
assert.equal(ree({ weight: 78, height: 170, age: 30, sex: "male" }), 1698); // 780 + 1062.5 − 150 + 5
assert.equal(ree({ weight: 60, height: 158, age: 45, sex: "female" }), 1202); // 600 + 987.5 − 225 − 161
assert.equal(ree({ weight: 60, height: 158, age: 45, sex: "not_stated" }), null); // no sex for the equation: no number
assert.equal(ree({ weight: 60, height: 158, age: 16, sex: "female" }), null);
assert.deepEqual(tdee(1698, "sedentary").range, [2040, 2210]);
assert.deepEqual(tdee(1698, undefined).range, tdee(1698, "unsure").range); // unknown activity: the cautious range
const t1 = target({ total: tdee(1698, "sedentary"), rest: 1698, sex: "male", mode: "deficit" });
assert.deepEqual([t1.kind, t1.kcal_range, t1.floor_kcal], ["deficit", [1700, 1800], 1700]);
// a small, older woman: a deficit would go below the floor (1,200 kcal or her resting energy): energy kept steady
const rest = ree({ weight: 55, height: 150, age: 50, sex: "female" });
const t2 = target({ total: tdee(rest, "sedentary"), rest, sex: "female", mode: "deficit" });
assert.equal(t2.kind, "maintenance");
assert.match(t2.why, /floor/);
for (const [w, h, a, s, act] of [[120, 180, 25, "male", "high"], [52, 150, 60, "female", "sedentary"], [90, 165, 40, "female", "light"]]) {
  const r = ree({ weight: w, height: h, age: a, sex: s });
  const t = target({ total: tdee(r, act), rest: r, sex: s, mode: "deficit" });
  assert.ok(t.kcal_range[0] >= Math.max(s === "male" ? 1500 : 1200, Math.round(r / 10) * 10), json(t)); // never below the floor
  assert.ok(t.kcal_range[0] < t.kcal_range[1]);
}
assert.deepEqual(protein({ weight: 78, height: 170, age: 30, index: bmi(78, 170), losing: true }).g_range, [80, 95]);
assert.ok(Math.abs(protein({ weight: 100, height: 170, age: 30, index: bmi(100, 170), losing: true }).reference_kg - 72.25) <= 0.25); // BMI 25 at 170 cm
assert.equal(protein({ weight: 78, withheld: true }), null);
// the day's limits by the national guide: WHO's by default
assert.deepEqual([limits(1800).sugar_g.max, limits(1800).sodium_mg.max], [45, 2000]);
assert.deepEqual([limits(1800, "uk").sugar_g.max, limits(1800, "uk").sodium_mg.max], [30, 2400]); // 30 g free sugars, 6 g salt
assert.equal(limits(1800, "us").sodium_mg.max, 2300);
assert.deepEqual(limits(1800, "cn").cooking_oil_g.range, [25, 30]);

// ------------------------------------------------------------------ screening and the next questions
let a = assess({});
assert.equal(a.status, "needs_information");
assert.deepEqual(a.ask_next.map((q) => q.id), ["conditions", "body"]); // safety first, two at most
assert.equal(a.target, null);
a = assess({ conditions: ["none"], age: 30, height_cm: 170, weight_kg: 78 });
assert.deepEqual(a.ask_next.map((q) => q.id), ["sex", "activity"]);
assert.equal(a.bmi.value, 27); // after the first round: BMI already
a = assess(MAN);
assert.equal(a.status, "ready");
assert.deepEqual(a.target.kcal_range, [1700, 1800]);
assert.deepEqual(a.energy.tdee_kcal_range, [2040, 2210]);
assert.deepEqual(a.self_reported.allergies, ["none"]); // "none" to conditions, which lists food allergy, means none
assert.ok(a.ask_next.every((q) => !q.required) && a.ask_next.length <= 2);
assert.ok(a.provenance.every((p) => SOURCES[p.id] && LABELS[p.label]));
// whatever is known, never more than two questions
const fields = [["age", 30], ["height_cm", 170], ["weight_kg", 78], ["sex", "female"], ["activity", "light"], ["conditions", ["diabetes"]],
  ["diet", ["halal"]], ["eating", ["hawker"]], ["after_meal", "bloated"], ["food_style", "warm_cooked"]];
for (let m = 0; m < 1 << fields.length; m += 7) {
  const p = Object.fromEntries(fields.filter((_, i) => m & (1 << i)));
  assert.ok(assess(p).ask_next.length <= 2, json(p));
}
// no automatic deficit: under 18, pregnancy, breastfeeding, insulin or a sulfonylurea, an unlisted or unsure condition
for (const p of [{ ...MAN, age: 16 }, { ...MAN, sex: "female", conditions: ["pregnant"] }, { ...MAN, sex: "female", conditions: ["breastfeeding"] },
  { ...MAN, conditions: ["diabetes", "glucose_lowering_medicine"] }, { ...MAN, conditions: ["diabetes"], diabetes_medicine: "yes" },
  { ...MAN, conditions: ["other"], other_condition: "lupus" }, { ...MAN, conditions: ["unsure"] }]) {
  const r = assess(p);
  assert.equal(r.status, "general_guidance_only", json(p));
  assert.equal(r.target, null, json(p));
  assert.ok(r.flags.length && r.flags.every((f) => f.say), json(p));
  assert.ok(!plan({ profile: p }).energy_target, json(p));
}
// a professional first: an eating disorder (no numbers at all), kidney disease (no protein target), unexplained weight
// loss, and wanting to lose weight while underweight
const ed = assess({ ...MAN, conditions: ["eating_disorder"] });
assert.equal(ed.status, "see_professional_first");
assert.equal(ed.bmi, null); assert.equal(ed.energy, null); assert.equal(ed.limits, null); assert.equal(ed.protein, null);
assert.ok(!ed.ask_next.some((q) => q.id === "body")); // nor asked for their weight
assert.ok(!/"(kcal|protein_g|totals|kcal_range)"/.test(json(plan({ profile: { ...MAN, conditions: ["eating_disorder"] }, days: 2 }))));
const kidney = assess({ ...MAN, conditions: ["kidney_disease"] });
assert.equal(kidney.status, "see_professional_first"); assert.equal(kidney.protein, null);
assert.equal(assess({ ...MAN, conditions: ["unexplained_weight_loss"] }).status, "see_professional_first");
assert.equal(assess({ ...MAN, weight_kg: 50 }).status, "see_professional_first"); // BMI 17.3 and wanting to lose weight
// diabetes: the medicines asked about first; without them, a plan with what to watch
assert.deepEqual(assess({ ...MAN, conditions: ["diabetes"] }).ask_next.map((q) => q.id), ["diabetes_medicine"]);
const dm = assess({ ...MAN, conditions: ["diabetes"], diabetes_medicine: "no" });
assert.equal(dm.status, "ready"); assert.equal(dm.target.kind, "deficit");
assert.ok(dm.flags.some((f) => f.code === "diabetes" && f.effect === "caution"));
// a healthy BMI and wanting to lose weight: no deficit, body composition instead
const fit = assess({ ...MAN, weight_kg: 62 });
assert.equal(fit.target.kind, "maintenance"); assert.ok(fit.flags.some((f) => f.code === "healthy_weight"));
// no goal stated: eating better, no deficit
assert.equal(assess({ ...MAN, goal: undefined }).target.kind, "maintenance");
assert.equal(assess({ ...MAN, age: 80 }).target.kind, "maintenance");
// a food allergy named: which foods, before a plan
assert.deepEqual(assess({ ...MAN, conditions: ["food_allergy"] }).ask_next.map((q) => q.id), ["allergies"]);
// a value out of bounds is reported, not used
assert.ok(assess({ ...MAN, weight_kg: 780 }).problems.some((p) => /weight_kg 780/.test(p)));

// ------------------------------------------------------------------ the dataset
const ids = new Set();
const KINDS = new Set(["main", "side", "snack", "fruit", "drink", "treat"]);
const NUT = ["kcal", "protein_g", "fat_g", "sat_fat_g", "carb_g", "fibre_g", "sugar_g", "sodium_mg"];
assert.ok(DISHES.length >= 60);
for (const d of DISHES) {
  assert.ok(!ids.has(d.id), d.id); ids.add(d.id);
  assert.ok(KINDS.has(d.kind), d.id);
  assert.ok(d.name && d.zh && d.serving && d.slots.length, d.id);
  assert.ok(typeof d.kcal === "number" && d.kcal > 0, d.id);
  for (const k of NUT) assert.ok(d[k] === null || (typeof d[k] === "number" && d[k] >= 0), `${d.id} ${k}`);
  assert.ok(d.allergens.every((x) => ALLERGENS.includes(x) && x !== "none" && x !== "other"), d.id);
  assert.ok(["hpb_coded", "hpb_secondary", "healthhub", "other", "usda"].includes(d.source), d.id);
  assert.ok(d.source === "usda" ? d.usda?.length : /^https:\/\//.test(d.source_url), d.id); // every value has its source
  if (d.source === "hpb_coded") assert.match(d.hpb_code, /^F\d{8}$/);
  if (d.pork) assert.ok(!d.halal, d.id);
  if (d.vegan) assert.ok(d.vegetarian, d.id);
}
assert.equal(dish("chicken_rice_steamed").kcal, 522);
assert.equal(dish("chicken_rice_steamed").hpb_code, "F05100133");
assert.equal(dish("roti_prata_plain_2").kcal, 418); // two pieces of 209
assert.equal(DATASET.status, "secondary_source_unverified");
assert.ok(DISHES.filter((d) => d.kind === "main").length >= 30);

// ------------------------------------------------------------------ plans: hard constraints, sums, swaps
const every = (p) => p.days.flatMap((d) => [...d.meals.flatMap((m) => [m.dish, ...(m.add || [])]), ...d.fruit_and_snacks]).map((x) => dish(x.id));
const rules = [[], ["halal"], ["vegetarian"], ["no_pork"], ["no_beef"], ["no_seafood"], ["halal", "no_seafood"]];
const allergies = [["none"], ...ALLERGENS.filter((x) => !["none", "other"].includes(x)).map((x) => [x]), ["peanut", "crustacean", "mollusc"], ["egg", "soy"]];
let failed = 0;
for (const diet of rules) {
  for (const al of allergies) {
    const p = plan({ profile: { ...MAN, diet, allergies: al }, days: 7 });
    if (!p.ok) { assert.equal(p.constraint_satisfaction, "failed"); failed++; continue; }
    for (const d of every(p)) assert.deepEqual(forbidden(d, { allergies: al, diet }), [], `${d.id} for ${json({ diet, al })}`);
  }
}
assert.ok(failed < rules.length * allergies.length / 4, `${failed} combinations failed`);
const week = plan({ profile: MAN, days: 7 });
assert.equal(week.days.length, 7);
assert.deepEqual(week.energy_target, { kcal_range: [1700, 1800], kind: "deficit" });
for (const d of week.days) {
  const items = [...d.meals.flatMap((m) => [m.dish, ...(m.add || [])]), ...d.fruit_and_snacks];
  for (const x of items) assert.equal(x.kcal, dish(x.id).kcal); // every number is the dataset's own
  assert.equal(d.totals.kcal, Math.round(items.reduce((s, x) => s + x.kcal, 0))); // and the day's total its sum
  const energy = d.checks.find((c) => c.check === "energy");
  assert.ok(energy.ok || /kcal (above|below) the target/.test(energy.say));
  assert.ok(!("sodium_mg" in d.totals) || d.not_totalled === undefined || !d.not_totalled.sodium_mg); // a partial sum is never totalled
}
assert.ok(week.week.days_within_range >= 5, json(week.week));
assert.ok(week.week.different_dishes >= 10, json(week.week));
assert.equal(json(plan({ profile: MAN, days: 7 })), json(week)); // deterministic
// a region's own dishes only there; everyday meals of plain foods everywhere
assert.ok(every(week).every((d) => d.regions.includes("*"))); // no region stated: no country's dishes
const usWeek = plan({ profile: { ...MAN, region: "US" }, days: 7 });
const sgWeek = plan({ profile: { ...MAN, region: "SG" }, days: 7 });
assert.ok(every(usWeek).every((d) => d.regions.includes("*")));
assert.ok(every(sgWeek).some((d) => d.regions.includes("SG")) && every(sgWeek).some((d) => d.regions.includes("*")));
assert.match(usWeek.warnings.join(" "), /No dish data yet for local dishes in United States/);
assert.match(week.warnings.join(" "), /No region stated/);
assert.match(usWeek.drinks, /tea or coffee without sugar/); assert.match(sgWeek.drinks, /kopi-O/);
assert.ok(!/kopi|hawker|Nutri-Grade|MUIS/i.test(json(usWeek))); // nothing of Singapore in a plan for elsewhere
assert.deepEqual(swap({ profile: { ...MAN, region: "US" }, day: usWeek.days[0].meals.map((m) => ({ slot: m.slot, dish_id: m.dish.id })), slot: "lunch", want: "laksa" })
  .day.meals.find((m) => m.slot === "lunch").dish.id, "laksa"); // a dish asked for by name may come from any pack
assert.ok(new Set([0, 1, 2, 3, 4, 5, 6, 7].map((v) => json(plan({ profile: MAN, days: 1, variant: v }).days))).size >= 4); // other variants, other plans
assert.ok(plan({ profile: MAN, exclude: ["chicken_rice_steamed"], days: 7 }).days.every((d) => d.meals.every((m) => m.dish.id !== "chicken_rice_steamed")));
// allergies not confirmed: said, and nothing excluded for them
assert.match(plan({ profile: { goal: "eat_better" } }).warnings.join(" "), /allergies not confirmed/);
// two meals a day, and Ramadan's sahur and iftar
assert.deepEqual(plan({ profile: { ...MAN, meals: 2 } }).days[0].meals.map((m) => m.slot), ["brunch", "dinner"]);
assert.deepEqual(plan({ profile: { ...MAN, diet: ["halal", "ramadan_fasting"] } }).days[0].meals.map((m) => m.slot), ["sahur", "iftar"]);
// nothing meets the constraints: said so, nothing invented
const none = plan({ profile: { ...MAN, allergies: ALLERGENS.filter((x) => !["none", "other"].includes(x)), diet: ["vegan"] } });
assert.equal(none.ok, false); assert.equal(none.constraint_satisfaction, "failed");
// a swap: the whole day re-checked; a dish that breaks a hard limit refused
const day = week.days[0].meals.map((m) => ({ slot: m.slot, dish_id: m.dish.id }));
const sw = swap({ profile: MAN, day, slot: "lunch" });
assert.ok(sw.ok && sw.swapped.from === day[1].dish_id && sw.swapped.to !== day[1].dish_id);
assert.deepEqual(sw.day.meals.filter((m) => m.slot !== "lunch").map((m) => m.dish.id), day.filter((m) => m.slot !== "lunch").map((m) => m.dish_id));
const items = [...sw.day.meals.flatMap((m) => [m.dish, ...(m.add || [])]), ...sw.day.fruit_and_snacks];
assert.equal(sw.day.totals.kcal, Math.round(items.reduce((s, x) => s + x.kcal, 0)));
const wanted = swap({ profile: MAN, day, slot: "dinner", want: "laksa" });
assert.equal(wanted.day.meals.find((m) => m.slot === "dinner").dish.id, "laksa");
const refused = swap({ profile: { ...MAN, allergies: ["peanut"] }, day, slot: "breakfast", want: "nasi_lemak" });
assert.equal(refused.ok, false); assert.deepEqual(refused.why, ["contains peanut (allergy)"]);
assert.equal(swap({ profile: MAN, day, slot: "lunch", want: "no such dish" }).ok, false);
assert.equal(swap({ profile: MAN, day, slot: "supper" }).ok, false);
// the dish lookup: the numbers as published, and what this visitor may not have
const looked = dishes({ query: "chicken rice", cuisine: "chinese", sort: "kcal" });
assert.deepEqual(looked.dishes.map((d) => d.kcal), [471, 522, 646]);
assert.deepEqual(dishes({ query: "nasi lemak", profile: { allergies: ["peanut"] } }).dishes[0].not_for_you, ["contains peanut (allergy)"]);
assert.equal(dishes({ query: "no such dish at all" }).count, 0);

// ------------------------------------------------------------------ the visitor's date, season, solar terms, festivals
assert.equal(localDay(null, "Asia/Singapore", new Date("2026-10-31T16:30:00Z")).iso, "2026-11-01"); // 00:30 in Singapore
assert.equal(localDay(null, "America/New_York", new Date("2026-10-31T16:30:00Z")).iso, "2026-10-31");
assert.equal(localDay("2026-02-30"), null); assert.equal(localDay("2026-13-01"), null);
assert.equal(context({ date: "nonsense" }).ok, false);
const phase = (d, code) => season(localDay(d), region(code)).phase;
// Singapore's monsoons
assert.deepEqual(["2026-12-15", "2027-01-10", "2027-02-10", "2026-04-20", "2026-07-01", "2026-10-15"].map((d) => phase(d, "SG")),
  ["northeast_monsoon_wet", "northeast_monsoon_wet", "northeast_monsoon_dry", "inter_monsoon_1", "southwest_monsoon", "inter_monsoon_2"]);
// temperate seasons by hemisphere; the tropics; South Asia's monsoon
assert.deepEqual(["2027-01-15", "2026-04-15", "2026-07-15", "2026-10-15"].map((d) => phase(d, "GB")), ["winter", "spring", "summer", "autumn"]);
assert.deepEqual(["2027-01-15", "2026-07-15"].map((d) => phase(d, "AU")), ["summer", "winter"]);
assert.equal(phase("2026-07-15", "BR"), "tropical"); assert.equal(phase("2026-07-15", "IN"), "southwest_monsoon");
assert.ok(season(localDay("2026-07-15"), region("AE")).eating[0].startsWith("Extreme heat"));
assert.equal(season(localDay("2026-07-15"), { climate: "temperate", hemisphere: "S" }).phase, "winter"); // as the visitor describes it
assert.equal(season(localDay("2026-07-15"), null).phase, null); // no region: no season, said so
assert.match(season(localDay("2026-07-01"), region("SG")).weather_status, /calendar_only/); // no live weather, said so
// the National Astronomical Observatory of Japan's 2026 almanac (JST), less one hour (China Standard Time)
const NAOJ = { 立春: "2026-02-04T04:02", 春分: "2026-03-20T22:46", 清明: "2026-04-05T02:40", 夏至: "2026-06-21T16:25", 立秋: "2026-08-07T19:43",
  秋分: "2026-09-23T08:05", 立冬: "2026-11-07T17:52", 小雪: "2026-11-22T15:23", 大雪: "2026-12-07T10:53", 冬至: "2026-12-22T04:50" };
for (const t of termsOf(2026)) {
  if (!NAOJ[t.zh]) continue;
  const off = Math.abs(Date.parse(`${t.cst_time.replace(" ", "T")}:00Z`) - Date.parse(`${NAOJ[t.zh]}:00Z`)) / 60000;
  assert.ok(off <= 15, `${t.zh} ${t.cst_time} vs ${NAOJ[t.zh]}`);
  assert.equal(t.date, NAOJ[t.zh].slice(0, 10));
}
assert.equal(termsOf(2026).length, 24);
const st = solarTerm(localDay("2026-11-01"), region("SG"));
assert.deepEqual([st.current.zh, st.next.zh, st.next.date, st.next.in_days], ["霜降", "立冬", "2026-11-07", 6]);
assert.match(st.note, /does not carry over/);
assert.match(solarTerm(localDay("2026-11-01"), region("AU")).note, /reversed/);
assert.match(solarTerm(localDay("2026-11-01"), region("CN")).note, /corpus tools/);
// festivals: computed where a rule fixes them, those kept where the visitor lives first
assert.deepEqual([easter(2024), easter(2025), easter(2026), easter(2027)], [[3, 31], [4, 20], [4, 5], [3, 28]]);
const due = (day, code, within) => festivals(localDay(day), within, code).upcoming.map((f) => [f.id, f.date, f.in_days]);
assert.deepEqual(due("2026-11-01", "SG"), [["diwali", "2026-11-08", 7], ["dongzhi", "2026-12-22", 51], ["christmas", "2026-12-25", 54]]);
assert.deepEqual(due("2026-11-01", "US").slice(0, 2), [["thanksgiving_us", "2026-11-26", 25], ["christmas", "2026-12-25", 54]]);
assert.deepEqual(due("2026-10-01", "CA", 30), [["thanksgiving_ca", "2026-10-12", 11]]);
assert.ok(!due("2026-11-01", "GB").some(([id]) => id.startsWith("thanksgiving"))); // kept in one country only
assert.equal(festivals(localDay("2026-11-01"), 60, "US").upcoming.find((f) => f.id === "diwali").kept_where_you_live, false);
assert.ok(festivals(localDay("2026-03-01"), 60, "MY").upcoming.some((f) => f.id === "ramadan" && f.ongoing && f.approximate));
assert.match(festivals(localDay("2028-06-01")).note, /No published festival dates here for 2028/);
const ctx = context({ date: "2026-11-01", region: "SG" });
assert.deepEqual([ctx.region.code, ctx.region.time_zone, ctx.season.phase], ["SG", "Asia/Singapore", "inter_monsoon_2"]);
assert.equal(context({ date: "2026-11-01" }).region.code, null);
assert.ok(ctx.provenance.every((p) => SOURCES[p.id]));

// ------------------------------------------------------------------ the weekly review
const entries = (kgs, step = 7) => kgs.map((kg, i) => ({ date: new Date(Date.UTC(2026, 9, 1) + i * step * 864e5).toISOString().slice(0, 10), weight_kg: kg }));
assert.equal(progress({ profile: MAN, entries: entries([78, 77.8]) }).verdict, "too_early");
assert.equal(progress({ profile: MAN, entries: entries([78, 77.6, 77.3, 76.9, 76.5]) }).verdict, "on_track");
assert.equal(progress({ profile: MAN, entries: entries([78, 76.6, 75.2, 73.8, 72.4]) }).verdict, "faster_than_planned");
assert.equal(progress({ profile: MAN, entries: entries([78, 78.1, 77.9, 78, 78]) }).verdict, "plateau");
assert.equal(progress({ profile: MAN, entries: entries([78, 78.4, 78.9, 79.3, 79.8]) }).verdict, "rising");
assert.equal(progress({ profile: { ...MAN, goal: "maintain" }, entries: entries([78, 78.1, 77.9, 78, 78]) }).verdict, "stable");
const quiet = progress({ profile: { ...MAN, conditions: ["eating_disorder"] }, entries: entries([78, 77, 76, 75]) });
assert.equal(quiet.reviewed, false); assert.ok(!/kg/.test(json(quiet)));
assert.equal(progress({ entries: [] }).ok, false);

// ------------------------------------------------------------------ the traditional layer: never a diagnosis
const n = natures(["durian", "mango", "pearl barley", "kopi", "西瓜"]);
assert.deepEqual(n.found.map((f) => f.food).sort(), ["barley (barley water, unsweetened)", "durian", "watermelon"]);
assert.equal(n.found.find((f) => f.food === "durian").everyday, "heaty");
assert.deepEqual(n.disputed.map((f) => f.food), ["mango", "coffee / kopi"]);
assert.ok(!n.found.some((f) => f.food === "pear")); // "pearl" is no pear
const dry = preference({ food_style: "dry_mouth" });
assert.match(dry.advice.join(" "), /doctor/); assert.equal(dry.tcm_pattern_status, "unconfirmed");
const fn = foodNature({ foods: ["ginger"], after_meal: "bloated", food_style: "warm_cooked" });
assert.equal(fn.tcm_pattern_status, "unconfirmed");
assert.ok(!/痰湿.*(是|为)你|you have/i.test(json(fn)));
assert.ok(plan({ profile: { ...MAN, food_style: "light_cool" } }).preference.boundary.includes("not a TCM diagnosis"));

// ------------------------------------------------------------------ the tools as the model is offered them
assert.deepEqual(DIET_TOOLS.map((t) => t.name), ["diet__assess", "diet__plan", "diet__swap", "diet__dishes", "diet__context", "diet__food_nature", "diet__progress"]);
for (const t of DIET_TOOLS) {
  assert.match(t.name, /^diet__[a-z_]+$/); assert.equal(t.parameters.type, "object"); assert.ok(t.description.length > 40);
  assert.ok(toolWord(t.name) && !/工具$/.test(toolWord(t.name)), t.name); // plain words of its own (redact.js)
}
assert.ok(isDiet("diet__plan") && isDiet("diet.plan") && !isDiet("classics__search") && !isDiet("dietary"));
assert.equal(dietName("Diet__Plan"), "diet.plan");
const out = callDiet("diet__assess", { profile: MAN });
assert.ok(out.ok && out.tool === "diet.assess" && JSON.parse(out.text).status === "ready" && out.citations.length === 0);
assert.match(out.summary, /BMI 27 · 1700–1800 kcal/);
assert.equal(callDiet("diet__nothing", {}).ok, false);
assert.equal(callDiet("diet__swap", { profile: MAN, day: [], slot: "supper" }).ok, false);
assert.ok(callDiet("diet__plan", { profile: MAN, days: 7 }).text.length <= 16000); // a week within a tool result's budget
assert.match(callDiet("diet__plan", { profile: MAN, days: 7 }, { maxChars: 3000 }).text, /truncated: ask for fewer days/);
assert.equal(scrub("以上由 diet__plan 核算，见 diet.assess。").text, "以上由饮食方案核算，见饮食评估。");
assert.match(DIET_PROMPT, /每轮至多两问/); assert.match(DIET_PROMPT, /diet__assess/); assert.match(DIET_PROMPT, /unconfirmed/);

// ------------------------------------------------------------------ which conversations carry health information
for (const t of ["我身高170，体重78公斤，想减肥", "I am 170 cm and 78 kg", "I have diabetes, what should I eat?", "my blood sugar is 8.2",
  "我怀孕了能吃榴莲吗", "I'm allergic to peanuts", "saya hamil", "BMI 28 怎么办"]) assert.ok(healthText(t), t);
for (const t of ["桂枝汤的原方组成与剂量出自哪里？", "「消渴」与糖尿病的异同", "Tell me about the medication in the Shanghan Lun", "古人身高八尺",
  "黄芪 30 克的用法", "What did Zhang Zhongjing say about diabetes?"]) assert.ok(!healthText(t), t);
assert.ok(isDietMode({ mode: "diet" }) && healthConv({ mode: "diet", messages: [] }));
assert.ok(healthConv({ messages: [{ role: "assistant", segments: [{ type: "tools", calls: [{ name: "diet__dishes" }] }] }] }));
assert.ok(healthConv({ messages: [{ role: "assistant", segments: [{ type: "tools", calls: [{ name: "taochronos_call", args: { tool: "diet.plan" } }] }] }] }));
assert.ok(healthConv({ messages: [{ role: "user", text: "我体重 80 公斤" }] }));
assert.ok(healthConv({ health: true, messages: [] }));
assert.ok(!healthConv({ messages: [{ role: "user", text: "桂枝汤主治什么？" }] }));
console.log("ok");
"""


def test_the_diet_engine_under_node(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    shutil.copytree(ROOT / "web" / "js", tmp_path / "js")
    (tmp_path / "package.json").write_text('{"type": "module"}')
    (tmp_path / "t.mjs").write_text(NODE_DIET, encoding="utf-8")
    run = subprocess.run([node, "t.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0 and run.stdout.strip() == "ok", run.stderr[-3000:]


def test_the_dish_module_is_what_its_sources_make(tmp_path):
    """web/js/diet/dishes.js is generated from data/diet (the collected records and the script's annotations): written
    again, it is the same file — no value was edited by hand."""
    out = tmp_path / "dishes.js"
    run = subprocess.run(["python3", "-I", str(ROOT / "data" / "diet" / "make_dishes.py"), str(ROOT / "data" / "diet" / "sg-dishes.sources.json"),
                          str(out)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr[-2000:]
    assert out.read_text(encoding="utf-8") == (ROOT / "web" / "js" / "diet" / "dishes.js").read_text(encoding="utf-8")


def test_the_page_never_records_health(tmp_path):
    """The guards in the page's own code: a turn's record and a feedback's attachment both ask about health, and a diet
    conversation's tools are routed to the page before any runtime (the browser test below shows them at work)."""
    app = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
    assert "if (!recording() || personal(conv) || healthConv(conv)) return;" in app
    assert "const mine = personal(conv) || healthConv(conv);" in app
    assert "if (isDiet(name)) return Promise.resolve(callDiet(name, args, options));" in app
    store = (ROOT / "web" / "js" / "store.js").read_text(encoding="utf-8")
    assert "if (conv?.ephemeral) return;" in store
    # the diet mode reaches no network of its own: no fetch, no geolocation
    for js in (ROOT / "web" / "js" / "diet").glob("*.js"):
        text = js.read_text(encoding="utf-8")
        assert "fetch(" not in text and "geolocation" not in text and "XMLHttpRequest" not in text, js.name


def test_a_diet_conversation_in_the_browser(tmp_path):
    """A visitor who agreed to conversation records opens 饮食与体重管理: the model is offered the diet tools (and the
    corpus search only), with the mode's instructions; its calls run in the page — the server hears nothing of them — and
    the turn is never recorded; feedback carries no word of it; the conversation is gone after a reload until the visitor
    keeps it.  An ordinary conversation in which the visitor gives their weight is not recorded either; one without is."""
    from test_web_client import _chromium, _published

    exe = _chromium()
    if exe is None:
        pytest.skip("playwright is not installed")
    from playwright.sync_api import Error, sync_playwright

    from taochronos.chat import ChatRuntime
    from taochronos.chat.server import ChatServer
    from web_mock import MockProvider, MockRelay

    mock = MockProvider().start()
    relay = MockRelay(mock.base_url).start()
    web = tmp_path / "web"
    _published(web, relay.url)
    rt = ChatRuntime.create("full-discovery", kind="server", ephemeral=True, data_dir=tmp_path / "data")
    srv = ChatServer(("127.0.0.1", 0), rt, web_root=web, home=ROOT)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    agreed = {"v": 1, "logs": True, "at": "2026-11-01T00:00:00Z"}
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(**({"executable_path": exe} if exe else {}))
            except Error as exc:
                pytest.skip(f"no Chromium for Playwright: {exc}")
            ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="zh-CN")
            ctx.add_init_script(f"localStorage.setItem('tc.consent', {json.dumps(json.dumps(agreed))});")
            page = ctx.new_page()
            errors: list[str] = []
            sent: list[str] = []  # what the page asked of its own server, beyond its files
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("request", lambda r: sent.append(f"{r.method} {r.url} {r.post_data or ''}")
                    if r.url.startswith(url) and (r.method != "GET" or "/api/" in r.url) else None)
            page.goto(url)
            page.wait_for_selector(".runtime-pill .dot.ok", timeout=30000)
            page.wait_for_function("document.querySelector('.hero .keyhint')?.textContent.includes('默认服务')", timeout=15000)

            def answered(n):
                page.wait_for_function(f"document.querySelectorAll('.msg.assistant .actions').length >= {n}", timeout=60000)

            # the way in: from the side bar; the mode's opening screen
            page.click("#new-diet")
            page.wait_for_selector(".diet-hero")
            assert "不记录" in page.inner_text(".diet-notice") and "饮食与体重管理" in page.inner_text(".diet-hero h1")
            assert "外面吃饭" in page.get_attribute("#input", "placeholder")
            before = len(mock.requests)
            page.fill("#input", "我想减重，30 岁男性，170 厘米，78 公斤，久坐，没有其他疾病。")
            page.keyboard.press("Enter")
            answered(1)
            assert page.query_selector("#consent[open]") is None
            diet_requests = mock.requests[before:]
            assert len(diet_requests) == 3  # assessed, planned, answered
            offered = {t["function"]["name"] for t in diet_requests[0]["body"]["tools"]}
            assert {t for t in offered if t.startswith("diet__")} == {"diet__assess", "diet__plan", "diet__swap", "diet__dishes", "diet__context",
                                                                     "diet__food_nature", "diet__progress"}
            assert offered - {t for t in offered if t.startswith("diet__")} <= {"classics__search", "classics__get_passage"}
            system = diet_requests[0]["body"]["messages"][0]["content"]
            assert "## 本对话：饮食与体重管理" in system and "每轮至多两问" in system and "国际（WHO）的默认标准" in system
            # the tools' results went back to the model: the plan of the day, its energy target
            plan_result = json.loads([m for m in diet_requests[2]["body"]["messages"] if m.get("role") == "tool"][-1]["content"])
            assert plan_result["energy_target"] == {"kcal_range": [1700, 1800], "kind": "deficit"} and plan_result["days"][0]["meals"]
            steps = page.eval_on_selector_all(".msg.assistant .steps", "els => els.map((e) => e.textContent).join(' ')")
            assert "饮食评估" in steps and "饮食方案" in steps and "diet__" not in steps
            assert "以上由饮食方案核算" in page.inner_text(".msg.assistant .md")
            assert "本对话不发送记录" in page.inner_text(".diet-banner")
            # nothing of it to the server, and no record though the visitor agreed to records
            assert not [s for s in sent if "diet" in s or "weight_kg" in s or "78 公斤" in s], sent
            time.sleep(2)
            assert relay.records == []
            # feedback: never the conversation's words
            page.click(".msg.assistant .rate[data-rate='up']")
            page.wait_for_selector("#feedback[open]")
            assert "涉及你的健康信息" in page.inner_text("#feedback") and page.query_selector("#feedback input[type=checkbox]") is None
            page.click("#feedback .modal-foot .btn:not(.secondary)")
            page.wait_for_function("!document.querySelector('#feedback[open]')", timeout=10000)
            [fb] = relay.feedback
            assert fb["rating"] == "up" and "question" not in fb and "answer" not in fb
            # kept only in the page: gone after a reload
            page.reload()
            page.wait_for_selector(".runtime-pill .dot.ok", timeout=30000)
            assert page.query_selector("#convs .conv") is None
            # kept in this browser when the visitor chooses
            page.click("#new-diet")
            page.fill("#input", "鸡饭和叻沙哪个热量低？")
            page.keyboard.press("Enter")
            answered(1)
            page.click(".diet-banner button")
            page.wait_for_function("document.querySelector('.diet-banner').textContent.includes('已保存在本浏览器')")
            page.reload()
            page.wait_for_selector("#convs .conv .conv-tag", timeout=30000)
            time.sleep(1)
            assert relay.records == []

            # an ordinary conversation in which the visitor gives their own weight: not recorded; one without: recorded
            page.click("#new-chat")
            page.fill("#input", "我体重 80 公斤，桂枝汤主治什么？")
            page.keyboard.press("Enter")
            page.wait_for_selector(".msg.assistant .verify-bar", timeout=60000)
            time.sleep(2)
            assert relay.records == []
            page.click("#new-chat")
            page.fill("#input", "桂枝汤主治什么？")
            page.keyboard.press("Enter")
            page.wait_for_selector(".msg.assistant .verify-bar", timeout=60000)
            end = time.time() + 20
            while not relay.records and time.time() < end:
                time.sleep(0.2)
            assert [r["question"] for r in relay.records] == ["桂枝汤主治什么？"]
            assert not errors, errors
            browser.close()
    finally:
        srv.shutdown()
        srv.server_close()
        relay.shutdown()
        mock.shutdown()
