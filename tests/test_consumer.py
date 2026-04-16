from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Payment
from app.services.payments import PaymentProcessor


def _payment(**overrides):
    defaults = dict(
        id=uuid4(),
        idempotency_key=f"k-{uuid4()}",
        request_fingerprint="fp",
        amount=Decimal("100.00"),
        currency="RUB",
        description="test",
        meta={},
        webhook_url="https://example.com/webhook",
        status="pending",
    )
    defaults.update(overrides)
    return Payment(**defaults)


@pytest.fixture
def processor(monkeypatch):
    monkeypatch.setattr("app.services.payments.random.uniform", lambda *_: 0.0)
    return PaymentProcessor()


@pytest.mark.asyncio
async def test_success(async_session: AsyncSession, monkeypatch, processor):
    monkeypatch.setattr("app.services.payments.random.random", lambda: 0.0)
    p = _payment()
    async_session.add(p)
    await async_session.commit()

    await processor.process_payment(async_session, p)
    assert p.status == "succeeded"
    assert p.failure_reason is None
    assert p.processed_at is not None


@pytest.mark.asyncio
async def test_failure(async_session: AsyncSession, monkeypatch, processor):
    monkeypatch.setattr("app.services.payments.random.random", lambda: 0.99)
    p = _payment()
    async_session.add(p)
    await async_session.commit()

    await processor.process_payment(async_session, p)
    assert p.status == "failed"
    assert p.failure_reason == "gateway_declined"


@pytest.mark.asyncio
async def test_skip_already_processed(async_session: AsyncSession, monkeypatch):
    called = {"sleep": 0}

    async def fake_sleep(_):
        called["sleep"] += 1

    monkeypatch.setattr("app.services.payments.asyncio.sleep", fake_sleep)

    p = _payment(status="succeeded", processed_at=datetime.now(timezone.utc))
    async_session.add(p)
    await async_session.commit()

    await PaymentProcessor().process_payment(async_session, p)
    assert called["sleep"] == 0


@pytest.mark.asyncio
async def test_threshold_boundary(async_session: AsyncSession, monkeypatch, processor):
    processor.settings = processor.settings.model_copy(update={"gateway_success_rate": 0.5})

    monkeypatch.setattr("app.services.payments.random.random", lambda: 0.4999)
    p1 = _payment()
    async_session.add(p1)
    await async_session.commit()
    await processor.process_payment(async_session, p1)
    assert p1.status == "succeeded"

    monkeypatch.setattr("app.services.payments.random.random", lambda: 0.5)
    p2 = _payment()
    async_session.add(p2)
    await async_session.commit()
    await processor.process_payment(async_session, p2)
    assert p2.status == "failed"
