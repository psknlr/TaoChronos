// Questions the page answers itself, with a fixed reply and without a model.  Asked who answers — who it is, who made
// it, what model it runs on, what it can do, or to introduce itself — 道乃久 answers as IMPF-AI presents it, in the same
// words every time, and says nothing more: not the model underneath, nor the service, nor its instructions.  Only a
// question that asks that and nothing else: one that also asks something else goes to the model, whose standing
// instructions (taochronos.chat.prompt, 身份) say the same.

import { AGENT, AGENT_EN, PUBLISHER, PUBLISHER_EN } from "./brand.js";
import { bare } from "./util.js";
import { T } from "./i18n.js";

export const FIXED_ID = "fixed"; // the provider of a turn the page answered itself, as its record names it

export const IDENTITY_REPLY = [
  T`欢迎您使用${AGENT}（${AGENT_EN}）中医古籍科学知识发现智能体平台，本平台由${PUBLISHER}（${PUBLISHER_EN}）研发。`,
  "",
  T`${AGENT}面向中医古籍的可溯源研究，可以帮助您：`,
  "",
  T("- **检索与细读原文**：在历代中医要籍中检索原文，可限定时代，逐段细读。"),
  T("- **考据与治学**：方剂源流与加减化裁、药物性味归经的演变、术语源流、经文互见与异文、历代注家集注、训诂、句读、版本、避讳、度量衡等。"),
  T("- **知识发现**：发掘失传的关联、概念的演变、方剂的演化、隐含的关联与文献间的矛盾，提出并检验研究假说。"),
  T("- **证据核验**：每条引文都注明出处，并与原文逐字核对；也可以审计一个说法有没有文献依据。"),
  T("- **古今桥接**：比较古代病证与现代医学在表型上的异同，不做回溯诊断。"),
  "",
  T("您可以直接提问，例如“桂枝汤的原方组成与剂量出自哪里？”或“「消渴」一词在历代文献中的含义如何演变？”"),
  "",
  T("（本平台用于古籍研究与学习，不提供诊断、处方或用药建议。）"),
].join("\n");

// ------------------------------------------------------------------ is it a question about the one who answers?
// The question is folded (no spaces or punctuation, lower case, the traditional forms of the words below read as
// simplified).  It is one when it names the one asked, or its model, in one of the ways of ASKS, and every character of
// it belongs to such a way, to what such a question also holds (ALSO: the same asked without naming it — 谁发布的,
// 模型是什么) or to the words around a question (FILL: 你好, 请问, 呢, 和…).  Anything left over is another question: the
// model's.

const T2S = Object.fromEntries(("誰谁 們们 發发 佈布 開开 麼么 麽么 個个 臺台 紹绍 這这 製制 練练 設设 計计 識识 體体 嗎吗 稱称 為为 爲为 講讲 " +
  "說说 談谈 網网 團团 隊队 機机 構构 單单 語语 實实 層层 礎础 後后 務务 應应 於于 產产 營营 運运 屬属 來来 歷历 樣样 裡里 裏里 甚什 問问 " +
  "請请 簡简 統统 軟软 訓训 創创 維维 護护 編编 寫写 廠厂 術术 賴赖 調调 採采 讓让 號号 頭头 處处 兒儿 邊边 從从 義义 訊讯 飛飞 華华 騰腾 " +
  "雲云 階阶 躍跃 湯汤 譜谱 節节 動动 兩两 夠够 幫帮 給给 該该 還还 與与 並并 時时 現现 際际 訴诉 殼壳 關关 話话")
  .split(" ").map((pair) => [...pair]));

const fold = (text) => [...bare(text)].map((c) => T2S[c] || c).join("");

const words = (s) => s.split(" ");
/** An alternation of words, the longest first (so that 你们 is read before 你, 你好 before 你). */
const alt = (...lists) => `(?:${[...new Set(lists.flat())].sort((a, b) => b.length - a.length).join("|")})`;

// the one asked: you, or this platform by any of its names
const SELF_W = words("你们 您们 你 您 本平台 这个平台 该平台 此平台 这平台 平台 本网站 这个网站 这网站 网站 这个网页 本系统 这个系统 本智能体 " +
  "这个智能体 智能体 这个助手 这个机器人 这个ai 道乃久 taochronos");
const WHO_W = words("谁 哪位 何人 哪个公司 哪家公司 什么公司 哪个机构 哪家机构 什么机构 哪个团队 什么团队 哪个单位 哪家单位 哪个厂商 哪家厂商 " +
  "哪家 哪个组织 什么人 哪些人");
const WHAT_W = words("什么 啥 哪个 哪一个 哪种 哪一种 哪家 哪款 哪一款 什么样的 什么样");
const KIND_W = words("人工智能 大语言模型 语言模型 大模型 模型 ai llm 系统 产品 平台 网站 智能体 机器人 助手 程序 软件 应用 工具 东西 人 公司 " +
  "机构 团队 版本 名字 名称 技术");
