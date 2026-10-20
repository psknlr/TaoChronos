// about.html in 中文 or English, as the rest of the site (i18n.js): the visitor's choice (?lang=, or the switch on the
// site, kept as tc.lang), else the browser's.  A classic script in the page's head, so the right half shows from the
// first paint; its links to the other language keep the choice.
(function () {
  var lang = null;
  try { lang = new URLSearchParams(location.search).get("lang"); } catch (e) { /* old browser */ }
  if (lang !== "zh" && lang !== "en") try { lang = JSON.parse(localStorage.getItem("tc.lang") || "null"); } catch (e) { /* storage unavailable */ }
  if (lang !== "zh" && lang !== "en") lang = /^zh\b/i.test(navigator.language || "") ? "zh" : "en";
  document.documentElement.lang = lang === "en" ? "en" : "zh-CN";
  if (lang === "en") document.title = "About TaoChronos · Scientific Knowledge Discovery from Ancient TCM Texts";
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a[data-lang]");
    if (!a) return;
    e.preventDefault();
    try { localStorage.setItem("tc.lang", JSON.stringify(a.dataset.lang)); } catch (err) { /* this visit only */ }
    location.replace(location.pathname + "?lang=" + a.dataset.lang);
  });
})();
