# ai-hive roadmap

Scoped, sprint-sized work. Sprints pull from here top-down. Priorities reflect the
refactor assessment: ai-hive is strong at design-time but the apps built on it (lineup)
proved it needs a **runtime layer**, and the standards it rides (MCP, A2A, SKILL.md,
AGENTS.md) have advanced. Rationale: `docs/interface-independence.md`, `docs/factory-thesis.md`.

## Sprint 0 — project setup (this sprint)

Convert to a monorepo and stand up the open-source + Claude Code lifecycle. See
`docs/sprints/sprint-0.md`. Done once the repo has governance, CI, Claude Code commands,
and the roadmap below is tracked as issues.

## P0 — the runtime layer (unblocks every product)

- **`workflows-hive` (new).** Durable, resumable multi-step recipes. Align with MCP's
  `Tasks` primitive (2026-07-28) and a Temporal-style engine. The missing layer lineup hit.
- **Execution-contract schema (agents-hive).** Define a worker by required capability,
  inputs, expected output, **budget, and permissions** — so workers are replaceable.
- **MCP spec bump (mcp-hive + docs).** Move references to the **2026-07-28** spec: stateless
  core, Extensions, Tasks, MCP Apps, auth hardening. Adopt **Server Cards / `.well-known`**
  discovery.

## P1 — interop, governance, state

- **A2A Agent Cards (agents-hive).** Give Barry & Patricia Agent2Agent cards so other agents
  can discover and call them (Linux Foundation A2A v1.x).
- **Structured approval/mandate schema (rules-hive).** Turn the Charter's prose into a
  per-action, per-scope policy (auto vs. human-gated), AP2-mandate-shaped. Encodes carve-outs
  like lineup's bullpen auto-send as data, not prose.
- **`knowledge-hive` (new).** Standardize the operational-state pattern apps hand-rolled
  (STATUS.md / PROJECT_STATE.md / memory) — the "persistent state · results · usage ledger".

## P2 — ecosystem & payments

- **skills-hive marketplace metadata + evals.** Align to the governed SKILL.md standard
  (agentskills.io); ship evals beside each skill; add discovery/publish metadata.
- **Payments (AP2 + x402).** Shared authorization (AP2 mandates) + settlement (x402) so apps
  like lineup's fee-splits don't reinvent it per app.
- **Connector capability matrix (mcp-hive).** Capture real connector limits learned in apps
  (Airtable option colors, send-less Twilio MCP, Inkbox consent gate) so the next app doesn't
  rediscover them.

## Guardrails

Adopt the two standards the artifacts already ride (**MCP latest + A2A**) first; treat
payments as design-ahead-of-need. Let `workflows-hive` be the forcing function that proves
the runtime layer before spreading thin. A working product on durable execution teaches more
than eight hives at spec parity.
