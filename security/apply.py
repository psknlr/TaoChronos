"""The edge rules of impf.ai, from security/rules.yaml to Cloudflare (security/README.md).

  plan    read the zone's rulesets and settings, say what apply would change (nothing is written)
  apply   write them: the custom rules and the rate limit (the phase entry points are replaced — rules whose description
          does not begin with [taochronos] are kept after ours), the zone settings, the bot settings, the block list

Environment: CLOUDFLARE_SECURITY_TOKEN — a token of its own (never the deploy token) with Zone → Zone WAF: Edit,
Zone → Zone Settings: Edit, Zone → Bot Management: Edit, Zone → Zone: Read (to find the zone by name) and, for the block
list, Account → Account Filter Lists: Edit; CLOUDFLARE_ZONE_ID (optional: found by name otherwise); CLOUDFLARE_ACCOUNT_ID
(for the list; optional).  Standard library and PyYAML only.  Exit status 1 when anything apply tried to write was refused.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

API = "https://api.cloudflare.com/client/v4"
TAG = "[taochronos]"
UA = "taochronos-security/1"
PHASES = {"custom_rules": "http_request_firewall_custom", "rate_limits": "http_ratelimit"}
FREE_LIMITS = {"http_request_firewall_custom": 5, "http_ratelimit": 1}


class Api:
    def __init__(self, token: str) -> None:
        self.token = token

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(f"{API}{path}", data=data, method=method,
                                     headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json", "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 — Cloudflare's API
                return r.status, json.loads(r.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as err:
            raw = err.read().decode("utf-8", "replace")
            try:
                return err.code, json.loads(raw)
            except json.JSONDecodeError:
                return err.code, {"errors": [{"message": raw[:300]}]}

    def get(self, path: str) -> tuple[int, dict]:
        return self.call("GET", path)


def errors(body: dict) -> str:
    return "; ".join(f"{e.get('code', '')} {e.get('message', '')}".strip() for e in body.get("errors", []) or []) or "unknown error"


# ---------------------------------------------------------------- the rules, rendered
def quoted_set(values: list[str]) -> str:
    return " ".join(json.dumps(str(v)) for v in values)


def render(rules: dict, with_list: bool) -> dict[str, list[dict]]:
    """The phases' rule lists as the API takes them, with the placeholders filled."""
    subst = {
        "${ORIGINS}": quoted_set(rules.get("origins", [])),
        "${OWN_AGENTS}": quoted_set(rules.get("own_agents", [])),
        "${HOSTING_ASNS}": " ".join(str(int(a)) for a in rules.get("hosting_asns", [])),
        "${LIST}": str(rules.get("list", "")),
    }
    out: dict[str, list[dict]] = {}
    for key, phase in PHASES.items():
        rendered = []
        for r in rules.get(key, []) or []:
            expr = " ".join(str(r["expression"]).split())
            for k, v in subst.items():
                expr = expr.replace(k, v)
            if not with_list and rules.get("list"):
                # without the list (no permission for it, or none yet): the clause goes, the rest of the rule stays — a
                # rule that was only the list is left out
                expr = re.sub(r"\(ip\.src in \$" + re.escape(str(rules["list"])) + r"\)\s*or\s*", "", expr)
                expr = re.sub(r"^\(ip\.src in \$" + re.escape(str(rules["list"])) + r"\)$", "", expr).strip()
                if not expr:
                    continue
            rule = {"ref": r["ref"], "description": r["description"], "enabled": r.get("enabled", True), "action": r["action"], "expression": expr}
            for k in ("action_parameters", "logging", "ratelimit"):
                if k in r:
                    rule[k] = r[k]
            rendered.append(rule)
        out[phase] = rendered
    return out


def strip(rule: dict) -> dict:
    """A rule as compared: without what the server adds."""
    return {k: v for k, v in rule.items() if k in ("ref", "description", "enabled", "action", "expression", "action_parameters", "logging", "ratelimit")}


# ---------------------------------------------------------------- the zone and the account
def zone_id(api: Api, name: str) -> str:
    env = os.environ.get("CLOUDFLARE_ZONE_ID", "").strip()
    if env:
        return env
    status, body = api.get(f"/zones?name={name}")
    if status != 200 or not body.get("result"):
        raise SystemExit(f"the zone {name} could not be found (set CLOUDFLARE_ZONE_ID, or give the token Zone → Zone: Read): {errors(body)}")
    return body["result"][0]["id"]


def ensure_list(api: Api, account: str, name: str, write: bool) -> tuple[bool, str]:
    """Is the block list there (created when apply may)?  Returns (usable, note)."""
    if not account:
        return False, "no CLOUDFLARE_ACCOUNT_ID: the block list is not used"
    status, body = api.get(f"/accounts/{account}/rules/lists")
    if status != 200:
        return False, f"the lists could not be read ({errors(body)}): the block list is not used"
    if any(item.get("name") == name for item in body.get("result", []) or []):
        return True, f"the block list {name} exists"
    if not write:
        return True, f"the block list {name} would be created"
    status, body = api.call("POST", f"/accounts/{account}/rules/lists", {"name": name, "kind": "ip", "description": "taochronos: addresses refused everywhere (security/README.md); empty until an incident"})
    if status in (200, 201):
        return True, f"the block list {name} created (empty)"
    return False, f"the block list could not be created ({errors(body)}): the block list is not used"


