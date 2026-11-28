#!/usr/bin/env python3
"""Check signals against observability-hive's contract, and the helpers that keep a signal
inside it at the trust boundary.

Standard library only, so it runs anywhere the hives do. A signal is one JSON object
(schema/signal.schema.json); beyond the schema's shape this checks the rules in DESIGN.md:

  - a metric's correlation names only its agent and version, since every other ID is
    unbounded and belongs on a span or an event
  - its name is one conventions.json gives for its kind, and a metric's unit is the one
    given for it
  - every attribute is in conventions.json with the right type; a metric's are only
    labels, never IDs or measures; a content attribute needs a capture exception naming
    it; and no string value reads as a secret, an address, a home path or a URL with a
    query or credentials
  - only a span carries sampling, and no number is NaN or infinite
  - a span ends no earlier than it starts and isn't its own parent, a window ends no
    earlier than it starts, and a metric's value is null exactly when its basis is unknown
  - it was written under the pinned conventions, or under ones a migration reads; a
    name an older release used that the pins gave another meaning is refused
  - a later minor of the contract may add fields, which are warnings, not errors; and a
    signal observed after it was ingested, past the skew tolerance, is a warning

The helpers: parse_traceparent and baggage validate incoming context, sanitize and
error_type make attributes safe before a signal is queued, migrate reads an older record
under the pinned conventions, and join and freshness read signals for one tenant only.

Usage:
  python3 scripts/check_signals.py                 # the examples, valid and invalid
  python3 scripts/check_signals.py signals.jsonl   # one or more files of signals
"""
import argparse
import copy
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

HIVE = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((HIVE / "schema" / "signal.schema.json").read_text())
CONVENTIONS = json.loads((HIVE / "schema" / "conventions.json").read_text())
EXAMPLES = HIVE / "examples"

MAJOR, MINOR = (int(n) for n in CONVENTIONS["contract"].split("."))
PINS = {"genai": CONVENTIONS["pins"]["genai"]["version"], "core": CONVENTIONS["pins"]["core"]["version"]}
ATTRIBUTES = CONVENTIONS["attributes"]
NAMES = CONVENTIONS["names"]
SKEW_SECONDS = 300
METRIC_CORRELATION = {"agent", "agentVersion"}  # bounded; every other ID is unbounded
MAX_STRING = 256

