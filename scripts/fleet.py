#!/usr/bin/env python3
"""Draw the skills-hive fleet SVG assets from harnesses.json.

The pro-code ten is ranked in harnesses.json. Ranks 1-6 occupy the inner ring,
clockwise from the top left. Ranks 7-10 occupy the four corners. Cline,
OpenCode and Goose are drawn with dashed cells because the registry identifies
them as free and open source.

Usage:
  python3 scripts/fleet.py           # rewrite the fleet SVG assets
  python3 scripts/fleet.py --check   # fail if they are out of date (what CI runs)
"""
import json
import math
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "harnesses.json"
FLEET = ROOT / "hives" / "skills-hive" / "assets" / "skills-hive-fleet.svg"
LABELED = ROOT / "hives" / "skills-hive" / "assets" / "variants" / "skills-hive-icon-labeled.svg"
REL_FLEET = FLEET.relative_to(ROOT)
REL_LABELED = LABELED.relative_to(ROOT)

INK, HONEY, CREAM, PAPER, BORDER, BROWN = (
    "#17140F", "#F2A81D", "#F7EFDD", "#FBF6EA", "#EADFC6", "#7A6B4F",
)
FONT = "'Poppins','Helvetica Neue',Arial,sans-serif"

# The registry does not yet have a machine-readable license field. Keep this
# explicit decision here until the registry gains one.
FREE_OPEN_SOURCE = {"cline", "opencode", "goose"}

INNER = [
    (202.75, 145.5),
    (277.25, 145.5),
    (314.5, 210),
    (277.25, 274.5),
    (202.75, 274.5),
    (165.5, 210),
]
CORNERS = [
    (165.5, 81),
    (314.5, 81),
    (165.5, 339),
    (314.5, 339),
]


def load_top_ten():
    data = json.loads(REGISTRY.read_text())
    found = [
        h for h in data["harnesses"]
        if h["category"] == "pro-code" and h["tier"] == "top-ten" and h["rank"] is not None
    ]
    if len(found) != 10:
        raise ValueError(f"expected 10 pro-code top-ten harnesses, found {len(found)}")
    found.sort(key=lambda h: h["rank"])
    if [h["rank"] for h in found] != list(range(1, 11)):
        raise ValueError("pro-code top-ten ranks must be 1 through 10")
    return found


def name_lines(name):
    forced = {
        "Claude Code": ("Claude", "Code"),
        "GitHub Copilot": ("GitHub", "Copilot"),
        "Gemini CLI": ("Gemini", "CLI"),
        "Gemini CLI and Antigravity": ("Gemini", "CLI / Antigravity"),
        "Devin Desktop": ("Devin", "Desktop"),
    }
    if name in forced:
        return forced[name]
    words = name.split()
    if len(words) == 1:
        return (name,)
    if len(name) <= 12:
        return (" ".join(words[:1]), " ".join(words[1:]))
    return (" ".join(words[:-1]), words[-1])


def hexagon(cx, cy, fill=CREAM, dashed=False):
    points = " ".join(
        f"{40 * math.cos(math.radians(a)):.1f},"
        f"{40 * math.sin(math.radians(a)):.1f}"
        for a in range(30, 390, 60)
    )
    dash = ' stroke-dasharray="7 5"' if dashed else ""
    return (
        f'    <polygon transform="translate({cx:g},{cy:g})" '
        f'points="{points}" fill="{fill}" stroke="{INK}" stroke-width="4.5" '
        f'stroke-linejoin="round"{dash}/>'
    )


def center_bee(x, y, size=1.0):
    tx = x - 125 * size
    ty = y - 130 * size
    return f"""  <g transform="translate({tx:g},{ty:g}) scale({size:g})">
    <ellipse cx="116" cy="120" rx="9" ry="5.4" fill="{CREAM}" opacity="0.92" transform="rotate(-28 116 120)"/>
    <ellipse cx="134" cy="120" rx="9" ry="5.4" fill="{CREAM}" opacity="0.92" transform="rotate(28 134 120)"/>
    <rect x="118.5" y="117" width="13" height="27" rx="6.5" fill="{HONEY}"/>
    <rect x="118.5" y="124.5" width="13" height="3" rx="1" fill="{INK}"/>
    <rect x="118.5" y="132.5" width="13" height="3" rx="1" fill="{INK}"/>
    <circle cx="125" cy="115" r="5.2" fill="{INK}"/>
    <path d="M118,109 L120.5,104 L123,108.5 L125,103 L127,108.5 L129.5,104 L132,109 Z" fill="{HONEY}"/>
    <circle cx="120.5" cy="104" r="1.2" fill="{HONEY}"/><circle cx="125" cy="103" r="1.3" fill="{HONEY}"/><circle cx="129.5" cy="104" r="1.2" fill="{HONEY}"/>
  </g>"""


