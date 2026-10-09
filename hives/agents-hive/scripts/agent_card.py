#!/usr/bin/env python3
"""Render and validate A2A Agent Cards (A2A v1.0, specification/a2a.proto) for the House.

`cards/<persona>/card.json` holds what only the persona can say about itself: name,
description, version, provider, links, capabilities and default media types. Two parts
of an Agent Card come from elsewhere, so the source must not contain them:

  skills               one per execution contract the persona fulfils (contracts/), so a
                       card can't drift from the contracts
  supportedInterfaces  the endpoint, which only exists once someone serves the agent

Rendering adds both. Publish the result at https://<host>/.well-known/agent-card.json.
`--check` renders every card against a stand-in endpoint and validates it, which is what
CI runs.

Standard library only.

Usage:
  python3 scripts/agent_card.py --check
  python3 scripts/agent_card.py patricia --url https://agents.example.org/a2a/patricia
  python3 scripts/agent_card.py barry --url https://... --binding HTTP+JSON
"""
import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

HIVE = Path(__file__).resolve().parent.parent
REPO_ROOT = HIVE.parent.parent
PROTOCOL_VERSION = "1.0"
CHECK_URL = "https://a2a.invalid/{persona}"

# AgentCard and its messages in a2a.proto, by their JSON (camelCase) names.
CARD_REQUIRED = {"name", "description", "supportedInterfaces", "version", "capabilities",
                 "defaultInputModes", "defaultOutputModes", "skills"}
CARD_OPTIONAL = {"provider", "documentationUrl", "securitySchemes", "securityRequirements",
                 "signatures", "iconUrl"}
DERIVED = {"skills", "supportedInterfaces"}
INTERFACE = {"url", "protocolBinding", "tenant", "protocolVersion"}
CAPABILITIES = {"streaming", "pushNotifications", "extensions", "extendedAgentCard"}
EXTENSION = {"uri", "description", "required", "params"}
SKILL_REQUIRED = {"id", "name", "description", "tags"}
SKILL_OPTIONAL = {"examples", "inputModes", "outputModes", "securityRequirements"}
SIGNATURE = {"protected", "signature", "header"}
MEDIA_TYPE = re.compile(r"^[\w.+-]+/[\w.+-]+$")


def require_secure(url):
    """HTTPS only, except plain HTTP to localhost for development."""
    parsed = urlparse(url)
    local = parsed.hostname in ("localhost", "127.0.0.1", "::1")
    return parsed.scheme == "https" and bool(parsed.hostname) or (parsed.scheme == "http" and local)


# Where a persona can live; a contract's fulfilledBy must name one of these exactly.
PERSONA_DIRS = ("hives/skills-hive/skills/{p}", "hives/agents-hive/agents/{p}")


class CardError(Exception):
    pass


def contracts_for(persona):
    """The contracts whose fulfilledBy names this persona's skill or agent.

    A malformed contract raises CardError; validate_contracts.py reports the detail.
    """
    paths = {d.format(p=persona) for d in PERSONA_DIRS}
    found = []
    for path in sorted((HIVE / "contracts").glob("*/contract.json")):
        rel = path.relative_to(REPO_ROOT)
        try:
            c = json.loads(path.read_text())
        except ValueError:
            raise CardError(f"{rel} is not valid JSON; run validate_contracts.py")
        impls = c.get("fulfilledBy") if isinstance(c, dict) else None
        if not isinstance(impls, list):
            raise CardError(f"{rel} has no fulfilledBy list; run validate_contracts.py")
        if not any(isinstance(i, dict) and i.get("path") in paths for i in impls):
            continue
        cap, desc, version = c.get("capability"), c.get("description"), c.get("version")
        if not (isinstance(cap, str) and cap and isinstance(desc, str) and desc
                and isinstance(version, int) and not isinstance(version, bool)):
            raise CardError(f"{rel} needs capability, description and version; run validate_contracts.py")
        found.append((path, c))
    return found


def skill(path, contract):
    cap = contract["capability"]
    rel = path.relative_to(REPO_ROOT)
    return {
        "id": cap,
        "name": cap.replace("-", " ").capitalize(),
        "description": f"{contract['description']} Inputs and output are defined by the "
                       f"execution contract {rel} (version {contract['version']}).",
        "tags": cap.split("-"),
        "inputModes": ["application/json"],
        "outputModes": ["application/json"],
    }


