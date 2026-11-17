"""Offline unit tests for the monthly open-weight metadata collector."""
import io
import copy
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch
from scripts.update_open_weight_models import MODELS, build_snapshot, fetch_model, main


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.close()


def api_metadata(model):
    return {"id": model, "sha": "a" * 40, "gated": False, "siblings": []}


def malformed_metadata(model):
    cases = [("response", value) for value in (None, [], False, 42, "not an object")]
    missing = object()
    fields = {
        "id": [missing, None, 42, "unexpected/model"],
        "sha": [missing, None, "", "main", "abc123", "z" * 40, "a" * 41, 42, True, {}],
        "gated": [missing, None, True, 0, 1, "false", "unknown", {}, []],
        "cardData": [[], False, "", 0],
        "tags": [None, {}, False, "tag", [None], [False], [""], ["license:"]],
        "siblings": [missing, None, False, {}, "files", [None], [{}]],
        "lastModified": ["", 42, [], "not-a-date", "2026-01-01", "2026-01-01T12:00:00"],
    }
    for field, values in fields.items():
        for value in values:
            item = api_metadata(model)
            if value is missing:
                item.pop(field)
            else:
                item[field] = value
            cases.append((field, item))
    for field in ("license", "license_name", "license_link"):
        for value in ({"unexpected": True}, [], False, 42, "", "   "):
            item = api_metadata(model)
            item["cardData"] = {field: value}
            cases.append(("cardData." + field, item))
    for name in (None, False, 42, "", "/model.bin", "../model.bin", "a/../model.bin",
                 "a//model.bin", "./model.bin", "a\\model.bin", "model\n.bin"):
        item = api_metadata(model)
        item["siblings"] = [{"rfilename": name}]
        cases.append(("siblings[0].rfilename", item))
    return cases


