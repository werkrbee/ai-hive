"""Shared dual-era MCP HTTP handling for Patricia and the verify server.

Authentication and tool execution stay with each server. This layer owns protocol
versions, header/body checks, discovery, legacy negotiation and JSON-RPC framing.
Legacy initialize always negotiates a legacy version, even when Barry asks for a
modern one; his client then sends the negotiated version on subsequent requests.
"""
import base64
import json
from urllib.parse import urlparse

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

MODERN = ("2026-07-28",)
LEGACY = ("2025-11-25", "2025-06-18")
VERSION_KEY = "io.modelcontextprotocol/protocolVersion"
# JSON-RPC error codes: the spec's own, then MCP's
PARSE, INVALID_REQUEST, NO_METHOD, INVALID_PARAMS = -32700, -32600, -32601, -32602
HEADER_MISMATCH, UNSUPPORTED_VERSION = -32020, -32022


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


class Protocol:
    def __init__(self, public_url, tools):
        u = urlparse(public_url)
        self.origin = f"{u.scheme}://{u.netloc}"
        self.tools = tools

    async def handle(self, request: Request):
        if request.method != "POST":
            return Response(status_code=405, headers={"allow": "POST"})
        sent_from = request.headers.get("origin")
        if sent_from is not None and sent_from != self.origin:
            return _error(None, INVALID_REQUEST, f"origin {sent_from} is not allowed", status=403)
        try:
            body = json.loads(await request.body())
        except ValueError:
            return _error(None, PARSE, "the body is not JSON", status=400)
        if not isinstance(body, dict) or body.get("jsonrpc") != "2.0" or not isinstance(body.get("method"), str):
            return _error(None, INVALID_REQUEST, "send one JSON-RPC 2.0 request", status=400)
        id_, method, params = body.get("id"), body["method"], body.get("params", {})
        if not isinstance(params, dict):
            return _error(id_, INVALID_PARAMS, "params must be an object")
        meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
        if VERSION_KEY in meta:
            return await self.modern(request, id_, method, params, meta[VERSION_KEY], notification="id" not in body)
        if "id" not in body:  # a legacy client's notifications/initialized, without executing a tool
            return Response(status_code=202)
        return await self.legacy(request, id_, method, params)

    async def modern(self, request, id_, method, params, version, notification=False):
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
        if notification:
            return Response(status_code=202)
        if method == "server/discover":
            return _result(id_, {"resultType": "complete", "supportedVersions": list(MODERN),
                                 "capabilities": {"tools": {}}, "_meta": {
                                     "io.modelcontextprotocol/serverInfo": self.server_info()},
                                 "instructions": self.instructions()})
        if method == "tools/list":
            return _result(id_, {"resultType": "complete", "tools": self.tools})
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
        # The spec's server SHOULD assume an older revision when the header is missing and it
        # can't tell otherwise; holding no session, this one can't, and Copilot Studio's client
        # sends none after initialize. A version it doesn't serve is still refused.
        version = request.headers.get("mcp-protocol-version")
        if version is not None and version not in LEGACY:
            return _error(id_, INVALID_REQUEST, "send the MCP-Protocol-Version header with a supported version "
                                                f"({', '.join([*MODERN, *LEGACY])}), or none", status=400)
        if method == "tools/list":
            return _result(id_, {"tools": self.tools})
        if method == "tools/call":
            return await self.call(request, id_, params, {})
        if method == "ping":
            return _result(id_, {})
        return _error(id_, NO_METHOD, f"no method {method}")
