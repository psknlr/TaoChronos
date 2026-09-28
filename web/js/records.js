// Conversation records for the test period of 道乃久默认服务: one compact record per finished turn, sent to the site's
// relay only after the visitor agreed; the repository collects them (relay/README.md).  The visitor's choice is kept in
// this browser; a new version of the notice asks again.

import { AGENT, PUBLISHER, PUBLISHER_EN } from "./brand.js";
import { storage } from "./util.js";

const KEY = "tc.consent";
const VERSION = 1;

export const NOTICE = [
  `测试期间，${AGENT}会把你的对话——问题、回答、用到的工具和引文核对结果——记录到${PUBLISHER}（${PUBLISHER_EN}）的服务器，只用于测试和改进${AGENT}。`,
  "不记录 API Key、设置和你的网络地址。请不要输入姓名、联系方式、病历等个人信息。",
];

/** true (agreed), false (declined) or null (not asked yet, or asked under an older notice). */
export function consent() {
  const c = storage.get(KEY);
  return c && c.v === VERSION ? Boolean(c.logs) : null;
}

export function setConsent(logs) {
  storage.set(KEY, { v: VERSION, logs: Boolean(logs), at: new Date().toISOString() });
}