class ModelTrackerTests(unittest.TestCase):
    def test_license_tag_and_gating(self):
        model = MODELS[0]
        def opener(request, timeout):
            self.assertEqual(timeout, 25)
            self.assertIn(model, request.full_url)
            return FakeResponse(json.dumps({
                **api_metadata(model),
                "id": model, "tags": ["license:llama3.1"],
                "gated": "manual", "lastModified": "2026-11-01T00:00:00Z"
            }).encode())
        row = fetch_model(model, opener)
        self.assertEqual(row["license_tag_unverified"], "llama3.1")
        self.assertEqual(row["gated"], "manual")

    def test_custom_license_and_revision_pinned_download(self):
        def opener(request, timeout):
            return FakeResponse(json.dumps({
                **api_metadata(MODELS[-1]),
                "cardData": {"license": "other", "license_name": "nvidia-open-model-license",
                             "license_link": "https://www.nvidia.com/license"},
                "siblings": [{"rfilename": "model.safetensors"}]
            }).encode())
        row = fetch_model(MODELS[-1], opener)
        self.assertEqual(row["license_name_unverified"], "nvidia-open-model-license")
        self.assertEqual(row["license_link_unverified"], "https://www.nvidia.com/license")
        self.assertEqual(row["weight_file_count"], 1)
        self.assertEqual(row["example_weight_download"],
                         "https://huggingface.co/" + MODELS[-1] + "/resolve/" + "a" * 40 + "/model.safetensors")

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

    def test_invalid_metadata_identifies_model_and_field(self):
        for field, item in malformed_metadata(MODELS[0]):
            with self.subTest(field=field, item=item):
                with self.assertRaises(ValueError) as caught:
                    fetch_model(MODELS[0], lambda *a, **k: FakeResponse(json.dumps(item).encode()))
                self.assertIn(MODELS[0], str(caught.exception))
                self.assertIn(field, str(caught.exception))

    def test_late_invalid_metadata_preserves_previous_snapshot(self):
        for field, item in malformed_metadata(MODELS[1]):
            with self.subTest(field=field, item=item), tempfile.TemporaryDirectory() as temporary:
                output = pathlib.Path(temporary) / "snapshot.json"
                previous = b'{"review_month_utc":"2026-11","models":[]}\n'
                output.write_bytes(previous)
                calls = []
                def opener(request, timeout):
                    calls.append(request.full_url)
                    payload = api_metadata(MODELS[0]) if len(calls) == 1 else item
                    return FakeResponse(json.dumps(payload).encode())
                with patch.object(fetch_model, "__defaults__", (opener,)), patch(
                    "sys.argv", ["collector", "--month", "2026-11", "--output", str(output)]
                ):
                    with self.assertRaises(ValueError) as caught:
                        main()
                self.assertIn(MODELS[1], str(caught.exception))
                self.assertIn(field, str(caught.exception))
                self.assertEqual(len(calls), 2)
                self.assertEqual(output.read_bytes(), previous)

    def test_optional_metadata_and_reported_gating_are_preserved(self):
        for gated in (False, "auto", "manual"):
            item = {**api_metadata(MODELS[0]), "gated": gated,
                    "cardData": None, "lastModified": None}
            row = fetch_model(MODELS[0], lambda *a, **k: FakeResponse(json.dumps(item).encode()))
            self.assertEqual(row["gated"], gated)
            self.assertIsNone(row["license_tag_unverified"])
            self.assertIsNone(row["license_link_unverified"])

    def test_full_revisions_pin_encoded_download_paths(self):
        for revision in ("a" * 40, "b" * 64):
            item = {**api_metadata(MODELS[0]), "sha": revision,
                    "siblings": [{"rfilename": "subdir/model #1.safetensors"}]}
            row = fetch_model(MODELS[0], lambda *a, **k: FakeResponse(json.dumps(item).encode()))
            self.assertEqual(row["example_weight_download"], "https://huggingface.co/" +
                             MODELS[0] + "/resolve/" + revision + "/subdir/model%20%231.safetensors")
            self.assertEqual(row["upstream_revision"], revision)

    def test_invalid_json_identifies_source(self):
        for body in (b"not-json", b"\xff"):
            with self.assertRaisesRegex(ValueError, "response is not valid JSON") as caught:
                fetch_model(MODELS[0], lambda *a, **k: FakeResponse(body))
            self.assertIn(MODELS[0], str(caught.exception))

    def test_invalid_response_cli_fails_without_dumping_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = pathlib.Path(temporary) / "snapshot.json"
            output.write_bytes(b"previous reviewed snapshot\n")
            code = (
                "import io,json; from scripts import update_open_weight_models as m; "
                "payload={'id':m.MODELS[0],'sha':'a'*40,'gated':False,'siblings':[],"
                "'cardData':{'license':{'SENSITIVE_PAYLOAD_SENTINEL':True}}}; "
                "m.fetch_model.__defaults__=(lambda *a,**k:io.BytesIO(json.dumps(payload).encode()),); "
                "m.main()"
            )
            result = subprocess.run([sys.executable, "-c", code, "--month", "2026-11",
                                     "--output", str(output)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(MODELS[0], result.stderr)
            self.assertIn("cardData.license", result.stderr)
            self.assertNotIn("SENSITIVE_PAYLOAD_SENTINEL", result.stderr)
            self.assertEqual(output.read_bytes(), b"previous reviewed snapshot\n")

    def test_late_upstream_failures_preserve_previous_snapshot(self):
        errors = [urllib.error.HTTPError("https://huggingface.co/api/models/example", 503,
                                        "unavailable", {}, None),
                  urllib.error.URLError("timeout"),
                  json.JSONDecodeError("invalid JSON", "not-json", 0)]
        for error in errors:
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as temporary:
                output = pathlib.Path(temporary) / "snapshot.json"
                output.write_bytes(b"previous reviewed snapshot\n")
                calls = []
                def opener(request, timeout):
                    calls.append(request.full_url)
                    if len(calls) == 2:
                        raise error
                    return FakeResponse(json.dumps(api_metadata(MODELS[0])).encode())
                with patch.object(fetch_model, "__defaults__", (opener,)), patch(
                    "sys.argv", ["collector", "--month", "2026-11", "--output", str(output)]
                ):
                    expected = ValueError if isinstance(error, json.JSONDecodeError) else type(error)
                    with self.assertRaises(expected):
                        main()
                self.assertEqual(len(calls), 2)
                self.assertEqual(output.read_bytes(), b"previous reviewed snapshot\n")


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
            legacy = "refs/heads/automation/open-weight-models-2026-11"
            git("push", "origin", main + ":" + legacy, cwd=repo)
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
  'pr create') touch "$TEST_PR_STATE"; echo created >> "$TEST_PR_CALLS"; echo 'https://example.invalid/review/1' ;;
  *) exit 1 ;;
