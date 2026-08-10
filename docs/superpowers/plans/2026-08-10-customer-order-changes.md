# Customer Order Changes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Разрешить клиенту пакетно добавлять, удалять и менять количество позиций подтверждённого заказа, переводя реально изменённый заказ в статус `Изменен клиентом` и отправляя одно уведомление в рабочую Telegram-группу.

**Architecture:** Frontend хранит исходный снимок и локальный draft заказа, а по кнопке отправляет полный желаемый набор позиций и `expected_updated` в новый endpoint. Новый backend manager проверяет владельца, статус и версию, создаёт товары для новых строк, одним запросом заменяет позиции вместе со статусом в МойСклад и затем отправляет Telegram-сводку; существующие немедленные endpoints проходят через тот же manager.

**Tech Stack:** Python 3.11, FastAPI 0.104, Pydantic 2.5, requests 2.31, aiogram 3.3, pytest; Next.js 14, React 18, TypeScript 5, Axios 1.6, AG Grid 31, React Hook Form 7, Vitest 3, Playwright.

## Global Constraints

- Точное имя целевого статуса: `Изменен клиентом`.
- Редактирование разрешено только для `Подтвержден менеджером`, `Ожидает подтверждения клиента`, `Подтвержден клиентом`, `Изменен клиентом`.
- В любом другом статусе frontend работает read-only, а backend отвечает конфликтом и не изменяет МойСклад.
- Клиент может добавить позицию, удалить позицию или изменить целое положительное количество; название и комментарий существующей позиции, цена и рассчитанные магазином поля не редактируются.
- Новая позиция требует непустую `Позиция` и положительное целое `Количество`; `Комментарий` может быть пустым.
- Сохранение пустого заказа запрещено; для отказа от последней позиции используется отмена всего заказа.
- До нажатия `Сохранить изменения` нельзя вызывать mutation endpoints МойСклад или Telegram.
- Одна серия правок создаёт один batch-запрос, одно обновление заказа и не более одного Telegram-сообщения.
- No-op не меняет статус и не отправляет Telegram.
- Backend проверяет владельца, статус и `expected_updated` по свежему ответу МойСклад; клиентские цена, assortment meta и владелец не считаются доверенными.
- Ошибка МойСклад оставляет draft для повтора и не отправляет Telegram.
- Ошибка Telegram после сохранения не откатывает заказ: ответ содержит `notification_sent: false`, а frontend предупреждает без повторного применения правок.
- Существующие endpoints отдельных операций нельзя использовать для обхода проверки статуса, смены статуса или уведомления.
- Не добавлять PostgreSQL-модель, Alembic migration, очередь или outbox.
- Все тесты используют fakes или локальный mock backend; не обращаться к рабочим МойСклад, Telegram или иным внешним сервисам.
- Сохранять границы `routes/` → `dependecies/` → `manager/` → repository и размещать frontend HTTP-вызовы только в `src/routes/routes.tsx`.
- Выполнить backend `scripts/check.ps1` и frontend `npm.cmd run check` после финальных изменений.

## File Structure

Backend repository (`pix_backend`):

- Modify `db/schemas/orders.py` — transport models для полного набора позиций и результата сохранения.
- Create `manager/order_changes.py` — разрешённые статусы, diff/serialization helpers, исключения, manager orchestration и Telegram-сводка.
- Modify `manager/moysklad.py` — методы получения state meta и единого обновления `positions + state`.
- Modify `db/repository.py` — проверка HTTP-ошибок в операциях МойСклад, используемых новым сценарием, и исключение служебного `link` из JSON.
- Modify `dependecies/orders.py` — создание `OrderChangesManager` с текущими МойСклад managers и `telegram_sender`.
- Modify `routes/orders.py` — `PUT /orders/{order_id}/changes`, HTTP mapping доменных ошибок и перевод legacy mutation routes на общий manager.
- Modify `errors.py` — типизированные ошибки доступа, статуса, версии и недопустимого набора позиций.
- Modify `scripts/check.ps1` — lint новых/изменённых Python-модулей.
- Modify `docs/ARCHITECTURE.md` — новый пакетный order-change flow и статусная граница.
- Create `tests/test_order_changes.py` — schema/domain/orchestration tests.
- Create `tests/test_order_changes_api.py` — endpoint, dependency override, authentication и legacy compatibility tests.
- Modify `tests/test_integrations.py` — HTTP error propagation repository tests без сети.

Frontend repository (`../pix_frontend_v2`):

- Create `src/app/dashboard/orders/[id]/orderChanges.ts` — чистая status/draft/diff/payload логика.
- Create `src/app/dashboard/orders/[id]/orderChanges.test.ts` — unit tests чистой логики.
- Create `src/app/dashboard/orders/[id]/OrderPositionAddForm.tsx` — форма локального добавления позиции.
- Modify `src/components/inputs/pixInputs.tsx` — поддержка `disabled` в общей input-обёртке.
- Modify `src/routes/routes.tsx` — расширенные order types и `SaveOrderChangesEndpoint`.
- Modify `src/app/dashboard/orders/[id]/page.tsx` — локальный draft, единое сохранение, read-only/status/conflict/warning UI.
- Modify `tests/mock-backend.mjs` — детерминированные detail/update/conflict/read-only ответы.
- Create `tests/order-changes.spec.ts` — browser tests пакетного редактирования и ошибок.

---

### Task 1: Backend transport schemas and pure order-change planning

**Files:**
- Modify: `db/schemas/orders.py`
- Modify: `errors.py`
- Create: `manager/order_changes.py`
- Create: `tests/test_order_changes.py`

**Interfaces:**
- Produces: `ExistingOrderPositionChange(id: UUID, count: int)`.
- Produces: `NewOrderPositionChange(link: str, count: int, comment: str = "")`.
- Produces: `OrderChangesRequest(expected_updated: str, positions: list[ExistingOrderPositionChange | NewOrderPositionChange])`.
- Produces: `OrderChangesResponse(order: dict, changed: bool, notification_sent: bool | None)`.
- Produces: `EDITABLE_ORDER_STATUSES`, `TARGET_ORDER_STATUS`, `is_order_editable(status)`, `OrderChangeSummary`, `OrderChangePlan`, and `build_order_change_plan(current_rows, requested_positions)`.
- Produces: `OrderNotAccessible`, `OrderNotEditable`, `OrderVersionConflict`, and `InvalidOrderChanges` for Task 2/3.

- [ ] **Step 1: Write failing schema and planning tests**

Create `tests/test_order_changes.py` with valid UUID fixtures and the first pure tests:

```python
from uuid import UUID

import pytest
from pydantic import ValidationError

from db.schemas.orders import (
    ExistingOrderPositionChange,
    NewOrderPositionChange,
    OrderChangesRequest,
)
from errors import InvalidOrderChanges
from manager.order_changes import (
    build_order_change_plan,
    is_order_editable,
)

POSITION_1 = UUID("00000000-0000-0000-0000-000000000001")
POSITION_2 = UUID("00000000-0000-0000-0000-000000000002")


def current_rows():
    return [
        {
            "id": str(POSITION_1),
            "quantity": 1,
            "price": 12500,
            "discount": 0,
            "vat": 0,
            "vatEnabled": False,
            "reserve": 0,
            "assortment": {"meta": {"href": "https://api.moysklad.ru/product/1"}},
        },
        {
            "id": str(POSITION_2),
            "quantity": 2,
            "price": 5000,
            "discount": 5,
            "vat": 20,
            "vatEnabled": True,
            "reserve": 1,
            "assortment": {"meta": {"href": "https://api.moysklad.ru/product/2"}},
        },
    ]


@pytest.mark.parametrize(
    ("status", "editable"),
    [
        ("Подтвержден менеджером", True),
        ("Ожидает подтверждения клиента", True),
        ("Подтвержден клиентом", True),
        ("Изменен клиентом", True),
        ("Принят к исполнению", False),
        ("Отменен", False),
    ],
)
def test_order_editability_follows_the_business_status_boundary(status, editable):
    assert is_order_editable(status) is editable


def test_request_rejects_empty_positions_duplicate_ids_and_invalid_counts():
    with pytest.raises(ValidationError):
        OrderChangesRequest(expected_updated="2026-08-10 12:00:00.000", positions=[])
    with pytest.raises(ValidationError):
        ExistingOrderPositionChange(id=POSITION_1, count=0)
    with pytest.raises(ValidationError):
        NewOrderPositionChange(link="   ", count=1, comment="")
    with pytest.raises(ValidationError):
        OrderChangesRequest(
            expected_updated="2026-08-10 12:00:00.000",
            positions=[
                ExistingOrderPositionChange(id=POSITION_1, count=1),
                ExistingOrderPositionChange(id=POSITION_1, count=2),
            ],
        )


def test_plan_counts_add_remove_and_quantity_changes():
    request = OrderChangesRequest(
        expected_updated="2026-08-10 12:00:00.000",
        positions=[
            ExistingOrderPositionChange(id=POSITION_1, count=3),
            NewOrderPositionChange(link="https://shop.example/item", count=1, comment="black"),
        ],
    )

    plan = build_order_change_plan(current_rows(), request.positions)

    assert plan.summary.added == 1
    assert plan.summary.removed == 1
    assert plan.summary.quantity_changed == 1
    assert [item.server_position["id"] for item in plan.existing] == [str(POSITION_1)]
    assert plan.existing[0].count == 3
    assert plan.new == tuple(request.positions[1:])


def test_plan_recognizes_noop_and_rejects_unknown_position():
    no_op = build_order_change_plan(
        current_rows(),
        [
            ExistingOrderPositionChange(id=POSITION_1, count=1),
            ExistingOrderPositionChange(id=POSITION_2, count=2),
        ],
    )
    assert no_op.summary.changed is False

    with pytest.raises(InvalidOrderChanges, match="unknown position"):
        build_order_change_plan(
            current_rows(),
            [
                ExistingOrderPositionChange(
                    id=UUID("00000000-0000-0000-0000-000000000099"),
                    count=1,
                )
            ],
        )
```

