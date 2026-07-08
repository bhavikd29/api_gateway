"""Gateway tests: rate-limiter atomicity, cache HIT/MISS, and routing + 404."""

import asyncio

from httpx import ASGITransport, AsyncClient
from fastapi.testclient import TestClient

from gateway.gateway import app, CAPACITY, SERVICES


# ---------------------------------------------------------------------------
# (a) Atomicity: under a simultaneous burst, the limiter lets exactly CAPACITY
#     requests through — never more. This is the property the Lua script buys us.
# ---------------------------------------------------------------------------
async def test_rate_limiter_allows_only_capacity_under_concurrency():
    N = 50  # fire far more than the bucket can hold

    # Drive the app in-process over ASGI (no network) so we can launch requests
    # truly concurrently with asyncio.gather.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        responses = await asyncio.gather(
            *(ac.get("/nonexistent/1") for _ in range(N))
        )

    statuses = [resp.status_code for resp in responses]
    allowed = [s for s in statuses if s != 429]
    denied = [s for s in statuses if s == 429]

    # The core assertion: exactly the bucket size got through, the rest were 429'd.
    # If the read-check-write weren't atomic, more than CAPACITY could slip past.
    assert len(allowed) == CAPACITY
    assert len(denied) == N - CAPACITY

    # We deliberately hit an UNKNOWN service: a request that passes the limiter
    # then 404s *before* any backend call, isolating the limiter from routing and
    # caching (no backend mock needed here).
    assert all(s == 404 for s in allowed)


# ---------------------------------------------------------------------------
# (b) Caching: first request is a MISS (backend called + response cached);
#     the second within TTL is a HIT (served from Redis, backend NOT called).
# ---------------------------------------------------------------------------
def test_cache_miss_then_hit(mock_backend):
    client = TestClient(app)

    first = client.get("/products/1")
    assert first.headers["x-cache"] == "MISS"

    second = client.get("/products/1")
    assert second.headers["x-cache"] == "HIT"

    # The hit must be served from cache — so the backend was hit exactly once.
    assert len(mock_backend) == 1


# ---------------------------------------------------------------------------
# (c) Routing: a known first path segment is forwarded to the matching backend;
#     an unknown one returns 404 without ever touching a backend.
# ---------------------------------------------------------------------------
def test_routing_and_unknown_service_404(mock_backend):
    client = TestClient(app)

    ok = client.get("/users/1")
    assert ok.status_code == 200
    # Routed to the users backend, carrying the full path.
    assert mock_backend[-1] == SERVICES["users"] + "/users/1"

    calls_before = len(mock_backend)
    missing = client.get("/nonexistent/1")
    assert missing.status_code == 404
    # An unknown service is rejected before any backend call.
    assert len(mock_backend) == calls_before
