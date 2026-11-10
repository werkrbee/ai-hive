"""harnesses.py's check refuses a matrix row whose claims don't name their evidence, and a
table that has fallen behind the registry."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import harnesses  # noqa: E402


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.registry = harnesses.load()

    def harness(self, registry, harness_id):
        return next(h for h in registry["harnesses"] if h["id"] == harness_id)

    def problems(self, mutate):
        registry = copy.deepcopy(self.registry)
        mutate(registry)
        return harnesses.check(registry)

    def assertRefused(self, mutate, text):
        problems = self.problems(mutate)
        self.assertTrue(any(text in p for p in problems), problems)

    def test_the_registry_as_committed_passes(self):
        self.assertEqual(harnesses.check(self.registry), [])

    def test_a_claim_names_its_source(self):
        self.assertRefused(lambda r: self.harness(r, "claude-code")["capabilities"]["rules"].pop("source"),
                           "rules: names no source")

    def test_a_source_is_a_url_or_a_repo_file(self):
        self.assertRefused(lambda r: self.harness(r, "claude-code")["cost"]["sources"].append("my notes"),
                           "neither an https URL nor a file in the repo")

    def test_a_claim_has_a_date_checked(self):
        self.assertRefused(lambda r: self.harness(r, "cursor")["capabilities"]["skills"].update(checked="Nov 2026"),
                           "no date checked")

    def test_an_unknown_needs_no_evidence(self):
        self.assertEqual(self.problems(lambda r: self.harness(r, "devin-desktop")["capabilities"]["rules"].update(
            supported="unknown")), [])

    def test_a_row_has_every_field_of_its_category(self):
        self.assertRefused(lambda r: self.harness(r, "n8n")["capabilities"].pop("a2a"), "its row lacks 'a2a'")

    def test_a_cost_names_known_models_and_basis(self):
        self.assertRefused(lambda r: self.harness(r, "codex")["cost"]["tokens"]["models"].append("gpt-9"),
                           "which isn't in models")
        self.assertRefused(lambda r: self.harness(r, "codex")["cost"]["tokens"].update(basis="cheap"),
                           "cost basis must be one of")

    def test_only_a_top_ten_harness_has_a_row(self):
        self.assertRefused(lambda r: self.harness(r, "zed").update(cost={}), "only a harness in a top ten")

    def test_the_table_is_current(self):
        self.assertRefused(lambda r: r["models"]["gpt-5-5"].update(output=31), "harness-matrix.md is out of date")

    def test_an_own_key_row_states_no_fee_it_cannot_source(self):
        text = harnesses.effective(self.harness(self.registry, "n8n"), self.registry)
        self.assertNotIn("no harness fee", text)
        self.assertIn("plus each execution", text)

    def test_a_fee_makes_the_effective_rate_list_plus_fee(self):
        [(name, inp, cached, out)] = harnesses.effective(self.harness(self.registry, "cursor"), self.registry)
        self.assertEqual((inp, cached, out), ("$2.25", "unknown", "$10.25"))


if __name__ == "__main__":
    unittest.main()
