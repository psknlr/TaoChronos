// The weekly review: weigh-ins read as a trend — a straight line through the last four weeks, and this week's average
// against last week's — never one weigh-in against another.  What the trend means for the plan follows fixed rules:
// too early to tell, on track, faster than planned, a plateau, or going up.  With an eating disorder flagged no numbers
// are reviewed (assess.js).

import { assess } from "./assess.js";
import { ALGORITHM, provenance } from "./sources.js";

const DAY = 86400e3;

/** The weigh-ins as {t, kg, waist}, by date, one a day (the last of a day), the implausible left out. */
function readings(entries = []) {
  const byDay = new Map();
  for (const e of Array.isArray(entries) ? entries : []) {
    const t = Date.parse(`${String(e?.date || "").slice(0, 10)}T00:00:00Z`);
    const kg = Number(e?.weight_kg);
    if (!Number.isFinite(t) || !Number.isFinite(kg) || kg < 25 || kg > 300) continue;
    const waist = Number(e?.waist_cm);
    byDay.set(t, { t, kg, waist: Number.isFinite(waist) && waist >= 40 && waist <= 200 ? waist : null });
  }
  return [...byDay.values()].sort((a, b) => a.t - b.t);
}

/** Least-squares slope, in kg a week. */
function slope(rows) {
  const n = rows.length;
  const mx = rows.reduce((a, r) => a + r.t, 0) / n;
  const my = rows.reduce((a, r) => a + r.kg, 0) / n;
  let num = 0, den = 0;
  for (const r of rows) { num += (r.t - mx) * (r.kg - my); den += (r.t - mx) ** 2; }
  return den ? (num / den) * 7 * DAY : 0;
}

const mean = (xs) => xs.reduce((a, x) => a + x, 0) / xs.length;
const r2 = (x) => Math.round(x * 100) / 100;

/** The tool: what the weigh-ins say, and what to do about it. */
export function progress(args = {}) {
  const a = assess(args.profile || {});
  if (a.flags.some((f) => f.code === "eating_disorder")) {
    return { ok: true, algorithm: ALGORITHM, reviewed: false,
      say: "Weight trends are not reviewed here. How you feel, your energy and regular meals matter more; your care team can review the rest with you." };
  }
  const rows = readings(args.entries);
  if (!rows.length) return { ok: false, error: "no weigh-ins: give entries as [{date: \"YYYY-MM-DD\", weight_kg, waist_cm?}]" };
  const last = rows[rows.length - 1];
  const recent = rows.filter((r) => r.t > last.t - 28 * DAY);
  const span = Math.round((last.t - recent[0].t) / DAY);
  const week = rows.filter((r) => r.t > last.t - 7 * DAY);
  const before = rows.filter((r) => r.t <= last.t - 7 * DAY && r.t > last.t - 14 * DAY);
  const out = {
    ok: true, algorithm: ALGORITHM, reviewed: true, weigh_ins: rows.length, span_days: span,
    this_week_average_kg: r2(mean(week.map((r) => r.kg))),
    last_week_average_kg: before.length ? r2(mean(before.map((r) => r.kg))) : undefined,
  };
  const plan = a.target?.kind || args.plan || "maintenance";
  if (recent.length < 3 || span < 14) {
    return { ...out, verdict: "too_early",
      say: "Too early to judge: weigh 2–3 times a week, in the morning before breakfast, and look at the trend after 2–4 weeks — day-to-day changes are mostly water.",
      provenance: provenance(["activity_factors"]) };
  }
  const rate = slope(recent); // kg a week, negative when losing
  out.trend_kg_per_week = r2(rate);
  const first = rows[0];
  out.change_since_start_kg = r2(last.kg - first.kg);
  out.change_since_start_percent = r2(((last.kg - first.kg) / first.kg) * 100);
  const waists = rows.filter((r) => r.waist !== null);
  if (waists.length >= 2) out.waist_change_cm = r2(waists[waists.length - 1].waist - waists[0].waist);
  if (plan === "deficit") {
    if (rate < -1.0) Object.assign(out, { verdict: "faster_than_planned",
      say: "Losing more than 1 kg a week: faster than planned. Make sure you eat the planned amount (not less), with protein at each meal; if it isn't intended or you feel unwell, see a doctor." });
    else if (rate <= -0.25) Object.assign(out, { verdict: "on_track", say: "On track: about the planned 0.25–1 kg a week. Keep going; review again next week." });
    else if (rate < 0.1 && span >= 21) Object.assign(out, { verdict: "plateau",
      say: "Little change over 3–4 weeks. First check the small things — sweet drinks, sauces and gravy, second helpings, snacks; add a daily walk or strength exercise. If all is as planned, the target may come down by 100–200 kcal, never below the plan's floor (ask diet.assess again with the current weight)." });
    else if (rate >= 0.1) Object.assign(out, { verdict: "rising", say: "Weight is going up on the trend: compare what is eaten with the plan for a few days (drinks and snacks first) before changing the target." });
    else Object.assign(out, { verdict: "slow", say: "Slower than planned but going down: give it another week or two before changing anything." });
  } else {
    if (Math.abs(rate) <= 0.25) Object.assign(out, { verdict: "stable", say: "Weight is steady, as planned." });
    else Object.assign(out, { verdict: rate < 0 ? "falling" : "rising",
      say: rate < 0 ? "Weight is falling on a plan meant to keep it steady: if this isn't intended, eat a little more, and see a doctor if it continues." : "Weight is rising on a plan meant to keep it steady: look at drinks, snacks and portions first." });
  }
  if (out.change_since_start_percent <= -5) out.milestone = "5% of starting weight lost: a change that already lowers the risk of diabetes and high blood pressure.";
  out.provenance = provenance(["activity_factors", "sg_moh_cpg_obesity"]);
  return out;
}
