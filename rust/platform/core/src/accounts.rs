//! 账户 · 额度 — what an organisation holds: its projects, its API keys, its credits, and what each call reserved and
//! spent.  One Durable Object an organisation (the API Worker's `Account`), so that a key's check, its rate, the
//! organisation's balance and the reservation a call makes are one step — the key cannot be revoked between its check
//! and the call's reservation, and two calls cannot both take the last credits.
//!
//! The arithmetic, in integer credits:
//!
//!   net        the ledger's sum: grants and adjustments in, settled usage out
//!   held       what calls in flight have reserved
//!   available  net − held.  A call is let through only if its price fits in it, and its price is then held; settling
//!              moves it from held to spent, a failure or a lapse gives it back.  So available is never below zero
//!              through anything a call does (an owner's negative adjustment alone can take it there)
//!
//! A reservation is settled once (a second settlement finds it settled and changes nothing), a usage entry is written
//! once (its reference is unique), a grant once (its reference likewise).  A reservation nobody settles — the Worker
//! that made it died — lapses after `hold_ms`: released, not charged, and counted, because a result that may never
//! have reached the caller is not charged for.  `Idempotency-Key`: a request repeated with the same key and body gets
//! the first one's answer and is not charged again; with another body it is refused.

use serde_json::{Value as Json, json};

use crate::args;
use crate::crypto::{Entropy, new_id};
use crate::keys::{self, KeyEnv, NewKey};
use crate::sql::{Row, Sql, SqlError, SqlExt, Value};
use crate::time::{DAY, MINUTE, day, is_day, month_start, to_midnight};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Product {
    Search,
    Verify,
}

impl Product {
    pub fn name(self) -> &'static str {
        match self {
            Product::Search => "evidence.search",
            Product::Verify => "citations.verify",
        }
    }

    pub fn scope(self) -> &'static str {
        match self {
            Product::Search => "evidence:search",
            Product::Verify => "citations:verify",
        }
    }

    pub fn parse(s: &str) -> Option<Product> {
        match s {
            "evidence.search" => Some(Product::Search),
            "citations.verify" => Some(Product::Verify),
            _ => None,
        }
    }
}

/// What a key may be given: the products, and reading its own usage.
pub const SCOPES: [&str; 3] = ["evidence:search", "citations:verify", "usage:read"];

#[derive(Debug, Clone)]
pub struct AccountConfig {
    pub price_search: i64,
    pub price_verify: i64,
    /// the prices' own name, kept with every reservation and charge: a price changed later does not rewrite one
    pub price_version: String,
    pub key_rate: i64,
    pub key_concurrency: i64,
    pub org_concurrency: i64,
    pub test_per_day: i64,
    pub hold_ms: i64,
    pub idem_ms: i64,
    pub max_keys: i64,
}

impl AccountConfig {
    /// From the Worker's variables (a missing or unreadable one: its default).
    pub fn from_vars(get: impl Fn(&str) -> Option<String>) -> Self {
        let num = |k: &str, default: i64, least: i64| {
            get(k).and_then(|v| v.trim().parse::<i64>().ok()).filter(|v| *v >= least).unwrap_or(default)
        };
        let price_search = num("PRICE_EVIDENCE_SEARCH", 10, 0);
        let price_verify = num("PRICE_CITATIONS_VERIFY", 2, 0);
        let version = crate::codec::hex(&crate::crypto::sha256(
            format!("search={price_search};verify={price_verify}").as_bytes(),
        ));
        AccountConfig {
            price_search,
            price_verify,
            price_version: format!("p{}", &version[..8]),
            key_rate: num("KEY_RATE_PER_MINUTE", 60, 1),
            key_concurrency: num("KEY_CONCURRENCY", 2, 1),
            org_concurrency: num("ORG_CONCURRENCY", 4, 1),
            test_per_day: num("TEST_CALLS_PER_DAY", 100, 0),
            hold_ms: num("HOLD_SECONDS", 120, 10) * 1000,
            idem_ms: num("IDEMPOTENCY_HOURS", 24, 1) * 3_600_000,
            max_keys: num("MAX_KEYS", 50, 1),
        }
    }

    pub fn price(&self, p: Product) -> i64 {
        match p {
            Product::Search => self.price_search,
            Product::Verify => self.price_verify,
        }
    }
}

/// A refusal as the API answers it: an HTTP status, an error type, a code a program branches on, words a person reads.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Refusal {
    pub status: u16,
    pub kind: &'static str,
    pub code: &'static str,
    pub message: String,
    /// seconds, for Retry-After
    pub retry: Option<i64>,
}

#[derive(Debug, Clone, PartialEq)]
pub enum Error {
    Refused(Refusal),
    Storage(SqlError),
}

impl From<SqlError> for Error {
    fn from(e: SqlError) -> Self {
        Error::Storage(e)
    }
}

pub type Outcome<T> = Result<T, Error>;

pub fn refused(status: u16, kind: &'static str, code: &'static str, message: impl Into<String>) -> Error {
    Error::Refused(Refusal { status, kind, code, message: message.into(), retry: None })
}

/// What needs a passkey's touch, asked without one: the console answers it by asking for the touch.
fn stepup(message: &str) -> Error {
    refused(403, "permission", "stepup", message)
}

fn retry_after(e: Error, seconds: i64) -> Error {
    match e {
        Error::Refused(r) => Error::Refused(Refusal { retry: Some(seconds.max(1)), ..r }),
        other => other,
    }
}

