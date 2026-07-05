from fastapi import FastAPI, HTTPException

app = FastAPI()

fake_orders = {
    1: {"id": 1, "product_id": 1, "quantity": 2, "status": "shipped"},
    2: {"id": 2, "product_id": 3, "quantity": 1, "status": "pending"},
    3: {"id": 3, "product_id": 2, "quantity": 5, "status": "delivered"},
}


@app.get("/orders")
async def list_orders():
    return list(fake_orders.values())


@app.get("/orders/{order_id}")
async def get_order(order_id: int):
    order = fake_orders.get(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order