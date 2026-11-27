"""What the published site may carry (distribution-policy.yaml, taochronos.chat.distribution, ADR 0034): every path of
the repository has a class; the package the site ships is what the browser can import, and never the server, the
command line, the evaluation suites or the corpus pipeline; its home is the files the policy names, never the gold sets
or a record; the two archives alone start the runtime and run a research; and a site that breaks the policy is not
built."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from taochronos.chat import build, distribution
from taochronos.chat.distribution import DistributionError, audit_site, browser_modules, class_of, home_files, load_policy

ROOT = Path(__file__).resolve().parents[1]
POLICY = load_policy(ROOT)


def test_every_path_of_the_repository_has_a_class_and_what_is_confidential_never_ships():
    """A new directory is classified before anything is built from it; the records and the gold sets are of the class
    that is never published, and nothing the site ships is."""
    try:
        tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True, check=True, timeout=60).stdout.split("\n")
    except (OSError, subprocess.SubprocessError):
        pytest.skip("not a git checkout")
    tracked = [t for t in tracked if t]
    assert distribution.unclassified(tracked, POLICY) == []
    assert distribution.unclassified(["a-new-directory/file.txt", "web/js/app.js"], POLICY) == ["a-new-directory/file.txt"]
    assert class_of("data/chat-logs/2026/10/05.jsonl", POLICY) == class_of("evals/gold/ner_heldout.yaml", POLICY) == "confidential"
    assert class_of("web/js/app.js", POLICY) == "public" and class_of("src/taochronos/cli.py", POLICY) == "restricted"
    # the most specific entry wins: a path named under a wider one keeps its own class
    policy = {"assets": {"public": ["corpus/web"], "restricted": ["corpus"], "confidential": ["corpus/web/private"]}}
    assert [class_of(p, policy) for p in ("corpus/web/books.json", "corpus/sources.lock.yaml", "corpus/web/private/x", "corpusx")] == [
        "public", "restricted", "confidential", None]
    shipped = [name for name, _ in home_files(ROOT, POLICY)]
    assert shipped and not [n for n in shipped if class_of(n, POLICY) == "confidential"]
    # the evaluation data carries its mark, file by file, in its first line: a copy under another name is known by it
    [canary] = POLICY["site"]["canaries"]
    gold = [t for t in tracked if t.startswith("evals/") and t.endswith((".yaml", ".yml"))]
    assert len(gold) >= 40 and all(canary in (ROOT / t).read_text(encoding="utf-8").split("\n", 1)[0] for t in gold)
    assert not [t for t in tracked if not t.startswith("evals/") and t != "distribution-policy.yaml" and (ROOT / t).suffix in distribution.TEXT
                and canary in (ROOT / t).read_text(encoding="utf-8", errors="replace")]


def test_the_servers_image_copies_nothing_confidential():
    """The full corpus's server is ours, not a visitor's — and still holds no record and no gold set: what the policy
    classes as confidential goes into no image.  Read from the image's own build files."""
    copied = [line.split()[1:-1] for line in (ROOT / "cloud" / "corpus" / "Dockerfile").read_text(encoding="utf-8").splitlines()
              if line.startswith("COPY ") and "--from=" not in line]
    sources = [src.rstrip("/") for group in copied for src in group if not src.startswith("--")]
    assert {"src", "profiles", "domains", "agents", "skills"} <= set(sources)
    built_here = {"cloud/.store"}  # the corpus store the workflow fetches before the build: not a tracked path
    assert [(src, class_of(src, POLICY)) for src in sources if src not in built_here and class_of(src, POLICY) in (None, "confidential")] == []
    allowed = [line[1:].rstrip("/") for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines() if line.startswith("!")]
    assert [a for a in allowed if a not in built_here and class_of(a, POLICY) in (None, "confidential")] == []
    assert not [a for a in allowed if a.startswith(("evals", "data"))]


