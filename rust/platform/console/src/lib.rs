//! console.impf.ai — 道乃久账户控制台 (docs/adr/0038-accounts-keys-and-credits.md; cloud/console/README.md).
//!
//! The browser's side of an account, as a backend-for-frontend (RFC 10017 §6.1): the page (public/, served from this
//! Worker) holds no token — the session is a `__Host-` cookie, `HttpOnly`, that names a row in the identity object;
//! every request that changes something must come from this origin (`Origin`, and `Sec-Fetch-Site` where the browser
//! sends it) as JSON, so that no other site's page can make a browser send one.
//!
//!   /auth/…      registering and signing in: email codes, passkeys, recovery codes, a passkey's touch (a step-up)
//!   /account/…   the person's own: passkeys, recovery codes, sessions, address, security events
//!   /console/…   their organisation's: keys (a live key needs a touch), projects, usage — through the API Worker's
//!                `Account` object (bound by script_name), after the identity object said the person is a member
//!
//! Turnstile, when its secret is set, stands before every flow that sends mail; its token is checked with Cloudflare
//! and kept once (its own reuse check is eventually consistent).

mod identity_do;

pub use identity_do::Identity;

use serde_json::{Value as Json, json};
use tao_edge::{body as read_body, call, json as answer, now, secret, var};
use tao_platform::crypto::{is_secret, new_secret};
use tao_platform::identity::{IdentityConfig, ip_key, locale};
use worker::{Context, Env, Fetch, Headers, Method, Request, RequestInit, Response, Result, Stub, event};

const PAGE: &str = include_str!("../public/index.html");
const SCRIPT: &str = include_str!("../public/console.js");
const STYLE: &str = include_str!("../public/console.css");
const LOGO: &str = include_str!("../public/logo.svg");

const SESSION: &str = "__Host-tcs";
const BINDING: &str = "__Host-tcb";

fn cookie(req: &Request, name: &str) -> Option<String> {
    let header = req.headers().get("Cookie").ok().flatten()?;
    header.split(';').find_map(|part| {
        let (k, v) = part.trim().split_once('=')?;
        (k == name && is_secret(v)).then(|| v.to_string())
    })
}

fn set_cookie(name: &str, value: &str, max_age: i64, same_site: &str) -> String {
    format!("{name}={value}; Path=/; Max-Age={max_age}; Secure; HttpOnly; SameSite={same_site}")
}

fn clear_cookie(name: &str) -> String {
    format!("{name}=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Lax")
}

fn identity(env: &Env) -> Result<Stub> {
    env.durable_object("IDENTITY")?.id_from_name("identity")?.get_stub_with_location_hint("apac")
}

fn account(env: &Env, org: &str) -> Result<Stub> {
    env.durable_object("ACCOUNT")?.id_from_name(org)?.get_stub()
}

/// A browser and a system, as a person is shown a session: never the agent string itself.
fn device(req: &Request) -> String {
    let ua = req.headers().get("User-Agent").ok().flatten().unwrap_or_default().to_ascii_lowercase();
    let browser = [
        ("micromessenger", "WeChat"),
        ("edg/", "Edge"),
        ("opr/", "Opera"),
        ("firefox/", "Firefox"),
        ("fxios", "Firefox"),
        ("crios", "Chrome"),
        ("chrome/", "Chrome"),
        ("safari/", "Safari"),
    ]
    .iter()
    .find(|(k, _)| ua.contains(k))
    .map_or("Browser", |(_, v)| *v);
    let system = [
        ("iphone", "iOS"),
        ("ipad", "iPadOS"),
        ("android", "Android"),
        ("harmonyos", "HarmonyOS"),
        ("windows", "Windows"),
        ("mac os x", "macOS"),
        ("cros", "ChromeOS"),
        ("linux", "Linux"),
    ]
    .iter()
    .find(|(k, _)| ua.contains(k))
    .map_or("", |(_, v)| *v);
    if system.is_empty() { browser.to_string() } else { format!("{browser} · {system}") }
}

fn place(req: &Request) -> String {
    req.headers().get("CF-IPCountry").ok().flatten().filter(|c| c.len() == 2).unwrap_or_default()
}

fn address(req: &Request) -> String {
    ip_key(&req.headers().get("CF-Connecting-IP").ok().flatten().unwrap_or_else(|| "unknown".into()))
}

