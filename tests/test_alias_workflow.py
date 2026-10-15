"""The aliases workflow (``.github/workflows/aliases.yml``, ADR 0023) and the sizes the docs quote for the layer: the
commit job's guard covers every file a build on the site's store reads, the report and decide steps say why a layer
waits, and a size is quoted with one measure."""

from __future__ import annotations

import builtins
import gzip
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from test_alias_build import make_home, make_store

from taochronos.plugins.classics.aliasbuild import FILES, build_open, deflated
from taochronos.plugins.classics.store import CorpusStore
from taochronos.protocol.yamlio import load_yaml

HOME = Path(__file__).resolve().parents[1]
WORKFLOW = HOME / ".github" / "workflows" / "aliases.yml"


def _steps(job: str) -> list[dict]:
    return load_yaml(WORKFLOW)["jobs"][job]["steps"]


def _inputs() -> list[str]:
    """The paths the commit job compares between the run's commit and the branch's head."""
    run = next(s for s in _steps("commit") if s.get("name") == "Commit the layer and the tables")["run"]
    return re.search(r"^inputs=\(([^)]*)\)$", run, re.MULTILINE).group(1).split()


def _web_flags(text: str, surface: str) -> dict[str, int]:
    rec = next(r for r in map(json.loads, text.splitlines()[1:]) if r.get("s") == surface)
    return {w[0]: w[4] for ref in rec["r"] for w in ref.get("w") or []}


