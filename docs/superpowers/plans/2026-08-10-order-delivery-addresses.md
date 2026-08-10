# Order Delivery Addresses Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить пользовательскую адресную книгу, обязательный выбор адреса при оформлении и передачу снимка выбранного адреса в заказ покупателя МойСклад.

**Architecture:** PostgreSQL хранит адреса и время последнего успешного использования; FastAPI предоставляет пользовательский CRUD и единый `OrderCreationManager`, который проверяет адрес до внешних вызовов и передаёт структурированный снимок в МойСклад. Next.js использует общий адресный компонент в checkout и на странице «Мои адреса», а API-контракт и чистые функции адреса вынесены из страниц.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, async SQLAlchemy, PostgreSQL, Alembic, pytest; Next.js 14.1, React 18, TypeScript, React Hook Form, Axios, Tailwind CSS, Vitest, Playwright.

## Global Constraints

- Backend repository: `C:\Users\zenja\IdeaProjects\pix_backend`; frontend repository: `C:\Users\zenja\IdeaProjects\pix_frontend_v2`.
- Public API stays under `/api_v1`; frontend URLs are built only through `backendUrl()`.
- The first release supports Russia only; do not add an editable country field, geocoder, DaData, FIAS, Google Maps, or another dependency.
- Required address fields are `name`, `city`, `street`, and `house`; optional fields are `postal_code`, `building`, `apartment`, and `delivery_comment`.
- Address names are unique per user after trimming, whitespace collapsing, and Unicode case folding.
- A new address is not default until an order using it succeeds in MoySklad.
- Copy the selected address only into the MoySklad customer order; never update the counterparty `actualAddress`.
- Keep `shipmentAddressFull.comment` reserved for the existing Privoz value with a `#` prefix; put the customer courier note in `addInfo`.
- Address ownership checks must return the same `404 address_not_found` for missing and foreign IDs.
- Do not contact production MoySklad, Telegram, Redis, email, or another external service from imports or tests.
- Do not run `alembic upgrade`, `downgrade`, revision autogeneration, or any data repair. Review the migration and history only.
- Preserve unrelated working-tree changes, including tracked `__pycache__` files; every `git add` command below names exact files.
- Backend contract changes require backend `scripts/check.ps1` and frontend `npm.cmd run check` after the final edit.

## File Structure

### Backend

- `db/models/addresses.py` — SQLAlchemy persistence model and database constraints.
- `db/schemas/addresses.py` — validated create/update/read/list transport schemas.
- `db/address_repository.py` — user-scoped PostgreSQL queries, pagination, uniqueness translation, and `last_used_at` mutation.
- `manager/addresses.py` — normalization, CRUD rules, default computation, and immutable order snapshot.
- `routes/addresses.py` — authenticated address HTTP endpoints only.
- `dependecies/addresses.py` — address dependency wiring; keep the repository's existing misspelling.
- `manager/order_creation.py` — complete create-order use case across address, product, customer order, preference, and notification collaborators.
- `manager/moysklad.py` — pure MoySklad delivery payload formatting and customer-order payload extension.
- `db/schemas/orders.py`, `dependecies/orders.py`, `routes/orders.py` — require `address_id` and delegate to `OrderCreationManager`.
- `main.py`, `errors.py`, `alembic/env.py`, `alembic/versions/b7e1d3a9f4c2_add_user_addresses.py`, `scripts/check.ps1` — router/error wiring, migration discovery, migration, and checks.
- `tests/test_address_models.py`, `tests/test_address_schemas.py`, `tests/test_address_repository.py`, `tests/test_addresses.py`, `tests/test_address_api.py`, `tests/test_moysklad_delivery_address.py`, `tests/test_order_creation.py`, `tests/test_order_creation_api.py` — offline backend coverage.

### Frontend

- `src/features/addresses/address.ts` and `address.test.ts` — shared types and pure formatting/selection helpers.
- `src/routes/routes.tsx` — typed address CRUD and the changed order-create request.
- `src/components/addresses/AddressBook.tsx` — shared loading, search, pagination, selection, CRUD, and stale-response protection.
- `src/components/addresses/AddressCard.tsx`, `AddressFormDialog.tsx`, `DeleteAddressDialog.tsx` — focused accessible presentation units.
- `src/app/dashboard/addresses/page.tsx` — standalone «Мои адреса» page.
- `src/app/dashboard/neworder/page.tsx` — checkout selection and guarded order submission.
- `src/components/navbar/navbar.tsx`, `src/app/dashboard/layout.tsx` — navigation and selected segment.
- `tests/mock-backend.mjs`, `tests/addresses.spec.ts`, `tests/new-order-address.spec.ts` — stateful local contract and browser scenarios.

---

### Task 1: Persisted Address Contract and Migration

**Files:**
- Create: `db/models/addresses.py`
- Create: `db/schemas/addresses.py`
- Create: `alembic/versions/b7e1d3a9f4c2_add_user_addresses.py`
- Create: `tests/test_address_models.py`
- Create: `tests/test_address_schemas.py`
- Modify: `alembic/env.py`
- Modify: `scripts/check.ps1`

**Interfaces:**
- Consumes: existing `db.postgres.Base` and `user.id` UUID primary key.
- Produces: `Address`, `AddressCreate`, `AddressUpdate`, `AddressRead`, `AddressListResponse`; Alembic revision `b7e1d3a9f4c2` with parent `c8f2a4e6d901`.

- [ ] **Step 1: Write failing model and schema tests**

```python
# tests/test_address_models.py
from sqlalchemy import UniqueConstraint

from db.models.addresses import Address


def test_address_model_has_user_scoped_normalized_name_constraint():
    constraints = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in Address.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert constraints["uq_address_user_normalized_name"] == (
        "user_id",
        "normalized_name",
    )


def test_address_model_keeps_required_and_optional_fields_distinct():
    columns = Address.__table__.columns
    assert columns.name.nullable is False
    assert columns.city.nullable is False
    assert columns.street.nullable is False
    assert columns.house.nullable is False
    assert columns.postal_code.nullable is True
    assert columns.delivery_comment.nullable is True
```

```python
# tests/test_address_schemas.py
import pytest
from pydantic import ValidationError

from db.schemas.addresses import AddressCreate, AddressUpdate


def valid_address():
    return {
        "name": "  Дом  ",
        "city": "  Калининград ",
        "street": " Ленинский проспект ",
        "house": " 10 ",
        "postal_code": "236000",
    }


def test_create_trims_fields_and_accepts_six_digit_postal_code():
    address = AddressCreate(**valid_address())
    assert address.name == "Дом"
    assert address.city == "Калининград"
    assert address.postal_code == "236000"


@pytest.mark.parametrize("postal_code", ["23600", "2360000", "23A000"])
def test_create_rejects_invalid_postal_code(postal_code):
    with pytest.raises(ValidationError):
        AddressCreate(**{**valid_address(), "postal_code": postal_code})


def test_update_requires_at_least_one_field_and_rejects_null_required_fields():
    with pytest.raises(ValidationError):
        AddressUpdate()
    with pytest.raises(ValidationError):
        AddressUpdate(name=None)
    assert AddressUpdate(apartment=None).model_fields_set == {"apartment"}
```

- [ ] **Step 2: Run the focused tests and confirm they fail because the modules do not exist**

Run from `pix_backend`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_address_models.py tests\test_address_schemas.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'db.models.addresses'`.

- [ ] **Step 3: Add the SQLAlchemy model and Pydantic contracts**

```python
# db/models/addresses.py
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, UUID, UniqueConstraint, func

from db.postgres import Base


class Address(Base):
    __tablename__ = "address"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "normalized_name",
            name="uq_address_user_normalized_name",
        ),
        Index("ix_address_user_last_used", "user_id", "last_used_at"),
    )

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID,
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(100), nullable=False)
    normalized_name = Column(String(100), nullable=False)
    city = Column(String(100), nullable=False)
    street = Column(String(200), nullable=False)
    house = Column(String(30), nullable=False)
    postal_code = Column(String(6))
    building = Column(String(30))
    apartment = Column(String(30))
    delivery_comment = Column(String(500))
    last_used_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
