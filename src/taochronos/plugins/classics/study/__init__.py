"""治学 — study functions over the classics for research and learning (see docs/study.md).

Each function answers a question scholars and students of Chinese medicine ask of the literature, and returns plain
data made of *witnesses* — verbatim quotes with book, date, locator and licence (``StudyBase.witness``):

=================  ==========================================================================================
concordance        经文互见·集注: where a passage recurs (other copies, quotations, restatements), with a 校勘记
variants / stemma  版本谱系: multi-witness collation of a work (or of a passage's copies and quotations), variant units,
edition            distances, a neighbour-joining stemma, shared-reading groups, contamination; one edition's profile
reuse              语义复用: a passage's reuses across the corpus, typed (直接引用 … 转述, 解释性改写, 引而驳之, 套语相似)
transmission       思想传播: a work's reception — which later works carry it and how, by period, and through which works
layers / dating    文本地层: style layers of a work's chapters, change points, outlying chapters; dating evidence per chapter
authorship         (cited works, late vocabulary, taboo); Burrows' Delta against candidate authors
cases              医案轨迹: case records read visit by visit (findings, diagnosis, principle, formula, 加减, doses,
trajectories       response, outcome); the sequences, transitions and outcome associations common to many cases
argument           医理论证: a passage's reasoning as a graph of marked steps; a work's way of reasoning, compared
senses             语义演变: a term's senses by period, the date its meaning shifted, candidate senses the curation lacks
fragments          佚书辑佚: a lost work's fragments gathered from the books that quote it, merged and ordered by volume
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

from collections import Counter
from typing import Any

from ..domain import DomainPack
from .argument import ArgumentStudy
from .base import StudyBase
from .cases import CaseStudy
from .concordance import Concordance
from .dataset import tables as dataset_tables
from .formulas import FormulaStudy
from .fragments import FragmentStudy
from .herbs import HerbStudy
from .senses import SenseStudy
from .intertext import IntertextStudy
from .learning import Learning, anki_tsv
from .network import CitationNetwork
from .stemma import StemmaStudy
from .stratigraphy import StratigraphyStudy
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
        self._stemma = StemmaStudy(self)
        self._intertext = IntertextStudy(self, self._concordance, self._stemma)
        self._strata = StratigraphyStudy(self, self._stemma, self._taboo)
        self._cases = CaseStudy(self)
        self._argument = ArgumentStudy(self, self._stemma)
        self._senses = SenseStudy(self)
        self._fragments = FragmentStudy(self)

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

    # ------------------------------------------------------------ computational philology
    def variants(self, work: str | None = None, *, text: str | None = None, passage_id: str | None = None,
                 **kw: Any) -> dict[str, Any]:
        """The apparatus of a work's witnesses — or, with ``text`` / ``passage_id``, of a passage's copies and
        quotations across the corpus."""
        if text or passage_id:
            return self._stemma.passage(text, passage_id, concordance=self._concordance,
                                        **{k: v for k, v in kw.items() if k in ("min_coverage", "max_witnesses")})
        return self._stemma.variants(work, **kw)

    def stemma(self, work: str | None = None, **kw: Any) -> dict[str, Any]:
        out = self._stemma.stemma(work, **kw)
        self._edition_floors(out)
        return out

    def edition(self, book: str, **kw: Any) -> dict[str, Any]:
        return self._stemma.edition(book, **kw)

    def tei(self, work: str | None = None, **kw: Any) -> str:
        return self._stemma.tei(work, **kw)

    def reuse(self, text: str | None = None, passage_id: str | None = None, **kw: Any) -> dict[str, Any]:
        """Typed reuses of a passage across the corpus (semantic reuse, two stages: candidates, then rules)."""
        return self._intertext.reuse(text, passage_id, **kw)

    def reuse_pair(self, source: str | None = None, target: str | None = None, *, source_id: str | None = None,
                   target_id: str | None = None) -> dict[str, Any]:
        """The reuse type of one passage in another, with its features and the rule that fired."""
        return self._intertext.compare(source or "", target or "", source_id=source_id, target_id=target_id)

    def transmission(self, work: str, **kw: Any) -> dict[str, Any]:
        """A work's reception: typed reuse of its clauses in later works, by period, with the channels."""
        return self._intertext.transmission(work, cache_dir=self.cache_dir(), **kw)

    def layers(self, work: str | None = None, **kw: Any) -> dict[str, Any]:
        """Style layers of a work's chapters, change points and outlying chapters."""
        return self._strata.layers(work, **kw)

    def dating(self, work: str | None = None, **kw: Any) -> dict[str, Any]:
        """Dating evidence chapter by chapter: cited works, late vocabulary, taboo characters of the witness."""
        return self._strata.dating(work, **kw)

    def authorship(self, text: str | None = None, **kw: Any) -> dict[str, Any]:
        """Burrows' Delta of a text (or a book, or one of its chapters) against candidate works."""
        return self._strata.authorship(text, **kw)

    def cases(self, book: str | None = None, *, disease: str | None = None, books: list[str] | None = None,
              limit: int = 200) -> dict[str, Any]:
        """Case records read visit by visit — of one book, or filed under a disease across the case collections."""
        records = self._cases.cases(book, disease=disease, books=books, limit=limit)
        return {"book": book, "disease": disease, "count": len(records), "cases": [r.to_dict() for r in records],
                "outcomes": dict(Counter(r.outcome or "unrecorded" for r in records))}

    def trajectories(self, disease: str | None = None, **kw: Any) -> dict[str, Any]:
        """Sequences, transitions and outcome associations of treatment across case records."""
        return self._cases.trajectories(disease, **kw)

    def argument(self, text: str | None = None, passage_id: str | None = None, *, work: str | None = None,
                 against: str | None = None, **kw: Any) -> dict[str, Any]:
        """A passage's argument graph; a work's way of reasoning (``work``); two works compared (``work``, ``against``)."""
        if work and against:
            return self._argument.compare(work, against, **kw)
        if work:
            out = self._argument.profile(work, **kw)
            out.pop("_counts", None)
            return out
        return self._argument.graph(text, passage_id)

    def senses(self, term: str, **kw: Any) -> dict[str, Any]:
        """A term's senses by period, the change point of their shares, candidate senses and the neighbourhood."""
        return self._senses.run(term, **kw)

    def fragments(self, work: str, *, exclude_books: list[str] | None = None, verify_against: list[str] | None = None,
                  **kw: Any) -> dict[str, Any]:
        """A lost work's fragments from the books that quote it; with ``verify_against`` (a surviving text's book
        ids), how much of the reconstruction is in it and how much of it is recovered."""
        if verify_against == ["*"]:  # the surviving work itself: all its witnesses
            verify_against = [b for ids in self._stemma.witness_sets(work) for b in ids]
        out = self._fragments.run(work, exclude_books=(exclude_books or []) + (verify_against or []), **kw)
        if verify_against:
            out["verification"] = self._fragments.verify(out, verify_against)
        for f in out["fragments"]:
            f.pop("_han", None)
        return out

    def _edition_floors(self, out: dict[str, Any]) -> None:
        """Each witness's lower date bound from its taboo characters (a witness in volumes: the latest)."""
        for w in out.get("witnesses", []):
            floors = [self._taboo.profile(bid).get("edition_floor") for bid in (w.get("book_id") or "").split("+")
                      if bid in self.corpus.books]
            floors = [f for f in floors if f is not None]
            w["edition_floor"] = max(floors) if floors else None

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
