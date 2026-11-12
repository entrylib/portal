"""Per-address rate limits in the app (design §8): a token bucket per client address and kind of request.

    limiter.take(address, kind) -> None if allowed, else the seconds to wait before retrying

The buckets live in memory: the app runs as one process, and a restart (daily, design §10) only forgets them. A
request with no address (the test client) is not limited. Cloudflare limits at the edge as well; these limits know
what a request costs.
"""

import ipaddress
import json
import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Limit:
    count: int          # requests allowed in a burst ...
    seconds: int        # ... refilled evenly over this many seconds

    def describe(self):
        unit = {60: "minute", 3600: "hour", 86400: "day"}.get(self.seconds, f"{self.seconds} seconds")
        return f"{self.count} per {unit}"


#: The limits per address (initial values, design §8).
LIMITS = {
    "read": Limit(120, 60),         # search, submission status, every MCP request
    "validate": Limit(30, 3600),    # POST /api/validate, MCP validate and score
    "submit": Limit(20, 3600),      # POST /api/submissions, MCP submit
    "fetch": Limit(10, 3600),       # submission by URL: the server downloads up to 210 MB
    "upload": Limit(10, 3600),      # MCP upload_url, each file sent to an upload address, a package attached at consent
    "request": Limit(10, 3600),     # POST /removal: retraction and removal requests
}

#: Buckets kept before full ones are dropped.
MAX_BUCKETS = 100_000


class RateLimited(Exception):
    def __init__(self, kind, limit, retry_after):
        super().__init__(f"too many {kind} requests from this address: at most {limit.describe()}; retry in "
                         f"{retry_after} seconds")
        self.retry_after = retry_after


class Limiter:
    def __init__(self, limits=None, clock=time.monotonic):
        self.limits = dict(LIMITS if limits is None else limits)
        self.clock = clock
        self._buckets = {}
        self._lock = threading.Lock()

    def take(self, address, kind):
        """Spend one request of `kind` for `address`. None if allowed, else whole seconds until one is."""
        limit = self.limits.get(kind)
        if address is None or limit is None:
            return None
        rate = limit.count / limit.seconds
        now = self.clock()
        with self._lock:
            tokens, last = self._buckets.get((kind, address), (limit.count, now))
            tokens = min(limit.count, tokens + (now - last) * rate)
            if tokens < 1:
                self._buckets[(kind, address)] = (tokens, now)
                return max(1, int((1 - tokens) / rate + 0.999))
            self._buckets[(kind, address)] = (tokens - 1, now)
            if len(self._buckets) > MAX_BUCKETS:
                self._prune(now)
        return None

    def check(self, address, kind):
        """take(), raising RateLimited when the request is over the limit."""
        wait = self.take(address, kind)
        if wait is not None:
            raise RateLimited(kind, self.limits[kind], wait)

    def _prune(self, now):
        for key, (tokens, last) in list(self._buckets.items()):
            limit = self.limits[key[0]]
            if tokens + (now - last) * limit.count / limit.seconds >= limit.count:
                del self._buckets[key]


def kind_of(method, path):
    """Which limit an HTTP request counts against, or None (pages, consent, health)."""
    if path == "/mcp" or path.startswith("/mcp/"):
        return "read"
    if method == "GET" and (path.startswith("/api/search/") or path.startswith("/api/submissions/")):
        return "read"
    if method in ("PUT", "POST") and path.startswith("/api/uploads/"):
        return "upload"
    attach = path == "/confirm/package" or (path.startswith("/consent/") and path.endswith("/package"))
    if method == "POST" and attach:                         # a package attached at consent (design §4.4)
        return "upload"
    if method == "POST":
        return {"/api/validate": "validate", "/api/submissions": "submit",
                "/api/submissions/from-url": "fetch", "/removal": "request"}.get(path)
    return None


class RateLimitMiddleware:
    """ASGI middleware applying the limiter to HTTP requests by kind_of; answers 429 with Retry-After."""

    def __init__(self, app, limiter):
        self.app, self.limiter = app, limiter

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            kind = kind_of(scope["method"], scope["path"])
            address = _address(scope)
            if kind:
                wait = self.limiter.take(address, kind)
                if wait is not None:
                    return await _too_many(send, RateLimited(kind, self.limiter.limits[kind], wait))
        await self.app(scope, receive, send)


def _address(scope):
    client = scope.get("client")
    try:
        return str(ipaddress.ip_address(client[0])) if client else None
    except ValueError:                                      # not an address (the test client): not limited
        return None


async def _too_many(send, exc):
    body = json.dumps({"error": str(exc), "errors": [], "warnings": []}).encode()
    await send({"type": "http.response.start", "status": 429,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                            (b"retry-after", str(exc.retry_after).encode())]})
    await send({"type": "http.response.body", "body": body})
