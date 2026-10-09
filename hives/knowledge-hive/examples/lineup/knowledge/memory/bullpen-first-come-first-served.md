---
name: bullpen-first-come-first-served
description: Open slots go to the whole bullpen at once, and the first valid claim wins.
type: decision
updated: 2026-08-19
source: https://github.com/werkrbee/lineup/blob/main/skills/lineup-bullpen/SKILL.md
---

The bullpen replaced the ordered waitlist. When a slot opens it is offered to the whole
opted-in bullpen at once, and the first valid claim wins. A claim is accepted only while
`In < Capacity`, so the event can't overfill. An ordered waitlist is a documented
optional mode, off by default.

**Why:** in pickup sports availability changes by the minute, so the fastest yes should
fill the game.
**How to apply:** recheck the live headcount on every claim, never bump an `In` player,
and use the RSVP `Position` field only if a group turns the ordered mode on.
