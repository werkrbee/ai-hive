# Barry on OpenCode

OpenCode is a popular **open-source** terminal coding agent that reads the
`SKILL.md` standard. It's a first-class peer harness — treat it like any other,
with the bonus that it's community-driven and model-agnostic.

**Skills load from:** `~/.config/opencode/skills/` (global) or `.agents/skills/`
(project).

**Delegation:** OpenCode runs skills and tools in the terminal. Map Barry's roles:

| Barry role | OpenCode equivalent |
|------------|---------------------|
| explore | file/grep search tools |
| generalPurpose | the default agent |
| shell | OpenCode's shell tool |
| code-review | a review skill on the diff |
| security-review | a security review skill |

**Open-source note:** because OpenCode is model-agnostic and self-hosted, it's a
good target for keeping Barry fully portable — nothing here should assume a
proprietary agent or model. Only pass a model when the user asks.
