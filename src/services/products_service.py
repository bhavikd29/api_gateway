from fastapi import FastAPI, HTTPException

app = FastAPI()

fake_products = {
    1: {"id": 1, "name": "Keyboard", "price": 49.99},
    2: {"id": 2, "name": "Mouse", "price": 19.99},
    3: {"id": 3, "name": "Monitor", "price": 199.99},
}


@app.get("/products")
async def list_products():
    return list(fake_products.values())


@app.get("/products/{product_id}")
async def get_product(product_id: int):
    product = fake_products.get(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product