def test_the_commit_guard_covers_every_file_a_build_on_the_full_store_reads(tmp_path, monkeypatch):
    """On the site's store (labelled full) the build reads the 要籍语料's pack besides the domain, for its witnesses'
    `web` flags.  canon.yml commits corpus/web under a concurrency group of its own: every file the build reads must
    lie under the paths the commit job compares, or a canon run during the eval lets a stale layer through."""
    home = make_home(tmp_path)
    store = make_store(tmp_path / "data" / "corpus" / "tcm.sqlite")
    db = CorpusStore(store)
    db.set_meta("edition", "full")
    db.commit()
    db.close()
    pack = home / "corpus" / "web" / "passages.jsonl.gz"
    pack.parent.mkdir(parents=True)
    with gzip.open(pack, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": "bc_a.00000"}) + "\n")
    read: list[Path] = []
    real = io.open

    def traced(file, *args, **kwargs):
        if isinstance(file, (str, os.PathLike)):
            read.append(Path(file))
        return real(file, *args, **kwargs)

    with monkeypatch.context() as m:
        m.setattr(io, "open", traced)
        m.setattr(builtins, "open", traced)
        flagged = build_open(store, home).text()
    rel = set()
    for p in read:
        for root in (home, HOME):  # the home's domain links to the repository's
            if p.is_relative_to(root):
                rel.add(p.relative_to(root))
                break
    assert Path("corpus/web/passages.jsonl.gz") in rel and Path("domains/classics/aliases/curated.yaml") in rel
    inputs = [Path(i) for i in _inputs()]
    assert not sorted(str(p) for p in rel if not any(p == i or i in p.parents for i in inputs))
    # the pack decides the flags: a pack without the witness gives another layer
    with gzip.open(pack, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": "bc_a.00001"}) + "\n")
    assert _web_flags(flagged, "国老")["bc_a.00000"] == 1
    assert _web_flags(build_open(store, home).text(), "国老")["bc_a.00000"] == 0
    # and the workflow's header names what the guard compares
    header = WORKFLOW.read_text(encoding="utf-8").split("\non:", 1)[0]
    assert not [i for i in _inputs() if i not in header]


def _heredoc(step: dict) -> str:
    run = step["run"]
    return run[run.index("<<'EOF'\n") + len("<<'EOF'\n"):run.rindex("\nEOF")]


def _gh(tmp_path: Path, name: str, argv: list[str], env: dict[str, str], stdin: str | None = None) -> dict[str, str]:
    """A step run as GitHub runs it; returns its outputs and its summary."""
    out, summary = tmp_path / f"{name}.out", tmp_path / f"{name}.md"
    for f in (out, summary):
        f.write_text("", encoding="utf-8")
    env = {**os.environ, **env, "GITHUB_OUTPUT": str(out), "GITHUB_STEP_SUMMARY": str(summary)}
    proc = subprocess.run(argv, input=stdin, cwd=tmp_path, env=env, capture_output=True, text=True, check=True)
    lines = out.read_text(encoding="utf-8").split()
    return {**dict(x.split("=", 1) for x in lines), "summary": summary.read_text(encoding="utf-8"),
            "stdout": proc.stdout}


def _part(profile: str, view: str, split: str, notes: list[str]) -> dict:
    tables = {s: {split: {"all": {"P@10": 0.5}}} for s in ("off", "on")}
    entry = {"pair": "deployed" if profile == "full-corpus" else "proxy", "split": split, "store": {"edition": "full"},
             "results": {"acceptance": {"met": True, "checks": {"P@10": True}}, "views": {view: tables}}}
    gold = {"items": 2, "resolution": 0, "split_sha256": "0" * 12, "valid": True, "store_valid": split == "heldout"}
    return {"aliases": {"metrics": {"gold": gold, "synthetic": {"ok": True}, profile: entry}, "details": [],
                        "notes": notes, "seconds": 60}}


def test_a_commit_waits_for_the_held_out_split_and_says_why(tmp_path):
    """The eval refuses the held-out split while the gold fails its checks (aliases_gold.validate) and says so in its
    notes: the report carries that note, and the decide step names that refusal as the reason — not a cause the eval
    does not refuse on."""
    report = _heredoc(next(s for s in _steps("report") if s.get("id") == "merge"))
    decide = next(s for s in _steps("commit") if s.get("id") == "decide")["run"]
    refused = "held-out split refused: the gold fails its checks on the store (aliases_gold.validate)"  # the eval's note
    for split, measured in (("dev", "false"), ("heldout", "true")):
        for p in ("web-canon", "full-corpus"):
            for v in ("main", "no-gangmu"):
                part = _part(p, v, split, [refused] if split == "dev" else [])
                (tmp_path / f"aliases-full-{p}-{v}.json").write_text(json.dumps(part), encoding="utf-8")
        merged = _gh(tmp_path, f"report-{split}", [sys.executable, "-"], {"CHECKED": "true"}, report)
        assert merged["measured"] == measured and merged["accepted"] == measured
        assert (refused in merged["summary"]) == (split == "dev")
        gate = _gh(tmp_path, f"decide-{split}", ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", decide],
                   {"COMMIT": "true", "EVAL": "true", "CHECKED": "true", "MEASURED": measured, "ACCEPTED": measured,
                    "GITHUB_REF_TYPE": "branch", "GITHUB_REF_NAME": "main"})
        assert gate["go"] == ("1" if split == "heldout" else "0")
        if split == "dev":
            assert "eval refused that split because the gold fails its checks, aliases_gold.validate" in gate["summary"]
            assert "the report says which" in gate["summary"]


SIZE = re.compile(r"([\d,]{5,}) bytes \((?:([\d,]+) deflated; )?the directory ([\d,]+)")


def test_the_docs_quote_the_layer_s_size_with_one_measure():
    """The layer's size is measured as home.zip stores it (zlib's default level, `aliases check`): every document
    that quotes a raw size gives the same deflated sizes for it, and for the file in the tree what `deflated` gives."""
    seen: dict[str, list[tuple[str, str, str]]] = {}
    for doc in sorted(HOME.glob("docs/**/*.md")) + [HOME / "README.md", HOME / "README.en.md"]:
        text = " ".join(doc.read_text(encoding="utf-8").split())  # wrapped lines joined
        for raw, file, directory in SIZE.findall(text):
            seen.setdefault(raw, []).append((doc.name, file, directory))
    assert seen
    for raw, quotes in seen.items():
        assert len({f for _, f, _ in quotes if f}) <= 1 and len({d for *_, d in quotes}) == 1, (raw, quotes)
    d = HOME / "domains" / "classics" / "aliases"
    text = (d / "aliases.jsonl").read_bytes()
    for _, file, directory in seen.get(f"{len(text):,}", []):
        assert int(directory.replace(",", "")) == sum(deflated((d / f).read_bytes()) for f in FILES)
        assert not file or int(file.replace(",", "")) == deflated(text)
