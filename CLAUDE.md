# CLAUDE.md — ai-hive

The Claude Code adapter for this repository. The repo's context lives in `AGENTS.md`, the
open cross-tool standard, imported here; this file adds only what is specific to Claude
Code. Put anything that isn't about Claude Code in `AGENTS.md`.

@AGENTS.md

## Claude Code

**Subagents.** `.claude/agents/barry.md` and `.claude/agents/patricia.md` run the dev team
as Claude Code subagents. Use Barry for planning and coordination, and Patricia to review a
diff or PR against the Charter before merge.

**Lifecycle commands.** `/sprint-plan` · `/next` · `/work <issue>` · `/ship` · `/release`,
in `.claude/commands/`.

**Settings.** `.claude/settings.json` holds the shared settings; `settings.local.json` is
each person's own and isn't committed.
