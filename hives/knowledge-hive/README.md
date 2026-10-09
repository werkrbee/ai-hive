# knowledge-hive

> **Operational state, written down once.** What a product knows about itself between
> sessions — its current state, what it has done, and what it has spent — in plain files
> every harness can read.

*Part of the **[ai-hive](https://github.com/werkrbee/ai-hive)** family — werkrbee's House of Hives (skills · rules · tools · agents · and more).*

The **state** layer of the House of Hives. Apps built on the House each hand-rolled a
status file, a resume file and some memory, and those files overlapped, drifted and
needed secrets redacted by hand. knowledge-hive standardizes that pattern into three
parts: **persistent state** (a current snapshot plus durable memory entries),
**results** (what was done and checked) and a **usage ledger** (what the work cost).

[`DESIGN.md`](DESIGN.md) defines where each part lives in a product and the format of
each. It is in design for P1: templates, a worked example and a validator come next.

## The parts

| Part | Where, in a product | What it holds |
|------|---------------------|---------------|
| Persistent state | `knowledge/STATE.md` | Summary, components, references, the one list of open work, how to resume |
| Persistent state | `knowledge/memory/<slug>.md` | One durable fact each: a decision, constraint, preference or reference |
| Results | `knowledge/results.jsonl` | Append-only records of what was done and checked, with evidence |
| Usage ledger | `knowledge/ledger.jsonl` | Append-only cost and token entries, tied to workflows-hive runs |

Nothing in `knowledge/` holds a secret: references say where a value lives, never the
value.

## Repository layout

```text
knowledge-hive/
├── adapters/                     # WHERE it's read — harness taxonomy & overrides
│   ├── claude-code/  cursor/  codex/  gemini-cli/  goose/  opencode/
│   ├── kiro/  databricks-genie-code/  snowflake-cortex-code/
│   └── github-copilot/
│       └── scout/                # sub-harness (child of GitHub Copilot)
├── DESIGN.md                     # the format of each part
├── LICENSE
└── README.md
```

A product's instruction file (`AGENTS.md` or its harness equivalent) points agents at
`knowledge/STATE.md`, so most harnesses need nothing more. The `adapters/` tree holds
per-harness wiring if one ever needs it, such as mirroring memory entries into a
harness's own memory, the same taxonomy every other hive uses.

## Relationship to the other hives

- **workflows-hive** writes a run record per run. Its per-step cost is designed to become
  ledger entries, and a finished run can be recorded as a result; the engine doesn't
  write either yet.
- **agents-hive** execution contracts set per-call budgets. The ledger is designed to be
  where spending against them is summed, such as the hosted Patricia server's monthly
  ceiling.
- **rules-hive** keeps the Charter. Its rules to checkpoint long work and to verify before
  calling something done need somewhere to write things down, and this hive is that place.

## License

MIT — see [LICENSE](LICENSE).
