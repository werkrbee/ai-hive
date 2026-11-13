"""Tests for Patricia's review over MCP (hive_a2a/mcp.py): no network, the stub or a fixed
model, locally signed tokens. They reuse test_server's config, tokens and providers.

Run from servers/a2a with the requirements installed:
  python -m unittest discover -s tests -v
"""
import base64
import dataclasses
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

import test_server
from test_server import CALLER, OTHER, STRANGER, WRONG_KEY, Fixed, Recording, token, write_config

from hive_a2a import mcp, providers, review
from hive_a2a.config import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "hives/mcp-hive/scripts"))
sys.dont_write_bytecode = True  # don't leave __pycache__ in another hive
import server_card  # noqa: E402
sys.dont_write_bytecode = False

ARGS = {"proposal": "Force-push main to drop a commit.", "context": "A teammate asked."}
VERDICT = {"verdict": "block", "reason": "Rewriting shared history.", "violation": "No force-push to main."}


class McpTest(unittest.TestCase):
    # test_server's helpers, without inheriting (and so running again) its tests
    client, rpc, send, ledger = (test_server.ServerTest.client, test_server.ServerTest.rpc,
                                 test_server.ServerTest.send, test_server.ServerTest.ledger)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def post(self, client, method, params=None, who=CALLER, auth=None, version="2026-07-28", headers=None, id_=1):
        """A 2026-07-28 request, with its headers matching its body unless headers override them."""
        params = dict(params or {})
        if version:
            params["_meta"] = {mcp.VERSION_KEY: version,
                               "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "1"},
                               "io.modelcontextprotocol/clientCapabilities": {}}
        h = {"Authorization": auth if auth is not None else f"Bearer {token(who)}",
             "Accept": "application/json, text/event-stream"}
        if version:
            h.update({"MCP-Protocol-Version": version, "Mcp-Method": method})
            if method == "tools/call":
                h["Mcp-Name"] = params.get("name", "")
        h.update(headers or {})
        return client.post(mcp.PATH, json={"jsonrpc": "2.0", "id": id_, "method": method, "params": params},
                           headers={k: v for k, v in h.items() if v is not None})

    def call(self, client, arguments=ARGS, **kwargs):
        r = self.post(client, "tools/call", {"name": "review", "arguments": arguments}, **kwargs)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["result"]

    # --- discovery and auth ----------------------------------------------

    def test_server_card_and_resource_metadata_are_public(self):
        config = write_config(self.root)
        with self.client(config) as c:
            card = c.get(mcp.CARD_PATH)
            meta = [c.get(p) for p in mcp.METADATA_PATHS]
        self.assertEqual(card.status_code, 200)
        self.assertEqual(server_card.validate(card.json()), [])
        remote = server_card.resolve("patricia", card.json(), {})
        self.assertEqual(remote["url"], "http://localhost/mcp")
        self.assertEqual(remote["headers"], [], "auth is OAuth through the metadata, not a header to fill in")
        self.assertEqual(card.json()["remotes"][0]["supportedProtocolVersions"], ["2026-07-28", "2025-11-25",
                                                                                 "2025-06-18"])
        agent = json.loads((REPO_ROOT / "hives/agents-hive/cards/patricia/card.json").read_text())
        self.assertEqual(card.json()["version"], agent["version"])
        for r in meta:
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json(), {"resource": "http://localhost/mcp",
                                        "authorization_servers": ["https://login.example.test/tenant/v2.0"],
                                        "scopes_supported": ["api://api-app/.default"],
                                        "bearer_methods_supported": ["header"],
                                        "resource_name": "Patricia (governance-review)"})

    def test_every_mcp_request_is_authenticated(self):
        with self.client(write_config(self.root)) as c:
            missing = self.post(c, "tools/list", auth="")
            self.assertEqual(missing.status_code, 401)
            challenge = missing.headers["www-authenticate"]
            self.assertIn('resource_metadata="http://localhost/.well-known/oauth-protected-resource/mcp"', challenge)
            self.assertIn('scope="api://api-app/.default"', challenge)
            self.assertNotIn("error=", challenge, "no error code when no token was sent")
            bad = self.post(c, "tools/list", auth=f"Bearer {token(key=WRONG_KEY)}").headers["www-authenticate"]
            self.assertTrue(bad.startswith(challenge) and bad.endswith('error="invalid_token"'))
            cases = {f"Bearer {token(key=WRONG_KEY)}": 401,
                     f"Bearer {token(exp=int(time.time()) - 3600)}": 401,
                     f"Bearer {token(STRANGER)}": 403,
                     f"Bearer {token(scp='Review.Request')}": 403,
                     f"Bearer {token(idtyp='user')}": 403}
            for header, status in cases.items():
                self.assertEqual(self.post(c, "tools/call", {"name": "review", "arguments": ARGS},
                                           auth=header).status_code, status, header[:20])
            # The A2A endpoint's challenge is unchanged.
            self.assertEqual(c.post("/", json={}).headers["www-authenticate"], 'Bearer error="invalid_token"')
        self.assertEqual(self.ledger(), [])

    def test_the_tool_role_is_required_when_the_config_requires_one(self):
        config = write_config(self.root)
        config = dataclasses.replace(config, auth=dataclasses.replace(config.auth, required_roles=("Review.Request",)))
        with self.client(config) as c:
            self.assertEqual(self.post(c, "tools/list").status_code, 403)
            self.assertEqual(self.post(c, "tools/list", auth=f"Bearer {token(roles=['Review.Request'])}").status_code,
                             200)

    # --- the protocol ----------------------------------------------------

    def test_discover_and_list_offer_one_read_only_tool_shaped_by_the_contract(self):
        contract = json.loads((REPO_ROOT / "hives/agents-hive/contracts/governance-review/contract.json").read_text())
        with self.client(write_config(self.root)) as c:
            discover = self.post(c, "server/discover").json()["result"]
            listed = self.post(c, "tools/list").json()["result"]
        self.assertEqual(discover["supportedVersions"], ["2026-07-28"])
        self.assertEqual(discover["capabilities"], {"tools": {}}, "no resources, prompts, sampling or elicitation")
        self.assertEqual(discover["_meta"]["io.modelcontextprotocol/serverInfo"]["name"], "patricia")
        [tool] = listed["tools"]
        self.assertEqual(tool["name"], "review")
        self.assertEqual(tool["inputSchema"], contract["inputs"])
        self.assertEqual(tool["outputSchema"], contract["output"])
        self.assertTrue(tool["annotations"]["readOnlyHint"])
        self.assertFalse(tool["annotations"]["destructiveHint"])

    def test_a_modern_request_s_headers_must_match_its_body(self):
        with self.client(write_config(self.root)) as c:
            cases = [
                ({"MCP-Protocol-Version": None}, -32020),
                ({"MCP-Protocol-Version": "2025-11-25"}, -32020),
                ({"Mcp-Method": "tools/list"}, -32020),
                ({"Mcp-Name": "something-else"}, -32020),
            ]
            for headers, code in cases:
                r = self.post(c, "tools/call", {"name": "review", "arguments": ARGS}, headers=headers)
                self.assertEqual((r.status_code, r.json()["error"]["code"]), (400, code), headers)
            encoded = "=?base64?" + base64.b64encode(b"review").decode() + "?="
            r = self.post(c, "tools/call", {"name": "review", "arguments": ARGS}, headers={"Mcp-Name": encoded})
            self.assertEqual(r.status_code, 200, "a Base64-encoded Mcp-Name is decoded before it's compared")
            old = self.post(c, "tools/list", version="2025-11-25")  # a legacy version needs initialize
            self.assertEqual(old.status_code, 400)
            self.assertEqual(old.json()["error"]["code"], -32022)
            unknown = self.post(c, "tools/list", version="1900-01-01")
            self.assertEqual(unknown.status_code, 400)
            self.assertEqual(unknown.json()["error"], {"code": -32022, "message": "Unsupported protocol version",
                                                       "data": {"supported": ["2026-07-28"],
                                                                "requested": "1900-01-01"}})
            missing = self.post(c, "resources/list")
            self.assertEqual((missing.status_code, missing.json()["error"]["code"]), (404, -32601))
            self.assertEqual(self.post(c, "tools/call", {"name": "approve", "arguments": {}}).json()["error"]["code"],
                             -32602)

    def test_a_legacy_client_initializes_without_a_session(self):
        with self.client(write_config(self.root)) as c:
            init = self.post(c, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                               "clientInfo": {"name": "platform", "version": "1"}}, version=None)
            self.assertEqual(init.status_code, 200)
            self.assertNotIn("mcp-session-id", init.headers)
            self.assertEqual(init.json()["result"]["protocolVersion"], "2025-06-18")
            self.assertEqual(init.json()["result"]["capabilities"], {"tools": {}})
            newest = self.post(c, "initialize", {"protocolVersion": "2099-01-01"}, version=None)
            self.assertEqual(newest.json()["result"]["protocolVersion"], "2025-11-25")
            note = c.post(mcp.PATH, json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                          headers={"Authorization": f"Bearer {token()}"})
            self.assertEqual(note.status_code, 202)
            listed = self.post(c, "tools/list", version=None, headers={"MCP-Protocol-Version": "2025-06-18"})
            self.assertEqual(listed.json()["result"]["tools"][0]["name"], "review")
            called = self.post(c, "tools/call", {"name": "review", "arguments": ARGS}, version=None,
                               headers={"MCP-Protocol-Version": "2025-11-25"}).json()["result"]
            self.assertNotIn("isError", called)
            self.assertIn(called["structuredContent"]["verdict"], ("allow", "allow-with-conditions", "block"))
            bare = self.post(c, "tools/list", version=None)
            self.assertEqual((bare.status_code, bare.json()["error"]["code"]), (400, -32600))

    def test_only_post_from_no_or_this_origin_is_served(self):
        with self.client(write_config(self.root)) as c:
            auth = {"Authorization": f"Bearer {token()}"}
            self.assertEqual(c.get(mcp.PATH, headers=auth).status_code, 405)
            self.assertEqual(c.delete(mcp.PATH, headers=auth).status_code, 405)
            self.assertEqual(self.post(c, "tools/list", headers={"Origin": "https://evil.test"}).status_code, 403)
            self.assertEqual(self.post(c, "tools/list", headers={"Origin": "http://localhost"}).status_code, 200)
            r = c.post(mcp.PATH, content=b"not json", headers=auth)
            self.assertEqual((r.status_code, r.json()["error"]["code"]), (400, -32700))

    # --- the review ------------------------------------------------------

    def test_a_review_returns_the_verdict_and_is_metered_without_a_task(self):
        with self.client(write_config(self.root), provider=Fixed(json.dumps({**VERDICT, "extra": "x"}))) as c:
            result = self.call(c)
            tasks = self.rpc(c, "ListTasks", {}).json()["result"]
        self.assertEqual(result["resultType"], "complete")
        self.assertNotIn("isError", result)
        self.assertEqual(result["structuredContent"], VERDICT, "trimmed to the contract's fields")
        self.assertEqual(json.loads(result["content"][0]["text"]), VERDICT)
        self.assertEqual(tasks.get("tasks", []), [], "an MCP review keeps no task")
        [entry] = self.ledger()
        self.assertEqual(entry["capability"], "governance-review")
        self.assertEqual(entry["tokenDetail"], {"input": 100, "output": 20})
        self.assertFalse((self.root / "data/ledger.jsonl.pending").exists() and
                         (self.root / "data/ledger.jsonl.pending").read_text().strip())

    def test_input_that_breaks_the_contract_is_a_tool_error_and_costs_nothing(self):
        with self.client(write_config(self.root)) as c:
            for arguments in ({}, {"proposal": 3}, {"proposal": "x" * 2_000_000}):
                result = self.call(c, arguments)
                self.assertTrue(result["isError"])
                self.assertTrue(result["content"][0]["text"].startswith("Refused:"))
            self.assertEqual(self.post(c, "tools/call", {"name": "review", "arguments": "no"}).json()["error"]["code"],
                             -32602)
        self.assertEqual(self.ledger(), [])

    def test_a_reply_that_breaks_the_contract_is_a_tool_error_and_still_metered(self):
        with self.client(write_config(self.root), provider=Fixed("not a verdict")) as c:
            result = self.call(c)
        self.assertTrue(result["isError"])
        self.assertIn("doesn't match the contract's output", result["content"][0]["text"])
        self.assertNotIn("structuredContent", result)
        self.assertEqual(len(self.ledger()), 1)

    def test_the_ceiling_refuses_a_call_with_the_a2a_refusal_s_json(self):
        config = write_config(self.root, in_price=3.0, out_price=15.0)
        reserve = review.Reviewer(config, None, providers.create(config.model)).plan(ARGS).max_usd
        config = dataclasses.replace(config, monthly_ceiling_usd=round(reserve + 0.001, 6))
        with self.client(config) as c:
            first = self.call(c)
            second = self.call(c)
            task = self.send(c)["result"]["task"]
        self.assertNotIn("isError", first)
        self.assertTrue(second["isError"])
        text, data = second["content"]
        self.assertIn("monthly spending ceiling", text["text"])
        a2a_text, a2a_data = task["status"]["message"]["parts"]
        self.assertEqual(text["text"], a2a_text["text"])
        self.assertEqual(json.loads(data["text"]), a2a_data["data"])
        self.assertEqual(json.loads(data["text"])["error"], "monthly-ceiling-reached")
        self.assertEqual(len(self.ledger()), 1, "a refused review costs nothing")

    def test_no_caller_s_data_reaches_another_call(self):
        provider = Recording(json.dumps({"verdict": "allow", "reason": "r"}))
        with self.client(write_config(self.root), provider=provider) as c:
            self.call(c, {"proposal": "Rotate the lineup signing key."})
            self.call(c, {"proposal": "Email the singularity beta list."}, who=OTHER)
            self.call(c, {"proposal": "And delete the old key."})
            for who in (CALLER, OTHER):
                self.assertEqual(self.rpc(c, "ListTasks", {}, who=who).json()["result"].get("tasks", []), [])
        self.assertEqual(len({system for system, _ in provider.calls}), 1)
        [(system, mine), (_, other), (_, later)] = provider.calls
        for text in ("signing key", "beta list", "old key"):
            self.assertNotIn(text, system)
        self.assertNotIn("signing key", other)
        self.assertNotIn("signing key", later, "each call stands alone")
        self.assertIn("old key", later)


if __name__ == "__main__":
    unittest.main()
