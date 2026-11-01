// Where and when a plan is for: the visitor's date on their own clock (their region's time zone, or this device's), the
// season where they live — by hemisphere and the country's broad climate (temperate, cold, subtropical, arid, tropical),
// by the monsoons in Singapore (MSS climatology) and South Asia, none at all where no region is stated —, the 24 solar
// terms (二十四节气) as the Chinese cultural calendar (computed from the Sun's apparent longitude; outside the northern
// temperate zone they describe no climate), and the festive seasons ahead, worldwide, with what is eaten at them.  No
// live weather is read.  The season changes what is suggested (warm soups, hydration, food safety, festive portions),
// never the energy target.

import { browserZone, region as regionOf } from "./regions.js";
import { ALGORITHM, provenance } from "./sources.js";

const CST_H = 8; // China Standard Time, UTC+8: the clock the solar terms are dated by
const pad = (n) => String(n).padStart(2, "0");
const iso = (d) => `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
const DAY = 86400e3;
const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

/** The calendar date at `now` in time zone `tz` (UTC when it is unknown): [y, m, d]. */
function dateIn(tz, now) {
  try {
    const parts = Object.fromEntries(new Intl.DateTimeFormat("en-CA", { timeZone: tz || "UTC", year: "numeric", month: "2-digit", day: "2-digit" })
      .formatToParts(now).map((p) => [p.type, p.value]));
    return [Number(parts.year), Number(parts.month), Number(parts.day)];
  } catch {
    return [now.getUTCFullYear(), now.getUTCMonth() + 1, now.getUTCDate()];
  }
}

/** The visitor's date: `date` ("YYYY-MM-DD") as given, or today in time zone `tz`: {iso, y, m, d, at, weekday}. */
export function localDay(date = null, tz = null, now = new Date()) {
  let y, m, d;
  const match = typeof date === "string" && /^(\d{4})-(\d{2})-(\d{2})$/.exec(date.trim());
  if (typeof date === "string" && date.trim() && !match) return null; // a date that is no date is not taken for today
  if (match) [y, m, d] = [Number(match[1]), Number(match[2]), Number(match[3])];
  else [y, m, d] = dateIn(tz, now);
  const at = Date.UTC(y, m - 1, d);
  if (!Number.isFinite(at) || new Date(at).getUTCDate() !== d || new Date(at).getUTCMonth() !== m - 1) return null;
  return { iso: iso(new Date(at)), y, m, d, at, weekday: WEEKDAYS[new Date(at).getUTCDay()] };
}

// ------------------------------------------------------------------ seasons
const SAFE = "Food safety: eat cooked food soon, and don't leave it out for more than 2 hours (1 hour above 32 °C); refrigerate leftovers quickly.";
const HEAT = "Heat: drink water regularly without waiting for thirst; water or unsweetened drinks rather than sweet iced ones.";
// Singapore's monsoons (MSS): [from (month, day), phase, what is typical, what it means for eating]
const MONSOON_SG = [
  [[1, 1], "northeast_monsoon_wet", "Northeast Monsoon (wet phase): monsoon surges can bring prolonged heavy rain, wind and cooler days; December and early January are among the wettest weeks.",
    ["Warm soups suit rainy days: choose clear soups (fish, tofu, vegetables) over coconut or creamy ones.",
      "Less walking on wet days: keep portions to the plan, and move indoors (stairs, home exercise)."]],
  [[1, 16], "northeast_monsoon_dry", "Northeast Monsoon (dry phase): usually drier, sunnier and windy, with cooler nights.",
    ["Sunny afternoons: drink water through the day.", "The Lunar New Year season often falls now: plan for festive snacks."]],
  [[3, 11], "inter_monsoon_1", "Inter-monsoon (late March to May): light winds, hot and humid afternoons with thunderstorms; April and May are among the hottest months.",
    [`${HEAT} In Singapore, Nutri-Grade A or B for packaged drinks.`, SAFE, "Lighter meals suit the heat: more vegetables and fruit, steamed or soup dishes over fried."]],
  [[6, 1], "southwest_monsoon", "Southwest Monsoon (June to September): warm, with early-morning squalls; transboundary haze is possible, especially from August.",
    ["Warm and humid: keep water at hand; fruit such as watermelon and papaya adds fluid and fibre.", "On haze days, check the air-quality readings and move exercise indoors when advised."]],
  [[10, 1], "inter_monsoon_2", "Inter-monsoon (October to November): afternoon and evening thunderstorms; November turns wetter as the Northeast Monsoon approaches.",
    ["Hot afternoons, rainy evenings: hydrate through the day; keep cooked food out of the heat.", "Festive seasons (Deepavali, then year-end parties) often fall now."]],
  [[12, 1], "northeast_monsoon_wet", null, null],
];
// South Asia (the India Meteorological Department's four seasons)
const MONSOON_SA = [
  [[1, 1], "winter", "Winter (January–February): cool and dry in the north, mild in the south.",
    ["Warm cooked meals: dals, vegetable curries and whole grains (millets, wholewheat roti); go easy on ghee and fried snacks."]],
  [[3, 1], "pre_monsoon", "Hot season (March–May): rising heat, very hot in the plains before the monsoon.",
    [HEAT, SAFE, "Lighter meals: curd or buttermilk (unsweetened), salads, seasonal fruit; fewer fried foods."]],
  [[6, 1], "southwest_monsoon", "Southwest monsoon (June–September): the rainy season across most of the country.",
    ["Food hygiene matters more in the rains: freshly cooked food, safe drinking water, washed produce.", "Less outdoor activity: keep portions to the plan and move indoors."]],
  [[10, 1], "post_monsoon", "Post-monsoon (October–December): the rains withdraw; cooler in the north by December.",
    ["The festive season often falls now (Diwali and others): plan for sweets and fried snacks."]],
];
const TEMPERATE = {
  winter: ["Warm cooked meals and soups suit cold days: broth-based soups rather than creamy ones, and watch the salt.",
    "Winter vegetables (cabbages, root vegetables, leeks) and citrus are in season across much of the temperate world.",
    "Shorter, colder days: keep moving indoors; holiday eating often falls now."],
  spring: ["Leafy greens and early vegetables return: build half the plate from them.", "Lighter cooking — steaming, quick stir-frying with little oil."],
  summer: [HEAT, SAFE, "Fresh fruit, salads and grilled fish or vegetables; at barbecues, lean meats and little processed meat."],
  autumn: ["Harvest season: pumpkins, apples, pears, mushrooms, beans and whole grains.", "Festive and year-end eating often begins: plan for it."],
};
const SEASON_OF_MONTH = ["winter", "winter", "spring", "spring", "spring", "summer", "summer", "summer", "autumn", "autumn", "autumn", "winter"];
const CLIMATE_WORDS = {
  temperate: "temperate", cold: "cold-winter", subtropical: "subtropical (mild winters, hot humid summers)", arid: "arid (hot, dry)",
  tropical: "tropical", monsoon_sg: "equatorial (Singapore's monsoons)", monsoon_south_asia: "monsoon",
};

function pick(rows, day) {
  const key = day.m * 100 + day.d;
  let s = rows[0];
  for (const row of rows) if (row[0][0] * 100 + row[0][1] <= key) s = row[2] ? row : rows[0];
  return s;
}

/** The season for a date where the visitor lives (`place`: a region, or {hemisphere, climate} given by the visitor). */
export function season(day, place) {
  const base = { weather_status: "calendar_only: no live weather is read — the local weather service has today's forecast",
    note: "The season shapes food choices, hydration and food safety, never the energy target." };
  if (!place?.climate) {
    return { ...base, phase: null, typical: "No region stated: seasonal advice needs to know where the visitor lives (country, or hemisphere and climate).", eating: [] };
  }
  const varied = place.varied ? ` ${place.name || "This country"} spans several climates: tell me if your area's differs.` : "";
  if (place.climate === "monsoon_sg") {
    const s = pick(MONSOON_SG, day);
    return { ...base, phase: s[1], climate: CLIMATE_WORDS.monsoon_sg, typical: s[2], eating: s[3], source: "mss_climate",
      note: `${base.note} Onsets vary by a few weeks from year to year.` };
  }
  if (place.climate === "monsoon_south_asia") {
    const s = pick(MONSOON_SA, day);
    return { ...base, phase: s[1], climate: CLIMATE_WORDS.monsoon_south_asia, typical: s[2] + varied, eating: s[3], source: "climate_rule" };
  }
  if (place.climate === "tropical") {
    return { ...base, phase: "tropical", climate: CLIMATE_WORDS.tropical, source: "climate_rule",
      typical: `Tropical climate: warm all year; the seasons are wet and dry rather than hot and cold.${varied}`,
      eating: ["Drink water through the day; fruit and vegetables are in season all year.", SAFE, "In the rainy season, freshly cooked food and safe drinking water matter more."] };
  }
  const north = place.hemisphere !== "S";
  const name = SEASON_OF_MONTH[north ? day.m - 1 : (day.m + 5) % 12];
  const eating = [...TEMPERATE[name]];
  if (place.climate === "arid" && name === "summer") eating.unshift("Extreme heat: drink water often, eat lighter meals, and avoid exercise in the hottest hours.");
  if (place.climate === "cold" && name === "winter") eating.push("Long, dark winters: plan regular indoor activity.");
  if (place.climate === "subtropical" && name === "winter") eating.splice(0, 1, "Mild winter: warm cooked meals still suit cool evenings.");
  return { ...base, phase: name, climate: CLIMATE_WORDS[place.climate] || place.climate, hemisphere: north ? "northern" : "southern",
    typical: `${name[0].toUpperCase()}${name.slice(1)} in the ${north ? "northern" : "southern"} hemisphere (meteorological seasons: ${north ? "December–February winter" : "June–August winter"}).${varied}`,
    eating, source: "climate_rule" };
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
  冬至: "Dongzhi (冬至): a family festival — tang yuan (glutinous rice balls) in southern China and Southeast Asia, dumplings in northern China.",
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

