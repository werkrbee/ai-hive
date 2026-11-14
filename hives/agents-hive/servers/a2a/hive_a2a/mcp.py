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
import base64
import json
import logging
import uuid
from urllib.parse import urlparse

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from a2a.utils.errors import InvalidParamsError

log = logging.getLogger("hive_a2a")

PATH = "/mcp"
CARD_PATH = "/.well-known/mcp/server-card.json"
METADATA_PATHS = ("/.well-known/oauth-protected-resource" + PATH, "/.well-known/oauth-protected-resource")
MODERN = ("2026-07-28",)
LEGACY = ("2025-11-25", "2025-06-18")
VERSION_KEY = "io.modelcontextprotocol/protocolVersion"
TOOL = "review"
# JSON-RPC error codes: the spec's own, then MCP's
PARSE, INVALID_REQUEST, NO_METHOD, INVALID_PARAMS = -32700, -32600, -32601, -32602
HEADER_MISMATCH, UNSUPPORTED_VERSION = -32020, -32022


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


def _decode(value):
    """A header value, with MCP's Base64 sentinel (=?base64?...?=) decoded."""
    if value and value.startswith("=?base64?") and value.endswith("?="):
        try:
            return base64.b64decode(value[9:-2], validate=True).decode("utf-8")
        except ValueError:
            return None
    return value


def _error(id_, code, message, status=200, data=None):
    error = {"code": code, "message": message, **({"data": data} if data is not None else {})}
    return JSONResponse({"jsonrpc": "2.0", "id": id_, "error": error}, status_code=status)


def _result(id_, result):
    return JSONResponse({"jsonrpc": "2.0", "id": id_, "result": result})


class Server:
    def __init__(self, config, reviewer, version):
        self.config = config
        self.reviewer = reviewer
        self.version = version
        self.tool = tool(config)

    def routes(self):
        return [Route(CARD_PATH, self.card, methods=["GET"]),
                *(Route(p, self.metadata, methods=["GET"]) for p in METADATA_PATHS),
                Route(PATH, self.handle, methods=["POST", "GET", "DELETE"])]

    async def card(self, request):
        return JSONResponse(server_card(self.config, self.version))

    async def metadata(self, request):
        return JSONResponse(resource_metadata(self.config))

    async def handle(self, request: Request):
        if request.method != "POST":
            return Response(status_code=405, headers={"allow": "POST"})
        sent_from = request.headers.get("origin")
        if sent_from is not None and sent_from != origin(self.config):
            return _error(None, INVALID_REQUEST, f"origin {sent_from} is not allowed", status=403)
        try:
            body = json.loads(await request.body())
        except ValueError:
            return _error(None, PARSE, "the body is not JSON", status=400)
        if not isinstance(body, dict) or body.get("jsonrpc") != "2.0" or not isinstance(body.get("method"), str):
            return _error(None, INVALID_REQUEST, "send one JSON-RPC 2.0 request", status=400)
        if "id" not in body:  # a notification, such as a legacy client's notifications/initialized
            return Response(status_code=202)
        id_, method, params = body["id"], body["method"], body.get("params") or {}
        if not isinstance(params, dict):
            return _error(id_, INVALID_PARAMS, "params must be an object")
        meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
        if VERSION_KEY in meta:
            return await self.modern(request, id_, method, params, meta[VERSION_KEY])
        return await self.legacy(request, id_, method, params)

    async def modern(self, request, id_, method, params, version):
        """A 2026-07-28 request: its headers must match its body, and it stands alone."""
        headers = request.headers
        if headers.get("mcp-protocol-version") != version:
            return _error(id_, HEADER_MISMATCH, "the MCP-Protocol-Version header must match the request's "
                                                "protocol version", status=400)
        if version not in MODERN:
            return _error(id_, UNSUPPORTED_VERSION, "Unsupported protocol version", status=400,
                          data={"supported": list(MODERN), "requested": version})
        if headers.get("mcp-method") != method:
            return _error(id_, HEADER_MISMATCH, "the Mcp-Method header must match the request's method", status=400)
        if method == "tools/call" and _decode(headers.get("mcp-name")) != params.get("name"):
            return _error(id_, HEADER_MISMATCH, "the Mcp-Name header must match the tool's name", status=400)
        if method == "server/discover":
            return _result(id_, {"resultType": "complete", "supportedVersions": list(MODERN),
                                 "capabilities": {"tools": {}}, "_meta": {
                                     "io.modelcontextprotocol/serverInfo": self.server_info()},
                                 "instructions": self.instructions()})
        if method == "tools/list":
            return _result(id_, {"resultType": "complete", "tools": [self.tool]})
        if method == "tools/call":
            return await self.call(request, id_, params, {"resultType": "complete"})
        if method == "ping":
            return _result(id_, {"resultType": "complete"})
        return _error(id_, NO_METHOD, f"no method {method}", status=404)

    async def legacy(self, request, id_, method, params):
        """A request from a client that opened with `initialize` (2025-11-25, 2025-06-18)."""
        if method == "initialize":
            asked = params.get("protocolVersion")
            return _result(id_, {"protocolVersion": asked if asked in LEGACY else LEGACY[0],
                                 "capabilities": {"tools": {}}, "serverInfo": self.server_info(),
                                 "instructions": self.instructions()})
        version = request.headers.get("mcp-protocol-version")
        if version not in LEGACY:
            return _error(id_, INVALID_REQUEST, "send the MCP-Protocol-Version header with a supported version "
                                                f"({', '.join([*MODERN, *LEGACY])})", status=400)
        if method == "tools/list":
            return _result(id_, {"tools": [self.tool]})
        if method == "tools/call":
            return await self.call(request, id_, params, {})
        if method == "ping":
            return _result(id_, {})
        return _error(id_, NO_METHOD, f"no method {method}")

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
