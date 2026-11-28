//! 每日额度 — one registered person's daily allowance of execution requests: a model's chat, an evidence search, a
//! citation check, whichever keys, projects, organisations or models they come through.  One Durable Object a person
//! (the API Worker's `UserQuota`, named `user-quota:<user_id>`), so that their admissions are one sequence: two
//! requests arriving together cannot both take the last call (docs/adr/0039-model-relay-and-daily-allowance.md).
//!
//! A request is **admitted** before it runs: the person not suspended, an `Idempotency-Key` seen before answered from
//! what it was, fewer than `concurrency` of theirs in flight, fewer than `daily_limit` admitted this UTC day.  Admitted,
//! it counts — whatever then happens to it, unless the service it was sent to says that it ran nothing (`release`: the
//! gateway's or the provider's refusal before anything ran, a corpus tool refusing its arguments before it ran, a
//! corpus never sent the call), and says so while the request's lease runs.  A request that never reports its end
//! stays admitted until its lease passes, and is then of unknown outcome: counted, never taken back by a late release,
//! never run again by a repeat of its key while keys name their requests.  Its day is the day it was admitted, and does
//! not change.
//!
//! Every method reads, decides and writes with no `await` in between, as the accounts' do: in a Durable Object that is
//! the transaction.  workers-rs has no `transactionSync`, so each step writes at most one row that matters — the
//! admission is one INSERT — and a storage failure between two writes leaves nothing inconsistent.

use serde_json::{Value as Json, json};

use crate::accounts::{Error, Outcome, Refusal, refused};
use crate::args;
use crate::sql::{Row, Sql, SqlError, SqlExt};
use crate::time::{DAY, day, to_midnight};

/// A response kept for an idempotent repeat: at most this many bytes (a larger one is not kept, and a repeat of it is
/// told so).
pub const MOST_RESPONSE: usize = 1_048_576;

#[derive(Debug, Clone)]
pub struct QuotaConfig {
    /// executions a person may be admitted each UTC day
    pub daily_limit: i64,
    /// executions of theirs in flight at once
    pub concurrency: i64,
    /// how long an `Idempotency-Key` names its request (and its kept response is replayed)
    pub replay_ms: i64,
    /// how long a request's record is kept for its status and the console's list (at least two days: today's count)
    pub keep_ms: i64,
}

impl QuotaConfig {
    pub fn from_vars(get: impl Fn(&str) -> Option<String>) -> Self {
        let num = |k: &str, default: i64, least: i64, most: i64| {
            get(k).and_then(|v| v.trim().parse::<i64>().ok()).filter(|v| (least..=most).contains(v)).unwrap_or(default)
        };
        let replay_ms = num("IDEMPOTENCY_HOURS", 24, 1, 720) * 3_600_000;
        QuotaConfig {
            daily_limit: num("DAILY_REQUEST_LIMIT", 5, 0, 100_000),
            concurrency: num("USER_EXECUTION_CONCURRENCY", 1, 1, 100),
            replay_ms,
            // a record outlives the time its Idempotency-Key names it, by a day at least: a key that outlived its record
            // would run its request again
            keep_ms: (num("REQUEST_RECORD_DAYS", 7, 2, 90) * DAY).max(replay_ms + DAY),
        }
    }
}

const SCHEMA: &[&str] = &[
    "CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL)",
    // one row a request admitted: its context, its idempotency, its day, how it ended, and (for a repeat of its key)
    // its response while it is kept
    "CREATE TABLE IF NOT EXISTS ops (request_id TEXT PRIMARY KEY, org_id TEXT NOT NULL, project_id TEXT NOT NULL,
      env TEXT NOT NULL, product TEXT NOT NULL, model TEXT, idem TEXT, request_hash TEXT NOT NULL, day TEXT NOT NULL,
      state TEXT NOT NULL, created INTEGER NOT NULL, lease_until INTEGER NOT NULL, finished INTEGER, http_status INTEGER,
      code TEXT, input_tokens INTEGER, output_tokens INTEGER, streamed INTEGER NOT NULL DEFAULT 0, response TEXT,
      response_status INTEGER, response_until INTEGER)",
    // an Idempotency-Key names one request in its context — the person is the object's own
    "CREATE UNIQUE INDEX IF NOT EXISTS ops_idem ON ops (org_id, project_id, env, idem) WHERE idem IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ops_day ON ops (day, state)",
    "CREATE INDEX IF NOT EXISTS ops_live ON ops (state, lease_until)",
    "CREATE INDEX IF NOT EXISTS ops_created ON ops (created)",
];

