#!/usr/bin/env python3
"""An agent's trust evaluation: judge its runs against the baseline in its passport, record
them, and decide whether a change to the agent may be promoted.

A runner that calls the agent's model, such as deploy/azure/eval/run.py, runs the suite and
hands each case's outcome here. A run drifts when it meets fewer cases than the baseline
minus the passport's threshold, or misses a critical case. A run that drifts is run once
more, and drift is recorded only when both runs drift. What the evaluation finds goes to
the workflows-hive review queue: drift, which holds promotion until a person answers it,
and three flags that don't: a critical case missed in only one run (unconfirmed-miss), a
run costing more than twice its baseline's per case (cost), and an eval the ceiling
refused (not-run). Each evaluation is an entry in results.jsonl and in the audit log.

Promotion is what deploy.sh checks before it deploys: the passport is valid, its baseline
was recorded against its exact pins, and no drift for it holds promotion. Design:
docs/assurance-loop.md.

Standard library only.

Usage:
  python3 scripts/trust_eval.py promotion PERSONA [--queue-dir DIR]
  python3 scripts/trust_eval.py pins PERSONA      # print the digest of a passport's pins
"""
import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

HIVE = Path(__file__).resolve().parent.parent
REPO_ROOT = HIVE.parent.parent
COST_FACTOR = 2  # a run costing more than this times its baseline's per case is flagged


def load(path, name):
    """A script loaded by path, so it never shadows or is shadowed by another module."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


vp = load(HIVE / "scripts" / "validate_passports.py", "validate_passports")
engine = load(REPO_ROOT / "hives" / "workflows-hive" / "scripts" / "run.py", "workflows_engine")


class EvalError(Exception):
    """A passport, suite or configuration the evaluation can't run against."""


def passport(persona):
    """The persona's passport, checked, with an eval to run."""
    path = HIVE / "passports" / persona / "passport.json"
    if not path.is_file():
        raise EvalError(f"no passport at passports/{persona}/passport.json")
    problems = vp.check(path)
    if problems:
        raise EvalError(f"passport {persona} is invalid: {problems[0]}")
    p = json.loads(path.read_text())
    if "eval" not in p:
        raise EvalError(f"passport {persona} has no eval: only an agent with a model pin is evaluated")
    return p


def agent(p):
    """How the audit log and the queue name a passport: {passport, version, sha256}."""
    return {"passport": p["passport"], "version": p["version"], "sha256": vp.digest(p)}


def pins_digest(p):
    """The digest of a passport's pins, as canonical JSON: what a result was recorded against."""
    return "sha256:" + hashlib.sha256(vp.canonical(p["pins"])).hexdigest()


def cases(p):
    suite = json.loads((REPO_ROOT / p["eval"]["suite"]).read_text(encoding="utf-8"))
    return suite["cases"] if isinstance(suite, dict) else suite


def critical(suite):
    return {c["id"] for c in suite if c.get("critical")}


def results_file(p):
    """The results.jsonl the passport's baseline is recorded in, where its evals are recorded."""
    return REPO_ROOT / p["eval"]["baseline"]["result"].split("#", 1)[0]


def baseline(p):
    """The results.jsonl entry that records the passport's baseline."""
    return vp.baseline_result(p["eval"]["baseline"]["result"])


def check_config(p, persona, capability, prompt_files):
    """Refuse to evaluate a configuration that doesn't run what the passport pins: its
    persona, its contract, and its prompt files in their order. prompt_files are paths from
    the repo root. Which model a deployment serves is checked where it is deployed."""
    problems = []
    if persona != p["passport"]:
        problems.append(f"the configuration is for {persona}, not {p['passport']}")
    if capability != p["contract"]["capability"]:
        problems.append(f"the configuration runs {capability}, not {p['contract']['capability']}")
    pinned = [f["path"] for f in p["pins"]["prompt"]]
    if list(prompt_files) != pinned:
        problems.append(f"the configuration's prompt files are {list(prompt_files)}, not the pinned {pinned}")
    if problems:
        raise EvalError("; ".join(problems))


def run_record(suite, outcomes):
    """One run of the suite, from its cases' outcomes in order: each {id, pass, usd,
    seconds}. Fewer outcomes than cases means the run stopped early."""
    ran = len(outcomes)
    record = {"met": sum(1 for o in outcomes if o.get("pass")), "ran": ran, "of": len(suite),
              "missed": [o["id"] for o in outcomes if not o.get("pass")],
              "usd": round(sum(o.get("usd") or 0 for o in outcomes), 6)}
    seconds = [o["seconds"] for o in outcomes if o.get("seconds") is not None]
    if seconds:
        record["seconds"] = round(sum(seconds), 2)
    return record


def drifts(p, suite, run):
    """Whether one complete run drifts: fewer cases met than the baseline minus the
    threshold, or any critical case missed."""
    base = p["eval"]["baseline"]
    return run["met"] < base["met"] - p["eval"]["threshold"] or bool(critical(suite) & set(run["missed"]))


def per_case(run):
    return run["usd"] / run["ran"] if run["ran"] else 0


def findings(p, suite, runs, base_entry):
    """What the runs found, in results.jsonl's terms."""
    if any(r["ran"] < r["of"] for r in runs):
        return ["not-run"]
    found = []
    if len(runs) == 2 and all(drifts(p, suite, r) for r in runs):
        found.append("drift")
    elif any(critical(suite) & set(r["missed"]) for r in runs):
        found.append("unconfirmed-miss")
    base_runs = ((base_entry or {}).get("eval") or {}).get("runs") or []
    if base_runs and per_case(base_runs[0]) > 0 \
            and any(per_case(r) > COST_FACTOR * per_case(base_runs[0]) for r in runs):
        found.append("cost")
    return found


