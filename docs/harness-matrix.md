# The harness matrix

_Generated from `harnesses.json` by `python3 scripts/harnesses.py matrix`; edit the registry, not this file._

What works in each harness the House commits to, and what it costs, with the source and the date behind every claim. Why these harnesses, what aligned means and how cost is compared: [`harness-ecosystem.md`](harness-ecosystem.md). A row is unverified until its harness's alignment issue checks every field against the vendor's own docs and price page; until then, read it as a lead, not a fact. A field nobody has evidence for says unknown.

## Pro-code

### What works

| Harness | Rules | Skills | Subagents | MCP servers | Hooks | Memory | Permissions | Headless | Row |
|---|---|---|---|---|---|---|---|---|---|
| Claude Code | yes<br>`CLAUDE.md`<br>`~/.claude/CLAUDE.md` | yes<br>`.claude/skills`<br>`~/.claude/skills` | yes<br>`.claude/agents/{name}.md` | yes<br>`.mcp.json` | yes<br>`.claude/settings.json` | yes<br>`~/.claude/projects/<project>/memory/` | yes<br>`.claude/settings.json` | yes<br>`claude -p` | verified |
| GitHub Copilot | yes<br>`.github/copilot-instructions.md`<br>`~/.copilot/copilot-instructions.md` | yes<br>`.agents/skills`<br>`~/.copilot/skills` | yes<br>`.github/agents/{name}.agent.md` | yes<br>`~/.copilot/mcp-config.json` | yes<br>`.github/hooks/` | yes | yes | yes<br>`copilot -p` | verified |
| Codex | yes<br>`AGENTS.md`<br>`~/.codex/AGENTS.md` | yes<br>`.agents/skills`<br>`~/.agents/skills` | yes<br>`.codex/agents/{name}.toml` | yes<br>`~/.codex/config.toml` | yes<br>`.codex/hooks.json` | yes | yes<br>`~/.codex/config.toml` | yes<br>`codex exec` | verified |
| Cursor | yes<br>`.cursor/rules/{name}.mdc` | yes<br>`.cursor/skills`<br>`~/.cursor/skills` | yes<br>`.cursor/agents/{name}.md` | yes<br>`.cursor/mcp.json` | unknown | unknown | unknown | unknown | unverified |
| Gemini CLI | yes<br>`GEMINI.md` | yes<br>`.agents/skills`<br>`~/.gemini/skills` | unknown | unknown | unknown | unknown | unknown | unknown | unverified |
| Devin Desktop | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unverified |
| Kiro | yes<br>`AGENTS.md` | yes<br>`.agents/skills`<br>`~/.kiro/skills` | unknown | unknown | unknown | unknown | unknown | unknown | unverified |
| Cline | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unverified |
| OpenCode | yes<br>`AGENTS.md` | yes<br>`.agents/skills`<br>`~/.config/opencode/skills` | unknown | unknown | unknown | unknown | unknown | unknown | unverified |
| Goose | yes<br>`.goosehints` | yes<br>`.goose/skills`<br>`~/.config/goose/skills` | unknown | yes | unknown | unknown | unknown | unknown | unverified |

### What it costs

