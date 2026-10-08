#!/usr/bin/env python3
"""Validate agents-hive execution contracts against schema/execution-contract.schema.json.

Standard library only, so it runs anywhere the hives do. It checks the parts of the
schema that matter for replaceable workers: required fields and no unknown ones, a
kebab-case capability that matches its directory, object schemas for inputs and output,
positive budget ceilings, permissions drawn from the schema's vocabulary with gated
ones only under approval, and fulfilledBy paths that exist in the repo.

Usage:
  python3 scripts/validate_contracts.py
"""
import json
import re
import sys
from pathlib import Path

HIVE = Path(__file__).resolve().parent.parent
REPO_ROOT = HIVE.parent.parent
SCHEMA = json.loads((HIVE / "schema" / "execution-contract.schema.json").read_text())
KEBAB = re.compile(SCHEMA["properties"]["capability"]["pattern"])
UNGATED = set(SCHEMA["$defs"]["ungated"]["enum"])
GATED = set(SCHEMA["$defs"]["gated"]["enum"])
ARTIFACT = {"skill": "SKILL.md", "agent": "agent.md"}


def check(path):
    errors = []
    err = errors.append
    try:
        c = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return [f"not valid JSON: {e}"]
    if not isinstance(c, dict):
        return ["contract must be a JSON object"]

    for key in SCHEMA["required"]:
        if key not in c:
            err(f"missing '{key}'")
    for key in set(c) - set(SCHEMA["properties"]):
        err(f"unknown field '{key}'")

    cap = c.get("capability")
    if not isinstance(cap, str) or not KEBAB.match(cap):
        err("capability must be kebab-case")
    elif cap != path.parent.name:
        err(f"capability '{cap}' doesn't match its directory '{path.parent.name}'")
    v = c.get("version")
    if not isinstance(v, int) or isinstance(v, bool) or v < 1:
        err("version must be an integer of at least 1")
    if not isinstance(c.get("description"), str) or not c.get("description"):
        err("description must be a non-empty string")

    for key in ("inputs", "output"):
        s = c.get(key)
        if not isinstance(s, dict) or s.get("type") != "object":
            err(f"{key} must be a JSON Schema with type 'object'")

    budget = c.get("budget")
    if not isinstance(budget, dict) or not budget:
        err("budget must set at least one of usd, tokens, seconds")
    else:
        for k, val in budget.items():
            if k not in ("usd", "tokens", "seconds"):
                err(f"unknown budget field '{k}'")
            elif isinstance(val, bool) or not isinstance(val, (int, float)) or val <= 0:
                err(f"budget.{k} must be a positive number")
            elif k != "usd" and not isinstance(val, int):
                err(f"budget.{k} must be an integer")

    perms = c.get("permissions")
    if not isinstance(perms, dict) or set(perms) != {"granted", "approval"}:
        err("permissions must have exactly 'granted' and 'approval'")
    else:
        granted, approval = perms["granted"], perms["approval"]
        for name, items in (("granted", granted), ("approval", approval)):
            if not isinstance(items, list) or len(items) != len(set(items)):
                err(f"permissions.{name} must be a list without duplicates")
        for p in granted:
            if p in GATED:
                err(f"'{p}' is gated by the Charter; it can only appear under approval")
            elif p not in UNGATED:
                err(f"unknown permission '{p}'")
        for p in approval:
            if p not in UNGATED | GATED:
                err(f"unknown permission '{p}'")
        for p in set(granted) & set(approval):
            err(f"'{p}' is both granted and under approval")

    impls = c.get("fulfilledBy")
    if not isinstance(impls, list) or not impls:
        err("fulfilledBy must list at least one skill or agent")
    else:
        for i in impls:
            kind, rel = i.get("kind"), i.get("path", "")
            if kind not in ARTIFACT:
                err(f"fulfilledBy kind must be skill or agent, not '{kind}'")
            elif not (REPO_ROOT / rel / ARTIFACT[kind]).is_file():
                err(f"fulfilledBy {kind} not found: {rel}/{ARTIFACT[kind]}")
    return errors


def main():
    contracts = sorted((HIVE / "contracts").glob("*/contract.json"))
    if not contracts:
        print("FAIL  no contracts found under contracts/")
        return 1
    fail = 0
    for path in contracts:
        rel = path.relative_to(REPO_ROOT)
        errors = check(path)
        for e in errors:
            print(f"FAIL  {rel}: {e}")
        fail |= bool(errors)
    if not fail:
        print(f"OK  {len(contracts)} execution contracts valid")
    return fail


if __name__ == "__main__":
    sys.exit(main())
