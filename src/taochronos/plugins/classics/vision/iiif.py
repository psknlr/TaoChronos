"""IIIF: the page images of an image witness, one page at a time, for reading (T1).

The image-witness catalogs (``corpus/catalog/images``) record IIIF manifests; nothing is downloaded when they are built.
Here one page is fetched on request — the canvas of a manifest (Presentation API 2 or 3), at a chosen width through the
Image API — into the local data directory, with the holder's terms kept beside it.  Images are never committed; their
use follows the terms the catalog records (研医会 CC BY-NC 4.0, 庆应 CC BY-NC-SA 4.0 …).
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any

USER_AGENT = "TaoChronos/0.1 (research harness; one page at a time)"


def _first(value: Any) -> Any:
    return value[0] if isinstance(value, list) and value else value


def canvases(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """The pages of a manifest: label, size, the image service (if any) and a full image URL."""
    out: list[dict[str, Any]] = []
    if "sequences" in manifest:  # Presentation 2
        for c in (_first(manifest.get("sequences")) or {}).get("canvases", []):
            image = _first(c.get("images")) or {}
            res = image.get("resource") or {}
            service = _first(res.get("service")) or {}
            out.append({"label": _label(c.get("label")), "width": c.get("width"), "height": c.get("height"),
                        "service": service.get("@id") or service.get("id"), "image": res.get("@id") or res.get("id")})
    else:  # Presentation 3
        for c in manifest.get("items", []):
            page = _first(c.get("items")) or {}
            anno = _first(page.get("items")) or {}
            body = anno.get("body") or {}
            body = _first(body) if isinstance(body, list) else body
            service = _first(body.get("service")) or {}
            out.append({"label": _label(c.get("label")), "width": c.get("width"), "height": c.get("height"),
                        "service": service.get("@id") or service.get("id"), "image": body.get("id")})
    return out


def _label(label: Any) -> str:
    if isinstance(label, dict):  # {"none": ["1"]}, {"ja": ["…"]}
        for v in label.values():
            return str(_first(v))
        return ""
    return "" if label is None else str(_first(label) if isinstance(label, list) else label)


def image_url(canvas: dict[str, Any], width: int = 1600) -> str:
    if canvas.get("service"):
        return f"{canvas['service'].rstrip('/')}/full/{width},/0/default.jpg"
    if canvas.get("image"):
        return canvas["image"]
    raise ValueError("the canvas has no image")


def load_manifest(source: str) -> dict[str, Any]:
    if source.startswith(("http://", "https://")):
        req = urllib.request.Request(source, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    return json.loads(Path(source).read_text(encoding="utf-8"))


def fetch_page(source: str, page: int, dest_dir: str | Path, *, width: int = 1600, terms: str | None = None) -> dict[str, Any]:
    """Fetch page ``page`` (1-based) of a manifest into ``dest_dir``; returns the file, the URL and the terms."""
    manifest = load_manifest(source)
    pages = canvases(manifest)
    if not 1 <= page <= len(pages):
        raise ValueError(f"the manifest has {len(pages)} pages")
    url = image_url(pages[page - 1], width)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
        media = resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    name = f"page-{page:04d}" + (".png" if "png" in media else ".jpg")
    path = dest / name
    path.write_bytes(data)
    meta = {"manifest": source, "page": page, "label": pages[page - 1]["label"], "url": url, "media_type": media,
            "terms": terms or manifest.get("license") or manifest.get("rights") or manifest.get("attribution"),
            "file": str(path)}
    (dest / (name + ".json")).write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


__all__ = ["canvases", "fetch_page", "image_url", "load_manifest"]
