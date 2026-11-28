//! Who a person is to the console (identity.rs), and the mails that prove it (mail.rs): over SQLite, with a clock the
//! tests move, a software authenticator (webauthn.rs), and a sender that keeps what it is handed.  The acceptance tests
//! of the proposal's §12.3 that are the identity object's are named by it.

use std::cell::{Cell, RefCell};

use serde_json::json;

use super::*;
use crate::crypto::tests::Counter;
use crate::mail::{Mail, MailConfig, Mailer, TEMPLATES, coded, delivery_events, render};
use crate::sql::sqlite::Memory;
use crate::webauthn::tests::{Authenticator, Twist};
use crate::webauthn::{ES256, RS256};

const START: i64 = 1_795_824_000_000 - 16 * HOUR; // 2026-11-27 08:00 UTC
const MIN: i64 = 60_000;

struct World {
    db: Memory,
    cfg: IdentityConfig,
    keys: Keyring,
    e: Counter,
    mail: MailConfig,
    clock: Cell<i64>,
    sent: RefCell<Vec<(String, Mail)>>,
}

fn here() -> Where {
    Where { device: "Chrome · macOS".into(), place: "SG".into() }
}

impl World {
    fn new(vars: &[(&str, &str)]) -> World {
        static SEED: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(1);
        let mut all = vec![("REGISTRATION", "open")];
        all.extend_from_slice(vars);
        let all: Vec<(String, String)> = all.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect();
        let get = |k: &str| all.iter().rev().find(|(n, _)| n == k).map(|(_, v)| v.clone());
        let w = World {
            db: Memory::new(),
            cfg: IdentityConfig::from_vars(get),
            keys: Keyring::new(&"s".repeat(40)).unwrap(),
            e: Counter(Cell::new(SEED.fetch_add(1, std::sync::atomic::Ordering::Relaxed) << 36)),
            mail: MailConfig::from_vars(|_| None),
            clock: Cell::new(START),
            sent: RefCell::new(Vec::new()),
        };
        w.id().ensure().unwrap();
        w
    }

    fn id(&self) -> Identity<'_> {
        Identity { sql: &self.db, cfg: &self.cfg, keys: &self.keys, e: &self.e }
    }

    fn now(&self) -> i64 {
        self.clock.get()
    }

    fn advance(&self, ms: i64) {
        self.clock.set(self.clock.get() + ms);
    }

    fn binding(&self) -> String {
        new_secret(&self.e)
    }

    fn mailer(&self) -> Mailer<'_> {
        Mailer { sql: &self.db, keys: &self.keys, cfg: &self.mail, code_minutes: 10 }
    }

    /// The alarm's drain, with a sender that takes everything: → (sent, obsolete, expired)
    fn drain(&self) -> (usize, i64, i64) {
        let m = self.mailer();
        let c = m.claim(self.now()).unwrap();
        for o in &c.out {
            self.sent.borrow_mut().push((o.to.clone(), o.mail.clone()));
            m.settle(o.id, Ok(Some(format!("msg-{}", self.sent.borrow().len()))), self.now()).unwrap();
        }
        (c.out.len(), c.obsolete, c.expired)
    }

    fn last_to(&self, address: &str) -> Option<Mail> {
        self.sent.borrow().iter().rev().find(|(to, _)| to == address).map(|(_, m)| m.clone())
    }

    fn code_to(&self, address: &str) -> Option<String> {
        self.last_to(address).and_then(|m| code_in(&m))
    }

    fn start(&self, purpose: &str, email: &str, binding: &str) -> Res<Json> {
        self.id().start(purpose, email, binding, "203.0.113.7", "en", self.now())
    }

    /// An address registered without a passkey: (binding, user, org, token)
    fn registered(&self, address: &str) -> (String, String, String, String) {
        let b = self.binding();
        let s = self.start("register", address, &b).unwrap();
        self.drain();
        let Verified::Enroll(grant) = self
            .id()
            .verify(s["flow"].as_str().unwrap(), &b, &self.code_to(address).unwrap(), None, &here(), self.now())
            .unwrap()
        else {
            panic!("not enrolled")
        };
        let done = self.id().complete(&grant, &b, None, "", &here(), self.now()).unwrap();
        (
            b,
            done["user"].as_str().unwrap().into(),
            done["org"].as_str().unwrap().into(),
            done["token"].as_str().unwrap().into(),
        )
    }
}

fn code_in(m: &Mail) -> Option<String> {
    m.text
        .lines()
        .find(|l| l.starts_with("    ") && l.trim().len() == 8 && l.trim().bytes().all(|c| c.is_ascii_digit()))
        .map(|l| l.trim().to_string())
}

fn reason<T: std::fmt::Debug>(r: Res<T>) -> &'static str {
    match r {
        Err(Fail::No(w)) => w.reason,
        other => panic!("not a refusal: {other:?}"),
    }
}

fn flow(v: &Json) -> String {
    v["flow"].as_str().unwrap().to_string()
}