def test_the_package_is_what_the_browser_can_import_and_never_the_server():
    """runtime/taochronos.zip: the modules reachable from what the page's worker imports, the plugins the browser's
    profiles load and the procedures the agents name — the harness, whole — and not the server, the command line, the
    site's build, the evaluation suites or the pipeline that builds the corpus."""
    modules = browser_modules(ROOT, POLICY)
    every = distribution._modules(distribution.PACKAGE)
    assert set(POLICY["site"]["package"]["entry"]) <= set(modules) <= set(every)
    # what the home names: every plugin of the browser's profiles, every procedure of the agents
    from taochronos.agents.spec import load_specs
    from taochronos.kernel.profiles import load_profile_dict
    for profile in POLICY["site"]["package"]["profiles"]:
        for bundle in load_profile_dict(profile, [ROOT / "profiles"])["bundles"]:
            assert bundle["plugin"] in modules, bundle["plugin"]
    procedures = [spec.procedure for spec in load_specs(ROOT / "agents").values() if getattr(spec, "procedure", None)]
    assert len(procedures) >= 10 and not [p for p in procedures if p not in modules]
    for kept in ("taochronos.chat.jobs", "taochronos.chat.prompt", "taochronos.bootstrap", "taochronos.engine", "taochronos.kernel",
                 "taochronos.plugins.classics.study", "taochronos.plugins.classics.sources", "taochronos.plugins.userdata"):
        assert kept in modules, kept
    for gone in ("taochronos.cli", "taochronos.__main__", "taochronos.governance", "taochronos.chat.server", "taochronos.chat.build",
                 "taochronos.chat.distribution", "taochronos.chat.cloud", "taochronos.chat.d1", "taochronos.chat.records",
                 "taochronos.evals", "taochronos.evals.aliases_gold", "taochronos.plugins.classics.ingest",
                 "taochronos.plugins.classics.ingest.kanripo", "taochronos.plugins.classics.harvest", "taochronos.workspace"):
        assert gone in every and gone not in modules, gone
    # a good part of the package stays home, and the archive is exactly the files of the rest
    assert len(every) - len(modules) >= 50
    names = zipfile.ZipFile(BytesIO(build.package_zip(home=ROOT))).namelist()
    assert sorted(names) == sorted(p.relative_to(distribution.PACKAGE.parent).as_posix() for p in modules.values())
    assert all(n.startswith("taochronos/") and n.endswith(".py") for n in names)


