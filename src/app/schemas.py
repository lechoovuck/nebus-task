from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class PaymentCreateIn(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    currency: Literal["RUB", "USD", "EUR"]
    description: str | None = Field(default=None, max_length=1000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    webhook_url: HttpUrl


class PaymentCreateOut(BaseModel):
    payment_id: UUID
    status: str
    created_at: datetime


class PaymentOut(BaseModel):
    payment_id: UUID
    amount: Decimal
    currency: str
    description: str | None
    metadata: dict[str, Any]
    status: str
    failure_reason: str | None
    webhook_url: HttpUrl
    created_at: datetime
    processed_at: datetime | None

    model_config = ConfigDict(from_attributes=True)
