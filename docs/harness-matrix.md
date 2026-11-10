# The harness matrix

_Generated from `harnesses.json` by `python3 scripts/harnesses.py matrix`; edit the registry, not this file._

What works in each harness the House commits to, and what it costs, with the source and the date behind every claim. Why these harnesses, what aligned means and how cost is compared: [`harness-ecosystem.md`](harness-ecosystem.md). A row is unverified until its harness's alignment issue checks every field against the vendor's own docs and price page; until then, read it as a lead, not a fact. A field nobody has evidence for says unknown.

## Pro-code

### What works

| Harness | Rules | Skills | Subagents | MCP servers | Hooks | Memory | Permissions | Headless | Row |
|---|---|---|---|---|---|---|---|---|---|
| Claude Code | yes<br>`CLAUDE.md`<br>`~/.claude/CLAUDE.md` | yes<br>`.claude/skills`<br>`~/.claude/skills` | yes<br>`.claude/agents/{name}.md` | yes<br>`.mcp.json` | unknown | unknown | unknown | unknown | unverified |
| GitHub Copilot | yes<br>`.github/copilot-instructions.md` | yes<br>`.agents/skills`<br>`~/.copilot/skills` | yes<br>`.github/chatmodes/{name}.chatmode.md` | yes<br>`.vscode/mcp.json` | unknown | unknown | unknown | unknown | unverified |
| Codex | yes<br>`AGENTS.md`<br>`~/.codex/AGENTS.md` | yes<br>`.agents/skills`<br>`~/.codex/skills` | unknown | yes | unknown | unknown | unknown | unknown | unverified |
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
| Claude Code | Plan seat (Pro $20, Max $100 or $200 a month), or API tokens | Claude Sonnet 5.5: $2 · $0.20 · $10<br>Claude Opus 5.5: $4 · $0.20 · $20 | 2026-11-10 |
| GitHub Copilot | AI Credit, $0.01, spent per token at the model's rate; plans $10, $39 and $100 a month include $15, $70 and $200 of credits | Claude Sonnet 5.5: $2 · $0.20 · $10 | 2026-11-10 |
| Codex | ChatGPT plan ($20 or $200 a month), or API tokens since 2026-04-02 | GPT-5.5: $5 · $0.50 · $30 | 2026-11-10 |
| Cursor | Plan allowance (Pro $20, Pro+ $60, Ultra $200, Teams $40 a user), then usage | Claude Sonnet 5.5: $2.25 · unknown · $10.25 (Teams and Enterprise, list + $0.25) | 2026-11-10 |
| Gemini CLI | Free tier, Google AI Pro or Ultra plan, or API tokens | Gemini 3.1 Pro (prompts up to 200,000 tokens): $2 · $0.20 · $12 | 2026-11-10 |
| Devin Desktop | Plan (Pro $20, Max $200 a month; Teams $80 plus $40 a seat) | Not published | 2026-11-10 |
| Kiro | Credit (Pro $20 for 1,000 a month; more at $0.04); credits per request vary by model | Not published | 2026-11-10 |
| Cline | Free; your own key, or Cline's provider | As the model, at its list price; no harness fee | 2026-11-10 |
| OpenCode | Free; your own key | As the model, at its list price; no harness fee | 2026-11-10 |
| Goose | Free; your own key | As the model, at its list price; no harness fee | 2026-11-10 |

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
| n8n | Execution, €0.008 (Starter, €20 for 2,500) to €0.005 (Pro); models on your own key | As the model, at its list price; no harness fee | 2026-11-10 |
| Zapier Agents | Activity, about $0.022 (Pro, about $33 a month for 1,500) | Not published | 2026-11-10 |
| Dify | Message credit, about $0.01 (Professional, $590 a year for 5,000 a month), or your own key | As the model, at its list price; no harness fee | 2026-11-10 |

## Model list prices

The rates the effective prices start from, in dollars per million tokens.