| Harness | Billing unit and retail price | Effective $ per 1M tokens: input · cached input · output | Checked |
|---|---|---|---|
| Claude Code | Plan (Pro $20, Max $100, Ultra $200 a month; Team $25 or $125 a seat), or API tokens | Claude Sonnet 5.5: $2 · $0.10 · $10<br>Claude Opus 5.5: $4 · $0.20 · $20 | 2026-11-10 |
| GitHub Copilot | AI Credit, $0.01, spent per token at the model's rate; Pro $10, Pro+ $39 and Max $100 a month include 1,500, 7,000 and 20,000 credits | Claude Sonnet 5.5: $2 · $0.10 · $10<br>Claude Opus 5.5: $4 · $0.20 · $20 | 2026-11-10 |
| Codex | ChatGPT plan (Plus $20; Pro $100, $200 or $500; Business $25 a user), then credits per token at Codex's rate card; or API tokens at list price | GPT-6.1 Sol (prompts up to 272,000 tokens): $2 · $0.10 · $10 | 2026-11-10 |
| Cursor | Plan allowance (Pro $20, Pro+ $60, Ultra $200, Teams $40 a user), then usage | Claude Sonnet 5.5: $2.25 · unknown · $10.25 (Teams and Enterprise, list + $0.25) | 2026-11-10 |
| Gemini CLI | Free tier, Google AI Pro or Ultra plan, or API tokens | Gemini 3.1 Pro (prompts up to 200,000 tokens): $2 · $0.20 · $12 | 2026-11-10 |
| Devin Desktop | Plan (Pro $20, Max $200 a month; Teams $80 plus $40 a seat) | Not published | 2026-11-10 |
| Kiro | Credit (Pro $20 for 1,000 a month; more at $0.04); credits per request vary by model | Not published | 2026-11-10 |
| Cline | Free; your own key, or Cline's provider | The model's list price, on your own key; or Cline's provider, whose rate isn't recorded | 2026-11-10 |
| OpenCode | Free; your own key | The model's list price, on your own key | 2026-11-10 |
| Goose | Free; your own key | The model's list price, on your own key | 2026-11-10 |

### Recorded runs

Barry and Patricia run once in the real harness when it's aligned. The run doubles as the reference task that cost is compared on; its cost is the harness's own figure.

