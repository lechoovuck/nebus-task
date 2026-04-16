import asyncio
import logging

from faststream.rabbit import Channel, RabbitBroker

from app.config import get_settings
from app.services.consumer import PaymentConsumer, declare_topology, main_queue
from app.services.outbox_relay import OutboxRelay

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("worker")


async def main() -> None:
    settings = get_settings()

    await declare_topology(settings.rabbit_url)

    broker = RabbitBroker(settings.rabbit_url)
    consumer = PaymentConsumer(broker)
    relay = OutboxRelay(broker)

    @broker.subscriber(
        main_queue(),
        channel=Channel(prefetch_count=settings.consumer_prefetch_count),
    )
    async def _handle(body: dict) -> None:
        await consumer.process_payment(body)

    log.info("starting worker")
    try:
        async with broker:
            await broker.start()
            await asyncio.gather(asyncio.Event().wait(), relay.run())
    finally:
        await consumer.engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
