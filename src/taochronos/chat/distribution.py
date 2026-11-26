"""What the published site may carry: ``distribution-policy.yaml`` read, applied and checked.

The page runs in the visitor's browser, so whatever the site carries is public — the edge can refuse an address or a
user agent, not a copy already made, and a mirror serves the same files outside it.  What protects is what is built
into the site.  This module is that line (docs/adr/0034-what-the-site-ships.md):

* :func:`browser_modules` — the modules of the package the browser can import: the import graph (every ``import`` of
  every module, those inside functions too) closed over what the page's worker imports, the plugins the browser's
  profiles load and the modules the shipped agents name.  A module the policy says must never ship (the server, the
  command line, the evaluation suites, the corpus pipeline) fails the build with the chain of imports that reached it.
* :func:`home_files` — the files of the home the policy names, and no other.
* :func:`audit_site` — a built site against the policy: every file is the client's or the build's, the archives hold
  what the two functions above say and nothing else, no name the policy forbids, nothing that reads as a credential.

``taochronos web build`` ships what the first two return and refuses to finish when the third finds anything.
"""

from __future__ import annotations

import ast
import fnmatch
import io
import json
import re
import zipfile
from collections import deque
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ..protocol.yamlio import load_yaml

POLICY = "distribution-policy.yaml"
PACKAGE = Path(__file__).resolve().parents[1]
CLASSES = ("public", "restricted", "confidential")
# what the build itself writes into a site, beside the client (web/) and Pyodide (named in the manifest)
GENERATED = ("runtime/taochronos.zip", "runtime/home.zip", "runtime/corpus.sqlite.xz", "runtime/taocore.wasm", "runtime/boot.json",
             "runtime/manifest.json", "providers.json", "site.json", "robots.txt", "sitemap.xml", ".nojekyll")
CACHE_ENTRY = re.compile(r"^\.cache/yaml/[0-9a-f]{2}/[0-9a-f]{64}\.v\d+\.pickle$")
TEXT = (".html", ".js", ".mjs", ".css", ".json", ".txt", ".xml", ".md", ".svg", ".webmanifest", ".py", ".yaml", ".yml", ".csv", ".pickle")
# What reads as a credential, by the forms the services issue them in — never a guess from a variable's name alone.
# The last one is this project's own: a secret's name with a value written beside it
SECRETS = {
    "a private key": re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"),
    "an AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "a GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})\b"),
    "a model provider's key": re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{32,}"),
    "a Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "a Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "a signed token (JWT)": re.compile(r"\beyJ[A-Za-z0-9_-]{16,}\.eyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}"),
    "a secret of this project with its value": re.compile(
        r"\b(?:LOG_EXPORT_TOKEN|MINIMAX_API_KEY|OPENAI_API_KEY|ANTHROPIC_API_KEY|SPONSOR_SECRET|SENTINEL_SALT|STATS_TOKEN|"
        r"TAOCHRONOS_STORE_TOKEN|CLOUDFLARE_[A-Z_]*TOKEN)[\"']?\s*[=:]\s*[\"']?[A-Za-z0-9_\-+/]{20,}"),
}


class DistributionError(ValueError):
    """What the site would carry breaks the policy; nothing is published."""


# ---------------------------------------------------------------- the policy
def load_policy(home: str | Path) -> dict[str, Any]:
    path = Path(home) / POLICY
    if not path.is_file():
        raise DistributionError(f"no {POLICY} in {home}: nothing is published without one")
    policy = load_yaml(path) or {}
    assets, site = policy.get("assets"), policy.get("site")
    if not isinstance(assets, dict) or not isinstance(site, dict) or set(assets) - set(CLASSES):
        raise DistributionError(f"{path}: wants `assets` ({', '.join(CLASSES)}) and `site`")
    for key in ("package", "home"):
        if not isinstance(site.get(key), dict):
            raise DistributionError(f"{path}: site.{key} is missing")
    if not site["package"].get("entry"):
        raise DistributionError(f"{path}: site.package.entry names no module")
    return policy


