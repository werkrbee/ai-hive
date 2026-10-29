"""Smoke tests for hive_a2a: no network, a stub or mock model, locally signed tokens.

Run from servers/a2a with the requirements installed:
  python -m unittest discover -s tests -v
"""
import asyncio
import datetime
import json
import sys
import tempfile
import time
import unittest
import unittest.mock
import uuid
from pathlib import Path

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.testclient import TestClient

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from hive_a2a import providers  # noqa: E402
from hive_a2a.app import create_app  # noqa: E402
from hive_a2a.config import REPO_ROOT, ConfigError, load  # noqa: E402
from hive_a2a.providers import Completion  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / "hives/knowledge-hive/scripts"))
sys.dont_write_bytecode = True  # don't leave __pycache__ in another hive
import check_knowledge  # noqa: E402
sys.dont_write_bytecode = False

ISSUER = "https://login.example.test/tenant/v2.0"
AUDIENCE = "api-app"
CALLER, OTHER, STRANGER = "lineup-app", "singularity-app", "unknown-app"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
WRONG_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def token(client=CALLER, key=KEY, kid="k1", **claims):
    body = {"iss": ISSUER, "aud": AUDIENCE, "azp": client, "exp": int(time.time()) + 600, **claims}
    return jwt.encode(body, key, algorithm="RS256", headers={"kid": kid})


def write_config(root, ceiling=25.0, in_price=3.0, out_price=15.0, api="stub", publisher="Test Labs"):
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key()))
    (root / "jwks.json").write_text(json.dumps({"keys": [{**jwk, "kid": "k1", "use": "sig", "alg": "RS256"}]}))
    (root / "config.toml").write_text(f"""
[server]
persona = "patricia"
capability = "governance-review"
public_url = "http://localhost/"
database = "data/tasks.db"
ledger = "data/ledger.jsonl"
monthly_ceiling_usd = {ceiling}
prompt_files = ["hives/rules-hive/rules/queen-charter/AGENTS.md"]

[auth]
issuer = "{ISSUER}"
audience = "{AUDIENCE}"
jwks_path = "jwks.json"
token_url = "https://login.example.test/tenant/oauth2/v2.0/token"
scope = "api://api-app/.default"
allowed_clients = ["{CALLER}", "{OTHER}"]

[model]
api = "{api}"
publisher = "{publisher}"
name = "test-model"
base_url = "https://models.example.test"
api_key_env = "HIVE_TEST_KEY"
input_usd_per_mtok = {in_price}
output_usd_per_mtok = {out_price}
max_output_tokens = 2000
""")
    return load(root / "config.toml")


def message(parts, message_id=None):
    return {"message": {"messageId": message_id or str(uuid.uuid4()), "role": "ROLE_USER", "parts": parts}}


PROPOSAL = [{"data": {"proposal": "Force-push main to drop a commit.", "context": "A teammate asked."}}]


class Gate:
    """A provider that waits until released, to hold a task in working."""

    name, model = "gate", "gate-model"

    def __init__(self):
        self.release = asyncio.Event()

    async def complete(self, system, user, max_tokens):
        await self.release.wait()
        return Completion(json.dumps({"verdict": "block", "reason": "r"}), 10, 5)

    async def aclose(self):
        pass


class Fixed:
    name, model = "fixed", "fixed-model"

    def __init__(self, text):
        self.text = text

    async def complete(self, system, user, max_tokens):
        return Completion(self.text, 100, 20)

    async def aclose(self):
        pass


