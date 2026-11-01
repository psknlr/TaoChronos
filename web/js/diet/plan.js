// Plans from the dish data: a day or a week, everywhere from everyday meals made of plain foods (USDA values), and in a
// region with a dish pack (Singapore and Malaysia: hawker and kopitiam dishes as HPB analysed them) from its own dishes
// too (dishes.js), each with what to add to make the plate (a vegetable side, fruit) and how to order or cook it.  Hard
// constraints are never traded away: allergens, halal, vegetarian, no beef or pork, and the screening of assess.js (a plan
// has an energy target only when screening allows one; with an eating disorder it shows no numbers at all).  Within them
// it prefers what fits the meal's share of the target, varied across the week, lower in sodium and saturated fat, higher
// in protein and vegetables, and in the style asked for.  Every total is the sum of the dataset's values; a nutrient
// missing for a dish is reported missing, never filled in.  A swap rebuilds and re-checks the whole day.

import { assess } from "./assess.js";
import { DATASET, DISHES } from "./dishes.js";
import { preference } from "./tcm.js";
import { region as regionOf } from "./regions.js";
import { ALGORITHM, provenance } from "./sources.js";

const NUTRIENTS = ["kcal", "protein_g", "fat_g", "sat_fat_g", "carb_g", "fibre_g", "sugar_g", "sodium_mg"];
const BY_ID = new Map(DISHES.map((d) => [d.id, d]));
export const dish = (id) => BY_ID.get(id) || null;

// each meal's share of the day's energy left after fruit, by how many meals are eaten
const SHARES = {
  3: [["breakfast", 0.27], ["lunch", 0.38], ["dinner", 0.35]],
  2: [["brunch", 0.45], ["dinner", 0.55]],
  ramadan: [["sahur", 0.42], ["iftar", 0.58]],
};
const SLOT_FROM = { brunch: ["breakfast", "lunch"], sahur: ["breakfast", "lunch", "dinner"], iftar: ["lunch", "dinner"] };

// ------------------------------------------------------------------ constraints
/** Why `d` may not be in this visitor's plan (a list of reasons; empty when it may). */
export function forbidden(d, pf) {
  const why = [];
  for (const a of pf.allergies || []) if (d.allergens.includes(a)) why.push(`contains ${a} (allergy)`);
  const diet = pf.diet || [];
  if (diet.includes("halal") && (!d.halal || d.pork)) why.push("not commonly sold halal");
  if (diet.includes("vegetarian") && !d.vegetarian) why.push("not vegetarian");
  if (diet.includes("vegan") && !d.vegan) why.push("not vegan");
  if (diet.includes("no_pork") && d.pork) why.push("contains pork or lard");
  if (diet.includes("no_beef") && d.beef) why.push("contains beef");
  if (diet.includes("no_seafood") && (d.allergens.includes("fish") || d.allergens.includes("crustacean") || d.allergens.includes("mollusc"))) {
    why.push("contains seafood");
  }
  return why;
}

/** A dish in a few numbers per 100 kcal, for ranking: protein, sodium, saturated fat; unknown stays unknown. */
function quality(d, style = { prefer: [], avoid: [] }) {
  let q = 0;
  if (d.kcal) {
    if (d.protein_g != null) q += Math.min(1, (d.protein_g / d.kcal) * 100 / 8) * 0.8; // 8 g per 100 kcal: full marks
    if (d.sodium_mg != null) q -= Math.max(0, (d.sodium_mg / d.kcal - 2) / 3) * 0.6; // over 2 mg a kcal begins to count
    if (d.sat_fat_g != null) q -= Math.max(0, (d.sat_fat_g * 9) / d.kcal - 0.1) * 3;
  }
  if (d.tags.includes("fried")) q -= 0.3;
  if (d.tags.includes("vegetables")) q += 0.3;
  if (d.tags.includes("wholegrain")) q += 0.2;
  if (d.tags.includes("home")) q += style.home ?? -0.2; // home cooking, for those who cook; else a little behind what they buy
  for (const t of style.prefer) if (d.tags.includes(t)) q += 0.15;
  for (const t of style.avoid) if (d.tags.includes(t)) q -= 0.25;
  return q;
}

// a small deterministic jitter, so that dishes alike in every other way take turns (FNV-1a)
function jitter(...parts) {
  let x = 0x811c9dc5;
  for (const c of parts.join("|")) { x ^= c.charCodeAt(0); x = Math.imul(x, 0x01000193) >>> 0; }
  return (x % 1000) / 1000;
}

