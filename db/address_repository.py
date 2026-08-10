from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from db.models.addresses import Address
from db.postgres import async_session_maker
from errors import AddressNameConflict


def build_address_list_statement(user_id, search, limit, offset):
    statement = select(Address).where(Address.user_id == user_id)
    if search:
        statement = statement.where(
            Address.normalized_name.contains(search, autoescape=True)
        )
    return (
        statement.order_by(
            Address.last_used_at.desc().nullslast(),
            Address.updated_at.desc(),
            Address.id,
        )
        .limit(limit)
        .offset(offset)
    )


def default_address_id_statement(user_id):
    return (
        select(Address.id)
        .where(Address.user_id == user_id, Address.last_used_at.is_not(None))
        .order_by(
            Address.last_used_at.desc(),
            Address.updated_at.desc(),
            Address.id,
        )
        .limit(1)
    )


def constraint_name(exc: IntegrityError) -> str | None:
    return getattr(
        getattr(getattr(exc, "orig", None), "diag", None),
        "constraint_name",
        None,
    )


class AddressRepository:
    def __init__(self, session_factory=async_session_maker):
        self._session_factory = session_factory

    @staticmethod
    def _filters(user_id: UUID, search: str):
        filters = [Address.user_id == user_id]
        if search:
            filters.append(Address.normalized_name.contains(search, autoescape=True))
        return filters

    async def list_for_user(
        self, user_id: UUID, search: str, limit: int, offset: int
    ) -> tuple[list[Address], int, UUID | None]:
        filters = self._filters(user_id, search)
        async with self._session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        build_address_list_statement(user_id, search, limit, offset)
                    )
                ).scalars()
            )
            total = (
                await session.execute(
                    select(func.count()).select_from(Address).where(*filters)
                )
            ).scalar_one()
            default_id = (
                await session.execute(default_address_id_statement(user_id))
            ).scalar_one_or_none()
            return rows, total, default_id

    async def get_default_id(self, user_id: UUID) -> UUID | None:
        async with self._session_factory() as session:
            return (
                await session.execute(default_address_id_statement(user_id))
            ).scalar_one_or_none()

    async def get_for_user(self, user_id: UUID, address_id: UUID) -> Address | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Address).where(
                    Address.id == address_id,
                    Address.user_id == user_id,
                )
            )
            return result.scalar_one_or_none()

    async def create_for_user(self, user_id: UUID, values: dict) -> Address:
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    row = Address(user_id=user_id, **values)
                    session.add(row)
                    await session.flush()
                    return row
        except IntegrityError as exc:
            if constraint_name(exc) == "uq_address_user_normalized_name":
                raise AddressNameConflict() from exc
            raise

    async def update_for_user(
        self, user_id: UUID, address_id: UUID, values: dict
    ) -> Address | None:
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    result = await session.execute(
                        update(Address)
                        .where(
                            Address.id == address_id,
                            Address.user_id == user_id,
                        )
                        .values(**values, updated_at=func.now())
                        .returning(Address)
                    )
                    return result.scalar_one_or_none()
        except IntegrityError as exc:
            if constraint_name(exc) == "uq_address_user_normalized_name":
                raise AddressNameConflict() from exc
            raise

    async def delete_for_user(self, user_id: UUID, address_id: UUID) -> bool:
        async with self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    delete(Address).where(
                        Address.id == address_id,
                        Address.user_id == user_id,
                    )
                )
                return result.rowcount == 1

    async def mark_used(
        self, user_id: UUID, address_id: UUID, used_at: datetime
    ) -> bool:
        async with self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    update(Address)
                    .where(
                        Address.id == address_id,
                        Address.user_id == user_id,
                    )
                    .values(last_used_at=used_at, updated_at=func.now())
                )
                return result.rowcount == 1
