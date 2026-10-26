#!/usr/bin/env python3
"""Validate agents-hive passports against schema/passport.schema.json and their contracts.

Standard library only, so it runs anywhere the hives do. A passport may only narrow its
execution contract, so beyond the schema's shape this checks that:

  - the passport names its own directory, and the persona has an Agent Card
  - its contract and policy exist at the versions it names
  - every action it grants or puts under approval is one the contract grants or puts
    under approval, nothing the contract puts under approval is granted, and no action
    in `never` is granted or under approval
  - each budget figure is at most the contract's
  - each prompt file and the policy file match their pinned SHA-256
  - an eval has a model pin, its suite exists, its critical marks are booleans, and its
    baseline is a results.jsonl entry for this passport and suite, with one run whose
    score is the baseline's and nothing found but a cost flag
  - every delegate has a passport

A digest mismatch prints the file's current digest, so a deliberate change can be pinned.

Usage:
  python3 scripts/validate_passports.py
  python3 scripts/validate_passports.py --digest barry   # print a passport's digest
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

HIVE = Path(__file__).resolve().parent.parent
REPO_ROOT = HIVE.parent.parent
SCHEMA = json.loads((HIVE / "schema" / "passport.schema.json").read_text())
CONTRACT_SCHEMA = json.loads((HIVE / "schema" / "execution-contract.schema.json").read_text())
ACTIONS = set(CONTRACT_SCHEMA["$defs"]["ungated"]["enum"]) | set(CONTRACT_SCHEMA["$defs"]["gated"]["enum"])
PROPS = SCHEMA["properties"]
KEBAB = re.compile(PROPS["passport"]["pattern"])
OWNER = re.compile(PROPS["owner"]["pattern"])
SHA256 = re.compile(SCHEMA["$defs"]["sha256"]["pattern"])
RESULT = re.compile(PROPS["eval"]["properties"]["baseline"]["properties"]["result"]["pattern"])


def canonical(obj):
    """Canonical JSON (docs/assurance-loop.md): keys sorted, no insignificant whitespace, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(passport):
    """The passport's SHA-256, over its canonical JSON; how the other controls name a version."""
    return hashlib.sha256(canonical(passport)).hexdigest()


def file_sha256(path):
    """A pinned file's SHA-256, with CRLF read as LF so a Windows checkout pins the same."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def repo_file(rel):
    """A path from the repo root that stays inside it, or None."""
    if not isinstance(rel, str) or not rel.startswith("hives/") or ".." in Path(rel).parts:
        return None
    return REPO_ROOT / rel


def read_results(path):
    """The entries in a results.jsonl file, by id. Lines that aren't objects with an id are
    skipped; knowledge-hive's checker reports them."""
    found = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and isinstance(entry.get("id"), str):
            found[entry["id"]] = entry
    return found


def baseline_result(ref):
    """The results.jsonl entry a baseline's result names (path#id), or None."""
    if not isinstance(ref, str) or not RESULT.match(ref):
        return None
    path, rid = ref.split("#", 1)
    path = repo_file(path)
    return read_results(path).get(rid) if path is not None and path.is_file() else None


def is_int(v, least):
    return isinstance(v, int) and not isinstance(v, bool) and v >= least


def fields(obj, spec, where, err):
    """Required fields present and no unknown ones, for one object in the schema."""
    if not isinstance(obj, dict):
        err(f"{where} must be an object")
        return False
    for key in spec.get("required", []):
        if key not in obj:
            err(f"{where} is missing '{key}'")
    for key in sorted(set(obj) - set(spec["properties"])):
        err(f"{where} has unknown field '{key}'")
    return True


def check_pin(rel, pinned, where, err):
    path = repo_file(rel)
    if path is None:
        err(f"{where} path must sit under hives/: {rel!r}")
    elif not path.is_file():
        err(f"{where} not found: {rel}")
    elif not isinstance(pinned, str) or not SHA256.match(pinned):
        err(f"{where} sha256 must be 64 lowercase hex digits")
    elif file_sha256(path) != pinned:
        err(f"{where} {rel} doesn't match its pin; its sha256 is now {file_sha256(path)}")


