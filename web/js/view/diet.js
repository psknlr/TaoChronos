// The diet mode's own screens (docs/diet.md): its opening screen, with what happens to what one tells it and a quick
// check that runs on this device without a model; the line at the head of a diet conversation (not recorded, kept only
// in this page unless the visitor keeps it); and the way into the mode from the platform's opening screen.

import { assess } from "../diet/assess.js";
import { plan } from "../diet/plan.js";
import { context } from "../diet/context.js";
import { browserZone, region, REGIONS, regionOfZone } from "../diet/regions.js";
import { h, icon } from "../util.js";
import { LANG, T } from "../i18n.js";

export const DIET_STARTERS = [
  { title: T("减重方案"), prompt: T("我想减重，请帮我定一个适合我的饮食方案。") },
  { title: T("外出就餐"), prompt: T("我经常在外面吃饭或叫外卖，怎样选得更健康、更有利于控制体重？") },
  { title: T("素食或清真一周餐单"), prompt: T("我吃素（或清真），想要一周的健康饮食计划。") },
  { title: T("节日怎么吃"), prompt: T("最近有什么节日？节日期间怎样吃得健康一些？") },
  { title: T("当季怎么吃"), prompt: T("按我所在地现在的季节，这周饮食上该注意什么？") },
  { title: T("热气与凉"), prompt: T("我常觉得口干、容易“上火”，饮食上该注意什么？") },
];

export const DIET_NOTICE = [
  [T("不记录"), T("这类对话不发送对话记录；评价时也不附带对话内容。")],
  [T("默认不保存"), T("对话默认不保存，关闭或刷新页面后消失；你可以选择保存（不加密）。")],
  [T("模型读到什么"), T("你在对话中写的内容会发给你所选的模型服务，用来作答。")],
  [T("不是诊断"), T("这里给的是一般的饮食建议，不是诊断或治疗；孕期、未成年、饮食失调、肾病或使用胰岛素等情况，会先建议你咨询专业人员。")],
];

/** The way into the diet mode from the platform's opening screen. */
export function dietEntry(ctx) {
  return h("button.diet-entry-card", { type: "button", on: { click: ctx.onDietMode } },
    icon("leaf", "sm"),
    h("span.grow", h("b", T("饮食与体重管理")), h("span", T("按你所在地的膳食指南、季节与饮食习惯，定制减重与健康饮食方案；不记录对话"))),
    icon("chev", "sm"));
}

const SEASON = {
  northeast_monsoon_wet: T("东北季风（湿季）"), northeast_monsoon_dry: T("东北季风（干季）"), inter_monsoon_1: T("季风间歇期"),
  inter_monsoon_2: T("季风间歇期"), southwest_monsoon: T("西南季风"), pre_monsoon: T("热季"), post_monsoon: T("季风后期"),
  winter: T("冬季"), spring: T("春季"), summer: T("夏季"), autumn: T("秋季"), tropical: T("热带气候"),
};
const FESTIVAL = {
  lunar_new_year: T("农历新年"), ramadan: T("斋月"), eid_fitr: T("开斋节"), eid_adha: T("宰牲节"), diwali: T("排灯节（屠妖节）"),
  vesak: T("卫塞节"), midautumn: T("中秋节"), dongzhi: T("冬至"), easter: T("复活节"), thanksgiving_us: T("感恩节"), thanksgiving_ca: T("感恩节"),
  christmas: T("圣诞节"),
};
const regionName = (r) => (LANG.startsWith("zh") ? r.zh : r.name);

