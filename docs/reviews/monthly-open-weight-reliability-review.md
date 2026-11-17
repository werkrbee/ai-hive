# Monthly model tracker reliability review

Baseline: main `112ae8010f74cfcb366261893eb45a3e7574ecb8`, after PR #327. Main [CI #507](https://github.com/werkrbee/ai-hive/actions/runs/44001227072) passed.

## Findings ranked by impact

| Rank | Finding | Evidence and consequence | Disposition |
| --- | --- | --- | --- |
| 1 — high | One branch name for the entire month blocks subsequent metadata reviews | A bare-Git regression reproduced a failure after merging the first monthly snapshot and then changing metadata: the retained branch has no open PR, so the proposal refuses to proceed. While the first PR is open, changed metadata is skipped with a success message instead. | This PR uses a full SHA-256 digest of the exact snapshot in each monthly branch name. Changed snapshots receive separate review PRs; repeats of identical snapshots retain the existing PR. |
| 2 — medium | Valid JSON with malformed field types can enter the snapshot | A mocked API response with an object-valued license and gated field was accepted. Missing revision was recorded as null while download links fell back to mutable main. Shape errors that raise exceptions fail safely, but not all malformed values raise. | Next focused improvement: validate required revision and metadata field types before publication. Not changed here. |
| 3 — medium | Concurrent collection/proposal runs can race on branch push or PR creation | The original workflow had no concurrency group. Normal pushes prevent forced overwrites, but a competing run can fail; failure after a successful push can leave a branch without a PR. | This PR serializes the entire job across scheduled, manual and reusable calls with a repository-specific concurrency group and cancel-in-progress false. Hosted concurrency was not exercised in this review. |
| 4 — low | Transient upstream failures require a rerun | Tests inject HTTP 503, URL/timeout and JSON decoding errors on the second model. All propagate and leave the previous snapshot byte-for-byte unchanged. There are 25-second request timeouts, but no retry policy. | Safe failure, not data corruption. Consider a small bounded retry/backoff for transient HTTP/network errors after schema validation; do not retry permanent identity/schema failures. |

## Focused change and safeguards

Proposal branches become `automation/open-weight-models-YYYY-MM-<full-snapshot-sha256>`. The old month-only branch is left untouched. A snapshot equal to main remains a no-op before any branch or PR creation. An identical snapshot with an open PR retains that PR. Different metadata, including changes after an earlier review merged, gets a new branch based on main and a new human-review PR. Old branches, open PRs and human edits are not rewritten or closed automatically. Multiple distinct snapshots can therefore have open PRs; reviewers must choose which to accept.

The workflow concurrency group covers the entire collector/proposal job. An active job is not canceled by a newer request. GitHub's default queue permits one pending job and can replace older pending requests; a queued job collects metadata after it starts, so this is a latest-observation tracker, not a complete event history. See [GitHub concurrency documentation](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).

There are no permission expansions, extra secrets, forced pushes or automatic merges. Public metadata is never executed. Collector behavior is unchanged apart from its now-outdated one-review-per-month comment.

## Tests and residual limits

The original post-merge regression failed before the fix and passes afterward. Seven offline tests pass, including real shell/Git integration coverage for changed metadata during an open review, later metadata after a prior merge, identical reruns, unchanged-main no-op, feature isolation, legacy-branch preservation, orphan refusal and synthetic-token log protection. HTTP/network/JSON failures on the second model preserve the prior output. GitHub PR operations are simulated in those tests; no production review PR or model API mutation was performed.

A pre-existing branch for the exact digest without an open PR still fails loudly and requires maintainer recovery. That includes a push-success/PR-creation-failure interruption, a closed review, or a reversion to a previously proposed snapshot while main differs. This deliberate refusal preserves human control; the PR does not automatically reuse or overwrite that branch. Direct script invocations outside the workflow do not receive GitHub's concurrency lock. Default job timeout and non-atomic output-file replacement are additional lower-priority hardening opportunities; runner disk-write failures were not tested.

Full CI and an independent read-only Patricia review are required for this PR. The user requires separate merge approval; leave the PR unmerged.

## Patricia review

Independent read-only supplied-context review by `/root/patricia_review`: **PASS**. The reviewer found no blocking flaw in the patch or reporting; schema validation remains a substantive disclosed follow-up. Installer checks and final-head CI must pass before considering merge, and hosted concurrency remains unverified. This is not the hosted/model-pinned Patricia deployment. The user's separate merge approval is required.

The delegation uses Barry passport v5 to Patricia passport v10's read-only intersection: review supplied context and return a verdict; no tools, network, shell, writes, external mutations or further delegates. The narrowed grant SHA-256 is `bcaef0b3f5234efdc57cb5ff84c97246bd17a3252b09bdaf85de956c6500e555`. Artifact digests underlying the supplied review (SHA-256):

- `scripts/propose_open_weight_review.sh`: `8668f9ac5a4700fa5f90a2f9e444c98269a6d183e1e48c52743623b7279c343c`
- `scripts/update_open_weight_models.py`: `9b75303eca3cb62961a32086428f730360ef44a1af0cb55c56edd40927ccd265`
- `tests/test_open_weight_models.py`: `30484acecf4fe495d1229c019000d38b24aefbb7bd1b9dae0b480e51c28f8c07`
- `.github/workflows/monthly-open-weight-models.yml`: `8614fb4f50ade88f1c80e7430ff8ab28e7231acdda427e09a40f660ed46462ce`
