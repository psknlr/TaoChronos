"""Versioned artifact store. Publishing goes through the BeforeArtifactPublish hook."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from ..protocol.artifacts import Artifact
from ..protocol.base import stable_id
from ..protocol.events import EventType
from .hooks import HookContext, HookPoint, HookRegistry

_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


class ArtifactBlocked(RuntimeError):
    pass


class ArtifactManager:
    def __init__(self, root: str | Path, hooks: HookRegistry | None = None) -> None:
        self.root = Path(root)
        self.hooks = hooks or HookRegistry()

    def _next_version(self, session: Any, kind: str, title: str) -> int:
        versions = [a.version for a in session.state.artifacts.values() if a.kind == kind and a.title == title]
        return max(versions, default=0) + 1

    def publish(
        self,
        session: Any,
        *,
        kind: str,
        title: str,
        content: str | bytes,
        filename: str,
        media_type: str,
        generator: str,
        evidence_refs: list[str] | None = None,
        hypothesis_refs: list[str] | None = None,
        parent_artifacts: list[str] | None = None,
        status: str = "published",
        tx: Any = None,
    ) -> Artifact:
        data = content.encode("utf-8") if isinstance(content, str) else content
        version = self._next_version(session, kind, title)
        rel = Path(session.id) / _SAFE.sub("_", kind) / f"v{version}" / _SAFE.sub("_", filename)
        artifact = Artifact(
            id=stable_id("art", session.id, kind, title, version),
            kind=kind,
            title=title,
            version=version,
            path=str(rel),
            media_type=media_type,
            sha256=hashlib.sha256(data).hexdigest(),
            generator=generator,
            parent_artifacts=list(parent_artifacts or []),
            evidence_refs=list(evidence_refs or []),
            hypothesis_refs=list(hypothesis_refs or []),
            status=status,
        )
        verdict = self.hooks.run(
            HookContext(HookPoint.BEFORE_ARTIFACT_PUBLISH, subject=artifact, session=session, data={"content": data})
        )
        if not verdict.allow:
            session.emit(
                EventType.HOOK_BLOCKED,
                {"hook": verdict.hook, "point": "BeforeArtifactPublish", "reason": verdict.reason, "artifact": artifact.id},
            )
            raise ArtifactBlocked(verdict.reason)
        if isinstance(verdict.subject, Artifact):
            artifact = verdict.subject
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        payload = {"artifact": artifact.to_dict()}
        if tx is not None:
            tx.emit(EventType.ARTIFACT_PUBLISHED, payload, generated=[artifact.id])
        else:
            session.emit(EventType.ARTIFACT_PUBLISHED, payload, actor=generator, generated=[artifact.id])
        return artifact

    def path_of(self, artifact: Artifact) -> Path:
        return self.root / artifact.path

    def read(self, artifact: Artifact) -> bytes:
        return self.path_of(artifact).read_bytes()
