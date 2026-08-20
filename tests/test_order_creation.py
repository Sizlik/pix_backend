from types import SimpleNamespace
from uuid import UUID

import pytest

from db.schemas.orders import CheckoutOrderCreate
from errors import AddressNotFound
from manager.addresses import DeliveryAddressSnapshot
from manager.order_creation import OrderCreationManager, checkout_fingerprint

ADDRESS_ID = UUID("00000000-0000-0000-0000-000000000010")
IDEMPOTENCY_KEY = UUID("00000000-0000-0000-0000-000000000020")
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
        self.sync_ids = None

    async def create_products(self, request, user, sync_ids=None):
        self.events.append("products:create")
        self.sync_ids = sync_ids
        if self.error:
            raise self.error
        return [{"meta": {"href": "product-meta"}}]


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


class StubIdempotency:
    def __init__(self, cached=None):
        self.cached = cached
        self.calls = []

    async def run(self, user_id, key, fingerprint, operation):
        self.calls.append((user_id, key, fingerprint))
        if self.cached is not None:
            return self.cached, False
        return await operation(), True


@pytest.mark.asyncio
async def test_order_creation_validates_address_before_products_and_marks_only_after_order():
    events = []
    addresses = StubAddresses(events)
    products = StubProducts(events)
    orders = StubCustomerOrders(events)
    result = await OrderCreationManager(
        addresses,
        products,
        orders,
        StubIdempotency(),
    ).create(make_request(), make_user(), IDEMPOTENCY_KEY)
    assert result["id"] == "moysklad-order"
    assert events == [
        "address:get",
        "products:create",
        "order:create",
        "address:mark",
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
        StubIdempotency(),
    )
    with pytest.raises(AddressNotFound):
        await manager.create(make_request(), make_user(), IDEMPOTENCY_KEY)
    assert events == ["address:get"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_stage", ["products", "order"])
async def test_external_failure_does_not_mark_address(failing_stage):
    events = []
    error = RuntimeError("external unavailable")
    products = StubProducts(
        events, error=error if failing_stage == "products" else None
    )
    orders = StubCustomerOrders(
        events, error=error if failing_stage == "order" else None
    )
    manager = OrderCreationManager(
        StubAddresses(events),
        products,
        orders,
        StubIdempotency(),
    )
    with pytest.raises(RuntimeError):
        await manager.create(make_request(), make_user(), IDEMPOTENCY_KEY)
    assert "address:mark" not in events


@pytest.mark.asyncio
async def test_address_mark_failure_does_not_turn_created_order_into_failure():
    events = []
    error = RuntimeError("secondary unavailable")
    manager = OrderCreationManager(
        StubAddresses(events, mark_error=error),
        StubProducts(events),
        StubCustomerOrders(events),
        StubIdempotency(),
    )
    result = await manager.create(make_request(), make_user(), IDEMPOTENCY_KEY)
    assert result["id"] == "moysklad-order"


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
    )

    assert await manager.create(
        make_request(), make_user(), IDEMPOTENCY_KEY
    ) == cached
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
