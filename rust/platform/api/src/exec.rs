//! The admission every execution goes through — a model's chat, an evidence search, a citation check — and its end
//! (docs/adr/0039-model-relay-and-daily-allowance.md):
//!
//!   1. the key's organisation (`Account`): the key, its scope, its owner (a registered person, an active member), its
//!      rate, what it and the organisation have in flight — a lease taken;
//!   2. the owner's daily allowance (`UserQuota`): a repeat of an `Idempotency-Key` answered from before, the person's
//!      own call in flight, the day's count — the request admitted, and counted;
//!   3. the call made; its end told to both: the allowance's record (or the request released, when nothing was asked of
//!      any service), then the organisation's usage.
//!
//! A refusal at 2 gives the lease of 1 back.  The allowance is asked second because only the organisation knows whose
//! the key is; nothing is asked of a service before both have let the request through.

use serde_json::{Value as Json, json};
use tao_edge::{call, json as answer};
use tao_platform::accounts::{Product, Refusal};
use tao_platform::models::ModelSpec;
use worker::{Env, Response, Result, Stub};

use crate::{object_refusal, refusal, refuse_with};

pub fn account(env: &Env, org: &str) -> Result<Stub> {
    env.durable_object("ACCOUNT")?.id_from_name(org)?.get_stub()
}

/// A person's allowance object: its name is theirs alone — no day, model, project or key in it.
pub fn user_quota(env: &Env, user: &str) -> Result<Stub> {
    env.durable_object("USER_QUOTA")?.id_from_name(&format!("user-quota:{user}"))?.get_stub()
}

/// An execution to admit.
pub struct Exec<'a> {
    pub rid: &'a str,
    pub org: &'a str,
    pub digest: &'a str,
    pub product: Product,
    pub model: Option<&'static ModelSpec>,
    pub request_hash: String,
    pub idem: Option<String>,
    /// how long the call may run before its lease lapses (and its outcome is unknown)
    pub hold_ms: i64,
    /// the model gate's word (MODEL_API)
    pub models: &'a str,
}

/// An execution let through.
#[derive(Debug, Clone)]
pub struct Admitted {
    pub rid: String,
    pub org: String,
    pub lease: String,
    pub owner: String,
    pub project: String,
    pub env: String,
    pub credits: i64,
    pub price_version: String,
    /// the owner's allowance once this request was counted
    pub quota: Json,
}

pub enum Gate {
    Go(Admitted),
    /// answered without running: a refusal, or a repeat answered from before
    Done(Response),
}

/// How an execution ended.
#[derive(Debug, Clone)]
pub struct End {
    /// asked of the service (or of unknown outcome): it spent the allowance
    pub executed: bool,
    /// and answered
    pub ok: bool,
    /// succeeded, failed or cancelled
    pub outcome: &'static str,
    pub http_status: u16,
    pub code: Option<String>,
    pub input_tokens: Option<i64>,
    pub output_tokens: Option<i64>,
    pub streamed: bool,
    /// the answer as given, for a repeat of its Idempotency-Key
    pub response: Option<(u16, String)>,
}

impl End {
    /// Nothing was asked of any service: released, not counted.
    pub fn released(http_status: u16, code: &str) -> End {
        End {
            executed: false,
            ok: false,
            outcome: "failed",
            http_status,
            code: Some(code.into()),
            input_tokens: None,
            output_tokens: None,
            streamed: false,
            response: None,
        }
    }

    pub fn failed(http_status: u16, code: &str, response: Option<(u16, String)>) -> End {
        End { executed: true, outcome: "failed", ..End::released(http_status, code) }.with_response(response)
    }

    pub fn succeeded(response: Option<(u16, String)>) -> End {
        End { executed: true, ok: true, outcome: "succeeded", code: None, ..End::released(200, "") }
            .with_response(response)
    }

    fn with_response(mut self, response: Option<(u16, String)>) -> End {
        self.response = response;
        self
    }
}

/// The allowance's headers: what a caller may still run today, and when it renews.  `released`: this request was
/// counted and then given back.
pub fn quota_headers(q: &Json, released: bool) -> Vec<(&'static str, String)> {
    let Some(limit) = q.get("limit").and_then(Json::as_i64) else { return Vec::new() };
    let remaining = (q.get("remaining").and_then(Json::as_i64).unwrap_or(0) + i64::from(released)).min(limit).max(0);
    vec![
        ("X-Tao-Quota-Limit", limit.to_string()),
        ("X-Tao-Quota-Remaining", remaining.to_string()),
        ("X-Tao-Quota-Reset", q.get("reset").and_then(Json::as_i64).unwrap_or(0).to_string()),
    ]
}

fn unavailable(rid: &str, what: &'static str, message: &str) -> Result<Response> {
    refuse_with(rid, &Refusal { retry: Some(5), ..refusal(503, "unavailable", what, message) }, &[])
}