/** The year's terms, each with its moment and its date in China Standard Time (UTC+8), as the calendar reckons them. */
export function termsOf(year) {
  return TERMS.map(([lon, zh, en]) => {
    const t = termMoment(year, lon);
    const l = new Date(t + CST_H * 3600e3);
    const minutes = l.getUTCHours() * 60 + l.getUTCMinutes();
    return { zh, en, longitude: lon, moment: new Date(t).toISOString(), cst_time: `${iso(l)} ${pad(l.getUTCHours())}:${pad(l.getUTCMinutes())}`, date: iso(l),
      at: Date.UTC(l.getUTCFullYear(), l.getUTCMonth(), l.getUTCDate()),
      // within the method's error of midnight, the date itself may be a day off
      ...(minutes < MIDNIGHT_MARGIN || minutes > 1440 - MIDNIGHT_MARGIN ? { near_midnight: true } : {}) };
  });
}

/** The term a date falls in, and the next one, with what the terms mean where the visitor is. */
export function solarTerm(day, place = null) {
  const all = [...termsOf(day.y - 1).slice(-1), ...termsOf(day.y), ...termsOf(day.y + 1).slice(0, 1)];
  let k = 0;
  while (k + 1 < all.length && all[k + 1].at <= day.at) k++;
  const brief = (t) => ({ zh: t.zh, en: t.en, date: t.date, cst_time: t.cst_time, culture: CULTURE[t.zh],
    ...(t.near_midnight ? { date_uncertain: "falls within half an hour of midnight: the date may be a day off; an almanac gives the exact day" } : {}) });
  const next = all[k + 1];
  return {
    current: { ...brief(all[k]), began: all[k].date },
    next: { ...brief(next), in_days: Math.round((next.at - day.at) / DAY) },
    source: "solar_terms",
    note: termsNote(place),
  };
}

