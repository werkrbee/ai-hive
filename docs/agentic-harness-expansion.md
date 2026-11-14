# Agentic harness expansion proposal

## Purpose

Extend AI Hive beyond its existing pro-code and low-code categories to cover **general-purpose, autonomous agent runtimes**. OpenClaw and Hermes Agent are initial candidates, not synonyms for coding agents or visual workflow builders. Preserve the existing top-ten rankings and avoid claiming support until tested.

## Proposed registry taxonomy

Add `agentic-runtime` to `harnesses.json.categories`: "Persistent, tool-using general-purpose agent runtimes with autonomous execution, scheduling, memory, and messaging or event-driven interfaces."

Candidates for an initial **watch** tier:

| Candidate | Primary fit | Evaluation focus |
| --- | --- | --- |
| OpenClaw | Self-hosted personal assistant / agent runtime | Gateway, channels, tool execution, skills, persistent sessions, approvals |
| Hermes Agent | General-purpose agent runtime | CLI, skills, tools, persistent memory, automation, model/provider portability |
| Letta | Stateful agent platform | Persistent memory, agent API, tool calling, deployment |
| OpenHands | Autonomous software-engineering agent platform | Overlap with pro-code; avoid duplicate classification |
| AutoGen / AG2 | Multi-agent framework | Framework vs deployable harness distinction |
| CrewAI | Multi-agent orchestration framework | Framework vs runtime distinction |
| LangGraph | Stateful orchestration framework | Durable execution, checkpointing, human approval |

OpenClaw and Hermes are the first two integration targets. Other candidates require classification and evidence before registry admission. Frameworks should not be described as turnkey personal assistant harnesses.

## Acceptance criteria

1. Add the category and watch-tier records in the single canonical `harnesses.json` registry, with stable kebab-case IDs, vendor/project attribution, `adapter: null` until an adapter exists, and no fabricated ranks.
2. For each candidate document upstream source, license, supported OS, deployment model, CLI/API entry points, local-model support (including Ollama where applicable), model-provider configuration, authentication, cost model, and date checked. Unknown capabilities must be `"unknown"`, not `false`.
3. Extend the capability schema and renderer only as needed for agentic-runtime-specific dimensions: scheduled/background execution, persistent memory, skills, MCP, A2A, messaging channels, sandboxing, permission gates, and headless execution. Do not break existing category rows.
4. Document an adapter contract mapping Hive skills, rules, agents, MCP tools, and knowledge into each runtime. Distinguish native installation from generated compatibility shims and unsupported features.
5. Implement OpenClaw and Hermes adapters only after upstream install/configuration paths are confirmed. No guessed dot-directories or executable flags.
6. Add registry validation and documentation generation tests; regenerate the harness matrix and ecosystem documentation using `scripts/harnesses.py` rather than editing generated rows manually.
7. Run a safe smoke test for each integrated runtime: install a harmless skill, invoke a read-only tool, verify persistence, exercise an approval boundary, and record version, date, outcome, and limitations. Never grant unrestricted shell/network access in tests.
8. Require green CI and Patricia charter review before merge.

## Architecture considerations

- **Harness ≠ model ≠ runtime provider.** Ollama serves models locally; an agentic harness coordinates tools, memory, workflows and execution. Document whether each harness can use local inference without implying zero operating cost.
- **Security first.** Message-triggered execution, credential storage, third-party skills, remote tool access and unattended actions need explicit threat modeling and least-privilege defaults.
- **No ranking inflation.** Preserve existing pro-code and low-code top tens. Keep agentic-runtime candidates on watch until category-specific evaluation and repeatable conformance evidence justify ranking.
- **One source of truth.** Registry, adapters, installers, docs and diagrams must stay synchronized.

## Follow-on implementation

Track registry/schema, renderer/docs, OpenClaw adapter, Hermes adapter, and conformance/security tests as separate reviewable changes. This PR is a scoped proposal; it does **not** claim that the runtimes are installed or operational.

## Upstream projects to verify

- OpenClaw: https://github.com/openclaw/openclaw
- Hermes Agent: https://github.com/NousResearch/hermes-agent
- Letta: https://github.com/letta-ai/letta
- OpenHands: https://github.com/All-Hands-AI/OpenHands
- AutoGen: https://github.com/microsoft/autogen
- AG2: https://github.com/ag2ai/ag2
- CrewAI: https://github.com/crewAIInc/crewAI
- LangGraph: https://github.com/langchain-ai/langgraph
