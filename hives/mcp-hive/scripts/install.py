#!/usr/bin/env python3
"""Merge mcp-hive server definitions into each harness's MCP config.

MCP config formats differ across harnesses (JSON vs TOML vs YAML), so this
installer merges into the JSON-based configs directly and prints ready-to-paste
snippets for the others. Merges are non-destructive: existing servers and other
keys are preserved.

An entry is either a local stdio server (a hand-written `config`) or a remote
server found through its MCP Server Card (a `discovery` block). Remote entries are
resolved at install time: the card is fetched, validated and turned into each
harness's remote config. See scripts/server_card.py.

Usage:
  python3 scripts/install.py --dir /path/to/project
  python3 scripts/install.py --harness cursor --server filesystem --server git
  python3 scripts/install.py --global --harness claude-code
  python3 scripts/install.py --server huggingface --dry-run
"""
import argparse
import json
import os
import sys
from pathlib import Path

import server_card

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVERS_DIR = REPO_ROOT / "servers"
TARGET_SPEC = "2026-07-28"

# harness -> where its JSON MCP config lives and which key holds the servers
JSON_TARGETS = {
    "claude-code":    {"project": ".mcp.json",         "global": "~/.claude.json",     "key": "mcpServers"},
    "cursor":         {"project": ".cursor/mcp.json",  "global": "~/.cursor/mcp.json", "key": "mcpServers"},
    "github-copilot": {"project": ".vscode/mcp.json",  "global": None,                 "key": "servers"},
}
# harnesses whose config isn't JSON — we print a snippet instead
SNIPPET_TARGETS = {"codex": "toml", "goose": "yaml"}
# how each JSON harness reads a value from the environment (VS Code prompts via inputs)
ENV_REF = {"claude-code": "${%s}", "cursor": "${env:%s}", "github-copilot": "${input:%s}"}


def load_servers(servers_dir, names):
    servers = {}
    for d in sorted(servers_dir.iterdir()):
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


def resolve_remotes(servers):
    """Fetch and validate the Server Card behind every discovery entry. Fails loud."""
    failed = False
    for name, spec in servers.items():
        if "discovery" not in spec:
            continue
        try:
            source, card = server_card.load_card(spec["discovery"])
            problems = server_card.validate(card)
            if problems:
                raise server_card.CardError(f"{source}: invalid Server Card: " + "; ".join(problems))
            remote = server_card.resolve(name, card, spec.get("variables", {}))
        except server_card.CardError as e:
            print(f"error: {name}: {e}", file=sys.stderr)
            failed = True
            continue
        spec["remote"] = remote
        print(f"{name}: Server Card {card['name']} {card['version']} from {source}")
        print(f"  remote: {remote['url']}")
        envs = [p[1] for h in remote["headers"] for p in h["parts"] if p[0] == "env"]
        if envs:
            print(f"  set in your environment: {', '.join(envs)} (VS Code prompts for these instead)")
        if remote["optional"]:
            print(f"  optional headers not written: {', '.join(remote['optional'])}")
        if remote["versions"] and TARGET_SPEC not in remote["versions"]:
            print(f"  note: card lists protocol versions {', '.join(remote['versions'])}; "
                  f"mcp-hive targets {TARGET_SPEC} and the client negotiates")
    if failed:
        sys.exit(2)


def substitute(obj, workspace):
    if isinstance(obj, str):
        return obj.replace("${WORKSPACE}", workspace)
    if isinstance(obj, list):
        return [substitute(x, workspace) for x in obj]
    if isinstance(obj, dict):
        return {k: substitute(v, workspace) for k, v in obj.items()}
    return obj


def json_config(harness, name, spec, workspace):
    """Return (config, VS Code inputs) for one server in one JSON harness."""
    if "remote" not in spec:
        return substitute(spec["config"], workspace), []
    r = spec["remote"]
    config = {"url": r["url"]} if harness == "cursor" else {"type": "http", "url": r["url"]}
    headers, inputs = {}, []
    for h in r["headers"]:
        value = ""
        for kind, text in h["parts"]:
            value += ENV_REF[harness] % text if kind == "env" else text
            if kind == "env" and harness == "github-copilot":
                inputs.append({"type": "promptString", "id": text,
                               "description": f"{h['name']} for {name}", "password": h["secret"]})
        headers[h["name"]] = value
    if headers:
        config["headers"] = headers
    return config, inputs


