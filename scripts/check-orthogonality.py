#!/usr/bin/env python3
"""Check static separation-of-powers invariants in the Queen Bee charter.

This validates repository governance artifacts, not runtime agent behavior.
Runtime authorization must still be enforced by the host/orchestrator.
"""
from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]
CHARTER = ROOT / "hives/rules-hive/rules/queen-charter/AGENTS.md"
POLICY = ROOT / "hives/rules-hive/rules/queen-charter/policy.json"
PATRICIA = ROOT / "hives/skills-hive/skills/patricia/SKILL.md"


class OrthogonalityGovernanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.charter = CHARTER.read_text(encoding="utf-8").lower()
        cls.patricia = PATRICIA.read_text(encoding="utf-8").lower()
        cls.policy = json.loads(POLICY.read_text(encoding="utf-8"))

    def test_charter_describes_independent_authority(self):
        for phrase in ("no self-approval", "no self-amendment",
                       "no privilege amplification", "no circular authority",
                       "independent enforcement", "fail closed"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.charter)

    def test_patricia_reviews_separation(self):
        for phrase in ("self-approval", "circular authority",
                       "independent deterministic gate"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.patricia)

    def test_policy_blocks_agent_answers_to_human_queue(self):
        prohibitions = self.policy["prohibitions"]
        self.assertTrue(any(p.get("action") == "queue.answer"
                            and p.get("id") == "queue.no-answer"
                            for p in prohibitions))

    def test_policy_rejects_unlisted_delegation_and_whole_context(self):
        ids = {p["id"] for p in self.policy["prohibitions"]}
        self.assertTrue({"delegate.unlisted", "delegate.whole-context"} <= ids)

    def test_policy_denies_audit_mutation(self):
        ids = {p["id"] for p in self.policy["prohibitions"]}
        self.assertTrue({"audit.no-edit", "audit.no-delete"} <= ids)


if __name__ == "__main__":
    unittest.main()
