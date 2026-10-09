#!/usr/bin/env python3
"""Check approval policies against schema/approval-policy.schema.json and their cases.

A policy (rules/<ruleset>/policy.json, or examples/<name>/policy.json) is the Charter's
approval rules as data. This script checks each one against the schema, checks that every
action is in the permission vocabulary (agents-hive's execution-contract schema, plus any
actions the policy or the one it extends declares), and that an open mandate for a gated
action is a narrow, recorded exception. Then it runs the cases.json beside the policy:
each case is a request and the decision the policy must reach for it.

How a request is decided:
  1. A prohibition whose constraints hold, and whose unless conditions don't all hold,
     denies it, even with a human's approval.
  2. Otherwise an open mandate whose constraints all hold lets the agent act on its own.
  3. Otherwise a closed mandate whose constraints all hold means a human approves it.
  4. Otherwise it is denied.
A fact the request doesn't supply never holds. A policy's extends chain is merged in.

Standard library only.

Usage:
  python3 scripts/check_policy.py
"""
import json
import re
import sys
from pathlib import Path

HIVE = Path(__file__).resolve().parent.parent
REPO_ROOT = HIVE.parent.parent
SCHEMA = json.loads((HIVE / "schema" / "approval-policy.schema.json").read_text())
CONTRACT_SCHEMA = json.loads((REPO_ROOT / "hives" / "agents-hive" / "schema"
                              / "execution-contract.schema.json").read_text())
UNGATED = set(CONTRACT_SCHEMA["$defs"]["ungated"]["enum"])
GATED = set(CONTRACT_SCHEMA["$defs"]["gated"]["enum"])
CORE_NAMESPACES = {a.split(".")[0] for a in UNGATED | GATED}
KEBAB = re.compile(SCHEMA["properties"]["policy"]["pattern"])
ID = re.compile(SCHEMA["$defs"]["id"]["pattern"])
ACTION_ID = re.compile(SCHEMA["properties"]["actions"]["items"]["properties"]["id"]["pattern"])
OPEN, CLOSED = SCHEMA["$defs"]["mandate"]["properties"]["type"]["enum"]
DECISIONS = {"auto", "human", "deny"}


class PolicyError(Exception):
    pass


def load(path):
    try:
        return json.loads(path.read_text())
    except ValueError as e:
        raise PolicyError(f"{path.relative_to(REPO_ROOT)}: not valid JSON: {e}")


def unknown(obj, allowed, where, err):
    for key in sorted(set(obj) - set(allowed)):
        err(f"{where}: unknown field '{key}'")


def check_constraints(items, where, err):
    if not isinstance(items, list):
        err(f"{where} must be a list")
        return
    for i, c in enumerate(items):
        at = f"{where}[{i}]"
        if not isinstance(c, dict):
            err(f"{at} must be an object")
            continue
        kind = c.get("type")
        if kind == "action.scope":
            unknown(c, ("type", "scope"), at, err)
            scope = c.get("scope")
            if (not isinstance(scope, dict) or not scope
                    or not all(isinstance(v, list) and v and all(isinstance(x, str) for x in v)
                               for v in scope.values())):
                err(f"{at}.scope must map each dimension to a non-empty list of values")
        elif kind == "action.trigger":
            unknown(c, ("type", "events"), at, err)
            ev = c.get("events")
            if not isinstance(ev, list) or not ev or not all(isinstance(x, str) and x for x in ev):
                err(f"{at}.events must be a non-empty list of event names")
        elif kind == "action.condition":
            unknown(c, ("type", "field", "equals", "in"), at, err)
            if not isinstance(c.get("field"), str) or not c["field"]:
                err(f"{at}.field is required")
            if ("equals" in c) == ("in" in c):
                err(f"{at} needs exactly one of equals or in")
            elif "in" in c and (not isinstance(c["in"], list) or not c["in"]):
                err(f"{at}.in must be a non-empty list")
        else:
            err(f"{at}.type must be action.scope, action.trigger or action.condition")