const SCHEMA: &[&str] = &[
    "CREATE TABLE IF NOT EXISTS org (org_id TEXT PRIMARY KEY, name TEXT NOT NULL, created INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'active')",
    "CREATE TABLE IF NOT EXISTS projects (project_id TEXT PRIMARY KEY, name TEXT NOT NULL, created INTEGER NOT NULL, monthly_limit INTEGER, archived INTEGER)",
    "CREATE TABLE IF NOT EXISTS keys (key_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, env TEXT NOT NULL, digest TEXT NOT NULL UNIQUE, shown TEXT NOT NULL,
      name TEXT NOT NULL, scopes TEXT NOT NULL, created INTEGER NOT NULL, created_by TEXT NOT NULL, expires INTEGER, revoked INTEGER, last_used INTEGER)",
    // every credit in or out, once: `ref` is the entry's own idempotency (grant:<ref>, use:<reservation>, adjust:<ref>)
    "CREATE TABLE IF NOT EXISTS ledger (entry_id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, kind TEXT NOT NULL, credits INTEGER NOT NULL,
      ref TEXT NOT NULL UNIQUE, project_id TEXT, key_id TEXT, product TEXT, price_version TEXT, note TEXT NOT NULL DEFAULT '')",
    "CREATE TABLE IF NOT EXISTS reservations (reservation_id TEXT PRIMARY KEY, key_id TEXT NOT NULL, project_id TEXT NOT NULL, env TEXT NOT NULL,
      product TEXT NOT NULL, credits INTEGER NOT NULL, price_version TEXT NOT NULL, idem TEXT, created INTEGER NOT NULL, expires INTEGER NOT NULL,
      state TEXT NOT NULL, ended INTEGER)",
    "CREATE INDEX IF NOT EXISTS reservations_held ON reservations (state, expires)",
    "CREATE TABLE IF NOT EXISTS idempotency (k TEXT PRIMARY KEY, request TEXT NOT NULL, reservation_id TEXT NOT NULL, status INTEGER, body TEXT,
      created INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS usage (day TEXT NOT NULL, key_id TEXT NOT NULL, product TEXT NOT NULL, project_id TEXT NOT NULL, env TEXT NOT NULL,
      calls INTEGER NOT NULL DEFAULT 0, credits INTEGER NOT NULL DEFAULT 0, failed INTEGER NOT NULL DEFAULT 0, refused INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (day, key_id, product))",
    "CREATE TABLE IF NOT EXISTS minutes (key_id TEXT NOT NULL, minute INTEGER NOT NULL, n INTEGER NOT NULL, PRIMARY KEY (key_id, minute))",
    // the running sums, written in the step that changes them: net, held, and what lapsed or came late
    "CREATE TABLE IF NOT EXISTS totals (k TEXT PRIMARY KEY, n INTEGER NOT NULL)",
];

const MOST_CREDITS: i64 = 1_000_000_000_000;
const MOST_BODY: usize = 1_000_000;

/// The request's own `Idempotency-Key`, and a digest of what it asked (method, path, body).
#[derive(Debug, Clone)]
pub struct Idem<'a> {
    pub key: &'a str,
    pub request: &'a str,
}

#[derive(Debug, Clone)]
pub struct Authorize<'a> {
    /// SHA-256 of the API key (keys::parse)
    pub digest: &'a str,
    pub product: Product,
    /// the gateway's id of the request, unique: the reservation's id
    pub request_id: &'a str,
    pub idem: Option<Idem<'a>>,
}

#[derive(Debug, Clone, PartialEq)]
pub enum Authorized {
    /// let through: the call is to be made, then settled
    Go { reservation: String, key_id: String, project_id: String, env: KeyEnv, credits: i64, price_version: String },
    /// the same request was answered before: this is its answer, and nothing is charged
    Replay { status: u16, body: String },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Settled {
    Charged(i64),
    Released,
    /// settled, released or lapsed before: nothing changed
    Already(String),
    Unknown,
}

/// A key as an owner or the console lists it: never its digest.
fn key_info(r: &Row) -> Json {
    json!({
        "id": r.text("key_id"), "project": r.text("project_id"), "environment": r.text("env"), "shown": r.text("shown"),
        "name": r.text("name"), "scopes": serde_json::from_str::<Json>(&r.text("scopes")).unwrap_or(json!([])),
        "created": r.int("created"), "created_by": r.text("created_by"), "expires": r.opt_int("expires"),
        "revoked": r.opt_int("revoked"), "last_used": r.opt_int("last_used"),
    })
}

fn clean_name(name: &str) -> Option<String> {
    let s = name.trim();
    (!s.is_empty() && s.chars().count() <= 64 && !s.chars().any(char::is_control)).then(|| s.to_string())
}

/// An Idempotency-Key a client may send: 1–255 visible ASCII characters.
pub fn idem_key_ok(k: &str) -> bool {
    !k.is_empty() && k.len() <= 255 && k.bytes().all(|c| (0x21..=0x7e).contains(&c))
}

pub struct AccountCore<'a> {
    sql: &'a dyn Sql,
    pub cfg: &'a AccountConfig,
}

impl<'a> AccountCore<'a> {
    pub fn new(sql: &'a dyn Sql, cfg: &'a AccountConfig) -> Self {
        AccountCore { sql, cfg }
    }

    /// Was this object provisioned — are its tables made?  Nothing else makes them: an object a forged key names (its
    /// checksum is anyone's to compute) is asked, finds no table, and writes nothing — no organisation is made by asking.
    pub fn ready(&self) -> Result<bool, SqlError> {
        Ok(self.sql.scalar("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'org'", &[])? == 1)
    }

    pub fn ensure(&self) -> Result<(), SqlError> {
        for s in SCHEMA {
            self.sql.run(s, &[])?;
        }
        Ok(())
    }

    fn total(&self, k: &str) -> Result<i64, SqlError> {
        self.sql.scalar("SELECT n FROM totals WHERE k = ?", args![k])
    }

    fn add_total(&self, k: &str, by: i64) -> Result<(), SqlError> {
        self.sql.run(
            "INSERT INTO totals (k, n) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET n = n + excluded.n",
            args![k, by],
        )
    }

    pub fn org(&self) -> Result<Option<Row>, SqlError> {
        self.sql.row("SELECT * FROM org", &[])
    }

    /// The organisation's object made ready: its row and a default project.  Done again, it changes nothing.
    pub fn provision(&self, org_id: &str, name: &str, e: &dyn Entropy, now: i64) -> Outcome<Json> {
        if !keys::is_org_id(org_id) {
            return Err(refused(400, "invalid_request", "org", "not an organisation's id"));
        }
        self.ensure()?;
        if let Some(o) = self.org()? {
            if o.text("org_id") != org_id {
                return Err(refused(409, "conflict", "org", "this object belongs to another organisation"));
            }
        } else {
            let name = clean_name(name).unwrap_or_else(|| "organisation".into());
            self.sql.run("INSERT INTO org (org_id, name, created) VALUES (?, ?, ?)", args![org_id, name, now])?;
        }
        if self.sql.scalar("SELECT COUNT(*) FROM projects", &[])? == 0 {
            self.sql.run(
                "INSERT INTO projects (project_id, name, created) VALUES (?, 'default', ?)",
                args![new_id(e, "prj", 10), now],
            )?;
        }
        self.summary(now)
    }

    fn require_org(&self) -> Outcome<Row> {
        self.org()?.ok_or_else(|| refused(404, "not_found", "org", "no such organisation"))
    }

