"""经文互见·集注 — every place a passage recurs in the corpus, in date order, with its variant readings.

A clause of a classic is transmitted in other witnesses of the same work (同书异本), quoted by later authors
(引文: 经曰…, 仲景云…, 《千金》…) and restated without attribution (互见/化用).  The concordance finds them all:

1. probes — short runs of the query's normalised characters (the full-text index does not cross punctuation, so a
   probe is kept short enough to fall inside a clause of a punctuated witness);
2. candidates — passages hit by enough probes, the rarest probes first;
3. local alignment of the query with each candidate (Han characters only, after variant normalisation, so 异体字
   do not count as differences), keeping those that cover enough of the query;
4. a 校勘记 (apparatus): for each place where witnesses differ from the base text — the query passage, or the
   earliest witness — the readings and the witnesses that have them.
"""

from __future__ import annotations

import difflib
import re
from collections import defaultdict
from typing import Any

from ..collation.impact import classify
from .base import StudyBase, dated, han_only

PROBE = 4
MAX_PROBE_HITS = 40000  # a probe that common says nothing about the query
_MARKER = re.compile(r"(《[^》]{1,14}》(?:云|曰|言|称|谓)?|(?:经|论|书|方|注|又|故|古人|前人|先哲|先贤)(?:曰|云|言)|所谓|"
                     r"[一-鿿]{1,3}(?:曰|云))[：:，,]?[“「『]?$")


# speakers of the dialogues inside the classics: their 曰 does not quote another text
_DIALOGUE = re.compile(r"(^|[^\u4e00-\u9fff])?(问|問|答|或|师|師)[對对]?(?:曰|云)$")


