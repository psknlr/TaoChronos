//! TaoCore: what a search computes over its candidates, as `src/taochronos/plugins/retrieval/index.py` defines it,
//! computed natively — the same numbers, bit for bit.
//!
//! A search over a large corpus ranks its few thousand candidates twice: by BM25 over their characters and bigrams, and
//! by the cosine of hashed character n-gram vectors (`HashingEmbedder`, `DenseIndex`).  Measured, those two rankings
//! were most of a search's time, in CPython and more so in the browser's Pyodide, and nearly all of it in loops Python
//! runs one character at a time.  This crate runs those loops.  What it computes is fixed by the Python definitions,
//! which stay the reference (and the fallback): the characters kept ([`keep`]), the tokens, the lengths, every
//! floating-point operation in Python's order, CPython's own `sum()` ([`py_sum`]), the hash ([`blake2b64`]), the
//! thresholds and the order of the results.
//!
//! Two things depend on the platform Python runs on, and stay with Python: the logarithm of a token's weight (idf) —
//! `math.log` is the C library's, and glibc, musl and a wasm32 build disagree in the last bit — and which summation
//! `sum()` does, compensated from CPython 3.12 and plain before.  So BM25 is two calls ([`Batch::count`], then the
//! caller's idf into [`Batch::bm25`]), and the dense route is told which sum to do ([`Sum`]).  Each result is then the
//! one the Python definitions give on the same interpreter: native beside CPython, wasm32 beside Pyodide.
//!
//! The crate has no dependency and no `unsafe`; the bindings (`taocore-py`, `taocore-wasm`) are thin.

#![forbid(unsafe_code)]

mod blake2b;

pub use blake2b::{MAX_MESSAGE, blake2b64};

/// The version of what the bindings speak: a caller that expects another refuses the module.
pub const ABI: u32 = 1;

/// What separates the texts of a batch: a control character no text the indexes read is made of.
pub const SEPARATOR: char = '\u{1f}';

/// The longest n-gram the embedder hashes here: 42 characters of 3 bytes each fill one BLAKE2b block.
pub const MAX_NGRAM: usize = MAX_MESSAGE / 3;

/// The characters the indexes read (index.py's `_KEEP`): U+3400–U+D7FF and U+E000–U+FAFF.  All are in the Basic
/// Multilingual Plane, so a `u16` holds each, and each is three bytes in UTF-8.
#[inline]
pub const fn keep(c: u32) -> bool {
    matches!(c, 0x3400..=0xD7FF | 0xE000..=0xFAFF)
}

/// What a caller gave that the definitions cannot take (the caller then runs its own code).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Error {
    /// the texts are not as many as said
    Count { expected: usize, found: usize },
    /// a query token is not one or two of the characters kept
    Token(String),
    /// BM25 scores asked before the query was counted, or with as many weights as tokens
    Weights { expected: usize, found: usize },
    /// a vector of no dimension
    Dimension,
    /// an n-gram size of 0, or above [`MAX_NGRAM`]
    Ngram(usize),
    /// a document that is not in the batch
    Document(usize),
    /// bytes that are not UTF-8
    Utf8,
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Error::Count { expected, found } => write!(f, "{found} texts where {expected} were said"),
            Error::Token(t) => write!(f, "{t:?} is not a query token (one or two kept characters)"),
            Error::Weights { expected, found } => {
                write!(f, "{found} weights for {expected} counted tokens")
            }
            Error::Dimension => write!(f, "a vector needs a dimension"),
            Error::Ngram(n) => write!(f, "n-grams of {n} characters are not hashed here"),
            Error::Document(d) => write!(f, "no document {d} in the batch"),
            Error::Utf8 => write!(f, "the bytes are not UTF-8"),
        }
    }
}

impl std::error::Error for Error {}

/// The characters the corpus store's full-text index reads (store.py's `is_han`, `HAN_RUN`): the unified ideographs of the
/// Basic Multilingual Plane and the compatibility ones, those of planes 2 and 3, 〇 and 〓 — not the retrieval indexes'
/// [`keep`]: each reads what it was made for.
#[inline]
pub const fn run_char(c: u32) -> bool {
    matches!(c, 0x3400..=0x9FFF | 0xF900..=0xFAFF | 0x20000..=0x3134F | 0x3007 | 0x3013)
}

