# Contributing to ai-hive

ai-hive is werkrbee's harness-agnostic factory for AI agent products. Contributions are
welcome — code, hives, docs, and evals.

## Ground rules

- **Harness-agnostic.** Nothing locks to one agent, model, or vendor. Ride the open standards
  (`SKILL.md`, `AGENTS.md`, MCP, A2A).
- **Two axes.** `<thing>/` is the portable source of truth; `adapters/<harness>/` is where it
  runs. Keep them separate.
- **Docs voice.** Plain prose, sentence case, minimal bullets. Match the existing docs.

## Workflow

1. Find or open an issue; keep changes scoped to it.
2. Branch from `main`: `feat/…`, `fix/…`, `refactor/…`, `docs/…` (one issue per branch).
3. Make the change; run the checks in `.github/workflows/ci.yml` locally until green.
4. Commit with **Conventional Commits** (`type(scope): summary`) referencing the issue.
5. Open a PR using the template. CI must pass and a Charter review must pass before merge.
6. Squash-merge. Releases are automated from Conventional Commits — don't bump versions by hand.

The architecture diagram, `assets/architecture.svg`, is drawn by `scripts/architecture.py`;
edit the script, not the SVG, and run it to redraw. CI fails when the repo has a hive,
harness or Azure resource the diagram doesn't account for, or when the SVG is out of date.
The release PR stamps the new version into it. Before merging a release PR, check that the
diagram's words still hold for what the changelog says is shipping; if they don't, fix the
script in its own PR first.

## Using a coding agent

`AGENTS.md` carries the repo's context for any coding agent that reads the open standard.
Each harness adapter adds only what is specific to its harness.

This repo is set up for Claude Code: `CLAUDE.md` imports `AGENTS.md`, `.claude/commands/`
provides `/sprint-plan`, `/next`, `/work`, `/ship`, `/release`, and `.claude/agents/` has the
Barry (orchestrator) and Patricia (reviewer) subagents. You don't need Claude Code to
contribute — it's one supported path.

## Don't commit

`.DS_Store`, `node_modules/`, secrets, `.env`. See `.gitignore`.
