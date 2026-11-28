//! `Identity` — the console's one Durable Object of people (tao_platform::identity), named "identity" and placed in
//! Asia-Pacific (where its readers are).  Its protocol is JSON over `POST https://do/<op>`; the console Worker, alone
//! bound to it, has already checked the request's origin and read its cookies.  Each op is one synchronous step of
//! the core.  Its alarm sends the outbox's mail through Email Service (`AUTH_EMAIL`): claimed in one step, sent, and
//! what came of each kept in another.

use js_sys::Reflect;
use serde_json::{Value as Json, json};
use tao_edge::{DoSql, JsEntropy, json as answer, now, secret, var};
use tao_platform::crypto::Keyring;
use tao_platform::identity::{Fail, Identity as Core, IdentityConfig, Verified, Where};
use tao_platform::mail::{MailConfig, Mailer, delivery_events};
use wasm_bindgen::JsValue;
use worker::{
    DurableObject, EmailAddress, Env, Request, Response, Result, ScheduledTime, SendEmail, SendEmailBuilder, State,
    durable_object,
};

#[durable_object]
pub struct Identity {
    state: State,
    env: Env,
    sql: DoSql,
    cfg: IdentityConfig,
    mail: MailConfig,
    keys: Option<Keyring>,
}

fn s<'a>(v: &'a Json, k: &str) -> &'a str {
    v.get(k).and_then(Json::as_str).unwrap_or("")
}

fn here(b: &Json) -> Where {
    Where { device: s(b, "device").into(), place: s(b, "place").into() }
}

impl DurableObject for Identity {
    fn new(state: State, env: Env) -> Self {
        let get = |k: &str| var(&env, k);
        let cfg = IdentityConfig::from_vars(get);
        let mail = MailConfig::from_vars(|k| var(&env, k));
        let keys = secret(&env, "ACCOUNT_SECRET").and_then(|s| Keyring::new(&s));
        let sql = DoSql(state.storage().sql());
        let me = Identity { state, env, sql, cfg, mail, keys };
        if let Some(k) = &me.keys
            && let Err(e) = (Core { sql: &me.sql, cfg: &me.cfg, keys: k, e: &JsEntropy }).ensure()
        {
            worker::console_error!("identity schema: {e}");
        }
        me
    }

    async fn fetch(&self, mut req: Request) -> Result<Response> {
        let op = req.path().trim_start_matches('/').to_string();
        let body: Json = serde_json::from_slice(&req.bytes().await?).unwrap_or(Json::Null);
        let Some(keys) = &self.keys else {
            return answer(503, &json!({ "no": { "reason": "unconfigured" } }), &[]);
        };
        // from here to the answer, nothing is awaited but the alarm's arming, after the step
        let core = Core { sql: &self.sql, cfg: &self.cfg, keys, e: &JsEntropy };
        let out = run(&core, &op, &body, now());
        self.arm().await;
        match out {
            Ok(v) => answer(200, &json!({ "ok": v }), &[]),
            Err(Fail::No(w)) => {
                answer(200, &json!({ "no": { "reason": w.reason, "retry": w.retry, "left": w.left } }), &[])
            }
            Err(Fail::Storage(e)) => {
                worker::console_error!("identity storage {op}: {e}");
                answer(500, &json!({ "error": "storage" }), &[])
            }
        }
    }

    async fn alarm(&self) -> Result<Response> {
        let Some(keys) = &self.keys else { return Response::ok("") };
        let mailer = Mailer { sql: &self.sql, keys, cfg: &self.mail, code_minutes: self.cfg.code_ms / 60_000 };
        let t = now();
        let claimed = mailer.claim(t).map_err(|e| worker::Error::RustError(e.to_string()))?;
        let binding: Option<SendEmail> = self.env.get_binding::<SendEmail>("AUTH_EMAIL").ok();
        for o in &claimed.out {
            let result = match &binding {
                None => Err(Some("no_binding".to_string())),
                Some(b) => {
                    let from = EmailAddress::new(&self.mail.from_name, &self.mail.from);
                    let builder = SendEmailBuilder::new_with_email_address_and_str(&from, &o.to, &o.mail.subject);
                    builder.set_text(&o.mail.text);
                    builder.set_html(&o.mail.html);
                    match b.send_with_builder(&builder).await {
                        Ok(r) => Ok(Some(r.message_id())),
                        Err(err) => {
                            let code = Reflect::get(&err, &JsValue::from_str("code")).ok().and_then(|c| c.as_string());
                            Err(code)
                        }
                    }
                }
            };
            if let Err(word) = &result {
                // never the address, never the words: the template and the error's code
                worker::console_error!("mail {} {}", o.template, word.as_deref().unwrap_or("no_answer"));
            }
            if let Err(e) = mailer.settle(o.id, result, now()) {
                worker::console_error!("mail settle: {e}");
            }
        }
        let core = Core { sql: &self.sql, cfg: &self.cfg, keys, e: &JsEntropy };
        if let Err(e) = core.prune(t) {
            worker::console_error!("identity prune: {e}"); // what has outlived its use: small tables, a few deletes
        }
        self.arm().await;
        Response::ok("")
    }
}

