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

## Using Claude Code

This repo is set up for Claude Code: `CLAUDE.md` carries the context, `.claude/commands/`
provides `/sprint-plan`, `/work`, `/ship`, `/release`, and `.claude/agents/` has the Barry
(orchestrator) and Patricia (reviewer) subagents. You don't need Claude Code to contribute —
it's one supported path.

## Don't commit

`.DS_Store`, `node_modules/`, secrets, `.env`. See `.gitignore`.
