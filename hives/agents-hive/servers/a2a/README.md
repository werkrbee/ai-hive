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
end over the ceiling is one review's reservation, at most $0.50. The exception is a reply
that runs past its token estimate, which the server logs. The running total is kept in
the server process, so one instance must own the ledger: run a single replica.

The ledger's `usd` is computed from the prices in the config, so its `basis` is
`estimated`. The Azure budget alert in #55 is the billed backstop.

**Model.** A provider-neutral interface, with the provider and model set in config:
- `stub` returns a fixed verdict without a network call. Tests and conformance runs use it.
- `anthropic` uses the Messages API, such as Claude on Microsoft Foundry's `/anthropic`
  endpoint.
- `openai` uses Chat Completions, such as OpenAI models on Foundry's `/openai/v1` endpoint.

The `anthropic` and `openai` providers are tested against a mock of each API's request
and response shapes, not yet against live Foundry endpoints. That, and whether Foundry
accepts managed-identity tokens for each API, is verified in the Azure deploy (#55).

With `model.auth = "entra"`, the server authenticates to the model with the managed
identity it runs as. With `"api-key"`, it reads the key from the environment variable
named by `model.api_key_env`. The system prompt is built from the files in
`server.prompt_files`: the Charter, Patricia's skill and the charter-review agent.

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
│   ├── providers.py    # stub, anthropic and openai models
│   └── review.py       # the executor: input, budget, ceiling, model, verdict
├── tests/test_server.py
├── conformance/        # the TCK runner and the recorded run
├── config.example.toml
└── requirements.txt
```
