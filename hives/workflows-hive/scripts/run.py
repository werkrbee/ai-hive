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
A run can run under an agent's passport (--passport), whose never actions are prohibited.

Every decision goes into a hash-chained audit log (knowledge-hive's audit.jsonl format,
--audit) before the run record that follows it, and the record keeps the seq and hash of
its run's last entry. A human's answer or cancel is recorded under an opaque actor ID
(--by, or WORKFLOWS_HIVE_ACTOR), never an operating-system login.

The engine is also a library (Engine, below). There a run can be open: it starts with no
steps, grows a step at a time, and keeps model turns in its record beside the steps, so
an agent loop resumed after a crash repeats neither a completed step nor a completed turn.

Usage:
  python3 scripts/run.py start word-count --input path=README.md
  python3 scripts/run.py start word-count --input path=README.md --crash-after read
  python3 scripts/run.py resume <run-id>
  python3 scripts/run.py status <run-id>
  python3 scripts/run.py start word-count --input path=README.md --passport barry
  python3 scripts/run.py approve <run-id> [--by ACTOR-ID]
  python3 scripts/run.py deny <run-id> --reason TEXT [--by ACTOR-ID]
  python3 scripts/run.py cancel <run-id> [--by ACTOR-ID]

Exit status: 0 when the run completed, 2 when it is waiting for approval, 1 otherwise.

