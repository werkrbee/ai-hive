# The assurance loop: design note

Status: accepted (#124). It settles how every agent the House ships is held to what it
may do before any code is written, as the hosted Barry note
([`hives/agents-hive/design/hosted-barry.md`](../hives/agents-hive/design/hosted-barry.md))
did for hosting Barry. It ends with what it changes in the implementation issues on the
`P2.1 — assurance loop` milestone (epic #122). The reason for this work is in the factory
thesis ([`factory-thesis.md`](factory-thesis.md), "Defensive co-scaling").

## The problem

What an agent may do is written down today, but in four places, and nothing checks them
against each other or against what the agent actually did. Its execution contract
(agents-hive) grants permissions and a budget. Its Agent Card says how to reach it. The
approval policy (rules-hive) decides each action. Its model, prompt files and ceiling sit
in a deployment's config. A run record (workflows-hive) and the usage ledger
(knowledge-hive) record what happened, but either can be edited without a trace. Patricia's
eval chose her model and last ran on 2026-10-21. A paused run reaches a human one run at a
time. And a sub-agent gets whatever its harness hands it.

The fix is one document per agent that says what it is and what it may do, and four
controls that hold it there. Each builds on a part that already exists, so none starts
from nothing:

| Control | Builds on |
|---------|-----------|
| Passport | the execution contract, the Agent Card, the approval policy, the deployment's model and prompt files |
| Audit log | the engine's step decisions, approvals and cancels; knowledge-hive's JSON-lines formats |
| Trust evaluation | Patricia's eval (`deploy/azure/eval`) and its recorded results |
| Rollback | git history, the engine's checkpoints, results that supersede earlier ones |
| Review queue | the engine's paused runs and their `pending` approvals |

## The passport

A passport is one JSON file per agent at `hives/agents-hive/passports/<persona>/passport.json`,
checked against `schema/passport.schema.json`. It lives beside the contracts and cards,
because they say what an agent is and the passport ties them together. It doesn't copy
them; it points at them and narrows them.

```json
{
  "$schema": "../../schema/passport.schema.json",
  "passport": "patricia",
  "version": 3,
  "owner": "@werkrbee",
  "contract": { "capability": "governance-review", "version": 1 },
  "policy": { "ruleset": "hives/rules-hive/rules/queen-charter/policy.json", "version": 1 },
  "permissions": { "granted": ["fs.read"], "approval": [], "never": ["agent.delegate", "net.fetch"] },
  "budget": { "usd": 0.5, "tokens": 200000, "seconds": 600 },
  "delegates": [],
  "pins": {
    "model": { "publisher": "anthropic", "name": "claude-sonnet-5-5", "version": "…" },
    "prompt": [
      { "path": "hives/rules-hive/rules/queen-charter/AGENTS.md", "sha256": "…" },
      { "path": "hives/skills-hive/skills/patricia/SKILL.md", "sha256": "…" },
      { "path": "hives/agents-hive/agents/charter-review/agent.md", "sha256": "…" }
    ],
    "policy": { "sha256": "…" }
  },
  "eval": {
    "suite": "hives/agents-hive/deploy/azure/eval/cases.json",
    "baseline": { "met": 12, "of": 12, "result": "…" },
    "threshold": 0
  }
}
```

**Identity and owner.** `passport` is the persona's name, the same as its card's and its
skill's directory. `owner` is the GitHub account or team accountable for the agent, so a
human is named at the top of every passport. `version` is an integer, bumped on any
change, and an agent's passport digest (SHA-256 of the file's canonical JSON, defined
under the audit log) is how the other controls name the exact version they saw.

**What it may and may not do.** `permissions` and `budget` can only narrow the contract's.
Every action the passport grants or puts under approval is one the contract grants or puts
under approval, and nothing the contract puts under approval is granted, so moving an
action from granted to approval narrows it and the reverse is refused. Each budget figure
is at most the contract's. `never` names actions the agent may not take even with a
human's approval, so what it may not do is written out rather than left to the absence of
a grant. Every action in `never` becomes a prohibition when the engine decides that
agent's steps, so the approval policy denies it before any mandate is read. CI refuses a
passport that grants more than its contract, names a `never` action anywhere it grants,
or pins a prompt file whose digest doesn't match the file.

**What it runs.** `pins` holds the versions the agent runs on: the model by its catalog
publisher, name and version, each prompt file with its digest, and the policy's digest.
The contract and policy versions are already in `contract` and `policy`. A change to any
pin is a new passport version. An agent run inside a harness, rather than deployed by
werkrbee, has no `model` pin, because the harness picks the model. It is still held to
its permissions, policy and prompt files, but it can't claim an eval baseline, since a
baseline belongs to a model.

**Its baseline.** `eval` names the agent's suite, the baseline its pins earned and the
result in `results.jsonl` that records it, and the threshold used to detect drift (see trust
evaluation, below).

**Who it may hand work to.** `delegates` lists the passports it may delegate to (see
sub-agents and clones, below).

**From the card.** Each Agent Card links its passport through an A2A extension in
`capabilities.extensions`, which is how A2A adds to a card without changing it. Its `uri`
is the passport schema's URL, since A2A uses an extension's `uri` to name the kind of
extension, and its `params` hold the passport's URL, its version and its digest;
`agent_card.py --check` already validates extensions. The deployment checks that the pins
it is about to run match the passport, so `deploy.sh` refuses to deploy a model, prompt or
policy the passport doesn't pin. The deployment's model choice lives in the git-ignored
`main.bicepparam`, so that check runs at deploy time, not in CI.

## The audit log

Traceability is an append-only, hash-chained JSON-lines file, `audit.jsonl`, in
knowledge-hive's format beside `results.jsonl` and `ledger.jsonl`, with the same rules:
one object per line, unknown fields rejected, and no secrets or personal data. It records
what an agent did and didn't do. Every decision goes in, not only the actions that ran.

```json
{"seq": 41, "at": "2026-11-02T14:02:12Z", "prev": "sha256:9f2c…", "kind": "step.decided",
 "agent": {"passport": "barry", "version": 4, "sha256": "…"}, "runId": "run_01J9Z…",
 "step": "s7", "action": "message.send", "decision": "paused", "rules": ["organizer.blast"],
 "call": "sha256:…", "hash": "sha256:4be1…"}
```

**What is recorded.** `kind` is one of: `step.decided` (with `decision` `allowed`,
`paused` or `denied`), `step.ran`, `step.failed`, `approval.answered` (with `by` and
`decision`), `run.started`, `run.cancelled`, `run.expired`, `budget.refused`,
`turn.completed`, `delegation`, `rollback`, `drift` and `eval.ran`. `call` is the digest
of the exact tool call, the same input as hosted Barry's approval `id`, so an entry can be
matched to its run record without the log holding the call's arguments. Message text,
recipients and model output stay in the run record. `by` is the identifier the approving
product gives its person, never their name or email, as with everything in knowledge-hive.
On one machine, the engine fills `by` from the operating-system login today, which is
often a name; it will instead take a configured actor ID and refuse to record an answer
without one.

**How tampering shows.** Each entry's `hash` is the SHA-256 of the entry without `hash`,
serialized as canonical JSON: keys sorted, no insignificant whitespace, UTF-8, numbers as
Python's `json` writes them. `prev` is the previous entry's `hash`, and the first entry's
`prev` is `sha256:` followed by 64 zeros. `seq` counts from 1 with no gaps. A verifier,
`check_audit.py`, recomputes the chain and reports the first entry that was edited,
removed, inserted or reordered. A chain can't show that its last entries were cut off, so
two things anchor its end. Each run record keeps the `seq` and `hash` of the last entry
written for it, so the verifier, given the run records, catches a log that ends before a
run's last entry. And a hosted deployment also writes each entry to an Azure Storage
append blob in a container with a locked, time-based immutability policy that allows
protected append writes (`allowProtectedAppendWrites`), which the storage service enforces
even against the subscription's owner until the retention period ends. That is generally
available. The format and the verifier don't depend on it, so a product on another host
anchors the log however its host allows.

**Who writes it.** The workflows-hive engine, as the one writer per log, for every step
decision, approval, denial, cancel and expiry; the review queue, through the engine; the
eval, for its runs and any drift; and rollback, for each restore. Like the ledger, one
process owns a log.

**The rule.** The Charter's first principles gain a line: no agent deletes, edits,
truncates or rewrites an audit log, or acts to hide what it did. The Charter's
`policy.json` gains the actions `audit.edit` and `audit.delete` as prohibitions, so no
mandate or approval can open them. Archiving a log under the owner's retention period is a
human's infrastructure change, gated like any other.

**What it can't stop.** On one machine, an agent that holds `fs.write` over the directory
holding the log can rewrite all of it and recompute every hash. The chain shows tampering
by anyone who didn't rewrite it whole; it isn't a lock. The approval policy can't close
that gap today: its scopes match exact values, not path prefixes, and an agent with
`shell.exec` can write files without asking for `fs.write`. So the local log is evidence,
not a guarantee, and the hosted case, where the agent has no file system or shell and the
blob is immutable, is the strong one.

## Trust evaluation and drift

An agent drifts when it stops behaving the way it did when it was approved. The trust
evaluation measures that against the baseline in its passport.

**The suite.** Each agent's suite is a cases file that runs through the agent's own
deployed path, as Patricia's twelve cases run through the server's reviewer. A case
records what output it accepts, and a case marked `critical` is one where the wrong
answer lets a consequential action through. For Patricia, the critical cases are the
six whose only acceptable verdict is `block`. Barry's orchestration eval (#119) is
added when it lands, and its critical goals are the ones with a gated action to pause
for.

**The score and the threshold.** The score is the number of cases met. A run drifts when
it meets fewer than the baseline minus the passport's `threshold`, or when it misses any
critical case, whatever the threshold. Patricia's threshold is 0, because she is the
governance check. Cost and time per case are recorded too, and a run that costs more than
twice its baseline's per case is flagged to the review queue without counting as drift.
Model output varies, so a run that drifts is run once more, and drift is recorded only
when both runs drift. A critical case missed in either run still sends an item to the
review queue, marked as an unconfirmed miss, so a governance gate that fails even once
leaves a trace.

**When it runs.** On any new passport version, before it is deployed, because `deploy.sh`
refuses a passport whose baseline result wasn't recorded against its exact pins. That is
what blocks promoting a change. And on a schedule, to catch drift nobody caused, such as a
provider changing what a model version serves: weekly for Patricia, through a Container
Apps job on a cron schedule in the same environment, under her identity, so no new
credential goes into CI. Each run is an entry in `results.jsonl` and the audit log, and
is metered into the agent's own ledger, against its own model-spend ceiling.
Patricia's last run was billed $0.13 on Claude Sonnet 5.5, so a weekly run is about
$0.55 a month. An eval the ceiling refuses goes to the review queue as an eval that
couldn't run, not as a pass.

**What drift does.** It sends an item to the review queue with both runs' results, and it
blocks promoting any change to that agent until a human answers. The agent keeps running
on its current version unless the human rolls it back or stops it.

## Rollback

Rollback restores an earlier version or state, and never erases history to do it: a
rollback is a new entry, a new checkpoint or a new deploy, recorded with who did it and
why.

**Versions.** A passport's history is its git history. Rolling an agent back is
deploying an earlier passport version, through `deploy.sh`, which restores the model
deployment, prompt files and policy it pins. That is a deploy, so the Charter gates it,
and the audit log records who approved it and why. A model version the catalog has since
retired can't come back, so `deploy.sh` checks the catalog first and stops if it is gone.
The earlier passport's baseline still applies, since its pins didn't change.

**Run state.** The engine already writes a checkpoint after every step. Rolling a run back
to an earlier step marks each later step `rolledBack`, never deleting it, and sets `next`
to the step after the target, so the record shows both what ran and what was undone. A
step whose actions all read, or write only the run's own record, has no effect outside
the system and is simply marked. Any other step had an external effect, and rolling past
it needs a compensating step first, newest first.

**Effects outside the system.** A sent message can't be unsent or a charge uncharged; it
can only be compensated, by a correction or a refund. A compensating step is an ordinary
step with its own action, decided by the approval policy like any other, so a correction
message to 14 people pauses for a human just as the first message did.

**Knowledge.** A result is never edited; a correction is a new result that supersedes it,
as knowledge-hive already does. `STATE.md` and memory files are rolled back with git. The
ledger and the audit log are never rolled back: money spent stays spent, and what
happened stays recorded.

## The human review queue

The review queue is one place where a human sees and answers everything that needs them,
across every run and agent. It lives in workflows-hive, since the engine owns runs and
their pauses.

**What it holds.** Three kinds of item: an `approval` (a paused step), `drift` (from the
trust evaluation) and an `escalation` (an agent asking a human, as the Charter requires on
ambiguous decisions, missing credentials or repeated failure). Each item is a JSON file in
the queue directory, written atomically like a run record, with its `id`, `kind`,
`source` (the run and step, or the passport and eval result), what it must present with
values, `createdAt`, `expiresAt` and `status` (`open`, `answered` or `expired`). The run
record stays the source of truth for an approval; the queue item points at it, and
answering one calls the engine's `approve` or `deny`. The local engine has no approval
`id` yet; it gains the same digest hosted Barry's approvals use, and refuses an answer
whose `id` doesn't match what is pending.

**Answers.** An answer records `decision`, `by`, `at` and, for a denial, `reason`, and is
written to the audit log before the run moves on. An approval or escalation expires after
seven days, as a paused hosted Barry task does, and expiry fails its run. Drift doesn't
expire: it holds promotion until a human answers it.

**Interfaces.** A command, `queue.py` (`list`, `show`, `approve`, `deny`, `answer`), and an
MCP server with the same reads as tools and resources. An agent must never answer its own
queue, and an MCP tool is something a model can call. So the MCP server's answering tool
takes no decision from its arguments: it asks the person through an MCP elicitation, which
the client shows to the user, and records only their reply. A client without elicitation
gets the queue read-only.

The command is the harder case, because an agent with `shell.exec` can run it. Three
things narrow that. The Charter's policy gains `queue.answer` as a prohibition, so no step
that maps to answering the queue can be opened by a mandate or an approval. The command
refuses to answer when it isn't attached to an interactive terminal, or when it runs
inside an engine run, which the engine marks in its steps' environment; harness shells are
usually not interactive. And every answer's audit entry records how it came (`via` is
`cli`, `mcp` or `a2a`). None of this is a lock: on one machine an agent with a shell can
still forge an answer, as it can rewrite the log, so the local trail is evidence rather
than proof. Hosted is the strong case. There the queue's items are the A2A approval
requests hosted Barry already returns, answered by the product as its person's
attestation, and the agent has no shell to reach the queue with.

