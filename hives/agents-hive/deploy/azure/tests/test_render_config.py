"""Tests for render_config.py: the config the app and the weekly job start from.

Standard library only. Run from the repo root:
  python3 -B -m unittest discover -s hives/agents-hive/deploy/azure/tests -p 'test_*.py'
"""
import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

try:
    import tomllib  # 3.11 and later, as in the image and CI
except ImportError:
    tomllib = None

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]

spec = importlib.util.spec_from_file_location("render_config", HERE.parent / "render_config.py")
rc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rc)

ENV = {"PUBLIC_URL": "https://patricia-a2a.example/", "AZURE_TENANT_ID": "t", "API_APP_ID": "a",
       "ALLOWED_CLIENTS": "c1, c2", "MODEL_API": "messages", "MODEL_PUBLISHER": "Anthropic",
       "MODEL_NAME": "review-a", "MODEL_BASE_URL": "https://ai.example/anthropic",
       "MODEL_INPUT_USD_PER_MTOK": "2", "MODEL_OUTPUT_USD_PER_MTOK": "10"}
PASSPORT = "hives/agents-hive/passports/patricia/passport.json"
BARRY = "hives/agents-hive/passports/barry/passport.json"
BARRY_ENV = {"PERSONA": "barry", "PATRICIA_URL": "https://patricia-a2a.example/", "PATRICIA_API_APP_ID": "p",
             "CALLERS": "v1=verify, l1 = lineup"}


@unittest.skipIf(tomllib is None, "needs Python 3.11 or later to read the TOML")
class Render(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        for rel in [PASSPORT, BARRY] + rc.pinned_prompts(REPO) + rc.pinned_prompts(REPO, "barry"):
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(REPO / rel, self.root / rel)

    def config(self, **env):
        return tomllib.loads(rc.render({**ENV, **env}, self.root))

    def test_the_prompt_files_are_the_ones_the_passport_pins_in_its_order(self):
        server = self.config()["server"]
        self.assertEqual(server["prompt_files"], [
            "hives/rules-hive/rules/queen-charter/AGENTS.md",
            "hives/skills-hive/skills/patricia/SKILL.md",
            "hives/agents-hive/agents/charter-review/agent.md"])

    def test_a_prompt_file_that_isnt_the_pinned_version_stops_the_container(self):
        charter = self.root / "hives/rules-hive/rules/queen-charter/AGENTS.md"
        charter.write_text(charter.read_text() + "\nOne more rule.\n")
        with self.assertRaisesRegex(SystemExit, "AGENTS.md isn't the version the passport pins"):
            self.config()
        charter.unlink()
        with self.assertRaisesRegex(SystemExit, "which the passport pins, isn't in the image"):
            self.config()

    def test_the_app_and_the_job_each_keep_a_ledger_and_share_the_others(self):
        app = self.config(SHARED_LEDGERS="/data/ledger-eval.jsonl")["server"]
        self.assertEqual((app["ledger"], app["shared_ledgers"]), ("/data/ledger.jsonl", ["/data/ledger-eval.jsonl"]))
        job = self.config(LEDGER="/data/ledger-eval.jsonl", SHARED_LEDGERS="/data/ledger.jsonl")["server"]
        self.assertEqual((job["ledger"], job["shared_ledgers"]), ("/data/ledger-eval.jsonl", ["/data/ledger.jsonl"]))
        self.assertEqual(self.config()["server"]["shared_ledgers"], [])

    def test_barrys_config_runs_orchestration_with_patricia_and_his_callers(self):
        c = self.config(**BARRY_ENV)
        self.assertEqual((c["server"]["persona"], c["server"]["capability"]), ("barry", "orchestration"))
        self.assertEqual(c["server"]["prompt_files"], rc.pinned_prompts(REPO, "barry"))
        self.assertNotIn("required_roles", c["auth"], "his roles are checked per method")
        o = c["orchestration"]
        self.assertEqual((o["passport"], o["state_dir"], o["reviewer"]), ("barry", "/data/runs", "patricia"))
        self.assertEqual(o["delegates"], [{"name": "patricia", "url": "https://patricia-a2a.example/",
                                           "capability": "governance-review", "token_scope": "api://p/.default"}])
        self.assertEqual(o["callers"], [{"client": "v1", "registration": "verify"},
                                        {"client": "l1", "registration": "lineup"}])

    def test_patricias_config_has_no_orchestration_and_keeps_her_role(self):
        c = self.config()
        self.assertNotIn("orchestration", c)
        self.assertEqual(c["auth"]["required_roles"], ["Review.Request"])

    def test_barry_needs_patricia_and_well_formed_callers(self):
        with self.assertRaisesRegex(SystemExit, "missing environment: PATRICIA_URL, PATRICIA_API_APP_ID"):
            self.config(PERSONA="barry")
        with self.assertRaisesRegex(SystemExit, "client=registration pairs"):
            self.config(**{**BARRY_ENV, "CALLERS": "v1"})
        with self.assertRaisesRegex(SystemExit, "PERSONA must be one of"):
            self.config(PERSONA="queen")
        self.assertNotIn("callers", self.config(**{**BARRY_ENV, "CALLERS": ""})["orchestration"])


if __name__ == "__main__":
    unittest.main()
