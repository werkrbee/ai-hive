"""Tests for the per-client limits (hive_a2a/limits.py) over both bindings: no network, the
stub or a recording model, locally signed tokens. They reuse test_server's and test_mcp's
helpers.

Run from servers/a2a with the requirements installed:
  python -m unittest discover -s tests -v
"""
import dataclasses
import datetime
import json
import tempfile
import unittest
from pathlib import Path

import test_mcp
import test_server
from test_server import CALLER, OTHER, PROPOSAL, Recording, write_config

from hive_a2a import providers, review
from hive_a2a.config import ClientLimit, ConfigError, Limits, load

VERDICT = json.dumps(test_mcp.VERDICT)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class LimitsTest(unittest.TestCase):
    # the other tests' helpers, without inheriting (and so running again) their tests
    client, rpc, send, ledger = (test_server.ServerTest.client, test_server.ServerTest.rpc,
                                 test_server.ServerTest.send, test_server.ServerTest.ledger)
    post, call = test_mcp.McpTest.post, test_mcp.McpTest.call

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def config(self, **limits):
        return dataclasses.replace(write_config(self.root), limits=Limits(**limits))

    def reserve(self, config):
        return review.Reviewer(config, None, providers.create(config.model)).plan(PROPOSAL[0]["data"]).max_usd

    def spent(self, usd, client=None):
        """A ledger entry this month, as an earlier process would have left it."""
        path = self.root / "data/ledger.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        entry = {"at": at, "usd": usd, "basis": "estimated", **({"client": client} if client else {})}
        with path.open("a") as f:
            f.write(json.dumps(entry) + "\n")

    def assert_rate_limited(self, r, limit, wait):
        self.assertEqual(r.status_code, 429, r.text)
        self.assertEqual(r.headers["retry-after"], str(wait))
        error = r.json()["error"]
        self.assertIn(f"Send again in {wait} seconds", error["message"])
        self.assertEqual(error["data"], {"error": "rate-limited", "limitPerHour": limit, "retryAfterSeconds": wait})

    # --- the hourly rate ---------------------------------------------------

    def test_a2a_reviews_past_the_rate_get_429_and_cost_nothing(self):
        clock, model = Clock(), Recording(VERDICT)
        with self.client(self.config(reviews_per_hour=2), provider=model, rate_clock=clock) as c:
            first = self.send(c)["result"]["task"]
            clock.now += 600
            self.send(c)
            clock.now += 600
            refused = self.rpc(c, "SendMessage", test_server.message(PROPOSAL))
            looked_up = self.rpc(c, "GetTask", {"id": first["id"]})
        self.assert_rate_limited(refused, 2, 3600 - 1200)
        self.assertEqual(looked_up.status_code, 200, "only a review counts toward the rate")
        self.assertEqual(len(model.calls), 2, "a refused review never reaches the model")
        self.assertEqual(len(self.ledger()), 2, "or the ledger")

    def test_mcp_tool_calls_past_the_rate_get_429_and_cost_nothing(self):
        clock, model = Clock(), Recording(VERDICT)
        with self.client(self.config(reviews_per_hour=1), provider=model, rate_clock=clock) as c:
            self.call(c)
            refused = self.post(c, "tools/call", {"name": "review", "arguments": test_mcp.ARGS}, id_=7)
            listed = self.post(c, "tools/list")
        self.assert_rate_limited(refused, 1, 3600)
        self.assertEqual(refused.json()["id"], 7)
        self.assertEqual(listed.status_code, 200, "only a tool call counts toward the rate")
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(len(self.ledger()), 1)

    def test_both_bindings_share_one_rate_and_the_window_moves_on(self):
        clock = Clock()
        with self.client(self.config(reviews_per_hour=2), rate_clock=clock) as c:
            self.send(c)
            self.call(c)
            refused = self.rpc(c, "SendMessage", test_server.message(PROPOSAL))
            clock.now += 3600
            again = self.send(c)["result"]["task"]
        self.assertEqual(refused.status_code, 429)
        self.assertEqual(again["status"]["state"], "TASK_STATE_COMPLETED")

    def test_one_client_s_rate_leaves_the_others_alone(self):
        own = (ClientLimit(OTHER, 0.25, reviews_per_hour=3),)
        with self.client(self.config(reviews_per_hour=1, clients=own), rate_clock=Clock()) as c:
            self.send(c)
            caller = self.rpc(c, "SendMessage", test_server.message(PROPOSAL))
            other = [self.rpc(c, "SendMessage", test_server.message(PROPOSAL), who=OTHER) for _ in range(4)]
        self.assertEqual(caller.status_code, 429)
        self.assertEqual([r.status_code for r in other], [200, 200, 200, 429], "OTHER has its own rate of 3")

    # --- the monthly allowance ---------------------------------------------

    def test_a_client_past_its_share_is_refused_on_both_bindings_and_others_are_not(self):
        config = self.config(client_share=0.5)
        reserve = self.reserve(config)
        # CALLER's earlier spending, recorded by a process before this one, leaves its share
        # less than one more review's worst case.
        self.spent(config.limits.client_share * config.monthly_ceiling_usd - reserve / 2, client=CALLER)
        model = Recording(VERDICT)
        with self.client(config, provider=model) as c:
            task = self.send(c)["result"]["task"]
            tool = self.call(c)
            other = self.send(c, who=OTHER)["result"]["task"]
        self.assertEqual(task["status"]["state"], "TASK_STATE_REJECTED")
        text, data = task["status"]["message"]["parts"]
        self.assertIn("this client's monthly allowance of $12.50 would be passed", text["text"])
        self.assertIn("accepted again on", text["text"])
        self.assertEqual(data["data"]["error"], "client-allowance-reached")
        self.assertEqual(data["data"]["ceilingUsd"], 12.5)
        self.assertTrue(tool["isError"])
        self.assertEqual(json.loads(tool["content"][1]["text"]), data["data"], "the same refusal on MCP")
        self.assertEqual(other["status"]["state"], "TASK_STATE_COMPLETED")
        self.assertEqual(len(model.calls), 1, "only OTHER's review reached the model")
        self.assertEqual(self.ledger()[-1]["client"], OTHER, "an entry names the client it was made for")

    def test_a_client_s_own_allowance_is_out_of_the_others_reach(self):
        # OTHER, as hosted Barry is, has a quarter of the ceiling held for it. Spending by
        # everyone else (here an entry naming no client, as the weekly evaluation's do) has
        # used what the rest may, so CALLER is refused while OTHER is still served.
        config = self.config(client_share=0.5, clients=(ClientLimit(OTHER, 0.25),))
        reserve = self.reserve(config)
        self.spent(0.75 * config.monthly_ceiling_usd - reserve / 2)
        with self.client(config) as c:
            caller = self.send(c)["result"]["task"]
            other = self.send(c, who=OTHER)["result"]["task"]
        self.assertEqual(caller["status"]["state"], "TASK_STATE_REJECTED")
        text, data = (p.get("text") or p.get("data") for p in caller["status"]["message"]["parts"])
        self.assertIn("the monthly allowance shared by clients without their own of $18.75", text)
        self.assertEqual(data["error"], "shared-allowance-reached")
        self.assertEqual(data["ceilingUsd"], 18.75)
        self.assertEqual(other["status"]["state"], "TASK_STATE_COMPLETED")

    def test_a_client_with_its_own_allowance_is_held_to_it(self):
        config = self.config(clients=(ClientLimit(OTHER, 0.25),))
        self.spent(0.25 * config.monthly_ceiling_usd, client=OTHER)
        with self.client(config) as c:
            other = self.send(c, who=OTHER)["result"]["task"]
            caller = self.send(c)["result"]["task"]
        self.assertEqual(other["status"]["state"], "TASK_STATE_REJECTED")
        self.assertEqual(other["status"]["message"]["parts"][1]["data"]["error"], "client-allowance-reached")
        self.assertEqual(caller["status"]["state"], "TASK_STATE_COMPLETED")

    # --- the config -----------------------------------------------------------

    def test_limits_default_to_a_rate_and_half_the_ceiling(self):
        limits = write_config(self.root).limits
        self.assertEqual((limits.reviews_per_hour, limits.client_share, limits.clients), (30, 0.5, ()))

    def test_config_reads_limits_and_refuses_unsafe_ones(self):
        write_config(self.root)
        base = (self.root / "config.toml").read_text()
        good = f"""
[limits]
reviews_per_hour = 12
client_share = 0.4

[[limits.clients]]
client = "{OTHER}"
share = 0.3
reviews_per_hour = 60
"""
        (self.root / "config.toml").write_text(base + good)
        limits = load(self.root / "config.toml").limits
        self.assertEqual(limits, Limits(12, 0.4, (ClientLimit(OTHER, 0.3, 60),)))
        self.assertEqual((limits.per_hour(OTHER), limits.per_hour(CALLER)), (60, 12))
        for old, new in (("reviews_per_hour = 12", "reviews_per_hour = 0"),
                         ("client_share = 0.4", "client_share = 1.5"),
                         ("share = 0.3", "share = 0"),
                         (f'client = "{OTHER}"', 'client = "unknown-app"'),
                         ("share = 0.3\n", f'share = 0.6\n\n[[limits.clients]]\nclient = "{CALLER}"\nshare = 0.6\n')):
            (self.root / "config.toml").write_text(base + good.replace(old, new))
            with self.subTest(change=new), self.assertRaises(ConfigError):
                load(self.root / "config.toml")


if __name__ == "__main__":
    unittest.main()
