// Which conversations carry health information, so that nothing of them leaves the page but to the model service the
// visitor chose: a conversation of the diet mode, one that called a diet tool, and an ordinary one in which the visitor
// wrote their own body measurements or health conditions.  None of them is ever recorded (records.js), and feedback on
// them carries no word of the conversation, whatever the visitor agreed to.  A diet conversation is also kept only in
// the page's memory (`ephemeral`: store.js writes none) until the visitor chooses to keep it in this browser.

import { isDiet } from "./tools.js";

export const DIET_MODE = "diet";

/** Is this a conversation of the diet mode? */
export const isDietMode = (conv) => conv?.mode === DIET_MODE;

/** Did the conversation call a diet tool (directly, or through the catalog's call)? */
export function calledDiet(conv) {
  return Boolean(conv?.messages?.some((m) => (m.segments || []).some((s) => (s.calls || []).some((c) => isDiet(c.resolved || c.name)
    || (c.name === "taochronos_call" && isDiet(c.args?.tool))))));
}

// a visitor's own health, in their words: a body measurement with its unit, or a condition, medicine, pregnancy, an
// allergy or one's weight written of oneself.  Only the first person counts — a question about a classic's 消渴, or what
// a text says of 糖尿病, is not one's own — and a dose of a herb (9 克) is no body measurement.
const MEASURE = [
  /(?:体重|體重|身高|腰围|腰圍|bmi|weigh(?:t|s|ing)?|height|waist)\D{0,8}\d{2,3}(?:\.\d+)?\s*(?:kg|公斤|千克|斤|cm|厘米|公分|lbs?|pounds|m\b)?/i,
  /\b\d{2,3}(?:\.\d)?\s*(?:kg|kgs|公斤|千克)\b.{0,12}\b\d{3}(?:\.\d)?\s*(?:cm|厘米|公分)/i,
  /\b\d{3}(?:\.\d)?\s*(?:cm|厘米|公分).{0,12}\b\d{2,3}(?:\.\d)?\s*(?:kg|kgs|公斤|千克|斤)/i,
  /(?:血糖|糖化|hba1c|a1c|blood (?:sugar|glucose|pressure)|血压|血壓)\D{0,6}\d/i,
];
const FIRST = String.raw`(?:我|本人|俺|\bi\b|\bi'm\b|\bim\b|\bmy\b|saya|aku)`;
const OWN = new RegExp(String.raw`${FIRST}.{0,16}(?:体重|體重|身高|腰围|胖|减肥|減肥|减重|減重|瘦身|怀孕|懷孕|孕期|哺乳|喂奶|糖尿病|血糖|高血压|高血壓|血压|肾病|腎病|`
  + String.raw`过敏|過敏|胆固醇|膽固醇|痛风|痛風|脂肪肝|厌食|暴食|胰岛素|胰島素|二甲双胍|降糖药|服药|吃药|`
  + String.raw`weigh|overweight|obese|lose weight|losing weight|diet\b|pregnan|breastfeed|diabet|blood sugar|blood pressure|hypertension|`
  + String.raw`kidney|cholesterol|gout|fatty liver|allerg|eating disorder|anorexi|bulimi|insulin|metformin|medication|`
  + String.raw`berat badan|hamil|kencing manis|darah tinggi|alahan)`, "i");

/** Does `text` carry the writer's own health information? */
export function healthText(text) {
  const t = String(text || "");
  return MEASURE.some((re) => re.test(t)) || OWN.test(t);
}

/** Does the conversation hold health information (and so is never recorded, nor attached to feedback)? */
export function healthConv(conv) {
  return Boolean(isDietMode(conv) || conv?.health || calledDiet(conv)
    || conv?.messages?.some((m) => m.role === "user" && healthText(m.text)));
}
