# observability-hive design note

Status: accepted with the hive (#375). It defines the signal contract every producer and
reader in this hive uses: what a signal is, how it joins the records its owners keep,
which standards it follows, and what it may never carry. The boundary it works inside,
and why this is a hive of its own, is in [`docs/observability.md`](../../docs/observability.md)
(accepted, #374). Standards were checked on 2026-11-27 against the model files of each
pinned release.

## A signal

A signal is one JSON object, one per line in a file of signals, in one of four kinds:

- an **event**, something that happened at one time: a run started, a step was decided, a
  request was refused;
- a **metric**, a number over a window: a duration, tokens, cost, coverage;
- a **span**, one unit of work with a start and an end, in a trace;
- an **evaluation**, a reference to a judged result that knowledge-hive keeps.

An evaluation signal points at a `results.jsonl` entry; it never holds the result, so
there is still one record of it. The four kinds are evidence types, not concerns: a span
can be evidence of health, performance and cost at once.

The shape is in [`schema/signal.schema.json`](schema/signal.schema.json), and the names a
signal may use are in [`schema/conventions.json`](schema/conventions.json).

```json
{"contract": "1.0", "kind": "span", "name": "io.werkrbee.step", "tenant": "tenant-a",
 "source": {"producer": "workflows-hive/engine", "version": "7c8e2cf"},
 "conventions": {"genai": "v0.1.0", "core": "v1.45.0"},
 "observedAt": "2026-11-27T14:00:10Z", "basis": "measured",
 "correlation": {"agent": "barry", "agentVersion": 6, "runId": "run_01J…", "step": "s1"},
 "trace": {"traceId": "4bf9…4736", "spanId": "b7ad…3331", "parentSpanId": "00f0…02b7", "sampled": true},
 "startAt": "2026-11-27T14:00:10Z", "endAt": "2026-11-27T14:00:38Z", "status": "ok",
 "attributes": {"gen_ai.tool.name": "patricia.review", "io.werkrbee.step.status": "completed"}}
```

Every signal has `contract`, `kind`, `name`, `tenant`, `source`, `conventions`,
`observedAt` and `basis`. A span adds `trace`, `startAt`, `endAt` and `status`; a metric
adds `value`, `unit` and `window`; an evaluation adds `outcome` and the `correlation`
that names its result. [`examples/slice.jsonl`](examples/slice.jsonl) is the first
vertical slice written as signals: hosted Barry's run, its turn and its step, the A2A
call to Patricia, her task and her model call, in one trace, with the metrics, events and
evaluation beside them.

## Correlation

`correlation` holds the opaque IDs that join a signal to its owners' records. Every one
is optional. An absent ID leaves a signal unattributed, and a reader keeps an
unattributed signal and counts it; it never guesses a join from times or names. Each ID
is the owner's, spelled as the owner spells it:

| Field | Joins | Owner |
|---|---|---|
| `agent`, `agentVersion` | A passport's `passport` and `version`, the inventory's key (#143) | agents-hive |
| `passportSha256` | The audit log's `agent.sha256` | agents-hive, knowledge-hive |
| `runId`, `step`, `turn` | The run record, and the ledger's `runId` and `step` (#142) | workflows-hive, knowledge-hive |
| `taskId`, `client` | The ledger's `taskId` and `client` | knowledge-hive |
| `call` | The audit log's `call` | knowledge-hive |
| `approval` | The run record's `pending.id` and the review queue's item | workflows-hive |
| `evaluation`, `outcome` | A `results.jsonl` `id` | knowledge-hive |
| `change`, `deployment` | An eval result's `commit` and `deployment` | knowledge-hive |

What isn't there is deliberate. A ledger entry has no ID of its own, so a signal joins it
through `runId` and `step`, or `taskId` and `client`, the keys the ledger already has,
and not through an ID this hive would have to invent. A person appears nowhere: the audit
log's `by` stays in the audit log. `client` is the calling app's ID, never a person's.

**The joins with the work that owns them.** #142 joins the ledger with outcomes; a signal
carries the same `runId`, `step`, `taskId` and `outcome` keys so that #381 can link a
cost-per-outcome row to its traces without computing it again. #143 lists agents; a
signal's `agent` and `agentVersion` are its key, and #377 adds lifecycle evidence beside
it. #144 emits spans; they are spans of this contract, with these names and this
correlation. The FinOps work (#346, #347, draft #353) owns the cost taxonomy: a cost
signal is in US dollars and tokens, the ledger's units, with the ledger's basis, and the
attribution dimensions FinOps names (product, team, tenant, agent, model, workflow,
environment) map to `tenant`, `correlation` and labels when its taxonomy lands. Nothing
here changes the ledger, the run record or the audit log.

## Time, units and what is known

`observedAt` is event time, by the producer's clock. `ingestedAt` is when a sink or a
reader received it, by its own. A signal observed more than five minutes after it was
ingested has a producer whose clock is ahead; the checker keeps it with a warning, and a
reader orders by `observedAt` within one producer only. Times are UTC, with `Z`.

A metric's `unit` is the [UCUM](https://ucum.org/) unit the conventions give for its name:
`s` for durations, `{token}`, `USD`, and `1` for a share. Its `window` is the interval it
covers.

`basis` says how a figure was arrived at: `measured` when the producer or provider
counted it (the ledger's `metered`), `estimated` when it was computed (the ledger's
`estimated`), and `unknown` when nobody knows. An unknown metric has a `value` of `null`,
never `0`, and a `null` value is always unknown. No evidence about an agent is unknown,
never healthy. The pinned GenAI token metrics differ: they record `0` when a response has
no usage. A House signal keeps `null`, and an exporter (#376, #382) that writes those
metrics must carry the unknown alongside, such as with `error.type`, rather than let it
read as zero tokens.

Three house metrics say how good the evidence is:

- `io.werkrbee.freshness`: the age of the newest signal for an agent.
- `io.werkrbee.coverage`: the share of the expected producers or records that reported in
  a window.
- `io.werkrbee.cost`: spend in a window, from the ledger.

A reader's `freshness` reads an agent with no signal as `unknown`, and one whose newest
signal is older than its threshold as `stale`.

**Sampling.** `sampling.rate` is the share of such signals kept; it is `null` when
unknown and absent when nothing was sampled out. Counts read from sampled spans are
estimates. Metrics, events and evaluations aren't sampled, and no audit entry, budget or
approval reads a signal, so sampling can't weaken them.

**Cardinality.** An ID has no bound on the values it takes, so it never labels a metric.
A metric's attributes are labels only (conventions.json's `label` class), and its
`correlation` names its agent and version and nothing else. Run, task, step, call and
trace IDs go on spans and events.

## Standards and versions

The pins are in `conventions.json`:

- **Trace context:** W3C Trace Context Level 1, a W3C Recommendation of 2021-11-23.
- **GenAI conventions:** OpenTelemetry's GenAI semantic conventions at v0.1.0, published
  2026-11-21. This is their first release in their own repository; its manifest marks the
  whole registry as development.
- **Core conventions:** OpenTelemetry's core semantic conventions at v1.45.0, which v0.1.0
  depends on.

Each attribute in `conventions.json` records where it comes from and how stable it is. On
these pins every GenAI, MCP and A2A attribute the House uses is `development`, and only
`error.type`, from the core conventions, is `stable`. Development means a release can
rename or remove an attribute, or change what a name counts, and v0.1.0 did all three. It
replaced `gen_ai.workflow.name` with `gen_ai.agent.name` and
`gen_ai.usage.cache_creation.input_tokens` with `gen_ai.usage.cache_write.input_tokens`,
renamed the provider `mistral_ai` to `mistral`, split `gen_ai.client.token.usage` into
input and output token metrics, and stopped reporting inference, agent, tool, embeddings
and retrieval operations on `gen_ai.client.operation.duration`, giving most of them a
metric of their own.

What the conventions don't name goes under the House's namespace, `io.werkrbee.`: the
run, step, turn and task spans, the house events, the cost, coverage and freshness
metrics, and attributes such as `io.werkrbee.capability`. It is the same reverse-DNS name
the A2A server already uses in MCP `_meta`, as `io.werkrbee/idempotency-key`. A house name
is replaced by a convention's when a pinned release defines one, through a migration.

**Moving the pins** is a reviewed change to `conventions.json`. It moves the pins, adds a
migration covering every breaking change the new release makes to a name the House uses,
and adds an older record to `examples/`. A record names the conventions it was written
under, and a reader reads an older record through its migration (`migrate` in the
checker). The migration renames attributes, attribute values and metrics, keeps what the
record was written under in `migratedFrom`, and never edits the record it read.

The migration from core v1.41.0 covers exactly the changes listed above. An old duration
on `gen_ai.client.operation.duration` moves to the metric v0.1.0 gives its operation:
inference to `gen_ai.client.inference.duration`, agent calls to
`gen_ai.client.invoke_agent.duration`, tool calls to `gen_ai.execute_tool.duration`. One
whose operation has no replacement the House uses (embeddings, retrieval), or that names
no operation, can't be read under the pins and is refused. So is a record whose
conventions nothing pins or migrates. Neither is read by guesswork. Any other name a
v1.41.0 record used that the House doesn't list is refused like any unknown name.

**The contract's own version** is `MAJOR.MINOR`. A minor release only adds optional
fields; a reader reads any minor of its major, and keeps a field from a newer minor with
a warning, unread. A major release is a new contract with a migration.

## The trust boundary

A trace ID is a correlation handle. It never identifies a caller, grants anything or
decides anything. Authentication and authorization stay where they are, in the A2A
server's tokens and the approval policy.

- **Incoming `traceparent`** is parsed strictly (`parse_traceparent`). A malformed
  header, an all-zero ID, version `ff`, or extra fields on version `00` is dropped, and
  the receiver starts a new trace; nothing is repaired. A later version is read by its
  first four fields, as the spec says. A receiver may also start a new trace on any call
  from outside its trust boundary and link the incoming one, so a caller can't attach its
  work to another tenant's trace.
- **`tracestate`** is passed on unread, and the House writes nothing personal into it, as
  the spec requires.
- **Baggage** is dropped by default (`baggage`). A product can allow keys by name, and a
  kept value is checked like an attribute.
- **Tenants.** Every signal has an opaque `tenant`, and every read takes one. A read
  given signals of another tenant refuses them (`CrossTenant`) instead of filtering
  quietly. The same run ID or trace ID in two tenants is two runs. This holds offline as
  well: a projection is built for one tenant at a time.

## Privacy

The default is content-free metadata: IDs, times, durations, counts, units, outcomes and
states. A signal carries none of the following:

- what was said: prompts, completions, system instructions, chain-of-thought, tool
  arguments or results, retrieval or memory queries, or an evaluation's explanation;
- message text;
- secrets or credentials;
- raw identities;
- sensitive paths or URLs.

No quality or security signal in this hive needs any of them.

- **An allowlist, not a blocklist.** An attribute is kept only if `conventions.json`
  names it. A name it doesn't know is dropped, so a new field in a producer stays out
  until someone reviews it in.
- **Content attributes** are listed, in the `content` class, so that they can be refused
  by name. A signal carries one only under a **capture exception**: a `capture` object
  naming the product policy that allows it, the exact fields, and a retention of 1 to 400
  days. The exception belongs to a product's own policy and its storage's access rules;
  this hive ships none and turns none on. A captured value is structured, as the pinned
  conventions require of message attributes on spans and events, so it can't be checked
  as a string; that is why capturing is a policy decision, not a default. Every other
  attribute is a scalar. Content never goes on a metric.
- **Sanitizing happens first** (`sanitize`), before a signal is queued, written or
  exported. It drops by name and returns the dropped names, never their values. Any
  string value that reads as one of these is dropped, and is refused by the checker:
  - an email address;
  - a bearer token, a JSON Web Token or an API key;
  - a URL with credentials or a query;
  - a home directory path;
  - anything longer than 256 characters.
- **Exceptions.** An error is recorded as `error.type`, its class name (`error_type`),
  never its message, which can hold a path, a token or what the user said.
- **Retention and access.** Signals are derived evidence, not records of authority. A
  product keeps them only as long as it needs them for observing, and they can be rebuilt
  from their owners' records. Anyone who can read the owners' records may read the
  signals derived from them, and no one else. A captured field is kept no longer than its
  exception's retention.

## Threats

| Threat | What stops it |
|---|---|
| A caller forges `traceparent` to join another tenant's trace | Strict parsing, a new trace at the boundary, and no join across tenants |
| Trace IDs read as identity or permission | They grant nothing; auth stays with tokens and the policy |
| Baggage carries a user ID or a secret in | Dropped by default; allowed keys are checked |
| A producer adds a prompt or a payload to an attribute | The allowlist drops unknown names; content needs a capture exception |
| An exception message leaks a path or a token | Only the class is kept |
| A run ID used as a metric label explodes cardinality | Metrics take labels only, and no correlation but the agent |
| Two tenants collide on a run ID | Every read is scoped to one tenant and refuses others |
| A skewed clock reorders events | Warned; ordering is within one producer |
| A telemetry outage hides a failing agent | No evidence reads unknown, never healthy |
| A dashboard is mistaken for proof | Signals are derived; gates read their owners' records, never signals |
| A convention rename or change of meaning silently breaks a view | Pinned versions; a migration for every breaking change to a name the House uses; a changed meaning with no replacement, and unpinned records, refused |

## What the checker holds you to

`scripts/check_signals.py` checks a signal against the schema and against these rules:

- its name is one `conventions.json` gives for its kind, and a metric's unit is the one
  given for it;
- every attribute is in `conventions.json`, with its type;
- a metric's attributes are labels, and its correlation names only its agent and its
  version;
- only a span carries sampling, and no number is NaN or infinite;
- content needs a capture exception that names it;
- no string reads as sensitive;
- a span ends no earlier than it starts and isn't its own parent;
- a metric's value is `null` exactly when its basis is `unknown`;
- the conventions are pinned or migrate, and a name that changed meaning with no
  replacement is refused.

A newer minor's fields and a skewed clock are warnings. With no arguments it checks
`examples/`: every signal in a `.jsonl` file must pass, and every case in
`examples/invalid.json` must fail with the error it names. The tests in
[`tests/`](tests) cover missing IDs, old records, clock skew, tenant collision, malicious
attributes and baggage, and sensitive exception messages.

## Emitting spans

`scripts/signals.py` is the emit seam (#144). The engine and the A2A server ask it for a
`Tracer` once, and get none unless an OTLP endpoint is configured. A `Tracer` sanitizes a
span's attributes, builds it as a signal of this contract, checks it, and hands it to a
sink. A span that fails its check is dropped and counted, and a sink that fails is ignored.
So telemetry never changes what a run, a task or a model call does, and it never raises
into one.

**IDs.** A run's trace ID is a hash of the tenant and the run's ID, and each span's ID a
hash of the tenant and what it is a span of: the run, a step's idempotency key, a turn's
key. So the same run gets the same trace in any process that resumes it. A step that calls
another agent sends `traceparent` naming its own span, and the callee, which parses it
strictly, puts its task beneath it. A call with no valid `traceparent` starts a trace of
its own. The hash includes the tenant, so the same run ID in two tenants is two traces.

**On the wire.** The OTLP sink posts the OTLP JSON encoding to an https endpoint, or http
on localhost, with headers from the environment for a credential kept outside the repo.
Correlation IDs become `io.werkrbee.<field>` span attributes and the tenant a resource
attribute. Its queue holds 1,024 spans; a full queue or a failed send drops and counts.
Retries, sampling, a file sink, volume budgets and export health come with #376.

## Out of scope here

Bounded export (#376), projections and views (#377 to #381), and backend mappings (#382)
come later. Each builds on this contract and moves no source of truth.
Nothing here is hosted, live or billable.
