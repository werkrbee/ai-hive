#!/usr/bin/env python3
"""Check an audit log (audit.jsonl) against the format in DESIGN.md, and append to one.

An audit log is append-only and hash-chained. Each entry's hash is the SHA-256 of the
entry without its hash, as canonical JSON, and each entry's prev is the hash before it,
so an entry that was edited, removed, inserted or moved breaks the chain where it was
changed. This reports the first place the chain breaks, and every entry whose fields
don't fit the format. Given the run records (--runs), it also catches a log that ends
before a run's last entry, which a chain alone can't show.

The workflows-hive engine writes the log through append(), so the writer and this checker
share one definition of the format.

Standard library only.

Usage:
  python3 scripts/check_audit.py path/to/audit.jsonl
  python3 scripts/check_audit.py path/to/audit.jsonl --runs ~/.local/state/workflows-hive/runs
"""
import argparse
import contextlib
import datetime
import hashlib
import json
import os
import re
import sys
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None
    import msvcrt

GENESIS = "sha256:" + "0" * 64
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
KEBAB = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
ACTOR = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/+-]{0,127}")

# Each kind, and the fields it needs beyond seq, at, prev, hash and kind.
KINDS = {
    "run.started": ("runId",),
    "run.completed": ("runId",),
    "run.failed": ("runId",),
    "run.cancelled": ("runId", "by"),
    "run.expired": ("runId",),
    "step.decided": ("runId", "step", "decision"),
    "step.ran": ("runId", "step"),
    "step.failed": ("runId", "step"),
    "budget.refused": ("runId", "step"),
    "approval.answered": ("runId", "step", "decision", "by"),
    "escalation.raised": ("runId", "item"),
    "escalation.answered": ("runId", "item", "by", "via"),
    "drift.answered": ("item", "decision", "by", "via"),
    "turn.completed": ("runId", "turn"),
    "turn.failed": ("runId", "turn"),
    "delegation": (),
    "rollback": (),
    "drift": ("agent", "item"),
    "eval.ran": ("agent", "result"),
    "eval.flagged": ("agent", "item"),
}
DECISIONS = {"step.decided": {"allowed", "paused", "denied"}, "approval.answered": {"approved", "denied"},
             "drift.answered": {"approved", "denied"}}
FIELDS = {"seq", "at", "prev", "hash", "kind", "agent", "runId", "step", "turn", "action",
          "decision", "rules", "call", "by", "item", "via", "result"}
VIA = ("cli", "mcp", "a2a")  # how a human's answer came


class AuditError(Exception):
    """An entry the log won't take, or a log that can't be appended to."""


def canonical(obj):
    """Canonical JSON: keys sorted, no insignificant whitespace, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(obj):
    return "sha256:" + hashlib.sha256(canonical(obj)).hexdigest()


def entry_hash(entry):
    """An entry's hash: the digest of the entry without its hash."""
    return digest({k: v for k, v in entry.items() if k != "hash"})


def opaque(by):
    """Whether by can identify a person in the log: an opaque ID, not a name or an email."""
    return isinstance(by, str) and bool(ACTOR.fullmatch(by)) and not EMAIL.fullmatch(by)


