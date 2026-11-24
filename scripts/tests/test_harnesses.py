"""harnesses.py's check refuses a matrix row whose claims don't name their evidence, and a
table that has fallen behind the registry."""
import copy
import datetime
import re
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

    def test_a_platform_rate_is_quoted_for_what_it_applies_to(self):
        [(applies, inp, cached, out)] = harnesses.effective(self.harness(self.registry, "copilot-studio"),
                                                            self.registry)
        self.assertIn("reasoning model", applies)
        self.assertEqual((inp, cached, out), ("$100", "$0", "$100"))
        self.assertIn(f"{applies}: $100 · $0 · $100", harnesses.render_matrix(self.registry))

    def test_a_platform_basis_gives_a_rate_and_what_it_applies_to(self):
        rule = "a platform basis gives a rate"
        self.assertRefused(lambda r: self.harness(r, "copilot-studio")["cost"]["tokens"]["rate"].pop("cached"), rule)
        self.assertRefused(lambda r: self.harness(r, "copilot-studio")["cost"]["tokens"].pop("applies"), rule)
        self.assertRefused(lambda r: self.harness(r, "copilot-studio")["cost"]["tokens"].update(
            models=["claude-opus-5-5"]), rule)
        self.assertRefused(lambda r: self.harness(r, "agentforce")["cost"]["tokens"].update(
            rate={"input": 1, "cached": 0, "output": 1}), "go with the platform basis")

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
    """Every date is pinned to 2026-01-01, so these don't start failing as time passes."""

    @staticmethod
    def registry_pinned():
        registry = copy.deepcopy(harnesses.load())
        for h in registry["harnesses"]:
            for c in h.get("capabilities", {}).values():
                if "checked" in c:
                    c["checked"] = "2026-01-01"
            if "cost" in h:
                h["cost"]["checked"] = "2026-01-01"
        for m in registry["models"].values():
            m["checked"] = "2026-01-01"
            m.pop("until", None)
            m.pop("then", None)
        return registry

    def setUp(self):
        self.registry = self.registry_pinned()

    def kinds(self, today, where=None):
        return {(w, kind) for w, kind, _, _, _ in harnesses.stale(self.registry, today)
                if where is None or w == where}

    def test_a_price_is_stale_after_thirty_days(self):
        self.assertEqual(harnesses.stale(self.registry, datetime.date(2026, 1, 31)), [])  # 30 days
        stale = harnesses.stale(self.registry, datetime.date(2026, 2, 1))  # 31 days
        self.assertIn(("Claude Code", "price", "2026-01-01", 31, 30), stale)
        rows = {w for w, kind, _, _, _ in stale if kind == "price" and not w.startswith("model ")}
        self.assertEqual(len(rows), 20)
        self.assertEqual(sum(w.startswith("model ") for w, _, _, _, _ in stale), len(self.registry["models"]))

    def test_capabilities_are_stale_after_thirty_days_too(self):
        for h in self.registry["harnesses"]:
            if "cost" in h:
                h["cost"]["checked"] = "2026-01-31"
        for m in self.registry["models"].values():
            m["checked"] = "2026-01-31"
        self.assertEqual(harnesses.stale(self.registry, datetime.date(2026, 1, 31)), [])  # 30 days
        stale = harnesses.stale(self.registry, datetime.date(2026, 2, 1))  # 31 days
        self.assertIn(("Claude Code", "capabilities", "2026-01-01", 31, 30), stale)
        self.assertEqual({kind for _, kind, _, _, _ in stale}, {"capabilities"})

    def test_a_stale_model_price_names_the_rows_that_quote_it(self):
        model = harnesses.get("codex", self.registry)["cost"]["tokens"]["models"][0]
        quoting = [h["name"] for h in self.registry["harnesses"]
                   if model in h.get("cost", {}).get("tokens", {}).get("models", [])]
        self.assertIn("Codex", quoting)
        self.registry["models"][model]["checked"] = "2025-12-01"
        [(where, kind, oldest, days, limit)] = harnesses.stale(self.registry, datetime.date(2026, 1, 20))
        self.assertEqual((where, kind, oldest, days, limit),
                         (f"model {model!r} (quoted by {', '.join(quoting)})", "price", "2025-12-01", 50, 30))
        self.registry["models"]["gpt-5-5"]["checked"] = "2025-12-01"  # quoted by no row, still listed
        self.assertIn(("model 'gpt-5-5'", "price"), self.kinds(datetime.date(2026, 1, 20)))

    def test_check_says_which_kind_of_date_went_stale(self):
        problems = harnesses.check(self.registry, datetime.date(2026, 2, 1))
        self.assertIn("Claude Code: its price was last checked 2026-01-01, 31 days ago (over 30); re-verify it, "
                      "as CONTRIBUTING.md describes", problems)
        self.assertIn("Claude Code: its capabilities were last checked 2026-01-01, 31 days ago (over 30); "
                      "re-verify them, as CONTRIBUTING.md describes", problems)

    def test_a_launch_price_fails_the_check_the_day_after_its_last_day(self):
        """until is the launch price's last day: the price changes the day after."""
        self.registry["models"]["gemini-4-argon"].update(until="2026-01-10",
                                                         then={"input": 4, "cached": 0.2, "output": 20})
        ended = "model 'gemini-4-argon': its launch price ended on 2026-01-10"
        on_last_day = harnesses.check(self.registry, datetime.date(2026, 1, 10))
        self.assertFalse(any(ended in p for p in on_last_day), on_last_day)
        day_after = harnesses.check(self.registry, datetime.date(2026, 1, 11))
        self.assertTrue(any(ended in p for p in day_after), day_after)
        self.assertEqual(self.kinds(datetime.date(2026, 1, 11)), set(), "inside 30 days, and still failing")

    def test_the_launch_price_shows_in_the_model_s_name(self):
        launch = {"name": "Gemini 4 Argon", "until": "2026-11-30", "then": {"input": 4, "cached": 0.2, "output": 20}}
        self.assertEqual(harnesses.model_name(launch),
                         "Gemini 4 Argon (launch price to 2026-11-30, then $4 · $0.20 · $20)")
        self.assertEqual(harnesses.model_name({"name": "X", "until": "2026-11-30"}), "X (launch price to 2026-11-30)")
        self.assertEqual(harnesses.model_name({"name": "X"}), "X")

    def test_until_and_then_are_validated(self):
        def refused(mutate, text):
            registry = copy.deepcopy(self.registry)
            mutate(registry)
            problems = harnesses.check(registry, datetime.date(2026, 1, 2))
            self.assertTrue(any(text in p for p in problems), problems)

        argon = lambda r: r["models"]["gemini-4-argon"]  # noqa: E731
        refused(lambda r: argon(r).update(until="end of November"), "until is the launch price's last day")
        refused(lambda r: argon(r).update(then={"input": 4, "cached": 0.2, "output": 20}),
                "then is the price after until, and goes with it")
        refused(lambda r: argon(r).update(until="2026-11-30", then={"input": 4}),
                "then gives input, cached, output, each a price or null")
        refused(lambda r: next(h for h in r["harnesses"] if h["id"] == "codex")["cost"].update(until="2026-11-30"),
                "until goes on a model's price, not a row's cost")