#[test]
fn registration_proves_an_address_makes_its_account_and_keeps_no_code() {
    let w = World::new(&[]);
    let b = w.binding();
    let s = w.start("register", " Li.Wei@Example.org ", &b).unwrap();
    assert!(flow(&s).starts_with("flw_"));
    assert_eq!(w.drain(), (1, 0, 0));
    let mail = w.last_to("Li.Wei@example.org").unwrap();
    let code = code_in(&mail).unwrap();
    assert!(!mail.subject.contains(&code), "a code is never in the subject");
    assert!(mail.html.contains(&code));
    // nothing of the code in any row
    let dump: String = ["users", "flows", "grants", "outbox", "counters", "sessions", "events"]
        .iter()
        .map(|t| format!("{:?}", w.db.rows(&format!("SELECT * FROM {t}"), &[]).unwrap()))
        .collect();
    assert!(!dump.contains(&code), "the code is derived, never stored");
    let typed = format!("{} {}", &code[..4], &code[4..]); // typed with a space
    let Verified::Enroll(grant) = w.id().verify(&flow(&s), &b, &typed, None, &here(), w.now()).unwrap() else {
        panic!()
    };
    let done = w.id().complete(&grant, &b, None, "", &here(), w.now()).unwrap();
    assert!(done["user"].as_str().unwrap().starts_with("usr_") && done["org"].as_str().unwrap().starts_with("org_"));
    assert_eq!(done["recovery"], json!([]), "no passkey, no recovery codes: the mailbox is the way back in");
    let me = w.id().overview(done["token"].as_str().unwrap(), w.now()).unwrap();
    assert_eq!(me["user"]["address"], "Li.Wei@example.org");
    assert_eq!(me["orgs"][0]["role"], "owner");
    assert_eq!((me["session"]["method"].as_str(), me["session"]["strong"].as_bool()), (Some("email"), Some(false)));
    assert_eq!(me["sessions"].as_array().unwrap().len(), 1);
    assert!(!me.to_string().contains(done["token"].as_str().unwrap()));
}

#[test]
fn s12_3_one_code_redeemed_once_and_its_grant_used_once() {
    let w = World::new(&[]);
    let b = w.binding();
    let s = w.start("register", "a@example.org", &b).unwrap();
    w.drain();
    let code = w.code_to("a@example.org").unwrap();
    let outs: Vec<_> = (0..8).map(|_| w.id().verify(&flow(&s), &b, &code, None, &here(), w.now())).collect();
    assert_eq!(outs.iter().filter(|o| o.is_ok()).count(), 1);
    let Ok(Verified::Enroll(grant)) = &outs[0] else { panic!() };
    assert!(outs[1..].iter().all(|o| matches!(o, Err(Fail::No(Why { reason: "flow", .. })))));
    assert!(w.id().complete(grant, &b, None, "", &here(), w.now()).is_ok());
    assert_eq!(reason(w.id().complete(grant, &b, None, "", &here(), w.now())), "grant");
    assert_eq!(w.db.scalar("SELECT COUNT(*) FROM users", &[]).unwrap(), 1);
}

#[test]
fn s12_3_a_registrations_code_is_not_a_signins() {
    let w = World::new(&[]);
    let (b, ..) = w.registered("a@example.org");
    w.start("register", "b@example.org", &b).unwrap();
    let sig = w.start("signin", "a@example.org", &b).unwrap();
    w.drain();
    let reg_code = w.code_to("b@example.org").unwrap();
    assert_eq!(reason(w.id().verify(&flow(&sig), &b, &reg_code, None, &here(), w.now())), "code");
    assert_ne!(w.code_to("a@example.org").unwrap(), reg_code);
}

#[test]
fn s12_3_resends_and_late_mail_only_the_current_generation_is_a_code() {
    let w = World::new(&[]);
    let b = w.binding();
    let s = w.start("register", "a@example.org", &b).unwrap();
    w.drain();
    let first = w.code_to("a@example.org").unwrap();
    let wrong = if first == "00000000" { "11111111" } else { "00000000" };
    assert!(matches!(
        w.id().verify(&flow(&s), &b, wrong, None, &here(), w.now()),
        Err(Fail::No(Why { reason: "code", left: Some(4), .. }))
    ));
    match w.id().resend(&flow(&s), &b, w.now()) {
        Err(Fail::No(Why { reason: "cooldown", retry: Some(r), .. })) => assert!((1..=60).contains(&r)),
        other => panic!("{other:?}"),
    }
    w.advance(MIN);
    w.id().resend(&flow(&s), &b, w.now()).unwrap();
    // the first code arrives late, after the resend: no code any more, and the resend gave no attempts back
    assert!(matches!(
        w.id().verify(&flow(&s), &b, &first, None, &here(), w.now()),
        Err(Fail::No(Why { reason: "code", left: Some(3), .. }))
    ));
    w.drain();
    let second = w.code_to("a@example.org").unwrap();
    assert_ne!(second, first);
    assert!(matches!(w.id().verify(&flow(&s), &b, &second, None, &here(), w.now()), Ok(Verified::Enroll(_))));
}

