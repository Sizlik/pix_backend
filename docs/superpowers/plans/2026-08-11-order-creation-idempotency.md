# Order Creation Idempotency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make one checkout attempt create at most one set of MoySklad products and one customer order, return that same order for safe retries, and reject empty checkout requests.

**Architecture:** The browser persists a UUID per logical checkout attempt and sends it in `Idempotency-Key`. A Redis-backed coordinator serializes each user/key pair, stores the request fingerprint and completed response, while deterministic UUIDv5 `syncId` values make MoySklad product and customer-order creation retry-safe even after an interrupted backend request.

**Tech Stack:** Python 3.11, FastAPI, Pydantic 2, redis-py asyncio, requests, pytest/pytest-asyncio; Next.js 14, React 18, TypeScript 5, Axios, browser `localStorage`, Vitest.

## Global Constraints

- `POST /api_v1/orders` requires a UUID `Idempotency-Key` header.
- The key is scoped to the authenticated user and one logical attempt, not to cart contents.
- Same key plus same request returns the original order; same key plus another request returns HTTP 409 `idempotency_key_reused`.
- A still-running duplicate waits for at most 35 seconds, then returns HTTP 409 `order_creation_in_progress`.
- Redis coordination failure returns HTTP 503 before the first external call whenever ownership has not yet been established.
- Completed Redis records expire after exactly 86,400 seconds; processing leases expire after exactly 300 seconds.
- Checkout requires at least one item, a non-blank trimmed link, and `count > 0`.
- A later intentional identical order uses a new key and creates a new order.
- MoySklad receives deterministic per-user/per-attempt UUIDv5 `syncId` values for the customer order and every generated product.
- Address preference and Telegram notification remain best-effort and run only for the request that completes the external workflow.
- Do not add a database model or Alembic migration.
- Do not contact production MoySklad, Telegram, Redis, or other integrations from tests.
- Preserve the existing public `/api_v1` prefix and coordinate all request-contract changes with `../pix_frontend_v2`.

---

## File map

### Backend

- Modify `db/schemas/orders.py` — add checkout-only item and non-empty-list validation.
- Modify `db/schemas/moysklad.py` — allow a product creation payload to carry `syncId`.
- Modify `errors.py` — define stable domain exceptions for key reuse, in-progress attempts, and unavailable coordination.
- Create `manager/order_identity.py` — pure deterministic UUIDv5 derivation for order and product identities.
- Create `manager/order_idempotency.py` — Redis record, lock, replay, conflict, and availability behavior.
- Modify `manager/moysklad.py` — include supplied product and customer-order `syncId` values in external payloads.
- Modify `manager/order_creation.py` — fingerprint requests, execute external work through the coordinator, and suppress repeated secondary effects.
- Modify `dependecies/orders.py` — inject the shared Redis client and coordinator.
- Modify `routes/orders.py` — validate the header, pass it to the use case, and map domain failures to stable HTTP responses.
- Modify `tests/test_order_creation_api.py` — checkout validation, header, and HTTP error contract.
- Create `tests/test_order_identity.py` — deterministic and scoped UUID behavior.
- Modify `tests/test_moysklad_delivery_address.py` — customer-order `syncId` payload coverage.
- Create `tests/test_order_idempotency.py` — Redis coordinator concurrency, replay, conflict, and failure tests.
- Modify `tests/test_order_creation.py` — manager integration, replay, stable external IDs, and one-time secondary effects.
- Modify `docs/ARCHITECTURE.md` — document the required key and replay flow.
- Modify `scripts/check.ps1` — add the two new manager files to Ruff targets.

### Frontend

- Create `../pix_frontend_v2/src/features/orders/checkoutAttempt.ts` — canonical payload fingerprint and persisted attempt lifecycle.
- Create `../pix_frontend_v2/src/features/orders/checkoutAttempt.test.ts` — retry, payload-change, malformed-storage, and clear behavior.
- Modify `../pix_frontend_v2/src/routes/routes.tsx` — send the caller-supplied idempotency header.
- Create `../pix_frontend_v2/src/routes/routes.test.ts` — verify the checkout request body and headers.
- Modify `../pix_frontend_v2/src/app/dashboard/neworder/page.tsx` — acquire/reuse the key before submit and clear it only after success.

---

### Task 1: Enforce the checkout transport contract

**Files:**
- Modify: `db/schemas/orders.py:7-30`
- Modify: `errors.py`
- Modify: `routes/orders.py:1-75`
- Modify: `tests/test_order_creation_api.py`

**Interfaces:**
- Consumes: existing `CheckoutOrderCreate`, authenticated `User`, and `OrderCreationManager` dependency.
- Produces: `OrderCreationManager.create(request, user, idempotency_key: UUID)`, plus `IdempotencyKeyReused`, `OrderCreationInProgress`, and `OrderCreationIdempotencyUnavailable` exception types used by later tasks.

- [ ] **Step 1: Add failing checkout payload validation tests**

Append these cases to `tests/test_order_creation_api.py`:

```python
import pytest


@pytest.mark.parametrize(
    "order_items",
    [
        [],
        [{"link": "   ", "count": 1, "comment": ""}],
        [{"link": "https://shop.example/item", "count": 0, "comment": ""}],
        [{"link": "https://shop.example/item", "count": -1, "comment": ""}],
    ],
)
def test_create_order_rejects_empty_or_invalid_checkout_items(order_items):
    manager = StubOrderCreationManager()
    payload = valid_payload()
    payload["order_items"] = order_items
    with order_client(manager) as client:
        response = client.post(
            "/api_v1/orders",
            json=payload,
            headers={"Idempotency-Key": "00000000-0000-0000-0000-000000000020"},
        )
    assert response.status_code == 422
    assert manager.calls == []
```