def _under(rel: str, prefix: str) -> bool:
    return rel == prefix or rel.startswith(prefix.rstrip("/") + "/")


def class_of(rel: str, policy: dict[str, Any]) -> str | None:
    """The class of a path of the repository: that of the most specific entry it falls under, or None."""
    best, best_len = None, -1
    for name in CLASSES:
        for prefix in policy["assets"].get(name) or []:
            prefix = str(prefix).strip("/")
            if _under(rel, prefix) and len(prefix) > best_len:
                best, best_len = name, len(prefix)
    return best


def unclassified(paths: Iterable[str], policy: dict[str, Any]) -> list[str]:
    """Of the repository's paths, those under no class."""
    return sorted({p for p in paths if class_of(p, policy) is None})


# ---------------------------------------------------------------- the package: what the browser can import
def _modules(package: Path) -> dict[str, Path]:
    out = {}
    for path in package.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        parts = list(path.relative_to(package.parent).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        out[".".join(parts)] = path
    return out


def _imported(module: str, path: Path, modules: dict[str, Path], top: str) -> set[str]:
    """The modules of the package a module imports, wherever in it: at its top, in a function, under a condition."""
    is_pkg = path.name == "__init__.py"
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names if a.name == top or a.name.startswith(top + ".")}
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = module.split(".") if is_pkg else module.split(".")[:-1]
                base = base[: len(base) - (node.level - 1)]
                target = ".".join(base + ([node.module] if node.module else []))
            else:
                target = node.module or ""
            if target == top or target.startswith(top + "."):
                found.add(target)
                found |= {f"{target}.{a.name}" for a in node.names}  # `from package import module`
    return {m for m in found if m in modules}


def _named(texts: Iterable[str], modules: dict[str, Path], top: str) -> set[str]:
    """The modules named in the home's files (a profile's plugins, an agent's procedure): each dotted name, by the
    longest part of it that is a module."""
    out = set()
    for text in texts:
        for name in set(re.findall(rf"\b{re.escape(top)}(?:\.[A-Za-z_][A-Za-z_0-9]*)+", text)):
            parts = name.split(".")
            for n in range(len(parts), 1, -1):
                if ".".join(parts[:n]) in modules:
                    out.add(".".join(parts[:n]))
                    break
    return out


def _forbidden(module: str, never: Iterable[str]) -> str | None:
    return next((n for n in never if module == n or module.startswith(n + ".")), None)


def browser_modules(home: str | Path, policy: dict[str, Any] | None = None, package: Path = PACKAGE) -> dict[str, Path]:
    """The modules of the package the runtime in the browser can import, each with its file, by name.

    :raises DistributionError: an entry point that is no module, or a module among them that must never ship (the
        message gives the imports from an entry point to it)."""
    home = Path(home)
    policy = policy or load_policy(home)
    rules = policy["site"]["package"]
    modules, top = _modules(package), package.name
    missing = [m for m in rules["entry"] if m not in modules]
    if missing:
        raise DistributionError(f"site.package.entry names no module of the package: {', '.join(missing)}")
    texts = [src.read_text(encoding="utf-8", errors="replace") for name, src in home_files(home, policy)
             if isinstance(src, Path) and name.endswith((".yaml", ".yml", ".json", ".md"))]
    came_from: dict[str, str | None] = {m: None for m in sorted(set(rules["entry"]) | _named(texts, modules, top))}
    todo = deque(came_from)
    while todo:
        module = todo.popleft()
        parts = module.split(".")
        parents = {".".join(parts[:n]) for n in range(1, len(parts))}  # importing a.b.c runs a and a.b first
        for dep in sorted(_imported(module, modules[module], modules, top) | parents):
            if dep in modules and dep not in came_from:
                came_from[dep] = module
                todo.append(dep)
    never = [str(n) for n in rules.get("never") or []]
    for module in sorted(came_from):
        rule = _forbidden(module, never)
        if rule:
            chain, at = [module], came_from[module]
            while at is not None:
                chain.append(at)
                at = came_from[at]
            raise DistributionError(f"{module} must never ship ({POLICY}: site.package.never has {rule}), and the browser would "
                                    f"import it: {' ← '.join(chain)}")
    return {m: modules[m] for m in sorted(came_from)}


