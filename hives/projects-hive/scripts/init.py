#!/usr/bin/env python3
"""Scaffold a new werkrbee initiative and wire in the House of Hives.

A scaffold (scaffolds/<name>/) is a project template plus a manifest naming which
plugins-hive pack to install. This creates a new project directory from the
template, then calls plugins-hive to fan the pack out to all four hives — so a
ready-to-work initiative is one command away.

Usage:
  python3 scripts/init.py --name "Payments Revamp"
  python3 scripts/init.py werkrbee-initiative --name "Q3 Migration" --dir ~/Projects/q3
  python3 scripts/init.py --name "Demo" --dry-run
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "project"


def resolve_hives_dir(override):
    if override:
        return Path(override).expanduser().resolve()
    if (REPO_ROOT / "hives").is_dir():
        return REPO_ROOT / "hives"
    return REPO_ROOT.parent


def main():
    ap = argparse.ArgumentParser(description="Scaffold a werkrbee initiative.")
    ap.add_argument("scaffold", nargs="?", default="werkrbee-initiative",
                    help="Scaffold under scaffolds/ (default: werkrbee-initiative)")
    ap.add_argument("--name", required=True, help="Project name")
    ap.add_argument("--description", default="", help="Override the project description")
    ap.add_argument("--dir", default="", help="Where to create the project (default: ~/Projects/<slug>)")
    ap.add_argument("--hives-dir", default="", help="Where the *-hive repos live (default: ./hives or siblings)")
    ap.add_argument("--force", action="store_true",
                    help="Override the guardrail that blocks scaffolding inside a hive repo")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sc_dir = REPO_ROOT / "scaffolds" / args.scaffold
    manifest = sc_dir / "scaffold.json"
    if not manifest.is_file():
        print(f"scaffold not found: {manifest}", file=sys.stderr)
        sys.exit(1)
    sc = json.loads(manifest.read_text())

    slug = slugify(args.name)
    # Default outside the repos, in ~/Projects — never the current directory,
    # which is often *inside* a hive when you're running this script.
    target = (Path(args.dir).expanduser() if args.dir else (Path.home() / "Projects" / slug)).resolve()
    desc = args.description or sc.get("description", "")
    subs = {"{{PROJECT_NAME}}": args.name, "{{PROJECT_SLUG}}": slug, "{{DESCRIPTION}}": desc}

    # Guardrail: refuse to scaffold inside a hive repo or the hives/ tree — an
    # initiative dropped in there mixes project files into a hive (that's the ai-hive/ai-hive
    # nesting trap). Ancestors named "*-hive" or "hives" are off-limits.
    if not args.force:
        for p in [target, *target.parents]:
            if p.name == "hives" or p.name.endswith("-hive"):
                print(f"refusing to scaffold inside a hive repo: {p}", file=sys.stderr)
                print("Initiatives should live outside the *-hive repos. Use "
                      "--dir ~/Projects/<name> (or --force to override).", file=sys.stderr)
                sys.exit(1)

    print(f"Scaffolding '{args.name}' from '{sc['name']}' -> {target}\n")
    if target.exists() and any(target.iterdir()):
        print(f"target exists and is not empty: {target}", file=sys.stderr)
        sys.exit(1)

    # 1) copy the template with placeholder substitution
    tpl = sc_dir / "template"
    for src in sorted(tpl.rglob("*")):
        rel = src.relative_to(tpl)
        dst = target / rel
        if src.is_dir():
            if not args.dry_run:
                dst.mkdir(parents=True, exist_ok=True)
            continue
        text = src.read_text()
        for k, v in subs.items():
            text = text.replace(k, v)
        if args.dry_run:
            print(f"[dry-run] write {dst}")
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(text)
            print(f"wrote: {dst}")

    # 2) install the pack via plugins-hive
    hives_dir = resolve_hives_dir(args.hives_dir)
    plugins = hives_dir / "plugins-hive"
    cmd = ["python3", str(plugins / "scripts/install.py"), sc["pack"], "--dir", str(target)]
    if args.hives_dir:
        cmd += ["--hives-dir", str(hives_dir)]
    if args.dry_run:
        cmd += ["--dry-run"]

    if not (plugins / "scripts/install.py").is_file():
        msg = f"plugins-hive not found at {plugins}"
        if args.dry_run:
            print(f"\n[dry-run] would run: {' '.join(cmd)}  ({msg})")
        else:
            print(f"WARNING: {msg}; scaffold created but pack not installed.", file=sys.stderr)
            print("Clone plugins-hive + the four hives beside this repo, or pass --hives-dir.", file=sys.stderr)
            sys.exit(2)
    else:
        print("\n$ " + " ".join(cmd))
        subprocess.run(cmd, check=True)

    print(f"\nInitiative '{args.name}' ready at {target}")


if __name__ == "__main__":
    main()
