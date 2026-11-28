# AI observability: design note

Status: accepted (#374). It decides where observing the House's agents lives, what it owns
and what it never owns, before any of it is built. It ends with what it changes in the
child issues of epic #369, worked in the order in `docs/sprints/p2.4.md`. Standards were
checked on 2026-11-27 against the sources at the end; #375 re-checks them and pins exact
versions.

## The problem

A person responsible for agents needs to answer six questions: which agents run, who owns
them, how they behave, what risks need attention, what they cost, and whether the outcomes
people accept get better. The House records most of the facts behind those answers, but
in separate files that nothing reads together, and only after the fact. A run record says
how a run ended, not where it is now. The ledger says what a call cost, not which outcome
it bought. An eval result says an agent drifted, not what changed before it did. Some
facts aren't recorded at all: a request the hosted server refuses for a bad token gets a
401 and leaves no trace.

Observability here means making those answers possible from evidence, and saying how good
the evidence is. It isn't a hosted monitoring product or a required dashboard, and a view
of the evidence proves nothing the evidence doesn't: not that an action was authorized,
safe or compliant, not a root cause, and not a return on investment.

## Four concerns, four kinds of evidence

The planning photos for this epic (photos 1 to 15, 19 to 27 and 38 to 47; private, cited
by number only) group what a person watches into four concerns. Within management they
separate health (is it up and finishing), performance (how fast and how much) and quality
(are its answers right). They name four kinds of evidence, which this note keeps as kinds,
not as further concerns: **activity** (events and records of what happened), **metrics**
(numbers aggregated over a window), **traces** (one unit of work followed across steps and
services) and **evaluations** (a judged result against cases or a baseline).

What the House records today, and what is missing:

| Concern | Recorded today | Missing |
|---|---|---|
| Management: health | Run and step status in run records; A2A task states; `run.failed` and `turn.failed` in the audit log | A view of what is running now; freshness, so an agent with no recent evidence reads unknown, not healthy |
| Management: performance | Step `startedAt` and `endedAt`; eval run `seconds` | Model and tool call latency; traces (#144); a baseline and window to compare against |
| Management: quality | Eval results in `results.jsonl` with drift findings; Patricia's verdicts; review queue answers | Quality drift tied to what changed before it (#380) |
| Governance | Passports (owner, version, pins, policy); the audit log's decisions; the review queue | One inventory (#143); lifecycle and change evidence per agent (#377) |
| Security | Denied and paused steps and `budget.refused` in the audit log; per-client allowances | Refused requests at the hosted server; warning classes and who a warning goes to (#379) |
| Business value | Ledger spend and tokens per run, step, client and task; results with outcomes | Cost per accepted outcome (#142); an agreed outcome, baseline and window (#381) |

The photos also show example indicators and trend comparisons (photos 17 and 18; photo 16
is unreadable). Their figures are illustrations, not House measurements or default
targets.

## Sources of truth

Each fact has one owner, and observing it never moves it.

| Owner | Keeps |
|---|---|
| agents-hive | Passports, identity, capabilities and execution contracts, the inventory (#143) and trust evaluation |
| workflows-hive | Run records and checkpoints, the review queue, and budget and action enforcement |
| knowledge-hive | The usage ledger, results and the audit log, with their provenance |
| rules-hive | Approval policy, authorization and what needs a person's approval |
| observability-hive (approved, not yet created) | Signal and mapping contracts, the privacy and export pipeline, and read-only projections |
| skills, plugins and projects hives | The operator's skill, opt-in composition and adoption in a product |

observability-hive holds no second agent registry, ledger, policy engine, evaluator or
deployment controller. Anything it builds from the owners' records is a projection: it can
be rebuilt from them, names the record each value came from, and is never what a check or
a gate reads. A projection that disagrees with its source is wrong, not the source.

Two consequences hold everywhere below. Losing telemetry, or sampling it, never weakens
an audit entry, a budget check or an approval, because none of those read telemetry. And
an observation is evidence for a person to act on: an alert or an eval proposal never
runs a remediation, answers an approval, adds an eval case or lifts a promotion hold.

## The decision: a new hive

Put observability in a new hive, `hives/observability-hive/`, as an opt-in layer. Accepting
this note, on 2026-11-27, is the maintainer's approval to create it.

Its work is cross-cutting by nature: it reads records owned by four hives and has to read
them under one contract, with one set of privacy rules, for every producer. Placed in any
one of those hives, the contract becomes that hive's, and the others either depend on it
for something unrelated to what it does, or copy it. A separate hive keeps the direction
of dependency clear: observability depends on the owners' published formats, and no owner
depends on observability to do its job.

**Considered: an existing hive.** knowledge-hive is the nearest fit, since it already owns
the ledger and the audit log. It loses on authority: a hive that keeps the canonical audit
evidence shouldn't also keep sampled, lossy, derived signals beside it, where one can be
mistaken for the other. workflows-hive would put a vendor-neutral export pipeline inside
the reference engine. A maintainer may still choose an existing hive; if so, the reason is
recorded here and the contracts below stay the same.

## What the hive contains

The layout:

```
hives/observability-hive/
  schema/              the signal, mapping and privacy contracts (#375), JSON Schema
  scripts/             stdlib: emit, sanitize, project and read; a no-op unless configured
  examples/            synthetic records, valid and invalid, for every test
  backends/<backend>/  optional: exporters and backend mappings, one folder per backend
  tests/
```

Backend mappings go in `backends/`, not `adapters/`. In every hive `adapters/` is the
harness axis, where an artifact runs, and the harness registry check holds it to exactly
the harnesses in `harnesses.json`. A backend is a different axis, so it gets its own
folder. (Corrected in #375; the note first said `adapters/<backend>/`.)

- **The core is standard-library Python**, like the rest of the repo outside the hosted
  server. With observability off, which is the default, nothing changes for any agent and
  no package is installed.
- **Producers call one emit seam** (`scripts/signals.py`), loaded by path the way the
  workflows-hive engine loads rules-hive and knowledge-hive scripts today. With no sink
  configured, it returns at once. A sink is configured by environment, a local file or an
  OTLP endpoint, and the OTLP exporter is imported only when that endpoint is set.
- **Backends depend on the core, never the reverse.** A backend mapping takes the portable
  signals to one backend's features and says which it can't show. Microsoft Foundry and
  Azure Monitor are optional examples (#382), not requirements, and core tests need no
  credentials or billable calls.
- **Every interface is headless first**: a command that prints text or JSON, readable
  without a dashboard. A rendered view, if any, reads the same output.

The wiring of the hive into the repo (its README, the architecture diagram, the root
README and AGENTS.md layout, the installers' hive list, CI) comes with its first
implementation, after this note is accepted, not in this note.

## Extension seams

Each existing issue stays the issue that implements its part. This note doesn't mark any
of them done, and observability-hive extends them through the shared contract rather than
doing their work again.

- **#144, traces.** Stays the implementation of runtime OpenTelemetry spans in the
  workflows-hive engine and the A2A server. The seam: its spans use #375's attribute names
  and privacy rules and go out through the emit seam, so a trace and a projection
  correlate on the same IDs.
- **#143, inventory.** Stays the one listing of agents. #377 reads that listing and adds
  change and lifecycle evidence beside it; it never lists agents itself. A product's own
  passports reach both only through #65, so product-file support is conditional on it.
- **#142, cost per accepted outcome.** Stays the join of the ledger with outcomes and its
  report. #381 links that report's rows to the runs and traces behind them; it doesn't
  compute cost per outcome again.
- **#346, #347 and draft #353, FinOps.** Own the cost taxonomy, forecasting, controls and
  reference reports, as a peer epic. Observability uses their unit and attribution
  vocabulary when it lands, agreed once in #375, and doesn't fork the schema, the
  calculator or the #350 report.
- **#146, eval case proposals.** Owns turning decisions and drift into proposed cases. An
  observation can link to that process; it never adds a case.
- **#310, orthogonality.** A proposal, not merged enforcement. Observability adds no
  approver and answers no approval, so it doesn't widen anyone's authority whatever #310
  decides.
- **#122 and #133, assurance and hosted Patricia.** Keep their ownership; nothing here
  reopens them or adds hosted work.

## Standards and versions

Two open standards carry correlation and export, and neither is a dependency of the core.

- **W3C Trace Context**, Level 1, a W3C Recommendation of 23 November 2021: the
  `traceparent` and `tracestate` headers. It forbids personal data in `tracestate`.
- **OpenTelemetry GenAI semantic conventions.** These moved out of the core semantic
  conventions into their own repository in 2026. Its first release, v0.1.0, published on
  2026-11-21, depends on core semantic conventions v1.45.0, and its conventions are in
  development, not stable: that release renamed spans and replaced the token usage metric.

The version rule: #375 pins one GenAI release and one core release by tag, records each
attribute's stability, and puts any attribute the House needs that the conventions don't
define under its own namespace, `io.werkrbee.`, the name the A2A server already uses in
MCP `_meta` (`io.werkrbee/idempotency-key`). Moving to a newer release is a reviewed change with a written mapping from
the old names to the new, and records written under the old version still read.

## Privacy and the trust boundary

The default is content-free metadata. A signal carries IDs, times, durations, counts,
units, outcomes and states. It carries no prompt, completion, reasoning, tool arguments or
results, message text, secret, credential, raw identity, or sensitive path or URL, and no
quality or security signal needs one to work. Capturing content is an exception a
product's policy turns on explicitly, scoped and with retention and access rules, not a
setting in this hive. Sanitizing happens before a signal is queued or leaves the process.

A trace ID is a correlation handle, never an identity or a permission. Incoming
`traceparent` headers are validated and may be dropped; unapproved baggage is stripped;
and no join, live or in an offline projection, crosses tenants. #375 writes these rules
down with fixtures that try to break each one.

## The first vertical slice

The smallest piece that proves the design. Its first two parts came with the spans (#144);
the local reader comes with #376:

1. **Two producers.** The workflows-hive engine, running hosted Barry's orchestration
   (a run, its turns and steps), and the A2A server's review executor, running Patricia's
   `governance-review` when Barry delegates to her or asks her to review a gated step.
   They are two producers joined by one A2A call, which is the hop correlation has to
   survive.
2. **One context across the hop.** The delegation carries `traceparent`; Patricia's server
   validates it and continues the trace, and her ledger entry and Barry's run record share
   the IDs a reader needs to join them.
3. **A local reader.** A stdlib command reads the signals written to a local file in the
   OTLP JSON encoding and prints the run as a tree: each turn, step, task and model call
   with its duration, its cost from the ledger, and what it couldn't see marked unknown.
   The same signals go to an OTLP endpoint only when one is configured.
4. **Offline proof.** The A2A server's tests already run with a stub model and no network.
   The slice runs there, on synthetic inputs, and the same tests run with observability off
   to show nothing changes.

## Plan

Four sprints, in order, with no dates or capacity promised. The maintainer owns each
decision; Patricia reviews each PR.

1. **Boundary and contract** (#370): this note (#374) and the signal and privacy contract
   (#375). Exit: the hive is approved, the schema validates its fixtures, and the slice is
   agreed.
2. **Instrumentation and views** (#371): bounded local and OTLP export (#376), ownership
   and lifecycle evidence (#377), and health, performance and quality with targets (#378),
   with #144 delivering the spans.
3. **Security, quality and value evidence** (#372): warning evidence and who it goes to
   (#379), drift correlated with change (#380), and outcomes tied to cost (#381), with #142
   and the FinOps contract.
4. **Backends, expertise and adoption** (#373): backend capability maps (#382), the
   operator's skill (#383) and conformance on synthetic scenarios (#384).

## Unresolved

- **Which GenAI convention release to pin**, settled in #375 against the releases out then.
- **Whether projections are written to disk or only computed when read.** Computing them
  is simpler and can't go stale; writing them is faster on a large estate. Settled in #377.
- **Hosted traces.** Whether hosted Patricia's and Barry's traces go anywhere is a hosted
  change, owned by deployment and #144 within the $25 ceiling, and not authorized here.

## Out of scope here

Hosted checks or deployments, live telemetry from real users, paid evaluations,
provisioning, new grants, consumer pin updates, scheduled jobs, and autonomous
notifications or remediation. Observability doesn't replace security incident response or
financial accounting.

## What it changes in the child issues

- **#375** pins the standards above, defines the signal, correlation and privacy contract
  under `schema/`, and agrees the joins with #142, #143, #144 and the FinOps work.
- **#376** builds the emit seam, the local file sink and the optional OTLP exporter, and
  the slice's reader.
- **#377 to #381** build projections, each reading its owner's records and naming them.
- **#382 to #384** stay as written, after the interfaces they map exist.
- The first of these to merge adds the hive's wiring to the repo.

## Sources

Checked 2026-11-27.

- W3C, [Trace Context](https://www.w3.org/TR/trace-context/), Recommendation, 23 November
  2021.
- OpenTelemetry, [GenAI semantic conventions](https://github.com/open-telemetry/semantic-conventions-genai),
  release v0.1.0 of 2026-11-21, and the [moved notice](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
  on the core conventions site.
- OpenTelemetry, [semantic conventions](https://github.com/open-telemetry/semantic-conventions),
  release v1.45.0 of 2026-11-02.
- The House's own formats: `hives/knowledge-hive/DESIGN.md` (results, ledger, audit log),
  `hives/workflows-hive/DESIGN.md` (run record, review queue),
  `hives/agents-hive/schema/passport.schema.json` and `docs/assurance-loop.md`.
