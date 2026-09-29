"""``taochronos web build``: the web client as a static site (GitHub Pages).

The site holds the client (``web/``), the in-browser runtime — the package (``runtime/taochronos.zip``) and the data it
reads (``runtime/home.zip``: profiles, domain packs, the demonstration corpus, agents, skills, gold sets) — the provider
list (``providers.json``) and, unless ``--pyodide cdn``, the Pyodide files the runtime runs on, so that the site
depends on no other host.  Archives are deterministic: the same checkout builds the same bytes.

The full corpus store is never part of the site.  The site carries the 要籍语料 (``corpus/web``: the texts of the 350
ranked works, ``taochronos web pack``) as a store without its full-text index, xz-compressed (``runtime/corpus.sqlite.xz``);
the browser indexes it on first use and keeps the result.  ``home.zip`` also carries the YAML the runtime reads already
parsed (``.cache/yaml``, the cache of ``protocol.yamlio``, keyed by each file's content): parsing it in the browser took
most of the runtime's start.  ``runtime/boot.json`` holds what the runtime will say about
itself (its info, with the standing instructions, and its tool catalogs), so that the page can start a conversation
while the runtime is still loading.  Without a pack the browser runs on the demonstration corpus.  The full corpus is
reached through ``taochronos serve``.
"""

from __future__ import annotations

import functools
import hashlib
import io
import json
import lzma
import os
import re
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from .. import __version__
from .providers import web_providers

