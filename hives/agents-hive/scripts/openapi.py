#!/usr/bin/env python3
"""Render and check the OpenAPI 3.0 document for a capability's A2A HTTP+JSON binding.

A2A v1.0's HTTP+JSON binding is one of the protocol's standard bindings, not another API.
This document describes one of its operations, SendMessage (`POST /message:send`), for a
low-code platform that imports OpenAPI and has neither A2A nor MCP, or whose A2A and MCP
can't carry a token the agent accepts (docs/low-code-alignment.md). It is rendered from the
capability's execution contract, as an Agent Card's skills are, so it can't drift from the
contract:

  the request    one message with one data part, narrowed to the contract's `inputs`
  the reply      the task, whose artifact's data part is narrowed to the contract's `output`;
                 a refusal before any task (input that breaks the contract, a missing
                 A2A-Version header) is A2A's REST error, and a refusal by the monthly
                 ceiling is a rejected task whose status message says why
  the security   OAuth2: Entra's client-credentials flow, and, where the agent accepts a
                 user's delegated token, the authorization-code flow with its scope

The server serves the document without a token, beside its Agent Card. `--check` renders
one for every contract against a stand-in endpoint and checks each against the OpenAPI
3.0.3 rules it uses, which is what CI runs.

Standard library only.

Usage:
  python3 scripts/openapi.py --check
  python3 scripts/openapi.py governance-review --url https://agents.example.org/a2a/patricia \\
      --token-url https://login.microsoftonline.com/<tenant>/oauth2/v2.0/token \\
      --scope api://<api-app-id>/.default [--delegated-scope Review.RequestAsUser]
"""
import argparse
import copy
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

HIVE = Path(__file__).resolve().parent.parent
REPO_ROOT = HIVE.parent.parent
OPENAPI_VERSION = "3.0.3"
PROTOCOL_VERSION = "1.0"
PATH = "/message:send"
CHECK_URL = "https://a2a.invalid/{capability}"
CHECK_OAUTH = {"tokenUrl": "https://login.invalid/tenant/oauth2/v2.0/token", "scope": "api://api-app/.default",
               "delegated": ["Review.RequestAsUser"]}
A2A_JSON = "application/a2a+json"
TASK_STATES = ["TASK_STATE_SUBMITTED", "TASK_STATE_WORKING", "TASK_STATE_COMPLETED", "TASK_STATE_FAILED",
               "TASK_STATE_CANCELED", "TASK_STATE_REJECTED"]

# The Schema Object's fields in OpenAPI 3.0.3, and the keywords a contract may use
# (servers/a2a/hive_a2a/contract.py), all of which are among them.
SCHEMA_FIELDS = {"title", "multipleOf", "maximum", "exclusiveMaximum", "minimum", "exclusiveMinimum",
                 "maxLength", "minLength", "pattern", "maxItems", "minItems", "uniqueItems", "maxProperties",
                 "minProperties", "required", "enum", "type", "allOf", "oneOf", "anyOf", "not", "items",
                 "properties", "additionalProperties", "description", "format", "default", "nullable",
                 "discriminator", "readOnly", "writeOnly", "xml", "externalDocs", "example", "deprecated"}
CONTRACT_KEYWORDS = {"type", "required", "properties", "enum", "items", "description", "additionalProperties"}
TYPES = {"string", "number", "integer", "boolean", "array", "object"}
METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
FLOWS = {"implicit": {"authorizationUrl"}, "password": {"tokenUrl"}, "clientCredentials": {"tokenUrl"},
         "authorizationCode": {"authorizationUrl", "tokenUrl"}}
STATUS = re.compile(r"^([1-5]XX|[1-5]\d\d|default)$")


class SpecError(Exception):
    pass


def require_secure(url):
    """HTTPS only, except plain HTTP to localhost for development, as for Agent Cards."""
    parsed = urlparse(url)
    local = parsed.hostname in ("localhost", "127.0.0.1", "::1")
    return parsed.scheme == "https" and bool(parsed.hostname) or (parsed.scheme == "http" and local)