    /// Credits in, once for each reference: a grant (positive) or an owner's adjustment (either sign).  Ok(false) when
    /// the reference was used before — nothing is added twice.
    pub fn credit(&self, kind: &str, credits: i64, reference: &str, note: &str, now: i64) -> Outcome<bool> {
        self.require_org()?;
        let ok_kind = kind == "grant" && credits > 0 || kind == "adjust" && credits != 0;
        if !ok_kind || !(-MOST_CREDITS..=MOST_CREDITS).contains(&credits) {
            return Err(refused(
                400,
                "invalid_request",
                "credits",
                "a grant is a positive number of credits; an adjustment is not zero",
            ));
        }
        if reference.is_empty() || reference.len() > 120 || !reference.bytes().all(|c| (0x21..=0x7e).contains(&c)) {
            return Err(refused(400, "invalid_request", "reference", "a reference is 1–120 visible ASCII characters"));
        }
        let note: String = note.chars().filter(|c| !c.is_control()).take(200).collect();
        let added = self.sql.rows(
            "INSERT INTO ledger (ts, kind, credits, ref, note) VALUES (?, ?, ?, ?, ?) ON CONFLICT(ref) DO NOTHING RETURNING entry_id",
            args![now, kind, credits, format!("{kind}:{reference}"), note],
        )?;
        if added.is_empty() {
            return Ok(false);
        }
        self.add_total("net", credits)?;
        Ok(true)
    }

    pub fn create_project(&self, name: &str, monthly_limit: Option<i64>, e: &dyn Entropy, now: i64) -> Outcome<String> {
        self.require_org()?;
        let name =
            clean_name(name).ok_or_else(|| refused(400, "invalid_request", "name", "a name is 1–64 characters"))?;
        if monthly_limit.is_some_and(|l| !(0..=MOST_CREDITS).contains(&l)) {
            return Err(refused(400, "invalid_request", "limit", "a monthly limit is 0 or more credits"));
        }
        if self.sql.scalar("SELECT COUNT(*) FROM projects WHERE archived IS NULL", &[])? >= 100 {
            return Err(refused(409, "conflict", "projects", "an organisation has at most 100 projects"));
        }
        let id = new_id(e, "prj", 10);
        self.sql.run(
            "INSERT INTO projects (project_id, name, created, monthly_limit) VALUES (?, ?, ?, ?)",
            args![&id, name, now, monthly_limit],
        )?;
        Ok(id)
    }

    /// A project's monthly limit in credits (None: none).  `touched`: a passkey touched the asking session lately (the
    /// console), or the owner asked (the admin token) — what decides what an organisation may spend is asked for so.
    pub fn set_limit(&self, project_id: &str, monthly_limit: Option<i64>, touched: bool) -> Outcome<()> {
        if !touched {
            return Err(stepup("a project's limit is set after a passkey's touch"));
        }
        if monthly_limit.is_some_and(|l| !(0..=MOST_CREDITS).contains(&l)) {
            return Err(refused(400, "invalid_request", "limit", "a monthly limit is 0 or more credits"));
        }
        if self.sql.scalar("SELECT COUNT(*) FROM projects WHERE project_id = ?", args![project_id])? == 0 {
            return Err(refused(404, "not_found", "project", "no such project"));
        }
        self.sql.run("UPDATE projects SET monthly_limit = ? WHERE project_id = ?", args![monthly_limit, project_id])?;
        Ok(())
    }

    fn default_project(&self) -> Outcome<String> {
        self.sql
            .row("SELECT project_id FROM projects WHERE archived IS NULL ORDER BY created, project_id LIMIT 1", &[])?
            .map(|r| r.text("project_id"))
            .ok_or_else(|| refused(409, "conflict", "project", "the organisation has no project"))
    }

    /// A new key of a project (the organisation's first when none is named): the key itself, shown this once.  Scopes:
    /// None for all of them; an empty list is refused, not widened.  A live key spends credits: made only after a
    /// passkey's touch (`touched`: the console says so of its session, the owner's token always).
    #[allow(clippy::too_many_arguments)]
    pub fn create_key(
        &self,
        project: Option<&str>,
        env: KeyEnv,
        name: &str,
        scopes: Option<&[String]>,
        expires: Option<i64>,
        by: &str,
        touched: bool,
        e: &dyn Entropy,
        now: i64,
    ) -> Outcome<(String, NewKey)> {
        let org = self.require_org()?;
        if env == KeyEnv::Live && !touched {
            return Err(stepup("a live key is made after a passkey's touch"));
        }
        let project = match project {
            Some(p) => p.to_string(),
            None => self.default_project()?,
        };
        let p = self.sql.row("SELECT archived FROM projects WHERE project_id = ?", args![&project])?;
        if p.as_ref().is_none_or(|p| p.opt_int("archived").is_some()) {
            return Err(refused(404, "not_found", "project", "no such project"));
        }
        let name = clean_name(name)
            .ok_or_else(|| refused(400, "invalid_request", "name", "a key's name is 1–64 characters"))?;
        let mut wanted: Vec<&str> = match scopes {
            None => SCOPES.to_vec(),
            Some([]) => return Err(refused(400, "invalid_request", "scope", "a key has at least one scope")),
            Some(list) => list.iter().map(String::as_str).collect(),
        };
        wanted.sort_unstable();
        wanted.dedup();
        if let Some(bad) = wanted.iter().find(|s| !SCOPES.contains(s)) {
            return Err(refused(400, "invalid_request", "scope", format!("no such scope: {bad}")));
        }
        if expires.is_some_and(|t| t <= now) {
            return Err(refused(400, "invalid_request", "expires", "a key's expiry is in the future"));
        }
        if self.sql.scalar("SELECT COUNT(*) FROM keys WHERE revoked IS NULL", &[])? >= self.cfg.max_keys {
            return Err(refused(
                409,
                "conflict",
                "keys",
                format!("an organisation has at most {} keys that are not revoked", self.cfg.max_keys),
            ));
        }
        let new = keys::mint(e, env, &org.text("org_id"))
            .ok_or_else(|| refused(409, "conflict", "org", "the organisation's id is not one"))?;
        let key_id = new_id(e, "key", 10);
        self.sql.run(
            "INSERT INTO keys (key_id, project_id, env, digest, shown, name, scopes, created, created_by, expires) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            args![&key_id, &project, env.as_str(), &new.digest, &new.shown, name, json!(wanted).to_string(), now, by, expires],
        )?;
        Ok((key_id, new))
    }

    /// Ok(true) when the key was revoked now, Ok(false) when it was before.  A live key's revocation is an outage if it
    /// is the wrong one: after a passkey's touch, as its making was — decided here, where the key's environment is known.
    pub fn revoke_key(&self, key_id: &str, touched: bool, now: i64) -> Outcome<bool> {
        let k = self
            .sql
            .row("SELECT revoked, env FROM keys WHERE key_id = ?", args![key_id])?
            .ok_or_else(|| refused(404, "not_found", "key", "no such key"))?;
        if k.opt_int("revoked").is_some() {
            return Ok(false);
        }
        if k.text("env") == "live" && !touched {
            return Err(stepup("a live key is revoked after a passkey's touch"));
        }
        self.sql.run("UPDATE keys SET revoked = ? WHERE key_id = ?", args![now, key_id])?;
        Ok(true)
    }

    pub fn keys(&self) -> Result<Vec<Json>, SqlError> {
        Ok(self.sql.rows("SELECT * FROM keys ORDER BY created, key_id", &[])?.iter().map(key_info).collect())
    }

