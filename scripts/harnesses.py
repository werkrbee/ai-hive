#!/usr/bin/env python3
"""Read harnesses.json, the harness registry, for every installer and page.

The registry is the only place a harness, its category and tier, its install paths, and
its capability and price row are written down (docs/harness-ecosystem.md). Python
installers import this module; shell installers call it. `matrix` writes the readable
table, docs/harness-matrix.md, and the index of harness guides, docs/harness-guides.md.
`check` is what CI runs: the registry is well formed, every claim in a row names its source and the date it was checked, each recorded run has
its category's shape, a verified row has no unknowns and records its runs, no row in either ten was checked more than 90 days ago,
the table and the guides index are current, each hive's adapters/ matches the registry, and each README that
draws an adapters/ tree names every adapter. `conformance` is what check-installers.sh
runs: it installs the House for every harness with install paths into a sandbox and
looks for each file where the registry says it lands.

Standard library only.

Usage:
  python3 scripts/harnesses.py path SURFACE SCOPE HARNESS [--name NAME]
      print where HARNESS reads SURFACE (skills, rules, agents) at SCOPE (global or
      project), with ~ expanded and {name} filled in; exit 1 if it has none
  python3 scripts/harnesses.py list [--surface SURFACE] [--category CATEGORY]
      print harness ids, one per line, in registry order
  python3 scripts/harnesses.py matrix
      rewrite docs/harness-matrix.md and docs/harness-guides.md from the registry
  python3 scripts/harnesses.py check
  python3 scripts/harnesses.py conformance SANDBOX
      install into SANDBOX for every harness with install paths; fail if a top-ten
      harness's file is missing, and report the rest
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "harnesses.json"
MATRIX = ROOT / "docs" / "harness-matrix.md"
GUIDES = ROOT / "docs" / "harness-guides.md"
# Where a harness's guide is, named for its id: Barry's harness references (P3's harness guides).
GUIDE_DIR = ROOT / "hives" / "skills-hive" / "skills" / "barry" / "references" / "harnesses"
SURFACES = ("skills", "rules", "agents", "mcp")
SCOPES = ("global", "project")

# What a row says about a harness, by category, in table order, with each column's heading.
CAPABILITIES = {
    "pro-code": {"rules": "Rules", "skills": "Skills", "subagents": "Subagents", "mcp": "MCP servers",
                 "hooks": "Hooks", "memory": "Memory", "permissions": "Permissions", "headless": "Headless"},
    "low-code": {"mcp": "MCP", "a2a": "A2A", "openapi": "OpenAPI connectors", "auth": "Auth"},
}
# Where a capability's path comes from when the installers already write it down.
CAPABILITY_SURFACE = {"rules": "rules", "skills": "skills", "subagents": "agents"}
# How a harness bills tokens: at the model's list price (plus any fee), on the person's own
# key at list price, or at a rate it doesn't publish.
BASES = ("list", "own-key", "not-published")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# A row in either ten checked longer ago than this is stale: CI fails until it's re-verified.
STALE_AFTER_DAYS = 90
# What conformance installs, one of each, and what a file it writes is named.
SKILL, RULESET, AGENT = "barry", "queen-charter", "explore"
# Who a pro-code harness's recorded run is of: alignment runs each once in the real harness.
RUN_AGENTS = ("barry", "patricia")
# What a recorded run writes down, and the tokens it counts.
RUN_FIELDS = ("agent", "date", "version", "model", "how", "tokens", "cost", "result")
RUN_TOKENS = ("input", "cache_write", "cached", "output")
# A low-code platform calls Patricia, so its row records a run of her, metered twice
# (docs/low-code-alignment.md, "Units consumed"): the platform's units, with their basis
# and source, and its tokens where it reports them, each unknown count null and never zero;
# and the House's tokens and dollars from Patricia's ledger, kept apart from the
# platform's cost. version is null where the platform shows none.
LOW_CODE_RUN_AGENT = "patricia"
LOW_CODE_RUN_FIELDS = ("agent", "date", "version", "binding", "auth", "units", "tokens", "house", "cost",
                       "result")
BINDINGS = ("mcp", "a2a", "openapi")
AUTH_ROUTES = ("app", "delegated")
UNIT_BASES = ("reported", "estimated", "not-reported")


def load(path=REGISTRY):
    return json.loads(Path(path).read_text())


def harnesses(registry=None, surface=None, category=None):
    """The harness entries, in registry order, optionally only those with SURFACE or in CATEGORY."""
    out = []
    for h in (registry or load())["harnesses"]:
        if surface and surface not in h["surfaces"]:
            continue
        if category and h["category"] != category:
            continue
        out.append(h)
    return out


def get(harness_id, registry=None):
    for h in (registry or load())["harnesses"]:
        if h["id"] == harness_id:
            return h
    return None


def surface(harness_id, name, registry=None):
    """HARNESS's entry for surface NAME, or None. A fallback is returned as written."""
    h = get(harness_id, registry)
    return h["surfaces"].get(name) if h else None


