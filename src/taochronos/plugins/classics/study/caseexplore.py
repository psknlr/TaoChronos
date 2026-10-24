"""医案探索 — the case records of every collection searched, matched, compared and read as one body of clinical record.

``cases.py`` reads each case collection once, visit by visit; these functions explore what it read, across physicians
and centuries:

=================  ==========================================================================================
casefind           医案检索: the cases that fit a query of many facets — disease, findings (symptom, pulse, tongue),
                   formula, drug, principle, outcome, the patient's sex and age, period or years, collections,
                   earlier physicians' treatment (误治), words of the text — with what matched, and the facets of the
                   matches (collections, periods, outcomes, formulas, principles, drugs, findings)
similar            类案: the cases whose presentation is most like a given one (a text, or a case), by the findings
                   they share weighted by rarity; what each did and how it ended, and what the like cases did together
case               医案详解: one case in full — its course visit by visit (with the prescription's changes as stated
                   and as computed from the drugs listed), the passages it rests on, its formulas, and its like cases
casecompare        医家与时代比较: groups of cases side by side — by collection, physician, period or author: visits,
                   outcomes, the patients they saw, the principles, formulas and drugs each favours against the rest,
                   tests across groups and, by period, trends
modifications      随证加减: at the visits that change the last prescription, which findings go with which drugs added
                   or taken away, and what is added to each base formula
treatments         同病异治 · 异病同治: for a disease, the different treatments its cases received and the findings that
                   set each group apart; for a formula, the diseases it treated in the cases and the findings they share
=================  ==========================================================================================

A case's presentation is a set of features: ``症:`` the lexicon's symptoms and signs, ``脉:`` each pulse quality, ``舌:`` /
``苔:`` the tongue body and coating, ``证:`` the diseases and patterns named; its treatment ``治法:``, ``方:``, ``药:``.
Every case keeps its passages.  The records were written by their physicians and selected by them and their editors:
they show what physicians reported doing, never evidence of efficacy, and never advice for a patient.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Callable, Iterable

from ....protocol.cases import CaseRecord, Visit
from ....science.stats import chi_square_independence, jensen_shannon, kruskal_wallis, mean_sd
from ....science.trajectories import cross_associations, group_contrasts, idf_weights, weighted_cosine
from .base import StudyBase, trend_test, wilson
from .cases import RESPONSES, CaseStudy
from .metrology import cn_number

TONGUE = set("白黄灰黑红绛紫淡胖瘦腻滑燥干剥光厚薄润糙裂焦")
OUTCOME_WORDS = {"improved": "improved", "愈": "improved", "痊愈": "improved", "好转": "improved", "效": "improved",
                 "unchanged": "unchanged", "未效": "unchanged", "无效": "unchanged", "不效": "unchanged",
                 "worse": "worse", "加重": "worse", "恶化": "worse", "died": "died", "死": "died", "死亡": "died",
                 "unrecorded": "", "未记": "", "none": ""}
PRIOR_ITEM = {"diagnosis": "prior_diagnosis", "principles": "prior_principle", "formulas": "prior_formula", "herbs": "prior_herb"}
SEX_WORDS = {"male": "male", "男": "male", "m": "male", "female": "female", "女": "female", "f": "female"}
NOTE = ("case records read by rules (cases.yaml): what physicians recorded and editors chose to keep — associations "
        "in a selected record, never evidence of efficacy, and never advice for a patient")


def presentation(v: Visit, qualities: set[str]) -> set[str]:
    """A visit's presentation as features: symptoms and signs, pulse qualities, tongue body and coating, diagnosis."""
    out = {f"症:{x}" for k in ("symptom", "sign") for x in v.findings.get(k, [])}
    out |= {f"脉:{ch}" for p in v.findings.get("pulse", []) for ch in p[1:] if ch in qualities}
    for t in v.findings.get("tongue", []):
        body, _, coat = t.partition("苔")
        out |= {f"舌:{ch}" for ch in body if ch in TONGUE} | {f"苔:{ch}" for ch in coat if ch in TONGUE}
    out |= {f"证:{x}" for x in v.diagnosis}
    return out


def treatment(v: Visit, name: Callable[[str], str] = str) -> set[str]:
    """A visit's treatment as features: principles, formulas (each under ``name``: the lexicon's, which merges a
    formula's other names), drugs (those listed and those added)."""
    return ({f"治法:{x}" for x in v.principles} | {f"方:{name(x)}" for x in v.formulas}
            | {f"药:{h['name']}" for h in v.herbs} | {f"药:{x}" for x in v.added})


def _ordinal(i: int) -> str:
    return f"第{i + 1}诊"