/// store.py's `grams(norm)`, the full-text index's tokens of a normalised text: each run of [`run_char`] characters gives
/// its overlapping bigrams and then its last character with "z" (so that every character starts a token); runs are
/// separated by "x", and one more follows the last run when anything comes after it; the tokens joined by spaces.
pub fn grams_into(text: &str, out: &mut String) {
    let mut tokens = 0usize;
    let mut run: Vec<char> = Vec::new();
    let token = |out: &mut String, tokens: &mut usize, parts: &[char], end: Option<char>| {
        if *tokens > 0 {
            out.push(' ');
        }
        out.extend(parts.iter().chain(end.as_ref()));
        *tokens += 1;
    };
    let flush = |out: &mut String, tokens: &mut usize, run: &[char]| {
        if *tokens > 0 {
            token(out, tokens, &['x'], None);
        }
        for pair in run.windows(2) {
            token(out, tokens, pair, None);
        }
        token(out, tokens, &run[run.len() - 1..], Some('z'));
    };
    for c in text.chars() {
        if run_char(c as u32) {
            run.push(c);
        } else if !run.is_empty() {
            flush(out, &mut tokens, &run);
            run.clear();
        }
    }
    if !run.is_empty() {
        flush(out, &mut tokens, &run);
    } else if tokens > 0 {
        token(out, &mut tokens, &['x'], None);
    }
}

/// [`grams_into`] of `count` texts separated by [`SEPARATOR`], the results separated by it too (no token holds it).
pub fn grams_many(texts: &str, count: usize) -> Result<String, Error> {
    let mut out = String::with_capacity(texts.len() * 3);
    let mut found = 0;
    if count > 0 {
        for (i, text) in texts.split(SEPARATOR).enumerate() {
            if i > 0 {
                out.push(SEPARATOR);
            }
            grams_into(text, &mut out);
            found += 1;
        }
    } else if !texts.is_empty() {
        found = 1;
    }
    if found != count {
        return Err(Error::Count { expected: count, found });
    }
    Ok(out)
}

/// The kept characters of a text, in order (index.py's `"".join(han(text))`).
pub fn kept(text: &str) -> Vec<u16> {
    let mut out = Vec::with_capacity(text.len() / 3);
    kept_into(text, &mut out);
    out
}

fn kept_into(text: &str, out: &mut Vec<u16>) {
    for c in text.chars() {
        let c = c as u32;
        if keep(c) {
            out.push(c as u16);
        }
    }
}

/// A token of a query (index.py's `query_tokens`): one kept character, or two.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Token {
    One(u16),
    Two(u16, u16),
}

impl Token {
    /// The token a string is, if it is one or two kept characters.
    pub fn parse(text: &str) -> Result<Token, Error> {
        let bad = || Error::Token(text.to_string());
        let mut chars = text.chars().map(|c| c as u32);
        let a = chars.next().filter(|&c| keep(c)).ok_or_else(bad)?;
        match chars.next() {
            None => Ok(Token::One(a as u16)),
            Some(b) if keep(b) && chars.next().is_none() => Ok(Token::Two(a as u16, b as u16)),
            Some(_) => Err(bad()),
        }
    }
}

/// Which summation Python's `sum()` does over floats: compensated (Neumaier's, CPython 3.12 and later) or plain
/// left-to-right addition (CPython 3.11).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Sum {
    Compensated,
    Plain,
}

/// CPython's `sum()` of floats, started from its int 0: the first addition is `0.0 + x` (a -0.0 becomes +0.0); then
/// each item is added, with Neumaier's compensation from 3.12, which is added at the end when it is finite and not zero.
/// An empty input gives 0.0 (Python's int 0; no caller here sums nothing).
pub fn py_sum<I: IntoIterator<Item = f64>>(items: I, how: Sum) -> f64 {
    let mut items = items.into_iter();
    let Some(first) = items.next() else {
        return 0.0;
    };
    let mut f = 0.0 + first;
    match how {
        Sum::Plain => {
            for x in items {
                f += x;
            }
            f
        }
        Sum::Compensated => {
            let mut c = 0.0f64;
            for x in items {
                let t = f + x;
                if f.abs() >= x.abs() {
                    c += (f - t) + x;
                } else {
                    c += (x - t) + f;
                }
                f = t;
            }
            if c != 0.0 && c.is_finite() {
                f += c;
            }
            f
        }
    }
}

