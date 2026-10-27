"""Tests for the trust evaluation: drift and its re-run, the flags, what an evaluation
records, the baseline a passport points at, and the promotion check deploy.sh runs.

Standard library only. Run from the repo root:
  python3 -B -m unittest discover -s hives/agents-hive/tests
"""
import copy
import importlib.util
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

HIVE = Path(__file__).resolve().parent.parent
REPO_ROOT = HIVE.parent.parent


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


te = load(HIVE / "scripts" / "trust_eval.py", "trust_eval")
knowledge = load(REPO_ROOT / "hives" / "knowledge-hive" / "scripts" / "check_knowledge.py", "check_knowledge")
audit = load(REPO_ROOT / "hives" / "knowledge-hive" / "scripts" / "check_audit.py", "check_audit")

PATRICIA = te.passport("patricia")
SUITE = te.cases(PATRICIA)
CRITICAL = sorted(te.critical(SUITE))
AT = datetime(2030, 1, 15, 9, 0, tzinfo=timezone.utc)  # a day with no real evaluation


def outcomes(miss=(), usd=0.0104):
    """One run's outcomes, meeting every case but those in miss."""
    return [{"id": c["id"], "pass": c["id"] not in miss, "usd": usd, "seconds": 3.0} for c in SUITE]


def run(miss=(), usd=0.0104, stop=None):
    return te.run_record(SUITE, outcomes(miss, usd)[:stop])


class Suite(unittest.TestCase):
    def test_patricias_critical_cases_are_her_six_block_only_cases(self):
        self.assertEqual(set(CRITICAL), {c["id"] for c in SUITE if c["accept"] == ["block"]})
        self.assertEqual(len(CRITICAL), 6)

    def test_the_recorded_results_fit_knowledge_hives_format(self):
        errors = []
        knowledge.check_results(te.results_file(PATRICIA), errors.append)
        self.assertEqual(errors, [])

    def test_a_run_counts_what_it_met_and_missed(self):
        r = run(miss=["local-typo"])
        self.assertEqual((r["met"], r["ran"], r["of"], r["missed"]), (11, 12, 12, ["local-typo"]))
        self.assertEqual((r["usd"], r["seconds"]), (0.1248, 36.0))


class Drift(unittest.TestCase):
    def test_a_run_below_the_baseline_drifts(self):
        self.assertFalse(te.drifts(PATRICIA, SUITE, run()))
        self.assertTrue(te.drifts(PATRICIA, SUITE, run(miss=["local-typo"])))

    def test_the_threshold_allows_that_many_cases_fewer(self):
        p = copy.deepcopy(PATRICIA)
        p["eval"]["threshold"] = 1
        self.assertFalse(te.drifts(p, SUITE, run(miss=["local-typo"])))
        self.assertTrue(te.drifts(p, SUITE, run(miss=["local-typo", "read-search"])))

    def test_a_missed_critical_case_drifts_whatever_the_threshold(self):
        p = copy.deepcopy(PATRICIA)
        p["eval"]["threshold"] = 5
        self.assertTrue(te.drifts(p, SUITE, run(miss=[CRITICAL[0]])))

    def test_drift_is_recorded_only_when_both_runs_drift(self):
        base = te.baseline(PATRICIA)
        both = [run(miss=["local-typo"]), run(miss=["read-search"])]
        self.assertEqual(te.findings(PATRICIA, SUITE, both, base), ["drift"])
        once = [run(miss=["local-typo"]), run()]
        self.assertEqual(te.findings(PATRICIA, SUITE, once, base), [])

    def test_a_critical_miss_in_either_run_alone_is_an_unconfirmed_miss(self):
        base = te.baseline(PATRICIA)
        self.assertEqual(te.findings(PATRICIA, SUITE, [run(miss=[CRITICAL[0]]), run()], base), ["unconfirmed-miss"])
        p = copy.deepcopy(PATRICIA)
        p["eval"]["threshold"] = 1  # so a second run missing one ordinary case doesn't drift
        runs = [run(miss=[CRITICAL[0]]), run(miss=["local-typo"])]
        self.assertEqual(te.findings(p, SUITE, runs, base), ["unconfirmed-miss"])
        both = [run(miss=[CRITICAL[0]]), run(miss=[CRITICAL[1]])]
        self.assertEqual(te.findings(PATRICIA, SUITE, both, base), ["drift"])

    def test_a_run_costing_more_than_twice_its_baseline_per_case_is_flagged_not_drift(self):
        base = te.baseline(PATRICIA)  # $0.1267 for 12 cases
        self.assertEqual(te.findings(PATRICIA, SUITE, [run(usd=0.02)], base), [])
        self.assertEqual(te.findings(PATRICIA, SUITE, [run(usd=0.03)], base), ["cost"])

    def test_a_run_the_ceiling_stopped_is_not_run_not_a_pass(self):
        self.assertEqual(te.findings(PATRICIA, SUITE, [run(stop=5)], te.baseline(PATRICIA)), ["not-run"])
        self.assertEqual(te.outcome(["not-run"]), "failed")
        self.assertEqual(te.outcome(["cost"]), "partial")

    def test_a_critical_miss_before_the_ceiling_stopped_the_eval_still_leaves_a_trace(self):
        base = te.baseline(PATRICIA)
        partial = te.run_record(SUITE, outcomes(miss=["force-push-main"])[:5])
        self.assertEqual(te.findings(PATRICIA, SUITE, [partial], base), ["unconfirmed-miss", "not-run"])
        drifted_then_stopped = [run(miss=[CRITICAL[0]]), run(stop=0)]
        self.assertEqual(te.findings(PATRICIA, SUITE, drifted_then_stopped, base), ["unconfirmed-miss", "not-run"])
        self.assertEqual(te.outcome(["unconfirmed-miss", "not-run"]), "failed")


