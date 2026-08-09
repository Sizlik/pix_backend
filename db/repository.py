import base64
from abc import ABC, abstractmethod
from uuid import UUID

import requests
from sqlalchemy import insert, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_upsert

from config import Settings, get_settings, require_secret, require_value
from db.postgres import async_session_maker


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
    async def read_all(self, filter=None, order_by=None, **kwargs):
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

    @abstractmethod
    async def upsert(self, array_data):
        raise NotImplementedError

    @abstractmethod
    async def export(self, **kwargs):
        raise NotImplementedError


class MoySkladRepository(AbstractRepository):
    model = None
    base_url = "https://api.moysklad.ru/api/remap/1.2/"

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def _headers(self) -> dict[str, str]:
        login = require_value(self.settings.moysklad_login, "moysklad")
        password = require_secret(self.settings.moysklad_password, "moysklad")
        encoded = base64.b64encode(f"{login}:{password}".encode("utf-8")).decode("utf-8")
        return {"Authorization": f"Basic {encoded}"}

    async def get_default_company(self) -> dict:
        response = requests.get(
            f"{self.base_url}context/usersettings",
            headers=self._headers(),
        ).json()
        return response["defaultCompany"]

    async def read_one(self, id, **kwargs):
        return requests.get(
            self.base_url + self.model + "/" + str(id) + "?" + kwargs.get("link", ""), headers=self._headers()
        ).json()

    async def create(self, **kwargs):
        print(kwargs)
        return requests.post(
            self.base_url + self.model + "/" + kwargs.get("link", ""), headers=self._headers(), json=kwargs
        ).json()

    async def create_multiply(self, rows: list):
        return requests.post(self.base_url + self.model, headers=self._headers(), json=rows).json()

    async def read_all(self, filter="", order_by=None, **kwargs):
        return requests.get(
            self.base_url + self.model + kwargs.get("metadata", "") + "?filter=" + filter, headers=self._headers()
        ).json()

    async def update(self, id, **kwargs):
        return requests.put(
            self.base_url + self.model + f"/{id}" + kwargs.get("link", ""), headers=self._headers(), json=kwargs
        ).json()

    async def search_one(self, search):
        pass

    async def delete(self, id, **kwargs):
        return requests.delete(
            self.base_url + self.model + f"/{id}" + kwargs.get("link", ""), headers=self._headers()
        ).status_code

    async def upsert(self, **kwargs):
        pass

    async def export(self, **kwargs):
        return requests.post(
            self.base_url + self.model + "/" + kwargs.get("link", ""), headers=self._headers(), json=kwargs
        ).content


class SQLAlchemyRepository(AbstractRepository):
    model = None

    async def read_one(self, id: UUID | int, **kwargs):
        async with async_session_maker() as session:
            stmt = select(self.model).where(self.model.id == id)
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

    async def read_all(self, filter=None, order_by=None, **kwargs):
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

    async def upsert(self, array_data: list):
        async with async_session_maker() as session:
            stmt = sqlite_upsert(self.model).values(array_data)
            stmt = stmt.on_conflict_do_update(
                index_elements=self.model.__table__.primary_key, set_=dict(state=stmt.excluded.state)
            ).returning(self.model)
            res = await session.execute(stmt)
            await session.commit()
            res = [x for x in res.scalars()]
            return res

    async def delete(self, id, **kwargs):
        pass

    async def export(self, kwargs):
        pass
