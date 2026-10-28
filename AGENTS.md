# AGENTS.md — ai-hive

Canonical agent context for this repo lives in **`CLAUDE.md`** — read it. This file mirrors
the essentials for non-Claude tools (AGENTS.md is the cross-tool standard). Keep the two in
sync when either changes.

## Essentials

- **What:** werkrbee's House of Hives — a harness-agnostic *factory* for AI agent products.
  Monorepo; hives live under `hives/` as plain directories.
- **Vision and mission:** every person and organization is the world's best user of AI and
  an expert at it; ai-hive is the framework that gets them there, obsessed with how to use
  AI across every model, harness and part of the craft, and explaining why what works
  works.
- **Conventions:** harness-agnostic (open standards: SKILL.md, AGENTS.md, MCP, A2A); two-axis
  (`<thing>/` vs `adapters/<harness>/`); kebab-case dirs; plain-prose docs, sentence case.
- **Workflow:** trunk-based branches, Conventional Commits, CI must pass + Charter review,
  squash-merge, automated releases. See `CONTRIBUTING.md`.
- **Roadmap & sprints:** `ROADMAP.md`, `docs/sprints/`.
- **Don't commit:** `.DS_Store`, `node_modules/`, secrets, `.env`.
