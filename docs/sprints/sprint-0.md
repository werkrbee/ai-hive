# Sprint 0 — project setup

Goal: convert ai-hive to a monorepo and stand up the open-source + Claude Code sprint
lifecycle, so all later work runs as issues → branches → PRs → releases.

Turn each item below into a GitHub issue with `/sprint-plan`, then work them with
`/work <issue>`.

## Issues

- [x] **Migrate submodules → monorepo.** (#1) Run `scripts/monorepo-migrate.sh` (review first),
      verify each `hives/<name>/` is now plain tracked files, remove `.gitmodules`, commit
      `refactor: consolidate hives into monorepo`. Confirm a fresh `git clone` needs no
      `--recurse-submodules`.
- [x] **Add community health files.** (#2) CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, GOVERNANCE,
      issue/PR templates, CODEOWNERS. (Seeded — review and adjust owners.)
- [x] **Stand up CI.** (#3) `.github/workflows/ci.yml` runs installer checks + validates every
      `SKILL.md` / `AGENTS.md`. Make it green.
- [x] **Wire Claude Code.** (#4) CLAUDE.md + `.claude/` commands and Barry/Patricia subagents.
      Mirror CLAUDE.md → AGENTS.md at root. (Seeded — verify commands run.)
- [x] **Release automation.** (#5) Add release-please (or semantic-release) so Conventional
      Commits produce SemVer tags, `CHANGELOG.md`, and GitHub Releases.
- [x] **Open the roadmap as issues.** (#7–#12) Create issues for each P0 item and attach to a
      `P0 — runtime layer` milestone.
- [x] **Project board.** (#6) Create a GitHub Projects (v2) board; add Sprint 0 + P0 issues.

## Definition of done

- Monorepo: one clone, no submodules, CI green on `main`.
- Governance + templates live; CODEOWNERS set.
- `/sprint-plan`, `/work`, `/ship`, `/release` all function.
- A first release (`v0.1.0`) cut by the automation as a smoke test.
- P0 issues created and on the board.