```

Implement `db/schemas/addresses.py` with these exact constrained aliases and public classes:

```python
AddressName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]
City = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]
Street = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
ShortPart = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=30),
]
PostalCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^\d{6}$"),
]
DeliveryCommentValue = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]


class AddressFields(BaseModel):
    name: AddressName
    city: City
    street: Street
    house: ShortPart
    postal_code: PostalCode | None = None
    building: ShortPart | None = None
    apartment: ShortPart | None = None
    delivery_comment: DeliveryCommentValue | None = None

    @field_validator(
        "postal_code",
        "building",
        "apartment",
        "delivery_comment",
        mode="before",
    )
    @classmethod
    def blank_optional_string_is_none(cls, value):
        return None if isinstance(value, str) and not value.strip() else value
```

```python
class AddressCreate(AddressFields):
    pass


class AddressUpdate(BaseModel):
    name: AddressName | None = None
    city: City | None = None
    street: Street | None = None
    house: ShortPart | None = None
    postal_code: PostalCode | None = None
    building: ShortPart | None = None
    apartment: ShortPart | None = None
    delivery_comment: DeliveryCommentValue | None = None

    @field_validator(
        "postal_code",
        "building",
        "apartment",
        "delivery_comment",
        mode="before",
    )
    @classmethod
    def blank_optional_string_is_none(cls, value):
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def require_nonempty_patch(self):
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        required = {"name", "city", "street", "house"}
        if any(
            field in self.model_fields_set and getattr(self, field) is None
            for field in required
        ):
            raise ValueError("required address fields cannot be null")
        return self


class AddressRead(AddressFields):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    is_default: bool
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None


class AddressListResponse(BaseModel):
    items: list[AddressRead]
    total: int
    limit: int
    offset: int
```

Required fields remain nonblank after trimming because their constrained aliases use `min_length=1`.

- [ ] **Step 4: Add and inspect the hand-written migration**

Use revision header:

```python
revision = "b7e1d3a9f4c2"
down_revision = "c8f2a4e6d901"
branch_labels = None
depends_on = None
```

Use this migration body:

```python
def upgrade() -> None:
    op.create_table(
        "address",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("normalized_name", sa.String(length=100), nullable=False),
        sa.Column("city", sa.String(length=100), nullable=False),
        sa.Column("street", sa.String(length=200), nullable=False),
        sa.Column("house", sa.String(length=30), nullable=False),
        sa.Column("postal_code", sa.String(length=6), nullable=True),
        sa.Column("building", sa.String(length=30), nullable=True),
        sa.Column("apartment", sa.String(length=30), nullable=True),
        sa.Column("delivery_comment", sa.String(length=500), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "normalized_name",
            name="uq_address_user_normalized_name",
        ),
    )
    op.create_index("ix_address_user_id", "address", ["user_id"], unique=False)
    op.create_index(
        "ix_address_user_last_used",
        "address",
        ["user_id", "last_used_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_address_user_last_used", table_name="address")
    op.drop_index("ix_address_user_id", table_name="address")
    op.drop_table("address")
```

Import the model in `alembic/env.py`:

```python
from db.models import addresses as addresses
```

Add the new model, schema, migration, and tests to `$ruffTargets` in `scripts/check.ps1`. Do not execute the migration.

- [ ] **Step 5: Run focused tests and migration-history checks**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_address_models.py tests\test_address_schemas.py -q
.\.venv\Scripts\python.exe -m alembic heads
.\.venv\Scripts\python.exe -m alembic history
git diff --check -- db/models/addresses.py db/schemas/addresses.py alembic/env.py alembic/versions/b7e1d3a9f4c2_add_user_addresses.py tests/test_address_models.py tests/test_address_schemas.py scripts/check.ps1
```

Expected: tests pass; exactly one head is `b7e1d3a9f4c2`; history shows `c8f2a4e6d901 -> b7e1d3a9f4c2`.

- [ ] **Step 6: Commit the persistence contract**

```powershell
git add -- db/models/addresses.py db/schemas/addresses.py alembic/env.py alembic/versions/b7e1d3a9f4c2_add_user_addresses.py tests/test_address_models.py tests/test_address_schemas.py scripts/check.ps1
git commit -m "feat: add user address persistence"
```

---

### Task 2: User-Scoped Address Repository and Manager

**Files:**
- Create: `db/address_repository.py`
- Create: `manager/addresses.py`
- Create: `tests/test_address_repository.py`
- Create: `tests/test_addresses.py`
- Modify: `errors.py`
- Modify: `scripts/check.ps1`

**Interfaces:**
- Consumes: `Address`, `AddressCreate`, `AddressUpdate`, `AddressRead`, `AddressListResponse` from Task 1.
- Produces: `AddressRepository`, `AddressManager`, `DeliveryAddressSnapshot`, `normalize_address_name`, `AddressNotFound`, `AddressNameConflict`.

- [ ] **Step 1: Write failing normalization, ownership, default, and statement tests**

```python
# tests/test_addresses.py
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
            (row for row in self.rows if row.user_id == user_id and row.id == address_id),
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
```

```python
# tests/test_address_repository.py
from sqlalchemy.dialects import postgresql

from db.address_repository import build_address_list_statement


def test_list_statement_is_user_scoped_searchable_and_stably_sorted():
    statement = build_address_list_statement(
        user_id="00000000-0000-0000-0000-000000000001",
        search="мой дом",
        limit=20,
        offset=0,
    )
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "address.user_id =" in sql
    assert "address.normalized_name LIKE" in sql
    assert "address.last_used_at DESC NULLS LAST" in sql
    assert "address.updated_at DESC" in sql
    assert "LIMIT 20 OFFSET 0" in sql
```

Add these manager assertions below the in-memory repository:

```python
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
```

- [ ] **Step 2: Run the focused tests and verify missing imports fail**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_address_repository.py tests\test_addresses.py -q
```

Expected: collection fails for missing repository/manager/error classes.

- [ ] **Step 3: Implement domain errors, normalization, snapshots, and manager rules**

Add to `errors.py`:

```python
class AddressNotFound(LookupError):
    pass


class AddressNameConflict(ValueError):
    pass
```

Implement these exact public interfaces in `manager/addresses.py`:

```python
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
        found = await self._repository.mark_used(
            user_id, address_id, self._clock()
        )
        if not found:
            raise AddressNotFound()
```

- [ ] **Step 4: Implement the session-injected PostgreSQL repository**

Implement `AddressRepository(session_factory=async_session_maker)` with these concrete queries:

```python
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

    async def get_for_user(
        self, user_id: UUID, address_id: UUID
    ) -> Address | None:
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
                        .where(Address.id == address_id, Address.user_id == user_id)
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
                    .where(Address.id == address_id, Address.user_id == user_id)
                    .values(last_used_at=used_at, updated_at=func.now())
                )
                return result.rowcount == 1
```

Build the list statement with exact ordering:

```python
def build_address_list_statement(user_id, search, limit, offset):
    statement = select(Address).where(Address.user_id == user_id)
    if search:
        statement = statement.where(
            Address.normalized_name.contains(search, autoescape=True)
        )
    return statement.order_by(
        Address.last_used_at.desc().nullslast(),
        Address.updated_at.desc(),
        Address.id,
    ).limit(limit).offset(offset)


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
    return getattr(getattr(getattr(exc, "orig", None), "diag", None), "constraint_name", None)
```

Import `delete`, `func`, `select`, `update`, `IntegrityError`, `AddressNameConflict`, and the address model explicitly.
All mutations include both ID and user ID; only the named uniqueness constraint is translated, while every other
integrity error is re-raised.

Add both new source files and tests to `scripts/check.ps1`.

- [ ] **Step 5: Run focused tests and lint**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_address_repository.py tests\test_addresses.py -q
.\.venv\Scripts\python.exe -m ruff check db/address_repository.py manager/addresses.py errors.py tests/test_address_repository.py tests/test_addresses.py
```

