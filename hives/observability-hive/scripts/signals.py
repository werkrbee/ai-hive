#!/usr/bin/env python3
"""Emit signals: the seam a producer calls, off unless configured.

Standard library only. A producer asks for a Tracer once, with from_env(), and gets None
when nothing is configured, so with observability off it does nothing and imports nothing
more. Configured, a Tracer builds spans of the signal contract (DESIGN.md), sanitizes their
attributes before anything is queued, and hands them to a sink:

  - MemorySink keeps them in a list, for tests and for a reader in the same process.
  - OtlpSink sends them to an OTLP/HTTP endpoint in the OTLP JSON encoding, from a
    background thread with a bounded queue. A full queue or a failed send drops the batch
    and counts it; nothing a run decides waits on it or changes because of it.

Configuration, by environment, read once:

  OTEL_EXPORTER_OTLP_TRACES_ENDPOINT   where to send spans, as a full URL; or
  OTEL_EXPORTER_OTLP_ENDPOINT          a base URL, to which /v1/traces is added
  OTEL_EXPORTER_OTLP_HEADERS           headers to send, as key=value pairs separated by commas,
                                       for a credential kept outside the repo
  OTEL_EXPORTER_OTLP_PROTOCOL          http/json, the only one this sink speaks, when set
  OTEL_SDK_DISABLED                    true turns emission off whatever else is set
  OBSERVABILITY_TENANT                 the opaque tenant every signal belongs to (default: local)

An endpoint must be https, or http to localhost only, so spans never cross a network in
the clear. A configuration this seam can't honour (an endpoint in the clear, another
protocol such as the gRPC a platform's own agent injects) turns emission off with a
warning; it never stops the producer from starting.

IDs. A run's trace ID and its spans' IDs are derived from the tenant and the run's own
IDs, so a run resumed in another process continues the same trace, and a step's span ID is
the one its outgoing calls name as their parent in traceparent. A traceparent that comes
in is parsed strictly (check_signals.parse_traceparent) and continued only if valid.
"""
import atexit
import hashlib
import importlib.util
import json
import logging
import os
import queue
import re
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("observability_check_signals", HERE / "check_signals.py")
check_signals = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_signals)

CONTRACT = check_signals.CONVENTIONS["contract"]
PINS = dict(check_signals.PINS)
SCOPE = "io.werkrbee.observability-hive"
TENANT = re.compile(r"[A-Za-z0-9_:.-]{1,128}")
QUEUE_ITEMS = 1024
BATCH = 128
FLUSH_SECONDS = 2.0
SEND_TIMEOUT = 5.0
log = logging.getLogger("observability-hive")


class ConfigError(Exception):
    """Observability is configured in a way it can't be used safely."""


# ---- IDs ---------------------------------------------------------------------------------

def _hex(*parts, size):
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:size]


def trace_id(tenant, run_id):
    """A run's trace ID: stable for the run, different in every tenant, never all zeros."""
    return _hex("trace", tenant, run_id, size=32).replace("0" * 32, "1" * 32)


def span_id(tenant, *parts):
    """A span's ID, from the IDs of what it is a span of."""
    return _hex("span", tenant, *parts, size=16).replace("0" * 16, "1" * 16)


def traceparent(trace, parent, sampled=True):
    return f"00-{trace}-{parent}-{'01' if sampled else '00'}"


# ---- Sinks -------------------------------------------------------------------------------

class MemorySink:
    def __init__(self):
        self.signals = []

    def put(self, signal):
        self.signals.append(signal)

    def flush(self, timeout=None):
        return True


