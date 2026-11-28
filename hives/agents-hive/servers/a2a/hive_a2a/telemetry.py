"""Spans for the server's tasks and model calls, through observability-hive's signal seam.

Off unless configured (observability-hive's scripts/signals.py reads the environment): with
no OTLP endpoint there is no tracer and nothing here runs. A task continues the trace a
caller's valid traceparent names, and otherwise starts its own. Spans are content-free:
the proposal, the context, the prompt and the verdict never go in, and an error keeps its
class, never its message.
"""
import importlib.util
import os
import re

from .config import REPO_ROOT

PRODUCER = "agents-hive/a2a"
SOURCE_VERSION = os.environ.get("HIVE_SOURCE_VERSION", "local")
MODEL_NAME = re.compile(r"[A-Za-z0-9_.:/@-]{1,64}")


def _signals():
    path = REPO_ROOT / "hives/observability-hive/scripts/signals.py"
    spec = importlib.util.spec_from_file_location("observability_signals", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


signals = _signals()


def from_env():
    return signals.from_env(PRODUCER, SOURCE_VERSION)


def incoming(tracer, headers, task_id):
    """(trace ID, parent span ID or None) for a task: the caller's, from a valid traceparent,
    or a new trace of the task's own."""
    parsed = signals.check_signals.parse_traceparent((headers or {}).get("traceparent"))
    if parsed:
        return parsed["traceId"], parsed["parentSpanId"]
    return tracer.trace_id(f"task:{task_id}"), None


def model_span(tracer, config, provider, trace, parent, key, start, end, completion=None, usd=None, error=None):
    """The span of one model call, a child of the task (or MCP call) that made it."""
    model = provider.model if MODEL_NAME.fullmatch(provider.model or "") else None
    attrs = {"gen_ai.operation.name": "chat", "gen_ai.provider.name": config.model.publisher.lower(),
             "io.werkrbee.capability": config.capability}
    if model:
        attrs["gen_ai.request.model"] = model
    if completion is not None:
        attrs.update({"gen_ai.usage.input_tokens": completion.input_tokens,
                      "gen_ai.usage.output_tokens": completion.output_tokens})
    if usd is not None:
        attrs["io.werkrbee.cost.usd"] = float(usd)
    tracer.emit(f"chat {model}" if model else "chat", trace=trace, span=tracer.span_id("model", key), parent=parent,
                start=start, end=end, correlation={"agent": config.persona}, attributes=attrs, error=error,
                basis="estimated" if usd is not None else "measured")
