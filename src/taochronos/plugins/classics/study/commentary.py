"""集注 — the commentaries on a clause, gathered from the commentary literature, aligned and compared.

A clause of a classic is explained again and again: 成无己 in 1144, 方有执 in 1592, 喻昌 in 1648, 张志聪 in 1683 …
Their books lay the text out in the same way — the clause (the lemma), then the commentary on it, then the next
clause — though some run the commentary on in the clause's own paragraph, some print it in brackets inside the
clause, and the Kanripo transcriptions keep it as rows anchored to the clause.  ``study commentaries``

1. finds the clause across the corpus (the concordance);
2. keeps the witnesses where the clause heads its passage (a clause quoted inside a longer passage is a quotation,
   not the lemma of a commentary) and gathers what follows it: the rest of its paragraph, the notes in brackets
   inside it, the rows after it — up to the next clause of the base text (a row made mostly of base text that is
   not this clause), at most a few rows;
3. names the commentator (the layer's attribution, else the book's authors) and dates the commentary (its layer);
4. reads each commentary for the concepts it brings (the lexicon and the vocabulary of exegesis in
   ``exegesis.yaml``: 六经, 脏腑经络, 表里, 营卫气血, 六气, 传变, 学说, 治法 — those of the clause itself left out),
   the commentators it names and its stance towards them (a rejection or an approval word in the sentence after
   the name), the books it cites;
5. compares them in date order: explicit relations (驳 rejects, 从 endorses, 引 cites a predecessor by name),
   shared wording (照录 copies, 承袭 takes over), and relations of content from the concepts they add (同解 the same
   reading, 增益 extends an earlier reading, 异解 a different one); the concepts most commentaries share (共识)
   and those only one has (独见), and who first brought each concept to the clause.

Relations of content are computed from shared concepts and wording, not read: they point to what to compare, and
the quotes are there to check.  驳 and 从 need a named predecessor and a marker word — a commentator who disagrees
without naming anyone is found only as 异解.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from typing import Any

from .base import StudyBase, dated, han_only

NOTE = re.compile(r"（[^（）]{1,300}）|\([^()]{1,300}\)")
APPARATUS_ONLY = re.compile(r"^(?:[一-鿿]{0,4}(?:一作|一云|又作|或作|音|切|反|读若|同)[一-鿿]{0,6})+$")
PIECE = re.compile(r"（[^（）]{1,300}）[。，；]?|\([^()]{1,300}\)[。，；]?|[^（(。？！]+[。？！]?|[。？！]")
LEAD = re.compile(r"^(?:又曰|又云|又|原文|[一二三四五六七八九十百零〇]+)")
QUOTING = re.compile(r"^[^，。；：、]{0,6}(?:曰|云)")  # 经曰, 难经云: a commentary quoting its sources
FOLD = str.maketrans("荣", "营")
_DYNASTY = re.compile(r"^[^·]{1,5}·")
_TRIM = re.compile(r"[《（(].*$|等$|^旧题")
_DIRECT = re.compile(r"(?:曰|云)$")


def mask(han: str, base: set[str], k: int, sign: str) -> str:
    """The characters of a text that belong to runs of the base text (every k-gram in it) replaced by a sign."""
    hidden = [False] * len(han)
    for i in range(len(han) - k + 1):
        if han[i: i + k] in base:
            for j in range(i, i + k):
                hidden[j] = True
    return "".join(sign if h else ch for ch, h in zip(han, hidden))


def grams(text: str, k: int) -> set[str]:
    return {text[i: i + k] for i in range(len(text) - k + 1)} if len(text) >= k else ({text} if text else set())


def clean_name(name: str) -> str:
    """A commentator's name from an attribution (明·方有执 → 方有执, 唐步祺《伤寒恒论阐释》 → 唐步祺)."""
    return _TRIM.sub("", _DYNASTY.sub("", name.strip())).strip()