const ADMITTED: &str = "admitted";
const RELEASED: &str = "released";

/// A request to admit.  Its id is the API's own (`req_…`), unique.
#[derive(Debug, Clone)]
pub struct Admit<'a> {
    pub request_id: &'a str,
    pub org: &'a str,
    pub project: &'a str,
    pub env: &'a str,
    pub product: &'a str,
    pub model: Option<&'a str>,
    /// the client's `Idempotency-Key`, as sent (checked by the API: 1–255 visible ASCII characters)
    pub idem: Option<&'a str>,
    /// what was asked, as a digest: the method, the path, the request as read, the model resolved
    pub request_hash: &'a str,
    /// how long the request may run before it is of unknown outcome
    pub lease_ms: i64,
}

/// The day's allowance as a caller is told it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct QuotaState {
    pub limit: i64,
    pub used: i64,
    pub in_flight: i64,
    pub remaining: i64,
    /// the next UTC midnight, in milliseconds
    pub reset_ms: i64,
}

impl QuotaState {
    pub fn to_json(&self) -> Json {
        json!({
            "limit": self.limit, "used": self.used, "in_flight": self.in_flight, "remaining": self.remaining,
            "timezone": "UTC", "reset_at": format!("{}T00:00:00Z", day(self.reset_ms)), "reset": self.reset_ms / 1000,
        })
    }
}

#[derive(Debug, Clone, PartialEq)]
pub enum Admission {
    /// counted: the request is to be run, then completed (or released if it was never asked of anyone)
    Admitted(QuotaState),
    /// the same request was admitted before and its answer is kept: this is it, and nothing is counted
    Replay { request_id: String, status: u16, body: String, quota: QuotaState },
}

/// How an admitted request ended.
#[derive(Debug, Clone)]
pub struct Completion<'a> {
    /// succeeded, failed or cancelled
    pub outcome: &'a str,
    pub http_status: u16,
    /// the error's code, when it failed
    pub code: Option<&'a str>,
    pub input_tokens: Option<i64>,
    pub output_tokens: Option<i64>,
    /// answered as a stream: its content is not kept, and a repeat of its key is told so
    pub streamed: bool,
    /// the answer as it was given (status, body), kept for a repeat of its key
    pub response: Option<(u16, &'a str)>,
}

pub struct QuotaCore<'a> {
    sql: &'a dyn Sql,
    pub cfg: &'a QuotaConfig,
}

fn midnight_after(now: i64) -> i64 {
    now - now.rem_euclid(DAY) + DAY
}

fn retry(e: Error, seconds: i64) -> Error {
    match e {
        Error::Refused(r) => Error::Refused(Refusal { retry: Some(seconds.max(1)), ..r }),
        other => other,
    }
}

impl<'a> QuotaCore<'a> {
    pub fn new(sql: &'a dyn Sql, cfg: &'a QuotaConfig) -> Self {
        QuotaCore { sql, cfg }
    }

    pub fn ensure(&self) -> Result<(), SqlError> {
        for s in SCHEMA {
            self.sql.run(s, &[])?;
        }
        Ok(())
    }

    fn meta(&self, k: &str) -> Result<Option<String>, SqlError> {
        Ok(self.sql.row("SELECT v FROM meta WHERE k = ?", args![k])?.map(|r| r.text("v")))
    }

    pub fn suspended(&self) -> Result<bool, SqlError> {
        Ok(self.meta("status")?.as_deref() == Some("suspended"))
    }

    /// The person's executions stopped, or let go on (the owner's endpoints; a console that disables a person).
    pub fn set_suspended(&self, suspended: bool, by: &str, now: i64) -> Result<(), SqlError> {
        let v = if suspended { "suspended" } else { "active" };
        self.sql.run(
            "INSERT INTO meta (k, v) VALUES ('status', ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v",
            args![v],
        )?;
        self.sql.run(
            "INSERT INTO meta (k, v) VALUES ('status_by', ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v",
            args![format!("{by}@{now}")],
        )
    }

