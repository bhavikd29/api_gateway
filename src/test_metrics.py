"""
Manual tester for the /metrics endpoint.

What it does:
  1. Scrapes /metrics once to get a baseline.
  2. Fires some traffic through the gateway (a known route, an unknown
     service -> 404, and a burst to try to trip the rate limiter -> 429).
  3. Scrapes /metrics again and prints the gateway_* lines so you can eyeball
     that the counters moved.

Prereqs: gateway running on localhost:8000 (and Redis up for rate limiting).
Run:     python scripts/test_metrics.py
"""

import httpx

BASE = "http://localhost:8000"


def scrape():
    """Fetch the raw Prometheus exposition text from /metrics."""
    return httpx.get(f"{BASE}/metrics").text


def gateway_lines(text):
    """Keep only our own metrics (drop python_* / process_* noise)."""
    return [ln for ln in text.splitlines()
            if ln.startswith("gateway_") and not ln.startswith("#")]


def main():
    print("=== BEFORE ===")
    before = scrape()
    for ln in gateway_lines(before):
        print(ln)

    # --- generate some traffic ---
    # A known service (may 200 if its backend is up, else whatever it returns).
    httpx.get(f"{BASE}/products/1")
    # An unknown service -> should be a 404, still counted by the middleware.
    httpx.get(f"{BASE}/nope/1")
    # A burst to try to trip the rate limiter -> some of these should 429.
    for _ in range(30):
        httpx.get(f"{BASE}/products/1")

    print("\n=== AFTER ===")
    after = scrape()
    for ln in gateway_lines(after):
        print(ln)

    # --- quick assertions so a failure is obvious ---
    assert "gateway_requests_total" in after, "requests counter missing"
    assert "gateway_request_duration_seconds" in after, "duration histogram missing"
    print("\nOK: /metrics responded and gateway_* metrics are present.")


if __name__ == "__main__":
    main()
