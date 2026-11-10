#!/usr/bin/env python3
"""Read harnesses.json, the harness registry, for every installer and page.

The registry is the only place a harness, its category and tier, and its install paths
are written down (docs/harness-ecosystem.md). Python installers import this module; shell
installers call it. `check` is what CI runs: the registry is well formed, each hive's
adapters/ matches it, and each README that draws an adapters/ tree names every adapter.

Standard library only.

Usage:
  python3 scripts/harnesses.py path SURFACE SCOPE HARNESS [--name NAME]
      print where HARNESS reads SURFACE (skills, rules, agents) at SCOPE (global or
      project), with ~ expanded and {name} filled in; exit 1 if it has none
  python3 scripts/harnesses.py list [--surface SURFACE] [--category CATEGORY]
      print harness ids, one per line, in registry order
  python3 scripts/harnesses.py check
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "harnesses.json"
SURFACES = ("skills", "rules", "agents")
SCOPES = ("global", "project")


def load(path=REGISTRY):
    return json.loads(Path(path).read_text())


def harnesses(registry=None, surface=None, category=None):
    """The harness entries, in registry order, optionally only those with SURFACE or in CATEGORY."""
    out = []
    for h in (registry or load())["harnesses"]:
        if surface and surface not in h["surfaces"]:
            continue
        if category and h["category"] != category:
            continue
        out.append(h)
    return out


def get(harness_id, registry=None):
    for h in (registry or load())["harnesses"]:
        if h["id"] == harness_id:
            return h
    return None


def surface(harness_id, name, registry=None):
    """HARNESS's entry for surface NAME, or None. A fallback is returned as written."""
    h = get(harness_id, registry)
    return h["surfaces"].get(name) if h else None


def path(harness_id, name, scope, fill=None, registry=None):
    """Where HARNESS reads surface NAME at SCOPE, expanded, or None if it has none."""
    s = surface(harness_id, name, registry)
    if not s or scope not in s:
        return None
    p = s[scope]
    if fill is not None:
        p = p.replace("{name}", fill)
    return os.path.expanduser(p)


def adapters(registry=None):
    """Top-level adapter directory -> display name, in registry order."""
    return {h["adapter"]: h["name"] for h in (registry or load())["harnesses"]
            if h.get("adapter") and "/" not in h["adapter"]}


def check(registry=None):
    """Problems with the registry and what must agree with it; empty when all is well."""
    reg = registry or load()
    problems = []
    entries = reg["harnesses"]
    ids = [h["id"] for h in entries]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        problems.append(f"harness id {dup!r} appears more than once")

    for h in entries:
        where = f"harness {h['id']!r}"
        if h["category"] not in reg["categories"]:
            problems.append(f"{where}: unknown category {h['category']!r}")
        if h["tier"] is not None and h["tier"] not in reg["tiers"]:
            problems.append(f"{where}: unknown tier {h['tier']!r}")
        if (h["tier"] == "top-ten") != (h["rank"] is not None):
            problems.append(f"{where}: a rank goes with the top-ten tier, and only with it")
        if h.get("parent") and h["parent"] not in ids:
            problems.append(f"{where}: parent {h['parent']!r} isn't a harness")
        for name, s in h["surfaces"].items():
            if name not in SURFACES:
                problems.append(f"{where}: unknown surface {name!r}")
            elif "fallback" in s:
                target = surface(s["fallback"], name, reg)
                if not target or "fallback" in target:
                    problems.append(f"{where}: {name} falls back to {s['fallback']!r}, which has no {name} paths")
            elif not any(scope in s for scope in SCOPES):
                problems.append(f"{where}: {name} has neither a global nor a project path")

    for cat in ("pro-code", "low-code"):
        ranks = sorted(h["rank"] for h in entries if h["category"] == cat and h["tier"] == "top-ten")
        if ranks != list(range(1, 11)):
            problems.append(f"{cat}: the top ten must be ranked 1 to 10, found {ranks}")

    expected = set(adapters(reg))
    nested = {h["adapter"] for h in entries if h.get("adapter") and "/" in h["adapter"]}
    for hive in sorted(p for p in (ROOT / "hives").glob("*/adapters") if p.is_dir()):
        rel = hive.relative_to(ROOT)
        found = {p.name for p in hive.iterdir() if p.is_dir()}
        for name in sorted(expected - found):
            problems.append(f"{rel}/: missing {name}/ (in harnesses.json)")
        for name in sorted(found - expected):
            problems.append(f"{rel}/: {name}/ isn't in harnesses.json")
        for sub in sorted(nested):
            if sub.split("/")[0] in found and not (hive / sub).is_dir():
                problems.append(f"{rel}/: missing {sub}/ (in harnesses.json)")
        readme = hive.parent / "README.md"
        if readme.is_file():
            text = readme.read_text()
            for name in sorted(expected):
                if f"{name}/" not in text:
                    problems.append(f"{readme.relative_to(ROOT)}: its adapters/ tree doesn't name {name}/")
    taxonomy = ROOT / "hives" / "skills-hive" / "adapters" / "README.md"
    if taxonomy.is_file():
        text = taxonomy.read_text()
        for name in sorted(expected):
            if f"{name}/" not in text:
                problems.append(f"{taxonomy.relative_to(ROOT)}: doesn't name {name}/")
    return problems


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    cmd, args = argv[0], argv[1:]
    opts = {}
    rest = []
    while args:
        a = args.pop(0)
        if a in ("--name", "--surface", "--category") and args:
            opts[a[2:]] = args.pop(0)
        else:
            rest.append(a)

    if cmd == "path" and len(rest) == 3:
        name, scope, harness_id = rest
        if name not in SURFACES or scope not in SCOPES:
            print(f"usage: harnesses.py path {{{','.join(SURFACES)}}} {{{','.join(SCOPES)}}} HARNESS",
                  file=sys.stderr)
            return 2
        p = path(harness_id, name, scope, opts.get("name"))
        if p is None:
            return 1
        print(p)
        return 0
    if cmd == "list" and not rest:
        for h in harnesses(surface=opts.get("surface"), category=opts.get("category")):
            print(h["id"])
        return 0
    if cmd == "check" and not rest:
        problems = check()
        for p in problems:
            print(f"FAIL  {p}")
        if problems:
            return 1
        print(f"OK  {REGISTRY.name} and the adapters/ trees agree")
        return 0
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
