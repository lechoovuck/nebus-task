import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import Outbox

log = logging.getLogger(__name__)


class OutboxRelay:
    def __init__(self, broker):
        self.settings = get_settings()
        self.broker = broker
        self.engine = create_async_engine(self.settings.database_url, future=True)
        self.SessionLocal = async_sessionmaker(self.engine, expire_on_commit=False)

    async def run(self) -> None:
        while True:
            try:
                await self.publish_unpublished_events()
            except Exception:
                log.exception("outbox relay iteration failed")
            await asyncio.sleep(self.settings.outbox_poll_interval_s)

    async def publish_unpublished_events(self) -> None:
        async with self.SessionLocal() as session:
            q = (
                select(Outbox.id)
                .where(Outbox.published_at.is_(None))
                .order_by(Outbox.created_at)
                .limit(self.settings.outbox_batch_size)
                .with_for_update(skip_locked=True)
            )
            event_ids = [row[0] for row in (await session.execute(q)).fetchall()]

        for event_id in event_ids:
            await self._publish_and_mark_event(event_id)

    async def _publish_and_mark_event(self, event_id) -> None:
        async with self.SessionLocal() as session:
            q = (
                select(Outbox)
                .where(Outbox.id == event_id, Outbox.published_at.is_(None))
                .with_for_update()
            )
            event = (await session.execute(q)).scalar_one_or_none()
            if not event:
                return

            try:
                await self.broker.publish(
                    message=json.dumps(event.payload),
                    queue=event.topic,
                    message_id=str(event.id),
                    headers={"x-attempt": 1},
                    persist=True,
                )
                await session.execute(
                    update(Outbox)
                    .where(Outbox.id == event_id)
                    .values(published_at=datetime.now(timezone.utc))
                )
                await session.commit()
            except Exception as e:
                log.warning("outbox publish failed for %s: %s", event_id, e)
                await session.execute(
                    update(Outbox)
                    .where(Outbox.id == event_id)
                    .values(
                        publish_attempts=Outbox.publish_attempts + 1,
                        last_error=str(e),
                    )
                )
                await session.commit()
