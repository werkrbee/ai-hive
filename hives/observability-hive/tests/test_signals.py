"""observability-hive's signal contract: the examples, the rules a schema can't state, and
the helpers at the trust boundary. Synthetic signals only; no network, no SDK."""
import copy
import importlib.util
import json
import re
import unittest
from datetime import datetime, timezone
from pathlib import Path

HIVE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("check_signals", HIVE / "scripts" / "check_signals.py")
cs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs)

SLICE = [json.loads(line) for line in (HIVE / "examples" / "slice.jsonl").read_text().splitlines()]
OLD = [json.loads(line) for line in (HIVE / "examples" / "old-conventions.jsonl").read_text().splitlines()]
STEP = next(s for s in SLICE if s["name"] == "io.werkrbee.step")


def signal(**changes):
    s = copy.deepcopy(STEP)
    s.update(changes)
    return s


class Examples(unittest.TestCase):
    def test_the_slice_is_valid_with_no_notes(self):
        for s in SLICE:
            self.assertEqual(cs.check(s), ([], []), s["name"])

    def test_every_invalid_case_is_refused_for_its_reason(self):
        fail, n = cs.check_examples()
        self.assertFalse(fail)
        self.assertGreaterEqual(n, 20)

    def test_the_slice_crosses_two_producers_in_one_trace(self):
        traced = [s for s in SLICE if s.get("trace", {}).get("traceId") == STEP["trace"]["traceId"]]
        self.assertEqual({s["source"]["producer"] for s in traced}, {"workflows-hive/engine", "agents-hive/a2a"})
        task = next(s for s in traced if s["name"] == "io.werkrbee.task")
        self.assertEqual(task["trace"]["parentSpanId"], STEP["trace"]["spanId"])


class Conventions(unittest.TestCase):
    def test_every_attribute_is_named_as_the_schema_allows(self):
        pattern = cs.SCHEMA["properties"]["attributes"]["propertyNames"]["pattern"]
        for key, spec in cs.ATTRIBUTES.items():
            self.assertRegex(key, pattern)
            self.assertIn(spec["class"], cs.CONVENTIONS["classes"])
            self.assertIn(spec["type"], [*cs.TYPES, "any"])
            self.assertEqual(spec["source"] == "house", key.startswith(cs.CONVENTIONS["namespace"]), key)

    def test_house_names_are_in_the_namespace(self):
        names = [*cs.NAMES["span"], *cs.NAMES["metric"], *cs.NAMES["event"], *cs.NAMES["evaluation"]]
        for name in names:
            if not name.startswith(("gen_ai.", "invoke_agent", "chat", "execute_tool")):
                self.assertTrue(name.startswith(cs.CONVENTIONS["namespace"]), name)

    def test_house_metrics_and_genai_metrics_are_sourced(self):
        for name, spec in cs.NAMES["metric"].items():
            self.assertEqual(spec["source"] == "house", name.startswith("io.werkrbee."), name)

    def test_only_development_or_stable(self):
        self.assertEqual({s["stability"] for s in cs.ATTRIBUTES.values()}, {"development", "stable"})


