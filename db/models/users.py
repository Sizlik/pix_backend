from fastapi import Depends
from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTableUUID, SQLAlchemyUserDatabase
from sqlalchemy import Column, Float, String, Integer, UUID, JSON, select, ForeignKey, Boolean, and_
from sqlalchemy.ext.asyncio import AsyncSession

from db.postgres import Base, get_async_session, async_session_maker


class User(SQLAlchemyBaseUserTableUUID, Base):
    balance = Column(Integer, default=0, nullable=False)
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    phone_number = Column(String, nullable=False)
    bitrix_client_id = Column(Integer)
    moysklad_counterparty_id = Column(UUID)
    moysklad_counterparty_meta = Column(JSON)
    telegram_id = Column(Integer)
    name_id = Column(Integer, autoincrement=True, server_default='1')

    organization_id = Column(ForeignKey("organization.id"), nullable=True)
    is_organization_user = Column(Boolean, default=False)


class UserDatabase(SQLAlchemyUserDatabase):
    async def get_by_moysklad(self, id: str):
        statement = select(self.user_table).where(self.user_table.moysklad_counterparty_id == id)
        return await self._get_user(statement)

    async def get_users_by_organization(self, organization_id: str):
        statement = select(self.user_table).where(and_(self.user_table.organization_id == organization_id, self.user_table.is_organization_user == True))
        results = await self.session.execute(statement)
        res = [x for x in results.scalars()]
        return res


async def get_user_db(session: AsyncSession = Depends(get_async_session)):
    yield UserDatabase(session, User)
