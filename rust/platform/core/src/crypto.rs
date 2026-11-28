//! What the platform keeps of a secret, and the secrets it makes (docs/adr/0038-accounts-keys-and-credits.md):
//!
//! * a secret of 192 bits or more (a session's token, a browser's binding, a grant, an API key) is kept as its SHA-256
//!   and nothing else: nobody guesses it, so a digest without a key is enough — and it outlives any rotation of the
//!   service's secret;
//! * a recovery code (80 random bits, typed by a person) likewise;
//! * a code sent by email — 8 digits, 27 bits, which a digest would give away to whoever read the rows — is kept
//!   nowhere: it is *derived*, an HMAC under the service's secret of what it is for (its purpose, its flow, its
//!   generation, its address), computed again when the mail leaves and again when the code is typed.  No code is in a
//!   table, an outbox or a log, sealed or plain.  The secret is a Worker secret, never in a row: rotating it voids
//!   only the codes in flight.
//!
//! Randomness comes from the caller (`Entropy`): in a Worker, `crypto.getRandomValues`; in the tests, whatever they
//! choose — this crate reads no clock and no system source of its own.

use hmac::{Hmac, KeyInit, Mac};
use sha2::{Digest, Sha256};

use crate::codec::{b64url, base32, hex};

pub fn sha256(data: &[u8]) -> [u8; 32] {
    Sha256::digest(data).into()
}

/// SHA-256 in hex: how a secret of 192 bits or more is kept.
pub fn digest(text: &str) -> String {
    hex(&sha256(text.as_bytes()))
}

pub fn hmac_sha256(key: &[u8], data: &[u8]) -> [u8; 32] {
    let mut mac = <Hmac<Sha256> as KeyInit>::new_from_slice(key).expect("HMAC takes a key of any length");
    mac.update(data);
    mac.finalize().into_bytes().into()
}

/// Two byte strings compared without their difference showing in the time it takes (their lengths may show).
pub fn same(a: &[u8], b: &[u8]) -> bool {
    if a.len() != b.len() {
        return false;
    }
    let mut diff = 0u8;
    for (x, y) in a.iter().zip(b) {
        diff |= x ^ y;
    }
    // (a compiler that sees through this is a compiler that sees `diff == 0` only once: the loop runs whole)
    std::hint::black_box(diff) == 0
}

/// Where random bytes come from.
pub trait Entropy {
    fn fill(&self, buf: &mut [u8]);
}

pub fn random<const N: usize>(e: &dyn Entropy) -> [u8; N] {
    let mut buf = [0u8; N];
    e.fill(&mut buf);
    buf
}

/// A new id: `<prefix>_<base32 of n random bytes>` (16 bytes: 26 characters).
pub fn new_id(e: &dyn Entropy, prefix: &str, n: usize) -> String {
    let mut buf = vec![0u8; n];
    e.fill(&mut buf);
    format!("{prefix}_{}", base32(&buf))
}

/// A new secret of 256 bits, as the text a cookie or a response carries (43 characters).
pub fn new_secret(e: &dyn Entropy) -> String {
    b64url(&random::<32>(e))
}

/// Is this the shape of a secret new_secret made?
pub fn is_secret(text: &str) -> bool {
    text.len() == 43 && text.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'-' || c == b'_')
}

/// `n` decimal digits drawn uniformly from `bytes`, four bytes a draw; a draw that would favour the low digits is
/// refused and the next one taken.  None when every draw was refused (at 8 digits a draw is refused 2.2% of the time,
/// and 32 bytes are 8 draws: one time in 2·10^13).
pub fn digits_from(bytes: &[u8], n: u32) -> Option<String> {
    assert!((1..=9).contains(&n), "1–9 digits");
    let span = 10u64.pow(n);
    let fair = (1u64 << 32) / span * span;
    for chunk in bytes.chunks_exact(4) {
        let v = u64::from(u32::from_be_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]));
        if v < fair {
            return Some(format!("{:0width$}", v % span, width = n as usize));
        }
    }
    None
}

/// Keys derived from the service's secret, one for each use (`taochronos/platform/v1/<label>`): what is made for one
/// purpose is never valid for another.
#[derive(Clone)]
pub struct Keyring {
    secret: Vec<u8>,
}