#[test]
fn a_resend_before_the_first_mail_left_drops_the_first() {
    let w = World::new(&[]);
    let b = w.binding();
    let s = w.start("register", "a@example.org", &b).unwrap();
    w.advance(MIN);
    w.id().resend(&flow(&s), &b, w.now()).unwrap();
    assert_eq!(w.drain(), (1, 1, 0));
    assert!(matches!(
        w.id().verify(&flow(&s), &b, &w.code_to("a@example.org").unwrap(), None, &here(), w.now()),
        Ok(Verified::Enroll(_))
    ));
}

#[test]
fn s12_3_another_flow_does_not_undo_the_first_and_a_code_works_only_in_its_browser() {
    let w = World::new(&[]);
    let (mine, theirs) = (w.binding(), w.binding());
    let s = w.start("register", "a@example.org", &mine).unwrap();
    w.drain();
    let code = w.code_to("a@example.org").unwrap();
    w.id().start("register", "a@example.org", &theirs, "192.0.2.9", "en", w.now()).unwrap();
    assert_eq!(reason(w.id().verify(&flow(&s), &theirs, &code, None, &here(), w.now())), "flow");
    assert!(matches!(w.id().verify(&flow(&s), &mine, &code, None, &here(), w.now()), Ok(Verified::Enroll(_))));
}

#[test]
fn s12_3_no_credential_before_the_address_is_proved() {
    let w = World::new(&[]);
    let b = w.binding();
    assert_eq!(reason(w.id().enroll_options(&new_secret(&w.e), &b, w.now())), "grant");
    let s = w.start("register", "victim@example.org", &b).unwrap();
    w.drain();
    let Verified::Enroll(grant) =
        w.id().verify(&flow(&s), &b, &w.code_to("victim@example.org").unwrap(), None, &here(), w.now()).unwrap()
    else {
        panic!()
    };
    // the grant in another browser is nothing
    assert_eq!(reason(w.id().enroll_options(&grant, &w.binding(), w.now())), "grant");
    assert_eq!(reason(w.id().complete(&grant, &w.binding(), None, "", &here(), w.now())), "grant");
    // a passkey made for a challenge this grant was not given
    w.id().enroll_options(&grant, &b, w.now()).unwrap();
    let a = Authenticator::new(ES256, &w.e);
    let stray = a.create(&b64url(&random::<32>(&w.e)), &Twist::default());
    assert_eq!(reason(w.id().complete(&grant, &b, Some(&stray), "", &here(), w.now())), "challenge");
    assert_eq!(w.db.scalar("SELECT COUNT(*) FROM users", &[]).unwrap(), 0);
}

#[test]
fn a_passkey_at_registration_gives_recovery_codes_and_signs_in_alone() {
    let w = World::new(&[]);
    let b = w.binding();
    let s = w.start("register", "a@example.org", &b).unwrap();
    w.drain();
    let Verified::Enroll(grant) =
        w.id().verify(&flow(&s), &b, &w.code_to("a@example.org").unwrap(), None, &here(), w.now()).unwrap()
    else {
        panic!()
    };
    let opts = w.id().enroll_options(&grant, &b, w.now()).unwrap();
    assert_eq!(
        (
            opts["rp"]["id"].as_str(),
            opts["authenticatorSelection"]["userVerification"].as_str(),
            opts["attestation"].as_str()
        ),
        (Some("impf.ai"), Some("required"), Some("none"))
    );
    let mut a = Authenticator::new(RS256, &w.e);
    a.user = crate::codec::from_b64url(opts["user"]["id"].as_str().unwrap()).unwrap(); // the handle the page passes on
    let done = w
        .id()
        .complete(
            &grant,
            &b,
            Some(&a.create(opts["challenge"].as_str().unwrap(), &Twist::default())),
            "Laptop",
            &here(),
            w.now(),
        )
        .unwrap();
    let recovery: Vec<String> = serde_json::from_value(done["recovery"].clone()).unwrap();
    assert_eq!(recovery.len(), 10);
    assert!(recovery.iter().all(|r| read_recovery(r).as_deref() == Some(r.as_str())));
    let token = done["token"].as_str().unwrap();
    let me = w.id().overview(token, w.now()).unwrap();
    assert_eq!(
        (me["session"]["strong"].as_bool(), me["passkeys"][0]["name"].as_str(), me["recovery_left"].as_i64()),
        (Some(true), Some("Laptop"), Some(10))
    );
    assert!(!format!("{:?}", w.db.rows("SELECT * FROM recovery_codes", &[]).unwrap()).contains(&recovery[0]));
    // signing in with the passkey alone; its challenge used once
    let so = w.id().signin_options(w.now()).unwrap();
    let cred = a.get(so["challenge"].as_str().unwrap(), &Twist::default());
    assert!(w.id().signin(&cred, &here(), w.now()).is_ok());
    assert_eq!(reason(w.id().signin(&cred, &here(), w.now())), "challenge");
    // an assertion whose user handle is not its owner's
    let so = w.id().signin_options(w.now()).unwrap();
    let other = Twist { user_handle: Some(Some(b64url(&[0u8; 16]))), ..Default::default() };
    assert_eq!(
        reason(w.id().signin(&a.get(so["challenge"].as_str().unwrap(), &other), &here(), w.now())),
        "passkey_user"
    );
}

