"""Allow Chrome extension order-chat messages and attachments.

Revision ID: e3b7c9d1a204
Revises: d4e5f6a7b8c9
Create Date: 2026-08-21
"""

from typing import Sequence, Union

from alembic import op

revision: str = "e3b7c9d1a204"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_order_chat_source", "order_chat_message", type_="check"
    )
    op.create_check_constraint(
        "ck_order_chat_source",
        "order_chat_message",
        "source IN ('site', 'moysklad', 'legacy', 'extension')",
    )
    op.drop_constraint(
        "ck_order_chat_attachment_origin",
        "order_chat_attachment",
        type_="check",
    )
    op.create_check_constraint(
        "ck_order_chat_attachment_origin",
        "order_chat_attachment",
        "origin IN ('site', 'moysklad', 'extension')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_order_chat_attachment_origin",
        "order_chat_attachment",
        type_="check",
    )
    op.create_check_constraint(
        "ck_order_chat_attachment_origin",
        "order_chat_attachment",
        "origin IN ('site', 'moysklad')",
    )
    op.drop_constraint(
        "ck_order_chat_source", "order_chat_message", type_="check"
    )
    op.create_check_constraint(
        "ck_order_chat_source",
        "order_chat_message",
        "source IN ('site', 'moysklad', 'legacy')",
    )
