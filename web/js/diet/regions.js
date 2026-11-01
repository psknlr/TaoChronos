// Where the visitor lives, as far as the diet tools need it: the country's clock, hemisphere and broad climate (for the
// season), the BMI scale its public-health guidance uses, its national food guide (plate model and limits), and the
// dish packs that hold its own dishes.  A region not listed — or none stated — gets the international defaults (WHO);
// nothing here is a fact about the visitor until they say where they live.

/** BMI scales: the cut-offs for underweight / overweight / obesity, and the further action points. */
export const SCALES = {
  who: {
    name: "WHO international classification",
    under: 18.5, over: 25, obese: 30, higher: [35, 40], source: "who_bmi",
    bands: "<18.5 underweight · 18.5–24.9 healthy · 25–29.9 overweight · ≥30 obesity (≥35 class II, ≥40 class III)",
  },
  asian: {
    name: "lower thresholds for Asian, Middle Eastern, Black African and African-Caribbean family backgrounds (WHO 2004; NICE; Singapore's MOH)",
    under: 18.5, over: 23, obese: 27.5, higher: [32.5, 37.5], source: "lower_bmi",
    bands: "<18.5 underweight · 18.5–22.9 healthy · 23–27.4 overweight · ≥27.5 obesity",
  },
  china: {
    name: "China's adult weight standard (WS/T 428-2013)",
    under: 18.5, over: 24, obese: 28, higher: [32.5, 37.5], source: "china_bmi",
    bands: "<18.5 underweight · 18.5–23.9 normal · 24–27.9 overweight · ≥28 obesity",
  },
};

/** Waist circumference, in cm, at which risk rises (and rises further), by scale and sex. */
export const WAIST = {
  who: { male: [94, 102], female: [80, 88], source: "who_waist" },
  asian: { male: [90, 90], female: [80, 80], source: "who_waist" },
  china: { male: [85, 90], female: [80, 85], source: "china_bmi" },
};

/** Family backgrounds for which NICE and WHO use the lower BMI thresholds. */
export const LOWER_BACKGROUNDS = ["asian", "middle_eastern", "black_african", "african_caribbean"];
export const BACKGROUNDS = [...LOWER_BACKGROUNDS, "white", "other", "not_stated"];

// National food guides: their plate model and, where they set them, the daily limits a plan is checked against.
// Every number here is the guide's own; a guide without a number falls back to WHO's, and says so.
export const GUIDES = {
  who: {
    name: "WHO healthy diet", source: "who_healthy_diet",
    plate: "Plenty of vegetables, fruit, wholegrains and pulses; at least 400 g of fruit and vegetables a day; unsaturated fats in place of saturated; water to drink",
    sodium_mg: 2000, salt_g: 5, sugar: { share: 0.10, ideal: 0.05, kind: "free sugars" },
  },
  sg: {
    name: "My Healthy Plate (Health Promotion Board, Singapore)", source: "hpb_healthy_plate",
    plate: "A quarter wholegrains, a quarter protein (fish, tofu, beans, eggs, lean meat), half fruit and vegetables; water to drink; healthier oils in small amounts",
    sodium_mg: 2000, salt_g: 5, sugar: { share: 0.10, kind: "added sugar" }, extra: ["hpb_sodium", "hpb_sugar", "hpb_nutri_grade"],
  },
  my: {
    name: "Malaysian Healthy Plate ('Suku-Suku Separuh', Ministry of Health Malaysia)", source: "my_healthy_plate",
    plate: "A quarter grains (preferably wholegrain), a quarter fish, poultry, meat or legumes, half vegetables and fruit; plain water",
    sodium_mg: 2000, salt_g: 5, sugar: { share: 0.10, kind: "free sugars", fallback: true },
  },
  cn: {
    name: "Dietary Guidelines for Chinese Residents (2022) and the Chinese Food Guide Plate", source: "cn_guidelines",
    plate: "Grains and tubers (part wholegrain), plenty of vegetables, fruit, protein foods (fish, poultry, eggs, lean meat, soy), dairy every day; salt under 5 g and cooking oil 25–30 g a day",
    sodium_mg: 2000, salt_g: 5, oil_g: [25, 30], sugar: { share: 0.10, kind: "free sugars", fallback: true },
  },
  us: {
    name: "Dietary Guidelines for Americans and MyPlate", source: "us_dga",
    plate: "Half the plate fruits and vegetables, grains (at least half whole), protein foods, and dairy or fortified soy alternatives",
    sodium_mg: 2300, sugar: { share: 0.10, kind: "added sugars", note: "the 2025–2030 edition recommends no amount of added sugar; 10% of calories is the earlier editions' ceiling" },
  },
  uk: {
    name: "Eatwell Guide (UK)", source: "uk_eatwell",
    plate: "At least 5 portions of fruit and vegetables a day; starchy foods, wholegrain where possible; beans, pulses, fish, eggs and meat; dairy or alternatives; unsaturated oils in small amounts; 6–8 drinks of fluid a day",
    sodium_mg: 2400, salt_g: 6, sugar: { grams: 30, kind: "free sugars" },
  },
  ca: {
    name: "Canada's Food Guide", source: "ca_food_guide",
    plate: "Half the plate vegetables and fruits, a quarter whole grain foods, a quarter protein foods; water as the drink of choice",
    sodium_mg: 2000, salt_g: 5, sugar: { share: 0.10, kind: "free sugars", fallback: true },
  },
  au: {
    name: "Australian Guide to Healthy Eating (NHMRC)", source: "au_guide",
    plate: "Five food groups every day: vegetables and legumes, fruit, grain foods (mostly wholegrain), lean meats, fish, eggs, tofu, nuts and legumes, and milk, yoghurt, cheese or alternatives; water",
    sodium_mg: 2000, salt_g: 5, sugar: { share: 0.10, kind: "free sugars", fallback: true },
  },
  jp: {
    name: "Japanese Food Guide Spinning Top (食事バランスガイド)", source: "jp_guide",
    plate: "Staple dishes (rice, bread, noodles), side dishes of vegetables, a main dish of fish, meat, eggs or soy, milk, and fruit, with water or tea",
    sodium_mg: 2000, salt_g: 5, sugar: { share: 0.10, kind: "free sugars", fallback: true },
  },
  in: {
    name: "Dietary Guidelines for Indians (ICMR–NIN, 2024): 'My Plate for the Day'", source: "in_guidelines",
    plate: "Vegetables and fruit about half the plate, cereals and millets (wholegrain), pulses, eggs, fish or meat, nuts and seeds, and milk or curd",
    sodium_mg: 2000, salt_g: 5, sugar: { share: 0.10, kind: "free sugars", fallback: true },
  },
};