const sum = (items) => {
  const total = {};
  const missing = {};
  for (const k of NUTRIENTS) {
    let s = 0;
    for (const it of items) {
      const v = it[k];
      if (v == null) (missing[k] ||= []).push(it.id); else s += v * (it.times || 1);
    }
    total[k] = Math.round(s);
  }
  return { total, missing };
};

// ------------------------------------------------------------------ a day
const PLATE_SLOTS = new Set(["lunch", "dinner", "brunch", "iftar"]); // the meals a vegetable side completes

function sides(d, need, slot) {
  const add = [];
  if (need.veg && PLATE_SLOTS.has(slot) && !d.tags.includes("vegetables") && d.kind === "main") add.push(need.veg);
  return add;
}

/** The pieces a day needs besides its mains: a vegetable side for mains without vegetables, fruit twice. */
/** Is `d` among the dishes a plan for this visitor's region picks by itself: everyday meals of plain foods everywhere,
 * a region's own dishes (its dish pack) only there.  A dish asked for by name may come from anywhere. */
export const here = (d, pf) => d.regions.includes("*") || (pf.region && d.regions.includes(pf.region));

function extras(pf) {
  const ok = (id) => { const d = dish(id); return d && here(d, pf) && !forbidden(d, pf).length ? d : null; };
  const veg = ok("side_vegetables_blanched") || ok("side_vegetables"); // the stall's side where there is one, else plain vegetables
  const fruit = DISHES.filter((d) => d.kind === "fruit" && d.kcal != null && here(d, pf) && !forbidden(d, pf).length);
  return { veg, fruit };
}

function candidates(slot, pf, used, exclude) {
  const from = SLOT_FROM[slot] || [slot];
  return DISHES.filter((d) => d.kind === "main" && d.kcal != null && d.slots.some((s) => from.includes(s)) && !exclude.has(d.id)
    && here(d, pf) && !forbidden(d, pf).length);
}

/** A day: each slot's dish chosen to fit its share of `kcal` (or, without a target, by quality alone). */
function buildDay({ pf, kcal, slots, k, seed, used, exclude, style, fixed = {} }) {
  const need = extras(pf);
  const fruit = need.fruit.length ? [need.fruit[(k * 2) % need.fruit.length], need.fruit[(k * 2 + 1) % need.fruit.length]] : [];
  const fruitKcal = fruit.reduce((a, f) => a + (f.kcal || 0), 0);
  const left = kcal ? kcal - fruitKcal : null;
  const meals = [];
  for (const [slot, share] of slots) {
    let pick = fixed[slot] ? dish(fixed[slot]) : null;
    if (!pick) {
      const goal = left ? left * share : null;
      let best = null;
      for (const d of candidates(slot, pf, used, exclude)) {
        const withSides = d.kcal + sides(d, need, slot).reduce((a, s) => a + (s.kcal || 0), 0);
        const fit = goal ? -Math.abs(withSides - goal) / goal * 2.5 : 0;
        // another variant: the jitter weighs enough to bring other dishes of near quality forward
        const score = fit + quality(d, style) - repeats(used, d.id, k) + jitter(seed, k, slot, d.id) * (seed ? 0.8 : 0.12);
        if (!best || score > best.score) best = { d, score };
      }
      pick = best?.d || null;
    }
    if (!pick) { meals.push({ slot, dish: null, problem: "no dish in the dataset meets every constraint for this meal" }); continue; }
    used.set(pick.id, [...(used.get(pick.id) || []), k]); // the next meal of the day is told
    meals.push({ slot, dish: pick, add: sides(pick, need, slot) });
  }
  return { meals, fruit };
}

