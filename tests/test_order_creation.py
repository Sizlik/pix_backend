from types import SimpleNamespace
from uuid import UUID

import pytest

from db.schemas.orders import CheckoutOrderCreate
from errors import AddressNotFound
from manager.addresses import DeliveryAddressSnapshot
from manager.order_creation import OrderCreationManager, build_new_order_message

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
    return CheckoutOrderCreate(
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
        return {
            "id": "moysklad-order",
            "meta": {"uuidHref": "https://moysklad/order"},
        }


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
    assert events == [
        "address:get",
        "products:create",
        "order:create",
        "address:mark",
        "notify",
    ]
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
    products = StubProducts(
        events, error=error if failing_stage == "products" else None
    )
    orders = StubCustomerOrders(
        events, error=error if failing_stage == "order" else None
    )
    manager = OrderCreationManager(
        StubAddresses(events), products, orders, StubNotifier(events)
    )
    with pytest.raises(RuntimeError):
        await manager.create(make_request(), make_user())
    assert "address:mark" not in events
    assert "notify" not in events


@pytest.mark.asyncio
@pytest.mark.parametrize("secondary_failure", ["mark", "notify"])
async def test_secondary_failure_does_not_turn_created_order_into_failure(
    secondary_failure,
):
    events = []
    error = RuntimeError("secondary unavailable")
    manager = OrderCreationManager(
        StubAddresses(
            events, mark_error=error if secondary_failure == "mark" else None
        ),
        StubProducts(events),
        StubCustomerOrders(events),
        StubNotifier(
            events, error=error if secondary_failure == "notify" else None
        ),
    )
    result = await manager.create(make_request(), make_user())
    assert result["id"] == "moysklad-order"


def test_order_notification_escapes_user_name():
    user = SimpleNamespace(first_name="<Иван>", name_id=7)
    message = build_new_order_message(
        {"meta": {"uuidHref": "https://moysklad/order"}}, user
    )
    assert "&lt;Иван&gt;" in message
    assert "<Иван>" not in message
    assert 'href="https://moysklad/order"' in message
