"""校勘疑义 — the textual cruxes of a classic, gathered from what its commentators say about its words.

A literal reading of a classic is not always the text's reading.  Commentators judge clauses transposed (「小青龙汤
主之」六字当在「发热不渴」之下), words miswritten (「去桂」当是「去芍药」), added (衍文) or lost (脱简).  For every clause of
a work's base witness, ``study cruxes`` reads the commentaries on it (``study commentaries``) for the vocabulary of
textual criticism:

* **transposition** 错简 · 倒装 · 当在……之下 / 之后 · 当移;
* **emendation** 当作 · 当是 · 应作 · 疑作 · 恐是 … and 字差 · 传写之误 — counted only when the words it corrects are words
  of the clause (「此当是……」 explains, it does not emend);
* **interpolation** 衍文 · 某字衍 · 后人所加 · 非仲景原文 · 叔和所增;
* **omission** 脱简 · 有脱文 · 阙文 · 脱某字;
* **doubt** 疑有脱误 · 疑误 · 未详 · 不可解 — weak alone;
* **misplacement** 「此条当是阳明篇错简」, or a 错简 that names no words: the clause belongs elsewhere — recorded, but it
  leaves the clause's wording as it is (and a clause misplaced in one work stands in its place in another), so it is no
  crux of its reading.

A statement is kept with its commentator, date, the words it doubts (the *target*, when they are the clause's) and a
short quote.  A clause becomes a crux when a commentator doubts named words of it, or when two commentators doubt it
without naming words (错简, 衍文, 传写之误, 疑有脱误 …); a transposition that sends the clause to another chapter, a
destination outside the clause, and a doubt the commentator reports only to reject (「……而不知」) do not count.  A commentary unit that runs on into the next
clause (「……（三一）伤寒……」) is cut there, so the next clause's problems are not charged to this one.

The result is the registry the support reading consults (``domains/classics/cruxes.yaml``): a claim that rests on the
literal wording of a crux is *ambiguous*, not supported.  Who doubts what is recorded; the reading is not decided.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from ....protocol.base import stable_id
from ..cruxes import NUMBERING, han_view
from .base import StudyBase

CONTEMPORARY = 1950  # commentaries from this year on are left out (the corpus's policy on contemporary work)
NEXT_CLAUSE = re.compile(r"[（(〔][一二三四五六七八九十百零〇]{1,5}[）)〕]")
MARKERS: list[tuple[str, bool, re.Pattern[str]]] = [  # kind, strong (counts alone), pattern on normalised text
    ("transposition", True, re.compile(r"错简|倒装|(?<![不非])当在[^。；]{1,24}?(?:句)?(?:之)?(?:下|后|上|前|末|首)|(?<![不非])当移[^。；]{0,12}"
                                       r"|宜移[^。；]{0,12}|(?<![不非])当接[^。；]{1,12}")),
    ("emendation", True, re.compile(r"(?<![不非])(?:当作|当是|应作|宜作|疑作|疑是|恐是)(?P<y>[一-鿿]{1,8}?)(?=[。，；、）」”]|$)"
                                    r"|(?<![不非])(?:当作|当是|应作|宜作|疑作|疑是|恐是)[一-鿿]{1,8}|字差|互差|传写之(?:误|讹)|传写有(?:误|讹)"
                                    r"|字之?(?:误|讹)")),
    ("interpolation", True, re.compile(r"衍文|衍(?:也|矣|耳)|后人所(?:加|增|附|羼)|非仲景(?:原文|之文|语|之言)|叔和所(?:增|加|附|撰)")),
    ("omission", True, re.compile(r"脱简|(?<![疑似])有脱文|阙文|缺文|(?<![疑似])脱[一两二三]字|(?<![疑似])有脱(?:误|简|句)")),
    ("doubt", False, re.compile(r"[疑似]有(?:脱|误|错|衍|阙)|疑误|不可解|存疑|疑非|疑脱")),
]
# terms that name the clause's own problem without quoting it
CLAUSE_BOUND = re.compile(r"错简|倒装|衍文|字差|互差|脱简|传写之(?:误|讹)")
# a transposition across chapters (「此条当是阳明篇错简」「宜移少阴篇」): the clause is misplaced, its words are not in doubt
CHAPTER = re.compile(r"[篇章卷论经]|病中|书中|错简于此")
PLACED = re.compile(r"[于在]|冠于")  # 「错简于……」「错简在……」 say where the clause belongs
# 「脉缓当作浮缓看」 reads the words, it does not correct them
READ_AS = re.compile(r"^[一-鿿]{0,6}(?:看|解|观|论|会)")
# a line of preparation (右三味，㕮咀，以水三升，煮取…) is not a clause whose reading a claim rests on
PREPARATION = re.compile(r"^[右上][一二三四五六七八九十]+味|㕮咀|煮取|为末|为散|去滓|分温")
PUNCT = "。，；：、,.;:「」“”（）()"
COUNTERS = re.compile(r"(?:[一两二三四五六七八九十]+字|字|句|之文|之句|之语|等语|等句)$")
# 「……则安得又复有大青龙汤主之之文」: a phrase the commentator's witness repeats; one occurrence in the clause is not it
REPEATED = re.compile(r"又复有|复有|重出|重见|又有|复出|复见")
# 「当在发热不渴之下」: the destination of a transposition; inside the clause it moves words within it
DESTINATION = re.compile(r"当在(?P<x>[^。；]{1,24}?)(?:句)?(?:之)?(?:下|后|上|前|末|首)")
# a doubt reported to be rejected: 「各注家疑为后人所附。而不知此方……」
REJECTED_AFTER = re.compile(r"而不知|殊不知|不然|非也|岂知|无谓|未必然")


class CruxStudy:
    def __init__(self, base: StudyBase, commentary: Any) -> None:
        self.b = base
        self.commentary = commentary

    # ----------------------------------------------------------- statements
    def _herb_list(self, han: str) -> bool:
        """A line that is (mostly) a list of drugs — a formula's composition — carries no reading a claim rests on."""
        covered = sum(m.end - m.start for m in self.b.pack.lexicon.match(han) if m.category == "herb")
        return covered >= 0.7 * len(han)

    @staticmethod
    def _named(before: str) -> tuple[str, bool]:
        """The words a statement points at, right before its marker: 「去桂当是」 → 去桂; 「小青龙汤主之六字。当在」 →
        小青龙汤主之 (a counter — 六字, 句 — may stand between, and then a mark).  A mark with no counter before it
        ends the pointing: 「虽得之二三日。当是……」 names nothing.  Returns the Han characters and whether a counter
        pointed at them."""
        text = before.rstrip(PUNCT + " 　")
        punct = len(text) < len(before)
        last = max((text.rfind(ch) for ch in PUNCT), default=-1)
        if last >= 0:
            text = text[last + 1:]  # the words pointed at stand after the last mark (「……辛味也。（本字」 → 本字)
        han = han_view(text)[0][-14:]
        counted = bool(COUNTERS.search(han))
        if punct and not counted:
            return "", False
        return COUNTERS.sub("", han), counted

    def _target(self, before: str, clause: str) -> str | None:
        """The clause's words a statement names: the longest ending of the pointed-at words that is a stretch of the
        clause, of two characters at least — for 「胁下偏痛之偏字当是满字」, the words before 之 (胁下偏痛)."""
        han, _ = self._named(before)
        cut = han.rfind("之")
        candidates = [han] + ([han[:cut]] if 0 < cut and len(han) - cut - 1 <= 2 else [])  # 「X之Y字」: Y one or two characters
        for text in candidates:
            for n in range(min(len(text), 12), 1, -1):
                if text[-n:] in clause:
                    return text[-n:]
        return None

    def statements(self, text: str, clause: str) -> list[dict[str, Any]]:
        """The crux statements of one commentary unit on a clause (its normalised Han characters)."""
        norm = self.b.normalize(text)
        cut = next((m.start() for m in NEXT_CLAUSE.finditer(norm) if m.start() > 6), len(norm))
        norm = norm[:cut]
        out: list[dict[str, Any]] = []
        taken: list[tuple[int, int]] = []
        for kind, strong, rx in MARKERS:
            for m in rx.finditer(norm):
                if any(s <= m.start() < e for s, e in taken):
                    continue
                before = norm[max(0, m.start() - 16): m.start()]
                target = self._target(before, clause)
                named, counted = self._named(before)
                if counted and not target and len(named) >= 2:
                    continue  # 「反恶寒之反字，衍文也」 in the unit of another clause: the words it names are not this clause's
                if target and REPEATED.search(before) and clause.count(target) < 2:
                    continue  # the doubted repetition is not in this witness
                if kind == "emendation" and m.group(0).startswith(("当作", "当是", "应作", "宜作", "疑作", "疑是", "恐是")) and not target:
                    continue  # 「此当是……」 explains the clause; an emendation corrects words of it
                if kind == "emendation" and READ_AS.search(norm[m.start() + 2: m.start() + 12]):
                    continue  # 「当作浮缓看」「寒字当作痰字解」 read the words, they do not correct them
                if kind == "transposition" and not target and not CLAUSE_BOUND.search(m.group(0)):
                    target = self._target(norm[max(0, m.start() - 24): m.start()], clause)
                if kind == "emendation" and not target and not CLAUSE_BOUND.search(m.group(0)) and m.group(0).endswith(("也", "矣", "耳")):
                    continue  # a bare 「……误也」 without the clause's words is judged of something else
                if REJECTED_AFTER.search(norm[m.end(): m.end() + 20]):
                    continue  # a doubt reported only to be answered
                if kind == "transposition" and (CHAPTER.search(norm[max(0, m.start() - 8): m.end() + 10])
                                                or PLACED.match(norm[m.end(): m.end() + 2])):
                    kind, target = "misplacement", None  # 「错简在杂疗篇内」「错简于太阳脉证之后」: the clause's place, not its words
                dest = DESTINATION.match(m.group(0)) if kind == "transposition" else None
                if dest and han_view(dest.group("x"))[0] not in clause:
                    target = None  # moved out of the clause (「当在十九条之后」): the clause's own words stand
                if kind == "transposition" and not target:
                    kind = "misplacement"  # 「此条必是错简」 without the words it moves: the clause's place is in doubt, not its reading
                taken.append((m.start(), m.end()))
                quote_start = max(0, m.start() - 24)
                # a statement that names words of the clause is a crux on its own; one that names none needs a second voice
                out.append({"kind": kind, "strong": strong and bool(target) and kind != "misplacement",
                            "target": target, "proposed": m.groupdict().get("y") if kind == "emendation" else None,
                            "marker": m.group(0)[:16], "quote": text[quote_start: min(len(text), m.end() + 16)][:60]})
        return out

    # --------------------------------------------------------------- clauses
    def clause(self, text: str | None = None, passage_id: str | None = None) -> dict[str, Any]:
        res = self.commentary.run(text, passage_id)
        clause = han_view(res["normalized"])[0]
        by: list[dict[str, Any]] = []
        for u in res["commentaries"]:
            year = (u.get("years") or [None])[0]
            if isinstance(year, (int, float)) and year >= CONTEMPORARY:
                continue  # a contemporary apparatus (a modern edition's notes) is neither the tradition nor free to quote
            for s in self.statements(u.get("text") or "", clause):
                by.append({"commentator": u["commentator"], "book": u.get("title") or u.get("book_id"),
                           "year": (u.get("years") or [None])[0], "passage": (u.get("passage_ids") or [None])[0], **s})
        return {"clause": res["clause"], "normalized": clause, "base_work": res.get("base_work"), "statements": by,
                "commentaries": res["count"], "crux": self.verdict(by)}

    @staticmethod
    def verdict(statements: list[dict[str, Any]]) -> dict[str, Any] | None:
        """A crux when a commentator doubts named words or uses an unambiguous term, or two voice a mere doubt."""
        statements = [s for s in statements if s["kind"] != "misplacement"]
        strong = [s for s in statements if s["strong"]]
        people = {s["commentator"] for s in statements}
        if not strong and len(people) < 2:
            return None
        targets = defaultdict(set)
        for s in strong or statements:
            if s.get("target"):
                targets[s["target"]].add(s["commentator"])
        target = max(targets.items(), key=lambda kv: (len(kv[1]), len(kv[0])))[0] if targets else None
        proposed = next((s["proposed"] for s in strong if s.get("proposed") and s.get("target") == target), None)
        return {"kinds": sorted({s["kind"] for s in (strong or statements)}), "target": target, "proposed": proposed,
                "commentators": len({s["commentator"] for s in (strong or statements)})}

    def harvest(self, work: str, *, limit: int | None = None, min_chars: int = 10) -> dict[str, Any]:
        """The cruxes of every clause of a work's base witness."""
        bid = self.commentary._base_witness(work)
        if bid is None:
            raise ValueError(f"no base witness of {work!r} in the corpus")
        passages = [p for p in self.b.corpus.passages(book_ids=[bid]) if len(han_view(p.text)[0]) >= min_chars]
        cruxes, seen, looked = [], set(), 0
        for p in passages[:limit] if limit else passages:
            for sentence in _clauses(p.text):
                han = han_view(self.b.normalize(sentence))[0]
                if len(han) < min_chars or han in seen or PREPARATION.search(han) or self._herb_list(han):
                    continue
                seen.add(han)
                looked += 1
                found = self.clause(sentence)
                verdict = found["crux"]
                if verdict is None:
                    continue
                by = sorted(found["statements"], key=lambda s: (not s["strong"], s.get("year") or 9999))
                anchor = NUMBERING.sub("", han)
                cruxes.append({"id": stable_id("crux", work, anchor), "work": work, "clause": anchor[:120], "witness": p.id,
                               **verdict, "by": [{k: s.get(k) for k in ("commentator", "book", "year", "passage", "kind", "target",
                                                                        "proposed", "quote")} for s in by[:6]]})
        return {"work": work, "base_witness": bid, "clauses": looked, "cruxes": cruxes}


