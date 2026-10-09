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
each. [`templates/knowledge/`](templates/knowledge) is a starting point to copy,
[`examples/lineup/knowledge/`](examples/lineup/knowledge) is a worked example, and
`scripts/check_knowledge.py` checks a product's directory against the format.

## The parts

| Part | Where, in a product | What it holds |
|------|---------------------|---------------|
| Persistent state | `knowledge/STATE.md` | Summary, components, references, the one list of open work, how to resume |
| Persistent state | `knowledge/memory/<slug>.md` | One durable fact each: a decision, constraint, preference or reference |
| Results | `knowledge/results.jsonl` | Append-only records of what was done and checked, with evidence |
| Usage ledger | `knowledge/ledger.jsonl` | Append-only cost and token entries, tied to workflows-hive runs |

Nothing in `knowledge/` holds a secret: references say where a value lives, never the
value.

## Start a product's knowledge

```bash
git clone https://github.com/werkrbee/ai-hive.git
cp -R ai-hive/hives/knowledge-hive/templates/knowledge /path/to/your/product/

# Fill in STATE.md and replace memory/example-decision.md, then check it
python3 ai-hive/hives/knowledge-hive/scripts/check_knowledge.py /path/to/your/product/knowledge
```

Then add a line to the product's `AGENTS.md`: read `knowledge/STATE.md` at the start of a
session, update it before ending one, and append to `results.jsonl` and `ledger.jsonl` as
work is done and checked.

The checker needs Python 3 and nothing else. It checks `STATE.md` (frontmatter, the five
sections in order, the two tables and the numbered lists), every memory entry,
`results.jsonl` and `ledger.jsonl`. It also scans every file for API keys, tokens,
private keys, email addresses and phone numbers, which must never be written there. That
scan is a heuristic: it catches the common shapes, not every secret. The rules it holds
you to beyond the format are listed in [`DESIGN.md`](DESIGN.md#what-the-checker-holds-you-to). With no arguments it
checks the template and the examples, and CI runs it that way.

## Worked example: lineup

[`examples/lineup/knowledge/`](examples/lineup/knowledge) is lineup's
[`STATUS.md`](https://github.com/werkrbee/lineup/blob/main/STATUS.md) and
[`PROJECT_STATE.md`](https://github.com/werkrbee/lineup/blob/main/PROJECT_STATE.md)
converted to this format, as of the 2026-08-19 snapshot. It is an example, not lineup's
live state. The two files' next steps become one Open work list. The live IDs become
references that say how to look each one up. The connector constraints, the
decisions behind the bullpen and the Inkbox switch, and a pointer to the ACS and WhatsApp
design become seven memory entries, and the tested email channel becomes a result. The member roster stays in Airtable. lineup
recorded no costs, so its ledger is empty; the first entries will come from metered work.

## Repository layout

```text
knowledge-hive/
├── adapters/                     # WHERE it's read — harness taxonomy & overrides
│   ├── claude-code/  cursor/  codex/  gemini-cli/  goose/  opencode/
│   ├── kiro/  databricks-genie-code/  snowflake-cortex-code/
│   └── github-copilot/
│       └── scout/                # sub-harness (child of GitHub Copilot)
├── templates/
│   └── knowledge/                # copy into a product: STATE.md, memory/, results, ledger
├── examples/
│   └── lineup/knowledge/         # lineup's state files, converted
├── scripts/
│   └── check_knowledge.py        # check a knowledge/ directory against the format
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
