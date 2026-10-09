"""OAuth2 client-credentials authentication for every A2A request.

A caller sends `Authorization: Bearer <access token>`, a JWT its identity provider
(Microsoft Entra, for werkrbee) issued through the client-credentials flow. The token
must be signed by a key in the configured JWKS, name the configured issuer and audience,
be unexpired, and come from a client on the allowlist, identified by the first claim in
auth.client_claims that is present (Entra v2 tokens carry `azp`, v1 tokens `appid`).
When auth.required_roles is set, the token's `roles` must include one of them.

Only the Agent Card is served without a token, because a client has to read it to learn
how to authenticate. It holds no secrets.
"""
import json

import anyio
import jwt
from starlette.authentication import BaseUser
from starlette.responses import JSONResponse

PUBLIC_PATHS = {"/.well-known/agent-card.json"}


class Caller(BaseUser):
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
        """The authenticated client id, or (status, reason) when the request is refused."""
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
        client = next((claims[c] for c in self.auth.client_claims if isinstance(claims.get(c), str)), None)
        if client not in self.auth.allowed_clients:
            return None, (403, "this client is not allowed to call this agent")
        roles = claims.get("roles") if isinstance(claims.get("roles"), list) else []
        if self.auth.required_roles and not set(roles) & set(self.auth.required_roles):
            return None, (403, "the token lacks a required role")
        return client, None


class AuthMiddleware:
    """ASGI middleware: authenticate every HTTP request except the public paths."""

    def __init__(self, app, authenticator):
        self.app = app
        self.authenticator = authenticator

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or (scope["path"] in PUBLIC_PATHS and scope["method"] in ("GET", "HEAD")):
            return await self.app(scope, receive, send)
        header = dict(scope["headers"]).get(b"authorization", b"").decode("latin-1")
        client, refusal = await self.authenticator.caller(header)
        if refusal:
            status, reason = refusal
            headers = {"www-authenticate": 'Bearer error="invalid_token"'} if status == 401 else {}
            return await JSONResponse({"error": reason}, status_code=status, headers=headers)(scope, receive, send)
        scope["user"] = Caller(client)
        scope["auth"] = {"client": client}
        return await self.app(scope, receive, send)
