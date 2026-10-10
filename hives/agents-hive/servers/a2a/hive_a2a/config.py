"""Server configuration, read from a TOML file. See config.example.toml.

No secret is ever read from the file: a model API key is named by the environment
variable that holds it.
"""
import json
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

# hives/agents-hive/servers/a2a/hive_a2a/config.py -> the repo root
REPO_ROOT = Path(os.environ.get("HIVE_REPO_ROOT") or Path(__file__).resolve().parents[5])

PROVIDERS = ("stub", "anthropic", "openai")
MODEL_AUTH = ("api-key", "entra")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Auth:
    issuer: str
    audience: str
    jwks_url: str | None
    jwks_path: Path | None
    token_url: str
    scope: str
    allowed_clients: tuple[str, ...]
    client_claims: tuple[str, ...]
    required_roles: tuple[str, ...]


@dataclass(frozen=True)
class Model:
    provider: str
    name: str
    base_url: str | None
    auth: str
    api_key_env: str | None
    input_usd_per_mtok: float
    output_usd_per_mtok: float
    max_output_tokens: int


@dataclass(frozen=True)
class Config:
    persona: str
    capability: str
    public_url: str
    database: Path
    ledger: Path
    monthly_ceiling_usd: float
    prompt_files: tuple[Path, ...]
    auth: Auth
    model: Model
    contract: dict

    def price(self, input_tokens, output_tokens):
        m = self.model
        return (input_tokens * m.input_usd_per_mtok + output_tokens * m.output_usd_per_mtok) / 1e6


def _get(table, key, kind, where, default=...):
    if key not in table:
        if default is ...:
            raise ConfigError(f"{where}.{key} is required")
        return default
    value = table[key]
    kinds = (int, float) if kind is float else kind
    if isinstance(value, bool) or not isinstance(value, kinds) or value == "":
        noun = "number" if kind is float else "integer" if kind is int else "string"
        raise ConfigError(f"{where}.{key} must be a non-empty {noun}")
    return value


def _strings(table, key, where, required=False):
    value = table.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise ConfigError(f"{where}.{key} must be a list of non-empty strings")
    if required and not value:
        raise ConfigError(f"{where}.{key} must name at least one entry")
    return tuple(value)


def _path(base, value):
    p = Path(value)
    return p if p.is_absolute() else base / p


def load(path):
    path = Path(path)
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise ConfigError(f"can't read {path}: {e.strerror or e}")
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path} is not valid TOML: {e}")
    base = path.resolve().parent

    s = raw.get("server", {})
    persona = _get(s, "persona", str, "server")
    capability = _get(s, "capability", str, "server")
    public_url = _get(s, "public_url", str, "server")
    if not (public_url.startswith("https://") or public_url.startswith("http://localhost")
            or public_url.startswith("http://127.0.0.1")):
        raise ConfigError("server.public_url must be https (plain http only for localhost)")
    ceiling = _get(s, "monthly_ceiling_usd", float, "server", 25.0)
    if ceiling <= 0:
        raise ConfigError("server.monthly_ceiling_usd must be more than 0")
    prompts = tuple(_path(REPO_ROOT, p) for p in _strings(s, "prompt_files", "server", required=True))
    for p in prompts:
        if not p.is_file():
            raise ConfigError(f"server.prompt_files: {p} doesn't exist")

    contract_path = REPO_ROOT / "hives/agents-hive/contracts" / capability / "contract.json"
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ConfigError(f"no readable contract for '{capability}' at {contract_path}")

    a = raw.get("auth", {})
    jwks_url = a.get("jwks_url")
    jwks_path = a.get("jwks_path")
    if bool(jwks_url) == bool(jwks_path):
        raise ConfigError("auth needs exactly one of jwks_url and jwks_path")
    if jwks_url is not None and not (isinstance(jwks_url, str) and jwks_url.startswith("https://")):
        raise ConfigError("auth.jwks_url must be an https URL")
    auth = Auth(
        issuer=_get(a, "issuer", str, "auth"),
        audience=_get(a, "audience", str, "auth"),
        jwks_url=jwks_url,
        jwks_path=_path(base, jwks_path) if jwks_path else None,
        token_url=_get(a, "token_url", str, "auth"),
        scope=_get(a, "scope", str, "auth"),
        allowed_clients=_strings(a, "allowed_clients", "auth", required=True),
        client_claims=_strings(a, "client_claims", "auth") or ("azp", "appid"),
        required_roles=_strings(a, "required_roles", "auth"),
    )

    m = raw.get("model", {})
    provider = _get(m, "provider", str, "model")
    if provider not in PROVIDERS:
        raise ConfigError(f"model.provider must be one of {', '.join(PROVIDERS)}")
    model_auth = _get(m, "auth", str, "model", "api-key")
    if model_auth not in MODEL_AUTH:
        raise ConfigError(f"model.auth must be one of {', '.join(MODEL_AUTH)}")
    base_url = m.get("base_url")
    if provider != "stub":
        if not (isinstance(base_url, str) and base_url.startswith("https://")):
            raise ConfigError("model.base_url must be an https URL")
        if model_auth == "api-key":
            _get(m, "api_key_env", str, "model")
    model = Model(
        provider=provider,
        name=_get(m, "name", str, "model"),
        base_url=base_url,
        auth=model_auth,
        api_key_env=m.get("api_key_env"),
        input_usd_per_mtok=_get(m, "input_usd_per_mtok", float, "model"),
        output_usd_per_mtok=_get(m, "output_usd_per_mtok", float, "model"),
        max_output_tokens=_get(m, "max_output_tokens", int, "model", 4000),
    )
    if model.input_usd_per_mtok < 0 or model.output_usd_per_mtok < 0 or model.max_output_tokens < 1:
        raise ConfigError("model prices must be non-negative and max_output_tokens at least 1")

    return Config(
        persona=persona,
        capability=capability,
        public_url=public_url,
        database=_path(base, _get(s, "database", str, "server")),
        ledger=_path(base, _get(s, "ledger", str, "server")),
        monthly_ceiling_usd=float(ceiling),
        prompt_files=prompts,
        auth=auth,
        model=model,
        contract=contract,
    )