class CaseExplorer:
    def __init__(self, base: StudyBase, cases: CaseStudy) -> None:
        self.b = base
        self.cs = cases
        self._names: dict[str, str] = {}
        # every name a physician goes by (丹溪, 朱丹溪, 朱震亨 …) → the name physicians.yaml gives him
        self._persons = {base.normalize(n): p["name"] for p in base.data("physicians.yaml").get("persons") or []
                         for n in [p["name"], *(p.get("names") or [])]}

    def fname(self, name: str) -> str:
        """A formula under the lexicon's name (六味丸 → 六味地黄丸), else as the record writes it."""
        got = self._names.get(name)
        if got is None:
            entry = self.b.pack.lexicon.resolve(name, "formula")
            got = self._names[name] = entry.term if entry is not None else name
        return got

    def _treatment(self, c: CaseRecord) -> set[str]:
        return set().union(*(treatment(v, self.fname) for v in c.visits)) if c.visits else set()

    # ------------------------------------------------------------ shared
    def _pool(self, disease: str | None, books: list[str] | None) -> list[CaseRecord]:
        ids = self._books(books)
        if disease:
            return self.cs.cases(disease=disease, books=ids, limit=10 ** 6)
        return self.cs.pool(ids)

    def _books(self, books: Iterable[str] | None) -> list[str] | None:
        """Book ids from ids, titles or works (a title matches the case collections whose title holds it)."""
        if not books:
            return None
        known = self.cs.case_books()
        out: list[str] = []
        for b in books:
            if b in self.b.corpus.books:
                out.append(b)
                continue
            nb = self.b.normalize(b)
            found = [x for x in known if nb in self.b.normalize(self.b.book_title(x))
                     or nb == (self.b.corpus.books[x].work or "")]
            if not found:
                raise ValueError(f"{b!r}: no case collection of this corpus has this id, title or work")
            out += found
        return list(dict.fromkeys(out))

    def _physician(self, c: CaseRecord) -> str:
        """Who treated: the physician the record names (丹溪治一妇), else the collection's author — under the name
        physicians.yaml gives him, so that 丹溪 in a compilation and 朱震亨 the author are one physician."""
        if c.physician:
            return self.person(c.physician)
        book = self.b.corpus.books.get(c.book_id)
        return self.person(re.sub(r"[（(][^）)]*[）)]", "", book.authors[0]).strip()) if book and book.authors else "佚名"

    def person(self, name: str) -> str:
        """A physician under the name physicians.yaml gives him (叶天士 → 叶桂, 子和 → 张从正), else as written."""
        n = self.b.normalize(name)
        bare = re.sub(r"(?:撰|著|编|辑|述|纂|集|评|按|翁|先生|老人)+$", "", n)  # 丹溪翁 → 丹溪, 汪机撰 → 汪机
        return self._persons.get(n) or self._persons.get(bare) or name

    def _period(self, c: CaseRecord) -> str:
        per = self.b.period_of(c.year)
        return per.label if per else "未定"

    def _period_order(self) -> list[str]:
        return [p.label for p in self.b.periods] + ["未定"]

    def _forms(self, term: str, category: str) -> set[str]:
        """The normalised written forms of a lexicon entry (the term itself when the lexicon lacks it)."""
        _, forms = self.b.surfaces(term, category)
        out = {self.b.normalize(f) for f, _ in forms} | {self.b.normalize(term)}
        entry = self.b.pack.lexicon.resolve(self.b.normalize(term), category)
        if entry is not None:
            out.add(entry.term)
        return out

    def _presentation(self, c: CaseRecord, scope: str = "first") -> set[str]:
        visits = c.visits[:1] if scope == "first" else c.visits
        return set().union(*(presentation(v, self.cs.qualities) for v in visits)) if visits else set()

    def summary(self, c: CaseRecord, *, matched: dict[str, str] | None = None) -> dict[str, Any]:
        """A case as a list shows it: where it is, who, how many visits, what was given, how it ended."""
        first = c.visits[0] if c.visits else Visit(index=0)
        book = self.b.corpus.books.get(c.book_id)
        prior: dict[str, list[str]] = {}
        for v in c.visits:
            for kind, names in v.prior.items():
                prior[kind] = list(dict.fromkeys(prior.get(kind, []) + names))
        prior_response = next((v.prior_response for v in c.visits if v.prior_response), "")
        out = {
            "id": c.id, "book_id": c.book_id, "title": self.b.book_title(c.book_id),
            "authors": list(book.authors) if book else [], "physician": self._physician(c), "year": c.year,
            "period": self._period(c),
            "section": c.section, "patient": c.patient, "visits": len(c.visits), "outcome": c.outcome,
            "formulas": list(dict.fromkeys(f for v in c.visits for f in v.formulas))[:6],
            "principles": list(dict.fromkeys(p for v in c.visits for p in v.principles))[:4],
            "findings": {k: x[:6] for k, x in first.findings.items()},
            "prior": prior, "prior_response": prior_response,
            "quote": first.quote[:80], "passage_id": c.passage_ids[0] if c.passage_ids else None,
        }
        if matched:
            out["matched"] = matched
        return out

    def facets(self, cases: list[CaseRecord]) -> dict[str, Any]:
        """What a set of cases holds, counted once per case: collections, periods, outcomes, the patients' sex, formulas,
        principles, drugs, findings, pulse qualities, visits per case, accounts of earlier treatment."""
        def top(fn: Callable[[CaseRecord], Iterable[str]], n: int) -> list[list[Any]]:
            c: Counter = Counter()
            for case in cases:
                c.update(set(fn(case)))
            return [[k, v] for k, v in c.most_common(n)]

        books = Counter(c.book_id for c in cases)
        periods = Counter(self._period(c) for c in cases)
        crossed: dict[str, Counter] = defaultdict(Counter)
        for c in cases:
            crossed[self._period(c)][c.outcome or "unrecorded"] += 1
        return {
            "books": [{"book_id": b, "title": self.b.book_title(b), "cases": n} for b, n in books.most_common(15)],
            "periods": {p: periods[p] for p in self._period_order() if periods.get(p)},
            "period_outcomes": {p: dict(crossed[p]) for p in self._period_order() if p in crossed},
            "outcomes": dict(Counter(c.outcome or "unrecorded" for c in cases)),
            "sex": dict(Counter(c.patient.get("sex") or "unrecorded" for c in cases)),
            "formulas": top(lambda c: (self.fname(f) for v in c.visits for f in v.formulas), 15),
            "principles": top(lambda c: (p for v in c.visits for p in v.principles), 10),
            "herbs": top(lambda c: (h["name"] for v in c.visits for h in v.herbs), 15),
            "findings": top(lambda c: (x for v in c.visits for k in ("symptom", "sign") for x in v.findings.get(k, [])), 15),
            "pulse": top(lambda c: (f[3:] for f in self._presentation(c, "all") if f.startswith("脉:")), 10),
            "visits": dict(sorted(Counter(len(c.visits) for c in cases).items())),
            "prior": sum(1 for c in cases if any(v.prior_words for v in c.visits)),
        }

    # ------------------------------------------------------------ 医案检索
    def find(self, *, limit: int = 50, **query: Any) -> dict[str, Any]:
        """The cases that fit every facet given, oldest first, each with what matched; the facets of all the matches."""
        pool, matches, asked = self._match(**query)
        return {"query": asked, "count": len(matches), "scanned": len(pool),
                "cases": [self.summary(c, matched=why) for c, why in matches[:limit]],
                "facets": self.facets([c for c, _ in matches]),
                "note": "facets are counted once per case over every match; " + NOTE}

    def records(self, **query: Any) -> list[CaseRecord]:
        """Every case that fits the query (``find``'s facets), oldest first."""
        return [c for c, _ in self._match(**query)[1]]

    def _match(self, *, disease: str | None = None, findings: Iterable[str] = (), formula: str | None = None,
               herb: str | None = None, principle: str | None = None, outcome: str | None = None, sex: str | None = None,
               age_min: float | None = None, age_max: float | None = None, after: float | None = None,
               before: float | None = None, period: str | None = None, books: list[str] | None = None,
               physician: str | None = None, prior: bool | None = None, text: str | None = None
               ) -> tuple[list[CaseRecord], list[tuple[CaseRecord, dict[str, str]]], dict[str, Any]]:
        n = self.b.normalize
        pool = self._pool(disease, books)
        want_findings = [n(f) for t in findings for f in re.split(r"[、，,；;\s]+", t) if f]
        fforms = self._forms(formula, "formula") if formula else set()
        hforms = self._forms(herb, "herb") if herb else set()
        pword = n(principle) if principle else None
        out_want = OUTCOME_WORDS.get(outcome.strip().lower(), outcome) if outcome is not None else None
        sex_want = SEX_WORDS.get(sex.strip().lower(), sex) if sex else None
        per = None
        if period:
            per = next((p for p in self.b.periods if period in (p.id, p.label)), None)
            if per is None:
                raise ValueError(f"{period!r}: not a period of the analysis ({', '.join(p.label for p in self.b.periods)})")
        text_ids: set[str] | None = None
        if text:
            book_ids = sorted({c.book_id for c in pool})
            text_ids = set(self.b.find(n(text), book_ids=book_ids, limit=10 ** 6)) if book_ids else set()
        matches: list[tuple[CaseRecord, dict[str, str]]] = []
        for c in pool:
            why: dict[str, str] = {}
            if per is not None and not (c.year is not None and per.start <= c.year < per.end):
                continue
            if after is not None and (c.year is None or c.year < after):
                continue
            if before is not None and (c.year is None or c.year >= before):
                continue
            if out_want is not None and (c.outcome or "") != out_want:
                continue
            if sex_want and c.patient.get("sex") != sex_want:
                continue
            if age_min is not None or age_max is not None:
                age = cn_number(c.patient.get("age", "")) if c.patient.get("age") else None
                if age is None or (age_min is not None and age < age_min) or (age_max is not None and age > age_max):
                    continue
                why["age"] = c.patient["age"]
            if prior is not None and any(v.prior_words for v in c.visits) != prior:
                continue
            if physician:
                who = self._physician(c)
                if self.person(physician) != who and n(physician) not in n(who) and n(physician) not in n(c.physician):
                    continue
                why["physician"] = who
            if text_ids is not None:
                hit = [pid for pid in c.passage_ids if pid in text_ids]
                if not hit:
                    continue
                why["text"] = hit[0]
            ok = True
            for f in want_findings:
                at = self._finding_at(c, f)
                if at is None:
                    ok = False
                    break
                why[f"finding:{f}"] = at
            if not ok:
                continue
            if fforms:
                at = next((f"{x}（{_ordinal(v.index)}）" for v in c.visits for x in v.formulas if x in fforms), None)
                if at is None:
                    continue
                why["formula"] = at
            if hforms:
                at = next((f"{x}（{_ordinal(v.index)}）" for v in c.visits
                           for x in [h["name"] for h in v.herbs] + v.added if x in hforms), None)
                if at is None:
                    continue
                why["herb"] = at
            if pword:
                at = next((f"{x}（{_ordinal(v.index)}）" for v in c.visits for x in v.principles
                           if pword in x or (len(x) >= 2 and x in pword)), None)
                if at is None:
                    continue
                why["principle"] = at
            if prior:
                why["prior"] = next(v.prior_quote for v in c.visits if v.prior_words)
            matches.append((c, why))
        matches.sort(key=lambda m: (m[0].year if m[0].year is not None else 9999, m[0].book_id))
        asked = {k: v for k, v in (("disease", disease), ("findings", want_findings or None), ("formula", formula),
                                   ("herb", herb), ("principle", principle), ("outcome", outcome), ("sex", sex),
                                   ("age_min", age_min), ("age_max", age_max), ("after", after), ("before", before),
                                   ("period", period), ("books", books), ("physician", physician), ("prior", prior),
                                   ("text", text)) if v is not None}
        return pool, matches, asked

    # ------------------------------------------------------------ 研究数据集
    def dataset(self, cases: list[CaseRecord]) -> dict[str, list[dict[str, Any]]]:
        """Cases as three tables (``dataset.SCHEMAS``): one row per case, per visit, per item a visit records."""
        rows: dict[str, list[dict[str, Any]]] = {"cases": [], "case_visits": [], "case_items": []}
        for c in cases:
            book = self.b.corpus.books.get(c.book_id)
            age = c.patient.get("age")
            rows["cases"].append({
                "case_id": c.id, "book_id": c.book_id, "title": self.b.book_title(c.book_id),
                "authors": "、".join(book.authors) if book else "", "physician": self._physician(c), "year": c.year,
                "period": self._period(c),
                "section": c.section, "patient_name": c.patient.get("name", ""), "sex": c.patient.get("sex", ""),
                "age": age or "", "age_years": cn_number(age) if age else None, "visits": len(c.visits), "outcome": c.outcome,
                "prior": any(v.prior_words for v in c.visits), "passage_id": c.passage_ids[0] if c.passage_ids else "",
                "license": book.source.license if book else ""})
            for v in c.visits:
                rows["case_visits"].append({"case_id": c.id, "visit": v.index + 1, "marker": v.marker, "doses": v.doses,
                                            "response": v.response, "prior_response": v.prior_response,
                                            "passage_ids": "；".join(v.passage_ids), "quote": v.quote[:80]})
                items = [(k, x, "") for k, xs in v.findings.items() for x in xs]
                items += [("diagnosis", x, "") for x in v.diagnosis] + [("principle", x, "") for x in v.principles]
                items += [("formula", x, "") for x in v.formulas] + [("herb", h["name"], h.get("dose", "")) for h in v.herbs]
                items += [("added", x, "") for x in v.added] + [("removed", x, "") for x in v.removed]
                items += [(PRIOR_ITEM.get(k, f"prior_{k}"), x, "") for k, xs in v.prior.items() for x in xs]
                rows["case_items"] += [{"case_id": c.id, "visit": v.index + 1, "kind": k, "item": x, "dose": d}
                                       for k, x, d in items]
        return rows

    def _finding_at(self, c: CaseRecord, f: str) -> str | None:
        """Where a case records a finding (a symptom, a pulse such as 浮数 or 脉浮, a tongue such as 苔黄): the visit."""
        entry = self.b.pack.lexicon.resolve(f)
        canon = entry.term if entry is not None else None  # 咳嗽 → 咳, as the visit stores it
        bare = f[1:] if f[0] in "脉舌苔" and len(f) > 1 else f
        for v in c.visits:
            for kind, values in v.findings.items():
                for x in values:
                    if f in x or (canon and canon == x) or (kind in ("pulse", "tongue") and bare in x):
                        return f"{x}（{_ordinal(v.index)}）"
            if f in v.diagnosis or (canon and canon in v.diagnosis):
                return f"{f}（{_ordinal(v.index)}，证）"
        return None

    # ------------------------------------------------------------ 类案
    def similar(self, text: str | None = None, *, case_id: str | None = None, disease: str | None = None,
                books: list[str] | None = None, k: int = 10, scope: str = "first", min_shared: int = 2,
                neighbours: int = 30) -> dict[str, Any]:
        """The cases whose presentation is most like the query's (a text read as a first visit, or a case): the cosine
        of the features weighted by rarity, at least ``min_shared`` shared; what each did and how it ended, and what the
        ``neighbours`` nearest did together, with their outcomes."""
        query_case = None
        if case_id:
            query_case = self.cs.find_case(case_id)
            if query_case is None:
                raise ValueError(f"{case_id!r}: no case of the case collections has this id")
            query = self._presentation(query_case, scope)
            read = {"case": self.summary(query_case)}
        elif text:
            v = Visit(index=0)
            self.cs._read(v, self.b.normalize(text))
            query = presentation(v, self.cs.qualities)
            read = {"text": text, "findings": v.findings, "diagnosis": v.diagnosis}
        else:
            raise ValueError("give a presentation (text) or a case id")
        pool = [c for c in self._pool(disease, books) if query_case is None or c.id != query_case.id]
        sets = [self._presentation(c, scope) for c in pool]
        idf = idf_weights(sets)
        need = min(min_shared, len(query))
        scored = sorted(((weighted_cosine(query, s, idf), c, s) for c, s in zip(pool, sets) if query and len(query & s) >= need),
                        key=lambda x: (-x[0], x[1].year if x[1].year is not None else 9999, x[1].id))
        rarest = max(idf.values(), default=1.0)
        weight = lambda f: idf.get(f, rarest)  # noqa: E731
        results = []
        for score, c, s in scored[:k]:
            done = next((v for v in c.visits if v.formulas or v.principles or v.herbs), None)
            results.append(self.summary(c) | {
                "score": round(score, 3), "shared": sorted(query & s, key=lambda f: (-weight(f), f)),
                "only_here": sorted(s - query, key=lambda f: (-weight(f), f))[:6],
                "treated": {"visit": _ordinal(done.index), "principles": done.principles[:4], "formulas": done.formulas[:4],
                            "herbs": [h["name"] for h in done.herbs][:8]} if done else None})
        near = [c for score, c, _ in scored[:neighbours]]
        return {"query": read | {"features": sorted(query, key=lambda f: (-weight(f), f))}, "scope": scope,
                "candidates": len(pool), "matched": len(scored), "results": results,
                "practice": self._practice(near) if near else None,
                "note": f"like cases by shared findings weighted by rarity (cosine; at least {need} shared); "
                        f"practice: what the {len(near)} nearest did, counted once per case — " + NOTE}

    def _practice(self, cases: list[CaseRecord]) -> dict[str, Any]:
        """What a set of cases did, counted once per case, with the outcomes of the cases that did it."""
        def tally(fn: Callable[[CaseRecord], Iterable[str]], n: int) -> list[dict[str, Any]]:
            seen: dict[str, list[CaseRecord]] = defaultdict(list)
            for c in cases:
                for x in dict.fromkeys(fn(c)):
                    seen[x].append(c)
            rows = sorted(seen.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:n]
            return [{"name": x, "cases": len(cs), "outcomes": dict(Counter(c.outcome or "unrecorded" for c in cs)),
                     "periods": sorted({self._period(c) for c in cs}, key=self._period_order().index)} for x, cs in rows]

        return {"cases": len(cases), "formulas": tally(lambda c: (self.fname(f) for v in c.visits for f in v.formulas), 10),
                "principles": tally(lambda c: (p for v in c.visits for p in v.principles), 8),
                "herbs": tally(lambda c: (h["name"] for v in c.visits for h in v.herbs), 12),
                "outcomes": dict(Counter(c.outcome or "unrecorded" for c in cases))}

    # ------------------------------------------------------------ 医案详解
    def case(self, case_id: str, *, similar: int = 5, chars: int = 600) -> dict[str, Any]:
        """One case in full: its course visit by visit, the passages it rests on, its formulas and its like cases."""
        c = self.cs.find_case(case_id)
        if c is None:
            raise ValueError(f"{case_id!r}: no case of the case collections has this id")
        lex = self.b.pack.lexicon
        course = []
        before: list[str] | None = None
        for v in c.visits:
            names = [h["name"] for h in v.herbs]
            computed = {}
            if before and names:  # what the drugs listed say changed, beside what the record says (加…, 去…)
                computed = {"added": [x for x in names if x not in before], "removed": [x for x in before if x not in names]}
            course.append(v.to_dict() | {"label": _ordinal(v.index), "computed_changes": computed,
                                         "presentation": sorted(presentation(v, self.cs.qualities))})
            before = names or before
        formulas = []
        for name in dict.fromkeys(f for v in c.visits for f in v.formulas):
            entry = lex.resolve(name, "formula")
            formulas.append({"name": name, "lexicon": entry.term if entry else None})
        out = self.summary(c) | {"course": course, "formulas_named": formulas,
                                 "witnesses": [self.b.witness(p, quote=p.text[:chars]) for p in self.b.passages(c.passage_ids)]}
        if similar:
            out["similar"] = [{k: r[k] for k in ("id", "title", "period", "section", "outcome", "score", "shared", "formulas")}
                              for r in self.similar(case_id=case_id, k=similar)["results"]]
        out["note"] = ("computed changes compare the drugs listed at a visit with the last visit that listed drugs; the "
                       "record's own 加/去 are under added/removed — " + NOTE)
        return out

    # ------------------------------------------------------------ 医家与时代比较
    def compare(self, *, by: str = "book", disease: str | None = None, books: list[str] | None = None,
                groups: list[str] | None = None, min_cases: int = 5, max_groups: int = 30, top: int = 8) -> dict[str, Any]:
        """Groups of cases side by side — by collection (``book``), ``physician`` (the one the record names, as in a
        compilation's 丹溪治…, else the collection's author), ``period`` or ``author`` (of the collection).  The
        ``max_groups`` largest groups of at least ``min_cases`` cases are compared; the others are listed as left out."""
        if by not in ("book", "physician", "period", "author"):
            raise ValueError("by: book, physician, period or author")
        pool = self._pool(disease, books)

        def key(c: CaseRecord) -> str:
            if by == "period":
                return self._period(c)
            if by == "physician":
                return self._physician(c)
            book = self.b.corpus.books.get(c.book_id)
            if by == "author":
                return (book.authors[0] if book and book.authors else "佚名")
            return self.b.book_title(c.book_id)

        grouped: dict[str, list[CaseRecord]] = defaultdict(list)
        for c in pool:
            grouped[key(c)].append(c)
        if groups:
            wanted = {self.b.normalize(g) for g in groups}
            ids = {self.b.book_title(b) for b in (self._books(groups) or [])} if by == "book" else set()
            grouped = {g: cs for g, cs in grouped.items() if self.b.normalize(g) in wanted or g in ids}
        large = sorted((g for g, cs in grouped.items() if len(cs) >= min_cases), key=lambda g: (-len(grouped[g]), g))
        kept = {g: grouped[g] for g in large[:max_groups]}
        if by == "period":
            order = [g for g in self._period_order() if g in kept]
        else:
            order = sorted(kept, key=lambda g: (min((c.year for c in kept[g] if c.year is not None), default=9999), g))
        profiles = [self._profile(g, kept[g], top) for g in order]
        treat = group_contrasts({g: [self._treatment(c) for c in kept[g]] for g in order},
                                min_cases=max(3, min_cases // 2), top=top)
        patients = group_contrasts({g: [self._presentation(c) for c in kept[g]] for g in order},
                                   min_cases=max(3, min_cases // 2), top=top)
        for p in profiles:
            p["distinctive"] = treat.get(p["group"], [])
            p["patients"] = patients.get(p["group"], [])
        table = [[sum(1 for c in kept[g] if c.outcome == o) for o in RESPONSES] for g in order]
        tests = {"outcome": chi_square_independence(table) if len(order) >= 2 else None,
                 "visits": kruskal_wallis([[len(c.visits) for c in kept[g]] for g in order]) if len(order) >= 2 else None}
        out: dict[str, Any] = {"by": by, "disease": disease, "cases": sum(len(kept[g]) for g in order), "scanned": len(pool),
                               "groups": profiles, "left_out": {g: len(cs) for g, cs in grouped.items() if g not in kept},
                               "tests": tests}
        if 2 <= len(order) <= 8:
            dists = {g: Counter(x for c in kept[g] for x in self._treatment(c) if not x.startswith("药:")) for g in order}
            out["distances"] = [{"a": a, "b": b, "jsd": round(jensen_shannon(dict(dists[a]), dict(dists[b])), 4)}
                                for i, a in enumerate(order) for b in order[i + 1:]]
        if by == "period" and len(order) >= 3:
            out["trends"] = self._trends(kept, order, top=12)
        out["note"] = ("groups with fewer than {} cases, and those past the {} largest, are left out; distinctive: items "
                       "over-represented in a group's cases "
                       "against the other groups' (one-sided Fisher, Benjamini–Hochberg); recovery rate among the cases "
                       "whose outcome is recorded (Wilson interval); outcome χ² over the four recorded outcomes; ".format(min_cases, max_groups)
                       + NOTE)
        return out

    def _profile(self, group: str, cases: list[CaseRecord], top: int) -> dict[str, Any]:
        n = len(cases)
        visits = [len(c.visits) for c in cases]
        mean, sd = mean_sd(visits) if n > 1 else (float(visits[0]), 0.0)
        outcomes = Counter(c.outcome or "unrecorded" for c in cases)
        recorded = n - outcomes.get("unrecorded", 0)
        lo, hi = wilson(outcomes.get("improved", 0), recorded)
        sexes = Counter(c.patient.get("sex") for c in cases if c.patient.get("sex"))

        def share(fn: Callable[[CaseRecord], Iterable[str]]) -> list[dict[str, Any]]:
            cnt: Counter = Counter()
            for c in cases:
                cnt.update(set(fn(c)))
            return [{"name": k, "cases": v, "share": round(v / n, 3)} for k, v in cnt.most_common(top)]

        years = [c.year for c in cases if c.year is not None]
        books = Counter(c.book_id for c in cases)
        return {
            "group": group, "cases": n, "years": [min(years), max(years)] if years else None,
            "books": [{"book_id": b, "title": self.b.book_title(b), "cases": k} for b, k in books.most_common(5)],
            "visits": {"mean": round(mean, 2), "sd": round(sd, 2), "max": max(visits)},
            "outcomes": dict(outcomes), "recorded": recorded,
            "improved_rate": round(outcomes.get("improved", 0) / recorded, 3) if recorded else None,
            "improved_ci": [round(lo, 3), round(hi, 3)] if recorded else None,
            "died_rate": round(outcomes.get("died", 0) / recorded, 3) if recorded else None,
            "female_share": round(sexes.get("female", 0) / sum(sexes.values()), 3) if sexes else None,
            "sex_recorded": sum(sexes.values()),
            "prior_share": round(sum(1 for c in cases if any(v.prior_words for v in c.visits)) / n, 3),
            "principles": share(lambda c: (p for v in c.visits for p in v.principles)),
            "formulas": share(lambda c: (self.fname(f) for v in c.visits for f in v.formulas)),
            "herbs": share(lambda c: (h["name"] for v in c.visits for h in v.herbs)),
        }

    def _trends(self, kept: dict[str, list[CaseRecord]], order: list[str], *, top: int) -> list[dict[str, Any]]:
        """The most used principles and formulas: their share of each period's cases, and a Cochran–Armitage trend test."""
        per: dict[str, list[set[str]]] = {g: [self._treatment(c) for c in kept[g]] for g in order}
        overall: Counter = Counter(x for g in order for s in per[g] for x in s if not x.startswith("药:"))
        rows = []
        for item, _ in overall.most_common(top):
            counts = [(sum(1 for s in per[g] if item in s), len(per[g])) for g in order]
            test = trend_test(counts)
            rows.append({"item": item, "shares": {g: round(k / n, 3) for g, (k, n) in zip(order, counts)},
                         "counts": {g: k for g, (k, _) in zip(order, counts)},
                         "trend_z": test[0] if test else None, "p": test[1] if test else None})
        return rows

    # ------------------------------------------------------------ 随证加减
    def modifications(self, *, disease: str | None = None, formula: str | None = None, books: list[str] | None = None,
                      findings: str = "visit", min_count: int = 3, top: int = 30) -> dict[str, Any]:
        """At the visits that change the last prescription (加…, 去…): the findings that go with each drug added or taken
        away, the drugs most often added and taken away, and what is added to each base formula.  ``findings``:
        ``visit`` — every finding of the visit; ``new`` — those its last visit did not record."""
        pool = self._pool(disease, books)
        fforms = self._forms(formula, "formula") if formula else set()
        add_units: list[tuple[set[str], set[str]]] = []
        remove_units: list[tuple[set[str], set[str]]] = []
        bases: dict[str, dict[str, Any]] = defaultdict(lambda: {"visits": 0, "added": Counter(), "removed": Counter()})
        examples: list[dict[str, Any]] = []
        cases_with = 0
        for c in pool:
            last_formula: str | None = None
            last_pres: set[str] = set()
            changed = False
            for v in c.visits:
                pres = presentation(v, self.cs.qualities)
                base = self.fname(v.formulas[0]) if v.formulas else last_formula
                if (v.added or v.removed) and (not fforms or (base and (base in fforms or self.fname(base) in fforms))):
                    changed = True
                    feats = pres - last_pres if findings == "new" else pres
                    feats = {f for f in feats if not f.startswith("证:")}
                    add_units.append((feats, set(v.added)))
                    remove_units.append((feats, set(v.removed)))
                    if base:
                        bases[base]["visits"] += 1
                        bases[base]["added"].update(set(v.added))
                        bases[base]["removed"].update(set(v.removed))
                    if len(examples) < 8:
                        examples.append({"case": c.id, "title": self.b.book_title(c.book_id), "period": self._period(c),
                                         "visit": _ordinal(v.index), "base": base, "added": v.added, "removed": v.removed,
                                         "findings": sorted(feats)[:8], "quote": v.quote[:80],
                                         "passage_id": v.passage_ids[0] if v.passage_ids else None})
                if v.formulas:
                    last_formula = self.fname(v.formulas[0])
                last_pres = pres or last_pres
            cases_with += changed
        added: Counter = Counter(x for _, a in add_units for x in a)
        removed: Counter = Counter(x for _, r in remove_units for x in r)
        base_rows = [{"formula": f, "visits": b["visits"], "added": b["added"].most_common(8), "removed": b["removed"].most_common(8)}
                     for f, b in sorted(bases.items(), key=lambda kv: (-kv[1]["visits"], kv[0]))[:15]]
        return {"disease": disease, "formula": formula, "findings": findings, "scanned": len(pool), "cases": cases_with,
                "visits": len(add_units), "added": added.most_common(top), "removed": removed.most_common(top),
                "bases": base_rows,
                "finding_added": cross_associations(add_units, min_count=min_count, top=top),
                "finding_removed": cross_associations(remove_units, min_count=min_count, top=top),
                "examples": examples,
                "note": "units: the visits that add to or take from the last prescription; base: the visit's own formula, "
                        "else the last one named; finding → drug: count, P(drug | finding) among those visits, lift, "
                        "one-sided Fisher, Benjamini–Hochberg — " + NOTE}

    # ------------------------------------------------------------ 同病异治 · 异病同治
    def treatments(self, target: str, *, mode: str | None = None, by: str = "formula", books: list[str] | None = None,
                   min_cases: int = 3, top: int = 8) -> dict[str, Any]:
        """``disease`` (同病异治): the treatments a disease's cases received at their first treated visit — grouped ``by``
        formula (else principle) or by principle (else formula) — and the findings that set each group apart;
        ``formula`` (异病同治): the diseases a formula's cases were filed under or named, the findings they share, and
        those that set each apart.  The mode follows the lexicon when not given."""
        entry = self.b.pack.lexicon.resolve(self.b.normalize(target))
        if mode is None:
            mode = "formula" if (entry is not None and entry.category == "formula") or target[-1] in "汤散丸饮丹膏" else "disease"
        if mode not in ("disease", "formula"):
            raise ValueError("mode: disease (同病异治) or formula (异病同治)")
        if by not in ("formula", "principle"):
            raise ValueError("by: formula or principle")
        if mode == "disease":
            pool = self._pool(target, books)
            grouped: dict[str, list[CaseRecord]] = defaultdict(list)
            for c in pool:
                done = next((v for v in c.visits if v.formulas or v.principles), None)
                if done is None:
                    continue
                formula = f"方:{self.fname(done.formulas[0])}" if done.formulas else None
                principle = f"治法:{done.principles[0]}" if done.principles else None
                grouped[(formula or principle) if by == "formula" else (principle or formula)].append(c)
            label = "同病异治"
        else:
            fforms = self._forms(target, "formula")
            pool = self._pool(None, books)
            grouped = defaultdict(list)
            for c in pool:
                v = next((v for v in c.visits if set(v.formulas) & fforms), None)
                if v is None:
                    continue
                named = v.diagnosis or next((x.diagnosis for x in c.visits if x.diagnosis), [])
                head = re.sub(r"[（(][^）)]*[）)]|[门类篇论治案]+$", "", c.section).strip()
                grouped[f"证:{named[0]}" if named else (f"门:{head}" if head else "未名")].append(c)
            label = "异病同治"
        kept = {g: cs for g, cs in grouped.items() if len(cs) >= min_cases and g != "未名"}
        order = sorted(kept, key=lambda g: (-len(kept[g]), g))
        pres = {g: [self._presentation(c, "all" if mode == "formula" else "first") for c in kept[g]] for g in order}
        contrasts = group_contrasts(pres, min_cases=max(2, min_cases - 1), top=top) if len(order) >= 2 else {}
        rows = []
        for g in order:
            cs = kept[g]
            outcomes = Counter(c.outcome or "unrecorded" for c in cs)
            recorded = len(cs) - outcomes.get("unrecorded", 0)
            years = [c.year for c in cs if c.year is not None]
            rows.append({"group": g, "cases": len(cs), "outcomes": dict(outcomes), "recorded": recorded,
                         "improved_rate": round(outcomes.get("improved", 0) / recorded, 3) if recorded else None,
                         "years": [min(years), max(years)] if years else None,
                         "periods": dict(Counter(self._period(c) for c in cs)),
                         "books": [self.b.book_title(b) for b, _ in Counter(c.book_id for c in cs).most_common(3)],
                         "findings": contrasts.get(g, []),
                         "examples": [self.summary(c) for c in cs[:2]]})
        table = [[sum(1 for c in kept[g] if c.outcome == o) for o in RESPONSES] for g in order]
        out: dict[str, Any] = {"target": target, "mode": mode, "by": by if mode == "disease" else None, "label": label,
                               "scanned": len(pool),
                               "cases": sum(len(grouped[g]) for g in grouped), "groups": rows,
                               "left_out": sum(len(cs) for g, cs in grouped.items() if g not in kept),
                               "outcome_test": chi_square_independence(table) if len(order) >= 2 else None}
        if mode == "formula":
            out["shared"] = self._shared(kept, pool, top=12)
        out["note"] = ((f"同病异治: each case grouped by the first {by} (else {'principle' if by == 'formula' else 'formula'}) "
                        "of its first treated visit; "
                        if mode == "disease" else
                        "异病同治: each case using the formula grouped by the disease its visit names, else its heading; "
                        "shared: findings common across the groups, with their lift over every case; ")
                       + "findings: features over-represented in a group against the other groups (one-sided Fisher, "
                         "Benjamini–Hochberg) — " + NOTE)
        return out

    def _shared(self, kept: dict[str, list[CaseRecord]], pool: list[CaseRecord], *, top: int) -> list[dict[str, Any]]:
        """The findings a formula's cases share across their diseases: share among them, among every case, the lift and
        the number of disease groups where at least a fifth of the cases record it."""
        mine = [c for cs in kept.values() for c in cs]
        if not mine:
            return []
        seen = {c.id: {f for f in self._presentation(c, "all") if not f.startswith("证:")} for c in pool}
        base: Counter = Counter(f for c in pool for f in seen[c.id])
        have: Counter = Counter(f for c in mine for f in seen[c.id])
        rows = []
        for f, k in have.items():
            if k < 2:
                continue
            groups = sum(1 for cs in kept.values() if sum(1 for c in cs if f in seen[c.id]) >= max(1, len(cs) / 5))
            share, everywhere = k / len(mine), base[f] / len(pool)
            rows.append({"feature": f, "cases": k, "share": round(share, 3), "share_all": round(everywhere, 3),
                         "lift": round(share / everywhere, 3) if everywhere else None, "groups": groups})
        rows.sort(key=lambda r: (-r["groups"], -(r["lift"] or 0) * r["share"], r["feature"]))
        return rows[:top]


__all__ = ["CaseExplorer", "presentation", "treatment"]