#[test]
fn s12_3_an_account_a_passkey_guards_is_not_opened_by_its_mailbox_alone() {
    let w = World::new(&[]);
    let (b, _, _, token) = w.registered("a@example.org");
    let opts = w.id().add_options(&token, w.now()).unwrap();
    let mut a = Authenticator::new(ES256, &w.e);
    a.user = crate::codec::from_b64url(opts["user"]["id"].as_str().unwrap()).unwrap();
    let added = w
        .id()
        .add(&token, &a.create(opts["challenge"].as_str().unwrap(), &Twist::default()), "Phone", w.now())
        .unwrap();
    let recovery: Vec<String> = serde_json::from_value(added["recovery"].clone()).unwrap();
    assert_eq!((added["first"].as_bool(), recovery.len()), (Some(true), 10));
    // someone with the mailbox, in another browser
    let thief = w.binding();
    let s = w.id().start("signin", "a@example.org", &thief, "192.0.2.66", "en", w.now()).unwrap();
    w.drain();
    let Verified::Second(grant) =
        w.id().verify(&flow(&s), &thief, &w.code_to("a@example.org").unwrap(), None, &here(), w.now()).unwrap()
    else {
        panic!("an email code alone opened an account a passkey guards")
    };
    assert_eq!(reason(w.id().second(&grant, &thief, "AAAA-BBBB-CCCC-DDDD", &here(), w.now())), "recovery");
    // a recovery code, typed loosely (lower case, an O for a zero): through — and every other session ends
    let typed = recovery[3].to_lowercase().replace('0', "O");
    let ok = w.id().second(&grant, &thief, &typed, &here(), w.now()).unwrap();
    assert_eq!(ok["left"], 9);
    assert!(w.id().current(&token, w.now()).unwrap().is_none(), "the other sessions ended");
    assert!(w.id().current(ok["token"].as_str().unwrap(), w.now()).unwrap().is_some());
    assert_eq!(reason(w.id().second(&grant, &thief, &typed, &here(), w.now())), "grant");
    w.drain();
    assert_eq!(w.last_to("a@example.org").unwrap().subject, "TaoChronos: a recovery code was used");
    let _ = b;
}

#[test]
fn existing_and_unknown_addresses_are_answered_alike_and_the_mail_alone_says() {
    let w = World::new(&[]);
    w.registered("known@example.org");
    w.sent.borrow_mut().clear();
    let b = w.binding();
    let mut shapes = Vec::new();
    for (purpose, email) in [
        ("register", "known@example.org"),
        ("register", "new@example.org"),
        ("signin", "known@example.org"),
        ("signin", "nobody@example.org"),
    ] {
        let out = w.start(purpose, email, &b).unwrap();
        let mut keys: Vec<_> = out.as_object().unwrap().keys().cloned().collect();
        keys.sort();
        shapes.push(keys);
    }
    assert!(shapes.windows(2).all(|p| p[0] == p[1]), "the same answer, whatever the address");
    w.drain();
    let subjects: Vec<(String, String, Option<String>)> =
        w.sent.borrow().iter().map(|(to, m)| (to.clone(), m.subject.clone(), code_in(m))).collect();
    let find = |to: &str, subject: &str| subjects.iter().find(|(t, s, _)| t == to && s == subject).map(|x| x.2.clone());
    assert_eq!(find("known@example.org", "TaoChronos: you already have an account"), Some(None));
    assert!(find("new@example.org", "TaoChronos: confirm your email address").flatten().is_some());
    assert!(find("known@example.org", "TaoChronos: your sign-in code").flatten().is_some());
    assert_eq!(find("nobody@example.org", "TaoChronos: no account uses this address"), Some(None));
    // a flow that sent no code takes none, and answers as a wrong code does, attempt for attempt
    let f =
        w.db.row("SELECT flow_id FROM flows WHERE email_key = 'nobody@example.org'", &[])
            .unwrap()
            .unwrap()
            .text("flow_id");
    assert!(matches!(
        w.id().verify(&f, &b, "12345678", None, &here(), w.now()),
        Err(Fail::No(Why { reason: "code", left: Some(4), .. }))
    ));
}

