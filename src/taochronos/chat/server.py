"""``taochronos serve``: the web client's local server — the full corpus behind the chat runtime.

It serves the web client (``web/``) and a small JSON API over :class:`~taochronos.chat.ChatRuntime`:

* ``GET  /api/info`` — corpus, tools, the system prompt;  ``GET /api/catalog?mode=core|all`` — tool definitions;
* ``POST /api/call`` ``{name, arguments, max_chars}`` — run one tool;  ``GET /api/passage?id=`` — a passage in full;
* ``POST /api/research`` — start a research run in the background;  ``GET /api/research/<job>`` — its progress and outcome;
* ``POST /api/data`` ``{name, data}`` (the file's bytes in base64) — add a file to 我的资料;  ``GET /api/data`` — the
  datasets;  ``POST /api/data/remove`` ``{id}``, ``POST /api/data/clear`` — remove one, or all.  Only a server bound to
  this machine takes a user's data: one other machines reach would mix its visitors' data in one runtime;
* ``POST /api/llm`` — forward one model request (``X-TC-Target: <url>``) to a provider listed in
  :mod:`taochronos.chat.providers` and stream the answer back, for providers a browser cannot call directly.
  The key travels with the request and is never stored or logged; with ``--env-keys`` a request without one gets the
  provider's key from this machine's environment.

Only this machine's pages, the server's own pages, the published client (``https://chat.impf.ai``) and origins
named with ``--allow-origin`` may call the API (CORS, Private Network Access); the Host header must name this machine,
so a rebound DNS name cannot reach it.  It binds to 127.0.0.1 unless told otherwise; bound to another address it
requires an access token (``--token``, else one is generated and printed), carried by every API request as
``X-TC-Token`` — the page takes it from its address (``#token=…``) once.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import mimetypes
import os
import secrets
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from .providers import key_env_for, proxy_hosts, web_providers

PAGES_ORIGIN = "https://chat.impf.ai"  # the published client (GitHub Pages under IMPF-AI's domain)
PAGES_ORIGINS = (PAGES_ORIGIN, "http://chat.impf.ai", "https://psknlr.github.io")  # before HTTPS is enforced; the old address
ENV_KEY = "tc-env-key"  # what the client sends as a key when it relies on --env-keys
LOCAL_NAMES = {"localhost", "127.0.0.1", "::1", "[::1]"}
FORWARD = ("content-type", "accept", "authorization", "x-api-key", "anthropic-version", "anthropic-beta",
           "anthropic-dangerous-direct-browser-access", "http-referer", "x-title", "x-stainless-retry-count")
ALLOW_HEADERS = "content-type, authorization, x-api-key, x-tc-target, x-tc-token, anthropic-version, anthropic-beta, " \
                "anthropic-dangerous-direct-browser-access, http-referer, x-title, x-stainless-arch, x-stainless-lang, " \
                "x-stainless-os, x-stainless-package-version, x-stainless-runtime, x-stainless-runtime-version, " \
                "x-stainless-retry-count, x-stainless-timeout"
TYPES = {".mjs": "text/javascript; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".wasm": "application/wasm",
         ".json": "application/json; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml",
         ".html": "text/html; charset=utf-8", ".zip": "application/zip", ".whl": "application/zip",
         ".webmanifest": "application/manifest+json", ".png": "image/png", ".ico": "image/x-icon",
         ".md": "text/markdown; charset=utf-8", ".txt": "text/plain; charset=utf-8"}


class ChatServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], runtime: Any, *, web_root: Path | None, origins: list[str] | None = None,
                 env_keys: bool = False, proxy: bool = True, home: Path | None = None, quiet: bool = True,
                 token: str | None = None, allow_hosts: list[str] | None = None) -> None:
        super().__init__(address, Handler)
        self.runtime = runtime
        self.token = token or None
        self.web_root = web_root.resolve() if web_root else None
        self.origins = {o.rstrip("/") for o in (origins or [])} | set(PAGES_ORIGINS)
        self.env_keys = env_keys
        self.proxy = proxy
        self.proxy_hosts = proxy_hosts() | {allowed_host(h) for h in allow_hosts or ()}
        self.home = home
        self.quiet = quiet
        self._runtime_files: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def origin_allowed(self, origin: str | None, host: str | None = None) -> bool:
        if not origin:
            return True  # not a browser page (curl, the page's own origin on a same-origin GET)
        if "*" in self.origins or origin.rstrip("/") in self.origins:
            return True
        parts = urlsplit(origin)
        if parts.scheme not in ("http", "https"):
            return False
        # this machine's pages, and the server's own pages wherever it is reached (a LAN address, a domain)
        return (parts.hostname or "") in LOCAL_NAMES or bool(host and parts.netloc.lower() == host.strip().lower())

    @property
    def private(self) -> bool:
        """Bound to this machine only: the one person at it is the only visitor, and may bring their own data."""
        return self.server_address[0] in ("127.0.0.1", "::1", "localhost")

    def token_ok(self, given: str | None) -> bool:
        return self.token is None or hmac.compare_digest((given or "").encode(), self.token.encode())

    def runtime_file(self, name: str) -> bytes | None:
        """The in-browser runtime's files when the client is served from here and was not built (``taochronos web
        build``): made from this checkout on first use."""
        if name not in ("taochronos.zip", "home.zip", "manifest.json") or self.home is None:
            return None
        with self._lock:
            if name not in self._runtime_files:
                from .build import home_zip, manifest, package_zip

                pkg, home = package_zip(), home_zip(self.home)
                self._runtime_files.update({"taochronos.zip": pkg, "home.zip": home,
                                            "manifest.json": json.dumps(manifest(pkg, home), ensure_ascii=False).encode()})
            return self._runtime_files[name]


class Handler(BaseHTTPRequestHandler):
    server: ChatServer
    protocol_version = "HTTP/1.1"
    server_version = "TaoChronos"

    # ------------------------------------------------------------------ plumbing
    def log_message(self, fmt: str, *args: Any) -> None:  # requests are not logged (a proxied request carries a key)
        if not self.server.quiet:
            sys.stderr.write(f"{self.command} {urlsplit(self.path).path}\n")

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
        bound = self.server.server_address[0]
        return host in {"localhost", "127.0.0.1", "::1"} or host == bound or bound in ("0.0.0.0", "::")

    def _cors(self) -> None:
        origin = self.headers.get("Origin")
        if origin and self.server.origin_allowed(origin, self.headers.get("Host")):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Expose-Headers", "content-type, x-request-id")
        if self.headers.get("Access-Control-Request-Private-Network") == "true":
            self.send_header("Access-Control-Allow-Private-Network", "true")

    def _send(self, status: int, body: bytes, content_type: str, *, cache: str = "no-store") -> None:
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, value: Any, status: int = 200) -> None:
        self._send(status, json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"), "application/json; charset=utf-8")

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _refuse(self) -> bool:
        if not self._host_ok():
            self._json({"error": "this server answers only to this machine's host names"}, 421)
            return True
        if not self.server.origin_allowed(self.headers.get("Origin"), self.headers.get("Host")):
            self._json({"error": f"origin {self.headers.get('Origin')} is not allowed (start with --allow-origin)"}, 403)
            return True
        if not self.server.token_ok(self.headers.get("X-TC-Token")):
            self._json({"error": "this server needs its access token (设置 → 运行环境 → 访问令牌)", "token_required": True}, 401)
            return True
        return False

    # ------------------------------------------------------------------ verbs
    def do_OPTIONS(self) -> None:  # CORS / Private Network Access preflight
        self.send_response(204 if self.server.origin_allowed(self.headers.get("Origin"), self.headers.get("Host")) else 403)
        self._cors()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", ALLOW_HEADERS)
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        path = unquote(url.path)
        if path.startswith("/api/"):
            if self._refuse():
                return
            query = {k: v[-1] for k, v in parse_qs(url.query).items()}
            rt = self.server.runtime
            try:
                if path == "/api/info":
                    return self._json({**rt.info(), "proxy": self.server.proxy, "env_keys": self.server.env_keys})
                if path == "/api/catalog":
                    return self._json(rt.catalog(query.get("mode", "core")))
                if path == "/api/providers":
                    return self._json(web_providers())
                if path == "/api/passage":
                    return self._json(rt.passage(query.get("id", "")))
                if path == "/api/data":
                    return self._json(rt.data_list() if self.server.private else {"datasets": [], "private": False})
                if path.startswith("/api/research/"):
                    return self._json(rt.job(path.rsplit("/", 1)[-1]))
                if path.startswith("/api/session/"):
                    return self._json(rt.session_view(path.rsplit("/", 1)[-1], what=query.get("what", "summary"),
                                                      hypothesis=query.get("hypothesis"), section=query.get("section")))
            except Exception as exc:
                return self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
            return self._json({"error": f"no such endpoint {path}"}, 404)
        self._static(path)

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if not path.startswith("/api/"):
            return self._json({"error": "not found"}, 404)
        if self._refuse():
            return
        if path == "/api/llm" or path.startswith("/api/llm/"):
            return self._proxy()
        try:
            data = json.loads(self._body() or b"{}")
        except json.JSONDecodeError as exc:
            return self._json({"error": f"invalid JSON: {exc}"}, 400)
        rt = self.server.runtime
        try:
            if path == "/api/call":
                return self._json(rt.call(str(data.get("name", "")), data.get("arguments") or {},
                                          max_chars=int(data.get("max_chars") or 16000)))
            if path.startswith("/api/data"):
                return self._data(path, data)
            if path == "/api/research":
                args = dict(data.get("arguments") or data)
                question = str(args.pop("question", "") or "").strip()
                if not question:
                    return self._json({"error": "a research run needs a question"}, 400)
                keep = ("focus_terms", "tracks", "max_rounds", "forbidden_assumptions", "holdout_after", "books")
                job = rt.start_research(question, **{k: args[k] for k in keep if args.get(k) not in (None, "", [])})
                return self._json({"job": job})
        except Exception as exc:
            return self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
        return self._json({"error": f"no such endpoint {path}"}, 404)

    def _data(self, path: str, data: dict[str, Any]) -> None:
        """我的资料: a file added, a dataset removed, all removed — on a server only this machine reaches."""
        rt = self.server.runtime
        if not self.server.private:
            return self._json({"ok": False, "error": "这个服务可由其他机器访问：个人资料不在这里处理，请在浏览器内处理"}, 403)
        if path == "/api/data":
            try:
                raw = base64.b64decode(str(data.get("data") or ""), validate=True)
            except (binascii.Error, ValueError):
                return self._json({"ok": False, "error": "文件内容须以 base64 编码"}, 400)
            return self._json(rt.data_add(str(data.get("name") or "资料"), raw))
        if path == "/api/data/remove":
            return self._json(rt.data_remove(str(data.get("id") or "")))
        if path == "/api/data/clear":
            return self._json(rt.data_clear())
        return self._json({"error": f"no such endpoint {path}"}, 404)

    # ------------------------------------------------------------------ static files
    def _static(self, path: str) -> None:
        name = path.lstrip("/") or "index.html"
        root = self.server.web_root
        if name == "providers.json" and not (root and (root / name).is_file()):
            return self._send(200, json.dumps(web_providers(), ensure_ascii=False).encode(), TYPES[".json"])
        if name.startswith("runtime/"):
            made = self.server.runtime_file(name.split("/", 1)[1])
            if made is not None and not (root and (root / name).is_file()):
                return self._send(200, made, TYPES.get(Path(name).suffix, "application/octet-stream"), cache="no-cache")
        if root is None:
            return self._json({"error": "no web client here (run from a TaoChronos checkout, or pass --web)"}, 404)
        target = (root / name).resolve()
        if root not in target.parents and target != root:
            return self._json({"error": "not found"}, 404)
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            return self._json({"error": "not found"}, 404)
        kind = TYPES.get(target.suffix) or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        cache = "no-cache" if target.suffix in (".html", ".js", ".mjs", ".css", ".json") else "public, max-age=86400"
        self._send(200, target.read_bytes(), kind, cache=cache)

    # ------------------------------------------------------------------ model proxy
    def _proxy(self) -> None:
        if not self.server.proxy:
            return self._json({"error": "the model proxy is off (started with --no-proxy)"}, 403)
        target = (self.headers.get("X-TC-Target") or "").strip()
        url = urlsplit(self.path)
        if url.path.startswith("/api/llm/"):  # an SDK's own path under the proxy: X-TC-Target names the provider's base
            target = target.rstrip("/") + url.path[len("/api/llm"):] + (f"?{url.query}" if url.query else "")
        parts = urlsplit(target)
        port = parts.port or (443 if parts.scheme == "https" else 80)
        if (parts.scheme, parts.hostname or "", port) not in self.server.proxy_hosts:
            return self._json({"error": f"the proxy forwards only to the listed providers, not to {parts.scheme}://{parts.netloc}"}, 403)
        headers = {k: v for k in FORWARD if (v := self.headers.get(k))}
        for k in ("authorization", "x-api-key"):  # the client's stand-in for "use this machine's key"
            if headers.get(k, "").removeprefix("Bearer ").strip() == ENV_KEY:
                del headers[k]
        if self.server.env_keys and not (headers.get("authorization") or headers.get("x-api-key")):
            env = key_env_for(parts.hostname or "")
            key = os.environ.get(env) if env else None
            if key:
                if parts.hostname == "api.anthropic.com":
                    headers["x-api-key"] = key
                else:
                    headers["authorization"] = f"Bearer {key}"
        headers.setdefault("content-type", "application/json")
        request = urllib.request.Request(target, data=self._body(), headers=headers, method="POST")
        try:
            upstream = urllib.request.urlopen(request, timeout=600)  # noqa: S310 — the target was checked against the list
        except urllib.error.HTTPError as exc:
            body = exc.read()
            return self._send(exc.code, body, exc.headers.get("Content-Type", "application/json"))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return self._json({"error": f"cannot reach {parts.netloc}: {exc}"}, 502)
        with upstream:
            self.send_response(upstream.status)
            self._cors()
            self.send_header("Content-Type", upstream.headers.get("Content-Type", "application/octet-stream"))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            try:
                while chunk := upstream.read1(65536):
                    self.wfile.write(f"{len(chunk):X}\r\n".encode() + chunk + b"\r\n")
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
            except (BrokenPipeError, ConnectionResetError):  # the page stopped the answer
                self.close_connection = True


def web_root(home: Path | None) -> Path | None:
    for candidate in ([Path(home) / "web"] if home else []) + [Path(__file__).resolve().parents[3] / "web"]:
        if (candidate / "index.html").is_file():
            return candidate
    return None


def allowed_host(value: str) -> tuple[str, str, int]:
    """``--allow-host`` → (scheme, host, port): ``api.example.com`` (https), ``https://api.example.com:8443``,
    ``http://10.0.0.5:8000`` — a model endpoint set by hand in the page that the proxy may forward to."""
    parts = urlsplit(value if "://" in value else f"https://{value}")
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"--allow-host: not a host or URL: {value!r}")
    return parts.scheme, parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)


