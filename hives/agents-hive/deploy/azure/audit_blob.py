#!/usr/bin/env python3
"""Copy hosted Patricia's audit log to an Azure Storage append blob, and check the copy.

The log is a hash chain (knowledge-hive's check_audit.py), and the blob is its anchor: it
sits in a container with a time-based immutability policy that allows protected append
writes, so the storage service refuses to change or delete a block once it is written,
even for the subscription's owner, until the retention period ends (docs/assurance-loop.md).

push appends whatever the local log has that the blob doesn't. It first reads the blob and
refuses unless the local log starts with exactly what the blob holds: a local log that
differs from its immutable copy was edited, cut short or rewritten, and pushing would hide
that. Each append is conditioned on the blob's length, so two writers can't interleave.

check reads the blob, verifies its chain, and compares it with a local log: the copy must
be a prefix of the log, and a log shorter than its copy was cut short.

Standard library only. The token comes from azure-identity's DefaultAzureCredential when it
is installed (the job's managed identity), else from `az account get-access-token`. The
account allows Entra auth only, so the identity needs Storage Blob Data Contributor to
push, or Reader to check.

Usage:
  python3 audit_blob.py push  LOG https://<account>.blob.core.windows.net/<container>/<blob>
  python3 audit_blob.py check LOG https://<account>.blob.core.windows.net/<container>/<blob>
"""
import argparse
import importlib.util
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

API_VERSION = "2023-11-03"
SCOPE = "https://storage.azure.com/.default"
BLOCK = 4 * 1024 * 1024  # the most one Append Block call takes in every API version
CHECK_AUDIT = Path(__file__).resolve().parents[3] / "knowledge-hive" / "scripts" / "check_audit.py"


class BlobError(Exception):
    pass


def token():
    try:
        from azure.identity import DefaultAzureCredential
    except ImportError:
        out = subprocess.run(["az", "account", "get-access-token", "--resource", "https://storage.azure.com/",
                              "--query", "accessToken", "-o", "tsv"], capture_output=True, text=True)
        if out.returncode != 0 or not out.stdout.strip():
            raise BlobError("can't get a storage token: sign in with az login")
        return out.stdout.strip()
    return DefaultAzureCredential().get_token(SCOPE).token


def http(method, url, headers, body=None):
    """(status, headers, body). An HTTP error status is returned, not raised."""
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


class Blob:
    def __init__(self, url, send=http, get_token=token):
        if not url.startswith("https://") or url.count("/") < 4:
            raise BlobError(f"{url} isn't an https URL of a blob: https://<account>.blob.core.windows.net/<container>/<blob>")
        self.url, self.send, self.get_token, self._token = url, send, get_token, None

    def call(self, method, query="", headers=None, body=None):
        self._token = self._token or self.get_token()
        h = {"Authorization": f"Bearer {self._token}", "x-ms-version": API_VERSION, **(headers or {})}
        if body is not None or method == "PUT":
            h["Content-Length"] = str(len(body or b""))
        return self.send(method, self.url + query, h, body)

    def read(self):
        """The blob's bytes, or None when it doesn't exist yet."""
        status, headers, body = self.call("GET")
        if status == 404:
            return None
        if status != 200:
            raise BlobError(f"reading {self.url} failed: HTTP {status} {error_code(headers, body)}")
        if headers.get("x-ms-blob-type", "AppendBlob") != "AppendBlob":
            raise BlobError(f"{self.url} is a {headers['x-ms-blob-type']}, not an append blob")
        return body

    def create(self):
        status, headers, body = self.call("PUT", headers={"x-ms-blob-type": "AppendBlob", "If-None-Match": "*",
                                                          "x-ms-blob-content-type": "application/x-ndjson"})
        if status not in (201, 409):  # 409: another writer created it first, which is fine
            raise BlobError(f"creating {self.url} failed: HTTP {status} {error_code(headers, body)}")

    def append(self, data, at):
        status, headers, body = self.call("PUT", "?comp=appendblock",
                                          {"x-ms-blob-condition-appendpos": str(at)}, data)
        if status == 412:
            raise BlobError(f"{self.url} grew while this was appending at byte {at}; another writer is "
                            "pushing, so run it again once that is done")
        if status != 201:
            raise BlobError(f"appending to {self.url} failed: HTTP {status} {error_code(headers, body)}")


def error_code(headers, body):
    code = headers.get("x-ms-error-code") or ""
    return f"({code})" if code else body[:200].decode("utf-8", "replace")


def blocks(data):
    """data cut into pieces of at most BLOCK bytes, each ending at a line's end where it can."""
    while data:
        piece = data[:BLOCK]
        if len(data) > BLOCK and b"\n" in piece:
            piece = piece[:piece.rindex(b"\n") + 1]
        yield piece
        data = data[len(piece):]


def push(log, blob):
    """Append what log has beyond the blob. Returns the number of bytes appended."""
    local = Path(log).read_bytes() if Path(log).exists() else b""
    if local and not local.endswith(b"\n"):
        raise BlobError(f"{log}'s last line is incomplete; a writer may still be appending")
    copy = blob.read()
    if copy is None:
        blob.create()
        copy = b""
    if not local.startswith(copy):
        raise BlobError(f"{log} doesn't start with what its immutable copy holds ({len(copy)} bytes): the "
                        "local log was edited, cut short or rewritten; compare them with check")
    at = len(copy)
    for piece in blocks(local[at:]):
        blob.append(piece, at)
        at += len(piece)
    return at - len(copy)


def check(log, blob):
    """Problems with the immutable copy, or with log against it; [] when they agree."""
    copy = blob.read()
    if copy is None:
        return [f"{blob.url} doesn't exist yet: nothing has been pushed"]
    spec = importlib.util.spec_from_file_location("check_audit", CHECK_AUDIT)
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    problems = audit.check_text(copy.decode("utf-8"), "the immutable copy")[0]
    local = Path(log).read_bytes() if Path(log).exists() else b""
    if not local.startswith(copy):
        lines, kept = copy.splitlines(), local.splitlines()
        n = next((i for i, (a, b) in enumerate(zip(lines, kept)) if a != b), min(len(lines), len(kept)))
        if n < len(kept):
            problems.append(f"{log}: entry {seq(lines[n])} differs from its immutable copy")
        else:
            problems.append(f"{log} ends at entry {seq(kept[-1]) if kept else 0}, but its immutable copy goes "
                            f"on to entry {seq(lines[-1])}: the log was cut short")
    return problems


def seq(line):
    try:
        return json.loads(line)["seq"]
    except (ValueError, KeyError, TypeError):
        return "?"


def main():
    ap = argparse.ArgumentParser(description="Copy an audit log to an immutable append blob, or check the copy.")
    ap.add_argument("command", choices=("push", "check"))
    ap.add_argument("log", help="the local audit.jsonl")
    ap.add_argument("url", help="https://<account>.blob.core.windows.net/<container>/<blob>")
    args = ap.parse_args()
    try:
        blob = Blob(args.url)
        if args.command == "push":
            n = push(args.log, blob)
            print(f"appended {n} bytes to {args.url}" if n else f"{args.url} already holds all of {args.log}")
            return 0
        problems = check(args.log, blob)
    except BlobError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for p in problems:
        print(p, file=sys.stderr)
    if not problems:
        print(f"{args.url} is a valid chain, and {args.log} starts with it")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
