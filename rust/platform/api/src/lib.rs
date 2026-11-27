//! api.impf.ai — 道乃久开发者接口 (docs/adr/0038-accounts-keys-and-credits.md; cloud/api/README.md).
//!
//!   POST /v1/evidence/search      a search of the classics (classics.search on the full corpus)
//!   POST /v1/citations/verify     a quotation found, or not, where it is said to be (validation.verify_quote)
//!   GET  /v1/limits               what this key may do now, and what it costs
//!   GET  /v1/usage?from=&to=      this key's project's usage by day (scope usage:read)
//!   GET  /v1                      the service: its products and their prices
//!   …/admin/…                     the owner's: organisations, keys, credits (Bearer the token whose SHA-256 is
//!                                 ADMIN_TOKEN_SHA256; off without it)
//!
//! Every paid call: the key read (its checksum, then the organisation's object it names), its price reserved in that
//! object in the same step that checks the key, the corpus asked (through the corpus Worker's service binding, with a
//! time limit inside the reservation's), and the reservation settled — charged only when the tool ran.  The edge's own
//! rate limits (per address, per key) stand before the object; the object's own (per key a minute, in flight, credits)
//! are exact.  No CORS: a key belongs on a server, not in a page.

mod account;

pub use account::Account;

use std::time::Duration;

use futures_util::future::{Either, select};
use serde_json::{Value as Json, json};
use tao_edge::{JsEntropy, call, json as answer, now, var};
use tao_platform::accounts::{Product, Refusal};
use tao_platform::api::{self, Corpus};
use tao_platform::crypto::{digest, new_id, same};
use tao_platform::keys::{self, ParsedKey};
use worker::{Context, Delay, Env, Headers, Method, Request, RequestInit, Response, Result, Stub, event};

const VERSION: &str = "2026-11-27";

fn refusal(status: u16, kind: &'static str, code: &'static str, message: impl Into<String>) -> Refusal {
    Refusal { status, kind, code, message: message.into(), retry: None }
}

fn refuse(rid: &str, r: &Refusal) -> Result<Response> {
    let mut extra = vec![("X-Request-Id", rid.to_string())];
    if let Some(s) = r.retry {
        extra.push(("Retry-After", s.to_string()));
    }
    answer(r.status, &api::error(rid, r), &extra)
}