def _package(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = tmp_path / "pkg" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path / "pkg"


def _home(tmp_path: Path, policy: dict, files: dict[str, str]) -> Path:
    import yaml
    home = tmp_path / "home"
    for name, text in {**files, "distribution-policy.yaml": yaml.safe_dump(policy)}.items():
        path = home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return home


def test_an_import_that_would_ship_the_server_fails_and_names_the_chain(tmp_path):
    """The modules are found by their imports — at a module's top, in a function, relative, `from package import
    module`, a package's parents — and by the names the home's files give; one that must never ship stops the build,
    with the chain of imports that reached it."""
    package = _package(tmp_path, {
        "__init__.py": "", "chat/__init__.py": "from . import runtime\n", "chat/runtime.py": "def f():\n    from ..tools import search\n",
        "tools/__init__.py": "", "tools/search.py": "import pkg.kernel.store\n", "kernel/__init__.py": "", "kernel/store.py": "",
        "plugins/__init__.py": "", "plugins/lexicon.py": "from pkg.agents import director\n", "agents/__init__.py": "", "agents/director.py": "",
        "cli.py": "from .chat import server\n", "chat/server.py": "from . import runtime\n", "evals/__init__.py": "", "evals/suite.py": ""})
    policy = {"assets": {"restricted": ["profiles"]}, "site": {"package": {"entry": ["pkg.chat"], "never": ["pkg.cli", "pkg.chat.server", "pkg.evals"]},
                                                              "home": {"ship": ["profiles"]}}}
    home = _home(tmp_path, policy, {"profiles/web.yaml": "bundles:\n  - {plugin: pkg.plugins.lexicon}\n  - {plugin: elsewhere.plugin}\n"})
    got = browser_modules(home, load_policy(home), package)
    assert sorted(got) == ["pkg", "pkg.agents", "pkg.agents.director", "pkg.chat", "pkg.chat.runtime", "pkg.kernel", "pkg.kernel.store",
                           "pkg.plugins", "pkg.plugins.lexicon", "pkg.tools", "pkg.tools.search"]
    # the runtime comes to import the server, two imports away: nothing is built
    (package / "tools" / "search.py").write_text("def g():\n    from ..chat.server import x\n", encoding="utf-8")
    with pytest.raises(DistributionError, match=r"pkg\.chat\.server must never ship .* pkg\.chat\.server ← pkg\.tools\.search ← pkg\.chat\.runtime ← pkg\.chat$"):
        browser_modules(home, load_policy(home), package)
    # a package named whole covers what is under it; an entry point that is no module is said
    (package / "tools" / "search.py").write_text("from pkg.evals import suite\n", encoding="utf-8")
    with pytest.raises(DistributionError, match=r"pkg\.evals(\.suite)? must never ship"):
        browser_modules(home, load_policy(home), package)
    policy["site"]["package"]["entry"] = ["pkg.chat", "pkg.gone"]
    with pytest.raises(DistributionError, match="names no module of the package: pkg.gone"):
        browser_modules(home, policy, package)


def test_the_home_is_the_files_the_policy_names_and_no_other(tmp_path):
    """runtime/home.zip: the browser's profiles with the ones they extend, the agents, the skills, the domain packs
    but the harvested lexicon, the demonstration corpus and the catalogs — no gold set, no record, no other profile;
    the marker the harness finds its home by, empty."""
    files = dict(home_files(ROOT, POLICY))
    names = set(files)
    assert files["architecture-policy.yaml"] == b"" and (ROOT / "architecture-policy.yaml").stat().st_size > 0
    for part in ("agents/director.yaml", "skills/manifests/", "domains/classics/periods.yaml", "corpus/demo/books/", "corpus/catalog/canon.yaml",
                 "corpus/modern/evidence.yaml"):
        assert any(n == part or n.startswith(part) for n in names), part
    for part in ("evals/", "data/", "docs/", "paper/", "security/", "src/", "tests/", "corpus/web/", "domains/classics/lexicon-harvested/",
                 "distribution-policy.yaml", "corpus/sources.lock.yaml"):
        assert not [n for n in names if n == part or n.startswith(part)], part
    # of the profiles, the ones the runtime in the browser starts on and what they extend
    from taochronos.protocol.yamlio import load_yaml
    chain = set()
    for name in POLICY["site"]["package"]["profiles"]:
        while name:
            chain.add(f"profiles/{name}.yaml")
            name = (load_yaml(ROOT / "profiles" / f"{name}.yaml") or {}).get("extends")
    assert {n for n in names if n.startswith("profiles/")} == chain and len(chain) < len(list((ROOT / "profiles").glob("*.yaml")))
    shipped = zipfile.ZipFile(BytesIO(build.home_zip(ROOT)))
    assert set(shipped.namelist()) == names and shipped.read("architecture-policy.yaml") == b""
    # a policy that names what is confidential, or what is not there, builds nothing
    policy = {"assets": {"confidential": ["evals", "agents/private"], "restricted": ["agents"]},
              "site": {"package": {"entry": ["x"]}, "home": {"ship": ["agents"], "except": ["agents/drafts"], "marker": "marker.yaml"}}}
    home = _home(tmp_path, policy, {"agents/a.yaml": "a", "agents/drafts/b.yaml": "b", "evals/gold/g.yaml": "g"})
    assert home_files(home, load_policy(home)) == [("agents/a.yaml", home / "agents" / "a.yaml"), ("marker.yaml", b"")]
    (home / "agents" / "private").mkdir()
    (home / "agents" / "private" / "c.yaml").write_text("c", encoding="utf-8")
    with pytest.raises(DistributionError, match="agents/private/c.yaml is confidential and would ship under agents"):
        home_files(home, load_policy(home))
    for ship, why in ((["evals"], "names evals, which is confidential"), (["skills"], "names skills, which is not in")):
        policy["site"]["home"]["ship"] = ship
        with pytest.raises(DistributionError, match=why):
            home_files(home, policy)
    (home / "distribution-policy.yaml").unlink()
    with pytest.raises(DistributionError, match="nothing is published without one"):
        load_policy(home)


RESEARCH = r"""
import json, sys
from pathlib import Path
package, home, data = sys.argv[1:4]
import taochronos
root = Path(package).resolve()
assert root in Path(taochronos.__file__).resolve().parents, taochronos.__file__
import importlib, pkgutil
names = sorted(m.name for m in pkgutil.walk_packages(taochronos.__path__, "taochronos."))
for name in names:  # every module the site ships imports, with nothing but the others
    importlib.import_module(name)
from taochronos.chat import ChatRuntime
rt = ChatRuntime.create("full-discovery", home=home, data_dir=data, kind="browser", ephemeral=True)
found = rt.call("classics.search", {"query": "桂枝汤", "k": 2})
run = rt.call("taochronos_research", {"question": "消渴的概念如何随时代演变？", "focus_terms": ["消渴"], "max_rounds": 1})
session = rt.session_view(run["result"]["session_id"]) if run.get("ok") else {}
asked = rt.call("taochronos_ask", {"question": "桂枝汤的方源"})
strays = sorted(n for n, m in sys.modules.items() if n.startswith("taochronos") and getattr(m, "__file__", None)
                and root not in Path(m.__file__).resolve().parents)
print(json.dumps({"modules": len(names), "search": bool(found.get("ok") and found.get("citations")), "research": run.get("ok"),
                  "research_error": None if run.get("ok") else str(run)[:400], "session": bool(session), "ask": asked.get("ok"),
                  "ask_error": None if asked.get("ok") else str(asked)[:400], "tools": len(rt.catalog("all")["tools"]), "strays": strays}))
"""


def test_the_two_archives_alone_start_the_runtime_search_and_run_a_research(tmp_path):
    """What a browser holds is the two archives: unpacked, in a process whose only taochronos they are, every shipped
    module imports, and the runtime searches, runs a multi-agent research (the agents' procedures, named in the home)
    and a V2 workflow (the skills) on the demonstration corpus."""
    package = build._unpack(distribution.package_files(ROOT, POLICY), tmp_path / "package")
    home = build._unpack(home_files(ROOT, POLICY), tmp_path / "home")
    env = {k: v for k, v in os.environ.items() if not k.startswith("TAOCHRONOS_")}
    env |= {"PYTHONPATH": str(package), "TAOCHRONOS_CACHE": "off", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
    ran = subprocess.run([sys.executable, "-c", RESEARCH, str(package), str(home), str(tmp_path / "data")], cwd=tmp_path, env=env,
                         capture_output=True, text=True, encoding="utf-8", timeout=600)
    assert ran.returncode == 0, ran.stderr[-2000:]
    out = json.loads(ran.stdout.strip().splitlines()[-1])
    assert out["modules"] == len(browser_modules(ROOT, POLICY)) - 1  # every module but the package itself, walked
    assert out["search"] and out["research"] and out["session"] and out["ask"], out
    assert out["tools"] > 90 and out["strays"] == []


@pytest.fixture(scope="module")
def site(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("distribution") / "site"
    build.build_site(out, home=ROOT, pyodide="cdn")
    return out


def _copy(site: Path, tmp_path: Path) -> Path:
    return Path(shutil.copytree(site, tmp_path / "site"))


def _add(archive: Path, name: str, data: bytes) -> None:
    with zipfile.ZipFile(archive, "a") as zf:
        zf.writestr(name, data)


def test_a_built_site_holds_what_the_policy_allows_and_the_audit_says_what_does_not(site, tmp_path):
    """The site as built passes; each thing that should never be in one is named: a file that is neither the client's
    nor the build's, a module the browser does not import, a gold set or a record in the home, the governance policy
    with its content, a forbidden name, what reads as a credential."""
    assert audit_site(site, ROOT, POLICY) == []
    home = zipfile.ZipFile(site / "runtime" / "home.zip")
    assert not [n for n in home.namelist() if n.startswith(("evals/", "data/"))] and home.read("architecture-policy.yaml") == b""
    assert len([n for n in home.namelist() if distribution.CACHE_ENTRY.match(n)]) > 40  # the YAML parsed by the build's boot
    bad = _copy(site, tmp_path)
    (bad / "data").mkdir()
    (bad / "data" / "records.jsonl").write_text("{}", encoding="utf-8")
    (bad / "js" / "app.js.map").write_text("{}", encoding="utf-8")
    (bad / "js" / "leak.js").write_text('const key = "sk-ant-api03-' + "A1b2C3d4" * 6 + '";\n', encoding="utf-8")
    _add(bad / "runtime" / "taochronos.zip", "taochronos/cli.py", b"print('the command line')\n")
    _add(bad / "runtime" / "home.zip", "evals/gold/ner_heldout.yaml", b"gold: []\n")
    _add(bad / "runtime" / "home.zip", "profiles/minimax.yaml", b"name: minimax\n")
    _add(bad / "runtime" / "home.zip", "corpus/tcm.sqlite", b"SQLite format 3")
    # a gold set copied where the policy ships from, under a name that says nothing: known by the mark it carries
    _add(bad / "runtime" / "home.zip", "domains/classics/more-entities.yaml", (ROOT / "evals" / "gold" / "ner_heldout.yaml").read_bytes())
    problems = audit_site(bad, ROOT, POLICY)
    for needle in ("data/records.jsonl: neither a file of the client", "js/app.js.map: a name the policy forbids (*.map)",
                   "js/leak.js: neither a file of the client", "js/leak.js: reads as a model provider's key",
                   "runtime/taochronos.zip: taochronos/cli.py is not a module the browser imports",
                   "runtime/home.zip: evals/gold/ner_heldout.yaml is not a file the policy names (confidential)",
                   "runtime/home.zip: profiles/minimax.yaml is not a file the policy names (restricted)",
                   "runtime/home.zip: corpus/tcm.sqlite: a name the policy forbids (*.sqlite)",
                   f"runtime/home.zip: domains/classics/more-entities.yaml: reads as confidential data (it carries the canary {POLICY['site']['canaries'][0][:8]}…)"):
        assert [p for p in problems if needle in p], (needle, problems)
    # the nine above, and two named twice: the store in the home and the copied gold set are also not files of the policy
    assert len(problems) == 11
    # an archive that lost a module, the marker with its content, an archive that is none
    worse = _copy(site, tmp_path / "worse")
    names = [n for n in zipfile.ZipFile(worse / "runtime" / "taochronos.zip").namelist() if n != "taochronos/chat/jobs.py"]
    with zipfile.ZipFile(site / "runtime" / "taochronos.zip") as src, zipfile.ZipFile(worse / "runtime" / "taochronos.zip", "w") as dst:
        for n in names:
            dst.writestr(n, src.read(n))
    with zipfile.ZipFile(site / "runtime" / "home.zip") as src, zipfile.ZipFile(worse / "runtime" / "home.zip", "w") as dst:
        for n in src.namelist():
            dst.writestr(n, (ROOT / n).read_bytes() if n == "architecture-policy.yaml" else src.read(n))
    problems = audit_site(worse, ROOT, POLICY)
    assert problems == ["runtime/taochronos.zip: taochronos/chat/jobs.py is missing (the browser imports it)",
                        "runtime/home.zip: architecture-policy.yaml is the home's marker and ships empty, not with its content"]
    (worse / "runtime" / "home.zip").write_bytes(b"not an archive")
    (worse / "runtime" / "manifest.json").unlink()
    assert {"runtime/manifest.json is missing or unreadable", "runtime/home.zip is missing or not an archive"} <= set(audit_site(worse, ROOT, POLICY))


def test_a_webassembly_module_the_build_ships_imports_nothing(site, tmp_path):
    """The text scan reads no binary; of a module, the audit knows what it may reach.  TaoCore's (runtime/taocore.wasm)
    imports nothing: it computes on its own memory and gives numbers back.  One that imports — or bytes that are no
    module — is not shipped."""
    assert distribution.wasm_imports((site / "runtime" / "taocore.wasm").read_bytes()) == 0
    assert distribution.wasm_imports(b"\0asm\x01\0\0\0") == 0 and distribution.wasm_imports(b"not a module") is None
    importing = b"\0asm\x01\0\0\0" + b"\x02\x07\x01\x01m\x01f\x00\x00"  # one import, m.f
    assert distribution.wasm_imports(importing) == 1 and distribution.wasm_imports(importing[:-3]) is None
    bad = _copy(site, tmp_path)
    (bad / "runtime" / "taocore.wasm").write_bytes(importing)
    assert audit_site(bad, ROOT, POLICY) == ["runtime/taocore.wasm: not a WebAssembly module of no imports (the build ships only "
                                             "such: it computes and reaches nothing)"]


def test_a_client_that_carries_a_credential_is_not_built(tmp_path):
    """The build checks what it built: a client with a key written into it stops there, and nothing publishes it."""
    web = Path(shutil.copytree(ROOT / "web", tmp_path / "web", ignore=shutil.ignore_patterns("node_modules", "tests")))
    (web / "js" / "config.js").write_text('export const LOG_EXPORT_TOKEN = "' + "0123456789abcdef" * 2 + '";\n', encoding="utf-8")
    with pytest.raises(DistributionError, match=r"must not be published: js/config\.js: reads as a secret of this project with its value"):
        build.build_site(tmp_path / "site", home=ROOT, web=web, pyodide="cdn")


def test_what_reads_as_a_credential_and_what_does_not():
    """By the forms the services issue them in: a name alone, a placeholder or a hash is not one."""
    reads = distribution._credentials
    assert reads("-----BEGIN PRIVATE KEY-----\nMIIE") == ["a private key"] and reads("-----BEGIN OPENSSH PRIVATE KEY-----") == ["a private key"]
    assert reads("aws_access_key_id = AKIAIOSFODNN7EXAMPLE") == ["an AWS access key"]
    assert reads("token ghp_" + "a1B2" * 9) == ["a GitHub token"]
    assert reads('"sk-ant-api03-' + "x9Y8" * 10 + '"') == ["a model provider's key"] and reads("sk-" + "Ab12" * 12) == ["a model provider's key"]
    assert reads("AIza" + "Sy" + "D4-_" * 8 + "a") == ["a Google API key"]
    assert reads("MINIMAX_API_KEY=" + "ab12" * 8) == ["a secret of this project with its value"]
    assert reads('SENTINEL_SALT: "' + "0f" * 16 + '"') == ["a secret of this project with its value"]
    for harmless in ('"api_key_env": "MINIMAX_API_KEY"', 'os.environ.get("OPENAI_API_KEY")', "Authorization: Bearer sk-...", "sk-xxxx",
                     'MINIMAX_API_KEY="$MINIMAX_API_KEY"', "sha256: " + "ab" * 32, "taochronos-collector/1", "LOG_EXPORT_TOKEN (the collector's)"):
        assert reads(harmless) == [], harmless
