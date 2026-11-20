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
        self.assertEqual(self.problems(lambda r: self.harness(r, "dify")["capabilities"]["mcp"].update(
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

    def test_the_guides_index_is_current(self):
        self.assertRefused(lambda r: self.harness(r, "dify")["cost"].update(unit="Message credit, $0.02"),
                           "harness-guides.md is out of date")

    def test_the_guides_index_shows_each_of_the_twenty_and_says_what_is_missing(self):
        with tempfile.TemporaryDirectory() as guides:
            (Path(guides) / "claude-code.md").write_text("# Barry on Claude Code\n")
            page = harnesses.render_guides(self.registry, guides)
        rows = [line for line in page.splitlines() if line.startswith("| ") and line[2].isdigit()]
        self.assertEqual(len(rows), 20)
        claude = next(line for line in rows if "Claude Code" in line)
        self.assertIn("[`claude-code.md`](../hives/skills-hive/skills/barry/references/harnesses/claude-code.md)",
                      claude)
        self.assertIn("Barry 2026-11-10, Patricia 2026-11-10", claude)
        self.assertIn("[verified](harness-matrix.md#pro-code)", claude)
        kiro = next(line for line in rows if "Kiro" in line)
        self.assertEqual(kiro.count("none yet"), 2, "no guide in this directory, and no run")
        self.assertIn("1 of 10 have a guide", page)

    def test_an_own_key_row_states_no_fee_it_cannot_source(self):
        text = harnesses.effective(self.harness(self.registry, "n8n"), self.registry)
        self.assertNotIn("no harness fee", text)
        self.assertIn("plus each execution", text)

    def test_a_fee_makes_the_effective_rate_list_plus_fee(self):
        [(name, inp, cached, out)] = harnesses.effective(self.harness(self.registry, "cursor"), self.registry)
        self.assertEqual((inp, cached, out), ("$2.25", "$0.35", "$10.25"))

    def test_a_model_with_cache_reads_under_the_threshold_is_exempt_from_the_fee(self):
        registry = copy.deepcopy(self.registry)
        tokens = self.harness(registry, "cursor")["cost"]["tokens"]
        tokens["models"] = ["claude-sonnet-5-5", "gpt-6-luna"]  # cache reads $0.10 and $0.01
        sonnet, luna = harnesses.effective(self.harness(registry, "cursor"), registry)
        self.assertEqual(sonnet[1:], ("$2.25", "$0.35", "$10.25"), "$0.10 isn't strictly under $0.10")
        self.assertEqual(luna[1:], ("$0.10", "$0.01", "$0.50"), "no fee on any token of an exempt model")
        matrix = harnesses.render_matrix(registry)
        self.assertIn("GPT-6 Luna (prompts up to 272,000 tokens): $0.10 · $0.01 · $0.50 (list; exempt from the "
                      "fee, cache reads under $0.10)", matrix)
        self.assertIn("$10.25 (Teams and Enterprise, list + $0.25)", matrix)

    def test_an_exemption_needs_a_recorded_cached_rate(self):
        registry = copy.deepcopy(self.registry)
        registry["models"]["claude-sonnet-5-5"]["cached"] = None
        [row] = harnesses.effective(self.harness(registry, "cursor"), registry)
        self.assertEqual(row[1:], ("unknown", "unknown", "unknown"))

    def test_an_exemption_is_a_number_and_goes_with_a_fee(self):
        self.assertRefused(lambda r: self.harness(r, "cursor")["cost"]["tokens"].update(fee_exempt_below="cheap"),
                           "fee_exempt_below is a non-negative number")
        self.assertRefused(lambda r: self.harness(r, "codex")["cost"]["tokens"].update(fee_exempt_below=0.1),
                           "fee_exempt_below is a non-negative number, and goes with a fee")

    def test_a_fee_leaves_cached_unknown_unless_the_row_says_it_covers_it(self):
        registry = copy.deepcopy(self.registry)
        self.harness(registry, "cursor")["cost"]["tokens"].pop("fee_cached")
        [(_, _, cached, _)] = harnesses.effective(self.harness(registry, "cursor"), registry)
        self.assertEqual(cached, "unknown")

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


class LowCodeRunTest(unittest.TestCase):
    """A low-code row records a run of Patricia in its own shape: the platform's meter and the
    House's, apart, with an unknown count null and never zero."""

    def setUp(self):
        self.registry = copy.deepcopy(harnesses.load())
        dates = [d for h in self.registry["harnesses"] for d in harnesses.row_dates(h, self.registry)]
        self.today = datetime.date.fromisoformat(max(dates))

    @staticmethod
    def run_of_patricia():
        return {"agent": "patricia", "date": "2026-11-15", "version": None, "binding": "mcp", "auth": "app",
                "units": {"amount": 5, "unit": "Copilot Credits", "basis": "reported",
                          "source": "Power Platform admin center, Copilot Studio usage, 2026-11-15"},
                "tokens": {"input": None, "cache_write": None, "cached": None, "output": None},
                "house": {"tokens": 4321, "usd": 0.0123, "taskId": "3f1c9a52-0d4e-4b7a-9c61-2a8e5f0b7d13"},
                "cost": "$0.05 at pay-as-you-go", "result": "pass, and the topic went on"}

    def row(self, registry, harness_id="copilot-studio"):
        return next(h for h in registry["harnesses"] if h["id"] == harness_id)

    def problems(self, mutate):
        registry = copy.deepcopy(self.registry)
        h = self.row(registry)
        h["runs"] = [self.run_of_patricia()]
        mutate(h)
        return harnesses.check(registry, self.today), registry

    def assertRefused(self, mutate, text):
        problems, _ = self.problems(mutate)
        self.assertTrue(any("copilot-studio" in p and text in p for p in problems), problems)

    def test_a_well_formed_run_passes(self):
        problems, registry = self.problems(lambda h: None)
        # Only the table, which is now behind the registry, is out of step.
        self.assertEqual([p for p in problems if "is out of date" not in p], [])

    def test_a_run_lacks_no_field(self):
        for key in harnesses.LOW_CODE_RUN_FIELDS:
            with self.subTest(key=key):
                self.assertRefused(lambda h: h["runs"][0].pop(key), f"run 1 lacks {key}")

    def test_an_unknown_token_count_is_null_not_zero(self):
        self.assertRefused(lambda h: h["runs"][0]["tokens"].update(input=0, output=0),
                           "records an unknown token count as zero; it is null")
        self.assertRefused(lambda h: h["runs"][0]["tokens"].pop("cached"), "counts the platform's tokens")

    def test_known_platform_tokens_pass(self):
        problems, _ = self.problems(lambda h: h["runs"][0]["tokens"].update(
            input=5200, cache_write=None, cached=0, output=610))
        self.assertEqual([p for p in problems if "is out of date" not in p], [])

    def test_units_not_reported_are_null_not_zero(self):
        self.assertRefused(lambda h: h["runs"][0]["units"].update(basis="not-reported", amount=0),
                           "a null amount, never zero")
        problems, _ = self.problems(lambda h: h["runs"][0]["units"].update(basis="not-reported", amount=None))
        self.assertEqual([p for p in problems if "is out of date" not in p], [])
        self.assertRefused(lambda h: h["runs"][0]["units"].update(basis="estimated", amount=None),
                           "estimated units have an amount")
        self.assertRefused(lambda h: h["runs"][0]["units"].pop("source"), "units name their source")

    def test_the_binding_auth_and_agent_are_known(self):
        self.assertRefused(lambda h: h["runs"][0].update(binding="webhook"), "binding must be one of")
        self.assertRefused(lambda h: h["runs"][0].update(auth="key"), "auth must be one of")
        self.assertRefused(lambda h: h["runs"][0].update(agent="barry"), "a low-code run is of patricia")

    def test_the_house_meter_comes_from_the_ledger(self):
        self.assertRefused(lambda h: h["runs"][0]["house"].pop("usd"), "the House's tokens and usd")
        self.assertRefused(lambda h: h["runs"][0]["house"].update(tokens=0), "the House's tokens and usd")
        problems, _ = self.problems(lambda h: h["runs"][0]["house"].pop("taskId"))
        self.assertEqual([p for p in problems if "is out of date" not in p], [])

    def verify(self, h):
        for c in h["capabilities"].values():
            c.update(supported=True, source="https://learn.microsoft.com/microsoft-copilot-studio/",
                     checked="2026-11-10")
        h["verified"] = True

    def test_a_verified_row_records_a_run_of_patricia(self):
        def verified_without_a_run(h):
            self.verify(h)
            h.pop("runs")
        self.assertRefused(verified_without_a_run, "a verified low-code row records a run of patricia")
        problems, _ = self.problems(self.verify)
        self.assertEqual([p for p in problems if "is out of date" not in p], [])

    def test_the_matrix_shows_low_code_runs_in_their_own_table(self):
        registry = copy.deepcopy(self.registry)
        self.row(registry)["runs"] = [self.run_of_patricia()]
        low_code = harnesses.render_matrix(registry).split("## Low-code", 1)[1].split("## Model list prices")[0]
        self.assertIn("The House's tokens · $", low_code)
        self.assertIn("| Copilot Studio | Patricia | 2026-11-15 | not shown | mcp | app | 5 Copilot Credits, "
                      "reported (Power Platform admin center, Copilot Studio usage, 2026-11-15) | "
                      "unknown · unknown · unknown · unknown | $0.05 at pay-as-you-go | 4,321 · $0.0123 | "
                      "pass, and the topic went on |", low_code)
        self.assertNotIn("Copilot Studio |", harnesses.render_matrix(registry).split("## Low-code", 1)[0])



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
        model = harnesses.get("codex", self.registry)["cost"]["tokens"]["models"][0]
        quoting = {h["name"] for h in self.registry["harnesses"]
                   if model in h.get("cost", {}).get("tokens", {}).get("models", [])}
        self.registry["models"][model]["checked"] = "2025-12-01"
        stale = {name for name, _, _ in harnesses.stale(self.registry, datetime.date(2026, 3, 15))}
        self.assertIn("Codex", stale)
        self.assertEqual(stale, quoting)

    def test_check_fails_a_stale_row(self):
        problems = harnesses.check(self.registry, datetime.date(2026, 4, 2))
        self.assertTrue(any("Claude Code: its row was last checked 2026-01-01, 91 days ago" in p
                            for p in problems), problems)


class ConformanceTest(unittest.TestCase):
    """The happy path runs in check-installers.sh; this is the failing one."""

    def test_a_missing_file_fails_a_top_ten_harness_and_is_reported_for_others(self):
        with tempfile.TemporaryDirectory() as sandbox:
            registry = harnesses.load()
            next(h for h in registry["harnesses"] if h["id"] == "goose")["surfaces"] = {}
            failures, reports, _ = harnesses.conformance(
                sandbox, registry,
                prepare=lambda house: (house / "hives/skills-hive/skills/barry/SKILL.md").unlink())
        self.assertIn("claude-code: skills (global) didn't land at "
                      "home/claude-code/.claude/skills/barry/SKILL.md (nothing written there)", failures)
        self.assertFalse(any(f.startswith("scout:") for f in failures))
        self.assertTrue(any(r.startswith("scout: skills (global)") for r in reports))
        self.assertIn("goose: no install paths yet", reports)
        self.assertEqual({f.split(": ", 1)[1].split(" ", 1)[0] for f in failures}, {"skills"})


if __name__ == "__main__":
    unittest.main()
