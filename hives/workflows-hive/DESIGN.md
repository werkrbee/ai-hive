# workflows-hive design note

Status: accepted for P0. This note defines how workflows are exposed, what runs them,
and what gets persisted. The resumable spike that follows builds against it.

## The problem

An agent product needs work that outlives a single request: several steps, an approval
in the middle, a crash or a deploy somewhere along the way. Without a durable record of
where a run is, a restart loses the run, and a retry repeats side effects that already
happened. `docs/interface-independence.md` sets the bar: one workflow, started from any
interface, that pauses for approval, survives a restart, finishes safely, and reports
its result and its cost.

## Interface: MCP Tasks

Workflows are exposed through the official MCP Tasks extension
(`io.modelcontextprotocol/tasks`), on the 2026-07-28 spec that mcp-hive targets. Tasks
already describe the lifecycle a workflow needs, so we adopt them rather than invent a
protocol.

A workflow server offers one tool per workflow. When a client that declared the Tasks
extension calls it, the server returns a `CreateTaskResult` (`resultType: "task"`) with
a `taskId`, instead of blocking until the run ends. The client then polls `tasks/get`
until the task reaches a terminal status, and the final `result` is what the tool would
have returned synchronously. An approval step moves the task to `input_required` and
surfaces the request in `inputRequests`; the client answers through `tasks/update` and
the run continues. `tasks/cancel` asks the run to stop; cancellation is cooperative, so
a run may still finish.

The run ID is the task ID. The spec requires a task to be durably created before the
server responds, which lines up with our first rule below: the run record is written
before the `CreateTaskResult` goes out. A client that restarts resumes polling with the
same ID.

Run statuses use the Tasks values unchanged: `working`, `input_required`, `completed`,
`failed`, `cancelled`. The last three are terminal.

A client without the Tasks extension still works. The server must not return a task to
it, so the tool runs synchronously and returns the result directly, with no resume if
the connection drops. An approval is never skipped on this path: the server asks through
the core spec's multi round-trip pattern (an `input_required` result, answered when the
client retries the call), and if the client can't answer, the run fails before the step
runs.

## Engine: Temporal evaluated

[Temporal](https://docs.temporal.io/evaluate/understanding-temporal) is the reference
for durable execution, and the engine we measured against. A Temporal workflow runs to
completion "whether that takes a second or a year". The Temporal Service keeps an event
history of every run, and after a crash a worker replays the workflow code against that
history to rebuild its state. Side effects live in activities, which retry on their own.
Workflows receive signals and updates while they run, which covers approvals. It is open
source (the server and most SDKs are MIT, the Java SDK Apache-2.0), with SDKs for .NET,
Go, Java, PHP, Python, Ruby, Rust and TypeScript, and it runs self-hosted or as Temporal
Cloud.

What it costs us: a Temporal Service to run (or a Cloud account) before the first
workflow executes. Every other hive installs with Bash or Python and nothing else.
Workflow code must also be deterministic, because Temporal replays it, and that code is
tied to a Temporal SDK. The portable artifact this hive ships has to be data that any
engine can run, not Temporal code.

**Decision.** The portable contract is the plan and the run record defined below, and
the engine sits behind them. For P0, the reference engine is a small runner written
against the Python standard library that writes the run record to disk. That is enough
to prove checkpoint, restart, resume and cost, and it keeps the hive installable with no
service. Temporal is the production engine target: one generic Temporal workflow that
interprets a plan, with each step as an activity, approvals as updates, and the run
record kept current from the workflow. We adopt it when a product needs what the
reference engine doesn't do well: many concurrent runs across worker processes, long
timers, or retries we would otherwise rebuild by hand. Because both engines read the
same plan and write the same record, the switch doesn't change the workflows or the
interface.

## Plan shape

A plan is the portable definition of a workflow, kept at
`workflows/<name>/workflow.json`:

```json
{
  "name": "summarize-url",
  "version": 1,
  "description": "Fetch a page, then summarize it.",
  "inputs": {
    "type": "object",
    "properties": { "url": { "type": "string" } },
    "required": ["url"]
  },
  "steps": [
    { "id": "fetch", "worker": "fetch-page", "input": { "url": "${inputs.url}" } },
    { "id": "summarize", "worker": "summarize", "input": { "text": "${steps.fetch.output}" },
      "approval": true, "budget": { "usd": 0.05 } }
  ],
  "output": "${steps.summarize.output}"
}
```

Steps run in order. `inputs` is a JSON Schema, and it becomes the tool's `inputSchema`.
`${…}` references read the run's inputs and the outputs of earlier steps. `worker` names
the capability that does the step; the execution contract planned for agents-hive will
define what a worker is, so this note only names it. `approval: true` pauses before the step runs, and
`budget` caps what the step may spend. A plan that changes in a way an in-flight run
can't absorb bumps `version`, and a run always finishes on the version it started with.

## Run record (the checkpoint)

Each run persists one record, keyed by its run ID:

```json
{
  "runId": "run_01J9Z…",
  "workflow": "summarize-url",
  "workflowVersion": 1,
  "status": "input_required",
  "inputs": { "url": "https://example.com" },
  "next": "summarize",
  "steps": {
    "fetch": {
      "status": "completed",
      "attempt": 1,
      "idempotencyKey": "run_01J9Z…:fetch",
      "output": "…page text…",
      "cost": { "usd": 0.0, "tokens": 0 },
      "startedAt": "2026-10-08T14:02:11Z",
      "endedAt": "2026-10-08T14:02:12Z"
    }
  },
  "pending": { "step": "summarize", "kind": "approval" },
  "cost": { "usd": 0.0, "tokens": 0 },
  "result": null,
  "error": null,
  "createdAt": "2026-10-08T14:02:11Z",
  "updatedAt": "2026-10-08T14:02:12Z"
}
```

`next` is the step to run on resume. A step's `status` is `not_started`, `working`,
`completed` or `failed`. Its `idempotencyKey` is the run ID and step ID, and never
changes; `attempt` counts deliberate retries after a recorded failure, and resuming after
a crash doesn't increase it. `pending` is set only while the run waits on input, and it
becomes one entry in `inputRequests` on `tasks/get`, keyed by the step ID: an
elicitation asking whether to run the step. A denied approval fails the run, with the
denial as its error, and the step never runs. `cost` is the sum of the step
costs and is reported with the result. `result` or `error` is filled when the run
reaches a terminal status.

The engine keeps these rules:

1. Write the record before acknowledging the run, so the task exists before its ID
   leaves the server.
2. Write the record atomically (write a new file, then rename) after every step and
   every status change, and before the next step starts.
3. On resume, load the record, skip completed steps, and run from `next`.
4. Pass a step's `idempotencyKey` to anything with an external effect. A step that
   crashed mid-flight runs again with the same key, so the effect happens once.
5. Stop a step that would exceed its budget, and fail the run with the reason.

## Out of scope here

The executable spike (a two-step workflow that checkpoints, survives a restart, resumes
at step two, and reports result and cost) is the next piece of work. The worker
execution contract will belong to agents-hive. The Temporal engine is built when a product
calls for it, against this same contract.
