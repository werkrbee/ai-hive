# Hosted Patricia on Azure

werkrbee's deployment of the reference A2A server ([`servers/a2a`](../../servers/a2a)) for
Patricia's `governance-review`. Only werkrbee's own products may call it: each has an Entra
ID app registration, and the server accepts tokens only from those apps.

Deploying is an infrastructure change, which the Queen Bee's Charter gates. Everything
here prepares the deploy, and the maintainer runs it. `deploy.sh` shows Azure's what-if
for each change and waits for a typed "yes".

## What gets created

One resource group holds the whole deployment, so one budget covers it.

| Resource | Why |
|----------|-----|
| Container App (scale 0 to 1) | Runs the server. It scales to zero when idle and never runs more than one replica, because the ledger's running total and the SQLite task store each belong to one process. Ingress is HTTPS only. |
| Container Apps environment and Log Analytics | Hosting and logs, kept 30 days and capped at 0.1 GB a day. Past the cap, logging stops until the next day. |
| Azure Files share | `/data`: the task database and the usage ledger, so both survive restarts and scale-to-zero, and the weekly evaluation's ledger and its results, queue and audit log under `assurance/`. It is mounted with `nobrl`, which is safe only with one writer to each file: the app and the job never write the same one. |
| Container Apps job (weekly) | Patricia's weekly trust evaluation, from the app's image, under the same identity and in the same environment, so no credential goes into CI (see "Weekly evaluation"). |
| Audit log storage account | The audit log's immutable copy, an append blob in a container under a time-based retention policy, in an account of its own so that locking the policy holds nothing else. Only Entra identities reach it: account keys are off. The identity may append (Storage Blob Data Contributor, on the container), and the people in `auditReaders` may read it. |
| Microsoft Foundry (AI Services) | The models. Key auth is disabled, so the server reaches them only with its managed identity, and there is no API key to store. |
| User-assigned managed identity | Pulls the image (AcrPull) and calls Foundry with the narrowest built-in role the model's API allows. For Chat Completions that's Cognitive Services OpenAI User, which can call the OpenAI v1 endpoint but can't list keys or use Foundry's other services; verified with the managed identity on 2026-10-14. For Messages (Anthropic models) it's Cognitive Services User, the role Microsoft names for Entra calls to Claude's `/anthropic` endpoint, which isn't under the OpenAI role. A deploy adds roles but doesn't remove them, so after switching from an Anthropic model to any other, remove the identity's Cognitive Services User assignment by hand. |
| Container registry (Basic) | Holds the image, built from a commit by `az acr build`. |
| Budget | Alerts at 80% and 100% of actual spend, and at 100% of forecast spend. $25 a month by default. |

**Two limits on spend.** The server refuses new reviews once its own ledger reaches
`monthlyCeilingUsd`. The weekly evaluation keeps its own ledger beside it, and each counts
the other's spending, and the calls it has in flight, toward the same ceiling. The ledgers
count only model calls, at list price. The Azure budget watches the bill for everything in
the group: the model, plus the registry (about $5 a month for Basic), storage, logs and
the job. The budget only alerts; it doesn't stop anything.

**Deploying a new image.** While a new revision starts, Container Apps can run it
alongside the old one for a short time, and both open the same files. Deploy when no
review is running; the app is idle most of the time, and reviews take seconds.

**The card.** The server renders its Agent Card with the app's HTTPS URL
(`https://<prefix>-a2a.<environment domain>/`) and serves it at
`/.well-known/agent-card.json`. The card is the one thing served without a token, because
clients need it to learn how to authenticate.

## Deploy

1. **Callers.** Run `./entra.sh lineup singularity`. It creates the API app, with a
   `Review.Request` app role and v2 tokens, and one client app per product granted that
   role. It looks everything up first and prints a plan: for each app, whether it will
   create it or reuse an existing one (and its appId), and which role grants it will add.
   Nothing changes until you type yes. It reuses an existing app only when exactly one
   has that name and you own it, and sets the API so that only assigned apps can get a
   token for it. It prints `apiAppId` and `allowedClients`. It creates no secrets: each
   product's owner adds a credential to their own app, preferably a certificate or a
   federated credential, and keeps it in that product's secret store.
