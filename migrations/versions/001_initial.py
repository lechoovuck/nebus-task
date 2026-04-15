"""Initial migration: create payments and outbox tables

Revision ID: 001
Revises:
Create Date: 2026-04-16 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'payments',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('idempotency_key', sa.String(255), nullable=False),
        sa.Column('request_fingerprint', sa.Text(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('webhook_url', sa.Text(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, server_default='pending'),
        sa.Column('failure_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('webhook_delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('webhook_attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('webhook_last_error', sa.Text(), nullable=True),
        sa.CheckConstraint('amount > 0', name='check_amount_positive'),
        sa.CheckConstraint("currency IN ('RUB', 'USD', 'EUR')", name='check_currency_valid'),
        sa.CheckConstraint("status IN ('pending', 'succeeded', 'failed')", name='check_status_valid'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('idempotency_key'),
    )
    op.create_index('ix_payments_idempotency_key', 'payments', ['idempotency_key'], unique=True)

    op.create_table(
        'outbox',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('topic', sa.Text(), nullable=False),
        sa.Column('aggregate_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('publish_attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_outbox_unpublished', 'outbox', ['created_at'],
                    postgresql_where=sa.text("published_at IS NULL"))


def downgrade() -> None:
    op.drop_index('ix_outbox_unpublished', table_name='outbox')
    op.drop_table('outbox')
    op.drop_index('ix_payments_idempotency_key', table_name='payments')
    op.drop_table('payments')