/// The texts of a search's candidates, as the indexes read them: each one's kept characters.
pub struct Docs {
    chars: Vec<u16>,
    ends: Vec<usize>,
}

impl Docs {
    /// `count` texts, separated by [`SEPARATOR`].  (No text, and `count` 0, is no document; no text and `count` 1 is
    /// one empty document.)
    pub fn parse(texts: &str, count: usize) -> Result<Docs, Error> {
        let mut docs = Docs { chars: Vec::with_capacity(texts.len() / 3), ends: Vec::with_capacity(count) };
        if count == 0 {
            return if texts.is_empty() { Ok(docs) } else { Err(Error::Count { expected: 0, found: 1 }) };
        }
        for part in texts.split(SEPARATOR) {
            kept_into(part, &mut docs.chars);
            docs.ends.push(docs.chars.len());
        }
        if docs.ends.len() != count {
            return Err(Error::Count { expected: count, found: docs.ends.len() });
        }
        Ok(docs)
    }

    pub fn len(&self) -> usize {
        self.ends.len()
    }

    pub fn is_empty(&self) -> bool {
        self.ends.is_empty()
    }

    /// The kept characters of document `d`.
    pub fn doc(&self, d: usize) -> &[u16] {
        let start = if d == 0 { 0 } else { self.ends[d - 1] };
        &self.chars[start..self.ends[d]]
    }

    /// The document's length as BM25Index counts it: its tokens, the characters and the bigrams (L + max(L − 1, 0)).
    pub fn length(&self, d: usize) -> u64 {
        let n = self.doc(d).len() as u64;
        if n == 0 { 0 } else { 2 * n - 1 }
    }
}

/// What BM25 reads of the documents for one query: each distinct token's count in each document, and in how many
/// documents it occurs — the query's tokens only (BM25Index counts every token of every document, and a search reads
/// those of its query alone).
struct Counted {
    /// the distinct tokens, in the order they first appear in the query
    distinct: Vec<Token>,
    /// the query, as places in `distinct` (a token asked twice counts twice)
    query: Vec<usize>,
    /// counts: document-major, `distinct.len()` per document
    tf: Vec<u32>,
}

/// The tokens that begin with one character: the one-character token's place among the distinct tokens, if it is one,
/// and each two-character token's second character and place.
type Group = (Option<usize>, Vec<(u16, usize)>);

/// A search's candidates, once read: BM25 for its query and the dense route's cosines are computed over it.
pub struct Batch {
    docs: Docs,
    counted: Option<Counted>,
}

/// One result: a document's place in the batch and its score.
pub type Scored = (u32, f64);

impl Batch {
    pub fn new(texts: &str, count: usize) -> Result<Batch, Error> {
        Ok(Batch { docs: Docs::parse(texts, count)?, counted: None })
    }

    pub fn from_utf8(texts: &[u8], count: usize) -> Result<Batch, Error> {
        Batch::new(std::str::from_utf8(texts).map_err(|_| Error::Utf8)?, count)
    }

    pub fn docs(&self) -> &Docs {
        &self.docs
    }

    pub fn len(&self) -> usize {
        self.docs.len()
    }

    pub fn is_empty(&self) -> bool {
        self.docs.is_empty()
    }

    /// The sum of the documents' lengths: BM25's average length is this over their number — divided by the caller,
    /// so that it is Python's int / int, correctly rounded.
    pub fn total_length(&self) -> u64 {
        (0..self.docs.len()).map(|d| self.docs.length(d)).sum()
    }

