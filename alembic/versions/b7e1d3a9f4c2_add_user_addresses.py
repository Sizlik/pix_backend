"""Add user delivery addresses.

Revision ID: b7e1d3a9f4c2
Revises: c8f2a4e6d901
Create Date: 2026-08-10
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b7e1d3a9f4c2"
down_revision: Union[str, None] = "c8f2a4e6d901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "address",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("normalized_name", sa.String(length=100), nullable=False),
        sa.Column("city", sa.String(length=100), nullable=False),
        sa.Column("street", sa.String(length=200), nullable=False),
        sa.Column("house", sa.String(length=30), nullable=False),
        sa.Column("postal_code", sa.String(length=6), nullable=True),
        sa.Column("building", sa.String(length=30), nullable=True),
        sa.Column("apartment", sa.String(length=30), nullable=True),
        sa.Column("delivery_comment", sa.String(length=500), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "normalized_name",
            name="uq_address_user_normalized_name",
        ),
    )
    op.create_index("ix_address_user_id", "address", ["user_id"], unique=False)
    op.create_index(
        "ix_address_user_last_used",
        "address",
        ["user_id", "last_used_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_address_user_last_used", table_name="address")
    op.drop_index("ix_address_user_id", table_name="address")
    op.drop_table("address")
