//! 账户 · 身份 — who a person is to the console (console.impf.ai): an address they have shown they read, the passkeys
//! they made, the recovery codes they keep, and the sessions their browsers hold.  One Durable Object of the console
//! Worker holds all of it (its `Identity`), so that every decision — is this code right, is this address free, is this
//! grant unused — is made and written in one step.  Every method here is synchronous, its cryptography included
//! (codes, digests, passkeys: `crypto`, `webauthn`): in the object, a call is a transaction.
//!
//! What is never kept: a code sent by email (derived: `crypto::Keyring::code`), a session's token, a browser's
//! binding, a grant or a recovery code (their SHA-256 only), a network's address (an HMAC of its /64, for the limits).
//!
//! The rules (docs/adr/0038-accounts-keys-and-credits.md):
//!
//! * an address is proved in the browser that asked (its binding cookie), by a code of the flow's current
//!   generation, within its time and its attempts; a resend makes the next generation and gives no attempts back;
//! * registering and signing in answer alike whether or not an address has an account: only the mail differs, and
//!   its owner alone reads it ("you already have an account", "no account uses this address" — and no code);
//! * nothing usable exists before the address is proved: no passkey, no session, no organisation — completing a
//!   registration takes the grant a right code gave, once, in the same browser;
//! * an account a passkey guards is not opened by its mailbox alone: an email sign-in then asks for a recovery code,
//!   which ends every other session;
//! * what changes an account's credentials or its keys asks for a passkey's touch within five minutes (`strong`); an
//!   account with no passkey makes its first one within ten minutes of proving its address (`fresh`).

use serde_json::{Value as Json, json};

use crate::args;
use crate::codec::b64url;
use crate::crypto::{Entropy, Keyring, digest, is_secret, new_id, new_secret, random, same};
use crate::email::{masked, normalize};
use crate::sql::{Row, Sql, SqlError, SqlExt};
use crate::time::{DAY, HOUR};
use crate::webauthn::{self, Expected, PublicKey, Stored, challenge_of, id_of};

#[derive(Debug, Clone)]
pub struct IdentityConfig {
    pub registration_open: bool,
    pub rp_id: String,
    pub rp_name: String,
    pub origins: Vec<String>,
    pub code_ms: i64,
    pub flow_ms: i64,
    pub attempts: i64,
    pub resend_ms: i64,
    pub flow_sends: i64,
    pub grant_ms: i64,
    pub per_address_hour: i64,
    pub per_address_day: i64,
    pub per_network_hour: i64,
    pub mails_per_day: i64,
    pub session_ms: i64,
    pub idle_ms: i64,
    pub stepup_ms: i64,
    pub fresh_ms: i64,
    pub trial_credits: i64,
    pub trials_per_day: i64,
}

impl IdentityConfig {
    pub fn from_vars(get: impl Fn(&str) -> Option<String>) -> Self {
        let num = |k: &str, default: f64, least: f64| {
            get(k)
                .and_then(|v| v.trim().parse::<f64>().ok())
                .filter(|v| v.is_finite() && *v >= least)
                .unwrap_or(default)
        };
        let min = 60_000.0;
        IdentityConfig {
            registration_open: get("REGISTRATION").is_some_and(|v| v.trim().eq_ignore_ascii_case("open")),
            rp_id: get("RP_ID").unwrap_or_else(|| "impf.ai".into()).trim().to_ascii_lowercase(),
            rp_name: get("RP_NAME").unwrap_or_else(|| "道乃久 TaoChronos".into()),
            origins: get("CONSOLE_ORIGIN")
                .unwrap_or_else(|| "https://console.impf.ai".into())
                .split(',')
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
                .collect(),
            code_ms: (num("CODE_MINUTES", 10.0, 1.0) * min) as i64,
            flow_ms: (num("FLOW_MINUTES", 30.0, 1.0) * min) as i64,
            attempts: num("CODE_ATTEMPTS", 5.0, 1.0) as i64,
            resend_ms: (num("RESEND_SECONDS", 60.0, 1.0) * 1000.0) as i64,
            flow_sends: num("FLOW_SENDS", 5.0, 1.0) as i64,
            grant_ms: (num("GRANT_MINUTES", 15.0, 1.0) * min) as i64,
            per_address_hour: num("MAILS_PER_ADDRESS_HOUR", 5.0, 1.0) as i64,
            per_address_day: num("MAILS_PER_ADDRESS_DAY", 10.0, 1.0) as i64,
            per_network_hour: num("STARTS_PER_NETWORK_HOUR", 20.0, 1.0) as i64,
            mails_per_day: num("AUTH_MAILS_PER_DAY", 1000.0, 1.0) as i64,
            session_ms: (num("SESSION_DAYS", 30.0, 0.01) * DAY as f64) as i64,
            idle_ms: (num("SESSION_IDLE_DAYS", 7.0, 0.01) * DAY as f64) as i64,
            stepup_ms: (num("STEPUP_MINUTES", 5.0, 0.1) * min) as i64,
            fresh_ms: (num("FRESH_MINUTES", 10.0, 0.1) * min) as i64,
            trial_credits: num("TRIAL_CREDITS", 0.0, 0.0) as i64,
            trials_per_day: num("TRIALS_PER_DAY", 50.0, 0.0) as i64,
        }
    }
}

/// Why something was not done: a word the console translates; how long to wait; attempts left.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Why {
    pub reason: &'static str,
    pub retry: Option<i64>,
    pub left: Option<i64>,
}

#[derive(Debug, Clone, PartialEq)]
pub enum Fail {
    No(Why),
    Storage(SqlError),
}

impl From<SqlError> for Fail {
    fn from(e: SqlError) -> Self {
        Fail::Storage(e)
    }
}

pub type Res<T> = Result<T, Fail>;

pub fn no(reason: &'static str) -> Fail {
    Fail::No(Why { reason, retry: None, left: None })
}

fn wait(reason: &'static str, retry_ms: i64) -> Fail {
    Fail::No(Why { reason, retry: Some(((retry_ms + 999) / 1000).max(1)), left: None })
}

