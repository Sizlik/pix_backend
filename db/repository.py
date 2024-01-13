import base64
import os
from abc import ABC, abstractmethod
from uuid import UUID

import requests
from sqlalchemy import select, insert, update

from db.models.users import User
from db.postgres import get_async_session, async_session_maker


class AbstractRepository(ABC):
    @abstractmethod
    async def read_one(self, id, **kwargs):
        raise NotImplementedError

    @abstractmethod
    async def create(self, **kwargs):
        raise NotImplementedError

    @abstractmethod
    async def create_multiply(self, rows: list):
        raise NotImplementedError

    @abstractmethod
    async def read_all(self, filter=None, order_by=None):
        raise NotImplementedError

    @abstractmethod
    async def update(self, id, **kwargs):
        raise NotImplementedError

    @abstractmethod
    async def search_one(self, search):
        raise NotImplementedError

    @abstractmethod
    async def delete(self, id, **kwargs):
        raise NotImplementedError


class MoySkladRepository(AbstractRepository):
    model = None

    __link = "https://api.moysklad.ru/api/remap/1.2/"
    __login = os.getenv("MOYSKLAD_LOGIN")
    __password = os.getenv("MOYSKLAD_PASWORD")
    __headers = {
        "Authorization": f'Basic {base64.b64encode(f"{__login}:{__password}".encode("UTF-8")).decode("utf-8")}'
    }

    async def read_one(self, id, **kwargs):
        return requests.get(self.__link + self.model + "/" + str(id) + "?" + kwargs.get("link", ""), headers=self.__headers).json()

    async def create(self, **kwargs):
        return requests.post(self.__link + self.model, headers=self.__headers, json=kwargs).json()

    async def create_multiply(self, rows: list):
        return requests.post(self.__link + self.model, headers=self.__headers, json=rows).json()

    async def read_all(self, filter="", order_by=None):
        return requests.get(self.__link + self.model + "?filter=" + filter, headers=self.__headers).json()

    async def update(self, id, **kwargs):
        pass

    async def search_one(self, search):
        pass

    async def delete(self, id, **kwargs):
        return requests.delete(self.__link + self.model + f"/{id}" + kwargs.get("link", ""), headers=self.__headers).status_code


class SQLAlchemyRepository(AbstractRepository):
    model = None

    async def read_one(self, id: UUID | int, **kwargs):
        async with async_session_maker() as session:
            stmt = select(self.model)
            res = await session.execute(stmt)
            return res.scalar()

    async def create(self, **kwargs) -> UUID | int:
        async with async_session_maker() as session:
            stmt = insert(self.model).values(**kwargs).returning(self.model.id)
            res = await session.execute(stmt)
            await session.commit()
            return res.scalar_one()

    async def create_multiply(self, rows: list):
        async with async_session_maker() as session:
            stmt = insert(self.model).values(rows).returning(self.model)
            res = await session.execute(stmt)
            await session.commit()
            res = [x for x in res.scalars()]
            return res

    async def read_all(self, filter=None, order_by=None):
        async with async_session_maker() as session:
            stmt = select(self.model)
            if filter is not None:
                stmt = stmt.filter(filter)
            stmt = stmt.order_by(self.model.id.desc() if order_by is None else order_by)

            res = await session.execute(stmt)
            res = [x for x in res.scalars()]
            return res

    async def update(self, id, **kwargs):
        async with async_session_maker() as session:
            stmt = update(self.model).where(self.model.id == id).values(**kwargs).returning(self.model)
            res = await session.execute(stmt)
            await session.commit()
            return res.scalar_one()

    async def search_one(self, search):
        async with async_session_maker() as session:
            stmt = select(self.model).where(search)
            res = await session.execute(stmt)
            return res.scalar()

    async def delete(self, id, **kwargs):
        pass