esac
""")
            fake_gh.chmod(0o755)
            env = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ["PATH"],
                       GH_TOKEN="secret-test-sentinel", GH_REPO="test/repo", TEST_PR_STATE=str(root / "pr"), TEST_PR_CALLS=str(root / "calls"))
            def run():
                return subprocess.run(["bash", str(script)], cwd=repo, env=env, capture_output=True, text=True)
            first = run()
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            digest = hashlib.sha256((repo / "docs/open-weight-models-monthly.json").read_bytes()).hexdigest()
            branch = "refs/heads/automation/open-weight-models-2026-11-" + digest
            head = git("--git-dir=" + str(remote), "rev-parse", branch)
            changed = git("--git-dir=" + str(remote), "diff", "--name-only", main, head)
            self.assertEqual(changed, "docs/open-weight-models-monthly.json")
            self.assertEqual(git("--git-dir=" + str(remote), "rev-parse", "main"), main)
            again = run()
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertIn("Existing monthly review PR retained", again.stdout)
            self.assertEqual(git("--git-dir=" + str(remote), "rev-parse", branch), head)
            snapshot = repo / "docs/open-weight-models-monthly.json"
            original = snapshot.read_bytes()
            # A newer snapshot while the first PR is open gets its own review.
            snapshot.write_text('{"review_month_utc":"2026-11","models":[{"gated":false}]}')
            newer_open = run()
            self.assertEqual(newer_open.returncode, 0, newer_open.stderr)
            self.assertEqual((root / "calls").read_text().splitlines(), ["created", "created"])
            self.assertEqual(git("--git-dir=" + str(remote), "rev-parse", branch), head)
            self.assertEqual(run().returncode, 0)
            self.assertEqual((root / "calls").read_text().splitlines(), ["created", "created"])
            snapshot.write_bytes(original)
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
            # Upstream changes again after the month's first review merged.
            snapshot = repo / "docs/open-weight-models-monthly.json"
            snapshot.write_text('{"review_month_utc":"2026-11","models":[{"gated":"manual"}]}')
            followup = run()
            self.assertEqual(followup.returncode, 0, followup.stdout + followup.stderr)
            self.assertTrue((root / "pr").exists())
            self.assertEqual(git("--git-dir=" + str(remote), "rev-parse", branch), head)
            new_digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
            followup_branch = "refs/heads/automation/open-weight-models-2026-11-" + new_digest
            followup_head = git("--git-dir=" + str(remote), "rev-parse", followup_branch)
            self.assertNotEqual(followup_head, head)
            self.assertEqual(git("--git-dir=" + str(remote), "diff", "--name-only", head, followup_head),
                             "docs/open-weight-models-monthly.json")
            self.assertEqual(git("--git-dir=" + str(remote), "rev-parse", "main"), head)
            self.assertEqual(run().returncode, 0)
            self.assertEqual(git("--git-dir=" + str(remote), "rev-parse", followup_branch), followup_head)
            self.assertEqual((root / "calls").read_text().splitlines(), ["created"] * 3)
            self.assertEqual(git("--git-dir=" + str(remote), "rev-parse", legacy), main)





if __name__ == "__main__":
    unittest.main()