/// Where a session was opened from, as its owner is shown it: a browser and a system, a country.
#[derive(Debug, Clone, Default)]
pub struct Where {
    pub device: String,
    pub place: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NewSession {
    /// the cookie's value: kept nowhere but in it
    pub token: String,
    pub public_id: String,
}

#[derive(Debug, Clone, PartialEq)]
pub enum Verified {
    /// a registration's address proved: the grant to make the account with
    Enroll(String),
    /// a sign-in's address proved, of an account a passkey guards: the grant to finish it with a recovery code
    Second(String),
    Session(NewSession),
    /// an address change made
    Done,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Me {
    pub digest: String,
    pub session: Row,
    pub user: Row,
}

const SCHEMA: &[&str] = &[
    "CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, handle TEXT NOT NULL UNIQUE, email_key TEXT NOT NULL UNIQUE, address TEXT NOT NULL,
      locale TEXT NOT NULL, created INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'active', security_version INTEGER NOT NULL DEFAULT 1, personal_org TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS passkeys (credential_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, name TEXT NOT NULL, key TEXT NOT NULL,
      sign_count INTEGER NOT NULL, backup_eligible INTEGER NOT NULL, backup_state INTEGER NOT NULL, transports TEXT NOT NULL, aaguid TEXT NOT NULL,
      created INTEGER NOT NULL, last_used INTEGER)",
    "CREATE INDEX IF NOT EXISTS passkeys_user ON passkeys (user_id)",
    "CREATE TABLE IF NOT EXISTS recovery_codes (user_id TEXT NOT NULL, digest TEXT NOT NULL, created INTEGER NOT NULL, used INTEGER, PRIMARY KEY (user_id, digest))",
    "CREATE TABLE IF NOT EXISTS flows (flow_id TEXT PRIMARY KEY, purpose TEXT NOT NULL, mode TEXT NOT NULL, email_key TEXT NOT NULL, address TEXT NOT NULL,
      user_id TEXT, browser TEXT NOT NULL, locale TEXT NOT NULL, created INTEGER NOT NULL, expires INTEGER NOT NULL, generation INTEGER NOT NULL,
      sent INTEGER NOT NULL, sends INTEGER NOT NULL, attempts INTEGER NOT NULL, state TEXT NOT NULL)",
    "CREATE INDEX IF NOT EXISTS flows_user ON flows (user_id, purpose, state)",
    "CREATE TABLE IF NOT EXISTS grants (digest TEXT PRIMARY KEY, purpose TEXT NOT NULL, flow_id TEXT NOT NULL, email_key TEXT NOT NULL, address TEXT NOT NULL,
      locale TEXT NOT NULL, user_id TEXT, browser TEXT NOT NULL, created INTEGER NOT NULL, expires INTEGER NOT NULL, used INTEGER)",
    "CREATE TABLE IF NOT EXISTS ceremonies (challenge TEXT PRIMARY KEY, purpose TEXT NOT NULL, user_id TEXT, session TEXT, grant_digest TEXT, handle TEXT,
      expires INTEGER NOT NULL, used INTEGER)",
    "CREATE TABLE IF NOT EXISTS sessions (digest TEXT PRIMARY KEY, public_id TEXT NOT NULL UNIQUE, user_id TEXT NOT NULL, created INTEGER NOT NULL,
      seen INTEGER NOT NULL, expires INTEGER NOT NULL, method TEXT NOT NULL, strong INTEGER, fresh INTEGER NOT NULL, security_version INTEGER NOT NULL,
      device TEXT NOT NULL, place TEXT NOT NULL, ended INTEGER)",
    "CREATE INDEX IF NOT EXISTS sessions_user ON sessions (user_id)",
    // the mails to send (mail.rs): written in the step that decided them, sent by the object's alarm
    "CREATE TABLE IF NOT EXISTS outbox (id INTEGER PRIMARY KEY AUTOINCREMENT, template TEXT NOT NULL, address TEXT NOT NULL, locale TEXT NOT NULL,
      flow_id TEXT, generation INTEGER, vars TEXT NOT NULL, created INTEGER NOT NULL, not_after INTEGER NOT NULL, next_at INTEGER NOT NULL,
      attempts INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL, message_id TEXT, error TEXT, delivery TEXT, done INTEGER)",
    "CREATE INDEX IF NOT EXISTS outbox_due ON outbox (state, next_at)",
    "CREATE INDEX IF NOT EXISTS outbox_message ON outbox (message_id)",
    "CREATE TABLE IF NOT EXISTS mail_events (event_id TEXT PRIMARY KEY, message_id TEXT NOT NULL, status TEXT NOT NULL, ts TEXT NOT NULL, detail TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS counters (k TEXT PRIMARY KEY, n INTEGER NOT NULL, until INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS seen (digest TEXT PRIMARY KEY, until INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, ts INTEGER NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL)",
    "CREATE INDEX IF NOT EXISTS events_user ON events (user_id, id)",
    // an organisation and its members: v1 makes one for each person, theirs alone (the roles are for what comes)
    "CREATE TABLE IF NOT EXISTS orgs (org_id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, created INTEGER NOT NULL,
      trial INTEGER NOT NULL DEFAULT 0, provisioned INTEGER)",
    "CREATE TABLE IF NOT EXISTS members (org_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL, created INTEGER NOT NULL, PRIMARY KEY (org_id, user_id))",
    "CREATE INDEX IF NOT EXISTS members_user ON members (user_id)",
];

/// The mail a flow sends, by purpose and by whether its address can be given a code.
fn template(purpose: &str, mode: &str, disabled: bool) -> &'static str {
    match (purpose, mode) {
        ("signin", _) if disabled => "account_disabled",
        ("register", "code") => "register_code",
        ("register", _) => "register_exists",
        ("signin", "code") => "signin_code",
        ("signin", _) => "signin_unknown",
        _ => "email_change_code",
    }
}

fn utc_day(now: i64) -> String {
    crate::time::day(now)
}

const CROCKFORD: &[u8; 32] = b"0123456789ABCDEFGHJKMNPQRSTVWXYZ";

/// A recovery code as a person writes it down: 16 of Crockford's characters (80 bits), in four groups.
fn recovery_code(e: &dyn Entropy) -> String {
    let b = random::<16>(e);
    let s: String = b.iter().map(|x| CROCKFORD[(x & 31) as usize] as char).collect();
    format!("{}-{}-{}-{}", &s[..4], &s[4..8], &s[8..12], &s[12..])
}

/// A recovery code as it was typed, as it is kept: upper case, without spaces or hyphens, the letters people confuse
/// read as Crockford reads them (O as 0, I and L as 1).
pub fn read_recovery(text: &str) -> Option<String> {
    let s: String = text
        .to_ascii_uppercase()
        .chars()
        .filter(|c| !c.is_whitespace() && *c != '-')
        .map(|c| match c {
            'O' => '0',
            'I' | 'L' => '1',
            c => c,
        })
        .collect();
    (s.len() == 16 && s.bytes().all(|c| CROCKFORD.contains(&c)))
        .then(|| format!("{}-{}-{}-{}", &s[..4], &s[4..8], &s[8..12], &s[12..]))
}

/// A name a person gave a passkey, or the default: no control characters, at most 64.
fn clean_name(name: &str) -> String {
    let s = name.trim();
    if s.is_empty() || s.chars().count() > 64 || s.chars().any(char::is_control) {
        "passkey".into()
    } else {
        s.to_string()
    }
}

/// A locale the mails are written in.
pub fn locale(s: &str) -> &'static str {
    if s.to_ascii_lowercase().starts_with("en") { "en" } else { "zh" }
}

pub struct Identity<'a> {
    pub sql: &'a dyn Sql,
    pub cfg: &'a IdentityConfig,
    pub keys: &'a Keyring,
    pub e: &'a dyn Entropy,
}

impl<'a> Identity<'a> {
    pub fn ensure(&self) -> Result<(), SqlError> {
        for s in SCHEMA {
            self.sql.run(s, &[])?;
        }
        Ok(())
    }

    // ---------------------------------------------------------------- limits
    fn allowed(&self, key: &str, limit: i64, now: i64) -> Result<(bool, i64), SqlError> {
        let r = self.sql.row("SELECT n, until FROM counters WHERE k = ?", args![key])?;
        Ok(match r {
            Some(r) if r.int("until") > now => (r.int("n") < limit, r.int("until") - now),
            _ => (true, 0),
        })
    }

    fn take(&self, key: &str, window: i64, now: i64) -> Result<(), SqlError> {
        self.sql.run(
            "INSERT INTO counters (k, n, until) VALUES (?, 1, ?) ON CONFLICT(k) DO UPDATE SET
               n = CASE WHEN until > ? THEN n + 1 ELSE 1 END, until = CASE WHEN until > ? THEN until ELSE excluded.until END",
            args![key, now + window, now, now],
        )
    }

