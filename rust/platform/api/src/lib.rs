//! api.impf.ai — 道乃久开发者接口 (docs/adr/0038-accounts-keys-and-credits.md, docs/adr/0039-model-relay-and-daily-allowance.md;
//! cloud/api/README.md).
//!
//!   POST /v1/chat/completions     a model's chat (the private model gateway: chat.rs)
//!   GET  /v1/models               the models this key may call
//!   POST /v1/evidence/search      a search of the classics (classics.search on the full corpus)
//!   POST /v1/citations/verify     a quotation found, or not, where it is said to be (validation.verify_quote)
//!   GET  /v1/limits               what this key may do now: its rate, its owner's daily allowance, how calls are paid
//!   GET  /v1/usage?from=&to=      this key's project's usage by day (scope usage:read)
//!   GET  /v1/requests/{id}        a request's record: how it ended, whether it was counted
//!   GET  /v1                      the service: its products, models and prices
//!   …/admin/…                     the owner's: organisations, members, keys, credits, people's allowances (Bearer the
//!                                 token whose SHA-256 is ADMIN_TOKEN_SHA256; off without it)
//!
//! Every execution — chat, search, verification — goes through one admission (exec.rs): the key's organisation, then
//! the key's owner's daily allowance, five a UTC day by default, whichever keys, projects, organisations or models it
//! comes through.  The edge's own rate limits (per address, per key) stand before the objects; the objects' own are
//! exact.  No CORS: a key belongs on a server, not in a page.

mod account;
mod chat;
mod exec;
mod user_quota;

pub use account::Account;
pub use user_quota::UserQuota;

use std::time::Duration;

use futures_util::future::{Either, select};
use serde_json::{Value as Json, json};
use tao_edge::{JsEntropy, call, json as answer, now, var};
use tao_platform::accounts::{Product, Refusal, idem_key_ok, is_user_id};
use tao_platform::api::{self, Corpus};
use tao_platform::crypto::{digest, new_id, same};
use tao_platform::keys::{self, ParsedKey};
use tao_platform::models;
use worker::{AbortController, Context, Delay, Env, Method, Request, RequestInit, Response, Result, event};

use exec::{End, Exec, Gate, account, user_quota};

const VERSION: &str = "2026-11-28";

fn refusal(status: u16, kind: &'static str, code: &'static str, message: impl Into<String>) -> Refusal {
    Refusal { status, kind, code, message: message.into(), retry: None }
}

