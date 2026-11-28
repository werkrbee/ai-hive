"""observability-hive's emit seam (scripts/signals.py): off unless configured, safe
endpoints only, spans of the contract, and an OTLP sink that never blocks or raises.
A collector on localhost stands in for a backend; nothing leaves the machine."""
import http.server
import importlib.util
import json
import threading
import unittest
from pathlib import Path

HIVE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("signals", HIVE / "scripts" / "signals.py")
signals = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signals)
check = signals.check_signals.check


def emit(tracer, name="io.werkrbee.step", **kw):
    args = dict(trace=tracer.trace_id("run_1"), span=tracer.span_id("run_1:s1"), parent=tracer.span_id("run_1"),
                start="2026-11-28T10:00:00Z", end="2026-11-28T10:00:02.500000Z", correlation={"runId": "run_1", "step": "s1"})
    args.update(kw)
    return tracer.emit(name, **args)


class Collector:
    """An OTLP/HTTP endpoint on localhost that keeps what it's sent."""

    def __init__(self, status=200):
        received = self.received = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                received.append(({k.lower(): v for k, v in self.headers.items()}, json.loads(self.rfile.read(int(self.headers["content-length"])))))
                self.send_response(status)
                self.end_headers()

            def log_message(self, *a):
                pass
        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1/traces"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class Configuration(unittest.TestCase):
    def test_off_unless_an_endpoint_is_set(self):
        self.assertIsNone(signals.from_env("p/q", "1", {}))
        self.assertIsNone(signals.from_env("p/q", "1", {"OBSERVABILITY_TENANT": "t"}))
        self.assertIsNone(signals.from_env("p/q", "1", {"OTEL_EXPORTER_OTLP_ENDPOINT": "https://otel.example.test",
                                                        "OTEL_SDK_DISABLED": "true"}))

    def test_endpoints_are_encrypted_or_local_and_carry_no_credentials(self):
        for url in ("http://otel.example.test", "ftp://localhost/x", "https://user:pw@otel.example.test",
                    "https://otel.example.test/v1/traces?key=abc"):
            with self.assertRaises(signals.ConfigError, msg=url):
                signals._endpoint({"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": url})
            with self.assertLogs("observability-hive", "WARNING"):
                self.assertIsNone(signals.from_env("p/q", "1", {"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": url}), url)
        self.assertEqual(signals._endpoint({"OTEL_EXPORTER_OTLP_ENDPOINT": "https://otel.example.test/"}),
                         "https://otel.example.test/v1/traces")
        self.assertEqual(signals._endpoint({"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://localhost:4318/v1/traces"}),
                         "http://localhost:4318/v1/traces")

    def test_a_platform_agents_injected_grpc_endpoint_turns_it_off_never_crashes(self):
        injected = {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://otel.service.k8se-apps:4317/",
                    "OTEL_EXPORTER_OTLP_PROTOCOL": "grpc"}
        with self.assertLogs("observability-hive", "WARNING"):
            self.assertIsNone(signals.from_env("p/q", "1", injected))
        with self.assertLogs("observability-hive", "WARNING"):
            self.assertIsNone(signals.from_env("p/q", "1", {"OTEL_EXPORTER_OTLP_ENDPOINT": "https://otel.example.test",
                                                            "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf"}))
        with self.assertLogs("observability-hive", "WARNING"):
            self.assertIsNone(signals.from_env("p/q", "1", {"OTEL_EXPORTER_OTLP_ENDPOINT": "https://otel.example.test",
                                                            "OBSERVABILITY_TENANT": "a@b.example"}))

    def test_a_tenant_must_be_opaque(self):
        with self.assertRaises(signals.ConfigError):
            signals.Tracer("p/q", "1", signals.MemorySink(), "someone@example.com")

    def test_headers_come_from_the_environment(self):
        self.assertEqual(signals._headers("authorization=Bearer%20abc, x-team = ops"),
                         {"authorization": "Bearer abc", "x-team": "ops"})


