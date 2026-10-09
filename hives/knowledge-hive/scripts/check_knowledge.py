#!/usr/bin/env python3
"""Check a product's knowledge/ directory against the formats in DESIGN.md.

Checks STATE.md (frontmatter, the five sections in order, the Components and References
tables, the numbered lists), every memory entry, results.jsonl and ledger.jsonl. It also
scans every file for things that must never be written down: secrets, email addresses
and phone numbers. That scan is a heuristic, not a guarantee.

With no arguments it checks this hive's template and worked examples, which is what CI
runs. Pass one or more knowledge/ directories to check a product's.

Standard library only.

Usage:
  python3 scripts/check_knowledge.py
  python3 scripts/check_knowledge.py /path/to/product/knowledge
"""
import datetime
import json
import re
import sys
from pathlib import Path

HIVE = Path(__file__).resolve().parent.parent

KEBAB = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
STATUSES = {"planning", "building", "live", "paused", "retired"}
SECTIONS = ["Summary", "Components", "References", "Open work", "How to resume"]
COMPONENT_STATES = {"built", "live", "partial", "missing"}
MEMORY_TYPES = {"decision", "constraint", "preference", "reference"}
RESULT_KINDS = {"test", "run", "release", "check", "delivery"}
OUTCOMES = {"passed", "failed", "partial"}
EVIDENCE = {"link": "url", "command": "command", "file": "path", "run": "runId", "note": "text"}
RESULT_REQUIRED = ("id", "at", "kind", "subject", "outcome", "summary", "evidence")
LEDGER_FIELDS = {"at", "basis", "usd", "tokens", "tokenDetail", "runId", "step",
                 "capability", "provider", "model"}

# Patterns for values that must never be committed. Heuristics: they catch the common
# shapes, not every secret.
NEVER = [
    ("a private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("an API key or token", re.compile(
        r"\b(sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
        r"|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,})")),
    ("a bearer token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}")),
    ("an email address", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("a phone number", re.compile(r"(?<![\w/.-])\+\d[\d ().-]{8,}\d")),
]


def is_date(value):
    if not isinstance(value, str):
        return False
    try:
        datetime.date.fromisoformat(value)
        return len(value) == 10
    except ValueError:
        return False