Expected: all focused tests pass and Ruff reports no errors.

- [ ] **Step 6: Commit repository and business rules**

```powershell
git add -- db/address_repository.py manager/addresses.py errors.py tests/test_address_repository.py tests/test_addresses.py scripts/check.ps1
git commit -m "feat: add address book business rules"
```

---

### Task 3: Authenticated Address HTTP API

**Files:**
- Create: `routes/addresses.py`
- Create: `dependecies/addresses.py`
- Create: `tests/test_address_api.py`
- Modify: `main.py`
- Modify: `scripts/check.ps1`

**Interfaces:**
- Consumes: `AddressManager`, address schemas, `AddressNotFound`, and `AddressNameConflict` from Tasks 1–2.
- Produces: `get_address_manager()` and `/api_v1/addresses` GET/POST/PATCH/DELETE endpoints with stable errors.

- [ ] **Step 1: Write failing API contract tests with dependency overrides**

```python
# tests/test_address_api.py
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from config import Settings
from db.schemas.addresses import AddressListResponse, AddressRead
from dependecies.addresses import get_address_manager
from errors import AddressNameConflict, AddressNotFound
from main import create_app
from routes.users import current_user_dependency

USER_ID = UUID("00000000-0000-0000-0000-000000000001")
ADDRESS_ID = UUID("00000000-0000-0000-0000-000000000010")
NOW = datetime(2026, 8, 10, tzinfo=timezone.utc)


def address_read():
    return AddressRead(
        id=ADDRESS_ID,
        name="Дом",
        city="Калининград",
        street="Ленинский проспект",
        house="10",
        postal_code="236000",
        building=None,
        apartment="15",
        delivery_comment=None,
        is_default=True,
        created_at=NOW,
        updated_at=NOW,
        last_used_at=NOW,
    )


class StubAddressManager:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def maybe_raise(self):
        if self.error:
            raise self.error

    async def list(self, user_id, search, limit, offset):
        self.calls.append(("list", user_id, search, limit, offset))
        self.maybe_raise()
        return AddressListResponse(items=[address_read()], total=1, limit=limit, offset=offset)

    async def create(self, user_id, request):
        self.calls.append(("create", user_id, request))
        self.maybe_raise()
        return address_read()

    async def update(self, user_id, address_id, request):
        self.calls.append(("update", user_id, address_id, request))
        self.maybe_raise()
        return address_read()

    async def delete(self, user_id, address_id):
        self.calls.append(("delete", user_id, address_id))
        self.maybe_raise()


def client_for(manager):
    app = create_app(Settings(_env_file=None, app_env="test"))
    app.dependency_overrides[current_user_dependency] = lambda: SimpleNamespace(id=USER_ID)
    app.dependency_overrides[get_address_manager] = lambda: manager
    return TestClient(app)


def test_list_is_authenticated_paginated_and_user_scoped():
    manager = StubAddressManager()
    with client_for(manager) as client:
        response = client.get("/api_v1/addresses?search=дом&limit=20&offset=0")
    assert response.status_code == 200
    assert response.json()["items"][0]["name"] == "Дом"
    assert manager.calls == [("list", USER_ID, "дом", 20, 0)]


def valid_payload():
    return {
        "name": "Дом",
        "city": "Калининград",
        "street": "Ленинский проспект",
        "house": "10",
    }


def test_create_update_and_delete_status_contracts():
    manager = StubAddressManager()
    with client_for(manager) as client:
        created = client.post("/api_v1/addresses", json=valid_payload())
        updated = client.patch(
            f"/api_v1/addresses/{ADDRESS_ID}", json={"house": "12"}
        )
        deleted = client.delete(f"/api_v1/addresses/{ADDRESS_ID}")
    assert created.status_code == 201
    assert updated.status_code == 200
    assert deleted.status_code == 204
    assert [call[0] for call in manager.calls] == ["create", "update", "delete"]


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (AddressNotFound(), 404, "address_not_found"),
        (AddressNameConflict(), 409, "address_name_conflict"),
    ],
)
def test_domain_errors_have_stable_http_shape(error, status, code):
    with client_for(StubAddressManager(error)) as client:
        response = client.post("/api_v1/addresses", json=valid_payload())
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code


def test_invalid_limit_is_rejected_before_manager_call():
    manager = StubAddressManager()
    with client_for(manager) as client:
        response = client.get("/api_v1/addresses?limit=101")
    assert response.status_code == 422
    assert manager.calls == []


def test_address_api_requires_authentication():
    app = create_app(Settings(_env_file=None, app_env="test"))
    app.dependency_overrides[get_address_manager] = lambda: StubAddressManager()
    with TestClient(app) as client:
        response = client.get("/api_v1/addresses")
    assert response.status_code == 401
```

- [ ] **Step 2: Run the API tests and confirm the router/dependency imports fail**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_address_api.py -q
```

Expected: collection fails for missing `dependecies.addresses` or the route returns `404`.

- [ ] **Step 3: Implement dependency wiring, router, and global error mapping**

```python
# dependecies/addresses.py
from db.address_repository import AddressRepository
from manager.addresses import AddressManager


async def get_address_manager():
    yield AddressManager(AddressRepository())
```

Implement `routes/addresses.py`:

```python
router = APIRouter(prefix="/addresses", tags=["Addresses"])


@router.get("", response_model=AddressListResponse)
async def list_addresses(
    search: str = Query(default="", max_length=100),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(current_user_dependency),
    manager: AddressManager = Depends(get_address_manager),
):
    return await manager.list(user.id, search, limit, offset)


@router.post("", response_model=AddressRead, status_code=201)
async def create_address(
    request: AddressCreate,
    user: User = Depends(current_user_dependency),
    manager: AddressManager = Depends(get_address_manager),
):
    return await manager.create(user.id, request)


@router.patch("/{address_id}", response_model=AddressRead)
async def update_address(
    address_id: UUID,
    request: AddressUpdate,
    user: User = Depends(current_user_dependency),
    manager: AddressManager = Depends(get_address_manager),
):
    return await manager.update(user.id, address_id, request)


@router.delete("/{address_id}", status_code=204)
async def delete_address(
    address_id: UUID,
    user: User = Depends(current_user_dependency),
    manager: AddressManager = Depends(get_address_manager),
):
    await manager.delete(user.id, address_id)
    return Response(status_code=204)
```

Include this router in `main.create_app()`. Add global handlers in `main.py`:

```python
@application.exception_handler(AddressNotFound)
async def address_not_found_handler(request: Request, exc: AddressNotFound):
    return JSONResponse(
        status_code=404,
        content={"detail": {"code": "address_not_found", "message": "Address not found"}},
    )


@application.exception_handler(AddressNameConflict)
async def address_name_conflict_handler(request: Request, exc: AddressNameConflict):
    return JSONResponse(
        status_code=409,
        content={"detail": {"code": "address_name_conflict", "message": "Address name already exists"}},
    )
```

Add new router, dependency, and tests to `scripts/check.ps1`.

- [ ] **Step 4: Run API tests and an offline app import**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_address_api.py tests\test_app.py -q
.\.venv\Scripts\python.exe -c "import main; print(main.app.title)"
```

Expected: tests pass; import prints `Pix Logistic API` without external calls.

- [ ] **Step 5: Commit the address API**

```powershell
git add -- routes/addresses.py dependecies/addresses.py main.py tests/test_address_api.py scripts/check.ps1
git commit -m "feat: expose user address API"
```

---

### Task 4: MoySklad Address Mapping and Order Creation Use Case

**Files:**
- Create: `manager/order_creation.py`
- Create: `tests/test_moysklad_delivery_address.py`
- Create: `tests/test_order_creation.py`
- Create: `tests/test_order_creation_api.py`
- Modify: `tests/test_integrations.py`
- Modify: `db/schemas/orders.py`
- Modify: `db/repository.py`
- Modify: `manager/moysklad.py`
- Modify: `dependecies/orders.py`
- Modify: `routes/orders.py`
- Modify: `scripts/check.ps1`

