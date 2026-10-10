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
| Azure Files share | `/data`: the task database and the usage ledger, so both survive restarts and scale-to-zero. It is mounted with `nobrl`, which is safe only with one writer. |
| Microsoft Foundry (AI Services) | The models. Key auth is disabled, so the server reaches them only with its managed identity, and there is no API key to store. |
| User-assigned managed identity | Pulls the image (AcrPull) and calls Foundry (Cognitive Services User). |
| Container registry (Basic) | Holds the image, built from a commit by `az acr build`. |
| Budget | Alerts at 80% and 100% of actual spend, and at 100% of forecast spend. $25 a month by default. |

**Two limits on spend.** The server refuses new reviews once its own ledger reaches
`monthlyCeilingUsd`. That ledger counts only model calls, at list price. The Azure budget
watches the bill for everything in the group: the model, plus the registry (about $5 a
month for Basic), storage and logs. The budget only alerts; it doesn't stop anything.

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
   role. It asks before changing anything, reuses an existing app only when exactly one
   has that name and you own it, and sets the API so that only assigned apps can get a
   token for it. It prints `apiAppId` and `allowedClients`. It creates no secrets: each
   product's owner adds a credential to their own app, preferably a certificate or a
   federated credential, and keeps it in that product's secret store.
2. **Parameters.** Copy `main.example.bicepparam` to `main.bicepparam`, which git
   ignores, and fill it in: the Entra ids, the two Foundry models, the chosen model's list
   prices, and the budget contacts.
3. **Choose the model.** See below. Until then, `modelDeployment` is either candidate.
4. **Deploy.** Run `./deploy.sh <resource-group> <location> main.bicepparam` from a clean
   checkout. It deploys in three steps, each confirmed after a what-if:
   - the infrastructure, without the app;
   - the image, built into the new registry and tagged with the commit;
   - the app.

   It prints the Agent Card URL at the end.

A product calls the server with a token from the client-credentials flow: `POST` to
`https://login.microsoftonline.com/<tenant>/oauth2/v2.0/token` with its client id, its
credential and `scope=api://<apiAppId>/.default`.

## Choosing the model

Patricia's default model is fixed by evidence, not by preference. `eval/cases.json` holds
twelve proposals with the verdicts the Charter allows for each. They cover read-only
work, local edits, requested and unrequested pushes, deletes, secrets, approved and
unapproved messages, unbounded retries, merging on red CI, claiming done without tests,
and purchases. `eval/run.py` sends each case to every model given. It goes through the
server's own reviewer, with the same prompt, contract checks and budget, and reports
verdicts, cases passed, cost and latency.

```bash
cd hives/agents-hive/servers/a2a                        # with requirements installed
az login                                                # the eval uses your identity
python ../../deploy/azure/eval/run.py --config model-a.toml --config model-b.toml --out results.json
```

Each config is a copy of `config.example.toml` naming one deployment, with
`auth = "entra"` and that model's `base_url` and prices. Your account needs Cognitive
Services User on the Foundry resource. Record the table and the choice in
`eval/RESULTS.md`, then set `modelDeployment`, `modelProvider` and the prices to match.

## What's verified so far

- `main.bicep` and the example parameters compile, and the Bicep linter is clean. CI
  checks both.
- The image's file list and `render_config.py` were exercised by running the server
  from a copy of exactly what the Dockerfile copies. The rendered config loads, the card
  carries the HTTPS URL and the `api://` scope, and calls without a valid token get 401.
  The image itself hasn't been built here. `az acr build` sends only the files the
  Dockerfile copies (the repo's `.dockerignore`).
- The managed-identity credential's async transport (`aiohttp`, now pinned) gets as far
  as requesting a token; it fails there off Azure, as expected.
- The eval harness runs end to end with the stub model.

Not yet verified, because it needs the deploy:
- The Foundry endpoints the server derives: `/anthropic` and `/openai/v1` on the
  account's subdomains.
- Whether each API accepts managed-identity tokens.
- `entra.sh` against a tenant.
- The Azure Files mount with SQLite.

The first deploy and the eval check these. Record anything that differs in this README.

## Files

```text
deploy/azure/
├── main.bicep                 # everything above, in one resource group
├── main.example.bicepparam    # copy to main.bicepparam and fill in
├── entra.sh                   # the API app and one client app per product
├── deploy.sh                  # what-if, confirm, deploy, in three steps
├── Dockerfile                 # the server image, built from the repo root
├── render_config.py           # the app's environment to the server's config, at start
└── eval/
    ├── cases.json             # governance-review cases and their acceptable verdicts
    └── run.py                 # compare models on them
```
