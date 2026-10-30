"""针灸推理的协调与审核 —— ``study.acupuncture_reason`` 与 ``study.acupuncture_audit``（ADR 0027）。

A request keeps every fact apart.  An observation is one of four states (present, absent, unknown, conflicting) of
one concept, about one subject at one time and side, with the words it was read from and where they came from; an
organ state keeps its organ entity and its aspect (胃 is not 脾, 肾阳 not 肾阴), the phase only an annotation.  The
coordinator routes first (sudden hearing loss, acute neurological features, pulsatile or persistent unilateral
tinnitus), asks next — two questions at most, those that change the next step —, then compares the patterns; it gives
candidate points only where a server-side review record bound to this very case version accepts the premise the
method needs, and an educational demonstration (a premise stated as an assumption, no real case) only as mappings
that are not about anyone.  The audit checks claims and a proposed plan against the same rules and the point tables.

Rules are data (``acupuncture_reasoning.yaml``) in a closed language — ``all``, ``any``, ``eq``, ``in``, ``present`` —
and three-valued: a fact that is unknown or conflicting leaves a condition unresolved, never false, and an unresolved
condition triggers nothing.  Free text is matched, never executed.  ``control.*`` facts and reviewed premises come
from this controller alone: nothing in a request (a ``verified`` flag, a premise claimed accepted, a sentence saying
it was reviewed) can create them.  The contracts (``acupuncture_contracts.schema.json``) are checked on the way in —
an invalid request is answered as such (``invalid_parameters``, no assessment), never by a default — and on the way
out: a result that would break them is withheld (``dependency_unavailable``).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from .acupuncture import GENERATES, MOTHER, AcupunctureStudy

ORGAN_ID = {"肝": "liver", "胆": "gallbladder", "心": "heart", "小肠": "small_intestine", "脾": "spleen", "胃": "stomach",
            "肺": "lung", "大肠": "large_intestine", "肾": "kidney", "膀胱": "bladder", "心包": "pericardium", "三焦": "sanjiao"}
ORGAN_OF = {v: k for k, v in ORGAN_ID.items()}
PHASE_ID = {"木": "wood", "火": "fire", "土": "earth", "金": "metal", "水": "water"}
STATE_ID = {"excess": "excess", "deficiency": "deficiency", "mixed": "mixed", "neither": "neither_excess_nor_deficiency",
            "balanced": "balanced", "unknown": "unknown", "conflicting": "conflicting"}
STATE_OF = {v: k for k, v in STATE_ID.items()}
ASPECTS = ("yin", "yang", "qi", "blood", "essence", "fluid_processing")
INTENT_ID = {"补": "tonify", "泻": "reduce"}
STATUS_RANK = ("needs_urgent_assessment", "needs_etiologic_assessment", "needs_information", "rule_conflict", "candidate_review",
               "pattern_comparison", "educational_only", "no_applicable_rule")
WUXING_METHODS = ("nanjing69", "nanjing69_cross", "own_channel", "nanjing79", "saam", "interior_exterior", "same_name")
RELATION_ONLY = ("yuan_luo", "bietong")
PRINCIPLE = {("nanjing69", "deficiency"): "nanjing69.tonify_mother", ("nanjing69", "excess"): "nanjing69.reduce_child",
             ("nanjing69_cross", "deficiency"): "nanjing69_cross.tonify_mother_channel",
             ("nanjing69_cross", "excess"): "nanjing69_cross.reduce_child_channel", ("own_channel", "neither"): "own_channel.same_phase",
             ("nanjing79", "deficiency"): "nanjing79.tonify_mother", ("nanjing79", "excess"): "nanjing79.reduce_child",
             ("interior_exterior", "deficiency"): "interior_exterior.mother_phase", ("interior_exterior", "excess"): "interior_exterior.child_phase",
             ("same_name", "deficiency"): "same_name.mother_phase", ("same_name", "excess"): "same_name.child_phase"}
POINT_CODE = re.compile(r"(?<![A-Za-z])(LU|LI|ST|SP|HT|SI|BL|KI|PC|TE|SJ|GB|LR|CV|GV)-?(\d{1,3})(?![0-9])", re.I)
TRUST_WORDS = {"verified", "reviewed", "trusted", "trusted_server_fixture", "signature", "authorized", "trust", "is_verified"}
EFFICACY_NOTE = ("此取穴之法的依据是理论的出处；以此法为据的临床疗效未见确立（例如 VA/DoD 2024 认为针灸用于耳鸣的证据不足以推荐"
                 "或反对）——理论的出处不等于疗效，疗效的缺如也不反证理论。")
_HOURS = {"小时": 1, "hour": 1, "hours": 1, "天": 24, "日": 24, "day": 24, "days": 24, "周": 168, "星期": 168, "礼拜": 168,
          "week": 168, "weeks": 168, "月": 720, "month": 720, "months": 720, "年": 8760, "year": 8760, "years": 8760}
_EN_NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
           "eleven": 11, "twelve": 12, "several": 3, "a few": 3}
_DURATION = re.compile(r"(\d+(?:\.\d+)?|[一二两三四五六七八九十半]{1,3}|(?<![a-z])(?:a few|several|an?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve))"
                       r"\s*(?:个)?(小时|天|日|周|星期|礼拜|月|年|hours?|days?|weeks?|months?|years?)(?:\s*(前|以前|之前|ago))?")


# ------------------------------------------------------------------ JSON values
def _canon(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _same(a: Any, b: Any) -> bool:
    """JSON equality: a boolean equals only a boolean, a number only a number."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, (dict, list)) or isinstance(b, (dict, list)):
        return _canon(a) == _canon(b)
    return type(a) is type(b) and a == b


def _is(v: Any, t: str) -> bool:
    if t == "object":
        return isinstance(v, dict)
    if t == "array":
        return isinstance(v, list)
    if t == "string":
        return isinstance(v, str)
    if t == "boolean":
        return isinstance(v, bool)
    if t == "null":
        return v is None
    if t == "integer":
        return (isinstance(v, int) and not isinstance(v, bool)) or (isinstance(v, float) and v.is_integer())
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    return False


def _kind(v: Any) -> str:
    return next((t for t in ("null", "boolean", "integer", "number", "string", "array", "object") if _is(v, t)), type(v).__name__)


def observations_digest(observations: Any) -> str:
    """The SHA-256 of a case's observations as given (canonical JSON) — what a review record is bound to."""
    return hashlib.sha256(_canon(observations if observations is not None else []).encode("utf-8")).hexdigest()


class Contracts:
    """A JSON Schema checker for the keywords the contracts use (Draft 2020-12: ``$ref`` to ``$defs``, type, const, enum,
    pattern, minLength, maxLength, minimum, maximum, items, minItems, maxItems, uniqueItems, properties, required,
    additionalProperties, allOf, anyOf, oneOf, if / then / else) — no formats, no remote references, nothing run."""

    def __init__(self, schema: dict[str, Any]) -> None:
        self.schema = schema
        self.defs: dict[str, Any] = schema.get("$defs") or {}
        self._patterns: dict[str, tuple[re.Pattern[str], bool]] = {}

    def errors(self, value: Any, name: str) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        self._check(value, {"$ref": f"#/$defs/{name}"}, "", out)
        return out

    def _errs(self, v: Any, s: Any, path: str) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        self._check(v, s, path, out)
        return out

    def _match(self, pattern: str, v: str) -> bool:
        if pattern not in self._patterns:  # ^…$ is a whole-string match (Python's $ would also allow a final newline)
            anchored = pattern.startswith("^") and pattern.endswith("$") and not pattern.endswith("\\$")
            self._patterns[pattern] = (re.compile(pattern[1:-1] if anchored else pattern), anchored)
        rx, anchored = self._patterns[pattern]
        return bool(rx.fullmatch(v) if anchored else rx.search(v))

    def _check(self, v: Any, s: Any, path: str, out: list[dict[str, str]]) -> None:
        if not isinstance(s, dict):
            if s is False:
                out.append({"path": path or "/", "message": "no value is allowed here"})
            return
        where = path or "/"
        if "$ref" in s:
            ref = s["$ref"]
            if not ref.startswith("#/$defs/") or ref[8:] not in self.defs:
                raise ValueError(f"unknown schema reference {ref}")
            self._check(v, self.defs[ref[8:]], path, out)
        if "type" in s:
            types = s["type"] if isinstance(s["type"], list) else [s["type"]]
            if not any(_is(v, t) for t in types):
                out.append({"path": where, "message": f"expected {' or '.join(types)}, got {_kind(v)}"})
                return
        if "const" in s and not _same(v, s["const"]):
            out.append({"path": where, "message": f"must be {_canon(s['const'])}"})
        if "enum" in s and not any(_same(v, e) for e in s["enum"]):
            out.append({"path": where, "message": f"{_canon(v)[:80]} is not one of {', '.join(_canon(e) for e in s['enum'])}"})
        if isinstance(v, str):
            if len(v) < s.get("minLength", 0):
                out.append({"path": where, "message": f"shorter than {s['minLength']} characters"})
            if "maxLength" in s and len(v) > s["maxLength"]:
                out.append({"path": where, "message": f"longer than {s['maxLength']} characters"})
            if "pattern" in s and not self._match(s["pattern"], v):
                out.append({"path": where, "message": f"{v[:60]!r} does not match {s['pattern']}"})
        elif _is(v, "number"):
            if "minimum" in s and v < s["minimum"]:
                out.append({"path": where, "message": f"less than {s['minimum']}"})
            if "maximum" in s and v > s["maximum"]:
                out.append({"path": where, "message": f"greater than {s['maximum']}"})
        elif isinstance(v, list):
            if len(v) < s.get("minItems", 0):
                out.append({"path": where, "message": f"fewer than {s['minItems']} items"})
            if "maxItems" in s and len(v) > s["maxItems"]:
                out.append({"path": where, "message": f"more than {s['maxItems']} items"})
            if s.get("uniqueItems") and len({_canon(x) for x in v}) < len(v):
                out.append({"path": where, "message": "items are not unique"})
            if isinstance(s.get("items"), dict):
                for i, x in enumerate(v):
                    self._check(x, s["items"], f"{path}/{i}", out)
        elif isinstance(v, dict):
            for k in s.get("required") or []:
                if k not in v:
                    out.append({"path": where, "message": f"missing required property '{k}'"})
            props = s.get("properties") or {}
            extra = s.get("additionalProperties", True)
            for k, x in v.items():
                if k in props:
                    self._check(x, props[k], f"{path}/{k}", out)
                elif extra is False:
                    out.append({"path": where, "message": f"unexpected property '{k}'"})
                elif isinstance(extra, dict):
                    self._check(x, extra, f"{path}/{k}", out)
        for sub in s.get("allOf") or []:
            self._check(v, sub, path, out)
        if "anyOf" in s:
            tries = [self._errs(v, sub, path) for sub in s["anyOf"]]
            if all(tries):
                best = min(tries, key=len)
                out.append({"path": where, "message": "matches none of the alternatives (" + "; ".join(f"{e['path']}: {e['message']}" for e in best[:3]) + ")"})
        if "oneOf" in s:
            tries = [self._errs(v, sub, path) for sub in s["oneOf"]]
            ok = sum(1 for t in tries if not t)
            if ok == 0:
                best = min(tries, key=len)
                out.append({"path": where, "message": "matches none of the alternatives (" + "; ".join(f"{e['path']}: {e['message']}" for e in best[:3]) + ")"})
            elif ok > 1:
                out.append({"path": where, "message": "matches more than one alternative"})
        if "if" in s:
            branch = s.get("then") if not self._errs(v, s["if"], path) else s.get("else")
            if branch is not None:
                self._check(v, branch, path, out)


# ------------------------------------------------------------------ the rule language
def evaluate(expr: dict[str, Any], facts: dict[str, dict[str, Any]]) -> bool | None:
    """A rule condition, three-valued: True, False, or None (unresolved — a fact unknown, conflicting or not given)."""
    (op, arg), = expr.items()
    if op == "all":
        rs = [evaluate(x, facts) for x in arg]
        return False if any(r is False for r in rs) else (True if all(r is True for r in rs) else None)
    if op == "any":
        rs = [evaluate(x, facts) for x in arg]
        return True if any(r is True for r in rs) else (False if all(r is False for r in rs) else None)
    if op == "present":
        f = facts.get(arg)
        if f is None or f["status"] in ("unknown", "conflicting"):
            return None
        return f["status"] == "present"
    if op in ("eq", "in"):
        f = facts.get(arg["fact"])
        if f is None or f["status"] in ("unknown", "conflicting"):
            return None
        wanted = [arg["value"]] if op == "eq" else arg["values"]
        return any(_same(f.get("value"), w) for w in wanted)
    raise ValueError(f"operator {op!r} is not in the rule language")


