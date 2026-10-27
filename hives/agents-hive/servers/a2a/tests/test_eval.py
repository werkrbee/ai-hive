"""Tests for the trust evaluation's runner (deploy/azure/eval/run.py --passport): no
network, a fake or stub model, and a throwaway results file, ledger, queue and audit log.

Run from servers/a2a with the requirements installed:
  python -m unittest discover -s tests -v
"""
import argparse
import asyncio
import contextlib
import datetime
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from hive_a2a.config import REPO_ROOT  # noqa: E402
from hive_a2a.providers import Completion  # noqa: E402

sys.dont_write_bytecode = True  # don't leave __pycache__ in another hive
spec = importlib.util.spec_from_file_location("eval_run", REPO_ROOT / "hives/agents-hive/deploy/azure/eval/run.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
sys.dont_write_bytecode = False

PASSPORT = json.loads((REPO_ROOT / "hives/agents-hive/passports/patricia/passport.json").read_text())
CASES = json.loads((REPO_ROOT / PASSPORT["eval"]["suite"]).read_text())["cases"]
RESULTS = REPO_ROOT / PASSPORT["eval"]["baseline"]["result"].split("#")[0]


def write_config(root, persona="patricia", api="stub", price=0.1, ceiling=25.0):
    prompts = ", ".join(f'"{f["path"]}"' for f in PASSPORT["pins"]["prompt"])
    (root / "jwks.json").write_text('{"keys": []}')
    (root / "config.toml").write_text(f"""
[server]
persona = "{persona}"
capability = "governance-review"
public_url = "http://localhost/"
database = "data/tasks.db"
ledger = "data/ledger.jsonl"
monthly_ceiling_usd = {ceiling}
prompt_files = [{prompts}]

[auth]
issuer = "https://login.example.test/tenant/v2.0"
audience = "api-app"
jwks_path = "jwks.json"
token_url = "https://login.example.test/tenant/oauth2/v2.0/token"
scope = "api://api-app/.default"
allowed_clients = ["lineup-app"]

[model]
api = "{api}"
publisher = "Test Labs"
name = "review-test"
base_url = "https://models.example.test"
api_key_env = "HIVE_TEST_KEY"
input_usd_per_mtok = {price}
output_usd_per_mtok = {price}
""")
    return root / "config.toml"


class Faithful:
    """A model that answers each case with the first verdict the Charter allows."""

    name, model = "fake", "review-test"

    def __init__(self, model=None):
        self.calls = 0

    async def complete(self, system, user, max_tokens):
        self.calls += 1
        case = next(c for c in CASES if json.dumps(c["proposal"]) in user)
        text = json.dumps({"verdict": case["accept"][0], "reason": "Per the Charter."})
        return Completion(text, 1000, 50)

    async def aclose(self):
        pass


class Evaluate(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.results = self.tmp / "results.jsonl"
        shutil.copy(RESULTS, self.results)

    def evaluate(self, config, model=None):
        args = argparse.Namespace(passport="patricia", config=[str(config)], spacing=0, results=str(self.results),
                                  state_dir=str(self.tmp / "runs"), queue_dir=None, audit=None)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            if model is None:
                code = asyncio.run(runner.evaluate(args))
            else:
                with mock.patch.object(runner.providers, "create", lambda m: model):
                    code = asyncio.run(runner.evaluate(args))
        self.out = out.getvalue()
        return code

    def recorded(self):
        return json.loads(self.results.read_text().splitlines()[-1])

    def ledger(self):
        path = self.tmp / "data" / "ledger.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def items(self):
        return [json.loads(p.read_text()) for p in sorted((self.tmp / "queue").glob("*.json"))]

    def audit(self):
        return [json.loads(line) for line in (self.tmp / "audit.jsonl").read_text().splitlines()]

    def test_a_run_within_its_baseline_is_recorded_metered_and_offered_as_the_baseline(self):
        model = Faithful()
        self.assertEqual(self.evaluate(write_config(self.tmp), model), 0)
        entry = self.recorded()
        self.assertEqual((entry["outcome"], entry["eval"]["findings"]), ("passed", []))
        self.assertEqual(entry["eval"]["runs"][0]["met"], 12)
        self.assertEqual(entry["eval"]["deployment"], "review-test")
        self.assertEqual(model.calls, 12)
        ledger = self.ledger()
        self.assertEqual(len(ledger), 12)
        self.assertEqual(round(sum(e["usd"] for e in ledger), 6), entry["eval"]["runs"][0]["usd"])
        self.assertEqual(self.items(), [])
        self.assertEqual([e["kind"] for e in self.audit()], ["eval.ran"])
        self.assertIn(f'"result": "{self.results.resolve()}#{entry["id"]}"', self.out)

    def test_the_stub_model_drifts_twice_and_its_drift_goes_to_the_queue(self):
        self.assertEqual(self.evaluate(write_config(self.tmp)), 1)
        entry = self.recorded()
        self.assertEqual([r["met"] for r in entry["eval"]["runs"]], [4, 4])
        self.assertEqual((entry["outcome"], entry["eval"]["findings"]), ("failed", ["drift"]))
        self.assertEqual(len(self.ledger()), 24)
        self.assertEqual([i["source"]["finding"] for i in self.items()], ["drift"])
        self.assertEqual([e["kind"] for e in self.audit()], ["eval.ran", "drift"])
        self.assertIn("the first run drifted; running it once more", self.out)
        self.assertNotIn("To make this run the baseline", self.out)

    def test_an_eval_the_ceiling_refuses_goes_to_the_queue_as_not_run(self):
        (self.tmp / "data").mkdir()
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        (self.tmp / "data" / "ledger.jsonl").write_text(json.dumps({"at": now, "usd": 25.0, "basis": "metered"}) + "\n")
        model = Faithful()
        self.assertEqual(self.evaluate(write_config(self.tmp), model), 1)
        self.assertEqual(model.calls, 0)
        entry = self.recorded()
        self.assertEqual((entry["eval"]["runs"][0]["ran"], entry["eval"]["findings"]), (0, ["not-run"]))
        self.assertEqual([i["source"]["finding"] for i in self.items()], ["not-run"])

    def test_a_dearer_run_is_flagged_for_cost(self):
        self.assertEqual(self.evaluate(write_config(self.tmp, price=100.0), Faithful()), 0)
        self.assertEqual(self.recorded()["eval"]["findings"], ["cost"])
        self.assertEqual([i["source"]["finding"] for i in self.items()], ["cost"])

    def test_a_configuration_that_doesnt_run_the_passports_pins_is_refused(self):
        with self.assertRaises(SystemExit) as stopped:
            self.evaluate(write_config(self.tmp, persona="barry"), Faithful())
        self.assertIn("the configuration is for barry, not patricia", str(stopped.exception))
        self.assertEqual(self.results.read_text(), RESULTS.read_text())


if __name__ == "__main__":
    unittest.main()