def render(persona, url, binding="JSONRPC"):
    source = json.loads((HIVE / "cards" / persona / "card.json").read_text())
    card = dict(source)
    card["supportedInterfaces"] = [{"url": url, "protocolBinding": binding,
                                    "protocolVersion": PROTOCOL_VERSION}]
    card["skills"] = [skill(p, c) for p, c in contracts_for(persona)]
    return card


def strings(value):
    return isinstance(value, list) and all(isinstance(x, str) and x for x in value)


def check_fields(obj, allowed, where, err):
    for key in sorted(set(obj) - allowed):
        hint = " (A2A JSON uses camelCase)" if "_" in key else ""
        err(f"{where}: unknown field '{key}'{hint}")


def validate_source(source):
    """Problems with a card.json before rendering."""
    if not isinstance(source, dict):
        return ["card.json must be a JSON object"]
    errors = []
    for key in sorted(DERIVED & set(source)):
        errors.append(f"'{key}' is added when the card is rendered; remove it from card.json")
    check_fields(source, CARD_REQUIRED | CARD_OPTIONAL, "card", errors.append)
    return errors


def validate(card):
    """Check a rendered card against AgentCard in a2a.proto. Returns a list of problems.

    URLs must be https (plain http only for localhost). That is house policy: the spec
    requires HTTPS for production endpoints but not for documentation or icon links.
    """
    if not isinstance(card, dict):
        return ["card is not a JSON object"]
    errors = []
    err = errors.append
    check_fields(card, CARD_REQUIRED | CARD_OPTIONAL, "card", err)
    for key in sorted(CARD_REQUIRED - set(card)):
        err(f"missing required '{key}'")
    for key in ("name", "description", "version"):
        if key in card and (not isinstance(card[key], str) or not card[key]):
            err(f"{key} must be a non-empty string")
    for key in ("documentationUrl", "iconUrl"):
        if key in card and (not isinstance(card[key], str) or not require_secure(card[key])):
            err(f"{key} must be an https URL")

    provider = card.get("provider")
    if provider is not None:
        if not isinstance(provider, dict):
            err("provider must be an object")
        else:
            check_fields(provider, {"url", "organization"}, "provider", err)
            if not isinstance(provider.get("organization"), str) or not provider["organization"]:
                err("provider.organization is required")
            if not isinstance(provider.get("url"), str) or not require_secure(provider["url"]):
                err("provider.url is required and must be https")

    interfaces = card.get("supportedInterfaces", [])
    if not isinstance(interfaces, list) or not interfaces:
        err("supportedInterfaces must list at least one interface")
        interfaces = []
    for i, f in enumerate(interfaces):
        where = f"supportedInterfaces[{i}]"
        if not isinstance(f, dict):
            err(f"{where} must be an object")
            continue
        check_fields(f, INTERFACE, where, err)
        if not isinstance(f.get("url"), str) or not require_secure(f["url"]):
            err(f"{where}.url must be an https URL (http only for localhost)")
        for key in ("protocolBinding", "protocolVersion"):
            if not isinstance(f.get(key), str) or not f[key]:
                err(f"{where}.{key} is required")
        if "tenant" in f and not isinstance(f["tenant"], str):
            err(f"{where}.tenant must be a string")

    caps = card.get("capabilities")
    if "capabilities" in card and not isinstance(caps, dict):
        err("capabilities must be an object")
    elif isinstance(caps, dict):
        check_fields(caps, CAPABILITIES, "capabilities", err)
        for key in ("streaming", "pushNotifications", "extendedAgentCard"):
            if key in caps and not isinstance(caps[key], bool):
                err(f"capabilities.{key} must be true or false")
        exts = caps.get("extensions", [])
        if not isinstance(exts, list):
            err("capabilities.extensions must be a list")
            exts = []
        for j, x in enumerate(exts):
            where = f"capabilities.extensions[{j}]"
            if not isinstance(x, dict) or not isinstance(x.get("uri"), str) or not x["uri"]:
                err(f"{where} needs a uri")
                continue
            check_fields(x, EXTENSION, where, err)

    for key in ("defaultInputModes", "defaultOutputModes"):
        if key in card and (not strings(card[key]) or not card[key]
                            or not all(MEDIA_TYPE.match(m) for m in card[key])):
            err(f"{key} must be a non-empty list of media types")

    skills = card.get("skills", [])
    if not isinstance(skills, list) or not skills:
        err("skills must list at least one skill (does an execution contract name this persona?)")
        skills = []
    ids = []
    for i, s in enumerate(skills):
        where = f"skills[{i}]"
        if not isinstance(s, dict):
            err(f"{where} must be an object")
            continue
        check_fields(s, SKILL_REQUIRED | SKILL_OPTIONAL, where, err)
        for key in ("id", "name", "description"):
            if not isinstance(s.get(key), str) or not s[key]:
                err(f"{where}.{key} is required")
        if not strings(s.get("tags")) or not s["tags"]:
            err(f"{where}.tags must be a non-empty list of strings")
        for key in ("examples", "inputModes", "outputModes"):
            if key in s and not strings(s[key]):
                err(f"{where}.{key} must be a list of strings")
        for key in ("inputModes", "outputModes"):
            if strings(s.get(key)) and not all(MEDIA_TYPE.match(m) for m in s[key]):
                err(f"{where}.{key} must be media types")
        ids.append(s.get("id"))
    for dup in sorted({x for x in ids if isinstance(x, str) and ids.count(x) > 1}):
        err(f"skill id '{dup}' appears more than once")

    if "securitySchemes" in card and not isinstance(card["securitySchemes"], dict):
        err("securitySchemes must be an object")
    if "securityRequirements" in card and not isinstance(card["securityRequirements"], list):
        err("securityRequirements must be a list")
    sigs = card.get("signatures", [])
    if not isinstance(sigs, list):
        err("signatures must be a list")
        sigs = []
    for j, g in enumerate(sigs):
        where = f"signatures[{j}]"
        if not isinstance(g, dict):
            err(f"{where} must be an object")
            continue
        check_fields(g, SIGNATURE, where, err)
        for key in ("protected", "signature"):
            if not isinstance(g.get(key), str) or not g[key]:
                err(f"{where}.{key} is required")
    return errors


