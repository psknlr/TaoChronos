// 道乃久 · 控制台 — the console's page.  It holds no token: the session is an HttpOnly cookie the console Worker sets
// (rust/platform/console), and every change is a same-origin JSON request.  Passkeys through navigator.credentials,
// with their options and results converted here (not every browser the console's readers use has toJSON()).  Text is
// put into the page as text, never as HTML.
"use strict";

const T = {
  zh: {
    brand: "道乃久 · 控制台", signout: "退出", foot: "道乃久 · 医哲未来人工智能研究院（IMPF-AI）", chat: "研究助手",
    signin: "登录", register: "注册", passkey_signin: "用通行密钥登录", or_email: "或用邮箱验证码", email: "邮箱",
    send_code: "发送验证码", code_sent: "验证码已发送到 {email}（10 分钟内有效）。没收到？看看垃圾邮件，或稍后重新发送。",
    code: "验证码（8 位数字）", verify: "确认", resend: "重新发送", resend_in: "{s} 秒后可重新发送", back: "返回",
    closed: "目前不开放注册。", make_passkey: "创建通行密钥", skip_passkey: "暂不创建，用邮箱登录",
    passkey_why: "通行密钥存在你的设备或密码管理器里，用指纹、面容或设备密码确认，无法被钓鱼网站骗走。之后创建 API 正式密钥、删除密钥等操作需要它。",
    recovery_title: "恢复码", recovery_why: "每个恢复码只能用一次。丢失通行密钥时，用邮箱验证码加一个恢复码登录。请现在保存，之后不会再显示。",
    saved: "我已保存", second_title: "这个账户受通行密钥保护", second_why: "只凭邮箱不能登录。请输入一个恢复码，或返回用通行密钥登录。",
    recovery_code: "恢复码", overview: "概览", keys: "API 密钥", usage: "用量", security: "安全",
    org: "组织", org_id: "组织编号：{id}（申请额度或联系我们时请提供）", credits: "可用额度", held: "进行中占用", today: "今天", calls: "调用", spent: "消耗",
    new_key: "新建密钥", key_name: "名称", environment: "环境", live: "正式（消耗额度）", test: "测试（每天少量免费调用）",
    scopes: "权限", create: "创建", key_once: "这是密钥唯一一次显示。请保存在服务器的密钥管理中，不要放进网页或代码仓库。",
    copy: "复制", copied: "已复制", revoke: "撤销", revoked: "已撤销", never: "从未", name: "名称", shown: "密钥",
    created: "创建", last_used: "最近使用", status: "状态", active: "有效", no_keys: "还没有密钥。",
    day: "日期", product: "产品", env: "环境", failed: "失败", refused: "被拒", no_usage: "这段时间没有调用。",
    passkeys: "通行密钥", add_passkey: "添加通行密钥", remove: "删除", synced: "已同步", device_bound: "仅本设备",
    recovery_left: "剩余恢复码：{n} 个", renew: "重新生成恢复码", sessions: "已登录的设备", this_device: "本设备",
    end: "退出", end_others: "退出其他所有设备", change_email: "更改邮箱", new_email: "新邮箱", events: "最近的安全记录",
    no_passkey_yet: "账户还没有通行密钥：只凭邮箱就能登录。添加一个，账户会更安全，也才能创建正式密钥。",
    stepup_needed: "这一步需要用通行密钥确认。", confirm_passkey: "用通行密钥确认", unsupported: "这个浏览器不支持通行密钥。",
    done: "完成", email_changed: "邮箱已更改。", saved_ok: "已保存。",
    ev_registered: "注册", ev_signed_in: "登录", ev_passkey_added: "添加通行密钥", ev_passkey_removed: "删除通行密钥",
    ev_recovery_used: "用恢复码登录", ev_recovery_renewed: "重新生成恢复码", ev_email_changed: "更改邮箱",
    ev_session_ended: "退出一个设备", ev_sessions_ended: "退出其他设备",
    e_email: "这不是有效的邮箱地址（域名请用 ASCII，如 xn--…）。", e_code: "验证码不对，还可以试 {left} 次。",
    e_attempts: "错误次数太多，请重新开始。", e_expired: "验证码已过期，请重新发送。", e_flow: "这个验证已失效，请重新开始。",
    e_cooldown: "请稍后再重新发送。", e_sends: "这次验证发送的邮件已达上限，请重新开始。", e_address: "这个邮箱收到的邮件太多，请稍后再试。",
    e_network: "这个网络的请求太多，请稍后再试。", e_service: "今天的验证邮件已达上限，请明天再试。", e_closed: "目前不开放注册。",
    e_grant: "这一步已失效，请重新开始。", e_taken: "这个邮箱已被另一个账户使用。", e_recovery: "恢复码不对，或已用过。",
    e_session: "请先登录。", e_stepup: "需要用通行密钥确认。", e_no_passkey: "需要先给账户添加通行密钥。", e_fresh: "请先重新登录，再添加第一个通行密钥。",
    e_same: "这就是现在的邮箱。", e_turnstile: "人机验证没有通过，请重试。", e_origin: "请求来源不对。", e_unavailable: "服务暂时不可用，请稍后再试。",
    e_credits: "额度不足。", e_passkey: "通行密钥验证失败（{r}）。", e_cancelled: "已取消。", e_other: "出错了（{r}）。",
    e_account: "这个账户更改邮箱的次数太多，请稍后再试。", e_scope: "请至少选择一项权限。", e_role: "你在这个组织里没有这个权限。",
    e_limit: "月度上限须是整数。", e_expires: "有效期须是 1 到 3650 天。",
  },
  en: {
    brand: "TaoChronos · Console", signout: "Sign out", foot: "TaoChronos · IMPF-AI", chat: "Research assistant",
    signin: "Sign in", register: "Register", passkey_signin: "Sign in with a passkey", or_email: "or with an email code", email: "Email",
    send_code: "Send code", code_sent: "A code was sent to {email} (valid for 10 minutes). Nothing? Check your spam folder, or resend in a moment.",
    code: "Code (8 digits)", verify: "Confirm", resend: "Resend", resend_in: "Resend in {s} s", back: "Back",
    closed: "Registration is closed for now.", make_passkey: "Create a passkey", skip_passkey: "Not now: sign in by email",
    passkey_why: "A passkey stays on your device or in your password manager, is confirmed with your fingerprint, face or device PIN, and cannot be phished. Creating live API keys and removing keys need one.",
    recovery_title: "Recovery codes", recovery_why: "Each code works once. If you lose your passkey, sign in with an email code and one of these. Save them now: they are not shown again.",
    saved: "I have saved them", second_title: "A passkey guards this account", second_why: "Your mailbox alone does not open it. Enter a recovery code, or go back and sign in with your passkey.",
    recovery_code: "Recovery code", overview: "Overview", keys: "API keys", usage: "Usage", security: "Security",
    org: "Organisation", org_id: "Organisation id: {id} (quote it when you ask for credits or write to us)", credits: "Available credits", held: "Held in flight", today: "Today", calls: "Calls", spent: "Spent",
    new_key: "New key", key_name: "Name", environment: "Environment", live: "Live (spends credits)", test: "Test (a few free calls a day)",
    scopes: "Scopes", create: "Create", key_once: "This is the only time the key is shown. Keep it in your server's secret store — never in a web page or a repository.",
    copy: "Copy", copied: "Copied", revoke: "Revoke", revoked: "Revoked", never: "never", name: "Name", shown: "Key",
    created: "Created", last_used: "Last used", status: "Status", active: "Active", no_keys: "No keys yet.",
    day: "Day", product: "Product", env: "Env", failed: "Failed", refused: "Refused", no_usage: "No calls in this period.",
    passkeys: "Passkeys", add_passkey: "Add a passkey", remove: "Remove", synced: "synced", device_bound: "this device only",
    recovery_left: "Recovery codes left: {n}", renew: "New recovery codes", sessions: "Signed-in devices", this_device: "this device",
    end: "Sign out", end_others: "Sign out all other devices", change_email: "Change email", new_email: "New email", events: "Recent security events",
    no_passkey_yet: "This account has no passkey: its mailbox alone opens it. Add one to make it safer — and to create live keys.",
    stepup_needed: "This step needs your passkey.", confirm_passkey: "Confirm with a passkey", unsupported: "This browser does not support passkeys.",
    done: "Done", email_changed: "Email changed.", saved_ok: "Saved.",
    ev_registered: "Registered", ev_signed_in: "Signed in", ev_passkey_added: "Passkey added", ev_passkey_removed: "Passkey removed",
    ev_recovery_used: "Recovery code used", ev_recovery_renewed: "Recovery codes renewed", ev_email_changed: "Email changed",
    ev_session_ended: "A device signed out", ev_sessions_ended: "Other devices signed out",
    e_email: "Not a valid email address (write the domain in ASCII, e.g. xn--…).", e_code: "Wrong code; {left} attempts left.",
    e_attempts: "Too many wrong codes: please start again.", e_expired: "The code has expired: resend it.", e_flow: "This verification is over: please start again.",
    e_cooldown: "Please wait a moment before resending.", e_sends: "This verification sent all the mail it may: please start again.", e_address: "Too much mail to this address: try later.",
    e_network: "Too many requests from this network: try later.", e_service: "Today's verification mail is spent: try tomorrow.", e_closed: "Registration is closed for now.",
    e_grant: "This step has expired: please start again.", e_taken: "Another account uses this address.", e_recovery: "Wrong or used recovery code.",
    e_session: "Please sign in.", e_stepup: "Confirm with your passkey.", e_no_passkey: "Add a passkey to the account first.", e_fresh: "Sign in again before adding your first passkey.",
    e_same: "That is the current address.", e_turnstile: "The human check failed: please retry.", e_origin: "Wrong origin.", e_unavailable: "The service is unavailable: try later.",
    e_credits: "Not enough credits.", e_passkey: "The passkey was not accepted ({r}).", e_cancelled: "Cancelled.", e_other: "Something went wrong ({r}).",
    e_account: "Too many address changes for this account: try later.", e_scope: "Choose at least one scope.", e_role: "Your role in this organisation does not allow this.",
    e_limit: "A monthly limit is a whole number.", e_expires: "Expiry is 1 to 3650 days.",
  },
};

