#!/usr/bin/env python3
"""Check caller registrations, and turn a tool call into the request a policy decides.

A registration (registrations/<caller>/registration.json, schema/registration.schema.json)
is what a caller registers for hosted Barry: its approval policy, its MCP servers in
mcp-hive's format, and for each tool the action it takes and where each scope value, fact
and present item comes from. The model chooses a call's arguments, but it can't vouch for
a fact that unlocks an action (design/hosted-barry.md, "Actions, facts and trust"):

  - scope values come from the call's arguments, or are fixed by the registration;
  - the trigger comes from the caller's request, never from the model;
  - actor.* facts come from the caller's request, and every other fact from a lookup: a
    fact-source tool the server calls itself, with input only from the call that will
    run, its subjects or the caller's request;
  - a fact looked up for each of a call's subjects holds only when it is the same for
    every one; otherwise, or when a lookup fails, it is missing, and a missing fact never
    satisfies a mandate or lets a call escape a prohibition.

A tool the registration doesn't list, or a fact source, is never an action Barry may take:
resolve() refuses it, and the call is denied.

This checks each registration beyond its schema: its policy is the Charter or extends it
and is itself valid, every action is in the policy's vocabulary, every present item is one
the policy presents for that action, every lookup names a fact source, and no fact comes
from the call's arguments. Then it runs the cases.json beside it: each case is a tool call,
the caller's request and what lookups return, and the decision, rule and presented values
the policy must reach for it.

Standard library only.

Usage:
  python3 scripts/registrations.py
"""
import importlib.util
import json
import re
import sys
from pathlib import Path

HIVE = Path(__file__).resolve().parent.parent
REPO_ROOT = HIVE.parent.parent
CHARTER = "hives/rules-hive/rules/queen-charter/policy.json"
SCHEMA = json.loads((HIVE / "schema" / "registration.schema.json").read_text())
KEBAB = re.compile(SCHEMA["properties"]["registration"]["pattern"])
TOOL = re.compile(SCHEMA["properties"]["tools"]["propertyNames"]["pattern"])
PATH = re.compile(SCHEMA["$defs"]["path"]["pattern"])
DECISIONS = {"auto", "human", "deny"}

_spec = importlib.util.spec_from_file_location("check_policy", REPO_ROOT / "hives/rules-hive/scripts/check_policy.py")
policies = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(policies)

# Where each kind of value may come from.
SUBJECTS = {"argument"}
SCOPE = {"argument", "value"}
FACT = {"request", "lookup"}
PRESENT = {"argument", "value", "count", "lookup"}
LOOKUP_INPUT = {"argument", "request", "subject"}
SOURCE_KEYS = {"argument": {"from", "path"}, "value": {"from", "value"}, "request": {"from", "field"},
               "subject": {"from"}, "count": {"from"}, "lookup": {"from", "tool", "input", "path"}}


class RegistrationError(Exception):
    pass


class Unmapped(Exception):
    """A tool call that isn't an action the registration maps, so it is denied."""


def load(path):
    try:
        return json.loads(path.read_text())
    except ValueError as e:
        raise RegistrationError(f"{path.relative_to(REPO_ROOT)}: not valid JSON: {e}")


def policy_path(reg):
    return (REPO_ROOT / reg["policy"]).resolve()


def extends_charter(path, seen=()):
    """Whether the policy at path is the Charter or extends it, through any chain."""
    if path == (REPO_ROOT / CHARTER).resolve():
        return True
    if path in seen or not path.is_file():
        return False
    ext = policies.load(path).get("extends")
    return bool(ext) and extends_charter((REPO_ROOT / ext).resolve(), seen + (path,))