**Interfaces:**
- Consumes: `DeliveryAddressSnapshot`, `AddressManager.get_for_order()`, `AddressManager.mark_used()`, existing product/customer-order managers and notifier.
- Produces: `OrderCreate.address_id: UUID`, `moysklad_delivery_payload(address) -> dict`, `OrderCreationManager.create(request, user) -> dict`, `get_order_creation_manager()`.

- [ ] **Step 1: Write failing pure mapping and orchestration tests**

Append this regression to `tests/test_integrations.py` so an HTTP error cannot be mistaken for a created entity:

```python
@pytest.mark.asyncio
async def test_moysklad_create_omits_transport_link_and_raises_http_errors(monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs["json"]))
        return FakeMoySkladResponse({"id": "position"})

    settings = Settings(
        _env_file=None,
        app_env="test",
        moysklad_login="login",
        moysklad_password="password",
    )
    monkeypatch.setattr(requests, "post", post)
    repository = MoySkladRepository(settings)
    repository.model = "entity/customerorder"

    await repository.create(link="order/positions", quantity=2)
    assert calls[0][0].endswith("/entity/customerorder/order/positions")
    assert calls[0][1] == {"quantity": 2}

    monkeypatch.setattr(
        requests,
        "post",
        lambda *args, **kwargs: FakeMoySkladResponse(status_code=503),
    )
    with pytest.raises(requests.HTTPError):
        await repository.create(positions=[])
```

```python
# tests/test_moysklad_delivery_address.py
from manager.addresses import DeliveryAddressSnapshot
from manager.moysklad import moysklad_delivery_payload


def test_moysklad_payload_is_structured_and_preserves_privoz_comment():
    payload = moysklad_delivery_payload(
        DeliveryAddressSnapshot(
            name="Дом",
            city="Калининград",
            street="Ленинский проспект",
            house="10",
            postal_code="236000",
            building="корп. 2",
            apartment="15",
            delivery_comment="Позвонить за 10 минут",
        )
    )
    assert payload["shipmentAddress"] == (
        "236000, Россия, Калининград, Ленинский проспект, дом 10, "
        "корп. 2, кв./офис 15"
    )
    assert payload["shipmentAddressFull"] == {
        "postalCode": "236000",
        "city": "Калининград",
        "street": "Ленинский проспект",
        "house": "10, корп. 2",
        "apartment": "15",
        "addInfo": "Позвонить за 10 минут",
    }
    assert "comment" not in payload["shipmentAddressFull"]
```

```python
# tests/test_order_creation.py
from types import SimpleNamespace
from uuid import UUID

import pytest

from db.schemas.orders import OrderCreate
from errors import AddressNotFound
from manager.addresses import DeliveryAddressSnapshot
from manager.order_creation import OrderCreationManager

ADDRESS_ID = UUID("00000000-0000-0000-0000-000000000010")
SNAPSHOT = DeliveryAddressSnapshot(
    name="Дом",
    city="Калининград",
    street="Ленинский проспект",
    house="10",
    postal_code=None,
    building=None,
    apartment=None,
    delivery_comment=None,
)


def make_request():
    return OrderCreate(
        address_id=ADDRESS_ID,
        order_items=[
            {"link": "https://shop.example/item", "count": 2, "comment": ""}
        ],
    )


def make_user():
    return SimpleNamespace(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        first_name="Иван",
        name_id=7,
        moysklad_counterparty_meta={"href": "counterparty"},
    )


class StubAddresses:
    def __init__(self, events, get_error=None, mark_error=None):
        self.events = events
        self.get_error = get_error
        self.mark_error = mark_error

    async def get_for_order(self, user_id, address_id):
        self.events.append("address:get")
        if self.get_error:
            raise self.get_error
        return SNAPSHOT

    async def mark_used(self, user_id, address_id):
        self.events.append("address:mark")
        if self.mark_error:
            raise self.mark_error


class StubProducts:
    def __init__(self, events, error=None):
        self.events = events
        self.error = error

    async def create_products(self, request, user):
        self.events.append("products:create")
        if self.error:
            raise self.error
        return [{"meta": {"href": "product-meta"}}]


class StubCustomerOrders:
    def __init__(self, events, error=None):
        self.events = events
        self.error = error
        self.arguments = None

    async def create_order_by_request(self, positions, user, address):
        self.events.append("order:create")
        self.arguments = (positions, user, address)
        if self.error:
            raise self.error
        return {"id": "moysklad-order", "meta": {"uuidHref": "https://moysklad/order"}}


class StubNotifier:
    def __init__(self, events, error=None):
        self.events = events
        self.error = error

    async def send_group_message(self, message):
        self.events.append("notify")
        if self.error:
            raise self.error


@pytest.mark.asyncio
async def test_order_creation_validates_address_before_products_and_marks_only_after_order():
    events = []
    addresses = StubAddresses(events)
    products = StubProducts(events)
    orders = StubCustomerOrders(events)
    notifier = StubNotifier(events)
    result = await OrderCreationManager(addresses, products, orders, notifier).create(
        make_request(), make_user()
    )
    assert result["id"] == "moysklad-order"
    assert events == ["address:get", "products:create", "order:create", "address:mark", "notify"]
    assert orders.arguments[0] == [
        {"count": 2, "moysklad_product_meta": {"href": "product-meta"}}
    ]


@pytest.mark.asyncio
async def test_address_failure_stops_before_products_and_order():
    events = []
    manager = OrderCreationManager(
        StubAddresses(events, get_error=AddressNotFound()),
        StubProducts(events),
        StubCustomerOrders(events),
        StubNotifier(events),
    )
    with pytest.raises(AddressNotFound):
        await manager.create(make_request(), make_user())
    assert events == ["address:get"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_stage", ["products", "order"])
async def test_external_failure_does_not_mark_or_notify(failing_stage):
    events = []
    error = RuntimeError("external unavailable")
    products = StubProducts(events, error=error if failing_stage == "products" else None)
    orders = StubCustomerOrders(events, error=error if failing_stage == "order" else None)
    manager = OrderCreationManager(
        StubAddresses(events), products, orders, StubNotifier(events)
    )
    with pytest.raises(RuntimeError):
        await manager.create(make_request(), make_user())
    assert "address:mark" not in events
    assert "notify" not in events


@pytest.mark.asyncio
@pytest.mark.parametrize("secondary_failure", ["mark", "notify"])
async def test_secondary_failure_does_not_turn_created_order_into_failure(secondary_failure):
    events = []
    error = RuntimeError("secondary unavailable")
    manager = OrderCreationManager(
        StubAddresses(events, mark_error=error if secondary_failure == "mark" else None),
        StubProducts(events),
        StubCustomerOrders(events),
        StubNotifier(events, error=error if secondary_failure == "notify" else None),
    )
    result = await manager.create(make_request(), make_user())
    assert result["id"] == "moysklad-order"
```

- [ ] **Step 2: Write failing HTTP tests for required `address_id` and route delegation**

