# Backend Production Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make order operations resilient to Telegram outages, classify asyncpg address conflicts correctly, and prevent MoySklad side effects when required order-state metadata is missing.

**Architecture:** A small notifier adapter owns the timeout and converts Telegram failures into a boolean result. Repository code traverses wrapped database exceptions without weakening uniqueness handling, while order changes perform a typed MoySklad metadata preflight before any product creation.

**Tech Stack:** Python 3.11, FastAPI, Pydantic Settings, SQLAlchemy, asyncpg, asyncio, pytest.

## Global Constraints

- Do not run Alembic or modify the database schema.
- Do not contact production Telegram, MoySklad, PostgreSQL, or Redis from unit tests.
- Read environment values only through `config.Settings`.
- Never log notification text, tokens, chat IDs, passwords, or authenticated URLs.
- Preserve all existing user changes and stage only files named by each task.
- Keep the old server and its Telegram bridge running.

---

### Task 1: Bounded best-effort Telegram adapter

**Files:**
- Create: `manager/telegram_notifications.py`
- Create: `tests/test_telegram_notifications.py`
- Modify: `config.py`
- Modify: `tests/test_config.py`
- Modify: `.env.example`
- Modify: `.env.production.example`
- Modify: `tests/test_production_config.py`

**Interfaces:**
- Consumes: an object exposing `async send_group_message(text: str) -> None` and `Settings.telegram_notification_timeout_seconds`.
- Produces: `BestEffortGroupNotifier.send_group_message(text: str) -> bool`.

- [ ] **Step 1: Write failing configuration and notifier tests**

Add to `tests/test_config.py`:

```python
def test_telegram_notification_timeout_is_positive_and_defaults_to_three_seconds():
    assert Settings(_env_file=None).telegram_notification_timeout_seconds == 3.0
    with pytest.raises(ValidationError):
        Settings(_env_file=None, telegram_notification_timeout_seconds=0)
```

Create `tests/test_telegram_notifications.py`:

```python
import asyncio
import logging

import pytest

from manager.telegram_notifications import BestEffortGroupNotifier


class SuccessfulSender:
    def __init__(self):
        self.messages = []

    async def send_group_message(self, text):
        self.messages.append(text)


class BlockingSender:
    async def send_group_message(self, text):
        await asyncio.Event().wait()


class FailedSender:
    async def send_group_message(self, text):
        raise RuntimeError("network unavailable")


@pytest.mark.asyncio
async def test_best_effort_notifier_reports_success():
    sender = SuccessfulSender()
    notifier = BestEffortGroupNotifier(sender, timeout_seconds=0.1)

    assert await notifier.send_group_message("safe text") is True
    assert sender.messages == ["safe text"]


@pytest.mark.asyncio
async def test_best_effort_notifier_bounds_timeout_without_logging_message(caplog):
    caplog.set_level(logging.WARNING)
    notifier = BestEffortGroupNotifier(BlockingSender(), timeout_seconds=0.001)

    assert await notifier.send_group_message("secret message body") is False
    assert "secret message body" not in caplog.text
    assert "timed out" in caplog.text


@pytest.mark.asyncio
async def test_best_effort_notifier_swallows_transport_failure(caplog):
    caplog.set_level(logging.WARNING)
    notifier = BestEffortGroupNotifier(FailedSender(), timeout_seconds=0.1)

    assert await notifier.send_group_message("not logged") is False
    assert "not logged" not in caplog.text
    assert "failed" in caplog.text
```

- [ ] **Step 2: Run the focused tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_config.py tests/test_telegram_notifications.py -q
```

Expected: collection fails because `manager.telegram_notifications` and the new setting do not exist.

- [ ] **Step 3: Add the setting and minimal adapter**

Add this field to `Settings` in `config.py`:

```python
telegram_notification_timeout_seconds: float = Field(3.0, gt=0)
```

Create `manager/telegram_notifications.py`:

```python
import asyncio
import logging
from typing import Protocol