def check_source(src, allowed, at, err, tools, subjects):
    """Problems with one value source, which may come only from the kinds in allowed."""
    if not isinstance(src, dict) or src.get("from") not in SOURCE_KEYS:
        err(f"{at} must be a source: an object whose from is one of {', '.join(sorted(allowed))}")
        return
    kind = src["from"]
    if kind not in allowed:
        if kind == "argument" and "subject" not in allowed and "count" not in allowed:
            err(f"{at} comes from the call's arguments, which the model chooses; "
                "a fact must come from the caller's request or a lookup")
        else:
            err(f"{at} can't come from {kind}; only from {', '.join(sorted(allowed))}")
        return
    extra = set(src) - SOURCE_KEYS[kind]
    missing = SOURCE_KEYS[kind] - set(src)
    if extra or missing:
        err(f"{at}: a {kind} source has exactly {', '.join(sorted(SOURCE_KEYS[kind]))}")
        return
    for key in ("path", "field"):
        if key in src and (not isinstance(src[key], str) or not PATH.fullmatch(src[key])):
            err(f"{at}.{key} must be dotted names, such as recipients or actor.role")
    if kind == "value" and (not isinstance(src["value"], (str, int, float, bool))):
        err(f"{at}.value must be a string, a number or true or false")
    if kind in ("subject", "count") and not subjects:
        err(f"{at} needs the tool's subjects, which it doesn't declare")
    if kind == "lookup":
        source = tools.get(src["tool"]) if isinstance(src["tool"], str) else None
        if not isinstance(source, dict) or source.get("fact_source") is not True:
            err(f"{at}.tool '{src['tool']}' isn't one of the registration's fact sources")
        if not isinstance(src["input"], dict):
            err(f"{at}.input must be an object")
            return
        for name, inner in src["input"].items():
            check_source(inner, LOOKUP_INPUT, f"{at}.input.{name}", err, tools, subjects)


def check(path):
    """Problems with one registration, with its policy's merged rules (or None)."""
    errors = []
    err = errors.append
    reg = load(path)
    if not isinstance(reg, dict):
        return ["registration must be a JSON object"], None
    for key in sorted(set(reg) - set(SCHEMA["properties"])):
        err(f"unknown key '{key}'")
    for key in SCHEMA["required"]:
        if key not in reg:
            err(f"missing '{key}'")
    if errors:
        return errors, None
    name = reg["registration"]
    if not isinstance(name, str) or not KEBAB.fullmatch(name):
        err("registration must be kebab-case")
    elif name != path.parent.name:
        err(f"registration '{name}' doesn't match its directory '{path.parent.name}'")
    v = reg["version"]
    if not isinstance(v, int) or isinstance(v, bool) or v < 1:
        err("version must be an integer of at least 1")
    if not isinstance(reg["description"], str) or not reg["description"]:
        err("description must be a non-empty string")

    merged = None
    pol = reg["policy"]
    if not isinstance(pol, str) or not pol.startswith("hives/") or not policy_path(reg).is_file() \
            or REPO_ROOT not in policy_path(reg).parents:
        err(f"policy {pol}: no such policy in the repo")
    elif not extends_charter(policy_path(reg)):
        err(f"policy {pol} doesn't extend the Queen Bee's Charter ({CHARTER}), "
            "so the actions it gates wouldn't stay gated")
    else:
        try:
            problems = policies.check(policy_path(reg))
            merged = policies.resolve(policy_path(reg)) if not problems else None
            problems = problems or policies.check_merged(merged)
        except policies.PolicyError as e:
            problems = [str(e)]
        if problems:
            err(f"policy {pol} is invalid ({problems[0]})")
            merged = None

    servers = set()
    if not isinstance(reg["servers"], list) or not reg["servers"]:
        err("servers must be a non-empty list")
    else:
        for i, s in enumerate(reg["servers"]):
            at = f"servers[{i}]"
            if not isinstance(s, dict) or set(s) != {"mcp", "token_scope"}:
                err(f"{at} must have exactly mcp and token_scope")
                continue
            if not isinstance(s["token_scope"], str) or not s["token_scope"]:
                err(f"{at}.token_scope must be a non-empty string")
            m = s["mcp"]
            if not isinstance(m, dict):
                err(f"{at}.mcp must be an mcp-hive server entry")
                continue
            if not isinstance(m.get("name"), str) or not KEBAB.fullmatch(m["name"]):
                err(f"{at}.mcp.name must be kebab-case")
            elif m["name"] in servers:
                err(f"{at}.mcp.name '{m['name']}' is registered twice")
            else:
                servers.add(m["name"])
            if not isinstance(m.get("description"), str) or not m.get("description"):
                err(f"{at}.mcp.description is required")
            if "config" in m or m.get("transport") != "streamable-http":
                err(f"{at}.mcp must be a remote server (transport streamable-http, no config): "
                    "hosted Barry runs no local processes")
            d = m.get("discovery")
            https = lambda u: isinstance(u, str) and u.startswith("https://")  # noqa: E731
            if not isinstance(d, dict) or not (
                    (set(d) == {"card"} and https(d["card"]))
                    or (set(d) == {"catalog", "identifier"} and https(d["catalog"])
                        and isinstance(d["identifier"], str) and d["identifier"])):
                err(f"{at}.mcp.discovery must name an https Server Card, or an https AI Catalog "
                    "and the card's identifier in it")

    tools = reg["tools"]
    if not isinstance(tools, dict) or not tools:
        err("tools must be a non-empty object")
        return errors, merged
    vocab = None
    if merged is not None:
        vocab = set(policies.UNGATED) | set(policies.GATED) | set(merged["actions"])
    for key, t in tools.items():
        at = f"tools['{key}']"
        if not TOOL.fullmatch(key):
            err(f"{at}: a tool is named <server>/<tool>")
            continue
        if key.split("/")[0] not in servers:
            err(f"{at}: no registered server named '{key.split('/')[0]}'")
        if not isinstance(t, dict) or not ("action" in t or "fact_source" in t):
            err(f"{at} has no map: give the action it takes, or mark it a fact source")
            continue
        if "fact_source" in t:
            if t["fact_source"] is not True or set(t) - {"fact_source", "description"}:
                err(f"{at}: a fact source has fact_source true, and at most a description")
            continue
        for k in sorted(set(t) - {"action", "subjects", "scope", "facts", "present"}):
            err(f"{at}: unknown key '{k}'")
        action = t["action"]
        if vocab is not None and action not in vocab:
            err(f"{at}: unknown action '{action}'; it isn't in {pol}'s vocabulary")
        subjects = "subjects" in t
        if subjects:
            check_source(t["subjects"], SUBJECTS, f"{at}.subjects", err, tools, False)
        for section, allowed in (("scope", SCOPE), ("facts", FACT), ("present", PRESENT)):
            entries = t.get(section, {})
            if not isinstance(entries, dict):
                err(f"{at}.{section} must be an object")
                continue
            for name, src in entries.items():
                check_source(src, allowed, f"{at}.{section}['{name}']", err, tools, subjects)
                if section == "facts" and isinstance(src, dict):
                    if src.get("from") == "request" and not name.startswith("actor."):
                        err(f"{at}.facts['{name}'] comes from the caller's request, which "
                            "vouches only for actor.* facts; look it up instead")
                    if src.get("from") == "lookup" and name.startswith("actor."):
                        err(f"{at}.facts['{name}'] is about the actor, so it comes from the caller's request")
                    if src.get("from") == "request" and src.get("field") != name:
                        err(f"{at}.facts['{name}'] must come from the request's own {name}")
                if section == "present" and isinstance(src, dict) and src.get("from") == "lookup" \
                        and any(isinstance(i, dict) and i.get("from") == "subject"
                                for i in (src.get("input") or {}).values()):
                    err(f"{at}.present['{name}'] is shown once, so its lookup can't be made per subject")
        if merged is not None:
            shown = {x for m in merged["mandates"] if m["action"] == action for x in m.get("present", [])}
            for name in t.get("present", {}) if isinstance(t.get("present"), dict) else ():
                if name not in shown:
                    err(f"{at}.present['{name}']: no mandate for '{action}' presents it")
    return errors, merged


