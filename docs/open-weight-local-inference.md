# Open-weight model catalog

Status: proposed feature, tracked in #190. The catalog and ingestion tooling are not implemented.
Evidence checked November 1, 2026.

## Outcome and coverage

AI-Hive maintains a searchable, versioned catalog of downloadable open-weight models so
people can compare capabilities, licensing and the hardware needed for local inference.
The goal is comprehensive coverage, not only frontier text models: language/code,
embedding/reranking, vision/multimodal, speech/audio and image/video models.

"All" is a coverage objective, never an unsupported completeness claim. Publish the
discovery sources, inclusion rules, snapshot date, counts, exclusions and known gaps.
Track base, instruction-tuned and fine-tuned releases, adapters and quantizations with
explicit relationships rather than counting mirrors as new foundation models. Support
paginated discovery and resumable updates; measure coverage against each declared source.

## Definition and eligibility

Open-weight here means downloadable model parameters under published terms. It does not
automatically mean unrestricted use, full open source, no registration, or free operation.
Capture free-of-charge download, gated access, commercial permissions, redistribution,
acceptable-use restrictions and unknown terms separately.

Offer a strict filter for the user's intended use: weights downloadable without a
purchase and local inference permitted under the recorded license, with registration or
approval gates disclosed. Restricted entries may remain discoverable but must not be
labelled unrestricted or universally available. A model that exceeds a person's memory
does not become practical on that machine just because its weights are downloadable.

Source: OSI Open Source AI Definition, a stronger standard than weight availability:
https://opensource.org/ai/open-source-ai-definition

## Record contract

Each release has a stable ID and records:

- Publisher, family, release name/date, official model card, weight URL, source repository,
  immutable revision/checksum where available, parent relationships and modality.
- License identifier/reference, dated evidence for restrictions and no-purchase download,
  access gates and local-inference permission. Unknown is explicit, never inferred as yes.
- Parameters (total and active for mixture-of-experts where documented), architecture,
  context limits, languages, supported tasks, weight format, precision and quantization.
- Serving-engine compatibility and version, with publisher-claimed versus independently
  tested status; tool calling, structured output and streaming are separate capabilities.
- Weight size, RAM/VRAM, accelerator and hardware tier. Estimated memory states its
  formula, precision, context/batch assumptions and KV-cache/overhead; tested memory
  names the actual setup. Missing hardware evidence remains unknown.
- Evaluation name/version, score/unit, date, source, exact model variant, inference
  settings and evaluation provenance. Publisher claims and independent results remain
  distinct; incomparable benchmarks are not collapsed into one intelligence ranking.
- First discovered, last checked, source URLs, provenance, freshness, and lifecycle
  status such as active, withdrawn, deprecated or unavailable.

Store metadata and links, never weights, access tokens, private exports or copied datasets.
Proposed ownership: knowledge-hive for portable catalog records/schema and guides;
agents-hive for optional consumers. Any serving-specific integration stays in adapters.

## Frontier comparison

Mozilla's September 2026 report describes approximately a four-month open/closed frontier
gap on Epoch's index and a 4.4-month fitted gap on METR data:
https://stateofopensource.ai/

This is dated aggregate evidence about selected leading models and metrics, not a
definition of open weights, an average over every catalog entry, or a guarantee for a
small model running on a laptop. Keep such comparisons in dated evidence notes with
metric, cohort, method, limitations and source. Refresh or mark stale; do not hard-code
four months into catalog scores, eligibility, rankings or recommendations.

## Discovery, maintenance and user access

Use official publisher releases/model cards/licenses as primary evidence, with registries
as discovery sources and benchmarks as separately attributed evaluation sources. Document
source terms and rate limits. Deduplicate canonical identities and preserve provenance
when sources disagree; flag conflicts for review.

Provide search and filters for modality, task, publisher, license/access, model size,
hardware fit, context, compatibility, evaluation evidence and freshness. Expose both
machine-readable exports and a generated human-readable index from the same records.

Refresh through an operator-run, resumable command initially. Validate updates and propose
reviewable diffs before publication; retain historical evidence and withdrawn records.
Scheduled ingestion is a later opt-in, not an automation created by this proposal.

## Acceptance and delivery

1. Approve the schema, source coverage manifest, taxonomy and license classifications.
2. Seed diverse verified records, including gated/restricted, missing-data, quantized and
   withdrawn examples; publish counts and coverage gaps without claiming exhaustive reach.
3. Implement discovery/normalization, provenance, deduplication, exports, filters and
   freshness reporting. Test these with fixtures and source failures, rate limits and
   resumable pagination. A failed fetch must not erase records or mark them withdrawn.
4. Validators reject missing IDs/provenance, broken parent relationships, invalid units,
   duplicate identities and unsupported unrestricted-use claims. Unknown values remain valid
   where evidence is missing. Untrusted source text cannot authorize code or tool execution.
5. Verify filters and generated views against the canonical records; ensure stale,
   estimated, publisher-claimed and independently measured results are visibly distinct.
6. Review representative licenses, links and hardware/eval claims against primary sources.
   Record observed verification separately from future acceptance work.

This PR proposes the feature. It neither creates the full catalog nor implements local
inference, installs models, accepts licenses for users, spends money or changes deployments.
Existing AI-Hive approval, privacy, accounting and trust-evaluation controls remain applicable.