def draw_fleet(harnesses):
    positions = INNER + [CORNERS[0], CORNERS[1], CORNERS[2], CORNERS[3]]
    cells = []
    labels = []
    desc_names = ", ".join(h["name"] for h in harnesses)
    for h, (cx, cy) in zip(harnesses, positions):
        cells.append(hexagon(cx, cy, dashed=h["id"] in FREE_OPEN_SOURCE))
        lines = name_lines(h["name"])
        if len(lines) == 1:
            labels.append(f'<text x="{cx:g}" y="{cy - 3:g}" font-size="12.5">{lines[0]}</text>')
        else:
            labels.append(
                f'<text x="{cx:g}" y="{cy - 7:g}" font-size="11">{lines[0]}</text>'
                f'<text x="{cx:g}" y="{cy + 5:g}" font-size="11">{lines[1]}</text>'
            )

    names = [h["name"] for h in harnesses]
    aria = (
        "Barry the king bee at the center of a honeycomb, surrounded by the ten pro-code "
        f"harnesses in rank order: {desc_names}."
    )
    return f"""<svg viewBox="118 24 300 398" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{aria}">
  <title>skills-hive — the fleet</title>
  <desc>Ranks 1-6 in the ring around Barry, clockwise from the top left: {', '.join(names[:6])}; ranks 7-10 in the corners: {', '.join(names[6:])}. Cline, OpenCode and Goose are free and open source and have dashed cells.</desc>

  <rect x="121" y="27" width="294" height="392" rx="24" fill="{PAPER}" stroke="{BORDER}" stroke-width="2.5"/>

  <g fill="{CREAM}" stroke="{INK}" stroke-width="4.5" stroke-linejoin="round">
{chr(10).join(cells)}
  </g>

  <polygon transform="translate(240,210)" points="34.64,20 0,40 -34.64,20 -34.64,-20 0,-40 34.64,-20"
           fill="{INK}" stroke="{INK}" stroke-width="4.5" stroke-linejoin="round"/>

  <g font-family="{FONT}" font-weight="700" fill="{INK}" text-anchor="middle">
{chr(10).join('    ' + label for label in labels)}
  </g>

{center_bee(240, 210)}
  <text x="240" y="243" font-family="{FONT}" font-size="10" font-weight="700" letter-spacing="1.5" fill="{CREAM}" text-anchor="middle">BARRY</text>

  <text x="266" y="392" font-family="{FONT}" font-size="13" font-weight="800" letter-spacing="1" fill="{INK}" text-anchor="middle">skills·hive — the fleet</text>
  <text x="266" y="408" font-family="{FONT}" font-size="9.5" font-weight="500" fill="{BROWN}" text-anchor="middle">the pro-code ten, by rank · dashed = free and open source</text>
</svg>
"""


def draw_labeled(harnesses):
    positions = [(87.75, 60.5), (162.25, 60.5), (199.5, 125), (162.25, 189.5), (87.75, 189.5), (50.5, 125)]
    cells = []
    labels = []
    for h, (cx, cy) in zip(harnesses[:6], positions):
        cells.append(hexagon(cx, cy, dashed=h["id"] in FREE_OPEN_SOURCE).replace("4.5", "4.5"))
        lines = name_lines(h["name"])
        if len(lines) == 1:
            labels.append(f'<text x="{cx:g}" y="{cy - 1:g}" font-size="11.5">{lines[0]}</text>')
        else:
            labels.append(
                f'<text x="{cx:g}" y="{cy - 7:g}" font-size="10.5">{lines[0]}</text>'
                f'<text x="{cx:g}" y="{cy + 4:g}" font-size="10.5">{lines[1]}</text>'
            )

    names = ", ".join(h["name"] for h in harnesses[:6])
    return f"""<svg viewBox="0 0 250 250" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="skills-hive — labeled harness fleet">
  <title>skills-hive — Barry orchestrating labeled harness cells</title>
  <desc>Barry the king bee in the center of a honeycomb, ringed by the first six of the pro-code ten in harnesses.json's rank order, clockwise from the top left: {names}.</desc>

  <g fill="{CREAM}" stroke="{INK}" stroke-width="4.5" stroke-linejoin="round">
{chr(10).join(cells)}
  </g>

  <g font-family="{FONT}" font-weight="700" fill="{INK}" text-anchor="middle">
{chr(10).join('    ' + label for label in labels)}
  </g>

  <polygon transform="translate(125,125)" points="34.64,20 0,40 -34.64,20 -34.64,-20 0,-40 34.64,-20"
           fill="{INK}" stroke="{INK}" stroke-width="4.5" stroke-linejoin="round"/>

{center_bee(125, 125, 0.92).replace('<ellipse cx="116"', '<ellipse cx="116"', 1)}
  <text x="125" y="156" font-family="{FONT}" font-size="10" font-weight="700" letter-spacing="1.5" fill="{CREAM}" text-anchor="middle">BARRY</text>
</svg>
"""


def main(argv):
    check = argv[1:] == ["--check"]
    if argv[1:] and not check:
        print(__doc__.split("Usage:")[1].rstrip(), file=sys.stderr)
        return 2
    try:
        harnesses = load_top_ten()
        fleet = draw_fleet(harnesses)
        labeled = draw_labeled(harnesses)
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"FAIL  harnesses.json: {exc}", file=sys.stderr)
        return 1

    outputs = ((FLEET, REL_FLEET, fleet), (LABELED, REL_LABELED, labeled))
    if check:
        failed = False
        for path, rel, svg in outputs:
            if not path.exists() or path.read_text() != svg:
                print(f"FAIL  {rel}: out of date; run python3 scripts/fleet.py and commit it")
                failed = True
            else:
                print(f"OK  {rel} is current")
        return 1 if failed else 0

    for path, rel, svg in outputs:
        path.write_text(svg)
        print(f"wrote {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