impl Keyring {
    /// None when the secret is shorter than 32 characters: a short secret is a mistake, not a choice.
    pub fn new(secret: &str) -> Option<Self> {
        let s = secret.trim();
        (s.chars().count() >= 32).then(|| Keyring { secret: s.as_bytes().to_vec() })
    }

    fn key(&self, label: &str) -> [u8; 32] {
        hmac_sha256(&self.secret, format!("taochronos/platform/v1/{label}").as_bytes())
    }

    /// HMAC-SHA256 under the label's key.
    pub fn mac(&self, label: &str, data: &[u8]) -> [u8; 32] {
        hmac_sha256(&self.key(label), data)
    }

    /// The code a flow's mail carries: 8 digits, a function of what it is for and of nothing else.  A code of one
    /// generation is not the next one's, nor another purpose's, flow's or address's.
    pub fn code(&self, purpose: &str, flow: &str, generation: i64, address: &str) -> String {
        let what = serde_json::json!([purpose, flow, generation, address]).to_string();
        digits_from(&self.mac("code", what.as_bytes()), 8)
            .or_else(|| digits_from(&self.mac("code-again", what.as_bytes()), 8))
            .unwrap_or_else(|| "00000000".into())
    }
}

#[cfg(test)]
pub mod tests {
    use super::*;
    use std::cell::Cell;

    /// Entropy for the tests: SHA-256 of a counter — different bytes each time, the same run after run.
    pub struct Counter(pub Cell<u64>);

    impl Entropy for Counter {
        fn fill(&self, buf: &mut [u8]) {
            for chunk in buf.chunks_mut(32) {
                let n = self.0.get();
                self.0.set(n + 1);
                let block = sha256(&n.to_be_bytes());
                chunk.copy_from_slice(&block[..chunk.len()]);
            }
        }
    }

    #[test]
    fn sha256_and_hmac_give_the_published_values() {
        // FIPS 180-4's "abc"; RFC 4231 test case 2
        assert_eq!(hex(&sha256(b"abc")), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
        assert_eq!(
            hex(&hmac_sha256(b"Jefe", b"what do ya want for nothing?")),
            "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843"
        );
        assert!(same(b"abc", b"abc") && !same(b"abc", b"abd") && !same(b"abc", b"abcd"));
    }

    #[test]
    fn codes_are_uniform_and_say_what_they_are_for() {
        assert_eq!(digits_from(&[0xff, 0xff, 0xff, 0xff, 0, 0, 0, 42], 8).as_deref(), Some("00000042"));
        assert_eq!(digits_from(&[0xff; 4], 8), None);
        let e = Counter(Cell::new(0));
        let mut counts = [[0u32; 10]; 8];
        for _ in 0..4000 {
            let code = digits_from(&random::<32>(&e), 8).unwrap();
            assert!(code.len() == 8 && code.bytes().all(|c| c.is_ascii_digit()));
            for (place, d) in code.bytes().enumerate() {
                counts[place][(d - b'0') as usize] += 1;
            }
        }
        for place in counts {
            for n in place {
                assert!((300..500).contains(&n), "a digit drawn {n} times in 4000");
            }
        }
        assert!(Keyring::new("short").is_none());
        let k = Keyring::new(&"k".repeat(32)).unwrap();
        let c = k.code("register", "flw_1", 1, "a@example.org");
        assert_eq!(c.len(), 8);
        assert_eq!(k.code("register", "flw_1", 1, "a@example.org"), c);
        let others = [
            k.code("signin", "flw_1", 1, "a@example.org"),
            k.code("register", "flw_2", 1, "a@example.org"),
            k.code("register", "flw_1", 2, "a@example.org"),
            k.code("register", "flw_1", 1, "b@example.org"),
            Keyring::new(&"j".repeat(32)).unwrap().code("register", "flw_1", 1, "a@example.org"),
        ];
        assert!(others.iter().all(|o| *o != c));
        assert_ne!(k.mac("code", b"x"), k.mac("network", b"x"));
    }

    #[test]
    fn ids_and_secrets() {
        let e = Counter(Cell::new(7));
        let id = new_id(&e, "org", 16);
        assert!(id.starts_with("org_") && id.len() == 30);
        assert_ne!(new_id(&e, "org", 16), id);
        let s = new_secret(&e);
        assert!(is_secret(&s));
        assert!(!is_secret("short") && !is_secret(&format!("{}!", &s[..42])));
    }
}
