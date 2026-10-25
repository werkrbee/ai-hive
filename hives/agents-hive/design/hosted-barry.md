# Hosted Barry: design note

Status: accepted (#105). It decides how Barry is hosted over A2A before any code is
written, as workflows-hive's [`DESIGN.md`](../../workflows-hive/DESIGN.md) did for
workflows. It ends with the implementation issues that build it.

## The problem

Hosted Patricia reads a proposal and returns a verdict. She calls one model once, holds
`fs.read` only, and has nothing to undo. Barry's `orchestration` contract is different in
kind. He takes a goal, works through many model turns, and acts: the contract grants him
file writes, shell commands, fetches and delegation, and lists nine gated actions he may
take only with a human's approval. A run can last up to an hour and cost up to $5, and it
may wait days for an answer. So hosting Barry raises questions hosting Patricia didn't:
what he runs, where his actions execute, how a paused run reaches the caller and who may
answer it, and how his spending is held.

The ROADMAP sets the bar: actions the Charter gates pause the task for a human (A2A
`input-required`) instead of running. The workflows-hive engine now does that for a run
on one machine. It pauses a step for approval (#102), holds each step to its budget
(#103) and decides each step's actions with the approval policy (#104). This note puts
that engine behind an A2A endpoint.

## What hosted Barry runs

Barry runs an agent loop, and the loop runs on the workflows-hive engine. The model
decides what to do next; the engine decides whether it may, does it, and records it.

A fixed workflows-hive plan alone isn't enough, because Barry's job is to decompose a
goal nobody planned in advance. An agent loop alone isn't enough either: it has no
durable record, so a restart loses the run, and nothing outside the model decides what is
gated. So each tool call the model makes becomes a step appended to the run, with the
action it takes. The engine decides that action with the caller's approval policy before
the step runs, exactly as it does for a planned step. The model's turns are kept in the
run record beside the steps, so a run that dies resumes from its last checkpoint without
repeating a completed tool call or a paid model turn. A fixed plan is then just a run
whose steps are known up front, so the same server can run a product's workflows-hive
plans as well. That comes after the loop.

This needs two things the engine doesn't have yet: a run whose steps are appended as it
goes, and model turns in the run record. Both belong in workflows-hive, so the engine
stays the one implementation of the run contract.

## What Barry can act on

The first hosted Barry has no shell and no file system of his own. His tools are:

- **Delegation** (`agent.delegate`) to other A2A agents named in his config, starting with
  hosted Patricia.
- **The caller's tools**, from MCP servers the caller registers for him in mcp-hive's
  format, each tool mapped to an action in the caller's approval policy.

This follows from who calls him. The callers are werkrbee products such as lineup, and
the actions they need orchestrated are their own: sending messages, cancelling events,
charging a fee. Those already live behind the product's own tools, with the product's
data and credentials. Barry calling those tools through the engine gives every gated
product action a pause and an approval without handing Barry the product's secrets.

`net.fetch` is left out as well. The server runs with a managed identity, and any process
in its container can ask the identity endpoint for a token, so a fetch to a URL the model
chose could reach it. A fetch can come back later as a tool limited to an allowlist of
hosts.

`fs.read`, `fs.write` and `shell.exec` stay granted in the contract, which is a ceiling,
not a promise. They return when Barry works on code, and then they run in a sandbox,
never in the server's container. That sandbox has three requirements: it holds no
credentials and no managed identity, each run gets its own and loses it when the run ends,
and the server is the only thing that can reach it. Azure offers two candidates, and
neither is clearly right today:

- **Container Apps dynamic sessions** isolate each session with Hyper-V and are built for
  untrusted code. Custom-container session pools run on dedicated E16 instances, about
  $1.55 an hour in eastus2 plus $0.10 an hour for Dedicated plan management, well past
  the $25 ceiling. Code interpreter pools cost $0.03 per session hour, but their API
  for running code and moving files is offered only in preview versions
  (2025-10-02-preview), and werkrbee uses only generally available Azure APIs. Each
  execution is also capped at 220 seconds.
- **A Container Apps job on the Consumption plan**, one execution per run in its own
  environment with no identity, uses generally available APIs and costs cents a run,
  mostly inside the monthly free grant. But it isn't offered as a boundary for untrusted
  code the way sessions are, and a job has no ingress, so the server would hand it work
  through a queue.

The prices and limits are as of October 2026, from the
[Container Apps pricing page](https://azure.microsoft.com/pricing/details/container-apps/)
and the [dynamic sessions docs](https://learn.microsoft.com/azure/container-apps/sessions).

Choosing between them, or waiting for a generally available sessions API, is the
decision for the code-work phase. Gated code actions (commit, push, merge, release,
deleting refs) wouldn't run in the sandbox in either case. The sandbox produces a patch,
the server pauses for approval with the patch as what is presented, and the server applies
the approved patch with credentials the sandbox never sees.

## Actions, facts and trust

A tool call becomes a step whose `actions` the engine decides (#104). The mapping lives
in the caller's registration, beside its MCP servers: for each tool, the action it takes,
and where each of the action's scope values, trigger and facts comes from. A registration
is server config, set when the caller is onboarded, and never sent with a request. The
caller's policy must extend the Charter, as lineup's does, so every action the Charter
gates stays gated unless the policy opens it with an exception, which `check_policy.py`
already checks. The model can choose the arguments, but it can't vouch for a fact that
unlocks an action. If lineup's policy allows a message only when `recipient.notifyOptIn`
is true, a model that says the recipient opted in proves nothing. So:

- **Scope values** may come from the tool call's arguments, since they describe what is
  being done (the channel, the audience).
- **The trigger** comes from the A2A request that started the task, as a `trigger` field
  in the request message's metadata, set by the caller and never by the model. One
  trigger covers every step of its run, so a run started with `bullpen.slot-opened` may
  send any bullpen message its mandate allows for as long as it lives. A caller that wants
  narrower runs starts one per trigger.
- **Condition facts** come from a lookup the server makes itself, through a tool the
  caller marks as a fact source, never from the model's arguments. A lookup's own inputs
  come only from the arguments of the call that will run, or from the caller's request,
  so the recipients a fact is looked up for are the recipients the message goes to. Facts
  about the actor, such as `actor.role`, come from the caller's request, like the trigger.
- **A call with several subjects**, such as a message to 14 recipients, has each fact
  looked up for every subject, and the fact holds for the call only when it holds for all
  of them.

A fact the mapping can't supply is missing, and the policy already treats a missing fact
as never satisfying a mandate. An action the mapping doesn't cover is denied.

The same mapping names the source of each `present` item, under the same rules: the
message text from the tool's arguments, the recipient count from the lookup, and the
estimated cost from a tool the caller marks as a fact source. An item with no source is
shown as missing, so the human sees what they weren't told. The engine today shows
`present` as names only; hosted, an approval request carries their values.

## How a paused run reaches the caller

The engine's statuses map to A2A's task states one for one: `working`, `input_required`,
`completed`, `failed` and `cancelled` become `TASK_STATE_WORKING`,
`TASK_STATE_INPUT_REQUIRED`, `TASK_STATE_COMPLETED`, `TASK_STATE_FAILED` and
`TASK_STATE_CANCELED`. The run ID is the task ID.

A paused task's status message carries one JSON data part, the approval request:

```json
{"approval": {"id": "sha256:…", "step": "s7", "tool": "lineup/send_message",
  "action": "message.send", "rules": ["organizer.blast"],
  "present": {"message": "Game moved to 7pm.", "recipient count": 14, "estimated cost": "$0.11"},
  "review": {"verdict": "allow", "reason": "…"}}}
```

`id` is a digest of the run ID, the step, the exact tool call, its action, the mandates
that gate it and its presented values, so it can't answer the same call in another task,
and the person always approves under the rule that applies. The caller answers
by sending a message on the same task with one data part:

```json
{"approval": {"id": "sha256:…", "decision": "approve", "by": "organizer@lineup"}}
```

A denial carries `"decision": "deny"` and a `reason`. The server refuses an answer whose
`id` doesn't match what is pending, so an approval answers only the action that was
shown, and a changed action needs a new one. An approval answers the recorded call, not a
new turn: the server runs the call exactly as it was recorded, without asking the model
again. Before it runs, the server looks the facts up again, fills in `present` again and
decides the policy again, as the engine already does for an approved step. If anything
the digest covers changed while the task waited, the approval is void, and the task
pauses again with a new request. `approve` runs the step and continues the loop; `deny`
fails the run, as `run.py deny` does. The engine records `by` and the time on the step.

Before pausing, the executor, not the model, sends the gated action to Patricia for a
governance review and puts her verdict in the request as `review`. Her verdict informs the
human; it doesn't replace them, and a `block` still goes to the human, flagged. If
Patricia can't be reached, the task still pauses, with `review` marked unreviewed.

Hosted Barry offers no streaming or push notifications, like Patricia, so a caller polls
`GetTask`. A paused task expires after seven days: it fails, its reservation is released,
and its status message says so. The run's 3,600-second budget counts time spent working,
not time spent waiting for an answer. `CancelTask` cancels the run: a paused task is
cancelled at once, and a working one stops before its next step. Either way its
reservation is released. The engine has no cancel command yet; it gets one in the first
implementation issue.

## Who may answer

Only the client that started a task can see it or answer it, as with Patricia, where
another caller's task is "task not found". Starting a task and answering an approval need
different app roles: `Orchestration.Request` to send a goal, and
`Orchestration.Approve` to answer. The server checks roles with the same
`required_roles` mechanism Patricia uses, per method instead of per server.

A client-credentials token proves which product is calling, not which person. So the
approval is the product's attestation that a person approved, and `by` names who. The
product is responsible for asking that person, through its own sign-in, and for never
answering on its own. That matches how werkrbee's products already gate their actions,
and it is recorded on every approved step. Approvals carried by the person's own
delegated token, which Patricia's server refuses today, are the stronger option, left for
when a product needs them.

## Auth

The same setup as hosted Patricia, and only for werkrbee products. Barry gets his own
Entra API app, made by `entra.sh`, with the two app roles above, v2 tokens, and
assignment required. Each product's client app is granted the roles it needs, and the
server accepts only app tokens from clients on `auth.allowed_clients`. The card is the
only thing served without a token.

Barry calls Patricia and the products' MCP servers as a client in his own right, with
tokens for his own managed identity. He gets a separate identity from Patricia's, so each
holds only what it uses: Barry's can pull the image (AcrPull), call Foundry, get tokens
for Patricia's API and for the products' APIs that grant it, and nothing else. Patricia's
server adds Barry's identity to its `auth.allowed_clients` and grants it her required
role. No product secret is stored for him. A product whose MCP server can't accept an
Entra token can't register it for Barry yet.

## Spend

Each run is held to the `orchestration` contract's budget: $5, 2 million tokens and an
hour of working time. Every model turn is metered into Barry's own ledger, in
knowledge-hive's format, with the run ID. Before each turn, the server checks the worst
case of that turn against what the run has left, and stops the run when it wouldn't fit.
A tool call that reports a cost counts against the run as well.

Barry has his own monthly ceiling, as Patricia does, because a ledger belongs to one
server process. The split: Barry $15, Patricia $5. Patricia's reviews cost about a cent
each, so $5 covers hundreds of them. When a run starts, its whole $5 budget is reserved
against Barry's ceiling, and whatever it doesn't spend is released when it ends or
expires.

The ledger today refuses a reservation only once what is spent and reserved has already
reached the ceiling, so it can start a call that ends the month past it. It will instead
refuse a reservation that would take what is spent and reserved past the ceiling, for
Patricia as well as Barry. So at most three runs are open at once, and neither server's
month ends over its ceiling, apart from a reply that runs past its token estimate. The
worst case is then $15 for Barry, $5 for Patricia, and fixed costs of about $5 for the
registry alone, plus storage and logs: a little over $25 when everything is fully spent.
The Azure budget alert stays the billed backstop. A run refused for the ceiling becomes a
task in the A2A `rejected` state, with the same message and JSON part Patricia's refusals
carry.

Lowering Patricia's ceiling from its $25 default to $5 is a change to her deployment,
made in the deploy issue below.

## The model

The model is configuration, chosen by an eval, as for Patricia. The orchestration eval
runs a set of goals against stub A2A and MCP servers, through the server's own loop,
engine and policy. A model passes a goal when it reaches the goal, pauses for every gated
action instead of working around it, never claims a fact it wasn't given, and stays within
the budget, with output that meets the contract. The eval reports goals passed, cost and
time per goal, and its results go in `deploy/azure/eval/RESULTS.md`. Candidates come from
the Foundry catalog's generally available models that support tool calls; Claude Sonnet
5.5, Patricia's model, is already deployed and starts as the default.

## What is reused from `servers/a2a`

Barry is a second executor in the same `hive_a2a` package, served from the same image as
a second Container App in the same resource group and environment, with its own config,
data directory and identity. It shares the Foundry account, registry and budget with
Patricia.

| Module | Reused as | Changes |
|--------|-----------|---------|
| `auth.py` | tokens, the client allowlist and per-caller tasks | roles checked per method |
| `config.py` | the TOML config | an `orchestration` section: MCP registrations, delegates, expiry |
| `contract.py` | input and output checks against the contract | none |
| `ledger.py` | the ledger, reservations and the monthly ceiling | a reservation held across a run's turns, settled at its end; refused when it would pass the ceiling |
| `providers.py` | the Messages and Chat Completions clients | tool calls in both APIs, still reporting usage on every call |
| `app.py` | the card, routes and SQLite task store | the executor chosen by the contract; paused tasks survive restarts |
| `review.py` | Patricia's executor, unchanged | a new `orchestrate.py` beside it |

Unlike a review, a run that was working when the server stopped resumes from its run
record at startup rather than failing, because the engine makes that safe. A tool call
that was in flight runs again with the same idempotency key. MCP has no standard field for
one, so the key travels in the request's `_meta`, and a product's gated tools must read it
and act once for it.

## Out of scope here

A shell and file system for Barry, until the sandbox above is chosen. Public access
beyond werkrbee products, which is its own ROADMAP item. Streaming and push
notifications. Product policies and tool maps kept in the product's own repo, which
depends on #65.

## Implementation issues

To create, in this order:

1. **workflows-hive: let a run grow.** Make the engine importable as a library, let a run
   append steps as it goes, and keep model turns in the run record, so a resumed run
   repeats neither a completed step nor a paid turn. Add a cancel command.
2. **agents-hive: tool calls in the model clients.** Tool definitions and tool-call
   replies in the Messages and Chat Completions clients, with usage still required on
   every call, tested against mocks as today.
3. **agents-hive: map tools to actions.** The registration format for a caller's MCP
   servers, tool-to-action maps, fact sources and `present` values; checked like
   policies, with lineup's tools as the worked example.
4. **agents-hive: the orchestration executor.** `orchestrate.py`: the loop on the engine,
   delegation to Patricia, the caller's MCP tools, the per-run reservation and budget,
   the ledger refusing a reservation that would pass the ceiling, resume at startup,
   cancel, and expiry.
5. **agents-hive: approvals over A2A.** The approval request and answer parts, the `id`
   check, Patricia's review in the request, and `Orchestration.Approve` checked per
   method.
6. **agents-hive: the orchestration eval.** Goals, stub servers and scoring; run the
   candidates and record the choice.
7. **agents-hive: deploy hosted Barry.** `entra.sh` for Barry's API app and roles,
   `main.bicep` for his app and identity (AcrPull included), his ceiling, Patricia's
   lowered to $5, and Barry on Patricia's allowed clients with her role; deployed through
   `deploy.sh`'s gated steps.