def _facts_of(expr: dict[str, Any]) -> list[str]:
    (op, arg), = expr.items()
    if op in ("all", "any"):
        return [f for x in arg for f in _facts_of(x)]
    return [arg] if op == "present" else [arg["fact"]]


def _flag(value: bool) -> dict[str, Any]:
    return {"status": "present" if value else "absent", "value": bool(value)}


# ------------------------------------------------------------------ server-side review records
class ReviewStore:
    """Review records (``trustedReviewRecord``) held by the server, each with an HMAC-SHA256 over its canonical JSON under
    a key only the server has.  A record is used only when its signature verifies; binding to the request (case,
    version, the digest of the observations, the knowledge and rule versions, the role and mode) is checked by the
    coordinator.  Records are issued by a trusted host through :meth:`issue` (or loaded from the file named by
    ``TAOCHRONOS_REVIEW_STORE``, signed with ``TAOCHRONOS_REVIEW_KEY``) — never by a tool call."""

    def __init__(self, key: bytes | None = None) -> None:
        self._key = key
        self._records: dict[str, tuple[dict[str, Any], str]] = {}

    @classmethod
    def from_env(cls) -> ReviewStore:
        key = os.environ.get("TAOCHRONOS_REVIEW_KEY") or ""
        store = cls(key.encode("utf-8") if key else None)
        path = os.environ.get("TAOCHRONOS_REVIEW_STORE")
        if key and path and Path(path).is_file():
            for line in Path(path).read_text(encoding="utf-8").splitlines():
                if line.strip():
                    item = json.loads(line)
                    rec = item.get("record") or {}
                    if isinstance(rec.get("review_context_ref"), str) and isinstance(item.get("signature"), str):
                        store._records[rec["review_context_ref"]] = (rec, item["signature"])
        return store

    def _sign(self, record: dict[str, Any]) -> str:
        assert self._key is not None
        return hmac.new(self._key, _canon(record).encode("utf-8"), hashlib.sha256).hexdigest()

    def issue(self, record: dict[str, Any]) -> str:
        """Keep a record (server side): signed now, so that a later change to it is detected."""
        if self._key is None:
            raise ValueError("this review store has no key: it cannot issue records")
        rec = deepcopy(record)
        self._records[rec["review_context_ref"]] = (rec, self._sign(rec))
        return rec["review_context_ref"]

    def load(self, ref: str) -> dict[str, Any] | None:
        """The record behind a reference, or None (no such record, no key, or its signature does not verify)."""
        item = self._records.get(ref)
        if item is None or self._key is None:
            return None
        rec, sig = item
        return deepcopy(rec) if hmac.compare_digest(self._sign(rec), sig) else None


# ------------------------------------------------------------------ the coordinator
class _Run:
    """The state of one call."""

    def __init__(self, tool: str, args: dict[str, Any]) -> None:
        self.tool = tool
        self.args = args
        self.mode: str = args["mode"]
        self.case: dict[str, Any] | None = args.get("case")
        self.policy: dict[str, Any] = args.get("policy") or {}
        self.provided = "requested_methods" in args
        self.requested: list[str] = list(args.get("requested_methods") or [])
        self.obs: list[dict[str, Any]] = []
        self.read_count = 0
        self.superseded: list[str] = []
        self.states: list[dict[str, Any]] = []  # the organ states, with the entity for the methods
        self.claims: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.facts: dict[str, dict[str, Any]] = {}
        self.refs: dict[str, list[str]] = defaultdict(list)  # the observations a fact rests on
        self.details: dict[str, str] = {}  # the details a finding adds, by control fact
        self.candidate_refs: dict[str, list[str]] = defaultdict(list)
        self.missing: list[str] = []
        self.notes: list[dict[str, str]] = []
        self.relations: dict[str, dict[str, Any]] = {}
        self.trace: list[dict[str, Any]] = []
        self.review: dict[str, Any] = {"review_context_ref": args.get("review_context_ref"), "verified": False}
        self.reviewed: list[dict[str, Any]] = []  # organ states a verified record accepts
        self.patterns: list[dict[str, Any]] = []
        self.mappings: list[dict[str, Any]] = []
        self.candidates: list[dict[str, Any]] = []
        self.withheld = 0
        self.points: list[dict[str, Any]] = []
        self.sources: list[str] = []
        self.texts: list[tuple[str, str, str | None]] = []
        self.blocked: list[str] = []  # routing rules that hold (urgent or etiologic assessment first)
        self.effective: list[str] = []
        self.fired: list[str] = []
        self.plan: list[dict[str, Any]] = []
        self.method_records: list[tuple[dict[str, Any], dict[str, Any]]] = []
        self.strategy_rows: list[dict[str, Any]] = []
        self.blocked_extra: list[str] = []  # conclusions a finding blocks that only this request names

    @property
    def case_id(self) -> str | None:
        return (self.case or {}).get("case_id")

    @property
    def subject_ref(self) -> str:
        return (self.case or {}).get("case_subject_ref") or "subject.query"


