// The diet mode's constitution self-check and medicinal dishes (docs/diet.md, "Medicinal dishes"): the published 60-question
// questionnaire (ZYYXH/T157-2009), a short safety check, and the dishes that suit the result, the season where the
// visitor lives and the time of day — all computed in the page, without a model and without sending anything.  The
// questions are shown in Chinese and English only (a questionnaire's meaning rests on its exact words); the page around
// them is in the visitor's language.  The visitor may send the result to the model as a message (only on pressing).

import { constitution, itemsFor, SCALE, TYPE_NAMES } from "../diet/constitution.js";
import { medicinal } from "../diet/medicinal.js";
import { DISHES, FOODS } from "../diet/medicinal-data.js";
import { region, REGIONS } from "../diet/regions.js";
import { h, icon } from "../util.js";
import { LANG, T } from "../i18n.js";

const ZH = LANG.startsWith("zh");
const SEP = ZH ? "、" : ", ";
const TYPE = {
  pinghe: T("平和质"), qixu: T("气虚质"), yangxu: T("阳虚质"), yinxu: T("阴虚质"), tanshi: T("痰湿质"), shire: T("湿热质"),
  xueyu: T("血瘀质"), qiyu: T("气郁质"), tebing: T("特禀质"),
};
const JUDGE = { yes: T("是"), basically: T("基本是"), tendency: T("倾向是"), no: T("否") };
const SLOT = { breakfast: T("早餐"), lunch: T("午餐"), afternoon: T("下午"), dinner: T("晚餐") };
const QUALITY = { spring: T("春季"), summer: T("夏季"), autumn: T("秋季"), winter: T("冬季"), hot: T("炎热"), wet: T("潮湿"), dry: T("干燥"), cold: T("寒冷") };
const CONDITIONS = [["none", T("都没有")], ["pregnant", T("怀孕")], ["breastfeeding", T("哺乳")], ["kidney_disease", T("肾病")],
  ["diabetes", T("糖尿病")], ["gout", T("痛风")], ["eating_disorder", T("饮食失调（现在或过去）")], ["food_allergy", T("食物过敏")]];
const MEDICINES = [["none", T("不服药")], ["anticoagulant", T("抗凝药（如华法林）")], ["immunosuppressant", T("免疫抑制剂")],
  ["diabetes_medicine", T("降糖药")], ["other", T("其他长期用药")]];
const ALLERGENS = [["tree_nut", T("坚果")], ["sesame", T("芝麻")], ["milk", T("奶")], ["egg", T("蛋")]];
const RULES = [["halal", T("清真")], ["vegetarian", T("素食")], ["vegan", T("纯素")], ["no_pork", T("不吃猪肉")]];
const TIMES = [["now", T("现在这一餐")], ["day", T("一天的安排")], ["breakfast", T("早餐")], ["lunch", T("午餐")], ["afternoon", T("下午")], ["dinner", T("晚餐")]];
const EXCLUDED = {
  allergen: T("含过敏原"), diet: T("不合饮食规定"), medicine: T("与所服药物可能相互作用"), condition: T("不宜于所述健康情况"),
  constitution: T("不宜于此体质"), season: T("不合时令"), time: T("不合时辰"),
};
const NOT_OFFERED = {
  pregnant: T("怀孕期间不推荐药膳：其中一些食材在孕期有传统上的禁忌，新近列入目录的几种也写明不推荐孕妇食用。普通饮食及医生、助产士的建议照常适用。"),
  breastfeeding: T("哺乳期不推荐药膳；普通饮食照常，任何草本食物请先问医生。"),
  kidney_disease: T("肾病：不推荐药膳——有几道含钾较高，草本食材也须由肾科团队审核。"),
  eating_disorder: T("有饮食失调（现在或过去）时，饮食宜与照护团队一起安排，这里不推荐药膳。"),
  unexplained_weight_loss: T("不明原因的体重下降须先请医生评估，不推荐药膳。"),
  under_18: T("未满 18 岁：本模式面向成年人，不推荐药膳。"),
};
const regionName = (r) => (ZH ? r.zh : r.name);
const dishName = (d) => (ZH ? d.zh : d.en);
/** A dish's ingredients in the page's language; ＊ marks a substance on China's food–medicine list. */
const parts = (id) => (DISHES.find((x) => x.id === id)?.ingredients || [])
  .map((i) => `${ZH ? i.zh : FOODS[i.food]?.en || i.en} ${i.g} g${i.homology !== "food" ? "＊" : ""}`).join(ZH ? "；" : "; ");
