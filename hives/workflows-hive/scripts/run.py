#!/usr/bin/env python3
"""Run a workflows-hive workflow with durable checkpoints (the P0 reference engine).

Implements the contract in DESIGN.md: a run record is written before the run is
acknowledged and atomically after every step, so a run that dies part way resumes
from its next step instead of starting over. Each step gets a stable idempotency key,
and the run reports its result and its total cost.

Usage:
  python3 scripts/run.py start word-count --input path=README.md
  python3 scripts/run.py start word-count --input path=README.md --crash-after read
  python3 scripts/run.py resume <run-id>
  python3 scripts/run.py status <run-id>

Run records live in --state-dir (default: ~/.local/state/workflows-hive/runs).
"""
import argparse
import json
import math
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / "workflows"
DEFAULT_STATE_DIR = Path("~/.local/state/workflows-hive/runs")
TERMINAL = ("completed", "failed", "cancelled")
REF = re.compile(r"\$\{([^}]+)\}")
CRASH_EXIT = 75

# The demo workers don't call a model, so they meter an estimated token count
# (about four characters per token) at a simulated price, to exercise cost reporting.
SIMULATED_USD_PER_1K_TOKENS = 0.002


def metered(text):
    tokens = math.ceil(len(text) / 4)
    return {"usd": round(tokens * SIMULATED_USD_PER_1K_TOKENS / 1000, 6), "tokens": tokens}


# Workers for the demo workflow. They are local functions from (input, idempotency key)
# to (output, cost), with no execution contract in agents-hive yet. Neither has an
# external effect, so neither needs the key.
def read_text(inp, _key):
    text = Path(inp["path"]).expanduser().read_text()
    return text, metered(text)


def count_words(inp, _key):
    text = inp["text"]
    return {"words": len(text.split()), "lines": len(text.splitlines())}, metered(text)


WORKERS = {"read-text": read_text, "count-words": count_words}


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_plan(name):
    path = WORKFLOWS_DIR / name / "workflow.json"
    if not path.is_file():
        sys.exit(f"workflow not found: {path}")
    plan = json.loads(path.read_text())
    for step in plan["steps"]:
        if step.get("approval") or step.get("budget"):
            sys.exit(f"step '{step['id']}': approval and budget aren't supported by this engine yet")
        if step["worker"] not in WORKERS:
            sys.exit(f"step '{step['id']}': unknown worker '{step['worker']}'")
    return plan


def record_path(state_dir, run_id):
    return state_dir / f"{run_id}.json"


def save(state_dir, run):
    """Write the run record atomically: a new file, flushed to disk, then renamed."""
    run["updatedAt"] = now()
    path = record_path(state_dir, run["runId"])
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(run, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load(state_dir, run_id):
    path = record_path(state_dir, run_id)
    if not path.is_file():
        sys.exit(f"run not found: {path}")
    return json.loads(path.read_text())


def lookup(ref, run):
    parts = ref.strip().split(".")
    if parts[0] == "inputs":
        value = run["inputs"]
        rest = parts[1:]
    elif parts[0] == "steps" and len(parts) >= 3 and parts[2] == "output":
        value = run["steps"][parts[1]]["output"]
        rest = parts[3:]
    else:
        raise ValueError(f"bad reference: ${{{ref}}}")
    for key in rest:
        value = value[key]
    return value


def resolve(value, run):
    """Substitute ${...} references. A string that is one whole reference keeps its type."""
    if isinstance(value, dict):
        return {k: resolve(v, run) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, run) for v in value]
    if isinstance(value, str):
        whole = REF.fullmatch(value)
        if whole:
            return lookup(whole.group(1), run)
        return REF.sub(lambda m: str(lookup(m.group(1), run)), value)
    return value


def add_cost(total, cost):
    total["usd"] = round(total["usd"] + cost.get("usd", 0), 6)
    total["tokens"] += cost.get("tokens", 0)


