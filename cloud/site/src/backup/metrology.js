// 历代度量衡 (plugins/classics/study/metrology.py): a written dose read in the measures of a year — a historical reading
// of a text, never dosage guidance.  The tables are domains/classics/metrology.yaml (tables.METROLOGY).

import { METROLOGY } from "./tables.js";
import { escapeRe, pyRound } from "./text.js";

const DIGITS = { 一: 1, 二: 2, 两: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9, 〇: 0, 零: 0 };
const NUM = "[一二三四五六七八九十廿卅百千半〇零]+";

/** 一 → 1, 十二 → 12, 廿四 → 24, 一百二十 → 120, 半 → 0.5 (null when it is not a number). */
export function cnNumber(text) {
  if (text === "半") return 0.5;
  const s = text.replaceAll("廿", "二十").replaceAll("卅", "三十");
  let total = 0;
  let current = 0;
  for (const ch of s) {
    if (ch in DIGITS) current = DIGITS[ch];
    else if (ch === "十") { total += (current || 1) * 10; current = 0; }
    else if (ch === "百") { total += (current || 1) * 100; current = 0; }
    else if (ch === "千") { total += (current || 1) * 1000; current = 0; }
    else return null;
  }
  const value = total + current;
  return value ? value : null;
}

const byLengthDesc = (xs) => [...xs].sort((a, b) => [...b].length - [...a].length);
const weight = Object.fromEntries(Object.entries(METROLOGY.weight_units || {}).map(([k, v]) => [k, Number(v)]));
const volume = Object.fromEntries(Object.entries(METROLOGY.volume_units || {}).map(([k, v]) => [k, Number(v)]));
const count = METROLOGY.count_units || [];
const nonstandard = METROLOGY.nonstandard || [];
const periods = METROLOGY.periods || [];
const units = byLengthDesc([...Object.keys(weight), "分", ...Object.keys(volume), ...count]);
const AMOUNT = new RegExp(`(${NUM})(${units.map(escapeRe).join("|")})(半)?`, "gu");
const NONSTD = nonstandard.length ? new RegExp(`(${NUM})?(${byLengthDesc(nonstandard).map(escapeRe).join("|")})`, "gu") : null;
const LIANG_COUNT = count.length ? new RegExp(`两(?=(${count.map(escapeRe).join("|")}))`, "gu") : null;

export const notice = METROLOGY.notice || "";

export function period(year) {
  if (year === null || year === undefined) return null;
  return periods.find((p) => p.start <= year && year < p.end) || null;
}

/** Amounts in a dose: [{value, unit, kind}] (kind: weight | volume | count | nonstandard | equal). */
export function parse(dose) {
  if (!dose) return [];
  if (dose.includes("等分")) return [{ value: null, unit: "等分", kind: "equal" }];
  const out = [];
  let text = dose.split("或")[0];
  if (LIANG_COUNT) text = text.replace(LIANG_COUNT, "二"); // 两 is also the numeral two before a counting unit
  for (const [, num, unit, half] of text.matchAll(AMOUNT)) {
    const n = cnNumber(num);
    if (n === null) continue;
    const kind = unit in weight || unit === "分" ? "weight" : unit in volume ? "volume" : "count";
    out.push({ value: n + (half ? 0.5 : 0), unit, kind });
  }
  if (!out.length && NONSTD) {
    for (const [, num, unit] of text.matchAll(NONSTD)) out.push({ value: num ? cnNumber(num) : null, unit, kind: "nonstandard" });
  }
  return out;
}

function inLiang(dose, year) {
  const per = period(year);
  let total = 0;
  let found = false;
  for (const part of parse(dose)) {
    if (part.kind !== "weight" || part.value === null) continue;
    const factor = part.unit === "分" ? (per?.fen ?? 0.01) : weight[part.unit];
    if (factor === undefined || factor === null) continue;
    total += part.value * Number(factor);
    found = true;
  }
  return found ? pyRound(total, 4) : null;
}

const fmt = (x) => pyRound(x, 1).toFixed(1).replace(/0+$/, "").replace(/\.$/, "");

/** Gram (or millilitre) range of a dose in the measures of its period (null outside the tables). */
export function convert(dose, year) {
  const per = period(year);
  if (!per) return null;
  const liang = inLiang(dose, year);
  if (liang !== null && per.liang_g) {
    const [lo, hi] = per.liang_g;
    return { system: per.label, liang, grams: [pyRound(liang * lo, 1), pyRound(liang * hi, 1)],
      text: lo !== hi ? `约${fmt(liang * lo)}–${fmt(liang * hi)}克（${per.label}制）` : `约${fmt(liang * lo)}克（${per.label}制）` };
  }
  for (const part of parse(dose)) {
    if (part.kind === "volume" && part.value !== null && per.sheng_ml) {
      const sheng = part.value * volume[part.unit];
      const [lo, hi] = per.sheng_ml;
      return { system: per.label, sheng, ml: [pyRound(sheng * lo), pyRound(sheng * hi)],
        text: `约${pyRound(sheng * lo)}–${pyRound(sheng * hi)}毫升（${per.label}制）` };
    }
  }
  return null;
}