def _value(v):
    if isinstance(v, bool):
        return {"boolValue": v}
    if isinstance(v, int):
        return {"intValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    if isinstance(v, str):
        return {"stringValue": v}
    return {"stringValue": json.dumps(v, sort_keys=True)}


def _nanos(text):
    t = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return str(int(t.timestamp()) * 1_000_000_000 + t.microsecond * 1000)


STATUS = {"unset": 0, "ok": 1, "error": 2}
CLIENT = {"chat", "invoke_agent"}  # a call out to a model or another agent; the rest are internal


def to_otlp(signals):
    """Spans of the contract in the OTLP JSON encoding, grouped by tenant and producer.
    Correlation IDs travel as io.werkrbee.<field> span attributes, the tenant as a resource
    attribute; nothing else is added."""
    groups = {}
    for s in signals:
        if s.get("kind") != "span":
            continue
        groups.setdefault((s["tenant"], s["source"]["producer"], s["source"]["version"]), []).append(s)
    out = []
    for (tenant, producer, version), spans in groups.items():
        rows = []
        for s in spans:
            attrs = dict(s.get("attributes", {}))
            attrs.update({f"io.werkrbee.{k}": v for k, v in s.get("correlation", {}).items()})
            row = {"traceId": s["trace"]["traceId"], "spanId": s["trace"]["spanId"], "name": s["name"],
                   "kind": 3 if s["name"].split(" ")[0] in CLIENT else 1,
                   "startTimeUnixNano": _nanos(s["startAt"]), "endTimeUnixNano": _nanos(s["endAt"]),
                   "attributes": [{"key": k, "value": _value(v)} for k, v in sorted(attrs.items())],
                   "status": {"code": STATUS[s["status"]]}}
            if s["trace"].get("parentSpanId"):
                row["parentSpanId"] = s["trace"]["parentSpanId"]
            rows.append(row)
        out.append({"resource": {"attributes": [
                        {"key": "service.name", "value": {"stringValue": producer}},
                        {"key": "service.version", "value": {"stringValue": version}},
                        {"key": "io.werkrbee.tenant", "value": {"stringValue": tenant}}]},
                    "scopeSpans": [{"scope": {"name": SCOPE, "version": CONTRACT}, "spans": rows}],
                    "schemaUrl": f"https://opentelemetry.io/schemas/{PINS['core'].lstrip('v')}"})
    return {"resourceSpans": out}


class OtlpSink:
    """Spans to an OTLP/HTTP endpoint, best effort. put() never blocks and never raises: a
    full queue drops the span, a failed send drops its batch, and both are counted."""

    def __init__(self, endpoint, headers=None):
        self.endpoint, self.headers = endpoint, dict(headers or {})
        self.queue = queue.Queue(maxsize=QUEUE_ITEMS)
        self.counts = {"sent": 0, "dropped": 0, "failed": 0}
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._run, name="observability-otlp", daemon=True)
        self.thread.start()
        atexit.register(self.flush, FLUSH_SECONDS)

    def put(self, signal):
        try:
            self.queue.put_nowait(signal)
        except queue.Full:
            self._count("dropped")

    def _count(self, what, n=1):
        with self.lock:
            self.counts[what] += n

    def _run(self):
        while True:
            batch = [self.queue.get()]
            while len(batch) < BATCH:
                try:
                    batch.append(self.queue.get(timeout=0.05))
                except queue.Empty:
                    break
            self._send(batch)
            for _ in batch:
                self.queue.task_done()

    def _send(self, batch):
        body = json.dumps(to_otlp(batch)).encode("utf-8")
        request = urllib.request.Request(self.endpoint, data=body, method="POST",
                                         headers={"content-type": "application/json", **self.headers})
        try:
            with urllib.request.urlopen(request, timeout=SEND_TIMEOUT) as r:
                ok = 200 <= r.status < 300
        except (urllib.error.URLError, OSError, ValueError):
            ok = False
        self._count("sent" if ok else "failed", len(batch))

    def flush(self, timeout=FLUSH_SECONDS):
        """Wait up to timeout seconds for what is queued to be sent; True if it was."""
        done = threading.Event()

        def wait():
            self.queue.join()
            done.set()
        threading.Thread(target=wait, daemon=True).start()
        return done.wait(timeout)


