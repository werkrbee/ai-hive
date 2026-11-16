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


## Follow-up verification — 2026-11-16

Primary publisher model cards and license text were checked for four exact releases:

| Model | Finding | Evidence |
| --- | --- | --- |
| GLM-4.5 | MIT; publisher explicitly permits commercial use; 355B total / 32B active | https://huggingface.co/zai-org/GLM-4.5 |
| Kimi-K2-Instruct | Modified MIT; commercial use allowed, but >100M monthly active users or >$20M monthly revenue triggers prominent Kimi K2 UI attribution | https://huggingface.co/moonshotai/Kimi-K2-Instruct/blob/main/LICENSE |
| NVIDIA-Nemotron-Nano-9B-v2 | NVIDIA Open Model License Agreement; publisher states ready for commercial use | https://huggingface.co/nvidia/NVIDIA-Nemotron-Nano-9B-v2 |
| gpt-oss-20b | Apache-2.0; model card describes 16 GB memory footprint with MXFP4 | https://huggingface.co/openai/gpt-oss-20b |

**Not yet fully verified:** Llama 3.1, Mistral 7B, Qwen2.5 7B, DeepSeek R1, Gemma 3, and Phi-4 need exact LICENSE and terms review, including commercial restrictions and hardware/runtime support.

**CI:** Run #488 succeeded, including the new offline collector tests. This does not demonstrate a live network fetch or monthly review-PR creation.

**Automation blocker:** The monthly workflow file is not present on the default branch. No dispatch was performed, and no monthly snapshot was generated. Do not merge merely to make testing possible while the outstanding security and licensing conditions remain unresolved.

**Patricia verdict remains ALLOW WITH CONDITIONS, not approval to merge.** In particular, review third-party action pinning, bot PR permissions, all model licenses, and a live end-to-end test before changing PR status.


## Live validation and remediation — 2026-11-16

The collector was executed against Hugging Face's live public API from a network-enabled runner. All ten exact model identities resolved. An anonymous HEAD request for a weight file in each repository returned HTTP 200 for eight models and HTTP 401 for the manually gated Llama and Gemma releases. No model weights were downloaded, terms accepted, or Hugging Face credentials supplied. Kimi identifies `modified-mit` and NVIDIA identifies `nvidia-open-model-license`; the generic `other` tag alone is insufficient, so schema v2 preserves custom license names, license links, upstream revisions, download pages and an example revision-pinned weight URL.

The monthly workflow now pins checkout and setup-python to resolved commit SHAs and exposes GH_TOKEN only to the PR proposal step. The proposal starts its branch at fetched main, stages only the generated snapshot, uses normal push, and never merges. Existing monthly branches are not overwritten; a branch without an open PR produces an explicit recovery error. A PR-324-only CI job calls the actual reusable monthly workflow to test live collection and review-PR creation before merge. This grant is restricted to this same-repository PR; no pull_request_target event or external token is used.

Patricia review: intake and code/security review complete; verdict ALLOW WITH CONDITIONS pending the live GitHub Actions acceptance run, generated PR inspection, current CI and production dispatch. The user's request authorizes fixes, test PR creation and merging only after all validation gates pass. Do not treat this entry as a completed independent Patricia subagent review.
