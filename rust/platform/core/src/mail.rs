//! 账户 · 邮件 — the mails the console sends, and how they leave: written into the identity object's outbox in the step
//! that decided them (`identity`), sent by the object's alarm through Cloudflare Email Service's binding
//! (`send_email`: env.AUTH_EMAIL.send({from, to, subject, text, html}) → {messageId}).
//!
//! What a mail carries, and what it does not:
//!
//! * a code is in the body alone — never in the subject, which delivery logs, a phone's lock screen and a mail list
//!   show to whoever looks.  It is derived when the mail is claimed (`Keyring::code`): the outbox holds none;
//! * nothing a person wrote, no research question, no other person's address (an address that changed is shown as its
//!   first character and its domain);
//! * no link that does anything: a code is typed where it was asked for (a link would be followed by the scanners some
//!   providers run on mail, and would open a session in whichever browser opened the mail).
//!
//! The drain, in two synchronous steps around the one that is not (the send): `claim` drops what is past its time,
//! drops a code's mail whose flow has moved on (another code sent since, the code typed, the flow over), and marks the
//! rest as sending, with their words; `settle` keeps what came of each.  A refusal that will not pass (a recipient
//! refused, a malformed address) is given up; what may pass is tried again later, a few times, never past the mail's
//! time.  Email Service takes no idempotency key: a send that ended without an answer may have gone, and its retry may
//! send it twice — the same code, the same words.

use serde_json::{Value as Json, json};

use crate::args;
use crate::crypto::Keyring;
use crate::sql::{Sql, SqlError, SqlExt};

#[derive(Debug, Clone)]
pub struct MailConfig {
    pub from: String,
    pub from_name: String,
    pub console: String,
    pub support: Option<String>,
}

impl MailConfig {
    pub fn from_vars(get: impl Fn(&str) -> Option<String>) -> Self {
        MailConfig {
            from: get("MAIL_FROM").unwrap_or_else(|| "noreply@impf.ai".into()),
            from_name: get("MAIL_FROM_NAME").unwrap_or_else(|| "道乃久 TaoChronos".into()),
            console: get("CONSOLE_ORIGIN")
                .unwrap_or_else(|| "https://console.impf.ai".into())
                .split(',')
                .next()
                .unwrap_or("")
                .trim()
                .to_string(),
            support: get("SUPPORT_ADDRESS"),
        }
    }
}

/// When a mail was asked for, in the two clocks its readers keep: Beijing / Singapore time, and UTC.
pub fn when(now: i64, locale: &str) -> String {
    let local = now + 8 * 3_600_000;
    let hm = |t: i64| format!("{:02}:{:02}", t.rem_euclid(86_400_000) / 3_600_000, t.rem_euclid(3_600_000) / 60_000);
    if locale == "en" {
        format!("{} {} UTC ({} in Beijing and Singapore)", crate::time::day(now), hm(now), hm(local))
    } else {
        format!("{} {}（北京时间）· {} UTC", crate::time::day(local), hm(local), hm(now))
    }
}

struct Words {
    sign: &'static str,
    never: &'static str,
    newer: &'static str,
    asked: &'static str,
    support: &'static str,
    support_at: &'static str,
}

const ZH: Words = Words {
    sign: "— 道乃久 · 医哲未来人工智能研究院（IMPF-AI）",
    never: "不要把验证码告诉任何人：道乃久的工作人员不会向你索要它。",
    newer: "验证码 {minutes} 分钟内有效；如果你又请求了新的验证码，以最新的一封为准。",
    asked: "请求时间：{at}",
    support: "如有疑问，请联系医哲未来人工智能研究院（IMPF-AI）。",
    support_at: "如有疑问，请写信至 {address}。",
};

const EN: Words = Words {
    sign: "— TaoChronos · IMPF-AI",
    never: "Never share this code with anyone: nobody at TaoChronos will ever ask you for it.",
    newer: "The code is valid for {minutes} minutes. If you asked for another code since, only the newest one works.",
    asked: "Requested: {at}",
    support: "If you have questions, contact IMPF-AI.",
    support_at: "Questions: write to {address}.",
};