Run records live in --state-dir (default: ~/.local/state/workflows-hive/runs). Plans are
read from --workflows-dir (default: workflows/), and a worker's execution contract, if it
has one, from --contracts-dir (default: agents-hive's contracts/). start --policy picks the
approval policy, and the run keeps it. The audit log defaults to audit.jsonl beside the
state directory.
"""
import argparse
import copy
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
PASSPORTS_DIR = REPO_ROOT.parent / "agents-hive" / "passports"
BUDGET_KEYS = {"usd": (int, float), "tokens": int, "seconds": int}
CHARTER_POLICY = "hives/rules-hive/rules/queen-charter/policy.json"
REQUEST_KEYS = {"action": str, "scope": dict, "trigger": str, "facts": dict}
DEFAULT_STATE_DIR = Path("~/.local/state/workflows-hive/runs")
TERMINAL = ("completed", "failed", "cancelled")
REF = re.compile(r"\$\{([^}]+)\}")


def load_script(hive, name):
    """Another hive's script, loaded by path so it never shadows or is shadowed by another
    module."""
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT.parent / hive / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_policy = load_script("rules-hive", "check_policy")              # check, resolve, decide
check_audit = load_script("knowledge-hive", "check_audit")            # the audit log's format
validate_passports = load_script("agents-hive", "validate_passports")  # check, digest
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


def load_passport(name, passports_dir=PASSPORTS_DIR):
    """The passport named name, checked against its contract and pins, and its digest."""
    if not isinstance(name, str) or not validate_passports.KEBAB.match(name):
        raise EngineError(f"a passport is named in kebab-case, not {name!r}")
    path = Path(passports_dir) / name / "passport.json"
    if not path.is_file():
        raise EngineError(f"no passport for '{name}' at {path}")
    problems = validate_passports.check(path)
    if problems:
        raise EngineError(f"passport {name} is invalid: {problems[0]}")
    passport = json.loads(path.read_text())
    return passport, validate_passports.digest(passport)


def under_passport(policy, passport):
    """The policy with each action in the passport's never as a prohibition, ahead of the
    policy's own, so no mandate or approval can open it."""
    name = passport["passport"]
    never = [{"id": f"passport.{name}.never.{a}", "action": a,
              "reason": f"{name}'s passport puts it under never, so {name} may not take it even with approval"}
             for a in passport["permissions"]["never"]]
    return dict(policy, prohibitions=never + policy["prohibitions"])


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
    """Decide a step's actions with the policy, in order, up to the first one denied: a list
    of (request, decision, deciding rule or None, what a human's approval must present)."""
    decided = []
    for req in resolve(step.get("actions", []), run):
        for key, kind in REQUEST_KEYS.items():  # a reference can resolve to the wrong type
            if key in req and not isinstance(req[key], kind):
                raise BadAction(f"{key} of action {req['action']} resolved to a "
                                f"{type(req[key]).__name__}, not a {kind.__name__}")
        decision, rule, show = check_policy.decide(policy, req)
        decided.append((req, decision, rule, show))
        if decision == "deny":
            break
    return decided


def denial(policy, req, rule):
    if rule is None:
        return f"{req['action']} is denied: no mandate in {policy['name']} allows it"
    reason = next(p["reason"] for p in policy["prohibitions"] if p["id"] == rule)
    return f"{req['action']} is prohibited by {rule}: {reason}"


def call_digest(run, step, inp, req=None):
    """The digest of the exact call a step makes: its run, step, worker, resolved input and,
    for one action, the action as decided. An audit entry names the call by it, so the log
    can be matched to the run record without holding the call's arguments."""
    call = {"runId": run["runId"], "step": step["id"], "worker": step["worker"], "input": inp}
    if req is not None:
        call["action"] = req
    return check_audit.digest(call)


def actor_id(by):
    """by, if it can stand for a person in the record: an opaque ID, never a name or email."""
    if not by:
        raise EngineError("an answer or cancel needs an actor ID: pass --by, or set WORKFLOWS_HIVE_ACTOR")
    if not check_audit.opaque(by):
        raise EngineError(f"{by!r} isn't an actor ID: use an opaque identifier, never a name or "
                          "email address (letters, digits and ._:@/+-, no spaces)")
    return by


class Engine:
    """The engine as a library: the CLI's commands, plus open runs that grow.

    workers maps a worker name to a function from (input, idempotency key, cap) to
    (output, cost); the default is the demo workers. A step with a seconds cap runs its
    worker in a spawned child process, so that worker must be a module-level function.
    audit is the audit log's path (default: audit.jsonl beside state_dir), and actor the
    opaque ID recorded for an answer or cancel that names no one else. log receives each
    progress line the CLI prints.
    """

    def __init__(self, state_dir=DEFAULT_STATE_DIR, workflows_dir=WORKFLOWS_DIR,
                 contracts_dir=CONTRACTS_DIR, workers=None, log=print, audit=None, actor=None,
                 passports_dir=PASSPORTS_DIR):
        self.state_dir = Path(state_dir).expanduser()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.workflows_dir = Path(workflows_dir).expanduser()
        self.contracts_dir = Path(contracts_dir).expanduser()
        self.passports_dir = Path(passports_dir).expanduser()
        self.audit_path = Path(audit).expanduser() if audit else self.state_dir.parent / "audit.jsonl"
        self.actor = actor
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

    def audit(self, run, kind, **fields):
        """Append an entry about run to the audit log, and anchor the run record to it. The
        caller saves the record next, so the log never falls behind the record."""
        entry = {"kind": kind}
        if run.get("agent"):
            entry["agent"] = run["agent"]
        entry["runId"] = run["runId"]
        entry.update((k, v) for k, v in fields.items() if v is not None)
        try:
            written = check_audit.append(self.audit_path, entry)
        except (check_audit.AuditError, OSError) as e:  # nothing goes on that the log can't hold
            raise EngineError(f"audit log {self.audit_path}: {e}") from None
        run["audit"] = {"seq": written["seq"], "hash": written["hash"]}

    def end(self, run, status, **fields):
        """End the run with status (completed or failed), audited, and save it."""
        run.update(status=status, **fields)
        self.audit(run, f"run.{status}")
        self.save(run)
        return run

    def load(self, run_id):
        path = self.record_path(run_id)
        if not path.is_file():
            raise EngineError(f"run not found: {path}")
        return json.loads(path.read_text())

    def passport_of(self, run):
        """The passport the run started under, refused if it has changed since."""
        agent = run.get("agent")
        if not agent:
            return None
        passport, sha = load_passport(agent["passport"], self.passports_dir)
        if sha != agent["sha256"]:
            raise EngineError(f"run {run['runId']} started under passport {agent['passport']} version "
                              f"{agent['version']}, which has changed since (it is now version "
                              f"{passport['version']}); a run keeps the passport it started under")
        return passport

    def plan_of(self, run):
        """The run's plan, and its policy under its passport. An open run carries its plan in
        its record."""
        policy = load_policy(run.get("policy", CHARTER_POLICY))
        passport = self.passport_of(run)
        if passport:
            policy = under_passport(policy, passport)
        if run.get("open"):
            return run["plan"], policy
        return load_plan(run["workflow"], self.workflows_dir, self.workers, self.contracts_dir, policy), policy

    def new_run(self, plan, policy_rel, inputs, passport=None):
        run_id = f"run_{uuid.uuid4().hex[:16]}"
        agent = None
        if passport is not None:
            p, sha = load_passport(passport, self.passports_dir)
            agent = {"passport": p["passport"], "version": p["version"], "sha256": sha}
        return {
            "runId": run_id,
            "workflow": plan["name"],
            "workflowVersion": plan["version"],
            "policy": policy_rel,
            "agent": agent,
            "status": "working",
            "inputs": inputs,
            "next": plan["steps"][0]["id"] if plan["steps"] else None,
            "steps": {s["id"]: new_step_state(run_id, s["id"]) for s in plan["steps"]},
            "pending": None,
            "cost": {"usd": 0.0, "tokens": 0},
            "result": None,
            "error": None,
            "audit": None,
            "createdAt": now(),
        }

    # Planned runs

    def start(self, workflow, inputs=None, policy=CHARTER_POLICY, crash_after=None, passport=None):
        """Start a run of the plan named workflow, under passport if one is named, and execute it."""
        plan = load_plan(workflow, self.workflows_dir, self.workers, self.contracts_dir, load_policy(policy))
        inputs = dict(inputs or {})
        missing = [k for k in plan["inputs"].get("required", []) if k not in inputs]
        if missing:
            raise EngineError(f"missing required input: {', '.join(missing)}")
        if crash_after and crash_after not in [s["id"] for s in plan["steps"]]:
            raise EngineError(f"--crash-after: no step '{crash_after}'")
        run = self.new_run(plan, policy, inputs, passport)
        self.audit(run, "run.started")
        self.save(run)  # the run exists before its ID is handed out
        self.log(f"start {run['runId']} ({plan['name']} v{plan['version']})")
        return self.execute(run, crash_after)

    def decide(self, run, step, policy, inp):
        """Decide the step's actions and audit each decision. Returns (denial message or None,
        rules that need a human's approval, what that approval must present). Once a human
        has approved the step, only a denial is audited again: the answer was the decision."""
        sid, state = step["id"], run["steps"][step["id"]]
        approved = (state.get("approval") or {}).get("decision") == "approved"
        rules, present = [], []
        decided = verdict(policy, step, run)
        for req, decision, rule, show in decided:
            word = {"auto": "allowed", "human": "paused", "deny": "denied"}[decision]
            if decision == "deny" or not approved:
                self.audit(run, "step.decided", step=sid, action=req["action"], decision=word,
                           rules=[rule] if rule else [], call=call_digest(run, step, inp, req))
            if decision == "deny":
                return denial(policy, req, rule), [], []
            if decision == "human":
                rules.append(rule)
                present += [x for x in show if x not in present]
        # approval: true adds a pause; approval: false can't remove one the policy requires.
        pause = bool(step.get("approval") or rules) and not approved
        if not approved and (not decided or (pause and not rules)):  # a decision no action records
            self.audit(run, "step.decided", step=sid, decision="paused" if pause else "allowed",
                       rules=[], call=call_digest(run, step, inp))
        return None, rules if pause else None, present

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
                inp = resolve(step["input"], run)
            except Exception as e:  # an input that can't be resolved fails the step, as a worker would
                message = f"{type(e).__name__}: {e}"
                state.update(status="failed", endedAt=now())
                self.audit(run, "step.failed", step=sid)
                self.log(f"fail  {sid} ({message})")
                return self.end(run, "failed", error={"step": sid, "message": message})
            try:
                denied, rules, present = self.decide(run, step, policy, inp)
            except EngineError:
                raise
            except Exception as e:  # the actions couldn't be decided, which fails the run too
                detail = str(e) if isinstance(e, BadAction) else f"{type(e).__name__}: {e}"
                message = f"actions: {detail}"
                self.audit(run, "step.failed", step=sid)
                self.log(f"fail  {sid} ({message})")
                return self.end(run, "failed", error={"step": sid, "message": message})
            if denied:  # a prohibition holds even after a human's approval
                self.log(f"deny  {sid} ({denied})")
                return self.end(run, "failed", error={"step": sid, "message": denied})
            if rules is not None:
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
                output, cost = call_worker(self.workers[step["worker"]], inp, state["idempotencyKey"], cap)
            except Exception as e:  # a failed step fails the run, with the reason recorded
                message = str(e) if isinstance(e, OverBudget) else f"{type(e).__name__}: {e}"
                state.update(status="failed", endedAt=now())
                self.audit(run, "budget.refused" if isinstance(e, OverBudget) else "step.failed", step=sid)
                self.log(f"fail  {sid} ({message})")
                return self.end(run, "failed", error={"step": sid, "message": message})
            over = over_cost(cost, cap)
            if over:  # the cost was spent, so it is recorded and counted, but the run stops
                state.update(status="failed", cost=cost, endedAt=now())
                add_cost(run["cost"], cost)
                self.audit(run, "budget.refused", step=sid)
                self.log(f"fail  {sid} ({over})")
                return self.end(run, "failed", error={"step": sid, "message": over})
            state.update(status="completed", output=output, cost=cost, endedAt=now())
            add_cost(run["cost"], cost)
            run["next"] = ids[i + 1] if i + 1 < len(ids) else None
            self.audit(run, "step.ran", step=sid)
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
            return self.end(run, "failed", error={"step": None, "message": f"output: {type(e).__name__}: {e}"})
        return self.end(run, "completed", next=None, result=result)

    # Open runs

    def open(self, name, inputs=None, policy=CHARTER_POLICY, passport=None):
        """Start an open run, under passport if one is named: no steps yet, grown with append
        and turn, ended with finish."""
        load_policy(policy)
        if not isinstance(name, str) or not name:
            raise EngineError("an open run needs a name")
        plan = {"name": name, "version": 1, "steps": []}
        run = self.new_run(plan, policy, dict(inputs or {}), passport)
        run.update(open=True, plan=plan, turns={})
        self.audit(run, "run.started")
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
            self.audit(run, "turn.failed", turn=turn_id)
            self.end(run, "failed", error={"step": None, "turn": turn_id, "message": message})
            self.log(f"fail  turn {turn_id} ({message})")
            raise Stopped(run, message) from e
        state.update(status="completed", output=output, cost=cost, endedAt=now())
        add_cost(run["cost"], cost)
        self.audit(run, "turn.completed", turn=turn_id)
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
        return self.end(run, "completed", next=None, result=result)

    def fail(self, run, message):
        """Fail an open run, as its owner's loop decided, with message as its error."""
        self.working_open_run(run, "fail")
        return self.end(run, "failed", error={"step": None, "message": message})

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
        by = actor_id(by or self.actor)
        sid = pending["step"]
        record = {"decision": decision, "by": by, "at": now()}
        if decision == "denied":
            record["reason"] = reason
        run["steps"][sid]["approval"] = record
        run["pending"] = None
        self.audit(run, "approval.answered", step=sid, decision=decision, by=by)
        if decision == "denied":
            self.log(f"deny  {sid}")
            return self.end(run, "failed", error={"step": sid, "message": f"approval denied by {by}: {reason}"})
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
        by = actor_id(by or self.actor)
        path = self.cancel_path(run_id)
        tmp = path.with_suffix(".cancel.tmp")
        tmp.write_text(json.dumps({"by": by, "at": now()}))
        os.replace(tmp, path)  # a file of its own, so a save of the record can't overwrite it
        run = self.load(run_id)  # an approval may have started the step since
        if run["status"] in TERMINAL:  # it ended meanwhile, with nothing left to stop
            path.unlink(missing_ok=True)
            self.log(f"run {run['runId']} ended ({run['status']}) before the cancel")
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
        self.audit(run, "run.cancelled", step=run.get("next"), by=request["by"])
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
    return report(engine.start(args.workflow, inputs, policy, args.crash_after, args.passport))


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
    ap.add_argument("--audit", metavar="PATH",
                    help="The audit log to append to (default: audit.jsonl beside --state-dir)")
    sub = ap.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start", help="Start a new run")
    start.add_argument("workflow", help="Workflow name under workflows/")
    start.add_argument("--input", action="append", default=[], metavar="KEY=VALUE")
    start.add_argument("--policy", metavar="PATH",
                       help="Approval policy for the steps' actions (default: the Charter's)")
    start.add_argument("--passport", metavar="NAME",
                       help="Run under this agent's passport (agents-hive's passports/NAME)")
    start.add_argument("--crash-after", metavar="STEP", help="Exit right after STEP checkpoints (to test resume)")
    for name, help_text in (("resume", "Resume a run from its next step"), ("status", "Show a run")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("run_id")
    for name, help_text in (("approve", "Approve the step a run is waiting on, and continue"),
                            ("deny", "Deny the step a run is waiting on, which fails the run"),
                            ("cancel", "Cancel a run: now if it is paused, else before its next step")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("run_id")
        p.add_argument("--by", metavar="ACTOR-ID",
                       help=f"Who {'cancelled' if name == 'cancel' else 'answered'}, as an opaque ID, "
                            "never a name or email (default: $WORKFLOWS_HIVE_ACTOR)")
        if name == "deny":
            p.add_argument("--reason", required=True, help="Why, recorded as the run's error")
    args = ap.parse_args()

    try:
        engine = Engine(args.state_dir, args.workflows_dir, args.contracts_dir, audit=args.audit,
                        actor=os.environ.get("WORKFLOWS_HIVE_ACTOR"))
        sys.exit(COMMANDS[args.command](args, engine))
    except EngineError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