    /// The key a digest names, if it may be used now: the refusals a caller is told.
    pub fn authenticate(&self, digest: &str, now: i64) -> Outcome<Row> {
        let k = self
            .sql
            .row("SELECT * FROM keys WHERE digest = ?", args![digest])?
            .ok_or_else(|| refused(401, "authentication", "invalid_key", "the API key is not valid"))?;
        if k.opt_int("revoked").is_some() {
            return Err(refused(401, "authentication", "revoked_key", "the API key was revoked"));
        }
        if k.opt_int("expires").is_some_and(|t| t <= now) {
            return Err(refused(401, "authentication", "expired_key", "the API key has expired"));
        }
        let org = self.require_org()?;
        if org.text("status") != "active" {
            return Err(refused(403, "permission", "org_disabled", "the organisation is disabled"));
        }
        Ok(k)
    }

    pub fn has_scope(k: &Row, scope: &str) -> bool {
        serde_json::from_str::<Vec<String>>(&k.text("scopes")).is_ok_and(|s| s.iter().any(|x| x == scope))
    }

    fn count_refused(&self, k: &Row, product: Product, now: i64) -> Result<(), SqlError> {
        self.sql.run(
            "INSERT INTO usage (day, key_id, product, project_id, env, refused) VALUES (?, ?, ?, ?, ?, 1)
             ON CONFLICT(day, key_id, product) DO UPDATE SET refused = refused + 1",
            args![day(now), k.text("key_id"), product.name(), k.text("project_id"), k.text("env")],
        )
    }

    /// A call's admission, in one step: the key, its scope, a repeat of an earlier request, the key's rate, what is in
    /// flight, and what it will cost — and, let through, its price held.
    pub fn authorize(&self, a: &Authorize, now: i64) -> Outcome<Authorized> {
        self.sweep(now)?;
        let k = self.authenticate(a.digest, now)?;
        if !Self::has_scope(&k, a.product.scope()) {
            return Err(refused(403, "permission", "scope", format!("this key may not call {}", a.product.name())));
        }
        let project = k.text("project_id");
        let p = self.sql.row("SELECT * FROM projects WHERE project_id = ?", args![&project])?;
        let Some(p) = p.filter(|p| p.opt_int("archived").is_none()) else {
            return Err(refused(403, "permission", "project_archived", "the key's project is archived"));
        };
        let key_id = k.text("key_id");
        // a repeat of an earlier request, by its Idempotency-Key
        let idem_k = match &a.idem {
            Some(i) if !idem_key_ok(i.key) => {
                return Err(refused(
                    400,
                    "invalid_request",
                    "idempotency_key",
                    "an Idempotency-Key is 1–255 visible ASCII characters",
                ));
            }
            Some(i) => Some(format!("{key_id}:{}", i.key)),
            None => None,
        };
        if let (Some(ik), Some(i)) = (&idem_k, &a.idem)
            && let Some(seen) = self.sql.row("SELECT * FROM idempotency WHERE k = ?", args![ik])?
        {
            if seen.int("created") + self.cfg.idem_ms > now {
                if seen.text("request") != i.request {
                    return Err(refused(
                        422,
                        "invalid_request",
                        "idempotency_mismatch",
                        "this Idempotency-Key was used for another request",
                    ));
                }
                return match (seen.opt_int("status"), seen.opt_text("body")) {
                    (Some(status), Some(body)) => Ok(Authorized::Replay { status: status as u16, body }),
                    (Some(_), None) => Err(refused(
                        409,
                        "conflict",
                        "idempotency_unavailable",
                        "the first answer to this request is too large to keep",
                    )),
                    _ => Err(retry_after(
                        refused(
                            409,
                            "conflict",
                            "idempotency_in_progress",
                            "a request with this Idempotency-Key is still running",
                        ),
                        1,
                    )),
                };
            }
            self.sql.run("DELETE FROM idempotency WHERE k = ?", args![ik])?;
        }
        // the key's rate, by the minute
        let minute = now.div_euclid(MINUTE);
        let used = self.sql.scalar("SELECT n FROM minutes WHERE key_id = ? AND minute = ?", args![&key_id, minute])?;
        if used >= self.cfg.key_rate {
            self.count_refused(&k, a.product, now)?;
            let left = (MINUTE - now.rem_euclid(MINUTE) + 999) / 1000;
            return Err(retry_after(
                refused(
                    429,
                    "rate_limit",
                    "rate",
                    format!("at most {} calls a minute with this key", self.cfg.key_rate),
                ),
                left,
            ));
        }
        // what is in flight: the key's, and the organisation's
        let key_held =
            self.sql.scalar("SELECT COUNT(*) FROM reservations WHERE state = 'held' AND key_id = ?", args![&key_id])?;
        let org_held = self.sql.scalar("SELECT COUNT(*) FROM reservations WHERE state = 'held'", &[])?;
        if key_held >= self.cfg.key_concurrency || org_held >= self.cfg.org_concurrency {
            self.count_refused(&k, a.product, now)?;
            return Err(retry_after(
                refused(429, "rate_limit", "concurrency", "too many calls in flight: wait for one to end"),
                1,
            ));
        }
        let env = KeyEnv::parse(&k.text("env")).unwrap_or(KeyEnv::Test);
        let today = day(now);
        let credits = match env {
            KeyEnv::Test => {
                let calls = self.sql.scalar(
                    "SELECT COALESCE(SUM(calls), 0) FROM usage WHERE day = ? AND env = 'test'",
                    args![&today],
                )?;
                let flying =
                    self.sql.scalar("SELECT COUNT(*) FROM reservations WHERE state = 'held' AND env = 'test'", &[])?;
                if calls + flying >= self.cfg.test_per_day {
                    self.count_refused(&k, a.product, now)?;
                    return Err(retry_after(
                        refused(
                            429,
                            "rate_limit",
                            "test_allowance",
                            format!("test keys make at most {} calls a day", self.cfg.test_per_day),
                        ),
                        to_midnight(now),
                    ));
                }
                0
            }
            KeyEnv::Live => {
                let price = self.cfg.price(a.product);
                let available = self.total("net")?.saturating_sub(self.total("held")?);
                if available < price {
                    self.count_refused(&k, a.product, now)?;
                    return Err(refused(
                        402,
                        "insufficient_credits",
                        "credits",
                        format!("{} costs {price} credits; {} are available", a.product.name(), available.max(0)),
                    ));
                }
                if let Some(limit) = p.opt_int("monthly_limit") {
                    let month = self.sql.scalar(
                        "SELECT COALESCE(SUM(credits), 0) FROM usage WHERE project_id = ? AND day >= ?",
                        args![&project, month_start(now)],
                    )?;
                    let flying = self.sql.scalar(
                        "SELECT COALESCE(SUM(credits), 0) FROM reservations WHERE state = 'held' AND project_id = ?",
                        args![&project],
                    )?;
                    if month + flying + price > limit {
                        self.count_refused(&k, a.product, now)?;
                        return Err(refused(
                            402,
                            "insufficient_credits",
                            "project_limit",
                            format!("the project's limit is {limit} credits a month"),
                        ));
                    }
                }
                price
            }
        };
        // let through: the price held, the minute counted, the request remembered for its repeats
        self.sql.run(
            "INSERT INTO reservations (reservation_id, key_id, project_id, env, product, credits, price_version, idem, created, expires, state)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'held')",
            args![a.request_id, &key_id, &project, env.as_str(), a.product.name(), credits, &self.cfg.price_version, idem_k.clone(), now, now + self.cfg.hold_ms],
        )?;
        self.add_total("held", credits)?;
        self.sql.run(
            "INSERT INTO minutes (key_id, minute, n) VALUES (?, ?, 1) ON CONFLICT(key_id, minute) DO UPDATE SET n = n + 1",
            args![&key_id, minute],
        )?;
        if let (Some(ik), Some(i)) = (&idem_k, &a.idem) {
            self.sql.run(
                "INSERT INTO idempotency (k, request, reservation_id, created) VALUES (?, ?, ?, ?)",
                args![ik, i.request, a.request_id, now],
            )?;
        }
        if k.opt_int("last_used").is_none_or(|t| t < now - MINUTE) {
            self.sql.run("UPDATE keys SET last_used = ? WHERE key_id = ?", args![now, &key_id])?;
        }
        Ok(Authorized::Go {
            reservation: a.request_id.to_string(),
            key_id,
            project_id: project,
            env,
            credits,
            price_version: self.cfg.price_version.clone(),
        })
    }

