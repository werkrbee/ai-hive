"""Tests for agents-hive passports: the validator's narrowing and pin checks, and the card link.

Standard library only. Run from the repo root:
  python3 -B -m unittest discover -s hives/agents-hive/tests
"""
import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HIVE = Path(__file__).resolve().parent.parent
REPO_ROOT = HIVE.parent.parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, HIVE / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


vp = load("validate_passports")
cards = load("agent_card")


def passport(persona):
    return json.loads((HIVE / "passports" / persona / "passport.json").read_text())


class Checked(unittest.TestCase):
    """Writes a changed passport into a temporary passports/<persona>/ and checks it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def errors(self, p):
        path = Path(self.tmp.name) / p["passport"] / "passport.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(p))
        return vp.check(path)

    def assertRefused(self, p, text):
        errors = self.errors(p)
        self.assertTrue(any(text in e for e in errors), f"expected {text!r} in {errors}")


class RepoPassports(Checked):
    def test_every_passport_in_the_repo_is_valid(self):
        for path in sorted((HIVE / "passports").glob("*/passport.json")):
            with self.subTest(persona=path.parent.name):
                self.assertEqual(self.errors(passport(path.parent.name)), [])

    def test_each_fleet_persona_has_a_passport_on_its_agent_definition_and_barry_lists_it(self):
        for persona in ("explore", "code-review", "security-review", "charter-review"):
            with self.subTest(persona=persona):
                p = passport(persona)
                self.assertNotIn("model", p["pins"])  # run inside a harness, which picks the model
                self.assertIn(f"hives/agents-hive/agents/{persona}/agent.md", [f["path"] for f in p["pins"]["prompt"]])
                self.assertIn(persona, passport("barry")["delegates"])

    def test_a_persona_with_neither_a_card_nor_an_agent_definition_is_refused(self):
        p = dict(passport("explore"), passport="shell")
        self.assertRefused(p, "no Agent Card at cards/shell/card.json, or agent definition at agents/shell/agent.md")

    def test_every_card_has_a_passport(self):
        for card in (HIVE / "cards").glob("*/card.json"):
            self.assertTrue((HIVE / "passports" / card.parent.name / "passport.json").is_file())


class Narrowing(Checked):
    def test_granting_what_the_contract_does_not_allow_is_refused(self):
        p = passport("patricia")
        p["permissions"]["granted"].append("fs.write")
        p["permissions"]["never"].remove("fs.write")
        self.assertRefused(p, "grants 'fs.write', but its contract doesn't allow it")

    def test_granting_what_the_contract_gates_is_refused(self):
        p = passport("barry")
        p["permissions"]["approval"].remove("vcs.push")
        p["permissions"]["granted"].append("vcs.push")
        self.assertRefused(p, "grants 'vcs.push', but its contract puts it under approval")

    def test_moving_a_grant_under_approval_is_allowed(self):
        p = passport("barry")
        p["permissions"]["granted"].remove("fs.write")
        p["permissions"]["approval"].append("fs.write")
        self.assertEqual(self.errors(p), [])

    def test_approval_for_what_the_contract_does_not_allow_is_refused(self):
        p = passport("barry")
        p["permissions"]["never"].remove("infra.change")
        p["permissions"]["approval"].append("infra.change")
        self.assertRefused(p, "puts 'infra.change' under approval, but its contract doesn't allow it")

    def test_a_never_action_that_is_also_granted_is_refused(self):
        p = passport("barry")
        p["permissions"]["never"].append("fs.read")
        self.assertRefused(p, "'fs.read' is in never and also granted or under approval")

    def test_an_unknown_action_is_refused(self):
        p = passport("barry")
        p["permissions"]["never"].append("db.drop")
        self.assertRefused(p, "unknown action 'db.drop'")

    def test_a_budget_above_the_contract_is_refused(self):
        p = passport("patricia")
        p["budget"]["usd"] = 1
        self.assertRefused(p, "budget.usd is 1, more than its contract's 0.5")

    def test_a_contract_version_that_does_not_exist_is_refused(self):
        p = passport("patricia")
        p["contract"]["version"] = 2
        self.assertRefused(p, "contract governance-review is version 1, not 2")


class Pins(Checked):
    def test_a_prompt_file_that_changed_is_refused_with_its_new_digest(self):
        p = passport("patricia")
        p["pins"]["prompt"][0]["sha256"] = "0" * 64
        real = vp.file_sha256(vp.REPO_ROOT / p["pins"]["prompt"][0]["path"])
        self.assertRefused(p, f"doesn't match its pin; its sha256 is now {real}")

    def test_a_policy_that_changed_is_refused(self):
        p = passport("barry")
        p["pins"]["policy"]["sha256"] = "f" * 64
        self.assertRefused(p, "pins.policy hives/rules-hive/rules/queen-charter/policy.json doesn't match its pin")

    def test_a_pinned_file_outside_the_repo_is_refused(self):
        p = passport("barry")
        p["pins"]["prompt"][0]["path"] = "hives/../../etc/passwd"
        self.assertRefused(p, "path must sit under hives/")

    def test_crlf_line_endings_pin_the_same_as_lf(self):
        with tempfile.TemporaryDirectory() as d:
            lf, crlf = Path(d) / "lf.md", Path(d) / "crlf.md"
            lf.write_bytes(b"# Title\n\nText.\n")
            crlf.write_bytes(b"# Title\r\n\r\nText.\r\n")
            self.assertEqual(vp.file_sha256(lf), vp.file_sha256(crlf))

    def test_an_eval_without_a_model_pin_is_refused(self):
        p = passport("patricia")
        del p["pins"]["model"]
        self.assertRefused(p, "eval needs pins.model")

    def test_a_baseline_that_does_not_fit_its_suite_is_refused(self):
        p = passport("patricia")
        n = len(json.loads((REPO_ROOT / p["eval"]["suite"]).read_text())["cases"])
        p["eval"]["baseline"]["of"] = p["eval"]["baseline"]["met"] = n + 1
        self.assertRefused(p, f"eval.baseline.of is {n + 1}, but the suite has {n} cases")

    def test_a_baseline_is_a_results_jsonl_entry(self):
        p = passport("patricia")
        p["eval"]["baseline"]["result"] = "hives/agents-hive/deploy/azure/eval/RESULTS.md#2026-10-21"
        self.assertRefused(p, "must be a results.jsonl file under hives/ and an entry's id")
        p["eval"]["baseline"]["result"] = "hives/agents-hive/deploy/azure/eval/results.jsonl#no-such-run"
        self.assertRefused(p, "eval.baseline.result not found")

    def test_a_baseline_whose_score_isnt_its_results_is_refused(self):
        p = passport("patricia")
        b = p["eval"]["baseline"]
        b["met"] -= 1
        self.assertRefused(p, f"eval.baseline is {b['met']} of {b['of']}, but its result's run met {b['met'] + 1} of {b['of']}")

    def test_a_baseline_that_drifted_or_belongs_to_another_agent_is_refused(self):
        good = vp.baseline_result(passport("patricia")["eval"]["baseline"]["result"])
        for change, text in (
                (lambda r: r["eval"].update(passport="barry"), "isn't an eval of patricia"),
                (lambda r: r["eval"]["runs"].append(r["eval"]["runs"][0]), "must have one run"),
                (lambda r: r["eval"].update(findings=["unconfirmed-miss"]), "a baseline can carry only a cost flag"),
                (lambda r: r["eval"]["runs"][0].update(ran=5), "with 5 run")):
            entry = copy.deepcopy(good)
            change(entry)
            with self.subTest(text=text), mock.patch.object(vp, "baseline_result", lambda ref: entry):
                self.assertRefused(passport("patricia"), text)

    def test_a_critical_mark_that_isnt_a_boolean_is_refused(self):
        with tempfile.TemporaryDirectory(dir=HIVE / "tests") as d:
            suite = json.loads((REPO_ROOT / passport("patricia")["eval"]["suite"]).read_text())
            suite["cases"][0]["critical"] = "yes"
            (Path(d) / "cases.json").write_text(json.dumps(suite))
            p = passport("patricia")
            p["eval"]["suite"] = str((Path(d) / "cases.json").relative_to(REPO_ROOT))
            self.assertRefused(p, "critical must be true or false")

    def test_an_edited_case_is_refused_with_the_suites_new_digest(self):
        with tempfile.TemporaryDirectory(dir=HIVE / "tests") as d:
            p = passport("patricia")
            suite = json.loads((REPO_ROOT / p["eval"]["suite"]).read_text())
            suite["cases"][0]["accept"] = ["block"]  # same count, different case
            path = Path(d) / "cases.json"
            path.write_text(json.dumps(suite, indent=2) + "\n")
            p["eval"]["suite"] = str(path.relative_to(REPO_ROOT))
            self.assertRefused(p, f"pins.suite {p['eval']['suite']} doesn't match its pin; "
                                  f"its sha256 is now {vp.file_sha256(path)}")

    def test_an_eval_needs_its_suite_pinned_and_a_suite_pin_needs_an_eval(self):
        p = passport("patricia")
        del p["pins"]["suite"]
        self.assertRefused(p, "eval needs pins.suite")
        p = passport("barry")
        p["pins"]["suite"] = {"sha256": "0" * 64}
        self.assertRefused(p, "pins.suite pins an eval suite, but the passport has no eval")


class Shape(Checked):
    def test_an_unknown_field_is_refused(self):
        p = passport("barry")
        p["model"] = "anything"
        self.assertRefused(p, "passport has unknown field 'model'")

    def test_a_missing_field_is_refused(self):
        p = passport("barry")
        del p["owner"]
        self.assertRefused(p, "passport is missing 'owner'")

    def test_an_owner_that_is_not_a_github_handle_is_refused(self):
        p = passport("barry")
        p["owner"] = "someone@example.com"
        self.assertRefused(p, "owner must be a GitHub account or team")

    def test_a_delegate_without_a_passport_is_refused(self):
        p = passport("barry")
        p["delegates"].append("shell")
        self.assertRefused(p, "delegate 'shell' has no passport")


class CardLink(unittest.TestCase):
    def test_each_rendered_card_links_its_passport_by_version_and_digest(self):
        for persona in ("barry", "patricia"):
            with self.subTest(persona=persona):
                card = cards.render(persona, f"https://a2a.invalid/{persona}")
                links = [x for x in card["capabilities"]["extensions"] if x["uri"] == cards.PASSPORT_URI]
                self.assertEqual(len(links), 1)
                p = passport(persona)
                self.assertEqual(links[0]["params"]["version"], str(p["version"]))
                self.assertEqual(links[0]["params"]["sha256"], vp.digest(p))
                self.assertEqual(cards.validate(card), [])

    def test_a_card_source_with_its_own_passport_link_is_refused(self):
        source = json.loads((HIVE / "cards" / "barry" / "card.json").read_text())
        source = copy.deepcopy(source)
        source["capabilities"]["extensions"] = [{"uri": cards.PASSPORT_URI}]
        self.assertTrue(any("passport extension" in e for e in cards.validate_source(source)))


if __name__ == "__main__":
    unittest.main()