def check(path):
    """Problems with one policy file, on its own."""
    errors = []
    err = errors.append
    p = load(path)
    if not isinstance(p, dict):
        return ["policy must be a JSON object"]
    unknown(p, SCHEMA["properties"], "policy", err)
    for key in SCHEMA["required"]:
        if key not in p:
            err(f"missing '{key}'")
    name = p.get("policy")
    if not isinstance(name, str) or not KEBAB.match(name):
        err("policy must be kebab-case")
    elif name != path.parent.name:
        err(f"policy '{name}' doesn't match its directory '{path.parent.name}'")
    v = p.get("version")
    if not isinstance(v, int) or isinstance(v, bool) or v < 1:
        err("version must be an integer of at least 1")
    for key in ("description", "source", "extends"):
        if key in p and (not isinstance(p[key], str) or not p[key]):
            err(f"{key} must be a non-empty string")

    actions = p.get("actions", [])
    if not isinstance(actions, list):
        err("actions must be a list")
        actions = []
    for i, a in enumerate(actions):
        at = f"actions[{i}]"
        if not isinstance(a, dict):
            err(f"{at} must be an object")
            continue
        unknown(a, ("id", "description", "gated"), at, err)
        aid = a.get("id")
        if not isinstance(aid, str) or not ACTION_ID.match(aid):
            err(f"{at}.id must be a dotted name such as lineup.event.cancel")
        elif aid.split(".")[0] in CORE_NAMESPACES:
            err(f"{at}.id '{aid}' uses a core namespace; use the product's own, e.g. lineup.")
        if not isinstance(a.get("description"), str) or not a.get("description"):
            err(f"{at}.description is required")
        if not isinstance(a.get("gated"), bool):
            err(f"{at}.gated must be true or false")

    for key, required in (("prohibitions", ("id", "action", "reason")),
                          ("mandates", ("id", "type", "action"))):
        items = p.get(key, [])
        if not isinstance(items, list) or (key == "mandates" and not items):
            err(f"{key} must be a {'non-empty ' if key == 'mandates' else ''}list")
            continue
        for i, m in enumerate(items):
            at = f"{key}[{i}]"
            if not isinstance(m, dict):
                err(f"{at} must be an object")
                continue
            allowed = SCHEMA["properties"]["prohibitions"]["items"]["properties"] if key == "prohibitions" \
                else SCHEMA["$defs"]["mandate"]["properties"]
            unknown(m, allowed, at, err)
            for r in required:
                if r not in m:
                    err(f"{at}: missing '{r}'")
            if "id" in m and (not isinstance(m["id"], str) or not ID.match(m["id"])):
                err(f"{at}.id must be lowercase words joined by dots or hyphens")
            if "action" in m and not isinstance(m["action"], str):
                err(f"{at}.action must be a string")
            if key == "prohibitions" and "reason" in m and (not isinstance(m["reason"], str) or not m["reason"]):
                err(f"{at}.reason must be a non-empty string")
            if key == "mandates" and "type" in m and m["type"] not in (OPEN, CLOSED):
                err(f"{at}.type must be {OPEN} or {CLOSED}")
            for ckey in ("constraints", "unless"):
                if ckey in m:
                    check_constraints(m[ckey], f"{at}.{ckey}", err)
            if "present" in m:
                pr = m["present"]
                if not isinstance(pr, list) or not all(isinstance(x, str) and x for x in pr):
                    err(f"{at}.present must be a list of strings")
                if m.get("type") != CLOSED:
                    err(f"{at}.present only applies to closed mandates")
            if "exception" in m:
                ex = m["exception"]
                if (not isinstance(ex, dict) or set(ex) != {"reason", "source"}
                        or not all(isinstance(x, str) and x for x in ex.values())):
                    err(f"{at}.exception must have exactly reason and source")
    return errors


def resolve(path, seen=()):
    """The merged policy for path: its own entries plus everything it extends."""
    rel = path.relative_to(REPO_ROOT)
    if path in seen:
        raise PolicyError(f"{rel}: extends loops back to itself")
    p = load(path)
    merged = {"actions": {}, "prohibitions": [], "mandates": []}
    ext = p.get("extends")
    if ext:
        if ext.startswith("https://"):
            raise PolicyError(f"{rel}: extends {ext} is remote; the checker only follows repo paths")
        target = (REPO_ROOT / ext).resolve()
        if REPO_ROOT not in target.parents or not target.is_file():
            raise PolicyError(f"{rel}: extends {ext}: no such policy in the repo")
        problems = check(target)
        if problems:
            raise PolicyError(f"{rel}: extends {ext}, which is invalid ({problems[0]})")
        merged = resolve(target, seen + (path,))
    for a in p.get("actions", []):
        merged["actions"][a["id"]] = a["gated"]
    merged["prohibitions"] += p.get("prohibitions", [])
    merged["mandates"] += p.get("mandates", [])
    return merged


