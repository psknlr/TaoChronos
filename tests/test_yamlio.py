"""The YAML parse cache: keyed by content, a fresh object per call, safe to damage or switch off."""

from __future__ import annotations

from taochronos.protocol import yamlio


def test_parsed_once_per_content_and_never_stale(tmp_path, monkeypatch):
    monkeypatch.setenv("TAOCHRONOS_CACHE", str(tmp_path / "cache"))
    f = tmp_path / "a.yaml"
    f.write_text("terms: [消渴, 渴]\nyear: 610\n", encoding="utf-8")
    first = yamlio.load_yaml(f)
    assert first == {"terms": ["消渴", "渴"], "year": 610}
    assert len(list((tmp_path / "cache" / "yaml").rglob("*.pickle"))) == 1
    first["terms"].append("changed")  # callers may modify what they get: the cache is not shared state
    assert yamlio.load_yaml(f) == {"terms": ["消渴", "渴"], "year": 610}
    f.write_text("terms: [消渴]\n", encoding="utf-8")  # an edited file is another key
    assert yamlio.load_yaml(f) == {"terms": ["消渴"]}
    assert yamlio.loads_yaml("a: 1") == {"a": 1}


def test_a_damaged_entry_is_parsed_again_and_the_cache_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setenv("TAOCHRONOS_CACHE", str(tmp_path / "cache"))
    f = tmp_path / "b.yaml"
    f.write_text("k: v\n", encoding="utf-8")
    yamlio.load_yaml(f)
    entry = next((tmp_path / "cache" / "yaml").rglob("*.pickle"))
    entry.write_bytes(b"not a pickle")
    assert yamlio.load_yaml(f) == {"k": "v"}
    monkeypatch.setenv("TAOCHRONOS_CACHE", "off")
    assert yamlio.cache_dir() is None and yamlio.load_yaml(f) == {"k": "v"}


def test_a_document_the_c_loader_refuses_is_read_by_the_python_loader(tmp_path, monkeypatch):
    import yaml

    class Refusing(yaml.SafeLoader):  # stands in for an older libyaml's CSafeLoader
        def __init__(self, stream):
            raise yaml.scanner.ScannerError("while scanning a plain scalar", None, "found unexpected ':'", None)

    monkeypatch.setenv("TAOCHRONOS_CACHE", "off")
    monkeypatch.setattr(yamlio, "_LOADER", Refusing)
    assert yamlio.loads_yaml("candidates: [modern:polydipsia, modern:diabetes_mellitus]\n") == {
        "candidates": ["modern:polydipsia", "modern:diabetes_mellitus"]}


def test_the_fast_serialiser_writes_what_the_general_one_did(research):
    """to_jsonable's fast paths (exact types first, field names cached per type) change nothing it produces."""
    import dataclasses
    import enum
    import json
    from collections.abc import Mapping

    from taochronos.protocol.base import to_jsonable

    def general(obj):
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            return {f.name: general(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
        if isinstance(obj, enum.Enum):
            return obj.value
        if isinstance(obj, Mapping):
            return {str(k): general(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [general(v) for v in obj]
        if isinstance(obj, (set, frozenset)):
            return sorted(general(v) for v in obj)
        if isinstance(obj, float) and obj != obj:
            return None
        return obj

    _, session = research
    dump = lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False)  # noqa: E731
    assert dump(to_jsonable(session.state)) == dump(general(session.state))
    assert to_jsonable({1: float("nan"), "s": {3, 1}, "t": (1, "a")}) == {"1": None, "s": [1, 3], "t": [1, "a"]}


def test_the_incremental_integrity_check_agrees_with_a_full_replay(research):
    _, session = research
    fork = session.fork(purpose="incremental verify", record_in_parent=False, new_session_id="ref.incremental")
    first = fork.verify_incremental()
    assert first["consistent"] and first["replayed_hash"] == fork.verify()["replayed_hash"]
    from taochronos.protocol import EventType as E

    fork.emit(E.DECISION_RECORDED, {"decisions": []})
    again = fork.verify_incremental()  # advanced by the new event only
    assert again["consistent"] and again["replayed_hash"] == fork.verify()["replayed_hash"]
    hyp = next(iter(fork.state.hypotheses.values()))
    hyp.status = "expert_approved"  # a change behind the log
    assert not fork.verify_incremental()["consistent"]


def test_the_state_hash_is_the_content_hash_of_the_scientific_state_alone(research):
    import gc

    from taochronos.protocol.artifacts import OPERATIONAL_ARTIFACT_KINDS
    from taochronos.protocol.base import content_hash, gc_paused
    from taochronos.protocol.research import OPTIONAL_SCIENTIFIC_FIELDS, SCIENTIFIC_FIELDS

    def as_before(st):  # the definition before the lean path: serialise everything, then keep the scientific fields
        data = st.to_dict()
        kept = {k: data[k] for k in SCIENTIFIC_FIELDS} | {k: data[k] for k in OPTIONAL_SCIENTIFIC_FIELDS if data.get(k)}
        for task in kept["task_graph"].values():
            if task.get("status") == "running":
                task["status"] = "pending"
        kept["artifacts"] = {k: v for k, v in kept["artifacts"].items() if v.get("kind") not in OPERATIONAL_ARTIFACT_KINDS}
        return content_hash(kept)

    _, session = research
    fork = session.fork(purpose="state hash", record_in_parent=False, new_session_id="ref.statehash")
    state = fork.state
    assert state.state_hash() == content_hash(state.scientific_state()) == as_before(state)
    before = state.state_hash()
    state.metrics["probe"] = 1  # operational: not part of what is hashed
    state.run_manifest = {"probe": True}
    assert state.state_hash() == before
    with gc_paused():
        assert not gc.isenabled()
    assert gc.isenabled()


def test_a_checkpoint_after_a_check_records_what_a_fresh_hash_gives_and_a_restore_replays_afresh(research):
    _, session = research
    fork = session.fork(purpose="checkpoint reuse", record_in_parent=False, new_session_id="ref.checkpoint")
    assert fork.verify_incremental()["consistent"]
    event = fork.checkpoint()  # reuses the check's hash
    assert event.payload["state_hash"] == fork.state.state_hash() == fork.verify()["replayed_hash"]
    assert fork.verify_incremental()["checkpoint_mismatches"] == []
    fork.restore()  # a rebuild from the log drops the kept replay
    assert fork._shadow is None and fork.verify_incremental()["consistent"]
    hyp = next(iter(fork.state.hypotheses.values()))
    hyp.status = "expert_approved"  # a change behind the log, after a check: the checkpoint still records the log's hash
    event = fork.checkpoint()
    assert event.payload["state_hash"] == fork.replay().state_hash() and not fork.verify_incremental()["consistent"]