// [code, English name, 中文, time zone, hemisphere, climate, BMI scale, guide, dish packs, the climate varies within]
const ROWS = [
  ["SG", "Singapore", "新加坡", "Asia/Singapore", "N", "monsoon_sg", "asian", "sg", ["sg"]],
  ["MY", "Malaysia", "马来西亚", "Asia/Kuala_Lumpur", "N", "tropical", "asian", "my", ["sg"]],
  ["CN", "China (mainland)", "中国内地", "Asia/Shanghai", "N", "temperate", "china", "cn", [], true],
  ["HK", "Hong Kong", "中国香港", "Asia/Hong_Kong", "N", "subtropical", "asian", "who", []],
  ["MO", "Macau", "中国澳门", "Asia/Macau", "N", "subtropical", "asian", "who", []],
  ["TW", "Taiwan", "中国台湾", "Asia/Taipei", "N", "subtropical", "asian", "who", []],
  ["JP", "Japan", "日本", "Asia/Tokyo", "N", "temperate", "asian", "jp", [], true],
  ["KR", "South Korea", "韩国", "Asia/Seoul", "N", "temperate", "asian", "who", []],
  ["IN", "India", "印度", "Asia/Kolkata", "N", "monsoon_south_asia", "asian", "in", [], true],
  ["ID", "Indonesia", "印度尼西亚", "Asia/Jakarta", "S", "tropical", "asian", "who", []],
  ["TH", "Thailand", "泰国", "Asia/Bangkok", "N", "tropical", "asian", "who", []],
  ["VN", "Vietnam", "越南", "Asia/Ho_Chi_Minh", "N", "tropical", "asian", "who", [], true],
  ["PH", "Philippines", "菲律宾", "Asia/Manila", "N", "tropical", "asian", "who", []],
  ["AE", "United Arab Emirates", "阿联酋", "Asia/Dubai", "N", "arid", "who", "who", []],
  ["SA", "Saudi Arabia", "沙特阿拉伯", "Asia/Riyadh", "N", "arid", "who", "who", []],
  ["EG", "Egypt", "埃及", "Africa/Cairo", "N", "arid", "who", "who", []],
  ["GB", "United Kingdom", "英国", "Europe/London", "N", "temperate", "who", "uk", []],
  ["IE", "Ireland", "爱尔兰", "Europe/Dublin", "N", "temperate", "who", "who", []],
  ["FR", "France", "法国", "Europe/Paris", "N", "temperate", "who", "who", []],
  ["DE", "Germany", "德国", "Europe/Berlin", "N", "temperate", "who", "who", []],
  ["NL", "Netherlands", "荷兰", "Europe/Amsterdam", "N", "temperate", "who", "who", []],
  ["ES", "Spain", "西班牙", "Europe/Madrid", "N", "temperate", "who", "who", []],
  ["IT", "Italy", "意大利", "Europe/Rome", "N", "temperate", "who", "who", []],
  ["SE", "Sweden", "瑞典", "Europe/Stockholm", "N", "cold", "who", "who", []],
  ["RU", "Russia", "俄罗斯", "Europe/Moscow", "N", "cold", "who", "who", [], true],
  ["US", "United States", "美国", "America/New_York", "N", "temperate", "who", "us", [], true],
  ["CA", "Canada", "加拿大", "America/Toronto", "N", "cold", "who", "ca", [], true],
  ["MX", "Mexico", "墨西哥", "America/Mexico_City", "N", "subtropical", "who", "who", [], true],
  ["BR", "Brazil", "巴西", "America/Sao_Paulo", "S", "tropical", "who", "who", [], true],
  ["AR", "Argentina", "阿根廷", "America/Argentina/Buenos_Aires", "S", "temperate", "who", "who", [], true],
  ["AU", "Australia", "澳大利亚", "Australia/Sydney", "S", "temperate", "who", "au", [], true],
  ["NZ", "New Zealand", "新西兰", "Pacific/Auckland", "S", "temperate", "who", "who", []],
  ["ZA", "South Africa", "南非", "Africa/Johannesburg", "S", "subtropical", "who", "who", []],
  ["NG", "Nigeria", "尼日利亚", "Africa/Lagos", "N", "tropical", "who", "who", []],
  ["KE", "Kenya", "肯尼亚", "Africa/Nairobi", "S", "tropical", "who", "who", []],
];
export const REGIONS = Object.fromEntries(ROWS.map(([code, name, zh, tz, hemisphere, climate, scale, guide, packs, varied]) =>
  [code, { code, name, zh, tz, hemisphere, climate, scale, guide, packs, varied: Boolean(varied) }]));
