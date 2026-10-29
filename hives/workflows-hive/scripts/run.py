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

Every pause is also an item in the review queue (review_queue.py), named by an approval ID
that digests exactly what the human is asked to approve. An answer must come from an
interactive terminal and from outside any engine run, and a pause unanswered for seven days
expires, which fails its run.

A person can roll a completed or failed run back to an earlier step (rollback). Each later
step with an effect outside the system is compensated first, newest first, by the
compensate step its plan declares, and each later step that ran is marked rolledBack,
never deleted. The rollback's reason stays in the run record, and the audit log records
who did it and the record's digest.

The engine is also a library (Engine, below). There a run can be open: it starts with no
steps, grows a step at a time, and keeps model turns in its record beside the steps, so
an agent loop resumed after a crash repeats neither a completed step nor a completed turn.
An open run under a passport can delegate to another agent (delegate), whose own open run
is held to the stricter of the two passports and to a budget carved out of this one's.

Usage:
  python3 scripts/run.py start word-count --input path=README.md
  python3 scripts/run.py start word-count --input path=README.md --crash-after read
  python3 scripts/run.py resume <run-id>
  python3 scripts/run.py status <run-id>
  python3 scripts/run.py start word-count --input path=README.md --passport barry
  python3 scripts/run.py approve <run-id> [--id APPROVAL-ID] [--by ACTOR-ID]
  python3 scripts/run.py deny <run-id> --reason TEXT [--id APPROVAL-ID] [--by ACTOR-ID]
  python3 scripts/run.py cancel <run-id> [--by ACTOR-ID]
  python3 scripts/run.py rollback <run-id> --to STEP --reason TEXT [--by ACTOR-ID]

Exit status: 0 when the run completed, 2 when it is waiting for approval, 1 otherwise. A
rollback exits 0 once it is done, with the run waiting at the step after STEP for resume.

