//! `taocore.wasm`: TaoCore for the browser's runtime worker, a WebAssembly module of no imports (wasm32-unknown-unknown)
//! with a C ABI.  The loader (web/js/taocore.js) copies a search's texts into this module's memory, calls, and copies
//! the results out; Python reaches it as `_taocore_wasm` (pyodide.registerJsModule) through the same facade as the
//! CPython extension, which falls back to the Python definitions on any failure.
//!
//! No wasm-bindgen: its generated glue, its version-locked command line and its string-only interface buy nothing
//! here — the loader is fifty lines, and Python's bytes reach this memory with one copy.
//!
//! Every entry point checks what it is given and answers -1 (or 0 for a handle) rather than trusting it; a batch is
//! named by a number, and the module keeps the last few: a caller that never frees leaks nothing, and a number that
//! names no batch (freed, or pushed out by newer ones) is refused, never read.

use std::alloc::{Layout, alloc, dealloc};
use std::cell::RefCell;

use taocore::{Batch, Embedding, GramCache, Scored, Sum, Token};

/// The n-gram cache: 2^19 places (8 MB of this module's memory, which never shrinks).
const CACHE_BITS: u32 = 19;
/// The batches kept: a search makes one, and the worker runs one search at a time.
const KEEP: usize = 4;

struct Held {
    next: u32,
    batches: Vec<(u32, Batch)>,
}

thread_local! {
    static HELD: RefCell<Held> = const { RefCell::new(Held { next: 1, batches: Vec::new() }) };
    static CACHE: RefCell<Option<GramCache>> = const { RefCell::new(None) };
    static RESULT: RefCell<String> = const { RefCell::new(String::new()) };
}

fn with_batch<T>(id: u32, work: impl FnOnce(&mut Batch) -> Option<T>) -> Option<T> {
    HELD.with(|held| {
        let mut held = held.borrow_mut();
        let (_, batch) = held.batches.iter_mut().find(|(i, _)| *i == id)?;
        work(batch)
    })
}

/// The version of this ABI (web/js/taocore.js refuses another).
#[unsafe(no_mangle)]
pub extern "C" fn tc_abi() -> u32 {
    taocore::ABI
}

/// `len` bytes of this module's memory, 8-aligned (a Float64Array may view them); 0 when there is none.
#[unsafe(no_mangle)]
pub extern "C" fn tc_alloc(len: usize) -> *mut u8 {
    match Layout::from_size_align(len.max(1), 8) {
        // SAFETY: the layout's size is not zero
        Ok(layout) => unsafe { alloc(layout) },
        Err(_) => std::ptr::null_mut(),
    }
}

/// Gives back what [`tc_alloc`] gave, with the length it was asked for.
///
/// # Safety
/// `ptr` came from `tc_alloc(len)` and is not used after.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn tc_free(ptr: *mut u8, len: usize) {
    if let (false, Ok(layout)) = (ptr.is_null(), Layout::from_size_align(len.max(1), 8)) {
        // SAFETY: the caller's promise
        unsafe { dealloc(ptr, layout) }
    }
}

/// # Safety
/// `ptr` names `len` readable bytes (or `len` is 0); the slice is not kept.
unsafe fn read<'a, T>(ptr: *const T, len: usize) -> &'a [T] {
    if len == 0 || ptr.is_null() || !(ptr as usize).is_multiple_of(align_of::<T>()) {
        return &[];
    }
    // SAFETY: the caller's promise, and the alignment checked above
    unsafe { std::slice::from_raw_parts(ptr, len) }
}

/// # Safety
/// `ptr` names room for `len` values of `T`, written by nothing else meanwhile.
unsafe fn write<'a, T>(ptr: *mut T, len: usize) -> Option<&'a mut [T]> {
    if len == 0 {
        return Some(&mut []);
    }
    if ptr.is_null() || !(ptr as usize).is_multiple_of(align_of::<T>()) {
        return None;
    }
    // SAFETY: the caller's promise, and the alignment checked above
    Some(unsafe { std::slice::from_raw_parts_mut(ptr, len) })
}

/// A batch of `count` texts — UTF-8 at `ptr`, separated by U+001F; its number, or 0 when the texts are not what is said.
///
/// # Safety
/// `ptr` names `len` readable bytes.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn tc_batch(ptr: *const u8, len: usize, count: usize) -> u32 {
    // SAFETY: the caller's promise
    let texts = unsafe { read(ptr, len) };
    let (true, Ok(batch)) = (texts.len() == len, Batch::from_utf8(texts, count)) else {
        return 0;
    };
    HELD.with(|held| {
        let mut held = held.borrow_mut();
        let id = held.next;
        held.next = held.next.checked_add(1).unwrap_or(1);
        held.batches.push((id, batch));
        if held.batches.len() > KEEP {
            held.batches.remove(0);
        }
        id
    })
}

/// Lets a batch go.
#[unsafe(no_mangle)]
pub extern "C" fn tc_batch_free(id: u32) {
    HELD.with(|held| held.borrow_mut().batches.retain(|(i, _)| *i != id));
}

/// The sum of a batch's lengths (exact: under 2^53), or -1.
#[unsafe(no_mangle)]
pub extern "C" fn tc_total(id: u32) -> f64 {
    with_batch(id, |b| Some(b.total_length() as f64)).unwrap_or(-1.0)
}

