"""引书与引人 — who cites which book and which physician, period by period.

The classics are woven out of citations: 《内经》曰, 经云, 仲景曰, 东垣云, 时珍曰.  One pass over the store collects

* **引书** — titles in 书名号 and the generic 经曰/经言, resolved to books and works of the corpus or to works known
  only through citations (``external-works.yaml``); unresolved titles are kept as “语料未收之书”;
* **引人** — physicians named with a citing word (``domains/classics/physicians.yaml``; the one-character names of the
  materia medica — 杲曰, 恭曰, 颂曰 — only in 本草 books);

and aggregates them by the date of the citing book.  The result answers: which authorities each period leaned on,
when a book or a physician started to be cited and by whom, and — linking the authors of citing books to the
physicians they cite — a network of intellectual descent.  Punctuated transcriptions carry most 书名号; the
unpunctuated Siku copies contribute mainly through 经曰 and names.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterator

from ..citations import CitationExtractor
from .base import StudyBase, dated

_TITLE = re.compile(r"《([^》]{1,14})》")
_GENERIC = re.compile(r"(经)(?:曰|云)|(经言)")
_VERBS = "曰|云|谓|言|论|所谓|之说|之论|方|法"
_LOOSE = {"仲景", "长沙", "东垣", "丹溪", "河间", "景岳", "叔和", "思邈", "时珍", "洁古", "海藏", "子和", "戴人", "天士", "嘉言",
          "韵伯", "修园", "鞠通", "孟英", "灵胎", "洄溪", "濒湖", "立斋", "仲淳", "士材", "隐庵", "石顽", "讱庵", "容川"}


class CitationNetwork:
    def __init__(self, base: StudyBase) -> None:
        self.b = base
        self.persons = {p["id"]: p for p in base.data("physicians.yaml").get("persons") or []}
        self._extractor: CitationExtractor | None = None
        self._resolved: dict[str, tuple[str, dict[str, float]]] = {}
        self._built: dict[str, Any] | None = None
        norm = base.normalize
        loose, strict, bencao = [], [], []
        self._alias: dict[str, str] = {}
        for pid, p in self.persons.items():
            for name in p.get("names") or []:
                key = norm(name)
                self._alias[key] = pid
                (loose if len(key) >= 3 or key in {norm(x) for x in _LOOSE} else strict).append(key)
            for name in p.get("bencao") or []:
                key = norm(name)
                self._alias.setdefault(key, pid)
                bencao.append(key)

        def alt(names: list[str]) -> str:
            return "|".join(map(re.escape, sorted(set(names), key=len, reverse=True))) or "(?!)"

        self._loose = re.compile(rf"({alt(loose)})(?:氏)?(?:{_VERBS})")
        self._strict = re.compile(rf"(?:^|[。，；：、\s　（(「『“])({alt(strict)})(?:曰|云|谓|言)")
        self._bencao = re.compile(rf"(?:^|[。，；：、\s　（(〕】])({alt(bencao)})(?:曰|云)")

    # ------------------------------------------------------------ resolution
    def _resolve(self, title: str) -> tuple[str, dict[str, float]]:
        hit = self._resolved.get(title)
        if hit is None:
            if self._extractor is None:
                self._extractor = CitationExtractor(self.b.pack, self.b.corpus)
            hit = self._extractor._resolve_title(title)
            self._resolved[title] = hit
        return hit

    def _generic(self, key: str) -> dict[str, float]:
        spec = (self.b.pack.citations.get("generic_references") or {}).get(key) or {}
        return dict(spec.get("candidates") or {})

    # ------------------------------------------------------------ scanning
    def _rows(self) -> Iterator[tuple[str, str, float | None, str]]:
        store = getattr(self.b.corpus, "store", None)
        if store is not None:
            last = ""
            while True:
                with store.lock:
                    rows = store.db.execute("SELECT id, book_id, year, text FROM passages WHERE id > ? AND kind != 'toc' "
                                            "ORDER BY id LIMIT 5000", (last,)).fetchall()
                if not rows:
                    return
                for row in rows:
                    if row[1] in self.b.corpus.books:
                        yield row
                last = rows[-1][0]
        else:
            for p in self.b.corpus.passages():
                yield p.id, p.book_id, self.b.year(p), p.text

    def build(self, cache: str | Path | None = None, *, refresh: bool = False) -> dict[str, Any]:
        """Citations aggregated over the corpus: (citing book, target) → count, and (citing book, person) → count."""
        if self._built is not None and not refresh:
            return self._built
        key = self._cache_key()
        if cache is not None and not refresh:
            path = Path(cache) / f"citations-{key}.json"
            if path.exists():
                self._built = json.loads(path.read_text(encoding="utf-8"))
                return self._built
        norm = self.b.normalize
        bencao_books = {bk.id for bk in self.b.corpus.books.values() if bk.category == "本草" or "本草" in bk.title}
        books: dict[str, Counter] = defaultdict(Counter)
        persons: dict[str, Counter] = defaultdict(Counter)
        unresolved: Counter = Counter()
        examples: dict[str, str] = {}
        passages = 0
        own = {bid: self._authors_as_persons(bid) for bid in self.b.corpus.books}
        work_of = {bid: (bk.work or bid) for bid, bk in self.b.corpus.books.items()}
        for pid, book_id, year, text in self._rows():
            passages += 1
            per = self.b.period_of(year)
            key_bp = f"{book_id}|{per.id if per else '-'}"  # the period of the passage (its layer), not of the book
            for m in _TITLE.finditer(text):
                kind, cands = self._resolve(m.group(1))
                if kind == "unresolved":
                    unresolved[norm(m.group(1))] += 1
                    continue
                for target, w in cands.items():
                    if kind == "book" and work_of.get(target, target) == work_of.get(book_id, book_id):
                        continue  # a book naming itself or another copy of the same work
                    books[key_bp][f"{kind}:{target}"] += w
                    examples.setdefault(f"{kind}:{target}", pid)
            for m in _GENERIC.finditer(text):
                for target, w in self._witnessed(self._generic(m.group(1) or m.group(2))).items():
                    books[key_bp][f"book:{target}"] += w
            ntext = norm(text)
            found = [m.group(1) for m in self._loose.finditer(ntext)] + [m.group(1) for m in self._strict.finditer(ntext)]
            if book_id in bencao_books:
                found += [m.group(1) for m in self._bencao.finditer(ntext)]
            for name in found:
                person = self._alias.get(name)
                if person and person not in own.get(book_id, ()):  # 时珍曰 in the 本草纲目 is the author speaking
                    persons[key_bp][person] += 1
                    examples.setdefault(f"person:{person}", pid)
        built = {"key": key, "passages": passages,
                 "books": {b: {t: round(n, 3) for t, n in c.items()} for b, c in books.items()},
                 "persons": {b: dict(c) for b, c in persons.items()},
                 "unresolved": dict(unresolved.most_common(300)), "examples": examples}
        if cache is not None:
            Path(cache).mkdir(parents=True, exist_ok=True)
            (Path(cache) / f"citations-{key}.json").write_text(json.dumps(built, ensure_ascii=False), encoding="utf-8")
        self._built = built
        return built

    def _authors_as_persons(self, book_id: str) -> set[str]:
        book = self.b.corpus.books.get(book_id)
        out = set()
        for author in (book.authors if book else []):
            person = self._alias.get(self.b.normalize(re.sub(r"[（(].*?[）)]|等$|^旧题", "", author).strip()))
            if person:
                out.add(person)
        return out

    def _witnessed(self, candidates: dict[str, float]) -> dict[str, float]:
        out: dict[str, float] = {}
        for target, weight in candidates.items():
            books = self.b.corpus.witnesses(target) or [target]
            for bk in books:
                out[bk] = out.get(bk, 0.0) + weight / len(books)
        return out

    def _cache_key(self) -> str:
        sig = self.b.signature()
        parts = [sig["corpus_digest"], json.dumps(self.persons, ensure_ascii=False, sort_keys=True),
                 json.dumps(self.b.pack.citations, ensure_ascii=False, sort_keys=True), "v3"]
        return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]

    # ------------------------------------------------------------ views
    def _work_title(self, work: str) -> str:
        if not hasattr(self, "_work_titles"):
            titles: dict[str, tuple[float, str]] = {}
            for bk in self.b.corpus.books.values():
                w = bk.work or bk.id
                year = bk.composition.start if bk.composition else 9999
                if w not in titles or year < titles[w][0] or (year == titles[w][0] and len(bk.title) < len(titles[w][1])):
                    titles[w] = (year, bk.title)
            self._work_titles = {w: t for w, (_, t) in titles.items()}
        return self._work_titles.get(work, work)

    def _work_of(self, target: str) -> tuple[str, str]:
        """(work key, display title) of a citation target (book witnesses of one work are one work)."""
        kind, ident = target.split(":", 1)
        if kind == "book":
            book = self.b.corpus.books.get(ident)
            if book is not None:
                work = book.work or book.id
                return f"work:{work}", self._work_title(work)
            return f"work:{ident}", ident
        if kind == "external":
            ext = getattr(self.b.corpus, "external", {}).get(ident)
            return f"external:{ident}", ext.title if ext else ident
        if kind == "person":
            p = self.persons.get(ident, {})
            return target, p.get("name", ident)
        return target, ident

    def _starts(self) -> dict[str, float]:
        """The earliest date of every citable target (work, external work, physician)."""
        if not hasattr(self, "_start_of"):
            starts: dict[str, float] = {}
            for bk in self.b.corpus.books.values():
                if bk.composition is not None:
                    key = f"work:{bk.work or bk.id}"
                    starts[key] = min(starts.get(key, 9999.0), float(bk.composition.start))
            for ident, ext in (getattr(self.b.corpus, "external", {}) or {}).items():
                if getattr(ext, "composition", None) is not None:
                    starts[f"external:{ident}"] = float(ext.composition.start)
            for ident, person in self.persons.items():
                span = person.get("life") or person.get("active")
                if span:
                    starts[f"person:{ident}"] = float(span[0])
            self._start_of = starts
        return self._start_of

    def _anachronistic(self, key: str, target: str) -> bool:
        """A citation dated before the cited work or physician existed sits in a later layer (an editor's note in a
        classic, dated with the text it annotates): it is set aside, not counted for that period."""
        per = self._period_of_key(key)
        start = self._starts().get(target)
        return per is not None and start is not None and start >= per.end

    def _period_of_key(self, key: str) -> Any:
        pid = key.split("|", 1)[1] if "|" in key else "-"
        return next((p for p in self.b.periods if p.id == pid), None)

    def summary(self, cache: str | Path | None = None, *, top: int = 12) -> dict[str, Any]:
        """The authorities each period cites most (books and physicians), counted in citing books."""
        built = self.build(cache)
        by_period: dict[str, dict[str, Counter]] = defaultdict(lambda: {"books": Counter(), "persons": Counter()})
        titles: dict[str, str] = {}
        later_layers: Counter = Counter()
        for key, targets in built["books"].items():
            per = self._label(key)
            for target, n in targets.items():
                work, title = self._work_of(target)
                if self._anachronistic(key, work):
                    later_layers[per] += n
                    continue
                titles[work] = titles.get(work) or title
                by_period[per]["books"][work] += n
        for key, people in built["persons"].items():
            per = self._label(key)
            for person, n in people.items():
                if self._anachronistic(key, f"person:{person}"):
                    later_layers[per] += n
                    continue
                by_period[per]["persons"][person] += n
        out = []
        for per in [p.label for p in self.b.periods]:
            d = by_period.get(per)
            if not d:
                continue
            out.append({"period": per,
                        "books": [{"work": w, "title": titles[w], "citations": round(n, 1)} for w, n in d["books"].most_common(top)],
                        "persons": [{"person": p, "name": self.persons[p]["name"], "citations": n}
                                    for p, n in d["persons"].most_common(top)]})
        return {"periods": out, "passages_scanned": built["passages"],
                "set_aside_later_layers": {k: round(v, 1) for k, v in later_layers.items()},
                "unresolved": [{"title": t, "count": n} for t, n in list(built["unresolved"].items())[:40]]}

    def _label(self, key: str) -> str:
        pid = key.split("|", 1)[1] if "|" in key else "-"
        return next((p.label for p in self.b.periods if p.id == pid), "未定")

    def reception(self, target: str, cache: str | Path | None = None) -> dict[str, Any]:
        """Who cites a book (title), a work or a physician, when first and how often, period by period."""
        built = self.build(cache)
        norm = self.b.normalize
        person = self._alias.get(norm(target)) or (target if target in self.persons else None)
        keys: set[str] = set()
        label = target
        if person:
            keys = {f"person:{person}"}
            label = self.persons[person]["name"]
        else:
            kind, cands = self._resolve(target)
            for ident in cands:
                work, title = self._work_of(f"{kind}:{ident}")
                keys.add(work)
                label = title
        per_book: dict[str, float] = defaultdict(float)
        first_in: dict[str, Any] = {}  # book → the earliest period its citing passages belong to
        periods: Counter = Counter()
        by_id = {per.id: per for per in self.b.periods}
        life = (self.persons[person].get("life") or self.persons[person].get("active")) if person else None
        for key, targets in (built["persons"].items() if person else built["books"].items()):
            bid, pid = key.split("|", 1)
            per = by_id.get(pid)
            if life and per is not None and per.end <= life[0]:
                continue  # a note of a later layer dated with the text it annotates
            if person:
                n = targets.get(person, 0)
            else:
                n = sum(v for t, v in targets.items() if self._work_of(t)[0] in keys and not self._anachronistic(key, self._work_of(t)[0]))
            if n:
                per_book[bid] += n
                periods[self._label(key)] += n
                if per is not None and (bid not in first_in or per.start < first_in[bid].start):
                    first_in[bid] = per
        by_work: dict[str, dict[str, Any]] = {}
        for bid, n in per_book.items():  # one row per citing work (its copies summed)
            book = self.b.corpus.books.get(bid)
            work = (book.work or bid) if book else bid
            per = first_in.get(bid)
            row = by_work.get(work)
            if row is None:
                by_work[work] = row = {"book_id": bid, "title": self._work_title(work) if book else bid, "dynasty": book.dynasty if book else "",
                                       "years": [book.composition.start, book.composition.end] if book and book.composition else None,
                                       "period": per.label if per else None, "_start": per.start if per else 9999,
                                       "citations": 0.0, "copies": 0, "authors": list(book.authors) if book else []}
            row["citations"] = round(row["citations"] + n, 2)
            row["copies"] += 1
            if per is not None and per.start < row["_start"]:
                row["period"], row["_start"] = per.label, per.start
        citing = list(by_work.values())
        # in the order of the citing passages' own period (a 新校正 note in the 素问 is a Song citation), then by date
        citing.sort(key=lambda r: (r["_start"], dated(r["years"]), r["book_id"]))
        for r in citing:
            r.pop("_start")
        example = built["examples"].get(next(iter(keys), ""), None)
        return {"target": label, "keys": sorted(keys), "citing_books": citing, "first": citing[0] if citing else None,
                "by_period": {k: round(v, 1) for k, v in periods.items()},
                "example_passage": example, "person": self.persons.get(person) if person else None}

    def lineage(self, cache: str | Path | None = None, *, min_count: int = 3) -> list[dict[str, Any]]:
        """Author → cited physician edges, where the author of a citing book is a known physician."""
        built = self.build(cache)
        norm = self.b.normalize
        edges: Counter = Counter()
        for key, people in built["persons"].items():
            bid = key.split("|", 1)[0]
            book = self.b.corpus.books.get(bid)
            if book is None:
                continue
            for author in book.authors:
                src = self._alias.get(norm(re.sub(r"[（(].*?[）)]|等$|旧题", "", author)))
                if not src:
                    continue
                for person, n in people.items():
                    if person != src:
                        edges[(src, person)] += n
        return [{"from": self.persons[a]["name"], "to": self.persons[b]["name"], "citations": n,
                 "from_dates": self.persons[a].get("life") or self.persons[a].get("active"),
                 "to_dates": self.persons[b].get("life") or self.persons[b].get("active")}
                for (a, b), n in edges.most_common() if n >= min_count]


__all__ = ["CitationNetwork"]