def path(harness_id, name, scope, fill=None, registry=None):
    """Where HARNESS reads surface NAME at SCOPE, expanded, or None if it has none."""
    s = surface(harness_id, name, registry)
    if not s or scope not in s:
        return None
    p = s[scope]
    if fill is not None:
        p = p.replace("{name}", fill)
    return os.path.expanduser(p)


def dumps(registry):
    """The registry as JSON, with any object that fits on one line kept on one line, so a
    reviewer reads one claim per line."""
    def fmt(v, indent):
        flat = json.dumps(v, ensure_ascii=False)
        if not isinstance(v, (dict, list)) or len(flat) + indent <= 120:
            return flat
        pad, inner = " " * indent, " " * (indent + 2)
        if isinstance(v, list):
            return "[\n" + ",\n".join(inner + fmt(x, indent + 2) for x in v) + "\n" + pad + "]"
        return "{\n" + ",\n".join(f"{inner}{json.dumps(k)}: {fmt(x, indent + 2)}" for k, x in v.items()) \
            + "\n" + pad + "}"
    return fmt(registry, 0) + "\n"


def money(v):
    """Dollars as the docs write them: $2, $0.20, $2.25."""
    text = f"{v:,.2f}"
    return "$" + (text[:-3] if text.endswith(".00") else text)


def fee_for(t, m):
    """The fee a row's tokens add to model M: the row's fee, 0 when M is exempt because its
    cached rate is under the row's fee_exempt_below (Cursor's Token Rate spares a model
    whose cache reads cost under $0.10), or None when that can't be told because M's cached
    rate isn't recorded. Cursor asks for every pricing tier to be under the threshold; a
    model's row records one tier, the one its name gives, so check a model's other tiers
    before quoting it as exempt."""
    fee, below = t.get("fee", 0), t.get("fee_exempt_below")
    if not fee or below is None:
        return fee
    if m["cached"] is None:
        return None
    return 0 if m["cached"] < below else fee


def effective(h, registry):
    """[(model name, input, cached, output)] in dollars per million tokens, as strings, or a
    sentence when no rate can be derived."""
    t = h["cost"]["tokens"]
    if t["basis"] == "not-published":
        return "Not published"
    if t["basis"] == "own-key":
        return "The model's list price, on your own key" + (f"; {t['note']}" if t.get("note") else "")
    rows = []
    for mid in t["models"]:
        m = registry["models"][mid]
        fee = fee_for(t, m)
        if fee is None:
            rows.append((m["name"], "unknown", "unknown", "unknown"))
            continue
        # Unknown, not "not published": a fee the row doesn't say covers cached tokens
        # (fee_cached), or a cached rate nobody has recorded yet, is a gap in the row, not a
        # claim about the vendor.
        if m["cached"] is None or (fee and not t.get("fee_cached")):
            cached = "unknown"
        else:
            cached = money(m["cached"] + fee)
        rows.append((m["name"], money(m["input"] + fee), cached, money(m["output"] + fee)))
    return rows


def link(source):
    """A source as a Markdown link: URLs as they are, repo paths relative to docs/."""
    if source.startswith("http"):
        return f"[{source.split('//', 1)[1].split('/', 1)[0]}]({source})"
    return f"[`{source}`](../{source}) (the House's installer, not the vendor's docs)"


