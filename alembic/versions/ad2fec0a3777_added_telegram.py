"""added_telegram

Revision ID: ad2fec0a3777
Revises: ef73eaab97ae
Create Date: 2024-02-08 19:15:29.802740

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ad2fec0a3777'
down_revision: Union[str, None] = 'ef73eaab97ae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('user', sa.Column('telegram_id', sa.Integer(), nullable=True))
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('user', 'telegram_id')
    # ### end Alembic commands ###
