---
description: Cut a release from main using Conventional Commits (SemVer + changelog + GitHub Release).
---

Preconditions: on `main`, clean tree, CI green.

1. Run the release tool (release-please or semantic-release) in dry-run; show the proposed
   version bump and changelog entries derived from Conventional Commits since the last tag.
2. **Wait for my confirmation** of the version.
3. On approval: let the tool tag, update `CHANGELOG.md`, and create the GitHub Release.
4. If any hive is published as its own package, run its publish step from the monorepo.
5. Report the new version, the release URL, and anything skipped.

Never hand-edit version numbers or the changelog — the commit history is the source of truth.