def schema(contract_schema, where):
    """A contract schema as an OpenAPI 3.0 Schema Object. A contract's keywords are all
    Schema Object fields; a string enum also gets its type, which some importers need."""
    unknown = set(contract_schema) - CONTRACT_KEYWORDS
    if unknown:
        raise SpecError(f"{where}: '{sorted(unknown)[0]}' isn't a contract keyword; run validate_contracts.py")
    out = copy.deepcopy(contract_schema)
    if "enum" in out and "type" not in out and all(isinstance(v, str) for v in out["enum"]):
        out["type"] = "string"
    if "properties" in out:
        out["properties"] = {k: schema(v, f"{where}.{k}") for k, v in out["properties"].items()}
    if "items" in out:
        out["items"] = schema(out["items"], f"{where}[]")
    return out


def ref(name):
    return {"$ref": f"#/components/schemas/{name}"}


def scopes(oauth):
    """The delegated scopes' full names: the API's identifier URI and each scope."""
    base = oauth["scope"].rsplit("/", 1)[0]
    return [f"{base}/{s}" for s in oauth.get("delegated") or ()]


def authorize_url(token_url):
    """Entra's authorization endpoint beside its token endpoint."""
    if not token_url.endswith("/token"):
        raise SpecError(f"can't tell the authorization endpoint from the token URL {token_url}")
    return token_url[:-len("token")] + "authorize"


def security(oauth, persona, capability):
    who = f"{persona.capitalize()}'s {capability}" if persona else capability
    flows = {"clientCredentials": {"tokenUrl": oauth["tokenUrl"],
                                   "scopes": {oauth["scope"]: f"Call {who} as an allowlisted app"}}}
    requirements = [{"entra": [oauth["scope"]]}]
    delegated = scopes(oauth)
    if delegated:
        flows["authorizationCode"] = {"authorizationUrl": authorize_url(oauth["tokenUrl"]),
                                      "tokenUrl": oauth["tokenUrl"],
                                      "scopes": {s: f"Call {who} as the signed-in user" for s in delegated}}
        requirements += [{"entra": [s]} for s in delegated]
    scheme = {"type": "oauth2", "flows": flows,
              "description": "Microsoft Entra. Only allowlisted clients may call: an app token needs the "
                             "API's app role, and a user's delegated token the delegated scope."}
    return scheme, requirements