class GroupMessageSender(Protocol):
    async def send_group_message(self, text: str) -> None: ...


class BestEffortGroupNotifier:
    def __init__(
        self,
        sender: GroupMessageSender,
        timeout_seconds: float,
        logger: logging.Logger | None = None,
    ) -> None:
        self._sender = sender
        self._timeout_seconds = timeout_seconds
        self._logger = logger or logging.getLogger(__name__)

    async def send_group_message(self, text: str) -> bool:
        try:
            await asyncio.wait_for(
                self._sender.send_group_message(text),
                timeout=self._timeout_seconds,
            )
        except TimeoutError:
            self._logger.warning("Telegram group notification timed out")
            return False
        except Exception:
            self._logger.warning(
                "Telegram group notification failed",
                exc_info=True,
            )
            return False
        return True
```

Add to `.env.example` and `.env.production.example`:

```dotenv
TELEGRAM_NOTIFICATION_TIMEOUT_SECONDS=3
```

Update the exact-key expectations in `tests/test_production_config.py` so the production template includes that key with value `3`.

- [ ] **Step 4: Run focused tests and verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_config.py tests/test_telegram_notifications.py tests/test_production_config.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit the adapter**

```powershell
git add config.py manager/telegram_notifications.py tests/test_config.py tests/test_telegram_notifications.py .env.example .env.production.example tests/test_production_config.py
git commit -m "fix: bound Telegram notification delivery"
```

### Task 2: Use the bounded notifier for order mutations

**Files:**
- Modify: `dependecies/orders.py`
- Modify: `manager/order_creation.py`
- Modify: `manager/order_changes.py`
- Modify: `routes/orders.py`
- Modify: `tests/test_order_creation.py`
- Modify: `tests/test_order_changes.py`
- Modify: `tests/test_order_creation_api.py`

**Interfaces:**
- Consumes: `BestEffortGroupNotifier.send_group_message(text: str) -> bool` from Task 1.
- Produces: `dependecies.orders.get_order_notifier()` and order HTTP responses that do not fail solely because Telegram is unavailable.

- [ ] **Step 1: Add failing manager tests for a false notifier result**

Use this stub shape in both order-manager test modules:

```python
class StubNotifier:
    def __init__(self, events=None, result=True, error=None):
        self.events = events if events is not None else []
        self.result = result
        self.error = error
        self.messages = []

    async def send_group_message(self, text):
        self.events.append("notify")
        self.messages.append(text)
        if self.error:
            raise self.error
        return self.result
```

Add an order-creation test asserting the created order is returned when the notifier returns `False`. Add this order-change assertion:

```python
result = await OrderChangesManager(
    orders,
    StubProducts(),
    StubNotifier(result=False),
).save_changes(make_user(), orders.order["id"], request)

assert result.changed is True
assert result.notification_sent is False
assert len(orders.replacements) == 1
```

- [ ] **Step 2: Run the manager tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_order_creation.py tests/test_order_changes.py -q
```

Expected: the order-change test fails because a false result is currently reported as sent.

- [ ] **Step 3: Wire one production adapter and consume its result**

In `dependecies/orders.py`, add:

```python
def get_order_notifier() -> BestEffortGroupNotifier:
    settings = get_settings()
    return BestEffortGroupNotifier(
        telegram_sender,
        timeout_seconds=settings.telegram_notification_timeout_seconds,
    )
```

Construct both order managers with `get_order_notifier()` instead of the raw sender.

In `OrderChangesManager._save_loaded_order`, use:

```python
try:
    notification_result = await self._notifier.send_group_message(
        format_order_change_message(updated_order, user, plan.summary)
    )
    notification_sent = notification_result is not False
except Exception:
    logger.warning("Telegram order-change notification failed", exc_info=True)
    notification_sent = False
```

Keep the defensive `try/except` in `OrderCreationManager` so future injected notifier implementations cannot break a completed checkout.

