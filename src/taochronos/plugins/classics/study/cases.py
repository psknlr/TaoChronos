"""医案轨迹 — case records read as courses of treatment, and the trajectories common to many of them.

``cases`` reads the case records of a book (or the records filed under a disease across the case collections): a
case opens where a patient is named (王　十岁 · 某氏 · 一妇人年四十 · 喻嘉言治石开晓，); a visit opens at 二诊, 又, a
date (十四日), 次日, 越三日, or a new prescription built on the last (前方加…).  From each visit it reads the
findings (the lexicon's symptoms and signs; pulse and tongue descriptions), the diagnosis (diseases, patterns), the
principle of treatment, the formula and drugs with their doses, what was added to or taken from the last
prescription, how many doses were taken, and the response; the case's outcome is the last response recorded.  Words
of response before a visit's own prescription answer the previous visit's.

``trajectories`` turns the cases into sequences of visits and mines them (``science.trajectories``): the sequences
of principles and formulas common to many cases, what follows what from one visit to the next, and which choices go
with recovery in the records — associations in a record that physicians wrote and editors selected, not evidence of
efficacy.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from typing import Any

from ....protocol.base import stable_id
from ....protocol.cases import CaseRecord, Visit
from ....science.trajectories import outcome_associations, prefixspan, transitions
from .base import StudyBase

_LONG_NOTE = re.compile(r"（[^（）]{13,}）|\([^()]{13,}\)")  # commentary in brackets (雄按: …), not a dose （三钱）
_DOSE = re.compile(r"^[（(]?([一二三四五六七八九十百半两钱分厘斤升合枚个片只条匙匕克\d.]+[^）)]{0,6})[）)]?")
_SEX_F = re.compile(r"[女妇氏妪姬室眷妻娘姑嫂媳]|夫人")
_SEX_M = re.compile(r"男|翁|童|儿|僧|道士|士人|孝廉|文学|秀才|司空|别驾|太守|中丞|方伯|先生|公|兄|弟")
_AGE = re.compile(r"(?:年)?([一二三四五六七八九十廿卅]+)岁|[（(]([一二三四五六七八九十廿卅]+)[）)]|年([一二三四五六七八九十廿卅]+)(?:余|许)?")
# a date at the head of a record: 癸亥七月廿五日 · 三月初二日 · 丙寅二月初九日
_DATE = re.compile(r"^(?:[甲乙丙丁戊己庚辛壬癸][子丑寅卯辰巳午未申酉戌亥](?:年)?)?(?:[正一二三四五六七八九十冬腊]+月)?"
                   r"(?:初|十|二十|廿|三十|卅)?[一二三四五六七八九十]?日(?=[，,　 ])|^[甲乙丙丁戊己庚辛壬癸][子丑寅卯辰巳午未申酉戌亥]年?"
                   r"(?:[正一二三四五六七八九十冬腊]+月)(?=[，,　 ])")
RESPONSES = ("died", "worse", "unchanged", "improved")


class CaseStudy:
    def __init__(self, base: StudyBase) -> None:
        self.b = base
        d = base.data("cases.yaml")
        n = base.normalize
        self.openers = [re.compile(n(p)) for p in d.get("case_openers", [])]
        self.visits = [re.compile(n(p)) for p in d.get("visit_markers", [])]
        self.passage_visits = [re.compile(n(p)) for p in d.get("passage_visit_markers", [])]
        self.formula = re.compile(n(d.get("formula", "(?!)")))
        self.day = re.compile(n(d.get("day_markers", "(?!)")))
        self.pulse = re.compile(n(d.get("pulse", "(?!)")))
        self.qualities = set(n(d.get("pulse_qualities", "")))
        self.tongue = re.compile(n(d.get("tongue", "(?!)")))
        self.principles = [re.compile(n(p)) for p in d.get("principle", [])]
        mod = d.get("modification") or {}
        self.add = re.compile(n(mod.get("add", "(?!)")))
        self.remove = re.compile(n(mod.get("remove", "(?!)")))
        self.processing = {n(x) for x in d.get("processing", [])}
        self.doses = re.compile(n(d.get("doses", "(?!)")))
        self.non_case = re.compile(n(d.get("non_case_sections", "(?!)")))
        self.response = {k: [re.compile(n(p)) for p in v] for k, v in (d.get("response") or {}).items()}

    # ------------------------------------------------------------ the books
    def case_books(self) -> list[str]:
        """The case collections — one transcription per work (the fullest), so that no case is counted twice."""
        best: dict[str, tuple[int, str]] = {}
        for b in self.b.corpus.books.values():
            if b.category != "医案":
                continue
            size = self.b.corpus.book_passage_count(b.id)
            key = b.work or b.id
            if key not in best or (size, b.id) > best[key]:
                best[key] = (size, b.id)
        return sorted(bid for _, bid in best.values())

    def _rows(self, book_id: str) -> list[tuple[str, str, str]]:
        """(passage id, heading, text) in reading order — the heading being the most specific named locator field."""
        store = getattr(self.b.corpus, "store", None)
        out = []
        if store is not None:
            with store.lock:
                rows = store.db.execute("SELECT id, locator, kind, text FROM passages WHERE book_id=? ORDER BY seq",
                                        (book_id,)).fetchall()
            items = [(pid, json.loads(loc), kind, text) for pid, loc, kind, text in rows]
        else:
            items = [(p.id, {"chapter": p.locator.chapter, "section": p.locator.section, "volume": p.locator.volume}, p.kind, p.text)
                     for p in self.b.corpus.passages(book_ids=[book_id])]
        for pid, loc, kind, text in items:
            if kind in ("toc", "preface"):
                continue
            head = next((x.strip() for x in (loc.get("section"), loc.get("chapter"), loc.get("volume"))
                         if x and x.strip() and not re.fullmatch(r"卷?[之第]?[一二三四五六七八九十百\d]+[卷上中下]?", x.strip())), "")
            out.append((pid, head, text))
        return out

    # ------------------------------------------------------------ segmentation
    def _opens_case(self, text: str) -> tuple[re.Match[str] | None, str]:
        """A patient named at the head of ``text`` — after a date, if one comes first (癸亥七月廿五日，伊，二十四岁)."""
        head = text.lstrip("　 \t\n，,")
        date = _DATE.match(head)
        rest = head[date.end():].lstrip("　 ，,") if date else head
        for p in self.openers:
            m = p.match(rest)
            if m:
                return m, date.group(0) if date else ""
        return None, ""

    def _opens_visit(self, text: str, *, passage_start: bool = False) -> str:
        head = text.lstrip("　 \t\n")
        for p in self.visits + (self.passage_visits if passage_start else []):
            m = p.match(head)
            if m:
                return m.group(0)
        return ""

    def parse(self, book_id: str, *, sections: set[str] | None = None, limit: int | None = None) -> list[CaseRecord]:
        """The case records of a book (optionally only those under the given headings)."""
        book = self.b.corpus.books.get(book_id)
        year = float(book.composition.start) if book and book.composition else None
        return self.parse_rows(self._rows(book_id), book_id, year=year, sections=sections, limit=limit)

    def parse_rows(self, rows: list[tuple[str, str, str]], book_id: str, *, year: float | None = None,
                   sections: set[str] | None = None, limit: int | None = None) -> list[CaseRecord]:
        """Case records from (passage id, heading, text) rows in reading order.  Sentence by sentence: a patient named
        at the head of a sentence opens a case, a visit marker a visit; a day marker at the head of a clause opens a
        visit too (…服之，次日热退)."""
        cases: list[CaseRecord] = []
        texts: list[list[str]] = []
        current: CaseRecord | None = None
        prev_head: str | None = None

        def new_case(pid: str, head: str, opener: str, marker: str) -> CaseRecord:
            case = CaseRecord(id=stable_id("case", book_id, pid, len(cases)), book_id=book_id, section=head, year=year,
                              opener=opener, patient=_patient(opener))
            case.visits.append(Visit(index=0, marker=marker))
            cases.append(case)
            texts.append([""])
            return case

        def new_visit(case: CaseRecord, marker: str) -> None:
            case.visits.append(Visit(index=len(case.visits), marker=marker))
            texts[-1].append("")

        for pid, head, raw in rows:
            if (sections is not None and head not in sections) or self.non_case.search(self.b.normalize(head)):
                prev_head, current = head, None
                continue
            norm = self.b.normalize(_LONG_NOTE.sub(lambda m: "　" * len(m.group(0)), raw)).replace("﹐", "，")
            if head != prev_head:
                current = None
            prev_head = head
            for k, sent in enumerate(re.split(r"(?<=[。！？])", norm)):
                if not sent.strip():
                    continue
                opener, date = self._opens_case(sent)
                if opener is not None or current is None:
                    if limit is not None and len(cases) >= limit:
                        return self._finish(cases[:limit], texts)
                    current = new_case(pid, head, opener.group(0) if opener else "", date)
                    if opener is not None:  # 一妇人年四十: what follows the opener may say more about the patient
                        more = _patient(opener.group(0) + sent[sent.find(opener.group(0)) + len(opener.group(0)):][:12])
                        current.patient = more | current.patient
                else:
                    marker = self._opens_visit(sent, passage_start=k == 0)
                    if marker:
                        new_visit(current, marker)
                clauses = re.split(r"(?<=[，；])", sent)
                for i, cl in enumerate(clauses):
                    dm = self.day.match(cl.lstrip("　 ")) if i > 0 else None
                    if dm and texts[-1][-1].strip():
                        new_visit(current, dm.group(0))
                    texts[-1][-1] += cl
                    v = current.visits[-1]
                    if pid not in v.passage_ids:
                        v.passage_ids.append(pid)
                if pid not in current.passage_ids:
                    current.passage_ids.append(pid)
        return self._finish(cases, texts)

    def _finish(self, cases: list[CaseRecord], texts: list[list[str]]) -> list[CaseRecord]:
        for case, vtexts in zip(cases, texts):
            for v, text in zip(case.visits, vtexts):
                v.quote = text.strip()[:120]
                self._read(v, text)
            for j in range(1, len(case.visits)):  # a response before a visit's own prescription answers the last one
                v, prev = case.visits[j], case.visits[j - 1]
                early = v.__dict__.pop("_early", None)
                if early and not prev.response:
                    prev.response, prev.response_words = early
            case.visits[0].__dict__.pop("_early", None)
            last = [v.response for v in case.visits if v.response]
            case.outcome = last[-1] if last else ""
        return [c for c in cases if any(v.formulas or v.herbs or v.principles for v in c.visits)]

    # ------------------------------------------------------------ one visit
    def _read(self, v: Visit, text: str) -> None:
        lex = self.b.pack.lexicon
        mentions = lex.match(text, include_weak=False)
        findings: dict[str, list[str]] = defaultdict(list)
        treat_at = len(text)
        herbs: list[dict[str, str]] = []
        for m in mentions:
            cat = m.category
            if cat in ("symptom", "sign"):
                findings[cat].append(m.entry.term)
            elif cat == "tongue":
                findings["tongue"].append(m.surface)
            elif cat in ("disease", "pattern"):
                v.diagnosis.append(m.entry.term)
            elif cat in ("treatment_principle", "treatment_method"):
                v.principles.append(m.entry.term)
            elif cat == "formula" and len(m.surface) >= 3 and not _is_drug(lex, m.surface):
                v.formulas.append(m.surface)  # as the record names it (the lexicon may file it under another name)
                treat_at = min(treat_at, m.start)
            elif cat == "herb" and len(m.surface) >= 2 and len(m.entry.term) >= 2:
                dose = _DOSE.match(text[m.end: m.end + 10])
                herbs.append({"name": m.entry.term, "dose": dose.group(1) if dose and dose.group(1)[0] not in "）)" else ""})
                treat_at = min(treat_at, m.start)
        for m in self.formula.finditer(text):  # formulas the record names, known to the lexicon or not
            name, at = (m.group(1), m.start(1)) if m.group(1) else (m.group(2), m.start(2))
            if name and not _is_drug(lex, name):
                v.formulas.append(name)
                treat_at = min(treat_at, at)
        findings["pulse"] = [m.group(0) for m in self.pulse.finditer(text) if set(m.group(0)) & self.qualities]
        findings["tongue"] += [m.group(0) for m in self.tongue.finditer(text) if m.group(0) not in findings["tongue"]]
        v.findings = {k: list(dict.fromkeys(x)) for k, x in findings.items() if x}
        v.diagnosis = list(dict.fromkeys(v.diagnosis))
        principles = list(v.principles)
        for p in self.principles:
            principles += [m.group(1) for m in p.finditer(text)]
        principles = list(dict.fromkeys(principles))
        v.principles = [x for x in principles if not any(x != y and x in y for y in principles)][:8]  # 辛凉 within 辛凉解表
        v.formulas = [f for f in dict.fromkeys(v.formulas) if not any(f != g and f in g for g in v.formulas)]
        seen: set[str] = set()
        v.herbs = [h for h in herbs if not (h["name"] in seen or seen.add(h["name"]))][:30]  # type: ignore[func-returns-value]
        for m in self.add.finditer(text):
            v.added += _drugs_in(lex, m.group(1))
            treat_at = min(treat_at, m.start())
        for m in self.remove.finditer(text):
            if m.group(1) in self.processing:
                continue
            names = _drugs_in(lex, m.group(1))
            if names:
                v.removed += names
                treat_at = min(treat_at, m.start())
        v.added, v.removed = list(dict.fromkeys(v.added)), list(dict.fromkeys(v.removed))
        dm = self.doses.search(text)
        v.doses = dm.group(0) if dm else ""
        if v.doses:
            treat_at = min(treat_at, dm.start())
        after, before = self._response(text[treat_at:]), self._response(text[:treat_at])
        if after:
            v.response, v.response_words = after
        if before:
            v.__dict__["_early"] = before

    def _response(self, text: str) -> tuple[str, list[str]] | None:
        """The last state the text reports (the latest word of response decides), with the words."""
        found: list[tuple[int, str, str]] = []
        for kind in RESPONSES:
            for p in self.response.get(kind, []):
                for m in p.finditer(text):
                    found.append((m.end(), kind, m.group(0)))
        if not found:
            return None
        found.sort()
        kind = found[-1][1]
        return kind, list(dict.fromkeys(w for _, k, w in found if k == kind))[:6]

    # ------------------------------------------------------------ a disease across the collections
    def cases(self, book: str | None = None, *, disease: str | None = None, books: list[str] | None = None,
              limit: int = 400) -> list[CaseRecord]:
        """Case records of one book, or those filed under (or naming) a disease across the case collections."""
        if book:
            return self.parse(book, limit=limit)
        pool = books or self.case_books()
        out: list[CaseRecord] = []
        if not disease:
            for bid in pool:
                out += self.parse(bid, limit=limit - len(out))
                if len(out) >= limit:
                    break
            return out[:limit]
        _, forms = self.b.surfaces(disease)
        ids: set[str] = set()
        for form, _ in forms[:6]:
            ids.update(self.b.find(form, book_ids=pool, limit=20000))
        by_book: dict[str, set[str]] = defaultdict(set)
        for p in self.b.passages(sorted(ids)):
            by_book[p.book_id].add(p.id)
        for bid in sorted(by_book):
            heads = {head for pid, head, _ in self._rows(bid) if pid in by_book[bid]}
            out += self.parse(bid, sections=heads)
            if len(out) >= limit:
                break
        names = {self.b.normalize(f) for f, _ in forms[:6]}

        def about(c: CaseRecord) -> bool:  # filed under it, or it is named in a diagnosis, a finding or the opening words
            said = [self.b.normalize(c.section)] + [x for v in c.visits for x in v.diagnosis + [y for ys in v.findings.values() for y in ys]]
            said.append(c.visits[0].quote if c.visits else "")
            return any(n in x or x == n for n in names for x in said)

        keep = [c for c in out if about(c)]
        return (keep or out)[:limit]

    def trajectories(self, disease: str | None = None, *, book: str | None = None, books: list[str] | None = None,
                     items: tuple[str, ...] = ("principle", "formula", "added"), limit: int = 400, min_support: int = 3
                     ) -> dict[str, Any]:
        cases = self.cases(book, disease=disease, books=books, limit=limit)
        seqs: list[list[set[str]]] = []
        used: list[tuple[set[str], str]] = []
        for c in cases:
            seq = []
            for v in c.visits:
                s: set[str] = set()
                if "principle" in items:
                    s |= {f"治法:{x}" for x in v.principles}
                if "formula" in items:
                    s |= {f"方:{x}" for x in v.formulas}
                if "added" in items:
                    s |= {f"加:{x}" for x in v.added}
                if "diagnosis" in items:
                    s |= {f"证:{x}" for x in v.diagnosis}
                if "pulse" in items:
                    s |= {f"脉:{x}" for x in v.findings.get("pulse", [])}
                seq.append(s)
            seqs.append(seq)
            if c.outcome:
                used.append((set().union(*seq) if seq else set(), c.outcome))
        visits = Counter(len(c.visits) for c in cases)
        books_used = Counter(c.book_id for c in cases)
        return {
            "disease": disease, "book": book, "cases": len(cases), "visits": sum(len(c.visits) for c in cases),
            "visits_per_case": dict(sorted(visits.items())), "outcomes": dict(Counter(c.outcome or "unrecorded" for c in cases)),
            "books": [{"book_id": b, "title": self.b.book_title(b), "cases": n} for b, n in books_used.most_common(20)],
            "patterns": prefixspan(seqs, min_support=min_support),
            "transitions": transitions(seqs, min_count=min_support),
            "associations": outcome_associations(used, min_cases=max(5, min_support)),
            "examples": [c.to_dict() for c in cases[:5]],
            "note": "cases and visits cut by rules (cases.yaml); items per visit: 治法 (principle), 方 (formula), 加 (drugs "
                    "added to the last prescription); patterns: items that follow one another across visits in many cases; "
                    "transitions: what the next visit holds (lift over its baseline); associations with recovery in the "
                    "record (Fisher, Benjamini–Hochberg) — physicians chose which cases to record, so these are "
                    "associations in a biased record, never evidence of efficacy",
        }


def _patient(opener: str) -> dict[str, str]:
    out: dict[str, str] = {}
    if not opener:
        return out
    if opener.strip() in ("左", "右"):  # 张聿青医案's convention
        return {"sex": "male" if opener.strip() == "左" else "female"}
    name = re.match(r"^(某|[一-鿿]{1,2}?)(?=[　 （(，,氏姓]|夫人|治|$)", opener)
    if name and name.group(1) not in ("一",):
        out["name"] = name.group(1)
    if _SEX_F.search(opener):
        out["sex"] = "female"
    elif _SEX_M.search(opener):
        out["sex"] = "male"
    age = _AGE.search(opener)
    if age:
        out["age"] = age.group(1) or age.group(2) or age.group(3)
    return out


def _is_drug(lex: Any, surface: str) -> bool:
    """A "formula" that is one processed drug (生石膏, 炙甘草): the lexicon's harvested formula names include some."""
    for form in (surface, surface[1:] if surface[0] in "生炒炙制煅焙酒醋盐姜蜜焦熟" else ""):
        if form and any(e.category == "herb" for e, _ in lex.lookup(form)):
            return True
    return False


def _drugs_in(lex: Any, text: str) -> list[str]:
    """The drugs a change names (加杏仁（三钱）　贝母（二钱）): the lexicon's, else the names as written."""
    bare = re.sub(r"[（(][^）)]*[）)]|[一二三四五六七八九十百半两钱分厘]+[钱两分]", " ", text)
    out = []
    for token in re.split(r"[、　 ，,。；]+", bare):
        if not token:
            continue
        known = [m.entry.term for m in lex.match(token, include_weak=False) if m.category == "herb" and len(m.surface) >= 2]
        out += known or ([token] if 2 <= len(token) <= 4 else [])
    return list(dict.fromkeys(out))[:8]


__all__ = ["CaseStudy"]