    /// A call's end.  `delivered`: the caller got the result (its status and body, kept for a repeat of the request) —
    /// charged; otherwise released, and a repeat of it runs again.
    pub fn settle(&self, reservation: &str, delivered: Option<(u16, &str)>, now: i64) -> Outcome<Settled> {
        let Some(r) = self.sql.row("SELECT * FROM reservations WHERE reservation_id = ?", args![reservation])? else {
            return Ok(Settled::Unknown);
        };
        let state = r.text("state");
        if state != "held" {
            if state == "lapsed" && delivered.is_some() {
                self.add_total("late", 1)?; // a result that came after its reservation lapsed: not charged, counted
            }
            return Ok(Settled::Already(state));
        }
        let credits = r.int("credits");
        let idem = r.opt_text("idem");
        let usage_args = |calls: i64, credits: i64, failed: i64| -> Vec<Value> {
            vec![
                day(now).into(),
                r.text("key_id").into(),
                r.text("product").into(),
                r.text("project_id").into(),
                r.text("env").into(),
                calls.into(),
                credits.into(),
                failed.into(),
            ]
        };
        const USAGE: &str = "INSERT INTO usage (day, key_id, product, project_id, env, calls, credits, failed) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT(day, key_id, product) DO UPDATE SET calls = calls + excluded.calls, credits = credits + excluded.credits, failed = failed + excluded.failed";
        match delivered {
            Some((status, body)) => {
                self.sql.run(
                    "UPDATE reservations SET state = 'settled', ended = ? WHERE reservation_id = ?",
                    args![now, reservation],
                )?;
                if credits > 0 {
                    self.sql.run(
                        "INSERT INTO ledger (ts, kind, credits, ref, project_id, key_id, product, price_version) VALUES (?, 'usage', ?, ?, ?, ?, ?, ?)",
                        args![now, -credits, format!("use:{reservation}"), r.text("project_id"), r.text("key_id"), r.text("product"), r.text("price_version")],
                    )?;
                    self.add_total("net", -credits)?;
                }
                self.add_total("held", -credits)?;
                self.sql.run(USAGE, &usage_args(1, credits, 0))?;
                if let Some(ik) = idem {
                    let kept = (body.len() <= MOST_BODY).then_some(body);
                    self.sql.run(
                        "UPDATE idempotency SET status = ?, body = ? WHERE k = ?",
                        args![i64::from(status), kept, ik],
                    )?;
                }
                Ok(Settled::Charged(credits))
            }
            None => {
                self.sql.run(
                    "UPDATE reservations SET state = 'released', ended = ? WHERE reservation_id = ?",
                    args![now, reservation],
                )?;
                self.add_total("held", -credits)?;
                self.sql.run(USAGE, &usage_args(0, 0, 1))?;
                if let Some(ik) = idem {
                    self.sql.run("DELETE FROM idempotency WHERE k = ?", args![ik])?;
                }
                Ok(Settled::Released)
            }
        }
    }

    /// Reservations nobody settled in time: lapsed — released, not charged, counted.  And what has outlived its use.
    pub fn sweep(&self, now: i64) -> Result<i64, SqlError> {
        let stale = self.sql.rows(
            "SELECT reservation_id, credits, idem FROM reservations WHERE state = 'held' AND expires <= ? LIMIT 200",
            args![now],
        )?;
        for r in &stale {
            self.sql.run(
                "UPDATE reservations SET state = 'lapsed', ended = ? WHERE reservation_id = ?",
                args![now, r.text("reservation_id")],
            )?;
            self.add_total("held", -r.int("credits"))?;
            self.add_total("lapsed", 1)?;
            if let Some(ik) = r.opt_text("idem") {
                self.sql.run("DELETE FROM idempotency WHERE k = ? AND status IS NULL", args![ik])?;
            }
        }
        self.sql.run("DELETE FROM minutes WHERE minute < ?", args![now.div_euclid(MINUTE) - 2])?;
        self.sql.run("DELETE FROM idempotency WHERE created < ?", args![now - self.cfg.idem_ms])?;
        self.sql.run("DELETE FROM reservations WHERE state <> 'held' AND ended < ?", args![now - 35 * DAY])?;
        Ok(stale.len() as i64)
    }

    pub fn balance(&self) -> Result<Json, SqlError> {
        let net = self.total("net")?;
        let held = self.total("held")?;
        Ok(json!({ "net": net, "held": held, "available": net.saturating_sub(held) }))
    }