In `routes/orders.py`, inject this dependency into state confirmation and cancellation:

```python
notifier: BestEffortGroupNotifier = Depends(dependency_orders.get_order_notifier)
```

Replace both raw sender calls with `notifier.send_group_message(...)`, remove the direct sender import, and ignore the boolean because the MoySklad mutation is already complete.

- [ ] **Step 4: Prove order routes no longer depend on the raw sender**

Add route tests that override `get_order_notifier` with a stub returning `False`, override the MoySklad manager with a stub returning an order, and assert state confirmation and cancellation both return HTTP 200.

- [ ] **Step 5: Run all affected order tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_telegram_notifications.py tests/test_order_creation.py tests/test_order_creation_api.py tests/test_order_changes.py tests/test_order_changes_api.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit order integration**

```powershell
git add dependecies/orders.py manager/order_creation.py manager/order_changes.py routes/orders.py tests/test_order_creation.py tests/test_order_changes.py tests/test_order_creation_api.py
git commit -m "fix: keep order responses independent of Telegram"
```

### Task 3: Asyncpg address uniqueness classification

**Files:**
- Modify: `db/address_repository.py`
- Modify: `tests/test_address_repository.py`

**Interfaces:**
- Consumes: exception chains containing `orig`, `__cause__`, `__context__`, `diag.constraint_name`, or `constraint_name`.
- Produces: `constraint_name(exc: BaseException | object) -> str | None`.

- [ ] **Step 1: Write failing nested-wrapper tests**

Add:

```python
from types import SimpleNamespace

from db.address_repository import constraint_name


def test_constraint_name_finds_asyncpg_name_through_sqlalchemy_wrapper():
    driver_error = SimpleNamespace(
        diag=SimpleNamespace(constraint_name="uq_address_user_normalized_name")
    )
    adapter_error = SimpleNamespace(orig=driver_error)
    sqlalchemy_error = SimpleNamespace(orig=adapter_error)

    assert constraint_name(sqlalchemy_error) == "uq_address_user_normalized_name"


def test_constraint_name_is_cycle_safe_and_ignores_unknown_errors():
    wrapper = RuntimeError("other integrity error")
    wrapper.__cause__ = wrapper

    assert constraint_name(wrapper) is None
```

- [ ] **Step 2: Run the repository tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_address_repository.py -q
```

Expected: the nested-wrapper assertion returns `None`.

- [ ] **Step 3: Implement cycle-safe traversal**

Replace `constraint_name` with:

```python
def constraint_name(exc: BaseException | object) -> str | None:
    pending = [exc]
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        if current is None or id(current) in visited:
            continue
        visited.add(id(current))

        name = getattr(current, "constraint_name", None)
        if isinstance(name, str):
            return name
        diag_name = getattr(getattr(current, "diag", None), "constraint_name", None)
        if isinstance(diag_name, str):
            return diag_name

        pending.extend(
            getattr(current, attribute, None)
            for attribute in ("orig", "__cause__", "__context__")
        )
    return None
```

Do not add message-string parsing. The existing known-constraint comparisons stay unchanged, so unrelated integrity failures still propagate.

- [ ] **Step 4: Run repository and API tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_address_repository.py tests/test_address_api.py tests/test_addresses.py -q
```

Expected: all selected tests pass and the existing HTTP 409 contract remains green.

- [ ] **Step 5: Commit address fix**

```powershell
git add db/address_repository.py tests/test_address_repository.py
git commit -m "fix: classify wrapped address uniqueness errors"
```

### Task 4: MoySklad order-state preflight

**Files:**
- Modify: `errors.py`
- Modify: `manager/moysklad.py`
- Modify: `manager/order_changes.py`
- Modify: `routes/orders.py`
- Modify: `tests/test_order_changes.py`
- Modify: `tests/test_order_changes_api.py`

