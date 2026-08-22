"""Add operator order-chat inbox state and durable email outbox.

Revision ID: f4c8a2d6b901
Revises: e3b7c9d1a204
Create Date: 2026-08-22
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "f4c8a2d6b901"
down_revision: Union[str, None] = "e3b7c9d1a204"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "order_chat_state",
        sa.Column("order_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "order_chat_state",
        sa.Column("latest_message_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "order_chat_state",
        sa.Column(
            "operator_unread_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.create_foreign_key(
        "fk_order_chat_state_latest_message",
        "order_chat_state",
        "order_chat_message",
        ["latest_message_id"],
        ["id"],
    )
    op.create_check_constraint(
        "ck_order_chat_operator_unread_nonnegative",
        "order_chat_state",
        "operator_unread_count >= 0",
    )

    op.create_table(
        "order_chat_email_outbox",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("message_id", sa.UUID(), nullable=False),
        sa.Column("recipient_email", sa.String(length=320), nullable=False),
        sa.Column("recipient_kind", sa.String(length=16), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "attempts",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "recipient_kind IN ('client', 'manager')",
            name="ck_order_chat_email_recipient_kind",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'sent', 'dead')",
            name="ck_order_chat_email_status",
        ),
        sa.CheckConstraint(
            "attempts >= 0",
            name="ck_order_chat_email_attempts_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["order_chat_message.id"],
            name="fk_order_chat_email_outbox_message",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_order_chat_email_outbox"),
        sa.UniqueConstraint(
            "message_id",
            name="uq_order_chat_email_outbox_message",
        ),
    )
    op.create_index(
        "ix_order_chat_email_outbox_due",
        "order_chat_email_outbox",
        ["status", "available_at"],
    )

    op.execute(
        sa.text(
            """
            UPDATE order_chat_state AS state
            SET latest_message_id = latest.id,
                updated_at = GREATEST(state.updated_at, latest.created_at)
            FROM (
                SELECT DISTINCT ON (order_id) order_id, id, created_at
                FROM order_chat_message
                ORDER BY order_id, created_at DESC, id DESC
            ) AS latest
            WHERE latest.order_id = state.order_id
            """
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_order_chat_email_outbox_due",
        table_name="order_chat_email_outbox",
    )
    op.drop_table("order_chat_email_outbox")
    op.drop_constraint(
        "ck_order_chat_operator_unread_nonnegative",
        "order_chat_state",
        type_="check",
    )
    op.drop_constraint(
        "fk_order_chat_state_latest_message",
        "order_chat_state",
        type_="foreignkey",
    )
    op.drop_column("order_chat_state", "operator_unread_count")
    op.drop_column("order_chat_state", "latest_message_id")
    op.drop_column("order_chat_state", "order_name")
