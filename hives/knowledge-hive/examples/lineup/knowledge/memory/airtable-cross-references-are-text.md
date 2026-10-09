---
name: airtable-cross-references-are-text
description: Group, event and member cross-references are single-line text, not linked records.
type: constraint
updated: 2026-08-19
source: https://github.com/werkrbee/lineup/blob/main/PROJECT_STATE.md
---

The Group, Event and Member cross-references in the Airtable base are single-line text
fields, not linked records, because the connector couldn't create linked-record fields
when the base was created.

**Why:** the connector couldn't create linked-record fields when the base was created,
so there are no links to follow.
**How to apply:** match cross-references by their text value until they are converted
(an open work item).