    /// BM25, first step: the query's tokens counted in every document.  Returns, for each distinct token in the order
    /// it first appears in the query, the number of documents it occurs in (df), from which the caller makes its
    /// weight (idf) with its own logarithm.
    pub fn count(&mut self, query: &[Token]) -> Vec<u64> {
        let mut distinct: Vec<Token> = Vec::new();
        let places: Vec<usize> = query
            .iter()
            .map(|t| match distinct.iter().position(|d| d == t) {
                Some(p) => p,
                None => {
                    distinct.push(*t);
                    distinct.len() - 1
                }
            })
            .collect();
        let width = distinct.len();
        // the tokens by their first character: a document is read once, one lookup per character
        let mut first: Vec<u32> = vec![0; 1 << 16];
        let mut groups: Vec<Group> = Vec::new();
        for (j, t) in distinct.iter().enumerate() {
            let a = match t {
                Token::One(a) | Token::Two(a, _) => *a as usize,
            };
            if first[a] == 0 {
                groups.push((None, Vec::new()));
                first[a] = groups.len() as u32;
            }
            let group = &mut groups[first[a] as usize - 1];
            match t {
                Token::One(_) => group.0 = Some(j),
                Token::Two(_, b) => group.1.push((*b, j)),
            }
        }
        let n = self.docs.len();
        let mut tf = vec![0u32; n * width];
        let mut df = vec![0u64; width];
        if width > 0 {
            for d in 0..n {
                let chars = self.docs.doc(d);
                let row = &mut tf[d * width..(d + 1) * width];
                for (i, &c) in chars.iter().enumerate() {
                    let g = first[c as usize];
                    if g == 0 {
                        continue;
                    }
                    let (one, two) = &groups[g as usize - 1];
                    if let Some(j) = one {
                        row[*j] += 1;
                    }
                    if let Some(&next) = chars.get(i + 1) {
                        for &(b, j) in two {
                            if b == next {
                                row[j] += 1;
                            }
                        }
                    }
                }
                for (j, &c) in row.iter().enumerate() {
                    if c > 0 {
                        df[j] += 1;
                    }
                }
            }
        }
        self.counted = Some(Counted { distinct, query: places, tf });
        df
    }

    /// The tokens [`Batch::count`] counted, in the order of its df.
    pub fn counted_tokens(&self) -> Option<&[Token]> {
        self.counted.as_ref().map(|c| c.distinct.as_slice())
    }

    /// BM25, second step: each document's score for the counted query (index.py's `BM25Index._score`, operation for
    /// operation), given each distinct token's weight (`idf`, in [`Batch::count`]'s order), the average length and the
    /// parameters; the documents scoring above 0, best first, a tie broken by the document's place; the first `k`.
    pub fn bm25(&self, idf: &[f64], avgdl: f64, k1: f64, b: f64, k: usize) -> Result<Vec<Scored>, Error> {
        let counted = self.counted.as_ref().ok_or(Error::Weights { expected: 0, found: idf.len() })?;
        let width = counted.distinct.len();
        if idf.len() != width {
            return Err(Error::Weights { expected: width, found: idf.len() });
        }
        let mut scored = Vec::new();
        for d in 0..self.docs.len() {
            let length = self.docs.length(d);
            if length == 0 {
                continue; // a document of which nothing is read scores 0.0 (and an index of such has no average)
            }
            let norm = k1 * ((1.0 - b) + (b * length as f64) / avgdl);
            let row = &counted.tf[d * width..(d + 1) * width];
            let mut s = 0.0f64;
            for &j in &counted.query {
                let tf = row[j];
                if tf != 0 {
                    let tf = tf as f64;
                    s += ((idf[j] * tf) * (k1 + 1.0)) / (tf + norm);
                }
            }
            if s > 0.0 {
                scored.push((d as u32, s));
            }
        }
        Ok(best(scored, k))
    }