| Harness | Agent | Date | Version | Model | Tokens: input · cache write · cached · output | Cost | How | Result |
|---|---|---|---|---|---|---|---|---|
| Claude Code | Barry | 2026-11-10 | 2.1.322 | Claude Opus 5.5 | 8 · 27,089 · 106,063 · 2,553 | $0.29 at list price (Claude Code's own estimate) | `claude -p "/barry Plan issue #234 …" --permission-mode dontAsk` | planned #234 in eight steps, each with an agent role; edited nothing |
| Claude Code | Patricia | 2026-11-10 | 2.1.322 | Claude Opus 5.5 | 12 · 17,819 · 68,779 · 2,235 | $0.20 at list price (Claude Code's own estimate) | `claude -p --agent patricia "Review the uncommitted diff …" --permission-mode dontAsk` | CONCERNS on the work in progress: the matrix wasn't redrawn; fixed before this commit |
| GitHub Copilot | Barry | 2026-11-10 | 1.0.108 | GPT-6 Luna (prompts up to 272,000 tokens) | 24 · 43,306 · 203,647 · 3,437 | 0.92 AI credits ($0.009), as Copilot reports it | `copilot -p "/barry Plan issue #235 …" --no-ask-user` | planned #235 in steps, each with an agent role; auto model selection; edited nothing |
| GitHub Copilot | Patricia | 2026-11-10 | 1.0.108 | MAI-Code-1.1-Flash | 38,536 · 0 · 134,784 · 3,787 | 1.49 AI credits ($0.015), as Copilot reports it | `copilot -p "/patricia Review the staged diff …" --no-ask-user` | PASS on the staged diff, with a short review; auto model selection; edited nothing |
| Codex | Barry | 2026-11-10 | 0.167.0 | GPT-6.1 Sol (prompts up to 272,000 tokens) | 29,198 · 0 · 191,360 · 1,098 | not reported by Codex; 2.21 credits at its rate card, $0.09 at API list price | `codex exec "Use the barry skill. Plan issue #236 …" --sandbox read-only` | planned #236 in steps, each with an agent role; edited nothing (gh was blocked by the sandbox, so it read the issue another way) |
| Codex | Patricia | 2026-11-10 | 0.167.0 | GPT-6.1 Sol (prompts up to 272,000 tokens) | 25,112 · 0 · 135,168 · 608 | not reported by Codex; 1.75 credits at its rate card, $0.07 at API list price | `codex exec "Use the patricia skill. Review the staged diff …" --sandbox read-only` | CONCERNS: Codex agent files drop the tools restriction; answered with an install warning and a guide note |

## Low-code

### What works

| Harness | MCP | A2A | OpenAPI connectors | Auth | Row |
|---|---|---|---|---|---|
| Copilot Studio | unknown | unknown | unknown | unknown | unverified |
| Agentforce | unknown | unknown | unknown | unknown | unverified |
| Gemini Enterprise | unknown | unknown | unknown | unknown | unverified |
| ServiceNow AI Agents | unknown | unknown | unknown | unknown | unverified |
| Amazon Quick Suite | unknown | unknown | unknown | unknown | unverified |
| UiPath Agent Builder | unknown | unknown | unknown | unknown | unverified |
| Workato Agent Studio | unknown | unknown | unknown | unknown | unverified |
| n8n | unknown | unknown | unknown | unknown | unverified |
| Zapier Agents | unknown | unknown | unknown | unknown | unverified |
| Dify | unknown | unknown | unknown | unknown | unverified |

### What it costs

| Harness | Billing unit and retail price | Effective $ per 1M tokens: input · cached input · output | Checked |
|---|---|---|---|
| Copilot Studio | Copilot Credit, $0.01 pay-as-you-go or $0.008 in a $200 pack of 25,000; a reasoning response can take 100 credits; internal use included with a $30 Microsoft 365 Copilot seat | Not published | 2026-11-10 |
| Agentforce | Flex Credit, $0.005 ($500 for 100,000); a standard action is 20 credits ($0.10), a voice action 30; or $2 a conversation | Not published | 2026-11-10 |
| Gemini Enterprise | Seat, $21 to $50 a month; agent usage billed separately | Not published | 2026-11-10 |
| ServiceNow AI Agents | Assist, from a pool per seat; about 25 for a summary, 150 for an agentic action; no dollar price published | Not published | 2026-11-10 |
| Amazon Quick Suite | Seat, $20 or $40 a month plus $250 an account; extra agent hours $3 (Flows, Automate) or $6 (Research) | Not published | 2026-11-10 |
| UiPath Agent Builder | Platform Unit per model call: 0.16 basic, 0.2 standard, 0.4 premium; dollar price by contract | Not published | 2026-11-10 |
| Workato Agent Studio | Genie action, one per prompt; price by quote | Not published | 2026-11-10 |
| n8n | Execution, €0.008 (Starter, €20 for 2,500) to €0.005 (Pro); models on your own key | The model's list price, on your own key; plus each execution | 2026-11-10 |
| Zapier Agents | Activity, about $0.022 (Pro, about $33 a month for 1,500) | Not published | 2026-11-10 |
| Dify | Message credit, about $0.01 (Professional, $590 a year for 5,000 a month), or your own key | The model's list price, on your own key; or message credits on Dify's plans | 2026-11-10 |

## Model list prices

The rates the effective prices start from, in dollars per million tokens.

| Model | Input | Cached input | Output | Source | Checked |
|---|---|---|---|---|---|
| Claude Sonnet 5.5 | $2 | $0.10 | $10 | [platform.claude.com](https://platform.claude.com/docs/en/about-claude/pricing) | 2026-11-10 |
| Claude Opus 5.5 | $4 | $0.20 | $20 | [platform.claude.com](https://platform.claude.com/docs/en/about-claude/pricing) | 2026-11-10 |
| Claude Fable 5.1 | $10 | $0.25 | $50 | [platform.claude.com](https://platform.claude.com/docs/en/about-claude/pricing) | 2026-11-10 |
| Claude Haiku 5.5 (prompts up to 100,000 tokens) | $0.10 | $0.01 | $0.50 | [platform.claude.com](https://platform.claude.com/docs/en/about-claude/pricing) | 2026-11-10 |
| GPT-5.5 | $5 | $0.50 | $30 | [developers.openai.com](https://developers.openai.com/api/docs/pricing) | 2026-11-10 |
| Gemini 3.1 Pro (prompts up to 200,000 tokens) | $2 | $0.20 | $12 | [ai.google.dev](https://ai.google.dev/gemini-api/docs/pricing) | 2026-11-10 |
| GPT-6 Luna (prompts up to 272,000 tokens) | $0.10 | $0.01 | $0.50 | [docs.github.com](https://docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing) | 2026-11-10 |
| MAI-Code-1.1-Flash | $0.20 | $0.02 | $1.20 | [docs.github.com](https://docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing) | 2026-11-10 |
| GPT-6.1 Sol (prompts up to 272,000 tokens) | $2 | $0.10 | $10 | [developers.openai.com](https://developers.openai.com/api/docs/pricing) | 2026-11-10 |

## Sources

- **Claude Code.** Rules, Memory: [code.claude.com](https://code.claude.com/docs/en/memory), 2026-11-10; Skills: [code.claude.com](https://code.claude.com/docs/en/skills), 2026-11-10; Subagents: [code.claude.com](https://code.claude.com/docs/en/sub-agents), 2026-11-10; MCP servers: [code.claude.com](https://code.claude.com/docs/en/mcp), 2026-11-10; Hooks: [code.claude.com](https://code.claude.com/docs/en/hooks), 2026-11-10; Permissions: [code.claude.com](https://code.claude.com/docs/en/permissions), 2026-11-10; Headless: [code.claude.com](https://code.claude.com/docs/en/headless), 2026-11-10; cost: [claude.com](https://claude.com/pricing), [platform.claude.com](https://platform.claude.com/docs/en/about-claude/pricing), 2026-11-10.
- **GitHub Copilot.** Rules: [docs.github.com](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-custom-instructions), 2026-11-10; Skills: [docs.github.com](https://docs.github.com/en/copilot/concepts/agents/about-agent-skills), 2026-11-10; Subagents: [docs.github.com](https://docs.github.com/en/copilot/reference/custom-agents-configuration), 2026-11-10; MCP servers: [docs.github.com](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers), 2026-11-10; Hooks: [docs.github.com](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/use-hooks), 2026-11-10; Memory: [docs.github.com](https://docs.github.com/en/copilot/concepts/agents/copilot-memory), 2026-11-10; Permissions: [docs.github.com](https://docs.github.com/en/copilot/how-tos/copilot-cli/use-copilot-cli/allowing-tools), 2026-11-10; Headless: [docs.github.com](https://docs.github.com/en/copilot/how-tos/copilot-cli/use-copilot-cli/overview), 2026-11-10; cost: [docs.github.com](https://docs.github.com/en/copilot/concepts/billing/usage-based-billing-for-individuals), [docs.github.com](https://docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing), 2026-11-10.
- **Codex.** Rules: [learn.chatgpt.com](https://learn.chatgpt.com/docs/agent-configuration/agents-md), 2026-11-10; Skills: [learn.chatgpt.com](https://learn.chatgpt.com/docs/build-skills), 2026-11-10; Subagents: [learn.chatgpt.com](https://learn.chatgpt.com/docs/agent-configuration/subagents), 2026-11-10; MCP servers: [learn.chatgpt.com](https://learn.chatgpt.com/docs/extend/mcp), 2026-11-10; Hooks: [learn.chatgpt.com](https://learn.chatgpt.com/docs/hooks), 2026-11-10; Memory: [learn.chatgpt.com](https://learn.chatgpt.com/docs/customization/memories), 2026-11-10; Permissions: [learn.chatgpt.com](https://learn.chatgpt.com/docs/agent-approvals-security), 2026-11-10; Headless: [learn.chatgpt.com](https://learn.chatgpt.com/docs/non-interactive-mode), 2026-11-10; cost: [learn.chatgpt.com](https://learn.chatgpt.com/docs/pricing), [developers.openai.com](https://developers.openai.com/api/docs/pricing), 2026-11-10.
- **Cursor.** Rules: [`hives/rules-hive/scripts/install.sh`](../hives/rules-hive/scripts/install.sh) (the House's installer, not the vendor's docs), 2026-11-10; Skills: [`hives/skills-hive/scripts/install.sh`](../hives/skills-hive/scripts/install.sh) (the House's installer, not the vendor's docs), 2026-11-10; Subagents: [`hives/agents-hive/scripts/install.py`](../hives/agents-hive/scripts/install.py) (the House's installer, not the vendor's docs), 2026-11-10; MCP servers: [`hives/mcp-hive/scripts/install.py`](../hives/mcp-hive/scripts/install.py) (the House's installer, not the vendor's docs), 2026-11-10; cost: [www.cloudzero.com](https://www.cloudzero.com/blog/ai-coding-tools-cost/), 2026-11-10.
- **Gemini CLI.** Rules: [`hives/rules-hive/scripts/install.sh`](../hives/rules-hive/scripts/install.sh) (the House's installer, not the vendor's docs), 2026-11-10; Skills: [`hives/skills-hive/scripts/install.sh`](../hives/skills-hive/scripts/install.sh) (the House's installer, not the vendor's docs), 2026-11-10; cost: [www.developersdigest.tech](https://www.developersdigest.tech/blog/ai-coding-tools-pricing-2026), [ai.google.dev](https://ai.google.dev/gemini-api/docs/pricing), 2026-11-10.
- **Devin Desktop.** cost: [www.developersdigest.tech](https://www.developersdigest.tech/blog/ai-coding-tools-pricing-2026), 2026-11-10.
- **Kiro.** Rules: [`hives/rules-hive/scripts/install.sh`](../hives/rules-hive/scripts/install.sh) (the House's installer, not the vendor's docs), 2026-11-10; Skills: [`hives/skills-hive/scripts/install.sh`](../hives/skills-hive/scripts/install.sh) (the House's installer, not the vendor's docs), 2026-11-10; cost: [www.developersdigest.tech](https://www.developersdigest.tech/blog/ai-coding-tools-pricing-2026), 2026-11-10.
- **Cline.** cost: [www.developersdigest.tech](https://www.developersdigest.tech/blog/ai-coding-tools-pricing-2026), 2026-11-10.
- **OpenCode.** Rules: [`hives/rules-hive/scripts/install.sh`](../hives/rules-hive/scripts/install.sh) (the House's installer, not the vendor's docs), 2026-11-10; Skills: [`hives/skills-hive/scripts/install.sh`](../hives/skills-hive/scripts/install.sh) (the House's installer, not the vendor's docs), 2026-11-10; cost: [www.morphllm.com](https://www.morphllm.com/comparisons/opencode-vs-gemini-cli), 2026-11-10.
- **Goose.** Rules: [`hives/rules-hive/scripts/install.sh`](../hives/rules-hive/scripts/install.sh) (the House's installer, not the vendor's docs), 2026-11-10; Skills: [`hives/skills-hive/scripts/install.sh`](../hives/skills-hive/scripts/install.sh) (the House's installer, not the vendor's docs), 2026-11-10; MCP servers: [`hives/mcp-hive/scripts/install.py`](../hives/mcp-hive/scripts/install.py) (the House's installer, not the vendor's docs), 2026-11-10; cost: [github.com](https://github.com/block/goose), 2026-11-10.
- **Copilot Studio.** cost: [cdn-dynmedia-1.microsoft.com](https://cdn-dynmedia-1.microsoft.com/is/content/microsoftcorp/microsoft/bade/documents/products-and-services/en-us/ai/CopilotCreditsGuideSeptember2026.pdf), [www.cloudzero.com](https://www.cloudzero.com/blog/copilot-studio-pricing/), 2026-11-10.
- **Agentforce.** cost: [www.supered.io](https://www.supered.io/blog/agentforce-pricing/), 2026-11-10.
- **Gemini Enterprise.** cost: [dupple.com](https://dupple.com/learn/gemini-enterprise-pricing), 2026-11-10.
- **ServiceNow AI Agents.** cost: [www.getmacha.com](https://www.getmacha.com/blog/servicenow-ai-agents-complete-guide), 2026-11-10.
- **Amazon Quick Suite.** cost: [aws.amazon.com](https://aws.amazon.com/quick/pricing), 2026-11-10.
- **UiPath Agent Builder.** cost: [docs.uipath.com](https://docs.uipath.com/agents/automation-cloud/latest/user-guide/licensing), 2026-11-10.
- **Workato Agent Studio.** cost: [docs.workato.com](https://docs.workato.com/en/pricing/usage-metrics/agent-studio.html), 2026-11-10.
- **n8n.** cost: [coworker.ai](https://coworker.ai/blog/n8n-pricing), 2026-11-10.
- **Zapier Agents.** cost: [www.jahanzaib.ai](https://www.jahanzaib.ai/blog/zapier-agents-vs-n8n-ai-agents-2026), [logicballs.com](https://logicballs.com/blog/best-no-code-ai-agent-builder), 2026-11-10.
- **Dify.** cost: [logicballs.com](https://logicballs.com/blog/best-no-code-ai-agent-builder), 2026-11-10.
