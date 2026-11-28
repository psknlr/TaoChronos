//! 通行密钥 — what the console checks of a passkey: its creation (registration) and its use (an assertion), as a
//! relying party does in Web Authentication Level 3 (W3C Recommendation, 25 August 2026), §7.1 and §7.2.  The checks
//! are numbered as the spec's steps are; the client's steps, and attestation (which the service does not ask for: it
//! trusts no maker of authenticators and needs to know none), are said and skipped.
//!
//! The three algorithms every passkey provider uses: ES256 (Apple, Google, most security keys; `p256`), EdDSA
//! (Ed25519; `ed25519-dalek`, strict verification), RS256 (Windows Hello; the signature raised to the key's exponent
//! with `num-bigint`, and the whole encoded message compared with the one expected — never parsed, the way lax RSA
//! verifiers have been forged since 2006).  CBOR is read by `cbor`, strictly.  Tested with a software authenticator for
//! each algorithm, and a failing case for each check.

use serde::{Deserialize, Serialize};
use serde_json::Value as Json;

use crate::cbor::{self, Cbor};
use crate::codec::{b64url, from_b64url};
use crate::crypto::{same, sha256};

/// The check that failed, in a word the console logs and the page translates; never the credential.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct WebAuthnError(pub &'static str);

type R<T> = Result<T, WebAuthnError>;

fn fail<T>(code: &'static str) -> R<T> {
    Err(WebAuthnError(code))
}

pub const EDDSA: i64 = -8;
pub const ES256: i64 = -7;
pub const RS256: i64 = -257;
pub const ALGORITHMS: [i64; 3] = [EDDSA, ES256, RS256];

pub const UP: u8 = 0x01;
pub const UV: u8 = 0x04;
pub const BE: u8 = 0x08;
pub const BS: u8 = 0x10;
pub const AT: u8 = 0x40;
pub const ED: u8 = 0x80;

/// A credential's public key, as it is kept (JSON in a row).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "alg")]
pub enum PublicKey {
    #[serde(rename = "ES256")]
    Es256 { x: String, y: String },
    #[serde(rename = "RS256")]
    Rs256 { n: String, e: String },
    #[serde(rename = "EdDSA")]
    EdDsa { x: String },
}

impl PublicKey {
    pub fn alg(&self) -> i64 {
        match self {
            PublicKey::Es256 { .. } => ES256,
            PublicKey::Rs256 { .. } => RS256,
            PublicKey::EdDsa { .. } => EDDSA,
        }
    }
}

// ------------------------------------------------------------------ authenticator data (§6.1)
pub struct AuthData {
    pub rp_id_hash: [u8; 32],
    pub flags: u8,
    pub sign_count: u32,
    pub aaguid: Option<[u8; 16]>,
    pub credential_id: Option<Vec<u8>>,
    pub cose: Option<Cbor>,
}

pub fn parse_auth_data(data: &[u8]) -> R<AuthData> {
    if data.len() < 37 {
        return fail("authdata");
    }
    let mut rp_id_hash = [0u8; 32];
    rp_id_hash.copy_from_slice(&data[..32]);
    let flags = data[32];
    let sign_count = u32::from_be_bytes([data[33], data[34], data[35], data[36]]);
    let mut out = AuthData { rp_id_hash, flags, sign_count, aaguid: None, credential_id: None, cose: None };
    let mut p = 37;
    if flags & AT != 0 {
        let head = data.get(p..p + 18).ok_or(WebAuthnError("authdata"))?;
        let mut aaguid = [0u8; 16];
        aaguid.copy_from_slice(&head[..16]);
        let id_len = usize::from(u16::from_be_bytes([head[16], head[17]]));
        p += 18;
        // §7.1 step 26: at most 1023 bytes (and 16 at least: no authenticator makes a shorter one)
        if !(16..=1023).contains(&id_len) {
            return fail("authdata");
        }
        let id = data.get(p..p + id_len).ok_or(WebAuthnError("authdata"))?;
        out.aaguid = Some(aaguid);
        out.credential_id = Some(id.to_vec());
        p += id_len;
        let (key, next) = cbor::read(data, p).map_err(|_| WebAuthnError("authdata"))?;
        if !matches!(key, Cbor::Map(_)) {
            return fail("authdata");
        }
        out.cose = Some(key);
        p = next;
    }
    if flags & ED != 0 {
        let (ext, next) = cbor::read(data, p).map_err(|_| WebAuthnError("authdata"))?;
        if !matches!(ext, Cbor::Map(_)) {
            return fail("authdata");
        }
        p = next;
    }
    if p != data.len() {
        return fail("authdata"); // nothing unaccounted for
    }
    Ok(out)
}