/** The opening screen of a diet conversation.  Today's line reads the device's own time zone, on the device. */
export function dietHero(ctx) {
  const guess = regionOfZone(browserZone());
  const today = context({ region: guess });
  const r = region(guess);
  const fest = today.ok ? today.festivals.find((f) => !f.ongoing && f.kept_where_you_live !== false) : null;
  const now = today.ok ? today.solar_term.current : null;
  const term = !now ? "" : LANG.startsWith("zh") ? now.zh : `${now.en} ${now.zh}`; // the solar term: a cultural calendar
  const line = today.ok ? [today.date, r ? regionName(r) : null, SEASON[today.season.phase], term,
    fest ? T`${fest.in_days} 天后：${FESTIVAL[fest.id] || fest.name}` : null].filter(Boolean).join(" · ") : "";
  return h("div.hero.diet-hero",
    h("div.diet-seal", icon("leaf")),
    h("h1", T("饮食与体重管理")),
    h("div.model-badge", h("b", T("循证营养")), h("span", T("各国膳食指南 · 家常菜与外出就餐 · 季节与节令"))),
    h("p.sub", T("说说你的目标，我每次只问一两个问题；两轮之内给出初步方案，所有数字都注明出处。")),
    line ? h("p.diet-today", line) : null,
    h("ul.diet-notice", DIET_NOTICE.map(([b, t]) => h("li", h("b", b), " ", t))),
    h("div.starters", DIET_STARTERS.map((s) => h("button.starter", { type: "button", on: { click: () => ctx.onStarter(s.prompt) } }, h("b", s.title), s.prompt))),
    quickCheck(ctx, guess),
    h("p.keyhint", h("button", { type: "button", on: { click: ctx.onLeaveDiet } }, T("回到中医古籍研究"))),
  );
}

/** The line at the head of a diet conversation: not recorded; kept only in this page unless the visitor keeps it. */
export function dietBanner(conv, ctx) {
  const kept = !conv.ephemeral;
  return h("div.diet-banner", { role: "note" },
    icon("leaf", "sm"),
    h("span.grow", T("饮食与体重管理 · 本对话不发送记录"), " · ",
      kept ? T("已保存（未加密）") : T("未保存，关闭页面后消失")),
    h("button.linkish", { type: "button", on: { click: () => ctx.onKeep(conv, !kept) } }, kept ? T("不再保存") : T("保存这段对话")));
}

// ------------------------------------------------------------------ the quick check: on this device, without a model
const ACTIVITY = [["sedentary", T("久坐")], ["light", T("轻度活动")], ["moderate", T("中度活动")], ["high", T("高强度活动")], ["unsure", T("不确定")]];
const GOALS = [["lose_weight", T("减重")], ["maintain", T("保持体重")], ["eat_better", T("吃得更健康")]];
const CONDITIONS = [["none", T("没有")], ["pregnant", T("怀孕")], ["breastfeeding", T("哺乳")], ["diabetes", T("糖尿病")],
  ["glucose_lowering_medicine", T("用胰岛素或磺脲类药")], ["kidney_disease", T("肾病")], ["eating_disorder", T("饮食失调（现在或过去）")],
  ["high_blood_pressure", T("高血压")], ["high_cholesterol", T("高胆固醇")], ["food_allergy", T("食物过敏")], ["other", T("其他")]];
const ALLERGENS = [["peanut", T("花生")], ["tree_nut", T("坚果")], ["crustacean", T("虾蟹")], ["mollusc", T("贝类、鱿鱼")], ["fish", T("鱼")],
  ["egg", T("蛋")], ["milk", T("奶")], ["soy", T("大豆")], ["wheat", T("小麦")], ["sesame", T("芝麻")]];
const BACKGROUND = [["asian", T("亚洲（南亚、东亚或东南亚）")], ["middle_eastern", T("中东")], ["black_african", T("非洲黑人")],
  ["african_caribbean", T("加勒比非裔")], ["white", T("白人 / 欧洲")], ["other", T("其他或混合")], ["not_stated", T("不愿说明")]];
const RULES = [["halal", T("清真")], ["vegetarian", T("素食")], ["no_beef", T("不吃牛肉")], ["no_pork", T("不吃猪肉")], ["ramadan_fasting", T("斋月")]];
const STATUS = {
  ready: T("可以制定方案"), needs_information: T("还需要一些信息"), general_guidance_only: T("只给一般建议，不设热量目标"),
  see_professional_first: T("建议先咨询专业人员"),
};
const SCALE = { who: T("WHO 国际标准"), asian: T("亚洲等族裔的较低切点"), china: T("中国成人体重标准") };
const BAND = { underweight: T("偏轻"), healthy: T("健康范围"), overweight: T("超重（中度风险）"), obese: T("肥胖（高风险）"), not_applicable: T("不适用") };
const SLOT = { breakfast: T("早餐"), lunch: T("午餐"), dinner: T("晚餐"), brunch: T("早午餐"), sahur: T("封斋饭"), iftar: T("开斋饭") };