def is_datetime(value, utc=False):
    if not isinstance(value, str) or "T" not in value:
        return False
    try:
        dt = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    if utc:
        return dt.utcoffset() == datetime.timedelta(0)
    return dt.tzinfo is not None


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def frontmatter(text):
    """Split '---' YAML frontmatter of plain `key: value` lines from the body."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, text, ["missing YAML frontmatter (the file must start with ---)"]
    fields, errors = {}, []
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return fields, "\n".join(lines[i + 1:]), errors
        if not line.strip():
            continue
        m = re.fullmatch(r"([A-Za-z][A-Za-z0-9_-]*):\s*(.*?)\s*", line)
        if not m:
            errors.append(f"frontmatter line {i + 1} isn't a plain 'key: value' line")
            continue
        key, value = m.groups()
        if key in fields:
            errors.append(f"frontmatter key '{key}' appears twice")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        fields[key] = value
    return None, text, ["frontmatter is never closed with ---"]


def table(lines, header, where, err):
    """Parse the Markdown table in lines, check its header, and return its rows."""
    rows = [l.strip() for l in lines if l.strip().startswith("|")]
    if len(rows) < 2:
        err(f"{where}: needs a table with columns {', '.join(header)}")
        return []
    cells = lambda row: [c.strip() for c in row.strip("|").split("|")]
    if cells(rows[0]) != header:
        err(f"{where}: table columns must be {', '.join(header)}")
        return []
    if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells(rows[1])):
        err(f"{where}: the second table row must be the --- separator")
        return []
    body = [cells(r) for r in rows[2:]]
    for n, r in enumerate(body, start=1):
        if len(r) != len(header) or not all(r):
            err(f"{where}: row {n} must fill all {len(header)} columns")
    return body


def numbered(lines, where, err, allow_none):
    text = [l for l in lines if l.strip()]
    if allow_none and [l.strip() for l in text] == ["None."]:
        return
    items = [l for l in text if re.match(r"\d+\.\s+\S", l)]
    if not items:
        err(f"{where}: needs a numbered list" + (" (or the line 'None.')" if allow_none else ""))
        return
    if any(re.match(r"\d+\.\s+~~", l) for l in items):
        err(f"{where}: remove done items instead of striking them through")
    if any(not l.startswith(f"{i}. ") for i, l in enumerate(items, start=1)):
        err(f"{where}: number the items 1, 2, 3 in order")


def check_state(path, err):
    fields, body, problems = frontmatter(path.read_text())
    for p in problems:
        err(f"STATE.md: {p}")
    if fields is None:
        return
    for key in sorted(set(fields) - {"name", "summary", "status", "updated", "ledger"}):
        err(f"STATE.md: unknown frontmatter key '{key}'")
    for key in ("name", "summary", "status", "updated"):
        if not fields.get(key):
            err(f"STATE.md: frontmatter needs '{key}'")
    if fields.get("name") and not KEBAB.fullmatch(fields["name"]):
        err("STATE.md: name must be kebab-case")
    if fields.get("status") and fields["status"] not in STATUSES:
        err(f"STATE.md: status must be one of {', '.join(sorted(STATUSES))}")
    if fields.get("updated") and not is_date(fields["updated"]):
        err("STATE.md: updated must be a date, YYYY-MM-DD")
    if "ledger" in fields and not fields["ledger"]:
        err("STATE.md: ledger, when present, must say where the ledger is")

    lines = body.split("\n")
    titles = [l[2:].strip() for l in lines if l.startswith("# ")]
    if len(titles) != 1:
        err("STATE.md: needs exactly one top-level '# ' heading, the product's name")
    heads = [(i, l[3:].strip()) for i, l in enumerate(lines) if l.startswith("## ")]
    if [h for _, h in heads] != SECTIONS:
        err(f"STATE.md: sections must be exactly, in order: {', '.join(SECTIONS)}")
        return
    sections = {}
    for n, (i, h) in enumerate(heads):
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        sections[h] = lines[i + 1:end]
    if not any(l.strip() for l in sections["Summary"]):
        err("STATE.md: Summary is empty")
    for row in table(sections["Components"], ["Component", "State", "Note"], "STATE.md Components", err):
        if len(row) == 3 and row[1] not in COMPONENT_STATES:
            err(f"STATE.md Components: state '{row[1]}' must be one of {', '.join(sorted(COMPONENT_STATES))}")
    table(sections["References"], ["Reference", "Kind", "Where"], "STATE.md References", err)
    numbered(sections["Open work"], "STATE.md Open work", err, allow_none=True)
    numbered(sections["How to resume"], "STATE.md How to resume", err, allow_none=False)


def check_memory(path, err):
    where = f"memory/{path.name}"
    fields, body, problems = frontmatter(path.read_text())
    for p in problems:
        err(f"{where}: {p}")
    if fields is None:
        return
    keys = ("name", "description", "type", "updated", "source")
    for key in sorted(set(fields) - set(keys)):
        err(f"{where}: unknown frontmatter key '{key}'")
    for key in keys:
        if not fields.get(key):
            err(f"{where}: frontmatter needs '{key}'")
    if fields.get("name") and fields["name"] != path.stem:
        err(f"{where}: name '{fields['name']}' must equal the file name '{path.stem}'")
    if not KEBAB.fullmatch(path.stem):
        err(f"{where}: the file name must be a kebab-case slug")
    if fields.get("type") and fields["type"] not in MEMORY_TYPES:
        err(f"{where}: type must be one of {', '.join(sorted(MEMORY_TYPES))}")
    if fields.get("updated") and not is_date(fields["updated"]):
        err(f"{where}: updated must be a date, YYYY-MM-DD")
    if not body.strip():
        err(f"{where}: the entry has no body")
    if fields.get("type") in ("decision", "constraint"):
        for label in ("**Why:**", "**How to apply:**"):
            if label not in body:
                err(f"{where}: a {fields['type']} must include {label}")


def jsonl(path, err):
    """Yield (line number, object) for each line, reporting lines that aren't objects."""
    text = path.read_text()
    if text and not text.endswith("\n"):
        err(f"{path.name}: must end with a newline")
    for n, line in enumerate(text.split("\n")[:-1] if text else [], start=1):
        if not line.strip():
            err(f"{path.name}:{n}: blank line")
            continue
        try:
            obj = json.loads(line)
        except ValueError as e:
            err(f"{path.name}:{n}: not valid JSON ({e})")
            continue
        if not isinstance(obj, dict):
            err(f"{path.name}:{n}: each line must be a JSON object")
            continue
        yield n, obj


