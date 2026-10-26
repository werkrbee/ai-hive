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

HIVE = Path(__file__).resolve().parent.parent


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
        for persona in ("barry", "patricia"):
            with self.subTest(persona=persona):
                self.assertEqual(self.errors(passport(persona)), [])

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
        p["eval"]["baseline"]["of"] = 13
        p["eval"]["baseline"]["met"] = 13
        self.assertRefused(p, "eval.baseline.of is 13, but the suite has 12 cases")


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
        p["delegates"].append("explore")
        self.assertRefused(p, "delegate 'explore' has no passport")


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