PYODIDE_VERSION = "0.28.2"
PYODIDE_CDN = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/"
PYODIDE_CORE = ["pyodide.mjs", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"]
PYODIDE_PACKAGES = ["pyyaml", "sqlite3"]
HOME_PARTS = ["architecture-policy.yaml", "profiles", "domains", "corpus/demo", "corpus/catalog", "corpus/modern", "agents",
              "skills", "evals/gold"]
HOME_SKIP = ("domains/classics/lexicon-harvested",)  # harvested from the full corpus, read only with it
EPOCH = (1980, 1, 1, 0, 0, 0)
PACKAGE = Path(__file__).resolve().parents[1]


def _zip(entries: list[tuple[str, Path]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name, path in sorted(entries):
            info = zipfile.ZipInfo(name, EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, path.read_bytes())
    return buf.getvalue()


def package_zip(package: Path = PACKAGE) -> bytes:
    """The ``taochronos`` package, to be unpacked into the browser's site-packages."""
    entries = [(f"taochronos/{p.relative_to(package).as_posix()}", p) for p in package.rglob("*")
               if p.is_file() and "__pycache__" not in p.parts and p.suffix not in (".pyc", ".pyo")]
    return _zip(entries)


def home_zip(home: Path, yaml_cache: Path | None = None) -> bytes:
    """What the harness reads from its home, for the demonstration corpus; with ``yaml_cache``, that YAML parsed
    (``.cache/yaml/…``: the browser points ``TAOCHRONOS_CACHE`` at ``.cache``)."""
    entries: list[tuple[str, Path]] = []
    if yaml_cache is not None:
        entries += [(f".cache/yaml/{p.relative_to(yaml_cache).as_posix()}", p) for p in sorted(yaml_cache.rglob("*.pickle"))]
    for part in HOME_PARTS:
        root = home / part
        paths = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file()) if root.is_dir() else []
        for p in paths:
            rel = p.relative_to(home).as_posix()
            if "__pycache__" in p.parts or any(rel.startswith(s + "/") for s in HOME_SKIP):
                continue
            entries.append((rel, p))
    return _zip(entries)


def manifest(pkg: bytes, home: bytes) -> dict[str, Any]:
    return {"version": __version__, "pyodide": PYODIDE_VERSION,
            "files": {"taochronos.zip": {"bytes": len(pkg), "sha256": hashlib.sha256(pkg).hexdigest()},
                      "home.zip": {"bytes": len(home), "sha256": hashlib.sha256(home).hexdigest()}}}


def _pack_digest(pack: Path) -> str:
    h = hashlib.sha256()
    for name in ("books.json", "passages.jsonl.gz"):
        h.update((pack / name).read_bytes())
    return h.hexdigest()


def corpus_store(home: Path) -> tuple[bytes, dict[str, Any]] | None:
    """The 要籍语料 pack as an xz-compressed store without its index (deterministic), or None without a pack."""
    pack = home / "corpus" / "web"
    if not (pack / "passages.jsonl.gz").is_file():
        return None
    preset = int(os.environ.get("TAOCHRONOS_WEB_XZ_PRESET") or 6)  # tests may trade size for time
    return _corpus_store(str(home), _pack_digest(pack), preset)


@functools.lru_cache(maxsize=2)
def _corpus_store(home_dir: str, digest: str, preset: int) -> tuple[bytes, dict[str, Any]]:
    import sqlite3

    from ..plugins.classics.domain import DomainPack
    from ..plugins.classics.webcorpus import CORE_RANK, build_store

    home = Path(home_dir)
    domain = DomainPack(home / "domains" / "classics")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "tcm.sqlite"
        info = build_store(home / "corpus" / "web", path, domain.variants.normalize_text, domain.variants.fingerprint,
                           external=home / "corpus" / "catalog" / "external-works.yaml", index=False)
        db = sqlite3.connect(path)
        core_rid = int(dict(db.execute("SELECT key, value FROM meta").fetchall()).get("index_core") or 0)
        core = db.execute("SELECT COUNT(*) FROM passages WHERE rid <= ?", (core_rid,)).fetchone()[0]
        db.close()
        raw = path.read_bytes()
    # xz (LZMA2, CRC32: what the browser's decoder reads) is two thirds the size of gzip for this data
    data = lzma.compress(raw, format=lzma.FORMAT_XZ, check=lzma.CHECK_CRC32, preset=preset)
    return data, {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "raw_bytes": len(raw), "encoding": "xz",
                  "books": info["books"], "passages": info["passages"], "core_rank": CORE_RANK, "core_passages": core,
                  "profile": "web-canon"}


def boot_file(home: Path, corpus: bytes | None, yaml_cache: Path | None = None) -> dict[str, Any]:
    """What the browser runtime will report once loaded — its info and tool catalogs — computed here on the same code and
    corpus, so that the page can put the first question to the model while the runtime loads.  With ``yaml_cache`` (an
    empty directory), the YAML this reads is left there parsed, for the browser."""
    before = os.environ.get("TAOCHRONOS_CACHE")
    if yaml_cache is not None:
        os.environ["TAOCHRONOS_CACHE"] = str(yaml_cache.parent)  # yamlio keeps its entries in <cache>/yaml
    try:
        return _boot(home, corpus)
    finally:
        if yaml_cache is not None:
            if before is None:
                os.environ.pop("TAOCHRONOS_CACHE", None)
            else:
                os.environ["TAOCHRONOS_CACHE"] = before


def _boot(home: Path, corpus: bytes | None) -> dict[str, Any]:
    from . import ChatRuntime

    with tempfile.TemporaryDirectory() as tmp:
        if corpus is not None:
            (Path(tmp) / "corpus").mkdir(parents=True)
            (Path(tmp) / "corpus" / "tcm.sqlite").write_bytes(lzma.decompress(corpus))
        rt = ChatRuntime.create("web-canon" if corpus is not None else "full-discovery", home=home, data_dir=tmp,
                                kind="browser", ephemeral=True)
        return {"info": rt.info(), "catalogs": {mode: rt.catalog(mode) for mode in ("core", "all")}}


def _download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as r:  # noqa: S310 — a fixed https URL
        return r.read()


def fetch_pyodide(dest: Path, *, base: str = PYODIDE_CDN, packages: list[str] = PYODIDE_PACKAGES) -> list[str]:
    """The Pyodide core and the packages the runtime loads (with their dependencies), from the pinned release."""
    dest.mkdir(parents=True, exist_ok=True)
    got = []
    for name in PYODIDE_CORE:
        (dest / name).write_bytes(_download(base + name))
        got.append(name)
    lock = json.loads((dest / "pyodide-lock.json").read_text(encoding="utf-8"))
    wanted, seen = list(packages), set()
    while wanted:
        name = wanted.pop()
        if name in seen:
            continue
        seen.add(name)
        pkg = lock["packages"][name]
        data = _download(base + pkg["file_name"])
        if pkg.get("sha256") and hashlib.sha256(data).hexdigest() != pkg["sha256"]:
            raise ValueError(f"{pkg['file_name']}: checksum does not match pyodide-lock.json")
        (dest / pkg["file_name"]).write_bytes(data)
        got.append(pkg["file_name"])
        wanted += list(pkg.get("depends", []))
    return got


def build_site(out: Path, *, home: Path, web: Path | None = None, pyodide: str = "self", relay: str | None = None) -> dict[str, Any]:
    """Assemble the site in ``out``: the client, the runtime, providers.json, (``pyodide="self"``) Pyodide, the texts'
    attribution (the repository may be private: the licence's credits travel with the site) and, with ``relay``,
    site.json naming the 道乃久默认服务 relay (relay/) the page may use without a key."""
    relay = (relay or "").strip().rstrip("/")
    if relay.lower() in ("", "none", "off"):
        relay = ""
    elif not re.match(r"^https?://[^/\s]+(/\S*)?$", relay):
        raise ValueError(f"the relay must be an http(s) address: {relay!r}")
    web = web or home / "web"
    if not (web / "index.html").is_file():
        raise FileNotFoundError(f"no web client at {web}")
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(web, out, ignore=shutil.ignore_patterns("node_modules", "tests", "*.map", ".DS_Store"))
    runtime = out / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    corpus = corpus_store(home)
    with tempfile.TemporaryDirectory() as tmp:
        yaml_cache = Path(tmp) / "yaml"  # what booting the runtime parses, parsed once here
        yaml_cache.mkdir()
        boot = boot_file(home, corpus[0] if corpus is not None else None, yaml_cache)
        pkg, data = package_zip(), home_zip(home, yaml_cache)
    (runtime / "taochronos.zip").write_bytes(pkg)
    (runtime / "home.zip").write_bytes(data)
    info = manifest(pkg, data)
    if corpus is not None:
        (runtime / "corpus.sqlite.xz").write_bytes(corpus[0])
        info["files"]["corpus.sqlite.xz"] = corpus[1]
    (runtime / "boot.json").write_text(json.dumps(boot, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    info["pyodide_base"] = "pyodide/" if pyodide == "self" else PYODIDE_CDN
    if pyodide == "self":
        info["pyodide_files"] = fetch_pyodide(out / "pyodide")
    (runtime / "manifest.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "providers.json").write_text(json.dumps(web_providers(), ensure_ascii=False, indent=1), encoding="utf-8")
    credits = home / "corpus" / "web" / "ATTRIBUTION.md"
    if credits.is_file():
        shutil.copyfile(credits, out / "ATTRIBUTION.md")
    if relay:
        (out / "site.json").write_text(json.dumps({"relay": relay}, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return {"out": str(out), **info, "relay": relay or None}
