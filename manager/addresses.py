from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from db.schemas.addresses import (
    AddressCreate,
    AddressListResponse,
    AddressRead,
    AddressUpdate,
)
from errors import AddressNotFound


@dataclass(frozen=True, slots=True)
class DeliveryAddressSnapshot:
    name: str
    city: str
    street: str
    house: str
    postal_code: str | None
    building: str | None
    apartment: str | None
    delivery_comment: str | None


def normalize_address_name(value: str) -> str:
    return " ".join(value.strip().split()).casefold()


class AddressManager:
    def __init__(self, repository, clock=None):
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _read(row, default_id: UUID | None) -> AddressRead:
        return AddressRead(
            id=row.id,
            name=row.name,
            city=row.city,
            street=row.street,
            house=row.house,
            postal_code=row.postal_code,
            building=row.building,
            apartment=row.apartment,
            delivery_comment=row.delivery_comment,
            is_default=row.id == default_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
            last_used_at=row.last_used_at,
        )

    async def list(
        self, user_id: UUID, search: str, limit: int, offset: int
    ) -> AddressListResponse:
        normalized_search = normalize_address_name(search) if search.strip() else ""
        rows, total, default_id = await self._repository.list_for_user(
            user_id, normalized_search, limit, offset
        )
        return AddressListResponse(
            items=[self._read(row, default_id) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def create(self, user_id: UUID, request: AddressCreate) -> AddressRead:
        values = request.model_dump()
        values["normalized_name"] = normalize_address_name(request.name)
        row = await self._repository.create_for_user(user_id, values)
        return self._read(row, default_id=None)

    async def update(
        self, user_id: UUID, address_id: UUID, request: AddressUpdate
    ) -> AddressRead:
        values = request.model_dump(exclude_unset=True)
        if "name" in values:
            values["normalized_name"] = normalize_address_name(values["name"])
        row = await self._repository.update_for_user(user_id, address_id, values)
        if row is None:
            raise AddressNotFound()
        return self._read(row, await self._repository.get_default_id(user_id))

    async def delete(self, user_id: UUID, address_id: UUID) -> None:
        if not await self._repository.delete_for_user(user_id, address_id):
            raise AddressNotFound()

    async def get_for_order(
        self, user_id: UUID, address_id: UUID
    ) -> DeliveryAddressSnapshot:
        row = await self._repository.get_for_user(user_id, address_id)
        if row is None:
            raise AddressNotFound()
        return DeliveryAddressSnapshot(
            name=row.name,
            city=row.city,
            street=row.street,
            house=row.house,
            postal_code=row.postal_code,
            building=row.building,
            apartment=row.apartment,
            delivery_comment=row.delivery_comment,
        )

    async def mark_used(self, user_id: UUID, address_id: UUID) -> None:
        found = await self._repository.mark_used(user_id, address_id, self._clock())
        if not found:
            raise AddressNotFound()
