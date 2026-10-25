#!/usr/bin/env python3
"""Run a workflows-hive workflow with durable checkpoints (the P0 reference engine).

Implements the contract in DESIGN.md: a run record is written before the run is
acknowledged and atomically after every step, so a run that dies part way resumes
from its next step instead of starting over. Each step gets a stable idempotency key,
and the run reports its result and its total cost. A step marked "approval": true
pauses the run in input_required until a human approves or denies it. A step's
"budget" caps what it may spend: the engine stops a step that runs past its seconds and
fails the run when a step reports more usd or tokens than its cap. A step's "actions" are
decided by an approval policy (rules-hive's Charter, or --policy): a prohibited action
fails the run, a gated one pauses it for approval, and one no mandate allows is denied.

The engine is also a library (Engine, below). There a run can be open: it starts with no
steps, grows a step at a time, and keeps model turns in its record beside the steps, so
an agent loop resumed after a crash repeats neither a completed step nor a completed turn.

Usage:
  python3 scripts/run.py start word-count --input path=README.md
  python3 scripts/run.py start word-count --input path=README.md --crash-after read
  python3 scripts/run.py resume <run-id>
  python3 scripts/run.py status <run-id>
  python3 scripts/run.py approve <run-id> [--by NAME]
  python3 scripts/run.py deny <run-id> --reason TEXT [--by NAME]
  python3 scripts/run.py cancel <run-id> [--by NAME]

Exit status: 0 when the run completed, 2 when it is waiting for approval, 1 otherwise.

Run records live in --state-dir (default: ~/.local/state/workflows-hive/runs). Plans are
read from --workflows-dir (default: workflows/), and a worker's execution contract, if it
has one, from --contracts-dir (default: agents-hive's contracts/). start --policy picks the
approval policy, and the run keeps it.
"""
import argparse
import copy
import getpass
import importlib.util
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
CHARTER_POLICY = "hives/rules-hive/rules/queen-charter/policy.json"
REQUEST_KEYS = {"action": str, "scope": dict, "trigger": str, "facts": dict}
DEFAULT_STATE_DIR = Path("~/.local/state/workflows-hive/runs")
TERMINAL = ("completed", "failed", "cancelled")
REF = re.compile(r"\$\{([^}]+)\}")