// ------------------------------------------------------------------ the credential's public key (COSE, RFC 9053)
/// The COSE key as it is kept: only the three algorithms offered, each with exactly the parameters it needs.
pub fn cose_to_key(cose: &Cbor, allowed: &[i64]) -> R<PublicKey> {
    let kty = cose.int_key(1).and_then(Cbor::as_int);
    let alg = cose.int_key(3).and_then(Cbor::as_int).ok_or(WebAuthnError("alg"))?;
    if !allowed.contains(&alg) {
        return fail("alg");
    }
    let bytes = |label: i64, size: Option<usize>| -> R<Vec<u8>> {
        match cose.int_key(label).and_then(Cbor::as_bytes) {
            Some(b) if size.is_none_or(|s| b.len() == s) => Ok(b.to_vec()),
            _ => fail("key"),
        }
    };
    let key = match alg {
        ES256 if kty == Some(2) && cose.int_key(-1).and_then(Cbor::as_int) == Some(1) => {
            PublicKey::Es256 { x: b64url(&bytes(-2, Some(32))?), y: b64url(&bytes(-3, Some(32))?) }
        }
        RS256 if kty == Some(3) => {
            let n = bytes(-1, None)?;
            let e = bytes(-2, None)?;
            // 2048–4096 bits, minimal; the exponent 65537 alone — every authenticator uses it, and a key of exponent 1 is a key
            // whose every message is its own signature
            if !(256..=512).contains(&n.len()) || n[0] == 0 || e != [1, 0, 1] {
                return fail("key");
            }
            PublicKey::Rs256 { n: b64url(&n), e: b64url(&e) }
        }
        EDDSA if kty == Some(1) && cose.int_key(-1).and_then(Cbor::as_int) == Some(6) => {
            PublicKey::EdDsa { x: b64url(&bytes(-2, Some(32))?) }
        }
        _ => return fail("key"),
    };
    check_key(&key)?; // a key the verifier takes, now — not at the first sign-in
    Ok(key)
}

fn decoded(s: &str) -> R<Vec<u8>> {
    from_b64url(s).ok_or(WebAuthnError("key"))
}

fn es256_key(x: &str, y: &str) -> R<p256::ecdsa::VerifyingKey> {
    let mut sec1 = vec![0x04];
    sec1.extend(decoded(x)?);
    sec1.extend(decoded(y)?);
    p256::ecdsa::VerifyingKey::from_sec1_bytes(&sec1).map_err(|_| WebAuthnError("key")) // a point on the curve, or none
}

fn eddsa_key(x: &str) -> R<ed25519_dalek::VerifyingKey> {
    let raw: [u8; 32] = decoded(x)?.try_into().map_err(|_| WebAuthnError("key"))?;
    ed25519_dalek::VerifyingKey::from_bytes(&raw).map_err(|_| WebAuthnError("key"))
}

fn check_key(key: &PublicKey) -> R<()> {
    match key {
        PublicKey::Es256 { x, y } => es256_key(x, y).map(|_| ()),
        PublicKey::EdDsa { x } => eddsa_key(x).map(|_| ()),
        PublicKey::Rs256 { n, e } => decoded(n).and(decoded(e)).map(|_| ()),
    }
}

/// SHA-256's DigestInfo, as PKCS #1 v1.5 prefixes the hash it signs (RFC 8017, §9.2 note 1).
const SHA256_INFO: [u8; 19] =
    [0x30, 0x31, 0x30, 0x0d, 0x06, 0x09, 0x60, 0x86, 0x48, 0x01, 0x65, 0x03, 0x04, 0x02, 0x01, 0x05, 0x00, 0x04, 0x20];

/// The encoded message RSASSA-PKCS1-v1_5 signs for `data` with a modulus of `k` bytes.
pub fn pkcs1_message(data: &[u8], k: usize) -> Vec<u8> {
    let mut em = vec![0x00, 0x01];
    em.resize(k - SHA256_INFO.len() - 32 - 1, 0xff);
    em.push(0x00);
    em.extend(SHA256_INFO);
    em.extend(sha256(data));
    em
}

/// RSASSA-PKCS1-v1_5 with SHA-256 (RFC 8017 §8.2.2): s^e mod n, compared whole with the message expected.
fn rs256_verify(n: &[u8], e: &[u8], sig: &[u8], data: &[u8]) -> bool {
    use num_bigint::BigUint;
    let k = n.len();
    if sig.len() != k {
        return false;
    }
    let modulus = BigUint::from_bytes_be(n);
    let s = BigUint::from_bytes_be(sig);
    if s >= modulus {
        return false;
    }
    let m = s.modpow(&BigUint::from_bytes_be(e), &modulus).to_bytes_be();
    if m.len() > k {
        return false;
    }
    let mut em = vec![0u8; k - m.len()];
    em.extend(m);
    same(&em, &pkcs1_message(data, k))
}