#[test]
fn limits_attempts_address_network_service_and_registration_closed() {
    let w =
        World::new(&[("MAILS_PER_ADDRESS_HOUR", "3"), ("STARTS_PER_NETWORK_HOUR", "4"), ("AUTH_MAILS_PER_DAY", "6")]);
    let b = w.binding();
    let s = w.start("register", "a@example.org", &b).unwrap();
    for left in (1..=4).rev() {
        assert!(
            matches!(w.id().verify(&flow(&s), &b, "99999999", None, &here(), w.now()), Err(Fail::No(Why { left: Some(l), .. })) if l == left)
        );
    }
    assert_eq!(reason(w.id().verify(&flow(&s), &b, "99999999", None, &here(), w.now())), "attempts");
    assert_eq!(
        reason(w.id().verify(&flow(&s), &b, "99999999", None, &here(), w.now())),
        "flow",
        "a flow out of attempts is over"
    );
    for i in 0..2 {
        w.id().start("register", "a@example.org", &b, &format!("198.51.100.{i}"), "en", w.now()).unwrap();
    }
    assert_eq!(reason(w.id().start("register", "A@example.org", &b, "198.51.100.20", "en", w.now())), "address");
    for i in 0..3 {
        w.id().start("signin", &format!("n{i}@example.org"), &b, "2001:db8::/64", "en", w.now()).unwrap();
    }
    assert_eq!(
        reason(w.id().start("signin", "z@example.org", &b, "192.0.2.1", "en", w.now())),
        "service",
        "six mails today in all"
    );
    let n = World::new(&[("STARTS_PER_NETWORK_HOUR", "2")]);
    for i in 0..2 {
        n.id().start("signin", &format!("m{i}@example.org"), &b, "2001:db8::/64", "en", n.now()).unwrap();
    }
    assert_eq!(reason(n.id().start("signin", "m9@example.org", &b, "2001:db8::/64", "en", n.now())), "network");
    assert_eq!(reason(w.start("register", "not an address", &b)), "email");
    let closed = World::new(&[("REGISTRATION", "off")]);
    assert_eq!(reason(closed.start("register", "a@example.org", &b)), "closed");
    assert!(closed.start("signin", "a@example.org", &b).is_ok());
}

#[test]
fn a_codes_time_and_a_flows_sends_and_a_mail_past_its_time() {
    let w = World::new(&[]);
    let b = w.binding();
    let s = w.start("register", "a@example.org", &b).unwrap();
    w.drain();
    w.advance(10 * MIN + 1);
    assert_eq!(
        reason(w.id().verify(&flow(&s), &b, &w.code_to("a@example.org").unwrap(), None, &here(), w.now())),
        "expired"
    );
    for _ in 0..4 {
        w.id().resend(&flow(&s), &b, w.now()).unwrap();
        w.advance(MIN);
    }
    assert_eq!(reason(w.id().resend(&flow(&s), &b, w.now())), "sends");
    let u = World::new(&[]);
    u.start("register", "b@example.org", &b).unwrap();
    u.advance(11 * MIN);
    assert_eq!(u.drain(), (0, 0, 1));
}

#[test]
fn s12_3_a_delivery_event_is_not_a_verification() {
    let w = World::new(&[]);
    let b = w.binding();
    let s = w.start("register", "a@example.org", &b).unwrap();
    w.drain();
    let ev = |id: &str, status: &str| {
        json!({ "type": format!("cf.email.sending.message.{status}"),
        "payload": { "eventId": id, "messageId": "msg-1", "terminal": status != "deferred", "delivery": { "status": status, "smtpStatusCode": "250" } },
        "metadata": { "eventTimestamp": "2026-11-27T08:00:02Z" } })
    };
    let out = delivery_events(&w.db, &[ev("e1", "delivered"), ev("e1", "delivered"), ev("e2", "deferred"), json!({ "type": "x" }),
        json!({ "type": "cf.email.sending.message.delivered", "payload": { "eventId": "e3", "messageId": "msg-unknown" } })]).unwrap();
    assert_eq!(out, (2, 2, 1));
    assert_eq!(
        w.mailer().status(&flow(&s)).unwrap().unwrap()["delivery"],
        "delivered",
        "a later deferral does not undo a delivery"
    );
    assert_eq!(w.db.scalar("SELECT COUNT(*) FROM users", &[]).unwrap(), 0);
    assert_eq!(w.db.row("SELECT state FROM flows", &[]).unwrap().unwrap().text("state"), "pending");
}

#[test]
fn sending_fails_given_up_or_tried_again_never_past_its_time() {
    let w = World::new(&[]);
    let b = w.binding();
    w.start("register", "a@example.org", &b).unwrap();
    let m = w.mailer();
    let c = m.claim(w.now()).unwrap();
    assert_eq!(m.settle(c.out[0].id, Err(Some("E_RECIPIENT_SUPPRESSED".into())), w.now()).unwrap(), "failed");
    w.start("register", "b@example.org", &b).unwrap();
    let c = m.claim(w.now()).unwrap();
    let id = c.out[0].id;
    assert_eq!(m.settle(id, Err(Some("E_RATE_LIMIT_EXCEEDED".into())), w.now()).unwrap(), "later");
    let next = m.next().unwrap().unwrap();
    assert!(next > w.now());
    assert!(m.claim(w.now()).unwrap().out.is_empty(), "not before its time");
    w.clock.set(next);
    let c = m.claim(w.now()).unwrap();
    assert_eq!(m.settle(c.out[0].id, Err(None), w.now()).unwrap(), "later", "no answer at all: tried again");
    w.advance(2 * MIN);
    let c = m.claim(w.now()).unwrap();
    assert_eq!(m.settle(c.out[0].id, Ok(Some("msg-x".into())), w.now()).unwrap(), "sent");
    let row = w.db.row("SELECT * FROM outbox WHERE id = ?", crate::args![id]).unwrap().unwrap();
    assert_eq!((row.text("state"), row.int("attempts"), row.text("message_id")), ("sent".into(), 3, "msg-x".into()));
    // a claim that never came back is due again after two minutes
    w.start("register", "c@example.org", &b).unwrap();
    assert_eq!(m.claim(w.now()).unwrap().out.len(), 1);
    assert!(m.claim(w.now()).unwrap().out.is_empty());
    w.advance(3 * MIN);
    assert_eq!(m.claim(w.now()).unwrap().out.len(), 1);
}