def check_results(path, err):
    seen = set()
    for n, r in jsonl(path, err):
        at = f"results.jsonl:{n}"
        for key in sorted(set(r) - set(RESULT_REQUIRED) - {"supersedes"}):
            err(f"{at}: unknown field '{key}'")
        for key in RESULT_REQUIRED:
            if key not in r:
                err(f"{at}: missing '{key}'")
        for key in ("id", "subject", "summary"):
            if key in r and (not isinstance(r[key], str) or not r[key].strip()):
                err(f"{at}: {key} must be a non-empty string")
        rid = r.get("id")
        if isinstance(rid, str):
            if rid in seen:
                err(f"{at}: id '{rid}' is already used")
        if "at" in r and not (is_date(r["at"]) or is_datetime(r["at"])):
            err(f"{at}: at must be an ISO 8601 date or a date-time with a time zone")
        if "kind" in r and r["kind"] not in RESULT_KINDS:
            err(f"{at}: kind must be one of {', '.join(sorted(RESULT_KINDS))}")
        if "outcome" in r and r["outcome"] not in OUTCOMES:
            err(f"{at}: outcome must be one of {', '.join(sorted(OUTCOMES))}")
        if "supersedes" in r and r["supersedes"] not in seen:
            err(f"{at}: supersedes must name an earlier result's id")
        ev = r.get("evidence")
        if "evidence" in r and (not isinstance(ev, list) or not ev):
            err(f"{at}: evidence must be a non-empty list")
        elif isinstance(ev, list):
            for i, e in enumerate(ev):
                field = EVIDENCE.get(e.get("kind")) if isinstance(e, dict) else None
                if not field:
                    err(f"{at}: evidence[{i}].kind must be one of {', '.join(EVIDENCE)}")
                elif set(e) != {"kind", field} or not isinstance(e[field], str) or not e[field].strip():
                    err(f"{at}: evidence[{i}] of kind {e['kind']} needs exactly a non-empty '{field}'")
        if isinstance(rid, str):
            seen.add(rid)


def check_ledger(path, err):
    for n, e in jsonl(path, err):
        at = f"{path.name}:{n}"
        for key in sorted(set(e) - LEDGER_FIELDS):
            err(f"{at}: unknown field '{key}'")
        if not is_datetime(e.get("at"), utc=True):
            err(f"{at}: at must be an ISO 8601 date-time in UTC")
        if e.get("basis") not in ("metered", "estimated"):
            err(f"{at}: basis must be metered or estimated")
        if "usd" not in e and "tokens" not in e:
            err(f"{at}: needs usd, tokens or both")
        if "usd" in e and (not number(e["usd"]) or e["usd"] < 0):
            err(f"{at}: usd must be a non-negative number")
        if "tokens" in e and (not integer(e["tokens"]) or e["tokens"] < 0):
            err(f"{at}: tokens must be a non-negative integer")
        if "tokenDetail" in e:
            d = e["tokenDetail"]
            if (not isinstance(d, dict) or set(d) != {"input", "output"}
                    or not all(integer(v) and v >= 0 for v in d.values())):
                err(f"{at}: tokenDetail must be {{input, output}}, both non-negative integers")
            elif e.get("tokens") != d["input"] + d["output"]:
                err(f"{at}: tokenDetail input and output must add up to tokens")
        for key in ("runId", "step", "capability", "provider", "model"):
            if key in e and (not isinstance(e[key], str) or not e[key]):
                err(f"{at}: {key} must be a non-empty string")


def scan(path, rel, err):
    """Report secrets and personal data. Returns False when the file isn't UTF-8 text."""
    try:
        text = path.read_text()
    except UnicodeDecodeError:
        err(f"{rel}: not UTF-8 text")
        return False
    for what, pattern in NEVER:
        if pattern.search(text):
            err(f"{rel}: looks like it contains {what}; knowledge/ must never hold one")
    return True


def check(knowledge):
    """All problems in one knowledge/ directory."""
    errors = []
    err = errors.append
    if not knowledge.is_dir():
        return [f"{knowledge} is not a directory"]
    state = knowledge / "STATE.md"
    known = {state, knowledge / "results.jsonl", knowledge / "ledger.jsonl"}
    unreadable = set()
    for f in sorted(p for p in knowledge.rglob("*") if p.is_file()):
        if not scan(f, f.relative_to(knowledge), err):
            unreadable.add(f)
        if f not in known and f.parent != knowledge / "memory":
            err(f"{f.relative_to(knowledge)}: not part of the format")
        elif f.parent == knowledge / "memory" and f.suffix != ".md":
            err(f"{f.relative_to(knowledge)}: memory entries are .md files")
    if not state.is_file():
        err("STATE.md is missing")
    elif state not in unreadable:
        check_state(state, err)
    for f in sorted((knowledge / "memory").glob("*.md")):
        if f not in unreadable:
            check_memory(f, err)
    for name, checker in (("results.jsonl", check_results), ("ledger.jsonl", check_ledger)):
        f = knowledge / name
        if f.is_file() and f not in unreadable:
            checker(f, err)
    return errors


def main():
    dirs = [Path(a) for a in sys.argv[1:]] or \
        [HIVE / "templates" / "knowledge"] + sorted(HIVE.glob("examples/*/knowledge"))
    fail = 0
    for d in dirs:
        label = d.relative_to(HIVE.parent.parent) if HIVE.parent.parent in d.resolve().parents else d
        errors = check(d)
        for e in errors:
            print(f"FAIL  {label}: {e}")
        fail |= bool(errors)
    if not fail:
        print(f"OK  {len(dirs)} knowledge directories valid")
    return fail


if __name__ == "__main__":
    sys.exit(main())
