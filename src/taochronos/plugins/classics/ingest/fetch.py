"""Fetching sources into the data directory and recording them in ``corpus/sources.lock.yaml``.

Only public, licensed sources are fetched, one repository at a time (no parallel crawling).  The lockfile
records what was ingested — repository, commit, file count and size — so a corpus build is reproducible
and every book's provenance (Gate G0) can be checked.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Iterable

import yaml

Log = Callable[[str], None]


def _clone(url: str, dest: Path, timeout: int = 900) -> tuple[bool, str]:
    env = {**os.environ, "GIT_LFS_SKIP_SMUDGE": "1", "GIT_TERMINAL_PROMPT": "0"}
    for attempt in range(2):
        proc = subprocess.run(["git", "clone", "-q", "--depth", "1", url, str(dest)], capture_output=True, text=True,
                              timeout=timeout, env=env)
        if proc.returncode == 0:
            return True, ""
        err = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ["?"]
        if "429" in err[0] and attempt == 0:
            time.sleep(5)
            continue
        return False, err[0]
    return False, "rate limited"


def fetch_kanripo(catalog: dict[str, Any], dest: Path, *, only: Iterable[str] | None = None, log: Log = print) -> dict[str, Any]:
    """Shallow-clone every catalogued text repository that is not present yet."""
    dest.mkdir(parents=True, exist_ok=True)
    wanted = {x.lower() for x in only} if only else None
    pattern = (catalog.get("source") or {}).get("repo", "https://github.com/kanripo/{kr_lower}")
    done: dict[str, Any] = {"ok": [], "skipped": [], "failed": {}}
    for entry in catalog["books"]:
        kr = entry["kr"]
        if wanted is not None and kr.lower() not in wanted and entry["id"].lower() not in wanted:
            continue
        target = dest / kr
        if (target / ".git").exists():
            done["skipped"].append(kr)
            continue
        ok, err = _clone(pattern.format(kr_lower=kr.lower(), kr=kr), target)
        if ok:
            done["ok"].append(kr)
            log(f"  fetched {kr}")
        else:
            done["failed"][kr] = err
            log(f"  FAILED {kr}: {err}")
    return done


def repo_facts(repo: Path) -> dict[str, Any]:
    files = [p for p in repo.glob("*.txt")]
    commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    date = subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%cs"], capture_output=True, text=True).stdout.strip()
    return {"commit": commit or None, "commit_date": date or None, "files": len(files), "bytes": sum(p.stat().st_size for p in files)}


def write_lock(lock_path: Path, source: str, catalog: dict[str, Any], sources_dir: Path) -> dict[str, Any]:
    """Record the fetched state of a source in the lockfile (other sources are left untouched)."""
    lock: dict[str, Any] = {}
    if lock_path.exists():
        lock = yaml.safe_load(lock_path.read_text(encoding="utf-8")) or {}
    src = catalog.get("source") or {}
    texts: dict[str, Any] = {}
    for entry in catalog["books"]:
        repo = sources_dir / entry["kr"]
        if (repo / ".git").exists():
            url = src.get("repo", "").format(kr_lower=entry["kr"].lower(), kr=entry["kr"])
            texts[entry["kr"]] = {"book": entry["id"], "repo": url, **repo_facts(repo)}
    lock[source] = {
        "name": src.get("name"),
        "license": src.get("license"),
        "license_url": src.get("license_url"),
        "catalog": Path(catalog.get("_path", "")).name,
        "locked": _dt.date.today().isoformat(),
        "texts": texts,
    }
    header = ("# Sources ingested into the TaoChronos corpus store (written by `taochronos corpus fetch` / `corpus unpack`).\n"
              "# The texts live in the data directory, not in git; this file pins exactly what was ingested.\n")
    lock_path.write_text(header + yaml.safe_dump(lock, allow_unicode=True, sort_keys=False, width=140), encoding="utf-8")
    return lock[source]


# ---------------------------------------------------------------- user-supplied archives (笈成)
SEVEN_ZIP_MAGIC = b"7z\xbc\xaf\x27\x1c"


def _volume_number(path: Path) -> int:
    m = re.search(r"\.(\d{3})$", path.name)
    return int(m.group(1)) if m else 0


def archive_name(path: Path) -> str:
    """``15e4b962-jc_1_4_8_all.7z.001`` → ``jc_1_4_8_all.7z`` (volume suffix and upload prefix removed)."""
    name = re.sub(r"\.\d{3}$", "", path.name)
    return re.sub(r"^[0-9a-f]{8}-", "", name)


def unpack_archive(volumes: Iterable[Path], dest: Path, *, log: Log = print) -> dict[str, Any]:
    """Join the volumes of a split 7z archive (.001, .002, …) in order, check it and extract it into ``dest``.

    Uses the ``7z`` program when installed, otherwise the ``py7zr`` package; the joined archive is kept next to
    the extracted files so its hash can be checked again."""
    vols = sorted((Path(v) for v in volumes), key=_volume_number)
    if not vols:
        raise ValueError("no archive volumes given")
    numbers = [_volume_number(v) for v in vols]
    if len(vols) > 1 and numbers != list(range(1, len(vols) + 1)):
        raise ValueError(f"volumes must be numbered .001 … .{len(vols):03d} without gaps (got {numbers})")
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / archive_name(vols[0])
    digest = hashlib.sha256()
    with open(target, "wb") as out:
        for v in vols:
            with open(v, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    digest.update(chunk)
                    out.write(chunk)
    with open(target, "rb") as f:
        if f.read(6) != SEVEN_ZIP_MAGIC:
            raise ValueError(f"{target.name} is not a 7z archive (is the first volume missing?)")
    log(f"  joined {len(vols)} volume(s) → {target} ({target.stat().st_size} bytes)")
    seven = shutil.which("7z") or shutil.which("7za")
    if seven:
        proc = subprocess.run([seven, "x", "-y", f"-o{dest}", str(target)], capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout).strip()[-800:])
    else:
        try:
            import py7zr  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - depends on the machine
            raise RuntimeError("extracting needs the 7z program (p7zip) or `pip install py7zr`") from exc
        with py7zr.SevenZipFile(target, mode="r") as z:
            z.extractall(path=dest)
    log(f"  extracted into {dest}")
    return {"archive": target.name, "sha256": digest.hexdigest(), "archive_bytes": target.stat().st_size, "volumes": len(vols)}


def tree_facts(root: Path, pattern: str = "data/**/*.txt") -> dict[str, Any]:
    """Count and fingerprint the text files of an unpacked collection (sha256 over sorted "path<TAB>sha1" lines)."""
    lines, total, latest = [], 0, ""
    for path in sorted(root.glob(pattern)):
        data = path.read_bytes()
        total += len(data)
        lines.append(f"{path.relative_to(root).as_posix()}\t{hashlib.sha1(data).hexdigest()}")
        latest = max(latest, _dt.date.fromtimestamp(path.stat().st_mtime).isoformat())
    return {"files": len(lines), "text_bytes": total, "latest_file_date": latest or None,
            "tree_sha256": hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()}


def write_archive_lock(lock_path: Path, source: str, facts: dict[str, Any]) -> dict[str, Any]:
    """Record a user-supplied archive source in the lockfile (other sources are left untouched)."""
    lock: dict[str, Any] = {}
    if lock_path.exists():
        lock = yaml.safe_load(lock_path.read_text(encoding="utf-8")) or {}
    lock[source] = {**(lock.get(source) or {}), **facts, "locked": _dt.date.today().isoformat()}
    header = ("# Sources ingested into the TaoChronos corpus store (written by `taochronos corpus fetch` / `corpus unpack`).\n"
              "# The texts live in the data directory, not in git; this file pins exactly what was ingested.\n")
    lock_path.write_text(header + yaml.safe_dump(lock, allow_unicode=True, sort_keys=False, width=140), encoding="utf-8")
    return lock[source]
