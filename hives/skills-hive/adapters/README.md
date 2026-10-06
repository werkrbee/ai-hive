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
  kiro/                     # AWS — spec-driven agent (replaced Amazon Q Developer)
  databricks-genie-code/    # data / analytics (workspace-based)
  snowflake-cortex-code/    # data / analytics (workspace-based)
  github-copilot/
    scout/                  # sub-harness: runs on the GitHub Copilot harness (Windows)
```

Folder names follow the **product name** in kebab-case (e.g. `claude-code`,
`github-copilot`, `databricks-genie-code`) so the convention is consistent across
the fleet.

Add a per-skill subfolder only when a skill needs materially different
instructions on that harness, e.g. `adapters/cursor/barry/` for Cursor-only
extensions. Until then the folders stand as the canonical harness list.

**Barry** ships as a single portable, harness-agnostic skill under
`skills/barry/`. His logical agent roster lives in
[`skills/barry/references/fleet.md`](../skills/barry/references/fleet.md), and his
harness-by-harness delegation notes (including how Scout maps onto GitHub Copilot)
live in [`skills/barry/references/harnesses/`](../skills/barry/references/harnesses/).
Only create an adapter here when behavior must actually diverge for a harness.
