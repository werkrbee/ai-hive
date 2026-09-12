# PROMPT — Add the "interface independence" architecture direction to werkrbee/ai-hive

_Paste into an agent working in the `werkrbee/ai-hive` repo (Claude Code, or a Cowork
session with the repo cloned). Produces `docs/interface-independence.md` and a README link._

---

You are working in the `werkrbee/ai-hive` repository — werkrbee's umbrella index for the
House of Hives. The repo already contains `docs/factory-thesis.md` ("build the factory,
then the product") and a layered model in the README (context · instructions ·
capabilities · tools · actors · orchestration, plus composition/delivery). Read both
first so your addition matches their voice: plain, unhurried, prose over bullets,
sentence case, two weights, no hype.

**Goal:** Add a new architecture-direction document that makes the case, for *any* product
built on the hives, for decoupling its capabilities from any single interface. A UI (React,
say) is one way in; the enduring product is the *service* that understands goals,
coordinates work, protects budgets, and delivers results. Frame it with the
Blockbuster→Netflix question: *what value remains when the delivery channel changes?* The
answer that survives is **trusted execution under human direction** — reachable
interchangeably via dashboard, chat, voice, or another agent. Keep the principle general
and use werkrbee/lineup only as a clearly-labeled worked example, not the subject.

**Create** `docs/interface-independence.md` containing, in order:

1. A short thesis: capabilities independent of interface; the service is the durable
   product; trusted execution under human direction is the value that survives a channel
   change.
2. The target architecture as a single mermaid `flowchart TB` block:
   `React dashboard --> Werk API`; `Chat, voice, other agents --> MCP interface --> Werk API`;
   `Werk API --> Core (Goals · permissions · approvals · budgets) --> Durable workflow engine
   --> Replaceable agents and harnesses --> Tools and external services`; and
   `Durable workflow engine <--> Persistent state · results · usage ledger`.
3. "Five choices that make this practical," as five short subsections:
   1. Turn each feature into a callable capability (API + MCP; authorization stays in the
      service). Cite the MCP specification.
   2. Give execution a durable lifecycle (persist plan, checkpoint steps, survive
      restart/approval waits; evaluate Temporal; idempotency for external actions). Cite
      Temporal docs.
   3. Make agents replaceable workers (assignments defined by capability, inputs, output,
      budget, permissions; behavior behind adapters). ai-hive supplies portable
      instructions and personas; werkrbee supplies the execution contract and operational
      state.
   4. Enforce human control and token economics outside the model (approvals bind to a
      specific action/scope; reserve budgets before, reconcile after; cost per accepted
      outcome). Tie to Patricia / the Queen Bee's Charter.
   5. Build value that compounds across interfaces (context, proven workflows, eval
      results, decision history, integrations — exportable).
4. A "Where werkrbee is today" note: React calls a local service that owns approvals and
   token accounting; it still only generates plans and lacks durable, autonomous
   multi-step execution.
5. A "Recommended next milestone": one real workflow initiated through dashboard **or**
   MCP, that pauses for approval, survives a service restart, finishes safely, and reports
   result and cost.

**Integration requirements:**
- Add a short "Interface independence" note to the README near the Mission / layered
  model, linking to `docs/interface-independence.md`.
- Cross-link with `docs/factory-thesis.md`: the factory *produces* capabilities;
  interface-independence is *how they're delivered and endure*. Place it against
  `mcp-hive` (tools), `skills-hive`/Barry (execution), `rules-hive`/Patricia (governance).
- End the new doc with a Sources section: MCP spec and Temporal docs.

**Constraints:** match existing docs' tone/format; frame as architecture direction and a
bet, not shipped functionality (the "today" note is the honest current state); keep
werkrbee's spelling of "werk"; documentation only — no code or installer changes.

**Done when:** `docs/interface-independence.md` exists with all five sections and a
rendering mermaid; README links to it; both docs cross-reference; sources cited. Show a
diff summary and stop for review before committing.
