# hive_a2a: a reference A2A server

`hive_a2a` serves one execution contract of one House persona over
[A2A](https://a2a-protocol.org) v1.0. It is configured for Patricia's
`governance-review`: another agent sends a proposal and gets back a verdict
(`allow`, `allow-with-conditions` or `block`) in the contract's output shape. The same
server, configured for Barry's `orchestration`, runs a goal as an agent loop on the
workflows-hive engine ([Orchestration](#orchestration), below).

It is built on the official [A2A Python SDK](https://github.com/a2aproject/a2a-python)
and needs Python 3.13 and the packages in `requirements.txt`. This directory is the
one place in the repo that isn't standard-library Python.

## What it does

**Protocol.** The JSON-RPC binding, at the path of `server.public_url`. It supports
`SendMessage`, `GetTask`, `ListTasks` and `CancelTask`. Streaming and push notifications
aren't offered, and the card says so. The Agent Card is served at
`/.well-known/agent-card.json`. It is rendered by `scripts/agent_card.py` from
`cards/<persona>/card.json` and the contract, then given this endpoint's URL and an
OAuth2 client-credentials security scheme.

**Security.** Every request except the card needs a bearer token. The token must be a JWT
signed by a key from the configured JWKS, name the configured issuer and audience, be
unexpired, and come from a client on `auth.allowed_clients`. Only app tokens from the
client-credentials flow are accepted: a delegated (user) token, one with `scp` or an Entra
`idtyp` other than `app`, is refused. A missing or invalid token
gets HTTP 401; a valid token from a client not on the list gets 403. Each caller sees only
its own tasks: another caller's task id is "task not found". TLS is terminated in front of
the server (Azure Container Apps ingress, in #55), and `public_url` must be HTTPS except on
localhost.

**Contract.** A request carries the contract input as one JSON data part, for example
`{"proposal": "...", "context": "..."}`. Plain text parts are also accepted as the proposal.
The checks happen before a task is created:
- A media type the card doesn't declare gets `ContentTypeNotSupportedError` (-32005).
- Input that doesn't match the contract's `inputs` schema, or that is too large to fit the
  contract's per-call budget, gets `InvalidParamsError` (-32602) with each problem listed.

The contract's per-call budget is enforced in three ways:
- **tokens:** the input is estimated conservatively, and the output cap is set to what's left.
- **usd:** the output cap is lowered until the worst case fits.
- **seconds:** the model call is stopped and the task fails when the time runs out.

The model's reply must match the contract's `output` schema. If it doesn't, the task
fails. If it does, the verdict, trimmed to the contract's fields, becomes the task's
artifact as a JSON data part.

**Monthly ceiling.** `server.monthly_ceiling_usd` defaults to $25. Every model call
appends an entry to `server.ledger` in [knowledge-hive's ledger
format](../../../knowledge-hive/DESIGN.md#usage-ledger-ledgerjsonl). Before a review runs,
its worst-case cost is reserved against the ceiling. A review whose reservation would
take the month's spending plus reservations past the ceiling is refused. A refused review
becomes a task in the A2A `rejected` state, without calling the model. Its status message
says the ceiling would be passed, how much is spent or reserved, what the review needed,
and the date reviews resume (the first of next month, UTC, or sooner if a reservation is
released). It also carries a JSON part
`{"error": "monthly-ceiling-reached", "month", "spentUsd", "ceilingUsd", "neededUsd", "resumesOn"}`.

A call that reports its usage is recorded at its metered tokens. A call that may have
been billed but reported no usage is recorded at its whole reservation. That covers a
timeout, a cancel, a provider error after the request was sent, and a review cut off when
the process dies: calls in flight are kept in `<ledger>.pending`, and any left there are
recorded when the server next starts. So a month ends at or under the ceiling when the
server spends alone. The exception is a reply that runs past its token estimate, which the
server logs. The running total is kept in
the server process, so one instance must own the ledger: run a single replica. Another
process that spends against the same ceiling, such as Patricia's weekly evaluation, keeps
a ledger of its own, and each names the other in `server.shared_ledgers`: at every
reservation, a shared ledger's spending this month and its calls in flight are read
afresh and counted toward the ceiling. Each process reserves under its own lock, so both
can reserve at the same moment, each without seeing the other's, and the month can end
past the ceiling by what the other process reserved: one call's for the job.

The ledger's `usd` is computed from the prices in the config, so its `basis` is
`estimated`. Each entry names the model three ways: `provider` is its publisher,
`model.publisher` in lower case (`openai`, `deepseek`); `api` is the wire API the call
used; `model` is the deployment. Older entries have no `api`, and their `provider` is the
vendor the server was set up for (`openai` or `anthropic`), which groups with newer ones.
(Builds between PRs #84 and #90, 2026-10-15 to 2026-10-18, wrote the API into `provider`;
none was deployed.) The Azure budget alert in #55 is the billed backstop.

**Model.** A model-neutral interface. Config sets `model.api`, the wire API the server
speaks, the model, and `model.publisher`, who made it, for the ledger (on Foundry, its
catalog format; the Azure deploy sets it). A stub needs no publisher. The API is named
for its protocol, not a vendor, because one API serves models from many publishers:
- `stub` returns a fixed verdict without a network call. Tests and conformance runs use it.
- `messages` uses the Messages API, such as Claude on Microsoft Foundry's `/anthropic`
  endpoint.
- `chat-completions` uses Chat Completions, such as Foundry's `/openai/v1` endpoint, which
  serves OpenAI's models and most of the catalog's other publishers (DeepSeek, Meta,
  Mistral AI, xAI, Microsoft and more).

Which models can be deployed is decided by the Foundry model catalog, not by this
server: the Azure deploy refuses any that isn't generally available in its region
(`deploy/azure/README.md`). Both APIs are tested against a mock of their request and
response shapes. Live on Foundry, both are verified with the managed identity:
`chat-completions` against GPT-5.4 and DeepSeek-V3.2, `messages` against Claude Sonnet
5.5 (`deploy/azure/README.md`). Every call must report its token usage, or the server treats
it as failed, so the ledger and ceiling hold for any model. `chat-completions` streams
each response and asks for usage in its last chunk (`stream_options.include_usage`),
because some publishers' models on Foundry, DeepSeek among them, report usage only that
way.

Both clients also take tool calls, for an agent loop such as hosted Barry's
(`design/hosted-barry.md`). A review is one prompt and one reply, `complete()`, and is
sent exactly as before. A turn, `converse()`, sends the conversation so far and the tools
the model may call, and returns the reply's text and tool calls in one shape whichever API
is configured; a tool call's reply must report its usage too. Chat Completions has no
flag for a failed tool call, so its result says `error:` in its content. Tool calls are
tested against mocks of both APIs only, until the orchestration eval runs them live.

With `model.auth = "entra"`, the server authenticates to the model with the managed
identity it runs as. With `"api-key"`, it reads the key from the environment variable
named by `model.api_key_env`. The system prompt is built from the files in
`server.prompt_files`: the Charter, Patricia's skill and the charter-review agent.

**Cache scope.** The Charter keeps a cache inside its trust boundary, and the server holds
to that by never keeping a session. The system prompt is built once, from the shared
prompt files only, and each call sends its own input after it, with no conversation and
no earlier message, even one from the same caller in the same context. So a provider's
prompt cache can only ever hold that shared prefix, and nothing one caller sends reaches
another's call. A test checks it across two callers and a follow-up message.

**Durability.** Tasks are kept in SQLite at `server.database` and survive a restart. A
review that was running when the server stopped can't resume, so at startup it is marked
failed, with a message asking the caller to send it again.

## Orchestration

With `server.capability = "orchestration"` and an `[orchestration]` section, the server is
hosted Barry ([`design/hosted-barry.md`](../../design/hosted-barry.md)). `orchestrate.py`
replaces the reviewer; the card, auth, task store, ledger and model clients are the same.

**The loop.** A request carries the contract input, `{"goal": ...}` with an optional
`scope` and `constraints`, and its message metadata may carry the caller's `trigger` and
`facts`, such as `{"actor.role": "organizer"}`. Each task is an open engine run with the
task's ID, kept in `orchestration.state_dir`, under Barry's passport and the caller's
policy. Each model turn is a turn in the run record. Each tool call becomes a step whose
action the engine decides with the policy before it runs: an allowed call runs, a gated
one pauses the task in `input-required`, and a denied one fails it. When the model replies
without a tool call, the reply must match the contract's output, once sent back if it
doesn't, and becomes the task's artifact.

**Tools.** Delegation to the A2A agents in `orchestration.delegates`, each a passport
Barry's lists in its delegates, starting with Patricia, and the tools the caller's
registration maps (`registrations/<caller>/`, checked at startup and in CI). Only tools
the registration maps to an action are offered; its fact sources are called by the server
for lookups, never by the model. A lookup runs when the call is turned into a step,
before the policy decides it, so it runs even for a call that is then denied. There is no
shell, file system or fetch. The model's
arguments go into a step as written, never read as `${…}` references, and never as facts:
a fact comes from the caller's request or a lookup. Each MCP call carries its step's
idempotency key in the request's `_meta`, as `io.werkrbee/idempotency-key`, so a call run
again after a restart can be acted on once. Barry calls MCP servers and A2A agents with
tokens for his own identity, for each one's `token_scope`. An MCP server's endpoint comes
from its Server Card, and a card that requires other headers can't be used.

**Spend.** A run's whole budget, the contract's $5, is held against the ceiling when it
starts, and a run the ceiling can't hold is a `rejected` task, as a review is. Each turn
is metered into the ledger with the run's `runId` and charged to the hold, and what is
left is released when the run ends, is cancelled or expires. Before each turn, its worst
case, the estimated input and the most output it may write, is checked against what the
run has left of its usd, tokens and working seconds, and the run fails when it wouldn't
fit. Working seconds count the time turns and steps ran, not time spent waiting for a
person. Tool calls report no cost yet, so only model turns count.

**Lifecycle.** `SendMessage` returns as soon as the task is working; a caller polls
`GetTask`. A run that was working when the server stopped resumes from its record at
startup, repeating neither a completed turn nor a completed step. A turn cut off by the
restart is taken again, and the ledger records it at its whole worst case. What a run has
spent is what the ledger charged to its run ID, that turn included, so the run's budget
and the hold it gets after the restart both count it. A paused run
keeps its hold across a restart and expires after seven days, which fails the task; the
server checks every `orchestration.sweep_seconds` (an hour by default). `CancelTask`
cancels a paused task at once and a working one before its next turn or step.

**Approvals.** Before a gated step pauses its task, the executor, not the model, asks the
delegate named in `orchestration.reviewer` (Patricia) to review the action. The paused
task's status message then carries one JSON data part, the approval request:

```json
{"approval": {"id": "sha256:…", "step": "t1-1", "tool": "lineup/send_message",
  "action": "message.send", "rules": ["organizer.blast"],
  "present": {"message": "Game moved to 7pm.", "recipient count": 14, "estimated cost": "$0.11"},
  "review": {"verdict": "allow", "reason": "…"}, "expiresAt": "2026-11-06T14:02:12Z"}}
```

`id` digests the run, the step, the exact call, its action, the mandates that gate it and
the values shown. The review informs the person and doesn't replace them: a `block` still
goes to them, flagged in the status text, and a reviewer that can't be reached leaves the
request `unreviewed`, with why. The client that started the task answers it with a
message on the same task carrying one data part:

```json
{"approval": {"id": "sha256:…", "decision": "approve", "by": "usr_7f3a"}}
```

`by` is an opaque ID for the person who decided, never a name or an email. A denial
carries `"decision": "deny"` and a `reason`, and fails the run. An answer whose `id` isn't
the pending one is refused (`InvalidParamsError`, with the pending `id` in its details),
as is one from another caller ("task not found"). An approval runs the recorded call,
without asking the model again, once its facts and presented values are looked up again
and the policy has decided it again. If anything the `id` covers changed while the task
waited, the approval is void and the task pauses again with a new request. The engine
records `by`, the time and `a2a` on the step. The product is responsible for asking the
person through its own sign-in, and its client-credentials token is its attestation that
they did.

**Roles.** Starting or cancelling a task needs a token with the `Orchestration.Request` app
role, and answering an approval needs `Orchestration.Approve`
(`orchestration.request_roles` and `approve_roles`). Reading a task needs neither, only to
be the client that started it. A token without the role gets `InvalidRequestError`
(-32600), since A2A has no authorization error of its own. Leave `auth.required_roles`
empty, or list both, so a client holding only one can still use what it holds.

## Run it

```bash
cd hives/agents-hive/servers/a2a
python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp config.example.toml config.toml        # fill in auth, the model and public_url
.venv/bin/python -m hive_a2a --config config.toml --port 8080
```

Point a caller at `public_url` with a token from the client-credentials flow (for Entra, a
`POST` to `auth.token_url` with the caller's client id and secret or certificate, and
`scope` set to `auth.scope`):

```json
{"jsonrpc": "2.0", "id": 1, "method": "SendMessage", "params": {"message": {
  "messageId": "m-1", "role": "ROLE_USER",
  "parts": [{"data": {"proposal": "Force-push main to drop one commit.", "context": "Requested in chat."}}]}}}
```

Send it with the headers `A2A-Version: 1.0` and `Authorization: Bearer <token>`.

## Tests and conformance

```bash
.venv/bin/python -m unittest discover -s tests -v
```

The tests run offline. They use the stub model and tokens signed by a throwaway key, and
cover:
- the card
- auth refusals
- contract input and output checks
- the time budget
- the ceiling, including a ledger already on disk, the monthly reset and a run's hold
- per-caller isolation and cancel
- restarts
- the HTTP providers' request shapes
- orchestration (`tests/test_orchestrate.py`, against a scripted model and mock MCP and
  A2A servers): the loop, delegation, allowed, gated and denied calls, budget stops, the
  ceiling, resume, expiry and cancel; approvals: the request and its review, approve,
  deny, a stale approval, a changed fact, a mismatched `id`, each method's role and
  another caller's task

CI runs them.

`conformance/run.py` runs the [A2A TCK](https://github.com/a2aproject/a2a-tck) against the
server, with the stub model, behind a local proxy that adds a valid token, so auth stays
on. [`conformance/RESULTS.md`](conformance/RESULTS.md) records the latest run.

## Layout

```text
servers/a2a/
├── hive_a2a/
│   ├── app.py          # the card, routes, task store and startup
│   ├── auth.py         # OAuth2 bearer tokens and the client allowlist
│   ├── config.py       # the TOML config
│   ├── contract.py     # check values against a contract's schemas
│   ├── ledger.py       # the usage ledger, the monthly ceiling and runs' holds
│   ├── orchestrate.py  # hosted Barry: the loop on the engine, MCP and A2A tools
│   ├── providers.py    # stub, Messages and Chat Completions
│   └── review.py       # the executor: input, budget, ceiling, model, verdict
├── tests/              # test_server.py, test_orchestrate.py, test_eval.py
├── conformance/        # the TCK runner and the recorded run
├── config.example.toml
└── requirements.txt
```
