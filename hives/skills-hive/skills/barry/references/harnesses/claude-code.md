# Barry on Claude Code

**Skills load from:** `~/.claude/skills/` (global) or `.claude/skills/` (project).

**Delegation:** Claude Code launches subagents with the Task tool, choosing a
subagent type. Map Barry's logical roles to Claude Code's agents:

| Barry role | Claude Code equivalent |
|------------|------------------------|
| explore | `Explore` (read-only search agent) |
| generalPurpose | `general-purpose` |
| shell | Bash tool, or `general-purpose` for scripted work |
| harness-guide | ask about Claude Code features directly |
| ci-investigator | `general-purpose` scoped to one failing check |
| code-review | `general-purpose` with a review prompt, or a review skill |
| security-review | `security-review` skill |
| best-of-n-runner | several `general-purpose` agents in one message |

**Parallelism:** send multiple Task calls in a single message; use
`run_in_background` for long jobs and await completion before synthesizing.

**Models:** only pass a model when the user asks; use Claude Code's available
model identifiers.