- [ ] **Step 2: Run the payload tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_order_creation_api.py -q
```

Expected: the new cases reach the manager or return 200 because checkout-specific constraints do not exist.

- [ ] **Step 3: Add checkout-only Pydantic validation**

In `db/schemas/orders.py`, leave legacy `OrderItemCreate` and `OrderCreate` unchanged and add:

```python
class CheckoutOrderItemCreate(BaseModel):
    comment: str = ""
    count: int = Field(gt=0)
    link: str = Field(min_length=1)

    @field_validator("link")
    @classmethod
    def strip_and_require_link(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("link must not be blank")
        return value


class CheckoutOrderCreate(BaseModel):
    address_id: UUID
    order_items: list[CheckoutOrderItemCreate] = Field(min_length=1)
```

Remove the old inherited `CheckoutOrderCreate(OrderBase)` definition so there is exactly one checkout schema.

- [ ] **Step 4: Re-run the payload tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_order_creation_api.py -q
```

Expected: all current API tests pass, including the four new 422 cases.

- [ ] **Step 5: Add failing header and error-contract tests**

Change the API stub so its new parameter is observable:

```python
class StubOrderCreationManager:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    async def create(self, request, user, idempotency_key=None):
        self.calls.append((request, user, idempotency_key))
        if self.error:
            raise self.error
        return {"id": "moysklad-order"}
```

Add these tests, using `import errors` so the first run reports missing attributes without a collection-time import failure:

```python
import errors

IDEMPOTENCY_KEY = "00000000-0000-0000-0000-000000000020"


def test_create_order_requires_uuid_idempotency_key():
    manager = StubOrderCreationManager()
    with order_client(manager) as client:
        missing = client.post("/api_v1/orders", json=valid_payload())
        malformed = client.post(
            "/api_v1/orders",
            json=valid_payload(),
            headers={"Idempotency-Key": "not-a-uuid"},
        )
    assert missing.status_code == 422
    assert malformed.status_code == 422
    assert manager.calls == []


def test_create_order_passes_valid_idempotency_key_to_use_case():
    manager = StubOrderCreationManager()
    with order_client(manager) as client:
        response = client.post(
            "/api_v1/orders",
            json=valid_payload(),
            headers={"Idempotency-Key": IDEMPOTENCY_KEY},
        )
    assert response.status_code == 200
    assert str(manager.calls[0][2]) == IDEMPOTENCY_KEY


def test_order_idempotency_errors_are_defined():
    assert issubclass(errors.IdempotencyKeyReused, RuntimeError)
    assert issubclass(errors.OrderCreationInProgress, RuntimeError)
    assert issubclass(errors.OrderCreationIdempotencyUnavailable, RuntimeError)


@pytest.mark.parametrize(
    ("error_name", "status", "code"),
    [
        ("IdempotencyKeyReused", 409, "idempotency_key_reused"),
        ("OrderCreationInProgress", 409, "order_creation_in_progress"),
        (
            "OrderCreationIdempotencyUnavailable",
            503,
            "order_idempotency_unavailable",
        ),
    ],
)
def test_create_order_maps_idempotency_failures(error_name, status, code):
    manager = StubOrderCreationManager(getattr(errors, error_name)())
    with order_client(manager) as client:
        response = client.post(
            "/api_v1/orders",
            json=valid_payload(),
            headers={"Idempotency-Key": IDEMPOTENCY_KEY},
        )
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
```

Update every pre-existing valid `client.post("/api_v1/orders", ...)` call in this test file to include `headers={"Idempotency-Key": IDEMPOTENCY_KEY}` except the explicit missing-header assertion.

- [ ] **Step 6: Run the header tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_order_creation_api.py -q
```

Expected: missing-header and mapping assertions fail because the route has no header parameter or domain mappings, and `test_order_idempotency_errors_are_defined` fails on the absent exception attributes.

- [ ] **Step 7: Add the domain errors and route mapping**

Add to `errors.py`:

```python
class IdempotencyKeyReused(RuntimeError):
    pass


class OrderCreationInProgress(RuntimeError):
    pass


class OrderCreationIdempotencyUnavailable(RuntimeError):
    pass
```

In `routes/orders.py`, import `Header`, the three exceptions, and add:

```python
def order_creation_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, IdempotencyKeyReused):
        return HTTPException(
            409,
            detail={
                "code": "idempotency_key_reused",
                "message": "Idempotency key was already used for another order",
            },
        )
    if isinstance(exc, OrderCreationInProgress):
        return HTTPException(
            409,
            detail={
                "code": "order_creation_in_progress",
                "message": "Order creation is still in progress",
            },
        )
    return HTTPException(
        503,
        detail={
            "code": "order_idempotency_unavailable",
            "message": "Order creation is temporarily unavailable",
        },
    )
```

Change the route signature and delegation to:

```python
@router.post("")
async def create_order(
    order: CheckoutOrderCreate,
    idempotency_key: Annotated[uuid.UUID, Header(alias="Idempotency-Key")],
    user: User = Depends(current_user_dependency),
    manager: OrderCreationManager = Depends(
        dependency_orders.get_order_creation_manager
    ),
):
    try:
        return await manager.create(order, user, idempotency_key)
    except (
        IdempotencyKeyReused,
        OrderCreationInProgress,
        OrderCreationIdempotencyUnavailable,
    ) as exc:
        raise order_creation_http_error(exc) from None
```

- [ ] **Step 8: Run API tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_order_creation_api.py -q
```

Expected: all tests pass.

- [ ] **Step 9: Commit the backend transport contract**

```powershell
git add db/schemas/orders.py errors.py routes/orders.py tests/test_order_creation_api.py
git commit -m "fix: validate checkout order attempts"
```

---

### Task 2: Give every external entity a deterministic retry identity

**Files:**
- Create: `manager/order_identity.py`
- Modify: `db/schemas/moysklad.py:16-19`
- Modify: `manager/moysklad.py:196-227,300-318`
- Create: `tests/test_order_identity.py`
- Modify: `tests/test_moysklad_delivery_address.py`

**Interfaces:**
- Consumes: authenticated user UUID, client idempotency UUID, checkout item count, `ProductManager`, and `CustomerOrderManager`.
- Produces: `build_order_create_identity(user_id: UUID, idempotency_key: UUID, item_count: int) -> OrderCreateIdentity`, `ProductManager.create_products(..., sync_ids: Sequence[UUID] | None = None)`, and `CustomerOrderManager.create_order_by_request(..., sync_id: UUID)`.

- [ ] **Step 1: Write failing UUID identity tests**

Create `tests/test_order_identity.py`:

```python
from uuid import UUID

from manager.order_identity import build_order_create_identity

USER_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_USER_ID = UUID("00000000-0000-0000-0000-000000000002")
KEY = UUID("00000000-0000-0000-0000-000000000020")
OTHER_KEY = UUID("00000000-0000-0000-0000-000000000021")


def test_order_create_identity_is_stable_and_distinct_per_entity():
    first = build_order_create_identity(USER_ID, KEY, 2)
    retry = build_order_create_identity(USER_ID, KEY, 2)
    assert first == retry
    assert len(first.product_sync_ids) == 2
    assert len({first.order_sync_id, *first.product_sync_ids}) == 3


def test_order_create_identity_is_scoped_by_user_and_attempt():
    original = build_order_create_identity(USER_ID, KEY, 1)
    other_user = build_order_create_identity(OTHER_USER_ID, KEY, 1)
    other_attempt = build_order_create_identity(USER_ID, OTHER_KEY, 1)
    assert original.order_sync_id != other_user.order_sync_id
    assert original.order_sync_id != other_attempt.order_sync_id
    assert original.product_sync_ids != other_user.product_sync_ids
    assert original.product_sync_ids != other_attempt.product_sync_ids
```