    pub fn state(&self, now: i64) -> Result<QuotaState, SqlError> {
        let used =
            self.sql.scalar("SELECT COUNT(*) FROM ops WHERE day = ? AND state <> 'released'", args![day(now)])?;
        let in_flight =
            self.sql.scalar("SELECT COUNT(*) FROM ops WHERE state = 'admitted' AND lease_until > ?", args![now])?;
        Ok(QuotaState {
            limit: self.cfg.daily_limit,
            used,
            in_flight,
            remaining: (self.cfg.daily_limit - used).max(0),
            reset_ms: midnight_after(now),
        })
    }

    /// A request's admission, in one step (see the module's comment).
    pub fn admit(&self, a: &Admit, now: i64) -> Outcome<Admission> {
        self.ensure()?;
        self.prune(now)?;
        if self.suspended()? {
            return Err(refused(403, "permission", "user_suspended", "executions are suspended for this account"));
        }
        if let Some(idem) = a.idem
            && let Some(seen) = self.sql.row(
                "SELECT * FROM ops WHERE org_id = ? AND project_id = ? AND env = ? AND idem = ?",
                args![a.org, a.project, a.env, idem],
            )?
        {
            if seen.text("request_hash") != a.request_hash {
                return Err(refused(
                    422,
                    "invalid_request",
                    "idempotency_conflict",
                    "this Idempotency-Key was used for another request",
                ));
            }
            let state = seen.text("state");
            if state == ADMITTED {
                return Err(if seen.int("lease_until") > now {
                    retry(
                        refused(
                            409,
                            "conflict",
                            "request_in_progress",
                            "the request with this Idempotency-Key is still running",
                        ),
                        1,
                    )
                } else {
                    refused(
                        409,
                        "conflict",
                        "request_outcome_unknown",
                        format!(
                            "the request {} with this Idempotency-Key ended without a known outcome; it is not run again",
                            seen.text("request_id")
                        ),
                    )
                });
            }
            if let (Some(status), Some(body)) = (seen.opt_int("response_status"), seen.opt_text("response")) {
                return Ok(Admission::Replay {
                    request_id: seen.text("request_id"),
                    status: status as u16,
                    body,
                    quota: self.state(now)?,
                });
            }
            if seen.int("streamed") == 1 {
                return Err(refused(
                    409,
                    "conflict",
                    "stream_replay_unavailable",
                    format!(
                        "the request {} with this Idempotency-Key was answered as a stream, which is not kept",
                        seen.text("request_id")
                    ),
                ));
            }
            return Err(refused(
                409,
                "conflict",
                "idempotency_unavailable",
                format!("the answer to the request {} with this Idempotency-Key is not kept", seen.text("request_id")),
            ));
        }
        let q = self.state(now)?;
        if q.in_flight >= self.cfg.concurrency {
            return Err(retry(
                refused(
                    429,
                    "rate_limit",
                    "user_concurrency",
                    format!("at most {} of your requests run at once: wait for one to end", self.cfg.concurrency),
                ),
                1,
            ));
        }
        if q.used >= self.cfg.daily_limit {
            return Err(retry(
                refused(
                    429,
                    "rate_limit",
                    "daily_quota_exceeded",
                    format!(
                        "your daily allowance of {} requests is spent; it renews at 00:00 UTC",
                        self.cfg.daily_limit
                    ),
                ),
                to_midnight(now),
            ));
        }
        self.sql.run(
            "INSERT INTO ops (request_id, org_id, project_id, env, product, model, idem, request_hash, day, state, created, lease_until)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'admitted', ?, ?)",
            args![a.request_id, a.org, a.project, a.env, a.product, a.model, a.idem, a.request_hash, day(now), now, now + a.lease_ms.max(1)],
        )?;
        Ok(Admission::Admitted(QuotaState {
            used: q.used + 1,
            in_flight: q.in_flight + 1,
            remaining: (q.remaining - 1).max(0),
            ..q
        }))
    }

