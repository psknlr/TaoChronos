"""What the alias layer may publish (ADR 0023): the committed layer credits shippable sources only, its directory holds
its four files and nothing local, no deployed profile reads a local layer, curated.yaml is well formed, writes no
held-out gold string in any spelling and cites no 别名录 passage, and ``aliases check`` passes on what is committed."""

from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

import pytest
import yaml

from taochronos.evals.aliases_gold import heldout_surfaces, load_gold
from taochronos.kernel.profiles import list_profiles, load_profile
from taochronos.plugins.classics import aliasbuild
from taochronos.plugins.classics.aliases import loads_records
from taochronos.plugins.classics.domain import DomainPack
from taochronos.plugins.classics.ingest.aliases import BOOK, LOCAL_SOURCES

HOME = Path(__file__).resolve().parents[1]
FOLDER = HOME / "domains" / "classics" / "aliases"
LOCAL_NAMES = {f"{name}.jsonl" for name in LOCAL_SOURCES} | {aliasbuild.LOCAL_FILE, "manifest.json", "review.tsv"}


def registry() -> dict:
    return {s["id"]: s for s in yaml.safe_load((FOLDER / "sources.yaml").read_text(encoding="utf-8"))["sources"]}


def committed() -> tuple[dict, list]:
    return loads_records((FOLDER / "aliases.jsonl").read_text(encoding="utf-8"), "aliases.jsonl")


def test_every_source_a_record_credits_ships():
    sources = registry()
    header, records = committed()
    used = {src for rec in records for ref in rec.r for src in ref.src}
    assert used and all(sources[s]["ship"] is True and sources[s]["class"] in ("open", "derived") for s in used)
    assert set(header["sources"]) == used
    assert {s: header["labels"][s] for s in used} == {s: sources[s]["label"] for s in used}
    assert sources["bielu-jc"]["label"] == "别名录（中醫笈成）" and "lexicon" in sources


def test_local_sources_never_ship():
    sources = registry()
    for sid in LOCAL_SOURCES.values():
        assert sources[sid]["ship"] is False and sources[sid]["class"] == "local"
    assert sources["ntu40k"]["licence"] == "CC BY-NC 4.0" and "unverified" in sources["ntu40k"]["attribution"]


def test_the_directory_holds_its_four_files_and_the_domain_nothing_local():
    assert sorted(p.name for p in FOLDER.iterdir()) == sorted(aliasbuild.FILES)
    stray = [p for p in (HOME / "domains").rglob("*") if p.name in LOCAL_NAMES]
    assert stray == []


def test_deployed_profiles_read_no_local_layer():
    dirs = [HOME / "profiles"]
    local = []
    for name in list_profiles(dirs):
        profile = load_profile(name, dirs)
        for bundle in profile.bundles:
            if (bundle.get("config") or {}).get("aliases_local"):
                local.append(name)
    assert local == ["full-corpus-local"]
    assert not any((HOME / "profiles" / f"{name}.yaml").read_text(encoding="utf-8").count("aliases_local")
                   for name in ("web-canon", "full-corpus"))


def normalize():
    return DomainPack(HOME / "domains" / "classics").variants.normalize_text


def test_curated_is_well_formed_and_names_no_held_out_gold_name():
    curated = yaml.safe_load((FOLDER / "curated.yaml").read_text(encoding="utf-8"))
    assert aliasbuild.validate_curated(curated) == []
    assert aliasbuild.heldout_in(curated, heldout_surfaces(load_gold(HOME)), normalize()) == []


def test_curated_writes_no_held_out_string_and_cites_no_list():
    """Stricter than ``check``: no held-out gold string anywhere in the file, in any spelling (the text and the names
    normalised), reasons and comments included, and no witness from the 别名录 the layer is built from (the cover
    strings' witnesses are in comments)."""
    text = (FOLDER / "curated.yaml").read_text(encoding="utf-8")
    norm = normalize()
    folded = norm(text)
    assert sorted(h for h in {norm(x) for x in heldout_surfaces(load_gold(HOME))} if h in folded) == []
    curated = yaml.safe_load(text)
    wit = [p for key in ("stop", "same_drug", "pairs", "first_use", "decisions", "head_repairs")
           for row in curated.get(key) or [] for p in row.get("wit") or []]
    comments = "\n".join(re.findall(r"#.*", text))
    assert wit and not [p for p in wit if p.startswith(f"{BOOK}.")] and f"{BOOK}." not in comments


def test_the_committed_layer_passes_check():
    result = aliasbuild.check(HOME, heldout=heldout_surfaces(load_gold(HOME)))
    assert result["ok"], result["errors"]
    assert result["bytes"]["raw"] <= aliasbuild.BUDGET["raw"] and result["bytes"]["deflated"] <= aliasbuild.BUDGET[
        "deflated"] and result["bytes"]["directory"] <= aliasbuild.BUDGET["directory"]


def test_web_witnesses_are_in_the_web_pack():
    pack = HOME / "corpus" / "web" / "passages.jsonl.gz"
    if not pack.exists():
        pytest.skip("no committed web pack")
    _, records = committed()
    flagged = {w.pid for rec in records for ref in rec.r for w in ref.w if w.web}
    with gzip.open(pack, "rt", encoding="utf-8") as fh:
        ids = {json.loads(line)["id"] for line in fh if line.strip()}
    assert flagged and flagged <= ids


def test_the_worker_tables_credit_shippable_sources_only():
    tables = HOME / "cloud" / "site" / "src" / "backup" / "tables.js"
    text = tables.read_text(encoding="utf-8") if tables.exists() else ""
    m = re.search(r"ALIAS_SOURCES\s*=\s*(\[.*?\]);", text, re.S)
    if m is None:
        pytest.skip("tables.js does not carry the alias layer yet (phase B)")
    sources = registry()
    assert all(sources[row["id"]]["ship"] is True for row in json.loads(m.group(1)))
