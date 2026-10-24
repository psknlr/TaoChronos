// about.html in the site's eight languages, as the rest of the site (i18n.js): the visitor's choice (?lang=, or the menu
// on the site, kept as tc.lang), else the browser's first language the page has, else English.  A classic script in the
// page's head, so the right version shows from the first paint; its links to the other languages keep the choice.
(function () {
  var CODES = ["zh", "zh-Hant", "en", "fr", "es", "ru", "ar", "ms"];
  var TITLES = {
    "zh-Hant": "關於道乃久 · 中醫古籍科學知識發現智能體平臺",
    en: "About TaoChronos · Scientific Knowledge Discovery from Ancient TCM Texts",
    fr: "À propos de TaoChronos · Découverte de connaissances scientifiques dans les textes anciens de MTC",
    es: "Acerca de TaoChronos · Descubrimiento de conocimiento científico en textos antiguos de MTC",
    ru: "О TaoChronos · Научное открытие знаний в древних текстах ТКМ",
    ar: "حول TaoChronos · اكتشاف المعرفة العلمية من نصوص الطب الصيني التقليدي القديمة",
    ms: "Perihal TaoChronos · Penemuan Pengetahuan Saintifik daripada Teks Purba PTC",
  };
  // a browser language tag as one of the page's (zh-TW → zh-Hant, en-SG → en), or null
  function fromTag(tag) {
    var t = String(tag || "").toLowerCase();
    if (/^zh\b/.test(t)) return /hant|-tw|-hk|-mo/.test(t) ? "zh-Hant" : "zh";
    var base = t.split("-")[0];
    return CODES.indexOf(base) >= 0 ? base : null;
  }
  var lang = null;
  try { lang = new URLSearchParams(location.search).get("lang"); } catch (e) { /* old browser */ }
  if (CODES.indexOf(lang) < 0) try { lang = JSON.parse(localStorage.getItem("tc.lang") || "null"); } catch (e) { /* storage unavailable */ }
  if (CODES.indexOf(lang) < 0) {
    var tags = navigator.languages && navigator.languages.length ? navigator.languages : [navigator.language];
    lang = "en";
    for (var i = 0; i < tags.length; i++) if (fromTag(tags[i])) { lang = fromTag(tags[i]); break; }
  }
  var root = document.documentElement;
  root.lang = lang === "zh" ? "zh-CN" : lang;
  root.dir = lang === "ar" ? "rtl" : "ltr";
  root.setAttribute("data-lang", lang);
  if (TITLES[lang]) document.title = TITLES[lang];
  document.addEventListener("DOMContentLoaded", function () {
    var here = document.querySelector('.langs a[data-lang="' + lang + '"]');
    if (here) here.setAttribute("aria-current", "page");
  });
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a[data-lang]");
    if (!a) return;
    e.preventDefault();
    try { localStorage.setItem("tc.lang", JSON.stringify(a.dataset.lang)); } catch (err) { /* this visit only */ }
    location.replace(location.pathname + "?lang=" + a.dataset.lang);
  });
})();
