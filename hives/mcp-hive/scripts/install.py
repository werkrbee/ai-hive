#!/usr/bin/env python3
"""Merge mcp-hive server definitions into each harness's MCP config.

MCP config formats differ across harnesses (JSON vs TOML vs YAML), so this
installer merges into the JSON-based configs directly and prints ready-to-paste
snippets for the others. Merges are non-destructive: existing servers and other
keys are preserved.

Usage:
  python3 scripts/install.py --dir /path/to/project
  python3 scripts/install.py --harness cursor --server filesystem --server git
  python3 scripts/install.py --global --harness claude-code
  python3 scripts/install.py --dry-run
"""
import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVERS_DIR = REPO_ROOT / "servers"

# harness -> where its JSON MCP config lives and which key holds the servers
JSON_TARGETS = {
    "claude-code":    {"project": ".mcp.json",         "global": "~/.claude.json",     "key": "mcpServers"},
    "cursor":         {"project": ".cursor/mcp.json",  "global": "~/.cursor/mcp.json", "key": "mcpServers"},
    "github-copilot": {"project": ".vscode/mcp.json",  "global": None,                 "key": "servers"},
}
# harnesses whose config isn't JSON — we print a snippet instead
SNIPPET_TARGETS = {"codex": "toml", "goose": "yaml"}


def load_servers(names):
    servers = {}
    for d in sorted(SERVERS_DIR.iterdir()):
        f = d / "mcp.json"
        if not f.is_file():
            continue
        spec = json.loads(f.read_text())
        if names and spec["name"] not in names:
            continue
        servers[spec["name"]] = spec
    missing = set(names) - set(servers) if names else set()
    for m in missing:
        print(f"warning: server not found: {m}", file=sys.stderr)
    return servers


def substitute(obj, workspace):
    if isinstance(obj, str):
        return obj.replace("${WORKSPACE}", workspace)
    if isinstance(obj, list):
        return [substitute(x, workspace) for x in obj]
    if isinstance(obj, dict):
        return {k: substitute(v, workspace) for k, v in obj.items()}
    return obj


def merge_json(path, key, servers, workspace, dry):
    path = Path(os.path.expanduser(path))
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text() or "{}")
        except json.JSONDecodeError:
            print(f"warning: {path} is not valid JSON; leaving it alone", file=sys.stderr)
            return
    data.setdefault(key, {})
    for name, spec in servers.items():
        data[key][name] = substitute(spec["config"], workspace)
    if dry:
        print(f"[dry-run] would write {path}:\n{json.dumps(data, indent=2)}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
    print(f"merged {len(servers)} server(s) -> {path}")


def print_snippet(fmt, servers, workspace):
    print(f"\n# --- add to your {fmt.upper()} config ---")
    if fmt == "toml":
        for name, spec in servers.items():
            c = substitute(spec["config"], workspace)
            print(f"[mcp_servers.{name}]")
            print(f'command = "{c["command"]}"')
            print(f'args = {json.dumps(c.get("args", []))}')
            if c.get("env"):
                print(f'env = {json.dumps(c["env"])}')
            print()
    elif fmt == "yaml":
        print("extensions:")
        for name, spec in servers.items():
            c = substitute(spec["config"], workspace)
            print(f"  {name}:")
            print(f'    cmd: "{c["command"]}"')
            print(f"    args: {json.dumps(c.get('args', []))}")


def main():
    ap = argparse.ArgumentParser(description="Install mcp-hive servers into harness configs.")
    ap.add_argument("--harness", action="append", default=[],
                    help="Target harness (repeatable). Default: claude-code cursor github-copilot")
    ap.add_argument("--server", action="append", default=[],
                    help="Server to install (repeatable). Default: all in servers/")
    ap.add_argument("--dir", default=".", help="Project directory (default: current)")
    ap.add_argument("--global", dest="glob", action="store_true", help="Use the user-level config where supported")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    harnesses = args.harness or ["claude-code", "cursor", "github-copilot"]
    servers = load_servers(args.server)
    if not servers:
        print("no servers to install", file=sys.stderr)
        sys.exit(1)
    workspace = os.path.abspath(args.dir)

    for h in harnesses:
        if h in JSON_TARGETS:
            t = JSON_TARGETS[h]
            if args.glob:
                if not t["global"]:
                    print(f"skip: {h} has no global MCP config; use project scope", file=sys.stderr)
                    continue
                target = t["global"]
            else:
                target = os.path.join(args.dir, t["project"])
            merge_json(target, t["key"], servers, workspace, args.dry_run)
        elif h in SNIPPET_TARGETS:
            print_snippet(SNIPPET_TARGETS[h], servers, workspace)
        else:
            print(f"unknown harness: {h}", file=sys.stderr)
            sys.exit(1)
    print("done.")


if __name__ == "__main__":
    main()
