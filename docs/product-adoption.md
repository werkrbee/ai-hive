# Adopting ai-hive in a product

This is for a product team that wants ai-hive as its agent development framework: the
skills, rules, tools and agents its agents run with, the contracts its workers meet, and
Patricia's governance checks. The short version is three things. Pin the monorepo,
let Barry execute, and let Patricia govern.

[lineup](https://github.com/werkrbee/lineup) and singularity (a private werkrbee repo)
are the two products built on the House so far. They're cited below as examples of what
works and what to change. Nothing here asks either repo to change; each adopts what it
needs on its own schedule.

## Pin the monorepo

Every hive lives in this repository under `hives/`. The standalone repos the hives came
from (`werkrbee/skills-hive`, `rules-hive`, `mcp-hive`, `agents-hive`, `plugins-hive`,
`projects-hive`) are archived and get no more changes, so a product that pins them is
pinned to history. Pin `werkrbee/ai-hive` at a release tag instead:

```bash
git submodule add https://github.com/werkrbee/ai-hive.git ai-hive
git -C ai-hive checkout <tag>         # a release tag, such as v0.4.0; never a branch
git add .gitmodules ai-hive
```

One pin covers every hive, and a release tag is a version whose changes are listed in
[`CHANGELOG.md`](../CHANGELOG.md). Pick the newest tag that has what you use, and don't
track `main`. Most of this guide needs the release after v0.3.0 (0.4.0, open as a release
pull request when this was written): the Agent Cards, the approval policy and its lineup
example, knowledge-hive, and the A2A server and its Azure deployment are all newer than
v0.3.0, which has the hives, their installers and the execution contracts.

Upgrade on purpose. Read the changelog between your tag and the new one, move the pin in
its own pull request, record the old and new tags, re-run your installs, and say what you
adopted. Singularity's dependency process, in its `docs/HIVE-ALIGNMENT.md`, is a good
model: no silent updates, and a product issue for each upstream change it takes
up. Singularity also shows the step to avoid now. It pins the six archived hive repos as
submodules, so moving to one `ai-hive` submodule is its first upgrade.

## Install what the product uses

The installers run from the pinned copy and write into your product, so nothing is
fetched from `main` at install time. The usual start is the `werkrbee-core` pack, which
fans out to each hive's installer:

```bash
python3 ai-hive/hives/plugins-hive/scripts/install.py werkrbee-core --dry-run --dir .
python3 ai-hive/hives/plugins-hive/scripts/install.py werkrbee-core --dir .
```

That installs Barry and Patricia as skills, globally for your user, and installs the
Queen Bee's Charter, the core MCP servers and the review agents (including Patricia's
`charter-review`) into the product. Each hive's own installer takes a subset when the
pack is more than you want; their READMEs list the options. A brand-new product can start
from projects-hive's `werkrbee-initiative` scaffold, which creates the project and installs
the pack in one step.

Re-run the installs after each upgrade, and commit what they write. The installed Charter
is a copy, so a product sees changes to it only when it upgrades.

## Keep the product's own artifacts beside the House's

A product's own skills, rules and tools follow the same two axes as the hives: the
portable artifact in a directory named for what it is, and harness specifics under
`adapters/<harness>/`. lineup does this with six `lineup-*` skills under `skills/` and
its house rules in `rules/lineup-etiquette/AGENTS.md`, which apply under the Charter.

A product's rules can also be data. rules-hive's approval policy turns the Charter's
gated actions into mandates, and a product policy `extends` the Charter's: it declares its
own namespaced actions and says which of them an agent may take alone and which need a
human. [`examples/lineup-etiquette/policy.json`](../hives/rules-hive/examples/lineup-etiquette/policy.json)
is lineup's house rules written that way, including the bullpen carve-out that used to
live only in prose.

A product's operational state goes in a `knowledge/` directory in knowledge-hive's
format: a current `STATE.md`, one memory file per durable fact, and append-only results
and usage ledgers. Copy `hives/knowledge-hive/templates/knowledge/` to start, and check it
with `hives/knowledge-hive/scripts/check_knowledge.py`.
[`examples/lineup/knowledge/`](../hives/knowledge-hive/examples/lineup/knowledge) is
lineup's `STATUS.md`, `PROJECT_STATE.md` and memory recast in that format.

Two limits today. The policy and contract checkers in this repo check only files in this
repo, and `extends` takes a path inside it, so a product can't yet check its own policy or
contracts from its own repo. And policies and contracts are declarations: no harness or
engine enforces them at runtime yet. Until both change, keep the product's policy as
review material and enforce the gates in the product's own code.

## Barry executes, Patricia governs

The two personas split the work the same way in every product. Barry, the King Bee,
takes a goal, breaks it into steps, delegates them and puts the results together. His
`orchestration` contract lets him read, write, run commands, fetch and delegate. Commits,
pushes, merges, releases, deletes, deploys, sent messages and spending need approval, and
anything the contract doesn't list is denied. Patricia, the Queen Bee, reviews a proposed
action against the Charter and returns a verdict. She reviews only and never does the
work.

In a product that means Barry, or whatever agent is doing the work, asks Patricia before
any action the Charter or the product's policy gates, and acts on her verdict:

- `allow`: go ahead.
- `allow-with-conditions`: go ahead only once each condition is met.
- `block`: stop and take it to the human, with her stated violation and safer alternative.