# ---------------------------------------------------------------- the phases
def phase_plan(api: Api, zone: str, phase: str, wanted: list[dict]) -> tuple[list[dict], list[dict], list[str]]:
    """What the phase holds now, what it would hold, and the differences in words."""
    status, body = api.get(f"/zones/{zone}/rulesets/phases/{phase}/entrypoint")
    current = body.get("result", {}).get("rules", []) if status == 200 else []
    if status not in (200, 404):
        raise SystemExit(f"{phase}: the ruleset could not be read: {errors(body)}")
    foreign = [strip(r) for r in current if not str(r.get("description", "")).startswith(TAG)]
    ours_now = {r.get("ref") or r.get("id"): strip(r) for r in current if str(r.get("description", "")).startswith(TAG)}
    target = wanted + foreign
    notes = []
    for r in wanted:
        before = ours_now.pop(r["ref"], None)
        if before is None:
            notes.append(f"+ {r['ref']}: added")
        elif before != r:
            changed = [k for k in set(before) | set(r) if before.get(k) != r.get(k)]
            notes.append(f"~ {r['ref']}: changed ({', '.join(sorted(changed))})")
    for ref in ours_now:
        notes.append(f"- {ref}: removed (no longer in rules.yaml)")
    if foreign:
        notes.append(f"= {len(foreign)} rule(s) not ours kept after ours: {', '.join(str(r.get('description') or r.get('ref')) for r in foreign)}")
    limit = FREE_LIMITS.get(phase)
    if limit and len(target) > limit:
        notes.append(f"! {len(target)} rules, the Free plan allows {limit}: the API may refuse the write")
    return current, target, notes


def phase_apply(api: Api, zone: str, phase: str, target: list[dict]) -> str | None:
    status, body = api.call("PUT", f"/zones/{zone}/rulesets/phases/{phase}/entrypoint", {"rules": target, "description": f"{TAG} security/rules.yaml"})
    return None if status == 200 else errors(body)


# ---------------------------------------------------------------- settings and bots
def settings_plan(api: Api, zone: str, wanted: dict) -> list[tuple[str, object, object]]:
    changes = []
    for name, value in wanted.items():
        status, body = api.get(f"/zones/{zone}/settings/{name}")
        current = body.get("result", {}).get("value") if status == 200 else f"(unreadable: {errors(body)})"
        if current != value:
            changes.append((name, current, value))
    return changes


def bots_plan(api: Api, zone: str, wanted: dict) -> tuple[dict, list[tuple[str, object, object]]]:
    status, body = api.get(f"/zones/{zone}/bot_management")
    current = body.get("result", {}) if status == 200 else {}
    changes = [(k, current.get(k), v) for k, v in wanted.items() if current.get(k) != v]
    return current, changes


# ---------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["plan", "apply"])
    ap.add_argument("--rules", default=str(Path(__file__).with_name("rules.yaml")))
    ap.add_argument("--only", default="custom,ratelimit,settings,bots", help="which parts: custom, ratelimit, settings, bots (comma-separated)")
    args = ap.parse_args(argv)
    parts = {p.strip() for p in args.only.split(",") if p.strip()}
    token = "".join(os.environ.get("CLOUDFLARE_SECURITY_TOKEN", "").split())
    if not token:
        raise SystemExit("CLOUDFLARE_SECURITY_TOKEN is not set (a token with Zone WAF / Zone Settings / Bot Management: Edit; security/README.md)")
    rules = yaml.safe_load(Path(args.rules).read_text(encoding="utf-8"))
    api = Api(token)
    zone = zone_id(api, rules["zone"])
    write = args.action == "apply"
    failed = []
    print(f"{args.action}: zone {rules['zone']} ({zone})")

    usable, note = ensure_list(api, os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip(), str(rules.get("list", "")), write) if rules.get("list") else (False, "no block list named")
    print(f"- {note}")
    rendered = render(rules, usable)
    for key, phase in PHASES.items():
        part = "custom" if key == "custom_rules" else "ratelimit"
        if part not in parts:
            continue
        current, target, notes = phase_plan(api, zone, phase, rendered[phase])
        print(f"- {phase}: {len(current)} rule(s) now, {len(target)} wanted")
        for n in notes:
            print(f"    {n}")
        if not notes:
            print("    (no change)")
        elif write:
            err = phase_apply(api, zone, phase, target)
            print(f"    {'written' if err is None else 'REFUSED: ' + err}")
            if err:
                failed.append(phase)
    if "settings" in parts:
        changes = settings_plan(api, zone, rules.get("settings", {}) or {})
        print(f"- settings: {len(changes)} change(s)")
        for name, before, after in changes:
            print(f"    ~ {name}: {json.dumps(before, ensure_ascii=False)} → {json.dumps(after, ensure_ascii=False)}")
            if write:
                status, body = api.call("PATCH", f"/zones/{zone}/settings/{name}", {"value": after})
                if status != 200:
                    print(f"      REFUSED: {errors(body)}")
                    failed.append(f"settings/{name}")
    if "bots" in parts and rules.get("bot_management"):
        current, changes = bots_plan(api, zone, rules["bot_management"])
        print(f"- bot_management: {len(changes)} change(s)")
        for name, before, after in changes:
            print(f"    ~ {name}: {json.dumps(before, ensure_ascii=False)} → {json.dumps(after, ensure_ascii=False)}")
        if changes and write:
            status, body = api.call("PUT", f"/zones/{zone}/bot_management", {**{k: v for k, v in current.items() if k in rules["bot_management"]}, **rules["bot_management"]})
            if status != 200:
                print(f"    REFUSED: {errors(body)}")
                failed.append("bot_management")
            else:
                print("    written")
    if failed:
        raise SystemExit(f"refused: {', '.join(failed)} (the token's permissions, or the plan's limits; security/README.md)")
    if not write:
        print("nothing written (plan); run with apply to write")


if __name__ == "__main__":
    main(sys.argv[1:])
