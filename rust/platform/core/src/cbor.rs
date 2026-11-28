//! CBOR (RFC 8949), the subset WebAuthn writes: integers, byte and text strings, arrays, maps, true, false, null — of
//! definite length only.  No tags, no floats, no indefinite lengths, a map's key once, and a depth and a count of
//! items no credential comes near; anything else is refused.  What is read is a credential a browser sent: the reader
//! is written for what an attacker would send instead.

#[derive(Debug, Clone, PartialEq)]
pub enum Cbor {
    Int(i64),
    Bytes(Vec<u8>),
    Text(String),
    Array(Vec<Cbor>),
    /// keys are integers or text, each once
    Map(Vec<(Cbor, Cbor)>),
    Bool(bool),
    Null,
}

impl Cbor {
    /// A map's value under an integer key (COSE's labels).
    pub fn int_key(&self, k: i64) -> Option<&Cbor> {
        match self {
            Cbor::Map(m) => m.iter().find(|(key, _)| *key == Cbor::Int(k)).map(|(_, v)| v),
            _ => None,
        }
    }

    /// A map's value under a text key (the attestation object's).
    pub fn text_key(&self, k: &str) -> Option<&Cbor> {
        match self {
            Cbor::Map(m) => m.iter().find(|(key, _)| matches!(key, Cbor::Text(t) if t == k)).map(|(_, v)| v),
            _ => None,
        }
    }

    pub fn as_int(&self) -> Option<i64> {
        match self {
            Cbor::Int(n) => Some(*n),
            _ => None,
        }
    }

