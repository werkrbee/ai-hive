# The harness ecosystem: the twenty ai-hive aligns with

_Which harnesses the House treats as first-class, what each costs to run, and what aligned
means._

ai-hive is harness-agnostic: its artifacts ride open standards (`AGENTS.md`, `SKILL.md`,
MCP, A2A) and `adapters/<harness>/` says where they run. Today that axis is a list of
names, not a promise. Six hives have ten adapter folders each, and all of them are empty. The
harness list is written out by hand in each installer, in `scripts/architecture.py` and in
eight READMEs, and several install paths carry a "verify" comment that nobody has acted
on. A product adopting the House can't tell which harnesses actually work, or what running
an agent in one costs compared with another.

This note picks twenty harnesses in two categories, read against public evidence on
2026-11-10, defines what aligned means for each category, and sets one unit for comparing
their cost. The work is tracked on the `P2.3 — harness alignment` milestone (epic #229), in the
order set in `docs/sprints/p2.3.md`.

## Two categories

**Pro-code harnesses** are where developers build: coding agents that read a repository,
run tools and load the open standards from files. The House reaches them by installing
its artifacts: rules, skills, subagents and MCP configuration.

**Low-code harnesses** are where everyone else builds: visual agent builders inside the
platforms an organization already runs. Most of them don't read `SKILL.md` or `AGENTS.md`
from a repository. The House reaches them over the wire instead, through MCP servers and
A2A agents they can call, which is the point of `interface-independence.md`. They are how
the vision's "every person and every organization" becomes more than developers.

## How the twenty were chosen

Three things count, in order. Reach comes first: how many people use the harness at work.
Openness second: whether it speaks the open standards (files for pro-code, MCP and A2A
for low-code), so aligning with it strengthens the standards instead of a vendor's
format. Third, whether it brings something the others don't, such as being open source.

The evidence for reach is strongest for the top five pro-code harnesses. JetBrains'
Developer Ecosystem Survey 2026 puts workplace use of Claude Code at about 39% of
professional developers, GitHub Copilot at 21%, OpenAI Codex at 16% and Cursor at 12%.
Stack Overflow's 2026 survey, asked of developers who already use agents, has the same
order (Claude Code 66%, Copilot 59%, Codex 30%, Cursor 26%) with Google's Antigravity and
Gemini tools next. Below the top five, and across the whole low-code list, no survey
separates the field well, so those places rest on the installed base of each vendor's
platform, openness and distinctness. That is the weakest part of this ranking, and the
first thing the quarterly check should revisit.

## The pro-code ten

1. **Claude Code** (Anthropic). The most used agent in both surveys, and the harness the
   House's own lifecycle runs on.
2. **GitHub Copilot** (GitHub). Second in both surveys, across VS Code, the CLI and the
   cloud agent.
3. **Codex** (OpenAI). Third in both surveys; reads `AGENTS.md` natively.
4. **Cursor** (Anysphere). Fourth in both surveys, with the subagent types closest to
   Barry's roles.
5. **Gemini CLI and Antigravity** (Google). Next in Stack Overflow's survey. Both load the
   same skills, so they are one harness with two surfaces. Reports conflict on whether
   Gemini CLI was replaced for consumers by Antigravity's CLI in June 2026; the
   alignment issue settles it.
6. **Devin Desktop** (Cognition), formerly Windsurf, renamed in June 2026 with its rules
   moving from `.windsurf/` to `.devin/`. A new adapter.
7. **Kiro** (AWS). Spec-driven, and the successor to Amazon Q Developer.
8. **Cline**. The most installed open-source agent inside VS Code, and a common way into
   agents for teams that bring their own model. A new adapter.
9. **OpenCode**. An open-source, model-agnostic terminal agent; the closest peer to the
   House's own position.
10. **Goose** (Linux Foundation). Open source under neutral governance, and a reference
    for MCP-first agents.

## The low-code ten

1. **Microsoft Copilot Studio**. Agents inside Microsoft 365 and the Power Platform, with
   MCP and A2A support; the largest installed base of any low-code builder.
2. **Salesforce Agentforce**. Agents inside CRM workflows, built on a canvas and Agent
   Script.
3. **Gemini Enterprise** (Google). Agent Designer for no-code agents, beside Google's ADK
   for code.
4. **ServiceNow AI Agents**. Agents inside IT and service workflows, built in AI Agent
   Studio.
5. **Amazon Quick Suite** (AWS). Quick Flows and Quick Automate for agents over an
   organization's data.
6. **UiPath Agent Builder**. Agents beside the most widely deployed automation estate.
7. **Workato Agent Studio**. Agents ("genies") on an enterprise integration platform.
8. **n8n**. Open source and self-hostable, with agents as steps in deterministic
   workflows.
9. **Zapier Agents**. The easiest way in for people who don't build software.
10. **Dify**. Open source, with a visual builder over any model.

OpenAI's Agent Builder would have made the list, but OpenAI is winding it down on
2026-11-30 in favor of its Agents SDK, which is pro-code.

## What changes in the current list

Databricks Genie Code and Snowflake Cortex Code stay, but sit outside both tens. They are
data workspace harnesses, used inside one platform, and their install paths are guesses
marked "verify". They stay installable and aren't held to the conformance check until a
product asks for them.

Each category has a watch list, each harness on it one quarter's evidence away from its
ten. For pro-code: JetBrains Junie, Amp, Factory's Droid and Zed, and two from Microsoft
whose shape is still moving. Scout, in private and public preview, is due to be renamed
Autopilot at Microsoft Ignite in November 2026, and which harness it belongs to isn't
confirmed. Microsoft 365 Copilot is the likely answer: one harness spanning Home (chat
and cowork), Code and Autopilot. Both stay on the watch list until Microsoft says what
Autopilot is part of, and Scout's install path stays usable meanwhile. For low-code: Make,
Botpress, Langflow and IBM watsonx Orchestrate. A harness on a watch list is promoted
when it passes one already in its ten on the evidence above, and the one it passes moves
to the watch list; nothing is dropped without a note saying why.

## What aligned means

A pro-code harness is aligned when five things are true. Its row in the capability matrix
says, for each surface the House installs (rules, skills, subagents, MCP servers, hooks,
memory, permissions, and running headless), whether the harness supports it, where it
reads it from, and the vendor document and date that say so. The installers read that row
from one registry instead of their own copies. A conformance check in CI installs the
House for the harness into a sandbox and finds every file where the row says it belongs.
Barry's harness guide covers every surface, not only delegation. And Barry and Patricia
have been run in the real harness once, with the date and version recorded.

A low-code harness is aligned when its row says how it calls out (MCP servers, A2A agents,
OpenAPI connectors), how it authenticates, and what it can't do, with the vendor document
and date; a guide shows a builder adding the House's capabilities without code; and an
agent built in the platform has called hosted Patricia over A2A, or one of mcp-hive's
servers over MCP, with the date and result recorded.

An adapter folder gets content only where behavior has to diverge. The portable artifact
stays the source of truth; aligning a harness never forks a skill, a rule or an agent for
it.

## Comparing cost

Harnesses don't bill alike. Some pass a model's tokens through at its list price, some
add a fee per token, some sell credits, actions, executions or seats, and some publish no
rate at all. To compare them, the House uses one unit and records two more beside it.

**The unit is the effective US dollar price per million tokens, for input, cached input
and output, of a named model run in that harness.** Tokens are what every model is priced
in and what every harness ultimately spends, so they are the only unit that crosses all
twenty. "Effective" means what the harness charges: the model's list price plus any
harness fee, or the list price alone when a person brings their own key. A rate is always
quoted for a named model, because the same harness costs very different amounts on
different models.

Beside it, each row records the harness's **native billing unit** and its retail price
(a credit, an action, an execution, a seat), since that is what appears on the bill. Where
a harness doesn't publish tokens per unit, the effective rate can't be derived, and the
row says so instead of guessing. Those harnesses are compared by **cost per reference
task**: the recorded run of Barry and Patricia in each aligned harness doubles as a fixed
task, and the native units it consumed, at retail, are its cost. The measure that decides
anything is still cost per accepted outcome (#142); the two units here are inputs to it.

The reference models below are what the House deploys or a harness defaults to. List
prices per million tokens, input · cached input · output: Claude Sonnet 5.5 $2 · $0.10 ·
$10, Claude Opus 5.5 $4 · $0.20 · $20, Claude Fable 5.1 $10 · $0.25 · $50 and Claude
Haiku 5.5 $0.10 · $0.01 · $0.50 for prompts up to 100,000 tokens (Anthropic's model table,
checked 2026-11-10); GPT-5.5 $5 · $0.50 · $30
(OpenAI); Gemini 3.1 Pro $2 · $0.20 · $12 for prompts up to 200,000 tokens (Google).

The tables give input and output for space; each row's cached-input rate is the model's,
listed above, wherever tokens are billed at list price.

Each harness's row, with the source and date behind every value, is kept in
`harnesses.json` and rendered as [`harness-matrix.md`](harness-matrix.md); the tables
below summarize it as of 2026-11-10, and the matrix is the one to trust when they differ.

### Pro-code

| Harness | Native unit and retail price | Tokens billed at | Effective $/1M in · out |
|---|---|---|---|
| Claude Code | Plan (Pro $20, Max $100, Ultra $200 a month; Team $25 or $125 a seat), or API tokens | List | Sonnet 5.5: $2 · $10; Opus 5.5: $4 · $20 |
| GitHub Copilot | AI Credit, $0.01, spent per token at the model's rate; plans $10, $39 and $100 a month include $15, $70 and $200 of credits | List | Sonnet 5.5: $2 · $10 |
| Codex | ChatGPT plan ($20 or $200 a month), or API tokens since 2026-04-02 | List | GPT-5.5: $5 · $30 |
| Cursor | Plan allowance (Pro $20, Pro+ $60, Ultra $200, Teams $40 a user), then usage; Teams and Enterprise add a $0.25 per 1M token rate | List + $0.25 (Teams) | Sonnet 5.5: $2.25 · $10.25 (Teams) |
| Gemini CLI and Antigravity | Free tier, Google AI Pro or Ultra plan, or API tokens | List | Gemini 3.1 Pro: $2 · $12 |
| Devin Desktop | Plan (Pro $20, Max $200 a month; Teams $80 plus $40 a seat) | Not published | Not published |
| Kiro | Credit (Pro $20 for 1,000 a month; more at $0.04); credits per request vary by model | Not published | Not published |
| Cline | Free; your own key, or Cline's provider | List, no fee | As the model |
| OpenCode | Free; your own key | List, no fee | As the model |
| Goose | Free; your own key | List, no fee | As the model |

### Low-code

| Harness | Native unit and retail price | Tokens billed at | Effective $/1M in · out |
|---|---|---|---|
| Copilot Studio | Copilot Credit, $0.01 pay-as-you-go or $0.008 in a $200 pack of 25,000; a reasoning response can take 100 credits; internal use included with a $30 Microsoft 365 Copilot seat | Not published | Not published |
| Agentforce | Flex Credit, $0.005 ($500 for 100,000); a standard action is 20 credits ($0.10), a voice action 30; or $2 a conversation | Not published | Not published |
| Gemini Enterprise | Seat, $21 to $50 a month; agent usage billed separately | Not published | Not published |
| ServiceNow AI Agents | Assist, from a pool per seat; about 25 for a summary, 150 for an agentic action; no dollar price published | Not published | Not published |
| Amazon Quick Suite | Seat, $20 or $40 a month plus $250 an account; extra agent hours $3 (Flows, Automate) or $6 (Research) | Not published | Not published |
| UiPath Agent Builder | Platform Unit per model call: 0.16 basic, 0.2 standard, 0.4 premium; dollar price by contract | Not published | Not published |
| Workato Agent Studio | Genie action, one per prompt; price by quote | Not published | Not published |
| n8n | Execution, €0.008 (Starter, €20 for 2,500) to €0.005 (Pro); models on your own key | List, plus executions | As the model |
| Zapier Agents | Activity, about $0.022 (Pro, about $33 a month for 1,500) | Not published | Not published |
| Dify | Message credit, about $0.01 (Professional, $590 a year for 5,000 a month), or your own key | List on your own key | As the model |

What the tables show: every pro-code harness that bills by token passes the model's list
price through, and only Cursor's team plans add a fee. So for pro-code the choice of model
moves cost far more than the choice of harness, and the harness's real price is its seat
against the usage it includes. In low-code, eight of ten publish no tokens per unit, so
the effective rate there will come from measured reference tasks, not from price pages.

## Keeping it current

The ranking and the prices are advice about AI, so they carry their evidence and their
date and go stale like any other guide. Both are checked every quarter, as P3's "keeping
current" item describes: the surveys, vendor docs and price pages are read again, each
row older than 90 days is re-verified, and the twenty change only through a reviewed edit
to this note. A price is re-checked before any decision rests on it, whatever its age.

## Sources

Checked on 2026-11-10. Anthropic's prices come from Anthropic's model table, dated 2026-10-06 and current on 2026-11-10. The
survey figures and every other price were read from secondary reports, many of which
disagree with one another, and must be confirmed against the vendor's own page when each
harness's row is filled in.

- [Stack Overflow Developer Survey 2026, AI coding agents](https://survey.stackoverflow.co/2026/ai/data/ai-code-agent)
- [JetBrains' 2026 survey of 15,000 developers, as reported on DEV](https://dev.to/jamilxt/claude-code-overtakes-github-copilot-what-jetbrains-survey-of-15000-developers-says-about-ai-3nhc)
- [Windsurf becomes Devin Desktop (June 2026)](https://digitalapplied.com/blog/windsurf-becomes-devin-desktop-ide-migration-2026)
- [Skills CLI's list of supported agents and their skill paths](https://mintlify.com/vercel-labs/skills/guides/supported-agents)
- [AI coding tools cost compared: Copilot, Cursor, Claude Code and Codex (CloudZero)](https://www.cloudzero.com/blog/ai-coding-tools-cost/)
- [Plans vs API break-even for Claude Code, Codex, Copilot and Cursor (DEV)](https://dev.to/tokely/claude-code-codex-copilot-and-cursor-plans-vs-api-break-even-and-the-cost-of-long-sessions-2026-53d6)
- [AI coding tools pricing 2026 (Developers Digest), for Kiro, Devin and Cline](https://www.developersdigest.tech/blog/ai-coding-tools-pricing-2026)
- [OpenAI API pricing](https://developers.openai.com/api/docs/pricing) and [GPT-5.5 pricing breakdown](https://apidog.com/blog/gpt-5-5-pricing/)
- [Gemini Developer API pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Microsoft Copilot Credits guide, September 2026](https://cdn-dynmedia-1.microsoft.com/is/content/microsoftcorp/microsoft/bade/documents/products-and-services/en-us/ai/CopilotCreditsGuideSeptember2026.pdf)
- [Agentforce pricing 2026, with the math](https://www.supered.io/blog/agentforce-pricing/)
- [Gemini Enterprise pricing 2026](https://dupple.com/learn/gemini-enterprise-pricing)
- [OpenAI Agent Builder and AgentKit: what shuts down on Nov 30](https://cosupport.ai/articles/openai-agent-builder-agentkit-architecture)
- [Amazon Quick pricing](https://aws.amazon.com/quick/pricing)
- [ServiceNow AI agents: tiers and pricing](https://www.getmacha.com/blog/servicenow-ai-agents-complete-guide)
- [UiPath agents licensing](https://docs.uipath.com/agents/automation-cloud/latest/user-guide/licensing)
- [Workato Agent Studio pricing](https://docs.workato.com/en/pricing/usage-metrics/agent-studio.html)
- [n8n pricing 2026](https://coworker.ai/blog/n8n-pricing), [Zapier Agents vs n8n cost](https://www.jahanzaib.ai/blog/zapier-agents-vs-n8n-ai-agents-2026) and [Dify and Zapier credits](https://logicballs.com/blog/best-no-code-ai-agent-builder)
- [Low-code AI agent platforms 2026 (Botpress)](https://botpress.com/blog/low-code-ai-agent-platforms)