- [ ] **Step 2: Run identity tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_order_identity.py -q
```

Expected: collection fails because `manager.order_identity` does not exist.

- [ ] **Step 3: Implement the pure UUIDv5 identity builder**

Create `manager/order_identity.py`:

```python
from dataclasses import dataclass
from uuid import UUID, uuid5

ORDER_CREATE_NAMESPACE = UUID("fa8f8d8b-d6ec-4ca2-8c08-b5ba76f1c676")


@dataclass(frozen=True)
class OrderCreateIdentity:
    order_sync_id: UUID
    product_sync_ids: tuple[UUID, ...]


def build_order_create_identity(
    user_id: UUID,
    idempotency_key: UUID,
    item_count: int,
) -> OrderCreateIdentity:
    attempt_namespace = uuid5(
        ORDER_CREATE_NAMESPACE,
        f"{user_id}:{idempotency_key}",
    )
    return OrderCreateIdentity(
        order_sync_id=uuid5(attempt_namespace, "customer-order"),
        product_sync_ids=tuple(
            uuid5(attempt_namespace, f"product:{index}")
            for index in range(item_count)
        ),
    )
```

- [ ] **Step 4: Re-run identity tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_order_identity.py -q
```

Expected: 2 tests pass.

- [ ] **Step 5: Add failing MoySklad payload assertions**

Extend the recording product-repository coverage in a new section of `tests/test_order_identity.py`:

```python
from types import SimpleNamespace

import pytest

from db.schemas.orders import CheckoutOrderCreate
from manager.moysklad import ProductManager


class RecordingProductRepository:
    def __init__(self):
        self.rows = None

    async def create_multiply(self, rows):
        self.rows = rows
        return [{"meta": {"href": f"product-{index}"}} for index, _ in enumerate(rows)]


@pytest.mark.asyncio
async def test_checkout_products_send_supplied_sync_ids():
    request = CheckoutOrderCreate(
        address_id=UUID("00000000-0000-0000-0000-000000000010"),
        order_items=[
            {"link": "first", "count": 1, "comment": ""},
            {"link": "second", "count": 2, "comment": "note"},
        ],
    )
    identity = build_order_create_identity(USER_ID, KEY, 2)
    repository = RecordingProductRepository()
    await ProductManager(repository).create_products(
        request,
        SimpleNamespace(),
        sync_ids=identity.product_sync_ids,
    )
    assert [row["syncId"] for row in repository.rows] == [
        str(value) for value in identity.product_sync_ids
    ]
```

In `tests/test_moysklad_delivery_address.py`, pass a fixed `sync_id` to the existing `create_order_by_request` call and assert the repository received it:

```python
ORDER_SYNC_ID = UUID("00000000-0000-0000-0000-000000000030")

await manager.create_order_by_request(
    positions,
    user,
    snapshot,
    sync_id=ORDER_SYNC_ID,
)
assert repository.created["syncId"] == str(ORDER_SYNC_ID)
```

Use the existing `RecordingCustomerOrderRepository.created` attribute and assert `repository.created["syncId"]`.

- [ ] **Step 6: Run MoySklad payload tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_order_identity.py tests/test_moysklad_delivery_address.py -q
```

Expected: `ProductManager.create_products` rejects `sync_ids`, and `CustomerOrderManager.create_order_by_request` rejects `sync_id`.

- [ ] **Step 7: Add `syncId` to product and customer-order payloads**

Change `ProductCreate` in `db/schemas/moysklad.py`:

```python
class ProductCreate(BaseModel):
    name: str
    description: str
    productFolder: dict | None = None
    syncId: str | None = None
```

Change only the checkout-capable product method in `manager/moysklad.py`:

```python
async def create_products(
    self,
    order: OrderCreate | CheckoutOrderCreate,
    user: User,
    sync_ids: Sequence[UUID] | None = None,
):
    if sync_ids is not None and len(sync_ids) != len(order.order_items):
        raise ValueError("one sync id is required per product")
    products = []
    for index, item in enumerate(order.order_items):
        product = moysklad.ProductCreate(
            name=f"{item.link}",
            description=f"{item.comment}",
            syncId=str(sync_ids[index]) if sync_ids is not None else None,
        ).model_dump(exclude_none=True)
        products.append(product)
    return await self.__repo.create_multiply(products)
```

Add `from collections.abc import Sequence`, `from uuid import UUID`, and import `CheckoutOrderCreate` beside `OrderCreate`. Preserve the optional argument because `OrderChangesManager` also uses this method for non-checkout additions.

Change the customer-order method signature and payload:

```python
async def create_order_by_request(
    self,
    order_items,
    user: User,
    delivery_address: DeliveryAddressSnapshot,
    *,
    sync_id: UUID,
):
    organization = await self.__repo.get_default_company()
    positions = [
        {
            "quantity": item["count"],
            "assortment": {"meta": item["moysklad_product_meta"]},
        }
        for item in order_items
    ]
    customer_order = {
        "syncId": str(sync_id),
        "organization": {"meta": organization.get("meta")},
        "agent": {"meta": user.moysklad_counterparty_meta},
        "positions": positions,
        **moysklad_delivery_payload(delivery_address),
    }
    return await self.__repo.create(**customer_order)
```

Add `from uuid import UUID` to `manager/moysklad.py`.

- [ ] **Step 8: Run focused and existing MoySklad tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_order_identity.py tests/test_moysklad_delivery_address.py tests/test_integrations.py -q
```

Expected: all selected tests pass.

- [ ] **Step 9: Commit external retry identities**

```powershell
git add manager/order_identity.py db/schemas/moysklad.py manager/moysklad.py tests/test_order_identity.py tests/test_moysklad_delivery_address.py
git commit -m "feat: add retry identities to MoySklad orders"
```

---

### Task 3: Implement the Redis idempotency coordinator

**Files:**
- Create: `manager/order_idempotency.py`
- Create: `tests/test_order_idempotency.py`
- Modify: `scripts/check.ps1`

**Interfaces:**
- Consumes: an asyncio redis-py client with `get`, `set`, and `lock`.
- Produces: `RedisOrderCreationIdempotency.run(user_id: UUID, key: UUID, fingerprint: str, operation: Callable[[], Awaitable[dict]]) -> tuple[dict, bool]`; the boolean is true only when this call executed `operation`.

- [ ] **Step 1: Write coordinator fake infrastructure and failing replay test**

Create `tests/test_order_idempotency.py` with a shared-lock fake and the first behavior test:

```python
import asyncio
import json
from uuid import UUID

import pytest

from manager.order_idempotency import RedisOrderCreationIdempotency

USER_ID = UUID("00000000-0000-0000-0000-000000000001")
KEY = UUID("00000000-0000-0000-0000-000000000020")


class FakeLock:
    def __init__(self, lock, options, acquire_error=None, force_unavailable=False):
        self._lock = lock
        self.options = options
        self.acquire_error = acquire_error
        self.force_unavailable = force_unavailable

    async def acquire(self):
        if self.acquire_error:
            raise self.acquire_error
        if self.force_unavailable:
            return False
        timeout = self.options["blocking_timeout"]
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=timeout)
        except TimeoutError:
            return False
        return True

    async def release(self):
        if self._lock.locked():
            self._lock.release()


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.locks = {}
        self.lock_calls = []
        self.get_error = None
        self.set_error = None
        self.set_calls = 0
        self.fail_set_call = None
        self.force_lock_unavailable = False

    async def get(self, key):
        if self.get_error:
            raise self.get_error
        return self.values.get(key)

    async def set(self, key, value, ex):
        self.set_calls += 1
        if self.set_error or self.fail_set_call == self.set_calls:
            raise self.set_error or RuntimeError("redis unavailable")
        self.values[key] = value
        self.values[f"{key}:ttl"] = ex
        return True

    def lock(self, name, **options):
        self.lock_calls.append((name, options))
        shared = self.locks.setdefault(name, asyncio.Lock())
        return FakeLock(
            shared,
            options,
            force_unavailable=self.force_lock_unavailable,
        )


@pytest.mark.asyncio
async def test_completed_attempt_replays_result_without_running_operation_twice():
    redis = FakeRedis()
    coordinator = RedisOrderCreationIdempotency(redis)
    calls = 0

    async def operation():
        nonlocal calls
        calls += 1
        return {"id": "order"}

    first = await coordinator.run(USER_ID, KEY, "fingerprint", operation)
    retry = await coordinator.run(USER_ID, KEY, "fingerprint", operation)

    assert first == ({"id": "order"}, True)
    assert retry == ({"id": "order"}, False)
    assert calls == 1
```

- [ ] **Step 2: Run replay test and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_order_idempotency.py -q
```

Expected: collection fails because `manager.order_idempotency` does not exist.

- [ ] **Step 3: Implement the minimal record/replay coordinator**

Create `manager/order_idempotency.py` with these public constants and helpers:

```python
import json
from collections.abc import Awaitable, Callable
from uuid import UUID

from errors import (
    IdempotencyKeyReused,
    OrderCreationIdempotencyUnavailable,
    OrderCreationInProgress,
)

RESULT_TTL_SECONDS = 86_400
LOCK_TIMEOUT_SECONDS = 300
LOCK_BLOCKING_TIMEOUT_SECONDS = 35


class RedisOrderCreationIdempotency:
    def __init__(
        self,
        redis_client,
        *,
        result_ttl_seconds=RESULT_TTL_SECONDS,
        lock_timeout_seconds=LOCK_TIMEOUT_SECONDS,
        blocking_timeout_seconds=LOCK_BLOCKING_TIMEOUT_SECONDS,
    ):
        self._redis = redis_client
        self._result_ttl = result_ttl_seconds
        self._lock_timeout = lock_timeout_seconds
        self._blocking_timeout = blocking_timeout_seconds

    @staticmethod
    def _base_key(user_id: UUID, key: UUID) -> str:
        return f"orders:create:idempotency:{user_id}:{key}"

    async def _read(self, record_key: str):
        try:
            raw = await self._redis.get(record_key)
            return json.loads(raw) if raw is not None else None
        except Exception as error:
            raise OrderCreationIdempotencyUnavailable from error

    async def _write(self, record_key: str, record: dict) -> None:
        try:
            await self._redis.set(
                record_key,
                json.dumps(record, separators=(",", ":")),
                ex=self._result_ttl,
            )
        except Exception as error:
            raise OrderCreationIdempotencyUnavailable from error

    @staticmethod
    def _resolve(record, fingerprint):
        if record is None:
            return None
        if record["fingerprint"] != fingerprint:
            raise IdempotencyKeyReused
        if record["state"] == "completed":
            return record["result"]
        return None

    async def run(
        self,
        user_id: UUID,
        key: UUID,
        fingerprint: str,
        operation: Callable[[], Awaitable[dict]],
    ) -> tuple[dict, bool]:
        record_key = self._base_key(user_id, key)
        cached = self._resolve(await self._read(record_key), fingerprint)
        if cached is not None:
            return cached, False

        lock = self._redis.lock(
            f"{record_key}:lock",
            timeout=self._lock_timeout,
            blocking_timeout=self._blocking_timeout,
        )
        try:
            acquired = await lock.acquire()
        except Exception as error:
            raise OrderCreationIdempotencyUnavailable from error
        if not acquired:
            cached = self._resolve(await self._read(record_key), fingerprint)
            if cached is not None:
                return cached, False
            raise OrderCreationInProgress

        try:
            record = await self._read(record_key)
            cached = self._resolve(record, fingerprint)
            if cached is not None:
                return cached, False
            if record is None:
                await self._write(
                    record_key,
                    {"state": "processing", "fingerprint": fingerprint},
                )
            result = await operation()
            await self._write(
                record_key,
                {
                    "state": "completed",
                    "fingerprint": fingerprint,
                    "result": result,
                },
            )
            return result, True
        finally:
            try:
                await lock.release()
            except Exception:
                pass
```

- [ ] **Step 4: Run replay test and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_order_idempotency.py -q
```

Expected: the replay test passes.

- [ ] **Step 5: Add failing concurrency, conflict, lease, and Redis-failure tests**

Append:

```python
from errors import (
    IdempotencyKeyReused,
    OrderCreationIdempotencyUnavailable,
    OrderCreationInProgress,
)


@pytest.mark.asyncio
async def test_concurrent_attempts_run_operation_once_and_both_get_result():
    redis = FakeRedis()
    coordinator = RedisOrderCreationIdempotency(redis, blocking_timeout_seconds=1)
    started = asyncio.Event()
    finish = asyncio.Event()
    calls = 0

    async def operation():
        nonlocal calls
        calls += 1
        started.set()
        await finish.wait()
        return {"id": "order"}

    first = asyncio.create_task(
        coordinator.run(USER_ID, KEY, "fingerprint", operation)
    )
    await started.wait()
    second = asyncio.create_task(
        coordinator.run(USER_ID, KEY, "fingerprint", operation)
    )
    finish.set()
    assert await asyncio.gather(first, second) == [
        ({"id": "order"}, True),
        ({"id": "order"}, False),
    ]
    assert calls == 1


@pytest.mark.asyncio
async def test_reused_key_with_another_fingerprint_conflicts():
    redis = FakeRedis()
    coordinator = RedisOrderCreationIdempotency(redis)
    await coordinator.run(
        USER_ID,
        KEY,
        "first",
        lambda: _return_order(),
    )
    with pytest.raises(IdempotencyKeyReused):
        await coordinator.run(
            USER_ID,
            KEY,
            "second",
            lambda: _return_order(),
        )


async def _return_order():
    return {"id": "order"}


@pytest.mark.asyncio
async def test_user_and_key_scope_allow_intentional_separate_orders():
    redis = FakeRedis()
    coordinator = RedisOrderCreationIdempotency(redis)
    calls = 0

    async def operation():
        nonlocal calls
        calls += 1
        return {"id": f"order-{calls}"}

    other_user = UUID("00000000-0000-0000-0000-000000000002")
    other_key = UUID("00000000-0000-0000-0000-000000000021")
    assert await coordinator.run(
        USER_ID, KEY, "same-payload", operation
    ) == ({"id": "order-1"}, True)
    assert await coordinator.run(
        USER_ID, other_key, "same-payload", operation
    ) == ({"id": "order-2"}, True)
    assert await coordinator.run(
        other_user, KEY, "same-payload", operation
    ) == ({"id": "order-3"}, True)


@pytest.mark.asyncio
async def test_failed_operation_keeps_fingerprint_and_allows_same_retry():
    redis = FakeRedis()
    coordinator = RedisOrderCreationIdempotency(redis)

    async def fail():
        raise RuntimeError("MoySklad unavailable")

    with pytest.raises(RuntimeError):
        await coordinator.run(USER_ID, KEY, "fingerprint", fail)
    assert await coordinator.run(
        USER_ID, KEY, "fingerprint", _return_order
    ) == ({"id": "order"}, True)
    with pytest.raises(IdempotencyKeyReused):
        await coordinator.run(USER_ID, KEY, "changed", _return_order)


@pytest.mark.asyncio
async def test_lock_timeout_reports_in_progress_with_exact_options():
    redis = FakeRedis()
    redis.force_lock_unavailable = True
    coordinator = RedisOrderCreationIdempotency(redis)
    with pytest.raises(OrderCreationInProgress):
        await coordinator.run(USER_ID, KEY, "fingerprint", _return_order)
    _, options = redis.lock_calls[-1]
    assert options == {"timeout": 300, "blocking_timeout": 35}


@pytest.mark.asyncio
async def test_redis_read_failure_never_runs_external_operation():
    redis = FakeRedis()
    redis.get_error = RuntimeError("redis unavailable")
    coordinator = RedisOrderCreationIdempotency(redis)
    called = False

    async def operation():
        nonlocal called
        called = True
        return {"id": "order"}

    with pytest.raises(OrderCreationIdempotencyUnavailable):
        await coordinator.run(USER_ID, KEY, "fingerprint", operation)
    assert called is False


@pytest.mark.asyncio
async def test_initial_record_write_failure_never_runs_external_operation():
    redis = FakeRedis()
    redis.set_error = RuntimeError("redis unavailable")
    coordinator = RedisOrderCreationIdempotency(redis)
    called = False

    async def operation():
        nonlocal called
        called = True
        return {"id": "order"}

    with pytest.raises(OrderCreationIdempotencyUnavailable):
        await coordinator.run(USER_ID, KEY, "fingerprint", operation)
    assert called is False


@pytest.mark.asyncio
async def test_completion_write_failure_leaves_attempt_retryable():
    redis = FakeRedis()
    redis.fail_set_call = 2
    coordinator = RedisOrderCreationIdempotency(redis)
    calls = 0

    async def operation():
        nonlocal calls
        calls += 1
        return {"id": "order"}

    with pytest.raises(OrderCreationIdempotencyUnavailable):
        await coordinator.run(USER_ID, KEY, "fingerprint", operation)
    record_key = coordinator._base_key(USER_ID, KEY)
    assert json.loads(redis.values[record_key])["state"] == "processing"

    redis.fail_set_call = None
    assert await coordinator.run(
        USER_ID, KEY, "fingerprint", operation
    ) == ({"id": "order"}, True)
    assert calls == 2


@pytest.mark.asyncio
async def test_completed_record_uses_24_hour_ttl():
    redis = FakeRedis()
    coordinator = RedisOrderCreationIdempotency(redis)
    await coordinator.run(USER_ID, KEY, "fingerprint", _return_order)
    record_key = coordinator._base_key(USER_ID, KEY)
    assert redis.values[f"{record_key}:ttl"] == 86_400
    assert json.loads(redis.values[record_key])["state"] == "completed"
```

The completion-write test deliberately executes the callback twice. Task 2 and Task 4 prove both executions carry the same MoySklad `syncId` values, so the resumed request receives the already-created external entities.

- [ ] **Step 6: Run coordinator tests and make them GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_order_idempotency.py -q
```

Expected: all replay, concurrency, conflict, failure, option, and TTL tests pass. If the completion-write test exposes the expected post-external 503 path, assert the processing record remains and a second call with the same fingerprint can resume.

- [ ] **Step 7: Add new manager files to Ruff coverage**

In `scripts/check.ps1`, add these entries to `$ruffTargets` beside `manager/order_creation.py`:

```powershell
"manager/order_identity.py",
"manager/order_idempotency.py",
```

- [ ] **Step 8: Run focused Ruff and coordinator tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m ruff check manager/order_idempotency.py manager/order_identity.py tests/test_order_idempotency.py tests/test_order_identity.py
.\.venv\Scripts\python.exe -m pytest tests/test_order_idempotency.py tests/test_order_identity.py -q
```

Expected: both commands exit 0.

- [ ] **Step 9: Commit the coordinator**

```powershell
git add manager/order_idempotency.py tests/test_order_idempotency.py scripts/check.ps1
git commit -m "feat: coordinate idempotent order creation"
```

---

### Task 4: Run checkout creation through idempotency

**Files:**
- Modify: `manager/order_creation.py`
- Modify: `dependecies/orders.py`
- Modify: `tests/test_order_creation.py`
- Modify: `tests/test_order_creation_api.py`

**Interfaces:**
- Consumes: `RedisOrderCreationIdempotency.run`, `build_order_create_identity`, checkout schema, existing address/product/customer-order/notifier collaborators.
- Produces: the finalized `OrderCreationManager.create(request: CheckoutOrderCreate, user: User, idempotency_key: UUID) -> dict` behavior used by the route.

- [ ] **Step 1: Update test doubles for the new collaborator signatures**

In `tests/test_order_creation.py`, change the product and customer-order stubs to record retry identities:

```python
class StubProducts:
    def __init__(self, events, error=None):
        self.events = events
        self.error = error
        self.sync_ids = None

    async def create_products(self, request, user, sync_ids=None):
        self.events.append("products:create")
        self.sync_ids = sync_ids
        if self.error:
            raise self.error
        return [
            {"meta": {"href": "product-meta"}}
            for _ in request.order_items
        ]


class StubCustomerOrders:
    def __init__(self, events, error=None):
        self.events = events
        self.error = error
        self.arguments = None

    async def create_order_by_request(
        self,
        positions,
        user,
        address,
        *,
        sync_id,
    ):
        self.events.append("order:create")
        self.arguments = (positions, user, address, sync_id)
        if self.error:
            raise self.error
        return {
            "id": "moysklad-order",
            "meta": {"uuidHref": "https://moysklad/order"},
        }
```

Add an idempotency test double:

```python
class StubIdempotency:
    def __init__(self, cached=None):
        self.cached = cached
        self.calls = []

    async def run(self, user_id, key, fingerprint, operation):
        self.calls.append((user_id, key, fingerprint))
        if self.cached is not None:
            return self.cached, False
        return await operation(), True
```

Change the manager construction in every existing test to pass `StubIdempotency()` immediately before the notifier argument, and call `.create(make_request(), make_user(), IDEMPOTENCY_KEY)` with:

```python
IDEMPOTENCY_KEY = UUID("00000000-0000-0000-0000-000000000020")
```

- [ ] **Step 2: Add failing manager replay and identity tests**

Append:

```python
@pytest.mark.asyncio
async def test_completed_retry_returns_cached_order_without_any_side_effect():
    events = []
    cached = {
        "id": "moysklad-order",
        "meta": {"uuidHref": "https://moysklad/order"},
    }
    manager = OrderCreationManager(
        StubAddresses(events),
        StubProducts(events),
        StubCustomerOrders(events),
        StubIdempotency(cached=cached),
        StubNotifier(events),
    )
    assert await manager.create(make_request(), make_user(), IDEMPOTENCY_KEY) == cached
    assert events == []


@pytest.mark.asyncio
async def test_checkout_passes_stable_sync_ids_to_both_moysklad_stages():
    events = []
    products = StubProducts(events)
    orders = StubCustomerOrders(events)
    idempotency = StubIdempotency()
    manager = OrderCreationManager(
        StubAddresses(events),
        products,
        orders,
        idempotency,
        StubNotifier(events),
    )
    await manager.create(make_request(), make_user(), IDEMPOTENCY_KEY)
    assert len(products.sync_ids) == 1
    assert orders.arguments[3] not in products.sync_ids
    assert idempotency.calls[0][0] == make_user().id
    assert idempotency.calls[0][1] == IDEMPOTENCY_KEY
    assert len(idempotency.calls[0][2]) == 64


def test_checkout_fingerprint_changes_with_address_or_item_data():
    original = make_request()
    changed = make_request().model_copy(
        update={
            "order_items": [
                make_request().order_items[0].model_copy(update={"count": 3})
            ]
        }
    )
    assert checkout_fingerprint(original) == checkout_fingerprint(make_request())
    assert checkout_fingerprint(original) != checkout_fingerprint(changed)
```

Import `checkout_fingerprint` from `manager.order_creation`.

- [ ] **Step 3: Run manager tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_order_creation.py -q
```

Expected: constructor/call signatures and the missing fingerprint function fail.

- [ ] **Step 4: Implement fingerprinting and coordinated external work**

In `manager/order_creation.py`, add:

```python
import hashlib
import json
from uuid import UUID

from manager.order_identity import build_order_create_identity