const scroll = (table) => h("div.tz-scroll", table);

function checks(name, items) {
  return h("div.qc-checks", items.map(([v, t]) => h("label.check", h("input", { type: "checkbox", name, value: v }), h("span", t))));
}
function field(label, input) { return h("label.qc-field", h("span", label), input); }

/** One question: its words (Chinese, or English with the Chinese beneath) and the five answers. */
function question(item, n) {
  const words = LANG === "zh" ? item.zh : LANG === "zh-Hant" ? T(item.zh) : item.en;
  return h("fieldset.tz-item", { dataset: { item: item.id, ...(item.sex ? { sex: item.sex } : {}) } },
    h("legend", h("span.tz-n", `${n}.`), " ", words, ZH ? null : h("small.muted", item.zh)),
    h("div.tz-scale", SCALE.map(([v, zh, en]) => h("label.check", h("input", { type: "radio", name: `q_${item.id}`, value: v }),
      h("span", ZH ? T(zh) : en)))));
}

/** The panel on the diet mode's opening screen. */
export function constitutionCheck(ctx, guess = null) {
  const out = h("div.qc-out", { role: "status" });
  const rows = Object.values(REGIONS).sort((a, b) => regionName(a).localeCompare(regionName(b)));
  const sex = h("select", { name: "sex" }, h("option", { value: "" }, T("请选择")),
    [["female", T("女")], ["male", T("男")], ["not_stated", T("不愿说明")]].map(([v, t]) => h("option", { value: v }, t)));
  const list = h("div.tz-items");
  const draw = () => {
    const kept = Object.fromEntries([...list.querySelectorAll("input:checked")].map((i) => [i.name, i.value]));
    list.replaceChildren(...itemsFor(sex.value).map((it, k) => question(it, k + 1)));
    for (const [n, v] of Object.entries(kept)) { const i = list.querySelector(`input[name="${n}"][value="${v}"]`); if (i) i.checked = true; }
  };
  sex.addEventListener("change", draw);
  draw();
  const form = h("form.qc-form.tz-form",
    h("p.muted", T("按《中医体质分类与判定》（中华中医药学会 ZYYXH/T157-2009，60 题）计分；请根据近一年的体验和感觉回答。体质是养生用的倾向，不是诊断；该标准已于 2026 年由 27 题的国家标准（GB/T 46939—2025）取代，结果只作参考。")),
    ZH ? null : h("p.muted", T("问卷只以中文和英文呈现：问卷的意思取决于原文的措辞，故不另作翻译。")),
    h("div.qc-row",
      field(T("性别（决定其中一题）"), sex),
      field(T("年龄"), h("input", { type: "number", name: "age", inputmode: "numeric", min: 0, placeholder: T("岁") })),
      field(T("所在国家或地区"), h("select", { name: "region" }, h("option", { value: "" }, T("其他 / 不说明")),
        rows.map((r) => h("option", { value: r.code, selected: r.code === guess }, regionName(r)))))),
    list,
    h("p.lb", T("安全检查：以下情况有吗？")), checks("conditions", CONDITIONS),
    h("p.lb", T("长期用药")), checks("medicines", MEDICINES),
    h("p.lb", T("食物过敏")), checks("allergies", [["none", T("没有")], ...ALLERGENS]),
    h("p.lb", T("饮食规定")), checks("diet", RULES),
    h("div.qc-row", field(T("推荐哪一餐"), h("select", { name: "time" }, TIMES.map(([v, t]) => h("option", { value: v }, t))))),
    h("div.qc-actions", h("button.btn", { type: "submit" }, T("计算体质并推荐药膳")), h("span.muted", T("不调用模型，不发送任何内容"))),
    out);
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const data = new FormData(form);
    const answers = {};
    for (const [k, v] of data.entries()) if (k.startsWith("q_")) answers[k.slice(2)] = Number(v);
    const sx = data.get("sex") || null;
    const profile = {};
    for (const k of ["conditions", "medicines", "allergies", "diet"]) { const v = data.getAll(k); if (v.length) profile[k] = v; }
    if (profile.conditions?.includes("none") && profile.conditions.length > 1) profile.conditions = profile.conditions.filter((c) => c !== "none");
    if (data.get("age")) profile.age = Number(data.get("age"));
    const code = data.get("region") || null;
    const c = constitution({ answers, sex: sx });
    const m = medicinal({ profile, region: code, time: data.get("time") || "now",
      constitution: c.status === "not_started" ? null : { primary: c.result.primary, tendency: c.result.tendency, source: "questionnaire" } });
    out.replaceChildren(...constitutionResult(c), ...medicinalResult(m), h("button.btn.secondary", { type: "button",
      on: { click: () => ctx.onAskWith(askText(c, profile, code)) } }, icon("sparkle", "sm"), T("带着结果问道乃久")));
  });
  return h("details.quick-check.tz-check", h("summary", icon("leaf", "sm"), T("体质自测与药膳推荐（不用模型）")), form);
}