/// The headers every answer carries, the page's own policy among them.
fn page(body: &str, content_type: &str, turnstile: bool) -> Result<Response> {
    let headers = Headers::new();
    headers.set("Content-Type", content_type)?;
    headers.set("Cache-Control", "no-cache")?;
    headers.set("X-Content-Type-Options", "nosniff")?;
    headers.set("Strict-Transport-Security", "max-age=31536000")?;
    headers.set("Referrer-Policy", "no-referrer")?;
    headers.set("X-Frame-Options", "DENY")?;
    headers.set("Cross-Origin-Opener-Policy", "same-origin")?;
    headers.set("Cross-Origin-Resource-Policy", "same-origin")?;
    headers.set(
        "Permissions-Policy",
        "publickey-credentials-create=(self), publickey-credentials-get=(self), camera=(), microphone=(), geolocation=(), payment=(), usb=(), \
         serial=(), browsing-topics=()",
    )?;
    let ts = if turnstile { " https://challenges.cloudflare.com" } else { "" };
    headers.set(
        "Content-Security-Policy",
        &format!(
            "default-src 'none'; script-src 'self'{ts}; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-src{}; \
             base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
            if turnstile { ts } else { " 'none'" }
        ),
    )?;
    Ok(Response::ok(body)?.with_headers(headers))
}

/// Is this request the page's own?  A change must come from the console's origin, as JSON; a read must not be one
/// another site's page made a browser send.
fn own(req: &Request, cfg: &IdentityConfig) -> bool {
    let h = |k: &str| req.headers().get(k).ok().flatten();
    let site_ok = h("Sec-Fetch-Site").is_none_or(|s| s == "same-origin");
    if req.method() == Method::Get {
        return site_ok;
    }
    let origin_ok = h("Origin").is_some_and(|o| cfg.origins.contains(&o));
    let json_ok = h("Content-Type").is_some_and(|c| c.to_ascii_lowercase().starts_with("application/json"));
    site_ok && origin_ok && json_ok
}

fn refused(status: u16, reason: &str) -> Result<Response> {
    answer(status, &json!({ "error": reason }), &[])
}

/// An identity op: `{ok}` → 200 with it, `{no}` → its HTTP status and the reason, else 503.
fn status_of(reason: &str) -> u16 {
    match reason {
        "session" => 401,
        "stepup" | "no_passkey" | "fresh" | "org" => 403,
        "address" | "network" | "service" | "cooldown" | "sends" | "attempts" => 429,
        "unconfigured" => 503,
        _ => 400,
    }
}

async fn ask(env: &Env, op: &str, b: Json) -> std::result::Result<Json, Result<Response>> {
    let res = match identity(env) {
        Ok(stub) => call(&stub, op, &b).await,
        Err(e) => Err(e),
    };
    match res {
        Ok((200, v)) if v.get("ok").is_some() => Ok(v["ok"].clone()),
        Ok((_, v)) if v.get("no").is_some() => {
            let no = &v["no"];
            let reason = no["reason"].as_str().unwrap_or("refused");
            let mut extra = Vec::new();
            if let Some(r) = no["retry"].as_i64() {
                extra.push(("Retry-After", r.to_string()));
            }
            Err(answer(
                status_of(reason),
                &json!({ "error": reason, "retry": no["retry"], "left": no["left"] }),
                &extra,
            ))
        }
        _ => Err(refused(503, "unavailable")),
    }
}

/// Cloudflare Turnstile, when its secret is set: the token valid, for this host and this action — and seen once.
async fn turnstile(env: &Env, req: &Request, token: &str, action: &str) -> bool {
    let Some(secret_key) = secret(env, "TURNSTILE_SECRET") else { return true };
    if token.is_empty() || token.len() > 2048 {
        return false;
    }
    let body = json!({ "secret": secret_key, "response": token, "remoteip": req.headers().get("CF-Connecting-IP").ok().flatten() });
    let headers = Headers::new();
    let _ = headers.set("Content-Type", "application/json");
    let mut init = RequestInit::new();
    init.with_method(Method::Post).with_headers(headers).with_body(Some(body.to_string().into()));
    let Ok(r) = Request::new_with_init("https://challenges.cloudflare.com/turnstile/v0/siteverify", &init) else {
        return false;
    };
    let Ok(mut res) = Fetch::Request(r).send().await else { return false };
    let v: Json = res.json().await.unwrap_or(Json::Null);
    let host = req.url().ok().and_then(|u| u.host_str().map(String::from)).unwrap_or_default();
    if v["success"] != json!(true)
        || v["hostname"].as_str() != Some(host.as_str())
        || v["action"].as_str() != Some(action)
    {
        return false;
    }
    matches!(ask(env, "first_use", json!({ "turnstile": token })).await, Ok(v) if v["first"] == json!(true))
}

