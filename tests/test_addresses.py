from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest

from db.schemas.addresses import AddressCreate, AddressUpdate
from errors import AddressNotFound
from manager.addresses import AddressManager, normalize_address_name

USER_ID = UUID("00000000-0000-0000-0000-000000000001")
ADDRESS_ID = UUID("00000000-0000-0000-0000-000000000010")
SECOND_ADDRESS_ID = UUID("00000000-0000-0000-0000-000000000011")
FIXED_TIME = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


class StubAddressRepository:
    def __init__(self, row=None):
        self.row = row
        self.marked = []

    async def get_for_user(self, user_id, address_id):
        return self.row if self.row and self.row.user_id == user_id else None

    async def mark_used(self, user_id, address_id, used_at):
        self.marked.append((user_id, address_id, used_at))
        return self.row is not None


def address_row(address_id=ADDRESS_ID, last_used_at=None):
    return SimpleNamespace(
        id=address_id,
        user_id=USER_ID,
        name="Дом" if address_id == ADDRESS_ID else "Офис",
        normalized_name="дом" if address_id == ADDRESS_ID else "офис",
        city="Калининград",
        street="Ленинский проспект",
        house="10",
        postal_code=None,
        building=None,
        apartment=None,
        delivery_comment=None,
        last_used_at=last_used_at,
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )


class MemoryAddressRepository:
    def __init__(self, rows=None, default_id=None, mutation_found=True):
        self.rows = list(rows or [])
        self.default_id = default_id
        self.mutation_found = mutation_found
        self.created = None
        self.updated_values = None
        self.list_args = None

    @classmethod
    def with_one_row(cls, last_used_at=None):
        return cls([address_row(last_used_at=last_used_at)], ADDRESS_ID)

    @classmethod
    def with_two_rows(cls, default_id):
        return cls(
            [address_row(ADDRESS_ID, FIXED_TIME), address_row(SECOND_ADDRESS_ID)],
            default_id,
        )

    async def list_for_user(self, user_id, search, limit, offset):
        self.list_args = (user_id, search, limit, offset)
        return self.rows, len(self.rows), self.default_id

    async def get_default_id(self, user_id):
        return self.default_id

    async def get_for_user(self, user_id, address_id):
        return next(
            (
                row
                for row in self.rows
                if row.user_id == user_id and row.id == address_id
            ),
            None,
        )

    async def create_for_user(self, user_id, values):
        self.created = values
        row = address_row()
        for key, value in values.items():
            setattr(row, key, value)
        self.rows.append(row)
        return row

    async def update_for_user(self, user_id, address_id, values):
        self.updated_values = values
        row = await self.get_for_user(user_id, address_id)
        if row is None:
            return None
        for key, value in values.items():
            setattr(row, key, value)
        return row

    async def delete_for_user(self, user_id, address_id):
        return self.mutation_found

    async def mark_used(self, user_id, address_id, used_at):
        return self.mutation_found


def test_normalize_address_name_collapses_space_and_casefolds_unicode():
    assert normalize_address_name("  МОЙ   Дом ") == "мой дом"


@pytest.mark.asyncio
async def test_get_for_order_returns_immutable_snapshot_for_owned_address():
    row = SimpleNamespace(
        id=ADDRESS_ID,
        user_id=USER_ID,
        name="Дом",
        city="Калининград",
        street="Ленинский проспект",
        house="10",
        postal_code="236000",
        building=None,
        apartment="15",
        delivery_comment=None,
    )
    snapshot = await AddressManager(StubAddressRepository(row)).get_for_order(
        USER_ID, ADDRESS_ID
    )
    assert snapshot.city == "Калининград"
    assert snapshot.apartment == "15"


@pytest.mark.asyncio
async def test_get_for_order_hides_missing_or_foreign_address():
    with pytest.raises(AddressNotFound):
        await AddressManager(StubAddressRepository()).get_for_order(
            USER_ID, ADDRESS_ID
        )


@pytest.mark.asyncio
async def test_create_passes_normalized_name_and_is_not_default():
    repository = MemoryAddressRepository()
    result = await AddressManager(repository).create(
        USER_ID,
        AddressCreate(
            name=" МОЙ   Дом ", city="Калининград", street="Ленина", house="1"
        ),
    )
    assert repository.created["normalized_name"] == "мой дом"
    assert result.is_default is False


@pytest.mark.asyncio
async def test_list_marks_only_repository_default_id():
    repository = MemoryAddressRepository.with_two_rows(default_id=ADDRESS_ID)
    result = await AddressManager(repository).list(USER_ID, " ДОМ ", 20, 0)
    assert [item.is_default for item in result.items] == [True, False]
    assert repository.list_args == (USER_ID, "дом", 20, 0)


@pytest.mark.asyncio
async def test_update_does_not_change_last_used_at():
    repository = MemoryAddressRepository.with_one_row(last_used_at=FIXED_TIME)
    result = await AddressManager(repository).update(
        USER_ID, ADDRESS_ID, AddressUpdate(house="12")
    )
    assert "last_used_at" not in repository.updated_values
    assert result.last_used_at == FIXED_TIME


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["delete", "mark_used"])
async def test_missing_mutation_is_hidden_as_not_found(operation):
    repository = MemoryAddressRepository(mutation_found=False)
    manager = AddressManager(repository, clock=lambda: FIXED_TIME)
    with pytest.raises(AddressNotFound):
        await getattr(manager, operation)(USER_ID, ADDRESS_ID)
