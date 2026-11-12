# Barry on Cline

Every surface the House installs into Cline, where it reads it, and what is specific to this
harness. Checked against Cline's docs (docs.cline.bot), the source of its SDK (`@cline/core`
0.2.0) and Cline CLI 3.0.74 on 2026-11-12. The registry row in `harnesses.json` is the
source of truth for paths; this guide explains them.

Cline is an open-source coding agent under Apache 2.0. It runs as a VS Code and JetBrains
extension, as Cline CLI (`cline`), as Cline Desktop, in other editors over the Agent Client
Protocol, and as an SDK. All of them read `~/.cline/` for the person and `.cline/` in the
project. Some surfaces below, subagents and custom agents among them, exist only in the CLI,
Desktop and the SDK, not in the editor extensions.

**Rules.** Markdown files in `.cline/rules/` or the older `.clinerules/` in the project, and
`~/.cline/rules/` for the person (also `~/Documents/Cline/Rules/`). Cline also reads
`AGENTS.md` at the project root and `~/.agents/AGENTS.md`, and `.cursorrules`. A rule with
no frontmatter is always on; a `paths` list of globs in its frontmatter makes it apply only
when matching files are in play. Each rule has a toggle, and workspace rules win a conflict.
The rules installer writes the Charter to `.cline/rules/queen-charter.md`, or
`~/.cline/rules/queen-charter.md` at global scope. `cline config rules` shows what loaded.

**Skills.** `.cline/skills/` in the project (also `.clinerules/skills/`, `.claude/skills/`
and `.agents/skills/`) and `~/.cline/skills/` or `~/.agents/skills/` for the person; a
global skill wins a name clash. Skills are no longer behind a setting: each is on when
discovered and has its own toggle. The skills installer writes to `.cline/skills` and
`~/.cline/skills`. `cline config skills` lists them.

**Subagents.** The `spawn_agent` tool starts a subagent with its own prompt and context
window; several can run at once, and their tokens count toward the session. A subagent has
the session's built-in tools for its mode and no MCP tools. Approving the `spawn_agent`
call approves everything the subagent then does. `/team` starts an agent team, with a
coordinator handing tasks to teammates through a shared task board.

**Custom agents.** Files in `.cline/agents/` (project) or `~/.cline/agents/` (person), each
a YAML frontmatter block and a body that is the system prompt. Cline's loader reads only
files ending `.yaml` or `.yml`, though the content is frontmatter and Markdown like any
other agent file, so the agents installer writes `.cline/agents/<name>.yaml`. The fields
are `name`, `description`, `tools`, `skills`, `providerId`, `modelId` and `maxIterations`.
Each agent becomes a tool, `subagent_<name>`, for the main agent to call. `tools` takes
ClineCore's tool names (`read_files`, `search_codebase`, `editor`, `apply_patch`,
`run_commands`, `fetch_web_content`, `skills`, `ask_question`), and Cline silently drops a
name it doesn't know, so an agent listing `Read` would get no tools at all. The installer
therefore translates Claude Code's names (`Read, Grep, Glob` becomes
`[read_files, search_codebase]`; an edit tool becomes both `editor` and `apply_patch`,
since Cline offers one or the other by model), which keeps `explore` and the review agents
read-only. An agent with a tool Cline has no name for gets no list and a warning. `cline
config agents` lists what loaded and `cline config tools` the tool names.

**Delegation.** Map Barry's logical roles to Cline's agents:

| Barry role | Cline equivalent |
|------------|------------------|
| explore | the House's `explore` agent, or a `spawn_agent` subagent asked for research only |
| generalPurpose | the main agent, or a `spawn_agent` subagent |
| shell | `run_commands`, within the session's auto-approve settings |
| code-review | the `code-review` agent |
| security-review | the `security-review` agent |
| best-of-n-runner | several subagents at once, an agent team, or Kanban's parallel worktrees |

**MCP servers.** One file for the person, `~/.cline/data/settings/cline_mcp_settings.json`
(or wherever `CLINE_MCP_SETTINGS_PATH` points), under `mcpServers`; Cline documents no
project file. A local server takes `command`, `args` and `env`; a remote one takes `url`,
`headers` and a `type`, which must be `streamableHttp` for Streamable HTTP since Cline
assumes the legacy SSE transport without it. Both take `disabled` and `autoApprove`. Cline
passes headers through as written, with no way to read a value from the environment.
`python3 hives/mcp-hive/scripts/install.py --global --harness cline` writes the file and
leaves a header that needs a secret for the person to set; without `--global` it skips
Cline. `cline mcp` manages servers from the terminal.

**Hooks.** Lifecycle hooks come from plugins: a plugin's `hooks` object can define
`beforeRun`, `afterRun`, `beforeModel`, `afterModel`, `beforeTool`, `afterTool` and
`onEvent`, and `beforeTool` can block a call. Plugins live in `.cline/plugins/` or
`~/.cline/plugins/`, and hook folders in `.cline/hooks/` and `~/.cline/hooks/`. The House
installs no hooks today.

**Memory.** Cline has no memory feature of its own. Its Memory Bank is a method: a rule
tells Cline to keep a `memory-bank/` folder of Markdown files and read it at the start of
each task. The House's knowledge-hive files serve the same purpose.

**Permissions.** Auto-approve settings decide what runs without asking: reading and editing
files in the workspace or anywhere, running commands the model marks safe or all commands,
the browser and MCP tools. YOLO mode approves everything. Plan mode removes the edit tools
and refuses commands that usually change files, though not every command that can. In the
CLI a prompt runs with auto-approve on unless given `--auto-approve false`, `--act` or
`--plan`, and `/settings` turns individual tools off.

**Headless.** `cline --json "<prompt>"` runs once and prints JSON Lines, ending with a
`run_result` that carries `usage`, `model` and the final text; piping stdin or redirecting
stdout also runs headless. Pass `--plan` for a run that shouldn't edit, `-m` for the model
and `-P` for the provider. A run needs a signed-in provider (`cline auth`), which can be a
ChatGPT plan (`openai-codex`) as well as a key. Barry's and Patricia's recorded runs were
headless in plan mode, signed in with a ChatGPT plan (`docs/harness-matrix.md`).

**Models.** Only pass a model when the user asks, with `-m`. Cline reaches 100+ models
through its own provider, ClinePass's open coding models, 30-odd other providers on your own
key, or local runtimes such as Ollama and LM Studio. Some models are free for a limited
time to anyone with a Cline account.

**Cost.** Cline itself is free. Inference is billed by whoever serves it: your provider at
its list price on your own key, Cline credits on its own provider (pay as you go, at cost),
or ClinePass at $9.99 a month for 2 to 5 times the standard rate limits on its open models.
Enterprise is priced on request. See the matrix for the current figures and their sources.
