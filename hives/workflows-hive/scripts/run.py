#!/usr/bin/env python3
"""Run a workflows-hive workflow with durable checkpoints (the P0 reference engine).

Implements the contract in DESIGN.md: a run record is written before the run is
acknowledged and atomically after every step, so a run that dies part way resumes
from its next step instead of starting over. Each step gets a stable idempotency key,
and the run reports its result and its total cost. A step marked "approval": true
pauses the run in input_required until a human approves or denies it. A step's
"budget" caps what it may spend: the engine stops a step that runs past its seconds and
fails the run when a step reports more usd or tokens than its cap.

Usage:
  python3 scripts/run.py start word-count --input path=README.md
  python3 scripts/run.py start word-count --input path=README.md --crash-after read
  python3 scripts/run.py resume <run-id>
  python3 scripts/run.py status <run-id>
  python3 scripts/run.py approve <run-id> [--by NAME]
  python3 scripts/run.py deny <run-id> --reason TEXT [--by NAME]

Exit status: 0 when the run completed, 2 when it is waiting for approval, 1 otherwise.

Run records live in --state-dir (default: ~/.local/state/workflows-hive/runs). Plans are
read from --workflows-dir (default: workflows/), and a worker's execution contract, if it
has one, from --contracts-dir (default: agents-hive's contracts/).
"""
import argparse
import getpass
import json
import math
import multiprocessing
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / "workflows"
CONTRACTS_DIR = REPO_ROOT.parent / "agents-hive" / "contracts"
BUDGET_KEYS = {"usd": (int, float), "tokens": int, "seconds": int}
DEFAULT_STATE_DIR = Path("~/.local/state/workflows-hive/runs")
TERMINAL = ("completed", "failed", "cancelled")
REF = re.compile(r"\$\{([^}]+)\}")
CRASH_EXIT = 75
WAITING_EXIT = 2

# The demo workers don't call a model, so they meter an estimated token count
# (about four characters per token) at a simulated price, to exercise cost reporting.
SIMULATED_USD_PER_1K_TOKENS = 0.002


def metered(text):
    tokens = math.ceil(len(text) / 4)
    return {"usd": round(tokens * SIMULATED_USD_PER_1K_TOKENS / 1000, 6), "tokens": tokens}


# Workers for the demo workflows. They are local functions from (input, idempotency key,
# cap) to (output, cost), with no execution contract in agents-hive yet. The cap is the
# step's budget; a worker that calls a model would stop itself within it. None has an
# external effect, so none needs the key.
def read_text(inp, _key, _cap):
    text = Path(inp["path"]).expanduser().read_text()
    return text, metered(text)


def count_words(inp, _key, _cap):
    text = inp["text"]
    return {"words": len(text.split()), "lines": len(text.splitlines())}, metered(text)


def wait(inp, _key, _cap):
    """Sleep for inp["seconds"], free of cost: stands in for a slow step."""
    time.sleep(float(inp["seconds"]))
    return {"waited": inp["seconds"]}, {"usd": 0.0, "tokens": 0}


WORKERS = {"read-text": read_text, "count-words": count_words, "wait": wait}


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check_budget(step, contracts_dir):
    """Refuse a malformed budget, or one above the per-call budget in the worker's contract."""
    budget = step.get("budget")
    if budget is None:
        return
    sid = step["id"]
    if not isinstance(budget, dict) or not budget:
        sys.exit(f"step '{sid}': budget must be an object with usd, tokens or seconds")
    for key, value in budget.items():
        kind = BUDGET_KEYS.get(key)
        if kind is None:
            sys.exit(f"step '{sid}': unknown budget '{key}' (use usd, tokens or seconds)")
        if isinstance(value, bool) or not isinstance(value, kind) or not math.isfinite(value) or value <= 0:
            sys.exit(f"step '{sid}': budget {key} must be a positive "
                     f"{'number' if key == 'usd' else 'whole number'}")
    path = contracts_dir / step["worker"] / "contract.json"
    if not path.is_file():
        return
    ceiling = json.loads(path.read_text()).get("budget", {})
    over = [f"{k} {v} > {ceiling[k]}" for k, v in budget.items() if k in ceiling and v > ceiling[k]]
    if over:
        sys.exit(f"step '{sid}': budget is above the '{step['worker']}' contract's per-call "
                 f"budget ({', '.join(over)})")


def load_plan(name, workflows_dir, contracts_dir):
    path = workflows_dir / name / "workflow.json"
    if not path.is_file():
        sys.exit(f"workflow not found: {path}")
    plan = json.loads(path.read_text())
    for step in plan["steps"]:
        if not isinstance(step.get("approval", False), bool):
            sys.exit(f"step '{step['id']}': approval must be true or false")
        if step["worker"] not in WORKERS:
            sys.exit(f"step '{step['id']}': unknown worker '{step['worker']}'")
        check_budget(step, contracts_dir)
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


class OverBudget(Exception):
    pass


def call_worker(name, inp, key, cap):
    """Run a worker with its cap. With a seconds cap it runs in a child process, which is
    stopped if it runs past the cap; the cap includes the child's start-up time."""
    if "seconds" not in cap:
        return WORKERS[name](inp, key, cap)
    with multiprocessing.get_context("spawn").Pool(1) as pool:  # leaving the block stops it
        job = pool.apply_async(WORKERS[name], (inp, key, cap))
        try:
            return job.get(timeout=cap["seconds"])
        except multiprocessing.TimeoutError:
            unit = "second" if cap["seconds"] == 1 else "seconds"
            raise OverBudget(f"ran past its budget of {cap['seconds']} {unit}") from None


