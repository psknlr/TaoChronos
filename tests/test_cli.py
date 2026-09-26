import json

from taochronos.cli import main


def _run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr().out
    return code, out


def test_cli_info_agents_search(capsys, tmp_path):
    code, out = _run(capsys, "--data", str(tmp_path), "info")
    info = json.loads(out)
    assert code == 0 and info["name"] == "TaoChronos" and info["agents"]["director"] == "TaoChronos"
    _, out = _run(capsys, "--data", str(tmp_path), "agents")
    assert out.splitlines()[0].startswith("TaoChronos ")
    _, out = _run(capsys, "--data", str(tmp_path), "search", "膜原最早见于何书", "-k", "2")
    assert "suwen.035" in out


def test_cli_research_report_replay(capsys, tmp_path):
    code, out = _run(capsys, "--data", str(tmp_path), "research", "消渴的概念如何随时代演变？", "--focus", "消渴",
                     "--forbid", "消渴=糖尿病", "--max-rounds", "1", "--session", "cli")
    result = json.loads(out)
    assert code == 0 and result["status"] in ("completed", "max_rounds")
    _, out = _run(capsys, "--data", str(tmp_path), "report", "cli")
    assert out.startswith("# TaoChronos 发现报告")
    _, out = _run(capsys, "--data", str(tmp_path), "replay", "cli")
    assert json.loads(out)["consistent"] is True
    _, out = _run(capsys, "--data", str(tmp_path), "workspace", "cli")
    assert out.strip().endswith("workspace.html")
    _, out = _run(capsys, "--data", str(tmp_path), "export", "cli", "--format", "cypher")
    assert "MERGE" in out


def test_cli_schema_and_governance(capsys):
    _, out = _run(capsys, "schema", "--outputs")
    assert "HypothesisSet" in json.loads(out)
    code, out = _run(capsys, "governance")
    assert code == 0 and json.loads(out)["violations"] == []
