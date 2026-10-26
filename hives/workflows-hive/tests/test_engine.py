"""Tests for the engine as a library: open runs that grow, model turns, crashes, cancel,
the audit log, passports and actor IDs.

Run from the repo root: python3 -m unittest discover -s hives/workflows-hive/tests
"""
import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import run as engine  # noqa: E402

LINEUP = "hives/rules-hive/examples/lineup-etiquette/policy.json"


def calls(path):
    """The lines a stub model or worker appended to path, one per call."""
    return path.read_text().splitlines() if path.exists() else []


def logged(path, name):
    """A worker that appends its idempotency key to path, then echoes its input."""
    def worker(inp, key, _cap):
        with open(path, "a") as f:
            f.write(f"{name} {key}\n")
        return inp, {"usd": 0.001, "tokens": 10}
    return worker


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.log = self.tmp / "calls.txt"
        self.workers = dict(engine.WORKERS, echo=logged(self.log, "echo"))
        self.engine = self.make()

    def make(self):
        return engine.Engine(self.tmp / "runs", workers=self.workers, log=lambda *a: None)

    def model(self, reply, usd=0.01, tokens=100):
        """A stub model turn: records the call, returns reply."""
        def call(key):
            with open(self.log, "a") as f:
                f.write(f"model {key}\n")
            return reply, {"usd": usd, "tokens": tokens}
        return call


class OpenRuns(Base):
    def test_a_run_grows_step_by_step_and_finishes(self):
        e = self.engine
        words = self.tmp / "words.txt"
        words.write_text("one two three\n")
        run = e.open("loop", {"path": str(words)})
        e.append(run, {"id": "read", "worker": "read-text", "input": {"path": "${inputs.path}"}})
        run = e.execute(run)
        self.assertEqual(run["status"], "working")
        self.assertEqual(run["steps"]["read"]["status"], "completed")
        e.append(run, {"id": "count", "worker": "count-words", "input": {"text": "${steps.read.output}"}})
        run = e.execute(run)
        run = e.finish(run, run["steps"]["count"]["output"])
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["result"]["words"], 3)
        self.assertEqual(e.load(run["runId"])["plan"]["steps"][1]["id"], "count")

    def test_an_appended_step_is_decided_by_the_policy(self):
        e = self.engine
        run = e.open("loop")
        e.append(run, {"id": "push", "worker": "echo", "input": {}, "actions": [{"action": "vcs.push"}]})
        run = e.execute(run)
        self.assertEqual(run["status"], "input_required")
        self.assertEqual(run["pending"]["rules"], ["approve.vcs.push"])
        self.assertEqual(calls(self.log), [])
        run = e.approve(run["runId"], by="ci")
        self.assertEqual(run["status"], "working")
        self.assertEqual(len(calls(self.log)), 1)
        self.assertEqual(e.finish(run, "pushed")["status"], "completed")

    def test_a_prohibited_appended_step_fails_the_run_without_running(self):
        e = self.engine
        run = e.open("loop", policy=LINEUP)
        e.append(run, {"id": "send", "worker": "echo", "input": {}, "actions": [
            {"action": "message.send", "scope": {"channel": "sms", "audience": "group"},
             "facts": {"recipient.notifyOptIn": False}}]})
        run = e.execute(run)
        self.assertEqual(run["status"], "failed")
        self.assertIn("prohibited by messages.opt-in-only", run["error"]["message"])
        self.assertEqual(calls(self.log), [])

    def test_append_refuses_what_it_couldnt_run(self):
        e = self.engine
        run = e.open("loop")
        e.append(run, {"id": "a", "worker": "echo", "input": {}})
        cases = [
            ({"id": "a", "worker": "echo", "input": {}}, "already has a step"),
            ({"id": "b", "worker": "nope", "input": {}}, "unknown worker"),
            ({"id": "b", "worker": "echo"}, "needs an id, a worker and an input"),
            ({"id": "b", "worker": "echo", "input": {}, "budget": {"usd": -1}}, "budget usd"),
            ({"id": "b", "worker": "echo", "input": {}, "actions": [{"action": "lineup.event.cancel"}]},
             "isn't in"),
        ]
        for step, message in cases:
            with self.subTest(message), self.assertRaisesRegex(engine.EngineError, message):
                e.append(run, step)
        self.assertEqual(list(e.load(run["runId"])["steps"]), ["a"])

    def test_only_a_working_open_run_grows(self):
        e = self.engine
        words = self.tmp / "words.txt"
        words.write_text("a b\n")
        planned = e.start("word-count", {"path": str(words)})
        with self.assertRaisesRegex(engine.EngineError, "only an open run"):
            e.append(planned, {"id": "x", "worker": "echo", "input": {}})
        run = e.open("loop")
        e.append(run, {"id": "gate", "worker": "echo", "input": {}, "approval": True})
        run = e.execute(run)
        with self.assertRaisesRegex(engine.EngineError, "input_required"):
            e.append(run, {"id": "next", "worker": "echo", "input": {}})

    def test_an_ended_run_never_executes_again(self):
        e = self.engine
        cancelled = e.open("loop")
        e.append(cancelled, {"id": "s1", "worker": "echo", "input": {}})
        e.cancel(cancelled["runId"], by="ci")
        cancelled = e.execute(cancelled)
        denied = e.execute(e.append(e.open("loop"), {"id": "gate", "worker": "echo", "input": {}, "approval": True}))
        denied = e.deny(denied["runId"], "no", by="ci")

        def broken(_inp, _key, _cap):
            raise RuntimeError("boom")
        e.workers["broken"] = broken
        failed = e.execute(e.append(e.open("loop"), {"id": "s1", "worker": "broken", "input": {}}))
        for run, status in ((cancelled, "cancelled"), (denied, "failed"), (failed, "failed")):
            with self.subTest(status):
                self.assertEqual(run["status"], status)
                with self.assertRaisesRegex(engine.EngineError, "only a working run"):
                    e.execute(run)
        self.assertEqual(calls(self.log), [])
        self.assertEqual(e.load(denied["runId"])["status"], "failed")

    def test_append_keeps_the_step_as_it_was_checked(self):
        e = self.engine
        run = e.open("loop")
        step = {"id": "push", "worker": "echo", "input": {}, "actions": [{"action": "vcs.push"}]}
        e.append(run, step)
        del step["actions"]
        self.assertEqual(e.execute(run)["status"], "input_required")
        self.assertEqual(calls(self.log), [])

    def test_finish_waits_for_every_step(self):
        e = self.engine
        run = e.open("loop")
        e.append(run, {"id": "a", "worker": "echo", "input": {}})
        with self.assertRaisesRegex(engine.EngineError, "haven't completed: a"):
            e.finish(run, None)


