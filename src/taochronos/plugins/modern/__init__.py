"""Modern evidence (S13) and real-world data (S14): PubMed typed by design and population with the cross-level guard,
the safety table, and questions about real-world data as validated study specs over the OMOP common data model."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import rwd
from .service import ModernEvidence


class RWDService:
    """The ``rwd`` capability: a question → a study spec → a checked query on an OMOP database (read-only)."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def default_db(self) -> Path:
        return self.data_dir / "rwd" / "omop-synthetic.sqlite"

    def ensure_demo(self) -> Path:
        path = self.default_db()
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            rwd.synthesize(path)
        return path

    def spec(self, question: str, db: str | Path | None = None, *, judge: Any = None) -> dict[str, Any]:
        import sqlite3

        path = Path(db) if db else self.ensure_demo()
        con = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
        try:
            spec = rwd.spec_by_model(question, con, judge) if judge is not None else rwd.spec_from_question(question, con)
            if spec.get("ok") is False:  # the model failed: the rules
                spec = rwd.spec_from_question(question, con)
            errors = rwd.check_spec(spec, con)
        finally:
            con.close()
        return {"spec": spec, "errors": errors, "db": str(path), "by": "model" if judge is not None else "rules"}

    def run(self, spec: dict[str, Any], db: str | Path | None = None) -> dict[str, Any]:
        return rwd.run(spec, Path(db) if db else self.ensure_demo())

    def ask(self, question: str, db: str | Path | None = None, *, judge: Any = None) -> dict[str, Any]:
        s = self.spec(question, db, judge=judge)
        if s["errors"]:
            return {"ok": False, "stage": "spec", **s}
        return {**self.run(s["spec"], s["db"]), "spec_by": s["by"]}


def register(registry: Any, config: dict[str, Any], context: Any) -> None:
    home = Path(getattr(context, "home", "."))
    data = Path(getattr(context, "data_dir", ".taochronos"))

    def diseases() -> dict[str, Any]:
        if not registry.has("bridge"):
            return {}
        return {d["id"]: d for d in registry.get("bridge").diseases()}

    curated = config.get("curated", "corpus/modern/evidence.yaml")
    registry.register("modern", "pubmed", ModernEvidence(home / config.get("domain", "domains/modern"), curated=home / curated,
                                                         cache_dir=data / "modern" / "pubmed", online=bool(config.get("online", False)),
                                                         diseases=diseases), default=True)
    registry.register("rwd", "omop", RWDService(data), default=True)


__all__ = ["ModernEvidence", "RWDService", "register", "rwd"]
