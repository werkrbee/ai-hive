"""Tests for the server's spans (hive_a2a/telemetry.py): an in-memory sink, the stub or a
fixed model, no network. Spans are spans of observability-hive's signal contract, and they
carry no proposal, context, prompt or verdict.

Run from servers/a2a with the requirements installed:
  python -m unittest discover -s tests -v
"""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path

import httpx

import test_server
import test_mcp
from test_mcp import ARGS, VERDICT
from test_server import PROPOSAL, Fixed, message, write_config

from hive_a2a import orchestrate, telemetry

signals = telemetry.signals
check = signals.check_signals.check
INCOMING = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


def tracer():
    sink = signals.MemorySink()
    return signals.Tracer(telemetry.PRODUCER, "test", sink, "tenant-a"), sink


class Traces(unittest.TestCase):
    client, rpc, ledger = test_server.ServerTest.client, test_server.ServerTest.rpc, test_server.ServerTest.ledger
    post, call = test_mcp.McpTest.post, test_mcp.McpTest.call  # helpers only, so its tests don't run twice

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def review_over_a2a(self, headers=None, provider=None):
        t, sink = tracer()
        with self.client(write_config(self.root), tracer=t,
                         provider=provider or Fixed(json.dumps({"verdict": "block", "reason": "r"}))) as c:
            body = {"jsonrpc": "2.0", "id": 1, "method": "SendMessage", "params": message(PROPOSAL)}
            r = c.post("/", json=body, headers={"A2A-Version": "1.0",
                                                "Authorization": f"Bearer {test_server.token()}", **(headers or {})})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["result"]["task"], sink.signals

    def assert_content_free(self, spans):
        text = json.dumps(spans)
        for said in ("Force-push", "teammate", "verdict", "block", "Queen Bee"):
            self.assertNotIn(said, text)

    def test_a_task_continues_the_callers_trace_with_its_model_call_beneath(self):
        task, spans = self.review_over_a2a({"traceparent": INCOMING})
        self.assertEqual([s["name"] for s in spans], ["chat fixed-model", "io.werkrbee.task"])
        model, span = spans
        for s in spans:
            self.assertEqual(check(s), ([], []))
            self.assertEqual(s["trace"]["traceId"], "4bf92f3577b34da6a3ce929d0e0e4736")
        self.assertEqual(span["trace"]["parentSpanId"], "00f067aa0ba902b7")
        self.assertEqual(model["trace"]["parentSpanId"], span["trace"]["spanId"])
        self.assertEqual(span["correlation"], {"agent": "patricia", "taskId": task["id"], "client": test_server.CALLER})
        self.assertEqual(span["attributes"]["a2a.task.state"], "completed")
        self.assertEqual(model["attributes"]["gen_ai.usage.input_tokens"], 100)
        self.assertEqual(model["attributes"]["gen_ai.usage.output_tokens"], 20)
        self.assertAlmostEqual(model["attributes"]["io.werkrbee.cost.usd"], self.ledger()[0]["usd"])
        self.assert_content_free(spans)

    def test_a_task_with_no_or_a_bad_traceparent_starts_its_own_trace(self):
        for headers in ({}, {"traceparent": "00-" + "0" * 32 + "-00f067aa0ba902b7-01"},
                        {"traceparent": INCOMING.upper()}):
            _, spans = self.review_over_a2a(headers)
            task = spans[-1]
            self.assertNotIn("parentSpanId", task["trace"], headers)
            self.assertNotEqual(task["trace"]["traceId"], "4bf92f3577b34da6a3ce929d0e0e4736")

    def test_a_failed_model_call_records_its_class_never_its_message(self):
        _, spans = self.review_over_a2a(provider=Fixed("not json, and it names /Users/someone/secret"))
        model, task = spans
        self.assertEqual(model["status"], "ok")  # the call itself returned
        self.assertEqual(task["status"], "error")
        self.assertEqual(task["attributes"]["error.type"], "task.failed")
        self.assertNotIn("/Users/", json.dumps(spans))

    def test_a_review_over_mcp_is_a_tool_span_with_its_model_call_beneath(self):
        t, sink = tracer()
        with self.client(write_config(self.root), tracer=t, provider=Fixed(json.dumps(VERDICT))) as c:
            self.call(c, ARGS, headers={"traceparent": INCOMING})
        model, tool = sink.signals
        self.assertEqual(tool["name"], "execute_tool review")
        self.assertEqual(tool["trace"]["parentSpanId"], "00f067aa0ba902b7")
        self.assertEqual(model["trace"]["parentSpanId"], tool["trace"]["spanId"])
        for s in sink.signals:
            self.assertEqual(check(s), ([], []))
        self.assert_content_free(sink.signals)

    def test_with_nothing_configured_nothing_is_emitted(self):
        self.assertIsNone(telemetry.from_env())
        with self.client(write_config(self.root), provider=Fixed(json.dumps({"verdict": "allow", "reason": "r"}))) as c:
            r = self.rpc(c, "SendMessage", message(PROPOSAL))
        self.assertEqual(r.status_code, 200)


class BarrysCalls(unittest.TestCase):
    """Barry's delegation carries traceparent naming his step's span, only when traced."""

    def delegate(self, tracer, message_id):
        seen = {}

        def handler(request):
            seen.update(request.headers)
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": message_id, "result": {"task": {
                "status": {"state": "TASK_STATE_COMPLETED"}, "artifacts": [{"parts": [{"data": {"verdict": "allow"}}]}]}}})

        async def token(scope):
            return "t"

        network = orchestrate.Network(transport=httpx.MockTransport(handler), token=token)
        network.tracer = tracer
        d = type("D", (), {"name": "patricia", "url": "https://patricia.example.test/", "token_scope": "s"})()

        async def go():
            try:
                return await network.delegate(d, {"proposal": "p"}, message_id)
            finally:
                await network.aclose()
        asyncio.run(go())
        return seen

    def test_a_step_names_its_own_span_and_a_review_names_the_runs(self):
        t, _ = tracer()
        step = self.delegate(t, "run_abc:s2")["traceparent"]
        self.assertEqual(step, signals.traceparent(t.trace_id("run_abc"), t.span_id("run_abc:s2")))
        review = self.delegate(t, "run_abc:review:0123456789abcdef")["traceparent"]
        self.assertEqual(review, signals.traceparent(t.trace_id("run_abc"), t.span_id("run_abc")))
        self.assertIsNotNone(signals.check_signals.parse_traceparent(step))

    def test_untraced_calls_carry_no_traceparent(self):
        self.assertNotIn("traceparent", self.delegate(None, "run_abc:s2"))


if __name__ == "__main__":
    unittest.main()
