#!/usr/bin/env python3
"""Write hive_a2a's config.toml from the environment the Container App or job sets
(main.bicep), for Patricia or, with PERSONA=barry, for hosted Barry.

The prompt files are the ones the persona's passport pins, in its order, and each must
match its pinned digest, or this exits without writing a config, so the container doesn't
start on a prompt the passport doesn't pin. Patricia's app and her weekly eval job each
keep a ledger on the share (LEDGER) and count the other's toward the ceiling
(SHARED_LEDGERS).

Barry's config adds the orchestration section: his passport, his run records on his own
share, Patricia as his one delegate and reviewer (PATRICIA_URL, PATRICIA_API_APP_ID), and
his callers' registrations (CALLERS, "client=registration" pairs, comma-separated). His
roles are checked per method, so his auth section requires none.

Nothing here is secret: identities are ids, and the model is reached with the app's
managed identity. Standard library only.

Usage: python3 render_config.py /path/to/config.toml
"""
import hashlib
import json
import os
import sys
from pathlib import Path

REQUIRED = ("PUBLIC_URL", "AZURE_TENANT_ID", "API_APP_ID", "ALLOWED_CLIENTS", "MODEL_API",
            "MODEL_PUBLISHER", "MODEL_NAME", "MODEL_BASE_URL", "MODEL_INPUT_USD_PER_MTOK",
            "MODEL_OUTPUT_USD_PER_MTOK")


def number(name, value):
    try:
        n = float(value)
    except ValueError:
        sys.exit(f"error: {name} must be a number, not {value!r}")
    if n < 0 or n != n or n in (float("inf"),):
        sys.exit(f"error: {name} must be a non-negative number")
    return n


def pinned_prompts(root, persona="patricia"):
    """The prompt files the persona's passport pins, as paths from the repo root, each
    checked against its digest."""
    path = Path(root) / "hives" / "agents-hive" / "passports" / persona / "passport.json"
    try:
        pins = json.loads(path.read_text(encoding="utf-8"))["pins"]["prompt"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        sys.exit(f"error: can't read the prompt files {path} pins ({e})")
    for pin in pins:
        try:
            got = hashlib.sha256((Path(root) / pin["path"]).read_bytes()).hexdigest()
        except OSError:
            sys.exit(f"error: {pin['path']}, which the passport pins, isn't in the image")
        if got != pin["sha256"]:
            sys.exit(f"error: {pin['path']} isn't the version the passport pins (sha256 {got}, pinned {pin['sha256']})")
    return [pin["path"] for pin in pins]


PERSONAS = {"patricia": "governance-review", "barry": "orchestration"}
BARRY_REQUIRED = ("PATRICIA_URL", "PATRICIA_API_APP_ID")


def callers(value):
    """[(client, registration)] from "client=registration,…"."""
    pairs = []
    for item in (i.strip() for i in value.split(",")):
        if not item:
            continue
        client, sep, registration = (x.strip() for x in item.partition("="))
        if not sep or not client or not registration:
            sys.exit(f"error: CALLERS takes client=registration pairs, not {item!r}")
        pairs.append((client, registration))
    return pairs


def orchestration(env, data, q):
    """Barry's [orchestration] section."""
    scope = f"api://{env['PATRICIA_API_APP_ID']}/.default"
    tables = (f"\n[[orchestration.delegates]]\nname = \"patricia\"\nurl = {q(env['PATRICIA_URL'])}\n"
              f"capability = \"governance-review\"\ntoken_scope = {q(scope)}\n")
    for client, registration in callers(env.get("CALLERS", "")):
        tables += f"\n[[orchestration.callers]]\nclient = {q(client)}\nregistration = {q(registration)}\n"
    return f"""
[orchestration]
passport = "barry"
state_dir = {q(data + "/runs")}
reviewer = "patricia"
{tables}"""


def render(env, root=None):
    persona = env.get("PERSONA", "patricia")
    if persona not in PERSONAS:
        sys.exit(f"error: PERSONA must be one of {', '.join(PERSONAS)}, not {persona!r}")
    missing = [k for k in REQUIRED + (BARRY_REQUIRED if persona == "barry" else ()) if not env.get(k)]
    if missing:
        sys.exit("error: missing environment: " + ", ".join(missing))
    q = json.dumps  # a JSON string is a valid TOML basic string
    tenant, api = env["AZURE_TENANT_ID"], env["API_APP_ID"]
    clients = [c.strip() for c in env["ALLOWED_CLIENTS"].split(",") if c.strip()]
    if not clients:
        sys.exit("error: ALLOWED_CLIENTS names no client")
    data = env.get("DATA_DIR", "/data")
    prompts = pinned_prompts(root or env.get("HIVE_REPO_ROOT", "/app"), persona)
    ledger = env.get("LEDGER") or data + "/ledger.jsonl"
    shared = [s.strip() for s in env.get("SHARED_LEDGERS", "").split(",") if s.strip()]
    login = f"https://login.microsoftonline.com/{tenant}"
    return f"""# Rendered by render_config.py at container start. Don't edit; change main.bicep.
[server]
persona = {q(persona)}
capability = {q(PERSONAS[persona])}
public_url = {q(env["PUBLIC_URL"])}
database = {q(data + "/tasks.db")}
ledger = {q(ledger)}
shared_ledgers = {q(shared)}
monthly_ceiling_usd = {number("MONTHLY_CEILING_USD", env.get("MONTHLY_CEILING_USD", "25"))}
prompt_files = {q(prompts)}

[auth]
issuer = {q(login + "/v2.0")}
audience = {q(api)}
jwks_url = {q(login + "/discovery/v2.0/keys")}
token_url = {q(login + "/oauth2/v2.0/token")}
scope = {q(f"api://{api}/.default")}
allowed_clients = {q(clients)}
{'required_roles = ["Review.Request"]' if persona == "patricia" else ""}

[model]
api = {q(env["MODEL_API"])}
publisher = {q(env["MODEL_PUBLISHER"])}
name = {q(env["MODEL_NAME"])}
base_url = {q(env["MODEL_BASE_URL"])}
auth = "entra"
input_usd_per_mtok = {number("MODEL_INPUT_USD_PER_MTOK", env["MODEL_INPUT_USD_PER_MTOK"])}
output_usd_per_mtok = {number("MODEL_OUTPUT_USD_PER_MTOK", env["MODEL_OUTPUT_USD_PER_MTOK"])}
""" + (orchestration(env, data, q) if persona == "barry" else "")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    with open(sys.argv[1], "w", encoding="utf-8") as f:
        f.write(render(os.environ))
