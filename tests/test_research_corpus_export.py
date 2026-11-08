"""Offline safety/completeness tests. No cloud or TaoChronos dependency."""
import copy
import gzip
import hashlib
import importlib.util
import io
import json
import lzma
from pathlib import Path
import sqlite3
import tempfile
import unittest
from urllib import error

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_research_corpus.py"
spec = importlib.util.spec_from_file_location("research_export", SCRIPT)
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fixture(root):
    db_path = Path(root) / "fixture.sqlite"
    db = sqlite3.connect(db_path)
    db.executescript("""
        CREATE TABLE books(id TEXT PRIMARY KEY, source TEXT, data TEXT NOT NULL);
        CREATE TABLE passages(rid INTEGER PRIMARY KEY, id TEXT UNIQUE, book_id TEXT,
          edition_id TEXT, seq INTEGER, kind TEXT, layer TEXT, year REAL,
          y_start INTEGER, y_end INTEGER, locator TEXT, temporal TEXT, text TEXT,
          punctuation TEXT, extra TEXT);
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE external(id TEXT PRIMARY KEY, data TEXT);
    """)
    for bid, source in (("ancient", "kanripo"), ("recent", "jicheng")):
        raw = {"id": bid, "title": bid, "source": {"origin": source, "license": "fixture-only", "url": "https://example.invalid"}, "work": "work-" + bid,
               "composition": {"start": 100, "end": 200}, "editions": [{"id": bid + "-edition"}]}
        db.execute("INSERT INTO books VALUES(?,?,?)", (bid, source, json.dumps(raw, ensure_ascii=False)))
    temporal = {"t_author": {"start": 100, "end": 120}, "t_composition": {"start": 150, "end": 200},
                "t_edition": {"start": 1800, "end": 1801}, "t_citation": {"start": 125, "end": 130}}
    originals = []
    for index, (bid, kind, layer, text) in enumerate([
        ("ancient", "text", "source", "中風 不可妄治。\n 保留空白 𠀀"),
        ("ancient", "toc", "table-of-contents", "目錄"),
        ("recent", "text", "modern-editorial", "2020年現代校注；不可刪除。"),
    ], 1):
        row = (index, bid + "." + str(index), bid, bid + "-edition", index, kind, layer,
               2020.0 if bid == "recent" else 175.0, 2020 if bid == "recent" else 150,
               2020 if bid == "recent" else 200, json.dumps({"page": str(index), "chapter": "原章"}, ensure_ascii=False),
               json.dumps(temporal, ensure_ascii=False), text, "none", json.dumps({"tags": ["preserve-me"]}))
        db.execute("INSERT INTO passages VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
        originals.append(row)
    db.execute("INSERT INTO meta VALUES('schema_version','1')")
    db.execute("INSERT INTO external VALUES('lost',?)", (json.dumps({"title": "lost work"}),))
    db.commit()
    db.close()
    raw_bytes = db_path.read_bytes()
    packed = lzma.compress(raw_bytes)
    mid = len(packed) // 2
    part_data = [packed[:mid], packed[mid:]]
    m = {"format": 1, "encoding": "xz", "sha256": digest(packed), "bytes": len(packed),
         "raw_sha256": digest(raw_bytes), "raw_bytes": len(raw_bytes),
         "books": 2, "passages": 3, "characters": sum(len(row[12]) for row in originals),
         "parts": [{"name": f"part-{i:03}", "bytes": len(data), "sha256": digest(data)} for i, data in enumerate(part_data)],
         "sources": {"kanripo": {"books": 1, "passages": 2, "characters": sum(len(row[12]) for row in originals[:2])},
                     "jicheng": {"books": 1, "passages": 1, "characters": len(originals[2][12])}},
         "excluded": {"restricted": 1}}
    m["key"] = f"store/{m['sha256']}/"
    return db_path, m, part_data, originals


class FakeKV:
    def __init__(self, parts, mutate=None):
        self.parts = parts
        self.mutate = mutate
        self.keys = []
        self.title = None

    def namespace(self, title):
        self.title = title
        return "ns"

    def download(self, namespace, key, target, expected_bytes):
        self.keys.append(key)
        index = int(key.rsplit("-", 1)[1])
        data = self.parts[index]
        if self.mutate:
            data = self.mutate(index, data)
        Path(target).write_bytes(data)


class FakeOpener:
    def __init__(self, values):
        self.values = iter(values)
        self.requests = []

    def open(self, req, timeout):
        self.requests.append(req)
        value = next(self.values)
        if isinstance(value, Exception):
            raise value
        return io.BytesIO(value)


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db, self.manifest, self.parts, self.originals = fixture(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def export_rows(self, output):
        with gzip.open(output / "passages.jsonl.gz", "rt", encoding="utf-8") as stream:
            return [json.loads(line) for line in stream]

    def test_exports_every_row_including_modern_and_toc(self):
        output = self.root / "out"
        observed = export.export_sqlite(self.db, self.manifest, output)
        rows = self.export_rows(output)
        self.assertEqual(len(rows), 3)
        self.assertEqual({row["kind"] for row in rows}, {"text", "toc"})
        self.assertIn("modern-editorial", {row["layer"] for row in rows})
        self.assertEqual(observed["passages"], self.manifest["passages"])
        self.assertIsNone(observed["selection_filter"])
        self.assertTrue(observed["all_rows_exported"])

    def test_original_text_ids_json_and_four_clocks_preserved(self):
        output = self.root / "out"
        export.export_sqlite(self.db, self.manifest, output)
        rows = self.export_rows(output)
        with export.open_readonly(self.db) as db:
            original_rows = [dict(row) for row in db.execute("SELECT * FROM passages ORDER BY rid")]
        for original, row in zip(original_rows, rows):
            for key, value in original.items():
                self.assertEqual(row[key], value)
            self.assertEqual(row["raw_text"], original["text"])
            self.assertEqual(row["original_row_sha256"], digest(export.dump(original).encode("utf-8")))
            self.assertEqual(row["text_sha256_utf8"], digest(original["text"].encode("utf-8")))
            self.assertEqual(set(row["temporal_parsed"]), {"t_author", "t_composition", "t_edition", "t_citation"})

    def test_source_licenses_books_external_and_meta_preserved(self):
        output = self.root / "out"
        observed = export.export_sqlite(self.db, self.manifest, output)
        registry = [json.loads(line) for line in (output / "source_license_registry.jsonl").read_text().splitlines()]
        self.assertEqual(len(registry), 2)
        self.assertTrue(all(row["source_info"]["license"] == "fixture-only" for row in registry))
        self.assertEqual(len((output / "books.jsonl").read_text().splitlines()), 2)
        self.assertEqual(observed["optional_table_rows"], {"meta": 1, "external": 1})

    def test_database_is_unchanged_and_readonly(self):
        before = export.file_record(self.db)
        db = export.open_readonly(self.db)
        with self.assertRaises(sqlite3.OperationalError):
            db.execute("DELETE FROM passages")
        db.close()
        export.export_sqlite(self.db, self.manifest, self.root / "out")
        self.assertEqual(before, export.file_record(self.db))
        self.assertFalse(Path(str(self.db) + "-wal").exists())

    def test_streamed_gzip_is_reproducible(self):
        export.export_sqlite(self.db, self.manifest, self.root / "a")
        export.export_sqlite(self.db, self.manifest, self.root / "b")
        self.assertEqual((self.root / "a/passages.jsonl.gz").read_bytes(), (self.root / "b/passages.jsonl.gz").read_bytes())

    def test_manifest_counts_must_match(self):
        for key in ("books", "passages", "characters"):
            bad = copy.deepcopy(self.manifest)
            bad[key] += 1
            with self.subTest(key=key), self.assertRaises(export.ExportError):
                export.export_sqlite(self.db, bad, self.root / key)

    def test_per_source_counts_must_match(self):
        bad = copy.deepcopy(self.manifest)
        bad["sources"]["kanripo"]["characters"] += 1
        with self.assertRaisesRegex(export.ExportError, "per-source"):
            export.export_sqlite(self.db, bad, self.root / "out")

    def test_book_embedded_id_alignment(self):
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE books SET data=? WHERE id='ancient'", (json.dumps({"id": "wrong"}),))
        with self.assertRaisesRegex(export.ExportError, "ID disagree"):
            export.export_sqlite(self.db, self.manifest, self.root / "out")

    def test_bad_temporal_json_is_not_silently_discarded(self):
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE passages SET temporal='bad' WHERE rid=1")
        with self.assertRaisesRegex(export.ExportError, "Invalid JSON"):
            export.export_sqlite(self.db, self.manifest, self.root / "out")

    def test_verified_download_in_manifest_order(self):
        client = FakeKV(self.parts)
        archive, records = export.acquire_archive(self.manifest, client, "taochronos-store", self.root)
        self.assertEqual(archive.read_bytes(), b"".join(self.parts))
        self.assertEqual(len(records), 2)
        self.assertEqual(client.keys, [self.manifest["key"] + p["name"] for p in self.manifest["parts"]])
        raw = export.unpack_verified(archive, self.manifest, self.root / "unpacked.sqlite")
        self.assertEqual(raw.read_bytes(), self.db.read_bytes())

    def test_truncated_part_is_rejected(self):
        client = FakeKV(self.parts, lambda index, data: data[:-1] if index == 0 else data)
        with self.assertRaisesRegex(export.ExportError, "byte count"):
            export.acquire_archive(self.manifest, client, "taochronos-store", self.root)

    def test_corrupt_part_same_length_is_rejected(self):
        client = FakeKV(self.parts, lambda index, data: bytes([data[0] ^ 1]) + data[1:] if index == 0 else data)
        with self.assertRaisesRegex(export.ExportError, "SHA-256"):
            export.acquire_archive(self.manifest, client, "taochronos-store", self.root)

    def test_whole_archive_hash_is_checked(self):
        bad = copy.deepcopy(self.manifest)
        bad["sha256"] = "a" * 64
        bad["key"] = f"store/{bad['sha256']}/"
        with self.assertRaisesRegex(export.ExportError, "assembled archive: SHA-256"):
            export.acquire_archive(bad, FakeKV(self.parts), "taochronos-store", self.root)

    def test_raw_hash_and_raw_length_are_checked(self):
        archive = self.root / "archive.xz"
        archive.write_bytes(b"".join(self.parts))
        for field, value in (("raw_sha256", "b" * 64), ("raw_bytes", self.manifest["raw_bytes"] - 1)):
            bad = copy.deepcopy(self.manifest)
            bad[field] = value
            with self.subTest(field=field), self.assertRaises(export.ExportError):
                export.unpack_verified(archive, bad, self.root / "bad.sqlite")

    def test_truncated_xz_with_matching_compressed_hash_still_fails(self):
        compressed = b"".join(self.parts)[:-10]
        archive = self.root / "archive.xz"
        archive.write_bytes(compressed)
        bad = copy.deepcopy(self.manifest)
        bad["bytes"] = len(compressed)
        bad["sha256"] = digest(compressed)
        with self.assertRaisesRegex(export.ExportError, "decompression"):
            export.unpack_verified(archive, bad, self.root / "bad.sqlite")

    def test_path_traversal_duplicate_names_and_bad_length_rejected(self):
        for change in (lambda m: m["parts"][0].update(name="../secret"),
                       lambda m: m["parts"][1].update(name=m["parts"][0]["name"]),
                       lambda m: m.update(bytes=m["bytes"] + 1)):
            bad = copy.deepcopy(self.manifest)
            change(bad)
            with self.assertRaises(export.ExportError):
                export.validate_manifest(bad)

    def test_namespace_pagination_and_encoded_key_get_only(self):
        first = {"success": True, "result": [{"id": "other", "title": "unrelated"}], "result_info": {"total_pages": 2}}
        second = {"success": True, "result": [{"id": "wanted", "title": "taochronos-store"}], "result_info": {"total_pages": 2}}
        opener = FakeOpener([json.dumps(first).encode(), json.dumps(second).encode(), b"payload"])
        client = export.CloudflareKV("test-account", "fixture-not-a-real-secret", opener=opener)
        namespace = client.namespace("taochronos-store")
        self.assertEqual(namespace, "wanted")
        client.download(namespace, "store/sha/part-000", self.root / "part", 7)
        self.assertIn("page=2", opener.requests[1].full_url)
        self.assertTrue(opener.requests[2].full_url.endswith("/values/store%2Fsha%2Fpart-000"))
        self.assertTrue(all(req.get_method() == "GET" for req in opener.requests))

    def test_retry_http_error_is_sanitized(self):
        secret_url = "https://example.invalid/PRIVATE_ACCOUNT"
        failure = error.HTTPError(secret_url, 403, "PRIVATE_TOKEN", {}, None)
        client = export.CloudflareKV("fixture", "PRIVATE_TOKEN", opener=FakeOpener([failure]))
        with self.assertRaises(export.ExportError) as caught:
            client.namespace("taochronos-store")
        self.assertEqual(str(caught.exception), "Cloudflare read failed with HTTP 403")
        self.assertNotIn("PRIVATE", str(caught.exception))

    def test_transient_failure_retries_and_oversize_stops(self):
        failure = error.HTTPError("https://example.invalid", 503, "server error", {}, None)
        opener = FakeOpener([failure, b"12345"])
        waits = []
        client = export.CloudflareKV("fixture", "fixture", opener=opener, sleep=waits.append)
        with self.assertRaisesRegex(export.ExportError, "exceeds manifest"):
            client.download("ns", "key", self.root / "part", 4)
        self.assertEqual(waits, [1])
        self.assertEqual(len(opener.requests), 2)

    def test_end_to_end_and_safe_failure_ledger(self):
        manifest_path = self.root / "store.json"
        manifest_path.write_text(json.dumps(self.manifest))
        output = self.root / "complete"
        result = export.run_export(manifest_path, output, FakeKV(self.parts), commit="fixture-commit")
        self.assertTrue(result["observed"]["all_rows_exported"])
        self.assertEqual(json.loads((output / "completion.json").read_text())["status"], "complete")
        self.assertEqual((output / "failures.jsonl").read_text(), "")
        self.assertEqual((output / "raw_verified.sqlite.xz").read_bytes(), b"".join(self.parts))
        self.assertEqual(result["upstream_excluded_sources"], {"restricted": 1})
        bad_output = self.root / "failed"
        with self.assertRaises(export.ExportError):
            export.run_export(manifest_path, bad_output, FakeKV(self.parts, lambda index, data: data[:-1]))
        self.assertEqual({p.name for p in bad_output.iterdir()}, {"completion.json", "failures.jsonl"})
        self.assertEqual(json.loads((bad_output / "completion.json").read_text())["status"], "failed")


if __name__ == "__main__":
    unittest.main()
