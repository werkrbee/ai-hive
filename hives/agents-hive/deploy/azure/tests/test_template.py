"""Tests for the compiled template: each agent may write only its own audit blob.

The audit container holds Patricia's copy and hosted Barry's. Its retention policy refuses
changes and deletes but not appends, so an identity with Storage Blob Data Contributor on
the whole container could add to the other agent's copy. Each assignment of that role on
the container must carry a condition that keeps its identity to its own blob.

Needs the Azure CLI with Bicep (az bicep build); skipped without it. Run from the repo root:
  python3 -B -m unittest discover -s hives/agents-hive/deploy/azure/tests -p 'test_*.py'
"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONTRIBUTOR = "storageBlobDataContributor"
PATH_CONDITION = ("[format('(({0}) OR (@Resource[Microsoft.Storage/storageAccounts/blobServices/containers/"
                  "blobs:path] StringEquals ''{1}''))', variables('notBlobActions'), variables('%s'))]")


@unittest.skipUnless(shutil.which("az"), "needs the Azure CLI with Bicep")
class Template(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = subprocess.run(["az", "bicep", "build", "--file", str(HERE.parent / "main.bicep"), "--stdout"],
                             capture_output=True, text=True, check=True).stdout
        cls.template = json.loads(out)

    def audit_writers(self):
        """The Contributor assignments on the audit container, by whose identity they're for."""
        found = {}
        for r in self.template["resources"]:
            p = r.get("properties", {})
            if r.get("type") == "Microsoft.Authorization/roleAssignments" and CONTRIBUTOR in p.get("roleDefinitionId", "") \
                    and "variables('auditContainer')" in r.get("scope", ""):
                who = "barry" if "variables('barryName')" in p["principalId"] else "patricia"
                self.assertNotIn(who, found, f"two Contributor assignments on the audit container for {who}")
                found[who] = p
        return found

    def test_each_agents_audit_role_is_conditioned_to_its_own_blob(self):
        writers = self.audit_writers()
        self.assertEqual(set(writers), {"patricia", "barry"})
        variables = self.template["variables"]
        for who, blob in (("patricia", "patricia.jsonl"), ("barry", "barry.jsonl")):
            with self.subTest(agent=who):
                p = writers[who]
                self.assertEqual(p.get("conditionVersion"), "2.0")
                self.assertEqual(p.get("condition"), PATH_CONDITION % f"{who}AuditBlob")
                self.assertEqual(variables[f"{who}AuditBlob"], blob)

    def test_the_condition_allows_no_blob_data_action_elsewhere(self):
        actions = self.template["variables"]["blobActions"]
        self.assertEqual(sorted(actions), sorted(["read", "write", "delete", "add/action", "move/action"]))
        self.assertIn("ActionMatches", self.template["variables"]["notBlobActions"])

    def test_patricias_job_pushes_to_the_blob_her_role_allows(self):
        url = self.template["outputs"]["auditBlobUrl"]["value"]
        self.assertTrue(re.search(r"variables\('patriciaAuditBlob'\)\)\]$", url), url)


if __name__ == "__main__":
    unittest.main()