def render(contract, url, oauth, persona=None):
    """The OpenAPI document for contract's SendMessage over HTTP+JSON at url. oauth holds
    tokenUrl, scope (the client-credentials scope, e.g. api://<app>/.default) and, where the
    agent accepts a user's delegated token, delegated: its scope names."""
    cap = contract["capability"]
    if contract["inputs"].get("type") != "object" or contract["output"].get("type") != "object":
        raise SpecError(f"{cap}: an HTTP+JSON data part needs object inputs and output")
    scheme, requirements = security(oauth, persona, cap)
    text_or_data = {"type": "object", "description": "A text part or a data part.",
                    "properties": {"text": {"type": "string"},
                                   "data": {"type": "object", "additionalProperties": True},
                                   "mediaType": {"type": "string"}}}
    schemas = {
        "Input": schema(contract["inputs"], "inputs"),
        "Output": schema(contract["output"], "output"),
        "InputPart": {"type": "object", "required": ["data"],
                      "properties": {"data": ref("Input"),
                                     "mediaType": {"type": "string", "enum": ["application/json"]}}},
        "Message": {"type": "object", "required": ["messageId", "role", "parts"],
                    "properties": {
                        "messageId": {"type": "string", "description": "A new unique ID for each message, "
                                                                       "such as a UUID."},
                        "role": {"type": "string", "enum": ["ROLE_USER"]},
                        "parts": {"type": "array", "minItems": 1, "maxItems": 1, "items": ref("InputPart")}}},
        "SendMessageRequest": {"type": "object", "required": ["message"], "properties": {"message": ref("Message")}},
        "OutputPart": {"type": "object", "required": ["data"],
                       "properties": {"data": ref("Output"), "mediaType": {"type": "string"}}},
        "Artifact": {"type": "object", "required": ["artifactId", "parts"],
                     "properties": {"artifactId": {"type": "string"}, "name": {"type": "string"},
                                    "parts": {"type": "array", "items": ref("OutputPart")}}},
        "StatusMessage": {"type": "object", "description": "Why the task failed or was rejected: a text part, "
                                                           "and for a rejection a data part with the refusal.",
                          "properties": {"messageId": {"type": "string"}, "role": {"type": "string"},
                                         "parts": {"type": "array", "items": text_or_data}}},
        "TaskStatus": {"type": "object", "required": ["state"],
                       "properties": {"state": {"type": "string", "enum": TASK_STATES},
                                      "message": ref("StatusMessage"),
                                      "timestamp": {"type": "string", "format": "date-time"}}},
        "Task": {"type": "object", "required": ["id", "contextId", "status"],
                 "properties": {"id": {"type": "string"}, "contextId": {"type": "string"},
                                "status": ref("TaskStatus"),
                                "artifacts": {"type": "array", "items": ref("Artifact"),
                                              "description": "On a completed task, the verdict."}}},
        "SendMessageResponse": {"type": "object", "required": ["task"], "properties": {"task": ref("Task")}},
        "Error": {"type": "object", "required": ["error"], "description": "A2A's REST error.",
                  "properties": {"error": {"type": "object", "required": ["code", "status", "message"],
                                           "properties": {
                                               "code": {"type": "integer"}, "status": {"type": "string"},
                                               "message": {"type": "string"},
                                               "details": {"type": "array", "items": {
                                                   "type": "object", "additionalProperties": True}}}}}},
        "AuthError": {"type": "object", "required": ["error"], "properties": {"error": {"type": "string"}}},
    }

    def body(name, media="application/json"):
        return {"content": {media: {"schema": ref(name)}}}

    rel = f"hives/agents-hive/contracts/{cap}/contract.json"
    operation = {
        "operationId": "SendMessage",
        "summary": contract["description"],
        "description": f"A2A v{PROTOCOL_VERSION} SendMessage over the HTTP+JSON binding. The message's one data "
                       f"part is the input of the execution contract {rel} (version {contract['version']}), and "
                       "the completed task's artifact is its output. The reply waits for the task to finish.",
        "parameters": [{"name": "A2A-Version", "in": "header", "required": True,
                        "description": "The A2A protocol version the request speaks.",
                        "schema": {"type": "string", "enum": [PROTOCOL_VERSION]}}],
        "requestBody": {"required": True, "content": {m: {"schema": ref("SendMessageRequest")}
                                                      for m in ("application/json", A2A_JSON)}},
        "responses": {
            "200": {"description": "The task: completed with the verdict as its artifact, failed, or rejected by "
                                   "the monthly ceiling or the client's allowance.",
                    **body("SendMessageResponse", A2A_JSON)},
            "400": {"description": "Refused before any task: input that breaks the contract, a media type the "
                                   "Agent Card doesn't declare, or an unsupported A2A-Version.",
                    **body("Error")},
            "401": {"description": "No valid token.", **body("AuthError"),
                    "headers": {"WWW-Authenticate": {"schema": {"type": "string"}}}},
            "403": {"description": "The token's client isn't allowlisted, or it lacks the role or scope.",
                    **body("AuthError")},
            "429": {"description": "Past the client's hourly rate. Nothing was sent to the model.", **body("Error"),
                    "headers": {"Retry-After": {"description": "Seconds until the client may send again.",
                                                "schema": {"type": "integer"}}}},
        },
    }
    title = f"{persona.capitalize()}: {cap}" if persona else cap
    return {
        "openapi": OPENAPI_VERSION,
        "info": {"title": title, "version": str(contract["version"]),
                 "description": f"{contract['description']} This describes A2A's standard HTTP+JSON binding "
                                "for this one operation; the Agent Card at /.well-known/agent-card.json "
                                "describes the agent."},
        "servers": [{"url": url.rstrip("/")}],
        "paths": {PATH: {"post": operation}},
        "components": {"schemas": schemas, "securitySchemes": {"entra": scheme}},
        "security": requirements,
    }


# --- checking ---------------------------------------------------------------------------


