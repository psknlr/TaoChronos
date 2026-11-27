//! BLAKE2b (RFC 7693) with an 8-byte digest, for messages of one block: what `hashlib.blake2b(gram, digest_size=8)`
//! gives an n-gram of the hashing embedder (index.py), read as Python reads it, `int.from_bytes(digest, "big")`.
//!
//! The digest size is part of the parameter block, so this is not the first 8 bytes of BLAKE2b-512: a truncated digest
//! would put every n-gram in another place.  An n-gram the embedder hashes is at most 42 characters of 3 bytes in UTF-8
//! (`MAX_MESSAGE`), one block: no message here needs the multi-block path, and none is written.

const IV: [u64; 8] = [
    0x6a09_e667_f3bc_c908,
    0xbb67_ae85_84ca_a73b,
    0x3c6e_f372_fe94_f82b,
    0xa54f_f53a_5f1d_36f1,
    0x510e_527f_ade6_82d1,
    0x9b05_688c_2b3e_6c1f,
    0x1f83_d9ab_fb41_bd6b,
    0x5be0_cd19_137e_2179,
];

const SIGMA: [[usize; 16]; 12] = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
    [14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3],
    [11, 8, 12, 0, 5, 2, 15, 13, 10, 14, 3, 6, 7, 1, 9, 4],
    [7, 9, 3, 1, 13, 12, 11, 14, 2, 6, 5, 10, 4, 0, 15, 8],
    [9, 0, 5, 7, 2, 4, 10, 15, 14, 1, 11, 12, 6, 8, 3, 13],
    [2, 12, 6, 10, 0, 11, 8, 3, 4, 13, 7, 5, 15, 14, 1, 9],
    [12, 5, 1, 15, 14, 13, 4, 10, 0, 7, 6, 3, 9, 2, 8, 11],
    [13, 11, 7, 14, 12, 1, 3, 9, 5, 0, 15, 4, 8, 6, 2, 10],
    [6, 15, 14, 9, 11, 3, 0, 8, 12, 2, 13, 7, 1, 4, 10, 5],
    [10, 2, 8, 4, 7, 6, 1, 5, 15, 11, 9, 14, 3, 12, 13, 0],
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
    [14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3],
];

/// The longest message this hashes: one block.
pub const MAX_MESSAGE: usize = 128;

#[inline(always)]
fn g(v: &mut [u64; 16], a: usize, b: usize, c: usize, d: usize, x: u64, y: u64) {
    v[a] = v[a].wrapping_add(v[b]).wrapping_add(x);
    v[d] = (v[d] ^ v[a]).rotate_right(32);
    v[c] = v[c].wrapping_add(v[d]);
    v[b] = (v[b] ^ v[c]).rotate_right(24);
    v[a] = v[a].wrapping_add(v[b]).wrapping_add(y);
    v[d] = (v[d] ^ v[a]).rotate_right(16);
    v[c] = v[c].wrapping_add(v[d]);
    v[b] = (v[b] ^ v[c]).rotate_right(63);
}

/// `int.from_bytes(hashlib.blake2b(message, digest_size=8).digest(), "big")`, for a message of at most
/// [`MAX_MESSAGE`] bytes (None for a longer one).
pub fn blake2b64(message: &[u8]) -> Option<u64> {
    if message.len() > MAX_MESSAGE {
        return None;
    }
    let mut block = [0u8; MAX_MESSAGE];
    block[..message.len()].copy_from_slice(message);
    let mut m = [0u64; 16];
    for (word, bytes) in m.iter_mut().zip(block.chunks_exact(8)) {
        let mut le = [0u8; 8];
        le.copy_from_slice(bytes);
        *word = u64::from_le_bytes(le);
    }
    // the parameter block: digest length 8, no key, fanout 1, depth 1
    let h0 = IV[0] ^ 0x0101_0000 ^ 8;
    let mut v = [0u64; 16];
    v[0] = h0;
    v[1..8].copy_from_slice(&IV[1..]);
    v[8..].copy_from_slice(&IV);
    v[12] ^= message.len() as u64; // the byte count (the high word, and v[13]'s, stay as they are: under 2^64)
    v[14] = !v[14]; // the last block
    for s in SIGMA.iter() {
        g(&mut v, 0, 4, 8, 12, m[s[0]], m[s[1]]);
        g(&mut v, 1, 5, 9, 13, m[s[2]], m[s[3]]);
        g(&mut v, 2, 6, 10, 14, m[s[4]], m[s[5]]);
        g(&mut v, 3, 7, 11, 15, m[s[6]], m[s[7]]);
        g(&mut v, 0, 5, 10, 15, m[s[8]], m[s[9]]);
        g(&mut v, 1, 6, 11, 12, m[s[10]], m[s[11]]);
        g(&mut v, 2, 7, 8, 13, m[s[12]], m[s[13]]);
        g(&mut v, 3, 4, 9, 14, m[s[14]], m[s[15]]);
    }
    // the digest is the first 8 bytes of h[0] in little-endian order, which Python reads big-endian
    Some((h0 ^ v[0] ^ v[8]).swap_bytes())
}

#[cfg(test)]
mod tests {
    use super::*;

    // from Python: int.from_bytes(hashlib.blake2b(s.encode("utf-8"), digest_size=8).digest(), "big")
    #[test]
    fn the_digests_python_gives() {
        let cases: [(&str, u64); 11] = [
            ("", 0xe4a6_a057_7479_b2b4),
            ("桂", 0x2af5_d763_be5d_56ad),
            ("桂枝", 0x498d_63ab_dd28_69c4),
            ("桂枝汤", 0x7090_6d9e_79b7_9874),
            ("㐀", 0x56b4_810d_6acc_6abe),
            ("\u{faff}", 0xada9_4008_5fb2_7fb7),
            ("\u{e000}", 0x7257_b093_b476_75cd),
            ("\u{d7ff}", 0x6ee8_25c5_d8cd_02c4),
            ("鿿", 0x0375_2849_1d71_7cb2),
            ("汤汤", 0xf017_5718_6701_e902),
            ("太阳病头痛发热汗出恶风桂枝汤主之消渴", 0xadee_e6aa_936b_d1b5),
        ];
        for (text, want) in cases {
            assert_eq!(blake2b64(text.as_bytes()), Some(want), "{text}");
        }
        assert_eq!(blake2b64(&[b'a'; 128]), Some(0xf066_43fe_9c7e_18da));
        assert_eq!(blake2b64(&[b'a'; 129]), None);
    }
}