def check_all():
    sources = sorted((HIVE / "cards").glob("*/card.json"))
    if not sources:
        print("FAIL  no Agent Cards found under cards/")
        return 1
    fail = 0
    for path in sources:
        rel = path.relative_to(REPO_ROOT)
        persona = path.parent.name
        try:
            source = json.loads(path.read_text())
        except ValueError as e:
            print(f"FAIL  {rel}: not valid JSON: {e}")
            fail = 1
            continue
        errors = validate_source(source)
        if not errors:
            try:
                errors = validate(render(persona, CHECK_URL.format(persona=persona)))
            except CardError as e:
                errors = [str(e)]
        for e in errors:
            print(f"FAIL  {rel}: {e}")
        fail |= bool(errors)
    if not fail:
        print(f"OK  {len(sources)} Agent Cards valid")
    return fail


def main():
    ap = argparse.ArgumentParser(description="Render or check A2A Agent Cards.")
    ap.add_argument("persona", nargs="?", help="Card to render, e.g. patricia")
    ap.add_argument("--url", help="The endpoint where the agent is served (https)")
    ap.add_argument("--binding", default="JSONRPC", help="Protocol binding (default JSONRPC); the core ones are JSONRPC, GRPC and HTTP+JSON")
    ap.add_argument("--check", action="store_true", help="Validate every card; used by CI")
    args = ap.parse_args()
    if args.check:
        return check_all()
    if not args.persona or not args.url:
        ap.error("give a persona and --url, or --check")
    if not (HIVE / "cards" / args.persona / "card.json").is_file():
        ap.error(f"no card at cards/{args.persona}/card.json")
    try:
        source = json.loads((HIVE / "cards" / args.persona / "card.json").read_text())
        errors = validate_source(source)
        if not errors:
            card = render(args.persona, args.url, args.binding)
            errors = validate(card)
    except ValueError as e:
        errors = [f"card.json is not valid JSON: {e}"]
    except CardError as e:
        errors = [str(e)]
    if errors:
        for e in errors:
            print(f"error: {e}", file=sys.stderr)
        return 2
    print(json.dumps(card, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