def resolve(doc, pointer):
    if not pointer.startswith("#/components/"):
        return None
    node = doc
    for part in pointer[2:].split("/"):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def check_schema(doc, s, where, err):
    if not isinstance(s, dict):
        return err(f"{where}: a schema must be an object")
    if "$ref" in s:
        if set(s) != {"$ref"}:
            err(f"{where}: a $ref has no sibling fields in OpenAPI 3.0")
        if resolve(doc, s["$ref"]) is None:
            err(f"{where}: $ref {s['$ref']} doesn't resolve")
        return
    for key in sorted(k for k in set(s) - SCHEMA_FIELDS if not k.startswith("x-")):
        err(f"{where}: '{key}' isn't a Schema Object field in OpenAPI 3.0")
    if "type" in s and not (isinstance(s["type"], str) and s["type"] in TYPES):
        err(f"{where}: type must be one of {', '.join(sorted(TYPES))}, a single string")
    if s.get("type") == "array" and "items" not in s:
        err(f"{where}: an array needs items")
    if "required" in s and not (isinstance(s["required"], list) and s["required"]
                                and all(isinstance(x, str) for x in s["required"])):
        err(f"{where}: required must be a non-empty list of names")
    if "enum" in s and not (isinstance(s["enum"], list) and s["enum"]):
        err(f"{where}: enum must be a non-empty list")
    for name, sub in (s.get("properties") or {}).items():
        check_schema(doc, sub, f"{where}.{name}", err)
    if "items" in s:
        check_schema(doc, s["items"], f"{where}[]", err)
    if isinstance(s.get("additionalProperties"), dict):
        check_schema(doc, s["additionalProperties"], f"{where}{{}}", err)
    for key in ("allOf", "oneOf", "anyOf"):
        for i, sub in enumerate(s.get(key) or []):
            check_schema(doc, sub, f"{where}.{key}[{i}]", err)


def check_content(doc, content, where, err):
    if not isinstance(content, dict) or not content:
        return err(f"{where}: content must name at least one media type")
    for media, item in content.items():
        if not isinstance(item, dict) or "schema" not in item:
            err(f"{where}.{media}: needs a schema")
        else:
            check_schema(doc, item["schema"], f"{where}.{media}.schema", err)


def check_security(doc, err):
    schemes = doc.get("components", {}).get("securitySchemes", {})
    granted = {}
    for name, s in schemes.items():
        where = f"securitySchemes.{name}"
        if not isinstance(s, dict) or s.get("type") != "oauth2":
            err(f"{where}: only oauth2 schemes are rendered")
            continue
        flows = s.get("flows")
        if not isinstance(flows, dict) or not flows:
            err(f"{where}: an oauth2 scheme needs flows")
            continue
        granted[name] = set()
        for flow, f in flows.items():
            if flow not in FLOWS:
                err(f"{where}.flows: unknown flow '{flow}'")
                continue
            for key in sorted(FLOWS[flow]):
                if not isinstance(f.get(key), str) or not require_secure(f[key]):
                    err(f"{where}.flows.{flow}.{key} must be an https URL")
            if not isinstance(f.get("scopes"), dict):
                err(f"{where}.flows.{flow}.scopes must be a map")
            else:
                granted[name] |= set(f["scopes"])
    requirements = doc.get("security", [])
    if not isinstance(requirements, list) or not requirements:
        err("security must list at least one requirement: every call needs a token")
        requirements = []
    for i, r in enumerate(requirements):
        for name, wanted in (r.items() if isinstance(r, dict) else []):
            if name not in granted:
                err(f"security[{i}]: no security scheme named '{name}'")
            elif not set(wanted) <= granted[name]:
                err(f"security[{i}]: {name} has no flow granting {sorted(set(wanted) - granted[name])}")


