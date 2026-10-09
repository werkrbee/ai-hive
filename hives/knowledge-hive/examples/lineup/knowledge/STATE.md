---
name: lineup
summary: RSVP product for pickup sports on the SportsCopilot platform; a live MVP on Airtable.
status: live
updated: 2026-08-19
---

# lineup

## Summary

lineup organizes pickup sports (pickleball first): groups, members, events and the RSVP
loop. It is an agent-run app on the House of Hives: Barry orchestrates and Patricia
governs. It is a fully built, live-running MVP. All six skills, governance, tools, brand
and a working Airtable backend are in place. What's outstanding (real SMS sending,
dashboard theming and the GitHub push) doesn't block it.

## Components

| Component | State | Note |
|-----------|-------|------|
| Skills | built | Six `lineup-*` skills: group, member, event, rsvp, bullpen, notify. |
| Governance | built | `rules/lineup-etiquette/AGENTS.md`, under the Queen Bee's Charter. |
| Data tools | live | Airtable MCP connector. |
| Notifications | partial | Inkbox: email is live; iMessage is provisioning; SMS needs a number and A2P registration. |
| Agents | built | Barry and Patricia, from the House. |
| Runtime | live | The SportsCopilot Airtable base and its dashboard interface. |
| Brand | built | Logo, icon and favicon set; the README brand section isn't written. |

## References

| Reference | Kind | Where |
|-----------|------|-------|
| SportsCopilot Airtable base | database | Look it up through the Airtable connector: `list_bases`, then `list_tables_for_base`. |
| Airtable connector | connector | The harness's connector settings. |
| SportsCopilot Dashboard interface | dashboard | In the Airtable base, through `list_pages_for_base`. |
| Inkbox identity `lineup` | identity | Look it up through the Inkbox connector, by the identity name `lineup`. |
| Inkbox connector | connector | The harness's connector settings. |

## Open work

1. Enable real SMS through Inkbox (a number and A2P registration), then wire `lineup-notify` to it.
2. Theme the dashboard in honey and ink. This is a manual step in the Airtable UI.
3. Add a brand section to the README.
4. Add a date filter or an Events page to the dashboard, so "tonight" means tonight once there is more than one event.
5. Reset the demo RSVPs to the real game if Monday's game is live.
6. Convert the Airtable cross-references from single-line text to linked records.
7. Evaluate Azure Communication Services and WhatsApp as the production channel (`docs/acs-whatsapp-backend.md`).
8. Build the roadmap skills: checkin, availability, matchmaking, standings, payments, venue, digest.
9. Push the repo to GitHub under werkrbee.

## How to resume

1. Read this file, `README.md` and `data/airtable-schema.md`, then list `memory/`.
2. Treat the Airtable base as the source of truth for groups, members, events and RSVPs.
3. Restore the base, table and record IDs from the connected Airtable before querying.
