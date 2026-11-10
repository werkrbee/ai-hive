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

## Harness rows

`harnesses.json` is the harness registry: every harness, its install paths and, for each
one in the pro-code and low-code tens, a row saying what works in it and what it costs
(`docs/harness-ecosystem.md`). CI holds the registry to two checks, and both name what to
fix.

The conformance check, in `scripts/check-installers.sh`, installs the House for each
harness into a sandbox and fails when a pro-code harness in the ten has a file missing
from where its row says it lands. Either the installer or the row is wrong. If the
harness has moved a path, confirm the new one in the vendor's docs, change the path in
`harnesses.json`, and update the capability's source and date. If the installer is wrong,
fix it; installers read their paths from the registry, so they shouldn't need a path of
their own. A harness outside the tens is only reported.

A row in either ten goes stale 90 days after the oldest date it rests on, counting its
capabilities, its cost and the list prices of the models its cost is quoted for, and
`python3 scripts/harnesses.py check` then fails. Re-verify each stale field against the
vendor's own docs or price page. Change what has changed, set its source to the page you
read and its date to today, and run `python3 scripts/harnesses.py matrix` to redraw
`docs/harness-matrix.md`. A field you can't confirm goes back to unknown; it isn't
re-dated without being re-read.

A row becomes verified in its harness's alignment issue. Every field is checked against
the vendor's docs, none is left unknown, and for a pro-code harness Barry and Patricia
are each run once in the real harness. Record each run under the row's `runs`: the agent,
date, harness version, model, the command, the input, cache-write, cached and output
tokens, the cost as the harness reports it, and the result. Claude Code's row is the
example. `check` refuses a verified row that falls short of any of these.

## Using a coding agent

`AGENTS.md` carries the repo's context for any coding agent that reads the open standard.
Each harness adapter adds only what is specific to its harness.

This repo is set up for Claude Code: `CLAUDE.md` imports `AGENTS.md`, `.claude/commands/`
provides `/sprint-plan`, `/next`, `/work`, `/ship`, `/release`, and `.claude/agents/` has the
Barry (orchestrator) and Patricia (reviewer) subagents. You don't need Claude Code to
contribute — it's one supported path.

## Don't commit

`.DS_Store`, `node_modules/`, secrets, `.env`. See `.gitignore`.