REGISTRY_HEADER = """# 校勘疑义 · the textual cruxes of the classics, harvested from their commentaries in the corpus store.
#
# Generated by `taochronos study cruxes --work <work> --write-registry` (plugins/classics/study/cruxes.py): for every clause of
# the work's base witness, the commentaries on it were read for the vocabulary of textual criticism (当作 / 当是,
# 衍文, 脱简, 错简, 当在……之下 …).  A clause is listed when a commentator doubts named words of it, or two doubt it
# without naming words.  Each entry keeps the clause (its Han characters, normalised), the doubted words when named
# (target), the kinds of doubt, the reading proposed, and who said it, with a short quote (≤ 60 characters) of a
# public-domain commentary.  The support reading consults this registry: a claim resting on the literal wording of a
# crux is *ambiguous*, not supported.  It records who doubts what; it does not decide the reading — review and edit.
"""


def write_registry(path: Any, harvests: list[dict[str, Any]]) -> dict[str, Any]:
    """Write (or update, work by work) the crux registry from ``harvest`` results."""
    import yaml

    from ....protocol.yamlio import load_yaml

    existing = (load_yaml(path) or {}) if path.exists() else {}
    works = {h["work"] for h in harvests}
    entries = [e for e in existing.get("cruxes") or [] if e.get("work") not in works]
    meta = dict(existing.get("meta") or {})
    for h in harvests:
        entries += h["cruxes"]
        meta[h["work"]] = {"base_witness": h["base_witness"], "clauses_read": h["clauses"], "cruxes": len(h["cruxes"])}
    entries.sort(key=lambda e: (e["work"], e.get("witness") or "", e["id"]))
    body = yaml.safe_dump({"meta": meta, "cruxes": entries}, allow_unicode=True, sort_keys=False, width=160)
    path.write_text(REGISTRY_HEADER + body, encoding="utf-8")
    return {"path": str(path), "works": sorted(works), "cruxes": len(entries)}


def _clauses(text: str, whole: int = 160) -> list[str]:
    """The clauses of a passage of the base text, notes in brackets left out: the passage itself when it is one 条 of
    ordinary length — what the commentators comment on, and where a transposition moves words from one sentence to
    another (「小青龙汤主之」 after 「发热不渴」) — else its sentences."""
    core = re.sub(r"（[^（）]{0,300}）|\([^()]{0,300}\)", "", text)
    if len(han_view(core)[0]) <= whole:
        return [core] if core.strip() else []
    return [s for s in re.split(r"(?<=[。？！])", core) if s.strip()]


__all__ = ["CruxStudy", "write_registry"]
