"""医案轨迹 — case records read as courses of treatment, and the trajectories common to many of them.

``cases`` reads the case records of a book (or the records filed under a disease across the case collections): a
case opens where a patient is named (王　十岁 · 某氏 · 一妇人年四十 · 喻嘉言治石开晓，); a visit opens at 二诊, 又, a
date (十四日), 次日, 越三日, or a new prescription built on the last (前方加…).  From each visit it reads the
findings (the lexicon's symptoms and signs; pulse and tongue descriptions), the diagnosis (diseases, patterns), the
principle of treatment, the formula and drugs with their doses, what was added to or taken from the last
prescription, how many doses were taken, and the response; the case's outcome is the last response recorded.  Words
of response before a visit's own prescription answer the previous visit's.  What other physicians did before (前医用…,
诸医作…治, 误投…) is read apart, as the visit's ``prior`` — its diagnosis, principles, formulas, drugs and the response
to it — and never as the visit's own.

Every case of a book is read once and kept (``book_cases``); on a store, all the case collections are cached together in
``study-cache/cases-<key>.json.gz``, keyed by the corpus, the lexicon, the rules and this module's code, so that the
exploration functions (``caseexplore.py``) search thousands of cases without reading them again.

``trajectories`` turns the cases into sequences of visits and mines them (``science.trajectories``): the sequences
of principles and formulas common to many cases, what follows what from one visit to the next, and which choices go
with recovery in the records — associations in a record that physicians wrote and editors selected, not evidence of
efficacy.
"""

from __future__ import annotations

import dataclasses
import gzip
import hashlib
import json
import re
import threading
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ....protocol.base import stable_id
from ....protocol.cases import CaseRecord, Visit
from ....science.trajectories import outcome_associations, prefixspan, transitions
from .base import StudyBase, cache_tmp

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
_BOUNDARY = re.compile(r"[。！？，；：,;]")
_ENUMERATION = re.compile(r"(?:以|用|投|与|进|服)((?:[一-鿿]{1,4}、)+[一-鿿]{1,4})")  # 医以参、术、川芎、陈皮、茯苓服之
_ENUMERATION_TAIL = re.compile(r"(?:下之|治之|服之|投之|与之|进之|补之|之属|之类|等|辈).*$")  # 五味等滋 → 五味
_READER = hashlib.sha1(Path(__file__).read_bytes()).hexdigest()[:12]  # the reading's own code: a cache outlives no change to it
PRIOR_KINDS = ("diagnosis", "principles", "formulas", "herbs")