**Interfaces:**
- Produces: `MoySkladOrderStateMissing(state_name: str)` with public `state_name`.
- Consumes: `CustomerOrderGateway.get_state_meta(TARGET_ORDER_STATUS)` before product creation.
- Produces: HTTP 503 detail code `moysklad_order_state_missing`.

- [ ] **Step 1: Write a failing no-side-effect manager test**

Extend `StubCustomerOrders` with `state_error` and `state_lookups`, raising from `get_state_meta` when configured. Add:

```python
@pytest.mark.asyncio
async def test_missing_target_state_is_detected_before_product_creation():
    error = MoySkladOrderStateMissing("Изменен клиентом")
    orders = StubCustomerOrders(state_error=error)
    products = StubProducts()
    notifier = StubNotifier()
    request = OrderChangesRequest(
        expected_updated=orders.order["updated"],
        positions=[
            ExistingOrderPositionChange(id=POSITION_1, count=1),
            NewOrderPositionChange(
                link="https://shop.example/new", count=1, comment=""
            ),
        ],
    )

    with pytest.raises(MoySkladOrderStateMissing):
        await OrderChangesManager(orders, products, notifier).save_changes(
            make_user(), orders.order["id"], request
        )

    assert products.orders == []
    assert orders.replacements == []
    assert notifier.messages == []
```

- [ ] **Step 2: Add a failing HTTP mapping test**

Add `MoySkladOrderStateMissing("Изменен клиентом")` to the parameterized API test with expected status `503` and code `moysklad_order_state_missing`.

- [ ] **Step 3: Run the focused tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_order_changes.py tests/test_order_changes_api.py -q
```

Expected: import or assertion failure because the typed error and mapping do not exist and state lookup still follows product creation.

- [ ] **Step 4: Add the typed error and raise it from metadata lookup**

Add to `errors.py`:

```python
class MoySkladOrderStateMissing(RuntimeError):
    def __init__(self, state_name: str) -> None:
        self.state_name = state_name
        super().__init__("required MoySklad order state is missing")
```

In `CustomerOrderManager.get_state_meta`, replace the generic error with:

```python
raise MoySkladOrderStateMissing(state_name)
```

- [ ] **Step 5: Move state resolution before product creation**

Resolve:

```python
state_meta = await self._customer_orders.get_state_meta(TARGET_ORDER_STATUS)
```

immediately after the no-op return and before constructing `product_rows`. Remove the old lookup below position serialization.

- [ ] **Step 6: Map the typed error without exposing account metadata**

In `order_change_http_error`, add:

```python
if isinstance(exc, MoySkladOrderStateMissing):
    return HTTPException(
        503,
        detail={
            "code": "moysklad_order_state_missing",
            "message": "Order editing is temporarily unavailable",
        },
    )
```

Add the error to every order-change route catch tuple: batch changes, quantity update, position removal, and position addition.

- [ ] **Step 7: Run state-preflight tests and verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_order_changes.py tests/test_order_changes_api.py -q
```

Expected: all selected tests pass and no product call occurs on missing state.

- [ ] **Step 8: Commit preflight fix**

```powershell
git add errors.py manager/moysklad.py manager/order_changes.py routes/orders.py tests/test_order_changes.py tests/test_order_changes_api.py
git commit -m "fix: validate MoySklad state before creating products"
```

### Task 5: Backend verification

**Files:**
- No new files

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces: a verified backend commit set suitable for an immutable production image.

- [ ] **Step 1: Run formatting integrity checks**

```powershell
git diff --check
```

Expected: no whitespace errors in implementation files.

- [ ] **Step 2: Run the repository verification command**

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
```

Expected: Ruff exits zero and the full pytest suite passes.

- [ ] **Step 3: Inspect only the implementation diff**

```powershell
git status --short
git diff --stat HEAD~4..HEAD
```

Confirm no `.env`, token, password, production data, `__pycache__`, or unrelated user file is committed. Do not clean or revert pre-existing working-tree changes.
