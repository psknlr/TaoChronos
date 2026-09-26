"""药性源流 — what the materia medica say about one drug, book by book, from the 本经 to the Qing.

The entry of the drug is located in each 本草 book (the name at the head of a passage, as its heading, or followed by
味/气/性), and the properties are read from it verbatim:

* 性味 — flavours (酸苦甘辛咸淡涩) and nature (寒热温凉平, with 大/微);
* 毒性 — 有毒 / 无毒 / 小毒 / 大毒;
* 归经 — the channels and organs it enters (入手太阴经, 专入肺, 足阳明经药 …), a doctrine of the Jin–Yuan physicians;
* 升降浮沉 — ascending, descending, floating, sinking (阳中之阴 …);
* 主治 — the indications, and 一名 — its other names.

The first statement of each property (earliest 归经, first mention of 有毒 …) and the changes between periods are what a
history of pharmacology asks; every field keeps its quote and locator.  Formats vary widely between books, so the
reading is by rule and marked as machine-read.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from .base import StudyBase, dated, han_only

FLAVORS = "酸苦甘辛咸淡涩"
NATURE = r"(大寒|微寒|寒|大热|微热|热|大温|微温|温|微凉|凉|平)"
ORGANS = ["心包络", "心包", "包络", "命门", "三焦", "膀胱", "大肠", "小肠", "肺", "脾", "胃", "心", "肝", "胆", "肾"]
CHANNEL = r"(?:手|足)(?:太阴|少阴|厥阴|太阳|阳明|少阳)"
_FLAVOR = re.compile(rf"(?:气味|性味|味)[：:]?\s*([{FLAVORS}]{{1,3}})")
_NATURE = re.compile(rf"(?:性|气)[：:]?\s*{NATURE}|[{FLAVORS}]{{1,3}}[，、,\s]*{NATURE}")
_TOXIC = re.compile(r"(大毒|小毒|微毒|有毒|无毒)")
_ENTER = re.compile(rf"(?:专入|兼入|入|归|行|走)((?:{CHANNEL}|{'|'.join(ORGANS)})(?:[、，,及与兼]?(?:{CHANNEL}|{'|'.join(ORGANS)}))*)(?:二|三|四)?(?:经|之经|脏|藏)?"
                    rf"|((?:{CHANNEL})(?:[、，,]?{CHANNEL})*)经(?:之)?药")
_CHANNEL_TOKEN = re.compile(rf"{CHANNEL}|{'|'.join(ORGANS)}")
_DIRECTION = re.compile(r"(可升可降|浮而升|沉而降|升而浮|降而沉|阳中之阴|阴中之阳|阳中之阳|阴中之阴|纯阳|纯阴|(?:升|降|浮|沉)也)")
_INDICATION = re.compile(r"(?:【主治】|主治[：:]|功用[：:]|主(?![之人])(?:治)?)([^。；【]{2,90})")
_ALIAS = re.compile(r"一名([^，。、；一]{1,6})")
_BENCAO_TITLE = re.compile(r"(本草|药性|藥性|药品|藥品|食疗|食療|食物|饮膳|飲膳|药鉴|藥鑑|药赋|藥賦|药解|藥解)")


_NEXT_ENTRY = re.compile(rf"^[（(〔【\s　]*(?:味|气味|性味|[{FLAVORS}]{{1,2}}[，、,]?(?:大|微)?(?:寒|热|温|凉|平))")
_PROPERTY_AFTER = re.compile(rf"^[（(〔【\s　]*(?:[^。，]{{0,6}}[）)〕】])?[\s　]*(?:气味|性味|味|气|性)[：:]?\s*(?:[{FLAVORS}]|寒|热|温|凉|平|大|微|纯)")


class HerbStudy:
    def __init__(self, base: StudyBase) -> None:
        self.b = base

    def books(self) -> list[str]:
        return sorted(bk.id for bk in self.b.corpus.books.values()
                      if bk.category == "本草" or _BENCAO_TITLE.search(bk.title))

    def heading_index(self) -> dict[str, list[tuple[str, int, str]]]:
        """Normalised entry heading → [(book, seq, passage)] in the 本草 books."""
        return self.b.heading_index(self.books(), "bencao")

    # ------------------------------------------------------------ entries
    def _entry_start(self, p: Any, norm: str, forms: list[str]) -> int | None:
        """Position of the drug's entry in a passage: the name followed by its flavour or nature (黄芪味甘微温,
        附子（本经下品）气味辛温), where the passage begins or anywhere in a list of entries."""
        for f in forms:
            for m in re.finditer(re.escape(f), norm):
                if re.search(r"(药名|名称|藥名|名稱)[：:]\s*$", norm[max(0, m.start() - 4): m.start()]) and \
                        re.search(r"(性味|气味)[：:]", norm[m.end(): m.end() + 80]):
                    return m.start()  # structured entries: 药名：黄芪 … 性味：甘温
                if m.start() > 0 and "\u4e00" <= norm[m.start() - 1] <= "\u9fff" and norm[m.start() - 1] not in "。，；：、":
                    head = norm[max(0, m.start() - 2): m.start()]
                    if not re.search(r"[。，；：、\s　）)】〕]$", head):
                        continue  # inside a longer word (生黄芪, 熟附子 …)
                if _PROPERTY_AFTER.match(norm[m.end(): m.end() + 24]):
                    return m.start()
        return None

    def _cut(self, text: str, forms: list[str]) -> str:
        """The entry up to the start of the next drug's entry."""
        for m in self.b.pack.lexicon.match(text[2:]):
            if m.category != "herb" or len(m.surface) < 2 or m.surface in forms:
                continue
            if _NEXT_ENTRY.match(text[2 + m.end: 2 + m.end + 10]):
                return text[: 2 + m.start]
        return text

    def _read(self, text: str) -> dict[str, Any]:
        out: dict[str, Any] = {"flavor": "", "nature": "", "toxicity": "", "channels": [], "direction": "", "indication": "",
                               "aliases": [], "quotes": {}}
        m = _FLAVOR.search(text)
        if m:
            out["flavor"] = m.group(1)
            out["quotes"]["flavor"] = text[max(0, m.start() - 2): m.end() + 8]
        n = _NATURE.search(text)
        if n:
            out["nature"] = n.group(1) or n.group(2)
            out["quotes"].setdefault("nature", text[max(0, n.start() - 2): n.end() + 4])
        t = _TOXIC.search(text[:240])
        if t:
            out["toxicity"] = t.group(1)
            out["quotes"]["toxicity"] = text[max(0, t.start() - 6): t.end() + 2]
        channels: list[str] = []
        for e in _ENTER.finditer(text):
            seg = e.group(1) or e.group(2) or ""
            for tok in _CHANNEL_TOKEN.findall(seg):
                if tok not in channels:
                    channels.append(tok)
            out["quotes"].setdefault("channels", text[max(0, e.start() - 2): e.end() + 4])
        out["channels"] = channels
        d = _DIRECTION.search(text)
        if d:
            out["direction"] = d.group(1)
            out["quotes"]["direction"] = text[max(0, d.start() - 6): d.end() + 2]
        ind = _INDICATION.search(text)
        if ind:
            out["indication"] = ind.group(1).strip("，、： ")
        out["aliases"] = list(dict.fromkeys(a for a in _ALIAS.findall(text)))
        return out

    # ------------------------------------------------------------ main
    def run(self, name: str, *, max_passages: int = 3000) -> dict[str, Any]:
        b = self.b
        term_id, forms = b.surfaces(name, "herb")
        keys = list(dict.fromkeys(han_only(b.normalize(f))[0] for f, _ in forms if b.normalize(f)))
        entries: dict[str, dict[str, Any]] = {}  # one entry per work: the fullest of its copies
        seen_books: set[str] = set()

        def richness(r: dict[str, Any]) -> int:
            return sum(bool(r[k]) for k in ("flavor", "nature", "toxicity", "direction", "indication")) + 2 * bool(r["channels"])

        def add(p: Any, text: str, raw: str, how: str, start: int = 0) -> None:
            reading = self._read(self._cut(text, keys))
            if not (reading["flavor"] or reading["nature"] or reading["channels"] or reading["toxicity"]):
                return
            book = b.corpus.books.get(p.book_id)
            work = (getattr(book, "work", None) if book else None) or p.book_id
            old = entries.get(work)
            if old is not None and old["book_id"] == p.book_id:
                old["entries_in_book"] += 1
                return
            seen_books.add(p.book_id)
            w = b.witness(p, start=start, end=min(len(p.text), start + 80), width=0)
            w["quote"] = raw[:160]
            row = {**w, **reading, "entries_in_book": 1, "found_by": how, "copies": 1}
            if old is None:
                entries[work] = row
            elif richness(row) > richness(old):
                row["copies"] = old["copies"] + 1
                entries[work] = row
            else:
                old["copies"] += 1

        # 1. entries whose heading is the drug (笈成: 【释名】【气味】【主治】 paragraphs under the heading)
        index = self.heading_index()
        groups: dict[tuple[str, str], list[tuple[int, str]]] = defaultdict(list)
        for head, items in index.items():
            if any(head == k or (head.startswith(k) and len(head) <= len(k) + 6) for k in keys):
                for bid, seq, pid in items:
                    groups[(bid, head)].append((seq, pid))
        for (bid, _), items in sorted(groups.items()):
            ps = b.passages([pid for _, pid in sorted(items)][:12])
            if not ps:
                continue
            raw = "。".join(p.text for p in ps)[:1600]
            add(ps[0], b.normalize(raw), raw, "heading")
        # 2. entries in running text: the name followed by its flavour or nature
        books = self.books()
        ids: list[str] = []
        for f, _ in forms:
            ids += b.find(f, book_ids=books, limit=max_passages)
        for p in b.passages(list(dict.fromkeys(ids))):
            if p.book_id in seen_books:
                continue
            norm = b.normalize(p.text)
            start = self._entry_start(p, norm, keys)
            if start is None:
                continue
            text, raw = norm[start: start + 420], p.text[start: start + 420]
            if len(text) < 60:  # the entry goes on in the next passages (汤液本草)
                for q in b.following(p, 2):
                    text += "。" + b.normalize(q.text)[:300]
                    raw += "。" + q.text[:300]
            add(p, text, raw, "text", start)
        rows = sorted(entries.values(), key=lambda r: (dated(r["years"]), r["book_id"]))
        return {"herb": {"term_id": term_id, "name": name, "forms": [{"form": f, "kind": k} for f, k in forms]},
                "entries": rows, "firsts": self._firsts(rows), "periods": self._periods(rows),
                "summary": {"works": len(rows), "books": len(seen_books), "with_channels": sum(1 for r in rows if r["channels"]),
                            "earliest": rows[0]["locator"] if rows else None,
                            "natures": sorted({r["nature"] for r in rows if r["nature"]}),
                            "toxicity": sorted({r["toxicity"] for r in rows if r["toxicity"]})}}

    @staticmethod
    def _firsts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The earliest book stating each property value (the first 归经 statement, the first 有毒 …)."""
        firsts: dict[tuple[str, str], dict[str, Any]] = {}
        for r in rows:
            values = [("性味", r["flavor"]), ("药性", r["nature"]), ("毒性", r["toxicity"]), ("升降浮沉", r["direction"])]
            values += [("归经", c) for c in r["channels"]]
            values += [("异名", a) for a in r["aliases"]]
            for field, value in values:
                if value and (field, value) not in firsts:
                    firsts[(field, value)] = {"field": field, "value": value, "locator": r["locator"], "years": r["years"],
                                              "passage_id": r["passage_id"],
                                              "quote": r["quotes"].get({"性味": "flavor", "药性": "nature", "毒性": "toxicity",
                                                                        "升降浮沉": "direction", "归经": "channels"}.get(field, ""), "")}
        order = {"性味": 0, "药性": 1, "毒性": 2, "归经": 3, "升降浮沉": 4, "异名": 5}
        return sorted(firsts.values(), key=lambda f: (order[f["field"]], dated(f["years"])))

    @staticmethod
    def _periods(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by: dict[str, dict[str, Any]] = defaultdict(lambda: {"books": 0, "natures": defaultdict(int), "flavors": defaultdict(int),
                                                            "toxicity": defaultdict(int), "channels": defaultdict(int)})
        order: dict[str, float] = {}
        for r in rows:
            per = r["period"] or "未定"
            order.setdefault(per, (r["years"] or [9999])[0])
            d = by[per]
            d["books"] += 1
            if r["nature"]:
                d["natures"][r["nature"]] += 1
            for ch in r["flavor"]:
                d["flavors"][ch] += 1
            if r["toxicity"]:
                d["toxicity"][r["toxicity"]] += 1
            for c in r["channels"]:
                d["channels"][c] += 1
        out = []
        for per in sorted(by, key=lambda k: order[k]):
            d = by[per]
            out.append({"period": per, "books": d["books"], "natures": dict(d["natures"]), "flavors": dict(d["flavors"]),
                        "toxicity": dict(d["toxicity"]), "channels": dict(sorted(d["channels"].items(), key=lambda kv: -kv[1]))})
        return out


__all__ = ["HerbStudy"]
