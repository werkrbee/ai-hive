# Monthly open-weight model tracker status

Checked November 16, 2026, after PRs [#324](https://github.com/werkrbee/ai-hive/pull/324), [#326](https://github.com/werkrbee/ai-hive/pull/326) and [#325](https://github.com/werkrbee/ai-hive/pull/325) merged.

The tracker, Node.js 24 Action pins and reviewed ten-model November snapshot are on main. Main CI [#502](https://github.com/werkrbee/ai-hive/actions/runs/43977377182) passed on `53998f2c5bbe9d20e4d991638d57bf887a2c32ea`. The snapshot blob is `b134f1893b972754f44ca0aea02a12d4d518ba7a`.

The two one-time PR #324 acceptance jobs are removed from CI in this cleanup. Routine collector tests, installer checks, artifact validation, registry/architecture checks, Azure compilation and A2A tests remain. The monthly schedule, workflow_dispatch and reusable-workflow entry point remain; the monthly workflow retains its scoped permissions and review-only PR behavior.

[The original Patricia review](pr-324-patricia-review.md) is a chronological audit record. Its earlier pending conditions describe the state at the time, not the current merge status. Historical entries and digests are preserved; the appended resolution records the completed gates.

## Validation limits

The pre-upgrade production dispatch [#1](https://github.com/werkrbee/ai-hive/actions/runs/43974129990) passed. Node.js 24 checkout/setup-python ran successfully in runtime-upgrade CI [#499](https://github.com/werkrbee/ai-hive/actions/runs/43976247088) and main CI [#500](https://github.com/werkrbee/ai-hive/actions/runs/43976548317).

A fresh dispatch of the monthly workflow on the final main commit is still pending: the connected GitHub tools do not expose dispatch and the cloud browser is signed out. Do not label the old dispatch as a successful Node.js 24 monthly run. Local live collection returned output byte-identical to the committed November snapshot (SHA-256 `605b5845283290ba842050f591c173eb59daf8167f13b36d2cea13f7b37c60ee`). The no-change regression check exits with `No metadata changes`, creates no PR and preserves the old monthly branch. These checks do not substitute for a GitHub Actions dispatch.

Model API license metadata remains unverified legal evidence. No model weights are executed or downloaded by the tracker, and no generated review PR merges automatically.
