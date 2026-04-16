from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Outbox
from app.services.outbox_relay import OutboxRelay


@pytest.fixture
def relay(async_engine):
    r = OutboxRelay.__new__(OutboxRelay)
    r.settings = type("S", (), {"outbox_poll_interval_s": 0.01, "outbox_batch_size": 100})()
    r.broker = AsyncMock()
    r.engine = async_engine
    r.SessionLocal = async_sessionmaker(async_engine, expire_on_commit=False)
    return r


@pytest.mark.asyncio
async def test_publish_batch(async_session: AsyncSession, relay):
    agg = uuid4()
    for i in range(3):
        async_session.add(
            Outbox(
                topic="payments.new",
                aggregate_id=agg,
                payload={"payment_id": str(agg), "n": i},
            )
        )
    await async_session.commit()

    await relay.publish_unpublished_events()
    assert relay.broker.publish.await_count == 3

    async with relay.SessionLocal() as fresh:
        rows = (await fresh.execute(select(Outbox))).scalars().all()
    for row in rows:
        assert row.published_at is not None


@pytest.mark.asyncio
async def test_publish_failure(async_session: AsyncSession, relay):
    relay.broker.publish.side_effect = RuntimeError("rabbit down")

    event = Outbox(
        topic="payments.new",
        aggregate_id=uuid4(),
        payload={"payment_id": str(uuid4())},
    )
    async_session.add(event)
    await async_session.commit()

    await relay.publish_unpublished_events()

    async with relay.SessionLocal() as fresh:
        fetched = (
            await fresh.execute(select(Outbox).where(Outbox.id == event.id))
        ).scalar_one()
    assert fetched.published_at is None
    assert fetched.publish_attempts == 1
    assert "rabbit down" in fetched.last_error


@pytest.mark.asyncio
async def test_skip_published(async_session: AsyncSession, relay):
    event = Outbox(
        topic="payments.new",
        aggregate_id=uuid4(),
        payload={"payment_id": str(uuid4())},
        published_at=datetime.now(timezone.utc),
    )
    async_session.add(event)
    await async_session.commit()

    await relay.publish_unpublished_events()
    assert relay.broker.publish.await_count == 0