def render_matrix(registry=None):
    """docs/harness-matrix.md, generated from the registry."""
    reg = registry or load()
    out = ["# The harness matrix", "",
           "_Generated from `harnesses.json` by `python3 scripts/harnesses.py matrix`; edit the "
           "registry, not this file._", "",
           "What works in each harness the House commits to, and what it costs, with the source and "
           "the date behind every claim. Why these harnesses, what aligned means and how cost is "
           "compared: [`harness-ecosystem.md`](harness-ecosystem.md). A row is unverified until its harness's alignment issue "
           "checks every field against the vendor's own docs and price page; until then, read it as "
           "a lead, not a fact. A field nobody has evidence for says unknown.", ""]
    for cat, title in (("pro-code", "Pro-code"), ("low-code", "Low-code")):
        rows = sorted((h for h in reg["harnesses"] if h["category"] == cat and h["tier"] == "top-ten"),
                      key=lambda h: h["rank"])
        caps = CAPABILITIES[cat]
        out += [f"## {title}", "", "### What works", "",
                "| Harness | " + " | ".join(caps.values()) + " | Row |",
                "|---|" + "---|" * len(caps) + "---|"]
        for h in rows:
            cells = []
            for key in caps:
                c = h["capabilities"][key]
                if c["supported"] == "unknown":
                    cells.append("unknown")
                    continue
                if not c["supported"]:
                    cells.append("no")
                    continue
                paths = []
                surface_name = CAPABILITY_SURFACE.get(key)
                if surface_name:
                    sv = h["surfaces"].get(surface_name, {})
                    paths = [sv[sc] for sc in ("project", "global") if sc in sv]
                elif c.get("path"):
                    paths = [c["path"]]
                cells.append("yes" + "".join(f"<br>`{p}`" for p in paths))
            row = "verified" if h["verified"] else "unverified"
            out.append(f"| {h['name']} | " + " | ".join(cells) + f" | {row} |")
        out += ["", "### What it costs", "",
                "| Harness | Billing unit and retail price | Effective $ per 1M tokens: input · cached input · output | Checked |",
                "|---|---|---|---|"]
        for h in rows:
            c = h["cost"]
            eff = effective(h, reg)
            if isinstance(eff, str):
                cell = eff
            else:
                t = c["tokens"]
                notes = []
                for mid in t["models"]:
                    fee = fee_for(t, reg["models"][mid])
                    if fee:
                        notes.append(f" ({t['fee_applies']}, list + {money(fee)})")
                    elif fee == 0 and t.get("fee"):
                        notes.append(f" (list; exempt from the fee, cache reads under {money(t['fee_exempt_below'])})")
                    elif fee is None:
                        notes.append(" (whether the fee applies turns on a cached rate not recorded)")
                    else:
                        notes.append("")
                cell = "<br>".join(f"{n}: {i} · {ca} · {o}{note}" for (n, i, ca, o), note in zip(eff, notes))
            out.append(f"| {h['name']} | {c['unit']} | {cell} | {c['checked']} |")
        out.append("")
        ran = [(h, r) for h in rows for r in h.get("runs", [])]
        if ran and cat == "low-code":
            out += low_code_runs(ran)
        elif ran:
            out += ["### Recorded runs", "",
                    "Barry and Patricia run once in the real harness when it's aligned. The run doubles "
                    "as the reference task that cost is compared on; its cost is the harness's own figure.", "",
                    "| Harness | Agent | Date | Version | Model | Tokens: input · cache write · cached · output | Cost | How | Result |",
                    "|---|---|---|---|---|---|---|---|---|"]
            for h, r in ran:
                t = " · ".join(f"{r['tokens'][k]:,}" for k in RUN_TOKENS)
                model = reg["models"].get(r["model"], {}).get("name", r["model"])
                out.append(f"| {h['name']} | {r['agent'].capitalize()} | {r['date']} | {r['version']} | "
                           f"{model} | {t} | {r['cost']} | `{r['how']}` | {r['result']} |")
            out.append("")
    out += ["## Model list prices", "",
            "The rates the effective prices start from, in dollars per million tokens.", "",
            "| Model | Input | Cached input | Output | Source | Checked |", "|---|---|---|---|---|---|"]
    for m in reg["models"].values():
        cached = "unknown" if m["cached"] is None else money(m["cached"])
        out.append(f"| {m['name']} | {money(m['input'])} | {cached} | {money(m['output'])} | "
                   f"{link(m['source'])} | {m['checked']} |")
    out += ["", "## Sources", ""]
    for cat in ("pro-code", "low-code"):
        for h in sorted((h for h in reg["harnesses"] if h["category"] == cat and h["tier"] == "top-ten"),
                        key=lambda h: h["rank"]):
            caps = {}
            for key, c in h["capabilities"].items():
                if c["supported"] != "unknown":
                    caps.setdefault((c["source"], c["checked"]), []).append(CAPABILITIES[cat][key])
            parts = [f"{', '.join(names)}: {link(src)}, {when}" for (src, when), names in caps.items()]
            parts.append("cost: " + ", ".join(link(u) for u in h["cost"]["sources"]) + f", {h['cost']['checked']}")
            out.append(f"- **{h['name']}.** " + "; ".join(parts) + ".")
    return "\n".join(out) + "\n"


