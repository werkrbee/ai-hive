# Barry on Goose

Every surface the House installs into Goose, where it reads it, and what is specific to this
harness. Checked against Goose's docs (goose-docs.ai) and the source of Goose 1.59.0 on
2026-11-12. The registry row in `harnesses.json` is the source of truth for paths; this
guide explains them.

Goose is an open-source agent under Apache 2.0, started at Block and now governed by the
Linux Foundation's Agentic AI Foundation (`aaif-goose/goose`). It runs as a desktop app, as
a CLI (`goose`) and over the Agent Client Protocol, and its GDK crates let you build your
own agent from the same parts. Every tool it has comes from an extension, which is an MCP
server or a platform extension built into Goose.

**Rules.** Goose loads `AGENTS.md` and `.goosehints` from the working directory up to the
repository root at the start of a session, then loads the ones in deeper folders as it reads
or edits files there; a deeper file is meant for that part of the code. Global ones live in
`~/.config/goose/` (both names), and Goose also reads `~/.agents/AGENTS.md`. The
`CONTEXT_FILE_NAMES` setting replaces the list of names, for example to add `CLAUDE.md`. In
a hints file, `@file.md` pulls that file's text into the context, and a plain path points
Goose at it to read when needed. The rules installer writes the Charter to `AGENTS.md`,
shared with the other harnesses that read it, or to `~/.config/goose/AGENTS.md` at global
scope, so it loads once; `.goosehints` is left for hints only Goose should see. Hints need
the Developer extension, which is on by default.

**Skills.** `.agents/skills/` in the project and `~/.agents/skills/` for the person, which
Goose recommends; it also reads `.goose/skills/`, `.claude/skills/` and their home-folder
twins, and skills from installed plugins. Goose lists each skill's name and description at
the start of a session and loads the instructions when a request matches or when asked
(`/skills <name>`, or `goose skills list` to see them). The skills installer writes to
`.agents/skills` and `~/.agents/skills`.

