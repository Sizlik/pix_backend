from fastapi import Depends
from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTableUUID, SQLAlchemyUserDatabase
from sqlalchemy import Column, Float, String, Integer, UUID, JSON
from sqlalchemy.ext.asyncio import AsyncSession

from db.postgres import Base, get_async_session


class User(SQLAlchemyBaseUserTableUUID, Base):
    balance = Column(Integer, default=0, nullable=False)
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    phone_number = Column(String, nullable=False)
    bitrix_client_id = Column(Integer)
    moysklad_counterparty_id = Column(UUID)
    moysklad_counterparty_meta = Column(JSON)
    telegram_id = Column(Integer)


async def get_user_db(session: AsyncSession = Depends(get_async_session)):
    yield SQLAlchemyUserDatabase(session, User)