def render_guides(registry=None, guide_dir=None):
    """docs/harness-guides.md, generated from the registry: for each of the twenty, its guide,
    matrix row, price and recorded runs, and plainly none yet where one doesn't exist. Guides
    are looked for in GUIDE_DIR, or in guide_dir when tests pass one, and linked where they're
    committed."""
    reg = registry or load()
    guide_dir = Path(guide_dir or GUIDE_DIR)
    out = ["# The harness guides", "",
           "_Generated from `harnesses.json` by `python3 scripts/harnesses.py matrix`; edit the "
           "registry or the guides, not this file._", "",
           "One page for picking a harness: for each of the twenty the House aligns with, the guide "
           "to using the House in it, its row in the [harness matrix](harness-matrix.md), what it "
           "costs and the runs recorded in it. Why these twenty: "
           "[`harness-ecosystem.md`](harness-ecosystem.md). A guide explains the surfaces and how to "
           "get the most from them; the matrix holds the paths, sources and effective rates, and an "
           "unverified row is a lead, not a fact. A price is as of the date beside it, so check it "
           "again before a decision rests on it. Where a guide or a run doesn't exist yet, the page "
           "says none yet; each harness's alignment issue adds them.", ""]
    for cat, title in (("pro-code", "Pro-code"), ("low-code", "Low-code")):
        rows = sorted((h for h in reg["harnesses"] if h["category"] == cat and h["tier"] == "top-ten"),
                      key=lambda h: h["rank"])
        guides = sum((guide_dir / f"{h['id']}.md").is_file() for h in rows)
        ran = sum(bool(h.get("runs")) for h in rows)
        verified = sum(h["verified"] for h in rows)
        out += [f"## {title}", "",
                f"{guides} of {len(rows)} have a guide, {ran} a recorded run and {verified} a verified row.", "",
                "| Harness | Guide | Matrix row | Billing unit and retail price | Price checked | Recorded runs |",
                "|---|---|---|---|---|---|"]
        for h in rows:
            name = f"{h['id']}.md"
            guide = (f"[`{name}`](../{(GUIDE_DIR / name).relative_to(ROOT).as_posix()})"
                     if (guide_dir / name).is_file() else "none yet")
            row = f"[{'verified' if h['verified'] else 'unverified'}](harness-matrix.md#{cat})"
            runs = ", ".join(f"{r['agent'].capitalize()} {r['date']}" +
                             (f" over {r['binding']}" if cat == "low-code" else "") for r in h.get("runs", []))
            vendor = "" if h["vendor"] in h["name"] else f" ({h['vendor']})"
            out.append(f"| {h['rank']}. {h['name']}{vendor} | {guide} | {row} | "
                       f"{h['cost']['unit']} | {h['cost']['checked']} | {runs or 'none yet'} |")
        out.append("")
    return "\n".join(out) + "\n"


def count(v):
    """A token count as the tables write it, or unknown for null."""
    return "unknown" if v is None else f"{v:,}"