**Subagents.** The `delegate` tool, from the Summon extension, starts a subagent with a
direct prompt or from a named source, sequentially or in parallel (five at once by default,
`GOOSE_MAX_CONCURRENT_SUBAGENTS`). A subagent can't start subagents, change extensions or
manage schedules, times out after five minutes unless asked otherwise, and runs only in
Autonomous mode: Goose turns subagents off in the other permission modes. A named source
can be a recipe, from `.goose/recipes/`, `.agents/recipes/`, `~/.config/goose/recipes/` or
`GOOSE_RECIPE_PATH`, or a Markdown agent file from `.goose/agents/`, `.claude/agents/` or
`.agents/agents/` and their home-folder twins. An agent file carries only `name`,
`description` and `model`, so a subagent run from one inherits every extension of the
session, whatever tools it lists. A recipe can narrow that: its `extensions` list is all the
subagent gets, and an extension's `available_tools` narrows it to some of its tools. The
agents installer therefore writes each agent as a recipe, `.goose/recipes/<name>.yaml`, with
the prompt as `instructions` and only the extensions and tools the agent's own tools map to
(Edit and Write become the developer extension's `edit` and `write`, Bash its `shell`). It
fails closed: a tool Goose has no stand-in for is left out, with a warning, and an agent
whose tools map to nothing gets `extensions: []`.

Goose has no tool that only reads a file's text. The developer extension's tools are
`write`, `edit`, `shell`, `tree` and `read_image`, and Goose reads files with `shell`, which
can change them too. A read-only agent such as `explore` or the review agents therefore gets
`tree`, `read_image` and the Analyze extension, which outlines code (its functions, classes,
imports and call graphs) but doesn't show a file's text, and the installer warns that it
can't read files. Add `shell` to its `available_tools` by hand if it must, knowing that
makes it able to edit.

**Delegation.** Map Barry's logical roles to Goose's agents:

| Barry role | Goose equivalent |
|------------|------------------|
| explore | the House's `explore` recipe (outlines only), or a delegated subagent asked for research |
| generalPurpose | the main agent, or a subagent from a direct prompt |
| shell | the developer extension's `shell` tool |
| code-review | the `code-review` recipe |
| security-review | the `security-review` recipe |
| best-of-n-runner | several subagents in parallel, or a recipe's `sub_recipes` |

**MCP servers.** Goose calls them extensions. They live under `extensions` in the person's
`~/.config/goose/config.yaml`, beside every other setting, and Goose documents no project
file; a recipe can carry its own. A local server has `type: stdio`, `cmd`, `args` and
`envs`; a remote one has `type: streamable_http`, `uri` and `headers` (SSE isn't supported).
Each takes `enabled`, `timeout` and `available_tools`. `env_keys` names variables Goose
fills from the shell or its secret store, and a header or URI reads them as `${NAME}`.
Because config.yaml holds the person's other settings, `python3
hives/mcp-hive/scripts/install.py --harness goose` prints the entries to paste rather than
editing the file, with a secret header as a `${NAME}` reference and the key in `env_keys`.
`goose configure` adds and toggles extensions interactively, and `goose session
--with-extension` adds one for a session.

**Hooks.** Goose follows the Open Plugins hooks specification: a plugin with a
`hooks/hooks.json` maps lifecycle events, such as `SessionStart`, `UserPromptSubmit`,
`PreToolUse`, `AfterFileEdit`, `BeforeShellExecution` and `Stop`, to commands that receive
the event as JSON on stdin. Plugins live in `.agents/plugins/` in the project and
`~/.agents/plugins/` for the person. The House installs no hooks today.

**Memory.** The built-in Memory extension, off by default, keeps what Goose is taught in
`.goose/memory/` for the project and `~/.config/goose/memory/` for the person. Top of Mind
injects standing instructions every turn, and Chat Recall searches past sessions. The
House's knowledge-hive files remain the way to keep state that travels with the repository.

**Permissions.** A permission mode per session: Autonomous (the default, which approves
everything), Manual Approval, Smart Approval (approves low-risk actions and asks about the
rest) and Chat Only (no tools at all). `GOOSE_MODE` sets it (`auto`, `approve`,
`smart_approve`, `chat`), and `/mode` changes it mid-session. In Manual and Smart Approval
each tool can be set to always allow, ask or never allow, kept in `permission.yaml`. Since
subagents run only in Autonomous mode, a recipe's extension list is the one limit a
subagent has.

**Headless.** `goose run -t "<prompt>"` runs once and exits; `-i <file>` reads the prompt
from a file or stdin, `--recipe <name>` runs a recipe, `--output-format json` or
`stream-json` prints structured output, `--no-session` keeps nothing, and `--provider` and
`--model` choose the model. A headless run takes the session's permission mode, which is
Autonomous unless set, so give it a recipe whose extensions can't write, or a directory it
can't change, for a run that mustn't edit. The JSON output ends with the session's token
counts and Goose's own cost estimate; its `input_tokens` include the cached ones. Barry's
and Patricia's recorded runs used `goose run` in a worktree with its write permissions
removed, signed in with a ChatGPT plan (`docs/harness-matrix.md`).

**Models.** Only pass a model when the user asks, with `--provider` and `--model`. Goose
reaches dozens of providers on your own key, local servers such as Ollama, LM Studio,
Docker Model Runner and Ramalama, and subscriptions it signs in to: a ChatGPT Plus or Pro
plan, GitHub Copilot, or Claude Code, Codex and Cursor through their own CLIs. `GOOSE_SUBAGENT_MODEL`
and `GOOSE_SUBAGENT_PROVIDER` give subagents their own model.

**Cost.** Goose itself is free and adds no fee. Inference is billed by whoever serves it:
your provider at its list price on your own key, or a subscription's usage against the
plan. See the matrix for the current figures and their sources.
