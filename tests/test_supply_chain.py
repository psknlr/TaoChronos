"""What the repository installs and runs, pinned (docs/adr/0026-pinned-supply-chain-and-enforced-policies.md): every
GitHub Action by its commit, every checkout without the token where its job pushes nothing; every Python package from a
hashed lockfile that still fits pyproject.toml, whose lower bounds stay above the published advisories; every Worker
deployed with the wrangler its lockfile names, installed without install scripts, the type checker locked as exactly,
and every npm lockfile kept current by Dependabot; the full corpus's image on a base pinned by digest, run by an
unprivileged user, its version made of everything it copies."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest
import yaml
from packaging.requirements import Requirement
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
LOCKS = sorted((ROOT / "requirements").glob("*.txt"))
WORKERS = ["relay", "cloud/site", "cloud/corpus", "cloud/api", "cloud/console"]
TOOLS = ["tools/typecheck"]  # installed only to check the code (CI's typecheck job), and pinned all the same
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
# the first release of each from which no published advisory applies (requirements/README.md; pypdf's of 2026-11-27)
FLOORS = {"setuptools": "84.1.0", "wheel": "0.46.2", "litellm": "1.103.1", "pytest": "9.0.3", "pyarrow": "23.0.1", "pypdf": "6.21.4"}


def _runs(workflow: dict) -> list[tuple[str, dict, dict]]:
    """(job, step, job) for every step of every job."""
    return [(name, step, job) for name, job in workflow["jobs"].items() for step in job.get("steps", [])]


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_every_action_is_pinned_to_a_commit_with_its_release_named():
    assert WORKFLOWS
    for path in WORKFLOWS:
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\s*(?:- )?uses:\s*(\S+)(.*)$", line)
            if not m or m.group(1).startswith("./"):
                continue
            assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", m.group(1)), f"{path.name}: {m.group(1)} is not pinned to a commit"
            assert re.fullmatch(r"\s+# v\d+\.\d+\.\d+", m.group(2)), f"{path.name}: {m.group(1)} does not name its release"


def test_the_token_stays_read_only_and_leaves_with_the_checkout_where_nothing_is_pushed():
    for path in WORKFLOWS:
        workflow = _load(path)
        assert "permissions" in workflow, f"{path.name}: no top-level permissions (the token's default may write)"
        for name, job in workflow["jobs"].items():
            pushes = any("git push" in str(step.get("run", "")) for step in job.get("steps", []))
            for step in job.get("steps", []):
                if str(step.get("uses", "")).startswith("actions/checkout@") and not pushes:
                    assert (step.get("with") or {}).get("persist-credentials") is False, f"{path.name} {name}: the checkout keeps the token"


def test_python_is_installed_only_from_the_hashed_lockfiles():
    commands = [(path.name, str(step.get("run", ""))) for path in WORKFLOWS for _, step, _ in _runs(_load(path))]
    commands += [("Dockerfile", line) for line in (ROOT / "cloud/corpus/Dockerfile").read_text(encoding="utf-8").splitlines() if line.startswith("RUN")]
    seen = 0
    for where, run in commands:
        for cmd in re.findall(r"pip install[^\n&|;]*", run):
            seen += 1
            locked = "--require-hashes" in cmd and re.search(r"-r requirements/\w+\.txt", cmd)
            itself = "--no-deps" in cmd and "--no-build-isolation" in cmd  # the project, its dependencies installed before
            assert locked or itself, f"{where}: {cmd!r} installs what no lockfile pins"
    assert seen >= 20


def test_each_lockfile_pins_every_package_with_its_hashes():
    assert {p.stem for p in LOCKS} == {"runtime", "build", "dev", "litellm", "ingest", "audit", "native"}
    for path in LOCKS:
        text = path.read_text(encoding="utf-8")
        assert "requirements/lock.sh" in text.splitlines()[1], f"{path.name}: not written by requirements/lock.sh"
        entries = re.split(r"\n(?=[A-Za-z0-9])", "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#") and l.strip()))
        assert entries
        for entry in entries:
            head = entry.split("\\", 1)[0].strip()
            assert re.fullmatch(r"[a-z0-9._-]+==[\w.+!-]+(?: ; .+)?", head), f"{path.name}: {head!r} is not one pinned version"
            assert len(re.findall(r"--hash=sha256:[0-9a-f]{64}", entry)) >= 1, f"{path.name}: {head!r} has no hash"


def _pins(name: str) -> dict[str, Version]:
    text = (ROOT / "requirements" / f"{name}.txt").read_text(encoding="utf-8")
    return {m.group(1): Version(m.group(2)) for m in re.finditer(r"^([a-z0-9._-]+)==([^\s;\\]+)", text, re.M)}


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def test_the_lockfiles_fit_pyproject_as_lock_sh_makes_them():
    project = PYPROJECT["project"]
    script = (ROOT / "requirements" / "lock.sh").read_text(encoding="utf-8")
    made = re.findall(r"^lock (\w+) (\S+)((?: --extra \w+)*)", script, re.M)
    assert {name for name, _, _ in made} == {p.stem for p in LOCKS}
    for name, source, extras in made:
        if source == "pyproject.toml":
            wanted = list(project["dependencies"]) + [r for e in re.findall(r"--extra (\w+)", extras) for r in project["optional-dependencies"][e]]
        else:
            wanted = [l for l in (ROOT / source).read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
        pins = {_norm(k): v for k, v in _pins(name).items()}
        for line in wanted:
            req = Requirement(line)
            assert _norm(req.name) in pins, f"{name}.txt lacks {req.name}"
            assert req.specifier.contains(pins[_norm(req.name)]), f"{name}.txt: {req.name} {pins[_norm(req.name)]} does not satisfy {req.specifier}"
    build_in = [l for l in (ROOT / "requirements/build.in").read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    assert build_in == PYPROJECT["build-system"]["requires"], "requirements/build.in must say what [build-system] requires"
    # TaoCore's extension is a distribution of its own (taochronos itself never needs Rust): what builds it, the same way
    native = tomllib.loads((ROOT / "rust/crates/taocore-py/pyproject.toml").read_text(encoding="utf-8"))
    native_in = [l for l in (ROOT / "requirements/native.in").read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    assert native_in == native["build-system"]["requires"], "requirements/native.in must say what the extension's [build-system] requires"


def test_no_lower_bound_allows_a_release_with_a_known_advisory():
    reqs = PYPROJECT["build-system"]["requires"] + PYPROJECT["project"]["dependencies"]
    reqs += [r for extra in PYPROJECT["project"]["optional-dependencies"].values() for r in extra]
    bounded = set()
    for line in reqs:
        req = Requirement(line)
        floor = FLOORS.get(_norm(req.name))
        if floor:
            lows = [Version(s.version) for s in req.specifier if s.operator in (">=", "==", "~=")]
            assert lows and max(lows) >= Version(floor), f"{line}: allows releases below {floor}, which have published advisories"
            bounded.add(_norm(req.name))
    assert bounded == set(FLOORS)


def test_filelock_stays_outside_the_releases_its_advisories_name():
    # GHSA-v4x8-3wr5-3wq8 and two more: 3.20.4–4.2.0; GHSA-w853-jp5j-5j7f and GHSA-qmgc-5h2g-mvrw: before 3.20.3
    v = _pins("litellm")["filelock"]
    assert Version("3.20.3") <= v < Version("3.20.4") or v >= Version("4.2.1"), f"filelock {v}"


@pytest.mark.parametrize("worker", WORKERS)
def test_each_worker_has_its_wrangler_locked_with_every_package_checked(worker):
    package = json.loads((ROOT / worker / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / worker / "package-lock.json").read_text(encoding="utf-8"))
    pinned = package["devDependencies"]["wrangler"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", pinned), f"{worker}: wrangler {pinned!r} is a range, not a version"
    assert lock["lockfileVersion"] == 3 and lock["packages"][""]["devDependencies"]["wrangler"] == pinned
    packages = {k: v for k, v in lock["packages"].items() if k and not v.get("link")}
    assert packages["node_modules/wrangler"]["version"] == pinned
    for key, entry in packages.items():
        assert entry.get("integrity", "").startswith("sha512-"), f"{worker}: {key} has no integrity hash"
        assert entry.get("resolved", "").startswith("https://registry.npmjs.org/"), f"{worker}: {key} comes from elsewhere"
    # the toolchain the assessment of 2026-10-26 found vulnerable: wrangler 4.142.0, with undici 7.29.0 and sharp 0.35.4
    assert Version(pinned) >= Version("4.153.0")
    for name, fixed in (("undici", "7.30.1"), ("sharp", "0.35.5")):
        if f"node_modules/{name}" in packages:
            assert Version(packages[f"node_modules/{name}"]["version"]) >= Version(fixed), f"{worker}: {name}"
    for script in package.get("scripts", {}).values():
        assert "npx" not in script and "wrangler@" not in script, f"{worker}: {script!r} would fetch a wrangler of its own"


def test_wrangler_runs_only_as_installed_from_a_lockfile_without_install_scripts():
    deploy = (ROOT / "cloud/site/deploy.sh").read_text(encoding="utf-8")
    texts = {"deploy.sh": deploy, **{p.name: p.read_text(encoding="utf-8") for p in WORKFLOWS}}
    for name, text in texts.items():
        assert "npx --yes" not in text and "wrangler@" not in text and "$WRANGLER" not in text, f"{name}: a wrangler not from the lockfile"
        for line in (l for l in text.splitlines() if not l.lstrip().startswith("#")):
            if re.search(r"\bnpx\b", line):
                assert "npx --no -- wrangler" in line, f"{name}: {line.strip()!r}"
            if re.search(r"\bnpm (?:ci|install|i)\b", line):
                assert re.search(r"npm ci --ignore-scripts", line), f"{name}: {line.strip()!r} runs install scripts or ignores the lockfile"
    assert deploy.index("npm ci --ignore-scripts") < deploy.index("npx --no -- wrangler")
    for path in WORKFLOWS:
        for job_name, job in _load(path)["jobs"].items():
            runs = [str(s.get("run", "")) for s in job.get("steps", [])]
            first = next((i for i, r in enumerate(runs) if "npx --no -- wrangler" in r), None)
            if first is not None:
                assert any("npm ci --ignore-scripts" in r for r in runs[:first]), f"{path.name} {job_name}: wrangler before its install"


@pytest.mark.parametrize("tool", TOOLS)
def test_each_tool_is_locked_to_exact_versions_with_every_package_checked(tool):
    package = json.loads((ROOT / tool / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / tool / "package-lock.json").read_text(encoding="utf-8"))
    wanted = package["devDependencies"]
    assert wanted and not package.get("dependencies"), f"{tool}: what it installs is a dev dependency"
    for name, version in wanted.items():
        assert re.fullmatch(r"\d+\.\d+\.\d+", version), f"{tool}: {name} {version!r} is a range, not a version"
    assert lock["lockfileVersion"] == 3 and lock["packages"][""]["devDependencies"] == wanted
    packages = {k: v for k, v in lock["packages"].items() if k and not v.get("link")}
    for name, version in wanted.items():
        assert packages[f"node_modules/{name}"]["version"] == version, f"{tool}: {name} is not the version package.json names"
    for key, entry in packages.items():
        assert entry.get("integrity", "").startswith("sha512-"), f"{tool}: {key} has no integrity hash"
        assert entry.get("resolved", "").startswith("https://registry.npmjs.org/"), f"{tool}: {key} comes from elsewhere"
    for script in package.get("scripts", {}).values():
        assert "npx" not in script, f"{tool}: {script!r} would fetch what its lockfile does not pin"


def test_every_npm_lockfile_is_checked_here_and_kept_current():
    """A new npm directory is pinned like the others (WORKERS or TOOLS above) and Dependabot proposes its updates."""
    found = {p.parent.relative_to(ROOT).as_posix() for pattern in ("*/package-lock.json", "*/*/package-lock.json")
             for p in ROOT.glob(pattern) if "node_modules" not in p.parts}
    assert found == set(WORKERS) | set(TOOLS)
    updates = _load(ROOT / ".github" / "dependabot.yml")["updates"]
    npm = {d.strip("/") for u in updates if u["package-ecosystem"] == "npm" for d in u.get("directories") or [u["directory"]]}
    assert npm == found, "a directory with an npm lockfile that Dependabot does not keep current, or the reverse"


def test_the_image_is_pinned_unprivileged_and_versioned_by_all_it_copies():
    dockerfile = (ROOT / "cloud/corpus/Dockerfile").read_text(encoding="utf-8")
    stages = set()
    for m in re.finditer(r"^FROM (\S+)(?: AS (\w+))?", dockerfile, re.M):
        assert m.group(1) in stages or re.fullmatch(r"[\w./-]+:[\w.-]+@sha256:[0-9a-f]{64}", m.group(1)), f"FROM {m.group(1)}: not pinned by digest"
        if m.group(2):
            stages.add(m.group(2))
    final = dockerfile[dockerfile.rindex("\nFROM "):]
    user = re.search(r"^USER (\d+)(?::(\d+))?$", final, re.M)
    assert user and int(user.group(1)) != 0, "the server must not run as root"
    assert re.search(r"^COPY --from=store --chown=" + user.group(1), final, re.M), "its data must be its own to write"
    # what the image copies from the repository is what its version is made of (site.yml), and what .dockerignore lets in
    workflow = (ROOT / ".github/workflows/site.yml").read_text(encoding="utf-8")
    tree = re.search(r"git ls-tree -r HEAD -- (.*?) \| sha256sum", workflow.replace("\\\n", " "), re.S).group(1).split()
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for m in re.finditer(r"^COPY (?!--from)(.+)$", dockerfile, re.M):
        for src in m.group(1).split()[:-1]:
            if src.startswith("cloud/.store"):
                continue  # the store: its sha256 is the version's first half
            assert any(src.rstrip("/") == t or src.startswith(t.rstrip("/") + "/") for t in tree), f"COPY {src}: not in the image's version"
            assert any(line.lstrip("!").rstrip("/") in (src.rstrip("/"), src.split("/")[0]) for line in ignore if line.startswith("!")), f"COPY {src}: .dockerignore keeps it out"
    # what is copied from elsewhere is copied from a stage of this file, or from an image pinned by digest
    for m in re.finditer(r"^COPY --from=(\S+)", dockerfile, re.M):
        assert m.group(1) in stages or re.fullmatch(r"[\w./-]+:[\w.-]+@sha256:[0-9a-f]{64}", m.group(1)), f"COPY --from={m.group(1)}: not a stage nor pinned by digest"


def test_the_rust_toolchain_is_one_exact_release_everywhere():
    """TaoCore (rust/) is compiled by one rustc: the toolchain file's exact release (the committed browser module is
    rebuilt byte for byte only by it), which the image's Rust stage is, and is told to use."""
    channel = tomllib.loads((ROOT / "rust/rust-toolchain.toml").read_text(encoding="utf-8"))["toolchain"]["channel"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", channel), f"rust-toolchain.toml: {channel!r} is not one exact release"
    dockerfile = (ROOT / "cloud/corpus/Dockerfile").read_text(encoding="utf-8")
    assert re.search(rf"^FROM rust:{re.escape(channel)}-[\w.-]+@sha256:[0-9a-f]{{64}} AS native$", dockerfile, re.M)
    assert re.search(rf"^ENV RUSTUP_TOOLCHAIN={re.escape(channel)}\b", dockerfile, re.M)
    # every cargo and maturin build reads Cargo.lock as it is
    for where, run in [(p.name, str(step.get("run", ""))) for p in WORKFLOWS for _, step, _ in _runs(_load(p))] + \
            [("Dockerfile", line) for line in dockerfile.splitlines() if line.startswith("RUN")]:
        for cmd in re.findall(r"\b(?:cargo (?:build|test|clippy|install|deny)|maturin build)\b[^\n&|;]*", run):
            assert "--locked" in cmd, f"{where}: {cmd!r} may change Cargo.lock"
    assert "--locked" in (ROOT / "rust/wasm.sh").read_text(encoding="utf-8")
