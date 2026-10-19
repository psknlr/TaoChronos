"""The full corpus on Cloudflare: what runs in the site's container (``cloud/corpus/``, deployed by .github/workflows/site.yml).

The page at https://chat.impf.ai is served by a Worker (``cloud/site``); its ``/api/…`` calls go to a Durable Object
that starts this container on demand and forwards them, adding the token it started the container with.  The container
has no address of its own; it serves the chat runtime's API (``taochronos.chat.server``) on port 8080 over the full
corpus as the site carries it (``taochronos web store``: every source the site may publish, never ``NEVER_PACKED``).

* ``python -m taochronos.chat.cloud prepare <store.sqlite.xz> <data> [--manifest cloud/store.json]`` — at image build:
  unpack the store, check it against the manifest, build its full-text index with this code's normalizer, and warm the
  caches the tools build on first use (a container starts from its image each time: what it builds at run time is lost
  when it sleeps);
* ``python -m taochronos.chat.cloud serve [--port 8080]`` — in the container: the API, with no web client and no model
  proxy; every request must carry ``$TAOCHRONOS_TOKEN`` (``X-TC-Token``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import os
import shutil
import sqlite3
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

# what the tools build on first use, built here once (each call is cheap once its cache exists)
WARM: list[tuple[str, dict[str, Any]]] = [
    ("classics.search", {"query": "桂枝汤", "k": 5}),
    ("classics.search", {"query": "消渴", "k": 5, "before": 1368}),
    ("classics.canon", {"limit": 20}),
    ("study.formula", {"name": "桂枝汤"}),
    ("study.herb", {"name": "黄连"}),
    ("study.term", {"term": "消渴"}),
    ("study.concordance", {"text": "太阳之为病，脉浮，头项强痛而恶寒"}),
    ("study.commentaries", {"text": "太阳之为病，脉浮，头项强痛而恶寒"}),
    ("study.clause", {"text": "太阳之为病，脉浮，头项强痛而恶寒"}),
    ("study.punctuate", {"text": "太阳之为病脉浮头项强痛而恶寒"}),
    ("study.citations", {"target": "伤寒论"}),
    ("study.network", {"target": "桂枝汤"}),
    ("study.pairs", {"herb": "桂枝"}),
    ("study.schools", {}),
    # every case collection read once and kept beside the store (study-cache/cases-*.json.gz): the case tools then load
    # it in seconds instead of reading tens of thousands of records again
    ("study.casefind", {"findings": ["脉浮数"]}),
    ("study.similar", {"text": "发热，咳嗽，脉浮数"}),
]


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def unpack(xz: Path, dest: Path, manifest: dict[str, Any] | None = None) -> None:
    """The compressed store into ``dest``, checked against the manifest's digests (``cloud/store.json``)."""
    if manifest and _sha256(xz) != manifest["sha256"]:
        raise SystemExit(f"{xz}: its sha256 is not the one cloud/store.json names")
    dest.parent.mkdir(parents=True, exist_ok=True)
    raw = hashlib.sha256()
    with lzma.open(xz, "rb") as src, open(dest, "wb") as out:
        while chunk := src.read(1 << 22):
            raw.update(chunk)
            out.write(chunk)
    if manifest and raw.hexdigest() != manifest["raw_sha256"]:
        raise SystemExit(f"{xz}: the store it unpacks to is not the one cloud/store.json names")


def warm(runtime: Any, calls: list[tuple[str, dict[str, Any]]] = WARM, log: Callable[[str], None] = _log) -> list[dict[str, Any]]:
    """Run each call once (a failure is reported, not raised: a tool that cannot warm is built on first use instead)."""
    done = []
    for name, args in calls:
        started = time.perf_counter()
        out = runtime.call(name, args, max_chars=2000)
        seconds = round(time.perf_counter() - started, 1)
        log(f"  {name} {json.dumps(args, ensure_ascii=False)}: {'ok' if out.get('ok') else out.get('error')} ({seconds} s)")
        done.append({"tool": name, "ok": bool(out.get("ok")), "seconds": seconds})
    return done


def prepare(xz: Path, data: Path, manifest: dict[str, Any] | None = None, *, calls: list[tuple[str, dict[str, Any]]] = WARM) -> dict[str, Any]:
    from ..config import find_home
    from ..plugins.classics.domain import DomainPack
    from ..plugins.classics.webcorpus import index_state, index_store
    from . import ChatRuntime

    home = find_home()
    path = data / "corpus" / "tcm.sqlite"
    started = time.perf_counter()
    unpack(xz, path, manifest)
    _log(f"unpacked {path.stat().st_size:,} bytes ({time.perf_counter() - started:.0f} s)")
    normalize = DomainPack(home / "domains" / "classics").variants.normalize_text
    last = [0.0]

    def progress(done: int, total: int) -> None:
        if time.perf_counter() - last[0] > 30 or done == total:
            last[0] = time.perf_counter()
            _log(f"  indexed {done:,}/{total:,} passages")

    index_store(path, normalize, progress=progress, chunk=20000)
    state = index_state(path)
    if state["state"] != "built":
        raise SystemExit(f"the index was not built: {state}")
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=DELETE")
    db.execute("VACUUM")
    db.close()
    _log(f"index built, store {path.stat().st_size:,} bytes ({time.perf_counter() - started:.0f} s)")
    runtime = ChatRuntime.create("full-corpus", home=home, data_dir=data, kind="server", ephemeral=True)
    info = runtime.info()
    _log(f"{info['corpus']['books']} books, {info['corpus']['passages']:,} passages, {info['tools']['offered']} tools; warming:")
    warmed = warm(runtime, calls)
    runtime.h.corpus.store.close()
    del runtime
    # the image keeps the store and the caches built beside it; not the warm-up's own traces
    for p in data.iterdir():
        if p.is_dir() and p.name != "corpus":
            shutil.rmtree(p)
        elif p.is_file():
            p.unlink()
    for db_path in (data / "corpus").rglob("*.sqlite"):  # whatever the warm-up wrote, in the file itself (no journal)
        db = sqlite3.connect(db_path)
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        db.execute("PRAGMA journal_mode=DELETE")
        db.close()
    for p in sorted(data.rglob("*"), reverse=True):  # the same bytes make the same image layer
        os.utime(p, (0, 0), follow_symlinks=False)
    return {"corpus": info["corpus"], "warmed": warmed, "seconds": round(time.perf_counter() - started)}


