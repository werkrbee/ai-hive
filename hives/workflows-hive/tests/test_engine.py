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

    def test_an_open_run_can_be_named_once(self):
        e = self.engine
        run = e.open("loop", run_id="9f1c2d3e-task")
        self.assertEqual(run["runId"], "9f1c2d3e-task")
        self.assertEqual(e.load("9f1c2d3e-task")["status"], "working")
        e.append(run, {"id": "a", "worker": "echo", "input": {}})
        self.assertEqual(e.load("9f1c2d3e-task")["steps"]["a"]["idempotencyKey"], "9f1c2d3e-task:a")
        with self.assertRaisesRegex(engine.EngineError, "already exists"):
            e.open("loop", run_id="9f1c2d3e-task")
        for bad in ("../escape", "", "a b", 7):
            with self.subTest(bad), self.assertRaisesRegex(engine.EngineError, "a run ID is"):
                e.open("loop", run_id=bad)

    def test_a_literal_step_takes_its_input_and_actions_as_they_are(self):
        e = self.engine
        run = e.open("loop", {"secret": "from the inputs"})
        # As references, these would read the run's inputs, or fail on a step that doesn't exist.
        text = "${inputs.secret} and ${steps.missing.output}"
        e.append(run, {"id": "a", "worker": "echo", "literal": True, "input": {"text": text},
                       "actions": [{"action": "fs.read", "scope": {"path": "${steps.missing.output}"}}]})
        run = e.execute(run)
        self.assertEqual(run["status"], "working")
        self.assertEqual(run["steps"]["a"]["output"], {"text": text})
        e.append(run, {"id": "b", "worker": "echo", "input": {"text": text}})
        self.assertEqual(e.execute(run)["status"], "failed", "without literal, the references resolve")
        with self.assertRaisesRegex(engine.EngineError, "literal must be true or false"):
            e.append(e.open("loop"), {"id": "b", "worker": "echo", "input": {}, "literal": "yes"})


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


