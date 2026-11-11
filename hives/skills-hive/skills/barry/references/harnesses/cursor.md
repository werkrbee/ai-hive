# Barry on Cursor

Every surface the House installs into Cursor, where Cursor reads it, and what is
specific to this harness. Checked against Cursor's docs (cursor.com/docs) on 2026-11-10,
Cursor CLI 2026.11.10. The registry row in `harnesses.json` is the source of truth for
paths; this guide explains them.

Cursor runs as the editor, as the CLI (`agent`), and as Cloud Agents, which work in their
own VMs and open pull requests. All three read the project's `.cursor/` folder; Cloud
Agents don't see your home directory.

**Rules.** Project rules are `.mdc` files in `.cursor/rules/`, each with frontmatter that
says when it applies: `alwaysApply: true` for every request, `globs` for matching files,
or a `description` the agent uses to decide. A plain `.md` file there is ignored. Cursor
also reads `AGENTS.md`, and keeps User Rules (in settings) and Team Rules (in the
dashboard) outside the repository. The rules installer writes the Charter to
`.cursor/rules/queen-charter.mdc` with `alwaysApply: true`.

**Skills.** `.cursor/skills/` or `.agents/skills/` in the project, including nested folders
in a monorepo, which then apply only under that folder; `~/.cursor/skills/` or
`~/.agents/skills/` for the person. For compatibility Cursor also loads
`.claude/skills/`, `.codex/skills/` and their home-directory versions. Cloud Agents get
project skills and synced personal skills only. The skills installer writes to
`.cursor/skills` and `~/.cursor/skills`.

**Subagents.** Markdown files with YAML frontmatter in `.cursor/agents/` or
`~/.cursor/agents/`; Cursor also reads `.claude/agents/` and `.codex/agents/` (and their
home versions), so agents installed for those harnesses show up too. The fields are
`name`, `description`, `model` (`inherit` or a model ID, with options such as
`claude-opus-5[effort=high]`), `readonly` and `is_background`. There is no tools list.
Instead `readonly: true` stops file edits and state-changing shell commands, so the agents
installer sets it for every agent whose tools list holds no tool that writes, which keeps
`explore` and the review agents read-only as the Charter requires. Cursor also has two
built-in subagents, Explore and Browser.

**Delegation.** Map Barry's logical roles to Cursor's agents:

| Barry role | Cursor equivalent |
|------------|-------------------|
| explore | the built-in Explore subagent, or the House's `explore` agent |
| generalPurpose | the main agent |
| shell | the terminal tool |
| code-review | the `code-review` agent; Bugbot reviews pull requests |
| security-review | the `security-review` agent |
| best-of-n-runner | several subagents (`is_background: true`), or Cloud Agents in parallel |

**Cloud Agents.** Start one from the editor (Cloud in the agent dropdown), cursor.com/agents,
Slack, Linear, GitHub (`@cursor` on an issue or PR) or the API. In the CLI, a message that
starts with `&` hands the conversation to a Cloud Agent. They need source control
connected by an admin and are on Premium and above.

**MCP servers.** `.cursor/mcp.json` in the project or `~/.cursor/mcp.json` for the person,
under `mcpServers`, with `${env:NAME}` for values from the environment.
`python3 hives/mcp-hive/scripts/install.py --harness cursor` writes the project file, and
`--global` the personal one.

**Hooks.** `hooks.json` in `.cursor/` (project) or `~/.cursor/` (person): scripts that talk
JSON over stdio on events such as `beforeShellExecution`, `beforeReadFile`,
`afterFileEdit`, `preToolUse`, `postToolUse`, `beforeSubmitPrompt` and `stop`. Cloud
Agents run the project's hooks but not the person's, and skip `sessionStart`,
`sessionEnd` and the MCP events. The House installs no hooks today.

**Memory.** Cursor documents no memory feature for its agent: rules are how context
carries from one session to the next. The House's knowledge-hive files are the way to
keep state.

**Permissions.** The CLI reads `permissions.allow` and `permissions.deny` from
`~/.cursor/cli-config.json` and, for a project, `.cursor/cli.json`, with tokens such as
`Shell(git)`, `Read(src/**)` and `Write(docs/**)`. In print mode, nothing is changed
without `--force`.

**Headless.** `agent -p "<prompt>"` (print mode) runs once and exits. `--output-format
json` gives a result with usage, and `stream-json` streams events. Without `--force` it
proposes changes instead of making them, and shell commands such as `gh` are refused.
Barry's recorded run was headless (`docs/harness-matrix.md`). Patricia's waits on #268:
the account's Free plan ran out after Barry's run, so Cursor's row stays unverified until
it's recorded.

**Models.** Only pass a model when the user asks, with `--model` or `model` in a subagent.
Cursor's own models (Composer and Grok) draw from the plan's pool; third-party models
such as `claude-*` and `gpt-*` bill per token.

**Cost.** Cursor is sold as part of The X Subscription. Each paid plan includes a weekly
pool for Cursor's own models. Third-party models are billed at their API list price from
prepaid credit, on Premium and above. Teams and Enterprise add the Cursor Token Rate,
$0.25 per million input, output and cached tokens, on eligible third-party models. A model
whose cache-read price is under $0.10 per million is exempt. Pro, Pro+, Ultra and the
older Teams seats are legacy plans that keep working as they were. See the matrix for
the current figures and their sources.
