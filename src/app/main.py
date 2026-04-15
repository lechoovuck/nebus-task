from fastapi import FastAPI

from app.api.payments import router as payments_router

app = FastAPI(title="payments", version="0.1.0")
app.include_router(payments_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