/** A day's totals and checks against the target and the limits. */
function checkDay(day, ctx) {
  const items = [];
  for (const m of day.meals) if (m.dish) items.push(m.dish, ...(m.add || []));
  items.push(...day.fruit);
  const { total, missing } = sum(items);
  const checks = [];
  if (ctx.range && missing.kcal) {
    checks.push({ check: "energy", ok: false, say: "energy unknown for some item: the day was not checked" });
  } else if (ctx.range) {
    const [lo, hi] = ctx.range;
    if (total.kcal > hi) checks.push({ check: "energy", ok: false, say: `about ${total.kcal - hi} kcal above the target range ${lo}–${hi}` });
    else if (total.kcal < lo) checks.push({ check: "energy", ok: false, say: `about ${lo - total.kcal} kcal below the target range ${lo}–${hi}: add a snack or a larger portion` });
    else checks.push({ check: "energy", ok: true, say: `within the target range ${lo}–${hi}` });
  }
  if (!missing.sodium_mg) { // only a complete sum is compared with a limit
    checks.push(total.sodium_mg > 2000
      ? { check: "sodium", ok: false, say: `sodium ${total.sodium_mg} mg is over the 2,000 mg limit: leave the gravy and soup, ask for less sauce` }
      : { check: "sodium", ok: true, say: `sodium ${total.sodium_mg} mg, within 2,000 mg` });
  }
  if (ctx.protein && !missing.protein_g) {
    const [plo] = ctx.protein;
    checks.push(total.protein_g >= plo ? { check: "protein", ok: true, say: `protein ${total.protein_g} g (aim ${ctx.protein[0]}–${ctx.protein[1]} g)` }
      : { check: "protein", ok: false, say: `protein ${total.protein_g} g, below the ${plo} g aimed for: add an egg, tofu, fish or unsweetened soya milk` });
  }
  if (ctx.satfat && !missing.sat_fat_g && total.sat_fat_g > ctx.satfat) {
    checks.push({ check: "saturated_fat", ok: false, say: `saturated fat ${total.sat_fat_g} g, over about ${ctx.satfat} g` });
  }
  return { total, missingIds: missing, checks };
}

const mealKcal = (m) => (m.dish ? m.dish.kcal + (m.add || []).reduce((a, x) => a + (x.kcal || 0), 0) : 0);
const dayKcal = (day) => day.meals.reduce((a, m) => a + mealKcal(m), 0) + day.fruit.reduce((a, f) => a + (f.kcal || 0), 0);
const repeats = (used, id, k) => (used.get(id) || []).reduce((a, day) => a + (day === k ? 2 : Math.abs(k - day) <= 2 ? 0.8 : 0.2), 0);

/** Bring a day within the range, a step at a time: of every replacement of one meal (and, when short, every snack or
 * fruit to add), the one that lands nearest the range — the best in quality and least repeated among equals; a day
 * that cannot be brought in keeps its best and says by how much it misses. */
function balance(day, { range, pf, exclude, style, used, k, fixed = {} }) {
  if (!range) return day;
  const [lo, hi] = range;
  const need = extras(pf);
  const off = (t) => (t > hi ? t - hi : t < lo ? lo - t : 0);
  for (let i = 0; i < 4; i++) {
    const total = dayKcal(day);
    if (!off(total)) break;
    let best = null;
    const consider = (t, score, next) => {
      const s2 = -(off(t) / hi) * 6 + score;
      if (off(t) < off(total) && (!best || s2 > best.score)) best = { score: s2, next };
    };
    day.meals.forEach((m, at) => {
      if (!m.dish || fixed[m.slot]) return;
      for (const d of candidates(m.slot, pf, used, exclude)) {
        if (d.id === m.dish.id) continue;
        const add = sides(d, need, m.slot);
        const t = total - mealKcal(m) + d.kcal + add.reduce((a, x) => a + (x.kcal || 0), 0);
        if (day.meals.some((x, j) => j !== at && x.dish?.id === d.id)) continue; // not the same dish twice in a day to fit a number
        consider(t, quality(d, style) - repeats(used, d.id, k) + jitter(k, m.slot, d.id) * 0.05,
          () => ({ ...day, meals: day.meals.map((x, j) => (j === at ? { slot: m.slot, dish: d, add } : x)) }));
      }
    });
    if (total < lo) {
      for (const d of DISHES) {
        if ((d.kind !== "snack" && d.kind !== "fruit") || d.kcal == null || !here(d, pf) || forbidden(d, pf).length || day.fruit.includes(d) || exclude.has(d.id)) continue;
        consider(total + d.kcal, quality(d, style) + 0.2, () => ({ ...day, fruit: [...day.fruit, d] })); // a snack keeps the meals as chosen
      }
    }
    if (!best) break;
    day = best.next();
  }
  return day;
}

// ------------------------------------------------------------------ what a plan shows
const SHOWN = ["kcal", "protein_g", "carb_g", "sodium_mg"]; // a meal's numbers in a plan (the dish lookup shows them all)
const source = (d) => (d.source === "usda" ? "USDA FoodData Central" : `${d.publisher}${d.source === "hpb_coded" ? `, HPB ${d.hpb_code}`
  : d.source === "hpb_secondary" ? ", quoting HPB" : ""}`);