#[event(fetch)]
async fn fetch(req: Request, env: Env, _ctx: Context) -> Result<Response> {
    match route(req, &env).await {
        Ok(r) => Ok(r),
        Err(e) => {
            worker::console_error!("console: {e}"); // never a cookie, never a body
            refused(500, "internal")
        }
    }
}

async fn route(mut req: Request, env: &Env) -> Result<Response> {
    let cfg = IdentityConfig::from_vars(|k| var(env, k));
    let path = req.path();
    let turnstile_on = secret(env, "TURNSTILE_SECRET").is_some() && var(env, "TURNSTILE_SITE_KEY").is_some();
    match (req.method(), path.as_str()) {
        (Method::Get, "/" | "/index.html") => return page(PAGE, "text/html; charset=utf-8", turnstile_on),
        (Method::Get, "/console.js") => return page(SCRIPT, "text/javascript; charset=utf-8", turnstile_on),
        (Method::Get, "/console.css") => return page(STYLE, "text/css; charset=utf-8", turnstile_on),
        (Method::Get, "/logo.svg") => return page(LOGO, "image/svg+xml", turnstile_on),
        (Method::Get, "/auth/config") => {
            return answer(
                200,
                &json!({ "registration": if cfg.registration_open { "open" } else { "off" },
                "turnstile": if turnstile_on { var(env, "TURNSTILE_SITE_KEY") } else { None }, "rp_id": cfg.rp_id }),
                &[],
            );
        }
        _ => {}
    }
    if !(path.starts_with("/auth/") || path.starts_with("/account") || path.starts_with("/console/")) {
        return refused(404, "not_found");
    }
    if !own(&req, &cfg) {
        return refused(403, "origin");
    }
    let body: Json = if req.method() == Method::Post {
        match read_body(&mut req, 64 * 1024).await? {
            Some(b) if b.is_empty() => json!({}),
            Some(b) => match serde_json::from_slice(&b) {
                Ok(v @ Json::Object(_)) => v,
                _ => return refused(400, "json"),
            },
            None => return refused(413, "too_large"),
        }
    } else {
        json!({})
    };
    let token = cookie(&req, SESSION).unwrap_or_default();
    let session_age = (cfg.session_ms / 1000).to_string();
    // a browser's binding: what ties a flow to the browser that began it (made on its first flow)
    let (binding, new_binding) = match cookie(&req, BINDING) {
        Some(b) => (b, None),
        None => {
            let b = new_secret(&tao_edge::JsEntropy);
            (b.clone(), Some(set_cookie(BINDING, &b, 86_400, "Strict")))
        }
    };
    let s = |k: &str| body.get(k).and_then(Json::as_str).unwrap_or("").to_string();
    let lang = locale(&s("locale")).to_string();
    let with_session = |v: &Json, extra: Option<String>| -> Vec<(&'static str, String)> {
        let mut h = Vec::new();
        if let Some(tok) = v.get("token").and_then(Json::as_str) {
            h.push(("Set-Cookie", set_cookie(SESSION, tok, cfg.session_ms / 1000, "Lax")));
        }
        if let Some(e) = extra {
            h.push(("Set-Cookie", e));
        }
        h
    };
    // what a session's answer never carries: the token itself
    let strip = |mut v: Json| {
        if let Some(o) = v.as_object_mut() {
            o.remove("token");
        }
        v
    };
    macro_rules! go {
        ($op:expr, $b:expr) => {
            match ask(env, $op, $b).await {
                Ok(v) => v,
                Err(r) => return r,
            }
        };
    }
    let post = req.method() == Method::Post;
    match (post, path.as_str()) {
        (true, "/auth/register/start" | "/auth/signin/start") => {
            let purpose = if path.contains("register") { "register" } else { "signin" };
            if !turnstile(env, &req, &s("turnstile"), purpose).await {
                return refused(403, "turnstile");
            }
            let v = go!(
                "start",
                json!({ "purpose": purpose, "email": s("email"), "binding": binding, "ip": address(&req), "locale": lang })
            );
            answer(200, &v, &with_session(&json!({}), new_binding))
        }
        (true, "/auth/flow/resend") => {
            let v = go!("resend", json!({ "flow": s("flow"), "binding": binding }));
            answer(200, &v, &[])
        }
        (true, "/auth/flow/verify") => {
            let v = go!(
                "verify",
                json!({ "flow": s("flow"), "binding": binding, "code": s("code"), "token": (!token.is_empty()).then_some(&token),
                "device": device(&req), "place": place(&req) })
            );
            answer(200, &strip(v.clone()), &with_session(&v, None))
        }
        (true, "/auth/register/options") => {
            let v = go!("enroll_options", json!({ "grant": s("grant"), "binding": binding }));
            answer(200, &json!({ "publicKey": v }), &[])
        }
        (true, "/auth/register/complete") => {
            let v = go!(
                "complete",
                json!({ "grant": s("grant"), "binding": binding, "credential": body.get("credential"), "name": s("name"),
                "device": device(&req), "place": place(&req) })
            );
            provision(env, &v["user"], &json!([{ "org": v["org"], "name": v["org_name"], "trial": v["trial"] }])).await;
            answer(200, &json!({ "recovery": v["recovery"], "trial": v["trial"] }), &with_session(&v, None))
        }
        (true, "/auth/passkey/options") => {
            let v = go!("signin_options", json!({}));
            answer(200, &json!({ "publicKey": v }), &[])
        }
        (true, "/auth/passkey/verify") => {
            let v = go!(
                "signin",
                json!({ "credential": body.get("credential"), "device": device(&req), "place": place(&req) })
            );
            answer(200, &json!({ "signed_in": true }), &with_session(&v, None))
        }
        (true, "/auth/second") => {
            let v = go!(
                "second",
                json!({ "grant": s("grant"), "binding": binding, "recovery": s("recovery"), "device": device(&req), "place": place(&req) })
            );
            answer(200, &json!({ "left": v["left"] }), &with_session(&v, None))
        }
        (true, "/auth/signout") => {
            let _ = ask(env, "sign_out", json!({ "token": token })).await;
            answer(200, &json!({}), &[("Set-Cookie", clear_cookie(SESSION))])
        }
        (true, "/auth/stepup/options") => {
            let v = go!("stepup_options", json!({ "token": token }));
            answer(200, &json!({ "publicKey": v }), &[])
        }
        (true, "/auth/stepup/verify") => {
            let v = go!("stepup", json!({ "token": token, "credential": body.get("credential") }));
            answer(
                200,
                &json!({ "strong": true }),
                &[(
                    "Set-Cookie",
                    set_cookie(SESSION, v["token"].as_str().unwrap_or(""), session_age.parse().unwrap_or(0), "Lax"),
                )],
            )
        }
        (false, "/account") => {
            let me = go!("overview", json!({ "token": token }));
            if let Ok(todo) = ask(env, "unprovisioned", json!({ "token": token })).await
                && todo.as_array().is_some_and(|a| !a.is_empty())
            {
                provision(env, &me["user"]["id"], &todo).await;
            }
            answer(200, &me, &[])
        }
        (false, "/account/events") => answer(200, &json!({ "events": go!("events", json!({ "token": token })) }), &[]),
        (true, "/account/passkeys/options") => {
            answer(200, &json!({ "publicKey": go!("add_options", json!({ "token": token })) }), &[])
        }
        (true, "/account/passkeys") => answer(
            200,
            &go!("add", json!({ "token": token, "credential": body.get("credential"), "name": s("name") })),
            &[],
        ),
        (true, "/account/passkeys/remove") => {
            answer(200, &go!("remove", json!({ "token": token, "id": s("id") })), &[])
        }
        (true, "/account/passkeys/rename") => {
            answer(200, &go!("rename", json!({ "token": token, "id": s("id"), "name": s("name") })), &[])
        }
        (true, "/account/recovery/renew") => answer(200, &go!("renew_recovery", json!({ "token": token })), &[]),
        (true, "/account/email/start") => {
            let v = go!(
                "email_start",
                json!({ "token": token, "email": s("email"), "binding": binding, "ip": address(&req), "locale": lang })
            );
            answer(200, &v, &with_session(&json!({}), new_binding))
        }
        (true, "/account/sessions/end") => {
            answer(200, &go!("end_session", json!({ "token": token, "id": s("id") })), &[])
        }
        (true, "/account/sessions/end-others") => answer(200, &go!("end_others", json!({ "token": token })), &[]),
        _ if path.starts_with("/console/") => org(&mut req, env, &path, &body, &token).await,
        _ => refused(404, "not_found"),
    }
}

