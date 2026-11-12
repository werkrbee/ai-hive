# Barry on Kiro

Every surface the House installs into Kiro, where it reads it, and what is specific to this
harness. Checked against Kiro's docs (kiro.dev/docs) and Kiro CLI 3.2.1 on 2026-11-11. The
registry row in `harnesses.json` is the source of truth for paths; this guide explains them.

Kiro is AWS's spec-driven coding agent and the successor to Amazon Q Developer. It runs in
the Kiro IDE, in Kiro CLI (`kiro-cli`), on the web and on mobile, and all of them read the
same `.kiro/` folder. The CLI has two engines: V3, the default for interactive chat, and V2,
which a headless run uses unless told otherwise.

**Steering (rules).** Markdown files in `.kiro/steering/` for the workspace and
`~/.kiro/steering/` for the person; workspace steering wins where the two conflict. A
steering file's frontmatter sets its `inclusion`: `always` (the default), `fileMatch` with
a `fileMatchPattern`, `manual` (pulled in with `#name` in chat) or `auto` (matched against
its `name` and `description`); the V1 and V2 engines load only `always` files. Kiro also
reads `AGENTS.md` in the workspace root and its subfolders, and in `~/.kiro/steering/`,
always included. The rules installer writes the Charter to `AGENTS.md`, shared with the
other harnesses that read it, or to `~/.kiro/steering/AGENTS.md` at global scope.

**Specs.** Kiro's own planning: a feature spec writes `requirements.md` (or `bugfix.md` for
a bugfix spec), `design.md` and `tasks.md`, with approval gates between them unless it is a
quick spec. Running all tasks builds a dependency graph and runs independent tasks
together in waves. The House installs no specs; a spec's tasks are where Barry's plan
lands, so lean on Kiro's planning rather than duplicating it.

**Skills.** `.kiro/skills/` in the workspace and `~/.kiro/skills/` for the person; a
workspace skill wins a name clash. A skill's `name` must match its folder. The skills
installer writes to `.kiro/skills` and `~/.kiro/skills`. A custom agent doesn't load
skills unless its `resources` list them, such as `skill://.kiro/skills/*/SKILL.md`.

**Subagents.** Custom agents are Markdown (frontmatter and a body that is the system prompt)
or JSON files in `.kiro/agents/` (loaded only in a trusted workspace) or `~/.kiro/agents/`.
The fields include `name`, `description`, `model`, `tools`, `excludedTools`, `resources`,
`mcpServers`, `includeMcpJson` and `permissions`. `tools` takes Kiro's categories (`read`,
`write`, `shell`, `web`, `subagent`), tool IDs, `@builtin` or `*`, and a subagent gets only
the tools its file lists. Kiro's docs don't say what happens to a name it doesn't know, so
the agents installer translates Claude Code's names (`Read, Grep, Glob` becomes `[read]`,
`Edit` and `Write` become `write`, `Bash` becomes `shell`), which keeps `explore` and the
review agents read-only; an agent with a tool Kiro has no name for gets no list and a
warning. Any custom agent can run as a subagent, in its own context window and in parallel
with others, sharing steering, MCP servers and the workspace. Built in are a context
gathering subagent and a general purpose one. An orchestrator needs `subagent` in its
tools to delegate.

**Delegation.** Map Barry's logical roles to Kiro's agents:

| Barry role | Kiro equivalent |
|------------|-----------------|
| explore | the built-in context gathering subagent, or the House's `explore` agent |
| generalPurpose | the main agent, or the general purpose subagent |
| shell | the `shell` tools, within the session's permissions |
| code-review | the `code-review` agent |
| security-review | the `security-review` agent |
| best-of-n-runner | several subagents in parallel, or a cloud session (`kiro-cli --cloud`) |

**MCP servers.** `.kiro/settings/mcp.json` in the workspace or `~/.kiro/settings/mcp.json`
for the person, under `mcpServers`, merged with the workspace winning. A local server takes
`command`, `args` and `env`; a remote one takes `url` and `headers`, and both take
`disabled`, `autoApprove` and `disabledTools`. `${NAME}` reads the environment in `headers`
and `env`; the IDE expands only the variables approved in its Mcp Approved Env Vars setting.
`python3 hives/mcp-hive/scripts/install.py --harness kiro` writes the workspace file, and
`--global` the personal one, with a secret header as a `${NAME}` reference. An agent file
can carry its own `mcpServers`, and gets the shared ones only with `includeMcpJson`.

**Hooks.** One JSON file per hook in `.kiro/hooks/` (`version` `"v1"` and a `hooks` list),
and in `~/.kiro/hooks/` for CLI V3. A hook has a `trigger` such as `PostFileSave`,
`PreToolUse`, `PostToolUse` or `Stop`, an optional `matcher`, and an action that runs a
command or prompts the agent. The House installs no hooks today.

**Memory.** Kiro keeps memories of commands, conventions and debugging findings across
sessions, stored locally per user account rather than per workspace and shared by the IDE
and CLI on one machine. It is off by default and set per app, as Use and learn, Use but
don't learn, Use only or Off. The House's knowledge-hive files remain the way to keep
state that travels with the repository.

**Permissions.** Rules with a `capability` (`fs_read`, `fs_write`, `shell`, `web_fetch`,
`web_search`, `mcp`, `subagent`, `skill` and more, or `all`, `builtin` and `filesystem`), a
`match` list of globs, an optional `exclude` and an `effect` of `deny`, `ask`, `allow` or
`evaluate`; deny always wins. They live in `~/.kiro/settings/permissions.yaml`, in a
per-workspace file under `~/.kiro/workspace-roots/` that a cloned repo can't supply, and in
an agent's `permissions`. `--trust-all-tools` trusts everything the rules don't deny. In a
subagent the stricter of its own and its parent's rules wins.

**Headless.** `kiro-cli chat --no-interactive "<prompt>"` runs once and exits; pass `--v3`
or `--v2` so the engine doesn't depend on the default, `--agent` and `--model` to choose,
and `--output-format stream-json` for JSON Lines. It needs a `KIRO_API_KEY`, which only Pro
and higher plans can create. Barry's and Patricia's runs wait on #276 for that
reason, so Kiro's row stays unverified until they're recorded.

**Models.** Only pass a model when the user asks, with `--model`. Auto, the recommended
setting, routes between models; Claude, GPT, Grok and several open-weight models are on
offer, and only some are on the Free plan.

**Cost.** Kiro bills in credits, used fractionally by each request: simple edits cost less
than long tasks, and each model has a multiplier against Auto (Claude Sonnet 5.5 1.3x,
Opus 5.5 2x, Haiku 5.5 0.06x up to 100K tokens). Free has 50 credits a month; Pro ($20 a
month) 1,000, Pro+ ($40) 2,000, Pro Max ($100) 5,000 and Power ($200) 10,000, with more at
$0.04 a credit; Teams pool 500 a seat at $20. Kiro doesn't say how many tokens a credit
buys, so no per-token rate is recorded. See the matrix for the current figures and their
sources.
