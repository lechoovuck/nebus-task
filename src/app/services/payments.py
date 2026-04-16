import asyncio
import random
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Payment


class PaymentProcessor:
    def __init__(self):
        self.settings = get_settings()

    async def process_payment(self, session: AsyncSession, payment: Payment) -> None:
        if payment.processed_at is not None:
            return

        await asyncio.sleep(random.uniform(2, 5))

        if random.random() < self.settings.gateway_success_rate:
            payment.status = "succeeded"
            payment.failure_reason = None
        else:
            payment.status = "failed"
            payment.failure_reason = "gateway_declined"

        payment.processed_at = datetime.now(timezone.utc)
