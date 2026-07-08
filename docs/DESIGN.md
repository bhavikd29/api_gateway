# Design Notes

The reasoning behind the gateway's main design decisions — the *why* and the
trade-offs, not just what was built. Drawn from the project's DEVLOG.

---

## 1. Problem & architecture overview

The gateway is a **reverse proxy**: every client request hits it first, and it
runs a short pipeline before (optionally) forwarding to a backend service.

```
client → [ rate limit? ] → [ resolve service ] → [ cache? ] → [ forward ] → backend
              │ 429                   │ 404            │ HIT ↑
              ▼                       ▼            (return cached)
```

**Pipeline order is deliberate:**
1. **Rate limit first** — reject over-limit clients with `429` *before* spending
   any work on them (no routing, no cache lookup, no backend call).
2. **Resolve the service** — map the first path segment to a backend; unknown →
   `404`.
3. **Cache** — on a hit, return immediately and never touch the backend.
4. **Forward** — on a miss, proxy to the backend, cache a successful response,
   return it.

**State lives in Redis** — rate-limit counters and cached responses both — so the
gateway process itself is stateless. Backends are independent FastAPI services;
Prometheus scrapes the gateway's `/metrics` and Grafana visualizes. The whole
stack runs under Docker Compose on one network.

---

## 2. Key design decisions

### 2.1 Two rate-limiting algorithms (token bucket & sliding-window log)

**Problem:** cap how fast each client can call the gateway. The naive fixed-window
counter has a well-known flaw — at the boundary between two windows a client can
sneak through ~2× the limit.

Two algorithms are implemented, switchable via one `ALGORITHM` constant:

- **Token bucket** — a bucket holds up to `capacity` tokens and refills at
  `refill_rate`/sec; each request spends one. Because tokens build up while a
  client is quiet, it **allows short bursts (up to `capacity`) but enforces a
  steady average** over time.
- **Sliding-window log** — keeps a timestamped log of every request in the last
  `window` seconds (a Redis sorted set: member = request id, score = timestamp).
  Each request trims anything older than `now - window`, counts what's left, and
  allows if `count < limit`. Because the window always slides back from *now*,
  there's **no boundary spike** — it's the most accurate limiter.

**Trade-off:** token bucket favors burst-tolerance and is cheap (two numbers per
client); sliding-window log is exactly accurate but **O(limit) memory per client**
(it literally stores one entry per request). The log variant was chosen as the
"accurate" option over the O(1)-memory **sliding-window counter** (which
approximates with a weighted estimate) because showing the exact algorithm was
the point of the exercise. Implementing both makes the accuracy-vs-cost trade-off
concrete.

### 2.2 Atomic rate limiting via Redis Lua scripts

**Problem:** the rate-limit check is a **read → compute → write** sequence (read
the count, apply refill/trim, decide, write back). Done as separate Redis calls
(`GET` then `SET`), two requests arriving together could **both read the same
count, both decide they're fine, and both pass** — a classic race condition, and
the limiter would silently leak over its limit.

**Decision:** put the whole sequence in a **Lua script**, which Redis executes as
**one atomic step** — nothing else runs in between, so check-and-decrement can't
be interleaved. This is a step up from plain `INCR` (which is atomic but only
does a fixed-window count); a token bucket needs an atomic read-modify-write of
*two* fields together, which is exactly what Lua provides. The scripts are
registered once at startup (`register_script` → `EVALSHA`), not shipped per
request. Correctness was validated with a concurrent load test.

### 2.3 Lazy, proportional token refill

**Problem:** refilling every client's bucket on a timer wouldn't scale — you'd
need a background job touching every bucket every second.

**Decision:** refill **on read**. When a request arrives, compute
`elapsed = now - last_refill` and add `elapsed × refill_rate` tokens right then,
capped at `capacity`. No timers, no background work — a bucket that isn't touched
simply isn't refilled until its next request, and the math makes that correct.

**Related decision — pass `now` in from the app** rather than calling Redis's
`TIME` inside the script. **Trade-off:** passing the timestamp keeps the script
**deterministic** (safer for Redis replication/persistence) and **unit-testable**
(a test can inject a fake clock); the cost is that multiple gateway instances
would need roughly synced clocks (see limitations: clock skew).

### 2.4 Cache key design

The gateway uses a **read-through** cache: check Redis first; on a hit return the
stored body (backend never touched, `X-Cache: HIT`); on a miss, forward, cache a
successful (200) response with a TTL, and return it (`X-Cache: MISS`).

**The key is `cache:<path>` + the query string** — and getting there fixed a real
**correctness bug**. Keying on path *only* meant `/products?sort=asc` and
`?sort=desc` shared one entry and served each other's bodies. Two coupled fixes:

1. Append `request.url.query` to the cache key, so query variants cache
   separately.
2. **Forward the query string to the backend too** — otherwise the backend would
   ignore it and every variant would cache the *same* body under different keys.

So the cache key and the backend URL now vary **in lockstep**. Other choices: the
`cache:` prefix keeps cache keys from colliding with `rate_limit:*` keys in the
same Redis instance; only **200s are cached** (caching a transient error would
keep serving it for the whole TTL); and `is_cacheable` is GET-only (a no-op today
since the route is GET-only, kept to document intent).

**Trade-off:** a single global 30s TTL trades freshness for speed uniformly —
simple to reason about, but real systems tune TTL per route (a static product
list vs. a live balance).

### 2.5 The deferred circuit breaker (a conscious scoping decision)

A circuit breaker was **designed but deliberately not implemented** — a scoping
decision, not an oversight. The failure point is already identified: the
`await client.get(target_url)` backend call. If a backend is down, that line
raises a `ConnectionError` and the request 500s; the circuit breaker is what would
**wrap that exact call** — tracking failures, "opening" to fail fast when a
backend is unhealthy, and "half-opening" to probe recovery. It was scoped out to
prioritize finishing observability and containerization. The open design question
left for it is the **fail-open vs. fail-closed** policy when the breaker trips.

---

## 3. Known limitations

Documented deliberately — conscious scoping decisions, not missed work:

**Rate limiting**
- **Sync Redis client inside an async handler** — the blocking `redis.Redis`
  client is called from `async def`, so under load it blocks the event loop
  (undermining the async concurrency win). Would move to `redis.asyncio`.
- **One global limit for everyone** — `CAPACITY`/`REFILL_RATE` are module
  constants; a real gateway sets limits per API key / plan / route.
- **Keyed by client IP** — imperfect (shared IPs, changing IPs); would key on an
  API key once auth exists.
- **Clock skew across instances** — the flip side of passing `now` from the app;
  only bites with more than one gateway process.
- **No typo guard on `ALGORITHM`** — an unknown value silently falls through to
  the sliding-window branch.
- **Sliding-window log memory** — O(limit) entries per active client; the counter
  variant is the escape hatch if it ever matters.

**Caching**
- **Query params not normalized** — `?a=1&b=2` and `?b=2&a=1` produce different
  keys → avoidable misses; would canonicalize by sorting params.
- **No active invalidation** — entries only leave by TTL expiry; a write that
  changes underlying data won't bust a stale cache (benign while everything is
  read-only GETs).
- **`X-Cache: MISS` on non-200s** — a 404 is labeled `MISS` though it's really
  "not cacheable"; cosmetic.

**Proxying / general**
- **Circuit breaker not implemented** (see 2.5).
- **GET-only forwarding** — generalizing to all HTTP methods is a straightforward
  extension.
- **Backend status codes not relayed** — the gateway returns bodies as 200s;
  currently benign because only 200s are cached.
