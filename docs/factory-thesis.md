# The Factory Thesis — ai-hive's mission

_Why werkrbee builds a harness-agnostic factory, not a pile of one-off products._

## Executive summary

There are two ways to build with AI agents.

- **Option 1 — build the thing.** Prompt an agent, iterate for hours or days, ship one
  product, then start over from zero. Every product is a fresh climb; nothing compounds.
- **Option 2 — build the factory.** Accept up front that no single product is the last
  one you'll build. First construct the reusable layer that *stamps out* products — so
  every next product ships faster and stronger. Measure twice, cut once; the measuring
  is the foundation layer.

werkrbee is a bet on Option 2. It is also a bet on **professionalism** — in Barry's
framing, the factory is how a master's 10x–100x edge over an amateur becomes
*structural* rather than personal (see "Barry's law" below).

**The House of Hives is the factory. `lineup` is the
first product we run through it to prove the factory works.** The strategic goal is not
"a great pickup-sports app" — it's a factory whose *marginal cost to build the next
agent product keeps falling*. In Allie K. Miller's framing, we invest in "the factory
behind the one singular task" rather than the task itself.

## The stack: primitives → factory → products

Every durable software company quietly runs an internal dev-tool layer — a "dark,
headless factory" — sitting on top of common **primitives** (login, payments, sharing,
newsletters) and beneath the **products** customers see. The factory is what makes the
second, third, and tenth product cheap.

ai-hive applies the same shape to **AI agents**:

| Layer | Generic SaaS factory | ai-hive |
|-------|----------------------|---------|
| **Primitives** | login, payments, sharing, email | open standards (`SKILL.md`, `AGENTS.md`, MCP) + connectors (Airtable, senders) + individual reusable skills/rules/agents |
| **The factory** | your internal dev-tool layer | the **House of Hives**: the two-axis pattern, `plugins-hive` (packs) and `projects-hive` (`init.py` scaffolds a fully-wired initiative in one command) |
| **Products** | the apps you sell | `lineup` today; each future product cheaper and stronger than the last |

The factory is the point. Barry (execution) and Patricia (governance) are the foremen;
the hives are the tooling; a scaffold is the assembly line that fans one command out
into skills + rules + tools + agents, wired and ready.

## Barry's law: amateurs build things, professionals build factories

Barry — the King Bee, master builder — holds that the gap between an amateur and a
professional isn't effort, and isn't even raw talent. It's **efficiency and quality,
together**. A professional produces better work *and* produces it far faster: 10x an
amateur, and a true master 100x. Both dimensions move at once — speed without quality is
just fast slop, quality without speed never ships. The professional refuses the
trade-off and delivers both.

That is exactly what a factory captures. The factory is where a master's efficiency and
quality are **encoded once and inherited by every product** — the hard-won judgment
about structure, the guardrails, the reusable patterns — so the whole team and every
future build perform at professional level *by default*, instead of rediscovering
competence from scratch each time. An amateur builds one thing, slowly, and starts over.
A professional builds the factory, and everything after arrives faster and better.

So the 10x–100x is not a claim about personal heroics. It's the **compounding output of
the factory**. Option 1 (build the thing) is capped at amateur slope no matter how hard
you prompt — you re-pay for competence every time. Option 2 (build the factory) is how
the professional's multiplier becomes *structural*: banked into portable tooling, not
trapped in one person's hands or one lucky session.

And because mastery is *both* halves, the factory must protect both. **Barry drives the
efficiency half; Patricia's charter keeps the quality half honest.** A factory that ships
fast but ungoverned isn't professional — it's just a faster amateur. The King builds to
professional tolerances; the Queen guarantees they hold.

## `lineup` is our Basecamp

Ruby on Rails wasn't designed in a vacuum — it was **extracted and hardened by building
a real product (Basecamp) on top of it.** A live application with real users is what
forces a framework to be honest: it surfaces the missing abstraction, the awkward seam,
the thing that only breaks in production.

`lineup` plays exactly that role for ai-hive. It is a real, live product (pickup-sports
RSVP, running on real data and real connectors) whose deeper job is to **stress-test the
factory**:

- It forced real tool integrations (Airtable for data, Inkbox for messaging) — proving
  the tools layer, not just describing it.
- It exercised governance for real (opt-in, approval gates, the bullpen's fairness
  rules) — proving the rules layer holds under a live use case.
- It proved artifacts **port across domains** — the same skills ran pickleball *and*
  Mahjong with no rewrite, which is the whole harness-/domain-agnostic promise in
  miniature.