#[test]
fn s12_3_a_changed_address_keeps_the_person_their_organisation_and_their_passkeys() {
    let w = World::new(&[]);
    let (b, user, org, token) = w.registered("old@example.org");
    let opts = w.id().add_options(&token, w.now()).unwrap();
    let mut a = Authenticator::new(ES256, &w.e);
    a.user = crate::codec::from_b64url(opts["user"]["id"].as_str().unwrap()).unwrap();
    w.id().add(&token, &a.create(opts["challenge"].as_str().unwrap(), &Twist::default()), "Key", w.now()).unwrap();
    w.advance(6 * MIN);
    assert_eq!(
        reason(w.id().start_email_change(&token, "new@example.org", &b, "198.51.100.1", "en", w.now())),
        "stepup"
    );
    let su = w.id().stepup_options(&token, w.now()).unwrap();
    let token2 = w.id().stepup(&token, &a.get(su["challenge"].as_str().unwrap(), &Twist::default()), w.now()).unwrap();
    assert!(w.id().current(&token, w.now()).unwrap().is_none(), "a raised session has a new token; the old is nothing");
    w.registered("taken@example.org");
    // an address that has an account: answered as any other — its owner alone is told, by mail, and given no code
    let taken = w.id().start_email_change(&token2, "TAKEN@example.org", &b, "198.51.100.1", "en", w.now()).unwrap();
    w.drain();
    let notice = w.last_to("TAKEN@example.org").unwrap();
    assert_eq!(notice.subject, "TaoChronos: this address already has an account");
    assert!(code_in(&notice).is_none());
    assert_eq!(reason(w.id().verify(&flow(&taken), &b, "12345678", Some(&user), &here(), w.now())), "code");
    let ch = w.id().start_email_change(&token2, "new@example.org", &b, "198.51.100.1", "en", w.now()).unwrap();
    w.drain();
    let code = w.code_to("new@example.org").unwrap();
    let (_, other_user, _, _) = w.registered("other@example.org");
    assert_eq!(reason(w.id().verify(&flow(&ch), &b, &code, Some(&other_user), &here(), w.now())), "flow");
    assert_eq!(w.id().verify(&flow(&ch), &b, &code, Some(&user), &here(), w.now()).unwrap(), Verified::Done);
    let me = w.id().overview(&token2, w.now()).unwrap();
    assert_eq!(
        (me["user"]["id"].as_str(), me["user"]["address"].as_str()),
        (Some(user.as_str()), Some("new@example.org"))
    );
    assert_eq!((me["orgs"][0]["id"].as_str(), me["passkeys"].as_array().map(Vec::len)), (Some(org.as_str()), Some(1)));
    w.drain();
    let told = w.last_to("old@example.org").unwrap();
    assert_eq!(told.subject, "TaoChronos: your account's email address changed");
    assert!(told.text.contains("n…@example.org") && !told.text.contains("new@example.org"));
}

#[test]
fn sessions_end_idle_and_in_time_by_their_owner_and_removing_a_passkey_needs_a_touch() {
    let w = World::new(&[]);
    let (_, _, _, t1) = w.registered("a@example.org");
    w.advance(6 * DAY);
    assert!(w.id().current(&t1, w.now()).unwrap().is_some());
    w.advance(6 * DAY);
    assert!(w.id().current(&t1, w.now()).unwrap().is_some());
    w.advance(7 * DAY + 1);
    assert!(w.id().current(&t1, w.now()).unwrap().is_none(), "a week unused");
    let (_, _, _, t2) = w.registered("b@example.org");
    for _ in 0..7 {
        w.advance(5 * DAY);
        let _ = w.id().current(&t2, w.now());
    }
    assert!(w.id().current(&t2, w.now()).unwrap().is_none(), "thirty days, however used");
    let (b3, _, _, t3) = w.registered("c@example.org");
    let s = w.start("signin", "c@example.org", &b3).unwrap();
    w.drain();
    let Verified::Session(second) =
        w.id().verify(&flow(&s), &b3, &w.code_to("c@example.org").unwrap(), None, &here(), w.now()).unwrap()
    else {
        panic!()
    };
    let list = w.id().overview(&t3, w.now()).unwrap()["sessions"].clone();
    assert_eq!(list.as_array().unwrap().len(), 2);
    let theirs = list.as_array().unwrap().iter().find(|s| !s["current"].as_bool().unwrap()).unwrap()["id"]
        .as_str()
        .unwrap()
        .to_string();
    assert!(w.id().end_session(&t3, &theirs, w.now()).unwrap());
    assert!(w.id().current(&second.token, w.now()).unwrap().is_none());
    w.id().end_others(&t3, w.now()).unwrap();
    w.id().sign_out(&t3, w.now()).unwrap();
    assert!(w.id().current(&t3, w.now()).unwrap().is_none());
    // removing a passkey and renewing recovery codes: a touch first
    let (_, _, _, t4) = w.registered("d@example.org");
    let opts = w.id().add_options(&t4, w.now()).unwrap();
    let mut a = Authenticator::new(ES256, &w.e);
    a.user = crate::codec::from_b64url(opts["user"]["id"].as_str().unwrap()).unwrap();
    w.id().add(&t4, &a.create(opts["challenge"].as_str().unwrap(), &Twist::default()), "Key", w.now()).unwrap();
    w.advance(6 * MIN);
    let id = w.id().overview(&t4, w.now()).unwrap()["passkeys"][0]["id"].as_str().unwrap().to_string();
    assert_eq!(reason(w.id().remove(&t4, &id, w.now())), "stepup");
    assert_eq!(reason(w.id().renew_recovery(&t4, w.now())), "stepup");
    let su = w.id().stepup_options(&t4, w.now()).unwrap();
    let up = w.id().stepup(&t4, &a.get(su["challenge"].as_str().unwrap(), &Twist::default()), w.now()).unwrap();
    assert_eq!(w.id().renew_recovery(&up, w.now()).unwrap().len(), 10);
    assert_eq!(w.id().remove(&up, &id, w.now()).unwrap(), json!({ "last": true }));
    assert_eq!(w.id().overview(&up, w.now()).unwrap()["recovery_left"], 0, "no passkey left, no recovery codes");
    w.advance(11 * MIN);
    assert_eq!(reason(w.id().add_options(&up, w.now())), "fresh", "a first passkey needs a fresh sign-in");
}