class CaseStudy:
    def __init__(self, base: StudyBase) -> None:
        self.b = base
        d = base.data("cases.yaml")
        n = base.normalize
        self._rules = d
        self._parsed: dict[str, list[CaseRecord]] = {}
        self._pool_loaded = False
        self._cache_read = False
        self._lock = threading.Lock()  # the books read so far
        self._loading = threading.RLock()  # reading the disk cache, or every collection, happens once
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
        prior = d.get("prior") or {}
        self.prior_opens = [re.compile(n(p)) for p in prior.get("opens", [])]
        self.prior_own = re.compile(n(prior.get("own", "(?!)")))
        self.prior_own_inline = re.compile(n(prior.get("own_inline", "(?!)")))
        self.prior_generic = re.compile(n(prior.get("generic", "(?!)")))
        self.prior_diagnosis = re.compile(n(prior.get("diagnosis", "(?!)")))
        self.prior_basic = set(n(prior.get("basic", "")))
        self.known_persons = {n(x) for p in base.data("physicians.yaml").get("persons") or []
                              for x in [p["name"], *(p.get("names") or [])]}

    # ------------------------------------------------------------ every case, read once
    def key(self) -> str:
        """What the cached cases were read from and with: the corpus, the lexicon, the rules and this module's code."""
        rules = hashlib.sha1(json.dumps(self._rules, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
        raw = json.dumps([self.b.signature()["corpus_digest"], len(self.b.pack.lexicon.entries), _READER, rules])
        return hashlib.sha1(raw.encode()).hexdigest()[:12]

    def book_cases(self, book_id: str) -> list[CaseRecord]:
        """Every case of a book, read once and kept (the callers filter; they never change a case) — from the disk cache
        of all the collections when there is one, so that a container's first question reads no book again."""
        self._read_cache()
        with self._lock:
            got = self._parsed.get(book_id)
        if got is None:
            got = self.parse(book_id)
            with self._lock:
                got = self._parsed.setdefault(book_id, got)
        return got

    def pool(self, books: list[str] | None = None) -> list[CaseRecord]:
        """The cases of the case collections (or of ``books``), in book order.  All the collections are read together
        once — on a store, from ``study-cache/cases-<key>.json.gz`` when it is there, else read and written there."""
        if books is None:
            self._load_pool()
        return [c for bid in (books or self.case_books()) for c in self.book_cases(bid)]

    def _cache_path(self) -> Path | None:
        store = getattr(self.b.corpus, "store", None)
        return store.path.parent / "study-cache" / f"cases-{self.key()}.json.gz" if store is not None else None

    def _read_cache(self) -> bool:
        """Every collection's cases from the disk cache, once, if it is there; whether the pool is now whole.  Callers
        arriving together (a container's preload and its first question) wait for one reading."""
        with self._loading:
            if not self._cache_read:
                self._cache_read = True
                path = self._cache_path()
                if path is not None and path.exists():
                    with gzip.open(path, "rt", encoding="utf-8") as f:
                        cached = json.load(f)
                    with self._lock:
                        for bid, rows in cached["books"].items():
                            self._parsed.setdefault(bid, [_record(r) for r in rows])
                    self._pool_loaded = True
            return self._pool_loaded

    def _load_pool(self) -> None:
        """All the collections, once: from the disk cache, else read — and, on a store, written there."""
        if self._read_cache():
            return
        with self._loading:
            if self._pool_loaded:
                return
            books: dict[str, list[CaseRecord]] = {}
            for bid in self.case_books():
                with self._lock:
                    got = self._parsed.get(bid)
                if got is None:
                    got = self.parse(bid)
                    with self._lock:
                        got = self._parsed.setdefault(bid, got)
                books[bid] = got
            path = self._cache_path()
            if path is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = cache_tmp(path)
                with gzip.open(tmp, "wt", encoding="utf-8") as f:
                    json.dump({"key": self.key(), "books": {b: [c.to_dict() for c in cs] for b, cs in books.items()}}, f,
                              ensure_ascii=False)
                tmp.replace(path)
                for old in path.parent.glob("cases-*.json.gz"):
                    if old != path:
                        old.unlink(missing_ok=True)
            self._pool_loaded = True

    def find_case(self, case_id: str) -> CaseRecord | None:
        """A case by its id (ids are stable: the book, the passage that opened the case and its place in the book)."""
        for c in self.pool():
            if c.id == case_id:
                return c
        return None

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

    def _physician(self, opener: str) -> str:
        """The physician a compilation's case opens with (丹溪治一妇 → 丹溪; 丹溪尝治一人 → 丹溪), else "": a name
        physicians.yaml knows, or one that looks like a name — never 一方治…, 今之治…, 二妙散治…"""
        m = _TREATS.match(opener or "")
        if not m:
            return ""
        name = re.sub(r"(?<=[一-鿿]{2})[之尝曾又亦乃遂常每昔初]+$", "", m.group(1))
        if self.b.normalize(name) in self.known_persons:
            return name
        surname = name[:2] in _COMPOUND_SURNAMES or name[0] in _SURNAMES
        return name if surname and 2 <= len(name) <= 4 and not set(name) & _NOT_IN_A_NAME else ""

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
                              opener=opener, patient=_patient(opener), physician=self._physician(opener))
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
    def _prior_spans(self, text: str) -> list[tuple[int, int, str]]:
        """Candidate accounts of what earlier physicians did: (start, end, the words that opened it) — from those words
        to the end of their sentence, or to a clause that turns back to the recording physician (余诊之, 予以…, 改用…);
        in a run without punctuation, to the first word that does (邀予诊之)."""
        found = sorted((m for p in self.prior_opens for m in p.finditer(text)), key=lambda m: (m.start(), -m.end()))
        head = text.lstrip("　 \t\n，,")
        opener = _TREATS.match(head)  # a compilation's case opens with its own physician (钱医治一人…): no earlier one
        own_until = len(text) - len(head) + opener.end() if opener else 0
        spans: list[tuple[int, int, str]] = []
        for m in found:
            if (spans and m.start() < spans[-1][1]) or m.start() < own_until:
                continue
            end, pos = len(text), m.end()
            for b in _BOUNDARY.finditer(text, pos):
                inline = self.prior_own_inline.search(text, pos, b.start())
                if inline:
                    end = inline.start()
                    break
                if b.group(0) in "。！？":
                    end = b.end()
                    break
                if self.prior_own.match(text[b.end():].lstrip("　 ")):
                    end = b.start()
                    break
                pos = b.end()
            else:
                inline = self.prior_own_inline.search(text, pos)
                end = inline.start() if inline else end
            spans.append((m.start(), end, m.group(0)))
        return spans

    def _read_prior(self, v: Visit, text: str, spans: list[tuple[int, int, str]], mentions: list[Any]) -> list[tuple[int, int, str]]:
        """The visit's ``prior``: what the accounts of earlier treatment name, and how the patient fared on it.  Returns
        the accounts kept — not a warning or a maxim, and naming something or reporting a response."""
        lex = self.b.pack.lexicon
        kept: list[tuple[int, int, str]] = []
        prior: dict[str, list[str]] = defaultdict(list)
        response = None
        for s, e, w in spans:
            sub = text[s:e]
            if self.prior_generic.search(sub):
                continue
            named: dict[str, list[str]] = defaultdict(list)
            for m in mentions:
                if not s <= m.start < e:
                    continue
                cat = m.category
                if cat in ("disease", "pattern"):
                    named["diagnosis"].append(m.entry.term)
                elif cat in ("treatment_principle", "treatment_method"):
                    named["principles"].append(m.entry.term)
                elif cat == "formula" and len(m.surface) >= 3 and not _is_drug(lex, m.surface):
                    named["formulas"].append(m.surface)
                elif cat == "herb" and len(m.surface) >= 2 and len(m.entry.term) >= 2:
                    named["herbs"].append(m.entry.term)
            for m in self.prior_diagnosis.finditer(sub):  # 以为劳瘵, 误认为实: what the lexicon knows, or one basic word
                name = m.group(1) or m.group(2)
                if name in self.prior_basic or any(e.category in ("disease", "pattern", "symptom", "sign")
                                                   for e, _ in lex.lookup(name)):
                    named["diagnosis"].append(name)
            for m in self.formula.finditer(sub, len(w)):  # after the opening words (医以理中汤与之 → 理中汤)
                name = _formula_name(lex, _formula_match(sub, m)[0])
                if name and not _is_drug(lex, name):
                    named["formulas"].append(name)
            for p in self.principles:
                named["principles"] += [m.group(1) for m in p.finditer(sub)]
            for m in _ENUMERATION.finditer(sub):  # 以大黄、巴豆下之: drugs the lexicon may not know, as written
                named["herbs"] += [x for x in _drugs_in(lex, _ENUMERATION_TAIL.sub("", m.group(1))) if x[-1] not in _SUFFIX]
            said = self._response(sub)
            if not any(named.values()) and said is None:
                continue
            kept.append((s, e, w))
            for kind, names in named.items():
                prior[kind] += names
            response = said or response
        if not kept:
            return kept
        out: dict[str, list[str]] = {}
        for kind in PRIOR_KINDS:
            names = list(dict.fromkeys(x for x in prior.get(kind, []) if x))
            names = [x for x in names if not any(x != y and x in y for y in names)]  # 辛凉 within 辛凉解表
            if kind == "herbs":
                names = [x for x in names if not any(x in f for f in out.get("formulas", []))]  # 大黄 of 大黄丸
            if names:
                out[kind] = names[:8]
        v.prior = out
        v.prior_words = list(dict.fromkeys(w for _, _, w in kept))[:4]
        v.prior_quote = text[kept[0][0]: kept[0][1]].strip()[:60]
        v.prior_response = response[0] if response else ""
        return kept

    def _read(self, v: Visit, text: str) -> None:
        lex = self.b.pack.lexicon
        mentions = lex.match(text, include_weak=False)
        spans = self._prior_spans(text)
        if spans:  # what earlier physicians did is read apart: the visit's own reading sees blanks there
            spans = self._read_prior(v, text, spans, mentions)
        if spans:
            chars = list(text)
            for s, e, _ in spans:
                chars[s:e] = "　" * (e - s)
            own = "".join(chars)
        else:
            own = text
        findings: dict[str, list[str]] = defaultdict(list)
        treat_at = len(text)
        herbs: list[dict[str, str]] = []
        for m in mentions:
            cat = m.category
            if cat in ("symptom", "sign"):  # the patient's findings, whoever was treating them
                findings[cat].append(m.entry.term)
            elif cat == "tongue":
                findings["tongue"].append(m.surface)
            elif spans and any(s <= m.start < e for s, e, _ in spans):
                continue
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
        for m in self.formula.finditer(own):  # formulas the record names, known to the lexicon or not
            name, at = _formula_match(own, m)
            name = _formula_name(lex, name)
            if name and not _is_drug(lex, name):
                v.formulas.append(name)
                treat_at = min(treat_at, at)
        findings["pulse"] = [m.group(0) for m in self.pulse.finditer(text) if set(m.group(0)) & self.qualities]
        findings["tongue"] += [m.group(0) for m in self.tongue.finditer(text) if m.group(0) not in findings["tongue"]]
        v.findings = {k: list(dict.fromkeys(x)) for k, x in findings.items() if x}
        v.diagnosis = list(dict.fromkeys(v.diagnosis))
        principles = list(v.principles)
        for p in self.principles:
            principles += [m.group(1) for m in p.finditer(own)]
        principles = list(dict.fromkeys(principles))
        v.principles = [x for x in principles if not any(x != y and x in y for y in principles)][:8]  # 辛凉 within 辛凉解表
        v.formulas = [f for f in dict.fromkeys(v.formulas) if not any(f != g and f in g for g in v.formulas)]
        seen: set[str] = set()
        v.herbs = [h for h in herbs if not (h["name"] in seen or seen.add(h["name"]))][:30]  # type: ignore[func-returns-value]
        for m in self.add.finditer(own):
            v.added += _drugs_in(lex, m.group(1))
            treat_at = min(treat_at, m.start())
        for m in self.remove.finditer(own):
            if m.group(1) in self.processing:
                continue
            names = _drugs_in(lex, m.group(1), known_only=True)  # 去血无算, 去皮研开: only the drugs the lexicon knows
            if names:
                v.removed += names
                treat_at = min(treat_at, m.start())
        v.added, v.removed = list(dict.fromkeys(v.added)), list(dict.fromkeys(v.removed))
        dm = self.doses.search(own)
        v.doses = dm.group(0) if dm else ""
        if v.doses:
            treat_at = min(treat_at, dm.start())
        after, before = self._response(own[treat_at:]), self._response(own[:treat_at])
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
        """Case records of one book, or those filed under (or naming) a disease across the case collections.  Books are
        read whole and kept (``book_cases``), so a case has the same id whichever function found it."""
        if book:
            return self.book_cases(book)[:limit]
        pool = books or self.case_books()
        out: list[CaseRecord] = []
        if not disease:
            for bid in pool:
                out += self.book_cases(bid)
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
            out += [c for c in self.book_cases(bid) if c.section in heads]  # what parse(sections=heads) reads, same ids
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


_CASE_FIELDS = {f.name for f in dataclasses.fields(CaseRecord)} - {"visits"}
_VISIT_FIELDS = {f.name for f in dataclasses.fields(Visit)}


def _record(row: dict[str, Any]) -> CaseRecord:
    """A case as the cache wrote it (``to_dict``): built directly — the generic ``from_dict`` reads the type hints of
    every field of every visit, several times slower over the tens of thousands of cases of the full corpus."""
    visits = [Visit(**{k: v for k, v in x.items() if k in _VISIT_FIELDS}) for x in row.get("visits") or []]
    return CaseRecord(**{k: v for k, v in row.items() if k in _CASE_FIELDS}, visits=visits)


_TREATS = re.compile(r"^([一-鿿]{2,5}?)治(?=[一-鿿])")  # 丹溪治一妇 · 喻嘉言治石开晓: the physician, then the patient


# a name before 治 that physicians.yaml does not know is a physician's only when it looks like one: a common surname
# first, two to four characters, none of the words or formula endings that stand there instead (二妙散治…, 而不能治…)
_SURNAMES = set("王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾萧肖田董袁潘于蒋蔡余杜叶程苏魏吕丁任"
                "沈姚卢姜崔钟谭陆汪范金石廖贾夏韦方白邹孟熊秦邱江尹薛段雷侯龙史陶黎贺顾毛郝龚邵万钱严武戴莫孔向汤常温"
                "康施文牛樊葛邢安齐易乔伍庞颜倪庄聂章鲁岳翟殷詹申欧耿关兰焦俞左柳甘祝包宁尚符舒阮柯纪梅童凌毕单季裴霍"
                "涂成苗谷盛曲翁冉骆蓝路游辛靳管柴蒙鲍华喻祁蒲房滕屈饶解牟艾尤阳时穆司卓古吉缪简车项连娄窦戚岑景党宫费"
                "卜冷晏席卫米柏宗瞿桂全佟应臧闵苟边卞姬师仇栾隋商刁沙荣巫寇桑郎甄丛仲虞敖巩明佘池查麻楼滑")
_COMPOUND_SURNAMES = ("欧阳", "司马", "皇甫", "上官", "诸葛", "东方", "公孙", "夏侯", "慕容", "尉迟", "令狐", "长孙", "淳于", "钟离")
_NOT_IN_A_NAME = set("之皆屡也者为而不能是故则乃每宜设考间主专仿阅见知但其所云曰谓用投与治病此凡今他诸众前后余予吾如"
                     "又有人贤方法汤散丸饮丹膏煎")


def _patient(opener: str) -> dict[str, str]:
    out: dict[str, str] = {}
    if not opener:
        return out
    if opener.strip() in ("左", "右"):  # 张聿青医案's convention
        return {"sex": "male" if opener.strip() == "左" else "female"}
    m = _TREATS.match(opener)
    if m:  # what comes before 治 is the physician, not the patient
        opener = opener[m.end():]
    name = re.match(r"^(某|[一-鿿]{1,2}?)(?=[　 （(，,氏姓]|夫人|治|$)", opener)
    if name and not name.group(1).startswith("一"):
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


_SUFFIX = "汤散丸饮丹膏煎"


def _formula_match(text: str, m: re.Match[str]) -> tuple[str, int]:
    """The name a match of the formula pattern read, and where it starts — run on over a suffix that follows at once:
    膏 is a suffix too, and the pattern stops at the first (用竹叶石膏汤 → 竹叶石膏汤, not 竹叶石膏)."""
    g = 1 if m.group(1) else 2
    name, start, end = m.group(g) or "", m.start(g), m.end(g)
    if end < len(text) and text[end] in _SUFFIX:
        name += text[end]
    return name, start


_LEADING = "以用即乃遂又仍则而并亦"  # words that run into a formula's name in the record (以四物汤, 即重用达生散)
_GIVING = "以用与予投进服送授"  # a verb inside a name read too far back (热成疳以大芦荟丸, 不效又进柴苓汤)
_REFERENCE = re.compile(r"^(?:前|原|此|是|其|本|旧|新)方")  # 仍用前方煎: the last prescription, not a formula's name
_PARTICLES = set("也哉矣乎焉耶欤")  # in 白文 a name read across a sentence's end (岂理也哉虽然丹) is no name


def _formula_name(lex: Any, name: str) -> str:
    """A formula's name as the record writes it, without the words run into its head — unless the lexicon knows the
    whole (再造散 keeps its 再: 再 is not stripped at all); "" for a reference to a prescription (前方煎)."""
    if any(e.category == "formula" for e, _ in lex.lookup(name)):
        return name
    cut = max((i for i in range(1, len(name) - 2) if name[i - 1] in _GIVING), default=0)
    name = name[cut:]  # the name after the last verb of giving, three characters at least
    while len(name) > 3 and name[0] in _LEADING and not any(e.category == "formula" for e, _ in lex.lookup(name)):
        name = name[1:]
    for lead in ("重用", "大剂", "重剂", "小剂"):
        if name.startswith(lead) and len(name) > len(lead) + 2:
            name = name[len(lead):]
    return "" if _REFERENCE.match(name) or _PARTICLES & set(name) else name


def _drugs_in(lex: Any, text: str, *, known_only: bool = False) -> list[str]:
    """The drugs a change names (加杏仁（三钱）　贝母（二钱）): the lexicon's, else (unless ``known_only``) the names as
    written."""
    bare = re.sub(r"[（(][^）)]*[）)]|[一二三四五六七八九十百半两钱分厘]+[钱两分]", " ", text)
    out = []
    for token in re.split(r"[、　 ，,。；]+", bare):
        if not token:
            continue
        known = [m.entry.term for m in lex.match(token, include_weak=False) if m.category == "herb" and len(m.surface) >= 2]
        out += known or ([token] if 2 <= len(token) <= 4 and not known_only else [])
    return list(dict.fromkeys(out))[:8]


__all__ = ["CaseStudy"]
