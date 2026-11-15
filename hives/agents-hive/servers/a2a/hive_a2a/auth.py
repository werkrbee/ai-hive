"""OAuth2 client-credentials authentication for every A2A request.

A caller sends `Authorization: Bearer <access token>`, a JWT its identity provider
(Microsoft Entra, for werkrbee) issued through the client-credentials flow. The token
must be signed by a key in the configured JWKS, name the configured issuer and audience,
be unexpired, and come from a client on the allowlist, identified by the first claim in
auth.client_claims that is present (Entra v2 tokens carry `azp`, v1 tokens `appid`).
When auth.required_roles is set, the token's `roles` must include one of them. The roles
also go to the handler, in the request's auth state, so an executor can require a role for
one method (orchestrate.py: Orchestration.Request to start or cancel a task,
Orchestration.Approve to answer one).

A server whose auth.delegated_scopes is set (only hosted Patricia's review, config.py)
also accepts a delegated (user) token from a client on the allowlist when it carries one of
those scopes, so a platform that signs a user in can call her. Such a token needs no role:
the scope is its permission. The user is held only as an opaque ID, a hash of the token's
issuer and `sub` (pairwise in Entra: one user's sub differs for every API), which goes to
the handler with the client and is never logged. Every other server refuses delegated
tokens, as hosted Barry and the verify server do.

Only the Agent Card is served without a token, because a client has to read it to learn
how to authenticate. It holds no secrets. The MCP endpoint (mcp.py) adds its Server Card and
Protected Resource Metadata to the public paths, for the same reason, and a challenge that
points a client at the metadata when its token is missing or invalid.
"""
import hashlib
import json

import anyio
import jwt
from starlette.authentication import BaseUser
from starlette.responses import JSONResponse

PUBLIC_PATHS = {"/.well-known/agent-card.json"}


def user_id(issuer, sub):
    """The opaque ID a delegated token's user is held as: never a name, email or raw claim."""
    return hashlib.sha256(f"{issuer}|{sub}".encode()).hexdigest()[:32]


class Caller(BaseUser):
    """The calling client. Its name is the client ID, which allowances and the ledger count
    by; a delegated token's user is kept apart, in the request's auth state."""

    def __init__(self, client_id):
        self.client_id = client_id

    @property
    def is_authenticated(self):
        return True

    @property
    def display_name(self):
        return self.client_id


class Keys:
    """Signing keys from a JWKS URL (fetched and cached) or a local JWKS file."""

    def __init__(self, auth):
        if auth.jwks_url:
            self.client = jwt.PyJWKClient(auth.jwks_url, cache_keys=True, lifespan=3600)
            self.keyset = None
        else:
            self.client = None
            self.keyset = jwt.PyJWKSet.from_dict(json.loads(auth.jwks_path.read_text(encoding="utf-8")))

    async def key_for(self, token):
        if self.client:
            return await anyio.to_thread.run_sync(self.client.get_signing_key_from_jwt, token)
        kid = jwt.get_unverified_header(token).get("kid")
        for key in self.keyset.keys:
            if key.key_id == kid:
                return key
        raise jwt.InvalidTokenError("no signing key matches the token's kid")


class Authenticator:
    def __init__(self, auth, keys=None):
        self.auth = auth
        self.keys = keys or Keys(auth)

    async def caller(self, header):
        """((client id, its roles, the user's opaque ID or None), None), or (None, (status,
        reason)) when the request is refused."""
        scheme, _, token = (header or "").partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            return None, (401, "a bearer token is required")
        try:
            key = await self.keys.key_for(token.strip())
            claims = jwt.decode(
                token.strip(), key.key, algorithms=["RS256"], audience=self.auth.audience,
                issuer=self.auth.issuer, options={"require": ["exp", "iss", "aud"]}, leeway=60,
            )
        except (jwt.PyJWTError, ValueError) as e:
            return None, (401, f"the token is not valid ({type(e).__name__})")
        delegated = "scp" in claims or claims.get("idtyp", "app") != "app"
        accepted = getattr(self.auth, "delegated_scopes", ())
        if delegated and not accepted:
            return None, (403, "only client-credentials (app) tokens may call this agent")
        if delegated:
            scopes = claims["scp"].split() if isinstance(claims.get("scp"), str) else []
            if not set(scopes) & set(accepted):
                return None, (403, "a delegated token needs a scope this agent accepts")
            if not (isinstance(claims.get("sub"), str) and claims["sub"]):
                return None, (401, "the token is not valid (no sub)")
        client = next((claims[c] for c in self.auth.client_claims if isinstance(claims.get(c), str)), None)
        if client not in self.auth.allowed_clients:
            return None, (403, "this client is not allowed to call this agent")
        roles = claims.get("roles") if isinstance(claims.get("roles"), list) else []
        if not delegated and self.auth.required_roles and not set(roles) & set(self.auth.required_roles):
            return None, (403, "the token lacks a required role")
        user = user_id(self.auth.issuer, claims["sub"]) if delegated else None
        return (client, tuple(r for r in roles if isinstance(r, str)), user), None


def task_owner(context):
    """Whose tasks a request sees (the task store's owner): the client's, for an app token,
    or one user's of that client, for a delegated token, so two users of one platform client
    never see each other's tasks."""
    auth = (context.state.get("auth") if context and context.state else None) or {}
    client = auth.get("client") or (context.user.user_name if context and context.user else "")
    return f"{client}/user/{auth['user']}" if auth.get("user") else client


class AuthMiddleware:
    """ASGI middleware: authenticate every HTTP request except the public paths."""

    def __init__(self, app, authenticator, public=PUBLIC_PATHS, challenges=None):
        """public: paths served without a token; challenges: WWW-Authenticate values by path."""
        self.app = app
        self.authenticator = authenticator
        self.public = set(public)
        self.challenges = challenges or {}

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan" or (
                scope["type"] == "http" and scope["path"] in self.public and scope["method"] in ("GET", "HEAD")):
            return await self.app(scope, receive, send)
        if scope["type"] != "http":
            raise RuntimeError(f"unsupported ASGI scope '{scope['type']}'")
        header = dict(scope["headers"]).get(b"authorization", b"").decode("latin-1")
        who, refusal = await self.authenticator.caller(header)
        if refusal:
            status, reason = refusal
            if scope["path"] in self.challenges:  # no error code when no token was sent (RFC 6750)
                challenge = self.challenges[scope["path"]] + (', error="invalid_token"' if header else "")
            else:
                challenge = 'Bearer error="invalid_token"'
            headers = {"www-authenticate": challenge} if status == 401 else {}
            return await JSONResponse({"error": reason}, status_code=status, headers=headers)(scope, receive, send)
        client, roles, user = who
        scope["user"] = Caller(client)
        scope["auth"] = {"client": client, "roles": roles, "user": user}
        return await self.app(scope, receive, send)
