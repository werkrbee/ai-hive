# {{PROJECT_NAME}}

{{DESCRIPTION}}

A **werkrbee initiative**, scaffolded by
[projects-hive](https://github.com/werkrbee/ai-hive/tree/main/hives/projects-hive) and wired to the House
of Hives via the `werkrbee-core` pack.

- **Barry** (the King Bee) orchestrates the work — see `.claude/agents/` and the
  installed skills.
- **Patricia** (the Queen Bee) governs it — the operating law is in `AGENTS.md`
  (and `CLAUDE.md`, `.cursor/rules/`, `.github/copilot-instructions.md`).
- **Tools** are wired via `.mcp.json` (and per-harness MCP configs).
- **Review agents** (`explore`, `code-review`, `security-review`, `charter-review`)
  are ready to dispatch.

## Getting started

Open this folder in any supported harness (Claude Code, Cursor, GitHub Copilot).
The charter, tools, and agents are already installed for the project. Skills
(Barry, Patricia) install globally, so they're available here and everywhere.

## Layout

```text
{{PROJECT_SLUG}}/
├── AGENTS.md / CLAUDE.md / .cursor/rules/   # the law (Patricia)
├── .mcp.json / .cursor/mcp.json / .vscode/  # tools
├── .claude/agents/ · .github/chatmodes/     # the review fleet
├── docs/                                     # your working docs
└── README.md
```