class DueTest(unittest.TestCase):
    """Every price is pinned to 2026-01-01 and every capability to 2026-01-10, so these don't
    start failing as time passes, and the two fall due on different days."""

    def setUp(self):
        self.registry = copy.deepcopy(harnesses.load())
        for h in self.registry["harnesses"]:
            for c in h.get("capabilities", {}).values():
                if "checked" in c:
                    c["checked"] = "2026-01-10"
            if "cost" in h:
                h["cost"]["checked"] = "2026-01-01"
        for m in self.registry["models"].values():
            m["checked"] = "2026-01-01"
            m.pop("until", None)
            m.pop("then", None)

    def test_a_price_is_listed_from_a_week_before_it_falls_due(self):
        # Checked 2026-01-01, a price is stale from 2026-02-01, its 31st day.
        self.assertEqual(harnesses.due(self.registry, 7, datetime.date(2026, 1, 24)), [])
        listed = harnesses.due(self.registry, 7, datetime.date(2026, 1, 25))
        self.assertEqual({when for when, _, _, _ in listed}, {datetime.date(2026, 2, 1)})
        self.assertIn((datetime.date(2026, 2, 1), "Claude Code", "cost last checked 2026-01-01, stale after 30 days",
                       harnesses.get("claude-code", self.registry)["cost"]["sources"]), listed)
        self.assertEqual(len(listed), 20 + len(self.registry["models"]), "every row's cost and every model")

    def test_a_price_already_due_stays_listed(self):
        prices = [e for e in harnesses.due(self.registry, 7, datetime.date(2026, 3, 1))
                  if not e[2].startswith("capabilities")]
        self.assertEqual(len(prices), 20 + len(self.registry["models"]))

    def test_a_launch_price_is_listed_for_the_day_after_its_last_day(self):
        self.registry["models"]["gemini-4-argon"]["until"] = "2026-01-10"
        listed = harnesses.due(self.registry, 7, datetime.date(2026, 1, 4))
        self.assertEqual(listed, [(datetime.date(2026, 1, 11),
                                   "model 'gemini-4-argon' (quoted by Gemini CLI and Antigravity)",
                                   "launch price ends on 2026-01-10", ["https://aistudio.google.com/docs/pricing"])])
        self.assertEqual(harnesses.due(self.registry, 7, datetime.date(2026, 1, 3)), [])

    def test_nothing_due_lists_nothing(self):
        self.assertEqual(harnesses.due_lines(self.registry, 7, datetime.date(2026, 1, 2)), [])

    @staticmethod
    def two_rows():
        """A registry of its own: two top-ten rows whose oldest capability differs."""
        def row(name, checked):
            return {"name": name, "tier": "top-ten", "cost": {},
                    "capabilities": {"rules": {"checked": checked[0], "source": f"https://example.test/{name}/rules"},
                                     "skills": {"checked": checked[1], "source": f"https://example.test/{name}/skills"},
                                     "mcp": {"supported": "unknown"}}}
        return {"harnesses": [row("A", ("2026-01-10", "2026-01-20")), row("B", ("2026-01-15", "2026-01-15")),
                              {"name": "Watched", "tier": "watch", "capabilities": {
                                  "rules": {"checked": "2025-01-01", "source": "https://example.test/w"}}}],
                "models": {}}

    def test_capabilities_are_listed_from_a_week_before_they_fall_due(self):
        # A's oldest capability was checked 2026-01-10, so they're stale from 2026-02-10.
        self.assertEqual(harnesses.due(self.two_rows(), 7, datetime.date(2026, 2, 2)), [])
        self.assertEqual(harnesses.due(self.two_rows(), 7, datetime.date(2026, 2, 3)), [
            (datetime.date(2026, 2, 10), "A", "capabilities last checked 2026-01-10, stale after 30 days",
             ["https://example.test/A/rules", "https://example.test/A/skills"])])

    def test_capabilities_already_due_stay_listed(self):
        listed = harnesses.due(self.two_rows(), 7, datetime.date(2026, 3, 1))
        self.assertEqual([(when, where) for when, where, _, _ in listed],
                         [(datetime.date(2026, 2, 10), "A"), (datetime.date(2026, 2, 15), "B")],
                         "soonest first, and a row outside the tens isn't listed")

    def test_a_capability_line_names_the_row_and_its_pages(self):
        lines = harnesses.due_lines(self.two_rows(), 7, datetime.date(2026, 2, 3))
        self.assertEqual(lines, ["- **2026-02-10** A: capabilities last checked 2026-01-10, stale after 30 days. "
                                 "Read again: <https://example.test/A/rules>, <https://example.test/A/skills>"])

    def test_the_list_is_markdown_naming_the_date_where_and_pages(self):
        lines = harnesses.due_lines(self.registry, 7, datetime.date(2026, 1, 30))
        self.assertIn("- **2026-02-01** model 'gpt-5-5': price last checked 2026-01-01, stale after 30 days. "
                      "Read again: <https://developers.openai.com/api/docs/pricing>", lines)
        self.assertFalse(any(re.search(r"(?i)\b(close[sd]?|fix(e[sd])?|resolve[sd]?)\b", line) for line in lines),
                         "the issue body closes nothing")