Run records live in --state-dir (default: ~/.local/state/workflows-hive/runs). Plans are
read from --workflows-dir (default: workflows/), and a worker's execution contract, if it
has one, from --contracts-dir (default: agents-hive's contracts/). start --policy picks the
approval policy, and the run keeps it. The audit log defaults to audit.jsonl beside the
state directory, and the review queue to queue/ beside it.
"""
import argparse
import contextlib
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
from datetime import datetime, timedelta, timezone
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
EXPIRY = timedelta(days=7)  # how long an approval or escalation waits for a human
RUN_ENV = "WORKFLOWS_HIVE_RUN"  # set in a step's or turn's environment while it runs
FINDINGS = ("drift", "unconfirmed-miss", "cost", "not-run")  # what a trust evaluation sends the queue
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


READS = ("fs.read",)  # actions with no effect outside the system
DELEGATE = "delegate"  # the worker of a delegation step, which only Engine.delegate adds


def has_effect(step):
    """Whether a step takes an action with an effect outside the system: any but a read. A
    step that lists no actions takes none the engine knows of."""
    return any(req["action"] not in READS for req in step.get("actions", []))


def compensation_id(sid, attempt):
    """The id of the step that compensates attempt of step sid."""
    return f"compensate-{sid}-{attempt}"


class EngineError(Exception):
    """A plan, policy, input or command the engine refuses. The CLI prints it and exits 1."""


class Stopped(Exception):
    """A model turn couldn't go ahead because its run failed or was cancelled; .run is the
    run record."""

    def __init__(self, run, message):
        super().__init__(message)
        self.run = run


def stamp(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def now():
    return stamp(datetime.now(timezone.utc))


def parse_time(value):
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


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


def narrow(outer, inner):
    """The grant a delegate runs under: its delegator's grant (outer) intersected with its
    own passport's permissions (inner). Each action takes the stricter of the two
    treatments, in the order never, then approval, then granted, and an action either
    leaves out is in no list, so it is denied."""
    never = set(outer["never"]) | set(inner["never"])
    both = (set(outer["granted"]) | set(outer["approval"])) & (set(inner["granted"]) | set(inner["approval"]))
    both -= never
    approval = both & (set(outer["approval"]) | set(inner["approval"]))
    return {"granted": sorted(both - approval), "approval": sorted(approval), "never": sorted(never)}


def under_grant(policy, grant, name):
    """The policy for a run under a delegated grant: each action the grant puts under never
    or leaves out is prohibited, ahead of the policy's own, and one under approval needs a
    person even where the policy would let it run on its own (see verdict)."""
    allowed = set(grant["granted"]) | set(grant["approval"])
    why = f"the grant {name} was delegated, narrowed from its delegator's,"
    rules = [{"id": f"grant.{name}.never.{a}", "action": a, "reason": f"{why} puts it under never"}
             for a in grant["never"]]
    rules += [{"id": f"grant.{name}.omits.{a}", "action": a, "reason": f"{why} leaves it out"}
              for a in sorted(policy["vocabulary"] - allowed - set(grant["never"]))]
    return dict(policy, prohibitions=rules + policy["prohibitions"], grant=dict(grant, rule=f"grant.{name}.approval"))


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


def check_step(step, workers, contracts_dir, policy, delegation=False):
    """Refuse a step the engine couldn't run: a bad approval flag, an unknown worker, a
    budget or actions that don't check, or a compensate step that doesn't. Only a
    delegation (Engine.delegate) has the delegate worker."""
    if not isinstance(step.get("approval", False), bool):
        raise EngineError(f"step '{step['id']}': approval must be true or false")
    if (step["worker"] == DELEGATE) != delegation:
        raise EngineError(f"step '{step['id']}': only Engine.delegate adds a step that starts a delegate")
    if step["worker"] not in workers and not delegation:
        raise EngineError(f"step '{step['id']}': unknown worker '{step['worker']}'")
    check_budget(step, contracts_dir)
    check_actions(step, policy)
    comp = step.get("compensate")
    if comp is None:
        return
    if not isinstance(comp, dict) or not isinstance(comp.get("worker"), str) \
            or not isinstance(comp.get("input"), dict):
        raise EngineError(f"step '{step['id']}': compensate must be a step with a worker and an input object")
    for key in sorted(set(comp) - {"worker", "input", "actions", "approval", "budget"}):
        raise EngineError(f"step '{step['id']}': unknown field '{key}' in compensate")
    check_step(dict(comp, id=f"compensate-{step['id']}"), workers, contracts_dir, policy)


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
        if req["action"] == "agent.delegate":  # whether the delegate is listed is the passport's to say
            listed = req.get("scope", {}).get("passport") in policy.get("delegates", ())
            req = dict(req, facts={**req.get("facts", {}), "delegate.listed": listed})
        decision, rule, show = check_policy.decide(policy, req)
        grant = policy.get("grant")
        if grant and decision == "auto" and req["action"] in grant["approval"]:
            decision, rule, show = "human", grant["rule"], []
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


def presented(names, reqs):
    """Each item a human's approval must present, with its value from the gated actions'
    facts or scope, or None when no action gives it."""
    return {name: next((r[k][name] for r in reqs for k in ("facts", "scope") if name in r.get(k, {})), None)
            for name in names}


def approval_id(run, step, inp, reqs, rules, values):
    """The ID of a pending approval, as hosted Barry's approvals have: the digest of the run,
    the step, the exact call, its gated actions, the mandates that gate them and the values
    shown. An answer names it, so it answers only what was shown, and an approval whose
    digest no longer matches is void."""
    return check_audit.digest({"runId": run["runId"], "step": step["id"], "call": call_digest(run, step, inp),
                               "actions": reqs, "rules": rules, "present": values})


@contextlib.contextmanager
def marked(run_id):
    """Mark the environment as inside run_id, for a step's worker or a model turn and any
    process it starts, so an answer to the queue from there is refused."""
    before = os.environ.get(RUN_ENV)
    os.environ[RUN_ENV] = run_id
    try:
        yield
    finally:
        if before is None:
            os.environ.pop(RUN_ENV, None)
        else:
            os.environ[RUN_ENV] = before


def outside_runs():
    """Refuse a person's answer from inside an engine run, where only an agent could be."""
    if os.environ.get(RUN_ENV):
        raise EngineError(f"refusing to answer from inside run {os.environ[RUN_ENV]}: an agent never "
                          "answers its own queue")


def answering_here(via="cli"):
    """Refuse a human's answer from where an agent would give one: inside an engine run, or,
    on the command line, without an interactive terminal. Neither is a lock; on one machine
    an agent with a shell can get around both, so the audit log's via and by are evidence.
    The engine refuses an answer from inside a run on its own, too."""
    outside_runs()
    if via == "cli" and not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise EngineError("refusing to answer without an interactive terminal: a person answers the "
                          "queue, at a terminal or through an MCP client that asks them")


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
    audit is the audit log's path (default: audit.jsonl beside state_dir), queue the review
    queue's directory (default: queue/ beside state_dir), and actor the opaque ID recorded
    for an answer or cancel that names no one else. clock returns the current UTC time, for
    expiry. log receives each progress line the CLI prints.
    """

    def __init__(self, state_dir=DEFAULT_STATE_DIR, workflows_dir=WORKFLOWS_DIR,
                 contracts_dir=CONTRACTS_DIR, workers=None, log=print, audit=None, actor=None,
                 passports_dir=PASSPORTS_DIR, queue=None, clock=None):
        self.state_dir = Path(state_dir).expanduser()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.workflows_dir = Path(workflows_dir).expanduser()
        self.contracts_dir = Path(contracts_dir).expanduser()
        self.passports_dir = Path(passports_dir).expanduser()
        self.audit_path = Path(audit).expanduser() if audit else self.state_dir.parent / "audit.jsonl"
        self.queue_dir = Path(queue).expanduser() if queue else self.state_dir.parent / "queue"
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.actor = actor
        self.workers = dict(WORKERS if workers is None else workers)
        self.log = log

    # Records

    def record_path(self, run_id):
        return self.state_dir / f"{run_id}.json"

    def cancel_path(self, run_id):
        return self.state_dir / f"{run_id}.cancel"

    @staticmethod
    def write(path, obj):
        """Write obj as JSON atomically: a new file, flushed to disk, then renamed."""
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(obj, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def save(self, run):
        """Write the run record atomically."""
        run["updatedAt"] = now()
        self.write(self.record_path(run["runId"]), run)
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
        written = self.append_audit(entry)
        run["audit"] = {"seq": written["seq"], "hash": written["hash"]}

    def append_audit(self, entry):
        try:
            return check_audit.append(self.audit_path, entry)
        except (check_audit.AuditError, OSError) as e:  # nothing goes on that the log can't hold
            raise EngineError(f"audit log {self.audit_path}: {e}") from None

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
            policy = dict(under_passport(policy, passport), delegates=passport["delegates"])
        if run.get("grant"):
            policy = under_grant(policy, run["grant"], passport["passport"])
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
        the pending approval when the step must wait for a human, else None). Once a human
        has approved exactly what the step would now do, only a denial is audited again: the
        answer was the decision. An approval of anything else is void, and the step waits again."""
        sid, state = step["id"], run["steps"][step["id"]]
        decided = verdict(policy, step, run)
        gated = [(req, rule, show) for req, decision, rule, show in decided if decision == "human"]
        reqs, rules, names = [req for req, _, _ in gated], [rule for _, rule, _ in gated], []
        for _, _, show in gated:
            names += [x for x in show if x not in names]
        # approval: true adds a pause; approval: false can't remove one the policy requires.
        pause = bool(step.get("approval") or rules) and not (decided and decided[-1][1] == "deny")
        values = presented(names, reqs)
        pid = approval_id(run, step, inp, reqs, rules, values) if pause else None
        given = state.get("approval") or {}
        approved = pause and given.get("decision") == "approved" and given.get("id") == pid
        for req, decision, rule, show in decided:
            word = {"auto": "allowed", "human": "paused", "deny": "denied"}[decision]
            if decision == "deny" or not approved:
                self.audit(run, "step.decided", step=sid, action=req["action"], decision=word,
                           rules=[rule] if rule else [], call=call_digest(run, step, inp, req),
                           item=pid if decision == "human" else None)
            if decision == "deny":
                return denial(policy, req, rule), None
        if not approved and (not decided or (pause and not rules)):  # a decision no action records
            self.audit(run, "step.decided", step=sid, decision="paused" if pause else "allowed",
                       rules=[], call=call_digest(run, step, inp), item=pid)
        if not pause or approved:
            return None, None
        return None, {"id": pid, "kind": "approval", "step": sid, "rules": rules, "present": names,
                      "values": values, "actions": reqs}

    def execute(self, run, crash_after=None):
        """Run every step that isn't completed, checkpointing after each one. A run being
        rolled back finishes its rollback instead, and stops there."""
        if run["status"] != "working":  # an ended or paused run never runs another step
            raise EngineError(f"run {run['runId']} is {run['status']}; only a working run executes")
        plan, policy = self.plan_of(run)
        if run["workflowVersion"] != plan["version"]:
            raise EngineError(f"run {run['runId']} started on version {run['workflowVersion']}, "
                              f"but the plan is now version {plan['version']}")
        if run.get("rollback"):
            return self.compensate(run, plan, policy, crash_after) or run
        ids = [s["id"] for s in plan["steps"]]
        for i, step in enumerate(plan["steps"]):
            sid = step["id"]
            if run["steps"][sid]["status"] == "completed":
                self.log(f"skip  {sid} (completed)")
                continue
            if self.cancel_requested(run):
                return run
            if run["steps"][sid]["status"] == "rolledBack":
                self.retry(run, sid)
            stopped = self.run_step(run, step, policy, ids[i + 1] if i + 1 < len(ids) else None, crash_after)
            if stopped:
                return stopped
        if run.get("open"):  # an open run ends only when its owner finishes it
            run["next"] = None
            self.save(run)
            return run
        try:
            result = resolve(plan["output"], run)
        except Exception as e:
            return self.end(run, "failed", error={"step": None, "message": f"output: {type(e).__name__}: {e}"})
        return self.end(run, "completed", next=None, result=result)

    def run_step(self, run, step, policy, after, crash_after=None):
        """Run one step: resolve its input, decide its actions, wait for a person or run its
        worker, and checkpoint, with after as the run's next step once it completes. Returns
        the run if it has to stop here, because it ended or is waiting, else None."""
        sid = step["id"]
        state = run["steps"][sid]
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
            denied, pending = self.decide(run, step, policy, inp)
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
        if pending:
            # Pause before the step: nothing runs until a human approves it, through the queue.
            self.pause(run, pending)
            why = f" under {', '.join(pending['rules'])}" if pending["rules"] else ""
            show = f", showing {', '.join(pending['present'])}" if pending["present"] else ""
            self.log(f"wait  {sid} (needs approval{why}{show}; review_queue.py show {pending['id']})")
            return run
        state.update(status="working", startedAt=now())
        self.save(run)
        self.log(f"run   {sid}")
        cap = step.get("budget", {})
        try:
            with marked(run["runId"]):
                if step["worker"] == DELEGATE:
                    output, cost = self.start_delegate(run, step, inp, state["idempotencyKey"])
                else:
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
        run["next"] = after
        self.audit(run, "step.ran", step=sid)
        over = self.over_delegated_budget(run)
        if over:  # the step's work is done, but a delegate stops at the budget it was given
            self.audit(run, "budget.refused", step=sid)
            self.log(f"fail  {sid} ({over})")
            return self.end(run, "failed", error={"step": sid, "message": over})
        self.save(run)
        if crash_after == sid:
            sys.stdout.flush()
            print(f"crash after {sid} (simulated); resume with: run.py resume {run['runId']}",
                  file=sys.stderr)
            os._exit(CRASH_EXIT)
        return None

    # Rollback

    def rollback(self, run_id, to, by=None, reason=None, via="cli"):
        """Roll a completed or failed run back to its step to, as a person decided, for
        reason. Each later step that had an effect outside the system is compensated first,
        newest first, by the compensate step its plan declares, decided by the policy like
        any other step, so one can wait for a person. Then each later step that ran is
        marked rolledBack, never deleted, and the run waits at the step after to, working,
        for resume. What was spent stays spent. Refused from inside a run."""
        outside_runs()
        run = self.load(run_id)
        if run["status"] not in ("completed", "failed"):
            raise EngineError(f"run {run['runId']} is {run['status']}; only a completed or failed run "
                              "can be rolled back")
        if via not in check_audit.VIA:
            raise EngineError(f"via must be one of {', '.join(check_audit.VIA)}")
        plan, _ = self.plan_of(run)
        if run["workflowVersion"] != plan["version"]:
            raise EngineError(f"run {run['runId']} started on version {run['workflowVersion']}, "
                              f"but the plan is now version {plan['version']}")
        ids = [s["id"] for s in plan["steps"]]
        if to not in ids or run["steps"][to]["status"] != "completed":
            raise EngineError(f"run {run['runId']} has no completed step '{to}' to roll back to")
        if not isinstance(reason, str) or not reason.strip():
            raise EngineError("a rollback needs a reason")
        by = actor_id(by or self.actor)
        steps = {s["id"]: s for s in plan["steps"]}
        later = [sid for sid in ids[ids.index(to) + 1:]
                 if run["steps"][sid]["status"] not in ("not_started", "rolledBack")]
        # A step that failed before its worker started had no effect to compensate.
        effects = [sid for sid in later if has_effect(steps[sid]) and run["steps"][sid]["startedAt"]]
        bare = [sid for sid in effects if "compensate" not in steps[sid]]
        if bare:
            raise EngineError(f"run {run['runId']} can't be rolled back past {', '.join(bare)}: "
                              f"{'it takes' if len(bare) == 1 else 'each takes'} an action with an effect "
                              "outside the system, and the plan declares no compensate step for it")
        undo = [[sid, compensation_id(sid, run["steps"][sid]["attempt"])] for sid in reversed(effects)]
        undo = [[sid, cid] for sid, cid in undo if run["steps"].get(cid, {}).get("status") != "completed"]
        clash = [cid for _, cid in undo if cid in steps]
        if clash:
            raise EngineError(f"the plan has a step named {clash[0]}, the name of a compensating step")
        record = {"to": to, "next": ids[ids.index(to) + 1] if ids.index(to) + 1 < len(ids) else None,
                  "compensate": undo, "rolledBack": later, "by": by, "via": via, "at": now(),
                  "reason": reason, "status": run["status"], "result": run["result"], "error": run["error"]}
        record["id"] = check_audit.digest(record)
        if run.get("rollback"):  # an earlier rollback that didn't finish; its record is kept
            run.setdefault("rollbacks", []).append(run["rollback"])
        for _, cid in undo:
            old = run["steps"].get(cid)
            run["steps"][cid] = new_step_state(run["runId"], cid)
            if old:  # a compensation that failed before is tried again, with its key
                run["steps"][cid]["history"] = old.pop("history", []) + [old]
        run.update(status="working", rollback=record, result=None, error=None, pending=None)
        self.audit(run, "rollback", step=to, by=by, via=via, record=record["id"])
        self.save(run)
        first = f", compensating {', '.join(sid for sid, _ in undo)} first" if undo else ""
        self.log(f"rollback {run['runId']} to {to}{first}")
        return self.execute(run)

    def compensate(self, run, plan, policy, crash_after=None):
        """Finish the run's rollback: run its compensating steps, newest first, then mark the
        later steps rolledBack and set next to the step after the target. Returns the run if
        it has to stop first, else None."""
        record = run["rollback"]
        steps = {s["id"]: s for s in plan["steps"]}
        for n, (sid, cid) in enumerate(record["compensate"]):
            if run["steps"][cid]["status"] == "completed":
                continue
            if self.cancel_requested(run):
                return run
            after = record["compensate"][n + 1][1] if n + 1 < len(record["compensate"]) else record["next"]
            stopped = self.run_step(run, dict(steps[sid]["compensate"], id=cid), policy, after, crash_after)
            if stopped:
                return stopped
        at = now()
        for sid in record["rolledBack"]:
            state = run["steps"][sid]
            state.update(status="rolledBack", undone={"status": state["status"], "at": at, "rollback": record["id"]})
        record["endedAt"] = at
        run.update(next=record["next"], rollback=None)
        run.setdefault("rollbacks", []).append(record)
        self.save(run)
        self.log(f"rolled back {run['runId']} to {record['to']}; resume with: run.py resume {run['runId']}")
        return None

    def retry(self, run, sid):
        """Start a rolled-back step over as a new attempt, with a new idempotency key so its
        effect happens again, and its earlier attempts kept in its history."""
        old = run["steps"][sid]
        attempt = old["attempt"] + 1
        state = new_step_state(run["runId"], sid)
        state.update(attempt=attempt, idempotencyKey=f"{run['runId']}:{sid}:{attempt}",
                     history=old.pop("history", []) + [old])
        run["steps"][sid] = state

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

    def append(self, run, step, delegation=False):
        """Add a step to an open run. It runs on the next execute, decided, budgeted and
        checkpointed like a planned step."""
        self.working_open_run(run, "grow")
        if not isinstance(step, dict) or not isinstance(step.get("id"), str) or not step["id"] \
                or not isinstance(step.get("worker"), str) or not isinstance(step.get("input"), dict):
            raise EngineError("a step needs an id, a worker and an input object")
        step = copy.deepcopy(step)  # the run keeps the step as it was checked
        if step["id"] in run["steps"]:
            raise EngineError(f"step '{step['id']}': run {run['runId']} already has a step with that id")
        check_step(step, self.workers, self.contracts_dir, load_policy(run["policy"]), delegation)
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
            with marked(run["runId"]):
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
        over = self.over_delegated_budget(run)
        if over:
            self.audit(run, "budget.refused", turn=turn_id)
            self.end(run, "failed", error={"step": None, "turn": turn_id, "message": over})
            self.log(f"fail  turn {turn_id} ({over})")
            raise Stopped(run, over)
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

    def escalate(self, run, ask_id, question, values=None):
        """Ask a person in an open run, as the Charter requires on an ambiguous decision,
        missing credentials or repeated failure. The run waits in input_required with an
        escalation in the review queue. Returns the person's answer once there is one, else
        None, so a resumed loop asks each question once."""
        answered = run.get("answers", {}).get(ask_id)
        if answered:
            return answered["text"]
        pending = run.get("pending") or {}
        if run["status"] == "input_required" and pending.get("ask") == ask_id:
            return None
        if not isinstance(ask_id, str) or not ask_id or not isinstance(question, str) or not question.strip():
            raise EngineError("an escalation needs an id and a question")
        if self.cancel_requested(run):
            raise Stopped(run, f"run {run['runId']} is {run['status']}")
        self.working_open_run(run, "escalate")
        values = dict(values or {})
        pid = check_audit.digest({"runId": run["runId"], "ask": ask_id, "question": question, "values": values})
        self.audit(run, "escalation.raised", item=pid)
        self.pause(run, {"id": pid, "kind": "escalation", "ask": ask_id, "question": question, "values": values})
        self.log(f"ask   {ask_id} (review_queue.py show {pid})")
        return None

    # Delegation

    def delegate(self, run, step_id, passport, context, whole_context=False):
        """Hand work to the agent whose passport is named passport, as step step_id of the
        open run. The approval policy decides agent.delegate with that passport as its
        scope, and the step waits for a person or fails the run as any step's would. context
        is the list of items passed, never the whole conversation: whole_context says
        whether it is, and the policy refuses it if so.

        Returns the delegate's run: an open run under the delegate's passport, narrowed by
        this run's grant, with a budget carved out of what this run has left. Returns None
        while the delegation waits for a person, and the run once it is completed when
        called again with the same step_id. Raises Stopped when the run has failed or been
        cancelled, a denied delegation among them."""
        if step_id not in run["steps"]:
            self.working_open_run(run, "delegate")
            parent = self.passport_of(run)
            if parent is None:
                raise EngineError(f"run {run['runId']} runs under no passport, so there is nothing to narrow "
                                  "a delegate's grant from")
            if passport == parent["passport"]:
                raise EngineError(f"{passport} is run {run['runId']}'s own passport: a clone runs as its parent, "
                                  "inside this run, so take its steps and turns here")
            if not isinstance(passport, str) or not isinstance(context, list) or not isinstance(whole_context, bool):
                raise EngineError("a delegation names a passport, passes its context as a list of items and says "
                                  "whether that is the whole context")
            self.append(run, {"id": step_id, "worker": DELEGATE, "input": {"passport": passport, "context": context},
                              "actions": [{"action": "agent.delegate", "scope": {"passport": passport},
                                           "facts": {"context.whole": whole_context}}]}, delegation=True)
        elif not any(s["id"] == step_id and s["worker"] == DELEGATE for s in (run.get("plan") or {}).get("steps", [])):
            raise EngineError(f"step '{step_id}' of run {run['runId']} isn't a delegation")
        if run["steps"][step_id]["status"] != "completed" and run["status"] == "working":
            run = self.execute(run)
        state = run["steps"][step_id]
        if state["status"] == "completed":
            return self.load(state["output"]["runId"])
        if run["status"] in ("failed", "cancelled"):
            raise Stopped(run, (run.get("error") or {}).get("message") or f"run {run['runId']} is {run['status']}")
        return None

    def start_delegate(self, run, step, inp, key):
        """The work of a delegation step: start the delegate's run, once, and log the
        delegation. Returns (output, cost) as a worker does."""
        child_id = "run_" + check_audit.digest(key)[7:23]  # the same run, should the step run again
        if self.record_path(child_id).is_file():
            child = self.load(child_id)
        else:
            parent = self.passport_of(run)
            passport, _ = load_passport(inp["passport"], self.passports_dir)
            grant = narrow(run.get("grant") or parent["permissions"], passport["permissions"])
            budget = self.carve(run, passport)
            child = self.new_run({"name": passport["passport"], "version": 1, "steps": []}, run["policy"],
                                 {"context": inp["context"]}, passport["passport"])
            child.update(runId=child_id, open=True, plan={"name": passport["passport"], "version": 1, "steps": []},
                         turns={}, grant=grant, budget=budget, parent={"runId": run["runId"], "step": step["id"]})
            self.audit(run, "delegation", step=step["id"], delegate=child["agent"], grant=check_audit.digest(grant),
                       context=[check_audit.digest(item) for item in inp["context"]])
            self.audit(child, "run.started")
            self.save(child)
            self.log(f"start {child_id} ({passport['passport']}, delegated by {run['runId']})")
        if child_id not in run.setdefault("delegations", []):
            run["delegations"].append(child_id)
        output = {"runId": child_id, "passport": child["agent"]["passport"], "version": child["agent"]["version"],
                  "grant": check_audit.digest(child["grant"]), "budget": child["budget"]}
        return output, {"usd": 0.0, "tokens": 0}

    def budget_of(self, run):
        """What run may spend: the budget it was delegated, else its passport's, else None."""
        if run.get("budget"):
            return run["budget"]
        passport = self.passport_of(run)
        return passport["budget"] if passport else None

    def spent(self, run):
        """What run has spent, counting each delegate it started: what an open one holds in
        reserve, and what an ended one spent."""
        total = {"usd": run["cost"]["usd"], "tokens": run["cost"]["tokens"]}
        for child_id in run.get("delegations", []):
            child = self.load(child_id)
            part = self.spent(child) if child["status"] in TERMINAL else child["budget"]
            for k in total:
                total[k] += part.get(k, 0)
        total["usd"] = round(total["usd"], 6)
        return total

    def carve(self, run, passport):
        """The budget for a delegate under passport: each figure of its passport's, cut to
        what run has left of its own. Time isn't spent from a pool, so seconds is the lower
        of the two. Raises OverBudget when nothing is left."""
        limit = self.budget_of(run) or {}
        spent = self.spent(run)
        left = {k: limit[k] - spent[k] for k in ("usd", "tokens") if k in limit}
        empty = [k for k, v in left.items() if v <= 0]
        if empty:
            raise OverBudget(f"nothing is left of run {run['runId']}'s {' or '.join(empty)} to delegate")
        budget = {}
        for k in ("usd", "tokens", "seconds"):
            figures = [x for x in (passport["budget"].get(k), limit.get(k) if k == "seconds" else left.get(k))
                       if x is not None]
            if figures:
                budget[k] = round(min(figures), 6) if k == "usd" else min(figures)
        return budget

    def over_delegated_budget(self, run):
        """Why a delegate's run is over the budget it was delegated, or None."""
        if not run.get("budget"):
            return None
        over = over_cost(self.spent(run), run["budget"])
        return f"{over} (the budget it was delegated)" if over else None

    # The review queue

    def item_path(self, item_id):
        return self.queue_dir / f"{item_id.split(':', 1)[1]}.json"

    def pause(self, run, pending):
        """Put the run in input_required on pending, which expires in seven days, and put it
        in the review queue. The run record is saved first: it is the source of truth."""
        created = self.clock()
        pending.update(createdAt=stamp(created), expiresAt=stamp(created + EXPIRY))
        run.update(status="input_required", pending=pending)
        self.save(run)
        if pending["kind"] == "approval":
            source = {"runId": run["runId"], "step": pending["step"]}
            present = {k: pending[k] for k in ("actions", "rules", "values")}
        else:
            source = {"runId": run["runId"], "ask": pending["ask"]}
            present = {"question": pending["question"], "values": pending["values"]}
        self.write(self.item_path(pending["id"]), {
            "id": pending["id"], "kind": pending["kind"], "source": source, "agent": run.get("agent"),
            "present": present, "createdAt": pending["createdAt"], "expiresAt": pending["expiresAt"],
            "status": "open", "answer": None})

    def drift(self, agent, result, present, finding="drift"):
        """Put what the trust evaluation found in the review queue. agent is {passport,
        version, sha256}, result the id of the results.jsonl entry that records the runs, and
        present what a person needs to judge it. finding is drift (the agent's runs fell below
        its baseline, which holds promotion until a person answers), or a flag that doesn't
        hold it: unconfirmed-miss (a critical case missed once), cost (a run cost more than
        twice its baseline's per case) or not-run (the eval didn't answer every case; the
        trust evaluation holds promotion after several in a row). None expires."""
        if finding not in FINDINGS:
            raise EngineError(f"a trust evaluation finds one of {', '.join(FINDINGS)}, not {finding!r}")
        created = stamp(self.clock())
        source = {"passport": agent["passport"], "version": agent["version"], "result": result, "finding": finding}
        item_id = check_audit.digest({"kind": "drift", "source": source, "present": present, "createdAt": created})
        self.append_audit({"kind": "drift" if finding == "drift" else "eval.flagged", "agent": agent, "item": item_id})
        item = {"id": item_id, "kind": "drift", "source": source, "agent": agent, "present": present,
                "createdAt": created, "expiresAt": None, "status": "open", "answer": None}
        self.write(self.item_path(item_id), item)
        return item

    def close_item(self, item_id, status, answer=None):
        path = self.item_path(item_id)
        if path.is_file():
            item = json.loads(path.read_text())
            item.update(status=status, answer=answer)
            self.write(path, item)

    def expire_if_due(self, run):
        """Fail the run if its approval or escalation has waited past its expiry. Returns
        whether it did."""
        pending = run.get("pending") or {}
        if run["status"] != "input_required" or not pending.get("expiresAt") \
                or self.clock() < parse_time(pending["expiresAt"]):
            return False
        run.update(status="failed", pending=None, error={
            "step": pending.get("step"), "message": f"the {pending['kind']} expired unanswered at {pending['expiresAt']}"})
        self.audit(run, "run.expired", step=pending.get("step"), item=pending["id"])
        self.save(run)
        self.close_item(pending["id"], "expired")
        self.log(f"expire {run['runId']} ({pending['kind']} unanswered since {pending['createdAt']})")
        return True

    def settle(self, item):
        """Bring an open item up to date with its run, the source of truth: expire it when it
        is due, and close it if the run answered it some other way, such as by a cancel."""
        if item["status"] != "open" or item["kind"] == "drift":
            return item
        path = self.record_path(item["source"]["runId"])
        if not path.is_file():
            return item
        run = json.loads(path.read_text())
        if (run.get("pending") or {}).get("id") == item["id"]:
            if self.expire_if_due(run):
                item.update(status="expired")
            return item
        given = run.get("answers", {}).get(item["source"].get("ask")) \
            or run["steps"].get(item["source"].get("step"), {}).get("approval")
        if given and given.get("id") == item["id"]:
            self.close_item(item["id"], "answered", given)
        elif run["status"] == "cancelled":
            self.close_item(item["id"], "answered", {"decision": "cancelled", "by": None, "at": run.get("updatedAt")})
        elif run["status"] == "failed" and "expired unanswered" in (run.get("error") or {}).get("message", ""):
            self.close_item(item["id"], "expired")
        else:
            return item
        return json.loads(self.item_path(item["id"]).read_text())

    def items(self, status="open"):
        """The queue's items with status (all of them for None), oldest first, each brought
        up to date with its run."""
        found = []
        for path in sorted(self.queue_dir.glob("*.json")):
            item = self.settle(json.loads(path.read_text()))
            if status is None or item["status"] == status:
                found.append(item)
        return sorted(found, key=lambda i: i["createdAt"])

    def item(self, ref):
        """The item whose ID is ref: in full, or the start of its hex digits (8 at least)."""
        hexes = ref.split(":", 1)[1] if ref.startswith("sha256:") else ref
        if not re.fullmatch(r"[0-9a-f]{8,64}", hexes):
            raise EngineError(f"{ref!r} isn't an item ID: give sha256:<hex>, or its first 8 or more hex digits")
        paths = sorted(self.queue_dir.glob(f"{hexes}*.json"))
        if len(paths) != 1:
            raise EngineError(f"no item {ref} in the queue" if not paths else f"{ref} names more than one item")
        return self.settle(json.loads(paths[0].read_text()))

    def answer_item(self, ref, decision, by=None, reason=None, text=None, via="cli"):
        """Answer the queue item ref. decision is approved or denied for an approval or
        drift, and answered (with text) for an escalation."""
        outside_runs()
        item = self.item(ref)
        if item["status"] != "open":
            raise EngineError(f"item {item['id']} is {item['status']}; only an open item can be answered")
        if item["kind"] != "drift":
            return self.answer(item["source"]["runId"], decision, by, reason, item["id"], via, text)
        if decision not in ("approved", "denied"):
            raise EngineError("drift is answered with approve or deny")
        by, reason = actor_id(by or self.actor), self.reason_for(decision, reason)
        answer = {"decision": decision, "by": by, "at": now(), "via": via, **({"reason": reason} if reason else {})}
        self.append_audit({"kind": "drift.answered", "agent": item["agent"], "item": item["id"],
                           "decision": decision, "by": by, "via": via})
        self.close_item(item["id"], "answered", answer)
        self.log(f"{'approve' if decision == 'approved' else 'deny'} {item['source']['finding']} {item['id']}")
        return json.loads(self.item_path(item["id"]).read_text())

    @staticmethod
    def reason_for(decision, reason):
        if decision != "denied":
            return None
        if not isinstance(reason, str) or not reason.strip():
            raise EngineError("deny needs a reason")
        return reason

    # Commands on a run by its ID

    def resume(self, run_id):
        run = self.load(run_id)
        if (run["status"] not in TERMINAL and self.cancel_requested(run)) or self.expire_if_due(run):
            return run
        if run["status"] in TERMINAL:
            self.log(f"run {run['runId']} is already {run['status']}")
            return run
        if run["status"] == "input_required":  # resuming never answers an approval
            self.log(f"run {run['runId']} is waiting for approval of {run['pending']['step']}")
            return run
        self.log(f"resume {run['runId']} at {run['next']}")
        return self.execute(run)

    def answer(self, run_id, decision, by=None, reason=None, item_id=None, via="cli", text=None):
        """Record a person's answer to what a run is waiting on. An approval is approved (the
        step runs) or denied (the run fails); an escalation is answered with text, which its
        open run's loop reads back from escalate. item_id, when given, must be the pending
        approval ID, so an answer only answers what was shown. Refused from inside a run."""
        outside_runs()
        run = self.load(run_id)
        if self.expire_if_due(run):
            raise EngineError(f"run {run['runId']} waited too long: {run['error']['message']}")
        pending = run.get("pending")
        if run["status"] != "input_required" or not pending:
            raise EngineError(f"run {run['runId']} isn't waiting for an answer (it is {run['status']})")
        if item_id is not None and item_id != pending.get("id"):
            raise EngineError(f"{item_id} isn't what run {run['runId']} is waiting on, which is "
                              f"{pending.get('id')}; an answer answers only what was shown")
        if via not in check_audit.VIA:
            raise EngineError(f"via must be one of {', '.join(check_audit.VIA)}")
        kind = pending.get("kind")
        if kind == "escalation":
            if decision != "answered" or not isinstance(text, str) or not text.strip():
                raise EngineError("an escalation is answered with text (review_queue.py answer ID --text ...)")
        elif decision not in ("approved", "denied"):
            raise EngineError(f"run {run['runId']} is waiting for an approval: approve or deny it")
        reason = self.reason_for(decision, reason)
        by = actor_id(by or self.actor)
        record = {"decision": decision, "by": by, "at": now(), "via": via}
        if pending.get("id"):
            record["id"] = pending["id"]
        if reason:
            record["reason"] = reason
        run["pending"] = None
        if kind == "escalation":
            record["text"] = text
            run.setdefault("answers", {})[pending["ask"]] = record
            run["status"] = "working"
            self.audit(run, "escalation.answered", item=pending["id"], by=by, via=via)
            self.save(run)
            self.close_item(pending["id"], "answered", record)
            self.log(f"answer {pending['ask']}")
            return run
        sid = pending["step"]
        run["steps"][sid]["approval"] = record
        self.audit(run, "approval.answered", step=sid, decision=decision, by=by, item=pending.get("id"), via=via)
        if decision == "denied":
            self.log(f"deny  {sid}")
            run = self.end(run, "failed", error={"step": sid, "message": f"approval denied by {by}: {reason}"})
            if pending.get("id"):
                self.close_item(pending["id"], "answered", record)
            return run
        run["status"] = "working"
        self.save(run)  # the approval is durable before the step runs
        if pending.get("id"):
            self.close_item(pending["id"], "answered", record)
        self.log(f"approve {sid}")
        return self.execute(run)

    def approve(self, run_id, by=None, item_id=None, via="cli"):
        return self.answer(run_id, "approved", by, None, item_id, via)

    def deny(self, run_id, reason, by=None, item_id=None, via="cli"):
        return self.answer(run_id, "denied", by, reason, item_id, via)

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
        pending = run.get("pending") or {}
        run.update(status="cancelled", pending=None,
                   error={"step": run.get("next"), "message": f"cancelled by {request['by']}"})
        self.audit(run, "run.cancelled", step=run.get("next"), by=request["by"])
        self.save(run)
        path.unlink(missing_ok=True)
        if pending.get("id"):  # a cancel answers what the run was waiting on
            self.close_item(pending["id"], "answered", {"decision": "cancelled", **request})
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


def cmd_rollback(args, engine):
    answering_here()
    run = engine.rollback(args.run_id, args.to, args.by, args.reason)
    return 0 if run["status"] == "working" else report(run)


def cmd_status(args, engine):
    run = engine.load(args.run_id)
    engine.expire_if_due(run)
    requested = " (cancel requested)" if engine.cancel_path(run["runId"]).is_file() else ""
    print(f"{run['runId']}: {run['status']}{requested}, next: {run['next']}")
    return report(run)


COMMANDS = {
    "start": cmd_start,
    "resume": lambda args, engine: report(engine.resume(args.run_id)),
    "status": cmd_status,
    "approve": lambda args, engine: answering_here() or report(engine.approve(args.run_id, args.by, args.id)),
    "deny": lambda args, engine: answering_here() or report(engine.deny(args.run_id, args.reason, args.by, args.id)),
    "cancel": lambda args, engine: report(engine.cancel(args.run_id, args.by)),
    "rollback": cmd_rollback,
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
        if name != "cancel":
            p.add_argument("--id", metavar="APPROVAL-ID",
                           help="The approval ID being answered (run.py status shows it); refused "
                                "if the run is waiting on anything else")
    rollback = sub.add_parser("rollback", help="Roll a completed or failed run back to an earlier step")
    rollback.add_argument("run_id")
    rollback.add_argument("--to", required=True, metavar="STEP", help="The step to roll back to; it stays done")
    rollback.add_argument("--reason", required=True, help="Why, kept in the run record")
    rollback.add_argument("--by", metavar="ACTOR-ID",
                          help="Who rolled it back, as an opaque ID (default: $WORKFLOWS_HIVE_ACTOR)")
    args = ap.parse_args()

    try:
        engine = Engine(args.state_dir, args.workflows_dir, args.contracts_dir, audit=args.audit,
                        actor=os.environ.get("WORKFLOWS_HIVE_ACTOR"))
        sys.exit(COMMANDS[args.command](args, engine))
    except EngineError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
