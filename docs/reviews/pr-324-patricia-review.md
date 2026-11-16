# Patricia charter review — PR #324

Date: 2026-11-16. Scope: open-weight model reference, scheduled metadata collector, GitHub Actions workflow, and test coverage.

## Verdict: allow with conditions; do not mark ready for merge yet

- **Human control:** The scheduled action creates a review PR, never auto-merges. A reviewer must verify exact license and model-card terms before accepting the update. GitHub Actions write access is scoped to the review job, not global workflow permissions.
- **Safety:** No downloaded model weights, secret tokens, model execution, shell tool grants, or remote agent installation. Metadata is requested from Hugging Face public API over HTTPS. The collector fails on API errors and mismatched model identity.
- **Truthfulness:** Metadata license tags are labeled unverified; publisher statements are attributed and distinct from independent benchmarks. Model-family pages are not presented as universal licenses. No claim of OSI Open Source AI compliance is inferred from downloadable weights.
- **Reliability:** A month-keyed snapshot avoids date-only churn; the PR action reuses its branch, updates only a single generated JSON file, and does not merge automatically. Unit tests exercise license tag parsing, gating, model-ID mismatch and deterministic snapshots.
- **Residual risks:** Third-party GitHub Actions are referenced by mutable major tags rather than pinned commit SHAs; upstream API model IDs and licensing can change; initial network-backed snapshot has not yet been generated; monthly review requires a human and repo settings must permit the bot to create PRs.
- **Required before ready:** Confirm third-party Action pinning policy, execute a live metadata fetch in GitHub Actions or another network-enabled runner, run current-commit CI, and have a human review the license evidence and generated JSON. Do not represent this written checklist as an independently executed Patricia agent session.

This is a charter-aligned documented assessment, not a substitute for the repository's required independent Patricia reviewer.