```python
# tests/test_order_creation_api.py
from types import SimpleNamespace

from fastapi.testclient import TestClient

from config import Settings
from dependecies.orders import get_order_creation_manager
from main import create_app
from routes.users import current_user_dependency


class StubOrderCreationManager:
    def __init__(self):
        self.calls = []

    async def create(self, request, user):
        self.calls.append((request, user))
        return {"id": "moysklad-order"}


def valid_payload():
    return {
        "address_id": "00000000-0000-0000-0000-000000000010",
        "order_items": [
            {"link": "https://shop.example/item", "count": 1, "comment": ""}
        ],
    }


def order_client(manager, authenticated=True):
    app = create_app(Settings(_env_file=None, app_env="test"))
    user = SimpleNamespace(id="user")
    if authenticated:
        app.dependency_overrides[current_user_dependency] = lambda: user
    app.dependency_overrides[get_order_creation_manager] = lambda: manager
    return TestClient(app)


def test_create_order_delegates_complete_request_to_use_case():
    manager = StubOrderCreationManager()
    with order_client(manager) as client:
        response = client.post("/api_v1/orders", json=valid_payload())
    assert response.status_code == 200
    assert manager.calls[0][0].address_id is not None


def test_create_order_rejects_missing_address_before_use_case():
    manager = StubOrderCreationManager()
    payload = valid_payload()
    payload.pop("address_id")
    with order_client(manager) as client:
        response = client.post("/api_v1/orders", json=payload)
    assert response.status_code == 422
    assert manager.calls == []


def test_create_order_requires_authentication():
    manager = StubOrderCreationManager()
    with order_client(manager, authenticated=False) as client:
        response = client.post("/api_v1/orders", json=valid_payload())
    assert response.status_code == 401
    assert manager.calls == []
```

- [ ] **Step 3: Run focused tests and confirm missing mapping/use-case failures**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_integrations.py tests\test_moysklad_delivery_address.py tests\test_order_creation.py tests\test_order_creation_api.py -q
```

Expected: imports or assertions fail before production implementation exists.

- [ ] **Step 4: Implement exact MoySklad formatting**

First make `MoySkladRepository.create` distinguish successful and failed HTTP responses:

```python
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
```

Add to `manager/moysklad.py`:

```python
def moysklad_delivery_payload(address: DeliveryAddressSnapshot) -> dict:
    parts = []
    if address.postal_code:
        parts.append(address.postal_code)
    parts.extend(["Россия", address.city, address.street, f"дом {address.house}"])
    if address.building:
        parts.append(address.building)
    if address.apartment:
        parts.append(f"кв./офис {address.apartment}")

    full = {
        "city": address.city,
        "street": address.street,
        "house": ", ".join(
            value for value in (address.house, address.building) if value
        ),
    }
    if address.postal_code:
        full["postalCode"] = address.postal_code
    if address.apartment:
        full["apartment"] = address.apartment
    if address.delivery_comment:
        full["addInfo"] = address.delivery_comment
    return {"shipmentAddress": ", ".join(parts), "shipmentAddressFull": full}
```

Change `CustomerOrderManager.create_order_by_request` to accept
`delivery_address: DeliveryAddressSnapshot`, and merge `moysklad_delivery_payload(delivery_address)` into the
customer-order dict before `self.__repo.create(**customer_order)`. Do not set counterparty fields and do not set
`shipmentAddressFull.comment`.

- [ ] **Step 5: Implement `OrderCreationManager` and dependency wiring**

`db/schemas/orders.py` adds `address_id: UUID` to `OrderCreate`.

Implement `manager/order_creation.py` with this public method and order:

```python
class OrderCreationManager:
    def __init__(self, addresses, products, customer_orders, notifier, logger=None):
        self._addresses = addresses
        self._products = products
        self._customer_orders = customer_orders
        self._notifier = notifier
        self._logger = logger or logging.getLogger(__name__)

    async def create(self, request: OrderCreate, user: User) -> dict:
        address = await self._addresses.get_for_order(user.id, request.address_id)
        products = await self._products.create_products(request, user)
        positions = [
            {"count": item.count, "moysklad_product_meta": product["meta"]}
            for product, item in zip(products, request.order_items)
        ]
        order = await self._customer_orders.create_order_by_request(
            positions, user, address
        )
        try:
            await self._addresses.mark_used(user.id, request.address_id)
        except Exception:
            self._logger.exception("failed to mark delivery address as used")
        try:
            await self._notifier.send_group_message(build_new_order_message(order, user))
        except Exception:
            self._logger.exception("failed to send new order notification")
        return order
```

Implement `build_new_order_message(order, user)` in the same file using the existing Russian message content and
MoySklad `meta.uuidHref`; escape `user.first_name` before embedding it in HTML. Do not include address fields in logs
or Telegram.

Add `get_order_creation_manager()` to `dependecies/orders.py` using `AddressManager(AddressRepository())`, existing
`ProductManager(ProductRepository())`, `CustomerOrderManager(CustomerOrderRepository())`, and `telegram_sender`.
Replace the current `routes.orders.create_order` body and its product/customer-order dependencies with one
`OrderCreationManager = Depends(get_order_creation_manager)` call.

Add all new files/tests to `scripts/check.ps1`.

- [ ] **Step 6: Run focused and existing order tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_integrations.py tests\test_moysklad_delivery_address.py tests\test_order_creation.py tests\test_order_creation_api.py tests\test_order_changes.py tests\test_order_changes_api.py -q
.\.venv\Scripts\python.exe -m ruff check db/repository.py db/schemas/orders.py manager/moysklad.py manager/order_creation.py dependecies/orders.py routes/orders.py tests/test_integrations.py tests/test_moysklad_delivery_address.py tests/test_order_creation.py tests/test_order_creation_api.py
```

Expected: all selected tests pass; no test performs a live external request.

- [ ] **Step 7: Commit the order integration**

```powershell
git add -- db/repository.py db/schemas/orders.py manager/moysklad.py manager/order_creation.py dependecies/orders.py routes/orders.py tests/test_integrations.py tests/test_moysklad_delivery_address.py tests/test_order_creation.py tests/test_order_creation_api.py scripts/check.ps1
git commit -m "feat: attach delivery address to orders"
```

---

### Task 5: Frontend Address Domain and Typed API Client

**Files:**
- Create: `src/features/addresses/address.ts`
- Create: `src/features/addresses/address.test.ts`
- Modify: `src/routes/routes.tsx`

**Interfaces:**
- Consumes: backend `AddressRead`, `AddressListResponse`, address CRUD, and changed order payload.
- Produces: `Address`, `AddressInput`, `AddressPage`, `formatAddress`, `defaultAddressId`, `selectionAfterDelete`, `GetAddresses`, `CreateAddress`, `UpdateAddress`, `DeleteAddress`, and `CreateOrder(data, addressId)`.

- [ ] **Step 1: Write failing pure domain tests**

```typescript
// src/features/addresses/address.test.ts
import { describe, expect, it } from "vitest";
import {
  defaultAddressId,
  formatAddress,
  selectionAfterDelete,
  type Address,
} from "./address";

const home: Address = {
  id: "home",
  name: "Дом",
  city: "Калининград",
  street: "Ленинский проспект",
  house: "10",
  postal_code: "236000",
  building: "корп. 2",
  apartment: "15",
  delivery_comment: null,
  is_default: true,
  created_at: "2026-08-10T10:00:00Z",
  updated_at: "2026-08-10T10:00:00Z",
  last_used_at: "2026-08-10T11:00:00Z",
};

describe("address helpers", () => {
  it("formats only present address parts", () => {
    expect(formatAddress(home)).toBe(
      "236000, Россия, Калининград, Ленинский проспект, дом 10, корп. 2, кв./офис 15",
    );
  });

  it("selects the server default and keeps an existing selection", () => {
    expect(defaultAddressId([home], null)).toBe("home");
    expect(defaultAddressId([home], "manual")).toBe("manual");
  });

  it("falls back to the remaining default only when selected address is deleted", () => {
    expect(selectionAfterDelete("home", "home", [Object.assign({}, home, { id: "work" })])).toBe("work");
    expect(selectionAfterDelete("manual", "home", [])).toBe("manual");
  });
});
```

- [ ] **Step 2: Run the unit test and verify the missing module failure**

Run from `pix_frontend_v2`:

```powershell
npm.cmd run test:unit -- src/features/addresses/address.test.ts
```

Expected: Vitest fails because `./address` does not exist.

- [ ] **Step 3: Implement types and pure helpers**

```typescript
// src/features/addresses/address.ts
export type Address = {
  id: string;
  name: string;
  city: string;
  street: string;
  house: string;
  postal_code: string | null;
  building: string | null;
  apartment: string | null;
  delivery_comment: string | null;
  is_default: boolean;
  created_at: string;
  updated_at: string;
  last_used_at: string | null;
};

export type AddressInput = Omit<
  Address,
  "id" | "is_default" | "created_at" | "updated_at" | "last_used_at"
>;

export type AddressPage = {
  items: Address[];
  total: number;
  limit: number;
  offset: number;
};
```

