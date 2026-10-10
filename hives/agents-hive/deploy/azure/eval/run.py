"""Run the governance-review cases against two or more models and compare.

Each --config is a hive_a2a config (config.example.toml) naming one model. The cases go
through the server's own reviewer: the same system prompt, contract input and output
checks, and per-call budget, with no server, auth or ceiling in between.

Run from hives/agents-hive/servers/a2a with its requirements installed, signed in with
`az login` when a config uses auth = "entra":

  python ../../deploy/azure/eval/run.py --config a.toml --config b.toml --out results.json

Prints a table of verdicts per case, how many each model got right, and what it cost.
"""
import argparse
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "servers/a2a"))

from hive_a2a import providers  # noqa: E402
from hive_a2a.config import load  # noqa: E402
from hive_a2a.ledger import Ledger  # noqa: E402
from hive_a2a.review import Reviewer  # noqa: E402


async def run_model(config, cases):
    provider = providers.create(config.model)
    with tempfile.TemporaryDirectory() as tmp:  # the eval doesn't touch the server's ledger
        reviewer = Reviewer(config, Ledger(Path(tmp) / "ledger.jsonl", config.monthly_ceiling_usd), provider)
        results = []
        try:
            for case in cases:
                value = {"proposal": case["proposal"], "context": case["context"]}
                plan = reviewer.plan(value)
                started = time.monotonic()
                try:
                    c = await asyncio.wait_for(
                        provider.complete(reviewer.system, plan.user_prompt, plan.max_output_tokens),
                        timeout=config.contract["budget"].get("seconds"))
                except (TimeoutError, providers.ProviderError) as e:
                    results.append({"id": case["id"], "verdict": None, "error": str(e) or type(e).__name__})
                    continue
                verdict, problem = reviewer.verdict(c.text)
                results.append({
                    "id": case["id"],
                    "verdict": verdict["verdict"] if verdict else None,
                    "reason": verdict["reason"] if verdict else None,
                    "error": problem,
                    "pass": bool(verdict) and verdict["verdict"] in case["accept"],
                    "inputTokens": c.input_tokens, "outputTokens": c.output_tokens,
                    "usd": round(config.price(c.input_tokens, c.output_tokens), 6),
                    "seconds": round(time.monotonic() - started, 2),
                })
        finally:
            await provider.aclose()
    return results


async def main():
    ap = argparse.ArgumentParser(description="Compare models on Patricia's governance-review cases.")
    ap.add_argument("--config", action="append", required=True, help="a hive_a2a config, once per model")
    ap.add_argument("--cases", default=str(HERE / "cases.json"))
    ap.add_argument("--out", help="write the full results as JSON here")
    args = ap.parse_args()
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))["cases"]
    runs = {}
    for path in args.config:
        config = load(path)
        label = f"{Path(path).stem} ({config.model.provider}:{config.model.name})"
        runs[label] = await run_model(config, cases)

    labels = list(runs)
    print("| Case | Accept | " + " | ".join(labels) + " |")
    print("|---|---|" + "---|" * len(labels))
    for i, case in enumerate(cases):
        cells = []
        for label in labels:
            r = runs[label][i]
            cells.append((r["verdict"] or f"error: {r['error']}") + ("" if r.get("pass") else " ✗"))
        print(f"| {case['id']} | {', '.join(case['accept'])} | " + " | ".join(cells) + " |")
    print()
    for label in labels:
        rs = runs[label]
        passed = sum(1 for r in rs if r.get("pass"))
        usd = sum(r.get("usd", 0) for r in rs)
        secs = [r["seconds"] for r in rs if "seconds" in r]
        mean = sum(secs) / len(secs) if secs else 0
        print(f"{label}: {passed}/{len(rs)} cases, ${usd:.4f} in total, {mean:.1f}s a call on average")
    if args.out:
        Path(args.out).write_text(json.dumps(runs, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
