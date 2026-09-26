import shutil

from taochronos.evals import run_suites
from taochronos.governance import check

from conftest import HOME


def test_quick_eval_suites(tmp_path):
    results = run_suites(["philology", "anachronism", "temporal", "hallucination", "contradiction"], home=HOME, data_dir=tmp_path)
    assert results["philology"]["metrics"]["pass_rate"] == 1.0
    assert results["anachronism"]["metrics"]["agent_equivalence_blocked"] is True
    assert results["anachronism"]["metrics"]["block"]["fp"] == 0
    assert results["temporal"]["metrics"]["period_leakage"] == 0
    assert results["hallucination"]["metrics"]["fabricated_detection"] == 1.0
    assert results["contradiction"]["metrics"]["accuracy"] >= 0.8


def test_source_rediscovery(tmp_path):
    metrics = run_suites(["source_rediscovery"], home=HOME, data_dir=tmp_path)["source_rediscovery"]["metrics"]
    assert metrics["recall@3"] == 1.0 and metrics["date_bound_consistent"] == 1.0


def test_governance_detects_a_layering_violation(tmp_path):
    copy = tmp_path / "repo"
    shutil.copytree(HOME, copy, ignore=shutil.ignore_patterns(".git", ".taochronos", "__pycache__", "*.egg-info", "tests"))
    assert check(copy)["violations"] == []
    bad = copy / "src" / "taochronos" / "kernel" / "leak.py"
    bad.write_text("from ..plugins.models.anthropic_provider import AnthropicProvider  # claude\n")
    rules = {v["rule"] for v in check(copy)["violations"]}
    assert {"layering", "kernel_forbidden_term"} <= rules