/// A refusal as the caller is told it, with the headers given (the allowance's, when a request was counted).
fn refuse_with(rid: &str, r: &Refusal, extra: &[(&'static str, String)]) -> Result<Response> {
    let mut headers = vec![("X-Request-Id", rid.to_string())];
    if let Some(s) = r.retry {
        headers.push(("Retry-After", s.to_string()));
    }
    headers.extend(extra.iter().cloned());
    answer(r.status, &api::error(rid, r), &headers)
}

fn refuse(rid: &str, r: &Refusal) -> Result<Response> {
    refuse_with(rid, r, &[])
}

/// A refusal an object sent back: `{refused: {status, type, code, message, retry}}`.
fn object_refusal(v: &Json) -> Option<Refusal> {
    let r = v.get("refused")?;
    let kind = match r.get("type").and_then(Json::as_str).unwrap_or("") {
        "authentication" => "authentication",
        "permission" => "permission",
        "rate_limit" => "rate_limit",
        "insufficient_credits" => "insufficient_credits",
        "not_found" => "not_found",
        "conflict" => "conflict",
        "unavailable" => "unavailable",
        _ => "invalid_request",
    };
    Some(Refusal {
        status: r.get("status").and_then(Json::as_u64).unwrap_or(400) as u16,
        kind,
        code: leak_code(r.get("code").and_then(Json::as_str).unwrap_or("refused")),
        message: r.get("message").and_then(Json::as_str).unwrap_or("").chars().take(300).collect(),
        retry: r.get("retry").and_then(Json::as_i64),
    })
}

/// The codes the objects may answer with, as static words (an unknown one is "refused").
fn leak_code(c: &str) -> &'static str {
    const CODES: &[&str] = &[
        "invalid_key",
        "revoked_key",
        "expired_key",
        "org_disabled",
        "scope",
        "project_archived",
        "user_binding_required",
        "member_suspended",
        "model_access",
        "user_suspended",
        "idempotency_conflict",
        "request_in_progress",
        "request_outcome_unknown",
        "stream_replay_unavailable",
        "idempotency_unavailable",
        "user_concurrency",
        "daily_quota_exceeded",
        "rate",
        "concurrency",
        "credits",
        "project_limit",
        "org",
        "project",
        "name",
        "expires",
        "keys",
        "projects",
        "reference",
        "limit",
        "environment",
        "product",
        "op",
        "key",
        "days",
        "stepup",
        "owner",
        "owner_required",
        "user",
        "status",
        "role",
    ];
    CODES.iter().copied().find(|k| *k == c).unwrap_or("refused")
}

/// An edge rate limit (a `[[ratelimits]]` binding): true when the request may go on (and when there is no binding).
async fn within(env: &Env, binding: &str, key: &str) -> bool {
    match env.rate_limiter(binding) {
        Ok(l) => l.limit(key.to_string()).await.map(|o| o.success).unwrap_or(true),
        Err(_) => true,
    }
}

fn bearer(req: &Request) -> Option<String> {
    let h = req.headers().get("Authorization").ok().flatten()?;
    let t = h.strip_prefix("Bearer ").or_else(|| h.strip_prefix("bearer "))?.trim();
    (!t.is_empty()).then(|| t.to_string())
}

fn address(req: &Request) -> String {
    req.headers().get("CF-Connecting-IP").ok().flatten().unwrap_or_else(|| "unknown".into())
}

#[event(fetch)]
async fn fetch(req: Request, env: Env, ctx: Context) -> Result<Response> {
    let rid = new_id(&JsEntropy, "req", 16);
    match route(req, &env, &ctx, &rid).await {
        Ok(r) => Ok(r),
        Err(e) => {
            worker::console_error!("api {rid}: {e}"); // never a key, never a body
            refuse(&rid, &refusal(500, "internal", "internal", "the service failed"))
        }
    }
}

async fn route(mut req: Request, env: &Env, ctx: &Context, rid: &str) -> Result<Response> {
    let path = req.path();
    let method = req.method();
    // the address's own allowance at the edge, before anything else is asked
    if !within(env, "IP_LIMIT", &address(&req)).await {
        return refuse(
            rid,
            &Refusal {
                retry: Some(60),
                ..refusal(429, "rate_limit", "address", "too many requests from this address")
            },
        );
    }
    match (method, path.as_str()) {
        (Method::Get, "/" | "/v1" | "/v1/") => answer(200, &service(env), &[("X-Request-Id", rid.to_string())]),
        (Method::Post, "/v1/chat/completions") => chat::completions(&mut req, env, ctx, rid).await,
        (Method::Get, "/v1/models") => chat::list(&req, env, rid).await,
        (Method::Post, "/v1/evidence/search") => product(&mut req, env, rid, Product::Search).await,
        (Method::Post, "/v1/citations/verify") => product(&mut req, env, rid, Product::Verify).await,
        (Method::Get, "/v1/limits") => limits(&req, env, rid).await,
        (Method::Get, "/v1/usage") => usage(&req, env, rid).await,
        (Method::Get, p) if p.starts_with("/v1/requests/") => {
            request_status(&req, env, rid, &p["/v1/requests/".len()..]).await
        }
        (_, p) if p.starts_with("/admin/") => admin(&mut req, env, rid).await,
        (
            _,
            "/v1/chat/completions"
            | "/v1/models"
            | "/v1/evidence/search"
            | "/v1/citations/verify"
            | "/v1/limits"
            | "/v1/usage",
        ) => refuse(rid, &refusal(405, "invalid_request", "method", "this path takes another method")),
        _ => refuse(rid, &refusal(404, "not_found", "path", "no such endpoint")),
    }
}

fn service(env: &Env) -> Json {
    let cfg = tao_platform::accounts::AccountConfig::from_vars(|k| var(env, k));
    let quota = tao_platform::quota::QuotaConfig::from_vars(|k| var(env, k));
    let m = chat::ModelSettings::read(env);
    let credits = |p: Product| if cfg.funding == tao_platform::accounts::Funding::Credits { cfg.price(p) } else { 0 };
    json!({
        "service": "TaoChronos API", "version": VERSION,
        "products": {
            "chat.completions": { "path": "/v1/chat/completions", "credits": credits(Product::Chat), "available": m.gate != tao_platform::accounts::ModelGate::Off },
            "evidence.search": { "path": "/v1/evidence/search", "credits": credits(Product::Search) },
            "citations.verify": { "path": "/v1/citations/verify", "credits": credits(Product::Verify) },
        },
        "models": if m.gate == tao_platform::accounts::ModelGate::Off { json!([]) } else { json!(m.offered.iter().map(|s| s.id).collect::<Vec<_>>()) },
        "daily_allowance": { "limit": quota.daily_limit, "timezone": "UTC", "shared_by": ["chat.completions", "evidence.search", "citations.verify"] },
        "funding": cfg.funding.name(),
        "price_version": cfg.price_version,
        "documentation": var(env, "DOCS_URL").unwrap_or_else(|| "https://github.com/psknlr/TaoChronos/blob/main/cloud/api/README.md".into()),
    })
}

/// The key a request carries, read: refused (401) when there is none or it is not one.
async fn key_of(req: &Request, env: &Env, rid: &str) -> std::result::Result<ParsedKey, Result<Response>> {
    let Some(token) = bearer(req) else {
        return Err(refuse(
            rid,
            &refusal(401, "authentication", "missing_key", "send the API key as Authorization: Bearer tao_…"),
        ));
    };
    let Some(key) = keys::parse(&token) else {
        return Err(refuse(rid, &refusal(401, "authentication", "invalid_key", "the API key is not valid")));
    };
    // a key's own allowance at the edge (the object's per-minute count is the exact one)
    if !within(env, "KEY_LIMIT", &key.digest[..32]).await {
        return Err(refuse(
            rid,
            &Refusal { retry: Some(60), ..refusal(429, "rate_limit", "rate", "too many requests with this key") },
        ));
    }
    Ok(key)
}

/// The request's `Idempotency-Key`, if it sent one that may be one.
fn idempotency(req: &Request, rid: &str) -> std::result::Result<Option<String>, Result<Response>> {
    match req.headers().get("Idempotency-Key").ok().flatten() {
        None => Ok(None),
        Some(k) if idem_key_ok(&k) => Ok(Some(k)),
        Some(_) => Err(refuse(
            rid,
            &refusal(400, "invalid_request", "idempotency_key", "an Idempotency-Key is 1–255 visible ASCII characters"),
        )),
    }
}

/// Who a key is (its organisation's object): its owner, whether it executes, what it may call.
async fn whoami(env: &Env, rid: &str, key: &ParsedKey, models: &str) -> std::result::Result<Json, Result<Response>> {
    let stub = account(env, &key.org).map_err(Err)?;
    match call(&stub, "whoami", &json!({ "digest": key.digest, "models": models })).await {
        Ok((200, out)) => match object_refusal(&out) {
            Some(r) => Err(refuse(rid, &r)),
            None => Ok(out),
        },
        Ok((_, out)) => Err(match object_refusal(&out) {
            Some(r) => refuse(rid, &r),
            None => refuse(rid, &refusal(503, "unavailable", "accounts", "the accounts could not be read; try again")),
        }),
        Err(_) => {
            Err(refuse(rid, &refusal(503, "unavailable", "accounts", "the accounts could not be read; try again")))
        }
    }
}

/// `GET /v1/limits`: the key's rate and what is in flight, how calls are paid, and its owner's daily allowance.
async fn limits(req: &Request, env: &Env, rid: &str) -> Result<Response> {
    let key = match key_of(req, env, rid).await {
        Ok(k) => k,
        Err(r) => return r,
    };
    let (status, mut out) = call(&account(env, &key.org)?, "limits", &json!({ "digest": key.digest })).await?;
    if let Some(r) = object_refusal(&out) {
        return refuse(rid, &r);
    }
    if status != 200 {
        return refuse(rid, &refusal(503, "unavailable", "accounts", "the accounts could not be read; try again"));
    }
    let owner = out["key"]["owner"].as_str().map(String::from);
    out["user_quota"] = match owner.as_deref() {
        Some(user) => match call(&user_quota(env, user)?, "limits", &json!({})).await {
            Ok((200, q)) => q,
            _ => Json::Null,
        },
        None => Json::Null,
    };
    answer(200, &json!({ "id": rid, "object": "limits", "data": out }), &[("X-Request-Id", rid.to_string())])
}

async fn usage(req: &Request, env: &Env, rid: &str) -> Result<Response> {
    let key = match key_of(req, env, rid).await {
        Ok(k) => k,
        Err(r) => return r,
    };
    let url = req.url()?;
    let q = |name: &str| url.query_pairs().find(|(k, _)| k == name).map(|(_, v)| v.into_owned());
    let today = tao_platform::time::day(now());
    let body = json!({ "digest": key.digest, "from": q("from").unwrap_or_else(|| today.clone()), "to": q("to").unwrap_or(today) });
    let (status, out) = call(&account(env, &key.org)?, "usage", &body).await?;
    if let Some(r) = object_refusal(&out) {
        return refuse(rid, &r);
    }
    if status != 200 {
        return refuse(rid, &refusal(503, "unavailable", "accounts", "the accounts could not be read; try again"));
    }
    answer(200, &json!({ "id": rid, "object": "usage", "data": out }), &[("X-Request-Id", rid.to_string())])
}

/// `GET /v1/requests/{id}`: a request's record, to its owner's keys of its organisation.
async fn request_status(req: &Request, env: &Env, rid: &str, id: &str) -> Result<Response> {
    let key = match key_of(req, env, rid).await {
        Ok(k) => k,
        Err(r) => return r,
    };
    let me = match whoami(env, rid, &key, "off").await {
        Ok(v) => v,
        Err(r) => return r,
    };
    let Some(owner) = me["owner"].as_str() else {
        return refuse(
            rid,
            &refusal(403, "permission", "user_binding_required", "this API key must be assigned to a registered user"),
        );
    };
    let (status, out) = call(&user_quota(env, owner)?, "status", &json!({ "request_id": id, "org": key.org })).await?;
    match (status, out.get("request")) {
        (200, Some(r)) if r.is_object() => answer(200, r, &[("X-Request-Id", rid.to_string())]),
        (200, _) => {
            refuse(rid, &refusal(404, "not_found", "request", "no such request of this key's owner and organisation"))
        }
        _ => refuse(rid, &refusal(503, "unavailable", "quota", "the request's record could not be read; try again")),
    }
}

/// An evidence search or a citation check: admitted, the corpus asked, the end told.
async fn product(req: &mut Request, env: &Env, rid: &str, product: Product) -> Result<Response> {
    let key = match key_of(req, env, rid).await {
        Ok(k) => k,
        Err(r) => return r,
    };
    let Some(body) = tao_edge::body(req, api::MOST_BODY).await? else {
        return refuse(
            rid,
            &refusal(
                413,
                "invalid_request",
                "too_large",
                format!("a request body is at most {} bytes", api::MOST_BODY),
            ),
        );
    };
    let call_ = match api::read_request(product, &body) {
        Ok(c) => c,
        Err(r) => return refuse(rid, &r),
    };
    // nothing is admitted for a call that cannot be made
    let Ok(corpus) = env.service("CORPUS") else {
        return refuse(
            rid,
            &Refusal {
                retry: Some(60),
                ..refusal(503, "unavailable", "corpus", "the full corpus is not deployed here")
            },
        );
    };
    let idem = match idempotency(req, rid) {
        Ok(i) => i,
        Err(r) => return r,
    };
    // the corpus, within a time the lease outlasts: the answer and its body under one deadline (a body that trickles
    // is no answer), at most the hold less a quarter of a minute — so that a lease never lapses under a call still
    // being read.  When it passes the call is aborted, so that the corpus stops too
    let hold_ms = tao_platform::accounts::AccountConfig::from_vars(|k| var(env, k)).hold_ms;
    let secs = var(env, "CORPUS_TIMEOUT_SECONDS")
        .and_then(|v| v.parse::<i64>().ok())
        .filter(|s| (5..=90).contains(s))
        .unwrap_or(60)
        .min(hold_ms / 1000 - 15)
        .max(5) as u64;
    let path = req.path();
    let ex = Exec {
        rid,
        org: &key.org,
        digest: &key.digest,
        product,
        model: None,
        request_hash: models::request_hash(
            "POST",
            &path,
            &json!({ "tool": call_.tool, "arguments": call_.arguments }),
            None,
        ),
        idem,
        hold_ms,
        models: "off",
    };
    let a = match exec::admit(env, &ex).await? {
        Gate::Done(r) => return Ok(r),
        Gate::Go(a) => a,
    };
    let headers = worker::Headers::new();
    headers.set("Content-Type", "application/json")?;
    headers.set("Accept", "application/json")?;
    let mut init = RequestInit::new();
    init.with_method(Method::Post).with_headers(headers).with_body(Some(api::corpus_body(&call_).to_string().into()));
    let stop = AbortController::default();
    let signal = stop.signal();
    let sys: worker::web_sys::RequestInit = (&init).into();
    sys.set_signal(Some(&*signal));
    let asked: Request =
        worker::web_sys::Request::new_with_str_and_init("https://corpus.internal/api/call", &sys)?.into();
    let whole = async {
        let mut res = corpus.fetch_request(asked).await?;
        let status = res.status_code();
        let retry = res.headers().get("Retry-After")?;
        let text = res.text().await?;
        Ok::<_, worker::Error>((status, text, retry))
    };
    enum Came {
        Answer(Corpus),
        Late,
    }
    let came = match select(Box::pin(whole), Box::pin(Delay::from(Duration::from_secs(secs)))).await {
        Either::Left((Ok((status, text, retry)), _)) => Came::Answer(api::read_corpus(status, &text, retry.as_deref())),
        Either::Left((Err(e), _)) => {
            worker::console_error!("api {rid}: corpus {e}");
            Came::Answer(Corpus::Failed)
        }
        Either::Right(_) => {
            stop.abort();
            Came::Late
        }
    };
    // what the caller is told, and whether the allowance was spent: a tool that ran (or may have) spends it; a tool
    // that refused its arguments, or a corpus still starting, ran nothing and spends nothing
    let error_body = |r: &Refusal| api::error(rid, r).to_string();
    let (end, outcome): (End, std::result::Result<Json, Refusal>) = match came {
        Came::Answer(Corpus::Delivered(data)) => {
            let body = api::success(rid, product, now(), data, a.credits, &a.env, &a.price_version);
            (End::succeeded(Some((200, body.to_string()))), Ok(body))
        }
        Came::Answer(Corpus::Refused(msg)) => {
            let r = refusal(422, "invalid_request", "tool_refused", format!("{msg} (nothing was counted)"));
            (End::released(422, "tool_refused"), Err(r))
        }
        Came::Answer(Corpus::Unavailable(s)) => {
            let r = Refusal {
                retry: Some(s),
                ..refusal(
                    503,
                    "unavailable",
                    "corpus",
                    "the corpus is starting or busy; nothing was counted — try again",
                )
            };
            (End::released(503, "corpus"), Err(r))
        }
        Came::Answer(Corpus::Failed) => {
            let r = refusal(502, "unavailable", "corpus", "the corpus failed; nothing was charged");
            (End::failed(502, "corpus", Some((502, error_body(&r)))), Err(r))
        }
        Came::Late => {
            let r = Refusal {
                retry: Some(10),
                ..refusal(503, "unavailable", "corpus_timeout", "the corpus did not answer in time")
            };
            (End::failed(503, "corpus_timeout", Some((503, error_body(&r)))), Err(r))
        }
    };
    exec::end(env, &a, &end).await;
    let mut extra = vec![("X-Request-Id", rid.to_string())];
    extra.extend(exec::quota_headers(&a.quota, !end.executed));
    match outcome {
        Ok(body) => answer(200, &body, &extra),
        Err(r) => refuse_with(rid, &r, &extra[1..]),
    }
}

// ------------------------------------------------------------------ the owner's
/// The owner's endpoints, behind the token whose SHA-256 is ADMIN_TOKEN_SHA256 (the token itself is kept nowhere here).
/// What they are told of people (a user's id, a member's role) is taken as said: the owner vouches for it.
async fn admin(req: &mut Request, env: &Env, rid: &str) -> Result<Response> {
    let Some(expected) =
        var(env, "ADMIN_TOKEN_SHA256").map(|v| v.trim().to_ascii_lowercase()).filter(|v| v.len() == 64)
    else {
        return refuse(rid, &refusal(404, "not_found", "path", "no such endpoint"));
    };
    let given = bearer(req).map(|t| digest(&t)).unwrap_or_default();
    if !same(given.as_bytes(), expected.as_bytes()) {
        worker::console_log!("api {rid}: admin token refused");
        return refuse(rid, &refusal(401, "authentication", "admin", "the owner's token is required"));
    }
    let path = req.path();
    let parts: Vec<&str> = path.trim_start_matches("/admin/").split('/').collect();
    let method = req.method();
    let body: Json = if method == Method::Post {
        match tao_edge::body(req, 16 * 1024).await? {
            Some(b) if !b.is_empty() => serde_json::from_slice(&b).unwrap_or(Json::Null),
            Some(_) => json!({}),
            None => return refuse(rid, &refusal(413, "invalid_request", "too_large", "at most 16 KiB")),
        }
    } else {
        json!({})
    };
    let ok = |v: Json| answer(200, &v, &[("X-Request-Id", rid.to_string())]);
    let ask = |org: &str, op: &'static str, b: Json| {
        let org = org.to_string();
        async move {
            if !keys::is_org_id(&org) {
                return Err(refusal(404, "not_found", "org", "not an organisation's id"));
            }
            let (status, out) =
                call(&account(env, &org).map_err(|_| refusal(500, "internal", "internal", "no binding"))?, op, &b)
                    .await
                    .map_err(|_| refusal(503, "unavailable", "accounts", "the accounts could not be asked"))?;
            match object_refusal(&out) {
                Some(r) => Err(r),
                None if status == 200 => Ok(out),
                None => Err(refusal(503, "unavailable", "accounts", "the accounts failed")),
            }
        }
    };
    let person = |user: &str, op: &'static str| {
        let user = user.to_string();
        async move {
            if !is_user_id(&user) {
                return Err(refusal(404, "not_found", "user", "not a registered person's id (usr_…)"));
            }
            let (status, out) = call(
                &user_quota(env, &user).map_err(|_| refusal(500, "internal", "internal", "no binding"))?,
                op,
                &json!({ "by": "owner", "n": 50 }),
            )
            .await
            .map_err(|_| refusal(503, "unavailable", "quota", "the allowance could not be asked"))?;
            match object_refusal(&out) {
                Some(r) => Err(r),
                None if status == 200 => Ok(out),
                None => Err(refusal(503, "unavailable", "quota", "the allowance failed")),
            }
        }
    };
    let result = match (method, parts.as_slice()) {
        (Method::Post, ["orgs"]) => {
            let org = new_id(&JsEntropy, "org", 16);
            ask(&org, "provision", json!({ "org": org, "name": body["name"], "owner": body["owner"], "by": "owner" })).await
        }
        (Method::Get, ["orgs", org]) => ask(org, "summary", json!({})).await,
        (Method::Post, ["orgs", org, "grants"]) => ask(org, "credit", json!({ "kind": "grant", "credits": body["credits"], "reference": body["reference"], "note": body["note"] })).await,
        (Method::Post, ["orgs", org, "adjustments"]) => ask(org, "credit", json!({ "kind": "adjust", "credits": body["credits"], "reference": body["reference"], "note": body["note"] })).await,
        (Method::Post, ["orgs", org, "projects"]) => ask(org, "create_project", json!({ "name": body["name"], "monthly_limit": body["monthly_limit"] })).await,
        (Method::Post, ["orgs", org, "projects", project, "limit"]) => ask(org, "set_limit", json!({ "project": project, "monthly_limit": body["monthly_limit"], "touched": true })).await,
        (Method::Post, ["orgs", org, "members"]) => ask(org, "set_member", json!({ "user": body["user"], "role": body["role"], "status": body["status"] })).await,
        (Method::Post, ["orgs", org, "models"]) => ask(org, "set_model_access", json!({ "on": body["access"] })).await,
        (Method::Post, ["orgs", org, "keys"]) => {
            ask(org, "create_key", json!({ "project": body["project"], "environment": body["environment"], "name": body["name"], "scopes": body["scopes"],
                "expires_days": body["expires_days"], "owner": body["owner"], "by": "owner", "touched": true })).await
        }
        (Method::Post, ["orgs", org, "keys", key, "owner"]) => ask(org, "bind_key", json!({ "key": key, "user": body["user"], "by": "owner" })).await,
        (Method::Post, ["orgs", org, "keys", key, "revoke"]) => ask(org, "revoke_key", json!({ "key": key, "touched": true })).await,
        (Method::Get, ["users", user]) => person(user, "recent").await,
        (Method::Post, ["users", user, "suspend"]) => person(user, "suspend").await,
        (Method::Post, ["users", user, "restore"]) => person(user, "restore").await,
        _ => Err(refusal(404, "not_found", "path", "no such endpoint")),
    };
    match result {
        Ok(v) => ok(v),
        Err(r) => refuse(rid, &r),
    }
}
