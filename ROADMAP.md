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
- **Execution-contract schema (agents-hive) (done).** Define a worker by required
  capability, inputs, expected output, **budget, and permissions** — so workers are
  replaceable.
- **MCP spec bump (mcp-hive + docs) (done).** Move references to the **2026-07-28** spec:
  stateless core, Extensions, Tasks, MCP Apps, auth hardening. Adopt **Server Cards /
  `.well-known`** discovery.

## P1 — interop, governance, state

Tracked on the `P1 — interop, governance, state` milestone. Everything is done and
released. Most of it shipped in 0.4.0, including hosted Patricia's server and deploy
definition. The fixes from deploying it and the move to Claude came in 0.5.0 to 0.6.1.
They include the deploy work's two follow-ups: a narrower Foundry role for its identity
(#69) and a check of built-in role ids before `deploy.sh`'s what-if (#79).

- **A2A Agent Cards (agents-hive) (done).** Give Barry & Patricia Agent2Agent cards so
  other agents can discover and call them (Linux Foundation A2A v1.x).
- **Structured approval/mandate schema (rules-hive) (done).** Turn the Charter's prose
  into a per-action, per-scope policy (auto vs. human-gated), AP2-mandate-shaped. Encodes
  carve-outs like lineup's bullpen auto-send as data, not prose.
- **`knowledge-hive` (done).** Standardize the operational-state pattern apps hand-rolled
  (STATUS.md / PROJECT_STATE.md / memory) — the "persistent state · results · usage ledger".
- **Hosted Patricia over A2A (agents-hive) (done).** A reference A2A v1.x server
  that exposes the `governance-review` contract as the skill on Patricia's Agent Card
  (builds on the Agent Cards item). The model is configuration, not code. werkrbee
  deploys an instance on Azure behind OAuth2 client credentials, for werkrbee products
  only; products built on the House (lineup, singularity) call it for governance checks.
  The server (#54) and the Azure deploy definition shipped (#55). It is deployed on
  Claude Sonnet 5.5, which the eval chose over GPT-5.4 and DeepSeek-V3.2 on 2026-10-21,
  meeting all 12 cases. An authenticated review through the public endpoint was verified
  on Claude on 2026-10-23.
- **Product adoption guide (docs) (done).** How a product adopts ai-hive as its agent
  development framework: pin the monorepo, Barry executes, Patricia governs.
- **Reconcile the repo with `workflows-hive` and `knowledge-hive` (docs) (done).** Once
  knowledge-hive lands, make every page and image describe both hives accurately.

## P1.1 — product adoption

Tracked on the `P1.1 — product adoption` milestone. Gaps a product hits when it adopts
ai-hive, found while writing the adoption guide and reconciling the repo with
`workflows-hive` and `knowledge-hive`. One of its three items is done, in 0.6.0.

- **Check a product's own files (rules-hive, agents-hive).** Let the approval-policy and
  contract checkers check a product's files, with `extends` pointing into its pinned copy
  of ai-hive. (#65)
- **Install every hive from a pack (plugins-hive).** Let packs install `workflows-hive` and
  `knowledge-hive`, starting with what installing each one means. (#66)
- **Call any generally available model (agents-hive) (done).** Let the A2A server call
  any model the Foundry catalog lists as generally available in its region, not only
  those served through the Anthropic or OpenAI APIs, with the catalog as the source of
  truth. (#77)

## P1.2 — product practice

Tracked on the `P1.2 — product practice` milestone. How a product is built on the House,
not just assembled from it. Both items have an open pull request.

- **Discover customer outcomes before planning (skills-hive).** A portable
  `discover-outcomes` skill that turns an ambiguous product request into an outcome brief
  with evidence, unknowns and acceptance criteria before Barry plans the work. Clear fixes
  and explicit edits skip it. The PR adds it to `werkrbee-core`. (#52, PR #53)
- **Native platform design consistency (rules-hive).** A versioned standard, held by
  Patricia, for keeping a product's desktop, mobile and web clients consistent, with a
  platform parity matrix, human-approved exceptions and drift remediation through Barry.
  Compliance is a release requirement: Patricia blocks a release recommendation while
  drift has no approved exception. Automated release enforcement is outside it.
  (#38, PR #39)

## P2 — ecosystem & payments

- **Hosted Barry over A2A.** Builds on the approval policy (done in P1): actions the
  Charter gates pause the task for a human (A2A `input-required`) instead of running.
  Tracked on the `P2 — hosted Barry` milestone (epic #106). Barry's runtime is done: the
  workflows-hive engine pauses a run for approval (#102), holds each step to its budget
  (#103) and decides each step's actions with the approval policy (#104). The design note
  is accepted (#105, `hives/agents-hive/design/hosted-barry.md`), and its seven
  implementation issues follow it in order (#114–#120). The first is done: the engine is
  a library, and a run can grow and keep model turns (#114). Barry's deploy (#120) waits
  for the assurance loop's passport, audit log and human review queue (P2.1), so he ships
  with his controls.
- **Public A2A access.** An option to open the hosted agents beyond werkrbee products.
- **skills-hive marketplace metadata + evals.** Align to the governed SKILL.md standard
  (agentskills.io); ship evals beside each skill; add discovery/publish metadata.
- **Payments (AP2 + x402).** Shared authorization (AP2 mandates) + settlement (x402) so apps
  like lineup's fee-splits don't reinvent it per app.
- **Connector capability matrix (mcp-hive).** Capture real connector limits learned in apps
  (Airtable option colors, send-less Twilio MCP, Inkbox consent gate) so the next app doesn't
  rediscover them.

## P2.1 — assurance loop

Tracked on the `P2.1 — assurance loop` milestone (epic #122), worked in the order set in
`docs/sprints/p2.1.md`. Defensive co-scaling: the agents' control systems are built at the
same pace as the agents (`docs/factory-thesis.md`). Every agent will carry a passport,
held by four controls. The passport and the audit log are done.

- **Vision and roadmap (docs).** Put defensive co-scaling into the factory thesis, the
  README, this roadmap and a sprint file. (#123)
- **Design note (docs).** Decide the passport, the four controls and the sub-agent
  boundary before code, building on what exists: execution contracts, Agent Cards, the
  approval policy, run records, the usage ledger and Patricia's eval. Accepted in
  `docs/assurance-loop.md`. (#124)
- **Agent passport (agents-hive) (done).** Versioned metadata per agent: identity, owner,
  what it may and may not do, its eval baseline and the model, prompt and policy versions
  it runs. (#125)
- **Tamper-evident audit log (knowledge-hive) (done).** An append-only, hash-chained
  record of what every agent did and didn't do, with a verifier. Deleting or editing it
  violates the Charter. (#126)
- **Trust evaluation and drift (agents-hive).** Each agent's eval re-runs on any change
  and on a schedule; a result below its baseline is drift, flagged to a human. (#127)
- **Rollback.** Back to an earlier passport or checkpoint; an external effect is
  compensated, as the approval policy decides. (#128)
- **Human review queue (workflows-hive).** One queue for approvals, drift and escalations
  across every run and agent. (#129)
- **Sub-agent and clone boundaries (rules-hive).** A delegate's passport only narrows its
  parent's; context is passed explicitly; cached context never crosses a trust boundary.
  (#130)

Hosted Barry's deploy (#120) waits for the passport, the audit log and the review queue.

## Guardrails

Adopt the two standards the artifacts already ride (**MCP latest + A2A**) first; treat
payments as design-ahead-of-need. Let `workflows-hive` be the forcing function that proves
the runtime layer before spreading thin. A working product on durable execution teaches more
than eight hives at spec parity. No agent gains autonomy before its controls do: hosted
Barry ships with his passport, audit log and review queue, and hosted Patricia comes under
the same controls as they land.