/// BM25's first step: the query's tokens — UTF-8 at `ptr`, separated by '\n' (no bytes: no token) — counted in each
/// document of the batch; each distinct token's df, in the order of first appearance, written to `df` (room for
/// `room`).  Returns their number, or -1.
///
/// # Safety
/// `ptr` names `len` readable bytes, `df` room for `room` f64.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn tc_count(id: u32, ptr: *const u8, len: usize, df: *mut f64, room: usize) -> i32 {
    // SAFETY: the caller's promise
    let bytes = unsafe { read(ptr, len) };
    let (true, Ok(text)) = (bytes.len() == len, std::str::from_utf8(bytes)) else {
        return -1;
    };
    let tokens: Result<Vec<Token>, _> =
        if text.is_empty() { Ok(Vec::new()) } else { text.split('\n').map(Token::parse).collect() };
    let Ok(tokens) = tokens else {
        return -1;
    };
    with_batch(id, |b| {
        let counts = b.count(&tokens);
        // SAFETY: the caller's promise
        let out = unsafe { write(df, room) }?;
        let out = out.get_mut(..counts.len())?;
        for (o, c) in out.iter_mut().zip(&counts) {
            *o = *c as f64;
        }
        i32::try_from(counts.len()).ok()
    })
    .unwrap_or(-1)
}

fn put(scored: Vec<Scored>, places: *mut u32, scores: *mut f64, room: usize) -> Option<i32> {
    // SAFETY: the caller's promise (tc_bm25, tc_dense)
    let (p, s) = unsafe { (write(places, room)?, write(scores, room)?) };
    for (i, (place, score)) in scored.iter().enumerate() {
        *p.get_mut(i)? = *place;
        *s.get_mut(i)? = *score;
    }
    i32::try_from(scored.len()).ok()
}

/// BM25's second step: the `k` best documents scoring above 0 for the counted query, given each distinct token's idf
/// (`width` of them, in tc_count's order) and the average length; their places and scores written to `places` and
/// `scores` (room for `k` each).  Returns how many, or -1.
///
/// # Safety
/// `idf` names `width` readable f64; `places` and `scores` room for `k` values each.
#[unsafe(no_mangle)]
#[allow(clippy::too_many_arguments)]
pub unsafe extern "C" fn tc_bm25(
    id: u32,
    idf: *const f64,
    width: usize,
    avgdl: f64,
    k1: f64,
    b: f64,
    k: usize,
    places: *mut u32,
    scores: *mut f64,
) -> i32 {
    // SAFETY: the caller's promise
    let idf = unsafe { read(idf, width) };
    if idf.len() != width {
        return -1;
    }
    with_batch(id, |batch| put(batch.bm25(idf, avgdl, k1, b, k).ok()?, places, scores, k)).unwrap_or(-1)
}

/// The dense route over the batch's documents at `docs` (`count` places): the `k` best cosines above `threshold` with
/// the query (UTF-8 at `query`), embedded as HashingEmbedder(dim, ngram) does — `ngram` names `sizes` n-gram sizes —
/// and summed as Python's compensated sum (`compensated` 1) or its plain one (0).  Places and cosines written to
/// `places` and `scores` (room for `k` each).  Returns how many, or -1.
///
/// # Safety
/// `docs` names `count` readable u32, `query` `query_len` bytes, `ngram` `sizes` u32; `places` and `scores` room for `k`
/// values each.
#[unsafe(no_mangle)]
#[allow(clippy::too_many_arguments)]
pub unsafe extern "C" fn tc_dense(
    id: u32,
    docs: *const u32,
    count: usize,
    query: *const u8,
    query_len: usize,
    dim: usize,
    ngram: *const u32,
    sizes: usize,
    compensated: u32,
    threshold: f64,
    k: usize,
    places: *mut u32,
    scores: *mut f64,
) -> i32 {
    // SAFETY: the caller's promise
    let (docs, query, ngram) = unsafe { (read(docs, count), read(query, query_len), read(ngram, sizes)) };
    if docs.len() != count || query.len() != query_len || ngram.len() != sizes {
        return -1;
    }
    let Ok(query) = std::str::from_utf8(query) else {
        return -1;
    };
    let ngram: Vec<usize> = ngram.iter().map(|&n| n as usize).collect();
    let sum = match compensated {
        1 => Sum::Compensated,
        0 => Sum::Plain,
        _ => return -1,
    };
    let Ok(embedding) = Embedding::new(dim, &ngram, sum) else {
        return -1;
    };
    CACHE
        .with(|cache| {
            let mut cache = cache.borrow_mut();
            let cache = cache.get_or_insert_with(|| GramCache::new(CACHE_BITS));
            with_batch(id, |batch| {
                put(batch.dense(docs, query, &embedding, threshold, k, cache).ok()?, places, scores, k)
            })
        })
        .unwrap_or(-1)
}

/// The full-text index's tokens (store.py's `grams`) of `count` texts — UTF-8 at `ptr`, separated by U+001F — kept until
/// the next call as UTF-8, separated the same way ([`tc_result`], [`tc_result_len`]).  Returns 0, or -1 when the texts are
/// not what is said.
///
/// # Safety
/// `ptr` names `len` readable bytes.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn tc_grams(ptr: *const u8, len: usize, count: usize) -> i32 {
    // SAFETY: the caller's promise
    let bytes = unsafe { read(ptr, len) };
    let (true, Ok(texts)) = (bytes.len() == len, std::str::from_utf8(bytes)) else {
        return -1;
    };
    match taocore::grams_many(texts, count) {
        Ok(out) => {
            RESULT.with(|r| *r.borrow_mut() = out);
            0
        }
        Err(_) => -1,
    }
}

/// Where the last [`tc_grams`] result is in this module's memory.
#[unsafe(no_mangle)]
pub extern "C" fn tc_result() -> *const u8 {
    RESULT.with(|r| r.borrow().as_ptr())
}

/// How many bytes the last [`tc_grams`] result is.
#[unsafe(no_mangle)]
pub extern "C" fn tc_result_len() -> usize {
    RESULT.with(|r| r.borrow().len())
}