def _endpoint(env):
    url = env.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    if not url and env.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        url = env["OTEL_EXPORTER_OTLP_ENDPOINT"].rstrip("/") + "/v1/traces"
    if not url:
        return None
    parts = urlsplit(url)
    local = parts.hostname in ("localhost", "127.0.0.1", "::1")
    if parts.scheme != "https" and not (parts.scheme == "http" and local):
        raise ConfigError("the OTLP endpoint must be https, or http to localhost")
    if parts.username or parts.password or parts.query:
        raise ConfigError("the OTLP endpoint can't carry credentials or a query; use OTEL_EXPORTER_OTLP_HEADERS")
    return url


def _headers(text):
    headers = {}
    for pair in (text or "").split(","):
        key, sep, value = pair.partition("=")
        if sep and key.strip():
            headers[key.strip()] = unquote(value.strip())
    return headers


# ---- The tracer --------------------------------------------------------------------------

def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class Tracer:
    """Builds spans of the contract and hands them to its sink. emit() never raises: a span
    that can't be built is counted and dropped, so telemetry can't change what a run does."""

    def __init__(self, producer, version, sink, tenant="local"):
        if not TENANT.fullmatch(tenant or ""):
            raise ConfigError("OBSERVABILITY_TENANT must be an opaque ID: letters, digits, _ : . -")
        self.producer, self.version, self.sink, self.tenant = producer, version, sink, tenant
        self.dropped = 0

    def trace_id(self, run_id):
        return trace_id(self.tenant, run_id)

    def span_id(self, *parts):
        return span_id(self.tenant, *parts)

    def traceparent(self, run_id, *parts):
        """The traceparent for a call made from the span named by parts, in run_id's trace."""
        return traceparent(self.trace_id(run_id), self.span_id(*parts))

    def emit(self, name, *, trace, span, start, end, parent=None, status="ok", correlation=None,
             attributes=None, error=None, basis="measured"):
        try:
            attrs, _ = check_signals.sanitize(attributes or {}, "span")
            if error is not None:
                attrs["error.type"] = error if isinstance(error, str) else check_signals.error_type(error)
                status = "error"
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,63}", attrs["error.type"]):
                    attrs["error.type"] = "_OTHER"
            signal = {"contract": CONTRACT, "kind": "span", "name": name, "tenant": self.tenant,
                      "source": {"producer": self.producer, "version": self.version},
                      "conventions": dict(PINS), "observedAt": start, "basis": basis,
                      "correlation": {k: v for k, v in (correlation or {}).items() if v is not None},
                      "trace": {"traceId": trace, "spanId": span, "sampled": True},
                      "startAt": start, "endAt": end if int(_nanos(end)) >= int(_nanos(start)) else start,
                      "status": status, "attributes": attrs}
            if parent:
                signal["trace"]["parentSpanId"] = parent
            if not signal["correlation"]:
                del signal["correlation"]
            errors, _ = check_signals.check(signal)
            if errors:
                self.dropped += 1
                return None
            self.sink.put(signal)
            return signal
        except Exception:  # best effort: nothing about telemetry may stop the work it observes
            self.dropped += 1
            return None


def from_env(producer, version, env=None):
    """The producer's Tracer, or None: when nothing is configured, when OTEL_SDK_DISABLED is
    set, or, with a warning, when the configuration can't be honoured safely."""
    env = os.environ if env is None else env
    if env.get("OTEL_SDK_DISABLED", "").strip().lower() == "true":
        return None
    try:
        endpoint = _endpoint(env)
        if endpoint is None:
            return None
        protocol = env.get("OTEL_EXPORTER_OTLP_TRACES_PROTOCOL") or env.get("OTEL_EXPORTER_OTLP_PROTOCOL")
        if protocol and protocol != "http/json":
            raise ConfigError(f"this sink speaks OTLP over http/json, not {protocol}")
        tenant = env.get("OBSERVABILITY_TENANT", "local")
        if not TENANT.fullmatch(tenant):
            raise ConfigError("OBSERVABILITY_TENANT must be an opaque ID: letters, digits, _ : . -")
    except ConfigError as e:
        log.warning("observability is off: %s", e)
        return None
    return Tracer(producer, version, OtlpSink(endpoint, _headers(env.get("OTEL_EXPORTER_OTLP_HEADERS"))), tenant)