def package_files(home: str | Path, policy: dict[str, Any] | None = None, package: Path = PACKAGE) -> list[tuple[str, Path]]:
    """The entries of runtime/taochronos.zip: the files of :func:`browser_modules`, as the archive names them."""
    return [(path.relative_to(package.parent).as_posix(), path) for path in browser_modules(home, policy, package).values()]


# ---------------------------------------------------------------- the home: what the runtime reads
def home_files(home: str | Path, policy: dict[str, Any] | None = None) -> list[tuple[str, Path | bytes]]:
    """The entries of runtime/home.zip, without the parsed YAML the build adds: the files the policy names (a
    directory with everything under it), and the marker the harness finds its home by, empty.

    :raises DistributionError: a named path that does not exist, or one of a class that is never published."""
    home = Path(home)
    policy = policy or load_policy(home)
    rules = policy["site"]["home"]
    skip = [str(s).strip("/") for s in rules.get("except") or []]
    out: dict[str, Path | bytes] = {}
    marker = str(rules.get("marker") or "").strip("/")
    if marker:
        out[marker] = b""
    for entry in rules.get("ship") or []:
        rel = str(entry).strip("/")
        root = home / rel
        if class_of(rel, policy) == "confidential":
            raise DistributionError(f"{POLICY}: site.home.ship names {rel}, which is confidential")
        if root.is_file():
            paths = [root]
        elif root.is_dir():
            paths = sorted(p for p in root.rglob("*") if p.is_file())
        else:
            raise DistributionError(f"{POLICY}: site.home.ship names {rel}, which is not in {home}")
        for path in paths:
            name = path.relative_to(home).as_posix()
            if "__pycache__" in path.parts or any(_under(name, s) for s in skip):
                continue
            if class_of(name, policy) == "confidential":
                raise DistributionError(f"{name} is confidential and would ship under {rel}")
            out[name] = path
    return sorted(out.items())


# ---------------------------------------------------------------- a built site, checked
def _credentials(text: str) -> list[str]:
    return [what for what, pattern in SECRETS.items() if pattern.search(text)]


def _banned(name: str, patterns: list[str]) -> str | None:
    base = name.rsplit("/", 1)[-1]
    return next((p for p in patterns if fnmatch.fnmatchcase(base, p)), None)


def wasm_imports(module: bytes) -> int | None:
    """How many imports a WebAssembly module declares — its import section's count (0 without one); None for bytes
    that are not a module.  The text scan reads no binary, so this is what the audit knows of one: a module of no
    imports can only compute on its own memory and give numbers back."""
    if module[:8] != b"\0asm\x01\0\0\0":
        return None

    def leb(at: int) -> tuple[int, int]:
        value = shift = 0
        while True:
            byte = module[at]
            value, shift, at = value | (byte & 0x7F) << shift, shift + 7, at + 1
            if not byte & 0x80:
                return value, at

    at = 8
    try:
        while at < len(module):
            section, (size, start) = module[at], leb(at + 1)
            if start + size > len(module):
                return None  # a section cut short: no module
            if section == 2:
                return leb(start)[0]
            at = start + size
    except IndexError:
        return None
    return 0 if at == len(module) else None


