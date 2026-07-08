import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter } from 'k6/metrics';

const BASE = 'http://localhost:8000';

// Custom counters so the end-of-test summary separates these from the raw
// HTTP stats. k6 tallies whatever we .add() to them.
const rateLimited = new Counter('gateway_429s');
const cacheHits = new Counter('gateway_cache_hits');
const cacheMisses = new Counter('gateway_cache_misses');

export const options = {
  // Two named traffic patterns ("scenarios") run in the same test. Each names
  // the `exec` function it drives, so the old `default` function is now split
  // into two explicit ones below.
  scenarios: {
    // Scenario 1 — the realistic mixed benchmark.
    // ramping-vus is a CLOSED model: each VU waits for its response before
    // firing again, so throughput is capped by latency. This is why it stayed
    // UNDER 600/s and produced 0 rejections — that's fine, it's the "healthy
    // traffic" baseline.
    steady_mix: {
      executor: 'ramping-vus',
      exec: 'mixedTraffic',
      startVUs: 0,
      stages: [
        { duration: '20s', target: 20 },
        { duration: '30s', target: 50 },
        { duration: '30s', target: 50 },
        { duration: '10s', target: 0 },
      ],
      gracefulRampDown: '5s',
    },

    // Scenario 2 — the burst that trips the limiter.
    // constant-arrival-rate is an OPEN model: it launches `rate` iterations per
    // second no matter how fast the gateway replies. 1500/s offered vs the
    // gateway's 600/s ceiling => ~900/s get 429'd. Starts at 50s so on the
    // dashboard you SEE the 429 panel jump from ~0 the moment it kicks in.
    burst_single: {
      executor: 'constant-arrival-rate',
      exec: 'hammerOneEndpoint',
      startTime: '50s',        // begin mid-run, overlapping the steady hold
      duration: '30s',         // hammer for 30s
      rate: 1500,              // 1500 requests...
      timeUnit: '1s',          // ...per second (well above REFILL_RATE=600)
      preAllocatedVUs: 200,    // VUs k6 reserves up front to sustain that rate
      maxVUs: 400,             // ceiling if it needs more (429s are fast, so few)
    },
  },

  // Show p99 in the summary (default stops at p95).
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],

  thresholds: {
    http_req_duration: ['p(95)<800'],
    checks: ['rate>0.95'],
  },
};

// Weighted mix for the steady baseline. /products/1 appears 3x so it dominates
// and its cache key stays hot; all three services get exercised.
const ENDPOINTS = [
  '/products/1',
  '/products/1',
  '/products/1',
  '/users/1',
  '/orders/2',
];

// --- Scenario 1 body: realistic mixed traffic ---
export function mixedTraffic() {
  const path = ENDPOINTS[Math.floor(Math.random() * ENDPOINTS.length)];
  const res = http.get(`${BASE}${path}`);

  check(res, {
    'status 200 or 429': (r) => r.status === 200 || r.status === 429,
  });

  if (res.status === 429) rateLimited.add(1);
  if (res.headers['X-Cache'] === 'HIT') cacheHits.add(1);
  if (res.headers['X-Cache'] === 'MISS') cacheMisses.add(1);

  sleep(0.05);   // closed-model pacing; keeps each VU from spinning 100% hot
}

// --- Scenario 2 body: hammer ONE endpoint to force rate-limit 429s ---
export function hammerOneEndpoint() {
  // Same path every time (one client, one endpoint). The limiter is keyed on
  // client IP and is global, so the endpoint choice doesn't matter for 429s —
  // reusing /products/1 just keeps it a cheap cache hit when it DOES get through.
  const res = http.get(`${BASE}/products/1`);

  check(res, {
    'burst: 200 or 429': (r) => r.status === 200 || r.status === 429,
  });

  if (res.status === 429) rateLimited.add(1);
  // NOTE: no sleep() here — the constant-arrival-rate executor controls pacing.
}