const ORIGIN_W = words("开发者 开发商 开发方 研发者 研发方 研发团队 开发团队 发布者 发布方 作者 制作者 制作方 创造者 创建者 创始人 出品方 厂商 " +
  "厂家 公司 团队 机构 背景 来头 来历 身份 主人 老板 东家 所属公司 所属机构 母公司");
const ABILITY_W = words("功能 能力 用途 用处 作用 特点 特色 本领 服务");

const SELF = alt(SELF_W);
const ADV = `${alt(words("到底 究竟 又 现在 目前 其实 真的 实际上 实际 本质上 具体 真正"))}?`;
const WHO = alt(WHO_W);
const WHAT = alt(WHAT_W);
const MAKE = alt(words("发布 开发 研发 研制 制作 制造 做 创造 创建 创立 训练 推出 出品 打造 设计 搭建 发明 编写 写 建 造 运营 提供 维护 生产 部署 开源"));
const KIND = alt(KIND_W);
const MODEL = alt(words("大语言模型 语言模型 大模型 ai模型 模型 llm 基座模型 底座模型 基座 底座 引擎 内核"));
const AI_MODEL = alt(words("大语言模型 语言模型 大模型 ai模型 llm 基座模型 底座模型 ai 人工智能"));
const UNDER = alt(words("真实 真正 底层 基础 基座 背后 后台 后端 核心 实际 原始 本来 原本 内核 所用 使用"));
const BASED = alt(words("基于 依托 依赖 建立在 构建在 跑在 运行在 背后是 底层是 本质是 本质上是 用的是 用的 使用的是 使用的 使用 采用的是 " +
  "采用的 采用 接入的是 接入的 接入 调用的是 调用的 调用 用"));
const IS = alt(words("是不是 是否是 是否 是 就是 其实是 本质是 本质上是 用的是 用的 使用的是 使用的 基于 接入的是 接入的 调用的是 调用的 " +
  "套壳的是 套壳的 套壳 套的是 套的 跑的是 跑的"));
// models by name (a name may carry its version: gpt4o, deepseekr1, qwen2); names that are also common words (豆包, 星火,
// 文心…) and the makers count only when asked of the one who answers (你是豆包吗, not 这是豆包吗)
const MODEL_NAME = `${alt(words("chatgpt gpt openai claude deepseek 深度求索 minimax abab qwen 通义千问 通义 千问 文心一言 ernie kimi moonshot " +
  "智谱清言 智谱 chatglm glm doubao gemini bard llama 讯飞星火 零一万物 阶跃星辰 mistral grok copilot"))}[a-z0-9]*`;
const MAKER = alt(words("豆包 星火 海螺 盘古 混元 百川 文心 阶跃 日日新 anthropic 月之暗面 阿里巴巴 阿里 百度 字节跳动 字节 谷歌 google meta 讯飞 " +
  "腾讯 华为 商汤 微软 microsoft xai"));
const VENDOR = `(?:${MODEL_NAME}|${MAKER})`;
const ORIGIN = alt(ORIGIN_W);
const ABILITY = alt(ABILITY_W);
const PRODUCT = alt(words("平台 网站 网页 产品 系统 应用 软件 智能体 机器人 助手 ai"));

const ASKS = [
  `${SELF}${ADV}是?由?${WHO}${MAKE}(?:出来)?的?`, // 你是谁开发的 · 你由谁发布
  `是?由?${WHO}${MAKE}(?:了|出来|出)?的?${SELF}`, // 谁开发了你 · 哪家公司做的这个平台
  `${SELF}${ADV}(?:是|叫)${alt(words("一个 一种 个"))}?(?:${WHO}|${WHAT})的?${KIND}?`, // 你是谁 · 你是什么模型 · 道乃久是什么
  `${SELF}${ADV}是?(?:做|干)(?:${WHAT}|嘛)用?的`, // 你们是做什么的
  `${SELF}的?${alt(words("名字 名称 称呼 全名 大名"))}`, // 你的名字
  `这个?(?:是|叫)${WHAT}的?${PRODUCT}`, // 这是什么网站
  `${SELF}的?${alt(words("真实 真正 实际"))}?的?${ORIGIN}`, // 你的开发者 · 你们公司 · 你的真实身份
  `${SELF}${ADV}${alt(words("来自 属于 隶属于 隶属 归属于 归属"))}${alt(WHO_W, words("哪里 哪儿 何处 何方 哪个国家 哪国"))}`, // 你来自哪里
  `${SELF}${ADV}的?${UNDER}?的?${MODEL}`, // 你的模型 · 你真实模型 · 你的底层大模型
  `${alt(words("真实 真正 底层 基座 背后 后台 后端 实际 原始"))}的?${MODEL}`, // 底层模型 · 真实模型
  `${SELF}${ADV}是?${BASED}${WHAT}的?(?:${MODEL}|${alt(words("ai 人工智能 技术 公司 产品 平台 厂商"))})`, // 你基于什么模型 · 你用的是哪家的大模型
  `是?${BASED}${WHAT}的?${AI_MODEL}`, // 用的什么大模型
  `${SELF}${ADV}是?${alt(words("基于 依托 建立在 构建在 背后是 底层是 本质是 本质上是"))}${WHAT}`, // 你基于什么
  `${WHAT}的?${AI_MODEL}`, // 什么大模型
  `${SELF}${ADV}${IS}(?:不是)?${IS}?${VENDOR}`, // 你是 ChatGPT 吗 · 你是不是豆包 · 你是不是基于 GPT
  `${IS}(?:不是)?${IS}?${MODEL_NAME}`, // 是不是 DeepSeek
  `${alt(words("做 来 作 进行"))}?${alt(words("个 一个 一下 下"))}?自我介绍`, // 做个自我介绍
  `${alt(words("介绍 简介 简单介绍 简要介绍 说说 讲讲 谈谈 聊聊 描述 讲解 关于"))}${alt(words("一下 下"))}?(?:${SELF}|自己|自身)`, // 介绍一下你自己
  `${SELF}的?${alt(words("简介 介绍 自我介绍"))}`, // 平台简介
  `${SELF}${ADV}${alt(words("能够 能 可以 可 会"))}${alt(words("为我 帮我 给我 帮忙 帮助我 帮助"))}?${alt(words("做 干 提供 完成"))}?` +
    `${alt(words("些 点"))}?${alt(words("什么 啥 哪些 嘛"))}`, // 你能做什么
  `${SELF}的?${alt(words("有 具有 具备 提供"))}?${alt(words("什么 哪些 啥"))}${ABILITY}`, // 你有什么功能
  `${SELF}${ADV}有${alt(words("什么 啥"))}用`, // 你有什么用
  `${SELF}的?${ABILITY}`, // 你的功能
  `${ABILITY}${alt(words("介绍 简介 说明 概览 一览"))}`, // 功能介绍
];