def merge_json(harness, path, key, servers, workspace, dry):
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
        config, inputs = json_config(harness, name, spec, workspace)
        data[key][name] = config
        if inputs:
            existing = {i.get("id") for i in data.setdefault("inputs", [])}
            data["inputs"] += [i for i in inputs if i["id"] not in existing]
    if dry:
        print(f"[dry-run] would write {path}:\n{json.dumps(data, indent=2)}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
    print(f"merged {len(servers)} server(s) -> {path}")


def toml_inline(table):
    return "{ " + ", ".join(f"{json.dumps(k)} = {json.dumps(v)}" for k, v in table.items()) + " }"


def remote_headers_toml(r):
    """Codex reads a bearer token or a whole header from an env var, or a static value."""
    lines, static, from_env = [], {}, {}
    for h in r["headers"]:
        parts = h["parts"]
        if all(k == "text" for k, _ in parts):
            static[h["name"]] = "".join(t for _, t in parts)
        elif h["name"].lower() == "authorization" and parts[:1] == [("text", "Bearer ")] and len(parts) == 2:
            lines.append(f"bearer_token_env_var = {json.dumps(parts[1][1])}")
        elif len(parts) == 1:
            from_env[h["name"]] = parts[0][1]
        else:
            lines.append(f"# set header {h['name']} by hand; it combines text with an env var")
    if static:
        lines.append(f"http_headers = {toml_inline(static)}")
    if from_env:
        lines.append(f"env_http_headers = {toml_inline(from_env)}")
    return lines


def print_snippet(fmt, servers, workspace):
    print(f"\n# --- add to your {fmt.upper()} config ---")
    if fmt == "toml":
        for name, spec in servers.items():
            print(f"[mcp_servers.{name}]")
            if "remote" in spec:
                print(f'url = {json.dumps(spec["remote"]["url"])}')
                for line in remote_headers_toml(spec["remote"]):
                    print(line)
                print()
                continue
            c = substitute(spec["config"], workspace)
            print(f'command = "{c["command"]}"')
            print(f'args = {json.dumps(c.get("args", []))}')
            if c.get("env"):
                print(f'env = {json.dumps(c["env"])}')
            print()
    elif fmt == "yaml":
        print("extensions:")
        for name, spec in servers.items():
            print(f"  {name}:")
            if "remote" in spec:
                r = spec["remote"]
                print(f"    name: {name}")
                print("    type: streamable_http")
                print(f"    uri: {json.dumps(r['url'])}")
                static = {h["name"]: "".join(t for _, t in h["parts"])
                          for h in r["headers"] if all(k == "text" for k, _ in h["parts"])}
                if static:
                    print("    headers:")
                    for k, v in static.items():
                        print(f"      {json.dumps(k)}: {json.dumps(v)}")
                for h in r["headers"]:
                    if h["name"] not in static:
                        print(f"    # set header {h['name']} by hand; it needs a value from the environment")
                continue
            c = substitute(spec["config"], workspace)
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
    ap.add_argument("--servers-dir", default=str(SERVERS_DIR), help="Registry directory (default: this hive's servers/)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    harnesses = args.harness or ["claude-code", "cursor", "github-copilot"]
    servers = load_servers(Path(args.servers_dir), args.server)
    if not servers:
        print("no servers to install", file=sys.stderr)
        sys.exit(1)
    resolve_remotes(servers)
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
            merge_json(h, target, t["key"], servers, workspace, args.dry_run)
        elif h in SNIPPET_TARGETS:
            print_snippet(SNIPPET_TARGETS[h], servers, workspace)
        else:
            print(f"unknown harness: {h}", file=sys.stderr)
            sys.exit(1)
    print("done.")


if __name__ == "__main__":
    main()
