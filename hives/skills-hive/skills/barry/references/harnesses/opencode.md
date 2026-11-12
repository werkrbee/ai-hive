# Barry on OpenCode

Every surface the House installs into OpenCode, where it reads it, and what is specific to
this harness. Checked against OpenCode's V2 docs (opencode.ai/docs) on 2026-11-12. The
registry row in `harnesses.json` is the source of truth for paths; this guide explains them.

OpenCode is an open-source, model-agnostic coding agent under MIT. V2 runs a terminal UI,
a minimal UI (`opencode mini`), a desktop app, a mobile client and an SDK, all talking to
one background server per user that owns sessions, configuration and permissions. V2
renamed much of V1's configuration; `opencode.ai/docs/migrate-v1` maps the old names, and
V2 still reads V1 files with a warning.

**Rules.** `AGENTS.md`, and only that name: V2 doesn't fall back to `CLAUDE.md`. OpenCode
loads `~/.config/opencode/AGENTS.md`, then every `AGENTS.md` from the working directory up
to the project root, and picks up deeper ones as the agent reads into their folders. It
notices edits to a loaded file and sends the update before the next prompt. The rules
installer writes the Charter to `AGENTS.md`, shared with the other harnesses that read it,
or to `~/.config/opencode/AGENTS.md` at global scope.

**Skills.** `.opencode/skills/` in the project, searched from the working directory up to
the project root, and `~/.config/opencode/skills/` for the person; it also reads
`.claude/skills/`, `.agents/skills/` and their home-folder twins. A `skills` array in
`opencode.json` adds folders or HTTP catalogs. The agent loads a skill's instructions with
the `skill` tool when it's relevant. The skills installer writes to `.opencode/skills` and
`~/.config/opencode/skills`.

**Subagents.** Markdown files in `.opencode/agents/` (project) or
`~/.config/opencode/agents/` (person), or entries under `agents` in `opencode.json`; the
file name is the agent's ID and the body its system prompt. The V2 fields are
`description`, `mode` (`primary`, `subagent` or `all`), `model` (`provider/model#variant`),
`permissions` and display options. A file that uses any V2 field is read as V2, and V1
fields in it, such as `name` and `tools`, are ignored with a warning, so the agents
installer writes `description`, `mode: subagent` and `permissions` and no name. V2 has no
tools list: an agent is limited by permission rules instead. The installer turns the
actions an agent's tools don't grant (`edit`, `shell`, `webfetch`, `websearch`,
`subagent`) into deny rules, which keeps `explore` and the review agents read-only, and
leaves reads to the session's own rules so defaults such as asking before reading a
`.env` file still apply. OpenCode's default rules allow every action (see Permissions), so
an agent with no rules of its own can do anything; the translation therefore fails closed:
an agent with a tool OpenCode has no action for still gets its deny rules, and a warning
saying to add an allow rule by hand if it needs more. A subagent runs in its own child
session in the background, and reports when it goes idle. Built in are `build` and `plan`
(primary) and `general` and `explore` (subagents).

**Delegation.** Map Barry's logical roles to OpenCode's agents:

| Barry role | OpenCode equivalent |
|------------|---------------------|
| explore | the built-in `explore` subagent, or the House's `explore` agent |
| generalPurpose | the `build` agent, or the `general` subagent |
| shell | the shell tool, within the session's `shell` rules |
| code-review | the `code-review` agent |
| security-review | the `security-review` agent |
| best-of-n-runner | several background subagents, each in its own child session |

**MCP servers.** Under `mcp.servers` (V2 doesn't put server names directly under `mcp`) in
`opencode.json` or `opencode.jsonc` in the project or `~/.config/opencode/` for the person.
A local server has `type: "local"`, a `command` array holding the executable and its
arguments, and `environment`; a remote one has `type: "remote"`, `url` (Streamable HTTP
only) and `headers`. `{env:NAME}` reads the environment, and shell syntax such as `$NAME`
doesn't. Remote servers try OAuth unless `oauth` is `false`. `python3
hives/mcp-hive/scripts/install.py --harness opencode` writes the project's
`opencode.json`, and `--global` the personal one, with a secret header as an `{env:NAME}`
reference and OAuth turned off for that server. `opencode mcp list` shows what connected.

**Hooks.** Server plugins register hooks that intercept live operations, such as prompt
admission, model requests and retries, and can add tools, agents, commands and permission
checks. Plugins come from `plugins` in `opencode.json`, as packages or local folders, and
from `.opencode/plugins/`. The House installs no hooks today.

**Memory.** OpenCode has no memory feature of its own; `AGENTS.md` files are how guidance
carries from one session to the next. The House's knowledge-hive files serve that purpose.

**Permissions.** An ordered list of rules, each an `action`, a `resource` and an `effect`
(`allow`, `deny` or `ask`), in `permissions` in `opencode.json` and on each agent; the last
match wins, and an operation touching several resources is denied if any one is. The
actions include `read`, `edit`, `glob`, `grep`, `shell`, `subagent`, `skill`, `webfetch`,
`websearch`, `external_directory` and one per MCP tool. OpenCode puts its default rules
first: allow every action, then ask before reading `.env` files, as `opencode debug agents`
shows for each agent. A rule added after them narrows that; an action no rule matches at
all, which the defaults leave rare, is asked about. Policies from an administrator or an
OpenCode Console workspace outrank them.

**Headless.** `opencode run "<prompt>"` sends one message and prints the reply; `--format
json` prints JSON Lines, `--agent` picks the agent (`plan` for a run that shouldn't edit),
`--model` the model, and `--auto` approves whatever isn't denied. In CI, `--standalone`
runs a private server that receives the provider key from the environment. Barry's and
Patricia's recorded runs used `--agent plan`, signed in with a ChatGPT plan
(`docs/harness-matrix.md`).

**Models.** Only pass a model when the user asks, with `--model provider/model`. OpenCode
reaches models through its catalog of providers on your own key, a ChatGPT Plus or Pro plan
(Connect OpenAI, then Sign in with ChatGPT), local servers, OpenCode Console's inference,
or OpenCode Go's open coding models. Several Console models are free for a limited time.

**Cost.** OpenCode itself is free. A ChatGPT plan's usage counts against the plan. OpenCode
Console sells inference at the provider's list price, with prepaid credits that carry a
4.6% plus $0.31 processing fee on each purchase and no seat fees. It is what was OpenCode
Zen, whose pages now redirect to it. OpenCode Go costs $10 a month, Go Plus $40 and Go
Teams $20 a member, for open models with usage limits. See the matrix for the current
figures and their sources.