    /// What a key may do now: its scopes, its rate, its environment's allowance or the organisation's credits.
    pub fn limits(&self, digest: &str, now: i64) -> Outcome<Json> {
        let k = self.authenticate(digest, now)?;
        let key_id = k.text("key_id");
        let used = self
            .sql
            .scalar("SELECT n FROM minutes WHERE key_id = ? AND minute = ?", args![&key_id, now.div_euclid(MINUTE)])?;
        let env = k.text("env");
        let allowance = if env == "test" {
            let calls = self
                .sql
                .scalar("SELECT COALESCE(SUM(calls), 0) FROM usage WHERE day = ? AND env = 'test'", args![day(now)])?;
            json!({ "calls_per_day": self.cfg.test_per_day, "used_today": calls })
        } else {
            self.balance()?
        };
        Ok(json!({
            "key": key_info(&k), "environment": env,
            "rate": { "per_minute": self.cfg.key_rate, "used_this_minute": used },
            "concurrency": { "key": self.cfg.key_concurrency, "organisation": self.cfg.org_concurrency },
            if env == "test" { "allowance" } else { "credits" }: allowance,
            "prices": { "evidence.search": if env == "test" { 0 } else { self.cfg.price_search }, "citations.verify": if env == "test" { 0 } else { self.cfg.price_verify } },
            "price_version": self.cfg.price_version,
        }))
    }

    /// Usage by day, product and environment, from `from` to `to` (inclusive), of a project or of all.
    pub fn usage(&self, from: &str, to: &str, project: Option<&str>) -> Outcome<Json> {
        if !is_day(from) || !is_day(to) || from > to {
            return Err(refused(
                400,
                "invalid_request",
                "days",
                "from and to are days (YYYY-MM-DD), from not after to",
            ));
        }
        let rows = self.sql.rows(
            "SELECT day, product, env, project_id, SUM(calls) AS calls, SUM(credits) AS credits, SUM(failed) AS failed, SUM(refused) AS refused
             FROM usage WHERE day >= ? AND day <= ? AND (? IS NULL OR project_id = ?) GROUP BY day, product, env, project_id ORDER BY day, product, env",
            args![from, to, project, project],
        )?;
        let data: Vec<Json> = rows
            .iter()
            .map(|r| json!({ "day": r.text("day"), "product": r.text("product"), "environment": r.text("env"), "project": r.text("project_id"),
                "calls": r.int("calls"), "credits": r.int("credits"), "failed": r.int("failed"), "refused": r.int("refused") }))
            .collect();
        Ok(json!({ "from": from, "to": to, "data": data }))
    }

    /// Everything an owner or the console reads of the organisation (no digest of any key).
    pub fn summary(&self, now: i64) -> Outcome<Json> {
        let org = self.require_org()?;
        let projects: Vec<Json> = self
            .sql
            .rows("SELECT * FROM projects ORDER BY created, project_id", &[])?
            .iter()
            .map(|p| {
                json!({ "id": p.text("project_id"), "name": p.text("name"), "created": p.int("created"),
                "monthly_limit": p.opt_int("monthly_limit"), "archived": p.opt_int("archived") })
            })
            .collect();
        let today = self.usage(&day(now), &day(now), None)?;
        Ok(json!({
            "org": { "id": org.text("org_id"), "name": org.text("name"), "created": org.int("created"), "status": org.text("status") },
            "credits": self.balance()?, "projects": projects, "keys": self.keys()?, "today": today["data"],
            "lapsed": self.total("lapsed")?, "late": self.total("late")?, "prices": { "evidence.search": self.cfg.price_search,
                "citations.verify": self.cfg.price_verify, "version": self.cfg.price_version },
        }))
    }

    /// The running sums against the rows they sum: what the tests hold the object to.
    pub fn consistent(&self) -> Result<bool, SqlError> {
        let net = self.sql.scalar("SELECT COALESCE(SUM(credits), 0) FROM ledger", &[])?;
        let held = self.sql.scalar("SELECT COALESCE(SUM(credits), 0) FROM reservations WHERE state = 'held'", &[])?;
        let spent = self.sql.scalar("SELECT COALESCE(SUM(credits), 0) FROM usage", &[])?;
        let charged = -self.sql.scalar("SELECT COALESCE(SUM(credits), 0) FROM ledger WHERE kind = 'usage'", &[])?;
        Ok(net == self.total("net")?
            && held == self.total("held")?
            && spent == charged
            && net.saturating_sub(held) >= 0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::crypto::tests::Counter;
    use crate::keys::parse;
    use crate::sql::sqlite::Memory;
    use std::cell::Cell;

    const T0: i64 = 1_795_824_000_000 - 10 * 3_600_000; // 2026-11-27 14:00 UTC

    struct World {
        db: Memory,
        cfg: AccountConfig,
        e: Counter,
        org: String,
    }

    impl World {
        fn new(vars: &[(&str, &str)]) -> World {
            let vars: Vec<(String, String)> = vars.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect();
            let cfg = AccountConfig::from_vars(|k| vars.iter().find(|(n, _)| n == k).map(|(_, v)| v.clone()));
            // each world its own seed: two worlds of one seed would mint the same ids and keys
            static SEED: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(1);
            let e = Counter(Cell::new(SEED.fetch_add(1, std::sync::atomic::Ordering::Relaxed) << 32));
            let org = new_id(&e, "org", 16);
            let w = World { db: Memory::new(), cfg, e, org };
            w.core().ensure().unwrap();
            w.core().provision(&w.org, "Lab", &w.e, T0).unwrap();
            w
        }

        fn core(&self) -> AccountCore<'_> {
            AccountCore::new(&self.db, &self.cfg)
        }

        fn key(&self, env: KeyEnv, scopes: &[&str]) -> String {
            let scopes: Vec<String> = scopes.iter().map(|s| s.to_string()).collect();
            self.core()
                .create_key(
                    None,
                    env,
                    "k",
                    (!scopes.is_empty()).then_some(&scopes[..]),
                    None,
                    "owner",
                    true,
                    &self.e,
                    T0,
                )
                .unwrap()
                .1
                .key
        }

        fn call(&self, key: &str, product: Product, id: &str, now: i64) -> Outcome<Authorized> {
            let d = parse(key).unwrap().digest;
            self.core().authorize(&Authorize { digest: &d, product, request_id: id, idem: None }, now)
        }
    }

    fn code(e: Outcome<impl std::fmt::Debug>) -> &'static str {
        match e {
            Err(Error::Refused(r)) => r.code,
            other => panic!("not a refusal: {other:?}"),
        }
    }

    fn go(a: Outcome<Authorized>) -> String {
        match a {
            Ok(Authorized::Go { reservation, .. }) => reservation,
            other => panic!("not let through: {other:?}"),
        }
    }

