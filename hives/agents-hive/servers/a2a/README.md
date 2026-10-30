# hive_a2a: a reference A2A server

`hive_a2a` serves one execution contract of one House persona over
[A2A](https://a2a-protocol.org) v1.0. It is configured for Patricia's
`governance-review`: another agent sends a proposal and gets back a verdict
(`allow`, `allow-with-conditions` or `block`) in the contract's output shape.

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
its worst-case cost is reserved against the ceiling. Once the month's spending plus
reservations reaches the ceiling, new reviews are refused. A refused review becomes a
task in the A2A `rejected` state, without calling the model. Its status message says the
ceiling was reached, how much was spent, and the date reviews resume (the first of next
month, UTC). It also carries a JSON part
`{"error": "monthly-ceiling-reached", "month", "spentUsd", "ceilingUsd", "resumesOn"}`.

A call that reports its usage is recorded at its metered tokens. A call that may have
been billed but reported no usage is recorded at its whole reservation. That covers a
timeout, a cancel, a provider error after the request was sent, and a review cut off when
the process dies: calls in flight are kept in `<ledger>.pending`, and any left there are
recorded when the server next starts. So the most a month can
end over the ceiling is one review's reservation, at most $0.50, when the server spends
alone. The exception is a reply that runs past its token estimate, which the server logs. The running total is kept in
the server process, so one instance must own the ledger: run a single replica. Another
process that spends against the same ceiling, such as Patricia's weekly evaluation, keeps
a ledger of its own, and each names the other in `server.shared_ledgers`: at every
reservation, a shared ledger's spending this month and its calls in flight are read
afresh and counted toward the ceiling. Each process reserves under its own lock, so both
can reserve from just below the ceiling at the same moment, and the bound becomes one
reservation from each: one review's for the server and one call's for the job.

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
- the ceiling, including a ledger already on disk and the monthly reset
- per-caller isolation and cancel
- restarts
- the HTTP providers' request shapes

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
│   ├── ledger.py       # the usage ledger and the monthly ceiling
│   ├── providers.py    # stub, Messages and Chat Completions
│   └── review.py       # the executor: input, budget, ceiling, model, verdict
├── tests/test_server.py
├── conformance/        # the TCK runner and the recorded run
├── config.example.toml
└── requirements.txt
```
