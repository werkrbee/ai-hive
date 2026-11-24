# The House in Copilot Studio

How a builder adds the House's one hosted capability, Patricia's governance review, to an
agent in Microsoft Copilot Studio without writing code. Checked on 2026-11-21 against
Microsoft Learn's pages on connecting an MCP server and an A2A agent, custom connectors
and Entra authentication, harnesses, and billing rates, and Microsoft's Copilot Credits
Guide of November 2026; the matrix row in `harnesses.json` names each one. The connection
was made and recorded on 2026-11-23, from a standard-harness agent in a trial, and the
steps below are the ones that worked; where the screens differed from Microsoft's pages,
they follow the screens.

Copilot Studio is where people build agents of their own. It isn't Microsoft 365 Copilot,
the separate harness in the Copilot app whose concerns are Home (chat and cowork),
Autopilot and Code (`m365-copilot.md`), and it isn't the pro-code GitHub Copilot harness.
An agent built in Copilot Studio can be published into Microsoft 365 Copilot or Teams, but
it is built, connected and billed in Copilot Studio.

## What the House offers here

Copilot Studio reads none of the House's files from a folder, so it reaches the House only
through something the House hosts (`docs/low-code-alignment.md`). That is hosted Patricia's
`governance-review`: the builder's agent sends a proposed action with its context and gets
back her verdict, `allow`, `allow-with-conditions` or `block`, with her reasons. Hosted
Barry isn't offered, since his approvals would be answered by the same agent that asked.

Agents on the Microsoft Copilot harness can also take an uploaded Agent Skills package, so
Patricia's `SKILL.md` folder could be uploaded as it is. That gives the agent her
instructions to follow by itself, not her review: no contract check, no ledger, no
ceiling, and nothing outside the agent deciding. This guide is about the hosted review.

## Which harness

Copilot Studio runs every agent on one of three harnesses. The **standard harness** runs
rule-based agents with topics and agent flows; the **Microsoft Copilot harness** runs
agents that plan through a goal on their own, with skills, memory and files; the
**Customer Conversation harness** runs customer-facing chat and voice agents. All three
can call MCP servers and connected agents.

Use the standard harness. Microsoft's pages on connecting an MCP server or an A2A agent are
written for it, its credits per feature are published, it bills only once an agent is
published, and its use in Microsoft's own channels by someone with a Microsoft 365 Copilot
seat costs no credits. The Microsoft Copilot harness bills tokens, tools and runtime from
the first build, test runs included, and publishes ranges per task rather than rates.

The Microsoft Copilot harness is where Copilot Studio now opens. To reach the standard
harness, select the three dots (**…**) at the bottom of the home page's side bar and then
**Open classic experience**, which lasts only for that session, or start the agent from
**Other ways to build** on the home page. An agent's URL that ends in `/bots/<id>/...` is
on the standard harness.

## The binding and the sign-in

Connect Patricia as an **MCP server**, signing each user in with **OAuth 2.0**.

Copilot Studio documents no client-credentials option for an MCP server or an A2A agent:
its OAuth 2.0 choice signs the agent's user in and sends that user's token. So the call
carries a delegated token, which Patricia accepts for reviews only, with the
`Review.RequestAsUser` scope, from a client app on her allowlist, for a user assigned to
her API app. She uses the user's identity only to keep their tasks apart; her ledger and
allowance name the client app, not the user. An API key is refused on every binding, and
Copilot Studio's API key option would have each user type the key.

MCP rather than the other two:

- **A2A** works in Copilot Studio (**Agents** > **Add agent** > **A2A agent**, with the
  same OAuth choices), but Microsoft's example payload calls `message/send`, the v0.3
  method, and Patricia serves A2A v1.0, whose method is `SendMessage`. Until a call shows
  which one Copilot Studio sends, MCP is the safer route. Copilot Studio also sends the
  whole chat history in each A2A message's metadata, which Patricia drops before a task is
  stored.
- **OpenAPI**, through a custom connector, needs an OpenAPI 2.0 file; Patricia publishes
  OpenAPI 3.0.3 at `/openapi.json`, which the connector wizard doesn't import. A connector
  also can't be created with a client-credentials security definition.

Copilot Studio's MCP client speaks Streamable HTTP only, which is what Patricia serves at
`/mcp`. It opens with the older `initialize` handshake, which she answers for the
2025-11-25 and 2025-06-18 revisions, and then sends no `MCP-Protocol-Version` header, so
she serves a request without one. Until that change (pull request 363, deployed on
2026-11-23) she refused it, and Copilot Studio showed "We couldn't find the resource you
requested".

## Before you start

The House's maintainer does these, each a change to Entra or the deployment that waits for
their yes:

1. Register a client app for the Copilot Studio tenant with `entra.sh`
   (`./entra.sh --agent patricia copilot-studio` makes `copilot-studio-patricia-client`),
   and add its client ID to Patricia's `allowedClients` through `deploy.sh`'s gated steps.
