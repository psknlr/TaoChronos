"""The run manifest: what a reader needs to reproduce a research, recorded in the log.

It is written twice — when the research starts (inputs) and when it stops (what was used) — and names: the corpus
snapshot (a fingerprint of the passages in scope), the versions of the lexicon, ontology and every domain file (content
hashes), the code (package version, git commit, whether the tree was clean), the agent specs, skills and prompts
(hashes), the models and routes used (never keys), the seeds, the environment, and a digest over every tool receipt
in the log — so a replay can show it read the same things.  Artifacts carry their own hashes in their events.
"""

from __future__ import annotations

import hashlib
import platform
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..protocol.base import canonical_json
from ..protocol.events import EventType


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:20]


@lru_cache(maxsize=16)
def tree_hash(root: str, pattern: str = "**/*.yaml") -> dict[str, str]:
    base = Path(root)
    if not base.exists():
        return {}
    return {str(p.relative_to(base)): _sha(p.read_bytes()) for p in sorted(base.glob(pattern)) if p.is_file()}


def _digest(entries: dict[str, str]) -> str:
    return _sha(canonical_json(entries).encode("utf-8"))


@lru_cache(maxsize=4)
def code_version(home: str) -> dict[str, Any]:
    from .. import __version__

    out: dict[str, Any] = {"package": __version__}
    try:
        rev = subprocess.run(["git", "-C", home, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5)
        dirty = subprocess.run(["git", "-C", home, "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True, timeout=5)
        if rev.returncode == 0:
            out["commit"] = rev.stdout.strip()
            out["clean"] = dirty.returncode == 0 and not dirty.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return out


def corpus_snapshot(harness: Any, state: Any) -> dict[str, Any]:
    corpus = harness.corpus
    manifest = state.corpus
    ids = sorted(manifest.passage_ids) if manifest is not None else []
    snap: dict[str, Any] = {"kind": "store" if getattr(corpus, "large", False) else "files", "books": len(corpus.books),
                            "scope_passages": len(ids), "scope_ids_sha": _sha("\n".join(ids).encode("utf-8"))}
    if manifest is not None:
        snap["withheld"] = {"holdout": len(manifest.holdout_passage_ids), "confirmation": len(manifest.confirmation_passage_ids),
                            "expert_only": len(manifest.expert_only_passage_ids)}
    store = getattr(corpus, "store", None)
    meta = getattr(store, "meta", None)
    if callable(meta):
        for key in ("fingerprint", "index_fingerprint", "passages"):
            value = meta(key)
            if value:
                snap[f"store_{key}"] = value
    elif ids:  # a file corpus: hash the texts in scope
        h = hashlib.sha256()
        for p in corpus.passages_by_id(ids):
            h.update(p.id.encode("utf-8"))
            h.update(p.text.encode("utf-8"))
        snap["scope_text_sha"] = h.hexdigest()[:20]
    return snap


def receipts_digest(events: list[Any]) -> dict[str, Any]:
    """A hash chain over the tool receipts in the log, in order."""
    h = hashlib.sha256()
    n = quarantined = 0
    for e in events:
        if e.type == EventType.TOOL_RESULT.value and e.payload.get("receipt"):
            h.update(canonical_json(e.payload["receipt"]).encode("utf-8"))
            n += 1
            quarantined += bool(e.payload["receipt"].get("quarantined"))
    return {"tool_receipts": n, "quarantined": quarantined, "chain_sha": h.hexdigest()[:24]}


def run_manifest(harness: Any, session: Any, *, phase: str) -> dict[str, Any]:
    home = str(harness.home)
    state = session.state
    domains = tree_hash(str(harness.home / "domains"))
    agents = tree_hash(str(harness.home / "agents"))
    skills = tree_hash(str(harness.home / "skills"), "**/*")
    prompts = tree_hash(str(Path(__file__).resolve().parents[1] / "agents"), "prompts.py")
    manifest: dict[str, Any] = {
        "phase": phase,
        "session": session.id,
        "profile": harness.profile.name,
        "goal_digest": state.goal_digest,
        "code": code_version(home),
        "corpus": corpus_snapshot(harness, state),
        "domain_data": {"digest": _digest(domains), "files": len(domains),
                        "lexicon": {k: v for k, v in domains.items() if "lexic" in k or "terminology" in k},
                        "ontology": {k: v for k, v in domains.items() if "ontology" in k or "hpo" in k or "phenotypes" in k}},
        "agents": {"digest": _digest(agents), "specs": sorted(harness.specs)},
        "skills": {"digest": _digest(skills), "count": len(skills)},
        "prompts": {"digest": _digest(prompts)},
        "models": {"routing": dict(harness.profile.routing or {}), "judge": {k: v for k, v in (harness.profile.judge or {}).items()
                                                                          if k in ("provider", "model", "tier", "temperature")},
                   "routes": state.metrics.get("routes", {}) if phase == "end" else {}},
        "seeds": {"confirmation": state.goal.confirmation.seed if state.goal and state.goal.confirmation else None,
                  "tournament": "round number", "permutation_tests": "fixed per analysis (0 unless stated)"},
        "environment": {"python": sys.version.split()[0], "platform": platform.platform(terse=True)},
    }
    if phase == "end":
        events = session.events()
        manifest["tools"] = receipts_digest(events)
        manifest["llm_calls"] = int(state.metrics.get("llm_calls", 0))
        manifest["events"] = len(events)
        manifest["state_hash"] = state.state_hash()
    return manifest