#[test]
fn turnstile_tokens_once_recovery_codes_as_typed_and_networks_by_their_64() {
    let w = World::new(&[]);
    assert!(w.id().first_use("tok", w.now()).unwrap());
    assert!(!w.id().first_use("tok", w.now()).unwrap());
    w.advance(11 * MIN);
    w.id().prune(w.now()).unwrap();
    assert!(w.id().first_use("tok", w.now()).unwrap());
    assert_eq!(read_recovery("abcd efgh jkmn pqrs").as_deref(), Some("ABCD-EFGH-JKMN-PQRS"));
    assert_eq!(read_recovery("O1L1-0000-0000-0000").as_deref(), Some("0111-0000-0000-0000"));
    assert_eq!(read_recovery("ABCD-EFGH-JKMN-PQR"), None);
    assert_eq!(read_recovery("ABCD-EFGH-JKMN-PQRU"), None, "U is no Crockford letter");
    assert_eq!(ip_key("203.0.113.7"), "203.0.113.7");
    assert_eq!(ip_key("2001:DB8:1:2:3:4:5:6"), "2001:db8:1:2::/64");
    assert_eq!(ip_key("2001:db8::1"), "2001:db8:0:0::/64");
    assert_eq!(ip_key("2001:db8:1:2::9"), "2001:db8:1:2::/64");
}

#[test]
fn every_template_renders_in_both_languages_with_its_code_where_it_has_one() {
    let cfg = MailConfig::from_vars(|_| None);
    let vars = json!({ "code": "12345678", "minutes": 10, "at": "2026-11-27 08:00 UTC", "to": "n…@example.org", "name": "{code} <b>x</b>", "left": 3 });
    for name in TEMPLATES {
        for loc in ["zh", "en"] {
            let m = render(name, loc, &vars, &cfg).unwrap();
            assert!(!m.subject.is_empty() && m.html.starts_with("<!doctype html>"));
            assert!(!m.subject.contains("12345678"));
            assert_eq!(m.text.contains("12345678"), coded(name), "{name} {loc}");
            let left = m.text.replace("{code} <b>x</b>", "");
            assert!(!left.contains('{'), "{name} {loc}: a placeholder left: {left}");
            if name.starts_with("passkey") {
                assert!(
                    !m.text.contains("<b>x</b>") && !m.html.contains("x</b>"),
                    "no name a person wrote is in a mail"
                );
            }
        }
    }
    assert!(render("nothing", "en", &vars, &cfg).is_none());
}

