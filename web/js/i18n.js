// The page in eight languages: the six of the United Nations, Traditional Chinese, and Malay.  The page is written in
// (simplified) Chinese: every string a visitor reads goes through T, which gives it back as it is, or, when the page is in
// another language, its translation from i18n-<code>.js (keyed by the Chinese; a template's key has {0}, {1}… where its
// values go).  A string with no translation yet is shown in Chinese.  The language is the visitor's choice (?lang=…, or
// the menu in the top bar, kept in this browser), else the browser's first language the page has, else English.  A
// worker is told the page's language in its URL (?lang=…); under Node (the tests) the page is in Chinese.  Changing the
// language reloads the page.  Arabic is laid out right to left.

const KEY = "tc.lang";

/** The languages, in the menu's order: code, own name, the locale of its dates and numbers, its name in English, and
 * whether it is written right to left. */
export const LANGUAGES = [
  { code: "zh", name: "简体中文", short: "简", locale: "zh-CN", english: "Simplified Chinese" },
  { code: "zh-Hant", name: "繁體中文", short: "繁", locale: "zh-TW", english: "Traditional Chinese" },
  { code: "en", name: "English", short: "EN", locale: "en-SG", english: "English" },
  { code: "fr", name: "Français", short: "FR", locale: "fr-FR", english: "French" },
  { code: "es", name: "Español", short: "ES", locale: "es-ES", english: "Spanish" },
  { code: "ru", name: "Русский", short: "RU", locale: "ru-RU", english: "Russian" },
  { code: "ar", name: "العربية", short: "ع", locale: "ar-u-nu-latn", english: "Arabic", rtl: true },
  { code: "ms", name: "Bahasa Melayu", short: "MS", locale: "ms-SG", english: "Malay" },
];
const CODES = LANGUAGES.map((l) => l.code);

/** The page's language for a browser language tag (zh-TW → zh-Hant, en-SG → en), or null. */
export function fromTag(tag) {
  const t = String(tag || "").toLowerCase();
  if (/^zh\b/.test(t)) return /hant|-tw|-hk|-mo/.test(t) ? "zh-Hant" : "zh";
  const base = t.split("-")[0];
  return CODES.includes(base) ? base : null;
}

function pick() {
  let asked = null;
  try { asked = new URLSearchParams(globalThis.location?.search || "").get("lang"); } catch { /* no location */ }
  if (CODES.includes(asked)) return asked;
  try {
    const kept = JSON.parse(globalThis.localStorage?.getItem(KEY) ?? "null");
    if (CODES.includes(kept)) return kept;
  } catch { /* private mode, or a worker */ }
  if (typeof document === "undefined") return "zh";
  const nav = globalThis.navigator || {};
  for (const tag of nav.languages?.length ? nav.languages : [nav.language]) {
    const lang = fromTag(tag);
    if (lang) return lang;
  }
  return "en";
}

export const LANG = pick();
export const LANGUAGE = LANGUAGES.find((l) => l.code === LANG);
/** Whether the page is in the language it is written in. */
export const SOURCE_PAGE = LANG === "zh";
/** The locale dates and numbers are written in. */
export const LOCALE = LANGUAGE.locale;
const DICT = SOURCE_PAGE ? {} : (await import(`./i18n-${LANG}.js`)).default; // a Chinese page fetches none

const fill = (text, values) => text.replace(/\{(\d+)\}/g, (m, i) => (Number(i) < values.length ? String(values[i]) : m));

/** A string in the page's language: T("新对话"), or as a tag, T`删除「${name}」？`. */
export function T(s, ...values) {
  if (Array.isArray(s) && s.raw) {
    const key = s.map((q, i) => q + (i < values.length ? `{${i}}` : "")).join("");
    const out = DICT[key];
    return out === undefined ? s.reduce((a, q, i) => a + String(values[i - 1]) + q) : fill(out, values);
  }
  if (typeof s !== "string" || SOURCE_PAGE) return s;
  const out = DICT[s];
  return out === undefined ? s : values.length ? fill(out, values) : out;
}

/** Keep `lang` as this browser's choice and show the page in it. */
export function setLang(lang) {
  try { localStorage.setItem(KEY, JSON.stringify(lang)); } catch { /* private mode: for this visit only */ }
  const url = new URL(location.href);
  url.searchParams.delete("lang");
  location.replace(url.href);
}

// the page's own markup (index.html, attribution.html): its text and the attributes a visitor reads or hears
const ATTRS = ["title", "aria-label", "placeholder", "alt", "data-tip"];
const squeeze = (s) => s.replace(/\s*\n\s*/g, "").trim();

/** Put the markup under `root` in the page's language. */
export function translatePage(root = document) {
  if (typeof document === "undefined") return;
  document.documentElement.lang = LANG === "zh" ? "zh-CN" : LANG;
  document.documentElement.dir = LANGUAGE.rtl ? "rtl" : "ltr";
  if (SOURCE_PAGE) return;
  if (root === document && document.title) document.title = T(document.title);
  const walker = document.createTreeWalker(root.body || root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
  for (let n = walker.currentNode; n; n = walker.nextNode()) {
    if (n.nodeType === Node.TEXT_NODE) {
      const key = squeeze(n.nodeValue);
      if (key && DICT[key] !== undefined) {
        const lead = /^\s/.test(n.nodeValue) ? " " : "", tail = /\s$/.test(n.nodeValue) ? " " : "";
        n.nodeValue = lead + DICT[key] + tail;
      }
    } else if (n.tagName !== "SCRIPT" && n.tagName !== "STYLE" && !n.closest("[translate=no]")) {
      for (const a of ATTRS) if (n.hasAttribute(a)) n.setAttribute(a, T(n.getAttribute(a)));
    }
  }
}
