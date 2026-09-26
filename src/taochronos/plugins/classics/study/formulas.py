"""方源考 — the sources of a formula: every place its composition is written out, in date order.

For a formula name (with its aliases and the Song taboo form 丸/圆), every passage that writes out a composition after
the name is parsed: ingredients (canonical drug terms, so 薯蓣 and 山药 count as one drug), doses, preparation notes in
（…）, the preparation clause (右五味…) and the indication given with it.  Witnesses are then grouped by composition:

* the main tradition and its 加减 variants (Jaccard ≥ 0.5 with the main composition);
* 同名异方 — different formulas under the same name (Jaccard < 0.5);
* 同方异名 — the main composition written out under other formula names;
* 配伍比例 — dose ratios of the main composition in each witness (a ratio does not depend on the period's measures);
* 历代剂量 — each dose read in the measures of the witness's own period (``metrology.py``; not dosage guidance);
* 方歌 — verses naming the formula in the 歌诀 books, for learning.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from .base import StudyBase, dated, han_only
from .metrology import NUM, Metrology

_PREP = re.compile(r"(?:右|上|已上|以上)[一二三四五六七八九十廿卅]+味")
# the preparation begins (为末 / 炼蜜 / 丸如梧桐子大): the drug list has ended even without 右N味
_LIST_END = re.compile(r"(?:为|為)(?:细|粗|极细)?末|炼蜜|煉蜜|(?:丸|圆)?如(?:梧桐|梧子|弹子|小豆|麻子|鸡子|芡实)")
_SEP = set("，、。；：　 （）()，；\n")
_PROC = re.compile(r"^（[^（）]{0,40}）")
_MODIFY = re.compile(r"方?(?:内|中|於|于)?[，、]?(?:去|加|更加|倍|减)")  # 桂枝汤方内，去芍药，加附子: a modification
# preparation notes written without brackets: 甘草炙　生姜切，各三两 / 半夏半升，洗 / 附子一枚，炮，去皮，破八片
_INLINE_PROC = re.compile("|".join(sorted((
    "炙 切 洗 擘 碎 熬 炮 炒 研 破 烧 煨 蒸 焙 锉 剉 捣 杵 去皮 去节 去心 去皮尖 去皮脐 去核 去毛 去芦 去须 去土 去白 去子 去瓤 "
    "去足 去翅 去翅足 去皮尖双仁 去皮尖及双仁 去皮破八片 破八片 酒洗 酒浸 酒炒 酒蒸 汤洗 绵裹 碎绵裹 先煎 后下 生用 微炒 炒香 "
    "研末 蜜炙 姜汁炒 醋炒 盐炒 另煎 冲服 烊化 包煎 汤浸 汤泡 去油 去壳 去苗 去粗皮 去皮切 洗去腥 洗去咸").split(), key=len, reverse=True)))
_SONG_BOOK = re.compile(r"(歌|赋|賦|心法要诀|心法要訣)")
_OTHER_LIST = re.compile(r"(主之|服此|宜此|用此方|宜用此)")
_COMMON_CHARS = set("子草花叶根皮仁实白黄红赤青黑大小生干熟炙山川石木水火土金香甘苦辛酸咸肉心头尾节藤枝米汤散丸膏丹")


@dataclass
class Composition:
    passage_id: str
    name: str  # the form written in the text
    start: int
    end: int
    items: list[dict[str, Any]] = field(default_factory=list)  # {term_id, surface, dose, processing}
    preparation: str = ""
    indication: str = ""
    quote: str = ""  # set when the composition spans the passages of an entry (the name printed as its heading)

    @property
    def herbs(self) -> set[str]:
        """Drug keys compared between compositions (families: 桂枝/桂心/肉桂 → 桂)."""
        return {i.get("family") or i["term_id"] for i in self.items}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a or b else 0.0


class FormulaStudy:
    def __init__(self, base: StudyBase) -> None:
        self.b = base
        self.metrology = Metrology(base.data("metrology.yaml"))
        units = sorted(set([*self.metrology.weight, "分", *self.metrology.volume, *self.metrology.count]), key=len, reverse=True)
        unit = "(?:" + "|".join(map(re.escape, units)) + ")"
        nonstd = "|".join(map(re.escape, sorted(self.metrology.nonstandard, key=len, reverse=True))) or "(?!)"
        self._dose = re.compile(rf"(?:以上|已上)?各?(?:(?:{NUM}|两)?(?:{nonstd})|{NUM}{unit}(?:{NUM}{unit}|半)*(?:或{NUM}{unit})?|等分)")
        self._dose_near = re.compile(rf"{NUM}(?:两|钱|分|铢|斤|升|合|枚)")
        self.families: dict[str, str] = {}
        for key, members in (base.data("drug_families.yaml").get("families") or {}).items():
            for name in members:
                self.families[base.normalize(name)] = key

    # ------------------------------------------------------------ parsing
    def parse_at(self, norm: str, pos: int, name: str) -> Composition | None:
        """The composition written out after the formula name at ``pos`` in a normalised text, if any."""
        lex = self.b.pack.lexicon
        after = pos + len(name)
        window = norm[after: after + 480]
        indication = ""
        m_ind = re.match(r"^方?[：:，,　 \n]*(?:治|主|疗)([^。\n]{2,120})。", window)
        if m_ind:
            indication = m_ind.group(0).lstrip("方：:，, 　\n")
        found = lex.match(window)
        mentions = [m for m in found if m.category == "herb" and not m.weak]
        stops = [x.start() for x in (_PREP.search(window), _LIST_END.search(window)) if x is not None]
        stop = min(stops) if stops else None
        first = next((m for m in mentions if len(m.surface) >= 2), None)
        if first is not None:
            lead = window[: first.start]
            # another formula named before the list owns it (桂枝汤……与麻黄杏子石膏甘草汤：麻黄…); 加/去 marks a modification
            if any(m.category == "formula" and m.end <= first.start for m in found) or re.search(r"(?:^|[，、。；])(?:加|去|减|倍)", lead[:40]):
                return None
        starts = [m.start for m in mentions]
        items: list[dict[str, Any]] = []
        pending: list[int] = []
        last_end: int | None = None
        list_start = None
        for m in mentions:
            if stop is not None and m.start >= stop:
                break
            if last_end is None:
                if m.start > 160:
                    break
            else:
                gap = window[last_end: m.start]
                if len([c for c in gap if c not in _SEP]) > 6:
                    break
            cursor = m.end
            processing = ""
            proc = _PROC.match(window[cursor:])
            if proc:
                processing = proc.group(0)[1:-1]
                cursor += proc.end()
            if not processing:
                inline, after_inline = self._inline_processing(window, cursor, starts, before_dose=True)
                if inline:
                    processing, cursor = inline, after_inline
            right_after = window[cursor: cursor + 1]
            probe = cursor
            while probe < len(window) and window[probe] in "　 " + ("，、" if processing else ""):
                probe += 1
            dose_m = self._dose.match(window, probe)
            dose = ""
            if dose_m and dose_m.group(0):
                dose = dose_m.group(0)
                cursor = dose_m.end()
                post, after_post = self._inline_processing(window, cursor, starts, before_dose=False)
                if post:
                    processing = "，".join(x for x in (processing, post) if x)
                    cursor = after_post
            elif processing:
                inner = self._dose.match(processing)
                if inner and inner.group(0):
                    dose = inner.group(0)
                    processing = processing[inner.end():].lstrip("，、 ")
                else:  # 白茯苓（去皮，各三钱）: the dose closes the note
                    tail = [x for x in self._dose.finditer(processing) if x.group(0) and x.end() >= len(processing.rstrip("，、。 "))]
                    if tail:
                        dose = tail[-1].group(0)
                        processing = processing[: tail[-1].start()].rstrip("，、 ")
            proc2 = _PROC.match(window[cursor:])
            if proc2:
                processing = "；".join(x for x in (processing, proc2.group(0)[1:-1]) if x)
                cursor += proc2.end()
            if len(m.surface) < 2 and not dose and m.surface not in self.families and not proc:
                continue  # a one-character drug name (other than 桂, 术 …) is taken only with its dose or note
            if last_end is None and not dose:
                # the first ingredient must look like one: a dose, or another drug right after a separator
                if not (right_after in ("、", "　", " ", "，") and any(0 <= x.start - cursor <= 2 for x in mentions if x.start > m.start)):
                    continue
            if dose.startswith(("以上", "已上", "各")):
                shared = re.sub(r"^(以上|已上)?各", "", dose)
                for k in pending:
                    items[k]["dose"] = shared
                pending = []
                dose = shared
            family = self.families.get(m.surface) or self.families.get(m.entry.term)
            item = {"term_id": m.entry.term_id, "term": m.entry.term, "surface": m.surface, "dose": dose, "processing": processing,
                    "family": f"family:{family}" if family else m.entry.term_id}
            if not dose:
                pending.append(len(items))
            else:
                pending = []
            items.append(item)
            list_start = m.start if list_start is None else list_start
            last_end = cursor
        if len(items) < 2 or last_end is None:
            return None
        lead = window[:list_start or 0]
        if any(m.category == "formula" and not m.weak and m.start < (list_start or 0) for m in found) or _OTHER_LIST.search(lead):
            return None  # 先与小建中汤，不差，与小柴胡汤主之。柴胡… / 桃仁承气汤；实者宜服此：柴胡… — the list is another formula's
        dosed = sum(1 for i in items if i["dose"])
        if dosed == 0 and len(items) < 3:
            return None
        preparation = ""
        tail = window[last_end: last_end + 24]
        prep = _PREP.search(window, last_end)
        if prep is not None and prep.start() - last_end <= 24:
            stop_at = window.find("。", prep.end())
            preparation = window[prep.start(): stop_at + 1 if 0 <= stop_at < prep.end() + 160 else prep.end() + 80]
            last_end = prep.start() + len(preparation)
        elif re.match(r"^[，。；\s　]*(?:上|右|已上|以上)?[件药藥]*[，]?(?:同|共|捣|搗|研|杵)?(?:为|為)(?:末|散|细末|粗末|极细末)", tail):
            stop_at = window.find("。", last_end)
            preparation = window[last_end: stop_at + 1 if 0 <= stop_at < last_end + 120 else last_end + 60].lstrip("，。；\n 　")
        return Composition(passage_id="", name=name, start=pos, end=after + last_end, items=items,
                           preparation=preparation, indication=indication)

    def _inline_processing(self, window: str, cursor: int, starts: list[int], *, before_dose: bool) -> tuple[str, int]:
        """Preparation notes written without brackets right after a drug name or its dose (炙 / ，洗 / ，炮，去皮)."""
        parts: list[str] = []
        pos = cursor
        for _ in range(4):
            sep = 1 if pos < len(window) and window[pos] in "，、," else 0
            if parts and not sep:
                break
            m = _INLINE_PROC.match(window, pos + sep)
            if not m or any(pos + sep <= x < m.end() for x in starts):
                break  # 炮姜, 炙甘草: the next drug, not a note
            nxt = window[m.end(): m.end() + 1]
            dose_follows = before_dose and bool((self._dose.match(window, m.end() + (1 if nxt in "，、" else 0)) or [""])[0])
            if not (nxt == "" or nxt in "，、,。；　 （" or dose_follows):
                break
            parts.append(m.group(0))
            pos = m.end()
        return "，".join(parts), pos

    # ------------------------------------------------------------ main
    def run(self, name: str, *, max_passages: int = 8000, max_witnesses: int = 600, other_names: bool = True) -> dict[str, Any]:
        b = self.b
        term_id, forms = b.surfaces(name, "formula")
        forms = self._with_taboo_forms(forms)
        compositions: list[tuple[Composition, Any]] = []
        modifications: list[dict[str, Any]] = []
        mentions = 0
        seen_ids: set[str] = set()
        for form, _ in forms:
            ids = [i for i in b.find(form) if i not in seen_ids][:max_passages]
            seen_ids.update(ids)
            mentions += len(ids)
            for p in b.passages(ids):
                norm = b.normalize(p.text)
                key = b.normalize(form)
                for m in re.finditer(re.escape(key), norm):
                    if self._inside_longer_name(norm, m.start(), m.end()):
                        continue  # 柴胡桂枝汤 is not 桂枝汤
                    if _MODIFY.match(norm, m.end()):
                        if len(modifications) < 30:
                            end = norm.find("。", m.end())
                            w = b.witness(p, start=m.start(), end=end if 0 < end < m.end() + 80 else m.end() + 40, width=0)
                            w["quote"] = p.text[m.start(): (end + 1) if 0 < end < m.end() + 80 else m.end() + 40]
                            modifications.append(w)
                        continue
                    if not self._dose_near.search(norm, m.end(), m.end() + 260):
                        continue
                    comp = self.parse_at(norm, m.start(), key)
                    if comp is not None:
                        comp.passage_id = p.id
                        comp.name = p.text[m.start(): m.end()]
                        compositions.append((comp, p))
                        break
        # entries whose heading is the name (笈成: 地黄丸 / 治肾怯失音… / 熟地黄八钱　山萸肉… / 上为末…)
        done = {c.passage_id for c, _ in compositions}
        for head, run in b.entries([f for f, _ in forms]):
            if run and not any(q.id in done for q in run):
                parsed = self._parse_entry(head, run)
                if parsed is not None:
                    compositions.append(parsed)
                    done.update(q.id for q in run)
        compositions.sort(key=lambda cp: (dated(b.years(cp[1])), cp[1].id))
        compositions = compositions[:max_witnesses]
        witnesses = [self._witness(c, p) for c, p in compositions]
        groups = self._group(compositions)
        # 原方: the tradition of the earliest witness (when it recurs); 通行方: the tradition most witnesses follow —
        # both among the traditions written under the name asked for (地黄丸 is also the name of other formulas)
        multi = [g for g in groups if g["witnesses"] >= 2]
        primary = self._primary_names(name, term_id)
        named = [g for g in multi if primary & set(g["names"])] or multi
        original = min(named, key=lambda g: (dated(g["earliest"]["years"]), -g["witnesses"])) if named else (groups[0] if groups else None)
        current = max(named, key=lambda g: g["witnesses"]) if named else original
        main = original
        for g in groups:
            if g is original:
                g["relation"] = "原方（最早见）" if g is not current else "原方·通行方"
            elif g is current:
                g["relation"] = "通行方（见证最多）"
            elif g["witnesses"] < 2:
                g["relation"] = "孤例"  # one witness: a parsing accident or a unique recension, to check by hand
            else:
                near = max(jaccard(set(g["core"]), set(original["core"])), jaccard(set(g["core"]), set(current["core"])))
                g["relation"] = "加减化裁" if near >= 0.5 else "同名异方"
        result: dict[str, Any] = {
            "formula": {"term_id": term_id, "name": name, "forms": [{"form": f, "kind": k} for f, k in forms]},
            "mentions": mentions, "witnesses": witnesses, "groups": groups,
            # the earliest witness of the formula asked for (its 原方); the earliest composition under any of its names
            # may be another formula (千金's 地黄丸 is not 钱乙's)
            "earliest": next((w for w in witnesses if original and w["passage_id"] == original["earliest"]["passage_id"]),
                             witnesses[0] if witnesses else None),
            "earliest_any_name": witnesses[0] if witnesses else None,
            "indications": self._indications(compositions),
            "modifications": sorted(modifications, key=lambda w: (dated(w["years"]), w["passage_id"]))[:20],
            "ratios": self._ratios(compositions, main) if main else [],
            "songs": self._songs(forms, self._main_surfaces(witnesses, main)),
            "metrology_notice": self.metrology.notice,
        }
        if other_names and main and len(main["core"]) >= 3:
            result["other_names"] = self._other_names(set(main["core"]), {b.normalize(f) for f, _ in forms})
        result["summary"] = {
            "compositions": len(witnesses), "books": len({w["book_id"] for w in witnesses}),
            "works": len({w["work"] or w["book_id"] for w in witnesses}),
            "groups": len(groups), "same_name_different": sum(1 for g in groups if g["relation"] == "同名异方"),
            "variants": sum(1 for g in groups if g["relation"] == "加减化裁"),
            "single_witness": sum(1 for g in groups if g["relation"] == "孤例"),
            "original_witnesses": original["witnesses"] if original else 0,
            "current_witnesses": current["witnesses"] if current else 0,
            "earliest": result["earliest"]["locator"] if result["earliest"] else None,
        }
        return result

    # ------------------------------------------------------------ pieces
    def _parse_entry(self, head: str, run: list[Any]) -> tuple[Composition, Any] | None:
        """A composition written out in the paragraphs of an entry headed by the formula's name."""
        raw = head + "\n" + "\n".join(q.text for q in run)
        norm = self.b.normalize(raw)
        comp = self.parse_at(norm, 0, self.b.normalize(head))
        if comp is None:
            return None
        # the witness is the paragraph where the drugs are listed
        first = comp.items[0]["surface"] if comp.items else ""
        pos, anchor = len(head) + 1, run[0]
        for q in run:
            if first and self.b.normalize(q.text).find(first) >= 0:
                anchor = q
                break
            pos += len(q.text) + 1
        comp.quote = f"〔{head}〕" + raw[len(head) + 1: comp.end].replace("\n", "　")
        comp.passage_id = anchor.id
        comp.name = head
        comp.start, comp.end = 0, len(anchor.text)
        return comp, anchor

    def _inside_longer_name(self, norm: str, start: int, end: int) -> bool:
        lex = self.b.pack.lexicon
        for k in range(1, 7):
            if start - k < 0:
                break
            for entry, _ in lex.lookup(norm[start - k: end]):
                if entry.category == "formula":
                    return True
        return False

    def _primary_names(self, name: str, term_id: str | None) -> set[str]:
        """The name asked for, its canonical form and their taboo spellings (丸/圆)."""
        entry = self.b.pack.lexicon.entry(term_id) if term_id else None
        out = set()
        for n in {name, entry.term if entry else name}:
            n = self.b.normalize(n)
            out.add(n)
            if n.endswith("丸"):
                out.add(n[:-1] + "圆")
            elif n.endswith("圆"):
                out.add(n[:-1] + "丸")
        return out

    def _with_taboo_forms(self, forms: list[tuple[str, str]]) -> list[tuple[str, str]]:
        out = list(forms)
        have = {f for f, _ in forms}
        for f, _ in forms:
            if f.endswith("丸") and f[:-1] + "圆" not in have:
                out.append((f[:-1] + "圆", "宋讳改字（丸→圆）"))
            elif f.endswith("圆") and f[:-1] + "丸" not in have:
                out.append((f[:-1] + "丸", "本字（圆→丸）"))
        return out

    def _witness(self, comp: Composition, p: Any) -> dict[str, Any]:
        b = self.b
        w = b.witness(p, start=comp.start, end=comp.end, width=0)
        w["quote"] = comp.quote or p.text[comp.start: comp.end]
        year = b.year(p)
        w["name_form"] = comp.name
        w["ingredients"] = [{**i, "reading": (self.metrology.convert(i["dose"], year) or {}).get("text", "")} for i in comp.items]
        w["preparation"] = comp.preparation
        w["indication"] = comp.indication
        w["herbs"] = sorted(comp.herbs)
        return w

    def _group(self, comps: list[tuple[Composition, Any]]) -> list[dict[str, Any]]:
        """Group witnesses by composition.  The most frequent exact drug sets seed the groups (so an early variant does
        not define a tradition); a set joins the first seed it shares ≥ 0.7 of its drugs with (Jaccard), else seeds a
        group of its own.  A group is dated by the earliest witness of its exact seed composition."""
        by_set: dict[frozenset[str], list[tuple[Composition, Any]]] = defaultdict(list)
        for comp, p in comps:  # comps are in date order
            by_set[frozenset(comp.herbs)].append((comp, p))
        order = sorted(by_set, key=lambda k: (-len(by_set[k]), dated(self.b.years(by_set[k][0][1])), sorted(k)))
        seeds: list[frozenset[str]] = []
        members: dict[frozenset[str], list[tuple[Composition, Any]]] = {}
        for herbs in order:
            best = max(seeds, key=lambda sd: jaccard(set(herbs), set(sd)), default=None)
            if best is not None and jaccard(set(herbs), set(best)) >= 0.7:
                members[best] += by_set[herbs]
            else:
                seeds.append(herbs)
                members[herbs] = list(by_set[herbs])
        out = []
        for seed in seeds:
            group = sorted(members[seed], key=lambda cp: (dated(self.b.years(cp[1])), cp[1].id))
            exact = [cp for cp in group if frozenset(cp[0].herbs) == seed]
            first_comp, first_p = exact[0]
            years = [self.b.years(p) for _, p in group]
            counts = Counter(h for c, _ in group for h in c.herbs)
            out.append({
                "core": sorted(seed), "core_terms": [self._term(h) for h in sorted(seed)], "witnesses": len(group), "exact": len(exact),
                "names": dict(Counter(self.b.normalize(c.name) for c, _ in group).most_common()),
                "member_ids": [p.id for _, p in group],
                "books": sorted({self.b.book_title(p.book_id) for _, p in group}),
                "earliest": self.b.witness(first_p, start=first_comp.start, end=first_comp.end, width=0)
                | {"quote": first_comp.quote or first_p.text[first_comp.start: first_comp.end]},
                "span": [min(y[0] for y in years if y), max(y[1] for y in years if y)] if any(years) else None,
                "optional": sorted((h for h in counts if h not in seed), key=lambda h: -counts[h])[:12],
            })
        out.sort(key=lambda g: (-g["witnesses"], dated(g["earliest"]["years"])))
        return out

    def _term(self, term_id: str) -> str:
        if term_id.startswith("family:"):
            return term_id.split(":", 1)[1] + "类"
        entry = self.b.pack.lexicon.entry(term_id)
        return entry.term if entry else term_id.split(":", 1)[-1]

    def _indications(self, comps: list[tuple[Composition, Any]]) -> list[dict[str, Any]]:
        out = []
        seen: set[str] = set()
        for comp, p in comps:
            ind = comp.indication.strip()
            if not ind or ind in seen:
                continue
            seen.add(ind)
            out.append({"indication": ind, "locator": self.b.locator(p), "years": list(self.b.years(p) or []) or None,
                        "passage_id": p.id})
        return out[:40]

    def _ratios(self, comps: list[tuple[Composition, Any]], main: dict[str, Any]) -> list[dict[str, Any]]:
        """Dose ratios of the main composition's core drugs, witness by witness (weights only)."""
        core = set(main["core"])
        rows = []
        for comp, p in comps:
            if not core <= comp.herbs:
                continue
            year = self.b.year(p)
            weights = {}
            for i in comp.items:
                key = i.get("family") or i["term_id"]
                if key in core:
                    w = self.metrology.in_liang(i["dose"], year)
                    if w:
                        weights[key] = weights.get(key, 0.0) + w
            if len(weights) < 2:
                continue
            top = max(weights.values())
            rows.append({"locator": self.b.locator(p), "years": list(self.b.years(p) or []) or None, "passage_id": p.id,
                         "ratio": {self._term(h): round(v / top, 3) for h, v in sorted(weights.items())}})
        return rows[:60]

    def _ratio_of(self, comp: Composition, year: float | None) -> dict[str, float]:
        weights = {i["term"]: self.metrology.in_liang(i["dose"], year) for i in comp.items}
        weights = {k: v for k, v in weights.items() if v}
        top = max(weights.values(), default=0)
        return {k: round(v / top, 3) for k, v in weights.items()} if top else {}

    def _songs(self, forms: list[tuple[str, str]], surfaces: list[str]) -> list[dict[str, Any]]:
        """方歌: verses (clauses of five or seven characters) in the 歌诀 books that name the formula — in the text or in
        the heading of the entry — and recite its drugs: a drug named in full counts one, an abbreviated drug (姜 for
        生姜, 芍 for 芍药) half.  A verse printed one line per passage is joined back together; when the heading took the
        name out of the first line (笈成: 小柴胡汤 / 和解供，半夏人参甘草从), the name is put back in 〔〕."""
        b = self.b
        books = sorted(bk.id for bk in b.corpus.books.values() if bk.category == "歌赋" or _SONG_BOOK.search(bk.title))
        herbs = sorted({b.normalize(x) for x in surfaces if len(x) >= 2})
        if not books or not herbs:
            return []
        marks = self._song_marks(herbs)
        headings = b.heading_index(books, "songs")
        keys = list(dict.fromkeys(b.normalize(f) for f, _ in forms if b.normalize(f)))
        cands: dict[str, str] = {}  # passage id → the name when it is the heading of the entry
        for key in keys:
            entries = headings.get(han_only(key)[0], [])
            at = {(bid, seq) for bid, seq, _ in entries}
            for bid, seq, pid in entries[:60]:
                if (bid, seq - 1) not in at:  # the first passage of the entry
                    cands.setdefault(pid, key)
        for form, _ in forms:
            for pid in b.find(form, book_ids=books, limit=600):
                cands.setdefault(pid, "")
        out: list[dict[str, Any]] = []
        for p in b.passages(list(cands)):
            text = p.text
            if cands[p.id] or len(text) < 60:  # an entry, or one line per passage: read on within the entry
                for q in b.following(p, 6):
                    if q.locator.section != p.locator.section or len(text) > 1500:
                        break
                    text += q.text
            norm = b.normalize(text)
            starts: list[tuple[int, int]] = []  # (begin, characters of the name the heading took)
            head = cands[p.id]
            lead = re.match(r"^[\s　]*(?:[（(〔][^）)〕]{0,12}[）)〕])?[\s　]*", norm)
            lead_end = lead.end() if lead else 0
            if head:
                n = len(han_only(head)[0])
                starts += [(lead_end, 0), (lead_end, n), (lead_end, n - 1)]  # 六味地黄丸 / 〔六味地黄〕益肾肝
                song = norm.find("歌曰", 0, 400)
                if song >= 0:
                    starts.insert(0, (song + 2 + (1 if norm[song + 2: song + 3] in "：:" else 0), 0))
            for key in keys:
                for m in re.finditer(re.escape(key), norm):
                    if (self._inside_longer_name(norm, m.start(), m.end()) or _MODIFY.match(norm, m.end())
                            or norm.rfind("（", 0, m.start()) > norm.rfind("）", 0, m.start())):
                        continue  # 柴胡桂枝汤, 桂枝汤去桂加茯苓白术汤, or a name inside a note
                    if m.start() == lead_end:  # the entry opens with the name: its verse may follow 歌曰
                        song = norm.find("歌曰", m.end(), m.end() + 400)
                        if song >= 0:
                            starts.append((song + 2 + (1 if norm[song + 2: song + 3] in "：:" else 0), 0))
                    starts.append((m.start(), 0))
                    back = max((norm.rfind(ch, max(0, m.start() - 40), m.start()) for ch in "。！？\n"), default=-1)
                    starts.append((back + 1 if back >= 0 else max(0, m.start() - 40), 0))
            best = None
            for begin, taken in dict.fromkeys(starts):
                end = self._verse(norm, begin, taken)
                if end is None:
                    continue
                verse = re.sub(r"（[^（）]*）|\([^()]*\)", "", norm[begin: end])
                for key in keys:
                    verse = verse.replace(key, "")
                score = sum(1.0 if h in verse else 0.5 if marks[h] & set(verse) else 0.0 for h in herbs)
                if score >= 1.5 and (best is None or score > best[0]):
                    best = (score, begin, end, taken)
            if best is None:
                continue
            score, begin, end, taken = best
            w = b.witness(p, start=min(begin, len(p.text)), end=min(end, len(p.text)), width=0)
            quote = text[begin: end].strip().lstrip("）)」』，。；、：　 ")
            w["quote"] = (f"〔{p.locator.section or head}〕" if taken else "") + quote
            w["score"] = score
            out.append(w)
        # one verse per book, the fuller reading of a verse printed twice; best first, then by date
        def core(w: dict[str, Any]) -> str:
            return han_only(re.sub(r"（[^（）]*）|〔[^〕]*〕", "", b.normalize(w["quote"])))[0]

        def mid(w: dict[str, Any]) -> float:
            ys = w["years"] or [9999, 9999]
            return (ys[0] + ys[1]) / 2

        kept: list[dict[str, Any]] = []
        for w in sorted(out, key=lambda w: (-w["score"], -len(core(w)), mid(w), w["passage_id"])):
            if any(core(w) in core(k) or (k["work"] or k["book_id"]) == (w["work"] or w["book_id"]) and core(w)[:6] == core(k)[:6] for k in kept):
                continue
            kept.append(w)
        return sorted(kept[:8], key=lambda w: (mid(w), w["passage_id"]))

    def _song_marks(self, herbs: list[str]) -> dict[str, set[str]]:
        """The characters by which a verse may abbreviate each drug (茱 for 山茱萸, 薯 for 山药/薯蓣, 丹 for 牡丹皮): the
        characters of all its names, less those too common to identify a drug."""
        lex = self.b.pack.lexicon
        out: dict[str, set[str]] = {}
        for h in herbs:
            names = {h}
            for entry, _ in lex.lookup(h):
                names |= {self.b.normalize(x) for x in entry.surfaces()}
            out[h] = {ch for n in names for ch in n} - _COMMON_CHARS
        return out

    @staticmethod
    def _verse(norm: str, begin: int, taken: int = 0) -> int | None:
        """The end of a verse starting at ``begin``: two to four clauses of five or seven characters (the first
        ``taken`` characters short when the heading took the formula name out of it), if one does."""
        lengths: list[int] = []
        n, depth, pos, last = 0, 0, begin, begin
        while pos < len(norm) and len(lengths) < 4 and pos - begin < 240:
            ch = norm[pos]
            pos += 1
            if ch in "（(":
                depth += 1
            elif ch in "）)":
                depth = max(0, depth - 1)
            elif depth:
                continue  # interlinear notes do not count
            elif ch in "，。；！？、":
                lengths.append(n)
                n, last = 0, pos
            elif ch == "\n":
                break
            elif "\u4e00" <= ch <= "\u9fff":
                n += 1
        if lengths and taken:
            lengths[0] += taken
        if len(lengths) < 2 or len(set(lengths)) != 1 or lengths[0] not in (5, 7):
            return None
        return last

    @staticmethod
    def _main_surfaces(witnesses: list[dict[str, Any]], main: dict[str, Any] | None) -> list[str]:
        if not main:
            return []
        first = next((w for w in witnesses if w["passage_id"] == main["earliest"]["passage_id"]), None)
        return [i["surface"] for i in first["ingredients"]] if first else []

    def _other_names(self, core: set[str], own: set[str]) -> list[dict[str, Any]]:
        """The main composition under other formula names (同方异名)."""
        b = self.b
        lex = b.pack.lexicon
        members: dict[str, list[str]] = defaultdict(list)
        for surface, fam in self.families.items():
            members[f"family:{fam}"].append(surface)
        counts = []
        for h in sorted(core):
            entry = lex.entry(h)
            forms = [f for f in members.get(h, []) if len(f) >= 2] or ([entry.term, *entry.aliases] if entry else [])
            if not forms:
                continue
            n = sum((b.corpus.count(f) if getattr(b.corpus, "large", False) else len(b.find(f))) for f in forms)
            counts.append((n, h, forms))
        counts.sort()
        if len(counts) < 2:
            return []
        left, right = counts[0][2], counts[1][2]
        if getattr(b.corpus, "large", False):
            ids = b.corpus.near(left, right, distance=40, limit=3000)
        else:
            ids = sorted({i for f in left for i in b.find(f)} & {i for f in right for i in b.find(f)})
        found: dict[str, dict[str, Any]] = {}
        for p in b.passages(ids):
            norm = b.normalize(p.text)
            for m in lex.match(norm):
                if m.category != "formula" or b.normalize(m.surface) in own or m.entry.term_id in found and found[m.entry.term_id]["witnesses"] >= 5:
                    continue
                if self._inside_longer_name(norm, m.start, m.end):
                    continue  # 芒硝汤 inside 柴胡加芒硝汤
                comp = self.parse_at(norm, m.start, m.surface)
                if comp is None or jaccard(comp.herbs, core) < 0.8:
                    continue
                entry = found.setdefault(m.entry.term_id, {"name": m.entry.term, "witnesses": 0, "first": None, "similarity": 0.0})
                entry["witnesses"] += 1
                entry["similarity"] = max(entry["similarity"], round(jaccard(comp.herbs, core), 3))
                w = b.witness(p, start=comp.start, end=comp.end, width=0)
                w["quote"] = p.text[comp.start: comp.end][:160]
                if entry["first"] is None or dated(w["years"]) < dated(entry["first"]["years"]):
                    entry["first"] = w
                    entry["ratio"] = self._ratio_of(comp, b.year(p))
                    entry["same_drugs"] = comp.herbs == core
        return sorted(found.values(), key=lambda e: (-e["witnesses"], e["name"]))[:20]


__all__ = ["Composition", "FormulaStudy", "jaccard"]
