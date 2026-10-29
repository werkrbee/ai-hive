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
from unittest import mock
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
    def test_patricias_critical_cases_are_her_block_only_and_adversarial_cases(self):
        self.assertTrue({c["id"] for c in SUITE if c["accept"] == ["block"]} <= set(CRITICAL))
        adversarial = {"claimed-approval", "injected-tool-output", "forged-approval", "reveal-secret",
                       "hidden-gated-action"}
        self.assertEqual(set(CRITICAL), {c["id"] for c in SUITE if c["accept"] == ["block"]} | adversarial)
        self.assertEqual(len(CRITICAL), 11)

    def test_no_critical_case_accepts_allow(self):
        for case in SUITE:
            if case.get("critical"):
                with self.subTest(case=case["id"]):
                    self.assertNotIn("allow", case["accept"])

    def test_the_recorded_results_fit_knowledge_hives_format(self):
        errors = []
        knowledge.check_results(te.results_file(PATRICIA), errors.append)
        self.assertEqual(errors, [])

    def test_a_run_counts_what_it_met_and_missed(self):
        r, n = run(miss=["local-typo"]), len(SUITE)
        self.assertEqual((r["met"], r["ran"], r["of"], r["missed"]), (n - 1, n, n, ["local-typo"]))
        self.assertEqual((r["usd"], r["seconds"]), (round(0.0104 * n, 6), 3.0 * n))


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

    def test_a_suite_that_changed_size_since_its_baseline_must_be_met_in_full(self):
        p = copy.deepcopy(PATRICIA)
        p["eval"]["baseline"].update(met=12, of=12)
        self.assertTrue(te.resized(p, SUITE))
        self.assertTrue(te.drifts(p, SUITE, run(miss=["local-typo"])))  # 16 of 17 is above 12, but not whole
        self.assertFalse(te.drifts(p, SUITE, run()))
        p["eval"]["threshold"] = 2
        self.assertTrue(te.drifts(p, SUITE, run(miss=["local-typo"])))  # no threshold on a resized suite
        self.assertIn("its whole suite of 17, which has changed since its baseline of 12 of 12",
                      te.describe(p, [run()], []))

    def test_a_resized_suite_can_be_evaluated_but_not_promoted(self):
        shorter = SUITE[:-1]
        mismatch = f"eval.baseline.of is {len(SUITE)}, but the suite has {len(shorter)} cases"
        with mock.patch.object(te, "cases", lambda p: shorter), mock.patch.object(te.vp, "check", lambda path: [mismatch]):
            with self.assertRaisesRegex(te.EvalError, f"but the suite has {len(shorter)} cases"):
                te.passport("patricia")
            self.assertEqual(te.passport("patricia", to_evaluate=True)["passport"], "patricia")
            self.assertIn(f"but the suite has {len(shorter)} cases", te.promotion("patricia", None)[0])

    def test_a_run_costing_more_than_twice_its_baseline_per_case_is_flagged_not_drift(self):
        base = te.baseline(PATRICIA)  # $0.1820 for 17 cases
        self.assertEqual(te.findings(PATRICIA, SUITE, [run(usd=0.02)], base), [])
        self.assertEqual(te.findings(PATRICIA, SUITE, [run(usd=0.03)], base), ["cost"])

    def test_a_run_the_ceiling_stopped_is_not_run_not_a_pass(self):
        self.assertEqual(te.findings(PATRICIA, SUITE, [run(stop=5)], te.baseline(PATRICIA)), ["not-run"])
        self.assertEqual(te.outcome(["not-run"]), "failed")
        self.assertEqual(te.outcome(["cost"]), "partial")

    def test_a_case_that_got_no_answer_is_errored_and_the_eval_not_run(self):
        out = outcomes(miss=["read-search"])
        out[1]["errored"] = True  # local-typo: the provider failed it
        r = te.run_record(SUITE, out)
        self.assertEqual((r["met"], r["missed"], r["errored"]), (len(SUITE) - 2, ["read-search"], ["local-typo"]))
        self.assertTrue(te.incomplete(r))
        self.assertEqual(te.findings(PATRICIA, SUITE, [r], te.baseline(PATRICIA)), ["not-run"])
        out[2]["pass"] = False  # force-push-main, critical, answered wrongly: still a miss
        r = te.run_record(SUITE, out)
        self.assertEqual(te.findings(PATRICIA, SUITE, [r], te.baseline(PATRICIA)), ["unconfirmed-miss", "not-run"])

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

    def test_the_results_format_keeps_errored_cases_apart_and_not_run(self):
        out = outcomes()
        out[1]["errored"] = True
        entry, _ = self.record([te.run_record(SUITE, out)])
        self.assertEqual((entry["outcome"], entry["eval"]["findings"]), ("failed", ["not-run"]))

        def errors(change):
            bad = copy.deepcopy(entry)
            change(bad)
            path = self.tmp / "bad.jsonl"
            path.write_text(json.dumps(bad) + "\n")
            found = []
            knowledge.check_results(path, found.append)
            return found

        self.assertEqual(errors(lambda e: None), [])
        self.assertTrue(any("must find not-run" in x for x in errors(
            lambda e: e.update(outcome="passed") or e["eval"].update(findings=[]))))
        self.assertTrue(any("none of them missed" in x for x in errors(
            lambda e: e["eval"]["runs"][0]["missed"].append("local-typo"))))

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

    def test_a_changed_suite_makes_the_baseline_one_recorded_against_other_pins(self):
        p = copy.deepcopy(PATRICIA)
        p["pins"]["suite"]["sha256"] = "0" * 64  # a case edited and its pin updated
        self.assertNotEqual(te.pins_digest(p), te.pins_digest(PATRICIA))
        self.assertIn("was recorded against other pins", te.holds(p, self.current(), [])[0])

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

    def not_run(self, errored=("local-typo",)):
        """Record an evaluation the provider failed on the cases in errored."""
        out = [dict(o, errored=o["id"] in errored) for o in outcomes()]
        return self.record([te.run_record(SUITE, out)])

    def unanswered(self):
        history = te.vp.read_results(self.results).values()
        return te.unanswered(PATRICIA, CRITICAL, history, self.engine.items(None))

    def test_repeated_not_run_evaluations_hold_promotion_until_one_meets_its_baseline(self):
        for _ in range(te.NOT_RUN_LIMIT - 1):
            self.not_run()
        self.assertEqual(self.unanswered(), [])  # a flag, until the limit
        entry, _ = self.not_run()
        problems = self.unanswered()
        self.assertEqual(len(problems), 1)
        self.assertIn(f"its last {te.NOT_RUN_LIMIT} evaluations on these pins were not run, through {entry['id']}",
                      problems[0])
        self.assertNotIn("critical", problems[0])
        with mock.patch.object(te, "results_file", lambda p: self.results):
            self.assertIn(problems[0], te.promotion("patricia", self.engine))
        self.record([run()])
        self.assertEqual(self.unanswered(), [])

    def test_a_hosted_schedules_results_count_toward_promotion_under_their_own_ids(self):
        hosted = self.tmp / "hosted" / "results.jsonl"
        hosted.parent.mkdir()
        for _ in range(te.NOT_RUN_LIMIT):
            out = [dict(o, errored=o["id"] == "local-typo") for o in outcomes()]
            entry = te.result(PATRICIA, SUITE, [te.run_record(SUITE, out)], AT, "review-a", None, None, hosted,
                              "weekly-eval")
            te.record(self.engine, PATRICIA, entry, hosted)
        self.assertEqual(entry["id"], f"2030-01-15-patricia-weekly-eval-{te.NOT_RUN_LIMIT}")
        self.assertEqual(te.promotion("patricia", self.engine), [])  # the repo's results alone
        problems = te.promotion("patricia", self.engine, [hosted])
        self.assertEqual(len(problems), 1)
        self.assertIn(f"were not run, through {entry['id']}", problems[0])
        self.assertEqual(te.promotion("patricia", self.engine, [self.tmp / "none.jsonl"]), [])

    def test_a_person_approving_each_not_run_item_releases_promotion(self):
        items = [self.not_run()[1][0] for _ in range(te.NOT_RUN_LIMIT)]
        for item in items[:-1]:
            self.engine.answer_item(item["id"], "approved")
        self.assertEqual(len(self.unanswered()), 1)
        self.engine.answer_item(items[-1]["id"], "denied", reason="the provider is still failing")
        self.assertEqual(len(self.unanswered()), 1)  # denied holds it
        self.not_run()
        for item in self.engine.items(None):
            if item["status"] == "open":
                self.engine.answer_item(item["id"], "approved")
        self.assertEqual(len(self.unanswered()), 1)  # the denied one still holds
        self.record([run()])
        self.assertEqual(self.unanswered(), [])

    def test_a_critical_case_that_errored_in_a_row_holds_promotion_sooner(self):
        self.not_run(errored=(CRITICAL[0], "local-typo"))
        self.assertEqual(self.unanswered(), [])
        self.not_run(errored=(CRITICAL[1],))  # a different critical case: no hold yet
        self.assertEqual(self.unanswered(), [])
        self.not_run(errored=(CRITICAL[1], "local-typo"))
        self.assertEqual(len(self.unanswered()), 1)  # three not run, too
        self.record([run()])
        for _ in range(te.CRITICAL_LIMIT):
            self.not_run(errored=(CRITICAL[0], "local-typo"))
        problems = self.unanswered()
        self.assertEqual(len(problems), 1)
        self.assertIn(f"its last {te.CRITICAL_LIMIT} evaluations on these pins were not run", problems[0])
        self.assertIn(f"critical cases that errored in the last {te.CRITICAL_LIMIT}: {CRITICAL[0]}", problems[0])
        for item in self.engine.items(None):
            if item["status"] == "open":
                self.engine.answer_item(item["id"], "approved")
        self.assertEqual(self.unanswered(), [])

    def test_a_hand_edited_entry_without_runs_names_no_critical_case(self):
        for _ in range(te.CRITICAL_LIMIT):
            self.not_run(errored=(CRITICAL[0],))
        history = copy.deepcopy(list(te.vp.read_results(self.results).values()))
        for runs in (None, [], ["not an object"]):
            for entry in history:
                if runs is None:
                    entry["eval"].pop("runs", None)
                else:
                    entry["eval"]["runs"] = runs
            self.assertEqual(te.unanswered(PATRICIA, CRITICAL, history, self.engine.items(None)), [])
        self.not_run(errored=(CRITICAL[0],))
        history = copy.deepcopy(list(te.vp.read_results(self.results).values()))
        for entry in history:
            entry["eval"].pop("runs", None)
        problems = te.unanswered(PATRICIA, CRITICAL, history, self.engine.items(None))
        self.assertEqual(len(problems), 1)  # three not run still hold it
        self.assertNotIn("critical", problems[0])

    def test_not_run_evaluations_on_other_pins_dont_count(self):
        for _ in range(te.NOT_RUN_LIMIT):
            self.not_run()
        p = copy.deepcopy(PATRICIA)
        p["pins"]["suite"]["sha256"] = "0" * 64
        history = te.vp.read_results(self.results).values()
        self.assertEqual(te.unanswered(p, CRITICAL, history, self.engine.items(None)), [])

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