export const REGION_CODES = Object.keys(REGIONS);

/** A region by its code (any case), or null. */
export const region = (code) => REGIONS[String(code || "").trim().toUpperCase()] || null;

// time zones that are not a region's default, by the region they belong to (a browser's zone, read on the device)
const ZONES = {
  "America/Chicago": "US", "America/Denver": "US", "America/Los_Angeles": "US", "America/Phoenix": "US", "America/Anchorage": "US",
  "Pacific/Honolulu": "US", "America/Vancouver": "CA", "America/Edmonton": "CA", "America/Winnipeg": "CA", "America/Halifax": "CA",
  "Australia/Melbourne": "AU", "Australia/Brisbane": "AU", "Australia/Perth": "AU", "Australia/Adelaide": "AU", "Australia/Darwin": "AU",
  "Australia/Hobart": "AU", "Asia/Chongqing": "CN", "Asia/Urumqi": "CN", "Asia/Harbin": "CN", "Asia/Calcutta": "IN", "Asia/Saigon": "VN",
  "Asia/Makassar": "ID", "Asia/Jayapura": "ID", "Asia/Kuching": "MY", "Europe/Belfast": "GB", "America/Manaus": "BR", "America/Recife": "BR",
};

/** The region a time zone (e.g. the browser's) suggests, or null: a default the visitor can change, never a fact. */
export function regionOfZone(tz) {
  if (!tz) return null;
  const hit = ROWS.find((r) => r[3] === tz);
  return hit ? hit[0] : ZONES[tz] || null;
}

/** The browser's own time zone (on the device; null where it cannot tell). */
export function browserZone() {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || null; } catch { return null; }
}

/** The BMI scale for a visitor: the lower thresholds for the family backgrounds NICE and WHO name, China's standard for a
 * visitor in China, else the region's own, else WHO's.  Says why. */
export function scaleFor({ region: code = null, background = null } = {}) {
  const r = region(code);
  if (LOWER_BACKGROUNDS.includes(background)) {
    return { scale: r?.scale === "china" ? "china" : "asian", why: r?.scale === "china" ? "living in China" : "family background with higher risk at lower BMI" };
  }
  if (background === "white" || background === "other") return { scale: "who", why: "family background" };
  // the international scale for want of a background: NICE's lower thresholds follow family background, not residence,
  // so where they would read a BMI otherwise the background may be asked (assess.js)
  if (r) return { scale: r.scale, why: `region ${r.name}`, ambiguous: r.scale === "who" };
  return { scale: "who", why: "no region or family background stated: the international scale", ambiguous: true };
}

/** The guide for a region (WHO's when it has none of its own). */
export const guideFor = (code) => GUIDES[region(code)?.guide || "who"];