    /// The mails an address may be sent now, and the service in all today: the first refusal.
    fn mail_refusal(&self, email_key: &str, now: i64) -> Res<()> {
        for (key, limit, reason) in [
            (format!("ah:{email_key}"), self.cfg.per_address_hour, "address"),
            (format!("ad:{email_key}"), self.cfg.per_address_day, "address"),
            (format!("md:{}", utc_day(now)), self.cfg.mails_per_day, "service"),
        ] {
            let (ok, left) = self.allowed(&key, limit, now)?;
            if !ok {
                return Err(wait(reason, left));
            }
        }
        Ok(())
    }

    fn count_mail(&self, email_key: &str, now: i64) -> Result<(), SqlError> {
        self.take(&format!("ah:{email_key}"), HOUR, now)?;
        self.take(&format!("ad:{email_key}"), DAY, now)?;
        self.take(&format!("md:{}", utc_day(now)), DAY, now)
    }

    fn network(&self, ip_key: &str) -> String {
        b64url(&self.keys.mac("network", ip_key.as_bytes())[..12])
    }

    /// A Turnstile token, once: a second use within its life is refused here whatever Turnstile says (its own reuse
    /// check is eventually consistent).
    pub fn first_use(&self, token: &str, now: i64) -> Res<bool> {
        let d = digest(token);
        if self.sql.row("SELECT 1 AS x FROM seen WHERE digest = ? AND until > ?", args![&d, now])?.is_some() {
            return Ok(false);
        }
        self.sql.run(
            "INSERT INTO seen (digest, until) VALUES (?, ?) ON CONFLICT(digest) DO UPDATE SET until = excluded.until",
            args![d, now + 600_000],
        )?;
        Ok(true)
    }

    // ---------------------------------------------------------------- the outbox
    #[allow(clippy::too_many_arguments)]
    fn enqueue(
        &self,
        template: &str,
        address: &str,
        locale: &str,
        flow: Option<&str>,
        generation: Option<i64>,
        vars: Json,
        not_after: i64,
        now: i64,
    ) -> Result<(), SqlError> {
        self.sql.run(
            "INSERT INTO outbox (template, address, locale, flow_id, generation, vars, created, not_after, next_at, state) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued')",
            args![template, address, locale, flow, generation, vars.to_string(), now, not_after, now],
        )
    }

    // ---------------------------------------------------------------- rows
    pub fn user(&self, user_id: &str) -> Result<Option<Row>, SqlError> {
        self.sql.row("SELECT * FROM users WHERE user_id = ?", args![user_id])
    }

    fn user_by_email(&self, key: &str) -> Result<Option<Row>, SqlError> {
        self.sql.row("SELECT * FROM users WHERE email_key = ?", args![key])
    }

    pub fn passkeys(&self, user_id: &str) -> Result<Vec<Row>, SqlError> {
        self.sql.rows("SELECT * FROM passkeys WHERE user_id = ? ORDER BY created, credential_id", args![user_id])
    }

    fn event(&self, user_id: &str, kind: &str, detail: Json, now: i64) -> Result<(), SqlError> {
        self.sql.run(
            "INSERT INTO events (user_id, ts, kind, detail) VALUES (?, ?, ?, ?)",
            args![user_id, now, kind, detail.to_string()],
        )?;
        self.sql.run(
            "DELETE FROM events WHERE user_id = ? AND id NOT IN (SELECT id FROM events WHERE user_id = ? ORDER BY id DESC LIMIT 100)",
            args![user_id, user_id],
        )
    }

    /// An organisation's role for a person, or None: not theirs.
    pub fn role(&self, user_id: &str, org_id: &str) -> Result<Option<String>, SqlError> {
        Ok(self
            .sql
            .row("SELECT role FROM members WHERE user_id = ? AND org_id = ?", args![user_id, org_id])?
            .map(|r| r.text("role")))
    }

    /// The organisations whose accounts object has not yet said it holds them (the Worker provisions them, then marks).
    pub fn unprovisioned(&self, user_id: &str) -> Result<Vec<Row>, SqlError> {
        self.sql.rows(
            "SELECT o.org_id, o.name, o.trial FROM members m JOIN orgs o ON o.org_id = m.org_id WHERE m.user_id = ? AND o.provisioned IS NULL",
            args![user_id],
        )
    }

    pub fn provisioned(&self, org_id: &str, now: i64) -> Result<(), SqlError> {
        self.sql.run("UPDATE orgs SET provisioned = ? WHERE org_id = ? AND provisioned IS NULL", args![now, org_id])
    }

    // ---------------------------------------------------------------- flows
    /// A flow begun: an address to prove, in one browser.  It answers alike whether or not the address has an account.
    pub fn start(&self, purpose: &str, email: &str, binding: &str, ip_key: &str, loc: &str, now: i64) -> Res<Json> {
        if purpose != "register" && purpose != "signin" {
            return Err(no("purpose"));
        }
        if purpose == "register" && !self.cfg.registration_open {
            return Err(no("closed"));
        }
        let email = normalize(email).ok_or_else(|| no("email"))?;
        if !is_secret(binding) {
            return Err(no("flow"));
        }
        let network = self.network(ip_key);
        let (ok, left) = self.allowed(&format!("n:{network}"), self.cfg.per_network_hour, now)?;
        if !ok {
            return Err(wait("network", left));
        }
        self.mail_refusal(&email.key, now)?;
        let user = self.user_by_email(&email.key)?;
        let active = user.as_ref().is_some_and(|u| u.text("status") == "active");
        let mode = if purpose == "register" {
            if user.is_some() { "notice" } else { "code" }
        } else if active {
            "code"
        } else {
            "notice"
        };
        let tpl = template(purpose, mode, purpose == "signin" && user.is_some() && !active);
        let flow = new_id(self.e, "flw", 16);
        let loc = locale(loc);
        self.sql.run(
            "INSERT INTO flows (flow_id, purpose, mode, email_key, address, user_id, browser, locale, created, expires, generation, sent, sends, attempts, state)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 1, 0, 'pending')",
            args![&flow, purpose, mode, &email.key, &email.address, user.as_ref().map(|u| u.text("user_id")), digest(binding), loc, now, now + self.cfg.flow_ms, now],
        )?;
        let life = if mode == "code" { self.cfg.code_ms } else { self.cfg.flow_ms };
        self.enqueue(tpl, &email.address, loc, Some(&flow), Some(1), json!({}), now + life, now)?;
        self.take(&format!("n:{network}"), HOUR, now)?;
        self.count_mail(&email.key, now)?;
        Ok(json!({ "flow": flow, "expires": now + self.cfg.flow_ms, "resend": now + self.cfg.resend_ms }))
    }

    /// A flow's pending row for this browser, or None.
    fn pending(&self, flow: &str, binding: &str, now: i64) -> Result<Option<Row>, SqlError> {
        let f = self.sql.row("SELECT * FROM flows WHERE flow_id = ?", args![flow])?;
        Ok(f.filter(|f| {
            f.text("state") == "pending"
                && f.int("expires") > now
                && same(f.text("browser").as_bytes(), digest(binding).as_bytes())
        }))
    }