class Exegesis:
    """The data of ``exegesis.yaml``, normalised: the vocabulary of exegesis, the stance markers, the gloss forms."""

    def __init__(self, base: StudyBase) -> None:
        data = base.data("exegesis.yaml")
        norm = base.normalize
        self.forms: dict[str, str] = {}
        self.group: dict[str, str] = {}
        for c in data.get("concepts") or []:
            self.group[c["id"]] = c.get("group", "")
            for f in c.get("forms") or []:
                self.forms.setdefault(norm(f), c["id"])
        self.longest = max((len(f) for f in self.forms), default=1)
        stance = data.get("stance") or {}
        self.reject = re.compile("|".join(f"(?:{x})" for x in stance.get("reject") or ["(?!)"]))
        self.endorse = re.compile("|".join(f"(?:{x})" for x in stance.get("endorse") or ["(?!)"]))
        self.report = stance.get("report") or "(?:曰|云|谓)"
        self.refer = re.compile(stance.get("refer") or "(?!)")
        self.hypothetical = re.compile(stance.get("hypothetical") or "(?!)")
        self.others = re.compile(stance.get("others") or "(?!)")
        self.acts = re.compile(stance.get("acts") or "(?!)")
        self.glosses = [(g["kind"], re.compile(g["pattern"])) for g in data.get("glosses") or []]

    def concepts(self, norm: str) -> dict[str, int]:
        """Concept id → occurrences in a normalised text (longest form first, left to right)."""
        out: Counter = Counter()
        i, n = 0, len(norm)
        while i < n:
            for length in range(min(self.longest, n - i), 1, -1):
                cid = self.forms.get(norm[i: i + length])
                if cid:
                    out[cid] += 1
                    i += length
                    break
            else:
                i += 1
        return dict(out)

    def stance(self, window: str, *, direct: bool, names: Any = None) -> tuple[str | None, str, int]:
        """The stance the author takes towards the view just reported — 'reject', 'endorse' or None — with the marker
        and its place in the window.  After a direct quotation (曰, 云) the quoted words are not the author's: in
        quotation marks only a marker after the closing mark counts, without them only one in a phrase that refers
        back to the quoted view (此说非也).  After an indirect report any marker counts, but not one in a hypothetical
        (若作阴冷看，误矣), nor one after the author has turned to others (近世之医 … 是未达)."""
        begin = 0
        quoted = direct and window[:2].strip("：:，, 　")[:1] in ("「", "“", "『")
        if quoted:
            close = min((i for i in (window.find("」"), window.find("”"), window.find("』")) if i > 0), default=-1)
            if close < 0:
                return None, "", -1
            begin = close + 1
        hits: list[tuple[int, str, str]] = []
        for kind, rx in (("reject", self.reject), ("endorse", self.endorse)):
            for m in rx.finditer(window, begin):
                if direct and not quoted and not self.refer.search(window[max(0, m.start() - 10): m.start() + 2]):
                    continue
                if self.hypothetical.search(window[max(begin, m.start() - 12): m.start()]):
                    continue
                if self.others.search(window[begin: m.start()]):
                    continue
                if m.start() and window[m.start() - 1] in "不非未无毋勿岂" and window[max(0, m.start() - 2): m.start()] not in (
                        "鲜不", "无不", "莫不", "罔不"):  # 良不谬也 denies the marker; 鲜不误矣 affirms it
                    continue
                if names is not None and not self.acts.fullmatch(m.group(0)) and names.search(window[begin: m.start()]):
                    continue  # another physician named in between: the verdict is likely about him
                hits.append((m.start(), kind, m.group(0)))
        if not hits:
            return None, "", -1
        pos, kind, marker = min(hits)
        return kind, marker, pos


