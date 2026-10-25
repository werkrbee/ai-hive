<p align="center">
  <img src="assets/workflows-hive-logo.svg" alt="workflows-hive — durable, resumable workflows, one hive, every harness" width="620">
</p>

# workflows-hive

> **Durable, resumable workflows.** Multi-step recipes written once as portable plans,
> run by a replaceable engine, and exposed to every harness through MCP Tasks.

*Part of the **[ai-hive](https://github.com/werkrbee/ai-hive)** family — werkrbee's House of Hives (skills · rules · tools · agents · and more).*

The **orchestration** layer of the House of Hives. Barry decomposes and coordinates work
at runtime; workflows-hive is the saved version of that work. A workflow is a plan of
steps that checkpoints as it runs, so it can survive a restart, pause for approval, and
report its result and its cost when it finishes.

[`DESIGN.md`](DESIGN.md) records the contract: MCP Tasks as the interface, the engine
decision (Temporal evaluated), and the shape of the persisted plan and checkpoint. The
reference engine, `scripts/run.py`, runs plans against it. The MCP Tasks server comes
later.

## Workflows

| Workflow | What it does |
|----------|--------------|
| [**word-count**](workflows/word-count/workflow.json) | Read a text file, then count its words and lines (the resumable spike) |
| [**approved-word-count**](workflows/approved-word-count/workflow.json) | The same, with the count waiting for a human's approval |
| [**budgeted-word-count**](workflows/budgeted-word-count/workflow.json) | The same, with each step held to a budget |

## Repository layout

```text
workflows-hive/
├── workflows/                    # WHAT workflows exist — portable plans
│   ├── word-count/workflow.json
│   ├── approved-word-count/workflow.json
│   └── budgeted-word-count/workflow.json
├── adapters/                     # WHERE they run — harness taxonomy & overrides
│   ├── claude-code/  cursor/  codex/  gemini-cli/  goose/  opencode/
│   ├── kiro/  databricks-genie-code/  snowflake-cortex-code/
│   └── github-copilot/
│       └── scout/                # sub-harness (child of GitHub Copilot)
├── scripts/
│   └── run.py                    # reference engine: run, checkpoint, resume, approve, budget
├── tests/
│   └── read-only-policy/         # a test approval policy for the engine's checks
├── DESIGN.md                     # the workflow contract and engine decision
├── LICENSE
└── README.md
```

A workflow reaches a harness as an MCP server, so most harnesses need nothing beyond
their usual MCP config. The `adapters/` tree holds per-harness wiring if a harness ever
needs it, the same taxonomy every other hive uses.

## Run a workflow

The reference engine needs Python 3 and nothing else. It writes one run record per run to
`~/.local/state/workflows-hive/runs` (change it with `--state-dir`), after every step.

```bash
git clone https://github.com/werkrbee/ai-hive.git
cd ai-hive/hives/workflows-hive

# Run both steps
python3 scripts/run.py start word-count --input path=README.md

# Stop the process right after step 1 checkpoints, then pick the run back up
python3 scripts/run.py start word-count --input path=README.md --crash-after read
python3 scripts/run.py resume <run-id>     # skips step 1, runs step 2

python3 scripts/run.py status <run-id>
```

`--crash-after` exits right after a step's checkpoint is written, to stand in for a
crash or a deploy. A process killed in the middle of a step resumes by running that step
again with the same idempotency key. Every run ends by printing its result and its
cost. The demo workers don't call a model, so they meter an estimated token count at a
simulated price.

A step marked `approval: true` pauses the run before it, in `input_required`, and nothing
runs it until a human answers. `approve` continues the run from that step; `deny` fails
the run, with the reason as its error, and the step never runs. The record keeps who
answered and when (`--by`, your user name by default). `resume` never answers for you: a
run restarted while paused stays paused.

```bash
python3 scripts/run.py start approved-word-count --input path=README.md   # pauses before count
python3 scripts/run.py approve <run-id>                                   # runs count, finishes
python3 scripts/run.py deny <run-id> --reason "not this file"             # or fails the run
```

The commands exit 0 when the run completed, 2 when it's waiting for approval, and 1
otherwise.

A step's `budget` caps what it may spend, in `usd`, `tokens` and `seconds`, each
optional, and the engine passes it to the worker as its cap. A step that runs past its
`seconds` is stopped. A step that reports more `usd` or `tokens` than its cap fails the
run with the reason, and what it spent is still recorded and counted in the run's cost.
When the worker's capability has an execution contract in agents-hive, a step budget
above the contract's per-call budget is refused before the run starts. `--workflows-dir`
and `--contracts-dir` point the engine at other plans and contracts.

```bash
python3 scripts/run.py start budgeted-word-count --input path=README.md
```

A step can list the `actions` it takes, and rules-hive's
[approval policy](../rules-hive/README.md#approval-policy) decides each one just before
the step runs. A prohibited action fails the run without running the step, even after
approval. An action an open mandate allows runs on its own. One a closed mandate gates
pauses the run, and `pending` shows the mandates and what the approval request must
present. An action no mandate allows is denied. `approval: true` still forces a pause,
and `approval: false` can't skip one the policy requires. The policy is the Charter's
unless `start --policy` names a product policy in this repo, and the run keeps it.
Facts compare strictly, and an `--input` value is a string, so a fact that must be
`true` comes from the plan or an earlier step's output.

```json
{ "id": "notify", "worker": "send-message", "input": { "text": "${steps.draft.output}" },
  "actions": [{ "action": "message.send",
                "scope": { "channel": "sms", "audience": "group" },
                "facts": { "recipient.notifyOptIn": true } }] }
```

```bash
python3 scripts/run.py start <workflow> --policy ../rules-hive/examples/lineup-etiquette/policy.json
```

## License

MIT — see [LICENSE](LICENSE).
