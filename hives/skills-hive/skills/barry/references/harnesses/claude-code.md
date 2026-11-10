# Barry on Claude Code

Every surface the House installs into Claude Code, where Claude Code reads it, and what
is specific to this harness. Checked against Claude Code's docs (code.claude.com/docs)
on 2026-11-10, Claude Code 2.1.322. The registry row in `harnesses.json` is the source
of truth for paths; this guide explains them.

**Rules.** Claude Code reads `CLAUDE.md` at the project root (or `.claude/CLAUDE.md`)
and `~/.claude/CLAUDE.md` for every project, plus a gitignored `CLAUDE.local.md` for
personal notes. It loads the files above the working directory at launch and the ones in
subdirectories on demand, and it can read `AGENTS.md` in place of `CLAUDE.md`. The rules
installer writes the Charter into `CLAUDE.md`; a repo can instead keep its context in
`AGENTS.md` and import it with `@AGENTS.md`, as this repo does. Rules scoped to file
types go in `.claude/rules/`.

**Skills.** `~/.claude/skills/<name>/SKILL.md` (personal) and `.claude/skills/<name>/SKILL.md`
(project, found from the working directory up to the repository root). Claude Code
doesn't document `.agents/skills`, so the skills installer writes to `.claude/skills`.
A skill runs when its description matches or when you type `/<name>`.

**Subagents.** Markdown files with YAML frontmatter in `.claude/agents/` (project) or
`~/.claude/agents/` (personal). Only `name` and `description` are required; the House's
agents also set `tools` and `model`. Other keys Claude Code reads include
`disallowedTools`, `permissionMode`, `skills`, `mcpServers`, `hooks`, `memory`, `effort`
and `isolation: worktree`; it ignores keys it doesn't know. Run one as the whole session
with `claude --agent <name>`.

**Delegation.** Claude Code launches subagents with the Agent (Task) tool, choosing a
subagent type. Map Barry's logical roles to Claude Code's agents:

| Barry role | Claude Code equivalent |
|------------|------------------------|
| explore | `Explore` (read-only search agent) |
| generalPurpose | `general-purpose` |
| shell | Bash tool, or `general-purpose` for scripted work |
| harness-guide | `claude-code-guide`, or ask about Claude Code features directly |
| ci-investigator | `general-purpose` scoped to one failing check |
| code-review | `general-purpose` with a review prompt, or a review skill |
| security-review | `security-review` skill |
| best-of-n-runner | several `general-purpose` agents in one message |

**Parallelism.** Send several Agent calls in one message; use `run_in_background` for
long jobs and wait for completion before synthesizing.

**MCP servers.** `.mcp.json` at the project root (shared, top-level key `mcpServers`), or
`~/.claude.json` for every project. `python3 hives/mcp-hive/scripts/install.py --harness
claude-code` merges mcp-hive's servers into `.mcp.json`, or `~/.claude.json` with
`--global`. Values from the environment are written `${VAR}`, with `${VAR:-default}` for
a fallback. Claude Code asks before it uses a project's servers in an interactive session.

**Hooks.** Shell commands (or prompts) that run on events such as `PreToolUse`,
`PostToolUse`, `SessionStart` and `Stop`, configured under `hooks` in
`~/.claude/settings.json`, `.claude/settings.json` (shared) or
`.claude/settings.local.json` (personal). A hook is the way to enforce something, since
rules and memory are context Claude reads, not configuration it must obey. The House
installs no hooks today.

**Memory.** Besides the rules files, Claude Code keeps auto memory: notes it writes
itself in `~/.claude/projects/<project>/memory/`, one file per memory with a `MEMORY.md`
index whose first 200 lines load into every session. It is per repository and stays on
the machine.

**Permissions.** `permissions.allow`, `ask` and `deny` rules in the same settings files,
such as `Bash(git diff *)` or `Read(./.env)`, and a permission mode: `default`,
`acceptEdits`, `plan`, `auto`, `dontAsk` or `bypassPermissions`. Patricia's subagent
has no Edit or Write tool in its `tools` list, so she can't change files whatever the
mode; her Bash use is held to review by her charter, not by a rule.

**Headless.** `claude -p "<prompt>"` runs one turn without the interface. Add
`--output-format json` for a result with `total_cost_usd` and per-model token usage,
`--permission-mode dontAsk` with `--allowedTools` for a locked-down run, and `--bare` in
CI to skip the machine's own hooks, skills and `CLAUDE.md`. Barry's and Patricia's
recorded runs were headless (`docs/harness-matrix.md`).

**Plugins.** A plugin bundles skills, agents, commands, hooks and MCP servers under one
name: `.claude-plugin/plugin.json` (optional) at the plugin root, with `skills/`,
`agents/`, `commands/`, `hooks/hooks.json` and `.mcp.json` beside it. plugins-hive's
packs are the House's composition layer; packaging one as a Claude Code plugin is the
adapter, not a fork of the skills inside it.

**Models.** Only pass a model when the user asks; use Claude Code's model aliases
(`sonnet`, `opus`, `haiku`, `fable`) or a full model ID.

**Cost.** Billed by plan (Pro, Max, Ultra, Team) or by API tokens at Anthropic's list
price. See the matrix for the current figures and their sources.
