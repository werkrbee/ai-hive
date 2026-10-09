---
name: inkbox-imessage-consent-gate
description: Inkbox can only iMessage someone after they have texted lineup first.
type: constraint
updated: 2026-08-19
source: https://github.com/werkrbee/lineup/blob/main/skills/lineup-notify/SKILL.md
---

iMessage through Inkbox is consent-gated: a recipient must text `lineup` first, and
until they do Inkbox returns `imessage_awaiting_inbound`. That first inbound text is
their opt-in. It can't be tested from the operator's own phone.

**Why:** a send to someone who hasn't texted first fails, and testing from the operator
phone looks like a failure when it isn't one.
**How to apply:** fall back to SMS when it's available, or flag the player for an opt-in
nudge; test with a real recipient who has opted in.