/// The signature an authenticator made over `data` (authenticator data ‖ hash of the client data).
pub fn verify_signature(key: &PublicKey, signature: &[u8], data: &[u8]) -> R<()> {
    let ok = match key {
        PublicKey::Es256 { x, y } => {
            use p256::ecdsa::signature::Verifier;
            let Ok(sig) = p256::ecdsa::Signature::from_der(signature) else { return fail("signature") };
            es256_key(x, y)?.verify(data, &sig).is_ok() // a high s is taken: WebAuthn asks for none other
        }
        PublicKey::EdDsa { x } => {
            let Ok(sig) = ed25519_dalek::Signature::from_slice(signature) else { return fail("signature") };
            eddsa_key(x)?.verify_strict(data, &sig).is_ok()
        }
        PublicKey::Rs256 { n, e } => rs256_verify(&decoded(n)?, &decoded(e)?, signature, data),
    };
    if ok { Ok(()) } else { fail("signature") }
}

// ------------------------------------------------------------------ the ceremonies
pub struct Expected<'a> {
    /// the challenge this ceremony was given, base64url
    pub challenge: &'a str,
    pub origins: &'a [String],
    pub rp_id: &'a str,
    pub require_uv: bool,
}

fn b64_field(v: Option<&Json>, code: &'static str, most: usize) -> R<Vec<u8>> {
    let s = v.and_then(Json::as_str).ok_or(WebAuthnError(code))?;
    if s.len() > most * 4 / 3 + 4 {
        return fail(code);
    }
    match from_b64url(s) {
        Some(b) if !b.is_empty() => Ok(b),
        _ => fail(code),
    }
}

/// The client data (§5.8.1) of a ceremony, checked: its type, its challenge, its origin, and that it was not made in
/// a frame of another site.
fn client_data(raw: &[u8], ty: &str, want: &Expected) -> R<()> {
    let c: Json =
        std::str::from_utf8(raw).ok().and_then(|t| serde_json::from_str(t).ok()).ok_or(WebAuthnError("client_data"))?; // 5–6
    if c.get("type").and_then(Json::as_str) != Some(ty) {
        return fail("type"); // §7.1 step 7 · §7.2 step 11
    }
    if c.get("challenge").and_then(Json::as_str) != Some(want.challenge) {
        return fail("challenge"); // 8 · 12
    }
    match c.get("origin").and_then(Json::as_str) {
        Some(o) if want.origins.iter().any(|w| w == o) => {}
        _ => return fail("origin"), // 9 · 13
    }
    // 10 · 14: a ceremony in a frame of another site is none the service asked for
    if c.get("crossOrigin").and_then(Json::as_bool) == Some(true) || c.get("topOrigin").is_some() {
        return fail("cross_origin");
    }
    Ok(())
}

