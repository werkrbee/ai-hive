# Barry on Devin Desktop

Every surface the House installs into Devin Desktop, where it reads it, and what is
specific to this harness. Checked against Cognition's docs (docs.devin.ai) and Devin CLI
3000.12.43 on 2026-11-11. The registry row in `harnesses.json` is the source of truth for
paths; this guide explains them.

Devin Desktop is Windsurf, renamed on 2026-06-02 as an ordinary update: the app is now
Devin, and the `surf` command is `devin-desktop`. Its agent is Devin Local, the harness
Devin CLI also runs; the older Cascade agent is legacy, and an admin can turn it off. So
Devin CLI (`devin`) is the terminal and headless surface of the same agent, on the same
plan. Devin Desktop still reads the `.windsurf/` paths; `.devin/` takes precedence where
both exist. User-level files for the old editor stay under `~/.codeium/`.

**Rules.** `AGENTS.md` (also `AGENT.md`, and `AGENTS.local.md` kept out of version
control) in the workspace and each folder down to the working directory, and Markdown
files in `.devin/rules/`, each with a `trigger` in its frontmatter: `always_on`, `glob`,
`model_decision` or `manual`. `.devin/global_rules.md` is always on for the project, and
`~/.devin/global_rules.md` for the person. The legacy `.windsurf/rules/`,
`.windsurf/global_rules.md` and `.windsurfrules` still load. The rules installer writes the
Charter to `.devin/rules/queen-charter.md` with `trigger: always_on`, or
`~/.devin/global_rules.md` at global scope. `devin rules list` shows what loaded.

**Skills.** `.devin/skills/` or `.agents/skills/` in the project (legacy `.windsurf/skills/`),
and `~/.config/devin/skills/` or `~/.agents/skills/` for the person. The skills installer
writes to `.devin/skills` and `~/.config/devin/skills`. `devin skills paths` lists every
place it looks.

**Subagents.** Markdown files with YAML frontmatter in `.devin/agents/` or
`.agents/agents/` (project) or `~/.config/devin/agents/` (person), as `<name>.md` or
`<name>/AGENT.md`; the body is the system prompt. The fields are `name`, `description`,
`model`, `allowed-tools` (alias `tools`; all tools when absent) and `max-nesting`. Devin's
tool names are `read`, `grep`, `glob`, `edit` and `exec`, and it doesn't check them, so the
agents installer translates Claude Code's names (`Read, Grep, Glob` becomes
`[read, grep, glob]`) and keeps `explore` and the review agents read-only. An agent with a
tool Devin has no name for gets no list and a warning. A background subagent keeps only the
permissions the session already granted. Built in are `subagent_explore` (read-only, with
web search) and `subagent_general`. In Devin Desktop subagents sit behind the Subagents
(Preview) setting. `devin doctor` reports the profiles it loaded.

**Delegation.** Map Barry's logical roles to Devin's agents:

| Barry role | Devin Desktop equivalent |
|------------|--------------------------|
| explore | the built-in `subagent_explore`, or the House's `explore` agent |
| generalPurpose | the main agent, or `subagent_general` |
| shell | the `exec` tool, within the session's permissions |
| code-review | the `code-review` agent |
| security-review | the `security-review` agent |
| best-of-n-runner | several background subagents, or Devin cloud sessions (`devin --cloud`) |

**MCP servers.** `.devin/mcp_config.json` in the project (with a gitignored
`.devin/mcp_config.local.json`) or `~/.config/devin/mcp_config.json` for the person, under
`mcpServers`. A local server takes `command`, `args` and `env`; a remote one takes `url`,
an optional `transport` (`http` by default, or `sse`) and `headers`. The docs show
`${env:NAME}` reading the environment only in OAuth fields, so until a run confirms it in
headers, a header that needs a secret is left for the person to set.
`python3 hives/mcp-hive/scripts/install.py --harness devin-desktop` writes the project
file, and `--global` the personal one. `devin mcp list`
shows what Devin found; legacy Windsurf kept its servers in `~/.codeium/mcp_config.json`.

**Hooks.** `.devin/hooks.v1.json` in the project, or a `hooks` key in `.devin/config.json`
or `~/.config/devin/config.json`; Devin also runs Claude Code's hooks from
`.claude/settings.json`. The events are `PreToolUse`, `PostToolUse`, `PermissionRequest`,
`UserPromptSubmit`, `Stop`, `PostCompaction`, `SessionStart` and `SessionEnd`. Hooks don't
run in Restricted Mode. The House installs no hooks today.

**Memory.** Devin Local documents no memory feature: rules are how context carries from
one conversation to the next. The legacy Cascade agent kept memories of its own. The
House's knowledge-hive files are the way to keep state.

**Permissions.** `permissions.allow`, `ask` and `deny` in `.devin/config.json` (with a
gitignored `.devin/config.local.json`) or `~/.config/devin/config.json`, by tool (`read`,
`edit`, `exec`) or scope (`Read(glob)`, `Write(glob)`, `Exec(prefix)`, `Fetch(pattern)`,
`mcp__server__tool`). Deny always wins. `--permission-mode` is `auto` (read-only tools run
unasked, the default), `accept-edits`, `smart` or `dangerous`, and `--sandbox` confines
commands to the workspace. In Devin Desktop the same rules are set under Allow, Deny and
Ask in Devin Local's settings, and an Enterprise admin can enforce them.

**Headless.** `devin -p "<prompt>"` runs once and exits; it refuses an untrusted folder
unless given `--respect-workspace-trust false`. It prints the answer as text; `/stats` in
an interactive session shows tokens and credits. Barry's and Patricia's runs wait on #274:
Devin CLI signs in only to an existing Devin account, and creating one asked for the Pro
plan, so Devin Desktop's row stays unverified until they're recorded.

**Models.** Only pass a model when the user asks, with `--model`; `devin models` lists what
the plan offers. Cognition's own SWE-2 and SWE-2 Flash sit beside Claude, GPT and Gemini
models, and Fusion and Adaptive route between them.

**Cost.** One plan covers Devin Desktop, Devin CLI and Devin sessions: Free, Pro ($20 a
month), Max ($200) or Teams ($80 a month plus $40 a full seat; flex seats draw on shared
credit). Each plan has a daily and weekly budget measured in the tokens each request uses,
and free models don't count against it. Past the budget, Pro, Max and Teams buy extra
usage, billed at the model's API list price. Enterprise is billed in ACUs, converted at the
models page's per-token rates. See the matrix for the current figures and their sources.