- Every rough edge it hit (a connector that can't recolor a field, an iMessage channel
  that's consent-gated and pricey) became a *factory* lesson — a documented constraint,
  a channel-agnostic `notify` design, a cheaper path — not just a one-off patch.

The discipline: when `lineup` reveals a gap, we ask "what does this teach the factory?"
before we ask "how do I fix lineup?" That's what turns a product into a proving ground.

## Goal / objective

> **ai-hive's objective is to be a harness-agnostic *factory* for AI-agent products** —
> a portable, standard-backed set of reusable layers (skills, rules, tools, agents,
> workflows and state, plus packaging and scaffolding) that lets a small team with
> agency assemble and ship new agent products on any harness, each faster and stronger
> than the last.

The measure of success is not any single product. It's the **slope**: the marginal cost
of the next product trending toward zero, while quality trends up.

## Why harness-agnostic is the moat

A factory only compounds if it isn't bolted to one machine. Because every ai-hive
artifact rides open standards (`SKILL.md`, `AGENTS.md`, MCP), the same skill runs on
Claude Code, Codex, Cursor, Gemini CLI, Copilot, and the rest — so the factory **and
every product it makes** port across harnesses. No vendor can strand the investment.
That's the difference between fast prototypes that evaporate and fast prototypes that
**accrete into infrastructure**. Harness-agnosticism is what makes the compounding real.

## Defensive co-scaling: the controls grow with the agents

The more an agent does on its own, the stronger its boundaries have to be. As agents
take on more of an organization's work, autonomy without control stops being a speed
advantage and becomes a liability. werkrbee has built the agents. Now it builds their
control systems at the same pace, so that every gain in what an agent can do comes with
an equal gain in how well it is held. That is the defensive half of co-scaling, and the
governance and assurance loop is the band around it.

Every agent carries a **passport**: versioned metadata stating who it is, who owns it,
what it may do and what it may not, and which model, prompt and policy it runs. Four
controls hold an agent to its passport:

1. **Trust evaluation.** A suite of evals with a recorded baseline, re-run whenever the
   model, prompt or policy changes, and on a schedule. It says exactly when an agent is
   drifting and when it isn't.
2. **Full traceability.** A tamper-evident log of what the agent did and didn't do: every
   action it ran, was denied, paused for or had approved, and who approved it. Deleting
   or editing that log violates the Charter's core principles.
3. **Rollback.** A way back to an earlier version or an earlier state. Versions are what
   the passport pins, and state is the run's checkpoints and records. An effect outside
   the system can't be undone, only compensated, and the compensation is approved like
   any other action.
4. **A human review queue.** One place where a person sees and answers what needs them,
   across every run and agent: approvals, drift and escalations. Accountability sits
   with a human at the top.

Sub-agents and clones need their own boundary. Every harness now spawns them, and they
reuse the parent's cached context, which is a large share of the compute. That is a good
design for getting things done, but it opens leaks: a delegate can inherit context, data
or authority it was never meant to have. So a delegate's passport can only narrow its
parent's, context is passed to it explicitly, and cached context never crosses a trust
boundary such as another caller.

These controls belong in the factory for the same reason the rest does. Built once and
inherited by every agent the House produces, they make "governed" the default rather
than something each product has to remember. The work is tracked on the
`P2.1 — assurance loop` milestone (epic #122).

## What "the factory works" looks like

Concrete success criteria we hold ourselves to:

1. **One-command scaffolding.** A new initiative stands up via `projects-hive` and
   inherits Barry + Patricia, the Queen Bee's Charter, core tools, and the review fleet
   — no hand-wiring.
2. **Reuse across domains, no rewrite.** The same artifacts serve ≥2 unrelated domains
   (proven: pickleball and Mahjong).
3. **Falling marginal cost.** Each new product or skill takes measurably less time than
   the one before it.
4. **Real connectors, end to end.** Data and notifications work against live services,
   not mocks.
5. **Governance without reinvention.** Opt-in, privacy, and approval gates hold across
   products from one shared charter.
6. **Controls at the pace of autonomy.** Every agent the House ships carries a passport,
   a trust evaluation, an audit log, a way back and a human review queue, and no agent
   gains autonomy before its controls do.

When those hold, the one singular task is handled *and* the factory behind it is
stronger for the next one. That is the werkrbee superpower: a small team with agency,
wielding a professional's factory — compounding portable artifacts that deliver both
speed and quality — and out-iterating anyone still building one thing at a time by hand.

---

_Framing credit: the "build the factory, then the product" and "factory behind the one
singular task" concepts are from Allie K. Miller._