def outcome(found):
    return "failed" if {"drift", "not-run"} & set(found) else "partial" if found else "passed"


def next_id(path, at, persona):
    """A new result id: the date, the persona and eval, with -2, -3 and on when taken."""
    taken = vp.read_results(path) if path.is_file() else {}
    base = f"{at}-{persona}-eval"
    rid, n = base, 1
    while rid in taken:
        n += 1
        rid = f"{base}-{n}"
    return rid


def describe(p, runs, found, refused=None):
    scores = " then ".join(f"{r['met']} of {r['of']}" + (f" ({r['ran']} ran)" if r["ran"] < r["of"] else "")
                           for r in runs)
    base = p["eval"]["baseline"]
    text = (f"{p['passport']} v{p['version']} met {scores} against a baseline of {base['met']} of "
            f"{base['of']}, for ${sum(r['usd'] for r in runs):.4f}.")
    if refused:
        text += f" The ceiling refused the rest: {refused}"
    return text + (f" Found: {', '.join(found)}." if found else " Within its baseline.")


def result(p, suite, runs, at, model, commit=None, refused=None, path=None):
    """The results.jsonl entry for an evaluation's runs, to be appended to path (default:
    the file the passport's baseline is in). at is a UTC datetime."""
    base_entry = baseline(p)
    found = findings(p, suite, runs, base_entry)
    path = Path(path) if path else results_file(p)
    record = {"passport": p["passport"], "version": p["version"], "pins": pins_digest(p),
              "suite": p["eval"]["suite"], **({"commit": commit} if commit else {}), "model": model,
              "baseline": base_entry["id"] if base_entry else None, "runs": runs, "findings": found}
    return {"id": next_id(path, at.strftime("%Y-%m-%d"), p["passport"]), "at": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "kind": "eval", "subject": f"{p['passport']} {p['contract']['capability']} trust evaluation",
            "outcome": outcome(found), "summary": describe(p, runs, found, refused),
            "evidence": [{"kind": "file", "path": p["eval"]["suite"]}], "eval": record}


def record(e, p, entry, path=None):
    """Append entry to the results file, audit it, and send each finding to the review
    queue through the engine e. Returns the queue items."""
    path = Path(path) if path else results_file(p)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    who = agent(p)
    e.append_audit({"kind": "eval.ran", "agent": who, "result": entry["id"]})
    base = p["eval"]["baseline"]
    present = {"summary": entry["summary"], "baseline": {"result": entry["eval"]["baseline"], "met": base["met"],
                                                         "of": base["of"]},
               "threshold": p["eval"]["threshold"], "runs": entry["eval"]["runs"]}
    return [e.drift(who, entry["id"], present, finding) for finding in entry["eval"]["findings"]]


def promotion(persona, e):
    """Why the persona's passport can't be promoted, or [] when it can: it must be valid,
    its baseline recorded against its exact pins, and no drift may hold it in the queue of
    the engine e."""
    try:
        p = passport(persona)
    except EvalError as err:
        return [str(err)]
    return holds(p, baseline(p), e.items(None))


def holds(p, entry, items):
    """What holds the passport p back, given its baseline's results.jsonl entry and the
    review queue's items. Drift holds it while it is open, and, once denied, until a newer
    baseline is recorded."""
    problems = []
    persona = p["passport"]
    if entry["eval"]["pins"] != pins_digest(p):
        problems.append(f"passport {persona} v{p['version']}'s baseline, {entry['id']}, was recorded against other "
                        f"pins; run its trust evaluation against these ({pins_digest(p)}) and record the result "
                        "as its baseline")
    since = str(entry["at"])
    for item in items:
        source = item["source"]
        if item["kind"] != "drift" or source.get("passport") != persona or source.get("finding") != "drift":
            continue
        answer = item.get("answer") or {}
        if item["status"] == "open":
            problems.append(f"drift {item['id']} holds promotion until a person answers it")
        elif answer.get("decision") == "denied" and item["createdAt"][:len(since)] >= since:
            problems.append(f"drift {item['id']} was denied ({answer.get('reason')}); "
                            "a newer baseline must be recorded before promotion")
    return problems


def main():
    ap = argparse.ArgumentParser(description="An agent's trust evaluation: its baseline and promotion.")
    sub = ap.add_subparsers(dest="command", required=True)
    pr = sub.add_parser("promotion", help="Check a passport may be promoted (deployed)")
    pr.add_argument("persona")
    pr.add_argument("--state-dir", default=str(engine.DEFAULT_STATE_DIR), help="Where run records live")
    pr.add_argument("--queue-dir", help="The review queue (default: queue/ beside --state-dir)")
    sub.add_parser("pins", help="Print the digest of a passport's pins").add_argument("persona")
    args = ap.parse_args()
    if args.command == "pins":
        try:
            print(pins_digest(passport(args.persona)))
        except EvalError as err:
            sys.exit(str(err))
        return 0
    e = engine.Engine(args.state_dir, queue=args.queue_dir, log=lambda *a: None)
    problems = promotion(args.persona, e)
    for problem in problems:
        print(f"refused: {problem}", file=sys.stderr)
    if not problems:
        print(f"{args.persona}: baseline recorded against its pins, and no drift holds it")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
