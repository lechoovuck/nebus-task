import logging
from uuid import UUID

import aio_pika
from faststream import Context
from faststream.rabbit import RabbitBroker, RabbitMessage, RabbitQueue
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import Payment
from app.services.payments import PaymentProcessor
from app.services.webhook import WebhookDeliverer

log = logging.getLogger(__name__)


MAIN_EXCHANGE = "payments"
DLX_EXCHANGE = "payments.dlx"
MAIN_QUEUE = "payments.new"
RETRY_5S_QUEUE = "payments.retry.5s"
RETRY_15S_QUEUE = "payments.retry.15s"
DLQ = "payments.dlq"

MAX_ATTEMPTS = 3


class PaymentConsumer:
    def __init__(self, broker: RabbitBroker):
        self.settings = get_settings()
        self.broker = broker
        self.engine = create_async_engine(self.settings.database_url, future=True)
        self.SessionLocal = async_sessionmaker(self.engine, expire_on_commit=False)
        self.processor = PaymentProcessor()
        self.deliverer = WebhookDeliverer()

    async def process_payment(
        self,
        body: dict,
        message: RabbitMessage = Context(),
    ) -> None:
        payment_id_str = body.get("payment_id")
        attempt = int(message.headers.get("x-attempt", 1))

        if not payment_id_str:
            log.error("message has no payment_id: %r", body)
            await message.reject(requeue=False)
            return

        try:
            payment_id = UUID(payment_id_str)
        except (ValueError, TypeError):
            log.error("bad payment_id %r", payment_id_str)
            await message.reject(requeue=False)
            return

        try:
            await self._process_and_deliver(payment_id)
            await message.ack()
        except Exception as exc:
            log.exception("payment %s failed on attempt %s", payment_id_str, attempt)
            await self._handle_error(payment_id_str, attempt, message, str(exc))

    async def _process_and_deliver(self, payment_id: UUID) -> None:
        async with self.SessionLocal() as session:
            payment = (
                await session.execute(
                    select(Payment).where(Payment.id == payment_id).with_for_update()
                )
            ).scalar_one_or_none()

            if not payment:
                log.warning("payment %s not found", payment_id)
                return

            if payment.webhook_delivered_at is not None:
                return

            await self.processor.process_payment(session, payment)

            await session.execute(
                update(Payment)
                .where(Payment.id == payment_id)
                .values(
                    status=payment.status,
                    failure_reason=payment.failure_reason,
                    processed_at=payment.processed_at,
                )
            )
            await session.commit()

        async with self.SessionLocal() as session:
            payment = (
                await session.execute(select(Payment).where(Payment.id == payment_id))
            ).scalar_one()
            await self.deliverer.deliver_webhook(session, payment)

    async def _handle_error(
        self,
        payment_id_str: str,
        attempt: int,
        message: RabbitMessage,
        error_msg: str,
    ) -> None:
        try:
            async with self.SessionLocal() as session:
                await self.deliverer.record_webhook_error(
                    session, UUID(payment_id_str), error_msg
                )
        except Exception:
            log.exception("could not record webhook error for %s", payment_id_str)

        if attempt >= MAX_ATTEMPTS:
            await message.reject(requeue=False)
            return

        next_attempt = attempt + 1
        retry_queue = RETRY_5S_QUEUE if next_attempt == 2 else RETRY_15S_QUEUE

        await self.broker.publish(
            message=message.body,
            queue=retry_queue,
            message_id=str(message.message_id),
            headers={**message.headers, "x-attempt": next_attempt},
            persist=True,
        )
        await message.ack()


def main_queue() -> RabbitQueue:
    return RabbitQueue(
        MAIN_QUEUE,
        durable=True,
        routing_key=MAIN_QUEUE,
        arguments={
            "x-dead-letter-exchange": DLX_EXCHANGE,
            "x-dead-letter-routing-key": DLQ,
        },
    )


async def declare_topology(rabbit_url: str) -> None:
    connection = await aio_pika.connect_robust(rabbit_url)
    try:
        channel = await connection.channel()

        main_ex = await channel.declare_exchange(
            MAIN_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True
        )
        dlx_ex = await channel.declare_exchange(
            DLX_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True
        )

        main_q = await channel.declare_queue(
            MAIN_QUEUE,
            durable=True,
            arguments={
                "x-dead-letter-exchange": DLX_EXCHANGE,
                "x-dead-letter-routing-key": DLQ,
            },
        )
        await main_q.bind(main_ex, routing_key=MAIN_QUEUE)

        for name, ttl in ((RETRY_5S_QUEUE, 5000), (RETRY_15S_QUEUE, 15000)):
            await channel.declare_queue(
                name,
                durable=True,
                arguments={
                    "x-message-ttl": ttl,
                    "x-dead-letter-exchange": MAIN_EXCHANGE,
                    "x-dead-letter-routing-key": MAIN_QUEUE,
                },
            )

        dlq_q = await channel.declare_queue(DLQ, durable=True)
        await dlq_q.bind(dlx_ex, routing_key=DLQ)
    finally:
        await connection.close()
