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
import urllib.error
from pathlib import Path
from unittest import mock

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


class CardColdStartTest(unittest.TestCase):
    """Barry asks again for a Server Card that times out or gets a 5xx, as from a server
    starting from zero, within a bound; anything else fails at once."""

    def network(self, answers):
        self.now, self.slept, self.asked = [0.0], [], 0

        def endpoint(mcp):
            self.asked += 1
            answer = answers[min(self.asked, len(answers)) - 1]
            if isinstance(answer, Exception):
                raise answer
            return answer

        async def sleep(seconds):
            self.slept.append(seconds)
            self.now[0] += seconds

        return orchestrate.Network(endpoint=endpoint, now=lambda: self.now[0], sleep=sleep)

    def endpoint(self, network, within=orchestrate.CARD_WAIT):
        async def go():
            try:
                return await network.endpoint({"name": "verify"}, within)
            finally:
                await network.client.aclose()
        return asyncio.run(go())

    def test_a_server_that_answers_on_the_second_try(self):
        timeout = orchestrate.McpError("verify: card: The read operation timed out", retryable=True)
        network = self.network([timeout, "https://verify.test/mcp"])
        self.assertEqual(self.endpoint(network), "https://verify.test/mcp")
        self.assertEqual((self.asked, self.slept), (2, [orchestrate.CARD_BACKOFF]))

    def test_a_server_that_never_answers(self):
        network = self.network([orchestrate.McpError("verify: card: HTTP 503", retryable=True)])
        with self.assertRaises(orchestrate.McpError) as caught:
            self.endpoint(network)
        self.assertIn("verify didn't answer in time", str(caught.exception))
        self.assertIn("HTTP 503", str(caught.exception))
        self.assertLess(self.now[0], orchestrate.CARD_WAIT)
        self.assertEqual(self.slept, [2, 4, 8, 16, 32])
        self.assertNotIn("verify", network.endpoints)

    def test_the_wait_stays_inside_the_runs_time_left(self):
        network = self.network([orchestrate.McpError("verify: card: timed out", retryable=True)])
        with self.assertRaises(orchestrate.McpError):
            self.endpoint(network, within=5)
        self.assertEqual(self.slept, [2])

    def test_a_4xx_or_a_bad_card_fails_at_once(self):
        for e in (orchestrate.McpError("verify: card: HTTP 404"),
                  orchestrate.McpError("verify: card: response is not JSON")):
            network = self.network([e])
            with self.assertRaises(orchestrate.McpError) as caught:
                self.endpoint(network)
            self.assertIs(caught.exception, e)
            self.assertEqual((self.asked, self.slept), (1, []))

    def test_card_errors_say_whether_asking_again_may_work(self):
        cards = orchestrate._server_card_module()
        cases = [(urllib.error.HTTPError("u", 503, "", {}, None), True),
                 (urllib.error.HTTPError("u", 404, "", {}, None), False),
                 (TimeoutError("The read operation timed out"), True),
                 (urllib.error.URLError(TimeoutError("timed out")), True),
                 (ConnectionRefusedError("refused"), False)]
        for error, retryable in cases:
            with mock.patch.object(cards.OPENER, "open", side_effect=error):
                with self.assertRaises(cards.CardError) as caught:
                    cards.fetch_json("https://verify.test/card", cards.CARD_TYPE)
            self.assertEqual(caught.exception.retryable, retryable, error)
        with mock.patch.object(cards, "load_card", side_effect=cards.CardError("x: timed out", retryable=True)):
            with mock.patch.object(orchestrate, "_server_card_module", return_value=cards):
                with self.assertRaises(orchestrate.McpError) as caught:
                    orchestrate._card_endpoint({"name": "verify", "discovery": {"card": "https://verify.test/card"}})
        self.assertTrue(caught.exception.retryable)


if __name__ == "__main__":
    unittest.main()
