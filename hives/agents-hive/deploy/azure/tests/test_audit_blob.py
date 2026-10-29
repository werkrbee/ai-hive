"""Tests for audit_blob.py against a fake Blob service: an append blob that only grows.

Standard library only. Run from the repo root:
  python3 -B -m unittest discover -s hives/agents-hive/deploy/azure/tests -p 'test_*.py'
"""
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ab = load(HERE.parent / "audit_blob.py", "audit_blob")
audit = load(ab.CHECK_AUDIT, "check_audit")
URL = "https://patricialogabc.blob.core.windows.net/audit/patricia.jsonl"


class Service:
    """One append blob, as the storage service keeps it under a time-based immutability
    policy with protected append writes: it can be created and appended to, and nothing
    else."""

    def __init__(self):
        self.data, self.calls = None, []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url.removeprefix(URL), dict(headers)))
        assert headers["Authorization"] == "Bearer t0k" and headers["x-ms-version"] == ab.API_VERSION
        if method == "GET":
            if self.data is None:
                return 404, {"x-ms-error-code": "BlobNotFound"}, b""
            return 200, {"x-ms-blob-type": "AppendBlob"}, self.data
        if method == "PUT" and url == URL:
            assert headers["x-ms-blob-type"] == "AppendBlob" and headers["If-None-Match"] == "*"
            if self.data is not None:
                return 409, {"x-ms-error-code": "BlobAlreadyExists"}, b""
            self.data = b""
            return 201, {}, b""
        if method == "PUT" and url == URL + "?comp=appendblock":
            if int(headers["x-ms-blob-condition-appendpos"]) != len(self.data):
                return 412, {"x-ms-error-code": "AppendPositionConditionNotMet"}, b""
            assert int(headers["Content-Length"]) == len(body) <= ab.BLOCK
            self.data += body
            return 201, {}, b""
        return 403, {"x-ms-error-code": "OperationNotAllowedOnImmutableBlob"}, b""


class Blob(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.log = self.tmp / "audit.jsonl"
        self.service = Service()
        self.blob = ab.Blob(URL, send=self.service, get_token=lambda: "t0k")

    def write(self, n):
        for _ in range(n):
            audit.append(self.log, {"kind": "run.started", "runId": "run_1"})

    def appends(self):
        return [c for c in self.service.calls if c[1] == "?comp=appendblock"]

    def test_the_first_push_creates_the_blob_and_copies_the_log(self):
        self.write(3)
        self.assertEqual(ab.push(self.log, self.blob), len(self.log.read_bytes()))
        self.assertEqual(self.service.data, self.log.read_bytes())
        self.assertEqual(ab.check(self.log, self.blob), [])

    def test_a_later_push_appends_only_what_is_new_at_the_blobs_end(self):
        self.write(2)
        ab.push(self.log, self.blob)
        before = len(self.service.data)
        self.write(2)
        ab.push(self.log, self.blob)
        self.assertEqual(self.appends()[-1][2]["x-ms-blob-condition-appendpos"], str(before))
        self.assertEqual(self.service.data, self.log.read_bytes())
        self.assertEqual(ab.push(self.log, self.blob), 0)

    def test_an_edited_local_log_is_refused_and_check_names_the_entry(self):
        self.write(3)
        ab.push(self.log, self.blob)
        lines = self.log.read_text().splitlines()
        lines[1] = lines[1].replace("run_1", "run_9")
        self.log.write_text("".join(line + "\n" for line in lines))
        with self.assertRaisesRegex(ab.BlobError, "doesn't start with what its immutable copy holds"):
            ab.push(self.log, self.blob)
        self.assertEqual(ab.check(self.log, self.blob), [f"{self.log}: entry 2 differs from its immutable copy"])

    def test_a_log_cut_short_is_refused_and_check_says_so(self):
        self.write(3)
        ab.push(self.log, self.blob)
        self.log.write_text("".join(line + "\n" for line in self.log.read_text().splitlines()[:1]))
        with self.assertRaises(ab.BlobError):
            ab.push(self.log, self.blob)
        self.assertEqual(ab.check(self.log, self.blob),
                         [f"{self.log} ends at entry 1, but its immutable copy goes on to entry 3: the log was cut short"])

    def test_check_verifies_the_copys_own_chain(self):
        self.write(2)
        ab.push(self.log, self.blob)
        entry = json.loads(self.service.data.splitlines()[0])
        entry["runId"] = "run_9"
        self.service.data = json.dumps(entry).encode() + b"\n" + self.service.data.split(b"\n", 1)[1]
        problems = ab.check(self.log, self.blob)
        self.assertTrue(any("the immutable copy:1: entry 1 was edited" in p for p in problems), problems)

    def test_another_writer_appending_first_stops_the_push(self):
        self.write(1)
        ab.push(self.log, self.blob)
        self.write(1)
        real = self.service

        def racing(method, url, headers, body):
            if url.endswith("?comp=appendblock"):
                real.data += b"x"
            return real(method, url, headers, body)
        blob = ab.Blob(URL, send=racing, get_token=lambda: "t0k")
        with self.assertRaisesRegex(ab.BlobError, "grew while this was appending"):
            ab.push(self.log, blob)

    def test_a_large_log_goes_in_blocks_that_end_at_a_line(self):
        line = b'{"x": "' + b"a" * 1000 + b'"}\n'
        data = line * (ab.BLOCK // len(line) + 5)
        pieces = list(ab.blocks(data))
        self.assertEqual(b"".join(pieces), data)
        self.assertTrue(all(len(p) <= ab.BLOCK and p.endswith(b"\n") for p in pieces))
        self.assertEqual(len(pieces), 2)

    def test_a_half_written_last_line_is_not_pushed(self):
        self.write(1)
        self.log.write_bytes(self.log.read_bytes() + b'{"seq": 2')
        with self.assertRaisesRegex(ab.BlobError, "last line is incomplete"):
            ab.push(self.log, self.blob)
        self.assertIsNone(self.service.data)

    def test_an_empty_log_creates_the_blob_and_appends_nothing(self):
        self.assertEqual(ab.push(self.log, self.blob), 0)
        self.assertEqual(self.service.data, b"")
        self.assertEqual(self.appends(), [])

    def test_a_url_that_isnt_a_blob_is_refused(self):
        for url in ("http://a.blob.core.windows.net/c/b", "https://a.blob.core.windows.net/c"):
            with self.subTest(url), self.assertRaises(ab.BlobError):
                ab.Blob(url)


if __name__ == "__main__":
    unittest.main()