function constitutionResult(c) {
  const nodes = [];
  if (c.status === "not_started") return [h("p.muted", T("没有作答体质问卷：下面只按季节与时辰推荐。"))];
  if (c.status === "partial") nodes.push(h("p.muted", T`已答 ${c.answered}/${c.of} 题：题目答全的体质才判定。`));
  const r = c.result;
  const named = (list) => list.map((t) => TYPE[t]).join(SEP);
  const line = r.primary.length ? T`你的体质：${named(r.primary)}` : r.balanced && (r.balanced.judgement === "yes" || r.balanced.judgement === "basically")
    ? T`你的体质：平和质（${JUDGE[r.balanced.judgement]}）` : T("没有达到判定标准的偏颇体质");
  nodes.push(h("p", h("b", line), r.tendency.length ? T`；倾向：${named(r.tendency)}` : ""));
  nodes.push(scroll(h("table.qc-plan.tz-scores",
    h("thead", h("tr", h("th", T("体质")), h("th", T("转化分")), h("th", T("判定")))),
    h("tbody", c.types.map((t) => h("tr", { class: t.judgement === "yes" || t.judgement === "basically" ? "on" : t.judgement === "tendency" ? "near" : "" },
      h("td", TYPE[t.type], ZH ? null : h("small.muted", ` ${TYPE_NAMES[t.type][0]}`)), h("td", String(t.transformed)), h("td", JUDGE[t.judgement] || "—")))))));
  nodes.push(h("p.muted", T("体质是养生用的自评倾向，不是疾病或证型的诊断；其中的症状（疼痛、瘀斑、心慌、情绪低落、气短等）如持续，请看医生。")));
  return nodes;
}

