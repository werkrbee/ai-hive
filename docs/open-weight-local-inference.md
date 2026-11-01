# Open-weight models and local inference

Status: proposed feature; no runtime support or deployment is claimed.
Repository baseline inspected: 469bae3bfe3f02718eaa2aa6da11c4ec26eb9c03, November 1, 2026.

## Outcome

A person can run a compatible, legally usable model on their own machine and configure
AI-Hive to use it without a paid hosted-model account. Portable skills, agent definitions,
approval rules and execution contracts remain independent of the model and serving engine.

## Terminology

Here, open-weight means model parameters are available to download for inference under
the publisher's terms. Availability does not guarantee unrestricted commercial use,
redistribution, access without registration, or compatibility with every machine.
Free download does not make electricity, hardware or operation free. Downloadable weights
alone do not establish that the whole AI system is open source.

Check the exact model release's license and model card before adoption. Record gated
access and use restrictions rather than assuming that anybody may use every release.
OSI's Open Source AI Definition is a separate, stronger standard:
https://opensource.org/ai/open-source-ai-definition

## Existing foundation and gap

The A2A runtime has protocol-named providers in
hives/agents-hive/servers/a2a/hive_a2a/providers.py. Its Chat Completions adapter supports
streaming, tool calls and token usage. The inspected HTTP provider requires either
an API key from an environment variable or Entra authentication. It requests streamed
usage and rejects missing token counts. An API-compatible URL alone therefore does not
prove a local server works. Existing Foundry catalog support (#77) does not establish
local inference support.

## Proposed first slice

Reuse the protocol adapter where practical. Start with one explicitly tested
loopback-hosted Chat Completions endpoint, with the serving engine selected during
implementation. Ollama, llama.cpp and vLLM are candidates to evaluate, not a promise
that all three are supported.

Keep endpoint, model identifier, authentication and capabilities in runtime configuration.
An explicit no-auth option must be restricted to loopback by default. Reject non-loopback
unauthenticated endpoints unless separately and deliberately configured under a reviewed
trust policy. Do not transmit credentials across redirects or silently fall back to a
hosted provider. Downloads and model execution remain deliberate operator actions.

Record the publisher/model ID, immutable revision or artifact checksum, weight format,
quantization, license reference and review date, serving-engine version, context limit,
and the tested machine's RAM/VRAM and accelerator. Do not commit weights or private data.

Negotiate or explicitly configure tested capabilities: structured JSON, streaming,
tool calls, token limits and usage reporting. Unsupported features fail clearly before
a governed task depends on them. Model-generated tool calls still pass the existing
permission and approval controls; changing the model never grants additional authority.

Preserve token accounting. Missing usage is an error unless a separately designed,
explicitly labelled estimation path is accepted; never invent metered counts.
Distinguish zero external API charge from unknown local operating cost. Keep hardware,
energy or allocated-cost estimates separate from actual provider charges.

## Acceptance criteria

- A documented setup runs an operator-selected, license-reviewed model on one declared
  hardware configuration, with exact model and server versions.
- Text completion and a structured Patricia response pass the appropriate existing eval
  suite. Barry tool use is supported only after the tool-call round trip and its
  permission/approval cases pass.
- Deterministic mock tests cover loopback no-auth configuration, existing authenticated
  providers, malformed replies, missing usage, unsupported capabilities, timeout,
  cancellation and bounded retries, and refusal of unintended remote transmission.
- A manual offline-after-setup run demonstrates inference without an external model API;
  evidence names what network activity was inspected and what remains unverified.
- Context/output limits and resource failures stop clearly; they do not trigger a cloud
  fallback or bypass budgets.
- Model replacement preserves product knowledge and audit history and requires the
  applicable version-pinned trust evaluation before promotion.
- The guide records observed latency and resource use, limitations, license restrictions,
  configuration, and the date checked. It makes no universal performance claim.
- Existing hosted-provider tests continue to pass; credentials and prompt contents are
  absent from committed evidence.

## Delivery and boundaries

First accept the design and select the initial engine/model/hardware test combination.
Then implement the configuration and adapter changes with mock tests, run local model
acceptance, and publish only verified compatibility guidance. Relate this work to #77
and P3's model guides without marking either local compatibility or a roadmap milestone done.

This proposal does not authorize downloads, model license acceptance on another person's
behalf, paid compute, public endpoint exposure, production migration, or hosted-agent
replacement. No training, fine-tuning, model distribution or automatic model installation
is included in the first slice.
