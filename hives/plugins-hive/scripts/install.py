#!/usr/bin/env python3
"""Install a plugins-hive pack — one command that fans out to all four hives.

A pack is a manifest (packs/<name>/pack.json) that names which skills, rules,
MCP servers, and agents to install, and for which harnesses. This installer
resolves the sibling hives (ai-hive's hives/) and invokes each hive's own
installer, so the whole House ships together.

Usage:
  python3 scripts/install.py werkrbee-core --dir /path/to/project
  python3 scripts/install.py werkrbee-core --dry-run
  python3 scripts/install.py werkrbee-core --hives-dir ~/src/ai-hive/hives
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def resolve_hives_dir(override):
    if override:
        return Path(override).expanduser().resolve()
    # Prefer ./hives, else sibling dirs next to plugins-hive (ai-hive's hives/ layout).
    if (REPO_ROOT / "hives").is_dir():
        return REPO_ROOT / "hives"
    return REPO_ROOT.parent


def hive_path(hives_dir, name):
    p = hives_dir / f"{name}-hive"
    return p if p.is_dir() else None


def run(cmd, dry):
    printable = " ".join(str(c) for c in cmd)
    print(f"$ {printable}")
    if dry:
        return
    subprocess.run(cmd, check=True)


def main():
    ap = argparse.ArgumentParser(description="Install a plugins-hive pack across all four hives.")
    ap.add_argument("pack", nargs="?", default="werkrbee-core", help="Pack name under packs/ (default: werkrbee-core)")
    ap.add_argument("--dir", default=".", help="Project directory for rules/mcp/agents (default: current)")
    ap.add_argument("--hives-dir", default="", help="Directory containing the *-hive dirs, e.g. ai-hive's hives/ (default: ./hives or sibling dirs)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    manifest_path = REPO_ROOT / "packs" / args.pack / "pack.json"
    if not manifest_path.is_file():
        print(f"pack not found: {manifest_path}", file=sys.stderr)
        sys.exit(1)
    pack = json.loads(manifest_path.read_text())

    hives_dir = resolve_hives_dir(args.hives_dir)
    harnesses = pack.get("harnesses", [])
    hflags = []
    for h in harnesses:
        hflags += ["--harness", h]

    print(f"Installing pack '{pack['name']}' v{pack.get('version','?')}")
    print(f"  harnesses: {', '.join(harnesses)}")
    print(f"  hives dir: {hives_dir}\n")

    missing = []

    # 1) skills (global capabilities)
    if pack.get("skills"):
        d = hive_path(hives_dir, "skills")
        if d:
            cmd = ["bash", str(d / "scripts/install.sh"), "--global"] + hflags
            for s in pack["skills"]:
                cmd += ["--skill", s]
            run(cmd, args.dry_run)
        else:
            missing.append("skills-hive")

    # 2) rules (per-project instruction files; one call per ruleset)
    if pack.get("rules"):
        d = hive_path(hives_dir, "rules")
        if d:
            for r in pack["rules"]:
                cmd = ["bash", str(d / "scripts/install.sh"), "--dir", args.dir, "--ruleset", r] + hflags
                run(cmd, args.dry_run)
        else:
            missing.append("rules-hive")

    # 3) mcp (tool configs merged into the project)
    if pack.get("mcp"):
        d = hive_path(hives_dir, "mcp")
        if d:
            cmd = ["python3", str(d / "scripts/install.py"), "--dir", args.dir] + hflags
            for s in pack["mcp"]:
                cmd += ["--server", s]
            run(cmd, args.dry_run)
        else:
            missing.append("mcp-hive")

    # 4) agents (personas rendered into the project)
    if pack.get("agents"):
        d = hive_path(hives_dir, "agents")
        if d:
            cmd = ["python3", str(d / "scripts/install.py"), "--dir", args.dir] + hflags
            for a in pack["agents"]:
                cmd += ["--agent", a]
            run(cmd, args.dry_run)
        else:
            missing.append("agents-hive")

    print()
    if missing:
        print(f"WARNING: could not find {', '.join(missing)} under {hives_dir}.", file=sys.stderr)
        print("Every hive ships in the ai-hive monorepo (git clone https://github.com/werkrbee/ai-hive);", file=sys.stderr)
        print("run this from its hives/plugins-hive, or pass --hives-dir pointing at its hives/.", file=sys.stderr)
        sys.exit(2)
    print(f"Pack '{pack['name']}' installed.")


if __name__ == "__main__":
    main()
