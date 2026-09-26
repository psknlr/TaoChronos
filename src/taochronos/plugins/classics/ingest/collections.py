"""The collections read through :mod:`.documents`: where each comes from, how it is fetched and read, and how its
texts are judged against the store.

Sources rank in the order their texts are trusted as witnesses — curated editions first (Kanripo, 笈成), then
independent transcriptions of prints (McGill), the volunteers' transcriptions on Wikisource, and last the web
copies (TCM-Ancient-Books, tcmoc, the Hugging Face dataset).  A collection's texts are compared only with the
books of higher-ranked sources and with each other, so a catalog comes out the same whatever order the sources
are ingested in.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import mcgill, textsets, wikisource
from .documents import Document
from .fetch import _clone

Log = Callable[[str], None]

RANK = {"kanripo": 0, "jicheng": 1, "mcgill": 2, "wikisource": 3, "tcm-ancient-books": 4, "tcmoc": 5, "hf-tcm-canon": 6}


@dataclass(frozen=True)
class Collection:
    source: dict[str, Any]
    prefix: str  # book ids: <prefix>_<code>
    subdir: str  # under <data>/sources
    fetch: Callable[[Path, Log], dict[str, Any]]  # → facts for the lockfile
    read: Callable[[Path], list[Document]]
    duplicate: float | None  # see build_document_catalog
    same_work: float | None
    derivative: bool

    @property
    def id(self) -> str:
        return str(self.source["id"])

    @property
    def rank(self) -> int:
        return RANK[self.id]


def _git(url: str, pattern: str) -> Callable[[Path, Log], dict[str, Any]]:
    def fetch(root: Path, log: Log) -> dict[str, Any]:
        if not (root / ".git").exists():
            root.parent.mkdir(parents=True, exist_ok=True)
            ok, err = _clone(url, root, timeout=3600)
            if not ok:
                raise RuntimeError(f"git clone {url} failed: {err}")
            log(f"  cloned {url}")
        return git_facts(root, url, pattern)

    return fetch


def git_facts(root: Path, url: str, pattern: str) -> dict[str, Any]:
    def git(*a: str) -> str:
        return subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True).stdout.strip()

    files = [p for p in root.glob(pattern) if p.is_file()]
    return {"repo": url, "commit": git("rev-parse", "HEAD") or None, "commit_date": git("log", "-1", "--format=%cs") or None,
            "files": len(files), "bytes": sum(p.stat().st_size for p in files)}


HF_DATASET = "wangekxy/classical-tcm-canon"
HF_FILES = ("classical-tcm-canon.parquet", "README.md")


def _hf_fetch(root: Path, log: Log) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    api = subprocess.run(["curl", "-sS", "--fail", f"https://huggingface.co/api/datasets/{HF_DATASET}"], capture_output=True, text=True)
    sha = json.loads(api.stdout).get("sha") if api.returncode == 0 and api.stdout.startswith("{") else None
    for name in HF_FILES:
        path = root / name
        if path.exists():
            continue
        url = f"https://huggingface.co/datasets/{HF_DATASET}/resolve/{sha or 'main'}/{name}"
        for attempt in range(4):
            p = subprocess.run(["curl", "-sS", "--fail", "-L", "-o", str(path), url], capture_output=True, text=True)
            if p.returncode == 0:
                break
            time.sleep(2 ** (attempt + 1))
        else:
            raise RuntimeError(f"download failed: {url}: {p.stderr[-300:]}")
        log(f"  downloaded {name}")
    return {"dataset": f"https://huggingface.co/datasets/{HF_DATASET}", "revision": sha,
            "files": {n: {"bytes": (root / n).stat().st_size, "sha256": _sha256(root / n)} for n in HF_FILES if (root / n).exists()}}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _ws_fetch(root: Path, log: Log) -> dict[str, Any]:
    return wikisource.fetch(root, log=log)


COLLECTIONS: dict[str, Collection] = {c.id: c for c in (
    Collection(mcgill.SOURCE, "mg", "mcgill/gynaecology", _git(mcgill.SOURCE["url"], "xml-files/*.xml"), mcgill.read,
               duplicate=None, same_work=None, derivative=False),
    # most pages are web copies (zysj.com.cn / 中医瑰宝苑), many converted back to traditional characters ({{s2t}})
    Collection(wikisource.SOURCE, "ws", "wikisource", _ws_fetch, wikisource.read, duplicate=0.85, same_work=0.4, derivative=True),
    Collection(textsets.TAB_SOURCE, "tab", "tcm-ancient-books/repo", _git(textsets.TAB_SOURCE["url"], "*.txt"), textsets.read_tab,
               duplicate=0.85, same_work=0.4, derivative=True),
    Collection(textsets.TCMOC_SOURCE, "oc", "tcmoc/repo", _git(textsets.TCMOC_SOURCE["url"], "books/*"), textsets.read_tcmoc,
               duplicate=0.85, same_work=0.4, derivative=True),
    Collection(textsets.HF_SOURCE, "hf", "hf-classical-tcm-canon", _hf_fetch,
               lambda root: textsets.read_hf(root / "classical-tcm-canon.parquet"), duplicate=0.85, same_work=0.4, derivative=True),
)}


__all__ = ["COLLECTIONS", "Collection", "RANK", "git_facts"]