function field(label, input) { return h("label.qc-field", h("span", label), input); }

/** The country list, the one this device's time zone suggests chosen (the visitor changes it; nothing is sent). */
function regionSelect(guess) {
  const rows = Object.values(REGIONS).sort((a, b) => regionName(a).localeCompare(regionName(b)));
  return h("select", { name: "region" }, h("option", { value: "" }, T("其他 / 不说明")),
    rows.map((r) => h("option", { value: r.code, selected: r.code === guess }, regionName(r))));
}
function checks(name, items) {
  return h("div.qc-checks", items.map(([v, t]) => h("label.check", h("input", { type: "checkbox", name, value: v }), h("span", t))));
}

function quickCheck(ctx, guess = null) {
  const num = (name, ph) => h("input", { type: "number", name, inputmode: "decimal", placeholder: ph, min: 0 });
  const select = (name, items, first) => h("select", { name }, first ? h("option", { value: "" }, first) : null, items.map(([v, t]) => h("option", { value: v }, t)));
  const out = h("div.qc-out", { role: "status" });
  const form = h("form.qc-form",
    h("div.qc-row",
      field(T("你的目标"), select("goal", GOALS)),
      field(T("年龄"), num("age", T("岁"))),
      field(T("用于能量公式的性别"), select("sex", [["male", T("男")], ["female", T("女")], ["not_stated", T("不愿说明")]], T("请选择"))),
      field(T("身高（厘米）"), num("height_cm", "cm")),
      field(T("体重（公斤）"), num("weight_kg", "kg")),
      field(T("平时活动"), select("activity", ACTIVITY, T("请选择"))),
      field(T("所在国家或地区"), regionSelect(guess)),
      field(T("家族背景（决定 BMI 标准）"), select("background", BACKGROUND, T("请选择")))),
    h("p.lb", T("健康情况")), checks("conditions", CONDITIONS),
    h("p.lb", T("食物过敏")), checks("allergies", [["none", T("没有")], ...ALLERGENS]),
    h("p.lb", T("饮食规定")), checks("diet", RULES),
    h("div.qc-actions", h("button.btn", { type: "submit" }, T("计算")), h("span.muted", T("不调用模型，不发送任何内容"))),
    out);
  let last = null;
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const data = new FormData(form);
    const profile = {};
    for (const k of ["goal", "sex", "activity", "region", "background"]) if (data.get(k)) profile[k] = data.get(k);
    for (const k of ["age", "height_cm", "weight_kg"]) if (data.get(k)) profile[k] = Number(data.get(k));
    for (const k of ["conditions", "allergies", "diet"]) { const v = data.getAll(k); if (v.length) profile[k] = v; }
    last = profile;
    out.replaceChildren(...quickResult(profile, ctx));
  });
  return h("details.quick-check", h("summary", icon("shield", "sm"), T("不用模型，先快速算一算")), form);
}