/// A template's subject and paragraphs; `{code}` alone is the code's own block, `{newer}`, `{asked}`, `{never}` and
/// `{support}` the sentences above, `{x}` a value of the mail's.
fn template(name: &str, en: bool) -> Option<(&'static str, &'static [&'static str])> {
    Some(match (name, en) {
        ("register_code", false) => (
            "道乃久：确认你的邮箱",
            &[
                "你好，",
                "你正在用这个邮箱注册道乃久（TaoChronos）账户。在注册页面输入下面的验证码：",
                "{code}",
                "{newer}",
                "{asked}",
                "{never}",
                "如果这不是你本人的操作，忽略这封邮件即可：没有这个验证码，账户不会建立。",
            ],
        ),
        ("register_code", true) => (
            "TaoChronos: confirm your email address",
            &[
                "Hello,",
                "You are registering a TaoChronos account with this address. Enter this code on the registration page:",
                "{code}",
                "{newer}",
                "{asked}",
                "{never}",
                "If this wasn't you, ignore this email: without the code, no account is created.",
            ],
        ),
        ("register_exists", false) => (
            "道乃久：这个邮箱已有账户",
            &[
                "你好，",
                "有人（可能就是你）刚才想用这个邮箱注册道乃久账户，但这个邮箱已经有账户了。这封邮件里没有验证码，注册不会继续。",
                "如果是你：直接登录即可 —— {console}",
                "如果不是你：无需任何操作，你的账户没有任何变化。",
                "{asked}",
            ],
        ),
        ("register_exists", true) => (
            "TaoChronos: you already have an account",
            &[
                "Hello,",
                "Someone (probably you) just tried to register a TaoChronos account with this address, but it already has one. This email contains no code, and registration will not go on.",
                "If it was you, simply sign in: {console}",
                "If it wasn't you, there is nothing to do: your account has not changed.",
                "{asked}",
            ],
        ),
        ("signin_code", false) => (
            "道乃久：登录验证码",
            &[
                "你好，",
                "你正在登录道乃久账户。在登录页面输入下面的验证码：",
                "{code}",
                "{newer}",
                "{asked}",
                "{never}",
                "如果这不是你本人的操作，忽略这封邮件即可，并建议为账户添加通行密钥：没有这个验证码，别人无法登录。",
            ],
        ),
        ("signin_code", true) => (
            "TaoChronos: your sign-in code",
            &[
                "Hello,",
                "You are signing in to your TaoChronos account. Enter this code on the sign-in page:",
                "{code}",
                "{newer}",
                "{asked}",
                "{never}",
                "If this wasn't you, ignore this email — without the code nobody can sign in — and consider adding a passkey to your account.",
            ],
        ),
        ("signin_unknown", false) => (
            "道乃久：这个邮箱没有账户",
            &[
                "你好，",
                "有人（可能就是你）刚才想用这个邮箱登录道乃久，但没有用这个邮箱注册的账户。这封邮件里没有验证码。",
                "如需注册：{console}",
                "如果不是你：无需任何操作。",
                "{asked}",
            ],
        ),
        ("signin_unknown", true) => (
            "TaoChronos: no account uses this address",
            &[
                "Hello,",
                "Someone (probably you) just tried to sign in to TaoChronos with this address, but no account uses it. This email contains no code.",
                "To register: {console}",
                "If it wasn't you, there is nothing to do.",
                "{asked}",
            ],
        ),
        ("account_disabled", false) => (
            "道乃久：账户已停用",
            &["你好，", "这个邮箱的道乃久账户已停用，无法登录。这封邮件里没有验证码。", "{support}", "{asked}"],
        ),
        ("account_disabled", true) => (
            "TaoChronos: account disabled",
            &[
                "Hello,",
                "The TaoChronos account of this address is disabled and cannot sign in. This email contains no code.",
                "{support}",
                "{asked}",
            ],
        ),
        ("email_change_code", false) => (
            "道乃久：确认新的邮箱",
            &[
                "你好，",
                "你正在把道乃久账户的邮箱改为这个地址。在账户页面输入下面的验证码：",
                "{code}",
                "{newer}",
                "{asked}",
                "{never}",
                "如果这不是你本人的操作，忽略这封邮件即可：没有这个验证码，邮箱不会更改。",
            ],
        ),
        ("email_change_code", true) => (
            "TaoChronos: confirm your new email address",
            &[
                "Hello,",
                "You are changing your TaoChronos account's email address to this one. Enter this code on your account page:",
                "{code}",
                "{newer}",
                "{asked}",
                "{never}",
                "If this wasn't you, ignore this email: without the code, the address is not changed.",
            ],
        ),
        ("email_changed", false) => (
            "道乃久：账户邮箱已更改",
            &[
                "你好，",
                "你的道乃久账户的邮箱刚刚改为 {to}，以后的通知会发到新的邮箱。",
                "如果这不是你本人的操作，请立即用通行密钥登录检查（{console}）。",
                "{support}",
                "{asked}",
            ],
        ),
        ("email_changed", true) => (
            "TaoChronos: your account's email address changed",
            &[
                "Hello,",
                "Your TaoChronos account's email address was just changed to {to}. Notices will go there from now on.",
                "If this wasn't you, sign in with your passkey now and check ({console}).",
                "{support}",
                "{asked}",
            ],
        ),
        ("passkey_added", false) => (
            "道乃久：账户添加了通行密钥",
            &[
                "你好，",
                "你的道乃久账户刚刚添加了一个通行密钥：「{name}」。",
                "如果这不是你本人的操作，请立即登录（{console}）删除它，并检查已登录的设备。",
                "{asked}",
            ],
        ),
        ("passkey_added", true) => (
            "TaoChronos: a passkey was added to your account",
            &[
                "Hello,",
                "A passkey was just added to your TaoChronos account: “{name}”.",
                "If this wasn't you, sign in now ({console}), remove it, and check your signed-in devices.",
                "{asked}",
            ],
        ),
        ("passkey_removed", false) => (
            "道乃久：账户删除了通行密钥",
            &[
                "你好，",
                "你的道乃久账户刚刚删除了通行密钥「{name}」。",
                "如果这不是你本人的操作，请立即登录（{console}）检查。",
                "{asked}",
            ],
        ),
        ("passkey_removed", true) => (
            "TaoChronos: a passkey was removed from your account",
            &[
                "Hello,",
                "The passkey “{name}” was just removed from your TaoChronos account.",
                "If this wasn't you, sign in now and check ({console}).",
                "{asked}",
            ],
        ),
        ("recovery_used", false) => (
            "道乃久：账户用恢复码登录了",
            &[
                "你好，",
                "你的道乃久账户刚刚用一个恢复码登录，其他已登录的设备都已退出。剩余的恢复码：{left} 个。",
                "请为账户添加新的通行密钥。如果这不是你本人的操作，请立即联系我们。",
                "{support}",
                "{asked}",
            ],
        ),
        ("recovery_used", true) => (
            "TaoChronos: a recovery code was used",
            &[
                "Hello,",
                "Your TaoChronos account was just signed in to with a recovery code, and every other device was signed out. Recovery codes left: {left}.",
                "Please add a new passkey. If this wasn't you, contact us at once.",
                "{support}",
                "{asked}",
            ],
        ),
        _ => return None,
    })
}

pub const TEMPLATES: [&str; 10] = [
    "register_code",
    "register_exists",
    "signin_code",
    "signin_unknown",
    "account_disabled",
    "email_change_code",
    "email_changed",
    "passkey_added",
    "passkey_removed",
    "recovery_used",
];

/// The templates whose mail carries a code.
pub fn coded(name: &str) -> bool {
    matches!(name, "register_code" | "signin_code" | "email_change_code")
}

fn escape(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' => out.push_str("&quot;"),
            '\'' => out.push_str("&#39;"),
            c => out.push(c),
        }
    }
    out
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Mail {
    pub subject: String,
    pub text: String,
    pub html: String,
}