/// An organisation's accounts object made ready for it, with the trial it was given: done again on a later visit if
/// it could not be now (the identity object keeps which are not yet).
async fn provision(env: &Env, user: &Json, orgs: &Json) {
    for o in orgs.as_array().into_iter().flatten() {
        let org = o["org"].as_str().unwrap_or("");
        let Ok(stub) = account(env, org) else { continue };
        let ok = matches!(call(&stub, "provision", &json!({ "org": org, "name": o["name"] })).await, Ok((200, v)) if v.get("refused").is_none());
        let trial = o["trial"].as_i64().unwrap_or(0);
        let granted = trial <= 0
            || matches!(call(&stub, "credit", &json!({ "kind": "grant", "credits": trial, "reference": format!("trial:{}", user.as_str().unwrap_or(org)),
                "note": "trial" })).await, Ok((200, v)) if v.get("refused").is_none());
        if ok && granted {
            let _ = ask(env, "provisioned", json!({ "org": org })).await;
        } else {
            worker::console_error!("provision {org}: not yet");
        }
    }
}

/// /console/…: the person's organisation, through the API Worker's `Account` object.
async fn org(req: &mut Request, env: &Env, path: &str, body: &Json, token: &str) -> Result<Response> {
    let s = |k: &str| body.get(k).and_then(Json::as_str).unwrap_or("").to_string();
    let org_id = if req.method() == Method::Get {
        req.url()?.query_pairs().find(|(k, _)| k == "org").map(|(_, v)| v.into_owned()).unwrap_or_default()
    } else {
        s("org")
    };
    let m = match ask(env, "member", json!({ "token": token, "org": org_id })).await {
        Ok(v) => v,
        Err(r) => return r,
    };
    let (user, strong, role) =
        (m["user"].as_str().unwrap_or(""), m["strong"] == json!(true), m["role"].as_str().unwrap_or(""));
    let stub = account(env, &org_id)?;
    let relay = |res: Result<(u16, Json)>| -> Result<Response> {
        match res {
            Ok((200, v)) => match v.get("refused") {
                Some(r) => answer(
                    r["status"].as_u64().unwrap_or(400) as u16,
                    &json!({ "error": r["code"], "message": r["message"] }),
                    &[],
                ),
                None => answer(200, &v, &[]),
            },
            _ => refused(503, "unavailable"),
        }
    };
    let manage = matches!(role, "owner" | "admin");
    match (req.method() == Method::Post, path) {
        (false, "/console/org") => relay(call(&stub, "summary", &json!({})).await),
        (false, "/console/usage") => {
            let url = req.url()?;
            let q = |k: &str| url.query_pairs().find(|(n, _)| n == k).map(|(_, v)| v.into_owned());
            let today = tao_platform::time::day(now());
            let from = q("from").unwrap_or_else(|| tao_platform::time::day(now() - 29 * tao_platform::time::DAY));
            relay(call(&stub, "org_usage", &json!({ "from": from, "to": q("to").unwrap_or(today) })).await)
        }
        (true, "/console/keys") => {
            let live = s("environment") == "live";
            if live && !strong {
                return refused(403, "stepup"); // a live key spends credits: a passkey's touch first
            }
            if !matches!(role, "owner" | "admin" | "developer") {
                return refused(403, "role");
            }
            relay(
                call(
                    &stub,
                    "create_key",
                    &json!({ "project": body.get("project"), "environment": s("environment"), "name": s("name"),
                "scopes": body.get("scopes"), "expires_days": body.get("expires_days"), "by": user }),
                )
                .await,
            )
        }
        (true, "/console/keys/revoke") => {
            // a live key's revocation needs a touch too (an outage is the price of a wrong one)
            let summary = call(&stub, "summary", &json!({})).await;
            let is_live = matches!(&summary, Ok((200, v)) if v["keys"].as_array().into_iter().flatten()
                .any(|k| k["id"].as_str() == Some(&s("id")) && k["environment"] == "live"));
            if is_live && !strong {
                return refused(403, "stepup");
            }
            relay(call(&stub, "revoke_key", &json!({ "key": s("id") })).await)
        }
        (true, "/console/projects") if manage => relay(
            call(&stub, "create_project", &json!({ "name": s("name"), "monthly_limit": body.get("monthly_limit") }))
                .await,
        ),
        (true, "/console/projects/limit") if manage => {
            if !strong {
                return refused(403, "stepup");
            }
            relay(
                call(
                    &stub,
                    "set_limit",
                    &json!({ "project": s("project"), "monthly_limit": body.get("monthly_limit") }),
                )
                .await,
            )
        }
        (true, "/console/projects" | "/console/projects/limit") => refused(403, "role"),
        _ => refused(404, "not_found"),
    }
}
