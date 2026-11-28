//! `Account` — one Durable Object an organisation, named by its id: its keys, its credits, its calls in flight
//! (tao_platform::accounts).  It has no route: the API Worker reaches it, and the console Worker through a binding to
//! this class (`script_name`).  Its protocol is JSON over `POST https://do/<op>`; whoever calls has already decided who
//! may ask (the gateway: the key's digest, which the object itself checks; the owner: the admin token; the console:
//! a session and its membership).
//!
//! The request is read whole before anything is decided; then the core runs — synchronous, so nothing else runs in
//! this object until it has written what it decided.

use serde_json::{Value as Json, json};
use tao_edge::{DoSql, JsEntropy, json as answer, now};
use tao_platform::accounts::{
    AccountConfig, AccountCore, Authorize, Authorized, Error, Idem, Outcome, Product, Settled, refused,
};
use tao_platform::keys::KeyEnv;
use worker::{DurableObject, Env, Request, Response, Result, State, durable_object};

#[durable_object]
pub struct Account {
    sql: DoSql,
    cfg: AccountConfig,
}

fn s<'a>(v: &'a Json, k: &str) -> &'a str {
    v.get(k).and_then(Json::as_str).unwrap_or("")
}

/// Did the caller say a passkey touched its session lately (the console), or is it the owner (the admin token)?
fn touched(v: &Json) -> bool {
    v.get("touched") == Some(&Json::Bool(true))
}

/// A monthly limit: absent or null for none, a whole number of credits — anything else is refused, never read as none.
fn limit(v: &Json) -> Outcome<Option<i64>> {
    match v.get("monthly_limit") {
        None | Some(Json::Null) => Ok(None),
        Some(n) => n.as_i64().map(Some).ok_or_else(|| {
            refused(400, "invalid_request", "limit", "monthly_limit is a whole number of credits, or null")
        }),
    }
}

fn opt_s<'a>(v: &'a Json, k: &str) -> Option<&'a str> {
    v.get(k).and_then(Json::as_str).filter(|x| !x.is_empty())
}

impl DurableObject for Account {
    fn new(state: State, env: Env) -> Self {
        let cfg = AccountConfig::from_vars(|k| tao_edge::var(&env, k));
        Account { sql: DoSql(state.storage().sql()), cfg }
    }

    async fn fetch(&self, mut req: Request) -> Result<Response> {
        let op = req.path().trim_start_matches('/').to_string();
        let body: Json = serde_json::from_slice(&req.bytes().await?).unwrap_or(Json::Null);
        // from here on, nothing is awaited: one step
        let t = now();
        let core = AccountCore::new(&self.sql, &self.cfg);
        match self.run(&core, &op, &body, t) {
            Ok(v) => answer(200, &v, &[]),
            Err(Error::Refused(r)) => answer(
                200,
                &json!({ "refused": { "status": r.status, "type": r.kind, "code": r.code, "message": r.message, "retry": r.retry } }),
                &[],
            ),
            Err(Error::Storage(e)) => {
                worker::console_error!("account storage {op}: {e}");
                answer(500, &json!({ "error": "storage" }), &[])
            }
        }
    }
}