/// Steps 1 and 2 of the module's comment.
pub async fn admit(env: &Env, ex: &Exec<'_>) -> Result<Gate> {
    let stub = account(env, ex.org)?;
    let asked = json!({ "digest": ex.digest, "product": ex.product.name(), "request_id": ex.rid, "hold_ms": ex.hold_ms, "models": ex.models });
    let (status, out) = match call(&stub, "admit", &asked).await {
        Ok(r) => r,
        Err(e) => {
            worker::console_error!("api {}: accounts {e}", ex.rid);
            return Ok(Gate::Done(unavailable(
                ex.rid,
                "accounts",
                "the accounts could not be asked; nothing was counted — try again",
            )?));
        }
    };
    if let Some(r) = object_refusal(&out) {
        return Ok(Gate::Done(refuse_with(ex.rid, &r, &[])?));
    }
    if status != 200 {
        return Ok(Gate::Done(unavailable(
            ex.rid,
            "accounts",
            "the accounts could not be asked; nothing was counted — try again",
        )?));
    }
    let text = |k: &str| out.get(k).and_then(Json::as_str).unwrap_or("").to_string();
    let mut a = Admitted {
        rid: ex.rid.to_string(),
        org: ex.org.to_string(),
        lease: text("lease"),
        owner: text("owner"),
        project: text("project"),
        env: text("environment"),
        credits: out.get("credits").and_then(Json::as_i64).unwrap_or(0),
        price_version: text("price_version"),
        quota: Json::Null,
    };
    let give_back = |refused: bool| {
        let stub = &stub;
        let lease = a.lease.clone();
        async move {
            if let Err(e) =
                call(stub, "finish", &json!({ "lease": lease, "executed": false, "refused": refused })).await
            {
                worker::console_error!("api: lease {lease} {e}"); // it lapses
            }
        }
    };
    let q = match user_quota(env, &a.owner) {
        Ok(q) => q,
        Err(e) => {
            worker::console_error!("api {}: user quota {e}", ex.rid);
            give_back(false).await;
            return Ok(Gate::Done(unavailable(
                ex.rid,
                "quota",
                "the daily allowance could not be asked; nothing was counted — try again",
            )?));
        }
    };
    let asked = json!({
        "request_id": ex.rid, "org": ex.org, "project": a.project, "env": a.env, "product": ex.product.name(),
        "model": ex.model.map(|m| m.id), "idem": ex.idem, "request_hash": ex.request_hash, "lease_ms": ex.hold_ms,
    });
    let (status, out) = match call(&q, "admit", &asked).await {
        Ok(r) => r,
        Err(e) => {
            worker::console_error!("api {}: user quota {e}", ex.rid);
            (503, Json::Null)
        }
    };
    if let Some(r) = object_refusal(&out) {
        let counted_refusal = matches!(r.code, "daily_quota_exceeded" | "user_concurrency");
        give_back(counted_refusal).await;
        let headers = quota_headers(&out["quota"], false);
        return Ok(Gate::Done(refuse_with(ex.rid, &r, &headers)?));
    }
    if status != 200 {
        give_back(false).await;
        return Ok(Gate::Done(unavailable(
            ex.rid,
            "quota",
            "the daily allowance could not be asked; nothing was counted — try again",
        )?));
    }
    if let Some(replay) = out.get("replay") {
        give_back(false).await;
        let status = replay.get("status").and_then(Json::as_u64).unwrap_or(200) as u16;
        let body: Json =
            serde_json::from_str(replay.get("body").and_then(Json::as_str).unwrap_or("null")).unwrap_or(Json::Null);
        let mut headers = vec![("X-Request-Id", ex.rid.to_string()), ("Idempotent-Replayed", "true".to_string())];
        headers.extend(quota_headers(&out["quota"], false));
        return Ok(Gate::Done(answer(status, &body, &headers)?));
    }
    a.quota = out.get("admitted").cloned().unwrap_or(Json::Null);
    Ok(Gate::Go(a))
}

/// Step 3: the end told to the allowance (its record, or the request released) and to the organisation (its usage,
/// its lease).  What fails here is logged: the caller has had their answer, and an untold end is safe — the request is
/// of unknown outcome and counted, the lease lapses and charges nothing.
pub async fn end(env: &Env, a: &Admitted, e: &End) {
    let quota = match user_quota(env, &a.owner) {
        Ok(q) => {
            let (op, body) = if e.executed {
                (
                    "complete",
                    json!({
                        "request_id": a.rid, "outcome": e.outcome, "http_status": e.http_status, "code": e.code,
                        "input_tokens": e.input_tokens, "output_tokens": e.output_tokens, "streamed": e.streamed,
                        "response_status": e.response.as_ref().map(|(s, _)| *s), "response": e.response.as_ref().map(|(_, b)| b.as_str()),
                    }),
                )
            } else {
                ("release", json!({ "request_id": a.rid }))
            };
            call(&q, op, &body).await.map(|_| ())
        }
        Err(err) => Err(err),
    };
    if let Err(err) = quota {
        worker::console_error!("api {}: user quota end {err}", a.rid);
    }
    let finish = json!({
        "lease": a.lease, "executed": e.executed, "ok": e.ok, "refused": false,
        "input_tokens": e.input_tokens.unwrap_or(0), "output_tokens": e.output_tokens.unwrap_or(0),
    });
    match account(env, &a.org) {
        Ok(stub) => {
            if let Err(err) = call(&stub, "finish", &finish).await {
                worker::console_error!("api {}: finish {err}", a.rid); // the lease lapses: released, not charged
            }
        }
        Err(err) => worker::console_error!("api {}: finish {err}", a.rid),
    }
}