/// A refusal the Account object sent back: `{refused: {status, type, code, message, retry}}`.
fn object_refusal(v: &Json) -> Option<Refusal> {
    let r = v.get("refused")?;
    let kind = match r.get("type").and_then(Json::as_str).unwrap_or("") {
        "authentication" => "authentication",
        "permission" => "permission",
        "rate_limit" => "rate_limit",
        "insufficient_credits" => "insufficient_credits",
        "not_found" => "not_found",
        "conflict" => "conflict",
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

/// The codes the object may answer with, as static words (an unknown one is "refused").
fn leak_code(c: &str) -> &'static str {
    const CODES: &[&str] = &[
        "invalid_key",
        "revoked_key",
        "expired_key",
        "org_disabled",
        "scope",
        "project_archived",
        "idempotency_key",
        "idempotency_mismatch",
        "idempotency_unavailable",
        "idempotency_in_progress",
        "rate",
        "concurrency",
        "test_allowance",
        "credits",
        "project_limit",
        "org",
        "project",
        "name",
        "scope",
        "expires",
        "keys",
        "projects",
        "credits",
        "reference",
        "limit",
        "environment",
        "product",
        "op",
        "key",
        "days",
    ];
    CODES.iter().copied().find(|k| *k == c).unwrap_or("refused")
}

fn account(env: &Env, org: &str) -> Result<Stub> {
    env.durable_object("ACCOUNT")?.id_from_name(org)?.get_stub()
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
async fn fetch(req: Request, env: Env, _ctx: Context) -> Result<Response> {
    let rid = new_id(&JsEntropy, "req", 16);
    match route(req, &env, &rid).await {
        Ok(r) => Ok(r),
        Err(e) => {
            worker::console_error!("api {rid}: {e}"); // never a key, never a body
            refuse(
                &rid,
                &refusal(500, "internal", "internal", "the service failed; nothing was charged that did not run"),
            )
        }
    }
}

async fn route(mut req: Request, env: &Env, rid: &str) -> Result<Response> {
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
        (Method::Post, "/v1/evidence/search") => product(&mut req, env, rid, Product::Search).await,
        (Method::Post, "/v1/citations/verify") => product(&mut req, env, rid, Product::Verify).await,
        (Method::Get, "/v1/limits") => read(&req, env, rid, "limits").await,
        (Method::Get, "/v1/usage") => read(&req, env, rid, "usage").await,
        (_, p) if p.starts_with("/admin/") => admin(&mut req, env, rid).await,
        (_, "/v1/evidence/search" | "/v1/citations/verify" | "/v1/limits" | "/v1/usage") => {
            refuse(rid, &refusal(405, "invalid_request", "method", "this path takes another method"))
        }
        _ => refuse(rid, &refusal(404, "not_found", "path", "no such endpoint")),
    }
}

fn service(env: &Env) -> Json {
    let cfg = tao_platform::accounts::AccountConfig::from_vars(|k| var(env, k));
    json!({
        "service": "TaoChronos API", "version": VERSION,
        "products": {
            "evidence.search": { "path": "/v1/evidence/search", "credits": cfg.price_search },
            "citations.verify": { "path": "/v1/citations/verify", "credits": cfg.price_verify },
        },
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

async fn read(req: &Request, env: &Env, rid: &str, op: &str) -> Result<Response> {
    let key = match key_of(req, env, rid).await {
        Ok(k) => k,
        Err(r) => return r,
    };
    let url = req.url()?;
    let q = |name: &str| url.query_pairs().find(|(k, _)| k == name).map(|(_, v)| v.into_owned());
    let today = tao_platform::time::day(now());
    let body = json!({ "digest": key.digest, "from": q("from").unwrap_or_else(|| today.clone()), "to": q("to").unwrap_or(today) });
    let (status, out) = call(&account(env, &key.org)?, op, &body).await?;
    if let Some(r) = object_refusal(&out) {
        return refuse(rid, &r);
    }
    if status != 200 {
        return refuse(rid, &refusal(503, "unavailable", "accounts", "the accounts could not be read; try again"));
    }
    answer(200, &json!({ "id": rid, "object": op, "data": out }), &[("X-Request-Id", rid.to_string())])
}

/// A paid call, from its key to its settlement.
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
    // nothing is reserved for a call that cannot be made
    let Ok(corpus) = env.service("CORPUS") else {
        return refuse(
            rid,
            &Refusal {
                retry: Some(60),
                ..refusal(503, "unavailable", "corpus", "the full corpus is not deployed here")
            },
        );
    };
    let idem = req.headers().get("Idempotency-Key")?;
    let stub = account(env, &key.org)?;
    let (status, out) = call(
        &stub,
        "authorize",
        &json!({
            "digest": key.digest, "product": product.name(), "request_id": rid,
            "idem_key": idem, "idem_request": api::request_digest(&call_),
        }),
    )
    .await?;
    if let Some(r) = object_refusal(&out) {
        return refuse(rid, &r);
    }
    if status != 200 {
        // the object could not be asked: nothing was reserved, and nothing is let through unchecked
        return refuse(
            rid,
            &Refusal {
                retry: Some(5),
                ..refusal(503, "unavailable", "accounts", "the accounts could not be asked; try again")
            },
        );
    }
    if let Some(replay) = out.get("replay") {
        let status = replay.get("status").and_then(Json::as_u64).unwrap_or(200) as u16;
        let body: Json =
            serde_json::from_str(replay.get("body").and_then(Json::as_str).unwrap_or("null")).unwrap_or(Json::Null);
        return answer(status, &body, &[("X-Request-Id", rid.to_string()), ("Idempotent-Replayed", "true".into())]);
    }
    let go = &out["go"];
    let reservation = go["reservation"].as_str().unwrap_or(rid).to_string();
    // the corpus, within a time the reservation outlasts
    let secs = var(env, "CORPUS_TIMEOUT_SECONDS")
        .and_then(|v| v.parse::<u64>().ok())
        .filter(|s| (5..=90).contains(s))
        .unwrap_or(60);
    let headers = Headers::new();
    headers.set("Content-Type", "application/json")?;
    headers.set("Accept", "application/json")?;
    let mut init = RequestInit::new();
    init.with_method(Method::Post).with_headers(headers).with_body(Some(api::corpus_body(&call_).to_string().into()));
    let asked = Request::new_with_init("https://corpus.internal/api/call", &init)?;
    let outcome =
        match select(Box::pin(corpus.fetch_request(asked)), Box::pin(Delay::from(Duration::from_secs(secs)))).await {
            Either::Left((Ok(mut res), _)) => {
                let status = res.status_code();
                let retry = res.headers().get("Retry-After")?;
                let text = res.text().await.unwrap_or_default();
                api::read_corpus(status, &text, retry.as_deref())
            }
            Either::Left((Err(e), _)) => {
                worker::console_error!("api {rid}: corpus {e}");
                Corpus::Failed
            }
            Either::Right(_) => Corpus::Unavailable(10),
        };
    // what the caller is told, and whether the call is charged: only a tool that ran
    let (refused, body) = match outcome {
        Corpus::Delivered(data) => {
            let credits = go["credits"].as_i64().unwrap_or(0);
            let env_ = go["environment"].as_str().unwrap_or("");
            (None, api::success(rid, product, now(), data, credits, env_, go["price_version"].as_str().unwrap_or("")))
        }
        Corpus::Refused(msg) => (Some(refusal(422, "invalid_request", "tool_refused", msg)), Json::Null),
        Corpus::Unavailable(s) => {
            let r = Refusal {
                retry: Some(s),
                ..refusal(503, "unavailable", "corpus", "the corpus is starting or busy; try again")
            };
            (Some(r), Json::Null)
        }
        Corpus::Failed => {
            (Some(refusal(502, "unavailable", "corpus", "the corpus failed; nothing was charged")), Json::Null)
        }
    };
    let delivered = match &refused {
        None => json!({ "status": 200, "body": body.to_string() }),
        Some(_) => Json::Null,
    };
    if let Err(e) = call(&stub, "settle", &json!({ "reservation": reservation, "delivered": delivered })).await {
        // not settled: the reservation lapses unsettled — released, not charged (accounts.rs)
        worker::console_error!("api {rid}: settle {e}");
    }
    match refused {
        None => answer(200, &body, &[("X-Request-Id", rid.to_string())]),
        Some(r) => refuse(rid, &r),
    }
}

// ------------------------------------------------------------------ the owner's
/// The owner's endpoints, behind the token whose SHA-256 is ADMIN_TOKEN_SHA256 (the token itself is kept nowhere here).
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
    let result = match (method, parts.as_slice()) {
        (Method::Post, ["orgs"]) => {
            let org = new_id(&JsEntropy, "org", 16);
            ask(&org, "provision", json!({ "org": org, "name": body["name"] })).await
        }
        (Method::Get, ["orgs", org]) => ask(org, "summary", json!({})).await,
        (Method::Post, ["orgs", org, "grants"]) => ask(org, "credit", json!({ "kind": "grant", "credits": body["credits"], "reference": body["reference"], "note": body["note"] })).await,
        (Method::Post, ["orgs", org, "adjustments"]) => ask(org, "credit", json!({ "kind": "adjust", "credits": body["credits"], "reference": body["reference"], "note": body["note"] })).await,
        (Method::Post, ["orgs", org, "projects"]) => ask(org, "create_project", json!({ "name": body["name"], "monthly_limit": body["monthly_limit"] })).await,
        (Method::Post, ["orgs", org, "projects", project, "limit"]) => ask(org, "set_limit", json!({ "project": project, "monthly_limit": body["monthly_limit"] })).await,
        (Method::Post, ["orgs", org, "keys"]) => {
            ask(org, "create_key", json!({ "project": body["project"], "environment": body["environment"], "name": body["name"], "scopes": body["scopes"],
                "expires_days": body["expires_days"], "by": "owner" })).await
        }
        (Method::Post, ["orgs", org, "keys", key, "revoke"]) => ask(org, "revoke_key", json!({ "key": key })).await,
        _ => Err(refusal(404, "not_found", "path", "no such endpoint")),
    };
    match result {
        Ok(v) => ok(v),
        Err(r) => refuse(rid, &r),
    }
}