    /// Another code for the same flow: the next generation, the one code from now on.  The attempts spent stay spent.
    pub fn resend(&self, flow: &str, binding: &str, now: i64) -> Res<Json> {
        let f = self.pending(flow, binding, now)?.ok_or_else(|| no("flow"))?;
        if now - f.int("sent") < self.cfg.resend_ms {
            return Err(wait("cooldown", f.int("sent") + self.cfg.resend_ms - now));
        }
        if f.int("sends") >= self.cfg.flow_sends {
            return Err(no("sends"));
        }
        self.mail_refusal(&f.text("email_key"), now)?;
        let generation = f.int("generation") + 1;
        self.sql.run(
            "UPDATE flows SET generation = ?, sent = ?, sends = sends + 1 WHERE flow_id = ?",
            args![generation, now, flow],
        )?;
        let disabled = match f.opt_text("user_id") {
            Some(u) => self.user(&u)?.is_some_and(|u| u.text("status") != "active"),
            None => false,
        };
        let tpl = template(&f.text("purpose"), &f.text("mode"), disabled);
        let life = if f.text("mode") == "code" { self.cfg.code_ms } else { self.cfg.flow_ms };
        self.enqueue(
            tpl,
            &f.text("address"),
            &f.text("locale"),
            Some(flow),
            Some(generation),
            json!({}),
            now + life,
            now,
        )?;
        self.count_mail(&f.text("email_key"), now)?;
        Ok(json!({ "flow": flow, "expires": f.int("expires"), "resend": now + self.cfg.resend_ms }))
    }

    fn grant(&self, purpose: &str, f: &Row, user_id: Option<&str>, now: i64) -> Result<String, SqlError> {
        let token = new_secret(self.e);
        self.sql.run(
            "INSERT INTO grants (digest, purpose, flow_id, email_key, address, locale, user_id, browser, created, expires) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            args![digest(&token), purpose, f.text("flow_id"), f.text("email_key"), f.text("address"), f.text("locale"), user_id, f.text("browser"), now, now + self.cfg.grant_ms],
        )?;
        Ok(token)
    }

    /// A code typed for a flow: the code of its current generation, within its time and its attempts — and, right,
    /// what it allows.  `user`: the signed-in person, for an address change (whose flow it must be).
    pub fn verify(
        &self,
        flow: &str,
        binding: &str,
        code: &str,
        user: Option<&str>,
        at: &Where,
        now: i64,
    ) -> Res<Verified> {
        let f = self.pending(flow, binding, now)?.ok_or_else(|| no("flow"))?;
        let purpose = f.text("purpose");
        if purpose == "email_change" && f.opt_text("user_id").as_deref() != user {
            return Err(no("flow"));
        }
        if f.int("attempts") >= self.cfg.attempts {
            self.sql.run("UPDATE flows SET state = 'dead' WHERE flow_id = ?", args![flow])?;
            return Err(no("attempts"));
        }
        if now - f.int("sent") > self.cfg.code_ms {
            return Err(no("expired"));
        }
        let typed: String = code.chars().filter(|c| !c.is_whitespace() && *c != '-').collect();
        let expected = self.keys.code(&purpose, flow, f.int("generation"), &f.text("address"));
        let right = typed.len() == 8
            && typed.bytes().all(|c| c.is_ascii_digit())
            && same(typed.as_bytes(), expected.as_bytes());
        if !right || f.text("mode") != "code" {
            let attempts = f.int("attempts") + 1;
            let state = if attempts >= self.cfg.attempts { "dead" } else { "pending" };
            self.sql.run("UPDATE flows SET attempts = ?, state = ? WHERE flow_id = ?", args![attempts, state, flow])?;
            return Err(if attempts >= self.cfg.attempts {
                no("attempts")
            } else {
                Fail::No(Why { reason: "code", retry: None, left: Some(self.cfg.attempts - attempts) })
            });
        }
        // every refusal is decided before the first write that is not an attempt's count (a storage failure is then the
        // only thing that can stop a step half-written): an address another account took meanwhile is one
        if purpose == "email_change"
            && self
                .user_by_email(&f.text("email_key"))?
                .is_some_and(|o| Some(o.text("user_id")) != f.opt_text("user_id"))
        {
            return Err(no("taken"));
        }
        self.sql.run("UPDATE flows SET state = 'consumed' WHERE flow_id = ?", args![flow])?;
        match purpose.as_str() {
            "register" => Ok(Verified::Enroll(self.grant("enroll", &f, None, now)?)),
            "signin" => {
                let user = self
                    .user(&f.text("user_id"))?
                    .filter(|u| u.text("status") == "active")
                    .ok_or_else(|| no("flow"))?;
                let uid = user.text("user_id");
                if !self.passkeys(&uid)?.is_empty() {
                    return Ok(Verified::Second(self.grant("second", &f, Some(&uid), now)?)); // not by the mailbox alone
                }
                self.event(&uid, "signed_in", json!({ "method": "email" }), now)?;
                Ok(Verified::Session(self.open_session(&uid, "email", None, at, now)?))
            }
            _ => {
                // an address change: the new address is proved, and becomes the account's if it is still nobody's
                let user = self.user(&f.text("user_id"))?.ok_or_else(|| no("flow"))?;
                let uid = user.text("user_id");
                self.sql.run(
                    "UPDATE users SET email_key = ?, address = ? WHERE user_id = ?",
                    args![f.text("email_key"), f.text("address"), &uid],
                )?;
                self.sql.run("UPDATE flows SET state = 'dead' WHERE user_id = ? AND purpose = 'email_change' AND state = 'pending'", args![&uid])?;
                self.event(
                    &uid,
                    "email_changed",
                    json!({ "from": masked(&user.text("address")), "to": masked(&f.text("address")) }),
                    now,
                )?;
                self.enqueue(
                    "email_changed",
                    &user.text("address"),
                    &user.text("locale"),
                    None,
                    None,
                    json!({ "to": masked(&f.text("address")) }),
                    now + DAY,
                    now,
                )?;
                Ok(Verified::Done)
            }
        }
    }

    fn usable_grant(&self, grant: &str, binding: &str, purpose: &str, now: i64) -> Result<Option<Row>, SqlError> {
        let g = self.sql.row("SELECT * FROM grants WHERE digest = ?", args![digest(grant)])?;
        Ok(g.filter(|g| {
            g.opt_int("used").is_none()
                && g.text("purpose") == purpose
                && g.int("expires") > now
                && same(g.text("browser").as_bytes(), digest(binding).as_bytes())
        }))
    }

    // ---------------------------------------------------------------- sessions
    fn open_session(
        &self,
        user_id: &str,
        method: &str,
        strong: Option<i64>,
        at: &Where,
        now: i64,
    ) -> Result<NewSession, SqlError> {
        let token = new_secret(self.e);
        let public_id = new_id(self.e, "ses", 10);
        let version = self.user(user_id)?.map(|u| u.int("security_version")).unwrap_or(1);
        let device: String = at.device.chars().take(80).collect();
        let place: String = at.place.chars().take(40).collect();
        self.sql.run(
            "INSERT INTO sessions (digest, public_id, user_id, created, seen, expires, method, strong, fresh, security_version, device, place)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            args![digest(&token), &public_id, user_id, now, now, now + self.cfg.session_ms, method, strong, now, version, device, place],
        )?;
        self.sql.run(
            "DELETE FROM sessions WHERE user_id = ? AND (ended IS NOT NULL OR expires < ?) AND created < ?",
            args![user_id, now, now - 30 * DAY],
        )?;
        Ok(NewSession { token, public_id })
    }

