//! The encodings the platform writes: base64url (unpadded, as WebAuthn and JWK write it), Crockford's base32 in lower
//! case (ids and keys: no i, l, o or u, so nothing is misread when retyped), hex (digests), CRC-32 (an API key's
//! checksum: a typo is told from a wrong key before anything is looked up).

const B64: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";

/// base64url without padding.
pub fn b64url(bytes: &[u8]) -> String {
    let mut out = String::with_capacity(bytes.len().div_ceil(3) * 4);
    for chunk in bytes.chunks(3) {
        let n = (u32::from(chunk[0]) << 16)
            | (u32::from(*chunk.get(1).unwrap_or(&0)) << 8)
            | u32::from(*chunk.get(2).unwrap_or(&0));
        let chars = chunk.len() + 1;
        for i in 0..chars {
            out.push(B64[((n >> (18 - 6 * i)) & 63) as usize] as char);
        }
    }
    out
}

fn b64_value(c: u8) -> Option<u32> {
    match c {
        b'A'..=b'Z' => Some(u32::from(c - b'A')),
        b'a'..=b'z' => Some(u32::from(c - b'a') + 26),
        b'0'..=b'9' => Some(u32::from(c - b'0') + 52),
        b'-' => Some(62),
        b'_' => Some(63),
        _ => None,
    }
}

/// The bytes of a base64url text, or None: not base64url, padded, or not the one text these bytes have (its last
/// character's unused bits set: "abd" decodes to the bytes of "abc", and two texts of one credential would be two
/// keys of a table).
pub fn from_b64url(text: &str) -> Option<Vec<u8>> {
    let bytes = text.as_bytes();
    if bytes.len() % 4 == 1 {
        return None;
    }
    let mut out = Vec::with_capacity(bytes.len() * 3 / 4);
    for chunk in bytes.chunks(4) {
        let mut n = 0u32;
        for (i, &c) in chunk.iter().enumerate() {
            n |= b64_value(c)? << (18 - 6 * i);
        }
        let take = chunk.len() - 1;
        let unused = match chunk.len() {
            2 => n & 0xffff,
            3 => n & 0xff,
            _ => 0,
        };
        if unused != 0 {
            return None;
        }
        for i in 0..take {
            out.push((n >> (16 - 8 * i)) as u8);
        }
    }
    Some(out)
}

pub const BASE32: &[u8; 32] = b"0123456789abcdefghjkmnpqrstvwxyz";

/// Crockford's base32, lower case, no padding.
pub fn base32(bytes: &[u8]) -> String {
    let mut out = String::with_capacity((bytes.len() * 8).div_ceil(5));
    let mut acc: u32 = 0;
    let mut bits = 0;
    for &b in bytes {
        acc = (acc << 8) | u32::from(b);
        bits += 8;
        while bits >= 5 {
            out.push(BASE32[((acc >> (bits - 5)) & 31) as usize] as char);
            bits -= 5;
        }
        acc &= (1 << bits) - 1;
    }
    if bits > 0 {
        out.push(BASE32[((acc << (5 - bits)) & 31) as usize] as char);
    }
    out
}

/// Is every character one of base32's?
pub fn is_base32(text: &str) -> bool {
    text.bytes().all(|c| BASE32.contains(&c))
}

pub fn hex(bytes: &[u8]) -> String {
    const H: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for &b in bytes {
        out.push(H[(b >> 4) as usize] as char);
        out.push(H[(b & 15) as usize] as char);
    }
    out
}

/// CRC-32 (IEEE 802.3, reflected, as zlib computes it).
pub fn crc32(data: &[u8]) -> u32 {
    let mut crc = 0xffff_ffffu32;
    for &b in data {
        crc ^= u32::from(b);
        for _ in 0..8 {
            crc = (crc >> 1) ^ (0xedb8_8320 & (crc & 1).wrapping_neg());
        }
    }
    !crc
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn base64url_both_ways_and_only_its_one_text() {
        // RFC 4648 §10's vectors, unpadded and url-safe
        for (plain, enc) in [
            ("", ""),
            ("f", "Zg"),
            ("fo", "Zm8"),
            ("foo", "Zm9v"),
            ("foob", "Zm9vYg"),
            ("fooba", "Zm9vYmE"),
            ("foobar", "Zm9vYmFy"),
        ] {
            assert_eq!(b64url(plain.as_bytes()), enc);
            assert_eq!(from_b64url(enc).unwrap(), plain.as_bytes());
        }
        assert_eq!(b64url(&[0xfb, 0xff]), "-_8");
        for n in 0..64u8 {
            let bytes: Vec<u8> = (0..n).map(|i| i.wrapping_mul(37).wrapping_add(n)).collect();
            assert_eq!(from_b64url(&b64url(&bytes)).unwrap(), bytes);
        }
        assert_eq!(from_b64url("abd"), None, "the bytes of \"abc\", written another way");
        assert_eq!(from_b64url("ab=="), None);
        assert_eq!(from_b64url("a+b/"), None);
        assert_eq!(from_b64url("a"), None);
    }

    #[test]
    fn base32_and_hex_and_crc32() {
        assert_eq!(base32(&[0xff; 5]), "zzzzzzzz");
        assert_eq!(base32(&[0]), "00");
        assert_eq!(base32(&[]), "");
        assert!(is_base32("0123456789abcdefghjkmnpqrstvwxyz") && !is_base32("i") && !is_base32("A"));
        assert_eq!(hex(&[0, 15, 255]), "000fff");
        assert_eq!(crc32(b""), 0);
        assert_eq!(crc32(b"123456789"), 0xcbf4_3926); // the check value of CRC-32/ISO-HDLC
        assert_eq!(crc32(b"The quick brown fox jumps over the lazy dog"), 0x414f_a339);
    }
}
