"""The ``audit`` capability (S15): a claim audited against the witnesses, the bridge and modern evidence; and the
evidence graph of a mapping or an audit.

The checks live in ``verification/audit.py`` and read nothing but the callables given here: the corpus (a work by its
title, a quote in a work), the bridge (a description's resemblances), modern evidence (typed records, when that
capability is present) and the presentism guard.
"""

from __future__ import annotations

import re
from typing import Any

from ...verification.audit import AuditContext, audit
from ...verification.evidence_graph import EvidenceGraph, add_audit, add_modern, from_bridge
from ...verification.presentism import guard_from_pack
from .reuse import strip_punct

GLOSSATORS = ["成无己", "王冰", "杨上善", "张志聪", "张隐庵", "高世栻", "柯琴", "尤怡", "尤在泾", "徐大椿", "徐灵胎", "吴谦", "喻昌",
              "方有执", "程应旄", "黄元御", "陈修园", "唐容川", "丹波元简", "丹波元坚", "林亿", "马莳", "吴崑", "张介宾", "李时珍"]


class AuditService:
    def __init__(self, study: Any, registry: Any) -> None:
        self.study = study
        self.registry = registry
        self.guard = guard_from_pack(study.pack)
        self._titles: dict[str, str] | None = None

    def _bridge(self) -> Any:
        return self.registry.get("bridge") if self.registry.has("bridge") else None

    def _modern(self) -> Any:
        return self.registry.get("modern") if self.registry.has("modern") else None

    def work_of(self, title: str) -> str | None:
        if self._titles is None:
            self._titles = {}
            for b in self.study.corpus.books.values():
                for name in [b.title, *getattr(b, "aliases", [])]:
                    self._titles.setdefault(self.study.normalize(name), b.id)
        key = self.study.normalize(title)
        if key in self._titles:
            return self._titles[key]
        hits = sorted({bid for name, bid in self._titles.items() if key in name or name in key})
        return hits[0] if hits else None

    def work_ids(self, title: str) -> list[str]:
        """All editions and books of a work (the same title in several editions, a work's other books)."""
        bid = self.work_of(title)
        if bid is None:
            return []
        book = self.study.corpus.books.get(bid)
        work = getattr(book, "work", None) if book else None
        if not work:
            return [bid]
        return sorted(b.id for b in self.study.corpus.books.values() if getattr(b, "work", None) == work) or [bid]

    def locate(self, quote: str, book_id: str | None) -> list[str]:
        """The passages that carry ``quote`` verbatim, marks and variant forms aside (in the work of ``book_id``, or
        anywhere): the longest unpunctuated stretch finds candidates, the whole quote confirms them."""
        norm = self.study.normalize(quote)
        needle = strip_punct(norm)[0]
        if len(needle) < 2:
            return []
        pieces = sorted((p for p in re.split(r"[^\w㐀-鿿]+", norm) if len(p) >= 2), key=len, reverse=True)
        if not pieces:
            return []
        books = None
        if book_id:
            book = self.study.corpus.books.get(book_id)
            work = getattr(book, "work", None) if book else None
            books = sorted(b.id for b in self.study.corpus.books.values() if work and getattr(b, "work", None) == work) or [book_id]
        found = []
        for p in self.study.passages(self.study.find(pieces[0], book_ids=books, limit=60)):
            if needle in strip_punct(self.study.normalize(p.text))[0]:
                found.append(p.id)
            if len(found) >= 5:
                break
        return found

    def locate_by(self, quote: str, author: str) -> list[str]:
        """Passages of the works of ``author`` (a commentator) that carry ``quote``."""
        books = sorted(b.id for b in self.study.corpus.books.values()
                       if any(author in a for a in getattr(b, "authors", [])) or any(author in r.get("name", "") for r in getattr(b, "responsibility", []) or []))
        if not books:
            return []
        needle = strip_punct(self.study.normalize(quote))[0]
        out = []
        for p in self.study.passages(self.study.find(needle[:8], book_ids=books, limit=40)):
            if needle in strip_punct(self.study.normalize(p.text))[0]:
                out.append(p.id)
        return out[:5]

    def context(self, *, modern: bool = True) -> AuditContext:
        bridge = self._bridge()
        mod = self._modern() if modern else None
        terms = list(getattr(self.study.pack.terminology, "terms", {}))
        if bridge is not None:
            terms += [h["term"] for h in bridge.data.homonyms]
        modern_terms = []
        if bridge is not None:
            modern_terms = [d.label.split("（")[0] for d in bridge.data.diseases.values()] + ["糖尿病", "2型糖尿病", "高血压", "冠心病", "肿瘤", "癌"]
        return AuditContext(
            normalize=self.study.normalize, work_of=self.work_of, locate=self.locate, guard=self.guard,
            bridge=(lambda text: bridge.map(text)) if bridge is not None else None,
            modern=(lambda text: mod.for_claim(text)) if mod is not None else None,
            modern_terms=modern_terms, ancient_terms=sorted(set(terms)),
            safety=getattr(self._modern(), "safety_table", {}) if self._modern() is not None else {},  # local: always read
            glossators=GLOSSATORS, locate_by=self.locate_by)

    def audit(self, text: str, *, modern: bool = True, audit_id: str = "a1") -> dict[str, Any]:
        with self.study.rules_only():  # the bridge runs on rules inside an audit; the critic below is the model's turn
            result = audit(text, self.context(modern=modern), audit_id=audit_id)
        judge = self.study.judge
        if judge is not None:
            from ...verification.audit import _review, overall
            from ...protocol.assertions import AuditVerdict

            result["review"] = _review(result["claims"], judge)
            result["verdict"] = overall([AuditVerdict(c["verdict"]) for c in result["claims"]]).value
            result["counts"] = {v.value: sum(1 for c in result["claims"] if c["verdict"] == v.value) for v in AuditVerdict}
        return result

    # ------------------------------------------------------------ graphs
    def graph(self, *, passage_id: str | None = None, text: str | None = None, claim: str | None = None,
              modern: str | None = None) -> EvidenceGraph:
        g = EvidenceGraph()
        bridge = self._bridge()
        if bridge is not None and (passage_id or text):
            with self.study.rules_only():
                from_bridge(bridge.map(text, passage_id=passage_id), g)
        if claim:
            add_audit(g, self.audit(claim))
        if modern:
            mod = self._modern()
            if mod is not None:
                r = mod.search(modern)
                add_modern(g, f"subject:{modern}", modern, r["records"], subject_type="drug")
        return g


__all__ = ["AuditService", "GLOSSATORS"]
