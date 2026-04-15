from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import verify_api_key
from app.db import get_session
from app.models import Outbox, Payment
from app.schemas import PaymentCreateIn, PaymentCreateOut, PaymentOut
from app.utils import calculate_request_fingerprint

router = APIRouter(prefix="/api/v1", tags=["payments"])


@router.post(
    "/payments",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=PaymentCreateOut,
)
async def create_payment(
    body: PaymentCreateIn,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_api_key),
) -> PaymentCreateOut:
    fingerprint = calculate_request_fingerprint(body.model_dump(mode="json"))

    payment = Payment(
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
        amount=body.amount,
        currency=body.currency,
        description=body.description,
        meta=body.metadata,
        webhook_url=str(body.webhook_url),
        status="pending",
    )

    try:
        session.add(payment)
        await session.flush()

        session.add(
            Outbox(
                topic="payments.new",
                aggregate_id=payment.id,
                payload={
                    "event_id": str(payment.id),
                    "payment_id": str(payment.id),
                    "idempotency_key": idempotency_key,
                    "created_at": payment.created_at.isoformat(),
                },
            )
        )
        await session.commit()
        return PaymentCreateOut(
            payment_id=payment.id,
            status=payment.status,
            created_at=payment.created_at,
        )
    except IntegrityError:
        await session.rollback()

    existing = (
        await session.execute(
            select(Payment).where(Payment.idempotency_key == idempotency_key)
        )
    ).scalar_one_or_none()

    if existing is None:
        raise

    if existing.request_fingerprint != fingerprint:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="idempotency key reused with different payload",
        )

    return PaymentCreateOut(
        payment_id=existing.id,
        status=existing.status,
        created_at=existing.created_at,
    )


@router.get("/payments/{payment_id}", response_model=PaymentOut)
async def get_payment(
    payment_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_api_key),
) -> PaymentOut:
    payment = (
        await session.execute(select(Payment).where(Payment.id == payment_id))
    ).scalar_one_or_none()

    if payment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")

    return PaymentOut(
        payment_id=payment.id,
        amount=payment.amount,
        currency=payment.currency,
        description=payment.description,
        metadata=payment.meta,
        status=payment.status,
        failure_reason=payment.failure_reason,
        webhook_url=payment.webhook_url,
        created_at=payment.created_at,
        processed_at=payment.processed_at,
    )