/// A mail's words, its values put in once: a value is never read again for a placeholder (a passkey a person named
/// "{code}" stays its name), and every value is escaped in the HTML.
pub fn render(name: &str, locale: &str, vars: &Json, cfg: &MailConfig) -> Option<Mail> {
    let en = locale == "en";
    let (subject, body) = template(name, en)?;
    let w = if en { &EN } else { &ZH };
    let support = match &cfg.support {
        Some(a) => w.support_at.replace("{address}", a),
        None => w.support.to_string(),
    };
    let value = |k: &str| -> Option<String> {
        match k {
            "console" => Some(cfg.console.clone()),
            "support" => Some(support.clone()),
            _ => vars.get(k).map(|v| v.as_str().map(String::from).unwrap_or_else(|| v.to_string())),
        }
    };
    // the template's own sentences first, then the values in one pass
    let expand = |p: &str| p.replace("{newer}", w.newer).replace("{asked}", w.asked).replace("{never}", w.never);
    let fill = |p: &str, esc: &dyn Fn(&str) -> String| -> String {
        let p = expand(p);
        let mut out = String::new();
        let mut rest = p.as_str();
        while let Some(open) = rest.find('{') {
            out.push_str(&esc(&rest[..open]));
            let after = &rest[open + 1..];
            match after.find('}') {
                Some(close) if after[..close].chars().all(|c| c.is_ascii_alphanumeric() || c == '_') => {
                    let k = &after[..close];
                    match value(k) {
                        Some(v) if k != "code" => out.push_str(&esc(&v)),
                        _ => out.push_str(&esc(&format!("{{{k}}}"))),
                    }
                    rest = &after[close + 1..];
                }
                _ => {
                    out.push_str(&esc("{"));
                    rest = after;
                }
            }
        }
        out.push_str(&esc(rest));
        out
    };
    let code = vars.get("code").and_then(Json::as_str).unwrap_or("");
    let plain = |s: &str| s.to_string();
    let mut text: Vec<String> =
        body.iter().map(|p| if *p == "{code}" { format!("    {code}") } else { fill(p, &plain) }).collect();
    text.push(format!("{}\n{}", w.sign, cfg.console));
    let paragraphs: Vec<String> = body
        .iter()
        .map(|p| {
            if *p == "{code}" {
                format!("<p style=\"font:600 30px/1.2 ui-monospace,Menlo,Consolas,monospace;letter-spacing:6px;margin:20px 0;padding:14px 18px;background:#f6f2e9;border-radius:8px;display:inline-block\">{}</p>", escape(code))
            } else {
                format!("<p style=\"margin:0 0 14px\">{}</p>", fill(p, &escape))
            }
        })
        .collect();
    let html = format!(
        "<!doctype html><html lang=\"{}\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width\"><title>{}</title></head>\
         <body style=\"margin:0;padding:24px;background:#fffcf6;color:#211f1b;font:15px/1.6 -apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif\">\
         <div style=\"max-width:560px;margin:0 auto\">{}<p style=\"margin:24px 0 0;color:#847c6f;font-size:13px\">{}<br>{}</p></div></body></html>",
        if en { "en" } else { "zh-CN" },
        escape(subject),
        paragraphs.join("\n"),
        escape(w.sign),
        escape(&cfg.console)
    );
    Some(Mail { subject: subject.into(), text: text.join("\n\n"), html })
}