class Spans(unittest.TestCase):
    def setUp(self):
        self.sink = signals.MemorySink()
        self.tracer = signals.Tracer("workflows-hive/engine", "abc1234", self.sink, "tenant-a")

    def test_a_span_is_a_valid_signal_of_the_contract(self):
        s = emit(self.tracer, attributes={"io.werkrbee.step.status": "completed"})
        self.assertEqual(check(s), ([], []))
        self.assertEqual(self.sink.signals, [s])
        self.assertEqual(s["conventions"], signals.PINS)

    def test_attributes_are_sanitized_before_anything_is_queued(self):
        s = emit(self.tracer, attributes={"gen_ai.input.messages": "my password is hunter2",
                                          "gen_ai.tool.name": "Bearer abc.def", "user.email": "a@b.example"})
        self.assertEqual(s["attributes"], {})
        self.assertNotIn("hunter2", json.dumps(self.sink.signals))

    def test_an_error_keeps_its_class_and_marks_the_span(self):
        s = emit(self.tracer, error=PermissionError("/Users/someone/.ssh/id_ed25519"))
        self.assertEqual((s["status"], s["attributes"]["error.type"]), ("error", "PermissionError"))
        s = emit(self.tracer, error="step failed: /etc/passwd")
        self.assertEqual(s["attributes"]["error.type"], "_OTHER")

    def test_a_span_that_breaks_the_contract_is_dropped_not_raised(self):
        self.assertIsNone(emit(self.tracer, name="send_email"))
        self.assertIsNone(emit(self.tracer, correlation={"runId": "run 1; drop"}))
        self.assertEqual((self.tracer.dropped, self.sink.signals), (2, []))

    def test_ids_are_stable_per_run_and_differ_by_tenant(self):
        other = signals.Tracer("workflows-hive/engine", "abc1234", self.sink, "tenant-b")
        self.assertEqual(self.tracer.trace_id("run_1"), self.tracer.trace_id("run_1"))
        self.assertNotEqual(self.tracer.trace_id("run_1"), other.trace_id("run_1"))
        self.assertRegex(self.tracer.traceparent("run_1", "run_1:s1"), r"^00-[0-9a-f]{32}-[0-9a-f]{16}-01$")

    def test_the_otlp_encoding(self):
        s = emit(self.tracer, attributes={"io.werkrbee.usage.tokens": 12, "io.werkrbee.cost.usd": 0.5})
        body = signals.to_otlp([s, {"kind": "metric"}])
        rs, = body["resourceSpans"]
        resource = {a["key"]: a["value"]["stringValue"] for a in rs["resource"]["attributes"]}
        self.assertEqual(resource, {"service.name": "workflows-hive/engine", "service.version": "abc1234",
                                    "io.werkrbee.tenant": "tenant-a"})
        span, = rs["scopeSpans"][0]["spans"]
        self.assertEqual((span["traceId"], span["parentSpanId"], span["status"]), (s["trace"]["traceId"],
                         s["trace"]["parentSpanId"], {"code": 1}))
        self.assertEqual(int(span["endTimeUnixNano"]) - int(span["startTimeUnixNano"]), 2_500_000_000)
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        self.assertEqual(attrs["io.werkrbee.usage.tokens"], {"intValue": "12"})
        self.assertEqual(attrs["io.werkrbee.runId"], {"stringValue": "run_1"})


class Export(unittest.TestCase):
    def test_spans_reach_a_collector_with_its_headers(self):
        c = Collector()
        self.addCleanup(c.close)
        tracer = signals.from_env("agents-hive/a2a", "1", {"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": c.url,
                                                           "OTEL_EXPORTER_OTLP_HEADERS": "authorization=Bearer t",
                                                           "OBSERVABILITY_TENANT": "tenant-a"})
        emit(tracer)
        emit(tracer, span=tracer.span_id("run_1:s2"))
        self.assertTrue(tracer.sink.flush(5))
        spans = [s for _, body in c.received for r in body["resourceSpans"] for s in r["scopeSpans"][0]["spans"]]
        self.assertEqual(len(spans), 2)
        self.assertEqual(c.received[0][0]["authorization"], "Bearer t")
        self.assertEqual(tracer.sink.counts, {"sent": 2, "dropped": 0, "failed": 0})

    def test_an_outage_is_counted_and_never_raised(self):
        dead = Collector(status=503)
        self.addCleanup(dead.close)
        sink = signals.OtlpSink(dead.url)
        tracer = signals.Tracer("p/q", "1", sink, "tenant-a")
        emit(tracer)
        self.assertTrue(sink.flush(5))
        self.assertEqual(sink.counts["failed"], 1)
        refused = signals.OtlpSink("http://127.0.0.1:9/v1/traces")  # nothing listens on the discard port
        emit(signals.Tracer("p/q", "1", refused, "tenant-a"))
        self.assertTrue(refused.flush(10))
        self.assertEqual(refused.counts["failed"], 1)

    def test_a_full_queue_drops_instead_of_blocking(self):
        sink = signals.OtlpSink.__new__(signals.OtlpSink)  # no sender thread: the queue only fills
        sink.queue = signals.queue.Queue(maxsize=2)
        sink.counts = {"sent": 0, "dropped": 0, "failed": 0}
        sink.lock = threading.Lock()
        for _ in range(5):
            sink.put({"kind": "span"})
        self.assertEqual(sink.counts["dropped"], 3)


if __name__ == "__main__":
    unittest.main()
