#!/usr/bin/env python3
"""Draw assets/architecture.svg, the House of Hives architecture diagram, from the repo.

What the diagram can read from the repo, it reads: the hives under hives/, the harnesses
under hives/*/adapters/, the Azure resources, app names, budget and eval schedule in
hives/agents-hive/deploy/azure/main.bicep, and the version in .release-please-manifest.json.
The rest (what each box says) is written here. A hive, harness or Azure resource type this
script doesn't know is an error, so the diagram can't silently fall behind the repo: name
it here and draw it.

The Azure icons are Microsoft's, vendored unmodified in assets/azure-icons/ (see its README).
release-please rewrites the version on the line marked x-release-please-version in each
release PR, so the diagram at a tag names that tag's version.

Standard library only.

Usage:
  python3 scripts/architecture.py           # rewrite assets/architecture.svg
  python3 scripts/architecture.py --check   # fail if it's out of date (what CI runs)
"""
import base64
import json
import math
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

import harnesses as harness_registry  # scripts/harnesses.py, beside this script

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "architecture.svg"
REL = OUT.relative_to(ROOT)
ICONS = ROOT / "assets" / "azure-icons"
BICEP = ROOT / "hives" / "agents-hive" / "deploy" / "azure" / "main.bicep"

INK, HONEY, AMBER, BROWN = "#17140F", "#F2A81D", "#B9791A", "#7A6B4F"
LIGHT, CREAM, PAPER, BORDER, BODY = "#F6DCA0", "#F7EFDD", "#FBF6EA", "#EADFC6", "#4A4030"
AZURE_BLUE, AZURE_WASH = "#0078D4", "#F4F8FC"
FONT = "'Poppins','Helvetica Neue',Arial,sans-serif"
W, H = 1720, 1900

# The six artifact hives, in the order they're drawn, and the two that compose them.
ARTIFACT_HIVES = [
    ("rules-hive", "instructions · AGENTS.md", ["AGENTS.md / CLAUDE.md, the Queen Bee's", "Charter, approval policy"]),
    ("agents-hive", "actors · personas", ["Personas rendered per harness,", "contracts, cards, passports"]),
    ("skills-hive", "capabilities · SKILL.md", ["Portable SKILL.md files,", "incl. barry and patricia"]),
    ("mcp-hive", "tools · MCP", ["MCP server configs: filesystem,", "git, fetch, huggingface, patricia"]),
    ("workflows-hive", "orchestration · engine", ["Durable, resumable plans,", "designed around MCP Tasks"]),
    ("knowledge-hive", "state · STATE.md", ["Memory, results and usage", "ledgers, audit log"]),
]
COMPOSITION_HIVES = ["plugins-hive", "projects-hive"]

# Each adapter directory under hives/*/adapters/ and the harness's name, in drawing order:
# the order of harnesses.json, the harness registry.
HARNESSES = harness_registry.adapters()

# Each resource type main.bicep declares and the tile that shows it; None where its parent's
# tile covers it (role assignments are drawn as what they let each identity do).
AZURE_TYPES = {
    "Microsoft.ManagedIdentity/userAssignedIdentities": "identities",
    "Microsoft.ContainerRegistry/registries": "registry",
    "Microsoft.Authorization/roleAssignments": None,
    "Microsoft.CognitiveServices/accounts": "foundry",
    "Microsoft.CognitiveServices/accounts/deployments": None,
    "Microsoft.Storage/storageAccounts": "storage",
    "Microsoft.Storage/storageAccounts/fileServices": None,
    "Microsoft.Storage/storageAccounts/fileServices/shares": "files",
    "Microsoft.Storage/storageAccounts/blobServices": None,
    "Microsoft.Storage/storageAccounts/blobServices/containers": "storage",
    "Microsoft.OperationalInsights/workspaces": "logs",
    "Microsoft.App/managedEnvironments": "environment",
    "Microsoft.App/managedEnvironments/storages": None,
    "Microsoft.App/containerApps": "apps",
    "Microsoft.App/jobs": "apps",
    "Microsoft.Consumption/budgets": "budget",
}

# What each Container App or job in main.bicep does, by its resource's symbolic name.
APPS = {
    "app": ["Patricia over A2A and MCP,", "scales 0 to 1"],
    "barryApp": ["Hosted Barry over A2A,", "scales 0 to 1"],
    "verifyApp": ["The MCP server Barry is checked", "against; every call pauses for a person"],
    "evalJob": ["The trust evaluation,", "{schedule}"],
}