- [ ] **Step 2: Run the focused test and verify RED**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_order_changes.py -v
```

Expected: collection fails because the new schemas, errors, and `manager.order_changes` do not exist. Confirm that the failure is not caused by fixture syntax.

- [ ] **Step 3: Add strict Pydantic request/response models**

Append to `db/schemas/orders.py`:

```python
from pydantic import ConfigDict, Field, field_validator, model_validator


class ExistingOrderPositionChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    count: int = Field(gt=0)


class NewOrderPositionChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    link: str = Field(min_length=1)
    count: int = Field(gt=0)
    comment: str = ""

    @field_validator("link")
    @classmethod
    def strip_and_require_link(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("link must not be blank")
        return value


OrderPositionChange = ExistingOrderPositionChange | NewOrderPositionChange


class OrderChangesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_updated: str = Field(min_length=1)
    positions: list[OrderPositionChange] = Field(min_length=1)

    @model_validator(mode="after")
    def reject_duplicate_existing_ids(self):
        ids = [str(item.id) for item in self.positions if isinstance(item, ExistingOrderPositionChange)]
        if len(ids) != len(set(ids)):
            raise ValueError("existing position ids must be unique")
        return self


class OrderChangesResponse(BaseModel):
    order: dict
    changed: bool
    notification_sent: bool | None
```

Keep the existing `OrderCreate` contract unchanged.

- [ ] **Step 4: Add domain errors and pure diff types**

Append to `errors.py`:

```python
class OrderNotAccessible(RuntimeError):
    pass


class OrderNotEditable(RuntimeError):
    def __init__(self, status: str) -> None:
        self.status = status
        super().__init__("order is not editable")


class OrderVersionConflict(RuntimeError):
    pass


class InvalidOrderChanges(ValueError):
    pass
```

Create `manager/order_changes.py` with the constants, dataclasses, and pure planner:

```python
from dataclasses import dataclass

from db.schemas.orders import ExistingOrderPositionChange, NewOrderPositionChange, OrderPositionChange
from errors import InvalidOrderChanges

EDITABLE_ORDER_STATUSES = frozenset(
    {
        "Подтвержден менеджером",
        "Ожидает подтверждения клиента",
        "Подтвержден клиентом",
        "Изменен клиентом",
    }
)
TARGET_ORDER_STATUS = "Изменен клиентом"


def is_order_editable(status: str) -> bool:
    return status in EDITABLE_ORDER_STATUSES


@dataclass(frozen=True)
class ExistingPositionUpdate:
    server_position: dict
    count: int


@dataclass(frozen=True)
class OrderChangeSummary:
    added: int
    removed: int
    quantity_changed: int

    @property
    def changed(self) -> bool:
        return any((self.added, self.removed, self.quantity_changed))


@dataclass(frozen=True)
class OrderChangePlan:
    existing: tuple[ExistingPositionUpdate, ...]
    new: tuple[NewOrderPositionChange, ...]
    summary: OrderChangeSummary


def build_order_change_plan(
    current_rows: list[dict],
    requested_positions: list[OrderPositionChange],
) -> OrderChangePlan:
    current_by_id = {str(row["id"]): row for row in current_rows}
    requested_existing = [
        item for item in requested_positions if isinstance(item, ExistingOrderPositionChange)
    ]
    requested_new = tuple(
        item for item in requested_positions if isinstance(item, NewOrderPositionChange)
    )
    requested_ids = {str(item.id) for item in requested_existing}
    unknown_ids = requested_ids - current_by_id.keys()
    if unknown_ids:
        raise InvalidOrderChanges("unknown position id")

    existing = tuple(
        ExistingPositionUpdate(current_by_id[str(item.id)], item.count)
        for item in requested_existing
    )
    quantity_changed = sum(
        int(float(item.server_position["quantity"]) != item.count) for item in existing
    )
    summary = OrderChangeSummary(
        added=len(requested_new),
        removed=len(current_by_id.keys() - requested_ids),
        quantity_changed=quantity_changed,
    )
    return OrderChangePlan(existing=existing, new=requested_new, summary=summary)
```

- [ ] **Step 5: Run focused tests and verify GREEN**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_order_changes.py -v
```

Expected: the four schema/planner tests PASS.

- [ ] **Step 6: Commit the domain boundary**

```powershell
git add db/schemas/orders.py errors.py manager/order_changes.py tests/test_order_changes.py
git commit -m "feat: model customer order changes"
```

---

### Task 2: Backend save orchestration and Telegram summary

**Files:**
- Modify: `manager/order_changes.py`
- Modify: `tests/test_order_changes.py`

**Interfaces:**
- Consumes: `CustomerOrderGateway.get_order_by_id(id)`, `get_state_meta(name)`, and `replace_positions_and_state(id, positions, state_meta)`; concrete adapter arrives in Task 3.
- Consumes: `ProductGateway.create_products(order: OrderCreate, user)` and `GroupNotifier.send_group_message(text)`.
- Produces: `OrderChangesManager.save_changes(user, order_id, request) -> OrderChangesResponse`.
- Produces: `format_order_change_message(order, user, summary) -> str` with HTML escaping.

- [ ] **Step 1: Add failing orchestration tests with fakes**

Append to `tests/test_order_changes.py`:

```python
from types import SimpleNamespace

from db.schemas.orders import OrderChangesResponse
from errors import OrderNotAccessible, OrderNotEditable, OrderVersionConflict
from manager.order_changes import OrderChangesManager


def order_payload(status="Подтвержден менеджером", updated="2026-08-10 12:00:00.000"):
    return {
        "id": "00000000-0000-0000-0000-000000000010",
        "name": "101",
        "updated": updated,
        "state": {"name": status},
        "agent": {"meta": {"href": "https://api.moysklad.ru/counterparty/00000000-0000-0000-0000-000000000020"}},
        "meta": {"uuidHref": "https://online.moysklad.ru/app/#customerorder/edit?id=order"},
        "positions": {"rows": current_rows()},
    }


class StubCustomerOrders:
    def __init__(self, order=None, error=None):
        self.order = order or order_payload()
        self.error = error
        self.replacements = []

    async def get_order_by_id(self, order_id):
        return self.order

    async def get_state_meta(self, state_name):
        assert state_name == "Изменен клиентом"
        return {"href": "https://api.moysklad.ru/state/changed"}

    async def replace_positions_and_state(self, order_id, positions, state_meta):
        if self.error:
            raise self.error
        self.replacements.append((str(order_id), positions, state_meta))
        return {
            **self.order,
            "updated": "2026-08-10 12:01:00.000",
            "state": {"name": "Изменен клиентом"},
            "positions": {"rows": positions},
        }


class StubProducts:
    def __init__(self):
        self.orders = []

    async def create_products(self, order, user):
        self.orders.append(order)
        return [{"meta": {"href": "https://api.moysklad.ru/product/new"}} for _ in order.order_items]


class StubNotifier:
    def __init__(self, error=None):
        self.error = error
        self.messages = []

    async def send_group_message(self, text):
        if self.error:
            raise self.error
        self.messages.append(text)


def test_user():
    return SimpleNamespace(
        moysklad_counterparty_id=UUID("00000000-0000-0000-0000-000000000020"),
        first_name="<Иван>",
        name_id=42,
    )


@pytest.mark.asyncio
async def test_manager_updates_positions_and_state_once_then_notifies_once():
    orders = StubCustomerOrders()
    products = StubProducts()
    notifier = StubNotifier()
    manager = OrderChangesManager(orders, products, notifier)
    request = OrderChangesRequest(
        expected_updated="2026-08-10 12:00:00.000",
        positions=[
            ExistingOrderPositionChange(id=POSITION_1, count=3),
            NewOrderPositionChange(link="https://shop.example/item", count=1, comment="black"),
        ],
    )

    result = await manager.save_changes(test_user(), orders.order["id"], request)

    assert isinstance(result, OrderChangesResponse)
    assert result.changed is True
    assert result.notification_sent is True
    assert len(orders.replacements) == 1
    _, positions, state_meta = orders.replacements[0]
    assert state_meta == {"href": "https://api.moysklad.ru/state/changed"}
    assert positions[0]["id"] == str(POSITION_1)
    assert positions[0]["quantity"] == 3
    assert positions[0]["price"] == 12500
    assert positions[1] == {
        "quantity": 1,
        "price": 0,
        "discount": 0,
        "vat": 0,
        "vatEnabled": False,
        "reserve": 0,
        "assortment": {"meta": {"href": "https://api.moysklad.ru/product/new"}},
    }
    assert len(notifier.messages) == 1
    assert "&lt;Иван&gt;" in notifier.messages[0]
    assert "Добавлено: 1" in notifier.messages[0]
    assert "Удалено: 1" in notifier.messages[0]
    assert "Количество изменено: 1" in notifier.messages[0]


@pytest.mark.asyncio
async def test_manager_noop_does_not_change_state_create_products_or_notify():
    orders = StubCustomerOrders()
    products = StubProducts()
    notifier = StubNotifier()
    manager = OrderChangesManager(orders, products, notifier)
    request = OrderChangesRequest(
        expected_updated=orders.order["updated"],
        positions=[
            ExistingOrderPositionChange(id=POSITION_1, count=1),
            ExistingOrderPositionChange(id=POSITION_2, count=2),
        ],
    )

    result = await manager.save_changes(test_user(), orders.order["id"], request)

    assert result.changed is False
    assert result.notification_sent is None
    assert orders.replacements == []
    assert products.orders == []
    assert notifier.messages == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("order", "expected_error"),
    [
        (order_payload(status="Принят к исполнению"), OrderNotEditable),
        (order_payload(updated="2026-08-10 12:00:01.000"), OrderVersionConflict),
        ({**order_payload(), "agent": {"meta": {"href": "https://api.moysklad.ru/counterparty/other"}}}, OrderNotAccessible),
    ],
)
async def test_manager_rejects_status_version_and_owner_before_side_effects(order, expected_error):
    orders = StubCustomerOrders(order)
    products = StubProducts()
    notifier = StubNotifier()
    manager = OrderChangesManager(orders, products, notifier)
    request = OrderChangesRequest(
        expected_updated="2026-08-10 12:00:00.000",
        positions=[ExistingOrderPositionChange(id=POSITION_1, count=2)],
    )

    with pytest.raises(expected_error):
        await manager.save_changes(test_user(), order["id"], request)

    assert orders.replacements == []
    assert products.orders == []
    assert notifier.messages == []


@pytest.mark.asyncio
async def test_moysklad_failure_skips_telegram_and_telegram_failure_returns_warning():
    request = OrderChangesRequest(
        expected_updated="2026-08-10 12:00:00.000",
        positions=[ExistingOrderPositionChange(id=POSITION_1, count=2)],
    )
    failed_orders = StubCustomerOrders(error=RuntimeError("moysklad unavailable"))
    notifier = StubNotifier()
    with pytest.raises(RuntimeError, match="moysklad unavailable"):
        await OrderChangesManager(failed_orders, StubProducts(), notifier).save_changes(
            test_user(), failed_orders.order["id"], request
        )
    assert notifier.messages == []

    orders = StubCustomerOrders()
    result = await OrderChangesManager(
        orders, StubProducts(), StubNotifier(error=RuntimeError("telegram unavailable"))
    ).save_changes(test_user(), orders.order["id"], request)
    assert result.changed is True
    assert result.notification_sent is False
```

- [ ] **Step 2: Run the manager tests and verify RED**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_order_changes.py -v
```

Expected: the new tests fail because `OrderChangesManager` and the protocol/serialization helpers are not implemented.

- [ ] **Step 3: Implement gateway protocols, writable-position serialization, and message formatting**

Extend `manager/order_changes.py`:

```python
import logging
from html import escape
from typing import Protocol

from db.models.users import User
from db.schemas.orders import OrderChangesRequest, OrderChangesResponse, OrderCreate, OrderItemCreate
from errors import OrderNotAccessible, OrderNotEditable, OrderVersionConflict

logger = logging.getLogger(__name__)


class CustomerOrderGateway(Protocol):
    async def get_order_by_id(self, order_id) -> dict: ...
    async def get_state_meta(self, state_name: str) -> dict: ...
    async def replace_positions_and_state(
        self, order_id, positions: list[dict], state_meta: dict
    ) -> dict: ...


class ProductGateway(Protocol):
    async def create_products(self, order: OrderCreate, user: User) -> list[dict]: ...


class GroupNotifier(Protocol):
    async def send_group_message(self, text: str) -> None: ...


def serialize_existing_position(item: ExistingPositionUpdate) -> dict:
    row = item.server_position
    result = {
        "id": str(row["id"]),
        "quantity": item.count,
        "price": row["price"],
        "discount": row["discount"],
        "vat": row["vat"],
        "vatEnabled": row.get("vatEnabled", False),
        "reserve": min(float(row.get("reserve", 0)), item.count),
        "assortment": {"meta": row["assortment"]["meta"]},
    }
    for optional_field in ("pack", "taxSystem"):
        if optional_field in row:
            result[optional_field] = row[optional_field]
    return result


def serialize_new_position(item: NewOrderPositionChange, product: dict) -> dict:
    return {
        "quantity": item.count,
        "price": 0,
        "discount": 0,
        "vat": 0,
        "vatEnabled": False,
        "reserve": 0,
        "assortment": {"meta": product["meta"]},
    }


def format_order_change_message(order: dict, user: User, summary: OrderChangeSummary) -> str:
    href = escape(order["meta"]["uuidHref"], quote=True)
    order_name = escape(str(order.get("name", order["id"])))
    first_name = escape(str(user.first_name))
    return (
        f'<a href="{href}">Заказ #{order_name}</a> изменён клиентом\n'
        f"Пользователь: {first_name} Клиент #{user.name_id}\n"
        f"Добавлено: {summary.added}\n"
        f"Удалено: {summary.removed}\n"
        f"Количество изменено: {summary.quantity_changed}\n"
        f"Статус: <b>{TARGET_ORDER_STATUS}</b>"
    )
```

Do not serialize response-only `sum`, `shipped`, `accountId`, `meta`, `updated`, or expanded assortment fields back into a position. Preserve required pricing/tax/reserve values from the fresh server row and clamp reserve when quantity decreases.

- [ ] **Step 4: Implement `OrderChangesManager.save_changes`**

Add to `manager/order_changes.py`:

```python
class OrderChangesManager:
    def __init__(
        self,
        customer_orders: CustomerOrderGateway,
        products: ProductGateway,
        notifier: GroupNotifier,
    ) -> None:
        self._customer_orders = customer_orders
        self._products = products
        self._notifier = notifier

    @staticmethod
    def _validate_context(order: dict, user: User, expected_updated: str) -> None:
        agent_href = order.get("agent", {}).get("meta", {}).get("href", "")
        if agent_href.rsplit("/", 1)[-1] != str(user.moysklad_counterparty_id):
            raise OrderNotAccessible()
        status = order.get("state", {}).get("name", "")
        if not is_order_editable(status):
            raise OrderNotEditable(status)
        if order.get("updated") != expected_updated:
            raise OrderVersionConflict()

    async def save_changes(
        self,
        user: User,
        order_id,
        request: OrderChangesRequest,
    ) -> OrderChangesResponse:
        order = await self._customer_orders.get_order_by_id(order_id)
        if not order or not order.get("id"):
            raise OrderNotAccessible()
        self._validate_context(order, user, request.expected_updated)
        plan = build_order_change_plan(order["positions"]["rows"], request.positions)
        if not plan.summary.changed:
            return OrderChangesResponse(order=order, changed=False, notification_sent=None)

        product_rows = OrderCreate(
            order_items=[
                OrderItemCreate(link=item.link, count=item.count, comment=item.comment)
                for item in plan.new
            ]
        )
        products = await self._products.create_products(product_rows, user) if plan.new else []
        positions = [serialize_existing_position(item) for item in plan.existing]
        positions.extend(
            serialize_new_position(item, product)
            for item, product in zip(plan.new, products, strict=True)
        )
        state_meta = await self._customer_orders.get_state_meta(TARGET_ORDER_STATUS)
        updated_order = await self._customer_orders.replace_positions_and_state(
            order_id, positions, state_meta
        )

        notification_sent = True
        try:
            await self._notifier.send_group_message(
                format_order_change_message(updated_order, user, plan.summary)
            )
        except Exception:
            logger.warning("Telegram order-change notification failed")
            notification_sent = False
        return OrderChangesResponse(
            order=updated_order,
            changed=True,
            notification_sent=notification_sent,
        )
```

The broad catch is intentionally limited to the notification boundary after a successful save. Do not catch exceptions from reading, product creation, metadata lookup, or order update.

- [ ] **Step 5: Run focused tests and verify GREEN**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_order_changes.py -v
```

Expected: all planner and manager tests PASS; fake call lists prove no external network activity.

- [ ] **Step 6: Commit the orchestration**

```powershell
git add manager/order_changes.py tests/test_order_changes.py
git commit -m "feat: save customer order changes"
```

---

### Task 3: MoySklad adapters and the batch HTTP endpoint

**Files:**
- Modify: `db/repository.py`
- Modify: `manager/moysklad.py`
- Modify: `dependecies/orders.py`
- Modify: `routes/orders.py`
- Modify: `scripts/check.ps1`
- Modify: `tests/test_integrations.py`
- Create: `tests/test_order_changes_api.py`

**Interfaces:**
- Produces: `CustomerOrderManager.get_state_meta(state_name) -> dict`.
- Produces: `CustomerOrderManager.replace_positions_and_state(order_id, positions, state_meta) -> dict`.
- Produces: dependency `get_order_changes_manager()`.
- Produces: authenticated `PUT /api_v1/orders/{order_id}/changes` with `OrderChangesResponse`.
- Produces stable error detail codes `order_not_found`, `order_not_editable`, `order_version_conflict`, and `invalid_order_changes`.

- [ ] **Step 1: Write failing repository behavior tests**

Append to `tests/test_integrations.py`:

```python
class FakeMoySkladResponse:
    def __init__(self, payload=None, status_code=200):
        self.payload = payload or {}
        self.status_code = status_code

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")


@pytest.mark.asyncio
async def test_moysklad_update_omits_transport_link_and_raises_http_errors(monkeypatch):
    calls = []

    def put(url, **kwargs):
        calls.append((url, kwargs["json"]))
        return FakeMoySkladResponse({"id": "order"})

    settings = Settings(
        _env_file=None,
        app_env="test",
        moysklad_login="login",
        moysklad_password="password",
    )
    monkeypatch.setattr(requests, "put", put)
    repository = MoySkladRepository(settings)
    repository.model = "entity/customerorder"

    await repository.update("order", link="/positions/position", quantity=2)

    assert calls[0][0].endswith("/entity/customerorder/order/positions/position")
    assert calls[0][1] == {"quantity": 2}

    monkeypatch.setattr(
        requests,
        "put",
        lambda *args, **kwargs: FakeMoySkladResponse(status_code=503),
    )
    with pytest.raises(requests.HTTPError):
        await repository.update("order", positions=[], state={"meta": {}})
```

- [ ] **Step 2: Write failing batch endpoint tests**

Create `tests/test_order_changes_api.py`:

```python
from types import SimpleNamespace

from fastapi.testclient import TestClient

from config import Settings
from db.schemas.orders import OrderChangesResponse
from dependecies.orders import get_order_changes_manager
from errors import OrderNotAccessible, OrderNotEditable, OrderVersionConflict
from main import create_app
from routes.users import current_user_dependency

ORDER_ID = "00000000-0000-0000-0000-000000000010"
POSITION_ID = "00000000-0000-0000-0000-000000000001"


class StubOrderChangesManager:
    def __init__(self, result=None, error=None):
        self.result = result or OrderChangesResponse(
            order={"id": ORDER_ID, "state": {"name": "Изменен клиентом"}},
            changed=True,
            notification_sent=True,
        )
        self.error = error
        self.calls = []

    async def save_changes(self, user, order_id, request):
        self.calls.append((user, str(order_id), request))
        if self.error:
            raise self.error
        return self.result


def order_changes_client(manager):
    app = create_app(Settings(_env_file=None, app_env="test"))
    user = SimpleNamespace(id="user", moysklad_counterparty_id="counterparty")
    app.dependency_overrides[current_user_dependency] = lambda: user
    app.dependency_overrides[get_order_changes_manager] = lambda: manager
    return TestClient(app), user


def valid_payload():
    return {
        "expected_updated": "2026-08-10 12:00:00.000",
        "positions": [{"id": POSITION_ID, "count": 2}],
    }


def test_batch_endpoint_returns_typed_result_without_live_integrations():
    manager = StubOrderChangesManager()
    client, user = order_changes_client(manager)

    with client:
        response = client.put(f"/api_v1/orders/{ORDER_ID}/changes", json=valid_payload())

    assert response.status_code == 200
    assert response.json()["notification_sent"] is True
    assert manager.calls[0][0] is user
    assert manager.calls[0][1] == ORDER_ID


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (OrderNotAccessible(), 404, "order_not_found"),
        (OrderNotEditable("Принят к исполнению"), 409, "order_not_editable"),
        (OrderVersionConflict(), 409, "order_version_conflict"),
    ],
)
def test_batch_endpoint_maps_domain_errors(error, status_code, code):
    client, _ = order_changes_client(StubOrderChangesManager(error=error))
    with client:
        response = client.put(f"/api_v1/orders/{ORDER_ID}/changes", json=valid_payload())
    assert response.status_code == status_code
    assert response.json()["detail"]["code"] == code


def test_batch_endpoint_rejects_empty_order_before_manager_call():
    manager = StubOrderChangesManager()
    client, _ = order_changes_client(manager)
    payload = {**valid_payload(), "positions": []}
    with client:
        response = client.put(f"/api_v1/orders/{ORDER_ID}/changes", json=payload)
    assert response.status_code == 422
    assert manager.calls == []


def test_batch_endpoint_requires_authentication():
    app = create_app(Settings(_env_file=None, app_env="test"))
    with TestClient(app) as client:
        response = client.put(f"/api_v1/orders/{ORDER_ID}/changes", json=valid_payload())
    assert response.status_code == 401
```

Add the missing `import pytest` at the top of this test file.

- [ ] **Step 3: Run the repository and endpoint tests and verify RED**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_integrations.py tests/test_order_changes_api.py -v
```

Expected: repository assertion fails because `link` is still sent in JSON and HTTP errors are not raised; endpoint collection fails because the dependency and route are absent.

- [ ] **Step 4: Make MoySklad repository failures observable**

In `db/repository.py`, update the methods used by the new flow to keep the current synchronous transport while checking status:

```python
async def read_one(self, id, **kwargs):
    response = requests.get(
        self.base_url + self.model + "/" + str(id) + "?" + kwargs.get("link", ""),
        headers=self._headers(),
    )
    response.raise_for_status()
    return response.json()

async def create_multiply(self, rows: list):
    response = requests.post(self.base_url + self.model, headers=self._headers(), json=rows)
    response.raise_for_status()
    return response.json()

async def read_all(self, filter="", order_by=None, **kwargs):
    response = requests.get(
        self.base_url + self.model + kwargs.get("metadata", "") + "?filter=" + filter,
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
```

Do not print request payloads or credentials.

- [ ] **Step 5: Add concrete CustomerOrder and dependency adapters**

In `manager/moysklad.py`, extend `CustomerOrderManager`:

```python
async def get_state_meta(self, state_name: str) -> dict:
    metadata = await self.get_metadata()
    for state in metadata.get("states", []):
        if state.get("name") == state_name:
            return state["meta"]
    raise RuntimeError("required MoySklad order state is missing")

async def replace_positions_and_state(
    self,
    order_id,
    positions: list[dict],
    state_meta: dict,
):
    await self.__repo.update(
        order_id,
        positions=positions,
        state={"meta": state_meta},
    )
    return await self.get_order_by_id(order_id)
```

The follow-up GET is required because the plain update response is not guaranteed to
contain expanded `positions.rows`; it does not add a second mutation. Refactor existing
`change_state()` to call `get_state_meta()` so status lookup has one implementation.

In `dependecies/orders.py`, add:

```python
from bot.sender import telegram_sender
from manager.moysklad import (
    CustomerOrderManager,
    CustomerOrderRepository,
    ProductManager,
    ProductRepository,
)
from manager.order_changes import OrderChangesManager


async def get_order_changes_manager():
    yield OrderChangesManager(
        CustomerOrderManager(CustomerOrderRepository()),
        ProductManager(ProductRepository()),
        telegram_sender,
    )
```

- [ ] **Step 6: Add the batch route and stable error mapping**

In `routes/orders.py`, import the new schemas, errors, manager, dependency, and
`HTTPException`. While touching the import block, remove the currently unused
`requests`, `UploadFile`, `Form`, `BaseModel`, `ProductFolderCreate`,
`OrderManager`, `OrderItemsManager`, `ProductFolderManager`, and
`dependency_bitrix` imports. Keep the imports used by create/read/export/action
routes. Add:

```python
def order_change_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, OrderNotAccessible):
        return HTTPException(404, detail={"code": "order_not_found", "message": "Order not found"})
    if isinstance(exc, OrderNotEditable):
        return HTTPException(
            409,
            detail={"code": "order_not_editable", "message": "Order is not editable"},
        )
    if isinstance(exc, OrderVersionConflict):
        return HTTPException(
            409,
            detail={"code": "order_version_conflict", "message": "Order was updated"},
        )
    return HTTPException(
        422,
        detail={"code": "invalid_order_changes", "message": str(exc)},
    )


@router.put("/{order_id}/changes", response_model=OrderChangesResponse)
async def save_order_changes(
    order_id: uuid.UUID,
    request: OrderChangesRequest,
    user: User = Depends(current_user_dependency),
    manager: OrderChangesManager = Depends(dependency_orders.get_order_changes_manager),
):
    try:
        return await manager.save_changes(user, order_id, request)
    except (OrderNotAccessible, OrderNotEditable, OrderVersionConflict, InvalidOrderChanges) as exc:
        raise order_change_http_error(exc) from None
```

Place this route before the generic `GET /{order_id}` for readability. The extra `/changes` segment already prevents a route collision.

Rename the handler attached to `PUT /{order_id}/positions/{position_id}` from
`update_order_position` to `update_order_position_count`, and rename the handler
attached to `PUT /{order_id}/positions` from `update_order_position` to
`add_order_positions_legacy`. Do not change either signature, decorator, or body
in this step.

This removes Ruff `F811`; Task 4 replaces both bodies. Reformat the
`dependecies/orders.py` import block as a parenthesized, alphabetized import so
adding it to `$ruffTargets` does not leave the existing `I001` finding.

- [ ] **Step 7: Extend lint targets and verify GREEN**

Add these exact entries to `$ruffTargets` in `scripts/check.ps1`:

```powershell
"db/schemas/orders.py",
"dependecies/orders.py",
"manager/order_changes.py",
"routes/orders.py",
```

Run:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_integrations.py tests/test_order_changes_api.py tests/test_order_changes.py -v
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
```

Expected: focused tests, Ruff, and the complete backend pytest suite PASS without live network requests.

- [ ] **Step 8: Commit the batch backend API**

```powershell
git add db/repository.py manager/moysklad.py dependecies/orders.py routes/orders.py scripts/check.ps1 tests/test_integrations.py tests/test_order_changes_api.py
git commit -m "feat: expose batched order changes"
```

---

### Task 4: Legacy order mutation compatibility through the shared manager

**Files:**
- Modify: `manager/order_changes.py`
- Modify: `routes/orders.py`
- Modify: `tests/test_order_changes.py`
- Modify: `tests/test_order_changes_api.py`

**Interfaces:**
- Produces: `OrderChangesManager.change_quantity(user, order_id, position_id, count)`.
- Produces: `OrderChangesManager.remove_position(user, order_id, position_id)`.
- Produces: `OrderChangesManager.add_positions(user, order_id, order: OrderCreate)`.
- Preserves: response body of existing `PUT /{order_id}/positions/{position_id}`, `DELETE /{order_id}/positions/{position_id}`, and `PUT /{order_id}/positions` as the updated raw order.

- [ ] **Step 1: Write failing manager compatibility tests**

Append to `tests/test_order_changes.py`:

```python
@pytest.mark.asyncio
async def test_legacy_quantity_change_uses_fresh_order_and_shared_save_path():
    orders = StubCustomerOrders()
    notifier = StubNotifier()
    manager = OrderChangesManager(orders, StubProducts(), notifier)

    result = await manager.change_quantity(test_user(), orders.order["id"], POSITION_1, 4)

    assert result.changed is True
    assert len(orders.replacements) == 1
    assert orders.replacements[0][1][0]["quantity"] == 4
    assert len(notifier.messages) == 1


@pytest.mark.asyncio
async def test_legacy_delete_rejects_last_position_and_noneditable_status():
    one_position_order = {**order_payload(), "positions": {"rows": current_rows()[:1]}}
    manager = OrderChangesManager(StubCustomerOrders(one_position_order), StubProducts(), StubNotifier())
    with pytest.raises(InvalidOrderChanges, match="at least one position"):
        await manager.remove_position(test_user(), one_position_order["id"], POSITION_1)

    locked = order_payload(status="Принят к исполнению")
    locked_manager = OrderChangesManager(StubCustomerOrders(locked), StubProducts(), StubNotifier())
    with pytest.raises(OrderNotEditable):
        await locked_manager.change_quantity(test_user(), locked["id"], POSITION_1, 2)


@pytest.mark.asyncio
async def test_legacy_add_positions_creates_every_requested_position_and_notifies_once():
    orders = StubCustomerOrders()
    products = StubProducts()
    notifier = StubNotifier()
    manager = OrderChangesManager(orders, products, notifier)
    additions = OrderCreate(
        order_items=[
            OrderItemCreate(link="https://shop.example/one", count=1, comment=""),
            OrderItemCreate(link="https://shop.example/two", count=2, comment="blue"),
        ]
    )

    result = await manager.add_positions(test_user(), orders.order["id"], additions)

    assert result.changed is True
    assert len(products.orders[0].order_items) == 2
    assert len(orders.replacements[0][1]) == 4
    assert len(notifier.messages) == 1
```

Import `OrderCreate` and `OrderItemCreate` from `db.schemas.orders` in this test module.

- [ ] **Step 2: Write failing legacy route tests**

Extend `StubOrderChangesManager` in `tests/test_order_changes_api.py` with call-recording methods:

```python
async def change_quantity(self, user, order_id, position_id, count):
    self.calls.append(("quantity", user, str(order_id), str(position_id), count))
    if self.error:
        raise self.error
    return self.result

async def remove_position(self, user, order_id, position_id):
    self.calls.append(("remove", user, str(order_id), str(position_id)))
    if self.error:
        raise self.error
    return self.result

async def add_positions(self, user, order_id, order):
    self.calls.append(("add", user, str(order_id), order))
    if self.error:
        raise self.error
    return self.result
```

Append route tests:

```python
@pytest.mark.parametrize(
    ("method", "path", "json_body", "operation"),
    [
        ("put", f"/api_v1/orders/{ORDER_ID}/positions/{POSITION_ID}", 3, "quantity"),
        ("delete", f"/api_v1/orders/{ORDER_ID}/positions/{POSITION_ID}", None, "remove"),
        (
            "put",
            f"/api_v1/orders/{ORDER_ID}/positions",
            {"order_items": [{"link": "https://shop.example/new", "count": 1, "comment": ""}]},
            "add",
        ),
    ],
)
def test_legacy_mutation_routes_use_order_changes_manager(method, path, json_body, operation):
    manager = StubOrderChangesManager()
    client, _ = order_changes_client(manager)
    with client:
        response = getattr(client, method)(path, json=json_body)
    assert response.status_code == 200
    assert response.json()["state"]["name"] == "Изменен клиентом"
    assert manager.calls[0][0] == operation


def test_legacy_mutation_route_maps_locked_status_to_conflict():
    manager = StubOrderChangesManager(error=OrderNotEditable("Принят к исполнению"))
    client, _ = order_changes_client(manager)
    with client:
        response = client.put(
            f"/api_v1/orders/{ORDER_ID}/positions/{POSITION_ID}",
            json=2,
        )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "order_not_editable"
```

- [ ] **Step 3: Run compatibility tests and verify RED**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_order_changes.py tests/test_order_changes_api.py -v
```

Expected: manager tests fail because the three convenience methods are absent; route tests fail because handlers still call `CustomerOrderManager` and `ProductManager` directly.

- [ ] **Step 4: Add shared fresh-order helpers and legacy manager methods**

Refactor `OrderChangesManager` so `save_changes()` delegates to
`_save_loaded_order(user, order_id, order, request)` after one read:

```python
async def save_changes(self, user: User, order_id, request: OrderChangesRequest):
    order = await self._customer_orders.get_order_by_id(order_id)
    if not order or not order.get("id"):
        raise OrderNotAccessible()
    return await self._save_loaded_order(user, order_id, order, request)

async def _save_loaded_order(
    self,
    user: User,
    order_id,
    order: dict,
    request: OrderChangesRequest,
) -> OrderChangesResponse:
    self._validate_context(order, user, request.expected_updated)
    plan = build_order_change_plan(order["positions"]["rows"], request.positions)
    if not plan.summary.changed:
        return OrderChangesResponse(order=order, changed=False, notification_sent=None)

    product_rows = OrderCreate(
        order_items=[
            OrderItemCreate(link=item.link, count=item.count, comment=item.comment)
            for item in plan.new
        ]
    )
    products = await self._products.create_products(product_rows, user) if plan.new else []
    positions = [serialize_existing_position(item) for item in plan.existing]
    positions.extend(
        serialize_new_position(item, product)
        for item, product in zip(plan.new, products, strict=True)
    )
    state_meta = await self._customer_orders.get_state_meta(TARGET_ORDER_STATUS)
    updated_order = await self._customer_orders.replace_positions_and_state(
        order_id, positions, state_meta
    )
    try:
        await self._notifier.send_group_message(
            format_order_change_message(updated_order, user, plan.summary)
        )
        notification_sent = True
    except Exception:
        logger.warning("Telegram order-change notification failed")
        notification_sent = False
    return OrderChangesResponse(
        order=updated_order,
        changed=True,
        notification_sent=notification_sent,
    )
```

Then add the fresh-order helpers and legacy methods:

```python
def _existing_request_rows(order: dict) -> list[ExistingOrderPositionChange]:
    return [
        ExistingOrderPositionChange(id=row["id"], count=int(row["quantity"]))
        for row in order["positions"]["rows"]
    ]


async def _load_for_legacy_change(self, user: User, order_id) -> dict:
    order = await self._customer_orders.get_order_by_id(order_id)
    if not order or not order.get("id"):
        raise OrderNotAccessible()
    self._validate_context(order, user, order["updated"])
    return order


async def change_quantity(self, user: User, order_id, position_id, count: int):
    order = await self._load_for_legacy_change(user, order_id)
    requested = _existing_request_rows(order)
    found = False
    for item in requested:
        if str(item.id) == str(position_id):
            item.count = count
            found = True
    if not found:
        raise InvalidOrderChanges("unknown position id")
    request = OrderChangesRequest(expected_updated=order["updated"], positions=requested)
    return await self._save_loaded_order(user, order_id, order, request)


async def remove_position(self, user: User, order_id, position_id):
    order = await self._load_for_legacy_change(user, order_id)
    requested = [
        item for item in _existing_request_rows(order) if str(item.id) != str(position_id)
    ]
    if len(requested) == len(order["positions"]["rows"]):
        raise InvalidOrderChanges("unknown position id")
    if not requested:
        raise InvalidOrderChanges("order must contain at least one position")
    request = OrderChangesRequest(expected_updated=order["updated"], positions=requested)
    return await self._save_loaded_order(user, order_id, order, request)


async def add_positions(self, user: User, order_id, additions: OrderCreate):
    order = await self._load_for_legacy_change(user, order_id)
    requested = _existing_request_rows(order)
    requested.extend(
        NewOrderPositionChange(link=item.link, count=item.count, comment=item.comment)
        for item in additions.order_items
    )
    request = OrderChangesRequest(expected_updated=order["updated"], positions=requested)
    return await self._save_loaded_order(user, order_id, order, request)
```

Because Pydantic models validate assignment only when configured for it, construct a replacement `ExistingOrderPositionChange` instead of mutating `item.count` if implementation enables `validate_assignment`. The observable contract remains the signatures above.

- [ ] **Step 5: Route all legacy mutations through `OrderChangesManager`**

Replace the bodies and dependencies of the three handlers in `routes/orders.py`:

```python
@router.delete("/{order_id}/positions/{position_id}")
async def delete_order_position(
    order_id: uuid.UUID,
    position_id: uuid.UUID,
    user: User = Depends(current_user_dependency),
    manager: OrderChangesManager = Depends(dependency_orders.get_order_changes_manager),
):
    try:
        return (await manager.remove_position(user, order_id, position_id)).order
    except (OrderNotAccessible, OrderNotEditable, OrderVersionConflict, InvalidOrderChanges) as exc:
        raise order_change_http_error(exc) from None


@router.put("/{order_id}/positions/{position_id}")
async def update_order_position_count(
    order_id: uuid.UUID,
    position_id: uuid.UUID,
    count: int = Body(..., gt=0),
    user: User = Depends(current_user_dependency),
    manager: OrderChangesManager = Depends(dependency_orders.get_order_changes_manager),
):
    try:
        return (await manager.change_quantity(user, order_id, position_id, count)).order
    except (OrderNotAccessible, OrderNotEditable, OrderVersionConflict, InvalidOrderChanges) as exc:
        raise order_change_http_error(exc) from None


@router.put("/{order_id}/positions")
async def add_order_positions(
    order_id: uuid.UUID,
    order: OrderCreate,
    user: User = Depends(current_user_dependency),
    manager: OrderChangesManager = Depends(dependency_orders.get_order_changes_manager),
):
    try:
        return (await manager.add_positions(user, order_id, order)).order
    except (OrderNotAccessible, OrderNotEditable, OrderVersionConflict, InvalidOrderChanges) as exc:
        raise order_change_http_error(exc) from None
```

Remove the old inline product creation and direct Telegram call from the add-position route. Keep create-order, confirmation, cancellation, export, and read endpoints unchanged.

- [ ] **Step 6: Run focused and full backend tests and verify GREEN**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_order_changes.py tests/test_order_changes_api.py -v
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
```

Expected: legacy tests prove every mutation passes through the shared policy; full backend checks PASS.

- [ ] **Step 7: Commit the compatibility layer**

```powershell
git add manager/order_changes.py routes/orders.py tests/test_order_changes.py tests/test_order_changes_api.py
git commit -m "fix: enforce order change workflow on legacy routes"
```

---

### Task 5: Frontend draft model and typed batch API client

**Files:**
- Create: `../pix_frontend_v2/src/app/dashboard/orders/[id]/orderChanges.ts`
- Create: `../pix_frontend_v2/src/app/dashboard/orders/[id]/orderChanges.test.ts`
- Modify: `../pix_frontend_v2/src/routes/routes.tsx`

**Interfaces:**
- Produces: `isOrderEditable(status) -> boolean`.
- Produces: `OrderDraftRow`, `createOrderDraftRows(order)`, `hasOrderChanges(original, current)`, and `buildOrderChangesPayload(expectedUpdated, rows)`.
- Produces: exported `GetOrderType`, `OrderChangesPayload`, `OrderChangesResponse`, and `SaveOrderChangesEndpoint(orderId, payload)`.

- [ ] **Step 1: Write failing draft-model tests**

Create `src/app/dashboard/orders/[id]/orderChanges.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import {
  buildOrderChangesPayload,
  createOrderDraftRows,
  hasOrderChanges,
  isOrderEditable,
} from "./orderChanges";

const order = {
  id: "order-1",
  updated: "2026-08-10 12:00:00.000",
  name: "101",
  state: { name: "Подтвержден менеджером" },
  positions: {
    rows: [
      {
        id: "00000000-0000-0000-0000-000000000001",
        assortment: { name: "Product one", description: "first" },
        quantity: 1,
        shipped: 0,
        price: 10000,
      },
      {
        id: "00000000-0000-0000-0000-000000000002",
        assortment: { name: "Product two", description: "second" },
        quantity: 2,
        shipped: 0,
        price: 20000,
      },
    ],
  },
  purchaseOrders: [],
  invoicesOut: [],
};

describe("isOrderEditable", () => {
  it("allows exactly the four agreed statuses", () => {
    expect([
      "Подтвержден менеджером",
      "Ожидает подтверждения клиента",
      "Подтвержден клиентом",
      "Изменен клиентом",
    ].every(isOrderEditable)).toBe(true);
    expect(isOrderEditable("Принят к исполнению")).toBe(false);
    expect(isOrderEditable("Отменен")).toBe(false);
  });
});

describe("order draft", () => {
  it("detects quantity, removal, and addition changes", () => {
    const original = createOrderDraftRows(order);
    expect(hasOrderChanges(original, original)).toBe(false);
    expect(hasOrderChanges(original, [{ ...original[0], count: 3 }, original[1]])).toBe(true);
    expect(hasOrderChanges(original, [original[0]])).toBe(true);
    expect(
      hasOrderChanges(original, [
        ...original,
        {
          rowKey: "new-1",
          source: "new",
          position: "https://shop.example/new",
          count: 1,
          comment: "black",
          delivered: 0,
          price: 0,
          sum: 0,
        },
      ]),
    ).toBe(true);
  });

  it("builds the complete server payload and rejects an empty draft", () => {
    const original = createOrderDraftRows(order);
    const payload = buildOrderChangesPayload(order.updated, [
      { ...original[0], count: 3 },
      {
        rowKey: "new-1",
        source: "new",
        position: " https://shop.example/new ",
        count: 1,
        comment: "black",
        delivered: 0,
        price: 0,
        sum: 0,
      },
    ]);
    expect(payload).toEqual({
      expected_updated: order.updated,
      positions: [
        { id: "00000000-0000-0000-0000-000000000001", count: 3 },
        { link: "https://shop.example/new", count: 1, comment: "black" },
      ],
    });
    expect(() => buildOrderChangesPayload(order.updated, [])).toThrow(
      "Заказ должен содержать хотя бы одну позицию",
    );
  });
});
```

- [ ] **Step 2: Run the focused unit test and verify RED**

```powershell
npm.cmd run test:unit -- "src/app/dashboard/orders/[id]/orderChanges.test.ts"
```

Expected: FAIL because `orderChanges.ts` does not exist.

- [ ] **Step 3: Implement the pure draft model**

Create `src/app/dashboard/orders/[id]/orderChanges.ts`:

```ts
import type { GetOrderType, OrderChangesPayload } from "@/routes/routes";

const editableStatuses = new Set([
  "Подтвержден менеджером",
  "Ожидает подтверждения клиента",
  "Подтвержден клиентом",
  "Изменен клиентом",
]);

export type OrderDraftRow = {
  rowKey: string;
  source: "existing" | "new";
  positionId?: string;
  position: string;
  count: number;
  comment: string;
  delivered: number;
  price: number;
  sum: number;
};

export function isOrderEditable(status: string): boolean {
  return editableStatuses.has(status);
}

export function createOrderDraftRows(order: GetOrderType): OrderDraftRow[] {
  return order.positions.rows.map((item) => ({
    rowKey: item.id,
    source: "existing",
    positionId: item.id,
    position: item.assortment.name,
    count: item.quantity,
    comment: item.assortment.description ?? "",
    delivered: item.shipped,
    price: item.price / 100,
    sum: (item.price / 100) * item.quantity,
  }));
}

export function hasOrderChanges(
  original: OrderDraftRow[],
  current: OrderDraftRow[],
): boolean {
  if (current.some((row) => row.source === "new")) return true;
  const originalCounts = new Map(
    original.filter((row) => row.source === "existing").map((row) => [row.positionId, row.count]),
  );
  const currentExisting = current.filter((row) => row.source === "existing");
  if (currentExisting.length !== originalCounts.size) return true;
  return currentExisting.some((row) => originalCounts.get(row.positionId) !== row.count);
}

export function buildOrderChangesPayload(
  expectedUpdated: string,
  rows: OrderDraftRow[],
): OrderChangesPayload {
  if (rows.length === 0) throw new Error("Заказ должен содержать хотя бы одну позицию");
  return {
    expected_updated: expectedUpdated,
    positions: rows.map((row) =>
      row.source === "existing"
        ? { id: row.positionId!, count: row.count }
        : { link: row.position.trim(), count: row.count, comment: row.comment },
    ),
  };
}
```

- [ ] **Step 4: Export typed backend contract and API call**

In `src/routes/routes.tsx`, export and extend the existing order types:

```ts
export type OrderPositionRow = {
  assortment: { name: string; description?: string };
  id: string;
  quantity: number;
  shipped: number;
  price: number;
};

export type GetOrderType = {
  id: string;
  updated: string;
  positions: { rows: OrderPositionRow[] };
  state: { name: string };
  name: string;
  purchaseOrders?: any[];
  invoicesOut?: any[];
};

export type OrderChangesPayload = {
  expected_updated: string;
  positions: (
    | { id: string; count: number }
    | { link: string; count: number; comment: string }
  )[];
};

export type OrderChangesResponse = {
  order: GetOrderType;
  changed: boolean;
  notification_sent: boolean | null;
};

export async function SaveOrderChangesEndpoint(
  orderId: string,
  payload: OrderChangesPayload,
) {
  return axios.put<OrderChangesResponse>(
    backendUrl(`orders/${orderId}/changes`),
    payload,
    { headers: { Authorization: getCookie("token") } },
  );
}
```

Keep this function free of `toast.promise`; the page must distinguish success, Telegram warning, version conflict, and locked status instead of collapsing them into one generic message.

- [ ] **Step 5: Run frontend unit tests and verify GREEN**

```powershell
npm.cmd run test:unit -- "src/app/dashboard/orders/[id]/orderChanges.test.ts"
npm.cmd run test:unit
```

Expected: new draft tests and all existing position-link/status-filter tests PASS.

- [ ] **Step 6: Commit the frontend model and client**

Run from `../pix_frontend_v2`:

```powershell
git add "src/app/dashboard/orders/[id]/orderChanges.ts" "src/app/dashboard/orders/[id]/orderChanges.test.ts" src/routes/routes.tsx
git commit -m "feat: model staged order changes"
```

---

### Task 6: Existing-order staged editor and one-save happy path

**Files:**
- Create: `../pix_frontend_v2/src/app/dashboard/orders/[id]/OrderPositionAddForm.tsx`
- Modify: `../pix_frontend_v2/src/components/inputs/pixInputs.tsx`
- Modify: `../pix_frontend_v2/src/app/dashboard/orders/[id]/page.tsx`
- Modify: `../pix_frontend_v2/tests/mock-backend.mjs`
- Create: `../pix_frontend_v2/tests/order-changes.spec.ts`

**Interfaces:**
- Consumes: Task 5 draft helpers and `SaveOrderChangesEndpoint`.
- Produces: accessible add-position form, locally editable grid, `Сохранить изменения`, visible status, and one happy-path batch request.
- Preserves: existing `PositionText`, documents, support chat, operations, export, cancellation, confirmation, and full-screen views.

- [ ] **Step 1: Extend the local mock backend for an editable order**

In `tests/mock-backend.mjs`, add a mutable fixture and request-body reader near the existing constants:

```js
const editableOrder = {
  id: "existing-order",
  updated: "2026-08-10 12:00:00.000",
  positions: {
    rows: [
      {
        id: "00000000-0000-0000-0000-000000000001",
        assortment: { name: "https://shop.example/item", description: "first" },
        quantity: 1,
        shipped: 0,
        price: 10000,
      },
      {
        id: "00000000-0000-0000-0000-000000000002",
        assortment: { name: "Product two", description: "second" },
        quantity: 2,
        shipped: 0,
        price: 20000,
      },
    ],
  },
  state: { name: "Подтвержден менеджером" },
  name: "101",
  purchaseOrders: [],
  invoicesOut: [],
};
```

Retain the existing `readJson()` helper. Change CORS methods to:

```js
"Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
```

Replace the existing-order detail response with `editableOrder`, and add before the final 404:

```js
if (request.method === "PUT" && pathname === "/api_v1/orders/existing-order/changes") {
  const payload = await readJson(request);
  return sendJson(response, {
    order: {
      ...editableOrder,
      updated: "2026-08-10 12:01:00.000",
      state: { name: "Изменен клиентом" },
      positions: {
        rows: [
          {
            ...editableOrder.positions.rows[0],
            quantity: payload.positions[0].count,
          },
          {
            id: "00000000-0000-0000-0000-000000000003",
            assortment: {
              name: payload.positions[1].link,
              description: payload.positions[1].comment,
            },
            quantity: payload.positions[1].count,
            shipped: 0,
            price: 0,
          },
        ],
      },
    },
    changed: true,
    notification_sent: true,
  });
}
```

- [ ] **Step 2: Write the failing happy-path browser test**

Create `tests/order-changes.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

test.beforeEach(async ({ context, page }) => {
  await context.addCookies([
    {
      name: "token",
      value: "Bearer test-token",
      url: "http://127.0.0.1:3100",
    },
  ]);
  await page.routeWebSocket("wss://pixlogistic.com/**", (socket) => socket.close());
});

test("stages add remove and quantity changes then saves once", async ({ page }) => {
  const mutations: { method: string; url: string; body: unknown }[] = [];
  page.on("request", (request) => {
    if (
      ["PUT", "DELETE"].includes(request.method()) &&
      request.url().includes("/orders/existing-order")
    ) {
      mutations.push({
        method: request.method(),
        url: request.url(),
        body: request.postData() ? request.postDataJSON() : null,
      });
    }
  });

  await page.goto("/dashboard/orders/existing-order");
  await expect(page.getByText("Статус: Подтвержден менеджером")).toBeVisible();

  const firstCount = page.locator(
    '.ag-row[row-id="00000000-0000-0000-0000-000000000001"] [col-id="count"]',
  );
  await firstCount.dblclick();
  await firstCount.locator("input").fill("3");
  await firstCount.locator("input").press("Enter");
  await page
    .locator('.ag-row[row-id="00000000-0000-0000-0000-000000000002"]')
    .getByRole("button", { name: "Удалить" })
    .click();

  await page.getByLabel("Позиция").fill("https://shop.example/new");
  await page.getByLabel("Количество").fill("1");
  await page.getByLabel("Комментарий").fill("black");
  await page.getByRole("button", { name: "Добавить позицию" }).click();

  expect(mutations).toHaveLength(0);
  await expect(page.getByRole("button", { name: "Сохранить изменения" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Подтвердить заказ" })).toBeDisabled();

  await page.getByRole("button", { name: "Сохранить изменения" }).click();
  await expect.poll(() => mutations.length).toBe(1);
  expect(mutations[0].method).toBe("PUT");
  expect(mutations[0].url).toContain("/orders/existing-order/changes");
  expect(mutations[0].body).toEqual({
    expected_updated: "2026-08-10 12:00:00.000",
    positions: [
      { id: "00000000-0000-0000-0000-000000000001", count: 3 },
      { link: "https://shop.example/new", count: 1, comment: "black" },
    ],
  });
  await expect(page.getByText("Статус: Изменен клиентом")).toBeVisible();
  await expect(page.getByText("Product two")).toHaveCount(0);
  await expect(page.getByText("https://shop.example/new")).toBeVisible();
});
```

- [ ] **Step 3: Run the browser test and verify RED**

```powershell
npx.cmd playwright test tests/order-changes.spec.ts
```

Expected: FAIL because the current page sends immediate quantity/delete mutations, has no add form, no visible status, and no batch-save button. Confirm the order detail and existing link title still load from the local mock backend.

- [ ] **Step 4: Implement the accessible local add form**

Create `src/app/dashboard/orders/[id]/OrderPositionAddForm.tsx`:

```tsx
"use client";

import { useForm } from "react-hook-form";

import PixButton from "@/components/button/button";
import { PixInput } from "@/components/inputs/pixInputs";

type AddPositionFields = {
  position: string;
  count: number;
  comment: string;
};

export default function OrderPositionAddForm({
  disabled,
  onAdd,
}: {
  disabled: boolean;
  onAdd: (fields: AddPositionFields) => void;
}) {
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<AddPositionFields>({ defaultValues: { count: 1, comment: "" } });

  const submit = handleSubmit((fields) => {
    onAdd({ ...fields, position: fields.position.trim() });
    reset({ position: "", count: 1, comment: "" });
  });

  return (
    <form aria-label="Добавление позиции" onSubmit={submit} className="grid gap-2 lg:grid-cols-4 mb-3">
      <PixInput
        label="Позиция"
        name="position"
        register={register}
        options={{ required: true, validate: (value) => value.trim().length > 0 }}
        error={Boolean(errors.position)}
        disabled={disabled}
      />
      <PixInput
        label="Количество"
        name="count"
        type="number"
        register={register}
        options={{ required: true, valueAsNumber: true, min: 1, validate: Number.isInteger }}
        error={Boolean(errors.count)}
        disabled={disabled}
      />
      <PixInput label="Комментарий" name="comment" register={register} disabled={disabled} />
      <PixButton value="Добавить позицию" type="submit" disabled={disabled} className="self-end" />
    </form>
  );
}
```

Extend the generic `PixInputProps` and `PixInput` in `src/components/inputs/pixInputs.tsx` with optional `disabled?: boolean`, and pass it to `<input disabled={disabled}>`. This is required by the form code above; do not change existing default behavior.

Use these exact additions in the existing generic component. Add the property
to `PixInputProps<T>`:

```tsx
disabled?: boolean;
```

Add the defaulted property to the existing `PixInput` destructuring:

```tsx
disabled = false,
```

Add the attribute to the existing input element before `id={name}`:

```tsx
disabled={disabled}
```

- [ ] **Step 5: Convert the page to a controlled draft**

In `src/app/dashboard/orders/[id]/page.tsx`:

1. Remove imports and calls for `PutPositionCountEndpoint` and `RemovePositionEndpoint`.
2. Import `AxiosError`, `toast`, `OrderPositionAddForm`, `SaveOrderChangesEndpoint`, and the Task 5 helpers.
3. Replace `OrderGrid` with `OrderDraftRow` plus the optional display `id` field if the visual index is retained.
4. Add state for `initialRows`, `updated`, `isSaving`, and the existing `rowData`.
5. Factor the response mapping into one callback used by initial load and save:

```tsx
const applyOrder = useCallback((order: GetOrderType) => {
  const rows = createOrderDraftRows(order);
  setInitialRows(rows);
  setRowData(rows);
  setUpdated(order.updated);
  setName(order.name);
  setState(order.state.name);
}, []);
```

6. Replace `handleEditCount` with local state only:

```tsx
const handleEditCount = (event: CellValueChangedEvent<OrderDraftRow>) => {
  const count = Number(event.newValue);
  if (!Number.isInteger(count) || count <= 0) {
    event.node.setDataValue("count", event.oldValue);
    toast.error("Количество должно быть целым числом больше нуля");
    return;
  }
  setRowData((rows) =>
    rows.map((row) =>
      row.rowKey === event.data.rowKey
        ? { ...row, count, sum: count * row.price }
        : row,
    ),
  );
};
```

7. Add local add/remove callbacks:

```tsx
const handleAddPosition = (fields: { position: string; count: number; comment: string }) => {
  setRowData((rows) => [
    ...rows,
    {
      rowKey: crypto.randomUUID(),
      source: "new",
      position: fields.position,
      count: fields.count,
      comment: fields.comment,
      delivered: 0,
      price: 0,
      sum: 0,
    },
  ]);
};

const handleRemovePosition = (rowKey: string) => {
  setRowData((rows) => {
    if (rows.length === 1) {
      toast.error("Последнюю позицию удалить нельзя. Отмените заказ целиком.");
      return rows;
    }
    return rows.filter((row) => row.rowKey !== rowKey);
  });
};
```

8. Derive edit/dirty flags and save happy path:

```tsx
const canEdit = isOrderEditable(state);
const isDirty = canEdit && hasOrderChanges(initialRows, rowData);

const handleSaveChanges = async () => {
  setIsSaving(true);
  try {
    const response = await SaveOrderChangesEndpoint(
      params.id,
      buildOrderChangesPayload(updated, rowData),
    );
    applyOrder(response.data.order);
    toast.success("Изменения сохранены");
  } finally {
    setIsSaving(false);
  }
};
```

The focused happy-path task may rethrow request errors to the existing Next error overlay; Task 7 replaces that with explicit conflict/upstream handling before full verification.

- [ ] **Step 6: Replace duplicated editable/read-only columns with one definition**

Replace the current `if (state == "Ожидает подтверждения клиента")` column effect with a definition whose `count.editable` is `canEdit` and whose delete column is included only when `canEdit`. Use `rowKey` for `getRowId`:

```tsx
const getRowId = (params: GetRowIdParams<OrderDraftRow>) => params.data.rowKey;
```

The delete renderer must call `handleRemovePosition(props.data!.rowKey)` and must not call an endpoint. Keep `PositionText` as the position renderer.

- [ ] **Step 7: Render status, add form, save controls, and confirmation lock in both layouts**

Above each normal/full-screen grid, render:

```tsx
<p className="font-medium" aria-live="polite">Статус: {state}</p>
{canEdit && (
  <OrderPositionAddForm disabled={isSaving} onAdd={handleAddPosition} />
)}
<PixButton
  value={isSaving ? "Сохраняем..." : "Сохранить изменения"}
  onClick={handleSaveChanges}
  disabled={!isDirty || isSaving}
/>
```

Keep the existing `Подтвердить заказ` button visibility rule unless it already covers another status, but pass `disabled={isDirty || isSaving}`. Keep cancellation behavior unchanged.

- [ ] **Step 8: Run browser, unit, and lint checks and verify GREEN**

```powershell
npm.cmd run test:unit
npx.cmd playwright test tests/order-changes.spec.ts tests/position-link-title.spec.ts
npm.cmd run lint
```

Expected: happy-path order change and existing link-title tests PASS; unit tests PASS; lint introduces no new warning.

- [ ] **Step 9: Commit the staged editor**

```powershell
git add src/components/inputs/pixInputs.tsx "src/app/dashboard/orders/[id]/OrderPositionAddForm.tsx" "src/app/dashboard/orders/[id]/page.tsx" tests/mock-backend.mjs tests/order-changes.spec.ts
git commit -m "feat: stage confirmed order edits"
```

---

### Task 7: Conflict/read-only/Telegram-warning UI, documentation, and final verification

**Files:**
- Modify: `../pix_frontend_v2/src/app/dashboard/orders/[id]/page.tsx`
- Modify: `../pix_frontend_v2/tests/mock-backend.mjs`
- Modify: `../pix_frontend_v2/tests/order-changes.spec.ts`
- Modify: `docs/ARCHITECTURE.md`

**Interfaces:**
- Produces: retained local draft plus explicit reload action for `order_version_conflict`.
- Produces: automatic read-only reload for `order_not_editable`.
- Produces: non-retry warning for `notification_sent: false`.
- Documents: package save flow and four-status allowlist.

- [ ] **Step 1: Add deterministic mock cases**

In `tests/mock-backend.mjs`, derive two additional detail fixtures:

```js
const conflictOrder = { ...editableOrder, id: "conflict-order", name: "102" };
const lockedOrder = {
  ...editableOrder,
  id: "locked-order",
  name: "103",
  state: { name: "Принят к исполнению" },
};
```

Return those fixtures from their detail/action/message paths. Add mutation responses:

```js
if (request.method === "PUT" && pathname === "/api_v1/orders/conflict-order/changes") {
  return sendJson(
    response,
    { detail: { code: "order_version_conflict", message: "Order was updated" } },
    409,
  );
}
if (request.method === "PUT" && pathname === "/api_v1/orders/telegram-warning-order/changes") {
  return sendJson(response, {
    order: {
      ...editableOrder,
      id: "telegram-warning-order",
      updated: "2026-08-10 12:02:00.000",
      state: { name: "Изменен клиентом" },
    },
    changed: true,
    notification_sent: false,
  });
}
```

Also return an editable detail fixture for `telegram-warning-order` and empty action/message arrays for all three added ids.

- [ ] **Step 2: Write failing error-state browser tests**

Append to `tests/order-changes.spec.ts`:

```ts
test("keeps a stale draft until the client explicitly reloads", async ({ page }) => {
  await page.goto("/dashboard/orders/conflict-order");
  const firstCount = page.locator(
    '.ag-row[row-id="00000000-0000-0000-0000-000000000001"] [col-id="count"]',
  );
  await firstCount.dblclick();
  await firstCount.locator("input").fill("3");
  await firstCount.locator("input").press("Enter");
  await page.getByRole("button", { name: "Сохранить изменения" }).click();

  const alert = page.getByRole("alert");
  await expect(alert).toContainText("Заказ был изменён магазином");
  await expect(firstCount).toHaveText("3");
  await alert.getByRole("button", { name: "Загрузить актуальный заказ" }).click();
  await expect(firstCount).toHaveText("1");
});


test("shows operational statuses as read only", async ({ page }) => {
  await page.goto("/dashboard/orders/locked-order");
  await expect(page.getByText("Статус: Принят к исполнению")).toBeVisible();
  await expect(page.getByRole("button", { name: "Добавить позицию" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Сохранить изменения" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Удалить" })).toHaveCount(0);
});


test("warns about Telegram without offering to resave an already saved order", async ({ page }) => {
  await page.goto("/dashboard/orders/telegram-warning-order");
  const firstCount = page.locator(
    '.ag-row[row-id="00000000-0000-0000-0000-000000000001"] [col-id="count"]',
  );
  await firstCount.dblclick();
  await firstCount.locator("input").fill("3");
  await firstCount.locator("input").press("Enter");
  await page.getByRole("button", { name: "Сохранить изменения" }).click();

  await expect(page.getByRole("alert")).toContainText(
    "Заказ сохранён, но Telegram-уведомление не отправлено",
  );
  await expect(page.getByRole("button", { name: "Сохранить изменения" })).toBeDisabled();
  await expect(page.getByText("Статус: Изменен клиентом")).toBeVisible();
});
```

- [ ] **Step 3: Run error-state tests and verify RED**

```powershell
npx.cmd playwright test tests/order-changes.spec.ts
```

Expected: happy path remains green; the three new tests fail because the page has no persistent alert/reload branch and does not distinguish `notification_sent: false`.

- [ ] **Step 4: Add typed error-code extraction and persistent banners**

In `page.tsx`, add state:

```tsx
type OrderAlert =
  | { kind: "version-conflict"; message: string }
  | { kind: "telegram-warning"; message: string }
  | null;

const [orderAlert, setOrderAlert] = useState<OrderAlert>(null);
```

Factor the existing initial `GetOrder` body into `loadOrder()` and use it from the effect and reload button. Replace the save handler catch/success branches:

```tsx
const handleSaveChanges = async () => {
  setIsSaving(true);
  setOrderAlert(null);
  try {
    const response = await SaveOrderChangesEndpoint(
      params.id,
      buildOrderChangesPayload(updated, rowData),
    );
    applyOrder(response.data.order);
    if (response.data.notification_sent === false) {
      setOrderAlert({
        kind: "telegram-warning",
        message: "Заказ сохранён, но Telegram-уведомление не отправлено.",
      });
    } else {
      toast.success("Изменения сохранены");
    }
  } catch (error) {
    const code =
      error instanceof AxiosError
        ? error.response?.data?.detail?.code
        : undefined;
    if (code === "order_version_conflict") {
      setOrderAlert({
        kind: "version-conflict",
        message: "Заказ был изменён магазином. Ваши правки пока сохранены на странице.",
      });
    } else if (code === "order_not_editable") {
      toast.error("Статус заказа больше не позволяет редактирование");
      await loadOrder();
    } else {
      toast.error("Не удалось сохранить изменения");
    }
  } finally {
    setIsSaving(false);
  }
};
```

Render directly above the grid in both layouts:

```tsx
{orderAlert && (
  <div role="alert" className="mb-3 rounded border border-amber-400 bg-amber-50 p-3">
    <span>{orderAlert.message}</span>
    {orderAlert.kind === "version-conflict" && (
      <button className="ml-3 underline" onClick={loadOrder}>
        Загрузить актуальный заказ
      </button>
    )}
  </div>
)}
```

When `loadOrder()` succeeds, clear the conflict alert before applying the fresh order. Do not clear a Telegram warning until navigation or the next explicit edit/save cycle.

- [ ] **Step 5: Document the route and lifecycle boundary**

Update the Orders row and REST flow in `docs/ARCHITECTURE.md` with:

```markdown
Customer edits are staged in the browser and saved through
`PUT /api_v1/orders/{id}/changes`. The backend accepts edits only in
`Подтвержден менеджером`, `Ожидает подтверждения клиента`,
`Подтвержден клиентом`, or `Изменен клиентом`, verifies the owner and
`expected_updated`, then replaces positions and sets `Изменен клиентом` in one
MoySklad order update. Telegram is attempted after the save; a notification
failure is reported separately and does not invite the client to resubmit the
order mutation.
```

Keep the route table concise by adding `/{id}/changes` to the existing Orders path list rather than creating a new route group.

- [ ] **Step 6: Run final backend verification after the documentation edit**

From `pix_backend`:

```powershell
git diff --check
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
& ".\.venv\Scripts\python.exe" -c "import main"
```

Expected: diff check, Ruff, all pytest tests, and a fresh `main` import PASS. No migration command is run.

- [ ] **Step 7: Run final frontend verification after the final UI edit**

From `../pix_frontend_v2`:

```powershell
npm.cmd run lint
npm.cmd run test:unit
npx.cmd playwright test tests/order-changes.spec.ts tests/position-link-title.spec.ts
npm.cmd run check
```

Expected: lint, API URL guard, all unit tests, production build, and all Playwright tests PASS. Existing documented hook warnings may remain; the changed order page must not add a new warning. If the build alone cannot download Google Fonts in a restricted network, retain the successful lint/unit/browser results and report the exact font-download blocker.

- [ ] **Step 8: Review both repositories for scope and secrets**

```powershell
git status --short
git diff --check
git diff -- routes/orders.py manager/order_changes.py manager/moysklad.py db/repository.py db/schemas/orders.py dependecies/orders.py errors.py scripts/check.ps1 tests docs/ARCHITECTURE.md
git -C ..\pix_frontend_v2 status --short
git -C ..\pix_frontend_v2 diff --check
git -C ..\pix_frontend_v2 diff -- src/routes/routes.tsx "src/app/dashboard/orders/[id]" src/components/inputs/pixInputs.tsx tests
```

Confirm that diffs contain no `.env` values, tokens, chat ids, credentials, production URLs beyond existing public order links, migration changes, scheduler changes, or unrelated refactors.

- [ ] **Step 9: Commit final error handling and documentation in their owning repositories**

From `../pix_frontend_v2`:

```powershell
git add "src/app/dashboard/orders/[id]/page.tsx" tests/mock-backend.mjs tests/order-changes.spec.ts
git commit -m "fix: handle order edit conflicts"
```

From `pix_backend`:

```powershell
git add docs/ARCHITECTURE.md
git commit -m "docs: document customer order changes"
```

- [ ] **Step 10: Record the final evidence**

```powershell
git log --oneline -8
git status --short
git -C ..\pix_frontend_v2 log --oneline -8
git -C ..\pix_frontend_v2 status --short
```

Expected: both worktrees are clean, the backend log contains the domain/API/compatibility/docs commits, the frontend log contains draft/editor/conflict commits, and the verification output used for completion comes from runs after the final edits.
