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


## Acceptance evidence and independent review — 2026-11-16

CI #493 (run 43973017550, head b48d19ca2dffa2fc9caa85f5d0a84e33729f27a1) passed all jobs. The actual monthly workflow's live collector and proposal step passed and created https://github.com/werkrbee/ai-hive/pull/325. Its single commit c08e99834dd4527eef271d91c8fa6ac99cca0b46 changes only the JSON snapshot. The generated blob b134f1893b972754f44ca0aea02a12d4d518ba7a exactly matches the independently generated local live snapshot. All ten records and revision-pinned sample downloads were reviewed; eight anonymous HEAD requests succeeded and two expected gated requests returned 401. Null custom license names or links mean the API does not supply them, not verified absence of terms. All metadata remains explicitly unverified legal evidence.

A sixth offline integration test now checks the real proposal script against a disposable bare Git repository and simulated GitHub CLI. It confirms main and unrelated feature content stay unchanged; the generated branch contains only the snapshot; reruns preserve its commit; an existing branch without an open PR fails safely; and a synthetic token never appears in output. All six tests pass locally. Artifact validation, registry checks and architecture checks pass. Local installer smoke checks reached their final cleanliness assertion and rejected the intentionally dirty development worktree; the equivalent clean CI #493 installer check passed.

Independent review task `/root/patricia_review` returned **PASS** on the supplied narrowed implementation and acceptance evidence, with final-head CI and final dispatch diff still required before merge. This was a separate read-only review of supplied context, with no shell, network, file writes, delegates or external authority; it was not the repository's hosted/model-pinned Patricia deployment. Delegation used Barry passport v5's Patricia delegate and Patricia passport v10's read-only intersection. The only identified nonblocking concern was an overly broad production-dispatch commit-message match; it was tightened to the exact PR #324 squash-title prefix.

The final CI adds an explicitly authorized production acceptance dispatch on the PR #324 squash push to main. Its isolated job has actions:write and contents:read, exposes the ephemeral GitHub token only to `gh workflow run monthly-open-weight-models.yml --repo "$GH_REPO" --ref main`, and cannot merge. This creates a workflow_dispatch event on main without requiring a PAT or browser sign-in. Post-merge production results must be verified and reported separately; they are not claimed complete here. The generated PR #325 is intentionally left for human review, never automatically merged.

Review audit digests (SHA-256): narrowed grant `bcaef0b3f5234efdc57cb5ff84c97246bd17a3252b09bdaf85de956c6500e555`. Artifact versions underlying the supplied review excerpts and evidence:

- `scripts/propose_open_weight_review.sh`: `63fd5d7239bf228476d84f1bc4df6f8660c084c1c1c7825d65def91df479b5b7`
- `scripts/update_open_weight_models.py`: `a4309568068c3ffcb189de3b8c0b31fc24797cca5c1f6dacead465a7192ae97a`
- `.github/workflows/monthly-open-weight-models.yml`: `4c22b975ac24d59bd9f3443d0c4db1404471dbcee80a8fee4bf68b0a16de51ac`
- `.github/workflows/ci.yml`: `c4fbc6b2123f333b8b8de2a395640d2b4ba5740b9f53bf62d675602c967f37ad`
- `tests/test_open_weight_models.py`: `6fbcbb172a65c00cb8f76f97c3d0c7a3ef06cab5d53e663d802d6e47147db772`
- `docs/open-weight-models-monthly.json`: `605b5845283290ba842050f591c173eb59daf8167f13b36d2cea13f7b37c60ee`

Final dispatch-diff review by `/root/patricia_review`: **PASS**. No additional governance blockers; final-commit CI must pass before merge, and production dispatch outcome must be recorded afterward.

Final-head CI #495 rejected the new dispatch condition before jobs started because its squash-title literal contains a colon in a YAML plain scalar. The condition was converted to a folded YAML scalar; both workflow files then parsed successfully. CI must run again on this correction.


## Post-merge resolution — 2026-11-16

This entry supersedes the pending merge and production conditions above without changing their historical text or audit digests. PR #324 was marked ready and squash-merged as `6c285eb9803319e88a4a720040fb2e5c68c7bca9` after final-head CI #496 and independent supplied-context Patricia PASS. Production workflow_dispatch run [#1](https://github.com/werkrbee/ai-hive/actions/runs/43974129990) and main CI #497 passed. That production run preceded the Node.js 24 Action upgrade.

PR #326 upgraded checkout/setup-python to commit-pinned Node.js 24 releases and merged as `0a860f89ad6732dcffc7e926f3bda6f1de45b032` after CI #499 and Patricia PASS; main CI #500 passed. PR #325 received maintainer workflow approval and an approved review, passed CI #494, and squash-merged the reviewed JSON as `53998f2c5bbe9d20e4d991638d57bf887a2c32ea`. Main CI #502 passed, and the merged snapshot blob exactly matches the reviewed blob `b134f1893b972754f44ca0aea02a12d4d518ba7a`.

The post-merge cleanup removes only the two obsolete PR #324 CI jobs and adds regression coverage for an unchanged, already-merged snapshot. It preserves the monthly workflow and normal CI checks. A fresh Node.js 24 monthly dispatch remains pending signed-in access; no success is claimed for an unexecuted run. See [current tracker status](monthly-open-weight-models-status.md) and the cleanup PR for subsequent verification. The user requires separate approval before this cleanup PR may merge.

Cleanup Patricia review by independent read-only task `/root/patricia_review`: **PASS** for PR preparation. The reviewer received narrowed supplied context only, under Barry passport v5 to Patricia passport v10's read-only intersection; no tools, network, shell, writes or delegation were permitted. Final-head CI and the user's new approval are still required before merge. The fresh hosted monthly dispatch remains pending; local no-change evidence does not complete it. This is not the hosted/model-pinned Patricia deployment.

Cleanup review audit: narrowed grant SHA-256 remains `bcaef0b3f5234efdc57cb5ff84c97246bd17a3252b09bdaf85de956c6500e555`. Artifact digests underlying the supplied cleanup review (SHA-256):

- `.github/workflows/ci.yml`: `af12377f21ebcb2d80fbcd486b90232f756225d785e5c311f236820eb5f7450b`
- `tests/test_open_weight_models.py`: `7c5ddb67c1a901948f95d4a9b7eb6997a52f1486c021ab7016d319ba8daa9ac0`
- `docs/reviews/monthly-open-weight-models-status.md`: `c8c31d4b80cc1c7f4e3eeb851ae1742d4292d87125c3fceb3ed9b09f18ac9bea`
