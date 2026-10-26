"""Run the governance-review cases: Patricia's trust evaluation, or a comparison of models.

Each --config is a hive_a2a config (config.example.toml) naming one model. The cases go
through the server's own reviewer: the same system prompt, contract input and output
checks, and per-call budget, with no server or auth in between.

Run from hives/agents-hive/servers/a2a with its requirements installed, signed in with
`az login` when a config uses auth = "entra".

With --passport it is the agent's trust evaluation (docs/assurance-loop.md), against the
baseline in its passport, with one config that must run what the passport pins: its
persona, contract and prompt files, on the deployment that serves its pinned model. Each
call is metered into the config's ledger, against its monthly ceiling, as the server's
are, so the ledger the config names should be the agent's own. A run that drifts is run
once more. The evaluation is appended to the passport's results.jsonl and the audit log,
and what it finds goes to the review queue (scripts/trust_eval.py says what each finding
means). It exits 1 when it found drift or couldn't run.

  python ../../deploy/azure/eval/run.py --passport patricia --config patricia.toml

Without --passport it compares models, each --config once, with each call held against a
throwaway ledger so the comparison doesn't touch a server's:

  python ../../deploy/azure/eval/run.py --config a.toml --config b.toml --out results.json

--spacing keeps that many seconds between the starts of one model's calls, for a deployment
whose quota allows few requests a minute (Foundry enforces it over short windows, so a
burst can be refused well under the minute's limit).

Prints a table of verdicts per case, how many each run got right, and what it cost.
"""
import argparse
import asyncio
import importlib.util
import json
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
HIVE = HERE.parents[2]
sys.path.insert(0, str(HIVE / "servers/a2a"))

from hive_a2a import providers  # noqa: E402
from hive_a2a.config import REPO_ROOT, load  # noqa: E402
from hive_a2a.ledger import Ledger  # noqa: E402
from hive_a2a.review import Reviewer  # noqa: E402