`formatAddress` joins the exact parts asserted above and omits null/blank optional parts. `defaultAddressId` returns
the existing selected ID unchanged, otherwise the first `is_default` ID or `null`. `selectionAfterDelete` changes
selection only when `deletedId === selectedId`, then returns the remaining `is_default` ID or `null`.

- [ ] **Step 4: Add typed API functions and change order creation**

In `src/routes/routes.tsx`, export:

```typescript
export function GetAddresses(
  params: { search?: string; limit?: number; offset?: number },
  signal?: AbortSignal,
) {
  return axios.get<AddressPage>(backendUrl("addresses"), {
    params,
    signal,
    headers: { Authorization: getCookie("token") },
  });
}

export function CreateAddress(payload: AddressInput) {
  return axios.post<Address>(backendUrl("addresses"), payload, {
    headers: { Authorization: getCookie("token") },
  });
}

export function UpdateAddress(id: string, payload: Partial<AddressInput>) {
  return axios.patch<Address>(backendUrl(`addresses/${id}`), payload, {
    headers: { Authorization: getCookie("token") },
  });
}

export function DeleteAddress(id: string) {
  return axios.delete(backendUrl(`addresses/${id}`), {
    headers: { Authorization: getCookie("token") },
  });
}
```

Change the existing signature and body to:

```typescript
export async function CreateOrder(data: OrderData[], addressId: string) {
  const promise = axios.post(
    backendUrl("orders"),
    { address_id: addressId, order_items: data },
    { headers: { Authorization: getCookie("token") } },
  );
  return toast.promise(promise, {
    loading: "Создаём заказ",
    success: "Успешно!",
    error: "Ошибка!",
  });
}
```

- [ ] **Step 5: Run unit tests and lint**

```powershell
npm.cmd run test:unit -- src/features/addresses/address.test.ts
npm.cmd run lint
```

Expected: unit tests pass; lint adds no new errors or warnings.

- [ ] **Step 6: Commit the frontend domain contract**

```powershell
git add -- src/features/addresses/address.ts src/features/addresses/address.test.ts src/routes/routes.tsx
git commit -m "feat: add address frontend contracts"
```

---

### Task 6: Shared Address UI and «Мои адреса» Page

**Files:**
- Create: `src/components/addresses/AddressBook.tsx`
- Create: `src/components/addresses/AddressCard.tsx`
- Create: `src/components/addresses/AddressFormDialog.tsx`
- Create: `src/components/addresses/DeleteAddressDialog.tsx`
- Create: `src/app/dashboard/addresses/page.tsx`
- Create: `tests/addresses.spec.ts`
- Modify: `src/components/navbar/navbar.tsx`
- Modify: `src/app/dashboard/layout.tsx`
- Modify: `tests/mock-backend.mjs`

**Interfaces:**
- Consumes: types/helpers/API functions from Task 5.
- Produces: reusable `AddressBook` with props `selectable`, `selectedAddressId`, `onSelectionChange`,
  `autoSelectDefault`, and `reloadKey`; route `/dashboard/addresses`; navigation enum `addresses`.

- [ ] **Step 1: Extend the local mock contract and write a failing browser scenario**

Add mutable address fixtures to `tests/mock-backend.mjs` with default `Дом` and previously used `Офис` whose
`last_used_at` is older. Implement:

- `POST /api_v1/test/reset-addresses` to restore fixtures;
- `GET /api_v1/addresses` with case-insensitive substring filtering by `search`, `limit`, `offset`, and the agreed page shape;
- `POST /api_v1/addresses` returning `201`, assigning a deterministic ID, rejecting duplicate normalized names with `409`;
- `PATCH /api_v1/addresses/{id}` returning the edited item;
- `DELETE /api_v1/addresses/{id}` returning `204` and recomputing `is_default` from remaining `last_used_at` values;
- include `PATCH` in `Access-Control-Allow-Methods`.

```typescript
// tests/addresses.spec.ts
import { expect, test } from "@playwright/test";

test.beforeEach(async ({ context, request }) => {
  await request.post("http://127.0.0.1:8100/api_v1/test/reset-addresses");
  await context.addCookies([
    { name: "token", value: "Bearer test-token", url: "http://127.0.0.1:3100" },
  ]);
});

test("searches creates edits and deletes addresses", async ({ page }) => {
  await page.goto("/dashboard/addresses");
  await expect(page.getByRole("heading", { name: "Мои адреса" })).toBeVisible();
  await expect(page.getByText("Дом")).toBeVisible();
  await expect(page.getByText("По умолчанию")).toBeVisible();

  await page.getByPlaceholder("Поиск по названию").fill("офис");
  await expect(page.getByText("Офис")).toBeVisible();
  await expect(page.getByText("Дом")).toHaveCount(0);

  await page.getByPlaceholder("Поиск по названию").fill("");
  await page.getByRole("button", { name: "Добавить адрес" }).click();
  await page.getByLabel("Название").fill("Родители");
  await page.getByLabel("Город или населённый пункт").fill("Калининград");
  await page.getByLabel("Улица").fill("Театральная");
  await page.getByLabel("Дом").fill("5");
  await page.getByRole("button", { name: "Сохранить адрес" }).click();
  await expect(page.getByText("Родители")).toBeVisible();

  await page.getByRole("article", { name: "Адрес Родители" }).getByRole("button", { name: "Изменить" }).click();
  await page.getByLabel("Дом").fill("7");
  await page.getByRole("button", { name: "Сохранить адрес" }).click();
  await expect(page.getByText(/дом 7/)).toBeVisible();

  await page.getByRole("article", { name: "Адрес Родители" }).getByRole("button", { name: "Удалить" }).click();
  await page.getByRole("dialog", { name: "Удалить адрес Родители" }).getByRole("button", { name: "Удалить" }).click();
  await expect(page.getByText("Родители")).toHaveCount(0);
});
```

Add these explicit browser checks:

```typescript
test("shows duplicate-name and empty-search states", async ({ page }) => {
  await page.goto("/dashboard/addresses");
  await page.getByRole("button", { name: "Добавить адрес" }).click();
  await page.getByLabel("Название").fill(" дом ");
  await page.getByLabel("Город или населённый пункт").fill("Калининград");
  await page.getByLabel("Улица").fill("Ленина");
  await page.getByLabel("Дом").fill("1");
  await page.getByRole("button", { name: "Сохранить адрес" }).click();
  await expect(page.getByText("Адрес с таким названием уже существует")).toBeVisible();

  await page.getByRole("button", { name: "Отмена" }).click();
  await page.getByPlaceholder("Поиск по названию").fill("неизвестный адрес");
  await expect(page.getByText("Адреса с таким названием не найдены")).toBeVisible();
});


test("address page fits a mobile viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/dashboard/addresses");
  await expect(page.getByRole("heading", { name: "Мои адреса" })).toBeVisible();
  const sizes = await page.evaluate(() => ({
    documentWidth: document.documentElement.scrollWidth,
    viewportWidth: window.innerWidth,
  }));
  expect(sizes.documentWidth).toBeLessThanOrEqual(sizes.viewportWidth);
});
```

- [ ] **Step 2: Run the browser test and confirm `/dashboard/addresses` is missing**

```powershell
npx.cmd playwright test tests/addresses.spec.ts
```

Expected: failure because the page/heading and components do not exist.

- [ ] **Step 3: Implement accessible focused presentation components**

`AddressCard` must render `<article aria-label={`Адрес ${address.name}`}>`, the title, `formatAddress(address)`, the
optional «По умолчанию» badge, and buttons «Изменить»/«Удалить». When `selectable` is true, the article also exposes
a radio control or button with an accessible selected state and calls `onSelect(address.id)`.