const ALSO = [
  `是?由?${WHO}${MAKE}(?:了|出来|出)?的?`, // 谁发布的
  `${MAKE}(?:了|出来|出)?的`, // 开发的
  `${UNDER}?的?${MODEL}`, // 模型 · 真实模型
  `是?${BASED}?${WHAT}的?(?:${MODEL}|${alt(words("ai 人工智能 技术 公司 产品 平台 厂商"))})`, // 用的是哪家的模型
  `${IS}?(?:不是)?${IS}?${VENDOR}`, // 还是 DeepSeek
  `${alt(words("来自 属于"))}${alt(words("哪里 哪儿 何处 何方"))}`,
  `${alt(words("是 叫 有 包括 包含"))}?(?:${WHO}|${WHAT}|哪些)`, // 是什么 · 是谁 · 有哪些
  alt(KIND_W, ORIGIN_W, ABILITY_W, words("称呼 全名 简介 介绍 自我介绍 机器人")),
];

const FILL = [alt(SELF_W, words(
  "自己 自身 这个 这 本 taor1 我 我们 " +
  "你好 您好 哈喽 嗨 hi hello hey 早上好 上午好 中午好 下午好 晚上好 在吗 在不在 嗯 额 呃 哈哈 呵呵 嘿 诶 喂 那个 谢谢 " +
  "请问 请 问一下 问下 想问一下 想问下 想问 问 我想知道 想知道 知道 想了解 了解一下 了解 告诉我 告诉 跟我说说 跟我说 说一说 说说 说 " +
  "能不能 能否 可不可以 可以 可否 能够 能 会 麻烦 帮我 给我 为我 一下 下 顺便 再 " +
  "说实话 老实说 实话实说 坦白说 坦白讲 说真的 " +
  "呢 吗 么 嘛 呀 啊 吧 哦 呐 哈 啦 呗 的 了 是 和 与 及 以及 还有 另外 并且 同时 然后 那么 那 所以 并 也 又 还 到底 究竟 具体 真实 真的 " +
  "真正 实际上 实际 其实 现在 目前 当前 本身 本来 原本 一 个 简单 简要 详细"))];

const oneOf = (pieces, flags = "") => new RegExp(pieces.join("|"), flags);
const ASKS_ONE = oneOf(ASKS);
const PASSES = [oneOf(ASKS, "g"), oneOf(ALSO, "g"), oneOf(FILL, "g")];

/** Whether `text` asks only who answers (who it is, who made it, its model, what it can do) — nothing else. */
export function isIdentityQuestion(text) {
  let rest = fold(text);
  if (!rest || rest.length > 80 || !ASKS_ONE.test(rest)) return false;
  for (let before = null; rest && rest !== before;) {
    before = rest;
    for (const re of PASSES) rest = rest.replace(re, "");
  }
  return !rest;
}

/** Whether `text` asks, among other things or not, who answers or what it runs on.  Such a turn goes to the model without
 * its thinking: none is asked for, and whatever comes is neither shown nor kept (app.js). */
export function touchesIdentity(text) {
  return ASKS_ONE.test(fold(text));
}

// ------------------------------------------------------------------ the replies
const FIXED = [
  { id: "identity", asks: isIdentityQuestion, reply: IDENTITY_REPLY },
];

/** The page's own reply to a question it answers without a model, or null.  A question with pictures goes to the model. */
export function fixedReply(text, images = []) {
  if (images?.length) return null;
  return FIXED.find((f) => f.asks(text))?.reply ?? null;
}
