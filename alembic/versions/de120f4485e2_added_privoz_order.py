"""added privoz order

Revision ID: de120f4485e2
Revises: 936e70921428
Create Date: 2024-01-18 19:03:40.224566

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'de120f4485e2'
down_revision: Union[str, None] = '936e70921428'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('privoz_order',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('privoz_order', sa.String(), nullable=True),
    sa.Column('state', sa.String(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('privoz_order')
    # ### end Alembic commands ###