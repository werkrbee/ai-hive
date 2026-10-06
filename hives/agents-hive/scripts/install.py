#!/usr/bin/env python3
"""Render agents-hive personas into each harness's native agent format.

Agent formats are fragmented across harnesses (Claude Code subagents, Copilot
chatmodes, the AGENTS.md ecosystem, …), so each canonical agent is stored once in
a neutral form (frontmatter + system prompt) and rendered per harness. Each agent
is its own file, so writes are non-destructive by construction.

Usage:
  python3 scripts/install.py --dir /path/to/project
  python3 scripts/install.py --harness claude-code --agent explore --agent code-review
  python3 scripts/install.py --dry-run
"""
import argparse
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO_ROOT / "agents"

# harness -> (path template, frontmatter keys to keep). {name} is the agent name.
MD_TARGETS = {
    "claude-code":    (".claude/agents/{name}.md",              ["name", "description", "tools", "model"]),
    "cursor":         (".cursor/agents/{name}.md",              ["name", "description", "tools", "model"]),
    "agents":         (".agents/agents/{name}.md",              ["name", "description", "tools", "model"]),
    "github-copilot": (".github/chatmodes/{name}.chatmode.md",  ["description", "tools", "model"]),
}
# Harnesses whose agent format isn't settled — fall back to the shared .agents dir.
FALLBACK = {"codex", "gemini-cli", "goose", "opencode", "kiro",
            "databricks-genie-code", "snowflake-cortex-code"}


def parse_agent(path):
    text = path.read_text()
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        raise ValueError(f"{path} missing frontmatter")
    fm_block, body = m.group(1), m.group(2).lstrip("\n")
    fm = {}
    for line in fm_block.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        v = v.strip()
        if v:
            fm[k.strip()] = v
    return fm, body


def render(fm, body, keys, name):
    out = ["---"]
    for k in keys:
        val = fm.get(k) if k != "name" else name
        if val:
            out.append(f"{k}: {val}")
    out.append("---")
    out.append("")
    out.append(body.rstrip() + "\n")
    return "\n".join(out)


def load_agents(names):
    agents = {}
    for d in sorted(AGENTS_DIR.iterdir()):
        f = d / "agent.md"
        if not f.is_file():
            continue
        name = d.name
        if names and name not in names:
            continue
        agents[name] = parse_agent(f)
    for missing in (set(names) - set(agents) if names else set()):
        print(f"warning: agent not found: {missing}", file=sys.stderr)
    return agents


def main():
    ap = argparse.ArgumentParser(description="Install agents-hive personas into harness agent formats.")
    ap.add_argument("--harness", action="append", default=[],
                    help="Target harness (repeatable). Default: claude-code github-copilot agents")
    ap.add_argument("--agent", action="append", default=[],
                    help="Agent to install (repeatable). Default: all in agents/")
    ap.add_argument("--dir", default=".", help="Project directory (default: current)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    harnesses = args.harness or ["claude-code", "github-copilot", "agents"]
    agents = load_agents(args.agent)
    if not agents:
        print("no agents to install", file=sys.stderr)
        sys.exit(1)

    for h in harnesses:
        if h in FALLBACK:
            print(f"note: {h} agent format varies — using the shared .agents/agents/ fallback (verify vs its docs)", file=sys.stderr)
            tmpl, keys = MD_TARGETS["agents"]
        elif h in MD_TARGETS:
            tmpl, keys = MD_TARGETS[h]
        else:
            print(f"unknown harness: {h}", file=sys.stderr)
            sys.exit(1)

        for name, (fm, body) in agents.items():
            rel = tmpl.format(name=name)
            target = Path(args.dir) / rel
            content = render(fm, body, keys, name)
            if args.dry_run:
                print(f"[dry-run] would write {target}")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            print(f"wrote: {target}")
    print("done.")


if __name__ == "__main__":
    main()
