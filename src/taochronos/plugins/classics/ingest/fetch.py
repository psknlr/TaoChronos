"""Fetching sources into the data directory and recording them in ``corpus/sources.lock.yaml``.

Only public, licensed sources are fetched, one repository at a time (no parallel crawling).  The lockfile
records what was ingested — repository, commit, file count and size — so a corpus build is reproducible
and every book's provenance (Gate G0) can be checked.
"""

from __future__ import annotations

import datetime as _dt
import os
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
    header = ("# Sources ingested into the TaoChronos corpus store (written by `taochronos corpus fetch`).\n"
              "# The texts live in the data directory, not in git; this file pins exactly what was ingested.\n")
    lock_path.write_text(header + yaml.safe_dump(lock, allow_unicode=True, sort_keys=False, width=140), encoding="utf-8")
    return lock[source]