## Sub-agents and clones

Every harness now spawns sub-agents or clones, and most reuse the parent's cached context
to save compute. Three rules hold a delegate inside its parent's bounds.

**Narrowing.** A delegate runs under its own passport, intersected with its parent's. Each
action takes the stricter of the two passports' treatments, in the order `never`, then
approval, then granted, and an action either passport leaves out is denied. Its budget is
carved out of what the parent has left, reserved from the parent's run. Delegation is the
action `agent.delegate`, with the delegate's passport as its scope, so the approval policy
decides it and refuses a delegate the parent's passport doesn't list in `delegates`. The
fleet personas in agents-hive (explore, code-review, security-review, charter-review) get
passports so they can be delegates.

**Context.** A delegate gets its context explicitly: the delegation names what it passes,
as A2A message parts or the harness's equivalent, never the parent's whole conversation.
A clone that inherits the whole context, as some harnesses' forks do, is the parent under
another name: it runs under the parent's passport, inside the same caller's run, and
nowhere else.

**Cache scope.** Cached context never crosses a trust boundary. A hosted server never
reuses a model session, a conversation or a cached prompt that holds one caller's data for
another caller or tenant. What it may cache is the shared material, such as the Charter,
the skill and the contract, placed before any caller's data so the cached prefix holds
nothing private.

