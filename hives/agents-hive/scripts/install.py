#!/usr/bin/env python3
"""Render agents-hive personas into each harness's native agent format.

Agent formats are fragmented across harnesses (Claude Code subagents, Copilot
custom agents, Codex's TOML agents, the AGENTS.md ecosystem, …), so each canonical agent is stored once in
a neutral form (frontmatter + system prompt) and rendered per harness. Each agent
is its own file, so writes are non-destructive by construction.

Usage:
  python3 scripts/install.py --dir /path/to/project
  python3 scripts/install.py --harness claude-code --agent explore --agent code-review
  python3 scripts/install.py --dry-run
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO_ROOT / "agents"
sys.path.insert(0, str(REPO_ROOT.parent.parent / "scripts"))
import harnesses  # noqa: E402  the House's harness registry, harnesses.json


def agent_target(harness):
    """(path template, keys to keep, harness it falls back to or None, file format) for a
    harness's agents, from the registry; None if it has no agent format. {name} is the
    agent name. The format is markdown (frontmatter and a body) unless the registry says
    toml. A harness whose agent format isn't settled falls back to another's."""
    s = harnesses.surface(harness, "agents")
    if not s:
        return None
    fallback = s.get("fallback")
    if fallback:
        s = harnesses.surface(fallback, "agents")
    return s["project"], s["keys"], fallback, s.get("format", "markdown")


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


# Tools that change files or run commands. An agent whose tools list has none of them is
# read-only, which a harness with a readonly flag (Cursor) can enforce.
WRITE_TOOLS = {"edit", "write", "multiedit", "notebookedit", "bash", "shell", "execute"}


def readonly(fm):
    """"true" when the agent's tools list holds no tool that writes, else None."""
    tools = [t.strip().lower() for t in fm.get("tools", "").split(",") if t.strip()]
    return "true" if tools and not set(tools) & WRITE_TOOLS else None


def render(fm, body, keys, name):
    out = ["---"]
    for k in keys:
        derived = {"name": name, "readonly": readonly(fm)}
        val = derived[k] if k in derived else fm.get(k)
        if val:
            out.append(f"{k}: {val}")
    out.append("---")
    out.append("")
    out.append(body.rstrip() + "\n")
    return "\n".join(out)


def toml_string(text):
    """A TOML string: a multi-line literal string when it can be one, else a basic string
    with every control character escaped (TOML allows only tab and newline unescaped)."""
    controls = [c for c in text if (ord(c) < 32 and c not in "\t\n") or ord(c) == 127]
    if "'''" not in text and not controls:
        return "'''\n" + text + "'''"
    return json.dumps(text, ensure_ascii=False).replace("\x7f", "\\u007f")


def render_toml(fm, body, keys, name):
    """A Codex custom agent: one TOML file, with the system prompt as developer_instructions.
    Codex has no tools list (a subagent inherits its parent's sandbox), so tools is dropped;
    see UNENFORCED."""
    out = []
    for k in keys:
        val = fm.get(k) if k != "name" else name
        if val:
            out.append(f"{k} = {json.dumps(val, ensure_ascii=False)}")
    out.append("developer_instructions = " + toml_string(body.rstrip() + "\n"))
    return "\n".join(out) + "\n"


# How to keep an agent read-only in a harness whose agent files can't carry its tools list.
# Codex has no tools field. Antigravity names its own tools, and a name it doesn't know can
# hang the subagent, so Claude Code's names aren't passed on; it reads the shared
# .agents/agents/ folder, so that target carries no tools list either.
UNENFORCED = {
    "codex": ("a Codex agent file", "it inherits the session's sandbox, so run that session "
                                    "with --sandbox read-only to keep this agent from editing"),
    "gemini-cli": ("an Antigravity agent file", "its main agent decides its tools and permissions, "
                                                "so deny write_file(*) and command(*) in that "
                                                "session's permissions to keep this agent from editing"),
}
UNENFORCED["agents"] = ("the shared .agents/agents/ folder, which Antigravity reads",
                        UNENFORCED["gemini-cli"][1])


def unenforced(fm, harness):
    """The warning for an agent whose tools list the harness's agent files can't carry, or
    None. Such an agent is read-only there only if the session is."""
    tools = fm.get("tools")
    if harness not in UNENFORCED or not tools:
        return None
    where, advice = UNENFORCED[harness]
    return f"tools ({tools}) can't be enforced in {where}; {advice}"


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

    targets = args.harness or ["claude-code", "github-copilot", "agents"]
    agents = load_agents(args.agent)
    if not agents:
        print("no agents to install", file=sys.stderr)
        sys.exit(1)

    for h in targets:
        found = agent_target(h)
        if found is None:
            print(f"unknown harness: {h}", file=sys.stderr)
            sys.exit(1)
        tmpl, keys, fallback, fmt = found
        if fallback:
            print(f"note: {h} agent format varies — using the shared {Path(tmpl).parent}/ fallback (verify vs its docs)", file=sys.stderr)

        for name, (fm, body) in agents.items():
            rel = tmpl.format(name=name)
            target = Path(args.dir) / rel
            content = (render_toml if fmt == "toml" else render)(fm, body, keys, name)
            warning = unenforced(fm, fallback or h)
            if warning:
                print(f"warning: {h}: {name}: {warning}", file=sys.stderr)
            if args.dry_run:
                print(f"[dry-run] would write {target}")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            print(f"wrote: {target}")
    print("done.")


if __name__ == "__main__":
    main()
