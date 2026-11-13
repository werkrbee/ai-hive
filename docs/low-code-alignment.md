# The low-code alignment pattern: design note

Status: accepted (#244). It decides how the House reaches the low-code ten before any
platform issue (#245–#254) starts, as `hives/agents-hive/design/hosted-barry.md` did for
hosted Barry. It ends with what each platform issue does and the implementation issues
that come first. Platform facts were checked on 2026-11-12 against the sources at the end;
each platform issue re-checks its own against the vendor's docs.

## The problem

A pro-code harness reads the House from files: the rules, skills and agents installers
write `AGENTS.md`, `SKILL.md` and agent files where its row says. A low-code platform
reads none of them. Its builders add capabilities by pointing the platform at something
on the network: an A2A agent, an MCP server or an HTTP API described in OpenAPI, with a
credential kept in the platform's own connection store. So the House reaches a low-code
platform only through something it hosts, and only as far as the platform's connection
options and the House's auth let a call through.

What the House hosts today:

- **Hosted Patricia** (`governance-review`), on Azure Container Apps. A2A v1.0 over the
  JSON-RPC binding only, no streaming. Every call but the Agent Card needs an Entra app
  token from the client-credentials flow, from a client on `auth.allowed_clients`, with
  the `Review.Request` role; a delegated (user) token is refused. Each call is metered
  into her ledger and held to a $5 monthly ceiling (`servers/a2a/README.md`).
- **Hosted Barry** (`orchestration`), beside her, with the same auth plus per-method
  roles, and approvals that a product answers as an attestation that its person decided.
- **verify-mcp**, a stand-in for a product's MCP server that only Barry's identity may call.

mcp-hive's registry is the other candidate, but none of its servers suits a platform.
filesystem, git and fetch run on a developer's machine over stdio, which no hosted
platform can reach, and huggingface is a third party's server, so calling it proves
nothing about the House.

## What the platforms support

On 2026-11-12, from the sources below. "Vendor" marks a vendor's own doc; anything else is
a secondary report the platform issue confirms first.

| Platform | A2A | MCP | OpenAPI or HTTP | App token (client credentials) |
|---|---|---|---|---|
| Copilot Studio | Yes: None, API key, or OAuth 2.0 with sign-in (vendor) | Yes, Streamable HTTP only: None, API key, or OAuth 2.0 with sign-in (vendor) | Custom connectors from an OpenAPI file (vendor) | Not documented for A2A or MCP |
| Agentforce | Beta | Client in beta, Streamable HTTP, with no auth or client credentials through a named credential | External Services, to verify | Yes, for MCP (secondary) |
| Gemini Enterprise | Preview, registered by an admin, v0.3 (v1.0 through the SDK's compatibility layer); a user's OAuth token, or a Google ID token for Cloud Run only; no API keys or static headers (vendor) | Remote servers through Agent Registry (vendor); Agent Designer not documented | Not checked | No |
| ServiceNow AI Agents | External agents, OAuth through a connection alias (vendor) | Client in AI Agent Studio: OAuth 2.1, API key or a connection alias (vendor) | Not checked | Through a connection alias, to verify |
| Amazon Quick Suite | Not found | Remote only, Streamable HTTP preferred: user OAuth, service (client credentials) or none; no custom headers; 5-minute timeout (vendor) | Actions from an OpenAPI 3 spec | Yes, for MCP (vendor) |
| UiPath Agent Builder | Preview, through Agent Gateway; upstream auth by static headers or an Orchestrator connection (vendor) | Remote servers proxied by Orchestrator: a static token, or an MCP connection for OAuth (vendor) | Integration Service, to verify | Through a connection, to verify |
| Workato Agent Studio | A connector for recipes: client credentials, API key or none (vendor) | Genies as clients: a token, or OAuth2 with optional verified user (vendor) | HTTP connector, to verify | Yes, for A2A in a recipe (vendor) |
| n8n | No built-in node; community nodes | MCP Client Tool: bearer, headers or OAuth2 (vendor) | HTTP Request node, to verify | n8n's OAuth2 credential, to verify |
| Zapier Agents | Not found | An MCP server as an action, auth not documented | API requests, to verify | Unknown |
| Dify | A community plugin (v0.3) | HTTP only: static or forwarded headers, or OAuth with registration or a client ID (vendor) | Custom tools from OpenAPI, to verify | Not documented |

Three things follow. MCP is the binding nearly every platform has; A2A is in preview,
beta or missing on most of them, and some of those that have it speak v0.3, not the v1.0
the House serves. Few platforms document a client-credentials token for every binding,
and some (Copilot Studio, Gemini Enterprise) sign a user in instead. And no platform
needs anything from the House but a URL, a credential and a schema, so nothing about a
platform belongs in an adapter folder.

## What the House offers

One capability: Patricia's `governance-review`. A builder's agent sends a proposed action,
plan or change, with its context, and gets back her verdict (`allow`,
`allow-with-conditions` or `block`) in the contract's output shape. It is the capability
that is useful to anyone building agents, the one the House already hosts, and the one a
caller can use without being trusted with anything.

The House serves it over three bindings, all from the same server, so the auth, contract
checks, budget, ledger and ceiling are one implementation:

- **A2A**, as today: the JSON-RPC binding at the endpoint the Agent Card names.
- **MCP**: a Streamable HTTP endpoint on the same server, with one tool, `review`, whose
  input schema is the contract's `inputs` and whose output schema is its `output`, so the
  verdict comes back as structured content. The tool is marked read-only, and the server
  offers no resources, prompts, sampling or elicitation. It publishes a Server Card, and
  mcp-hive gets a remote entry, `servers/patricia`, that points at it, so hosted Patricia
  becomes the mcp-hive server a platform calls, and pro-code harnesses can install her too.
- **OpenAPI**, where a platform has neither, or where its A2A and MCP options can't carry
  a token Patricia accepts: A2A's own HTTP+JSON binding, which the server adds and the card
  declares, described by an OpenAPI 3.0 document with one operation, `SendMessage`. It is
  rendered from the contract, as the Agent Card is, with the request's data part narrowed
  to the contract's `inputs` and the reply's artifact to its `output`. It is a description
  of the standard binding, not a fourth API.

A review answers in the reply to the call. It returns a completed task (A2A) or a tool
result (MCP) within the contract's 600-second budget, so a platform needs no polling, push
notifications or streaming. A platform's own time limit can be shorter, as Quick's five
minutes is, and its platform issue records that limit.

What isn't offered, and why:

- **Hosted Barry.** His gated actions pause for a person, and the client that started the
  task answers as the product's attestation that its person asked them through its own
  sign-in (`servers/a2a/README.md`, "Approvals"). A platform's agent that started the task
  would be answering its own approval, attesting to nobody, and an agent must never answer
  its own approvals (`hives/workflows-hive/README.md`, "The review queue"). Opening Barry
  beyond werkrbee products is the ROADMAP's "Public A2A access" item, which needs signed
  passports first.
- **Product MCP servers registered for Barry**, such as verify-mcp. Their gating is done by
  Barry's engine, under the caller's approval policy, not by the server, so a platform
  calling one directly would skip the approval policy. They accept only Barry's identity.
- **The review queue's MCP server.** It is answered by a person through elicitation, runs
  over stdio, and an agent must never answer its own queue.
- **mcp-hive's local servers.** A platform can't reach a developer's stdio process, and a
  platform that can run one, a self-hosted n8n or Dify, gains the platform's own tools, not
  the House's.

## Auth

**The identity.** Every call comes from an Entra identity on Patricia's
`auth.allowed_clients` holding `Review.Request`, on every binding. Each platform tenant
the House aligns with gets its own Entra client app, made by `entra.sh` and added to the
allowlist through `deploy.sh`'s gated steps, so one platform's credential can be revoked
without touching another's. Its secret or certificate lives in the platform's connection
store (a Power Platform connection, a Salesforce named credential, a Workato connection),
never in the repository, a prompt or an agent's instructions. Patricia never sees it:
the platform presents a token, and the token is all the server reads. A platform client
stays on the allowlist while its platform issue and the quarterly check need it. Keeping
one there for real users is the ROADMAP's public-access item, not alignment.

**App tokens first.** A platform that can fetch a client-credentials token uses that, and
nothing in the server changes. Amazon Quick Suite (service authentication), Agentforce
(a named credential) and Workato (its A2A connector) document one; ServiceNow, UiPath and
n8n may have one through a connection, which their issues confirm. Two Entra details the
guides must carry: Entra doesn't support dynamic client registration, so the client ID and
secret are entered by hand, and a platform that sends a `resource` parameter, as Quick
does under the MCP authorization spec, needs the API app set up for it (Quick's docs name
the Entra error and its fix). The MCP endpoint publishes Protected Resource Metadata (RFC
9728) naming Entra as its authorization server, so a platform that discovers auth that
way finds it.

**Delegated tokens, for reviews only.** Copilot Studio and Gemini Enterprise sign a user in
and send that user's token; neither documents a client-credentials option for A2A or MCP.
So Patricia will also accept a delegated token from a registered platform client, on two
conditions: it carries a delegated scope her API app exposes, `Review.Request`, and its
`azp` is on the allowlist. The API app already requires assignment, so only users assigned
to it can get one. Patricia uses the user's identity for nothing: tasks still belong to
the client, and nothing about the user is logged or stored. This loosens a rule the server
has today, and only for her: hosted Barry keeps refusing delegated tokens, because his
approvals rest on the product client's attestation. The change is an implementation issue
below, and it changes Entra, so it waits for the maintainer's yes.

**What stays refused.** Unauthenticated calls, and static API keys or headers, on every
binding. A key isn't an Entra identity the allowlist and roles can check, and the server
has no way to rotate or revoke one. A platform that offers only those (on what's
documented today, possibly Zapier Agents) can't call Patricia, and its row says so; that is
a finding, not a failure of its issue.

**Within the approval policy.** A review is not an action the Charter gates. Patricia's
passport grants `fs.read` only, her contract gates nothing, and she reads the proposal and
returns a verdict without acting anywhere. The platform's agent remains the actor, and the
verdict binds it only as far as the builder's flow makes it, for example a condition that
stops on `block`. Each guide says so plainly and shows the condition: the House doesn't
claim to gate a platform's actions.

**Within the sub-agent boundary.** To the platform's agent, Patricia is a delegate, so the
Charter's sub-agent rules apply from her side. She receives only the contract's input,
never the platform's conversation. Copilot Studio sends the whole chat history in a
message's metadata (`copilotstudio.microsoft.com/a2a/chathistory`), and the SDK's task
store keeps a message as sent, so the server will drop metadata a capability doesn't
read before the task is stored (Barry reads `trigger` and `facts`; Patricia reads none).
Her prompt is built from the shared files only, each call stands alone, and nothing one
caller sends reaches another's call, as the cache-scope test already checks. She has no
tools in the platform and never calls back into it.

**The ceiling.** Platform calls spend against Patricia's $5 month, beside hosted Barry's
approval reviews. A platform that loops can use it up. Barry's approvals then reach the
person marked `unreviewed`, which is safe, and the refusal says when reviews resume. A review
costs about a cent, so the ten recorded calls cost about ten cents.

## What the recorded call proves

Each platform issue records one call from an agent built in the platform to hosted
Patricia. Every platform makes the same call, the reference task: the proposal
"Force-push main to drop one commit." with the context "Requested in chat.", whose verdict
should be `block`. A fixed task makes the ten comparable for the cost report (#255)
and checks the answer as well as the plumbing.

It proves five things:

- A builder connected the House to the platform without code, through the platform's
  own connection screens, on the binding the issue names.
- The call authenticated as that platform's registered identity, by the route the issue
  names (an app token or a delegated one).
- The platform sent the contract's input and accepted its output: the verdict came back
  valid and the platform's agent used it, in its reply or its flow.
- Patricia received only the contract's input.
- What the call consumed, on both meters below.

It doesn't prove that Patricia's verdicts are good, which her trust evaluation measures;
that the platform enforces the verdict, which its builder decides; or that the platform
works at volume, under other users or on other tasks.

## Units consumed

A call is metered twice, and the two meters stay apart.

**The platform's meter** is the harness's cost, the figure that goes in the cost columns.
The units the platform charged for the run (Copilot Credits, Flex Credits, Assists, agent
hours, Platform Units, genie actions, executions, activities or message credits) are read
from the platform's own usage report, which the run names. Where the report doesn't break
usage down by run, the units are worked out from the platform's published rates for what
the run did and marked estimated; where neither is possible, they are recorded as not
reported, never as zero. Their cost is the units at the row's retail price. Tokens come
from the platform only where it reports them, which on own-key platforms (n8n, Dify) means
the model provider's usage for the run; elsewhere they are unknown, not zero, which is why
eight of the ten publish no effective rate.

**The House's meter** is what Patricia's review cost werkrbee: her ledger entry for the
call, with its tokens and estimated dollars. It is recorded beside the run but never added
to the platform's cost, since a builder pays it only if the House charges for it, and it
doesn't today. A review's ledger entry doesn't yet name its task, so it is found only by
time; the entry will carry the task ID.

A pro-code run's row records Barry and Patricia with tokens in four counts. A low-code
run records the binding, the auth route, the platform's units with their basis and
source, the platform's tokens where known, the House's tokens and dollars, and the
verdict. A low-code row is verified only with a run of Patricia, as a pro-code row needs
runs of both agents. `scripts/harnesses.py` gets that shape and that check before the first
recorded call.

## What each platform issue does

1. Re-check the platform's row against the vendor's docs and price page: how it calls out
   over each binding, how it authenticates, its limits (timeouts, tool counts, headers,
   A2A version), and what it can't do, with each source and its date.
2. Choose the binding and auth route: MCP with an app token where the platform offers one,
   otherwise MCP or A2A with a delegated token, otherwise OpenAPI. Say why.
3. With the maintainer's yes, register the platform's Entra client app and add it to
   Patricia's allowlist. That changes Entra and Azure.
4. Write the guide in Barry's harness references: a builder connecting Patricia through
   the platform's screens, the condition that stops on `block`, what the guide can't do,
   and where the platform's usage report is.
5. Make the reference call from an agent built in the platform, and record it in the row,
   with both meters.
6. Mark the row verified once it has no unknowns and records the run.

A platform account or trial, and any spend, wait for the maintainer's yes as well.

## Implementation issues

Created on acceptance, to be done before the first platform's recorded call:

1. **agents-hive: Patricia over MCP** (#298). The Streamable HTTP endpoint and its
   `review` tool on the A2A server, the Server Card and Protected Resource Metadata,
   mcp-hive's `servers/patricia` entry, and tests through the same auth, contract, budget
   and ledger.
2. **agents-hive: the HTTP+JSON binding and its OpenAPI document** (#299). The binding on
   the server, declared in the card, and the OpenAPI 3.0 document rendered from the
   contract.
3. **agents-hive: delegated tokens for reviews** (#300). The delegated scope on
   Patricia's API app in `entra.sh`, and `auth.py` accepting one from an allowed `azp` for
   `governance-review` only, deciding whether one platform client's users share their tasks or each sees only
   their own. Deployed through the gated steps.
4. **agents-hive: the boundary and the ledger** (#301). Drop message metadata a
   capability doesn't read before a task is stored, and put the task ID in a review's
   ledger entry.
5. **scripts: low-code runs in the registry** (#302). The low-code run shape in
   `harnesses.json`, its check, the matrix's columns for it, and the rule that a verified
   low-code row records a run of Patricia.

A2A v0.3 is left to the platform issues. Gemini Enterprise documents v0.3, and Copilot
Studio's example payload uses v0.3's `message/send`; if either can't reach the v1.0
endpoint, its issue files the server change. Both also have MCP.

## Sources

Checked on 2026-11-12.

- [Copilot Studio: connect an agent over A2A](https://learn.microsoft.com/en-us/microsoft-copilot-studio/add-agent-agent-to-agent) (updated 2026-10-15)
- [Copilot Studio: connect an existing MCP server](https://learn.microsoft.com/en-us/microsoft-copilot-studio/mcp-add-existing-server-to-agent) (updated 2026-11-02)
- [Salesforce: three ways to connect Agentforce to external MCP servers](https://www.salesforce.com/blog/connect-agentforce-external-mcp-servers/) and [Agentforce MCP: connecting external systems (Vantagepoint)](https://vantagepoint.io/blog/sf/agentforce-mcp-connect-external-systems-guide)
- [Gemini Enterprise: register and manage A2A agents](https://docs.cloud.google.com/gemini/enterprise/docs/register-and-manage-an-a2a-agent) and [Agent Registry](https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/agent-registry)
- [ServiceNow: connecting to an MCP server from an MCP client](https://www.servicenow.com/docs/r/zurich/intelligent-experiences/connect-mcp-server-client.html) and [set up Google A2A](https://www.servicenow.com/docs/r/intelligent-experiences/set-up-google-a2a.html)
- [Amazon Quick: MCP integration](https://docs.aws.amazon.com/quick/latest/userguide/mcp-integration.html) and [MCP and OpenAPI integration patterns in Amazon Quick (re:Post)](https://repost.aws/articles/ARJ4ZM_8tLTIWg1HNVRm1gUg/bridging-systems-and-ai-a-technical-deep-dive-into-mcp-and-openapi-integration-patterns-in-amazon-quick)
- [UiPath: outbound A2A](https://docs.uipath.com/orchestrator/automation-cloud/latest/user-guide/outbound-a2a) and [MCP server types](https://docs.uipath.com/orchestrator/automation-cloud/latest/user-guide/mcp-server-types)
- [Workato: A2A Protocol connector](https://docs.workato.com/en/connectors/a2a) and [genies as MCP clients](https://docs.workato.com/en/mcp/genies-as-mcp-clients)
- [n8n: MCP Client Tool node](https://docs.n8n.io/integrations/builtin/cluster-nodes/sub-nodes/n8n-nodes-langchain.toolmcp/)
- [Zapier MCP](https://docs.zapier.com/mcp/get-started/connect) and [Zapier MCP in an agent builder (Pickaxe)](https://pickaxe.co/learn/zapier-integration)
- [Dify: using MCP tools](https://docs.dify.ai/en/guides/tools/mcp) and [the A2A Client plugin](https://marketplace.dify.ai/plugin/ryan_duff/dify-a2a-plugin)
