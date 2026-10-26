"""Tests for the audit log: its hash rules, the verifier's reports, and the run records' anchors.

Standard library only. Run from the repo root:
  python3 -B -m unittest discover -s hives/knowledge-hive/tests
"""
import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

HIVE = Path(__file__).resolve().parent.parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, HIVE / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = load("check_audit")
knowledge = load("check_knowledge")


class Log(unittest.TestCase):
    """Writes a five-entry log for one run, with the run's record anchored to its last entry."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.log = self.tmp / "audit.jsonl"
        self.runs = self.tmp / "runs"
        self.runs.mkdir()
        written = [audit.append(self.log, {"kind": "run.started", "runId": "run_1"})]
        for sid in ("read", "count"):
            written.append(audit.append(self.log, {"kind": "step.decided", "runId": "run_1", "step": sid,
                                                   "decision": "allowed", "rules": []}))
        written.append(audit.append(self.log, {"kind": "run.completed", "runId": "run_1"}))
        written.append(audit.append(self.log, {"kind": "approval.answered", "runId": "run_2", "step": "s1",
                                               "decision": "approved", "by": "usr_7f3a"}))
        self.anchor("run_1", written[3])
        self.anchor("run_2", written[4])

    def anchor(self, run_id, entry):
        (self.runs / f"{run_id}.json").write_text(json.dumps(
            {"runId": run_id, "audit": {"seq": entry["seq"], "hash": entry["hash"]}}))

    def lines(self):
        return self.log.read_text().splitlines()

    def rewrite(self, lines):
        self.log.write_text("".join(line + "\n" for line in lines))

    def errors(self):
        return audit.check(self.log, self.runs)

    def assertReported(self, text):
        errors = self.errors()
        self.assertTrue(errors and text in errors[0], f"expected {text!r} first in {errors}")


class HashRules(Log):
    def test_a_written_log_checks(self):
        self.assertEqual(self.errors(), [])
        self.assertEqual([json.loads(line)["seq"] for line in self.lines()], [1, 2, 3, 4, 5])

    def test_the_first_prev_is_the_genesis_value(self):
        self.assertEqual(json.loads(self.lines()[0])["prev"], "sha256:" + "0" * 64)

    def test_each_hash_is_the_canonical_digest_of_the_entry_without_it(self):
        for line in self.lines():
            entry = json.loads(line)
            body = {k: v for k, v in entry.items() if k != "hash"}
            canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            self.assertEqual(entry["hash"], "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest())

    def test_each_prev_is_the_hash_before_it(self):
        entries = [json.loads(line) for line in self.lines()]
        for before, after in zip(entries, entries[1:]):
            self.assertEqual(after["prev"], before["hash"])


class Tampering(Log):
    def test_an_edited_entry_is_reported_at_its_line(self):
        lines = self.lines()
        lines[1] = lines[1].replace('"allowed"', '"denied"')
        self.rewrite(lines)
        self.assertReported("audit.jsonl:2: entry 2 was edited")

    def test_an_edited_entry_with_its_hash_recomputed_is_reported_at_the_next(self):
        lines = self.lines()
        entry = json.loads(lines[1])
        entry["decision"] = "denied"
        entry["hash"] = audit.entry_hash(entry)
        lines[1] = json.dumps(entry)
        self.rewrite(lines)
        self.assertReported("audit.jsonl:3: entry 3's prev isn't entry 2's hash")

    def test_a_removed_entry_is_reported(self):
        self.rewrite(self.lines()[:2] + self.lines()[3:])
        self.assertReported("audit.jsonl:3: entry 3 is missing: seq jumps from 2 to 4")

    def test_an_inserted_entry_is_reported(self):
        lines = self.lines()
        self.rewrite(lines[:3] + [lines[1]] + lines[3:])
        self.assertReported("audit.jsonl:4: entry 2 comes after entry 3")

    def test_reordered_entries_are_reported(self):
        lines = self.lines()
        lines[1], lines[2] = lines[2], lines[1]
        self.rewrite(lines)
        self.assertReported("audit.jsonl:2: entry 2 is missing: seq jumps from 1 to 3")

    def test_a_removed_first_entry_is_reported(self):
        self.rewrite(self.lines()[1:])
        self.assertReported("audit.jsonl:1: entry 1 is missing")

    def test_a_log_cut_short_is_caught_by_a_run_record(self):
        self.rewrite(self.lines()[:4])
        self.assertEqual(audit.check(self.log), [])  # the chain alone can't show it
        self.assertReported("ends at entry 4, before run run_2's last entry 5; the log was cut short")

    def test_a_log_rewritten_whole_is_caught_by_a_run_record(self):
        self.log.unlink()
        audit.append(self.log, {"kind": "run.started", "runId": "run_1"})
        for _ in range(4):
            audit.append(self.log, {"kind": "run.started", "runId": "run_3"})
        self.assertReported("entry 4 isn't the one run run_1 recorded; the log was rewritten")

    def test_only_the_first_break_is_reported(self):
        lines = self.lines()
        lines[1] = lines[1].replace('"allowed"', '"denied"')
        lines[3] = lines[3].replace('"run.completed"', '"run.failed"')
        self.rewrite(lines)
        self.assertEqual(len(self.errors()), 1)


class Format(Log):
    def append_raw(self, **fields):
        last = json.loads(self.lines()[-1])
        entry = {"seq": last["seq"] + 1, "at": "2026-10-26T12:00:00Z", "prev": last["hash"], **fields}
        entry["hash"] = audit.entry_hash(entry)
        self.log.write_text(self.log.read_text() + json.dumps(entry) + "\n")

    def test_an_unknown_field_is_reported(self):
        self.append_raw(kind="run.started", runId="run_9", message="hello")
        self.assertIn("audit.jsonl:6: unknown field 'message'", audit.check(self.log))

    def test_a_name_or_email_in_by_is_reported(self):
        for by in ("Jane Doe", "jane@example.com"):
            with self.subTest(by):
                self.setUp()
                self.append_raw(kind="run.cancelled", runId="run_9", by=by)
                self.assertTrue(any("by must be an opaque identifier" in e for e in audit.check(self.log)))

    def test_a_decision_that_doesnt_fit_its_kind_is_reported(self):
        self.append_raw(kind="approval.answered", runId="run_9", step="s1", decision="allowed", by="ci")
        self.assertTrue(any("decision must be one of approved, denied" in e for e in audit.check(self.log)))

    def test_an_answer_says_how_it_came(self):
        self.append_raw(kind="escalation.answered", runId="run_9", item="sha256:" + "a" * 64, by="ci", via="email")
        self.assertTrue(any("via must be one of cli, mcp, a2a" in e for e in audit.check(self.log)))
        with self.assertRaisesRegex(audit.AuditError, "missing 'via'"):
            audit.append(self.log, {"kind": "drift.answered", "item": "sha256:" + "a" * 64,
                                    "decision": "approved", "by": "ci"})

    def test_an_eval_names_its_result_and_a_finding_its_item(self):
        agent = {"passport": "patricia", "version": 4, "sha256": "a" * 64}
        with self.assertRaisesRegex(audit.AuditError, "missing 'result'"):
            audit.append(self.log, {"kind": "eval.ran", "agent": agent})
        with self.assertRaisesRegex(audit.AuditError, "missing 'item'"):
            audit.append(self.log, {"kind": "eval.flagged", "agent": agent})
        audit.append(self.log, {"kind": "eval.ran", "agent": agent, "result": "2026-10-27-patricia-eval"})
        self.assertEqual(self.errors(), [])

    def test_the_writer_refuses_an_entry_that_doesnt_fit(self):
        with self.assertRaisesRegex(audit.AuditError, "missing 'by'"):
            audit.append(self.log, {"kind": "run.cancelled", "runId": "run_9"})
        self.assertEqual(len(self.lines()), 5)

    def test_the_writer_refuses_a_log_whose_last_line_is_cut_off(self):
        self.log.write_text(self.log.read_text() + '{"seq": 6, "at"')
        with self.assertRaisesRegex(audit.AuditError, "last line is incomplete"):
            audit.append(self.log, {"kind": "run.started", "runId": "run_9"})


class InKnowledge(Log):
    def test_a_knowledge_directory_checks_its_audit_log(self):
        k = self.tmp / "knowledge"
        k.mkdir()
        (k / "STATE.md").write_text((HIVE / "templates" / "knowledge" / "STATE.md").read_text())
        lines = self.lines()
        (k / "audit.jsonl").write_text("".join(line + "\n" for line in lines))
        self.assertEqual(knowledge.check(k), [])
        lines[1] = lines[1].replace('"allowed"', '"denied"')
        (k / "audit.jsonl").write_text("".join(line + "\n" for line in lines))
        self.assertEqual(knowledge.check(k), ["audit.jsonl:2: entry 2 was edited: its hash doesn't match its contents"])


if __name__ == "__main__":
    unittest.main()