let lang = (() => {
  try { const saved = localStorage.getItem("tc.console.lang"); if (saved === "zh" || saved === "en") return saved; } catch { /* storage off */ }
  return /^zh/i.test(navigator.language || "zh") ? "zh" : "en";
})();
const t = (k, vars = {}) => String(T[lang][k] ?? T.zh[k] ?? k).replace(/\{(\w+)\}/g, (_, v) => String(vars[v] ?? ""));

// ------------------------------------------------------------------ the DOM, as text
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of children.flat()) if (c !== null && c !== undefined && c !== false) el.append(c instanceof Node ? c : String(c));
  return el;
}
const app = document.getElementById("app");
const show = (...nodes) => app.replaceChildren(...nodes);
const msg = (kind, text) => h("p", { class: `msg ${kind}`, role: kind === "error" ? "alert" : "status" }, text);

function errorText(r) {
  const reason = r?.error || "other";
  if (reason.startsWith("passkey")) return t("e_passkey", { r: reason });
  if (`e_${reason}` in T[lang]) return t(`e_${reason}`, { left: r.left ?? "" });
  return t("e_other", { r: reason });
}

// ------------------------------------------------------------------ the server
async function api(method, path, body) {
  try {
    const res = await fetch(path, { method, credentials: "same-origin", headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined });
    const data = await res.json().catch(() => ({}));
    return { status: res.status, ok: res.ok, ...data };
  } catch {
    return { status: 0, ok: false, error: "unavailable" };
  }
}

