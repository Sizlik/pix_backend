"""removed user_organizations

Revision ID: ecc42f08ec1e
Revises: 00a8969ff4d9
Create Date: 2024-03-23 18:23:47.884877

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ecc42f08ec1e'
down_revision: Union[str, None] = '00a8969ff4d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('user_organization')
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('user_organization',
    sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('user_id', sa.UUID(), autoincrement=False, nullable=True),
    sa.Column('organization_id', sa.UUID(), autoincrement=False, nullable=True),
    sa.ForeignKeyConstraint(['organization_id'], ['organization.id'], name='user_organization_organization_id_fkey'),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], name='user_organization_user_id_fkey'),
    sa.PrimaryKeyConstraint('id', name='user_organization_pkey')
    )
    # ### end Alembic commands ###