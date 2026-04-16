import logging
from datetime import datetime, timezone
from uuid import UUID

import httpx
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Payment

log = logging.getLogger(__name__)


class WebhookDeliverer:
    def __init__(self):
        self.settings = get_settings()
        self.http_client = httpx.AsyncClient(timeout=self.settings.webhook_timeout_s)

    async def deliver_webhook(self, session: AsyncSession, payment: Payment) -> None:
        if payment.webhook_delivered_at is not None:
            return

        payload = {
            "event_id": str(payment.id),
            "payment_id": str(payment.id),
            "status": payment.status,
            "amount": str(payment.amount),
            "currency": payment.currency,
            "description": payment.description,
            "metadata": payment.meta,
            "failure_reason": payment.failure_reason,
            "processed_at": payment.processed_at.isoformat() if payment.processed_at else None,
        }

        response = await self.http_client.post(payment.webhook_url, json=payload)
        response.raise_for_status()

        await session.execute(
            update(Payment)
            .where(Payment.id == payment.id)
            .values(
                webhook_delivered_at=datetime.now(timezone.utc),
                webhook_attempts=Payment.webhook_attempts + 1,
                webhook_last_error=None,
            )
        )
        await session.commit()

    async def record_webhook_error(
        self, session: AsyncSession, payment_id: UUID, error_msg: str
    ) -> None:
        await session.execute(
            update(Payment)
            .where(Payment.id == payment_id)
            .values(
                webhook_attempts=Payment.webhook_attempts + 1,
                webhook_last_error=error_msg,
            )
        )
        await session.commit()
