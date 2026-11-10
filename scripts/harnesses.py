#!/usr/bin/env python3
"""Read harnesses.json, the harness registry, for every installer and page.

The registry is the only place a harness, its category and tier, its install paths, and
its capability and price row are written down (docs/harness-ecosystem.md). Python
installers import this module; shell installers call it. `matrix` writes the readable
table, docs/harness-matrix.md. `check` is what CI runs: the registry is well formed, every
claim in a row names its source and the date it was checked, the table is current, each
hive's adapters/ matches the registry, and each README that draws an adapters/ tree names
every adapter.

Standard library only.

Usage:
  python3 scripts/harnesses.py path SURFACE SCOPE HARNESS [--name NAME]
      print where HARNESS reads SURFACE (skills, rules, agents) at SCOPE (global or
      project), with ~ expanded and {name} filled in; exit 1 if it has none
  python3 scripts/harnesses.py list [--surface SURFACE] [--category CATEGORY]
      print harness ids, one per line, in registry order
  python3 scripts/harnesses.py matrix
      rewrite docs/harness-matrix.md from the registry
  python3 scripts/harnesses.py check
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "harnesses.json"
MATRIX = ROOT / "docs" / "harness-matrix.md"
SURFACES = ("skills", "rules", "agents")
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


def effective(h, registry):
    """[(model name, input, cached, output)] in dollars per million tokens, as strings, or a
    sentence when no rate can be derived."""
    t = h["cost"]["tokens"]
    if t["basis"] == "not-published":
        return "Not published"
    if t["basis"] == "own-key":
        return "The model's list price, on your own key" + (f"; {t['note']}" if t.get("note") else "")
    fee = t.get("fee", 0)
    rows = []
    for mid in t["models"]:
        m = registry["models"][mid]
        # Unknown, not "not published": whether a fee applies to cached tokens, or a cached
        # rate nobody has recorded yet, is a gap in the row, not a claim about the vendor.
        cached = "unknown" if m["cached"] is None or fee else money(m["cached"])
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
                fee = c["tokens"].get("fee")
                note = f" ({c['tokens']['fee_applies']}, list + {money(fee)})" if fee else ""
                cell = "<br>".join(f"{n}: {i} · {ca} · {o}{note}" for n, i, ca, o in eff)
            out.append(f"| {h['name']} | {c['unit']} | {cell} | {c['checked']} |")
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


def adapters(registry=None):
    """Top-level adapter directory -> display name, in registry order."""
    return {h["adapter"]: h["name"] for h in (registry or load())["harnesses"]
            if h.get("adapter") and "/" not in h["adapter"]}


def check(registry=None):
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
            if t.get("basis") == "list" and not t.get("models"):
                problems.append(f"{where}: a list-price basis names the models it's quoted for")
        if not isinstance(h.get("verified"), bool):
            problems.append(f"{where}: its row says whether it's verified (true or false)")

    if not problems:
        if not MATRIX.is_file() or MATRIX.read_text() != render_matrix(reg):
            problems.append(f"{MATRIX.relative_to(ROOT)} is out of date: run python3 scripts/harnesses.py matrix")

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
        print(f"wrote {MATRIX.relative_to(ROOT)}")
        return 0
    if cmd == "check" and not rest:
        problems = check()
        for p in problems:
            print(f"FAIL  {p}")
        if problems:
            return 1
        print(f"OK  {REGISTRY.name}, its matrix and the adapters/ trees agree")
        return 0
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
