"""Per-client limits on reviews, over every binding (A2A SendMessage, over JSON-RPC or
HTTP+JSON, and MCP tools/call).

Two limits, each keyed by the client ID auth.py authenticated:

  rate       each client may send limits.reviews_per_hour reviews in any hour. One past it
             gets HTTP 429 with Retry-After, and an error saying when to try again (a
             JSON-RPC error, or over HTTP+JSON A2A's REST error), before the request
             reaches a handler, so it costs nothing. The window is kept
             in this process: a restart, or scaling to zero, starts it afresh. The allowance
             below is what bounds spending across restarts.
  allowance  what one client may spend or reserve in a month, as a share of the monthly
             ceiling: limits.client_share by default, so no one client can spend the whole
             month's ceiling. A client in limits.clients has its own share instead, held for
             it: no other client's reviews may use it, so a platform can't crowd out hosted
             Barry's approval reviews. The allowance is checked when the review's cost is
             reserved (ledger.py), from the `client` the ledger records on each entry, so it
             survives restarts; a review over it is refused like one over the ceiling, saying
             when it is accepted again.
"""
import collections
import json
import math
import time

from .ledger import Refusal, month_of, next_month

WINDOW_SECONDS = 3600
RATE_LIMITED = -32000  # JSON-RPC's server error range; the HTTP status is what clients act on
REST = None  # in RateLimit's paths: every POST there starts a review (HTTP+JSON's message:send)


class Limiter:
    """Each client's reviews in the last hour, in this process."""

    def __init__(self, limits, clock=time.monotonic):
        self.limits = limits
        self.clock = clock
        self.sent = {}  # client -> the times of its admitted reviews, oldest first

    def admit(self, client):
        """None when the review is admitted (and counted), or the seconds until the client
        may send another."""
        now = self.clock()
        sent = self.sent.setdefault(client, collections.deque())
        while sent and sent[0] <= now - WINDOW_SECONDS:
            sent.popleft()
        if len(sent) >= self.limits.per_hour(client):
            return max(1, math.ceil(sent[0] + WINDOW_SECONDS - now))
        sent.append(now)
        return None


class RateLimit:
    """ASGI middleware: refuse a client's review past its hourly rate with 429. paths maps
    each path to the JSON-RPC methods there that start a review, or to REST where every POST
    does. It sits inside AuthMiddleware, which has put the client in the scope."""

    def __init__(self, app, limiter, paths):
        self.app = app
        self.limiter = limiter
        self.paths = paths

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] not in self.paths:
            return await self.app(scope, receive, send)
        client = (scope.get("auth") or {}).get("client")
        if self.paths[scope["path"]] is REST:
            wait = self.limiter.admit(client) if client else None
            if wait is not None:
                return await self.respond(send, self.rest_error(client, wait), wait)
            return await self.app(scope, receive, send)
        body, more = b"", True
        while more:
            message = await receive()
            body += message.get("body", b"")
            more = message.get("more_body", False)
        try:
            request = json.loads(body)
        except ValueError:
            request = None
        if isinstance(request, dict) and request.get("method") in self.paths[scope["path"]] and client:
            wait = self.limiter.admit(client)
            if wait is not None:
                return await self.respond(send, self.rpc_error(request.get("id"), client, wait), wait)
        replayed = False

        async def replay():
            nonlocal replayed
            if replayed:
                return await receive()
            replayed = True
            return {"type": "http.request", "body": body, "more_body": False}

        return await self.app(scope, replay, send)

    def text(self, client, wait):
        limit = self.limiter.limits.per_hour(client)
        return (f"Refused: this client has sent {limit} reviews in the last hour, its limit. "
                f"Send again in {wait} seconds."), {"error": "rate-limited", "limitPerHour": limit,
                                                    "retryAfterSeconds": wait}

    def rpc_error(self, id_, client, wait):
        message, data = self.text(client, wait)
        return {"jsonrpc": "2.0", "id": id_, "error": {"code": RATE_LIMITED, "message": message, "data": data}}

    def rest_error(self, client, wait):
        """A2A's REST error, whose ErrorInfo metadata holds strings."""
        message, data = self.text(client, wait)
        info = {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "RATE_LIMITED", "domain": "hive-a2a",
                "metadata": {k: str(v) for k, v in data.items()}}
        return {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": message, "details": [info]}}

    async def respond(self, send, payload, wait):
        body = json.dumps(payload).encode()
        await send({"type": "http.response.start", "status": 429,
                    "headers": [(b"content-type", b"application/json"), (b"retry-after", str(wait).encode()),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


def allowance(config, client):
    """A check for Ledger.reserve: a Refusal when reserving usd would take client past its
    allowance, or, for a client without one of its own, the clients without one past the
    part of the ceiling the others' allowances leave them."""
    limits, ceiling = config.limits, config.monthly_ceiling_usd
    own = limits.named()

    def check(ledger, usd, at):
        month, resumes = month_of(at), next_month(at)
        share = own[client].share if client in own else limits.client_share
        used = ledger.client_committed(client, at)
        if used + usd > share * ceiling:
            return Refusal(month, used, round(share * ceiling, 6), resumes, usd, limit="client")
        if client in own:
            return None
        # Everything that isn't spent or reserved by a client with its own allowance draws on
        # what those allowances leave, so none of them is ever reached into.
        left = ceiling * (1 - sum(c.share for c in own.values()))
        others = ledger.committed(at) - sum(ledger.client_committed(c, at) for c in own)
        if others + usd > left + 1e-9:
            return Refusal(month, others, round(left, 6), resumes, usd, limit="shared")
        return None

    return check