`AddressFormDialog` uses `react-hook-form<AddressInput>`, `role="dialog"`, `aria-modal="true"`, the exact labels used
in the browser test, visible `Россия`, and these rules:

```typescript
const required = { required: "Обязательное поле" };
const postalCode = {
  pattern: { value: /^\d{6}$/, message: "Индекс должен содержать 6 цифр" },
};
```

It calls `CreateAddress` or `UpdateAddress`, keeps the dialog open on failure, maps
`address_name_conflict` to the name field, and calls `onSaved(response.data)` on success. Optional blank strings are
sent as `null`.

`DeleteAddressDialog` names the address in its accessible title, calls `DeleteAddress`, disables both dialog actions
while pending, and calls `onDeleted(address.id)` only after `204`.

- [ ] **Step 4: Implement `AddressBook` data flow without stale search results**

Use this public contract:

```typescript
export type AddressBookProps = {
  selectable?: boolean;
  selectedAddressId?: string | null;
  onSelectionChange?: (id: string | null) => void;
  autoSelectDefault?: boolean;
  reloadKey?: number;
};
```

The concrete implementation keeps `items`, `total`, `search`, debounced search, `offset`, `loading`, edit/delete
targets, and dialog state. Every load creates an `AbortController`; cleanup aborts the old request. A 300 ms effect
updates the debounced search. A fresh search replaces items at offset 0; «Загрузить ещё» appends de-duplicated IDs.
After the unfiltered first load, call `onSelectionChange(defaultAddressId(items, selectedAddressId))` only when
`autoSelectDefault !== false` and the returned ID differs. Include `reloadKey` in the load dependencies. Do not clear
selection when a search hides the selected card. After create, insert/replace the row and select it when `selectable`;
after update, replace it. After delete, reload the current page and also request
`GetAddresses({ search: "", limit: 1, offset: 0 })`; use the refreshed first item only when it has
`is_default: true`, then pass that item with the refreshed current rows to
`selectionAfterDelete(selectedAddressId, deletedId, remaining)`. This extra unfiltered read makes deletion of the
current default select the next server-computed default even when the active search hides it.

Render exact states:

- no addresses: «Добавьте адрес доставки, чтобы оформить заказ»;
- no search matches: «Адреса с таким названием не найдены»;
- request failure: `role="alert"` with «Не удалось загрузить адреса» and «Повторить»;
- primary action: «Добавить адрес»;
- pagination action: «Загрузить ещё» only while `items.length < total`.

- [ ] **Step 5: Add the standalone page and navigation**

```typescript
// src/app/dashboard/addresses/page.tsx
"use client";

import AddressBook from "@/components/addresses/AddressBook";

export default function AddressesPage() {
  return (
    <main className="min-h-screen px-4 pb-8 pt-24 lg:px-8">
      <section className="mx-auto max-w-5xl rounded-2xl bg-white p-4 shadow-xl lg:p-6">
        <h1 className="mb-4 text-2xl font-bold">Мои адреса</h1>
        <AddressBook />
      </section>
    </main>
  );
}
```

Add `addresses = "addresses"` to `NavbarLinkEnum`, an enabled «Мои адреса» item with a location icon in the profile
section, and `segment == NavbarLinkEnum.addresses` to the selected-layout condition.

Keep navigation usable without horizontal overflow at the approved mobile viewport: change each dashboard sidebar
wrapper to `w-16 lg:w-[288px]`, each content wrapper to `min-w-0 flex-1 ml-16 lg:ml-[288px]`, and the Navbar inner
width to `w-16 lg:w-72`. Give every `NavItem` link `aria-label={title}`, render its visible title in
`<span className="hidden lg:inline">`, hide section headings and the PIX Logistic wordmark below `lg`, and use
`px-4 lg:px-8` on links. Icons remain visible, so all destinations including «Мои адреса» remain reachable on
mobile and desktop.

- [ ] **Step 6: Run the focused browser test, unit tests, and lint**

```powershell
npx.cmd playwright test tests/addresses.spec.ts
npm.cmd run test:unit
npm.cmd run lint
```

Expected: address scenarios pass on desktop/mobile; all unit tests pass; no new lint warning.

- [ ] **Step 7: Commit shared address UI and page**

```powershell
git add -- src/components/addresses/AddressBook.tsx src/components/addresses/AddressCard.tsx src/components/addresses/AddressFormDialog.tsx src/components/addresses/DeleteAddressDialog.tsx src/app/dashboard/addresses/page.tsx src/components/navbar/navbar.tsx src/app/dashboard/layout.tsx tests/mock-backend.mjs tests/addresses.spec.ts
git commit -m "feat: add address book interface"
```

---

### Task 7: Checkout Address Selection and Safe Submission

**Files:**
- Create: `tests/new-order-address.spec.ts`
- Modify: `src/app/dashboard/neworder/page.tsx`
- Modify: `tests/mock-backend.mjs`

**Interfaces:**
- Consumes: `AddressBook` from Task 6 and `CreateOrder(data, addressId)` from Task 5.
- Produces: required checkout selection, one-submit guard, preserved cart on error, and successful order payload containing `address_id`.

- [ ] **Step 1: Add order-create behavior to the mock and write failing browser tests**

Change the existing `/api_v1/orders` mock branch to distinguish methods: `GET` returns the order list; `POST` reads
and stores the payload, returns `503` for deterministic address ID `address-failure`, returns
`404 address_not_found` for `address-deleted`, and otherwise returns `{ id: "new-order" }`. Add test-only
`GET /api_v1/test/last-created-order` and reset its value in `POST /api_v1/test/reset-addresses`. Include selectable
fixtures named «Сбой» (`address-failure`) and «Удалённый» (`address-deleted`); remove `address-deleted` from the
mock list immediately before returning its `404`. Let the reset endpoint accept `{ "empty": true }` for the empty
address-book scenario.

```typescript
// tests/new-order-address.spec.ts
import { expect, test } from "@playwright/test";


async function seedCart(page) {
  await page.addInitScript(() => {
    localStorage.setItem(
      "cart",
      JSON.stringify([
        { position: "https://shop.example/item", count: 1, comment: "" },
      ]),
    );
  });
}

test.beforeEach(async ({ context, request }) => {
  await request.post("http://127.0.0.1:8100/api_v1/test/reset-addresses");
  await context.addCookies([
    { name: "token", value: "Bearer test-token", url: "http://127.0.0.1:3100" },
  ]);
});

test("selects default and creates exactly one order with address_id", async ({ page, request }) => {
  await seedCart(page);
  const posts: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/api_v1/orders")) posts.push(request.url());
  });

  await page.goto("/dashboard/neworder");
  await expect(page.getByRole("heading", { name: "Адрес доставки" })).toBeVisible();
  await expect(page.getByRole("radio", { name: /Дом/ })).toBeChecked();
  const submit = page.getByRole("button", { name: "Оформить" });
  await submit.dblclick();
  await expect(page).toHaveURL(/\/dashboard\/orders$/);
  expect(posts).toHaveLength(1);

  const saved = await request.get("http://127.0.0.1:8100/api_v1/test/last-created-order");
  expect(await saved.json()).toMatchObject({ address_id: "address-home" });
});


test("requires an address and selects a newly created one", async ({ page, request }) => {
  await request.post("http://127.0.0.1:8100/api_v1/test/reset-addresses", {
    data: { empty: true },
  });
  await seedCart(page);
  await page.goto("/dashboard/neworder");
  await expect(page.getByRole("button", { name: "Оформить" })).toBeDisabled();
  await page.getByRole("button", { name: "Добавить адрес" }).click();
  await page.getByLabel("Название").fill("Родители");
  await page.getByLabel("Город или населённый пункт").fill("Калининград");
  await page.getByLabel("Улица").fill("Театральная");
  await page.getByLabel("Дом").fill("5");
  await page.getByRole("button", { name: "Сохранить адрес" }).click();
  await expect(page.getByRole("radio", { name: /Родители/ })).toBeChecked();
  await expect(page.getByRole("button", { name: "Оформить" })).toBeEnabled();
});


test("keeps cart and selection when order creation fails", async ({ page }) => {
  await seedCart(page);
  await page.goto("/dashboard/neworder");
  await page.getByRole("radio", { name: /Сбой/ }).check();
  await page.getByRole("button", { name: "Оформить" }).click();
  await expect(page).toHaveURL(/\/dashboard\/neworder$/);
  await expect(page.getByRole("radio", { name: /Сбой/ })).toBeChecked();
  await expect(page.getByText("https://shop.example/item")).toBeVisible();
  await expect(page.getByRole("alert")).toContainText("Корзина сохранена");
});


test("reloads after selected address was deleted", async ({ page }) => {
  await seedCart(page);
  await page.goto("/dashboard/neworder");
  await page.getByRole("radio", { name: /Удалённый/ }).check();
  await page.getByRole("button", { name: "Оформить" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Адрес был удалён. Выберите другой адрес",
  );
  await expect(page.getByRole("radio", { name: /Удалённый/ })).toHaveCount(0);
  await expect(page.getByRole("radio", { checked: true })).toHaveCount(0);
});


test("deleting the selected default chooses the next server default", async ({ page }) => {
  await seedCart(page);
  await page.goto("/dashboard/neworder");
  const home = page.getByRole("article", { name: "Адрес Дом" });
  await expect(home.getByRole("radio")).toBeChecked();
  await home.getByRole("button", { name: "Удалить" }).click();
  await page
    .getByRole("dialog", { name: "Удалить адрес Дом" })
    .getByRole("button", { name: "Удалить" })
    .click();
  await expect(page.getByRole("radio", { name: /Офис/ })).toBeChecked();
});
```