class Commentators:
    """Named predecessors in a commentary: the physicians of ``physicians.yaml`` (and 氏 forms) followed by a word that
    reports their view (曰, 谓, 以为, 之说 …), with the stance of the sentence that follows."""

    LOOSE = {"仲景", "长沙", "东垣", "丹溪", "河间", "景岳", "叔和", "思邈", "时珍", "洁古", "海藏", "子和", "戴人", "天士", "嘉言",
             "韵伯", "修园", "鞠通", "孟英", "灵胎", "洄溪", "濒湖", "立斋", "仲淳", "士材", "隐庵", "石顽", "讱庵", "容川",
             "成氏", "成注", "方氏", "喻氏", "柯氏", "尤氏", "中行", "郊倩", "卿子"}

    def __init__(self, base: StudyBase, exegesis: Exegesis) -> None:
        self.b = base
        self.ex = exegesis
        self.persons = {p["id"]: p for p in base.data("physicians.yaml").get("persons") or []}
        norm = base.normalize
        self.alias: dict[str, str] = {}
        loose, strict = [], []
        for pid, p in self.persons.items():
            for name in p.get("names") or []:
                key = norm(name)
                self.alias[key] = pid
                (loose if len(key) >= 3 or key in {norm(x) for x in self.LOOSE} else strict).append(key)

        def alt(names: list[str]) -> str:
            return "|".join(map(re.escape, sorted(set(names), key=len, reverse=True))) or "(?!)"

        report = exegesis.report
        self._loose = re.compile(rf"({alt(loose)})({report})")
        self._strict = re.compile(rf"(?:^|(?<=[。，；：、\s　（(「『“]))({alt(strict)})({report})")
        self._any = re.compile(alt([k for k in self.alias if len(k) >= 2]))

    def person_of(self, names: list[str]) -> str | None:
        for name in names:
            pid = self.alias.get(self.b.normalize(clean_name(name)))
            if pid:
                return pid
        return None

    def name(self, pid: str) -> str:
        return self.persons.get(pid, {}).get("name", pid)

    def cited(self, norm: str, *, own: str | None = None) -> list[dict[str, Any]]:
        """Named predecessors in a normalised text, with the stance of the sentence after each and its words."""
        out: list[dict[str, Any]] = []
        found = sorted({(m.start(1), m.end(1), m.end(2), m.group(1), m.group(2)) for rx in (self._loose, self._strict)
                        for m in rx.finditer(norm)})
        for start, _end_name, end, name, verb in found:
            pid = self.alias.get(name)
            if not pid or pid == own:
                continue
            rest = norm[end: end + 160]
            ends = [m.end() for m in re.finditer(r"[。？！]", rest)]
            window = rest[: ends[1] if len(ends) > 1 else (ends[0] if ends else len(rest))]
            kind, marker, pos = self.ex.stance(window, direct=bool(_DIRECT.search(verb)) or norm[end: end + 1] in ("曰", "云"),
                                               names=self._any)
            by = None
            if kind and pos > 0 and self.ex.acts.fullmatch(marker):  # 景岳驳之: the one who rejects is named before the act
                named = [m for m in self._any.finditer(window[max(0, pos - 6): pos])]
                if named and self.alias.get(named[-1].group(0)) not in (None, pid):
                    by = self.alias[named[-1].group(0)]
            out.append({"person": pid, "name": self.name(pid), "stance": kind, "marker": marker,
                        "reported_by": by, "quote": norm[start: end + len(window)][:120]})
        return out


