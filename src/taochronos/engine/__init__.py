"""Research engine: the operational loop (tasks, agents, commits) inside the scientific loop (rounds)."""

from .report import build as build_report
from .report import publish_report
from .research import ResearchEngine, RunResult

__all__ = ["ResearchEngine", "RunResult", "build_report", "publish_report"]
