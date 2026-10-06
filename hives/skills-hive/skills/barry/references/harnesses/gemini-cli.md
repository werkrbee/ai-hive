# Barry on Gemini CLI (and Antigravity)

**Skills load from:** `~/.gemini/skills/` (global) or `.agents/skills/` (project).
The same `SKILL.md` skills also load in Google Antigravity.

**Delegation:** Gemini CLI runs skills and extensions; map Barry's roles to its
agent/tool model:

| Barry role | Gemini CLI equivalent |
|------------|-----------------------|
| explore | search/read tooling |
| generalPurpose | default agent |
| shell | shell tool |
| code-review | review skill / scoped agent |
| security-review | security review skill |

> Confirm exact subagent names against current Gemini CLI / Antigravity docs.

**Models:** only when asked; use the Gemini model identifiers the CLI exposes.
