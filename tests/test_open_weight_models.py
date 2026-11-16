"""Offline unit tests for the monthly open-weight metadata collector."""
import io
import json
import os
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from scripts.update_open_weight_models import MODELS, build_snapshot, fetch_model


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.close()


class ModelTrackerTests(unittest.TestCase):
    def test_license_tag_and_gating(self):
        model = MODELS[0]
        def opener(request, timeout):
            self.assertEqual(timeout, 25)
            self.assertIn(model, request.full_url)
            return FakeResponse(json.dumps({
                "id": model, "tags": ["license:llama3.1"],
                "gated": "manual", "lastModified": "2026-11-01T00:00:00Z"
            }).encode())
        row = fetch_model(model, opener)
        self.assertEqual(row["license_tag_unverified"], "llama3.1")
        self.assertEqual(row["gated"], "manual")

    def test_custom_license_and_revision_pinned_download(self):
        def opener(request, timeout):
            return FakeResponse(json.dumps({
                "id": MODELS[-1], "sha": "abc123", "gated": False,
                "cardData": {"license": "other", "license_name": "nvidia-open-model-license",
                             "license_link": "https://www.nvidia.com/license"},
                "siblings": [{"rfilename": "model.safetensors"}]
            }).encode())
        row = fetch_model(MODELS[-1], opener)
        self.assertEqual(row["license_name_unverified"], "nvidia-open-model-license")
        self.assertEqual(row["license_link_unverified"], "https://www.nvidia.com/license")
        self.assertEqual(row["weight_file_count"], 1)
        self.assertEqual(row["example_weight_download"],
                         "https://huggingface.co/" + MODELS[-1] + "/resolve/abc123/model.safetensors")

    def test_wrong_model_id_rejected(self):
        def opener(request, timeout):
            return FakeResponse(b'{"id":"unexpected"}')
        with self.assertRaises(ValueError):
            fetch_model(MODELS[0], opener)

    def test_snapshot_deterministic_and_complete(self):
        def fake_fetch(model):
            return {"model_id": model}
        a = build_snapshot("2026-11", fake_fetch)
        self.assertEqual(a, build_snapshot("2026-11", fake_fetch))
        self.assertEqual(len(a["models"]), len(MODELS))
        self.assertEqual(a["review_month_utc"], "2026-11")

    def test_invalid_month_rejected(self):
        with self.assertRaises(ValueError):
            build_snapshot("2026-13", lambda model: {})


class ReviewProposalTests(unittest.TestCase):
    def test_proposal_is_scoped_and_never_overwrites(self):
        script = pathlib.Path("scripts/propose_open_weight_review.sh").resolve()
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            remote, repo, binaries = root / "origin.git", root / "repo", root / "bin"
            def git(*args, cwd=None):
                return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.STDOUT, text=True).strip()
            git("init", "--bare", str(remote))
            git("clone", str(remote), str(repo))
            git("config", "user.name", "Test", cwd=repo)
            git("config", "user.email", "test@example.invalid", cwd=repo)
            git("switch", "-c", "main", cwd=repo)
            (repo / "unrelated.txt").write_text("preserve me")
            git("add", ".", cwd=repo)
            git("commit", "-m", "initial", cwd=repo)
            git("push", "origin", "main", cwd=repo)
            main = git("rev-parse", "main", cwd=repo)
            # Simulate feature code that must never enter the generated PR.
            git("switch", "-c", "feature", cwd=repo)
            (repo / "feature.txt").write_text("not for the snapshot PR")
            git("add", ".", cwd=repo)
            git("commit", "-m", "feature", cwd=repo)
            (repo / "docs").mkdir()
            (repo / "docs/open-weight-models-monthly.json").write_text('{"review_month_utc":"2026-11","models":[]}')
            binaries.mkdir()
            fake_gh = binaries / "gh"
            fake_gh.write_text("""#!/usr/bin/env bash
set -eu
case "$1 $2" in
  'auth setup-git') exit 0 ;;
  'pr list') if test -f "$TEST_PR_STATE"; then echo 'https://example.invalid/review/1'; fi ;;
  'pr create') touch "$TEST_PR_STATE"; echo 'https://example.invalid/review/1' ;;
  *) exit 1 ;;
esac
""")
            fake_gh.chmod(0o755)
            env = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ["PATH"],
                       GH_TOKEN="secret-test-sentinel", GH_REPO="test/repo", TEST_PR_STATE=str(root / "pr"))
            def run():
                return subprocess.run(["bash", str(script)], cwd=repo, env=env, capture_output=True, text=True)
            first = run()
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            branch = "refs/heads/automation/open-weight-models-2026-11"
            head = git("--git-dir=" + str(remote), "rev-parse", branch)
            changed = git("--git-dir=" + str(remote), "diff", "--name-only", main, head)
            self.assertEqual(changed, "docs/open-weight-models-monthly.json")
            self.assertEqual(git("--git-dir=" + str(remote), "rev-parse", "main"), main)
            again = run()
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertIn("Existing monthly review PR retained", again.stdout)
            self.assertEqual(git("--git-dir=" + str(remote), "rev-parse", branch), head)
            (root / "pr").unlink()
            orphan = run()
            self.assertNotEqual(orphan.returncode, 0)
            self.assertIn("refusing to overwrite", orphan.stderr)
            self.assertEqual(git("--git-dir=" + str(remote), "rev-parse", branch), head)
            self.assertNotIn(env["GH_TOKEN"], first.stdout + first.stderr + again.stdout + again.stderr + orphan.stderr)
            # A merged, unchanged snapshot must be a no-op even though the old
            # monthly branch still exists and no open review PR remains.
            git("push", "origin", head + ":refs/heads/main", cwd=repo)
            unchanged = run()
            self.assertEqual(unchanged.returncode, 0, unchanged.stderr)
            self.assertIn("No metadata changes", unchanged.stdout)
            self.assertFalse((root / "pr").exists())
            self.assertEqual(git("--git-dir=" + str(remote), "rev-parse", branch), head)



if __name__ == "__main__":
    unittest.main()
