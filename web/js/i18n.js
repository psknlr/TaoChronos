// The page in 中文 or in English.  The page is written in Chinese: every string a visitor reads goes through T, which
// gives it back as it is, or, when the page is in English, its English from i18n-en.js (keyed by the Chinese; a
// template's key has {0}, {1}… where its values go).  A string with no English yet is shown in Chinese.  The language
// is the visitor's choice (?lang=en, or the switch in the top bar, kept in this browser), else the browser's: Chinese
// for a browser set to Chinese, English for any other.  A worker is told the page's language in its URL (?lang=…);
// under Node (the tests) the page is in Chinese.  Changing the language reloads the page.

const KEY = "tc.lang";
const LANGS = ["zh", "en"];

function pick() {
  let asked = null;
  try { asked = new URLSearchParams(globalThis.location?.search || "").get("lang"); } catch { /* no location */ }
  if (LANGS.includes(asked)) return asked;
  try {
    const kept = JSON.parse(globalThis.localStorage?.getItem(KEY) ?? "null");
    if (LANGS.includes(kept)) return kept;
  } catch { /* private mode, or a worker */ }
  if (typeof document === "undefined") return "zh";
  return /^zh\b/i.test(globalThis.navigator?.language || "") ? "zh" : "en";
}

export const LANG = pick();
export const EN_PAGE = LANG === "en";
const EN = EN_PAGE ? (await import("./i18n-en.js")).default : {}; // a Chinese page does not fetch it
/** The locale dates and numbers are written in. */
export const LOCALE = EN_PAGE ? "en-SG" : "zh-CN";

const fill = (text, values) => text.replace(/\{(\d+)\}/g, (m, i) => (Number(i) < values.length ? String(values[i]) : m));

/** A string in the page's language: T("新对话"), or as a tag, T`删除「${name}」？`. */
export function T(s, ...values) {
  if (Array.isArray(s) && s.raw) {
    const key = s.map((q, i) => q + (i < values.length ? `{${i}}` : "")).join("");
    const en = EN_PAGE ? EN[key] : undefined;
    return en === undefined ? s.reduce((a, q, i) => a + String(values[i - 1]) + q) : fill(en, values);
  }
  if (typeof s !== "string" || !EN_PAGE) return s;
  const en = EN[s];
  return en === undefined ? s : values.length ? fill(en, values) : en;
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
  document.documentElement.lang = EN_PAGE ? "en" : "zh-CN";
  if (!EN_PAGE) return;
  if (root === document && document.title) document.title = T(document.title);
  const walker = document.createTreeWalker(root.body || root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
  for (let n = walker.currentNode; n; n = walker.nextNode()) {
    if (n.nodeType === Node.TEXT_NODE) {
      const key = squeeze(n.nodeValue);
      if (key && EN[key] !== undefined) {
        const lead = /^\s/.test(n.nodeValue) ? " " : "", tail = /\s$/.test(n.nodeValue) ? " " : "";
        n.nodeValue = lead + EN[key] + tail;
      }
    } else if (n.tagName !== "SCRIPT" && n.tagName !== "STYLE") {
      for (const a of ATTRS) if (n.hasAttribute(a)) n.setAttribute(a, T(n.getAttribute(a)));
    }
  }
}
