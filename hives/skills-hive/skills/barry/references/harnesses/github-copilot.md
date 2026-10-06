# Barry on GitHub Copilot

**Skills load from:** `~/.copilot/skills/` (CLI, global) and `.github/skills/`
(repo). The same skills work across GitHub Copilot in VS Code, the CLI, and the
cloud agent.

**Delegation:** Copilot defines custom agents (persona + tools) and skills
(focused instructions). Map Barry's roles to Copilot's agent + skill model:

| Barry role | GitHub Copilot equivalent |
|------------|---------------------------|
| explore | a search-oriented custom agent |
| generalPurpose | the default coding agent |
| shell | Copilot CLI / terminal tool |
| code-review | a review agent / skill |
| security-review | a security review skill |

**Models:** only when asked; use the model options Copilot exposes.

---

## Sub-harness: Scout (Microsoft)

Scout runs **on top of the GitHub Copilot harness**, which is why it lives under
this file rather than as a peer harness.

- **Skills load from:** `%USERPROFILE%\.scout\skills\` (Windows).
- **Gate:** skill loading requires `"loadCopilotCliSkills": true` in
  `%USERPROFILE%\.scout\m-settings.json`.
- **Install:** use `scripts/install.ps1` — it creates directory junctions into
  `.scout\skills` and sets the gate flag.
- **Behavior:** Barry delegates exactly as on GitHub Copilot; Scout is the
  Windows delivery/runtime surface, not a different delegation model.

Note the distinction from Microsoft's other AI surfaces: **Microsoft Foundry
agents** and **Copilot Studio** can run these same `SKILL.md` files but load them
from a project/deployment `skills/` folder (you publish, not junction), and
**Microsoft 365 Copilot** uses declarative agents rather than file-based skills.
