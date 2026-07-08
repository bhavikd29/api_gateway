"""Shared test setup: import path, Redis cleanup, and the backend mock.

These are integration tests — they run against a REAL Redis (the whole point of
the atomicity test is that the Lua script executes atomically for real). The
backend HTTP calls, however, are mocked, so the tests exercise the gateway's own
logic without needing the backend services up.
"""

import os
import sys

import pytest

# The gateway lives at src/gateway/gateway.py. Put src/ on the import path so
# `from gateway.gateway import app` works when pytest runs from the project root.
SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, SRC)

import httpx

from gateway.gateway import r  # the gateway's Redis client — we reuse it to clean up


@pytest.fixture(autouse=True)
def clean_redis():
    """Before every test, wipe ONLY the gateway's keys so tests don't leak into
    each other (a leftover token bucket or cached body would break the next test).
    If Redis isn't running, skip the suite with a clear message rather than error."""
    try:
        r.ping()
    except Exception:
        pytest.skip("these tests need a running Redis on localhost:6379")
    for pattern in ("rate_limit:*", "cache:*"):
        for key in r.scan_iter(pattern):
            r.delete(key)
    yield


class FakeResponse:
    """A stand-in for the httpx.Response the gateway gets back from a backend."""

    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data


@pytest.fixture
def mock_backend(monkeypatch):
    """Replace the gateway's backend call (`httpx.AsyncClient.get`) with a fake.

    Returns a list that records every URL the gateway tried to fetch, so a test
    can assert *which* backend was called and *how many times* (e.g. a cache hit
    means the backend is NOT called again).

    Note: this patches the ASYNC client the gateway uses to reach backends. The
    TestClient that drives the app uses the SYNC httpx.Client, so it's unaffected —
    no clash between "driving the app" and "mocking the backend".
    """
    calls = []

    async def fake_get(self, url, *args, **kwargs):
        calls.append(str(url))
        return FakeResponse({"mocked": True, "url": str(url)})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    return calls