def check(path):
    errors = []
    err = errors.append
    try:
        p = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return [f"not valid JSON: {e}"]
    if not fields(p, SCHEMA, "passport", err):
        return errors

    name = p.get("passport")
    if not isinstance(name, str) or not KEBAB.match(name):
        err("passport must be kebab-case")
    elif name != path.parent.name:
        err(f"passport '{name}' doesn't match its directory '{path.parent.name}'")
    elif not (HIVE / "cards" / name / "card.json").is_file():
        err(f"no Agent Card at cards/{name}/card.json")
    if not is_int(p.get("version"), 1):
        err("version must be an integer of at least 1")
    if not isinstance(p.get("owner"), str) or not OWNER.match(p["owner"]):
        err("owner must be a GitHub account or team, as @account or @org/team")

    contract = None
    c = p.get("contract")
    if fields(c, PROPS["contract"], "contract", err):
        cpath = HIVE / "contracts" / str(c.get("capability")) / "contract.json"
        if not isinstance(c.get("capability"), str) or not cpath.is_file():
            err(f"contract {c.get('capability')!r} not found under contracts/")
        else:
            try:
                contract = json.loads(cpath.read_text())
            except json.JSONDecodeError:
                err(f"contract {c['capability']} is not valid JSON; run validate_contracts.py")
            if contract is not None and contract.get("version") != c.get("version"):
                err(f"contract {c['capability']} is version {contract.get('version')}, not {c.get('version')}")

    policy_file = None
    pol = p.get("policy")
    if fields(pol, PROPS["policy"], "policy", err):
        policy_file = repo_file(pol.get("ruleset"))
        if policy_file is None or not policy_file.is_file():
            err(f"policy ruleset not found: {pol.get('ruleset')!r}")
            policy_file = None
        else:
            try:
                version = json.loads(policy_file.read_text()).get("version")
            except (json.JSONDecodeError, AttributeError):
                version = None
            if version != pol.get("version"):
                err(f"policy {pol['ruleset']} is version {version}, not {pol.get('version')}")

    perms = p.get("permissions")
    if fields(perms, PROPS["permissions"], "permissions", err):
        lists = {}
        for key in ("granted", "approval", "never"):
            items = perms.get(key, [])
            if not isinstance(items, list) or not all(isinstance(a, str) for a in items):
                err(f"permissions.{key} must be a list of action names")
                items = []
            elif len(items) != len(set(items)):
                err(f"permissions.{key} has duplicates")
            for a in items:
                if a not in ACTIONS:
                    err(f"permissions.{key}: unknown action '{a}'")
            lists[key] = set(items)
        for a in sorted(lists["never"] & (lists["granted"] | lists["approval"])):
            err(f"'{a}' is in never and also granted or under approval")
        for a in sorted(lists["granted"] & lists["approval"]):
            err(f"'{a}' is both granted and under approval")
        if contract is not None:
            cperms = contract.get("permissions", {})
            cgranted, capproval = set(cperms.get("granted", [])), set(cperms.get("approval", []))
            for a in sorted(lists["granted"] - cgranted):
                why = "puts it under approval" if a in capproval else "doesn't allow it"
                err(f"grants '{a}', but its contract {why}")
            for a in sorted(lists["approval"] - cgranted - capproval):
                err(f"puts '{a}' under approval, but its contract doesn't allow it")

    budget = p.get("budget")
    if fields(budget, PROPS["budget"], "budget", err):
        if not budget:
            err("budget must set at least one of usd, tokens, seconds")
        cbudget = contract.get("budget", {}) if contract else {}
        for k, val in budget.items():
            if k not in PROPS["budget"]["properties"]:
                continue
            if isinstance(val, bool) or not isinstance(val, (int, float)) or val <= 0:
                err(f"budget.{k} must be a positive number")
            elif k != "usd" and not isinstance(val, int):
                err(f"budget.{k} must be an integer")
            elif contract is not None and k not in cbudget:
                err(f"budget.{k} isn't in its contract's budget")
            elif contract is not None and val > cbudget[k]:
                err(f"budget.{k} is {val}, more than its contract's {cbudget[k]}")

    delegates = p.get("delegates")
    if not isinstance(delegates, list) or not all(isinstance(d, str) for d in delegates):
        err("delegates must be a list of passport names")
    else:
        for d in delegates:
            if d == name:
                err("an agent can't list itself as a delegate")
            elif not (HIVE / "passports" / d / "passport.json").is_file():
                err(f"delegate '{d}' has no passport")

    pins = p.get("pins")
    model = None
    if fields(pins, PROPS["pins"], "pins", err):
        model = pins.get("model")
        if model is not None and fields(model, PROPS["pins"]["properties"]["model"], "pins.model", err):
            for key in ("publisher", "name", "version"):
                if not isinstance(model.get(key), str) or not model[key]:
                    err(f"pins.model.{key} must be a non-empty string")
        prompt = pins.get("prompt")
        if not isinstance(prompt, list) or not prompt:
            err("pins.prompt must list at least one file")
        else:
            seen = set()
            for i, f in enumerate(prompt):
                where = f"pins.prompt[{i}]"
                if fields(f, PROPS["pins"]["properties"]["prompt"]["items"], where, err):
                    if f.get("path") in seen:
                        err(f"{where} repeats {f.get('path')}")
                    seen.add(f.get("path"))
                    check_pin(f.get("path"), f.get("sha256"), where, err)
        ppin = pins.get("policy")
        if fields(ppin, PROPS["pins"]["properties"]["policy"], "pins.policy", err) and policy_file:
            check_pin(pol["ruleset"], ppin.get("sha256"), "pins.policy", err)

    ev = p.get("eval")
    if ev is not None and fields(ev, PROPS["eval"], "eval", err):
        if model is None:
            err("eval needs pins.model: a baseline belongs to a model")
        suite = repo_file(ev.get("suite"))
        cases = None
        if suite is None or not suite.is_file():
            err(f"eval suite not found: {ev.get('suite')!r}")
        else:
            try:
                cases = json.loads(suite.read_text())
            except json.JSONDecodeError:
                err(f"eval suite {ev['suite']} is not valid JSON")
            if isinstance(cases, dict):
                cases = cases.get("cases")
            if cases is not None and not isinstance(cases, list):
                err(f"eval suite {ev['suite']} has no list of cases")
                cases = None
            for case in cases or []:
                if isinstance(case, dict) and not isinstance(case.get("critical", False), bool):
                    err(f"eval suite case {case.get('id')!r}: critical must be true or false")
        base = ev.get("baseline")
        if fields(base, PROPS["eval"]["properties"]["baseline"], "eval.baseline", err):
            met, of = base.get("met"), base.get("of")
            if not is_int(met, 0) or not is_int(of, 1) or met > of:
                err("eval.baseline needs integers met and of, with met no more than of")
            elif isinstance(cases, list) and of != len(cases):
                err(f"eval.baseline.of is {of}, but the suite has {len(cases)} cases")
            ref = base.get("result")
            result = baseline_result(ref)
            record = result.get("eval") if isinstance(result, dict) else None
            runs = record.get("runs") if isinstance(record, dict) else None
            if not isinstance(ref, str) or not RESULT.match(ref):
                err("eval.baseline.result must be a results.jsonl file under hives/ and an entry's id, as path#id")
            elif result is None:
                err(f"eval.baseline.result not found: {ref!r}")
            elif not isinstance(record, dict) or record.get("passport") != name or record.get("suite") != ev.get("suite"):
                err(f"eval.baseline.result {ref} isn't an eval of {name} on {ev.get('suite')}")
            elif not isinstance(runs, list) or len(runs) != 1 or not isinstance(runs[0], dict):
                err(f"eval.baseline.result {ref} must have one run; a run that drifted and was run again isn't a baseline")
            elif (runs[0].get("met"), runs[0].get("of")) != (met, of) or runs[0].get("ran") != of:
                err(f"eval.baseline is {met} of {of}, but its result's run met "
                    f"{runs[0].get('met')} of {runs[0].get('of')} with {runs[0].get('ran')} run")
            elif not isinstance(record.get("findings"), list) or set(map(str, record["findings"])) - {"cost"}:
                err(f"eval.baseline.result {ref} found {', '.join(map(str, record.get('findings') or []))}; "
                    "a baseline can carry only a cost flag")
        if not is_int(ev.get("threshold"), 0):
            err("eval.threshold must be an integer of at least 0")
    return errors


def main():
    ap = argparse.ArgumentParser(description="Validate agents-hive passports.")
    ap.add_argument("--digest", metavar="PERSONA", help="Print a passport's SHA-256 and exit")
    args = ap.parse_args()
    if args.digest:
        path = HIVE / "passports" / args.digest / "passport.json"
        if not path.is_file():
            ap.error(f"no passport at passports/{args.digest}/passport.json")
        print(digest(json.loads(path.read_text())))
        return 0

    passports = sorted((HIVE / "passports").glob("*/passport.json"))
    if not passports:
        print("FAIL  no passports found under passports/")
        return 1
    fail = 0
    for path in passports:
        rel = path.relative_to(REPO_ROOT)
        errors = check(path)
        for e in errors:
            print(f"FAIL  {rel}: {e}")
        fail |= bool(errors)
    for card in sorted((HIVE / "cards").glob("*/card.json")):
        if not (HIVE / "passports" / card.parent.name / "passport.json").is_file():
            print(f"FAIL  {card.relative_to(REPO_ROOT)}: no passport at passports/{card.parent.name}/passport.json")
            fail = 1
    if not fail:
        print(f"OK  {len(passports)} passports valid")
    return fail


if __name__ == "__main__":
    sys.exit(main())
