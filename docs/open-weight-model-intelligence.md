# Open-weight model intelligence — November 16, 2026

This is AI Hive's expert-level **model** reference, complementary to the harness registry (`harnesses.json`). A model supplies inference; a harness orchestrates agents; Ollama, llama.cpp and vLLM are inference runtimes. Downloadable weights do **not** transfer copyright ownership, guarantee unrestricted use, or make a release Open Source AI under the [OSI definition](https://opensource.org/ai/open-source-ai-definition).

## License families

| License family | Practical meaning | Required check |
| --- | --- | --- |
| Apache-2.0 | Permissive commercial redistribution/modification; includes patent grant | Preserve notices, attribution and license |
| MIT | Permissive commercial use and modification | Preserve copyright and license notice |
| Vendor community license | Downloadable weights, often commercial use subject to conditions | Usage restrictions, scale thresholds, attribution, redistribution |
| Vendor model terms / acceptable-use policy | Model-specific conditions and prohibited uses | Read both license and linked policies |
| Research / noncommercial | Commercial deployment may be prohibited | Do not label commercially deployable |
| Gated / custom / unclear | Download may require approval or conditions | Verify exact revision and terms before use |
| Closed / API-only | No publicly downloadable flagship weights | Do not conflate vendor's other open releases |

## Major families and official discovery locations

**Important:** These links are publisher organization pages, not evidence that *every* model on the page has the stated license. Each individual model card and LICENSE file controls. License examples below are indicative, not blanket legal conclusions.

| Family | Open weights? | License examples / caution | Publisher download or model card |
| --- | --- | --- | --- |
| Meta Llama | Yes, selected releases | Llama Community License; custom terms, thresholds and acceptable-use conditions | https://huggingface.co/meta-llama |
| Mistral | Yes, selected releases | Apache-2.0 on many; other releases have different terms | https://huggingface.co/mistralai |
| Alibaba Qwen | Yes, selected releases | Apache-2.0 on many; exceptions require per-model review | https://huggingface.co/Qwen |
| DeepSeek | Yes, selected releases | MIT on R1; other variants may differ | https://huggingface.co/deepseek-ai |
| Google Gemma | Yes | Gemma Terms of Use, not standard Apache/MIT | https://huggingface.co/google |
| Microsoft Phi | Yes, selected releases | MIT on Phi-4 examples; verify variant | https://huggingface.co/microsoft |
| Z.ai / GLM | Yes, selected releases | MIT on some GLM variants; verify release | https://huggingface.co/zai-org |
| Moonshot Kimi | Selected releases; verify availability | Custom or version-specific terms; verify weights actually downloadable | https://huggingface.co/moonshotai |
| xAI Grok | Grok-1 weights; not every later Grok | Verify exact release license; do not generalize | https://huggingface.co/xai-org |
| OpenAI gpt-oss | Yes, selected models; flagship GPT API remains closed | Apache-2.0 for gpt-oss releases; verify model card | https://huggingface.co/openai |
| NVIDIA Nemotron | Yes, selected releases | Release-specific terms | https://huggingface.co/nvidia |
| Arcee | Yes, selected releases | Release-specific terms | https://huggingface.co/arcee-ai |

## Tracked exact model downloads

These are specific upstream model-card/download pages monitored by the monthly collector, rather than publisher home pages. Download access may require accepting terms or authentication. License status is **unverified until the model card and its linked LICENSE are reviewed**.

| Model | Exact download / card | License family to verify |
| --- | --- | --- |
| Llama 3.1 8B Instruct | https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct | Meta Llama 3.1 community terms |
| Mistral 7B Instruct v0.3 | https://huggingface.co/mistralai/Mistral-7B-Instruct-v0.3 | Apache-2.0 |
| Qwen2.5 7B Instruct | https://huggingface.co/Qwen/Qwen2.5-7B-Instruct | Apache-2.0 |
| DeepSeek R1 | https://huggingface.co/deepseek-ai/DeepSeek-R1 | MIT / supplemental model terms |
| Gemma 3 4B IT | https://huggingface.co/google/gemma-3-4b-it | Gemma terms |
| Phi-4 | https://huggingface.co/microsoft/phi-4 | MIT |
| gpt-oss 20B | https://huggingface.co/openai/gpt-oss-20b | Apache-2.0 / usage policy |
| GLM-4.5 | https://huggingface.co/zai-org/GLM-4.5 | MIT (publisher model card; 355B total / 32B active) |
| Kimi K2 Instruct | https://huggingface.co/moonshotai/Kimi-K2-Instruct | Modified MIT (publisher model card; ~1T total parameters) |
| Nemotron Nano 9B v2 | https://huggingface.co/nvidia/NVIDIA-Nemotron-Nano-9B-v2 | NVIDIA Open Model License Agreement (commercial use stated; 9B) |