    /// The dense route (index.py's `DenseIndex.search` over these documents): the query's vector and each of
    /// `docs`' (places in the batch), their cosines; those above `threshold`, best first, a tie broken by the
    /// document's place; the first `k`.
    pub fn dense(
        &self,
        docs: &[u32],
        query: &str,
        embedding: &Embedding,
        threshold: f64,
        k: usize,
        cache: &mut GramCache,
    ) -> Result<Vec<Scored>, Error> {
        if let Some(&d) = docs.iter().find(|&&d| d as usize >= self.docs.len()) {
            return Err(Error::Document(d as usize));
        }
        let mut q = vec![0.0; embedding.dim];
        embedding.embed(&kept(query), cache, &mut q);
        let mut v = vec![0.0; embedding.dim];
        let mut scored = Vec::new();
        for &d in docs {
            embedding.embed(self.docs.doc(d as usize), cache, &mut v);
            let s = cosine(&q, &v, embedding.sum);
            if s > threshold {
                scored.push((d, s));
            }
        }
        Ok(best(scored, k))
    }
}

/// Best first, a tie broken by the place (which is the id's order: a batch's documents are in the order of their
/// ids), the first `k` — index.py's `sort(key=lambda t: (-t[1], t[0]))[:k]`.  The scores are finite and above a
/// threshold of at least 0.
fn best(mut scored: Vec<Scored>, k: usize) -> Vec<Scored> {
    scored.sort_unstable_by(|a, b| b.1.total_cmp(&a.1).then(a.0.cmp(&b.0)));
    scored.truncate(k);
    scored
}

/// The hashing embedder's settings (index.py's `HashingEmbedder(dim, ngram)`) and the sum Python does.
#[derive(Debug, Clone)]
pub struct Embedding {
    pub dim: usize,
    pub ngram: Vec<usize>,
    pub sum: Sum,
}

impl Embedding {
    pub fn new(dim: usize, ngram: &[usize], sum: Sum) -> Result<Embedding, Error> {
        if dim == 0 {
            return Err(Error::Dimension);
        }
        if let Some(&n) = ngram.iter().find(|&&n| n == 0 || n > MAX_NGRAM) {
            return Err(Error::Ngram(n));
        }
        Ok(Embedding { dim, ngram: ngram.to_vec(), sum })
    }

    /// A text's vector (index.py's `HashingEmbedder.embed`): for each n-gram size in order, each n-gram from the left
    /// adds its weight (1.0, 1.5, 2.0 … for 1, 2, 3 … characters) at the place its hash names, with the sign of the
    /// hash's top bit; then the vector over its length (`math.sqrt(sum(v * v …)) or 1.0`).
    pub fn embed(&self, chars: &[u16], cache: &mut GramCache, out: &mut [f64]) {
        out.fill(0.0);
        let dim = self.dim as u64;
        for &n in &self.ngram {
            if chars.len() < n {
                continue;
            }
            let weight = 1.0 + 0.5 * ((n - 1) as f64);
            for gram in chars.windows(n) {
                let h = cache.hash(gram);
                let place = if dim.is_power_of_two() { h & (dim - 1) } else { h % dim } as usize;
                out[place] += if h >> 63 == 1 { weight } else { -weight };
            }
        }
        let length = py_sum(out.iter().map(|v| v * v), self.sum).sqrt();
        let length = if length == 0.0 { 1.0 } else { length };
        for v in out.iter_mut() {
            *v /= length;
        }
    }
}

/// index.py's `cosine`: `sum(map(mul, a, b))`, with the summation of the Python it stands beside.
pub fn cosine(a: &[f64], b: &[f64], how: Sum) -> f64 {
    py_sum(a.iter().zip(b).map(|(x, y)| x * y), how)
}

/// The UTF-8 bytes of kept characters (three bytes each).
fn utf8(chars: &[u16], out: &mut [u8; MAX_MESSAGE]) -> usize {
    let mut at = 0;
    for &c in chars {
        out[at] = 0xE0 | (c >> 12) as u8;
        out[at + 1] = 0x80 | ((c >> 6) & 0x3F) as u8;
        out[at + 2] = 0x80 | (c & 0x3F) as u8;
        at += 3;
    }
    at
}

/// The hashes of the n-grams of up to three characters already met: the same characters and words come back in every
/// passage of a search, and in the next search.  Open addressing over a power-of-two table, started again when it is
/// 70% full (a cache only: what it holds never changes a number).  Longer n-grams are hashed each time.
pub struct GramCache {
    keys: Vec<u64>,
    hashes: Vec<u64>,
    used: usize,
}

