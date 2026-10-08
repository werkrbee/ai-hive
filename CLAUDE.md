# CLAUDE.md — ai-hive

Context for Claude Code working in this repository. (A mirror lives in `AGENTS.md` for
non-Claude tools — keep the two in sync.)

## What this is

`ai-hive` is **werkrbee's House of Hives** — a harness-agnostic *factory* for building AI
agent products. It is not an app; it is the reusable layers apps are assembled from. The
guiding thesis: build the factory, then the product (`docs/factory-thesis.md`), and keep a
product's capabilities independent of any one interface (`docs/interface-independence.md`).

**Monorepo.** The hives live under `hives/` as plain directories (migrated off git
submodules — see `scripts/monorepo-migrate.sh`). Change them with ordinary edits; PRs can
span hives atomically.

## Layout

```
hives/
  skills-hive/     capabilities — portable SKILL.md (Barry, Patricia live here)
  rules-hive/      instructions — AGENTS.md guardrails (the Queen Bee's Charter)
  mcp-hive/        tools — MCP server configs / registry
  agents-hive/     actors — subagent & persona definitions
  plugins-hive/    composition — installable packs
  projects-hive/   containers — scaffolds that assemble the House per initiative
  workflows-hive/  orchestration — durable, resumable workflows (in design)
docs/              factory-thesis, interface-independence, prompts, sprints
.claude/           Claude Code config: commands, subagents, settings
.github/           OSS health, issue/PR templates, CI
ROADMAP.md         P0–P2 refactor plan; sprints draw from here
```

## Conventions (do not break)

- **Harness-agnostic.** Artifacts ride open standards (`SKILL.md`, `AGENTS.md`, MCP, A2A).
  Nothing is locked to one agent or model.
- **Two axes.** `<thing>/` is *what* an artifact is (portable source of truth);
  `adapters/<harness>/` is *where* it runs. Sub-harnesses nest one level deeper.
- **Naming.** kebab-case product directories (`claude-code`, `github-copilot`).
- **Docs voice.** Plain prose, sentence case, minimal bullets, two weights. Match the
  existing docs. No hype.

## Working rules

- **Conventional Commits** (`feat:`, `fix:`, `refactor:`, `docs:`, `chore:`, `ci:`). This
  drives automated versioning and the changelog.
- **Trunk-based.** Short-lived branches (`feat/…`, `refactor/…`), one issue each,
  squash-merge to `main`.
- **Every change is reviewable.** Run the checks in `.github/workflows/ci.yml` locally
  before shipping; a PR needs green CI and a Patricia charter-review pass.
- **Don't commit** `.DS_Store`, `node_modules/`, secrets, or `.env` (see `.gitignore`).

## The dev team (subagents)

- **Barry** (`.claude/agents/barry.md`) — orchestrator/chief of staff; decomposes a sprint
  issue, delegates, synthesizes.
- **Patricia** (`.claude/agents/patricia.md`) — governance reviewer; gates PRs against the
  Charter before merge.

## Lifecycle commands

`/sprint-plan` · `/work <issue>` · `/ship` · `/release` (see `.claude/commands/`).