class Recorded(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.results = self.tmp / "results.jsonl"
        shutil.copy(te.results_file(PATRICIA), self.results)
        self.engine = te.engine.Engine(self.tmp / "runs", log=lambda *a: None, actor="usr_7f3a")

    def record(self, runs, refused=None):
        entry = te.result(PATRICIA, SUITE, runs, AT, "review-a", "abc1234", refused, self.results)
        return entry, te.record(self.engine, PATRICIA, entry, self.results)

    def entries(self, kind):
        lines = (self.tmp / "audit.jsonl").read_text().splitlines()
        return [e for e in map(json.loads, lines) if e["kind"] == kind]

    def test_drift_is_a_result_an_audit_entry_and_a_queue_item(self):
        entry, items = self.record([run(miss=["local-typo"]), run(miss=[CRITICAL[0]])])
        self.assertEqual((entry["id"], entry["outcome"]), ("2030-01-15-patricia-eval", "failed"))
        self.assertEqual(entry["eval"]["pins"], te.pins_digest(PATRICIA))
        self.assertEqual(entry["eval"]["baseline"], te.baseline(PATRICIA)["id"])
        self.assertEqual([i["source"]["finding"] for i in items], ["drift"])
        self.assertEqual(items[0]["present"]["runs"], entry["eval"]["runs"])
        self.assertIsNone(items[0]["expiresAt"])
        errors = []
        knowledge.check_results(self.results, errors.append)
        self.assertEqual(errors, [])
        self.assertEqual(audit.check(self.tmp / "audit.jsonl"), [])
        self.assertEqual(self.entries("eval.ran")[0]["result"], entry["id"])
        self.assertEqual(self.entries("drift")[0]["item"], items[0]["id"])

    def test_flags_are_audited_as_flags(self):
        entry, items = self.record([run(miss=[CRITICAL[0]], usd=0.05), run()])
        self.assertEqual(entry["eval"]["findings"], ["unconfirmed-miss", "cost"])
        self.assertEqual(entry["outcome"], "partial")
        self.assertEqual([i["source"]["finding"] for i in items], ["unconfirmed-miss", "cost"])
        self.assertEqual(len(self.entries("eval.flagged")), 2)
        self.assertEqual(self.entries("drift"), [])

    def test_an_eval_the_ceiling_refused_goes_to_the_queue_as_not_run(self):
        entry, items = self.record([run(stop=3)], refused="Refused: the monthly spending ceiling...")
        self.assertEqual((entry["outcome"], entry["eval"]["findings"]), ("failed", ["not-run"]))
        self.assertIn("ceiling refused the rest", entry["summary"])
        self.assertEqual([i["source"]["finding"] for i in items], ["not-run"])

    def test_a_second_evaluation_on_the_same_day_gets_its_own_id(self):
        first, _ = self.record([run()])
        second, _ = self.record([run()])
        self.assertEqual((first["id"], second["id"]), ("2030-01-15-patricia-eval", "2030-01-15-patricia-eval-2"))


class Promotion(Recorded):
    def current(self):
        """A baseline entry recorded against Patricia's current pins."""
        entry = te.result(PATRICIA, SUITE, [run()], AT, "review-a", path=self.results)
        return entry

    def test_patricias_baseline_was_recorded_against_her_pins_so_she_promotes(self):
        self.assertEqual(te.holds(PATRICIA, te.baseline(PATRICIA), []), [])

    def test_a_baseline_recorded_against_other_pins_holds_promotion(self):
        p = copy.deepcopy(PATRICIA)
        p["eval"]["baseline"]["result"] = p["eval"]["baseline"]["result"].split("#")[0] + "#2026-10-21-patricia-eval"
        problems = te.holds(PATRICIA, te.baseline(p), [])  # her first, before the Charter changed
        self.assertEqual(len(problems), 1)
        self.assertIn("was recorded against other pins", problems[0])
        self.assertIn(te.pins_digest(PATRICIA), problems[0])

    def test_a_baseline_against_its_exact_pins_promotes(self):
        self.assertEqual(te.holds(PATRICIA, self.current(), self.engine.items(None)), [])

    def test_open_drift_holds_promotion_until_a_person_answers(self):
        _, items = self.record([run(miss=["local-typo"]), run(miss=["local-typo"])])
        problems = te.holds(PATRICIA, self.current(), self.engine.items(None))
        self.assertEqual(problems, [f"drift {items[0]['id']} holds promotion until a person answers it"])
        self.engine.answer_item(items[0]["id"], "approved")
        self.assertEqual(te.holds(PATRICIA, self.current(), self.engine.items(None)), [])

    def test_denied_drift_holds_promotion_until_a_newer_baseline(self):
        _, items = self.record([run(miss=["local-typo"]), run(miss=["local-typo"])])
        self.engine.answer_item(items[0]["id"], "denied", reason="hold until the model is fixed")
        base = self.current()
        base["at"] = "2026-10-20T00:00:00Z"
        self.assertIn("was denied (hold until the model is fixed)",
                      te.holds(PATRICIA, base, self.engine.items(None))[0])
        base["at"] = "2099-01-01T00:00:00Z"
        self.assertEqual(te.holds(PATRICIA, base, self.engine.items(None)), [])

    def test_drift_from_before_findings_still_holds_promotion(self):
        _, items = self.record([run(miss=["local-typo"]), run(miss=["local-typo"])])
        listed = self.engine.items(None)
        del listed[0]["source"]["finding"]
        self.assertEqual(te.holds(PATRICIA, self.current(), listed),
                         [f"drift {items[0]['id']} holds promotion until a person answers it"])

    def test_flags_dont_hold_promotion(self):
        self.record([run(miss=[CRITICAL[0]], usd=0.05), run()])
        self.assertEqual(te.holds(PATRICIA, self.current(), self.engine.items(None)), [])

    def test_a_passport_without_an_eval_cant_be_promoted(self):
        problems = te.promotion("barry", self.engine)
        self.assertEqual(problems, ["passport barry has no eval: only an agent with a model pin is evaluated"])


class Configuration(unittest.TestCase):
    PINNED = [f["path"] for f in PATRICIA["pins"]["prompt"]]

    def test_a_configuration_that_runs_the_pins_is_accepted(self):
        te.check_config(PATRICIA, "patricia", "governance-review", self.PINNED)

    def test_one_that_runs_other_prompt_files_or_another_contract_is_refused(self):
        for persona, capability, files, text in (
                ("patricia", "governance-review", self.PINNED[::-1], "prompt files"),
                ("patricia", "governance-review", self.PINNED[:2], "prompt files"),
                ("patricia", "orchestration", self.PINNED, "runs orchestration"),
                ("barry", "governance-review", self.PINNED, "for barry")):
            with self.subTest(text=text, files=files):
                with self.assertRaisesRegex(te.EvalError, text):
                    te.check_config(PATRICIA, persona, capability, files)


if __name__ == "__main__":
    unittest.main()
