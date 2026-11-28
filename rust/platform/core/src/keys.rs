//! An API key: `tao_<env>_<org>_<secret><check>` — 82 characters.
//!
//!   env     live (draws on the organisation's credits) · test (a small free allowance a day, never credits)
//!   org     the organisation's id without its prefix (26 of Crockford's characters): which Durable Object holds the
//!           key, read without a lookup — the id is no secret, the secret is
//!   secret  24 random bytes (192 bits), 39 characters
//!   check   CRC-32 of everything before it, 7 characters: a key mistyped or cut short is refused before anything is
//!           asked, and a scanner finds keys in a text with few false alarms (the distinctive prefix does the rest)
//!
//! What is kept: the SHA-256 of the whole key, and how it is shown — `tao_live_…` and its last four characters (the
//! checksum's: no bit of the secret).  The key itself is shown once, when it is made.

use crate::codec::{base32, crc32, is_base32};
use crate::crypto::{Entropy, digest, random};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum KeyEnv {
    Live,
    Test,
}

impl KeyEnv {
    pub fn as_str(self) -> &'static str {
        match self {
            KeyEnv::Live => "live",
            KeyEnv::Test => "test",
        }
    }

    pub fn parse(s: &str) -> Option<KeyEnv> {
        match s {
            "live" => Some(KeyEnv::Live),
            "test" => Some(KeyEnv::Test),
            _ => None,
        }
    }
}

const ORG: usize = 26;
const SECRET: usize = 39;
const CHECK: usize = 7;

/// An organisation's id: `org_` and 26 of Crockford's characters.
pub fn is_org_id(id: &str) -> bool {
    id.len() == 4 + ORG && id.starts_with("org_") && is_base32(&id[4..])
}

fn check(body: &str) -> String {
    base32(&crc32(body.as_bytes()).to_be_bytes())
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NewKey {
    /// the key, shown once
    pub key: String,
    /// what is kept: SHA-256 of the key
    pub digest: String,
    /// how it is shown from then on
    pub shown: String,
}

/// A new key of an organisation.  None when the id is not an organisation's.
pub fn mint(e: &dyn Entropy, env: KeyEnv, org_id: &str) -> Option<NewKey> {
    if !is_org_id(org_id) {
        return None;
    }
    let secret = base32(&random::<24>(e));
    let body = format!("tao_{}_{}_{secret}", env.as_str(), &org_id[4..]);
    let key = format!("{body}{}", check(&body));
    Some(NewKey { digest: digest(&key), shown: shown(&key, env), key })
}

pub fn shown(key: &str, env: KeyEnv) -> String {
    format!("tao_{}_…{}", env.as_str(), &key[key.len().saturating_sub(4)..])
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ParsedKey {
    pub env: KeyEnv,
    /// `org_…`: the Durable Object that holds the key
    pub org: String,
    /// SHA-256 of the key: what the object looks it up by
    pub digest: String,
}

/// A key as a request carries it, or None: not one's shape, or its checksum wrong.
pub fn parse(text: &str) -> Option<ParsedKey> {
    let rest = text.strip_prefix("tao_")?;
    let (env, rest) = rest.split_once('_')?;
    let env = KeyEnv::parse(env)?;
    let (org, tail) = rest.split_once('_')?;
    if org.len() != ORG || tail.len() != SECRET + CHECK || !is_base32(org) || !is_base32(tail) {
        return None;
    }
    let body = &text[..text.len() - CHECK];
    if check(body) != text[text.len() - CHECK..] {
        return None;
    }
    Some(ParsedKey { env, org: format!("org_{org}"), digest: digest(text) })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::crypto::new_id;
    use crate::crypto::tests::Counter;
    use std::cell::Cell;

    #[test]
    fn a_key_made_is_read_back_and_a_mistyped_one_is_not() {
        let e = Counter(Cell::new(1));
        let org = new_id(&e, "org", 16);
        assert!(is_org_id(&org));
        let k = mint(&e, KeyEnv::Live, &org).unwrap();
        assert_eq!(k.key.len(), 82);
        assert!(k.key.starts_with("tao_live_"));
        assert_eq!(k.shown, format!("tao_live_…{}", &k.key[78..]));
        let p = parse(&k.key).unwrap();
        assert_eq!((p.env, p.org.as_str(), p.digest.as_str()), (KeyEnv::Live, org.as_str(), k.digest.as_str()));
        // each character changed, in turn, to another of the alphabet: the checksum catches every one
        for i in 9..k.key.len() {
            if k.key.as_bytes()[i] == b'_' {
                continue;
            }
            let mut b = k.key.clone().into_bytes();
            b[i] = if b[i] == b'0' { b'1' } else { b'0' };
            assert_eq!(parse(std::str::from_utf8(&b).unwrap()), None, "position {i}");
        }
        assert_eq!(parse(&k.key[..81]), None);
        assert_eq!(parse(&k.key.replace("tao_live_", "tao_prod_")), None);
        assert_eq!(parse(&k.key.to_uppercase()), None);
        assert_eq!(parse(""), None);
        assert!(mint(&e, KeyEnv::Test, "org_short").is_none());
        let t = mint(&e, KeyEnv::Test, &org).unwrap();
        assert_eq!(parse(&t.key).unwrap().env, KeyEnv::Test);
        assert_ne!(t.digest, k.digest);
    }
}