    pub fn as_bytes(&self) -> Option<&[u8]> {
        match self {
            Cbor::Bytes(b) => Some(b),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Malformed;

const DEPTH: usize = 8;
const ITEMS: usize = 512;

/// One item at `at`: the item, and where the next begins.
pub fn read(bytes: &[u8], at: usize) -> Result<(Cbor, usize), Malformed> {
    let mut items = 0;
    item(bytes, at, 0, &mut items)
}

/// A whole buffer as one item: nothing may follow it.
pub fn decode(bytes: &[u8]) -> Result<Cbor, Malformed> {
    let (v, end) = read(bytes, 0)?;
    if end == bytes.len() { Ok(v) } else { Err(Malformed) }
}

fn item(bytes: &[u8], at: usize, depth: usize, items: &mut usize) -> Result<(Cbor, usize), Malformed> {
    *items += 1;
    if depth > DEPTH || *items > ITEMS {
        return Err(Malformed);
    }
    let head = *bytes.get(at).ok_or(Malformed)?;
    let (major, info) = (head >> 5, head & 31);
    let mut p = at + 1;
    let n: u64 = match info {
        0..=23 => u64::from(info),
        24..=27 => {
            let size = 1usize << (info - 24);
            let raw = bytes.get(p..p + size).ok_or(Malformed)?;
            p += size;
            raw.iter().fold(0u64, |acc, b| (acc << 8) | u64::from(*b))
        }
        _ => return Err(Malformed), // reserved, or an indefinite length
    };
    let len = |n: u64| usize::try_from(n).map_err(|_| Malformed);
    match major {
        0 => Ok((Cbor::Int(i64::try_from(n).map_err(|_| Malformed)?), p)),
        1 => Ok((Cbor::Int(-1 - i64::try_from(n).map_err(|_| Malformed)?), p)),
        2 | 3 => {
            let end = p.checked_add(len(n)?).ok_or(Malformed)?;
            let raw = bytes.get(p..end).ok_or(Malformed)?;
            let v = if major == 2 {
                Cbor::Bytes(raw.to_vec())
            } else {
                Cbor::Text(std::str::from_utf8(raw).map_err(|_| Malformed)?.to_string())
            };
            Ok((v, end))
        }
        4 => {
            let count = len(n)?;
            if count > ITEMS {
                return Err(Malformed);
            }
            let mut list = Vec::with_capacity(count);
            for _ in 0..count {
                let (v, next) = item(bytes, p, depth + 1, items)?;
                list.push(v);
                p = next;
            }
            Ok((Cbor::Array(list), p))
        }
        5 => {
            let count = len(n)?;
            if count > ITEMS {
                return Err(Malformed);
            }
            let mut map: Vec<(Cbor, Cbor)> = Vec::with_capacity(count);
            for _ in 0..count {
                let (k, next) = item(bytes, p, depth + 1, items)?;
                if !matches!(k, Cbor::Int(_) | Cbor::Text(_)) || map.iter().any(|(seen, _)| *seen == k) {
                    return Err(Malformed);
                }
                let (v, next) = item(bytes, next, depth + 1, items)?;
                map.push((k, v));
                p = next;
            }
            Ok((Cbor::Map(map), p))
        }
        7 => match info {
            20 => Ok((Cbor::Bool(false), p)),
            21 => Ok((Cbor::Bool(true), p)),
            22 => Ok((Cbor::Null, p)),
            _ => Err(Malformed), // undefined, floats, other simple values
        },
        _ => Err(Malformed), // 6: tags
    }
}

/// CBOR of a value, as an authenticator writes it (the tests' software authenticator uses it).
pub fn encode(v: &Cbor) -> Vec<u8> {
    fn head(out: &mut Vec<u8>, major: u8, n: u64) {
        let m = major << 5;
        match n {
            0..=23 => out.push(m | n as u8),
            24..=0xff => out.extend([m | 24, n as u8]),
            0x100..=0xffff => {
                out.push(m | 25);
                out.extend((n as u16).to_be_bytes());
            }
            0x1_0000..=0xffff_ffff => {
                out.push(m | 26);
                out.extend((n as u32).to_be_bytes());
            }
            _ => {
                out.push(m | 27);
                out.extend(n.to_be_bytes());
            }
        }
    }
    fn walk(out: &mut Vec<u8>, v: &Cbor) {
        match v {
            Cbor::Int(n) if *n >= 0 => head(out, 0, *n as u64),
            Cbor::Int(n) => head(out, 1, (-1 - *n) as u64),
            Cbor::Bytes(b) => {
                head(out, 2, b.len() as u64);
                out.extend(b);
            }
            Cbor::Text(t) => {
                head(out, 3, t.len() as u64);
                out.extend(t.as_bytes());
            }
            Cbor::Array(a) => {
                head(out, 4, a.len() as u64);
                a.iter().for_each(|x| walk(out, x));
            }
            Cbor::Map(m) => {
                head(out, 5, m.len() as u64);
                for (k, x) in m {
                    walk(out, k);
                    walk(out, x);
                }
            }
            Cbor::Bool(b) => out.push(if *b { 0xf5 } else { 0xf4 }),
            Cbor::Null => out.push(0xf6),
        }
    }
    let mut out = Vec::new();
    walk(&mut out, v);
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn what_webauthn_writes_is_read_and_nothing_else() {
        let v = Cbor::Map(vec![
            (Cbor::Text("fmt".into()), Cbor::Text("none".into())),
            (Cbor::Int(-2), Cbor::Bytes(vec![1; 300])),
            (Cbor::Int(3), Cbor::Int(-257)),
            (Cbor::Text("a".into()), Cbor::Array(vec![Cbor::Bool(true), Cbor::Null, Cbor::Int(1 << 40)])),
        ]);
        assert_eq!(decode(&encode(&v)).unwrap(), v);
        assert_eq!(v.int_key(3).and_then(Cbor::as_int), Some(-257));
        assert_eq!(v.text_key("fmt"), Some(&Cbor::Text("none".into())));
        let mut trailing = encode(&v);
        trailing.push(0);
        assert_eq!(decode(&trailing), Err(Malformed));
        for bad in [
            &[0xbf, 0xff][..],                                       // an indefinite-length map
            &[0xc0, 0x60],                                           // a tag
            &[0xa2, 0x61, 0x61, 0x01, 0x61, 0x61, 0x02],             // a key twice
            &[0xfa, 0, 0, 0, 0],                                     // a float
            &[0xf7],                                                 // undefined
            &[0x5a, 0xff, 0xff, 0xff, 0xff],                         // a byte string longer than what follows
            &[0x62, 0xff, 0xfe],                                     // text that is not UTF-8
            &[0xa1, 0x40, 0x01],                                     // a map keyed by bytes
            &[0x1b, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff], // past i64
            &[],
        ] {
            assert_eq!(decode(bad), Err(Malformed), "{bad:02x?}");
        }
        let mut deep = vec![0x81u8; 12];
        deep.push(0x00);
        assert_eq!(decode(&deep), Err(Malformed), "nested past the depth allowed");
    }
}
