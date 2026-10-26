"""Tests for the review queue: approvals, escalations and drift as items, their IDs, expiry,
the refusals to answer from an agent's seat, the command and the MCP server.

Run from the repo root: python3 -B -m unittest discover -s hives/workflows-hive/tests
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import run as engine  # noqa: E402

LINEUP = "hives/rules-hive/examples/lineup-etiquette/policy.json"
BLAST = {"action": "message.send", "scope": {"channel": "sms", "audience": "group"},
         "facts": {"recipient.notifyOptIn": True, "message": "Game moved to 7pm.", "recipient count": 14}}


def at_terminal(*argv, env=None):
    """Run argv with a pseudo-terminal as its stdin and stdout, as a person at a terminal
    would. Returns (exit status, output)."""
    import pty
    main, sub = pty.openpty()
    p = subprocess.Popen(argv, stdin=sub, stdout=sub, stderr=sub, env=env)
    os.close(sub)
    out = b""
    while True:
        try:
            chunk = os.read(main, 4096)
        except OSError:
            break
        if not chunk:
            break
        out += chunk
    os.close(main)
    return p.wait(), out.decode(errors="replace").replace("\r\n", "\n")


def audit_kinds(path):
    return [json.loads(line)["kind"] for line in path.read_text().splitlines()]


def last_entry(path, kind):
    return [json.loads(line) for line in path.read_text().splitlines() if json.loads(line)["kind"] == kind][-1]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.later = timedelta(0)
        self.engine = self.make()
        self.ran = []

    def make(self, **kw):
        workers = dict(engine.WORKERS, echo=lambda inp, key, cap: (self.ran.append(key) or inp, {"usd": 0, "tokens": 0}))
        return engine.Engine(self.tmp / "runs", workers=workers, log=lambda *a: None, actor="usr_7f3a",
                             clock=lambda: datetime.now(timezone.utc) + self.later, **kw)

    def paused(self, actions=None, approval=None):
        """An open run paused on one step."""
        run = self.engine.open("loop", policy=LINEUP)
        step = {"id": "send", "worker": "echo", "input": {"n": 1}}
        if actions is not None:
            step["actions"] = actions
        if approval is not None:
            step["approval"] = approval
        self.engine.append(run, step)
        return self.engine.execute(run)

    @property
    def audit(self):
        return self.tmp / "audit.jsonl"


class Approvals(Base):
    def test_a_pause_is_an_open_item_named_by_its_approval_id(self):
        run = self.paused([BLAST])
        pending = run["pending"]
        self.assertTrue(pending["id"].startswith("sha256:"))
        [item] = self.engine.items()
        self.assertEqual(item["id"], pending["id"])
        self.assertEqual((item["kind"], item["status"]), ("approval", "open"))
        self.assertEqual(item["source"], {"runId": run["runId"], "step": "send"})
        self.assertEqual(item["present"]["rules"], ["organizer.blast"])
        self.assertEqual(item["present"]["values"], {"message": "Game moved to 7pm.", "recipient count": 14,
                                                     "estimated cost": None})
        created = datetime.fromisoformat(item["createdAt"].replace("Z", "+00:00"))
        self.assertEqual(datetime.fromisoformat(item["expiresAt"].replace("Z", "+00:00")) - created, timedelta(days=7))
        self.assertEqual(last_entry(self.audit, "step.decided")["item"], pending["id"])

    def test_the_id_digests_what_is_shown(self):
        one = self.paused([BLAST])["pending"]["id"]
        other = dict(BLAST, facts=dict(BLAST["facts"], message="Game cancelled."))
        self.assertNotEqual(self.paused([other])["pending"]["id"], one)

    def test_approving_an_item_runs_the_step_and_records_how(self):
        run = self.paused([BLAST])
        self.engine.answer_item(run["pending"]["id"][7:15], "approved")
        run = self.engine.load(run["runId"])
        self.assertEqual(run["steps"]["send"]["status"], "completed")
        self.assertEqual(run["steps"]["send"]["approval"]["via"], "cli")
        self.assertEqual(self.engine.items(), [])
        [item] = self.engine.items(None)
        self.assertEqual((item["status"], item["answer"]["by"]), ("answered", "usr_7f3a"))
        entry = last_entry(self.audit, "approval.answered")
        self.assertEqual((entry["item"], entry["via"], entry["by"]), (item["id"], "cli", "usr_7f3a"))

    def test_denying_an_item_fails_the_run_and_needs_a_reason(self):
        run = self.paused([BLAST])
        with self.assertRaisesRegex(engine.EngineError, "deny needs a reason"):
            self.engine.answer_item(run["pending"]["id"], "denied")
        self.engine.answer_item(run["pending"]["id"], "denied", reason="wrong group")
        run = self.engine.load(run["runId"])
        self.assertEqual(run["status"], "failed")
        self.assertEqual(self.ran, [])
        self.assertEqual(self.engine.items(None)[0]["answer"]["reason"], "wrong group")

    def test_an_answer_with_the_wrong_id_is_refused(self):
        run = self.paused([BLAST])
        with self.assertRaisesRegex(engine.EngineError, "isn't what run .* is waiting on"):
            self.engine.approve(run["runId"], item_id="sha256:" + "0" * 64)
        self.assertEqual(self.engine.load(run["runId"])["status"], "input_required")
        self.engine.approve(run["runId"], item_id=run["pending"]["id"])
        self.assertEqual(self.engine.load(run["runId"])["steps"]["send"]["status"], "completed")

    def test_an_approval_of_anything_else_is_void_and_the_step_waits_again(self):
        run = self.paused([BLAST])
        pid = run["pending"]["id"]
        run["steps"]["send"]["approval"] = {"decision": "approved", "by": "usr_7f3a", "id": "sha256:" + "1" * 64}
        run.update(status="working", pending=None)
        self.engine.save(run)
        run = self.engine.execute(self.engine.load(run["runId"]))
        self.assertEqual((run["status"], run["pending"]["id"]), ("input_required", pid))
        self.assertEqual(self.ran, [])

    def test_a_cancel_answers_the_item(self):
        run = self.paused(approval=True)
        self.engine.cancel(run["runId"])
        [item] = self.engine.items(None)
        self.assertEqual((item["status"], item["answer"]["decision"]), ("answered", "cancelled"))


class Expiry(Base):
    def test_an_approval_unanswered_for_seven_days_expires_and_fails_its_run(self):
        run = self.paused([BLAST])
        self.later = timedelta(days=7, seconds=1)
        self.assertEqual(self.engine.items(), [])
        [item] = self.engine.items(None)
        self.assertEqual(item["status"], "expired")
        run = self.engine.load(run["runId"])
        self.assertEqual(run["status"], "failed")
        self.assertIn("expired unanswered", run["error"]["message"])
        self.assertEqual(audit_kinds(self.audit)[-1], "run.expired")
        self.assertEqual(self.ran, [])

    def test_an_expired_approval_cant_be_answered(self):
        run = self.paused([BLAST])
        self.later = timedelta(days=8)
        with self.assertRaisesRegex(engine.EngineError, "waited too long"):
            self.engine.approve(run["runId"])
        self.assertEqual(self.ran, [])

    def test_resume_expires_a_due_pause(self):
        run = self.paused(approval=True)
        self.later = timedelta(days=8)
        self.assertEqual(self.engine.resume(run["runId"])["status"], "failed")

    def test_six_days_isnt_seven(self):
        run = self.paused(approval=True)
        self.later = timedelta(days=6)
        self.assertEqual(len(self.engine.items()), 1)
        self.assertEqual(self.engine.load(run["runId"])["status"], "input_required")


class Escalations(Base):
    def test_an_escalation_waits_for_an_answer_its_loop_reads_once(self):
        e = self.engine
        run = e.open("loop")
        self.assertIsNone(e.escalate(run, "which-repo", "Which repo should I release?"))
        self.assertEqual(run["status"], "input_required")
        self.assertIsNone(e.escalate(run, "which-repo", "Which repo should I release?"))  # still waiting
        [item] = e.items()
        self.assertEqual((item["kind"], item["present"]["question"]), ("escalation", "Which repo should I release?"))
        with self.assertRaisesRegex(engine.EngineError, "answered with text"):
            e.answer_item(item["id"], "approved")
        e.answer_item(item["id"], "answered", text="ai-hive")
        run = e.load(run["runId"])
        self.assertEqual(run["status"], "working")
        self.assertEqual(e.escalate(run, "which-repo", "Which repo should I release?"), "ai-hive")
        self.assertEqual(audit_kinds(self.audit)[-2:], ["escalation.raised", "escalation.answered"])
        self.assertNotIn("ai-hive", self.audit.read_text())  # the answer's text stays in the run

    def test_an_escalation_expires_too(self):
        run = self.engine.open("loop")
        self.engine.escalate(run, "q", "Go ahead?")
        self.later = timedelta(days=8)
        self.assertEqual(self.engine.items(None)[0]["status"], "expired")
        self.assertEqual(self.engine.load(run["runId"])["status"], "failed")


class Drift(Base):
    AGENT = {"passport": "patricia", "version": 3, "sha256": "a" * 64}

    def test_drift_never_expires_and_is_answered_without_a_run(self):
        item = self.engine.drift(self.AGENT, "eval_2026-10-26", {"baseline": 12, "runs": [9, 10]})
        self.assertIsNone(item["expiresAt"])
        self.later = timedelta(days=365)
        self.assertEqual([i["id"] for i in self.engine.items()], [item["id"]])
        with self.assertRaisesRegex(engine.EngineError, "deny needs a reason"):
            self.engine.answer_item(item["id"], "denied")
        answered = self.engine.answer_item(item["id"], "denied", reason="hold until the model is fixed")
        self.assertEqual(answered["status"], "answered")
        entry = last_entry(self.audit, "drift.answered")
        self.assertEqual((entry["agent"], entry["decision"], entry["via"]), (self.AGENT, "denied", "cli"))
        with self.assertRaisesRegex(engine.EngineError, "only an open item"):
            self.engine.answer_item(item["id"], "approved")


class Refusals(Base):
    def test_a_step_runs_marked_as_inside_its_run(self):
        seen = []

        def agent(inp, key, cap):
            try:
                engine.answering_here("mcp")
            except engine.EngineError as err:
                seen.append(str(err))
            return inp, {"usd": 0, "tokens": 0}
        e = engine.Engine(self.tmp / "runs", workers={"agent": agent}, log=lambda *a: None)
        run = e.open("loop")
        e.append(run, {"id": "s", "worker": "agent", "input": {}})
        e.execute(run)
        self.assertEqual(len(seen), 1)
        self.assertIn("from inside run", seen[0])
        self.assertNotIn(engine.RUN_ENV, os.environ)

    def cli(self, *args, terminal, env_extra=None):
        env = dict(os.environ, WORKFLOWS_HIVE_ACTOR="usr_7f3a", **(env_extra or {}))
        argv = [sys.executable, "-B", str(SCRIPTS / "review_queue.py"), "--state-dir", str(self.tmp / "runs"), *args]
        if terminal:
            return at_terminal(*argv, env=env)
        p = subprocess.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env)
        return p.returncode, p.stdout + p.stderr

    @unittest.skipUnless(os.name == "posix", "needs a pseudo-terminal")
    def test_the_command_answers_only_at_a_terminal_and_outside_a_run(self):
        run = self.paused([BLAST])
        pid = run["pending"]["id"]
        code, out = self.cli("approve", pid, terminal=False)
        self.assertEqual(code, 1)
        self.assertIn("without an interactive terminal", out)
        code, out = self.cli("approve", pid, terminal=True, env_extra={engine.RUN_ENV: "run_x"})
        self.assertEqual(code, 1)
        self.assertIn("from inside run run_x", out)
        code, out = self.cli("approve", "0123456789abcdef", terminal=True)
        self.assertEqual(code, 1)
        self.assertIn("no item 0123456789abcdef", out)
        self.assertEqual(self.engine.load(run["runId"])["status"], "input_required")
        code, out = self.cli("approve", pid[7:19], terminal=True)
        self.assertEqual(code, 0, out)
        approval = self.engine.load(run["runId"])["steps"]["send"]["approval"]
        self.assertEqual((approval["decision"], approval["via"]), ("approved", "cli"))
        code, out = self.cli("list", "--all", terminal=False)
        self.assertIn(f"{pid[7:19]}  approval    answered", out)


class Mcp(Base):
    def start(self, elicitation=True, version="2025-06-18"):
        env = dict(os.environ, WORKFLOWS_HIVE_ACTOR="usr_7f3a")
        env.pop(engine.RUN_ENV, None)
        self.p = subprocess.Popen([sys.executable, "-B", str(SCRIPTS / "queue_mcp.py"), "--state-dir",
                                   str(self.tmp / "runs")], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, env=env)
        self.addCleanup(self.p.wait)
        self.addCleanup(self.p.stdin.close)
        self.n = 0
        caps = {"elicitation": {}} if elicitation else {}
        result = self.request("initialize", {"protocolVersion": version, "capabilities": caps,
                                             "clientInfo": {"name": "test", "version": "0"}})
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return result

    def send(self, message):
        self.p.stdin.write(json.dumps(message) + "\n")
        self.p.stdin.flush()

    def read(self):
        return json.loads(self.p.stdout.readline())

    def request(self, method, params=None, reply=None):
        """Send a request; answer an elicitation with reply when one comes first."""
        self.n += 1
        self.send({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}})
        while True:
            message = self.read()
            if message.get("method") == "elicitation/create":
                self.elicited = message["params"]
                self.send({"jsonrpc": "2.0", "id": message["id"], "result": reply})
                continue
            self.assertEqual(message["id"], self.n)
            return message.get("result", message.get("error"))

    def tools(self):
        return [t["name"] for t in self.request("tools/list")["tools"]]

    def call(self, name, reply=None, **args):
        result = self.request("tools/call", {"name": name, "arguments": args}, reply)
        return result["content"][0]["text"], result.get("isError", False)

    def test_reads_list_show_and_resources(self):
        run = self.paused([BLAST])
        self.start()
        self.assertIn(run["pending"]["id"], self.call("list_items")[0])
        self.assertIn("Game moved to 7pm.", self.call("show_item", id=run["pending"]["id"])[0])
        [resource] = self.request("resources/list")["resources"]
        contents = self.request("resources/read", {"uri": resource["uri"]})["contents"][0]
        self.assertEqual(json.loads(contents["text"])["id"], run["pending"]["id"])

    def test_a_client_without_elicitation_gets_the_queue_read_only(self):
        run = self.paused([BLAST])
        self.start(elicitation=False)
        self.assertEqual(self.tools(), ["list_items", "show_item"])
        error = self.request("tools/call", {"name": "answer_item", "arguments": {"id": run["pending"]["id"]}})
        self.assertIn("no tool answer_item", error["message"])
        self.assertEqual(self.engine.load(run["runId"])["status"], "input_required")

    def test_the_decision_comes_from_the_person_never_the_arguments(self):
        run = self.paused([BLAST])
        self.assertEqual(self.start(version="2025-11-25")["protocolVersion"], "2025-11-25")
        self.assertIn("answer_item", self.tools())
        self.assertEqual(list(next(t for t in self.request("tools/list")["tools"]
                                   if t["name"] == "answer_item")["inputSchema"]["properties"]), ["id"])
        text, error = self.call("answer_item", reply={"action": "accept", "content": {"decision": "approve"}},
                                id=run["pending"]["id"], decision="deny", reason="the model says no")
        self.assertFalse(error, text)
        self.assertIn("Game moved to 7pm.", self.elicited["message"])
        run = self.engine.load(run["runId"])
        self.assertEqual(run["steps"]["send"]["approval"]["decision"], "approved")
        self.assertEqual(last_entry(self.audit, "approval.answered")["via"], "mcp")

    def test_a_declined_elicitation_answers_nothing(self):
        run = self.paused([BLAST])
        self.start()
        text, _ = self.call("answer_item", reply={"action": "decline"}, id=run["pending"]["id"])
        self.assertIn("not answered", text)
        self.assertEqual(self.engine.load(run["runId"])["status"], "input_required")
        self.assertEqual(self.engine.items()[0]["status"], "open")


if __name__ == "__main__":
    unittest.main()