// ------------------------------------------------------------------ passkeys
const b64u = {
  enc(buf) {
    const bytes = new Uint8Array(buf);
    let s = "";
    for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  },
  dec(text) {
    const s = String(text).replace(/-/g, "+").replace(/_/g, "/");
    const bin = atob(s + "===".slice((s.length + 3) % 4));
    return Uint8Array.from(bin, (c) => c.charCodeAt(0)).buffer;
  },
};
const passkeysWork = () => typeof window.PublicKeyCredential === "function" && !!navigator.credentials;
const ids = (list) => (list || []).map((c) => ({ ...c, id: b64u.dec(c.id) }));

function credentialJSON(cred) {
  const r = cred.response;
  const out = { id: cred.id, rawId: b64u.enc(cred.rawId), type: cred.type, authenticatorAttachment: cred.authenticatorAttachment || null,
    response: { clientDataJSON: b64u.enc(r.clientDataJSON) }, clientExtensionResults: cred.getClientExtensionResults?.() || {} };
  if (r.attestationObject) {
    out.response.attestationObject = b64u.enc(r.attestationObject);
    out.response.transports = typeof r.getTransports === "function" ? r.getTransports() : [];
  } else {
    out.response.authenticatorData = b64u.enc(r.authenticatorData);
    out.response.signature = b64u.enc(r.signature);
    out.response.userHandle = r.userHandle ? b64u.enc(r.userHandle) : null;
  }
  return out;
}