def lan_address() -> str | None:
    """This machine's address on its network, for the page other machines open (a UDP socket is routed, nothing is sent)."""
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 9))  # TEST-NET-1
            address = sock.getsockname()[0]
    except OSError:
        return None
    return None if address.startswith("127.") or address == "0.0.0.0" else address


def access_token(host: str, token: str | None) -> str | None:
    """The token every API request must carry: the one given, else — for a server other machines can reach — a new one."""
    if token:
        return token
    return None if host in ("127.0.0.1", "localhost", "::1") else secrets.token_urlsafe(18)


def serve(runtime: Any, *, host: str = "127.0.0.1", port: int = 8765, web: Path | None = None, origins: list[str] | None = None,
          env_keys: bool = False, proxy: bool = True, open_browser: bool = False, quiet: bool = True,
          token: str | None = None, allow_hosts: list[str] | None = None) -> None:
    home = Path(runtime.h.home)
    root = web or web_root(home)
    token = access_token(host, token)  # reachable from other machines: never without a token
    info = runtime.info()  # counted before the first request, which then answers at once
    server = ChatServer((host, port), runtime, web_root=root, origins=origins, env_keys=env_keys, proxy=proxy, home=home,
                        quiet=quiet, token=token, allow_hosts=allow_hosts)
    shown = "localhost" if host in ("127.0.0.1", "0.0.0.0", "::") else host
    url = f"http://{shown}:{server.server_address[1]}/"
    open_url = f"{url}#token={token}" if token else url
    print(f"TaoChronos {info['version']} · {info['profile']} · {info['corpus']['books']} 部书 · {info['corpus']['passages']} 段 · "
          f"{info['tools']['offered']} 个工具", file=sys.stderr)
    print(f"web client: {open_url}" + ("" if root else "  (no web/ directory found: API only)"), file=sys.stderr)
    if host in ("0.0.0.0", "::") and (lan := lan_address()):
        print(f"other machines: http://{lan}:{server.server_address[1]}/#token={token}", file=sys.stderr)
    if token:
        print(f"access token (访问令牌): {token}  — every API request must carry it (X-TC-Token)", file=sys.stderr)
    print(f"published client: {PAGES_ORIGIN}/ → 设置 → 运行环境 → 接入全部古籍 → 连接 {url.rstrip('/')}", file=sys.stderr)
    if open_browser:
        threading.Timer(0.6, lambda: __import__("webbrowser").open(open_url)).start()
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


__all__ = ["ENV_KEY", "ChatServer", "PAGES_ORIGIN", "PAGES_ORIGINS", "access_token", "allowed_host", "lan_address", "serve", "web_root"]
