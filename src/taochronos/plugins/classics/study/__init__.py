"""治学 — study functions over the classics for research and learning (see docs/study.md).

Each function answers a question scholars and students of Chinese medicine ask of the literature, and returns plain
data made of *witnesses* — verbatim quotes with book, date, locator and licence (``StudyBase.witness``):

=================  ==========================================================================================
concordance        经文互见·集注: where a passage recurs (other copies, quotations, restatements), with a 校勘记
formula            方源考: every written-out composition of a formula; original and current versions, 加减,
                   同名异方, 同方异名, dose ratios, doses in the measures of their time, 方歌
herb               药性源流: 性味, 毒性, 归经, 升降浮沉, 主治 of a drug, book by book; the first statement of each
term               术语源流: relative frequency by period with intervals and a trend test, first attestations,
                   collocates by period, where to read, senses and candidate modern concepts
taboo              避讳断代: taboo characters a witness avoids, and the edition date they imply
citations          引书与引人: which books and physicians each period cites; the reception of one of them
cards / reading    学习卡片 (Anki) and 阅读门径 for a topic
dataset            研究数据集: the results as tables with provenance, for a Frictionless data package
=================  ==========================================================================================
"""

from __future__ import annotations

from typing import Any

from ..domain import DomainPack
from .base import StudyBase
from .concordance import Concordance
from .dataset import tables as dataset_tables
from .formulas import FormulaStudy
from .herbs import HerbStudy
from .learning import Learning, anki_tsv
from .network import CitationNetwork
from .taboo import TabooStudy
from .terms import TermStudy


class StudyService(StudyBase):
    """The ``study`` capability."""

    def __init__(self, pack: DomainPack, corpus: Any) -> None:
        super().__init__(pack, corpus)
        self._concordance = Concordance(self)
        self._formulas = FormulaStudy(self)
        self._herbs = HerbStudy(self)
        self._taboo = TabooStudy(self)
        self._terms = TermStudy(self)
        self._network = CitationNetwork(self)
        self._learning = Learning(self, self._formulas, self._herbs, self._terms, self._network)

    @property
    def metrology(self) -> Any:
        return self._formulas.metrology

    def cache_dir(self) -> str | None:
        store = getattr(self.corpus, "store", None)
        return str(store.path.parent / "study-cache") if store is not None else None

    # ------------------------------------------------------------ functions
    def concordance(self, text: str | None = None, passage_id: str | None = None, **kw: Any) -> dict[str, Any]:
        return self._concordance.run(text, passage_id, **kw)

    def formula(self, name: str, **kw: Any) -> dict[str, Any]:
        return self._formulas.run(name, **kw)

    def herb(self, name: str, **kw: Any) -> dict[str, Any]:
        return self._herbs.run(name, **kw)

    def term(self, term: str, **kw: Any) -> dict[str, Any]:
        return self._terms.run(term, **kw)

    def taboo(self, book_id: str | None = None, **kw: Any) -> dict[str, Any]:
        return self._taboo.profile(book_id) if book_id else self._taboo.survey(**kw)

    def citations(self, target: str | None = None, **kw: Any) -> dict[str, Any]:
        if target:
            return self._network.reception(target, self.cache_dir())
        out = self._network.summary(self.cache_dir(), **kw)
        out["lineage"] = self._network.lineage(self.cache_dir())
        return out

    def cards(self, *, book: str | None = None, formulas: list[str] = (), herbs: list[str] = (), term: str | None = None,
              limit: int = 60) -> dict[str, Any]:
        cards: list[dict[str, Any]] = []
        if book:
            cards += self._learning.clause_cards(book, limit=limit)
        cards += self._learning.formula_cards(list(formulas))
        cards += self._learning.herb_cards(list(herbs))
        if term:
            cards += self._learning.term_cards(term)
        return {"cards": cards, "anki_tsv": anki_tsv(cards), "count": len(cards)}

    def reading(self, topic: str) -> dict[str, Any]:
        return self._learning.reading_path(topic)

    def dataset(self, *, formulas: list[str] = (), herbs: list[str] = (), terms: list[str] = (),
                citations: bool = False) -> dict[str, Any]:
        fres = [self.formula(f, other_names=False) for f in formulas]
        hres = [self.herb(h) for h in herbs]
        tres = [self.term(t, sample_per_period=50) for t in terms]
        cres = self.citations() if citations else None
        rows = dataset_tables(fres, hres, tres, cres, self.metrology)
        licences = sorted({r.get("license", "") for table in rows.values() for r in table if r.get("license")})
        return {"tables": rows, "licenses": licences, "signature": self.signature(), "notice": self.metrology.notice}


__all__ = ["StudyService"]
