from fastapi import FastAPI, HTTPException
import asyncio
app = FastAPI()

# Fake data — dict keyed by user id
fake_users = {
    1: {"id": 1, "name": "Alice", "email": "alice@example.com"},
    2: {"id": 2, "name": "Bob", "email": "bob@example.com"},
    3: {"id": 3, "name": "Charlie", "email": "charlie@example.com"},
}


@app.get("/users")
async def list_users():
    return list(fake_users.values())


@app.get("/users/{user_id}")
async def get_user(user_id: int):
    user = fake_users.get(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user