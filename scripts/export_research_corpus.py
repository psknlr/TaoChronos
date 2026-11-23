#!/usr/bin/env python3
"""Export every row of cloud/store.json's verified store; Python stdlib only.

This script reads Cloudflare KV, never writes to it. It does not import TaoChronos,
rebuild the store, apply normalisation, select website works or filter layers/dates.
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import datetime as dt
import gzip
import hashlib
import json
import lzma
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from urllib import error, parse, request

CHUNK = 1024 * 1024
SHA256 = re.compile(r"^[0-9a-f]{64}$")
PART_NAME = re.compile(r"^part-[0-9]{3,}$")
PARSER_VERSION = "research-full-store-export-v1"


class ExportError(RuntimeError):
    """A safe-to-log error, without credentials, response bodies or URLs."""


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def file_record(path):
    path = Path(path)
    return {"bytes": path.stat().st_size, "sha256": sha_file(path)}


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def verify_file(path, expected_bytes, expected_sha, label):
    result = file_record(path)
    if result["bytes"] != expected_bytes:
        raise ExportError(f"{label}: byte count mismatch")
    if result["sha256"] != expected_sha:
        raise ExportError(f"{label}: SHA-256 mismatch")
    return result


def validate_manifest(m):
    if m.get("format") != 1 or m.get("encoding") != "xz":
        raise ExportError("Unsupported manifest format or compression")
    for field in ("sha256", "raw_sha256"):
        if not isinstance(m.get(field), str) or not SHA256.fullmatch(m[field]):
            raise ExportError(f"Invalid manifest {field}")
    for field in ("bytes", "raw_bytes", "books", "passages", "characters"):
        if type(m.get(field)) is not int or m[field] < 0:
            raise ExportError(f"Invalid manifest {field}")
    if m.get("key") != f"store/{m['sha256']}/":
        raise ExportError("Unexpected content-addressed KV key")
    parts = m.get("parts")
    if not isinstance(parts, list) or not parts:
        raise ExportError("Manifest has no parts")
    names = set()
    for part in parts:
        name = part.get("name", "")
        if not PART_NAME.fullmatch(name) or name in names:
            raise ExportError("Invalid or duplicate part name")
        names.add(name)
        if type(part.get("bytes")) is not int or part["bytes"] <= 0:
            raise ExportError("Invalid part byte count")
        if not isinstance(part.get("sha256"), str) or not SHA256.fullmatch(part["sha256"]):
            raise ExportError("Invalid part SHA-256")
    if sum(p["bytes"] for p in parts) != m["bytes"]:
        raise ExportError("Part lengths do not sum to archive length")
    return m


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ExportError("Cloudflare redirect rejected")


class CloudflareKV:
    """Read-only Cloudflare API client, with namespace-list pagination."""

    def __init__(self, account, token, opener=None, sleep=time.sleep):
        if not account or not re.fullmatch(r"[A-Za-z0-9_-]+", account) or not token:
            raise ExportError("Required Cloudflare environment variables are missing or invalid")
        self.base = f"https://api.cloudflare.com/client/v4/accounts/{account}/storage/kv/namespaces"
        self.token = token
        self.opener = opener or request.build_opener(NoRedirect())
        self.sleep = sleep

    def _read(self, url, destination=None, maximum_bytes=None):
        for attempt in range(3):
            req = request.Request(url, headers={"Authorization": f"Bearer {self.token}", "User-Agent": PARSER_VERSION}, method="GET")
            try:
                with self.opener.open(req, timeout=120) as response:
                    if destination is None:
                        data = response.read(4 * CHUNK + 1)
                        if len(data) > 4 * CHUNK:
                            raise ExportError("Cloudflare JSON response exceeds size limit")
                        return data
                    size = 0
                    with Path(destination).open("wb") as output:
                        while True:
                            chunk = response.read(CHUNK)
                            if not chunk:
                                break
                            size += len(chunk)
                            if maximum_bytes is not None and size > maximum_bytes:
                                raise ExportError("Cloudflare part exceeds manifest length")
                            output.write(chunk)
                    return None
            except error.HTTPError as exc:
                # Do not print exc, its URL, request headers, or the response body.
                if (exc.code == 429 or exc.code >= 500) and attempt < 2:
                    self.sleep(2 ** attempt)
                    continue
                raise ExportError(f"Cloudflare read failed with HTTP {exc.code}") from None
            except (error.URLError, TimeoutError, OSError):
                if attempt < 2:
                    self.sleep(2 ** attempt)
                    continue
                raise ExportError("Cloudflare read failed after retries") from None
        raise ExportError("Cloudflare read failed")

    def namespace(self, title):
        found = []
        for page in range(1, 10001):
            raw = self._read(self.base + "?" + parse.urlencode({"page": page, "per_page": 100}))
            try:
                body = json.loads(raw)
            except (ValueError, UnicodeError):
                raise ExportError("Cloudflare namespace response is not JSON") from None
            if body.get("success") is not True or not isinstance(body.get("result"), list):
                raise ExportError("Cloudflare namespace listing was unsuccessful")
            result = body["result"]
            found.extend(row.get("id") for row in result if row.get("title") == title)
            pages = body.get("result_info", {}).get("total_pages")
            if (isinstance(pages, int) and page >= pages) or (pages is None and len(result) < 100):
                break
        else:
            raise ExportError("Cloudflare namespace pagination exceeded limit")
        if len(found) != 1 or not isinstance(found[0], str) or not re.fullmatch(r"[A-Za-z0-9_-]+", found[0]):
            raise ExportError("Expected exactly one matching Cloudflare KV namespace")
        return found[0]

    def download(self, namespace, key, target, expected_bytes):
        # Encode the complete KV key, including every slash; no request to a site API.
        url = self.base + "/" + parse.quote(namespace, safe="") + "/values/" + parse.quote(key, safe="")
        self._read(url, target, maximum_bytes=expected_bytes)


def acquire_archive(manifest, client, namespace_title, work_dir):
    validate_manifest(manifest)
    work_dir = Path(work_dir)
    namespace = client.namespace(namespace_title)
    archive = work_dir / "raw_verified.sqlite.xz"
    part_records = []
    with archive.open("wb") as out:
        for part in manifest["parts"]:
            path = work_dir / part["name"]
            client.download(namespace, manifest["key"] + part["name"], path, part["bytes"])
            result = verify_file(path, part["bytes"], part["sha256"], part["name"])
            with path.open("rb") as src:
                shutil.copyfileobj(src, out, CHUNK)
            part_records.append({"name": part["name"], **result})
            path.unlink()
    verify_file(archive, manifest["bytes"], manifest["sha256"], "assembled archive")
    return archive, part_records


def unpack_verified(archive, manifest, destination):
    verify_file(archive, manifest["bytes"], manifest["sha256"], "archive")
    destination = Path(destination)
    n = 0
    try:
        with lzma.open(archive, "rb") as src, destination.open("wb") as out:
            for chunk in iter(lambda: src.read(CHUNK), b""):
                n += len(chunk)
                if n > manifest["raw_bytes"]:
                    raise ExportError("Expanded store exceeds manifest length")
                out.write(chunk)
    except (lzma.LZMAError, EOFError):
        raise ExportError("Archive decompression failed or was truncated") from None
    verify_file(destination, manifest["raw_bytes"], manifest["raw_sha256"], "expanded store")
    with destination.open("rb") as stream:
        if stream.read(16) != b"SQLite format 3\x00":
            raise ExportError("Expanded store is not a SQLite database")
    destination.chmod(0o444)
    return destination


def open_readonly(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise ExportError("SQLite input does not exist")
    db = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    db.execute("PRAGMA trusted_schema=OFF")
    return db


def json_field(value, label, expected=dict):
    if value is None:
        return None
    try:
        decoded = json.loads(value)
    except (ValueError, TypeError):
        raise ExportError(f"Invalid JSON in {label}") from None
    if not isinstance(decoded, expected):
        raise ExportError(f"Unexpected JSON type in {label}")
    return decoded


@contextlib.contextmanager
def gz_writer(path):
    # gzip mtime=0 and no embedded filename keep identical export bytes reproducible.
    with Path(path).open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            yield compressed


def source_counts(db):
    return {row[0]: {"books": row[1], "passages": row[2], "characters": row[3]}
            for row in db.execute("""SELECT b.source, COUNT(DISTINCT b.id), COUNT(p.id),
                 COALESCE(SUM(LENGTH(p.text)),0) FROM books b LEFT JOIN passages p
                 ON p.book_id=b.id GROUP BY b.source ORDER BY b.source""")}


def export_sqlite(db_path, manifest, export_dir):
    """Stream ALL books/passages, retaining raw database columns and decoded JSON."""
    export_dir = Path(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    db = open_readonly(db_path)
    try:
        check = db.execute("PRAGMA integrity_check").fetchall()
        if [row[0] for row in check] != ["ok"]:
            raise ExportError("SQLite integrity_check failed")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"books", "passages"}.issubset(tables):
            raise ExportError("Required corpus tables are absent")
        cols = {row[1] for row in db.execute("PRAGMA table_info(passages)")}
        required = {"rid", "id", "book_id", "seq", "kind", "layer", "text", "locator", "temporal", "extra"}
        if not required.issubset(cols):
            raise ExportError("Corpus passage schema is incompatible")
        actual = {
            "books": db.execute("SELECT COUNT(*) FROM books").fetchone()[0],
            "passages": db.execute("SELECT COUNT(*) FROM passages").fetchone()[0],
            "characters": db.execute("SELECT COALESCE(SUM(LENGTH(text)),0) FROM passages").fetchone()[0],
        }
        for field, count in actual.items():
            if count != manifest[field]:
                raise ExportError(f"Observed {field} do not match manifest")
        if db.execute("SELECT COUNT(DISTINCT id) FROM passages").fetchone()[0] != actual["passages"]:
            raise ExportError("Duplicate or missing original passage IDs")
        if db.execute("SELECT COUNT(*) FROM passages p LEFT JOIN books b ON b.id=p.book_id WHERE b.id IS NULL").fetchone()[0]:
            raise ExportError("Passages without registered books")
        observed_sources = source_counts(db)
        if "sources" in manifest and observed_sources != manifest["sources"]:
            raise ExportError("Observed per-source counts do not match manifest")
        book_count = 0
        source_registry = []
        with (export_dir / "books.jsonl").open("w", encoding="utf-8", newline="\n") as out:
            for row in db.execute("SELECT * FROM books ORDER BY id"):
                record = dict(row)
                raw = json_field(record["data"], "book data")
                if raw.get("id") != record["id"]:
                    raise ExportError("Book row and embedded original ID disagree")
                record["data_parsed"] = raw
                out.write(dump(record) + "\n")
                book_count += 1
                source_registry.append({"book_id": record["id"], "source_registry_key": record.get("source"),
                                        "source_info": raw.get("source"), "title": raw.get("title"),
                                        "work": raw.get("work"), "editions": raw.get("editions", []),
                                        "permission_status": "source metadata preserved; no new redistribution permission inferred"})
        passages = characters = 0
        kind_counts = collections.Counter()
        layer_counts = collections.Counter()
        clock_present = collections.Counter()
        with gz_writer(export_dir / "passages.jsonl.gz") as out:
            # No WHERE clause, date boundary, layer exclusion, website selector or LIMIT.
            for row in db.execute("SELECT * FROM passages ORDER BY rid"):
                original = dict(row)
                text = original["text"]
                if not isinstance(text, str):
                    raise ExportError("A source passage does not contain original string text")
                record = dict(original)
                for field in ("locator", "temporal", "extra"):
                    record[field + "_parsed"] = json_field(original[field], "passage " + field)
                record["raw_text"] = text
                record["text_sha256_utf8"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
                record["original_row_sha256"] = hashlib.sha256(dump(original).encode("utf-8")).hexdigest()
                out.write((dump(record) + "\n").encode("utf-8"))
                passages += 1
                characters += len(text)
                kind_counts[str(original["kind"])] += 1
                layer_counts[str(original["layer"])] += 1
                temporal = record["temporal_parsed"] or {}
                for clock in ("t_author", "t_composition", "t_edition", "t_citation"):
                    clock_present[clock] += int(temporal.get(clock) is not None)
        if {"books": book_count, "passages": passages, "characters": characters} != actual:
            raise ExportError("Streamed export does not align with database counts")
        with (export_dir / "source_license_registry.jsonl").open("w", encoding="utf-8", newline="\n") as out:
            for record in source_registry:
                out.write(dump(record) + "\n")
        optional_counts = {}
        for table, filename in (("meta", "store_meta.jsonl"), ("external", "external_works.jsonl")):
            count = 0
            with (export_dir / filename).open("w", encoding="utf-8", newline="\n") as out:
                if table in tables:
                    order = "key" if table == "meta" else "id"
                    for row in db.execute(f'SELECT * FROM "{table}" ORDER BY "{order}"'):
                        out.write(dump(dict(row)) + "\n")
                        count += 1
            optional_counts[table] = count
        return {**actual, "sources": observed_sources, "kinds": dict(sorted(kind_counts.items())),
                "layers": dict(sorted(layer_counts.items())), "temporal_clock_nonnull_counts": dict(clock_present),
                "optional_table_rows": optional_counts,
                "schema_columns": [row[1] for row in db.execute("PRAGMA table_info(passages)")],
                "sqlite_integrity_check": "ok", "read_only": True, "original_text_normalised": False,
                "all_rows_exported": True, "selection_filter": None}
    finally:
        db.close()


def run_export(manifest_path, output_dir, client, namespace_title="taochronos-store", repo_root=None, commit=None):
    manifest_path = Path(manifest_path)
    output_dir = Path(output_dir)
    # Refuse to overwrite an older verified export or mix snapshots.
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        raise ExportError("Output directory must be empty")
    failures_path = output_dir / "failures.jsonl"
    failures_path.touch()
    stage_name = "manifest"
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = validate_manifest(json.loads(manifest_bytes))
        with tempfile.TemporaryDirectory(prefix="taochronos-export-") as temp:
            stage = Path(temp)
            stage_name = "read_only_cloudflare_download"
            archive, parts = acquire_archive(manifest, client, namespace_title, stage)
            stage_name = "archive_and_raw_hash_verification"
            db_path = unpack_verified(archive, manifest, stage / "verified.sqlite")
            stage_name = "all_row_streaming_export"
            exports = stage / "exports"
            exports.mkdir()
            observed = export_sqlite(db_path, manifest, exports)
            shutil.copyfile(archive, exports / "raw_verified.sqlite.xz")
            (exports / "master_manifest.json").write_bytes(manifest_bytes)
            copied_metadata = []
            if repo_root:
                root = Path(repo_root)
                for source, destination in (("cloud/ATTRIBUTION.md", "source_ATTRIBUTION.md"),
                                            ("corpus/sources.lock.yaml", "source_versions.lock.yaml")):
                    if (root / source).is_file():
                        shutil.copyfile(root / source, exports / destination)
                        copied_metadata.append({"repository_path": source, "artifact_path": destination})
            provenance = {
                "format": 1, "exporter_version": PARSER_VERSION,
                "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "repository": os.environ.get("GITHUB_REPOSITORY"),
                "code_commit": commit, "git_ref": os.environ.get("GITHUB_REF"),
                "workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
                "master_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                "manifest_counts_verified": True, "observed": observed,
                "part_verification": parts, "raw_database_sha256": manifest["raw_sha256"],
                "verified_archive_sha256": manifest["sha256"],
                "scope": "every row of the full store identified by cloud/store.json; not a site-selected subset",
                "upstream_excluded_sources": manifest.get("excluded", {}),
                "scope_limitation": "Sources excluded from this archive are unavailable here; this export does not recover them.",
                "source_metadata_files": copied_metadata,
                "sharing": "Private repository Actions artifact only; no public release or site publication. Source-specific permissions remain applicable.",
                "outputs": {p.name: file_record(p) for p in sorted(exports.iterdir())},
                "failures": 0,
            }
            write_json(exports / "export_provenance.json", provenance)
            stage_name = "publish_verified_local_artifact"
            for path in exports.iterdir():
                shutil.move(str(path), output_dir / path.name)
        write_json(output_dir / "completion.json", {"status": "complete", "manifest_counts_verified": True,
                    "books": observed["books"], "passages": observed["passages"], "characters": observed["characters"]})
        return provenance
    except Exception as exc:
        # Unexpected library errors are deliberately sanitised; credentials may be
        # present in HTTP objects. The failure stage/type remains actionable.
        message = str(exc) if isinstance(exc, ExportError) else "Export failed; inspect input validity and stage"
        with failures_path.open("a", encoding="utf-8") as out:
            out.write(dump({"stage": stage_name, "error_type": type(exc).__name__, "message": message}) + "\n")
        write_json(output_dir / "completion.json", {"status": "failed", "stage": stage_name, "message": message})
        raise ExportError(message) from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("cloud/store.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--namespace-title", default="taochronos-store")
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--commit", default=os.environ.get("GITHUB_SHA"))
    args = parser.parse_args(argv)
    try:
        client = CloudflareKV(os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""), os.environ.get("CLOUDFLARE_API_TOKEN", ""))
        result = run_export(args.manifest, args.output, client, args.namespace_title, args.repository_root, args.commit)
        print(dump({"status": "complete", **{k: result["observed"][k] for k in ("books", "passages", "characters")}}))
        return 0
    except ExportError as exc:
        # Credential/configuration failure can precede run_export; still retain a
        # safe ledger, without overwriting any previous nonempty export.
        if not args.output.exists() or not any(args.output.iterdir()):
            args.output.mkdir(parents=True, exist_ok=True)
            (args.output / "failures.jsonl").write_text(dump({"stage": "configuration", "error_type": "ExportError", "message": str(exc)}) + "\n", encoding="utf-8")
            write_json(args.output / "completion.json", {"status": "failed", "stage": "configuration", "message": str(exc)})
        print("Research corpus export failed: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
