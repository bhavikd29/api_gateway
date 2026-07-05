from fastapi import FastAPI, HTTPException
import httpx

app = FastAPI()

# ---------- Routing table ----------
SERVICES = {
    "users": "http://localhost:8001",
    "orders": "http://localhost:8002",
    "products": "http://localhost:8003",
}


@app.get("/{full_path:path}")
async def gateway(full_path: str):
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