class Turns(Base):
    def test_a_completed_turn_is_never_called_again(self):
        e = self.engine
        run = e.open("loop")
        first = e.turn(run, "t1", self.model("hello"))
        again = e.turn(e.load(run["runId"]), "t1", self.model("something else"))
        self.assertEqual((first, again), ("hello", "hello"))
        self.assertEqual(len(calls(self.log)), 1)
        self.assertEqual(e.load(run["runId"])["cost"], {"usd": 0.01, "tokens": 100})

    def test_a_turn_that_raises_fails_the_run(self):
        e = self.engine
        run = e.open("loop")

        def broken(_key):
            raise RuntimeError("model unavailable")
        with self.assertRaises(engine.Stopped) as stopped:
            e.turn(run, "t1", broken)
        self.assertEqual(stopped.exception.run["status"], "failed")
        self.assertEqual(e.load(run["runId"])["error"]["turn"], "t1")
        with self.assertRaises(engine.Stopped):
            e.turn(run, "t2", self.model("late"))

    def test_turns_and_steps_add_to_the_run_cost(self):
        e = self.engine
        run = e.open("loop")
        e.turn(run, "t1", self.model("go", usd=0.02, tokens=200))
        e.append(run, {"id": "s1", "worker": "echo", "input": {}})
        run = e.execute(run)
        self.assertEqual(run["cost"], {"usd": 0.021, "tokens": 210})


LOOP = textwrap.dedent("""
    import os, sys
    sys.path.insert(0, {scripts!r})
    import run as engine
    log, state, crash = {log!r}, {state!r}, {crash!r}

    def note(line):
        with open(log, "a") as f:
            f.write(line + "\\n")

    def model(reply):
        def call(key):
            note("model " + key)
            if crash == "turn" and reply == "second":
                os._exit(75)  # dies mid-turn, before its reply is recorded
            return reply, {{"usd": 0.01, "tokens": 100}}
        return call

    def echo(inp, key, _cap):
        note("echo " + key)
        if crash == "step":
            os._exit(75)  # dies mid-step, after its effect, before its checkpoint
        return inp, {{"usd": 0.0, "tokens": 0}}

    e = engine.Engine(state, workers=dict(engine.WORKERS, echo=echo), log=lambda *a: None)
    run = e.open("loop")
    print(run["runId"], flush=True)
    e.turn(run, "t1", model("first"))
    e.append(run, {{"id": "s1", "worker": "echo", "input": {{}}}})
    run = e.execute(run)
    e.turn(run, "t2", model("second"))
""")