def execute(state_dir, plan, run, crash_after=None):
    """Run every step that isn't completed, checkpointing after each one."""
    if run["workflowVersion"] != plan["version"]:
        sys.exit(f"run {run['runId']} started on version {run['workflowVersion']}, "
                 f"but the plan is now version {plan['version']}")
    ids = [s["id"] for s in plan["steps"]]
    for i, step in enumerate(plan["steps"]):
        sid = step["id"]
        state = run["steps"][sid]
        if state["status"] == "completed":
            print(f"skip  {sid} (completed)")
            continue
        run["next"] = sid
        state.update(status="working", startedAt=now())
        save(state_dir, run)
        print(f"run   {sid}")
        try:
            output, cost = WORKERS[step["worker"]](resolve(step["input"], run), state["idempotencyKey"])
        except Exception as e:  # a failed step fails the run, with the reason recorded
            state.update(status="failed", endedAt=now())
            run.update(status="failed", error={"step": sid, "message": f"{type(e).__name__}: {e}"})
            save(state_dir, run)
            return run
        state.update(status="completed", output=output, cost=cost, endedAt=now())
        add_cost(run["cost"], cost)
        run["next"] = ids[i + 1] if i + 1 < len(ids) else None
        save(state_dir, run)
        if crash_after == sid:
            sys.stdout.flush()
            print(f"crash after {sid} (simulated); resume with: run.py resume {run['runId']}",
                  file=sys.stderr)
            os._exit(CRASH_EXIT)
    try:
        result = resolve(plan["output"], run)
    except Exception as e:
        run.update(status="failed", error={"step": None, "message": f"output: {type(e).__name__}: {e}"})
    else:
        run.update(status="completed", next=None, result=result)
    save(state_dir, run)
    return run


def report(run):
    print(json.dumps({k: run[k] for k in ("runId", "status", "result", "error", "cost")}, indent=2))
    return 0 if run["status"] == "completed" else 1


def cmd_start(args, state_dir):
    plan = load_plan(args.workflow)
    bad = [kv for kv in args.input if "=" not in kv]
    if bad:
        sys.exit(f"--input must be KEY=VALUE: {', '.join(bad)}")
    inputs = dict(kv.split("=", 1) for kv in args.input)
    missing = [k for k in plan["inputs"].get("required", []) if k not in inputs]
    if missing:
        sys.exit(f"missing required input: {', '.join(missing)}")
    if args.crash_after and args.crash_after not in [s["id"] for s in plan["steps"]]:
        sys.exit(f"--crash-after: no step '{args.crash_after}'")
    run_id = f"run_{uuid.uuid4().hex[:16]}"
    run = {
        "runId": run_id,
        "workflow": plan["name"],
        "workflowVersion": plan["version"],
        "status": "working",
        "inputs": inputs,
        "next": plan["steps"][0]["id"],
        "steps": {
            s["id"]: {"status": "not_started", "attempt": 1, "idempotencyKey": f"{run_id}:{s['id']}",
                      "output": None, "cost": {"usd": 0.0, "tokens": 0}, "startedAt": None, "endedAt": None}
            for s in plan["steps"]
        },
        "pending": None,
        "cost": {"usd": 0.0, "tokens": 0},
        "result": None,
        "error": None,
        "createdAt": now(),
    }
    save(state_dir, run)  # the run exists before its ID is handed out
    print(f"start {run_id} ({plan['name']} v{plan['version']})")
    return report(execute(state_dir, plan, run, args.crash_after))


def cmd_resume(args, state_dir):
    run = load(state_dir, args.run_id)
    if run["status"] in TERMINAL:
        print(f"run {run['runId']} is already {run['status']}")
        return report(run)
    print(f"resume {run['runId']} at {run['next']}")
    return report(execute(state_dir, load_plan(run["workflow"]), run))


def cmd_status(args, state_dir):
    run = load(state_dir, args.run_id)
    print(f"{run['runId']}: {run['status']}, next: {run['next']}")
    return report(run)


def main():
    ap = argparse.ArgumentParser(description="Run a workflows-hive workflow with durable checkpoints.")
    ap.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR), help="Where run records live")
    sub = ap.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start", help="Start a new run")
    start.add_argument("workflow", help="Workflow name under workflows/")
    start.add_argument("--input", action="append", default=[], metavar="KEY=VALUE")
    start.add_argument("--crash-after", metavar="STEP", help="Exit right after STEP checkpoints (to test resume)")
    for name, help_text in (("resume", "Resume a run from its next step"), ("status", "Show a run")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("run_id")
    args = ap.parse_args()

    state_dir = Path(args.state_dir).expanduser()
    state_dir.mkdir(parents=True, exist_ok=True)
    handler = {"start": cmd_start, "resume": cmd_resume, "status": cmd_status}[args.command]
    sys.exit(handler(args, state_dir))


if __name__ == "__main__":
    main()