impl GramCache {
    /// A cache of 2^`bits` places (16 bytes each).
    pub fn new(bits: u32) -> GramCache {
        let size = 1usize << bits.clamp(4, 28);
        GramCache { keys: vec![0; size], hashes: vec![0; size], used: 0 }
    }

    /// How many n-grams it holds.
    pub fn len(&self) -> usize {
        self.used
    }

    pub fn is_empty(&self) -> bool {
        self.used == 0
    }

    /// The n-gram's hash ([`blake2b64`] of its UTF-8).  The n-gram is of kept characters, at most [`MAX_NGRAM`].
    pub fn hash(&mut self, gram: &[u16]) -> u64 {
        if gram.len() > 3 {
            return Self::compute(gram);
        }
        // the key: the characters and their number, never 0
        let key = gram.iter().fold(gram.len() as u64, |k, &c| (k << 16) | c as u64);
        let mask = self.keys.len() - 1;
        let mut i = (key.wrapping_mul(0x9E37_79B9_7F4A_7C15) >> 32) as usize & mask;
        loop {
            match self.keys[i] {
                k if k == key => return self.hashes[i],
                0 => break,
                _ => i = (i + 1) & mask,
            }
        }
        let h = Self::compute(gram);
        if (self.used + 1) * 10 > self.keys.len() * 7 {
            self.keys.fill(0);
            self.used = 0;
            i = (key.wrapping_mul(0x9E37_79B9_7F4A_7C15) >> 32) as usize & mask;
        }
        self.keys[i] = key;
        self.hashes[i] = h;
        self.used += 1;
        h
    }