class Recording(Fixed):
    """Records each call's system and user prompts."""

    def __init__(self, text):
        super().__init__(text)
        self.calls = []

    async def complete(self, system, user, max_tokens):
        self.calls.append((system, user))
        return await super().complete(system, user, max_tokens)


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def client(self, config, **kwargs):
        return TestClient(create_app(config, **kwargs))

    def rpc(self, client, method, params, who=CALLER, auth=None):
        headers = {"A2A-Version": "1.0",
                   "Authorization": auth if auth is not None else f"Bearer {token(who)}"}
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        return client.post("/", json=body, headers=headers)

    def send(self, client, parts=PROPOSAL, who=CALLER, **config):
        params = message(parts)
        if config:
            params["configuration"] = config
        r = self.rpc(client, "SendMessage", params, who)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def ledger(self):
        path = self.root / "data/ledger.jsonl"
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    # --- card and auth ---------------------------------------------------

    def test_card_is_public_and_declares_oauth2(self):
        with self.client(write_config(self.root)) as c:
            r = c.get("/.well-known/agent-card.json")
        self.assertEqual(r.status_code, 200)
        card = r.json()
        self.assertEqual(card["supportedInterfaces"][0]["url"], "http://localhost/")
        self.assertEqual(card["supportedInterfaces"][0]["protocolBinding"], "JSONRPC")
        self.assertEqual([s["id"] for s in card["skills"]], ["governance-review"])
        flow = card["securitySchemes"]["oauth2"]["oauth2SecurityScheme"]["flows"]["clientCredentials"]
        self.assertIn("api://api-app/.default", flow["scopes"])
        self.assertEqual(card["securityRequirements"][0]["schemes"]["oauth2"]["list"], ["api://api-app/.default"])
        link = card["capabilities"]["extensions"][0]
        self.assertTrue(link["uri"].endswith("/schema/passport.schema.json"))
        self.assertTrue(link["params"]["passport"].endswith("/passports/patricia/passport.json"))
        passport = json.loads((REPO_ROOT / "hives/agents-hive/passports/patricia/passport.json").read_text())
        self.assertEqual(link["params"]["version"], str(passport["version"]))

    def test_every_request_is_authenticated(self):
        with self.client(write_config(self.root)) as c:
            cases = {
                "": 401,
                "Basic abc": 401,
                f"Bearer {token(key=WRONG_KEY)}": 401,
                f"Bearer {token(aud='someone-else')}": 401,
                f"Bearer {token(iss='https://evil.test/')}": 401,
                f"Bearer {token(exp=int(time.time()) - 3600)}": 401,
                f"Bearer {token(kid='unknown')}": 401,
                f"Bearer {token(STRANGER)}": 403,
                f"Bearer {token(scp='Review.Request')}": 403,
                f"Bearer {token(idtyp='user')}": 403,
            }
            for header, status in cases.items():
                r = self.rpc(c, "ListTasks", {}, auth=header)
                self.assertEqual(r.status_code, status, header[:20])
            self.assertEqual(self.rpc(c, "ListTasks", {}).status_code, 200)
        self.assertEqual(self.ledger(), [])

    # --- the contract ----------------------------------------------------

    def test_review_completes_with_a_verdict_and_a_ledger_entry(self):
        with self.client(write_config(self.root)) as c:
            task = self.send(c)["result"]["task"]
        self.assertEqual(task["status"]["state"], "TASK_STATE_COMPLETED")
        verdict = task["artifacts"][0]["parts"][0]["data"]
        self.assertEqual(verdict["verdict"], "allow-with-conditions")
        self.assertTrue(verdict["reason"])
        [entry] = self.ledger()
        self.assertEqual(entry["capability"], "governance-review")
        self.assertEqual((entry["provider"], entry["api"], entry["model"]), ("test labs", "stub", "test-model"))
        self.assertEqual(entry["tokens"], entry["tokenDetail"]["input"] + entry["tokenDetail"]["output"])
        self.assertGreater(entry["usd"], 0)
        problems = []
        check_knowledge.check_ledger(self.root / "data/ledger.jsonl", problems.append)
        self.assertEqual(problems, [], "the ledger must be in knowledge-hive's format")
        for api in ("", 7):
            with self.subTest(api=api):
                bad = self.root / "bad.jsonl"
                bad.write_text(json.dumps({**entry, "api": api}) + "\n")
                problems = []
                check_knowledge.check_ledger(bad, problems.append)
                self.assertEqual(problems, ["bad.jsonl:1: api must be a non-empty string"])

    def test_text_parts_are_the_proposal(self):
        with self.client(write_config(self.root)) as c:
            task = self.send(c, [{"text": "Delete the release branch."}])["result"]["task"]
        self.assertEqual(task["status"]["state"], "TASK_STATE_COMPLETED")

    def test_input_that_breaks_the_contract_is_invalid_params(self):
        with self.client(write_config(self.root)) as c:
            for parts in ([{"data": {"context": "no proposal"}}],
                          [{"data": {"proposal": 42}}],
                          [{"data": {"proposal": "  "}}],
                          [{"data": {"proposal": "x" * 900_000}}],
                          [{"data": {"proposal": "a"}}, {"text": "b"}]):
                body = self.send(c, parts)
                self.assertEqual(body.get("error", {}).get("code"), -32602, body)
            body = self.send(c, [{"raw": "AAAA", "mediaType": "image/png"}])
            self.assertEqual(body["error"]["code"], -32005, "media the card doesn't declare")
            self.assertEqual(self.rpc(c, "ListTasks", {}).json()["result"].get("tasks", []), [])
        self.assertEqual(self.ledger(), [])

    def test_model_output_that_breaks_the_contract_fails_the_task(self):
        for text in ("not json", json.dumps({"verdict": "maybe", "reason": "r"}), json.dumps({"reason": "r"})):
            with self.subTest(text=text), self.client(write_config(self.root), provider=Fixed(text)) as c:
                task = self.send(c)["result"]["task"]
                self.assertEqual(task["status"]["state"], "TASK_STATE_FAILED")
                self.assertIn("contract", task["status"]["message"]["parts"][0]["text"])
        self.assertEqual(len(self.ledger()), 3, "spend is recorded even when the output is unusable")

    def test_output_is_limited_to_the_contract_fields(self):
        text = "```json\n" + json.dumps({"verdict": "block", "reason": "r", "violation": "v", "extra": 1}) + "\n```"
        with self.client(write_config(self.root), provider=Fixed(text)) as c:
            task = self.send(c)["result"]["task"]
        self.assertEqual(task["artifacts"][0]["parts"][0]["data"], {"verdict": "block", "reason": "r", "violation": "v"})

    def test_time_budget_stops_the_call(self):
        config = write_config(self.root)
        config.contract["budget"]["seconds"] = 0.2
        with self.client(config, provider=Gate()) as c:
            task = self.send(c)["result"]["task"]
        self.assertEqual(task["status"]["state"], "TASK_STATE_FAILED")
        self.assertIn("second budget", task["status"]["message"]["parts"][0]["text"])
        [entry] = self.ledger()
        self.assertGreater(entry["usd"], 0, "a timed-out call may have been billed")
        self.assertNotIn("tokens", entry)

    def test_unbilled_calls_still_reach_the_ceiling(self):
        # Every call times out without reporting usage; the ceiling must still stop them.
        config = write_config(self.root, ceiling=0.05)
        config.contract["budget"]["seconds"] = 0.05
        with self.client(config, provider=Gate()) as c:
            states = [self.send(c)["result"]["task"]["status"]["state"] for _ in range(6)]
        self.assertIn("TASK_STATE_REJECTED", states)
        self.assertLessEqual(sum(e["usd"] for e in self.ledger()), 0.05 + 0.5)

    # --- the ceiling -----------------------------------------------------

    def test_ceiling_refuses_new_reviews_with_a_clear_reason(self):
        # A stub call costs about $0.004 at these prices, so the first one reaches the ceiling.
        with self.client(write_config(self.root, ceiling=0.001, in_price=3.0, out_price=15.0)) as c:
            first = self.send(c)["result"]["task"]
            second = self.send(c)["result"]["task"]
        self.assertEqual(first["status"]["state"], "TASK_STATE_COMPLETED")
        self.assertEqual(second["status"]["state"], "TASK_STATE_REJECTED")
        text, data = (p for p in second["status"]["message"]["parts"])
        self.assertIn("monthly spending ceiling", text["text"])
        self.assertIn("accepted again on", text["text"])
        self.assertEqual(data["data"]["error"], "monthly-ceiling-reached")
        self.assertEqual(data["data"]["ceilingUsd"], 0.001)
        self.assertEqual(len(self.ledger()), 1, "a refused review costs nothing")

    def test_ceiling_counts_the_ledger_already_on_disk(self):
        config = write_config(self.root, ceiling=1.0)
        now = datetime.datetime.now(datetime.timezone.utc)
        (self.root / "data").mkdir()
        (self.root / "data/ledger.jsonl").write_text(
            json.dumps({"at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "basis": "estimated", "usd": 1.0}) + "\n")
        with self.client(config) as c:
            task = self.send(c)["result"]["task"]
        self.assertEqual(task["status"]["state"], "TASK_STATE_REJECTED")

    def test_ceiling_resets_next_month(self):
        config = write_config(self.root, ceiling=1.0)
        (self.root / "data").mkdir()
        (self.root / "data/ledger.jsonl").write_text(
            json.dumps({"at": "2020-01-31T23:59:59Z", "basis": "estimated", "usd": 5.0}) + "\n")
        with self.client(config) as c:
            self.assertEqual(self.send(c)["result"]["task"]["status"]["state"], "TASK_STATE_COMPLETED")

    # --- tasks: isolation, cancel, durability ----------------------------

    def test_callers_see_only_their_own_tasks(self):
        with self.client(write_config(self.root)) as c:
            mine = self.send(c)["result"]["task"]["id"]
            theirs = self.send(c, who=OTHER)["result"]["task"]["id"]
            listed = [t["id"] for t in self.rpc(c, "ListTasks", {}).json()["result"]["tasks"]]
            self.assertEqual(listed, [mine])
            self.assertEqual(self.rpc(c, "GetTask", {"id": theirs}).json()["error"]["code"], -32001)
            self.assertEqual(self.rpc(c, "CancelTask", {"id": theirs}).json()["error"]["code"], -32001)
            self.assertEqual(self.rpc(c, "GetTask", {"id": theirs}, who=OTHER).json()["result"]["id"], theirs)

    def test_no_caller_s_data_reaches_another_call_or_the_shared_prefix(self):
        provider = Recording(json.dumps({"verdict": "allow", "reason": "r"}))
        first = [{"data": {"proposal": "Rotate the lineup signing key."}}]
        theirs = [{"data": {"proposal": "Email the singularity beta list."}}]
        follow_up = [{"data": {"proposal": "And delete the old key."}}]
        with self.client(write_config(self.root), provider=provider) as c:
            context = self.send(c, first)["result"]["task"]["contextId"]
            self.send(c, theirs, who=OTHER)
            params = message(follow_up)
            params["message"]["contextId"] = context
            r = self.rpc(c, "SendMessage", params)
            self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(len(provider.calls), 3)
        systems = {system for system, _ in provider.calls}
        self.assertEqual(len(systems), 1, "every call shares one prefix, the only part a cache could hold")
        [(_, mine), (_, other), (_, later)] = provider.calls
        for text in ("signing key", "beta list", "old key"):
            self.assertNotIn(text, next(iter(systems)))
        self.assertIn("signing key", mine)
        self.assertNotIn("signing key", other)  # another caller's call
        self.assertNotIn("signing key", later)  # the same caller's next message carries no history
        self.assertIn("old key", later)

    def test_cancel_stops_a_working_review(self):
        gate = Gate()
        with self.client(write_config(self.root), provider=gate) as c:
            task = self.send(c, returnImmediately=True)["result"]["task"]
            for _ in range(50):
                state = self.rpc(c, "GetTask", {"id": task["id"]}).json()["result"]["status"]["state"]
                if state == "TASK_STATE_WORKING":
                    break
                time.sleep(0.05)
            self.assertEqual(state, "TASK_STATE_WORKING")
            canceled = self.rpc(c, "CancelTask", {"id": task["id"]}).json()["result"]
            self.assertEqual(canceled["status"]["state"], "TASK_STATE_CANCELED")
            done = self.rpc(c, "CancelTask", {"id": task["id"]}).json()
            self.assertEqual(done["error"]["code"], -32002)
        [entry] = self.ledger()
        self.assertGreater(entry["usd"], 0, "a cancelled call may have been billed")

    def test_tasks_survive_a_restart(self):
        config = write_config(self.root)
        with self.client(config) as c:
            done = self.send(c)["result"]["task"]["id"]
        gate = Gate()
        with self.client(config, provider=gate) as c:
            cut = self.send(c, returnImmediately=True)["result"]["task"]["id"]
            time.sleep(0.3)
        # The gate never opened: the second task was still working at shutdown.
        with self.client(config) as c:
            got = self.rpc(c, "GetTask", {"id": done}).json()["result"]
            self.assertEqual(got["status"]["state"], "TASK_STATE_COMPLETED")
            self.assertEqual(got["artifacts"][0]["parts"][0]["data"]["verdict"], "allow-with-conditions")
            cut_task = self.rpc(c, "GetTask", {"id": cut}).json()["result"]
            self.assertIn(cut_task["status"]["state"], ("TASK_STATE_FAILED", "TASK_STATE_CANCELED"))
            listed = {t["id"] for t in self.rpc(c, "ListTasks", {}).json()["result"]["tasks"]}
            self.assertEqual(listed, {done, cut})
        usd = [e["usd"] for e in self.ledger()]
        self.assertEqual(len(usd), 2, "the completed call, and the cut-off one, once")
        self.assertGreater(usd[1], 0)

    def test_calls_in_flight_when_the_process_dies_are_recorded(self):
        from hive_a2a.ledger import Ledger
        path = self.root / "ledger.jsonl"

        async def crash():
            ledger = Ledger(path, 25.0)
            await ledger.reserve(0.4)
            await ledger.start("task-1", {"usd": 0.4, "basis": "estimated"})
            # ...and the process dies here, before settle.

        asyncio.run(crash())
        ledger = Ledger(path, 25.0)
        self.assertAlmostEqual(ledger.spent(), 0.4)
        self.assertFalse((self.root / "ledger.jsonl.pending").exists())
        self.assertAlmostEqual(Ledger(path, 25.0).spent(), 0.4, msg="recorded once, not on every start")

    def test_a_shared_ledger_counts_toward_the_ceiling_read_afresh(self):
        from hive_a2a.ledger import Ledger, LedgerError
        mine, theirs = self.root / "ledger.jsonl", self.root / "ledger-eval.jsonl"
        now = datetime.datetime.now(datetime.timezone.utc)
        stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        last_month = (now.replace(day=1) - datetime.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        ledger = Ledger(mine, 1.0, shared=[theirs])

        async def reserve():
            refusal = await ledger.reserve(0.1)
            if refusal is None:
                await ledger.settle(0.1)
            return refusal

        self.assertIsNone(asyncio.run(reserve()), "a shared ledger not yet written counts nothing")
        theirs.write_text(json.dumps({"at": last_month, "usd": 5.0}) + "\n"
                          + json.dumps({"at": stamp, "usd": 0.6}) + "\n")
        self.assertIsNone(asyncio.run(reserve()), "only this month's spending counts")
        theirs.with_name(theirs.name + ".pending").write_text(json.dumps({"job-1": {"usd": 0.4}}))
        refusal = asyncio.run(reserve())
        self.assertIsNotNone(refusal, "written after this ledger was opened, with its calls in flight")
        self.assertAlmostEqual(refusal.spent_usd, 1.0)
        theirs.write_text("not json\n")
        with self.assertRaises(LedgerError):
            asyncio.run(reserve())

    # --- configuration and providers -------------------------------------

    def test_config_refuses_unsafe_settings(self):
        write_config(self.root)
        base = (self.root / "config.toml").read_text()
        for old, new in (('allowed_clients = ["lineup-app", "singularity-app"]', "allowed_clients = []"),
                         ('public_url = "http://localhost/"', 'public_url = "http://example.org/"'),
                         ('jwks_path = "jwks.json"', 'jwks_url = "http://keys.example.test"'),
                         ("monthly_ceiling_usd = 25.0", "monthly_ceiling_usd = 0"),
                         ('api = "stub"', 'api = "mystery"'),
                         ('publisher = "Test Labs"', 'publisher = " "'),
                         ('api = "stub"\npublisher = "Test Labs"', 'api = "messages"')):
            (self.root / "config.toml").write_text(base.replace(old, new))
            with self.subTest(change=new), self.assertRaises(ConfigError):
                load(self.root / "config.toml")

    def test_http_providers_send_the_right_requests(self):
        seen = []

        def handle(request):
            seen.append(request)
            if request.url.path.endswith("/v1/messages"):
                return httpx.Response(200, json={"content": [{"type": "text", "text": "{}"}],
                                                 "usage": {"input_tokens": 11, "output_tokens": 7}})
            return sse({"choices": [{"delta": {"content": "{}"}}], "usage": None},
                       {"choices": [], "usage": {"prompt_tokens": 13, "completion_tokens": 5}})

        async def run():
            import os
            os.environ["HIVE_TEST_KEY"] = "test-key"
            out = []
            for name in ("messages", "chat-completions"):
                config = write_config(self.root, api=name)
                p = providers.create(config.model, transport=httpx.MockTransport(handle))
                out.append(await p.complete("sys", "user", 100))
                await p.aclose()
            return out

        a, o = asyncio.run(run())
        self.assertEqual((a.input_tokens, a.output_tokens, o.input_tokens, o.output_tokens), (11, 7, 13, 5))
        ra, ro = seen
        self.assertEqual(str(ra.url), "https://models.example.test/v1/messages")
        self.assertEqual(ra.headers["x-api-key"], "test-key")
        self.assertEqual(json.loads(ra.content)["max_tokens"], 100)
        self.assertEqual(str(ro.url), "https://models.example.test/chat/completions")
        self.assertEqual(ro.headers["authorization"], "Bearer test-key")
        self.assertEqual(json.loads(ro.content)["max_completion_tokens"], 100)
        self.assertEqual(json.loads(ro.content)["stream_options"], {"include_usage": True})

    def test_chat_completions_reads_the_stream(self):
        # Each case: the events streamed back, then the text and tokens read from them, or
        # the error. Usage comes only in the last chunk, as Foundry sends it.
        usage = {"prompt_tokens": 13, "completion_tokens": 5}
        cases = {
            "text across chunks, usage last": (
                sse({"choices": [], "prompt_filter_results": []},
                    {"choices": [{"delta": {"role": "assistant", "content": ""}}], "usage": None},
                    {"choices": [{"delta": {"content": '{"verdict": '}}], "usage": None},
                    {"choices": [{"delta": {"content": '"allow"}'}}], "usage": None},
                    {"choices": [], "usage": usage}),
                ('{"verdict": "allow"}', 13, 5)),
            "usage never sent": (
                sse({"choices": [{"delta": {"content": "{}"}}], "usage": None}),
                "has no token usage"),
            "usage but no text": (sse({"choices": [], "usage": usage}), "has no message"),
            "an event that isn't JSON": (httpx.Response(200, text="data: {not json\n\n"), "isn't JSON"),
            "an error mid-stream": (
                sse({"choices": [{"delta": {"content": "{"}}]}, {"error": {"message": "overloaded"}}),
                "streamed an error"),
            "refused": (httpx.Response(429, json={"error": {"code": "429"}}), "returned HTTP 429"),
        }

        async def call(response):
            config = write_config(self.root, api="chat-completions")
            p = providers.create(config.model, transport=httpx.MockTransport(lambda request: response))
            try:
                c = await p.complete("sys", "user", 100)
                return (c.text, c.input_tokens, c.output_tokens)
            except providers.ProviderError as e:
                return str(e)
            finally:
                await p.aclose()

        import os
        os.environ["HIVE_TEST_KEY"] = "test-key"
        for name, (response, expected) in cases.items():
            with self.subTest(case=name):
                got = asyncio.run(call(response))
                if isinstance(expected, tuple):
                    self.assertEqual(got, expected)
                else:
                    self.assertIn(expected, got)


    def test_a_refusal_carries_its_status_and_wait_and_a_cut_off_reply_says_so(self):
        replies = {
            "messages": [httpx.Response(429, headers={"retry-after": "7"}, json={}),
                         httpx.Response(200, json={"content": [{"type": "text", "text": '{"verd'}],
                                                   "stop_reason": "max_tokens",
                                                   "usage": {"input_tokens": 11, "output_tokens": 100}})],
            "chat-completions": [httpx.Response(503, text="busy"),
                                 sse({"choices": [{"delta": {"content": '{"verd'}, "finish_reason": "length"}]},
                                     {"choices": [], "usage": {"prompt_tokens": 13, "completion_tokens": 100}})],
        }

        async def run(name):
            config = write_config(self.root, api=name)
            queue = list(replies[name])
            p = providers.create(config.model, transport=httpx.MockTransport(lambda request: queue.pop(0)))
            try:
                with self.assertRaises(providers.ProviderError) as refused:
                    await p.complete("sys", "user", 100)
                return refused.exception, await p.complete("sys", "user", 100)
            finally:
                await p.aclose()

        self.enterContext(unittest.mock.patch.dict("os.environ", {"HIVE_TEST_KEY": "test-key"}))
        error, cut = asyncio.run(run("messages"))
        self.assertEqual((error.status, error.retry_after, cut.cut_off), (429, 7.0, True))
        error, cut = asyncio.run(run("chat-completions"))
        self.assertEqual((error.status, error.retry_after, cut.cut_off), (503, None, True))


def sse(*chunks):
    """A Chat Completions stream: one data event per chunk, then [DONE]."""
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})


if __name__ == "__main__":
    unittest.main()
