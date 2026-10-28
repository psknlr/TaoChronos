"""针灸选穴配穴 · 腧穴考 — acupuncture points chosen the way the tradition reasons, and a point read in the classics.

The central principle of point selection: find where the disorder is and what it is, set a treatment principle, take
points by their channel relations and their specific-point attributes, and combine them into a prescription whose every
point says what it is for.  ``acupuncture.yaml`` writes that reasoning as reviewable data — the fourteen channels, the
points with their standard locations, the specific-point tables (Five-Shu with the phases of *Nanjing* 64, Yuan, Luo,
Xi, Back-Shu, Front-Mu, Lower He-Sea, the Eight Influential and Eight Confluent points, crossing points, the Four
Command points), the regions, symptoms and patterns with the points the teaching takes for them, and the rules with their
classical sources.  Three functions read it:

* **framework** — the tables, and what follows from them: the phase of every Five-Shu point, the mother and child points
  of each channel (same channel and the mother's or child's channel), its own-phase point;
* **select** (选穴配穴) — a presentation (regions, symptoms, organ systems or channels, nature and course, side; or a
  text naming them) read into objectives — the location, the pattern, each prominent symptom — and points proposed for
  each by the rules that apply (local, distal, Four Command, Back-Shu, Front-Mu, Yuan, Lower He-Sea, Xi, Hui, confluent
  pairs, mother–child, the Five-Shu indications of *Nanjing* 68 and *Lingshu* 44, the points the teaching takes for a
  symptom); a point serving several objectives ranks higher, and none is added for its category alone.  The chosen
  points come with their purposes, the combinations they form (local–distal, upper–lower, anterior–posterior,
  same-channel, interior–exterior, same-name, Yuan–Luo host–guest, Shu–Mu, Shu–Yuan, Lower He–Mu, Xi–Hui, confluent
  pairs, the Four Gates — and what they are not: 合谷 + 太冲 is no Yuan–Luo pair), the technique principles, a record to
  fill (laterality, modality, stimulation, frequency, course, outcomes), the cautions, the classical witness of every rule
  used, the classics' own statements that a chosen point treats the findings asked about, and the modern evidence kept
  apart from the theory;
* **point** (腧穴考) — one point through the literature: its names, its attributes against what the classics' entries
  state (甲乙经: 「太渊者，土也……为俞」 — and the witness that reads 水 instead), the location they give, the needling and
  moxibustion they prescribe and forbid, and the findings they say it treats (「……三里主之」「太泉主心痛」「取三里」), work by
  work and period by period.

What the texts are read for is said by rules, and every statement carries its witness.  This is textual research and
the tradition's reasoning — not a diagnosis, a prescription or an efficacy claim: whether and how to needle is for a
qualified practitioner after examination.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Iterable

from .base import HAN, StudyBase, dated
from .wuxing_symptoms import assess as assess_symptoms, mention_status

GENERATES = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}  # the generating cycle (相生)
MOTHER = {child: mother for mother, child in GENERATES.items()}
CONTROLS = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}  # the controlling cycle (相克)
CONTROLLED_BY = {controlled: controller for controller, controlled in CONTROLS.items()}
STATES = ("excess", "deficiency")
LEVELS = {"classical": "经典之规", "teaching": "教材", "school": "流派之法", "deduction": "教学推演与近人推论", "empirical": "经验",
          "standard": "标准与规范"}
UPPER = {"head", "face", "neck", "shoulder", "chest", "upper_abdomen", "upper_back", "upper_limb"}
LOWER = {"lower_abdomen", "lower_back", "sacrum", "hip", "lower_limb"}
ANTERIOR = {"chest", "upper_abdomen", "abdomen", "lower_abdomen"}
POSTERIOR = {"upper_back", "lower_back", "sacrum"}
LIMBS = {"upper_limb", "lower_limb"}
MIDLINE = {"CV", "GV"}
SIX = ("太阴", "少阴", "厥阴", "阳明", "太阳", "少阳")
VESSEL_WORDS = {"督脉": "督脉", "任脉": "任脉", "冲脉": "冲脉", "带脉": "带脉", "阴维": "阴维脉", "阳维": "阳维脉",
                "阴跷": "阴跷脉", "阳跷": "阳跷脉"}
# the five kinds as the classics write them in an entry: 为井 / 为荥 (荣) / 为俞 (腧, 输) / 为经 / 为合 / 为原; and 之所出 …
STATED_KIND = {"井": "jing_well", "荥": "ying_spring", "荣": "ying_spring", "俞": "shu_stream", "腧": "shu_stream",
               "输": "shu_stream", "经": "jing_river", "合": "he_sea", "原": "yuan"}
FLOW_KIND = {"出": "jing_well", "溜": "ying_spring", "流": "ying_spring", "注": "shu_stream", "行": "jing_river",
             "入": "he_sea", "过": "yuan"}
ORGAN_WORDS = ("大肠", "小肠", "膀胱", "心包", "三焦", "肺", "胃", "脾", "心", "肾", "胆", "肝")
# how much one reason weighs for one objective (a point's score sums, over the objectives, the weight of its best reason)
WEIGHT = {"local": 3, "posterior": 2, "distal": 2, "four_command": 2, "confluent_pair": 2, "symptom": 3, "symptom_more": 2,
          "back_shu": 3, "front_mu": 3, "lower_he": 3, "yuan": 2, "xi": 2, "hui": 2, "pattern": 2, "mother": 2,
          "cross": 1, "five_shu": 1, "classical": 1, "minor": 1}
SERVES = 2  # the weight at which a point is said to serve an objective (a lighter reason only supports it)
PARSED_MAX = 50_000  # passages whose parse is kept
PAIN = {"headache", "epigastric_pain", "toothache", "sore_throat", "neck_stiffness", "low_back_pain", "hypochondriac_pain",
        "joint_pain", "dysmenorrhea", "red_eyes", "cramp"}
MUSCULOSKELETAL = {"head", "forehead", "temple", "occiput", "vertex", "neck_posterior", "neck_lateral", "shoulder", "elbow",
                   "wrist", "lumbar", "hip", "knee", "calf", "ankle", "face"}
_SEP = "、及与并和"
_STOP = "。；;\n"
_ENTRY_START = set("。；;）)」』") | {"壮", "呼"}
_NEEDLE = re.compile(r"(?:刺|针|鍼)入|灸[^。；]{0,3}壮|禁不可|不可[刺灸]|禁[刺针灸]")
_PROHIBIT = re.compile(r"(?:禁不可(?:刺|灸)|不可(?:刺|灸)|禁(?:刺|针|灸))[^。；，]{0,24}")
_LIMB_SIX = re.compile(r"(手足|手|足)?(太阴|少阴|厥阴|阳明|太阳|少阳|三阳|三阴|心主)|(督脉|任脉|冲脉|带脉|阴维|阳维|阴跷|阳跷)")


def _han(text: str) -> bool:
    return bool(HAN.search(text))


class Framework:
    """The data of ``acupuncture.yaml`` and what follows from it — no corpus needed."""

    def __init__(self, data: dict[str, Any], normalize: Any) -> None:
        self.d = data
        self.normalize = normalize
        self.channels: dict[str, dict[str, Any]] = data.get("channels") or {}
        self.points: dict[str, dict[str, Any]] = {}
        self.order: dict[str, int] = {}
        for i, p in enumerate(data.get("points") or []):
            code = p["code"]
            channel = code.split("-")[0] if code.startswith("EX-") else re.match(r"[A-Z]+", code).group(0)
            self.points[code] = {**p, "channel": channel}
            self.order[code] = i
        self.organs: dict[str, dict[str, Any]] = data.get("organs") or {}
        self.regions: dict[str, dict[str, Any]] = data.get("regions") or {}
        self.symptoms: dict[str, dict[str, Any]] = data.get("symptoms") or {}
        self.natures: dict[str, dict[str, Any]] = data.get("natures") or {}
        self.rules: dict[str, dict[str, Any]] = data.get("rules") or {}
        fs = data.get("five_shu") or {}
        self.kinds: list[str] = fs.get("kinds") or []
        self.kind_label: dict[str, str] = fs.get("labels") or {}
        self.kind_en: dict[str, str] = fs.get("en") or {}
        self._categories: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._index()

    # ------------------------------------------------------------ the specific-point tables, point by point
    def _add(self, code: str, type_: str, label: str, rule: str, **extra: Any) -> None:
        self._categories[code].append({"type": type_, "label": label, "rule": rule, **extra})

    def _index(self) -> None:
        d = self.d
        fs = d.get("five_shu") or {}
        for ch, codes in (fs.get("points") or {}).items():
            phases = fs["phases"]["yin" if self.channels[ch].get("yin") else "yang"]
            for kind, code, phase in zip(self.kinds, codes, phases):
                self._add(code, "five_shu", f"{self.channels[ch]['short']}{self.kind_label[kind]}穴（{phase}）", "five_shu",
                          channel=ch, kind=kind, phase=phase, en=f"{self.kind_en[kind]} point ({phase}) of the {self.channels[ch]['en']}")
        for ch, code in (d.get("yuan") or {}).items():
            self._add(code, "yuan", f"{self.channels[ch]['short']}原穴", "yuan", channel=ch,
                      en=f"Yuan-Source point of the {self.channels[ch]['en']}")
        for of, code in (d.get("luo") or {}).items():
            name = self.channels[of]["short"] if of in self.channels else of
            self._add(code, "luo", f"{name}络穴" if of in self.channels else of, "luo", channel=of if of in self.channels else None,
                      en=f"Luo-Connecting point of the {self.channels[of]['en']}" if of in self.channels else "point of the Great Luo of the Spleen")
        for of, code in (d.get("xi") or {}).items():
            if of in self.channels:
                self._add(code, "xi", f"{self.channels[of]['short']}郄穴", "xi", channel=of, en=f"Xi-Cleft point of the {self.channels[of]['en']}")
            else:
                self._add(code, "xi", f"{of}郄穴", "xi", vessel=of, en=f"Xi-Cleft point of the {(d['vessels'].get(of) or {}).get('en', of)}")
        for organ, code in (d.get("back_shu") or {}).items():
            self._add(code, "back_shu", f"{organ}之背俞穴", "back_shu", organ=organ, en=f"Back-Shu point of the {self.organs[organ]['en']}")
        for organ, code in (d.get("front_mu") or {}).items():
            self._add(code, "front_mu", f"{organ}之募穴", "front_mu", organ=organ, en=f"Front-Mu point of the {self.organs[organ]['en']}")
        for organ, code in (d.get("lower_he") or {}).items():
            self._add(code, "lower_he", f"{organ}之下合穴", "lower_he", organ=organ, en=f"Lower He-Sea point of the {self.organs[organ]['en']}")
        for of, h in (d.get("hui") or {}).items():
            self._add(h["point"], "hui", f"{of}会", "hui", of=of, en=f"Influential Point of the {h['en']}")
        for code, vessel in ((d.get("confluent") or {}).get("points") or {}).items():
            self._add(code, "confluent", f"八脉交会穴（通{vessel}）", "confluent", vessel=vessel,
                      en=f"Confluent point of the {(d['vessels'].get(vessel) or {}).get('en', vessel)}")
        for code, c in (d.get("crossing") or {}).items():
            self._add(code, "crossing", f"交会穴（{c['statement']}）", "crossing", channels=list(c.get("channels") or []),
                      vessels=list(c.get("vessels") or []), en="Crossing point")
        for code, c in (d.get("four_command") or {}).items():
            self._add(code, "four_command", f"四总穴（{c['area']}）", "four_command", area=c["area"], en="one of the Four Command Points")
        for code, p in self.points.items():
            if p["channel"] == "EX":
                self._add(code, "extra", "经外奇穴", "extra", en="extra point")

    def categories(self, code: str) -> list[dict[str, Any]]:
        return list(self._categories.get(code, []))

    def has(self, code: str, kind: str, **match: Any) -> bool:
        return any(c["type"] == kind and all(c.get(k) == v for k, v in match.items()) for c in self._categories.get(code, []))

    def five_shu(self, ch: str, kind: str) -> str | None:
        codes = ((self.d.get("five_shu") or {}).get("points") or {}).get(ch)
        return codes[self.kinds.index(kind)] if codes and kind in self.kinds else None

    def phase_point(self, ch: str, phase: str) -> str | None:
        """The Five-Shu point of a channel whose phase is ``phase`` (Nanjing 64)."""
        fs = self.d.get("five_shu") or {}
        codes = (fs.get("points") or {}).get(ch)
        if not codes:
            return None
        phases = fs["phases"]["yin" if self.channels[ch].get("yin") else "yang"]
        return codes[phases.index(phase)]

    def phase_channel(self, phase: str, yin: bool) -> str | None:
        """The channel of a phase and polarity — of the two Fire channels of each polarity the Heart's and the Small
        Intestine's (君火), as the teaching examples take them, not the Pericardium's or the Sanjiao's (相火)."""
        for ch in ("LU", "LI", "ST", "SP", "HT", "SI", "BL", "KI", "GB", "LR"):
            c = self.channels[ch]
            if c.get("phase") == phase and bool(c.get("yin")) == yin:
                return ch
        return None

    def mother_child(self, ch: str) -> dict[str, Any] | None:
        """补母泻子 for one channel: its phase, the mother and child phases (generating cycle), the mother point and the child
        point on the channel itself, the mother's and the child's channel and their own-phase points, the channel's own-phase
        point."""
        c = self.channels.get(ch) or {}
        phase = c.get("phase")
        if not phase or not self.five_shu(ch, "jing_well"):
            return None
        mother, child = MOTHER[phase], GENERATES[phase]
        yin = bool(c.get("yin"))
        mch, cch = self.phase_channel(mother, yin), self.phase_channel(child, yin)
        return {"channel": ch, "phase": phase, "mother_phase": mother, "child_phase": child,
                "same": {"mother": self.phase_point(ch, mother), "child": self.phase_point(ch, child)},
                "cross": {"mother_channel": mch, "mother": self.phase_point(mch, mother) if mch else None,
                          "child_channel": cch, "child": self.phase_point(cch, child) if cch else None},
                "own": self.phase_point(ch, phase)}

    # ------------------------------------------------------------ the Five Phases: a point's phase against its channel's
    @property
    def wx(self) -> dict[str, Any]:
        return self.d.get("five_phases") or {}

    def shu_phase(self, code: str) -> str | None:
        return next((c["phase"] for c in self.categories(code) if c["type"] == "five_shu"), None)

    def relation(self, phase: str, of: str) -> str:
        """What ``phase`` (a point's) is to ``of`` (its channel's): same, child, controlled, controller or mother."""
        if phase == of:
            return "same"
        if GENERATES[of] == phase:
            return "child"
        if CONTROLS[of] == phase:
            return "controlled"
        if CONTROLS[phase] == of:
            return "controller"
        return "mother"

    def relation_text(self, phase: str, of: str) -> str:
        rel = self.relation(phase, of)
        name = ((self.wx.get("relations") or {}).get(rel) or {}).get("name", rel)
        return {"same": f"{name}：同属{of}", "child": f"{name}：{of}生{phase}", "controlled": f"{name}：{of}克{phase}",
                "controller": f"{name}：{phase}克{of}", "mother": f"{name}：{phase}生{of}"}[rel]

    def channel_phases(self, ch: str) -> list[dict[str, Any]]:
        """A channel's five Five-Shu points: the category, the point's phase, and what that phase is to the channel's —
        three attributes, kept apart (大敦 is the Liver's same-phase point, 太冲 its Yuan point)."""
        of = self.channels[ch]["phase"]
        rows = []
        for kind in self.kinds:
            code = self.five_shu(ch, kind)
            phase = self.shu_phase(code)
            rows.append({"code": code, "name": self.points[code]["name"], "kind": kind, "label": self.kind_label[kind],
                         "en": self.kind_en[kind], "phase": phase, "relation": self.relation(phase, of),
                         "relation_text": self.relation_text(phase, of), "yuan": (self.d.get("yuan") or {}).get(ch) == code})
        return rows

    def saam(self, ch: str) -> dict[str, Any] | None:
        """舍岩针法 for one channel: the deficiency template (正格: tonify the mother, sedate the controller) and the excess
        template (胜格: tonify the controller, sedate the child) — each phase taken on the channel itself and on that
        phase's own channel of the same polarity."""
        c = self.channels.get(ch) or {}
        own = c.get("phase")
        if not own or not self.five_shu(ch, "jing_well"):
            return None
        yin = bool(c.get("yin"))

        def two(phase: str) -> dict[str, Any]:
            other = self.phase_channel(phase, yin)
            return {"phase": phase, "channels": [ch, other], "points": [self.phase_point(ch, phase), self.phase_point(other, phase)]}

        return {"channel": ch, "phase": own,
                "deficiency": {"tonify": two(MOTHER[own]), "sedate": two(CONTROLLED_BY[own])},
                "excess": {"tonify": two(CONTROLLED_BY[own]), "sedate": two(GENERATES[own])}}

    def paired(self, ch: str) -> dict[str, Any] | None:
        """The mother-phase and child-phase points of the channel's interior–exterior partner and of its same-name channel
        (a deduction in two steps: the relation of the channels, then the phase)."""
        c = self.channels.get(ch) or {}
        own = c.get("phase")
        if not own or not self.five_shu(ch, "jing_well"):
            return None
        out: dict[str, Any] = {"channel": ch, "phase": own}
        for via, other in (("interior_exterior", c.get("partner")), ("same_name", c.get("same_name"))):
            if other and self.five_shu(other, "jing_well"):
                out[via] = {"channel": other, "mother": self.phase_point(other, MOTHER[own]), "child": self.phase_point(other, GENERATES[own])}
        return out

    def phase_organ(self, phase: str, hint: str = "") -> str:
        """The organ that stands for a phase: the one the hint writes (胃 in 肝胃不和), else its zang."""
        info = (self.wx.get("phases") or {})[phase]
        for o in sorted([info["zang"], info["fu"], *(info.get("also") or [])], key=len, reverse=True):
            if o in hint:
                return o
        return info["zang"]

    def phase_states(self, text: str) -> dict[str, Any]:
        """The Five-Phase states a text names: a pattern already identified (肝郁脾虚 — Wood excess, Earth deficiency), or an
        organ, a phase or its English name with a word of excess or deficiency (肝实, 土虚, 脾肺气虚, Wood excess, deficient
        Earth).  Each state: its phase, organ, channel, excess / deficiency / any, and what the text wrote."""
        wx = self.wx
        norm = self.normalize(text or "").lower()
        taken = [False] * len(norm)
        found: list[dict[str, Any]] = []
        spans: list[dict[str, Any]] = []
        notes: list[dict[str, str]] = []

        def add(phase: str, organ: str, state: str, written: str, at: tuple[int, int], pattern: str | None = None, note: str | None = None) -> None:
            status = mention_status(norm, *at)
            if status != "present":
                item = {"text": written, "status": status, "note": {"negated": "已否定，不作为当前证候",
                        "uncertain": "尚待确认，不作为已成立的证候", "historical": "既往记录，不作为当前证候"}[status]}
                if item not in notes:
                    notes.append(item)
                return
            if any(f["phase"] == phase and f["organ"] == organ and f["state"] == state for f in found):
                return
            found.append({"phase": phase, "organ": organ, "channel": self.organs[organ]["channel"], "state": state, "written": written,
                          "pattern": pattern, "note": note})
            spans.append({"text": written, "span": list(at)})

        def free(a: int, b: int) -> bool:
            return not any(taken[a:b])

        def take(a: int, b: int) -> None:
            for i in range(a, b):
                taken[i] = True

        for name in sorted(wx.get("named") or {}, key=len, reverse=True):
            spec = wx["named"][name]
            for m in re.finditer(re.escape(self.normalize(name)), norm):
                if not free(m.start(), m.end()):
                    continue
                take(m.start(), m.end())
                if not any(k in GENERATES for k in spec):  # 阴虚火旺: no phase's own excess
                    notes.append({"text": text[m.start():m.end()], "note": spec.get("note") or ""})
                for phase, state in spec.items():
                    if phase in GENERATES:
                        add(phase, self.phase_organ(phase, name), state, text[m.start():m.end()], (m.start(), m.end()), name, spec.get("note"))
        words: dict[str, str] = {}
        for sid, s in (wx.get("states") or {}).items():
            for n in s.get("names") or []:
                words[self.normalize(n).lower()] = sid
        cn_org = {o: o for o in self.organs} | {p: p for p in GENERATES}
        en_org = {p["en"].lower(): ph for ph, p in (wx.get("phases") or {}).items()}
        for o, info in self.organs.items():
            for n in info.get("names") or []:
                if n.isascii():
                    en_org[n.lower()] = o
        alt = lambda xs: "|".join(re.escape(x) for x in sorted(xs, key=len, reverse=True))  # noqa: E731
        cn_words = [w for w in words if not w.isascii()]
        en_words = [w for w in words if w.isascii()]
        cn = re.compile(rf"((?:{alt(cn_org)}){{1,3}})(?:经)?(?:两|俱|皆|同|之)?(?:气|阴|阳|血|精)?({alt(cn_words)})")
        organ_re = re.compile(alt(cn_org))

        def organ_for(x: str) -> tuple[str, str]:
            if x in GENERATES:
                return x, self.phase_organ(x)
            return self.channels[self.organs[x]["channel"]]["phase"], x

        for m in cn.finditer(norm):
            if not free(m.start(), m.end()):
                continue
            take(m.start(), m.end())
            named = organ_re.findall(m.group(1))
            if any(o not in GENERATES for o in named):  # 胃火旺, 肝木虚: a phase after an organ qualifies it, it is no second organ
                named = [o for o in named if o not in GENERATES]
            for o in named:
                phase, organ = organ_for(o)
                add(phase, organ, words[m.group(2)], text[m.start():m.end()], (m.start(), m.end()))
        if en_words:
            org = alt(en_org)
            st = alt(en_words)
            for rx, oi, si in ((rf"(?<![a-z])({org})\s+(?:qi\s+|yin\s+|yang\s+|blood\s+)?({st})(?![a-z])", 1, 2),
                               (rf"(?<![a-z])({st})(?:\s+of|\s+in)?\s+(?:the\s+)?({org})(?![a-z])", 2, 1)):
                for m in re.finditer(rx, norm):
                    if not free(m.start(), m.end()):
                        continue
                    take(m.start(), m.end())
                    x = en_org[m.group(oi)]
                    phase, organ = organ_for(x)
                    add(phase, organ, words[m.group(si)], text[m.start():m.end()], (m.start(), m.end()))
        return {"states": found, "spans": sorted(spans, key=lambda s: s["span"][0]), "notes": notes}

    def point_of(self, code: str) -> dict[str, Any]:
        return self.points[code]

    def resolve(self, name: str) -> str | None:
        """A point by its code (ST36, st-36), name, an alias or its pinyin."""
        raw = (name or "").strip()
        key = re.sub(r"[\s\-_.]", "", raw).upper()
        for code in self.points:
            if re.sub(r"[\s\-_.]", "", code).upper() == key:
                return code
            if any(re.sub(r"[\s\-_.]", "", o).upper() == key for o in self.points[code].get("other_codes") or []):
                return code
        norm = self.normalize(raw)
        for code, p in self.points.items():
            if norm in {self.normalize(n) for n in [p["name"], *(p.get("aliases") or [])]}:
                return code
        low = re.sub(r"\s", "", raw.lower())
        for code, p in self.points.items():
            if p.get("pinyin", "").lower() == low:
                return code
        return None

    def names(self, code: str) -> list[str]:
        """The written forms a text may give a point: its name and aliases, with 腧 / 输 for 俞 and 窌 for 髎."""
        p = self.points[code]
        out: list[str] = []
        for n in [p["name"], *(p.get("aliases") or [])]:
            for form in {n, n.replace("俞", "腧"), n.replace("俞", "输"), n.replace("髎", "窌")}:
                form = self.normalize(form)
                if len(form) >= 2 and form not in out:
                    out.append(form)
        return out

    # ------------------------------------------------------------ reading a presentation
    def vocabulary(self) -> list[tuple[str, str, str]]:
        """(normalised name, kind, id) of every region, symptom, organ, channel, nature, course and side, longest first."""
        out: list[tuple[str, str, str]] = []
        for kind, table in (("region", self.regions), ("symptom", self.symptoms), ("organ", self.organs),
                            ("nature", self.natures), ("acuity", self.d.get("acuity") or {}), ("side", self.d.get("sides") or {})):
            for key, v in table.items():
                for n in [v.get("name", key), *(v.get("names") or [])]:
                    if n:
                        out.append((self.normalize(n).lower(), kind, key))
        for ch, c in self.channels.items():
            if ch == "EX":
                continue
            for n in [c["name"], *(c.get("names") or [])]:
                if len(n) >= 2 and n not in self.organs:  # 肺 is the organ; 手太阴 and 肺经 the channel
                    out.append((self.normalize(n).lower(), "channel", ch))
        seen: set[tuple[str, str]] = set()
        uniq = []
        for n, kind, key in sorted(out, key=lambda x: -len(x[0])):
            if (n, kind) not in seen:
                seen.add((n, kind))
                uniq.append((n, kind, key))
        return uniq

    def read(self, text: str) -> dict[str, Any]:
        """The regions, symptoms, organs, channels, natures, course and side a text names (longest name first; English
        names as whole words), and what it says that none of them is."""
        norm = self.normalize(text or "").lower()
        taken = [False] * len(norm)
        found: dict[str, list[str]] = defaultdict(list)
        spans: list[dict[str, Any]] = []
        for name, kind, key in self.vocabulary():
            ascii_name = name.isascii()
            pattern = (r"(?<![a-z])" + re.escape(name) + r"(?![a-z])") if ascii_name else re.escape(name)
            for m in re.finditer(pattern, norm):
                if any(taken[m.start():m.end()]):
                    continue
                for i in range(m.start(), m.end()):
                    taken[i] = True
                if key not in found[kind]:
                    found[kind].append(key)
                spans.append({"text": text[m.start():m.end()], "kind": kind, "id": key, "span": [m.start(), m.end()]})
        rest = "".join(ch if not taken[i] else " " for i, ch in enumerate(norm))
        unread = [w for w in re.split(r"[\s，。、；;,.:：！!？?（）()【】\[\]“”\"'/]+", rest) if _han(w) and len(w) >= 2]
        return {"found": dict(found), "spans": sorted(spans, key=lambda s: s["span"][0]), "unread": unread}

    def lookup(self, kind: str, value: str) -> str | None:
        """An id of the given kind for a value written as its id, its name or one of its names."""
        table = {"region": self.regions, "symptom": self.symptoms, "organ": self.organs, "nature": self.natures,
                 "acuity": self.d.get("acuity") or {}, "side": self.d.get("sides") or {}}.get(kind)
        v = (value or "").strip()
        if kind == "channel":
            up = v.upper()
            if up in self.channels and up != "EX":
                return up
            norm = self.normalize(v)
            for ch, c in self.channels.items():
                if ch != "EX" and norm in {self.normalize(n) for n in [c["name"], *(c.get("names") or [])]}:
                    return ch
            return None
        if table is None:
            return None
        if v in table:
            return v
        norm = self.normalize(v).lower()
        for key, t in table.items():
            if norm in {self.normalize(n).lower() for n in [t.get("name", key), *(t.get("names") or [])] if n}:
                return key
        return None


