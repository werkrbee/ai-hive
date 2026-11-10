# Barry on Scout (Microsoft)

Scout is on the watch list (`harnesses.json`). It is in private and public preview and is
due to be renamed **Autopilot** at Microsoft Ignite in November 2026. Which harness it
belongs to isn't confirmed: it has run on the GitHub Copilot harness, but it is likely to
become part of Microsoft 365 Copilot, beside Home (chat and cowork) and Code. Treat it as
its own harness until Microsoft says otherwise, and update this file and the registry
when it does.

- **Skills load from:** `%USERPROFILE%\.scout\skills\` (Windows).
- **Gate:** skill loading requires `"loadCopilotCliSkills": true` in
  `%USERPROFILE%\.scout\m-settings.json`.
- **Install:** use `scripts/install.ps1` — it creates directory junctions into
  `.scout\skills` and sets the gate flag.
- **Behavior:** Barry delegates as on GitHub Copilot today; recheck once Autopilot's
  delegation model is published.
