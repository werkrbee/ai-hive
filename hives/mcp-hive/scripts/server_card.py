"""Fetch, validate and resolve MCP Server Cards (the Server Card extension, SEP-2127).

A registry entry can describe a remote server by where its Server Card lives instead of
by a hand-written config. Its `discovery` block names either the card itself
(`{"card": URL}`) or a domain's AI Catalog plus the entry to pick
(`{"catalog": URL, "identifier": URN}`), usually the catalog at
`https://<domain>/.well-known/ai-catalog.json`.

The card is checked against the extension schema
(github.com/modelcontextprotocol/ext-server-card, schema.ts) and turned into a neutral
remote config: a URL plus the headers the server requires. A header value is a list of
parts, each a literal string or an environment variable to read at connect time, so no
secret is ever written into a config file. Card contents are advisory; the client still
verifies them against the live server.

Standard library only.
"""
import json
import re
import urllib.error
import urllib.request
from urllib.parse import urlparse

CARD_SCHEMA = "https://static.modelcontextprotocol.io/schemas/v1/server-card.schema.json"
CARD_TYPE = "application/mcp-server-card+json"
CATALOG_TYPE = "application/ai-catalog+json"
NAME = re.compile(r"^[a-zA-Z0-9.-]+/[a-zA-Z0-9._-]+$")
REMOTE_URL = re.compile(r"^(https?://[^\s]+|\{[a-zA-Z_][a-zA-Z0-9_]*\}[^\s]*)$")
VERSION_RANGE = re.compile(r"^[\^~<>=]|(^|\.)[x*](\.|$)")
VAR = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
TIMEOUT = 10


class CardError(Exception):
    pass


def require_secure(url):
    """HTTPS only, except plain HTTP to localhost for development."""
    parsed = urlparse(url)
    local = parsed.hostname in ("localhost", "127.0.0.1", "::1")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
        raise CardError(f"{url}: must be https (plain http is allowed only for localhost)")


class NoDowngrade(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        require_secure(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(NoDowngrade)


def fetch_json(url, accept):
    """GET a JSON document over HTTPS, refusing redirects that drop to plain HTTP."""
    require_secure(url)
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "mcp-hive"})
    try:
        with OPENER.open(req, timeout=TIMEOUT) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        raise CardError(f"{url}: HTTP {e.code}")
    except (urllib.error.URLError, OSError) as e:
        raise CardError(f"{url}: {getattr(e, 'reason', e)}")
    try:
        return json.loads(body)
    except ValueError:
        raise CardError(f"{url}: response is not JSON")


def card_url_from_catalog(catalog_url, identifier):
    catalog = fetch_json(catalog_url, CATALOG_TYPE)
    entries = catalog.get("entries") if isinstance(catalog, dict) else None
    if not isinstance(entries, list):
        raise CardError(f"{catalog_url}: not an AI Catalog (no entries list)")
    for e in entries:
        if isinstance(e, dict) and e.get("identifier") == identifier:
            if e.get("type") != CARD_TYPE:
                raise CardError(f"{catalog_url}: entry {identifier} is {e.get('type')}, not a Server Card")
            if "data" in e:
                return None, e["data"]
            if isinstance(e.get("url"), str):
                return e["url"], None
            raise CardError(f"{catalog_url}: entry {identifier} has neither url nor data")
    raise CardError(f"{catalog_url}: no entry {identifier}")


def load_card(discovery):
    """Return (where it came from, card) for a registry entry's discovery block."""
    if "card" in discovery:
        url = discovery["card"]
        return url, fetch_json(url, CARD_TYPE)
    if "catalog" in discovery and "identifier" in discovery:
        url, inline = card_url_from_catalog(discovery["catalog"], discovery["identifier"])
        if inline is not None:
            return f"{discovery['catalog']} (inline)", inline
        return url, fetch_json(url, CARD_TYPE)
    raise CardError("discovery needs either 'card', or 'catalog' and 'identifier'")