    #[test]
    fn a_grant_is_spent_by_calls_and_never_past_what_is_available() {
        let w = World::new(&[("PRICE_EVIDENCE_SEARCH", "10"), ("ORG_CONCURRENCY", "10"), ("KEY_CONCURRENCY", "10")]);
        let key = w.key(KeyEnv::Live, &[]);
        assert_eq!(code(w.call(&key, Product::Search, "req_0", T0)), "credits");
        assert!(w.core().credit("grant", 25, "trial", "", T0).unwrap());
        assert!(!w.core().credit("grant", 25, "trial", "", T0).unwrap(), "a grant's reference is used once");
        // §12.3: calls arrive together before any is settled — the reservations stay within what is available
        let a = go(w.call(&key, Product::Search, "req_1", T0));
        let b = go(w.call(&key, Product::Search, "req_2", T0));
        assert_eq!(code(w.call(&key, Product::Search, "req_3", T0)), "credits");
        assert_eq!(w.core().balance().unwrap(), json!({ "net": 25, "held": 20, "available": 5 }));
        // one charged, one released: the released one's credits come back
        assert_eq!(w.core().settle(&a, Some((200, "{}")), T0).unwrap(), Settled::Charged(10));
        assert_eq!(w.core().settle(&b, None, T0).unwrap(), Settled::Released);
        // §12.3: a settlement repeated changes nothing
        assert_eq!(w.core().settle(&a, Some((200, "{}")), T0).unwrap(), Settled::Already("settled".into()));
        assert_eq!(w.core().settle(&b, Some((200, "{}")), T0).unwrap(), Settled::Already("released".into()));
        assert_eq!(w.core().settle("req_nobody", None, T0).unwrap(), Settled::Unknown);
        assert_eq!(w.core().balance().unwrap(), json!({ "net": 15, "held": 0, "available": 15 }));
        assert!(w.core().consistent().unwrap());
        let u = w.core().usage(&day(T0), &day(T0), None).unwrap();
        assert_eq!(
            (
                u["data"][0]["calls"].as_i64(),
                u["data"][0]["credits"].as_i64(),
                u["data"][0]["failed"].as_i64(),
                u["data"][0]["refused"].as_i64()
            ),
            (Some(1), Some(10), Some(1), Some(2))
        );
    }

