# Barry on Gemini CLI and Antigravity

Every surface the House installs into Google's coding agents, where they read it, and what
is specific to this harness. Checked against Antigravity's docs (antigravity.google/docs)
and Gemini CLI's (geminicli.com/docs) on 2026-11-11, Antigravity CLI 1.5.5. The registry
row in `harnesses.json` is the source of truth for paths; this guide explains them.

One harness, two surfaces. Since 2026-06-18 consumers (the free tier, Google AI Pro and
Ultra) use Antigravity: the desktop app and its CLI, `agy`, which share one engine.
Gemini CLI (`gemini`) still ships for paid Gemini API keys and for Gemini Code Assist
Standard and Enterprise, but stopped serving consumer accounts that day. The House
installs where Antigravity reads, and notes below where Gemini CLI reads somewhere else.
`agy plugin import gemini` turns Gemini CLI extensions into Antigravity plugins.

**Rules.** `GEMINI.md` or `AGENTS.md` in the workspace and each parent folder up to the
repository root (also `.agents/GEMINI.md` and `.agents/AGENTS.md`), and
`~/.gemini/GEMINI.md` or `~/.gemini/AGENTS.md` for the person. These are plain Markdown and
always on. Rules in `.agents/rules/*.md` need frontmatter with a `trigger` (`always_on`,
`model_decision`, `glob` or `manual`), or Antigravity silently drops them. Each file is
capped at 24,000 bytes, and global and always-on rules share a 20,000-token budget. Gemini
CLI reads `GEMINI.md` and `~/.gemini/GEMINI.md` the same way. The rules installer writes
the Charter to `GEMINI.md`, or `~/.gemini/GEMINI.md` at global scope.

**Skills.** `.agents/skills/` in the workspace and each parent folder up to the repository
root, read by the app, the CLI and Gemini CLI. For the person, the app and CLI read
`~/.gemini/config/skills/`; the CLI also reads `~/.gemini/skills/`, as does Gemini CLI.
The skills installer writes to `.agents/skills` and `~/.gemini/skills`, so a global install
reaches both CLIs but not the desktop app. In the CLI each skill is also a slash command;
run `/skills reload` after adding one mid-session.

**Subagents.** Markdown files with YAML frontmatter in `.agents/agents/` (workspace) or
`~/.gemini/config/agents/` (person); the body is the system prompt. The fields are `name`,
`description`, `tools`, `model` (`inherit`, `flash` or `pro`), `commandExecutionPolicy`,
`mcpServers` and `skills`. `tools` takes Antigravity's own tool names, and a name it doesn't
know can hang the subagent, so the agents installer writes only `name` and `description`.
A subagent's tools and permissions are then whatever its main agent gives it, and it
inherits the session's allowed commands and file scopes. So the installer warns for each
agent with a tools list: a read-only agent such as `explore` or Patricia's `charter-review`
is read-only in Antigravity only when the session denies writes and commands (see
Permissions). Built in are `research` (codebase exploration), `browser` (through
`/browser`) and `self` (a copy of the calling agent), and `/agents` in the CLI shows the
running ones. Gemini CLI reads custom agents from `.gemini/agents/` instead, with its own
built-ins `codebase_investigator` and `generalist`.

**Delegation.** Map Barry's logical roles to Antigravity's agents:

| Barry role | Antigravity equivalent |
|------------|------------------------|
| explore | the built-in `research` subagent, or the House's `explore` agent |
| generalPurpose | the main agent, or `self` |
| shell | the terminal tool, within the session's permissions |
| code-review | the `code-review` agent |
| security-review | the `security-review` agent |
| best-of-n-runner | several subagents at once, or remote agents (`--remote-agent`) |

**MCP servers.** `.agents/mcp_config.json` in the workspace or
`~/.gemini/config/mcp_config.json` for the person, under `mcpServers`. A local server takes
`command`, `args` and `env`; a remote one takes `serverUrl` and `headers`, and must speak
Streamable HTTP. The docs give no way to read a value from the environment, so values are
literal. `python3 hives/mcp-hive/scripts/install.py --harness gemini-cli` writes the
workspace file, and `--global` the personal one; a header that needs a secret is left for
the person to set. `/mcp` in the CLI shows what loaded. Gemini CLI keeps its servers under
`mcpServers` in `.gemini/settings.json` or `~/.gemini/settings.json`, with `httpUrl` and
`${VAR}` references.

**Hooks.** `.agents/hooks.json` in the workspace or `~/.gemini/config/hooks.json` for the
person, on the events `SessionStart`, `PreToolUse`, `PostToolUse`, `PreInvocation`,
`PostInvocation` and `Stop`; the tool events take a regular-expression `matcher`. A hook is
a shell command with a timeout (30 seconds by default). The House installs no hooks today.

**Memory.** Antigravity documents no memory feature: rules are how context carries from one
conversation to the next. Gemini CLI saves facts into its `GEMINI.md` files when asked and
shows them with `/memory show`. The House's knowledge-hive files are the way to keep state
in either.

**Permissions.** The CLI reads `permissions.allow`, `ask` and `deny` from
`~/.gemini/antigravity-cli/settings.json`, with rules shaped `action(target)`:
`read_file`, `write_file`, `read_url`, `execute_url`, `command` and `mcp`, such as
`command(git)` or `write_file(.git/)`. Deny beats ask beats allow. Modes (`--mode`) are
`default`, `accept-edits`, `auto` (terminal commands in a sandbox) and `plan`;
`--dangerously-skip-permissions` approves everything. `--settings` applies settings to one
session without saving them, which is how to run a read-only session:
`--settings '{"permissions":{"deny":["write_file(*)","command(*)"]}}'`.

**Headless.** `agy -p "<prompt>"` runs once and exits. `--output-format json` gives one
result with `usage` (`input_tokens`, `output_tokens`, `thinking_tokens`,
`cache_read_tokens`, `total_tokens`), and `stream-json` streams steps. With no one to ask,
a tool that needs approval is soft-denied: the run goes on and exits 0, with a notice on
stderr and the denials listed under `denied_actions`. A command like `gh issue view`
counts, so hand a headless run what it needs as a file or allow the command. Barry's and
Patricia's recorded runs were headless, with writes denied (`docs/harness-matrix.md`).
Gemini CLI's equivalent is `gemini -p`.

**Models.** Only pass a model when the user asks, with `--model`; `agy models` lists what
the plan offers. Gemini 3.8 Flash (High) is the default on the free plan and is on every plan, Gemini 4 Argon from Google AI Pro up,
and Claude Sonnet 5.5 and Opus 5.5 on paid Pro, Ultra and Enterprise.

**Cost.** Antigravity is free for individuals with a weekly limit. Google AI Pro ($19.99 a
month) and Ultra ($99.99 or $199.99) raise the limits, refreshed every five hours up to a
weekly cap, and can buy AI credits, billed at Gemini Enterprise consumption prices, for use
beyond them. Teams buy through Gemini Enterprise, from $30 a seat. Gemini CLI on an API key,
or `agy` with `"modelProvider": "gemini"` and `GEMINI_API_KEY`, bills at the Gemini API's
list price. See the matrix for the current figures and their sources.
