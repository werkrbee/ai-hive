"""The engine's spans: one per run, step and turn as it ends, spans of observability-hive's
signal contract, in an in-memory sink. Off unless configured, and content-free."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import run as engine  # noqa: E402

signals = engine.signals
check = signals.check_signals.check


def echo(inp, key, _cap):
    return inp, {"usd": 0.001, "tokens": 10}


def boom(inp, key, _cap):
    raise RuntimeError("failed reading /Users/someone/notes.txt with token sk-live-0123456789abcdef")


class Traces(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.sink = signals.MemorySink()

    def make(self, traced=True):
        tracer = signals.Tracer("workflows-hive/engine", "test", self.sink, "tenant-a") if traced else None
        return engine.Engine(self.tmp / "runs", workers=dict(engine.WORKERS, echo=echo, boom=boom),
                             log=lambda *a: None, tracer=tracer)

    def spans(self):
        for s in self.sink.signals:
            self.assertEqual(check(s), ([], []), s["name"])
        return self.sink.signals

    def test_a_planned_run_is_a_run_span_with_a_span_per_step(self):
        words = self.tmp / "words.txt"
        words.write_text("one two three")
        run = self.make().start("word-count", {"path": str(words)})
        spans = self.spans()
        self.assertEqual([s["name"] for s in spans], ["io.werkrbee.step", "io.werkrbee.step", "io.werkrbee.run"])
        *steps, root = spans
        t = signals.Tracer("x/y", "1", None, "tenant-a")
        self.assertEqual(root["trace"]["traceId"], t.trace_id(run["runId"]))
        self.assertEqual(root["trace"]["spanId"], t.span_id(run["runId"]))
        for s, sid in zip(steps, ("read", "count")):
            self.assertEqual(s["trace"]["parentSpanId"], root["trace"]["spanId"])
            self.assertEqual(s["trace"]["spanId"], t.span_id(run["steps"][sid]["idempotencyKey"]))
            self.assertEqual(s["correlation"], {"runId": run["runId"], "step": sid})
            self.assertEqual(s["attributes"]["io.werkrbee.step.status"], "completed")
        self.assertEqual(root["attributes"]["io.werkrbee.usage.tokens"], run["cost"]["tokens"])
        self.assertEqual(root["status"], "ok")
        self.assertNotIn("one two three", json.dumps(spans))

    def test_a_resumed_run_continues_its_trace_in_another_engine(self):
        first = self.make()
        run = first.open("loop")
        first.append(run, {"id": "a", "worker": "echo", "input": {"note": "private words"}})
        first.execute(run)
        second = self.make()  # another process
        run = second.load(run["runId"])
        second.append(run, {"id": "b", "worker": "echo", "input": {}})
        run = second.execute(run)
        second.finish(run, {"done": True})
        a, b, root = self.spans()
        self.assertEqual({a["trace"]["traceId"], b["trace"]["traceId"], root["trace"]["traceId"]},
                         {root["trace"]["traceId"]})
        self.assertEqual(a["trace"]["parentSpanId"], root["trace"]["spanId"])
        self.assertNotIn("private words", json.dumps(self.sink.signals))

    def test_turns_are_spans_numbered_from_their_ids(self):
        e = self.make()
        run = e.open("loop")
        e.turn(run, "t1", lambda key: ("thinking", {"usd": 0.02, "tokens": 300}))
        e.turn(run, "t2", lambda key: ("done", {"usd": 0.01, "tokens": 120}))
        e.finish(run, {"ok": True})
        t1, t2, root = self.spans()
        self.assertEqual((t1["name"], t1["correlation"]["turn"], t2["correlation"]["turn"]), ("io.werkrbee.turn", 1, 2))
        self.assertEqual(t1["attributes"]["io.werkrbee.usage.tokens"], 300)
        self.assertNotIn("thinking", json.dumps(self.sink.signals))

    def test_a_failure_records_where_never_the_message(self):
        e = self.make()
        run = e.open("loop")
        e.append(run, {"id": "x", "worker": "boom", "input": {}})
        e.execute(run)
        step, root = self.spans()
        self.assertEqual((step["status"], step["attributes"]["error.type"]), ("error", "step.failed"))
        self.assertEqual((root["status"], root["attributes"]["error.type"]), ("error", "run.failed"))
        self.assertNotIn("/Users/", json.dumps(self.sink.signals))
        self.assertNotIn("sk-live", json.dumps(self.sink.signals))

    def test_a_run_under_a_passport_names_its_agent(self):
        e = self.make()
        run = e.open("loop", passport="barry")
        e.finish(run, {})
        root, = self.spans()
        self.assertEqual(root["correlation"]["agent"], "barry")
        self.assertEqual(root["correlation"]["passportSha256"], run["agent"]["sha256"])
        self.assertEqual(root["attributes"]["gen_ai.agent.version"], str(run["agent"]["version"]))

    def test_untraced_by_default_and_unchanged(self):
        e = engine.Engine(self.tmp / "plain", workers=dict(engine.WORKERS, echo=echo), log=lambda *a: None)
        self.assertIsNone(e.tracer)
        run = e.open("loop")
        e.append(run, {"id": "a", "worker": "echo", "input": {}})
        run = e.execute(run)
        self.assertEqual(e.finish(run, {"ok": True})["status"], "completed")

    def test_a_broken_sink_never_stops_a_run(self):
        class Broken:
            def put(self, signal):
                raise OSError("disk full")
        e = engine.Engine(self.tmp / "runs", workers=dict(engine.WORKERS, echo=echo), log=lambda *a: None,
                          tracer=signals.Tracer("workflows-hive/engine", "test", Broken(), "tenant-a"))
        run = e.open("loop")
        e.append(run, {"id": "a", "worker": "echo", "input": {}})
        run = e.execute(run)
        self.assertEqual(e.finish(run, {})["status"], "completed")
        self.assertEqual(e.tracer.dropped, 2)


if __name__ == "__main__":
    unittest.main()