def validate(card):
    """Check a card against the Server Card schema. Returns a list of problems."""
    if not isinstance(card, dict):
        return ["card is not a JSON object"]
    errors = []
    err = errors.append
    if card.get("$schema") != CARD_SCHEMA:
        err(f"$schema must be {CARD_SCHEMA}")
    name = card.get("name")
    if not isinstance(name, str) or not 3 <= len(name) <= 200 or not NAME.match(name):
        err("name must be reverse-DNS with one slash, e.g. com.example/weather")
    version = card.get("version")
    if not isinstance(version, str) or len(version) > 255:
        err("version must be a string of at most 255 characters")
    elif VERSION_RANGE.search(version):
        err(f"version must not be a range: {version}")
    desc = card.get("description")
    if not isinstance(desc, str) or not 1 <= len(desc) <= 100:
        err("description must be 1 to 100 characters")
    if "title" in card and (not isinstance(card["title"], str) or not 1 <= len(card["title"]) <= 100):
        err("title must be 1 to 100 characters")
    if "websiteUrl" in card and not isinstance(card["websiteUrl"], str):
        err("websiteUrl must be a URL string")
    repo = card.get("repository")
    if repo is not None and (not isinstance(repo, dict) or not isinstance(repo.get("url"), str)
                             or not isinstance(repo.get("source"), str)):
        err("repository needs url and source")
    icons = card.get("icons", [])
    if not isinstance(icons, list) or not all(isinstance(i, dict) and isinstance(i.get("src"), str)
                                               and i.get("theme", "light") in ("light", "dark")
                                               for i in icons):
        err("icons must be a list of {src, optional theme light|dark}")
    remotes = card.get("remotes", [])
    if not isinstance(remotes, list):
        err("remotes must be a list")
        remotes = []
    for i, r in enumerate(remotes):
        where = f"remotes[{i}]"
        if not isinstance(r, dict):
            err(f"{where} must be an object")
            continue
        if r.get("type") not in ("streamable-http", "sse"):
            err(f"{where}.type must be streamable-http or sse")
        if not isinstance(r.get("url"), str) or not REMOTE_URL.match(r["url"]):
            err(f"{where}.url must start with http(s):// or a {{variable}}")
        headers = r.get("headers", [])
        if not isinstance(headers, list):
            err(f"{where}.headers must be a list")
            headers = []
        for j, h in enumerate(headers):
            if not isinstance(h, dict) or not isinstance(h.get("name"), str) or not h["name"]:
                err(f"{where}.headers[{j}] needs a name")
                continue
            input_problems(h, f"{where}.headers[{j}]", err)
            check_vars(h.get("variables", {}), f"{where}.headers[{j}].variables", err)
        check_vars(r.get("variables", {}), f"{where}.variables", err)
        v = r.get("supportedProtocolVersions")
        if v is not None and (not isinstance(v, list) or not all(isinstance(x, str) for x in v)):
            err(f"{where}.supportedProtocolVersions must be a list of strings")
    return errors


def input_problems(spec, where, err):
    if "format" in spec and spec["format"] not in ("string", "number", "boolean", "filepath"):
        err(f"{where}.format must be string, number, boolean or filepath")
    if "choices" in spec and (not isinstance(spec["choices"], list)
                              or not all(isinstance(c, str) for c in spec["choices"])):
        err(f"{where}.choices must be a list of strings")
    for key in ("value", "default", "description", "placeholder"):
        if key in spec and not isinstance(spec[key], str):
            err(f"{where}.{key} must be a string")


def check_vars(variables, where, err):
    if not isinstance(variables, dict):
        err(f"{where} must be an object")
        return
    for name, spec in variables.items():
        if not isinstance(spec, dict):
            err(f"{where}.{name} must be an object")
        else:
            input_problems(spec, f"{where}.{name}", err)


def env_name(entry, var):
    return re.sub(r"[^A-Z0-9]+", "_", f"{entry}_{var}".upper()).strip("_")


def resolve(entry_name, card, entry_vars):
    """Turn a valid card into a neutral remote config for one registry entry.

    Returns {"url", "headers": [{"name", "parts", "secret"}], "optional", "versions"}.
    URL variables must resolve to concrete values (from the entry's `variables`, the
    card's preset value or its default). Header variables that are secret or unresolved
    become environment variables. Headers the card marks optional are listed, not written.
    """
    remotes = [r for r in card.get("remotes", []) if r.get("type") == "streamable-http"]
    if not remotes:
        offered = sorted({r.get("type") for r in card.get("remotes", [])}) or ["none"]
        raise CardError(f"card offers no streamable-http remote (offers: {', '.join(offered)})")
    remote = remotes[0]

    def concrete(var, spec):
        spec = spec or {}
        if var in entry_vars:
            if spec.get("isSecret"):
                raise CardError(f"variables.{var} is secret; set it in the environment, not the registry")
            return entry_vars[var]
        for key in ("value", "default"):
            if isinstance(spec.get(key), str) and not spec.get("isSecret"):
                return spec[key]
        return None

    url_vars = remote.get("variables", {})

    def fill_url(m):
        value = concrete(m.group(1), url_vars.get(m.group(1)))
        if value is None:
            raise CardError(f"url variable '{m.group(1)}' has no value; set variables.{m.group(1)} in the entry")
        return value

    url = VAR.sub(fill_url, remote["url"])
    # The harness will send the card's headers here, so a card can't steer it to plain HTTP.
    require_secure(url)

    headers, optional = [], []
    for h in remote.get("headers", []):
        if not h.get("isRequired"):
            optional.append(h["name"])
            continue
        template = h.get("value")
        if not isinstance(template, str):
            # No template: the whole header value is the user's input.
            headers.append({"name": h["name"], "parts": [("env", env_name(entry_name, h["name"]))],
                            "secret": bool(h.get("isSecret"))})
            continue
        parts, secret, pos = [], False, 0
        hvars = h.get("variables", {})
        for m in VAR.finditer(template):
            if m.start() > pos:
                parts.append(("text", template[pos:m.start()]))
            var, spec = m.group(1), hvars.get(m.group(1)) or {}
            value = concrete(var, spec)
            if value is None:
                parts.append(("env", env_name(entry_name, var)))
                secret = secret or bool(spec.get("isSecret"))
            else:
                parts.append(("text", value))
            pos = m.end()
        if pos < len(template):
            parts.append(("text", template[pos:]))
        headers.append({"name": h["name"], "parts": parts, "secret": secret or bool(h.get("isSecret"))})

    return {"url": url, "headers": headers, "optional": optional,
            "versions": remote.get("supportedProtocolVersions")}