async function createPasskey(pk) {
  const publicKey = { ...pk, challenge: b64u.dec(pk.challenge), user: { ...pk.user, id: b64u.dec(pk.user.id) }, excludeCredentials: ids(pk.excludeCredentials) };
  return credentialJSON(await navigator.credentials.create({ publicKey }));
}

async function getPasskey(pk) {
  const publicKey = { ...pk, challenge: b64u.dec(pk.challenge), allowCredentials: ids(pk.allowCredentials) };
  return credentialJSON(await navigator.credentials.get({ publicKey }));
}

/** A passkey's touch on this session (a step-up): the session is strong for five minutes after it. */
async function touch() {
  const o = await api("POST", "/auth/stepup/options", {});
  if (!o.ok) return o;
  let credential;
  try { credential = await getPasskey(o.publicKey); } catch { return { ok: false, error: "cancelled" }; }
  return api("POST", "/auth/stepup/verify", { credential });
}

/** A step that may need a passkey's touch: asked once more after one.  (Not for a step that carries a Turnstile token,
 * which is good once: such a step asks for the touch first.) */
async function withTouch(step) {
  let r = await step();
  if (r.status === 403 && r.error === "stepup") {
    const v = await touch();
    if (!v.ok) return v;
    r = await step();
  }
  return r;
}

// ------------------------------------------------------------------ Turnstile, when the console has it
let config = { registration: "off", turnstile: null };
let turnstileReady = null;
function loadTurnstile() {
  if (!config.turnstile) return Promise.resolve(null);
  turnstileReady ||= new Promise((resolve) => {
    const s = h("script", { src: "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit", async: true });
    s.addEventListener("load", () => resolve(window.turnstile || null));
    s.addEventListener("error", () => resolve(null));
    document.head.append(s);
  });
  return turnstileReady;
}
async function widget(box, action) {
  const ts = await loadTurnstile();
  if (!ts) return () => "";
  const id = ts.render(box, { sitekey: config.turnstile, action, language: lang === "zh" ? "zh-cn" : "en" });
  return () => ts.getResponse(id) || "";
}

// ------------------------------------------------------------------ signed out
function signedOut(tab = "signin", note = null) {
  setWho(null);
  const tabs = h("div", { class: "tabs", role: "tablist" },
    h("button", { type: "button", role: "tab", "aria-selected": tab === "signin", onclick: () => signedOut("signin") }, t("signin")),
    h("button", { type: "button", role: "tab", "aria-selected": tab === "register", onclick: () => signedOut("register") }, t("register")));
  const body = h("div", { class: "stack" });
  if (tab === "signin" && passkeysWork()) {
    const out = h("div");
    body.append(h("button", { type: "button", class: "primary wide", onclick: async () => {
      const o = await api("POST", "/auth/passkey/options", {});
      if (!o.ok) return out.replaceChildren(msg("error", errorText(o)));
      let credential;
      try { credential = await getPasskey(o.publicKey); } catch { return out.replaceChildren(msg("error", t("e_cancelled"))); }
      const v = await api("POST", "/auth/passkey/verify", { credential });
      if (!v.ok) return out.replaceChildren(msg("error", errorText(v)));
      boot();
    } }, t("passkey_signin")), out, h("div", { class: "or" }, t("or_email")));
  }
  if (tab === "register" && config.registration !== "open") body.append(msg("warn", t("closed")));
  else body.append(emailForm(tab === "register" ? "register" : "signin"));
  show(h("section", { class: "card narrow" }, tabs, note, body));
}

