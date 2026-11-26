//! `_taocore`: TaoCore for CPython.  Only the retrieval plugin imports it (src/taochronos/plugins/retrieval/taocore.py),
//! and only through a facade that falls back to the Python definitions whenever this module is absent, refuses its
//! input, or disagrees with them on the self-test.  Every error and every panic comes out as an ordinary exception
//! (ValueError, RuntimeError), which the facade catches.
//!
//! The work runs with the GIL held: a search's two calls take milliseconds, where the Python they replace held it for
//! hundreds; the n-gram cache is the process's own, behind a lock no one else waits on.

use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::Mutex;

use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;

use taocore::{Embedding, GramCache, Sum, Token};

/// 2^19 places (8 MB): a search's 1,500 passages hold up to ~180,000 distinct n-grams, and 70% of the table 367,000 —
/// room for the next search's too.
const CACHE_BITS: u32 = 19;

static CACHE: Mutex<Option<GramCache>> = Mutex::new(None);

fn guarded<T>(work: impl FnOnce() -> Result<T, taocore::Error>) -> PyResult<T> {
    match catch_unwind(AssertUnwindSafe(work)) {
        Ok(Ok(value)) => Ok(value),
        Ok(Err(err)) => Err(PyValueError::new_err(err.to_string())),
        Err(_) => Err(PyRuntimeError::new_err("taocore: an internal error (a panic)")),
    }
}

fn split(scored: Vec<taocore::Scored>) -> (Vec<u32>, Vec<f64>) {
    scored.into_iter().unzip()
}

/// A search's candidates, read once: `Batch(texts, count)` with the texts as UTF-8, separated by U+001F.
#[pyclass(module = "_taocore")]
struct Batch {
    inner: taocore::Batch,
}

#[pymethods]
impl Batch {
    #[new]
    fn new(texts: &[u8], count: usize) -> PyResult<Self> {
        guarded(|| taocore::Batch::from_utf8(texts, count)).map(|inner| Batch { inner })
    }

    fn __len__(&self) -> usize {
        self.inner.len()
    }

    /// BM25's first step: the query's tokens (each one or two kept characters, a repeated one counting each time)
    /// counted in every document.  Returns (df of each distinct token in the order of first appearance, the sum of the
    /// documents' lengths).
    fn count(&mut self, tokens: Vec<String>) -> PyResult<(Vec<u64>, u64)> {
        let inner = &mut self.inner;
        guarded(|| {
            let query = tokens.iter().map(|t| Token::parse(t)).collect::<Result<Vec<_>, _>>()?;
            let df = inner.count(&query);
            Ok((df, inner.total_length()))
        })
    }

    /// BM25's second step: (places, scores) of the `k` best documents scoring above 0, given each distinct token's idf
    /// in `count`'s order and the average length.
    fn bm25(&self, idf: Vec<f64>, avgdl: f64, k1: f64, b: f64, k: usize) -> PyResult<(Vec<u32>, Vec<f64>)> {
        guarded(|| self.inner.bm25(&idf, avgdl, k1, b, k)).map(split)
    }

    /// The dense route over the documents at `docs`: (places, cosines) of the `k` best above `threshold`, the query
    /// (UTF-8) embedded as HashingEmbedder(dim, ngram) does, with Python's compensated sum or its plain one.
    #[allow(clippy::too_many_arguments)]
    fn dense(
        &self,
        docs: Vec<u32>,
        query: &[u8],
        dim: usize,
        ngram: Vec<usize>,
        compensated: bool,
        threshold: f64,
        k: usize,
    ) -> PyResult<(Vec<u32>, Vec<f64>)> {
        guarded(|| {
            let query = std::str::from_utf8(query).map_err(|_| taocore::Error::Utf8)?;
            let embedding = Embedding::new(dim, &ngram, if compensated { Sum::Compensated } else { Sum::Plain })?;
            let mut held = CACHE.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
            let cache = held.get_or_insert_with(|| GramCache::new(CACHE_BITS));
            self.inner.dense(&docs, query, &embedding, threshold, k, cache)
        })
        .map(split)
    }
}

/// The full-text index's tokens (store.py's `grams`) of `count` texts — UTF-8, separated by U+001F — separated the same way.
#[pyfunction]
fn grams(texts: &[u8], count: usize) -> PyResult<String> {
    guarded(|| taocore::grams_many(std::str::from_utf8(texts).map_err(|_| taocore::Error::Utf8)?, count))
}

#[pymodule]
fn _taocore(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("ABI", taocore::ABI)?;
    m.add("VERSION", env!("CARGO_PKG_VERSION"))?;
    m.add_class::<Batch>()?;
    m.add_function(wrap_pyfunction!(grams, m)?)?;
    Ok(())
}
