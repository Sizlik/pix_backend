import base64
import logging
from abc import ABC, abstractmethod
from uuid import UUID

import requests
from sqlalchemy import insert, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_upsert

from config import Settings, get_settings, require_secret, require_value
from db.postgres import async_session_maker
from errors import MoySkladDocumentExportError

logger = logging.getLogger(__name__)


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
    async def export_document(
        self,
        document_id: str,
        *,
        template: dict,
        extension: str,
    ) -> bytes:
        raise NotImplementedError

    @abstractmethod
    async def read_embedded_templates(self) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def read_export_context(self, document_id: str) -> dict:
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
        response = requests.get(
            self.base_url
            + self.model
            + "/"
            + str(id)
            + "?"
            + kwargs.get("link", ""),
            headers=self._headers(),
        )
        if response.status_code == 404:
            return {}
        response.raise_for_status()
        return response.json()

    async def create(self, **kwargs):
        payload = dict(kwargs)
        link = payload.pop("link", "")
        response = requests.post(
            self.base_url + self.model + "/" + link,
            headers=self._headers(),
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    async def create_multiply(self, rows: list):
        response = requests.post(
            self.base_url + self.model,
            headers=self._headers(),
            json=rows,
        )
        response.raise_for_status()
        return response.json()

    async def read_all(self, filter="", order_by=None, **kwargs):
        response = requests.get(
            self.base_url
            + self.model
            + kwargs.get("metadata", "")
            + "?filter="
            + filter,
            headers=self._headers(),
        )
        response.raise_for_status()
        return response.json()

    async def update(self, id, **kwargs):
        payload = dict(kwargs)
        link = payload.pop("link", "")
        response = requests.put(
            self.base_url + self.model + f"/{id}" + link,
            headers=self._headers(),
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    async def search_one(self, search):
        pass

    async def delete(self, id, **kwargs):
        return requests.delete(
            self.base_url + self.model + f"/{id}" + kwargs.get("link", ""), headers=self._headers()
        ).status_code

    async def upsert(self, **kwargs):
        pass

    async def export_document(
        self,
        document_id: str,
        *,
        template: dict,
        extension: str,
    ) -> bytes:
        try:
            response = requests.post(
                f"{self.base_url}{self.model}/{document_id}/export",
                headers=self._headers(),
                json={"template": template, "extension": extension},
                allow_redirects=True,
                timeout=(5, 30),
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            logger.warning(
                "MoySklad document export request failed model=%s document_id=%s status=%s",
                self.model,
                document_id,
                status_code,
            )
            raise MoySkladDocumentExportError("request_failed", status_code) from exc

        if response.status_code != 200:
            logger.warning(
                "MoySklad document export returned a non-final status "
                "model=%s document_id=%s status=%s",
                self.model,
                document_id,
                response.status_code,
            )
            raise MoySkladDocumentExportError("unexpected_status", response.status_code)

        if not response.content.startswith(b"%PDF-"):
            logger.warning(
                "MoySklad document export returned invalid PDF content "
                "model=%s document_id=%s status=%s",
                self.model,
                document_id,
                response.status_code,
            )
            raise MoySkladDocumentExportError("invalid_pdf", response.status_code)

        return response.content

    async def read_embedded_templates(self) -> dict:
        try:
            response = requests.get(
                f"{self.base_url}{self.model}/metadata/embeddedtemplate",
                headers=self._headers(),
                timeout=(5, 30),
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            logger.warning(
                "MoySklad embedded template request failed model=%s status=%s",
                self.model,
                status_code,
            )
            raise MoySkladDocumentExportError(
                "template_request_failed",
                status_code,
            ) from exc
        except ValueError as exc:
            logger.warning(
                "MoySklad embedded template response was invalid model=%s status=%s",
                self.model,
                response.status_code,
            )
            raise MoySkladDocumentExportError(
                "template_request_failed",
                response.status_code,
            ) from exc

    async def read_export_context(self, document_id: str) -> dict:
        try:
            response = requests.get(
                f"{self.base_url}{self.model}/{document_id}",
                headers=self._headers(),
                params={"expand": "agent"},
                timeout=(5, 30),
            )
            if response.status_code == 404:
                return {}
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("invalid document context")
            return payload
        except requests.RequestException as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            logger.warning(
                "MoySklad document context request failed "
                "model=%s document_id=%s status=%s",
                self.model,
                document_id,
                status_code,
            )
            raise MoySkladDocumentExportError(
                "context_request_failed",
                status_code,
            ) from exc
        except ValueError as exc:
            logger.warning(
                "MoySklad document context response was invalid "
                "model=%s document_id=%s status=%s",
                self.model,
                document_id,
                response.status_code,
            )
            raise MoySkladDocumentExportError(
                "context_request_failed",
                response.status_code,
            ) from exc


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

    async def export_document(
        self,
        document_id: str,
        *,
        template: dict,
        extension: str,
    ) -> bytes:
        raise NotImplementedError

    async def read_embedded_templates(self) -> dict:
        raise NotImplementedError

    async def read_export_context(self, document_id: str) -> dict:
        raise NotImplementedError
