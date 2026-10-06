# Barry on Codex

**Skills load from:** `~/.codex/skills/` (global) or `.agents/skills/` (project).
Repo-wide instructions ride in `AGENTS.md`.

**Delegation:** Codex packages capabilities as skills and runs tools/subagents.
Map Barry's roles to Codex's agent + tool model:

| Barry role | Codex equivalent |
|------------|------------------|
| explore | search/read tools or a scoped agent |
| generalPurpose | default agent |
| shell | Codex shell/exec tool |
| code-review | review skill / scoped agent |
| security-review | security review skill |
| best-of-n-runner | parallel runs |

> Confirm exact subagent names against current Codex docs — the roles above are
> logical, not literal.

**Models:** only when asked; use OpenAI model identifiers Codex exposes.