def trust_eval():
    spec = importlib.util.spec_from_file_location("trust_eval", HIVE / "scripts" / "trust_eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def run_model(config, cases, spacing=0, ledger=None):
    """One run of the cases, each call held against ledger's ceiling and recorded in it, as
    the server's are (a throwaway ledger when None). Returns each case's outcome, and the
    ceiling's refusal if it stopped the run before the last case."""
    provider = providers.create(config.model)
    with tempfile.TemporaryDirectory() as tmp:
        ledger = ledger or Ledger(Path(tmp) / "ledger.jsonl", config.monthly_ceiling_usd)
        reviewer = Reviewer(config, ledger, provider)
        results, refused, started = [], None, None
        try:
            for case in cases:
                if started is not None and spacing:
                    await asyncio.sleep(max(0, spacing - (time.monotonic() - started)))
                plan = reviewer.plan({"proposal": case["proposal"], "context": case["context"]})
                if plan is None:
                    results.append({"id": case["id"], "verdict": None, "pass": False,
                                    "error": "too large for the contract's per-call budget"})
                    continue
                refusal = await ledger.reserve(plan.max_usd)
                if refusal:
                    refused = refusal.text()
                    break
                key = f"eval-{uuid.uuid4().hex}"
                entry = reviewer.unmetered(plan.max_usd)  # until the provider reports usage
                started = time.monotonic()
                try:
                    await ledger.start(key, entry)
                    try:
                        c = await asyncio.wait_for(
                            provider.complete(reviewer.system, plan.user_prompt, plan.max_output_tokens),
                            timeout=config.contract["budget"].get("seconds"))
                    except (TimeoutError, providers.ProviderError) as e:
                        if isinstance(e, providers.ProviderError):
                            entry = reviewer.entry(e.completion) if e.completion else entry if e.sent else None
                        results.append({"id": case["id"], "verdict": None, "pass": False,
                                        "error": str(e) or type(e).__name__,
                                        "usd": entry["usd"] if entry else 0,
                                        "seconds": round(time.monotonic() - started, 2)})
                        continue
                    entry = reviewer.entry(c)
                    verdict, problem = reviewer.verdict(c.text)
                    results.append({
                        "id": case["id"],
                        "verdict": verdict["verdict"] if verdict else None,
                        "reason": verdict["reason"] if verdict else None,
                        "error": problem,
                        "pass": bool(verdict) and verdict["verdict"] in case["accept"],
                        "inputTokens": c.input_tokens, "outputTokens": c.output_tokens,
                        "usd": entry["usd"],
                        "seconds": round(time.monotonic() - started, 2),
                    })
                finally:
                    await ledger.settle(plan.max_usd, entry, key=key)
        finally:
            await provider.aclose()
    return results, refused


def table(cases, columns):
    """Print each case's verdict under each column's label: {label: outcomes}."""
    labels = list(columns)
    print("| Case | Accept | " + " | ".join(labels) + " |")
    print("|---|---|" + "---|" * len(labels))
    for i, case in enumerate(cases):
        cells = []
        for label in labels:
            rs = columns[label]
            if i >= len(rs):
                cells.append("not run")
                continue
            r = rs[i]
            cells.append((r["verdict"] or f"error: {r['error']}") + ("" if r.get("pass") else " ✗"))
        mark = " (critical)" if case.get("critical") else ""
        print(f"| {case['id']}{mark} | {', '.join(case['accept'])} | " + " | ".join(cells) + " |")
    print()


def commit():
    try:
        return subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--short=12", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


async def evaluate(args):
    """The trust evaluation of one passport."""
    te = trust_eval()
    try:
        p = te.passport(args.passport)
        if len(args.config) != 1:
            raise te.EvalError("a trust evaluation takes one --config, the agent's own")
        config = load(args.config[0])
        files = []
        for f in config.prompt_files:
            try:
                files.append(str(f.resolve().relative_to(REPO_ROOT.resolve())))
            except ValueError:
                files.append(str(f))
        te.check_config(p, config.persona, config.capability, files)
    except te.EvalError as e:
        sys.exit(f"refused: {e}")
    e = te.engine.Engine(args.state_dir, queue=args.queue_dir, audit=args.audit, log=print)
    suite = te.cases(p)
    ledger = Ledger(config.ledger, config.monthly_ceiling_usd)
    runs, columns, refused = [], {}, None
    for attempt in (1, 2):
        outcomes, refused = await run_model(config, suite, args.spacing, ledger)
        columns[f"run {attempt} ({config.model.api}:{config.model.name})"] = outcomes
        runs.append(te.run_record(suite, outcomes))
        if refused or attempt == 2 or not te.drifts(p, suite, runs[-1]):
            break
        print("the first run drifted; running it once more")
    table(suite, columns)
    entry = te.result(p, suite, runs, ledger.clock(), config.model.name, commit(), refused, args.results)
    items = te.record(e, p, entry, args.results)
    print(f"{entry['id']}: {entry['outcome']}. {entry['summary']}")
    for item in items:
        print(f"queued {item['source']['finding']}: review_queue.py show {item['id']}")
    if len(runs) == 1 and set(entry["eval"]["findings"]) <= {"cost"}:
        path = Path(args.results).resolve() if args.results else te.results_file(p)
        try:
            path = path.relative_to(REPO_ROOT.resolve())
        except ValueError:
            pass
        run = runs[0]
        print("To make this run the baseline for these pins, set the passport's eval.baseline to "
              + json.dumps({"met": run["met"], "of": run["of"], "result": f"{path}#{entry['id']}"})
              + " and bump its version.")
    return 1 if entry["outcome"] == "failed" else 0


async def compare(args):
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))["cases"]
    runs = {}
    for path in args.config:
        config = load(path)
        label = f"{Path(path).stem} ({config.model.api}:{config.model.name})"
        runs[label], refused = await run_model(config, cases, args.spacing)
        if refused:
            print(f"{label}: {refused}")
    table(cases, runs)
    for label, rs in runs.items():
        passed = sum(1 for r in rs if r.get("pass"))
        usd = sum(r.get("usd", 0) for r in rs)
        secs = [r["seconds"] for r in rs if "seconds" in r]
        mean = sum(secs) / len(secs) if secs else 0
        print(f"{label}: {passed}/{len(cases)} cases, ${usd:.4f} in total, {mean:.1f}s a call on average")
    if args.out:
        Path(args.out).write_text(json.dumps(runs, indent=2) + "\n", encoding="utf-8")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Patricia's trust evaluation, or a comparison of models on her cases.")
    ap.add_argument("--config", action="append", required=True, help="a hive_a2a config, once per model")
    ap.add_argument("--passport", help="run this passport's trust evaluation, with its own config")
    ap.add_argument("--cases", default=str(HERE / "cases.json"), help="the cases to compare models on")
    ap.add_argument("--out", help="write a comparison's full results as JSON here")
    ap.add_argument("--spacing", type=float, default=0, help="seconds between the starts of one model's calls")
    ap.add_argument("--results", help="the results.jsonl to append an evaluation to (default: the passport's)")
    ap.add_argument("--state-dir", default="~/.local/state/workflows-hive/runs",
                    help="the workflows-hive state directory; the queue and audit log sit beside it")
    ap.add_argument("--queue-dir", help="the review queue (default: queue/ beside --state-dir)")
    ap.add_argument("--audit", metavar="PATH", help="the audit log (default: audit.jsonl beside --state-dir)")
    args = ap.parse_args()
    return asyncio.run(evaluate(args) if args.passport else compare(args))


if __name__ == "__main__":
    sys.exit(main())