    /// The signed-in person a session's token is, or None: ended, out of time, idle too long, of an account whose
    /// sessions were all ended since (a recovery), or no longer active.  Its last use is written at most once a minute.
    pub fn current(&self, token: &str, now: i64) -> Result<Option<Me>, SqlError> {
        if !is_secret(token) {
            return Ok(None);
        }
        let d = digest(token);
        let Some(s) = self.sql.row("SELECT * FROM sessions WHERE digest = ?", args![&d])? else { return Ok(None) };
        if s.opt_int("ended").is_some() || s.int("expires") <= now || s.int("seen") + self.cfg.idle_ms <= now {
            return Ok(None);
        }
        let Some(user) = self.user(&s.text("user_id"))? else { return Ok(None) };
        if user.text("status") != "active" || user.int("security_version") != s.int("security_version") {
            return Ok(None);
        }
        if now - s.int("seen") > 60_000 {
            self.sql.run("UPDATE sessions SET seen = ? WHERE digest = ?", args![now, &d])?;
        }
        Ok(Some(Me { digest: d, session: s, user }))
    }

    fn me(&self, token: &str, now: i64) -> Res<Me> {
        self.current(token, now)?.ok_or_else(|| no("session"))
    }

    /// Has this session touched a passkey (or used a recovery code) within the step-up window?
    pub fn strong(&self, me: &Me, now: i64) -> bool {
        me.session.opt_int("strong").is_some_and(|t| now - t <= self.cfg.stepup_ms)
    }

    fn fresh(&self, me: &Me, now: i64) -> bool {
        now - me.session.int("fresh") <= self.cfg.fresh_ms
    }

    /// What needs a passkey's touch: Ok when the session had one lately; else why not.
    pub fn need_strong(&self, me: &Me, now: i64) -> Res<()> {
        if self.strong(me, now) {
            return Ok(());
        }
        Err(no(if self.passkeys(&me.user.text("user_id"))?.is_empty() { "no_passkey" } else { "stepup" }))
    }

    // ---------------------------------------------------------------- passkeys
    fn creation_options(&self, challenge: &str, handle: &str, name: &str, exclude: &[Row]) -> Json {
        json!({
            "challenge": challenge, "rp": { "id": self.cfg.rp_id, "name": self.cfg.rp_name }, "user": { "id": handle, "name": name, "displayName": name },
            "pubKeyCredParams": [{ "type": "public-key", "alg": -8 }, { "type": "public-key", "alg": -7 }, { "type": "public-key", "alg": -257 }],
            "authenticatorSelection": { "residentKey": "required", "requireResidentKey": true, "userVerification": "required" },
            "attestation": "none", "timeout": 300_000, "hints": ["client-device", "hybrid"],
            "excludeCredentials": exclude.iter().map(|p| json!({ "type": "public-key", "id": p.text("credential_id"),
                "transports": serde_json::from_str::<Json>(&p.text("transports")).unwrap_or(json!([])) })).collect::<Vec<_>>(),
        })
    }

    fn ceremony(
        &self,
        purpose: &str,
        user: Option<&str>,
        session: Option<&str>,
        grant: Option<&str>,
        handle: Option<&str>,
        now: i64,
    ) -> Result<String, SqlError> {
        let challenge = b64url(&random::<32>(self.e));
        self.sql.run("DELETE FROM ceremonies WHERE expires < ?", args![now - HOUR])?;
        self.sql.run(
            "INSERT INTO ceremonies (challenge, purpose, user_id, session, grant_digest, handle, expires) VALUES (?, ?, ?, ?, ?, ?, ?)",
            args![&challenge, purpose, user, session, grant, handle, now + 300_000],
        )?;
        Ok(challenge)
    }

    /// A challenge taken for its one use, whether or not what it was given then verifies.
    fn take_ceremony(&self, credential: &Json, purpose: &str, now: i64) -> Res<Row> {
        let challenge = challenge_of(credential).ok_or_else(|| no("challenge"))?;
        let c = self.sql.row("SELECT * FROM ceremonies WHERE challenge = ?", args![&challenge])?;
        let c = c
            .filter(|c| c.opt_int("used").is_none() && c.text("purpose") == purpose && c.int("expires") > now)
            .ok_or_else(|| no("challenge"))?;
        self.sql.run("UPDATE ceremonies SET used = ? WHERE challenge = ?", args![now, &challenge])?;
        Ok(c)
    }

    fn expected<'b>(&'b self, challenge: &'b str) -> Expected<'b> {
        Expected { challenge, origins: &self.cfg.origins, rp_id: &self.cfg.rp_id, require_uv: true }
    }

    fn registration(&self, credential: &Json, c: &Row) -> Res<webauthn::Registered> {
        let challenge = c.text("challenge");
        let r = webauthn::verify_registration(credential, &self.expected(&challenge))
            .map_err(|e| no(passkey_reason(e.0)))?;
        if self.sql.row("SELECT 1 AS x FROM passkeys WHERE credential_id = ?", args![&r.credential_id])?.is_some() {
            return Err(no("credential")); // §7.1 step 27: registered already
        }
        Ok(r)
    }

