"""Shared fixtures: an in-memory harness and one reference research run (both session-scoped)."""

from __future__ import annotations

from pathlib import Path

import pytest

from taochronos.bootstrap import Harness
from taochronos.kernel import MemoryEventStore

HOME = Path(__file__).resolve().parents[1]
QUESTION = "消渴的概念如何随时代演变？宋代以前治疗消渴的哪些知识后来被遗忘？"


def make_harness(tmp: Path, profile: str = "full-discovery", **kw):
    kw.setdefault("store", MemoryEventStore())
    return Harness.from_profile(profile, home=HOME, data_dir=tmp, **kw)


def run_research(harness, session_id: str = "t", question: str = QUESTION, **fields):
    engine = harness.engine()
    fields.setdefault("focus_terms", ["消渴"])
    fields.setdefault("forbidden_assumptions", ["消渴=糖尿病"])
    session = engine.start(harness.make_goal(question, **fields), session_id=session_id)
    engine.run(session)
    return session


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("taochronos-data")


@pytest.fixture(scope="session")
def harness(data_dir):
    return make_harness(data_dir)


@pytest.fixture(scope="session")
def research(data_dir):
    h = make_harness(data_dir)
    return h, run_research(h, "ref")