// ------------------------------------------------------------------ the drain
/// What Email Service's binding throws (err.code) that a later try would meet again.
pub fn permanent(code: &str) -> bool {
    matches!(
        code,
        "E_VALIDATION_ERROR"
            | "E_FIELD_MISSING"
            | "E_TOO_MANY_RECIPIENTS"
            | "E_TOO_MANY_ATTACHMENTS"
            | "E_SENDER_NOT_VERIFIED"
            | "E_SENDER_DOMAIN_NOT_AVAILABLE"
            | "E_SENDER_DOMAIN_NOT_CONFIGURED"
            | "E_RECIPIENT_NOT_ALLOWED"
            | "E_RECIPIENT_PLAN_RESTRICTED"
            | "E_RECIPIENT_SUPPRESSED"
            | "E_ACCOUNT_SUSPENDED"
            | "E_CONTENT_TOO_LARGE"
            | "E_HEADER_NOT_ALLOWED"
            | "E_HEADER_USE_API_FIELD"
            | "E_HEADER_VALUE_INVALID"
            | "E_HEADER_VALUE_TOO_LONG"
            | "E_HEADER_NAME_INVALID"
            | "E_HEADERS_TOO_LARGE"
            | "E_HEADERS_TOO_MANY"
    )
}

const TRIES: i64 = 4;
const STUCK: i64 = 120_000;
const BATCH: i64 = 20;