def validate(doc):
    """Check a rendered document against the OpenAPI 3.0.3 rules it uses. Returns a list
    of problems."""
    if not isinstance(doc, dict):
        return ["the document is not a JSON object"]
    errors = []
    err = errors.append
    if not isinstance(doc.get("openapi"), str) or not re.match(r"^3\.0\.\d+$", doc["openapi"]):
        err("openapi must be a 3.0.x version string")
    info = doc.get("info")
    if not isinstance(info, dict) or not all(isinstance(info.get(k), str) and info[k] for k in ("title", "version")):
        err("info needs a title and a version")
    servers = doc.get("servers")
    if not isinstance(servers, list) or not servers:
        err("servers must name the endpoint")
        servers = []
    for i, s in enumerate(servers):
        if not isinstance(s, dict) or not isinstance(s.get("url"), str) or not require_secure(s["url"]):
            err(f"servers[{i}].url must be an https URL (http only for localhost)")
    paths = doc.get("paths")
    if not isinstance(paths, dict) or not paths:
        err("paths must hold at least one operation")
        paths = {}
    ids = []
    for path, item in paths.items():
        if not path.startswith("/"):
            err(f"path '{path}' must start with /")
        for method, op in (item.items() if isinstance(item, dict) else []):
            where = f"{method.upper()} {path}"
            if method not in METHODS:
                err(f"{where}: unknown method")
                continue
            ids.append(op.get("operationId"))
            for p in op.get("parameters", []):
                if not isinstance(p.get("name"), str) or p.get("in") not in ("query", "header", "path", "cookie"):
                    err(f"{where}: a parameter needs a name and where it goes")
                elif p["in"] == "path" and (not p.get("required") or f"{{{p['name']}}}" not in path):
                    err(f"{where}: path parameter {p['name']} must be required and in the path")
                if "schema" in p:
                    check_schema(doc, p["schema"], f"{where} parameter {p.get('name')}", err)
            if "requestBody" in op:
                check_content(doc, op["requestBody"].get("content"), f"{where} requestBody", err)
            responses = op.get("responses")
            if not isinstance(responses, dict) or not responses:
                err(f"{where}: needs responses")
                continue
            for status, r in responses.items():
                if not STATUS.match(str(status)):
                    err(f"{where}: response '{status}' isn't a status code")
                if not isinstance(r, dict) or not isinstance(r.get("description"), str):
                    err(f"{where} {status}: a response needs a description")
                    continue
                if "content" in r:
                    check_content(doc, r["content"], f"{where} {status}", err)
    for x in ids:
        if not isinstance(x, str) or not x:
            err("every operation needs an operationId")
        elif ids.count(x) > 1:
            err(f"operationId {x} appears more than once")
    for name, s in doc.get("components", {}).get("schemas", {}).items():
        check_schema(doc, s, f"components.schemas.{name}", err)
    check_security(doc, err)
    return sorted(set(errors), key=errors.index)


def contracts():
    for path in sorted((HIVE / "contracts").glob("*/contract.json")):
        yield path, json.loads(path.read_text())


def check_all():
    fail, count = 0, 0
    for path, contract in contracts():
        rel = path.relative_to(REPO_ROOT)
        cap = contract.get("capability", path.parent.name)
        try:
            problems = validate(render(contract, CHECK_URL.format(capability=cap), CHECK_OAUTH))
        except (SpecError, KeyError, AttributeError) as e:
            problems = [str(e) or f"missing {e}"]
        for p in problems:
            print(f"FAIL  {rel}: {p}")
        fail |= bool(problems)
        count += 1
    if not count:
        print("FAIL  no execution contracts found under contracts/")
        return 1
    if not fail:
        print(f"OK  {count} OpenAPI documents valid")
    return fail


def main():
    ap = argparse.ArgumentParser(description="Render or check a capability's OpenAPI document for A2A HTTP+JSON.")
    ap.add_argument("capability", nargs="?", help="The contract to render, e.g. governance-review")
    ap.add_argument("--url", help="The agent's A2A endpoint (https)")
    ap.add_argument("--token-url", help="The OAuth2 token endpoint")
    ap.add_argument("--scope", help="The client-credentials scope, e.g. api://<api-app-id>/.default")
    ap.add_argument("--delegated-scope", action="append", default=[], help="A delegated scope the agent accepts")
    ap.add_argument("--persona", help="The persona serving it, for the title")
    ap.add_argument("--check", action="store_true", help="Render and check one for every contract; used by CI")
    args = ap.parse_args()
    if args.check:
        return check_all()
    if not (args.capability and args.url and args.token_url and args.scope):
        ap.error("give a capability, --url, --token-url and --scope, or --check")
    path = HIVE / "contracts" / args.capability / "contract.json"
    if not path.is_file():
        ap.error(f"no contract at contracts/{args.capability}/contract.json")
    try:
        doc = render(json.loads(path.read_text()), args.url,
                     {"tokenUrl": args.token_url, "scope": args.scope, "delegated": args.delegated_scope},
                     args.persona)
        problems = validate(doc)
    except SpecError as e:
        problems = [str(e)]
    if problems:
        for p in problems:
            print(f"error: {p}", file=sys.stderr)
        return 2
    print(json.dumps(doc, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
