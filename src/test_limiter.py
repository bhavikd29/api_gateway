import httpx, time

URL = "http://127.0.0.1:8000/products"

for i in range(15):
    resp = httpx.get(URL)
    retry = resp.headers.get("Retry-After", "-")
    print(f"{i+1:2d}: {resp.status_code}  Retry-After={retry}")

print("waiting 2s for refill...")
time.sleep(2)

resp = httpx.get(URL)
print(f"after wait: {resp.status_code}")