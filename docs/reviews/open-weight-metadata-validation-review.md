# Open-weight metadata validation review

Checked November 17, 2026. Baseline: main `90ef2bf5afa53f347d56b0c60d05b5f0b443baa9`, the squash merge of PR #329. Main [CI #513](https://github.com/werkrbee/ai-hive/actions/runs/44126538133) passed.

## Validation contract

The collector validates every API response before projecting fields into the snapshot. The full ten-model collection must succeed before the output directory is created or the snapshot is written. A malformed response raises a ValueError naming the requested model and field without dumping arbitrary upstream values.

| Field | Accepted shape |
| --- | --- |
| response / id | JSON object with the exact requested model ID |
| sha | Required full 40- or 64-character hexadecimal commit ID; no mutable main fallback |
| gated | Required false, auto or manual; true, integer zero and unknown/null values are rejected |
| cardData | Optional object or null |
| license / license_name / license_link | Optional nonempty string or null within cardData |
| tags | Optional array of nonempty strings; license tags must have a value |
| siblings | Required array of objects with nonempty relative repository filenames; empty inventory is permitted and does not imply downloadable weights |
| lastModified | Optional timezone-aware ISO 8601 timestamp or null |

File paths reject absolute paths, empty/dot/traversal components, backslashes and control characters. Valid URL-reserved filename characters are percent-encoded. Malformed JSON and invalid text encoding identify the model and response field. HTTP/network failures still propagate and retain the existing 25-second request timeout.

The contract covers consumed fields, not every possible Hub field. Optional model-card metadata may be absent; no license or access conclusion is invented. The tracker deliberately requires revision, gating and file inventory even though selective/list queries elsewhere in the Hub API can omit attributes. References: [ModelInfo](https://huggingface.co/docs/huggingface_hub/v1.19.0/en/package_reference/hf_api#huggingface_hub.hf_api.ModelInfo) and [ModelCardData](https://huggingface.co/docs/huggingface_hub/package_reference/cards#huggingface_hub.ModelCardData).

## Offline and live results

Thirteen test methods pass. Eighty-two malformed payloads are checked both directly and after a valid first model; every late validation failure preserves previous snapshot bytes. Cases cover root/identity/revision/gating/card/tags/file inventory/file paths/timestamps and all three license fields. Tests also cover optional/null metadata, reported gating modes, full revision pins, encoded paths, late HTTP503/network/JSON failures, and CLI nonzero exit with a clear diagnostic that does not echo a payload sentinel. Existing proposal integration tests remain intact.

The actual updated CLI fetched all ten public Hugging Face model APIs with no authentication, writing only to a temporary output. All ten responses passed validation, with full 40-character revisions and revision-pinned download links. The generated schema-v2 snapshot is byte-identical to the committed November snapshot: SHA-256 `605b5845283290ba842050f591c173eb59daf8167f13b36d2cea13f7b37c60ee`.

| Exact model | License metadata (unverified) | Gated |
| --- | --- | --- |
| `meta-llama/Llama-3.1-8B-Instruct` | `llama3.1` | `manual` |
| `mistralai/Mistral-7B-Instruct-v0.3` | `apache-2.0` | `false` |
| `Qwen/Qwen2.5-7B-Instruct` | `apache-2.0` | `false` |
| `deepseek-ai/DeepSeek-R1` | `mit` | `false` |
| `google/gemma-3-4b-it` | `gemma` | `manual` |
| `microsoft/phi-4` | `mit` | `false` |
| `openai/gpt-oss-20b` | `apache-2.0` | `false` |
| `zai-org/GLM-4.5` | `mit` | `false` |
| `moonshotai/Kimi-K2-Instruct` | `other / modified-mit` | `false` |
| `nvidia/NVIDIA-Nemotron-Nano-9B-v2` | `other / nvidia-open-model-license` | `false` |

The live check did not download model weights, accept terms, run models, modify the committed snapshot or publish a generated review PR. Workflow permissions, concurrency, proposal branches and the output schema are unchanged. API metadata remains unverified legal evidence; field validation is not license verification or proof of access.

## Patricia review and limits

Independent read-only supplied-context task `/root/patricia_review`: **PASS**. No blocking flaw was identified; installer checks and final-head CI must pass before merge consideration. This is not the hosted/model-pinned Patricia deployment. The user requires the PR to remain unmerged until separate approval.

Transport and validation failures occur before output writes. This PR does not add retries or atomic file replacement; a disk-write failure after successful collection is outside the byte-preservation guarantee. Future upstream schema changes may fail closed and require a reviewed contract update. Unknown unused fields are ignored.

Review delegation uses Barry passport v5 to Patricia passport v10's read-only intersection. The delegate may review supplied context and return a verdict, with no tools, network, shell, writes, external mutations or further delegation. Narrowed grant SHA-256: `bcaef0b3f5234efdc57cb5ff84c97246bd17a3252b09bdaf85de956c6500e555`. Artifact digests underlying supplied code/test review (SHA-256):

- `scripts/update_open_weight_models.py`: `e5ac47f707f9ba4af58c13d58220a0cb3874dd9ca9bc55bdeedafe6e9aa426ec`
- `tests/test_open_weight_models.py`: `a9ec69a317414b66182f91cf854fcb5691e2d16ff5965158eb4a2afde023cbab`

## Test-runner compatibility follow-up

Initial CI #517 failed only the CLI payload-leakage assertion: the runner's newer Python printed the test's inline source, which itself contained the synthetic sentinel. The collector was not dumping response data. The fixture now sends its JSON through stdin so the child program's source contains no payload. All thirteen local tests pass again; collector code and the successful all-ten-model live results are unchanged. Final-head CI must rerun. Earlier review digests above are retained as historical evidence.

Updated test artifact SHA-256: `409138b9da92d491a0eb9b789cbe2785fcfc14f3c65cdded2d0c0074e9908f57`.
