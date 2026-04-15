from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import declarative_base

Base = declarative_base()

CURRENCIES = ("RUB", "USD", "EUR")
STATUSES = ("pending", "succeeded", "failed")


def _in_sql(values):
    return ", ".join(f"'{v}'" for v in values)


class Payment(Base):
    __tablename__ = "payments"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    idempotency_key = Column(String(255), unique=True, nullable=False, index=True)
    request_fingerprint = Column(Text, nullable=False)

    amount = Column(Numeric(18, 4), nullable=False)
    currency = Column(String(3), nullable=False)
    description = Column(Text)
    meta = Column("metadata", JSONB, nullable=False, default=dict)
    webhook_url = Column(Text, nullable=False)

    status = Column(String(16), nullable=False, default="pending")
    failure_reason = Column(Text)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    processed_at = Column(DateTime(timezone=True))

    webhook_delivered_at = Column(DateTime(timezone=True))
    webhook_attempts = Column(Integer, nullable=False, default=0)
    webhook_last_error = Column(Text)

    __table_args__ = (
        CheckConstraint("amount > 0", name="payments_amount_positve"),
        CheckConstraint(f"currency IN ({_in_sql(CURRENCIES)})", name="payments_currency_valid"),
        CheckConstraint(f"status IN ({_in_sql(STATUSES)})", name="payments_status_valid"),
    )


class Outbox(Base):
    __tablename__ = "outbox"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    topic = Column(Text, nullable=False)
    aggregate_id = Column(PG_UUID(as_uuid=True), nullable=False)
    payload = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    published_at = Column(DateTime(timezone=True))
    publish_attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text)

    __table_args__ = (
        Index(
            "ix_outbox_unpublished",
            "created_at",
            postgresql_where="published_at IS NULL",
        ),
    )
