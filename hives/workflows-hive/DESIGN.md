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
the capability that does the step; agents-hive's execution contract for that capability
defines what the worker accepts, returns, may spend and may do. `approval: true` pauses
before the step runs, and `budget` caps what the step may spend. A plan that changes in a
way an in-flight run can't absorb bumps `version`, and a run always finishes on the
version it started with.

A step can also list the `actions` it takes, each a request in rules-hive's approval
policy shape: an `action` from the execution-contract permission vocabulary (or a
product policy's own namespaced actions), and the `scope`, `trigger` and `facts` its
mandates' constraints need. The `scope`, `trigger` and `facts` values can be `${…}`
references. The run is decided against one policy, the Charter's `policy.json` by default
or a product policy that `extends` it, and the run record keeps which one. It keeps the
policy's path, not its version, so a policy edited while a run is paused decides the
step when it is approved. Just before the step runs, each action is decided in
rules-hive's order. A prohibition fails the run, even after a human's approval, and the
step never runs. An open mandate lets it run. A closed mandate pauses the run for
approval, and `pending` names the mandates and the `present` items the approval request
must show. Anything else is denied, which fails the run. `approval: true` adds a pause
the policy doesn't require, but `approval: false` can't remove one it does.

```json
{ "id": "push", "worker": "git-push", "input": { "ref": "${inputs.ref}" },
  "actions": [{ "action": "vcs.push", "scope": { "remote": "origin" } }] }
```

## Run record (the checkpoint)

Each run persists one record, keyed by its run ID:

```json
{
  "runId": "run_01J9Z…",
  "workflow": "summarize-url",
  "workflowVersion": 1,
  "policy": "hives/rules-hive/rules/queen-charter/policy.json",
  "agent": { "passport": "barry", "version": 3, "sha256": "…" },
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
  "pending": { "id": "sha256:9c1e…", "kind": "approval", "step": "summarize",
               "rules": [], "present": [], "values": {}, "actions": [],
               "createdAt": "2026-10-08T14:02:12Z", "expiresAt": "2026-10-15T14:02:12Z" },
  "cost": { "usd": 0.0, "tokens": 0 },
  "result": null,
  "error": null,
  "audit": { "seq": 41, "hash": "sha256:4be1…" },
  "createdAt": "2026-10-08T14:02:11Z",
  "updatedAt": "2026-10-08T14:02:12Z"
}
```

`next` is the step to run on resume. A step's `status` is `not_started`, `working`,
`completed` or `failed`. Its `idempotencyKey` is the run ID and step ID, and never
changes; `attempt` counts deliberate retries after a recorded failure, and resuming after
a crash doesn't increase it. `pending` is set only while the run waits on input, and it
becomes one entry in `inputRequests` on `tasks/get`, keyed by the step ID: an elicitation
asking whether to run the step. Its `id` is the approval ID: the digest of the run ID,
the step, the exact call, its gated `actions`, the mandates that gate them (`rules`) and
the `values` of the items they must present. The same pause is an item in the review
queue, below, and it expires seven days after `createdAt`, at `expiresAt`. The answer is
kept on the step as `approval`: `decision` (`approved` or `denied`), `by`, `at`, `via`
(`cli`, `mcp` or `a2a`), the `id` it answered, and for a denial its `reason`. `by` is an
actor ID, which should be opaque. A step that needs approval runs only once its
`approval.decision` is `approved` and its `approval.id` is the approval ID the step would
pause on now, so resuming a paused run never runs it, and an approval of anything else is
void. A denied
approval fails the run, with the denial as its error, and the step never runs. A step
stopped by its budget fails the run, with the reason as its error; a step over its cost
cap keeps the cost it reported. `cost` is the sum of the step costs, including those, and
is reported with the result. `result` or `error` is filled when the run reaches a terminal
status. `agent` is the passport the run is under, if any, as its name, version and digest;
the run keeps it, and its `never` actions are prohibitions. `audit` is the `seq` and
`hash` of the last audit log entry written for the run.

The engine keeps these rules:

1. Write the record before acknowledging the run, so the task exists before its ID
   leaves the server.
2. Write the record atomically (write a new file, then rename) after every step and
   every status change, and before the next step starts.
3. On resume, load the record, skip completed steps, and run from `next`.
4. Pass a step's `idempotencyKey` to anything with an external effect. A step that
   crashed mid-flight runs again with the same key, so the effect happens once.
5. Stop a step that would exceed its budget, and fail the run with the reason. A step's
   budget may not exceed the per-call budget in its worker's execution contract.
6. Append every decision to the audit log before writing the record that follows it, and
   keep the last entry's `seq` and `hash` in the record. A run whose log can't be written
   doesn't go on.
7. Refuse an answer whose approval ID isn't what the run is waiting on, and an answer to
   a pause that has expired. Expiry fails the run.

A cancelled run ends in `cancelled`, with who cancelled it as its `error`. The request is
kept apart from the record until a process applies it, so the save of a step in flight
doesn't lose it: a paused run is cancelled at once, and a working one before its next step
or turn. The reference engine takes no lock on the record, so a cancel that lands at the
same moment as an approval in another process can still lose to it. It does lock the audit
log while it appends, so two processes never write the same entry.

## Open runs

An agent loop doesn't know its steps in advance, so the engine also keeps an open run.
It starts with no steps and grows: each tool call the loop makes is appended as a step
and decided, budgeted, checkpointed and resumed by the same rules as a planned step. The
record carries `open: true` and its own `plan`, the steps appended so far, since no
workflow file holds them. Steps run in the order they were appended.

The loop's model turns are kept in the record beside the steps, under `turns`, keyed by
turn ID:

```json
"turns": {
  "t1": {
    "status": "completed",
    "idempotencyKey": "run_01J9Z…:turn:t1",
    "output": "…the model's reply…",
    "cost": { "usd": 0.012, "tokens": 3100 },
    "startedAt": "2026-10-08T14:02:11Z",
    "endedAt": "2026-10-08T14:02:14Z"
  }
}
```

A turn is recorded as `working` before the model is called, and as `completed`, with its
output and cost, before the loop goes on. A resumed loop asks for the same turns again,
and the engine returns each completed one from the record without calling the model, so
a resumed run repeats neither a completed step nor a completed turn, and pays for
neither twice. A turn that was in flight when the process died is called again, with the
same idempotency key. Its cost counts in the run's `cost` with the steps'. An open run
ends when the loop finishes it with its result, which the engine allows only once every
step has completed, or fails it.

## The review queue

The review queue holds everything that waits on a person, across runs and agents, as one
JSON file per item in a queue directory (`queue/` beside the state directory), written
atomically like a run record:

```json
{
  "id": "sha256:9c1e…",
  "kind": "approval",
  "source": { "runId": "run_01J9Z…", "step": "summarize" },
  "agent": { "passport": "barry", "version": 3, "sha256": "…" },
  "present": { "actions": [ … ], "rules": ["organizer.blast"],
               "values": { "message": "Game moved to 7pm.", "recipient count": 14 } },
  "createdAt": "2026-10-08T14:02:12Z",
  "expiresAt": "2026-10-15T14:02:12Z",
  "status": "open",
  "answer": null
}
```

`kind` is `approval`, `escalation` or `drift`. An approval's `source` is its run and step;
an escalation's is its run and the question's `ask` ID, and it presents the `question`
and any `values`; drift's is the passport, its version and the `results.jsonl` entry that
recorded the eval, and it presents what the trust evaluation gives it. `status` is `open`,
`answered` or `expired`, and `answer` is the answer as the run recorded it, or a cancel.
Drift has no `expiresAt`.

The run record stays the source of truth for an approval or an escalation. The engine
writes the item after the record, and reading the queue brings each open item up to date
with its run: an item whose pause is past its expiry expires its run, and one its run
answered some other way, such as by a cancel, is closed. An escalation's answer is kept in
the record under `answers`, keyed by its `ask` ID, with `text`, `by`, `at`, `via` and the
item's `id`, and the run goes back to `working` for its loop. Answering drift writes a
`drift.answered` entry to the audit log; nothing else changes until the trust evaluation
reads it.

A step's worker and a model turn run with `WORKFLOWS_HIVE_RUN` set to the run's ID in
their environment, which processes they start inherit. The queue's command and MCP server
refuse to answer when it is set, and the command also refuses without an interactive
terminal. Neither is a lock on one machine; the audit log records each answer's `by` and
`via` as evidence.

## Out of scope here

The reference engine (`scripts/run.py`) implements rules 1 to 7, approvals, policy-decided
actions, passports, cancel, open runs, escalations and the review queue, with the two-step
`word-count`, `approved-word-count` and `budgeted-word-count` workflows. It is a command
and a Python module (`Engine`); open runs are offered only through the module. It applies
rules-hive's own checker (`check_policy.py`), so the engine and the policy's cases can't
disagree, and it reads only policies inside this repo. Its `approve` and `deny` commands
stand in for `tasks/update`, and `cancel` for `tasks/cancel`. It stops a step past its
`seconds` while it runs, in a child process whose start-up counts toward the cap, and
stops only that process, not any it started. It checks `usd` and `tokens` against what the
step reports when it finishes, so a worker that calls a model must keep itself within its
cap. The MCP Tasks server comes later. Worker execution contracts live in agents-hive. The
Temporal engine is built when a product calls for it, against this same contract.