class Delegation(Base):
    def passports(self, **barry):
        """An engine whose passports are copies, with Barry's fields changed by barry."""
        passports = self.tmp / "passports"
        shutil.copytree(engine.PASSPORTS_DIR, passports)
        path = passports / "barry" / "passport.json"
        path.write_text(json.dumps(dict(json.loads(path.read_text()), **barry)))
        return engine.Engine(self.tmp / "runs", workers=self.workers, log=lambda *a: None, passports_dir=passports)

    def test_a_delegate_runs_under_the_stricter_of_both_passports(self):
        e = self.engine
        run = e.open("loop", passport="barry")
        child = e.delegate(run, "map", "explore", ["Find where approvals are answered."])
        self.assertEqual((child["status"], child["agent"]["passport"]), ("working", "explore"))
        self.assertEqual(child["parent"], {"runId": run["runId"], "step": "map"})
        self.assertEqual(child["inputs"], {"context": ["Find where approvals are answered."]})
        self.assertEqual(child["grant"]["granted"], ["fs.read"])
        self.assertIn("fs.write", child["grant"]["never"])  # Barry may write; explore may not
        e.append(child, {"id": "read", "worker": "echo", "input": {}, "actions": [{"action": "fs.read"}]})
        e.append(child, {"id": "edit", "worker": "echo", "input": {}, "actions": [{"action": "fs.write"}]})
        child = e.execute(child)
        self.assertEqual(child["steps"]["read"]["status"], "completed")
        self.assertEqual(child["status"], "failed")
        self.assertIn("fs.write is prohibited by grant.explore.never.fs.write", child["error"]["message"])

    def test_each_action_takes_the_stricter_treatment_and_one_either_leaves_out_is_denied(self):
        outer = {"granted": ["fs.read", "fs.write", "shell.exec"], "approval": ["vcs.push", "message.send"],
                 "never": ["infra.change"]}
        inner = {"granted": ["fs.read", "fs.write", "vcs.push", "net.fetch"], "approval": ["shell.exec"],
                 "never": ["message.send"]}
        grant = engine.narrow(outer, inner)
        self.assertEqual(grant, {"granted": ["fs.read", "fs.write"], "approval": ["shell.exec", "vcs.push"],
                                 "never": ["infra.change", "message.send"]})
        policy = engine.under_grant(engine.load_policy(engine.CHARTER_POLICY), grant, "helper")
        run = {"inputs": {}, "steps": {}}
        for action, decision, rule in (("fs.write", "auto", "auto.fs.write"),
                                       ("shell.exec", "human", "grant.helper.approval"),  # the Charter auto-allows it
                                       ("net.fetch", "deny", "grant.helper.omits.net.fetch"),
                                       ("message.send", "deny", "grant.helper.never.message.send")):
            with self.subTest(action):
                [(_, got, by, _)] = engine.verdict(policy, {"id": "s", "actions": [{"action": action}]}, run)
                self.assertEqual((got, by), (decision, rule))

    def test_a_delegation_the_grant_gates_waits_for_a_person_then_starts_its_delegate(self):
        e = self.engine
        run = e.open("loop", passport="barry")
        run["grant"] = {"granted": ["fs.read"], "approval": ["agent.delegate"], "never": []}  # as a delegate's would be
        e.save(run)
        self.assertIsNone(e.delegate(run, "map", "explore", ["Find it."]))
        run = e.load(run["runId"])
        self.assertEqual((run["status"], run["pending"]["rules"]), ("input_required", ["grant.barry.approval"]))
        self.assertFalse(any(x["kind"] == "delegation" for x in entries(self)))
        run = e.approve(run["runId"], by="ci")
        child = e.delegate(run, "map", "explore", ["Find it."])
        self.assertEqual(child["agent"]["passport"], "explore")
        self.assertEqual(child["grant"], {"granted": ["fs.read"], "approval": [], "never": sorted(
            engine.load_passport("explore")[0]["permissions"]["never"])})

    def test_a_delegate_the_passport_doesnt_list_is_refused(self):
        e = self.passports(delegates=["patricia"])
        run = e.open("loop", passport="barry")
        with self.assertRaisesRegex(engine.Stopped, "prohibited by delegate.unlisted"):
            e.delegate(run, "map", "explore", [])
        decided = [x for x in entries(self) if x["kind"] == "step.decided"]
        self.assertEqual((decided[-1]["decision"], decided[-1]["rules"]), ("denied", ["delegate.unlisted"]))
        self.assertFalse(any(x["kind"] == "delegation" for x in entries(self)))
        self.assertEqual(len(list((self.tmp / "runs").glob("*.json"))), 1)  # no delegate's run

    def test_a_step_cant_claim_its_delegate_is_listed_or_start_one(self):
        e = self.passports(delegates=["patricia"])
        run = e.open("loop", passport="barry")
        with self.assertRaisesRegex(engine.EngineError, "only Engine.delegate"):
            e.append(run, {"id": "d", "worker": "delegate", "input": {"passport": "explore", "context": []}})
        e.append(run, {"id": "d", "worker": "echo", "input": {}, "actions": [{
            "action": "agent.delegate", "scope": {"passport": "explore"},
            "facts": {"delegate.listed": True, "context.whole": False}}]})
        run = e.execute(run)
        self.assertEqual(run["status"], "failed")
        self.assertIn("prohibited by delegate.unlisted", run["error"]["message"])

    def test_the_whole_context_is_never_passed_and_a_clone_stays_in_its_run(self):
        e = self.engine
        run = e.open("loop", passport="barry")
        with self.assertRaisesRegex(engine.EngineError, "a clone runs as its parent, inside this run"):
            e.delegate(run, "fork", "barry", [], whole_context=True)
        with self.assertRaisesRegex(engine.Stopped, "prohibited by delegate.whole-context"):
            e.delegate(run, "map", "explore", [], whole_context=True)

    def test_only_a_run_under_a_passport_its_own_may_delegate(self):
        with self.assertRaisesRegex(engine.EngineError, "runs under no passport"):
            self.engine.delegate(self.engine.open("loop"), "map", "explore", [])
        run = self.engine.open("review", passport="patricia")  # her passport puts agent.delegate under never
        with self.assertRaisesRegex(engine.Stopped, "prohibited by passport.patricia.never.agent.delegate"):
            self.engine.delegate(run, "map", "explore", [])

    def test_a_delegation_is_logged_with_both_passports_the_grant_and_each_item_passed(self):
        e = self.engine
        run = e.open("loop", passport="barry")
        context = ["Find where approvals are answered.", {"path": "hives/workflows-hive"}]
        child = e.delegate(run, "map", "explore", context)
        [entry] = [x for x in entries(self) if x["kind"] == "delegation"]
        self.assertEqual((entry["runId"], entry["step"], entry["agent"]), (run["runId"], "map", run["agent"]))
        self.assertEqual(entry["delegate"], child["agent"])
        self.assertEqual(entry["grant"], engine.check_audit.digest(child["grant"]))
        self.assertEqual(entry["context"], [engine.check_audit.digest(c) for c in context])
        self.assertNotIn("approvals are answered", (self.tmp / "audit.jsonl").read_text())
        self.assertEqual(engine.check_audit.check(self.tmp / "audit.jsonl"), [])
        again = e.delegate(e.load(run["runId"]), "map", "explore", context)  # asked again: the same delegate
        self.assertEqual(again["runId"], child["runId"])
        self.assertEqual(len([x for x in entries(self) if x["kind"] == "delegation"]), 1)

    def test_a_delegates_budget_is_carved_out_of_what_its_delegator_has_left(self):
        e = self.passports(budget={"usd": 0.6, "tokens": 300000, "seconds": 3600})
        run = e.open("loop", passport="barry")
        e.turn(run, "plan", self.model("plan", usd=0.2))
        first = e.delegate(run, "map", "explore", [])
        self.assertEqual(first["budget"], {"usd": 0.4, "tokens": 200000, "seconds": 600})
        with self.assertRaisesRegex(engine.Stopped, "nothing is left of run .*'s usd to delegate"):
            e.delegate(run, "review", "code-review", [])  # the first holds the rest in reserve
        self.assertEqual(e.load(run["runId"])["steps"]["review"]["status"], "failed")

    def test_an_ended_delegate_counts_what_it_spent_and_frees_the_rest(self):
        e = self.passports(budget={"usd": 0.6, "tokens": 300000, "seconds": 3600})
        run = e.open("loop", passport="barry")
        e.turn(run, "plan", self.model("plan", usd=0.2))
        first = e.delegate(run, "map", "explore", [])
        e.turn(first, "look", self.model("found it", usd=0.1))
        e.finish(first, "found it")
        second = e.delegate(e.load(run["runId"]), "review", "code-review", [])
        self.assertEqual(second["budget"]["usd"], 0.3)

    def test_a_delegate_stops_at_the_budget_it_was_delegated(self):
        e = self.engine
        child = e.delegate(e.open("loop", passport="barry"), "map", "explore", [])
        with self.assertRaisesRegex(engine.Stopped, r"over its budget of 0.5 \(the budget it was delegated\)"):
            e.turn(child, "look", self.model("found it", usd=0.6))
        refused = [x for x in entries(self) if x["kind"] == "budget.refused"]
        self.assertEqual((refused[-1]["runId"], refused[-1]["turn"]), (child["runId"], "look"))
        self.assertEqual(e.load(child["runId"])["status"], "failed")


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


