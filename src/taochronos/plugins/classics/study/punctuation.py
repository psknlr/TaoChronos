"""句读 — punctuating unpunctuated text (白文) with a model learned from the punctuated transcriptions in the store.

The editors of the 笈成 texts (and CMETA's, the 東亜医学協会's, Wikisource's) have punctuated some eighty million
characters of the medical classics.  Every gap between two characters of that text is an example: a sentence mark
(。；？！) was put there, a clause mark (，、：), or none.  The model reads each gap by the characters around it — the
character before and after, the two characters on either side, the pair across the gap, the three before — and turns
each view into a log-odds from its counts (smoothed towards the base rate); a logistic regression weighs the views and
a second model tells a sentence mark from a clause mark.  The rules of the extraction segmenter (``segment.py``) are
one more view.

**Marks only.**  The model inserts marks between the characters of the input; it never changes, adds or drops a
character.  The output is checked for it (``preserved``), because a punctuator that rewrites the text is an editor, not
a punctuator.

**Measured.**  The ``punctuation`` suite of TaoChronos-Eval holds out whole books, strips their marks and scores the
model's gaps against the editors' (boundary and sentence F1, the mark type, character preservation), beside the rule
segmenter as a baseline.  The model is trained on the transcriptions in the store; it stays in the local cache, since
it is derived from texts that are for local research only.
"""

from __future__ import annotations

import gzip
import hashlib
import math
import pickle
import random
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from ..collation import align, matched
from ..segment import Segmenter, is_unpunctuated

MODEL_VERSION = "judou-ngram@1"
MAJOR = "。；？！"
MINOR = "，、："
MARKS = set(MAJOR + MINOR)
# brackets, quotation and title marks, dashes and ellipses: not boundaries of their own
SILENT = set("「」『』“”‘’《》〈〉【】〔〕［］()[]{}…—·‧・")
SPACE = set("　 ")
OPEN = set("「『“‘《〈【〔［([{")
LEAD = OPEN | set("○●◯◎")  # what opens the next unit: a mark goes in front of it
CLOSE = set("」』”’》〉】〕］)]}")
QUESTION = re.compile(r"(?:何也|何如|奈何|云何|何谓也|何以然|何故|何哉|耶|欤|否|乎)$")
HAN = re.compile(r"[㐀-鿿\U00020000-\U0002ffff〓□]")
NOTE = re.compile(r"（[^（）]{0,300}）|\([^()]{0,300}\)")
VIEWS = ("L1", "R1", "L2", "R2", "LR", "L3", "R3", "X4", "RULE")
NOTE_MIN = 6  # Han characters a bracketed note needs before it is punctuated inside
PAD = "＾"


def gaps(text: str) -> tuple[str, list[int]]:
    """The characters of a punctuated text and, for every gap before a character, its mark: 0 none, 1 clause, 2
    sentence.  Notes in brackets are left out; a run of spaces (items of a printed prescription) is a clause mark."""
    text = NOTE.sub("", text.replace("\r", "").replace("\n", ""))
    chars: list[str] = []
    labels: list[int] = []
    pending = 0
    for ch in text:
        if ch in MAJOR:
            pending = 2
        elif ch in MINOR or ch in SPACE:
            pending = max(pending, 1)
        elif ch in SILENT or ch in ",.;:!?":
            if ch in ".;!?":
                pending = 2
            elif ch in ",:":
                pending = max(pending, 1)
        else:
            if chars:
                labels.append(pending)
            chars.append(ch)
            pending = 0
    return "".join(chars), labels


def both_kinds(labels: list[int]) -> bool:
    """Whether a text tells sentences from clauses: some editors put 。 at every stop, which says nothing of the kind of
    mark (the sentence model learns, and the sentence scores are read, only on texts that use both)."""
    marks = [y for y in labels if y]
    if len(marks) < 4:
        return False
    share = sum(1 for y in marks if y == 1) / len(marks)
    return 0.15 <= share <= 0.95


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    if x < -35:
        return 0.0
    if x > 35:
        return 1.0
    return 1.0 / (1.0 + math.exp(-x))