    /// An admitted request known never to have been asked of anyone: not counted, and its key free to be used again.
    /// Ok(false) when it was not in flight — ended before, not this object's, or its lease passed: a request reported
    /// of unknown outcome was counted, and a late word does not take that back.
    pub fn release(&self, request_id: &str, now: i64) -> Result<bool, SqlError> {
        let Some(op) = self.sql.row("SELECT state, lease_until FROM ops WHERE request_id = ?", args![request_id])?
        else {
            return Ok(false);
        };
        if op.text("state") != ADMITTED || op.int("lease_until") <= now {
            return Ok(false);
        }
        self.sql.run(
            "UPDATE ops SET state = 'released', idem = NULL, finished = ? WHERE request_id = ? AND state = 'admitted' AND lease_until > ?",
            args![now, request_id, now],
        )?;
        Ok(true)
    }

    /// An admitted request's end, once: later reports (and reports of a released one) change nothing.  A request whose
    /// lease passed is still told its end — it was counted all along.
    pub fn complete(&self, request_id: &str, c: &Completion, now: i64) -> Result<bool, SqlError> {
        let Some(op) = self.sql.row("SELECT state, idem FROM ops WHERE request_id = ?", args![request_id])? else {
            return Ok(false);
        };
        if op.text("state") != ADMITTED {
            return Ok(false);
        }
        let outcome = match c.outcome {
            "succeeded" | "failed" | "cancelled" => c.outcome,
            _ => "failed",
        };
        // a response is kept only for a repeat of its key, and only while that key names it
        let kept = match (op.opt_text("idem"), c.response) {
            (Some(_), Some((status, body))) if !c.streamed && body.len() <= MOST_RESPONSE => Some((status, body)),
            _ => None,
        };
        self.sql.run(
            "UPDATE ops SET state = ?, finished = ?, http_status = ?, code = ?, input_tokens = ?, output_tokens = ?, streamed = ?,
               response_status = ?, response = ?, response_until = ? WHERE request_id = ? AND state = 'admitted'",
            args![
                outcome,
                now,
                i64::from(c.http_status),
                c.code,
                c.input_tokens,
                c.output_tokens,
                i64::from(c.streamed),
                kept.map(|(s, _)| i64::from(s)),
                kept.map(|(_, b)| b),
                kept.map(|_| now + self.cfg.replay_ms),
                request_id
            ],
        )?;
        Ok(true)
    }

    fn op_json(r: &Row, now: i64) -> Json {
        let mut state = r.text("state");
        if state == ADMITTED && r.int("lease_until") <= now {
            state = "unknown".into();
        }
        let usage = match (r.opt_int("input_tokens"), r.opt_int("output_tokens")) {
            (None, None) => Json::Null,
            (i, o) => json!({ "input_tokens": i, "output_tokens": o }),
        };
        json!({
            "id": r.text("request_id"), "object": "request", "product": r.text("product"), "model": r.opt_text("model"),
            "organisation": r.text("org_id"), "project": r.text("project_id"), "environment": r.text("env"),
            "state": state, "quota_consumed": r.text("state") != RELEASED, "day": r.text("day"),
            "created": r.int("created"), "finished": r.opt_int("finished"), "http_status": r.opt_int("http_status"),
            "code": r.opt_text("code"), "streamed": r.int("streamed") == 1, "usage": usage,
        })
    }

    /// A request's record, if it is this person's and of this organisation.
    pub fn status(&self, request_id: &str, org: &str, now: i64) -> Result<Option<Json>, SqlError> {
        self.ensure()?;
        Ok(self
            .sql
            .row("SELECT * FROM ops WHERE request_id = ? AND org_id = ?", args![request_id, org])?
            .map(|r| Self::op_json(&r, now)))
    }

    /// The person's latest requests, newest first (the console's list): at most `n`.
    pub fn recent(&self, n: i64, now: i64) -> Result<Vec<Json>, SqlError> {
        self.ensure()?;
        Ok(self
            .sql
            .rows("SELECT * FROM ops ORDER BY created DESC, request_id DESC LIMIT ?", args![n.clamp(1, 100)])?
            .iter()
            .map(|r| Self::op_json(r, now))
            .collect())
    }

    /// What a caller or the console is told: the day's allowance, and whether the person may run anything.
    pub fn limits(&self, now: i64) -> Result<Json, SqlError> {
        self.ensure()?;
        let mut v = self.state(now)?.to_json();
        v["suspended"] = json!(self.suspended()?);
        Ok(v)
    }