impl Identity {
    /// The alarm, set for the next mail due (if sooner than the one set, or none is).
    async fn arm(&self) {
        let Some(keys) = &self.keys else { return };
        let mailer = Mailer { sql: &self.sql, keys, cfg: &self.mail, code_minutes: 0 };
        let Ok(Some(next)) = mailer.next() else { return };
        let storage = self.state.storage();
        let current = storage.get_alarm().await.ok().flatten();
        if current.is_none_or(|c| c > next) {
            // a moment, not an offset: workers-rs reads a bare i64 as milliseconds from now
            let at = ScheduledTime::new(js_sys::Date::new(&JsValue::from_f64(next.max(now()) as f64)));
            if let Err(e) = storage.set_alarm(at).await {
                worker::console_error!("identity alarm: {e}");
            }
        }
    }
}

fn run(core: &Core, op: &str, b: &Json, t: i64) -> std::result::Result<Json, Fail> {
    let verified = |v: Verified| match v {
        Verified::Enroll(g) => json!({ "next": "enroll", "grant": g }),
        Verified::Second(g) => json!({ "next": "second", "grant": g }),
        Verified::Session(s) => json!({ "next": "session", "token": s.token, "session": s.public_id }),
        Verified::Done => json!({ "next": "done" }),
    };
    match op {
        "start" => core.start(s(b, "purpose"), s(b, "email"), s(b, "binding"), s(b, "ip"), s(b, "locale"), t),
        "resend" => core.resend(s(b, "flow"), s(b, "binding"), t),
        "verify" => {
            let user = match b.get("token").and_then(Json::as_str) {
                Some(tok) => core.current(tok, t)?.map(|me| me.user.text("user_id")),
                None => None,
            };
            core.verify(s(b, "flow"), s(b, "binding"), s(b, "code"), user.as_deref(), &here(b), t).map(verified)
        }
        "enroll_options" => core.enroll_options(s(b, "grant"), s(b, "binding"), t),
        "complete" => core.complete(
            s(b, "grant"),
            s(b, "binding"),
            b.get("credential").filter(|c| c.is_object()),
            s(b, "name"),
            &here(b),
            t,
        ),
        "signin_options" => core.signin_options(t),
        "signin" => {
            core.signin(&b["credential"], &here(b), t).map(|s| json!({ "token": s.token, "session": s.public_id }))
        }
        "second" => core.second(s(b, "grant"), s(b, "binding"), s(b, "recovery"), &here(b), t),
        "stepup_options" => core.stepup_options(s(b, "token"), t),
        "stepup" => core.stepup(s(b, "token"), &b["credential"], t).map(|token| json!({ "token": token })),
        "add_options" => core.add_options(s(b, "token"), t),
        "add" => core.add(s(b, "token"), &b["credential"], s(b, "name"), t),
        "remove" => core.remove(s(b, "token"), s(b, "id"), t),
        "rename" => core.rename(s(b, "token"), s(b, "id"), s(b, "name"), t).map(|_| json!({})),
        "renew_recovery" => core.renew_recovery(s(b, "token"), t).map(|codes| json!({ "recovery": codes })),
        "email_start" => {
            core.start_email_change(s(b, "token"), s(b, "email"), s(b, "binding"), s(b, "ip"), s(b, "locale"), t)
        }
        "overview" => core.overview(s(b, "token"), t),
        "events" => core.events(s(b, "token"), t),
        "sign_out" => core.sign_out(s(b, "token"), t).map(|_| json!({})),
        "end_session" => core.end_session(s(b, "token"), s(b, "id"), t).map(|ended| json!({ "ended": ended })),
        "end_others" => core.end_others(s(b, "token"), t).map(|_| json!({})),
        "member" => core
            .member(s(b, "token"), s(b, "org"), t)
            .map(|(user, strong, role)| json!({ "user": user, "strong": strong, "role": role })),
        "unprovisioned" => {
            let me = core.current(s(b, "token"), t)?.ok_or_else(|| tao_platform::identity::no("session"))?;
            let rows = core.unprovisioned(&me.user.text("user_id"))?;
            Ok(json!(
                rows.iter()
                    .map(|r| json!({ "org": r.text("org_id"), "name": r.text("name"), "trial": r.int("trial"),
                "user": me.user.text("user_id") }))
                    .collect::<Vec<_>>()
            ))
        }
        "provisioned" => core.provisioned(s(b, "org"), t).map(|_| json!({})).map_err(Fail::from),
        "first_use" => core.first_use(s(b, "turnstile"), t).map(|first| json!({ "first": first })),
        "delivery_events" => {
            let events = b.get("events").and_then(Json::as_array).cloned().unwrap_or_default();
            delivery_events(core.sql, &events).map(|(kept, unmatched, duplicate)| json!({ "kept": kept, "unmatched": unmatched, "duplicate": duplicate })).map_err(Fail::from)
        }
        _ => Err(tao_platform::identity::no("op")),
    }
}
