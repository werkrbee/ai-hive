"""Tests for hosted Barry's executor: the loop on the engine, delegation, the caller's MCP
tools, budget stops, the ceiling, resume, expiry and cancel. No network: a scripted model,
and mock MCP and A2A servers behind one httpx transport.

Run from servers/a2a with the requirements installed:
  python -m unittest discover -s tests -v
"""
import asyncio
import dataclasses
import datetime
import json
import shutil
import sys
import tempfile
import time
import unittest
import unittest.mock
import uuid
from pathlib import Path

import httpx
import jwt
from starlette.testclient import TestClient

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))  # the shared token and key helpers in test_server

from hive_a2a.app import create_app  # noqa: E402
from hive_a2a.config import REPO_ROOT, ConfigError, load  # noqa: E402
from hive_a2a.orchestrate import IDEMPOTENCY_META, Network  # noqa: E402
from hive_a2a import orchestrate  # noqa: E402
from hive_a2a.providers import Completion, ProviderError, ToolCall  # noqa: E402
from test_server import AUDIENCE, CALLER, ISSUER, KEY, OTHER, check_knowledge, token  # noqa: E402

PATRICIA = "https://patricia.test/"
LINEUP = "https://lineup.test/mcp"
FINAL = {"summary": "Done.", "results": [{"workstream": "bullpen", "result": "sent"}]}
WAITS = ("TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_CANCELED", "TASK_STATE_REJECTED",
         "TASK_STATE_INPUT_REQUIRED")


def write_config(root, ceiling=25.0, callers=((CALLER, "lineup"),), delegates=(("patricia", PATRICIA),),
                 reviewer=None):
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key()))
    (root / "jwks.json").write_text(json.dumps({"keys": [{**jwk, "kid": "k1", "use": "sig", "alg": "RS256"}]}))
    tables = "".join(f'\n[[orchestration.delegates]]\nname = "{n}"\nurl = "{u}"\ncapability = "governance-review"\n'
                     f'token_scope = "api://{n}/.default"\n' for n, u in delegates)
    tables += "".join(f'\n[[orchestration.callers]]\nclient = "{c}"\nregistration = "{r}"\n' for c, r in callers)
    (root / "config.toml").write_text(f"""
[server]
persona = "barry"
capability = "orchestration"
public_url = "http://localhost/"
database = "data/tasks.db"
ledger = "data/ledger.jsonl"
monthly_ceiling_usd = {ceiling}
prompt_files = ["hives/rules-hive/rules/queen-charter/AGENTS.md", "hives/skills-hive/skills/barry/SKILL.md"]

[auth]
issuer = "{ISSUER}"
audience = "{AUDIENCE}"
jwks_path = "jwks.json"
token_url = "https://login.example.test/tenant/oauth2/v2.0/token"
scope = "api://barry-api/.default"
allowed_clients = ["{CALLER}", "{OTHER}"]

[model]
api = "stub"
publisher = "Test Labs"
name = "test-model"
input_usd_per_mtok = 3.0
output_usd_per_mtok = 15.0
max_output_tokens = 2000

[orchestration]
passport = "barry"
state_dir = "data/runs"
{f'reviewer = "{reviewer}"' if reviewer else ""}
{tables}""")
    return load(root / "config.toml")


def call(name, arguments, n=1):
    return Completion("", 100, 20, tool_calls=(ToolCall(f"call-{n}", name, arguments),))


def final(value=FINAL, **usage):
    return Completion(json.dumps(value), usage.get("i", 100), usage.get("o", 20))


BOTH = ("Orchestration.Request", "Orchestration.Approve")
GATE = object()  # in a script: wait until the test opens the gate


class Scripted:
    """A model that replies from a script, recording what each turn was sent."""

    name, model = "scripted", "scripted-model"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.seen = []
        self.gate = None
        self.waiting = False

    async def converse(self, system, history, tools, max_tokens):
        self.seen.append({"history": history, "tools": [t.name for t in tools], "max_tokens": max_tokens})
        reply = self.replies.pop(0)
        if reply is GATE:
            self.gate = asyncio.Event()
            self.waiting = True
            await self.gate.wait()
            reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    async def aclose(self):
        pass