/** What the solar terms mean where the visitor is. */
function termsNote(place) {
  const east = ["CN", "TW", "JP", "KR"].includes(place?.code);
  if (east) {
    return "A Chinese calendar of the seasons, which here broadly follow the terms; traditional seasonal eating (for instance the "
      + "chapter 四气调神大论 of the 素问) can be quoted through the corpus tools, as a historical text, not modern evidence.";
  }
  if (place?.hemisphere === "S" && place.climate !== "tropical") {
    return "A Chinese cultural calendar; in the southern hemisphere its seasons are reversed (立冬, the start of winter, falls in spring), so it carries no seasonal advice here.";
  }
  if (place?.climate === "tropical" || place?.climate === "monsoon_sg" || place?.climate === "monsoon_south_asia") {
    return "A Chinese cultural calendar (festivals such as 冬至); the terms describe northern-temperate seasons, not this climate, so seasonal advice written for China's winters or summers does not carry over.";
  }
  return "A Chinese cultural calendar, dated in China Standard Time (UTC+8): the local date may differ by a day.";
}

// ------------------------------------------------------------------ festive seasons
// where each is widely observed (for ranking; every festival in the window is listed, with who keeps it)
const EAST = ["CN", "HK", "MO", "TW", "SG", "MY", "VN", "KR"];
const MUSLIM = ["MY", "ID", "SG", "AE", "SA", "EG", "IN", "NG"];
const FESTIVE = {
  lunar_new_year: { name: "Lunar New Year (Chinese New Year; also Tết and Seollal)", observed: "Chinese, Vietnamese and Korean communities worldwide",
    where: [...EAST, "ID", "TH", "PH"], foods: "festive snacks (pineapple tarts, bak kwa, nian gao), dumplings, banquets, hot pot, mandarin oranges",
    tips: ["Decide on one or two festive snacks and savour them; pass on the rest.", "Mandarin oranges are a lighter snack than tarts or cured meats.",
      "Hot pot: a clear broth, lean meat, fish, tofu and plenty of vegetables; go easy on dipping sauces and processed balls."] },
  ramadan: { name: "Ramadan", observed: "Muslims worldwide", where: MUSLIM, foods: "suhoor (sahur) before dawn and iftar at sunset; dates; festive sweets and fried snacks",
    tips: ["Suhoor: wholegrains, protein (eggs, beans, yoghurt) and water, to last the day.",
      "Break the fast with water and one to three dates, then a balanced plate — not a run of fried snacks and sweet drinks.",
      "Drink water steadily between iftar and suhoor.", "If you take medicines for diabetes, discuss fasting with your doctor beforehand."],
    note: "Its start and end follow moon sighting and local religious authorities." },
  eid_fitr: { name: "Eid al-Fitr (Hari Raya Puasa)", observed: "Muslims worldwide", where: MUSLIM, foods: "festive rice dishes, rich curries and stews, cookies and sweets",
    tips: ["Rich dishes: a small portion, and fill up on vegetables.", "Cookies and sweets: a few, savoured; water or unsweetened tea rather than sweet drinks."] },
  eid_adha: { name: "Eid al-Adha (Hari Raya Haji)", observed: "Muslims worldwide", where: MUSLIM, foods: "meat dishes from the sacrifice, rice dishes, sweets",
    tips: ["Choose lean cuts and trim fat; balance a meat dish with vegetables and a modest portion of rice or bread."] },
  diwali: { name: "Diwali (Deepavali)", observed: "Hindus, Sikhs and Jains worldwide", where: ["IN", "SG", "MY"],
    foods: "sweets (mithai, ladoo, barfi), fried snacks (murukku, samosas), festive meals",
    tips: ["Sweets and fried snacks: a small plate, shared; they are rich in sugar and fat.", "At the meal: dal and vegetables alongside rice or biryani, and yoghurt or raita."] },
  vesak: { name: "Vesak", observed: "Buddhists (the date varies by country)", where: ["SG", "MY", "TH"], foods: "vegetarian meals",
    tips: ["Tofu, tempeh, beans and lentils keep a vegetarian meal high in protein; fried mock meats are often high in fat and salt."] },
  midautumn: { name: "Mid-Autumn Festival (中秋节)", observed: "Chinese and Vietnamese communities", where: ["CN", "HK", "MO", "TW", "SG", "MY", "VN"],
    foods: "mooncakes, pomelo, tea", tips: ["Share a mooncake: a quarter is a portion.", "Unsweetened tea goes with mooncakes better than sweet drinks."] },
  dongzhi: { name: "Dongzhi (冬至, winter solstice festival)", observed: "Chinese communities", where: ["CN", "HK", "MO", "TW", "SG", "MY"],
    foods: "tang yuan (glutinous rice balls in sweet soup) in the south, dumplings in the north",
    tips: ["Tang yuan: a few balls in a lightly sweetened soup; filled ones (sesame, peanut) are richer.", "Dumplings: steamed or boiled rather than fried, with vegetables on the side."] },
  easter: { name: "Easter (Western churches)", observed: "Christians (Orthodox Easter often falls later)", where: ["GB", "IE", "FR", "DE", "NL", "ES", "IT", "SE", "US", "CA", "MX", "BR", "AR", "AU", "NZ", "ZA", "NG", "KE", "PH"],
    foods: "chocolate eggs, hot cross buns, a festive roast", tips: ["Chocolate: a small egg, savoured; the roast with plenty of vegetables."] },
  thanksgiving_us: { name: "Thanksgiving (United States)", observed: "the United States", where: ["US"], foods: "roast turkey, stuffing, potatoes, pies",
    tips: ["Fill half the plate with vegetables first; take turkey without the skin; one slice of pie."] },
  thanksgiving_ca: { name: "Thanksgiving (Canada)", observed: "Canada", where: ["CA"], foods: "roast turkey, stuffing, potatoes, pies",
    tips: ["Fill half the plate with vegetables first; take turkey without the skin; one slice of pie."] },
  christmas: { name: "Christmas", observed: "Christians and many countries", where: ["*", "!SA", "!AE"], foods: "roasts, festive cakes, cookies, party food",
    tips: ["At parties: start with vegetables and lean protein, then choose one treat; alternate drinks with water."] },
};
// published dates (2026–2027): lunar ones exact; Islamic and Hindu ones approximate (Singapore's gazetted dates, which
// may differ by a day elsewhere); Vesak varies by country
const TABLE = {
  2026: [["lunar_new_year", "2026-02-17"], ["eid_fitr", "2026-03-21", true], ["eid_adha", "2026-05-27", true], ["vesak", "2026-05-31", true],
    ["midautumn", "2026-09-25"], ["diwali", "2026-11-08", true]],
  2027: [["lunar_new_year", "2027-02-06"], ["eid_fitr", "2027-03-10", true], ["vesak", "2027-05-20", true], ["midautumn", "2027-09-15"],
    ["diwali", "2027-10-28", true]],
};
export const FESTIVE_YEARS = Object.keys(TABLE).map(Number);

