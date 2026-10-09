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


def write_config(root, ceiling=25.0, in_price=3.0, out_price=15.0, provider="stub"):
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
provider = "{provider}"
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
        self.assertEqual(entry["tokens"], entry["tokenDetail"]["input"] + entry["tokenDetail"]["output"])
        self.assertGreater(entry["usd"], 0)
        problems = []
        check_knowledge.check_ledger(self.root / "data/ledger.jsonl", problems.append)
        self.assertEqual(problems, [], "the ledger must be in knowledge-hive's format")

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

    # --- configuration and providers -------------------------------------

    def test_config_refuses_unsafe_settings(self):
        write_config(self.root)
        base = (self.root / "config.toml").read_text()
        for old, new in (('allowed_clients = ["lineup-app", "singularity-app"]', "allowed_clients = []"),
                         ('public_url = "http://localhost/"', 'public_url = "http://example.org/"'),
                         ('jwks_path = "jwks.json"', 'jwks_url = "http://keys.example.test"'),
                         ("monthly_ceiling_usd = 25.0", "monthly_ceiling_usd = 0"),
                         ('provider = "stub"', 'provider = "mystery"')):
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
            return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}],
                                             "usage": {"prompt_tokens": 13, "completion_tokens": 5}})

        async def run():
            import os
            os.environ["HIVE_TEST_KEY"] = "test-key"
            out = []
            for name in ("anthropic", "openai"):
                config = write_config(self.root, provider=name)
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


if __name__ == "__main__":
    unittest.main()
