"""学派 — what the works of a school share against the other works of their time, whom they cite and whom they dispute.

The schools and their members are those of ``schools.yaml`` and ``physicians.yaml`` (the groupings of the 中医各家学说
textbooks: 伤寒 with its branches 错简重订 维护旧论 辨证论治, 河间, 攻邪, 易水, 丹溪, 温补, 温病, 汇通 …).  A school's
works are the works of the store its members wrote (traditional or compiled attributions), each read in one
transcription, in its own layers (later notes and modern apparatus left out), up to a fixed number of characters
taken evenly through it.  They are compared with the other works written within sixty years of any of them, weighed
so that

* each physician counts once — a member's works share one unit, and so do the works of one other author — and
* the other works come in the school's proportions of forms (论著, 医案, 方书, 本草, 歌赋): case records are compared
  with case records, formularies with formularies, whatever the subject.

``study schools`` gives

* **vocabulary** — words of two to four characters that the school's physicians use more than the others: the
  log-odds ratio of the (weighted) shares using a word, with a z score (by which words are ranked), a one-sided test
  with Benjamini–Hochberg, the rates per 10 000 characters on both sides, the works that use it and a quotation;
  words that only begin or end on a particle, doses and physicians' names are left out;
* **formulas** — the formulas the school's works write out or prescribe (the compositions and treatment sentences of
  ``study pairs``), the same way;
* **citations** — the physicians the school's works name more than the others do; the share of their citations that
  go to the school's own members against the share of the other works' citations that do (homophily); which schools
  cite it; whom it rejects and who rejects it (the stance reading of ``study disputes``); citations between members;

and without a school, every school with its members, works, span and first words, and the school-by-school matrices
of citation and rejection.

A school is a historian's grouping: membership is a convention the numbers test, not a fact the texts state.  A
commentary carries the classic it comments on, so a school of commentators shares its classic's words; and a word a
school uses more is not a doctrine until its passages are read — each row names the works to read.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from ....science.stats import benjamini_hochberg
from .base import StudyBase, dated, normal_sf, row_filter

VERSION = "schools@2"
ATTRIBUTIONS = ("traditional", "compiled")
FORMS = {"医案": "医案", "方书": "方书", "本草": "本草", "歌赋": "歌赋"}  # every other category: 论著
_HAN = re.compile(r"[㐀-鿿]+")
NO_SCHOOL = "无派属"
# a word worth listing neither begins nor ends on a particle or an adverb (之温, 温之, 更有邪), and is not a dose
_EDGE = set("之乎者也矣焉哉而以于於其与则乃且亦所此彼是故曰云谓又即皆既已为夫盖若或凡但兮耳尔然及更再必尚犹只仍每各诸")
_END = _EDGE | set("不有无")
_NUM = "一二三四五六七八九十百千半两"
# doses, counts and the serving vessel (三两, 一盏, 作一服, 钱半, 二十); the openings of case records (一男, 一妇人)
_NOISE = re.compile(rf"[{_NUM}]大?[两钱分铢升合斗枚片丸日盏碗钟杯服次沸度]|[两钱分]半|^[{_NUM}]+$|[至水]{{1}}[{_NUM}]|"
                    rf"^一(?:男|女|妇|人|儿|老|僧|童|小|室|少|士)")
# the words of making and taking a medicine (clause.yaml's preparation and administration, in short)
_SERVING = re.compile(r"[盏煎滓渣]|^服|服$|温服|热服|冷服|顿服|食前|食后|食远|空心|为末|细末|蜜丸|糊丸|水浸|汤浸|酒浸|炼蜜|捣|杵")
TYPES = {"词": "words", "药": "drugs", "方": "formulas", "煎服": "serving"}


def _as_list(value: Any) -> list[str]:
    if not value:
        return []
    return [str(v) for v in value] if isinstance(value, (list, tuple)) else [str(value)]


def form_of(category: str | None) -> str:
    return FORMS.get(category or "", "论著")


def _odds(a: float, n1: float, c: float, n0: float) -> tuple[float, float]:
    """Log-odds ratio (with ½ added to each cell) of a in n1 against c in n0, and its z score."""
    lor = math.log((a + 0.5) / (n1 - a + 0.5)) - math.log((c + 0.5) / (n0 - c + 0.5))
    se = math.sqrt(1 / (a + 0.5) + 1 / (n1 - a + 0.5) + 1 / (c + 0.5) + 1 / (n0 - c + 0.5))
    return lor, lor / se


def _rate_z(ys: float, yo: float, ns: float, no: float, a0: float = 1000.0) -> float:
    """z of the log-odds of a word's rate on the school's side against the other side, with an informative Dirichlet
    prior of total weight ``a0`` spread by the pooled rate (Monroe, Colaresi & Quinn 2008, "Fightin' Words")."""
    if ns <= 0 or no <= 0 or ys + yo <= 0:
        return 0.0
    ai = a0 * (ys + yo) / (ns + no)
    d = math.log((ys + ai) / (ns + a0 - ys - ai)) - math.log((yo + ai) / (no + a0 - yo - ai))
    return d / math.sqrt(1 / (ys + ai) + 1 / (yo + ai))


class SchoolStudy:
    def __init__(self, base: StudyBase, network: Any, harvest: Any) -> None:
        self.b = base
        self.net = network
        self.harvest = harvest
        self.schools: dict[str, dict[str, Any]] = dict(base.data("schools.yaml").get("schools") or {})
        self.persons: dict[str, dict[str, Any]] = network.persons
        self.members: dict[str, list[str]] = {}  # 伤寒, 伤寒·错简重订 → person ids
        for name, spec in self.schools.items():
            self.members[name] = []
            for branch in spec.get("branches") or {}:
                self.members[f"{name}·{branch}"] = []
        for pid, p in self.persons.items():
            for s in _as_list(p.get("school")):
                self.members.setdefault(s, []).append(pid)
                if p.get("branch"):
                    self.members.setdefault(f"{s}·{p['branch']}", []).append(pid)
        self._works: dict[str, dict[str, Any]] | None = None
        self._sizes: dict[str, dict[float | None, int]] | None = None
        self._samples: dict[tuple[str, int], list[str]] = {}

    # ------------------------------------------------------------ schools and works
    def resolve(self, name: str) -> str:
        """伤寒学派 → 伤寒, 错简重订 → 伤寒·错简重订, 温疫 → 温病·温疫."""
        key = self.b.normalize(name.strip())
        for group in self.members:
            spec = self.schools.get(group.split("·")[0], {})
            forms = {group, group.split("·")[-1]} | ({spec.get("label", "")} if "·" not in group else set())
            norms = {self.b.normalize(f) for f in forms if f}
            if key in norms or key in {n + "派" for n in norms} or key in {n + "学派" for n in norms}:
                return group
        raise KeyError(f"no school {name!r}; schools: {', '.join(self.members)}")

    def _schools_of(self, persons: Iterable[str]) -> set[str]:
        return {s for p in persons for s in _as_list(self.persons.get(p, {}).get("school"))}

    def works(self) -> dict[str, dict[str, Any]]:
        """Work → title, dates, category, the book read for it (the one with the most text in its own layers), its
        books, its authors as physicians (through traditional or compiled attributions) and their schools.  The
        witnesses of one work that different physicians edited or commented on count apart (the 宋本 of 张机, 成无己's
        注解伤寒论, 张卿子's edition), keyed ``work|persons``; a witness naming none of them goes with the others."""
        if self._works is not None:
            return self._works
        sizes = self._own_sizes()
        grouped: dict[str, list[Any]] = defaultdict(list)
        for bid, bk in self.b.corpus.books.items():
            grouped[bk.work or bid].append(bk)

        def own(bk: Any) -> int:
            c = bk.composition
            return sum(n for y, n in sizes.get(bk.id, {}).items() if y is None or c is None or c.start - 5 <= y <= c.end + 5)

        out: dict[str, dict[str, Any]] = {}
        self.units_of_work: dict[str, list[str]] = defaultdict(list)
        for key, books in grouped.items():
            sets: dict[frozenset[str], list[Any]] = defaultdict(list)
            for bk in books:
                sets[frozenset(self.net.persons_of_book(bk.id)) if bk.attribution in ATTRIBUTIONS else frozenset()].append(bk)
            named = sorted((s for s in sets if s), key=lambda s: (-len(sets[s]), sorted(s)))
            for s in list(named):  # a set inside a larger one joins it
                bigger = next((b for b in named if b != s and s < b), None)
                if bigger is not None:
                    sets[bigger] += sets.pop(s)
                    named.remove(s)
            if frozenset() in sets and named:
                sets[named[0]] += sets.pop(frozenset())
            for s, members in sets.items():
                rep = max(members, key=lambda bk: (own(bk), bk.id))
                persons = sorted(s, key=lambda p: (dated(self.persons[p].get("life") or self.persons[p].get("active")), p))
                ukey = key if len(sets) == 1 else f"{key}|{'+'.join(sorted(s))}"
                title = self.net._work_title(key) if len(sets) == 1 else \
                    f"{rep.title}（{'、'.join(self.persons[p]['name'] for p in persons)}）"
                c = rep.composition
                first = next((a for a in rep.authors if a and "佚名" not in a and "不详" not in a), "")
                out[ukey] = {"work": ukey, "title": title, "book_id": rep.id, "books": sorted(bk.id for bk in members),
                             "years": [c.start, c.end] if c else None, "category": rep.category, "form": form_of(rep.category),
                             "authors": list(rep.authors), "persons": persons, "schools": sorted(self._schools_of(persons)),
                             "author_key": (f"person:{persons[0]}" if persons else
                                            f"author:{self.b.normalize(re.sub(r'[（(].*?[）)]|等$', '', first).strip())}" if first
                                            else f"work:{key}"),
                             "characters": own(rep)}
                self.units_of_work[key].append(ukey)
        self._works = out
        return out

    def lived(self, w: dict[str, Any], members: Iterable[str]) -> list[float]:
        """A school work's years within its member author's life (and thirty years after: posthumous editions) — a
        compilation printed long after (脉因证治, 1775) is compared with its author's contemporaries."""
        spans = [self.persons[p].get("life") or self.persons[p].get("active") for p in w["persons"] if p in members]
        spans = [s for s in spans if s]
        if not spans or not w["years"]:
            return w["years"]
        lo, hi = min(s[0] for s in spans), max(s[1] for s in spans) + 30
        a, b = max(w["years"][0], lo), min(w["years"][1], hi)
        return [a, b] if a <= b else [lo, hi - 30]

    def _own_sizes(self) -> dict[str, dict[float | None, int]]:
        """Book → layer year → characters (toc left out)."""
        if self._sizes is not None:
            return self._sizes
        sizes: dict[str, dict[float | None, int]] = defaultdict(dict)
        store = getattr(self.b.corpus, "store", None)
        if store is not None:
            with store.lock:
                extra, params = row_filter(self.b.corpus)
                rows = store.db.execute(f"SELECT book_id, year, SUM(LENGTH(text)) FROM passages WHERE kind != 'toc'{extra} "
                                        "GROUP BY book_id, year", params).fetchall()
            for bid, year, n in rows:
                sizes[bid][year] = sizes[bid].get(year, 0) + (n or 0)
        else:
            for p in self.b.corpus.passages():
                if p.kind != "toc":
                    y = self.b.year(p)
                    sizes[p.book_id][y] = sizes[p.book_id].get(y, 0) + len(p.text)
        self._sizes = sizes
        return sizes

    def group_works(self, group: str) -> list[dict[str, Any]]:
        members = set(self.members.get(group, []))
        return sorted((w for w in self.works().values() if members & set(w["persons"]) and w["years"] and w["characters"]),
                      key=lambda w: (dated(w["years"]), w["work"]))

    def comparison(self, group: str, *, window: int = 60) -> list[dict[str, Any]]:
        """The other works written within ``window`` years of any of the group's works (none by its members)."""
        members = set(self.members.get(group, []))
        spans = [(y[0] - window, y[1] + window) for y in (self.lived(w, members) for w in self.group_works(group))]
        return sorted((w for w in self.works().values() if w["years"] and w["characters"] and not members & set(w["persons"])
                       and any(w["years"][0] <= hi and w["years"][1] >= lo for lo, hi in spans)), key=lambda w: w["work"])

    def weights(self, group: str, own: list[dict[str, Any]], other: list[dict[str, Any]]) -> dict[str, Any]:
        """The weight of each work: a member's works share one unit (the first member named, when a work has two),
        and so do another author's; the other works are reweighed to the school's proportions of forms.  A school
        with one member counts its works one by one."""
        members = self.members.get(group, [])
        unit = {w["work"]: next((f"person:{p}" for p in w["persons"] if p in members), w["author_key"]) for w in own}
        by_works = len(set(unit.values())) < 2
        if by_works:
            unit = {w["work"]: w["work"] for w in own}
        k = Counter(unit.values())
        ws = {w["work"]: 1.0 / k[unit[w["work"]]] for w in own}
        ko = Counter(w["author_key"] for w in other)
        base = {w["work"]: 1.0 / ko[w["author_key"]] for w in other}
        share_s: Counter = Counter()
        for w in own:
            share_s[w["form"]] += ws[w["work"]]
        share_o: Counter = Counter()
        for w in other:
            share_o[w["form"]] += base[w["work"]]
        n1, total_o = sum(ws.values()), sum(base.values())
        mult = {f: (share_s[f] / n1) / (share_o[f] / total_o) if share_o[f] else 0.0 for f in share_o}
        wo = {w["work"]: base[w["work"]] * mult[w["form"]] for w in other}
        matched = sum(base[w["work"]] for w in other if mult[w["form"]] > 0)
        scale = matched / (sum(wo.values()) or 1.0)
        wo = {x: v * scale for x, v in wo.items()}
        return {"own": ws, "other": wo, "units": len(k), "by_works": by_works, "other_units": round(matched, 1),
                "forms": {f: round(share_s[f] / n1, 3) for f in share_s},
                "other_forms": {f: round(share_o[f] / total_o, 3) for f in share_o if share_o[f]}}

    # ------------------------------------------------------------ text samples
    def sample(self, work: dict[str, Any], cap: int) -> list[str]:
        """The Han runs (normalised) of up to ``cap`` characters of the work's own layers, taken evenly through it."""
        key = (work["work"], cap)
        if key in self._samples:
            return self._samples[key]
        bid, years = work["book_id"], work["years"]
        lo, hi = (years[0] - 5, years[1] + 5) if years else (-1e9, 1e9)
        store = getattr(self.b.corpus, "store", None)
        if store is not None:
            with store.lock:
                extra, params = row_filter(self.b.corpus)
                rows = store.db.execute(f"SELECT id, year, LENGTH(text) FROM passages WHERE book_id=? AND kind != 'toc'{extra} "
                                        "ORDER BY seq", (bid, *params)).fetchall()
            ids = self._evenly([(pid, n) for pid, y, n in rows if y is None or lo <= y <= hi], cap)
            texts: list[str] = []
            for i in range(0, len(ids), 900):
                chunk = ids[i: i + 900]
                with store.lock:
                    extra, params = row_filter(self.b.corpus)
                    got = dict(store.db.execute(f"SELECT id, text FROM passages WHERE id IN ({','.join('?' * len(chunk))}){extra}",
                                                [*chunk, *params]).fetchall())
                texts += [got[x] for x in chunk if x in got]
        else:
            ps = [p for p in self.b.corpus.passages(book_ids=[bid]) if p.kind != "toc"
                  and (self.b.year(p) is None or lo <= self.b.year(p) <= hi)]
            keep = set(self._evenly([(p.id, len(p.text)) for p in ps], cap))
            texts = [p.text for p in ps if p.id in keep]
        runs, taken = [], 0
        for r in (r for t in texts for r in _HAN.findall(self.b.normalize(t))):
            runs.append(r[: cap - taken])
            taken += len(runs[-1])
            if taken >= cap:
                break
        if len(self._samples) < 4000:
            self._samples[key] = runs
        return runs

    @staticmethod
    def _evenly(rows: list[tuple[str, int]], cap: int) -> list[str]:
        """Passages at even steps through the work (one in total/cap) until ``cap`` characters are taken."""
        total = sum(n for _, n in rows)
        if total <= cap:
            return [pid for pid, _ in rows]
        step, out, taken, i = total / cap, [], 0, 0.0
        while int(i) < len(rows) and taken < cap:
            pid, n = rows[int(i)]
            out.append(pid)
            taken += n
            i += step
        return out

    # ------------------------------------------------------------ words
    def wordlike(self, g: str) -> bool:
        if g[0] in _EDGE or g[-1] in _END or _NOISE.search(g) or g.endswith("氏") or len(set(g)) == 1:
            return False
        return g not in self._names()

    def _names(self) -> set[str]:
        """Physicians' names and their parts (天士 of 叶天士): cited names go to the citations, not the words."""
        if not hasattr(self, "_name_set"):
            names: set[str] = set()
            for p in self.persons.values():
                for n in _as_list(p.get("names")) + _as_list(p.get("bencao")):
                    key = self.b.normalize(n)
                    if len(key) >= 2:
                        names.add(key)
                        names.update(key[i: i + k] for k in (2, 3) if len(key) > k for i in range(len(key) - k + 1))
            self._name_set = names
        return self._name_set

    @staticmethod
    def candidates(runs_by_unit: dict[str, list[str]], min_units: int, keep: Any) -> set[str]:
        """Words of two to four characters used by at least ``min_units`` units (a four-character word only where its
        three-character parts are, a three-character one where its pairs are), passing ``keep``."""
        prev: set[str] | None = None
        found: set[str] = set()
        for n in (2, 3, 4):
            df: Counter = Counter()
            for runs in runs_by_unit.values():
                seen = set()
                for r in runs:
                    for i in range(len(r) - n + 1):
                        g = r[i: i + n]
                        if prev is None or (g[:-1] in prev and g[1:] in prev):
                            seen.add(g)
                df.update(seen)
            prev = {g for g, k in df.items() if k >= min_units}
            found |= prev
        return {g for g in found if keep(g)}

    def _count(self, works: list[dict[str, Any]], index: dict[str, int], groups: dict[str, dict[str, Any]], cap: int,
               probes: list[str]) -> dict[str, Any]:
        """One pass over the works: for each group and side, the weighted works using each indexed word, its weighted
        occurrences and characters (and the same for the probes)."""
        size = len(index)
        acc = {g: {"df": ([0.0] * size, [0.0] * size), "occ": ([0.0] * size, [0.0] * size), "chars": [0.0, 0.0],
                   "uses": {}, "probe": {p: [0.0, 0.0, 0.0, 0.0] for p in probes}} for g in groups}
        for w in works:
            sides = [(g, 0 if w["work"] in spec["own"] else 1, spec["own"].get(w["work"]) or spec["other"].get(w["work"]))
                     for g, spec in groups.items() if w["work"] in spec["own"] or spec["other"].get(w["work"])]
            if not sides:
                continue
            runs = self.sample(w, cap)
            chars = sum(len(r) for r in runs)
            if not chars:
                continue
            counts: Counter = Counter()
            for r in runs:
                n = len(r)
                for i in range(n - 1):
                    j = index.get(r[i: i + 2])
                    if j is None:
                        continue
                    counts[j] += 1
                    if i + 3 <= n and (j3 := index.get(r[i: i + 3])) is not None:
                        counts[j3] += 1
                        if i + 4 <= n and (j4 := index.get(r[i: i + 4])) is not None:
                            counts[j4] += 1
            joined = "\u3000".join(runs)
            pc = {p: joined.count(p) for p in probes}
            for g, side, weight in sides:
                a = acc[g]
                df, occ = a["df"][side], a["occ"][side]
                for j, k in counts.items():
                    df[j] += weight
                    occ[j] += k * weight
                a["chars"][side] += chars * weight
                if side == 0:
                    a["uses"][w["work"]] = set(counts)
                for p, k in pc.items():
                    a["probe"][p][side] += weight if k else 0.0
                    a["probe"][p][2 + side] += k * weight
        return acc

    @staticmethod
    def _rank(items: dict[str, tuple[float, float, float, float]], n1: float, n0: float, min_units: float,
              totals: tuple[float, float] | None = None, q: float = 0.05) -> list[dict[str, Any]]:
        """Rows of (item, weighted units using it on each side, occurrences on each side) that a larger share of the
        school's units use, ranked by how much more often the school uses them: the z of the log-odds of the rates
        (occurrences over ``totals``, with an informative Dirichlet prior); significant when that z passes
        Benjamini–Hochberg at ``q`` and the share test (log-odds of the shares using it) is one-sided p < 0.05."""
        rows, prate, pshare = [], {}, {}
        for item, (a, c, oa, oc) in items.items():
            if a < min_units - 1e-9 or n1 <= 0 or n0 <= 0:
                continue
            lor, zs = _odds(a, n1, c, n0)
            if lor <= 0:
                continue
            zr = _rate_z(oa, oc, *totals) if totals else zs
            if zr <= 0:
                continue  # more of the school's units use it, but less often: not its word
            prate[item], pshare[item] = normal_sf(zr), normal_sf(zs)
            rows.append({"item": item, "units": round(a, 2), "share": round(a / n1, 3), "other_units": round(c, 2),
                         "other_share": round(c / n0, 3), "share_z": round(zs, 2), "z": round(zr, 2),
                         "occurrences": [round(oa, 1), round(oc, 1)]})
        sig = benjamini_hochberg(prate, q)
        for r in rows:
            r["p"] = float(f"{prate[r['item']]:.3g}")
            r["significant"] = bool(sig.get(r["item"])) and pshare[r["item"]] < 0.05
        rows.sort(key=lambda r: (not r["significant"], -r["z"], r["item"]))
        return rows

    @staticmethod
    def _prune(rows: list[dict[str, Any]], limit: int, pool: int = 400) -> list[dict[str, Any]]:
        """Of a word and a longer one it is nearly always written in (at least 85% of its occurrences on the school's
        side): the longer (达原饮 for 达原, 炙黑甘草 for 炙黑甘) — a part written in several words (营分 in 热入营分,
        营分受热 …) stays."""
        def occ(r: dict[str, Any]) -> float:
            return r["occurrences"][0]

        kept: list[dict[str, Any]] = []
        for r in rows[:pool]:
            g = r["item"]
            if any(g in k["item"] and occ(k) >= 0.85 * occ(r) for k in kept):
                continue  # mostly inside a listed word
            parts = [i for i, k in enumerate(kept) if k["item"] in g and occ(r) >= 0.85 * occ(k)]
            if parts:  # a listed word is mostly inside this one: this one takes its place
                kept[parts[0]] = r
                kept = [k for i, k in enumerate(kept) if i not in parts[1:]]
                continue
            kept.append(r)
        return kept[:limit]

    # ------------------------------------------------------------ the study
    def run(self, school: str | None = None, *, cap: int = 30000, window: int = 60, top: int = 40,
            probes: Iterable[str] = (), cache: str | Path | None = None, refresh: bool = False) -> dict[str, Any]:
        probes = [self.b.normalize(p) for p in probes if p and len(p.strip()) >= 2]
        group = self.resolve(school) if school else None
        key = self._key([group, cap, window, top, sorted(probes)])
        path = Path(cache) / f"schools-{key}.json" if cache is not None else None
        if path is not None and path.exists() and not refresh:
            return json.loads(path.read_text(encoding="utf-8"))
        out = self._one(group, cap=cap, window=window, top=top, probes=probes) if group else \
            self._survey(cap=cap, window=window, top=top, probes=probes)
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        return out

    def _key(self, params: list[Any]) -> str:
        books = sorted((b.id, list(b.authors), b.attribution) for b in self.b.corpus.books.values())
        raw = json.dumps([VERSION, self.b.signature()["corpus_digest"], books, self.schools,
                          sorted((k, v.get("names"), v.get("school"), v.get("branch"), v.get("life"), v.get("active"))
                                 for k, v in self.persons.items()),
                          self.harvest.key(), self.net._cache_key(), params], ensure_ascii=False, default=str)
        return hashlib.sha1(raw.encode()).hexdigest()[:12]

    def _sides(self, names: list[str], window: int) -> dict[str, dict[str, Any]]:
        out = {}
        for g in names:
            own, other = self.group_works(g), self.comparison(g, window=window)
            if own and other:
                out[g] = {"own_works": own, "other_works": other, **self.weights(g, own, other)}
        return out

    def _vocabulary(self, sides: dict[str, dict[str, Any]], *, cap: int, top: int, probes: list[str]) -> dict[str, dict[str, Any]]:
        cands: dict[str, set[str]] = {}
        index: dict[str, int] = {}
        min_units: dict[str, float] = {}
        school_runs: dict[str, list[str]] = {}
        for g, spec in sides.items():
            units: dict[str, list[str]] = defaultdict(list)
            for w in spec["own_works"]:
                u = w["work"] if spec["by_works"] else next((p for p in w["persons"] if p in self.members.get(g, [])), w["work"])
                units[u] += self.sample(w, cap)
            school_runs[g] = [r for rs in units.values() for r in rs]
            min_units[g] = max(2, math.ceil(0.25 * len(units)))
            cands[g] = self.candidates(units, min_units[g], self.wordlike) if len(units) >= 2 else set()
            for c in sorted(cands[g]):
                index.setdefault(c, len(index))
        for c in list(index):  # a word's parts are looked up first (a trigram only after its pair)
            for n in (2, 3):
                for i in range(len(c) - n + 1):
                    index.setdefault(c[i: i + n], len(index))
        all_works = {w["work"]: w for spec in sides.values() for w in spec["own_works"] + spec["other_works"]}
        acc = self._count(sorted(all_works.values(), key=lambda w: w["work"]), index, sides, cap, probes)
        words = {j: g for g, j in index.items()}
        out = {}
        for g, spec in sides.items():
            a = acc[g]
            n1, n0 = sum(spec["own"].values()), sum(spec["other"].values())
            items = {words[j]: (a["df"][0][j], a["df"][1][j], a["occ"][0][j], a["occ"][1][j]) for j in (index[c] for c in cands[g])}
            pool = self._prune(self._rank(items, n1, n0, min_units[g], totals=(a["chars"][0], a["chars"][1])), 400)
            kinds = self._types(school_runs[g], [r["item"] for r in pool])
            by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for r in pool:
                j = index[r["item"]]
                r["type"] = kinds[r["item"]]
                r["per_10k"] = [round(1e4 * r["occurrences"][0] / max(1.0, a["chars"][0]), 2),
                                round(1e4 * r["occurrences"][1] / max(1.0, a["chars"][1]), 2)]
                r["used_in"] = [all_works[w]["title"] for w, used in a["uses"].items() if j in used][:8]
                terms = [e.term_id for e, _ in self.b.pack.lexicon.lookup(r["item"])]
                if terms:
                    r["lexicon"] = terms[0]
                by_type[r["type"]].append(r)
            probe_rows = []
            for p, (pa, pc, oa, oc) in a["probe"].items():
                lor, zs = _odds(pa, n1, pc, n0)
                probe_rows.append({"item": p, "units": round(pa, 2), "share": round(pa / n1, 3), "other_units": round(pc, 2),
                                   "other_share": round(pc / n0, 3), "share_z": round(zs, 2),
                                   "z": round(_rate_z(oa, oc, a["chars"][0], a["chars"][1]), 2),
                                   "per_10k": [round(1e4 * oa / max(1.0, a["chars"][0]), 2), round(1e4 * oc / max(1.0, a["chars"][1]), 2)]})
            out[g] = {"units": round(n1, 2), "other_units": round(n0, 2), "characters": [round(x) for x in a["chars"]],
                      "min_units": min_units[g], "candidates": len(cands[g]), "probes": probe_rows,
                      "words": by_type["词"][:top], "drugs": by_type["药"][: max(10, top // 2)],
                      "formula_words": by_type["方"][: max(10, top // 2)], "serving": by_type["煎服"][:10]}
        return out

    def _types(self, runs: list[str], items: list[str]) -> dict[str, str]:
        """词, 药, 方 or 煎服 of each word: a drug's or a formula's name, or mostly written inside one in the school's
        texts (达原 of 达原饮, 麦门 of 麦门冬); a word of making and taking a medicine; else a word."""
        lex = self.b.pack.lexicon
        text = "\u3000".join(runs)
        mask = bytearray(len(text))
        for m in lex.match(text, include_weak=False):
            code = 1 if m.category == "herb" else 2 if m.category == "formula" else 0
            if code:
                mask[m.start: m.end] = bytes([code]) * (m.end - m.start)
        out = {}
        for g in items:
            cats = {e.category for e, _ in lex.lookup(g)}
            if _SERVING.search(g):
                out[g] = "煎服"
            elif "formula" in cats or g[-1] in "汤丸":
                out[g] = "方"
            elif "herb" in cats:
                out[g] = "药"
            else:
                n = herb = formula = 0
                i = text.find(g)
                while i >= 0 and n < 300:
                    n += 1
                    seg = set(mask[i: i + len(g)])
                    herb += seg == {1}
                    formula += seg == {2}
                    i = text.find(g, i + 1)
                out[g] = "方" if n and formula >= 0.6 * n else ("药" if n and herb >= 0.6 * n else "词")
        return out

    def _examples(self, rows: list[dict[str, Any]], own: list[dict[str, Any]], n: int = 12) -> None:
        books = [w["book_id"] for w in own]
        for r in rows[:n]:
            for p in self.b.passages(self.b.find(r["item"], book_ids=books, limit=3)[:3]):
                i = self.b.normalize(p.text).find(r["item"])
                if i >= 0:
                    r["example"] = self.b.witness(p, start=i, end=i + len(r["item"]), width=20)
                    break

    def _formulas(self, sides: dict[str, dict[str, Any]], top: int) -> dict[str, list[dict[str, Any]]]:
        built = self.harvest.build(self.b.cache_dir() if hasattr(self.b, "cache_dir") else None)
        self.works()
        by_work: dict[str, Counter] = defaultdict(Counter)
        for row in built["compositions"] + built["indications"]:
            for unit in self.units_of_work.get(row[0], [row[0]]):
                by_work[unit][row[1]] += 1
        lex = self.b.pack.lexicon
        out = {}
        for g, spec in sides.items():
            n1, n0 = sum(spec["own"].values()), sum(spec["other"].values())
            items: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
            for side, weights in ((0, spec["own"]), (1, spec["other"])):
                for wk, weight in weights.items():
                    for fid, k in by_work.get(wk, {}).items():
                        items[fid][side] += weight
                        items[fid][2 + side] += k * weight
            units = len({w["work"] for w in spec["own_works"]}) if spec["by_works"] else spec["units"]
            totals = (sum(v[2] for v in items.values()), sum(v[3] for v in items.values()))
            rows = self._rank({f: (v[0], v[1], v[2], v[3]) for f, v in items.items()}, n1, n0, max(2, math.ceil(0.2 * units)),
                              totals=totals)[:top]
            for r in rows:
                entry = lex.entry(r["item"])
                r["name"] = entry.term if entry else r["item"].split(":", 1)[-1]
                r["used_in"] = [w["title"] for w in spec["own_works"] if r["item"] in by_work.get(w["work"], {})][:8]
            out[g] = rows
        return out

    # ------------------------------------------------------------ citations
    def _citations(self) -> dict[str, Any]:
        """Per work (its most-citing transcription): physicians named, rejected and endorsed (a citation dated before
        the physician — a later layer's note dated with its text — left out)."""
        if hasattr(self, "_cites"):
            return self._cites
        built = self.net.build(self.b.cache_dir() if hasattr(self.b, "cache_dir") else None)
        per_book: dict[str, dict[str, Counter]] = defaultdict(lambda: {"persons": Counter(), "rejects": Counter(), "endorses": Counter()})
        for kind in ("persons", "rejects", "endorses"):
            for key, people in (built.get(kind) or {}).items():
                bid = key.split("|", 1)[0]
                for person, n in people.items():
                    if not self.net._anachronistic(key, f"person:{person}"):
                        per_book[bid][kind][person] += n
        book_work = {b: w["work"] for w in self.works().values() for b in w["books"]}
        best: dict[str, str] = {}
        for bid, d in per_book.items():
            wk = book_work.get(bid)
            if wk and (wk not in best or sum(d["persons"].values()) > sum(per_book[best[wk]]["persons"].values())):
                best[wk] = bid
        self._cites = {"works": {wk: per_book[bid] for wk, bid in best.items()}, "book": best,
                       "examples": built.get("reject_examples") or {}}
        return self._cites

    def _person_row(self, pid: str) -> dict[str, Any]:
        p = self.persons.get(pid, {})
        return {"person": pid, "name": p.get("name", pid), "school": _as_list(p.get("school")), "branch": p.get("branch"),
                "field": p.get("field"), "dates": p.get("life") or p.get("active")}

    def citation_profile(self, group: str, spec: dict[str, Any], top: int = 20) -> dict[str, Any]:
        cites = self._citations()["works"]
        works = self.works()
        members = set(self.members.get(group, []))
        n1, n0 = sum(spec["own"].values()), sum(spec["other"].values())
        items: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
        totals = [0.0, 0.0]
        to_members = [0.0, 0.0]
        for side, weights in ((0, spec["own"]), (1, spec["other"])):
            for wk, weight in weights.items():
                for p, n in cites.get(wk, {}).get("persons", Counter()).items():
                    items[p][side] += weight
                    items[p][2 + side] += n * weight
                    totals[side] += n * weight
                    to_members[side] += n * weight if p in members else 0.0
        rows = self._rank({p: (v[0], v[1], v[2], v[3]) for p, v in items.items()}, n1, n0, max(2, math.ceil(0.2 * spec["units"])),
                          totals=(totals[0], totals[1]))
        for r in rows:
            r.update({k: v for k, v in self._person_row(r["item"]).items() if k != "person"})
        own_share = to_members[0] / totals[0] if totals[0] else None
        other_share = to_members[1] / totals[1] if totals[1] else None
        cites_schools: Counter = Counter()
        for p, v in items.items():
            for s in _as_list(self.persons.get(p, {}).get("school")) or [NO_SCHOOL]:
                cites_schools[s] += v[2]
        member_works = set(spec["own"])
        cited_by: Counter = Counter()
        citing: list[dict[str, Any]] = []
        rejects: Counter = Counter()
        rejected_by: Counter = Counter()
        reject_rows: list[dict[str, Any]] = []
        examples, book_of = self._citations()["examples"], self._citations()["book"]
        for wk, c in cites.items():
            w = works.get(wk)
            if w is None:
                continue
            if wk in member_works:
                for p, k in c["rejects"].items():
                    for s in _as_list(self.persons.get(p, {}).get("school")) or [NO_SCHOOL]:
                        rejects[s] += k
                continue
            n = sum(k for p, k in c["persons"].items() if p in members)
            r = sum(k for p, k in c["rejects"].items() if p in members)
            if n:
                for s in w["schools"] or [NO_SCHOOL]:
                    cited_by[s] += n
                citing.append({"work": wk, "title": w["title"], "years": w["years"], "schools": w["schools"], "citations": n})
            if r:
                for s in w["schools"] or [NO_SCHOOL]:
                    rejected_by[s] += r
                reject_rows.append({"work": wk, "title": w["title"], "years": w["years"], "schools": w["schools"], "rejections": r,
                                    "rejected": sorted({self.persons[p]["name"] for p, k in c["rejects"].items() if p in members}),
                                    "examples": [e for p in sorted(members) for e in examples.get(f"{book_of[wk]}|{p}", [])][:3]})
        citing.sort(key=lambda x: (-x["citations"], dated(x["years"])))
        reject_rows.sort(key=lambda x: (-x["rejections"], dated(x["years"])))
        lineage: Counter = Counter()
        for w in spec["own_works"]:
            for p, n in cites.get(w["work"], {}).get("persons", Counter()).items():
                for a in w["persons"]:
                    if p in members and a in members and a != p:
                        lineage[(a, p)] += n
        return {
            "cited": rows[:top],
            "homophily": {"own_share": round(own_share, 4) if own_share is not None else None,
                          "other_share": round(other_share, 4) if other_share is not None else None,
                          "ratio": round(own_share / other_share, 2) if own_share and other_share else None},
            "cites_schools": {k: round(v, 1) for k, v in cites_schools.most_common() if v > 0},
            "cited_by_schools": dict(cited_by.most_common()), "citing_works": citing[:top],
            "rejects_schools": dict(rejects.most_common()), "rejected_by_schools": dict(rejected_by.most_common()),
            "rejected_by": reject_rows[:top],
            "lineage": [{"from": self.persons[a]["name"], "to": self.persons[b]["name"], "citations": n,
                         "from_dates": self.persons[a].get("life") or self.persons[a].get("active"),
                         "to_dates": self.persons[b].get("life") or self.persons[b].get("active")}
                        for (a, b), n in lineage.most_common(top)],
        }

    # ------------------------------------------------------------ views
    def _members(self, group: str, own: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        for pid in self.members.get(group, []):
            works = [{"work": w["work"], "title": w["title"], "years": w["years"], "category": w["category"], "book_id": w["book_id"]}
                     for w in own if pid in w["persons"]]
            rows.append({**self._person_row(pid), "works": works})
        rows.sort(key=lambda r: (dated(r["dates"]), r["name"]))
        return rows

    def _describe(self, group: str) -> dict[str, Any]:
        school = group.split("·")[0]
        spec = self.schools.get(school, {})
        return {"school": group, "label": spec.get("label", school) + (f"·{group.split('·')[1]}" if "·" in group else ""),
                "parent": spec.get("parent") if "·" not in group else school,
                "founder": self._person_row(spec["founder"]) if "·" not in group and spec.get("founder") in self.persons else None,
                "source": [self._person_row(p) for p in _as_list(spec.get("source")) if p in self.persons],
                "note": (spec.get("branches") or {}).get(group.split("·")[1]) if "·" in group else spec.get("note")}

    def _one(self, group: str, *, cap: int, window: int, top: int, probes: list[str]) -> dict[str, Any]:
        sides = self._sides([group], window)
        own = self.group_works(group)
        out = {**self._describe(group), "members": self._members(group, own), "works": len(own),
               "span": [min(w["years"][0] for w in own), max(w["years"][1] for w in own)] if own else None}
        if group not in sides:
            return {**out, "note_method": "no works of the school (or none of their time) in the store"}
        spec = sides[group]
        vocab = self._vocabulary(sides, cap=cap, top=top, probes=probes)[group]
        self._examples(vocab["words"], own)
        return {**out, "comparison": {"works": len(spec["other_works"]), "units": spec["units"], "other_units": spec["other_units"],
                                      "by_works": spec["by_works"], "window": window, "cap": cap, "characters_read": vocab["characters"],
                                      "forms": spec["forms"], "other_forms": spec["other_forms"]},
                "vocabulary": vocab["words"], "drugs": vocab["drugs"], "formula_words": vocab["formula_words"],
                "serving": vocab["serving"], "probes": vocab["probes"], "min_units": vocab["min_units"],
                "formulas": self._formulas(sides, top)[group], "citations": self.citation_profile(group, spec),
                "note_method": "the school's physicians (each counting once) against the other authors of their time (±window "
                               "years, reweighed to the school's forms: 论著 医案 方书 本草 歌赋); words ranked by the z of the "
                               "log-odds of their rates with an informative Dirichlet prior (Monroe, Colaresi & Quinn 2008), "
                               "significant when that z passes Benjamini–Hochberg (q=0.05) and more of the school's physicians "
                               "use the word (share test, p<0.05); a commentary carries its classic's words; memberships are "
                               "the textbooks' conventions, and a word is not a doctrine until its passages are read"}

    def _survey(self, *, cap: int, window: int, top: int, probes: list[str]) -> dict[str, Any]:
        sides = self._sides(list(self.members), window)
        vocab = self._vocabulary(sides, cap=cap, top=max(top, 12), probes=probes)
        formulas = self._formulas(sides, 6)
        rows = []
        for g in self.members:
            own = self.group_works(g)
            row = {**self._describe(g), "members": len(self.members[g]),
                   "members_with_works": sum(1 for m in self._members(g, own) if m["works"]), "works": len(own),
                   "span": [min(w["years"][0] for w in own), max(w["years"][1] for w in own)] if own else None}
            if g in sides:
                prof = self.citation_profile(g, sides[g], top=5)
                row.update({"units": sides[g]["units"], "other_units": sides[g]["other_units"], "by_works": sides[g]["by_works"],
                            "words": [{k: r[k] for k in ("item", "share", "other_share", "z", "significant")} for r in vocab[g]["words"][:12]],
                            "probes": vocab[g]["probes"],
                            "formulas": [{k: r[k] for k in ("name", "share", "other_share", "z", "significant")} for r in formulas[g][:6]],
                            "homophily": prof["homophily"], "cited": [{"name": r["name"], "z": r["z"]} for r in prof["cited"][:5]]})
            rows.append(row)
        return {"schools": rows, "matrix": self.matrix(), "window": window, "cap": cap,
                "note": "each school (and branch) against the other authors of its time, reweighed to its forms"}

    def matrix(self) -> dict[str, Any]:
        """Citations (and rejections) from the works of each school to the physicians of each school, with the ratio
        of each row's share to the column's share of all citations between schools."""
        cites = self._citations()["works"]
        works = self.works()
        schools = list(self.schools)
        counts = {k: {a: Counter() for a in schools} for k in ("persons", "rejects")}
        for wk, c in cites.items():
            w = works.get(wk)
            if w is None or not w["schools"]:
                continue
            for kind in ("persons", "rejects"):
                for p, n in c[kind].items():
                    for b in _as_list(self.persons.get(p, {}).get("school")):
                        for a in w["schools"]:
                            if a in counts[kind] and b in schools:
                                counts[kind][a][b] += n
        col: Counter = Counter()
        for a in schools:
            col.update(counts["persons"][a])
        total = sum(col.values()) or 1
        rows = []
        for a in schools:
            row_total = sum(counts["persons"][a].values())
            if not row_total and not sum(counts["rejects"][a].values()):
                continue
            rows.append({"school": a, "citations": row_total,
                         "to": {b: {"citations": n, "share": round(n / row_total, 3) if row_total else None,
                                    "ratio": round((n / row_total) / (col[b] / total), 2) if row_total and col[b] else None}
                                for b, n in counts["persons"][a].most_common()},
                         "rejects": dict(counts["rejects"][a].most_common())})
        return {"rows": rows, "columns": {b: col[b] for b in schools if col[b]}}


__all__ = ["FORMS", "SchoolStudy", "form_of"]
