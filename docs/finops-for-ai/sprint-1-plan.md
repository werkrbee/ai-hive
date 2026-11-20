# FinOps for AI — Sprint 1: Plan

Issue #347 · Epic #346. This is a provider-neutral **planning reference**, not a billing engine. All examples use invented synthetic rates and usage, not current provider prices. Reviewed 2026-11-20.

## Architecture and compatibility

The canonical product usage ledger is `knowledge/ledger.jsonl` in [knowledge-hive](../../hives/knowledge-hive/DESIGN.md). It already defines `at`, `basis`, `usd`, `tokens`, `tokenDetail`, `runId`, `step`, `capability`, `provider`, `api`, `model`, `client`, and `taskId`. Preserve its append-only semantics, token accounting, and exact per-step USD/tokens carried from [workflows-hive](../../hives/workflows-hive/README.md). The FinOps extension below is an **optional, separate planning view** linked to those ledger records; do not rewrite canonical entries, create a second source of truth for spend, or replace execution-contract budgets. Deduplicate provider invoices and workflow-metered entries before allocating cost.

The synthetic planning view uses `record_id`, `source_record_id`, `period`, `category`, `quantity`, `unit`, `unit_rate_usd`, `amount_usd`, `basis` (`metered` or `estimated`), `product`, `project`, `team`, `tenant`, `agent`, `workflow`, `model`, `provider`, `environment`, `business_outcome`, `successful_outcomes`, and `source`. A separate `scenario` labels hypothetical calculations. Each entry represents one allocated charge, with an explicit unit and rate or a documented direct amount; never double-count a provider bill and its corresponding run charge. Missing attribution is `unallocated`, not silently distributed.

## Cost taxonomy

| Category | Examples | Preferred unit |
| --- | --- | --- |
| Inference | input, output and reasoning tokens | million tokens by token type |
| Cache | writes, reads, storage | million tokens or GB-month |
| Embeddings and retrieval | embedding tokens, vector query | million tokens, query |
| Tools and orchestration | MCP calls, A2A handoffs, retries | invocation, run |
| Compute | hosted GPU/CPU, idle capacity | GPU-hour, CPU-hour |
| Storage and observability | vectors, logs, traces | GB-month, GB ingested |
| Human oversight | approvals, evaluations, remediation | labor-hour |
| Other | licenses, networking, reserved capacity | seat-month, GB, hour |

Separate fixed and variable costs; account for retries and failed work; do not confuse model API price with fully allocated cost. Track gross and net spend and discounts separately when real invoices are available.

## Eight Plan use cases

| ID | Use case | Business decision | Evidence / acceptance |
| --- | --- | --- | --- |
| PLAN-01 | AI workload inventory | What workloads and owners exist? | Every charge attributed or explicitly unallocated |
| PLAN-02 | Budget and forecast | What is next month's expected cost? | Units × rates, forecast variance defined |
| PLAN-03 | Showback / chargeback | Which team or product consumed resources? | Reconciled allocations with no duplicates |
| PLAN-04 | Cost per outcome | Which workflow creates value efficiently? | Cost divided by verified successful outcomes |
| PLAN-05 | Open-weight TCO | Host or call an API? | GPU, utilization, operations, licenses and depreciation included |
| PLAN-06 | Capacity planning | How much serving headroom is needed? | Peak and average GPU-hour scenarios |
| PLAN-07 | Scenario analysis | How do traffic and model choice change spend? | Best/base/worst assumptions and sensitivity |
| PLAN-08 | Data quality and anomaly baseline | Can we trust the forecast? | Completeness, provenance and freshness checks |

## KPI definitions

- **Forecast** = sum of projected usage × rate, plus fixed expenses; **variance** = actual − forecast; **variance %** = variance / forecast when forecast > 0.
- **Cost per successful outcome** = allocated spend / independently verified successful outcomes; undefined at zero successes.
- **Utilization** = used capacity-hours / provisioned capacity-hours, with matching time windows.
- **Budget variance** = actual − approved budget; report overage separately from forecast error.
- **Business value per dollar** = *measured, attributable* business benefit / fully allocated cost; not computable without defensible benefit evidence.
- **Coverage** = attributed charges / total charges, and separately metered / total; report missing-data share.

## Three synthetic worked examples

1. **API inference.** 2,000 requests × 1,000 input tokens = 2M input; 2,000 × 250 output = 0.5M output. At invented rates of $2/M input and $8/M output, cost = $4 + $4 = **$8**. With 1,600 verified successes, **$0.005 per success**.
2. **Multi-agent workflow.** 100 workflows, each with 3 model calls at $0.02 and 2 tool calls at $0.005, plus 10 retries at $0.02: 100 × ($0.06 + $0.01) + $0.20 = **$7.20**. At 80 successful outcomes, **$0.09 per success**. A retry is charged once, not added again from the provider invoice.
3. **Self-hosted open-weight inference.** 1 GPU × 120 hours × invented $1.50/GPU-hour = $180; storage $20; operations 4 hours × $30 = $120; total **$320**. For 8,000 successful outputs, **$0.04 per success**. For a separate 240-hour provisioned-capacity scenario, 120 busy GPU-hours gives **50% utilization**; do not treat this as the utilization of the 120 billed GPU-hours in the rental-cost calculation. A reserved 240-hour GPU commitment would require billing all 240 hours, even when only 120 were busy. This illustrative example omits acquisition/depreciation when using a rented GPU, but a purchased-host comparison must add them; do not compare to API-only token charges without all-in costs.

## Data quality, failure modes and best practices

- Reconcile invoice totals and measured run entries; flag differences and late-arriving data. Separate provider, aggregator, and infrastructure charges to avoid double-counting.
- Treat missing rates, unit mismatches, zero successes and incomplete attribution as errors or explicitly undefined values, never zeros.
- Track pricing source, currency, effective date, provider/model revision and estimated vs metered basis; convert currency only with a dated FX rate.
- Forecast with ranges and assumptions, not a single unexplained number. Model changes can affect quality, retries, latency and approval labor.
- Record verified outcome quality before declaring ROI. Never infer savings from a cheaper token price alone.
- No credentials, user prompts, customer identifiers or personal data in the synthetic ledger. Use opaque IDs where real systems need joins.
- Do not silently edit `knowledge/ledger.jsonl` or `knowledge/audit.jsonl`; corrections must preserve history.

## Sources and limits

Repository contracts: [knowledge-hive](../../hives/knowledge-hive/DESIGN.md), [workflows-hive](../../hives/workflows-hive/README.md), [execution contracts](../../hives/agents-hive/README.md), and [Queen Bee's Charter](../../hives/rules-hive/rules/queen-charter/AGENTS.md).

External guidance to check at implementation time: [FinOps Foundation](https://www.finops.org/framework/), [FOCUS cost and usage specification](https://focus.finops.org/), and provider billing/pricing documentation. These are references, **not** evidence that synthetic rates reflect live market prices. Provider pricing must be verified against a dated primary source before production use.

## Sprint 2 handoff

Define enforcement for hard/soft limits, anomaly detection, rate limits, runaway retries, approval boundaries, and fail-closed missing telemetry using the existing workflows-hive and rules-hive mechanisms. The Plan view provides measurement and projections only; it must never grant runtime authority.