def over_cost(cost, cap):
    for key in ("usd", "tokens"):
        if key in cap and cost.get(key, 0) > cap[key]:
            return f"spent {cost[key]} {key}, over its budget of {cap[key]}"
    return None


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
        if step.get("approval") and (state.get("approval") or {}).get("decision") != "approved":
            # Pause before the step: nothing runs until a human approves it (run.py approve).
            run.update(status="input_required", pending={"step": sid, "kind": "approval"})
            save(state_dir, run)
            print(f"wait  {sid} (needs approval: run.py approve {run['runId']}, or deny)")
            return run
        state.update(status="working", startedAt=now())
        save(state_dir, run)
        print(f"run   {sid}")
        cap = step.get("budget", {})
        try:
            output, cost = call_worker(step["worker"], resolve(step["input"], run),
                                       state["idempotencyKey"], cap)
        except Exception as e:  # a failed step fails the run, with the reason recorded
            message = str(e) if isinstance(e, OverBudget) else f"{type(e).__name__}: {e}"
            state.update(status="failed", endedAt=now())
            run.update(status="failed", error={"step": sid, "message": message})
            save(state_dir, run)
            print(f"fail  {sid} ({message})")
            return run
        over = over_cost(cost, cap)
        if over:  # the cost was spent, so it is recorded and counted, but the run stops
            state.update(status="failed", cost=cost, endedAt=now())
            add_cost(run["cost"], cost)
            run.update(status="failed", error={"step": sid, "message": over})
            save(state_dir, run)
            print(f"fail  {sid} ({over})")
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
    print(json.dumps({k: run[k] for k in ("runId", "status", "pending", "result", "error", "cost")}, indent=2))
    if run["status"] == "completed":
        return 0
    return WAITING_EXIT if run["status"] == "input_required" else 1


def plan_for(args, name):
    return load_plan(name, Path(args.workflows_dir).expanduser(), Path(args.contracts_dir).expanduser())


def cmd_start(args, state_dir):
    plan = plan_for(args, args.workflow)
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
    if run["status"] == "input_required":  # resuming never answers an approval
        print(f"run {run['runId']} is waiting for approval of {run['pending']['step']}")
        return report(run)
    print(f"resume {run['runId']} at {run['next']}")
    return report(execute(state_dir, plan_for(args, run["workflow"]), run))


def answer(args, state_dir, decision):
    """Record a human's answer to a pending approval: approve runs the step, deny fails the run."""
    run = load(state_dir, args.run_id)
    pending = run.get("pending")
    if run["status"] != "input_required" or not pending or pending.get("kind") != "approval":
        sys.exit(f"run {run['runId']} isn't waiting for an approval (it is {run['status']})")
    if decision == "denied" and not args.reason.strip():
        sys.exit("deny needs a reason")
    sid = pending["step"]
    by = args.by or current_user()
    record = {"decision": decision, "by": by, "at": now()}
    if decision == "denied":
        record["reason"] = args.reason
    run["steps"][sid]["approval"] = record
    run["pending"] = None
    if decision == "denied":
        run.update(status="failed", error={"step": sid, "message": f"approval denied by {by}: {args.reason}"})
        save(state_dir, run)
        print(f"deny  {sid}")
        return report(run)
    run["status"] = "working"
    save(state_dir, run)  # the approval is durable before the step runs
    print(f"approve {sid}")
    return report(execute(state_dir, plan_for(args, run["workflow"]), run))


def current_user():
    try:
        return getpass.getuser()
    except Exception:  # no USER/LOGNAME and no passwd entry, as in some containers
        return "unknown"


def cmd_approve(args, state_dir):
    return answer(args, state_dir, "approved")


def cmd_deny(args, state_dir):
    return answer(args, state_dir, "denied")


def cmd_status(args, state_dir):
    run = load(state_dir, args.run_id)
    print(f"{run['runId']}: {run['status']}, next: {run['next']}")
    return report(run)


def main():
    ap = argparse.ArgumentParser(description="Run a workflows-hive workflow with durable checkpoints.")
    ap.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR), help="Where run records live")
    ap.add_argument("--workflows-dir", default=str(WORKFLOWS_DIR), help="Where plans live")
    ap.add_argument("--contracts-dir", default=str(CONTRACTS_DIR),
                    help="Where execution contracts live, to check step budgets against")
    sub = ap.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start", help="Start a new run")
    start.add_argument("workflow", help="Workflow name under workflows/")
    start.add_argument("--input", action="append", default=[], metavar="KEY=VALUE")
    start.add_argument("--crash-after", metavar="STEP", help="Exit right after STEP checkpoints (to test resume)")
    for name, help_text in (("resume", "Resume a run from its next step"), ("status", "Show a run")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("run_id")
    for name, help_text in (("approve", "Approve the step a run is waiting on, and continue"),
                            ("deny", "Deny the step a run is waiting on, which fails the run")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("run_id")
        p.add_argument("--by", help="Who answered (default: your user name)")
        if name == "deny":
            p.add_argument("--reason", required=True, help="Why, recorded as the run's error")
    args = ap.parse_args()

    state_dir = Path(args.state_dir).expanduser()
    state_dir.mkdir(parents=True, exist_ok=True)
    handler = {"start": cmd_start, "resume": cmd_resume, "status": cmd_status,
               "approve": cmd_approve, "deny": cmd_deny}[args.command]
    sys.exit(handler(args, state_dir))


if __name__ == "__main__":
    main()