    #[test]
    fn a_repeated_request_is_answered_once_and_charged_once() {
        let w = World::new(&[]);
        w.core().credit("grant", 100, "g", "", T0).unwrap();
        let key = w.key(KeyEnv::Live, &[]);
        let d = parse(&key).unwrap().digest;
        let ask = |id: &str, request: &str, now| {
            w.core().authorize(
                &Authorize {
                    digest: &d,
                    product: Product::Verify,
                    request_id: id,
                    idem: Some(Idem { key: "order-17", request }),
                },
                now,
            )
        };
        let first = go(ask("req_1", "digest-A", T0));
        // the same request again while the first runs: told so
        assert_eq!(code(ask("req_2", "digest-A", T0)), "idempotency_in_progress");
        w.core().settle(&first, Some((200, r#"{"found":true}"#)), T0).unwrap();
        // §12.3 a request repeated: the first answer, not a second charge
        assert_eq!(
            ask("req_3", "digest-A", T0 + 1000).unwrap(),
            Authorized::Replay { status: 200, body: r#"{"found":true}"#.into() }
        );
        assert_eq!(code(ask("req_4", "digest-B", T0 + 1000)), "idempotency_mismatch");
        assert_eq!(w.core().balance().unwrap()["net"], 98);
        // a day later the key is forgotten: the same key is a new request
        go(ask("req_5", "digest-B", T0 + DAY + 1));
        // a failed call is no answer: its repeat runs again
        let w2 = World::new(&[]);
        w2.core().credit("grant", 100, "g", "", T0).unwrap();
        let k2 = parse(&w2.key(KeyEnv::Live, &[])).unwrap().digest;
        let again = |id: &str| {
            w2.core().authorize(
                &Authorize {
                    digest: &k2,
                    product: Product::Verify,
                    request_id: id,
                    idem: Some(Idem { key: "x", request: "r" }),
                },
                T0,
            )
        };
        let r1 = go(again("req_1"));
        w2.core().settle(&r1, None, T0).unwrap();
        go(again("req_2"));
        assert_eq!(code(again("req_3")), "idempotency_in_progress");
        assert!(w.core().consistent().unwrap() && w2.core().consistent().unwrap());
    }

    #[test]
    fn a_call_nobody_settles_lapses_released_and_a_late_result_is_not_charged() {
        let w = World::new(&[("HOLD_SECONDS", "60")]);
        w.core().credit("grant", 10, "g", "", T0).unwrap();
        let key = w.key(KeyEnv::Live, &[]);
        let r = go(w.call(&key, Product::Search, "req_1", T0));
        assert_eq!(code(w.call(&key, Product::Search, "req_2", T0 + 1000)), "credits");
        // §12.3: the Worker died; a minute later the reservation lapses, and the credits are available again
        go(w.call(&key, Product::Search, "req_3", T0 + 61_000));
        assert_eq!(w.core().settle(&r, Some((200, "{}")), T0 + 62_000).unwrap(), Settled::Already("lapsed".into()));
        let s = w.core().summary(T0 + 62_000).unwrap();
        assert_eq!(
            (s["lapsed"].as_i64(), s["late"].as_i64(), s["credits"]["held"].as_i64()),
            (Some(1), Some(1), Some(10))
        );
        assert!(w.core().consistent().unwrap());
    }

    #[test]
    fn a_key_is_refused_for_what_it_is_not_and_for_going_too_fast() {
        let w = World::new(&[
            ("KEY_RATE_PER_MINUTE", "3"),
            ("KEY_CONCURRENCY", "2"),
            ("ORG_CONCURRENCY", "3"),
            ("TEST_CALLS_PER_DAY", "4"),
        ]);
        w.core().credit("grant", 1000, "g", "", T0).unwrap();
        let verify_only = w.key(KeyEnv::Live, &["citations:verify"]);
        assert_eq!(code(w.call(&verify_only, Product::Search, "req_1", T0)), "scope");
        // the rate: three a minute, the fourth refused until the next minute
        let r: Vec<String> =
            (0..2).map(|i| go(w.call(&verify_only, Product::Verify, &format!("req_r{i}"), T0))).collect();
        assert_eq!(code(w.call(&verify_only, Product::Verify, "req_r2", T0)), "concurrency", "two in flight a key");
        for id in &r {
            w.core().settle(id, Some((200, "{}")), T0).unwrap();
        }
        let third = go(w.call(&verify_only, Product::Verify, "req_r3", T0));
        w.core().settle(&third, Some((200, "{}")), T0).unwrap();
        match w.call(&verify_only, Product::Verify, "req_r4", T0 + 1000) {
            Err(Error::Refused(r)) => assert!(r.code == "rate" && r.retry.is_some_and(|s| (1..=60).contains(&s))),
            other => panic!("{other:?}"),
        }
        go(w.call(&verify_only, Product::Verify, "req_r5", T0 + MINUTE));
        // a test key: free, and four calls a day for the organisation
        let test = w.key(KeyEnv::Test, &[]);
        let before = w.core().balance().unwrap();
        for i in 0..3 {
            let id = go(w.call(&test, Product::Search, &format!("req_t{i}"), T0 + 2 * MINUTE));
            w.core().settle(&id, Some((200, "{}")), T0 + 2 * MINUTE).unwrap();
        }
        assert_eq!(w.core().balance().unwrap()["net"], before["net"], "a test key spends no credits");
        // the key's rate comes first: a fourth call in the same minute is refused for it, not for the day's allowance
        assert_eq!(code(w.call(&test, Product::Search, "req_t3", T0 + 2 * MINUTE)), "rate");
        // the next minute: three settled and one in flight are the day's four
        go(w.call(&test, Product::Search, "req_t4", T0 + 3 * MINUTE));
        assert_eq!(code(w.call(&test, Product::Search, "req_t5", T0 + 3 * MINUTE)), "test_allowance");
        go(w.call(&test, Product::Search, "req_t6", T0 + DAY));
        // revoked, expired, unknown
        let (gone_id, gone) =
            w.core().create_key(None, KeyEnv::Live, "gone", None, None, "owner", true, &w.e, T0).unwrap();
        let gone = gone.key;
        assert_eq!(code(w.core().revoke_key(&gone_id, false, T0)), "stepup", "a live key's revocation needs a touch");
        assert!(w.core().revoke_key(&gone_id, true, T0).unwrap());
        assert!(!w.core().revoke_key(&gone_id, true, T0).unwrap());
        assert_eq!(code(w.call(&gone, Product::Verify, "req_x", T0)), "revoked_key");
        let (_, soon) =
            w.core().create_key(None, KeyEnv::Live, "soon", None, Some(T0 + 1000), "owner", true, &w.e, T0).unwrap();
        assert_eq!(code(w.call(&soon.key, Product::Verify, "req_y", T0 + 1000)), "expired_key");
        let other = World::new(&[]);
        assert_eq!(
            code(w.call(&other.key(KeyEnv::Live, &[]), Product::Verify, "req_z", T0)),
            "invalid_key",
            "another organisation's key is not this one's"
        );
        assert!(w.core().consistent().unwrap());
    }

    #[test]
    fn a_projects_monthly_limit_and_the_keys_it_lists_without_their_digests() {
        let w = World::new(&[("PRICE_EVIDENCE_SEARCH", "10")]);
        w.core().credit("grant", 1000, "g", "", T0).unwrap();
        let p = w.core().create_project("pilot", Some(25), &w.e, T0).unwrap();
        let (_, k) =
            w.core().create_key(Some(&p), KeyEnv::Live, "pilot key", None, None, "owner", true, &w.e, T0).unwrap();
        for i in 0..2 {
            let id = go(w.call(&k.key, Product::Search, &format!("req_{i}"), T0));
            w.core().settle(&id, Some((200, "{}")), T0).unwrap();
        }
        assert_eq!(code(w.call(&k.key, Product::Search, "req_2", T0)), "project_limit");
        assert_eq!(code(w.core().set_limit(&p, None, false)), "stepup");
        w.core().set_limit(&p, None, true).unwrap();
        go(w.call(&k.key, Product::Search, "req_3", T0));
        let listed = serde_json::to_string(&w.core().keys().unwrap()).unwrap();
        assert!(!listed.contains(&k.digest) && !listed.contains(&k.key) && listed.contains(&k.shown));
        // a key of a project that is no project; a name that is none; a scope that is none
        assert_eq!(
            code(w.core().create_key(Some("prj_nothing"), KeyEnv::Live, "x", None, None, "o", true, &w.e, T0)),
            "project"
        );
        assert_eq!(code(w.core().create_key(None, KeyEnv::Live, "  ", None, None, "o", true, &w.e, T0)), "name");
        assert_eq!(
            code(w.core().create_key(None, KeyEnv::Live, "x", Some(&["admin".into()]), None, "o", true, &w.e, T0)),
            "scope"
        );
        // the limits a key reads of itself
        let l = w.core().limits(&k.digest, T0).unwrap();
        // 1000 granted, 20 spent, 10 held by the call still in flight
        assert_eq!((l["environment"].as_str(), l["credits"]["available"].as_i64()), (Some("live"), Some(970)));
        assert!(w.core().consistent().unwrap());
    }

    #[test]
    fn an_object_never_provisioned_is_asked_and_writes_nothing() {
        let db = Memory::new();
        let cfg = AccountConfig::from_vars(|_| None);
        let core = AccountCore::new(&db, &cfg);
        assert!(!core.ready().unwrap());
        assert_eq!(db.scalar("SELECT COUNT(*) FROM sqlite_master", &[]).unwrap(), 0);
        let e = Counter(Cell::new(9 << 40));
        core.provision(&new_id(&e, "org", 16), "x", &e, T0).unwrap();
        assert!(core.ready().unwrap());
    }

    #[test]
    fn provisioning_is_done_once_and_belongs_to_one_organisation() {
        let w = World::new(&[]);
        let again = w.core().provision(&w.org, "Lab", &w.e, T0 + 1).unwrap();
        assert_eq!(again["projects"].as_array().unwrap().len(), 1);
        assert_eq!(code(w.core().provision(&new_id(&w.e, "org", 16), "Other", &w.e, T0)), "org");
        assert_eq!(code(w.core().provision("org_short", "x", &w.e, T0)), "org");
        assert_eq!(code(w.core().credit("grant", -5, "g", "", T0)), "credits");
        assert!(w.core().credit("adjust", -5, "fix-1", "a correction", T0).unwrap());
        assert_eq!(w.core().balance().unwrap()["net"], -5, "an owner's adjustment alone may go below zero");
    }

    #[test]
    fn what_spends_needs_a_touch_and_nothing_malformed_is_widened() {
        let w = World::new(&[]);
        // a live key is made, and revoked, only after a passkey's touch; a test key needs none
        assert_eq!(code(w.core().create_key(None, KeyEnv::Live, "x", None, None, "o", false, &w.e, T0)), "stepup");
        let (test_id, _) = w.core().create_key(None, KeyEnv::Test, "t", None, None, "o", false, &w.e, T0).unwrap();
        assert!(w.core().revoke_key(&test_id, false, T0).unwrap());
        // an empty list of scopes is refused, not made into all of them
        let none: Vec<String> = Vec::new();
        assert_eq!(
            code(w.core().create_key(None, KeyEnv::Test, "x", Some(&none), None, "o", false, &w.e, T0)),
            "scope"
        );
        // credits at the edges of i64: refused, never wrapped
        for credits in [i64::MIN, i64::MAX, -MOST_CREDITS - 1, MOST_CREDITS + 1] {
            assert_eq!(
                code(w.core().credit("adjust", credits, &format!("edge-{credits}"), "", T0)),
                "credits",
                "{credits}"
            );
        }
        assert!(w.core().credit("adjust", -MOST_CREDITS, "floor", "", T0).unwrap());
        assert_eq!(
            w.core().balance().unwrap()["available"],
            -MOST_CREDITS,
            "an owner's adjustment alone goes below zero"
        );
    }
}