function emailForm(purpose) {
  const input = h("input", { type: "email", id: "email", autocomplete: "email webauthn", required: true, inputmode: "email" });
  const box = h("div");
  const out = h("div");
  let token = () => "";
  widget(box, purpose).then((get) => { token = get; });
  const form = h("form", { class: "stack", onsubmit: async (e) => {
    e.preventDefault();
    const button = form.querySelector("button");
    button.disabled = true;
    const r = await api("POST", `/auth/${purpose}/start`, { email: input.value, locale: lang, turnstile: token() });
    button.disabled = false;
    if (!r.ok) return out.replaceChildren(msg("error", errorText(r)));
    codeForm(purpose, r.flow, input.value.trim(), r.resend);
  } }, h("label", { for: "email" }, t("email")), input, box, h("button", { type: "submit", class: "primary wide" }, t("send_code")), out);
  return form;
}

function codeForm(purpose, flow, email, resendAt, onDone = null) {
  const input = h("input", { type: "text", id: "code", class: "code", inputmode: "numeric", autocomplete: "one-time-code", maxlength: 9, required: true });
  const out = h("div");
  const resend = h("button", { type: "button", class: "link" }, t("resend"));
  let until = resendAt;
  const tick = () => {
    const s = Math.ceil((until - Date.now()) / 1000);
    resend.disabled = s > 0;
    resend.textContent = s > 0 ? t("resend_in", { s }) : t("resend");
  };
  const timer = setInterval(() => { if (!document.body.contains(resend)) clearInterval(timer); else tick(); }, 1000);
  tick();
  resend.addEventListener("click", async () => {
    const r = await api("POST", "/auth/flow/resend", { flow });
    if (!r.ok) return out.replaceChildren(msg("error", errorText(r)));
    until = r.resend;
    tick();
    out.replaceChildren(msg("ok", t("code_sent", { email })));
  });
  const form = h("form", { class: "stack", onsubmit: async (e) => {
    e.preventDefault();
    const r = await api("POST", "/auth/flow/verify", { flow, code: input.value });
    if (!r.ok) return out.replaceChildren(msg("error", errorText(r)));
    clearInterval(timer);
    if (onDone) return onDone(r);
    if (r.next === "enroll") return enroll(r.grant);
    if (r.next === "second") return second(r.grant);
    boot();
  } }, msg("ok", t("code_sent", { email })), h("label", { for: "code" }, t("code")), input,
  h("div", { class: "row" }, h("button", { type: "submit", class: "primary" }, t("verify")), resend,
    h("button", { type: "button", class: "link", onclick: () => (onDone ? boot() : signedOut(purpose)) }, t("back"))), out);
  show(h("section", { class: "card narrow" }, form));
  input.focus();
}

function enroll(grant) {
  const out = h("div");
  const make = async () => {
    const o = await api("POST", "/auth/register/options", { grant });
    if (!o.ok) return out.replaceChildren(msg("error", errorText(o)));
    let credential;
    try { credential = await createPasskey(o.publicKey); } catch { return out.replaceChildren(msg("error", t("e_cancelled"))); }
    const r = await api("POST", "/auth/register/complete", { grant, credential, name: deviceName() });
    if (!r.ok) return out.replaceChildren(msg("error", errorText(r)));
    recoveryCodes(r.recovery, boot);
  };
  const skip = async () => {
    const r = await api("POST", "/auth/register/complete", { grant, credential: null });
    if (!r.ok) return out.replaceChildren(msg("error", errorText(r)));
    boot();
  };
  show(h("section", { class: "card narrow stack" }, h("h2", {}, t("make_passkey")), h("p", { class: "muted" }, t("passkey_why")),
    passkeysWork() ? h("button", { type: "button", class: "primary wide", onclick: make }, t("make_passkey")) : msg("warn", t("unsupported")),
    h("button", { type: "button", class: "wide", onclick: skip }, t("skip_passkey")), out));
}

function second(grant) {
  const input = h("input", { type: "text", id: "recovery", autocomplete: "off", spellcheck: "false", required: true });
  const out = h("div");
  show(h("section", { class: "card narrow" }, h("form", { class: "stack", onsubmit: async (e) => {
    e.preventDefault();
    const r = await api("POST", "/auth/second", { grant, recovery: input.value });
    if (!r.ok) return out.replaceChildren(msg("error", errorText(r)));
    boot();
  } }, h("h2", {}, t("second_title")), h("p", { class: "muted" }, t("second_why")), h("label", { for: "recovery" }, t("recovery_code")), input,
  h("div", { class: "row" }, h("button", { type: "submit", class: "primary" }, t("verify")), h("button", { type: "button", class: "link", onclick: () => signedOut() }, t("back"))), out)));
}

