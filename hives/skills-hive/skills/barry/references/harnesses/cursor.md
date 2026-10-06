# Barry on Cursor

**Skills load from:** `~/.cursor/skills/` (global) or `.cursor/skills/` /
`.agents/skills/` (project).

**Delegation:** Cursor's native subagent types map almost 1:1 to Barry's roles:

| Barry role | Cursor subagent |
|------------|-----------------|
| explore | `explore` |
| generalPurpose | `generalPurpose` |
| shell | `shell` |
| harness-guide | `cursor-guide` |
| ci-investigator | `ci-investigator` |
| code-review | `bugbot` (set Task description to `Bugbot`) |
| security-review | `security-review` (set Task description to `Security Review`) |
| best-of-n-runner | `best-of-n-runner` |

**Extras:** Cursor Automations and Cloud Agents are available; `run_in_background`
and `resume` work for long / continued jobs.

**Models:** only when asked — Cursor slugs such as `composer-2.5-fast`,
`cursor-grok-4.5-high-fast`, and the `claude-*` / `gpt-*` thinking slugs.