def _at(obj, path):
    for part in path.split("."):
        if not isinstance(obj, dict) or part not in obj:
            return None
        obj = obj[part]
    return obj


def _scalar(v):
    return v if isinstance(v, (str, int, float, bool)) else None


def resolve(reg, tool, arguments, request, lookup):
    """The policy request a tool call makes, and the values of its present items.

    arguments are the model's; request is the caller's request metadata, with its trigger
    and its facts; lookup(tool, input) calls a fact source and returns its result object,
    or None when it fails. Raises Unmapped for a tool that isn't a mapped action. A value
    that can't be found is left out: a missing scope or fact, or a present item of None."""
    t = reg["tools"].get(tool)
    if not isinstance(t, dict) or "action" not in t:
        raise Unmapped(f"{tool} isn't an action {reg['registration']}'s registration maps")
    request = request if isinstance(request, dict) else {}
    told = request.get("facts") if isinstance(request.get("facts"), dict) else {}
    subjects = None
    if "subjects" in t:
        listed = _at(arguments, t["subjects"]["path"])
        if isinstance(listed, list) and all(_scalar(s) is not None for s in listed):
            subjects = listed

    def value(src, subject=None):
        kind = src["from"]
        if kind == "argument":
            return _at(arguments, src["path"])
        if kind == "value":
            return src["value"]
        if kind == "request":
            return told.get(src["field"])
        if kind == "subject":
            return subject
        if kind == "count":
            return len(subjects) if subjects is not None else None
        # A lookup, made once, or once for each subject when its input names one.
        per_subject = any(i["from"] == "subject" for i in src["input"].values())
        if per_subject and not subjects:
            return None
        found = []
        for s in (subjects if per_subject else [None]):
            given = {k: value(i, s) for k, i in src["input"].items()}
            if any(v is None for v in given.values()):
                return None
            result = lookup(src["tool"], given)
            got = _scalar(_at(result, src["path"])) if isinstance(result, dict) else None
            if got is None:
                return None
            found.append(got)
        first = found[0]
        return first if all(policies.same(first, f) for f in found) else None

    req = {"action": t["action"]}
    scope = {d: _scalar(value(s)) for d, s in t.get("scope", {}).items()}
    req["scope"] = {d: v for d, v in scope.items() if v is not None}
    if isinstance(request.get("trigger"), str):
        req["trigger"] = request["trigger"]
    facts = {f: _scalar(value(s)) for f, s in t.get("facts", {}).items()}
    req["facts"] = {f: v for f, v in facts.items() if v is not None}
    present = {n: value(s) for n, s in t.get("present", {}).items()}
    return req, present