SENSITIVE = [
    ("an email address", re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")),
    ("a bearer token", re.compile(r"(?i)\bbearer\s+\S+")),
    ("a JSON Web Token", re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.")),
    ("an API key", re.compile(r"\b(sk|pk|rk|ghp|gho|ghs|github_pat|xox[abprs])[-_][A-Za-z0-9_-]{8,}")),
    ("a URL with credentials or a query", re.compile(r"[a-z][a-z0-9+.-]*://([^\s/@]*@|[^\s?#]*\?)", re.I)),
    ("a home path", re.compile(r"(/Users/|/home/|[A-Za-z]:\\Users\\)")),
]
TYPES = {"string": str, "int": int, "double": (int, float), "boolean": bool}


# ---- The schema ------------------------------------------------------------------------

def resolve(node):
    while "$ref" in node:
        node = SCHEMA["$defs"][node["$ref"].rsplit("/", 1)[1]]
    return node


def json_type(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    return {float: "number", str: "string", list: "array", dict: "object"}[type(value)]


def shape(value, node, where, errors):
    """The subset of JSON Schema the signal schema uses, so no package is needed."""
    node = resolve(node)
    if "const" in node and value != node["const"]:
        errors.append(f"{where}: must be {node['const']!r}")
    if "enum" in node and value not in node["enum"]:
        errors.append(f"{where}: {value!r} isn't one of {', '.join(map(str, node['enum']))}")
        return
    if "type" in node:
        allowed = node["type"] if isinstance(node["type"], list) else [node["type"]]
        t = json_type(value)
        if t not in allowed and not (t == "integer" and "number" in allowed):
            errors.append(f"{where}: must be {' or '.join(allowed)}")
            return
    if isinstance(value, str):
        if "pattern" in node and not re.search(node["pattern"], value):
            errors.append(f"{where}: {value!r} doesn't match {node['pattern']}")
        if len(value) > node.get("maxLength", len(value)) or len(value) < node.get("minLength", 0):
            errors.append(f"{where}: length out of range")
    if isinstance(value, float) and not math.isfinite(value):
        errors.append(f"{where}: must be a finite number")
        return
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in node and value < node["minimum"]:
            errors.append(f"{where}: below {node['minimum']}")
        if "maximum" in node and value > node["maximum"]:
            errors.append(f"{where}: above {node['maximum']}")
        if "exclusiveMinimum" in node and value <= node["exclusiveMinimum"]:
            errors.append(f"{where}: must be above {node['exclusiveMinimum']}")
    if isinstance(value, list):
        if len(value) < node.get("minItems", 0):
            errors.append(f"{where}: needs at least {node['minItems']} items")
        if node.get("uniqueItems") and len(set(map(json.dumps, value))) != len(value):
            errors.append(f"{where}: items repeat")
        for i, item in enumerate(value):
            shape(item, node.get("items", {}), f"{where}[{i}]", errors)
    if isinstance(value, dict):
        props = node.get("properties", {})
        for key in node.get("required", []):
            if key not in value:
                errors.append(f"{where}: missing {key}")
        for key, item in value.items():
            if "propertyNames" in node:
                shape(key, node["propertyNames"], f"{where} key", errors)
            if key in props:
                shape(item, props[key], f"{where}.{key}", errors)
            elif node.get("additionalProperties") is False:
                errors.append(f"{where}: unknown field {key}")
            elif isinstance(node.get("additionalProperties"), dict):
                shape(item, node["additionalProperties"], f"{where}.{key}", errors)
        for rule in node.get("allOf", []):
            test = rule["if"]["properties"]
            if all(value.get(k) == v.get("const") for k, v in test.items()):
                for key in rule["then"].get("required", []):
                    if key not in value:
                        errors.append(f"{where}: a {value.get('kind')} needs {key}")


# ---- The rules a schema can't state -----------------------------------------------------

def parse_time(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def sensitive(value):
    """What a string value reads as, if it reads as something no signal may carry."""
    for what, pattern in SENSITIVE:
        if pattern.search(value):
            return what
    return None


def typed(value, spec):
    """Whether a value has its attribute's type. Only content, typed any, may be structured,
    as the pinned GenAI conventions require of message attributes."""
    if spec["type"] == "any":
        return value is not None
    if isinstance(value, bool):
        return spec["type"] == "boolean"
    return isinstance(value, TYPES[spec["type"]]) and not (isinstance(value, float) and not math.isfinite(value))


def check(signal):
    """A signal's errors and warnings, as two lists of strings."""
    errors, warnings = [], []
    if not isinstance(signal, dict):
        return ["a signal must be a JSON object"], warnings
    signal = dict(signal)
    contract = signal.get("contract")
    if isinstance(contract, str) and re.fullmatch(r"\d+\.\d+", contract):
        major, minor = (int(n) for n in contract.split("."))
        if major != MAJOR:
            return [f"contract {contract}: this reader reads {MAJOR}.x only"], warnings
        if minor > MINOR:
            for key in sorted(set(signal) - set(SCHEMA["properties"])):
                warnings.append(f"{key}: a field of contract {contract}, newer than {CONVENTIONS['contract']}; kept, not read")
                del signal[key]
    shape(signal, SCHEMA, "signal", errors)
    if errors:
        return errors, warnings

    conv = signal["conventions"]
    if conv.get("genai") != PINS["genai"] or conv["core"] != PINS["core"]:
        if migration(conv) is None:
            return errors + [f"conventions: {json.dumps(conv, sort_keys=True)} isn't pinned and no migration "
                             f"reads it"], warnings
        try:
            signal = migrate(signal)
        except Unreadable as e:
            return errors + [f"conventions: {e}"], warnings
        warnings.append(f"conventions: written under core {conv['core']}; read through its migration")

    kind, name = signal["kind"], signal["name"]
    operation = name.split(" ", 1)[0]
    if kind == "metric":
        spec = NAMES["metric"].get(name)
        if spec is None:
            errors.append(f"name: {name} isn't a metric in conventions.json")
        elif signal["unit"] != spec["unit"]:
            errors.append(f"unit: {name} is in {spec['unit']}, not {signal['unit']}")
        if " " in name:
            errors.append("name: a metric's name has no target")
    elif operation not in NAMES[kind] or (" " in name and kind != "span"):
        errors.append(f"name: {name} isn't a {kind} name in conventions.json")

    if "sampling" in signal and kind != "span":
        errors.append(f"sampling: only spans are sampled; a {kind} is kept whole")
    if kind == "span":
        if parse_time(signal["endAt"]) < parse_time(signal["startAt"]):
            errors.append("endAt: before startAt")
        if signal["trace"].get("parentSpanId") == signal["trace"]["spanId"]:
            errors.append("trace: a span can't be its own parent")
    if kind == "metric":
        w = signal["window"]
        if parse_time(w["end"]) < parse_time(w["start"]):
            errors.append("window: ends before it starts")
        if (signal["value"] is None) != (signal["basis"] == "unknown"):
            errors.append("value: null exactly when basis is unknown; an unknown is never 0")
        for key in sorted(set(signal.get("correlation", {})) - METRIC_CORRELATION):
            errors.append(f"correlation: a metric can't carry {key}; IDs go on spans and events, not metrics")

    capture = signal.get("capture")
    for field in (capture or {}).get("fields", []):
        if ATTRIBUTES.get(field, {}).get("class") != "content":
            errors.append(f"capture: {field} isn't a content attribute")
    for key, value in signal.get("attributes", {}).items():
        spec = ATTRIBUTES.get(key)
        if spec is None:
            errors.append(f"attributes: {key} isn't in conventions.json")
            continue
        if not typed(value, spec):
            errors.append(f"attributes: {key} must be {spec['type']}")
        if kind == "metric" and spec["class"] != "label":
            errors.append(f"attributes: {key} is {spec['class']}, and a metric takes labels only")
        if spec["class"] == "content" and key not in (capture or {}).get("fields", []):
            errors.append(f"attributes: {key} is content, kept only under a capture exception naming it")
        elif isinstance(value, str) and spec["class"] != "content":
            if len(value) > MAX_STRING:
                errors.append(f"attributes: {key} is longer than {MAX_STRING} characters")
            what = sensitive(value)
            if what:
                errors.append(f"attributes: {key} reads as {what}")

    if "ingestedAt" in signal:
        ahead = (parse_time(signal["observedAt"]) - parse_time(signal["ingestedAt"])).total_seconds()
        if ahead > SKEW_SECONDS:
            warnings.append(f"observedAt: {int(ahead)}s after ingestedAt; the producer's clock is ahead")
    return errors, warnings


# ---- Migration --------------------------------------------------------------------------

def migration(conv):
    for m in CONVENTIONS["migrations"]:
        if conv == m["from"]:
            return m
    return None


class Unreadable(Exception):
    """An older record used a name the pinned conventions gave another meaning, with no
    faithful replacement."""


def migrate(signal):
    """A copy of an older signal, read under the pinned conventions. Unchanged if current;
    Unreadable if a name it used now means something else and nothing replaces it."""
    m = migration(signal.get("conventions", {}))
    if m is None:
        return signal
    out = copy.deepcopy(signal)
    attrs = out.get("attributes", {})
    for old, new in m["attributes"].items():
        if old in attrs:
            attrs[new] = attrs.pop(old)
    for key, renames in m.get("values", {}).items():
        if attrs.get(key) in renames:
            attrs[key] = renames[attrs[key]]
    rule = m["metrics"].get(out.get("name"))
    if out.get("kind") == "metric" and rule:
        by = attrs.pop(rule["by"], None) if rule["drop"] else attrs.get(rule["by"])
        if by not in rule["values"]:
            raise Unreadable(f"{out['name']} with {rule['by']} {by!r}, written under core "
                             f"{out['conventions']['core']}, has no faithful name under the pins")
        out["name"] = rule["values"][by]
    out["migratedFrom"] = out["conventions"]
    out["conventions"] = dict(m["to"])
    return out


# ---- The trust boundary -----------------------------------------------------------------

TRACEPARENT = re.compile(r"([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})(-.*)?")


def parse_traceparent(header):
    """An incoming traceparent's IDs, or None to start a new trace. Malformed, all-zero or
    version ff headers are dropped, never repaired; a later version is read by its first
    four fields, as the spec says."""
    if not isinstance(header, str):
        return None
    m = TRACEPARENT.fullmatch(header.strip())
    if not m:
        return None
    version, trace_id, parent, flags, rest = m.groups()
    if version == "ff" or (version == "00" and rest) or set(trace_id) == {"0"} or set(parent) == {"0"}:
        return None
    return {"traceId": trace_id, "parentSpanId": parent, "sampled": bool(int(flags, 16) & 1)}


def baggage(header, allow=()):
    """The incoming baggage entries a product allows by key; every other entry is dropped.
    Nothing is allowed by default, and a kept value is still checked like an attribute."""
    kept = {}
    if not isinstance(header, str) or len(header) > 8192:
        return kept
    for member in header.split(","):
        key, sep, value = member.split(";", 1)[0].partition("=")
        key, value = key.strip(), unquote(value.strip())
        if sep and key in allow and len(value) <= MAX_STRING and not sensitive(value):
            kept[key] = value
    return kept


def sanitize(attributes, kind="span", capture=None):
    """The attributes a signal may carry, and the names of those dropped (never values).
    What it keeps always passes check: a known name, its type, no content on a metric and
    none elsewhere without its capture exception, and no string that reads as sensitive."""
    fields = set((capture or {}).get("fields", []))
    kept, dropped = {}, []
    for key, value in (attributes or {}).items():
        spec = ATTRIBUTES.get(key)
        ok = spec is not None and typed(value, spec)
        if ok and spec["class"] == "content":
            ok = kind != "metric" and key in fields
        elif ok and kind == "metric":
            ok = spec["class"] == "label"
        if ok and isinstance(value, str) and spec["class"] != "content":
            ok = len(value) <= MAX_STRING and not sensitive(value)
        if ok:
            kept[key] = value
        else:
            dropped.append(key)
    return kept, sorted(dropped)


def error_type(exc):
    """What a signal records of an exception: its class, never its message, which can hold
    a path, an address, a token or what the user said."""
    name = type(exc).__qualname__ if isinstance(exc, BaseException) else "_OTHER"
    return name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,63}", name) else "_OTHER"


class CrossTenant(Exception):
    """Signals of another tenant were given to a read scoped to one."""


def scoped(signals, tenant):
    signals = list(signals)  # read twice; an iterator would come back empty
    others = sorted({s.get("tenant") for s in signals} - {tenant})
    if others:
        raise CrossTenant(f"signals of {len(others)} other tenant(s) given to a read for {tenant}")
    return signals


def join(signals, tenant):
    """One tenant's signals grouped by run, then task. Signals with neither are kept, under
    None, as unattributed, never dropped or guessed."""
    groups = {}
    for s in scoped(signals, tenant):
        c = s.get("correlation", {})
        key = ("run", c["runId"]) if "runId" in c else ("task", c["taskId"]) if "taskId" in c else None
        groups.setdefault(key, []).append(s)
    return groups


def freshness(signals, tenant, agents, now, stale_after):
    """Each agent's age of evidence: fresh, stale or unknown. No signal is unknown, never
    healthy."""
    latest = {}
    for s in scoped(signals, tenant):
        agent = s.get("correlation", {}).get("agent")
        if agent:
            t = parse_time(s["observedAt"])
            latest[agent] = max(latest.get(agent, t), t)
    out = {}
    for agent in agents:
        if agent not in latest:
            out[agent] = "unknown"
        else:
            out[agent] = "fresh" if (now - latest[agent]).total_seconds() <= stale_after else "stale"
    return out


# ---- Files ------------------------------------------------------------------------------

def read_lines(path):
    for n, line in enumerate(path.read_text().splitlines(), 1):
        if line.strip():
            yield n, json.loads(line)


def shown(path):
    try:
        return path.resolve().relative_to(HIVE.parent.parent)
    except ValueError:
        return path


def check_files(paths, notes=True):
    fail = False
    for path in paths:
        for n, signal in read_lines(path):
            errors, warnings = check(signal)
            for e in errors:
                print(f"FAIL  {shown(path)}:{n}: {e}")
                fail = True
            for w in warnings if notes else []:
                print(f"NOTE  {shown(path)}:{n}: {w}")
    return fail


def check_examples():
    fail = check_files(sorted(EXAMPLES.glob("*.jsonl")), notes=False)  # old-conventions warns by design
    cases = json.loads((EXAMPLES / "invalid.json").read_text())
    for case in cases["cases"]:
        errors, _ = check(case["signal"])
        if not any(case["error"] in e for e in errors):
            print(f"FAIL  examples/invalid.json: {case['name']}: expected an error containing "
                  f"{case['error']!r}, got {errors or 'none'}")
            fail = True
    return fail, len(cases["cases"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("files", nargs="*", type=Path)
    args = ap.parse_args(argv)
    if args.files:
        fail = check_files(args.files)
        if not fail:
            print(f"OK  {len(args.files)} file(s) of signals")
        return 1 if fail else 0
    fail, n = check_examples()
    if not fail:
        print(f"OK  observability-hive signal examples, and {n} invalid ones refused")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
