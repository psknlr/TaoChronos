# Private full-store export for TaoStroke research

This temporary research PR exports every book and passage row from the immutable
SQLite archive identified by `cloud/store.json`. **Do not merge this PR into
`main`.** Keep it on a branch named `codex/taostroke-corpus-export-*`. Pushing the
branch starts the new workflow without changing `main`, deploying the site,
writing Cloudflare data, creating a public release or committing corpus data.
The export job only runs inside the private `psknlr/TaoChronos` repository, on the
specified branch prefix. It does not run on fork or pull-request events.

The workflow reuses the existing `CLOUDFLARE_API_TOKEN` and
`CLOUDFLARE_ACCOUNT_ID` repository secrets. They appear only in the read step's
environment. No values, request headers, response bodies or Cloudflare URLs are
printed. Namespace discovery is paginated; the exact title `taochronos-store`
must identify one namespace. All Cloudflare operations are HTTP GET requests.

## What the artifact contains

The workflow uploads a repository-access-controlled GitHub Actions artifact with
a seven-day retention period. It is not a public release, site asset or blanket
permission to redistribute source texts. Download it while logged into an
account with access to this private repository. Do not change repository
visibility or publish artifact download URLs. Source-specific licenses and
permissions continue to apply; complete user review is deferred until the
research results and outputs are ready for review.

- `raw_verified.sqlite.xz`: the original archive, unchanged, after per-part and
  whole-archive byte-count/SHA-256 verification; its expanded SQLite bytes have
  also matched the manifest's raw length and SHA-256.
- `passages.jsonl.gz`: every passage row, in `rid` order. There is no date,
  textual-layer, genre, kind, book or website selection. Original IDs, text,
  temporal and locator JSON strings, and all database columns are preserved.
  Additional decoded JSON fields retain the author, composition, edition and
  citation clocks; they do not fill missing dates. `raw_text` equals `text`,
  `text_sha256_utf8` anchors that exact string, and `original_row_sha256`
  fingerprints the original row represented as sorted compact UTF-8 JSON.
- `books.jsonl`: every original book row, with the original `data` JSON string
  and its decoded `data_parsed` object.
- `source_license_registry.jsonl`: each book's original source information,
  source key, title, work identity and editions. Missing permission statements
  remain missing; the exporter does not infer new permission.
- `master_manifest.json`, `export_provenance.json`: the exact input manifest,
  exporter/version/commit/run identifiers, recomputed counts, source strata,
  textual layers, kinds, four-clock completeness, hash records and exclusions.
- `store_meta.jsonl`, `external_works.jsonl`: all rows in these optional tables.
- `source_ATTRIBUTION.md` and `source_versions.lock.yaml`: repository attribution
  and source-lock snapshots, when present at the checked-out commit.
- `failures.jsonl`, `completion.json`: explicit success/failure status. On a
  failed verification, staged corpus/export files do not enter the artifact;
  the failure ledger remains available.

`cloud/store.json` identifies the full distributable cloud store, not every
material ever ingested on a maintainer's machine. The inspected main snapshot
contains 958 bibliographic records, 2,038,497 passages and 122,212,591 characters.
These figures are checked against the actual database, including per-source
counts, rather than hard-coded by the exporter. The manifest excludes AEAM (7)
and hf-tcm-canon (1); those eight unavailable sources cannot be recovered by this
workflow. It is also distinct from the smaller browser-selected pack. Report the
actual artifact's manifest and checksums as the research denominator.

## Checks and failure behavior

Python 3.12 and the standard library are sufficient; no project dependencies are
installed. The exporter validates part names, lengths, hashes and the
content-addressed key before download; validates assembled and expanded bytes;
then opens SQLite with URI `mode=ro&immutable=1`, `query_only=ON` and
`trusted_schema=OFF`. It requires `PRAGMA integrity_check = ok`, valid row JSON,
consistent book IDs, registered passage books and exact master/per-source
counts. Streaming totals must match the database totals, preserving original
text without normalization. The source database is never repaired, indexed or
written.

Before cloud access the workflow runs offline stdlib tests, using a synthetic
SQLite store and a mock HTTP transport. Tests cover all-row export, modern and
table-of-contents layers, four clocks, exact text/ID alignment, read-only access,
count and hash failures, truncation, encoded KV keys, namespace pagination and
safe failure artifacts. These are engineering checks; they do not certify the
historical or medical accuracy of corpus contents.

To run only the offline tests:

```sh
python -m unittest discover -s tests -p test_research_corpus_export.py -v
```

To run an authorized local read with credentials already in the environment:

```sh
python scripts/export_research_corpus.py --manifest cloud/store.json \
  --output research-export --repository-root . --commit "$(git rev-parse HEAD)"
```

The output directory must be empty. Workflow runtime is capped at 30 minutes;
if the manifest no longer matches KV content, the job fails rather than
exporting a different snapshot. A workflow-dispatch listing may require the
workflow to exist on the default branch; the branch push trigger is the initial
execution path and requires no merge. Do not add this workflow to `main` merely
to make the manual-dispatch button visible.
