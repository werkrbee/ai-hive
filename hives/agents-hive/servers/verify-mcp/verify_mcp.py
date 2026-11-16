"""The MCP server hosted Barry is checked against once deployed: one harmless gated tool.

No werkrbee product's MCP server can take Barry's Entra token yet, so this one stands in,
to check a gated call end to end: Barry calls `record_note`, the `verify` registration maps
it to the action `verify.note.record`, its policy (rules-hive/examples/verify) gates it,
the task pauses for a person, and once approved the call runs here. The tool only keeps
the note in memory and says so; nothing persists, and nothing outside this process
changes.

It shares dual-era MCP handling with Patricia (hive_a2a.mcp_protocol): modern
2026-07-28 requests are stateless, while initialize negotiates 2025-11-25 or
2025-06-18, including for Barry's client when it asks for a modern version.
It uses Streamable HTTP with plain JSON replies and no session, and
serves its Server Card without a token at /.well-known/mcp/server-card.json. Every other
request needs an app token for its own API app (entra.sh --agent verify) from a client on
ALLOWED_CLIENTS, Barry's managed identity, carrying the Verify.Call role. It reuses the A2A
server's token checks (hive_a2a.auth).

Environment: PUBLIC_URL, AZURE_TENANT_ID, API_APP_ID, ALLOWED_CLIENTS (comma-separated).

  python verify_mcp.py --host 0.0.0.0 --port 8080
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "a2a"))

from starlette.applications import Starlette  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402

from hive_a2a.auth import Authenticator  # noqa: E402
from hive_a2a.config import Auth  # noqa: E402
from hive_a2a.mcp_protocol import Protocol, MODERN, LEGACY, INVALID_PARAMS, _error, _result  # noqa: E402

CARD_PATH = "/.well-known/mcp/server-card.json"
VERSIONS = [*MODERN, *LEGACY]
ROLE = "Verify.Call"
TOOLS = [{
    "name": "record_note",
    "description": "Record a short note for the maintainer. It is kept in this server's memory only, and is "
                   "the gated action hosted Barry is checked with: it needs a person's approval first.",
    "inputSchema": {"type": "object", "properties": {"text": {"type": "string", "maxLength": 500}},
                    "required": ["text"]},
}]


def auth_from(env):
    missing = [k for k in ("PUBLIC_URL", "AZURE_TENANT_ID", "API_APP_ID", "ALLOWED_CLIENTS") if not env.get(k)]
    if missing:
        sys.exit("error: missing environment: " + ", ".join(missing))
    login = f"https://login.microsoftonline.com/{env['AZURE_TENANT_ID']}"
    clients = tuple(c.strip() for c in env["ALLOWED_CLIENTS"].split(",") if c.strip())
    return Auth(issuer=login + "/v2.0", audience=env["API_APP_ID"], jwks_url=login + "/discovery/v2.0/keys",
                jwks_path=None, token_url=login + "/oauth2/v2.0/token", scope=f"api://{env['API_APP_ID']}/.default",
                allowed_clients=clients, client_claims=("azp", "appid"), required_roles=(ROLE,))


def card(public_url):
    return {
        "$schema": "https://static.modelcontextprotocol.io/schemas/v1/server-card.schema.json",
        "name": "io.werkrbee/barry-verify",
        "version": "1.0.0",
        "description": "One gated tool hosted Barry is checked against after a deploy.",
        "remotes": [{"type": "streamable-http", "url": public_url.rstrip("/") + "/mcp",
                     "supportedProtocolVersions": VERSIONS}],
    }


class Server(Protocol):
    def __init__(self, public_url, authenticator):
        super().__init__(public_url, TOOLS)
        self.authenticator = authenticator
        self.notes = []

    def server_info(self):
        return {"name": "barry-verify", "version": "1.0.0"}

    def instructions(self):
        return "Call record_note to record a short note in this server's memory only."

    async def handle(self, request: Request):
        who, refusal = await self.authenticator.caller(request.headers.get("authorization"))
        if refusal:
            status, reason = refusal
            return JSONResponse({"error": reason}, status_code=status)
        request.scope["verify_client"] = who[0]
        return await super().handle(request)

    async def call(self, request, id_, params, extra):
        if params.get("name") != "record_note":
            return _error(id_, INVALID_PARAMS, f"no tool named {params.get('name')!r}")
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            return _error(id_, INVALID_PARAMS, "arguments must be an object")
        text = arguments.get("text")
        if not isinstance(text, str) or not text or len(text) > 500:
            return _result(id_, {**extra, "isError": True, "content": [{"type": "text", "text": "text must be 1 to 500 "
                                                                   "characters"}]})
        self.notes.append({"by": request.scope["verify_client"], "text": text})
        return _result(id_, {**extra, "content": [{"type": "text", "text": f"Recorded note {len(self.notes)}, "
                                                            f"in memory only: {text}"}]})


def create_app(env=os.environ, authenticator=None):
    authenticator = authenticator or Authenticator(auth_from(env))
    public_url = env["PUBLIC_URL"]
    server = Server(public_url, authenticator)

    async def server_card(request):
        return JSONResponse(card(public_url))

    app = Starlette(routes=[Route(CARD_PATH, server_card, methods=["GET"]),
                            Route("/mcp", server.handle, methods=["POST", "GET", "DELETE"])])
    app.state.notes = server.notes
    return app


def main():
    ap = argparse.ArgumentParser(description="The MCP server hosted Barry is checked against.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    import uvicorn
    uvicorn.run(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