def recorded(test, run_id, key):
    return json.loads((test.tmp / "runs" / f"{run_id}.json").read_text())[key]


class Crashes(Base):
    def crash(self, where):
        script = LOOP.format(scripts=str(SCRIPTS), log=str(self.log), state=str(self.tmp / "runs"), crash=where)
        out = subprocess.run([sys.executable, "-B", "-c", script], capture_output=True, text=True)
        self.assertEqual(out.returncode, 75, out.stderr)
        return out.stdout.split()[0]

    def replay(self, run_id):
        """The loop again after the crash: the same turns and steps, from the record."""
        e = self.make()
        run = e.resume(run_id)
        e.turn(run, "t1", self.model("first"))
        if "s1" not in run["steps"]:
            e.append(run, {"id": "s1", "worker": "echo", "input": {}})
        run = e.execute(run)
        e.turn(run, "t2", self.model("second"))
        return e.finish(run, "done")

    def test_resume_after_a_crash_mid_turn_repeats_only_that_turn(self):
        run_id = self.crash("turn")
        before = calls(self.log)
        self.assertEqual(recorded(self, run_id, "turns")["t2"]["status"], "working")
        run = self.replay(run_id)
        after = calls(self.log)[len(before):]
        self.assertEqual(run["status"], "completed")
        self.assertEqual([c.split()[0] for c in before], ["model", "echo", "model"])
        self.assertEqual(after, [f"model {run_id}:turn:t2"])  # t1 and s1 aren't repeated
        self.assertEqual(run["cost"], {"usd": 0.02, "tokens": 200})  # t1 once, t2 once

    def test_resume_after_a_crash_mid_step_runs_it_again_with_the_same_key(self):
        run_id = self.crash("step")
        self.assertEqual(recorded(self, run_id, "steps")["s1"]["status"], "working")
        run = self.replay(run_id)
        echoes = [c for c in calls(self.log) if c.startswith("echo")]
        models = [c for c in calls(self.log) if c.startswith("model")]
        self.assertEqual(run["status"], "completed")
        self.assertEqual(echoes, [f"echo {run_id}:s1"] * 2)
        self.assertEqual(models, [f"model {run_id}:turn:t1", f"model {run_id}:turn:t2"])
        self.assertEqual(run["cost"], {"usd": 0.021, "tokens": 210})  # t1, s1's second run, t2


class Cancel(Base):
    def test_a_paused_run_is_cancelled_at_once(self):
        e = self.engine
        words = self.tmp / "words.txt"
        words.write_text("a b\n")
        run = e.start("approved-word-count", {"path": str(words)})
        self.assertEqual(run["status"], "input_required")
        run = e.cancel(run["runId"], by="ci")
        self.assertEqual(run["status"], "cancelled")
        self.assertEqual(run["error"]["message"], "cancelled by ci")
        self.assertIsNone(run["pending"])
        with self.assertRaisesRegex(engine.EngineError, "isn't waiting for an answer"):
            e.approve(run["runId"])

    def test_a_working_run_stops_before_its_next_step_or_turn(self):
        e = self.engine
        run = e.open("loop")
        e.turn(run, "t1", self.model("go"))
        e.append(run, {"id": "s1", "worker": "echo", "input": {}})
        self.assertEqual(e.cancel(run["runId"], by="ci")["status"], "working")
        run = e.execute(run)
        self.assertEqual(run["status"], "cancelled")
        self.assertEqual(run["error"], {"step": "s1", "message": "cancelled by ci"})
        self.assertEqual(calls(self.log), [f"model {run['runId']}:turn:t1"])
        with self.assertRaises(engine.Stopped):
            e.turn(run, "t2", self.model("late"))

    def test_a_cancel_requested_while_no_process_runs_it_holds_on_resume(self):
        e = self.engine
        run = e.open("loop")
        e.cancel(run["runId"], by="ci")
        run = self.make().resume(run["runId"])
        self.assertEqual(run["status"], "cancelled")
        self.assertFalse(e.cancel_path(run["runId"]).exists())

    def test_a_cancel_during_the_last_step_ends_with_the_run(self):
        words = self.tmp / "words.txt"
        words.write_text("a b\n")
        def cancelling(inp, key, cap):
            self.make().cancel(key.split(":")[0], by="ci")
            return engine.count_words(inp, key, cap)
        self.workers["count-words"] = cancelling
        e = self.make()
        run = e.start("word-count", {"path": str(words)})
        self.assertEqual(run["status"], "completed")  # cooperative: the run had nothing left to stop
        self.assertFalse(e.cancel_path(run["runId"]).exists())
        run = e.open("loop")
        e.append(run, {"id": "s1", "worker": "count-words", "input": {"text": "a"}})
        run = e.finish(e.execute(run), "done")
        self.assertEqual(run["status"], "cancelled")
        self.assertFalse(e.cancel_path(run["runId"]).exists())

    def test_a_finished_run_cant_be_cancelled(self):
        e = self.engine
        run = e.finish(e.open("loop"), "done")
        with self.assertRaisesRegex(engine.EngineError, "already completed"):
            e.cancel(run["runId"])


