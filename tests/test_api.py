from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Outbox, Payment

API_KEY = "test-api-key-change-in-prod"


def _body(**overrides):
    body = {
        "amount": "100.00",
        "currency": "RUB",
        "description": "t-shirt",
        "metadata": {"order_id": "123"},
        "webhook_url": "https://example.com/webhook",
    }
    body.update(overrides)
    return body


def _headers(idem, api_key=API_KEY):
    h = {"Idempotency-Key": idem}
    if api_key is not None:
        h["X-API-Key"] = api_key
    return h


@pytest.mark.asyncio
async def test_create_payment(client: AsyncClient, async_session: AsyncSession):
    r = await client.post("/api/v1/payments", json=_body(), headers=_headers("k1"))
    assert r.status_code == 202
    data = r.json()
    assert data["status"] == "pending"

    pid = UUID(data["payment_id"])
    payment = (
        await async_session.execute(select(Payment).where(Payment.id == pid))
    ).scalar_one()
    assert payment.amount == Decimal("100.00")
    assert payment.idempotency_key == "k1"

    outbox = (
        await async_session.execute(select(Outbox).where(Outbox.aggregate_id == pid))
    ).scalar_one()
    assert outbox.topic == "payments.new"
    assert outbox.published_at is None


@pytest.mark.asyncio
async def test_idempotent_duplicate(client: AsyncClient):
    body = _body()
    h = _headers("k2")
    first = (await client.post("/api/v1/payments", json=body, headers=h)).json()
    second = (await client.post("/api/v1/payments", json=body, headers=h)).json()
    assert first["payment_id"] == second["payment_id"]


@pytest.mark.asyncio
async def test_idempotent_conflict(client: AsyncClient):
    h = _headers("k3")
    await client.post("/api/v1/payments", json=_body(amount="100.00"), headers=h)
    r = await client.post("/api/v1/payments", json=_body(amount="200.00"), headers=h)
    assert r.status_code == 409


@pytest.mark.parametrize("api_key", [None, "wrong"])
@pytest.mark.asyncio
async def test_unauthorized(client: AsyncClient, api_key):
    r = await client.post(
        "/api/v1/payments", json=_body(), headers=_headers("k4", api_key=api_key)
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_get_payment(client: AsyncClient):
    created = (
        await client.post("/api/v1/payments", json=_body(), headers=_headers("k5"))
    ).json()

    r = await client.get(
        f"/api/v1/payments/{created['payment_id']}",
        headers={"X-API-Key": API_KEY},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["payment_id"] == created["payment_id"]
    assert Decimal(data["amount"]) == Decimal("100.00")
    assert data["status"] == "pending"


@pytest.mark.asyncio
async def test_get_missing(client: AsyncClient):
    r = await client.get(f"/api/v1/payments/{uuid4()}", headers={"X-API-Key": API_KEY})
    assert r.status_code == 404