def utc(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z", value):
        return False
    try:
        datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def entry_problems(e):
    """What is wrong with one entry's fields, apart from the chain."""
    problems = []
    bad = problems.append
    for key in sorted(set(e) - FIELDS):
        bad(f"unknown field '{key}'")
    kind = e.get("kind")
    if kind not in KINDS:
        bad(f"kind must be one of {', '.join(KINDS)}")
    for key in ("seq", "at", "prev", "hash", "kind") + KINDS.get(kind, ()):
        if key not in e:
            bad(f"missing '{key}'")
    if "seq" in e and (not isinstance(e["seq"], int) or isinstance(e["seq"], bool) or e["seq"] < 1):
        bad("seq must be an integer of at least 1")
    if "at" in e and not utc(e["at"]):
        bad("at must be an ISO 8601 date-time in UTC")
    for key in ("prev", "hash", "call", "item"):
        if key in e and not (isinstance(e[key], str) and DIGEST.fullmatch(e[key])):
            bad(f"{key} must be sha256: followed by 64 lowercase hex digits")
    for key in ("runId", "step", "turn", "action", "result"):
        if key in e and (not isinstance(e[key], str) or not e[key]):
            bad(f"{key} must be a non-empty string")
    if "decision" in e and e["decision"] not in DECISIONS.get(kind, ()):
        allowed = DECISIONS.get(kind)
        bad(f"decision must be one of {', '.join(sorted(allowed))}" if allowed else f"a {kind} entry has no decision")
    if "rules" in e and (not isinstance(e["rules"], list) or not all(isinstance(r, str) and r for r in e["rules"])):
        bad("rules must be a list of rule ids")
    if "via" in e and e["via"] not in VIA:
        bad(f"via must be one of {', '.join(VIA)}")
    if "by" in e and not opaque(e["by"]):
        bad("by must be an opaque identifier, never a name or an email address")
    if "agent" in e:
        a = e["agent"]
        if (not isinstance(a, dict) or set(a) != {"passport", "version", "sha256"}
                or not isinstance(a["passport"], str) or not KEBAB.fullmatch(a["passport"])
                or not isinstance(a["version"], int) or isinstance(a["version"], bool) or a["version"] < 1
                or not isinstance(a["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", a["sha256"])):
            bad("agent must be {passport, version, sha256}: a passport's name, version and digest")
    return problems


def lines(text, name, err):
    """Yield (line number, entry) for each line, reporting lines that aren't objects."""
    if text and not text.endswith("\n"):
        err(f"{name}: must end with a newline (the last entry may have been cut off as it was written)")
    for n, line in enumerate(text.split("\n")[:-1] if text else [], start=1):
        try:
            obj = json.loads(line)
        except ValueError as e:
            err(f"{name}:{n}: not valid JSON ({e})")
            yield n, None
            continue
        if not isinstance(obj, dict):
            err(f"{name}:{n}: each line must be a JSON object")
            obj = None
        yield n, obj


def check_text(text, name="audit.jsonl"):
    """Problems in a log's text, and {seq: hash} for the entries before the chain first breaks."""
    errors = []
    err = errors.append
    chain, prev, broken = {}, GENESIS, False
    for n, e in lines(text, name, err):
        if e is None:
            broken = True
            continue
        for p in entry_problems(e):
            err(f"{name}:{n}: {p}")
        if broken:
            continue
        seq, want = e.get("seq"), len(chain) + 1
        if e.get("hash") != entry_hash(e):
            err(f"{name}:{n}: entry {seq} was edited: its hash doesn't match its contents")
        elif seq != want:
            if isinstance(seq, int) and seq > want:
                err(f"{name}:{n}: entry {want} is missing: seq jumps from {want - 1} to {seq} "
                    "(an entry was removed, or entries were reordered)")
            else:
                err(f"{name}:{n}: entry {seq} comes after entry {want - 1} "
                    "(an entry was inserted, or entries were reordered)")
        elif e.get("prev") != prev:
            before = "the genesis value" if seq == 1 else f"entry {seq - 1}'s hash"
            err(f"{name}:{n}: entry {seq}'s prev isn't {before} "
                f"({'that entry was replaced, or this one was inserted' if seq > 1 else 'entries before it were removed'})")
        else:
            chain[seq] = prev = e["hash"]
            continue
        broken = True  # report the first break only; everything after it is suspect
    return errors, chain


def check_runs(chain, runs, name="audit.jsonl"):
    """Problems with the log's end, from each run record's anchor: the seq and hash of the
    last entry written for that run."""
    errors = []
    last = max(chain, default=0)
    for path in sorted(Path(runs).glob("*.json")):
        try:
            run = json.loads(path.read_text())
        except (OSError, ValueError):
            errors.append(f"{path.name}: not a readable run record")
            continue
        anchor = run.get("audit") if isinstance(run, dict) else None
        if anchor is None:
            continue
        seq, h = (anchor.get("seq"), anchor.get("hash")) if isinstance(anchor, dict) else (None, None)
        if not isinstance(seq, int) or isinstance(seq, bool) or not isinstance(h, str):
            errors.append(f"{path.name}: audit must be {{seq, hash}}")
        elif seq > last:
            errors.append(f"{name}: ends at entry {last}, before run {run.get('runId')}'s last entry {seq}; "
                          "the log was cut short")
        elif chain[seq] != h:
            errors.append(f"{name}: entry {seq} isn't the one run {run.get('runId')} recorded; "
                          "the log was rewritten")
    return errors


def check(path, runs=None):
    """All problems in the audit log at path, and its end against the run records in runs."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return [f"{path.name}: can't be read ({e})"]
    errors, chain = check_text(text, path.name)
    if runs is not None and not errors:
        errors += check_runs(chain, runs, path.name)
    return errors


@contextlib.contextmanager
def locked(f):
    """Hold an exclusive lock on the open log, so two processes can't both append entry n."""
    if fcntl:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
    else:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
    try:
        yield
    finally:
        if fcntl:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        else:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)


def last_entry(f):
    """The log's last entry, read from its end, or None for an empty log."""
    f.seek(0, os.SEEK_END)
    pos = end = f.tell()
    if end == 0:
        return None
    tail = b""
    while pos > 0 and tail.count(b"\n") < 2:
        step = min(4096, pos)
        pos -= step
        f.seek(pos)
        tail = f.read(step) + tail
    if not tail.endswith(b"\n"):
        raise AuditError("its last line is incomplete; check it with check_audit.py before writing more")
    try:
        entry = json.loads(tail[:-1].rsplit(b"\n", 1)[-1])
        return {"seq": int(entry["seq"]), "hash": str(entry["hash"])}
    except (ValueError, KeyError, TypeError):
        raise AuditError("its last line isn't an entry; check it with check_audit.py before writing more") from None


def append(path, fields):
    """Append an entry with fields (kind and the rest) to the log at path, numbered and
    chained after its last entry, and flushed to disk. Returns the entry as written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+b") as f, locked(f):
        last = last_entry(f)
        entry = {"seq": last["seq"] + 1 if last else 1,
                 "at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "prev": last["hash"] if last else GENESIS}
        entry.update(fields)
        entry["hash"] = entry_hash(entry)
        problems = entry_problems(entry)
        if problems:
            raise AuditError(f"a {fields.get('kind')} entry {problems[0]}")
        f.seek(0, os.SEEK_END)
        f.write(json.dumps(entry, ensure_ascii=False).encode("utf-8") + b"\n")
        f.flush()
        os.fsync(f.fileno())
    return entry


def main():
    ap = argparse.ArgumentParser(description="Check an audit log's chain and format.")
    ap.add_argument("log", help="The audit.jsonl to check")
    ap.add_argument("--runs", metavar="DIR",
                    help="Run records to check the log's end against (workflows-hive's --state-dir)")
    args = ap.parse_args()
    errors = check(args.log, args.runs)
    for e in errors:
        print(f"FAIL  {e}")
    if not errors:
        print(f"OK  {args.log}: the chain is whole" + (", and no run's last entry is missing" if args.runs else ""))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
