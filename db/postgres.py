import os
from typing import AsyncGenerator

from fastapi import Depends
from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTableUUID, SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

driver = os.getenv("POSTGRES_DRIVER", "postgresql+asyncpg")
user = os.getenv("POSTGRES_USER", "user")
password = os.getenv("POSTGRES_PASSWORD", "user")
database = os.getenv("POSTGRES_DB", "pix")
host = os.getenv("POSTGRES_HOST", "localhost")
port = os.getenv("DB_PORT", "5431")

DATABASE_URL = f"{driver}://{user}:{password}@{host}:{port}/{database}"


class Base(DeclarativeBase):
    pass


class User(SQLAlchemyBaseUserTableUUID, Base):
    pass


engine = create_async_engine(DATABASE_URL)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


async def get_user_db(session: AsyncSession = Depends(get_async_session)):
    yield SQLAlchemyUserDatabase(session, User)