const nums = (d, keys, quiet) => (quiet ? {} : Object.fromEntries(keys.filter((k) => d[k] != null).map((k) => [k, d[k]])));
const shown = (d, quiet, keys = NUTRIENTS) => ({ id: d.id, name: d.name, zh: d.zh, serving: d.serving, ...nums(d, keys, quiet),
  allergens: d.allergens.length ? d.allergens : undefined, order: d.order || undefined, source: source(d) });
const brief = (d, quiet) => ({ id: d.id, name: d.name, zh: d.zh, serving: d.serving, ...nums(d, ["kcal", "protein_g"], quiet),
  allergens: d.allergens.length ? d.allergens : undefined });

/** A day's totals: each nutrient summed only where every item has it; the others say for how many it is known. */
function totals(check, count) {
  const out = {};
  const partial = {};
  for (const k of NUTRIENTS) {
    if (check.missingIds[k]) partial[k] = `known for ${count - check.missingIds[k].length} of ${count} items: not totalled`;
    else out[k] = check.total[k];
  }
  return { totals: out, not_totalled: Object.keys(partial).length ? partial : undefined };
}

function showDay(day, k, ctx, first = true) {
  const check = checkDay(day, ctx);
  const count = day.meals.reduce((a, m) => a + (m.dish ? 1 + (m.add || []).length : 0), 0) + day.fruit.length;
  const out = {
    day: k + 1,
    meals: day.meals.map((m) => (m.dish ? { slot: m.slot, dish: shown(m.dish, ctx.quiet, SHOWN), add: m.add?.length ? m.add.map((x) => brief(x, ctx.quiet)) : undefined } : m)),
    fruit_and_snacks: day.fruit.map((f) => brief(f, ctx.quiet)),
  };
  if (!first) for (const m of out.meals) if (m.dish) { delete m.dish.order; delete m.dish.source; }
  if (!ctx.quiet) Object.assign(out, totals(check, count), { checks: check.checks });
  const twice = day.meals.filter((m, i) => m.dish && day.meals.findIndex((x) => x.dish?.id === m.dish.id) !== i);
  if (twice.length) out.note = `the same dish twice in a day: few dishes in the dataset meet every restriction`;
  return out;
}

// what to drink, said as people order it where they live
const DRINKS = {
  default: "water through the day; tea or coffee without sugar if you like; for packaged drinks, check the sugar on the label",
  SG: "water through the day; kopi-O or teh-O kosong (no sugar) or siew dai (less sugar) if you like; Nutri-Grade A or B for packaged drinks",
  MY: "water through the day; kopi-O or teh-O kosong (no sugar) or kurang manis (less sugar) if you like",
};

/** Read the plan's options: days 1–7, meals 2 or 3 (or the Ramadan pair), dishes to leave out, a variant number. */
function options(args, pf) {
  const days = Math.max(1, Math.min(7, Math.round(Number(args.days) || 1)));
  const ramadan = (pf.diet || []).includes("ramadan_fasting");
  const meals = ramadan ? "ramadan" : Number(args.meals || pf.meals) === 2 ? 2 : 3;
  const exclude = new Set((Array.isArray(args.exclude) ? args.exclude : []).map(String));
  return { days, meals, slots: SHARES[meals], exclude, seed: Number.isFinite(Number(args.variant)) ? Number(args.variant) : 0 };
}

function context(args) {
  const a = assess(args.profile || {});
  const pf = { ...(args.profile || {}), allergies: a.self_reported.allergies || null, diet: a.self_reported.diet || [], region: a.self_reported.region || null };
  const quiet = a.bmi === null && a.flags.some((f) => f.code === "eating_disorder");
  const range = a.target?.kcal_range || null;
  const kcal = range ? Math.round((range[0] + range[1]) / 2) : null;
  const style = preference({ after_meal: a.self_reported.after_meal, food_style: a.self_reported.food_style });
  const eating = a.self_reported.eating || [];
  style.home = eating.some((e) => e === "home_cooking" || e === "quick_cooking") ? 0.35
    : eating.length && eating.every((e) => ["eating_out", "takeaway", "workplace_canteen"].includes(e)) ? -1 : -0.2;
  return { a, pf, quiet, range, kcal, style, protein: a.protein?.g_range || null, satfat: a.limits?.saturated_fat_g?.max || null };
}