def audit_site(site: str | Path, home: str | Path, policy: dict[str, Any] | None = None, package: Path = PACKAGE,
               web: Path | None = None) -> list[str]:
    """What is wrong with a built site, by the policy (nothing: an empty list):

    * a file that is neither the client's (``web``, by default the home's web/), nor one the build writes, nor a
      Pyodide file the manifest names;
    * runtime/taochronos.zip not holding exactly the modules the browser can import;
    * runtime/home.zip holding anything but the files the policy names, the empty marker and the YAML parsed from them;
    * a name the policy forbids anywhere, in the site or in its archives;
    * anything that reads as a credential, or carries the mark of the confidential data (the policy's canaries), in
      the site's text or its archives' (Pyodide and the corpus store, which are others' files and public-domain
      texts, are not read)."""
    site, home = Path(site), Path(home)
    policy = policy or load_policy(home)
    banned = [str(p) for p in policy["site"].get("never") or []]
    canaries = [str(c) for c in policy["site"].get("canaries") or [] if str(c)]

    def marks(text: str) -> list[str]:
        return _credentials(text) + [f"confidential data (it carries the canary {c[:8]}…)" for c in canaries if c in text]

    problems: list[str] = []
    try:
        manifest = json.loads((site / "runtime" / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = {}
        problems.append("runtime/manifest.json is missing or unreadable")
    expected = set(GENERATED) | {f"pyodide/{n}" for n in manifest.get("pyodide_files") or []}
    web = web or home / "web"
    for path in sorted(p for p in site.rglob("*") if p.is_file()):
        rel = path.relative_to(site).as_posix()
        rule = _banned(rel, banned)
        if rule:
            problems.append(f"{rel}: a name the policy forbids ({rule})")
        elif rel not in expected and not (web / rel).is_file():
            problems.append(f"{rel}: neither a file of the client (web/) nor one the build writes")
        if not rel.startswith("pyodide/") and path.suffix in TEXT and path.stat().st_size < 32_000_000:
            for what in marks(path.read_text(encoding="utf-8", errors="replace")):
                problems.append(f"{rel}: reads as {what}")
        if rel.startswith("runtime/") and path.suffix == ".wasm" and wasm_imports(path.read_bytes()) != 0:
            problems.append(f"{rel}: not a WebAssembly module of no imports (the build ships only such: it computes and reaches nothing)")

    def entries(name: str) -> dict[str, bytes] | None:
        try:
            with zipfile.ZipFile(site / "runtime" / name) as zf:
                return {i.filename: zf.read(i) for i in zf.infolist() if not i.is_dir()}
        except (OSError, zipfile.BadZipFile):
            problems.append(f"runtime/{name} is missing or not an archive")
            return None

    def inside(archive: str, held: dict[str, bytes]) -> None:
        for name, data in sorted(held.items()):
            rule = _banned(name, banned)
            if rule:
                problems.append(f"runtime/{archive}: {name}: a name the policy forbids ({rule})")
            for what in marks(data.decode("utf-8", errors="replace")):
                problems.append(f"runtime/{archive}: {name}: reads as {what}")

    held = entries("taochronos.zip")
    if held is not None:
        wanted = {name for name, _ in package_files(home, policy, package)}
        for name in sorted(set(held) - wanted):
            problems.append(f"runtime/taochronos.zip: {name} is not a module the browser imports")
        for name in sorted(wanted - set(held)):
            problems.append(f"runtime/taochronos.zip: {name} is missing (the browser imports it)")
        inside("taochronos.zip", held)
    held = entries("home.zip")
    if held is not None:
        wanted_home = dict(home_files(home, policy))
        marker = str(policy["site"]["home"].get("marker") or "")
        for name in sorted(held):
            if CACHE_ENTRY.match(name):
                continue
            if name not in wanted_home:
                problems.append(f"runtime/home.zip: {name} is not a file the policy names ({class_of(name, policy) or 'unclassified'})")
            elif name == marker and held[name]:
                problems.append(f"runtime/home.zip: {name} is the home's marker and ships empty, not with its content")
        for name in sorted(set(wanted_home) - set(held)):
            problems.append(f"runtime/home.zip: {name} is missing (the policy names it)")
        inside("home.zip", {k: v for k, v in held.items() if not CACHE_ENTRY.match(k)})
    return problems


def zipped(entries: Iterable[tuple[str, Path | bytes]], epoch: tuple[int, int, int, int, int, int]) -> bytes:
    """A deterministic archive of the entries: sorted, one timestamp, one mode."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name, src in sorted(entries, key=lambda e: e[0]):
            info = zipfile.ZipInfo(name, epoch)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, src if isinstance(src, bytes) else src.read_bytes())
    return buf.getvalue()
