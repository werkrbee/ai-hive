---
description: Commit the current branch with a Conventional Commit, push, and open a PR.
---

1. Confirm CI checks pass locally and the diff is approved.
2. Commit with a **Conventional Commit** message (`type(scope): summary`) that references the
   issue (`Closes #N`). Body explains the what/why.
3. `git push -u origin HEAD`.
4. Open a PR with `gh pr create` using `.github/PULL_REQUEST_TEMPLATE.md`; fill the checklist.
5. Request a **Patricia charter-review** (run the patricia subagent on the diff) and paste its
   verdict into the PR.
6. Report the PR URL. Do not merge — I merge after review + green CI.
