---
description: Recommend the next step and write it as a prompt ready to paste.
---

Recommend the single next best step, and write it as a prompt I can paste back in.

1. Work out where things stand: this conversation, `git status` and the current branch,
   open PRs and their CI (`gh pr list`, `gh pr checks`), and the open issues in the current
   milestone and on the project board.
2. Pick one next step, the one that unblocks the most. Say in a sentence or two why you
   picked it.
3. Write the prompt in a fenced code block. Spell out the gates it keeps:
   - stop for my diff approval before committing;
   - wait for my yes before anything that changes Entra or Azure, spends money, or runs
     `deploy.sh`, `entra.sh` or `verify_barry.sh`;
   - merge only when CI is green and Patricia passes.
   For an issue that must stay open, say to use `Refs #N` and to run the pre-merge
   closing-keyword check.
4. Do nothing else: don't run the step, commit, push or merge.
