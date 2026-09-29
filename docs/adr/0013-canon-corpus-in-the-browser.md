# ADR 0013 — 要籍语料 in the browser: all 350 works, loaded in the order a visitor waits for them

**Status:** accepted · 2026-09-28 · supersedes the corpus part of [ADR 0011](0011-web-client.md)

## Context

The published page ran on the openly licensed texts of 108 of the 350 key works (4.1 million characters).  IMPF-AI asked for
all 350 by default — the works are all in the public domain — and found the page slow to load.  Measured, it was slow for a
reason of its own: the site is served over http:// until its certificate is issued, and an http page has no Cache API, so
every visit downloaded the runtime and the corpus again and rebuilt the full-text index (about 10 seconds of 17 on a fast
machine, far more on a slow one).

The 350 works whole are 57 million characters: as a store with its index, some 800 MB.  No browser downloads or indexes
that on opening a page, and the runtime's tools read a store as if it were local (a trace of their reads through a lazily
fetched file showed them scanning most of it), so fetching pages on demand would not rescue it.  All the books, and the
works whole, are for `taochronos serve`.

## Decision

1. **Every ranked work, the first whole.**  `taochronos web pack` takes each of the 350 from the best witness the site may
   carry (`WEB_SOURCES`: the openly licensed first, then 笈成 and the collections transcribed from it), within the budget
   by rank that the pack already had (the first ten whole within 350 000 characters, with up to three witnesses; then 50 000,
   25 000 and 12 000, as whole chapters spread through the book): 348 works, 8.5 million characters.  The transcriptions of
   笈成 declare no licence and their punctuation is their editors': the site carries them because IMPF-AI decided so, and
   each record and the attribution say on what terms.  *(Corrected 2026-09-29: 笈成 releases its editorial work under
   CC0 1.0 — see the addendum.)*  Sources whose terms forbid passing their texts on (`NEVER_PACKED`)
   are never packed; the two works known only through them are listed without text.
2. **Smaller, and unpacked as it arrives.**  The store ships without its index (two thirds of an indexed download, and it
   compresses badly), xz-compressed: 10.8 MB where gzip would be 17.  It downloads while Python starts and is unpacked
   (xzwasm) into the runtime's file system as the bytes arrive.
3. **Indexed in the order a visitor waits for it.**  The pack is in rank order; the worker indexes the works ranked up to 40
   (52 % of the passages) before the runtime answers, the rest in slices between questions.  Every book's text is there
   from the start; only the search of the later works follows, seconds later.  The index is resumable
   (`index_store(phase, limit)`), and the runtime's connection sees what the indexing connection adds (the store keeps a
   rollback journal in the browser; SQLite checks the file's change counter on each read).
4. **Kept where an http page can keep it.**  Once indexed, the store is kept in IndexedDB — which an http page has — in
   16 MB parts, the head written last, keyed by the corpus's hash: a later visit downloads and indexes nothing.
5. **The conversation does not wait for the runtime.**  The build computes what the runtime will report — its info, with the
   standing instructions, and its tool catalogs — on the same code and corpus (`runtime/boot.json`); the page asks the model
   at once and only the tools the model calls wait for the runtime.

## Consequences

- First visit, fast machine: ready in 15 s (the rest indexed 10 s later), with twice the corpus of before (17 s); a return
  visit, 6 s.  Throttled to 1 MB/s and 150 ms: 40 s and 16 s.  The first question goes to the model at once either way.
- A browser that keeps no site data (a private window) indexes on every visit; one with little memory may struggle with a
  90 MB store — `taochronos serve` remains the way to all the books and to the works whole.
- The repository carries a 13 MB pack instead of 7 MB; the build takes about 40 s more (xz), the tests compress fast
  (`TAOCHRONOS_WEB_XZ_PRESET=1`).
- The page loads faster still once https is on and when served from a CDN near its readers (Cloudflare in front of
  chat.impf.ai): neither changes this design.

## Addendum — 2026-09-29: 笈成 is openly licensed

The premise of decision 1 was wrong.  中醫笈成's copyright statement ([著作權聲明](https://jicheng.tw/tcm/copyright.html),
checked 2026-09-29) releases all the site's editing of public-domain texts — selection, arrangement, punctuation,
annotation — under CC0 1.0, and its own writing (introductions, help and data pages) under CC BY 4.0, free to use when
the site is credited; individual pages may declare other terms, embedded images and media may carry other licences, and
the site does not guarantee every marking.  笈成 is now an open source (`OPEN_SOURCES`, last, so that the preference
among the others and the order of `WEB_SOURCES` are unchanged): its records keep their own licence in the pack, and 344
of the 350 have an openly licensed witness (`open` in `canon.yaml`, 108 before).  The pack's choice of witnesses is
unchanged.  The decision of 2026-09-28 now carries only what that licence does not: the four works known only through
TCM-Ancient-Books, whose repository declares no licence (a copy of a 笈成 text is never stored, so these four match no
笈成 text in the store), and the modern editors' part of the 笈成 texts that follow a modern edition — the 今人辑校本 of
lost works (集验方, 名医别录, 食疗本草, 小品方, 吴普本草, 海药本草, 新修本草) among them — which 笈成's CC0 cannot release.