def check_merged(merged):
    """Problems that need the whole extends chain: vocabulary, ids, exceptions."""
    errors = []
    err = errors.append
    vocab = {a: False for a in UNGATED} | {a: True for a in GATED} | merged["actions"]
    seen = set()
    for key in ("prohibitions", "mandates"):
        for m in merged[key]:
            mid = m["id"]
            if mid in seen:
                err(f"id '{mid}' is used twice (including policies this one extends)")
            seen.add(mid)
            if m["action"] not in vocab:
                err(f"{mid}: unknown action '{m['action']}'; declare it under actions")
            if key == "mandates" and m["type"] == OPEN and vocab.get(m["action"]):
                kinds = {c["type"] for c in m.get("constraints", [])}
                if "exception" not in m:
                    err(f"{mid}: '{m['action']}' is gated, so an open mandate needs an exception "
                        "with the reason and where it was decided")
                if "action.scope" not in kinds or not kinds & {"action.trigger", "action.condition"}:
                    err(f"{mid}: an open mandate for gated '{m['action']}' must be narrow: "
                        "a scope plus a trigger or condition")
            if key == "mandates" and "exception" in m and not (m["type"] == OPEN and vocab.get(m["action"])):
                err(f"{mid}: exception only applies to an open mandate for a gated action")
    return errors


def holds(c, req):
    kind = c["type"]
    if kind == "action.scope":
        scope = req.get("scope", {})
        return all(scope.get(dim) in values for dim, values in c["scope"].items())
    if kind == "action.trigger":
        return req.get("trigger") in c["events"]
    facts = req.get("facts", {})
    if c["field"] not in facts:
        return False
    value = facts[c["field"]]
    return value == c["equals"] if "equals" in c else value in c["in"]


def decide(merged, req):
    """Return (decision, id of the rule that decided it)."""
    action = req.get("action")
    for p in merged["prohibitions"]:
        if p["action"] == action and all(holds(c, req) for c in p.get("constraints", [])):
            unless = p.get("unless", [])
            if not unless or not all(holds(c, req) for c in unless):
                return "deny", p["id"]
    for kind, decision in ((OPEN, "auto"), (CLOSED, "human")):
        for m in merged["mandates"]:
            if m["type"] == kind and m["action"] == action \
                    and all(holds(c, req) for c in m.get("constraints", [])):
                return decision, m["id"]
    return "deny", None


def run_cases(path, merged):
    errors = []
    cases_path = path.parent / "cases.json"
    if not cases_path.is_file():
        return ["no cases.json beside the policy; add requests and the decision each must get"]
    cases = load(cases_path)
    if not isinstance(cases, list) or not cases:
        return ["cases.json must be a non-empty list"]
    for i, case in enumerate(cases):
        at = f"cases.json[{i}]"
        if (not isinstance(case, dict) or not isinstance(case.get("name"), str)
                or not isinstance(case.get("request"), dict)
                or not isinstance(case["request"].get("action"), str)
                or case.get("decision") not in DECISIONS):
            errors.append(f"{at} needs a name, a request with an action, and a decision "
                          "(auto, human or deny)")
            continue
        req = case["request"]
        if not isinstance(req.get("scope", {}), dict) or not isinstance(req.get("facts", {}), dict):
            errors.append(f"{at}: request scope and facts must be objects")
            continue
        got, rule = decide(merged, req)
        if got != case["decision"]:
            errors.append(f"case '{case['name']}': expected {case['decision']}, "
                          f"got {got} ({'by ' + rule if rule else 'no rule matched'})")
    return errors


def main():
    paths = sorted(HIVE.glob("rules/*/policy.json")) + sorted(HIVE.glob("examples/*/policy.json"))
    if not paths:
        print("FAIL  no approval policies found")
        return 1
    fail, cases = 0, 0
    for path in paths:
        rel = path.relative_to(REPO_ROOT)
        try:
            errors = check(path)
            if not errors:
                merged = resolve(path)
                errors = check_merged(merged) or run_cases(path, merged)
                if not errors:
                    cases += len(load(path.parent / "cases.json"))
        except PolicyError as e:
            msg = str(e)
            errors = [msg[len(f"{rel}: "):] if msg.startswith(f"{rel}: ") else msg]
        for e in errors:
            print(f"FAIL  {rel}: {e}")
        fail |= bool(errors)
    if not fail:
        print(f"OK  {len(paths)} approval policies valid, {cases} cases pass")
    return fail


if __name__ == "__main__":
    sys.exit(main())