function recoveryCodes(codes, then) {
  if (!codes || !codes.length) return then();
  show(h("section", { class: "card narrow stack" }, h("h2", {}, t("recovery_title")), h("p", { class: "muted" }, t("recovery_why")),
    h("div", { class: "codes" }, codes.map((c) => h("span", {}, c))),
    h("div", { class: "row" }, h("button", { type: "button", onclick: () => copy(codes.join("\n")) }, t("copy")),
      h("button", { type: "button", class: "primary", onclick: then }, t("saved")))));
}

function deviceName() {
  const ua = navigator.userAgent;
  const os = /iPhone|iPad/.test(ua) ? "iOS" : /Android/.test(ua) ? "Android" : /Mac/.test(ua) ? "Mac" : /Windows/.test(ua) ? "Windows" : /Linux/.test(ua) ? "Linux" : "";
  return os ? `${os} · ${new Date().toISOString().slice(0, 10)}` : new Date().toISOString().slice(0, 10);
}

async function copy(text) {
  try { await navigator.clipboard.writeText(text); } catch { /* the text stays selectable */ }
}

const when = (ms) => (ms ? new Date(ms).toLocaleString(lang === "zh" ? "zh-CN" : "en-GB", { dateStyle: "medium", timeStyle: "short" }) : t("never"));

// ------------------------------------------------------------------ signed in
function setWho(me) {
  const who = document.getElementById("who");
  const out = document.getElementById("signout");
  who.hidden = out.hidden = !me;
  who.textContent = me ? me.user.address : "";
}

let state = { me: null, org: null, tab: "overview" };
let renders = 0;

async function dashboard(me, tab = state.tab) {
  // a render a later one overtook (a second tab clicked before the first answered) shows nothing
  const render = ++renders;
  state = { ...state, me, tab };
  setWho(me);
  const orgId = me.orgs[0]?.id;
  const org = orgId ? await api("GET", `/console/org?org=${encodeURIComponent(orgId)}`) : null;
  if (render !== renders) return;
  state.org = org?.ok ? org : null;
  const tabs = h("div", { class: "tabs", role: "tablist" }, ["overview", "keys", "usage", "security"].map((k) =>
    h("button", { type: "button", role: "tab", "aria-selected": tab === k, onclick: () => dashboard(state.me, k) }, t(k))));
  const panel = h("div");
  show(tabs, panel);
  const views = { overview, keys, usage, security };
  await views[tab](panel, me, orgId);
}

function overview(panel, me) {
  const o = state.org;
  const today = (o?.today || []).reduce((a, d) => ({ calls: a.calls + d.calls, credits: a.credits + d.credits }), { calls: 0, credits: 0 });
  panel.append(
    me.passkeys.length ? null : msg("warn", t("no_passkey_yet")),
    h("section", { class: "card" }, h("h2", {}, `${t("org")} · ${o?.org?.name ?? "—"}`),
      o?.org?.id ? h("p", { class: "muted small", id: "org-id" }, t("org_id", { id: o.org.id })) : null, o ? h("div", { class: "stats" },
      h("div", { class: "stat" }, t("credits"), h("b", {}, String(o.credits.available))),
      h("div", { class: "stat" }, t("held"), h("b", {}, String(o.credits.held))),
      h("div", { class: "stat" }, `${t("today")} · ${t("calls")}`, h("b", {}, String(today.calls))),
      h("div", { class: "stat" }, `${t("today")} · ${t("spent")}`, h("b", {}, String(today.credits)))) : msg("warn", t("e_unavailable"))));
}

