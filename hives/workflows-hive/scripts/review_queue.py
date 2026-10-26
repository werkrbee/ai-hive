#!/usr/bin/env python3
"""Read and answer the review queue: everything that needs a person, across runs and agents.

The queue holds three kinds of item. An approval is a step a run paused on, an escalation
is a question an agent's run asked a person, and drift is the trust evaluation finding an
agent below its baseline. Each is a JSON file in the queue directory. The run record stays
the source of truth for an approval or an escalation, so answering one answers its run,
through the engine in run.py.

A person answers the queue; an agent never does. So this refuses to answer when it isn't
attached to an interactive terminal, or when it runs inside an engine run. That isn't a
lock: on one machine an agent with a shell can get around both, so each answer's audit
entry records who answered and how (via), as evidence.

Standard library only. (It isn't named queue.py, which would shadow Python's own queue
module for run.py beside it.)

Usage:
  python3 scripts/review_queue.py list [--all]
  python3 scripts/review_queue.py show ID
  python3 scripts/review_queue.py approve ID [--by ACTOR-ID]
  python3 scripts/review_queue.py deny ID --reason TEXT [--by ACTOR-ID]
  python3 scripts/review_queue.py answer ID --text TEXT [--by ACTOR-ID]

ID is an item's ID (sha256:...), or its first 8 or more hex digits. The queue lives in
queue/ beside --state-dir (default: ~/.local/state/workflows-hive/queue).
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run as engine  # noqa: E402


def summary(item):
    source = item["source"]
    if item["kind"] == "approval":
        where = f"run {source['runId']} step {source['step']}"
    elif item["kind"] == "escalation":
        where = f"run {source['runId']} asks: {item['present']['question']}"
    else:
        where = f"passport {source['passport']} v{source['version']}"
    until = f", expires {item['expiresAt']}" if item["status"] == "open" and item["expiresAt"] else ""
    return f"{item['id'][7:19]}  {item['kind']:<10}  {item['status']:<8}  {where}{until}"


def cmd_list(args, e):
    items = e.items(None if args.all else "open")
    for item in items:
        print(summary(item))
    if not items:
        print("the queue is empty" if args.all else "nothing is waiting for a person")
    return 0


def cmd_show(args, e):
    print(json.dumps(e.item(args.id), indent=2))
    return 0


def answer(decision, text_of=lambda args: None, reason_of=lambda args: None):
    def cmd(args, e):
        engine.answering_here("cli")
        result = e.answer_item(args.id, decision, args.by, reason_of(args), text_of(args), "cli")
        if "runId" in result:
            print(json.dumps({k: result[k] for k in ("runId", "status", "pending", "result", "error")}, indent=2))
        else:
            print(json.dumps(result, indent=2))
        return 0
    return cmd


COMMANDS = {
    "list": cmd_list,
    "show": cmd_show,
    "approve": answer("approved"),
    "deny": answer("denied", reason_of=lambda args: args.reason),
    "answer": answer("answered", text_of=lambda args: args.text),
}


def main():
    ap = argparse.ArgumentParser(description="Read and answer the review queue.")
    ap.add_argument("--state-dir", default=str(engine.DEFAULT_STATE_DIR), help="Where run records live")
    ap.add_argument("--queue-dir", help="Where queue items live (default: queue/ beside --state-dir)")
    ap.add_argument("--workflows-dir", default=str(engine.WORKFLOWS_DIR), help="Where plans live")
    ap.add_argument("--contracts-dir", default=str(engine.CONTRACTS_DIR), help="Where execution contracts live")
    ap.add_argument("--audit", metavar="PATH", help="The audit log (default: audit.jsonl beside --state-dir)")
    sub = ap.add_subparsers(dest="command", required=True)
    ls = sub.add_parser("list", help="List the items waiting for a person")
    ls.add_argument("--all", action="store_true", help="Include answered and expired items")
    sub.add_parser("show", help="Show an item and what it presents").add_argument("id")
    for name, help_text in (("approve", "Approve an approval (the step runs) or drift (promotion may go ahead)"),
                            ("deny", "Deny an approval (the run fails) or drift (promotion stays held)"),
                            ("answer", "Answer an escalation")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("id")
        p.add_argument("--by", metavar="ACTOR-ID",
                       help="Who answered, as an opaque ID (default: $WORKFLOWS_HIVE_ACTOR)")
        if name == "deny":
            p.add_argument("--reason", required=True, help="Why, recorded with the answer")
        if name == "answer":
            p.add_argument("--text", required=True, help="The answer, recorded in the run for its agent")
    args = ap.parse_args()

    try:
        e = engine.Engine(args.state_dir, args.workflows_dir, args.contracts_dir, audit=args.audit,
                          actor=os.environ.get("WORKFLOWS_HIVE_ACTOR"), queue=args.queue_dir)
        sys.exit(COMMANDS[args.command](args, e))
    except engine.EngineError as err:
        sys.exit(str(err))


if __name__ == "__main__":
    main()