def low_code_runs(ran):
    """The low-code recorded-runs table: the platform's meter, then the House's, apart."""
    out = ["### Recorded runs", "",
           "Patricia is called once from an agent built in the platform when it's aligned. The "
           "platform's units and cost are the harness's own figures; the House's tokens and dollars "
           "are her ledger's, recorded beside the run and never added to its cost.", "",
           "| Harness | Agent | Date | Version | Binding | Auth | Platform units | "
           "Platform tokens: input · cache write · cached · output | Cost | The House's tokens · $ | Result |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    for h, r in ran:
        u = r["units"]
        units = (f"not reported ({u['source']})" if u["basis"] == "not-reported"
                 else f"{u['amount']:,} {u['unit']}, {u['basis']} ({u['source']})")
        tokens = " · ".join(count(r["tokens"][k]) for k in RUN_TOKENS)
        house = f"{r['house']['tokens']:,} · ${r['house']['usd']:.4f}"
        out.append(f"| {h['name']} | {r['agent'].capitalize()} | {r['date']} | {r['version'] or 'not shown'} | "
                   f"{r['binding']} | {r['auth']} | {units} | {tokens} | {r['cost']} | {house} | {r['result']} |")
    return out + [""]


def run_problems(r, category, models):
    """What's wrong with one recorded run of a row in category; empty when it's well formed."""
    if category != "low-code":
        missing = [k for k in RUN_FIELDS if k not in r]
        if missing:
            return [f"lacks {', '.join(missing)}"]
        problems = []
        if not DATE.match(str(r["date"])):
            problems.append("has no date (YYYY-MM-DD)")
        if r["model"] not in models:
            problems.append(f"names model {r['model']!r}, which isn't in models")
        if not all(isinstance(r["tokens"].get(k), int) for k in RUN_TOKENS):
            problems.append(f"counts tokens as {', '.join(RUN_TOKENS)}")
        return problems

    missing = [k for k in LOW_CODE_RUN_FIELDS if k not in r]
    if missing:
        return [f"lacks {', '.join(missing)}"]
    problems = []
    if r["agent"] != LOW_CODE_RUN_AGENT:
        problems.append(f"is of {r['agent']!r}; a low-code run is of {LOW_CODE_RUN_AGENT}")
    if not DATE.match(str(r["date"])):
        problems.append("has no date (YYYY-MM-DD)")
    if r["version"] is not None and not (isinstance(r["version"], str) and r["version"]):
        problems.append("names the platform's version, or null where it shows none")
    if r["binding"] not in BINDINGS:
        problems.append(f"binding must be one of {', '.join(BINDINGS)}")
    if r["auth"] not in AUTH_ROUTES:
        problems.append(f"auth must be one of {', '.join(AUTH_ROUTES)}")

    u = r["units"] if isinstance(r["units"], dict) else {}
    if u.get("basis") not in UNIT_BASES:
        problems.append(f"units basis must be one of {', '.join(UNIT_BASES)}")
    elif u["basis"] == "not-reported":
        if u.get("amount") is not None:
            problems.append("units not reported have a null amount, never zero")
    elif not number(u.get("amount")):
        problems.append(f"{u['basis']} units have an amount")
    if not (isinstance(u.get("unit"), str) and u["unit"]):
        problems.append("units name the platform's unit")
    if not (isinstance(u.get("source"), str) and u["source"]):
        problems.append("units name their source: the usage report, or the rates they're worked out from")

    t = r["tokens"] if isinstance(r["tokens"], dict) else {}
    if set(t) != set(RUN_TOKENS) or not all(v is None or (isinstance(v, int) and not isinstance(v, bool)
                                                          and v >= 0) for v in t.values()):
        problems.append(f"counts the platform's tokens as {', '.join(RUN_TOKENS)}, each a count or null")
    elif any(t[k] == 0 for k in ("input", "output")):
        problems.append("records an unknown token count as zero; it is null")

    house = r["house"] if isinstance(r["house"], dict) else {}
    if not (isinstance(house.get("tokens"), int) and not isinstance(house["tokens"], bool)
            and house["tokens"] > 0) or not number(house.get("usd")):
        problems.append("records the House's tokens and usd from Patricia's ledger")
    if "taskId" in house and not (isinstance(house["taskId"], str) and house["taskId"]):
        problems.append("names the ledger entry's taskId as a string, or leaves it out")
    for key in ("cost", "result"):
        if not (isinstance(r[key], str) and r[key]):
            problems.append(f"says its {key}")
    return problems


def number(v):
    """A finite, non-negative number, and not a bool."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 and v == v and v != float("inf")


def adapters(registry=None):
    """Top-level adapter directory -> display name, in registry order."""
    return {h["adapter"]: h["name"] for h in (registry or load())["harnesses"]
            if h.get("adapter") and "/" not in h["adapter"]}


def row_dates(h, registry):
    """Every date checked that a top-ten harness's row rests on: its capabilities, its cost,
    and the list prices of the models its cost is quoted for."""
    dates = [c["checked"] for c in h.get("capabilities", {}).values() if "checked" in c]
    cost = h.get("cost", {})
    if "checked" in cost:
        dates.append(cost["checked"])
    for mid in cost.get("tokens", {}).get("models", []):
        m = registry.get("models", {}).get(mid)
        if m and "checked" in m:
            dates.append(m["checked"])
    return [d for d in dates if DATE.match(str(d))]


def stale(registry, today=None):
    """[(harness name, oldest date, days ago)] for each top-ten row checked more than
    STALE_AFTER_DAYS ago."""
    today = today or datetime.date.today()
    out = []
    for h in registry["harnesses"]:
        if h["tier"] != "top-ten":
            continue
        dates = row_dates(h, registry)
        if dates:
            oldest = min(dates)
            days = (today - datetime.date.fromisoformat(oldest)).days
            if days > STALE_AFTER_DAYS:
                out.append((h["name"], oldest, days))
    return out


def check(registry=None, today=None):
    """Problems with the registry and what must agree with it; empty when all is well."""
    reg = registry or load()
    problems = []
    entries = reg["harnesses"]
    ids = [h["id"] for h in entries]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        problems.append(f"harness id {dup!r} appears more than once")

    for h in entries:
        where = f"harness {h['id']!r}"
        if h["category"] not in reg["categories"]:
            problems.append(f"{where}: unknown category {h['category']!r}")
        if h["tier"] is not None and h["tier"] not in reg["tiers"]:
            problems.append(f"{where}: unknown tier {h['tier']!r}")
        if (h["tier"] == "top-ten") != (h["rank"] is not None):
            problems.append(f"{where}: a rank goes with the top-ten tier, and only with it")
        if h.get("parent") and h["parent"] not in ids:
            problems.append(f"{where}: parent {h['parent']!r} isn't a harness")
        for name, s in h["surfaces"].items():
            if name not in SURFACES:
                problems.append(f"{where}: unknown surface {name!r}")
            elif "fallback" in s:
                target = surface(s["fallback"], name, reg)
                if not target or "fallback" in target:
                    problems.append(f"{where}: {name} falls back to {s['fallback']!r}, which has no {name} paths")
            elif not any(scope in s for scope in SCOPES):
                problems.append(f"{where}: {name} has neither a global nor a project path")
            if name == "mcp":
                fmt = s.get("format")
                if fmt not in ("json", "toml", "yaml"):
                    problems.append(f"{where}: mcp format must be json, toml or yaml")
                if fmt in ("toml", "yaml") and s.get("snippet") is not True:
                    problems.append(f"{where}: non-JSON mcp config must be a snippet")
                if fmt == "json":
                    if s.get("snippet"):
                        problems.append(f"{where}: JSON mcp config cannot be a snippet")
                    for scope in SCOPES:
                        if scope not in s:
                            continue
                        keys = s.get("keys")
                        key = keys.get(scope) if isinstance(keys, dict) else None
                        if not isinstance(key, str) or not key or any(not p for p in key.split(".")):
                            problems.append(f"{where}: mcp {scope} needs a servers key")
                        env = s.get("env")
                        env = env if isinstance(env, dict) else {}
                        if scope not in env or (env[scope] is not None and
                                               (not isinstance(env[scope], str) or env[scope].count("%s") != 1
                                                or "%" in env[scope].replace("%s", ""))):
                            problems.append(f"{where}: mcp {scope} needs an env reference with one %s, or null")
            for scope in SCOPES:
                if scope in s and (not isinstance(s[scope], str) or not s[scope]):
                    problems.append(f"{where}: {name} {scope} path must be a nonempty string")
            for field in ("windows_order", "windows_default_order", "default_order"):
                if field in s and (type(s[field]) is not int or s[field] < 1):
                    problems.append(f"{where}: {name} {field} must be a positive integer")
            if "windows_order" in s and (name != "skills" or not isinstance(s.get("global"), str)
                                         or not s["global"].startswith("~/")):
                problems.append(f"{where}: windows_order needs a global skills path under ~/")
            if "windows_default_order" in s and (name != "rules" or not isinstance(s.get("project"), str)
                                                 or not s["project"]):
                problems.append(f"{where}: windows_default_order needs a project rules path")
            if "default_order" in s and name != "mcp":
                problems.append(f"{where}: default_order belongs to mcp")
            aliases = s.get("windows_aliases", [])
            if not isinstance(aliases, list) or any(not isinstance(a, str) or not a for a in aliases):
                problems.append(f"{where}: {name} windows_aliases must be nonempty strings")

    for name, field in (("skills", "windows_order"), ("rules", "windows_default_order"),
                        ("mcp", "default_order")):
        orders = [h["surfaces"].get(name, {}).get(field) for h in entries
                  if type(h["surfaces"].get(name, {}).get(field)) is int]
        if len(orders) != len(set(orders)):
            problems.append(f"{name}: duplicate {field}")
    aliases = []
    for h in entries:
        names = h["surfaces"].get("skills", {}).get("windows_aliases", [])
        if isinstance(names, list):
            aliases.extend(a.lower() for a in names if isinstance(a, str))
    if len(aliases) != len(set(aliases)) or set(aliases) & {i.lower() for i in ids}:
        problems.append("skills: Windows aliases must be unique and distinct from harness ids")

    for cat in ("pro-code", "low-code"):
        ranks = sorted(h["rank"] for h in entries if h["category"] == cat and h["tier"] == "top-ten")
        if ranks != list(range(1, 11)):
            problems.append(f"{cat}: the top ten must be ranked 1 to 10, found {ranks}")

    def evidence(where, item, source_key="source"):
        sources = item.get(source_key)
        sources = sources if isinstance(sources, list) else [sources]
        if not all(isinstance(x, str) and x for x in sources) or not sources:
            problems.append(f"{where}: names no source")
        elif not all(x.startswith("https://") or (ROOT / x).exists() for x in sources):
            problems.append(f"{where}: a source is neither an https URL nor a file in the repo")
        if not DATE.match(str(item.get("checked", ""))):
            problems.append(f"{where}: no date checked (YYYY-MM-DD)")

    for mid, m in reg.get("models", {}).items():
        evidence(f"model {mid!r}", m)
    for h in entries:
        where = f"harness {h['id']!r}"
        if h["tier"] != "top-ten":
            if "capabilities" in h or "cost" in h:
                problems.append(f"{where}: only a harness in a top ten has a matrix row")
            continue
        caps = h.get("capabilities", {})
        for key in sorted(set(CAPABILITIES[h["category"]]) ^ set(caps)):
            problems.append(f"{where}: its row {'lacks' if key not in caps else 'has an unknown field'} {key!r}")
        for key, c in caps.items():
            if c.get("supported") not in (True, False, "unknown"):
                problems.append(f"{where}: {key} must be supported true, false or \"unknown\"")
            elif c["supported"] != "unknown":
                evidence(f"{where}: {key}", c)
        cost = h.get("cost")
        if not cost:
            problems.append(f"{where}: its row has no cost")
        else:
            evidence(f"{where}: cost", cost, "sources")
            t = cost.get("tokens", {})
            if t.get("basis") not in BASES:
                problems.append(f"{where}: cost basis must be one of {', '.join(BASES)}")
            for mid in t.get("models", []):
                if mid not in reg.get("models", {}):
                    problems.append(f"{where}: cost names model {mid!r}, which isn't in models")
            if t.get("note") is not None and t.get("basis") != "own-key":
                problems.append(f"{where}: a cost note goes with the own-key basis")
            if "fee_cached" in t and (not isinstance(t["fee_cached"], bool) or not t.get("fee")):
                problems.append(f"{where}: fee_cached is true or false, and goes with a fee")
            if "fee_exempt_below" in t and (not number(t["fee_exempt_below"]) or not t.get("fee")):
                problems.append(f"{where}: fee_exempt_below is a non-negative number, and goes with a fee")
            if t.get("basis") == "list" and not t.get("models"):
                problems.append(f"{where}: a list-price basis names the models it's quoted for")
        for i, r in enumerate(h.get("runs", [])):
            for p in run_problems(r, h["category"], reg.get("models", {})):
                problems.append(f"{where}: run {i + 1} {p}")
        if not isinstance(h.get("verified"), bool):
            problems.append(f"{where}: its row says whether it's verified (true or false)")
        elif h["verified"]:
            unknown = sorted(k for k, c in caps.items() if c.get("supported") == "unknown")
            if unknown:
                problems.append(f"{where}: a verified row has no unknowns, found {', '.join(unknown)}")
            ran = {r.get("agent") for r in h.get("runs", [])}
            if h["category"] == "pro-code" and not set(RUN_AGENTS) <= ran:
                problems.append(f"{where}: a verified pro-code row records a run of "
                                f"{' and '.join(RUN_AGENTS)}")
            if h["category"] == "low-code" and LOW_CODE_RUN_AGENT not in ran:
                problems.append(f"{where}: a verified low-code row records a run of {LOW_CODE_RUN_AGENT}")

    for name, oldest, days in stale(reg, today):
        problems.append(f"{name}: its row was last checked {oldest}, {days} days ago (over "
                        f"{STALE_AFTER_DAYS}); re-verify it, as CONTRIBUTING.md describes")

    if not problems:
        if not MATRIX.is_file() or MATRIX.read_text() != render_matrix(reg):
            problems.append(f"{MATRIX.relative_to(ROOT)} is out of date: run python3 scripts/harnesses.py matrix")
        if not GUIDES.is_file() or GUIDES.read_text() != render_guides(reg):
            problems.append(f"{GUIDES.relative_to(ROOT)} is out of date: run python3 scripts/harnesses.py matrix")

    expected = set(adapters(reg))
    nested = {h["adapter"] for h in entries if h.get("adapter") and "/" in h["adapter"]}
    for hive in sorted(p for p in (ROOT / "hives").glob("*/adapters") if p.is_dir()):
        rel = hive.relative_to(ROOT)
        found = {p.name for p in hive.iterdir() if p.is_dir()}
        for name in sorted(expected - found):
            problems.append(f"{rel}/: missing {name}/ (in harnesses.json)")
        for name in sorted(found - expected):
            problems.append(f"{rel}/: {name}/ isn't in harnesses.json")
        for sub in sorted(nested):
            if sub.split("/")[0] in found and not (hive / sub).is_dir():
                problems.append(f"{rel}/: missing {sub}/ (in harnesses.json)")
        readme = hive.parent / "README.md"
        if readme.is_file():
            text = readme.read_text()
            for name in sorted(expected):
                if f"{name}/" not in text:
                    problems.append(f"{readme.relative_to(ROOT)}: its adapters/ tree doesn't name {name}/")
    taxonomy = ROOT / "hives" / "skills-hive" / "adapters" / "README.md"
    if taxonomy.is_file():
        text = taxonomy.read_text()
        for name in sorted(expected):
            if f"{name}/" not in text:
                problems.append(f"{taxonomy.relative_to(ROOT)}: doesn't name {name}/")
    return problems


def conformance(sandbox, registry=None, prepare=None):
    """Install the House into SANDBOX for every harness with install paths, and look for each
    file where the registry says it lands. Returns (failures, reports, checked): a missing file is a
    failure for a top-ten harness and a report for any other, and a top-ten harness without
    install paths yet is a report. Also returns what was checked, as (harness, surface,
    scope) triples. The repo is never written to: the installers run from a
    copy of the House inside SANDBOX, reading a copy of the registry. PREPARE, if given, is
    called with the copy's root before anything runs (tests use it)."""
    reg = registry or load()
    sandbox = Path(sandbox)
    house = sandbox / "house"
    if house.exists():
        shutil.rmtree(house)
    skip = shutil.ignore_patterns("__pycache__", ".DS_Store")
    for hive in ("skills-hive", "rules-hive", "agents-hive"):
        shutil.copytree(ROOT / "hives" / hive, house / "hives" / hive, ignore=skip)
    (house / "scripts").mkdir(parents=True)
    shutil.copy2(Path(__file__), house / "scripts" / "harnesses.py")
    (house / "harnesses.json").write_text(dumps(reg))
    if prepare:
        prepare(house)

    failures, reports, checked = [], [], []
    for h in reg["harnesses"]:
        held = h["tier"] == "top-ten" and h["category"] == "pro-code"
        if h["tier"] == "top-ten" and h["category"] != "pro-code":
            continue  # low-code harnesses are reached over the wire, not installed into
        if not h["surfaces"]:
            if held:
                reports.append(f"{h['id']}: no install paths yet")
            continue
        home, proj = sandbox / "home" / h["id"], sandbox / "proj" / h["id"]
        for d in (home, proj):
            if d.exists():
                shutil.rmtree(d)
            d.mkdir(parents=True)
        env = dict(os.environ, HOME=str(home))
        skills_hive = house / "hives" / "skills-hive"

        def expect(surface_name, scope, cmd, where):
            result = subprocess.run(cmd, env=env, capture_output=True, text=True)
            checked.append((h["id"], surface_name, scope))
            if result.returncode == 0 and where.is_file():
                return
            rel = os.path.relpath(where, sandbox)
            why = f"exit {result.returncode}" if result.returncode else "nothing written there"
            msg = f"{h['id']}: {surface_name} ({scope}) didn't land at {rel} ({why})"
            (failures if held else reports).append(msg)

        def under(base, template, fill):
            """A registry path inside the sandbox: ~ is the sandbox home, anything else is
            relative to BASE."""
            p = template.replace("{name}", fill)
            return home / p[2:] if p.startswith("~/") else base / p

        skills = h["surfaces"].get("skills", {})
        script = str(skills_hive / "scripts" / "install.sh")
        if "global" in skills:
            expect("skills", "global", ["bash", script, "--global", "--harness", h["id"], "--skill", SKILL],
                   under(home, skills["global"], "") / SKILL / "SKILL.md")
        if "project" in skills:
            expect("skills", "project", ["bash", script, "--harness", h["id"], "--skill", SKILL],
                   skills_hive / skills["project"] / SKILL / "SKILL.md")
            shutil.rmtree(skills_hive / skills["project"].split("/")[0], ignore_errors=True)

        rules = h["surfaces"].get("rules", {})
        script = str(house / "hives" / "rules-hive" / "scripts" / "install.sh")
        if "project" in rules:
            expect("rules", "project", ["bash", script, "--harness", h["id"], "--dir", str(proj)],
                   under(proj, rules["project"], RULESET))
        if "global" in rules:
            expect("rules", "global", ["bash", script, "--global", "--harness", h["id"]],
                   under(home, rules["global"], RULESET))

        agents = h["surfaces"].get("agents", {})
        if agents:
            target = surface(agents["fallback"], "agents", reg) if "fallback" in agents else agents
            script = str(house / "hives" / "agents-hive" / "scripts" / "install.py")
            expect("agents", "project", [sys.executable, "-B", script, "--harness", h["id"], "--agent", AGENT,
                                         "--dir", str(proj)],
                   under(proj, target["project"], AGENT))
    return failures, reports, checked


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    cmd, args = argv[0], argv[1:]
    opts = {}
    rest = []
    while args:
        a = args.pop(0)
        if a in ("--name", "--surface", "--category") and args:
            opts[a[2:]] = args.pop(0)
        else:
            rest.append(a)

    if cmd == "path" and len(rest) == 3:
        name, scope, harness_id = rest
        if name not in SURFACES or scope not in SCOPES:
            print(f"usage: harnesses.py path {{{','.join(SURFACES)}}} {{{','.join(SCOPES)}}} HARNESS",
                  file=sys.stderr)
            return 2
        p = path(harness_id, name, scope, opts.get("name"))
        if p is None:
            return 1
        print(p)
        return 0
    if cmd == "list" and not rest:
        for h in harnesses(surface=opts.get("surface"), category=opts.get("category")):
            print(h["id"])
        return 0
    if cmd == "matrix" and not rest:
        MATRIX.write_text(render_matrix())
        GUIDES.write_text(render_guides())
        print(f"wrote {MATRIX.relative_to(ROOT)} and {GUIDES.relative_to(ROOT)}")
        return 0
    if cmd == "conformance" and len(rest) == 1:
        failures, reports, checked = conformance(rest[0])
        for f in failures:
            print(f"FAIL  {f}")
        for r in reports:
            print(f"note  {r}")
        if failures:
            return 1
        print(f"OK  {len(checked)} installs across {len({c[0] for c in checked})} harnesses landed "
              f"where the registry says")
        return 0
    if cmd == "check" and not rest:
        problems = check()
        for p in problems:
            print(f"FAIL  {p}")
        if problems:
            return 1
        print(f"OK  {REGISTRY.name}, its matrix, the guides index and the adapters/ trees agree")
        return 0
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
