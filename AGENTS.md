# AGENTS.md — ai-hive

Context for any coding agent working in this repository. This file follows the open
[AGENTS.md](https://agents.md/) standard and is the repo's canonical context. Harness
adapters, such as `CLAUDE.md` for Claude Code, import it and add only what is specific to
their harness.

## What this is

`ai-hive` is **werkrbee's House of Hives** — a harness-agnostic *factory* for building AI
agent products. It is not an app; it is the reusable layers apps are assembled from. The
guiding thesis: build the factory, then the product (`docs/factory-thesis.md`), and keep a
product's capabilities independent of any one interface (`docs/interface-independence.md`).

**Vision and mission.** Every person and every organization on the planet is the world's
best user of AI, and an expert at it; ai-hive is the framework that gets them there. It is
obsessed with how to use AI across every model, harness and part of the craft (memory,
knowledge graphs, evaluation, cost, governance), and it explains why what works works, so
its users become experts. Advice about AI names its evidence and when it was checked.

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
  workflows-hive/  orchestration — durable, resumable workflows and a reference engine
  knowledge-hive/  state — STATE.md, memory, results and usage ledgers
docs/              factory-thesis, interface-independence, product-adoption, prompts, sprints
.claude/           Claude Code adapter: commands, subagents, settings (see CLAUDE.md)
.github/           OSS health, issue/PR templates, CI
ROADMAP.md         P0–P2 refactor plan; sprints draw from here
harnesses.json     the harness registry: every harness, its category, tier and install paths
```

## Conventions (do not break)

- **Harness-agnostic.** Artifacts ride open standards (`SKILL.md`, `AGENTS.md`, MCP, A2A).
  Nothing is locked to one agent or model.
- **Two axes.** `<thing>/` is *what* an artifact is (portable source of truth);
  `adapters/<harness>/` is *where* it runs. Sub-harnesses nest one level deeper.
- **Naming.** kebab-case product directories (`claude-code`, `github-copilot`).
- **One harness registry.** A harness, its adapter folder and its install paths are
  written down only in `harnesses.json`; installers read it through `scripts/harnesses.py`.
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

## The dev team

- **Barry** (`hives/skills-hive/skills/barry/`) — orchestrator/chief of staff; decomposes a
  sprint issue, delegates, synthesizes.
- **Patricia** (`hives/skills-hive/skills/patricia/`) — governance reviewer; gates PRs
  against the Charter (`hives/rules-hive/rules/queen-charter/AGENTS.md`) before merge.

## Lifecycle

Work moves through five steps: plan a sprint's issues from `ROADMAP.md` and
`docs/sprints/`, pick the next step, work one issue on its own branch, ship it as a PR with
a Patricia review, and release by merging release-please's release PR. `CONTRIBUTING.md`
has the details.