    fn insert_passkey(&self, user_id: &str, p: &webauthn::Registered, name: &str, now: i64) -> Result<(), SqlError> {
        self.sql.run(
            "INSERT INTO passkeys (credential_id, user_id, name, key, sign_count, backup_eligible, backup_state, transports, aaguid, created)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            args![&p.credential_id, user_id, name, serde_json::to_string(&p.key).unwrap_or_default(), i64::from(p.sign_count), p.backup_eligible,
                p.backup_state, json!(p.transports).to_string(), &p.aaguid, now],
        )?;
        self.event(user_id, "passkey_added", json!({ "name": name }), now)
    }

    fn replace_recovery(&self, user_id: &str, now: i64) -> Result<Vec<String>, SqlError> {
        let codes: Vec<String> = (0..10).map(|_| recovery_code(self.e)).collect();
        self.sql.run("DELETE FROM recovery_codes WHERE user_id = ?", args![user_id])?;
        for c in &codes {
            self.sql.run(
                "INSERT INTO recovery_codes (user_id, digest, created) VALUES (?, ?, ?)",
                args![user_id, digest(c), now],
            )?;
        }
        Ok(codes)
    }

    fn recovery_left(&self, user_id: &str) -> Result<i64, SqlError> {
        self.sql.scalar("SELECT COUNT(*) FROM recovery_codes WHERE user_id = ? AND used IS NULL", args![user_id])
    }

    /// The passkey a new account makes, once its address is proved: the user handle is chosen now.
    pub fn enroll_options(&self, grant: &str, binding: &str, now: i64) -> Res<Json> {
        let g = self.usable_grant(grant, binding, "enroll", now)?.ok_or_else(|| no("grant"))?;
        let handle = b64url(&random::<16>(self.e));
        let challenge = self.ceremony("enroll", None, None, Some(&digest(grant)), Some(&handle), now)?;
        let address = g.text("address");
        Ok(self.creation_options(&challenge, &handle, &address, &[]))
    }

    /// A new account: with the passkey just made, or none (then it is opened by its mailbox until one is added).  One
    /// step: the grant used, the address free, the credential new — or nothing written.  → {user, org, trial, session,
    /// recovery (shown once)}
    pub fn complete(
        &self,
        grant: &str,
        binding: &str,
        credential: Option<&Json>,
        name: &str,
        at: &Where,
        now: i64,
    ) -> Res<Json> {
        let g = self.usable_grant(grant, binding, "enroll", now)?.ok_or_else(|| no("grant"))?;
        let (passkey, handle) = match credential {
            Some(cred) => {
                let c = self.take_ceremony(cred, "enroll", now)?;
                if c.text("grant_digest") != digest(grant) {
                    return Err(no("challenge"));
                }
                (Some(self.registration(cred, &c)?), c.text("handle"))
            }
            None => (None, b64url(&random::<16>(self.e))),
        };
        if self.user_by_email(&g.text("email_key"))?.is_some() {
            return Err(no("taken")); // registered from another browser meanwhile
        }
        self.sql.run("UPDATE grants SET used = ? WHERE digest = ?", args![now, digest(grant)])?;
        let mut trial = 0;
        let today = format!("trial:{}", utc_day(now));
        if self.cfg.trial_credits > 0 && self.allowed(&today, self.cfg.trials_per_day, now)?.0 {
            trial = self.cfg.trial_credits;
            self.take(&today, DAY, now)?;
        }
        let user_id = new_id(self.e, "usr", 16);
        let org_id = new_id(self.e, "org", 16);
        let address = g.text("address");
        self.sql.run(
            "INSERT INTO users (user_id, handle, email_key, address, locale, created, personal_org) VALUES (?, ?, ?, ?, ?, ?, ?)",
            args![&user_id, &handle, g.text("email_key"), &address, g.text("locale"), now, &org_id],
        )?;
        let org_name: String = address.split('@').next().unwrap_or("").chars().take(64).collect();
        self.sql.run(
            "INSERT INTO orgs (org_id, name, kind, created, trial) VALUES (?, ?, 'personal', ?, ?)",
            args![&org_id, &org_name, now, trial],
        )?;
        self.sql.run(
            "INSERT INTO members (org_id, user_id, role, created) VALUES (?, ?, 'owner', ?)",
            args![&org_id, &user_id, now],
        )?;
        self.event(&user_id, "registered", json!({ "address": masked(&address) }), now)?;
        let mut recovery = Vec::new();
        if let Some(p) = &passkey {
            self.insert_passkey(&user_id, p, &clean_name(name), now)?;
            recovery = self.replace_recovery(&user_id, now)?;
        }
        let session = self.open_session(
            &user_id,
            if passkey.is_some() { "passkey" } else { "email" },
            passkey.as_ref().map(|_| now),
            at,
            now,
        )?;
        Ok(
            json!({ "user": user_id, "org": org_id, "org_name": org_name, "trial": trial, "token": session.token, "session": session.public_id, "recovery": recovery }),
        )
    }

    /// A sign-in with a passkey: no address asked for — the authenticator says whose it is (a discoverable credential).
    pub fn signin_options(&self, now: i64) -> Res<Json> {
        let challenge = self.ceremony("signin", None, None, None, None, now)?;
        Ok(
            json!({ "challenge": challenge, "rpId": self.cfg.rp_id, "userVerification": "required", "timeout": 300_000, "allowCredentials": [] }),
        )
    }

    /// An assertion, checked against the passkey it names and its owner; `check`: what the ceremony requires besides.
    fn assert(
        &self,
        credential: &Json,
        purpose: &str,
        now: i64,
        check: impl Fn(&Row, &Row) -> bool,
    ) -> Res<(Row, Row)> {
        let c = self.take_ceremony(credential, purpose, now)?;
        let id = id_of(credential).ok_or_else(|| no("challenge"))?;
        let p = self
            .sql
            .row("SELECT * FROM passkeys WHERE credential_id = ?", args![&id])?
            .ok_or_else(|| no("passkey_unknown"))?;
        let user = self
            .user(&p.text("user_id"))?
            .filter(|u| u.text("status") == "active")
            .ok_or_else(|| no("passkey_unknown"))?;
        if !check(&c, &p) {
            return Err(no("passkey_user"));
        }
        let key: PublicKey = serde_json::from_str(&p.text("key")).map_err(|_| no("passkey"))?;
        let challenge = c.text("challenge");
        let stored = Stored {
            key: &key,
            sign_count: p.int("sign_count") as u32,
            backup_eligible: p.int("backup_eligible") == 1,
        };
        let out = webauthn::verify_assertion(credential, &self.expected(&challenge), &stored)
            .map_err(|e| no(passkey_reason(e.0)))?;
        match &out.user_handle {
            Some(h) if *h != user.text("handle") => return Err(no("passkey_user")),
            None if purpose == "signin" => return Err(no("passkey_user")), // a discoverable credential names its user
            _ => {}
        }
        self.sql.run(
            "UPDATE passkeys SET sign_count = ?, backup_state = ?, last_used = ? WHERE credential_id = ?",
            args![i64::from(out.sign_count), out.backup_state, now, &id],
        )?;
        Ok((user, p))
    }

    pub fn signin(&self, credential: &Json, at: &Where, now: i64) -> Res<NewSession> {
        let (user, p) = self.assert(credential, "signin", now, |_, _| true)?;
        let uid = user.text("user_id");
        self.event(&uid, "signed_in", json!({ "method": "passkey", "passkey": p.text("name") }), now)?;
        Ok(self.open_session(&uid, "passkey", Some(now), at, now)?)
    }

    /// The second step of an email sign-in to an account a passkey guards: a recovery code, used once.  Every other
    /// session ends, and the owner is told.
    pub fn second(&self, grant: &str, binding: &str, recovery: &str, at: &Where, now: i64) -> Res<Json> {
        let code = read_recovery(recovery).ok_or_else(|| no("recovery"))?;
        let g = self.usable_grant(grant, binding, "second", now)?.ok_or_else(|| no("grant"))?;
        let uid = g.text("user_id");
        let (ok, left) = self.allowed(&format!("rc:{uid}"), 10, now)?;
        if !ok {
            return Err(wait("attempts", left));
        }
        let d = digest(&code);
        if self
            .sql
            .row(
                "SELECT 1 AS x FROM recovery_codes WHERE user_id = ? AND digest = ? AND used IS NULL",
                args![&uid, &d],
            )?
            .is_none()
        {
            self.take(&format!("rc:{uid}"), HOUR, now)?;
            return Err(no("recovery"));
        }
        let user = self.user(&uid)?.filter(|u| u.text("status") == "active").ok_or_else(|| no("grant"))?;
        self.sql.run("UPDATE recovery_codes SET used = ? WHERE user_id = ? AND digest = ?", args![now, &uid, &d])?;
        self.sql.run("UPDATE grants SET used = ? WHERE digest = ?", args![now, digest(grant)])?;
        self.sql.run("UPDATE users SET security_version = security_version + 1 WHERE user_id = ?", args![&uid])?;
        let left = self.recovery_left(&uid)?;
        self.event(&uid, "recovery_used", json!({ "left": left }), now)?;
        self.enqueue(
            "recovery_used",
            &user.text("address"),
            &user.text("locale"),
            None,
            None,
            json!({ "left": left }),
            now + DAY,
            now,
        )?;
        self.event(&uid, "signed_in", json!({ "method": "recovery" }), now)?;
        let s = self.open_session(&uid, "recovery", Some(now), at, now)?;
        Ok(json!({ "token": s.token, "session": s.public_id, "left": left }))
    }

    /// A passkey's touch asked for by a session (a step-up): only that session's owner's passkeys are offered.
    pub fn stepup_options(&self, token: &str, now: i64) -> Res<Json> {
        let me = self.me(token, now)?;
        let keys = self.passkeys(&me.user.text("user_id"))?;
        if keys.is_empty() {
            return Err(no("no_passkey"));
        }
        let challenge = self.ceremony("stepup", Some(&me.user.text("user_id")), Some(&me.digest), None, None, now)?;
        Ok(json!({ "challenge": challenge, "rpId": self.cfg.rp_id, "userVerification": "required", "timeout": 300_000,
            "allowCredentials": keys.iter().map(|p| json!({ "type": "public-key", "id": p.text("credential_id"),
                "transports": serde_json::from_str::<Json>(&p.text("transports")).unwrap_or(json!([])) })).collect::<Vec<_>>() }))
    }

    /// The session raised by the touch: a new token (what was raised is not what a copy of the old cookie holds).
    pub fn stepup(&self, token: &str, credential: &Json, now: i64) -> Res<String> {
        let me = self.me(token, now)?;
        let uid = me.user.text("user_id");
        self.assert(credential, "stepup", now, |c, p| c.text("session") == me.digest && p.text("user_id") == uid)?;
        let next = new_secret(self.e);
        self.sql.run(
            "UPDATE sessions SET digest = ?, strong = ?, fresh = ?, seen = ? WHERE digest = ? AND ended IS NULL",
            args![digest(&next), now, now, now, &me.digest],
        )?;
        Ok(next)
    }

    /// A passkey added by a signed-in person: the first needs a fresh proof of the address, another a touch.
    pub fn add_options(&self, token: &str, now: i64) -> Res<Json> {
        let me = self.me(token, now)?;
        let keys = self.passkeys(&me.user.text("user_id"))?;
        if keys.is_empty() && !self.fresh(&me, now) {
            return Err(no("fresh"));
        }
        if !keys.is_empty() {
            self.need_strong(&me, now)?;
        }
        let challenge = self.ceremony("register", Some(&me.user.text("user_id")), Some(&me.digest), None, None, now)?;
        Ok(self.creation_options(&challenge, &me.user.text("handle"), &me.user.text("address"), &keys))
    }

    /// → {first, recovery (shown once, when it was the first)}; the owner is told by mail.
    pub fn add(&self, token: &str, credential: &Json, name: &str, now: i64) -> Res<Json> {
        let me = self.me(token, now)?;
        let uid = me.user.text("user_id");
        let c = self.take_ceremony(credential, "register", now)?;
        if c.text("session") != me.digest || c.text("user_id") != uid {
            return Err(no("challenge"));
        }
        let p = self.registration(credential, &c)?;
        let first = self.passkeys(&uid)?.is_empty();
        let name = clean_name(name);
        self.insert_passkey(&uid, &p, &name, now)?;
        let recovery = if first { self.replace_recovery(&uid, now)? } else { Vec::new() };
        if first {
            // the touch that made it counts as one: the person may go on to what needs one
            self.sql.run("UPDATE sessions SET strong = ? WHERE digest = ?", args![now, &me.digest])?;
        }
        self.enqueue(
            "passkey_added",
            &me.user.text("address"),
            &me.user.text("locale"),
            None,
            None,
            json!({ "name": name }),
            now + DAY,
            now,
        )?;
        Ok(json!({ "first": first, "recovery": recovery }))
    }

    pub fn remove(&self, token: &str, credential_id: &str, now: i64) -> Res<Json> {
        let me = self.me(token, now)?;
        self.need_strong(&me, now)?;
        let uid = me.user.text("user_id");
        let p = self
            .sql
            .row("SELECT * FROM passkeys WHERE credential_id = ? AND user_id = ?", args![credential_id, &uid])?
            .ok_or_else(|| no("passkey"))?;
        self.sql.run("DELETE FROM passkeys WHERE credential_id = ?", args![credential_id])?;
        let last = self.passkeys(&uid)?.is_empty();
        if last {
            self.sql.run("DELETE FROM recovery_codes WHERE user_id = ?", args![&uid])?; // only an account a passkey guards needs them
        }
        self.event(&uid, "passkey_removed", json!({ "name": p.text("name") }), now)?;
        self.enqueue(
            "passkey_removed",
            &me.user.text("address"),
            &me.user.text("locale"),
            None,
            None,
            json!({ "name": p.text("name") }),
            now + DAY,
            now,
        )?;
        Ok(json!({ "last": last }))
    }

    pub fn rename(&self, token: &str, credential_id: &str, name: &str, now: i64) -> Res<()> {
        let me = self.me(token, now)?;
        self.sql.run(
            "UPDATE passkeys SET name = ? WHERE credential_id = ? AND user_id = ?",
            args![clean_name(name), credential_id, me.user.text("user_id")],
        )?;
        Ok(())
    }

    pub fn renew_recovery(&self, token: &str, now: i64) -> Res<Vec<String>> {
        let me = self.me(token, now)?;
        self.need_strong(&me, now)?;
        let codes = self.replace_recovery(&me.user.text("user_id"), now)?;
        self.event(&me.user.text("user_id"), "recovery_renewed", json!({}), now)?;
        Ok(codes)
    }

    /// A new address for the account: a touch first where a passkey guards it, a fresh sign-in where none does; the
    /// code goes to the new address, and the old one is told once the change is made.
    pub fn start_email_change(
        &self,
        token: &str,
        email: &str,
        binding: &str,
        ip_key: &str,
        loc: &str,
        now: i64,
    ) -> Res<Json> {
        let me = self.me(token, now)?;
        let uid = me.user.text("user_id");
        if self.passkeys(&uid)?.is_empty() {
            if !self.fresh(&me, now) {
                return Err(no("fresh"));
            }
        } else {
            self.need_strong(&me, now)?;
        }
        let email = normalize(email).ok_or_else(|| no("email"))?;
        if email.key == me.user.text("email_key") {
            return Err(no("same"));
        }
        if self.user_by_email(&email.key)?.is_some() {
            return Err(no("taken")); // said to its signed-in owner only, and limited like every start
        }
        let network = self.network(ip_key);
        let (ok, left) = self.allowed(&format!("n:{network}"), self.cfg.per_network_hour, now)?;
        if !ok {
            return Err(wait("network", left));
        }
        self.mail_refusal(&email.key, now)?;
        self.sql.run(
            "UPDATE flows SET state = 'dead' WHERE user_id = ? AND purpose = 'email_change' AND state = 'pending'",
            args![&uid],
        )?;
        let flow = new_id(self.e, "flw", 16);
        let loc = locale(loc);
        self.sql.run(
            "INSERT INTO flows (flow_id, purpose, mode, email_key, address, user_id, browser, locale, created, expires, generation, sent, sends, attempts, state)
             VALUES (?, 'email_change', 'code', ?, ?, ?, ?, ?, ?, ?, 1, ?, 1, 0, 'pending')",
            args![&flow, &email.key, &email.address, &uid, digest(binding), loc, now, now + self.cfg.flow_ms, now],
        )?;
        self.enqueue(
            "email_change_code",
            &email.address,
            loc,
            Some(&flow),
            Some(1),
            json!({}),
            now + self.cfg.code_ms,
            now,
        )?;
        self.take(&format!("n:{network}"), HOUR, now)?;
        self.count_mail(&email.key, now)?;
        Ok(json!({ "flow": flow, "expires": now + self.cfg.flow_ms, "resend": now + self.cfg.resend_ms }))
    }

    // ---------------------------------------------------------------- what a person reads and ends of their own
    pub fn overview(&self, token: &str, now: i64) -> Res<Json> {
        let me = self.me(token, now)?;
        let u = &me.user;
        let uid = u.text("user_id");
        let passkeys: Vec<Json> = self
            .passkeys(&uid)?
            .iter()
            .map(|p| json!({ "id": p.text("credential_id"), "name": p.text("name"), "created": p.int("created"), "last_used": p.opt_int("last_used"),
                "synced": p.int("backup_state") == 1 }))
            .collect();
        let sessions: Vec<Json> = self
            .sql
            .rows(
                "SELECT * FROM sessions WHERE user_id = ? AND ended IS NULL AND expires > ? AND seen > ? ORDER BY seen DESC",
                args![&uid, now, now - self.cfg.idle_ms],
            )?
            .iter()
            .filter(|s| s.int("security_version") == u.int("security_version"))
            .map(|s| json!({ "id": s.text("public_id"), "created": s.int("created"), "seen": s.int("seen"), "method": s.text("method"),
                "device": s.text("device"), "place": s.text("place"), "current": s.text("digest") == me.digest }))
            .collect();
        let orgs: Vec<Json> = self
            .sql
            .rows("SELECT o.org_id, o.name, o.kind, m.role FROM members m JOIN orgs o ON o.org_id = m.org_id WHERE m.user_id = ? ORDER BY o.created", args![&uid])?
            .iter()
            .map(|o| json!({ "id": o.text("org_id"), "name": o.text("name"), "kind": o.text("kind"), "role": o.text("role") }))
            .collect();
        let strong_until = me.session.opt_int("strong").map(|t| t + self.cfg.stepup_ms);
        Ok(json!({
            "user": { "id": uid, "address": u.text("address"), "locale": u.text("locale"), "created": u.int("created") },
            "passkeys": passkeys, "recovery_left": self.recovery_left(&uid)?, "sessions": sessions, "orgs": orgs,
            "session": { "strong": self.strong(&me, now), "fresh": self.fresh(&me, now), "method": me.session.text("method"), "strong_until": strong_until },
        }))
    }

    pub fn events(&self, token: &str, now: i64) -> Res<Json> {
        let me = self.me(token, now)?;
        let rows = self.sql.rows(
            "SELECT ts, kind, detail FROM events WHERE user_id = ? ORDER BY id DESC LIMIT 100",
            args![me.user.text("user_id")],
        )?;
        Ok(json!(
            rows.iter()
                .map(|r| json!({ "ts": r.int("ts"), "kind": r.text("kind"),
            "detail": serde_json::from_str::<Json>(&r.text("detail")).unwrap_or(json!({})) }))
                .collect::<Vec<_>>()
        ))
    }

    pub fn sign_out(&self, token: &str, now: i64) -> Res<()> {
        if let Some(me) = self.current(token, now)? {
            self.sql.run("UPDATE sessions SET ended = ? WHERE digest = ?", args![now, &me.digest])?;
        }
        Ok(())
    }

    pub fn end_session(&self, token: &str, public_id: &str, now: i64) -> Res<bool> {
        let me = self.me(token, now)?;
        let uid = me.user.text("user_id");
        let found = self.sql.row(
            "SELECT digest FROM sessions WHERE user_id = ? AND public_id = ? AND ended IS NULL",
            args![&uid, public_id],
        )?;
        if let Some(s) = found {
            self.sql.run("UPDATE sessions SET ended = ? WHERE digest = ?", args![now, s.text("digest")])?;
            self.event(&uid, "session_ended", json!({}), now)?;
            return Ok(true);
        }
        Ok(false)
    }

    pub fn end_others(&self, token: &str, now: i64) -> Res<()> {
        let me = self.me(token, now)?;
        let uid = me.user.text("user_id");
        self.sql.run(
            "UPDATE sessions SET ended = ? WHERE user_id = ? AND digest <> ? AND ended IS NULL",
            args![now, &uid, &me.digest],
        )?;
        self.event(&uid, "sessions_ended", json!({}), now)?;
        Ok(())
    }

    /// The person a session is, for the console's own checks: (user id, strong now, role in the organisation).
    pub fn member(&self, token: &str, org_id: &str, now: i64) -> Res<(String, bool, String)> {
        let me = self.me(token, now)?;
        let uid = me.user.text("user_id");
        let role = self.role(&uid, org_id)?.ok_or_else(|| no("org"))?;
        Ok((uid, self.strong(&me, now), role))
    }

    /// What has outlived its use.
    pub fn prune(&self, now: i64) -> Result<(), SqlError> {
        self.sql.run("DELETE FROM flows WHERE expires < ?", args![now - DAY])?;
        self.sql.run("DELETE FROM grants WHERE expires < ?", args![now - DAY])?;
        self.sql.run("DELETE FROM ceremonies WHERE expires < ?", args![now - HOUR])?;
        self.sql.run("DELETE FROM counters WHERE until < ?", args![now])?;
        self.sql.run("DELETE FROM seen WHERE until < ?", args![now])?;
        self.sql
            .run("DELETE FROM outbox WHERE state NOT IN ('queued', 'sending') AND created < ?", args![now - 7 * DAY])?;
        self.sql.run(
            "DELETE FROM sessions WHERE (ended IS NOT NULL OR expires < ?) AND created < ?",
            args![now, now - 90 * DAY],
        )?;
        self.sql.run("DELETE FROM mail_events WHERE message_id NOT IN (SELECT message_id FROM outbox WHERE message_id IS NOT NULL)", &[])
    }
}