/// A mail claimed for sending: its row, its recipient, its words.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Outgoing {
    pub id: i64,
    pub template: String,
    pub to: String,
    pub mail: Mail,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Claimed {
    pub out: Vec<Outgoing>,
    pub obsolete: i64,
    pub expired: i64,
}

pub struct Mailer<'a> {
    pub sql: &'a dyn Sql,
    pub keys: &'a Keyring,
    pub cfg: &'a MailConfig,
    /// a code's life, for its mail's words
    pub code_minutes: i64,
}

impl<'a> Mailer<'a> {
    /// The mails due now, claimed: what is past its time or obsolete dropped, the rest marked as sending with their
    /// words.  A mail claimed by a run that never came back is due again after STUCK.
    pub fn claim(&self, now: i64) -> Result<Claimed, SqlError> {
        let mut c = Claimed::default();
        self.sql
            .run("UPDATE outbox SET state = 'queued' WHERE state = 'sending' AND next_at < ?", args![now - STUCK])?;
        for m in self.sql.rows(
            "SELECT * FROM outbox WHERE state = 'queued' AND next_at <= ? ORDER BY id LIMIT ?",
            args![now, BATCH],
        )? {
            let id = m.int("id");
            if m.int("not_after") <= now {
                self.sql.run("UPDATE outbox SET state = 'expired', done = ? WHERE id = ?", args![now, id])?;
                c.expired += 1;
                continue;
            }
            let mut vars: Json = serde_json::from_str(&m.text("vars")).unwrap_or(json!({}));
            if let Some(flow) = m.opt_text("flow_id") {
                let f = self.sql.row("SELECT * FROM flows WHERE flow_id = ?", args![&flow])?;
                let Some(f) = f.filter(|f| {
                    f.text("state") == "pending" && f.int("generation") == m.int("generation") && f.int("expires") > now
                }) else {
                    self.sql.run("UPDATE outbox SET state = 'obsolete', done = ? WHERE id = ?", args![now, id])?;
                    c.obsolete += 1;
                    continue;
                };
                if coded(&m.text("template")) {
                    vars["code"] =
                        json!(self.keys.code(&f.text("purpose"), &flow, m.int("generation"), &f.text("address")));
                    vars["minutes"] = json!(self.code_minutes);
                }
            }
            vars["at"] = json!(when(m.int("created"), &m.text("locale")));
            let Some(mail) = render(&m.text("template"), &m.text("locale"), &vars, self.cfg) else {
                self.sql.run(
                    "UPDATE outbox SET state = 'failed', error = 'template', done = ? WHERE id = ?",
                    args![now, id],
                )?;
                continue;
            };
            self.sql.run(
                "UPDATE outbox SET state = 'sending', attempts = attempts + 1, next_at = ? WHERE id = ?",
                args![now, id],
            )?;
            c.out.push(Outgoing { id, template: m.text("template"), to: m.text("address"), mail });
        }
        Ok(c)
    }