def checkout_fingerprint(request: CheckoutOrderCreate) -> str:
    canonical = {
        "address_id": str(request.address_id),
        "order_items": [
            {
                "link": item.link,
                "count": item.count,
                "comment": item.comment,
            }
            for item in request.order_items
        ],
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
```

Add `idempotency` between `customer_orders` and `notifier` in the constructor. Replace `create` with:

```python
async def create(
    self,
    request: CheckoutOrderCreate,
    user: User,
    idempotency_key: UUID,
) -> dict:
    identity = build_order_create_identity(
        user.id,
        idempotency_key,
        len(request.order_items),
    )

    async def create_external_order():
        address = await self._addresses.get_for_order(
            user.id,
            request.address_id,
        )
        products = await self._products.create_products(
            request,
            user,
            sync_ids=identity.product_sync_ids,
        )
        positions = [
            {
                "count": item.count,
                "moysklad_product_meta": product["meta"],
            }
            for product, item in zip(products, request.order_items)
        ]
        return await self._customer_orders.create_order_by_request(
            positions,
            user,
            address,
            sync_id=identity.order_sync_id,
        )

    order, executed = await self._idempotency.run(
        user.id,
        idempotency_key,
        checkout_fingerprint(request),
        create_external_order,
    )
    if not executed:
        return order

    try:
        await self._addresses.mark_used(user.id, request.address_id)
    except Exception:
        self._logger.exception("failed to mark delivery address as used")
    try:
        await self._notifier.send_group_message(
            build_new_order_message(order, user)
        )
    except Exception:
        self._logger.exception("failed to send new order notification")
    return order
```

Store the constructor argument as `self._idempotency`.

- [ ] **Step 5: Run manager tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_order_creation.py tests/test_order_idempotency.py tests/test_order_identity.py -q
```

Expected: all selected tests pass, including original address/error sequencing.

- [ ] **Step 6: Inject the real Redis coordinator**

In `dependecies/orders.py`, import the shared client and coordinator:

```python
from db.redis import redis
from manager.order_idempotency import RedisOrderCreationIdempotency
```

Construct the manager as:

```python
async def get_order_creation_manager():
    yield OrderCreationManager(
        AddressManager(AddressRepository()),
        ProductManager(ProductRepository()),
        CustomerOrderManager(CustomerOrderRepository()),
        RedisOrderCreationIdempotency(redis),
        telegram_sender,
    )
```

- [ ] **Step 7: Run the backend order suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_order_creation.py tests/test_order_creation_api.py tests/test_order_idempotency.py tests/test_order_identity.py tests/test_moysklad_delivery_address.py tests/test_order_changes.py tests/test_order_changes_api.py -q
```

Expected: all selected tests pass with no external services contacted.

- [ ] **Step 8: Commit the coordinated use case**

```powershell
git add manager/order_creation.py dependecies/orders.py tests/test_order_creation.py tests/test_order_creation_api.py
git commit -m "fix: make checkout creation idempotent"
```

---

### Task 5: Persist one browser key per logical checkout attempt

**Files:**
- Create: `../pix_frontend_v2/src/features/orders/checkoutAttempt.ts`
- Create: `../pix_frontend_v2/src/features/orders/checkoutAttempt.test.ts`

**Interfaces:**
- Consumes: selected address ID, ordered checkout items, a `Storage`-compatible object, and a UUID factory.
- Produces: `getOrCreateCheckoutAttempt`, `clearCheckoutAttempt`, `CheckoutOrderItem`, and `CheckoutAttemptPayload` for the page and API wrapper.

- [ ] **Step 1: Write failing browser-attempt helper tests**

Create `../pix_frontend_v2/src/features/orders/checkoutAttempt.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import {
  CHECKOUT_ATTEMPT_STORAGE_KEY,
  clearCheckoutAttempt,
  getOrCreateCheckoutAttempt,
  type CheckoutAttemptPayload,
} from "./checkoutAttempt";

class MemoryStorage {
  values = new Map<string, string>();
  getItem(key: string) {
    return this.values.get(key) ?? null;
  }
  setItem(key: string, value: string) {
    this.values.set(key, value);
  }
  removeItem(key: string) {
    this.values.delete(key);
  }
}

const payload = (count = 1, addressId = "address-1"): CheckoutAttemptPayload => ({
  addressId,
  items: [{ link: "https://shop.example/item", count, comment: "" }],
});

describe("checkout attempt persistence", () => {
  it("reuses one key for retries of an unchanged payload", () => {
    const storage = new MemoryStorage();
    let generated = 0;
    const createKey = () => `key-${++generated}`;
    expect(getOrCreateCheckoutAttempt(storage, payload(), createKey).key).toBe("key-1");
    expect(getOrCreateCheckoutAttempt(storage, payload(), createKey).key).toBe("key-1");
    expect(generated).toBe(1);
  });

  it("creates a new key when address or item data changes", () => {
    const storage = new MemoryStorage();
    let generated = 0;
    const createKey = () => `key-${++generated}`;
    getOrCreateCheckoutAttempt(storage, payload(), createKey);
    expect(getOrCreateCheckoutAttempt(storage, payload(2), createKey).key).toBe("key-2");
    expect(
      getOrCreateCheckoutAttempt(storage, payload(2, "address-2"), createKey).key,
    ).toBe("key-3");
  });

  it("replaces malformed storage and clears a completed attempt", () => {
    const storage = new MemoryStorage();
    storage.setItem(CHECKOUT_ATTEMPT_STORAGE_KEY, "not-json");
    expect(
      getOrCreateCheckoutAttempt(storage, payload(), () => "replacement").key,
    ).toBe("replacement");
    clearCheckoutAttempt(storage);
    expect(storage.getItem(CHECKOUT_ATTEMPT_STORAGE_KEY)).toBeNull();
  });
});
```

- [ ] **Step 2: Run the helper tests and verify RED**

Run from `../pix_frontend_v2`:

```powershell
npm.cmd run test:unit -- src/features/orders/checkoutAttempt.test.ts
```

Expected: the module cannot be resolved.

- [ ] **Step 3: Implement the pure storage helper**

Create `../pix_frontend_v2/src/features/orders/checkoutAttempt.ts`:

```typescript
export const CHECKOUT_ATTEMPT_STORAGE_KEY = "pix:checkout-attempt";

export type CheckoutOrderItem = {
  link: string;
  count: number;
  comment: string;
};

export type CheckoutAttemptPayload = {
  addressId: string;
  items: CheckoutOrderItem[];
};

type AttemptRecord = {
  key: string;
  fingerprint: string;
};

type AttemptStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

function fingerprint(payload: CheckoutAttemptPayload): string {
  return JSON.stringify({
    address_id: payload.addressId,
    order_items: payload.items.map((item) => ({
      link: item.link.trim(),
      count: item.count,
      comment: item.comment,
    })),
  });
}

function readAttempt(storage: AttemptStorage): AttemptRecord | null {
  const raw = storage.getItem(CHECKOUT_ATTEMPT_STORAGE_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<AttemptRecord>;
    return typeof parsed.key === "string" && typeof parsed.fingerprint === "string"
      ? { key: parsed.key, fingerprint: parsed.fingerprint }
      : null;
  } catch {
    return null;
  }
}

export function getOrCreateCheckoutAttempt(
  storage: AttemptStorage,
  payload: CheckoutAttemptPayload,
  createKey: () => string = () => crypto.randomUUID(),
): AttemptRecord {
  const nextFingerprint = fingerprint(payload);
  const current = readAttempt(storage);
  if (current?.fingerprint === nextFingerprint) return current;
  const next = { key: createKey(), fingerprint: nextFingerprint };
  storage.setItem(CHECKOUT_ATTEMPT_STORAGE_KEY, JSON.stringify(next));
  return next;
}

export function clearCheckoutAttempt(storage: AttemptStorage): void {
  storage.removeItem(CHECKOUT_ATTEMPT_STORAGE_KEY);
}
```

- [ ] **Step 4: Run helper tests and verify GREEN**

Run:

```powershell
npm.cmd run test:unit -- src/features/orders/checkoutAttempt.test.ts
```

Expected: 3 tests pass.

- [ ] **Step 5: Run frontend lint on the helper**

Run:

```powershell
npm.cmd run lint
```

Expected: lint exits 0 or reports only pre-existing warnings documented by the repository. Fix any new warning in the helper before continuing.

- [ ] **Step 6: Commit the frontend attempt helper**

From `../pix_frontend_v2`:

```powershell
git add src/features/orders/checkoutAttempt.ts src/features/orders/checkoutAttempt.test.ts
git commit -m "feat: persist checkout attempt keys"
```

---

### Task 6: Send and retire the browser idempotency key

**Files:**
- Modify: `../pix_frontend_v2/src/routes/routes.tsx:48-52,257-271`
- Create: `../pix_frontend_v2/src/routes/routes.test.ts`
- Modify: `../pix_frontend_v2/src/app/dashboard/neworder/page.tsx:1-20,176-213`

**Interfaces:**
- Consumes: `CheckoutOrderItem`, `getOrCreateCheckoutAttempt`, `clearCheckoutAttempt`, browser `localStorage`.
- Produces: `CreateOrder(data: CheckoutOrderItem[], addressId: string, idempotencyKey: string)` and a page flow that retains a key on failure and clears it on success.

- [ ] **Step 1: Write a failing Axios contract test**

Create `../pix_frontend_v2/src/routes/routes.test.ts`:

```typescript
import axios from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("axios", () => ({ default: { post: vi.fn() } }));
vi.mock("cookies-next", () => ({
  getCookie: () => "Bearer token",
  setCookie: vi.fn(),
}));
vi.mock("react-hot-toast", () => ({
  default: { promise: <T>(promise: Promise<T>) => promise },
}));
vi.mock("@/config/api", () => ({
  backendUrl: (path: string) => `http://backend/${path}`,
}));

import { CreateOrder } from "./routes";

describe("CreateOrder", () => {
  beforeEach(() => vi.clearAllMocks());

  it("sends the checkout key with the exact body", async () => {
    vi.mocked(axios.post).mockResolvedValue({ data: { id: "order" } });
    const items = [
      { link: "https://shop.example/item", count: 1, comment: "" },
    ];
    await CreateOrder(items, "address-id", "attempt-id");
    expect(axios.post).toHaveBeenCalledWith(
      "http://backend/orders",
      { address_id: "address-id", order_items: items },
      {
        headers: {
          Authorization: "Bearer token",
          "Idempotency-Key": "attempt-id",
        },
      },
    );
  });
});
```

- [ ] **Step 2: Run the Axios test and verify RED**

Run:

```powershell
npm.cmd run test:unit -- src/routes/routes.test.ts
```

Expected: TypeScript reports that `CreateOrder` accepts only two arguments, or the header assertion fails.

- [ ] **Step 3: Update the request wrapper**

Import the shared type and remove the private `OrderData` type:

```typescript
import type { CheckoutOrderItem } from "@/features/orders/checkoutAttempt";
```

Change the wrapper:

```typescript
export async function CreateOrder(
  data: CheckoutOrderItem[],
  addressId: string,
  idempotencyKey: string,
) {
  const promise = axios.post(
    backendUrl("orders"),
    { address_id: addressId, order_items: data },
    {
      headers: {
        Authorization: getCookie("token"),
        "Idempotency-Key": idempotencyKey,
      },
    },
  );
  return toast.promise(promise, {
    loading: "Создаём заказ",
    success: "Успешно!",
    error: "Ошибка!",
  });
}
```

Preserve the repository's actual UTF-8 Russian strings if the terminal renders them differently.

- [ ] **Step 4: Run the Axios test and verify GREEN**

Run:

```powershell
npm.cmd run test:unit -- src/routes/routes.test.ts
```

Expected: 1 test passes.

- [ ] **Step 5: Wire the persisted attempt into the page**

Import:

```typescript
import {
  clearCheckoutAttempt,
  getOrCreateCheckoutAttempt,
  type CheckoutOrderItem,
} from "@/features/orders/checkoutAttempt";
```

At the start of `submitOrder`, after the existing guard and before setting `submittingRef.current`, build the submitted payload once:

```typescript
const items: CheckoutOrderItem[] = data.map((item) => ({
  link: item.position,
  count: item.count,
  comment: item.comment || "",
}));
const attempt = getOrCreateCheckoutAttempt(localStorage, {
  addressId: selectedAddressId,
  items,
});
```

Call:

```typescript
await CreateOrder(items, selectedAddressId, attempt.key);
```

In the success branch, before navigation, clear only after the API resolves:

```typescript
clearCheckoutAttempt(localStorage);
localStorage.removeItem("cart");
setData([]);
router.replace("/dashboard/orders");
```

Do not clear the attempt in `catch` or `finally`. When an address is removed or cart data changes, the helper's next payload fingerprint replaces the old key automatically.

- [ ] **Step 6: Run focused frontend tests**

Run:

```powershell
npm.cmd run test:unit -- src/features/orders/checkoutAttempt.test.ts src/routes/routes.test.ts
```

Expected: all 4 focused tests pass.

- [ ] **Step 7: Run frontend type/build verification**

Run:

```powershell
npm.cmd run lint
npm.cmd run build
```

Expected: both commands exit 0, with no new warning from the modified checkout files.

- [ ] **Step 8: Commit the frontend contract integration**

```powershell
git add src/routes/routes.tsx src/routes/routes.test.ts src/app/dashboard/neworder/page.tsx
git commit -m "fix: reuse checkout keys across retries"
```

---

### Task 7: Update architecture documentation and run full verification

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Verify: all changed backend and frontend files

**Interfaces:**
- Consumes: completed backend and frontend implementation.
- Produces: source-of-truth documentation and fresh repository-wide verification evidence.

- [ ] **Step 1: Document the checkout idempotency flow**

Replace the checkout paragraph in `docs/ARCHITECTURE.md` with text that states all of the following explicitly:

```markdown
Checkout `POST /api_v1/orders` requires `address_id`, at least one valid item,
and a UUID `Idempotency-Key`. The browser persists one key for a logical
checkout attempt and reuses it after an uncertain response; changing the
address or cart starts a new attempt. The backend scopes the key to the user,
serializes it through Redis, rejects changed payloads for an existing key, and
replays the completed order response. Deterministic MoySklad `syncId` values
make generated products and the customer order safe to recreate after a
worker interruption. Only the owning request updates the last-used address
and attempts the Telegram notification.
```

Keep the existing immutable delivery-address snapshot explanation immediately after this paragraph.

- [ ] **Step 2: Run backend whitespace and full checks**

From `pix_backend`, run:

```powershell
git diff --check
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
```

Expected: `git diff --check` prints nothing; Ruff and the complete pytest suite exit 0.

- [ ] **Step 3: Verify startup contract without external services**

Run:

```powershell
.\.venv\Scripts\python.exe -c "from config import Settings; from main import create_app; app = create_app(Settings(_env_file=None, app_env='test')); print([route.path for route in app.routes if route.path == '/api_v1/health'])"
```

Expected output contains exactly `['/api_v1/health']`, and importing the app does not contact MoySklad or Telegram.

- [ ] **Step 4: Run frontend full checks**

From `../pix_frontend_v2`, run:

```powershell
git diff --check
npm.cmd run check
```

Expected: lint, API URL validation, all Vitest tests, production build, and Playwright tests exit 0. If a pre-existing repository warning remains, record it separately and verify no warning points to the changed checkout files.

- [ ] **Step 5: Review the final cross-repository contract**

Confirm from the final diff and tests:

```text
Backend rejects empty checkout before manager calls.
Backend requires a UUID Idempotency-Key.
Same user/key/payload returns the original order.
Same user/key/different payload returns 409.
Different keys permit intentional identical orders.
MoySklad product and customer-order payloads include stable syncId values.
Secondary effects run once for a completed attempt.
Frontend retains cart and key on failure, and clears both on success.
No migration or production integration call was added.
```

- [ ] **Step 6: Commit documentation after verification**

From `pix_backend`:

```powershell
git add docs/ARCHITECTURE.md
git commit -m "docs: describe idempotent checkout flow"
```

Do not commit generated `__pycache__`, test artifacts, build output, `.env`, or any unrelated dirty-worktree file.
