# ai-hive roadmap

Scoped, sprint-sized work. Sprints pull from here top-down. Priorities reflect the
refactor assessment: ai-hive is strong at design-time but the apps built on it (lineup)
proved it needs a **runtime layer**, and the standards it rides (MCP, A2A, SKILL.md,
AGENTS.md) have advanced. Rationale: `docs/interface-independence.md`, `docs/factory-thesis.md`.

## Sprint 0 — project setup (done)

Convert to a monorepo and stand up the open-source + Claude Code lifecycle. See
`docs/sprints/sprint-0.md`. Done once the repo has governance, CI, Claude Code commands,
and the roadmap below is tracked as issues.

## P0 — the runtime layer (done)

Tracked as issues #7–#12, worked in the order set in `docs/sprints/p0.md`. All closed.

- **`workflows-hive` (done).** Durable, resumable multi-step recipes. Align with MCP's
  `Tasks` primitive (2026-07-28) and a Temporal-style engine. The missing layer lineup hit.
  The plan format and a reference engine shipped; the MCP Tasks server is still to come.
- **Execution-contract schema (agents-hive).** Define a worker by required capability,
  inputs, expected output, **budget, and permissions** — so workers are replaceable.
- **MCP spec bump (mcp-hive + docs).** Move references to the **2026-07-28** spec: stateless
  core, Extensions, Tasks, MCP Apps, auth hardening. Adopt **Server Cards / `.well-known`**
  discovery.

## P1 — interop, governance, state

Tracked on the `P1 — interop, governance, state` milestone. Everything is done except
hosted Patricia's first deploy and model eval (#55).

- **A2A Agent Cards (agents-hive) (done).** Give Barry & Patricia Agent2Agent cards so
  other agents can discover and call them (Linux Foundation A2A v1.x).
- **Structured approval/mandate schema (rules-hive) (done).** Turn the Charter's prose
  into a per-action, per-scope policy (auto vs. human-gated), AP2-mandate-shaped. Encodes
  carve-outs like lineup's bullpen auto-send as data, not prose.
- **`knowledge-hive` (done).** Standardize the operational-state pattern apps hand-rolled
  (STATUS.md / PROJECT_STATE.md / memory) — the "persistent state · results · usage ledger".
- **Hosted Patricia over A2A (agents-hive) (in progress).** A reference A2A v1.x server
  that exposes the `governance-review` contract as the skill on Patricia's Agent Card
  (builds on the Agent Cards item). The model is configuration, not code. werkrbee
  deploys an instance on Azure behind OAuth2 client credentials, for werkrbee products
  only; products built on the House (lineup, singularity) call it for governance checks.
  The server (#54) and the Azure deploy definition shipped; the first deploy and the eval
  that picks Patricia's model are still to run (#55).
- **Product adoption guide (docs) (done).** How a product adopts ai-hive as its agent
  development framework: pin the monorepo, Barry executes, Patricia governs.
- **Reconcile the repo with `workflows-hive` and `knowledge-hive` (docs) (done).** Once
  knowledge-hive lands, make every page and image describe both hives accurately.

## P2 — ecosystem & payments

- **Hosted Barry over A2A.** After the approval policy: actions the Charter gates pause the
  task for a human (A2A `input-required`) instead of running.
- **Public A2A access.** An option to open the hosted agents beyond werkrbee products.
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