function keys(panel, me, orgId) {
  const o = state.org;
  const out = h("div");
  const name = h("input", { type: "text", id: "key-name", maxlength: 64, required: true, value: "server" });
  const env = h("select", { id: "key-env" }, h("option", { value: "test" }, t("test")), h("option", { value: "live" }, t("live")));
  const scopes = ["evidence:search", "citations:verify", "usage:read"].map((s) => h("label", { class: "row small" },
    h("input", { type: "checkbox", value: s, checked: true }), s));
  const form = h("form", { class: "stack", onsubmit: async (e) => {
    e.preventDefault();
    const chosen = scopes.map((l) => l.querySelector("input")).filter((i) => i.checked).map((i) => i.value);
    const r = await withTouch(() => api("POST", "/console/keys", { org: orgId, environment: env.value, name: name.value, scopes: chosen }));
    if (!r.ok) return out.replaceChildren(msg("error", errorText(r)));
    out.replaceChildren(msg("warn", t("key_once")), h("p", { class: "secret" }, r.key), h("button", { type: "button", onclick: () => copy(r.key) }, t("copy")));
    const fresh = await api("GET", `/console/org?org=${encodeURIComponent(orgId)}`);
    if (fresh.ok) { state.org = fresh; list.replaceChildren(keyTable(orgId)); }
  } }, h("h2", {}, t("new_key")), h("label", { for: "key-name" }, t("key_name")), name, h("label", { for: "key-env" }, t("environment")), env,
  h("div", {}, h("label", {}, t("scopes")), scopes), h("button", { type: "submit", class: "primary" }, t("create")), out);
  const list = h("div", {}, keyTable(orgId));
  panel.append(h("section", { class: "card" }, form), h("section", { class: "card" }, h("h2", {}, t("keys")), o ? list : msg("warn", t("e_unavailable"))));
}

function keyTable(orgId) {
  const all = state.org?.keys || [];
  if (!all.length) return h("p", { class: "muted" }, t("no_keys"));
  return h("div", { class: "scroll" }, h("table", {}, h("thead", {}, h("tr", {}, [t("name"), t("shown"), t("env"), t("last_used"), t("status"), ""].map((x) => h("th", {}, x)))),
    h("tbody", {}, all.map((k) => h("tr", {},
      h("td", {}, k.name), h("td", {}, h("code", {}, k.shown)), h("td", {}, h("span", { class: `tag ${k.environment}` }, k.environment)),
      h("td", { class: "small" }, when(k.last_used)), h("td", {}, k.revoked ? h("span", { class: "tag off" }, t("revoked")) : t("active")),
      h("td", {}, k.revoked ? null : h("button", { type: "button", class: "danger", onclick: async () => {
        const r = await withTouch(() => api("POST", "/console/keys/revoke", { org: orgId, id: k.id }));
        if (r.ok) dashboard(state.me, "keys");
        else alert(errorText(r));
      } }, t("revoke"))))))));
}

async function usage(panel, me, orgId) {
  const r = await api("GET", `/console/usage?org=${encodeURIComponent(orgId)}`);
  const rows = r.ok ? r.data : [];
  panel.append(h("section", { class: "card" }, h("h2", {}, t("usage")), !r.ok ? msg("error", errorText(r)) : !rows.length ? h("p", { class: "muted" }, t("no_usage")) :
    h("div", { class: "scroll" }, h("table", {}, h("thead", {}, h("tr", {}, [t("day"), t("product"), t("env"), t("calls"), t("spent"), t("failed"), t("refused")]
      .map((x, i) => h("th", { class: i > 2 ? "num" : "" }, x)))),
    h("tbody", {}, rows.slice().reverse().map((d) => h("tr", {}, h("td", {}, d.day), h("td", {}, d.product), h("td", {}, d.environment),
      ...[d.calls, d.credits, d.failed, d.refused].map((n) => h("td", { class: "num" }, String(n))))))))));
}