def upload(path: Path, manifest: dict[str, Any], site: str, token: str, *, log: Callable[[str], None] = _log,
           attempts: int = 5) -> dict[str, Any]:
    """Put the compressed store into the site's Workers KV namespace through its Worker (``PUT /api/store/<sha256>/
    part-NNN``, the token as a bearer; ``cloud/site``), part by part: a part already there (same sha256) is not sent again."""
    import urllib.error
    import urllib.request

    if _sha256(path) != manifest["sha256"]:
        raise SystemExit(f"{path}: its sha256 is not the one the manifest names")
    base = f"{site.rstrip('/')}/api/{manifest['key'].rstrip('/')}"
    headers = {"Authorization": f"Bearer {token}", "User-Agent": "taochronos-upload"}
    sent = kept = 0
    with open(path, "rb") as f:
        for part in manifest["parts"]:
            url = f"{base}/{part['name']}"
            body = f.read(part["bytes"])
            if hashlib.sha256(body).hexdigest() != part["sha256"]:
                raise SystemExit(f"{part['name']}: not the bytes the manifest names")
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers, method="HEAD"), timeout=60) as r:
                    if r.headers.get("X-Content-SHA256") == part["sha256"]:
                        kept += 1
                        log(f"{part['name']}: already there")
                        continue
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    raise SystemExit(f"{url}: HTTP {exc.code} {exc.read()[:300]!r}") from exc
            for attempt in range(1, attempts + 1):
                request = urllib.request.Request(url, data=body, method="PUT", headers={
                    **headers, "Content-Type": "application/octet-stream", "X-Content-SHA256": part["sha256"]})
                try:
                    started = time.perf_counter()
                    with urllib.request.urlopen(request, timeout=900) as r:
                        answer = json.loads(r.read() or b"{}")
                    log(f"{part['name']}: {part['bytes']:,} bytes in {time.perf_counter() - started:.0f} s {answer}")
                    sent += 1
                    break
                except urllib.error.HTTPError as exc:
                    if exc.code in (400, 401, 403, 404, 413):
                        raise SystemExit(f"{url}: HTTP {exc.code} {exc.read()[:300]!r}") from exc
                    log(f"{part['name']}: HTTP {exc.code}, again ({attempt}/{attempts})")
                except (urllib.error.URLError, TimeoutError, OSError) as exc:
                    log(f"{part['name']}: {exc}, again ({attempt}/{attempts})")
                if attempt == attempts:
                    raise SystemExit(f"{part['name']}: not uploaded after {attempts} attempts")
                time.sleep(2 ** attempt)
    return {"key": manifest["key"], "parts": len(manifest["parts"]), "sent": sent, "already": kept, "bytes": manifest["bytes"]}


def _preload(runtime: Any) -> None:
    """The case collections loaded from the image's cache while the first requests are answered: a case tool asked
    soon after the container wakes waits for nothing (a failure only means the tool loads them on first use)."""
    started = time.perf_counter()
    try:
        n = runtime.h.capabilities.get("study").warm_cases()
        _log(f"case records ready: {n:,} ({time.perf_counter() - started:.1f} s)")
    except Exception as exc:  # noqa: BLE001 - a preload never stops the server
        _log(f"case records not preloaded: {type(exc).__name__}: {exc}")


def serve(port: int = 8080) -> None:
    from .server import ChatServer
    from . import ChatRuntime

    token = os.environ.get("TAOCHRONOS_TOKEN") or None
    if not token:
        raise SystemExit("TAOCHRONOS_TOKEN is not set: the container is started by the site's Worker, which gives it one")
    runtime = ChatRuntime.create("full-corpus", kind="server")
    info = runtime.info()  # counted before the port opens: the first request answers at once
    server = ChatServer(("0.0.0.0", port), runtime, web_root=None, proxy=False, token=token)
    threading.Thread(target=_preload, args=(runtime,), name="case-records", daemon=True).start()
    _log(f"TaoChronos {info['version']} · {info['profile']} · {info['corpus']['books']} 部书 · "
         f"{info['corpus']['passages']} 段 · {info['tools']['offered']} 个工具 · :{port}")
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m taochronos.chat.cloud", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("prepare", help="unpack, check and index the store; warm the caches (image build)")
    sp.add_argument("store", help="the compressed store (taochronos web store), or the directory holding <sha256>.sqlite.xz")
    sp.add_argument("data", help="the data directory to fill")
    sp.add_argument("--manifest", help="cloud/store.json: the digests to check against")
    sp = sub.add_parser("serve", help="serve the API (the container's command)")
    sp.add_argument("--port", type=int, default=int(os.environ.get("PORT") or 8080))
    args = p.parse_args(argv)
    if args.cmd == "prepare":
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8")) if args.manifest else None
        store = Path(args.store)
        if store.is_dir():
            if not manifest:
                raise SystemExit("a directory needs --manifest: it names the store's sha256")
            store = store / f"{manifest['sha256']}.sqlite.xz"
        print(json.dumps(prepare(store, Path(args.data), manifest), ensure_ascii=False, indent=1))
    else:
        serve(args.port)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