function header(c, extra = {}) {
  const warn = [];
  if (!c.pf.allergies) warn.push("Food allergies not confirmed yet: ask before anyone prepares or eats these meals; no dish was excluded for an allergen.");
  if ((c.pf.allergies || []).includes("other")) warn.push(`An allergy the dataset does not tag (${c.a.self_reported.other_allergy || "other"}): check every dish and ingredient yourself.`);
  if ((c.pf.allergies || []).filter((x) => x !== "none").length) warn.push("Allergen marks are the dishes' usual ingredients; recipes and products differ — with a food allergy, check labels and ask whoever cooks, every time.");
  if ((c.pf.diet || []).includes("halal")) warn.push("Halal: use halal-certified meat and products, and certified stalls when eating out (e.g. MUIS in Singapore, JAKIM in Malaysia).");
  const r = regionOf(c.pf.region);
  if (!r) warn.push("No region stated: the meals are everyday dishes made of plain foods; ask where the user lives for their country's food guide and local dishes.");
  else if (!r.packs.length) warn.push(`No dish data yet for local dishes in ${r.name}: the meals are everyday dishes made of plain foods (USDA values); local dishes can be suggested in words, without numbers.`);
  return {
    ok: true, algorithm: ALGORITHM, status: c.a.status,
    energy_target: c.quiet ? null : c.range ? { kcal_range: c.range, kind: c.a.target.kind } : null,
    why_no_target: c.range || c.quiet ? undefined : c.a.flags.map((f) => f.say).join(" ") || c.a.status_means,
    flags: c.a.flags, warnings: warn.length ? warn : undefined, ...extra,
    nutrition_validation: c.quiet ? "numbers withheld" : `computed from the dataset (${DATASET.status}): ${DATASET.note}`,
    dataset: { id: DATASET.id, version: DATASET.version, dishes: DISHES.length },
    preference: c.style.advice.length ? { advice: c.style.advice, tcm_pattern_status: "unconfirmed", boundary: c.style.boundary } : undefined,
    provenance: provenance(["hpb_dish_composition", "usda_fdc", "hpb_healthy_plate", "hpb_sodium", ...(c.range ? ["mifflin_st_jeor", "activity_factors"] : []),
      ...(c.style.advice.length ? ["tcm_food_nature"] : [])]),
  };
}

/** The tool: a day or a week of meals. */
export function plan(args = {}) {
  const c = context(args);
  const o = options(args, c.pf);
  const used = new Map();
  const days = [];
  for (let k = 0; k < o.days; k++) {
    let day = buildDay({ pf: c.pf, kcal: c.kcal, slots: o.slots, k, seed: o.seed, used: new Map(used), exclude: o.exclude, style: c.style });
    if (day.meals.some((m) => !m.dish)) {
      return { ...header(c), ok: false, constraint_satisfaction: "failed",
        error: "No dish in the dataset meets every constraint for some meal (allergies, food rules, dishes left out). Say so plainly; do not invent a dish or its numbers.",
        meals: day.meals.filter((m) => !m.dish).map((m) => m.slot) };
    }
    day = balance(day, { range: c.range, pf: c.pf, exclude: o.exclude, style: c.style, used, k });
    for (const m of day.meals) used.set(m.dish.id, [...(used.get(m.dish.id) || []), k]);
    days.push(showDay(day, k, c, k === 0));
  }
  const week = days.length > 1 && !c.quiet ? {
    average_kcal: Math.round(days.reduce((a, d) => a + d.totals.kcal, 0) / days.length),
    days_within_range: c.range ? days.filter((d) => d.checks.find((x) => x.check === "energy")?.ok).length : undefined,
    different_dishes: new Set(days.flatMap((d) => d.meals.map((m) => m.dish.id))).size,
  } : undefined;
  return {
    ...header(c, { meals_per_day: o.meals === "ramadan" ? "ramadan (sahur and iftar)" : o.meals, variant: o.seed }),
    days, week,
    drinks: DRINKS[regionOf(c.pf.region)?.code] || DRINKS.default,
    how_to_use: "Show each meal with its serving, energy and protein (from the result), what to add and how to order it. Offer a swap (diet.swap) for any meal; never alter a number yourself.",
  };
}