def load_check_policy():
    """rules-hive's policy checker (check, resolve, decide), loaded by path so it never
    shadows or is shadowed by another module."""
    path = REPO_ROOT.parent / "rules-hive" / "scripts" / "check_policy.py"
    spec = importlib.util.spec_from_file_location("check_policy", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_policy = load_check_policy()
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


class EngineError(Exception):
    """A plan, policy, input or command the engine refuses. The CLI prints it and exits 1."""


class Stopped(Exception):
    """A model turn couldn't go ahead because its run failed or was cancelled; .run is the
    run record."""

    def __init__(self, run, message):
        super().__init__(message)
        self.run = run


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check_budget(step, contracts_dir):
    """Refuse a malformed budget, or one above the per-call budget in the worker's contract."""
    budget = step.get("budget")
    if budget is None:
        return
    sid = step["id"]
    if not isinstance(budget, dict) or not budget:
        raise EngineError(f"step '{sid}': budget must be an object with usd, tokens or seconds")
    for key, value in budget.items():
        kind = BUDGET_KEYS.get(key)
        if kind is None:
            raise EngineError(f"step '{sid}': unknown budget '{key}' (use usd, tokens or seconds)")
        if isinstance(value, bool) or not isinstance(value, kind) or not math.isfinite(value) or value <= 0:
            raise EngineError(f"step '{sid}': budget {key} must be a positive "
                              f"{'number' if key == 'usd' else 'whole number'}")
    path = contracts_dir / step["worker"] / "contract.json"
    if not path.is_file():
        return
    ceiling = json.loads(path.read_text()).get("budget", {})
    over = [f"{k} {v} > {ceiling[k]}" for k, v in budget.items() if k in ceiling and v > ceiling[k]]
    if over:
        raise EngineError(f"step '{sid}': budget is above the '{step['worker']}' contract's per-call "
                          f"budget ({', '.join(over)})")


def load_policy(rel):
    """The approval policy at rel (a path from the repo root), merged with what it extends."""
    path = (check_policy.REPO_ROOT / rel).resolve()
    if check_policy.REPO_ROOT not in path.parents or not path.is_file():
        raise EngineError(f"policy not found in the repo: {rel}")
    try:
        problems = check_policy.check(path)
        merged = None if problems else check_policy.resolve(path)
        problems = problems or check_policy.check_merged(merged)
    except check_policy.PolicyError as e:
        problems = [str(e)]
    if problems:
        raise EngineError(f"policy {rel} is invalid: {problems[0]}")
    merged["name"] = rel
    merged["vocabulary"] = check_policy.UNGATED | check_policy.GATED | set(merged["actions"])
    return merged


def check_actions(step, policy):
    """Refuse a step's actions unless each is a request the policy can decide."""
    actions = step.get("actions")
    if actions is None:
        return
    sid = step["id"]
    if not isinstance(actions, list) or not actions:
        raise EngineError(f"step '{sid}': actions must be a non-empty list")
    for req in actions:
        if not isinstance(req, dict) or not isinstance(req.get("action"), str):
            raise EngineError(f"step '{sid}': each action needs an action name")
        for key in sorted(set(req) - set(REQUEST_KEYS)):
            raise EngineError(f"step '{sid}': unknown field '{key}' in action {req['action']}")
        for key, kind in REQUEST_KEYS.items():
            if key in req and not isinstance(req[key], kind) and not REF.fullmatch(str(req[key])):
                raise EngineError(f"step '{sid}': {key} of action {req['action']} must be a {kind.__name__}")
        if req["action"] not in policy["vocabulary"]:
            raise EngineError(f"step '{sid}': action '{req['action']}' isn't in {policy['name']}'s vocabulary")


def check_step(step, workers, contracts_dir, policy):
    """Refuse a step the engine couldn't run: a bad approval flag, an unknown worker, or a
    budget or actions that don't check."""
    if not isinstance(step.get("approval", False), bool):
        raise EngineError(f"step '{step['id']}': approval must be true or false")
    if step["worker"] not in workers:
        raise EngineError(f"step '{step['id']}': unknown worker '{step['worker']}'")
    check_budget(step, contracts_dir)
    check_actions(step, policy)


def load_plan(name, workflows_dir, workers, contracts_dir, policy):
    path = workflows_dir / name / "workflow.json"
    if not path.is_file():
        raise EngineError(f"workflow not found: {path}")
    plan = json.loads(path.read_text())
    for step in plan["steps"]:
        check_step(step, workers, contracts_dir, policy)
    return plan


def new_step_state(run_id, sid):
    return {"status": "not_started", "attempt": 1, "idempotencyKey": f"{run_id}:{sid}",
            "output": None, "cost": {"usd": 0.0, "tokens": 0}, "startedAt": None, "endedAt": None}


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


def call_worker(worker, inp, key, cap):
    """Run a worker with its cap. With a seconds cap it runs in a child process, which is
    stopped if it runs past the cap; the cap includes the child's start-up time."""
    if "seconds" not in cap:
        return worker(inp, key, cap)
    with multiprocessing.get_context("spawn").Pool(1) as pool:  # leaving the block stops it
        job = pool.apply_async(worker, (inp, key, cap))
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


class BadAction(Exception):
    pass


def verdict(policy, step, run):
    """Decide a step's actions with the policy: (denial message or None, rules that need a
    human's approval, what that approval must present)."""
    rules, present = [], []
    for req in resolve(step.get("actions", []), run):
        for key, kind in REQUEST_KEYS.items():  # a reference can resolve to the wrong type
            if key in req and not isinstance(req[key], kind):
                raise BadAction(f"{key} of action {req['action']} resolved to a "
                                f"{type(req[key]).__name__}, not a {kind.__name__}")
        decision, rule, show = check_policy.decide(policy, req)
        if decision == "deny":
            if rule is None:
                return f"{req['action']} is denied: no mandate in {policy['name']} allows it", [], []
            reason = next(p["reason"] for p in policy["prohibitions"] if p["id"] == rule)
            return f"{req['action']} is prohibited by {rule}: {reason}", [], []
        if decision == "human":
            rules.append(rule)
            present += [x for x in show if x not in present]
    return None, rules, present


def current_user():
    try:
        return getpass.getuser()
    except Exception:  # no USER/LOGNAME and no passwd entry, as in some containers
        return "unknown"


class Engine:
    """The engine as a library: the CLI's commands, plus open runs that grow.

    workers maps a worker name to a function from (input, idempotency key, cap) to
    (output, cost); the default is the demo workers. A step with a seconds cap runs its
    worker in a spawned child process, so that worker must be a module-level function.
    log receives each progress line the CLI prints.
    """

    def __init__(self, state_dir=DEFAULT_STATE_DIR, workflows_dir=WORKFLOWS_DIR,
                 contracts_dir=CONTRACTS_DIR, workers=None, log=print):
        self.state_dir = Path(state_dir).expanduser()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.workflows_dir = Path(workflows_dir).expanduser()
        self.contracts_dir = Path(contracts_dir).expanduser()
        self.workers = dict(WORKERS if workers is None else workers)
        self.log = log

    # Records

    def record_path(self, run_id):
        return self.state_dir / f"{run_id}.json"

    def cancel_path(self, run_id):
        return self.state_dir / f"{run_id}.cancel"

    def save(self, run):
        """Write the run record atomically: a new file, flushed to disk, then renamed."""
        run["updatedAt"] = now()
        path = self.record_path(run["runId"])
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(run, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        if run["status"] in TERMINAL:  # a cancel that lands as the run ends has nothing left to stop
            self.cancel_path(run["runId"]).unlink(missing_ok=True)

    def load(self, run_id):
        path = self.record_path(run_id)
        if not path.is_file():
            raise EngineError(f"run not found: {path}")
        return json.loads(path.read_text())

    def plan_of(self, run):
        """The run's plan and policy. An open run carries its plan in its record."""
        policy = load_policy(run.get("policy", CHARTER_POLICY))
        if run.get("open"):
            return run["plan"], policy
        return load_plan(run["workflow"], self.workflows_dir, self.workers, self.contracts_dir, policy), policy

    def new_run(self, plan, policy_rel, inputs):
        run_id = f"run_{uuid.uuid4().hex[:16]}"
        return {
            "runId": run_id,
            "workflow": plan["name"],
            "workflowVersion": plan["version"],
            "policy": policy_rel,
            "status": "working",
            "inputs": inputs,
            "next": plan["steps"][0]["id"] if plan["steps"] else None,
            "steps": {s["id"]: new_step_state(run_id, s["id"]) for s in plan["steps"]},
            "pending": None,
            "cost": {"usd": 0.0, "tokens": 0},
            "result": None,
            "error": None,
            "createdAt": now(),
        }

    # Planned runs

    def start(self, workflow, inputs=None, policy=CHARTER_POLICY, crash_after=None):
        """Start a run of the plan named workflow, and execute it."""
        plan = load_plan(workflow, self.workflows_dir, self.workers, self.contracts_dir, load_policy(policy))
        inputs = dict(inputs or {})
        missing = [k for k in plan["inputs"].get("required", []) if k not in inputs]
        if missing:
            raise EngineError(f"missing required input: {', '.join(missing)}")
        if crash_after and crash_after not in [s["id"] for s in plan["steps"]]:
            raise EngineError(f"--crash-after: no step '{crash_after}'")
        run = self.new_run(plan, policy, inputs)
        self.save(run)  # the run exists before its ID is handed out
        self.log(f"start {run['runId']} ({plan['name']} v{plan['version']})")
        return self.execute(run, crash_after)

    def execute(self, run, crash_after=None):
        """Run every step that isn't completed, checkpointing after each one."""
        if run["status"] != "working":  # an ended or paused run never runs another step
            raise EngineError(f"run {run['runId']} is {run['status']}; only a working run executes")
        plan, policy = self.plan_of(run)
        if run["workflowVersion"] != plan["version"]:
            raise EngineError(f"run {run['runId']} started on version {run['workflowVersion']}, "
                              f"but the plan is now version {plan['version']}")
        ids = [s["id"] for s in plan["steps"]]
        for i, step in enumerate(plan["steps"]):
            sid = step["id"]
            state = run["steps"][sid]
            if state["status"] == "completed":
                self.log(f"skip  {sid} (completed)")
                continue
            if self.cancel_requested(run):
                return run
            run["next"] = sid
            try:
                denied, rules, present = verdict(policy, step, run)
                label = "deny"
            except Exception as e:  # the actions couldn't be decided, which fails the run too
                detail = str(e) if isinstance(e, BadAction) else f"{type(e).__name__}: {e}"
                denied, rules, present, label = f"actions: {detail}", [], [], "fail"
            if denied:  # a prohibition holds even after a human's approval
                run.update(status="failed", error={"step": sid, "message": denied})
                self.save(run)
                self.log(f"{label:<5} {sid} ({denied})")
                return run
            # approval: true adds a pause; approval: false can't remove one the policy requires.
            if (step.get("approval") or rules) and (state.get("approval") or {}).get("decision") != "approved":
                # Pause before the step: nothing runs until a human approves it (run.py approve).
                run.update(status="input_required",
                           pending={"step": sid, "kind": "approval", "rules": rules, "present": present})
                self.save(run)
                why = f" under {', '.join(rules)}" if rules else ""
                show = f", showing {', '.join(present)}" if present else ""
                self.log(f"wait  {sid} (needs approval{why}{show}; run.py approve {run['runId']}, or deny)")
                return run
            state.update(status="working", startedAt=now())
            self.save(run)
            self.log(f"run   {sid}")
            cap = step.get("budget", {})
            try:
                output, cost = call_worker(self.workers[step["worker"]], resolve(step["input"], run),
                                           state["idempotencyKey"], cap)
            except Exception as e:  # a failed step fails the run, with the reason recorded
                message = str(e) if isinstance(e, OverBudget) else f"{type(e).__name__}: {e}"
                state.update(status="failed", endedAt=now())
                run.update(status="failed", error={"step": sid, "message": message})
                self.save(run)
                self.log(f"fail  {sid} ({message})")
                return run
            over = over_cost(cost, cap)
            if over:  # the cost was spent, so it is recorded and counted, but the run stops
                state.update(status="failed", cost=cost, endedAt=now())
                add_cost(run["cost"], cost)
                run.update(status="failed", error={"step": sid, "message": over})
                self.save(run)
                self.log(f"fail  {sid} ({over})")
                return run
            state.update(status="completed", output=output, cost=cost, endedAt=now())
            add_cost(run["cost"], cost)
            run["next"] = ids[i + 1] if i + 1 < len(ids) else None
            self.save(run)
            if crash_after == sid:
                sys.stdout.flush()
                print(f"crash after {sid} (simulated); resume with: run.py resume {run['runId']}",
                      file=sys.stderr)
                os._exit(CRASH_EXIT)
        if run.get("open"):  # an open run ends only when its owner finishes it
            run["next"] = None
            self.save(run)
            return run
        try:
            result = resolve(plan["output"], run)
        except Exception as e:
            run.update(status="failed", error={"step": None, "message": f"output: {type(e).__name__}: {e}"})
        else:
            run.update(status="completed", next=None, result=result)
        self.save(run)
        return run

    # Open runs

    def open(self, name, inputs=None, policy=CHARTER_POLICY):
        """Start an open run: no steps yet, grown with append and turn, ended with finish."""
        load_policy(policy)
        if not isinstance(name, str) or not name:
            raise EngineError("an open run needs a name")
        plan = {"name": name, "version": 1, "steps": []}
        run = self.new_run(plan, policy, dict(inputs or {}))
        run.update(open=True, plan=plan, turns={})
        self.save(run)
        self.log(f"start {run['runId']} ({name}, open)")
        return run

    def working_open_run(self, run, verb):
        if not run.get("open"):
            raise EngineError(f"run {run['runId']} follows the {run['workflow']} plan; "
                              f"only an open run can {verb}")
        if run["status"] != "working":
            raise EngineError(f"run {run['runId']} is {run['status']}; it can {verb} only while working")

    def append(self, run, step):
        """Add a step to an open run. It runs on the next execute, decided, budgeted and
        checkpointed like a planned step."""
        self.working_open_run(run, "grow")
        if not isinstance(step, dict) or not isinstance(step.get("id"), str) or not step["id"] \
                or not isinstance(step.get("worker"), str) or not isinstance(step.get("input"), dict):
            raise EngineError("a step needs an id, a worker and an input object")
        step = copy.deepcopy(step)  # the run keeps the step as it was checked
        if step["id"] in run["steps"]:
            raise EngineError(f"step '{step['id']}': run {run['runId']} already has a step with that id")
        check_step(step, self.workers, self.contracts_dir, load_policy(run["policy"]))
        run["plan"]["steps"].append(step)
        run["steps"][step["id"]] = new_step_state(run["runId"], step["id"])
        run["next"] = run["next"] or step["id"]
        self.save(run)  # the step is durable before it can run
        return run

    def turn(self, run, turn_id, call):
        """Take one model turn in an open run, or return the output it already recorded.

        call gets the turn's idempotency key and returns (output, cost). A completed turn
        is never called again, so a resumed loop replays its turns from the record. A turn
        whose process died before its reply was recorded is called again. If call raises,
        the run fails. Raises Stopped when the run has failed or been cancelled.
        """
        if run["status"] != "working" or self.cancel_requested(run):
            raise Stopped(run, f"run {run['runId']} is {run['status']}")
        self.working_open_run(run, "take a turn")
        recorded = run["turns"].get(turn_id)
        if recorded and recorded["status"] == "completed":
            self.log(f"skip  turn {turn_id} (completed)")
            return recorded["output"]
        state = {"status": "working", "idempotencyKey": f"{run['runId']}:turn:{turn_id}", "output": None,
                 "cost": {"usd": 0.0, "tokens": 0}, "startedAt": now(), "endedAt": None}
        run["turns"][turn_id] = state
        self.save(run)
        self.log(f"turn  {turn_id}")
        try:
            output, cost = call(state["idempotencyKey"])
        except Exception as e:
            message = f"{type(e).__name__}: {e}"
            state.update(status="failed", endedAt=now())
            run.update(status="failed", error={"step": None, "turn": turn_id, "message": message})
            self.save(run)
            self.log(f"fail  turn {turn_id} ({message})")
            raise Stopped(run, message) from e
        state.update(status="completed", output=output, cost=cost, endedAt=now())
        add_cost(run["cost"], cost)
        self.save(run)
        return output

    def finish(self, run, result):
        """Complete an open run with its result, once every step has completed."""
        if self.cancel_requested(run):
            return run
        self.working_open_run(run, "finish")
        unfinished = [sid for sid, s in run["steps"].items() if s["status"] != "completed"]
        if unfinished:
            raise EngineError(f"run {run['runId']} has steps that haven't completed: {', '.join(unfinished)}")
        run.update(status="completed", next=None, result=result)
        self.save(run)
        return run

    def fail(self, run, message):
        """Fail an open run, as its owner's loop decided, with message as its error."""
        self.working_open_run(run, "fail")
        run.update(status="failed", error={"step": None, "message": message})
        self.save(run)
        return run

    # Commands on a run by its ID

    def resume(self, run_id):
        run = self.load(run_id)
        if run["status"] not in TERMINAL and self.cancel_requested(run):
            return run
        if run["status"] in TERMINAL:
            self.log(f"run {run['runId']} is already {run['status']}")
            return run
        if run["status"] == "input_required":  # resuming never answers an approval
            self.log(f"run {run['runId']} is waiting for approval of {run['pending']['step']}")
            return run
        self.log(f"resume {run['runId']} at {run['next']}")
        return self.execute(run)

    def answer(self, run_id, decision, by=None, reason=None):
        """Record a human's answer to a pending approval: approve runs the step, deny fails the run."""
        run = self.load(run_id)
        pending = run.get("pending")
        if run["status"] != "input_required" or not pending or pending.get("kind") != "approval":
            raise EngineError(f"run {run['runId']} isn't waiting for an approval (it is {run['status']})")
        if decision == "denied" and not (reason or "").strip():
            raise EngineError("deny needs a reason")
        sid = pending["step"]
        by = by or current_user()
        record = {"decision": decision, "by": by, "at": now()}
        if decision == "denied":
            record["reason"] = reason
        run["steps"][sid]["approval"] = record
        run["pending"] = None
        if decision == "denied":
            run.update(status="failed", error={"step": sid, "message": f"approval denied by {by}: {reason}"})
            self.save(run)
            self.log(f"deny  {sid}")
            return run
        run["status"] = "working"
        self.save(run)  # the approval is durable before the step runs
        self.log(f"approve {sid}")
        return self.execute(run)

    def approve(self, run_id, by=None):
        return self.answer(run_id, "approved", by)

    def deny(self, run_id, reason, by=None):
        return self.answer(run_id, "denied", by, reason)

    def cancel(self, run_id, by=None):
        """Cancel a run. A paused run is cancelled at once. A working one stops before its
        next step or turn, in whichever process runs it, or when it is resumed."""
        run = self.load(run_id)
        if run["status"] in TERMINAL:
            raise EngineError(f"run {run['runId']} is already {run['status']}")
        path = self.cancel_path(run_id)
        tmp = path.with_suffix(".cancel.tmp")
        tmp.write_text(json.dumps({"by": by or current_user(), "at": now()}))
        os.replace(tmp, path)  # a file of its own, so a save of the record can't overwrite it
        run = self.load(run_id)  # an approval may have started the step since
        if run["status"] in TERMINAL:  # it ended meanwhile, with nothing left to stop
            path.unlink(missing_ok=True)
        elif run["status"] == "input_required":
            self.cancel_requested(run)
        else:
            self.log(f"cancel requested; {run['runId']} stops before its next step")
        return run

    def cancel_requested(self, run):
        """If the run's cancel has been requested, cancel it now and return True."""
        path = self.cancel_path(run["runId"])
        if not path.is_file():
            return False
        request = json.loads(path.read_text())
        run.update(status="cancelled", pending=None,
                   error={"step": run.get("next"), "message": f"cancelled by {request['by']}"})
        self.save(run)
        path.unlink(missing_ok=True)
        self.log(f"cancel {run['runId']}")
        return True


def report(run):
    print(json.dumps({k: run[k] for k in ("runId", "status", "pending", "result", "error", "cost")}, indent=2))
    if run["status"] == "completed":
        return 0
    return WAITING_EXIT if run["status"] == "input_required" else 1


def policy_arg(value):
    """--policy as a path from the repo root, the form an extends uses."""
    path = Path(value).expanduser().resolve()
    try:
        rel = path.relative_to(check_policy.REPO_ROOT).as_posix()
    except ValueError:
        rel = ""
    if not rel.startswith("hives/"):
        raise EngineError(f"--policy must be a policy in this repo, under hives/: {value}")
    return rel


def cmd_start(args, engine):
    policy = policy_arg(args.policy) if args.policy else CHARTER_POLICY
    bad = [kv for kv in args.input if "=" not in kv]
    if bad:  # a plan that can't load is reported first
        load_plan(args.workflow, engine.workflows_dir, engine.workers, engine.contracts_dir, load_policy(policy))
        raise EngineError(f"--input must be KEY=VALUE: {', '.join(bad)}")
    inputs = dict(kv.split("=", 1) for kv in args.input)
    return report(engine.start(args.workflow, inputs, policy, args.crash_after))


def cmd_status(args, engine):
    run = engine.load(args.run_id)
    requested = " (cancel requested)" if engine.cancel_path(run["runId"]).is_file() else ""
    print(f"{run['runId']}: {run['status']}{requested}, next: {run['next']}")
    return report(run)


COMMANDS = {
    "start": cmd_start,
    "resume": lambda args, engine: report(engine.resume(args.run_id)),
    "status": cmd_status,
    "approve": lambda args, engine: report(engine.approve(args.run_id, args.by)),
    "deny": lambda args, engine: report(engine.deny(args.run_id, args.reason, args.by)),
    "cancel": lambda args, engine: report(engine.cancel(args.run_id, args.by)),
}


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
    start.add_argument("--policy", metavar="PATH",
                       help="Approval policy for the steps' actions (default: the Charter's)")
    start.add_argument("--crash-after", metavar="STEP", help="Exit right after STEP checkpoints (to test resume)")
    for name, help_text in (("resume", "Resume a run from its next step"), ("status", "Show a run")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("run_id")
    for name, help_text in (("approve", "Approve the step a run is waiting on, and continue"),
                            ("deny", "Deny the step a run is waiting on, which fails the run"),
                            ("cancel", "Cancel a run: now if it is paused, else before its next step")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("run_id")
        p.add_argument("--by", help=f"Who {'cancelled' if name == 'cancel' else 'answered'} "
                                    "(default: your user name)")
        if name == "deny":
            p.add_argument("--reason", required=True, help="Why, recorded as the run's error")
    args = ap.parse_args()

    try:
        engine = Engine(args.state_dir, args.workflows_dir, args.contracts_dir)
        sys.exit(COMMANDS[args.command](args, engine))
    except EngineError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