Her verdict never replaces the human's approval for a gated action. It decides whether
the request is worth putting to the human, and what it must show them.

Patricia can run in three places, and they return the same verdict shape. In a harness
session she's the `patricia` skill or the `charter-review` agent the pack installs. Inside
a product's running service, which has no harness, she's the hosted A2A agent described
below.

## Contracts and Agent Cards

An execution contract defines a worker by capability: the inputs it takes, the output it
returns, a budget for one call and the permissions it holds. The contracts are in
[`hives/agents-hive/contracts/`](../hives/agents-hive/contracts). Refer to a worker by its
capability (`governance-review`, `orchestration`) rather than by persona, so the worker
behind it can change. A workflows-hive step names a capability as its `worker` in the
same way.

`governance-review` is the one a product calls most. Its input is a `proposal` (the
action, plan or diff) and an optional `context` (who proposes it, why, and the blast
radius). Its output is a `verdict` and a `reason`, with `conditions` for an
`allow-with-conditions` and a `violation` and `alternative` for a `block`. Its budget is
$0.50, 200,000 tokens and 600 seconds a call. Code that calls it should check the output
against the contract's `output` schema, the same as the hosted server does.

An Agent Card is how another agent finds a persona over [A2A](https://a2a-protocol.org):
its skills, which come from its contracts, plus where it's served and how to
authenticate. [`cards/`](../hives/agents-hive/cards) holds Barry's and Patricia's cards
without an endpoint. A served card fills that in, so a product reads the live card rather
than the file in this repo.

## Calling hosted Patricia

werkrbee runs Patricia's `governance-review` as an A2A agent on Azure, for werkrbee
products only. [`hives/agents-hive/deploy/azure/`](../hives/agents-hive/deploy/azure)
describes the deployment. The first deploy hasn't been run yet, so the endpoint and API
app id come from the maintainer once it has.

To get access, the maintainer adds the product as a caller. They run `entra.sh` with every
calling product's name, the new one and the existing ones, since the `allowedClients` it
prints lists only the names it was given. It creates an Entra ID app registration for the
new product and grants it the `Review.Request` role on Patricia's API. The maintainer
then puts the printed `allowedClients` in `main.bicepparam` and redeploys with
`deploy.sh`, which is what adds the product to the server's allowlist. The product's owner then adds a credential to that app, a certificate or federated credential
for preference, and keeps it in the product's secret store. Nothing about the credential
goes into this repo.

The card is public at `https://<host>/.well-known/agent-card.json`. It names the
endpoint, the token URL and the scope. A call is two requests. First get a token with the
client-credentials flow:

```bash
curl -s https://login.microsoftonline.com/<tenant>/oauth2/v2.0/token \
  -d grant_type=client_credentials \
  -d client_id=<product-client-app-id> \
  -d scope=api://<api-app-id>/.default \
  -d client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer \
  -d client_assertion=<a JWT signed with the product's certificate>
```

Then send the proposal as a JSON-RPC `SendMessage`, with the contract input as one data
part:

```json
{"jsonrpc": "2.0", "id": 1, "method": "SendMessage",
 "params": {"message": {"messageId": "<a new uuid>", "role": "ROLE_USER",
   "parts": [{"data": {"proposal": "Text the whole league that tonight's game is cancelled.",
                       "context": "lineup, organizer asked in chat; 40 members, all opted in."}}]}}}
```

`POST` it to the endpoint on the card with `Authorization: Bearer <token>` and
`A2A-Version: 1.0`. The reply is a task. When its state is `TASK_STATE_COMPLETED`, the
verdict is the data part of its first artifact.

There is a verdict only when the task is `TASK_STATE_COMPLETED` and that data part passes
the caller's own check against the contract's `output` schema. Anything else means no
verdict, and the caller treats the action as blocked and asks the human. That includes:
- `TASK_STATE_REJECTED`: the server's $25 monthly ceiling is reached, and the status
  message's data part says when reviews resume.
- `TASK_STATE_FAILED` or `TASK_STATE_CANCELED`: the review didn't finish, for example a
  timeout or a reply that didn't match the contract.
- A JSON-RPC error: -32602 for input that doesn't match the contract or won't fit its
  budget, -32005 for a media type the card doesn't declare.
- HTTP 401 for a missing or invalid token, and 403 for a valid token from an app that
  isn't on the allowlist or a delegated (user) token.
- A network error or the caller's own timeout.

Each caller sees only its own tasks. The server's
[README](../hives/agents-hive/servers/a2a/README.md) has the full behavior.

## Where the two products stand

lineup is the House's first product, built while the hives were separate repos. Barry
orchestrates its six skills, Patricia governs under `lineup-etiquette`, Airtable holds its
data, and notifications go through Inkbox, with email live and SMS still being set up.
Its README installs by copying its skills by hand and names the per-hive installers,
with no pin. Adopting this guide would mean an `ai-hive` pin and the pack, the
`lineup-etiquette` policy moved into lineup beside its `AGENTS.md`, its state files moved
into `knowledge/` as the example shows, and a call to hosted Patricia before a gated
send.

Singularity is a game whose React app is one client of a game service, and it already
follows the House's patterns: portable skills and a guide contract, provider details in
adapters, and the Charter as its root `AGENTS.md` extended with game rules. Its
alignment doc records how it takes upstream changes. It pins the six archived hive repos,
so the `ai-hive` pin is its main step.