class ImpossibleDateTest(unittest.TestCase):
    """A date written YYYY-MM-DD that isn't on the calendar is a problem check names, never a
    crash. Dates are pinned to 2026-01-01; the reading helpers get a registry of their own."""

    def setUp(self):
        self.registry = StaleTest.registry_pinned()
        self.today = datetime.date(2026, 1, 2)

    def check(self, mutate):
        mutate(self.registry)
        return harnesses.check(self.registry, self.today)

    def test_an_impossible_checked_is_named_where_it_is(self):
        claude = harnesses.get("claude-code", self.registry)
        cap = next(k for k, c in claude["capabilities"].items() if c["supported"] != "unknown")
        problems = self.check(lambda r: (claude["capabilities"][cap].update(checked="2026-02-30"),
                                         claude["cost"].update(checked="2026-13-01"),
                                         r["models"]["gpt-5-5"].update(checked="2026-04-31")))
        self.assertIn(f"harness 'claude-code': {cap}: checked is 2026-02-30, a day that doesn't exist", problems)
        self.assertIn("harness 'claude-code': cost: checked is 2026-13-01, a day that doesn't exist", problems)
        self.assertIn("model 'gpt-5-5': checked is 2026-04-31, a day that doesn't exist", problems)

    def test_an_impossible_until_is_named_on_its_model(self):
        problems = self.check(lambda r: r["models"]["gemini-4-argon"].update(
            until="2026-11-31", then={"input": 4, "cached": 0.2, "output": 20}))
        self.assertIn("model 'gemini-4-argon': until is 2026-11-31, a day that doesn't exist", problems)

    def test_an_impossible_run_date_is_named_on_its_run(self):
        claude = harnesses.get("claude-code", self.registry)
        problems = self.check(lambda r: claude["runs"][0].update(date="2026-02-29"))
        self.assertIn("harness 'claude-code': run 1 date is 2026-02-29, a day that doesn't exist", problems)
        low_code = dict(LowCodeRunTest.run_of_patricia(), date="2026-06-31")
        self.assertEqual([p for p in harnesses.run_problems(low_code, "low-code", {}) if "date" in p],
                         ["date is 2026-06-31, a day that doesn't exist"])

    def test_due_stale_and_launch_ended_pass_over_an_impossible_date(self):
        registry = {"harnesses": [], "models": {
            "real": {"checked": "2026-01-01", "until": "2026-01-05", "source": "https://example.test/real"},
            "impossible": {"checked": "2026-02-30", "until": "2026-02-31", "source": "https://example.test/x"}}}
        today = datetime.date(2026, 3, 1)
        self.assertEqual(harnesses.due(registry, 7, today), [
            (datetime.date(2026, 1, 6), "model 'real'", "launch price ends on 2026-01-05",
             ["https://example.test/real"]),
            (datetime.date(2026, 2, 1), "model 'real'", "price last checked 2026-01-01, stale after 30 days",
             ["https://example.test/real"])])
        self.assertEqual(harnesses.stale(registry, today), [("model 'real'", "price", "2026-01-01", 59, 30)])
        self.assertEqual(harnesses.launch_ended(registry, today), [("real", "2026-01-05")])
        self.assertEqual(len(harnesses.due_lines(registry, 7, today)), 2)


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
        self.assertFalse(any(f.startswith("databricks-genie-code:") for f in failures))
        self.assertTrue(any(r.startswith("databricks-genie-code: skills (global)") for r in reports))
        self.assertIn("goose: no install paths yet", reports)
        self.assertEqual({f.split(": ", 1)[1].split(" ", 1)[0] for f in failures}, {"skills"})


if __name__ == "__main__":
    unittest.main()
