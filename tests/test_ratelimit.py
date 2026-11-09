"""Per-address rate limits (design §8)."""

import json

import pytest
from fastapi.testclient import TestClient
from publishing import example

from portal import fetch, ratelimit
from portal.app import create_app
from portal.db import make_pool, migrate
from portal.ratelimit import Limit, Limiter


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_bucket():
    clock = Clock()
    lim = Limiter({"read": Limit(3, 60)}, clock)
    assert [lim.take("203.0.113.5", "read") for _ in range(3)] == [None, None, None]
    assert lim.take("203.0.113.5", "read") == 20                 # one request every 20 seconds
    assert lim.take("198.51.100.7", "read") is None              # another address has its own bucket
    clock.now += 20
    assert lim.take("203.0.113.5", "read") is None
    assert lim.take("203.0.113.5", "read") is not None
    clock.now += 3600                                            # refills to the burst, no further
    assert [lim.take("203.0.113.5", "read") for _ in range(4)][-1] is not None
    assert lim.take(None, "read") is None and lim.take("203.0.113.5", "other") is None
    with pytest.raises(ratelimit.RateLimited, match="at most 3 per minute; retry in"):
        lim.check("203.0.113.5", "read")


def test_full_buckets_are_dropped(monkeypatch):
    monkeypatch.setattr(ratelimit, "MAX_BUCKETS", 10)
    clock = Clock()
    lim = Limiter({"read": Limit(2, 60)}, clock)
    for i in range(10):
        lim.take(f"203.0.113.{i}", "read")
    clock.now += 60
    lim.take("198.51.100.1", "read")
    assert list(lim._buckets) == [("read", "198.51.100.1")]


def test_kinds():
    assert ratelimit.kind_of("GET", "/api/search/claims") == "read"
    assert ratelimit.kind_of("GET", "/api/submissions/sub_x") == "read"
    assert ratelimit.kind_of("POST", "/mcp") == "read"
    assert ratelimit.kind_of("POST", "/api/validate") == "validate"
    assert ratelimit.kind_of("POST", "/api/submissions") == "submit"
    assert ratelimit.kind_of("POST", "/api/submissions/from-url") == "fetch"
    for method, path in (("GET", "/"), ("GET", "/submit"), ("GET", "/consent/x"), ("GET", "/healthz")):
        assert ratelimit.kind_of(method, path) is None


@pytest.fixture
def limited(settings):
    """The app seen from two addresses, with small limits."""
    migrate(settings.database_url)
    pool = make_pool(settings.database_url, min_size=1, max_size=3)
    pool.open()
    limiter = Limiter({"read": Limit(3, 60), "validate": Limit(1, 3600), "submit": Limit(1, 3600),
                       "fetch": Limit(1, 3600)})
    app = create_app(settings, pool=pool, run_expiry=False, limiter=limiter)
    a = TestClient(app, client=("203.0.113.5", 40000))     # no lifespan of its own: the app runs one, for b's MCP
    with TestClient(app, client=("198.51.100.7", 40000)) as b:
        yield a, b
    pool.close()


MCP = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
       "MCP-Protocol-Version": "2025-06-18"}


def test_over_http(limited):
    a, b = limited
    for _ in range(3):
        assert a.get("/api/search/claims", params={"q": "x"}).status_code == 200
    r = a.get("/api/search/claims", params={"q": "x"})
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1 and "at most 3 per minute" in r.json()["error"]
    assert a.post("/mcp", headers=MCP, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code == 429
    assert a.get("/submit").status_code == 200 and a.get("/healthz").status_code == 200   # pages are not limited
    assert b.get("/api/search/claims", params={"q": "x"}).status_code == 200
    body = json.dumps(example()).encode()
    assert b.post("/api/validate", content=body).status_code == 200
    assert b.post("/api/validate", content=body).status_code == 429


def test_costly_mcp_tools_have_their_own_limits(limited):
    _, b = limited

    def validate():
        r = b.post("/mcp", headers=MCP, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "validate", "arguments": {"claimset": example()}}})
        return r.json()["result"]
    assert not validate().get("isError")
    out = validate()
    assert out["isError"] and "too many validate requests" in out["content"][0]["text"]


def test_downloads_at_once_are_capped(limited, monkeypatch):
    a, _ = limited
    monkeypatch.setattr(fetch, "_SLOTS", __import__("threading").BoundedSemaphore(1))
    fetch._SLOTS.acquire()
    try:
        r = a.post("/api/submissions/from-url", json={"url": "https://zenodo.org/records/1/files/p.zip"})
    finally:
        fetch._SLOTS.release()
    assert r.status_code == 503 and r.headers["retry-after"] == "60" and "try again" in r.json()["error"]
