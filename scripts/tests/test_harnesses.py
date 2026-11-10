"""harnesses.py's check refuses a matrix row whose claims don't name their evidence, and a
table that has fallen behind the registry."""
import copy
import datetime
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import harnesses  # noqa: E402


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.registry = harnesses.load()
        # The structural tests judge the registry as of its newest date, so they don't start
        # failing as time passes; staleness has tests of its own.
        dates = [d for h in self.registry["harnesses"] for d in harnesses.row_dates(h, self.registry)]
        self.today = datetime.date.fromisoformat(max(dates))

    def harness(self, registry, harness_id):
        return next(h for h in registry["harnesses"] if h["id"] == harness_id)

    def problems(self, mutate):
        registry = copy.deepcopy(self.registry)
        mutate(registry)
        return harnesses.check(registry, self.today)

    def assertRefused(self, mutate, text):
        problems = self.problems(mutate)
        self.assertTrue(any(text in p for p in problems), problems)

    def test_the_registry_as_committed_passes(self):
        self.assertEqual(harnesses.check(self.registry, self.today), [])

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

    def test_a_verified_row_has_no_unknowns(self):
        self.assertRefused(lambda r: self.harness(r, "claude-code")["capabilities"]["hooks"].update(
            supported="unknown"), "a verified row has no unknowns, found hooks")

    def test_a_verified_pro_code_row_records_both_runs(self):
        self.assertRefused(lambda r: self.harness(r, "claude-code")["runs"].pop(),
                           "records a run of barry and patricia")

    def test_a_run_counts_its_tokens(self):
        self.assertRefused(lambda r: self.harness(r, "claude-code")["runs"][0]["tokens"].pop("cached"),
                           "run 1 counts tokens as")
        self.assertRefused(lambda r: self.harness(r, "claude-code")["runs"][1].pop("version"),
                           "run 2 lacks version")

    def test_a_run_names_a_known_model(self):
        self.assertRefused(lambda r: self.harness(r, "github-copilot")["runs"][0].update(model="gpt-9"),
                           "run 1 names model 'gpt-9', which isn't in models")

    def test_an_unverified_row_needs_no_run(self):
        def unverify(r):
            h = self.harness(r, "claude-code")
            h["verified"] = False
            h.pop("runs")
        problems = self.problems(unverify)
        self.assertFalse([p for p in problems if "claude-code" in p], problems)



class StaleTest(unittest.TestCase):
    def setUp(self):
        self.registry = copy.deepcopy(harnesses.load())
        for h in self.registry["harnesses"]:
            for c in h.get("capabilities", {}).values():
                if "checked" in c:
                    c["checked"] = "2026-01-01"
            if "cost" in h:
                h["cost"]["checked"] = "2026-01-01"
        for m in self.registry["models"].values():
            m["checked"] = "2026-01-01"

    def test_a_row_is_stale_after_ninety_days(self):
        self.assertEqual(harnesses.stale(self.registry, datetime.date(2026, 4, 1)), [])  # 90 days
        stale = harnesses.stale(self.registry, datetime.date(2026, 4, 2))  # 91 days
        self.assertEqual(len(stale), 20)
        self.assertIn(("Claude Code", "2026-01-01", 91), stale)

    def test_a_stale_model_price_makes_its_rows_stale(self):
        self.registry["models"]["gpt-5-5"]["checked"] = "2025-12-01"
        stale = {name for name, _, _ in harnesses.stale(self.registry, datetime.date(2026, 3, 15))}
        self.assertEqual(stale, {"Codex"})

    def test_check_fails_a_stale_row(self):
        problems = harnesses.check(self.registry, datetime.date(2026, 4, 2))
        self.assertTrue(any("Claude Code: its row was last checked 2026-01-01, 91 days ago" in p
                            for p in problems), problems)


class ConformanceTest(unittest.TestCase):
    """The happy path runs in check-installers.sh; this is the failing one."""

    def test_a_missing_file_fails_a_top_ten_harness_and_is_reported_for_others(self):
        with tempfile.TemporaryDirectory() as sandbox:
            failures, reports, _ = harnesses.conformance(
                sandbox, prepare=lambda house: (house / "hives/skills-hive/skills/barry/SKILL.md").unlink())
        self.assertIn("claude-code: skills (global) didn't land at "
                      "home/claude-code/.claude/skills/barry/SKILL.md (nothing written there)", failures)
        self.assertFalse(any(f.startswith("scout:") for f in failures))
        self.assertTrue(any(r.startswith("scout: skills (global)") for r in reports))
        self.assertIn("cline: no install paths yet", reports)
        self.assertEqual({f.split(": ", 1)[1].split(" ", 1)[0] for f in failures}, {"skills"})


if __name__ == "__main__":
    unittest.main()
