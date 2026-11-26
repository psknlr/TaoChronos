"""``taochronos web build``: the web client as a static site (GitHub Pages).

The site holds the client (``web/``), the in-browser runtime — the package as the browser can import it
(``runtime/taochronos.zip``) and the data it reads (``runtime/home.zip``: the browser's profiles, domain packs, the
demonstration corpus, the catalogs, agents, skills) — the provider list (``providers.json``) and, unless ``--pyodide
cdn``, the Pyodide files the runtime runs on, so that the site depends on no other host.  Archives are deterministic:
the same checkout builds the same bytes.

Whatever the site carries is public, so what it may carry is written down (``distribution-policy.yaml``, read by
:mod:`taochronos.chat.distribution`; docs/adr/0034-what-the-site-ships.md): of the package, the modules the browser can
import — never the server, the command line, the evaluation suites or the corpus pipeline; of the home, the files the
policy names — never the gold sets, the conversation records or the logs.  The build starts the runtime on exactly
those two archives, in a process that can import nothing else of the package, before it publishes them (what it
reports then is ``runtime/boot.json``), and checks the finished site against the policy: a violation stops the build.

The full corpus store is never part of the site.  The site carries the 要籍语料 (``corpus/web``: the texts of the
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
import json
import lzma
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .. import __version__
from ..config import find_home
from .distribution import PACKAGE, DistributionError, audit_site, home_files, load_policy, package_files, zipped
from .providers import ORDER, web_providers

PYODIDE_VERSION = "0.28.2"
PYODIDE_CDN = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/"
PYODIDE_CORE = ["pyodide.mjs", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"]
PYODIDE_PACKAGES = ["pyyaml", "sqlite3"]
EPOCH = (1980, 1, 1, 0, 0, 0)
# TaoCore for the browser (docs/adr/0036-taocore.md): the module rust/wasm.sh builds, committed so that a build needs no
# Rust (CI rebuilds it and compares the bytes); shipped as runtime/taocore.wasm, named in the manifest with its sha256
TAOCORE_WASM = Path("rust") / "crates" / "taocore-wasm" / "taocore.wasm"


def package_zip(package: Path = PACKAGE, home: Path | None = None, policy: dict[str, Any] | None = None) -> bytes:
    """The ``taochronos`` package as the browser can import it, to be unpacked into its site-packages: the modules the
    policy of ``home`` (by default this checkout's) lets the site carry (:func:`distribution.browser_modules`)."""
    return zipped(package_files(home or find_home(), policy, package), EPOCH)


def home_zip(home: Path, yaml_cache: Path | None = None, policy: dict[str, Any] | None = None) -> bytes:
    """What the harness reads from its home, as the policy names it (:func:`distribution.home_files`); with
    ``yaml_cache``, that YAML parsed (``.cache/yaml/…``: the browser points ``TAOCHRONOS_CACHE`` at ``.cache``)."""
    entries: list[tuple[str, Path | bytes]] = list(home_files(home, policy))
    if yaml_cache is not None:
        entries += [(f".cache/yaml/{p.relative_to(yaml_cache).as_posix()}", p) for p in sorted(yaml_cache.rglob("*.pickle"))]
    return zipped(entries, EPOCH)


def manifest(pkg: bytes, home: bytes, kernel: bytes | None = None) -> dict[str, Any]:
    files = {"taochronos.zip": {"bytes": len(pkg), "sha256": hashlib.sha256(pkg).hexdigest()},
             "home.zip": {"bytes": len(home), "sha256": hashlib.sha256(home).hexdigest()}}
    if kernel is not None:  # the worker loads it only for the ABI its loader speaks
        from ..plugins.retrieval.taocore import ABI

        files["taocore.wasm"] = {"bytes": len(kernel), "sha256": hashlib.sha256(kernel).hexdigest(), "abi": ABI}
    return {"version": __version__, "pyodide": PYODIDE_VERSION, "files": files}


def taocore_module(home: Path) -> bytes | None:
    """TaoCore's browser module as this home holds it (None for a home without one: the runtime computes in Python)."""
    path = home / TAOCORE_WASM
    return path.read_bytes() if path.is_file() else None


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


# What the runtime says of itself, asked of the two archives as the browser will hold them: a process whose only
# taochronos is the unpacked package and whose home is the unpacked home.  It fails if any module it imported came from
# anywhere else — the archive lacks what the runtime needs, and a visitor's browser would have found out first.
_BOOT = r"""
import json, sys
from pathlib import Path
package, home, profile, data, out = sys.argv[1:6]
import taochronos
root = Path(package).resolve()
if root not in Path(taochronos.__file__).resolve().parents:
    raise SystemExit(f"the package imported is not the one the site would ship: {taochronos.__file__}")
from taochronos.chat import ChatRuntime
rt = ChatRuntime.create(profile, home=home, data_dir=data, kind="browser", ephemeral=True)
report = {"info": rt.info(), "catalogs": {mode: rt.catalog(mode) for mode in ("core", "all")}}
strays = sorted(name for name, mod in sys.modules.items() if (name == "taochronos" or name.startswith("taochronos."))
                and getattr(mod, "__file__", None) and root not in Path(mod.__file__).resolve().parents)
if strays:
    raise SystemExit("imported from outside what the site would ship: " + ", ".join(strays))
Path(out).write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
"""


def boot_file(package: Path, home: Path, corpus: bytes | None, yaml_cache: Path | None = None) -> dict[str, Any]:
    """What the browser runtime will report once loaded — its info and tool catalogs — asked of the archives' own
    content: ``package`` (a directory holding the shipped ``taochronos``) and ``home`` (the shipped home) are all the
    process started here has of TaoChronos.  The page can then put the first question to the model while its runtime
    loads, and a site whose archives lack what the runtime needs is never built.  With ``yaml_cache`` (an empty
    directory), the YAML this reads is left there parsed, for the browser.

    :raises DistributionError: the runtime does not start on what the site would ship."""
    with tempfile.TemporaryDirectory() as tmp:
        data, out = Path(tmp) / "data", Path(tmp) / "boot.json"
        if corpus is not None:
            (data / "corpus").mkdir(parents=True)
            (data / "corpus" / "tcm.sqlite").write_bytes(lzma.decompress(corpus))
        env = {k: v for k, v in os.environ.items() if not k.startswith("TAOCHRONOS_") or k == "TAOCHRONOS_SQLITE_JOURNAL"}
        env |= {"PYTHONPATH": str(package), "TAOCHRONOS_HOME": str(home), "TAOCHRONOS_DATA": str(data), "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONIOENCODING": "utf-8",
                # yamlio keeps its entries in <cache>/yaml
                "TAOCHRONOS_CACHE": str(yaml_cache.parent) if yaml_cache is not None else "off"}
        profile = "web-canon" if corpus is not None else "full-discovery"
        # from a directory of its own: `python -c` looks for modules in the working directory first
        ran = subprocess.run([sys.executable, "-c", _BOOT, str(package), str(home), profile, str(data), str(out)],  # noqa: S603
                             cwd=tmp, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
        if ran.returncode != 0 or not out.is_file():
            why = (ran.stderr or ran.stdout or "").strip().splitlines()
            raise DistributionError("the runtime does not start on what the site would ship (distribution-policy.yaml: a module "
                                    "the browser imports, or a file it reads, is not among what is published): "
                                    + (" | ".join(why[-4:]) or f"exit {ran.returncode}"))
        return json.loads(out.read_text(encoding="utf-8"))


def _unpack(entries: Iterable[tuple[str, Path | bytes]], dest: Path) -> Path:
    """The entries of an archive as files under ``dest``: what the browser will have unpacked."""
    for name, src in entries:
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(src if isinstance(src, bytes) else src.read_bytes())
    return dest


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


# the pages a search engine may index (sitemap.xml), by their addresses without .html (the site redirects those)
# the pages search engines are pointed to; the attribution page (the credits the texts' licences ask for) is not one of
# them — it travels with the site, kept out of search (noindex), linked once from the about page
PAGES = ("", "about")


# crawlers that gather pages only to train models: asked here to stay away, and refused by name at the edge
# (security/rules.yaml training_agents, the same names but the robots.txt-only tokens; tests/test_security_apply.py
# checks).  A search engine's crawler is never named — Baiduspider, PetalBot and Bytespider gather for search as well —
# so every search engine reads the rules for every crawler
TRAINING_CRAWLERS = ("GPTBot", "ClaudeBot", "anthropic-ai", "Claude-Web", "CCBot", "Google-Extended", "Applebot-Extended",
                     "Google-CloudVertexBot", "meta-externalagent", "FacebookBot", "Amazonbot", "cohere-ai", "Diffbot", "omgili",
                     "MistralAI-Training")


def search_files(site: str) -> dict[str, str]:
    """robots.txt and sitemap.xml for the site at ``site``: the pages are indexed, the runtime and Pyodide (the files
    the page loads, not pages) are not, and crawlers that only gather training data are asked to stay away.  No
    lastmod: the build stays deterministic."""
    site = site.strip().rstrip("/")
    if not re.match(r"^https://[^/\s]+$", site):
        raise ValueError(f"the site must be an https origin: {site!r}")
    robots = ("User-agent: *\nAllow: /\nDisallow: /runtime/\nDisallow: /pyodide/\n\n"
              + "".join(f"User-agent: {agent}\nDisallow: /\n\n" for agent in TRAINING_CRAWLERS)
              + f"Sitemap: {site}/sitemap.xml\n")
    urls = "".join(f"  <url><loc>{site}/{page}</loc></url>\n" for page in PAGES)
    sitemap = ('<?xml version="1.0" encoding="UTF-8"?>\n'
               f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}</urlset>\n')
    return {"robots.txt": robots, "sitemap.xml": sitemap}


def build_site(out: Path, *, home: Path, web: Path | None = None, pyodide: str = "self", relay: str | None = None,
               unlist: Iterable[str] = (), site: str = "https://chat.impf.ai") -> dict[str, Any]:
    """Assemble the site in ``out``: the client, the runtime, providers.json (without the presets named in ``unlist``),
    (``pyodide="self"``) Pyodide, the texts' credits (attribution.html, a short notice of each licensed source: the
    repository may be private, and the licences' credits travel with the site), robots.txt and sitemap.xml for the site's address ``site`` and, with ``relay``, site.json naming
    the 道乃久默认服务 relay (relay/) the page may use without a key.

    The runtime's two archives hold what ``distribution-policy.yaml`` lets the site carry; the runtime is started on
    them before they are written, and the finished site is checked against the policy.

    :raises DistributionError: the policy is missing or broken by what would ship, the runtime does not start on the
        archives, or the finished site holds what the policy does not allow (it is left in ``out`` to be looked at;
        nothing should publish it)."""
    policy = load_policy(home)
    search = search_files(site)
    relay = (relay or "").strip().rstrip("/")
    if relay.lower() in ("", "none", "off"):
        relay = ""
    elif not re.match(r"^https?://[^/\s]+(/\S*)?$", relay):
        raise ValueError(f"the relay must be an http(s) address: {relay!r}")
    unlist = sorted({u.strip() for u in unlist if u.strip()})
    if unknown := [u for u in unlist if u not in ORDER]:
        raise ValueError(f"no such provider preset: {', '.join(unknown)} (the presets: {', '.join(ORDER)})")
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
        shipped_package = _unpack(package_files(home, policy), Path(tmp) / "package")
        shipped_home = _unpack(home_files(home, policy), Path(tmp) / "home")
        boot = boot_file(shipped_package, shipped_home, corpus[0] if corpus is not None else None, yaml_cache)
        pkg, data = package_zip(home=home, policy=policy), home_zip(home, yaml_cache, policy)
    (runtime / "taochronos.zip").write_bytes(pkg)
    (runtime / "home.zip").write_bytes(data)
    kernel = taocore_module(home)
    if kernel is not None:
        (runtime / "taocore.wasm").write_bytes(kernel)
    info = manifest(pkg, data, kernel)
    if corpus is not None:
        (runtime / "corpus.sqlite.xz").write_bytes(corpus[0])
        info["files"]["corpus.sqlite.xz"] = corpus[1]
    (runtime / "boot.json").write_text(json.dumps(boot, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    info["pyodide_base"] = "pyodide/" if pyodide == "self" else PYODIDE_CDN
    if pyodide == "self":
        info["pyodide_files"] = fetch_pyodide(out / "pyodide")
    (runtime / "manifest.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "providers.json").write_text(json.dumps(web_providers(unlist), ensure_ascii=False, indent=1), encoding="utf-8")
    # the book-by-book credits (corpus/web/ATTRIBUTION.md, and the full corpus's cloud/ATTRIBUTION.md) stay in the
    # repository, by the publisher's choice: the site carries attribution.html, the credits the licences ask for
    if relay:
        (out / "site.json").write_text(json.dumps({"relay": relay}, ensure_ascii=False, indent=1), encoding="utf-8")
    for name, text in search.items():
        (out / name).write_text(text, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    problems = audit_site(out, home, policy, web=web)
    if problems:
        raise DistributionError(f"the site built in {out} breaks distribution-policy.yaml and must not be published: "
                                + "; ".join(problems[:12]) + (f"; and {len(problems) - 12} more" if len(problems) > 12 else ""))
    return {"out": str(out), **info, "relay": relay or None}
