"""地域 — time × person × place (T27): where the physicians came from, where the works were signed, and how the
vocabulary of the literature is spread over the regions of China period by period.

Places come from three sources, kept apart:

* **curated** — the native place (籍贯) of the physicians of ``physicians.yaml`` (``native``), as the reference works
  give it;
* **signed** — the place a preface or colophon puts before its writer's name (「新安汪机撰」「吴门叶桂天士著」「云间李中梓
  识」), read in the first and last passages of every book;
* **stated** — the place a text gives for a person (「李杲，字明之，真定人」), read where the person is named.

Each place is one of ``places.yaml`` (historical names normalised to a place with its modern province, a macro-region
and approximate coordinates).  A work is placed by its author's native place, else by its signature; its date is the
work's composition.  Then:

* ``study places`` — physicians and works by region and period, the most frequent places, points for a map (GeoJSON);
* ``--person 叶桂`` — a physician's place: curated, and what the texts state and sign;
* ``--school 温病`` — where a school's physicians came from;
* ``--term 湿热`` — in each period, the share of works from each region that use a term, against the other regions'
  (two-proportion z, Benjamini–Hochberg): the question 「江南湿热理论为何兴起」 asked of the texts;
* a place name — the physicians from it and the works signed or written there.

A region is a convenience for statistics (see places.yaml): the counts are of the works that survive and are in the
store, placed by their authors' origin, not by where they were read.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Any

from .base import StudyBase, dated

# verbs of writing; 序 识 书 题 跋 only at the end of the signature (before a mark, 于, or the end), where they cannot be
# the nouns they also are (诸书, 序文)
VERBS = (r"(?:谨撰|拜撰|撰次|编次|重订|集注|辑注|评注|谨序|谨识|谨书|拜手|撰|著|述|编|辑|纂|注|校|订|评"
         r"|(?:序|识|书|题|跋)(?=[，。、；：」』）\s]|于|$))")


def _z_two(k1: int, n1: int, k2: int, n2: int) -> tuple[float, float]:
    """Two-proportion z and its two-sided p (pooled)."""
    if not n1 or not n2:
        return 0.0, 1.0
    p = (k1 + k2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2)) if 0 < p < 1 else 0.0
    if se == 0:
        return 0.0, 1.0
    z = (k1 / n1 - k2 / n2) / se
    return z, math.erfc(abs(z) / math.sqrt(2))


def _bh(ps: list[float]) -> list[float]:
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    q = [1.0] * len(ps)
    running = 1.0
    for rank, i in reversed(list(enumerate(order, start=1))):
        running = min(running, ps[i] * len(ps) / rank)
        q[i] = running
    return q


class PlaceStudy:
    def __init__(self, base: StudyBase, network: Any) -> None:
        self.b = base
        self.net = network
        data = base.data("places.yaml")
        self.regions: list[str] = list(data.get("regions", []))
        self.places: dict[str, dict[str, Any]] = {p["id"]: p for p in data.get("places", [])}
        self.by_name: dict[str, list[str]] = defaultdict(list)
        for p in self.places.values():
            for name in p.get("names", []):
                self.by_name[self.b.normalize(name)].append(p["id"])
        self.persons: dict[str, dict[str, Any]] = {p["id"]: p for p in base.data("physicians.yaml").get("persons", [])}
        self.alias: dict[str, str] = {}
        for p in self.persons.values():
            for name in p.get("names", []):
                if len(self.b.normalize(name)) >= 2:
                    self.alias.setdefault(self.b.normalize(name), p["id"])
        names = sorted((n for n in self.by_name if len(n) >= 2), key=len, reverse=True)
        people = sorted(self.alias, key=len, reverse=True)
        self._place_re = "(?:" + "|".join(map(re.escape, names)) + ")" if names else "(?!)"
        self._person_re = "(?:" + "|".join(map(re.escape, people)) + ")" if people else "(?!)"
        # a known physician may carry his 字 or 号 before the verb (钱塘张志聪隐庵集注, 河间刘完素守真序); another name
        # (two to five characters: a name and its 字, 程国彭钟龄) must meet the verb at once
        self._sign_known = re.compile(rf"(?P<place>{self._place_re})(?P<name>{self._person_re})"
                                      rf"(?:[，、 ]?(?:字|号)?[一-鿿]{{1,3}}?)?[，、 ]?(?P<verb>{VERBS})")
        self._sign = re.compile(rf"(?P<place>{self._place_re})(?P<name>[一-鿿]{{2,5}}?)(?P<verb>{VERBS})")
        # 「李杲，字明之，真定人」; a prefecture before its county (婺州义乌人) names the county
        self._stated = re.compile(rf"(?P<name>{self._person_re})[，,]?(?:字[一-鿿]{{1,3}}[，,]?)?(?:号[一-鿿]{{1,4}}[，,]?)?"
                                  rf"(?P<place>(?:{self._place_re}){{1,2}})人")
        self._one_place = re.compile(self._place_re)
        self._works: dict[str, dict[str, Any]] | None = None

    # ------------------------------------------------------------ places and people
    def place(self, pid: str | None) -> dict[str, Any] | None:
        p = self.places.get(pid or "")
        if p and p.get("same_as"):
            p = self.places.get(p["same_as"], p)
        return p

    def same_area(self, a: str | None, b: str | None) -> bool:
        """Whether two places are one, or one lies in the other (义乌 in 金华)."""
        if not a or not b:
            return False
        pa, pb = self.place(a), self.place(b)
        if pa is None or pb is None:
            return False
        return pa["id"] == pb["id"] or pa.get("in") == pb["id"] or pb.get("in") == pa["id"]

    def place_of_name(self, name: str) -> dict[str, Any] | None:
        ids = self.by_name.get(self.b.normalize(name)) or []
        return self.place(ids[0]) if ids else None

    def _row(self, p: dict[str, Any] | None) -> dict[str, Any]:
        if not p:
            return {"place": None, "place_name": None, "region": None, "province": None, "lat": None, "lon": None}
        return {"place": p["id"], "place_name": p["names"][0], "region": p.get("region"), "province": p.get("province"),
                "lat": p.get("lat"), "lon": p.get("lon")}

    @staticmethod
    def person_years(person: dict[str, Any]) -> list[float] | None:
        span = person.get("life") or person.get("active")
        return [float(span[0]), float(span[1])] if span else None

    def person_row(self, pid: str) -> dict[str, Any]:
        person = self.persons[pid]
        years = self.person_years(person)
        mid = (years[0] + years[1]) / 2 if years else None
        per = self.b.period_of(mid)
        school = person.get("school")
        return {"person": pid, "name": person.get("name"), "dynasty": person.get("dynasty"), "years": years,
                "period": per.label if per else None, "school": school if isinstance(school, (str, type(None))) else "、".join(school),
                "source": "curated" if person.get("native") else None, **self._row(self.place(person.get("native")))}

    # ------------------------------------------------------------ works
    def _edge_passages(self, book_id: str, n: int = 4) -> list[Any]:
        store = getattr(self.b.corpus, "store", None)
        if store is not None:
            with store.lock:
                ids = [r[0] for r in store.db.execute(
                    "SELECT id FROM (SELECT id, seq FROM passages WHERE book_id=? AND kind != 'toc' ORDER BY seq LIMIT ?) "
                    "UNION SELECT id FROM (SELECT id, seq FROM passages WHERE book_id=? AND kind != 'toc' ORDER BY seq DESC LIMIT ?)",
                    (book_id, n, book_id, n)).fetchall()]
            return self.b.passages(ids)
        ps = [p for p in self.b.corpus.passages(book_ids=[book_id]) if p.kind != "toc"]
        return ps[:n] + [p for p in ps[-n:] if p not in ps[:n]]

    def signatures(self, book_id: str) -> list[dict[str, Any]]:
        """The places the first and last passages of a book sign before a writer's name."""
        out = []
        for p in self._edge_passages(book_id):
            out += self.read_signatures(p)
        return out

    def read_signatures(self, p: Any, text: str | None = None) -> list[dict[str, Any]]:
        """Place + writer + verb (撰 著 序 识 集注 …) in a passage (or a text)."""
        out: list[dict[str, Any]] = []
        norm = self.b.normalize(text if text is not None else p.text)
        seen: set[int] = set()
        for reg in (self._sign_known, self._sign):
            for m in reg.finditer(norm):
                if m.start() in seen:
                    continue
                seen.add(m.start())
                name = m.group("name")
                person = self.alias.get(name) or next((pid for n, pid in self.alias.items() if name.startswith(n)), None)
                place = self.place_of_name(m.group("place"))
                if place is None:
                    continue
                named = self.alias.get(m.group("place"))
                if (named and named != person) or re.search(r"[诸等之与及并]", m.group(0)):
                    continue  # a list of physicians (河间东垣丹溪诸书: 河间 is 刘完素), not a place and its writer
                out.append({"place": place["id"], "name": name, "person": person, "verb": m.group("verb"),
                            "witness": self.b.witness(p, start=m.start(), end=m.end()) if p is not None else None})
        return out

    def read_stated(self, text: str) -> list[dict[str, Any]]:
        """「name，(字…，)place人」: the place a text states for a physician."""
        out = []
        for m in self._stated.finditer(self.b.normalize(text)):
            place = self.place_of_name(self._one_place.findall(m.group("place"))[-1])
            if place is not None:
                out.append({"place": place["id"], "person": self.alias.get(m.group("name")), "name": m.group("name")})
        return out

    def works(self) -> dict[str, dict[str, Any]]:
        """Each work of the store placed: by its author's native place, else by the place its preface or colophon signs."""
        if self._works is not None:
            return self._works
        out: dict[str, dict[str, Any]] = {}
        for bid, book in sorted(self.b.corpus.books.items()):
            unit = book.work or bid
            if unit in out and out[unit]["place"]:
                continue
            years = [book.composition.start, book.composition.end] if book.composition else None
            per = self.b.period_of((years[0] + years[1]) / 2 if years else None)
            row: dict[str, Any] = {"work": unit, "title": book.title, "book_id": bid, "years": years,
                                   "period": per.label if per else None, "how": None, "person": None, "evidence": None}
            persons = sorted(self.net.persons_of_book(bid)) if self.net is not None else []
            placed = next((pid for pid in persons if self.persons.get(pid, {}).get("native")), None)
            if placed:
                row.update(self._row(self.place(self.persons[placed]["native"])), how="author", person=placed)
            else:
                signed = self.signatures(bid)
                if signed:
                    s = signed[0]
                    row.update(self._row(self.place(s["place"])), how="signed", person=s["person"], evidence=s["witness"])
                else:
                    row.update(self._row(None))
            out[unit] = row
        self._works = out
        return out

    # ------------------------------------------------------------ views
    def run(self, target: str | None = None, *, term: str | None = None, school: str | None = None,
            person: str | None = None, limit: int = 60) -> dict[str, Any]:
        if term:
            return self.term(term, limit=limit)
        if school:
            return self.school(school)
        if person:
            return self.person(person)
        if target:
            return self.one_place(target, limit=limit)
        return self.overview(limit=limit)

    def overview(self, *, limit: int = 60) -> dict[str, Any]:
        people = [self.person_row(pid) for pid in self.persons]
        works = list(self.works().values())
        table: dict[str, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: {"physicians": 0, "works": 0}))
        for r in people:
            if r["region"] and r["period"]:
                table[r["region"]][r["period"]]["physicians"] += 1
        for w in works:
            if w["region"] and w["period"]:
                table[w["region"]][w["period"]]["works"] += 1
        places = Counter(r["place_name"] for r in people + works if r["place_name"])
        by_how = Counter(w["how"] or "unplaced" for w in works)
        return {"view": "overview", "regions": self.regions, "periods": [per.label for per in self.b.periods],
                "physicians": sorted(people, key=lambda r: (r["years"] or [9999])[0])[:200],
                "works": sorted((w for w in works if w["place"]), key=lambda w: dated(w["years"]))[:limit],
                "by_region_period": {rg: dict(v) for rg, v in table.items()},
                "top_places": [{"place": p, "count": n} for p, n in places.most_common(25)],
                "placed": {"physicians": sum(1 for r in people if r["place"]), "physicians_total": len(people),
                           "works": sum(1 for w in works if w["place"]), "works_total": len(works), "works_by": dict(by_how)},
                "geojson": self.geojson(people, [w for w in works if w["place"]]),
                "note": "physicians placed by their native place (physicians.yaml); works by their author's native place, "
                        "else the place their preface or colophon signs; a region is a convenience for statistics"}

    def person(self, name: str) -> dict[str, Any]:
        pid = self.alias.get(self.b.normalize(name)) or (name if name in self.persons else None)
        if pid is None:
            raise KeyError(f"{name} is not in physicians.yaml")
        row = self.person_row(pid)
        stated: list[dict[str, Any]] = []
        names = [n for n in self.persons[pid].get("names", []) if len(self.b.normalize(n)) >= 2]
        for n in names:
            for p in self.b.passages(self.b.find(n, limit=300)):
                norm = self.b.normalize(p.text)
                for m in self._stated.finditer(norm):
                    if self.alias.get(m.group("name")) != pid:
                        continue
                    place = self.place_of_name(self._one_place.findall(m.group("place"))[-1])
                    if place:
                        stated.append({"place": place["id"], "place_name": place["names"][0], "how": "stated",
                                       "witness": self.b.witness(p, start=m.start(), end=m.end())})
        signed = []
        for w in self.works().values():
            if w["how"] == "signed" and w["person"] == pid:
                signed.append({"place": w["place"], "place_name": w["place_name"], "how": "signed", "witness": w["evidence"]})
        places = Counter(x["place"] for x in stated + signed)
        agree = any(self.same_area(row["place"], p) for p in places) if row["place"] and places else None
        return {"view": "person", "person": row, "stated": stated[:40], "signed": signed[:20],
                "places_in_texts": [{"place": p, "place_name": self.places[p]["names"][0], "count": n} for p, n in places.most_common()],
                "curated_confirmed": agree, "geojson": self.geojson([row], []),
                "note": "curated: physicians.yaml; stated: 「name，(字…)，place人」 where the texts name him; signed: a preface "
                        "or colophon placing him"}

    def school(self, school: str) -> dict[str, Any]:
        key = school.removesuffix("学派").removesuffix("派")
        members = [pid for pid, p in self.persons.items()
                   if key == p.get("school") or (isinstance(p.get("school"), list) and key in p["school"])
                   or p.get("branch") == key]
        if not members:
            raise KeyError(f"no physician of physicians.yaml is counted in {school}")
        rows = [self.person_row(pid) for pid in members]
        regions = Counter(r["region"] or "未详" for r in rows)
        base = Counter(self.person_row(pid)["region"] or "未详" for pid in self.persons)
        return {"view": "school", "school": key, "members": sorted(rows, key=lambda r: (r["years"] or [9999])[0]),
                "by_region": [{"region": rg, "members": n, "share": round(n / len(rows), 3),
                               "all_physicians_share": round(base[rg] / len(self.persons), 3)} for rg, n in regions.most_common()],
                "geojson": self.geojson(rows, []),
                "note": "members as physicians.yaml counts them; the share of all physicians of the list is the baseline"}

    def one_place(self, name: str, *, limit: int = 60) -> dict[str, Any]:
        place = self.place_of_name(name)
        if place is None:
            raise KeyError(f"{name} is not a place of places.yaml")
        inside = {pid for pid, x in self.places.items() if pid == place["id"] or x.get("in") == place["id"] or x.get("same_as") == place["id"]}
        people = [self.person_row(pid) for pid, p in self.persons.items() if p.get("native") in inside]
        works = [w for w in self.works().values() if w["place"] in inside]
        return {"view": "place", "place": {**self._row(place), "names": place["names"], "level": place.get("level")},
                "physicians": people, "works": sorted(works, key=lambda w: dated(w["years"]))[:limit],
                "geojson": self.geojson(people, works), "note": "physicians native to the place and works placed there"}

    def term(self, term: str, *, limit: int = 60, min_works: int = 3, max_passages: int = 30000) -> dict[str, Any]:
        """In each period: the share of the works of each region that use the term, against the other regions'."""
        _, found = self.b.surfaces(term)
        forms = [f for f, _ in found] or [term]
        ids: set[str] = set()
        for f in forms:
            ids.update(self.b.find(f, limit=max_passages))
        with_term = {(self.b.corpus.books[bid].work or bid) for bid in self.b.book_counts(sorted(ids)) if bid in self.b.corpus.books}
        works = [w for w in self.works().values() if w["region"] and w["period"]]
        cells: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
        per_total: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for w in works:
            hit = int(w["work"] in with_term)
            cells[(w["period"], w["region"])][0] += hit
            cells[(w["period"], w["region"])][1] += 1
            per_total[w["period"]][0] += hit
            per_total[w["period"]][1] += 1
        rows = []
        for (per, rg), (k, n) in cells.items():
            K, N = per_total[per]
            if n < min_works or N - n < min_works:
                continue
            z, p = _z_two(k, n, K - k, N - n)
            rows.append({"period": per, "region": rg, "works_with": k, "works": n, "share": round(k / n, 3),
                         "rest_share": round((K - k) / (N - n), 3), "z": round(z, 2), "p": p})
        qs = _bh([r["p"] for r in rows]) if rows else []
        for r, q in zip(rows, qs):
            r["q"] = round(q, 4)
            r["p"] = round(r["p"], 4)
            r["significant"] = q < 0.05 and r["z"] > 0
        order = {per.label: i for i, per in enumerate(self.b.periods)}
        rows.sort(key=lambda r: (order.get(r["period"], 99), -r["share"]))
        examples = [w for w in works if w["work"] in with_term]
        return {"view": "term", "term": term, "forms": forms, "works_with_term": len(with_term),
                "placed_works_with_term": len(examples), "rows": rows,
                "leading": [r for r in rows if r["significant"]][:20],
                "works": sorted(examples, key=lambda w: dated(w["years"]))[:limit],
                "geojson": self.geojson([], examples),
                "note": "works placed by their author's native place (else their signature); a work counts once; each "
                        "region against the other regions of the same period (two-proportion z, Benjamini–Hochberg); "
                        "a region leads a term's use — it does not prove the doctrine arose there"}

    # ------------------------------------------------------------ map
    @staticmethod
    def geojson(people: list[dict[str, Any]], works: list[dict[str, Any]]) -> dict[str, Any]:
        feats = []
        for r in people:
            if r.get("lat") is not None:
                feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
                              "properties": {"kind": "physician", "name": r["name"], "place": r["place_name"],
                                             "region": r["region"], "years": r["years"], "school": r.get("school")}})
        for w in works:
            if w.get("lat") is not None:
                feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [w["lon"], w["lat"]]},
                              "properties": {"kind": "work", "title": w["title"], "place": w["place_name"],
                                             "region": w["region"], "years": w["years"], "how": w["how"]}})
        return {"type": "FeatureCollection", "features": feats,
                "note": "approximate coordinates (the modern seat of each place), for maps only"}


__all__ = ["PlaceStudy"]
