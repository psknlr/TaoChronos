// Where and when a plan is for: Singapore, on its own clock (Asia/Singapore, UTC+8 — not the server's or the browser's),
// its season by the monsoons (Meteorological Service Singapore's climatology: typical onsets, no live weather), the 24
// solar terms (二十四节气) computed from the Sun's apparent longitude as a cultural calendar only — Singapore lies 1°
// north of the equator, and the terms describe a temperate climate it does not have — and the festive seasons ahead,
// with what is eaten at them.  The season changes what is suggested (warm soups, hydration, food safety, festive
// portions), never the energy target.

import { ALGORITHM, provenance } from "./sources.js";

export const TIMEZONE = "Asia/Singapore";
const OFFSET_H = 8; // Singapore Standard Time, UTC+8 all year (no daylight saving): the same clock as China Standard Time

const pad = (n) => String(n).padStart(2, "0");
const iso = (d) => `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
/** A Date whose UTC fields read as Singapore's clock at `t`. */
const local = (t) => new Date(t.getTime() + OFFSET_H * 3600e3);
const DAY = 86400e3;

/** Singapore's date for `date` ("YYYY-MM-DD", taken as a Singapore date) or for now: {iso, y, m, d, at} (`at`: midnight, UTC ms of the local fields). */
export function sgDate(date = null, now = new Date()) {
  let y, m, d;
  const match = typeof date === "string" && /^(\d{4})-(\d{2})-(\d{2})$/.exec(date.trim());
  if (typeof date === "string" && date.trim() && !match) return null; // a date that is no date is not taken for today
  if (match) [y, m, d] = [Number(match[1]), Number(match[2]), Number(match[3])];
  else { const l = local(now); [y, m, d] = [l.getUTCFullYear(), l.getUTCMonth() + 1, l.getUTCDate()]; }
  const at = Date.UTC(y, m - 1, d);
  if (!Number.isFinite(at) || new Date(at).getUTCDate() !== d || new Date(at).getUTCMonth() !== m - 1) return null;
  return { iso: iso(new Date(at)), y, m, d, at, weekday: ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"][new Date(at).getUTCDay()] };
}

// ------------------------------------------------------------------ the monsoons
// [from (month, day), phase, what is typical, what it means for eating]: in the order of the year
const SEASONS = [
  [[1, 1], "northeast_monsoon_wet", "Northeast Monsoon (wet phase): monsoon surges can bring prolonged heavy rain, wind and cooler days; December and early January are among the wettest weeks.",
    ["Warm soups suit rainy days: choose clear soups (sliced fish, tofu, vegetables) over coconut or creamy ones.",
      "Less walking on wet days: keep portions to the plan, and move indoors (stairs, home exercise)."]],
  [[1, 16], "northeast_monsoon_dry", "Northeast Monsoon (dry phase): usually drier, sunnier and windy, with cooler nights.",
    ["Sunny afternoons: drink water through the day.", "The Lunar New Year season often falls now: plan for festive snacks (below)."]],
  [[3, 11], "inter_monsoon_1", "Inter-monsoon (late March to May): light winds, hot and humid afternoons with thunderstorms; April and May are among the hottest months.",
    ["Heat: drink water regularly without waiting for thirst; plain water or Nutri-Grade A/B drinks rather than sweet iced drinks.",
      "Food safety in the heat: eat cooked food soon, and don't leave it out for more than 2 hours; refrigerate leftovers quickly.",
      "Lighter meals suit the heat: more vegetables and fruit, steamed or soup dishes over fried."]],
  [[6, 1], "southwest_monsoon", "Southwest Monsoon (June to September): warm, with 'Sumatra squalls' (early-morning storms); transboundary haze is possible, especially from August, depending on regional fires.",
    ["Warm and humid: keep water at hand; fruit such as watermelon and papaya adds fluid and fibre.",
      "On haze days check NEA's air-quality readings; move exercise indoors when advised."]],
  [[10, 1], "inter_monsoon_2", "Inter-monsoon (October to November): afternoon and evening thunderstorms, light winds; November turns wetter as the Northeast Monsoon approaches.",
    ["Hot afternoons, rainy evenings: hydrate through the day; keep cooked food out of the heat.",
      "Festive seasons (Deepavali, then year-end parties) often fall now: see the festivals below."]],
  [[12, 1], "northeast_monsoon_wet", null, null],
];

export function season(day) {
  const key = day.m * 100 + day.d;
  let s = SEASONS[0];
  for (const row of SEASONS) if (row[0][0] * 100 + row[0][1] <= key) s = row[2] ? row : SEASONS[0];
  return { phase: s[1], typical: s[2], eating: s[3], source: "mss_climate",
    weather_status: "calendar_only: no live weather is read — today's forecast, rain and haze are on MSS/NEA (weather.gov.sg)",
    note: "Onsets vary by a few weeks from year to year. The season shapes food choices and hydration, never the energy target." };
}

// ------------------------------------------------------------------ the 24 solar terms
// by the Sun's apparent longitude (Meeus, Astronomical Algorithms, 2nd ed., ch. 25: about 0.01°, some 15 minutes)
const RAD = Math.PI / 180;
const DELTA_T = 69; // TT − UT in seconds, about its value in the 2020s
// the method is good to about a quarter of an hour (against the NAOJ almanac for 2026: within 13 minutes); a term this
// close to midnight may fall on the next or the previous day
const MIDNIGHT_MARGIN = 30;

export function sunLongitude(jde) {
  const T = (jde - 2451545.0) / 36525;
  const L0 = 280.46646 + 36000.76983 * T + 0.0003032 * T * T;
  const M = (357.52911 + 35999.05029 * T - 0.0001537 * T * T) * RAD;
  const C = (1.914602 - 0.004817 * T - 0.000014 * T * T) * Math.sin(M) + (0.019993 - 0.000101 * T) * Math.sin(2 * M) + 0.000289 * Math.sin(3 * M);
  const omega = (125.04 - 1934.136 * T) * RAD;
  const lambda = L0 + C - 0.00569 - 0.00478 * Math.sin(omega);
  return ((lambda % 360) + 360) % 360;
}

// in the order of a calendar year, from 小寒 (285°) to 冬至 (270°)
export const TERMS = [
  [285, "小寒", "Minor Cold"], [300, "大寒", "Major Cold"], [315, "立春", "Start of Spring"], [330, "雨水", "Rain Water"],
  [345, "惊蛰", "Awakening of Insects"], [0, "春分", "Spring Equinox"], [15, "清明", "Clear and Bright"], [30, "谷雨", "Grain Rain"],
  [45, "立夏", "Start of Summer"], [60, "小满", "Grain Buds"], [75, "芒种", "Grain in Ear"], [90, "夏至", "Summer Solstice"],
  [105, "小暑", "Minor Heat"], [120, "大暑", "Major Heat"], [135, "立秋", "Start of Autumn"], [150, "处暑", "End of Heat"],
  [165, "白露", "White Dew"], [180, "秋分", "Autumn Equinox"], [195, "寒露", "Cold Dew"], [210, "霜降", "Frost's Descent"],
  [225, "立冬", "Start of Winter"], [240, "小雪", "Minor Snow"], [255, "大雪", "Major Snow"], [270, "冬至", "Winter Solstice"],
];
const CULTURE = {
  冬至: "Dongzhi (冬至): many Chinese families in Singapore eat tang yuan (glutinous rice balls) together.",
  清明: "Qingming (清明): a time of remembering ancestors.",
  立春: "Lichun (立春) falls near the Lunar New Year.",
};

/** The moment (ms, UTC) the Sun reaches apparent longitude `lon` in calendar year `year`. */
export function termMoment(year, lon) {
  const march = Date.UTC(year, 2, 20) / DAY + 2440587.5;
  let jde = march + ((lon >= 285 ? lon - 360 : lon) / 360) * 365.2422 + DELTA_T / 86400;
  for (let i = 0; i < 60; i++) {
    const d = ((lon - sunLongitude(jde) + 540) % 360) - 180;
    jde += (d * 365.2422) / 360;
    if (Math.abs(d) < 1e-7) break;
  }
  return Math.round((jde - DELTA_T / 86400 - 2440587.5) * DAY);
}

/** The year's terms, each with its moment and its Singapore date. */
export function termsOf(year) {
  return TERMS.map(([lon, zh, en]) => {
    const t = termMoment(year, lon);
    const l = local(new Date(t));
    const minutes = l.getUTCHours() * 60 + l.getUTCMinutes();
    return { zh, en, longitude: lon, moment: new Date(t).toISOString(), sg_time: `${iso(l)} ${pad(l.getUTCHours())}:${pad(l.getUTCMinutes())}`, date: iso(l),
      at: Date.UTC(l.getUTCFullYear(), l.getUTCMonth(), l.getUTCDate()),
      // within the method's error of midnight, the date itself may be a day off
      ...(minutes < MIDNIGHT_MARGIN || minutes > 1440 - MIDNIGHT_MARGIN ? { near_midnight: true } : {}) };
  });
}

/** The term a Singapore date falls in, and the next one. */
export function solarTerm(day) {
  const all = [...termsOf(day.y - 1).slice(-1), ...termsOf(day.y), ...termsOf(day.y + 1).slice(0, 1)];
  let k = 0;
  while (k + 1 < all.length && all[k + 1].at <= day.at) k++;
  const brief = (t) => ({ zh: t.zh, en: t.en, date: t.date, sg_time: t.sg_time, culture: CULTURE[t.zh],
    ...(t.near_midnight ? { date_uncertain: "falls within half an hour of midnight: the date may be a day off; an almanac gives the exact day" } : {}) });
  const next = all[k + 1];
  return {
    current: { ...brief(all[k]), began: all[k].date },
    next: { ...brief(next), in_days: Math.round((next.at - day.at) / DAY) },
    source: "solar_terms",
    note: "A cultural calendar in Singapore: its weather follows the monsoons, not these northern-temperate seasons, so seasonal advice written for China's winters or summers does not carry over unchanged.",
  };
}

// ------------------------------------------------------------------ festive seasons
// MOM's gazetted dates (2026 announced in 2025, 2027 on 18 June 2026, as reported), the Mid-Autumn Festival by the
// lunar calendar, Dongzhi by the Sun.  Years without verified dates have none: the result says so.
const FESTIVE = {
  cny: { name: "Chinese New Year (农历新年)", foods: "bak kwa, pineapple tarts, love letters, kueh bangkit, yusheng, steamboat, mandarin oranges",
    tips: ["Decide on one or two pieces of a festive snack, and enjoy them slowly; pass on the rest.", "Mandarin oranges are a lighter snack than tarts or bak kwa.",
      "Steamboat: a clear broth, lean meat, fish, tofu and plenty of vegetables; go easy on dipping sauces and processed balls."] },
  ramadan: { name: "Ramadan (bulan puasa)", foods: "sahur and iftar meals; dates; kuih; bubur lambuk; bandung and sirap",
    tips: ["Sahur: wholegrains (oats, wholemeal bread, brown rice), protein (eggs, tempeh, fish) and water, to last the day.",
      "Break the fast with water and one to three dates, then a balanced plate — not a run of fried kuih and sweet drinks.",
      "Drink water steadily between iftar and sahur.", "If you take medicines for diabetes, discuss fasting with your doctor beforehand."],
    note: "MUIS announces the start of Ramadan and Hari Raya Puasa by moon sighting." },
  hrp: { name: "Hari Raya Puasa (Aidilfitri)", foods: "ketupat, lontong, rendang, sayur lodeh, kuih and cookies",
    tips: ["Rich coconut gravies: take a small ladle and fill up on vegetables.", "Cookies and kuih: a few, savoured; water or unsweetened tea rather than sweet drinks."] },
  hrh: { name: "Hari Raya Haji (Aidiladha)", foods: "korban meat dishes, rendang, briyani",
    tips: ["Choose lean cuts and trim fat; balance a meat dish with vegetables and a modest portion of rice."] },
  vesak: { name: "Vesak Day", foods: "vegetarian meals",
    tips: ["Tofu, tempeh, beans and lentils keep a vegetarian meal high in protein; fried mock meats are often high in fat and sodium."] },
  midautumn: { name: "Mid-Autumn Festival (中秋节)", foods: "mooncakes (baked lotus paste, often with salted yolks; snowskin), pomelo, tea",
    tips: ["Share a mooncake: a quarter is a portion; pomelo makes a refreshing companion.", "Unsweetened Chinese tea goes with mooncakes better than sweet drinks."] },
  deepavali: { name: "Deepavali", foods: "murukku, ladoo and other mithai, kuih; briyani, curries",
    tips: ["Sweets and murukku: a small plate, shared; they are rich in sugar and fat.", "At the meal: dhal and vegetables alongside briyani, yoghurt or raita, and a modest rice portion."] },
  dongzhi: { name: "Dongzhi (冬至, winter solstice)", foods: "tang yuan (glutinous rice balls in sweet soup)",
    tips: ["Tang yuan: a few balls in a lightly sweetened ginger soup; filled ones (sesame, peanut) are richer."] },
  christmas: { name: "Christmas", foods: "roasts, log cake, cookies, party food",
    tips: ["At parties: start with vegetables and lean protein, then choose one treat; alternate drinks with water."] },
};
const DATES = {
  2026: [["cny", "2026-02-17"], ["hrp", "2026-03-21"], ["hrh", "2026-05-27"], ["vesak", "2026-05-31"], ["midautumn", "2026-09-25"],
    ["deepavali", "2026-11-08"], ["christmas", "2026-12-25"]],
  2027: [["cny", "2027-02-06"], ["hrp", "2027-03-10"], ["vesak", "2027-05-20"], ["midautumn", "2027-09-15"], ["deepavali", "2027-10-28"],
    ["christmas", "2027-12-25"]],
};
export const FESTIVE_YEARS = Object.keys(DATES).map(Number);

/** The festive seasons from `day` to `within` days on (and Ramadan while it runs, before Hari Raya Puasa). */
export function festivals(day, within = 60) {
  const out = [];
  const add = (id, date, extra = {}) => {
    const at = Date.parse(`${date}T00:00:00Z`);
    const inDays = Math.round((at - day.at) / DAY);
    if (inDays >= 0 && inDays <= within) out.push({ id, ...FESTIVE[id], date, in_days: inDays, ...extra });
  };
  for (const y of [day.y, day.y + 1]) {
    for (const [id, date] of DATES[y] || []) {
      if (id === "hrp") {
        // Ramadan: about the 29–30 days before Hari Raya Puasa (MUIS announces it)
        const days = Math.round((Date.parse(`${date}T00:00:00Z`) - day.at) / DAY);
        if (days > 0 && days <= 30) out.push({ id: "ramadan", ...FESTIVE.ramadan, date: `ends before ${date}`, in_days: 0, ongoing: true });
        else if (days > 30 && days <= within + 30) out.push({ id: "ramadan", ...FESTIVE.ramadan, date: `about ${days - 30} days from now (the month before Hari Raya Puasa on ${date})`, in_days: days - 30 });
      }
      add(id, date, { source: id === "midautumn" ? "lunar_calendar" : "mom_holidays" });
    }
    const dongzhi = termsOf(y).find((t) => t.zh === "冬至");
    add("dongzhi", dongzhi.date, { source: "solar_terms" });
  }
  out.sort((a, b) => a.in_days - b.in_days);
  return { upcoming: out, verified_years: FESTIVE_YEARS,
    note: DATES[day.y] ? undefined : `No verified festival dates for ${day.y}: check MOM's public-holiday list.` };
}

/** The whole context for a Singapore date (default: today in Singapore). */
export function context({ date = null, within = 60 } = {}, now = new Date()) {
  const day = sgDate(date, now);
  if (!day) return { ok: false, error: `date ${JSON.stringify(date)} is not a calendar date (YYYY-MM-DD)` };
  const fest = festivals(day, Math.max(0, Math.min(120, Number(within) || 60)));
  const ids = ["mss_climate", "solar_terms", ...new Set(fest.upcoming.map((f) => f.source).filter(Boolean))];
  return {
    ok: true, algorithm: ALGORITHM, place: "Singapore", timezone: `${TIMEZONE} (UTC+8)`, date: day.iso, weekday: day.weekday,
    season: season(day), solar_term: solarTerm(day), festivals: fest.upcoming, festivals_note: fest.note,
    provenance: provenance(ids),
  };
}
