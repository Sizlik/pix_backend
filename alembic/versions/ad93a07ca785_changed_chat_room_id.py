"""changed_chat_room_id

Revision ID: ad93a07ca785
Revises: db474c046025
Create Date: 2024-03-14 23:43:49.676974

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ad93a07ca785'
down_revision: Union[str, None] = 'db474c046025'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint('message_to_chat_room_id_fkey', 'message', type_='foreignkey')
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_foreign_key('message_to_chat_room_id_fkey', 'message', 'chat_room', ['to_chat_room_id'], ['id'])
    # ### end Alembic commands ###
