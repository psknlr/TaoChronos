// 我的资料 — the user's own files, read where the user is (the browser's runtime, or a TaoChronos server on this machine),
// made anonymous as they are read, analysed by the model through the 我的资料 tools.  This module holds what the page
// says about it (the notice shown before the first upload), what the model is told of the files a message carries, and
// which conversations touch them (their turns are never recorded).

import { storage } from "./util.js";
import { T } from "./i18n.js";

const KEY = "tc.mydata.notice";
const VERSION = 1;
const LIST = "tc.mydata.list"; // the datasets' summaries, so that the page knows there are some before a runtime answers

export const ACCEPT = ".csv,.tsv,.xlsx,.xlsm,.docx,.txt,.md,.json";
export const MAX_BYTES = 10 * 1024 * 1024;

export const DATA_NOTICE = [
  [T("在本机处理"), T("文件在你的浏览器里读取（若连接的是本机的 TaoChronos 服务，则在本机读取），不上传到道乃久的服务器。")],
  [T("读取时即脱敏"), T("姓名、医生姓名换成化名（P0001、D0001…），身份证号、病历号等换成编号，电话、地址、邮箱删去，出生日期只留年份；")
    + T("文中写出的身份证号、手机号、“姓名：××”等也会替换。自由书写的人名未必都能识别，请先检查原文件。")],
  [T("模型读到什么"), T("模型只读到它调用工具时得到的内容：统计结果，以及它要求阅读的行或段落（已脱敏）。这些内容会随对话发给你所选的模型服务。")
    + T("文件名也会告诉模型，请不要在文件名里写姓名。")],
  [T("不记录"), T("涉及上传资料的对话，不发送任何对话记录。")],
  [T("保存与删除"), T("脱敏后的资料只保存在本浏览器，下次打开仍在；可在侧栏“资料”里随时删除一份或全部。")],
  [T("统计的边界"), T("统计只描述这份数据，不推断因果，也不构成诊疗建议。")],
];

/** Has this browser been shown the notice (its current version)? */
export function noticeSeen() {
  const c = storage.get(KEY);
  return Boolean(c && c.v === VERSION);
}

export function setNoticeSeen() {
  storage.set(KEY, { v: VERSION, at: new Date().toISOString() });
}

/** The datasets the page last heard of (the runtime is the authority: it replaces this as soon as it answers). */
export function cachedList() {
  const v = storage.get(LIST, []);
  return Array.isArray(v) ? v : [];
}

export function cacheList(list) {
  storage.set(LIST, (list || []).map(brief));
}

/** What a message keeps of a dataset it carries (and what the page lists): no rows, only the shape. */
export function brief(d) {
  const out = { id: d.id, name: d.name, kind: d.kind, created: d.created };
  if (d.kind === "table") {
    out.rows = d.rows;
    out.columns = (d.columns || []).slice(0, 60).map((c) => ({ name: c.name, type: c.type }));
  } else {
    out.passages = d.passages;
    out.characters = d.characters;
  }
  if (d.deidentified) out.deidentified = d.deidentified;
  if (d.notes?.length) out.notes = d.notes.slice(0, 4);
  return out;
}

const TYPE_WORDS = { number: T("数值"), date: T("日期"), category: T("分类"), text: T("文本"), prescription: T("处方"), empty: T("空") };

/** A dataset in a few words: 表格 120 行 · 9 列 / 文本 35 段. */
export function sizeLabel(d) {
  return d.kind === "table" ? T`表格 ${d.rows} 行 · ${d.columns?.length || 0} 列` : T`文本 ${d.passages} 段`;
}

export function columnsLabel(d, max = 12) {
  const cols = (d.columns || []).filter((c) => c.type !== "empty");
  const shown = cols.slice(0, max).map((c) => T`${c.name}（${TYPE_WORDS[c.type] || c.type}）`).join(T("、"));
  return shown + (cols.length > max ? T` 等 ${cols.length} 列` : "");
}

/** What was taken out, in a line: 姓名→化名；手机已删除；文中手机号 3 处. */
export function deidLabel(d) {
  const r = d.deidentified || {};
  const parts = Object.entries(r.columns || {}).map(([c, what]) => `${c}${what.startsWith("以") ? "：" : ""}${what}`);
  for (const [kind, n] of Object.entries(r.masked || {})) parts.push(T`文中${kind} ${n} 处`);
  return parts.length ? parts.join(T("；")) : T("未发现需要去除的个人信息（自由书写的人名未必能识别）");
}

/** What the model reads with a user message that carries datasets (the page shows chips instead). */
export function dataNote(data) {
  if (!data?.length) return "";
  const each = data.map((d) => `${d.id}「${d.name}」，${d.kind === "table" ? `表格 ${d.rows} 行；列：${columnsLabel(d, 30)}` : `文本 ${d.passages} 段`}`);
  return `\n\n［本条消息附有用户上传的资料（已在本机脱敏）：${each.join("；")}。用“我的资料”工具（mydata.*）读取和分析，`
    + "引用其中的行或段落时写 [[mine:…]]；统计只描述这份数据，不作诊疗建议。］";
}

/** A tool of 我的资料, by the name the model calls it (mydata__describe) or the catalog's (mydata.describe). */
export const isMine = (name) => /^mydata(?:__|\.)/.test(String(name || ""));

/** Does this conversation touch the user's data — a message that carried some, or a 我的资料 tool called? */
export function personal(conv) {
  return Boolean(conv?.messages?.some((m) => m.data?.length
    || (m.segments || []).some((s) => (s.calls || []).some((c) => isMine(c.resolved || c.name) || (c.name === "taochronos_call" && isMine(c.args?.tool)))))); // a call made through the catalog
}