2. **Parameters.** Copy `main.example.bicepparam` to `main.bicepparam`, which git
   ignores, and fill it in: the Entra ids, the Foundry models to compare (see "Which
   models" below), the chosen model's list prices, and the budget contacts. Some providers need facts about who is using their
   model, which go in that model's `providerData`; Azure refuses the deployment without
   them. Anthropic, for one, needs your organization's legal name, its two-letter country
   code and its industry (lowercase: technology, finance, healthcare, education, retail,
   manufacturing, government, media or other). Azure uses them to accept the provider's
   Marketplace terms and sends them to the provider with each request, so they must be
   true.
3. **Choose the model.** See below. Until then, `modelDeployment` is either candidate.
4. **Deploy.** Run `./deploy.sh <resource-group> <location> main.bicepparam` from a clean
   checkout. It first checks that Patricia's passport may be promoted (see trust
   evaluation, below), and stops before anything else if not. Once a template with the
   weekly evaluation is deployed, it then reads what that evaluation recorded on the share
   and stops if drift there holds her, or if it has recorded nothing in eight days. It looks up every built-in role id `main.bicep`
   assigns, and stops before any change if one doesn't exist, because what-if doesn't
   check them. It checks every model against the region's Foundry catalog and stops if
   one isn't there, isn't generally available, doesn't do chat completions or isn't
   offered with its sku, and if `modelDeployment` isn't the model her passport pins, by
   name and version. Then it deploys in four steps, each confirmed:
   - the infrastructure, without the app, after a what-if;
   - the audit log's retention policy, when it isn't set (see "The audit log's immutable
     copy");
   - the image, built into the new registry and tagged with the commit;
   - the app and the weekly evaluation job, after a what-if.

   If a what-if fails, it stops there without asking, since there is no plan to approve.

   It prints the Agent Card URL at the end. The app and the job start only on the prompt
   files her passport pins: each must match its pinned digest, or the container exits
   before it serves anything (`render_config.py`). The policy she is pinned to isn't read
   by the server; the promotion check holds it to its pin.

A product calls the server with a token from the client-credentials flow: `POST` to
`https://login.microsoftonline.com/<tenant>/oauth2/v2.0/token` with its client id, its
credential and `scope=api://<apiAppId>/.default`.

## Which models

The Foundry model catalog for the deployment's region is the source of truth: it's what
the subscription can actually deploy, and it marks each model's lifecycle. List it with
`az cognitiveservices model list -l <region>`, the same data as the portal's catalog.
Take each `models` entry's `format`, `name`, `version` and `sku` from it. Only
`GenerallyAvailable` models are eligible, the same rule as for Azure API versions:
`deploy.sh` refuses preview, deprecating and retired ones, naming the status. The catalog
lists a model once per account kind (`AIServices`, `OpenAI`, `MaaS`, …), and the kinds can
offer different skus, so `deploy.sh` reads only the rows for the kind `main.bicep`
deploys, `AIServices`, and says so when a model is offered only for another. The catalog
carries no reliable prices, so the prices stay a parameter you check yourself.
`prices.sh` looks them up in Azure's public Retail Prices API, with no sign-in:
`./prices.sh <region>` lists the region's Foundry products, and
`./prices.sh <region> <product> [<sku-prefix>]` prints that product's meters per million
tokens, all of them or those whose name starts with the prefix. Meter names differ by
publisher, so it shows them and you pick the input and output meters for your sku:
GPT-5.4's are `5.4 inp Gl` and `5.4 opt Gl` under `Azure OpenAI GPT5`, DeepSeek-V3.2's
`V3.2 Inp glbl` and `V3.2 Outp glbl` under `Azure Deepseek Models` (`Gl` and `glbl` are
GlobalStandard). Pick the base meters, not the ones marked `longco`, `Batch`, `cd`
(cached input) or `pro`. `longco` prices prompts over the model's long-context threshold
higher (GPT-5.4's are $5.00 and $22.50 per million, against $2.50 and $15.00); a review
sends about 2,500 input tokens, far below it. Models sold through the Azure Marketplace,
such as Claude, aren't in that API; their prices are on the offer.

The chosen model's format decides the API the server speaks. Anthropic models are
served through the Messages API at the account's `/anthropic` endpoint; every other
format, OpenAI's and the other publishers', through Chat Completions at
`/openai/v1`. The managed identity's role follows the API (see Resources). The catalog
doesn't say which API a model needs (Claude's entries list `chatCompletion`, like every
other chat model's), so the rule is `messagesFormats` in `main.bicep`. If a publisher
whose models need the Messages API joins the catalog, add its format there. `deploy.sh`
reads that list and shows, for each model, the API the server would use with it and which
one `modelDeployment` chooses, before the what-if.

The catalog doesn't say how much quota the subscription has. A deployment's `capacity`
must fit the model's quota in the region, or the what-if fails Azure's preflight with
`InsufficientQuota`, naming the limit. Quota is counted in the model's own unit: thousands
of tokens a minute for OpenAI's models, requests a minute for some others (DeepSeek-V3.2
had 20).

Not supported yet, and refused by `deploy.sh` because the catalog says they don't do
chat completions:
- Models served only through OpenAI's Responses API, such as the codex and `-pro`
  models. The server would need a third API for them; add it when one is a candidate.
- Models that can't review a proposal: embeddings, rerankers, image, speech and
  document models.

## Choosing the model

Patricia's default model is fixed by evidence, not by preference. `eval/cases.json` holds
seventeen proposals with the verdicts the Charter allows for each. They cover read-only
work, local edits, requested and unrequested pushes, deletes, secrets, approved and
unapproved messages, unbounded retries, merging on red CI, claiming done without tests,
and purchases, and five adversarial cases whose input tries to talk the reviewer into a
verdict. `eval/run.py` sends each case to every model given. It goes through the
server's own reviewer, with the same prompt, contract checks and budget, and reports
verdicts, cases passed, cost and latency.

```bash
cd hives/agents-hive/servers/a2a                        # with requirements installed
az login                                                # the eval uses your identity
python ../../deploy/azure/eval/run.py --config model-a.toml --config model-b.toml --out results.json
```

Each config is a copy of `config.example.toml` naming one deployment, with
`auth = "entra"`, the `api` its format calls for, its format as `publisher`, and that
model's `base_url` and prices. Any eligible model can be a candidate. Your account needs
Cognitive Services User on the Foundry resource. Record the table and the choice in
`eval/RESULTS.md`, then set `modelDeployment` and the prices to match.

## Trust evaluation

The same cases are Patricia's trust evaluation (the agents-hive README, "Trust
evaluation"). With `--passport`, `eval/run.py` takes one config, which must name her
persona, contract and pinned prompt files, on the deployment that serves her pinned model,
and whose `ledger` is her own: each call is metered there against her monthly ceiling. It
compares the run with the baseline in her passport, runs it again if it drifted, appends
the evaluation to `eval/results.jsonl` and the audit log, and sends what it finds to the
review queue.

```bash
python ../../deploy/azure/eval/run.py --passport patricia --config patricia.toml --spacing 12
```

`review-a` allows 50,000 tokens a minute, and Foundry counts each call's output allowance
toward it as well as its prompt, so keep Patricia's calls 12 seconds apart. A call the
deployment still rate-limits is retried, and a case that never gets an answer makes the
evaluation `not-run`, not drift.

Before a change to her pins is deployed, run it on the new pins. If the run is within her
baseline, it prints the `eval.baseline` that makes it the new one; set that in her
passport and bump its version. `deploy.sh` refuses her passport until then, and while
drift in the review queue holds it. Her suite is one of her pins, so a changed case is a
change to her pins too: pin the suite's new digest, which the validator prints, and run
her on it. When cases are added to her suite or taken out, the baseline no longer fits
it: the runner still evaluates her, but the run must meet the whole suite to become the
new baseline.

## Weekly evaluation

A Container Apps job runs `eval/weekly.sh` on `evalSchedule`, Mondays at 06:00 UTC by
default, to catch drift nobody caused, such as a provider changing what a model version
serves. It runs from the image the app runs, under the same identity, so it evaluates
what is deployed, with the same pins check: the config it starts from takes the prompt
files from her passport. Each call is metered into its own ledger,
`/data/ledger-eval.jsonl`, which the server counts toward the ceiling, as the job counts
the server's. A run takes about four minutes at 12 seconds between calls and costs about
$0.19 on Claude Sonnet 5.5 (`eval/results.jsonl`, 2026-10-29), about $0.80 a month.

It records on the share, under `assurance/`: the evaluation in `results.jsonl`, with ids
`<date>-patricia-weekly-eval` so none matches one in the repo, its findings in `queue/`,
and its audit entries in `audit.jsonl`, which it pushes to the immutable copy before and
after each run. A run that drifts or can't run fails, so it shows in the job's execution
history:

```bash
az containerapp job execution list --name <prefix>-eval --resource-group <rg> -o table
```

What it finds holds promotion: `deploy.sh` downloads `assurance/`, read-only, with the
account key in its environment, and runs the promotion check on it. So does its silence. A
run whose first audit push fails exits before it records anything, so `deploy.sh` also
stops when the newest evaluation, or the job's creation if it has none, is more than eight
days old (`HOSTED_MAX_DAYS`, a week and a day's grace; a less frequent `evalSchedule`
needs it raised). The job's execution history says why it went quiet. Answer an item with
`assurance.sh`, at your terminal, under your actor id:

```bash
./assurance.sh list <rg>
./assurance.sh approve <rg> <item-id> --by usr_7f3a
./assurance.sh deny <rg> <item-id> --reason "the provider changed the model" --by usr_7f3a
```

It downloads `assurance/`, answers with workflows-hive's `review_queue.py`, which refuses
without an interactive terminal, and uploads the item and the audit log, unless the
share's log changed after it was downloaded, in which case nothing is uploaded and you
answer again. The log's etag is read before the download, so a run that finishes during
or just after it is caught too. The job pushes your answer's audit entry to the immutable copy when it next runs.

## The audit log's immutable copy

The audit log on the share is a hash chain, which shows tampering but can't prevent it:
anyone who can write the share can rewrite the log whole. Its copy, the append blob
`audit/patricia.jsonl` in the audit log's storage account, is held by a time-based
retention policy that allows protected append writes. The storage service lets blocks be
appended and refuses to change or delete them, even for the subscription's owner, until
the period ends. `audit_blob.py push` appends only while the log still starts with what
the copy holds, so a rewritten log stops the job rather than going unnoticed. Check the
copy, and the log against it, with:

```bash
./assurance.sh check <rg>
```

That needs read access to the container: put your object id in `auditReaders`.

`deploy.sh` sets the policy after the infrastructure step, as its own confirmed step: 365
days, protected append writes allowed. An unlocked policy is enforced, but an owner can
remove it. Locking it is a separate decision, taken only when you deploy with
`--lock-audit-retention` and type the account's name: once locked, for 365 days from each
blob's creation, nobody can shorten or remove the policy, change or delete what the
container holds, or delete the account or the resource group. Lock it once the first
weekly run has pushed to the copy and `assurance.sh check` passes. A deploy leaves a
locked policy as it is.

## Rolling back

To roll Patricia back to an earlier passport version, deploy it again with `--rollback`.
Her passport's history is its git history, so `deploy.sh` deploys the newest commit at
which her passport was that version, from a temporary worktree, with the model, prompt
files and policy it pins. Nothing is undone in place: it is a new deploy, through the
same what-if and typed yes at each step.

```bash
./deploy.sh --rollback 6 --reason "v8 misreads the Charter" --by usr_7f3a \
  rg-patricia eastus2 main.bicepparam
```

Before any change, it checks that she was ever that version and that it is earlier than
the one checked out, and it runs the promotion check as it was at that commit, against the
results recorded then, since that passport's baseline still applies. That check can't see
a result recorded later, so if a later evaluation of the same pins found something (drift,
say, or a not-run), it names it in a warning before the first what-if, for you to weigh
before typing yes. A version from before trust evaluation can't be promoted, so it can't
be rolled back to. `modelDeployment` in the parameters must be the model that passport
pins, by name and version, and the model check refuses it if the catalog no longer offers
it as generally available, since a retired model can't come back. Once the app is
deployed, the audit log (`--audit`, by default the workflows-hive engine's) records who
rolled her back (`--by`, or `WORKFLOWS_HIVE_ACTOR`) and the digest of a record in
`rollbacks/` beside it, which keeps the reason. If a step fails or you stop it partway,
nothing is recorded, and what was applied stays applied until the next deploy. If the app
deploys but the rollback can't be recorded (the audit log isn't writable, say),
`deploy.sh` fails and prints the `rollback.py record` command to run once the cause is
fixed.

Some things a rollback doesn't restore. The role assignments a later deploy added stay,
since a deploy adds roles but doesn't remove them. The ledger and the audit log keep
everything since, and so does her results file: a run is corrected by a newer result, not
by going back. A rollback doesn't read the weekly evaluation's findings, since answering
drift is what it is for. And a rollback to a version from before the weekly job leaves
the job in place, still evaluating the newer image. Delete it with
`az containerapp job delete --name <prefix>-eval --resource-group <rg>`, a change to
approve like any other; deploying a version with the job creates it again.

## What's verified so far

- `main.bicep` and the example parameters compile, and the Bicep linter is clean. CI
  checks both.
- The image's file list and `render_config.py` were exercised by running the server
  from a copy of exactly what the Dockerfile copies. The rendered config loads, the card
  carries the HTTPS URL and the `api://` scope, and calls without a valid token get 401.
  `az acr build` sends only the files the Dockerfile copies (the repo's `.dockerignore`).
- The managed-identity credential's async transport (`aiohttp`, now pinned) gets as far
  as requesting a token; it fails there off Azure, as expected.
- The eval harness runs end to end with the stub model, and the trust evaluation with
  the stub and a fake model, through drift, its re-run, the flags and the ceiling
  (`servers/a2a/tests/test_eval.py`, run in CI).
- `entra.sh` ran against werkrbee's tenant and created the API app and the lineup and
  singularity clients; a second run reuses all three and adds nothing. That first run
  showed two things the script had assumed wrongly about `az` (2.90), both fixed:
  `az ad app create` doesn't make you an owner, so the script now adds you, and
  `az ad app update` can't set the token version on a new app, so that goes to
  Microsoft Graph. Its plan and refusals
  are also tested against a stubbed `az` (`tests/entra_test.sh`, run in CI).

- The first deploy, on 2026-10-13, into werkrbee's subscription in eastus2 from commit
  `ef5cb6c`: all three steps, each after its what-if. The image built in the registry
  (`az acr build`, under a minute). The app serves its Agent Card, refuses calls with no
  token or an invalid one with 401, and redirects plain HTTP to HTTPS. The server created
  its SQLite database on the Azure Files share at start.
- Foundry's OpenAI endpoint, `https://<account>.openai.azure.com/openai/v1`, accepts
  Entra tokens: the eval called GPT-5.4 through it (`eval/RESULTS.md`).
- The app's managed identity calls GPT-5.4 on that endpoint with Cognitive Services
  OpenAI User as its only Foundry role: a chat completion from inside the running
  container, on 2026-10-14, returned 200. The role was assigned by hand for that check;
  the template's own assignment replaces it at the next deploy.
- A model from another publisher, on 2026-10-15: DeepSeek-V3.2 (`review-c`), deployed by
  `deploy.sh` after its catalog check passed. The managed identity calls it on the same
  endpoint with the same OpenAI User role (200 from inside the container), and the eval
  ran it (`eval/RESULTS.md`). On this endpoint DeepSeek reports token usage only in a
  streamed response's last chunk; unstreamed, `usage` is null. The server's Chat
  Completions client streams for that reason.

The first deploy found three things, two in this template, both fixed:
- Azure refuses an Anthropic model deployment without `modelProviderData`, so a
  `models` entry can carry `providerData` (step 2).
- The AcrPull role id was wrong. What-if doesn't check role ids, so this failed only
  during the apply; `deploy.sh` now checks role ids before the what-if (#79, step 4).
- Foundry wouldn't deploy Claude Sonnet 5.5 on werkrbee's subscription
  (`MarketplaceSubscriptionCannotBeCompleted`). Azure support found that a purchase
  block on the account caused it and lifted the block; on 2026-10-20 `deploy.sh`
  deployed Claude Sonnet 5.5 version 2 as `review-a`, with the server still calling
  GPT-5.4.

Verified since:
- Foundry's Anthropic endpoint (`/anthropic`), on 2026-10-20: one review through the
  server's Messages client and its own prompt and reply check, against `review-a`, with
  the maintainer's Entra token. It returned 200, reported its token usage, and its
  verdict met the contract.
- A whole authenticated review, on 2026-10-20: a token from an allowed client's
  client-credentials flow, one `SendMessage` to the public endpoint, a completed task
  with a verdict, and its ledger entry on the share (`provider`, `api` and `model` as
  expected, priced at the configured rates). The client's secret was made for the check
  and deleted after it.
- The server on Claude, on 2026-10-22 and 2026-10-23, after the eval chose Claude Sonnet
  5.5 (`eval/RESULTS.md`). With `modelDeployment = 'review-a'` at $2.00 and $10.00 per
  million input and output tokens, `deploy.sh` gave the managed identity Cognitive
  Services User, and the new revision runs with `MODEL_API=messages`. An authenticated review
  through the public endpoint completed with a verdict: the managed identity got a token
  and Claude's `/anthropic` endpoint returned 200, and the ledger entry reads
  `anthropic`, `messages` and `review-a`, priced at those rates. The identity keeps
  Cognitive Services OpenAI User, since a deploy adds roles but doesn't remove them, so
  the previous revision, on GPT-5.4, still works as a rollback.
- Claude's prices. Claude isn't in the Retail Prices API; Azure bills it through its
  Marketplace plan in Claude consumption units at $0.01 each. The 2026-10-20 charge for
  3,811 input and 310 output tokens was 1.0722 units, $0.010722, exactly $2.00 and $10.00
  per million.

That deploy found a fault in `deploy.sh`: the app step's what-if failed (the Bicep CLI
crashed while compiling), and the script still asked to apply. It now stops when a
what-if fails (`tests/deploy_test.sh`). The re-run's what-ifs matched the approved plan.

The weekly evaluation and the audit log's copy aren't deployed yet (#133). So far:
- The image's file list was exercised by copying exactly what the Dockerfile copies,
  through `.dockerignore`, and running the weekly evaluation from that copy with the stub
  model: it rendered its config from the passport's pins, ran the suite, recorded its
  result under a weekly id, queued the drift the stub's verdicts make, and wrote a whole
  audit chain and its own ledger. The promotion check refused the passport on that queue
  and passed it on the local one. That check also found that `.dockerignore` had kept out
  the passports since they were added to the image (#134), so the image's passport COPY
  would have failed; it lets them through now.
- `audit_blob.py` is tested against a fake Blob service that only grows
  (`tests/test_audit_blob.py`), `deploy.sh`'s new steps against a stubbed `az`, and
  `assurance.sh` against a stubbed `az` whose share is a directory.

Record anything that differs in this README.

## Files

```text
deploy/azure/
├── main.bicep                 # everything above, in one resource group
├── main.example.bicepparam    # copy to main.bicepparam and fill in
├── entra.sh                   # the API app and one client app per product
├── deploy.sh                  # check, what-if, confirm, deploy, in four steps; or roll back
├── assurance.sh               # answer the weekly evaluation's queue; check the audit log's copy
├── audit_blob.py              # push the audit log to its immutable append blob, or check it
├── prices.sh                  # the models' list prices, from the Retail Prices API
├── Dockerfile                 # the image for the app and the weekly job, built from the repo root
├── render_config.py           # the environment to the server's config, with the pinned prompts
├── tests/
│   ├── entra_test.sh          # entra.sh's plan and refusals, against a stubbed az
│   ├── deploy_test.sh         # deploy.sh's checks, steps and rollback, against a stubbed az
│   ├── assurance_test.sh      # assurance.sh's answers, against a stubbed az and share
│   ├── test_audit_blob.py     # audit_blob.py, against a fake Blob service
│   ├── test_render_config.py  # the config's pinned prompts and ledgers
│   └── prices_test.sh         # prices.sh's lookup, against a stubbed curl
└── eval/
    ├── cases.json             # governance-review cases, their acceptable verdicts, which are critical
    ├── run.py                 # Patricia's trust evaluation, or compare models on the cases
    ├── weekly.sh              # the weekly job: evaluate, record on the share, push the audit log
    ├── results.jsonl          # each trust evaluation, and the baseline her passport names
    └── RESULTS.md             # each comparison's verdicts, cost and choice
```
