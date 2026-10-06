---
description: Implement one issue end to end on a short-lived branch. Usage /work <issue-number>
---

For issue #$ARGUMENTS:

1. `gh issue view $ARGUMENTS` — restate the scope and acceptance criteria.
2. Branch: `git checkout -b <type>/<short-slug>` (type from the issue: feat/fix/refactor/docs).
3. Implement the change. Follow CLAUDE.md conventions (harness-agnostic, two-axis, docs voice).
4. Run the checks in `.github/workflows/ci.yml` locally (installer checks, artifact validation).
   Fix until green.
5. Stage only the files you changed; show me a diff summary.
6. **Stop here.** Do not commit or push until I approve the diff — then continue with `/ship`.

Stay inside the issue's scope. If you find adjacent work, note it as a follow-up issue, don't
expand this branch.
