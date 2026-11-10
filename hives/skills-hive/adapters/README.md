# Harness adapters

This is the **harness axis** — the taxonomy of *where* skills run, and the home for
any override tied to a specific harness. Portable skills themselves live in
[`skills/`](../skills/) and install unchanged into any harness that reads `SKILL.md`.

Each harness has a folder here; a **sub-harness** nests one level deeper:

```text
adapters/
  claude-code/
  cursor/
  codex/
  gemini-cli/
  goose/
  opencode/                 # open-source, model-agnostic peer harness
  devin-desktop/            # Cognition — formerly Windsurf
  kiro/                     # AWS — spec-driven agent (replaced Amazon Q Developer)
  cline/                    # open-source agent in VS Code
  databricks-genie-code/    # data workspace
  snowflake-cortex-code/    # data workspace
  github-copilot/
```

The list is the House's harness registry, [`harnesses.json`](../../../harnesses.json),
which also holds each harness's category, tier and install paths; CI checks that
every hive's `adapters/` matches it (`python3 scripts/harnesses.py check`).

Folder names follow the **product name** in kebab-case (e.g. `claude-code`,
`github-copilot`, `databricks-genie-code`) so the convention is consistent across
the fleet.

Add a per-skill subfolder only when a skill needs materially different
instructions on that harness, e.g. `adapters/cursor/barry/` for Cursor-only
extensions. Until then the folders stand as the canonical harness list.

**Barry** ships as a single portable, harness-agnostic skill under
`skills/barry/`. His logical agent roster lives in
[`skills/barry/references/fleet.md`](../skills/barry/references/fleet.md), and his
harness-by-harness delegation notes live in [`skills/barry/references/harnesses/`](../skills/barry/references/harnesses/).
Only create an adapter here when behavior must actually diverge for a harness.
