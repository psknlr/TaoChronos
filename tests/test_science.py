from taochronos.science import benjamini_hochberg, fisher_exact_greater, jensen_shannon, wilson_interval
from taochronos.science.contradiction import classify_passages
from taochronos.tools.adapters import contradiction_context


def test_statistics():
    assert jensen_shannon({"a": 1}, {"a": 1}) == 0
    assert 0 < fisher_exact_greater(3, 0, 0, 10) < 0.01
    lo, hi = wilson_interval(5, 10)
    assert lo < 0.5 < hi
    assert benjamini_hochberg({"x": 0.001, "y": 0.8}, 0.1) == {"x": True, "y": False}


def _classify(harness, a, b):
    kb = harness.capabilities.get("knowledge")
    by = {}
    for c in kb.claims():
        by.setdefault(c.passage_id, []).append(c)
    ctx = contradiction_context(harness.pack, harness.corpus, harness.philology, lineage=kb.lineage())
    return classify_passages(by.get(a, []), by.get(b, []) if a != b else by.get(a, []), ctx, a, b)


def test_contradiction_labels(harness):
    assert _classify(harness, "shanghanlun.c176", "shanghanlun.c176")["type"] == "philological"
    assert _classify(harness, "zhubing.05.xiaoke", "shanghanlun.c071")["type"] == "sense_shift"
    assert _classify(harness, "suwen.074.zhize", "piwei.rezhong")["label"] == "conditional"
    assert _classify(harness, "jinkui.05.zhongfeng", "yilin_gaicuo.bansui")["label"] == "contradiction"
    assert _classify(harness, "shanghanlun.c013", "shanghanlun.c035")["label"] == "unrelated"  # differential, not conflict


def test_discovery_tools(harness):
    from taochronos.kernel import Actor, ToolCall

    call = lambda name, **a: harness.scheduler.execute(ToolCall(name, a), actor=Actor.kernel()).result  # noqa: E731
    families = call("analysis.formula_evolution")["families"]
    shenqi = next(f for f in families if "formula:肾气丸" in f["members"])
    assert {"herb:地黄", "herb:山茱萸", "herb:山药"} <= set(shenqi["stable_core"])
    drift = call("analysis.concept_drift", term="消渴")
    assert drift["sense_changes"]
    lost = call("analysis.lost_knowledge", pivot_year=960)
    assert any(t["herb"] == "herb:金银花" for t in lost["testimony"])
    missing = call("analysis.missing_sources")
    assert missing and missing[0]["source"] == "gujin_luyan"