class PunctuationModel:
    """Character n-gram views of a gap, turned into log-odds and weighed by a logistic regression."""

    def __init__(self) -> None:
        self.total: dict[str, Counter] = {v: Counter() for v in VIEWS}
        self.bound: dict[str, Counter] = {v: Counter() for v in VIEWS}
        self.typed: dict[str, Counter] = {v: Counter() for v in VIEWS}  # marks in texts that use both kinds
        self.major: dict[str, Counter] = {v: Counter() for v in VIEWS}
        self.prior_b = 0.1
        self.prior_m = 0.4
        self.w_b: list[float] = [1.0] * (len(VIEWS) + 1)
        self.w_m: list[float] = [1.0] * (len(VIEWS) + 1)
        self.threshold = 0.5
        self.threshold_m = 0.5  # sentence mark rather than clause mark
        self.info: dict[str, Any] = {"version": MODEL_VERSION}
        self.segmenter: Segmenter | None = None

    # ------------------------------------------------------------ features
    def _rules(self, chars: str) -> dict[int, str]:
        """Gap index (before character i) → the rule of the extraction segmenter that marks it."""
        if self.segmenter is None:
            return {}
        return {pos: f"{mark}{rule}" for pos, (mark, rule) in self.segmenter.boundaries(chars).items()}

    @staticmethod
    def _keys(chars: str, i: int, rules: dict[int, str]) -> tuple[str, ...]:
        """The views of the gap before character ``i`` (1 ≤ i < len)."""
        c = chars
        l1 = c[i - 1]
        r1 = c[i]
        l2 = (c[i - 2] if i >= 2 else PAD) + l1
        r2 = r1 + (c[i + 1] if i + 1 < len(c) else PAD)
        l3 = (c[i - 3] if i >= 3 else PAD) + l2
        r3 = r2 + (c[i + 2] if i + 2 < len(c) else PAD)
        return (l1, r1, l2, r2, l1 + r1, l3, r3, l2 + r2, rules.get(i, "-"))

    # ------------------------------------------------------------ training
    def count(self, chars: str, labels: list[int]) -> None:
        rules = self._rules(chars)
        typed = both_kinds(labels)
        for i in range(1, len(chars)):
            y = labels[i - 1]
            for view, key in zip(VIEWS, self._keys(chars, i, rules)):
                self.total[view][key] += 1
                if y:
                    self.bound[view][key] += 1
                    if typed:
                        self.typed[view][key] += 1
                        if y == 2:
                            self.major[view][key] += 1

    def _deltas(self, chars: str, i: int, rules: dict[int, str]) -> tuple[list[float], list[float]]:
        """Each view's log-odds of a mark (and of a sentence mark, given a mark) against the base rates."""
        xb = [1.0]
        xm = [1.0]
        lb, lm = _logit(self.prior_b), _logit(self.prior_m)
        for view, key in zip(VIEWS, self._keys(chars, i, rules)):
            n = self.total[view].get(key, 0)
            if n:
                b = self.bound[view].get(key, 0)
                xb.append(_logit((b + 4 * self.prior_b) / (n + 4)) - lb)
                t = self.typed[view].get(key, 0)
                m = self.major[view].get(key, 0)
                xm.append(_logit((m + 4 * self.prior_m) / (t + 4)) - lm if t else 0.0)
            else:
                xb.append(0.0)
                xm.append(0.0)
        return xb, xm

    @staticmethod
    def _fit(rows: list[tuple[list[float], int]], epochs: int = 60, rate: float = 0.5) -> list[float]:
        """Logistic regression over the views' log-odds (full-batch gradient descent with a small L2 penalty)."""
        if not rows:
            return [1.0] * (len(VIEWS) + 1)
        k = len(rows[0][0])
        w = [0.0] + [0.3] * (k - 1)
        n = len(rows)
        for _ in range(epochs):
            grad = [0.0] * k
            for x, y in rows:
                p = _sigmoid(sum(wi * xi for wi, xi in zip(w, x)))
                err = p - y
                for j in range(k):
                    grad[j] += err * x[j]
            for j in range(k):
                w[j] -= rate * (grad[j] / n + (0.001 * w[j] if j else 0.0))
        return w

    def train(self, passages: Iterable[str], *, dev_share: float = 0.1, seed: int = 7, max_chars: int = 8_000_000,
              use_rules: bool = True, lexicon: Any = None) -> "PunctuationModel":
        """Count the views on most passages, then weigh them on the rest (the development share)."""
        self.segmenter = Segmenter(lexicon) if use_rules else None
        rng = random.Random(seed)
        counted = dev_chars = 0
        dev: list[tuple[str, list[int]]] = []
        n_pass = 0
        for text in passages:
            chars, labels = gaps(text)
            if len(chars) < 8 or not labels:
                continue
            n_pass += 1
            if rng.random() < dev_share and dev_chars < 400_000:
                dev.append((chars, labels))
                dev_chars += len(chars)
                continue
            self.count(chars, labels)
            counted += len(chars)
            if counted >= max_chars:
                break
        self.prune()
        gaps_total = sum(self.total["L1"].values()) or 1
        self.prior_b = sum(self.bound["L1"].values()) / gaps_total
        self.prior_m = sum(self.major["L1"].values()) / max(1, sum(self.typed["L1"].values()))
        rows_b: list[tuple[list[float], int]] = []
        rows_m: list[tuple[list[float], int]] = []
        for chars, labels in dev:
            rules = self._rules(chars)
            for i in range(1, len(chars)):
                xb, xm = self._deltas(chars, i, rules)
                y = labels[i - 1]
                if rng.random() < 0.25:
                    rows_b.append((xb, 1 if y else 0))
                if y and both_kinds(labels):
                    rows_m.append((xm, 1 if y == 2 else 0))
        rng.shuffle(rows_b)
        rng.shuffle(rows_m)
        self.w_b = self._fit(rows_b[:60000])
        self.w_m = self._fit(rows_m[:60000])  # the marks beyond the first 60 000 tune the sentence cut
        if dev:  # too little text to hold any back: the cuts stay at one half
            self.threshold = self._best_threshold(dev[: max(1, len(dev) // 2)])
        if rows_m:
            self.threshold_m = self._best_sentence_threshold(rows_m[60000:] or rows_m)
        self.info.update({"passages": n_pass, "characters": counted, "dev_characters": dev_chars,
                          "gap_rate": round(self.prior_b, 4), "sentence_share": round(self.prior_m, 4),
                          "weights": {"mark": [round(x, 3) for x in self.w_b], "sentence": [round(x, 3) for x in self.w_m],
                                      "views": ["bias", *VIEWS]},
                          "threshold": self.threshold, "threshold_sentence": self.threshold_m, "rules": bool(use_rules)})
        return self

    def prune(self, min_count: int = 2) -> None:
        """Drop views seen once (their smoothed log-odds are close to the base rate): a smaller model, as good."""
        for view in VIEWS:
            if view in ("L1", "R1", "RULE"):
                continue
            rare = [k for k, n in self.total[view].items() if n < min_count]
            for k in rare:
                del self.total[view][k]
                self.bound[view].pop(k, None)
                self.typed[view].pop(k, None)
                self.major[view].pop(k, None)

    def _best_sentence_threshold(self, rows: list[tuple[list[float], int]]) -> float:
        """The cut on P(sentence | mark) that best tells sentence marks from clause marks on held-back marks."""
        scored = [(_sigmoid(sum(w * x for w, x in zip(self.w_m, xm))), y) for xm, y in rows]
        gold = sum(y for _, y in scored) or 1
        best, best_f = 0.5, -1.0
        for t in [x / 100 for x in range(20, 81, 2)]:
            tp = sum(1 for p, y in scored if p >= t and y)
            pred = sum(1 for p, _ in scored if p >= t) or 1
            prec, rec = tp / pred, tp / gold
            f = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
            if f > best_f:
                best, best_f = t, f
        return best

    def _best_threshold(self, dev: list[tuple[str, list[int]]]) -> float:
        best, best_f = 0.5, -1.0
        scored: list[tuple[float, int]] = []
        for chars, labels in dev:
            rules = self._rules(chars)
            for i in range(1, len(chars)):
                xb, _ = self._deltas(chars, i, rules)
                scored.append((_sigmoid(sum(w * x for w, x in zip(self.w_b, xb))), 1 if labels[i - 1] else 0))
        gold = sum(y for _, y in scored) or 1
        for t in [x / 100 for x in range(20, 81, 2)]:
            tp = sum(1 for p, y in scored if p >= t and y)
            pred = sum(1 for p, _ in scored if p >= t) or 1
            prec, rec = tp / pred, tp / gold
            f = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
            if f > best_f:
                best, best_f = t, f
        return best

    # ------------------------------------------------------------ reading
    def probabilities(self, chars: str) -> list[tuple[float, float]]:
        """For every gap (before character 1 … n-1): the probability of a mark and of a sentence mark given a mark."""
        rules = self._rules(chars)
        out: list[tuple[float, float]] = []
        for i in range(1, len(chars)):
            xb, xm = self._deltas(chars, i, rules)
            out.append((_sigmoid(sum(w * x for w, x in zip(self.w_b, xb))),
                        _sigmoid(sum(w * x for w, x in zip(self.w_m, xm)))))
        return out

    def mark_for(self, chars: str, i: int, pm: float) -> str:
        """The mark of a gap the model punctuates: a sentence mark (？ after a question) or a clause mark (： after
        曰 and 云)."""
        if pm >= self.threshold_m:
            return "？" if QUESTION.search(chars[max(0, i - 4): i]) else "。"
        return "：" if chars[i - 1] in "曰云" else "，"

    def marks(self, chars: str) -> list[tuple[int, str, float]]:
        """(gap before character i, mark, probability of a mark) for the gaps the model punctuates."""
        return [(i, self.mark_for(chars, i, pm), round(pb, 3))
                for i, (pb, pm) in enumerate(self.probabilities(chars), start=1) if pb >= self.threshold]

    def punctuate(self, text: str, normalize: Any = None, *, margin: float = 0.08) -> dict[str, Any]:
        """Marks for the gaps between the Han characters of a text, read on the normalised characters the model was
        counted on.  Bracketed notes are punctuated on their own (the main text reads across them); a mark that falls
        before an opening quote goes in front of it, one after a note behind its closing bracket; existing marks are
        kept and nothing else changes.  Gaps near the cut are listed for review: marks put with little margin
        (``doubtful``) and marks almost put (``possible``)."""
        in_note = [False] * len(text)
        notes = [(m.start(), m.end()) for m in NOTE.finditer(text)]
        for s, e in notes:
            for k in range(s, e):
                in_note[k] = True
        han = [i for i, ch in enumerate(text) if HAN.match(ch)]
        runs = [[i for i in han if not in_note[i]]] + [[i for i in han if s <= i < e] for s, e in notes]
        decided: dict[int, tuple[str, float]] = {}
        review: list[dict[str, Any]] = []
        for k_run, pos in enumerate(runs):
            if len(pos) < (2 if k_run == 0 else NOTE_MIN):  # a short note (一两, 去皮) is one unit
                continue
            chars = "".join(text[i] for i in pos)
            norm = normalize(chars) if normalize is not None else chars
            if len(norm) != len(chars):
                norm = chars
            for k, (pb, pm) in enumerate(self.probabilities(norm), start=1):
                mark = self.mark_for(norm, k, pm)
                if pb >= self.threshold:
                    decided[pos[k]] = (mark, pb)
                    if pb < self.threshold + margin:
                        review.append({"at": pos[k], "kind": "doubtful", "mark": mark, "p": round(pb, 3)})
                elif pb >= self.threshold - margin:
                    review.append({"at": pos[k], "kind": "possible", "mark": mark, "p": round(pb, 3)})
        out: list[tuple[str, bool]] = []  # (character, inserted)
        inserted: list[dict[str, Any]] = []
        for i, ch in enumerate(text):
            if i in decided:
                j = len(out)
                while j > 0 and out[j - 1][0] in LEAD:
                    j -= 1
                prev = out[j - 1][0] if j else ""
                if prev and prev not in MARKS and prev not in SPACE and prev not in LEAD and prev not in ",.;:!?":
                    mark, p = decided[i]
                    out.insert(j, (mark, True))
                    inserted.append({"at": i, "mark": mark, "p": round(p, 3)})
            out.append((ch, False))
        tail = len(out)
        while tail > 0 and (out[tail - 1][0] in CLOSE or out[tail - 1][0] in SPACE or out[tail - 1][0] in "\r\n"):
            tail -= 1
        if tail and HAN.match(out[tail - 1][0]):
            last = "".join(ch for ch, _ in out[max(0, tail - 4): tail])
            end = "？" if QUESTION.search(normalize(last) if normalize is not None else last) else "。"
            out.append((end, True))
            inserted.append({"at": len(text), "mark": end, "p": None})
        result = "".join(ch for ch, _ in out)
        kept = "".join(ch for ch, new in out if not new)
        done = {m["at"] for m in inserted}
        marked = {i for i in range(1, len(text)) if text[i - 1] in MARKS or text[i - 1] in SPACE}  # the text's own marks
        review = [dict(r, context=text[max(0, r["at"] - 8): r["at"]] + "▲" + text[r["at"]: r["at"] + 8])
                  for r in sorted(review, key=lambda r: r["at"])
                  if (r["kind"] == "possible" and r["at"] not in marked) or r["at"] in done]
        return {"text": result, "marks": inserted, "inserted": len(inserted), "preserved": kept == text,
                "review": review}

    # ------------------------------------------------------------ cache
    def save(self, path: Path) -> None:
        seg, self.segmenter = self.segmenter, None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            with gzip.open(tmp, "wb") as f:
                pickle.dump(self, f, protocol=pickle.HIGHEST_PROTOCOL)
            tmp.replace(path)
        finally:
            self.segmenter = seg

    @classmethod
    def load(cls, path: Path, lexicon: Any = None) -> "PunctuationModel | None":
        try:
            with gzip.open(path, "rb") as f:
                model = pickle.load(f)
        except Exception:  # noqa: BLE001 - a broken or foreign cache is rebuilt
            return None
        if not isinstance(model, cls) or model.info.get("version") != MODEL_VERSION:
            return None
        model.segmenter = Segmenter(lexicon) if model.info.get("rules") else None
        return model


def score(gold: list[int], pred: list[int]) -> dict[str, float]:
    """Boundary, sentence and mark-type scores of predicted gap labels (0 none, 1 clause, 2 sentence) against gold."""
    tp = fp = fn = stp = sfp = sfn = typed = 0
    for g, p in zip(gold, pred):
        if g and p:
            tp += 1
            typed += int(g == p)
        elif p:
            fp += 1
        elif g:
            fn += 1
        if g == 2 and p == 2:
            stp += 1
        elif p == 2:
            sfp += 1
        elif g == 2:
            sfn += 1

    def f1(a: int, b: int, c: int) -> tuple[float, float, float]:
        prec = a / (a + b) if a + b else 0.0
        rec = a / (a + c) if a + c else 0.0
        return prec, rec, (2 * prec * rec / (prec + rec) if prec + rec else 0.0)

    bp, br, bf = f1(tp, fp, fn)
    sp, sr, sf = f1(stp, sfp, sfn)
    return {"boundary_p": round(bp, 4), "boundary_r": round(br, 4), "boundary_f1": round(bf, 4),
            "sentence_p": round(sp, 4), "sentence_r": round(sr, 4), "sentence_f1": round(sf, 4),
            "mark_type_accuracy": round(typed / tp, 4) if tp else 0.0, "gaps": len(gold)}


def rule_labels(segmenter: Segmenter, chars: str) -> list[int]:
    """The extraction segmenter's marks as gap labels (the baseline)."""
    labels = [0] * max(0, len(chars) - 1)
    for pos, (mark, _rule) in segmenter.boundaries(chars).items():
        if 1 <= pos < len(chars):
            labels[pos - 1] = 2 if mark in MAJOR else 1
    return labels


def model_labels(model: PunctuationModel, chars: str) -> list[int]:
    labels = [0] * max(0, len(chars) - 1)
    for i, mark, _p in model.marks(chars):
        labels[i - 1] = 2 if mark in MAJOR else 1
    return labels


class PunctuationStudy:
    """``study punctuate``: the model trained on the store's punctuated main text and cached.  Whole works are held out
    of training (chosen by a hash of the work key, so every transcription of a held-out work is out), and the model
    is measured on them when it is trained: every result carries the scores it was measured at."""

    SAMPLE = 3000  # held-out passages scored when a model is trained

    def __init__(self, base: Any) -> None:
        self.b = base
        self._model: PunctuationModel | None = None

    @staticmethod
    def held_out(key: str, share: int = 12) -> bool:
        return int(hashlib.sha1(key.encode()).hexdigest()[:6], 16) % share == 0

    def unit(self, book_id: str) -> str:
        """The unit held out together: the work a book is a witness of (the book itself when it has none)."""
        book = self.b.corpus.books.get(book_id)
        return (getattr(book, "work", None) or book_id) if book is not None else book_id

    def _store_rows(self, books: list[str] | None = None, chunk: int = 20000, *, plain: bool = False) -> Iterable[tuple[str, str]]:
        """(book id, text) of the store's punctuated main text (``plain``: its unpunctuated main text), in reading order,
        read in chunks (the store stays free in between)."""
        store = self.b.corpus.store
        where = ("punctuation!='editorial'" if plain else "punctuation='editorial'") + " AND layer='正文' AND kind IN ('text','formula')"
        args: list[Any] = []
        if books is not None:
            where += f" AND book_id IN ({','.join('?' * len(books))})"
            args = list(books)
        last = 0
        while True:
            with store.lock:
                rows = store.db.execute(f"SELECT rid, book_id, text FROM passages WHERE {where} AND rid > ? ORDER BY rid "
                                        f"LIMIT {chunk}", [*args, last]).fetchall()
            if not rows:
                return
            last = rows[-1][0]
            for _rid, bid, text in rows:
                yield bid, text

    def training_texts(self, *, max_chars: int = 8_000_000, seed: int = 11) -> Iterable[str]:
        """Normalised punctuated passages of the works not held out — from the store a random share of them spread
        over all its books (about ``max_chars`` characters), else the corpus's passages."""
        store = getattr(self.b.corpus, "store", None)
        if store is not None:
            with store.lock:
                total = store.db.execute("SELECT sum(length(text)) FROM passages WHERE punctuation='editorial' AND "
                                         "layer='正文' AND kind IN ('text','formula')").fetchone()[0] or 1
            share = min(1.0, 1.3 * max_chars / total)
            rng = random.Random(seed)
            for bid, text in self._store_rows():
                if rng.random() < share and not self.held_out(self.unit(bid)) and not is_unpunctuated(text):
                    yield self.b.normalize(text)
            return
        for p in self.b.corpus.passages():
            if p.kind in ("text", "formula", "materia_medica") and not is_unpunctuated(p.text) and not self.held_out(self.unit(p.book_id)):
                yield self.b.normalize(p.text)

    def held_out_texts(self, *, sample: int = SAMPLE, seed: int = 3) -> list[tuple[str, str]]:
        """A sample of the held-out works' punctuated passages: (book id, text)."""
        books = sorted(bid for bid in self.b.corpus.books if self.held_out(self.unit(bid)))
        if not books:
            return []
        if getattr(self.b.corpus, "store", None) is not None:
            rows = [(bid, t) for bid, t in self._store_rows(books) if not is_unpunctuated(t)]
        else:
            rows = [(p.book_id, p.text) for p in self.b.corpus.passages(book_ids=books)
                    if p.kind in ("text", "formula", "materia_medica") and not is_unpunctuated(p.text)]
        random.Random(seed).shuffle(rows)
        return rows[:sample]

    def evaluate(self, model: PunctuationModel, texts: list[tuple[str, str]] | None = None, *,
                 preservation_checks: int = 300) -> dict[str, Any]:
        """Scores against the editors on held-out text (by default the held-out works): boundary, sentence and
        mark-type scores of the model and of the rule segmenter, on all texts and on the texts that tell sentences
        from clauses; the character preservation rate of the punctuated output."""
        texts = self.held_out_texts() if texts is None else texts
        seg = Segmenter(self.b.pack.lexicon)
        g_all: list[int] = []
        m_all: list[int] = []
        r_all: list[int] = []
        g_typed: list[int] = []
        m_typed: list[int] = []
        r_typed: list[int] = []
        books: set[str] = set()
        n = chars_n = preserved = checked = 0
        for bid, text in texts:
            chars, gold = gaps(self.b.normalize(text))
            if len(chars) < 8 or not any(gold):
                continue
            pm, pr = model_labels(model, chars), rule_labels(seg, chars)
            g_all += gold
            m_all += pm
            r_all += pr
            if both_kinds(gold):
                g_typed += gold
                m_typed += pm
                r_typed += pr
            n += 1
            chars_n += len(chars)
            books.add(bid)
            if checked < preservation_checks:
                stripped = strip_marks(text)
                preserved += int(model.punctuate(stripped, self.b.normalize)["preserved"])
                checked += 1
        return {"passages": n, "books": len(books), "works": len({self.unit(b) for b in books}), "characters": chars_n,
                "model": score(g_all, m_all), "rules": score(g_all, r_all),
                "typed": {"gaps": len(g_typed), "model": score(g_typed, m_typed), "rules": score(g_typed, r_typed)},
                "preservation_rate": round(preserved / checked, 4) if checked else None, "preservation_checked": checked}

    def against_baiwen(self, model: PunctuationModel, *, max_chars: int = 30000, max_works: int = 12,
                       min_rate: float = 0.05) -> dict[str, Any]:
        """The real use: 白文.  For the held-out works that the store has both unpunctuated (the 四库 transcriptions of
        Kanripo) and punctuated, the 白文 witness is punctuated by the model and the editors' marks are carried over
        from the punctuated witness that aligns best; the gaps inside aligned runs are scored.  A work is left out
        when too little of it aligns or its punctuated witness is barely punctuated (the gold would be wrong); the
        sentence scores count only the works whose editors tell sentences from clauses."""
        store = getattr(self.b.corpus, "store", None)
        if store is None:
            return {"works": [], "skipped": [], "note": "no 白文 witnesses in this corpus"}
        with store.lock:
            counts = store.db.execute("SELECT book_id, punctuation = 'editorial', count(*) FROM passages WHERE layer='正文' "
                                      "GROUP BY book_id, punctuation = 'editorial'").fetchall()
        plain: dict[str, list[str]] = {}
        marked: dict[str, list[str]] = {}
        for bid, editorial, n in counts:
            key = self.unit(bid)
            if n > 20 and self.held_out(key):
                (marked if editorial else plain).setdefault(key, []).append(bid)
        seg = Segmenter(self.b.pack.lexicon)
        results: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        pooled: dict[str, list[int]] = {"gold": [], "model": [], "rules": [], "gold_t": [], "model_t": [], "rules_t": []}
        for key in sorted(set(plain) & set(marked))[:max_works]:
            bid = sorted(plain[key])[0]
            bchars, bpred, brule, inner = self._baiwen_side(bid, model, seg, max_chars)
            if len(bchars) < 200:
                skipped.append({"work": key, "reason": "too little 白文"})
                continue
            best = None
            for wid in sorted(marked[key]):
                wchars, wlabels = self._punctuated_side(wid, 4 * max_chars)
                ops = align(bchars, wchars)
                if best is None or matched(ops) > best[0]:
                    best = (matched(ops), wid, ops, wlabels)
            if best is None or best[0] < 0.3 * len(bchars):
                skipped.append({"work": key, "reason": f"the punctuated witnesses align with {best[0] if best else 0} of "
                                                       f"{len(bchars)} characters of the 白文 sample"})
                continue
            _, wid, ops, wlabels = best
            gold: list[int] = []
            pred: list[int] = []
            rule: list[int] = []
            for tag, b0, b1, w0, _w1 in ops:
                if tag != "equal":
                    continue
                for t in range(1, b1 - b0):
                    if inner[b0 + t - 1]:
                        gold.append(wlabels[w0 + t - 1])
                        pred.append(bpred[b0 + t - 1])
                        rule.append(brule[b0 + t - 1])
            rate = sum(1 for y in gold if y) / len(gold) if gold else 0.0
            if rate < min_rate:
                skipped.append({"work": key, "punctuated": wid, "reason": f"the punctuated witness marks {rate:.1%} of the "
                                                                          "aligned gaps: barely punctuated"})
                continue
            typed = both_kinds(gold)
            pooled["gold"] += gold
            pooled["model"] += pred
            pooled["rules"] += rule
            if typed:
                pooled["gold_t"] += gold
                pooled["model_t"] += pred
                pooled["rules_t"] += rule
            results.append({"work": key, "baiwen": bid, "punctuated": wid, "characters": len(bchars),
                            "aligned": round(best[0] / len(bchars), 3), "gold_mark_rate": round(rate, 3),
                            "tells_sentences": typed, "model": score(gold, pred), "rules": score(gold, rule)})
        out: dict[str, Any] = {"works": results, "skipped": skipped,
                               "note": "gaps inside runs where the 白文 and the punctuated witness align character by "
                                       "character; a paragraph break of the punctuated witness counts as a sentence end"}
        if pooled["gold"]:
            out["model"] = score(pooled["gold"], pooled["model"])
            out["rules"] = score(pooled["gold"], pooled["rules"])
        if pooled["gold_t"]:
            out["typed"] = {"model": score(pooled["gold_t"], pooled["model_t"]), "rules": score(pooled["gold_t"], pooled["rules_t"])}
        return out

    def _baiwen_side(self, book_id: str, model: PunctuationModel, seg: Segmenter,
                     max_chars: int) -> tuple[str, list[int], list[int], list[bool]]:
        """The first ``max_chars`` characters of a 白文 witness, the model's and the rules' gap labels, and whether each
        gap lies inside a passage (paragraph breaks are given, not predicted)."""
        chars: list[str] = []
        pred: list[int] = []
        rule: list[int] = []
        inner: list[bool] = []
        total = 0
        for _bid, text in self._store_rows([book_id], plain=True):
            c, _ = gaps(self.b.normalize(text))
            if len(c) < 2:
                continue
            if chars:
                pred.append(2)
                rule.append(2)
                inner.append(False)
            chars.append(c)
            pred += model_labels(model, c)
            rule += rule_labels(seg, c)
            inner += [True] * (len(c) - 1)
            total += len(c)
            if total >= max_chars:
                break
        return "".join(chars), pred, rule, inner

    def _punctuated_side(self, book_id: str, max_chars: int) -> tuple[str, list[int]]:
        chars: list[str] = []
        labels: list[int] = []
        total = 0
        for _bid, text in self._store_rows([book_id]):
            c, lab = gaps(self.b.normalize(text))
            if not c:
                continue
            if chars:
                labels.append(2)
            chars.append(c)
            labels += lab
            total += len(c)
            if total >= max_chars:
                break
        return "".join(chars), labels

    def model(self, *, rebuild: bool = False) -> PunctuationModel:
        if self._model is not None and not rebuild:
            return self._model
        cache = None
        store = getattr(self.b.corpus, "store", None)
        if store is not None:
            sig = self.b.signature()
            cache = Path(store.path).parent / "study-cache" / f"punct-{sig['corpus_digest']}.pkl.gz"
            if not rebuild and cache.exists():
                loaded = PunctuationModel.load(cache, self.b.pack.lexicon)
                if loaded is not None:
                    self._model = loaded
                    return loaded
        model = PunctuationModel().train(self.training_texts(), lexicon=self.b.pack.lexicon)
        measured = self.evaluate(model)
        if measured["passages"]:
            model.info["held_out"] = {k: measured[k] for k in ("passages", "books", "works", "characters", "model",
                                                                "rules", "typed", "preservation_rate")}
        baiwen = self.against_baiwen(model)
        if baiwen.get("model"):
            model.info["baiwen"] = {"works": [w["work"] for w in baiwen["works"]], "model": baiwen["model"],
                                    "rules": baiwen["rules"], "typed": baiwen.get("typed")}
        if cache is not None:
            model.save(cache)
        self._model = model
        return model

    def run(self, text: str | None = None, passage_id: str | None = None, *, compare: bool = True) -> dict[str, Any]:
        """Punctuate a text (or a passage).  A text that is already punctuated is stripped of its marks and punctuated
        again, and the model's marks are compared with the editors' (``compare``)."""
        passage = None
        if passage_id:
            found = self.b.passages([passage_id])
            if not found:
                raise KeyError(f"no passage {passage_id}")
            passage = found[0]
            text = passage.text
        if not text or not text.strip():
            raise ValueError("give a text or a passage id")
        model = self.model()
        chars, gold = gaps(self.b.normalize(text))
        already = has_marks(text) and (passage is None or getattr(passage, "punctuation", "editorial") != "none")
        # a punctuated input loses its marks (not its notes) and is punctuated again; 白文 is punctuated as it is
        base = strip_marks(text) if already else text
        marked = model.punctuate(base, self.b.normalize)
        info = {k: v for k, v in model.info.items() if k != "weights"}
        out: dict[str, Any] = {
            "input": text[:4000], "unpunctuated": base[:4000], "punctuated": marked["text"], "preserved": marked["preserved"],
            "inserted": marked["inserted"], "marks": marked["marks"][:600], "review": marked["review"][:200],
            "model": info, "measured": model.info.get("held_out"), "measured_baiwen": model.info.get("baiwen"),
            "method": "character n-gram views of each gap (log-odds from the store's punctuated texts), weighed by "
                      "logistic regression; marks are only inserted — every character is kept",
        }
        if passage is not None:
            out["passage"] = self.b.witness(passage)
        if already and compare:
            out["against_editors"] = score(gold, model_labels(model, chars))
            out["baseline_rules"] = score(gold, rule_labels(Segmenter(self.b.pack.lexicon), chars))
            out["note"] = "the input was punctuated: its marks were stripped, the text punctuated again and the two compared"
        return out


def has_marks(text: str) -> bool:
    """Whether a text is punctuated: sentence and clause marks, not brackets, spaces or item circles (a 白文 passage
    with its notes in brackets is still 白文)."""
    han = sum(1 for ch in text if HAN.match(ch))
    marks = sum(1 for ch in text if ch in MARKS or ch in ",.;:!?")
    return marks >= 2 and marks >= 0.03 * han


def strip_marks(text: str) -> str:
    """A text without its punctuation marks and spacing (brackets, quotes and notes stay): the 白文 the model reads."""
    return "".join(ch for ch in text if ch not in MARKS and ch not in SPACE and ch not in ",.;:!?")


__all__ = ["MODEL_VERSION", "PunctuationModel", "PunctuationStudy", "both_kinds", "gaps", "has_marks", "model_labels",
           "rule_labels", "score", "strip_marks"]