#[test]
fn an_address_change_tells_nobody_but_the_addresses_owner_whether_it_is_taken_and_limits_come_first() {
    let w = World::new(&[("STARTS_PER_NETWORK_HOUR", "50"), ("EMAIL_CHANGES_PER_HOUR", "3")]);
    for i in 0..3 {
        w.registered(&format!("known{i}@example.org"));
    }
    let (b, _, _, token) = w.registered("asker@example.org");
    let answer = |r: Res<Json>| match r {
        Ok(v) => format!("ok:{}", v.as_object().unwrap().keys().cloned().collect::<Vec<_>>().join(",")),
        Err(Fail::No(why)) => why.reason.to_string(),
        Err(e) => panic!("{e:?}"),
    };
    // a registered address and a free one: the same answer
    let known = answer(w.id().start_email_change(&token, "known0@example.org", &b, "198.51.100.1", "en", w.now()));
    let free = answer(w.id().start_email_change(&token, "free0@example.org", &b, "198.51.100.1", "en", w.now()));
    assert_eq!(known, free);
    assert!(known.starts_with("ok:"));
    // the account's own allowance spent: the same refusal for both, however often asked
    w.id().start_email_change(&token, "free1@example.org", &b, "198.51.100.1", "en", w.now()).unwrap();
    for round in 0..10 {
        let known = reason(w.id().start_email_change(
            &token,
            &format!("known{}@example.org", round % 3),
            &b,
            "198.51.100.1",
            "en",
            w.now(),
        ));
        let free = reason(w.id().start_email_change(
            &token,
            &format!("nobody{round}@example.org"),
            &b,
            "198.51.100.1",
            "en",
            w.now(),
        ));
        assert_eq!((known, free), ("account", "account"));
    }
    // and the wider network's allowance stands over every /64 of a /48
    let n = World::new(&[("STARTS_PER_WIDE_NETWORK_HOUR", "3")]);
    let b = n.binding();
    for i in 0..3 {
        n.id()
            .start("signin", &format!("m{i}@example.org"), &b, &format!("2001:db8:1:{i}::/64"), "en", n.now())
            .unwrap();
    }
    assert_eq!(reason(n.id().start("signin", "m9@example.org", &b, "2001:db8:1:ff::/64", "en", n.now())), "network");
    assert!(n.id().start("signin", "m9@example.org", &b, "2001:db8:2:0::/64", "en", n.now()).is_ok(), "another /48");
    assert_eq!(
        (wide("2001:db8:1:2::/64"), wide("203.0.113.7")),
        ("2001:db8:1::/48".to_string(), "203.0.113.0/24".to_string())
    );
}

#[test]
fn what_the_old_address_began_ends_when_the_account_moves() {
    let w = World::new(&[]);
    let (b, user, _, token) = w.registered("old@example.org");
    // someone who reads the old mailbox starts a sign-in in their own browser
    let thief = w.binding();
    let s = w.id().start("signin", "old@example.org", &thief, "192.0.2.66", "en", w.now()).unwrap();
    w.drain();
    let ch = w.id().start_email_change(&token, "new@example.org", &b, "198.51.100.1", "en", w.now()).unwrap();
    w.drain();
    assert_eq!(
        w.id().verify(&flow(&ch), &b, &w.code_to("new@example.org").unwrap(), Some(&user), &here(), w.now()).unwrap(),
        Verified::Done
    );
    // the old address's flow is over: no resend, no code of it opens the account
    w.advance(MIN);
    assert_eq!(reason(w.id().resend(&flow(&s), &thief, w.now())), "flow");
    assert_eq!(
        reason(w.id().verify(
            &flow(&s),
            &thief,
            &w.code_to("old@example.org").unwrap_or_default(),
            None,
            &here(),
            w.now()
        )),
        "flow"
    );
    // a grant the old address earned before the move (an account a passkey guards) is spent too
    let w = World::new(&[]);
    let (b, user, _, token) = w.registered("old2@example.org");
    let opts = w.id().add_options(&token, w.now()).unwrap();
    let mut a = Authenticator::new(ES256, &w.e);
    a.user = crate::codec::from_b64url(opts["user"]["id"].as_str().unwrap()).unwrap();
    let added =
        w.id().add(&token, &a.create(opts["challenge"].as_str().unwrap(), &Twist::default()), "Key", w.now()).unwrap();
    let recovery = added["recovery"][0].as_str().unwrap().to_string();
    let thief = w.binding();
    let s = w.id().start("signin", "old2@example.org", &thief, "192.0.2.66", "en", w.now()).unwrap();
    w.drain();
    let Verified::Second(grant) =
        w.id().verify(&flow(&s), &thief, &w.code_to("old2@example.org").unwrap(), None, &here(), w.now()).unwrap()
    else {
        panic!()
    };
    let ch = w.id().start_email_change(&token, "new2@example.org", &b, "198.51.100.1", "en", w.now()).unwrap();
    w.drain();
    w.id().verify(&flow(&ch), &b, &w.code_to("new2@example.org").unwrap(), Some(&user), &here(), w.now()).unwrap();
    assert_eq!(reason(w.id().second(&grant, &thief, &recovery, &here(), w.now())), "grant");
}

#[test]
fn the_ceremonies_are_cleaned_by_an_index_and_names_keep_no_invisible_characters() {
    let w = World::new(&[]);
    for _ in 0..200 {
        w.id().signin_options(w.now()).unwrap();
    }
    let plan: Vec<String> =
        w.db.rows("EXPLAIN QUERY PLAN DELETE FROM ceremonies WHERE expires < 1", &[])
            .unwrap()
            .iter()
            .map(|r| r.text("detail"))
            .collect();
    assert!(plan.iter().any(|d| d.contains("ceremonies_expires")), "{plan:?}");
    assert_eq!(clean_name("Lap\u{202e}pot\u{200b} "), "Lappot");
    assert_eq!(clean_name("\u{2066}\u{2069}"), "passkey");
    assert_eq!(clean_name("Phone"), "Phone");
}
