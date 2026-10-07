---
description: Cut a release from main by merging release-please's release PR (SemVer + changelog + GitHub Release).
---

Releases are driven by release-please (`.github/workflows/release-please.yml`). Every push to
`main` opens or updates a release PR, titled `chore(main): release X.Y.Z` and labeled
`autorelease: pending`, from the Conventional Commits since the last tag. Merging that PR is
the release.

Preconditions: CI green on `main`, and the latest Release workflow run on `main` succeeded.

1. Find the open release PR: `gh pr list --label "autorelease: pending"`. If there is none,
   report that nothing releasable has landed since the last tag (`chore`, `test`, `build`, and
   `style` commits don't release) and stop.
2. Show the proposed version and the `CHANGELOG.md` entries from `gh pr diff <number>`. Check
   the diff touches only `CHANGELOG.md`, `.release-please-manifest.json`, and `version.txt`.
3. **Wait for my confirmation** of the version.
4. On approval: `gh pr merge <number> --squash --delete-branch`. Watch the Release workflow run
   on the merge commit until it finishes.
5. Verify the tag points at the merge commit, the GitHub Release is published (not a draft),
   and the PR is relabeled `autorelease: tagged`.
6. If any hive is published as its own package, run its publish step from the monorepo.
7. Report the new version, the release URL, and anything skipped.

Never hand-edit version numbers or the changelog — the commit history is the source of truth.
To force a specific version, land a commit with a `Release-As: X.Y.Z` footer instead.
