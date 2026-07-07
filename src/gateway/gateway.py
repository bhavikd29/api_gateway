from fastapi import FastAPI, HTTPException, Request
import httpx
import redis
import os
import time
import uuid

app = FastAPI()

# ---------- Routing table ----------
SERVICES = {
    "users": "http://localhost:8001",
    "orders": "http://localhost:8002",
    "products": "http://localhost:8003",
}

r = redis.Redis(host="localhost", port=6379)

# ---------- Rate limiter ----------
# Which algorithm is active: "token_bucket" or "sliding_window".
ALGORITHM = "token_bucket"

# Load and register both Lua scripts once at startup.
def _load_script(filename):
    path = os.path.join(os.path.dirname(__file__), filename)
    with open(path) as f:
        return r.register_script(f.read())

_token_bucket = _load_script("token_bucket.lua")
_sliding_window = _load_script("sliding_window.lua")

# Token-bucket config
CAPACITY = 10        # bucket holds up to 10 tokens
REFILL_RATE = 1.0    # 1 token/sec sustained, bursts up to CAPACITY

# Sliding-window config
WINDOW = 60          # window size in seconds
LIMIT = 100          # max requests per window

@app.get("/{full_path:path}")
async def gateway(full_path: str, request: Request):
    client_ip = request.client.host
    now = time.time()

    if ALGORITHM == "token_bucket":
        key = f"rate_limit:tb:{client_ip}"
        allowed, retry_after = _token_bucket(
            keys=[key],
            args=[CAPACITY, REFILL_RATE, now, 1],
        )
    else:  # sliding_window
        key = f"rate_limit:sw:{client_ip}"
        req_id = str(uuid.uuid4())
        allowed, retry_after = _sliding_window(
            keys=[key],
            args=[now, WINDOW, LIMIT, req_id],
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