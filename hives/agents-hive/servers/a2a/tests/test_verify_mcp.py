"""Tests for the verify MCP server: its card, its token checks and its one tool, and that
hosted Barry's own MCP client and Server Card resolution work against it. No network:
tokens signed by a throwaway key.

Run from servers/a2a with the requirements installed:
  python -m unittest discover -s tests -v
"""
import asyncio
import json
import sys
import time
import unittest
from pathlib import Path

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.testclient import TestClient

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1] / "verify-mcp"))

sys.dont_write_bytecode = True  # don't leave __pycache__ beside the server
import verify_mcp  # noqa: E402
sys.dont_write_bytecode = False
from hive_a2a import orchestrate  # noqa: E402
from hive_a2a.auth import Authenticator  # noqa: E402

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
ENV = {"PUBLIC_URL": "https://verify.test/", "AZURE_TENANT_ID": "tenant", "API_APP_ID": "verify-api",
       "ALLOWED_CLIENTS": "barry-mi"}
ISSUER = "https://login.microsoftonline.com/tenant/v2.0"


class Keys:
    async def key_for(self, token):
        return jwt.PyJWK.from_dict({**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key())), "alg": "RS256"})


def token(client="barry-mi", roles=("Verify.Call",), **claims):
    body = {"iss": ISSUER, "aud": "verify-api", "azp": client, "roles": list(roles), "exp": int(time.time()) + 600,
            **claims}
    return jwt.encode(body, KEY, algorithm="RS256")


class VerifyMcpTest(unittest.TestCase):
    def setUp(self):
        self.app = verify_mcp.create_app(ENV, Authenticator(verify_mcp.auth_from(ENV), Keys()))
        self.client = TestClient(self.app)

    def rpc(self, method, params=None, tok=None, rid=1):
        headers = {"authorization": f"Bearer {tok or token()}"}
        return self.client.post("/mcp", json={"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}},
                                headers=headers)

    def test_the_card_is_public_and_valid(self):
        r = self.client.get(verify_mcp.CARD_PATH)
        self.assertEqual(r.status_code, 200)
        cards = orchestrate._server_card_module()
        self.assertEqual(cards.validate(r.json()), [])
        self.assertEqual(cards.resolve("verify", r.json(), {})["url"], "https://verify.test/mcp")

    def test_a_request_without_a_valid_token_is_refused(self):
        self.assertEqual(self.client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code,
                         401)
        self.assertEqual(self.rpc("tools/list", tok=token(client="someone-else")).status_code, 403)
        self.assertEqual(self.rpc("tools/list", tok=token(roles=())).status_code, 403)
        self.assertEqual(self.rpc("tools/list", tok=token(scp="user_impersonation")).status_code, 403)

    def test_the_tool_records_a_note_in_memory(self):
        r = self.rpc("tools/call", {"name": "record_note", "arguments": {"text": "hello"}}).json()
        self.assertEqual(r["result"]["content"][0]["text"], "Recorded note 1, in memory only: hello")
        self.assertEqual(self.app.state.notes, [{"by": "barry-mi", "text": "hello"}])
        bad = self.rpc("tools/call", {"name": "record_note", "arguments": {"text": ""}}).json()
        self.assertTrue(bad["result"]["isError"])
        other = self.rpc("tools/call", {"name": "delete_everything", "arguments": {}}).json()
        self.assertEqual(other["error"]["code"], -32602)

    def test_barrys_client_lists_and_calls_it(self):
        def transport(request):
            headers = {k: v for k, v in request.headers.items() if k in ("authorization", "content-type")}
            r = self.client.post(request.url.path, content=request.content, headers=headers)
            return httpx.Response(r.status_code, headers={"content-type": r.headers.get("content-type", "")},
                                  content=r.content)

        async def mi_token(scope):
            self.assertEqual(scope, "api://verify-api/.default")
            return token()

        server = {"mcp": {"name": "verify"}, "token_scope": "api://verify-api/.default"}

        async def go():
            network = orchestrate.Network(transport=httpx.MockTransport(transport), token=mi_token,
                                          endpoint=lambda mcp: "https://verify.test/mcp")
            try:
                listed = await network.tools(server)
                called = await network.mcp(server, "tools/call", {"name": "record_note", "arguments": {"text": "hi"}})
            finally:
                await network.client.aclose()
            return listed, called

        listed, called = asyncio.run(go())
        self.assertIn("record_note", listed)
        self.assertIn("hi", called["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