**Logged.** Every delegation is an audit entry naming the parent's and the delegate's
passports and versions, the digest of the narrowed grant and the digests of the context
items passed.

## Harness-agnostic

Nothing here depends on one vendor. Passports are JSON files with a JSON Schema, linked
from A2A cards through A2A's own extension mechanism. The audit log, results and queue
items are JSON files any harness can read, checked by stdlib Python. The rules are in the
Charter's `AGENTS.md` and its policy. The queue is reached through a command and MCP, and
delegation through A2A. Azure appears only in werkrbee's own deployment: the immutable
blob and the scheduled job are how werkrbee anchors its log and runs its schedule, and a
product elsewhere uses its own host's equivalents.

## Cost

The scheduled evals are metered into each agent's ledger, so the ledger's ceiling caps
their model spend with the rest of the agent's. That ceiling counts model calls only. The
blob and the job are infrastructure, which the Azure budget covers, and the budget only
alerts. By estimate, not yet measured, the blob holds a few kilobytes a day, well under a
dollar a month, and a weekly job of a few minutes stays inside Container Apps' monthly
free grant. A locked immutability policy can't be shortened or removed until its retention
ends, so the container is kept for at least that long; it is created through the deploy's
gated steps with the maintainer's approval.

## Out of scope here

Signing passports and Agent Cards, until a caller needs to verify them without trusting
the repo. Approvals carried by the person's own delegated token, as in the hosted Barry
note. Retention periods past the first year. A dashboard for the queue, which would be
one more client of the same interfaces.

