//! 账户 · 额度 — what an organisation holds: its members, its projects, its API keys, its credits, and what each call
//! its keys make holds and spends.  One Durable Object an organisation (the API Worker's `Account`), so that a key's
//! check, its owner's membership, its rate and the lease a call takes are one step — the key cannot be revoked between
//! its check and the call's admission, and two calls cannot both take the last credits.
//!
//! Every execution — a model's chat, an evidence search, a citation check — is **admitted** here before the person's
//! daily allowance is asked (quota.rs): the key (not revoked, not expired, its scope), its project, its **owner** — the
//! registered person whose allowance it spends — still an active member, the key's rate and what is in flight, and,
//! when the organisation pays in credits (`FUNDING_POLICY = credits`), its price held.  The admission is a **lease**:
//! finished when the call ends (charged then only if it ran and answered), released when it was never made (the
//! allowance spent, a repeat answered from before), lapsed when nobody ends it in time — released, not charged, counted.
//!
//! The arithmetic, in integer credits (the daily allowance spends none):
//!
//!   net        the ledger's sum: grants and adjustments in, settled usage out
//!   held       what calls in flight have reserved
//!   available  net − held.  A call is let through only if its price fits in it, and its price is then held; finishing
//!              moves it from held to spent, a failure or a lapse gives it back.  So available is never below zero
//!              through anything a call does (an owner's negative adjustment alone can take it there)
//!
//! A lease is finished once (a second finish finds it finished and changes nothing), a usage entry is written once (its
//! reference is unique), a grant once (its reference likewise).
//!
//! The members are told to the object by those who know them: the console, of the person whose session asks (and of
//! the owner it provisions), and the platform's owner through the owner's endpoints.  An object made before members were
//! kept (schema 1) is migrated when it is next asked: the keys the console made name their maker, who becomes their
//! owner and a member; a key the owner's token made names no one and executes nothing until it is given an owner.

use serde_json::{Value as Json, json};

use crate::args;
use crate::crypto::{Entropy, new_id};
use crate::keys::{self, KeyEnv, NewKey};
use crate::sql::{Row, Sql, SqlError, SqlExt, Value};
use crate::time::{DAY, MINUTE, day, is_day, month_start};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Product {
    Search,
    Verify,
    Chat,
}

impl Product {
    pub fn name(self) -> &'static str {
        match self {
            Product::Search => "evidence.search",
            Product::Verify => "citations.verify",
            Product::Chat => "chat.completions",
        }
    }

    pub fn scope(self) -> &'static str {
        match self {
            Product::Search => "evidence:search",
            Product::Verify => "citations:verify",
            Product::Chat => "chat:completions",
        }
    }

    pub fn parse(s: &str) -> Option<Product> {
        match s {
            "evidence.search" => Some(Product::Search),
            "citations.verify" => Some(Product::Verify),
            "chat.completions" => Some(Product::Chat),
            _ => None,
        }
    }
}

/// What a key may be given: the products, reading its own usage, listing the models.
pub const SCOPES: [&str; 5] = ["evidence:search", "citations:verify", "usage:read", "chat:completions", "models:read"];

/// What a key made without naming its scopes is given — as before models were offered: a new scope is given only by
/// naming it, so that no update of the service widens a key that exists or one a script makes as it always did.
pub const LEGACY_SCOPES: [&str; 3] = ["evidence:search", "citations:verify", "usage:read"];

/// How executions are paid for: by the person's daily allowance alone, or in the organisation's credits as well.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Funding {
    DailyAllowance,
    Credits,
}

impl Funding {
    pub fn name(self) -> &'static str {
        match self {
            Funding::DailyAllowance => "daily_allowance",
            Funding::Credits => "credits",
        }
    }
}

/// Who may call a model: everyone with the scope, the organisations the owner let in (a pilot), or nobody (the API
/// answers before it asks the object).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ModelGate {
    On,
    Pilot,
    Off,
}

impl ModelGate {
    pub fn parse(s: &str) -> ModelGate {
        match s.trim().to_ascii_lowercase().as_str() {
            "on" => ModelGate::On,
            "pilot" => ModelGate::Pilot,
            _ => ModelGate::Off,
        }
    }
}

#[derive(Debug, Clone)]
pub struct AccountConfig {
    pub price_search: i64,
    pub price_verify: i64,
    pub price_chat: i64,
    /// the prices' own name, kept with every lease and charge: a price changed later does not rewrite one
    pub price_version: String,
    pub funding: Funding,
    pub key_rate: i64,
    pub key_concurrency: i64,
    pub org_concurrency: i64,
    pub hold_ms: i64,
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
        let price_chat = num("PRICE_CHAT_COMPLETIONS", 20, 0);
        let version = crate::codec::hex(&crate::crypto::sha256(
            format!("search={price_search};verify={price_verify};chat={price_chat}").as_bytes(),
        ));
        let funding = match get("FUNDING_POLICY").map(|v| v.trim().to_ascii_lowercase()).as_deref() {
            Some("credits") => Funding::Credits,
            _ => Funding::DailyAllowance,
        };
        AccountConfig {
            price_search,
            price_verify,
            price_chat,
            price_version: format!("p{}", &version[..8]),
            funding,
            key_rate: num("KEY_RATE_PER_MINUTE", 60, 1),
            key_concurrency: num("KEY_CONCURRENCY", 2, 1),
            org_concurrency: num("ORG_CONCURRENCY", 4, 1),
            hold_ms: num("HOLD_SECONDS", 120, 10) * 1000,
            max_keys: num("MAX_KEYS", 50, 1),
        }
    }

    pub fn price(&self, p: Product) -> i64 {
        match p {
            Product::Search => self.price_search,
            Product::Verify => self.price_verify,
            Product::Chat => self.price_chat,
        }
    }

    /// What a call is charged when it runs: its price in credits mode, none on the daily allowance or a test key.
    pub fn charge(&self, p: Product, env: KeyEnv) -> i64 {
        match (self.funding, env) {
            (Funding::Credits, KeyEnv::Live) => self.price(p),
            _ => 0,
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

/// The schema's version: 1, before members and keys' owners were kept; 2 since.
pub const SCHEMA_VERSION: i64 = 2;

const SCHEMA: &[&str] = &[
    "CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS org (org_id TEXT PRIMARY KEY, name TEXT NOT NULL, created INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'active',
      model_access INTEGER NOT NULL DEFAULT 0)",
    // the registered people of the organisation, as those who know them said (the console, the owner's endpoints)
    "CREATE TABLE IF NOT EXISTS members (user_id TEXT PRIMARY KEY, role TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
      since INTEGER NOT NULL, by TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS projects (project_id TEXT PRIMARY KEY, name TEXT NOT NULL, created INTEGER NOT NULL, monthly_limit INTEGER, archived INTEGER)",
    // a key's owner is the person whose daily allowance it spends: set when it is made, by who made it, never by what a
    // request says; created_by stays as it was written, for the record
    "CREATE TABLE IF NOT EXISTS keys (key_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, env TEXT NOT NULL, digest TEXT NOT NULL UNIQUE, shown TEXT NOT NULL,
      name TEXT NOT NULL, scopes TEXT NOT NULL, created INTEGER NOT NULL, created_by TEXT NOT NULL, expires INTEGER, revoked INTEGER, last_used INTEGER,
      owner_user_id TEXT, owner_bound_at INTEGER, owner_bound_by TEXT)",
    // every credit in or out, once: `ref` is the entry's own idempotency (grant:<ref>, use:<lease>, adjust:<ref>)
    "CREATE TABLE IF NOT EXISTS ledger (entry_id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, kind TEXT NOT NULL, credits INTEGER NOT NULL,
      ref TEXT NOT NULL UNIQUE, project_id TEXT, key_id TEXT, product TEXT, price_version TEXT, note TEXT NOT NULL DEFAULT '')",
    // a call's lease (named by the API's request id): what it holds while it runs
    "CREATE TABLE IF NOT EXISTS reservations (reservation_id TEXT PRIMARY KEY, key_id TEXT NOT NULL, project_id TEXT NOT NULL, env TEXT NOT NULL,
      product TEXT NOT NULL, credits INTEGER NOT NULL, price_version TEXT NOT NULL, idem TEXT, created INTEGER NOT NULL, expires INTEGER NOT NULL,
      state TEXT NOT NULL, ended INTEGER)",
    "CREATE INDEX IF NOT EXISTS reservations_held ON reservations (state, expires)",
    "CREATE TABLE IF NOT EXISTS usage (day TEXT NOT NULL, key_id TEXT NOT NULL, product TEXT NOT NULL, project_id TEXT NOT NULL, env TEXT NOT NULL,
      calls INTEGER NOT NULL DEFAULT 0, credits INTEGER NOT NULL DEFAULT 0, failed INTEGER NOT NULL DEFAULT 0, refused INTEGER NOT NULL DEFAULT 0,
      quota INTEGER NOT NULL DEFAULT 0, input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (day, key_id, product))",
    "CREATE TABLE IF NOT EXISTS minutes (key_id TEXT NOT NULL, minute INTEGER NOT NULL, n INTEGER NOT NULL, PRIMARY KEY (key_id, minute))",
    // the running sums, written in the step that changes them: net, held, and what lapsed or came late
    "CREATE TABLE IF NOT EXISTS totals (k TEXT PRIMARY KEY, n INTEGER NOT NULL)",
];

