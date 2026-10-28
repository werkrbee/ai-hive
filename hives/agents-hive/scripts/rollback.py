#!/usr/bin/env python3
"""Roll an agent back to an earlier passport version (docs/assurance-loop.md, "Rollback").

A passport's history is its git history, so rolling an agent back is deploying the commit
at which its passport was that version, with the model, prompt files and policy it pins.
deploy.sh --rollback uses this script twice. plan finds the newest commit before the
checked-out one at which the passport was VERSION, and prints it with the model that
passport pins, for deploy.sh to check against the model catalog and the parameters, and
warns of any findings recorded since against that passport's pins, which the promotion
check at that commit can't see. record, once the deploy is done, writes a rollback record
beside the audit log, with who rolled the agent back and why, and a rollback entry to the
log naming the record's digest, since the log itself holds no free text.

Standard library only.

Usage:
  python3 rollback.py plan PERSONA VERSION --by ACTOR-ID --reason TEXT
  python3 rollback.py record PERSONA COMMIT --by ACTOR-ID --reason TEXT [--audit PATH]
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
# The workflows-hive engine's audit log, by default (its state directory's parent).
DEFAULT_AUDIT = Path("~/.local/state/workflows-hive/audit.jsonl")


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_audit = load(REPO_ROOT / "hives" / "knowledge-hive" / "scripts" / "check_audit.py", "check_audit")


class RollbackError(Exception):
    """A rollback that can't go ahead. The command line prints it and exits 1."""


def git(*args):
    done = subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True)
    if done.returncode:
        raise RollbackError(f"git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout.strip()


def passport_path(persona):
    return f"hives/agents-hive/passports/{persona}/passport.json"


def passport_at(commit, persona):
    """The persona's passport as it was at commit."""
    return json.loads(git("show", f"{commit}:{passport_path(persona)}"))


def digest(passport):
    """The passport's SHA-256 over its canonical JSON, as validate_passports.digest gives it."""
    return hashlib.sha256(check_audit.canonical(passport)).hexdigest()


def find(persona, version):
    """The newest commit before HEAD at which the persona's passport was version, and that
    passport. Versions only go up, so it is the parent of the commit that moved past it."""
    current = passport_at("HEAD", persona)
    if not isinstance(version, int) or not 1 <= version < current["version"]:
        raise RollbackError(f"passport {persona} is version {current['version']}; "
                            "roll it back to an earlier version")
    changes = git("rev-list", "--first-parent", "HEAD", "--", passport_path(persona)).split()
    for newer, commit in zip(changes, changes[1:]):
        if passport_at(commit, persona)["version"] == version:
            target = git("rev-parse", f"{newer}^")
            return target, passport_at(target, persona)
    raise RollbackError(f"passport {persona} was never version {version} in this checkout's history")


def results_at(commit, path):
    """The entries of the results.jsonl at path as it was at commit, by id, or {} when it
    didn't exist then."""
    try:
        text = git("show", f"{commit}:{path}")
    except RollbackError:
        return {}
    found = {}
    for line in text.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and isinstance(entry.get("id"), str):
            found[entry["id"]] = entry
    return found


def newer_findings(persona, commit):
    """The results recorded since commit that found something against the pins of the
    persona's passport at commit, as "ID (FINDINGS)". The promotion check at commit reads
    the results file as it was then, so it can't see them."""
    then = passport_at(commit, persona)
    ref = ((then.get("eval") or {}).get("baseline") or {}).get("result")
    if not isinstance(ref, str) or "pins" not in then:
        return []
    path = ref.split("#", 1)[0]
    pins = "sha256:" + hashlib.sha256(check_audit.canonical(then["pins"])).hexdigest()
    recorded = results_at(commit, path)
    found = []
    for rid, entry in results_at("HEAD", path).items():
        ev = entry.get("eval") or {}
        if rid not in recorded and ev.get("passport") == persona and ev.get("pins") == pins \
                and ev.get("findings"):
            found.append(f"{rid} ({', '.join(map(str, ev['findings']))})")
    return found


def check_reason(by, reason):
    if not check_audit.opaque(by):
        raise RollbackError(f"{by!r} isn't an actor ID: use an opaque identifier, never a name or email "
                            "(--by, or WORKFLOWS_HIVE_ACTOR)")
    if not isinstance(reason, str) or not reason.strip():
        raise RollbackError("a rollback needs a reason")


def plan(persona, version, by, reason):
    """The commit to deploy and the model its passport pins, as "COMMIT NAME VERSION"."""
    check_reason(by, reason)
    commit, passport = find(persona, version)
    model = passport.get("pins", {}).get("model")
    if not model:
        raise RollbackError(f"passport {persona} v{version} pins no model, so it can't be deployed")
    return f"{commit} {model['name']} {model['version']}"


def record(persona, commit, by, reason, audit=DEFAULT_AUDIT, via="cli"):
    """Record that persona was rolled back to its passport at commit: the record, beside the
    audit log, and the log's rollback entry. Returns (the entry, the record's path)."""
    check_reason(by, reason)
    head = git("rev-parse", "HEAD")
    commit = git("rev-parse", commit)
    before, after = passport_at(head, persona), passport_at(commit, persona)
    rec = {"passport": persona,
           "from": {"version": before["version"], "sha256": digest(before), "commit": head},
           "to": {"version": after["version"], "sha256": digest(after), "commit": commit},
           "by": by, "via": via, "reason": reason,
           "at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    rec_id = check_audit.digest(rec)
    audit = Path(audit).expanduser()
    path = audit.parent / "rollbacks" / f"{rec_id.split(':', 1)[1]}.json"
    agent = {"passport": persona, "version": after["version"], "sha256": rec["to"]["sha256"]}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rec, indent=2) + "\n")  # the record exists before the log names it
        entry = check_audit.append(audit, {"kind": "rollback", "agent": agent, "by": by, "via": via, "record": rec_id})
    except (check_audit.AuditError, OSError) as e:
        raise RollbackError(f"audit log {audit}: {e}") from None
    return entry, path


def main():
    ap = argparse.ArgumentParser(description="Roll an agent back to an earlier passport version.")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan", help="Print the commit to deploy and the model its passport pins")
    p.add_argument("persona")
    p.add_argument("version", type=int)
    r = sub.add_parser("record", help="Record a rollback that has been deployed")
    r.add_argument("persona")
    r.add_argument("commit")
    r.add_argument("--audit", default=str(DEFAULT_AUDIT), help="The audit log (default: the engine's)")
    for q in (p, r):
        q.add_argument("--by", required=True, metavar="ACTOR-ID", help="Who rolled it back, as an opaque ID")
        q.add_argument("--reason", required=True, help="Why, kept in the rollback record")
    args = ap.parse_args()
    try:
        if args.command == "plan":
            planned = plan(args.persona, args.version, args.by, args.reason)
            later = newer_findings(args.persona, planned.split()[0])
            if later:
                print(f"warning: since that commit, evaluations of passport {args.persona} v{args.version}'s "
                      f"pins found: {'; '.join(later)}. Its promotion check reads only the results "
                      "recorded then, so it doesn't see them.", file=sys.stderr)
            print(planned)
        else:
            entry, path = record(args.persona, args.commit, args.by, args.reason, args.audit)
            print(f"recorded: {args.persona} rolled back to v{entry['agent']['version']}, entry {entry['seq']} "
                  f"of {Path(args.audit).expanduser()}, record {path}")
    except RollbackError as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