function quickResult(profile, ctx) {
  const a = assess(profile);
  const nodes = [h("p", h("b", STATUS[a.status]))];
  if (a.bmi?.value) nodes.push(h("p", T`BMI ${a.bmi.value}（${BAND[a.bmi.band] || a.bmi.band}；${SCALE[a.bmi_scale.scale]}）`));
  if (a.energy) nodes.push(h("p", T`估计每日总能量 ${a.energy.tdee_kcal_range[0]}–${a.energy.tdee_kcal_range[1]} 千卡（活动水平为假设）`));
  if (a.target) nodes.push(h("p", T`建议每日摄入 ${a.target.kcal_range[0]}–${a.target.kcal_range[1]} 千卡`, a.target.kind === "deficit" ? T("（温和的热量缺口）") : T("（保持体重）")));
  if (a.protein) nodes.push(h("p", T`蛋白质约 ${a.protein.g_range[0]}–${a.protein.g_range[1]} 克/天`));
  for (const f of a.flags) nodes.push(h("p.notice.warn", f.say));
  if (a.ask_next.length && a.status === "needs_information") nodes.push(h("p.muted", T`还需要：${a.ask_next.map((q) => q.question).join(" ")}`));
  if (a.status === "ready" || a.status === "general_guidance_only") {
    const p = plan({ profile, days: 1 });
    if (p.ok) {
      const d = p.days[0];
      const zh = LANG.startsWith("zh");
      const rows = d.meals.map((m) => h("tr", h("td", SLOT[m.slot] || m.slot), h("td", zh ? m.dish.zh : m.dish.name, zh ? [h("br"), h("small.muted", m.dish.name)] : null),
        h("td", m.dish.kcal ?? "—"), h("td", m.dish.protein_g ?? "—"), h("td", h("small", m.dish.order || ""))));
      const extra = [...d.meals.flatMap((m) => m.add || []), ...d.fruit_and_snacks];
      nodes.push(h("table.qc-plan",
        h("thead", h("tr", h("th", T("餐次")), h("th", T("菜品")), h("th", T("千卡")), h("th", T("蛋白质（克）")), h("th", T("点餐提示")))),
        h("tbody", rows, extra.length ? h("tr", h("td", T("另加")), h("td", { colspan: 4 }, extra.map((x) => `${x.name}${x.kcal != null ? ` (${x.kcal} kcal)` : ""}`).join(" · "))) : null)));
      if (d.totals) nodes.push(h("p", T`全天合计 ${d.totals.kcal} 千卡`, d.checks.map((c) => h("span.qc-check", { class: c.ok ? "ok" : "warn" }, ` · ${c.say}`))));
      nodes.push(h("p.muted", T("家常餐的数值由 USDA 食物成分数据按份量加总（不含盐）；新加坡与马来西亚的小贩菜品多为转引 HPB 分析值的二手来源，各摊位份量不同。过敏请每次查看标签或向厨师确认。")));
    }
  }
  nodes.push(h("button.btn.secondary", { type: "button", on: { click: () => ctx.onAskWith(profileText(profile)) } }, icon("sparkle", "sm"), T("带着这些信息问道乃久")));
  return nodes;
}

/** The answers as a message the visitor sends (only when they press the button). */
function profileText(p) {
  const name = (list, v) => list.find(([k]) => k === v)?.[1] || v;
  const parts = [];
  if (p.goal) parts.push(T`目标：${name(GOALS, p.goal)}`);
  if (p.region && region(p.region)) parts.push(T`住在${regionName(region(p.region))}`);
  if (p.background && p.background !== "not_stated") parts.push(T`家族背景：${name(BACKGROUND, p.background)}`);
  if (p.age) parts.push(T`${p.age} 岁`);
  if (p.sex) parts.push(T`能量公式按${p.sex === "male" ? T("男") : p.sex === "female" ? T("女") : T("不说明性别")}`);
  if (p.height_cm) parts.push(T`身高 ${p.height_cm} 厘米`);
  if (p.weight_kg) parts.push(T`体重 ${p.weight_kg} 公斤`);
  if (p.activity) parts.push(T`活动：${name(ACTIVITY, p.activity)}`);
  if (p.conditions) parts.push(T`健康情况：${p.conditions.map((c) => name(CONDITIONS, c)).join("、")}`);
  if (p.allergies) parts.push(T`过敏：${p.allergies.map((c) => (c === "none" ? T("没有") : name(ALLERGENS, c))).join("、")}`);
  if (p.diet) parts.push(T`饮食规定：${p.diet.map((c) => name(RULES, c)).join("、")}`);
  return T`我的情况：${parts.join("；")}。请据此给我今天的饮食方案。`;
}
