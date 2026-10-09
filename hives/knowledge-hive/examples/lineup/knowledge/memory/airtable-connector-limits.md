---
name: airtable-connector-limits
description: The Airtable connector can't add select options, set option colors or set an interface theme.
type: constraint
updated: 2026-08-19
source: https://github.com/werkrbee/lineup/blob/main/PROJECT_STATE.md
---

The Airtable connector can't add or rename select options, set option colors, or set an
interface theme; `update_field` only edits formulas. Appearance and schema-color changes
are manual steps in the Airtable UI.

**Why:** lineup recorded it under "Connector constraints (don't re-learn these)", so the
next session doesn't spend time finding it again.
**How to apply:** plan colors, themes and new select options as manual UI steps for the
organizer, not as agent steps.
