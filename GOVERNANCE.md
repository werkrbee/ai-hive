# Governance

ai-hive is a werkrbee open-source project. Governance mirrors the House of Hives itself:

- **Patricia (the Queen Bee) — the law.** The Queen Bee's Charter (`hives/rules-hive/`) defines
  always-on guardrails: harness-agnosticism, human-in-the-loop, safety, and the rules of the
  house. Every contribution is reviewed against it before merge.
- **Barry (the King Bee) — execution.** Orchestrates the work: planning, decomposition, and
  synthesis. Barry proposes and builds; he does not decide what is authorized — that is the
  Charter's and the maintainers' call.

## Decisions

- Maintainers (`.github/CODEOWNERS`) review and merge. Two conventions are non-negotiable:
  harness-agnostic design and the two-axis pattern.
- Roadmap scope is set in `ROADMAP.md` and worked in sprints (`docs/sprints/`). Larger
  direction changes are proposed as a doc PR first (see `docs/factory-thesis.md` style).
- Releases are automated from Conventional Commits; maintainers approve the version bump.

## Adding a hive

A category earns its own hive only when its artifact is **portable** (reusable across projects
and harnesses) and **standard-backed** (an open convention exists). Propose it as a doc PR
against `README.md`'s layered model before building.