| Model | Input | Cached input | Output | Source | Checked |
|---|---|---|---|---|---|
| Claude Sonnet 5.5 | $2 | $0.20 | $10 | [platform.claude.com](https://platform.claude.com/docs/en/about-claude/pricing) | 2026-11-10 |
| Claude Opus 5.5 | $4 | $0.20 | $20 | [platform.claude.com](https://platform.claude.com/docs/en/about-claude/pricing) | 2026-11-10 |
| Claude Fable 5.1 | $10 | $0.25 | $50 | [platform.claude.com](https://platform.claude.com/docs/en/about-claude/pricing) | 2026-11-10 |
| Claude Haiku 5.5 | $0.10 | unknown | $0.50 | [platform.claude.com](https://platform.claude.com/docs/en/about-claude/pricing) | 2026-11-10 |
| GPT-5.5 | $5 | $0.50 | $30 | [developers.openai.com](https://developers.openai.com/api/docs/pricing) | 2026-11-10 |
| Gemini 3.1 Pro (prompts up to 200,000 tokens) | $2 | $0.20 | $12 | [ai.google.dev](https://ai.google.dev/gemini-api/docs/pricing) | 2026-11-10 |

## Sources

- **Claude Code.** Rules: [`hives/rules-hive/scripts/install.sh`](../hives/rules-hive/scripts/install.sh), 2026-11-10; Skills: [`hives/skills-hive/scripts/install.sh`](../hives/skills-hive/scripts/install.sh), 2026-11-10; Subagents: [`hives/agents-hive/scripts/install.py`](../hives/agents-hive/scripts/install.py), 2026-11-10; MCP servers: [`hives/mcp-hive/scripts/install.py`](../hives/mcp-hive/scripts/install.py), 2026-11-10; cost: [www.cloudzero.com](https://www.cloudzero.com/blog/ai-coding-tools-cost/), [dev.to](https://dev.to/tokely/claude-code-codex-copilot-and-cursor-plans-vs-api-break-even-and-the-cost-of-long-sessions-2026-53d6), [platform.claude.com](https://platform.claude.com/docs/en/about-claude/pricing), 2026-11-10.
- **GitHub Copilot.** Rules: [`hives/rules-hive/scripts/install.sh`](../hives/rules-hive/scripts/install.sh), 2026-11-10; Skills: [`hives/skills-hive/scripts/install.sh`](../hives/skills-hive/scripts/install.sh), 2026-11-10; Subagents: [`hives/agents-hive/scripts/install.py`](../hives/agents-hive/scripts/install.py), 2026-11-10; MCP servers: [`hives/mcp-hive/scripts/install.py`](../hives/mcp-hive/scripts/install.py), 2026-11-10; cost: [www.cloudzero.com](https://www.cloudzero.com/blog/ai-coding-tools-cost/), [dev.to](https://dev.to/tokely/claude-code-codex-copilot-and-cursor-plans-vs-api-break-even-and-the-cost-of-long-sessions-2026-53d6), 2026-11-10.
- **Codex.** Rules: [`hives/rules-hive/scripts/install.sh`](../hives/rules-hive/scripts/install.sh), 2026-11-10; Skills: [`hives/skills-hive/scripts/install.sh`](../hives/skills-hive/scripts/install.sh), 2026-11-10; MCP servers: [`hives/mcp-hive/scripts/install.py`](../hives/mcp-hive/scripts/install.py), 2026-11-10; cost: [www.cloudzero.com](https://www.cloudzero.com/blog/ai-coding-tools-cost/), [apidog.com](https://apidog.com/blog/gpt-5-5-pricing/), 2026-11-10.
- **Cursor.** Rules: [`hives/rules-hive/scripts/install.sh`](../hives/rules-hive/scripts/install.sh), 2026-11-10; Skills: [`hives/skills-hive/scripts/install.sh`](../hives/skills-hive/scripts/install.sh), 2026-11-10; Subagents: [`hives/agents-hive/scripts/install.py`](../hives/agents-hive/scripts/install.py), 2026-11-10; MCP servers: [`hives/mcp-hive/scripts/install.py`](../hives/mcp-hive/scripts/install.py), 2026-11-10; cost: [www.cloudzero.com](https://www.cloudzero.com/blog/ai-coding-tools-cost/), 2026-11-10.
- **Gemini CLI.** Rules: [`hives/rules-hive/scripts/install.sh`](../hives/rules-hive/scripts/install.sh), 2026-11-10; Skills: [`hives/skills-hive/scripts/install.sh`](../hives/skills-hive/scripts/install.sh), 2026-11-10; cost: [www.developersdigest.tech](https://www.developersdigest.tech/blog/ai-coding-tools-pricing-2026), [ai.google.dev](https://ai.google.dev/gemini-api/docs/pricing), 2026-11-10.
- **Devin Desktop.** cost: [www.developersdigest.tech](https://www.developersdigest.tech/blog/ai-coding-tools-pricing-2026), 2026-11-10.
- **Kiro.** Rules: [`hives/rules-hive/scripts/install.sh`](../hives/rules-hive/scripts/install.sh), 2026-11-10; Skills: [`hives/skills-hive/scripts/install.sh`](../hives/skills-hive/scripts/install.sh), 2026-11-10; cost: [www.developersdigest.tech](https://www.developersdigest.tech/blog/ai-coding-tools-pricing-2026), 2026-11-10.
- **Cline.** cost: [www.developersdigest.tech](https://www.developersdigest.tech/blog/ai-coding-tools-pricing-2026), 2026-11-10.
- **OpenCode.** Rules: [`hives/rules-hive/scripts/install.sh`](../hives/rules-hive/scripts/install.sh), 2026-11-10; Skills: [`hives/skills-hive/scripts/install.sh`](../hives/skills-hive/scripts/install.sh), 2026-11-10; cost: [www.morphllm.com](https://www.morphllm.com/comparisons/opencode-vs-gemini-cli), 2026-11-10.
- **Goose.** Rules: [`hives/rules-hive/scripts/install.sh`](../hives/rules-hive/scripts/install.sh), 2026-11-10; Skills: [`hives/skills-hive/scripts/install.sh`](../hives/skills-hive/scripts/install.sh), 2026-11-10; MCP servers: [`hives/mcp-hive/scripts/install.py`](../hives/mcp-hive/scripts/install.py), 2026-11-10; cost: [github.com](https://github.com/block/goose), 2026-11-10.
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