def entries(test):
    """The audit log's entries, after checking its chain against the run records."""
    log = test.tmp / "audit.jsonl"
    test.assertEqual(engine.check_audit.check(log, test.tmp / "runs"), [])
    return [json.loads(line) for line in log.read_text().splitlines()]


def kinds(test, run_id):
    return [(e["kind"], e.get("step") or e.get("turn"), e.get("decision"))
            for e in entries(test) if e["runId"] == run_id]


class Audit(Base):
    def test_every_decision_of_a_planned_run_is_logged_and_the_record_anchors_the_last(self):
        words = self.tmp / "words.txt"
        words.write_text("a b\n")
        run = self.engine.start("word-count", {"path": str(words)})
        self.assertEqual(kinds(self, run["runId"]), [
            ("run.started", None, None),
            ("step.decided", "read", "allowed"), ("step.ran", "read", None),
            ("step.decided", "count", "allowed"), ("step.ran", "count", None),
            ("run.completed", None, None)])
        last = entries(self)[-1]
        self.assertEqual(run["audit"], {"seq": last["seq"], "hash": last["hash"]})
        self.assertEqual(entries(self)[0]["prev"], "sha256:" + "0" * 64)

    def test_a_gated_action_is_logged_paused_then_answered_and_not_decided_again(self):
        e = self.engine
        run = e.execute(e.append(e.open("loop"), {"id": "push", "worker": "echo", "input": {"branch": "x"},
                                                   "actions": [{"action": "vcs.push"}]}))
        run = e.approve(run["runId"], by="ci")
        self.assertEqual(kinds(self, run["runId"]), [
            ("run.started", None, None), ("step.decided", "push", "paused"),
            ("approval.answered", "push", "approved"), ("step.ran", "push", None)])
        decided = next(x for x in entries(self) if x["kind"] == "step.decided")
        self.assertEqual((decided["action"], decided["rules"]), ("vcs.push", ["approve.vcs.push"]))
        self.assertRegex(decided["call"], r"^sha256:[0-9a-f]{64}$")
        self.assertNotIn("branch", json.dumps(decided))  # the call's arguments stay in the record
        self.assertEqual(next(x for x in entries(self) if x["kind"] == "approval.answered")["by"], "ci")

    def test_a_denial_a_cancel_a_failed_turn_and_a_budget_refusal_are_logged(self):
        e = self.engine
        denied = e.execute(e.append(e.open("loop"), {"id": "gate", "worker": "echo", "input": {}, "approval": True}))
        e.deny(denied["runId"], "not now", by="ci")
        cancelled = e.open("loop")
        e.cancel(cancelled["runId"], by="ci")
        e.resume(cancelled["runId"])
        failed = e.open("loop")

        def broken(_key):
            raise RuntimeError("model unavailable")
        with self.assertRaises(engine.Stopped):
            e.turn(failed, "t1", broken)
        costly = e.execute(e.append(e.open("loop"), {"id": "big", "worker": "echo", "input": {},
                                                      "budget": {"tokens": 5}}))
        self.assertEqual(kinds(self, denied["runId"])[1:], [
            ("step.decided", "gate", "paused"), ("approval.answered", "gate", "denied"), ("run.failed", None, None)])
        self.assertEqual(kinds(self, cancelled["runId"])[1:], [("run.cancelled", None, None)])
        self.assertEqual(kinds(self, failed["runId"])[1:], [("turn.failed", "t1", None), ("run.failed", None, None)])
        self.assertEqual(kinds(self, costly["runId"])[2:], [("budget.refused", "big", None), ("run.failed", None, None)])
        self.assertNotIn("not now", (self.tmp / "audit.jsonl").read_text())  # a denial's reason stays in the record

    def test_a_turn_and_a_finish_are_logged(self):
        e = self.engine
        run = e.open("loop")
        e.turn(run, "t1", self.model("hi"))
        e.turn(e.load(run["runId"]), "t1", self.model("hi"))  # replayed from the record, not logged again
        e.finish(run, "done")
        self.assertEqual(kinds(self, run["runId"]), [
            ("run.started", None, None), ("turn.completed", "t1", None), ("run.completed", None, None)])

    def test_a_log_that_cant_be_written_stops_the_run(self):
        log = self.tmp / "audit.jsonl"
        log.write_text('{"seq": 1, "cut off')
        with self.assertRaisesRegex(engine.EngineError, "last line is incomplete"):
            self.engine.open("loop")
        self.assertEqual(list((self.tmp / "runs").glob("*.json")), [])


