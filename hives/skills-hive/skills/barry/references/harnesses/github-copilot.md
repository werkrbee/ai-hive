# Barry on GitHub Copilot

Every surface the House installs into GitHub Copilot, where Copilot reads it, and what is
specific to this harness. Checked against GitHub's Copilot docs (docs.github.com/copilot)
and the Copilot CLI's own help on 2026-11-10, Copilot CLI 1.0.108. The registry row in
`harnesses.json` is the source of truth for paths; this guide explains them.

Copilot is one harness with several faces: the CLI, VS Code and the other IDEs, and the
cloud agent on GitHub.com, which works from an issue or a `/delegate` and opens a pull
request. They share instructions, skills and custom agents, but not every file reaches
every face, as noted below.

**Rules.** `.github/copilot-instructions.md` for the repository, read by all three faces,
and `~/.copilot/copilot-instructions.md` for the person, read by the CLI. Path-specific
files go in `.github/instructions/<name>.instructions.md` with an `applyTo` glob. Copilot
also reads `AGENTS.md`, and the CLI reads `CLAUDE.md`, `GEMINI.md` and `.claude/rules/`
at the repository root and the working directory. `copilot instruction list` shows what a
session found. The rules installer writes the Charter into `.github/copilot-instructions.md`, or
`~/.copilot/copilot-instructions.md` at global scope.

**Skills.** Project skills load from `.github/skills`, `.claude/skills` or `.agents/skills`,
personal skills from `~/.copilot/skills` or `~/.agents/skills`. The CLI, the cloud agent
and VS Code's agent mode support them. The skills installer writes to `.agents/skills`
and `~/.copilot/skills`. A cloud-agent session reads personal skills from
`.copilot/skills` in the person's dotfiles repository instead.

**Custom agents.** `.github/agents/<name>.agent.md` in the repository, `~/.copilot/agents/`
for the person, or the `agents/` folder of an organization's `.github-private`
repository. They replaced VS Code's chat modes (`.github/chatmodes/*.chatmode.md`), which
still load but are no longer what the agents installer writes. Only `description` is
required. The House's agents set `name`, `description`, `tools` and `model`. `tools`
accepts Claude Code's names as aliases (`Read`, `Grep`, `Glob`, `Bash`, `Edit`, `Task`),
so the same list restricts the agent in both harnesses. `model` applies only in the IDEs,
and `target: vscode` or `github-copilot` limits an agent to one face. Run one with
`copilot --agent <name>` or `/agent`. `COPILOT_SKILLS_DIRS` adds skill directories for a
session, which is how the recorded runs loaded Barry and Patricia from skills-hive without
installing them.

**Delegation.** Map Barry's logical roles to Copilot's agents:

| Barry role | GitHub Copilot equivalent |
|------------|---------------------------|
| explore | the `explore` custom agent (read and search tools only) |
| generalPurpose | the default agent |
| shell | the shell tool, allowed with `--allow-tool='shell(...)'` |
| code-review | `/review`, or the `code-review` custom agent |
| security-review | `/security-review` |
| best-of-n-runner | `/fleet` (parallel subagents), or several cloud-agent tasks |

**Parallelism.** `/fleet` (or `--fleet`) runs subagents in parallel, and `/tasks` lists
them. `/delegate` hands the session to the cloud agent, which works on GitHub and opens a
pull request.

**MCP servers.** The CLI reads `~/.copilot/mcp-config.json` for the person and `.mcp.json`
or `.github/mcp.json` in the workspace, all under `mcpServers`. It doesn't read
`.vscode/mcp.json`. VS Code reads `.vscode/mcp.json` under `servers`, and also the CLI's
user file as Copilot Global. `python3 hives/mcp-hive/scripts/install.py --harness
github-copilot` writes `.vscode/mcp.json`, with VS Code prompting for secrets through
`inputs`. Add `--global` to write `~/.copilot/mcp-config.json` for the CLI and VS Code
together. That file documents no way to read the environment, so a header that needs one
is left for the person to set. The cloud agent takes its servers from the repository's
settings on GitHub.

**Hooks.** JSON files in `.github/hooks/` (committed to the default branch) or
`~/.copilot/hooks/` for the person, with events such as `sessionStart`,
`userPromptSubmitted`, `preToolUse`, `postToolUse` and `sessionEnd`. The CLI also reads
hooks from `.claude/settings.json`. The House installs no hooks today.

**Memory.** Copilot Memory keeps facts about a repository, shared with its collaborators,
and preferences for each person, on GitHub rather than in a file. The CLI, the cloud agent
and code review use it. VS Code supports it but has it off by default, and Business and
Enterprise owners turn on personal preferences. `copilot memories` manages them.

**Permissions.** Tools are approved per session with `--allow-tool` and `--deny-tool`
(`shell(git:*)`, `write(path)`, `<server>(<tool>)`); deny always wins. `--allow-all-tools`
and `--allow-all` are for sandboxes. Approvals you save land in
`~/.copilot/permissions-config.json`. Without an allow rule, a headless run is denied any
tool that would ask, so Patricia can be run with only the read-only commands she needs
allowed, such as `shell(git diff:*)`.

**Headless.** `copilot -p "<prompt>"` runs one prompt and exits. Add `-s` to print only
the answer, `--output-format json` for JSON lines, `--no-ask-user` so it never waits on a
question, and `--usage-output-file <file>` for the session's AI Credits and tokens.
Barry's and Patricia's recorded runs were headless (`docs/harness-matrix.md`).

**Models.** Only pass a model when the user asks. `--model auto` lets Copilot pick, and
paid plans get 10% off model costs with it. Which models a person can choose depends on
their plan; the Free plan has auto selection only.

**Cost.** Since 2026-06-01 Copilot bills AI Credits, $0.01 each, spent per token (input,
cached input, cache write and output) at the model's rate. Pro, Pro+ and Max include
credits each month; code completions don't spend them. Some annual Pro and Pro+
subscribers stayed on premium requests. See the matrix for the current figures and their
sources.

**Other Microsoft surfaces.** **Microsoft Foundry agents** and **Copilot Studio** can run
these same `SKILL.md` files but load them from a project or deployment `skills/` folder
(you publish, not junction), and **Microsoft 365 Copilot** has used declarative agents
rather than file-based skills. It is on the watch list as the likely home of Autopilot,
formerly Scout (see [`scout.md`](scout.md)).
