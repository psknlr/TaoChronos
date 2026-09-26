"""名称 — the names of a drug, a formula or a disease through time.

A drug is written 薯蓣 in the 本经, 薯药 once the Tang avoided 代宗's name (豫), 山药 once the Song avoided 英宗's (曙);
玄参 became 元参 under 康熙 (玄烨); a formula's 丸 became 圆 under 钦宗 (桓).  For the names the lexicon records for
an entry — its name, its 异名, its taboo renames, the names of its parts and preparations (``study term`` counts
them together) — ``study names``

* counts the works that write each name, period by period and in bins of years, and each name's share of the works
  that write any of them (a work counts once; a name written only inside a longer one — 山药 in 干山药 — is left to
  the longer);
* gives the first works that write each name, the name each period prefers and when that changes;
* finds where the texts equate two of the names (薯蓣，一名山药; 山药即薯蓣) — the evidence that they are one;
* reads the names the punctuated texts give it that the lexicon lacks (…一名X, 又名X, 俗呼X, 今名X, X即…), for curation.

The counts are of the store's texts, dated by their layers: a name in a later editor's note counts in the note's
period.  A one-character name is too ambiguous to count; a candidate name is a reading, not a finding, until an expert
adds it to the lexicon.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from .base import StudyBase, dated

_EQUATE = r"(?:一名|又名|亦名|俗名|俗呼|俗谓之|今名|今呼|古名|又称|或作|一作|即是|即)"
_EDGE = set("之乎者也矣焉而以于其与则乃且亦所此是故曰云谓又即皆为若或凡但一及")


class NameStudy:
    def __init__(self, base: StudyBase) -> None:
        self.b = base

    # ------------------------------------------------------------ passages
    def _ids(self, form: str, limit: int) -> list[str]:
        corpus = self.b.corpus
        if getattr(corpus, "large", False):
            return corpus.contains(form, verify=True, limit=limit)
        return corpus.contains(form, normalize=self.b.normalize, limit=limit)

    def _rows(self, ids: list[str]) -> dict[str, tuple[str, float | None, str]]:
        """Passage id → (book id, year, text)."""
        out: dict[str, tuple[str, float | None, str]] = {}
        store = getattr(self.b.corpus, "store", None)
        if store is not None:
            for i in range(0, len(ids), 900):
                chunk = ids[i: i + 900]
                with store.lock:
                    rows = store.db.execute(f"SELECT id, book_id, year, text FROM passages WHERE id IN ({','.join('?' * len(chunk))})",
                                            chunk).fetchall()
                out.update({pid: (bid, year, text) for pid, bid, year, text in rows})
            return out
        for p in self.b.passages(ids):
            out[p.id] = (p.book_id, self.b.year(p), p.text)
        return out

    def _work(self, book_id: str) -> str:
        bk = self.b.corpus.books.get(book_id)
        return (bk.work if bk else None) or book_id

    # ------------------------------------------------------------ the study
    def run(self, term: str, *, bin_years: int = 100, max_passages: int = 30000, examples: int = 3) -> dict[str, Any]:
        b = self.b
        term_id, forms = b.surfaces(term)
        entry = b.pack.lexicon.entry(term_id) if term_id else None
        notes = dict(entry.synonym_notes) if entry else {}
        keys = {f: b.normalize(f) for f, _ in forms}
        found: dict[str, dict[str, tuple[str, float | None, str]]] = {}
        skipped = []
        for form, kind in forms:
            if len(keys[form]) < 2:
                skipped.append({"name": form, "kind": kind, "why": "one character: too ambiguous to count"})
                continue
            found[form] = self._rows(self._ids(form, max_passages))
        # a name written only inside a longer one (山药 of 干山药) is the longer one's
        for form in found:
            longer = [g for g in found if g != form and keys[form] in keys[g]]
            if not longer:
                continue
            for pid in [pid for pid in found[form] if any(pid in found[g] for g in longer)]:
                text = b.normalize(found[form][pid][2])
                rest = text
                for g in sorted(longer, key=lambda g: -len(keys[g])):
                    rest = rest.replace(keys[g], "〇" * len(keys[g]))
                if keys[form] not in rest:
                    del found[form][pid]
        by_period: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        by_bin: dict[int, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        rows = []
        for form, kind in forms:
            if form not in found:
                continue
            first: dict[str, tuple[Any, str]] = {}
            works_all: set[str] = set()
            for pid, (bid, year, _text) in found[form].items():
                work = self._work(bid)
                works_all.add(work)
                per = b.period_of(year)
                by_period[per.label if per else "未定"][form].add(work)
                if year is not None:
                    by_bin[int(year // bin_years * bin_years)][form].add(work)
                bk = b.corpus.books.get(bid)
                years = [bk.composition.start, bk.composition.end] if bk and bk.composition else None
                key = (dated([year, year] if year is not None else years), pid)
                if work not in first or key < first[work][0]:
                    first[work] = (key, pid)
            earliest = sorted(first.values())[:examples]
            quotes = []
            for _, pid in earliest:
                p = b.passages([pid])[0]
                i = b.normalize(p.text).find(keys[form])
                quotes.append(b.witness(p, start=max(0, i), end=max(0, i) + len(form), width=18))
            rows.append({"name": form, "kind": kind, "note": notes.get(form, ""), "passages": len(found[form]),
                         "works": len(works_all), "first": quotes})
        periods = [p.label for p in b.periods if p.label in by_period] + (["未定"] if "未定" in by_period else [])
        table = []
        for label in periods:
            any_work = set().union(*by_period[label].values())
            shares = {f: round(len(ws) / len(any_work), 3) for f, ws in by_period[label].items() if any_work}
            table.append({"period": label, "works": len(any_work), "names": {f: len(ws) for f, ws in by_period[label].items()},
                          "shares": shares, "preferred": max(shares, key=lambda f: (shares[f], f)) if shares else None})
        bins = []
        for start in sorted(by_bin):
            any_work = set().union(*by_bin[start].values())
            shares = {f: round(len(ws) / len(any_work), 3) for f, ws in by_bin[start].items()}
            bins.append({"from": start, "to": start + bin_years, "works": len(any_work), "shares": shares,
                         "preferred": max(shares, key=lambda f: (shares[f], f))})
        switches = self._switches([x for x in bins if x["works"] >= 3])
        out = {"term": term, "term_id": term_id, "names": rows, "skipped": skipped, "periods": table, "bins": bins,
               "bin_years": bin_years, "switches": switches,
               "equations": self._equations(found, keys), "candidates": self._candidates(found, keys),
               "note": "works writing each name (a work counts once, dated by the passage's layer); shares of the works "
                       "writing any of the names; candidates are names the punctuated texts give it after 一名/又名/俗呼… "
                       "that the lexicon lacks — readings to check, not findings"}
        return out

    @staticmethod
    def _switches(bins: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Where the preferred name changes and the new one holds (in the next bin too, or it is the last bin); a bin
        whose preference differs from both its neighbours, which agree, is a blip (three Tang works in Song editions
        writing 山药) and is read as theirs."""
        pref = [x["preferred"] for x in bins]
        for i in range(1, len(pref) - 1):
            if pref[i - 1] == pref[i + 1] != pref[i]:
                pref[i] = pref[i - 1]
        out = []
        for i in range(1, len(bins)):
            if pref[i - 1] == pref[i]:
                continue
            last = i == len(bins) - 1
            if last or pref[i + 1] == pref[i]:
                out.append({"from": pref[i - 1], "to": pref[i], "between": [bins[i - 1]["from"], bins[i]["to"]], "last_bin": last})
        return out

    def _equations(self, found: dict[str, dict[str, tuple[str, float | None, str]]], keys: dict[str, str],
                   limit: int = 12) -> list[dict[str, Any]]:
        """Passages that equate two of the names (A，一名B; A即B), earliest first, one per work and pair."""
        seen: set[tuple[str, str, str]] = set()
        out = []
        names = list(found)
        for a in names:
            for c in names:
                if a == c or keys[a] in keys[c] or keys[c] in keys[a]:
                    continue
                rx = re.compile(re.escape(keys[a]) + r"[，,、]?" + _EQUATE + r"[，,]?" + re.escape(keys[c]))
                for pid in set(found[a]) & set(found[c]):
                    bid, year, text = found[a][pid]
                    m = rx.search(self.b.normalize(text))
                    if not m or (a, c, self._work(bid)) in seen:
                        continue
                    seen.add((a, c, self._work(bid)))
                    p = self.b.passages([pid])[0]
                    out.append({"names": [a, c], "year": year,
                                "witness": self.b.witness(p, start=m.start(), end=m.end(), width=12)})
        out.sort(key=lambda r: (dated([r["year"], r["year"]] if r["year"] is not None else None), r["names"]))
        return out[:limit]

    def _candidates(self, found: dict[str, dict[str, tuple[str, float | None, str]]], keys: dict[str, str],
                    limit: int = 20) -> list[dict[str, Any]]:
        """Names the punctuated texts give after 一名/又名/俗呼/今名… (or before 即 a name) that the lexicon lacks."""
        known = set(keys.values())
        lex = self.b.pack.lexicon
        own_ids = {e.term_id for k in known for e, _ in lex.lookup(k)}
        other_names = _OtherNames(lex, own_ids)  # another entry's name (…即六君子汤) is not a name of this one
        counts: Counter = Counter()
        works: dict[str, set[str]] = defaultdict(set)
        first: dict[str, tuple[Any, str]] = {}
        for form, rows in found.items():
            k = re.escape(keys[form])
            after = re.compile(k + r"[，,]?" + _EQUATE + r"[，,]?([㐀-鿿]{2,4})(?=[，。；、：）)」』\s]|$)")
            before = re.compile(r"(?:^|[，。；：、\s])([㐀-鿿]{2,4})[，,]?(?:一名|又名|亦名|即是|即)" + k)
            for pid, (bid, year, text) in rows.items():
                norm = self.b.normalize(text)
                if not re.search(r"[，。；]", norm):
                    continue  # 白文: where a name ends cannot be read
                names = {m.group(1) for m in list(after.finditer(norm)) + list(before.finditer(norm))}
                for name in names:
                    if name in known or name[0] in _EDGE or name[-1] in _EDGE or any(name in kk or kk in name for kk in known) \
                            or name in other_names:
                        continue
                    counts[name] += 1
                    works[name].add(self._work(bid))
                    key = (dated([year, year] if year is not None else None), pid)
                    if name not in first or key < first[name][0]:
                        first[name] = (key, pid)
        out = []
        for name, n in counts.most_common():
            if len(works[name]) < 2 and n < 3:
                continue
            p = self.b.passages([first[name][1]])[0]
            i = self.b.normalize(p.text).find(name)
            out.append({"name": name, "passages": n, "works": len(works[name]),
                        "first": self.b.witness(p, start=max(0, i), end=max(0, i) + len(name), width=16)})
            if len(out) >= limit:
                break
        return out


class _OtherNames:
    """``name in other_names``: the name belongs to another lexicon entry."""

    def __init__(self, lex: Any, own_ids: set[str]) -> None:
        self.lex, self.own = lex, own_ids

    def __contains__(self, name: str) -> bool:
        ids = {e.term_id for e, _ in self.lex.lookup(name)}
        return bool(ids) and not ids & self.own


__all__ = ["NameStudy"]