These ten are a baseline for reproducible tracking, **not** the top seven models as of November 16, 2026. Expand the list by dated evaluation and add new releases after verifying the official repository.

## Verified primary-source findings (November 16, 2026)

- **GLM-4.5:** Z.ai's model card identifies an MIT release, 355B total / 32B active parameters and an FP8 multi-GPU serving configuration. A full-featured FP8 setup is described with eight H100s or four H200s; this is not a practical 16 GB laptop model. Source: https://huggingface.co/zai-org/GLM-4.5/blob/main/README.md
- **Kimi K2 Instruct:** Moonshot's card identifies the **Modified MIT** license, provides downloadable FP8 checkpoints, and documents vLLM/SGLang serving. The model repository is roughly 1 TB; a small local desktop is not a realistic full-weight deployment target. Source: https://huggingface.co/moonshotai/Kimi-K2-Instruct
- **Nemotron Nano 9B v2:** NVIDIA identifies its own **Open Model License Agreement**, states commercial use is permitted, and lists HF, vLLM and TensorRT-LLM inference with A10G 24 GB, H100 80 GB and Jetson AGX Thor as tested hardware. This is not an Apache-2.0/MIT blanket license. Source: https://huggingface.co/nvidia/NVIDIA-Nemotron-Nano-9B-v2

These are documented publisher claims, not independently executed model benchmarks or legal opinions. Other model entries remain pending per-release source verification; no claim is made that every family member shares a license.

## Selection and deployment guidance

Choose by **task** (general reasoning, coding, multilingual, vision, embedding, speech), **license**, **context window**, **total/active parameters**, **quantization**, **RAM/VRAM**, **runtime compatibility**, **provenance**, and **evaluation evidence**. An organization download page is not an executable model download; use an exact repository/revision. Distinguish native weights from community quantizations and mirrors. Test performance on your own workloads; benchmark claims are not interchangeable.

For local use, start with a small quantized model compatible with available RAM; larger MoE models can have large *total* weight footprints despite low active parameters. Offline inference can avoid provider token charges, but electricity, hardware, operations and licensing remain costs. Self-hosting does not itself establish HIPAA/GDPR compliance or eliminate model security risks.

## Monthly maintenance

The companion scheduled workflow runs on the first day of every month and can be manually dispatched. It fetches live metadata for a **curated list of exact Hugging Face model repositories**, records model-card license tags and gated status, preserves source URLs, and opens a review PR when the snapshot changes. Treat API metadata as a *signal*, not legal verification. A reviewer must inspect model cards and primary LICENSE files, record exceptions, check newly released models, and update this editorial guide. If an upstream API fails, the job fails rather than presenting stale information as fresh. No automatic merge.

The initial curated set intentionally samples ten representative releases; it is not a performance ranking or exhaustive census. The workflow's generated `docs/open-weight-models-monthly.json` records what was observed and when. Maintain source provenance and dated license evidence in the reviewed PR.

## Primary and secondary resources

- Model repositories and licenses: the publisher Hugging Face pages above; model cards and linked LICENSE files
- Hugging Face model API: https://huggingface.co/docs/hub/api
- OSI Open Source AI Definition: https://opensource.org/ai/open-source-ai-definition
- Apache-2.0: https://www.apache.org/licenses/LICENSE-2.0
- MIT: https://opensource.org/license/mit
- Secondary business overview (updated November 2, 2026): https://www.layer3labs.io/open-weights/best-open-weights-ai-models

This guide is informational, not legal advice. All license claims require per-release confirmation before production deployment.
