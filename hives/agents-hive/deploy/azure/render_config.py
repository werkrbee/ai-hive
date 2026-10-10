#!/usr/bin/env python3
"""Write hive_a2a's config.toml from the environment the Container App sets (main.bicep).

Nothing here is secret: identities are ids, and the model is reached with the app's
managed identity. Standard library only.

Usage: python3 render_config.py /path/to/config.toml
"""
import json
import os
import sys

REQUIRED = ("PUBLIC_URL", "AZURE_TENANT_ID", "API_APP_ID", "ALLOWED_CLIENTS", "MODEL_PROVIDER",
            "MODEL_NAME", "MODEL_BASE_URL", "MODEL_INPUT_USD_PER_MTOK", "MODEL_OUTPUT_USD_PER_MTOK")


def number(name, value):
    try:
        n = float(value)
    except ValueError:
        sys.exit(f"error: {name} must be a number, not {value!r}")
    if n < 0 or n != n or n in (float("inf"),):
        sys.exit(f"error: {name} must be a non-negative number")
    return n


def render(env):
    missing = [k for k in REQUIRED if not env.get(k)]
    if missing:
        sys.exit("error: missing environment: " + ", ".join(missing))
    q = json.dumps  # a JSON string is a valid TOML basic string
    tenant, api = env["AZURE_TENANT_ID"], env["API_APP_ID"]
    clients = [c.strip() for c in env["ALLOWED_CLIENTS"].split(",") if c.strip()]
    if not clients:
        sys.exit("error: ALLOWED_CLIENTS names no client")
    data = env.get("DATA_DIR", "/data")
    login = f"https://login.microsoftonline.com/{tenant}"
    return f"""# Rendered by render_config.py at container start. Don't edit; change main.bicep.
[server]
persona = "patricia"
capability = "governance-review"
public_url = {q(env["PUBLIC_URL"])}
database = {q(data + "/tasks.db")}
ledger = {q(data + "/ledger.jsonl")}
monthly_ceiling_usd = {number("MONTHLY_CEILING_USD", env.get("MONTHLY_CEILING_USD", "25"))}
prompt_files = [
  "hives/rules-hive/rules/queen-charter/AGENTS.md",
  "hives/skills-hive/skills/patricia/SKILL.md",
  "hives/agents-hive/agents/charter-review/agent.md",
]

[auth]
issuer = {q(login + "/v2.0")}
audience = {q(api)}
jwks_url = {q(login + "/discovery/v2.0/keys")}
token_url = {q(login + "/oauth2/v2.0/token")}
scope = {q(f"api://{api}/.default")}
allowed_clients = {q(clients)}
required_roles = ["Review.Request"]

[model]
provider = {q(env["MODEL_PROVIDER"])}
name = {q(env["MODEL_NAME"])}
base_url = {q(env["MODEL_BASE_URL"])}
auth = "entra"
input_usd_per_mtok = {number("MODEL_INPUT_USD_PER_MTOK", env["MODEL_INPUT_USD_PER_MTOK"])}
output_usd_per_mtok = {number("MODEL_OUTPUT_USD_PER_MTOK", env["MODEL_OUTPUT_USD_PER_MTOK"])}
"""


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    with open(sys.argv[1], "w", encoding="utf-8") as f:
        f.write(render(os.environ))