    fn compute(gram: &[u16]) -> u64 {
        let mut bytes = [0u8; MAX_MESSAGE];
        let n = utf8(gram, &mut bytes);
        // an n-gram of at most MAX_NGRAM characters fits one block (Embedding::new refuses a longer one)
        blake2b64(&bytes[..n]).unwrap_or(0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_kept_characters_are_the_ones_index_py_keeps() {
        for c in [0x3400, 0x4E00, 0x9FFF, 0xA000, 0xAC00, 0xD7FF, 0xE000, 0xF8FF, 0xF900, 0xFAFF] {
            assert!(keep(c), "{c:X}");
        }
        for c in [0x0, 0x41, 0x3000, 0x33FF, 0xD800, 0xDFFF, 0xFB00, 0xFF0C, 0x20000, 0x2A6A5] {
            assert!(!keep(c), "{c:X}");
        }
        assert_eq!(kept("桂 枝,汤 abc 𠀀"), vec!['桂' as u16, '枝' as u16, '汤' as u16]);
    }

    #[test]
    fn the_tokens_of_a_query_are_one_or_two_kept_characters() {
        assert_eq!(Token::parse("桂"), Ok(Token::One('桂' as u16)));
        assert_eq!(Token::parse("桂枝"), Ok(Token::Two('桂' as u16, '枝' as u16)));
        for bad in ["", "a", "桂a", "桂枝汤", "𠀀", "。"] {
            assert!(Token::parse(bad).is_err(), "{bad}");
        }
    }

    #[test]
    fn python_sums_its_way() {
        // CPython 3.12+: sum([1e100, 1.0, -1e100]) == 1.0; 3.11: 0.0
        assert_eq!(py_sum([1e100, 1.0, -1e100], Sum::Compensated), 1.0);
        assert_eq!(py_sum([1e100, 1.0, -1e100], Sum::Plain), 0.0);
        assert_eq!(py_sum([1.0, 1e100, 1.0, -1e100], Sum::Compensated), 2.0);
        // the int 0 it starts from turns a -0.0 into +0.0
        for how in [Sum::Compensated, Sum::Plain] {
            assert!(py_sum([-0.0], how).is_sign_positive());
            assert!(py_sum([-0.0, -0.0], how).is_sign_positive());
            assert_eq!(py_sum(std::iter::empty(), how), 0.0);
        }
        // an infinite compensation is not added (it would make a NaN of an overflowed sum)
        assert_eq!(py_sum([f64::MAX, f64::MAX, -f64::MAX], Sum::Compensated), f64::INFINITY);
    }

    #[test]
    fn a_batch_reads_its_texts_and_says_when_they_are_not_as_many() {
        let b = Batch::new("桂枝汤\u{1f}\u{1f}abc。\u{1f}消渴", 4).unwrap();
        assert_eq!(b.len(), 4);
        assert_eq!(b.docs().doc(1), &[] as &[u16]);
        assert_eq!(b.docs().length(0), 5);
        assert_eq!(b.docs().length(2), 0);
        assert_eq!(b.total_length(), 5 + 3);
        assert_eq!(Batch::new("a\u{1f}b", 3).err(), Some(Error::Count { expected: 3, found: 2 }));
        assert_eq!(Batch::new("", 0).map(|b| b.len()), Ok(0));
        assert_eq!(Batch::new("", 1).map(|b| b.len()), Ok(1));
        assert!(Batch::from_utf8(&[0xFF], 1).is_err());
    }

    #[test]
    fn bm25_counts_overlapping_bigrams_and_breaks_ties_by_place() {
        let mut b = Batch::new("汤汤汤\u{1f}汤汤\u{1f}桂枝\u{1f}汤汤汤", 4).unwrap();
        let q = [Token::Two('汤' as u16, '汤' as u16), Token::One('桂' as u16)];
        assert_eq!(b.count(&q), vec![3, 1]);
        let scored = b.bm25(&[1.0, 2.0], 1.0, 1.4, 0.75, 10).unwrap();
        // documents 0 and 3 are the same text: the same score, in the order of their places
        assert_eq!(scored.iter().map(|s| s.0).collect::<Vec<_>>(), [2, 0, 3, 1]);
        assert_eq!(scored[1].1.to_bits(), scored[2].1.to_bits());
        assert_eq!(b.bm25(&[1.0, 2.0], 1.0, 1.4, 0.75, 2).unwrap().len(), 2);
        assert!(b.bm25(&[1.0], 1.0, 1.4, 0.75, 10).is_err());
    }

    #[test]
    fn the_full_text_tokens_are_store_pys() {
        let g = |t: &str| {
            let mut out = String::new();
            grams_into(t, &mut out);
            out
        };
        // from Python: taochronos.plugins.classics.store.grams
        assert_eq!(g("桂枝汤"), "桂枝 枝汤 汤z");
        assert_eq!(g("桂枝，汤。"), "桂枝 枝z x 汤z x");
        assert_eq!(g("，桂"), "桂z");
        assert_eq!(g("abc"), "");
        assert_eq!(g(""), "");
        assert_eq!(g("〇𠀀𪚥〓"), "〇𠀀 𠀀𪚥 𪚥〓 〓z");
        assert_eq!(g("한글\u{e3e7}桂"), "桂z");
        assert_eq!(grams_many("桂枝\u{1f}\u{1f}汤。", 3), Ok("桂枝 枝z\u{1f}\u{1f}汤z x".to_string()));
        assert!(grams_many("a\u{1f}b", 3).is_err());
        assert_eq!(grams_many("", 0), Ok(String::new()));
    }

    #[test]
    fn an_embedding_refuses_what_it_cannot_hash() {
        assert!(Embedding::new(0, &[1], Sum::Compensated).is_err());
        assert!(Embedding::new(512, &[0], Sum::Compensated).is_err());
        assert!(Embedding::new(512, &[MAX_NGRAM + 1], Sum::Compensated).is_err());
        assert!(Embedding::new(64, &[2, 4], Sum::Plain).is_ok());
    }

    #[test]
    fn the_cache_changes_no_hash() {
        let mut small = GramCache::new(4); // 16 places: started again many times
        let text = kept("太阳病，头痛，发热，汗出，恶风，桂枝汤主之。阳浮而阴弱，阳浮者，热自发；阴弱者，汗自出。");
        for n in 1..=5 {
            for gram in text.windows(n) {
                assert_eq!(small.hash(gram), GramCache::compute(gram));
                assert!(small.len() <= 16);
            }
        }
    }
}
