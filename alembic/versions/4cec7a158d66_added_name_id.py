"""added_name_id

Revision ID: 4cec7a158d66
Revises: ad2fec0a3777
Create Date: 2024-03-03 09:38:07.296172

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4cec7a158d66'
down_revision: Union[str, None] = 'ad2fec0a3777'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('user', sa.Column('name_id', sa.Integer(), autoincrement=True, primary_key=True))
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('user', 'name_id')
    # ### end Alembic commands ###