    /// What came of a send: Ok(message id), or the error's code (None: no answer at all — it may have gone).
    pub fn settle(
        &self,
        id: i64,
        result: Result<Option<String>, Option<String>>,
        now: i64,
    ) -> Result<&'static str, SqlError> {
        let Some(m) = self.sql.row("SELECT attempts, not_after FROM outbox WHERE id = ?", args![id])? else {
            return Ok("unknown");
        };
        match result {
            Ok(message_id) => {
                let message_id: Option<String> = message_id.map(|s| s.chars().take(200).collect());
                self.sql.run(
                    "UPDATE outbox SET state = 'sent', message_id = ?, error = NULL, done = ? WHERE id = ?",
                    args![message_id, now, id],
                )?;
                Ok("sent")
            }
            Err(code) => {
                let word = code.unwrap_or_else(|| "no_answer".into());
                let word: String = word.chars().take(60).collect();
                if permanent(&word) {
                    self.sql.run(
                        "UPDATE outbox SET state = 'failed', error = ?, done = ? WHERE id = ?",
                        args![word, now, id],
                    )?;
                    return Ok("failed");
                }
                // what may pass: a limit (the day's: an hour later), Email Service's own failure, or no answer at all
                let attempts = m.int("attempts");
                let wait = if word == "E_DAILY_LIMIT_EXCEEDED" {
                    3_600_000
                } else {
                    (15_000 << attempts.clamp(0, 6)).min(600_000)
                };
                if attempts >= TRIES || now + wait >= m.int("not_after") {
                    self.sql.run(
                        "UPDATE outbox SET state = 'failed', error = ?, done = ? WHERE id = ?",
                        args![word, now, id],
                    )?;
                    return Ok("failed");
                }
                self.sql.run(
                    "UPDATE outbox SET state = 'queued', error = ?, next_at = ? WHERE id = ?",
                    args![word, now + wait, id],
                )?;
                Ok("later")
            }
        }
    }

    /// When the next mail is due (for the alarm), or None.
    pub fn next(&self) -> Result<Option<i64>, SqlError> {
        Ok(self
            .sql
            .row("SELECT MIN(next_at) AS t FROM outbox WHERE state IN ('queued', 'sending')", &[])?
            .and_then(|r| r.opt_int("t")))
    }

    /// What became of a flow's last mail, as the owner may read it (no address, no code).
    pub fn status(&self, flow: &str) -> Result<Option<Json>, SqlError> {
        Ok(self
            .sql
            .row("SELECT state, attempts, error, delivery, created, done FROM outbox WHERE flow_id = ? ORDER BY id DESC LIMIT 1", args![flow])?
            .map(|m| json!({ "state": m.text("state"), "attempts": m.int("attempts"), "error": m.opt_text("error"), "delivery": m.opt_text("delivery") })))
    }
}

/// Email Service's delivery events (a Queue subscribed to the sending domain: cf.email.sending.message.*), kept beside
/// the mail they are of when its message id is one the binding returned — each once (its eventId); a later "deferred"
/// never undoes a "delivered".  The docs do not say that an event's message id is the one the binding returns: an
/// event that matches no mail is counted, not kept.  → (kept, unmatched, duplicate)
pub fn delivery_events(sql: &dyn Sql, events: &[Json]) -> Result<(i64, i64, i64), SqlError> {
    let rank = |s: &str| match s {
        "deferred" => 1,
        "delivered" | "bounced" | "failed" | "rejected" => 3,
        "complained" => 4,
        _ => 0,
    };
    let (mut kept, mut unmatched, mut duplicate) = (0, 0, 0);
    for e in events {
        let status = e.get("type").and_then(Json::as_str).unwrap_or("").trim_start_matches("cf.email.sending.message.");
        let p = e.get("payload");
        let (Some(event_id), Some(message_id)) = (
            p.and_then(|p| p.get("eventId")).and_then(Json::as_str),
            p.and_then(|p| p.get("messageId")).and_then(Json::as_str),
        ) else {
            unmatched += 1;
            continue;
        };
        if rank(status) == 0 || sql.row("SELECT id FROM outbox WHERE message_id = ?", args![message_id])?.is_none() {
            unmatched += 1;
            continue;
        }
        if sql.row("SELECT 1 AS x FROM mail_events WHERE event_id = ?", args![event_id])?.is_some() {
            duplicate += 1;
            continue;
        }
        let p = p.unwrap_or(&Json::Null);
        let detail = json!({ "smtp": p.pointer("/delivery/smtpEnhancedStatusCode").or_else(|| p.pointer("/delivery/smtpStatusCode")),
            "bounce": p.pointer("/bounce/type"), "ms": p.pointer("/delivery/deliveryTimeMs"), "terminal": p.get("terminal") });
        let ts = e.pointer("/metadata/eventTimestamp").and_then(Json::as_str).unwrap_or("");
        sql.run(
            "INSERT INTO mail_events (event_id, message_id, status, ts, detail) VALUES (?, ?, ?, ?, ?)",
            args![event_id, message_id, status, ts, detail.to_string()],
        )?;
        let best = sql
            .rows("SELECT status FROM mail_events WHERE message_id = ?", args![message_id])?
            .iter()
            .map(|r| r.text("status"))
            .max_by_key(|s| rank(s))
            .unwrap_or_default();
        sql.run("UPDATE outbox SET delivery = ? WHERE message_id = ?", args![best, message_id])?;
        kept += 1;
    }
    Ok((kept, unmatched, duplicate))
}
