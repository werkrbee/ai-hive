"""Patricia's review over MCP: one read-only tool, `review`, on the same server as her A2A
endpoint (docs/low-code-alignment.md).

The tool's input schema is the contract's `inputs` and its output schema the contract's
`output`, and a call runs review.Reviewer's check_value and review, so it is held to the
same contract, budget, ledger and monthly ceiling as an A2A task. It keeps no task: the
verdict comes back in the reply, as structured content and as its JSON in a text block.
A ceiling or allowance refusal is a tool error whose second text block is the same JSON
the A2A refusal carries; a call past the client's hourly rate gets 429 (limits.py). The
server offers no resources, prompts, sampling or elicitation.

Transport: Streamable HTTP at /mcp, POST only, answered with plain JSON and no session.
It speaks MCP 2026-07-28, statelessly: a request whose `_meta` names its protocol version
is checked against the MCP-Protocol-Version, Mcp-Method and Mcp-Name headers and served
on its own, and server/discover is offered. It also answers the `initialize` handshake of
2025-11-25 and 2025-06-18, which the low-code platforms' clients still use, without
minting a session. GET and DELETE get 405, and a request from a browser origin other than
this server's gets 403.

Auth is the A2A server's (auth.py): every request to /mcp needs an app token from an
allowlisted client with the required role. A request without a valid token gets 401 with
a WWW-Authenticate header naming the Protected Resource Metadata (RFC 9728), which, like
the Server Card, is served without a token.
"""
import json
import logging
import uuid
from urllib.parse import urlparse

from starlette.responses import JSONResponse
from starlette.routing import Route

from a2a.utils.errors import InvalidParamsError

from .mcp_protocol import (Protocol, MODERN, LEGACY, VERSION_KEY, INVALID_PARAMS,
                           _error, _result)

log = logging.getLogger("hive_a2a")

PATH = "/mcp"
CARD_PATH = "/.well-known/mcp/server-card.json"
METADATA_PATHS = ("/.well-known/oauth-protected-resource" + PATH, "/.well-known/oauth-protected-resource")
TOOL = "review"


def origin(config):
    u = urlparse(config.public_url)
    return f"{u.scheme}://{u.netloc}"


def endpoint(config):
    return origin(config) + PATH


def metadata_url(config):
    return origin(config) + METADATA_PATHS[0]


def challenge(config):
    """The WWW-Authenticate header a request to /mcp without a valid token gets."""
    return f'Bearer resource_metadata="{metadata_url(config)}", scope="{config.auth.scope}"'


def tool(config):
    c = config.contract
    return {
        "name": TOOL,
        "title": f"{config.persona.capitalize()}'s {config.capability}",
        "description": c["description"],
        "inputSchema": c["inputs"],
        "outputSchema": c["output"],
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    }


def server_card(config, version):
    return {
        "$schema": "https://static.modelcontextprotocol.io/schemas/v1/server-card.schema.json",
        "name": f"io.werkrbee/{config.persona}",
        "version": version,
        # the card schema allows 100 characters; the tool carries the contract's description
        "description": f"{config.persona.capitalize()}'s {config.capability} as one read-only MCP tool: "
                       "a verdict against the Charter.",
        "remotes": [{"type": "streamable-http", "url": endpoint(config),
                     "supportedProtocolVersions": [*MODERN, *LEGACY]}],
    }


def resource_metadata(config):
    """Protected Resource Metadata (RFC 9728) for /mcp: Entra issues its tokens."""
    return {
        "resource": endpoint(config),
        "authorization_servers": [config.auth.issuer],
        "scopes_supported": [config.auth.scope],
        "bearer_methods_supported": ["header"],
        "resource_name": f"{config.persona.capitalize()} ({config.capability})",
    }


class Server(Protocol):
    def __init__(self, config, reviewer, version):
        self.config = config
        self.reviewer = reviewer
        self.version = version
        self.tool = tool(config)
        super().__init__(config.public_url, [self.tool])

    def routes(self):
        return [Route(CARD_PATH, self.card, methods=["GET"]),
                *(Route(p, self.metadata, methods=["GET"]) for p in METADATA_PATHS),
                Route(PATH, self.handle, methods=["POST", "GET", "DELETE"])]

    async def card(self, request):
        return JSONResponse(server_card(self.config, self.version))

    async def metadata(self, request):
        return JSONResponse(resource_metadata(self.config))

    async def call(self, request, id_, params, extra):
        if params.get("name") != TOOL:
            return _error(id_, INVALID_PARAMS, f"no tool named {params.get('name')!r}")
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            return _error(id_, INVALID_PARAMS, "arguments must be an object")
        try:
            _, plan = self.reviewer.check_value(arguments)
        except InvalidParamsError as e:
            refused = [{"type": "text", "text": f"Refused: {e.message}"}]
            return _result(id_, {**extra, "isError": True, "content": refused})
        # A key for the ledger's calls in flight; nothing about the call is kept after it.
        key = f"mcp-{uuid.uuid4()}"
        client = request.scope.get("auth", {}).get("client")
        log.info("review %s for %s over MCP", key, client)
        outcome = await self.reviewer.review(plan, key, client=client)
        if outcome.state == "completed":
            return _result(id_, {**extra, "content": [{"type": "text", "text": json.dumps(outcome.verdict)}],
                                 "structuredContent": outcome.verdict})
        content = [{"type": "text", "text": outcome.text}]
        if outcome.data is not None:
            content.append({"type": "text", "text": json.dumps(outcome.data)})
        return _result(id_, {**extra, "isError": True, "content": content})

    def server_info(self):
        return {"name": self.config.persona, "version": self.version}

    def instructions(self):
        return (f"Call `{TOOL}` with a proposed action, plan or change and its context to get "
                f"{self.config.persona.capitalize()}'s verdict against the Queen Bee's Charter. It reviews only.")