    /// What has outlived its use: kept responses past their time, keys past the time they name a request, records past
    /// theirs — a request whose end was never told among them, once its lease has passed (it stays counted on its day,
    /// and its key names it, as `request_outcome_unknown`, for as long as any key names its request).  Bounded: the
    /// object holds a person's few requests a day.
    pub fn prune(&self, now: i64) -> Result<(), SqlError> {
        self.sql.run(
            "UPDATE ops SET response = NULL, response_status = NULL WHERE response_until IS NOT NULL AND response_until <= ?",
            args![now],
        )?;
        self.sql.run(
            "UPDATE ops SET idem = NULL WHERE idem IS NOT NULL AND (state <> 'admitted' OR lease_until <= ?) AND created <= ?",
            args![now, now - self.cfg.replay_ms],
        )?;
        self.sql.run(
            "DELETE FROM ops WHERE request_id IN (SELECT request_id FROM ops WHERE (state <> 'admitted' OR lease_until <= ?)
               AND created < ? LIMIT 200)",
            args![now, now - self.cfg.keep_ms],
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sql::sqlite::Memory;

    const T0: i64 = 1_795_824_000_000 - 2 * 3_600_000; // 2026-11-27 22:00 UTC

    fn cfg() -> QuotaConfig {
        QuotaConfig::from_vars(|_| None)
    }

    fn ask<'a>(id: &'a str, idem: Option<&'a str>, hash: &'a str) -> Admit<'a> {
        Admit {
            request_id: id,
            org: "org_a",
            project: "prj_a",
            env: "live",
            product: "chat.completions",
            model: Some("Tao-R1"),
            idem,
            request_hash: hash,
            lease_ms: 240_000,
        }
    }

    fn done(q: &QuotaCore, id: &str, now: i64) {
        let c = Completion {
            outcome: "succeeded",
            http_status: 200,
            code: None,
            input_tokens: Some(10),
            output_tokens: Some(20),
            streamed: false,
            response: Some((200, r#"{"ok":true}"#)),
        };
        assert!(q.complete(id, &c, now).unwrap());
    }

    fn code(e: Error) -> &'static str {
        match e {
            Error::Refused(r) => r.code,
            Error::Storage(_) => "storage",
        }
    }

    #[test]
    fn five_a_day_then_none_until_midnight_and_a_new_day_counts_anew() {
        let db = Memory::default();
        let c = cfg();
        let q = QuotaCore::new(&db, &c);
        for i in 0..5 {
            let id = format!("req_{i}");
            match q.admit(&ask(&id, None, "h"), T0 + i).unwrap() {
                Admission::Admitted(s) => assert_eq!((s.used, s.remaining), (i + 1, 4 - i)),
                other => panic!("{other:?}"),
            }
            done(&q, &id, T0 + i);
        }
        let e = q.admit(&ask("req_5", None, "h"), T0 + 10).unwrap_err();
        assert_eq!(code(e.clone()), "daily_quota_exceeded");
        match e {
            Error::Refused(r) => {
                assert_eq!(r.status, 429);
                assert_eq!(r.retry, Some(2 * 3600), "until 00:00 UTC");
            }
            _ => unreachable!(),
        }
        // the next UTC day: five again; the records of the last keep their day
        let next = T0 + 2 * 3_600_000;
        assert!(matches!(q.admit(&ask("req_6", None, "h"), next).unwrap(), Admission::Admitted(s) if s.used == 1));
        let first = q.status("req_0", "org_a", next).unwrap().unwrap();
        assert_eq!(first["day"], "2026-11-27");
        assert_eq!(q.state(next).unwrap().used, 1);
    }

    #[test]
    fn one_in_flight_at_once_and_a_request_without_an_end_is_counted_and_unknown() {
        let db = Memory::default();
        let c = cfg();
        let q = QuotaCore::new(&db, &c);
        assert!(matches!(q.admit(&ask("req_a", Some("k1"), "h1"), T0).unwrap(), Admission::Admitted(_)));
        assert_eq!(code(q.admit(&ask("req_b", None, "h"), T0 + 1).unwrap_err()), "user_concurrency");
        // its repeat while it runs: in progress
        assert_eq!(code(q.admit(&ask("req_c", Some("k1"), "h1"), T0 + 2).unwrap_err()), "request_in_progress");
        // the Worker that ran it died: after its lease it is of unknown outcome — counted, never run again by its key
        let later = T0 + 240_001;
        assert_eq!(code(q.admit(&ask("req_d", Some("k1"), "h1"), later).unwrap_err()), "request_outcome_unknown");
        assert_eq!(q.status("req_a", "org_a", later).unwrap().unwrap()["state"], "unknown");
        let s = q.state(later).unwrap();
        assert_eq!((s.used, s.in_flight), (1, 0));
        // and another request may run now
        assert!(matches!(q.admit(&ask("req_e", None, "h"), later).unwrap(), Admission::Admitted(s) if s.used == 2));
        // its end reported late is still kept
        done(&q, "req_a", later + 5);
        assert_eq!(q.status("req_a", "org_a", later + 5).unwrap().unwrap()["state"], "succeeded");
    }

    #[test]
    fn a_repeat_of_a_key_is_its_first_answer_another_request_under_it_is_refused() {
        let db = Memory::default();
        let c = cfg();
        let q = QuotaCore::new(&db, &c);
        assert!(matches!(q.admit(&ask("req_a", Some("k1"), "h1"), T0).unwrap(), Admission::Admitted(_)));
        done(&q, "req_a", T0 + 5);
        match q.admit(&ask("req_b", Some("k1"), "h1"), T0 + 10).unwrap() {
            Admission::Replay { request_id, status, body, quota } => {
                assert_eq!((request_id.as_str(), status, body.as_str()), ("req_a", 200, r#"{"ok":true}"#));
                assert_eq!(quota.used, 1, "a replay counts nothing");
            }
            other => panic!("{other:?}"),
        }
        assert_eq!(code(q.admit(&ask("req_c", Some("k1"), "other"), T0 + 11).unwrap_err()), "idempotency_conflict");
        // the same key in another project, environment or organisation is another request
        let other_env = Admit { env: "test", ..ask("req_d", Some("k1"), "h1") };
        assert!(matches!(q.admit(&other_env, T0 + 12).unwrap(), Admission::Admitted(_)));
        done(&q, "req_d", T0 + 13);
        // past the replay window the key is free, and the request runs (and counts) again
        let day_later = T0 + c.replay_ms + 1;
        assert!(matches!(q.admit(&ask("req_e", Some("k1"), "h1"), day_later).unwrap(), Admission::Admitted(_)));
    }

    #[test]
    fn a_stream_is_not_replayed_and_a_released_request_neither_counts_nor_holds_its_key() {
        let db = Memory::default();
        let c = cfg();
        let q = QuotaCore::new(&db, &c);
        assert!(matches!(q.admit(&ask("req_s", Some("ks"), "h"), T0).unwrap(), Admission::Admitted(_)));
        let streamed = Completion {
            outcome: "succeeded",
            http_status: 200,
            code: None,
            input_tokens: None,
            output_tokens: None,
            streamed: true,
            response: Some((200, "ignored")),
        };
        assert!(q.complete("req_s", &streamed, T0 + 1).unwrap());
        assert_eq!(code(q.admit(&ask("req_t", Some("ks"), "h"), T0 + 2).unwrap_err()), "stream_replay_unavailable");
        // released: never asked of anyone — not counted, and its key may be used again at once
        assert!(matches!(q.admit(&ask("req_r", Some("kr"), "h"), T0 + 3).unwrap(), Admission::Admitted(_)));
        assert!(q.release("req_r", T0 + 4).unwrap());
        assert!(!q.release("req_r", T0 + 5).unwrap(), "once");
        assert!(!q.complete("req_r", &streamed, T0 + 5).unwrap(), "a released request's end changes nothing");
        assert_eq!(q.state(T0 + 6).unwrap().used, 1);
        assert!(
            matches!(q.admit(&ask("req_r2", Some("kr"), "h"), T0 + 7).unwrap(), Admission::Admitted(s) if s.used == 2)
        );
        let rec = q.status("req_r", "org_a", T0 + 8).unwrap().unwrap();
        assert_eq!((rec["state"].as_str(), rec["quota_consumed"].as_bool()), (Some("released"), Some(false)));
        // a record is shown only to its organisation
        assert!(q.status("req_r", "org_b", T0 + 8).unwrap().is_none());
    }

    #[test]
    fn a_late_release_takes_back_nothing_and_an_unknown_requests_key_is_freed_in_its_time() {
        let db = Memory::default();
        let c = cfg();
        let q = QuotaCore::new(&db, &c);
        assert!(matches!(q.admit(&ask("req_a", Some("k1"), "h1"), T0).unwrap(), Admission::Admitted(_)));
        // its lease passed: of unknown outcome, and counted — a release told after that changes nothing
        let lapsed = T0 + 240_001;
        assert!(!q.release("req_a", lapsed).unwrap());
        assert_eq!(q.state(lapsed).unwrap().used, 1);
        assert_eq!(q.status("req_a", "org_a", lapsed).unwrap().unwrap()["state"], "unknown");
        // released within its lease, a request is not counted
        assert!(matches!(q.admit(&ask("req_b", None, "h"), lapsed).unwrap(), Admission::Admitted(_)));
        assert!(q.release("req_b", lapsed + 1).unwrap());
        assert_eq!(q.state(lapsed + 1).unwrap().used, 1);
        // the unknown request's key names it as long as a key names its request, then is free to run again
        let replay_end = T0 + c.replay_ms;
        assert_eq!(
            code(q.admit(&ask("req_c", Some("k1"), "h1"), replay_end - 1).unwrap_err()),
            "request_outcome_unknown"
        );
        assert!(matches!(q.admit(&ask("req_d", Some("k1"), "h1"), replay_end + 1).unwrap(), Admission::Admitted(_)));
        // and its record goes with the others'
        q.prune(T0 + c.keep_ms + 1).unwrap();
        assert!(q.status("req_a", "org_a", T0 + c.keep_ms + 1).unwrap().is_none());
        // a record is kept a day longer than its key may name it, however the two are set
        let short = QuotaConfig::from_vars(|k| match k {
            "IDEMPOTENCY_HOURS" => Some("720".into()),
            "REQUEST_RECORD_DAYS" => Some("2".into()),
            _ => None,
        });
        assert_eq!(short.keep_ms, 720 * 3_600_000 + DAY);
        assert_eq!(cfg().keep_ms, 7 * DAY);
    }

    #[test]
    fn a_suspended_person_runs_nothing_and_old_records_go() {
        let db = Memory::default();
        let c = cfg();
        let q = QuotaCore::new(&db, &c);
        assert!(matches!(q.admit(&ask("req_a", None, "h"), T0).unwrap(), Admission::Admitted(_)));
        done(&q, "req_a", T0 + 1);
        q.set_suspended(true, "owner", T0 + 2).unwrap();
        assert_eq!(code(q.admit(&ask("req_b", None, "h"), T0 + 3).unwrap_err()), "user_suspended");
        assert_eq!(q.limits(T0 + 3).unwrap()["suspended"], true);
        q.set_suspended(false, "owner", T0 + 4).unwrap();
        assert!(matches!(q.admit(&ask("req_c", None, "h"), T0 + 5).unwrap(), Admission::Admitted(_)));
        // a week on, the records are gone — req_c's among them, whose end was never told and whose lease passed long
        // ago — and one in flight stays
        let week = T0 + c.keep_ms + DAY;
        assert!(matches!(q.admit(&ask("req_live", None, "h"), week).unwrap(), Admission::Admitted(_)));
        q.prune(week + 1).unwrap();
        assert!(q.status("req_a", "org_a", week).unwrap().is_none());
        assert!(q.status("req_c", "org_a", week).unwrap().is_none());
        assert_eq!(
            q.recent(10, week).unwrap().iter().map(|r| r["id"].clone()).collect::<Vec<_>>(),
            vec![json!("req_live")]
        );
        // the limits' shape, and a limit of none
        let l = q.limits(T0).unwrap();
        assert_eq!(
            (l["limit"].as_i64(), l["timezone"].as_str(), l["reset_at"].as_str()),
            (Some(5), Some("UTC"), Some("2026-11-28T00:00:00Z"))
        );
        let none = QuotaConfig { daily_limit: 0, ..cfg() };
        let db2 = Memory::default();
        assert_eq!(
            code(QuotaCore::new(&db2, &none).admit(&ask("req_z", None, "h"), T0).unwrap_err()),
            "daily_quota_exceeded"
        );
    }
}