class AcupunctureReasoning:
    """``study.acupuncture_reason`` (the coordinator) and ``study.acupuncture_audit`` (the independent audit)."""

    def __init__(self, study: AcupunctureStudy, *, reviews: ReviewStore | None = None) -> None:
        self.s = study
        self.reviews = reviews if reviews is not None else ReviewStore.from_env()
        self._pack: dict[str, Any] | None = None
        self._contracts: Contracts | None = None
        self._lexicon: dict[str, Any] | None = None
        self._versions: tuple[str, str] | None = None

    # ------------------------------------------------------------ data
    @property
    def fw(self) -> Any:
        return self.s.fw

    @property
    def contracts(self) -> Contracts:
        if self._contracts is None:
            path = Path(self.s.b.pack.root) / "acupuncture_contracts.schema.json"
            self._contracts = Contracts(json.loads(path.read_text(encoding="utf-8")))
        return self._contracts

    @property
    def pack(self) -> dict[str, Any]:
        if self._pack is None:
            pack = self.s.b.data("acupuncture_reasoning.yaml")
            if not pack.get("rules"):
                raise FileNotFoundError("acupuncture_reasoning.yaml: no rule pack")
            self.check_pack(pack)
            self._pack = pack
        return self._pack

    def _digest(self, *names: str) -> str:
        h = hashlib.sha256()
        for name in names:
            path = Path(self.s.b.pack.root) / name
            h.update(path.read_bytes() if path.is_file() else b"")
        return h.hexdigest()[:12]

    @property
    def knowledge_version(self) -> str:
        """The point and Five-Phase data's version with the digest of its file: a review given against one content of the
        data does not outlive an edit of it, bumped or not."""
        if self._versions is None:
            self._versions = (f"acupuncture@{self.fw.d.get('version', 'unversioned')}+{self._digest('acupuncture.yaml')}",
                              f"{self.pack.get('version')}+{self._digest('acupuncture_reasoning.yaml', 'acupuncture_contracts.schema.json')}")
        return self._versions[0]

    @property
    def rulepack_version(self) -> str:
        """The rule pack's version with the digest of the pack and its contracts."""
        self.knowledge_version  # noqa: B018
        return self._versions[1]  # type: ignore[index]

    def check_pack(self, pack: dict[str, Any]) -> None:
        """The rule pack's own consistency: every condition in the closed language, every fact it names declared
        (a concept, a claim, a control fact), every effect well-formed, every source registered."""
        allowed = set(pack.get("operators") or [])
        if not allowed <= {"all", "any", "eq", "in", "present"}:
            raise ValueError(f"rule pack: operators beyond the closed language: {sorted(allowed - {'all', 'any', 'eq', 'in', 'present'})}")
        known = set(pack.get("concepts") or {}) | set(pack.get("claims") or {}) | set(pack.get("controls") or {})
        sources = set(pack.get("sources") or {})
        statuses = set(self.contracts.defs["evaluatedAssessmentStatus"]["enum"])
        code = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]*$")
        seen: set[str] = set()

        def ops(expr: dict[str, Any]) -> set[str]:
            (op, arg), = expr.items()
            return {op} | ({o for x in arg for o in ops(x)} if op in ("all", "any") else set())

        for r in pack["rules"]:
            rid = r.get("id")
            if not rid or rid in seen:
                raise ValueError(f"rule pack: a rule without an id, or a repeated id: {rid}")
            seen.add(rid)
            errs = self.contracts.errors(r.get("when"), "dslExpression")
            if errs:
                raise ValueError(f"rule pack: {rid}: condition outside the rule language: {errs[0]['message']}")
            if not ops(r["when"]) <= allowed:
                raise ValueError(f"rule pack: {rid}: operator not allowed")
            unknown = [f for f in _facts_of(r["when"]) if f not in known]
            if unknown:
                raise ValueError(f"rule pack: {rid}: undeclared facts {unknown}")
            eff = r.get("effect") or {}
            if not code.match(eff.get("code", "")) or eff.get("severity") not in ("information", "clarification", "block") or not eff.get("message"):
                raise ValueError(f"rule pack: {rid}: malformed effect")
            if eff.get("status") is not None and eff["status"] not in statuses:
                raise ValueError(f"rule pack: {rid}: unknown assessment status {eff['status']}")
            bad = [x for x in r.get("sources") or [] if x not in sources]
            if bad:
                raise ValueError(f"rule pack: {rid}: unregistered sources {bad}")
        for cid, pats in (pack.get("claims") or {}).items():
            for p in pats:
                re.compile(p)

    # ------------------------------------------------------------ the text reader's lexicon
    def _norm(self, text: str) -> str:
        n = self.fw.normalize(text or "").lower()
        return n if len(n) == len(text or "") else (text or "").lower()

    @property
    def lexicon(self) -> dict[str, Any]:
        if self._lexicon is None:
            pack = self.pack
            names: list[tuple[str, str]] = []
            patterns: list[tuple[str, re.Pattern[str]]] = []
            denials: list[tuple[str, re.Pattern[str]]] = []
            for cid, c in (pack.get("concepts") or {}).items():
                for n in c.get("names") or []:
                    names.append((self._norm(n), cid))
                if c.get("pattern"):
                    patterns.append((cid, re.compile(c["pattern"])))
                for d in c.get("denials") or []:
                    denials.append((cid, re.compile(d, re.I)))
            names.sort(key=lambda x: -len(x[0]))
            claims = [(cid, re.compile(p, re.I)) for cid, ps in (pack.get("claims") or {}).items() for p in ps]
            self._lexicon = {"names": names, "patterns": patterns, "denials": denials, "claims": claims}
        return self._lexicon

    # ============================================================ entry points
    def reason(self, args: Any) -> dict[str, Any]:
        """``study.acupuncture_reason``: route, ask, compare the patterns, and give candidates only on a reviewed premise."""
        try:
            self.pack, self.fw.d  # noqa: B018 — the data the coordinator depends on
        except Exception as exc:  # noqa: BLE001 — a missing or malformed pack is reported, not raised
            return self._unavailable("reason", args, f"{type(exc).__name__}: {exc}")
        errs = self._argument_errors(args, "reasonParameters")
        if errs:
            return self._invalid("reason", args, errs)
        run = _Run("reason", args)
        try:
            self._prepare(run)
            self._route(run)
            self._select(run)
            self._compare(run)
            out = self._reason_out(run)
        except Exception as exc:  # noqa: BLE001
            return self._unavailable("reason", args, f"{type(exc).__name__}: {exc}")
        return self._seal(out, "reasonReturn", "reason", args)

    def audit(self, args: Any) -> dict[str, Any]:
        """``study.acupuncture_audit``: claims and a proposed plan checked against the rules and the point tables."""
        try:
            self.pack, self.fw.d  # noqa: B018
        except Exception as exc:  # noqa: BLE001
            return self._unavailable("audit", args, f"{type(exc).__name__}: {exc}")
        errs = self._argument_errors(args, "auditParameters")
        if errs:
            return self._invalid("audit", args, errs)
        run = _Run("audit", args)
        try:
            self._prepare(run)
            plan = self._plan(run)
            self._route(run)
            self._select(run)
            self._compare(run)
            out = self._audit_out(run, plan)
        except Exception as exc:  # noqa: BLE001
            return self._unavailable("audit", args, f"{type(exc).__name__}: {exc}")
        return self._seal(out, "auditReturn", "audit", args)

    def screen(self, text: str) -> dict[str, Any]:
        """The shared validation of a legacy, text-only, case-specific path (study.acupoints, study.wuxing): the text read
        as a case and routed by the same rules as the coordinator.  ``in_scope`` says whether it names a complaint the
        rule pack routes (tinnitus, hearing loss); ``withhold`` whether case-specific points must not be shown — when
        an urgent or etiologic assessment comes first, or (for an in-scope complaint) decision-critical information is
        still missing.  Nothing else of the legacy path changes: knowledge stays available."""
        args = {"mode": "case_review", "query": (text or "").strip() or "—",
                "case": {"case_id": "legacy.text", "case_version": 1, "is_synthetic": False, "observations": [], "organ_states": [],
                         "premise_claims": [], "source_messages": [{"message_id": "legacy.message", "text": text or "", "actor_kind": "patient"}],
                         "case_subject_ref": "subject.legacy"}}
        res = self.reason(args)
        status = res.get("assessment_status")
        complaints = set(self.pack.get("complaints") or {})
        obs = res.get("normalized_observations") or []
        in_scope = any(o["concept_id"] in complaints and o["status"] in ("present", "conflicting") and o["subject_scope"] == "current_case_subject"
                       and o["time"]["temporal_scope"] == "current" for o in obs)
        withhold = res["execution_status"] != "completed" or status in ("needs_urgent_assessment", "needs_etiologic_assessment") \
            or (in_scope and status == "needs_information")
        return {"tool": "study.acupuncture_reason", "result_id": res.get("result_id"), "execution_status": res["execution_status"],
                "assessment_status": status if in_scope or status in STATUS_RANK[:2] else "no_applicable_rule",
                "in_scope": in_scope, "withhold": withhold,
                "findings": [{k: f[k] for k in ("code", "severity", "message")} for f in res.get("findings") or []
                             if in_scope or f["severity"] == "block" or status in STATUS_RANK[:2]],
                "questions": res.get("questions") or [] if in_scope else [],
                "observations": [{"concept_id": o["concept_id"], "status": o["status"], "subject_scope": o["subject_scope"],
                                  "temporal_scope": o["time"]["temporal_scope"], "text": "".join(x["text"] for x in o["original_spans"])}
                                 for o in obs if not o["concept_id"].startswith("organ.")],
                "knowledge_version": res.get("knowledge_version"), "rulepack_version": res.get("rulepack_version")}

    def guard_selection(self, res: dict[str, Any], text: str) -> dict[str, Any]:
        """study.acupoints through the shared validation: the screen kept as ``validation``; when it withholds, the
        case-specific parts (the prescription, its combinations and alternatives, the record to fill) are withheld —
        said so, with what is missing — and the textual research (indications, rules, tables) stays."""
        v = self.screen(text)
        res["validation"] = v
        if v["withhold"]:
            pres = res.get("prescription") or {}
            n = len(pres.get("core") or []) + len(pres.get("supplementary") or [])
            res["prescription"] = {"core": [], "supplementary": [], "ashi": None, "deferred_pairs": [],
                                   "budget": pres.get("budget") or {"max_points": 6, "is_not_treatment_point_count": True},
                                   "withheld": {"points": n, "why": v["assessment_status"],
                                                "text": "共享的校验未通过：先" + ("就医评估" if v["assessment_status"] in STATUS_RANK[:2] else "回答所列的问题")
                                                        + "，此处不给出针对此人的选穴（文献与规则的部分照常）"}}
            res["combinations"], res["alternatives"], res["implementation"] = [], [], {}
            res.setdefault("summary", {})["points"] = 0
            res["summary"]["core"] = 0
        return res

    # ============================================================ arguments
    def _argument_errors(self, args: Any, name: str) -> list[dict[str, str]]:
        if not isinstance(args, dict):
            return [{"code": "INVALID_PARAMETERS", "path": "/", "message": "the arguments must be an object"}]
        errs = []
        for e in self.contracts.errors(args, name):
            code = "INVALID_METHOD" if e["path"].startswith("/requested_methods/") else "INVALID_PARAMETERS"
            m = re.match(r"unexpected property '(.+)'", e["message"])
            if m and m.group(1).lower() in TRUST_WORDS:
                e = {**e, "message": e["message"] + "：工具参数中的信任标记一律拒绝；审阅只能经服务器端核验的 review_context_ref"}
            errs.append({"code": code, **e})
        return errs + ([] if errs else self._structural(args))

    def _structural(self, args: dict[str, Any]) -> list[dict[str, str]]:
        """What the schema cannot say: spans within and equal to their message, references that exist, the organ of a
        state concept equal to its entity's."""
        out: list[dict[str, str]] = []
        case = args.get("case")
        if not case:
            return out
        msgs = {m["message_id"]: m["text"] for m in case["source_messages"]}
        if len(msgs) < len(case["source_messages"]):
            out.append({"code": "INVALID_PARAMETERS", "path": "/case/source_messages", "message": "repeated message_id"})
        msgs.setdefault("query", args["query"])
        ids = [o["observation_id"] for o in case["observations"]]
        if len(set(ids)) < len(ids):
            out.append({"code": "INVALID_PARAMETERS", "path": "/case/observations", "message": "repeated observation_id"})
        for i, o in enumerate(case["observations"]):
            for j, sp in enumerate(o["original_spans"]):
                where = f"/case/observations/{i}/original_spans/{j}"
                if sp["source_message_id"] not in msgs:
                    out.append({"code": "INVALID_PARAMETERS", "path": where, "message": f"refers to no source message: {sp['source_message_id']}"})
                elif (sp["start"] is None) != (sp["end"] is None):
                    out.append({"code": "INVALID_PARAMETERS", "path": where, "message": "start and end must both be given or both be null"})
                elif sp["start"] is not None and (sp["end"] < sp["start"] or msgs[sp["source_message_id"]][sp["start"]:sp["end"]] != sp["text"]):
                    out.append({"code": "INVALID_PARAMETERS", "path": where, "message": "the span's offsets do not give its text in its message"})
            src = o["provenance"].get("source_message_id")
            if src is not None and src not in msgs:
                out.append({"code": "INVALID_PARAMETERS", "path": f"/case/observations/{i}/provenance", "message": f"refers to no source message: {src}"})
            m = re.match(r"^organ\.([a-z_]+)\.", o["concept_id"])
            if m and m.group(1) in ORGAN_OF and o["entity"]["organ_entity"] not in (None, m.group(1)):
                out.append({"code": "INVALID_PARAMETERS", "path": f"/case/observations/{i}/entity",
                            "message": f"the concept names {m.group(1)}, the entity {o['entity']['organ_entity']}: one organ entity is not another"})
        known = set(ids)
        for i, st in enumerate(case["organ_states"]):
            bad = [r for r in st["observation_refs"] if r not in known]
            if bad:
                out.append({"code": "INVALID_PARAMETERS", "path": f"/case/organ_states/{i}", "message": f"refers to no observation: {', '.join(bad)}"})
        for i, pc in enumerate(case["premise_claims"]):
            bad = [r for r in pc["observation_refs"] if r not in known]
            if bad:
                out.append({"code": "INVALID_PARAMETERS", "path": f"/case/premise_claims/{i}", "message": f"refers to no observation: {', '.join(bad)}"})
        return out

    # ============================================================ normalization
    def _prepare(self, run: _Run) -> None:
        """The observations (the case's, and those read from its messages and the query that it does not already
        hold), the organ states, the claims, the subject and time of everything, and the control facts that follow."""
        case = run.case or {}
        run.obs = deepcopy(case.get("observations") or [])
        texts: list[tuple[str, str, str | None]] = [(m["message_id"], m["text"], m["actor_kind"]) for m in case.get("source_messages") or []]
        if run.args["query"].strip() and run.args["query"] not in [t for _, t, _ in texts]:
            texts.append(("query", run.args["query"], None))
        run.texts = texts
        default = self._default_subject(run)
        read: list[dict[str, Any]] = []
        for mid, text, actor in texts:
            read += self._read(run, text, mid, actor, default)
        given = list(run.obs)
        for i, o in enumerate(read):
            if self._covered(o, given):
                run.superseded.append(o["concept_id"])
                continue
            o["observation_id"] = f"{run.case_id or 'query'}.read{i + 1}"
            run.obs.append(o)
            run.read_count += 1
        for text in [t for _, t, _ in texts] + list(run.args.get("proposed_claims") or []):
            self._read_claims(run, text)
        for o in run.obs:
            if o["concept_id"].startswith("claim.") and o["status"] == "present":
                run.claims[o["concept_id"]].append({"observation_id": o["observation_id"], "text": "".join(s["text"] for s in o["original_spans"])})
                run.refs[o["concept_id"]].append(o["observation_id"])
        if any(pc["review_status"] == "claimed_accepted" or pc["reviewer_kind"] != "none" for pc in case.get("premise_claims") or []):
            run.claims["claim.review_asserted"].append({"observation_id": None, "text": "premise_claims（claimed_accepted / reviewer_kind）"})
        self._organ_states(run)
        current = [o for o in run.obs if self._is_current(o)]
        run.facts.update(self._concept_facts(run, current))
        for cid in self.pack.get("claims") or {}:
            run.facts[cid] = _flag(bool(run.claims.get(cid)))
        route = run.mode == "case_review" or bool(current)
        run.facts["control.clinical_case_route_required"] = _flag(route)
        apart = [o["observation_id"] for o in run.obs if o["subject_scope"] == "other_person" or o["time"]["temporal_scope"] == "past"]
        self._control(run, "control.noncurrent_facts_kept_apart", bool(apart), apart)
        self._control(run, "control.case_content_in_knowledge_mode", run.tool == "reason" and run.mode == "knowledge" and bool(current),
                      [o["observation_id"] for o in current])
        mismatch = [k for k, mine in (("knowledge_version", self.knowledge_version), ("rulepack_version", self.rulepack_version))
                    if run.args.get(k) not in (None, mine)]
        self._control(run, "control.version_mismatch", bool(mismatch), detail="、".join(mismatch))
        assumed = [s for s in run.states if s["assumed"]]
        self._control(run, "control.phase_label_assumed", bool(assumed), [r for s in assumed for r in s["refs"]])
        self._review(run)
        self._strategies(run)
        for pid in run.args.get("requested_points") or []:
            run.points.append(self._point_record(pid))
        self._control(run, "control.unknown_point", any(not p["known"] for p in run.points),
                      detail="、".join(p["input"] for p in run.points if not p["known"]))
        self._control(run, "control.alias_normalized", any(p["alias"] for p in run.points))
        run.trace.append(self._step(run, "normalize", [o["observation_id"] for o in run.obs], [], [],
                                    f"{len(run.obs)} 条观察（{len(case.get('observations') or [])} 条由个案给出，{run.read_count} 条由文本读出"
                                    + (f"，{len(run.superseded)} 条已由个案自己的观察涵盖" if run.superseded else "")
                                    + f"）；当前个案主体的当前所见 {len(current)} 条；脏腑状态 {len(run.states)} 个（脏腑与其方面分别保留）；"
                                    + f"文本中的主张 {sum(1 for v in run.claims.values() if v)} 种"))

    def _strategies(self, run: _Run) -> None:
        """A named strategy the text writes (滋水涵木 …) checked against the organ states as study.wuxing checks it: by
        organ entity and aspect — 肾阳虚 does not complete 滋水涵木, whose premise is 肾阴虚."""
        wx = self.fw.wx
        texts = " ".join(self._norm(t) for _, t, _ in run.texts) + " " + " ".join(self._norm(t) for t in run.args.get("proposed_claims") or [])
        named = [sid for sid, st in (wx.get("strategies") or {}).items() if self._norm(st["name"]) in texts]
        if not named:
            self._control(run, "control.strategy_premise_incomplete", False)
            return
        entries = [self._entity(s) for s in run.states if s["state"]["observation_status"] == "present"]
        fits = {r["id"]: r for r in self.s._wx_strategies(entries, [])}
        rows, short = [], []
        for sid in named:
            st = wx["strategies"][sid]
            r = fits.get(sid)
            fit = r["fit"] if r else "not_met"
            missing = r["missing"] if r else [st["premise"]]
            rows.append({"strategy": sid, "name": st["name"], "premise": st["premise"], "fit": fit, "missing": missing})
            if fit != "full":
                short.append(f"{st['name']}：仍缺{'、'.join(missing)}")
                run.blocked_extra.append(f"{st['name']}前提完整")
        run.strategy_rows = rows
        self._control(run, "control.strategy_premise_incomplete", bool(short), [r for s in run.states for r in s["refs"]], "；".join(short))

    def _default_subject(self, run: _Run) -> str:
        if run.mode == "case_review":
            return "current_case_subject"
        if run.mode == "method_compare" and any(o["subject_scope"] == "current_case_subject" and o["time"]["temporal_scope"] == "current"
                                                 for o in (run.case or {}).get("observations") or []):
            return "current_case_subject"
        return "hypothetical_subject"

    @staticmethod
    def _is_current(o: dict[str, Any]) -> bool:
        return o["subject_scope"] == "current_case_subject" and o["time"]["temporal_scope"] == "current" and not o["concept_id"].startswith("claim.")

    @staticmethod
    def _covered(o: dict[str, Any], given: list[dict[str, Any]]) -> bool:
        """A read observation the case already holds: the same concept for the same subject and time, or words of the
        same message the case has already taken."""
        for g in given:
            if g["concept_id"] == o["concept_id"] and g["subject_scope"] == o["subject_scope"] and g["time"]["temporal_scope"] == o["time"]["temporal_scope"]:
                return True
            for a in g["original_spans"]:
                for b in o["original_spans"]:
                    if (a["source_message_id"] == b["source_message_id"] and a["start"] is not None and b["start"] is not None
                            and a["start"] < b["end"] and b["start"] < a["end"] and g["concept_id"].split(".")[0] == o["concept_id"].split(".")[0]):
                        return True
        return False

    def _control(self, run: _Run, fact: str, value: bool, refs: Iterable[str] = (), detail: str = "") -> None:
        run.facts[fact] = _flag(value)
        if value:
            run.refs[fact] = list(dict.fromkeys(r for r in refs if r))
            if detail:
                run.details[fact] = detail

    # ------------------------------------------------------------ reading a text
    def _bounds(self, norm: str, start: int, end: int, marks: str) -> tuple[int, int]:
        a = max([norm.rfind(c, 0, start) for c in marks] + [-1]) + 1
        b = min([i for i in (norm.find(c, end) for c in marks) if i >= 0] + [len(norm)])
        return a, b

    def _words(self, words: Iterable[str], text: str) -> list[tuple[str, int]]:
        out = []
        for w in words:
            w = w.lower()
            rx = rf"(?<![a-z]){re.escape(w)}(?![a-z])" if w.isascii() else re.escape(w)
            out += [(w, m.start()) for m in re.finditer(rx, text)]
        return out

    def _read(self, run: _Run, text: str, mid: str, actor: str | None, default: str) -> list[dict[str, Any]]:
        """The observations a text writes: each concept's words with their status, subject, time and side (the cues of
        ``reading`` in acupuncture.yaml), the explicit denials, the organ states (study.wuxing's reading), and the timing
        facts that follow from words written next to them (只推出确有其词者)."""
        fw = self.fw
        lex = self.lexicon
        norm = self._norm(text)
        taken = [False] * len(norm)
        raw: list[dict[str, Any]] = []

        def free(a: int, b: int) -> bool:
            return not any(taken[a:b])

        def take(a: int, b: int) -> None:
            for i in range(a, b):
                taken[i] = True

        for cid, rx in lex["denials"]:
            for m in rx.finditer(norm):
                if free(m.start(), m.end()):
                    take(m.start(), m.end())
                    sc = fw.scope(norm, m.start(), m.end())  # 听力没有下降不清楚 stays unknown: a denial is not read over a stated doubt
                    raw.append({"cid": cid, "a": m.start(), "b": m.end(),
                                "scope": sc if sc["status"] == "unknown" else {**sc, "status": "absent", "cue": "denial"}})
        for name, cid in lex["names"]:
            rx = rf"(?<![a-z]){re.escape(name)}(?![a-z])" if name.isascii() else re.escape(name)
            for m in re.finditer(rx, norm):
                if free(m.start(), m.end()):
                    take(m.start(), m.end())
                    raw.append({"cid": cid, "a": m.start(), "b": m.end(), "scope": fw.scope(norm, m.start(), m.end())})
        for cid, rx in lex["patterns"]:
            for m in rx.finditer(norm):
                if free(m.start(), m.end()):
                    take(m.start(), m.end())
                    raw.append({"cid": cid, "a": m.start(), "b": m.end(), "scope": fw.scope(norm, m.start(), m.end())})
        raw.sort(key=lambda r: r["a"])
        out = [self._observation(run, text, norm, mid, actor, default, r["cid"], [(r["a"], r["b"])], r["scope"], inferred=False) for r in raw]
        out += self._derived(run, text, norm, mid, actor, default, out)
        for e in fw.phase_states(text)["states"]:
            out.append(self._state_observation(run, text, norm, mid, actor, default, e))
        return [o for o in out if o is not None]

    def _subject(self, run: _Run, norm: str, a: int, sc: dict[str, Any], default: str) -> tuple[str, str]:
        """(subject_scope, temporal_scope) of a finding."""
        rd = self.fw.d.get("reading") or {}
        ss, _ = self._bounds(norm, a, a, rd.get("sentence_marks", ""))
        if sc["subject"] == "other":
            subject = "other_person"
        elif sc["time"] == "hypothetical":
            subject = "hypothetical_subject"
        elif default != "current_case_subject" and run.tool == "reason" and self._words(rd.get("self_subject") or [], norm[ss:a]):
            subject = "current_case_subject"
        else:
            subject = default
        time = sc["time"] if sc["time"] in ("past", "hypothetical") else ("hypothetical" if subject == "hypothetical_subject" else "current")
        return subject, time

    def _observation(self, run: _Run, text: str, norm: str, mid: str, actor: str | None, default: str, cid: str,
                     spans: list[tuple[int, int]], sc: dict[str, Any], *, inferred: bool, value: Any = None, note: str | None = None) -> dict[str, Any]:
        c = (self.pack.get("concepts") or {}).get(cid) or {}
        subject, time = self._subject(run, norm, spans[0][0], sc, default)
        status = sc["status"]
        kind = c.get("kind", "symptom")
        ek = {"symptom": "symptom", "sign": "sign", "timing": "context", "context": "context", "report": "context"}.get(kind, "context")
        clause = self._bounds(norm, spans[0][0], spans[-1][1], (self.fw.d.get("reading") or {}).get("clause_marks", "") + (self.fw.d.get("reading") or {}).get("sentence_marks", ""))
        duration = self._duration(norm[clause[0]:clause[1]]) if kind == "symptom" else None
        prov = {"patient": "patient_report", "clinician": "clinician_input", "researcher": "literature",
                "synthetic_fixture": "synthetic_fixture"}.get(actor or "", "model_extraction")
        return {
            "observation_id": "pending",
            "concept_id": cid,
            "status": status,
            "value": None if status in ("unknown", "conflicting") else (value if value is not None else status == "present"),
            "entity": {"entity_kind": ek, "entity_id": cid, "organ_entity": None, "yin_yang_aspect": None},
            "time": {"observed_at": None, "onset_at": None, "duration_hours": duration[0] if duration and not duration[1] else None,
                     "timezone": None, "temporal_scope": time, "recorded_at": None, "valid_from": None, "valid_until": None},
            "context": {"scope": {"current": "current_case", "past": "past_history"}.get(time, "hypothetical"), "setting": None,
                        "note": note or (f"读自文本：{sc.get('cue')}" if sc.get("cue") else None)},
            "original_spans": [{"source_message_id": mid, "text": text[a:b], "start": a, "end": b, "offset_unit": "unicode_code_points"} for a, b in spans],
            "provenance": {"kind": prov, "actor_id": None, "source_message_id": mid, "source_refs": [], "is_inference": inferred,
                           "extraction_method": "taochronos.reading.v1"},
            "subject_ref": run.subject_ref if subject in ("current_case_subject", "hypothetical_subject") else f"other:{self._other_cue(norm, spans[0][0])}",
            "subject_scope": subject,
            "laterality": sc.get("laterality", "unknown") if kind in ("symptom", "sign") else "not_applicable",
        }

    def _other_cue(self, norm: str, a: int) -> str:
        rd = self.fw.d.get("reading") or {}
        ss, _ = self._bounds(norm, a, a, rd.get("sentence_marks", ""))
        hits = self._words(rd.get("other_subject") or [], norm[ss:a])
        return max(hits, key=lambda h: h[1])[0] if hits else "unknown"

    def _duration(self, clause: str) -> tuple[float, bool] | None:
        """A written length of time in a clause: (hours, whether it says “ago”)."""
        m = _DURATION.search(clause)
        if not m:
            return None
        n = m.group(1)
        if re.fullmatch(r"\d+(?:\.\d+)?", n):
            num = float(n)
        elif n in _EN_NUM:
            num = float(_EN_NUM[n])
        else:
            digit = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
            if n == "半":
                num = 0.5
            elif "十" in n:
                left, _, right = n.partition("十")
                num = (digit.get(left, 1) if left else 1) * 10 + (digit.get(right, 0) if right else 0)
            else:
                num = float(digit.get(n[0], 1))
        return num * _HOURS[m.group(2)], bool(m.group(3))

    def _derived(self, run: _Run, text: str, norm: str, mid: str, actor: str | None, default: str,
                 read: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Timing facts from the words written with a finding — only what the words say: 突然 by a hearing loss makes it
        sudden; 昨天, 两周前 date it; 逐渐 makes it not developed within 72 hours.  An explicit denial of hearing loss is
        also a denial of a sudden one.  What the text does not say stays unknown (no observation)."""
        timing = self.pack.get("timing") or {}
        rd = self.fw.d.get("reading") or {}
        marks_c, marks_s = rd.get("clause_marks", ""), rd.get("sentence_marks", "")
        have = {o["concept_id"] for o in read}
        out: list[dict[str, Any]] = []

        def span_of(o: dict[str, Any]) -> tuple[int, int]:
            return o["original_spans"][0]["start"], o["original_spans"][0]["end"]

        def make(cid: str, base: dict[str, Any], status: str, cue: tuple[str, int] | None, why: str) -> None:
            a, b = span_of(base)
            spans = sorted({(a, b)} | ({(cue[1], cue[1] + len(cue[0]))} if cue else set()))
            sc = {"status": status, "subject": "other" if base["subject_scope"] == "other_person" else "self",
                  "time": {"current": "current", "past": "past"}.get(base["time"]["temporal_scope"], "hypothetical"),
                  "laterality": base["laterality"], "cue": cue[0] if cue else None}
            o = self._observation(run, text, norm, mid, actor, default, cid, spans, sc, inferred=True, note=why)
            o["subject_scope"], o["subject_ref"] = base["subject_scope"], base["subject_ref"]
            o["time"]["temporal_scope"] = base["time"]["temporal_scope"]
            o["context"]["scope"] = base["context"]["scope"]
            out.append(o)
            have.add(cid)

        def recency(sentence: str, offset: int) -> tuple[float, tuple[str, int]] | None:
            hits = [(timing["recent"][w], (w, offset + at)) for w, at in self._words(timing.get("recent") or {}, sentence)]
            d = self._duration(sentence)
            if d:
                m = _DURATION.search(sentence)
                hits.append((d[0], (m.group(0), offset + m.start())))
            return min(hits, key=lambda h: h[0]) if hits else None

        for o in list(read):
            if o["concept_id"] not in ("hearing.loss", "hearing.sudden_loss", "symptom.tinnitus"):
                continue
            a, b = span_of(o)
            cs, ce = self._bounds(norm, a, b, marks_c + marks_s)
            ss, se = self._bounds(norm, a, b, marks_s)
            clause, sentence = norm[cs:ce], norm[ss:se]
            sudden = self._words(timing.get("sudden") or [], clause)
            sudden_cue = (sudden[0][0], cs + sudden[0][1]) if sudden else None
            if o["concept_id"] == "hearing.loss" and "hearing.sudden_loss" not in have:
                slow = self._words(timing.get("gradual") or [], clause)
                if o["status"] == "absent":
                    make("hearing.sudden_loss", o, "absent", None, "否认听力下降，亦即否认突发的听力下降")
                elif o["status"] == "present" and sudden_cue:
                    make("hearing.sudden_loss", o, "present", sudden_cue, f"“{sudden_cue[0]}”写在听力下降之旁")
                elif o["status"] == "present" and slow:
                    make("hearing.sudden_loss", o, "absent", (slow[0][0], cs + slow[0][1]), f"“{slow[0][0]}”：逐渐形成，不是突发")
            if o["concept_id"] == "hearing.sudden_loss" and o["status"] == "present" and "hearing.loss" not in have:
                make("hearing.loss", o, "present", None, "突发的听力下降亦是听力下降")
            if o["concept_id"] == "symptom.tinnitus" and o["status"] == "present":
                if sudden_cue and "tinnitus.sudden_onset" not in have:
                    make("tinnitus.sudden_onset", o, "present", sudden_cue, f"“{sudden_cue[0]}”写在耳鸣之旁")
                side = o["laterality"] in ("left", "right")
                lasting = self._words(timing.get("persistent") or [], clause)
                d = self._duration(clause)
                if side and (lasting or (d and not d[1] and d[0] >= float(timing.get("persistent_hours", 336)))) and "tinnitus.persistent_unilateral" not in have:
                    make("tinnitus.persistent_unilateral", o, "present", (lasting[0][0], cs + lasting[0][1]) if lasting else None,
                         "单侧，且写明持续或时长达两周")
        for o in [x for x in read + out if x["concept_id"] == "hearing.sudden_loss" and x["status"] == "present"]:
            a, b = span_of(o)
            ss, se = self._bounds(norm, a, b, marks_s)
            sentence = norm[ss:se]
            rec = recency(sentence, ss)
            remote = self._words(timing.get("remote") or [], sentence)
            if "hearing.onset_within_past_30_days" not in have:
                if rec and rec[0] <= 720:
                    make("hearing.onset_within_past_30_days", o, "present", rec[1], f"“{rec[1][0]}”：起于 30 天之内")
                elif rec or remote:
                    cue = rec[1] if rec else (remote[0][0], ss + remote[0][1])
                    make("hearing.onset_within_past_30_days", o, "absent", cue, f"“{cue[0]}”：起于 30 天之前")
            if "hearing.developed_within_72_hours" not in have:
                quick = self._words(timing.get("within_72_hours") or [], sentence)
                slow = self._words(timing.get("gradual") or [], sentence)
                if quick:
                    make("hearing.developed_within_72_hours", o, "present", (quick[0][0], ss + quick[0][1]), f"“{quick[0][0]}”：3 天之内形成")
                elif slow:
                    make("hearing.developed_within_72_hours", o, "absent", (slow[0][0], ss + slow[0][1]), f"“{slow[0][0]}”：逐渐形成")
                elif rec and rec[0] <= 72:
                    make("hearing.developed_within_72_hours", o, "present", rec[1], f"突然、且起于“{rec[1][0]}”：不过 3 天")
        return out

    def _state_observation(self, run: _Run, text: str, norm: str, mid: str, actor: str | None, default: str,
                           e: dict[str, Any]) -> dict[str, Any]:
        """An organ state study.wuxing reads (肝实, 肾阳虚, 肝郁脾虚, 木实 — the last only as an assumption) as an
        observation that keeps the organ entity and the aspect."""
        organ = ORGAN_ID[e["organ"]]
        aspect = e["aspect"] if e["aspect"] in ASPECTS else "unspecified"
        state = STATE_ID.get(e["state"], "unknown")
        a, b = e["span"]
        sc = {"status": "unknown" if state == "unknown" else ("conflicting" if state == "conflicting" else "present"),
              "subject": "self", "time": e.get("time") or "current", "laterality": "not_applicable", "cue": None}
        note = (f"由“{e['phase']}”推定为{e['organ']}：推定不是诊察所见" if e.get("assumed") else None) or e.get("note") \
            or (f"出自所给之证“{e['pattern']}”" if e.get("pattern") else None)
        cid = f"organ.{organ}.state" if aspect == "unspecified" else f"organ.{organ}.{aspect}.state"
        o = self._observation(run, text, norm, mid, actor, default, cid, [(a, b)], sc, inferred=bool(e.get("assumed")),
                              value=state if sc["status"] == "present" else None, note=note)
        o["entity"] = {"entity_kind": "functional_aspect", "entity_id": f"zangfu.{organ}", "organ_entity": organ, "yin_yang_aspect": aspect}
        o["laterality"] = "not_applicable"
        o["provenance"]["extraction_method"] = "taochronos.reading.v1+study.wuxing.phase_states"
        return o

    def _read_claims(self, run: _Run, text: str) -> None:
        norm = self._norm(text)
        for cid, rx in self.lexicon["claims"]:
            m = rx.search(norm)
            if m:
                run.claims[cid].append({"observation_id": None, "text": text[m.start():m.end()]})

    # ------------------------------------------------------------ organ states
    def _organ_states(self, run: _Run) -> None:
        """The case's organ states, and those its observations name that it does not list — each kept by organ entity
        and aspect (a shared phase never merges two); others' and past states are not the case's."""
        fw = self.fw
        by_obs = {o["observation_id"]: o for o in run.obs}
        listed = deepcopy((run.case or {}).get("organ_states") or [])
        covered = {r for st in listed for r in st["observation_refs"]}
        rx = re.compile(r"^organ\.([a-z_]+)(?:\.(yin|yang|qi|blood|essence|fluid_processing|unspecified))?\.(state|excess|deficiency|mixed|balanced|neither_excess_nor_deficiency|unknown|conflicting)$")
        for o in run.obs:
            m = rx.match(o["concept_id"])
            if not m or o["observation_id"] in covered or o["subject_scope"] == "other_person" or o["time"]["temporal_scope"] == "past":
                continue
            organ = o["entity"]["organ_entity"] or m.group(1)
            if organ not in ORGAN_OF:
                continue
            aspect = o["entity"]["yin_yang_aspect"] or m.group(2) or "unspecified"
            if o["status"] in ("unknown", "conflicting"):
                state = o["status"]
            elif m.group(3) == "state":
                state = o["value"] if isinstance(o["value"], str) and o["value"] in STATE_OF else "unknown"
            elif o["status"] == "present" and o["value"] is not False:
                state = m.group(3)
            else:
                continue  # 肾阳虚: absent says only that it is not so — no state follows
            listed.append({"organ_entity": organ, "yin_yang_aspect": aspect, "state": state,
                           "observation_status": o["status"] if state not in ("unknown",) else "unknown",
                           "observation_refs": [o["observation_id"]], "phase_annotation": None, "phase_annotation_origin": "unresolved"})
        out = []
        for st in listed:
            ch = fw.organs[ORGAN_OF[st["organ_entity"]]]["channel"]
            phase = fw.channels[ch]["phase"]
            if st.get("phase_annotation") is None:
                st["phase_annotation"], st["phase_annotation_origin"] = PHASE_ID[phase], "study.acupoints_framework"
            refs = st["observation_refs"]
            obs = [by_obs[r] for r in refs if r in by_obs]
            hypothetical = bool(obs) and all(o["subject_scope"] == "hypothetical_subject" or o["time"]["temporal_scope"] == "hypothetical" for o in obs)
            assumed = any(o["provenance"]["is_inference"] and o["provenance"]["extraction_method"].endswith("phase_states") for o in obs)
            spans = [s for o in obs for s in o["original_spans"]]
            run.states.append({"state": st, "organ": ORGAN_OF[st["organ_entity"]], "channel": ch, "phase": phase, "refs": refs,
                               "hypothetical": hypothetical or not obs and run.mode != "case_review", "assumed": assumed, "spans": spans})
            out.append(st)

    # ------------------------------------------------------------ facts
    def _concept_facts(self, run: _Run, current: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Each concept's state for the case's subject now: present and absent together are conflicting; unknown leaves it
        as it is; a concept not written at all is no fact (unresolved)."""
        by: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for o in current:
            by[o["concept_id"]].append(o)
        out: dict[str, dict[str, Any]] = {}
        for cid, xs in by.items():
            st = {o["status"] for o in xs}
            if "conflicting" in st or {"present", "absent"} <= st:
                status = "conflicting"
            elif "present" in st:
                status = "present"
            elif "absent" in st:
                status = "absent"
            else:
                status = "unknown"
            value = next((o["value"] for o in xs if o["status"] == status), None) if status in ("present", "absent") else None
            out[cid] = {"status": status, "value": value}
            run.refs[cid] = [o["observation_id"] for o in xs]
        return out

    # ------------------------------------------------------------ the review record
    def _review(self, run: _Run) -> None:
        """A review_context_ref is only a reference: the record is loaded and verified here, and bound to this request."""
        ref = run.args.get("review_context_ref")
        flags = {"control.trusted_review_verified": False, "control.review_context_unverified": False,
                 "control.stale_review_context": False, "control.review_not_authorized": False}
        if ref:
            rec = self.reviews.load(ref)
            checks: dict[str, bool] = {}
            if rec is None or self.contracts.errors(rec, "trustedReviewRecord"):
                flags["control.review_context_unverified"] = True
                run.details["control.review_context_unverified"] = ref
            else:
                case = run.case or {}
                checks = {"case_id": rec["case_id"] == case.get("case_id"), "case_version": rec["case_version"] == case.get("case_version"),
                          "normalized_observations_sha256": rec["normalized_observations_sha256"] == observations_digest(case.get("observations")),
                          "knowledge_version": rec["knowledge_version"] == self.knowledge_version,
                          "rulepack_version": rec["rulepack_version"] == self.rulepack_version}
                roles = {"clinician": ("case_review", "method_compare"), "domain_reviewer": ("method_compare", "knowledge")}
                checks["authorized_mode"] = run.mode in rec["authorized_modes"] and run.mode in roles[rec["authorized_role"]]
                if not all(v for k, v in checks.items() if k != "authorized_mode"):
                    flags["control.stale_review_context"] = True
                    run.details["control.stale_review_context"] = "、".join(k for k, v in checks.items() if not v and k != "authorized_mode")
                elif not checks["authorized_mode"]:
                    flags["control.review_not_authorized"] = True
                    run.details["control.review_not_authorized"] = f"{rec['authorized_role']} → {run.mode}"
                else:
                    flags["control.trusted_review_verified"] = True
                    for s in run.states:
                        st = s["state"]
                        for c in rec["reviewed_conditions"]:
                            if (c["organ_entity"], c["yin_yang_aspect"], c["state"]) == (st["organ_entity"], st["yin_yang_aspect"], st["state"]) \
                                    and st["observation_status"] == "present":
                                run.reviewed.append({"entity": s, "premise_id": c["premise_id"], "clinical_condition": c["clinical_condition"]})
                run.review.update({"authorized_role": rec["authorized_role"], "issuer_principal_ref": rec["issuer_principal_ref"]})
            run.review.update({"verified": flags["control.trusted_review_verified"], "binding": checks,
                               "accepted_premises": [r["premise_id"] for r in run.reviewed]})
        for k, v in flags.items():
            self._control(run, k, v, detail=run.details.get(k, ""))

    # ============================================================ routing and what is missing
    def _route(self, run: _Run) -> None:
        """The routing rules, and the decision-critical information still missing — for the case's subject now only."""
        pack = self.pack
        route = run.facts["control.clinical_case_route_required"]["value"]
        missing: list[str] = []
        if route:
            current = {cid for cid, f in run.facts.items() if not cid.startswith(("claim.", "control.")) and f["status"] in ("present", "conflicting")}
            concepts = pack.get("concepts") or {}
            symptoms = [cid for cid in current if (concepts.get(cid) or {}).get("kind") in ("symptom", "sign") and run.facts[cid]["status"] == "present"]
            real_states = any(s["state"]["observation_status"] == "present" and not s["hypothetical"] for s in run.states)
            if not symptoms and (run.mode == "case_review" or not real_states):
                missing.append("complaint")
            queue = [cid for cid in (pack.get("complaints") or {}) if (run.facts.get(cid) or {}).get("status") in ("present", "conflicting")]
            seen: set[str] = set()
            while queue:
                cid = queue.pop(0)
                if cid in seen:
                    continue
                seen.add(cid)
                if run.facts[cid]["status"] == "conflicting":
                    missing.append(cid)
                for need in ((pack.get("complaints") or {}).get(cid) or {}).get("decision_critical") or []:
                    st = (run.facts.get(need) or {}).get("status")
                    if st in (None, "unknown", "conflicting"):
                        missing.append(need)
                    elif st == "present" and need in (pack.get("complaints") or {}):
                        queue.append(need)
            out_of_scope = [cid for cid in symptoms if cid not in (pack.get("complaints") or {}) and not cid.startswith(("tinnitus.", "hearing."))
                            and cid not in {x for p in (pack.get("patterns") or {}).get("tinnitus") or [] for x in p["supports"] + p["opposes"]}]
            in_scope = [cid for cid in symptoms if cid in (pack.get("complaints") or {})]
            self._control(run, "control.complaint_out_of_scope", bool(out_of_scope) and not in_scope,
                          [r for c in out_of_scope for r in run.refs.get(c, [])], detail="、".join((concepts.get(c) or {}).get("zh", c) for c in out_of_scope))
        else:
            self._control(run, "control.complaint_out_of_scope", False)
        run.missing = list(dict.fromkeys(missing))
        self._set_missing(run)
        run.blocked = [r["id"] for r in self._fired(run, kinds=("routing_guard",)) if (r["effect"].get("status") or "") in STATUS_RANK[:2]]
        self._control(run, "control.routing_decided", bool(run.blocked))

    def _set_missing(self, run: _Run) -> None:
        concepts = self.pack.get("concepts") or {}
        label = lambda c: {"complaint": "当前的主诉", "premise": "已审阅的取穴前提", "state": "明确的虚实"}.get(c, (concepts.get(c) or {}).get("zh", c))  # noqa: E731
        refs = [r for c in run.missing for r in run.refs.get(c, [])]
        for cid in ("symptom.tinnitus", "hearing.loss", "hearing.sudden_loss"):
            if any(m in ((self.pack.get("complaints") or {}).get(cid) or {}).get("decision_critical", []) for m in run.missing):
                refs += run.refs.get(cid, [])
        detail = "仍缺：" + "、".join(label(c) for c in run.missing) if run.missing else ""
        if "hearing.onset_within_past_30_days" in run.missing or "hearing.developed_within_72_hours" in run.missing:
            detail += "——若听力下降起于近 30 天、在 3 天内形成，须在 24 小时内就医评估"
        self._control(run, "control.missing_decision_critical_information", bool(run.missing), refs, detail)

    def _fired(self, run: _Run, kinds: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
        rules = [r for r in self.pack["rules"] if kinds is None or r.get("kind") in kinds]
        return [r for r in sorted(rules, key=lambda r: -int(r.get("priority", 0))) if evaluate(r["when"], run.facts) is True]

    # ============================================================ methods: candidates and mappings
    def _select(self, run: _Run) -> None:
        """The methods requested (none when omitted or empty; never all), allowed by the policy, run on each organ state
        whose state meets their premise — as candidates where a verified review accepts that state and nothing in the
        routing blocks, as educational mappings where there is no real case and no review was asked for."""
        pack = self.pack
        policy = run.policy
        allowed, refused = [], []
        for m in dict.fromkeys(run.requested):
            need = ((pack.get("methods") or {}).get(m) or {}).get("policy")
            (allowed if not need or policy.get(need) is True else refused).append(m)
        run.effective = allowed
        self._control(run, "control.method_not_allowed", bool(refused), detail="、".join(refused))
        relation_only = [m for m in allowed if m in RELATION_ONLY]
        self._control(run, "control.relation_only_method", bool(relation_only), detail="、".join(relation_only))
        wanted = [m for m in allowed if m in WUXING_METHODS]
        route = run.facts["control.clinical_case_route_required"]["value"]
        educational = not route and not run.args.get("review_context_ref")
        held = [s for s in run.states if s["state"]["state"] not in ("excess", "deficiency", "neither_excess_nor_deficiency")
                or s["state"]["observation_status"] != "present"]
        records: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for s in run.states:
            if s in held:
                continue
            e = self._entity(s)
            for m in wanted:
                for rec in self.s._wx_methods(e, [m]):
                    records.append((s, rec))
        self._control(run, "control.method_premise_unmet", bool(wanted) and not records,
                      [r for s in held for r in s["refs"]], detail="、".join(f"{s['organ']}（{s['state']['state']}）" for s in held))
        if wanted and not records:
            run.missing.append("state")
        run.method_records = records
        if run.tool == "audit":  # the audit compares a plan with what the methods give; it gives no candidates itself
            self._control(run, "control.candidate_requires_review", False)
            self._control(run, "control.methods_differ_in_intent", False)
            self._set_missing(run)
            return
        reviewed = {id(r["entity"]): r for r in run.reviewed}
        need_review = bool(wanted) and (route or bool(run.args.get("review_context_ref"))) and not any(id(s) in reviewed for s, _ in records)
        self._control(run, "control.candidate_requires_review", need_review, [r for s, _ in records for r in s["refs"]])
        if need_review and route:
            run.missing.append("premise")
        run.missing = list(dict.fromkeys(run.missing))
        self._set_missing(run)
        blocked = bool(run.blocked) or bool(run.missing)
        for s, rec in records:
            if id(s) in reviewed and not blocked:
                run.candidates += self._candidates(run, s, rec, reviewed[id(s)])
            elif id(s) in reviewed:
                run.withheld += len(rec["points"])
            elif educational and s["hypothetical"] and s["spans"]:
                run.mappings += self._mappings(s, rec)
        intents: dict[str, set[str]] = defaultdict(set)
        for c in run.candidates:
            intents[c["point_id"]].add(c["intent"]["traditional_manipulation"])
        opposed = sorted(p for p, xs in intents.items() if {"tonify", "reduce"} <= xs)
        self._control(run, "control.opposed_intentions", bool(opposed), detail="、".join(opposed))
        if opposed:  # merged candidates that tonify and reduce one point are not averaged: none is shown
            run.candidate_refs["control.opposed_intentions"] = opposed
            run.withheld += len(run.candidates)
            run.candidates = []
        m_intents: dict[str, set[str]] = defaultdict(set)
        for mp in run.mappings:
            m_intents[mp["point_id"]].add(mp["intent"]["traditional_manipulation"])
        differ = sorted(p for p, xs in m_intents.items() if {"tonify", "reduce"} <= xs)
        self._control(run, "control.methods_differ_in_intent", bool(differ), detail="、".join(differ))
        if differ:
            run.candidate_refs["control.methods_differ_in_intent"] = differ
        for s in run.states:
            for m in relation_only:
                self._relations_for_method(run, s, m)
        for s, _ in records:  # 虚者补其母 (the mother generates it), 实者泻其子 (it generates the child)
            st = s["state"]["state"]
            if st in ("excess", "deficiency"):
                a, b = (MOTHER[s["phase"]], s["phase"]) if st == "deficiency" else (s["phase"], GENERATES[s["phase"]])
                self._relation(run, "generates", f"phase.{PHASE_ID[a]}", f"phase.{PHASE_ID[b]}", ["src_nanjing"])
        run.trace.append(self._step(run, "method_selection", [r for s in run.states for r in s["refs"]],
                                    [f"reasoning.methods.{m}" for m in allowed], sorted({x for m in allowed for x in ((pack.get("methods") or {}).get(m) or {}).get("rule_source", [])}),
                                    ("未请求方法（省略与 [] 相同）：不运行任何取穴方法，也不回退到全部" if not run.requested else
                                     f"请求 {'、'.join(run.requested)}；policy 允许 {'、'.join(allowed) or '无'}"
                                     + (f"；未允许 {'、'.join(refused)}" if refused else "")
                                     + f"；{len(records)} 条方法记录，{len(held)} 个状态不满足前提而不取")
                                    + (f"；候选 {len(run.candidates)}（已审阅的前提）" if run.candidates else "")
                                    + (f"；暂不显示 {run.withheld} 个（分流或冲突）" if run.withheld else "")
                                    + (f"；教学映射 {len(run.mappings)}（假设的前提，不涉及任何人）" if run.mappings else "")))
        run.trace.append(self._step(run, "legacy_lookup", [], [f"acupuncture.rules.{rec['rule']}" for _, rec in records][:20], [],
                                    "方法的穴与补泻取自 study.wuxing 的同一计算，穴的经脉、五输与五行取自 study.point 的固定穴位表"))

    def _entity(self, s: dict[str, Any]) -> dict[str, Any]:
        st = s["state"]
        state = STATE_OF.get(st["state"], st["state"])
        wx = self.fw.wx
        return {"phase": s["phase"], "organ": s["organ"], "channel": s["channel"], "state": state, "aspect": st["yin_yang_aspect"],
                "state_name": ((wx.get("states") or {}).get(state) or {}).get("name", ""), "pattern": None, "note": None, "assumed": s["assumed"]}

    def _point_attrs(self, code: str) -> dict[str, Any]:
        fw = self.fw
        p = fw.points[code]
        ch = p["channel"]
        cat = next((c for c in fw.categories(code) if c["type"] == "five_shu"), None)
        return {"point_id": code, "name_zh": p["name"], "channel": ch, "channel_phase": PHASE_ID.get((fw.channels.get(ch) or {}).get("phase")),
                "point_phase": PHASE_ID.get(cat["phase"]) if cat else None, "five_shu_class": cat["kind"] if cat else None}

    def _support(self, method: str, rec: dict[str, Any]) -> dict[str, Any]:
        m = (self.pack.get("methods") or {}).get(method) or {}
        return {"level": m.get("level", rec.get("level", "classical")), "source_refs": list(m.get("rule_source") or []),
                "rule_refs": [f"reasoning.methods.{method}", f"acupuncture.rules.{rec['rule']}"],
                "scope_note": f"{rec['name']}：{rec['selection']}（{rec['relationship']}）——理论的出处，不是对此人的诊断或处方"}

    @staticmethod
    def _efficacy() -> dict[str, Any]:
        return {"status": "not_established_for_rule", "source_refs": ["src_vadod_2024"], "applicability_note": EFFICACY_NOTE,
                "does_not_validate_theory_automatically": True}

    def _intent(self, method: str, state: str, intent: str | None) -> dict[str, Any]:
        principle = PRINCIPLE.get((method, state)) or (f"saam.{'tonify' if intent == '补' else 'sedate'}" if method == "saam" else f"{method}.{state}")
        return {"traditional_manipulation": INTENT_ID.get(intent or "", "undetermined"), "treatment_principle": principle, "not_a_procedure_order": True}

    def _candidates(self, run: _Run, s: dict[str, Any], rec: dict[str, Any], reviewed: dict[str, Any]) -> list[dict[str, Any]]:
        state = STATE_OF.get(s["state"]["state"], s["state"]["state"])
        out = []
        for p in rec["points"]:
            out.append({**self._point_attrs(p["code"]), "input_aliases": [], "intent": self._intent(rec["method"], state, p.get("intent")),
                        "modality": "undetermined", "modality_status": "requires_separate_assessment", "method_id": rec["method"],
                        "premise_refs": [reviewed["premise_id"], *s["refs"]], "theory_support": self._support(rec["method"], rec),
                        "clinical_efficacy": self._efficacy(), "lookup_tool": "study.point", "usage_scope": "candidate_review_only"})
        return out

    def _mappings(self, s: dict[str, Any], rec: dict[str, Any]) -> list[dict[str, Any]]:
        st = s["state"]
        state = STATE_OF.get(st["state"], st["state"])
        out = []
        for p in rec["points"]:
            attrs = self._point_attrs(p["code"])
            out.append({"mapping_id": f"edu.{rec['method']}.{st['organ_entity']}.{st['yin_yang_aspect']}.{st['state']}.{p['code']}",
                        "hypothetical_premise": {"organ_entity": st["organ_entity"], "yin_yang_aspect": st["yin_yang_aspect"], "state": st["state"],
                                                 "assertion_kind": "explicit_educational_hypothesis", "clinical_truth_status": "not_asserted",
                                                 "original_spans": deepcopy(s["spans"][:3])},
                        **{k: attrs[k] for k in ("point_id", "name_zh", "channel", "channel_phase", "point_phase", "five_shu_class")},
                        "intent": self._intent(rec["method"], state, p.get("intent")), "modality": "undetermined", "method_id": rec["method"],
                        "theory_support": self._support(rec["method"], rec), "clinical_efficacy": self._efficacy(),
                        "usage_scope": "educational_mapping_only", "runtime_clinical_action": "none", "not_patient_specific": True})
        return out

    # ------------------------------------------------------------ typed relations
    def _relation(self, run: _Run, rtype: str, a: str, b: str, sources: list[str], rid: str | None = None) -> None:
        rid = rid or f"{rtype}.{a.split('.')[-1]}.{b.split('.')[-1]}"
        run.relations.setdefault(rid, {"relation_id": rid, "relation_type": rtype, "from_entity": a, "to_entity": b, "transitive": False,
                                       "clinical_action": "none_without_independent_selection_rule", "source_refs": sources})

    def _relations_for_method(self, run: _Run, s: dict[str, Any], method: str) -> None:
        organ = s["state"]["organ_entity"]
        if method == "bietong":
            for r in (self.pack.get("relations") or {}).get("bietong") or []:
                if organ in (r["from"], r["to"]):
                    self._relation(run, "bietong", f"zangfu.{r['from']}", f"zangfu.{r['to']}", ["src_yixue_rumen"])
        elif method == "yuan_luo":
            self._yuan_luo(run, s["channel"])

    def _yuan_luo(self, run: _Run, ch: str) -> None:
        fw = self.fw
        partner = (fw.channels.get(ch) or {}).get("partner")
        d = fw.d
        if not partner:
            return
        self._relation(run, "interior_exterior", f"meridian.{ch}", f"meridian.{partner}", ["src_cijiu_xinfa"])
        for host, guest in ((ch, partner), (partner, ch)):
            yuan, luo = (d.get("yuan") or {}).get(host), (d.get("luo") or {}).get(guest)
            if yuan and luo:
                self._relation(run, "yuan_luo", f"point.{yuan}", f"point.{luo}", ["src_cijiu_xinfa"])

    def _context_relations(self, run: _Run, codes: Iterable[str] = ()) -> None:
        """The relations a request bears on: the ear's (organ–orifice, channel course) when tinnitus or hearing is
        named; Kidney–Sanjiao as 别通 with the real interior–exterior and Yuan–Luo pairings beside it when a claim
        confuses them; the interior–exterior partner of each channel in a plan; the analogy, as an analogy."""
        rel = self.pack.get("relations") or {}
        named = {o["concept_id"] for o in run.obs}
        if named & {"symptom.tinnitus", "hearing.loss", "hearing.sudden_loss", "tinnitus.pulsatile"}:
            for r in rel.get("organ_orifice") or []:
                self._relation(run, "organ_orifice", f"zangfu.{r['from']}", f"body_region.{r['to']}", r.get("sources") or [])
            for r in rel.get("channel_course") or []:
                self._relation(run, "channel_course", f"meridian.{self.fw.organs[ORGAN_OF[r['from']]]['channel']}", f"body_region.{r['to']}", r.get("sources") or [])
        if run.claims.get("claim.kidney_sanjiao_is_yuan_luo") or run.claims.get("claim.bietong_transitive"):
            self._relation(run, "bietong", "zangfu.kidney", "zangfu.sanjiao", ["src_yixue_rumen"])
            self._yuan_luo(run, "KI")
            self._yuan_luo(run, "TE")
        for code in codes:
            ch = self.fw.points[code]["channel"] if code in self.fw.points else None
            partner = (self.fw.channels.get(ch) or {}).get("partner") if ch else None
            if partner:
                self._relation(run, "interior_exterior", f"meridian.{ch}", f"meridian.{partner}", ["src_cijiu_xinfa"])
        texts = " ".join(self._norm(t) for _, t, _ in run.texts) + " " + " ".join(self._norm(t) for t in run.args.get("proposed_claims") or [])
        for an in self.pack.get("analogies") or []:
            if self._words(an["source_terms"], texts) and self._words(an["target_terms"], texts):
                self._relation(run, "analogy", "metaphor.window_paper", "body_region.eardrum", an.get("sources") or [], rid=an["id"])

    # ============================================================ pattern comparison
    def _compare(self, run: _Run) -> None:
        """The tinnitus patterns (textbook) set against the case's own findings once the routing has nothing left to
        ask: what supports each, what opposes it, what is still unknown — no probability, and a clue (age, a trigger)
        never makes a pattern by itself."""
        pack = self.pack
        route = run.facts["control.clinical_case_route_required"]["value"]
        tin = (run.facts.get("symptom.tinnitus") or {}).get("status")
        if not route or tin != "present" or run.blocked or any(
                m in ((pack.get("complaints") or {}).get("symptom.tinnitus") or {}).get("decision_critical", []) for m in run.missing):
            return
        for p in (pack.get("patterns") or {}).get("tinnitus") or []:
            st = lambda c: (run.facts.get(c) or {}).get("status")  # noqa: E731
            sup = [r for c in p["supports"] if st(c) == "present" for r in run.refs.get(c, [])]
            opp = [r for c in p["opposes"] if st(c) == "present" for r in run.refs.get(c, [])]
            missing = [c for c in p["supports"] + p["opposes"] if st(c) not in ("present", "absent")]
            status = "contradicted" if opp and not sup else ("plausible" if sup else "insufficient_information")
            run.patterns.append({"hypothesis_id": f"{run.case_id or 'query'}.{p['id']}", "clinical_condition": p["id"], "status": status,
                                 "supporting_observation_refs": sup, "opposing_observation_refs": opp, "missing_concepts": missing,
                                 "organ_entities": list(p.get("organs") or []), "yin_yang_aspects": list(p.get("aspects") or ["unspecified"]),
                                 "theory_support": [{"level": "teaching", "source_refs": list(p.get("sources") or []),
                                                     "rule_refs": [f"reasoning.patterns.tinnitus.{p['id'].split('.')[-1]}"],
                                                     "scope_note": f"{p['zh']}：教材的证型与其辨别要点；证型的比较不是诊断，也不给概率"
                                                                   + ("；年龄与诱因只是线索" if p.get("clues") else "")}],
                                 "clinical_efficacy": {"status": "not_applicable", "source_refs": [], "applicability_note": "证型的比较不涉及治疗的效果",
                                                       "does_not_validate_theory_automatically": True}})
        run.trace.append(self._step(run, "pattern_review", run.refs.get("symptom.tinnitus", []), ["reasoning.patterns.tinnitus"], ["src_textbook"],
                                    f"耳鸣的分流已无待问：比较 {len(run.patterns)} 个证型的支持、反对与仍缺的所见（不给概率）"))

    # ============================================================ results
    def _findings(self, run: _Run) -> tuple[list[dict[str, Any]], list[str]]:
        out, statuses, fired = [], [], []
        for r in self._fired(run):
            eff = r["effect"]
            facts = _facts_of(r["when"])
            refs = list(dict.fromkeys(x for f in facts for x in run.refs.get(f, [])))
            detail = "；".join(run.details[f] for f in facts if f in run.details)
            cands = list(dict.fromkeys(x for f in facts for x in run.candidate_refs.get(f, [])))
            extra = run.blocked_extra if "control.strategy_premise_incomplete" in facts else []
            out.append({"code": eff["code"], "severity": eff["severity"], "message": eff["message"].strip() + (f"（{detail}）" if detail else ""),
                        "observation_refs": refs, "candidate_refs": cands, "blocked_conclusions": list(dict.fromkeys([*(r.get("blocked") or []), *extra])),
                        "suggested_restatement": r.get("restate"), "source_refs": list(r.get("sources") or [])})
            run.sources += list(r.get("sources") or [])
            fired.append(r["id"])
            if eff.get("status"):
                statuses.append(eff["status"])
        run.fired = fired
        return out, statuses

    def _questions(self, run: _Run, status: str) -> list[dict[str, Any]]:
        if status in ("needs_urgent_assessment", "needs_etiologic_assessment"):
            return []
        limit = int(run.policy.get("max_questions_per_turn", 2))
        wanted = list(run.missing)
        rank: dict[str, int] = {}
        if status == "pattern_comparison":  # what would tell apart the patterns still standing comes first
            order = {"plausible": 0, "insufficient_information": 1, "contradicted": 2}
            for p in sorted(run.patterns, key=lambda p: order[p["status"]]):
                for c in p["missing_concepts"]:
                    rank.setdefault(c, order[p["status"]])
            wanted += list(rank)
        en = not re.search(r"[\u4e00-\u9fff]", run.args["query"])
        qs = sorted((q for q in self.pack.get("questions") or [] if set(q["targets"]) & set(wanted)),
                    key=lambda q: (min([rank.get(t, -1) for t in q["targets"] if t in wanted]), -q["priority"]))
        out = []
        for q in qs[:limit]:
            out.append({"question_id": q["id"], "text": q["en" if en else "zh"], "target_concepts": [t for t in q["targets"] if t in wanted] or q["targets"],
                        "reason": q["reason"]})
        return out

    def _status(self, run: _Run, statuses: list[str]) -> str:
        if statuses:
            status = min(statuses, key=STATUS_RANK.index)
        elif run.candidates:
            status = "candidate_review"
        elif run.tool == "reason" and run.mode == "knowledge":
            status = "educational_only" if (run.mappings or run.relations or run.obs or run.states or run.claims or run.points) else "no_applicable_rule"
        elif run.mappings:
            status = "educational_only"
        elif run.patterns:
            status = "pattern_comparison"
        elif not run.facts["control.clinical_case_route_required"]["value"] and (run.states or run.relations or run.obs or run.claims or run.points
                                                                                  or run.plan):
            status = "educational_only"
        else:
            status = "no_applicable_rule"
        if run.tool == "reason" and run.mode == "knowledge" and status not in ("educational_only", "no_applicable_rule"):
            run.notes.append({"note": f"知识问答的结果不作个案的判断：规则所示的 {status} 见 findings，assessment_status 记为 educational_only"})
            status = "educational_only"
        return status

    def _evidence(self, run: _Run, extra: Iterable[str] = ()) -> dict[str, Any]:
        reg = self.pack.get("sources") or {}
        used = list(dict.fromkeys([*run.sources, *extra, *(x for r in run.relations.values() for x in r["source_refs"])]))
        return {"registry": "acupuncture_reasoning.yaml#/sources",
                "strategies": run.strategy_rows,
                "theory_sources": [{"source_id": k, **{f: reg[k].get(f) for f in ("kind", "title", "url", "verification", "supports", "does_not_establish") if reg[k].get(f)}}
                                   for k in used if k in reg],
                "clinical_efficacy": self._efficacy(),
                "points": run.points,
                "separation": "理论的出处（theory_support）与临床的疗效（clinical_efficacy）分开记：一者成立不使另一者成立"}

    def _analogies(self, run: _Run) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        texts = " ".join(self._norm(t) for _, t, _ in run.texts) + " " + " ".join(self._norm(t) for t in run.args.get("proposed_claims") or [])
        analogies = []
        for an in self.pack.get("analogies") or []:
            src, tgt = self._words(an["source_terms"], texts), self._words(an["target_terms"], texts)
            if src and tgt:
                analogies.append({"analogy_id": an["id"], "source_terms": sorted({w for w, _ in src}), "target_terms": sorted({w for w, _ in tgt}),
                                  "status": "hypothesis_only", "hypothesis": an["hypothesis"],
                                  "observations_needed": [{"concept_id": c, "status": (run.facts.get(c) or {}).get("status", "unknown")} for c in an["observations_needed"]],
                                  "cannot_establish": an["cannot_establish"], "provenance": "user_metaphor", "source_refs": an.get("sources") or []})
        directions = []
        for frame, d in (self.pack.get("directions") or {}).items():
            hits = self._words(d.get("names") or [], texts)
            if hits:
                directions.append({"frame": frame, "words": sorted({w for w, _ in hits}), "source_refs": d.get("sources") or [],
                                   "note": "功能的方向（气机升降出入）、经脉的走向与物理的压力是三个参照系，不互换"})
        return analogies, directions

    def _common(self, run: _Run, status: str, findings: list[dict[str, Any]], questions: list[dict[str, Any]]) -> dict[str, Any]:
        case = run.case or {}
        return {"execution_status": "completed", "assessment_status": status, "mode": run.mode,
                "result_id": self._result_id(run.tool, run.args), "case_id": case.get("case_id"), "case_version": case.get("case_version"),
                "findings": findings, "questions": questions, "production_integration": "taochronos.study",
                "method_resolution": {"parameter_was_provided": run.provided, "effective_methods": list(run.effective),
                                      "empty_semantics": "no_selection_method_execution", "query_does_not_override_explicit_empty": True},
                "theory_relations": list(run.relations.values()), "knowledge_version": self.knowledge_version,
                "rulepack_version": self.rulepack_version, "notice": (self.pack.get("notice") or "").strip()}

    def _reason_out(self, run: _Run) -> dict[str, Any]:
        self._context_relations(run)
        findings, statuses = self._findings(run)
        status = self._status(run, statuses)
        if status != "candidate_review" and run.candidates:
            run.withheld += len(run.candidates)
            run.candidates = []
        if run.mode == "case_review":
            run.mappings = []
        questions = self._questions(run, status)
        budget = int(run.policy.get("max_candidate_points", 6))
        shown = run.candidates[:budget]
        analogies, directions = self._analogies(run)
        self._route_trace(run, status)
        out = {"artifact_type": "reason_result", **self._common(run, status, findings, questions),
               "normalized_observations": run.obs, "organ_states": [s["state"] for s in run.states], "pattern_hypotheses": run.patterns,
               "point_candidates": shown, "trace": run.trace, "source_registry_ref": "acupuncture_reasoning.yaml#/sources",
               "clinical_condition_is_not_diagnosis_probability": True, "educational_mappings": run.mappings,
               "candidate_display": {"budget": budget, "total_validated_candidates": len(run.candidates), "displayed_count": len(shown),
                                     "remaining_count": len(run.candidates) - len(shown), "budget_is_not_treatment_point_count": True},
               "evidence": self._evidence(run, [x for c in shown for x in c["theory_support"]["source_refs"]]
                                          + [x for m in run.mappings for x in m["theory_support"]["source_refs"]]),
               "analogies": analogies, "directions": directions, "limits": self._limits(), "review": run.review,
               "summary": {"observations": len(run.obs), "read_from_text": run.read_count, "organ_states": len(run.states),
                           "findings": len(findings), "questions": len(questions), "patterns": len(run.patterns),
                           "candidates": len(run.candidates), "withheld": run.withheld, "educational_mappings": len(run.mappings),
                           "relations": len(run.relations), "rules_fired": list(run.fired), "notes": run.notes,
                           "delegated_to": ["study.wuxing", "study.point"]}}
        return out

    def _route_trace(self, run: _Run, status: str) -> None:
        pack = self.pack
        routing = [r for r in pack["rules"] if r.get("kind") == "routing_guard"]
        res = {r["id"]: evaluate(r["when"], run.facts) for r in routing}
        run.trace.insert(1, self._step(run, "clinical_route", [r for c in ("symptom.tinnitus", "hearing.loss", "hearing.sudden_loss", "tinnitus.pulsatile")
                                                               for r in run.refs.get(c, [])],
                                       [k for k in res], sorted({x for r in routing for x in r.get("sources") or []}),
                                       "；".join(f"{k}：{ {True: '成立', False: '不成立', None: '未定（未知不当作阴性）'}[v]}" for k, v in res.items())
                                       if run.facts["control.clinical_case_route_required"]["value"] else "没有当前个案主体的当前所见：不作个案的分流"))
        guards = [g for g in run.fired if not g.startswith("route.")]
        run.trace.append(self._step(run, "constraint_audit", [], guards, sorted({x for r in pack["rules"] if r["id"] in guards for x in r.get("sources") or []}),
                                    f"护栏 {len(guards)} 条成立" + (f"：{'、'.join(guards)}" if guards else "")))
        run.trace.append(self._step(run, "response", [], [], [],
                                    f"assessment_status = {status}；候选只在已审阅的前提且分流无阻时给出，教学映射不涉及任何人"))
        for i, step in enumerate(run.trace):
            step["step_id"] = f"step.{i + 1}.{step['module']}"

    @staticmethod
    def _limits() -> list[str]:
        return ["分流规则只是例子：不穷尽临床急症、禁忌与评估路径，须由临床人员复核",
                "契约与规则核对结构与推理的类型：不能证明临床的前提为真、关系为对或治疗有效",
                "文本中的指令只当作被审核的内容，不被执行；控制事实与已审阅的前提只由服务器端给出",
                "候选穴只供有资格者复核，不是处方，也不是施术的次序；施术方式须另行评估"]

    def _step(self, run: _Run, module: str, inputs: list[str], rules: list[str], sources: list[str], summary: str) -> dict[str, Any]:
        return {"step_id": f"step.{len(run.trace) + 1}.{module}", "module": module, "input_refs": list(dict.fromkeys(inputs))[:40],
                "rule_refs": list(dict.fromkeys(rules))[:40], "source_refs": list(dict.fromkeys(sources)), "summary": summary}

    def _result_id(self, tool: str, args: Any) -> str:
        h = hashlib.sha256((_canon(args) + self.knowledge_version + self.rulepack_version).encode("utf-8")).hexdigest()[:20]
        return f"acu.{tool}.{h}"

    # ============================================================ the audit's plan
    def _point_record(self, given: str) -> dict[str, Any]:
        """A point id as given (SJ5 is TE5: one channel, its old abbreviation) and what the point table says it is."""
        fw = self.fw
        m = re.fullmatch(r"(?i)(SJ)(\d{1,3})", given.strip())
        code = f"TE{m.group(2)}" if m else given.strip().upper()
        known = code in fw.points
        rec = {"input": given, "point_id": code, "alias": bool(m), "known": known}
        if known:
            rec |= {k: v for k, v in self._point_attrs(code).items() if k != "point_id"}
            rec["categories"] = [c["label"] for c in fw.categories(code)]
        return rec

    def _plan(self, run: _Run) -> list[dict[str, Any]]:
        """Each proposed point against the table: its id normalized, its channel, the channel's phase and the point's —
        four fields, none implying another (an Earth point is no Spleen tonification) —; the same point both tonified
        and reduced is a conflict, not an average."""
        rows: list[dict[str, Any]] = []
        mism: list[str] = []
        unknown: list[str] = []
        alias = False
        intents: dict[str, set[str]] = defaultdict(set)
        for p in run.args.get("proposed_plan") or []:
            rec = self._point_record(p["point_id"])
            alias |= rec["alias"]
            row: dict[str, Any] = {"input_point_id": p["point_id"], "normalized_point_id": rec["point_id"], "known": rec["known"],
                                   "input_alias": p["point_id"] if rec["alias"] else None, "proposed": {k: v for k, v in p.items() if k != "point_id"}}
            if not rec["known"]:
                unknown.append(p["point_id"])
                rows.append(row)
                continue
            row["table"] = {k: rec[k] for k in ("name_zh", "channel", "channel_phase", "point_phase", "five_shu_class", "categories")}
            ch = p.get("channel")
            if ch == "SJ":
                alias = True
                ch = "TE"
            diffs = [f for f, v in (("channel", ch), ("channel_phase", p.get("channel_phase")), ("point_phase", p.get("point_phase")))
                     if f in p and v != rec[f]]
            row["mismatches"] = diffs
            if diffs:
                mism.append(rec["point_id"])
            if p.get("intent") in ("tonify", "reduce"):
                intents[rec["point_id"]].add(p["intent"])
            row["independent_fields"] = "经脉、经脉的五行、穴的五行、补泻的意图与施术方式各自独立：任何一个都不自动决定其余"
            if p.get("modality") not in (None, "undetermined"):
                row["modality_note"] = "施术方式须另行评估：穴的五行不决定针或灸"
            rows.append(row)
        opposed = sorted(c for c, xs in intents.items() if {"tonify", "reduce"} <= xs)
        self._control(run, "control.opposed_intentions", bool(opposed), detail="、".join(opposed))
        run.candidate_refs["control.opposed_intentions"] = opposed
        self._control(run, "control.point_attribute_mismatch", bool(mism), detail="、".join(mism))
        run.candidate_refs["control.point_attribute_mismatch"] = mism
        self._control(run, "control.unknown_point", bool(unknown) or run.facts.get("control.unknown_point", {}).get("value", False), detail="、".join(unknown))
        self._control(run, "control.alias_normalized", alias or run.facts.get("control.alias_normalized", {}).get("value", False))
        run.plan = rows
        return rows

    def _claims_review(self, run: _Run) -> list[dict[str, Any]]:
        by_claim = {r["when"]["present"]: r for r in self.pack["rules"] if "present" in r["when"]}
        for r in self.pack["rules"]:
            for f in _facts_of(r["when"]):
                if f.startswith("claim."):
                    by_claim.setdefault(f, r)
        hyps = {h["claim"]: h for h in self.pack.get("hypotheses") or []}
        out = []
        for text in run.args.get("proposed_claims") or []:
            norm = self._norm(text)
            matched = sorted({cid for cid, rx in self.lexicon["claims"] if rx.search(norm)})
            row: dict[str, Any] = {"claim": text, "matched": matched,
                                   "codes": [by_claim[c]["effect"]["code"] for c in matched if c in by_claim and c in run.facts
                                             and evaluate(by_claim[c]["when"], run.facts) is True],
                                   "status": "guarded" if matched else "no_rule"}
            if not matched:
                row["note"] = "规则包中没有针对此主张的护栏：未作判定（不是认可）"
            for c in matched:
                if c in hyps:
                    h = hyps[c]
                    row["hypothesis"] = {"id": h["id"], "wording": h["wording"], "level": h["level"], "status": h["status"],
                                         "premise": h.get("premise"), "differs_from": h.get("differs_from"), "validation": h.get("validation")}
                    if run.policy.get("unvalidated_hypotheses") == "explanation_only" and h.get("mapping"):
                        row["hypothesis"]["mapping_explained"] = {k: v for k, v in h["mapping"].items()}
                        row["hypothesis"]["mapping_note"] = "只说明其推导，不作为取穴：此假说默认停用"
            out.append(row)
        return out

    def _audit_out(self, run: _Run, plan: list[dict[str, Any]]) -> dict[str, Any]:
        for row in plan:  # what the requested methods give for this point, on the states given
            row["methods"] = [{"method_id": rec["method"], "organ_entity": s["state"]["organ_entity"], "state": s["state"]["state"],
                               "intent": INTENT_ID.get(p.get("intent") or "", "undetermined")}
                              for s, rec in run.method_records for p in rec["points"] if p["code"] == row["normalized_point_id"]]
        codes = [r["normalized_point_id"] for r in plan if r["known"]]
        for text in [t for _, t, _ in run.texts] + list(run.args.get("proposed_claims") or []):
            for m in POINT_CODE.finditer(text):
                rec = self._point_record(m.group(1) + m.group(2))
                if rec["known"]:
                    codes.append(rec["point_id"])
            norm = self._norm(text)
            for m in self.s._names_re().finditer(norm):
                codes.append(self.s._name_code[m.group(0)])
        codes = list(dict.fromkeys(codes))
        self._context_relations(run, codes)
        claims_review = self._claims_review(run)
        findings, statuses = self._findings(run)
        status = self._status(run, statuses)
        questions = self._questions(run, status)
        self._route_trace(run, status)
        out = {"artifact_type": "audit_result", **self._common(run, status, findings, questions), "normalized_point_ids": codes,
               "evidence": self._evidence(run), "plan_review": plan, "claims_review": claims_review,
               "organ_states": [s["state"] for s in run.states], "normalized_observations": run.obs,
               "summary": {"claims": len(claims_review), "plan_points": len(plan), "findings": len(findings), "relations": len(run.relations),
                           "rules_fired": list(run.fired), "trace": run.trace, "notes": run.notes,
                           "delegated_to": ["study.point", "study.wuxing"]}}
        return out

    # ============================================================ invalid, unavailable, sealed
    def _empty(self, tool: str, args: Any, status: str, findings: list[dict[str, Any]]) -> dict[str, Any]:
        a = args if isinstance(args, dict) else {}
        mode = a.get("mode") if a.get("mode") in ("knowledge", "case_review", "method_compare") else None
        case = a.get("case") if isinstance(a.get("case"), dict) else {}
        cid = case.get("case_id") if isinstance(case.get("case_id"), str) else None
        ver = case.get("case_version") if _is(case.get("case_version"), "integer") and not isinstance(case.get("case_version"), float) and case.get("case_version", 0) >= 1 else None
        kv = self.knowledge_version if self._safe(lambda: self.knowledge_version) else "unavailable"
        rv = self.rulepack_version if self._safe(lambda: self.rulepack_version) else "unavailable"
        common = {"execution_status": status, "assessment_status": None, "findings": findings, "questions": [],
                  "production_integration": "taochronos.study", "result_id": f"acu.{tool}.{hashlib.sha256(_canon(args).encode('utf-8')).hexdigest()[:20]}",
                  "case_id": cid, "case_version": ver, "knowledge_version": kv, "rulepack_version": rv, "theory_relations": [],
                  "method_resolution": {"parameter_was_provided": "requested_methods" in a, "effective_methods": [],
                                        "empty_semantics": "no_selection_method_execution", "query_does_not_override_explicit_empty": True}}
        if tool == "audit":
            return {"artifact_type": "audit_result", **common, "normalized_point_ids": [], "mode": mode}
        return {"artifact_type": "reason_result", **common, "mode": mode, "normalized_observations": [], "organ_states": [],
                "pattern_hypotheses": [], "point_candidates": [], "trace": [], "source_registry_ref": "acupuncture_reasoning.yaml#/sources",
                "clinical_condition_is_not_diagnosis_probability": True, "educational_mappings": [],
                "candidate_display": {"budget": 6, "total_validated_candidates": 0, "displayed_count": 0, "remaining_count": 0,
                                      "budget_is_not_treatment_point_count": True}}

    @staticmethod
    def _safe(fn: Any) -> bool:
        try:
            fn()
            return True
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _finding(code: str, message: str) -> dict[str, Any]:
        return {"code": code, "severity": "block", "message": message, "observation_refs": [], "candidate_refs": [],
                "blocked_conclusions": [], "suggested_restatement": None, "source_refs": []}

    def _invalid(self, tool: str, args: Any, errs: list[dict[str, str]]) -> dict[str, Any]:
        findings = [self._finding(e["code"], f"{e['path']}：{e['message']}") for e in errs[:25]]
        if len(errs) > 25:
            findings.append(self._finding("INVALID_PARAMETERS", f"另有 {len(errs) - 25} 处不合契约"))
        if any(e["code"] == "INVALID_METHOD" for e in errs):
            findings[0]["message"] += "——未知的方法被拒绝，不回退到全部方法"
        out = self._empty(tool, args, "invalid_parameters", findings)
        out["notice"] = "参数不合契约：没有作任何评估（assessment_status 为 null），也不回退到旧的接口或默认的方法。"
        return out

    def _unavailable(self, tool: str, args: Any, why: str) -> dict[str, Any]:
        out = self._empty(tool, args, "dependency_unavailable", [self._finding("DEPENDENCY_UNAVAILABLE", f"所依赖的数据或计算不可用：{why}")])
        out["notice"] = "依赖不可用：没有作任何评估。"
        return out

    def _seal(self, out: dict[str, Any], name: str, tool: str, args: Any) -> dict[str, Any]:
        errs = self.contracts.errors(out, name)
        if errs:
            res = self._empty(tool, args, "dependency_unavailable",
                              [self._finding("OUTPUT_CONTRACT_VIOLATION", f"结果不合返回的契约，已整体不予给出：{e['path']}：{e['message']}") for e in errs[:10]])
            res["notice"] = "结果未通过返回契约的核对：没有作任何评估。"
            return res
        return out


__all__ = ["AcupunctureReasoning", "Contracts", "ReviewStore", "evaluate", "observations_digest"]
