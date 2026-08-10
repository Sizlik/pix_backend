"""Add immutable order chat delivery tables.

Revision ID: c8f2a4e6d901
Revises: 107b04f2194b
Create Date: 2026-08-10
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "c8f2a4e6d901"
down_revision: Union[str, None] = "107b04f2194b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "order_chat_message",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("order_id", sa.UUID(), nullable=False),
        sa.Column("client_id", sa.UUID(), nullable=False),
        sa.Column("sender_kind", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("external_key", sa.String(length=255), nullable=True),
        sa.Column("legacy_message_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "sender_kind IN ('client', 'manager')",
            name="ck_order_chat_sender_kind",
        ),
        sa.CheckConstraint(
            "source IN ('site', 'moysklad', 'legacy')",
            name="ck_order_chat_source",
        ),
        sa.ForeignKeyConstraint(["client_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_key"),
        sa.UniqueConstraint("legacy_message_id"),
    )
    op.create_index(
        "ix_order_chat_message_client_id",
        "order_chat_message",
        ["client_id"],
        unique=False,
    )
    op.create_index(
        "ix_order_chat_message_order_id",
        "order_chat_message",
        ["order_id"],
        unique=False,
    )
    op.create_index(
        "ix_order_chat_message_order_created",
        "order_chat_message",
        ["order_id", "created_at", "id"],
        unique=False,
    )

    op.create_table(
        "order_chat_attachment",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("message_id", sa.UUID(), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("origin_external_file_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("size_bytes > 0", name="ck_order_chat_attachment_size"),
        sa.CheckConstraint(
            "origin IN ('site', 'moysklad')",
            name="ck_order_chat_attachment_origin",
        ),
        sa.ForeignKeyConstraint(["message_id"], ["order_chat_message.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key"),
    )
    op.create_index(
        "ix_order_chat_attachment_message_id",
        "order_chat_attachment",
        ["message_id"],
        unique=False,
    )

    op.create_table(
        "order_chat_state",
        sa.Column("order_id", sa.UUID(), nullable=False),
        sa.Column("client_id", sa.UUID(), nullable=False),
        sa.Column(
            "initialized",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("rendered_description_hash", sa.String(length=64), nullable=True),
        sa.Column("prior_comment_file_id", sa.UUID(), nullable=True),
        sa.Column("history_file_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["client_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("order_id"),
    )
    op.create_index(
        "ix_order_chat_state_client_id",
        "order_chat_state",
        ["client_id"],
        unique=False,
    )

    op.create_table(
        "moysklad_order_file",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("order_id", sa.UUID(), nullable=False),
        sa.Column("moysklad_file_id", sa.UUID(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("disposition", sa.String(length=32), nullable=False),
        sa.Column("message_id", sa.UUID(), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "disposition IN ('baseline', 'client_mirror', 'manager_public', 'internal', 'system')",
            name="ck_moysklad_order_file_disposition",
        ),
        sa.ForeignKeyConstraint(["message_id"], ["order_chat_message.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "order_id",
            "moysklad_file_id",
            name="uq_moysklad_order_file",
        ),
    )
    op.create_index(
        "ix_moysklad_order_file_order_id",
        "moysklad_order_file",
        ["order_id"],
        unique=False,
    )

    op.create_table(
        "chat_outbox_event",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("order_id", sa.UUID(), nullable=False),
        sa.Column("dedup_key", sa.String(length=255), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'dead')",
            name="ck_chat_outbox_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedup_key"),
    )
    op.create_index(
        "ix_chat_outbox_event_order_id",
        "chat_outbox_event",
        ["order_id"],
        unique=False,
    )
    op.create_index(
        "ix_chat_outbox_due",
        "chat_outbox_event",
        ["status", "available_at"],
        unique=False,
    )

    op.execute(
        """
        CREATE FUNCTION reject_order_chat_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'order chat history is append-only';
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER order_chat_message_append_only
        BEFORE UPDATE OR DELETE ON order_chat_message
        FOR EACH ROW EXECUTE FUNCTION reject_order_chat_mutation();

        CREATE TRIGGER order_chat_attachment_append_only
        BEFORE UPDATE OR DELETE ON order_chat_attachment
        FOR EACH ROW EXECUTE FUNCTION reject_order_chat_mutation();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS order_chat_attachment_append_only
            ON order_chat_attachment;
        DROP TRIGGER IF EXISTS order_chat_message_append_only
            ON order_chat_message;
        DROP FUNCTION IF EXISTS reject_order_chat_mutation();
        """
    )
    op.drop_index("ix_chat_outbox_due", table_name="chat_outbox_event")
    op.drop_index("ix_chat_outbox_event_order_id", table_name="chat_outbox_event")
    op.drop_table("chat_outbox_event")
    op.drop_index("ix_moysklad_order_file_order_id", table_name="moysklad_order_file")
    op.drop_table("moysklad_order_file")
    op.drop_index("ix_order_chat_state_client_id", table_name="order_chat_state")
    op.drop_table("order_chat_state")
    op.drop_index(
        "ix_order_chat_attachment_message_id",
        table_name="order_chat_attachment",
    )
    op.drop_table("order_chat_attachment")
    op.drop_index(
        "ix_order_chat_message_order_created",
        table_name="order_chat_message",
    )
    op.drop_index("ix_order_chat_message_order_id", table_name="order_chat_message")
    op.drop_index("ix_order_chat_message_client_id", table_name="order_chat_message")
    op.drop_table("order_chat_message")