/// A WebAuthn check's word, as the console's: `passkey_<check>`.
fn passkey_reason(code: &'static str) -> &'static str {
    match code {
        "type" => "passkey_type",
        "challenge" => "passkey_challenge",
        "origin" => "passkey_origin",
        "cross_origin" => "passkey_cross_origin",
        "rp" => "passkey_rp",
        "up" => "passkey_up",
        "uv" => "passkey_uv",
        "flags" => "passkey_flags",
        "alg" => "passkey_alg",
        "key" => "passkey_key",
        "signature" => "passkey_signature",
        "counter" => "passkey_counter",
        _ => "passkey",
    }
}

/// An address's network as the limits know it: an IPv4 address whole, an IPv6 one by its /64 (one household, one
/// network operator's customer) — the sentinel's rule (security/sentinel.js: ipKey).
pub fn ip_key(ip: &str) -> String {
    if ip.contains(':') {
        let groups: Vec<&str> = ip.split(':').collect();
        if let Some(gap) = groups.iter().position(|g| g.is_empty()) {
            // expand "::" so that the first four groups are the /64
            let head: Vec<&str> = groups[..gap].iter().copied().filter(|g| !g.is_empty()).collect();
            let tail: Vec<&str> = groups[gap..].iter().copied().filter(|g| !g.is_empty()).collect();
            let mut full: Vec<String> = head.iter().map(|g| g.to_ascii_lowercase()).collect();
            full.extend(std::iter::repeat_n("0".to_string(), 8usize.saturating_sub(head.len() + tail.len())));
            full.extend(tail.iter().map(|g| g.to_ascii_lowercase()));
            return format!("{}::/64", full.iter().take(4).cloned().collect::<Vec<_>>().join(":"));
        }
        return format!("{}::/64", groups.iter().take(4).map(|g| g.to_ascii_lowercase()).collect::<Vec<_>>().join(":"));
    }
    ip.to_string()
}

#[cfg(test)]
#[path = "identity_tests.rs"]
mod tests;
