import json
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Payment
from app.services.webhook import WebhookDeliverer


def _payment(**overrides):
    defaults = dict(
        id=uuid4(),
        idempotency_key=f"k-{uuid4()}",
        request_fingerprint="fp",
        amount=Decimal("100.00"),
        currency="RUB",
        description="test",
        meta={},
        webhook_url="https://receiver.example/webhook",
        status="succeeded",
        processed_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return Payment(**defaults)


def _deliverer(handler):
    d = WebhookDeliverer()
    d.http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return d


@pytest.mark.asyncio
async def test_webhook_ok(async_session: AsyncSession):
    received = []

    def handler(req):
        received.append(req)
        return httpx.Response(200)

    d = _deliverer(handler)
    p = _payment()
    async_session.add(p)
    await async_session.commit()

    await d.deliver_webhook(async_session, p)
    fetched = (
        await async_session.execute(select(Payment).where(Payment.id == p.id))
    ).scalar_one()
    assert fetched.webhook_delivered_at is not None
    assert fetched.webhook_attempts == 1
    assert fetched.webhook_last_error is None
    assert len(received) == 1


@pytest.mark.asyncio
async def test_webhook_5xx(async_session: AsyncSession):
    d = _deliverer(lambda req: httpx.Response(503))
    p = _payment()
    async_session.add(p)
    await async_session.commit()

    with pytest.raises(httpx.HTTPStatusError):
        await d.deliver_webhook(async_session, p)

    fetched = (
        await async_session.execute(select(Payment).where(Payment.id == p.id))
    ).scalar_one()
    assert fetched.webhook_delivered_at is None


@pytest.mark.asyncio
async def test_noop_if_delivered(async_session: AsyncSession):
    called = {"n": 0}

    def handler(req):
        called["n"] += 1
        return httpx.Response(200)

    d = _deliverer(handler)
    p = _payment(webhook_delivered_at=datetime.now(timezone.utc), webhook_attempts=1)
    async_session.add(p)
    await async_session.commit()

    await d.deliver_webhook(async_session, p)
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_record_error(async_session: AsyncSession):
    p = _payment()
    async_session.add(p)
    await async_session.commit()

    d = WebhookDeliverer()
    await d.record_webhook_error(async_session, p.id, "Connection timeout")
    await d.record_webhook_error(async_session, p.id, "Connection timeout")

    fetched = (
        await async_session.execute(select(Payment).where(Payment.id == p.id))
    ).scalar_one()
    assert fetched.webhook_attempts == 2
    assert fetched.webhook_last_error == "Connection timeout"


@pytest.mark.asyncio
async def test_payload_fields(async_session: AsyncSession):
    captured = {}

    def handler(req):
        captured["body"] = req.content
        return httpx.Response(200)

    d = _deliverer(handler)
    p = _payment(status="succeeded", description="Order #1")
    async_session.add(p)
    await async_session.commit()

    await d.deliver_webhook(async_session, p)

    body = json.loads(captured["body"])
    assert body["payment_id"] == str(p.id)
    assert body["event_id"] == str(p.id)
    assert body["status"] == "succeeded"
    assert body["amount"] == "100.00"
    assert body["currency"] == "RUB"
