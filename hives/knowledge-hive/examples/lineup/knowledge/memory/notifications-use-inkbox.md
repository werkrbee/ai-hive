---
name: notifications-use-inkbox
description: Notifications go through Inkbox, which replaced a Twilio placeholder.
type: decision
updated: 2026-08-19
source: https://github.com/werkrbee/lineup/blob/main/PROJECT_STATE.md
---

Inkbox is lineup's notification connector, routing iMessage, then SMS, then email. It
replaced the Twilio placeholder.

**Why:** Twilio's MCP server is search-only, so it can't send.
**How to apply:** wire notification work to Inkbox; don't reintroduce Twilio through its
MCP server.
