<p align="center">
  <img src="assets/skills-hive-logo.svg" alt="skills-hive — portable agent skills, one hive, every harness" width="620">
</p>

# skills-hive

> **Harness-agnostic by design.** Skills here are portable `SKILL.md` files with
> no lock-in to any one agent — the same skill runs across Claude Code, Codex,
> Gemini CLI, GitHub Copilot, Cursor, Goose, OpenCode, Kiro,
> Databricks Genie Code, and Snowflake Cortex Code.

*Part of the **[ai-hive](https://github.com/werkrbee/ai-hive)** family — werkrbee's House of Hives (skills · rules · tools · agents · and more).*

Personal agent skills for [werkrbee](https://github.com/werkrbee), packaged for **multiple AI coding harnesses** using the open [Agent Skills](https://agentskills.io) standard (`SKILL.md`).

One repo. Install into Cursor, Claude Code, Codex, GitHub Copilot, Gemini CLI, Goose, Kiro, Databricks Genie Code, Snowflake Cortex Code, and more.

## Skills

| Skill | Description |
|-------|-------------|
| [**barry**](skills/barry/) | The King Bee — chief of staff who decomposes goals, delegates to a fleet of agents, and synthesizes executive summaries |
| [**patricia**](skills/patricia/) | The Queen Bee — governance guardian who reviews plans and actions against the charter and gates consequential operations |

## Harnesses

<p align="center">
  <img src="assets/skills-hive-fleet.svg" alt="skills-hive fleet — Barry at the center of the ten pro-code harnesses, in rank order" width="380">
</p>

skills-hive installs into every major agent harness that reads the `SKILL.md`
standard. Barry is the king; the art's cells are the ten pro-code harnesses in
`harnesses.json`'s rank order, and the installers reach these:

- **Frontier labs** — Claude Code (Anthropic), Codex (OpenAI), Gemini CLI (Google)
- **Hyperscalers** — GitHub Copilot (Microsoft), Kiro (AWS)
- **Data & analytics** — Databricks Genie Code, Snowflake Cortex Code
- **Open source & independent** — Cursor, Devin Desktop (Cognition), Cline,
  Goose, OpenCode

Microsoft 365 Copilot is a separate harness from GitHub Copilot, with its own
concerns: Home (chat and cowork), Autopilot and Code. It has no skills folder to
install into; Autopilot takes a skill as an uploaded `SKILL.md` folder or ZIP.

See [Harness paths](#harness-paths) for exact install locations per harness.

## Repository layout

```text
skills-hive/
├── skills/                       # WHAT agents do — portable skills (source of truth)
│   └── barry/                    # king: the primary orchestrator skill
│       ├── SKILL.md
│       └── references/
│           ├── fleet.md          # the agent roster (logical roles)
│           └── harnesses/        # Barry's per-harness delegation notes
│               ├── claude-code.md
│               ├── cursor.md
│               ├── codex.md
│               ├── gemini-cli.md
│               ├── devin-desktop.md
│               ├── cline.md
│               ├── goose.md
│               ├── opencode.md
│               ├── kiro.md
│               ├── databricks-genie-code.md
│               ├── snowflake-cortex-code.md
│               ├── github-copilot.md
│               ├── m365-copilot.md     # watch list: Autopilot, by upload
│               └── copilot-studio.md   # low-code: Patricia's hosted review over MCP
├── adapters/                     # WHERE skills run — harness taxonomy & overrides
│   ├── README.md
│   ├── claude-code/
│   ├── cursor/
│   ├── codex/
│   ├── gemini-cli/
│   ├── goose/
│   ├── opencode/                 # open-source peer harness
│   ├── devin-desktop/            # Cognition (formerly Windsurf)
│   ├── kiro/                     # AWS (spec-driven; replaced Amazon Q)
│   ├── cline/                    # open-source VS Code agent
│   ├── databricks-genie-code/    # data workspace
│   ├── snowflake-cortex-code/    # data workspace
│   └── github-copilot/
├── scripts/
│   ├── install.sh                # macOS/Linux: copy skills into harness dirs
│   └── install.ps1               # Windows: junctions
├── LICENSE
└── README.md
```

The repo separates two axes so the "king orchestrator" idea scales cleanly:

- **`skills/` is *what* agents do.** Each skill (Barry, and future ones) is a
  portable `SKILL.md` folder. It stays flat and harness-neutral so `install.sh`
  can copy `skills/barry/` into any harness without dragging platform-specific
  material along. Barry is the **king** — the orchestrator — and his per-harness
  delegation notes live *with* him as reference files under
  `skills/barry/references/harnesses/<harness>.md`, loaded on demand.
- **`adapters/` is *where* skills run.** This is the harness taxonomy and the home
  for any behavior override tied to a specific harness:
  `adapters/<harness>/`, with a **sub-harness** nested one level deeper as
  `adapters/<harness>/<sub-harness>/`.

Why not nest harness folders inside `skills/barry/`? Because installing Barry
copies that whole folder into each harness's skills dir — nested harness
directories would pollute every install, and they'd lock the harness list inside
one skill instead of sharing it across all of them.

## Install

### Option 1 — skills CLI (recommended)

Requires [Node.js](https://nodejs.org/). Installs straight from this hive's folder in ai-hive on GitHub:

```bash
# All skills → Cursor (global)
npx skills add https://github.com/werkrbee/ai-hive/tree/main/hives/skills-hive --global -a cursor -y

# Barry only → multiple harnesses
npx skills add https://github.com/werkrbee/ai-hive/tree/main/hives/skills-hive --global \
  -a cursor -a claude-code -a codex -a github-copilot -a goose -a gemini-cli \
  -a opencode -a kiro \
  --skill barry -y

# List the skills without installing
npx skills add https://github.com/werkrbee/ai-hive/tree/main/hives/skills-hive --list
```

For Cursor, use this option (`-a cursor`) or Option 2 (`--harness cursor`). Cursor
imports skills from GitHub only as plugins published through a marketplace, and this
hive doesn't publish one.

### Option 2 — install script (macOS / Linux)

```bash
git clone https://github.com/werkrbee/ai-hive.git
cd ai-hive/hives/skills-hive
chmod +x scripts/install.sh

# Barry → global Cursor skills dir
./scripts/install.sh --global --harness cursor --skill barry

# All skills → Cursor + Claude Code (global)
./scripts/install.sh --global --all --harness cursor --harness claude-code
```

The script is written for macOS's default Bash 3.2 (no associative arrays). It reads
the House's harness registry (`harnesses.json`) with `python3`, which ships with git on
macOS and with most Linux distributions.

### Option 3 — install script (Windows)

Windows harnesses use directory **junctions** instead of copies/symlinks — they
match how Copilot already links skills and need no Admin or Developer Mode.

```powershell
.\scripts\install.ps1                 # link into every installed Windows harness
.\scripts\install.ps1 -DryRun         # preview only
.\scripts\install.ps1 -Only cursor    # just Cursor
.\scripts\install.ps1 -Force          # replace an existing target
```

### Option 4 — manual copy

```bash
cp -R skills/barry ~/.cursor/skills/barry
```

## Harness paths

| Harness | Global path | Project path |
|---------|-------------|--------------|
| Cursor | `~/.cursor/skills/` | `.cursor/skills/` or `.agents/skills/` |
| Claude Code | `~/.claude/skills/` | `.claude/skills/` |
| OpenAI Codex | `~/.agents/skills/` | `.agents/skills/` |
| GitHub Copilot | `~/.copilot/skills/` | `.agents/skills/` |
| Gemini CLI and Antigravity | `~/.gemini/skills/` | `.agents/skills/` |
| Devin Desktop | `~/.config/devin/skills/` | `.devin/skills/` |
| Cline | `~/.cline/skills/` | `.cline/skills/` |
| Goose | `~/.agents/skills/` | `.agents/skills/` |
| OpenCode | `~/.config/opencode/skills/` | `.opencode/skills/` |
| Kiro (AWS) | `~/.kiro/skills/` | `.kiro/skills/` |
| Databricks Genie Code | workspace-based ‡ | `.agents/skills/` ‡ |
| Snowflake Cortex Code | workspace-based ‡ | `.agents/skills/` ‡ |

Many harnesses also read `~/.agents/skills/` as a shared fallback.

‡ Databricks Genie Code and Snowflake Cortex Code are **data / analytics**
harnesses; skills are provisioned in the platform workspace (publish-based, like
Foundry) rather than a local home directory. Confirm the exact mechanism in
their docs.

### Which "Copilot"? (and Microsoft's other AI surfaces)

The installer targets **GitHub Copilot** — the coding agent (VS Code / CLI /
cloud) that reads file-based skills from `~/.copilot/skills` and `.github/skills/`.
Microsoft's other AI surfaces are different products with different extension
models, so they're intentionally not in the install scripts:

- **Microsoft Foundry agents** can run these same portable `SKILL.md` files, but
  they load them from a project/deployment `skills/` folder at session start — you
  *publish* skills to them rather than linking into a home directory.
- **Copilot Studio** is a low-code harness where people build agents of their own.
  It reaches the House through Patricia's hosted review, connected as an MCP
  server ([`copilot-studio.md`](skills/barry/references/harnesses/copilot-studio.md));
  agents on its Microsoft Copilot harness can also take an uploaded skill package.
- **Microsoft 365 Copilot** is its own harness, with Home, Autopilot and Code;
  Autopilot takes a skill as an uploaded `SKILL.md` folder or ZIP
  ([`m365-copilot.md`](skills/barry/references/harnesses/m365-copilot.md)).

## Using Barry

Invoke by name in any harness where the skill is installed:

- *"Barry, map the auth system and fix the session timeout."*
- *"Chief of staff: get this PR merge-ready."*
- *"Orchestrate agents in parallel to review my changes."*

Barry is harness-agnostic: the intake → plan → delegate → synthesize loop applies
everywhere. The agent/skill/model names in Barry are logical roles — each harness
supplies its own equivalents (see [`skills/barry/references/fleet.md`](skills/barry/references/fleet.md)).

## Adding a skill

1. Create `skills/<skill-name>/SKILL.md` with YAML frontmatter (`name`, `description`).
2. Add optional `references/`, `scripts/` as needed.
3. Update the skills table in this README.
4. Run `./scripts/install.sh --global --harness cursor --skill <skill-name>` or use `npx skills add`.

## Sync with local development

While editing this repo, symlink for live reload:

```bash
ln -sf "$(pwd)/skills/barry" ~/.cursor/skills/barry
```

Or re-run install after changes.

## License

MIT — see [LICENSE](LICENSE).
