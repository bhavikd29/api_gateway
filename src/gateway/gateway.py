from fastapi import FastAPI, HTTPException, Request
import httpx
import redis
import os
import time

app = FastAPI()

# ---------- Routing table ----------
SERVICES = {
    "users": "http://localhost:8001",
    "orders": "http://localhost:8002",
    "products": "http://localhost:8003",
}

r = redis.Redis(host="localhost", port=6379)

# ---------- Rate limiter ----------
# Load and register the token-bucket Lua script once at startup.
_LUA_PATH = os.path.join(os.path.dirname(__file__), "token_bucket.lua")
with open(_LUA_PATH) as f:
    _token_bucket = r.register_script(f.read())

CAPACITY = 10        # bucket holds up to 10 tokens
REFILL_RATE = 1.0    # 1 token/sec sustained, bursts up to CAPACITY

@app.get("/{full_path:path}")
async def gateway(full_path: str, request: Request):
    client_ip = request.client.host
    key = f"rate_limit:{client_ip}"

    allowed, tokens_left, retry_after = _token_bucket(
        keys=[key],
        args=[CAPACITY, REFILL_RATE, time.time(), 1],
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )

    service_name = full_path.split("/")[0]
    # 1. Is this a service we know about?
    base_url = SERVICES.get(service_name)
    if base_url is None:
        raise HTTPException(status_code=404, detail=f"Unknown service: {service_name}")

    # 2. Forward the request to that backend
    target_url = f"{base_url}/{full_path}"
    async with httpx.AsyncClient() as client:
        response = await client.get(target_url)

    # 3. Return the backend's JSON back to the caller
    return response.json()