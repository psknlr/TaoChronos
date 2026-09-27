"""``taochronos web build``: the web client as a static site (GitHub Pages).

The site holds the client (``web/``), the in-browser runtime — the package (``runtime/taochronos.zip``) and the data it
reads (``runtime/home.zip``: profiles, domain packs, the demonstration corpus, agents, skills, gold sets) — the provider
list (``providers.json``) and, unless ``--pyodide cdn``, the Pyodide files the runtime runs on, so that the site
depends on no other host.  Archives are deterministic: the same checkout builds the same bytes.

The full corpus store is never part of the site; the browser runs on the demonstration corpus, and the full corpus is
reached through ``taochronos serve`` on the user's machine.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
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


def home_zip(home: Path) -> bytes:
    """What the harness reads from its home, for the demonstration corpus."""
    entries: list[tuple[str, Path]] = []
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


def build_site(out: Path, *, home: Path, web: Path | None = None, pyodide: str = "self") -> dict[str, Any]:
    """Assemble the site in ``out``: the client, the runtime, providers.json and (``pyodide="self"``) Pyodide."""
    web = web or home / "web"
    if not (web / "index.html").is_file():
        raise FileNotFoundError(f"no web client at {web}")
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(web, out, ignore=shutil.ignore_patterns("node_modules", "tests", "*.map", ".DS_Store"))
    runtime = out / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    pkg, data = package_zip(), home_zip(home)
    (runtime / "taochronos.zip").write_bytes(pkg)
    (runtime / "home.zip").write_bytes(data)
    info = manifest(pkg, data)
    info["pyodide_base"] = "pyodide/" if pyodide == "self" else PYODIDE_CDN
    if pyodide == "self":
        info["pyodide_files"] = fetch_pyodide(out / "pyodide")
    (runtime / "manifest.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "providers.json").write_text(json.dumps(web_providers(), ensure_ascii=False, indent=1), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return {"out": str(out), **info}