function medicinalResult(m) {
  if (!m.ok) return [h("p.notice.warn", m.error || T("失败"))];
  if (m.status === "not_offered") return [h("p.notice.warn", T("不推荐药膳：")), ...m.codes.map((x) => h("p", NOT_OFFERED[x] || x))];
  if (m.status === "needs_information") return [h("p.notice.warn", T("请先完成安全检查：健康情况与长期用药（没有就勾“都没有”“不服药”）。"))];
  const nodes = [h("p", h("b", T("推荐的药膳")), m.now.season?.phase ? ` · ${(m.now.season.qualities || []).map((q) => QUALITY[q] || q).join(SEP)}` : ` · ${T("未选所在地，不按季节")}`)];
  const groups = m.meals || [{ slot: m.slot, dishes: m.dishes || [] }];
  if (m.slot === "late") nodes.push(h("p", T("夜已深：古籍说饱食即卧会生百病；饿的话，吃一点清淡的就好。")));
  const rows = groups.flatMap((g) => g.dishes.map((d, k) => h("tr",
    h("td", k === 0 ? SLOT[g.slot] || "" : ""),
    h("td", h("b", dishName(d)), h("br"), h("small.muted", ZH ? d.en : d.zh), h("br"), h("small", parts(d.id))),
    h("td", fitText(d.fits)),
    h("td", d.nutrition.energy_kcal != null ? T`${d.nutrition.energy_kcal} 千卡` : "—", d.nutrition.protein_g != null ? h("br") : null,
      d.nutrition.protein_g != null ? T`蛋白质 ${d.nutrition.protein_g} 克` : null, d.nutrition.not_counted ? h("small.muted", h("br"), T`未计入：${d.nutrition.not_counted.join(SEP)}`) : null),
    h("td", d.classics.filter(Boolean).slice(0, 2).map((q) => h("div.tz-quote", h("span", `《${q.work}》`), `「${q.quote}」`, ZH ? null : h("small.muted", h("br"), q.says)))),
  )));
  if (rows.length) {
    nodes.push(scroll(h("table.qc-plan.tz-dishes",
      h("thead", h("tr", h("th", T("餐次")), h("th", T("药膳与配料")), h("th", T("为何适合")), h("th", T("每份")), h("th", T("古籍出处")))),
      h("tbody", rows))));
    nodes.push(h("p.muted", T("＊ 中国“食药物质目录”所列之物")));
    for (const g of groups) for (const d of g.dishes) {
      const cautions = d.cautions.filter(Boolean);
      nodes.push(h("details.tz-method", h("summary", dishName(d)), h("p", ZH ? d.method_zh : d.method_en),
        cautions.length ? h("ul", cautions.map((c) => h("li", c.quote ? [`《${c.work}》「${c.quote}」`, ZH ? null : h("small.muted", ` ${c.says}`)] : c.note))) : null));
    }
  } else nodes.push(h("p", T("这一餐没有合适的药膳。")));
  const left = (m.left_out || []).slice(0, 8);
  if (left.length) nodes.push(h("details.tz-left", h("summary", T`未推荐的 ${(m.left_out || []).length} 道及原因`),
    h("ul", left.map((x) => h("li", `${ZH ? x.zh : x.en}：${EXCLUDED[x.code] || x.code}${x.type ? `（${TYPE[x.type]}）` : ""}${x.quality ? `（${QUALITY[x.quality] || x.quality}）` : ""}`,
      x.quote ? h("small.muted", ` 《${x.quote.work}》「${x.quote.quote}」`) : null)))));
  nodes.push(h("p.muted", T("配料均为日常食物或中国“食药物质目录”所列之物，按菜谱用量；营养数值由 USDA 食物成分数据按份量加总，无数据的配料注明未计入。古籍原文是历史文献的说法，不是现代疗效证据。药膳是食养，不是治疗；有病在身或长期服药，请先问医生或药剂师。")));
  return nodes;
}

function fitText(fits = []) {
  const parts = fits.map((f) => f.kind === "constitution" ? (f.level === "primary" ? T`宜${TYPE[f.type]}` : T`宜${TYPE[f.type]}倾向`)
    : f.kind === "season" ? T`合时令（${f.qualities.map((q) => QUALITY[q] || q).join(SEP)}）` : f.kind === "mild" ? T("性味平和") : "");
  return parts.filter(Boolean).join(ZH ? "；" : "; ") || "—";
}

/** The result as a message the visitor sends (only when they press the button). */
function askText(c, p, code) {
  const parts = [];
  if (c.status !== "not_started") {
    const r = c.result;
    const named = (list) => list.map((t) => TYPE[t]).join(SEP);
    parts.push(T`体质自测（ZYYXH/T157-2009，已答 ${c.answered}/${c.of} 题）：${r.primary.length ? T`是：${named(r.primary)}` : r.balanced ? T`平和质：${JUDGE[r.balanced.judgement]}` : T("无达到标准的偏颇体质")}${r.tendency.length ? T`；倾向是：${named(r.tendency)}` : ""}`);
  }
  if (code && region(code)) parts.push(T`住在${regionName(region(code))}`);
  if (p.age) parts.push(T`${p.age} 岁`);
  const name = (list, v) => list.find(([k]) => k === v)?.[1] || v;
  if (p.conditions) parts.push(T`健康情况：${p.conditions.map((x) => name(CONDITIONS, x)).join("、")}`);
  if (p.medicines) parts.push(T`长期用药：${p.medicines.map((x) => name(MEDICINES, x)).join("、")}`);
  if (p.allergies) parts.push(T`过敏：${p.allergies.map((x) => (x === "none" ? T("没有") : name(ALLERGENS, x))).join("、")}`);
  if (p.diet) parts.push(T`饮食规定：${p.diet.map((x) => name(RULES, x)).join("、")}`);
  return T`${parts.join("；")}。请据此推荐适合我现在的药膳，并说明古籍出处。`;
}