class Passports(Base):
    def test_a_never_action_is_prohibited_before_any_mandate(self):
        e = self.engine
        run = e.open("review", passport="patricia")
        e.append(run, {"id": "edit", "worker": "echo", "input": {}, "actions": [{"action": "fs.write"}]})
        run = e.execute(run)  # the Charter lets fs.write run on its own; Patricia's passport doesn't
        self.assertEqual(run["status"], "failed")
        self.assertIn("fs.write is prohibited by passport.patricia.never.fs.write", run["error"]["message"])
        self.assertEqual(calls(self.log), [])
        decided = next(x for x in entries(self) if x["kind"] == "step.decided")
        self.assertEqual(decided["rules"], ["passport.patricia.never.fs.write"])

    def test_each_entry_names_the_passport_its_run_is_under(self):
        e = self.engine
        passport, sha = engine.load_passport("barry")
        run = e.execute(e.append(e.open("loop", passport="barry"), {"id": "s1", "worker": "echo", "input": {}}))
        self.assertEqual(run["agent"], {"passport": "barry", "version": passport["version"], "sha256": sha})
        self.assertTrue(all(x["agent"] == run["agent"] for x in entries(self)))

    def test_a_run_without_a_passport_names_no_agent(self):
        run = self.engine.open("loop")
        self.assertIsNone(run["agent"])
        self.assertNotIn("agent", entries(self)[0])

    def test_an_unknown_or_malformed_passport_is_refused(self):
        for name, message in (("nobody", "no passport for 'nobody'"), ("../barry", "kebab-case")):
            with self.subTest(name), self.assertRaisesRegex(engine.EngineError, message):
                self.engine.open("loop", passport=name)

    def test_a_run_keeps_the_passport_it_started_under(self):
        passports = self.tmp / "passports"
        shutil.copytree(engine.PASSPORTS_DIR, passports)
        e = engine.Engine(self.tmp / "runs", workers=self.workers, log=lambda *a: None, passports_dir=passports)
        run = e.append(e.open("loop", passport="barry"), {"id": "s1", "worker": "echo", "input": {}})
        path = passports / "barry" / "passport.json"
        changed = json.loads(path.read_text())
        changed["version"] += 1
        changed["budget"]["usd"] = 0.01
        path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(engine.EngineError, "has changed since"):
            e.execute(run)
        self.assertEqual(calls(self.log), [])


class Actors(Base):
    def paused(self):
        e = self.engine
        return e.execute(e.append(e.open("loop"), {"id": "gate", "worker": "echo", "input": {}, "approval": True}))

    def test_an_answer_or_cancel_without_an_actor_id_is_refused(self):
        run = self.paused()
        for act in (lambda: self.engine.approve(run["runId"]), lambda: self.engine.cancel(run["runId"])):
            with self.assertRaisesRegex(engine.EngineError, "needs an actor ID"):
                act()
        self.assertEqual(self.engine.load(run["runId"])["status"], "input_required")

    def test_a_name_or_email_is_not_an_actor_id(self):
        run = self.paused()
        for by in ("Jane Doe", "jane@example.com"):
            with self.subTest(by), self.assertRaisesRegex(engine.EngineError, "isn't an actor ID"):
                self.engine.approve(run["runId"], by=by)

    def test_the_configured_actor_answers_when_no_one_else_is_named(self):
        run = self.paused()
        e = engine.Engine(self.tmp / "runs", workers=self.workers, log=lambda *a: None, actor="usr_7f3a")
        run = e.approve(run["runId"])
        self.assertEqual(run["steps"]["gate"]["approval"]["by"], "usr_7f3a")


if __name__ == "__main__":
    unittest.main()
