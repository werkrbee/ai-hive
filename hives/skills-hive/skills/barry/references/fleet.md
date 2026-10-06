# Barry's Agent Fleet

Reference for delegating work. Barry assigns **one clear outcome per agent**.

> **Harness-agnostic.** The agent types and skills below are logical roles. Map
> each to the equivalent your current harness (Claude Code, Codex, Cursor,
> GitHub Copilot, Gemini, Scout, Goose, …) provides; if a role has no equivalent,
> Barry does it directly or skips it.

## Subagent types

### explore

**Use for:** Fast codebase discovery — find files, APIs, patterns, "where is X?"

**Prompt tips:**

- Specify thoroughness: `quick`, `medium`, or `very thorough`
- Ask for paths, symbols, and a short architecture note
- Narrow directory or naming convention when known

**Avoid:** Implementation, git operations, long-running fixes.

---

### generalPurpose

**Use for:** Research, multi-step tasks, implementation when no narrower type fits.

**Prompt tips:**

- Full context in the prompt (paths, errors, acceptance criteria)
- State exactly what to return to Barry

**Avoid:** Using for pure search (use `explore`) or pure shell (use `shell`).

---

### shell

**Use for:** Git, gh, npm, docker, migrations, scripted terminal work.

**Prompt tips:**

- Exact commands or goal + constraints
- Say whether commits/pushes are allowed (default: no unless user asked)

---

### harness-guide

**Use for:** Questions about the agent harness/platform itself — settings,
automations / scheduled tasks, background or cloud agents, CLI, features.

**Avoid:** User's application code unless it's about harness integration.

> Maps to whatever "how this tool works" agent the current harness provides.

---

### ci-investigator

**Use for:** **One** failing PR CI check — root cause + fix suggestion.

**Prompt tips:**

- PR URL or repo + check name + failure snippet
- Return: cause, fix, whether change belongs in this PR

---

### code-review

**Use for:** Code review focused on bugs, correctness, edge cases.

**Prompt shape** (follow `review-code` skill):

```
Full Repository Path: ...
Diff: branch changes | uncommitted changes | natural language
Change Description: ... (if natural language)
Custom Instructions: ... (optional)
```

Set the Task `description` to the review label your harness's code-review agent
expects (e.g. `Bugbot` in Cursor, or its equivalent elsewhere).

---

### security-review

**Use for:** Security-focused review of local changes.

**Prompt shape** (follow `review-security` skill):

```
Full Repository Path: ...
Diff: branch changes | uncommitted changes
Custom Instructions: ... (optional)
```

Set Task `description` to exactly `Security Review`.

---

### best-of-n-runner

**Use for:** Isolated parallel attempts (best-of-N), experiments in separate worktrees.

**Prompt tips:**

- Each attempt needs its own branch/worktree story
- Barry compares outcomes and picks or merges recommendation

---

## Parallel dispatch patterns

### Pattern A — Independent investigations

One message, multiple Task calls:

- Auth flow (`explore`) + failing test logs (`shell`) + CI failure (`ci-investigator`)

### Pattern B — Dual review

One message:

- `code-review` + `security-review` on same diff scope

### Pattern C — Map then build

Sequential:

1. `explore` → architecture map
2. `generalPurpose` → implement using map in prompt

### Pattern D — Long background job

- `generalPurpose` with `run_in_background: true`
- Barry continues other streams or prepares synthesis template
- Await completion notification before final report

---

## Model selection

Only pass a `model` when the user explicitly requests one. Available model
identifiers are **harness-specific** — use whatever slugs the current harness
exposes (check its model list or docs). Do not hardcode model names into this
skill; they differ across Claude Code, Codex, Cursor, Copilot, Gemini, Scout, etc.

If the user asks for a model the active harness doesn't offer, say so and list the
options that harness supports.

---

## Failure handling

| Situation | Barry action |
|-----------|----------------|
| Wrong subagent type | Re-launch with correct type |
| Missing path/context | Add context and retry once |
| Auth / permissions | Stop; tell user what to connect |
| Ambiguous product choice | Ask user; do not guess |
| Agent blocked on destructive op | Escalate; never override user git safety rules |

---

## What Barry keeps

Do **not** delegate:

- Final executive summary and prioritization
- User-facing tradeoff decisions
- Choosing whether to commit, push, or open PRs (unless user pre-authorized)
- Deciding when the mission is complete