class Rules(unittest.TestCase):
    def test_missing_ids_are_unattributed_not_dropped(self):
        bare = copy.deepcopy(next(s for s in SLICE if s["name"] == "io.werkrbee.request.refused"))
        self.assertNotIn("correlation", bare)
        groups = cs.join([*SLICE, bare], "tenant-a")
        self.assertIn(bare, groups[None])
        self.assertEqual(len(sum(groups.values(), [])), len(SLICE) + 1)

    def test_old_records_read_through_their_migration(self):
        span, metric, duration = (cs.migrate(s) for s in OLD)
        self.assertEqual(span["attributes"], {"gen_ai.agent.name": "word-count", "gen_ai.provider.name": "mistral",
                                              "gen_ai.usage.cache_write.input_tokens": 120})
        self.assertEqual(duration["name"], "gen_ai.client.inference.duration")
        self.assertEqual(duration["attributes"], {"gen_ai.operation.name": "chat"})
        self.assertEqual(metric["name"], "gen_ai.client.inference.operation.input_tokens")
        self.assertNotIn("gen_ai.token.type", metric["attributes"])
        self.assertEqual(span["migratedFrom"], {"core": "v1.41.0"})
        self.assertEqual(span["conventions"], cs.PINS)
        self.assertIn("gen_ai.workflow.name", OLD[0]["attributes"], "migrate copies")
        for s in OLD:
            errors, warnings = cs.check(s)
            self.assertEqual(errors, [])
            self.assertTrue(any("migration" in w for w in warnings))

    def test_a_name_that_changed_meaning_is_refused_not_read(self):
        for op in ("retrieval", "embeddings", None):
            old = copy.deepcopy(OLD[2])
            old["attributes"] = {"gen_ai.operation.name": op} if op else {}
            with self.assertRaises(cs.Unreadable):
                cs.migrate(old)
            errors, _ = cs.check(old)
            self.assertTrue(any("no faithful name" in e for e in errors), op)

    def test_only_spans_are_sampled_and_numbers_are_finite(self):
        metric = copy.deepcopy(next(s for s in SLICE if s["name"] == "io.werkrbee.cost"))
        self.assertEqual(cs.check(metric), ([], []))
        self.assertTrue(cs.check({**metric, "sampling": {"rate": 0.5}})[0])
        for bad in (float("nan"), float("inf")):
            self.assertTrue(any("finite" in e for e in cs.check({**metric, "value": bad})[0]))
        self.assertEqual(cs.check(signal(sampling={"rate": 0.25})), ([], []))

    def test_a_newer_minor_adds_fields_as_warnings(self):
        errors, warnings = cs.check(signal(contract="1.1", priority="low"))
        self.assertEqual(errors, [])
        self.assertTrue(any("priority" in w for w in warnings))

    def test_clock_skew_is_a_warning(self):
        errors, warnings = cs.check(signal(ingestedAt="2026-11-27T13:50:00Z"))
        self.assertEqual(errors, [])
        self.assertTrue(any("clock is ahead" in w for w in warnings))
        self.assertEqual(cs.check(signal(ingestedAt="2026-11-27T14:02:00Z")), ([], []))

    def test_a_content_attribute_passes_only_with_its_capture_exception(self):
        captured = next(s for s in SLICE if "capture" in s)
        self.assertEqual(cs.check(captured), ([], []))
        errors, _ = cs.check({k: v for k, v in captured.items() if k != "capture"})
        self.assertTrue(any("capture exception" in e for e in errors))


