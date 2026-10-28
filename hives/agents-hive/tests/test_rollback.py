"""Tests for rolling an agent back to an earlier passport version: which commit is
deployed, what is refused, and what is recorded. deploy.sh's side of it is tested in
deploy/azure/tests/deploy_test.sh.

Standard library only. Run from the repo root:
  python3 -B -m unittest discover -s hives/agents-hive/tests
"""
import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock
from pathlib import Path

HIVE = Path(__file__).resolve().parent.parent
REPO_ROOT = HIVE.parent.parent


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rb = load(HIVE / "scripts" / "rollback.py", "rollback")
vp = load(HIVE / "scripts" / "validate_passports.py", "validate_passports")


class History(unittest.TestCase):
    """A repo whose passport is v1, then v2 in two commits, then v4: v3 never existed."""

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        patcher = mock.patch.object(rb, "REPO_ROOT", self.repo)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.git("init", "-q")
        self.commits = {}
        for version, model, note in ((1, "claude-x", "a"), (2, "claude-x", "b"), (2, "claude-x", "c"),
                                     (4, "gpt-5.4", "d")):
            self.commit(version, model, note)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=test", "-c", "user.email=t@example.com",
                               *args], check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, version, model, note):
        path = self.repo / rb.passport_path("patricia")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"passport": "patricia", "version": version,
                                    "pins": {"model": {"publisher": "test", "name": model, "version": "1"}}}))
        (self.repo / "notes.txt").write_text(note)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", note)
        self.commits[note] = self.git("rev-parse", "HEAD")

    def test_the_newest_commit_at_the_version_is_deployed_with_the_model_it_pins(self):
        self.assertEqual(rb.plan("patricia", 2, "usr_7f3a", "v4 drifted"), f"{self.commits['c']} claude-x 1")
        self.assertEqual(rb.plan("patricia", 1, "usr_7f3a", "v4 drifted"), f"{self.commits['a']} claude-x 1")

    def test_a_version_that_isnt_earlier_or_never_existed_is_refused(self):
        for version, why in ((4, "is version 4; roll it back to an earlier version"), (5, "is version 4"),
                             (0, "is version 4"), (3, "was never version 3")):
            with self.subTest(version), self.assertRaisesRegex(rb.RollbackError, why):
                rb.plan("patricia", version, "usr_7f3a", "why")

    def test_a_rollback_needs_an_actor_id_and_a_reason(self):
        for by, reason, why in (("jane@example.com", "why", "isn't an actor ID"), ("", "why", "isn't an actor ID"),
                                ("usr_7f3a", " ", "needs a reason")):
            with self.subTest(by=by, reason=reason), self.assertRaisesRegex(rb.RollbackError, why):
                rb.plan("patricia", 2, by, reason)

    def test_findings_recorded_since_against_the_earlier_pins_are_named(self):
        results = self.repo / "results.jsonl"
        pins = {"model": {"publisher": "test", "name": "claude-x", "version": "1"}}
        digest = "sha256:" + rb.hashlib.sha256(rb.check_audit.canonical(pins)).hexdigest()

        def entry(rid, found, pinned=digest):
            return json.dumps({"id": rid, "eval": {"passport": "patricia", "pins": pinned, "findings": found}})

        path = self.repo / rb.passport_path("patricia")
        path.write_text(json.dumps({"passport": "patricia", "version": 5, "pins": pins,
                                    "eval": {"baseline": {"result": "results.jsonl#base"}}}))
        results.write_text(entry("base", []) + "\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "v5")
        then = self.git("rev-parse", "HEAD")
        self.assertEqual(rb.newer_findings("patricia", then), [])
        self.commit(6, "gpt-5.4", "e")
        with results.open("a") as f:
            for line in (entry("later-pass", []), entry("later-drift", ["drift", "cost"]),
                         entry("other-pins", ["drift"], "sha256:00")):
                f.write(line + "\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "results")
        self.assertEqual(rb.newer_findings("patricia", then), ["later-drift (drift, cost)"])
        self.assertEqual(rb.newer_findings("patricia", self.commits["c"]), [])  # v2 has no eval

    def test_the_record_keeps_the_reason_and_the_log_only_who_and_the_records_digest(self):
        audit = self.repo / "state" / "audit.jsonl"
        entry, path = rb.record("patricia", self.commits["c"], "usr_7f3a", "v4 misreads the Charter", audit)
        record = json.loads(path.read_text())
        self.assertEqual(entry["record"], rb.check_audit.digest(record))
        self.assertEqual(path.parent, audit.parent / "rollbacks")
        self.assertEqual((record["from"]["version"], record["to"]["version"]), (4, 2))
        self.assertEqual((record["from"]["commit"], record["to"]["commit"]), (self.commits["d"], self.commits["c"]))
        self.assertEqual((record["by"], record["reason"]), ("usr_7f3a", "v4 misreads the Charter"))
        v2 = json.loads(self.git("show", f"{self.commits['c']}:{rb.passport_path('patricia')}"))
        self.assertEqual(entry["agent"], {"passport": "patricia", "version": 2, "sha256": vp.digest(v2)})
        self.assertEqual((entry["kind"], entry["by"], entry["via"]), ("rollback", "usr_7f3a", "cli"))
        self.assertEqual(rb.check_audit.check(audit), [])
        self.assertNotIn("Charter", audit.read_text())


if __name__ == "__main__":
    unittest.main()