2. Give that client app a delegated permission for Patricia's `Review.RequestAsUser` scope,
   grant admin consent, and add a client secret (or a federated credential). `entra.sh`
   creates no secrets and doesn't add a delegated permission or a redirect URI.
3. Assign each user who will run the agent to Patricia's API app, which requires an
   assignment before it issues anyone a token.

The builder then needs the client ID, the secret, the tenant ID and Patricia's API app ID,
and a way into Copilot Studio. Microsoft offers four: the free Copilot Studio user
license, which needs the tenant to have a prepaid Copilot Credit pack first; the
**Copilot Studio authors** role, with pay-as-you-go billing linked to an Azure
subscription; a Microsoft 365 Copilot license, which builds agents for the Microsoft
Copilot harness, not the standard one; or a trial, signed up for with a work account,
which can test in the test chat but can't publish (Microsoft Learn, "Standard harness
licensing", checked 2026-11-23). A trial is enough to make and test the connection.

## Connecting Patricia

1. Open the agent in Copilot Studio and go to **Tools** > **Add a tool** > **New tool** >
   **Model Context Protocol**.
2. Name it **Patricia**, describe it as "Reviews a proposed action against the Queen Bee's
   Charter before the agent takes it, and returns allow, allow with conditions, or block,
   with reasons", and set the **Server URL** to
   `https://patricia-a2a.kindpebble-873b1da9.eastus2.azurecontainerapps.io/mcp`.
3. Choose **OAuth 2.0**, then **Manual**: Entra doesn't offer the dynamic client
   registration that Copilot Studio's other two OAuth types need. Enter the client ID and
   secret, `https://login.microsoftonline.com/<tenant>/oauth2/v2.0/authorize` as the
   **Authorization URL**, `https://login.microsoftonline.com/<tenant>/oauth2/v2.0/token` as
   both the **Token URL template** and the **Refresh URL**, and
   `api://<api-app-id>/Review.RequestAsUser offline_access` as the **Scopes**.
4. Select **Create**, copy the **callback URL** it shows (it begins
   `https://global.consent.azure-apim.net/redirect/`), and give it to the maintainer to add
   to the client app as a web redirect URI. Sign-in fails until it's there.
5. Select **Next**, create a connection, signing in as an assigned user, and select **Add
   and configure**. The tool list should show one tool, `review`. Where the settings ask
   which credentials to use, choose the end user's, so that each person signs in as
   themselves.

The connection signs in through a pop-up window that Safari blocks even with pop-ups
allowed for Copilot Studio, since it opens from another Microsoft domain; use Edge or
Chrome, or allow pop-ups and cross-site tracking in Safari while you connect.

The connection is a Power Platform connector underneath, so a data policy that governs
connectors in the environment governs this one too.

## Acting on the verdict

A review gates nothing by itself. Patricia reads the proposal and returns a verdict; the
agent is still the one acting, and the verdict binds it only as far as the builder makes
it. In the agent's **Instructions**, say when to ask and what to do with the answer, for
example: "Before you send, share, delete or change anything for the user, call Patricia's
`review` with the proposed action as `proposal` and what the user asked as `context`. If
the verdict is `block`, don't do it; tell the user her reasons. If it is
`allow-with-conditions`, meet each condition first." The reference task, the proposal
"Force-push main to drop one commit." with the context "Requested in chat.", came back
`block` in the recorded call: she named the missing repository, commit and approval, and
the agent took no action and offered `git revert` instead.

Instructions steer generative orchestration but don't guarantee it. Whether a topic can
call the MCP tool and branch on its `verdict` with a **Condition** node, which would make
the stop on `block` deterministic, the recorded call didn't test.

## What this can't do

It can't call Patricia without a signed-in, assigned user, so an agent that runs on a
trigger with nobody signed in can't use it. It can't reach hosted Barry, mcp-hive's local
servers or any product's MCP server. It doesn't make Copilot Studio enforce a verdict.
Every review spends from Patricia's $5 month, beside hosted Barry's approval reviews, and
her per-client limits hold the client app to 30 reviews an hour and to half of that $5. A
review answers within her 600-second budget, in the reply to the call, so nothing polls.

## Usage and cost

Copilot Studio's meter is the agent's **Monitor** page, which shows the credits it has
used and, when a breakdown is available, what used them; across an environment it is
**Licensing** > **Copilot Studio** in the Power Platform admin center. On the standard
harness a turn that calls the review costs credits for what the agent did around it: 2 for
a generative answer, 5 for each agent action, plus 10 per 1,000 billed tokens when a
reasoning model orchestrates. At $0.01 a credit pay-as-you-go, a turn with one answer and
one action on a non-reasoning model is 7 credits, 7 cents, and a reasoning model adds a
dollar for every 10,000 tokens it's billed for. Test-chat turns aren't billed
on the standard harness, and a user with a Microsoft 365 Copilot seat pays nothing in
Microsoft's channels, within fair use. The House's meter is Patricia's ledger, about a
cent a review, kept apart from the platform's cost; the recorded call's entry was 4,726
tokens and $0.0124, under the client app's ID, and over MCP it has no task, so it is found
by time.
