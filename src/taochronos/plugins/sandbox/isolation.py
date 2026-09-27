"""Security tiers for running code, stated as what each one actually isolates.

========== ==================================================== =============================================
tier       isolates                                             may run
========== ==================================================== =============================================
in_process nothing (AST whitelist + step budget in the harness)  code the harness itself wrote
process    a separate process: CPU/memory/time limits, a         trusted analytics snippets (the system's own)
           scrubbed environment (no API keys), cwd in the
           session workspace — **not** the filesystem: it can
           read and write whatever the harness user can
namespace  Linux user+mount+pid+net namespaces: a new root with  model-written or otherwise untrusted code
           the system directories read-only, the session
           workspace the only writable place, a private /tmp,
           no network, no home directories, no data directory,
           no host credentials
container  an OCI container (docker/podman) with no network, a   untrusted code where a container runtime is
           read-only root, dropped capabilities                  configured
========== ==================================================== =============================================

The router (:class:`SandboxRouter`) picks the tier by the code's origin, and **refuses** to run untrusted code when no
isolating tier is available — it never falls back silently.  None of this is a guarantee against kernel exploits; for
hostile code use a VM-grade sandbox (gVisor, Firecracker) behind the same interface.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

TIERS = ("in_process", "process", "namespace", "container")
RANK = {t: i for i, t in enumerate(TIERS)}
ISOLATES = {
    "in_process": "nothing: an AST whitelist and a step budget inside the harness process",
    "process": "a separate process with resource limits and a scrubbed environment; not the filesystem",
    "namespace": "filesystem (read-only system, writable workspace only), network (none), processes (own pid namespace), credentials (none)",
    "container": "an OCI container: no network, read-only root, dropped capabilities",
}
# what each origin of code needs at least
REQUIRED = {"harness": "in_process", "trusted": "process", "model": "namespace", "user": "namespace"}


class SandboxUnavailable(RuntimeError):
    """No tier that isolates enough is available: the code is not run."""


def _limits(cpu_seconds: int, memory_mb: int):  # pragma: no cover - runs in the child
    def apply() -> None:
        os.setsid()
        try:
            import resource

            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
            limit = memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        except Exception:
            pass

    return apply


_NS_CACHE: dict[str, bool] = {}


def namespace_available() -> bool:
    """Whether unprivileged user+mount+pid+net namespaces work here (Linux with ``unshare``)."""
    if "ok" in _NS_CACHE:
        return _NS_CACHE["ok"]
    ok = False
    if sys.platform.startswith("linux") and shutil.which("unshare"):
        try:
            probe = subprocess.run(["unshare", "--user", "--map-root-user", "--mount", "--net", "--pid", "--fork", "true"],
                                   capture_output=True, timeout=10)
            ok = probe.returncode == 0
        except (OSError, subprocess.SubprocessError):
            ok = False
    _NS_CACHE["ok"] = ok
    return ok


def _python_roots() -> list[str]:
    """Directories the interpreter needs, read-only (its prefixes, whatever they are: /usr, a venv, a toolcache)."""
    roots = {"/usr", "/bin", "/lib", "/lib64", "/sbin"}
    for p in {sys.prefix, sys.base_prefix, sys.exec_prefix, os.path.dirname(os.path.realpath(sys.executable))}:
        if p and not any(p == r or p.startswith(r + "/") for r in ("/usr", "/bin", "/lib", "/lib64", "/sbin")):
            roots.add(p)
    return sorted(r for r in roots if os.path.exists(r))


# Runs as root of a fresh user namespace (the host's root is not reachable from it): builds a new root from read-only
# binds of the interpreter's directories, the workspace (the one writable place) and a private /tmp; pivots into it and
# detaches the old root; then enters a *nested* user namespace, so the code holds no capability over these mounts (their
# read-only flags are locked) — and finally executes the boot script with an empty environment.
_NS_SETUP = r"""
import ctypes, os, platform, sys
libc = ctypes.CDLL(None, use_errno=True)
MS_RDONLY, MS_NOSUID, MS_NODEV, MS_NOEXEC, MS_REMOUNT, MS_BIND, MS_REC, MS_PRIVATE = 1, 2, 4, 8, 32, 4096, 16384, 1 << 18
ST_FLAGS = {1: MS_RDONLY, 2: MS_NOSUID, 4: MS_NODEV, 8: MS_NOEXEC, 1024: 1024, 2048: 2048, 4096: 1 << 21}
def check(ret, what):
    if ret != 0:
        e = ctypes.get_errno()
        raise OSError(e, f"{what}: {os.strerror(e)}")
def mount(src, dst, fstype, flags, data=None):
    check(libc.mount(src and src.encode(), dst.encode(), fstype and fstype.encode(), ctypes.c_ulong(flags), data and data.encode()), f"mount {dst}")
def locked(path):
    f = os.statvfs(path).f_flag
    return sum(v for k, v in ST_FLAGS.items() if f & k)
new, work = os.environ["TC_STAGE"], os.environ["TC_WORK"]
mount(None, "/", None, MS_REC | MS_PRIVATE)
mount("tmpfs", new, "tmpfs", MS_NOSUID | MS_NODEV, "size=64m,mode=755")
for d in os.environ["TC_RO"].split():
    target = new + d
    os.makedirs(target, exist_ok=True)
    mount(d, target, None, MS_BIND | MS_REC)
    mount(None, target, None, MS_BIND | MS_REMOUNT | MS_RDONLY | locked(target))