class CommentaryStudy:
    THEORY = ("pathogenesis", "pattern", "concept", "organ", "etiology", "treatment_principle", "treatment_method")
    K = 4  # base-text grams: short enough to see a clause through its variants

    def __init__(self, base: StudyBase, concordance: Any) -> None:
        self.b = base
        self.conc = concordance
        self.ex = Exegesis(base)
        self.people = Commentators(base, self.ex)
        self._base_grams: dict[str, set[str]] = {}
        self._in_clause: set[str] = set()
        self._explains = re.compile("|".join(f"(?:{x})" for x in base.data("intertext.yaml").get("interpretation") or ["(?!)"]))

    # ------------------------------------------------------------ the base text
    def _base_witness(self, work: str) -> str | None:
        """The witness of the base work whose main text stands for it: the one with the most main-layer text (a
        commentary edition's text is in its own layer, so it does not count)."""
        best: tuple[int, str] | None = None
        for bid, book in self.b.corpus.books.items():
            if (book.work or bid) != work:
                continue
            size = self._main_size(bid)
            if size and (best is None or (size, bid) > best):
                best = (size, bid)
        return best[1] if best else None

    def _main_size(self, book_id: str) -> int:
        store = getattr(self.b.corpus, "store", None)
        if store is not None:
            with store.lock:
                row = store.db.execute("SELECT COALESCE(SUM(LENGTH(text)), 0) FROM passages WHERE book_id=? AND layer='正文'",
                                       (book_id,)).fetchone()
            return int(row[0] or 0)
        return sum(len(p.text) for p in self.b.corpus.passages(book_ids=[book_id]) if not _layered(p))

    def base_grams(self, work: str | None) -> set[str]:
        """4-grams of the base work's main text, notes left out (a stretch made mostly of them is another clause)."""
        if not work:
            return set()
        if work not in self._base_grams:
            bid = self._base_witness(work)
            out: set[str] = set()
            if bid:
                store = getattr(self.b.corpus, "store", None)
                if store is not None:
                    with store.lock:
                        texts = [r[0] for r in store.db.execute(
                            "SELECT text FROM passages WHERE book_id=? AND layer='正文' ORDER BY rid", (bid,))]
                else:
                    texts = [p.text for p in self.b.corpus.passages(book_ids=[bid]) if not _layered(p)]
                for t in texts:
                    out |= grams(self._core(t), self.K)
            self._base_grams[work] = out
        return self._base_grams[work]

    def _core(self, text: str) -> str:
        """The normalised Han characters of a stretch without its notes and a leading number or speaker (又曰, 二)."""
        core = NOTE.sub("", text)
        han = han_only(self.b.normalize(core))[0]
        return LEAD.sub("", han)

    # ------------------------------------------------------------ one commentary
    def _extra(self, pid: str) -> dict[str, Any]:
        store = getattr(self.b.corpus, "store", None)
        if store is None:
            return {}
        with store.lock:
            row = store.db.execute("SELECT extra FROM passages WHERE id=?", (pid,)).fetchone()
        return json.loads(row[0]) if row and row[0] else {}

    def reading(self, concepts: dict[str, int] | list[str]) -> list[str]:
        """The concepts that interpret (the vocabulary of exegesis and the lexicon's theory), not the findings."""
        out = []
        for c in concepts:
            if c in self.ex.group:
                out.append(c)
                continue
            entry = self.b.pack.lexicon.resolve(c)
            if entry is not None and entry.category in self.THEORY:
                out.append(c)
        return sorted(out)

    def explains(self, norm: str) -> bool:
        return bool(self._explains.search(norm))

    def _is_clause(self, text: str, bgrams: set[str], cgrams: set[str]) -> bool:
        """A stretch of base text that is not this clause — the next clause, even in another witness's wording."""
        core = self._core(text)
        if len(core) < 4:
            return False
        g = grams(core, self.K)
        share = (len(g & bgrams) - len(g & cgrams)) / len(g)
        if share >= 0.5:
            return True
        norm = self.b.normalize(NOTE.sub("", text))
        return share >= 0.3 and not self.interprets(norm)

    def interprets(self, norm: str) -> bool:
        """Whether a stretch explains: a concept of interpretation beyond the clause's own, or an explaining turn."""
        return bool(self.reading(set(self.concepts(norm)) - self._in_clause)) or self.explains(norm)

    def _opens_with_clause(self, text: str, bgrams: set[str], cgrams: set[str]) -> bool:
        """Whether a row begins with the next clause (the clause, then its own commentary run on after it)."""
        head = next((m.group(0) for m in PIECE.finditer(text) if m.group(0).strip("。，；：、 　")), "")
        if not head or NOTE.fullmatch(head.strip("。，；：、 　")):
            return False
        if QUOTING.match(self.b.normalize(head)) and not LEAD.match(self.b.normalize(head)):
            return False  # the commentary quoting its sources (经曰：尺寸俱浮者 …), not the next clause
        if not re.search(r"[。？！]", head):  # 白文: the first clause-length stretch
            head = han_only(head)[0][:20]
        return self._is_clause(head, bgrams, cgrams)

    def _run_on(self, text: str, bgrams: set[str], cgrams: set[str]) -> str:
        """The commentary run on after the clause in its paragraph — its notes and sentences — up to the next clause
        of the base text (a 白文 paragraph of clause, note, clause, note … stops at the second clause)."""
        out = []
        for m in PIECE.finditer(text):
            s = m.group(0)
            if not s.strip("。，；：、 　"):
                if out:
                    out.append(s)
                continue
            if not NOTE.fullmatch(s.strip("。，；：、 　")) and self._is_clause(s, bgrams, cgrams):
                break
            out.append(s)
        return "".join(out)

    def _lemma(self, p: Any, start: int, end: int, clause: str, bgrams: set[str]) -> bool:
        """Whether the clause heads a unit of its passage and the passage carries it as a whole — at the start (a number
        or 又曰 may come before it), after the note that closes the previous clause (白文 of clause, note, clause, note),
        or after the previous clauses of the base text — and not quoted inside a longer passage, where it is a
        quotation, not the lemma of a commentary."""
        span = han_only(NOTE.sub("", p.text[start:end]))[0]
        if len(span) > 1.4 * len(clause) + 4:
            return False
        before = p.text[:start].rstrip("　 ")
        if len(LEAD.sub("", han_only(self.b.normalize(before))[0])) <= 2 or before.endswith(("）", ")")):
            return True
        last = re.split(r"[。？！]", before.rstrip("。？！"))[-1] if before.endswith(("。", "？", "！")) else ""
        return bool(last) and self._is_clause(last, bgrams, set())

    def units(self, p: Any, hit: dict[str, Any], clause: str, bgrams: set[str], *, max_rows: int = 4,
              max_chars: int = 1200) -> list[dict[str, Any]] | None:
        """The commentaries on a clause in one witness — one per voice (a Kanripo 素问 row has 王冰's note and the
        新校正 after it) — or None when the clause does not head its passage (a quotation)."""
        start, end = hit.get("span") or (0, len(p.text))
        if not self._lemma(p, start, end, clause, bgrams):
            return None
        cgrams = grams(clause, self.K)
        pieces: list[tuple[str, Any, str]] = []
        notes = "".join(m.group(0) for m in NOTE.finditer(p.text[start:end]))
        if len(han_only(notes)[0]) >= 4:
            pieces.append(("inline", p, notes))
        after = p.text[end:]
        rest = self._run_on(after, bgrams, cgrams)
        if len(han_only(rest)[0]) >= 4:
            pieces.append(("run_on", p, rest))
        taken = sum(len(han_only(t)[0]) for _, _, t in pieces)
        cut = len(han_only(after)[0]) - len(han_only(rest)[0]) >= 4  # the paragraph went on into the next clause
        for q in ([] if cut else self.b.following(p, max_rows)):
            if q.kind in ("toc", "preface"):
                break
            anchored = self._extra(q.id).get("anchor") == p.id
            if not anchored and (self._is_clause(q.text, bgrams, cgrams) or self._opens_with_clause(q.text, bgrams, cgrams)):
                break
            han = han_only(self.b.normalize(q.text))[0]
            if pieces and taken + len(han) > max_chars:
                break
            pieces.append(("anchored" if anchored else "row", q, q.text))
            taken += len(han)
        if not pieces:
            return []
        voices: dict[str, list[tuple[str, Any, str]]] = defaultdict(list)
        lemma_layer = _layer(p)
        for piece in pieces:
            q = piece[1]
            ex = self._extra(q.id) if q.id != p.id else {}
            voice = ex.get("attribution") or (_layer(q) if _layer(q) != lemma_layer else "")
            voices[voice].append(piece)
        book = self.b.corpus.books.get(p.book_id)
        out = []
        for voice, group in voices.items():
            body = "".join(t for _, _, t in group)
            han = han_only(self.b.normalize(body))[0]
            if len(han) < 8 or APPARATUS_ONLY.match(han):
                continue
            norm_body = self.b.normalize(body)
            concepts = self.concepts(norm_body)
            if not self.interprets(norm_body):
                continue  # nothing that explains: the next clauses of another arrangement, not a commentary
            first = group[0][1]
            if voice:
                names = [clean_name(voice[:-1] if voice.endswith(("注", "解", "按")) and "·" not in voice else voice)]
            else:
                names = [clean_name(a) for a in (book.authors if book else [])]
            names = [n for n in names if n]
            person = self.people.person_of(names)
            years = self.b.years(first)
            per = self.b.period_of(self.b.year(first))
            out.append({
                "commentator": "、".join(names) or (book.title if book else p.book_id), "person": person,
                "book_id": p.book_id, "title": book.title if book else p.book_id,
                "work": (book.work if book else None) or p.book_id, "voice": voice or _layer(first),
                "years": list(years) if years else None, "period": per.label if per else None,
                "lemma": self.b.witness(p, start=start, end=end, width=0) | {"quote": p.text[start:end][:120]},
                "passage_ids": list(dict.fromkeys(q.id for _, q, _ in group)), "layout": [k for k, _, _ in group],
                "quote": body.strip("。，；： 　")[:160], "text": body.strip(), "chars": len(han), "concepts": concepts,
                "cites": self.people.cited(norm_body, own=person),
                "books_cited": sorted(set(re.findall(r"《([^》]{1,14})》", body))), "_han": han.translate(FOLD),
            })
        return out

    def concepts(self, norm: str) -> dict[str, int]:
        """Concepts of a normalised text: the vocabulary of exegesis, then the lexicon's terms (by their names)."""
        out = dict(self.ex.concepts(norm))
        for m in self.b.pack.lexicon.match(norm, include_weak=False):
            if m.category in ("herb", "formula", "condition"):
                continue
            out[m.entry.term] = out.get(m.entry.term, 0) + 1
        return out

    # ------------------------------------------------------------ all commentaries on a clause
    def run(self, text: str | None = None, passage_id: str | None = None, *, max_rows: int = 4, max_chars: int = 1200,
            limit: int = 60) -> dict[str, Any]:
        conc = self.conc.run(text, passage_id, min_coverage=0.8, limit=800)
        clause = conc["normalized"]
        base_work = conc.get("base_work")
        bgrams = self.base_grams(base_work)
        in_clause = set(self.concepts(self.b.normalize(conc["query"])))
        self._in_clause = in_clause
        units: list[dict[str, Any]] = []
        quotations: list[dict[str, Any]] = []
        used: set[str] = set()
        for hit in conc["hits"]:
            if hit["passage_id"] in used:
                continue
            p = self.b.corpus.passage(hit["passage_id"])
            if p is None:
                continue
            found = self.units(p, hit, clause, bgrams, max_rows=max_rows, max_chars=max_chars)
            if found is None:
                quotations.append({k: hit.get(k) for k in ("passage_id", "title", "years", "period", "locator", "quote")})
                continue
            for u in found:
                used.update(u["passage_ids"])
                u["added"] = sorted(set(u["concepts"]) - in_clause)
                u["reading"] = self.reading(u["added"])
                units.append(u)
        units = self._one_per_commentary(units)
        for u in units:  # wording shared because both quote the base text is not wording taken over
            u["_masked"] = mask(u["_han"], bgrams, self.K, "◇")
        units.sort(key=lambda u: (dated(u["years"]), u["book_id"]))
        units = units[:limit]
        for k, u in enumerate(units, 1):
            u["id"] = f"C{k}"
        relations = self.relations(units)
        counts = Counter(c for u in units for c in u["reading"])
        n = len(units)
        consensus = [{"concept": c, "group": self.ex.group.get(c, "lexicon"), "commentaries": k}
                     for c, k in counts.most_common() if n >= 3 and k >= max(2, math.ceil(n / 2))]
        unique = [{"concept": c, "group": self.ex.group.get(c, "lexicon"), "commentary": u["id"], "commentator": u["commentator"]}
                  for u in units for c in u["reading"] if counts[c] == 1]
        first: dict[str, dict[str, Any]] = {}
        for u in units:
            for c in u["reading"]:
                first.setdefault(c, {"concept": c, "group": self.ex.group.get(c, "lexicon"), "commentary": u["id"],
                                     "commentator": u["commentator"], "years": u["years"], "followed_by": counts[c] - 1})
        for u in units:
            u.pop("_han", None)
            u.pop("_masked", None)
        return {
            "clause": conc["query"], "normalized": clause, "base_work": base_work, "concepts_in_clause": sorted(in_clause),
            "commentaries": units, "count": n, "relations": relations, "consensus": consensus, "unique": unique[:80],
            "first_readings": sorted(first.values(), key=lambda r: (-r["followed_by"], r["commentary"]))[:60],
            "quotations": quotations[:40], "quotation_count": len(quotations),
            "note": "relations of content (同解, 增益, 异解) and wording (照录, 承袭) are computed, not read: check the quotes; "
                    "驳 and 从 need a named predecessor and a marker word in the sentence after the name",
        }

    def _one_per_commentary(self, units: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Transcriptions of one commentary (several copies of 伤寒论条辨) are one commentary.  The copy that stands for
        it is one whose commentary is a layer of its own (the transcription marked where it begins and ends), else the
        copy of middle length (the longest may have run on into the next clause's commentary)."""
        groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for u in units:
            groups[(u["work"], u["commentator"])].append(u)
        out = []
        for members in groups.values():
            members.sort(key=lambda u: (u["chars"], u["book_id"]))
            layered = [u for u in members if "·" in u["voice"] or set(u["layout"]) <= {"row", "anchored"} and u["voice"] != "正文"
                       and self._explicit(u)]
            chosen = layered[0] if layered else members[(len(members) - 1) // 2]
            best = dict(chosen)
            members = [best] + [m for m in members if m is not chosen]
            best["copies"] = [{"book_id": m["book_id"], "title": m["title"], "passage_id": m["lemma"]["passage_id"]}
                              for m in members[1:]]
            out.append(best)
        return out

    def _explicit(self, u: dict[str, Any]) -> bool:
        """Whether a unit's commentary rows are a layer of their own (a commentary layer of the transcription)."""
        return any(t.startswith("layer:") and not t.endswith("）") for pid in u["passage_ids"][:1]
                   for p in [self.b.corpus.passage(pid)] if p is not None for t in p.tags)

    def relations(self, units: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Each later commentary towards each earlier one: explicit (驳, 从, 引), wording (照录, 承袭 — towards the
        earliest source only, not the copies of it in between; 自录 when one commentator repeats himself) and
        content (增益, 同解, 异解 over the concepts each reading adds)."""
        out: list[dict[str, Any]] = []
        g6 = {u["id"]: {g for g in grams(u["_masked"], 6) if "◇" not in g} for u in units}
        for j, b in enumerate(units):
            wording: list[tuple[dict[str, Any], float, int]] = []
            for a in units[:j]:
                if b["years"] and a["years"] and b["years"][1] < a["years"][0]:
                    continue
                pair = {"from": b["id"], "to": a["id"], "from_commentator": b["commentator"], "to_commentator": a["commentator"]}
                for c in b["cites"]:
                    if a["person"] and c["person"] == a["person"]:
                        kind = {"reject": "驳", "endorse": "从"}.get(c["stance"] or "", "引")
                        out.append(pair | {"type": kind, "marker": c["marker"], "evidence": c["quote"]})
                gb = g6[b["id"]]
                share = len(gb & g6[a["id"]]) / len(gb) if gb else 0.0
                bm = b["_masked"].replace("◇", "◉").replace("◆", "◉")  # the masks of two texts never match each other
                am = a["_masked"].replace("◇", "◈").replace("◆", "◈")
                run = SequenceMatcher(None, bm, am, autojunk=False).find_longest_match(0, len(bm), 0, len(am)).size
                if share >= 0.3 or run >= 14:
                    wording.append((a, share, run))
                sa, sb = set(a["reading"]), set(b["reading"])
                same = a["person"] is not None and a["person"] == b["person"]
                if len(sa) >= 3 and len(sb) >= 3 and not same:
                    both = sa & sb
                    jac = len(both) / len(sa | sb)
                    if len(sa) >= 4 and len(both) >= 0.8 * len(sa) and len(sb - sa) >= 2:
                        out.append(pair | {"type": "增益", "shared": sorted(both), "added": sorted(sb - sa)[:12], "jaccard": round(jac, 3)})
                    elif jac >= 0.5:
                        out.append(pair | {"type": "同解", "shared": sorted(both), "jaccard": round(jac, 3)})
                    elif jac <= 0.1 and len(sa) >= 4 and len(sb) >= 4:
                        out.append(pair | {"type": "异解", "a_only": sorted(sa - sb)[:10], "b_only": sorted(sb - sa)[:10],
                                           "jaccard": round(jac, 3)})
            if wording:
                origin = wording[0]  # the earliest carrier of the shared words; a later one only if it carries more
                keep = [origin] + [w for w in wording[1:] if w[1] >= origin[1] + 0.15]
                for a, share, run in keep:
                    kind = "自录" if a["person"] and a["person"] == b["person"] else ("照录" if share >= 0.6 else "承袭")
                    out.append({"from": b["id"], "to": a["id"], "from_commentator": b["commentator"],
                                "to_commentator": a["commentator"], "type": kind, "share": round(share, 3), "longest_run": run})
        order = {"驳": 0, "从": 1, "引": 2, "照录": 3, "承袭": 4, "自录": 5, "增益": 6, "异解": 7, "同解": 8}
        out.sort(key=lambda r: (order.get(r["type"], 9), r["from"], r["to"]))
        return out


def _layered(p: Any) -> bool:
    return any(t.startswith("layer:") for t in getattr(p, "tags", []))


def _layer(p: Any) -> str:
    return next((t.split(":", 1)[1] for t in getattr(p, "tags", []) if t.startswith("layer:")), "正文")


__all__ = ["CommentaryStudy", "Commentators", "Exegesis", "clean_name", "grams"]