/** The tool: replace one meal of a day (with a named dish, or the best other one) and re-check the whole day. */
export function swap(args = {}) {
  const c = context(args);
  const o = options(args, c.pf);
  const given = Array.isArray(args.day) ? args.day : [];
  const fixed = {};
  for (const m of given) if (m && m.slot && dish(m.dish_id)) fixed[m.slot] = m.dish_id;
  const slot = String(args.slot || "");
  if (!o.slots.some(([s]) => s === slot)) return { ok: false, error: `slot must be one of ${o.slots.map(([s]) => s).join(", ")} for ${o.meals} meals a day` };
  const old = fixed[slot];
  delete fixed[slot];
  if (args.want) {
    const d = dish(args.want) || DISHES.find((x) => x.name.toLowerCase() === String(args.want).toLowerCase());
    if (!d) return { ok: false, error: `no dish ${JSON.stringify(args.want)} in the dataset: use diet.dishes to find one by name` };
    const why = forbidden(d, c.pf);
    if (why.length) return { ...header(c), ok: false, refused: d.name, why, error: "This dish breaks a hard constraint and cannot be put in the plan." };
    fixed[slot] = d.id;
  }
  const exclude = new Set([...o.exclude, ...(old && !args.want ? [old] : [])]);
  const used = new Map(Object.values(fixed).map((id) => [id, [0]]));
  let day = buildDay({ pf: c.pf, kcal: c.kcal, slots: o.slots, k: 0, seed: o.seed + 1, used, exclude, style: c.style, fixed });
  if (!day.meals.some((m) => !m.dish)) day = balance(day, { range: c.range, pf: c.pf, exclude, style: c.style, used, k: 0, fixed });
  if (day.meals.some((m) => !m.dish)) {
    return { ...header(c), ok: false, constraint_satisfaction: "failed", error: "No other dish meets every constraint for this meal. Say so; do not invent one." };
  }
  const shownDay = showDay(day, Number(args.day_number || 1) - 1, c);
  return { ...header(c), swapped: { slot, from: old || null, to: day.meals.find((m) => m.slot === slot).dish.id }, day: shownDay,
    note: "The whole day was re-checked: energy, protein, sodium and allergens." };
}

/** The tool: dishes by name or kind, with their numbers and how to order them; those this visitor may not have are marked. */
export function dishes(args = {}) {
  const c = context({ profile: args.profile || {} });
  const words = String(args.query || "").toLowerCase().split(/[\s,，、]+/).filter(Boolean);
  const want = (d) => !words.length || words.every((w) => [d.name, d.zh, d.id, d.cuisine, ...(d.aka || []), ...d.tags].join(" ").toLowerCase().includes(w));
  const r = regionOf(args.region || args.profile?.region);
  let rows = DISHES.filter((d) => want(d) && (!r || d.regions.includes("*") || d.regions.includes(r.code))
    && (!args.slot || d.slots.includes(args.slot)) && (!args.cuisine || d.cuisine === args.cuisine)
    && (!Number(args.max_kcal) || (d.kcal != null && d.kcal <= Number(args.max_kcal))));
  if (args.sort === "kcal") rows = rows.sort((a, b) => (a.kcal ?? 1e9) - (b.kcal ?? 1e9));
  else if (args.sort === "sodium") rows = rows.sort((a, b) => (a.sodium_mg ?? 1e9) - (b.sodium_mg ?? 1e9));
  else if (args.sort === "protein") rows = rows.sort((a, b) => (b.protein_g ?? -1) - (a.protein_g ?? -1));
  const limit = Math.max(1, Math.min(30, Number(args.limit) || 12));
  return {
    ok: true, algorithm: ALGORITHM, count: rows.length,
    dishes: rows.slice(0, limit).map((d) => {
      const no = forbidden(d, c.pf);
      return { ...shown(d, c.quiet), cuisine: d.cuisine, kind: d.kind, tags: d.tags, regions: d.regions.includes("*") ? "anywhere" : d.regions,
        other_figure: d.other_figure, per_piece_kcal: d.per_piece_kcal,
        not_for_you: no.length ? no : undefined, source_url: d.source_url || undefined, usda: d.usda };
    }),
    more: rows.length > limit ? rows.length - limit : undefined,
    dataset: { id: DATASET.id, version: DATASET.version, status: DATASET.status, note: DATASET.note },
    provenance: provenance(["hpb_dish_composition", "usda_fdc"]),
    note: "Values are for the serving shown; stalls' portions differ. A dish not listed has no data here: say so rather than estimate it.",
  };
}