for sub in ("work", "tmp", "dev", "proc", ".old"):
    os.makedirs(os.path.join(new, sub), exist_ok=True)
mount(work, new + "/work", None, MS_BIND | MS_REC)
mount("tmpfs", new + "/tmp", "tmpfs", MS_NOSUID | MS_NODEV, "size=64m")
for f in ("null", "zero", "urandom", "random"):
    open(os.path.join(new, "dev", f), "w").close()
    mount("/dev/" + f, os.path.join(new, "dev", f), None, MS_BIND)
try:
    mount("proc", new + "/proc", "proc", MS_NOSUID | MS_NODEV | MS_NOEXEC)
except OSError:
    pass
SYS_PIVOT_ROOT = {"x86_64": 155, "aarch64": 41, "arm64": 41, "ppc64le": 203, "s390x": 217, "riscv64": 41}[platform.machine()]
os.chdir(new)
check(libc.syscall(SYS_PIVOT_ROOT, b".", b".old"), "pivot_root")
os.chdir("/")
check(libc.umount2(b"/.old", 2), "detach old root")
os.rmdir("/.old")
CLONE_NEWUSER = 0x10000000
check(libc.unshare(CLONE_NEWUSER), "nested user namespace")
os.chdir("/work")
py = os.environ["TC_PY"]
boot = os.environ["TC_BOOT"]
env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/work", "TMPDIR": "/tmp", "PYTHONIOENCODING": "utf-8",
       "PYTHONDONTWRITEBYTECODE": "1"}
os.execve(py, [py, "-I", "-S", "-c", boot], env)
"""


class Launcher:
    """Starts a Python child running ``boot`` in one tier, with pipes on stdin/stdout, a watchdog and resource limits."""

    def __init__(self, tier: str, *, cpu_seconds: int = 20, memory_mb: int = 1024) -> None:
        if tier not in ("process", "namespace"):
            raise ValueError(f"the launcher runs the process or namespace tier, not {tier!r}")
        self.tier = tier
        self.cpu_seconds = cpu_seconds
        self.memory_mb = memory_mb

    def available(self) -> bool:
        return self.tier == "process" or namespace_available()

    def spawn(self, boot: str, workspace: Path) -> subprocess.Popen:
        workspace = Path(workspace).resolve()
        if self.tier == "process":
            env = {"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8", "HOME": str(workspace), "TMPDIR": str(workspace / "tmp")}
            cmd = [sys.executable, "-I", "-c", boot]
            cwd = str(workspace)
        else:
            if not namespace_available():
                raise SandboxUnavailable("namespace isolation is not available on this host (unprivileged user namespaces)")
            stage = workspace.parent / f".root-{os.getpid()}-{threading.get_ident()}"
            stage.mkdir(parents=True, exist_ok=True)
            env = {"PATH": "/usr/bin:/bin", "TC_STAGE": str(stage), "TC_WORK": str(workspace), "TC_RO": " ".join(_python_roots()),
                   "TC_PY": os.path.realpath(sys.executable), "TC_BOOT": boot}
            cmd = ["unshare", "--user", "--map-root-user", "--mount", "--net", "--pid", "--ipc", "--uts", "--fork", "--kill-child",
                   os.path.realpath(sys.executable), "-I", "-S", "-c", _NS_SETUP]
            cwd = str(workspace)
        return subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                encoding="utf-8", cwd=cwd, env=env,
                                preexec_fn=_limits(self.cpu_seconds, self.memory_mb) if os.name == "posix" else None)


class Watchdog:
    """Kills a child's whole process group after ``timeout`` seconds."""

    def __init__(self, proc: subprocess.Popen, timeout: float) -> None:
        self.proc = proc
        self.fired = False
        self._timer = threading.Timer(timeout, self._kill)
        self._timer.daemon = True
        self._timer.start()

    def _kill(self) -> None:
        self.fired = True
        try:
            os.killpg(self.proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                self.proc.kill()
            except OSError:
                pass

    def cancel(self) -> None:
        self._timer.cancel()


def run_boot(launcher: Launcher, boot: str, payload: dict[str, Any], workspace: Path, timeout: float) -> dict[str, Any]:
    """Run a one-shot boot script: payload on stdin, ``__TAOCHRONOS_RESULT__{json}`` on stdout."""
    proc = launcher.spawn(boot, workspace)
    dog = Watchdog(proc, timeout)
    try:
        out, err = proc.communicate(json.dumps(payload, ensure_ascii=False))
    finally:
        dog.cancel()
    result = None
    if "__TAOCHRONOS_RESULT__" in out:
        out, raw = out.rsplit("__TAOCHRONOS_RESULT__", 1)
        try:
            result = json.loads(raw)["result"]
        except (json.JSONDecodeError, KeyError):
            result = None
    ok = proc.returncode == 0 and not dog.fired
    return {"ok": ok, "result": result, "stdout": out[-4000:], "stderr": ("killed: time limit\n" if dog.fired else "") + err[-4000:],
            "returncode": proc.returncode, "tier": launcher.tier, "isolates": ISOLATES[launcher.tier]}