class Servers:
    """lineup's MCP server and Patricia's A2A server, as mocks, recording what they're sent."""

    MEMBERS = {"m1": True, "m2": True, "m3": False}
    TOOLS = ["send_message", "cancel_event", "remove_member", "delete_group", "get_member", "estimate_cost",
             "charge_fee"]

    def __init__(self):
        self.calls, self.reviews = [], []
        self.members = dict(self.MEMBERS)
        self.estimate = "$0.02"
        self.verdict = {"verdict": "allow", "reason": "Fine."}
        self.patricia_up = True

    def __call__(self, request):
        body = json.loads(request.content)
        if request.url.host == "patricia.test":
            self.reviews.append({"auth": request.headers["authorization"], "body": body})
            if not self.patricia_up:
                return httpx.Response(503)
            task = {"id": "p1", "contextId": "pc", "status": {"state": "TASK_STATE_COMPLETED"},
                    "artifacts": [{"artifactId": "a", "parts": [{"data": self.verdict}]}]}
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"task": task}})
        assert request.headers["authorization"] == "Bearer token-for-api://<lineup-api-app-id>/.default"
        if "id" not in body:
            return httpx.Response(202)
        method, params = body["method"], body.get("params", {})
        if method == "initialize":
            return httpx.Response(200, headers={"mcp-session-id": "s1"}, json={"jsonrpc": "2.0", "id": body["id"], "result": {
                "protocolVersion": "2026-07-28", "capabilities": {"tools": {}}, "serverInfo": {"name": "lineup"}}})
        assert request.headers["mcp-session-id"] == "s1"
        if method == "tools/list":
            tools = [{"name": t, "description": f"lineup's {t}", "inputSchema": {"type": "object"}} for t in self.TOOLS]
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"tools": tools}})
        self.calls.append({"tool": params["name"], "arguments": params["arguments"], "meta": params.get("_meta")})
        if params["name"] == "get_member":
            result = {"structuredContent": {"notifyOptIn": self.members.get(params["arguments"]["member"])}}
        elif params["name"] == "estimate_cost":
            result = {"content": [{"type": "text", "text": json.dumps({"estimate": self.estimate})}]}
        else:
            result = {"content": [{"type": "text", "text": f"{params['name']} done"}]}
        event = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result})
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=f"event: message\ndata: {event}\n\n")

    def sent(self, tool):
        return [c for c in self.calls if c["tool"] == tool]


async def fake_token(scope):
    return f"token-for-{scope}"


class OrchestrateTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.servers = Servers()
        self.now = [datetime.datetime.now(datetime.timezone.utc)]

    def client(self, config, provider, token=fake_token):
        network = Network(transport=httpx.MockTransport(self.servers), token=token, endpoint=lambda mcp: LINEUP)
        self.app = create_app(config, provider=provider, network=network, clock=lambda: self.now[0])
        return TestClient(self.app)

    def rpc(self, client, method, params, who=CALLER, roles=BOTH):
        headers = {"A2A-Version": "1.0", "Authorization": f"Bearer {token(who, roles=list(roles))}"}
        r = client.post("/", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, headers=headers)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def start(self, client, goal="Fill the open bullpen slot.", trigger=None, facts=None, who=CALLER):
        message = {"messageId": str(uuid.uuid4()), "role": "ROLE_USER", "parts": [{"data": {"goal": goal}}]}
        metadata = {k: v for k, v in (("trigger", trigger), ("facts", facts)) if v is not None}
        if metadata:
            message["metadata"] = metadata
        reply = self.rpc(client, "SendMessage", {"message": message}, who)
        self.assertIn("result", reply, reply)
        return reply["result"]["task"]

    def answer(self, client, task, who=CALLER, roles=BOTH, **approval):
        message = {"messageId": str(uuid.uuid4()), "role": "ROLE_USER", "taskId": task["id"],
                   "contextId": task["contextId"], "parts": [{"data": {"approval": approval}}]}
        return self.rpc(client, "SendMessage", {"message": message}, who, roles)

    def request(self, task):
        """The approval request a paused task's status message carries."""
        [data] = [p["data"] for p in task["status"]["message"]["parts"] if "data" in p]
        return data["approval"]

    def wait(self, client, task_id, until=WAITS, who=CALLER):
        for _ in range(200):
            task = self.rpc(client, "GetTask", {"id": task_id}, who)["result"]
            if task["status"]["state"] in until:
                return task
            time.sleep(0.02)
        self.fail(f"task {task_id} stayed {task['status']['state']}")

    def text(self, task):
        return task["status"]["message"]["parts"][0]["text"]

    def ledger(self):
        path = self.root / "data/ledger.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def record(self, task_id):
        return json.loads((self.root / f"data/runs/{task_id}.json").read_text())

    def holds(self):
        return dict(self.app.state.orchestrator.ledger.holds)

    # --- the loop --------------------------------------------------------

    def test_a_run_delegates_to_patricia_and_completes_with_its_result(self):
        model = Scripted(call("delegate__patricia", {"proposal": "Send the bullpen call."}), final())
        with self.client(write_config(self.root), model) as c:
            task = self.wait(c, self.start(c)["id"])
            holds = self.holds()
        self.assertEqual(task["status"]["state"], "TASK_STATE_COMPLETED", self.text(task))
        self.assertEqual(task["artifacts"][0]["parts"][0]["data"], FINAL)
        [review] = self.servers.reviews
        self.assertEqual(review["auth"], "Bearer token-for-api://patricia/.default")
        self.assertEqual(review["body"]["params"]["message"]["parts"], [{"data": {"proposal": "Send the bullpen call."}}])
        [result] = model.seen[1]["history"][-1]
        self.assertFalse(result.error)
        self.assertEqual(json.loads(result.content)["verdict"], "allow")
        entries = self.ledger()
        self.assertEqual([e["runId"] for e in entries], [task["id"]] * 2, "each turn is metered with the run ID")
        self.assertEqual({e["capability"] for e in entries}, {"orchestration"})
        problems = []
        check_knowledge.check_ledger(self.root / "data/ledger.jsonl", problems.append)
        self.assertEqual(problems, [])
        self.assertEqual(holds, {}, "an ended run's hold is released")

    def test_an_allowed_call_runs_once_with_its_idempotency_key_and_its_arguments_as_given(self):
        text = "A spot opened at 7pm. ${inputs.request} ${steps.t1-1.output}"
        model = Scripted(call("lineup__send_message", {"channel": "sms", "audience": "bullpen",
                                                       "recipients": ["m1", "m2"], "text": text}), final())
        with self.client(write_config(self.root), model) as c:
            task = self.wait(c, self.start(c, trigger="bullpen.slot-opened")["id"])
        self.assertEqual(task["status"]["state"], "TASK_STATE_COMPLETED", self.text(task))
        self.assertEqual([c["arguments"]["member"] for c in self.servers.sent("get_member")], ["m1", "m2"])
        [sent] = self.servers.sent("send_message")
        self.assertEqual(sent["arguments"]["text"], text, "a model's argument is never read as a reference")
        self.assertEqual(sent["meta"], {IDEMPOTENCY_META: f"{task['id']}:t1-1"})
        offered = model.seen[0]["tools"]
        self.assertIn("delegate__patricia", offered)
        self.assertIn("lineup__send_message", offered)
        for hidden in ("lineup__get_member", "lineup__estimate_cost", "lineup__charge_fee"):
            self.assertNotIn(hidden, offered, "fact sources and unlisted tools are never offered")
        [result] = model.seen[1]["history"][-1]
        self.assertEqual(result.content, "send_message done")

    def test_a_gated_call_pauses_the_task_and_never_runs(self):
        model = Scripted(call("lineup__send_message", {"channel": "sms", "audience": "group",
                                                       "recipients": ["m1", "m2"], "text": "Game moved to 7pm."}))
        with self.client(write_config(self.root), model) as c:
            task = self.wait(c, self.start(c, facts={"actor.role": "organizer"})["id"])
            holds = self.holds()
        self.assertEqual(task["status"]["state"], "TASK_STATE_INPUT_REQUIRED")
        self.assertIn("lineup/send_message (message.send under organizer.blast)", self.text(task))
        self.assertEqual(self.servers.sent("send_message"), [])
        self.assertEqual(self.servers.sent("estimate_cost")[0]["arguments"], {"channel": "sms", "recipients": ["m1", "m2"]})
        step = self.record(task["id"])["plan"]["steps"][0]
        self.assertEqual(step["input"]["present"],
                         {"message": "Game moved to 7pm.", "recipient count": 2, "estimated cost": "$0.02"})
        self.assertAlmostEqual(holds[task["id"]], 5 - self.ledger()[0]["usd"], msg="a paused run keeps its hold")

    def test_a_denied_call_fails_the_task_before_it_runs(self):
        cases = {
            "the request says the actor is a member": (
                call("lineup__cancel_event", {"event": "e1", "actor.role": "organizer"}),
                {"actor.role": "member"}, "organizers-only.cancel", "cancel_event"),
            "the model says the recipient opted in": (
                call("lineup__send_message", {"channel": "sms", "audience": "bullpen", "recipients": ["m3"],
                                              "text": "Hi", "notifyOptIn": True}),
                None, "messages.opt-in-only", "send_message"),
        }
        for name, (reply, facts, rule, tool) in cases.items():
            with self.subTest(name), self.client(write_config(self.root), Scripted(reply)) as c:
                task = self.wait(c, self.start(c, trigger="bullpen.slot-opened", facts=facts)["id"])
                self.assertEqual(task["status"]["state"], "TASK_STATE_FAILED")
                self.assertIn(f"prohibited by {rule}", self.text(task))
                self.assertEqual(self.servers.sent(tool), [])
                self.assertEqual(self.holds(), {})

    def test_a_tool_that_isnt_offered_gets_an_error_and_the_loop_goes_on(self):
        model = Scripted(call("lineup__charge_fee", {"member": "m1", "usd": 20}), final())
        with self.client(write_config(self.root), model) as c:
            task = self.wait(c, self.start(c)["id"])
        self.assertEqual(task["status"]["state"], "TASK_STATE_COMPLETED")
        [result] = model.seen[1]["history"][-1]
        self.assertTrue(result.error)
        self.assertIn("no tool named lineup__charge_fee", result.content)
        self.assertEqual(self.servers.calls, [])

    def test_a_final_reply_that_misses_the_schema_is_sent_back_once(self):
        with self.client(write_config(self.root), Scripted(final({"summary": "Done."}), final())) as c:
            task = self.wait(c, self.start(c)["id"])
        self.assertEqual(task["status"]["state"], "TASK_STATE_COMPLETED")
        with self.client(write_config(self.root), Scripted(final({"summary": "Done."}), final("no"))) as c:
            task = self.wait(c, self.start(c)["id"])
        self.assertEqual(task["status"]["state"], "TASK_STATE_FAILED")
        self.assertIn("doesn't match the contract's output", self.text(task))

    def test_a_caller_with_no_registration_can_only_delegate(self):
        model = Scripted(final())
        with self.client(write_config(self.root), model) as c:
            task = self.wait(c, self.start(c, who=OTHER)["id"], who=OTHER)
        self.assertEqual(task["status"]["state"], "TASK_STATE_COMPLETED")
        self.assertEqual(model.seen[0]["tools"], ["delegate__patricia"])

    # --- spend -----------------------------------------------------------

    def test_a_turn_the_run_cant_afford_stops_the_run(self):
        # The first turn reports nearly all of the run's usd, or of its tokens; the next can't fit.
        for name, usage, said in (("usd", {"i": 1_666_000, "o": 0}, "$0.0020"),
                                  ("tokens", {"i": 1_999_000, "o": 0}, "1000 tokens")):
            with self.subTest(name):
                config = write_config(self.root)
                if name == "tokens":
                    config = dataclasses.replace(config, model=dataclasses.replace(config.model, input_usd_per_mtok=0.0))
                model = Scripted(Completion("", usage["i"], usage["o"], tool_calls=(
                    ToolCall("c1", "delegate__patricia", {"proposal": "p"}),)))
                with self.client(config, model) as c:
                    task = self.wait(c, self.start(c)["id"])
                    self.assertEqual(self.holds(), {})
                self.assertEqual(task["status"]["state"], "TASK_STATE_FAILED")
                self.assertIn("no room for another turn", self.text(task))
                self.assertIn(said, self.text(task))
                self.assertEqual(len(model.seen), 1, "the turn that wouldn't fit is never taken")

    def test_the_ceiling_rejects_a_run_it_cant_hold_counting_the_runs_it_holds(self):
        organizer = {"actor.role": "organizer"}
        blast = {"channel": "sms", "audience": "group", "recipients": ["m1"], "text": "Hi"}
        model = Scripted(call("lineup__send_message", blast), call("lineup__send_message", blast))
        with self.client(write_config(self.root, ceiling=10.0), model) as c:
            for _ in range(2):
                self.assertEqual(self.wait(c, self.start(c, facts=organizer)["id"])["status"]["state"],
                                 "TASK_STATE_INPUT_REQUIRED")
            task = self.start(c)
        self.assertEqual(task["status"]["state"], "TASK_STATE_REJECTED")
        text, data = task["status"]["message"]["parts"]
        self.assertIn("New runs are accepted again on", text["text"])
        self.assertEqual(data["data"]["error"], "monthly-ceiling-reached")
        self.assertEqual(data["data"]["neededUsd"], 5)
        self.assertEqual(len(model.seen), 2, "a rejected run never reaches the model")
        self.assertFalse((self.root / f"data/runs/{task['id']}.json").exists())

    # --- rate limits -----------------------------------------------------

    def limited(self, retry_after=None):
        return ProviderError("scripted returned HTTP 429", status=429, retry_after=retry_after)

    def test_a_rate_limited_turn_is_asked_again_unbilled_and_the_run_completes(self):
        model = Scripted(self.limited(), self.limited(retry_after=0), call("delegate__patricia", {"proposal": "p"}),
                         final())
        with unittest.mock.patch.object(orchestrate, "RATE_BACKOFF", 0), \
                self.client(write_config(self.root), model) as c:
            task = self.wait(c, self.start(c)["id"])
            holds = self.holds()
        self.assertEqual(task["status"]["state"], "TASK_STATE_COMPLETED", self.text(task))
        self.assertEqual(len(model.seen), 4, "the refused turn was asked twice more")
        entries = self.ledger()
        self.assertEqual(len(entries), 2, "only the two turns the model answered are charged")
        self.assertEqual(sum(e["usd"] for e in entries), self.record(task["id"])["cost"]["usd"])
        self.assertEqual(holds, {})

    def test_a_turn_still_refused_after_its_retries_fails_the_run_unbilled(self):
        model = Scripted(*[self.limited()] * (orchestrate.RATE_RETRIES + 1))
        with unittest.mock.patch.object(orchestrate, "RATE_BACKOFF", 0), \
                self.client(write_config(self.root), model) as c:
            task = self.wait(c, self.start(c)["id"])
            holds = self.holds()
        self.assertEqual(task["status"]["state"], "TASK_STATE_FAILED")
        self.assertIn(f"refused the turn {orchestrate.RATE_RETRIES + 1} times for its rate limit", self.text(task))
        self.assertEqual(len(model.seen), orchestrate.RATE_RETRIES + 1)
        self.assertEqual(self.ledger(), [], "a refused turn is never billed")
        self.assertEqual(holds, {})

    def test_another_provider_error_isnt_retried(self):
        model = Scripted(ProviderError("scripted returned HTTP 500", status=500))
        with self.client(write_config(self.root), model) as c:
            task = self.wait(c, self.start(c)["id"])
        self.assertEqual(task["status"]["state"], "TASK_STATE_FAILED")
        self.assertEqual(len(model.seen), 1)

    def test_a_wait_past_the_runs_working_time_isnt_taken(self):
        model = Scripted(self.limited(retry_after=10_000))
        with unittest.mock.patch.object(orchestrate, "RATE_WAIT_MAX", 10_000), \
                self.client(write_config(self.root), model) as c:
            task = self.wait(c, self.start(c)["id"])
        self.assertEqual(task["status"]["state"], "TASK_STATE_FAILED")
        self.assertIn("refused the turn 1 time for its rate limit", self.text(task))

    # --- resume, expiry, cancel -------------------------------------------

    def test_a_working_run_resumes_after_a_restart_without_repeating_a_turn_or_a_call(self):
        config = write_config(self.root)
        first = Scripted(call("lineup__send_message", {"channel": "sms", "audience": "bullpen",
                                                       "recipients": ["m1"], "text": "A spot opened."}), GATE)
        with self.client(config, first) as c:
            task_id = self.start(c, trigger="bullpen.slot-opened")["id"]
            for _ in range(200):
                if first.waiting:
                    break
                time.sleep(0.02)
            self.assertTrue(first.waiting, "the second turn is in flight when the server stops")
        record = self.record(task_id)
        self.assertEqual((record["turns"]["t1"]["status"], record["turns"]["t2"]["status"]), ("completed", "working"))
        self.assertEqual(record["steps"]["t1-1"]["status"], "completed")
        second = Scripted(GATE, final())
        with self.client(config, second) as c:
            for _ in range(200):
                if second.waiting:
                    break
                time.sleep(0.02)
            [first_turn, cut_off] = self.ledger()
            self.assertEqual(cut_off["runId"], task_id)
            self.assertNotIn("tokens", cut_off, "the cut-off turn is recorded at its worst case")
            # Held again is the budget less both turns: the cut-off one is spending, not held twice.
            self.assertAlmostEqual(self.holds()[task_id], 5 - first_turn["usd"] - cut_off["usd"], places=6)
            orchestrator = self.app.state.orchestrator
            self.assertAlmostEqual(orchestrator.ledger.run_spent(task_id), first_turn["usd"] + cut_off["usd"])
            c.portal.call(second.gate.set)
            task = self.wait(c, task_id)
        self.assertEqual(task["status"]["state"], "TASK_STATE_COMPLETED", self.text(task))
        self.assertEqual(len(second.seen), 1, "only the cut-off turn is taken again")
        self.assertEqual([type(t).__name__ for t in second.seen[0]["history"]], ["User", "Completion", "list"])
        self.assertEqual(len(self.servers.sent("send_message")), 1, "the completed call isn't made again")
        self.assertEqual(len(self.ledger()), 3, "both turns, and the one cut off, at its worst case")

    def test_a_paused_run_keeps_its_hold_across_a_restart_and_expires_after_seven_days(self):
        config = write_config(self.root)
        model = Scripted(call("lineup__cancel_event", {"event": "e1"}))
        with self.client(config, model) as c:
            task_id = self.wait(c, self.start(c, facts={"actor.role": "organizer"})["id"])["id"]
        with self.client(config, Scripted()) as c:
            self.assertIn(task_id, self.holds())
            self.now[0] += datetime.timedelta(days=6)
            c.portal.call(self.app.state.orchestrator.sweep)
            self.assertEqual(self.wait(c, task_id)["status"]["state"], "TASK_STATE_INPUT_REQUIRED")
            self.now[0] += datetime.timedelta(days=2)
            c.portal.call(self.app.state.orchestrator.sweep)
            task = self.wait(c, task_id, until=("TASK_STATE_FAILED",))
            self.assertEqual(self.holds(), {})
        self.assertIn("expired unanswered", self.text(task))
        self.assertEqual(self.servers.sent("cancel_event"), [])

    def test_cancel_stops_a_paused_run_at_once_and_a_working_one_before_its_next_step(self):
        organizer = {"actor.role": "organizer"}
        model = Scripted(call("lineup__cancel_event", {"event": "e1"}),
                         GATE, call("lineup__send_message", {"channel": "sms", "audience": "bullpen",
                                                             "recipients": ["m1"], "text": "Hi"}))
        with self.client(write_config(self.root), model) as c:
            paused = self.wait(c, self.start(c, facts=organizer)["id"])["id"]
            canceled = self.rpc(c, "CancelTask", {"id": paused})["result"]
            self.assertEqual(canceled["status"]["state"], "TASK_STATE_CANCELED")
            self.assertEqual(self.record(paused)["status"], "cancelled")
            self.assertNotIn(paused, self.holds())
            self.assertEqual(self.rpc(c, "CancelTask", {"id": paused}, who=OTHER)["error"]["code"], -32001)

            working = self.start(c, trigger="bullpen.slot-opened")["id"]
            for _ in range(200):
                if model.waiting:
                    break
                time.sleep(0.02)
            canceled = self.rpc(c, "CancelTask", {"id": working})["result"]
            self.assertEqual(canceled["status"]["state"], "TASK_STATE_CANCELED")
            c.portal.call(model.gate.set)
            for _ in range(200):
                if self.record(working)["status"] == "cancelled" and working not in self.holds():
                    break
                time.sleep(0.02)
            self.assertEqual(self.record(working)["status"], "cancelled")
            self.assertNotIn(working, self.holds())
            self.assertEqual(self.wait(c, working)["status"]["state"], "TASK_STATE_CANCELED")
        self.assertEqual(self.servers.calls, [], "neither run's call ran")

    # --- approvals over A2A ----------------------------------------------

    BLAST = {"channel": "sms", "audience": "group", "recipients": ["m1", "m2"], "text": "Game moved to 7pm."}
    ORGANIZER = {"actor.role": "organizer"}

    def paused(self, c):
        task = self.wait(c, self.start(c, facts=self.ORGANIZER)["id"])
        self.assertEqual(task["status"]["state"], "TASK_STATE_INPUT_REQUIRED", self.text(task))
        return task

    def test_a_paused_task_carries_the_approval_request_and_patricias_review(self):
        model = Scripted(call("lineup__send_message", self.BLAST))
        with self.client(write_config(self.root, reviewer="patricia"), model) as c:
            task = self.paused(c)
        request = self.request(task)
        self.assertTrue(request["id"].startswith("sha256:"))
        self.assertEqual((request["step"], request["tool"], request["action"], request["rules"]),
                         ("t1-1", "lineup/send_message", "message.send", ["organizer.blast"]))
        self.assertEqual(request["present"], {"message": "Game moved to 7pm.", "recipient count": 2,
                                              "estimated cost": "$0.02"})
        self.assertEqual(request["review"], {"verdict": "allow", "reason": "Fine."})
        self.assertEqual(request["id"], self.record(task["id"])["pending"]["id"])
        [review] = self.servers.reviews
        proposal = review["body"]["params"]["message"]["parts"][0]["data"]["proposal"]
        self.assertIn("lineup/send_message", proposal)
        self.assertIn("Game moved to 7pm.", proposal)
        self.assertEqual(len(model.seen), 1, "the executor asks for the review, not the model")

    def test_a_block_is_flagged_and_an_unreachable_reviewer_leaves_it_unreviewed(self):
        for name, verdict, up, said in (("block", {"verdict": "block", "reason": "Too broad."}, True, "flagged it"),
                                        ("down", None, False, "hasn't reviewed it")):
            with self.subTest(name):
                self.servers.verdict, self.servers.patricia_up = verdict, up
                model = Scripted(call("lineup__send_message", self.BLAST))
                with self.client(write_config(self.root, reviewer="patricia"), model) as c:
                    task = self.paused(c)
                review = self.request(task)["review"]
                self.assertEqual(review["verdict"], name if name == "block" else "unreviewed")
                self.assertIn(said, self.text(task))
                self.assertEqual(self.servers.sent("send_message"), [], "either way, it waits for the person")

    def test_a_reviewer_token_that_cant_be_had_leaves_it_unreviewed_and_answerable(self):
        async def no_patricia(scope):
            if "patricia" in scope:
                raise RuntimeError("secret detail from the credential chain")
            return await fake_token(scope)

        model = Scripted(call("lineup__send_message", self.BLAST), final())
        with self.client(write_config(self.root, reviewer="patricia"), model, token=no_patricia) as c:
            task = self.paused(c)
            request = self.request(task)
            self.assertEqual(request["review"]["verdict"], "unreviewed")
            self.assertIn("RuntimeError", request["review"]["reason"])
            self.assertNotIn("secret detail", json.dumps(task), "the caller sees the error's type, not its text")
            self.assertIn("hasn't reviewed it", self.text(task))
            self.answer(c, task, id=request["id"], decision="approve", by="usr_7f3a")
            done = self.wait(c, task["id"], until=("TASK_STATE_COMPLETED", "TASK_STATE_FAILED"))
        self.assertEqual(done["status"]["state"], "TASK_STATE_COMPLETED", self.text(done))
        self.assertEqual(len(self.servers.sent("send_message")), 1)

    def test_concurrent_publishes_ask_the_reviewer_once(self):
        async def slow(scope):  # so the second publish arrives while the first is still asking
            await asyncio.sleep(0.05)
            return await fake_token(scope)

        model = Scripted(call("lineup__send_message", self.BLAST))
        with self.client(write_config(self.root, reviewer="patricia"), model, token=slow) as c:
            task = self.paused(c)
            o = self.app.state.orchestrator
            review = o.review_path(self.request(task)["id"])
            review.unlink()

            async def twice():
                await asyncio.gather(o.publish(task["id"]), o.publish(task["id"]))

            c.portal.call(twice)
        self.assertEqual(len(self.servers.reviews), 2, "one for the first publish, one for both of these")
        self.assertEqual(o.reviewing, {})

    def test_approve_runs_the_recorded_call_and_the_loop_goes_on(self):
        model = Scripted(call("lineup__send_message", self.BLAST), final())
        with self.client(write_config(self.root, reviewer="patricia"), model) as c:
            task = self.paused(c)
            request = self.request(task)
            r = self.answer(c, task, id=request["id"], decision="approve", by="usr_7f3a")
            self.assertEqual(r["result"]["task"]["status"]["state"], "TASK_STATE_WORKING", r)
            done = self.wait(c, task["id"], until=("TASK_STATE_COMPLETED", "TASK_STATE_FAILED"))
            holds = self.holds()
        self.assertEqual(done["status"]["state"], "TASK_STATE_COMPLETED", self.text(done))
        [sent] = self.servers.sent("send_message")
        self.assertEqual(sent["arguments"], self.BLAST, "the recorded call, exactly")
        self.assertEqual(sent["meta"], {IDEMPOTENCY_META: f"{task['id']}:t1-1"})
        self.assertEqual(len(self.servers.sent("estimate_cost")), 2, "looked up again before it ran")
        approval = self.record(task["id"])["steps"]["t1-1"]["approval"]
        self.assertEqual((approval["decision"], approval["by"], approval["via"], approval["id"]),
                         ("approved", "usr_7f3a", "a2a", request["id"]))
        self.assertEqual(len(model.seen), 2, "approval runs the call without asking the model again")
        self.assertEqual(holds, {})

    def test_deny_fails_the_run(self):
        with self.client(write_config(self.root), Scripted(call("lineup__send_message", self.BLAST))) as c:
            task = self.paused(c)
            self.answer(c, task, id=self.request(task)["id"], decision="deny", by="usr_7f3a", reason="Not tonight.")
            done = self.wait(c, task["id"], until=("TASK_STATE_FAILED",))
            self.assertEqual(self.holds(), {})
        self.assertIn("approval denied by usr_7f3a: Not tonight.", self.text(done))
        self.assertEqual(self.servers.sent("send_message"), [])

    def test_a_stale_approval_is_void_and_the_task_asks_again(self):
        model = Scripted(call("lineup__send_message", self.BLAST), final())
        with self.client(write_config(self.root), model) as c:
            task = self.paused(c)
            first = self.request(task)
            self.servers.estimate = "$0.05"  # what the person was shown has changed
            self.answer(c, task, id=first["id"], decision="approve", by="usr_7f3a")
            for _ in range(200):
                again = self.rpc(c, "GetTask", {"id": task["id"]})["result"]
                if again["status"]["state"] == "TASK_STATE_INPUT_REQUIRED" and self.request(again)["id"] != first["id"]:
                    break
                time.sleep(0.02)
            second = self.request(again)
            self.assertNotEqual(second["id"], first["id"])
            self.assertEqual(second["present"]["estimated cost"], "$0.05")
            self.assertEqual(self.servers.sent("send_message"), [], "the stale approval ran nothing")
            refused = self.answer(c, again, id=first["id"], decision="approve", by="usr_7f3a")
            self.assertEqual(refused["error"]["code"], -32602)
            self.answer(c, again, id=second["id"], decision="approve", by="usr_7f3a")
            done = self.wait(c, task["id"], until=("TASK_STATE_COMPLETED", "TASK_STATE_FAILED"))
        self.assertEqual(done["status"]["state"], "TASK_STATE_COMPLETED", self.text(done))
        self.assertEqual(len(self.servers.sent("send_message")), 1)

    def test_a_fact_that_changed_while_it_waited_can_deny_the_approved_call(self):
        with self.client(write_config(self.root), Scripted(call("lineup__send_message", self.BLAST))) as c:
            task = self.paused(c)
            self.servers.members["m2"] = False  # m2 opted out while the task waited
            self.answer(c, task, id=self.request(task)["id"], decision="approve", by="usr_7f3a")
            done = self.wait(c, task["id"], until=("TASK_STATE_FAILED",))
        self.assertIn("prohibited by messages.opt-in-only", self.text(done))
        self.assertEqual(self.servers.sent("send_message"), [])

    def test_an_answer_that_doesnt_answer_what_is_pending_is_refused(self):
        with self.client(write_config(self.root), Scripted(call("lineup__send_message", self.BLAST), final())) as c:
            task = self.paused(c)
            pid = self.request(task)["id"]
            cases = {
                "another id": dict(id="sha256:" + "0" * 64, decision="approve", by="usr_7f3a"),
                "a denial without a reason": dict(id=pid, decision="deny", by="usr_7f3a"),
                "a name, not an actor ID": dict(id=pid, decision="approve", by="Jane Doe"),
                "an unknown decision": dict(id=pid, decision="maybe", by="usr_7f3a"),
            }
            for name, approval in cases.items():
                with self.subTest(name):
                    self.assertEqual(self.answer(c, task, **approval)["error"]["code"], -32602)
            mismatch = self.answer(c, task, **cases["another id"])["error"]
            # A2A carries an error's data as google.rpc.ErrorInfo metadata.
            self.assertEqual(mismatch["data"][0]["metadata"]["pending"], pid)
            self.assertEqual(self.rpc(c, "GetTask", {"id": task["id"]})["result"]["status"]["state"],
                             "TASK_STATE_INPUT_REQUIRED")
            self.answer(c, task, id=pid, decision="approve", by="usr_7f3a")
            self.wait(c, task["id"], until=("TASK_STATE_COMPLETED",))
            late = self.answer(c, task, id=pid, decision="approve", by="usr_7f3a")
            self.assertIn("error", late, "a task that ended takes no answer")
        self.assertEqual(len(self.servers.sent("send_message")), 1)

    def test_each_method_needs_its_role(self):
        with self.client(write_config(self.root), Scripted(call("lineup__send_message", self.BLAST))) as c:
            message = {"messageId": "m", "role": "ROLE_USER", "parts": [{"data": {"goal": "g"}}]}
            started = self.rpc(c, "SendMessage", {"message": message}, roles=("Orchestration.Approve",))
            self.assertEqual(started["error"]["code"], -32600)
            self.assertIn("Orchestration.Request", started["error"]["message"])
            task = self.paused(c)
            pid = self.request(task)["id"]
            answered = self.answer(c, task, roles=("Orchestration.Request",), id=pid, decision="approve", by="usr_7f3a")
            self.assertEqual(answered["error"]["code"], -32600)
            self.assertIn("Orchestration.Approve", answered["error"]["message"])
            cancelled = self.rpc(c, "CancelTask", {"id": task["id"]}, roles=("Orchestration.Approve",))
            self.assertEqual(cancelled["error"]["code"], -32600)
            self.assertEqual(self.rpc(c, "GetTask", {"id": task["id"]}, roles=())["result"]["status"]["state"],
                             "TASK_STATE_INPUT_REQUIRED", "reading your own task needs no role")
        self.assertEqual(self.servers.sent("send_message"), [])

    def test_another_caller_can_neither_see_nor_answer_a_task(self):
        with self.client(write_config(self.root), Scripted(call("lineup__send_message", self.BLAST))) as c:
            task = self.paused(c)
            pid = self.request(task)["id"]
            self.assertEqual(self.rpc(c, "GetTask", {"id": task["id"]}, who=OTHER)["error"]["code"], -32001)
            theirs = self.answer(c, task, who=OTHER, id=pid, decision="approve", by="usr_7f3a")
            self.assertEqual(theirs["error"]["code"], -32001)
            self.assertEqual(self.rpc(c, "GetTask", {"id": task["id"]})["result"]["status"]["state"],
                             "TASK_STATE_INPUT_REQUIRED")
        self.assertEqual(self.servers.sent("send_message"), [])

    # --- config ----------------------------------------------------------

    def test_config_refuses_a_caller_or_delegate_it_cant_trust(self):
        with self.assertRaisesRegex(ConfigError, "isn't on auth.allowed_clients"):
            write_config(self.root, callers=(("stranger-app", "lineup"),))
        with self.assertRaisesRegex(ConfigError, "no registration 'nowhere'"):
            write_config(self.root, callers=((CALLER, "nowhere"),))
        # A registration whose server is named delegate, kept beside lineup's while the test runs.
        name = f"collision-{uuid.uuid4().hex[:8]}"
        lineup = REPO_ROOT / "hives/agents-hive/registrations/lineup"
        here = lineup.parent / name
        here.mkdir()
        self.addCleanup(shutil.rmtree, here)
        for f in ("registration.json", "cases.json"):
            text = (lineup / f).read_text().replace('"lineup/', '"delegate/').replace('"name": "lineup"', '"name": "delegate"')
            (here / f).write_text(text.replace('"registration": "lineup"', f'"registration": "{name}"'))
        with self.assertRaisesRegex(ConfigError, "collide with the delegation tools"):
            write_config(self.root, callers=((CALLER, name),))
        config = write_config(self.root, delegates=(("security-review", PATRICIA), ("lineup-bot", PATRICIA)))
        with self.assertRaisesRegex(ValueError, "doesn't list lineup-bot"):
            create_app(config, provider=Scripted())


if __name__ == "__main__":
    unittest.main()