/// The challenge a ceremony's client data names, read before anything is verified: what the caller looks up (and
/// takes, once) first.  None when there is none to read.
pub fn challenge_of(credential: &Json) -> Option<String> {
    let raw = from_b64url(credential.pointer("/response/clientDataJSON")?.as_str()?)?;
    if raw.len() > 4096 {
        return None;
    }
    let c: Json = serde_json::from_slice(&raw).ok()?;
    let ch = c.get("challenge")?.as_str()?;
    (16..=128)
        .contains(&ch.len())
        .then(|| ch.to_string())
        .filter(|s| s.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_'))
}

/// The raw id of the credential the page names, checked against its text form.
fn credential_id(credential: &Json) -> R<Vec<u8>> {
    if credential.get("type").and_then(Json::as_str) != Some("public-key") {
        return fail("credential");
    }
    let raw = b64_field(credential.get("rawId").or_else(|| credential.get("id")), "credential", 1023)?;
    if let Some(id) = credential.get("id")
        && id.as_str() != Some(b64url(&raw).as_str())
    {
        return fail("credential");
    }
    Ok(raw)
}

/// The id a page's credential names (base64url), or None: what the caller looks the stored credential up by.
pub fn id_of(credential: &Json) -> Option<String> {
    credential_id(credential).ok().map(|raw| b64url(&raw))
}

fn uuid(b: &[u8; 16]) -> String {
    let h = crate::codec::hex(b);
    format!("{}-{}-{}-{}-{}", &h[..8], &h[8..12], &h[12..16], &h[16..20], &h[20..])
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Registered {
    pub credential_id: String,
    pub key: PublicKey,
    pub sign_count: u32,
    pub aaguid: String,
    pub backup_eligible: bool,
    pub backup_state: bool,
    pub uv: bool,
    pub transports: Vec<String>,
}

const TRANSPORTS: [&str; 7] = ["ble", "cable", "hybrid", "internal", "nfc", "smart-card", "usb"];

/// §7.1 Registering a new credential.  `credential` is PublicKeyCredential.toJSON() as the page sent it.  Whether the
/// id is already registered (step 27) is the caller's to check, in the step in which it keeps it.
pub fn verify_registration(credential: &Json, want: &Expected) -> R<Registered> {
    let raw_id = credential_id(credential)?;
    let response = credential.get("response").filter(|r| r.is_object()).ok_or(WebAuthnError("credential"))?; // 3
    // 4. client extension outputs: none were asked for, and nothing is read from them
    let cdj = b64_field(response.get("clientDataJSON"), "client_data", 4096)?;
    client_data(&cdj, "webauthn.create", want)?; // 5–10
    // 11. the client data's hash is what attestation signs: no attestation is verified (22–25)
    let att = cbor::decode(&b64_field(response.get("attestationObject"), "attestation", 16384)?)
        .map_err(|_| WebAuthnError("cbor"))?; // 12
    let (Some(Cbor::Text(_)), Some(Cbor::Bytes(auth_data)), Some(Cbor::Map(_))) =
        (att.text_key("fmt"), att.text_key("authData"), att.text_key("attStmt"))
    else {
        return fail("attestation");
    };
    let auth = parse_auth_data(auth_data)?;
    if auth.rp_id_hash != sha256(want.rp_id.as_bytes()) {
        return fail("rp"); // 13
    }
    if auth.flags & UP == 0 {
        return fail("up"); // 14
    }
    if want.require_uv && auth.flags & UV == 0 {
        return fail("uv"); // 15
    }
    if auth.flags & BE == 0 && auth.flags & BS != 0 {
        return fail("flags"); // 16; 17–18: kept, and shown to the person
    }
    let (Some(id), Some(cose), Some(aaguid)) = (&auth.credential_id, &auth.cose, &auth.aaguid) else {
        return fail("authdata"); // 19
    };
    let key = cose_to_key(cose, &ALGORITHMS)?; // 20
    // 21. extensions: none asked for (parse_auth_data read past any)
    // 22–25. the attestation statement: "none" is asked for and no statement is trusted, whatever the format
    if *id != raw_id {
        return fail("credential"); // the id the page names is the one created
    }
    let transports = response
        .get("transports")
        .and_then(Json::as_array)
        .map(|a| {
            let mut t: Vec<String> =
                a.iter().filter_map(Json::as_str).filter(|s| TRANSPORTS.contains(s)).map(String::from).collect();
            t.dedup();
            t.truncate(7);
            t
        })
        .unwrap_or_default();
    Ok(Registered {
        credential_id: b64url(&raw_id),
        key,
        sign_count: auth.sign_count,
        aaguid: uuid(aaguid),
        backup_eligible: auth.flags & BE != 0,
        backup_state: auth.flags & BS != 0,
        uv: auth.flags & UV != 0,
        transports,
    })
}

pub struct Stored<'a> {
    pub key: &'a PublicKey,
    pub sign_count: u32,
    pub backup_eligible: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Asserted {
    pub credential_id: String,
    pub user_handle: Option<String>,
    pub sign_count: u32,
    pub backup_state: bool,
    pub uv: bool,
}

/// §7.2 Verifying an authentication assertion.  The caller has found the stored credential by the id the page names
/// (`id_of`) and, where the ceremony is for one person, checked that it is theirs (steps 5–7).
pub fn verify_assertion(credential: &Json, want: &Expected, stored: &Stored) -> R<Asserted> {
    let raw_id = credential_id(credential)?;
    let response = credential.get("response").filter(|r| r.is_object()).ok_or(WebAuthnError("credential"))?; // 3
    let cdj = b64_field(response.get("clientDataJSON"), "client_data", 4096)?;
    let auth_data = b64_field(response.get("authenticatorData"), "authdata", 4096)?;
    let signature = b64_field(response.get("signature"), "signature", 1024)?;
    let user_handle = match response.get("userHandle") {
        None | Some(Json::Null) => None,
        Some(Json::String(s)) if s.is_empty() => None,
        h => Some(b64url(&b64_field(h, "user", 64)?)),
    };
    client_data(&cdj, "webauthn.get", want)?; // 9–14
    let auth = parse_auth_data(&auth_data)?;
    if auth.flags & AT != 0 {
        return fail("authdata"); // an assertion carries no new credential
    }
    if auth.rp_id_hash != sha256(want.rp_id.as_bytes()) {
        return fail("rp"); // 15
    }
    if auth.flags & UP == 0 {
        return fail("up"); // 16
    }
    if want.require_uv && auth.flags & UV == 0 {
        return fail("uv"); // 17
    }
    if auth.flags & BE == 0 && auth.flags & BS != 0 {
        return fail("flags"); // 18
    }
    if (auth.flags & BE != 0) != stored.backup_eligible {
        return fail("flags"); // eligibility for backup never changes for a credential
    }
    // 19–20. extensions: none asked for
    let mut signed = auth_data.clone();
    signed.extend(sha256(&cdj)); // 21
    verify_signature(stored.key, &signature, &signed)?; // 22
    // 23. the counter: once either side counts, it must go up — or the credential was copied, and the copy (or the
    // original) is refused.  Passkeys that sync count nothing (0 and 0) and are not judged by it
    if (auth.sign_count != 0 || stored.sign_count != 0) && auth.sign_count <= stored.sign_count {
        return fail("counter");
    }
    Ok(Asserted {
        credential_id: b64url(&raw_id),
        user_handle,
        sign_count: auth.sign_count,
        backup_state: auth.flags & BS != 0,
        uv: auth.flags & UV != 0,
    })
}

#[cfg(test)]
pub mod tests {
    //! A software authenticator for each algorithm: credentials and assertions as a platform authenticator or a
    //! security key makes them, and each check failed by changing the one thing it checks.
    use super::*;
    use crate::cbor::encode;
    use crate::crypto::tests::Counter;
    use crate::crypto::{Entropy, random};
    use serde_json::json;
    use std::cell::Cell;

    // a test key, used for nothing else: RSA-2048, e = 65537
    include!("webauthn_test_rsa.rs");

    fn hex_bytes(parts: &[&str]) -> Vec<u8> {
        let h: String = parts.concat();
        let h = if h.len() % 2 == 1 { format!("0{h}") } else { h }; // a leading zero nibble the dump left out
        (0..h.len()).step_by(2).map(|i| u8::from_str_radix(&h[i..i + 2], 16).unwrap()).collect()
    }

    pub enum Signer {
        Es256(p256::ecdsa::SigningKey),
        Ed(ed25519_dalek::SigningKey),
        Rsa { n: Vec<u8>, d: Vec<u8> },
    }

    pub struct Authenticator {
        pub signer: Signer,
        pub id: Vec<u8>,
        pub user: Vec<u8>,
        pub counter: Cell<u32>,
        pub rp_id: String,
        pub origin: String,
        pub backup_eligible: bool,
    }

    /// What a test changes of what a real authenticator would send.
    #[derive(Default, Clone)]
    pub struct Twist {
        pub ty: Option<&'static str>,
        pub challenge: Option<String>,
        pub origin: Option<&'static str>,
        pub cross_origin: bool,
        pub top_origin: bool,
        pub rp_id: Option<&'static str>,
        pub no_up: bool,
        pub no_uv: bool,
        pub be: Option<bool>,
        pub bs: bool,
        pub no_at: bool,
        pub at: bool,
        pub raw_id: Option<Vec<u8>>,
        pub cose: Option<Vec<u8>>,
        pub trailing: bool,
        pub fmt: Option<&'static str>,
        pub counter: Option<u32>,
        pub user_handle: Option<Option<String>>,
        pub sign_other: bool,
    }

    impl Authenticator {
        pub fn new(alg: i64, e: &dyn Entropy) -> Authenticator {
            let signer = match alg {
                ES256 => Signer::Es256(p256::ecdsa::SigningKey::from_slice(&random::<32>(e)).unwrap()),
                EDDSA => Signer::Ed(ed25519_dalek::SigningKey::from_bytes(&random::<32>(e))),
                _ => Signer::Rsa { n: hex_bytes(TEST_N), d: hex_bytes(TEST_D) },
            };
            Authenticator {
                signer,
                id: random::<32>(e).to_vec(),
                user: random::<16>(e).to_vec(),
                counter: Cell::new(0),
                rp_id: "impf.ai".into(),
                origin: "https://console.impf.ai".into(),
                backup_eligible: true,
            }
        }

        pub fn counting(mut self, from: u32) -> Self {
            self.counter = Cell::new(from);
            self
        }

        pub fn id(&self) -> String {
            b64url(&self.id)
        }

        pub fn handle(&self) -> String {
            b64url(&self.user)
        }

        fn cose(&self) -> Vec<u8> {
            let i = |n: i64| Cbor::Int(n);
            encode(&match &self.signer {
                Signer::Es256(k) => {
                    let p = k.verifying_key().to_sec1_point(false);
                    let b = p.as_bytes();
                    Cbor::Map(vec![
                        (i(1), i(2)),
                        (i(3), i(ES256)),
                        (i(-1), i(1)),
                        (i(-2), Cbor::Bytes(b[1..33].to_vec())),
                        (i(-3), Cbor::Bytes(b[33..].to_vec())),
                    ])
                }
                Signer::Ed(k) => Cbor::Map(vec![
                    (i(1), i(1)),
                    (i(3), i(EDDSA)),
                    (i(-1), i(6)),
                    (i(-2), Cbor::Bytes(k.verifying_key().to_bytes().to_vec())),
                ]),
                Signer::Rsa { n, .. } => Cbor::Map(vec![
                    (i(1), i(3)),
                    (i(3), i(RS256)),
                    (i(-1), Cbor::Bytes(n.clone())),
                    (i(-2), Cbor::Bytes(vec![1, 0, 1])),
                ]),
            })
        }

        pub fn sign(&self, data: &[u8]) -> Vec<u8> {
            match &self.signer {
                Signer::Es256(k) => {
                    use p256::ecdsa::signature::Signer as _;
                    let s: p256::ecdsa::Signature = k.sign(data);
                    s.to_der().as_bytes().to_vec()
                }
                Signer::Ed(k) => {
                    use ed25519_dalek::Signer as _;
                    k.sign(data).to_bytes().to_vec()
                }
                Signer::Rsa { n, d } => {
                    use num_bigint::BigUint;
                    let em = BigUint::from_bytes_be(&pkcs1_message(data, n.len()));
                    let s = em.modpow(&BigUint::from_bytes_be(d), &BigUint::from_bytes_be(n)).to_bytes_be();
                    let mut out = vec![0u8; n.len() - s.len()];
                    out.extend(s);
                    out
                }
            }
        }

        fn client(&self, ty: &str, challenge: &str, t: &Twist) -> Vec<u8> {
            let mut c = json!({ "type": t.ty.unwrap_or(ty), "challenge": t.challenge.as_deref().unwrap_or(challenge),
                "origin": t.origin.unwrap_or(&self.origin), "crossOrigin": t.cross_origin });
            if t.top_origin {
                c["topOrigin"] = json!("https://evil.example");
            }
            c.to_string().into_bytes()
        }

        fn flags(&self, t: &Twist) -> u8 {
            (if t.no_up { 0 } else { UP })
                | (if t.no_uv { 0 } else { UV })
                | (if t.be.unwrap_or(self.backup_eligible) { BE } else { 0 })
                | (if t.bs { BS } else { 0 })
        }

        pub fn create(&self, challenge: &str, t: &Twist) -> Json {
            let mut auth = sha256(t.rp_id.unwrap_or(&self.rp_id).as_bytes()).to_vec();
            auth.push(self.flags(t) | if t.no_at { 0 } else { AT });
            auth.extend(self.counter.get().to_be_bytes());
            if !t.no_at {
                auth.extend([0u8; 16]);
                auth.extend((self.id.len() as u16).to_be_bytes());
                auth.extend(&self.id);
                auth.extend(t.cose.clone().unwrap_or_else(|| self.cose()));
            }
            if t.trailing {
                auth.push(0);
            }
            let att = encode(&Cbor::Map(vec![
                (Cbor::Text("fmt".into()), Cbor::Text(t.fmt.unwrap_or("none").into())),
                (Cbor::Text("attStmt".into()), Cbor::Map(vec![])),
                (Cbor::Text("authData".into()), Cbor::Bytes(auth)),
            ]));
            let raw = t.raw_id.clone().unwrap_or_else(|| self.id.clone());
            json!({ "id": b64url(&raw), "rawId": b64url(&raw), "type": "public-key",
                "response": { "clientDataJSON": b64url(&self.client("webauthn.create", challenge, t)), "attestationObject": b64url(&att),
                    "transports": ["internal", "hybrid", "carrier-pigeon"] }, "clientExtensionResults": {} })
        }

        pub fn get(&self, challenge: &str, t: &Twist) -> Json {
            if self.counter.get() > 0 {
                self.counter.set(self.counter.get() + 1);
            }
            let mut auth = sha256(t.rp_id.unwrap_or(&self.rp_id).as_bytes()).to_vec();
            auth.push(self.flags(t) | if t.at { AT } else { 0 });
            auth.extend(t.counter.unwrap_or(self.counter.get()).to_be_bytes());
            let cdj = self.client("webauthn.get", challenge, t);
            let mut signed = if t.sign_other { vec![0u8; 37] } else { auth.clone() };
            signed.extend(sha256(&cdj));
            let handle = match &t.user_handle {
                Some(h) => h.clone(),
                None => Some(self.handle()),
            };
            json!({ "id": self.id(), "rawId": self.id(), "type": "public-key",
                "response": { "clientDataJSON": b64url(&cdj), "authenticatorData": b64url(&auth), "signature": b64url(&self.sign(&signed)),
                    "userHandle": handle }, "clientExtensionResults": {} })
        }
    }

    fn a_rsa_cose() -> Vec<u8> {
        let i = |n: i64| Cbor::Int(n);
        encode(&Cbor::Map(vec![
            (i(1), i(3)),
            (i(3), i(RS256)),
            (i(-1), Cbor::Bytes(hex_bytes(TEST_N))),
            (i(-2), Cbor::Bytes(vec![1, 0, 1])),
        ]))
    }

    pub fn origins() -> Vec<String> {
        vec!["https://console.impf.ai".to_string()]
    }

    fn want<'a>(challenge: &'a str, origins: &'a [String]) -> Expected<'a> {
        Expected { challenge, origins, rp_id: "impf.ai", require_uv: true }
    }

    fn challenge(e: &dyn Entropy) -> String {
        b64url(&random::<32>(e))
    }

    #[test]
    fn each_algorithm_makes_a_passkey_and_signs_in_with_it() {
        let e = Counter(Cell::new(1 << 50));
        let o = origins();
        for alg in ALGORITHMS {
            let a = Authenticator::new(alg, &e);
            let c = challenge(&e);
            let reg = verify_registration(&a.create(&c, &Twist::default()), &want(&c, &o)).unwrap();
            assert_eq!(
                (reg.credential_id.clone(), reg.key.alg(), reg.sign_count, reg.uv, reg.backup_eligible),
                (a.id(), alg, 0, true, true)
            );
            assert_eq!(reg.transports, vec!["internal", "hybrid"], "an unknown transport is dropped");
            assert_eq!(reg.aaguid, "00000000-0000-0000-0000-000000000000");
            // kept as JSON in a row, and read back
            let kept: PublicKey = serde_json::from_str(&serde_json::to_string(&reg.key).unwrap()).unwrap();
            let c2 = challenge(&e);
            let out = verify_assertion(
                &a.get(&c2, &Twist::default()),
                &want(&c2, &o),
                &Stored { key: &kept, sign_count: 0, backup_eligible: true },
            )
            .unwrap();
            assert_eq!((out.credential_id, out.user_handle), (a.id(), Some(a.handle())));
        }
    }

    #[test]
    fn registration_refuses_what_each_check_is_there_to_refuse() {
        let e = Counter(Cell::new(2 << 50));
        let o = origins();
        let a = Authenticator::new(ES256, &e);
        let c = challenge(&e);
        let check = |t: Twist, code: &str| {
            assert_eq!(
                verify_registration(&a.create(&c, &t), &want(&c, &o)).err(),
                Some(WebAuthnError(Box::leak(code.to_string().into_boxed_str()))),
                "{code}"
            );
        };
        check(Twist { ty: Some("webauthn.get"), ..Default::default() }, "type");
        check(Twist { challenge: Some(challenge(&e)), ..Default::default() }, "challenge");
        check(Twist { origin: Some("https://chat.impf.ai"), ..Default::default() }, "origin");
        check(Twist { origin: Some("https://console.impf.ai.evil.example"), ..Default::default() }, "origin");
        check(Twist { cross_origin: true, ..Default::default() }, "cross_origin");
        check(Twist { top_origin: true, ..Default::default() }, "cross_origin");
        check(Twist { rp_id: Some("evil.example"), ..Default::default() }, "rp");
        check(Twist { no_up: true, ..Default::default() }, "up");
        check(Twist { no_uv: true, ..Default::default() }, "uv");
        check(Twist { be: Some(false), bs: true, ..Default::default() }, "flags");
        check(Twist { no_at: true, ..Default::default() }, "authdata");
        check(Twist { raw_id: Some(vec![7; 32]), ..Default::default() }, "credential");
        check(Twist { trailing: true, ..Default::default() }, "authdata");
        let i = |n: i64| Cbor::Int(n);
        check(
            Twist {
                cose: Some(encode(&Cbor::Map(vec![
                    (i(1), i(2)),
                    (i(3), i(-35)),
                    (i(-1), i(2)),
                    (i(-2), Cbor::Bytes(vec![0; 48])),
                    (i(-3), Cbor::Bytes(vec![0; 48])),
                ]))),
                ..Default::default()
            },
            "alg",
        );
        check(
            Twist {
                cose: Some(encode(&Cbor::Map(vec![
                    (i(1), i(2)),
                    (i(3), i(-7)),
                    (i(-1), i(1)),
                    (i(-2), Cbor::Bytes(vec![0; 31])),
                    (i(-3), Cbor::Bytes(vec![0; 32])),
                ]))),
                ..Default::default()
            },
            "key",
        );
        check(
            Twist {
                cose: Some(encode(&Cbor::Map(vec![
                    (i(1), i(2)),
                    (i(3), i(-7)),
                    (i(-1), i(1)),
                    (i(-2), Cbor::Bytes(vec![1; 32])),
                    (i(-3), Cbor::Bytes(vec![2; 32])),
                ]))),
                ..Default::default()
            },
            "key",
        );
        // an RSA key of another exponent than 65537 (1 would make every message its own signature): refused
        let n = cbor::decode(&a_rsa_cose()).unwrap().int_key(-1).cloned().unwrap();
        for e in [vec![1u8], vec![3u8], vec![1, 0, 0, 1]] {
            let cose =
                encode(&Cbor::Map(vec![(i(1), i(3)), (i(3), i(RS256)), (i(-1), n.clone()), (i(-2), Cbor::Bytes(e))]));
            check(Twist { cose: Some(cose), ..Default::default() }, "key");
        }
        // without user verification asked for, a credential made without it is taken (and said to be)
        let loose = verify_registration(
            &a.create(&c, &Twist { no_uv: true, ..Default::default() }),
            &Expected { require_uv: false, ..want(&c, &o) },
        )
        .unwrap();
        assert!(!loose.uv);
        // a format other than "none" is not trusted, and not refused (§7.1 steps 22–25)
        assert!(
            verify_registration(&a.create(&c, &Twist { fmt: Some("packed"), ..Default::default() }), &want(&c, &o))
                .is_ok()
        );
    }

    #[test]
    fn an_assertion_refuses_what_each_check_is_there_to_refuse() {
        let e = Counter(Cell::new(3 << 50));
        let o = origins();
        for alg in ALGORITHMS {
            let a = Authenticator::new(alg, &e).counting(5);
            let c0 = challenge(&e);
            let reg = verify_registration(&a.create(&c0, &Twist::default()), &want(&c0, &o)).unwrap();
            let stored = Stored { key: &reg.key, sign_count: reg.sign_count, backup_eligible: reg.backup_eligible };
            let c = challenge(&e);
            let check = |t: Twist, code: &'static str| {
                assert_eq!(
                    verify_assertion(&a.get(&c, &t), &want(&c, &o), &stored).err(),
                    Some(WebAuthnError(code)),
                    "{alg} {code}"
                );
            };
            check(Twist { ty: Some("webauthn.create"), ..Default::default() }, "type");
            check(Twist { challenge: Some(challenge(&e)), ..Default::default() }, "challenge");
            check(Twist { origin: Some("http://console.impf.ai"), ..Default::default() }, "origin");
            check(Twist { rp_id: Some("console.impf.ai"), ..Default::default() }, "rp");
            check(Twist { no_up: true, ..Default::default() }, "up");
            check(Twist { no_uv: true, ..Default::default() }, "uv");
            check(Twist { be: Some(false), ..Default::default() }, "flags");
            check(Twist { at: true, ..Default::default() }, "authdata");
            check(Twist { sign_other: true, ..Default::default() }, "signature");
            check(Twist { counter: Some(5), ..Default::default() }, "counter");
            check(Twist { counter: Some(3), ..Default::default() }, "counter");
            let ok = verify_assertion(&a.get(&c, &Twist::default()), &want(&c, &o), &stored).unwrap();
            assert!(ok.sign_count > 5);
            // signed by another key of the same algorithm
            let other = Authenticator::new(alg, &e);
            let mut theirs = a.get(&c, &Twist::default());
            theirs["response"]["signature"] = other.get(&c, &Twist::default())["response"]["signature"].clone();
            if alg != RS256 {
                assert_eq!(verify_assertion(&theirs, &want(&c, &o), &stored).err(), Some(WebAuthnError("signature")));
            }
        }
    }

    #[test]
    fn signatures_and_handles_at_their_edges() {
        let e = Counter(Cell::new(4 << 50));
        let o = origins();
        let a = Authenticator::new(ES256, &e);
        let c0 = challenge(&e);
        let reg = verify_registration(&a.create(&c0, &Twist::default()), &want(&c0, &o)).unwrap();
        let stored = Stored { key: &reg.key, sign_count: 0, backup_eligible: true };
        // a high s (n − s) is a valid ECDSA signature: authenticators make them and WebAuthn takes them
        let c = challenge(&e);
        let mut cred = a.get(&c, &Twist::default());
        let der = from_b64url(cred["response"]["signature"].as_str().unwrap()).unwrap();
        let sig = p256::ecdsa::Signature::from_der(&der).unwrap();
        let low = sig.normalize_s();
        let high = p256::ecdsa::Signature::from_scalars(low.r(), -low.s()).unwrap();
        assert_ne!(low, high);
        for form in [low, high] {
            cred["response"]["signature"] = json!(b64url(form.to_der().as_bytes()));
            assert!(verify_assertion(&cred, &want(&c, &o), &stored).is_ok(), "both s and n − s verify");
        }
        // a signature in raw r ‖ s is not an authenticator's DER
        let mut raw = a.get(&c, &Twist::default());
        raw["response"]["signature"] = json!(b64url(&sig.to_bytes()));
        assert_eq!(verify_assertion(&raw, &want(&c, &o), &stored).err(), Some(WebAuthnError("signature")));
        // no user handle (a credential that is not discoverable) is None
        let none = verify_assertion(
            &a.get(&c, &Twist { user_handle: Some(None), ..Default::default() }),
            &want(&c, &o),
            &stored,
        )
        .unwrap();
        assert_eq!(none.user_handle, None);
        // what is read before verifying: the challenge and the id, or None — never a panic
        assert_eq!(challenge_of(&cred).as_deref(), Some(c.as_str()));
        assert_eq!(id_of(&cred), Some(a.id()));
        for junk in [json!(null), json!({}), json!({"response": {}}), json!({"response": {"clientDataJSON": "!!"}})] {
            assert_eq!(challenge_of(&junk), None);
        }
        assert_eq!(id_of(&json!({"type": "public-key", "id": "abc", "rawId": "abd"})), None);
        assert_eq!(id_of(&json!({"type": "password", "id": a.id()})), None);
        // RSA: a signature one bit off, or as long as the modulus plus one byte
        let r = Authenticator::new(RS256, &e);
        let rk = verify_registration(&r.create(&c0, &Twist::default()), &want(&c0, &o)).unwrap();
        let mut bad = r.get(&c, &Twist::default());
        let mut s = from_b64url(bad["response"]["signature"].as_str().unwrap()).unwrap();
        s[100] ^= 1;
        bad["response"]["signature"] = json!(b64url(&s));
        assert_eq!(
            verify_assertion(&bad, &want(&c, &o), &Stored { key: &rk.key, sign_count: 0, backup_eligible: true }).err(),
            Some(WebAuthnError("signature"))
        );
        s.push(0);
        bad["response"]["signature"] = json!(b64url(&s));
        assert_eq!(
            verify_assertion(&bad, &want(&c, &o), &Stored { key: &rk.key, sign_count: 0, backup_eligible: true }).err(),
            Some(WebAuthnError("signature"))
        );
        let _ = e.0.get();
        let _: &dyn Entropy = &e;
    }
}