ICON_FILES = {
    "app": "02884-icon-service-Worker-Container-App.svg",
    "environment": "02989-icon-service-Container-Apps-Environments.svg",
    "registry": "10105-icon-service-Container-Registries.svg",
    "foundry": "03513-icon-service-AI-Studio.svg",
    "identities": "10227-icon-service-Entra-Managed-Identities.svg",
    "appreg": "10232-icon-service-App-Registrations.svg",
    "storage": "10086-icon-service-Storage-Accounts.svg",
    "files": "10400-icon-service-Azure-Fileshares.svg",
    "logs": "00009-icon-service-Log-Analytics-Workspaces.svg",
    "budget": "10793-icon-service-Cost-Budgets.svg",
}

ICON_SIZE = 48

DAYS = ["Sundays", "Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays"]


class Drift(Exception):
    """The repo has something the diagram doesn't account for."""


# ---- Facts from the repo ---------------------------------------------------------------

def changed(where, found, known):
    new, gone = sorted(found - known), sorted(known - found)
    if new or gone:
        raise Drift(f"{where} changed: " + "; ".join(
            s for s in (f"new {', '.join(new)}" if new else "", f"gone {', '.join(gone)}" if gone else "") if s))


def hives():
    changed("hives/", {p.name for p in (ROOT / "hives").iterdir() if p.is_dir()},
            {h for h, _, _ in ARTIFACT_HIVES} | set(COMPOSITION_HIVES))


def harnesses():
    changed("the harnesses under hives/*/adapters/",
            {p.name for p in (ROOT / "hives").glob("*/adapters/*") if p.is_dir()}, set(HARNESSES))
    return list(HARNESSES.values())


def bicep():
    """The resource types, the Container Apps and jobs by name, the budget and the schedule."""
    src = BICEP.read_text()
    params = dict(re.findall(r"^param (\w+) \w+ = '?([^'\n]*)'?$", src, re.M))
    variables = dict(re.findall(r"^var (\w+) = '([^'\n]*)'$", src, re.M))

    def resolve(symbol, expr):
        """A name that's a quoted string or a var, with ${...} filled from params and vars."""
        if not re.fullmatch(r"\w+|'[^']*'", expr) or (expr[0] != "'" and expr not in variables):
            raise Drift(f"main.bicep's {symbol} is named {expr}, which the diagram can't read; teach resolve() to")
        value = re.sub(r"\$\{(\w+)\}", lambda m: params.get(m.group(1), variables.get(m.group(1), m.group(0))),
                       variables.get(expr, expr.strip("'")))
        if "${" in value:
            raise Drift(f"main.bicep's {symbol} is named {value}, which the diagram can't fill in")
        return value

    # The drift check reads top-level resources; a module or nested resource would slip past it.
    other = re.search(r"^(module \w+|[ \t]+resource \w+)", src, re.M)
    if other:
        raise Drift(f"main.bicep has {other.group(1).strip()}, which the diagram's check doesn't read; teach bicep() to")
    apps = []
    for m in re.finditer(r"^resource (\w+) '([\w./]+)@", src, re.M):
        symbol, kind = m.groups()
        if kind not in AZURE_TYPES:
            raise Drift(f"main.bicep declares {kind} ({symbol}), which the diagram doesn't draw")
        if AZURE_TYPES[kind] == "apps":
            if symbol not in APPS:
                raise Drift(f"main.bicep's {kind} {symbol} has no tile in the diagram")
            block = src[m.end():src.find("\n}", m.end())]
            name = re.search(r"^  name: (.*?)\s*$", block, re.M)
            if not name:
                raise Drift(f"main.bicep's {symbol} has no name: line the diagram can read")
            apps.append((symbol, resolve(symbol, name.group(1)), kind == "Microsoft.App/jobs"))
    missing = set(APPS) - {s for s, _, _ in apps}
    if missing:
        raise Drift(f"the diagram draws {', '.join(sorted(missing))}, which main.bicep no longer declares")
    for key in ("budgetUsd", "evalSchedule"):
        if key not in params:
            raise Drift(f"main.bicep's {key} has no default the diagram can read")
    return apps, params["budgetUsd"], schedule(params["evalSchedule"])


def schedule(cron):
    m = re.fullmatch(r"(\d+) (\d+) \* \* ([0-6])", cron)
    if not m:
        raise Drift(f"the eval schedule {cron!r} isn't a weekly 'M H * * D'; teach schedule() to say it")
    minute, hour, day = (int(g) for g in m.groups())
    return f"{DAYS[day]} {hour:02d}:{minute:02d} UTC"


