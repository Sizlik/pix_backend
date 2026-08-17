from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import ValidationError

from db.schemas.orders import (
    ExistingOrderPositionChange,
    NewOrderPositionChange,
    OrderChangesRequest,
    OrderChangesResponse,
    OrderCreate,
    OrderItemCreate,
)
from errors import (
    InvalidOrderChanges,
    OrderNotAccessible,
    OrderNotEditable,
    OrderVersionConflict,
)
from manager.order_changes import (
    OrderChangesManager,
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
            NewOrderPositionChange(
                link="https://shop.example/item", count=1, comment="black"
            ),
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


def order_payload(
    status="Подтвержден менеджером", updated="2026-08-10 12:00:00.000"
):
    return {
        "id": "00000000-0000-0000-0000-000000000010",
        "name": "101",
        "updated": updated,
        "state": {"name": status},
        "agent": {
            "meta": {
                "href": (
                    "https://api.moysklad.ru/counterparty/"
                    "00000000-0000-0000-0000-000000000020"
                )
            }
        },
        "meta": {
            "uuidHref": "https://online.moysklad.ru/app/#customerorder/edit?id=order"
        },
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
        return [
            {"meta": {"href": "https://api.moysklad.ru/product/new"}}
            for _ in order.order_items
        ]


class StubNotifier:
    def __init__(self, result=True, error=None):
        self.result = result
        self.error = error
        self.messages = []

    async def send_group_message(self, text):
        if self.error:
            raise self.error
        self.messages.append(text)
        return self.result


def make_user():
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
            NewOrderPositionChange(
                link="https://shop.example/item", count=1, comment="black"
            ),
        ],
    )

    result = await manager.save_changes(make_user(), orders.order["id"], request)

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
        "assortment": {
            "meta": {"href": "https://api.moysklad.ru/product/new"}
        },
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

    result = await manager.save_changes(make_user(), orders.order["id"], request)

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
        (
            {
                **order_payload(),
                "agent": {
                    "meta": {
                        "href": "https://api.moysklad.ru/counterparty/other"
                    }
                },
            },
            OrderNotAccessible,
        ),
    ],
)
async def test_manager_rejects_status_version_and_owner_before_side_effects(
    order, expected_error
):
    orders = StubCustomerOrders(order)
    products = StubProducts()
    notifier = StubNotifier()
    manager = OrderChangesManager(orders, products, notifier)
    request = OrderChangesRequest(
        expected_updated="2026-08-10 12:00:00.000",
        positions=[ExistingOrderPositionChange(id=POSITION_1, count=2)],
    )

    with pytest.raises(expected_error):
        await manager.save_changes(make_user(), order["id"], request)

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
        await OrderChangesManager(
            failed_orders, StubProducts(), notifier
        ).save_changes(make_user(), failed_orders.order["id"], request)
    assert notifier.messages == []

    orders = StubCustomerOrders()
    result = await OrderChangesManager(
        orders,
        StubProducts(),
        StubNotifier(error=RuntimeError("telegram unavailable")),
    ).save_changes(make_user(), orders.order["id"], request)
    assert result.changed is True
    assert result.notification_sent is False


@pytest.mark.asyncio
async def test_false_notification_result_is_reported_after_saved_order_change():
    request = OrderChangesRequest(
        expected_updated="2026-08-10 12:00:00.000",
        positions=[ExistingOrderPositionChange(id=POSITION_1, count=2)],
    )
    orders = StubCustomerOrders()

    result = await OrderChangesManager(
        orders,
        StubProducts(),
        StubNotifier(result=False),
    ).save_changes(make_user(), orders.order["id"], request)

    assert result.changed is True
    assert result.notification_sent is False
    assert len(orders.replacements) == 1


@pytest.mark.asyncio
async def test_legacy_quantity_change_uses_fresh_order_and_shared_save_path():
    orders = StubCustomerOrders()
    notifier = StubNotifier()
    manager = OrderChangesManager(orders, StubProducts(), notifier)

    result = await manager.change_quantity(
        make_user(), orders.order["id"], POSITION_1, 4
    )

    assert result.changed is True
    assert len(orders.replacements) == 1
    assert orders.replacements[0][1][0]["quantity"] == 4
    assert len(notifier.messages) == 1


@pytest.mark.asyncio
async def test_legacy_delete_rejects_last_position_and_noneditable_status():
    one_position_order = {
        **order_payload(),
        "positions": {"rows": current_rows()[:1]},
    }
    manager = OrderChangesManager(
        StubCustomerOrders(one_position_order), StubProducts(), StubNotifier()
    )
    with pytest.raises(InvalidOrderChanges, match="at least one position"):
        await manager.remove_position(
            make_user(), one_position_order["id"], POSITION_1
        )

    locked = order_payload(status="Принят к исполнению")
    locked_manager = OrderChangesManager(
        StubCustomerOrders(locked), StubProducts(), StubNotifier()
    )
    with pytest.raises(OrderNotEditable):
        await locked_manager.change_quantity(
            make_user(), locked["id"], POSITION_1, 2
        )


@pytest.mark.asyncio
async def test_legacy_add_positions_creates_every_requested_position_and_notifies_once():
    orders = StubCustomerOrders()
    products = StubProducts()
    notifier = StubNotifier()
    manager = OrderChangesManager(orders, products, notifier)
    additions = OrderCreate(
        order_items=[
            OrderItemCreate(link="https://shop.example/one", count=1, comment=""),
            OrderItemCreate(
                link="https://shop.example/two", count=2, comment="blue"
            ),
        ]
    )

    result = await manager.add_positions(
        make_user(), orders.order["id"], additions
    )

    assert result.changed is True
    assert len(products.orders[0].order_items) == 2
    assert len(orders.replacements[0][1]) == 4
    assert len(notifier.messages) == 1