## What it changes in the implementation issues

The order on the milestone holds: the passport and the audit log first, then the review
queue, trust evaluation, rollback and sub-agent boundaries. On acceptance, the issues are
edited to match:

- **#125, passport.** Adds `never`, `delegates`, the prompt and policy digests, the card
  extension, and the CI checks above.
- **#126, audit log.** Adds the engine reading the passport a step runs under, so that
  each entry names it and its `never` actions become prohibitions, the canonical JSON and
  genesis rules, the run record's anchor, `audit.edit` and `audit.delete` as prohibitions
  in the Charter's policy, and opaque `by` identifiers, with the engine's operating-system
  login default replaced by a configured actor ID. Its body's "core principles" becomes
  "first principles".
- **#127, trust evaluation.** Adds critical cases, the confirming re-run, the queue item
  for an unconfirmed critical miss, the cost flag and `deploy.sh` refusing a passport with
  no baseline for its pins.
- **#128, rollback.** Adds `rolledBack` steps, compensation newest first and the retired
  model check.
- **#129, review queue.** Adds the item files, expiry rules, elicitation-only answers over
  MCP, the approval `id` in the local engine, `queue.answer` as a prohibition, the
  command's refusal outside an interactive terminal or inside a run, and `via` on each
  answer.
- **#130, sub-agents.** Adds passports for the four fleet personas, the stricter-treatment
  intersection, the clone rule and the cache rule.

One new issue covers the deploy side, which the ROADMAP's guardrail already asks for:
putting hosted Patricia under the controls as they land, with the immutable blob, the
weekly eval job and `deploy.sh`'s pin checks, through the deploy's gated steps. Hosted
Barry's deploy (#120) gets the same pieces when he ships.