def version():
    return json.loads((ROOT / ".release-please-manifest.json").read_text())["."]


# ---- Drawing ---------------------------------------------------------------------------

class Svg:
    def __init__(self):
        self.out = []

    def add(self, s):
        self.out.append(s)

    def text(self, x, y, s, size=13, weight=400, fill=INK, anchor="middle"):
        self.add(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
                 f'text-anchor="{anchor}">{escape(s)}</text>')

    def box(self, x, y, w, h, fill="#FFFFFF", stroke=INK, sw=2.5, rx=14, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" '
                 f'stroke="{stroke}" stroke-width="{sw}"{d}/>')

    def card(self, x, y, w, h, title, lines, tag=None, fill="#FFFFFF", stroke=INK):
        self.box(x, y, w, h, fill, stroke)
        rows = 1 + (1 if tag else 0) + len(lines)
        ty, cx = y + h / 2 - (rows - 1) * 9 + 4, x + w / 2
        self.text(cx, ty, title, 16, 700)
        if tag:
            ty += 19
            self.text(cx, ty, tag, 12, 600, AMBER)
        for line in lines:
            ty += 18
            self.text(cx, ty, line, 12, 400, BODY)

    def pill(self, x, y, s, fill, color, size=15, pad=16):
        w = len(s) * size * 0.5 + pad * 2
        self.box(x, y, w, size + 18, fill, fill, 0, rx=(size + 18) / 2)
        self.text(x + pad, y + size + 5, s, size, 600, color, "start")

    def hexagon(self, cx, cy, r, fill, stroke, sw=3):
        pts = " ".join(f"{cx + r * math.cos(math.radians(a)):.1f},{cy + r * math.sin(math.radians(a)):.1f}"
                       for a in range(30, 390, 60))
        self.add(f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" stroke-linejoin="round"/>')

    def arrow(self, points, label=None, at=None, color=INK, anchor="middle"):
        pts = " ".join(f"{x},{y}" for x, y in points)
        self.add(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2.2" '
                 f'marker-end="url(#head-{color[1:]})"/>')
        if label:
            self.text(at[0], at[1], label, 13.5, 500, BROWN, anchor)

    def icons(self):
        """Each icon once, at 48 by 48 (the tiles' size), for icon() to place and scale."""
        for key, file in ICON_FILES.items():
            data = base64.b64encode((ICONS / file).read_bytes()).decode()
            self.add(f'<image id="icon-{key}" width="{ICON_SIZE}" height="{ICON_SIZE}" href="data:image/svg+xml;base64,{data}"/>')

    def icon(self, key, x, y, size):
        self.add(f'<use href="#icon-{key}" transform="translate({x} {y}) scale({size / ICON_SIZE:g})"/>')

    def tile(self, x, y, w, h, key, title, lines, tag=None):
        """An Azure tile: the icon, then the service's full name beside it, as Microsoft asks."""
        self.box(x, y, w, h, "#FFFFFF", BORDER, 2, rx=12)
        self.icon(key, x + 16, y + (h - 48) / 2, 48)
        rows = len(lines) + (1 if tag else 0)
        ty = y + h / 2 - rows * 9 + 1
        self.text(x + 80, ty, title, 14.5, 700, INK, "start")
        if tag:
            ty += 18
            self.text(x + 80, ty, tag, 12, 600, AZURE_BLUE, "start")
        for line in lines:
            ty += 18
            self.text(x + 80, ty, line, 12, 400, BODY, "start")


GITHUB_MARK = (
    "M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94"
    "-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07"
    "-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 "
    "1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54"
    ".73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z")


def draw():
    hives()
    names = harnesses()
    apps, budget, when = bicep()
    s = Svg()
    s.add(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" '
          f'aria-label="werkrbee ai-hive architecture: the House of Hives" font-family="{FONT}">')
    s.add("<!-- Generated by scripts/architecture.py; edit that, not this. -->")
    s.add("<title>werkrbee ai-hive — Architecture (House of Hives)</title>")
    s.add("<desc>Humans set the charter and goals; Patricia governs and Barry executes across the six artifact "
          "hives, which plugins-hive bundles and projects-hive stamps out into products that run on every harness. "
          "An assurance loop wraps the agents, and Patricia and Barry are hosted on Azure from "
          "hives/agents-hive/deploy/azure.</desc>")
    s.add("<defs>")
    for c in (INK, AMBER, BROWN):
        s.add(f'<marker id="head-{c[1:]}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" '
              f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>')
    s.icons()
    s.add("</defs>")
    s.box(6, 6, W - 12, H - 12, PAPER, BORDER, 2.5, rx=28)

    # Header: the hive mark and wordmark; the repo and version on the right.
    s.hexagon(72, 78, 36, INK, INK)
    s.hexagon(72, 78, 22, "none", HONEY, 4)
    s.hexagon(72, 78, 10, HONEY, HONEY, 1)
    s.add(f'<text x="124" y="80" font-size="34" font-weight="800" letter-spacing="-0.5" fill="{INK}">the ai'
          f'<tspan fill="{HONEY}">·hive</tspan></text>')
    s.text(124, 108, "Architecture — the House of Hives", 19, 600, INK, "start")
    s.text(124, 132, "A harness-agnostic factory for AI agent products: build the reusable layers once, "
           "stamp out products from them.", 14, 500, BROWN, "start")
    s.add(f'<path d="{GITHUB_MARK}" fill="{INK}" transform="translate({W - 330},62) scale(1.6)"/>')
    s.text(W - 290, 82, "github.com/werkrbee/ai-hive", 16, 600, INK, "start")
    s.text(W - 290, 104, "werkrbee's House of Hives", 12.5, 500, BROWN, "start")
    # The version stays alone on this line: release-please rewrites it in each release PR.
    s.add(f'<text x="{W - 290}" y="124" font-size="12.5" font-weight="600" fill="{AMBER}" '
          f'text-anchor="start">v{version()}</text><!-- x-release-please-version -->')
    s.add(f'<line x1="40" y1="162" x2="{W - 40}" y2="162" stroke="{BORDER}" stroke-width="2"/>')

    # Humans and the two thrones.
    s.card(430, 186, 400, 84, "Humans", ["Own the house: set goals, approve consequential", "actions, review, roll back"])
    for x, name, role, tag, lines in (
            (110, "Patricia", "Queen Bee", "Governance · rules-hive",
             ["Always-on law every agent inherits;", "reviews and gates actions"]),
            (740, "Barry", "King Bee", "Execution · skills-hive",
             ["Chief of staff: decomposes goals,", "delegates to the fleet, synthesizes"])):
        s.box(x, 330, 410, 104, "#FFFFFF", INK, 3)
        s.hexagon(x + 52, 382, 30, INK, INK)
        s.text(x + 52, 389, name[0], 20, 800, HONEY)
        s.text(x + 96, 368, f"{name}, the {role}", 16, 700, INK, "start")
        s.text(x + 96, 388, tag, 12, 600, AMBER, "start")
        for i, line in enumerate(lines):
            s.text(x + 96, 407 + i * 17, line, 12, 400, BODY, "start")
    s.arrow([(520, 270), (400, 328)], "charter", (432, 300), anchor="end")
    s.arrow([(740, 270), (860, 328)], "goals", (828, 300), anchor="start")
    s.arrow([(522, 382), (736, 382)], "governs", (629, 372))
    s.arrow([(830, 228), (1465, 228), (1465, 318)], "review & approve", (1150, 218), color=AMBER)

    # The six artifact hives.
    s.box(50, 490, 1160, 392, CREAM, HONEY, 2.5, rx=22, dash="12 8")
    s.pill(400, 472, "The six artifact hives · hives/ · one portable artifact each", HONEY, INK)
    for i, (name, tag, lines) in enumerate(ARTIFACT_HIVES):
        s.card(90 + (i % 3) * 370, 530 + (i // 3) * 170, 340, 136, name, lines, tag, fill=LIGHT)
    s.arrow([(260, 434), (260, 528)])
    s.arrow([(1000, 434), (1000, 528)])
    s.arrow([(1210, 686), (1258, 686)], color=AMBER)

    # Composition and products.
    s.arrow([(300, 882), (300, 936)], "bundled into packs", (316, 914), anchor="start")
    s.card(110, 940, 410, 86, "plugins-hive", ["Packs such as werkrbee-core:", "skills + rules + tools + agents in one install"],
           "composition · bundles", stroke=AMBER)
    s.card(740, 940, 410, 86, "projects-hive", ["Scaffolds such as werkrbee-initiative:", "a new project with the pack wired in"],
           "containers · scaffolds", stroke=AMBER)
    s.arrow([(522, 983), (736, 983)], "installed by", (629, 973))
    s.arrow([(860, 1028), (420, 1088)], color=BROWN)
    s.arrow([(945, 1028), (945, 1088)], "stamps out", (960, 1064), color=BROWN, anchor="start")
    s.card(110, 1092, 410, 86, 'lineup — "our Basecamp"',
           ["First real product: pickup-sports RSVP on Airtable", "+ Inkbox; stress-tests the hives"], stroke=BROWN)
    s.card(740, 1092, 410, 86, "singularity",
           ["A game whose React app is one client of a game", "service; follows the House's patterns"], stroke=BROWN)
    s.arrow([(315, 1180), (340, 1236)], color=BROWN)
    s.arrow([(945, 1180), (920, 1236)], "runs on", (946, 1214), color=BROWN, anchor="start")

    # Worker bees: every harness, two lines.
    s.box(50, 1240, 1160, 96, INK, INK, 2.5, rx=16)
    s.text(630, 1278, "Worker bees: every harness", 17, 700, HONEY)
    half = (len(names) + 1) // 2
    s.text(630, 1304, "Installers render each hive into native formats for " + ", ".join(names[:half]) + ",",
           12.5, 400, CREAM)
    s.text(630, 1322, ", ".join(names[half:-1]) + " and " + names[-1], 12.5, 400, CREAM)

    # Assurance loop.
    s.box(1258, 338, 420, 998, "#FFFDF7", AMBER, 2.5, rx=22, dash="12 8")
    s.pill(1270, 320, "Assurance loop (P2.1) · controls grow with the agents", AMBER, "#FFFFFF", 13.5, 14)
    for i, (title, line) in enumerate((
            ("Passport", "What each agent may and may not do"),
            ("Trust evaluation", "Weekly eval that catches drift"),
            ("Audit log", "Hash-chained, tamper-evident record"),
            ("Rollback", "Back to an earlier version or state"),
            ("Human review queue", "Paused runs wait for approval"))):
        s.card(1298, 384 + i * 186, 340, 104, title, [line], stroke=AMBER)

    # Azure: an adapter, so it sits in its own frame.
    s.box(50, 1404, W - 100, 446, "#FFFFFF", BROWN, 2.5, rx=22, dash="12 8")
    s.pill(74, 1386, "Hosted on Azure · hives/agents-hive/deploy/azure — an adapter; the hives don't depend on it",
           INK, CREAM)
    s.text(W - 74, 1438, "Microsoft Azure architecture icons, unmodified", 11.5, 500, BROWN, "end")
    s.box(80, 1456, 720, 360, AZURE_WASH, AZURE_BLUE, 2, rx=16)
    s.icon("environment", 100, 1470, 34)
    s.text(146, 1486, "Container Apps environment", 15, 700, INK, "start")
    s.text(146, 1504, "Scale-to-zero apps on one shared environment", 12, 400, BODY, "start")
    for i, (symbol, name, job) in enumerate(apps):
        lines = [line.format(schedule=when) for line in APPS[symbol]]
        s.tile(100 + (i % 2) * 350, 1528 + (i // 2) * 140, 330, 124, "app", name, lines,
               "Container Apps job" if job else "Container App")
    for i, (key, title, lines) in enumerate((
            ("registry", "Azure Container Registry", ["The hive-a2a image every app runs"]),
            ("foundry", "Microsoft Foundry", ["Models via managed identity, no API keys"]),
            ("identities", "Microsoft Entra Managed Identities", ["One each for Patricia, Barry", "and barry-verify"]),
            ("appreg", "Entra ID app registrations", ["Only werkrbee products may call"]),
            ("storage", "Storage account (audit)", ["Immutable blob; each agent appends", "only to its own copy"]),
            ("files", "Azure Files", ["State shares for Patricia and Barry"]),
            ("logs", "Log Analytics workspace", ["Logs from every app and the job"]),
            ("budget", "Cost Management budget", [f"${budget} a month; it alerts, it never", "stops anything"]))):
        s.tile(830 + (i % 2) * 415, 1456 + (i // 2) * 92, 395, 80, key, title, lines)

    s.add("</svg>")
    return "\n".join(s.out) + "\n"


def main(argv):
    check = argv[1:] == ["--check"]
    if argv[1:] and not check:
        print(__doc__.split("Usage:")[1].rstrip(), file=sys.stderr)
        return 2
    try:
        svg = draw()
    except Drift as e:
        print(f"FAIL  {REL}: {e}")
        return 1
    if check:
        if not OUT.exists() or OUT.read_text() != svg:
            print(f"FAIL  {REL}: out of date; run python3 scripts/architecture.py and commit it")
            return 1
        print(f"OK  {REL} is current")
        return 0
    OUT.write_text(svg)
    print(f"wrote {REL}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