/** Western Easter Sunday (the Gregorian computus): [month, day]. */
export function easter(y) {
  const a = y % 19, b = Math.floor(y / 100), c = y % 100, d = Math.floor(b / 4), e = b % 4, f = Math.floor((b + 8) / 25);
  const g = Math.floor((b - f + 1) / 3), h = (19 * a + b - d - g + 15) % 30, i = Math.floor(c / 4), k = c % 4;
  const l = (32 + 2 * e + 2 * i - h - k) % 7, m = Math.floor((a + 11 * h + 22 * l) / 451);
  return [Math.floor((h + l - 7 * m + 114) / 31), ((h + l - 7 * m + 114) % 31) + 1];
}

/** The n-th `weekday` (0 = Sunday) of a month: [month, day]. */
function nthWeekday(y, month, weekday, n) {
  const first = new Date(Date.UTC(y, month - 1, 1)).getUTCDay();
  return [month, 1 + ((weekday - first + 7) % 7) + (n - 1) * 7];
}

const ymd = (y, [m, d]) => `${y}-${pad(m)}-${pad(d)}`;
const keptIn = (f, code) => !code ? null : f.where.includes(code) || (f.where.includes("*") && !f.where.includes(`!${code}`));

/** The festive seasons from `day` to `within` days on (Ramadan while it runs), those kept where the visitor lives first. */
export function festivals(day, within = 60, code = null) {
  const out = [];
  const add = (id, date, extra = {}) => {
    const inDays = Math.round((Date.parse(`${date}T00:00:00Z`) - day.at) / DAY);
    if (inDays >= 0 && inDays <= within) out.push({ id, ...FESTIVE[id], date, in_days: inDays, ...extra });
  };
  for (const y of [day.y, day.y + 1]) {
    add("christmas", `${y}-12-25`, { source: "festival_calendar" });
    add("easter", ymd(y, easter(y)), { source: "festival_calendar" });
    add("thanksgiving_us", ymd(y, nthWeekday(y, 11, 4, 4)), { source: "festival_calendar" });
    add("thanksgiving_ca", ymd(y, nthWeekday(y, 10, 1, 2)), { source: "festival_calendar" });
    add("dongzhi", termsOf(y).find((t) => t.zh === "冬至").date, { source: "solar_terms" });
    for (const [id, date, approximate] of TABLE[y] || []) {
      const extra = { source: "festival_calendar", ...(approximate ? { approximate: "may differ by a day by country (moon sighting, local calendars)" } : {}) };
      if (id === "eid_fitr") { // Ramadan: about the 29–30 days before it
        const days = Math.round((Date.parse(`${date}T00:00:00Z`) - day.at) / DAY);
        if (days > 0 && days <= 30) out.push({ id: "ramadan", ...FESTIVE.ramadan, date: `ends about ${date}`, in_days: 0, ongoing: true, ...extra });
        else if (days > 30 && days <= within + 30) out.push({ id: "ramadan", ...FESTIVE.ramadan, date: `begins about ${days - 30} days from now`, in_days: days - 30, ...extra });
      }
      add(id, date, extra);
    }
  }
  for (const f of out) {
    f.kept_where_you_live = keptIn(f, code) ?? undefined;
    delete f.where;
  }
  const rank = (f) => (f.kept_where_you_live === false ? 1 : 0);
  out.sort((a, b) => rank(a) - rank(b) || a.in_days - b.in_days);
  // a festival kept only in one country is left out elsewhere (Thanksgiving)
  const shown = out.filter((f) => !(f.id.startsWith("thanksgiving") && f.kept_where_you_live !== true));
  return { upcoming: shown, verified_years: FESTIVE_YEARS,
    note: TABLE[day.y] ? undefined : `No published festival dates here for ${day.y}: Christmas, Easter, Thanksgiving and Dongzhi are computed; check local calendars for the others.` };
}

