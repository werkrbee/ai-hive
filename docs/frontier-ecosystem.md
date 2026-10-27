# The frontier ecosystem: gaps in ai-hive

_What Microsoft's FY26 shareholder letter asks of an agent platform, and what's missing._

Satya Nadella's letter in Microsoft's 2026 annual report, "Building the Frontier
Ecosystem", describes how agent platforms are meant to work. People "macro delegate and
micro steer": they set a goal, and the system comes back for direction and judgment when
it needs them. The harness (context, memory and action space) is separate from the model,
so each job gets the right model, and customers "measure the cost of tokens against the
outcomes they produce". Every organization should "own its own continuous learning
system" and be able to "switch out a 'generalist' model without losing the 'company
veteran' expertise accumulated in their learning system"; the letter calls that "the
defining test of control and sovereignty of this era". Agents are managed "the same way
they manage people", with identity, governance, security and FinOps, and trust rests on
"verifiable standards for transparency".

Much of that is already how ai-hive is built. Its artifacts ride open standards (MCP,
A2A, `SKILL.md`, `AGENTS.md`) and keep a product's capabilities independent of any one
interface (`interface-independence.md`). The model is configuration, and the eval chose
Patricia's. workflows-hive runs long, durable, resumable work, and the assurance loop
(`assurance-loop.md`) gives each agent a passport, a trust evaluation, an audit log and a
human review queue. This note records what's missing, read against the code on
2026-10-27, and where each gap is tracked.

## The learning loop

ai-hive records an agent's history in run records, the audit log, the review queue,
`results.jsonl` and the ledger, but nothing learns from it. A human's denial of a wrong
verdict, a confirmed drift or a correction never becomes an eval case or a lesson, and
knowledge-hive's memory isn't tied to an agent's passport. A model swap is checked
against the suite the agent already has, and keeps nothing the agent built up. This is
the letter's central test, and ai-hive doesn't meet it yet.

Answered review items and drift become proposed eval cases, added through a reviewed
change (#146). An agent's lessons become plain-text memory pinned in its passport, and a
model swap must pass the eval with them (#147).

## Attacks on the agent

The letter's agentic security system uses agents to simulate attacks. ai-hive's trust
evaluation catches drift, but none of Patricia's 12 cases attacks her: none carries a
prompt injection, a forged approval or an instruction hidden in quoted tool output.
Hosted Barry will act on tools and context a caller supplies (#116), so each suite gains
adversarial cases, marked critical, before he deploys (#139).

## Steering a run

A run paused for approval can be approved or denied, nothing else. Delegating a goal
needs a person to be able to say what to do instead, and the run to carry on with it,
without that direction widening what the policy allows (#145).

## Cost per outcome

`interface-independence.md` says to track cost per accepted outcome alongside raw token
consumption, but nothing does: the ledger records spend and `results.jsonl` records
outcomes, and nothing joins them (#142).

## Following a run

A long-running run can't be followed while it runs. The run record and the audit log say
what happened afterwards, not where a run is or where its time and spend go. ai-hive
emits no traces; OpenTelemetry's GenAI conventions let any backend show a run, its steps
and its model calls without tying ai-hive to one vendor (#144).

## One view of every agent

Each agent has a passport, a ledger, eval results and review items, but nothing shows
them together: every agent, its owner, the version it runs, its spend against its
ceiling, whether its eval holds and what waits on a human (#143).

## Verifiable claims

An Agent Card links its passport by version and digest, and the audit log is hash-chained,
but nothing is signed. Inside werkrbee, where only werkrbee products call the agents,
that is enough. Opening the agents beyond werkrbee (P2's public A2A access) needs callers
to verify a passport and its eval results for themselves, so signing them is a
prerequisite of that item.

## Deferred

Three of the letter's themes wait, with no issue yet. Grounding agents in a business's
systems of record (the letter's context engine) belongs to mcp-hive's connectors and the
sub-agent boundary on cached context (#130) first. Running models on the device needs a
product that asks for it. Routing each job to the model with the best cost per outcome
needs that cost measured first (#142).

The learning loop is tracked on the `P2.2 — learning loop` milestone (epic #140), after
hosted Barry; the adversarial cases join the assurance loop (#122).

Source: the shareholder letter in Microsoft's
[2026 Annual Report](https://www.microsoft.com/investor/reports/ar26/index.html).