impl Account {
    fn run(&self, core: &AccountCore, op: &str, b: &Json, t: i64) -> Outcome<Json> {
        if op == "provision" {
            return core.provision(s(b, "org"), s(b, "name"), &JsEntropy, t);
        }
        // an object never provisioned answers and writes nothing (accounts.rs: ready)
        if !core.ready()? {
            return Err(match op {
                "authorize" | "limits" | "usage" => {
                    refused(401, "authentication", "invalid_key", "the API key is not valid")
                }
                _ => refused(404, "not_found", "org", "no such organisation"),
            });
        }
        core.sweep(t)?;
        match op {
            "authorize" => {
                let product = Product::parse(s(b, "product"))
                    .ok_or_else(|| refused(400, "invalid_request", "product", "no such product"))?;
                let idem = opt_s(b, "idem_key").map(|key| Idem { key, request: s(b, "idem_request") });
                let a = Authorize { digest: s(b, "digest"), product, request_id: s(b, "request_id"), idem };
                Ok(match core.authorize(&a, t)? {
                    Authorized::Go { reservation, key_id, project_id, env, credits, price_version } => json!({ "go": {
                        "reservation": reservation, "key": key_id, "project": project_id, "environment": env.as_str(),
                        "credits": credits, "price_version": price_version } }),
                    Authorized::Replay { status, body } => json!({ "replay": { "status": status, "body": body } }),
                })
            }
            "settle" => {
                let delivered = b.get("delivered").filter(|d| d.is_object());
                let d = delivered.map(|d| (d.get("status").and_then(Json::as_u64).unwrap_or(200) as u16, s(d, "body")));
                let out = core.settle(s(b, "reservation"), d, t)?;
                Ok(json!({ "settled": match out {
                    Settled::Charged(n) => format!("charged:{n}"),
                    Settled::Released => "released".into(),
                    Settled::Already(state) => format!("already:{state}"),
                    Settled::Unknown => "unknown".into(),
                } }))
            }
            "limits" => core.limits(s(b, "digest"), t),
            "usage" => {
                let key = core.authenticate(s(b, "digest"), t)?;
                if !AccountCore::has_scope(&key, "usage:read") {
                    return Err(refused(403, "permission", "scope", "this key may not read usage"));
                }
                core.usage(s(b, "from"), s(b, "to"), Some(&key.text("project_id")))
            }
            // the owner's and the console's (the console has checked that its person is a member)
            "summary" => core.summary(t),
            "org_usage" => core.usage(s(b, "from"), s(b, "to"), opt_s(b, "project")),
            "credit" => {
                let credits = b.get("credits").and_then(Json::as_i64).unwrap_or(0);
                let added = core.credit(s(b, "kind"), credits, s(b, "reference"), s(b, "note"), t)?;
                Ok(json!({ "added": added, "credits": core.balance()? }))
            }
            "create_project" => {
                let id = core.create_project(s(b, "name"), limit(b)?, &JsEntropy, t)?;
                Ok(json!({ "project": id }))
            }
            "set_limit" => {
                core.set_limit(s(b, "project"), limit(b)?, touched(b))?;
                Ok(json!({ "ok": true }))
            }
            "create_key" => {
                let env = KeyEnv::parse(s(b, "environment"))
                    .ok_or_else(|| refused(400, "invalid_request", "environment", "environment is live or test"))?;
                // scopes: none named, all of them; a list, exactly it (an empty one is refused by the core); anything
                // else refused — a value that is not what it should be is never read as the widest it could be
                let scopes: Option<Vec<String>> = match b.get("scopes") {
                    None | Some(Json::Null) => None,
                    Some(Json::Array(a)) if a.iter().all(Json::is_string) => {
                        Some(a.iter().filter_map(|x| x.as_str().map(String::from)).collect())
                    }
                    Some(_) => return Err(refused(400, "invalid_request", "scope", "scopes is a list of scope names")),
                };
                let expires = match b.get("expires_days") {
                    None | Some(Json::Null) => None,
                    Some(d) => match d.as_i64().filter(|d| (1..=3650).contains(d)) {
                        Some(d) => Some(t + d * 86_400_000),
                        None => {
                            return Err(refused(
                                400,
                                "invalid_request",
                                "expires",
                                "expires_days is a whole number from 1 to 3650",
                            ));
                        }
                    },
                };
                let (id, key) = core.create_key(
                    opt_s(b, "project"),
                    env,
                    s(b, "name"),
                    scopes.as_deref(),
                    expires,
                    s(b, "by"),
                    touched(b),
                    &JsEntropy,
                    t,
                )?;
                Ok(json!({ "id": id, "key": key.key, "shown": key.shown, "environment": env.as_str() }))
            }
            "revoke_key" => Ok(json!({ "revoked": core.revoke_key(s(b, "key"), touched(b), t)? })),
            "keys" => Ok(json!({ "keys": core.keys()? })),
            _ => Err(refused(404, "not_found", "op", "no such operation")),
        }
    }
}
