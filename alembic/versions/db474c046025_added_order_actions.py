"""added_order_actions

Revision ID: db474c046025
Revises: 4cec7a158d66
Create Date: 2024-03-11 02:47:01.252764

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'db474c046025'
down_revision: Union[str, None] = '4cec7a158d66'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('order_actions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('new_state', sa.String(), nullable=True),
    sa.Column('order_id', sa.UUID(), nullable=True),
    sa.Column('date', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.alter_column('user', 'name_id',
               existing_type=sa.INTEGER(),
               nullable=True,
               autoincrement=True)
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column('user', 'name_id',
               existing_type=sa.INTEGER(),
               nullable=False,
               autoincrement=True)
    op.drop_table('order_actions')
    # ### end Alembic commands ###