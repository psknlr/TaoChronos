"""配伍禁忌 — 十八反 and 十九畏 read in the literature: who said which drug 反 or 畏 which, when, and which formulas still
write the two together.

The pairs come from ``incompatibility.yaml`` (the groups of the two verses, with the names each drug goes by).  Against
the corpus:

* **statements** — every passage writing 反 or 畏 followed by a list of drugs (甘草……反大戟、芫花、甘遂、海藻): the drug
  the statement is about (the entry's heading, else the nearest drug of the rule before it) and each drug of the list;
  a pair of the verses is attested by its earliest witness, the works stating it and their periods; pairs stated that the
  verses do not hold are listed too (the doctrine before and beside its verses);
* **verses** — where the verses themselves are written (their lines, searched as they are);
* **formulas** — the written-out compositions (the harvest of ``study pairs``, one per work) that hold both drugs of a
  pair: how many works, in which periods, and the earliest (甘遂半夏汤 writes 甘遂 with 甘草);
* **check** — a formula's 原方 or a list of drugs, against the pairs.

It reads what the texts say.  That a formula writes two drugs together says nothing of whether doing so is sound or safe,
and a statement of 反 is a text, not a pharmacological finding; ``modern.safety`` gives the modern warnings.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from .base import StudyBase, dated

_LIST_SEP = set("、，,及与和并")
_STOP = set("。；;：:！？\n")
_USED_BY = re.compile(r"[、，]?(?:为之?使|为之?佐|为之?君|为之?臣)")  # 术、干漆、苦参为之使: the entry's drug's 使


def _clause_start(norm: str, at: int, reach: int = 40) -> int:
    """Where the sentence holding a statement at ``at`` begins — no more than ``reach`` characters back (then after a
    comma, else at the statement itself)."""
    begin = max(norm.rfind(c, 0, at) for c in "。；;\n") + 1
    if at - begin <= reach:
        return begin
    comma = max(norm.rfind(c, at - reach, at) for c in "，,")
    return comma + 1 if comma >= 0 else at


class IncompatibilityStudy:
    def __init__(self, base: StudyBase, formulas: Any, pairs: Any) -> None:
        self.b = base
        self.formulas = formulas
        self.pairs = pairs
        self._rules: list[dict[str, Any]] | None = None

    # ------------------------------------------------------------ the rules
    @property
    def data(self) -> dict[str, Any]:
        return self.b.data("incompatibility.yaml")

    def rules(self) -> list[dict[str, Any]]:
        """Each rule with its pairs: [{rule, relation, a: {drug, names}, b: {drug, names}}]."""
        if self._rules is None:
            out = []
            for rule in self.data.get("rules") or []:
                pairs = []
                for g in rule.get("groups") or []:
                    for other in g.get("against") or []:
                        pairs.append(({"drug": g["drug"], "names": list(g["names"])}, {"drug": other["drug"], "names": list(other["names"])}))
                for a, b in rule.get("pairs") or []:
                    pairs.append((dict(a), dict(b)))
                out.append({**{k: v for k, v in rule.items() if k not in ("groups", "pairs")},
                            "pairs": [{"a": a, "b": b, "label": f"{a['drug']}{rule['relation']}{b['drug']}"} for a, b in pairs]})
            self._rules = out
        return self._rules

    def _norm_names(self, names: list[str]) -> set[str]:
        return {self.b.normalize(n) for n in names if n}

    def _pair_index(self) -> list[tuple[dict[str, Any], dict[str, Any], set[str], set[str]]]:
        return [(rule, p, self._norm_names(p["a"]["names"]), self._norm_names(p["b"]["names"]))
                for rule in self.rules() for p in rule["pairs"]]

    # ------------------------------------------------------------ main
    def run(self, target: str | None = None, *, drugs: list[str] | None = None, top: int = 30) -> dict[str, Any]:
        out: dict[str, Any] = {"rules": [{k: r[k] for k in ("id", "name", "relation", "verse", "attribution")}
                                         | {"pairs": [p["label"] for p in r["pairs"]]} for r in self.rules()],
                               "notice": self.data.get("notice", "")}
        index = self._pair_index()
        focus: set[str] | None = None
        if drugs:
            out["check"] = self.check(drugs)
        elif target:
            lex = self.b.pack.lexicon
            if lex.resolve(target, "formula") or lex.resolve(self.b.normalize(target), "formula"):
                out["check"] = self.check_formula(target)
            else:
                norm = self.b.normalize(target)
                focus = {p["label"] for _r, p, a, b in index if norm in a or norm in b}
                if not focus:
                    raise ValueError(f"{target!r} is neither a formula nor a drug of the 十八反 / 十九畏 pairs")
                out["drug"] = target
        pairs = [(r, p, a, b) for r, p, a, b in index if focus is None or p["label"] in focus]
        out["statements"] = self.statements(pairs)
        out["verses"] = self.verses() if focus is None else []
        out["formulas"] = self.formulas_with(pairs, top=top)
        attested = {s["pair"] for s in out["statements"]["pairs"]}
        out["summary"] = {"pairs": len(pairs), "attested": len(attested),
                          "written_together": sum(1 for f in out["formulas"]["pairs"] if f["works"]),
                          "works_writing_together": len({w for f in out["formulas"]["pairs"] for w in f["_works"]})}
        for f in out["formulas"]["pairs"]:
            f.pop("_works")
        return out

    # ------------------------------------------------------------ check
    def check(self, drugs: list[str]) -> dict[str, Any]:
        names = [d.strip() for d in drugs if d and d.strip()]
        canon = {self.b.normalize(n): n for n in names}
        for n in names:  # the lexicon's canonical name too (白芍 → 芍药)
            entry = self.b.pack.lexicon.resolve(n, "herb") or self.b.pack.lexicon.resolve(self.b.normalize(n), "herb")
            if entry is not None:
                canon.setdefault(self.b.normalize(entry.term), n)
        flagged = []
        for rule, p, a, b in self._pair_index():
            hit_a = sorted({canon[x] for x in a if x in canon})
            hit_b = sorted({canon[x] for x in b if x in canon})
            if hit_a and hit_b:
                flagged.append({"rule": rule["name"], "relation": rule["relation"], "pair": p["label"], "a": hit_a, "b": hit_b})
        return {"drugs": names, "flagged": flagged}

    def check_formula(self, name: str) -> dict[str, Any]:
        res = self.formulas.run(name, other_names=False)
        group = next((g for g in res.get("groups", []) if "原方" in (g.get("relation") or "")), None)
        w = next((x for x in res.get("witnesses", []) if group and x["passage_id"] == group["earliest"]["passage_id"]), None)
        if w is None:
            return {"formula": name, "drugs": [], "flagged": [], "found": False}
        out = self.check([i["term"] for i in w.get("ingredients", [])] + [i["surface"] for i in w.get("ingredients", [])])
        out["drugs"] = list(dict.fromkeys(i["term"] for i in w.get("ingredients", [])))
        keep = ("passage_id", "title", "years", "period", "locator", "quote", "source", "license")
        return {"formula": name, "found": True, "witness": {k: w.get(k) for k in keep}, **out}

    # ------------------------------------------------------------ statements (反 / 畏 written in the texts)
    def statements(self, pairs: list[tuple[dict[str, Any], dict[str, Any], set[str], set[str]]]) -> dict[str, Any]:
        b = self.b
        lex = b.pack.lexicon
        by_rel: dict[str, list[tuple[dict[str, Any], dict[str, Any], set[str], set[str]]]] = defaultdict(list)
        for item in pairs:
            by_rel[item[0]["relation"]].append(item)
        found: dict[str, list[dict[str, Any]]] = defaultdict(list)
        other: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for rel, items in by_rel.items():
            names = sorted({n for _r, _p, a, bb in items for n in a | bb}, key=len, reverse=True)
            subjects = names
            ids: list[str] = []
            for n in names:
                ids += b.find(rel + n)
            seen: set[str] = set()
            for p in b.passages(dict.fromkeys(ids)):
                if p.id in seen:
                    continue
                seen.add(p.id)
                norm = b.normalize(p.text)
                heading = b.normalize(p.locator.section or "")
                for m in re.finditer(re.escape(rel), norm):
                    listed = self._list_after(norm, m.end(), lex, names)
                    if not listed:
                        continue
                    subject = self._subject(norm[: m.start()], heading, subjects)
                    if subject is None:
                        continue
                    # the quotation: the sentence of the statement (from a comma when it is long), to the end of its list
                    start = _clause_start(norm, m.start())
                    last, last_at = listed[-1][0], listed[-1][1]
                    end = last_at + len(last) + (1 if norm[last_at + len(last): last_at + len(last) + 1] in ("。", "；", ";") else 0)
                    for drug, _at in listed:
                        pair = next((p_ for _r, p_, a, bb in items if (subject in a and drug in bb) or (subject in bb and drug in a)), None)
                        w = b.witness(p, start=start, end=min(len(p.text), end), width=0)
                        if pair is not None:
                            found[pair["label"]].append(w)
                        elif subject != drug:
                            other[(subject, rel, drug)].append(w)
        rows = []
        for _r, p_, _a, _b in pairs:
            ws = found.get(p_["label"], [])
            if not ws:
                rows.append({"pair": p_["label"], "works": 0, "earliest": None, "periods": {}})
                continue
            rows.append(self._attest(p_["label"], ws))
        rows.sort(key=lambda r: (r["earliest"] is None, dated((r["earliest"] or {}).get("years")), r["pair"]))
        others = [self._attest(f"{s}{rel}{d}", ws) for (s, rel, d), ws in other.items()]
        others = [o for o in others if o["works"] >= 2]
        others.sort(key=lambda r: (-r["works"], dated((r["earliest"] or {}).get("years"))))
        return {"pairs": [r for r in rows if r["works"]], "unattested": [r["pair"] for r in rows if not r["works"]],
                "other_pairs": others[:20],
                "note": "a statement: 反 or 畏 followed by a list of drugs, about the entry's drug (its heading, else the drug "
                        "its sentence opens with); one per work, the earliest witness shown — when it is a 辑本 (神农本草经), "
                        "dated as the lost work although its 七情 notes come from later books, the earliest other witness too"}

    def _list_after(self, norm: str, start: int, lex: Any, names: list[str]) -> list[tuple[str, int]]:
        """The drugs listed right after 反 / 畏 (反大戟、芫花、甘遂、海藻): (normalised name, offset), until the list ends.
        A drug is a name of the rules (longest first) or a drug of the lexicon."""
        window = norm[start: start + 60]
        cut = min((i for i, ch in enumerate(window) if ch in _STOP), default=len(window))
        window = window[:cut]
        herbs = {m.start: m.end for m in lex.match(window) if m.category == "herb"}
        out: list[tuple[str, int]] = []
        pos = 0
        while pos < len(window):
            while pos < len(window) and window[pos] in _LIST_SEP | {" ", "　"}:
                pos += 1
            name = next((n for n in names if window.startswith(n, pos)), None)
            end = pos + len(name) if name else max((e for s_, e in herbs.items() if s_ == pos), default=None)
            if end is None:
                break
            out.append((window[pos:end], start + pos))
            pos = end
        return out

    @staticmethod
    def _subject(before: str, heading: str, names: list[str]) -> str | None:
        """The drug a statement is about: the entry's heading; else the drug whose bracketed note it is in (甘草（术干漆苦参
        为使恶远志反甘遂…）); else the drug its sentence opens with (甘草　术、干漆、苦参为之使；…反甘遂); else the nearest
        drug of the rules before it (within 160 characters) that is not another drug's 使 (苦参为之使) or the object of
        恶 / 畏 / 反 / 杀."""
        for n in names:
            if heading.startswith(n):
                return n
        tail = before[-160:]
        opened, closed = tail.rfind("（"), tail.rfind("）")
        if opened > closed:
            head = tail[:opened].rstrip("　 ")
            for n in names:
                if head.endswith(n):
                    return n
        start = max(tail.rfind(c) for c in "。\n") + 1
        opening = tail[start:].lstrip("　 ，、")
        for n in names:
            if opening.startswith(n):
                return n
        found = sorted(((m.start(), n) for n in names for m in re.finditer(re.escape(n), tail)), reverse=True)
        for at, n in found:
            if _USED_BY.match(tail, at + len(n)):
                continue  # 苦参为之使: the 使 of the entry's drug
            prior = tail[max(0, at - 16): at]
            k = max(prior.rfind(c) for c in "恶畏反杀")
            if k >= 0 and not any(c in prior[k:] for c in "；。（）"):
                continue  # 恶远志、…: the object of another relation
            return n
        return None

    def _attest(self, label: str, ws: list[dict[str, Any]]) -> dict[str, Any]:
        by_work: dict[str, dict[str, Any]] = {}
        for w in sorted(ws, key=lambda w: (dated(w.get("years")), w["passage_id"])):
            by_work.setdefault(w.get("work") or w["book_id"], w)
        first = min(by_work.values(), key=lambda w: (dated(w.get("years")), w["passage_id"]))
        periods = Counter(w.get("period") or "未定" for w in by_work.values())
        out = {"pair": label, "works": len(by_work), "earliest": first, "periods": dict(periods),
               "examples": sorted(by_work.values(), key=lambda w: dated(w.get("years")))[:5]}
        # a 辑本 (a lost work gathered from later books, 神农本草经) is dated as the work, not as the notes it carries
        if self._compiled(first):
            out["earliest_compiled"] = True
            plain = [w for w in by_work.values() if not self._compiled(w)]
            out["earliest_uncompiled"] = min(plain, key=lambda w: (dated(w.get("years")), w["passage_id"])) if plain else None
        return out

    def _compiled(self, w: dict[str, Any]) -> bool:
        book = self.b.corpus.books.get(w.get("book_id"))
        return getattr(book, "attribution", "") == "compiled"

    # ------------------------------------------------------------ verses
    def verses(self) -> list[dict[str, Any]]:
        out = []
        for rule in self.rules():
            ids: list[str] = []
            for line in rule.get("verse_probe") or []:
                ids += self.b.find(line)
            ws = []
            for p in self.b.passages(dict.fromkeys(ids)):
                norm = self.b.normalize(p.text)
                at = min((i for i in (norm.find(self.b.normalize(x)) for x in rule.get("verse_probe") or []) if i >= 0), default=0)
                ws.append(self.b.witness(p, start=at, end=min(len(p.text), at + 40), width=0))
            row = self._attest(rule["name"], ws) if ws else {"pair": rule["name"], "works": 0, "earliest": None, "periods": {}}
            out.append({"rule": rule["name"], "works": row["works"], "earliest": row["earliest"], "periods": row["periods"],
                        "examples": row.get("examples", [])})
        return out

    # ------------------------------------------------------------ formulas writing a pair together
    def formulas_with(self, pairs: list[tuple[dict[str, Any], dict[str, Any], set[str], set[str]]], *, top: int = 30) -> dict[str, Any]:
        built = self.pairs.h.build(self.pairs._cache())
        comps = built["compositions"]
        order = [p.label for p in self.b.periods] + ["未定"]
        holding: dict[str, set[int]] = defaultdict(set)  # drug (normalised) → the compositions writing it
        for k, c in enumerate(comps):
            for item in (c[6] if len(c) > 6 else []):
                holding[self.b.normalize(item[1])].add(k)
        rows = []
        for _r, p_, a, bb in pairs:
            with_a = set().union(*(holding.get(x, set()) for x in a))
            with_b = set().union(*(holding.get(x, set()) for x in bb))
            hits = [comps[k] for k in sorted(with_a & with_b)]
            by_work: dict[str, list[Any]] = {}
            for c in sorted(hits, key=lambda c: (dated([c[3], c[3]] if c[3] is not None else None), c[4])):
                by_work.setdefault(c[0], c)
            periods = Counter(self.pairs._period(c[3]) for c in by_work.values())
            formulas = Counter(self.pairs._label(c[1]) for c in by_work.values() if c[1])
            first = list(by_work.values())[:3]
            rows.append({"pair": p_["label"], "works": len(by_work), "compositions": len(hits),
                         "periods": {p: periods[p] for p in order if periods[p]},
                         "formulas": [{"formula": f, "works": k} for f, k in formulas.most_common(8)],
                         "earliest": [{"formula": self.pairs._label(c[1]) if c[1] else "", "year": c[3], "passage_id": c[4]} for c in first],
                         "_works": set(by_work)})
        rows.sort(key=lambda r: (-r["works"], r["pair"]))
        return {"pairs": rows, "compositions": len(comps),
                "note": "written-out compositions holding both drugs of a pair (one per work); a composition is the text's, "
                        "not a judgement that the combination is sound"}


__all__ = ["IncompatibilityStudy"]
