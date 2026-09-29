# ADR 0015 — The 要籍语料 in the browser starts faster: measured first, then five changes

**Status:** accepted · 2026-09-29 · refines [ADR 0013](0013-canon-corpus-in-the-browser.md)

## Context

IMPF-AI asked for the 350 key works to load faster.  The start was measured in Chromium on the built site, phase by phase,
before anything was changed (a fast machine on a local link; then throttled to 1 MB/s and 150 ms):

| phase | first visit | return visit |
|---|---|---|
| Python starts | 4.0 s | 2.0 s |
| the store unpacked (xz, 90 MB), after Python | 2.8 s | — (read from IndexedDB, 0.2 s) |
| the works ranked up to 40 indexed | 5.7 s | — |
| the runtime built (“建立工具网格”) | 1.8 s | 2.9 s |
| **ready** | **15.3 s** | **6.0 s** |

Profiling the runtime's build under Pyodide showed where its seconds went: parsing 73 YAML files with the pure-Python
loader (the cache of `protocol.yamlio` is off in the browser), compiling some 240 modules from source on every visit, and
counting the whole store for `info` on every visit.  Indexing spent half its time in `grams`, which tested every character
in Python.

Two ideas were measured and set aside.  **Shipping the index**: the indexed store compresses to 32.4 MB against 10.8 MB —
21.6 MB more to download, which a fast link repays in about the time it saves and a 1 MB/s link pays for with 20 s.
**Answering before the index, by scanning**: the search tools (contains, search, near, count, document frequency) all read
the index; a scan standing in for its missing part would have to reproduce each, and BM25 ranks would differ from the
indexed ones.  Faster indexing gains most of the same seconds with neither cost.

## Decision

1. **The YAML comes parsed.**  `taochronos web build` runs the runtime once (for `boot.json`) with the YAML cache on and
   ships the cache in `home.zip` (`.cache/yaml`, 69 entries, pickles of plain data keyed by the SHA-256 of each file's
   bytes — an edited file is another key, so a stale value is never read).  The worker points `TAOCHRONOS_CACHE` at it
   before anything reads the home.  The canon list is read through the same loader.
2. **The store keeps its counts.**  `build_store` records the passages per book, the characters and the passages per year
   (`CorpusStore.count`); `stats` reads them while the store's last passage is still the one counted, and counts as before
   otherwise, or when a scope filters the books.
3. **Bytecode is kept.**  After the first visit's indexing the worker compiles the package to unchecked-hash `.pyc` and
   keeps them in IndexedDB, keyed by the package archive's hash; a later visit unpacks them next to the very sources they
   were compiled from.
4. **Unpacking runs beside Python, not after it.**  A worker of its own (`unpack-worker.js`, helpers in `unpack.js`)
   downloads and unpacks the store into one buffer of its final size and transfers it; the runtime's file system takes the
   buffer without a copy (`FS.write(…, canOwn)`).  Where a worker cannot start another, the old path runs in place.  The
   page starts the runtime first thing, not after its own setup and a 250 ms pause.
5. **Indexing does less work per character.**  `grams` finds the runs of Han characters with one regular expression; its
   output is unchanged (a test compares it with the character-by-character definition on 20 000 random strings and every
   edge case, and it gave the same tokens for every passage of the pack).  Empty fields of locators and temporal contexts are
   no longer stored (every reader takes a missing field for None): 90 → 81 MB unpacked.

## Consequences

Measured the same way after the change (the original build beside it, same machine):

| | before | after |
|---|---|---|
| first visit, ready | 15.4 s | 9.6 s |
| first visit, every work searchable | 24.2 s | 16.3 s |
| return visit | 5.4–5.9 s | 3.9–4.0 s |
| 1 MB/s: first visit ready / all searchable | 39.2 s / 47.0 s | 26.6 s / 33.2 s |
| 1 MB/s: return visit | 15.1–15.7 s | 12.6–14.2 s |

- The download is unchanged (10.7 MB of corpus); a slow link still waits mostly for bytes — a CDN in front of the site
  and https (the Cache API, brotli for the runtime's files) are what would help it next.  Throttled return visits in the
  test re-fetch Pyodide's files through the HTTP cache of the test server; the published site's caching headers decide
  that there.
- Nothing about what is searched, or found, changes: the same index, the same passages, the same counts.