class Rollback(Base):
    """A plan whose read takes no effect, whose write and publish do, each with a compensate
    step, and whose send pauses for a person under the Charter, as does its compensation."""

    STEPS = [
        {"id": "read", "worker": "echo", "input": {"path": "${inputs.path}"}, "actions": [{"action": "fs.read"}]},
        {"id": "count", "worker": "echo", "input": {"of": "${steps.read.output.path}"}},
        {"id": "write", "worker": "echo", "input": {"file": "out.txt"}, "actions": [{"action": "fs.write"}],
         "compensate": {"worker": "echo", "input": {"remove": "${steps.write.output.file}"},
                        "actions": [{"action": "fs.write"}]}},
        {"id": "publish", "worker": "echo", "input": {"page": "p1"}, "actions": [{"action": "fs.write"}],
         "compensate": {"worker": "echo", "input": {"unpublish": "${steps.publish.output.page}"},
                        "actions": [{"action": "fs.write"}]}},
    ]
    SEND = {"id": "send", "worker": "echo", "input": {"to": 14}, "actions": [{"action": "message.send"}],
            "compensate": {"worker": "echo", "input": {"correct": "${steps.send.output.to}"},
                           "actions": [{"action": "message.send"}]}}

    def make(self):
        return engine.Engine(self.tmp / "runs", workflows_dir=self.tmp / "workflows", workers=self.workers,
                             log=lambda *a: None, actor="usr_7f3a")

    def plan(self, steps, name="effects"):
        path = self.tmp / "workflows" / name / "workflow.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"name": name, "version": 1, "inputs": {"required": ["path"]},
                                    "steps": steps, "output": "${steps.%s.output}" % steps[-1]["id"]}))
        return name

    def completed(self, steps=None):
        run = self.engine.start(self.plan(steps or self.STEPS), {"path": "README.md"})
        self.assertEqual(run["status"], "completed")
        open(self.log, "w").close()
        return run

    def test_effects_are_compensated_newest_first_then_later_steps_are_marked_and_the_run_waits(self):
        run = self.completed()
        rid = run["runId"]
        run = self.engine.rollback(rid, "read", reason="wrote to the wrong page")
        self.assertEqual(calls(self.log), [f"echo {rid}:compensate-publish-1", f"echo {rid}:compensate-write-1"])
        self.assertEqual((run["status"], run["next"], run["rollback"]), ("working", "count", None))
        for sid in ("count", "write", "publish"):
            self.assertEqual(run["steps"][sid]["status"], "rolledBack")
            self.assertEqual(run["steps"][sid]["undone"]["status"], "completed")
        self.assertEqual(run["steps"]["read"]["status"], "completed")
        record = run["rollbacks"][0]
        self.assertEqual((record["to"], record["by"], record["reason"], record["status"]),
                         ("read", "usr_7f3a", "wrote to the wrong page", "completed"))
        self.assertEqual(record["result"], {"page": "p1"})
        self.assertEqual(record["compensate"], [["publish", "compensate-publish-1"], ["write", "compensate-write-1"]])
        self.assertEqual(run["steps"]["compensate-write-1"]["output"], {"remove": "out.txt"})
        entry = [e for e in entries(self) if e["kind"] == "rollback"][0]
        self.assertEqual((entry["runId"], entry["step"], entry["by"], entry["via"], entry["record"]),
                         (rid, "read", "usr_7f3a", "cli", record["id"]))
        self.assertNotIn("wrong page", (self.tmp / "audit.jsonl").read_text())
        self.assertEqual(engine.check_audit.digest({k: v for k, v in record.items() if k not in ("id", "endedAt")}),
                         record["id"])

        cost = run["cost"]["tokens"]
        run = self.engine.resume(rid)  # each later step runs again, as a new attempt
        self.assertEqual(run["status"], "completed")
        self.assertEqual(calls(self.log)[2:], [f"echo {rid}:count:2", f"echo {rid}:write:2", f"echo {rid}:publish:2"])
        self.assertEqual(run["steps"]["write"]["attempt"], 2)
        self.assertEqual(run["steps"]["write"]["history"][0]["status"], "rolledBack")
        self.assertEqual(run["cost"]["tokens"], cost + 30)  # what was spent stays spent

    def test_a_step_with_no_effect_is_only_marked(self):
        run = self.completed(self.STEPS[:2])
        run = self.engine.rollback(run["runId"], "read", reason="recount")
        self.assertEqual(calls(self.log), [])
        self.assertEqual((run["steps"]["count"]["status"], run["next"]), ("rolledBack", "count"))

    def test_a_step_that_failed_before_its_worker_started_isnt_compensated(self):
        steps = [dict(s) for s in self.STEPS]
        steps[3]["input"] = {"page": "${steps.write.output.missing}"}
        run = self.engine.start(self.plan(steps), {"path": "README.md"})
        self.assertEqual((run["status"], run["error"]["step"]), ("failed", "publish"))
        open(self.log, "w").close()
        run = self.engine.rollback(run["runId"], "read", reason="fix the page reference")
        self.assertEqual(calls(self.log), [f"echo {run['runId']}:compensate-write-1"])
        self.assertEqual(run["steps"]["publish"]["undone"]["status"], "failed")
        self.assertEqual(run["rollbacks"][0]["status"], "failed")

    def test_rolling_back_past_an_effect_without_a_compensate_step_is_refused(self):
        steps = [dict(s) for s in self.STEPS]
        del steps[2]["compensate"]
        run = self.completed(steps)
        with self.assertRaisesRegex(engine.EngineError, "can't be rolled back past write: it takes an action "
                                    "with an effect outside the system"):
            self.engine.rollback(run["runId"], "read", reason="undo")
        self.assertEqual(self.engine.load(run["runId"])["status"], "completed")
        self.engine.rollback(run["runId"], "write", reason="republish")  # publish has one

    def test_a_compensating_step_is_decided_by_the_policy_like_any_other(self):
        run = self.engine.start(self.plan(self.STEPS[:1] + [self.SEND]), {"path": "README.md"})
        run = self.engine.approve(run["runId"], item_id=run["pending"]["id"])
        self.assertEqual(run["status"], "completed")
        rid = run["runId"]
        run = self.engine.rollback(rid, "read", reason="sent to the wrong list")
        self.assertEqual((run["status"], run["pending"]["step"]), ("input_required", "compensate-send-1"))
        self.assertEqual(run["pending"]["rules"], ["approve.message.send"])
        item = self.engine.item(run["pending"]["id"])
        self.assertEqual(item["present"]["actions"], [{"action": "message.send"}])

        run = self.engine.deny(rid, "not yet", item_id=run["pending"]["id"])  # a denial fails the run
        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["steps"]["send"]["status"], "completed")
        self.assertTrue(run["rollback"])

        run = self.engine.rollback(rid, "read", reason="sent to the wrong list, again")  # tried again
        self.assertEqual(len(run["rollbacks"]), 1)  # the unfinished one is kept
        self.assertEqual(run["steps"]["compensate-send-1"]["history"][0]["approval"]["decision"], "denied")
        run = self.engine.approve(rid, item_id=run["pending"]["id"])
        self.assertEqual((run["status"], run["next"]), ("working", "send"))
        self.assertEqual(run["steps"]["send"]["status"], "rolledBack")
        self.assertEqual(calls(self.log)[-1], f"echo {rid}:compensate-send-1")

    def test_only_a_completed_or_failed_run_rolls_back_to_a_step_that_completed(self):
        run = self.engine.start(self.plan(self.STEPS[:1] + [self.SEND]), {"path": "README.md"})
        with self.assertRaisesRegex(engine.EngineError, "is input_required; only a completed or failed run"):
            self.engine.rollback(run["runId"], "read", reason="undo")
        run = self.completed()
        for to, why in (("nope", "has no completed step 'nope'"), ("read", "needs a reason")):
            with self.subTest(to), self.assertRaisesRegex(engine.EngineError, why):
                self.engine.rollback(run["runId"], to, reason="" if to == "read" else "undo")
        e = engine.Engine(self.tmp / "runs", workflows_dir=self.tmp / "workflows", workers=self.workers,
                          log=lambda *a: None)
        with self.assertRaisesRegex(engine.EngineError, "needs an actor ID"):
            e.rollback(run["runId"], "read", reason="undo")
        with engine.marked("run_other"), self.assertRaisesRegex(engine.EngineError, "inside run run_other"):
            self.engine.rollback(run["runId"], "read", reason="undo")
        self.assertEqual(self.engine.load(run["runId"])["status"], "completed")

    def test_a_plan_with_a_compensate_step_that_doesnt_check_is_refused(self):
        for comp, why in (({"worker": "echo"}, "compensate must be a step with a worker and an input"),
                          ({"worker": "echo", "input": {}, "retries": 3}, "unknown field 'retries' in compensate"),
                          ({"worker": "nope", "input": {}}, "unknown worker 'nope'")):
            with self.subTest(why), self.assertRaisesRegex(engine.EngineError, why):
                self.engine.start(self.plan([dict(self.STEPS[2], compensate=comp)]), {"path": "x"})


if __name__ == "__main__":
    unittest.main()