class Concordance:
    def __init__(self, base: StudyBase) -> None:
        self.b = base

    # ------------------------------------------------------------ probes and candidates
    def _probes(self, han: str) -> list[str]:
        n = len(han)
        if n <= PROBE:
            return [han]
        step = max(2, (n - PROBE) // 11 + 1)
        probes = [han[i: i + PROBE] for i in range(0, n - PROBE + 1, step)]
        if han[-PROBE:] not in probes:
            probes.append(han[-PROBE:])
        return list(dict.fromkeys(probes))

    @staticmethod
    def _segment_probes(norm: str) -> list[str]:
        """Probes inside the query's own punctuation (太阳病，发热，汗出 …): the index does not cross a mark, so a clause
        of short segments is found in punctuated witnesses only through probes that stay within one segment."""
        out: list[str] = []
        for seg in re.split(r"[^\u3400-\u9fff\U00020000-\U0003134f〇〓]+", norm):
            if len(seg) >= 3:
                out += [seg[i: i + PROBE] for i in range(0, max(1, len(seg) - PROBE + 1))]
        return list(dict.fromkeys(out))

    def _candidates(self, han: str, exclude: str | None, max_candidates: int, norm: str = "") -> tuple[list[str], list[str]]:
        corpus = self.b.corpus
        large = getattr(corpus, "large", False)
        hits: dict[str, int] = defaultdict(int)
        used: list[tuple[int, str]] = []
        inner: list[tuple[int, str]] = []
        segs = [x for x in self._segment_probes(norm) if len(x) < len(han)] if norm else []
        for probe in dict.fromkeys(self._probes(han) + segs):
            n = corpus.count(probe) if large else len(self.b.find(probe))
            if 0 < n <= MAX_PROBE_HITS:
                (inner if probe in segs else used).append((n, probe))
        used.sort()
        inner.sort()
        used = used[:8] + inner[:5]  # the rarest probes carry the evidence (and some that 白文 does not need)
        for _, probe in used:
            ids = corpus.contains(probe, verify=False) if large else self.b.find(probe)
            for pid in ids:
                hits[pid] += 1
        need = 1 if len(used) <= 2 else 2
        ranked = sorted((pid for pid, k in hits.items() if k >= need and pid != exclude), key=lambda pid: (-hits[pid], pid))
        return ranked[:max_candidates], [p for _, p in used]

    # ------------------------------------------------------------ alignment
    @staticmethod
    def _align(q: str, t: str) -> tuple[float, int, int, list[tuple[int, int, int]]]:
        """(coverage of q, start, end in t, matching blocks) for the best local alignment of q inside t."""
        if not q or not t:
            return 0.0, 0, 0, []
        # crop t around the exact occurrences of q's probes, so long passages align quickly
        pos = [m for i in range(0, max(1, len(q) - PROBE + 1), max(1, PROBE // 2)) for m in [t.find(q[i: i + PROBE])] if m >= 0]
        lo = max(0, min(pos) - len(q)) if pos else 0
        hi = min(len(t), max(pos) + 2 * len(q)) if pos else min(len(t), 4 * len(q))
        window = t[lo:hi]
        sm = difflib.SequenceMatcher(None, q, window, autojunk=False)
        blocks = [b for b in sm.get_matching_blocks() if b.size >= 2]
        if not blocks:
            return 0.0, 0, 0, []
        # the densest run of blocks whose extent stays close to the query's length
        best = (0, 0, 0)
        for i in range(len(blocks)):
            matched = 0
            for j in range(i, len(blocks)):
                start, end = blocks[i].b, blocks[j].b + blocks[j].size
                if end - start > 1.6 * len(q) + 8:
                    break
                matched += blocks[j].size
                if matched > best[0]:
                    best = (matched, i, j)
        matched, i, j = best
        chosen = [(b.a, b.b + lo, b.size) for b in blocks[i: j + 1]]
        start, end = chosen[0][1], chosen[-1][1] + chosen[-1][2]
        return matched / len(q), start, end, chosen

    # ------------------------------------------------------------ main
    def run(self, text: str | None = None, passage_id: str | None = None, *, min_coverage: float = 0.6,
            max_candidates: int = 4000, limit: int = 300) -> dict[str, Any]:
        b = self.b
        query_passage = b.corpus.passage(passage_id) if passage_id else None
        raw = text if text else (query_passage.text if query_passage else "")
        norm = b.normalize(raw)
        q, _ = han_only(norm)
        if len(q) < 4:
            raise ValueError("the passage to trace needs at least four characters")
        q = q[:400]
        candidates, probes = self._candidates(q, passage_id, max_candidates, norm)
        hits: list[dict[str, Any]] = []
        for p in b.passages(candidates):
            pn = b.normalize(p.text)
            t, index = han_only(pn)
            coverage, s, e, blocks = self._align(q, t)
            if coverage < min_coverage:
                continue
            start, end = index[s], index[e - 1] + 1
            w = b.witness(p, start=start, end=end, width=0)
            w["quote"] = p.text[start:end]
            w["coverage"] = round(coverage, 3)
            w["aligned"] = t[s:e]
            before = p.text[max(0, start - 16): start]
            marker = _MARKER.search(before.rstrip("　 "))
            found = marker.group(0) if marker and not _DIALOGUE.search(marker.group(0)) else ""
            w["marker"] = re.sub(r"^.*?(《[^》]+》|[經经](?=[曰云言])|所谓)", r"\1", found) if found else ""
            w["before"] = before
            hits.append(w)
        base_work = None
        if query_passage is not None:
            book = b.corpus.books.get(query_passage.book_id)
            base_work = getattr(book, "work", None) or query_passage.book_id
        else:  # the earliest full witness stands for the text
            full = sorted((w for w in hits if w["coverage"] >= 0.95), key=lambda w: (dated(w["years"]), w["passage_id"]))
            if full:
                base_work = full[0]["work"] or full[0]["book_id"]
        for w in hits:
            same = base_work is not None and (w["work"] or w["book_id"]) == base_work
            w["relation"] = "同书异本" if same else ("引文" if w["marker"] else "互见")
        hits.sort(key=lambda w: (dated(w["years"]), -w["coverage"], w["passage_id"]))
        hits = hits[:limit]
        if query_passage is not None:
            base = b.witness(query_passage, quote=raw[:200])
            base_text = q
        else:
            full = [w for w in hits if w["coverage"] >= 0.95]
            base = dict(full[0]) if full else {"quote": raw}
            base_text = full[0]["aligned"] if full else q
        apparatus = self._apparatus(base_text, hits, base)
        for a in apparatus:  # 异文分级
            a.update(classify(a["base"], a["reading"], a["context"].replace(a["base"], "〔" + a["base"] + "〕", 1)
                              if a["base"] else a["context"], b.pack.lexicon, kind="transposition" if a["kind"] == "倒" else None))
        works = {w["work"] or w["book_id"] for w in hits}
        periods: dict[str, int] = defaultdict(int)
        for w in hits:
            periods[w["period"] or "未定"] += 1
        return {
            "query": raw[:400], "normalized": q, "probes": probes, "candidates": len(candidates),
            "base": base, "base_work": base_work, "hits": hits, "apparatus": apparatus,
            "summary": {"witnesses": len(hits), "books": len({w['book_id'] for w in hits}), "works": len(works),
                        "earliest": hits[0] if hits else None, "by_period": dict(periods),
                        "by_relation": {k: sum(1 for w in hits if w["relation"] == k) for k in ("同书异本", "引文", "互见")}},
        }

    @staticmethod
    def _apparatus(base: str, hits: list[dict[str, Any]], base_witness: dict[str, Any]) -> list[dict[str, Any]]:
        """Variant readings against the base text: (base span, reading) → witnesses.  Only witnesses that transmit
        the text (another copy of the work, or an explicit quotation) with most of it are collated; differences
        longer than a few characters are interleaved commentary, not variant readings."""
        places: dict[tuple[int, int, str], dict[str, Any]] = {}
        for w in hits:
            if w.get("passage_id") == base_witness.get("passage_id") or w["coverage"] < 0.8 or w["relation"] == "互见" \
                    and w["coverage"] < 0.95:
                continue
            sm = difflib.SequenceMatcher(None, base, w["aligned"], autojunk=False)
            ops = sm.get_opcodes()
            # ignore differences at the edges (the alignment may start or stop a character early)
            inner = [op for k, op in enumerate(ops) if not (op[0] != "equal" and (k == 0 or k == len(ops) - 1))]
            for tag, i1, i2, j1, j2 in _transpositions(inner, base, w["aligned"]):
                if tag == "equal" or max(i2 - i1, j2 - j1) > 6:
                    continue
                reading = w["aligned"][j1:j2]
                key = (i1, i2, reading)
                entry = places.setdefault(key, {"at": i1, "base": base[i1:i2], "reading": reading,
                                                "kind": {"replace": "异文", "delete": "脱", "insert": "衍", "transpose": "倒"}[tag],
                                                "context": base[max(0, i1 - 4): i2 + 4], "witnesses": []})
                entry["witnesses"].append(w["title"])
        out = sorted(places.values(), key=lambda e: (e["at"], -len(e["witnesses"])))
        for e in out:
            e["witnesses"] = sorted(dict.fromkeys(e["witnesses"]))
        return out


def _transpositions(ops: list[tuple], a: str, b: str) -> list[tuple]:
    """Merge an insertion and a deletion of the same characters a few places apart into one 倒文 (食饮 → 饮食)."""
    out: list[tuple] = []
    k = 0
    while k < len(ops):
        op = ops[k]
        if k + 2 < len(ops) and ops[k + 1][0] == "equal" and ops[k + 1][2] - ops[k + 1][1] <= 3:
            nxt = ops[k + 2]
            first = b[op[3]:op[4]] if op[0] == "insert" else a[op[1]:op[2]]
            second = a[nxt[1]:nxt[2]] if nxt[0] == "delete" else b[nxt[3]:nxt[4]]
            if {op[0], nxt[0]} == {"insert", "delete"} and first and first == second:
                out.append(("transpose", op[1], nxt[2], op[3], nxt[4]))
                k += 3
                continue
        out.append(op)
        k += 1
    return out


__all__ = ["Concordance"]
