"""Backfill legacy order messages and remove Telegram support data.

Revision ID: d4e5f6a7b8c9
Revises: b7e1d3a9f4c2
Create Date: 2026-08-20
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "b7e1d3a9f4c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TEMP TABLE _legacy_order_message_map
        ON COMMIT DROP
        AS
        SELECT
            m.id AS legacy_message_id,
            cr.id AS chat_room_id,
            cr.order_id,
            cr.client_id,
            CASE
                WHEN author.email = 'bot@pixlogistic.com' THEN 'manager'
                ELSE 'client'
            END AS sender_kind,
            m.message AS body,
            m.time_created AS created_at
        FROM message AS m
        JOIN chat_room AS cr
          ON m.to_chat_room_id = cr.id
          OR m.to_chat_room_id = cr.order_id
        LEFT JOIN "user" AS author
          ON author.id = m.from_user_id
        WHERE cr.order_id IS NOT NULL
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM _legacy_order_message_map
                GROUP BY legacy_message_id
                HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION 'legacy order message mapping is ambiguous';
            END IF;
        END
        $$
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM _legacy_order_message_map
                WHERE client_id IS NULL
            ) THEN
                RAISE EXCEPTION 'legacy order message has no client';
            END IF;
        END
        $$
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM notifications AS notification
                JOIN message AS legacy
                  ON legacy.id = notification.object_id
                LEFT JOIN _legacy_order_message_map AS map
                  ON map.legacy_message_id = legacy.id
                WHERE notification.type = 'ORDER_MESSAGE'
                  AND map.legacy_message_id IS NULL
            ) THEN
                RAISE EXCEPTION 'ORDER_MESSAGE notification has no order mapping';
            END IF;
        END
        $$
        """
    )
    op.execute(
        """
        INSERT INTO order_chat_message (
            id,
            order_id,
            client_id,
            sender_kind,
            source,
            body,
            external_key,
            legacy_message_id,
            created_at
        )
        SELECT
            md5(map.legacy_message_id::text || '\\:order-chat')::uuid,
            map.order_id,
            map.client_id,
            map.sender_kind,
            'legacy',
            map.body,
            NULL,
            map.legacy_message_id,
            COALESCE(map.created_at, now())
        FROM _legacy_order_message_map AS map
        ON CONFLICT (legacy_message_id) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE notifications AS notification
        SET object_id = retained.id
        FROM order_chat_message AS retained
        WHERE notification.type = 'ORDER_MESSAGE'
          AND notification.object_id = retained.legacy_message_id
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM (
                    SELECT DISTINCT legacy_message_id
                    FROM _legacy_order_message_map
                ) AS mapped
                LEFT JOIN order_chat_message AS retained
                  ON retained.legacy_message_id = mapped.legacy_message_id
                WHERE retained.id IS NULL
            ) THEN
                RAISE EXCEPTION 'legacy order message backfill incomplete';
            END IF;
        END
        $$
        """
    )
    op.execute(
        """
        DELETE FROM notifications
        WHERE type = 'MESSAGE'
        """
    )
    op.execute(
        """
        DELETE FROM chat_outbox_event
        WHERE event_type IN (
            'telegram_client_alert',
            'telegram_manager_alert',
            'telegram_projection_error'
        )
        """
    )
    op.drop_table("message")
    op.drop_table("chat_room")
    op.drop_column("user", "telegram_id")


def downgrade() -> None:
    op.add_column(
        "user",
        sa.Column("telegram_id", sa.Integer(), nullable=True),
    )
    op.create_table(
        "chat_room",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("members", sa.JSON(), nullable=True),
        sa.Column("client_id", sa.UUID(), nullable=True),
        sa.Column("order_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "message",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column(
            "time_created",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("time_updated", sa.DateTime(), nullable=True),
        sa.Column("from_user_id", sa.UUID(), nullable=True),
        sa.Column("to_chat_room_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["from_user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