/** The whole context for a date where the visitor lives.  `region`: an ISO code from regions.js; else the visitor's
 * `hemisphere` and `climate` if they gave them; else none (no season, festivals unranked).  The date is the region's,
 * else this device's. */
export function context({ date = null, within = 60, region: code = null, hemisphere = null, climate = null } = {}, now = new Date()) {
  const r = regionOf(code);
  const tz = r?.tz || browserZone();
  const day = localDay(date, tz, now);
  if (!day) return { ok: false, error: `date ${JSON.stringify(date)} is not a calendar date (YYYY-MM-DD)` };
  const place = r ? { ...r, ...(climate ? { climate } : {}), ...(hemisphere ? { hemisphere } : {}) }
    : climate ? { climate, hemisphere: hemisphere === "S" ? "S" : "N" } : null;
  const fest = festivals(day, Math.max(0, Math.min(120, Number(within) || 60)), r?.code || null);
  const s = season(day, place);
  const ids = [s.source, "solar_terms", ...new Set(fest.upcoming.map((f) => f.source).filter(Boolean))].filter(Boolean);
  return {
    ok: true, algorithm: ALGORITHM,
    region: r ? { code: r.code, name: r.name, time_zone: r.tz } : { code: null, note: "no region stated: the date is this device's; ask where the user lives for the season and local festivals" },
    date: day.iso, weekday: day.weekday,
    season: s, solar_term: solarTerm(day, place), festivals: fest.upcoming, festivals_note: fest.note,
    provenance: provenance(ids),
  };
}
