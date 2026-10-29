# knowledge-hive design note

Status: accepted for P1 (#45). This note defines the operational state a product keeps:
what it holds, where it lives, and the format of each part. The templates, the lineup
worked example and `scripts/check_knowledge.py` (#46) are built against it.

## The problem

An agent-run product needs to remember where it is between sessions. Every app built on
the House has hand-rolled that memory, and lineup shows what that costs.

lineup keeps two files. [`STATUS.md`](https://github.com/werkrbee/lineup/blob/main/STATUS.md)
is an assessment: layer status, components, what's not done, next steps.
[`PROJECT_STATE.md`](https://github.com/werkrbee/lineup/blob/main/PROJECT_STATE.md) is
what a fresh session needs to resume: live IDs, the current data, connector constraints,
next steps, and how to resume. The two overlap. Both list next steps, numbered
differently, and both describe the notification channels, so a change has to be made
twice and one copy drifts. The live IDs had to be redacted by hand before the repo went
public. Lessons that should outlive the project ("connector constraints, don't re-learn
these") sit in the middle of a snapshot that is rewritten every session. And nothing
records what the product spent: lineup's house rules say to state the estimated cost
before a mass send, but there is nowhere to write down the cost afterwards.

Harnesses each have their own memory (Claude Code keeps one fact per file with a short
description, for example), but that memory belongs to one harness on one machine. A
product's state has to be readable by any harness and by the people who own it.

## Three parts

The roadmap names the pattern "persistent state, results, usage ledger". Each part
answers a different question and changes at a different rate, so each gets its own
format. The rule across all three is one fact, one place.

**Persistent state** is what is true now: a snapshot (`STATE.md`) that is rewritten as
the product changes, plus memory entries for durable facts that outlive any one
snapshot. **Results** are what was done and checked, appended and never edited. The
**usage ledger** is what the work cost, also appended.

The assurance loop (P2.1, [`docs/assurance-loop.md`](../../docs/assurance-loop.md)) adds a
fourth file in the same style, the **audit log**: what every agent decided and did,
hash-chained so it can't be quietly edited.

## Where it lives

A product keeps its knowledge in one directory at its root:

```text
knowledge/
├── STATE.md            # persistent state: the current snapshot
├── memory/             # persistent state: durable facts, one per file
│   └── <slug>.md
├── results.jsonl       # results: append-only
├── ledger.jsonl        # usage ledger: append-only
└── audit.jsonl         # audit log: append-only and hash-chained
```

The product's `AGENTS.md` (or whatever instruction file its harnesses read) tells agents
to read `knowledge/STATE.md` at the start of a session, update it before ending one, and
append to the results and the ledger as they work. Files in the repo are the reference
backend, because they need nothing installed and every harness can read them. A service
can keep results and the ledger in a database instead, with the same record shape. The
hosted Patricia server keeps its ledger in this format on its own file share, outside any
repo. A product with frequent metered work can also keep the ledger outside the repo,
and the `ledger` field in `STATE.md` says where (below).

## Persistent state: `STATE.md`

Markdown with YAML frontmatter, the same pattern as `SKILL.md`, so people and agents
read the same file.

```markdown
---
name: lineup
summary: RSVP product for pickup sports; live MVP on Airtable.
status: live
updated: 2026-08-19
ledger: knowledge/ledger.jsonl
---

# lineup

## Summary
## Components
## References
## Open work
## How to resume
```

`name` (kebab-case), `summary` (one line), `status` (`planning`, `building`, `live`,
`paused` or `retired`) and `updated` are required. `ledger`
is optional: the ledger's path from the product root, or a description of the store that
holds it, defaulting to `knowledge/ledger.jsonl`. Dates throughout are ISO 8601:
`updated` is a date (`YYYY-MM-DD`).

The sections are fixed, all five are required, and they appear in this order.

**Summary** is a short assessment: what the product is and where it stands. **Components**
is a table with three columns, `Component`, `State` and `Note`: one row per part of the
product, its state (`built`, `live`, `partial` or `missing`) and a one-line note.
**References** is a table with three columns, `Reference`, `Kind` and `Where`: the live
things the product depends on (a database, a connector, an identity), what kind each is,
and where its value is found (an environment variable, a vault entry, or the call that
looks it up). **Open work** is the only list of next steps in the product: a numbered
list, most important first, with done items removed rather than struck through. **How to
resume** is a numbered list of the few steps a fresh session takes before it acts.

What doesn't go in `STATE.md`: history (that's results), durable lessons (that's
memory), and secrets (below). A snapshot that only holds the present stays short enough
to read at the start of every session.

## Persistent state: memory entries

A memory entry holds one durable fact that should outlive the current snapshot: a
decision, a constraint learned the hard way, a preference, or a pointer to something
external. Each is a Markdown file in `knowledge/memory/`, named after its slug.

```markdown
---
name: airtable-connector-limits
description: The Airtable connector can't add select options, set colors or themes.
type: constraint
updated: 2026-08-19
source: https://github.com/werkrbee/lineup/blob/main/PROJECT_STATE.md
---

The Airtable connector can't add or rename select options, set option colors, or set an
interface theme; `update_field` only edits formulas. Appearance changes are manual.

**Why:** lineup recorded it under "Connector constraints (don't re-learn these)", so the
next session doesn't spend time finding it again.
**How to apply:** plan schema colors and themes as manual UI steps, not agent steps.
```

The `description` is one line, written so an agent can decide from a directory listing
whether to read the entry. That listing is the index, so there is no separate index file
to keep in sync. All five frontmatter fields are required: `name` is the kebab-case slug
and equals the file name without `.md`, `description` is one line, `type` is one of the
four values, `updated` is a date (`YYYY-MM-DD`), and `source` records where the fact came
from (a URL, a path in the repo, or a short description such as a conversation).
Decisions and constraints end with why and how to apply, because a rule without its reason gets broken the first
time it is inconvenient. When a fact stops being true, the entry is changed or deleted,
not left to contradict a newer one.

Open proposals for a shared agent-memory format exist, but none is widely adopted yet.
The closest is the [Engram specification](https://plur.ai/spec.html) (v2.1, March 2026,
Apache-2.0). The spec calls itself storage-agnostic, and its reference implementation
keeps facts as YAML lists with one file per scope. Its per-fact fields map onto a memory
entry: `statement` is the body, `rationale` is the why, `temporal.learned_at` is
`updated`, and `source` is close (Engram's is an origin identifier, this one is usually a
URL). Two things don't map. Engram's reference storage keeps many facts in a file where
this format keeps one, so that a git diff or merge touches one fact.
And Engram's types (behavioral, terminological, procedural, architectural) classify what a
fact is about, where these (decision, constraint, preference, reference) classify what kind
of fact it is, so converting a type takes a person's judgment. Engram's retrieval and usage
tracking fields have no counterpart here, because a product's state file doesn't need them.

## Results: `results.jsonl`

One JSON object per line, appended when something is done and checked: a test run, a
delivery, a release, a workflow run, a manual check. Results are never edited. A
correction is a new result that names the one it supersedes.

```json
{"id": "2026-08-20-email-delivery", "at": "2026-08-20", "kind": "delivery", "subject": "lineup-notify email channel", "outcome": "passed", "summary": "A test email from the lineup identity was delivered.", "evidence": [{"kind": "link", "url": "https://github.com/werkrbee/lineup/blob/main/STATUS.md"}]}
```

`id`, `at`, `kind`, `subject`, `outcome`, `summary` and `evidence` are required, and
`supersedes` and `eval` are optional. `id` is unique within the file, and `at` is an ISO
8601 date or a date-time with a time zone. `kind` is `test`, `run`, `release`, `check`,
`delivery` or `eval`. `outcome` is `passed`, `failed` or `partial`. `evidence` is a
non-empty list of what backs the claim, each item an object with a `kind` and one field
that depends on it: `link` has `url`, `command` has `command` (what was run), `file` has
`path` (from the product root), `run` has `runId` (a workflows-hive run) and `note` has
`text`. `supersedes` names an earlier result's `id` when this one corrects it. A claim in
`STATE.md` that something works should be traceable to a result.

An `eval` result is an agent's trust evaluation (agents-hive's `scripts/trust_eval.py`),
and only it has an `eval` object: the `passport` evaluated and its `version`, the digest
of its `pins` as canonical JSON, the `suite` of cases, the `commit` it ran on and the
`deployment` it called when known, the `baseline` result it was compared with (`null` for
the first), its `runs` and its `findings`. The model a deployment serves isn't checked
yet, so the entry records the deployment, not a model; the pinned model is in `pins`. Each
run has the cases it `met`, how many `ran` of the suite's `of`, the ids it `missed` (a
wrong answer) and, when any got no answer because the provider failed, timed out or cut
the reply off, the ids that `errored`; its `usd` and, when timed, its `seconds`. A second
run is there only when the first drifted. `findings` lists any of `drift`,
`unconfirmed-miss`, `cost` and `not-run`, and decides `outcome`: `failed` for drift or an
eval that couldn't run, `partial` for the other two, `passed` for none. An eval with an
errored case, or one that ran fewer cases than its suite, is `not-run`.

## Usage ledger: `ledger.jsonl`

One JSON object per line for each piece of metered work, appended when the work ends.

```json
{"at": "2026-10-08T14:02:12Z", "runId": "run_01J9Z…", "step": "summarize", "capability": "summarize", "provider": "openai", "api": "chat-completions", "model": "…", "usd": 0.0071, "tokens": 2152, "tokenDetail": {"input": 1840, "output": 312}, "basis": "metered"}
```

`at` (an ISO 8601 date-time in UTC), `basis`, and at least one of `usd` and `tokens` are
required. `usd` is a non-negative number in US dollars and `tokens` a non-negative
integer, the same units and types as agents-hive contract budgets. `tokenDetail`
optionally splits `tokens` into `input` and `output` integers that add up to it. `basis`
is `metered` when the figures came from the provider and `estimated` when they were
computed, as the workflows-hive reference engine does today. `runId`, `step`,
`capability`, `provider`, `api` and `model` are optional strings. `runId` and `step` tie an
entry to a workflows-hive run record, whose per-step `cost` (`usd` and an integer
`tokens`) carries over to this entry's `usd` and `tokens` unchanged, so the engine will be
able to append one entry per step as it checkpoints. `capability` is the execution
contract the work ran under. `provider` is who made the model, in lower case (`openai`,
`deepseek`), `api` the wire API the call used (`chat-completions`, `messages`), and
`model` the model or deployment called. Older entries from the hosted Patricia server
have no `api`, and their `provider` is the vendor it was set up for, `openai` or
`anthropic`, which groups with the publisher. (Builds from 2026-10-15 to 2026-10-18,
between ai-hive PRs #84 and #90, wrote the API into `provider`; none was deployed.)

Totals are sums over the file, so a budget is checked by summing entries in its window.
That is how the hosted Patricia server enforces its monthly ceiling: it sums the month's
entries, reserves each review's worst-case cost before the review runs, and refuses new
reviews once spending and reservations reach the ceiling
([`servers/a2a/README.md`](../agents-hive/servers/a2a/README.md)).

## Audit log: `audit.jsonl`

One JSON object per line for every decision an agent's run makes, not only the actions
that ran, chained so that an edited, removed, inserted or reordered entry shows. The
design is in [`docs/assurance-loop.md`](../../docs/assurance-loop.md) (accepted, #124).

```json
{"seq": 41, "at": "2026-11-02T14:02:12Z", "prev": "sha256:9f2c…", "kind": "step.decided", "agent": {"passport": "barry", "version": 4, "sha256": "…"}, "runId": "run_01J9Z…", "step": "s7", "action": "message.send", "decision": "paused", "rules": ["organizer.blast"], "call": "sha256:…", "hash": "sha256:4be1…"}
```

`seq`, `at` (an ISO 8601 date-time in UTC), `prev`, `hash` and `kind` are required. `kind`
is one of `run.started`, `run.completed`, `run.failed`, `run.cancelled`, `run.expired`,
`step.decided`, `step.ran`, `step.failed`, `budget.refused`, `approval.answered`,
`escalation.raised`, `escalation.answered`, `drift.answered`, `turn.completed`,
`turn.failed`, `delegation`, `rollback`, `drift`, `eval.ran` and `eval.flagged`. A run's
entries carry its `runId`, and a step's or a turn's carry `step` or `turn`. `step.decided`
carries the `action` it decided, its `decision` (`allowed`, `paused` or `denied`) and the
`rules` that decided it; a step with no action, or one paused by its plan rather than its
policy, has one entry with no `action`. `approval.answered` carries `decision` (`approved`
or `denied`) and `by`, as `run.cancelled` carries `by`. Anything that names a review queue
item carries its ID as `item`: a paused `step.decided`, `approval.answered`,
`run.expired`, `escalation.raised`, `escalation.answered`, `drift`, `eval.flagged` and
`drift.answered`, which also carries `decision`. A person's answer carries `via`, how it
came (`cli`, `mcp` or `a2a`); `escalation.answered` and `drift.answered` require it, and
`approval.answered` has it from the review queue on. `agent` names the passport the run is
under, its version and its digest, and is left out for a run under none. `call` is the
digest of the exact call a step makes: its run, step, worker, resolved input and action.
So an entry can be matched to its run record, which keeps the call's arguments, the
model's output, message text and a denial's reason, none of which the log holds, nor an
escalation's question or answer. A trust evaluation writes `eval.ran`, with the `agent` it
evaluated and the `result` id in `results.jsonl` that records it, and for each finding it
sends the review queue, `drift` for drift and `eval.flagged` for a flag, each with the
`agent` and the `item`. A `rollback` carries `by`, `via` and `record`, the digest of a
rollback record that keeps the reason, which the log never holds. A run's rollback names
the `runId` and the `step` it went back to, and its record is in the run record, under
`rollbacks`. An agent's rollback to an earlier passport version (agents-hive's `deploy.sh
--rollback`) names the `agent` it went back to, and its record is a JSON file in
`rollbacks/` beside the log, named by the digest's hex digits. A `delegation` is written
in the delegator's run, with the `step` that delegated, and names both passports: the
delegator's as `agent` and the delegate's as `delegate`, each with its version and digest.
`grant` is the digest of the narrowed grant the delegate runs under, and `context` lists
the digest of each item passed to it, an empty list when nothing was, never the items
themselves. A `budget.refused` names the `step` or the `turn` that ran past the budget.

**Hash rules.** Each `hash` is `sha256:` followed by the SHA-256 of the entry without
`hash`, serialized as canonical JSON: keys sorted, no insignificant whitespace, UTF-8,
numbers as Python's `json` writes them. `prev` is the previous entry's `hash`, and the
first entry's `prev` is `sha256:` followed by 64 zeros. `seq` counts from 1 with no gaps.

**Anchors.** A chain can't show that its last entries were cut off, so each
workflows-hive run record keeps, under `audit`, the `seq` and `hash` of the last entry
written for its run. The engine writes an entry before the record that follows it, so a
record never points past the log.

**One writer.** The workflows-hive engine writes the log, the review queue's answers
included, through `append` in `scripts/check_audit.py`, which takes an exclusive lock,
numbers and chains the entry, and flushes it to disk before returning. The writer refuses
an entry that doesn't fit the format, and a log whose last line is incomplete.

**What it can't stop.** On one machine, an agent that can write the directory holding the
log can rewrite all of it and recompute every hash, and its run records' anchors with it.
The chain shows tampering by anyone who didn't rewrite it whole; it isn't a lock. The
Charter forbids it, and its policy prohibits `audit.edit` and `audit.delete`, but the
approval policy can't tell a write to the log from any other `fs.write` or `shell.exec`.
So a local log is evidence, not a guarantee. The strong case is a hosted deployment that
also writes each entry to storage the agent can't reach and nobody can rewrite, such as
an immutable append blob.

## What the checker holds you to

`scripts/check_knowledge.py` checks everything above, and a few rules this note implies
but doesn't spell out. Frontmatter is plain `key: value` lines, with no YAML lists, block
scalars or comments, and an optional pair of quotes around a value. Keys and fields not
named above are rejected, in frontmatter and in JSON lines alike, and so is any file
outside the layout. `STATE.md` has exactly one `# ` heading, the product's name, and its
Open work can be the single line `None.` when there is nothing left. An evidence item
holds its `kind` and its one field, nothing else. `memory/`, `results.jsonl` and
`ledger.jsonl` can be absent until there is something to put in them, and so can
`audit.jsonl`. The checker checks an audit log's format and chain, and reports the first
place the chain breaks; `scripts/check_audit.py` also checks a log's end against the run
records.

## Secrets and personal data

Nothing in `knowledge/` holds a secret. A reference names where its value lives (an
environment variable, a vault entry, or the connector call that looks it up) and never
the value. lineup's `PROJECT_STATE.md` redacted its base, table and field IDs by hand
before the repo went public; under this format those IDs are references from the start,
with "restore from the connected Airtable" as the way to find them. Personal data (names,
phone numbers, emails) stays in the product's own data store and is never copied into
state, results, the ledger or the audit log. The log names a person only by `by`, the
opaque identifier their product gives them, never a name or an email, and the checker
refuses one with a space or the shape of an email address.

## How lineup maps

| lineup today | knowledge-hive |
|---|---|
| `STATUS.md` assessment and layer status | `STATE.md` Summary and Components |
| `PROJECT_STATE.md` live IDs | `STATE.md` References, as references not values |
| `PROJECT_STATE.md` current data | stays in Airtable; `STATE.md` points at it |
| "Connector constraints (don't re-learn these)" | memory entries of type `constraint` |
| Next steps in both files | `STATE.md` Open work, once |
| The email channel, tested and delivered on 2026-08-20 | a result |
| Mass sends: "state the message, recipient count, and estimated cost first" | the estimate is shown at approval; the actual cost is a ledger entry |
| "How to resume" | `STATE.md` How to resume |

Moving lineup onto this format is a follow-up in the lineup repo.

## Considered

**Keep two files.** A status file and a resume file each make sense alone, but together
they duplicate next steps and descriptions. One snapshot with fixed sections removes the
overlap.

**One JSON state file.** Easier to validate, harder for the people who own the product to
read and edit. Markdown with frontmatter keeps the structured parts (name, status,
updated) machine-checkable and the rest readable, as `SKILL.md` already does.

**A database first.** A service needs one, but an agent-run app built in a harness has
none, and the House installs with nothing but files. Files are the reference backend; a
store with the same record shapes is a drop-in for services.

## Out of scope here

An MCP server that exposes a product's knowledge to harnesses, writes from the
workflows-hive engine to the ledger, and the hosted ceiling's enforcement come later,
against this same format.