async function security(panel, me) {
  const out = h("div");
  const addPasskey = async () => {
    const o = await withTouch(() => api("POST", "/account/passkeys/options", {}));
    if (!o.ok) return out.replaceChildren(msg("error", errorText(o)));
    let credential;
    try { credential = await createPasskey(o.publicKey); } catch { return out.replaceChildren(msg("error", t("e_cancelled"))); }
    const r = await api("POST", "/account/passkeys", { credential, name: deviceName() });
    if (!r.ok) return out.replaceChildren(msg("error", errorText(r)));
    const fresh = await api("GET", "/account");
    recoveryCodes(r.recovery, () => dashboard(fresh, "security"));
  };
  const passkeyRows = me.passkeys.map((p) => h("tr", {}, h("td", {}, p.name), h("td", { class: "small" }, p.synced ? t("synced") : t("device_bound")),
    h("td", { class: "small hide-narrow" }, when(p.last_used)),
    h("td", {}, h("button", { type: "button", class: "danger", onclick: async () => {
      const r = await withTouch(() => api("POST", "/account/passkeys/remove", { id: p.id }));
      if (!r.ok) return out.replaceChildren(msg("error", errorText(r)));
      dashboard(await api("GET", "/account"), "security");
    } }, t("remove")))));
  const sessionRows = me.sessions.map((s) => h("tr", {}, h("td", {}, s.device || "—", s.current ? h("span", { class: "tag" }, ` ${t("this_device")}`) : null),
    h("td", { class: "small" }, s.place), h("td", { class: "small hide-narrow" }, when(s.seen)),
    h("td", {}, s.current ? null : h("button", { type: "button", onclick: async () => {
      await api("POST", "/account/sessions/end", { id: s.id });
      dashboard(await api("GET", "/account"), "security");
    } }, t("end")))));
  const email = h("input", { type: "email", id: "new-email", required: true });
  const box = h("div");
  let token = () => "";
  widget(box, "email_change").then((get) => { token = get; });
  const emailForm = h("form", { class: "stack", onsubmit: async (e) => {
    e.preventDefault();
    // the touch first, where a passkey guards the account: the request then goes once, with its one Turnstile token
    if (me.passkeys.length && !(me.session.strong_until > Date.now() + 10000)) {
      const v = await touch();
      if (!v.ok) return out.replaceChildren(msg("error", errorText(v)));
    }
    const r = await api("POST", "/account/email/start", { email: email.value, locale: lang, turnstile: token() });
    if (!r.ok) return out.replaceChildren(msg("error", errorText(r)));
    codeForm("email_change", r.flow, email.value.trim(), r.resend, async () => dashboard(await api("GET", "/account"), "security"));
  } }, h("label", { for: "new-email" }, t("new_email")), email, box, h("button", { type: "submit" }, t("change_email")));
  const events = await api("GET", "/account/events");
  panel.append(
    h("section", { class: "card" }, h("h2", {}, t("passkeys")), me.passkeys.length ? h("table", {}, h("tbody", {}, passkeyRows)) : msg("warn", t("no_passkey_yet")),
      h("div", { class: "row" }, passkeysWork() ? h("button", { type: "button", class: "primary", onclick: addPasskey }, t("add_passkey")) : msg("warn", t("unsupported")),
        me.passkeys.length ? h("button", { type: "button", onclick: async () => {
          const r = await withTouch(() => api("POST", "/account/recovery/renew", {}));
          if (!r.ok) return out.replaceChildren(msg("error", errorText(r)));
          recoveryCodes(r.recovery, () => dashboard(state.me, "security"));
        } }, t("renew")) : null),
      me.passkeys.length ? h("p", { class: "muted small" }, t("recovery_left", { n: me.recovery_left })) : null, out),
    h("section", { class: "card" }, h("h2", {}, t("sessions")), h("div", { class: "scroll" }, h("table", {}, h("tbody", {}, sessionRows))),
      me.sessions.length > 1 ? h("button", { type: "button", onclick: async () => {
        await api("POST", "/account/sessions/end-others", {});
        dashboard(await api("GET", "/account"), "security");
      } }, t("end_others")) : null),
    h("section", { class: "card" }, h("h2", {}, t("change_email")), h("p", { class: "muted small" }, me.user.address), emailForm),
    h("section", { class: "card" }, h("h2", {}, t("events")), h("table", {}, h("tbody", {}, (events.ok ? events.events || [] : [])
      .map((e) => h("tr", {}, h("td", { class: "small" }, when(e.ts)), h("td", {}, t(`ev_${e.kind}`))))))));
}

// ------------------------------------------------------------------ start
async function boot() {
  document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
  for (const el of document.querySelectorAll("[data-t]")) el.textContent = t(el.dataset.t);
  document.getElementById("lang").textContent = lang === "zh" ? "EN" : "中文";
  const c = await api("GET", "/auth/config");
  if (c.ok) config = c;
  const me = await api("GET", "/account");
  if (me.status === 200) return dashboard(me);
  if (me.status === 401 || me.status === 403) return signedOut();
  show(h("section", { class: "card narrow" }, msg("error", errorText(me))));
}

document.getElementById("lang").addEventListener("click", () => {
  lang = lang === "zh" ? "en" : "zh";
  try { localStorage.setItem("tc.console.lang", lang); } catch { /* storage off */ }
  boot();
});
document.getElementById("signout").addEventListener("click", async () => {
  await api("POST", "/auth/signout", {});
  state = { me: null, org: null, tab: "overview" };
  signedOut();
});
boot();