/// The columns schema 2 added to schema 1's tables, each added once (a migration cut short is taken up again).
const ADDED_COLUMNS: &[(&str, &str, &str)] = &[
    ("org", "model_access", "INTEGER NOT NULL DEFAULT 0"),
    ("keys", "owner_user_id", "TEXT"),
    ("keys", "owner_bound_at", "INTEGER"),
    ("keys", "owner_bound_by", "TEXT"),
    ("usage", "quota", "INTEGER NOT NULL DEFAULT 0"),
    ("usage", "input_tokens", "INTEGER NOT NULL DEFAULT 0"),
    ("usage", "output_tokens", "INTEGER NOT NULL DEFAULT 0"),
];

const MOST_CREDITS: i64 = 1_000_000_000_000;
const ROLES: [&str; 4] = ["owner", "admin", "developer", "viewer"];

/// A call to admit.
#[derive(Debug, Clone)]
pub struct Admit<'a> {
    /// SHA-256 of the API key (keys::parse)
    pub digest: &'a str,
    pub product: Product,
    /// the API's id of the request, unique: the lease's id
    pub request_id: &'a str,
    /// how long the call may run before its lease lapses
    pub hold_ms: i64,
    /// who may call a model now (Product::Chat only)
    pub models: ModelGate,
}

/// A call let through: what the API asks the person's allowance and runs it with.
#[derive(Debug, Clone, PartialEq)]
pub struct Lease {
    pub lease: String,
    pub key_id: String,
    pub project_id: String,
    pub env: KeyEnv,
    /// the registered person whose daily allowance it spends
    pub owner: String,
    pub credits: i64,
    pub price_version: String,
}

