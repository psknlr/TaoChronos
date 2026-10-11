"""The edge rules of impf.ai, from security/rules.yaml to Cloudflare (security/README.md).

  plan    read the zone's rulesets and settings, say what apply would change (nothing is written)
  apply   write them: the custom rules and the rate limit (the phase entry points are replaced — rules whose description
          does not begin with [taochronos] are kept after ours), the zone settings, the bot settings, the block list and
          its addresses from security/blocklist.yaml (the unexpired ones; addresses added by hand, whose comment does not
          begin with [taochronos], are kept; an entry overlapping a network never to be blocked stops the list's write)

Environment: CLOUDFLARE_SECURITY_TOKEN — a token of its own (never the deploy token) with Zone → Zone WAF: Edit,
Zone → Zone Settings: Edit, Zone → Bot Management: Edit, Zone → Zone: Read (to find the zone by name) and, for the block
list, Account → Account Filter Lists: Edit; CLOUDFLARE_ZONE_ID (optional: found by name otherwise); CLOUDFLARE_ACCOUNT_ID
(for the list; optional).  Standard library and PyYAML only.  Exit status 1 when anything apply tried to write was refused.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
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

    def call(self, method: str, path: str, body: dict | list | None = None) -> tuple[int, dict]:
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
    training = [str(a) for a in rules.get("training_agents", []) or []]
    subst = {
        "${TRAINING_AGENTS_MATCH}": "(" + " or ".join(f"(http.user_agent contains {json.dumps(a)})" for a in training) + ")"
                                    if training else "false",
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


def ensure_list(api: Api, account: str, name: str, write: bool) -> tuple[str, str, str | None]:
    """Is the block list there (created when apply may)?  Returns (state, note, its id): ok — usable; missing — none, and
    none to be made (the rules go without it); unknown — it could not be read, so nothing about it may be changed."""
    if not account:
        return "missing", "no CLOUDFLARE_ACCOUNT_ID: the block list is not used", None
    status, body = api.get(f"/accounts/{account}/rules/lists")
    if status in (401, 403):
        return "missing", f"the token may not read the account's lists ({errors(body)}): the block list is not used", None
    if status != 200:
        return "unknown", f"the lists could not be read ({errors(body)}): the custom rules are left as they are", None
    found = next((item for item in body.get("result", []) or [] if item.get("name") == name), None)
    if found:
        return "ok", f"the block list {name} exists", found.get("id")
    if not write:
        return "ok", f"the block list {name} would be created", None
    status, body = api.call("POST", f"/accounts/{account}/rules/lists", {"name": name, "kind": "ip", "description": "taochronos: addresses refused everywhere (security/blocklist.yaml)"})
    if status in (200, 201):
        return "ok", f"the block list {name} created (empty)", (body.get("result") or {}).get("id")
    return "unknown", f"the block list could not be created ({errors(body)}): the custom rules are left as they are", None


# ---------------------------------------------------------------- the block list's addresses
COMMENT_MAX = 200
pause = time.sleep  # waiting on the list's operations (a test does without)


def canon(text: str) -> str:
    """An address or network as the list holds it: an address without its /32 (/128), a network by its first address."""
    net = ipaddress.ip_network(str(text).strip(), strict=False)
    return str(net.network_address) if net.prefixlen == net.max_prefixlen else str(net)


def wanted_items(blocklist: dict, today: date) -> tuple[list[dict], list[str], list[str]]:
    """The addresses the list should hold of ours ({ip, comment}), the notes (what was left out: an entry past its until)
    and the problems (what may not be written: an entry that cannot be read, or one overlapping a network never to be
    blocked).  An entry without until is refused for good.  Any problem stops the list's write: a half-applied list is
    worse than an unchanged one."""
    never, problems = [], []
    for n in blocklist.get("never", []) or []:
        try:
            never.append((ipaddress.ip_network(str(n["net"]), strict=False), str(n.get("why") or n["net"])))
        except (KeyError, TypeError, ValueError) as err:
            problems.append(f"never: {n!r} is not a network ({err})")
    items, notes, taken = [], [], set()
    for e in blocklist.get("block", []) or []:
        raw = str(e.get("ip") or "").strip() if isinstance(e, dict) else ""
        try:
            net = ipaddress.ip_network(raw, strict=False)
        except ValueError:
            problems.append(f"{raw or e!r}: not an address or a network")
            continue
        widest = 8 if net.version == 4 else 12
        if net.prefixlen < widest:
            problems.append(f"{raw}: wider than /{widest}, which the list does not take")
            continue
        why, until = str(e.get("why") or "").strip(), e.get("until")
        if isinstance(until, datetime):  # until: 2027-01-05T00:00:00 reads as a time; the day is what counts
            until = until.date()
        if not why:
            problems.append(f"{raw}: needs why (what was seen)")
            continue
        if until is not None and not isinstance(until, date):
            problems.append(f"{raw}: until must be a date (YYYY-MM-DD), or be left out to refuse the address for good")
            continue
        spared = next((w for n, w in never if n.version == net.version and n.overlaps(net)), None)
        if spared is not None:
            problems.append(f"{raw}: overlaps a network never to be blocked ({spared})")
            continue
        ip = canon(raw)
        if ip in taken:
            problems.append(f"{raw}: listed twice")
            continue
        taken.add(ip)
        if until is not None and until < today:
            notes.append(f"· {ip}: expired on {until}, left out")
            continue
        items.append({"ip": ip, "comment": f"{TAG} {why} · seen {e.get('seen', '?')} · {f'until {until}' if until else 'for good'}"[:COMMENT_MAX]})
    return items, notes, problems


def list_items(api: Api, account: str, list_id: str) -> list[dict] | None:
    """What the list holds now ({ip, comment}), page by page; None when it could not be read."""
    out, cursor = [], ""
    for _ in range(200):
        status, body = api.get(f"/accounts/{account}/rules/lists/{list_id}/items?per_page=500" + (f"&cursor={cursor}" if cursor else ""))
        if status != 200:
            return None
        out.extend({"ip": canon(i["ip"]), "comment": str(i.get("comment") or "")} for i in body.get("result", []) or [] if i.get("ip"))
        cursor = ((body.get("result_info") or {}).get("cursors") or {}).get("after") or ""
        if not cursor:
            break
    return out


def list_plan(current: list[dict], wanted: list[dict]) -> tuple[list[dict], list[str], bool]:
    """The addresses to write (ours as wanted, then the ones added by hand, kept), the differences in words, and whether
    there are any."""
    ours_now = {i["ip"]: i for i in current if i["comment"].startswith(TAG)}
    wanted_ips = {i["ip"] for i in wanted}
    by_hand = [i for i in current if not i["comment"].startswith(TAG) and i["ip"] not in wanted_ips]
    notes = []
    for i in wanted:
        before = ours_now.pop(i["ip"], None)
        if before is None:
            was = "now in blocklist.yaml (it was added by hand)" if any(c["ip"] == i["ip"] for c in current) else "added"
            notes.append(f"+ {i['ip']}: {was} — {i['comment'][len(TAG) + 1:]}")
        elif before["comment"] != i["comment"]:
            notes.append(f"~ {i['ip']}: its note changed")
    for ip in ours_now:
        notes.append(f"- {ip}: removed (expired, or no longer in blocklist.yaml)")
    if by_hand:
        notes.append(f"= {len(by_hand)} address(es) added by hand kept: {', '.join(i['ip'] for i in by_hand)}")
    target = wanted + by_hand
    changed = sorted((i["ip"], i["comment"]) for i in target) != sorted((i["ip"], i["comment"]) for i in current)
    return target, notes, changed


def list_apply(api: Api, account: str, list_id: str, target: list[dict], wait: float = 60.0) -> str | None:
    """Replace the list's addresses with target and wait for the operation to finish; None when it did, else why not."""
    for attempt in range(5):
        status, body = api.call("PUT", f"/accounts/{account}/rules/lists/{list_id}/items", target)
        if status != 429:  # 429: an earlier operation on the list is still running
            break
        pause(2 * (attempt + 1))
    if status != 200:
        return errors(body)
    op = (body.get("result") or {}).get("operation_id")
    if not op:
        return None
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        status, body = api.get(f"/accounts/{account}/rules/lists/bulk_operations/{op}")
        result = body.get("result") or {}
        if status == 200 and result.get("status") == "completed":
            return None
        if status != 200 or result.get("status") == "failed":
            return str(result.get("error") or errors(body))
        pause(1)
    return f"the operation {op} had not finished after {int(wait)} s (it may still finish: run plan to see)"


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
    ap.add_argument("--blocklist", default=str(Path(__file__).with_name("blocklist.yaml")))
    ap.add_argument("--only", default="custom,ratelimit,settings,bots,list", help="which parts: custom, ratelimit, settings, bots, list (comma-separated)")
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

    account = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    state, note, list_id = ensure_list(api, account, str(rules.get("list", "")), write) if rules.get("list") else ("missing", "no block list named", None)
    print(f"- {note}")
    rendered = render(rules, state == "ok")
    for key, phase in PHASES.items():
        part = "custom" if key == "custom_rules" else "ratelimit"
        if part not in parts:
            continue
        if part == "custom" and state == "unknown":
            # a list that may be in use (an incident) must not be dropped on a failed read: nothing is written to the phase
            print(f"- {phase}: not touched (the block list could not be read)")
            if write:
                failed.append(phase)
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
    if "list" in parts and rules.get("list"):
        path = Path(args.blocklist)
        blocklist = (yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else None) or {}
        wanted, left_out, problems = wanted_items(blocklist, datetime.now(timezone.utc).date())
        if problems:
            print(f"- the block list's addresses: not written, {path.name} has {len(problems)} problem(s)")
            for p in problems:
                print(f"    ! {p}")
            failed.append(path.name)
        elif state != "ok":
            print(f"- the block list's addresses: not touched ({note})")
            if write and (state == "unknown" or wanted):  # addresses to refuse and no list to hold them: not a quiet success
                failed.append("the block list's addresses")
        else:
            current = list_items(api, account, list_id) if list_id else []
            if current is None:
                print("- the block list's addresses: the list could not be read: not touched")
                if write:
                    failed.append("the block list's addresses")
            else:
                target, notes, changed = list_plan(current, wanted)
                print(f"- the block list's addresses: {len(current)} now, {len(target)} wanted")
                for n in left_out + notes:
                    print(f"    {n}")
                if not changed:
                    print("    (no change)")
                elif write:
                    err = list_apply(api, account, list_id, target)
                    print(f"    {'written' if err is None else 'REFUSED: ' + err}")
                    if err:
                        failed.append("the block list's addresses")
    if failed:
        raise SystemExit(f"refused: {', '.join(failed)} (see above: the token's permissions, the plan's limits, or blocklist.yaml; security/README.md)")
    if not write:
        print("nothing written (plan); run with apply to write")


if __name__ == "__main__":
    main(sys.argv[1:])
