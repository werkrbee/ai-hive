# Barry on Codex

Every surface the House installs into Codex, where Codex reads it, and what is specific
to this harness. Checked against OpenAI's Codex docs (learn.chatgpt.com/docs, which
developers.openai.com/codex now redirects to) and the Codex CLI's own help on
2026-11-10, Codex CLI 0.167.0. The registry row in `harnesses.json` is the source of
truth for paths; this guide explains them.

Codex runs in the terminal (`codex`), in the IDE extension, in the ChatGPT desktop app
and in the cloud, all reading the same `~/.codex` home (`CODEX_HOME` moves it).
Configuration lives in `~/.codex/config.toml`, and a project can add `.codex/config.toml`,
which Codex reads only once the project is trusted.

**Rules.** `AGENTS.md`. Codex reads `~/.codex/AGENTS.md` (or `AGENTS.override.md`) for
the person, then one file per directory from the project root down to the working
directory, so a nearer `AGENTS.md` comes later and wins. Other file names count only if
listed in `project_doc_fallback_filenames`, and the total stops at 32 KiB
(`project_doc_max_bytes`). The rules installer writes the Charter to `AGENTS.md` and
`~/.codex/AGENTS.md`.

**Skills.** `.agents/skills` in each directory from the working directory up to the
repository root, `~/.agents/skills` for the person, and `/etc/codex/skills` for an
admin. Codex follows symlinked skill folders. The skills installer writes to
`.agents/skills` and `~/.agents/skills`; earlier installs went to `~/.codex/skills`,
which Codex's docs no longer list, so move a skill from there if Codex doesn't see it.
Codex picks a skill by its description, or when a prompt names it.

**Subagents.** Codex spawns subagents when asked, and has three built in: `default`,
`worker` (implementation) and `explorer` (read-heavy exploration). A custom agent is one
TOML file in `.codex/agents/` (project) or `~/.codex/agents/` (person) with `name`,
`description` and `developer_instructions`, and optionally `model` and
`model_reasoning_effort`. The agents installer renders each agent into
`.codex/agents/<name>.toml`, with its prompt as `developer_instructions`. Codex has no
tools list: a subagent inherits its parent's sandbox and approvals, and setting
`sandbox_mode` in the file doesn't change that. So the installer can't carry an agent's
`tools` list into Codex, and it warns for each agent that has one: a read-only agent
such as `explore` or Patricia's `charter-review` is read-only in Codex only when the
session runs with `--sandbox read-only`. Pass the flag explicitly, since a `sandbox_mode`
in `config.toml` can change `codex exec`'s default. Its instructions alone don't enforce
it: the Charter runs a delegate under the stricter of its own grant and its caller's, and
Codex can't apply the agent's half.
A custom agent named like a built-in one takes its place.

**Delegation.** Map Barry's logical roles to Codex's agents:

| Barry role | Codex equivalent |
|------------|------------------|
| explore | the `explore` custom agent, or the built-in `explorer` |
| generalPurpose | `default` |
| shell | Codex's shell tool, within the sandbox |
| code-review | `codex review`, or the `code-review` custom agent |
| security-review | the `security-review` custom agent |
| best-of-n-runner | several subagents at once (`[agents] max_concurrent_threads_per_session`) |

Ask for a subagent by name in the prompt ("have `explore` map the auth module"). The CLI's
`/subagents` switches between their threads.

**MCP servers.** `[mcp_servers.<name>]` tables in `~/.codex/config.toml`, or in a trusted
project's `.codex/config.toml`. A local server takes `command`, `args` and `env`; a
remote one takes `url`, with `bearer_token_env_var`, `http_headers` or `env_http_headers`.
`python3 hives/mcp-hive/scripts/install.py --harness codex` prints the tables to paste,
since the installer doesn't edit TOML. `codex mcp list` shows what Codex found.

**Hooks.** `hooks.json` or inline `[hooks]` tables, in `~/.codex/` or a project's
`.codex/`, with events including `SessionStart`, `PreToolUse`, `PermissionRequest`,
`PostToolUse`, `SubagentStart`, `Stop` and `SessionEnd`. Codex runs a hook only after
you trust it (`/hooks`), and it trusts the definition by hash, so an edited hook needs
trusting again. The House installs no hooks today.

**Memory.** Codex memories are off by default. Turn them on with `[features] memories =
true` (or in the desktop app's settings), and use `/memories` to choose whether a chat
reads or adds to them. They stay on the machine, under the Codex home.

**Permissions.** A sandbox (`read-only`, `workspace-write` or `danger-full-access`) and an
approval policy (such as `on-request` or `never`), set with `--sandbox` and `--ask-for-approval`
or `sandbox_mode` and `approval_policy` in `config.toml`. Rules files control which
commands may run outside the sandbox.

**Headless.** `codex exec "<prompt>"` runs one task and exits, in a read-only sandbox by
default. `--json` streams events as JSON lines; each `turn.completed` carries the turn's
`input_tokens`, `cached_input_tokens` and `output_tokens`. `-o <file>` saves the final
message, `--ephemeral` keeps no session, and `--skip-git-repo-check` runs outside a
repository. Barry's and Patricia's recorded runs were headless (`docs/harness-matrix.md`).

**Models.** Only pass a model when the user asks, with `-m <model>` or `model` in
`config.toml`; use the OpenAI model identifiers Codex lists, such as `gpt-6.1-sol` or
`gpt-6-luna`.

**Cost.** Since 2026-04-02 Codex usage on ChatGPT plans is priced per token: Codex's rate
card gives credits per million input, cached input and output tokens for each model, with
no charge for cache writes. Plus, Pro and Business include usage and can buy more credits;
what a credit costs depends on the plan and isn't published on the rate card. With an API
key, Codex bills at OpenAI's API list prices. See the matrix for the current figures and
their sources.