/// How a call ended, for the organisation's usage.
#[derive(Debug, Clone, Default)]
pub struct Finish {
    /// it was asked of the service (and so spent the person's allowance)
    pub executed: bool,
    /// and it answered: in credits mode, charged
    pub ok: bool,
    /// it was refused before it ran (the allowance spent): counted among the day's refusals
    pub refused: bool,
    pub input_tokens: i64,
    pub output_tokens: i64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Settled {
    Charged(i64),
    Released,
    /// finished, released or lapsed before: nothing changed
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
        "owner": r.opt_text("owner_user_id"), "owner_binding": if r.opt_text("owner_user_id").is_some() { "bound" } else { "unbound" },
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

/// A registered person's id, as the identity object makes them: `usr_` and 16 random bytes in base32 (26 characters),
/// the shape of an organisation's id.
pub fn is_user_id(s: &str) -> bool {
    s.len() == 30 && s.starts_with("usr_") && crate::codec::is_base32(&s[4..])
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

    fn version(&self) -> Result<i64, SqlError> {
        if self.sql.scalar("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'meta'", &[])? == 0 {
            return Ok(1);
        }
        Ok(self
            .sql
            .row("SELECT v FROM meta WHERE k = 'schema'", &[])?
            .and_then(|r| r.text("v").parse().ok())
            .unwrap_or(1))
    }

    fn has_column(&self, table: &str, column: &str) -> Result<bool, SqlError> {
        let sql = self
            .sql
            .row("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", args![table])?
            .map(|r| r.text("sql"))
            .unwrap_or_default();
        Ok(sql.split(|c: char| !(c.is_ascii_alphanumeric() || c == '_')).any(|w| w == column))
    }

    /// A provisioned object brought to the schema this code writes: schema 1's tables given their new columns, the
    /// members table made, and the keys the console made bound to their maker.  Each step is done once and may be done
    /// again (a migration a failure cut short is taken up where it stopped); the version is written last.
    pub fn migrate(&self, now: i64) -> Result<(), SqlError> {
        if self.version()? >= SCHEMA_VERSION {
            return Ok(());
        }
        self.ensure()?;
        for (table, column, kind) in ADDED_COLUMNS {
            if !self.has_column(table, column)? {
                self.sql.run(&format!("ALTER TABLE {table} ADD COLUMN {column} {kind}"), &[])?;
            }
        }
        // the console wrote its person's id as a key's maker, after checking they were a member who may make keys
        self.sql.run(
            "INSERT OR IGNORE INTO members (user_id, role, status, since, by)
             SELECT DISTINCT created_by, 'owner', 'active', ?, 'migration' FROM keys WHERE substr(created_by, 1, 4) = 'usr_' AND length(created_by) = 30",
            args![now],
        )?;
        self.sql.run(
            "UPDATE keys SET owner_user_id = created_by, owner_bound_at = ?, owner_bound_by = 'migration'
             WHERE owner_user_id IS NULL AND substr(created_by, 1, 4) = 'usr_' AND length(created_by) = 30",
            args![now],
        )?;
        self.sql.run(
            "INSERT INTO meta (k, v) VALUES ('schema', ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v",
            args![SCHEMA_VERSION.to_string()],
        )
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

    /// The organisation's object made ready: its row, a default project, and — when it is said — its owner, a member.
    /// Done again, it changes nothing.
    pub fn provision(
        &self,
        org_id: &str,
        name: &str,
        owner: Option<&str>,
        by: &str,
        e: &dyn Entropy,
        now: i64,
    ) -> Outcome<Json> {
        if !keys::is_org_id(org_id) {
            return Err(refused(400, "invalid_request", "org", "not an organisation's id"));
        }
        if owner.is_some_and(|u| !is_user_id(u)) {
            return Err(refused(400, "invalid_request", "user", "the owner is a registered person's id (usr_…)"));
        }
        let fresh = !self.ready()?;
        self.ensure()?;
        if fresh {
            self.sql.run("INSERT INTO meta (k, v) VALUES ('schema', ?)", args![SCHEMA_VERSION.to_string()])?;
        } else {
            self.migrate(now)?;
        }
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
        if let Some(user) = owner {
            self.vouch(user, "owner", by, now)?;
        }
        self.summary(now)
    }

    fn require_org(&self) -> Outcome<Row> {
        self.org()?.ok_or_else(|| refused(404, "not_found", "org", "no such organisation"))
    }

    // ---------------------------------------------------------------- members
    /// A person said to be a member, in a role: added if they were not, their role brought up to date if they were.
    /// Their status is not changed — a suspended member is not let back by being seen.
    pub fn vouch(&self, user: &str, role: &str, by: &str, now: i64) -> Outcome<()> {
        if !is_user_id(user) {
            return Err(refused(400, "invalid_request", "user", "not a registered person's id (usr_…)"));
        }
        let role = if ROLES.contains(&role) { role } else { "developer" };
        self.sql.run(
            "INSERT INTO members (user_id, role, status, since, by) VALUES (?, ?, 'active', ?, ?)
             ON CONFLICT(user_id) DO UPDATE SET role = excluded.role",
            args![user, role, now, by],
        )?;
        Ok(())
    }

    /// The owner's: a member's status (active, suspended) and, given, their role.  A person not yet a member is added.
    pub fn set_member(&self, user: &str, status: &str, role: Option<&str>, by: &str, now: i64) -> Outcome<()> {
        if !matches!(status, "active" | "suspended") {
            return Err(refused(400, "invalid_request", "status", "a member is active or suspended"));
        }
        if role.is_some_and(|r| !ROLES.contains(&r)) {
            return Err(refused(400, "invalid_request", "role", "a role is owner, admin, developer or viewer"));
        }
        match self.member(user)? {
            Some(_) => {
                if let Some(r) = role {
                    self.sql.run("UPDATE members SET role = ? WHERE user_id = ?", args![r, user])?;
                }
            }
            None => self.vouch(user, role.unwrap_or("developer"), by, now)?,
        }
        self.sql.run("UPDATE members SET status = ? WHERE user_id = ?", args![status, user])?;
        Ok(())
    }

    fn member(&self, user: &str) -> Result<Option<Row>, SqlError> {
        self.sql.row("SELECT * FROM members WHERE user_id = ?", args![user])
    }

    pub fn members(&self) -> Result<Vec<Json>, SqlError> {
        Ok(self
            .sql
            .rows("SELECT * FROM members ORDER BY since, user_id", &[])?
            .iter()
            .map(|m| json!({ "user": m.text("user_id"), "role": m.text("role"), "status": m.text("status"), "since": m.int("since") }))
            .collect())
    }

    /// The person a new key belongs to: the one named, if an active member; or, none named, the organisation's one
    /// active owner — and if there is not exactly one, the key must name one.
    fn key_owner(&self, owner: Option<&str>) -> Outcome<String> {
        match owner {
            Some(user) => match self.member(user)? {
                Some(m) if m.text("status") == "active" => Ok(user.to_string()),
                _ => Err(refused(
                    400,
                    "invalid_request",
                    "owner",
                    "the key's owner is not an active member of the organisation",
                )),
            },
            None => {
                let owners =
                    self.sql.rows("SELECT user_id FROM members WHERE status = 'active' AND role = 'owner'", &[])?;
                match owners.as_slice() {
                    [one] => Ok(one.text("user_id")),
                    _ => Err(refused(
                        400,
                        "invalid_request",
                        "owner_required",
                        "name the key's owner: a registered member of the organisation (usr_…)",
                    )),
                }
            }
        }
    }

    /// The owner's: a key given to a member, whose daily allowance it spends from now on.
    pub fn bind_key(&self, key_id: &str, user: &str, by: &str, now: i64) -> Outcome<()> {
        let k = self
            .sql
            .row("SELECT revoked FROM keys WHERE key_id = ?", args![key_id])?
            .ok_or_else(|| refused(404, "not_found", "key", "no such key"))?;
        if k.opt_int("revoked").is_some() {
            return Err(refused(409, "conflict", "key", "the key was revoked"));
        }
        let owner = self.key_owner(Some(user))?;
        self.sql.run(
            "UPDATE keys SET owner_user_id = ?, owner_bound_at = ?, owner_bound_by = ? WHERE key_id = ?",
            args![owner, now, by, key_id],
        )?;
        Ok(())
    }

    /// The owner's: whether this organisation may call models while they are offered to a pilot only.
    pub fn set_model_access(&self, on: bool) -> Outcome<()> {
        self.require_org()?;
        self.sql.run("UPDATE org SET model_access = ?", args![i64::from(on)])?;
        Ok(())
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
    /// None for the legacy ones (no model access unless named); an empty list is refused, not widened.  Its owner: the
    /// person named, an active member — the console names the person whose session asks — or the organisation's one
    /// owner.  A live key may spend credits: made only after a passkey's touch (`touched`: the console says so of its
    /// session, the owner's token always).
    #[allow(clippy::too_many_arguments)]
    pub fn create_key(
        &self,
        project: Option<&str>,
        env: KeyEnv,
        name: &str,
        scopes: Option<&[String]>,
        expires: Option<i64>,
        by: &str,
        owner: Option<&str>,
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
            None => LEGACY_SCOPES.to_vec(),
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
        let owner = self.key_owner(owner)?;
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
            "INSERT INTO keys (key_id, project_id, env, digest, shown, name, scopes, created, created_by, expires, owner_user_id, owner_bound_at, owner_bound_by)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            args![&key_id, &project, env.as_str(), &new.digest, &new.shown, name, json!(wanted).to_string(), now, by, expires, &owner, now, by],
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

    /// A key's owner, if it may execute now: bound to a person, and that person an active member.
    fn owner_of(&self, k: &Row) -> Outcome<String> {
        let Some(owner) = k.opt_text("owner_user_id") else {
            return Err(refused(
                403,
                "permission",
                "user_binding_required",
                "this API key must be assigned to a registered user before it executes requests",
            ));
        };
        match self.member(&owner)? {
            Some(m) if m.text("status") == "active" => Ok(owner),
            _ => Err(refused(
                403,
                "permission",
                "member_suspended",
                "the key's owner is not an active member of the organisation",
            )),
        }
    }

    fn count(&self, k: &Row, product: Product, now: i64, f: &Finish, credits: i64) -> Result<(), SqlError> {
        self.sql.run(
            "INSERT INTO usage (day, key_id, product, project_id, env, calls, credits, failed, refused, quota, input_tokens, output_tokens)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT(day, key_id, product) DO UPDATE SET calls = calls + excluded.calls, credits = credits + excluded.credits,
               failed = failed + excluded.failed, refused = refused + excluded.refused, quota = quota + excluded.quota,
               input_tokens = input_tokens + excluded.input_tokens, output_tokens = output_tokens + excluded.output_tokens",
            args![
                day(now),
                k.text("key_id"),
                product.name(),
                k.text("project_id"),
                k.text("env"),
                i64::from(f.executed && f.ok),
                credits,
                i64::from(f.executed && !f.ok),
                i64::from(f.refused),
                i64::from(f.executed),
                f.input_tokens.max(0),
                f.output_tokens.max(0)
            ],
        )
    }

    fn count_refused(&self, k: &Row, product: Product, now: i64) -> Result<(), SqlError> {
        self.count(k, product, now, &Finish { refused: true, ..Finish::default() }, 0)
    }

    /// A call's admission, in one step: the key, its scope, its owner, its project, the model gate, the key's rate,
    /// what is in flight, and — in credits mode — what it will cost; let through, its lease taken (its price held).
    pub fn admit(&self, a: &Admit, now: i64) -> Outcome<Lease> {
        self.sweep(now)?;
        let k = self.authenticate(a.digest, now)?;
        if !Self::has_scope(&k, a.product.scope()) {
            return Err(refused(403, "permission", "scope", format!("this key may not call {}", a.product.name())));
        }
        let owner = self.owner_of(&k)?;
        let project = k.text("project_id");
        let p = self.sql.row("SELECT * FROM projects WHERE project_id = ?", args![&project])?;
        let Some(p) = p.filter(|p| p.opt_int("archived").is_none()) else {
            return Err(refused(403, "permission", "project_archived", "the key's project is archived"));
        };
        if a.product == Product::Chat {
            let open = match a.models {
                ModelGate::On => true,
                ModelGate::Pilot => self.require_org()?.int("model_access") == 1,
                ModelGate::Off => false,
            };
            if !open {
                return Err(refused(403, "permission", "model_access", "this organisation may not call models yet"));
            }
        }
        let key_id = k.text("key_id");
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
        let credits = self.cfg.charge(a.product, env);
        if credits > 0 {
            let available = self.total("net")?.saturating_sub(self.total("held")?);
            if available < credits {
                self.count_refused(&k, a.product, now)?;
                return Err(refused(
                    402,
                    "insufficient_credits",
                    "credits",
                    format!("{} costs {credits} credits; {} are available", a.product.name(), available.max(0)),
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
                if month + flying + credits > limit {
                    self.count_refused(&k, a.product, now)?;
                    return Err(refused(
                        402,
                        "insufficient_credits",
                        "project_limit",
                        format!("the project's limit is {limit} credits a month"),
                    ));
                }
            }
        }
        // let through: the lease taken (its price held), the minute counted
        self.sql.run(
            "INSERT INTO reservations (reservation_id, key_id, project_id, env, product, credits, price_version, created, expires, state)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'held')",
            args![a.request_id, &key_id, &project, env.as_str(), a.product.name(), credits, &self.cfg.price_version, now, now + a.hold_ms.max(10_000)],
        )?;
        self.add_total("held", credits)?;
        self.sql.run(
            "INSERT INTO minutes (key_id, minute, n) VALUES (?, ?, 1) ON CONFLICT(key_id, minute) DO UPDATE SET n = n + 1",
            args![&key_id, minute],
        )?;
        if k.opt_int("last_used").is_none_or(|t| t < now - MINUTE) {
            self.sql.run("UPDATE keys SET last_used = ? WHERE key_id = ?", args![now, &key_id])?;
        }
        Ok(Lease {
            lease: a.request_id.to_string(),
            key_id,
            project_id: project,
            env,
            owner,
            credits,
            price_version: self.cfg.price_version.clone(),
        })
    }

    /// A call's end, once: counted in the organisation's usage as it ended, and — in credits mode, if it ran and
    /// answered — charged.  A call that was never made (`executed` false) is released: nothing charged, its credits
    /// back.
    pub fn finish(&self, lease: &str, f: &Finish, now: i64) -> Outcome<Settled> {
        let Some(r) = self.sql.row("SELECT * FROM reservations WHERE reservation_id = ?", args![lease])? else {
            return Ok(Settled::Unknown);
        };
        let state = r.text("state");
        if state != "held" {
            if state == "lapsed" && f.executed && f.ok {
                self.add_total("late", 1)?; // a result that came after its lease lapsed: not charged, counted
            }
            return Ok(Settled::Already(state));
        }
        let held = r.int("credits");
        let charged = if f.executed && f.ok { held } else { 0 };
        let product = Product::parse(&r.text("product")).unwrap_or(Product::Search);
        self.sql.run(
            "UPDATE reservations SET state = ?, ended = ? WHERE reservation_id = ?",
            args![if f.executed { "settled" } else { "released" }, now, lease],
        )?;
        if charged > 0 {
            self.sql.run(
                "INSERT INTO ledger (ts, kind, credits, ref, project_id, key_id, product, price_version) VALUES (?, 'usage', ?, ?, ?, ?, ?, ?)",
                args![now, -charged, format!("use:{lease}"), r.text("project_id"), r.text("key_id"), r.text("product"), r.text("price_version")],
            )?;
            self.add_total("net", -charged)?;
        }
        self.add_total("held", -held)?;
        // the key's row is what the usage is kept under (its project and environment as the lease took them)
        let k = Row(vec![
            ("key_id".into(), Value::Text(r.text("key_id"))),
            ("project_id".into(), Value::Text(r.text("project_id"))),
            ("env".into(), Value::Text(r.text("env"))),
        ]);
        if f.executed || f.refused {
            self.count(&k, product, now, f, charged)?;
        }
        Ok(if charged > 0 {
            Settled::Charged(charged)
        } else if f.executed {
            Settled::Charged(0)
        } else {
            Settled::Released
        })
    }

    /// Leases nobody finished in time: lapsed — released, not charged, counted.  And what has outlived its use.
    pub fn sweep(&self, now: i64) -> Result<i64, SqlError> {
        let stale = self.sql.rows(
            "SELECT reservation_id, credits FROM reservations WHERE state = 'held' AND expires <= ? LIMIT 200",
            args![now],
        )?;
        for r in &stale {
            self.sql.run(
                "UPDATE reservations SET state = 'lapsed', ended = ? WHERE reservation_id = ?",
                args![now, r.text("reservation_id")],
            )?;
            self.add_total("held", -r.int("credits"))?;
            self.add_total("lapsed", 1)?;
        }
        self.sql.run("DELETE FROM minutes WHERE minute < ?", args![now.div_euclid(MINUTE) - 2])?;
        self.sql.run("DELETE FROM reservations WHERE state <> 'held' AND ended < ?", args![now - 35 * DAY])?;
        Ok(stale.len() as i64)
    }

    pub fn balance(&self) -> Result<Json, SqlError> {
        let net = self.total("net")?;
        let held = self.total("held")?;
        Ok(json!({ "net": net, "held": held, "available": net.saturating_sub(held) }))
    }

    /// Who a key is, for what the API answers of it without running anything (its limits, a request's record, the
    /// models it may call): the key, its organisation, its owner and whether it may execute.
    pub fn whoami(&self, digest: &str, models: ModelGate, now: i64) -> Outcome<Json> {
        let k = self.authenticate(digest, now)?;
        let org = self.require_org()?;
        let executes = self.owner_of(&k);
        let model_access = match models {
            ModelGate::On => true,
            ModelGate::Pilot => org.int("model_access") == 1,
            ModelGate::Off => false,
        };
        Ok(json!({
            "key": key_info(&k), "organisation": org.text("org_id"), "project": k.text("project_id"),
            "environment": k.text("env"), "owner": k.opt_text("owner_user_id"),
            "executes": executes.is_ok(),
            "refusal": match executes { Err(Error::Refused(r)) => json!({ "code": r.code, "message": r.message }), _ => Json::Null },
            "model_access": model_access && Self::has_scope(&k, "chat:completions"),
            "models_listed": Self::has_scope(&k, "models:read"),
        }))
    }

    /// The person a key executes as, or why it does not (the tests; whoami tells the same to the API).
    pub fn call_owner(&self, digest: &str, now: i64) -> Outcome<String> {
        let k = self.authenticate(digest, now)?;
        self.owner_of(&k)
    }

    /// What a key may do now: its scopes, its rate, what is in flight, and how executions are paid.
    pub fn limits(&self, digest: &str, now: i64) -> Outcome<Json> {
        let k = self.authenticate(digest, now)?;
        let key_id = k.text("key_id");
        let used = self
            .sql
            .scalar("SELECT n FROM minutes WHERE key_id = ? AND minute = ?", args![&key_id, now.div_euclid(MINUTE)])?;
        let env = KeyEnv::parse(&k.text("env")).unwrap_or(KeyEnv::Test);
        let credits_required = self.cfg.funding == Funding::Credits && env == KeyEnv::Live;
        Ok(json!({
            "key": key_info(&k), "environment": env.as_str(),
            "rate": { "per_minute": self.cfg.key_rate, "used_this_minute": used },
            "concurrency": { "key": self.cfg.key_concurrency, "organisation": self.cfg.org_concurrency },
            "funding": { "mode": self.cfg.funding.name(), "credits_required": credits_required },
            "credits": self.balance()?,
            "prices": {
                "evidence.search": self.cfg.charge(Product::Search, env),
                "citations.verify": self.cfg.charge(Product::Verify, env),
                "chat.completions": self.cfg.charge(Product::Chat, env),
            },
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
            "SELECT day, product, env, project_id, SUM(calls) AS calls, SUM(credits) AS credits, SUM(failed) AS failed, SUM(refused) AS refused,
               SUM(quota) AS quota, SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens
             FROM usage WHERE day >= ? AND day <= ? AND (? IS NULL OR project_id = ?) GROUP BY day, product, env, project_id ORDER BY day, product, env",
            args![from, to, project, project],
        )?;
        let data: Vec<Json> = rows
            .iter()
            .map(|r| json!({ "day": r.text("day"), "product": r.text("product"), "environment": r.text("env"), "project": r.text("project_id"),
                "calls": r.int("calls"), "credits": r.int("credits"), "failed": r.int("failed"), "refused": r.int("refused"),
                "quota_consumed": r.int("quota"), "input_tokens": r.int("input_tokens"), "output_tokens": r.int("output_tokens") }))
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
            "org": { "id": org.text("org_id"), "name": org.text("name"), "created": org.int("created"), "status": org.text("status"),
                "model_access": org.int("model_access") == 1 },
            "members": self.members()?,
            "credits": self.balance()?, "projects": projects, "keys": self.keys()?, "today": today["data"],
            "lapsed": self.total("lapsed")?, "late": self.total("late")?,
            "funding": self.cfg.funding.name(),
            "prices": { "evidence.search": self.cfg.price_search, "citations.verify": self.cfg.price_verify,
                "chat.completions": self.cfg.price_chat, "version": self.cfg.price_version },
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
    const OWNER: &str = "usr_aaaaaaaaaaaaaaaaaaaaaaaaaa";
    const OTHER: &str = "usr_bbbbbbbbbbbbbbbbbbbbbbbbbb";

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
            w.core().provision(&w.org, "Lab", Some(OWNER), "console", &w.e, T0).unwrap();
            w
        }

        fn credits() -> World {
            World::new(&[("FUNDING_POLICY", "credits")])
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
                    None,
                    true,
                    &self.e,
                    T0,
                )
                .unwrap()
                .1
                .key
        }

        fn call(&self, key: &str, product: Product, id: &str, now: i64) -> Outcome<Lease> {
            let d = parse(key).unwrap().digest;
            self.core()
                .admit(&Admit { digest: &d, product, request_id: id, hold_ms: 120_000, models: ModelGate::On }, now)
        }

        fn ran(&self, lease: &str, now: i64) -> Settled {
            self.core().finish(lease, &Finish { executed: true, ok: true, ..Finish::default() }, now).unwrap()
        }
    }

    fn code(e: Outcome<impl std::fmt::Debug>) -> &'static str {
        match e {
            Err(Error::Refused(r)) => r.code,
            other => panic!("not a refusal: {other:?}"),
        }
    }

    fn go(a: Outcome<Lease>) -> String {
        match a {
            Ok(l) => l.lease,
            other => panic!("not let through: {other:?}"),
        }
    }

    #[test]
    fn on_the_daily_allowance_a_call_spends_no_credits_and_names_its_owner() {
        let w = World::new(&[]);
        let key = w.key(KeyEnv::Live, &[]);
        // no credits at all, and a live key is let through: the person's allowance pays (quota.rs)
        let lease = w.call(&key, Product::Search, "req_1", T0).unwrap();
        assert_eq!((lease.owner.as_str(), lease.credits), (OWNER, 0));
        assert_eq!(w.ran("req_1", T0 + 5), Settled::Charged(0));
        let u = w.core().usage(&day(T0), &day(T0), None).unwrap();
        assert_eq!((u["data"][0]["calls"].as_i64(), u["data"][0]["quota_consumed"].as_i64()), (Some(1), Some(1)));
        let l = w.core().limits(&parse(&key).unwrap().digest, T0).unwrap();
        assert_eq!(
            (l["funding"]["mode"].as_str(), l["funding"]["credits_required"].as_bool()),
            (Some("daily_allowance"), Some(false))
        );
        assert!(w.core().consistent().unwrap());
    }

    #[test]
    fn in_credits_mode_a_grant_is_spent_by_calls_and_never_past_what_is_available() {
        let w = World::new(&[
            ("FUNDING_POLICY", "credits"),
            ("PRICE_EVIDENCE_SEARCH", "10"),
            ("ORG_CONCURRENCY", "10"),
            ("KEY_CONCURRENCY", "10"),
        ]);
        let key = w.key(KeyEnv::Live, &[]);
        assert_eq!(code(w.call(&key, Product::Search, "req_0", T0)), "credits");
        assert!(w.core().credit("grant", 25, "trial", "", T0).unwrap());
        assert!(!w.core().credit("grant", 25, "trial", "", T0).unwrap(), "a grant's reference is used once");
        // §12.3: calls arrive together before any ends — the leases stay within what is available
        let a = go(w.call(&key, Product::Search, "req_1", T0));
        let b = go(w.call(&key, Product::Search, "req_2", T0));
        assert_eq!(code(w.call(&key, Product::Search, "req_3", T0)), "credits");
        assert_eq!(w.core().balance().unwrap(), json!({ "net": 25, "held": 20, "available": 5 }));
        // one ran, one was never made (released): the released one's credits come back
        assert_eq!(w.ran(&a, T0), Settled::Charged(10));
        assert_eq!(w.core().finish(&b, &Finish::default(), T0).unwrap(), Settled::Released);
        // §12.3: an end told again changes nothing
        assert_eq!(w.ran(&a, T0), Settled::Already("settled".into()));
        assert_eq!(w.ran(&b, T0), Settled::Already("released".into()));
        assert_eq!(w.core().finish("req_nobody", &Finish::default(), T0).unwrap(), Settled::Unknown);
        assert_eq!(w.core().balance().unwrap(), json!({ "net": 15, "held": 0, "available": 15 }));
        // a call that ran and failed: counted, not charged
        let c = go(w.call(&key, Product::Search, "req_4", T0));
        assert_eq!(
            w.core().finish(&c, &Finish { executed: true, ok: false, ..Finish::default() }, T0).unwrap(),
            Settled::Charged(0)
        );
        assert!(w.core().consistent().unwrap());
        let u = w.core().usage(&day(T0), &day(T0), None).unwrap();
        assert_eq!(
            (
                u["data"][0]["calls"].as_i64(),
                u["data"][0]["credits"].as_i64(),
                u["data"][0]["failed"].as_i64(),
                u["data"][0]["refused"].as_i64(),
                u["data"][0]["quota_consumed"].as_i64()
            ),
            (Some(1), Some(10), Some(1), Some(2), Some(2))
        );
        // a test key spends no credits in credits mode either
        let test = w.key(KeyEnv::Test, &[]);
        assert_eq!(w.call(&test, Product::Search, "req_t", T0).unwrap().credits, 0);
    }

    #[test]
    fn a_call_nobody_finishes_lapses_released_and_a_late_result_is_not_charged() {
        let w = World::new(&[("FUNDING_POLICY", "credits")]);
        w.core().credit("grant", 10, "g", "", T0).unwrap();
        let key = w.key(KeyEnv::Live, &[]);
        let r = go(w.call(&key, Product::Search, "req_1", T0));
        assert_eq!(code(w.call(&key, Product::Search, "req_2", T0 + 1000)), "credits");
        // §12.3: the Worker died; when its lease lapses the credits are available again
        go(w.call(&key, Product::Search, "req_3", T0 + 121_000));
        assert_eq!(w.ran(&r, T0 + 122_000), Settled::Already("lapsed".into()));
        let s = w.core().summary(T0 + 122_000).unwrap();
        assert_eq!(
            (s["lapsed"].as_i64(), s["late"].as_i64(), s["credits"]["held"].as_i64()),
            (Some(1), Some(1), Some(10))
        );
        assert!(w.core().consistent().unwrap());
    }

    #[test]
    fn a_key_is_refused_for_what_it_is_not_and_for_going_too_fast() {
        let w = World::new(&[("KEY_RATE_PER_MINUTE", "3"), ("KEY_CONCURRENCY", "2"), ("ORG_CONCURRENCY", "3")]);
        let verify_only = w.key(KeyEnv::Live, &["citations:verify"]);
        assert_eq!(code(w.call(&verify_only, Product::Search, "req_1", T0)), "scope");
        // the rate: three a minute, the fourth refused until the next minute
        let r: Vec<String> =
            (0..2).map(|i| go(w.call(&verify_only, Product::Verify, &format!("req_r{i}"), T0))).collect();
        assert_eq!(code(w.call(&verify_only, Product::Verify, "req_r2", T0)), "concurrency", "two in flight a key");
        for id in &r {
            w.ran(id, T0);
        }
        let third = go(w.call(&verify_only, Product::Verify, "req_r3", T0));
        w.ran(&third, T0);
        match w.call(&verify_only, Product::Verify, "req_r4", T0 + 1000) {
            Err(Error::Refused(r)) => assert!(r.code == "rate" && r.retry.is_some_and(|s| (1..=60).contains(&s))),
            other => panic!("{other:?}"),
        }
        go(w.call(&verify_only, Product::Verify, "req_r5", T0 + MINUTE));
        // revoked, expired, unknown
        let (gone_id, gone) =
            w.core().create_key(None, KeyEnv::Live, "gone", None, None, "owner", None, true, &w.e, T0).unwrap();
        assert_eq!(code(w.core().revoke_key(&gone_id, false, T0)), "stepup", "a live key's revocation needs a touch");
        assert!(w.core().revoke_key(&gone_id, true, T0).unwrap());
        assert!(!w.core().revoke_key(&gone_id, true, T0).unwrap());
        assert_eq!(code(w.call(&gone.key, Product::Verify, "req_x", T0)), "revoked_key");
        let (_, soon) = w
            .core()
            .create_key(None, KeyEnv::Live, "soon", None, Some(T0 + 1000), "owner", None, true, &w.e, T0)
            .unwrap();
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
    fn a_key_without_naming_scopes_calls_no_model_and_the_gate_decides_who_may() {
        let w = World::new(&[]);
        let legacy = w.key(KeyEnv::Test, &[]);
        assert_eq!(code(w.call(&legacy, Product::Chat, "req_1", T0)), "scope", "no model access unless named");
        let chat = w.key(KeyEnv::Test, &["chat:completions", "models:read"]);
        go(w.call(&chat, Product::Chat, "req_2", T0));
        // a pilot: only organisations the owner let in
        let d = parse(&chat).unwrap().digest;
        let pilot = |id: &str| {
            w.core().admit(
                &Admit {
                    digest: &d,
                    product: Product::Chat,
                    request_id: id,
                    hold_ms: 240_000,
                    models: ModelGate::Pilot,
                },
                T0,
            )
        };
        assert_eq!(code(pilot("req_3")), "model_access");
        w.core().set_model_access(true).unwrap();
        go(pilot("req_4"));
        // what a key is, without running anything
        let me = w.core().whoami(&d, ModelGate::Pilot, T0).unwrap();
        assert_eq!(
            (me["owner"].as_str(), me["executes"].as_bool(), me["model_access"].as_bool()),
            (Some(OWNER), Some(true), Some(true))
        );
        let ld = parse(&legacy).unwrap().digest;
        assert_eq!(w.core().whoami(&ld, ModelGate::On, T0).unwrap()["model_access"], false);
        assert_eq!(
            code(w.core().create_key(None, KeyEnv::Test, "x", Some(&["chat".into()]), None, "o", None, true, &w.e, T0)),
            "scope"
        );
    }

    #[test]
    fn a_key_belongs_to_a_member_and_executes_only_while_they_are_one() {
        let w = World::new(&[("ORG_CONCURRENCY", "20"), ("KEY_CONCURRENCY", "20")]);
        // the owner's token names a member, or the organisation's one owner is the key's
        let (_, mine) =
            w.core().create_key(None, KeyEnv::Test, "m", None, None, "owner", None, true, &w.e, T0).unwrap();
        assert_eq!(w.call(&mine.key, Product::Search, "req_1", T0).unwrap().owner, OWNER);
        assert_eq!(
            code(w.core().create_key(None, KeyEnv::Test, "x", None, None, "owner", Some(OTHER), true, &w.e, T0)),
            "owner",
            "a person who is not a member owns no key"
        );
        w.core().vouch(OTHER, "developer", "console", T0).unwrap();
        let (theirs_id, theirs) =
            w.core().create_key(None, KeyEnv::Test, "t", None, None, OTHER, Some(OTHER), true, &w.e, T0).unwrap();
        assert_eq!(w.call(&theirs.key, Product::Search, "req_2", T0).unwrap().owner, OTHER);
        // suspended: their keys execute nothing; seen again by the console, they are not let back by it
        w.core().set_member(OTHER, "suspended", None, "owner", T0).unwrap();
        assert_eq!(code(w.call(&theirs.key, Product::Search, "req_3", T0 + 1)), "member_suspended");
        w.core().vouch(OTHER, "developer", "console", T0 + 2).unwrap();
        assert_eq!(code(w.call(&theirs.key, Product::Search, "req_4", T0 + 3)), "member_suspended");
        let members = w.core().members().unwrap();
        assert!(members.iter().any(|m| m["user"] == OTHER && m["role"] == "developer" && m["status"] == "suspended"));
        w.core().set_member(OTHER, "active", None, "owner", T0 + 4).unwrap();
        go(w.call(&theirs.key, Product::Search, "req_5", T0 + 5));
        // two owners: a key must name one
        w.core().set_member(OTHER, "active", Some("owner"), "owner", T0 + 6).unwrap();
        assert_eq!(
            code(w.core().create_key(None, KeyEnv::Test, "x", None, None, "owner", None, true, &w.e, T0)),
            "owner_required"
        );
        // binding a key to someone else, and to no one who is a member
        w.core().bind_key(&theirs_id, OWNER, "owner", T0 + 7).unwrap();
        assert_eq!(w.call(&theirs.key, Product::Search, "req_6", T0 + MINUTE).unwrap().owner, OWNER);
        assert_eq!(code(w.core().bind_key(&theirs_id, "usr_cccccccccccccccccccccccccc", "owner", T0)), "owner");
        assert_eq!(code(w.core().vouch("someone", "owner", "console", T0)), "user");
    }

    #[test]
    fn an_object_of_schema_1_is_migrated_once_its_console_keys_bound_and_its_owners_keys_not() {
        let db = Memory::new();
        let e = Counter(Cell::new(77 << 40));
        let org = new_id(&e, "org", 16);
        // schema 1, as the API Worker of 2026-11-27 made it: no meta, no members, keys without owners
        for q in [
            "CREATE TABLE org (org_id TEXT PRIMARY KEY, name TEXT NOT NULL, created INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'active')",
            "CREATE TABLE projects (project_id TEXT PRIMARY KEY, name TEXT NOT NULL, created INTEGER NOT NULL, monthly_limit INTEGER, archived INTEGER)",
            "CREATE TABLE keys (key_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, env TEXT NOT NULL, digest TEXT NOT NULL UNIQUE, shown TEXT NOT NULL,
              name TEXT NOT NULL, scopes TEXT NOT NULL, created INTEGER NOT NULL, created_by TEXT NOT NULL, expires INTEGER, revoked INTEGER, last_used INTEGER)",
            "CREATE TABLE ledger (entry_id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, kind TEXT NOT NULL, credits INTEGER NOT NULL,
              ref TEXT NOT NULL UNIQUE, project_id TEXT, key_id TEXT, product TEXT, price_version TEXT, note TEXT NOT NULL DEFAULT '')",
            "CREATE TABLE reservations (reservation_id TEXT PRIMARY KEY, key_id TEXT NOT NULL, project_id TEXT NOT NULL, env TEXT NOT NULL,
              product TEXT NOT NULL, credits INTEGER NOT NULL, price_version TEXT NOT NULL, idem TEXT, created INTEGER NOT NULL, expires INTEGER NOT NULL,
              state TEXT NOT NULL, ended INTEGER)",
            "CREATE TABLE idempotency (k TEXT PRIMARY KEY, request TEXT NOT NULL, reservation_id TEXT NOT NULL, status INTEGER, body TEXT, created INTEGER NOT NULL)",
            "CREATE TABLE usage (day TEXT NOT NULL, key_id TEXT NOT NULL, product TEXT NOT NULL, project_id TEXT NOT NULL, env TEXT NOT NULL,
              calls INTEGER NOT NULL DEFAULT 0, credits INTEGER NOT NULL DEFAULT 0, failed INTEGER NOT NULL DEFAULT 0, refused INTEGER NOT NULL DEFAULT 0,
              PRIMARY KEY (day, key_id, product))",
            "CREATE TABLE minutes (key_id TEXT NOT NULL, minute INTEGER NOT NULL, n INTEGER NOT NULL, PRIMARY KEY (key_id, minute))",
            "CREATE TABLE totals (k TEXT PRIMARY KEY, n INTEGER NOT NULL)",
        ] {
            db.run(q, &[]).unwrap();
        }
        db.run("INSERT INTO org (org_id, name, created) VALUES (?, 'Lab', ?)", args![&org, T0]).unwrap();
        db.run("INSERT INTO projects (project_id, name, created) VALUES ('prj_1', 'default', ?)", args![T0]).unwrap();
        let console_key = keys::mint(&e, KeyEnv::Live, &org).unwrap();
        let owners_key = keys::mint(&e, KeyEnv::Live, &org).unwrap();
        for (id, k, by) in [("key_c", &console_key, OWNER), ("key_o", &owners_key, "owner")] {
            db.run(
                "INSERT INTO keys (key_id, project_id, env, digest, shown, name, scopes, created, created_by) VALUES (?, 'prj_1', 'live', ?, ?, 'k', ?, ?, ?)",
                args![id, &k.digest, &k.shown, r#"["citations:verify","evidence:search","usage:read"]"#, T0, by],
            )
            .unwrap();
        }
        db.run("INSERT INTO ledger (ts, kind, credits, ref) VALUES (?, 'grant', 500, 'grant:g1')", args![T0]).unwrap();
        db.run("INSERT INTO ledger (ts, kind, credits, ref, key_id, product) VALUES (?, 'usage', -30, 'use:req_old', 'key_c', 'evidence.search')", args![T0]).unwrap();
        db.run("INSERT INTO totals (k, n) VALUES ('net', 470), ('held', 0)", &[]).unwrap();
        db.run("INSERT INTO usage (day, key_id, product, project_id, env, calls, credits) VALUES ('2026-11-27', 'key_c', 'evidence.search', 'prj_1', 'live', 3, 30)", &[]).unwrap();
        let cfg = AccountConfig::from_vars(|_| None);
        let core = AccountCore::new(&db, &cfg);
        assert!(core.ready().unwrap());
        core.migrate(T0 + 1).unwrap();
        // and again, as a migration cut short and taken up again would: nothing changes
        core.migrate(T0 + 2).unwrap();
        db.run("DELETE FROM meta", &[]).unwrap();
        core.migrate(T0 + 3).unwrap();
        // the console's key is its maker's, who is a member; the owner's token's key is nobody's
        assert_eq!(core.call_owner(&console_key.digest, T0 + 4), Ok(OWNER.to_string()));
        assert_eq!(code(core.call_owner(&owners_key.digest, T0 + 4)), "user_binding_required");
        assert_eq!(core.members().unwrap().len(), 1);
        // what was there is there: the credits, the day's usage (with the new columns at zero), the keys' names
        assert_eq!(core.balance().unwrap()["net"], 470);
        let u = core.usage("2026-11-27", "2026-11-27", None).unwrap();
        assert_eq!((u["data"][0]["calls"].as_i64(), u["data"][0]["quota_consumed"].as_i64()), (Some(3), Some(0)));
        assert_eq!(core.keys().unwrap().len(), 2);
        assert!(core.consistent().unwrap());
        // the owner gives their key to the member, and it executes
        core.bind_key("key_o", OWNER, "owner", T0 + 5).unwrap();
        assert_eq!(core.call_owner(&owners_key.digest, T0 + 6), Ok(OWNER.to_string()));
    }

    #[test]
    fn a_projects_monthly_limit_and_the_keys_it_lists_without_their_digests() {
        let w = World::new(&[("FUNDING_POLICY", "credits"), ("PRICE_EVIDENCE_SEARCH", "10")]);
        w.core().credit("grant", 1000, "g", "", T0).unwrap();
        let p = w.core().create_project("pilot", Some(25), &w.e, T0).unwrap();
        let (_, k) = w
            .core()
            .create_key(Some(&p), KeyEnv::Live, "pilot key", None, None, "owner", None, true, &w.e, T0)
            .unwrap();
        for i in 0..2 {
            let id = go(w.call(&k.key, Product::Search, &format!("req_{i}"), T0));
            w.ran(&id, T0);
        }
        assert_eq!(code(w.call(&k.key, Product::Search, "req_2", T0)), "project_limit");
        assert_eq!(code(w.core().set_limit(&p, None, false)), "stepup");
        w.core().set_limit(&p, None, true).unwrap();
        go(w.call(&k.key, Product::Search, "req_3", T0));
        let listed = serde_json::to_string(&w.core().keys().unwrap()).unwrap();
        assert!(!listed.contains(&k.digest) && !listed.contains(&k.key) && listed.contains(&k.shown));
        assert!(
            listed.contains(r#""owner":"usr_aaaaaaaaaaaaaaaaaaaaaaaaaa""#)
                && listed.contains(r#""owner_binding":"bound""#)
        );
        // a key of a project that is no project; a name that is none; a scope that is none
        assert_eq!(
            code(w.core().create_key(Some("prj_nothing"), KeyEnv::Live, "x", None, None, "o", None, true, &w.e, T0)),
            "project"
        );
        assert_eq!(code(w.core().create_key(None, KeyEnv::Live, "  ", None, None, "o", None, true, &w.e, T0)), "name");
        assert_eq!(
            code(w.core().create_key(
                None,
                KeyEnv::Live,
                "x",
                Some(&["admin".into()]),
                None,
                "o",
                None,
                true,
                &w.e,
                T0
            )),
            "scope"
        );
        // the limits a key reads of itself: 1000 granted, 20 spent, 10 held by the call still in flight
        let l = w.core().limits(&k.digest, T0).unwrap();
        assert_eq!((l["environment"].as_str(), l["credits"]["available"].as_i64()), (Some("live"), Some(970)));
        assert_eq!(l["funding"]["credits_required"], true);
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
        core.provision(&new_id(&e, "org", 16), "x", None, "owner", &e, T0).unwrap();
        assert!(core.ready().unwrap());
        assert_eq!(core.version().unwrap(), SCHEMA_VERSION);
    }

    #[test]
    fn provisioning_is_done_once_and_belongs_to_one_organisation() {
        let w = World::new(&[]);
        let again = w.core().provision(&w.org, "Lab", Some(OWNER), "console", &w.e, T0 + 1).unwrap();
        assert_eq!(again["projects"].as_array().unwrap().len(), 1);
        assert_eq!(again["members"].as_array().unwrap().len(), 1);
        assert_eq!(code(w.core().provision(&new_id(&w.e, "org", 16), "Other", None, "owner", &w.e, T0)), "org");
        assert_eq!(code(w.core().provision("org_short", "x", None, "owner", &w.e, T0)), "org");
        assert_eq!(code(w.core().provision(&w.org, "Lab", Some("nobody"), "owner", &w.e, T0)), "user");
        // a person's id as the identity object mints it (16 bytes in base32), and nothing of another length
        assert!(is_user_id(&new_id(&w.e, "usr", 16)));
        assert!(
            !is_user_id("usr_aaaaaaaaaaaaaaaa")
                && !is_user_id(&new_id(&w.e, "org", 16))
                && !is_user_id("usr_ILOUiloiloiloiloiloiloilou")
        );
        assert_eq!(code(w.core().credit("grant", -5, "g", "", T0)), "credits");
        assert!(w.core().credit("adjust", -5, "fix-1", "a correction", T0).unwrap());
        assert_eq!(w.core().balance().unwrap()["net"], -5, "an owner's adjustment alone may go below zero");
    }

    #[test]
    fn what_spends_needs_a_touch_and_nothing_malformed_is_widened() {
        let w = World::credits();
        // a live key is made, and revoked, only after a passkey's touch; a test key needs none
        assert_eq!(
            code(w.core().create_key(None, KeyEnv::Live, "x", None, None, "o", None, false, &w.e, T0)),
            "stepup"
        );
        let (test_id, _) =
            w.core().create_key(None, KeyEnv::Test, "t", None, None, "o", None, false, &w.e, T0).unwrap();
        assert!(w.core().revoke_key(&test_id, false, T0).unwrap());
        // an empty list of scopes is refused, not made into all of them
        let none: Vec<String> = Vec::new();
        assert_eq!(
            code(w.core().create_key(None, KeyEnv::Test, "x", Some(&none), None, "o", None, false, &w.e, T0)),
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