def run_cases(path, reg, merged):
    errors = []
    cases_path = path.parent / "cases.json"
    if not cases_path.is_file():
        return ["no cases.json beside the registration; add tool calls and the decision each must get"]
    cases = load(cases_path)
    if not isinstance(cases, list) or not cases:
        return ["cases.json must be a non-empty list"]
    for i, case in enumerate(cases):
        at = f"cases.json[{i}]"
        if (not isinstance(case, dict) or not isinstance(case.get("name"), str)
                or not isinstance(case.get("tool"), str) or not isinstance(case.get("arguments", {}), dict)
                or not isinstance(case.get("request", {}), dict) or not isinstance(case.get("lookups", []), list)
                or case.get("decision") not in DECISIONS):
            errors.append(f"{at} needs a name, a tool, and a decision (auto, human or deny); "
                          "arguments and request are objects, lookups a list")
            continue
        made = case.get("lookups", [])

        def lookup(tool, given):
            for m in made:
                if isinstance(m, dict) and m.get("tool") == tool and m.get("input") == given:
                    return m.get("result")
            return None

        try:
            req, values = resolve(reg, case["tool"], case.get("arguments", {}), case.get("request", {}), lookup)
            got, rule, shown = policies.decide(merged, req)
        except Unmapped:
            req, got, rule, shown, values = None, "deny", None, [], {}
        presented = {n: values.get(n) for n in shown}
        name = case["name"]
        if got != case["decision"]:
            errors.append(f"case '{name}': expected {case['decision']}, got {got} "
                          f"({'by ' + rule if rule else 'no rule matched'}) for {json.dumps(req)}")
        elif "rule" in case and rule != case["rule"]:
            errors.append(f"case '{name}': expected rule {case['rule']}, got {rule}")
        elif "facts" in case and req["facts"] != case["facts"]:
            errors.append(f"case '{name}': expected facts {json.dumps(case['facts'])}, got {json.dumps(req['facts'])}")
        elif "present" in case and presented != case["present"]:
            errors.append(f"case '{name}': expected present {json.dumps(case['present'])}, "
                          f"got {json.dumps(presented)}")
    return errors


def main():
    paths = sorted(HIVE.glob("registrations/*/registration.json"))
    if not paths:
        print("FAIL  no caller registrations found")
        return 1
    fail, cases = 0, 0
    for path in paths:
        rel = path.relative_to(REPO_ROOT)
        try:
            errors, merged = check(path)
            if not errors:
                errors = run_cases(path, load(path), merged)
                if not errors:
                    cases += len(load(path.parent / "cases.json"))
        except RegistrationError as e:
            msg = str(e)
            errors = [msg[len(f"{rel}: "):] if msg.startswith(f"{rel}: ") else msg]
        for e in errors:
            print(f"FAIL  {rel}: {e}")
        fail |= bool(errors)
    if not fail:
        print(f"OK  {len(paths)} caller registration{'s' if len(paths) != 1 else ''} valid, {cases} cases pass")
    return fail


if __name__ == "__main__":
    sys.exit(main())