class TrustBoundary(unittest.TestCase):
    def test_traceparent(self):
        good = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        self.assertEqual(cs.parse_traceparent(good),
                         {"traceId": "4bf92f3577b34da6a3ce929d0e0e4736", "parentSpanId": "00f067aa0ba902b7", "sampled": True})
        self.assertFalse(cs.parse_traceparent(good[:-1] + "0")["sampled"])
        self.assertIsNotNone(cs.parse_traceparent("01" + good[2:] + "-later-fields"), "a later version reads")
        for bad in (None, "", good.upper(), "ff" + good[2:], good + "-extra", "00-" + "0" * 32 + "-00f067aa0ba902b7-01",
                    "00-4bf92f3577b34da6a3ce929d0e0e4736-" + "0" * 16 + "-01", "00-4bf92f3577b34da6a3ce929d0e0e473-00f067aa0ba902b7-01",
                    "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01; user=admin"):
            self.assertIsNone(cs.parse_traceparent(bad), bad)

    def test_baggage_is_dropped_unless_allowed(self):
        header = "userId=alice@example.com,tenant=tenant-b,role=admin;prop=1,region=eu"
        self.assertEqual(cs.baggage(header), {})
        self.assertEqual(cs.baggage(header, allow={"region", "userId"}), {"region": "eu"}, "a kept value is still checked")
        self.assertEqual(cs.baggage("region=eu," * 2000, allow={"region"}), {}, "an oversized header is dropped")
        self.assertEqual(cs.baggage("u=a%40b.example.com,region=e%75", allow={"u", "region"}), {"region": "eu"},
                         "values are decoded before they're checked")

    def test_sanitize_drops_by_name_and_reports_names_only(self):
        kept, dropped = cs.sanitize({
            "gen_ai.request.model": "model-b",
            "gen_ai.input.messages": "my password is hunter2",
            "gen_ai.tool.name": "Bearer abc.def",
            "http.request.header.authorization": "Bearer abc",
            "a2a.task.id": "task-1",
        }, kind="metric")
        self.assertEqual(kept, {"gen_ai.request.model": "model-b"})
        self.assertEqual(dropped, ["a2a.task.id", "gen_ai.input.messages", "gen_ai.tool.name",
                                   "http.request.header.authorization"])
        self.assertNotIn("hunter2", json.dumps([kept, dropped]))
        messages = [{"role": "user", "parts": [{"type": "text", "content": "x"}]}]
        capture = {"fields": ["gen_ai.input.messages"]}
        kept, _ = cs.sanitize({"a2a.task.id": "task-1", "gen_ai.input.messages": messages}, "span", capture)
        self.assertEqual(set(kept), {"a2a.task.id", "gen_ai.input.messages"})
        kept, dropped = cs.sanitize({"gen_ai.input.messages": messages}, "metric", capture)
        self.assertEqual((kept, dropped), ({}, ["gen_ai.input.messages"]), "never content on a metric")

    def test_what_sanitize_keeps_always_passes_check(self):
        kept, dropped = cs.sanitize({"gen_ai.usage.input_tokens": "12", "gen_ai.request.model": True,
                                     "io.werkrbee.cost.usd": float("nan"), "gen_ai.tool.name": {"x": 1},
                                     "gen_ai.usage.output_tokens": 312})
        self.assertEqual(kept, {"gen_ai.usage.output_tokens": 312})
        self.assertEqual(len(dropped), 4)
        self.assertEqual(cs.check(signal(attributes=kept)), ([], []))

    def test_an_exception_keeps_its_class_never_its_message(self):
        exc = PermissionError("/Users/someone/.ssh/id_ed25519: token sk-live-0123456789abcdef")
        self.assertEqual(cs.error_type(exc), "PermissionError")
        self.assertEqual(cs.error_type("not an exception"), "_OTHER")
        s = signal(status="error", attributes={"error.type": cs.error_type(exc)})
        self.assertEqual(cs.check(s), ([], []))

    def test_no_join_crosses_tenants(self):
        theirs = copy.deepcopy(STEP)
        theirs["tenant"] = "tenant-b"  # the same run ID, the same trace, another tenant
        with self.assertRaises(cs.CrossTenant):
            cs.join([*SLICE, theirs], "tenant-a")
        with self.assertRaises(cs.CrossTenant):
            cs.freshness([STEP, theirs], "tenant-a", ["barry"], datetime.now(timezone.utc), 3600)
        self.assertEqual(cs.join([theirs], "tenant-b"), {("run", STEP["correlation"]["runId"]): [theirs]})
        self.assertEqual(cs.join(iter(SLICE), "tenant-a"), cs.join(SLICE, "tenant-a"), "an iterator reads whole")

    def test_no_evidence_is_unknown_not_healthy(self):
        now = datetime(2026, 11, 27, 15, 0, tzinfo=timezone.utc)
        self.assertEqual(cs.freshness(SLICE, "tenant-a", ["barry", "patricia", "nobody"], now, 3600),
                         {"barry": "fresh", "patricia": "fresh", "nobody": "unknown"})
        later = datetime(2026, 11, 29, tzinfo=timezone.utc)
        self.assertEqual(cs.freshness(SLICE, "tenant-a", ["barry"], later, 3600), {"barry": "stale"})


class Privacy(unittest.TestCase):
    def test_no_example_carries_what_the_contract_forbids(self):
        text = (HIVE / "examples" / "slice.jsonl").read_text()
        for what, pattern in cs.SENSITIVE:
            self.assertIsNone(pattern.search(text), what)
        self.assertIsNone(re.search(r"\b(sk|ghp)[-_]", text))


if __name__ == "__main__":
    unittest.main()
