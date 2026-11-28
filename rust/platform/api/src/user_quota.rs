//! `UserQuota` — one Durable Object a registered person, named `user-quota:<user_id>`: their daily allowance of
//! executions and the record of each (tao_platform::quota).  It has no route: the API Worker reaches it once a key's
//! `Account` has said whose the key is, and the console Worker (through a binding to this class, `script_name`) for the
//! person whose session asks.  JSON over `POST https://do/<op>`, as `Account`.
//!
//! The name never holds a day, a model, a project or a key: each of those would be a second allowance.  The class is
//! never renamed for the same reason — a new namespace would be a fresh allowance for everyone.

use serde_json::{Value as Json, json};
use tao_edge::{DoSql, json as answer, now};
use tao_platform::accounts::{Error, Outcome};
use tao_platform::quota::{Admission, Admit, Completion, QuotaConfig, QuotaCore};
use worker::{DurableObject, Env, Request, Response, Result, State, durable_object};

#[durable_object]
pub struct UserQuota {
    sql: DoSql,
    cfg: QuotaConfig,
}

fn s<'a>(v: &'a Json, k: &str) -> &'a str {
    v.get(k).and_then(Json::as_str).unwrap_or("")
}

fn opt_s<'a>(v: &'a Json, k: &str) -> Option<&'a str> {
    v.get(k).and_then(Json::as_str).filter(|x| !x.is_empty())
}

impl DurableObject for UserQuota {
    fn new(state: State, env: Env) -> Self {
        let cfg = QuotaConfig::from_vars(|k| tao_edge::var(&env, k));
        UserQuota { sql: DoSql(state.storage().sql()), cfg }
    }

    async fn fetch(&self, mut req: Request) -> Result<Response> {
        let op = req.path().trim_start_matches('/').to_string();
        let body: Json = serde_json::from_slice(&req.bytes().await?).unwrap_or(Json::Null);
        // from here on, nothing is awaited: one step
        let t = now();
        let core = QuotaCore::new(&self.sql, &self.cfg);
        match run(&core, &op, &body, t) {
            Ok(v) => answer(200, &v, &[]),
            Err(Error::Refused(r)) => {
                // a refusal carries the day's allowance as it stands, for the caller's headers
                let quota = core.ensure().ok().and_then(|_| core.limits(t).ok()).unwrap_or(Json::Null);
                answer(
                    200,
                    &json!({ "refused": { "status": r.status, "type": r.kind, "code": r.code, "message": r.message, "retry": r.retry },
                        "quota": quota }),
                    &[],
                )
            }
            Err(Error::Storage(e)) => {
                worker::console_error!("user quota storage {op}: {e}");
                answer(500, &json!({ "error": "storage" }), &[])
            }
        }
    }
}

fn run(core: &QuotaCore, op: &str, b: &Json, t: i64) -> Outcome<Json> {
    match op {
        "admit" => {
            let a = Admit {
                request_id: s(b, "request_id"),
                org: s(b, "org"),
                project: s(b, "project"),
                env: s(b, "env"),
                product: s(b, "product"),
                model: opt_s(b, "model"),
                idem: opt_s(b, "idem"),
                request_hash: s(b, "request_hash"),
                lease_ms: b.get("lease_ms").and_then(Json::as_i64).unwrap_or(240_000),
            };
            Ok(match core.admit(&a, t)? {
                Admission::Admitted(q) => json!({ "admitted": q.to_json() }),
                Admission::Replay { request_id, status, body, quota } => {
                    json!({ "replay": { "request_id": request_id, "status": status, "body": body }, "quota": quota.to_json() })
                }
            })
        }
        "release" => Ok(json!({ "released": core.release(s(b, "request_id"), t)? })),
        "complete" => {
            let response = match (b.get("response_status").and_then(Json::as_u64), opt_s(b, "response")) {
                (Some(st), Some(body)) => Some((st as u16, body)),
                _ => None,
            };
            let c = Completion {
                outcome: s(b, "outcome"),
                http_status: b.get("http_status").and_then(Json::as_u64).unwrap_or(0) as u16,
                code: opt_s(b, "code"),
                input_tokens: b.get("input_tokens").and_then(Json::as_i64),
                output_tokens: b.get("output_tokens").and_then(Json::as_i64),
                streamed: b.get("streamed") == Some(&Json::Bool(true)),
                response,
            };
            Ok(json!({ "completed": core.complete(s(b, "request_id"), &c, t)? }))
        }
        "status" => Ok(json!({ "request": core.status(s(b, "request_id"), s(b, "org"), t)? })),
        "limits" => Ok(core.limits(t)?),
        "recent" => Ok(
            json!({ "quota": core.limits(t)?, "requests": core.recent(b.get("n").and_then(Json::as_i64).unwrap_or(20), t)? }),
        ),
        "suspend" | "restore" => {
            core.ensure()?;
            core.set_suspended(op == "suspend", opt_s(b, "by").unwrap_or("owner"), t)?;
            Ok(core.limits(t)?)
        }
        _ => Err(tao_platform::accounts::refused(404, "not_found", "op", "no such operation")),
    }
}
