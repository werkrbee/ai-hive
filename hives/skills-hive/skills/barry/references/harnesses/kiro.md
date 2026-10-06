# Barry on Kiro (AWS)

Kiro is AWS's spec-driven coding agent (IDE + CLI) that replaced Amazon Q
Developer. It adopted the open `SKILL.md` standard — the same skill file that runs
in Claude Code runs in Kiro.

**Skills load from:** `~/.kiro/skills/` (global) or `.kiro/skills/` /
`.agents/skills/` (project). *Verify exact paths against current Kiro docs.*

**Delegation:** Kiro plans first (spec phase), then implements; it reads available
skills and matches them to the current task. Map Barry's roles:

| Barry role | Kiro equivalent |
|------------|-----------------|
| explore | Kiro's codebase/spec discovery |
| generalPurpose | Kiro implementation agent |
| shell | Kiro CLI / terminal tool |
| code-review | a review skill during the implement phase |
| security-review | a security review skill |

**Fit:** Kiro already breaks work into discrete tasks during its spec phase, so
Barry's intake → plan → delegate → synthesize loop maps cleanly; lean on Kiro's
own planning rather than duplicating it.

**Models:** only when asked; use the model options Kiro exposes (incl. Bedrock).