class AcupunctureStudy:
    """``study.acupoints`` (framework, selection) and ``study.point`` over a corpus."""

    def __init__(self, base: StudyBase) -> None:
        self.b = base
        self._fw: Framework | None = None
        self._name_re: re.Pattern[str] | None = None
        self._name_code: dict[str, str] = {}
        self._parsed: dict[str, dict[str, Any]] = {}
        self._rules_seen: dict[str, dict[str, Any]] = {}
        self._by_point: dict[str, dict[str, Any]] = {}
        self._acu_books: list[str] | None = None

    @property
    def fw(self) -> Framework:
        if self._fw is None:
            self._fw = Framework(self.b.data("acupuncture.yaml"), self.b.normalize)
        return self._fw

    @property
    def notice(self) -> str:
        return (self.fw.d.get("notice") or "").strip()

    # ============================================================ the framework
    def framework(self) -> dict[str, Any]:
        """The specific-point tables and the mother–child points of every channel, computed from the data."""
        fw = self.fw
        label = lambda code: f"{fw.points[code]['name']} {code}" if code else ""  # noqa: E731
        five = []
        for ch in ("LU", "LI", "ST", "SP", "HT", "SI", "BL", "KI", "PC", "TE", "GB", "LR"):
            row: dict[str, Any] = {"channel": ch, "name": fw.channels[ch]["name"], "yin": bool(fw.channels[ch].get("yin"))}
            for kind in fw.kinds:
                code = fw.five_shu(ch, kind)
                phase = next(c["phase"] for c in fw.categories(code) if c["type"] == "five_shu")
                row[kind] = {"code": code, "name": fw.points[code]["name"], "phase": phase}
            five.append(row)
        d = fw.d
        specific = [{"channel": ch, "name": fw.channels[ch]["name"], "yuan": label(d["yuan"].get(ch)), "luo": label(d["luo"].get(ch)),
                     "xi": label(d["xi"].get(ch)), "yuan_is_shu": d["yuan"].get(ch) == fw.five_shu(ch, "shu_stream")}
                    for ch in d["yuan"]]
        shu_mu = [{"organ": o, "kind": fw.organs[o]["kind"], "back_shu": label(code), "front_mu": label(d["front_mu"][o]),
                   "mu_channel": fw.points[d["front_mu"][o]]["channel"], "organ_channel": fw.organs[o]["channel"]}
                  for o, code in d["back_shu"].items()]
        lower = [{"organ": o, "he_sea": label(fw.five_shu(fw.organs[o]["channel"], "he_sea")), "lower_he": label(code),
                  "same": fw.five_shu(fw.organs[o]["channel"], "he_sea") == code} for o, code in d["lower_he"].items()]
        hui = [{"of": of, "en": h["en"], "point": label(h["point"])} for of, h in d["hui"].items()]
        conf = [{"points": [label(c) for c in pr["points"]], "vessels": [d["confluent"]["points"][c] for c in pr["points"]],
                 "emphasis": pr["emphasis"], "en": pr["en"]} for pr in d["confluent"]["pairs"]]
        mc = []
        for ch in ("LU", "LI", "ST", "SP", "HT", "SI", "BL", "KI", "PC", "TE", "GB", "LR"):
            m = fw.mother_child(ch)
            mc.append({**m, "name": fw.channels[ch]["name"],
                       "labels": {"mother": label(m["same"]["mother"]), "child": label(m["same"]["child"]), "own": label(m["own"]),
                                  "cross_mother": label(m["cross"]["mother"]), "cross_child": label(m["cross"]["child"])}})
        twelve = ("LU", "LI", "ST", "SP", "HT", "SI", "BL", "KI", "PC", "TE", "GB", "LR")
        phases = [{"channel": ch, "name": fw.channels[ch]["name"], "phase": fw.channels[ch]["phase"], "points": fw.channel_phases(ch)} for ch in twelve]
        saam = []
        for ch in twelve:
            s = fw.saam(ch)
            saam.append({"channel": ch, "name": fw.channels[ch]["name"], "phase": s["phase"],
                         **{state: {act: {"phase": s[state][act]["phase"], "points": [label(c) for c in s[state][act]["points"]]}
                                    for act in ("tonify", "sedate")} for state in STATES}})
        paired = []
        for ch in twelve:
            pr = fw.paired(ch)
            paired.append({"channel": ch, "name": fw.channels[ch]["name"], "phase": pr["phase"],
                           **{via: {"channel": fw.channels[pr[via]["channel"]]["name"], "mother": label(pr[via]["mother"]),
                                    "child": label(pr[via]["child"])} for via in ("interior_exterior", "same_name") if via in pr}})
        wx = fw.wx
        return {"five_shu": five, "yuan_luo_xi": specific, "extra_luo": {k: label(v) for k, v in d["luo"].items() if k not in d["yuan"]},
                "extra_xi": {k: label(v) for k, v in d["xi"].items() if k not in d["yuan"]}, "shu_mu": shu_mu,
                "lower_he": lower, "hui": hui, "confluent": conf, "mother_child": mc,
                "five_phases": {"terms": wx.get("terms") or [], "channel_phases": phases, "saam": saam, "paired": paired,
                                "pathology": [{"id": k, **v} for k, v in (wx.get("pathology") or {}).items()],
                                "pathogens": [{"id": k, **v} for k, v in (wx.get("pathogens") or {}).items()],
                                "strategies": [{"id": k, **{x: v.get(x) for x in ("name", "en", "premise", "implication", "note")}}
                                               for k, v in (wx.get("strategies") or {}).items()],
                                "methods": [{"id": k, "name": v["name"], "en": v["en"], "level": v["level"], "level_name": LEVELS.get(v["level"], v["level"])}
                                            for k, v in (wx.get("methods") or {}).items()],
                                "guards": [{"id": k, "statement": v["statement"], "level": v.get("level")} for k, v in (wx.get("guards") or {}).items()
                                           if v.get("when") == "always"]},
                "counts": {"five_shu": sum(1 for code in fw.points if fw.has(code, "five_shu")), "luo": len(d["luo"]), "xi": len(d["xi"]),
                           "hui": len(d["hui"]), "confluent": len(d["confluent"]["points"]), "lower_he": len(d["lower_he"])},
                "rules": [self._rule_card(r) for r in ("five_shu", "five_phase", "nanjing68", "lingshu44", "yuan", "luo", "xi",
                                                         "back_shu", "lower_he", "hui", "confluent", "mother_child", "own_phase",
                                                         "five_phase_cycles", "five_pathogens", "nanjing75", "nanjing79", "prevent_transmission",
                                                         "saam", "pair_mother_child")],
                "evidence_levels": d.get("evidence_levels") or [], "notice": self.notice}

    # ============================================================ selection
    def select(self, text: str | None = None, *, regions: Iterable[str] = (), symptoms: Iterable[str] = (),
               organs: Iterable[str] = (), channels: Iterable[str] = (), natures: Iterable[str] = (), acute: bool | None = None,
               side: str | None = None, pregnant: bool = False, max_points: int = 6, classical: bool = True) -> dict[str, Any]:
        fw = self.fw
        pres = self._presentation(text, regions, symptoms, organs, channels, natures, acute, side, pregnant)
        if not (pres["regions"] or pres["symptoms"] or pres["organs"] or pres["channels"]):
            raise ValueError("study.acupoints: name where the disorder is or what it is — a region (胃脘, 腰, 颈项 …), a symptom "
                             "(恶心, 失眠, 头痛 …), an organ system or a channel (胃, 足阳明 …); "
                             f"regions it knows: {'、'.join(r['name'] for r in list(fw.regions.values())[:12])} …")
        objectives = self._objectives(pres)
        cands: dict[str, dict[str, Any]] = {}
        notes: list[str] = []
        self._propose(pres, objectives, cands, notes)
        attest = self._attest(pres, cands) if classical else {"findings": [], "searched": False}
        excluded = self._excluded(cands, pres)
        chosen, core = self._choose(objectives, {k: v for k, v in cands.items() if k not in excluded}, max_points)
        labels = {o["id"]: o["label"] for o in objectives}
        points = [self._point_out(code, cands[code], code in core, pres, labels) for code in chosen]
        combos = self._combinations(chosen, cands, pres)
        used = sorted({r["rule"] for c in chosen for r in cands[c]["reasons"]} | {c["rule"] for c in combos}
                      | {n.get("rule") for n in (fw.natures.get(x) or {} for x in pres["natures"]) if n.get("rule")}
                      | {"localization", "safety", "record"},
                      key=lambda r: list(fw.rules).index(r) if r in fw.rules else 999)
        out: dict[str, Any] = {
            "presentation": pres,
            "objectives": [{k: o.get(k) for k in ("id", "kind", "label", "principal", "inferred", "via")} for o in objectives],
            "channels": self._channels_read(pres, objectives),
            "prescription": {"core": [p for p in points if p["core"]], "supplementary": [p for p in points if not p["core"]],
                             "ashi": self._ashi(pres)},
            "combinations": combos,
            "alternatives": self._alternatives({k: v for k, v in cands.items() if k not in excluded}, chosen),
            "excluded": [{"code": c, "name": fw.points[c]["name"], "why": why} for c, why in excluded.items()],
            "mother_child": self._mc_out(pres),
            "technique": self._technique(pres),
            "implementation": self._implementation(chosen, pres),
            "cautions": self._cautions(chosen, pres),
            "classical": attest,
            "rules": [self._rule_card(r) for r in used if r in fw.rules],
            "evidence": self._evidence(chosen, pres),
            "five_phase": self._five_phase_brief(pres),
            "steps": [],
            "notes": notes,
            "notice": self.notice,
        }
        for p in points:
            mine = [m for m in out["evidence"]["modern"] if m["scope"] == "points" and p["name"] in m["bears_on"]]
            broad = [m for m in out["evidence"]["modern"] if m["scope"] == "broad"]
            p["record"]["modern_evidence"] = "；".join([f"{m['id']}（{m['population']}）" for m in mine]
                                                       + [f"{m['id']}（针灸整体的证据，不针对此穴）" for m in broad]) or "未见记录"
        out["steps"] = self._steps(out)
        out["summary"] = {"points": len(chosen), "core": len(core), "objectives": len(objectives), "combinations": len(combos),
                          "candidates": len(cands), "rules": len(out["rules"])}
        return out

    def _five_phase_brief(self, pres: dict[str, Any]) -> dict[str, Any] | None:
        """Where the presentation writes states organ by organ, what the Five-Phase reading adds (study.wuxing in full)."""
        if not pres.get("states") or not pres.get("text"):
            return None
        r = self.wuxing(pres["text"], classical=False)
        return {"states": [f"{s['organ']}（{s['phase']}）{s['state_name']}" + (f"〔{s['pattern']}〕" if s.get("pattern") else "") for s in r["states"]],
                "relations": [x["text"] for x in r["relations"]],
                "strategies": [s["name"] for s in r["strategies"] if s["fit"] == "full"],
                "conflicts": [c["text"] for c in r["conflicts"]],
                "guards": [g["statement"] for g in r["guards"] if g["why"] != "always"],
                "see": "study.wuxing：五行关系、取法（本经与他经补母泻子、舍岩针法、表里经与同名经之推演）与不能推出的结论"}

    # ------------------------------------------------------------ step 1: the presentation
    def _presentation(self, text: str | None, regions: Iterable[str], symptoms: Iterable[str], organs: Iterable[str],
                      channels: Iterable[str], natures: Iterable[str], acute: bool | None, side: str | None,
                      pregnant: bool) -> dict[str, Any]:
        fw = self.fw
        got: dict[str, list[str]] = {k: [] for k in ("region", "symptom", "organ", "channel", "nature", "acuity", "side")}
        unknown: list[str] = []
        for kind, values in (("region", regions), ("symptom", symptoms), ("organ", organs), ("channel", channels), ("nature", natures)):
            for v in values or []:
                key = fw.lookup(kind, v)
                if key is None:  # a value given under the wrong heading (失眠 as a region) is read for what it is
                    read = fw.read(v)["found"]
                    keys = [(k, x) for k, xs in read.items() for x in xs]
                    if not keys:
                        unknown.append(v)
                    for k, x in keys:
                        if x not in got[k]:
                            got[k].append(x)
                elif key not in got[kind]:
                    got[kind].append(key)
        read: dict[str, Any] = {"spans": [], "unread": []}
        states: list[dict[str, Any]] = []
        if text:
            read = fw.read(text)
            for kind, keys in read["found"].items():
                for key in keys:
                    if key not in got[kind]:
                        got[kind].append(key)
            # a state written organ by organ (肝实脾虚, 木实土虚): each organ's own excess or deficiency
            states = [{k: e[k] for k in ("organ", "channel", "phase", "state", "pattern")} for e in fw.phase_states(text)["states"]
                      if e["state"] in STATES]
            for e in states:
                if e["organ"] not in got["organ"]:
                    got["organ"].append(e["organ"])
                nat = "deficiency" if e["state"] == "deficiency" else "excess"
                if nat not in got["nature"]:
                    got["nature"].append(nat)
        if side:
            s = fw.lookup("side", side)
            if s and s not in got["side"]:
                got["side"].insert(0, s)
        acuity = "acute" if acute else ("chronic" if acute is False else (got["acuity"][0] if got["acuity"] else None))
        inferred: dict[str, list[str]] = {"regions": [], "organs": []}
        for s in got["symptom"]:  # a symptom's usual region, unless it or a region within it (前额 in 头部) is given
            r = fw.symptoms[s].get("region")
            if r and not any(g == r or fw.regions[g].get("within") == r or fw.regions[r].get("within") == g for g in got["region"]):
                got["region"].append(r)
                inferred["regions"].append(r)
        if not got["organ"] and not got["channel"]:
            for src in [fw.regions[r] for r in got["region"]] + [fw.symptoms[s] for s in got["symptom"]]:
                for o in src.get("organs") or []:
                    if o not in got["organ"]:
                        got["organ"].append(o)
                        inferred["organs"].append(o)
        # a channel named for its organ's sake (肺经) counts as that organ's channel, not as a second objective
        organ_channels = {fw.organs[o]["channel"] for o in got["organ"]}
        return {"text": text or "", "regions": got["region"], "symptoms": got["symptom"], "organs": got["organ"],
                "channels": [c for c in got["channel"] if c not in organ_channels], "natures": got["nature"], "acuity": acuity,
                "side": (got["side"] or [None])[0], "pregnant": bool(pregnant), "inferred": inferred, "states": states,
                "read": read.get("spans", []), "unread": read.get("unread", []) + unknown,
                "labels": {"regions": [fw.regions[r]["name"] for r in got["region"]],
                           "symptoms": [fw.symptoms[s]["name"] for s in got["symptom"]],
                           "organs": got["organ"], "channels": [fw.channels[c]["name"] for c in got["channel"]],
                           "natures": [fw.natures[n]["name"] for n in got["nature"]]}}

    def _objectives(self, pres: dict[str, Any]) -> list[dict[str, Any]]:
        fw = self.fw
        out: list[dict[str, Any]] = []
        for r in pres["regions"]:
            out.append({"id": f"region:{r}", "kind": "location", "key": r, "label": f"病位：{fw.regions[r]['name']}",
                        "inferred": r in pres["inferred"]["regions"]})
        for o in pres["organs"]:
            kind = "脏" if fw.organs[o]["kind"] == "zang" else "腑"
            out.append({"id": f"organ:{o}", "kind": "pattern", "key": o, "label": f"脏腑：{o}（{kind}）",
                        "inferred": o in pres["inferred"]["organs"]})
        for c in pres["channels"]:
            out.append({"id": f"channel:{c}", "kind": "channel", "key": c, "label": f"经脉：{fw.channels[c]['name']}", "inferred": False})
        for s in pres["symptoms"]:
            sym = fw.symptoms[s]
            # a symptom whose points are for an unlocated complaint (头痛) is served by the region that locates it (前额)
            via = next((f"region:{r}" for r in pres["regions"] if sym.get("generic") and fw.regions[r].get("within") == sym.get("region")), None)
            out.append({"id": f"symptom:{s}", "kind": "symptom", "key": s, "label": f"症状：{sym['name']}", "inferred": False, "via": via})
        for n in pres["natures"]:
            out.append({"id": f"nature:{n}", "kind": "nature", "key": n, "label": f"病性：{fw.natures[n]['name']}", "inferred": False})
        principal = next((o for o in out if o["kind"] == "location" and not o["inferred"]), None) \
            or next((o for o in out if o["kind"] in ("pattern", "channel") and not o["inferred"]), None) \
            or next((o for o in out if o["kind"] == "symptom"), None) or (out[0] if out else None)
        for o in out:
            o["principal"] = o is principal
        return out

    def _affected_channels(self, pres: dict[str, Any]) -> list[str]:
        """The channels a channel-bound rule applies to: those of the organs named, then the channels named."""
        fw = self.fw
        out = [fw.organs[o]["channel"] for o in pres["organs"]] + list(pres["channels"])
        return list(dict.fromkeys(c for c in out if c in fw.channels and c not in MIDLINE | {"EX"}))

    # ------------------------------------------------------------ step 2–3: candidates and their reasons
    def _reason(self, cands: dict[str, dict[str, Any]], code: str, objective: str, rule: str, weight: int, text: str,
                **extra: Any) -> None:
        if code not in self.fw.points:
            return
        c = cands.setdefault(code, {"reasons": [], "by": {}, "rank": 99})
        c["reasons"].append({"objective": objective, "rule": rule, "weight": weight, "text": text, **extra})
        c["by"][objective] = max(c["by"].get(objective, 0), weight)
        c["rank"] = min(c["rank"], int(extra.get("rank", 99)))

    def _propose(self, pres: dict[str, Any], objectives: list[dict[str, Any]], cands: dict[str, dict[str, Any]],
                 notes: list[str]) -> None:
        fw, d = self.fw, self.fw.d
        name = lambda code: fw.points[code]["name"]  # noqa: E731
        affected = self._affected_channels(pres)
        for o in objectives:
            oid = o["id"]
            if o["kind"] == "location":
                reg = fw.regions[o["key"]]
                for i, code in enumerate(reg.get("local") or []):
                    self._reason(cands, code, oid, "local", WEIGHT["local"], f"近部：位于{reg['name']}", rank=i)
                for code in (reg.get("back") or []) + (reg.get("front") or []):
                    where = "背部" if reg.get("back") and code in reg["back"] else "胸腹部"
                    self._reason(cands, code, oid, "anterior_posterior", WEIGHT["posterior"], f"前后：{reg['name']}在{'前' if where == '背部' else '后'}，此穴在{where}")
                for i, code in enumerate(reg.get("distal") or []):
                    ch = fw.points[code]["channel"]
                    self._reason(cands, code, oid, "distal", WEIGHT["distal"],
                                 f"远部：{fw.channels[ch]['short']}之穴，经络上与{reg['name']}相连" if ch in reg.get("channels", []) else f"远部：{reg['name']}之远道取穴",
                                 rank=i)
                for code, c in (d.get("four_command") or {}).items():
                    if o["key"] in c["regions"]:
                        self._reason(cands, code, oid, "four_command", WEIGHT["four_command"], f"四总穴：{c['area']}{name(code)}")
                for pair in d["confluent"]["pairs"]:
                    if o["key"] in pair["regions"]:
                        for code in pair["points"]:
                            self._reason(cands, code, oid, "confluent_pair", WEIGHT["confluent_pair"],
                                         f"八脉交会：{'、'.join(name(c) for c in pair['points'])}相配，主{pair['emphasis']}", pair=pair["points"])
            elif o["kind"] == "pattern":
                organ = o["key"]
                info = fw.organs[organ]
                ch = info["channel"]
                zang = info["kind"] == "zang"
                self._reason(cands, d["back_shu"][organ], oid, "back_shu", WEIGHT["back_shu"] if zang else 2, f"{organ}之背俞穴" + ("（脏病多取背俞）" if zang else ""))
                self._reason(cands, d["front_mu"][organ], oid, "front_mu", WEIGHT["front_mu"] if not zang else 2, f"{organ}之募穴" + ("（腑病多取募穴）" if not zang else ""))
                self._reason(cands, d["yuan"][ch], oid, "yuan", 3 if zang else 1, f"{fw.channels[ch]['short']}原穴" + ("（五藏有疾，当取之十二原）" if zang else ""))
                if organ in d["lower_he"]:
                    self._reason(cands, d["lower_he"][organ], oid, "lower_he", WEIGHT["lower_he"], f"{organ}之下合穴（合治内府）")
                self._xi(cands, ch, oid, pres)
                self._host_guest(cands, ch, oid, affected)
            elif o["kind"] == "channel":
                ch = o["key"]
                if ch in d["yuan"]:
                    self._reason(cands, d["yuan"][ch], oid, "yuan", WEIGHT["yuan"], f"{fw.channels[ch]['short']}原穴")
                if ch in d["luo"]:
                    self._reason(cands, d["luo"][ch], oid, "luo", WEIGHT["minor"], f"{fw.channels[ch]['short']}络穴（兼及表里两经）")
                self._xi(cands, ch, oid, pres)
            elif o["kind"] == "symptom":
                sym = fw.symptoms[o["key"]]
                located = sym.get("generic") and any(fw.regions[r].get("within") == sym.get("region") for r in pres["regions"])
                for i, code in enumerate([] if located else sym.get("points") or []):
                    self._reason(cands, code, oid, "symptom", WEIGHT["symptom"] if i == 0 else WEIGHT["symptom_more"],
                                 f"对症：{sym['name']}" + (f"（{sym['note']}）" if sym.get("note") and i == 0 else ""), rank=i)
                if pres["acuity"] == "acute":
                    for code in sym.get("acute") or []:
                        self._reason(cands, code, oid, "xi", WEIGHT["xi"], f"急症取郄：{sym['name']}")
                for pair in d["confluent"]["pairs"]:
                    if o["key"] in pair["symptoms"]:
                        for code in pair["points"]:
                            self._reason(cands, code, oid, "confluent_pair", WEIGHT["confluent_pair"],
                                         f"八脉交会：{'、'.join(name(c) for c in pair['points'])}主{pair['emphasis']}", pair=pair["points"])
                if sym.get("five_shu"):
                    self._five_shu_hint(cands, sym["five_shu"], oid, affected, "nanjing68", sym["name"], notes)
            elif o["kind"] == "nature":
                n = fw.natures[o["key"]]
                for code in n.get("points") or []:
                    self._reason(cands, code, oid, n.get("rule") or "pattern", WEIGHT["pattern"], f"辨证：{n['name']}（{n.get('principle', '')}）")
                if n.get("hui"):
                    h = d["hui"][n["hui"]]
                    self._reason(cands, h["point"], oid, "hui", WEIGHT["hui"], f"八会：{n['hui']}会{name(h['point'])}")
                if n.get("xi") == "yin":
                    for ch in affected:
                        if fw.channels[ch].get("yin") and ch in d["xi"]:
                            self._reason(cands, d["xi"][ch], oid, "xi", WEIGHT["xi"], f"阴经郄穴多用于血证：{fw.channels[ch]['short']}郄穴")
                if n.get("five_shu"):
                    self._five_shu_hint(cands, n["five_shu"], oid, affected, n.get("rule") or "lingshu44", n["name"], notes)
                if n.get("mother_child"):
                    targets = affected
                    if pres.get("states"):  # 肝实脾虚: the Liver's child, the Spleen's mother — not both for both
                        want = "deficiency" if n["mother_child"] == "mother" else "excess"
                        targets = [ch for ch in affected if any(e["channel"] == ch and e["state"] == want for e in pres["states"])]
                    if targets or not pres.get("states"):
                        self._mother_child(cands, n["mother_child"], oid, targets, notes)

    def _host_guest(self, cands: dict[str, dict[str, Any]], ch: str, oid: str, affected: list[str]) -> None:
        """主客原络: when the channel's interior–exterior partner is affected too, the first named is the host (its Yuan
        point), the other the guest (its Luo point)."""
        fw, d = self.fw, self.fw.d
        partner = fw.channels[ch].get("partner")
        if partner not in affected or ch not in affected or affected.index(ch) > affected.index(partner):
            return
        host, guest = d["yuan"][ch], d["luo"][partner]
        text = f"主客原络：先病之经{fw.channels[ch]['short']}（主）取原穴{fw.points[host]['name']}，表里经{fw.channels[partner]['short']}（客）取络穴{fw.points[guest]['name']}"
        for code in (host, guest):
            self._reason(cands, code, oid, "yuan_luo", WEIGHT["yuan"], text, pair=[host, guest])

    def _xi(self, cands: dict[str, dict[str, Any]], ch: str, oid: str, pres: dict[str, Any]) -> None:
        fw, d = self.fw, self.fw.d
        if ch not in d["xi"]:
            return
        pain = bool(set(pres["symptoms"]) & PAIN)
        if pres["acuity"] == "acute" and (not fw.channels[ch].get("yin") or "blood_stasis" in pres["natures"] or pain):
            why = "阳经郄穴多用于急性痛证" if not fw.channels[ch].get("yin") else "阴经郄穴多用于血证与急症"
            self._reason(cands, d["xi"][ch], oid, "xi", WEIGHT["xi"], f"急症取郄：{fw.channels[ch]['short']}郄穴（{why}）")

    def _five_shu_hint(self, cands: dict[str, dict[str, Any]], kind: str, oid: str, affected: list[str], rule: str, what: str,
                       notes: list[str]) -> None:
        fw = self.fw
        label = fw.kind_label.get(kind, kind)
        if not affected:
            notes.append(f"《{'难经' if rule == 'nanjing68' else '灵枢'}》以{what}归之于{label}穴；须先定病经，才知取哪一经之{label}穴——"
                         "此说也不意味着凡有此候皆取该类穴。")
            return
        for ch in affected:
            code = fw.five_shu(ch, kind)
            if code:
                self._reason(cands, code, oid, rule, WEIGHT["five_shu"], f"{'难经·六十八难' if rule == 'nanjing68' else '五输取法'}：{what}→{label}穴，"
                             f"病经{fw.channels[ch]['short']}之{label}穴")

    def _mother_child(self, cands: dict[str, dict[str, Any]], which: str, oid: str, affected: list[str], notes: list[str]) -> None:
        fw = self.fw
        if not affected:
            notes.append("补母泻子须先定病经的五行：未给脏腑或经脉，未取母穴、子穴。")
            return
        for ch in affected:
            m = fw.mother_child(ch)
            if m is None:
                continue
            phase, rel = (m["mother_phase"], "母") if which == "mother" else (m["child_phase"], "子")
            same = m["same"][which]
            cross_ch = m["cross"][f"{which}_channel"]
            cross = m["cross"][which]
            intent = "补" if which == "mother" else "泻"
            self._reason(cands, same, oid, "mother_child", WEIGHT["mother"],
                         f"{'虚者补其母' if which == 'mother' else '实者泻其子'}：{fw.channels[ch]['short']}属{m['phase']}，{phase}为其{rel}，"
                         f"本经{phase}穴{fw.points[same]['name']}", technique=intent, channel=ch)
            if cross and cross_ch:
                self._reason(cands, cross, oid, "mother_child_cross", WEIGHT["cross"],
                             f"他经{intent}{rel}：{rel}经{fw.channels[cross_ch]['short']}（{phase}）之本穴{fw.points[cross]['name']}——"
                             f"是{fw.channels[cross_ch]['short']}自身五行之穴，而不是{fw.channels[cross_ch]['short']}的母穴", technique=intent, channel=ch)

    # ------------------------------------------------------------ the classics: what they say a candidate treats
    def _attest(self, pres: dict[str, Any], cands: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """For every symptom asked about, the points the classics say treat it — in the indications read for each candidate
        across the corpus, and for any point in the acupuncture books — with the works saying so and the earliest.  A
        candidate so attested gains a light reason; a point only the texts propose is listed (the three most attested are
        candidates too, and may serve an objective no rule reached)."""
        fw = self.fw
        rows = []
        for s in pres["symptoms"]:
            sym = fw.symptoms[s]
            forms = [self.b.normalize(f) for f in sym.get("classical") or []]
            if not forms:
                continue
            hits: dict[str, dict[tuple[str, str], dict[str, Any]]] = defaultdict(dict)
            for code in list(cands):
                for ind in self._point_passages(code)["indications"]:
                    hit = next((f for f in forms if f in ind["condition"]), None)
                    if hit:
                        hits[code].setdefault((ind["witness"]["passage_id"], ind["condition"]), {**ind, "matched": hit})
            for code, inds in self._indications_for(forms).items():
                for ind in inds:
                    hits[code].setdefault((ind["witness"]["passage_id"], ind["condition"]), ind)
            ranked = []
            for code, found in hits.items():
                by_work: dict[str, dict[str, Any]] = {}
                for w in sorted(found.values(), key=lambda w: (dated(w["witness"].get("years")), w["witness"]["passage_id"])):
                    by_work.setdefault(w["witness"].get("work") or w["witness"]["book_id"], w)
                first = next(iter(by_work.values()))
                ranked.append({"code": code, "name": fw.points[code]["name"], "works": len(by_work), "earliest": first["witness"],
                               "condition": first["condition"], "form": first["form"], "matched": first["matched"],
                               "candidate": code in cands})
            ranked.sort(key=lambda r: (-r["works"], dated(r["earliest"].get("years")), fw.order[r["code"]]))
            oid = f"symptom:{s}"
            for r in ranked:
                if r["candidate"] or r in ranked[:3]:
                    w = r["earliest"]
                    self._reason(cands, r["code"], oid, "classical_indication", WEIGHT["classical"],
                                 f"古籍主治：{r['works']} 部著作言其主「{r['matched']}」，最早见{w.get('locator', '')}",
                                 witness=w, works=r["works"])
            rows.append({"symptom": s, "name": sym["name"], "forms": sym.get("classical") or [], "points": ranked[:12]})
        return {"findings": rows, "searched": True,
                "note": "据语料中“……某穴主之”“某穴主（治、疗）……”“取（刺、灸）某穴”等语句，其所主之文含所问症状的古籍字面者；"
                        "一部著作计一次；只识别本数据所收之穴名（一名两穴者不计）。是文献所言之主治，不是疗效证据。"}

    def _indications_for(self, forms: list[str]) -> dict[str, list[dict[str, Any]]]:
        """Point → the indications whose condition writes one of ``forms``, from the acupuncture books and from the
        indication sentences elsewhere (…主之 / 主 … / 取 …) that write a form."""
        out: dict[str, list[dict[str, Any]]] = defaultdict(list)
        ids: list[str] = []
        books = self._acupuncture_books()
        for f in forms:
            ids += self.b.find(f, book_ids=books, limit=4000) if books else []
        for p in self.b.passages(dict.fromkeys(ids)):
            for ind in self._parse(p)["indications"]:
                hit = next((f for f in forms if f in ind["condition"]), None)
                if hit:
                    out[ind["code"]].append({**ind, "matched": hit})
        return out

    def _acupuncture_books(self) -> list[str]:
        """The books of the acupuncture category (针灸) — where entries and indications are read whole — and, beside them,
        the works whose acupuncture chapters the corpus carries in other categories are reached through their sentences."""
        if self._acu_books is None:
            self._acu_books = self.b.book_ids(categories=["针灸"])
        return self._acu_books

    # ------------------------------------------------------------ step 3–4: choosing
    def _excluded(self, cands: dict[str, dict[str, Any]], pres: dict[str, Any]) -> dict[str, str]:
        """Candidates left out before choosing: in pregnancy, the points the teaching lists as not to be needled then and
        the points of the lower abdomen and the lumbosacral region."""
        if not pres["pregnant"]:
            return {}
        out = {}
        for code in cands:
            p = self.fw.points[code]
            if "pregnancy" in (p.get("cautions") or []):
                out[code] = "孕期不宜针刺（教材所列）"
            elif p.get("part") in ("lower_abdomen", "sacrum", "lower_back"):
                out[code] = "孕期下腹部、腰骶部腧穴不宜针刺"
        return out

    def _score(self, c: dict[str, Any], principal: str | None) -> float:
        s = float(sum(c["by"].values()))
        if principal and c["by"].get(principal, 0) >= SERVES:
            s += 0.5
        return s

    def _choose(self, objectives: list[dict[str, Any]], cands: dict[str, dict[str, Any]], max_points: int) -> tuple[list[str], set[str]]:
        fw = self.fw
        principal = next((o["id"] for o in objectives if o["principal"]), None)
        key = lambda code: (-self._score(cands[code], principal), -sum(1 for w in cands[code]["by"].values() if w >= SERVES),  # noqa: E731
                            cands[code]["rank"], fw.order[code])
        ranked = sorted(cands, key=key)
        max_points = max(1, int(max_points))
        chosen: list[str] = []
        core: set[str] = set()
        if principal:
            for code in [c for c in ranked if cands[c]["by"].get(principal, 0) >= SERVES][:max(1, min(3, max_points))]:
                chosen.append(code)
                core.add(code)
        for o in objectives:  # a location: a local and a distal point (近远配穴), where both were proposed
            if o["kind"] != "location":
                continue
            for rules in (("local", "anterior_posterior"), ("distal", "four_command", "confluent_pair")):
                if len(chosen) >= max_points or any(any(r["objective"] == o["id"] and r["rule"] in rules for r in cands[c]["reasons"]) for c in chosen):
                    continue
                best = [c for c in ranked if c not in chosen and any(r["objective"] == o["id"] and r["rule"] in rules for r in cands[c]["reasons"])]
                if best:
                    chosen.append(best[0])
        for o in objectives:  # every objective served by one chosen point at least
            if len(chosen) >= max_points:
                break
            if o.get("via") or any(cands[c]["by"].get(o["id"], 0) >= SERVES for c in chosen):
                continue
            # else a lighter reason: a Five-Shu hint, or what the classics say in two works or more
            best = [c for c in ranked if c not in chosen and cands[c]["by"].get(o["id"], 0) >= SERVES] \
                or [c for c in ranked if c not in chosen and any(r["objective"] == o["id"] and (r["rule"] != "classical_indication" or r.get("works", 0) >= 2)
                                                                 for r in cands[c]["reasons"])]
            if best:
                chosen.append(best[0])
        for code in ranked:  # then the points serving most, while they serve something
            if len(chosen) >= max_points:
                break
            if code not in chosen and self._score(cands[code], principal) >= 2 * SERVES:
                chosen.append(code)
        for code in list(chosen):  # a conventional pair is taken whole when one of its points was taken for it
            for r in cands[code]["reasons"]:
                for other in r.get("pair") or []:
                    if other not in chosen and other in cands and len(chosen) < max_points + 1:
                        chosen.append(other)
        return chosen, core

    def _point_out(self, code: str, c: dict[str, Any], core: bool, pres: dict[str, Any], labels: dict[str, str]) -> dict[str, Any]:
        fw = self.fw
        p = fw.points[code]
        reasons = sorted(c["reasons"], key=lambda r: -r["weight"])
        purposes: dict[str, dict[str, Any]] = {}
        for r in reasons:
            purposes.setdefault(r["objective"], {"objective": r["objective"], "label": labels.get(r["objective"], r["objective"]),
                                                 "weight": r["weight"], "reasons": []})["reasons"].append(
                {k: r[k] for k in ("rule", "text", "weight") if k in r} | ({"witness": r["witness"]} if r.get("witness") else {}))
        role = self._role(code, pres)
        intents = list(dict.fromkeys(r["technique"] for r in reasons if r.get("technique")))
        technique = intents[0] if len(intents) == 1 else ("补泻相反" if intents else None)
        classical = next((r for r in reasons if r["rule"] == "classical_indication"), None)
        out = {"code": code, "name": p["name"], "pinyin": p.get("pinyin"), "channel": p["channel"],
               "channel_name": fw.channels[p["channel"]]["name"], "part": p.get("part"), "core": core, "role": role,
               "categories": [{k: v for k, v in cat.items() if k in ("type", "label", "en", "rule")} for cat in fw.categories(code)],
               "purposes": list(purposes.values()), "score": self._score(c, None),
               "technique": ({"intent": technique, "basis": "补母泻子（《难经·六十九难》）"} if len(intents) == 1 else
                             {"intent": technique, "basis": "补母泻子（《难经·六十九难》）",
                              "conflict": "此穴为一经之母（补）又为另一经之子（泻）：意图相反，须先定主次，不能由五行之式自动合并"}) if intents else None,
               "laterality": self._laterality(code, pres), "location": p.get("location"),
               "cautions": [{"id": k, **(fw.d["cautions"].get(k) or {})} for k in p.get("cautions") or []
                            if k != "pregnancy" or pres["pregnant"]],
               "classical": {"works": classical["works"], "earliest": classical["witness"]} if classical else None,
               "classics": self._classics(code)}
        out["record"] = self._record(out)
        return out

    def _classics(self, code: str) -> dict[str, Any]:
        """What the classics' entries and indications give a chosen point: the earliest entry (its stated location), how
        many entries and indications the corpus holds, and whether an entry states an attribute other than the data's."""
        found = self._point_passages(code)
        entry = found["entries"][0] if found["entries"] else None
        works = {i["witness"].get("work") or i["witness"]["book_id"] for i in found["indications"]}
        return {"entry": {"witness": entry["witness"], "location": entry["stated"].get("location")} if entry else None,
                "entries": len(found["entries"]), "indication_works": len(works),
                "differ": [c["label"] for c in self._checks(code, found["entries"]) if c["differ"]]}

    def _role(self, code: str, pres: dict[str, Any]) -> str:
        fw = self.fw
        p = fw.points[code]
        for r in pres["regions"]:
            reg = fw.regions[r]
            if code in reg.get("local") or []:
                return "local"
            if code in (reg.get("back") or []) + (reg.get("front") or []):
                return "local_opposite"
        return "distal" if p.get("part") in LIMBS else "other"

    def _laterality(self, code: str, pres: dict[str, Any]) -> str:
        fw = self.fw
        p = fw.points[code]
        if p["channel"] in MIDLINE:
            return "单穴（正中线）"
        if code == "EX-HN1":
            return "四穴"
        side = pres.get("side")
        if side in ("left", "right"):
            which = "左" if side == "left" else "右"
            if self._role(code, pres) in ("local", "local_opposite"):
                return f"患侧（{which}）"
            return f"患侧（{which}），或取对侧（巨刺、缪刺）——由医者定"
        return "双侧"

    def _record(self, p: dict[str, Any]) -> dict[str, Any]:
        """The chain a teaching or research record keeps (§9): point and attributes → condition → combination rationale →
        implementation → classical source → modern evidence."""
        rules = self.fw.rules
        reasons = [r for pur in p["purposes"] for r in pur["reasons"]]
        sources = list(dict.fromkeys(rules[r["rule"]].get("source", "") for r in reasons if r["rule"] in rules and rules[r["rule"]].get("source")))
        return {"point": f"{p['name']} {p['code']}（{p['channel_name']}" + ("；" + "、".join(c["label"] for c in p["categories"]) if p["categories"] else "") + "）",
                "condition": "；".join(dict.fromkeys(pur["label"] for pur in p["purposes"])),
                "rationale": "；".join(dict.fromkeys(r["text"] for r in reasons)),
                "implementation": f"{p['laterality']}；施术方式、刺激方法、频次与疗程待医者确定",
                "classical_source": "；".join(sources[:3]) + (f"；本语料最早见证：{p['classical']['earliest'].get('locator', '')}" if p.get("classical") else ""),
                "modern_evidence": None}

    def _alternatives(self, cands: dict[str, dict[str, Any]], chosen: list[str]) -> list[dict[str, Any]]:
        fw = self.fw
        rest = sorted((c for c in cands if c not in chosen), key=lambda c: (-self._score(cands[c], None), fw.order[c]))
        return [{"code": c, "name": fw.points[c]["name"], "score": self._score(cands[c], None),
                 "reasons": list(dict.fromkeys(r["text"] for r in sorted(cands[c]["reasons"], key=lambda r: -r["weight"])))[:3]}
                for c in rest[:12]]

    def _ashi(self, pres: dict[str, Any]) -> dict[str, Any] | None:
        regs = [r for r in pres["regions"] if r in MUSCULOSKELETAL]
        if not regs and not set(pres["symptoms"]) & PAIN:
            return None
        where = "、".join(self.fw.regions[r]["name"] for r in regs) or "病痛处"
        return {"where": where, "rule": "ashi", "text": f"阿是穴：于{where}按压，以压痛或局部反应处为穴（以痛为输），不计入定穴之数。"}

    # ------------------------------------------------------------ step 5: combinations, technique, record, cautions
    def _combinations(self, chosen: list[str], cands: dict[str, dict[str, Any]], pres: dict[str, Any]) -> list[dict[str, Any]]:
        fw, d = self.fw, self.fw.d
        P = fw.points
        nm = lambda codes: "、".join(P[c]["name"] for c in codes)  # noqa: E731
        out: list[dict[str, Any]] = []

        def add(method: str, codes: list[str], text: str, **extra: Any) -> None:
            rule = fw.rules.get(method) or {}
            out.append({"method": method, "name": extra.pop("name", rule.get("name", method)), "en": extra.pop("en", rule.get("en", method)),
                        "rule": method, "points": list(dict.fromkeys(codes)), "text": text, **extra})

        roles = {c: self._role(c, pres) for c in chosen}
        local = [c for c in chosen if roles[c] in ("local", "local_opposite")]
        distal = [c for c in chosen if roles[c] == "distal"]
        if local and distal:
            add("local_distal", local + distal, f"近部{nm(local)}配远部{nm(distal)}")
        up = [c for c in chosen if P[c].get("part") in UPPER]
        down = [c for c in chosen if P[c].get("part") in LOWER]
        if up and down:
            add("upper_lower", up + down, f"上部{nm(up)}配下部{nm(down)}")
        front = [c for c in chosen if P[c].get("part") in ANTERIOR]
        back = [c for c in chosen if P[c].get("part") in POSTERIOR]
        if front and back:
            add("anterior_posterior", front + back, f"胸腹{nm(front)}配背部{nm(back)}")
        paired = [c for c in chosen if P[c]["channel"] not in MIDLINE and c != "EX-HN1"]
        if paired:
            side = pres.get("side")
            add("left_right", paired, f"{nm(paired)}左右两侧同取" if side not in ("left", "right")
                else f"{nm(paired)}取患侧；远部之穴亦可取对侧（巨刺、缪刺），由医者按病情定")
        by_ch: dict[str, list[str]] = defaultdict(list)
        for c in chosen:
            by_ch[P[c]["channel"]].append(c)
        for ch, codes in by_ch.items():
            if len(codes) > 1 and ch != "EX":
                add("same_channel", codes, f"{nm(codes)}同属{fw.channels[ch]['name']}")
        done: set[frozenset[str]] = set()
        for a in chosen:
            for b in chosen:
                ca, cb = P[a]["channel"], P[b]["channel"]
                if a >= b or ca not in fw.channels or cb not in fw.channels or ca == cb:
                    continue
                pair = frozenset((ca, cb))
                if pair in done:
                    continue
                if fw.channels[ca].get("partner") == cb:
                    done.add(pair)
                    add("interior_exterior", by_ch[ca] + by_ch[cb], f"{fw.channels[ca]['short']}与{fw.channels[cb]['short']}互为表里："
                        f"{nm(by_ch[ca])}配{nm(by_ch[cb])}")
                elif fw.channels[ca].get("same_name") == cb:
                    done.add(pair)
                    add("same_name", by_ch[ca] + by_ch[cb], f"手足{fw.channels[ca]['six']}：{nm(by_ch[ca])}配{nm(by_ch[cb])}")
        for a in chosen:
            for b in chosen:
                if a == b:
                    continue
                ya = next((cat["channel"] for cat in fw.categories(a) if cat["type"] == "yuan"), None)
                lb = next((cat["channel"] for cat in fw.categories(b) if cat["type"] == "luo" and cat.get("channel")), None)
                if ya and lb and fw.channels[ya].get("partner") == lb:
                    add("yuan_luo", [a, b], f"主客原络：先病之经{fw.channels[ya]['short']}取原穴{P[a]['name']}，表里经{fw.channels[lb]['short']}取络穴{P[b]['name']}")
                elif ya and lb and ya == lb:
                    add("yuan_luo", [a, b], f"{P[a]['name']}、{P[b]['name']}是{fw.channels[ya]['short']}本经的原穴与络穴——与“先病之经取原、表里经取络”的主客结构不同",
                        classical=False, name="本经原穴配络穴（非主客原络）", en="Yuan and Luo points of one channel (not the host–guest structure)")
        for organ, shu in d["back_shu"].items():
            mu = d["front_mu"][organ]
            ch = fw.organs[organ]["channel"]
            if shu in chosen and mu in chosen:
                add("shu_mu", [shu, mu], f"{organ}之背俞{P[shu]['name']}配募穴{P[mu]['name']}")
            if shu in chosen and d["yuan"][ch] in chosen:
                add("shu_yuan", [shu, d["yuan"][ch]], f"{organ}之背俞{P[shu]['name']}配{fw.channels[ch]['short']}原穴{P[d['yuan'][ch]]['name']}")
        for organ, he in d["lower_he"].items():
            mu = d["front_mu"][organ]
            if he in chosen and mu in chosen:
                note = f"；二穴同在{fw.channels[P[he]['channel']]['short']}，而合为{organ}之合募配穴" if P[he]["channel"] == P[mu]["channel"] else ""
                add("lowerhe_mu", [he, mu], f"{organ}之下合穴{P[he]['name']}配募穴{P[mu]['name']}{note}")
        xis = [c for c in chosen if fw.has(c, "xi")]
        huis = [(c, cat["of"]) for c in chosen for cat in fw.categories(c) if cat["type"] == "hui"]
        for x in xis:
            for h, of in huis:
                if h != x:
                    add("xi_hui", [x, h], f"郄穴{P[x]['name']}配{of}会{P[h]['name']}")
        for pair in d["confluent"]["pairs"]:
            if all(c in chosen for c in pair["points"]):
                add("confluent_pair", pair["points"], f"{nm(pair['points'])}（{'、'.join(d['confluent']['points'][c] for c in pair['points'])}）"
                    f"主{pair['emphasis']}")
        for e in d.get("empirical_pairs") or []:
            if all(c in chosen for c in e["points"]):
                add(e["rule"], e["points"], f"{e['name']}：{e['note']}", classical=False)
        for c in chosen:
            for r in (cands.get(c) or {}).get("reasons", []):
                if r["rule"] == "mother_child_cross":
                    add("mother_child_cross", [c], r["text"])
        return out

    def _mc_out(self, pres: dict[str, Any]) -> list[dict[str, Any]]:
        fw = self.fw
        which = [fw.natures[n]["mother_child"] for n in pres["natures"] if fw.natures[n].get("mother_child")]
        out = []
        for ch in self._affected_channels(pres):
            m = fw.mother_child(ch)
            if m is None:
                continue
            mine = ["mother" if e["state"] == "deficiency" else "child" for e in pres.get("states") or [] if e["channel"] == ch]
            row = {**m, "name": fw.channels[ch]["name"], "applies": mine if pres.get("states") else which}
            row["text"] = (f"{fw.channels[ch]['short']}属{m['phase']}：虚则补母（{m['mother_phase']}）——本经{fw.points[m['same']['mother']]['name']}，"
                           f"他经{fw.channels[m['cross']['mother_channel']]['short']}之{fw.points[m['cross']['mother']]['name']}；"
                           f"实则泻子（{m['child_phase']}）——本经{fw.points[m['same']['child']]['name']}，"
                           f"他经{fw.channels[m['cross']['child_channel']]['short']}之{fw.points[m['cross']['child']]['name']}；"
                           f"本穴{fw.points[m['own']]['name']}")
            out.append(row)
        return out

    def _technique(self, pres: dict[str, Any]) -> list[dict[str, Any]]:
        fw = self.fw
        out = []
        for n in pres["natures"]:
            nat = fw.natures[n]
            if nat.get("principle") or nat.get("technique"):
                out.append({"nature": nat["name"], "principle": nat.get("principle"), "technique": nat.get("technique"),
                            "rule": nat.get("rule")})
        out.append({"nature": None, "principle": None, "rule": "mother_child",
                    "technique": "选穴与补泻相关而各自为一事：穴的类别不决定手法（原穴不当只视为补穴）；施术的方式与刺激量由医者据诊察而定。"})
        return out

    def _implementation(self, chosen: list[str], pres: dict[str, Any]) -> dict[str, Any]:
        fw = self.fw
        outcomes = [fw.symptoms[s]["name"] for s in pres["symptoms"]] + [f"{fw.regions[r]['name']}的疼痛与活动" for r in pres["regions"]
                                                                       if r in MUSCULOSKELETAL]
        return {"points": [{"code": c, "name": fw.points[c]["name"], "laterality": self._laterality(c, pres)} for c in chosen],
                "modality": None, "stimulation": None, "frequency": None, "course": None,
                "outcomes": list(dict.fromkeys(outcomes)) + ["耐受与不良反应"],
                "note": "施术方式（针刺、艾灸、按压……）、刺激方法、治疗频次与疗程须由执业人员据诊察确定后记入；"
                        "据症状与功能的变化、耐受与不良反应再评估、调整（见规则“处方记录”）。"}

    def _cautions(self, chosen: list[str], pres: dict[str, Any]) -> list[dict[str, Any]]:
        fw = self.fw
        by: dict[str, list[str]] = defaultdict(list)
        for c in chosen:
            for k in fw.points[c].get("cautions") or []:
                by[k].append(c)
        out = []
        for k, codes in by.items():
            if k == "pregnancy" and not pres["pregnant"]:
                text = fw.d["cautions"][k]["text"] + "（若为孕妇须避开或慎用。）"
            else:
                text = fw.d["cautions"][k]["text"]
            out.append({"kind": k, "name": fw.d["cautions"][k]["name"], "points": codes, "text": text,
                        "severity": "high" if (k == "pregnancy" and pres["pregnant"]) or k in ("thorax", "nape", "eye", "throat") else "note"})
        if pres["pregnant"]:
            ab = [c for c in chosen if fw.points[c].get("part") in ("lower_abdomen", "abdomen", "sacrum", "lower_back") and c not in by.get("pregnancy", [])]
            if ab:
                out.append({"kind": "pregnancy", "name": "孕期", "points": ab, "severity": "high",
                            "text": "下腹部、腰骶部腧穴，孕期不宜针刺（教材所列）。"})
        for c in chosen:
            for pro in self.prohibitions(c)[:1]:
                out.append({"kind": "classical", "name": "古籍禁忌", "points": [c], "severity": "note",
                            "text": f"{fw.points[c]['name']}：{pro['text']}", "witness": pro["witness"]})
        out += [{"kind": "general", "name": "通则", "points": [], "severity": "note", "text": t} for t in fw.d.get("general_cautions") or []]
        return out

    def _channels_read(self, pres: dict[str, Any], objectives: list[dict[str, Any]]) -> list[dict[str, Any]]:
        fw = self.fw
        why: dict[str, list[dict[str, str]]] = defaultdict(list)
        for o in pres["organs"]:
            why[fw.organs[o]["channel"]].append({"rule": "pattern", "text": f"{o}之经" + ("（推断）" if o in pres["inferred"]["organs"] else "")})
        for c in pres["channels"]:
            why[c].append({"rule": "channel_course", "text": "所给之经"})
        for r in pres["regions"]:
            reg = fw.regions[r]
            for c in reg.get("channels") or []:
                why[c].append({"rule": reg.get("rule") or "channel_course", "text": f"{reg['name']}" + ("（头痛分经）" if reg.get("rule") == "headache_channels" else "所过之经")})
        for s in pres["symptoms"]:
            for c in fw.symptoms[s].get("channels") or []:
                why[c].append({"rule": "symptom", "text": f"{fw.symptoms[s]['name']}相关之经"})
        rows = [{"channel": c, "name": fw.channels[c]["name"], "because": v, "weight": len(v)} for c, v in why.items()]
        rows.sort(key=lambda r: (-r["weight"], list(fw.channels).index(r["channel"])))
        return rows

    def _evidence(self, chosen: list[str], pres: dict[str, Any]) -> dict[str, Any]:
        fw = self.fw
        recs = []
        for key, m in (fw.d.get("modern") or {}).items():
            ap = m.get("applies")
            bears: list[str] = []
            if ap == "all":
                bears = ["本处方的选穴方式"]
            elif isinstance(ap, dict):
                bears += [fw.points[c]["name"] for c in ap.get("points") or [] if c in chosen]
                bears += [fw.symptoms[s]["name"] for s in ap.get("symptoms") or [] if s in pres["symptoms"]]
                bears += [fw.regions[r]["name"] for r in ap.get("regions") or [] if r in pres["regions"]]
                if ap.get("points") and not any(c in chosen for c in ap["points"]):
                    bears = []
                if ap.get("points") and ap.get("symptoms") and not any(s in pres["symptoms"] for s in ap["symptoms"]):
                    bears = []
            if bears:
                recs.append({"id": key, **{k: m.get(k) for k in ("citation", "pmid", "doi", "design", "population", "size", "finding", "limits")},
                             "bears_on": list(dict.fromkeys(bears)),
                             "scope": "points" if isinstance(ap, dict) and ap.get("points") else "broad"})
        return {"levels": fw.d.get("evidence_levels") or [], "modern": recs,
                "note": "经典与教材的理论说明“为什么这样取”，标准说明“怎样一致地施行”，临床研究说明“对一定人群是否有益”；"
                        "一种配穴是否优于另一种，须有专门设计的比较研究。可用现代证据工具（modern.search）检索并按设计分级。"}

    def _steps(self, out: dict[str, Any]) -> list[dict[str, str]]:
        pres, labels = out["presentation"], out["presentation"]["labels"]
        core = "、".join(f"{p['name']}（{p['code']}）" for p in out["prescription"]["core"])
        supp = "、".join(f"{p['name']}（{p['code']}）" for p in out["prescription"]["supplementary"])
        chans = "、".join(c["name"] for c in out["channels"][:4])
        inferred = [x for x in pres["inferred"]["regions"]] + pres["inferred"]["organs"]
        steps = [
            {"step": "1", "title": "明确病位与病性", "text": "；".join(x for x in (
                f"病位：{'、'.join(labels['regions'])}" if labels["regions"] else "",
                f"症状：{'、'.join(labels['symptoms'])}" if labels["symptoms"] else "",
                f"脏腑：{'、'.join(labels['organs'])}" if labels["organs"] else "",
                f"经脉：{'、'.join(labels['channels'])}" if labels["channels"] else "",
                f"病性：{'、'.join(labels['natures'])}" if labels["natures"] else "",
                {"acute": "急性", "chronic": "慢性"}.get(pres["acuity"] or "", "")) if x)
             + ("（推断者须以辨证确认）" if inferred else "") + "。诊断与适宜性评估须先行。"},
            {"step": "2", "title": "确定选经", "text": f"相关之经：{chans or '未能确定'}。"},
            {"step": "3", "title": "选定主穴", "text": f"主穴：{core or '无'}。"},
            {"step": "4", "title": "说明每一配穴的用意", "text": (f"配穴：{supp}；" if supp else "") + "每穴所主之病位、症状或病机见其“用意”。"},
            {"step": "5", "title": "记录施术条件并再评估", "text": "左右、施术方式、刺激方法、频次与疗程待医者确定；按症状与功能、耐受与不良反应调整。"},
        ]
        return steps

    # ------------------------------------------------------------ rules and their witnesses
    def _rule_card(self, rid: str) -> dict[str, Any]:
        r = self.fw.rules[rid]
        card = {"id": rid, **{k: r.get(k) for k in ("name", "en", "kind", "level", "statement", "source")}}
        if r.get("probes"):
            card["witnesses"] = self.rule_witnesses(rid)
        return card

    def rule_witnesses(self, rid: str) -> list[dict[str, Any]]:
        """Each probe of a rule found in the corpus as written: the works writing it, the earliest witness, the periods."""
        if rid in self._rules_seen:
            return self._rules_seen[rid]["rows"]
        rows = []
        for probe in self.fw.rules[rid].get("probes") or []:
            text, reading = (probe["text"], probe.get("reading")) if isinstance(probe, dict) else (probe, None)
            ws = []
            for p in self.b.passages(dict.fromkeys(self.b.find(text, limit=400))):
                norm = self.b.normalize(p.text)
                at = norm.find(self.b.normalize(text))
                if at < 0:
                    compact, idx = self._compact(p.text)
                    k = compact.find(self.b.normalize(text))
                    at = idx[k] if k >= 0 else 0
                ws.append(self.b.witness(p, start=at, end=min(len(p.text), at + max(len(text), 24)), width=12))
            by_work: dict[str, dict[str, Any]] = {}
            for w in sorted(ws, key=lambda w: (dated(w.get("years")), w["passage_id"])):
                by_work.setdefault(w.get("work") or w["book_id"], w)
            first = min(by_work.values(), key=lambda w: (dated(w.get("years")), w["passage_id"])) if by_work else None
            rows.append({"probe": text, **({"reading": reading} if reading else {}), "works": len(by_work), "earliest": first,
                         "periods": dict(Counter(w.get("period") or "未定" for w in by_work.values()))})
        self._rules_seen[rid] = {"rows": rows}
        return rows

    # ============================================================ the Five Phases in point selection
    def wuxing(self, text: str | None = None, *, states: Iterable[str] = (), symptoms: Iterable[str] = (),
               methods: Iterable[str] = (), pregnant: bool = False, classical: bool = True) -> dict[str, Any]:
        """五行选穴: Five-Phase relations read into point selection, through the two decisions between them — the pattern
        (a phase's state does not name it) and the method of selection (each with its level: classical, school,
        deduction).  States (肝实 土虚 金虚, 肝郁脾虚, Wood excess …) become: the patterns still to tell apart; the
        pathological relations among them (mother–child, overacting and counteracting, each in its two readings) with the
        Nanjing 50 name of what the receiving organ suffers; the classical statements that apply (Nanjing 75 for East
        excess with West deficiency, the Jin Gui's condition on strengthening the Spleen, Nanjing 79 for the Heart); the
        named strategies whose premise the states fit (or would, with one more); for every state the points each method
        takes, with their phase, the relation of that phase to their channel and the intention — and the points two
        methods would treat oppositely; the conclusions that do not follow; each as the record of six elements."""
        fw = self.fw
        wx = fw.wx
        states, symptoms, methods = list(states or []), list(symptoms or []), list(methods or [])
        unknown_methods = [m for m in methods if m not in wx.get("methods", {})]
        if unknown_methods:
            raise ValueError("study.wuxing: unknown methods " + ", ".join(unknown_methods) + "; choose " + ", ".join(wx.get("methods", {})))
        if not any(str(x).strip() for x in [text or "", *states, *symptoms]):
            raise ValueError("study.wuxing: give symptoms or Five-Phase states (食欲差、便溏、乏力; 肝虚; 木实 土虚)")
        given = [text or ""] + [re.sub(r"[:=：＝]", " ", str(s)) for s in states or []]
        symptom_text = "；".join([*given, *symptoms])
        assessment = assess_symptoms(symptom_text, self.b.data("wuxing-symptoms.yaml"), self.b.normalize)
        pregnant = pregnant or any(f["id"] == "pregnancy" and f["status"] in ("present", "uncertain") for f in assessment["findings"])
        read = [fw.phase_states(t) for t in given if t]
        entries: list[dict[str, Any]] = []
        for r in read:
            for e in r["states"]:
                if not any(x["phase"] == e["phase"] and x["organ"] == e["organ"] and x["state"] == e["state"] for x in entries):
                    entries.append(e)
        notes = [n for r in read for n in r["notes"]]
        wanted = methods or list(wx.get("methods") or {})
        state_conflicts = [o for o in dict.fromkeys(e["organ"] for e in entries)
                          if len({e["state"] for e in entries if e["organ"] == o and e["state"] in (*STATES, "neutral")}) > 1]
        blocked = bool(assessment["alerts"] or pregnant or state_conflicts or assessment["contradictory_findings"])
        for e in entries:
            e["channel_name"] = fw.channels[e["channel"]]["name"]
            e["state_name"] = ((wx.get("states") or {}).get(e["state"]) or {}).get("name", "虚实未定")
            e["phase_en"] = (wx["phases"][e["phase"]] or {}).get("en")
        active = [] if blocked else entries
        records = [r for e in active for r in self._wx_methods(e, wanted)]
        relations = self._wx_relations(entries)
        strategies = self._wx_strategies(active)
        used_methods = sorted({r["method"] for r in records})
        guards = self._wx_guards(entries, used_methods, " ".join(given))
        conflicts = self._wx_conflicts(records)
        classical_rows = self._wx_classical(active)
        rules = ["five_phase", "five_phase_cycles", "five_pathogens", "mother_child"] + [r["rule"] for r in records] \
            + [c["rule"] for c in classical_rows] + [s["rule"] for s in strategies if s["fit"] == "full"] + ["wuxing_record"]
        rules = [r for r in dict.fromkeys(rules) if r in fw.rules]
        out: dict[str, Any] = {
            "input": {"text": text or "", "states": states, "symptoms": symptoms, "pregnant": pregnant,
                      "read": [s for r in read for s in r["spans"]], "notes": notes},
            "input_mode": "states" if entries else "symptoms",
            "status": "given_states" if entries else assessment["status"],
            "state_conflicts": state_conflicts,
            "states": [{k: e.get(k) for k in ("phase", "phase_en", "organ", "channel", "channel_name", "state", "state_name", "written",
                                              "pattern", "note")} for e in entries],
            "clarify": self._wx_clarify(entries),
            "relations": relations,
            "pathogens": self._wx_pathogens(entries),
            "classical": classical_rows,
            "strategies": strategies,
            "methods": records,
            "conflicts": conflicts,
            "branches": self._wx_branches(active, strategies),
            "guards": guards,
            "rules": [self._rule_card(r) if classical else {"id": r, **{k: fw.rules[r].get(k) for k in ("name", "en", "kind", "level", "statement", "source")}}
                      for r in rules],
            "evidence": self._wx_evidence(used_methods),
            "levels": [{"level": k, "name": v} for k, v in LEVELS.items()],
            "terms": wx.get("terms") or [],
            "notice": self.notice,
        }
        out["steps"] = self._wx_steps(out)
        out["summary"] = {"states": len(entries), "relations": len(relations), "strategies": sum(1 for s in strategies if s["fit"] == "full"),
                          "methods": len(records), "conflicts": len(conflicts), "guards": len(guards)}
        if not entries or blocked:
            if assessment["alerts"]:
                assessment["status"] = "urgent"
            elif pregnant:
                assessment["status"] = "pregnancy_review"
                assessment["questions"] = ["目前孕几周，症状持续多久？"]
                assessment["note"] = "孕期需先评估针灸适宜性；当前仅保留症状线索，暂停候选取穴及补泻推演。"
            elif state_conflicts:
                assessment["status"] = "needs_clarification"
                assessment["questions"] = ["请明确" + "、".join(state_conflicts) + "当前的虚实，或区分不同证候层次？"]
            if not blocked:
                for candidate in assessment["candidates"]:
                    if candidate["status"] != "conditional":
                        continue
                    # An inference is kept inside its hypothesis, never promoted to top-level states.
                    result = self.wuxing(candidate["pattern"], methods=methods or ["nanjing69"], classical=classical)
                    candidate["selection"] = {k: result[k] for k in ("states", "relations", "methods", "conflicts", "rules", "evidence")}
                    for record in candidate["selection"]["methods"]:
                        record["premise"] = "若经辨证确认" + candidate["pattern"] + "；由症状提出的候选，尚未确诊"
                    candidate["selection"]["conditional"] = True
            else:
                for candidate in assessment["candidates"]:
                    candidate["status"] = "withheld"
            out["assessment"] = assessment
            out["status"] = assessment["status"]
            out["summary"]["candidates"] = len(assessment["candidates"])
            out["summary"]["conditional_candidates"] = sum(c["selection"] is not None for c in assessment["candidates"])
        return out

    def _wx_point(self, code: str, intent: str | None) -> dict[str, Any]:
        fw = self.fw
        p = fw.points[code]
        ch = p["channel"]
        out: dict[str, Any] = {"code": code, "name": p["name"], "channel": ch, "channel_short": fw.channels[ch]["short"], "intent": intent}
        out["cautions"] = [fw.d["cautions"][key]["text"] for key in p.get("cautions", [])]
        cat = next((c for c in fw.categories(code) if c["type"] == "five_shu"), None)
        if cat:
            out |= {"label": fw.kind_label[cat["kind"]], "en": fw.kind_en[cat["kind"]], "phase": cat["phase"],
                    "relation": fw.relation_text(cat["phase"], fw.channels[ch]["phase"]), "yuan": fw.has(code, "yuan")}
        return out

    def _wx_premise(self, e: dict[str, Any]) -> str:
        if e.get("pattern"):
            return f"{e['pattern']}（所给之证）" + (f"；{e['note']}" if e.get("note") else "")
        cands = self._wx_pattern_options(e)
        return f"{e['organ']}{e.get('state_name', '')}——证候待辨" + (f"（{'、'.join(cands)}……）" if cands else "")

    def _wx_record(self, method: str, e: dict[str, Any], points: list[dict[str, Any]], relationship: str, selection: str,
                   intent: str | None) -> dict[str, Any]:
        fw = self.fw
        m = (fw.wx.get("methods") or {})[method]
        rule = fw.rules.get(m["rule"]) or {}
        chans = list(dict.fromkeys([e["channel"]] + [p["channel"] for p in points]))
        return {"method": method, "name": m["name"], "en": m["en"], "level": m["level"], "level_name": LEVELS.get(m["level"], m["level"]),
                "rule": m["rule"], "organ": e["organ"], "phase": e["phase"], "state": e["state"], "premise": self._wx_premise(e),
                "channels": [fw.channels[c]["name"] for c in chans], "relationship": relationship, "selection": selection,
                "points": points, "intent": intent, "source": rule.get("source"), **({"note": m["note"]} if m.get("note") else {})}

    def _wx_methods(self, e: dict[str, Any], wanted: list[str]) -> list[dict[str, Any]]:
        """Every method's points for one state (an organ, its phase, excess or deficiency)."""
        fw = self.fw
        ch, own, organ, state = e["channel"], e["phase"], e["organ"], e["state"]
        c = fw.channels[ch]
        short = c["short"]
        nm = lambda code: f"{fw.points[code]['name']}（{fw.kind_label.get(next((x['kind'] for x in fw.categories(code) if x['type'] == 'five_shu'), ''), '')}，{fw.shu_phase(code)}）"  # noqa: E731
        out: list[dict[str, Any]] = []
        if state == "neutral":
            code = fw.phase_point(ch, own)
            if "own_channel" in wanted and code:
                out.append(self._wx_record("own_channel", e, [self._wx_point(code, None)], f"{organ}属{own}；明确不实不虚",
                                           f"不实不虚，以经取之：取本经；后世读作取本经同气之穴{nm(code)}——补泻据所辨之证", None))
            return out
        if state not in STATES:  # unknown is not the positive finding "neither excess nor deficiency"
            return out
        mother = state == "deficiency"
        target = MOTHER[own] if mother else GENERATES[own]
        intent = "补" if mother else "泻"
        rel = f"{organ}属{own}，{target}生{own}：{target}为{own}之母" if mother else f"{organ}属{own}，{own}生{target}：{target}为{own}之子"
        if "nanjing69" in wanted:
            code = fw.phase_point(ch, target)
            out.append(self._wx_record("nanjing69", e, [self._wx_point(code, intent)], rel,
                                       f"{'虚者补其母' if mother else '实者泻其子'}：取本经{target}穴{nm(code)}", intent))
        if "nanjing69_cross" in wanted:
            other = fw.phase_channel(target, bool(c.get("yin")))
            code = fw.phase_point(other, target)
            os_ = fw.channels[other]["short"]
            out.append(self._wx_record("nanjing69_cross", e, [self._wx_point(code, intent)], rel + f"；{os_}属{target}",
                                       f"{'虚补母经' if mother else '实泻子经'}之同气之穴：{os_}的{target}穴{nm(code)}——是{os_}自身五行之穴，"
                                       f"不是{os_}的母穴或子穴", intent))
        if "nanjing79" in wanted and organ == "心":
            code = fw.phase_point("PC", target)
            out.append(self._wx_record("nanjing79", e, [self._wx_point(code, intent)], rel + "；《难经》心病取手心主之经",
                                       f"{'补手心主井' if mother else '泻手心主俞'}：{nm(code)}，{'随而济之' if mother else '迎而夺之'}", intent))
        if "saam" in wanted:
            s = fw.saam(ch)
            t = s[state]
            tmpl = (fw.wx["methods"]["saam"].get("templates") or {}).get(state) or {}
            ton, sed = t["tonify"], t["sedate"]
            pts = [self._wx_point(x, "补") for x in ton["points"]] + [self._wx_point(x, "泻") for x in sed["points"]]
            relt = (f"{own}虚：{ton['phase']}生{own}（母）；{sed['phase']}克{own}（所不胜）" if mother
                    else f"{own}实：{ton['phase']}克{own}（所不胜）；{own}生{sed['phase']}（子）")
            out.append(self._wx_record("saam", e, pts, relt,
                                       f"{tmpl.get('name', '')}：补{ton['phase']}——{nm(ton['points'][0])}、{fw.channels[ton['channels'][1]]['short']}{nm(ton['points'][1])}；"
                                       f"泻{sed['phase']}——{nm(sed['points'][0])}、{fw.channels[sed['channels'][1]]['short']}{nm(sed['points'][1])}", "补泻相合"))
        pr = fw.paired(ch) or {}
        for via in ("interior_exterior", "same_name"):
            if via not in wanted or via not in pr:
                continue
            other = pr[via]["channel"]
            code = pr[via]["mother" if mother else "child"]
            os_ = fw.channels[other]["short"]
            link = f"{short}与{os_}互为表里" if via == "interior_exterior" else f"{short}与{os_}为手足{c.get('six', '')}同名"
            out.append(self._wx_record(via, e, [self._wx_point(code, intent)], f"{link}；{rel}",
                                       f"先因{'表里' if via == 'interior_exterior' else '同名'}及于{os_}，再取其{target}穴{nm(code)}"
                                       f"——{os_}不是{short}的{'母' if mother else '子'}经，两步都须写明", intent))
        return out

    def _wx_relations(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The pathological relations among the states, each pair once, with the readings it allows."""
        fw = self.fw
        path = fw.wx.get("pathology") or {}
        out: list[dict[str, Any]] = []
        lab = lambda e: f"{e['phase']}（{e['organ']}）{e.get('state_name', '')}"  # noqa: E731

        def reading(rid: str, src: dict[str, Any], dst: dict[str, Any]) -> dict[str, Any]:
            p = path[rid]
            return {"id": rid, "name": p["name"], "en": p["en"], "from": src["organ"], "to": dst["organ"], "meaning": p["meaning"],
                    "example": p.get("example"), "implication": p.get("implication"), "pathogen": self._wx_pathogen(src["phase"], dst)}

        for i, a in enumerate(entries):
            for b in entries[i + 1:]:
                if a["phase"] == b["phase"]:
                    continue
                for x, y in ((a, b), (b, a)):
                    X, Y, sx, sy = x["phase"], y["phase"], x["state"], y["state"]
                    rows: list[dict[str, Any]] = []
                    kind = None
                    if GENERATES[X] == Y:  # x is the mother of y
                        kind = "mother_child"
                        if sx == "deficiency" and sy == "deficiency":
                            rows = [reading("mother_to_child", x, y), reading("child_to_mother", y, x)]
                        elif sx == "deficiency" and sy == "excess":
                            rows = [reading("mother_to_child", x, y)]
                        elif sx == "excess" and sy == "excess":
                            rows = [reading("mother_to_child", x, y), reading("child_to_mother", y, x)]
                    elif CONTROLS[X] == Y:  # x controls y
                        if sx == "excess" and sy == "deficiency":
                            kind, rows = "overacting", [reading("overacting_excess", x, y), reading("overacting_deficiency", x, y)]
                        elif sx == "excess" and sy == "any":
                            kind, rows = "overacting", [reading("overacting_excess", x, y)]
                        elif sx == "any" and sy == "deficiency":
                            kind, rows = "overacting", [reading("overacting_deficiency", x, y)]
                        elif sy == "excess" and sx == "deficiency":
                            kind, rows = "counteracting", [reading("counteracting_excess", y, x), reading("counteracting_deficiency", y, x)]
                        elif sy == "excess" and sx == "any":
                            kind, rows = "counteracting", [reading("counteracting_excess", y, x)]
                        elif sy == "any" and sx == "deficiency":
                            kind, rows = "counteracting", [reading("counteracting_deficiency", y, x)]
                    if rows:
                        cycle = f"{X}生{Y}" if kind == "mother_child" else f"{X}克{Y}"
                        out.append({"kind": kind, "between": [lab(x), lab(y)], "cycle": cycle, "readings": rows,
                                    "text": f"{lab(x)}、{lab(y)}：{cycle}——" + "，或".join(r["name"] for r in rows)
                                            + ("（何者在先，所给不足以定）" if len(rows) > 1 else "")})
        return out

    def _wx_pathogen(self, source: str, dst: dict[str, Any]) -> dict[str, Any]:
        """What the receiving organ suffers from a phase, by Nanjing 50 (from where it comes, not a deficiency or an excess)."""
        fw = self.fw
        rel = fw.relation(source, dst["phase"])
        key = {"mother": "deficiency", "child": "excess", "controller": "thieving", "controlled": "slight", "same": "direct"}[rel]
        p = (fw.wx.get("pathogens") or {})[key]
        return {"name": p["name"], "en": p["en"], "organ": dst["organ"], "statement": p["statement"],
                "text": f"于{dst['organ']}为{p['name']}（{p['statement']}）——言邪之所从来，不是{dst['organ']}的虚证或实证"}

    def _wx_pathogens(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """For every organ named, the five sources of Nanjing 50 relative to it."""
        fw = self.fw
        out = []
        for organ in dict.fromkeys(e["organ"] for e in entries):
            phase = fw.channels[fw.organs[organ]["channel"]]["phase"]
            rows = []
            for key, p in (fw.wx.get("pathogens") or {}).items():
                src = {"mother": MOTHER[phase], "child": GENERATES[phase], "controller": CONTROLLED_BY[phase],
                       "controlled": CONTROLS[phase], "same": phase}[p["from"]]
                rows.append({"name": p["name"], "en": p["en"], "from_phase": src, "from_organ": fw.phase_organ(src) if src != phase else organ,
                             "statement": p["statement"]})
            out.append({"organ": organ, "phase": phase, "rows": rows})
        return out

    def _wx_clarify(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        pats = self.fw.wx.get("patterns") or {}
        out = []
        for e in entries:
            p = pats.get(e["phase"]) or {}
            out.append({"phase": e["phase"], "organ": e["organ"], "state": e["state"], "given": e.get("pattern"),
                        "candidates": [] if e.get("pattern") else self._wx_pattern_options(e),
                        "note": ("虚实尚未确定，不能据此套用“不实不虚”之法。" if e["state"] == "any" else p.get("note"))
                        if self.fw.organs[e["organ"]]["kind"] == "zang" else f"须辨明{e['organ']}本身的证候，不以同五行的脏替代。"})
        return out

    def _wx_pattern_options(self, e: dict[str, Any]) -> list[str]:
        # The existing phase tables describe the representative zang, not every organ of that phase.
        if e["state"] == "neutral" or e["organ"] != self.fw.wx["phases"][e["phase"]]["zang"]:
            return []
        p = (self.fw.wx.get("patterns") or {}).get(e["phase"]) or {}
        return list(p.get(e["state"]) or (p.get("excess", []) + p.get("deficiency", [])))

    def _wx_classical(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The classical statements the states bear on, and whether their condition is met."""
        fw = self.fw
        out = []
        st = lambda organ: [e["state"] for e in entries if e["organ"] == organ]  # noqa: E731
        if "excess" in st("肝") and "deficiency" in st("肺"):
            out.append({"rule": "nanjing75", "name": fw.rules["nanjing75"]["name"], "status": "applies",
                        "text": "东方（木、肝）实而西方（金、肺）虚：《难经·七十五难》泻南方火（木之子）、补北方水（木之母）——原文言方位与五行，"
                                "取何经何穴是后人的读法"})
        for e in entries:
            if e["organ"] != "肝":
                continue
            earth = st("脾")
            status = "met" if "deficiency" in earth else ("not_needed" if "excess" in earth else "not_given")
            text = {"met": "脾（土）之虚已见：扶脾有据——仍据所辨之证取穴",
                    "not_needed": "所给之土非虚：四季脾王不受邪，即勿补之",
                    "not_given": "脾的状况未给：防传须考虑，但不据此自动加补脾之穴；脾已足者即勿补之"}[status]
            out.append({"rule": "prevent_transmission", "name": fw.rules["prevent_transmission"]["name"], "status": status, "text": text})
            break
        if any(e["organ"] == "心" and e["state"] in STATES for e in entries):
            out.append({"rule": "nanjing79", "name": fw.rules["nanjing79"]["name"], "status": "applies",
                        "text": "《难经·七十九难》心病取手心主：泻手心主俞（大陵），补手心主井（中冲）——另一经典取法，与取心经本经之穴并列"})
        if any(e["state"] == "neutral" for e in entries):
            out.append({"rule": "own_phase", "name": fw.rules["own_phase"]["name"], "status": "applies",
                        "text": "所给明确不实不虚者，《难经·六十九难》“不实不虚，以经取之”；虚实未定不满足此条件"})
        return out

    def _wx_strategies(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The named strategies whose premise the states fit (full), or would with one more state (conditional)."""
        fw = self.fw
        wx = fw.wx
        # These strategies name the five zang. A fu sharing a phase does not
        # establish its paired zang's state (e.g. 胃虚 does not establish 脾虚).
        zang = [e for e in entries if e["organ"] == fw.phase_organ(e["phase"])]
        have = {(e["phase"], e["state"]) for e in zang}
        phases = {e["phase"] for e in zang}
        sname = lambda s: ((wx.get("states") or {}).get(s) or {}).get("name", "")  # noqa: E731
        out = []
        for sid, s in (wx.get("strategies") or {}).items():
            best = None
            for alt in s.get("when") or []:
                missing = [(ph, want) for ph, want in alt.items()
                           if not (ph in phases if want == "any" else (ph, want) in have)]
                if missing and len(missing) >= len(alt):
                    continue
                if best is None or len(missing) < len(best):
                    best = missing
            if best is None or len(best) > 1:
                continue
            rule = fw.rules.get(s["rule"]) or {}
            row = {"id": sid, "name": s["name"], "en": s["en"], "rule": s["rule"], "level": rule.get("level", "teaching"),
                   "fit": "full" if not best else "conditional",
                   "missing": [f"{ph}（{fw.phase_organ(ph)}）{'' if w == 'any' else sname(w)}" for ph, w in best],
                   "premise": s["premise"], "implication": s["implication"], "note": s.get("note"),
                   "derived": [], "conflicts": [], "examples": []}
            for d in s.get("derive") or []:
                organ = d["organ"]
                phase = fw.channels[fw.organs[organ]["channel"]]["phase"]
                e = {"organ": organ, "channel": fw.organs[organ]["channel"], "phase": phase,
                     "state": "deficiency" if d["take"] == "mother" else "excess", "pattern": s["premise"],
                     "state_name": sname("deficiency" if d["take"] == "mother" else "excess")}
                row["derived"] += self._wx_methods(e, ["nanjing69", "nanjing69_cross"])
            row["conflicts"] = self._wx_conflicts(row["derived"])
            for ex in s.get("examples") or []:
                row["examples"].append({**{k: ex.get(k) for k in ("context", "source", "url", "doi", "note")},
                                        "points": [self._wx_example_point(c, s) for c in ex["points"]],
                                        "checked": False})
            out.append(row)
        out.sort(key=lambda r: (r["fit"] != "full", list(wx.get("strategies") or {}).index(r["id"])))
        return out

    def _wx_example_point(self, code: str, strategy: dict[str, Any]) -> dict[str, Any]:
        """A point a source gives for a strategy, with what the tables say it is — its Five-Shu phase (if any), and its other
        categories — so that the rationale the tables can and cannot give is visible."""
        fw = self.fw
        out = self._wx_point(code, None)
        out["categories"] = [c["label"] for c in fw.categories(code) if c["type"] != "five_shu"]
        organs = strategy.get("organs") or []
        phases = {fw.channels[fw.organs[o]["channel"]]["phase"]: o for o in organs}
        if out.get("phase"):
            rel = [f"{fw.relation_text(out['phase'], ph)}（对{o}）" for ph, o in phases.items()]
            out["reading"] = f"{out['label']}穴，{out['phase']}；" + "；".join(rel)
        else:
            out["reading"] = "不是五输穴，无五输之五行：" + ("、".join(out["categories"]) or "其理在所在之经与传统主治")
        return out

    def _wx_conflicts(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        names: dict[str, str] = {}
        for r in records:
            for p in r["points"]:
                if p["intent"] in ("补", "泻"):
                    by[p["code"]][p["intent"]].append(f"{r['name']}（{r['organ']}{'虚' if r['state'] == 'deficiency' else '实'}）")
                    names[p["code"]] = p["name"]
        out = []
        for code, it in by.items():
            if it.get("补") and it.get("泻"):
                out.append({"code": code, "name": names[code], "tonify": list(dict.fromkeys(it["补"])), "reduce": list(dict.fromkeys(it["泻"])),
                            "text": f"{names[code]}：{'、'.join(dict.fromkeys(it['补']))}言补，{'、'.join(dict.fromkeys(it['泻']))}言泻——"
                                    "同一穴意图相反，须先定主次（标本缓急），不能由五行之式自动合并"})
        return out

    def _wx_branches(self, entries: list[dict[str, Any]], strategies: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The branches of reasoning the states allow: each strategy whose premise a further clarification would confirm,
        and, where excess and deficiency are found in different organs, the need to set priorities."""
        out = []
        for s in strategies:
            pts = "、".join(dict.fromkeys(f"{p['name']}（{p['intent']}）" for r in s["derived"] for p in r["points"]))
            out.append({"kind": "strategy" if s["fit"] == "full" else "conditional", "strategy": s["name"], "level": s["level"],
                        "clarification": s["premise"] if s["fit"] == "full" else f"若兼{'、'.join(s['missing'])}：{s['premise']}",
                        "concept": s["name"], "interpretation": s["implication"] + (f"；按五输之理可推出 {pts}" if pts else "")
                        + (f"（{s['note']}）" if s.get("note") else "")})
        ex = {e["organ"] for e in entries if e["state"] == "excess"}
        de = {e["organ"] for e in entries if e["state"] == "deficiency"}
        if ex and de and ex != de:
            out.append({"kind": "mixed", "strategy": None, "level": "deduction",
                        "clarification": f"{'、'.join(ex)}实与{'、'.join(de)}虚并见", "concept": "先定主次，补泻相合",
                        "interpretation": f"单一的“泻{'、'.join(ex)}”之式不能代表整个证候"})
        return out

    def _wx_guards(self, entries: list[dict[str, Any]], used: list[str], text: str) -> list[dict[str, Any]]:
        fw = self.fw
        wx = fw.wx
        low = self.b.normalize(text).lower()
        claims: dict[str, str] = {}
        for c in wx.get("claims") or []:
            m = re.search(c["pattern"], low)
            if m:
                claims.setdefault(c["guard"], text[m.start():m.end()] if len(text) == len(low) else m.group(0))
        states = {e["state"] for e in entries}
        ex = {e["organ"] for e in entries if e["state"] == "excess"}
        de = {e["organ"] for e in entries if e["state"] == "deficiency"}
        out = []
        for gid, g in (wx.get("guards") or {}).items():
            w = g.get("when")
            why = None
            if gid in claims:
                why = f"所给之文：「{claims[gid]}」"
            elif w == "always":
                why = "always"
            elif isinstance(w, dict):
                if w.get("state") and w["state"] in states:
                    why = "state"
                elif w.get("states") and len(entries) >= w["states"]:
                    why = "states"
                elif w.get("mixed") and ex and de and ex != de:
                    why = "mixed"
                elif w.get("phase") and any(e["phase"] == w["phase"] for e in entries):
                    why = "phase"
                elif w.get("method") and w["method"] in used:
                    why = "method"
                elif w.get("text") and re.search(w["text"], low):
                    why = "text"
            if why:
                out.append({"id": gid, "statement": g["statement"], "level": g.get("level"), "why": why, "claim": gid in claims})
        out.sort(key=lambda g: not g["claim"])
        return out

    def _wx_evidence(self, used: list[str]) -> dict[str, Any]:
        fw = self.fw
        recs = []
        for key, m in (fw.d.get("modern") or {}).items():
            ap = m.get("applies")
            if isinstance(ap, dict) and set(ap.get("methods") or []) & set(used):
                recs.append({"id": key, **{k: m.get(k) for k in ("citation", "pmid", "doi", "design", "population", "size", "finding", "limits")},
                             "bears_on": [(fw.wx["methods"][x] or {}).get("name", x) for x in ap["methods"] if x in used]})
        return {"levels": fw.d.get("evidence_levels") or [], "modern": recs,
                "note": "文献支持把这些方法当作可追溯的传统选穴体系来研究；其临床效果须就具体病证与处方评价——一项试验既不证明五行取穴的"
                        "全部配方，也不否定某一个具体组合。可用现代证据工具（modern.search）检索并按设计分级。"}

    def _wx_steps(self, out: dict[str, Any]) -> list[dict[str, str]]:
        """The record of six elements: pattern premise → channels → relation → selection rule → intention → source."""
        states = "；".join(f"{s['organ']}（{s['phase']}）{s['state_name']}" + (f"〔{s['pattern']}〕" if s.get("pattern") else "") for s in out["states"])
        pending = [c for c in out["clarify"] if not c["given"]]
        chans = "、".join(dict.fromkeys(c for r in out["methods"] for c in r["channels"]))
        rel = "；".join(r["text"] for r in out["relations"]) or "所给之态之间未见生克乘侮的关系（或只给一态）"
        meth = "、".join(dict.fromkeys(f"{r['name']}（{r['level_name']}）" for r in out["methods"]))
        intents = f"补泻意图逐穴标明；{len(out['conflicts'])} 穴在不同取法中意图相反，须定主次" if out["conflicts"] else "补泻意图逐穴标明"
        return [
            {"step": "1", "title": "证候前提", "text": states + ("。须先辨明：" + "；".join(f"{c['organ']}——{'、'.join(c['candidates'][:5])}" for c in pending) if pending else "。")},
            {"step": "2", "title": "所涉之经", "text": chans or "—"},
            {"step": "3", "title": "五行关系", "text": rel},
            {"step": "4", "title": "取穴之规", "text": meth or "—"},
            {"step": "5", "title": "补泻意图", "text": intents},
            {"step": "6", "title": "文献或经验出处", "text": "每一取法附其规则与出处（经典、流派、推演分层）；现代证据另列，不验证选穴之规。"},
        ]

    def _point_phase(self, code: str) -> dict[str, Any]:
        """A point in the Five Phases: its channel's phase, its Five-Shu category and phase (if any) and what that phase is to
        the channel's — three attributes — and the methods that take it, with their intention."""
        fw = self.fw
        p = fw.points[code]
        ch = p["channel"]
        c = fw.channels.get(ch) or {}
        out: dict[str, Any] = {"channel_phase": c.get("phase"), "five_shu": None, "roles": [], "notes": []}
        cat = next((x for x in fw.categories(code) if x["type"] == "five_shu"), None)
        if cat:
            out["five_shu"] = {"kind": cat["kind"], "label": fw.kind_label[cat["kind"]], "en": fw.kind_en[cat["kind"]], "phase": cat["phase"],
                               "relation": fw.relation(cat["phase"], c["phase"]), "relation_text": fw.relation_text(cat["phase"], c["phase"])}
            if fw.has(code, "yuan") and cat["phase"] != c["phase"]:
                own = fw.phase_point(ch, c["phase"])
                out["notes"].append(f"{p['name']}是{c['short']}的原穴，五行属{cat['phase']}；{c['short']}的同气之穴是{fw.points[own]['name']}（{c['phase']}）——二者不同")
            if cat["phase"] == "土" and c["phase"] != "土":
                out["notes"].append(f"{p['name']}是土穴，但仍是{c['short']}之穴：不即是补脾之穴，其解读兼及所在之经、特定穴之位、传统主治与刺激方式")
            out["notes"].append(f"{p['name']}属{cat['phase']}：取此穴是补是泻，由取法与所辨之证定，不由其五行定")
        elif c.get("phase") and ch not in MIDLINE | {"EX"}:
            others = "、".join(x["label"] for x in fw.categories(code)) or "非特定穴"
            out["notes"].append(f"不是五输穴，无五输之五行（{others}）：不因所在之经属{c['phase']}而为{c['phase']}穴")
        for x in fw.categories(code):
            if x["type"] in ("back_shu", "front_mu") and fw.organs.get(x.get("organ", "")):
                ph = fw.channels[fw.organs[x["organ"]]["channel"]]["phase"]
                out["notes"].append(f"{x['label']}：与{x['organ']}相关，并不因此成为五输的{ph}穴" + ("；背俞（Back-Shu）与五输的输穴（Shu-Stream）是两种归类" if x["type"] == "back_shu" else ""))
        for other in ("LU", "LI", "ST", "SP", "HT", "SI", "BL", "KI", "PC", "TE", "GB", "LR"):
            s = fw.saam(other)
            for state, label in (("deficiency", "正格"), ("excess", "胜格")):
                for act, intent in (("tonify", "补"), ("sedate", "泻")):
                    if code in s[state][act]["points"]:
                        out["roles"].append({"method": "saam", "level": "school", "channel": other, "state": state, "intent": intent,
                                             "text": f"舍岩针法 {fw.channels[other]['short']}{label}：{intent}（{s[state][act]['phase']}）"})
            pr = fw.paired(other) or {}
            for via in ("interior_exterior", "same_name"):
                if via in pr:
                    for which, state, intent in (("mother", "deficiency", "补"), ("child", "excess", "泻")):
                        if pr[via][which] == code:
                            out["roles"].append({"method": via, "level": "deduction", "channel": other, "state": state, "intent": intent,
                                                 "text": f"{(fw.wx.get('methods') or {}).get(via, {}).get('name', via)}：{fw.channels[other]['short']}"
                                                         f"{'虚' if state == 'deficiency' else '实'}，{intent}{fw.channels[pr[via]['channel']]['short']}之此穴"})
        for kind, state, intent, said in (("shu_stream", "excess", "泻", "泻手心主俞"), ("jing_well", "deficiency", "补", "补手心主井")):
            if fw.five_shu("PC", kind) == code:  # 《难经·七十九难》: the Heart's disorders through the Pericardium channel
                out["roles"].append({"method": "nanjing79", "level": "classical", "channel": "HT", "state": state, "intent": intent,
                                     "text": f"《难经·七十九难》心病：{said}"})
        return out

    # ============================================================ one point in the classics
    def point(self, name: str, *, limit: int = 30) -> dict[str, Any]:
        fw = self.fw
        code = fw.resolve(name)
        if code is None:
            near = [f"{p['name']}（{c}）" for c, p in fw.points.items() if any(ch in p["name"] for ch in self.b.normalize(name))][:6]
            raise ValueError(f"{name!r} is not a point of acupuncture.yaml (a code such as ST36, a name such as 足三里, an alias "
                             f"or pinyin)" + (f"; points sharing a character: {'、'.join(near)}" if near else ""))
        p = fw.points[code]
        cats = fw.categories(code)
        found = self._point_passages(code)
        entries = found["entries"]
        indications = found["indications"]
        checks = self._checks(code, entries)
        by_work: dict[str, dict[str, Any]] = {}
        for ind in sorted(indications, key=lambda x: (dated(x["witness"].get("years")), x["witness"]["passage_id"])):
            by_work.setdefault(ind["witness"].get("work") or ind["witness"]["book_id"], ind)
        findings = Counter()
        for ind in by_work.values():
            for f in ind["findings"]:
                findings[f] += 1
        periods = Counter(ind["witness"].get("period") or "未定" for ind in by_work.values())
        roles = []
        for cat in cats:
            if cat["type"] == "five_shu":
                m = fw.mother_child(cat["channel"])
                if m and m["same"]["mother"] == code:
                    roles.append(f"{fw.channels[cat['channel']]['short']}之母穴（{m['mother_phase']}生{m['phase']}）：虚则补之")
                if m and m["same"]["child"] == code:
                    roles.append(f"{fw.channels[cat['channel']]['short']}之子穴（{m['phase']}生{m['child_phase']}）：实则泻之")
                if m and m["own"] == code:
                    roles.append(f"{fw.channels[cat['channel']]['short']}之本穴（与本经同属{m['phase']}）")
        for ch in fw.channels:
            m = fw.mother_child(ch)
            if m and m["cross"]["mother"] == code:
                roles.append(f"他经补母：{fw.channels[ch]['short']}（{m['phase']}）虚，补母经之本穴{p['name']}")
            if m and m["cross"]["child"] == code:
                roles.append(f"他经泻子：{fw.channels[ch]['short']}（{m['phase']}）实，泻子经之本穴{p['name']}")
        rules_used = list(dict.fromkeys(c["rule"] for c in cats))
        out = {
            "point": {"code": code, "name": p["name"], "pinyin": p.get("pinyin"), "channel": p["channel"],
                      "channel_name": fw.channels[p["channel"]]["name"], "part": p.get("part"), "location": p.get("location"),
                      "aliases": p.get("aliases") or [], "also_called": p.get("also_called") or [], "other_codes": p.get("other_codes") or [],
                      "note": p.get("note"), "categories": cats, "mother_child": roles, "five_phase": self._point_phase(code),
                      "cautions": [{"id": k, **(fw.d["cautions"].get(k) or {})} for k in p.get("cautions") or []],
                      "standard": "GB/T 12346—2021《经穴名称与定位》"},
            "names": fw.names(code),
            "entries": entries[:limit],
            "checks": checks,
            "indications": {"works": len(by_work), "statements": len(indications), "periods": dict(periods),
                            "earliest": next(iter(by_work.values()))["witness"] if by_work else None,
                            "findings": [{"finding": f, "works": k} for f, k in findings.most_common(30)],
                            "examples": [{"witness": x["witness"], "condition": x["condition"], "form": x["form"], "findings": x["findings"]}
                                         for x in list(by_work.values())[:limit]]},
            "prohibitions": self.prohibitions(code),
            "rules": [self._rule_card(r) for r in rules_used if r in fw.rules],
            "summary": {"entries": len(entries), "entry_works": len({e["witness"].get("work") or e["witness"]["book_id"] for e in entries}),
                        "indication_works": len(by_work), "checks_differ": sum(1 for c in checks if c["differ"])},
            "note": "条目（某穴“在……刺入……灸……”）与主治语句（“……某穴主之”“某穴主……”“取某穴”）由规则读出，属机器阅读："
                    "每条附原文，请回查；只识别本数据所收之穴名与别名，一名两穴者（临泣、通谷、窍阴、五里）不计。",
            "notice": self.notice,
        }
        return out

    def prohibitions(self, code: str) -> list[dict[str, Any]]:
        """禁刺、禁灸 as the classics' entries for the point state them (one per work)."""
        by_work: dict[str, dict[str, Any]] = {}
        for e in sorted(self._point_passages(code)["entries"], key=lambda e: (dated(e["witness"].get("years")), e["witness"]["passage_id"])):
            for text in e["stated"].get("prohibitions") or []:
                by_work.setdefault(e["witness"].get("work") or e["witness"]["book_id"], {"text": text, "witness": e["witness"]})
        return list(by_work.values())

    def _checks(self, code: str, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The point's attributes in the data against what each entry states: agree, differ (with the witnesses)."""
        fw = self.fw
        cats = fw.categories(code)
        expect: dict[str, set[str]] = {}
        for c in cats:
            if c["type"] == "five_shu":
                expect["phase"] = {c["phase"]}
                expect["kind"] = expect.get("kind", set()) | {c["kind"]}
            elif c["type"] == "yuan":
                expect["kind"] = expect.get("kind", set()) | {"yuan"}
            elif c["type"] == "front_mu":
                expect["mu"] = {c["organ"]}
            elif c["type"] == "xi":
                expect["xi"] = {c.get("channel") or c.get("vessel")}
            elif c["type"] == "luo" and c.get("channel"):
                expect["luo"] = {c["channel"]}
            elif c["type"] == "crossing":
                expect["meeting"] = set(c["channels"]) | set(c.get("vessels") or [])
        label = {"phase": "五行", "kind": "五输或原", "mu": "募", "xi": "郄", "luo": "络", "meeting": "交会"}
        rows = []
        for attr, want in expect.items():
            agree, differ = [], []
            for e in entries:
                said = e["stated"].get(attr)
                if not said:
                    continue
                said_set = set(said) if isinstance(said, list) else {said}
                if attr == "meeting":
                    own = {fw.points[code]["channel"]}
                    ok = said_set <= (want | own) and want <= (said_set | own)
                elif attr == "kind":
                    ok = bool(said_set & want)
                else:
                    ok = said_set == want
                (agree if ok else differ).append({"stated": sorted(said_set), "witness": e["witness"]})
            if agree or differ:
                rows.append({"attribute": attr, "label": label[attr], "data": sorted(want), "agree": len(agree), "differ": differ[:6],
                             "agree_earliest": agree[0]["witness"] if agree else None})
        return rows

    # ------------------------------------------------------------ the passages naming a point, read once
    def _point_passages(self, code: str) -> dict[str, Any]:
        if code in self._by_point:
            return self._by_point[code]
        books = self._acupuncture_books()
        ids: list[str] = []
        names = self.fw.names(code)
        # a shorter name another point goes by, which this one's ends with (三里 of 手三里): a chapter of its channel may
        # write it so (「三里在曲池下二寸」 under 手阳明); the parse gives it to the point the chapter's channel has
        own = self.b.normalize(self.fw.points[code]["name"])
        names += [n for c in self.fw.points if c != code for n in self.fw.names(c) if own.endswith(n) and n != own and n not in names]
        for n in names:
            if books:
                ids += self.b.find(n, book_ids=books, limit=3000)
            ids += self.b.find(n + "主", limit=400)  # 千金、外台、资生经 … : 「太泉主心痛」「三里主之」
            ids += self.b.find("取" + n, limit=200)  # 灵枢: 「胃病者……取三里」
        entries, indications = [], []
        for p in self.b.passages(dict.fromkeys(ids)):
            parsed = self._parse(p)
            entries += [e for e in parsed["entries"] if e["code"] == code]
            indications += [i for i in parsed["indications"] if i["code"] == code]
        entries.sort(key=lambda e: (dated(e["witness"].get("years")), e["witness"]["passage_id"]))
        out = {"entries": entries, "indications": indications}
        self._by_point[code] = out
        return out

    def _names_re(self) -> re.Pattern[str]:
        if self._name_re is None:
            pairs = []
            for code in self.fw.points:
                for n in self.fw.names(code):
                    pairs.append((n, code))
            self._name_code = {}
            for n, code in pairs:
                self._name_code.setdefault(n, code)
            names = sorted(self._name_code, key=len, reverse=True)
            self._name_re = re.compile("|".join(map(re.escape, names)))
        return self._name_re

    def _compact(self, text: str) -> tuple[str, list[int]]:
        """The normalised text without its spaces (a Siku page break may fall inside a name: 鬲　俞), and for each of its
        characters the offset in the original."""
        norm = self.b.normalize(text)
        if len(norm) != len(text):  # pragma: no cover - the normaliser keeps lengths
            norm = text
        chars, idx = [], []
        for i, ch in enumerate(norm):
            if ch.isspace():
                continue
            chars.append(ch)
            idx.append(i)
        return "".join(chars), idx

    def _parse(self, p: Any) -> dict[str, Any]:
        """A passage's point entries and indication statements."""
        if p.id in self._parsed:
            return self._parsed[p.id]
        t, idx = self._compact(p.text)
        tokens = [(m.start(), m.end(), self._name_code[m.group(0)]) for m in self._names_re().finditer(t)]
        tokens = self._by_heading(p, t, tokens)
        acu = getattr(self.b.corpus.books.get(p.book_id), "category", "") == "针灸"

        def span(a: int, b: int) -> tuple[int, int]:
            a = max(0, min(a, len(idx) - 1)) if idx else 0
            b = max(a, min(b, len(idx))) if idx else 0
            return (idx[a] if idx else 0), (idx[b - 1] + 1 if idx and b > 0 else 0)

        indications: list[dict[str, Any]] = []
        ends = {e: (s, c) for s, e, c in tokens}
        starts = {s: (e, c) for s, e, c in tokens}
        # (a) 「……三里主之」: the points just before 主之, the condition before them
        last = 0
        for m in re.finditer("主之", t):
            j = m.start()
            got: list[tuple[int, int, str]] = []
            while True:  # 「尺泽、曲泽主之」「厉兑解溪三里主之」: every point of the list
                k = j
                while k > 0 and t[k - 1] in "穴":
                    k -= 1
                hit = ends.get(k)
                if hit is None:
                    break
                got.append((hit[0], k, hit[1]))
                j = hit[0]
                if j > 0 and t[j - 1] in _SEP:
                    j -= 1
                continue
            if got:
                first = min(s for s, _, _ in got)
                begin = max(last, max((t.rfind(c, 0, first) for c in _STOP), default=-1) + 1, first - 80,
                            max(t.rfind(c, 0, first) for c in "壮呼") + 1)  # after the needling of an entry before it
                cond = t[begin:first].strip("，,、 ")
                if len(cond) >= 2 and _han(cond):
                    a, b = span(begin, m.end())
                    for s, _e, c in got:
                        indications.append(self._indication(p, c, "主之", cond, a, b))
            last = m.end()
        # (b) 「太泉主心痛」「三里：主……」「太泉治胸胁支满」: the points, then 主 / 主治 / 治 / 疗 and the condition after
        for s, e, c in tokens:
            k = e
            group = [(s, e, c)]
            while k < len(t) and t[k] in _SEP and starts.get(k + 1):
                e2, c2 = starts[k + 1]
                group.append((k + 1, e2, c2))
                k = e2
            mm = re.match(r"(?:二穴|两穴|穴)?[：:，,]?(主治|主|治|疗)(?!之)", t[k:k + 6])
            if not mm or (s > 0 and t[s - 1] in _SEP and ends.get(s - 1) is not None):
                continue
            begin = k + mm.end()
            stop = min([i for i in (t.find(ch, begin) for ch in _STOP + "（(") if i >= 0] + [begin + 60, len(t)])
            other = t.find("主之", begin, stop)
            stop = other if other >= 0 else stop
            nxt = next((s2 for s2, _e2, _c2 in tokens if begin < s2 < stop), None)
            stop = nxt if nxt is not None else stop
            cond = t[begin:stop].strip("，,、 ")
            if len(cond) >= 2 and _han(cond):
                a, b = span(s, stop)
                for _s, _e, c2 in group:
                    indications.append(self._indication(p, c2, mm.group(1), cond, a, b))
        # (c) 「胃病者……取三里」「胸满腹痛刺内关」: 取 / 刺 / 灸 just before a point, the condition before — only where a
        # sentence begins within forty characters (in unpunctuated text a procedure is too easily read for a condition)
        for s, e, c in tokens:
            mm = re.search(r"(?:取之|取|刺|灸)$", t[max(0, s - 2):s])
            if not mm:
                continue
            at = s - len(mm.group(0))
            done_at = t.rfind("主之", 0, at)
            begin = max([t.rfind(ch, 0, at) + 1 for ch in _STOP] + [done_at + 2 if done_at >= 0 else 0])
            if at - begin > 40:  # the last clauses within forty characters, cut at a comma
                cut = min((i for i in (t.find(ch, at - 40, at) for ch in "，,") if i >= 0), default=-1)
                if cut < 0:
                    continue
                begin = cut + 1
            cond = t[begin:at].strip("，,、 ")
            if len(cond) >= 2 and self._names_finding(cond) and not cond.endswith(("在", "去", "下", "上")):
                a, b = span(begin, e)
                indications.append(self._indication(p, c, mm.group(0), cond, a, b))
        entries = self._entries(p, t, tokens, span, tail=self._continuation(p, t, tokens)) if acu else []
        out = {"entries": entries, "indications": indications}
        if len(self._parsed) >= PARSED_MAX:  # a long-running server reads many passages: keep the cache bounded
            self._parsed.clear()
        self._parsed[p.id] = out
        return out

    def _indication(self, p: Any, code: str, form: str, cond: str, a: int, b: int) -> dict[str, Any]:
        lex = self.b.pack.lexicon
        findings = [sym["name"] for sym, forms in self._symptom_forms() if any(f in cond for f in forms)]
        findings += [m.entry.term for m in lex.match(cond)
                     if m.entry.category in ("symptom", "sign", "disease", "pulse", "pattern") and len(m.surface) >= 2]
        findings = list(dict.fromkeys(findings))
        return {"code": code, "form": form, "condition": cond, "findings": findings,
                "witness": self.b.witness(p, start=a, end=b, width=0)}

    def _names_finding(self, cond: str) -> bool:
        """Whether a condition names a finding (a symptom of the data or one of the lexicon) — not a procedure (又当灸三里)."""
        if any(any(f in cond for f in forms) for _sym, forms in self._symptom_forms()):
            return True
        return any(m.entry.category in ("symptom", "sign", "disease", "pulse", "pattern") and len(m.surface) >= 2
                   for m in self.b.pack.lexicon.match(cond))

    def _symptom_forms(self) -> list[tuple[dict[str, Any], list[str]]]:
        if not hasattr(self, "_forms"):
            self._forms = [(sym, [self.b.normalize(f) for f in sym.get("classical") or []]) for sym in self.fw.symptoms.values()]
        return self._forms

    def _by_heading(self, p: Any, t: str, tokens: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
        """A name read in the chapter of another channel is that channel's point when one of its points ends with it:
        「三里在曲池下二寸」 under 手阳明 is 手三里, not 足三里."""
        loc = p.locator
        heading = self.b.normalize(" ".join(x for x in (loc.volume, loc.chapter, loc.section) if x))
        if not heading:
            return tokens
        fw = self.fw
        ch = next((c for n, kind, c in fw.vocabulary() if kind == "channel" and n in heading), None)
        if ch is None:
            return tokens
        out = []
        for s, e, code in tokens:
            if fw.points[code]["channel"] != ch:
                same = [c for c, pt in fw.points.items() if pt["channel"] == ch and self.b.normalize(pt["name"]).endswith(t[s:e])]
                code = same[0] if len(same) == 1 else code
            out.append((s, e, code))
        return out

    def _continuation(self, p: Any, t: str, tokens: list[tuple[int, int, str]]) -> str:
        """The start of the next passage when an entry runs over the end of this one (its location here, its needling
        there) — read for what the entry states, never quoted as this passage's."""
        late = [e for s, e, _c in tokens if len(t) - e < 160 and re.search("[在去]", t[e:e + 40]) and not _NEEDLE.search(t[e:])]
        if not late:
            return ""
        nxt = self.b.following(p, 1)
        return self._compact(nxt[0].text)[0][:200] if nxt else ""

    def _entries(self, p: Any, t: str, tokens: list[tuple[int, int, str]], span: Any, tail: str = "") -> list[dict[str, Any]]:
        """Point entries of an acupuncture book: a name at the head of a statement, its location (在……, or 去……) within
        forty characters and its needling or moxibustion within a hundred and sixty — 「中府，肺之募也，一名膺中俞，在云门下
        一寸……刺入三分，留五呼，灸五壮」; an entry running into the next passage is read with its start (``tail``)."""
        full = t + tail

        def seg(e: int, n: int) -> str:  # what follows a name, to the next entry marked ○ (针经节要: 「曲池(合)○商阳二穴……」)
            stop = full.find("○", e)
            return full[e: min(e + n, stop) if stop >= 0 else e + n]

        heads = [(s, e, c) for s, e, c in tokens if (s == 0 or t[s - 1] in _ENTRY_START)
                 and t.rfind("（", 0, s) <= t.rfind("）", 0, s)  # not inside a note
                 and (re.search("[在去]", seg(e, 40)) or _PROHIBIT.search(seg(e, 60)))  # 「脐中……禁不可刺」
                 and _NEEDLE.search(seg(e, 160))]
        more = [(m.start() + len(t), m.end() + len(t)) for m in self._names_re().finditer(tail)]
        starts = sorted(s2 for s2, e2 in [(a, b) for a, b, _c in tokens] + more
                        if full[e2:e2 + 1] in ("为", "者"))  # 「经渠为经金」: another point's entry begins
        out = []
        for i, (s, e, c) in enumerate(heads):
            nxt = min([heads[i + 1][0] if i + 1 < len(heads) else len(full)] + [x for x in starts if x > e]
                      + ([full.find("○", e)] if full.find("○", e) >= 0 else []))
            needle = _NEEDLE.search(full, e, min(nxt, e + 160))
            end = min(nxt, e + 220)
            if needle:
                stop = full.find("。", needle.end(), end)
                end = stop + 1 if stop >= 0 else end
            body = full[e:end]
            a, b = span(s, min(end, len(t)))
            out.append({"code": c, "stated": self._stated(c, body), "witness": self.b.witness(p, start=a, end=b, width=0)})
        return out

    def _stated(self, code: str, body: str) -> dict[str, Any]:
        """What an entry states of its point: phase, kind (井荥俞经合原), Mu, Xi, Luo, meeting, other names, location,
        needling and moxibustion, prohibitions."""
        out: dict[str, Any] = {}
        head = body[:60]
        loc_at = head.find("在")
        pre = head[: loc_at if loc_at >= 0 else 30]
        m = re.match(r"^(?:二穴|穴)?[者：:，,]*([木火土金水])也", body)  # 「太渊者，土也」「商阳二穴金也」
        if m:
            out["phase"] = m.group(1)
        kinds = [STATED_KIND[k] for k in re.findall(r"为(井|荥|荣|俞|腧|输|经|合|原)", body[:200])]
        kinds += [FLOW_KIND[k] for k in re.findall(r"之?所(出|溜|流|注|行|入|过)(?:也|为|，|。)", body[:200])]
        if kinds:
            out["kind"] = sorted(set(kinds))
        m = re.search(r"(" + "|".join(ORGAN_WORDS) + r")之?募", pre)
        if m:
            out["mu"] = m.group(1)
        m = re.search(r"((?:手|足)(?:太阴|少阴|厥阴|阳明|太阳|少阳)|阴跷|阳跷|阴维|阳维)之?郄", pre)
        if m:
            out["xi"] = self._channel_of(m.group(1), code)
        m = re.search(r"((?:手|足)?(?:太阴|少阴|厥阴|阳明|太阳|少阳|心主))之?络", body[:120])
        if m:
            out["luo"] = self._channel_of(m.group(1), code)
        m = re.search(r"([^。；]{2,26})之会", body[:200])
        if m:
            out["meeting"] = self._meeting(m.group(1))
        names = [x.rstrip("是也") for x in re.findall(r"一名([^\s，。、；一在]{1,4}?)(?=一名|在|，|。|、|；|$|(?:" + "|".join(ORGAN_WORDS) + r")之?募|[手足][太少厥阳])", pre)]
        if names:
            out["names"] = names
        m = re.search(r"在(.{2,60}?)(?=(?:手|足)(?:太阴|少阴|厥阴|阳明|太阳|少阳|心主)|督脉|任脉|(?:刺|针|鍼)|灸|禁|不可|[）)]|$)", body)
        if m:
            out["location"] = m.group(1).strip("，,。")
        m = re.search(r"(?:刺|针|鍼)入([一二三四五六七八九十半]+(?:寸[一二三四五六七八九十半]*分?|分))", body)
        if m:
            out["needle"] = m.group(1)
        m = re.search(r"留([一二三四五六七八九十]+)呼", body)
        if m:
            out["retain"] = m.group(1) + "呼"
        m = re.search(r"灸([一二三四五六七八九十百]+)壮", body)
        if m:
            out["moxa"] = m.group(1) + "壮"
        pro = [x.group(0).rstrip("，,") for x in _PROHIBIT.finditer(body)]
        if pro:
            out["prohibitions"] = pro
        return out

    def _channel_of(self, words: str, code: str) -> str | None:
        """手太阴 → LU; 阴跷 → 阴跷脉; a six-name without its limb read on the point's own limb."""
        fw = self.fw
        if words in VESSEL_WORDS:
            return VESSEL_WORDS[words]
        if words.endswith("心主"):
            return "PC"
        limb = words[0] if words[0] in "手足" else fw.channels.get(fw.points[code]["channel"], {}).get("limb")
        six = words[-2:]
        return next((ch for ch, c in fw.channels.items() if c.get("six") == six and c.get("limb") == limb), None)

    def _meeting(self, text: str) -> list[str]:
        """The channels and vessels a 「……之会」 names: 足太阴厥阴少阴 → SP LR KI; 三阳督脉 → the six yang channels and 督脉."""
        fw = self.fw
        out: list[str] = []
        limb: str | None = None
        for m in _LIMB_SIX.finditer(text):
            if m.group(3):
                out.append(VESSEL_WORDS[m.group(3)] if m.group(3) not in ("督脉", "任脉") else {"督脉": "GV", "任脉": "CV"}[m.group(3)])
                continue
            if m.group(1):
                limb = m.group(1)
            six = m.group(2)
            limbs = ["手", "足"] if limb in (None, "手足") and six in ("三阳", "三阴") else ["手", "足"] if limb == "手足" else [limb or ""]
            if six in ("三阳", "三阴"):
                yin = six == "三阴"
                out += [ch for ch, c in fw.channels.items() if c.get("limb") in limbs and c.get("six") and bool(c.get("yin")) == yin]
            elif six == "心主":
                out.append("PC")
            else:
                out += [ch for ch, c in fw.channels.items() if c.get("six") == six and (not limbs[0] or c.get("limb") in limbs)]
        return list(dict.fromkeys(out))


__all__ = ["AcupunctureStudy", "Framework", "GENERATES", "MOTHER"]