- [ ] **Step 2: Run the focused browser tests and confirm checkout lacks address selection**

```powershell
npx.cmd playwright test tests/new-order-address.spec.ts
```

Expected: failure because «Адрес доставки» and selected address do not exist and order payload lacks `address_id`.

- [ ] **Step 3: Integrate shared address selection into checkout**

In `NewOrder`, add:

```typescript
const [selectedAddressId, setSelectedAddressId] = useState<string | null>(null);
const [isSubmitting, setIsSubmitting] = useState(false);
const [orderError, setOrderError] = useState<string | null>(null);
const [addressReloadKey, setAddressReloadKey] = useState(0);
const [autoSelectDefault, setAutoSelectDefault] = useState(true);
const submittingRef = useRef(false);

const handleAddressSelection = (id: string | null) => {
  setSelectedAddressId(id);
  if (id !== null) setAutoSelectDefault(true);
};
```

Render a section headed «Адрес доставки» before the clear/submit actions:

```tsx
<section aria-labelledby="delivery-address-heading" className="rounded-xl border p-3">
  <h2 id="delivery-address-heading" className="mb-3 text-xl font-bold">
    Адрес доставки
  </h2>
  <AddressBook
    selectable
    selectedAddressId={selectedAddressId}
    onSelectionChange={handleAddressSelection}
    autoSelectDefault={autoSelectDefault}
    reloadKey={addressReloadKey}
  />
</section>
```

Replace the promise chain with a guarded async function:

```typescript
const submitOrder = async () => {
  if (submittingRef.current || data.length === 0 || !selectedAddressId) return;
  submittingRef.current = true;
  setIsSubmitting(true);
  setOrderError(null);
  try {
    await CreateOrder(
      data.map((item) => ({
        link: item.position,
        count: item.count,
        comment: item.comment || "",
      })),
      selectedAddressId,
    );
    localStorage.removeItem("cart");
    setData([]);
    router.replace("/dashboard/orders");
  } catch (error) {
    const code = isAxiosError<{ detail?: { code?: string } }>(error)
      ? error.response?.data?.detail?.code
      : undefined;
    if (code === "address_not_found") {
      setAutoSelectDefault(false);
      setSelectedAddressId(null);
      setAddressReloadKey((value) => value + 1);
      setOrderError("Адрес был удалён. Выберите другой адрес");
    } else {
      setOrderError("Не удалось оформить заказ. Корзина сохранена, попробуйте ещё раз");
    }
  } finally {
    submittingRef.current = false;
    setIsSubmitting(false);
  }
};
```

Give the error `role="alert"`. Set the `PixButton` disabled condition to
`isSubmitting || data.length === 0 || selectedAddressId === null`, and show «Оформляем» while pending. Remove
the existing debug `console.log` calls. Keep the cart in `localStorage` on all failures.

The `reloadKey` increment performs an explicit address-list reload without refreshing the page. Passing
`autoSelectDefault={false}` after `address_not_found` prevents the reloaded list from silently choosing a different
address while the alert asks the user to make a new choice.

- [ ] **Step 4: Run checkout browser tests and all frontend tests**

```powershell
npx.cmd playwright test tests/new-order-address.spec.ts tests/addresses.spec.ts
npm.cmd run test:unit
npm.cmd run lint
```

Expected: all address/checkout scenarios and unit tests pass; no new lint warning.

- [ ] **Step 5: Commit checkout integration**

```powershell
git add -- src/app/dashboard/neworder/page.tsx src/components/addresses/AddressBook.tsx tests/mock-backend.mjs tests/new-order-address.spec.ts
git commit -m "feat: require delivery address at checkout"
```

---

### Task 8: Architecture Documentation and Full Verification

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Verify only: all backend and frontend files changed in Tasks 1–7

**Interfaces:**
- Consumes: completed backend/frontend address feature.
- Produces: current architecture documentation and final offline verification evidence.

- [ ] **Step 1: Update the architecture source of truth**

In `docs/ARCHITECTURE.md`:

- add `/addresses` CRUD/search to the mounted route table;
- add `address` to the PostgreSQL data table with user ownership and `last_used_at` semantics;
- document that `POST /orders` requires `address_id`, validates ownership before external calls, copies
  `shipmentAddress`/`shipmentAddressFull` into the MoySklad order, and marks default only after success;
- state that `shipmentAddressFull.comment` remains reserved for Privoz and the courier note uses `addInfo`;
- state that checkout and `/dashboard/addresses` share the same CRUD component.

- [ ] **Step 2: Run complete backend verification after the final backend edit**

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
.\.venv\Scripts\python.exe -m alembic heads
.\.venv\Scripts\python.exe -m alembic history
.\.venv\Scripts\python.exe -c "import main; print(main.app.title)"
git diff --check
```

Expected: Ruff and all pytest tests pass; one Alembic head is `b7e1d3a9f4c2`; import succeeds without an external
request; diff check is clean. Do not run `alembic upgrade`.

- [ ] **Step 3: Manually review migration safety**

Confirm in the diff that the migration only creates `address`, its named foreign key/unique constraint/indexes, and
drops only those objects in `downgrade`; it contains no `UPDATE`, `DELETE`, `TRUNCATE`, data copy, credential, or
database URL.

- [ ] **Step 4: Run complete frontend verification after the final frontend edit**

Run from `pix_frontend_v2`:

```powershell
npm.cmd run check
git diff --check
```

Expected: lint, API URL guard, unit tests, production build, and all Playwright tests pass. If the production build
fails only because the documented Google Fonts download is blocked, capture that exact output, run the remaining
local checks separately, and do not claim the full check passed.

- [ ] **Step 5: Inspect both worktrees for accidental or unrelated staging**

```powershell
git status --short
git diff --stat
```

Run once in each repository. Confirm no tracked `__pycache__`, user file, environment file, secret, or unrelated
change is staged by this feature.

- [ ] **Step 6: Commit the architecture documentation**

From `pix_backend`:

```powershell
git add -- docs/ARCHITECTURE.md
git commit -m "docs: document delivery address flow"
```

- [ ] **Step 7: Record final acceptance evidence**

In the handoff, report the exact backend/frontend verification commands and results, the new Alembic head, and that
the migration was reviewed but not applied. List backend and frontend commit IDs separately because the repositories
have independent histories.
