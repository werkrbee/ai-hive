"""Tests for the verify MCP server: its card, its token checks and its one tool, and that
hosted Barry's own MCP client and Server Card resolution work against it. No network:
tokens signed by a throwaway key.

Run from servers/a2a with the requirements installed:
  python -m unittest discover -s tests -v
"""
import asyncio
import base64
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
from hive_a2a import mcp_protocol, orchestrate  # noqa: E402
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
        headers = {"authorization": f"Bearer {tok or token()}", "MCP-Protocol-Version": "2025-06-18"}
        return self.client.post("/mcp", json={"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}},
                                headers=headers)

    def modern(self, method, params=None, version="2026-07-28", headers=None, notification=False):
        params = {**(params or {}), "_meta": {mcp_protocol.VERSION_KEY: version,
                  "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "1"},
                  "io.modelcontextprotocol/clientCapabilities": {}}}
        h = {"authorization": f"Bearer {token()}", "MCP-Protocol-Version": version, "Mcp-Method": method}
        if method == "tools/call":
            h["Mcp-Name"] = params.get("name", "")
        h.update(headers or {})
        body = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notification:
            body["id"] = 7
        return self.client.post("/mcp", json=body, headers={k: v for k, v in h.items() if v is not None})

    def test_the_card_is_public_and_valid(self):
        r = self.client.get(verify_mcp.CARD_PATH)
        self.assertEqual(r.status_code, 200)
        cards = orchestrate._server_card_module()
        self.assertEqual(cards.validate(r.json()), [])
        self.assertEqual(cards.resolve("verify", r.json(), {})["url"], "https://verify.test/mcp")
        self.assertEqual(r.json()["remotes"][0]["supportedProtocolVersions"],
                         ["2026-07-28", "2025-11-25", "2025-06-18"])

    def test_modern_discovery_list_ping_and_call_need_no_initialize(self):
        discover = self.modern("server/discover")
        self.assertEqual(discover.status_code, 200)
        result = discover.json()["result"]
        self.assertEqual(result["supportedVersions"], ["2026-07-28"])
        self.assertEqual(result["capabilities"], {"tools": {}})
        self.assertEqual(result["_meta"]["io.modelcontextprotocol/serverInfo"]["name"], "barry-verify")
        listed = self.modern("tools/list").json()["result"]
        self.assertEqual(listed, {"resultType": "complete", "tools": verify_mcp.TOOLS})
        self.assertEqual(self.modern("ping").json()["result"], {"resultType": "complete"})
        r = self.modern("tools/call", {"name": "record_note", "arguments": {"text": "modern"}})
        self.assertNotIn("mcp-session-id", r.headers)
        self.assertEqual(r.json()["result"]["resultType"], "complete")
        self.assertEqual(self.app.state.notes, [{"by": "barry-mi", "text": "modern"}])

    def test_modern_header_version_and_method_errors_do_not_execute_the_tool(self):
        params = {"name": "record_note", "arguments": {"text": "must not run"}}
        for headers in ({"MCP-Protocol-Version": None}, {"MCP-Protocol-Version": "2025-06-18"},
                        {"Mcp-Method": None}, {"Mcp-Method": "tools/list"},
                        {"Mcp-Name": None}, {"Mcp-Name": "other"}, {"Mcp-Name": "=?base64?bad?="}):
            with self.subTest(headers=headers):
                r = self.modern("tools/call", params, headers=headers)
                self.assertEqual((r.status_code, r.json()["error"]["code"]), (400, -32020))
        r = self.modern("tools/list", version="1900-01-01")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"]["code"], -32022)
        self.assertEqual(r.json()["error"]["data"], {"supported": ["2026-07-28"], "requested": "1900-01-01"})
        r = self.modern("resources/list")
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (404, -32601))
        self.assertEqual(self.app.state.notes, [])
        encoded = "=?base64?" + base64.b64encode(b"record_note").decode() + "?="
        self.assertEqual(self.modern("tools/call", params, headers={"Mcp-Name": encoded}).status_code, 200)
        self.assertEqual(len(self.app.state.notes), 1)

    def test_legacy_negotiation_never_claims_modern_handshake_support(self):
        for asked, chosen in (("2025-06-18", "2025-06-18"), ("2025-11-25", "2025-11-25"),
                              ("2026-07-28", "2025-11-25"), ("unknown", "2025-11-25")):
            with self.subTest(asked=asked):
                r = self.rpc("initialize", {"protocolVersion": asked})
                self.assertEqual(r.json()["result"]["protocolVersion"], chosen)
                self.assertNotIn("mcp-session-id", r.headers)
                headers = {"authorization": f"Bearer {token()}", "MCP-Protocol-Version": chosen}
                listed = self.client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                                          headers=headers)
                self.assertEqual(listed.json()["result"], {"tools": verify_mcp.TOOLS})
        bare = self.client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                                headers={"authorization": f"Bearer {token()}"})
        self.assertEqual(bare.json()["result"], {"tools": verify_mcp.TOOLS}, "no header after initialize is served")
        unserved = self.client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                                    headers={"authorization": f"Bearer {token()}", "MCP-Protocol-Version": "2025-03-26"})
        self.assertEqual(unserved.status_code, 400)

    def test_invalid_envelopes_and_arguments_are_errors_not_server_crashes(self):
        headers = {"authorization": f"Bearer {token()}", "MCP-Protocol-Version": "2025-11-25"}
        for body in ([], {}, {"jsonrpc": "1.0", "id": 1, "method": "ping"},
                     {"jsonrpc": "2.0", "id": 1, "method": 3}):
            with self.subTest(body=body):
                r = self.client.post("/mcp", json=body, headers=headers)
                self.assertEqual((r.status_code, r.json()["error"]["code"]), (400, -32600))
        r = self.client.post("/mcp", content=b"not JSON", headers=headers)
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (400, -32700))
        for value in ([], "wrong", 0, False, None):
            r = self.client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": value},
                                 headers=headers)
            self.assertEqual(r.json()["error"]["code"], -32602)
            r = self.modern("tools/call", {"name": "record_note", "arguments": value})
            self.assertEqual(r.json()["error"]["code"], -32602)
        self.assertEqual(self.app.state.notes, [])

    def test_methods_origins_and_notifications_do_not_bypass_validation(self):
        headers = {"authorization": f"Bearer {token()}"}
        self.assertEqual(self.client.get("/mcp", headers=headers).status_code, 405)
        self.assertEqual(self.client.delete("/mcp", headers=headers).status_code, 405)
        self.assertEqual(self.modern("tools/list", headers={"Origin": "https://evil.test"}).status_code, 403)
        self.assertEqual(self.modern("tools/list", headers={"Origin": "https://verify.test"}).status_code, 200)
        note = {"name": "record_note", "arguments": {"text": "no request id"}}
        self.assertEqual(self.modern("tools/call", note, notification=True).status_code, 202)
        self.assertEqual(self.modern("tools/call", note, notification=True,
                                     headers={"Mcp-Method": "other"}).status_code, 400)
        self.assertEqual(self.app.state.notes, [])
        r = self.client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=headers)
        self.assertEqual(r.status_code, 202)

    def test_a_request_without_a_valid_token_is_refused(self):
        self.assertEqual(self.client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code,
                         401)
        self.assertEqual(self.rpc("tools/list", tok=token(client="someone-else")).status_code, 403)
        self.assertEqual(self.rpc("tools/list", tok=token(roles=())).status_code, 403)
        self.assertEqual(self.rpc("tools/list", tok=token(scp="user_impersonation")).status_code, 403)
        for auth, status in (("", 401), (f"Bearer {token(client='someone-else')}", 403),
                             (f"Bearer {token(roles=())}", 403),
                             (f"Bearer {token(scp='Review.Request')}", 403)):
            with self.subTest(status=status, auth=bool(auth)):
                r = self.modern("tools/call", {"name": "record_note", "arguments": {"text": "denied"}},
                                headers={"authorization": auth})
                self.assertEqual(r.status_code, status)
        self.assertEqual(self.app.state.notes, [])

    def test_the_tool_records_a_note_in_memory(self):
        r = self.rpc("tools/call", {"name": "record_note", "arguments": {"text": "hello"}}).json()
        self.assertEqual(r["result"]["content"][0]["text"], "Recorded note 1, in memory only: hello")
        self.assertEqual(self.app.state.notes, [{"by": "barry-mi", "text": "hello"}])
        bad = self.rpc("tools/call", {"name": "record_note", "arguments": {"text": ""}}).json()
        self.assertTrue(bad["result"]["isError"])
        other = self.rpc("tools/call", {"name": "delete_everything", "arguments": {}}).json()
        self.assertEqual(other["error"]["code"], -32602)

    def test_barrys_client_lists_and_calls_it(self):
        requests = []

        def transport(request):
            requests.append((json.loads(request.content), dict(request.headers)))
            headers = dict(request.headers)
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
        self.assertEqual(requests[0][0]["method"], "initialize")
        self.assertEqual(requests[0][0]["params"]["protocolVersion"], "2026-07-28")
        for body, headers in requests[1:]:
            self.assertEqual(headers["mcp-protocol-version"], "2025-11-25")
        self.assertEqual(self.app.state.notes, [{"by": "barry-mi", "text": "hi"}])


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
